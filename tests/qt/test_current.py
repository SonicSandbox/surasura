"""The first screens (W2.2; the window's spec RUNBOOK W2.2: A2 #3–#5, #7, #8, the statuses, the top-20 line drawn;
06 E1–E4, E14–E16; 02 §2.4's *Getting ready*), on the synthetic seed through the stand-in store, offscreen.

What a wrong answer would cost a learner:
  * a row that doesn't open, or opens the wrong episodes (A2 #4) — the list is how he finds his place;
  * a missing video in his top 20 not said in amber (A2 #5) — those cards wait silently;
  * a mined episode whose video was later deleted shown as unmined (A2 #7) — he'd mine it twice — or its ▶ failing
    without saying why (A2 #8);
  * the top-20 line in the wrong place — what mines itself is exactly what's above it;
  * a number shown as 0 % before a Generate (E1), an elided title with no way to read it whole (E15), a column pushed
    off the window at Large text (E16), a read-only library that looks writable (E4);
  * every row painted at 20,000 files (E3: only what's on screen may be painted).
"""
import json
import os

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app import theme
from app.qt import rows, screens, shell, strings, style
from app.services import library_reader
from tests.fixtures import window_seed
from tests.qt.conftest import wait_until
from tests.qt.pixels import count, rgb_array
from tests.qt.test_wiring import problems


def _settings(**values):
    from app import path_utils
    path = path_utils.get_user_file("settings.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(values, f)


def open_on(qapp, seed, size=(1280, 800)):
    reader = library_reader.LibraryReader(seed.opener, language=seed.language, numbers=seed.numbers,
                                          mining=seed.mining, poll=0.02)
    services = shell.Services(library=reader)
    win = shell.open_window(qapp, services)
    win.resize(*size)
    win.show()
    page = win.page_widgets["current"]
    assert wait_until(lambda: page.view_model is not None and not page.view_model.loading, 10)
    QApplication.processEvents()
    for _ in range(50):                                       # the list's batched layout settles
        QApplication.processEvents()
    return win, services


@pytest.fixture
def seeded(qapp):
    made = []

    def make(files=window_seed.SMALL, language="ja", size=(1280, 800), **kw):
        seed = window_seed.build(files=files, language=language, **kw)
        win, services = open_on(qapp, seed, size)
        made.append((win, services))
        return seed, win
    yield make
    for win, services in made:
        win.close()
        services.shutdown(0.5)


def current(win):
    return win.page_widgets["current"].list


def entry_of(lst, key):
    for i, e in enumerate(lst.model().entries):
        if getattr(e[1], "key", None) == key:
            return i, e
    raise AssertionError(key)


def grab(lst, i):
    rect = lst.visualRect(lst.model().index(i, 0))
    img = lst.viewport().grab(rect)
    return rect, rgb_array(img)


def part(lst, i, name):
    entry = lst.model().entries[i]
    return [p for p in lst.delegate.parts(entry, lst.visualRect(lst.model().index(i, 0))) if p[0] == name]


# --- Current: the hero and the rows ----------------------------------------------------------------------------- #
def test_the_hero_is_the_first_row_and_its_play_says_where_it_opens(seeded):
    """A2 #3: ▶ Watch on Up Next says where it opens (the video player)."""
    seed, win = seeded()
    lst = current(win)
    kind, hero, _lines = lst.model().entries[0]
    assert kind == rows.HERO and hero.work_id == seed.hero_work
    assert hero.title_ep == "Ep 3"                                    # two watched: Up next is the third
    play = part(lst, 0, "play")[0]
    assert play[2].startswith("Watch Ep 3 in your video player")
    assert lst.model().data(lst.model().index(0, 0), Qt.ItemDataRole.AccessibleTextRole).startswith(
        "Up next: " + hero.title)


def test_a_click_on_a_row_opens_its_episodes_and_a_second_closes_it(seeded):
    """A2 #4: a click on a row opens its episodes (8)."""
    seed, win = seeded()
    lst = current(win)
    i, (kind, row, _l) = next((i, e) for i, e in enumerate(lst.model().entries) if e[0] == rows.ROW and
                              len(e[1].episodes) == 8)
    before = lst.visualRect(lst.model().index(i, 0)).height()
    QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=lst.visualRect(lst.model().index(i, 0)).center())
    assert wait_until(lambda: lst.visualRect(lst.model().index(i, 0)).height() > before)
    assert lst.model().open_key == row.key
    rect = lst.visualRect(lst.model().index(i, 0))
    assert rect.height() >= before + 8 * round(theme.SIZES["episode-row"] * rows.fz())
    QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(rect.center().x(), rect.top() + 10))
    assert wait_until(lambda: lst.model().open_key is None)


