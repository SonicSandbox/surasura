"""Connect's switch, its work on its own (W3.3 P5): `app/connect/switch.py`, moved out of the Tk window so 3.0's Qt
Settings row runs the same steps. The Tk switch's own suites (test_connect_switch*.py) prove the window still does
what it did; these prove the moved functions, with no window at all.

What a wrong answer would cost: a switch-on that saves `connect_enabled` with one language's watermark missing (that
language's whole history mined), or before the watermarks (a placement in between mined); a save that writes more than
its one key (a 2.5 file gaining defaults); surasura.json refreshed before the save (hato told `register` while the file
still says off) or after a failed one; a switch-off that drops the readers or says "off" when the file still says on; a
shelf the window can't show (no Junban) offered for a put-back; a put-back that waits for Anki silently or loses the
reason a restore point stayed on the shelf. Stores, hato, the undo and AnkiConnect are stood in for — never a real
Anki, never the network; settings.json is the test root's own (`SURASURA_TEST_ROOT`)."""
import os
import subprocess
import sys

import pytest

from tests.connect_tk_helpers import read_settings, settings_bytes, settings_path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _write_settings(text):
    with open(settings_path(), "w", encoding="utf-8") as f:
        f.write(text)


class FakeStore:
    """A library store that opens: entered and left as `with store:` does; its readers dropped are recorded."""

    def __init__(self, lang, order):
        self.lang, self.order = lang, order

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def unregister_reader(self, name):
        self.order.append(f"unregister {self.lang} {name}")


@pytest.fixture
def world(monkeypatch, tmp_path):
    """Every step the switch takes recorded in one list, in the order taken: each language's store opened and its
    watermark set, its last-looked-at list forgotten (a ledger there), the save (the real `save_keys`, onto the test
    root's file), surasura.json's refresh (with the file as saved) and every log line."""
    from app import library_store, settings_manager, tools_entry
    from app.connect import ledger, level, library
    order, refreshed = [], []
    ledger_file = tmp_path / "ledger.sqlite"
    ledger_file.write_bytes(b"")
    monkeypatch.setattr(ledger, "path", lambda: str(ledger_file))
    monkeypatch.setattr(library, "open_store", lambda lang, role="connect": (order.append(f"open {lang}"),
                                                                            FakeStore(lang, order))[1])
    monkeypatch.setattr(library, "switch_on", lambda store, *a: order.append(f"watermark {store.lang}"))
    # P4.1 L2 (F-6): the switch goes through `resume.watermarks`, which hands `forget` its open ledger
    monkeypatch.setattr(level, "forget", lambda lang, ledger=None: order.append(f"forget {lang}"))
    monkeypatch.setattr(library, "has_reader", lambda store, name=library.READER: True)
    monkeypatch.setattr(library_store.Store, "unregister_reader", lambda self, name: None, raising=False)
    real_save = settings_manager.save_keys
    saves = []

    def save_keys(changes, *a, **k):
        order.append("save")
        saves.append((dict(changes), k))
        return real_save(changes, *a, **k)
    monkeypatch.setattr(settings_manager, "save_keys", save_keys)

    def refresh(settings=None):
        order.append("refresh")
        refreshed.append(dict(settings or {}))
    monkeypatch.setattr(tools_entry, "refresh", refresh)
    _write_settings('{"target_language": "ja", "theme": "Dark Flow", "placing_rules": {"hato": "top"}}')

    def log(line):
        order.append(f"log {line}")
    return type("World", (), {"order": order, "refreshed": refreshed, "saves": saves, "log": staticmethod(log)})


# --- turn_on ----------------------------------------------------------------------------------------------------------

def test_turn_on_sets_every_watermark_before_saving_only_the_switch_then_refreshes_the_tools_entry(world):
    """G1.1-2 / IK2: each language's watermark (and its list forgotten) first, then `connect_enabled` saved alone and
    strictly (it is read next), then surasura.json refreshed with the file as saved, then "on" said."""
    from app.connect import switch
    before = read_settings()
    ok, saved, why = switch.turn_on(("ja", "zh"), log=world.log)
    assert (ok, why) == (True, None) and saved["connect_enabled"] is True
    assert world.order == ["open ja", "watermark ja", "forget ja", "open zh", "watermark zh", "forget zh", "save",
                           "refresh", f"log {switch.ON}"]
    assert read_settings() == dict(before, connect_enabled=True), "its own key, every other as the file holds it"
    assert world.saves[0][0] == {"connect_enabled": True} and world.saves[0][1].get("strict") is True
    assert world.refreshed == [saved]


