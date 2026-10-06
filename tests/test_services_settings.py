"""The settings service (`app/services/settings.py`) and where each setting belongs (`app/settings_placement.py`) —
W1.3, the window's spec 04 §4.2.

What a wrong answer would cost:
  * a change lost — the user flips two switches a moment apart and only one is saved, because the writer keeps only its
    newest build;
  * someone else's setting reverted or dropped — the window writing settings.json whole put back retired keys (a full
    Generate per click) and wrote over what the Anki window or a module had saved meanwhile (CLAUDE.md §6);
  * a frozen window — a save that waits on the `settings` lock on the window's thread while another program writes;
  * a stale journey nobody notices — a change that moves the run signature reported as "neither".

Real settings files under the test's own root (SURASURA_TEST_ROOT); another program is a real child process.
"""
import os
import threading
import time

import pytest

from app import settings_manager, settings_placement
from app.services import settings as service_module
from app.services.settings import SettingsService
from tests import services_helpers as h


# --- where each setting belongs (row 1) ------------------------------------------------------------------------- #
@pytest.mark.parametrize("key,language,expected", [
    ("theme", "ja", "report"),                       # the report's own look
    ("strategy", "zh", "analysis"),
    ("logic.names_kanji", "ja", "analysis"),          # analysis:ja — a Japanese run reads it…
    ("logic.names_kanji", "zh", "neither"),           # …a Chinese one never does
    ("zh_script", "zh", "analysis"),
    ("zh_script", "ja", "neither"),
    ("telemetry_enabled", "ja", "neither"),
    ("logic.selection.bands_ppm.very_rare", "ja", "analysis"),   # under a placed key: the placed key's
    ("logic.context._comment", "ja", "neither"),
    ("a_key_nobody_placed", "ja", "analysis"),        # as compute_run_signature counts it: a needless run at worst
])
def test_kind_answers_per_language_from_placed(key, language, expected):
    assert settings_placement.kind(key, language) == expected
    assert SettingsService.kind(key, language) == expected


def test_every_placed_value_is_one_of_the_four_places():
    allowed = {"analysis", "analysis:ja", "analysis:zh", "report", "neither"}
    assert set(settings_placement.PLACED.values()) <= allowed
    assert settings_placement.PLACED["index_pool_workers"] == "neither"


def test_stales_says_whether_a_change_makes_the_journey_stale():
    service = SettingsService()
    assert service.stales(["theme"], "ja") is True                    # a re-render
    assert service.stales(["telemetry_enabled", "open_count"], "ja") is False
    assert service.stales(["logic.ignore_names"], "zh") is False


# --- the settings service (row 2) ------------------------------------------------------------------------------- #
def test_get_is_the_loaded_settings_frozen():
    """Defaults filled in as load_settings reads them; nobody can change the copy a window holds."""
    h.write_settings({"target_language": "zh", "theme": "Zen Mode"})
    service = SettingsService()
    got = service.get()
    assert got["target_language"] == "zh" and got["theme"] == "Zen Mode"
    assert got["logic"]["selection"]["band"] == settings_manager.load_settings()["logic"]["selection"]["band"]
    with pytest.raises(TypeError):
        got["theme"] = "x"
    with pytest.raises(TypeError):
        got["logic"]["selection"]["band"] = "x"


def test_get_after_the_load_is_a_copy_in_memory_within_4_ms():
    """The file is read when the service is made (before a window's first paint, or on a worker); after that `get()` is
    safe on a window's thread, even right after a change (it lays the pending change over its copy)."""
    h.write_settings({"target_language": "ja"})
    service = SettingsService(delay=5.0)
    _, ms = h.timed(service.get)
    service.set({"theme": "Zen Mode"})
    got, ms_after_set = h.timed(service.get)
    assert ms <= 4 and ms_after_set <= 4, (ms, ms_after_set)
    assert got["theme"] == "Zen Mode"
    assert service.flush(10)