def test_three_missing_in_the_top_20_are_amber_on_the_open_rows_episodes(seeded):
    """A2 #5: …the three with no video in the top 20 say so, in amber."""
    seed, win = seeded(size=(1280, 1100))
    lst = current(win)
    i, (kind, row, _l) = next((i, e) for i, e in enumerate(lst.model().entries)
                              if e[0] == rows.ROW and sum(ep.missing for ep in e[1].episodes) == 3)
    assert row.mark.tone == "warn" and row.status.kind == "waiting"
    lst.toggle(lst.model().index(i, 0))
    assert wait_until(lambda: lst.visualRect(lst.model().index(i, 0)).height() > 200)
    lst.scrollTo(lst.model().index(i, 0), lst.ScrollHint.PositionAtTop)
    QApplication.processEvents()
    statuses = part(lst, i, "status")
    rect, arr = grab(lst, i)
    warn = 0
    for name, r, tip, _p in statuses:
        if tip and "top 20" in tip and "waiting for one" in tip:
            sub = arr[r.top() - rect.top():r.bottom() - rect.top() + 1, r.left() - rect.left():r.right() - rect.left() + 1]
            warn += count(sub, theme.STATUS["warn"], tolerance=40) > 3
    assert warn == 3


def test_mined_then_removed_is_in_anki_with_the_dim_mark_and_its_play_names_the_removal(seeded):
    """A2 #7 and #8: ✓ in Anki **and** a no-video mark; its ▶ says the video was removed and offers Link."""
    seed, win = seeded(size=(1280, 1100))
    lst = current(win)
    i, (kind, row, _l) = next((i, e) for i, e in enumerate(lst.model().entries)
                              if e[0] == rows.ROW and any(ep.removed for ep in e[1].episodes)
                              and e[1].status.kind == "in_anki")
    assert row.mark is not None and row.mark.tone == "faint"
    rect, arr = grab(lst, i)
    st = [p for p in part(lst, i, "status")][0][1]
    sub = arr[st.top() - rect.top():st.bottom() - rect.top() + 1, st.left() - rect.left():st.right() - rect.left() + 1]
    assert count(sub, theme.STATUS["ok"], tolerance=40) > 3                  # the glyph and words in the learned green
    lst.toggle(lst.model().index(i, 0))
    assert wait_until(lambda: lst.visualRect(lst.model().index(i, 0)).height() > 200)
    lst.scrollTo(lst.model().index(i, 0), lst.ScrollHint.PositionAtTop)
    QApplication.processEvents()
    gone = next(ep for ep in row.episodes if ep.removed)
    plays = [p for p in part(lst, i, "play") if p[3] is not None and p[3].id == gone.id]
    assert plays and "removed" in plays[0][2] and "link" in plays[0][2].lower()
    fired = []
    lst.play_requested.connect(fired.append)
    QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=plays[0][1].center())
    assert fired == []                                                       # a ▶ that can't play asks for nothing


def test_every_status_is_a_glyph_and_words_never_colour_alone(seeded):
    seed, win = seeded()
    lst = current(win)
    kinds = set()
    for kind, row, _l in lst.model().entries:
        if kind in (rows.HERO, rows.ROW):
            kinds.add(row.status.kind)
            assert row.status.label and row.status.tip
            # the hero reads as it's painted: its next episode's status (IK-12)
            said = row.episodes[row.next_index].status if kind == rows.HERO else row.status
            assert said.label.lower() in row.accessible.lower()
    assert {"mining", "waiting", "in_anki", "no_media", "mine"} <= kinds


