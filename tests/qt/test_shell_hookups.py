"""The shell's hookups after W3.1a (the window's batch: W3.5 part 3's mount, W3.3's P7, W3.4 row 1's quit).

What a wrong answer would cost:
  * the Settings page built on the first frame's path (the window opens slower), never built, or built twice;
    `open_setting` that lands on the wrong tab or nothing;
  * the start gate skipped, or run after the store opened (an import into a library already open: §S3.1 D3);
  * a quiet Generate while the setup wizard is up (an upgrader's library has no journey yet: AD-8), or one never asked
    again after it closes;
  * *Install Anki Miner…* in Settings opening a browser page instead of the in-Surasura route (G1.3-2), or its install
    invisible to the bar and the quit;
  * a ported window's own close skipped at quit (its run not told to stop, its workspace left: AD4-4), a deferred delete
    left for Python's teardown or a 順 thread still running Python at exit (the exit crash, W3.4 row 2 / row 6).

On the real main window (`shell.open_window` on the test root) unless a stand-in is named.
"""
import inspect
import threading
import time

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from app.qt import first_run, settings_connect, shell, windows
from app.qt import settings_page as sp
from app.qt import wizard as W
from tests.qt.conftest import wait_until
from tests.qt.test_wizard import FakeApi, FakeMiner, miner_look


@pytest.fixture
def services(qapp):
    s = shell.Services()
    yield s
    s.shutdown(0.5)


@pytest.fixture
def window(qapp, services):
    win = shell.open_window(qapp, services)
    win.resize(1280, 800)
    win.show()
    QApplication.processEvents()
    yield win
    win.close()


# --- W3.3 P7: the Settings page in its tab ------------------------------------------------------------------------- #
def test_the_settings_page_is_made_the_first_time_its_tab_shows_and_only_once(window):
    assert window.settings_page is None                                   # never on the first frame's path
    window.show_tab("settings")
    page = window.settings_page
    assert isinstance(page, sp.SettingsPage) and page.parentWidget() is window.page_widgets["settings"]
    assert window.pages.currentWidget() is window.page_widgets["settings"]
    window.show_tab("current")
    window.show_tab("settings")
    assert window.settings_page is page and len(window.findChildren(sp.SettingsPage)) == 1
    for row_id in ("connect_enabled", "placing_rules", "soon_line", "mine_line", "set_up_again"):
        assert page.custom_row(row_id).layout().count() > 0, f"{row_id}'s rows weren't attached"
    assert wait_until(lambda: page.built, 20)


def test_open_setting_shows_the_settings_tab_with_the_row_brought_into_view(window, monkeypatch):
    revealed = []
    monkeypatch.setattr(sp.SettingsPage, "reveal", lambda self, target: revealed.append(target) or True)
    assert window.open_setting("soon_line") is True
    assert window.current_tab() == "settings" and revealed == ["soon_line"]


def test_a_package_whose_rows_fail_never_keeps_the_page_from_opening(window, monkeypatch):
    def broken(_page):
        raise RuntimeError("a row package that broke")
    monkeypatch.setattr(settings_connect, "attach", broken)
    window.show_tab("settings")
    assert isinstance(window.settings_page, sp.SettingsPage)
    assert window.settings_page.custom_row("set_up_again").layout().count() > 0     # the others still attached


def test_install_anki_miner_opens_the_wizard_at_its_anki_miner_page(window, monkeypatch):
    opened = []
    monkeypatch.setattr(windows, "open_url", lambda url: opened.append(url))
    monkeypatch.setattr(W, "services_api", lambda: FakeApi())
    monkeypatch.setattr(W, "miner_api", lambda: FakeMiner(miner_look("missing")))
    assert settings_connect.install_anki_miner(window) is True
    wiz = first_run.opened(window)
    assert wiz is not None and W.PAGES[wiz.index] == "cards" and opened == []
    wiz._close("later")
    QApplication.processEvents()


def test_install_anki_miner_with_no_window_or_no_wizard_opens_the_releases_page(window, monkeypatch):
    from app.connect import setup
    opened = []
    monkeypatch.setattr(windows, "open_url", lambda url: opened.append(url) or True)
    assert settings_connect.install_anki_miner(None) is True and opened == [setup.RELEASES]
    monkeypatch.setattr(first_run, "open_again", lambda shell, **kw: None)      # a wizard that couldn't open
    assert settings_connect.install_anki_miner(window) is True and opened == [setup.RELEASES] * 2


# --- W3.5 part 3: the gate, the wizard's mount and its hold ------------------------------------------------------- #
def test_main_runs_the_start_gate_after_the_claim_and_before_the_services():
    source = inspect.getsource(shell.main)
    assert source.index("instance.claim(") < source.index("start_gate.gate(app)") < source.index("Services(")
    assert source.index("start_gate.gate(app)") < source.index("instance.release()\n        return 0")


def test_the_wizard_up_holds_the_quiet_generates_and_its_close_asks_again(window, monkeypatch):
    ended = []
    monkeypatch.setattr(window.services, "setup_ended", lambda: ended.append(True))
    wiz = first_run.host(window, api=FakeApi(), miner=FakeMiner(miner_look("missing")))
    assert wiz is not None and window.services.setup_open.is_set()
    wiz._close("later")
    assert wait_until(lambda: ended == [True])


def test_the_hold_reaches_the_automation_and_the_keeper_once_the_duties_start(services):
    class Duty:
        held = None
    services.automation, services.replan = Duty(), Duty()
    services._hold_while_setup()
    assert services.automation.held() is False and services.replan.held() is False
    services.setup_open.set()
    assert services.automation.held() is True and services.replan.held() is True


