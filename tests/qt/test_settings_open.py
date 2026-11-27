"""Settings opened at a section (SETTINGS-OPEN, 3.0.21): what the open builds and reads, and when.

Train 98's watch: Settings › Anki & mining by a click took 2.6 s to the page built and 1.5 s to the section (v3.0.20:
2.2 s and 1.0 s). Measured by step: the click's own stretch attached all six packages' rows (150–340 ms) beside the
page's first reads; the section's 35 rows came a slice or two a turn, the loop laying out and painting the page between
(~1 s); the level read (every band's numbers over the token store, 0.7 s of Python cold) started at the page's making
and held Python's lock against every slice, for rows not on screen.

What a wrong answer would cost: a section opened by a link that fills in row by row for a second (the learner waits
for the row the link named); the slow read back on the open's path; a package's rows never attached, attached after
its row is shown (a row's control appearing late, the page moving), or attached twice; a reveal of a fallback row
read before its package filled it (the wrong row lit).

Never a timing here: what is built in which turn, which read is asked when, and how many times.
"""
import os
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from app.qt import settings_catalog as catalog
from app.qt import settings_live, shell
from app.qt import settings_page as sp
from tests.qt.conftest import wait_until
from tests.qt.test_settings_page import ALL_ON, EVERYTHING, Recorder, _at_third, _no_direct_save  # noqa: F401


def _page(data=None, language="ja"):
    """A page shown and not yet built (its build runs as the event loop turns), its packages attached as the window
    attaches them (`shell.settings_attaches`), each call recorded with the sections that had a row built by then."""
    store = Recorder(dict({"target_language": language}, **(data or ALL_ON)))
    page = sp.SettingsPage(SimpleNamespace(settings=store), language, found=EVERYTHING)
    calls = []
    for attach, rows in shell.settings_attaches():
        def recorded(p, _attach=attach):
            calls.append((_attach.__module__, {view.row.section for view in p.rows.values()}))
            return _attach(p)
        recorded.__module__ = attach.__module__
        later = getattr(page, "attach_later", None)             # (before SETTINGS-OPEN: attached at the mount)
        later(recorded, rows) if later is not None else recorded(page)
    page.resize(1100, 700)
    page.show()
    return page, calls


def _sections_of(rows):
    return {catalog.ROW[row_id].section for row_id in rows}


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_link_to_a_section_builds_it_whole_in_the_turn_after_the_click_then_brings_it_into_view(qapp, language):
    # the slab a reveal names is built in one go once the tab has painted (never a row or two a turn: 35 turns of the
    # loop's layout and paint for Anki & mining); the rest of the page goes on in slices after it
    page, _calls = _page(language=language)
    assert page.reveal("anki") is True
    assert not page._section_built("anki")                     # the click's own stretch: the frame only
    assert wait_until(lambda: page._section_built("anki"), 20)
    assert len(page.slice_ms) <= 2, page.slice_ms              # (the slices queued before the link; v3.0.21: 35)
    assert not page.built, "the rest of the page is still to come, in slices"
    assert page.built_order[0] == "anki"
    revealed = page._revealed
    assert revealed is page.rows[sp.SettingsPage._first_shown_row(page, "anki").row.id]
    assert wait_until(lambda: page.built, 20)
    QApplication.processEvents()
    assert _at_third(page, revealed)                            # kept in place while the slabs above it were built
    page.close()


def test_a_link_to_a_row_under_more_options_still_opens_its_fold_and_lands_on_it(qapp):
    page, _calls = _page()
    assert page.reveal("anki_connect_url") is True              # (Anki & mining's More options)
    assert wait_until(lambda: page._section_built("anki"), 20)
    QApplication.processEvents()
    assert "anki" in page.folds() and page.rows["anki_connect_url"].isVisibleTo(page)
    assert wait_until(lambda: page.built, 20)
    page.close()


def test_two_links_before_the_section_is_built_land_on_the_last(qapp):
    page, _calls = _page()
    page.reveal("anki")
    page.reveal("sentences")                                    # (the second link wins: its slab is built first)
    assert wait_until(lambda: page._section_built("sentences"), 20)
    assert page.built_order[0] == "sentences"
    assert wait_until(lambda: page.built, 20)
    page.close()


