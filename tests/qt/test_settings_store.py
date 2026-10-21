"""Settings' store rows and *Set up again* (W3.3 P6; `app/qt/settings_store.py`), and the Connect watermarks a write that
turns Connect on asks for (Michi's W-A7, the intent keeper's B2: `resume_connect`).

What a wrong answer would cost: *Soon starts after* or *Mine automatically* written into settings.json (they are the
library's own values: the store's meta, through the window's writer, never the file); a value shown that the library
doesn't hold, or a field that looks writable with no library behind it; a refused write left showing as if saved; a
repaint on every view (S19); Settings' automation row (or the wizard's *Make cards for me*) turning Connect on without
moving its watermarks — then everything placed while it was off would be mined at once (G1.1-2).

The page is the real `SettingsPage` over the settings recorder of `test_settings_page`; the library is a stand-in
reader (its options and a view) and a stand-in writer recording `set_options` — the writer's own store path is
`tests/test_services_moves.py`'s.
"""
import threading
from collections import namedtuple
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from app.qt import settings_page as sp
from app.qt import settings_store as store_rows
from app.qt import settings_strings as S
from tests.qt.conftest import wait_until
from tests.qt.test_settings_page import ALL_ON, EVERYTHING, Recorder, change

Row = namedtuple("Row", "tier episodes")
View = namedtuple("View", "rows")


def _view(now=3, soon=2):
    return View(tuple([Row("now", ("e1", "e2"))] * now + [Row("soon", ("e3",))] * soon))


class Reader:
    def __init__(self, options=None, view=None):
        self._options = dict(options or {})
        self._view = view if view is not None else _view()

    def options(self):
        return dict(self._options)

    def view(self):
        return self._view


class Writer:
    def __init__(self, refuse=False, reason=None):
        self.calls = []
        self.refuse = refuse
        self._reason = reason

    def set_options(self, **kw):
        self.calls.append(kw)
        return None if self.refuse else len(self.calls)

    def reason(self):
        return self._reason


class Heard(QObject):
    library_changed = pyqtSignal(object)


class Bar:
    def __init__(self):
        self.lines = []

    def set_full(self, text):
        self.lines.append(text)


def make(options=None, reader=True, writer=None, data=None, view=None):
    store = Recorder(dict({"target_language": "ja"}, **(data if data is not None else ALL_ON)))
    services = SimpleNamespace(settings=store, library=Reader(options, view) if reader else None,
                               writer=writer if writer is not None else (Writer() if reader else None))
    shell = SimpleNamespace(services=services, bar_line=Bar(), library_bridge=Heard())
    page = sp.SettingsPage(shell, "ja", found=EVERYTHING)
    rows = store_rows.attach(page)
    page.resize(1100, 700)
    page.show()
    assert wait_until(lambda: page.built, 20)
    QApplication.processEvents()
    return page, rows, shell, store


def _close(page):
    page.close()
    page.deleteLater()
    QApplication.processEvents()


def test_the_store_lines_show_the_librarys_values_and_a_soon_line_not_set_shows_nows_files(qapp):
    page, rows, _shell, store = make({"soon_line": None, "mine_line": 7, "arrivals_on": 1}, view=_view(now=3))
    try:
        assert rows.fields["mine_line"].value() == 7
        assert rows.fields["soon_line"].value() == 6                       # 3 NOW rows of 2 files: nothing written
        assert page.custom_row("soon_line").layout().indexOf(rows.fields["soon_line"]) >= 0
        assert store.calls == []
    finally:
        _close(page)


def test_a_mine_line_the_store_never_set_shows_its_default(qapp):
    page, rows, _shell, _store = make({"soon_line": 25, "mine_line": None, "arrivals_on": 1})
    try:
        assert rows.fields["mine_line"].value() == store_rows.MINE_LINE_DEFAULT == 20
        assert rows.fields["soon_line"].value() == 25
    finally:
        _close(page)


def test_a_typed_line_goes_to_the_writer_never_to_settings_json(qapp):
    writer = Writer()
    page, rows, _shell, store = make({"soon_line": 25, "mine_line": 20, "arrivals_on": 1}, writer=writer)
    try:
        change(rows.fields["soon_line"], 12)
        change(rows.fields["mine_line"], 4)
        assert writer.calls == [{"soon_line": 12}, {"mine_line": 4}]
        assert store.calls == []                                           # the library's values, not the file's
    finally:
        _close(page)


def test_a_refused_line_goes_back_to_the_librarys_value_and_the_bar_says_why(qapp):
    writer = Writer(refuse=True, reason="damaged")
    page, rows, shell, _store = make({"soon_line": 25, "mine_line": 20, "arrivals_on": 1}, writer=writer)
    try:
        change(rows.fields["soon_line"], 3)
        assert writer.calls == [{"soon_line": 3}]
        assert rows.fields["soon_line"].value() == 25
        assert shell.bar_line.lines == [S.STORE_NOT_SAVED.format(reason="damaged")]
    finally:
        _close(page)


@pytest.mark.parametrize("case", ["no library", "not read yet"])
def test_with_no_library_to_write_to_the_fields_are_greyed_and_say_why(qapp, case):
    page, rows, _shell, _store = make({} if case == "not read yet" else None, reader=case != "no library")
    try:
        for field in rows.fields.values():
            assert not field.isEnabled() and field.toolTip() == S.STORE_NO_LIBRARY_TIP
            assert field.edit.text() == ""                      # never a number the library doesn't hold
        if case == "not read yet":                              # its first read lands: the values, writable
            page.services.library._options.update(soon_line=25, mine_line=20, arrivals_on=1)
            rows.follow()
            assert rows.fields["soon_line"].isEnabled() and rows.fields["soon_line"].edit.text() == "25"
            assert rows.fields["mine_line"].edit.text() == "20"
    finally:
        _close(page)


