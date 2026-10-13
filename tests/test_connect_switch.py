"""The Connect preview's switch in Settings (P3.1 row 3.1.1; P1.5 05-surface U4's head): *Make cards automatically
(preview)* in a third column, `connect_enabled` saved alone and only when touched; on, Connect's watermark set (✅
G1.1-2: nothing placed before is mined), its controls and the dashboard's line appear; off, they go.

What a wrong answer would cost: a Settings window that writes `connect_enabled: false` (or any default) into a 2.5
user's file the moment it opens; a switch-on that mines the user's whole history (every episode placed before it), or
says "on" with one language's watermark missing; a switch that shows on while the file says off; a switch-off that
strands the shelved cards (nothing can show or put them back once the preview is off); a Settings window that imports
Connect with the preview off (2.5 byte for byte). The real dashboard on a hidden root, the test's own root; real
subtitles in the library."""
import json
import os
import sys
import time
import types
from unittest.mock import patch

import pytest
import tkinter as tk

from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.connect_tk_helpers import on_main, read_settings, settings_bytes


class Now:
    """A worker that runs at once."""

    def __init__(self, target=None, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


def test_a_dashboard_save_of_a_file_without_the_switch_never_gains_it():
    """The switch is never part of the dashboard's own save: a 2.5 file stays without it (carried only as written)."""
    from tests.test_settings_signatures import _dashboard_saved, _write
    _write({"target_language": "ja"})
    assert "connect_enabled" not in _dashboard_saved()
    _write({"target_language": "ja", "connect_enabled": True})
    assert _dashboard_saved()["connect_enabled"] is True


def _pump(root, until, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if until():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def dashboard(monkeypatch):
    from app.main import MasterDashboardApp
    made = []

    def make():
        try:
            root = tk.Tk()
        except tk.TclError:
            pytest.skip("Tk is not available in this environment")
        root.withdraw()
        monkeypatch.setattr(tk, "_default_root", root)
        made.append(root)
        with patch.object(MasterDashboardApp, "check_updates_thread"):
            return MasterDashboardApp(root)
    yield make
    for root in made:
        try:
            root.destroy()
        except Exception:
            pass


def _settings_open(dashboard, monkeypatch, **settings):
    """The dashboard with settings.json as given and Settings open; the Processing Log's lines collected."""
    app = dashboard()
    h.write_settings(target_language="ja", **settings)
    app.load_settings()
    app.toggle_settings_window()
    lines = []
    monkeypatch.setattr(app, "log_to_terminal", lines.append)
    if settings.get("connect_enabled"):
        assert _pump(app.root, lambda: app._connect_panel is not None)
    return app, lines


def _switch(app, on):
    """The switch touched, and everything it started finished (the switch usable again)."""
    app.var_connect_enabled.set(on)
    app._connect_switch_toggled()
    assert _pump(app.root, lambda: "disabled" not in app.chk_connect.state())
    app.root.update()


# --- switching on ---------------------------------------------------------------------------------------------------

def test_switching_on_writes_only_connect_enabled(dashboard, monkeypatch):
    app, _lines = _settings_open(dashboard, monkeypatch, theme="Dark Flow", placing_rules={"hato": "top"})
    before = read_settings()
    _switch(app, True)
    assert read_settings() == dict(before, connect_enabled=True), "its own key, every other as the file holds it"
    assert app._current_settings["connect_enabled"] is True


def test_switching_on_sets_the_watermark_so_an_item_placed_before_is_never_queued(dashboard, monkeypatch):
    from app.connect import inbox, library
    from app.connect.ledger import Ledger
    c.library()
    with c.store() as s:
        s.bookkeeping({"mine_line": 2}, copy_carries=True)
    with c.store() as s, Ledger() as ledger:
        inbox.consume(s, "ja", ledger)                              # Connect ran once (its reader set), then off
    with c.store() as s:
        library.place(s, s.ids("now")[-1], "now", source="user")   # placed into the top 2 while the switch was off
    app, lines = _settings_open(dashboard, monkeypatch)
    _switch(app, True)
    with c.store() as s, Ledger() as ledger:
        assert inbox.consume(s, "ja", ledger)["queued"] == [], "nothing placed before the switch-on is mined"
    assert "Connect is on: what you place in your top 20 from now on gets cards." in lines
    assert _pump(app.root, lambda: app._connect_panel is not None and app._connect_row is not None), \
        "then the controls and the line"


def test_the_watermarks_come_first_then_the_save_then_the_session_look(dashboard, monkeypatch):
    """IK2: the key saved only after every language's watermark; no session look (or its kick) before the save."""
    from app import settings_manager
    from app.connect import library
    order = []
    real_switch_on, real_save = library.switch_on, settings_manager.save_keys
    monkeypatch.setattr(library, "switch_on", lambda store, *a: (order.append("watermark"),
                                                                 real_switch_on(store, *a))[1])
    monkeypatch.setattr(settings_manager, "save_keys", lambda *a, **k: (order.append("save"), real_save(*a, **k))[1])
    c.library()
    app, _lines = _settings_open(dashboard, monkeypatch)
    monkeypatch.setattr(app, "_connect_session", lambda *a, **k: order.append("session"))
    _switch(app, True)
    assert order == ["watermark", "save", "session"]


def test_a_language_whose_watermark_fails_is_named_the_other_still_tried_and_nothing_saved(dashboard, monkeypatch):
    """H8 / IK2: Japanese's library refusing leaves Chinese tried, the switch off, the file untouched, the reason
    named in the Processing Log — never "Connect is on" with a watermark missing."""
    from app.connect import library
    opened = []

    def open_store(lang, role="connect"):
        opened.append(lang)
        if lang == "ja":
            raise OSError("the library file is locked")
        return None
    monkeypatch.setattr(library, "open_store", open_store)
    app, lines = _settings_open(dashboard, monkeypatch)
    sessions = []
    monkeypatch.setattr(app, "_connect_session", lambda *a, **k: sessions.append(1))
    before = settings_bytes()
    _switch(app, True)
    assert opened == ["ja", "zh"], "each language in its own try"
    assert settings_bytes() == before, "nothing saved"
    assert app.var_connect_enabled.get() is False and not app._current_settings.get("connect_enabled")
    assert app._connect_panel is None and app._connect_row is None and sessions == []
    assert any(line.startswith("Connect wasn't switched on: Japanese: the library file is locked") for line in lines)
    assert not any(line.startswith("Connect is on") for line in lines)


def test_a_switch_on_whose_save_fails_goes_back_off(dashboard, monkeypatch):
    """H9: settings.json not written → the switch back off, no controls, no line, no session look."""
    from app import settings_manager
    app, lines = _settings_open(dashboard, monkeypatch)
    sessions = []
    monkeypatch.setattr(app, "_connect_session", lambda *a, **k: sessions.append(1))
    monkeypatch.setattr(settings_manager, "save_settings", lambda *a, **k: False)
    _switch(app, True)
    assert app.var_connect_enabled.get() is False and not app._current_settings.get("connect_enabled")
    assert app._connect_panel is None and app._connect_row is None and sessions == []
    assert any("Connect wasn't switched on: the switch wasn't saved" in line for line in lines)


def test_switched_on_again_a_level_raise_while_off_mines_nothing(dashboard, monkeypatch):
    """IK1 (G1.1-2): the list Connect last looked at is forgotten at switch-on, so the next look records the list as it
    is — the words it gained while Connect was off are never mined."""
    from app.connect import level
    from app.connect.ledger import Ledger
    with Ledger() as ledger, ledger.transaction():
        ledger.record_list("ja", "generate-1", {("上層部", "ジョウソウブ")})     # looked at before the switch-off
    app, _lines = _settings_open(dashboard, monkeypatch)
    _switch(app, True)
    listed = {("上層部", "ジョウソウブ"), ("一生懸命", "イッショウケンメイ")}   # 一生懸命 listed while off
    out = level.check(None, "ja", listed, "generate-2", {})
    assert out["first"] is True and out["new"] == 0 and out["queued"] == [], "a first look: nothing mined"


# --- switching off --------------------------------------------------------------------------------------------------

def test_switching_off_drops_the_controls_and_the_line_and_writes_only_the_switch(dashboard, monkeypatch):
    app, lines = _settings_open(dashboard, monkeypatch, connect_enabled=True)
    app._connect_row_start()
    row = app._connect_row.frame
    before = read_settings()
    _switch(app, False)
    assert read_settings() == dict(before, connect_enabled=False), "its own key, every other as the file holds it"
    assert app._connect_panel is None and app._connect_row is None and not row.winfo_exists()
    assert lines[-1] == "Connect is off."


def test_a_switch_off_whose_save_fails_stays_on_and_says_why(dashboard, monkeypatch):
    """H9 / IK2: the file still says on → the switch, the controls and the line stay on; the reason shown."""
    from app import settings_manager
    app, lines = _settings_open(dashboard, monkeypatch, connect_enabled=True)
    monkeypatch.setattr(settings_manager, "save_settings", lambda *a, **k: False)
    _switch(app, False)
    assert app.var_connect_enabled.get() is True and app._current_settings["connect_enabled"] is True
    assert app._connect_panel is not None and read_settings()["connect_enabled"] is True
    assert any("Connect wasn't switched off" in line for line in lines)


SHELF = {"ja": {"shelf": {"on_shelf": 3, "swap_ins": 0, "runs": [
             {"run": "shelf-2026-10-11-a", "cards": 3, "back": 0, "why": "the cap", "at": "2026-10-11T09:00:00Z",
              "words": ["上層部", "一生懸命"]},
             {"run": "shelf-2026-10-09-a", "cards": 2, "back": 2, "why": "the cap", "at": "2026-10-09T09:00:00Z",
              "words": ["気配"]}]}},
         "zh": {"shelf": {"on_shelf": 0, "runs": [], "swap_ins": 0}}}


def _shelf(monkeypatch, record):
    """Connect's status record stood in for (its shelf), Junban present, `undo.act` recorded with the switch as the
    file holds it at the call."""
    from app.connect import setup, status, undo
    monkeypatch.setattr(setup, "_present", lambda module: True)
    monkeypatch.setattr(status, "read", lambda languages=None, **k: {"languages": record})
    acts = []

    def act(settings, language, job=None, shelf_run=None, confirm=False):
        acts.append((language, shelf_run, confirm, read_settings()["connect_enabled"], on_main()))
        return {"language": language, "shelf": shelf_run, "back": 3, "confirm": True}
    monkeypatch.setattr(undo, "act", act)
    return acts


@pytest.mark.parametrize("answer", [True, False])
def test_switched_off_with_cards_on_the_shelf_asks_once_and_puts_them_back_on_yes(dashboard, monkeypatch, answer):
    """IK-D1 (S16, gate (b)): once off, nothing can show or put the shelf back — so the switch-off asks first; yes puts
    back each restore point with cards still on it (as you), while the preview is still on, then saves off."""
    from tkinter import messagebox
    app, lines = _settings_open(dashboard, monkeypatch, connect_enabled=True)
    acts = _shelf(monkeypatch, SHELF)
    asked = []
    monkeypatch.setattr(messagebox, "askyesno", lambda title, text, **k: (asked.append((text, on_main())), answer)[1])
    _switch(app, False)
    assert asked == [("Put the 3 shelved cards back into your new cards?", True)], "asked once, on the Tk thread"
    if answer:
        assert acts == [("ja", "shelf-2026-10-11-a", True, True, False)], \
            "the restore point with cards on it, put back on a worker before the switch was saved off"
        assert "3 shelved cards back in your new cards." in lines
    else:
        assert acts == []
    assert read_settings()["connect_enabled"] is False and app._connect_panel is None


def test_switched_off_with_an_empty_shelf_asks_nothing(dashboard, monkeypatch):
    from tkinter import messagebox
    app, _lines = _settings_open(dashboard, monkeypatch, connect_enabled=True)
    acts = _shelf(monkeypatch, {"ja": {"shelf": {"on_shelf": 0, "runs": [], "swap_ins": 0}}})
    asked = []
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: (asked.append(a), True)[1])
    _switch(app, False)
    assert asked == [] and acts == [] and read_settings()["connect_enabled"] is False


def test_a_switch_off_of_a_switch_that_was_off_imports_nothing_of_connect(dashboard, monkeypatch):
    """H11: the switch-off's worker reads the shelf only for a switch that was on; otherwise nothing of app.connect."""
    app, _lines = _settings_open(dashboard, monkeypatch)
    for name in [m for m in sys.modules if m.startswith("app.connect")]:
        monkeypatch.delitem(sys.modules, name)
    app._connect_switched(False, False)
    assert not [m for m in sys.modules if m.startswith("app.connect")]
    assert read_settings()["connect_enabled"] is False


def test_opening_connects_window_with_the_switch_off_imports_nothing(monkeypatch):
    """H14: the window's worker checks the switch before it imports the window."""
    from app import main
    for name in [m for m in sys.modules if m.startswith("app.connect")]:
        monkeypatch.delitem(sys.modules, name)
    queued = []
    window = types.SimpleNamespace(var_language=types.SimpleNamespace(get=lambda: "ja"),
                                   _current_settings={"connect_enabled": False},
                                   gui_queue=types.SimpleNamespace(put=queued.append))
    monkeypatch.setattr(main.threading, "Thread", Now)
    main.MasterDashboardApp._open_connect_window(window)
    assert queued == [] and not [m for m in sys.modules if m.startswith("app.connect")]


def test_the_connect_window_learns_whether_junban_is_installed_on_the_worker(monkeypatch):
    """H12: Junban's presence is a file look (`find_spec`): the window's worker asks it and hands it in."""
    import threading
    from app import main
    from app.connect import connect_window
    asked, queued, shown = [], [], []
    monkeypatch.setattr(connect_window, "junban_present", lambda: (asked.append(on_main()), False)[1])
    window = types.SimpleNamespace(var_language=types.SimpleNamespace(get=lambda: "ja"),
                                   _current_settings={"connect_enabled": True},
                                   gui_queue=types.SimpleNamespace(put=queued.append),
                                   _show_connect_window=lambda lang, record, junban=None: shown.append(junban))
    main.MasterDashboardApp._open_connect_window(window)
    deadline = time.monotonic() + 5
    while not queued and time.monotonic() < deadline:
        time.sleep(0.02)
    assert asked == [False], "asked on the worker"
    queued[0]()
    assert shown == [False], "and handed to the window"
    assert threading.current_thread() is threading.main_thread()


# --- the window -----------------------------------------------------------------------------------------------------

def test_with_the_switch_off_settings_shows_it_imports_nothing_of_connect_and_writes_nothing(dashboard, monkeypatch):
    h.write_settings(target_language="ja", theme="Dark Flow")
    app = dashboard()
    for name in [m for m in sys.modules if m.startswith("app.connect")]:
        monkeypatch.delitem(sys.modules, name)
    before = settings_bytes()
    app.toggle_settings_window()
    app.root.update()
    assert app.chk_connect.cget("text") == "Make cards automatically (preview)"
    assert app.var_connect_enabled.get() is False
    assert app._connect_panel is None and app._connect_row is None
    assert not [m for m in sys.modules if m.startswith("app.connect")], "nothing of Connect imported"
    assert settings_bytes() == before, "nothing written"
    # Esc closes (hides) Settings
    app.settings_window.focus_force()
    app.root.update()
    app.settings_window.event_generate("<Escape>")
    app.root.update()
    assert app.settings_window.state() == "withdrawn"


def test_switched_on_in_settings_the_controls_and_the_line_appear_and_off_they_go(dashboard):
    c.library()
    app = dashboard()
    h.write_settings(target_language="ja", connect_enabled=False)
    app.load_settings()
    app.toggle_settings_window()
    _switch(app, True)
    assert _pump(app.root, lambda: app._connect_panel is not None and app._connect_row is not None)
    assert read_settings()["connect_enabled"] is True
    with c.store() as s:
        from app.connect import library
        assert library.has_reader(s), "the watermark is set"
    row = app._connect_row.frame
    assert row.winfo_manager() == "pack" and row.pack_info()["side"] == "bottom"
    # Another language shows its own cap (each language's: SD4)
    from app import settings_manager
    settings_manager.save_keys({"connect_backlog_cap": {"ja": 200, "zh": 80}})
    app.var_language.set("zh")
    assert _pump(app.root, lambda: app._connect_panel is not None and app._connect_panel.var_cap.get() == "80")
    _switch(app, False)
    assert app._connect_panel is None and app._connect_row is None and not row.winfo_exists()
    assert read_settings()["connect_enabled"] is False


def test_the_language_written_again_rebuilds_nothing_and_a_rebuild_reads_settings_on_a_worker(dashboard, monkeypatch):
    """W1 / W2: the language trace fires on every write; only a real change rebuilds the panel (and runs Anki Miner's
    checks again), and its settings are read on a worker, never the Tk thread."""
    from app import settings_manager
    app, _lines = _settings_open(dashboard, monkeypatch, connect_enabled=True)
    panel = app._connect_panel
    app.var_language.set("ja")                      # the same language, written again (load_settings does it)
    _pump(app.root, lambda: False, timeout=0.3)
    assert app._connect_panel is panel, "the same language: nothing rebuilt"
    reads = []
    real = settings_manager.load_settings

    def load_settings(*a, **k):
        caller = sys._getframe(1)
        if caller.f_code.co_name in ("_connect_panel_build", "read") and caller.f_code.co_filename.endswith("main.py"):
            reads.append(on_main())                 # the panel's read (the dashboard's other traces read too)
        return real(*a, **k)
    monkeypatch.setattr(settings_manager, "load_settings", load_settings)
    app.var_language.set("zh")
    assert _pump(app.root, lambda: app._connect_panel is not None and app._connect_panel is not panel)
    assert reads and True not in reads, "settings.json read on a worker"


def test_settings_fits_the_screen():
    """IK15: 1260×740, or the screen less its edges — 150 % on a 1080p screen is 1280×720 logical."""
    from app.main import MasterDashboardApp
    assert MasterDashboardApp._settings_size(1920, 1080) == "1260x740"
    assert MasterDashboardApp._settings_size(1280, 720) == "1240x640"


def test_the_wheel_scrolls_connects_column_over_its_groups_and_leaves_other_bindings(dashboard):
    """H7: Tk sends the column a <Leave> as the pointer enters a group; the wheel still scrolls it there, and no
    other wheel binding (bind_all) is removed."""
    from tkinter import ttk
    from app.main import MasterDashboardApp
    app = dashboard()
    other = []
    app.root.bind_all("<MouseWheel>", lambda e: other.append(1))
    top = tk.Toplevel(app.root)
    top.geometry("300x200")
    outer, inner = MasterDashboardApp._scrolled_column(top)
    outer.pack(fill=tk.BOTH, expand=True)
    group = ttk.LabelFrame(inner, text=" Connect (preview)")
    group.pack(fill=tk.X)
    labels = [ttk.Label(group, text=f"上層部 {i}") for i in range(40)]
    for label in labels:
        label.pack(anchor=tk.W)
    _pump(app.root, lambda: False, timeout=0.3)
    canvas = [w for w in outer.winfo_children() if isinstance(w, tk.Canvas)][0]
    outer.event_generate("<Enter>")
    outer.event_generate("<Leave>")                 # the pointer went on into a group
    assert canvas.yview()[0] == 0.0
    labels[20].event_generate("<MouseWheel>", delta=-120)
    app.root.update()
    assert canvas.yview()[0] > 0.0, "the wheel over a group scrolls the column"
    assert app.root.bind_all("<MouseWheel>"), "the app's other wheel binding is still there"
    app.root.unbind_all("<MouseWheel>")


# --- the final adversary's rows (P3.1 W5) -----------------------------------------------------------------------------

def _answers(monkeypatch, *answers):
    """messagebox.askyesno stood in for: each question kept with its thread, answered in order."""
    from tkinter import messagebox
    asked, left = [], list(answers)
    monkeypatch.setattr(messagebox, "askyesno",
                        lambda title, text, **k: (asked.append((text, on_main())), left.pop(0))[1])
    return asked


def _act_refusing(monkeypatch):
    from app.cli.contract import CliError
    from app.connect import undo
    acts = []

    def act(settings, language, job=None, shelf_run=None, confirm=False):
        acts.append((language, shelf_run, on_main()))
        raise CliError("anki-closed", "Anki isn't open (or stopped answering): connection refused")
    monkeypatch.setattr(undo, "act", act)
    return acts


OFF_ANYWAY = "Turn Connect off anyway? The cards on the shelf stay suspended until you put them back."


@pytest.mark.parametrize("anyway", [True, False])
def test_a_put_back_that_fails_keeps_connect_on_and_asks_whether_to_turn_it_off_anyway(dashboard, monkeypatch, anyway):
    """Adversary #2 (P3.1-3): "Yes" to putting the shelf back, and Anki refuses — the switch isn't saved off with the
    cards still shelved and nothing left to show them. Asked why and whether to turn it off anyway: Yes → off (the
    cards stay suspended, as said); No → Connect, its controls and its line stay on."""
    app, lines = _settings_open(dashboard, monkeypatch, connect_enabled=True)
    _shelf(monkeypatch, SHELF)
    acts = _act_refusing(monkeypatch)
    asked = _answers(monkeypatch, True, anyway)
    _switch(app, False)
    if anyway:          # the second question's Yes starts another worker: wait for it
        assert _pump(app.root, lambda: app._connect_panel is None)
    assert [t for t, _m in asked][0] == "Put the 3 shelved cards back into your new cards?"
    second, on_tk = asked[1]
    assert on_tk and "Anki isn't open (or stopped answering): connection refused" in second
    assert second.endswith(OFF_ANYWAY)
    assert acts == [("ja", "shelf-2026-10-11-a", False)], "tried once, on a worker: Anki refused, no wait"
    if anyway:
        assert read_settings()["connect_enabled"] is False and app._connect_panel is None
        assert app.var_connect_enabled.get() is False and lines[-1] == "Connect is off."
    else:
        assert read_settings()["connect_enabled"] is True and app._current_settings["connect_enabled"] is True
        assert app.var_connect_enabled.get() is True and app._connect_panel is not None
        assert "disabled" not in app.chk_connect.state()


def test_the_switch_offs_put_back_waits_for_anki_miner_as_the_window_does(dashboard, monkeypatch):
    """Adversary #2: Anki Miner holding Anki's write lock (18–24 s a batch) makes the put-back wait and try again — the
    window's own wait (`connect_window.wait_for_writer`), said once — then it's put back and the switch saved off."""
    from app.cli.contract import CliError
    from app.connect import connect_window, undo
    app, lines = _settings_open(dashboard, monkeypatch, connect_enabled=True)
    _shelf(monkeypatch, SHELF)
    answers = [CliError("busy", "Another program is writing to Anki. Try again in a moment.", lock="anki-writer",
                        held_by=None), {"language": "ja", "shelf": "shelf-2026-10-11-a", "back": 3, "confirm": True}]
    acts = []

    def act(settings, language, job=None, shelf_run=None, confirm=False):
        acts.append(shelf_run)
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setattr(undo, "act", act)
    monkeypatch.setattr(connect_window, "writer_busy", lambda: True)
    monkeypatch.setattr(connect_window, "update_waits", lambda: False)
    monkeypatch.setattr(connect_window, "RETRY_GAP_S", 0.05)
    asked = _answers(monkeypatch, True)
    _switch(app, False)
    assert len(asked) == 1 and acts == ["shelf-2026-10-11-a", "shelf-2026-10-11-a"], "it waited and tried again"
    assert lines.count(app.PUT_BACK_WAITING) == 1 and "3 shelved cards back in your new cards." in lines
    assert read_settings()["connect_enabled"] is False and app._connect_panel is None


def test_a_library_there_but_not_opening_is_named_busy_and_the_switch_stays_off(dashboard, monkeypatch):
    """Adversary #3 (G1.1-2): Japanese's library file exists but won't open (busy, damaged, read-only) — its watermark
    can't be set, so the switch isn't saved on with the old one. Chinese, with no library yet, is fine as before."""
    from app.connect import library
    c.library()
    app, lines = _settings_open(dashboard, monkeypatch)
    monkeypatch.setattr(library, "open_store", lambda lang, role="connect": None)
    before = settings_bytes()
    _switch(app, True)
    assert settings_bytes() == before and app.var_connect_enabled.get() is False
    assert app._connect_panel is None and app._connect_row is None
    failed = [line for line in lines if line.startswith("Connect wasn't switched on")]
    assert failed == ["Connect wasn't switched on: Japanese: the library is busy; try again in a moment. Nothing "
                      "changed; try again."], "named for Japanese only: Chinese has no library file"


def test_settings_shown_again_reads_the_file_on_a_worker_and_the_panel_follows_another_windows_write(
        dashboard, monkeypatch):
    """Adversary #5: 順's window writes the sync minute while Settings is hidden. Shown again, settings.json is read on
    a worker and the panel rebuilt from it — so picking the value the panel once showed is a change, and written.
    Shown again with nothing changed: nothing rebuilt."""
    from app import settings_manager
    app, _lines = _settings_open(dashboard, monkeypatch, connect_enabled=True, anki_sync_delay_min=1)
    panel = app._connect_panel
    app.toggle_settings_window()                                    # hidden
    settings_manager.save_keys({"anki_sync_delay_min": 5})          # 順's "5 minutes after"
    reads = []
    real = settings_manager.load_settings

    def load_settings(*a, **k):
        if sys._getframe(1).f_code.co_name == "read":
            reads.append(on_main())
        return real(*a, **k)
    monkeypatch.setattr(settings_manager, "load_settings", load_settings)
    app.toggle_settings_window()                                    # shown again
    assert _pump(app.root, lambda: app._connect_panel is not None and app._connect_panel is not panel)
    assert reads and True not in reads, "read on a worker"
    fresh = app._connect_panel
    assert fresh.combo_sync.get() == "5 minutes after"
    assert fresh._set("anki_sync_delay_min", 1, 1) and read_settings()["anki_sync_delay_min"] == 1, \
        "'About a minute after' picked again is a change now: written"
    app.toggle_settings_window()
    app.toggle_settings_window()
    _pump(app.root, lambda: False, timeout=0.5)
    assert app._connect_panel is fresh, "nothing changed: nothing rebuilt"


def test_settings_shown_again_with_the_switch_off_imports_nothing_of_connect(dashboard, monkeypatch):
    app, _lines = _settings_open(dashboard, monkeypatch)
    for name in [m for m in sys.modules if m.startswith("app.connect")]:
        monkeypatch.delitem(sys.modules, name)
    before = settings_bytes()
    app.toggle_settings_window()
    app.toggle_settings_window()
    _pump(app.root, lambda: False, timeout=0.3)
    assert not [m for m in sys.modules if m.startswith("app.connect")] and settings_bytes() == before


def _kicks(monkeypatch):
    from app.connect import kick
    kicks = []
    monkeypatch.setattr(kick, "kick", lambda settings: kicks.append((settings.get("connect_enabled"), on_main())))
    return kicks


def _quiet_update(app, monkeypatch):
    from app import updater
    for name in ("drop_update_lock", "release_children", "discard_staged"):
        monkeypatch.setattr(updater, name, lambda *a, **k: None)
    monkeypatch.setattr(app, "_maybe_auto_generate", lambda: None)
    monkeypatch.setattr(app, "_replan_restart", lambda: None)


def test_a_cancelled_update_kicks_connect_so_its_line_stops_saying_installing(dashboard, monkeypatch):
    """Adversary #7: Connect stopped between batches for the update ("Surasura is installing an update."); the update
    cancelled, its lock gone, Connect is kicked (on a worker) to go on — after a cancel once downloaded and after one
    during the download; never while the dashboard is closing."""
    app = dashboard()
    app._current_settings = {"connect_enabled": True}
    _quiet_update(app, monkeypatch)
    kicks = _kicks(monkeypatch)
    app._update_job = job = {"done": True, "lock": None, "after": None, "window": None}
    app._cancel_update(job)
    assert _pump(app.root, lambda: kicks) and kicks == [(True, False)]
    app._update_downloaded({"ended": True, "start_held": True, "lock": None})
    assert _pump(app.root, lambda: len(kicks) == 2)
    app._update_job = job = {"done": True, "lock": None, "after": None, "window": None}
    app._cancel_update(job, start_held=False)                       # the dashboard closing
    _pump(app.root, lambda: False, timeout=0.3)
    assert len(kicks) == 2


def test_a_cancelled_update_with_connect_off_imports_nothing_of_connect(dashboard, monkeypatch):
    app = dashboard()
    app._current_settings = {"connect_enabled": False}
    _quiet_update(app, monkeypatch)
    for name in [m for m in sys.modules if m.startswith("app.connect")]:
        monkeypatch.delitem(sys.modules, name)
    app._update_job = job = {"done": True, "lock": None, "after": None, "window": None}
    app._cancel_update(job)
    _pump(app.root, lambda: False, timeout=0.3)
    assert not [m for m in sys.modules if m.startswith("app.connect")]


# --- P3.2: hato's back-fill and surasura.json at the switch (RUNBOOK-P3.2 row 3.2.4) ---------------------------------

def _summary(lang, **more):
    from app.connect import hato
    out = {"language": lang, "hato": hato.ASKED, "new": 3, "same": 0, "replaced": 0, "refused": [], "unpaired": [],
           "stopped": None, "skipped": None, "need": None}
    out.update(more)
    return out


def _hato_connected(tmp_path):
    """hato's entry in the shared tools folder (hato.json), as hato 1.1.0 writes it while it connects to Surasura."""
    cli = tmp_path / "hato" / "hato-cli.exe"
    cli.parent.mkdir(exist_ok=True)
    cli.write_bytes(b"MZ")
    c.FakeHato(str(cli.parent), str(cli)).entry()


def test_switching_on_back_fills_each_set_up_language_on_the_worker_and_logs_its_summary(dashboard, monkeypatch,
                                                                                          tmp_path):
    """09-hato-layer v2 §4: once the switch is saved on, hato's pairings are back-filled on the switch's worker (never
    the Tk thread), once per language Surasura is set up for, each summary in the Processing Log in place of 2.5's
    "the back-fill is skipped"."""
    from app.connect import hato
    _hato_connected(tmp_path)
    c.library()
    os.makedirs(os.path.join(h.root(), "User Files", "zh"), exist_ok=True)       # Chinese set up too
    calls = []

    def backfill(lang, settings, wait=10, run=None):
        calls.append((lang, settings.get("connect_enabled"), read_settings()["connect_enabled"], on_main()))
        return _summary(lang)
    monkeypatch.setattr(hato, "backfill", backfill)
    app, lines = _settings_open(dashboard, monkeypatch)
    _switch(app, True)
    assert _pump(app.root, lambda: len([x for x in lines if x.startswith("hato's pairings")]) == 2)
    assert calls == [("ja", True, True, False), ("zh", True, True, False)], "after the save, on the worker, each once"
    assert "hato's pairings (Japanese): 3 new, 0 already there." in lines
    assert "hato's pairings (Chinese): 3 new, 0 already there." in lines
    assert not any("back-fill is skipped" in x for x in lines)


def test_a_language_not_set_up_isnt_back_filled(dashboard, monkeypatch, tmp_path):
    from app.connect import hato
    _hato_connected(tmp_path)
    c.library()                                                     # Japanese only
    calls = []
    monkeypatch.setattr(hato, "backfill", lambda lang, settings, **k: (calls.append(lang), _summary(lang))[1])
    app, lines = _settings_open(dashboard, monkeypatch)
    _switch(app, True)
    assert _pump(app.root, lambda: any(x.startswith("hato's pairings (Japanese)") for x in lines))
    _pump(app.root, lambda: False, timeout=0.3)
    assert calls == ["ja"]


def test_a_back_fill_that_fails_leaves_the_switch_on_and_says_so(dashboard, monkeypatch, tmp_path):
    """A back-fill that fails (hato's answer, the ledger, anything) is said in the Processing Log; Connect stays on,
    saved on, with its controls and line — never turned back off by it."""
    from app.connect import hato
    _hato_connected(tmp_path)
    c.library()

    def backfill(lang, settings, wait=10, run=None):
        raise OSError("the ledger is locked")
    monkeypatch.setattr(hato, "backfill", backfill)
    app, lines = _settings_open(dashboard, monkeypatch)
    _switch(app, True)
    assert _pump(app.root, lambda: any(x.startswith("hato's pairings (Japanese) weren't read: the ledger is locked")
                                       for x in lines))
    assert read_settings()["connect_enabled"] is True and app.var_connect_enabled.get() is True
    assert app._current_settings["connect_enabled"] is True and "disabled" not in app.chk_connect.state()
    assert _pump(app.root, lambda: app._connect_panel is not None and app._connect_row is not None)
    assert not any(x.startswith("Connect wasn't switched on") for x in lines)


def test_switching_on_with_hato_connected_says_it_is_asking_hato_before_the_answers(dashboard, monkeypatch, tmp_path):
    """hato's entry in the shared tools folder: a line says hato is being asked as the back-fill starts, then each
    language's summary once it has answered."""
    # why: hato is given up to a minute a language; with no line until it ends, the Processing Log said nothing of it
    from app.connect import hato
    _hato_connected(tmp_path)
    c.library()
    monkeypatch.setattr(hato, "backfill", lambda lang, settings, **k: _summary(lang))
    app, lines = _settings_open(dashboard, monkeypatch)
    _switch(app, True)
    assert _pump(app.root, lambda: "hato's pairings (Japanese): 3 new, 0 already there." in lines)
    assert "Asking hato for its pairings…" in lines
    assert lines.index("Asking hato for its pairings…") < lines.index(
        "hato's pairings (Japanese): 3 new, 0 already there."), "said as it starts, before the answer"


def test_switching_on_without_hato_says_nothing_of_hato_in_the_processing_log(dashboard, monkeypatch):
    """No hato.json in the shared tools folder (hato isn't installed, or never connected): the switch-on still runs
    the back-fill, whose reason goes to Connect's own log, and the Processing Log says nothing of hato."""
    # why: every switch-on for a learner without hato logged "hato couldn't be asked for its pairings" per language
    from app.connect import hato
    c.library()
    calls = []

    def backfill(lang, settings, wait=10, run=None):
        calls.append(lang)
        return _summary(lang, hato="hato isn't connected to Surasura (it has no entry in the shared tools folder)")
    monkeypatch.setattr(hato, "backfill", backfill)
    app, lines = _settings_open(dashboard, monkeypatch)
    _switch(app, True)
    assert _pump(app.root, lambda: calls == ["ja"])
    _pump(app.root, lambda: False, timeout=0.3)
    assert [x for x in lines if "hato" in x] == [], lines


def test_the_switch_refreshes_surasura_json_on_and_off(dashboard, monkeypatch, tmp_path):
    """09-hato-layer v2 §3: surasura.json lists `register` only while the preview is on — rewritten after the switch's
    save, on and off, on the switch's worker, so hato registers its drops from then on (and stops when it's off)."""
    from app import tools_entry
    cli = tmp_path / "surasura-cli.exe"
    cli.write_bytes(b"MZ")
    monkeypatch.setenv("SURASURA_TOOLS_CLI", str(cli))
    monkeypatch.setenv("HOUSEKI_TOOLS_DIR", str(tmp_path / "tools"))
    entry = tmp_path / "tools" / "surasura.json"
    c.library(connect=False)            # off from the start: the window's own start-up write lists no `register`
    app, _lines = _settings_open(dashboard, monkeypatch)
    assert _pump(app.root, lambda: entry.exists()), "written at the window's start"
    real, refreshes = tools_entry.refresh, []
    monkeypatch.setattr(tools_entry, "refresh", lambda settings=None: (
        refreshes.append(((settings or {}).get("connect_enabled"), on_main())), real(settings))[1])
    assert json.loads(entry.read_text(encoding="utf-8"))["verbs"] == ["status"]
    _switch(app, True)
    assert refreshes == [(True, False)] and json.loads(entry.read_text(encoding="utf-8"))["verbs"] == \
        ["status", "register"]
    _switch(app, False)
    assert refreshes == [(True, False), (False, False)]
    assert json.loads(entry.read_text(encoding="utf-8"))["verbs"] == ["status"]


def test_a_tools_entry_that_cant_be_written_changes_nothing_of_the_switch(dashboard, monkeypatch):
    """A failure is only logged: the switch saves and shows on, then off, as it would."""
    from app import tools_entry

    def refuses(settings=None):
        raise OSError("the shared tools folder is read-only")
    monkeypatch.setattr(tools_entry, "refresh", refuses)
    c.library()
    app, lines = _settings_open(dashboard, monkeypatch)
    _switch(app, True)
    assert read_settings()["connect_enabled"] is True and app.var_connect_enabled.get() is True
    _switch(app, False)
    assert read_settings()["connect_enabled"] is False and lines[-1] == "Connect is off."


def test_one_shelved_card_is_named_in_the_singular():
    """The drill found "Put the 1 shelved cards back": the switch-off question and its answer count one card as one."""
    import inspect
    import app.main as app
    src = inspect.getsource(app)
    assert "shelved {'card' if n == 1 else 'cards'} back into your new cards?" in src