@pytest.mark.parametrize("target", ["anki", None])
def test_each_package_is_attached_once_just_before_its_sections_first_row(qapp, target):
    # opened at Anki & mining: Connect's, the store's and the AI voice's rows (they fill slots there) attached before
    # its first row; the placing rules (Arrivals), *Library folders* (Content), *Your settings* (App) only once the
    # build reaches them — never in the click's stretch. Opened at the top: each before its own sections, all by built
    page, calls = _page()
    if target:
        page.reveal(target)
        assert wait_until(lambda: page._section_built(target), 20)
        early = {module for module, _built in calls}
        assert "app.qt.settings_rules" not in early and "app.qt.settings_io" not in early
        assert {"app.qt.settings_connect", "app.qt.settings_store"} <= early
    assert wait_until(lambda: page.built, 20)
    modules = [module for module, _built in calls]
    assert sorted(modules) == sorted(a.__module__ for a, _rows in shell.settings_attaches())
    assert len(modules) == len(set(modules)), "each attached once"
    declared = {a.__module__: _sections_of(rows) for a, rows in shell.settings_attaches()}
    for module, built in calls:
        assert not (built & declared[module]), f"{module} attached after a row of its sections was built"
    page.close()


def test_a_fallback_row_read_before_its_package_is_attached_reads_its_filled_slot(qapp):
    # *Mine automatically: the top N* (`mine_line`, the store's) shows only once its slot is filled; a link to it
    # before the build reached Anki & mining must not fall back to the switch's row for an empty slot
    page, _calls = _page()
    assert page.shows("mine_line") is True
    assert page.custom_row("mine_line").layout().count() > 0
    assert page.reveal("mine_line") is True
    assert wait_until(lambda: page._section_built("anki"), 20)
    QApplication.processEvents()
    assert page._revealed is page.rows["mine_line"]
    assert wait_until(lambda: page.built, 20)
    page.close()


def test_each_package_fills_only_the_slots_it_declares(qapp):
    # `settings_attaches` names the rows each package fills: an undeclared slot would be attached late (after its row
    # was built and shown), a declared one it doesn't fill would attach it early for nothing
    for attach, rows in shell.settings_attaches():
        store = Recorder(dict(ALL_ON, target_language="ja"))
        page = sp.SettingsPage(SimpleNamespace(settings=store), "ja", found=EVERYTHING)    # (never shown: no build)
        before = {row_id for row_id, slot in page.slots.items() if slot.layout().count()}
        attach(page)
        filled = {row_id for row_id, slot in page.slots.items() if slot.layout().count()} - before
        assert filled == set(rows), (attach.__module__, sorted(filled ^ set(rows)))
        page.deleteLater()
    QApplication.processEvents()


@pytest.mark.parametrize("target", ["anki", None])
def test_the_level_read_is_asked_once_and_only_once_a_row_that_shows_it_is_built(qapp, monkeypatch, target):
    # every band's numbers over the token store (0.7 s of a worker's Python): asked for Your setup's level line or the
    # Level row, never at the page's making while the section a link named is built
    asked = []
    real = settings_live.Live._read_level

    def read_level(live):
        asked.append(set(live.page.rows) & set(settings_live.LEVEL_ROWS))
        return real(live)
    monkeypatch.setattr(settings_live.Live, "_read_level", read_level)
    page, _calls = _page()
    assert asked == [], "not at the page's making"
    if target:
        page.reveal(target)
        assert wait_until(lambda: page._section_built(target), 20)
        assert asked == [], "not while the section the link named is built"
    assert wait_until(lambda: page.built, 20)
    assert len(asked) == 1 and asked[0], asked                  # once, with a row there to show it
    page.close()


def test_a_package_whose_sections_build_no_row_is_still_attached_before_the_page_is_built(qapp):
    # (a package that names no row of the catalog's, or one whose rows all fail to build: attached all the same)
    page, _calls = _page()
    seen = []
    page.attach_later(lambda p: seen.append(p.built), ())
    assert wait_until(lambda: page.built, 20)
    assert seen == [False]
    page.close()