def test_turn_on_with_one_watermark_failing_saves_nothing_and_names_that_language(world, monkeypatch):
    """H8: Chinese's library refusing — Japanese still set, nothing saved, nothing refreshed, the reason names Chinese;
    never "on" with a watermark missing."""
    from app.connect import library, switch

    def open_store(lang, role="connect"):
        world.order.append(f"open {lang}")
        if lang == "zh":
            raise OSError("the library file is locked")
        return FakeStore(lang, world.order)
    monkeypatch.setattr(library, "open_store", open_store)
    before = settings_bytes()
    ok, saved, why = switch.turn_on(("ja", "zh"), log=world.log)
    assert (ok, saved, why) == (False, None, "Chinese: the library file is locked")
    assert settings_bytes() == before
    assert "save" not in world.order and "refresh" not in world.order
    assert world.order[-1] == "log " + switch.NOT_ON.format(why)
    assert world.order[-1] == "log Connect wasn't switched on: Chinese: the library file is locked. Nothing changed; " \
                              "try again."


def test_turn_on_with_a_library_there_but_not_opening_calls_it_busy(world, monkeypatch, tmp_path):
    """Adversary #3: Japanese's library file exists but won't open — its watermark can't be set, so nothing is saved;
    Chinese, with no library file, is fine."""
    from app import library_store
    from app.connect import library, switch
    there = tmp_path / "library.db"
    there.write_bytes(b"")
    monkeypatch.setattr(library, "open_store", lambda lang, role="connect": None)
    monkeypatch.setattr(library_store, "library_db_path",
                        lambda lang, data_dir: str(there) if lang == "ja" else str(tmp_path / "none.db"))
    ok, _saved, why = switch.turn_on(("ja", "zh"), log=world.log)
    assert not ok and why == "Japanese: the library is busy; try again in a moment"
    assert "save" not in world.order and "connect_enabled" not in read_settings()


def test_turn_on_whose_save_is_held_by_another_saver_returns_not_ok_and_does_nothing_after(world, monkeypatch):
    """The `settings` lock held past the wait: `save_keys(strict)` raises — nothing written or queued, no refresh, the
    reason said; the caller puts the switch back off."""
    from app import locks, settings_manager
    from app.connect import switch
    monkeypatch.setattr(settings_manager, "LOCK_WAIT", 0.3)
    held = locks.take("settings", "another save", owner=object())
    try:
        ok, saved, why = switch.turn_on(("ja",), log=world.log)
    finally:
        held.release()
    assert not ok and saved is None and why.startswith("the switch wasn't saved: ")
    assert world.order.index("save") == len(world.order) - 2, "the save the last step before the failure is said"
    assert "refresh" not in world.order and world.order[-1].startswith("log Connect wasn't switched on: the switch")
    assert settings_manager.flush_keys(timeout=5) and "connect_enabled" not in read_settings()


def test_turn_on_returns_before_the_hato_backfill(world, monkeypatch):
    """The caller shows the switch on first, then runs `backfill` on the same worker: `turn_on` never asks hato."""
    from app.connect import hato, switch
    asked = []
    monkeypatch.setattr(hato, "backfill", lambda *a, **k: asked.append(a))
    monkeypatch.setattr(hato, "connected", lambda: asked.append("connected") or True)
    assert switch.turn_on(("ja",), log=world.log)[0] and asked == []


# --- backfill ---------------------------------------------------------------------------------------------------------

def _user_files(lang):
    from app.path_utils import get_user_files_path
    os.makedirs(get_user_files_path(lang), exist_ok=True)


def test_backfill_asks_hato_for_each_set_up_language_and_says_each_summary(monkeypatch):
    """P3.2 row 3.2.4: with hato's entry there, "asking" then each set-up language's summary to the log; a language
    Surasura isn't set up for (no User Files folder) is skipped."""
    from app.connect import hato, switch
    _user_files("ja")
    calls, lines = [], []
    monkeypatch.setattr(hato, "connected", lambda: True)
    monkeypatch.setattr(hato, "backfill", lambda lang, settings: (calls.append((lang, settings)), {"lang": lang})[1])
    monkeypatch.setattr(hato, "say", lambda summary: f"hato paired {summary['lang']}")
    switch.backfill(("ja", "zh"), {"connect_enabled": True}, log=lines.append)
    assert calls == [("ja", {"connect_enabled": True})]
    assert lines == [switch.ASKING_HATO, "hato paired ja"]


