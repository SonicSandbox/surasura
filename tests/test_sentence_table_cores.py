"""The sentence table's per-line numbers on the PC's other cores (E-CORES, SPEC § 8.3): the same table, a faster walk.

What these prove:
  - a Generate at level 1 with workers writes every file in results/ byte for byte as one process does — Japanese and
    Chinese, a library with people's names (a joined name, a person's line), a Finished show (the Finished pass asks
    too); the table also under another hash seed;
  - each answer a worker gives is the one the walk works out itself (`numbers_of` against `line_words` on every real
    line, every word and span); a line a worker reads otherwise than the walk did (other tokens, another length, no
    such sentence) gives no answer, and that file is answered by the walk, read as the walk reads it — the same bytes;
  - a worker that dies, or a line offered without its question, fails the table at its write (the run's own warning),
    never the run, and never hangs it; the workers end either way;
  - one core, a small library, *Use every core* off or on, settings' `index_pool_workers` 0: the count follows
    `token_index.pool_workers`' rule, at most CORES_MAX, and 1 is today's one-process path; level 0 starts nothing.

What a wrong answer would cost a learner: a card's sentence chosen on numbers that moved with how many cores the PC
has, or with which worker finished first — or a Generate that hangs, or fails, because a helper process did.
"""
import os
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool

import pytest

from app import sentence_table as st
from tests.test_sentence_table_speed import _lines, _people


# --------------------------------------------------------------------------- #
# 1. The workers' answers are the walk's
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module", params=["ja", "zh"])
def real(request):
    language = request.param
    return language, _lines(language)


def _asked(lines, spans=True):
    """Every question the walk could ask of `lines`: each word of a line, then each 1–3 token span — as `Cores` keeps
    them (sentence number, tokens, characters, key | start, end)."""
    asked = []
    for no, (text, tokens) in enumerate(lines):
        head = (no, len(tokens), len(text))
        asked += [head + (key,) for key in dict.fromkeys((t[0], t[1]) for t in tokens)]
        if spans:
            asked += [head + (a, a + n) for n in (1, 2, 3) for a in range(len(tokens))]
    return asked


def _walk_answers(lines, kept, asked, language, people):
    """What the walk packs for each question when it works the numbers out itself (`line_words`, `Packer.add`'s clip)."""
    out = []
    for q in asked:
        text, tokens = lines[q[0]]
        words = st.line_words(kept, q[0], tokens, text, language, people)
        b, s = words.of_word(q[3]) if len(q) == 4 else words.of_span(q[3], q[4])
        out += [min(b, 255), min(s, st.STARTS_PAST)]
    return bytes(out)


def test_a_workers_answer_for_every_real_line_word_and_span_is_the_walks_own(real):
    # why: a worker works out what the walk would — every real ja / zh line, with and without the library's people,
    # from the kept counts and without them; one byte off would move a card's sentence with the PC's core count
    language, lines = real
    asked = _asked(lines)
    assert len(asked) > 1000
    kept = st.FileWords(st.file_words(lines, language), language)
    for people in (frozenset(), _people(lines)):
        for counts in (None, kept):
            counted = [0, 0]
            got = st.numbers_of(lines, counts, asked, language, people, counted)
            assert got == _walk_answers(lines, counts, asked, language, people)
            assert counted[0 if counts is not None else 1] > 0 and sum(counted) <= len(lines)


@pytest.mark.parametrize("wrong", ["tokens", "length", "past the end"])
def test_a_line_a_worker_reads_otherwise_than_the_walk_gives_no_answer(real, wrong):
    # why: the worker reads the file again from the token store — if its line is not the walk's (a re-tokenized file
    # the store had empty, a changed row) no number may come from it
    language, lines = real
    asked = _asked(lines[:20], spans=False)
    no, n_tokens, n_chars, key = asked[-1]
    asked[-1] = {"tokens": (no, n_tokens + 1, n_chars, key), "length": (no, n_tokens, n_chars + 1, key),
                 "past the end": (len(lines) + 5, n_tokens, n_chars, key)}[wrong]
    assert st.numbers_of(lines, None, asked, language) is None


# --------------------------------------------------------------------------- #
# 2. The walk's side: questions kept, answers written in in the walk's order
# --------------------------------------------------------------------------- #
class _Pool:
    """A pool that answers in this process, as the workers do — or not at all (`none`), or dies (`dies`)."""

    def __init__(self, lines, language, people, none=(), dies=False):
        self.lines, self.language, self.people, self.none, self.dies = lines, language, people, none, dies
        self.sent, self.shut = [], False

    def submit(self, _fn, batch):
        self.sent.append([path for path, _asked in batch])
        future = Future()
        if self.dies:
            future.set_exception(BrokenProcessPool("a worker died"))
        else:
            future.set_result([(None if path in self.none else
                                st.numbers_of(self.lines[path], None, asked, self.language, self.people), [0, 0])
                               for path, asked in batch])
        return future

    def shutdown(self, wait=True, cancel_futures=False):
        self.shut = True