# --- SETTINGS-OPEN 2: the rest of the open ------------------------------------------------------------------------- #
# Measured at SETTINGS-OPEN's head (Anki & mining by a click, my lib2k): the click's stretch imported the page's modules
# (60–240 ms) and drew its frame's 28 nav icons (QIcon's enums made with them: ~100 ms); the page's first reads, `_warm`,
# the modules' look and the AI voice row's look went to workers at the page's making and took Python's lock from the
# section's turn (100–250 ms of worker time beside it); then every slice of the rest settled the whole page's layout
# ten passes deep twice (a reveal's row in view) and showed its section again for each row it built.


def _jobs(monkeypatch, events):
    """Every job handed to a worker recorded in `events` as ("job", its name), in order with the build's own marks."""
    from app.qt import bridge
    real = bridge.run_in_worker

    def run(fn, *args, **kw):
        events.append(("job", getattr(fn, "__qualname__", repr(fn))))
        return real(fn, *args, **kw)
    monkeypatch.setattr(bridge, "run_in_worker", run)


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_links_section_is_built_before_any_of_the_pages_reads_goes_to_a_worker(qapp, monkeypatch, language):
    # the reads still all go — the known words, hato's entry, the licence, the modules' look — in the turn after the
    # section's, so none takes Python's lock from it
    events = []
    _jobs(monkeypatch, events)
    real_finish = sp.SettingsPage._finish_build_of

    def finish(page, section_id):
        real_finish(page, section_id)
        events.append(("built", section_id))
    monkeypatch.setattr(sp.SettingsPage, "_finish_build_of", finish)
    store = Recorder(dict(ALL_ON, target_language=language))
    page = sp.SettingsPage(SimpleNamespace(settings=store), language)      # (found=None: the modules looked for)
    for attach, rows in shell.settings_attaches():
        page.attach_later(attach, rows)
    page.resize(1100, 700)
    page.show()
    page.reveal("anki")
    assert [e for e in events if e[0] == "job"] == [], "nothing at the page's making"
    assert wait_until(lambda: page._section_built("anki"), 20)
    assert wait_until(lambda: {"read_hato", "read_licence", "_look_for"} <= {e[1] for e in events}, 20), events
    built = events.index(("built", "anki"))
    assert [e for e in events[:built] if e[0] == "job"] == [], events[:built]
    assert wait_until(lambda: page.built, 20)
    page.close()


def test_opened_at_its_top_the_pages_reads_go_after_its_first_slice(qapp, monkeypatch):
    # (no link: the page is built in slices from the top; its first slice paints before the reads go)
    events = []
    _jobs(monkeypatch, events)
    real_slice = sp.SettingsPage._slice

    def slice_(page):
        real_slice(page)
        events.append(("slice", len(page.slice_ms)))
    monkeypatch.setattr(sp.SettingsPage, "_slice", slice_)
    page, _calls = _page()
    assert [e for e in events if e[0] == "job"] == []
    assert wait_until(lambda: {"read_hato", "read_licence"} <= {e[1] for e in events}, 20), events
    first_job = next(i for i, e in enumerate(events) if e[0] == "job")
    assert ("slice", 1) in events[:first_job], events[:first_job + 1]
    assert wait_until(lambda: page.built, 20)
    page.close()


def test_a_read_asked_after_the_first_build_turn_goes_at_once(qapp):
    page, _calls = _page()
    assert wait_until(lambda: page.built, 20)
    ran = []
    page.after_first_build(lambda: ran.append(True))
    assert ran == [True]
    page.close()


def test_a_held_read_that_fails_never_keeps_the_others_from_going(qapp):
    page, _calls = _page()
    ran = []
    page.after_first_build(lambda: 1 / 0)
    page.after_first_build(lambda: ran.append(True))
    assert wait_until(lambda: ran == [True], 20)
    assert wait_until(lambda: page.built, 20)
    page.close()


