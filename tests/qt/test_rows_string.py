"""W3.1a package D: the string on Current's one-line row (the planning folder's `docs/agent instructions/3.0/W3.1a-current/
RUNBOOK.md` §1 *Rows*, *The string*, *Up Next*, *Top-20 line*, *Soon line*; §3 B3), on the synthetic seed through the
stand-in store, offscreen.

What a wrong answer would cost a learner:
  * a stone that changed (a file watched, in Anki, joining, its video removed) and a row still showing the old string —
    or every row on screen drawn again for it, a list that stutters each time Anki makes a card (B3);
  * a row painted before the stones arrived left without them for good;
  * one row's string pushed into its Anki count because the title width was picked from the wrong row;
  * 95 % shown in the warning colour (93–96 is plain ink, S11);
  * a click on a stone that does something other than Up Next's ✓ Done (one rule for a Done, S12);
  * a hover that repaints the whole screen while its springs run;
  * a groove too thin to point at (S10), or Finished's rows changed by Current's new look (S5).
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QPointF, QRect, Qt
from PyQt6.QtGui import QColor, QImage, QMouseEvent, QPainter
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app import theme
from app.qt import freeze, rows, stones, strings, style
from app.services import stone_plan, view_rows
from tests.qt.conftest import wait_until
from tests.qt.pixels import count, rgb_array
from tests.qt.test_current import _stones_sheet, current, part, seeded   # noqa: F401  (fixtures)


def _closed_on_screen(lst, need=2):
    """A closed Current row fully on screen whose neighbours are rows too, holding at least `need` files: its index."""
    entries, vp = lst.model().entries, lst.viewport().rect()
    for i, (kind, row, _l) in enumerate(entries):
        if (kind == rows.ROW and 0 < i < len(entries) - 1 and entries[i - 1][0] == rows.ROW and
                entries[i + 1][0] == rows.ROW and len(row.episodes) >= need and row.key != lst.model().open_key and
                vp.contains(lst.visualRect(lst.model().index(i + 1, 0)))):
            return i
    raise AssertionError("no closed row on screen to test with")


def _paint_spy(lst, monkeypatch):
    """Record the entry index of every row the list paints (and still paint it)."""
    painted = []
    real = lst.delegate.paint
    monkeypatch.setattr(lst.delegate, "paint", lambda p, option, index: (painted.append(index.row()),
                                                                         real(p, option, index))[1])
    return painted


def _settle(n=20):
    for _ in range(n):
        QApplication.processEvents()


def _change_shows_on_that_row_alone(seed, win, monkeypatch, pick, change, *, check):
    """B3: one stone change → that row alone rebuilt, repainted, and drawn afresh once; its string shows the change.
    `pick(row)` -> the episode to change (or None); `change(seed, row, ep)` commits it; `check(old_plan, new_plan, ep)`."""
    lst = current(win)
    lst.viewport().repaint()
    assert wait_until(lambda: not lst._warm.isActive())               # the list has rested: nothing else is pending
    model = lst.model()
    i = next(n for n in range(len(model.entries)) if model.entries[n][0] == rows.ROW and
             model.entries[n][1].key != model.open_key and pick(model.entries[n][1]) is not None and
             lst.viewport().rect().contains(lst.visualRect(model.index(n, 0))))
    row = model.entries[i][1]
    ep = pick(row)
    old_plan = stone_plan.plan_of(row)
    painted = _paint_spy(lst, monkeypatch)
    renders = lst.delegate.renders
    change(seed, row, ep)
    assert wait_until(lambda: model.entries[i][1] is not row, 10)
    _settle()
    new = model.entries[i][1]
    assert new.key == row.key
    assert model.changed == [i], model.changed                        # rebuilt: that row alone
    assert sorted(set(painted)) == [i], sorted(set(painted))          # repainted: that row alone
    assert lst.delegate.renders == renders + 1                        # drawn afresh: once, that row
    check(old_plan, stone_plan.plan_of(new), ep)


# --- B3: one test per stone change ------------------------------------------------------------------------------------
def test_a_file_watched_repaints_its_row_alone_and_its_stone_is_cut(seeded, monkeypatch):
    seed, win = seeded(size=(1280, 1100))

    def check(old, new, ep):
        assert old.watched + 1 == new.watched                         # the string says one more watched

    _change_shows_on_that_row_alone(
        seed, win, monkeypatch, lambda row: next((e for e in row.episodes if not e.watched), None)
        if len(row.episodes) >= 2 else None,
        lambda seed, row, ep: seed.library.commit(items=[{"id": ep.id, "watched": 1}]), check=check)


def test_a_file_put_in_anki_repaints_its_row_alone_and_its_stone_turns_raw(seeded, monkeypatch):
    seed, win = seeded(size=(1280, 1100))

    def change(seed, row, ep):
        seed.library._cards[ep.id] = [8_000_000 + ep.id * 100 + c for c in range(5)]     # Anki made five cards
        seed.library.commit(items=[{"id": ep.id, "mined_at": "2026-10-14T09:00:00Z"}])

    def check(old, new, ep):
        assert old.in_anki + 1 == new.in_anki                         # the string says one more in Anki

    _change_shows_on_that_row_alone(
        seed, win, monkeypatch, lambda row: next((e for e in row.episodes if not e.cards and not e.watched and
                                                  not e.missing), None) if len(row.episodes) >= 2 else None,
        change, check=check)


def test_a_file_joining_a_row_repaints_that_row_alone_and_its_string_grows(seeded, monkeypatch):
    """A file joining a closed row keeps it one line (a "same" refresh, no relayout), and its string gains a stone."""
    seed, win = seeded(size=(1280, 1100))

    def change(seed, row, ep):
        last = next(r for r in seed.items if r["id"] == ep.id)
        seed.library.commit(items=[dict(last, id=10 ** 6, ord=last["ord"] + 0.5, rel_path=last["rel_path"][:-4] +
                                        "b.srt", title="追加 - 99.srt", availability="missing", watched=0,
                                        mined_at=None)], order=True, availability=True)

    def check(old, new, ep):
        assert new.n == old.n + 1                                     # one stone more

    _change_shows_on_that_row_alone(
        seed, win, monkeypatch, lambda row: row.episodes[-1] if len(row.episodes) >= 2 and row.media != "youtube"
        else None, change, check=check)


def test_a_mined_files_video_removed_repaints_its_row_alone_and_its_stone_is_marked(seeded, monkeypatch):
    seed, win = seeded(size=(1280, 1100))

    def change(seed, row, ep):
        seed.library.commit(items=[{"id": ep.id, "availability": "missing"}], availability=True)

    def check(old, new, ep):
        marked = lambda plan: sum(1 for it in plan.items if it.kind == "stone" and it.removed)
        assert marked(new) == marked(old) + 1                         # its stone carries the removed mark

    _change_shows_on_that_row_alone(
        seed, win, monkeypatch, lambda row: next((e for e in row.episodes if e.cards and not e.missing and
                                                  not e.in_top), None) if len(row.episodes) >= 2 else None,
        change, check=check)                     # (below the top-20 line: a file in it leaving moves the line itself)


def test_a_row_painted_before_the_sheet_arrived_is_painted_again_once_when_it_lands(seeded, monkeypatch):
    """Until the stones' sheet is drawn (on a worker, at the window's first paint) the rows paint without their stones;
    when it lands every such picture is let go and painted again — once: a second word that a sheet landed paints
    nothing."""
    key = stones._key(1.0, "M")
    stones._SHEETS.pop(key, None)
    stones._BUILDING[key] = []                     # a build in flight: the window asks, and waits for it
    try:
        seed, win = seeded()
        lst = current(win)
        lst.viewport().repaint()
        sprites = lst.delegate._sprites["row"]
        unsheeted = [k for k in sprites if k[0] == rows.ROW and k[7] is not None and k[7][-1] is False]
        assert unsheeted, "the rows were painted with the sheet already there, so the test would prove nothing"
        on_screen = sum(1 for i, e in enumerate(lst.model().entries) if e[0] == rows.ROW and
                        lst.visualRect(lst.model().index(i, 0)).intersects(lst.viewport().rect()))
        renders = lst.delegate.renders
        stones._landed(key, stones.build(*key))
        _settle()
        assert lst.delegate.renders - renders == on_screen + 1      # each row on screen once, and Up Next (its string)
        assert not [k for k in lst.delegate._sprites["row"] if k[7] is not None and k[7][-1] is False]
        renders, paints = lst.delegate.renders, lst.delegate.paints
        stones.notifier().ready.emit(key)                           # the word again: nothing left to paint
        _settle()
        assert lst.delegate.renders == renders and lst.delegate.paints == paints
    finally:
        stones._BUILDING.pop(key, None)
        if key not in stones._SHEETS:
            stones._landed(key, stones.build(*key))


# --- the one title width -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("size", ["M", "L"])
def test_the_one_title_width_leaves_every_rows_string_room_at_its_tightest(qapp, seeded, size):
    """One title width for every row (`title_w`), picked from the row shortest of room: every closed row's string fits
    its room at its tightest (now or after its next fuse), unless the title is at its floor — and the title is no
    narrower than that row needs (one px more and it would be short)."""
    seed, win = seeded(files=400, size=(1024, 800))
    lst = current(win)
    theme_name, _size, language = style.current()
    style.apply(qapp, theme_name, size, language)
    try:
        d = lst.delegate
        f = rows.fz()
        width = lst.visualRect(lst.model().index(1, 0)).width()
        tw = d.title_w(width)
        floor, base = round(80 * f), round(187 * f)
        slack = []
        for kind, row, _l in lst.model().entries:
            if kind != rows.ROW:
                continue
            g = d.line_geometry(row, QRect(0, 0, width, d._line_h()), tw)
            plan = stone_plan.plan_of(row)
            need = max(stone_plan.tightest(plan), stone_plan.ahead(plan))
            slack.append(g["gstr"].width() - need)
        assert slack
        if tw > floor:
            assert min(slack) >= -1, (min(slack), tw)                  # no row's string is short of room
        if floor < tw < base:
            assert min(slack) < 2, (min(slack), tw)                    # narrowed exactly as far as the worst row needs
        assert len({d.line_geometry(row, QRect(0, 0, width, d._line_h()))["main"].width()
                    for kind, row, _l in lst.model().entries if kind == rows.ROW}) == 1
    finally:
        style.apply(qapp, theme_name, "M", language)


# --- the % bands --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("pct, ink", [(97, "ok"), (99.6, "ok"), (96, "ink"), (93, "ink"), (92.4, "warn"), (80, "warn")])
def test_the_known_share_takes_its_band_colour(qapp, pct, ink):
    """S11: ≥ 97 % in the learned green, 93–96 in plain ink (never the warning), < 93 in the warning amber."""
    img = QImage(300, 30, QImage.Format.Format_RGB32)
    img.fill(rows.c("surface"))
    p = QPainter(img)
    try:
        rows.paint_diff(p, pct, view_rows.pct_tone(pct), 12, 296, 15, 1.0)
    finally:
        p.end()
    arr = rgb_array(img)
    col = style.colours()
    found = {name: count(arr, col[name], tolerance=30) for name in ("ok", "ink", "warn")}
    assert found[ink] > 5, found
    for other in {"ok", "warn"} - {ink}:
        assert found[other] == 0, (other, found)


# --- one rule for a Done ------------------------------------------------------------------------------------------------
def test_every_done_wherever_it_is_clicked_goes_through_the_pages_one_path(seeded):
    """S12: a click on a row's stone, on Up Next's stone or its ✓ Done, or on an open row's episode stone asks the page
    for a Done (`CurrentPage.done` → its `on_done` hook, package F's writer, toast and Undo): the same call each time,
    with the row and the file. A stone click never opens or closes the row."""
    seed, win = seeded(size=(1280, 1100))
    page = win.page_widgets["current"]
    lst = page.list
    got = []
    page.on_done = lambda row, ep: got.append((row.key, ep.id))
    i = _closed_on_screen(lst, need=2)
    row = lst.model().entries[i][1]
    stone = part(lst, i, "stone")[0]
    QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=stone[1].center())
    assert got == [(row.key, stone[3].id)] and lst.model().open_key is None
    hero = lst.model().entries[0][1]
    for name in ("stone", "done"):
        p = part(lst, 0, name)[0]
        QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=p[1].center())
        assert got[-1] == (hero.key, p[3].id), name
    lst.toggle(lst.model().index(i, 0))
    lst.doItemsLayout()
    QApplication.processEvents()
    ep_stone = part(lst, i, "stone")[-1]
    QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=ep_stone[1].center())
    assert got[-1] == (row.key, ep_stone[3].id) and lst.model().open_key == row.key
    assert len(got) == 4
    page.on_done = None
    QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=ep_stone[1].center())   # no hook: nothing happens
    assert len(got) == 4


def test_the_mine_now_button_says_when_it_arrives_and_no_video_names_link_and_mine_text(seeded):
    """Waiting's icon is the Mine now button: hit-tested, and its click says it arrives with Anki Miner's step (a tip,
    no toast). No video shows a warning whose tip names Link… · Mine text."""
    seed, win = seeded(size=(1280, 1100))
    lst = current(win)
    entries = lst.model().entries
    i = next(n for n, e in enumerate(entries) if e[0] == rows.ROW and e[1].status.kind == "waiting")
    lst.scrollTo(lst.model().index(i, 0), lst.ScrollHint.PositionAtTop)
    QApplication.processEvents()
    mine = part(lst, i, "mine-now")[0]
    toasts = [w for w in QApplication.topLevelWidgets() if w.isVisible()]
    QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=mine[1].center())
    assert wait_until(lambda: win.tooltips.showing() == strings.ROWS_MINE_NOW_LATER)
    assert lst.model().open_key is None
    assert [w for w in QApplication.topLevelWidgets() if w.isVisible() and w not in toasts and
            "toast" in w.objectName().lower()] == []
    k = next(n for n, e in enumerate(entries) if e[0] == rows.ROW and e[1].status.kind == "no_media")
    warn = part(lst, k, "status")[0]
    assert "Link… · Mine text" in warn[2]


# --- hover ---------------------------------------------------------------------------------------------------------------
def test_a_hover_repaints_the_hovered_row_and_its_two_neighbours_alone_while_the_springs_run(seeded, monkeypatch):
    """§3: the hovered row lifts and its neighbours ease apart on springs; while they run, those three rows are
    repainted and nothing else — and the springs do run (several frames), then rest lifted."""
    seed, win = seeded(size=(1280, 1100))
    lst = current(win)
    freeze.set_frozen(False)                           # the springs run (the harness puts the switch back)
    lst.viewport().repaint()
    i = _closed_on_screen(lst)
    painted = _paint_spy(lst, monkeypatch)
    pos = QPointF(lst.visualRect(lst.model().index(i, 0)).center())
    QApplication.sendEvent(lst.viewport(), QMouseEvent(QEvent.Type.MouseMove, pos, Qt.MouseButton.NoButton,
                                                       Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
    key = lst.model().entries[i][1].key
    assert wait_until(lambda: key in lst._touch and lst._touch[key].lift >= theme.SPRINGS["lift-px"] - 0.05 and
                      lst._touch[key].fade >= 1.0, 5)
    QTest.qWait(200)
    assert set(painted) <= {i - 1, i, i + 1}, sorted(set(painted))
    assert painted.count(i) > 2, "the spring ran in one jump, so the test would prove nothing about its frames"
    dy, lift, fade = lst.touch(i, key)
    assert lift > 0 and dy < 0 and fade == 1.0                        # lifted, faded in
    assert lst.touch(i + 1, lst.model().entries[i + 1][1].key)[0] > 0   # the row below eased down (apart)


def test_reduced_motion_jumps_the_hover_lift_to_its_rest(seeded):
    """Reduced motion: the lift and the parting jump (a move); the hover look shows at once, no frames between."""
    seed, win = seeded(size=(1280, 1100))
    lst = current(win)
    freeze.set_frozen(False)
    from app.qt import motion
    mode = motion.clock().mode
    was = mode.setting
    mode.set_setting("reduced")
    try:
        i = _closed_on_screen(lst)
        key = lst.model().entries[i][1].key
        lst._hover = i
        lst._retouch()
        t = lst._touch[key]
        assert t.lift == theme.SPRINGS["lift-px"] and t.nb == theme.SPRINGS["neighbour-px"]
    finally:
        mode.set_setting(was)


# --- the grooves ---------------------------------------------------------------------------------------------------------
def test_the_top_20_groove_is_an_easy_target_lights_under_the_hand_and_opens_nothing(seeded):
    """S10: a 2 px groove with a hover area of at least 12 px, reaching into the row below; under the hand it lights a
    step (its lip in `line-hi`); its tip says what it is and where its setting lives; a click opens nothing."""
    seed, win = seeded()
    lst = current(win)
    at = next(i for i, e in enumerate(lst.model().entries) if any(ln.kind == "top" for ln in e[2]))
    strip = part(lst, at, "top-line")[0]
    assert strip[1].height() >= 12
    assert "Settings → Anki & mining" in strip[2]
    below = lst.visualRect(lst.model().index(at + 1, 0))
    assert strip[1].bottom() > below.top()                          # it reaches into the row under it ...
    pos = QPointF(strip[1].center().x(), below.top() + 2)
    idx, hit = lst.part_at(pos.toPoint())
    assert hit is not None and hit[0] == "top-line" and idx.row() == at   # ... and wins there
    QApplication.sendEvent(lst.viewport(), QMouseEvent(QEvent.Type.MouseMove, pos, Qt.MouseButton.NoButton,
                                                       Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
    _settle(5)
    assert lst.line_hover == (at, "top")
    rect = lst.visualRect(lst.model().index(at, 0))
    arr = rgb_array(lst.viewport().grab(rect))
    assert count(arr[rect.height() - theme.ROW_LINE["line"]:], style.colours()["line-hi"], tolerance=2) > \
        rect.width() * 0.9                                           # lit a step
    opened = []
    lst.opened.connect(opened.append)
    QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=pos.toPoint())
    assert opened == [] and lst.model().open_key is None


def test_the_soon_groove_says_where_soon_starts(seeded):
    seed, win = seeded()
    lst = current(win)
    at = next(i for i, e in enumerate(lst.model().entries) if any(ln.kind == "soon" for ln in e[2]))
    strip = part(lst, at, "soon-line")[0]
    assert strip[1].height() >= 12 and strip[2].startswith("Soon:")


# --- S5: Finished keeps today's layout ---------------------------------------------------------------------------------
def test_finished_rows_keep_todays_layout_and_share_the_painter(seeded, monkeypatch):
    """S5 (C-scope §2.3): Finished's rows are painted by the same delegate class as Current's, in today's layout — its
    two-line row at `SIZES["row"]`, a date, no number, no string — never the one-line row."""
    seed, win = seeded()
    win.show_tab("finished")
    fin = win.page_widgets["finished"].list
    QApplication.processEvents()
    assert type(fin.delegate) is type(current(win).delegate)
    f = rows.fz()
    calls = {"row": 0, "current": 0}
    real_row, real_current = fin.delegate._paint_row, fin.delegate._paint_current
    monkeypatch.setattr(fin.delegate, "_paint_row", lambda *a, **k: (calls.__setitem__("row", calls["row"] + 1),
                                                                     real_row(*a, **k))[1])
    monkeypatch.setattr(fin.delegate, "_paint_current", lambda *a, **k: (calls.__setitem__(
        "current", calls["current"] + 1), real_current(*a, **k))[1])
    fin.delegate._sprites["row"].clear()
    fin.delegate._bytes["row"] = 0
    fin.viewport().repaint()
    assert calls["row"] > 0 and calls["current"] == 0
    for i, (kind, row, lines) in enumerate(fin.model().entries):
        if kind != rows.FINISHED:
            continue
        h = fin.visualRect(fin.model().index(i, 0)).height()
        assert h == round(theme.SIZES["row"] * f) + theme.SPACING["list-gap"] + fin.delegate._lines_h(lines)
        assert not [p for p in fin.delegate.parts(fin.model().entries[i], fin.visualRect(fin.model().index(i, 0)))
                    if p[0] == "stone"]


def test_a_stone_dimmed_as_its_file_leaves_the_top_20_is_a_new_picture(seeded):
    """B3: a file that leaves the top 20 changes nothing on its row but its stone (dimmed: it won't mine itself) — no
    count, no status. That alone makes the row a new picture."""
    seed, win = seeded()
    lst = current(win)
    entries = lst.model().entries
    i, row = next((n, e[1]) for n, e in enumerate(entries) if e[0] == rows.ROW and
                  any(ep.in_top and not ep.watched and not ep.cards for ep in e[1].episodes))
    k = next(n for n, ep in enumerate(row.episodes) if ep.in_top and not ep.watched and not ep.cards)
    left = row._replace(episodes=row.episodes[:k] + (row.episodes[k]._replace(in_top=False),) + row.episodes[k + 1:])
    assert stone_plan.plan_of(left) != stone_plan.plan_of(row)        # its string shows it (the stone dims)
    assert not rows._same_face(row, left, rows.ROW)


def test_a_hover_on_the_row_under_up_next_never_repaints_up_next(seeded, monkeypatch):
    """Up Next never eases apart (it is no Current row): a hover on the row just under it repaints that row and the
    one below, never the hero (S19: nothing visible changed there)."""
    seed, win = seeded(size=(1280, 1100))
    lst = current(win)
    lst.viewport().repaint()
    entries = lst.model().entries
    assert entries[0][0] == rows.HERO and entries[1][0] == rows.ROW
    painted = _paint_spy(lst, monkeypatch)
    lst._hover = 1
    lst._retouch()
    _settle()
    assert 1 in painted and 0 not in painted, sorted(set(painted))