def _walk(lines_by_file, ask):
    """Offer every word of every line of each file to a Packer, as the walk does: `ask(text, tokens, no)` -> the line's
    words (the walk's `_line_words`); `before(path)`, if any, as each file starts. -> the packer."""
    packer = st.Packer()
    for src, (path, lines) in enumerate(lines_by_file.items()):
        if hasattr(ask, "file"):
            ask.file(path, packer)
        for no, (text, tokens) in enumerate(lines):
            for key in dict.fromkeys((t[0], t[1]) for t in tokens):
                packer.add(key, src, no, len(text), hash(text) & 0xFFFF, (), (), *ask.line(text, tokens, no).of_word(key))
            if len(tokens) >= 2:
                packer.add(0, src, no, len(text), 1, (), (0,), *ask.line(text, tokens, no).of_span(0, 2))
    return packer


class _Here:
    """The one-process walk's asking (`line_words` for each line)."""

    def __init__(self, language, people):
        self.language, self.people = language, people

    def line(self, text, tokens, no):
        return st.line_words(None, no, tokens, text, self.language, self.people)


def _files(lines, n=7):
    """The real lines cut into `n` files."""
    size = len(lines) // n + 1
    return {f"file{i:02d}.srt": lines[i * size:(i + 1) * size] for i in range(n)}


@pytest.mark.parametrize("small_batches", [False, True])
def test_the_answers_are_written_in_the_walks_order_whatever_the_batches(real, monkeypatch, small_batches):
    # why: files go to the workers in batches and come back in any order; the lines' bytes must be the one-process
    # walk's, whatever the batch size (a file is never split)
    language, lines = real
    people = _people(lines)
    files = _files(lines)
    if small_batches:
        monkeypatch.setattr(st, "CORES_BATCH", 1)
    here = _walk(files, _Here(language, people))
    pool = _Pool(files, language, people)
    cores = st.Cores(pool)
    there = _walk(files, cores)
    assert bytes(there._lines) != bytes(here._lines)        # packed 0 until settled
    cores.settle(there, lambda path: (files[path], None), language, people)
    assert bytes(there._lines) == bytes(here._lines)
    assert there._ids == here._ids and bytes(there._cow) == bytes(here._cow) and bytes(there._phr) == bytes(here._phr)
    assert pool.shut
    assert sum(len(b) for b in pool.sent) == len([f for f in files.values() if f])
    assert all(len(b) == 1 for b in pool.sent) if small_batches else len(pool.sent) == 1


def test_a_file_no_worker_could_answer_is_answered_by_the_walk_as_it_read_it(real):
    # why: a worker that reads a file otherwise than the walk did answers nothing for it; the walk answers it, read
    # again as it reads it — the table is the same bytes
    language, lines = real
    files = _files(lines)
    here = _walk(files, _Here(language, frozenset()))
    read = []
    cores = st.Cores(_Pool(files, language, frozenset(), none={"file02.srt", "file05.srt"}))
    there = _walk(files, cores)
    cores.settle(there, lambda path: read.append(path) or (files[path], None), language, frozenset())
    assert read == ["file02.srt", "file05.srt"]
    assert bytes(there._lines) == bytes(here._lines)


def test_a_worker_that_dies_fails_the_table_and_the_workers_end(real):
    # why: a worker killed (memory, a crash) must not hang the Generate nor end it: the table's write fails (the run
    # prints its warning and writes the rest), and no helper process is left behind
    language, lines = real
    files = _files(lines)
    pool = _Pool(files, language, frozenset(), dies=True)
    cores = st.Cores(pool)
    packer = _walk(files, cores)
    with pytest.raises(BrokenProcessPool):
        cores.settle(packer, lambda path: (files[path], None), language, frozenset())
    assert pool.shut


def test_a_line_offered_without_its_question_fails_the_table_at_its_write(real):
    # why: the answers are matched to the lines by count, file by file — a line packed with no question would shift
    # every answer after it, so it fails the table (never the run, never a wrong table)
    language, lines = real
    files = _files(lines, 2)
    pool = _Pool(files, language, frozenset())
    cores = st.Cores(pool)
    packer = _walk(files, cores)
    packer.add(("余分", "ヨブン"), 1, 0, 3, 1)                # the second file's: no question asked
    with pytest.raises(ValueError, match="without its question"):
        cores.settle(packer, lambda path: (files[path], None), language, frozenset())
    assert pool.shut