def test_backfill_without_hato_prints_instead_of_logging_and_a_failure_is_only_said(monkeypatch, capsys):
    """No hato here: nothing goes to the Processing Log (Connect's log has why); a failing back-fill names its
    language and says the switch stays on — it never raises."""
    from app.connect import hato, switch
    _user_files("zh")
    monkeypatch.setattr(hato, "connected", lambda: False)

    def backfill(lang, settings):
        raise RuntimeError("hato timed out")
    monkeypatch.setattr(hato, "backfill", backfill)
    lines = []
    switch.backfill(("zh",), {}, log=lines.append)
    assert lines == []
    assert switch.NOT_READ.format("Chinese", "hato timed out") in capsys.readouterr().out


# --- turn_off ---------------------------------------------------------------------------------------------------------

def test_turn_off_saves_the_switch_off_then_refreshes_then_drops_the_readers(world):
    """Off: `connect_enabled` saved False alone, surasura.json refreshed with the file as saved (no `register`), the
    readers dropped where the store can, then "off" said."""
    from app.connect import switch
    _write_settings('{"target_language": "ja", "connect_enabled": true, "theme": "Dark Flow"}')
    ok, saved, why = switch.turn_off(was_on=True, log=world.log, languages=("ja", "zh"))
    assert (ok, why) == (True, None) and saved["connect_enabled"] is False
    assert world.order == ["save", "refresh", "open ja", "unregister ja connect", "open zh", "unregister zh connect",
                           f"log {switch.OFF}"]
    assert read_settings() == {"target_language": "ja", "connect_enabled": False, "theme": "Dark Flow"}
    assert world.refreshed == [saved] and world.saves[0][0] == {"connect_enabled": False}


def test_turn_off_of_a_switch_that_was_off_opens_no_store(world):
    """Readers are dropped only for a switch that was on: the save and the refresh alone."""
    from app.connect import switch
    assert switch.turn_off(was_on=False, log=world.log)[0]
    assert world.order == ["save", "refresh", f"log {switch.OFF}"]


def test_turn_off_whose_save_fails_does_nothing_else_and_says_it_stays_on(world, monkeypatch):
    """A failed save: no refresh, no reader dropped, the reason said — the caller shows the switch on again."""
    from app import settings_manager
    from app.connect import switch

    def refuses(*a, **k):
        world.order.append("save")
        raise OSError("your settings file is being saved by another window or program just now")
    monkeypatch.setattr(settings_manager, "save_keys", refuses)
    _write_settings('{"target_language": "ja", "connect_enabled": true}')
    ok, saved, why = switch.turn_off(was_on=True, log=world.log)
    assert not ok and saved is None and "being saved by another window" in why
    assert world.order == ["save", "log Connect wasn't switched off: the switch wasn't saved: your settings file is "
                                   "being saved by another window or program just now. It stays on; try again."]
    assert read_settings()["connect_enabled"] is True


# --- shelved / put_back -----------------------------------------------------------------------------------------------

SHELF = {"ja": {"shelf": {"on_shelf": 3, "swap_ins": 0, "runs": [
             {"run": "shelf-2026-10-11-a", "cards": 3, "back": 0, "words": ["上層部", "一生懸命"]},
             {"run": "shelf-2026-10-09-a", "cards": 2, "back": 2, "words": ["気配"]}]}},
         "zh": {"shelf": {"on_shelf": 0, "runs": [], "swap_ins": 0}}}


def test_shelved_is_empty_without_junban_and_reads_no_record(monkeypatch):
    """Only Junban can put a shelf back: without it there is nothing to offer, and the record isn't read."""
    from app.connect import setup, status, switch
    read = []
    monkeypatch.setattr(setup, "_present", lambda module: False)
    monkeypatch.setattr(status, "read", lambda languages=None, **k: read.append(languages) or {"languages": SHELF})
    assert switch.shelved(("ja", "zh")) == {} and read == []


def test_shelved_lists_only_restore_points_with_cards_still_on_the_shelf(monkeypatch):
    """Each language asked; a run whose cards are all back, and a language with an empty shelf, aren't offered."""
    from app.connect import setup, status, switch
    asked = []
    monkeypatch.setattr(setup, "_present", lambda module: True)
    monkeypatch.setattr(status, "read", lambda languages=None, **k: asked.append(languages) or {"languages": SHELF})
    assert switch.shelved(("ja", "zh")) == {"ja": (3, ["shelf-2026-10-11-a"])}
    assert asked == [["ja", "zh"]]


