"""The sentence table (the sentence choice): Generate keeps every candidate sentence of every list word as numbers.

What these prove, so far — the switch, `plan_rules.SENTENCE_TABLE`, before anything reads it:
  - it is 0 in the tree, and a level is only ever one of 0, 1, 2;
  - a child process (a Generate is one) takes its level from SURASURA_SENTENCE_TABLE, read once at import; any other
    value is the tree's;
  - off is today: a Generate with the switch at 0 writes every file in results/ the same bytes as one with no switch
    set at all, and no table.

What a wrong answer would cost a learner: a build half switched on in a release that was meant to change nothing —
sentences on their cards or their list moving before the release that says so.
"""
import ast
import hashlib
import os
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
def test_the_switch_is_off_in_the_tree():
    # why: every lane of the build lands inert; a flip is its own commit (with ENGINE_REVISION), never a side effect
    with open(os.path.join(REPO, "app", "plan_rules.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    literals = [node.value.value for node in tree.body
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                and any(isinstance(t, ast.Name) and t.id == "SENTENCE_TABLE" for t in node.targets)]
    assert literals == [0]
    assert plan_rules.SENTENCE_TABLE_LEVELS == (0, 1, 2)


@pytest.mark.parametrize("env_value, level", [(None, 0), ("0", 0), ("1", 1), ("2", 2)])
def test_a_child_process_takes_its_level_from_the_environment(env_value, level):
    # why: a Generate is a subprocess; the harness runs a level by its environment, read once at import
    assert _child_level(env_value) == level


@pytest.mark.parametrize("raw", ["", " ", "3", "-1", "1.0", "on", "true", "２", "0x1"])
def test_anything_but_a_level_reads_as_the_trees_value(raw):
    # why: a typo or a stray value must never switch a release on (the full-width ２ included: int() would take it)
    assert plan_rules.sentence_table_level({"SURASURA_SENTENCE_TABLE": raw}) == plan_rules.SENTENCE_TABLE_LEVELS[0]
    assert plan_rules.sentence_table_level({"SURASURA_SENTENCE_TABLE": raw}, default=2) == 2


def test_a_level_with_spaces_around_it_is_that_level():
    assert plan_rules.sentence_table_level({"SURASURA_SENTENCE_TABLE": " 2\r\n"}) == 2
    assert plan_rules.sentence_table_level({}) == plan_rules.SENTENCE_TABLE


# --------------------------------------------------------------------------- #
# 2. Off is today
# --------------------------------------------------------------------------- #
def _outputs():
    from tests import services_helpers as h
    folder = os.path.join(h.root(), "results")
    return {name: hashlib.sha256(open(os.path.join(folder, name), "rb").read()).hexdigest()
            for name in sorted(os.listdir(folder)) if os.path.isfile(os.path.join(folder, name))}


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_generate_with_the_switch_off_writes_what_one_without_it_writes(language, monkeypatch):
    # why: at 0 every file in results/ is byte for byte the code before (the build's inert rule); a reader of the
    # switch that leaks into a run at 0 shows up here as a changed file or a table
    from tests import services_helpers as h
    monkeypatch.delenv("SURASURA_SENTENCE_TABLE", raising=False)
    from tests.test_services_progress import _analyzer
    h.seed_library(language)
    h.write_settings({"target_language": language, "anki_connect_url": "http://127.0.0.1:9"})
    # one hash seed for both runs: word_stats.json and file_words.json list a word's files from a set, so their bytes
    # follow the seed (as test_services_progress.py's flag test fixes it) — the switch is what this compares
    found = []
    for env in ({}, {"SURASURA_SENTENCE_TABLE": "0"}):
        proc = _analyzer(language, env=dict(env, SURASURA_FORCE_RUN="1", PYTHONHASHSEED="0"))
        assert proc.returncode == 0, proc.stdout.decode("utf-8", "replace")[-2000:]
        found.append(_outputs())
    assert found[0] == found[1]
    assert "plan.json.gz" in found[0] and "sentences.bin" not in found[0]


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


@pytest.mark.parametrize("asked", [{"language": "zh"}, {"engine": "e46"}, {"run_signature": "other"}, {"version": 2}])
def test_another_version_engine_language_or_run_reads_as_none(tmp_path, monkeypatch, asked):
    # why: a table from another format, engine, language or run is not this library's: no table
    lib = _Library(_sentences("ja"))
    asked = dict(asked)
    if "version" in asked:
        monkeypatch.setattr(st, "VERSION", asked.pop("version"))
    path = _write(lib.finish(lib.packer()), tmp_path)
    monkeypatch.setattr(st, "VERSION", 1)
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