def test_the_icons_the_page_draws_first_are_drawn_by_the_warm_up_and_none_again_by_the_page(qapp, monkeypatch):
    # warmed at the window's idle after its start (`ShellWindow._warm_settings`): the page's frame, the slab's head and
    # *More options* then draw no icon of their own at the click
    monkeypatch.setattr(sp, "_PIXMAPS", {})
    steps = sp.warm_icons()
    assert len(steps) >= 2 * len(catalog.SECTIONS) + 1
    for step in steps:
        step()
    assert len(sp._PIXMAPS) >= 2 * len(catalog.SECTIONS)
    drawn = []
    real = sp.QSvgRenderer
    monkeypatch.setattr(sp, "QSvgRenderer", lambda *args: drawn.append(args) or real(*args))
    page, _calls = _page()
    page.reveal("anki")
    assert wait_until(lambda: page._section_built("anki"), 20)
    QApplication.processEvents()
    assert drawn == [], f"{len(drawn)} icons drawn at the click the warm-up should have drawn"
    assert wait_until(lambda: page.built, 20)
    page.close()


def test_the_window_warms_settings_icons_a_few_a_turn_and_stops_once_the_page_is_made(qapp, monkeypatch):
    monkeypatch.setattr(sp, "_PIXMAPS", {})
    win = SimpleNamespace(settings_page=None)
    turns = []

    def again(steps):
        turns.append(len(steps))
        shell.ShellWindow._warm_icons(win, steps)
    win._warm_icons = again
    shell.ShellWindow._warm_icons(win, None)
    assert wait_until(lambda: len(sp._PIXMAPS) >= 2 * len(catalog.SECTIONS), 20)
    assert turns, "spread over the window's turns, never one stretch"
    monkeypatch.setattr(sp, "_PIXMAPS", {})
    win.settings_page = object()                                # made meanwhile: it draws what it needs itself
    shell.ShellWindow._warm_icons(win, None)
    assert sp._PIXMAPS == {}
    asked = []
    monkeypatch.setattr(shell.bridge, "run_in_worker", lambda *a, **k: asked.append(a))
    shell.ShellWindow._warm_settings(win)
    assert asked == [], "no warm-up once the page is made"


def test_settings_modules_imported_on_a_worker_make_no_qt_enum_there():
    # PyQt6 makes a class's enums at their first look-up; two threads at once can each make their own (the GUI guide
    # § 4): what the warm-up imports on a worker must look none up at import (a fresh process: nothing imported yet)
    import subprocess
    import sys
    code = (
        "import enum, sys, threading\n"
        "from app.qt import bridge, shell\n"
        "bridge.warm_worker_types()\n"
        "made = []\n"
        "real = enum.EnumType._create_\n"
        "def create(cls, class_name, *a, **k):\n"
        "    made.append((class_name, threading.current_thread() is threading.main_thread()))\n"
        "    return real(cls, class_name, *a, **k)\n"
        "enum.EnumType._create_ = create\n"
        "t = threading.Thread(target=shell._import_settings)\n"
        "t.start(); t.join()\n"
        "assert 'app.qt.settings_page' in sys.modules and 'app.qt.settings_connect' in sys.modules\n"
        "print('OFF', [name for name, main in made if not main])\n")
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=root)
    out = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert "OFF []" in out.stdout, out.stdout


def _per_slice(monkeypatch):
    """Each slice's record: the sections of the rows it built, its settles, its `_show_section` calls (on the class:
    a page made after it, or one whose slices go on, is recorded from its next slice)."""
    log, cur = [], {}
    cls = sp.SettingsPage
    real_slice, real_build = cls._slice, cls._build_guarded
    real_settle, real_show = cls._settle, cls._show_section

    real_off = cls._off_aim

    def slice_(self):
        cur.clear()
        cur.update(rows=[], settles=0, aims=0, off=False, shows=[])
        real_slice(self)
        log.append(dict(cur, rows=list(cur["rows"]), shows=list(cur["shows"]), last=not self._queue))

    def build(self, index, row, settings):
        cur.setdefault("rows", []).append(row.section)
        return real_build(self, index, row, settings)

    def settle(self):
        # only the slice's own layout: its `_keeping` or its `_aim` (a read's answer filling a row mid-slice keeps
        # its own row in place with a settle of its own)
        frame, names = sys._getframe(1), []
        while frame is not None and len(names) < 3:
            names.append(frame.f_code.co_name)
            frame = frame.f_back
        if names == ["_keeping", "__exit__", "_slice"]:
            cur["settles"] = cur.get("settles", 0) + 1
        elif names[:2] == ["_aim", "_slice"]:
            cur["aims"] = cur.get("aims", 0) + 1
        return real_settle(self)

    def off_aim(self):
        off = real_off(self)
        cur["off"] = cur.get("off", False) or off
        return off

    def show(self, section_id, *args, **kw):
        cur.setdefault("shows", []).append(section_id)
        return real_show(self, section_id, *args, **kw)
    monkeypatch.setattr(cls, "_slice", slice_)
    monkeypatch.setattr(cls, "_build_guarded", build)
    monkeypatch.setattr(cls, "_settle", settle)
    monkeypatch.setattr(cls, "_off_aim", off_aim)
    monkeypatch.setattr(cls, "_show_section", show)
    return log