def test_two_changes_a_tenth_of_a_second_apart_both_land():
    """The writer keeps only its newest build; the service's build carries every pending change, so the first is never
    lost to the second."""
    h.write_settings({"target_language": "ja"})
    service = SettingsService(delay=0.05)
    service.set({"theme": "Zen Mode"})
    time.sleep(0.1)
    service.set({"logic.selection.band": "rare"})
    assert service.flush(10)
    on_disk = h.read_settings()
    assert on_disk["theme"] == "Zen Mode" and on_disk["logic"]["selection"]["band"] == "rare"
    assert service.pending() == []


def test_a_change_held_while_another_is_written_is_never_lost():
    """A change made while a write is in flight (between its build and its landing) stays pending and lands next."""
    h.write_settings({"target_language": "ja"})
    service = SettingsService(delay=0.0)
    gate = threading.Event()
    real_build = service._build

    def slow_build():
        out = real_build()
        gate.wait(5)                     # the write is in flight: its keys are fixed
        return out
    service._build = slow_build
    service.set({"theme": "Dark Flow"})
    time.sleep(0.1)
    service.set({"theme": "Zen Mode", "zen_limit": 77})
    gate.set()
    assert service.flush(10)
    assert h.read_settings()["theme"] == "Zen Mode" and h.read_settings()["zen_limit"] == 77


def test_only_the_keys_given_are_written_and_everything_else_stays_as_the_file_holds_it():
    """No default, retired key or another window's key is written or reverted: the file compared key by key."""
    before = {"target_language": "ja", "reinforce_segmentation": True, "junban_deck": "日本語::Mining",
              "logic": {"weights": {"high": 7}}, "a_hand_edited_key": [1, 2]}
    h.write_settings(before)
    service = SettingsService(delay=0.0)
    service.set({"logic.selection.band": "rare", "zen_limit": 12})
    assert service.flush(10)
    after = h.read_settings()
    expected = dict(before, zen_limit=12, logic={"weights": {"high": 7}, "selection": {"band": "rare"}})
    assert after == expected


def test_a_key_another_program_saves_between_two_changes_survives():
    """The build reads the file as it is when written (inside the lock), so the Anki window's save in between stays."""
    h.write_settings({"target_language": "ja"})
    service = SettingsService(delay=0.0)
    service.set({"theme": "Zen Mode"})
    assert service.flush(10)
    settings_manager.save_keys({"anki_sync_decks": {"ja": ["日本語::Mining"]}})
    service.set({"zen_limit": 20})
    assert service.flush(10)
    after = h.read_settings()
    assert after["anki_sync_decks"] == {"ja": ["日本語::Mining"]} and after["zen_limit"] == 20


def test_get_shows_a_change_at_once_before_it_is_written():
    h.write_settings({"target_language": "ja"})
    service = SettingsService(delay=5.0)               # nothing written for 5 s
    service.set({"logic.context.max_contexts": 5})
    assert service.get()["logic"]["context"]["max_contexts"] == 5
    assert "max_contexts" not in h.read_settings().get("logic", {}).get("context", {})
    assert service.flush(10)


def test_set_returns_within_4_ms_while_another_program_holds_the_settings_lock():
    """Safe on a window's thread: the lock is waited for on the writer's worker; the write lands once it is free."""
    h.write_settings({"target_language": "ja"})
    service = SettingsService(delay=0.0)
    service.get()
    with h.Holder("settings"):
        _, ms = h.timed(lambda: service.set({"theme": "Zen Mode"}))
        _, get_ms = h.timed(service.get)
        assert ms <= 4 and get_ms <= 4, (ms, get_ms)
        time.sleep(0.3)
        assert h.read_settings().get("theme") is None          # held: not written yet
    assert service.flush(15)
    assert h.read_settings()["theme"] == "Zen Mode"


def test_subscribers_hear_each_landed_write_with_its_keys_and_a_failing_one_is_harmless():
    h.write_settings({"target_language": "ja"})
    service = SettingsService(delay=0.0)
    heard = []

    def broken(_keys):
        raise RuntimeError("a listener's own fault")
    service.subscribe(broken)
    service.subscribe(heard.append)
    service.set({"theme": "Zen Mode", "logic.phrase_rows": False})
    assert service.flush(10)
    assert h.until(lambda: heard) == [["logic.phrase_rows", "theme"]]
    service.set({"zen_limit": 9})
    assert service.flush(10)
    assert h.until(lambda: len(heard) == 2) and heard[1] == ["zen_limit"]


