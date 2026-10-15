"""The Anki window's rules (`app/anki_window.py`, W3.4 row 3): what the Tk `AnkiSyncGui` decided inside its class, moved
beside the engine so the Qt window only paints the answers. Each test names the Tk method it replaces.

What a wrong answer would cost: the sync reading the wrong field (a sentence field marking every word of it known); a
deck pick saved by merely opening the window (S16) or written over another language's; a plain "Anki isn't running"
hiding a permission prompt the user must accept; a Replace or Restore writing numbers the user never saw; a window job
the automatic sync doesn't see (two appends to KnownWord.json at once), or one started while an update waits; a result
the automatic Generate never hears.

Anki is the suite's fake collection behind a patched `urllib.request.urlopen` (loopback, never live Anki); the words are
real Japanese and Chinese from `tests/Test Resources/`.
"""
import json
import os
import threading
from datetime import datetime
from unittest import mock

import pytest

from app import anki_sync
from app import anki_window as AW
from app.path_utils import get_user_files_path
from app.services.jobs import JobRegistry
from tests import services_helpers as h
from tests.test_anki_sync import URL, FakeCollection, _ok


class FakeAnki(FakeCollection):
    """The suite's fake collection, answering what the window asks first too: the probe and the deck list."""

    def __init__(self, notes=(), offline=False, decks=None, permission="granted", fail_after_probe=False):
        super().__init__(notes, offline=offline)
        self.extra_decks = list(decks or [])
        self.permission = permission
        self.fail_after_probe = fail_after_probe

    def _answer(self, payload):
        action = payload["action"]
        if action == "requestPermission":
            return _ok({"permission": self.permission, "version": 6})
        if self.fail_after_probe:
            return {"result": None, "error": "collection is not available"}
        if action == "deckNames":
            return _ok(sorted({n["deck"] for n in self.notes} | set(self.extra_decks)))
        return super()._answer(payload)


@pytest.fixture
def ja_words(ja_resources_dir):
    with open(os.path.join(ja_resources_dir, "context_test.txt"), encoding="utf-8") as f:
        text = f.read()
    words = ["冒険", "準備", "危険", "価値", "冒険家", "有名", "素晴らしい", "求める"]
    assert all(w[:2] in text for w in words)
    return words


def _known(language="ja"):
    return os.path.join(get_user_files_path(language), "KnownWord.json")


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _bytes(path):
    with open(path, "rb") as f:
        return f.read()


# --- what is synced (the Tk `_fields`, `_save`, `_probe_worker`'s pick, `_render_fields`, `_sync_controls`) -------- #
def test_fields_auto_is_each_note_types_first_field_and_a_second_needs_a_named_first():
    assert AW.fields(None, None) == [] and AW.fields("", "Sentence") == [], "Auto: never a second field"
    assert AW.fields("Expression") == ["Expression"]
    assert AW.fields("Expression", "Sentence") == ["Expression", "Sentence"]
    assert AW.fields("Expression", "Expression") == ["Expression"], "the same field twice is read once"


def test_saved_reads_this_languages_choices_alone():
    settings = {"anki_sync_decks": {"ja": ["TheBank"], "zh": ["中文"]},
                "anki_sync_fields": {"ja": ["Expression", "Sentence", "Meaning"]},
                "anki_sync_include_suspended": True}
    assert AW.saved(settings, "ja") == (["TheBank"], ["Expression", "Sentence"], True)
    assert AW.saved(settings, "zh") == (["中文"], [], True)
    assert AW.saved({}, "ja") == ([], [], False)


def test_merge_writes_one_languages_decks_and_fields_and_keeps_the_others():
    """The per-language merge onto the file as it is: the other language's pick and a key saved meanwhile survive."""
    decks, chosen = ["TheBank"], ["Expression"]
    update = AW.merge("ja", decks, chosen)
    file_now = {"anki_sync_decks": {"zh": ["中文"], "ja": ["Old"]}, "anki_sync_fields": {"zh": ["汉字"]},
                "theme": "night"}
    update(file_now)
    assert file_now == {"anki_sync_decks": {"zh": ["中文"], "ja": ["TheBank"]},
                        "anki_sync_fields": {"zh": ["汉字"], "ja": ["Expression"]}, "theme": "night"}
    decks.append("Later")                                       # the caller's list is never the file's
    file_now["anki_sync_decks"]["ja"].append("x")
    fresh = {}
    update(fresh)
    assert fresh == {"anki_sync_decks": {"ja": ["TheBank"]}, "anki_sync_fields": {"ja": ["Expression"]}}