def test_the_top_20_line_is_drawn_after_the_row_holding_the_20th_available_file(seeded):
    seed, win = seeded()
    lst = current(win)
    at = [i for i, e in enumerate(lst.model().entries) if any(ln.kind == "top" for ln in e[2])]
    assert at == [4]                                       # the seed: the 20th available file is row 5's
    strip = part(lst, at[0], "top-line")[0]
    assert strip[2].startswith("Everything above this line mines itself")
    rect, arr = grab(lst, at[0])
    band = arr[strip[1].top() - rect.top():strip[1].bottom() - rect.top() + 1]
    assert count(band, style.colours()["top20-line"], tolerance=12) > 40      # the dashed rule, across the row


def test_the_soon_line_sits_where_soon_starts_with_its_word(seeded):
    seed, win = seeded()
    lst = current(win)
    entries = lst.model().entries
    first_soon = next(i for i, e in enumerate(entries) if e[0] == rows.ROW and e[1].tier == "soon")
    assert any(ln.kind == "soon" for ln in entries[first_soon - 1][2])
    tip = part(lst, first_soon - 1, "soon-line")[0][2]
    assert tip.startswith("Soon:")


def test_a_long_mixed_title_is_cut_once_with_the_whole_in_its_tooltip_and_accessible_text(seeded):
    """E15: elided per paint, the full title in the tooltip and to a screen reader; never two lines."""
    seed, win = seeded(size=(1100, 760))
    long_title = "海鳴りの聞こえる町で暮らす二人 Season 2 — 特別編 🌊 and a very long English subtitle that goes on"
    lst = current(win)
    i = next(k for k, e in enumerate(lst.model().entries) if e[0] == rows.ROW and e[1].media != "youtube")
    row = lst.model().entries[i][1]
    seed.library.commit(works=[{"id": row.work_id, "title": long_title}])
    assert wait_until(lambda: lst.model().entries[i][1].title == long_title)
    QApplication.processEvents()
    idx = lst.model().index(i, 0)
    title = part(lst, i, "title")[0]
    assert title[2].startswith(long_title)
    assert lst.model().data(idx, Qt.ItemDataRole.AccessibleTextRole).startswith(long_title)
    cols = lst.delegate.columns(lst.visualRect(idx))
    _st, _w, elided = rows.TEXT.static(long_title, "row-title", cols["text_right"] - 80)
    assert elided
    assert lst.visualRect(idx).height() == lst.delegate.sizeHint(None, idx).height()   # one line: the height holds


def test_nothing_the_screens_do_writes_to_the_library(seeded):
    """Display only (W2.2): opening rows, clicking every painted part and pressing ▶ never touches the store — any
    write would go through the library's `commit`, watched here."""
    seed, win = seeded()
    lst = current(win)
    writes = []
    real = seed.library.commit
    seed.library.commit = lambda *a, **kw: (writes.append((a, kw)), real(*a, **kw))[1]
    for i in range(min(6, lst.model().rowCount())):
        for p in lst.delegate.parts(lst.model().entries[i], lst.visualRect(lst.model().index(i, 0))):
            QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=p[1].center())
    lst.play_requested.emit(lst.model().entries[0][1].episodes[0])
    QApplication.processEvents()
    assert writes == []


def test_play_looks_for_the_video_beside_the_file_on_a_worker_and_says_why_it_cant(seeded, tmp_path):
    seed, win = seeded()
    page = win.page_widgets["current"]
    lines = []
    page.message.connect(lines.append)
    ep = page.list.model().entries[0][1].episodes[0]
    page.list.play_requested.emit(ep)
    assert wait_until(lambda: lines)
    assert "no video beside it on disk" in lines[0]
    assert win.bar_line.full() == lines[0]
    # a video beside it: found (what opens it is the system's, so the opener is the seam)
    from app import path_utils
    sub = os.path.join(path_utils.get_data_path("ja"), *ep.rel_path.split("/"))
    os.makedirs(os.path.dirname(sub), exist_ok=True)
    open(os.path.splitext(sub)[0] + ".mkv", "wb").close()
    found = screens.media_to_open("ja", ep, "anime")
    assert found[0].endswith(".mkv") and found[1] is None


