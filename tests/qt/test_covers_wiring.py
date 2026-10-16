"""Covers wired into the window (W3.2 landing 3): Q6's pictures in New arrivals' tray and inset and in Goal's sheet, Q7's
online covers asked by the window, *Change cover…* in every ⋯, and Settings → Connections' *Download covers*.

What a wrong answer would cost a learner:
  * a show's name sent to AniList while *Download covers* is off (01 §1.3 C1: off, nothing leaves the machine), or the
    whole library swept instead of the titles the window shows;
  * a tray row or a Goal tile stuck on the generated cover when its poster is right beside the files — or every row
    repainted whenever one picture lands;
  * a cover chosen online (a candidate, a pasted link) that Undo can't take back, or one offered while the switch is off;
  * *Remove downloaded covers* missing, or reaching anything but the downloaded covers.

The network is blocked (test_covers_online's guard: only 127.0.0.1); a fake AniList on 127.0.0.1 answers. The window
tests run on the seed (tests/fixtures/window_seed.py) and on real migrated stores (Japanese and Chinese titles from
tests/Test Resources).
"""
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication

from app import settings_manager
from app.qt import covers as qcovers
from app.qt import shell, strings
from app.services import covers_online as O
from app.services import library_reader
from app.services import moves as moves_module
from tests.qt.conftest import wait_until
from tests.qt.pixels import rgb_array
from tests.qt.test_covers_view import ROSE, _covers_state, _give_poster, near, settle  # noqa: F401 (autouse state)
from tests.test_covers_online import AniList, blocked  # noqa: F401 (autouse: the network blocked)
from tests.test_library_store_support import migrated


@pytest.fixture
def anilist():
    fake = AniList()
    yield fake
    fake.close()


@pytest.fixture(autouse=True)
def _no_fetcher():
    """No window's fetcher is left behind for the next test."""
    qcovers.use_fetcher(None)
    qcovers.asked_online[0] = 0
    yield
    qcovers.use_fetcher(None)


# --- a real store in the window, the fetcher pointed at the fake AniList -------------------------------------------- #
@pytest.fixture
def real(qapp):
    made = []

    def make(language, anilist, on):
        store = migrated(language)
        settings_manager.save_keys({"target_language": language})      # the window's language is its library's (P0)
        opener = moves_module.store_opener(language)
        reader = library_reader.LibraryReader(opener, language, poll=0.02)
        writer = moves_module.Writer(opener, language, journal_file=moves_module.journal_path(language),
                                     words=strings.MOVE_WORDS, retry=0.05)
        services = shell.Services(library=reader, writer=writer)
        switch = {"covers_download": on}
        services.cover_fetcher_factory = lambda lang, w, settings: O.Fetcher(
            lang, w, settings=lambda: switch, api=anilist.base, ytimg=anilist.base, image_hosts=("127.0.0.1",))
        win = shell.open_window(qapp, services)
        win.resize(1280, 900)
        win.show()
        page = win.page_widgets["current"]
        assert wait_until(lambda: page.view_model is not None and page.view_model.state == "full", 15)
        settle(30)
        made.append((win, services, store))
        return store, win, writer, switch
    yield make
    for win, services, store in made:
        win.close()
        services.shutdown(2.0)
        store.close()


