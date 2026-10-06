"""The reading verbs write nothing (P0.3 03, 04; P1.2 row 1.2.3): `status`, `list` and `known` open every store
`mode=ro`, `status` never syncs the disk into the library store and never starts its helper, and a schema mismatch is
refused before anything is opened.

What a wrong answer would cost, in order:
  * Connect polls `status`: a poll that wrote (a store synced, an analysed order recorded, a helper started) would
    change the library under the window, many times a minute;
  * a `known` that tokenized on every call would cost seconds where the cache answers in one read;
  * a `list` handed another language's results would offer Chinese words to a Japanese mining run.

Real Japanese files from tests/Test Resources, a real Generate (the analyzer as the command line starts it), under the
test's own root. With and without a library store (STORE_LIVE is on in 2.5).
"""
import json
import os
import sqlite3
import time

import pytest

from app import analyzer, library_store, token_index
from tests import cli_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


def _snapshot():
    """Every file under the root that a verb must not write: everything but the command line's own log, events and
    lock files, and SQLite's side files (the databases themselves are compared)."""
    seen = {}
    for folder, _dirs, files in os.walk(h.root()):
        rel = os.path.relpath(folder, h.root())
        if rel.split(os.sep)[:2] in (["local", "logs"], ["local", "locks"]):
            continue
        for name in files:
            if name.endswith(("-wal", "-shm")):
                continue        # SQLite's side files: a `mode=ro` reader of a WAL database makes them, empty
            path = os.path.join(folder, name)
            st = os.stat(path)
            seen[os.path.relpath(path, h.root())] = (st.st_size, st.st_mtime_ns)
    return seen


@pytest.fixture
def generated(monkeypatch):
    """A Japanese library generated once by `surasura-cli generate` (no Anki: the test switch)."""
    h.seed_library("ja")
    h.write_settings()
    code, lines = h.run_cli("generate")
    assert code == 0 and h.answer(lines)["ran"] is True, lines
    return lines


def _with_store():
    """The library store built from the library's folders, ready (2.5's switch-over): the helper's own build."""
    data_dir = os.path.join(h.root(), "data", "ja")
    user_files = os.path.join(h.root(), "User Files", "ja")
    assert library_store.maintain("ja", data_dir, user_files, from_folders=True) == library_store.EXIT_DONE
    assert library_store.check_mode("ja", data_dir)[0] == "store"
    code, lines = h.run_cli("generate")         # the list as the store gives it
    assert code == 0, lines
    return lines


@pytest.mark.parametrize("store", [False, True], ids=["no store", "a ready store"])
def test_status_writes_nothing_and_says_the_journey_is_current(generated, store):
    ran = _with_store() if store else generated
    before = _snapshot()
    code, lines = h.run_cli("status")
    status = h.answer(lines)
    assert code == 0, lines
    assert status["journey_current"] is True
    assert status["run_signature"] == ran[-1]["run_signature"]
    assert status["last_generate"] and status["known_words"] > 1000
    assert status["junban"] in ("present", "absent") and status["indexer"] == "idle"
    assert status["update_staged"] is False and "reachable" not in status["anki"]
    assert _snapshot() == before, "status changed a file"


def test_status_says_not_current_after_a_known_words_change_and_still_writes_nothing(generated):
    known = os.path.join(h.root(), "User Files", "ja", "KnownWord.json")
    with open(known, "a", encoding="utf-8") as f:
        f.write("\n")                                   # a changed file: a new signature
    before = _snapshot()
    code, lines = h.run_cli("status")
    assert code == 0 and h.answer(lines)["journey_current"] is False
    assert _snapshot() == before


def test_status_cannot_tell_while_the_store_has_a_dropped_file_it_has_not_synced(generated):
    """A file dropped into NOW since the store's last sync: only a sync can tell, and status never syncs: null. The
    window's own check syncs, and then knows."""
    import shutil
    from app import run_args, settings_manager
    _with_store()
    shutil.copy2(os.path.join(h.RESOURCES, "ja", "context_test.txt"),
                 os.path.join(h.root(), "data", "ja", "HighPriority", "dropped_in.txt"))
    before = _snapshot()
    code, lines = h.run_cli("status")
    assert code == 0 and h.answer(lines)["journey_current"] is None
    assert _snapshot() == before, "the dropped file was not synced into the store"
    argv = run_args.analyzer_args(settings_manager.load_settings(), "ja", headless=True)
    assert analyzer.journey_is_current(argv, "ja") is False


@pytest.mark.parametrize("verb", [["status"], ["list"], ["known"]])
@pytest.mark.parametrize("store", [False, True], ids=["no store", "a ready store"])
def test_the_reading_verbs_open_every_store_read_only(generated, monkeypatch, verb, store):
    """In this process, every SQLite open is seen: the token store and the library store only through `mode=ro`."""
    if store:
        _with_store()
    opened = []
    real_connect = sqlite3.connect

    def connect(database, *args, **kwargs):
        opened.append(str(database))
        return real_connect(database, *args, **kwargs)
    monkeypatch.setattr(sqlite3, "connect", connect)
    spawned = []
    monkeypatch.setattr(library_store, "spawn_maintain", lambda *a, **k: spawned.append(a))
    monkeypatch.setattr(library_store, "spawn_build_if_waiting", lambda *a, **k: spawned.append(a))
    code, line = h.call(*verb)
    assert code == 0, line
    stores = [path for path in opened if "token_store_" in path or path.endswith(".db") or ".db?" in path]
    assert stores, "it read a store"
    assert all("mode=ro" in path for path in stores), stores
    assert spawned == [], "the store's helper was started"