def test_the_first_open_picks_every_studied_deck_largest_first():
    assert AW.preselect({"Kana": 0, "TheBank": 120, "Accelerator": 511}) == ["Accelerator", "TheBank"]
    assert AW.preselect({}) == [] and AW.preselect(None) == []


def test_field_choices_keep_a_saved_name_and_never_offer_the_word_field_twice():
    models = {"Lapis": ["Expression", "Sentence"], "Migaku Japanese": ["Target Word", "Sentence"]}
    assert AW.field_names(models) == ["Expression", "Sentence", "Target Word"]
    assert AW.field_choices(models, None) == (["Expression", "Sentence", "Target Word"],
                                              ["Expression", "Sentence", "Target Word"])
    firsts, seconds = AW.field_choices(models, "Word")
    assert firsts[-1] == "Word" and "Word" not in seconds
    assert "Expression" not in AW.field_choices(models, "Expression")[1]


def test_field_lines_resolve_auto_to_the_first_field_and_name_the_note_types_skipped():
    models = {"Migaku Japanese": ["Target Word", "Sentence"], "Lapis": ["Expression", "Sentence"]}
    assert AW.field_lines(models, []) == ([("Lapis", ["Expression"]), ("Migaku Japanese", ["Target Word"])], [])
    assert AW.field_lines(models, ["Expression"]) == ([("Lapis", ["Expression"])], ["Migaku Japanese"])
    assert AW.field_lines({}, []) == ([], [])


@pytest.mark.parametrize("connected, busy, decks, chosen, live", [
    (True, False, ["TheBank"], ["Expression"], {"sync", "replace", "add", "field1", "field2", "recheck", "remove",
                                                "suspended", "restore"}),
    (True, False, [], [], {"add", "field1", "recheck", "remove", "suspended", "restore"}),
    (False, False, ["TheBank"], ["Expression"], {"recheck", "remove", "suspended", "restore"}),
    (True, True, ["TheBank"], ["Expression"], set()),
])
def test_controls_follow_anki_the_decks_and_the_job(connected, busy, decks, chosen, live):
    """The Tk `_sync_controls`, and its defect 4 fixed: nothing changes the scope while a job runs."""
    on = AW.controls(connected, busy, decks, chosen)
    assert {k for k, v in on.items() if v} == live


# --- what Anki said (the Tk `_set_connection`, `_probe_worker`, `_scope_worker`) -------------------------------------- #
def test_connection_is_short_when_up_plain_when_closed_and_as_written_when_actionable():
    assert AW.connection({"ok": True, "version": 6}) == ("connected", 6)
    assert AW.connection({"ok": False, "error": "Anki isn't reachable at http://127.0.0.1:8765"})[0] == "closed"
    for error in ("Anki did not grant access (it may be showing a permission prompt — accept it and try again).",
                  "This AnkiConnect is missing deckNames — update the add-on to use this feature.",
                  "Anki stopped answering: collection is not available"):
        assert AW.connection({"ok": False, "error": error}) == ("problem", error)


def test_the_probe_picks_studied_decks_only_when_none_is_chosen(ja_words):
    fake = FakeAnki([{"word": w, "deck": "TheBank"} for w in ja_words[:3]]
                    + [{"word": ja_words[3], "deck": "Kana", "new": True}], decks=["Grammar"])
    with mock.patch("urllib.request.urlopen", fake):
        first = AW.read_probe(URL, [], False)
        again = AW.read_probe(URL, ["Grammar"], False)
    assert first.report["ok"] and first.decks == ["Grammar", "Kana", "TheBank"]
    assert first.preselected == ["TheBank"], "a deck with only new cards is never picked"
    assert first.counts == {"TheBank": 3} and first.models == {"Lapis": ["Expression", "Sentence", "Meaning"]}
    assert again.preselected is None and again.counts == {"Grammar": 0}
    assert not any(r["action"].startswith(("add", "update", "delete", "change")) for r in fake.requests), \
        "the window's reads never write Anki"


def test_the_probe_offline_or_anki_gone_mid_read_is_a_report_never_a_raise(ja_words):
    with mock.patch("urllib.request.urlopen", FakeAnki(offline=True)):
        offline = AW.read_probe(URL, [], False)
    assert not offline.report["ok"] and offline.preselected is None and offline.decks == []
    with mock.patch("urllib.request.urlopen", FakeAnki([{"word": ja_words[0]}], fail_after_probe=True)):
        gone = AW.read_probe(URL, ["TheBank"], False)
    assert AW.connection(gone.report)[0] == "problem" and "stopped answering" in gone.report["error"]