def shown_works(win):
    """Every work the window's view holds (Current, Finished, Needs you, Goal, New arrivals)."""
    view = win.page_widgets["current"].view_model
    out = {r.work_id for r in view.rows}
    out |= {r.work_id for m in view.finished or () for r in m.rows}
    out |= {a.work_id for a in view.arrivals or ()}
    out |= {w.work_id for w in (view.goal.works if view.goal is not None else ())}
    out |= {n.work_id for n in view.needs or ()}
    return out - {None}


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_with_download_covers_off_the_window_paints_its_titles_and_nothing_leaves_the_machine(real, anilist,
                                                                                                language):
    store, win, _writer, _switch = real(language, anilist, on=False)
    for title in {w["title"] for w in store.read_feed()["works"] if w.get("title")}:
        anilist.add(len(anilist.media) + 1, title, title, search=title)          # every title would be found
    win.page_widgets["current"].list.viewport().update()
    win._settings_written(["covers_download"])                        # a write that leaves it off
    settle(60)
    time.sleep(0.3)
    settle(20)
    f = win.cover_fetcher()
    assert f is not None and qcovers.fetcher() is f
    assert anilist.posts == [] and anilist.gets == []
    assert qcovers.asked_online[0] == 0 and not f._queue and not f._done and qcovers._online["asked"] == set()
    entries = qcovers.change_cover_entries(win.page_widgets["current"].view_model.rows[0])
    assert [e[0] for e in entries] == ["cover-choose", "cover-generated"], "no online entry while it's off"


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_with_it_on_the_titles_shown_are_asked_once_each_and_a_found_cover_lands_as_a_background_cover(real, anilist,
                                                                                                       language):
    store, win, writer, _switch = real(language, anilist, on=False)
    work = store.item(store.ids("now")[0])["work_id"]
    title = store._work_row(work)["title"]
    anilist.add(16498, "Shingeki no Kyojin", title, search=O.clean_title(title)[0])
    _switch["covers_download"] = True                                  # turned on in Settings: what shows is asked
    win._settings_written(["covers_download"])
    assert wait_until(lambda: (settle() or True) and store._work_row(work)["cover_source"] == "anilist", 10)
    row = store._work_row(work)
    assert row["cover_ref"] == "16498" and row["cover_path"].startswith("cache:") and not row["cover_locked"]
    assert not writer.can_undo(), "a downloaded cover is never on the user's Undo"
    asked = qcovers._online["asked"]
    assert asked and asked <= shown_works(win), "only what the window shows, never a sweep of the library"
    searches = [b["variables"]["search"] for b, _h in anilist.posts if "search" in b["variables"]]
    assert len(searches) == len(set(searches)), "each title asked once"
    for _b, headers in anilist.posts:
        assert headers.get("User-Agent", "").startswith("Surasura/") and "Referer" not in headers
    lst = win.page_widgets["current"].list
    assert wait_until(lambda: (settle() or True) and any(
        getattr(p, "work_id", None) == work and getattr(getattr(p, "cover", None), "source", None) == "anilist"
        for _k, p, _l in lst.model().entries), 10)                    # the row reads the new record and repaints


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_paste_a_link_and_a_picked_candidate_are_the_users_locked_with_undo(real, anilist, language):
    store, win, writer, _switch = real(language, anilist, on=True)
    view = win.page_widgets["current"].view_model
    row = next(r for r in view.rows if r.work_id is not None)
    before = store._work_row(row.work_id)["cover_source"]
    assert row.cover is None or qcovers._askable(row.cover)
    assert wait_until(lambda: (settle() or True) and row.work_id in qcovers._online["asked"], 5),         "a title painted with the switch on is asked by its first paint"
    names = [e[0] for e in qcovers.change_cover_entries(row)]
    assert names == ["cover-choose", "cover-generated", "cover-online", "cover-paste"]
    said = []
    win.say = said.append
    QApplication.clipboard().setText("https://example.com/表紙.jpg")
    assert qcovers.paste_link(row) is False and said[-1] == strings.COVER_PASTE_NOT_A_LINK
    settle(20)
    assert not [b for b, _h in anilist.posts if "example" in str(b)] and not [g for g in anilist.gets if "表紙" in g[0]]
    anilist.add(154587, "Sousou no Frieren", "葬送のフリーレン")
    QApplication.clipboard().setText("  https://anilist.co/anime/154587/Sousou-no-Frieren/  ")
    assert qcovers.paste_link(row)
    assert wait_until(lambda: (settle() or True) and store._work_row(row.work_id)["cover_source"] == "anilist", 10)
    kept = store._work_row(row.work_id)
    assert kept["cover_ref"] == "154587" and kept["cover_path"].startswith("user:") and kept["cover_locked"]
    win.moves.undo_last()                                             # Ctrl+Z (the toast's Undo is the same ticket)
    assert wait_until(lambda: (settle() or True) and store._work_row(row.work_id)["cover_source"] == before, 10)
    # *Find it online…*: the top five, then one picked
    for n in range(7):
        anilist.add(400000 + n, f"Candidate {n}", f"{row.cover_title}{n}", year=2010 + n, search=row.cover_title)
    assert qcovers.find_online(row, at=QPoint(200, 200))
    assert wait_until(lambda: (settle() or True) and qcovers._online["menu"] is not None
                      and qcovers._online["menu"].isVisible(), 10)
    acts = qcovers._online["menu"].actions()
    assert len(acts) == 5 and all(a.toolTip() for a in acts)
    acts[2].trigger()
    assert wait_until(lambda: (settle() or True) and store._work_row(row.work_id)["cover_ref"] == "400002", 10)
    assert store._work_row(row.work_id)["cover_locked"]
    qcovers._online["menu"].close()


