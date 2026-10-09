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
from PyQt6.QtGui import QColor, QImage, QPainter
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
    assert win.tab_buttons["needs"].text() == strings.TAB_COUNT.format(name="Needs you", count=1)


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
    on_screen = lambda i: lst.visualRect(lst.model().index(i, 0)).bottom() < lst.viewport().height()
    openable = [i for i, e in enumerate(lst.model().entries) if e[0] == rows.ROW and len(e[1].episodes) >= 2 and
                on_screen(i)][:6]
    assert len(openable) >= 3
    for i in openable:                                         # open and close several: their episodes fill a cache
        lst.toggle(lst.model().index(i, 0))
        lst.doItemsLayout()
        lst.viewport().repaint()
        renders = lst.delegate.renders
        lst.viewport().repaint()                               # the open row again: its head and episodes are reused
        assert lst.delegate.renders == renders
        key = lst.model().entries[i][1].key
        assert any(k[1] == (key, "open") for k in lst.delegate._sprites["row"]), [k[:2] for k in lst.delegate._sprites["row"]][-4:]   # the head is a pixmap (B-9)
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
    assert wait_until(lambda: not fin._warm.isActive())        # one row a turn, until its first screen is done
    win.show_tab("finished")
    QApplication.processEvents()
    fin.viewport().repaint()
    assert fin.delegate.paints > 0
    assert fin.delegate.renders == 0


def test_the_painted_rows_are_kept_within_their_byte_budget(seeded, monkeypatch):
    """Review B-2: kept by count alone, the painted rows outgrew the idle budget at 250 % (~2 MB a row). A list keeps
    its pixmaps within `SPRITE_MB` too, oldest out first."""
    monkeypatch.setitem(rows.SPRITE_MB, "row", 1)            # 1 MB: a few rows at this size
    seed, win = seeded(files=2000)
    lst = current(win)
    bar = lst.verticalScrollBar()
    for v in range(0, min(bar.maximum(), 4000), 200):
        bar.setValue(v)
        lst.viewport().repaint()
    d = lst.delegate
    assert d._bytes["row"] <= 1024 * 1024 or len(d._sprites["row"]) == 1
    assert d._bytes["row"] == sum(rows._size(v[1]) for v in d._sprites["row"].values())


def test_a_scroll_step_repaints_only_the_strip_that_came_into_view(seeded):
    """Profile 2026-10-08: every 40 px scroll step repainted the whole list (~10 rows, every frame ~2–3 ms at 150 %):
    the app's style sheet turned the viewport's autoFillBackground off when it polished it, so Qt couldn't move the
    pixels already drawn. The viewport is opaque now (it fills its own ground where it paints): a step paints only the
    strip that came into view, and the gaps between rows still get the list's ground."""
    from PyQt6.QtCore import QEvent, QObject

    class Regions(QObject):
        def __init__(self):
            super().__init__()
            self.heights = []

        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.Type.Paint:
                self.heights.append(ev.region().boundingRect().height())
            return False

    seed, win = seeded(files=2000)
    lst = current(win)
    vp = lst.viewport()
    win.style().unpolish(vp)                                   # polished again, as a theme change does
    win.style().polish(vp)
    regions = Regions()
    vp.installEventFilter(regions)
    bar = lst.verticalScrollBar()
    bar.setValue(400)
    for _ in range(5):
        QApplication.processEvents()
    regions.heights = []
    bar.setValue(440)
    for _ in range(5):
        QApplication.processEvents()
    assert regions.heights and max(regions.heights) <= 40 + 2, (regions.heights, vp.height())