# --- the other pages ------------------------------------------------------------------------------------------ #
def test_finished_shows_its_months_newest_first_and_the_tab_counts_its_records(seeded):
    seed, win = seeded()
    page = win.page_widgets["finished"]
    entries = page.list.model().entries
    months = [p for k, p, _l in entries if k == rows.MONTH]
    assert months[0] == "October 2026" and months[-1] == "Earlier"
    assert win.tab_buttons["finished"].text() == strings.TAB_COUNT.format(name="Finished", count=7)
    assert any(k == rows.FINISHED and p.studying for k, p, _l in entries)
    assert page.help.toolTip() == strings.FINISHED_HELP_TIP


def test_needs_you_shows_the_show_waiting_on_videos_and_its_tab_appears(seeded):
    seed, win = seeded()
    page = win.page_widgets["needs"]
    needs = [p for k, p, _l in page.list.model().entries if k == rows.NEED]
    assert len(needs) == 1 and needs[0].title.endswith("3 episodes have no video")
    assert not win.tab_buttons["needs"].isHidden()
    assert win.tab_buttons["needs"].text() == strings.TAB_WITH_COUNT.format(name="Needs you", count=1)


def test_the_subline_counts_current(seeded):
    """Counted from the seed itself, not from the view: the rows are Current's pieces, the files its items."""
    seed, win = seeded()
    current_items = [r for r in seed.items if r["tier"] in ("now", "soon")]
    pieces = len({r["piece_id"] for r in current_items})
    assert win.subline.text() == f"日本語 · {pieces} in Current · {len(current_items)} files"


def test_the_goal_strip_counts_goals_titles_and_files(seeded):
    seed, win = seeded()
    strip = win.page_widgets["current"].goal_strip
    assert strip.isVisible() and strip.goal.line == "3 titles · 34 files"
    assert strip.toolTip() == strip.goal.tip and strip.accessibleName().startswith("Goal: 3 titles")


# --- edge cases --------------------------------------------------------------------------------------------- #
def test_e1_e2_an_empty_library_says_so_and_shows_no_zero_percent(qapp):
    """E1 / E2: Current's empty line, Goal's *Goal is empty*, Finished's own line; no number at all, never 0 %."""
    from tests.fixtures import standin_store
    lib = standin_store.StandinLibrary([], [])
    seed = window_seed.Seed(library=lib, opener=standin_store.StandinOpener(lib), numbers=lambda: (0, {}),
                            mining=lambda: (), root=None, language="ja", files=0, vocabulary=set(), items=[], works=[],
                            hero_work=None)
    win, services = open_on(qapp, seed)
    try:
        cur = win.page_widgets["current"]
        assert [k for k, _p, _l in cur.list.model().entries] == [rows.EMPTY]
        assert cur.list.model().entries[0][1] == strings.CURRENT_EMPTY
        assert cur.goal_strip.goal.line == "Goal is empty"
        assert win.page_widgets["finished"].list.model().entries[0][1] == strings.FINISHED_EMPTY
        assert win.subline.text() == "日本語 · nothing added yet"
        assert win.tab_buttons["needs"].isHidden()
        img = rgb_array(cur.list.viewport().grab())
        assert img.size
    finally:
        win.close()
        services.shutdown(0.5)


@pytest.mark.parametrize("files", [2000, 20000])
def test_e3_only_the_rows_on_screen_are_painted(seeded, files):
    seed, win = seeded(files=files)
    lst = current(win)
    assert lst.model().rowCount() > 20
    lst.delegate.paints = 0
    lst.viewport().repaint()
    on_screen = sum(1 for i in range(lst.model().rowCount())
                    if lst.visualRect(lst.model().index(i, 0)).intersects(lst.viewport().rect()))
    assert 0 < lst.delegate.paints <= on_screen + 2
    assert on_screen < 40