def test_known_view_counts_real_known_words_and_the_backlog(ja_resources_dir):
    with open(os.path.join(ja_resources_dir, "KnownWord.json"), encoding="utf-8") as f:
        data = json.load(f)
    _write(_known(), data)
    view = AW.known_view("ja")
    assert view.total == anki_sync.count_known("ja") > 0
    assert (view.last_sync, view.last_added, view.backup, view.backlog) == (None, 0, None, 0)


def test_ago_says_minutes_hours_and_days():
    now = datetime(2026, 10, 14, 12, 0, 0)
    assert AW.ago("2026-10-14T11:59:30", now) == ("now", 0)
    assert AW.ago("2026-10-14T11:56:00", now) == ("min", 4)
    assert AW.ago("2026-10-14T09:00:00", now) == ("h", 3)
    assert AW.ago("2026-10-12T12:00:00", now) == ("days", 2)
    assert AW.ago(None, now) is None and AW.ago("not a time", now) is None


def test_result_view_names_each_outcome():
    S = anki_sync.SyncResult
    assert AW.result_view(S(error="Choose at least one deck first.")) == ("error",
                                                                          {"text": "Choose at least one deck first."})
    assert AW.result_view(S(mode="dry-run", changed=True))[0] == "changed"
    assert AW.result_view(S(mode="delta", added=3, scanned=40)) == ("synced", {"added": 3, "scanned": 40,
                                                                               "full": False})
    assert AW.result_view(S(mode="replace", added=3, total_known=8, kept_graduated=5, kept_ignored=2)) == \
        ("replaced", {"total": 8, "added": 3, "graduated": 5, "ignored": 2})
    assert AW.result_view(S(mode="restore", total_known=40)) == ("restored", {"total": 40})


def test_restore_point_names_the_backup_its_time_and_both_totals(ja_words):
    """The Tk link said "from before the last Replace" even after a Restore (its defect 7): the point names what it
    puts back — the backup made at that time — with the totals now and then."""
    assert AW.restore_point("ja") is None
    _write(_known(), {"words": [{"dictForm": w, "knownStatus": "KNOWN"} for w in ja_words[:5]]})
    with mock.patch("urllib.request.urlopen", FakeAnki([{"word": w} for w in ja_words[:2]])):
        replaced = anki_sync.replace("ja", URL, ["TheBank"], [])
    point = AW.restore_point("ja")
    assert point.name == replaced.backup and point.now == 2 and point.then == 5
    assert point.when == AW.backup_time(replaced.backup) and point.when.year >= 2026
    os.remove(os.path.join(get_user_files_path("ja"), ".trash", replaced.backup))
    assert AW.restore_point("ja") is None, "a backup gone from the trash folder can't be offered"
    assert AW.backup_time("KnownWord.20261014-210305-2.json") == datetime(2026, 10, 14, 21, 3, 5)
    assert AW.backup_time("notes.txt") is None


# --- the jobs ----------------------------------------------------------------------------------------------------- #
class _Automation:
    def __init__(self):
        self.heard = []

    def anki_synced(self, result, language):
        self.heard.append((result.mode, language))


def _wait(event):
    assert event.wait(10), "the job ended"


def test_a_window_sync_is_an_anki_sync_job_and_its_result_reaches_the_automation_service(ja_words):
    registry, automation, ended = JobRegistry(), _Automation(), []
    done = threading.Event()
    fake = FakeAnki([{"word": w} for w in ja_words[:3]])
    with mock.patch("urllib.request.urlopen", fake):
        job = AW.submit(registry, "Syncing", lambda: AW.run_sync("ja", URL, ["TheBank"], [], False),
                        lambda r: (ended.append(r), done.set()), automation, "ja")
        _wait(done)
    assert job.kind == AW.KIND == "anki-sync" and job.on_quit == "detach"
    assert ended[0].added == 3 and automation.heard == [("full", "ja")], "a first sync reads every card"
    assert h.until(lambda: not registry.live("anki-sync"))
    assert [v.state for v in registry.snapshot()] == ["done"]


def test_a_dry_run_and_a_write_that_stopped_tell_the_automation_service_nothing(ja_words):
    registry, automation = JobRegistry(), _Automation()
    for result in (anki_sync.SyncResult(mode="dry-run", added=3), anki_sync.SyncResult(mode="dry-run", changed=True),
                   anki_sync.SyncResult(mode="restore", changed=True)):
        done = threading.Event()
        AW.submit(registry, "x", lambda r=result: r, lambda _r: done.set(), automation, "ja")
        _wait(done)
    assert automation.heard == []
    assert AW.tells(anki_sync.SyncResult(mode="restore")) and not AW.tells(None)


