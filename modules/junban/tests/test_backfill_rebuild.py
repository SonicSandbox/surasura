# SPDX-License-Identifier: GPL-3.0-or-later
"""The library's パターン set, built again as the library grows — in the background (`backfill.py`).

The user (2026-10-01): "As my library grows and adjusts, is there a way to do it in Surasura … it wouldn't be done
often", then "I would just want this to not get in the way … in the background … so it doesn't hold the generate or
anything hostage." What this file holds, most costly first:

  * **Nothing waits for it.** The build starts and the call returns; Preview and Fill read the set in use until the
    new one goes in — written beside it, put in when nothing holds the old one (Windows will not replace an open
    database); the process runs at low priority, so a Generate started meanwhile goes first.
  * **Never two builds at once**, whoever asks — the window, its button, the automatic step.
  * **A failed build keeps the set in use and says so once**, and the automatic one does not try again that session.
  * **The growth check**: what the build recorded it read, against what the token store holds now — never a first
    build, never for a missing or an older builder's set, never for a set that recorded nothing.

Real Japanese text in a sandboxed library and token store; the build process is a stand-in that writes a real set.
"""
import os
import subprocess
import threading
import time
from unittest import mock

import pytest

from app import token_index
from app.path_utils import get_data_path
from modules.junban import backfill, patterns_build
from modules.junban.patterns_build import BUILDER_VERSION, default_db_path, write_rows


@pytest.fixture(autouse=True)
def _no_build_left_running():
    """The module keeps one build, its progress and its failures for the app's session: each test starts clean."""
    backfill._PROCESS = None
    backfill._BACKGROUND.clear()
    backfill._FAILED.clear()
    yield
    backfill._PROCESS = None
    backfill._BACKGROUND.clear()
    backfill._FAILED.clear()


# --- a sandboxed library: its set, its token store ------------------------------------------------- #
def _set(language="ja", count=40, built_at="2026-09-30T21:14:05", path=None, **meta):
    """A library set as the builder writes it: one word (冒険, `count` uses) and the meta a build records."""
    from modules.junban import patterns_zh
    version = patterns_zh.BUILDER_VERSION if language == "zh" else BUILDER_VERSION
    row = ("冒险", "", "冒险", "n", count) if language == "zh" else ("冒険", "ボウケン", "冒険", "名詞", count)
    stored = {"corpus": "library", "corpus_kind": "library", "files": 2, "duplicates": 0, "tokens": 1000,
              "floor": 12, "language": language, "built_at": built_at, "builder_version": version}
    stored.update(meta)
    path = path or default_db_path(language)
    tmp = path + ".tmp"
    write_rows(tmp, [row], [], [], stored)
    os.replace(tmp, path)
    return path


def _store(totals, language="ja"):
    """The token store as an index leaves it: one row per file, `total` its words (the columns the counts use)."""
    store = token_index.open_store(language)
    try:
        store.conn.executemany("INSERT INTO files(path, mtime, size, total) VALUES (?,?,?,?)",
                               [(f"c:/library/episode{n:04d}.srt", 1.0, 100, total) for n, total in enumerate(totals)])
        store.conn.commit()
    finally:
        store.close()


def _count(language="ja"):
    """How many uses the set in use gives 冒険 — read the way a preview reads it."""
    from modules.junban.patterns_store import open_store
    store = open_store(language=language)
    try:
        key = ("冒险", "") if language == "zh" else ("冒険", "ボウケン")
        return store.word(*key)[2]
    finally:
        store.close()


class _Build:
    """The build process as `subprocess.Popen` hands it over: progress lines, then — once the test lets it end
    (`end`) — a new set written where its command line says (`--db`, else over the set in use, as the builder does)
    and its exit code."""

    def __init__(self, argv, code=0, last="Built: 3 files (0 duplicates skipped).", **kwargs):
        self.argv, self.kwargs, self.code, self.last = argv, kwargs, code, last
        self.returncode = None
        self.ended = threading.Event()
        self.stdout = self._output()

    def _output(self):
        yield "PROGRESS 1/3\n"
        yield "PROGRESS 2/3\n"
        self.ended.wait(10)
        if self.code == 0:
            language = self.argv[self.argv.index("--language") + 1] if "--language" in self.argv else "ja"
            db = self.argv[self.argv.index("--db") + 1] if "--db" in self.argv else default_db_path(language)
            _set(language, count=55, built_at="2026-10-01T09:00:00", path=db, library_tokens=1300)
        yield self.last + "\n"

    def end(self):
        self.ended.set()

    def poll(self):
        return self.returncode

    def wait(self):
        self.ended.wait(10)
        self.returncode = self.code
        return self.code