def test_e4_a_read_only_library_says_why_and_still_shows_its_rows(seeded):
    seed, win = seeded(mode="read-only", reason="damaged")
    page = win.page_widgets["current"]
    assert page.state_bar.isVisible() and "the library needs a repair" in page.state_bar.text()
    assert page.list.model().rowCount() > 5


def test_getting_ready_shows_the_last_copy_read_only_with_its_line(seeded):
    seed, win = seeded(mode="json", reason="not ready")
    page = win.page_widgets["current"]
    assert page.state_bar.text() == strings.STATE_LINES["getting-ready"]
    assert page.list.model().rowCount() > 5


def test_e14_a_chinese_library(qapp, seeded):
    _settings(target_language="zh", zh_script="s")
    try:
        seed, win = seeded(language="zh")
        assert win.subline.text().startswith("中文 · ")
        assert style.current()[2] == "zh"
        lst = current(win)
        assert any("一" <= ch <= "鿿" for ch in lst.model().entries[0][1].title)
        fam = rows.TEXT.font("row-title").families()
        assert "Microsoft YaHei UI" in fam and "Yu Gothic UI" not in fam
    finally:
        style.apply(qapp, "hb", "M", "ja")                 # the harness puts back theme and size, not the language


def test_e16_large_text_at_1024_keeps_every_column_inside_the_row(qapp, seeded):
    _settings(text_size="L")
    seed, win = seeded(size=(1024, 720))
    assert style.current()[1] == "L"
    lst = current(win)
    width = lst.viewport().width()
    f = rows.fz()
    for i in range(min(8, lst.model().rowCount())):
        rect = lst.visualRect(lst.model().index(i, 0))
        kind, payload, lines = lst.model().entries[i]
        if kind == rows.ROW:
            cols = lst.delegate.columns(rect)
            cover_right = rect.left() + 4 + round(20 * f) + 12 + round(theme.SIZES["row-cover-w"] * f)
            assert cols["acts"].right() <= width
            assert cols["text_right"] - cover_right >= 100            # the title keeps room to be read
        elif kind == rows.HERO:
            g = lst.delegate._hero_geometry(payload, rect, lines)
            assert g["main"].width() >= 200 and g["play"].right() <= width
            assert g["status"].left() >= g["main"].right()            # the side column never covers the text
            assert g["cover"].bottom() <= g["box"].bottom()


def test_the_wiring_check_passes_with_the_pages_alive(seeded):
    seed, win = seeded()
    found, walked = problems(win)
    assert found == []


def test_painted_parts_show_their_tooltip_through_the_bubble(seeded):
    seed, win = seeded()
    lst = current(win)
    play = part(lst, 0, "play")[0]
    from PyQt6.QtGui import QHelpEvent
    from PyQt6.QtCore import QEvent
    ev = QHelpEvent(QEvent.Type.ToolTip, play[1].center(), lst.viewport().mapToGlobal(play[1].center()))
    lst.viewportEvent(ev)
    assert wait_until(lambda: win.tooltips.showing() == play[2])


def test_a_click_on_a_pill_a_mark_or_a_tick_changes_nothing(seeded):
    """IK-10: in W2.2 a status pill, the on-disk mark, a chip and an episode's tick are states, not buttons: a click on
    one neither opens nor closes the row."""
    seed, win = seeded(size=(1280, 1100))
    lst = current(win)
    i = next(k for k, e in enumerate(lst.model().entries) if e[0] == rows.ROW and e[1].mark is not None)
    lst.toggle(lst.model().index(i, 0))
    assert wait_until(lambda: lst.model().open_key is not None)
    lst.scrollTo(lst.model().index(i, 0), lst.ScrollHint.PositionAtTop)
    QApplication.processEvents()
    for name in ("status", "mark", "tick"):
        p = part(lst, i, name)[0]
        QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=p[1].center())
        QApplication.processEvents()
        assert lst.model().open_key is not None, name