def test_nothing_is_submitted_while_an_update_holds_the_children(monkeypatch):
    from app import updater
    monkeypatch.setattr(updater, "children_held", lambda: True)
    registry, ran = JobRegistry(), []
    assert AW.submit(registry, "Syncing", lambda: ran.append(1), lambda _r: None) is None
    assert registry.snapshot() == () and ran == []


def test_a_job_that_raises_ends_with_its_error_never_stuck():
    registry, ended = JobRegistry(), []
    done = threading.Event()

    def boom():
        raise RuntimeError("the state file is held")
    AW.submit(registry, "Syncing", boom, lambda r: (ended.append(r), done.set()))
    _wait(done)
    assert "the state file is held" in ended[0].error
    assert h.until(lambda: registry.snapshot()[0].state == "failed")


def test_a_window_job_waits_behind_a_running_sync_and_the_automatic_sync_never_starts_beside_one():
    """One known-words writer: the window's job asked while a sync runs waits its turn (the registry's table); the
    automatic sync asked while the window's runs says "running" and starts nothing (`AutoSync.maybe`)."""
    registry = JobRegistry()
    gate, order = threading.Event(), []
    first_done, second_done = threading.Event(), threading.Event()

    def held():
        gate.wait(10)
        order.append("first")
        return anki_sync.SyncResult()
    AW.submit(registry, "Syncing", held, lambda _r: first_done.set())
    AW.submit(registry, "Replacing", lambda: order.append("second") or anki_sync.SyncResult(),
              lambda _r: second_done.set())
    assert h.until(lambda: [v.state for v in registry.snapshot()] == ["running", "waiting"])

    from app.services import automation as A
    owner = type("Owner", (), {})()
    owner.settings_now = lambda: {"anki_sync_auto": True, "anki_sync_decks": {"ja": ["TheBank"]}}
    owner.clock, owner.language, owner.registry = (lambda: 1e9), "ja", registry
    owner.update_staged = lambda: False
    anki_sync._save_state("ja", {"last_sync": "2026-10-01T10:00:00"})
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SURASURA_NO_ANKI_SYNC", None)
        assert A.AutoSync(owner).maybe(force=True) == "running"
    gate.set()
    _wait(first_done)
    _wait(second_done)
    assert order == ["first", "second"]


def test_a_write_may_be_waited_for_at_quit_and_every_other_job_is_detached():
    """AD3-1: Replace and Restore write two files (the list, then the state naming its backup) and ask `wait`; a sync
    or a dry run stays `detach` (it only appends or reads)."""
    registry = JobRegistry()
    done = threading.Event()
    job = AW.submit(registry, "Replacing", lambda: anki_sync.SyncResult(mode="replace"), lambda _r: done.set(),
                    on_quit="wait")
    _wait(done)
    assert job.on_quit == "wait"
    done.clear()
    assert AW.submit(registry, "Syncing", lambda: anki_sync.SyncResult(), lambda _r: done.set()).on_quit == "detach"
    _wait(done)


def test_the_automation_service_is_found_when_the_job_ends_not_when_it_was_asked(ja_words):
    """AD3-9: the duties (and their automation service) are made on a worker after the window opens: a job asked
    before they exist still tells them its result."""
    registry, automation, holder = JobRegistry(), _Automation(), {}
    gate, done = threading.Event(), threading.Event()

    def work():
        gate.wait(10)
        return anki_sync.SyncResult(mode="delta", added=2)
    AW.submit(registry, "Syncing", work, lambda _r: done.set(), lambda: holder.get("automation"), "ja")
    holder["automation"] = automation                      # made meanwhile
    gate.set()
    _wait(done)
    assert automation.heard == [("delta", "ja")]


# --- the Chinese side ------------------------------------------------------------------------------------------------ #
def test_a_chinese_sync_reads_its_own_decks_and_writes_only_chinese_known_words(zh_resources_dir):
    with open(os.path.join(zh_resources_dir, "context_test.txt"), encoding="utf-8") as f:
        text = f.read()
    words = [w for w in ("冒险", "危险", "挑战", "勇敢") if w in text][:3]
    assert len(words) == 3, "real Chinese words from the shared resources"
    fake = FakeAnki([{"word": w, "deck": "中文", "model": "Chinese"} for w in words])
    registry, done, ended = JobRegistry(), threading.Event(), []
    with mock.patch("urllib.request.urlopen", fake):
        AW.submit(registry, "Syncing", lambda: AW.run_sync("zh", URL, ["中文"], [], False),
                  lambda r: (ended.append(r), done.set()), None, "zh")
        _wait(done)
    assert ended[0].added == 3 and not os.path.exists(_known("ja"))
    with open(_known("zh"), encoding="utf-8") as f:
        assert [w["dictForm"] for w in json.load(f)["words"]] == words
