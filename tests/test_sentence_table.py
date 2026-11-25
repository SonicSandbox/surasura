"""The sentence table (the sentence choice): Generate keeps every candidate sentence of every list word as numbers.

What these prove, so far — the switch, `plan_rules.SENTENCE_TABLE`, before anything reads it:
  - it is 2 in the tree since the flip (3.0.19: 0 → 2 directly), and a level is only ever one of 0, 1, 2;
  - a child process (a Generate is one) takes its level from SURASURA_SENTENCE_TABLE, read once at import; any other
    value is the tree's;
  - the tree's level is the one a Generate runs: with no switch set it writes every file in results/ the same bytes
    as one with the switch at 2, the table included (before the flip: at 0, the same bytes as the code before).

What a wrong answer would cost a learner: a build half switched on in a release that was meant to change nothing —
sentences on their cards or their list moving before the release that says so.
"""
import ast
import hashlib
import os
import re
import subprocess
import sys

import pytest

from app import plan_rules

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _child_level(env_value):
    """The switch as a fresh interpreter sees it, with SURASURA_SENTENCE_TABLE `env_value` (None: not set)."""
    env = dict(os.environ)
    env.pop("SURASURA_SENTENCE_TABLE", None)
    if env_value is not None:
        env["SURASURA_SENTENCE_TABLE"] = env_value
    p = subprocess.run([sys.executable, "-c", "from app import plan_rules; print(plan_rules.SENTENCE_TABLE)"],
                       cwd=REPO, env=env, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr
    return int(p.stdout.strip())


# --------------------------------------------------------------------------- #
# 1. The switch
# --------------------------------------------------------------------------- #
def test_the_switch_is_at_release_2_in_the_tree():
    # why: the flip is its own commit (with ENGINE_REVISION and SCHEMA_VERSION), never a side effect; level 1 never
    # ships (one release: the list and the cards change together)
    with open(os.path.join(REPO, "app", "plan_rules.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    literals = [node.value.value for node in tree.body
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                and any(isinstance(t, ast.Name) and t.id == "SENTENCE_TABLE" for t in node.targets)]
    assert literals == [2]
    assert plan_rules.SENTENCE_TABLE_LEVELS == (0, 1, 2)


@pytest.mark.parametrize("env_value, level", [(None, 2), ("0", 0), ("1", 1), ("2", 2)])
def test_a_child_process_takes_its_level_from_the_environment(env_value, level):
    # why: a Generate is a subprocess; the harness runs a level by its environment, read once at import
    assert _child_level(env_value) == level


@pytest.mark.parametrize("raw", ["", " ", "3", "-1", "1.0", "on", "true", "２", "0x1"])
def test_anything_but_a_level_reads_as_the_trees_value(raw):
    # why: a typo or a stray value must never switch a release on (the full-width ２ included: int() would take it)
    assert plan_rules.sentence_table_level({"SURASURA_SENTENCE_TABLE": raw}) == plan_rules.SENTENCE_TABLE == 2
    assert plan_rules.sentence_table_level({"SURASURA_SENTENCE_TABLE": raw}, default=0) == 0


def test_a_level_with_spaces_around_it_is_that_level():
    assert plan_rules.sentence_table_level({"SURASURA_SENTENCE_TABLE": " 2\r\n"}) == 2
    assert plan_rules.sentence_table_level({}) == plan_rules.SENTENCE_TABLE


# --------------------------------------------------------------------------- #
# 2. Off is today
# --------------------------------------------------------------------------- #
def _outputs():
    # the v3 journey's head names its render time (`stamp`, ms): blanked, as plan_file_cases' hashes do
    from tests import services_helpers as h
    folder = os.path.join(h.root(), "results")
    found = {}
    for name in sorted(os.listdir(folder)):
        if os.path.isfile(os.path.join(folder, name)):
            data = open(os.path.join(folder, name), "rb").read()
            if name == "reading_list_static.html":
                data = re.sub(rb'"stamp":"\d+"', b'"stamp":""', data, count=1)
            found[name] = hashlib.sha256(data).hexdigest()
    return found


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_generate_with_no_switch_set_writes_what_one_at_the_trees_level_writes(language, monkeypatch):
    # why: the tree's level (2 since the flip) is what a learner's Generate runs — a reader that took its level from
    # anywhere but the switch shows up here as a changed file, or as no table
    from tests import services_helpers as h
    monkeypatch.delenv("SURASURA_SENTENCE_TABLE", raising=False)
    from tests.test_services_progress import _analyzer
    h.seed_library(language)
    h.write_settings({"target_language": language, "anki_connect_url": "http://127.0.0.1:9"})
    # one hash seed for both runs: word_stats.json and file_words.json list a word's files from a set, so their bytes
    # follow the seed (as test_services_progress.py's flag test fixes it) — the switch is what this compares
    found = []
    for env in ({}, {"SURASURA_SENTENCE_TABLE": "2"}):
        proc = _analyzer(language, env=dict(env, SURASURA_FORCE_RUN="1", PYTHONHASHSEED="0"))
        assert proc.returncode == 0, proc.stdout.decode("utf-8", "replace")[-2000:]
        found.append(_outputs())
    assert found[0] == found[1]
    assert "plan.json.gz" in found[0] and "sentences.bin" in found[0]


# --------------------------------------------------------------------------- #
# 3. The format (app/sentence_table.py), on real sentences
# --------------------------------------------------------------------------- #
from app import sentence_table as st  # noqa: E402

RESOURCES = os.path.join(REPO, "tests", "Test Resources")
TEXTS = {"ja": ("runaway_transcript.txt", "context_test.txt"), "zh": ("mixed_script_transcript.txt", "chinese_text_1.txt")}


def _sentences(language):
    """[(src, number, text, [word keys, as said])] of the language's real files, each file a source."""
    from app import analyzer
    tokenizer = analyzer.JapaneseTokenizer() if language == "ja" else analyzer.ChineseTokenizer()
    out = []
    for src, name in enumerate(TEXTS[language]):
        with open(os.path.join(RESOURCES, language, name), encoding="utf-8") as f:
            for number, (text, tokens) in enumerate(tokenizer.tokenize_sentences(f.read())):
                out.append((src, number, text, [(t[0], t[1]) for t in tokens]))
    return out


class _Library:
    """A made list over real sentences: rows are the words said twice or more (by key); the first five rows' words are
    known from the start; a row's word is known once its row is taught; a word said once is never known."""

    def __init__(self, sentences, max_chars=40):
        from collections import Counter
        from app import plan_rules
        said = Counter(key for *_x, keys in sentences for key in set(keys))
        self.keys = sorted(key for key, n in said.items() if n >= 2)
        self.row = {key: k for k, key in enumerate(self.keys)}
        self.known = set(self.keys[:5])
        self.lines = []                         # (word, src, number, chars, hash, cowords, over), as offered
        firsts = set()
        for src, number, text, keys in sentences:
            words = list(dict.fromkeys(keys))
            for word in words:
                over = len(text) > max_chars
                if over and (word, src) in firsts:
                    continue                    # over the cap: kept only as the word's first sentence in its file
                firsts.add((word, src))
                self.lines.append((word, src, number, len(text), plan_rules.text_hash_of(text),
                                   {c for c in words if c != word}, over))

    def packer(self, lines=None):
        p = st.Packer()
        for word, src, number, chars, h, cowords, over in (self.lines if lines is None else lines):
            p.add(word, src, number, chars, h, sorted(cowords), besides=len(cowords), starts=number % 300, over=over)
        return p

    def clauses(self, key):
        from app import plan_rules
        if key in self.known:
            return plan_rules.TRUE
        return ((self.row[key],),) if key in self.row else plan_rules.FALSE

    def finish(self, packer, language="ja", phrase_row=lambda index: None):
        return packer.finish(self.keys, self.row.get, self.clauses, lambda key: self.row.get(key, -1), lambda key: key,
                             phrase_row, [[f"show/{n}.srt", "subtitle", None] for n in range(2)],
                             {"engine": "e47", "run_signature": "sig", "language": language})

    def expected(self):
        """{row: [(src, number, chars, OVER or 0, [co-word ids])]} worked out line by line, apart from the packer."""
        named = sorted({c for line in self.lines if line[0] in self.row for c in line[5]})
        ids = {}
        for key in named:
            if key not in self.known:
                ids[key] = len(ids)
        out = {}
        for word, src, number, chars, _h, cowords, over in self.lines:
            if word in self.row:
                out.setdefault(self.row[word], []).append(
                    (src, number, chars, st.OVER if over else 0, sorted(ids[c] for c in cowords if c in ids)))
        return {k: sorted(v) for k, v in out.items()}, len(ids)


def _lines_of(table, k):
    cols, cow, _phr = table.block(k)
    out, at = [], 0
    for i in range(len(cols["src"])):
        n = int(cols["ncow"][i])
        out.append((int(cols["src"][i]), int(cols["number"][i]), int(cols["chars"][i]), int(cols["marks"][i]),
                    cow[at:at + n].tolist()))
        at += n
    return out


def _write(table, tmp_path, name=None):
    path = str(tmp_path / (name or st.TABLE_FILE))
    table.write(path)
    return path


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_table_reads_back_every_rows_lines_as_the_walk_offered_them(tmp_path, language):
    # why: the table is what every reader asks; a row's lines must come back whole — file, place, length, marks and
    # exactly its other new words — from the head and that row's block alone
    lib = _Library(_sentences(language))
    expected, n_formulas = lib.expected()
    assert len(expected) > 10 and any(len(v) > 3 for v in expected.values())
    assert any(mark for v in expected.values() for _s, _n, _c, mark, _w in v), "some line over the cap, marked"
    table = st.open_table(_write(lib.finish(lib.packer(), language), tmp_path), language=language, engine="e47",
                          run_signature="sig")
    assert table is not None
    assert sorted(table.head["rows"]) == sorted(expected)
    for k, lines in expected.items():
        assert _lines_of(table, k) == lines, lib.keys[k]
    own, ncl, _cl_len, _cl_rows = table.formulas()
    assert len(own) == len(ncl) == n_formulas
    assert table.rows() == {tuple(lib.keys[k]): k for k in expected}
    assert table.sources() == [[f"show/{n}.srt", "subtitle", None] for n in range(2)]
    assert table.block(len(lib.keys) + 5) is None


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_packed_in_any_order_the_table_is_the_same_bytes(tmp_path, language):
    # why: packed as the walk goes = packed at the end (SPEC § 3.5): the words' and co-words' first-met order, which
    # follows the walk, must never reach the file — numbers are by key and lines by (file, place)
    import random
    lib = _Library(_sentences(language))
    shuffled = list(lib.lines)
    random.Random(7).shuffle(shuffled)
    blobs = []
    for n, lines in enumerate((lib.lines, shuffled, lib.lines + lib.lines[:9])):   # (a line offered twice: once)
        path = str(tmp_path / f"{n}.bin")
        size = lib.finish(lib.packer(lines), language).write(path)
        blobs.append(open(path, "rb").read())
        assert size == len(blobs[-1])
    assert blobs[0] == blobs[1] == blobs[2]


def test_the_table_is_the_same_bytes_whatever_the_processs_hash_seed(tmp_path):
    # why: the twin of the plan's hash-seed test — co-words arrive as sets; numbered as they came, the file would move
    # with the seed
    code = ("import sys; from tests import test_sentence_table as t; lib = t._Library(t._sentences('ja')); "
            "lib.finish(lib.packer([l[:5] + (set(l[5]),) + l[6:] for l in lib.lines])).write(sys.argv[1])")
    blobs = []
    for seed in ("1", "2"):
        path = str(tmp_path / f"{seed}.bin")
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONPATH=REPO)
        p = subprocess.run([sys.executable, "-c", code, path], cwd=REPO, env=env, capture_output=True, text=True,
                           timeout=300)
        assert p.returncode == 0, p.stderr[-2000:]
        blobs.append(open(path, "rb").read())
    assert blobs[0] == blobs[1]


def test_an_empty_library_writes_a_table_with_no_rows(tmp_path):
    lib = _Library([])
    table = st.open_table(_write(lib.finish(lib.packer()), tmp_path))
    assert table is not None and table.head["rows"] == [] and table.rows() == {} and table.block(0) is None
    assert [len(x) for x in table.formulas()] == [0, 0, 0, 0]


def test_a_word_not_on_the_list_and_a_word_known_from_the_start_are_left_out(tmp_path):
    # why: a line is kept only for a row of the list; a co-word known before any file is never a new word in it
    sentences = _sentences("ja")
    lib = _Library(sentences)
    once = next(key for *_x, keys in sentences for key in keys if key not in lib.row)
    table = st.open_table(_write(lib.finish(lib.packer()), tmp_path))
    assert once not in table.rows()
    own, _ncl, _l, _r = table.formulas()
    assert not set(own.tolist()) & {lib.row[key] for key in lib.known}, "a known word has no formula"


def _small(lines, keys, row_of, phrase_row=lambda index: None):
    p = st.Packer()
    for args, kwargs in lines:
        p.add(*args, **kwargs)
    return p.finish(keys, row_of, lambda key: ((keys.index(key),),) if key in keys else (),
                    lambda key: keys.index(key) if key in keys else -1, lambda key: key, phrase_row, [],
                    {"engine": "e", "run_signature": "s", "language": "ja"})


def test_a_lines_fingerprint_is_kept_only_where_the_word_says_the_same_words_twice(tmp_path):
    # why: a word's shown sentences must never be the same sentence twice (a repeated line in another episode);
    # a line said once needs no fingerprint (0, which compresses to nothing)
    from app import plan_rules
    word, other = ("灯台", "トウダイ"), ("海", "ウミ")
    text, alone = "灯台の光が見えた。", "白い灯台が海の近くにある。"
    same, once = plan_rules.text_hash_of(text), plan_rules.text_hash_of(alone)
    t = _small([((word, 0, 3, len(text), same), {}),
                ((word, 1, 8, len(text), same), {}),                    # the same words, another episode
                ((word, 1, 9, len(alone), once, [other]), {}),
                ((other, 1, 9, len(alone), once, [word]), {}),
                ((other, 2, 0, len(text), same), {})],                  # another word's line: not the same row
               [word, other], {word: 0, other: 1}.get)
    t = st.open_table(_write(t, tmp_path))
    assert t.block(0)[0]["fp"].tolist() == [same, same, 0]
    assert t.block(1)[0]["fp"].tolist() == [0, 0]
    # the co-words are numbered by key, not as met: 海 before 灯台
    assert t.block(0)[1].tolist() == [0] and t.block(1)[1].tolist() == [1]


def test_a_lines_set_phrases_are_kept_as_their_rows(tmp_path):
    # why: a set phrase in a line counts as one more new word while it is not taught — by its row; a phrase with no
    # row (under the cut-off) is not one
    word = ("気", "キ")
    t = _small([((word, 0, 0, 5, 1), {"phrases": [7, 3]}), ((word, 0, 1, 5, 2), {"phrases": [5]})],
               [word, ("気がする", "キガスル")], {word: 0}.get, {7: 1, 3: None, 5: 1}.get)
    cols, _cow, phr = st.open_table(_write(t, tmp_path)).block(0)
    assert cols["nphr"].tolist() == [1, 1] and phr.tolist() == [1, 1]


def test_besides_and_where_the_word_starts_are_kept_and_capped(tmp_path):
    word = ("言葉", "コトバ")
    t = _small([((word, 0, 0, 30, 1), {"besides": 4, "starts": 12}),
                ((word, 0, 1, 900, 2), {"besides": 400, "starts": 600, "over": True})], [word], {word: 0}.get)
    cols = st.open_table(_write(t, tmp_path)).block(0)[0]
    assert cols["besides"].tolist() == [4, 255] and cols["starts"].tolist() == [12, st.STARTS_PAST]
    assert cols["marks"].tolist() == [0, st.OVER] and cols["chars"].tolist() == [30, 900]


@pytest.mark.parametrize("damage", ["cut", "tail", "magic", "head", "missing", "empty"])
def test_a_damaged_or_half_written_table_reads_as_none(tmp_path, damage):
    # why: a reader meeting a broken table takes today's path, never a crash and never a wrong line
    lib = _Library(_sentences("ja"))
    path = _write(lib.finish(lib.packer()), tmp_path)
    data = open(path, "rb").read()
    if damage == "missing":
        os.remove(path)
    else:
        bad = {"cut": data[:-7], "tail": data + b"\0", "magic": b"X" + data[1:], "empty": b"",
               "head": data[:20] + b"\xff" * 16 + data[36:]}[damage]
        with open(path, "wb") as f:
            f.write(bad)
    assert st.open_table(path) is None


@pytest.mark.parametrize("asked", [{"language": "zh"}, {"engine": "e46"}, {"run_signature": "other"}, {"version": 1}])
def test_another_version_engine_language_or_run_reads_as_none(tmp_path, monkeypatch, asked):
    # why: a table from another format, engine, language or run is not this library's: no table
    lib = _Library(_sentences("ja"))
    asked, version = dict(asked), st.VERSION
    if "version" in asked:
        monkeypatch.setattr(st, "VERSION", version + asked.pop("version"))     # written by the next format
    path = _write(lib.finish(lib.packer()), tmp_path)
    monkeypatch.setattr(st, "VERSION", version)
    assert st.open_table(path, **dict({"language": "ja", "engine": "e47", "run_signature": "sig"}, **asked)) is None
    if asked:
        assert st.open_table(path) is not None, "asked nothing, the same version: read"


def test_a_failed_write_leaves_the_old_table_and_no_temp(tmp_path, monkeypatch):
    lib = _Library(_sentences("ja"))
    path = _write(lib.finish(lib.packer()), tmp_path)
    before = open(path, "rb").read()

    def refuse(*_a):
        raise OSError("disk full")
    monkeypatch.setattr(st.os, "replace", refuse)
    with pytest.raises(OSError):
        lib.finish(lib.packer(lib.lines[:3])).write(path)
    assert open(path, "rb").read() == before and os.listdir(tmp_path) == [st.TABLE_FILE]


def test_a_rows_lines_come_in_file_then_place_order(tmp_path):
    # why: lines in (file, place) order are what makes the bytes the walk's alone, and Swap's "the next line of the
    # same episode" the next one in the block — a later file's early line never comes before an earlier file's
    word = ("灯台", "トウダイ")
    t = _small([((word, 1, 2, 9, 5), {}), ((word, 0, 40, 9, 6), {}), ((word, 1, 0, 9, 7), {}),
                ((word, 0, 3, 9, 8), {})], [word], {word: 0}.get)
    cols = st.open_table(_write(t, tmp_path)).block(0)[0]
    assert list(zip(cols["src"].tolist(), cols["number"].tolist())) == [(0, 3), (0, 40), (1, 0), (1, 2)]


# --------------------------------------------------------------------------- #
# 4. Generate writes it (level 1): the walk's lines, beside today's plan
# --------------------------------------------------------------------------- #
def _generate_at(language, level, force=True, extra=(), seed="0"):
    from tests.test_services_progress import _analyzer
    env = {"SURASURA_SENTENCE_TABLE": str(level), "PYTHONHASHSEED": seed}
    if force:
        env["SURASURA_FORCE_RUN"] = "1"
    proc = _analyzer(language, *extra, env=env)
    assert proc.returncode == 0, proc.stdout.decode("utf-8", "replace")[-3000:]
    return proc.stdout.decode("utf-8", "replace")


def _seed(language):
    from tests import services_helpers as h
    h.seed_library(language)
    h.write_settings({"target_language": language, "anki_connect_url": "http://127.0.0.1:9"})
    return os.path.join(h.root(), "results")


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_at_level_1_every_kept_sentence_of_the_plan_is_a_line_of_the_table(language, monkeypatch):
    # why: the table must hold every candidate — the 60 + 15 the plan keeps today are some of them, so each of them
    # must be its row's line in the table, at the same file, place and length (the best is always there: SPEC § 1)
    from app import analyzer, plan_engine
    monkeypatch.delenv("SURASURA_SENTENCE_TABLE", raising=False)
    results = _seed(language)
    _generate_at(language, 1)
    with open(os.path.join(results, "run_signature.txt"), encoding="utf-8") as f:
        signature = f.read().strip()
    table = st.open_table(os.path.join(results, st.TABLE_FILE), language=language, engine=analyzer.engine_id(),
                          run_signature=signature)
    assert table is not None
    plan = plan_engine.load(os.path.join(results, analyzer.PLAN_FILE))
    rows, checked = table.rows(), 0
    for k, (_first, pool, audio) in plan.pools.items():
        key = tuple(plan.keys[k][:2])
        assert key in rows, key
        cols = table.block(rows[key])[0]
        lines = dict(zip(zip(cols["src"].tolist(), cols["number"].tolist()), cols["chars"].tolist()))
        for s in set(pool) | set(audio):
            sentence = plan.sentences[s]
            assert lines.get((sentence[4], sentence[7])) == sentence[9], (key, sentence[0])
            checked += 1
    assert checked >= 10
    assert len(table.sources()) == len(plan.files) + len(plan.finished)


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_at_level_1_every_other_file_in_results_is_the_same_bytes_as_at_0(language, monkeypatch):
    # why: release 1 leaves the list and the journey on today's rule — the table is written beside them and nothing
    # else may move (the walk's offers to the table take nothing from the shortlists). *Length* is the learner's own
    # pick here: its default follows the level (settings_manager.sentence_length_default), which is E-LENGTH's to test
    from tests import services_helpers as h
    monkeypatch.delenv("SURASURA_SENTENCE_TABLE", raising=False)
    _seed(language)
    h.write_settings({"target_language": language, "anki_connect_url": "http://127.0.0.1:9",
                      "sentence_length_chosen": True,
                      "logic": {"context": {"min_chars": 10, "preferred_max_chars": 50}}})
    found = []
    for level in (0, 1):
        _generate_at(language, level)
        found.append(_outputs())
    assert st.TABLE_FILE in found[1] and st.TABLE_FILE not in found[0]
    found[1].pop(st.TABLE_FILE)
    assert found[0] == found[1]
    assert h.root()


def test_at_level_1_a_run_without_its_table_is_not_reused(monkeypatch):
    # why: a library generated before the switch was on (or whose table was lost) must get its table at the next
    # Generate, even when nothing else changed
    monkeypatch.delenv("SURASURA_SENTENCE_TABLE", raising=False)
    results = _seed("ja")
    _generate_at("ja", 1)
    assert "reusing existing results" in _generate_at("ja", 1, force=False)
    os.remove(os.path.join(results, st.TABLE_FILE))
    out = _generate_at("ja", 1, force=False)
    assert "reusing existing results" not in out and os.path.exists(os.path.join(results, st.TABLE_FILE))


# A set phrase said in many files (ja only: Chinese has no set phrases, analyzer.py's _phrase_set): in each file a
# line in the preferred length first, then one over the preferred length, then one over *Never longer than*.
_PAGES = ("{n}ページ目まで読んで、やっと気がついた。",
          "{n}ページ目で彼女はすぐに気が付いて振り返ったが、そこにはもう誰もいなかった。",
          "{n}ページ目を開いたとき、やっと気がついたのだが、その手紙を書いたのは先生ではなく、ずっと前に町を出ていった兄だったのだ。")


def _phrase_library(files):
    """`files` files of the three _PAGES lines (each file its own page number, so no two lines are the same text) and
    a last one holding only the over-long line; lengths 22 / 40 / 62 against preferred 30 and *Never longer than* 55."""
    from tests import services_helpers as h
    folder = h.seed_library("ja", files=["context_test.txt"])
    for n in range(files):
        with open(os.path.join(folder, f"pages_{n:03d}.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(line.format(n=n + 1) for line in _PAGES) + "\n")
    with open(os.path.join(folder, "pages_zz_only_long.txt"), "w", encoding="utf-8") as f:
        f.write(_PAGES[2].format(n=999) + "\n")
    h.write_settings({"target_language": "ja", "anki_connect_url": "http://127.0.0.1:9",
                      "logic": {"context": {"min_chars": 10, "preferred_max_chars": 30, "max_chars": 55}}})
    return os.path.join(h.root(), "results")


def test_at_level_1_a_phrase_keeps_every_line_its_shortlists_turn_away_and_an_over_long_one_only_as_a_files_first(
        monkeypatch):
    # why: the table holds every candidate (SPEC § 1), so the walk's skip of a line both full shortlists would turn
    # away (`_could_take`) must not apply at level 1 — here the later files' longer line, once 60 short ones fill both;
    # and a line over *Never longer than* is a candidate only as the phrase's first sentence in its file (never chosen,
    # kept as the fallback), as a word's is: the table's size stays what the cap allows
    monkeypatch.delenv("SURASURA_SENTENCE_TABLE", raising=False)
    files = 100
    results = _phrase_library(files)
    _generate_at("ja", 1)
    table = st.open_table(os.path.join(results, st.TABLE_FILE), language="ja")
    names = [os.path.basename(s[0]) for s in table.sources()]
    rows = [k for key, k in table.rows().items() if key[0] == "気が付く"]
    assert len(rows) == 1, sorted(table.rows())
    by_file = {}
    for src, number, _chars, marks, _w in _lines_of(table, rows[0]):
        by_file.setdefault(names[src], []).append((number, bool(marks & st.OVER)))
    paged = {name: lines for name, lines in by_file.items() if name.startswith("pages_") and "zz" not in name}
    assert len(paged) == files
    # every file: its short line and its longer one, both under the cap (the longer one turned away by full shortlists
    # in the later files at level 0), never its third, over the cap and not the file's first
    assert {len(lines) for lines in paged.values()} == {2}, sorted(
        (name, lines) for name, lines in paged.items() if len(lines) != 2)[:5]
    assert not any(over for lines in paged.values() for _n, over in lines)
    # a file whose only sentence of the phrase is over the cap: that one, kept, marked
    assert [over for _n, over in by_file["pages_zz_only_long.txt"]] == [True]


# --------------------------------------------------------------------------- #
# 5. The two numbers a line carries: words besides the word, where the word starts
# --------------------------------------------------------------------------- #
def _line(language, n, people=()):
    """Line `n` of the language's sentence_words.txt as the store yields it: (its text, its tokens, its LineWords) —
    `people`, surfaces the library knows as people's names (taken as their lemmas, as names_words holds them)."""
    from app import analyzer
    tokenizer = analyzer.JapaneseTokenizer() if language == "ja" else analyzer.ChineseTokenizer()
    with open(os.path.join(RESOURCES, language, "sentence_words.txt"), encoding="utf-8") as f:
        line = f.read().splitlines()[n]
    (text, tokens), = tokenizer.tokenize_sentences(line)
    names = frozenset(t[0] for t in tokens if t[2] in people)
    return text, tokens, st.LineWords(tokens, text, language, names)


def _key(tokens, surface):
    return next((t[0], t[1]) for t in tokens if t[2] == surface)


def test_grammar_is_left_out_and_every_content_word_counts():
    # why: "does the line say something about the word" — 私 昨日 駅 友達 besides 会う; は で に ます た say nothing
    text, tokens, words = _line("ja", 0)
    assert words.of_word(_key(tokens, "会い")) == (4, text.index("会い"))
    assert words.of_word(_key(tokens, "友達")) == (4, text.index("友達"))


def test_a_helping_verb_after_te_is_grammar_but_the_same_verb_alone_counts():
    # why: いる in 読んでいる is grammar (UniDic's helping use), in 家にいる it is the line's verb
    _text, tokens, words = _line("ja", 1)
    assert words.of_word(_key(tokens, "本"))[0] == 2              # 彼 読む
    _text, tokens, words = _line("ja", 2)
    assert words.of_word(_key(tokens, "家"))[0] == 1              # いる


def test_a_counter_after_its_number_is_grammar():
    # why: the number is no token of the store, so 人 in 三人 would read as the noun 人 'person'
    _text, tokens, words = _line("ja", 3)
    assert words.of_word(_key(tokens, "子供"))[0] == 2            # 公園 遊ぶ; not 人, not いる after で


def test_a_person_the_line_is_about_and_a_place_count_but_a_call_does_not():
    # why: the count's rule for people — ケン followed by は is part of what is said, ロンドン is a place;
    # a name standing free at the end, or before a comma, is a call
    _text, tokens, words = _line("ja", 4, people=("ケン",))
    assert words.of_word(_key(tokens, "住ん"))[0] == 2            # ケン ロンドン
    _text, tokens, words = _line("ja", 5, people=("ケン",))
    assert words.of_word(_key(tokens, "来い"))[0] == 1            # 早い; ケン is called
    _text, tokens, words = _line("ja", 9, people=("ケン",))
    assert words.of_word(_key(tokens, "来い"))[0] == 1            # こっち; ケン、 is called
    _text, tokens, words = _line("ja", 4)                         # a library that names no one: every name counts
    assert words.of_word(_key(tokens, "住ん"))[0] == 2


def test_a_name_of_several_pieces_is_one_name_and_the_word_when_it_holds_the_word():
    # why: ジョン・スミス is one person; the row スミス's line says only 医者 besides it
    text, tokens, words = _line("ja", 6, people=("ジョン", "スミス"))
    assert words.of_word(_key(tokens, "スミス")) == (1, text.index("スミス"))
    assert words.of_word(_key(tokens, "医者"))[0] == 1            # the name, once


def test_a_word_in_latin_letters_counts_and_marks_never_do():
    # why: NASA is a thing the line names; 。 and the like are no words
    _text, tokens, words = _line("ja", 7)
    assert words.of_word(_key(tokens, "衛星"))[0] == 2            # NASA 見つかる


def test_a_set_phrase_is_its_span_and_starts_where_its_first_token_does():
    # why: a phrase row's words are its own tokens — 気がする says nothing besides itself
    text, tokens, words = _line("ja", 8)
    assert words.of_span(0, 3) == (0, 0)
    assert words.of_span(2, 3) == (1, text.index("する"))         # する alone: 気 is a word besides it


def test_chinese_leaves_out_its_particles_and_prepositions():
    # why: jieba's own table — 在 了 吗 把 say nothing about the word; 我 你 他 (pronouns) do
    _text, tokens, words = _line("zh", 0)
    assert words.of_word(_key(tokens, "商店"))[0] == 4            # 我 昨天 买 本书
    _text, tokens, words = _line("zh", 1)
    assert words.of_word(_key(tokens, "吃饭"))[0] == 1            # 你


def test_an_empty_line_and_a_word_not_in_it_are_zero():
    # why: the walk never asks of a word outside the line, but a reader of the numbers must not crash on one
    words = st.LineWords([], "", "ja")
    assert words.of_word(("駅", "エキ")) == (0, 0) and words.of_span(0, 1) == (0, 0)
    _text, _tokens, words = _line("ja", 0)
    assert words.of_word(("無い語", "ナイゴ")) == (words.total, 0)


def test_the_grammar_lists_are_base_forms_and_hold_no_katakana_word():
    # why: the lists are read by base form (one token, no spaces); a katakana word is a loanword or a name: content
    import re
    for language in ("ja", "zh"):
        grammar, particles, helpers, _titles = st._lists(language)
        assert grammar and particles <= grammar and not helpers & particles
        assert all(word and not re.search(r"\s", word) for word in grammar | helpers)
    assert not [w for w in st._lists("ja")[0] if re.fullmatch(r"[゠-ヿ]+", w)]
    assert {"は", "が", "を", "の", "だ", "です", "ます", "た"} <= st._lists("ja")[0]
    assert {"的", "了", "吗", "把"} <= st._lists("zh")[0]


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_at_level_1_the_table_carries_each_lines_two_numbers(language, monkeypatch):
    # why: the score reads both numbers from the table alone (SPEC § 4.2: written by Generate, never by a reader) —
    # a plan sentence's line must carry the count and the start its text gives
    from app import analyzer, plan_engine
    monkeypatch.delenv("SURASURA_SENTENCE_TABLE", raising=False)
    results = _seed(language)
    _generate_at(language, 1)
    table = st.open_table(os.path.join(results, st.TABLE_FILE), language=language)
    plan = plan_engine.load(os.path.join(results, analyzer.PLAN_FILE))
    rows, besides, starts = table.rows(), [], []
    for k, (_first, pool, _audio) in plan.pools.items():
        cols = table.block(rows[tuple(plan.keys[k][:2])])[0]
        at = {(s, n): i for i, (s, n) in enumerate(zip(cols["src"].tolist(), cols["number"].tolist()))}
        for s in pool:
            sentence = plan.sentences[s]
            i = at[(sentence[4], sentence[7])]
            besides.append(int(cols["besides"][i]))
            starts.append((int(cols["starts"][i]), sentence[0], plan.keys[k][0]))
    assert besides and max(besides) >= 2 and len(set(besides)) >= 3
    assert any(start > 0 for start, _t, _w in starts)
    assert all(start <= len(text) for start, text, _w in starts)


def test_at_level_1_each_source_carries_its_files_own_digest_in_one_spelling(monkeypatch):
    # why: a reader skips a line whose file changed since the Generate (SPEC § 5.4) by the file's digest — its path,
    # time, size and kind, as the plan's files are signed, but its path in one spelling (st.source_digest), so a
    # reader that spells the data folder another way still finds the file; the plan's files, in the plan's order
    import re
    from app import analyzer, plan_engine
    from app.path_utils import get_data_path
    monkeypatch.delenv("SURASURA_SENTENCE_TABLE", raising=False)
    results = _seed("ja")
    _generate_at("ja", 1)
    table = st.open_table(os.path.join(results, st.TABLE_FILE), language="ja")
    plan = plan_engine.load(os.path.join(results, analyzer.PLAN_FILE))
    sources = table.sources()

    def signed(rel, kind):
        path = os.path.join(get_data_path("ja"), *rel.split("/"))
        stat = os.stat(path)
        return st.source_digest(path, [stat.st_mtime, stat.st_size], kind or None)
    assert [s[2] for s in sources[:len(plan.files)]] == [signed(f[0], f[3]) for f in plan.files]
    assert [s[0] for s in sources[:len(plan.files)]] == [f[0] for f in plan.files]
    assert all(isinstance(s[2], str) and re.fullmatch(r"[0-9a-f]{16}", s[2]) for s in sources)


def test_a_token_the_lines_text_does_not_hold_moves_no_later_place():
    # why: the line's text can lose a mark its tokens keep (a quote cut off its edge); the words after it must keep
    # their own places, and a counter's look at the character before it must stay inside the text
    tokens = [("」", "", "」", "」"), ("駅", "エキ", "駅", "駅"), ("人", "ヒト", "人", "人")]
    words = st.LineWords(tokens, "駅人", "ja")
    assert words.at == [0, 0, 1]
    assert words.of_word(("人", "ヒト")) == (1, 1)


def test_the_chinese_copula_is_grammar_as_da_and_desu_are():
    # why: 是 says nothing about the word, as だ / です do not in Japanese
    from app import analyzer
    (text, tokens), = analyzer.ChineseTokenizer().tokenize_sentences("他是老师。")
    words = st.LineWords(tokens, text, "zh")
    assert words.of_word(_key(tokens, "老师"))[0] == 1            # 他


def test_a_name_linked_to_a_piece_the_library_does_not_know_is_still_one_name():
    # why: ジョン・スミス is one person even when the library names only ジョン; what follows the whole name (は) says
    # it is part of the sentence, so the row ジョン's line says 医者 besides it — スミス is the name, not a word
    _text, tokens, words = _line("ja", 6, people=("ジョン",))
    assert words.of_word(_key(tokens, "ジョン"))[0] == 1


def test_where_the_word_starts_is_its_first_place_in_the_line():
    # why: the late-word term asks where the learner first meets the word in the line
    text, tokens, words = _line("ja", 10)
    assert words.of_word(_key(tokens, "駅")) == (1, 0)            # 歩く; both 駅 are the word, the first at 0


def test_a_title_after_a_name_is_passed_over_to_see_what_follows():
    # why: ケン警部が — the が after the title says the name is part of the sentence (警部 itself is a word, as the
    # tagger's count has it)
    _text, tokens, words = _line("ja", 11, people=("ケン",))
    assert words.of_word(_key(tokens, "来"))[0] == 2              # ケン 警部


def test_a_name_before_da_is_what_the_sentence_is_about():
    # why: 犯人はケンだ — a name followed by だ / です counts, as one followed by a particle does
    _text, tokens, words = _line("ja", 12, people=("ケン",))
    assert words.of_word(_key(tokens, "犯人"))[0] == 1            # ケン


# --------------------------------------------------------------------------- #
# 6. Each row's place in the list (format 3): the reader knows what is taught before a word without an order
# --------------------------------------------------------------------------- #
def test_places_are_kept_by_row_and_a_row_off_the_list_is_minus_one(tmp_path):
    # why: the score's reader takes "taught before this word" from the table alone when no order is passed (SPEC
    # § 5: an order is passed only after a move) — each row's place must come back as Generate gave it
    lib = _Library(_sentences("ja"))
    n = len(lib.keys)
    places = [(n - 1 - k) if k % 3 else -1 for k in range(n)]      # a list order of its own; every third row off it
    packer = lib.packer()
    table = st.open_table(_write(packer.finish(
        lib.keys, lib.row.get, lib.clauses, lambda key: lib.row.get(key, -1), lambda key: key, lambda index: None,
        [["show/0.srt", "subtitle", None]], {"engine": "e47", "run_signature": "sig", "language": "ja"},
        places=places), tmp_path))
    assert table is not None and table.head["v"] == st.VERSION >= 3
    assert table.places() == places


def test_without_places_every_row_is_off_the_list_and_an_empty_library_has_none(tmp_path):
    # why: a caller that has no list (a made table) must still write a table a reader can open; no rows, no places
    lib = _Library(_sentences("zh"))
    assert st.open_table(_write(lib.finish(lib.packer(), "zh"), tmp_path)).places() == [-1] * len(lib.keys)
    empty = _Library([])
    assert st.open_table(_write(empty.finish(empty.packer()), tmp_path, "empty.bin")).places() == []


def test_places_of_another_length_than_the_rows_are_refused(tmp_path):
    # why: a place list off by one would give every later row its neighbour's place; refused, the run's write fails
    # and is logged (the analyzer's try), and the reader takes today's path
    lib = _Library(_sentences("ja"))
    with pytest.raises(ValueError):
        lib.packer().finish(lib.keys, lib.row.get, lib.clauses, lambda key: lib.row.get(key, -1), lambda key: key,
                            lambda index: None, [], {"engine": "e47", "run_signature": "sig", "language": "ja"},
                            places=list(range(len(lib.keys) - 1)))


def _list_order(results):
    import csv
    with open(os.path.join(results, "progressive_learning_list.csv"), encoding="utf-8-sig", newline="") as f:
        return [(r["Word"], r["Reading"], r["Score"]) for r in csv.DictReader(f)]


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_at_level_1_each_rows_place_is_its_place_in_the_list_generate_wrote(language, monkeypatch):
    # why: "taught before" is the list's own order, ties included — two words of the same score keep the order the
    # list shows them in, never one the reader works out again
    monkeypatch.delenv("SURASURA_SENTENCE_TABLE", raising=False)
    results = _seed(language)
    _generate_at(language, 1)
    table = st.open_table(os.path.join(results, st.TABLE_FILE), language=language)
    listed = _list_order(results)
    assert len(listed) >= 5
    assert any(a[2] == b[2] for a, b in zip(listed, listed[1:])), "ties in the list: the test reaches them"
    places, keys = table.places(), table.head["keys"]
    assert len(places) == len(keys)
    at = {tuple(k): p for k, p in zip(keys, places)}
    assert [at[(w, r)] for w, r, _s in listed] == list(range(len(listed)))
    assert sorted(p for p in places if p >= 0) == list(range(len(listed)))   # every other row: -1


def test_at_level_1_a_generate_with_an_empty_list_writes_no_places(monkeypatch):
    # why: a library whose every word falls under the list's floor writes a table with no rows — and no places
    monkeypatch.delenv("SURASURA_SENTENCE_TABLE", raising=False)
    results = _seed("ja")
    _generate_at("ja", 1, extra=("--min-freq=100000",))
    table = st.open_table(os.path.join(results, st.TABLE_FILE), language="ja")
    assert table is not None and table.places() == [-1] * len(table.head["keys"])
    assert table.head["rows"] == []


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_at_level_1_generate_writes_the_same_table_whatever_the_hash_seed(language, monkeypatch):
    # why: the places come from the list, the rows from word_stats: neither may move with the process's seed
    monkeypatch.delenv("SURASURA_SENTENCE_TABLE", raising=False)
    results = _seed(language)
    path, blobs = os.path.join(results, st.TABLE_FILE), []
    for seed in ("1", "2"):
        if os.path.exists(path):
            os.remove(path)                 # each run's own table, never the one before
        assert "Saved the sentence table" in _generate_at(language, 1, seed=seed)
        blobs.append(open(path, "rb").read())
    assert blobs[0] == blobs[1]
    assert max(st.open_table(path).places()) >= 0