def test_a_failed_migration_says_so_and_never_getting_ready_forever(seeded):
    """IK-8 / G1.2-18: the bar says why and what to do."""
    seed, win = seeded(mode="json", reason="migration failed")
    page = win.page_widgets["current"]
    assert page.state_bar.text() == strings.STATE_LINES["migration-failed"]



def test_the_text_cache_holds_across_device_pixel_ratios(qapp):
    """A-1: a caller asking at 1.0 between two paints at 1.5 must not empty the cache (it did, 2–4 times a frame)."""
    rows.TEXT.static("星降る街の小さな工房", "row-title", 300, dpr=1.5)
    key = rows.TEXT._key
    held = len(rows.TEXT._static)
    rows.TEXT.metrics("status-pill")                     # at the default ratio
    rows.TEXT.static("雲の上の郵便屋さん", "row-title", 300, dpr=2.0)
    assert rows.TEXT._key == key and len(rows.TEXT._static) == held + 1


def test_a_reset_keeps_the_row_at_the_top_where_it_was(seeded):
    """An outside commit (a hato drop at the top) changes the rows' keys: the list is reset, and the row that was at
    the top of the view stays there."""
    seed, win = seeded(files=2000)
    lst = current(win)
    lst.verticalScrollBar().setValue(lst.verticalScrollBar().maximum() // 2)
    QApplication.processEvents()
    idx = lst.indexAt(QPoint(4, 1))
    key = rows.RowsModel.key_of(lst.model().entries[idx.row()])
    y = lst.visualRect(idx).top()
    first = next(r for r in seed.items if r["tier"] == "now")
    seed.library.commit(items=[dict(first, id=10 ** 6, ord=first["ord"] - 512, piece_id=10 ** 6,
                                    rel_path="HighPriority/Hato/new - 01.srt", title="new - 01.srt")], order=True)
    assert wait_until(lambda: lst.model().entries[0][1].key == f"p{10 ** 6}")
    QApplication.processEvents()
    row = lst.model().keys.index(key)
    assert abs(lst.visualRect(lst.model().index(row, 0)).top() - y) <= 1


def test_finished_hit_tests_only_what_it_paints(seeded):
    """A-14: a Finished row paints only Mining… / N in Anki; no hidden pill or mark answers the pointer."""
    seed, win = seeded()
    win.show_tab("finished")
    lst = win.page_widgets["finished"].list
    QApplication.processEvents()
    for i, (kind, payload, _l) in enumerate(lst.model().entries):
        if kind != rows.FINISHED:
            continue
        names = [p[0] for p in part_any(lst, i)]
        assert "mark" not in names
        if payload.status.kind not in ("in_anki", "mining"):
            assert "status" not in names


def part_any(lst, i):
    entry = lst.model().entries[i]
    return lst.delegate.parts(entry, lst.visualRect(lst.model().index(i, 0)))


def test_a_youtube_videos_play_is_muted_and_says_why(seeded):
    """A-19: its video is online; until the window holds its address ▶ is muted with the reason, never a dead click."""
    seed, win = seeded()
    lst = current(win)
    i, (kind, row, _l) = next((i, e) for i, e in enumerate(lst.model().entries)
                              if e[0] == rows.ROW and e[1].media == "youtube")
    assert not row.can_play and "online" in row.play_tip.lower()
    fired = []
    lst.play_requested.connect(fired.append)
    play = [p for p in part(lst, i, "play")][0]
    QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=play[1].center())
    assert fired == []


def test_a_repaint_reuses_the_painted_rows_and_a_refresh_repaints_only_what_changed(seeded):
    """Each closed row is painted once into a pixmap; a repaint draws the pixmaps (no row drawn again), and a status
    write on one show repaints that show's row alone."""
    seed, win = seeded()
    lst = current(win)
    lst.viewport().repaint()
    renders = lst.delegate.renders
    lst.viewport().repaint()
    assert lst.delegate.renders == renders
    i, (kind, row, _l) = next((i, e) for i, e in enumerate(lst.model().entries) if e[0] == rows.ROW)
    seed.library.commit(items=[{"id": row.episodes[0].id, "watched": 1 - int(row.episodes[0].watched)}])
    assert wait_until(lambda: lst.model().entries[i][1] is not row)
    assert lst.model().changed == [i]
    lst.viewport().repaint()
    assert lst.delegate.renders == renders + 1


