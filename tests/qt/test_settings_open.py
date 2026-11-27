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