def test_the_pointer_resting_on_a_closed_row_paints_its_episodes_ahead_so_opening_it_draws_none_afresh(seeded,
                                                                                                       monkeypatch):
    """Bench 9: opening a row was one long step, its episodes' first paints. A pointer that rests on a closed row for a
    moment paints that row's episodes ahead; opening it then draws no episode afresh (the spy counts every episode the
    open row's repaint draws; warming draws are counted only after the warm has finished)."""
    from PyQt6.QtCore import QEvent, QPointF
    from PyQt6.QtGui import QMouseEvent
    seed, win = seeded()
    lst = current(win)
    lst.viewport().repaint()
    on_screen = lambda i: lst.visualRect(lst.model().index(i, 0)).bottom() < lst.viewport().height()
    i = next(i for i, e in enumerate(lst.model().entries)
             if e[0] == rows.ROW and len(e[1].episodes) >= 2 and on_screen(i))
    row = lst.model().entries[i][1]
    ids = {(ep.id, False) for ep in row.episodes}
    assert not any(k[1] in ids for k in lst.delegate._sprites["ep"])     # nothing warmed before the pointer arrives
    pos = QPointF(lst.visualRect(lst.model().index(i, 0)).center())
    QApplication.sendEvent(lst.viewport(), QMouseEvent(QEvent.Type.MouseMove, pos, Qt.MouseButton.NoButton,
                                                       Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
    assert wait_until(lambda: any(k[1] in ids for k in lst.delegate._sprites["ep"]))
    assert wait_until(lambda: not lst._hover_warm.isActive())            # the warm has run out of episodes in view
    drawn = []
    original = lst.delegate._paint_episode
    monkeypatch.setattr(lst.delegate, "_paint_episode", lambda *a, **k: (drawn.append(a[2]), original(*a, **k))[1])
    lst.toggle(lst.model().index(i, 0))
    lst.doItemsLayout()
    lst.viewport().repaint()
    assert lst.model().open_key == row.key
    assert drawn == []                                                   # opening blits the warmed episodes


def test_a_resting_list_keeps_its_screen_and_the_rows_ahead_and_lets_rows_scrolled_far_past_go(seeded):
    """Bench 9: a list kept every row it had ever painted, so idle memory grew with what was scrolled past (284 MB idle
    at 375 %). Once the list rests, it keeps its screen and the WARM_AHEAD rows either side; rows scrolled several
    screens past are let go, and the screen it rests on is still painted."""
    seed, win = seeded(files=2000)
    lst = current(win)
    bar = lst.verticalScrollBar()
    lst.viewport().repaint()
    top_last = lst.indexAt(QPoint(4, lst.viewport().height() - 2)).row()
    row_index = {e[1].key: i for i, e in enumerate(lst.model().entries) if getattr(e[1], "key", None) is not None}

    def owner(ident):                    # the row a pixmap is of: a closed row's key, or an open head's (key, "open")
        if ident in row_index:
            return row_index[ident]
        if isinstance(ident, tuple) and len(ident) == 2 and ident[0] in row_index:
            return row_index[ident[0]]
        return None

    def painted_rows():
        return [i for i in (owner(k[1]) for k in lst.delegate._sprites["row"]) if i is not None]

    bar.setValue(bar.maximum() // 2)                           # far down the list: its screen is painted
    lst.viewport().repaint()
    far = [i for i in painted_rows() if i > top_last + rows.WARM_AHEAD]
    assert far, "the far screen should be painted before the rest"
    bar.setValue(0)                                            # back to the top, and the list rests
    lst.viewport().repaint()
    assert wait_until(lambda: not lst._warm.isActive())
    kept = painted_rows()
    assert any(i <= top_last for i in kept), "the screen the list rests on is kept"
    assert max(kept) <= top_last + rows.WARM_AHEAD, (max(kept), top_last)


def test_the_generated_covers_are_kept_within_their_byte_budget_oldest_out_first(qapp, monkeypatch):
    """Covers are generated per title and kept by bytes (`COVERS_MB`), not by count: a library of many titles at
    250 % would otherwise hold tens of megabytes of pixmaps. The oldest go first, and the running byte count must match
    what is actually held, or the next eviction works from a wrong total."""
    rows.clear_covers()
    try:
        monkeypatch.setattr(rows, "COVERS_MB", 1)            # 1 MiB: about 18 covers of 100 x 140 at 1.0
        titles = [f"星降る街{n:02d}" for n in range(40)]     # 40 covers of 56,000 bytes: 2.2 MB, over the budget
        for title in titles:
            rows.cover(title, 100, 140, 1.0)
        assert rows._COVER_BYTES[0] <= 1024 * 1024
        assert rows._COVER_BYTES[0] == sum(rows._size(p) for p in rows._COVERS.values())
        kept = [key[0] for key in rows._COVERS]
        assert kept and kept[-1] == titles[-1] and titles[0] not in kept
        assert kept == titles[len(titles) - len(kept):]      # the survivors are the newest, in order
    finally:
        rows.clear_covers()


def test_an_open_hero_keeps_its_head_as_a_pixmap_and_a_repaint_draws_nothing_afresh(seeded):
    """Review B-13 for the hero: the open hero's head is a pixmap of its own, keyed as the open hero, not drawn afresh
    on each paint; a repaint of the open hero draws no head or episode afresh."""
    seed, win = seeded()
    lst = current(win)
    lst.viewport().repaint()
    lst.toggle(lst.model().index(0, 0))                        # the hero is the first entry: open it
    lst.doItemsLayout()
    lst.viewport().repaint()
    hero = lst.model().entries[0][1]
    assert any(k[0] == rows.HERO and k[1] == (hero.key, "open") for k in lst.delegate._sprites["row"]), \
        [k[:2] for k in lst.delegate._sprites["row"]][-4:]
    renders = lst.delegate.renders
    lst.viewport().repaint()                                   # the open hero again: nothing new is drawn
    assert lst.delegate.renders == renders


def test_the_goal_strip_blits_its_pixmap_and_paints_afresh_only_for_a_new_goal(seeded):
    """The Goal strip is painted once into `_pix` and blitted on every repaint (a tab switch, a window repaint): the
    same goal, size and look keep the same pixmap object, and a different goal draws a new one."""
    seed, win = seeded()
    strip = win.page_widgets["current"].goal_strip
    strip.repaint()
    first = strip._pix
    assert first is not None
    strip.repaint()
    assert strip._pix is first
    other = strip.goal._replace(line="1 title · 2 files")
    strip.set_goal(other)
    strip.repaint()
    assert strip._pix is not first and strip._pix_key[0] is other


def test_an_emptied_list_lets_its_row_and_episode_pixmaps_go_once_it_rests(seeded):
    """A list emptied (a search that finds nothing, a view with no entries) must not keep the pixmaps of the rows it
    showed: idle memory should not hold on to what an empty list no longer draws. Once it rests, both caches and their
    byte counts are back to nothing."""
    seed, win = seeded()
    lst = current(win)
    lst.viewport().repaint()
    assert wait_until(lambda: lst.delegate.warmed >= 3)
    # the list painted rows, so there is a pixmap to let go; without this the rest of the test proves nothing
    assert lst.delegate._sprites["row"] and lst.delegate._bytes["row"] > 0
    lst.set_entries([])
    assert wait_until(lambda: not lst._warm.isActive())
    assert not lst.delegate._sprites["row"] and not lst.delegate._sprites["ep"]
    assert lst.delegate._bytes == {"row": 0, "ep": 0}


def test_the_hover_warm_stops_once_its_episodes_would_push_out_what_it_drew(seeded, monkeypatch):
    """Bench 9 follow-up: the hover warm paints episodes ahead only within half the episodes' cache. Past that, each
    one drawn would evict one drawn before, call after call, so the warm must stop (return False) within a few calls,
    and the episodes' cache stays inside its cap."""
    monkeypatch.setitem(rows.SPRITE_MB, "ep", 0.25)          # 0.25 MB: half of it (128 KB) is less than two episodes
    seed, win = seeded(files=2000)
    lst = current(win)
    d = lst.delegate
    i = next(i for i, e in enumerate(lst.model().entries) if e[0] == rows.ROW and len(e[1].episodes) >= 6)
    index = lst.model().index(i, 0)
    calls = 0
    while calls < 8 and d.warm_episodes(index, 1.0, 1 << 20):   # a large room: only the budget can stop it
        calls += 1
    assert calls <= 2, ("the warm drew past its budget: without it all 6+ episodes would be drawn", calls)
    assert d._bytes["ep"] <= 0.25 * 1024 * 1024


def test_a_hidden_list_keeps_the_screen_it_was_scrolled_to_not_its_top(seeded):
    """Review C-1: a list left scrolled several screens down keeps that screen while it is hidden, not its top. Warmed
    from the top instead, the screen the learner left would be drawn afresh on the way back to it."""
    seed, win = seeded(files=2000)
    fin = win.page_widgets["finished"].list
    win.show_tab("finished")
    QApplication.processEvents()
    fin.verticalScrollBar().setValue(3 * fin.viewport().height())
    fin.viewport().repaint()
    assert fin.verticalScrollBar().value() >= 2 * fin.viewport().height()   # really scrolled, not left at the top
    assert wait_until(lambda: not fin._warm.isActive(), 10)
    top = fin.indexAt(QPoint(4, 1))
    assert top.isValid()
    top_key = fin.model().entries[top.row()][1].key
    win.show_tab("current")                                                  # Finished is hidden now
    assert wait_until(lambda: not fin._warm.isActive(), 10)                  # its hidden warm has run its course
    assert any(k[1] == top_key for k in fin.delegate._sprites["row"])        # the row at its scroll place is kept
    renders = fin.delegate.renders
    win.show_tab("finished")
    QApplication.processEvents()
    fin.viewport().repaint()
    assert fin.delegate.paints > 0
    assert fin.delegate.renders == renders                                   # switching back draws no row afresh


def test_a_stale_hover_warms_nothing_while_the_list_is_still_moving_and_warms_once_it_rests(seeded, monkeypatch):
    """Review C-4: a wheel scroll moves no pointer, so the row a hover names can be a screen away from the pointer. While
    the list is still moving, that hover must paint nothing: a warm there is work the learner never sees, competing with
    the scroll. It waits (`_hover_warm` re-arms) and warms once the list has rested."""
    monkeypatch.setattr(rows, "WARM_IDLE_MS", 1000)     # a wide margin: the wait must be real, not a race
    seed, win = seeded()
    lst = current(win)
    lst.viewport().repaint()
    on_screen = lambda i: lst.visualRect(lst.model().index(i, 0)).bottom() < lst.viewport().height()
    i = next(i for i, e in enumerate(lst.model().entries)
             if e[0] == rows.ROW and len(e[1].episodes) >= 2 and on_screen(i))
    row = lst.model().entries[i][1]
    ids = {(ep.id, False) for ep in row.episodes}
    before = lst.delegate.warmed
    lst._hover = i
    lst._rest()                                          # the list has just moved
    lst._warm_hovered()                                  # at once: still moving, so nothing is painted
    assert lst.delegate.warmed == before
    assert not any(k[1] in ids for k in lst.delegate._sprites["ep"])
    assert lst._hover_warm.isActive()                    # re-armed for when the list rests
    assert wait_until(lambda: any(k[1] in ids for k in lst.delegate._sprites["ep"]), 10)


def test_a_user_scroll_step_lands_on_a_whole_device_pixel_so_the_drawn_rows_move(seeded, monkeypatch):
    """Review C-2: a step that isn't a whole device pixel (a drag, a notch, an arrow) makes Qt repaint the whole list
    instead of moving the pixels already drawn (1, 7, 13 px at 150 % painted 514 px). The step is snapped away from
    where it was to a multiple of the ratio's whole step, so a learner's scroll stays smooth at every text scale."""
    from PyQt6.QtWidgets import QAbstractSlider

    assert [rows.whole_step(d) for d in (1.0, 1.25, 1.5, 1.75, 2.0, 2.5)] == [1, 4, 2, 4, 1, 2]

    seed, win = seeded(files=2000)
    bar = current(win).verticalScrollBar()
    monkeypatch.setattr(rows, "whole_step", lambda dpr: 4)
    bar.setSingleStep(7)
    bar.setValue(400)
    bar.triggerAction(QAbstractSlider.SliderAction.SliderSingleStepAdd)
    assert bar.value() == 408                                  # 407 snapped up to the next multiple of 4
    bar.setValue(400)
    bar.triggerAction(QAbstractSlider.SliderAction.SliderSingleStepSub)
    assert bar.value() == 392                                  # 393 snapped down to the multiple below


def test_a_list_at_rest_lets_go_of_pixmaps_of_another_screen_ratio(seeded):
    """Review C-5: a row pixmap painted at another screen ratio (a window dragged to a monitor at another scale) can
    never be drawn again on this screen, so a list at rest must let it go, with its bytes counted out. Kept, it would
    hold memory the screen can't use, and the byte count would drift from what is really held."""
    seed, win = seeded()
    lst = current(win)
    lst.viewport().repaint()
    d = lst.delegate
    assert d._sprites["row"], "the first screen should have painted rows to test with"
    original = next(k for k in d._sprites["row"] if k[4] == 1.0 and k[5] == style.current())
    payload, pix = d._sprites["row"][original]
    other = original[:4] + (2.0,) + original[5:]              # the same row, painted for a 200 % screen
    d._sprites["row"][other] = (payload, pix)
    d._bytes["row"] += rows._size(pix)
    d.keep_only(lst.model().entries, 1.0, original[2])
    assert other not in d._sprites["row"], "a pixmap of another screen ratio is kept at rest"
    assert original in d._sprites["row"], "the pixmap for this screen was let go"
    assert d._bytes["row"] == sum(rows._size(v[1]) for v in d._sprites["row"].values())


def test_a_stale_hover_scrolled_off_screen_warms_no_episodes_once_the_list_rests(seeded):
    """Review C-4: a wheel scroll moves no pointer, so the hover can still name a row the list has scrolled past. Nobody
    sees that row's episodes, and painting them would only push out what is on screen, so a stale hover off screen
    warms nothing once the list rests."""
    seed, win = seeded(files=2000)
    lst = current(win)
    bar = lst.verticalScrollBar()
    vp = lst.viewport()
    model = lst.model()
    i = next(i for i, e in enumerate(model.entries)
             if e[0] == rows.ROW and len(e[1].episodes) >= 2 and e[1].key != model.open_key)
    ids = {(ep.id, False) for ep in model.entries[i][1].episodes}
    index = model.index(i, 0)
    bar.setValue(bar.value() + lst.visualRect(index).top())             # the row at the top of the screen...
    bar.setValue(bar.value() + 2 * vp.height())                         # ...then scrolled well past it
    for _ in range(5):
        QApplication.processEvents()
    assert not lst.visualRect(index).intersects(vp.rect())              # precondition: the row is off screen
    assert wait_until(lambda: not lst._warm.isActive())                 # the list's own warm has run out
    assert not any(k[1] in ids for k in lst.delegate._sprites["ep"])    # nothing of this row painted so far
    before = lst.delegate.warmed
    lst._hover = i                                                      # the pointer's hover, left behind by the wheel
    lst._moved = 0.0                                                    # the list rested long ago
    lst._warm_hovered()
    assert lst.delegate.warmed == before
    assert not any(k[1] in ids for k in lst.delegate._sprites["ep"])


def _ground_strip_below_last_row(lst):
    """The share of ground-coloured pixels in the viewport strip under the last row (from its bottom edge down)."""
    last = lst.model().rowCount() - 1
    bottom = lst.visualRect(lst.model().index(last, 0)).bottom()
    lst.viewport().repaint()
    arr = rgb_array(lst.viewport().grab())
    strip = arr[bottom + 1:, :, :]
    return strip.shape[0], count(strip, rows.c("bg").name()) / float(strip.shape[0] * strip.shape[1])


def test_the_list_ground_shows_under_the_last_row_before_and_after_it_is_opened_and_closed(seeded):
    """The list's viewport is opaque (it paints no ground of its own), so the list paints its ground itself: the space
    under the last row must show the list's ground, not black or leftover pixels, or a learner sees a torn window at
    the foot of his list. Checked before a row is opened and again after the last row is opened and closed (review
    C-10: a grab after closing the last row)."""
    seed, win = seeded(size=(1280, 1400))
    lst = current(win)
    for _ in range(20):
        QApplication.processEvents()
    height, share = _ground_strip_below_last_row(lst)
    assert height >= 20, height                                       # the list is taller than its rows
    assert share >= 0.95, share
    last = lst.model().rowCount() - 1
    lst.toggle(lst.model().index(last, 0))                            # open the last row ...
    lst.doItemsLayout()
    lst.toggle(lst.model().index(last, 0))                            # ... and close it again
    lst.doItemsLayout()
    for _ in range(20):
        QApplication.processEvents()
    height, share = _ground_strip_below_last_row(lst)
    assert height >= 20, height
    assert share >= 0.95, share


def test_a_file_arriving_above_moves_the_numbers_and_draws_no_row_afresh(seeded):
    """A file that lands above the screen moves every row below it one place, so each row's number changes. The number
    is drawn over the row's pixmap, so the rows on screen are shown again from their pixmaps and none is painted afresh:
    a learner's list keeps its speed when a file arrives above where he is reading."""
    seed, win = seeded(files=2000)
    lst = current(win)
    lst.verticalScrollBar().setValue(lst.verticalScrollBar().maximum() // 2)
    for _ in range(20):
        QApplication.processEvents()
    lst.viewport().repaint()
    idx = lst.indexAt(QPoint(4, 1))
    assert lst.model().entries[idx.row()][0] == rows.ROW          # the row on screen is a closed row, not a line
    key = rows.RowsModel.key_of(lst.model().entries[idx.row()])
    before = lst.model().entries[idx.row()][1].index
    renders = lst.delegate.renders
    first = next(r for r in seed.items if r["tier"] == "now")
    seed.library.commit(items=[dict(first, id=10 ** 6, ord=first["ord"] - 512, piece_id=10 ** 6,
                                    rel_path="HighPriority/Hato/new - 01.srt", title="new - 01.srt")], order=True)
    assert wait_until(lambda: lst.model().entries[0][1].key == f"p{10 ** 6}")
    for _ in range(20):
        QApplication.processEvents()
    lst.viewport().repaint()
    assert lst.delegate.renders == renders                         # nothing on screen was drawn afresh
    row = lst.model().keys.index(key)
    assert lst.model().entries[row][1].index == before + 1         # ... yet its number moved (the test is not a no-op)


def test_a_relayout_reuses_each_rows_height_and_only_an_opened_row_or_a_new_look_works_one_out(qapp, seeded, monkeypatch):
    """A relayout (a row opened, a file arrived) asks every row its height. Working each one out again was most of a
    relayout's time at a few hundred rows, so a row's height is kept per entry, open or not, and look: a second relayout
    works out none, opening one row works out only that row, and a new text size works them all out again, once. The
    heights kept must be the ones a row would get afresh, or a row would paint over its neighbours."""
    seed, win = seeded()
    lst = current(win)
    lst.doItemsLayout()                                    # the first relayout fills the cache before the spy is put in
    QApplication.processEvents()
    real = lst.delegate._size_hint
    calls = []

    def spy(entry, is_open):
        calls.append((entry, is_open))
        return real(entry, is_open)

    monkeypatch.setattr(lst.delegate, "_size_hint", spy)
    try:
        lst.doItemsLayout()
        assert calls == [], len(calls)                     # a second relayout: every height is kept

        i = next(n for n, e in enumerate(lst.model().entries) if e[0] == rows.ROW)
        calls.clear()
        lst.toggle(lst.model().index(i, 0))                # open one row ...
        lst.doItemsLayout()
        assert len(calls) == 1, len(calls)                 # ... and only that row's height is worked out
        assert calls[0][1] is True

        calls.clear()
        style.apply(qapp, "hb", "L", "ja")                 # a new text size: the heights are worked out again
        lst.doItemsLayout()
        assert len(calls) >= 1, len(calls)
        calls.clear()
        lst.doItemsLayout()
        assert calls == []                                 # and then kept again

        for n, e in enumerate(lst.model().entries):       # the kept heights are the ones a row gets afresh
            is_open = lst.model().open_key == getattr(e[1], "key", None)
            kept = lst.delegate.sizeHint(None, lst.model().index(n, 0))
            assert kept.height() == real(e, is_open).height(), (n, kept.height())
    finally:
        style.apply(qapp, "hb", "M", "ja")                 # the harness puts back theme and size


def test_a_file_arriving_below_the_screen_draws_no_row_afresh_and_moves_nothing_on_screen(seeded):
    """A file that lands at the end of Soon, below where the learner is reading, is no change on his screen: the rows he
    sees keep their places and their numbers, and none is drawn again. A redraw that isn't needed is a slow list. (The
    screen's rows are still repainted from their kept pixmaps: Qt's list repaints its viewport on any row added — S19's
    written skip, `RowsModel.set_entries`, IK-38 — so this checks that none is drawn afresh, not that none is blitted.)"""
    seed, win = seeded(files=2000)
    lst = current(win)
    lst.verticalScrollBar().setValue(lst.verticalScrollBar().maximum() // 3)
    for _ in range(20):
        QApplication.processEvents()
    lst.viewport().repaint()

    def on_screen():
        seen = {}
        for y in range(1, lst.viewport().height(), 8):
            idx = lst.indexAt(QPoint(4, y))
            if idx.isValid():
                entry = lst.model().entries[idx.row()]
                seen[rows.RowsModel.key_of(entry)] = (lst.visualRect(idx).top(), getattr(entry[1], "index", None))
        return seen

    before = on_screen()
    assert before                                                  # something is on screen to compare
    renders = lst.delegate.renders
    last = max((r for r in seed.items if r["tier"] == "soon"), key=lambda r: r["ord"])
    seed.library.commit(items=[dict(last, id=10 ** 6, ord=last["ord"] + 512, piece_id=10 ** 6,
                                    rel_path="LowPriority/Hato/新着 - 01.srt", title="新着 - 01.srt")], order=True)
    assert wait_until(lambda: any(getattr(e[1], "key", None) == f"p{10 ** 6}" for e in lst.model().entries))
    for _ in range(20):
        QApplication.processEvents()
    lst.viewport().repaint()
    new_row = next(n for n, e in enumerate(lst.model().entries) if getattr(e[1], "key", None) == f"p{10 ** 6}")
    assert lst.visualRect(lst.model().index(new_row, 0)).top() > lst.viewport().height()   # it did land below the screen
    assert lst.delegate.renders == renders                         # nothing on screen drawn afresh (repainted from pixmaps)
    assert on_screen() == before                                   # same keys, same tops, same numbers


def test_the_same_status_snapshot_published_again_paints_no_widget_and_no_row(seeded, qapp):
    """The status service hands the bar a snapshot on every job tick and every events-file look. When nothing new
    came, the bar and the lists must not repaint: a window that flickers on every tick looks broken to a learner, and
    every needless row redraw is work the laptop does for nothing."""
    from PyQt6.QtCore import QEvent, QObject

    class Paints(QObject):
        def __init__(self):
            super().__init__()
            self.painted = []

        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.Type.Paint:
                self.painted.append((type(obj).__name__, obj.objectName()))
            return False

    seed, win = seeded()
    status = win.services.status
    lists = [p.list for p in win.page_widgets.values() if hasattr(p, "list")]
    assert lists, "the window has at least one list to watch"
    before_snapshot = status._snapshot
    before_paints = [lst.delegate.paints for lst in lists]
    spy = Paints()
    qapp.installEventFilter(spy)
    try:
        status._publish()                                   # the same state, delivered again
        QTest.qWait(500)
    finally:
        qapp.removeEventFilter(spy)
    assert status._snapshot is not before_snapshot          # the publish really happened, so the test isn't a no-op
    assert spy.painted == [], spy.painted
    assert [lst.delegate.paints for lst in lists] == before_paints


def test_a_goal_only_change_leaves_current_and_finished_entries_and_paint_alone(seeded):
    """A Goal item's watch is no row on Current or Finished: the reader builds a new view for it, but both lists keep
    the very same entries (nothing rebuilt, nothing marked changed) and paint no row again, so a write elsewhere never
    costs the learner a redraw of a list it didn't touch."""
    seed, win = seeded()
    goal = [r for r in seed.items if r["tier"] == "goal"]
    assert goal, "the small seed holds a Goal item"
    page = win.page_widgets["current"]
    lst = current(win)
    fin = win.page_widgets["finished"].list
    cur_entries, fin_entries = lst.model().entries, fin.model().entries
    cur_paints, fin_paints = lst.delegate.paints, fin.delegate.paints
    view_before = page.view_model
    builds = win.services.library.builds
    seed.library.commit(items=[{"id": goal[0]["id"], "watched": 1}])
    assert wait_until(lambda: win.services.library.builds > builds)
    assert wait_until(lambda: page.view_model is not view_before)    # the new view has reached the Current page
    for _ in range(5):
        QApplication.processEvents()
    assert lst.model().entries is cur_entries and lst.model().changed == []
    assert fin.model().entries is fin_entries and fin.model().changed == []
    assert lst.delegate.paints == cur_paints and fin.delegate.paints == fin_paints


def test_the_pointer_leaving_a_row_repaints_that_row_alone_from_its_kept_pixmap(seeded):
    """A learner moving the pointer down the list sees each row light up and go back. Leaving a row must repaint only
    that row, from the pixmap it kept before the hover: repainting the whole list (or drawing rows afresh) on every
    pointer move is what makes a long list stutter."""
    from PyQt6.QtCore import QEvent, QPointF
    from PyQt6.QtGui import QMouseEvent
    seed, win = seeded()
    lst = current(win)
    lst.viewport().repaint()                                             # every row on screen: its unhovered pixmap
    on_screen = lambda i: lst.visualRect(lst.model().index(i, 0)).bottom() < lst.viewport().height()
    shown = [i for i, e in enumerate(lst.model().entries) if e[0] == rows.ROW and on_screen(i)]
    assert len(shown) > 3, shown
    i = shown[len(shown) // 2]
    pos = QPointF(lst.visualRect(lst.model().index(i, 0)).center())
    QApplication.sendEvent(lst.viewport(), QMouseEvent(QEvent.Type.MouseMove, pos, Qt.MouseButton.NoButton,
                                                       Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
    for _ in range(5):
        QApplication.processEvents()
    assert lst._hover == i                                               # the row is hovered: the test isn't a no-op
    assert wait_until(lambda: not lst._hover_warm.isActive() and not lst._warm.isActive())   # the hover has settled
    paints, renders = lst.delegate.paints, lst.delegate.renders
    QApplication.sendEvent(lst, QEvent(QEvent.Type.Leave))
    for _ in range(5):
        QApplication.processEvents()
    assert lst._hover is None
    assert lst.delegate.paints - paints == 1, (lst.delegate.paints - paints, len(shown))   # exactly the row left
    assert lst.delegate.renders == renders                               # from its kept pixmap: nothing drawn afresh


def test_a_list_at_rest_paints_nothing_on_screen_while_it_paints_ahead(seeded):
    """Bench 10: once a list rests, it draws the rows just past its screen ahead, one per turn of the loop, and trims
    its pixmaps. All of that is off screen, so a resting list must not repaint what the reader can see: no row on
    screen is painted again or drawn afresh, while the rows ahead are drawn in the background."""
    seed, win = seeded()
    lst = current(win)
    bar = lst.verticalScrollBar()
    bar.setValue(bar.value() + round(theme.SIZES["row"] * rows.fz()) * 3)      # a few rows down, then the list rests
    for _ in range(5):
        QApplication.processEvents()
    paints, renders, warmed = lst.delegate.paints, lst.delegate.renders, lst.delegate.warmed
    QTest.qWait(1200)                                                          # nothing happens for a while
    assert lst.delegate.warmed > warmed, (warmed, lst.delegate.warmed)         # it did work ahead, off screen
    assert lst.delegate.paints == paints, (paints, lst.delegate.paints)        # no on-screen row painted again
    assert lst.delegate.renders == renders, (renders, lst.delegate.renders)    # and none drawn afresh


def test_a_row_takes_each_colour_from_the_theme_now_applied_and_asking_twice_gives_the_same(qapp):
    """A row's colours are kept once per theme (its first paint asks for about twelve), so a theme change must hand the
    new theme's colour, not the one kept from the last theme, or rows would keep painting in the old theme's inks until
    the app restarts. Asking a second time gives the same colour."""
    try:
        for t in theme.THEMES:
            style.apply(qapp, t, "M", "ja")
            for name in ("bg", "surface", "ink", "ink-dim", "accent"):
                want = style.qcolor(style.colours()[name]).rgba()
                assert rows.c(name).rgba() == want, (t, name)
                assert rows.c(name).rgba() == want, (t, name, "second ask")
    finally:
        style.apply(qapp, "hb", "M", "ja")                 # the harness puts back theme and size


def test_the_pointer_resting_on_a_closed_row_paints_its_open_head_ahead_so_opening_it_draws_no_head_afresh(seeded):
    """Bench 9, speed round 5: opening a row was also its head's first paint. A pointer resting on a closed row paints
    the row's open head ahead, hovered as the click will show it, so opening blits the head from its pixmap; the head
    is drawn afresh by nothing the click does (the renders count is kept across the open)."""
    from PyQt6.QtCore import QEvent, QPointF
    from PyQt6.QtGui import QHoverEvent, QMouseEvent
    seed, win = seeded()
    lst = current(win)
    lst.viewport().repaint()
    on_screen = lambda i: lst.visualRect(lst.model().index(i, 0)).bottom() < lst.viewport().height()
    i = next(i for i, e in enumerate(lst.model().entries)
             if e[0] == rows.ROW and len(e[1].episodes) >= 2 and on_screen(i))
    row = lst.model().entries[i][1]
    head_warmed = lambda: any(k[1] == (row.key, "open") for k in lst.delegate._sprites["row"])
    assert not head_warmed()                                             # nothing warmed before the pointer arrives
    pos = QPointF(lst.visualRect(lst.model().index(i, 0)).center())
    QApplication.sendEvent(lst.viewport(), QHoverEvent(QEvent.Type.HoverMove, pos,
                                                       QPointF(lst.viewport().mapToGlobal(pos.toPoint())),
                                                       QPointF(-1, -1)))
    QApplication.sendEvent(lst.viewport(), QMouseEvent(QEvent.Type.MouseMove, pos, Qt.MouseButton.NoButton,
                                                       Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
    assert wait_until(head_warmed)                                       # the open head is painted ahead
    assert wait_until(lambda: not lst._hover_warm.isActive())            # the warm has run out of work in view
    renders = lst.delegate.renders
    lst.toggle(lst.model().index(i, 0))
    lst.doItemsLayout()
    lst.viewport().repaint()
    assert lst.model().open_key == row.key
    assert lst.delegate.renders == renders                               # opening draws no row, its head included


def test_a_look_that_finds_the_store_unchanged_reads_builds_and_paints_nothing(seeded):
    """The reader looks every 20 ms and most looks find the store as it was. Each must return before it reads the feed
    or builds a view, so a window left open on a learner's desk costs nothing while he reads. A real change still reads
    and builds, so the quiet check is not a no-op."""
    seed, win = seeded()
    reader = win.services.library
    lists = [current(win), win.page_widgets["finished"].list]
    QTest.qWait(500)                                          # the first looks after the open settle
    reads, builds = reader.reads, reader.builds
    paints = [lst.delegate.paints for lst in lists]
    reader.refresh()
    QTest.qWait(500)
    assert reader.reads == reads and reader.builds == builds
    assert [lst.delegate.paints for lst in lists] == paints
    lst = current(win)
    i, (kind, row, _l) = next((i, e) for i, e in enumerate(lst.model().entries) if e[0] == rows.ROW)
    seed.library.commit(items=[{"id": row.episodes[0].id, "watched": 1 - int(row.episodes[0].watched)}])
    assert wait_until(lambda: reader.reads > reads and reader.builds > builds)
    assert wait_until(lambda: lst.model().entries[i][1] is not row)


def test_focus_in_and_out_repaints_only_the_current_row(seeded):
    """Qt repaints a whole list when it gains or loses focus, but only the current row's ring changes. Each focus change
    paints that one row and no other: a learner tabbing between his list and the tabs sees no needless redraw."""
    seed, win = seeded()
    lst = current(win)
    win.tab_buttons["current"].setFocus(Qt.FocusReason.TabFocusReason)
    for _ in range(5):
        QApplication.processEvents()
    i = next(n for n, e in enumerate(lst.model().entries)          # a closed row on screen (the hero is not one)
             if e[0] == rows.ROW and lst.visualRect(lst.model().index(n, 0)).intersects(lst.viewport().rect()))
    lst.setCurrentIndex(lst.model().index(i, 0))                  # made current while the list has no focus
    for _ in range(5):
        QApplication.processEvents()
    before = lst.delegate.paints

    lst.setFocus(Qt.FocusReason.TabFocusReason)
    for _ in range(5):
        QApplication.processEvents()
    assert lst.hasFocus()
    assert lst.delegate.paints == before + 1, lst.delegate.paints - before  # focus in: the current row alone

    before = lst.delegate.paints
    win.tab_buttons["current"].setFocus(Qt.FocusReason.TabFocusReason)
    for _ in range(5):
        QApplication.processEvents()
    assert not lst.hasFocus()
    assert lst.delegate.paints == before + 1, lst.delegate.paints - before  # focus out: the current row alone


def test_keyboard_focus_in_makes_the_first_row_current_without_scrolling(seeded):
    """With no current row, a keyboard focus-in makes one current where the list stands: Qt's own first-row step is kept,
    but the list does not jump to show it, so a learner who scrolled half way stays where he was."""
    seed, win = seeded(files=2000)
    lst = current(win)
    win.tab_buttons["current"].setFocus(Qt.FocusReason.TabFocusReason)
    for _ in range(5):
        QApplication.processEvents()
    lst.setCurrentIndex(lst.model().index(-1, 0))                 # no current row
    lst.verticalScrollBar().setValue(lst.verticalScrollBar().maximum() // 2)
    for _ in range(5):
        QApplication.processEvents()
    scrolled = lst.verticalScrollBar().value()
    assert scrolled > 0                                           # really scrolled, not left at the top

    lst.setFocus(Qt.FocusReason.TabFocusReason)
    for _ in range(5):
        QApplication.processEvents()
    assert lst.currentIndex().isValid()
    assert lst.verticalScrollBar().value() == scrolled


def _number_spy(lst, monkeypatch):
    """Record the place each _paint_number call draws, and still draw it (the real call)."""
    drawn = []
    real = lst.delegate._paint_number

    def spy(p, row, body, dpr):
        drawn.append(row.index)
        real(p, row, body, dpr)
    monkeypatch.setattr(lst.delegate, "_paint_number", spy)
    return drawn


def test_every_closed_row_on_screen_shows_its_own_number_and_no_other_entry_does(seeded, monkeypatch):
    """A learner finds his place in Current by the number on each row: every closed row on screen draws its own
    place, and only rows do — never the hero, a month or a finished row."""
    seed, win = seeded()
    lst = current(win)
    drawn = _number_spy(lst, monkeypatch)
    lst.doItemsLayout()                                   # the rows' places settle before the repaint
    lst.viewport().repaint()
    model = lst.model()
    view = lst.viewport().rect()
    expected = [e[1].index for i, e in enumerate(model.entries)
                if e[0] == rows.ROW and e[1].key != model.open_key
                and lst.visualRect(model.index(i, 0)).intersects(view)]
    assert expected, "the seed should put at least one closed row on screen"
    assert sorted(drawn) == sorted(expected)


def test_an_open_rows_head_draws_its_number_too(seeded, monkeypatch):
    """Opening a row must not lose its place: the open row's head draws its number over its pixmap, as a closed row
    does."""
    seed, win = seeded()
    lst = current(win)
    i, (kind, row, _l) = next((i, e) for i, e in enumerate(lst.model().entries) if e[0] == rows.ROW)
    before = lst.visualRect(lst.model().index(i, 0)).height()
    lst.toggle(lst.model().index(i, 0))
    assert wait_until(lambda: lst.visualRect(lst.model().index(i, 0)).height() > before)
    assert lst.model().open_key == row.key
    drawn = _number_spy(lst, monkeypatch)
    lst.viewport().repaint()
    assert drawn.count(row.index) == 1


def _rows_on_screen(lst):
    """The closed rows on screen, top to bottom, as (entry index, row payload)."""
    screen = lst.viewport().rect()
    return [(i, e[1]) for i, e in enumerate(lst.model().entries)
            if e[0] == rows.ROW and lst.visualRect(lst.model().index(i, 0)).intersects(screen)]


def test_a_file_arriving_on_screen_draws_exactly_one_row_afresh_and_only_moves_the_numbers_below_it(seeded):
    """A file that lands where the learner is reading gets a row of its own, and that row is the only one drawn: the rows
    below it stay on their pixmaps and only their numbers move down one, so a new file never makes the list stutter
    under his eyes."""
    seed, win = seeded(files=2000)
    lst = current(win)
    lst.viewport().repaint()
    on = _rows_on_screen(lst)
    assert len(on) >= 6, len(on)                                   # rows below the 4th are on screen to be checked
    fourth = on[3][1]
    item = next(r for r in seed.items if r["id"] == fourth.episodes[0].id)
    before = {r.key: r.index for _i, r in on}
    renders = lst.delegate.renders
    new_key = f"p{10 ** 6}"
    new = dict(item, id=10 ** 6, ord=item["ord"] - 0.5, piece_id=10 ** 6,
               rel_path=item["rel_path"].rsplit("/", 1)[0] + "/new - 01.srt", title="new - 01.srt",
               availability="missing")                             # a file not yet on disk: the top 20 (available files) stay put
    seed.library.commit(items=[new], order=True, availability=True)
    assert wait_until(lambda: any(getattr(e[1], "key", None) == new_key for e in lst.model().entries))
    for _ in range(20):
        QApplication.processEvents()
    lst.viewport().repaint()
    shown = _rows_on_screen(lst)
    keys = [r.key for _i, r in shown]
    assert keys[3] == new_key, keys[:5]                            # it landed just above the 4th row
    assert lst.delegate.renders == renders + 1                     # the new row, and no other row drawn afresh
    moved = 0
    for pos, (_i, r) in enumerate(shown):
        if r.key == new_key or r.key not in before:
            continue
        if pos < 3:
            assert r.index == before[r.key], (pos, r.index)        # the rows above it keep their numbers
        else:
            assert r.index == before[r.key] + 1, (pos, r.index)    # the rows below it moved one number down
            moved += 1
    assert moved >= 2, moved                                       # the 4th and 5th rows were really checked, not an empty screen


def test_a_refresh_that_changes_nothing_starts_no_paint_ahead_and_paints_nothing(seeded):
    """S19 (Sonic, 2026-10-08): a refresh that came back the same is no reason to work. The same entries handed to a
    list again repaint no row and don't restart its paint-ahead timer (the idle walk over the rows ahead and the trim);
    a refresh that did change a row still restarts it."""
    seed, win = seeded()
    lst = current(win)
    assert wait_until(lambda: not lst._warm.isActive())         # the list has rested and painted ahead
    paints = lst.delegate.paints
    assert lst.set_entries(list(lst.model().entries)) == "same"
    for _ in range(5):
        QApplication.processEvents()
    assert not lst._warm.isActive()
    assert lst.delegate.paints == paints
    entries = list(lst.model().entries)
    i = next(n for n, e in enumerate(entries) if e[0] == rows.ROW)
    kind, row, lines = entries[i]
    entries[i] = (kind, row._replace(title=row.title + "（改）"), lines)     # one row changed: work restarts
    assert lst.set_entries(entries) == "same" and lst.model().changed == [i]
    assert lst._warm.isActive()


_FACE = ("title", "line", "pct", "pct_tone", "n_new", "status", "mark", "can_play", "cover_title", "studying",
         "n_files", "n_watched", "chips", "date")


def _face(row):
    """What the learner would see of a closed row: the shown fields as one tuple."""
    return tuple(getattr(row, name) for name in _FACE)


def test_an_available_file_arriving_on_screen_draws_afresh_only_the_new_row_and_the_rows_whose_face_changed(seeded):
    """A file that lands where the learner is reading pushes one row past the top-20 line. That row is rebuilt because
    its episodes moved, but usually it looks the same, so it keeps its picture: only the new row and the rows whose
    look really changed are drawn again, and the list never redraws what the learner cannot see change."""
    seed, win = seeded(files=2000)
    lst = current(win)
    line_at = next(i for i, e in enumerate(lst.model().entries) if any(ln.kind == "top" for ln in e[2]))
    lst.scrollTo(lst.model().index(line_at, 0))
    for _ in range(20):
        QApplication.processEvents()
    lst.viewport().repaint()
    on = _rows_on_screen(lst)
    assert line_at in [i for i, _r in on], line_at                 # the row holding the top-20 line is on screen
    above = [r for i, r in on if i < line_at]
    assert len(above) >= 2, len(above)                             # two rows above the line, to land a file between them
    target = above[1]
    before = {r.key: r for _i, r in on}
    renders = lst.delegate.renders
    item = next(r for r in seed.items if r["id"] == target.episodes[0].id)
    new_key = f"p{10 ** 6}"
    new = dict(item, id=10 ** 6, ord=item["ord"] - 0.5, piece_id=10 ** 6,
               rel_path=item["rel_path"].rsplit("/", 1)[0] + "/new - 01.srt", title="new - 01.srt",
               availability="available")                           # an available file: it takes a place in the top 20
    seed.library.commit(items=[new], order=True)
    assert wait_until(lambda: any(getattr(e[1], "key", None) == new_key for e in lst.model().entries))
    for _ in range(20):
        QApplication.processEvents()
    lst.viewport().repaint()
    shown = _rows_on_screen(lst)
    after = {r.key: r for _i, r in shown}
    assert [r.key for _i, r in shown][1] == new_key, [r.key for _i, r in shown][:4]   # it landed just above the target
    changed = [k for k in before if k in after and _face(before[k]) != _face(after[k])]
    crossed = [k for k in before if k in after and after[k] is not before[k] and _face(after[k]) == _face(before[k])
               and after[k].episodes != before[k].episodes]        # rebuilt (its episodes moved), same look: kept
    assert crossed, "no on-screen row was rebuilt with an unchanged face, so the test would prove nothing"
    assert lst.delegate.renders == renders + 1 + len(changed)      # the new row, and each row whose look changed


def test_a_relayout_makes_the_height_list_once_and_reads_it_for_every_row(seeded, monkeypatch):
    """Speed round 5: Qt asks every row's height on a relayout, one call each, so each answer must be one look in a
    list made once for the entries, the open row and the look: a second relayout makes it no more, opening a row makes
    it once, and the heights it answers are each row's own."""
    seed, win = seeded()
    lst = current(win)
    lst.doItemsLayout()
    made = []
    real = lst.delegate._heights_now
    monkeypatch.setattr(lst.delegate, "_heights_now", lambda model: (made.append(1), real(model))[1])
    lst.doItemsLayout()
    assert made == []                                           # the same entries, open row and look: the list kept
    i = next(n for n, e in enumerate(lst.model().entries) if e[0] == rows.ROW)
    lst.toggle(lst.model().index(i, 0))
    lst.doItemsLayout()
    assert len(made) == 1                                       # another open row: made once, for every row
    for n, e in enumerate(lst.model().entries):
        is_open = lst.model().open_key == getattr(e[1], "key", None)
        assert lst.delegate.sizeHint(None, lst.model().index(n, 0)) == lst.delegate._size_hint(e, is_open), n
    assert len(made) == 1


def test_a_setting_no_screen_reads_paints_no_widget_and_no_row(seeded, qapp):
    """A settings write that no screen shows (reduced motion, which no screen reads yet) must not repaint. The window
    hears every landed write, but a change it doesn't show is no change on screen: a window that flickers on an
    unrelated save looks broken to a learner, and every needless row redraw is work the laptop does for nothing."""
    from PyQt6.QtCore import QEvent, QObject

    class Paints(QObject):
        def __init__(self):
            super().__init__()
            self.painted = []

        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.Type.Paint:
                self.painted.append((type(obj).__name__, obj.objectName()))
            return False

    seed, win = seeded()
    lists = [p.list for p in win.page_widgets.values() if hasattr(p, "list")]
    assert lists, "the window has at least one list to watch"
    heard = []
    win.bridge.settings_written.connect(lambda keys: heard.append(tuple(keys)))
    before_paints = [lst.delegate.paints for lst in lists]
    spy = Paints()
    qapp.installEventFilter(spy)
    try:
        win.services.settings.set({"motion": "reduced"})   # the write is queued; it lands on the writer's thread
        assert wait_until(lambda: any("motion" in keys for keys in heard))   # it really reached the window, so no no-op
        QTest.qWait(500)                                    # nothing happens for a while: any repaint would show here
    finally:
        qapp.removeEventFilter(spy)
    assert spy.painted == [], spy.painted
    assert [lst.delegate.paints for lst in lists] == before_paints


def test_a_closed_rows_picture_never_shows_its_number_its_episode_count_or_its_descriptions(seeded):
    """A closed row's picture shows its title, cover, line, status and the diff, never its place in Current, how many
    episodes it has, or its screen-reader and tooltip text. So when a rebuilt row differs only there, its picture is
    kept and nothing is redrawn: the learner sees the same row either way (Sonic's S19)."""
    seed, win = seeded()
    lst = current(win)
    i, (kind, row, lines) = next(
        (n, e) for n, e in enumerate(lst.model().entries)
        if e[0] == rows.ROW and len(e[1].episodes) >= 2 and len(e[1].title) <= 12 and e[1].key != lst.model().open_key)
    row = row._replace(title="霧の町")      # short: a title one character longer must still fit, not be cut to the same "…"
    other = row._replace(episodes=row.episodes[:1], accessible="別の説明", description="別の説明", index=row.index + 7)
    assert other != row and len(other.episodes) != len(row.episodes)
    size = lst.visualRect(lst.model().index(i, 0)).size()
    size.setWidth(1100)            # a narrower picture elides the title away, and then no title change can show

    def paint(payload):
        img = QImage(size, QImage.Format.Format_RGB32)
        img.fill(QColor("#1e1e1e"))
        p = QPainter(img)
        lst.delegate._paint_row(p, rows.ROW, payload, QRect(0, 0, size.width(), size.height()), False, False,
                                1.0, lines, number=False)
        p.end()
        return rgb_array(img)

    before, after = paint(row), paint(other)
    assert (before != before[0, 0]).any(), "the closed row painted nothing, so the test would prove nothing"
    retitled = paint(row._replace(title=row.title + "改"))
    assert (retitled != before).any(), "a changed title left the picture as it was, so the comparison could not see text"
    assert before.shape == after.shape and (before == after).all()     # the number, the count and the text stay off the picture
    assert rows._same_face(row, other, rows.ROW)


def test_a_numbers_refresh_compares_only_the_rows_near_the_screen_and_repaints_none(seeded, monkeypatch):
    """Bench D-1: a numbers version rebuilt every row as a new object with the same fields, and the window's thread
    compared all 2,000 of them (~6 ms). A refresh that changes nothing a learner sees now asks about the rows on
    screen and those painted ahead only, and paints no row again."""
    seed, win = seeded(files=2000)
    lst = current(win)
    model = lst.model()
    bar = lst.verticalScrollBar()
    bar.setValue(bar.maximum() // 3)                          # about a third of the way down the list
    for _ in range(20):
        QApplication.processEvents()
    lst.viewport().repaint()
    QTest.qWait(500)                                          # the list rests: the rows ahead are painted
    n = model.rowCount()
    first = lst.indexAt(QPoint(4, 1)).row()
    last = lst.indexAt(QPoint(4, lst.viewport().height() - 2)).row()
    on_screen = last - first + 1
    new = [(kind, payload._replace() if kind in (rows.ROW, rows.FINISHED) else payload, lines)
           for kind, payload, lines in model.entries]
    calls = []
    real = model.looks_different
    monkeypatch.setattr(model, "looks_different", lambda i: (calls.append(i), real(i))[1])
    renders = lst.delegate.renders
    assert lst.set_entries(new) == "same"
    assert len(calls) <= on_screen + 2 * rows.WARM_AHEAD + 2, (len(calls), on_screen)
    assert len(calls) < n, (len(calls), n)                    # not every row: the rows far off are never compared
    for _ in range(20):
        QApplication.processEvents()
    lst.viewport().repaint()
    assert lst.delegate.renders == renders


def test_a_same_refresh_keeps_the_list_heights_and_works_no_height_out_again(seeded, monkeypatch):
    """Review D-2: a refresh that changes only what a row shows (one show's next-episode line) leaves every row as tall
    as it was, so the height list is carried over and no height is worked out again on the window's thread. Making it
    again walked every entry (~6 ms at 20,000), a stutter a learner feels while the library updates under the scroll."""
    seed, win = seeded()
    lst = current(win)
    lst.viewport().repaint()
    i = next(n for n, e in enumerate(lst.model().entries) if e[0] == rows.ROW)
    assert lst.viewport().rect().intersects(lst.visualRect(lst.model().index(i, 0))), "the row must be on screen"
    lst.delegate.sizeHint(None, lst.model().index(i, 0))      # the heights exist before the refresh
    made = []
    real = lst.delegate._heights_now
    monkeypatch.setattr(lst.delegate, "_heights_now", lambda m: (made.append(1), real(m))[1])
    entries = [tuple(e) for e in lst.model().entries]
    kind, row, lines = entries[i]
    entries[i] = (kind, row._replace(line="次は第4話 · 残り3話"), lines)
    assert lst.set_entries(entries) == "same"                 # every shape as it was: a "same" refresh
    for _ in range(20):
        QApplication.processEvents()
    lst.viewport().repaint()
    for n in range(max(0, i - 3), min(len(lst.model().entries), i + 4)):
        lst.delegate.sizeHint(None, lst.model().index(n, 0))
        lst.visualRect(lst.model().index(n, 0))
    assert made == [], "the heights were worked out again after a same refresh"


def test_a_file_joining_a_closed_row_is_a_same_refresh_and_one_joining_the_open_row_is_a_relayout(seeded):
    """D-3: a closed row's episodes decide no height, so a new file joining a closed row changes nothing about how tall
    the list is. That refresh is "same" and only that row is repainted. The open row's episodes do decide its height,
    so a new file joining it is a relayout. Both matter because files arrive while a learner has a row open on his
    desk: a closed row must not push every other row around."""
    seed, win = seeded()
    lst = current(win)
    i, (kind, row, lines) = next((n, e) for n, e in enumerate(lst.model().entries)
                                 if e[0] == rows.ROW and len(e[1].episodes) >= 2)
    key = row.key
    entries = list(lst.model().entries)
    entries[i] = (kind, row._replace(episodes=row.episodes + (row.episodes[-1]._replace(id=10 ** 7),)), lines)
    assert lst.set_entries(entries) == "same"                  # the closed row gained an episode: no height moved
    assert len(entry_of(lst, key)[1][1].episodes) == len(row.episodes) + 1

    lst.toggle(lst.model().index(i, 0))                        # open the same row, as a click does
    lst.doItemsLayout()
    lst.viewport().repaint()
    assert lst.model().open_key == key
    i, (kind, row, lines) = entry_of(lst, key)
    entries = list(lst.model().entries)
    entries[i] = (kind, row._replace(episodes=row.episodes + (row.episodes[-1]._replace(id=10 ** 7 + 1),)), lines)
    assert lst.set_entries(entries) == "relayout"              # the open row grew: its height grew too


def test_an_open_head_painted_ahead_takes_only_free_room_and_never_pushes_a_row_out(seeded, monkeypatch):
    """Bench 9, speed round 5 (review D-4): an open head painted ahead is only a guess at what a click will want, so it
    takes free room and never evicts. With room it is drawn and goes first in the cache's order (the first to go when a
    real row needs the room); with none it is not drawn, and every row already painted is still in the cache, so a
    pointer resting on a closed row never pushes out the rows a learner is looking at."""
    from PyQt6.QtCore import QEvent, QPointF
    from PyQt6.QtGui import QHoverEvent, QMouseEvent
    seed, win = seeded()
    lst = current(win)
    lst.viewport().repaint()
    on_screen = lambda i: lst.visualRect(lst.model().index(i, 0)).bottom() < lst.viewport().height()
    closed = [i for i, e in enumerate(lst.model().entries)
              if e[0] == rows.ROW and len(e[1].episodes) >= 2 and on_screen(i)]
    assert len(closed) >= 2, "two closed rows with episodes on screen: one to hover, then another"
    i, j = closed[0], closed[1]
    row_i, row_j = lst.model().entries[i][1], lst.model().entries[j][1]
    cache = lst.delegate._sprites["row"]

    def hover(index):
        pos = QPointF(lst.visualRect(lst.model().index(index, 0)).center())
        QApplication.sendEvent(lst.viewport(), QHoverEvent(QEvent.Type.HoverMove, pos,
                                                           QPointF(lst.viewport().mapToGlobal(pos.toPoint())),
                                                           QPointF(-1, -1)))
        QApplication.sendEvent(lst.viewport(), QMouseEvent(QEvent.Type.MouseMove, pos, Qt.MouseButton.NoButton,
                                                           Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))

    # with room: the head is drawn and goes first in the cache's order
    hover(i)
    assert wait_until(lambda: any(k[1] == (row_i.key, "open") for k in cache))
    assert wait_until(lambda: not lst._hover_warm.isActive())       # its episodes too: the warm looked at the head again
    assert next(iter(cache))[1] == (row_i.key, "open")             # ... and left it first to go
    # no room: the cache holds what it holds now, with room for the hovered row's own paint and none for a head
    assert wait_until(lambda: not lst._warm.isActive())               # the list at rest has finished its paint ahead
    before = list(cache)
    monkeypatch.setattr(rows, "SPRITES_KEPT", len(cache) + 1)
    hover(j)
    assert wait_until(lambda: any(k[1] == row_j.key and k[6] for k in cache))   # the hovered row itself is painted
    assert wait_until(lambda: not lst._hover_warm.isActive())                   # then the head's warm has had its turn
    assert not any(k[1] == (row_j.key, "open") for k in cache)        # no head drawn without room
    assert all(k in cache for k in before)                            # and no row pushed out for it


def test_the_window_turning_active_or_inactive_repaints_no_row(seeded):
    """Qt's item view repaints its whole viewport when the window turns active or inactive, yet no row shows that state:
    a learner who clicks away to another app must not see every visible row drawn again for nothing (charter S19)."""
    from PyQt6.QtCore import QEvent, QObject

    class Paints(QObject):
        def __init__(self):
            super().__init__()
            self.painted = []

        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.Type.Paint:
                self.painted.append(type(obj).__name__)
            return False

    seed, win = seeded()
    lst = current(win)
    assert wait_until(lambda: not lst._warm.isActive(), 10)     # at rest: the rows ahead are painted, nothing more
    QTest.qWait(400)
    before = lst.delegate.paints
    spy = Paints()
    vp = lst.viewport()
    vp.installEventFilter(spy)
    try:
        QApplication.sendEvent(vp, QEvent(QEvent.Type.WindowDeactivate))
        QApplication.sendEvent(vp, QEvent(QEvent.Type.WindowActivate))
        QTest.qWait(500)                                        # nothing happens for a while: any repaint would show here
    finally:
        vp.removeEventFilter(spy)
    assert spy.painted == [], spy.painted
    assert lst.delegate.paints == before