def test_a_slice_that_builds_only_rows_below_the_reveal_lays_nothing_out_itself(qapp, monkeypatch):
    # opened at Anki & mining: the slabs above it (Your setup, Known words) are laid out at once to keep its row in
    # place; a slab built below it can't move it, so the loop lays the page out in its own turn
    page, _calls = _page()
    page.reveal("anki")
    assert wait_until(lambda: page._section_built("anki"), 20)
    revealed = page._revealed
    log = _per_slice(monkeypatch)
    assert wait_until(lambda: page.built, 20)
    order = [s.id for s in catalog.SECTIONS]
    anki = order.index("anki")
    below = [entry for entry in log if entry["rows"] and min(order.index(s) for s in entry["rows"]) > anki
             and not entry["last"]]                             # (the build's last slice aims once, laid out first)
    above = [entry for entry in log if any(order.index(s) < anki for s in entry["rows"])]
    assert len(below) >= 20 and above, (len(below), len(above))
    assert sum(entry["settles"] for entry in below) == 0, [entry["settles"] for entry in below]
    assert all(entry["aims"] == 0 for entry in below if not entry["off"]), [(e["aims"], e["off"]) for e in below]
    assert all(entry["settles"] + entry["aims"] >= 1 for entry in above)    # (laid out at once: the reveal kept)
    QApplication.processEvents()
    assert _at_third(page, revealed)                            # kept in place all the same
    page.close()


def test_each_slice_shows_each_section_it_built_rows_in_once(qapp, monkeypatch):
    # a section's rows asked their rules once a slice, not once for every row the slice built (Anki & mining's 35:
    # 35 times each in one go)
    log = _per_slice(monkeypatch)                               # (before the page: its first slice recorded too)
    monkeypatch.setattr(sp, "BUILD_MS", 10 ** 6)                # (in as few slices as the warm allows)
    page, _calls = _page()
    assert wait_until(lambda: page.built, 20)
    built = [entry for entry in log if entry["rows"]]
    assert built and max(len(entry["rows"]) for entry in built) > len(catalog.SECTIONS)
    for entry in built:
        assert sorted(entry["shows"]) == sorted(set(entry["rows"])), (entry["rows"], entry["shows"])
    page.close()


def test_the_level_read_hands_its_own_settings_to_the_numbers(monkeypatch, tmp_path):
    # SETTINGS-OPEN 2: one level read read settings.json four times (the known words' switches, Ignore names, one-kanji
    # words, set phrases): the page's settings go down with it instead
    from app import token_index
    path = tmp_path / "token_store_ja.db"
    path.write_bytes(b"")
    handed = []

    class Store:
        def close(self):
            pass

        def file_count(self):
            return 1
    monkeypatch.setattr(token_index, "store_path_for", lambda language: str(path))
    monkeypatch.setattr(token_index, "open_store", lambda language: Store())
    monkeypatch.setattr(token_index, "preview_frequencies", lambda *a, **k: handed.append((a, k)))
    settings = {"logic": {"selection": {}}, "zh_script": "asis"}
    assert settings_live.read_previews(settings, "ja") is None
    (args, kw), = handed
    assert (list(args) + list(kw.values()))[-1] is settings