@pytest.fixture
def builds():
    """Every build started, as `_Build`s that wait for the test to end them."""
    started = []

    def popen(argv, **kwargs):
        started.append(_Build(argv, **kwargs))
        return started[-1]
    with mock.patch.object(subprocess, "Popen", side_effect=popen):
        yield started
    for build in started:
        build.end()
    _until_ended()


def _until_ended(seconds=10):
    deadline = time.monotonic() + seconds
    while backfill.background() is not None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert backfill.background() is None, "the build was never followed to its end"


def _until(condition, seconds=10):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert condition()


# --- what a build records, and the growth measured against it -------------------------------------- #
LIBRARY = ("週末に友だちと近くの山へ探検に出かけた。\n古い地図を頼りに細い道を歩いた。\n"
           "途中で小さな滝を見つけて写真を撮った。\n帰りに駅前の店で温かいそばを食べた。\n")
MORE = ("翌朝は早く起きて海辺の町まで電車で行った。\n港では漁師たちが網を片付けていた。\n"
        "市場で新鮮な魚を買って宿の台所で焼いた。\n夜は波の音を聞きながら日記を書いた。\n")


def test_a_library_build_records_the_library_it_read_and_growth_is_measured_against_it():
    tier = os.path.join(get_data_path("ja"), "HighPriority")
    os.makedirs(tier)
    paths = []
    for name, text in (("山の探検.txt", LIBRARY), ("海辺の町.txt", MORE)):
        paths.append(os.path.join(tier, name))
        with open(paths[-1], "w", encoding="utf-8") as f:
            f.write(text)
    token_index.reconcile_language("ja", paths)
    words, files = patterns_build.library_size("ja")
    assert words > 40 and files == 2

    meta = patterns_build.build()
    assert (meta["library_tokens"], meta["library_files"]) == (words, 2)
    assert backfill.growth("ja") == 0.0

    # Two more episodes as long as the first two: the library has doubled since its set was built.
    for name, text in (("山の探検・続き.txt", LIBRARY.replace("週末", "連休")), ("海辺の町・続き.txt", MORE)):
        paths.append(os.path.join(tier, name))
        with open(paths[-1], "w", encoding="utf-8") as f:
            f.write(text)
    token_index.reconcile_language("ja", paths)
    assert backfill.growth("ja") == pytest.approx(patterns_build.library_size("ja")[0] / words - 1)
    assert backfill.growth("ja") >= backfill.GROWTH


def test_a_general_corpus_records_no_library(tmp_path):
    # Its meta is no one's library: a general set is never rebuilt from the library, and never measured against it.
    _store([500, 700])
    corpus = tmp_path / "talk"
    corpus.mkdir()
    (corpus / "a.txt").write_text(MORE, encoding="utf-8")
    meta = patterns_build.build(corpus_dir=str(corpus), db_path=str(tmp_path / "patterns_ja_talk.db"))
    assert meta["corpus_kind"] == "general" and "library_tokens" not in meta


@pytest.mark.parametrize("totals, grown", [([620, 619], False),      # 1,239 words: 24% more than 1,000
                                           ([625, 625], True),       # 1,250: a quarter more
                                           ([3000], True)])
def test_the_set_is_rebuilt_once_the_library_has_grown_by_a_quarter(builds, totals, grown):
    _set(library_tokens=1000)
    _store(totals)
    assert backfill.rebuild_in_background("ja", when_grown=True) is grown
    assert len(builds) == int(grown)


def test_an_empty_library_never_starts_a_build(builds):
    _set(library_tokens=1000)
    _store([])                                  # every file gone from the library
    assert backfill.growth("ja") == -1.0
    _set(library_tokens=0)                      # built while the library held nothing, and it still holds nothing
    assert backfill.growth("ja") == 0.0
    assert backfill.rebuild_in_background("ja", when_grown=True) is False
    assert builds == []


def test_a_set_built_before_the_store_counted_anything_is_rebuilt_once_it_has():
    _set(library_tokens=0)
    _store([800])
    assert backfill.growth("ja") == float("inf")