def test_a_change_on_current_leaves_finished_and_goal_untouched(seeded):
    """Bench 6: every reader view diffed every page on the window's thread. A status write on a Current row now builds
    no entries for Finished (its rows are the same objects) and doesn't repaint the Goal strip."""
    seed, win = seeded()
    lst = current(win)
    fin = win.page_widgets["finished"].list
    strip = win.page_widgets["current"].goal_strip
    fin_entries, goal = fin.model().entries, strip.goal
    i, (kind, row, _l) = next((i, e) for i, e in enumerate(lst.model().entries) if e[0] == rows.ROW)
    seed.library.commit(items=[{"id": row.episodes[0].id, "watched": 1 - int(row.episodes[0].watched)}])
    assert wait_until(lambda: lst.model().entries[i][1] is not row)
    assert fin.model().entries is fin_entries and fin.model().changed == []
    assert strip.goal is goal


def test_the_rows_just_past_the_screen_are_painted_ahead_when_the_list_rests(seeded):
    """Bench 7: a row's first paint (up to ~15 ms) fell in the scroll's frames. Once the list rests, the rows just below
    the screen are drawn ahead, one per turn of the loop; scrolling onto them then draws no row afresh."""
    seed, win = seeded()
    lst = current(win)
    lst.viewport().repaint()
    assert wait_until(lambda: lst.delegate.warmed >= 3)
    bar = lst.verticalScrollBar()
    renders = lst.delegate.renders
    bar.setValue(bar.value() + round(theme.SIZES["row"] * rows.fz()))    # one row down: the next row comes in
    lst.viewport().repaint()
    assert lst.delegate.renders == renders


def test_an_open_row_repaints_from_pixmaps_and_opening_rows_never_pushes_the_closed_ones_out(seeded):
    """Bench 8: every opening was a long step — the open row's head was drawn afresh on each paint, and its episodes'
    pixmaps shared one cache with the rows, so opening rows pushed the closed rows on screen out. The open row's head is
    now a pixmap too, and episodes keep a cache of their own: a repaint of an open row, and of the rows after closing
    it again, draws nothing afresh."""
    seed, win = seeded()
    lst = current(win)
    lst.viewport().repaint()
    openable = [i for i, e in enumerate(lst.model().entries) if e[0] == rows.ROW and len(e[1].episodes) >= 2][:6]
    assert len(openable) >= 3
    for i in openable:                                         # open and close several: their episodes fill a cache
        lst.toggle(lst.model().index(i, 0))
        lst.doItemsLayout()
        lst.viewport().repaint()
        renders = lst.delegate.renders
        lst.viewport().repaint()                               # the open row again: its head and episodes are reused
        assert lst.delegate.renders == renders
        lst.toggle(lst.model().index(i, 0))
        lst.doItemsLayout()
        lst.viewport().repaint()
    renders = lst.delegate.renders
    lst.viewport().repaint()
    assert lst.delegate.renders == renders                     # every closed row on screen still in its cache


def test_a_hidden_tabs_first_screen_is_painted_ahead_so_its_first_switch_draws_no_row(seeded):
    """Bench 8: a tab's first switch drew its whole first screen in one step. While Finished is hidden, its first
    screen is painted ahead at Current's width, one row a turn; switching to it then draws no row afresh."""
    seed, win = seeded(files=2000)
    fin = win.page_widgets["finished"].list
    assert not fin.isVisible() and fin.model().rowCount() > 0
    assert wait_until(lambda: fin.delegate.warmed >= 3)
    for _ in range(20):
        QApplication.processEvents()
    win.show_tab("finished")
    QApplication.processEvents()
    fin.viewport().repaint()
    assert fin.delegate.paints > 0
    assert fin.delegate.renders == 0