def test_a_new_view_repaints_only_a_line_that_moved(qapp):
    page, rows, shell, _store = make({"soon_line": 25, "mine_line": 20, "arrivals_on": 1})
    try:
        mine = rows.fields["mine_line"]
        sets = []
        real = mine.set_value
        mine.set_value = lambda v: (sets.append(v), real(v))
        shell.library_bridge.library_changed.emit(_view())                 # nothing moved: nothing repainted (S19)
        assert sets == []
        page.services.library._options["mine_line"] = 9                    # another window's write, read by the reader
        shell.library_bridge.library_changed.emit(_view())
        assert sets == [9] and mine.value() == 9
    finally:
        _close(page)


def test_set_up_again_opens_the_wizard_over_the_window(qapp, monkeypatch):
    from app.qt import first_run
    asked = []
    monkeypatch.setattr(first_run, "open_again", lambda shell, **kw: asked.append((shell, kw)) or "wizard")
    page, rows, shell, _store = make({"soon_line": 25, "mine_line": 20, "arrivals_on": 1})
    try:
        assert page.row("set_up_again") is not None and page.row("set_up_again").isVisibleTo(page)
        rows.again.click()
        assert asked == [(shell, {})]
        assert rows.again.toolTip() and rows.again.accessibleName()
    finally:
        _close(page)


# --- resume_connect: a write that turns Connect on moves its watermarks ------------------------------------------------ #
@pytest.fixture
def turned(monkeypatch):
    from app.connect import resume
    calls = []
    done = threading.Event()

    def record(before, after):
        calls.append((before, after, threading.current_thread() is threading.main_thread()))
        done.set()
    monkeypatch.setattr(resume, "turned_on", record)
    return calls, done


def test_the_automation_row_turned_on_asks_for_connects_watermarks_on_a_worker(qapp, turned):
    calls, done = turned
    data = dict(ALL_ON, logic={"automation": False})
    page, _rows, _shell, store = make({"soon_line": 25, "mine_line": 20, "arrivals_on": 1}, data=data)
    try:
        view = page.rows["automation"]
        change(view.controls[0], True)
        assert store.calls[-1][0] == {"logic.automation": True}
        assert wait_until(done.is_set)
        before, after, on_main = calls[0]
        assert before["logic"]["automation"] is False and after["logic"]["automation"] is True
        assert before["connect_enabled"] is True and on_main is False
    finally:
        _close(page)


def test_a_write_of_no_connect_key_asks_for_no_watermark(qapp, turned):
    calls, done = turned
    assert store_rows.resume_connect({"connect_enabled": False}, {"split_length": 900}) is False
    assert store_rows.resume_connect(None, {"connect_enabled": True}) is True     # (no settings read: off before)
    assert wait_until(done.is_set)
    assert calls[0][0] == {} and calls[0][1] == {"connect_enabled": True}


# --- Trust my subtitles' timing turned on: Connect is started, so the episodes waiting on it mine now ----------------- #
@pytest.fixture
def kicked(monkeypatch):
    from app.connect import kick
    calls = []
    done = threading.Event()

    def record(settings):
        calls.append((settings, threading.current_thread() is threading.main_thread()))
        done.set()
    monkeypatch.setattr(kick, "kick", record)
    return calls, done


def test_trust_turned_on_in_the_page_starts_connect_on_a_worker(qapp, kicked):
    # Laptop try row 9: the episodes already waiting as *Not timed* are picked again only when Connect next starts —
    # turning the switch on must start it, or they sit until something else does.
    calls, done = kicked
    data = dict(ALL_ON, connect_trust_timing=False)
    page, _rows, _shell, store = make({"soon_line": 25, "mine_line": 20, "arrivals_on": 1}, data=data)
    try:
        change(page.rows["connect_trust_timing"].controls[0], True)
        assert store.calls[-1][0] == {"connect_trust_timing": True}
        assert wait_until(done.is_set)
        settings, on_main = calls[0]
        assert settings["connect_trust_timing"] is True and on_main is False
    finally:
        _close(page)


def test_trust_turned_off_or_another_key_starts_nothing(qapp, kicked):
    calls, _done = kicked
    assert store_rows.kick_on_trust({"connect_trust_timing": True}, {"connect_trust_timing": False}) is False
    assert store_rows.kick_on_trust({"connect_trust_timing": True}, {"connect_trust_timing": True}) is False
    assert store_rows.kick_on_trust({}, {"split_length": 900}) is False
    assert store_rows.kick_on_trust(None, {"connect_trust_timing": True}) is True


def test_trust_waits_for_its_settings_write_before_starting_connect(qapp, kicked):
    # Review LF-9 #4: the started Connect reads settings.json from disk; the page's write is queued (0.25 s, retried
    # behind another program's lock), so the start waits for it to land, or Connect would read the switch still off.
    calls, done = kicked
    order = []

    class Store:
        def flush(self, timeout=None):
            order.append("flush")
            return True

    from app.connect import kick
    kick.kick = lambda settings: (order.append("kick"), done.set())
    assert store_rows.kick_on_trust({}, {"connect_trust_timing": True}, store=Store()) is True
    assert wait_until(done.is_set)
    assert order == ["flush", "kick"]