def test_an_update_runs_on_the_file_as_it_is():
    """The Anki address: a hand-edited 2.x `junban_url` becomes the one address every Anki caller reads."""
    h.write_settings({"target_language": "ja", "junban_url": "http://127.0.0.1:8766"})

    def address(settings):
        from app import anki_connect
        settings["anki_connect_url"] = anki_connect.address(settings)
        settings.pop("junban_url", None)
    service = SettingsService(delay=0.0)
    service.set({}, update=address)
    assert service.flush(10)
    after = h.read_settings()
    assert after["anki_connect_url"] == "http://127.0.0.1:8766" and "junban_url" not in after


@pytest.mark.parametrize("bad", ["", "theme.colour", 3, "selection.band"])
def test_a_key_that_is_neither_a_name_nor_a_logic_path_is_refused(bad):
    with pytest.raises(ValueError):
        SettingsService().set({bad: 1})


def test_thaw_gives_back_a_plain_dict():
    frozen = service_module.freeze({"logic": {"x": [1, {"y": 2}]}})
    assert service_module.thaw(frozen) == {"logic": {"x": [1, {"y": 2}]}}


# --- the review's cases (tracks/window/reviews/W1.3-adversary.md #1, #2) ----------------------------------------- #
def test_a_first_save_writes_only_the_keys_given_never_every_default():
    """No settings.json yet (a fresh install): the save writes the one key, never every default and every module's
    (Speech's hidden koe_* keys, the hand-only junban_auto_reorder)."""
    path = h.settings_path()
    if os.path.exists(path):
        os.remove(path)
    service = SettingsService(delay=0.0, load=False)
    service.set({"theme": "Zen Mode"})
    assert service.flush(10)
    assert h.read_settings() == {"theme": "Zen Mode"}


def test_an_unreadable_file_is_kept_beside_before_the_save_starts_it_again():
    with open(h.settings_path(), "w", encoding="utf-8") as f:
        f.write('{"theme": "Zen Mode", broken')
    service = SettingsService(delay=0.0, load=False)
    service.set({"zen_limit": 30})
    assert service.flush(10)
    assert h.read_settings() == {"zen_limit": 30}
    with open(h.settings_path() + ".unreadable", encoding="utf-8") as f:
        assert f.read() == '{"theme": "Zen Mode", broken'


def test_after_flush_get_shows_the_written_value_never_the_old_one():
    """`flush` returns only once the write is read back: a get() right after never sees the value from before."""
    h.write_settings({"target_language": "ja", "theme": "Old"})
    service = SettingsService(delay=0.0)
    gate = threading.Event()
    real_load = settings_manager.load_settings

    def slow_load(*a, **k):
        if threading.current_thread().name == "settings-writer":
            gate.wait(2)                 # the read-back after the write, held a moment
        return real_load(*a, **k)
    settings_manager.load_settings = slow_load
    heard = []
    service.subscribe(heard.append)
    try:
        service.set({"theme": "New"})
        threading.Timer(0.3, gate.set).start()
        assert service.flush(10)
        assert heard == [["theme"]], "flush returns once the write is read back and its listeners heard it"
        assert service.get()["theme"] == "New" and service.pending() == []
    finally:
        settings_manager.load_settings = real_load


def test_a_save_now_holds_the_settings_lock_for_its_read_and_write():
    """`now=True` (a test harness, a headless tool) reads and writes inside the lock, as the writer does."""
    h.write_settings({"target_language": "ja"})
    service = SettingsService(load=False)
    from app import locks
    seen = []
    real_save = settings_manager.save_settings

    def save(settings, **k):
        seen.append(locks.held_here("settings"))
        return real_save(settings, **k)
    settings_manager.save_settings = save
    try:
        service.set({"theme": "Zen Mode"}, now=True)
    finally:
        settings_manager.save_settings = real_save
    assert seen == [True] and h.read_settings()["theme"] == "Zen Mode"