def test_the_fetcher_is_made_with_the_library_again_for_another_writer_and_stopped_at_close(real, anilist):
    store, win, writer, _switch = real("ja", anilist, on=False)
    f = win.cover_fetcher()
    assert f is win.cover_fetcher() and f.writer is writer and f.language == "ja"
    other = SimpleNamespace(can_write=lambda: True)
    win.services.writer = other                                       # another library's writer (a switch)
    g = win.cover_fetcher()
    assert g is not f and g.writer is other and f._stop and qcovers.fetcher() is g
    win.services.writer = writer
    h = win.cover_fetcher()
    win.close()
    assert h._stop and qcovers.fetcher() is None


# --- the tray, the inset and Goal's sheet paint Q6's pictures (the seed) ------------------------------------------- #
def open_seed(qapp, seed, writer):
    """The seed's window in the seed's own language (its settings say so: the covers' data folder is that language's)."""
    from tests.qt.test_settings_page import Recorder
    reader = library_reader.LibraryReader(seed.opener, language=seed.language, numbers=seed.numbers,
                                          mining=seed.mining, poll=0.02)
    services = shell.Services(settings=Recorder({"target_language": seed.language}), library=reader, writer=writer)
    win = shell.open_window(qapp, services)
    win.resize(1280, 900)
    win.move(40, 30)
    win.show()
    page = win.page_widgets["current"]
    assert wait_until(lambda: page.view_model is not None and not page.view_model.loading
                      and win.arrivals_tray.groups, 10)
    settle(30)
    return win, services