def test_shelved_whose_record_cant_be_read_is_empty(monkeypatch, capsys):
    from app.connect import setup, status, switch
    monkeypatch.setattr(setup, "_present", lambda module: True)

    def broken(languages=None, **k):
        raise OSError("status record torn")
    monkeypatch.setattr(status, "read", broken)
    assert switch.shelved() == {}
    assert "Connect's shelf wasn't read: status record torn" in capsys.readouterr().out


def _anki_busy_then(monkeypatch, answers):
    """`undo.act` answering in turn (an exception raised), Anki's write lock held by a live program meanwhile."""
    from app.connect import connect_window, undo
    acts = []

    def act(settings, language, job=None, shelf_run=None, confirm=False):
        acts.append((language, shelf_run, confirm))
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setattr(undo, "act", act)
    monkeypatch.setattr(connect_window, "writer_busy", lambda: True)
    monkeypatch.setattr(connect_window, "update_waits", lambda: False)
    monkeypatch.setattr(connect_window, "RETRY_GAP_S", 0.05)
    return acts


def test_put_back_waits_for_anki_through_waiting_then_says_what_went_back(monkeypatch):
    """Another program writing to Anki: `waiting` called once, the act tried again, every card back -> no reasons."""
    from app.cli.contract import CliError
    from app.connect import switch
    _write_settings('{"target_language": "ja", "connect_enabled": true}')
    acts = _anki_busy_then(monkeypatch, [
        CliError("busy", "Another program is writing to Anki. Try again in a moment.", lock="anki-writer",
                 held_by=None), {"back": 3}])
    lines, waits = [], []
    failed = switch.put_back({"ja": (3, ["shelf-2026-10-11-a"])}, log=lines.append,
                             waiting=lambda: waits.append(1))
    assert failed == [] and waits == [1]
    assert acts == [("ja", "shelf-2026-10-11-a", True)] * 2, "as you (confirm), tried again after the wait"
    assert lines == ["3 shelved cards back in your new cards."]


def test_put_back_without_a_waiting_callback_logs_the_waiting_line(monkeypatch):
    from app.cli.contract import CliError
    from app.connect import switch
    _write_settings('{"target_language": "ja", "connect_enabled": true}')
    _anki_busy_then(monkeypatch, [CliError("busy", "Another program is writing to Anki.", lock="anki-writer",
                                           held_by=None), {"back": 1}])
    lines = []
    assert switch.put_back({"ja": (1, ["shelf-2026-10-11-a"])}, log=lines.append) == []
    assert lines == [switch.PUT_BACK_WAITING, "1 shelved card back in your new cards."]


def test_put_back_returns_the_reason_of_each_restore_point_not_put_back(monkeypatch):
    """A skipped act and a failing one each give their reason (the caller asks "turn it off anyway?" with them); the
    next restore point is still tried."""
    from app.connect import connect_window, switch
    _write_settings('{"target_language": "ja", "connect_enabled": true}')
    acts = _anki_busy_then(monkeypatch, [{"skipped": "Anki isn't open"}, RuntimeError("the deck is gone"), {"back": 2}])
    monkeypatch.setattr(connect_window, "writer_busy", lambda: False)
    lines = []
    failed = switch.put_back({"ja": (3, ["run-a", "run-b"]), "zh": (2, ["run-c"])}, log=lines.append,
                             waiting=lambda: lines.append("waiting"))
    assert failed == ["Not done: Anki isn't open.", "Shelved cards weren't put back: the deck is gone"]
    assert lines == failed + ["2 shelved cards back in your new cards."]
    assert [a[1] for a in acts] == ["run-a", "run-b", "run-c"]


# --- the module itself ------------------------------------------------------------------------------------------------

def test_the_words_match_the_tk_windows():
    """2.x's window keeps its own names (a test reads them): they say exactly what the moved module says."""
    from app.connect import switch
    from app.main import MasterDashboardApp
    assert MasterDashboardApp.PUT_BACK_WAITING == switch.PUT_BACK_WAITING
    assert MasterDashboardApp.CONNECT_LANGUAGES == switch.CONNECT_LANGUAGES


def test_importing_the_switch_brings_in_neither_qt_nor_tk():
    """3.0's Qt row and a headless caller both run it: the module and what its import pulls in hold no GUI toolkit."""
    code = ("import sys, app.connect.switch; "
            "bad = [m for m in sys.modules if m.split('.')[0] in ('tkinter', '_tkinter', 'PyQt6', 'PySide6')]; "
            "print(bad); sys.exit(1 if bad else 0)")
    out = subprocess.run([sys.executable, "-c", code], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60,
                         env=dict(os.environ, PYTHONPATH=PROJECT_ROOT))
    assert out.returncode == 0, out.stdout + out.stderr