def test_a_schema_mismatch_is_refused_before_any_store_is_opened(generated, monkeypatch):
    conn = sqlite3.connect(token_index.store_path_for("ja"))
    conn.execute(f"PRAGMA user_version={token_index.SCHEMA_VERSION + 1}")
    conn.close()
    code, lines = h.run_cli("status")
    assert code == 2 and h.answer(lines)["code"] == "version-skew"


def test_list_gives_the_list_in_its_order_with_each_rows_kind(generated):
    code, lines = h.run_cli("list", "--limit", "5")
    listed = h.answer(lines)
    assert code == 0 and 0 < len(listed["words"]) <= 5
    first = listed["words"][0]
    assert set(first) == {"word", "orth", "reading", "score", "occurrences", "kind"}
    scores = [w["score"] for w in listed["words"]]
    assert scores == sorted(scores, reverse=True), "the list's own order: leverage"
    kinds = {w["word"]: w["kind"] for w in h.answer(h.run_cli("list")[1])["words"]}
    assert set(kinds.values()) <= {"word", "compound", "one_kanji", "phrase"}
    assert "phrase" in kinds.values(), "the sample's set phrases are phrase rows (手っ取り早い, 眉根を寄せる)"


def test_list_for_one_file_gives_its_new_words_in_its_own_order(generated):
    code, lines = h.run_cli("list", "--file", "runaway_transcript.txt")
    listed = h.answer(lines)
    assert code == 0 and listed["file"] == "runaway_transcript.txt"
    assert [w["file_order"] for w in listed["words"]] == list(range(1, len(listed["words"]) + 1))
    code, lines = h.run_cli("list", "--file", "no_such_file.txt")
    assert code == 0 and h.answer(lines)["words"] == []


def test_list_of_another_language_than_results_hold_is_empty_and_says_why(generated):
    os.makedirs(os.path.join(h.root(), "User Files", "zh"), exist_ok=True)
    code, lines = h.run_cli("list", "--lang", "zh")
    assert code == 0 and h.answer(lines)["words"] == [] and h.answer(lines)["skipped"] == "results hold ja"


def test_list_waits_for_a_generate_writing_the_results_or_says_busy(generated):
    from tests.test_cli_locks import Holder
    with Holder("results", "Generate") as other:
        code, lines = h.run_cli("list")
        assert code == 3 and h.answer(lines)["code"] == "busy" and h.answer(lines)["held_by"]["verb"] == "Generate"
        import threading
        threading.Timer(0.5, other.release).start()
        code, lines = h.run_cli("list", "--wait", "10")
        assert code == 0 and h.answer(lines)["words"]


def test_known_reads_the_cache_and_names_each_word_by_its_lemma(generated):
    code, lines = h.run_cli("known")
    known = h.answer(lines)
    assert code == 0 and known["source"] == "cache" and known["count"] == len(known["words"]) > 1000
    assert {"word", "reading", "orth"} == set(known["words"][0])


def test_known_reads_the_file_itself_when_the_cache_is_behind(generated):
    path = os.path.join(h.root(), "User Files", "ja", "KnownWord.json")
    os.utime(path, (time.time() + 5, time.time() + 5))       # changed since the cache: it no longer matches
    code, lines = h.run_cli("known")
    assert code == 0 and h.answer(lines)["source"] == "computed" and h.answer(lines)["count"] > 1000


def test_known_with_an_unreadable_file_is_bad_data_and_leaves_it_untouched(generated):
    path = os.path.join(h.root(), "User Files", "ja", "KnownWord.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"words": [{"dictForm": "冒険"')                # cut short
    before = open(path, "rb").read()
    code, lines = h.run_cli("known")
    assert code == 1 and h.answer(lines)["code"] == "bad-data"
    assert open(path, "rb").read() == before


def test_unreadable_settings_are_bad_data_never_the_defaults(generated):
    with open(os.path.join(h.root(), "settings.json"), "w", encoding="utf-8") as f:
        f.write('{"target_language": "ja",')
    for verb in ("status", "list", "known", "generate", "known-sync"):
        code, lines = h.run_cli(verb)
        assert code == 1 and h.answer(lines)["code"] == "bad-data", (verb, lines)


def test_a_language_never_set_up_is_not_set_up(generated):
    code, lines = h.run_cli("status", "--lang", "zh")
    assert code == 2 and h.answer(lines)["code"] == "not-set-up"


# --------------------------------------------------------------------------- #
# The cost model (05 §3): status on a Sonic-sized library, timed
# --------------------------------------------------------------------------- #
def test_status_on_a_774_file_library_is_quick(monkeypatch):
    """Recorded in the step note: status (no Anki probe) and status --anki with Anki closed, on 774 files."""
    folder = h.seed_library("ja", templates=False)
    text = open(os.path.join(h.RESOURCES, "ja", "context_test.txt"), encoding="utf-8").read()
    for n in range(774 - len(h.LIBRARY["ja"])):
        with open(os.path.join(folder, f"episode_{n:03d}.txt"), "w", encoding="utf-8") as f:
            f.write(text[: 200 + n % 300])
    h.write_settings()
    timings = {}
    for label, args in (("status", ("status",)), ("status --anki", ("status", "--anki"))):
        started = time.perf_counter()
        code, lines = h.run_cli(*args)
        timings[label] = round(time.perf_counter() - started, 3)
        assert code == 0, lines
    print(f"\nTIMING status on 774 files: {json.dumps(timings)}")
    assert timings["status"] < 5.0