def _centre(widget, rect):
    arr = rgb_array(widget.grab(rect))
    return tuple(int(v) for v in arr[arr.shape[0] // 2, arr.shape[1] // 2])


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_tray_row_paints_its_arrivals_poster_and_a_landing_repaints_only_its_rows(qapp, language):
    from tests.qt.test_arrivals import ArrivalsWriter, open_tray, tray_rows
    from tests.fixtures import window_seed
    seed = window_seed.build(language=language)
    work = next(r["work_id"] for r in seed.items if r["tier"] == "arrivals")
    seed.library.commit(works=[_give_poster(seed, work)])
    win, services = open_seed(qapp, seed, ArrivalsWriter(seed.library))
    try:
        tray = open_tray(win)
        row = next(r for r in tray_rows(win) if r.arrival.work_id == work)
        assert row.arrival.cover is not None and row.arrival.cover.source == "file"
        m = row._m()
        cover = (m["h"], (row.height() - m["ch"]) // 2, m["cw"], m["ch"])
        from PyQt6.QtCore import QRect
        assert wait_until(lambda: (settle() or True) and near(_centre(row, QRect(*cover)), ROSE), 5)
        assert any(r is not None and r.work_id == work for r in win.arrivals_inset.refs)
        hits = []
        for r in tray_rows(win):
            r.update = (lambda key: lambda: hits.append(key))(r.arrival.key)
        inset_hits = []
        win.arrivals_inset.update = lambda: inset_hits.append(1)
        tray._cover_ready(work)
        win.arrivals_inset._cover_ready(work)
        assert hits == [row.arrival.key] and inset_hits == [1]
        tray._cover_ready(-1)
        win.arrivals_inset._cover_ready(-1)
        assert hits == [row.arrival.key] and inset_hits == [1]       # another title's picture: nothing repainted
    finally:
        win.close()
        services.shutdown(0.5)


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_goal_tile_paints_its_titles_poster_and_a_landing_repaints_only_its_tile(qapp, language):
    from tests.qt.test_goal_sheet import Writer, open_sheet
    from tests.fixtures import window_seed
    seed = window_seed.build(language=language)
    work = next(r["work_id"] for r in seed.items if r["tier"] == "goal")
    seed.library.commit(works=[_give_poster(seed, work)])
    win, services = open_seed(qapp, seed, Writer(seed.library))
    try:
        sheet = open_sheet(win)
        settle(60)
        tile = next(t for t in sheet.order if t.work.work_id == work)
        assert tile.work.cover is not None and tile.work.cover.source == "file"
        _w, _h, pad, cw, ch = tile.size_for()
        from PyQt6.QtCore import QRect
        assert wait_until(lambda: (settle() or True) and near(_centre(tile, QRect(pad, pad, cw, ch)), ROSE), 5)
        hits = []
        for t in sheet.order:
            t.update = (lambda key: lambda: hits.append(key))(t.work.key)
        sheet._cover_ready(work)
        assert hits == [tile.work.key]
    finally:
        win.close()
        services.shutdown(0.5)


# --- Change cover… in every ⋯ ------------------------------------------------------------------------------------- #
def _cover_sub(menu):
    act = next((a for a in menu.actions() if a.menu() is not None and a.text() == strings.ITEM_MENU["cover"][0]), None)
    return act.menu() if act is not None else None


def test_change_cover_is_in_the_trays_the_sheets_finisheds_and_currents_menus_with_the_online_ones_only_when_on(qapp):
    from tests.qt.test_arrivals import ArrivalsWriter, open_tray, open_window, tray_rows
    from tests.qt.test_goal_sheet import open_sheet
    from tests.fixtures import window_seed
    seed = window_seed.build(language="ja")
    win, services = open_window(qapp, seed, ArrivalsWriter(seed.library))
    switch = {"covers_download": False}
    try:
        f = win.cover_fetcher()
        f.settings = lambda: switch
        tray = open_tray(win)
        menus = {}
        menus["tray"] = tray.menu(tray_rows(win)[0])
        tray.close()
        sheet = open_sheet(win)
        menus["sheet"] = sheet.menu(sheet.order[0])
        sheet.close()
        view = win.page_widgets["current"].view_model
        menus["finished"] = win.finished.menu(view.finished[0].rows[0], QPoint(10, 10))
        for name, m in menus.items():
            sub = _cover_sub(m)
            assert sub is not None, name
            assert [a.text() for a in sub.actions()] == [strings.COVER_MENU["choose"][0],
                                                         strings.COVER_MENU["generated"][0]], name
            assert all(a.toolTip() for a in sub.actions()) and sub.menuAction().toolTip()
            m.close()
        current = win.items.entries(next(r for r in view.rows if r.work_id is not None))
        assert [c.label for c in next(e for e in current if e.name == "cover").children] == [
            strings.COVER_MENU["choose"][0], strings.COVER_MENU["generated"][0]]
        switch["covers_download"] = True
        m = tray.menu(tray_rows(win)[0])
        assert [a.text() for a in _cover_sub(m).actions()][2:] == [strings.COVER_ONLINE[0], strings.COVER_PASTE[0]]
        m.close()
        current = win.items.entries(next(r for r in view.rows if r.work_id is not None))
        assert [c.label for c in next(e for e in current if e.name == "cover").children][2:] == [
            strings.COVER_ONLINE[0], strings.COVER_PASTE[0]]
    finally:
        win.close()
        services.shutdown(0.5)


def test_on_a_store_that_cant_be_saved_change_cover_is_greyed_with_the_reason(qapp):
    from tests.qt.test_arrivals import ArrivalsWriter, open_tray, open_window, tray_rows
    from tests.fixtures import window_seed
    seed = window_seed.build(language="zh")
    writer = ArrivalsWriter(seed.library)
    win, services = open_window(qapp, seed, writer)
    try:
        tray = open_tray(win)
        writer.can_write = lambda: False
        writer.reason = lambda: "damaged"
        sub = _cover_sub(tray.menu(tray_rows(win)[0]))
        assert sub is not None and not sub.menuAction().isEnabled()
        assert all(not a.isEnabled() and a.toolTip() for a in sub.actions())
    finally:
        win.close()
        services.shutdown(0.5)


# --- Settings → Connections: *Remove downloaded covers* ---------------------------------------------------------- #
def test_remove_downloaded_covers_asks_the_windows_fetcher_on_a_worker_and_says_so(qapp, monkeypatch):
    import threading
    from tests.qt.test_settings_live import Fakes, make
    fakes = Fakes(monkeypatch)
    page, store, shell_ = make(fakes)
    removed = []

    class Fetcher:
        def remove_downloaded(self):
            removed.append(threading.current_thread() is threading.main_thread())
            return 7
    shell_.cover_fetcher = lambda: Fetcher()
    qcovers._online["asked"] = {1, 2}
    button = page.live.parts["remove_downloaded_covers"]["remove"]
    assert button.toolTip() and page.row("remove_downloaded_covers").row.sub
    button.click()
    assert wait_until(lambda: shell_.bar_line.lines[-1:] == [strings.COVERS_REMOVED], 5)
    assert removed == [False], "on a worker, never the window's thread"
    assert qcovers._online["asked"] == set(), "every title may be asked again"
    assert store.calls == [], "the action writes no setting"
    shell_.cover_fetcher = lambda: None                               # no library open
    button.click()
    assert wait_until(lambda: shell_.bar_line.lines[-1:] == [strings.COVERS_REMOVE_NONE], 5)


def test_the_download_covers_toggle_saves_only_its_key_through_the_settings_service(qapp, monkeypatch):
    from tests.qt.test_settings_live import Fakes, make
    from tests.qt.test_settings_page import change
    fakes = Fakes(monkeypatch)
    page, store, _shell = make(fakes)
    toggle = page.rows["covers_download"].controls[0]
    assert toggle.value() is False and toggle.toolTip()
    change(toggle, True)
    assert store.calls == [({"covers_download": True}, None)]


# --- W3.2 L3 fix round ------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_turned_on_from_settings_currents_rows_in_view_are_asked_and_titles_dropped_while_off_are_asked_again(
        real, anilist, language):
    """S1: the switch lives on the Settings page, so 'the shown page' is Settings — Current's rows in view are asked
    all the same. N1: a title asked while the fetcher dropped it (the switch went off) is asked again when it's on."""
    store, win, _writer, switch = real(language, anilist, on=False)
    lst = win.page_widgets["current"].list
    view = win.page_widgets["current"].view_model
    elsewhere = {a.work_id for a in view.arrivals or ()}
    elsewhere |= {w.work_id for w in (view.goal.works if view.goal is not None else ())}
    in_view = []
    for _kind, payload, _lines in lst.model().entries[:6]:
        work = getattr(payload, "work_id", None)
        if work is not None and work not in elsewhere and work not in in_view:
            in_view.append(work)
    wants = {w.id: w for w in O.wants_for(store, in_view)}
    picked = [w for w in in_view if w in wants and O.fetchable(wants[w]) and not wants[w].anilist_id][:2]
    assert len(picked) == 2, "two of Current's rows in view, asked by name"
    for n, work in enumerate(picked):
        name = O.clean_title(wants[work].title)[0]
        anilist.add(170000 + n, f"Title {n}", name, search=name)
    win.show_tab("settings")
    settle(20)
    qcovers._online["asked"].add(picked[1])         # asked once while the fetcher dropped it (the switch went off)
    switch["covers_download"] = True
    win._settings_written(["covers_download"])
    assert wait_until(lambda: (settle() or True) and all(
        store._work_row(w)["cover_source"] == "anilist" for w in picked), 10)


def test_a_downloaded_cover_whose_file_went_is_asked_online_again_when_its_decode_finds_it_gone(qapp):
    """S3 / S4: the decoder finds an online record's cached file gone (another library's Remove, an Undo to an old
    record): that title is asked again; a missing file of the art beside the files is never asked online."""
    class Fetcher:
        def on(self):
            return True

        def want(self, wants):
            return 0
    qcovers.use_fetcher(Fetcher(), lambda ids: [])
    gone = (7, "anilist", "16498", "cache:anilist-7.jpg", "row", 40, 60, 1.0)
    disk = (8, "file", "アニメ/進撃の巨人/poster.jpg", None, "row", 40, 60, 1.0)
    for key in (gone, disk):
        qcovers._running[key] = []
        qcovers._landed(key, None)
    assert 7 in qcovers._online["asked"] and 8 not in qcovers._online["asked"]