@pytest.mark.parametrize("case", ["no set", "older builder", "recorded nothing", "no token store"])
def test_without_both_numbers_nothing_is_rebuilt_by_itself(builds, case):
    # A missing set is a first build — the window's "Build & preview", never started by itself; an older builder's
    # counts as not built (Patterns_Quality_Spec.md §8.3a); a set from before builds recorded the library, or a
    # library never indexed, gives nothing to measure against.
    if case != "no set":
        _set(**({"builder_version": BUILDER_VERSION - 1, "library_tokens": 1000} if case == "older builder"
                else {} if case == "recorded nothing" else {"library_tokens": 1000}))
    if case != "no token store":
        _store([5000])
    assert backfill.growth("ja") is None
    assert backfill.rebuild_in_background("ja", when_grown=True) is False
    assert builds == []


# --- in the background: nothing waits, one at a time, the set in use read meanwhile ---------------- #
def test_the_build_runs_beside_the_set_in_use_and_nothing_waits_for_it(builds):
    from modules.junban import patterns
    _set(library_tokens=1000)
    _store([700, 600])
    reading = dict(patterns.open_sources("ja"))["library"]      # a preview's own handle on the set
    started = time.monotonic()
    assert backfill.rebuild_in_background("ja", when_grown=True) is True
    assert time.monotonic() - started < 2.0                     # returned while the build still runs
    assert backfill.building()
    argv, flags = builds[0].argv, builds[0].kwargs["creationflags"]
    assert argv[argv.index("--db") + 1] == backfill.staged_path("ja") == default_db_path("ja") + ".new"
    # Low priority: a Generate started meanwhile goes first (Windows; elsewhere the flag does not exist).
    assert flags & getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0) == getattr(
        subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
    _until(lambda: backfill.background() == ("ja", 2, 3))
    assert reading.word("冒険", "ボウケン")[2] == 40 and _count() == 40    # the set in use, while it builds

    builds[0].end()
    _until_ended()
    assert reading.word("冒険", "ボウケン")[2] == 40            # an open reader keeps what it opened
    if os.name == "nt":                                         # Windows would not replace it under the reader
        assert os.path.exists(backfill.staged_path("ja"))
    reading.close()
    session = backfill.Session({"target_language": "ja", "junban_backfill_fills": ["patterns"]})
    try:                                                        # the next one to open it puts the new set in
        assert dict(session.stores)["library"].word("冒険", "ボウケン")[2] == 55
    finally:
        session.close()
    assert not os.path.exists(backfill.staged_path("ja"))
    assert backfill.growth("ja") == 0.0                         # measured from the new set's own record now


def test_never_two_builds_at_once(builds):
    _set(library_tokens=1000)
    _store([1500])
    assert backfill.rebuild_in_background("ja", when_grown=True) is True
    assert backfill.rebuild_in_background("ja") is False                    # the button, meanwhile
    assert backfill.start_rebuild("ja") is None                             # "Build & preview", meanwhile
    assert len(builds) == 1
    builds[0].end()
    _until_ended()
    assert not backfill.building()
    assert backfill.rebuild_in_background("ja") is True                     # one after the other is fine
    assert len(builds) == 2


def test_a_build_counts_as_running_until_its_new_set_is_put_in(builds):
    # Its process ends a moment before its follower puts the new set in: a build started in that moment would have
    # its progress line wiped by the first one's end.
    backfill._BACKGROUND.update(language="ja", done=3, total=3)
    try:
        assert backfill.building()
        assert backfill.start_rebuild("ja") is None and builds == []
    finally:
        backfill._BACKGROUND.clear()            # what its follower does once the set is in


def test_a_failed_build_keeps_the_set_in_use_and_says_so_once(builds):
    path = _set(library_tokens=1000)
    _store([1500])
    with open(path, "rb") as f:
        before = f.read()
    with mock.patch.object(subprocess, "Popen", side_effect=lambda argv, **kw: builds.append(_Build(
            argv, code=1, last="Error: the パターン build failed (disk full). The previous database is unchanged.",
            **kw)) or builds[-1]):
        assert backfill.rebuild_in_background("ja", when_grown=True) is True
        builds[0].end()
        _until_ended()
        with open(path, "rb") as f:
            assert f.read() == before
        assert not os.path.exists(backfill.staged_path("ja"))
        note = backfill.failed_note()
        assert note.startswith("Your Japanese library's パターン could not be updated (Error: the パターン build failed "
                               "(disk full).") and note.endswith("Backfill keeps using the one it has.")
        assert backfill.failed_note() == ""                                 # said once
        # It would fail the same way: the automatic one leaves it until the app starts again; the button still tries.
        assert backfill.rebuild_in_background("ja", when_grown=True) is False
        assert len(builds) == 1
        assert backfill.rebuild_in_background("ja") is True


def test_a_rebuild_that_ended_while_the_app_was_closed_goes_in_first():
    _set(library_tokens=1000)
    _store([1500])
    _set(count=55, built_at="2026-10-01T09:00:00", path=backfill.staged_path("ja"), library_tokens=1500)
    assert backfill.rebuild_in_background("ja", when_grown=True) is False   # no growth since the one waiting
    assert _count() == 55 and not os.path.exists(backfill.staged_path("ja"))


def test_a_staged_set_older_than_the_set_in_use_is_dropped():
    # "Build & preview" built the set again since (a new builder, say): the older rebuild never goes over it.
    staged = _set(path=backfill.staged_path("ja"), count=55)
    os.utime(staged, (1_000_000, 1_000_000))
    _set(count=70)
    assert backfill.promote("ja") is False
    assert _count() == 70 and not os.path.exists(staged)


def test_the_automatic_step_starts_it_and_fills_from_the_set_in_use_without_waiting(builds):
    from modules.junban.tests.test_backfill import _Session, _fake, _lapis, _patched, _settings
    _set(library_tokens=1000)
    _store([1500])
    fake = _fake(_lapis(0, "探検", "たんけん"))
    with _patched(fake), mock.patch.object(backfill, "Session", lambda settings: _Session()):
        report = backfill.run_auto(_settings())
    assert report["ok"] and backfill.building()                 # filled, while the build still runs
    assert len(builds) == 1


def test_the_automatic_step_leaves_the_set_alone_when_it_does_not_fill_patterns(builds):
    from modules.junban.tests.test_backfill import _Session, _fake, _lapis, _patched, _settings
    _set(library_tokens=1000)
    _store([1500])
    fake = _fake(_lapis(0, "探検", "たんけん"))
    with _patched(fake), mock.patch.object(backfill, "Session", lambda settings: _Session()):
        backfill.run_auto(_settings(junban_backfill_fills=["sentence"]))
    assert builds == []


def test_a_chinese_library_set_is_rebuilt_as_chinese(builds):
    # Chinese where a Chinese library exists: its own set, its own token store, its own command line.
    _store([1500], language="zh")
    assert backfill.rebuild_in_background("zh", when_grown=True) is False   # no Chinese set: nothing by itself
    _set("zh", library_tokens=1000)
    _store([1500])                                                         # the Japanese library grew too: not this
    assert backfill.rebuild_in_background("zh", when_grown=True) is True
    argv = builds[0].argv
    assert argv[argv.index("--language") + 1] == "zh"
    assert argv[argv.index("--db") + 1] == default_db_path("zh") + ".new"
    builds[0].end()
    _until_ended()
    assert backfill.promote("zh") is False and _count("zh") == 55          # in by the build's own end


# --- the button's tooltip ---------------------------------------------------------------------------- #
def test_the_tooltip_says_when_it_was_built_from_how_much_and_what_the_library_holds_now():
    _set(library_files=1987, library_tokens=4_239_192)
    _store([2_216] * 2_309 + [5_120_000 - 2_216 * 2_309])
    assert backfill.rebuild_tip("ja") == (
        "Builds your library's パターン again, in the background. Backfill keeps using the one it has meanwhile.\n"
        "Built 2026-09-30 from 1,987 files (4.2 million words).\n"
        "Your library now: 2,310 files (5.1 million words), 21% more.\n"
        "It rebuilds by itself once your library grows by a quarter.\n"
        "A word gets lines once your library uses it 12 times.")


def test_a_small_library_is_shown_word_for_word_and_an_older_set_says_how_to_keep_up():
    # No minimum size: the floor is what a small library is held to, and the tooltip says it.
    _set(files=3, tokens=8_412)                 # recorded no library: the builder's own counts stand in
    _store([3_000, 6_100])
    assert backfill.rebuild_tip("ja").split("\n")[1:] == [
        "Built 2026-09-30 from 3 files (8,412 words).",
        "Your library now: 2 files (9,100 words).",
        "Rebuild it once, and it keeps up with your library by itself.",
        "A word gets lines once your library uses it 12 times."]