def test_setup_ended_clears_the_hold_and_asks_as_a_focus_does(services, monkeypatch):
    asked = []
    monkeypatch.setattr(services, "activated", lambda: asked.append(True))
    services.setup_open.set()
    services.setup_ended()
    assert not services.setup_open.is_set() and asked == [True]


def test_a_finished_setup_opens_no_wizard_at_the_first_frame(window, monkeypatch):
    window.services.settings.set({"onboarding_completed": True, "setup_seen": "3.0"})
    hosted = []
    real = first_run.host
    monkeypatch.setattr(first_run, "host", lambda shell: hosted.append(real(shell)))
    monkeypatch.setattr(window.services, "has_duties", lambda: False)
    monkeypatch.setattr(shell.bridge, "run_in_worker", lambda *a, **k: None)      # the duties never made here
    window.start_duties()
    assert hosted == [None] and not window.services.setup_open.is_set()


# --- W3.4 row 1: the quit ------------------------------------------------------------------------------------------ #
def test_the_quit_closes_every_ported_window_through_its_own_close(window):
    closed = []

    class Ported(windows.SecondaryWindow):
        def closeEvent(self, event):
            closed.append(self.windowTitle())
            super().closeEvent(event)
    win = windows.show(window, "test-port", lambda sh: Ported(sh, "Test"))
    assert win.isVisible()
    window.close()
    assert closed and win.gone


def test_close_all_with_nothing_open_asks_nothing(window):
    assert windows.close_all(window) == 0


def test_the_quits_last_step_waits_for_the_pool_and_the_junban_threads(qapp):
    from app.qt import bridge
    stop = threading.Event()
    thread = threading.Thread(target=lambda: stop.wait(0.3), name="junban-read-test", daemon=True)
    thread.start()
    pooled = threading.Event()
    bridge.run_in_worker(lambda: (time.sleep(0.2), pooled.set()))
    assert shell.quiet_exit(workers_ms=3000, join_s=2.0) is True
    assert pooled.is_set() and not thread.is_alive()


def test_a_junban_thread_still_running_past_its_wait_is_said_not_waited_for_forever(qapp):
    stop = threading.Event()
    thread = threading.Thread(target=lambda: stop.wait(5), name="junban-job-test", daemon=True)
    thread.start()
    began = time.monotonic()
    try:
        assert shell.quiet_exit(workers_ms=100, join_s=0.2) is False
        assert time.monotonic() - began < 2.0
    finally:
        stop.set()
        thread.join(2)


def test_main_ends_with_the_quiet_exit_after_the_services_stopped():
    source = inspect.getsource(shell.main)
    assert source.index("services.shutdown(") < source.index("quiet_exit()")


# --- the wizard's *Make cards for me*: Connect's watermarks (W-A7) ------------------------------------------------- #
from tests.qt.test_wizard import make  # noqa: E402,F401  (the wizard over a stand-in window)


@pytest.mark.parametrize("was, now, asked", [(False, True, True), (True, True, False)])
def test_make_cards_for_me_turned_on_in_the_wizard_moves_connects_watermarks(make, monkeypatch, was, now, asked):
    # Off -> on: everything placed while Connect was off must never be mined (G1.1-2). `turned_on` decides from the
    # before / after it is handed, so the wizard must hand the settings as they were before its own save.
    from app.connect import resume
    calls, done = [], threading.Event()
    def record(before, after):
        calls.append((before, after, not before.get("connect_enabled") and bool(after.get("connect_enabled"))))
        done.set()
    monkeypatch.setattr(resume, "turned_on", record)
    wiz, _shell, _api, settings, _m = make(data={"connect_enabled": was})
    wiz._save("cards", {"make_cards": now})
    assert settings.calls[-1] == {"connect_enabled": now}
    assert wait_until(done.is_set)
    before, after, off_to_on = calls[0]
    assert before["connect_enabled"] is was and after["connect_enabled"] is now
    assert bool(off_to_on) is asked


def test_settings_opens_in_the_language_the_settings_hold_now_above_its_bottom_edge(window):
    # A switch made before the first visit (the wizard's page 1) is the page's language; the page
    # sits above the bottom edge every page carries, never under it.
    window.services.settings.set({"target_language": "zh"})
    window.show_tab("settings")
    page = window.settings_page
    assert page.language == "zh"
    holder = window.page_widgets["settings"].layout()
    assert holder.indexOf(page) == 0 and holder.count() >= 2


def test_a_wizard_that_breaks_while_it_is_hooked_up_leaves_no_hold(window, monkeypatch):
    # The window's parts and the quiet Generates are never held under a wizard that isn't there.
    monkeypatch.setattr(first_run, "_Cover", lambda wiz, area: (_ for _ in ()).throw(RuntimeError("broke")))
    assert first_run.host(window, api=FakeApi(), miner=FakeMiner(miner_look("missing"))) is None
    assert first_run.opened(window) is None
    assert not window.services.setup_open.is_set() and window.header.isEnabled() and window.pages.isEnabled()


def test_set_up_again_from_settings_closes_back_onto_settings(window):
    # The learner opened it from Settings: closing it keeps their place there; a first run's wizard
    # still closes onto Current (the contract).
    window.show_tab("settings")
    wiz = first_run.open_again(window, api=FakeApi(), miner=FakeMiner(miner_look("missing")))
    wiz._close("later")
    QApplication.processEvents()
    assert window.current_tab() == "settings"
    wiz = first_run.host(window, api=FakeApi(), miner=FakeMiner(miner_look("missing")))
    wiz._close("later")
    QApplication.processEvents()
    assert window.current_tab() == "current"