# --------------------------------------------------------------------------- #
# 3. How many: the indexer's rule, at most CORES_MAX; 1 is today's path
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("cpus, files, setting, every, want", [
    (1, 20000, None, False, 1),         # one core: one process
    (2, 20000, None, False, 1),         # half of two
    (24, 40, None, False, 1),           # a small library (under POOL_MIN_FILES)
    (24, 20000, None, False, st.CORES_MAX),
    (24, 20000, None, True, st.CORES_MAX),
    (24, 20000, 0, False, 1),           # index_pool_workers 0: one process
    (24, 3, 8, False, min(3, st.CORES_MAX)),
    (4, 20000, None, True, min(4, st.CORES_MAX)),
])
def test_the_worker_count_follows_the_indexers_rule_at_most_cores_max(monkeypatch, cpus, files, setting, every, want):
    # why: *Use every core* and settings' `index_pool_workers` mean what they mean for the indexer; a PC with one core
    # (or a small library) gets today's single-process path
    from app import settings_manager, token_index
    monkeypatch.setattr(os, "cpu_count", lambda: cpus)
    monkeypatch.setattr(token_index, "_free_memory_mb", lambda: 16000)
    monkeypatch.setattr(token_index, "every_core", lambda: every)
    monkeypatch.setattr(settings_manager, "load_settings",
                        lambda: {} if setting is None else {"index_pool_workers": setting})
    assert st.cores_wanted(files) == want


def test_no_store_or_one_core_starts_no_worker(monkeypatch):
    # why: the workers read the token store; without one (locked, damaged) the walk works the numbers out itself
    monkeypatch.setattr(st, "cores_wanted", lambda n: 2)
    assert st.Cores.start(20000, None, "ja", frozenset()) is None
    monkeypatch.setattr(st, "cores_wanted", lambda n: 1)
    assert st.Cores.start(20000, object(), "ja", frozenset()) is None


# --------------------------------------------------------------------------- #
# 4. A Generate with workers: every file in results/ the same bytes
# --------------------------------------------------------------------------- #
def _outputs_now():
    from tests.test_services_progress import _outputs
    return _outputs()


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_generate_with_workers_writes_every_file_of_results_as_one_process_does(language, monkeypatch):
    # why: the bytes are the same or it does not land (SPEC § 8.3) — a library with people's names and a Finished show,
    # one process against two workers, and the table under another hash seed
    from tests import services_helpers as h
    from tests.test_generate_finished import _shows
    from tests.test_sentence_table import _generate_at
    monkeypatch.delenv("SURASURA_SENTENCE_TABLE", raising=False)
    store, _paths, ids = _shows(language, names=(language == "ja"))
    assert store.finish([ids["A1"], ids["A2"]]) is not None   # the Finished pass offers lines too
    store.close()
    h.write_settings({"target_language": language, "anki_connect_url": "http://127.0.0.1:9", "index_pool_workers": 0})
    alone = _generate_at(language, 1)
    assert "Sentence table: the lines' words in" not in alone
    one = _outputs_now()
    assert st.TABLE_FILE in one
    h.write_settings({"target_language": language, "anki_connect_url": "http://127.0.0.1:9", "index_pool_workers": 2})
    log = _generate_at(language, 1)
    assert "Sentence table: the lines' words in 2 processes." in log
    two = _outputs_now()
    assert sorted(two) == sorted(one)
    assert [name for name in one if one[name] != two[name]] == []
    counted = [line for line in log.splitlines() if "counted when indexed" in line]
    assert counted and counted[0].split("lines offered")[1] == \
        [line for line in alone.splitlines() if "counted when indexed" in line][0].split("lines offered")[1]
    # another hash seed: the table the same bytes too (file_words.json and word_stats.json follow the seed in one
    # process as well: not this change's)
    _generate_at(language, 1, seed="7")
    assert _outputs_now()[st.TABLE_FILE] == one[st.TABLE_FILE]


def test_at_level_0_a_generate_starts_no_worker(monkeypatch):
    # why: the switch is off in the tree — nothing of this may run, even with workers asked for
    from tests import services_helpers as h
    from tests.test_sentence_table import _generate_at
    monkeypatch.delenv("SURASURA_SENTENCE_TABLE", raising=False)
    h.seed_library("ja")
    h.write_settings({"target_language": "ja", "anki_connect_url": "http://127.0.0.1:9", "index_pool_workers": 2})
    log = _generate_at("ja", 0)
    assert "Sentence table" not in log and "sentence table" not in log
