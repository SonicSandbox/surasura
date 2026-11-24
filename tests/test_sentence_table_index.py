"""The sentence table's two numbers counted once, when a file is indexed (E-INDEX): the same table, a cheaper Generate.

What these prove:
  - what the indexer keeps for a file (`sentence_table.file_words`, the token store's `words`) gives every line of the
    real ja + zh files the numbers `LineWords` gives — for every word and every set-phrase span in it, with and
    without the library's people (a person's tokens asked the person rule at the walk); a line with a name link, a
    sentence a name table joined at the read, or tokens of another count is handed back to be counted at the walk;
  - a row of another rule's count, a damaged one, or none at all reads as "count at the walk", never as numbers;
  - a Generate at level 1 writes the same table, byte for byte, from a store indexed with the counts as from one
    indexed without them (at level 0, or by a build before them — the column dropped), Japanese and Chinese;
  - at level 0 the indexer counts nothing and keeps nothing new (the switch is off: nothing a learner has changes).

What a wrong answer would cost a learner: a card's sentence chosen on a stale or shifted count of what it says about
the word — the table would differ with how the library happened to be indexed — or, at level 0, a first read of the
library made slower for numbers nothing reads yet.
"""
import os
import sqlite3
import zlib

import pytest

from app import sentence_table as st
from tests.test_sentence_table_speed import _lines, _people

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module", params=["ja", "zh"])
def real(request):
    language = request.param
    return language, _lines(language)


def _answers(words, tokens):
    """Everything the walk asks of a line: each word's numbers, each span's (1 to 3 tokens), a word not in it."""
    keys = list(dict.fromkeys((t[0], t[1]) for t in tokens))
    spans = [(a, a + n) for n in (1, 2, 3) for a in range(len(tokens))]
    return ([words.of_word(k) for k in keys], [words.of_span(a, b) for a, b in spans], words.of_word(("無い語", "ナイゴ")))


def _clipped(answers):
    """The answers as the table keeps them (`Packer.add`: both numbers at most 255)."""
    def clip(pair):
        return min(pair[0], 255), min(pair[1], st.STARTS_PAST)
    of_word, of_span, missing = answers
    return [clip(p) for p in of_word], [clip(p) for p in of_span], clip(missing)


def _kept(sentences, language, joined=()):
    return st.FileWords(st.file_words(sentences, language), language, joined)


# --------------------------------------------------------------------------- #
# 1. What the indexer keeps gives the walk's numbers
# --------------------------------------------------------------------------- #
def test_every_real_line_kept_at_indexing_gives_the_numbers_the_walk_counts(real):
    # why: the table's bytes must not depend on where the two numbers were counted — every line of real text, every
    # word and phrase span in it, read back from what the indexer kept, is LineWords' answer as the table keeps it
    language, lines = real
    kept, compared = _kept(lines, language), 0
    for no, (text, tokens) in enumerate(lines):
        words = kept.line(no, tokens, text)
        if words is None:
            assert any(link in text for link in st._NAME_LINKS), text     # only a name link is counted at the walk
            continue
        assert _clipped(_answers(words, tokens)) == _clipped(_answers(st.LineWords(tokens, text, language), tokens))
        compared += 1
    assert compared >= 0.95 * len(lines) and compared >= 100


def test_a_line_holding_one_of_the_librarys_people_gives_the_numbers_the_walk_counts(real):
    # why: a person counts only when the line is about them (a particle or だ / です after the name) — the library's
    # people are known only after a whole index, so the indexer counts with none, and the walk asks the person rule of
    # a person's tokens alone: every line's numbers must be LineWords' with the people
    language, lines = real
    # (a Chinese library has no people today: its first words of some lines stand in, to prove the hand-back alone)
    people = _people(lines) if language == "ja" else frozenset(tokens[0][0] for _t, tokens in lines[:6] if tokens)
    kept, with_people, compared = _kept(lines, language), 0, 0
    for no, (text, tokens) in enumerate(lines):
        words = kept.line(no, tokens, text, people)
        if words is None:
            assert any(link in text for link in st._NAME_LINKS), text
            continue
        assert _clipped(_answers(words, tokens)) == _clipped(_answers(st.LineWords(tokens, text, language, people),
                                                                       tokens))
        compared += 1
        with_people += any(t[0] in people for t in tokens)
    assert with_people >= 5 and compared >= 0.95 * len(lines)


def test_a_sentence_a_name_table_joined_or_of_another_length_is_counted_at_the_walk(real):
    # why: Japanese name tables join a sentence's tokens as the store is read (names.apply_spans) — the indexed
    # tokens are then not the walk's, so the place of every word after the join would be another's
    language, lines = real
    no = next(i for i, (_text, tokens) in enumerate(lines) if len(tokens) >= 3 and i)
    kept = _kept(lines, language, joined={no})
    assert kept.line(no, lines[no][1], lines[no][0]) is None
    assert kept.line(no - 1, lines[no - 1][1], lines[no - 1][0]) is not None or not lines[no - 1][1]
    other = _kept(lines, language)
    assert other.line(no, lines[no][1][1:], lines[no][0]) is None             # one token fewer than indexed: never trusted
    assert other.line(len(lines), lines[no][1], lines[no][0]) is None          # a sentence the file did not have when indexed


def test_a_line_with_a_name_link_is_kept_as_count_at_the_walk():
    # why: フランク・ライアン is one name, held by its first piece — the rule for it reads the people all through
    tokens = [("フランク", "フランク", "フランク", "フランク"), ("・", "・", "・", "・"),
              ("ライアン", "ライアン", "ライアン", "ライアン"), ("が", "ガ", "が", "が"), ("来る", "クル", "来た", "来")]
    text = "フランク・ライアンが来た"
    plain = [("猫", "ネコ", "猫", "猫"), ("が", "ガ", "が", "が"), ("来る", "クル", "来た", "来")]
    kept = _kept([(text, tokens), ("猫が来た", plain)], "ja")
    assert kept.line(0, tokens, text) is None
    assert kept.line(1, plain, "猫が来た").of_word(("猫", "ネコ")) == st.LineWords(plain, "猫が来た", "ja").of_word(("猫", "ネコ"))


def test_a_word_late_in_a_long_line_keeps_its_start_as_the_table_does():
    # why: where the word starts is kept up to 255 (255 = at or past it): the indexer's code holds the same
    text = "あ" * 300 + "猫が来た"
    tokens = [("あ" * 300, "ア", "あ" * 300, "あ" * 300), ("猫", "ネコ", "猫", "猫"), ("が", "ガ", "が", "が"),
              ("来る", "クル", "来た", "来")]
    words = _kept([(text, tokens)], "ja").line(0, tokens, text)
    assert words.of_word(("猫", "ネコ")) == st.LineWords(tokens, text, "ja").of_word(("猫", "ネコ")) == (2, 300)
    longer = "あ" * 40000 + "猫"                     # past what two bytes hold: counted at the walk
    assert _kept([(longer, tokens[:2])], "ja").line(0, tokens[:2], longer) is None


def test_an_empty_file_and_an_empty_line_keep_nothing_to_count():
    # why: a file with no sentences, or a line with no words (a song line's, ♪～), reads back as (0, 0)
    assert _kept([], "ja").line(0, [], "") is None
    empty = _kept([("♪～", [])], "ja").line(0, [], "♪～")
    assert empty.of_word(("猫", "ネコ")) == (0, 0) and empty.of_span(0, 1) == (0, 0)


@pytest.mark.parametrize("damage", ["another rule", "cut short", "not ours", "empty"])
def test_a_row_of_another_rule_or_damaged_reads_as_count_at_the_walk(damage):
    # why: a count made by another rule (the lists rebuilt) or bytes that are not one must never become numbers
    lines = [("猫が来た", [("猫", "ネコ", "猫", "猫"), ("が", "ガ", "が", "が"), ("来る", "クル", "来た", "来")])]
    raw = st.file_words(lines, "ja")
    raw = {"another rule": (st.WORDS_RULE + 1).to_bytes(2, "little") + raw[2:], "cut short": raw[:-3],
           "not ours": b"\x00" * 3, "empty": b""}[damage]
    assert st.read_file_words(raw, "ja") is None
    assert st.read_file_words(None, "ja") is None
    assert st.read_file_words(st.file_words(lines, "ja"), "ja") is not None


# --------------------------------------------------------------------------- #
# 2. The indexer keeps them, and the Generate's table is the same bytes
# --------------------------------------------------------------------------- #
def _generate_at(language, level, extra_env=None):
    from tests.test_sentence_table import _generate_at as generate
    return generate(language, level)


def _store(language):
    from tests import services_helpers as h
    return os.path.join(h.root(), "index", f"token_store_{language}.db")


def _held(language):
    """(files the store holds, files with kept counts)."""
    con = sqlite3.connect(_store(language))
    try:
        rows = con.execute("SELECT words FROM files").fetchall()
    finally:
        con.close()
    return len(rows), sum(1 for (w,) in rows if w is not None)


def _table_bytes(language):
    from tests import services_helpers as h
    with open(os.path.join(h.root(), "results", st.TABLE_FILE), "rb") as f:
        return f.read()


def _fresh_store(language):
    path = _store(language)
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(path + suffix):
            os.remove(path + suffix)


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_at_level_1_the_table_is_the_same_bytes_from_a_store_indexed_with_or_without_the_counts(language,
                                                                                             monkeypatch):
    # why: the counts the indexer keeps replace the walk's own counting — the table may not move by a byte, whichever
    # way a library's store was made (at level 0, or with the counts)
    from tests.test_sentence_table import _seed
    monkeypatch.delenv("SURASURA_SENTENCE_TABLE", raising=False)
    _seed(language)
    _generate_at(language, 0)                       # the store indexed with the switch off: no counts kept
    files, counted = _held(language)
    assert files and counted == 0
    log = _generate_at(language, 1)                 # unchanged files: the store is reused, the walk counts
    assert "counted when indexed: 0 lines" in log
    without = _table_bytes(language)
    _fresh_store(language)
    log = _generate_at(language, 1)                 # indexed again at level 1: the counts kept, the walk reads them
    files, counted = _held(language)
    assert files and counted == files
    assert "counted when indexed: 0 lines" not in log and "counted when indexed:" in log
    assert _table_bytes(language) == without


def test_at_level_1_a_store_made_before_the_counts_gets_the_column_and_the_same_table(monkeypatch):
    # why: a store a build before this one made has no `words` column — it is added on open (no rebuild, as `lines`
    # was), every row reads as "count at the walk", and the table is the one a store with the counts gives
    from tests.test_sentence_table import _seed
    monkeypatch.delenv("SURASURA_SENTENCE_TABLE", raising=False)
    _seed("ja")
    _generate_at("ja", 1)
    with_counts = _table_bytes("ja")
    con = sqlite3.connect(_store("ja"))
    try:                                            # the files table as the build before made it (SCHEMA_VERSION 28)
        con.execute("CREATE TABLE files_before (path TEXT PRIMARY KEY, mtime REAL, size INTEGER, total INTEGER, "
                    "counts BLOB, tokens BLOB, names BLOB, bound BLOB, counted INTEGER NOT NULL DEFAULT 1, "
                    "aside INTEGER NOT NULL DEFAULT 0, lines BLOB)")
        con.execute("INSERT INTO files_before SELECT path, mtime, size, total, counts, tokens, names, bound, counted, "
                    "aside, lines FROM files")
        con.execute("DROP TABLE files")
        con.execute("ALTER TABLE files_before RENAME TO files")
        con.commit()
        assert "words" not in [r[1] for r in con.execute("PRAGMA table_info(files)")]
    finally:
        con.close()
    log = _generate_at("ja", 1)
    assert "counted when indexed: 0 lines" in log
    assert _table_bytes("ja") == with_counts
    files, counted = _held("ja")
    assert files and counted == 0


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_at_level_0_the_indexer_keeps_no_counts_and_the_log_says_nothing_of_them(language, monkeypatch):
    # why: the switch is off in the tree — a learner's first read of the library must not pay for numbers no one
    # reads yet, and a Generate's output stays today's
    from tests.test_sentence_table import _seed
    monkeypatch.delenv("SURASURA_SENTENCE_TABLE", raising=False)
    _seed(language)
    log = _generate_at(language, 0)
    files, counted = _held(language)
    assert files and counted == 0
    assert "counted when indexed" not in log


def test_the_kept_counts_are_compressed_and_smaller_than_the_tokens(monkeypatch):
    # why: the store's size is a learner's disk — the counts are two bytes a token, compressed as the tokens are
    from tests.test_sentence_table import _seed
    monkeypatch.delenv("SURASURA_SENTENCE_TABLE", raising=False)
    _seed("ja")
    _generate_at("ja", 1)
    con = sqlite3.connect(_store("ja"))
    try:
        rows = con.execute("SELECT tokens, words FROM files").fetchall()
    finally:
        con.close()
    for tokens, words in rows:
        assert st.read_file_words(zlib.decompress(words), "ja") is not None
        assert len(words) < len(tokens)


def _old_shape(path):
    """The files table as the build before made it (SCHEMA_VERSION 28: no `words` column)."""
    con = sqlite3.connect(path)
    try:
        con.execute("CREATE TABLE files_before (path TEXT PRIMARY KEY, mtime REAL, size INTEGER, total INTEGER, "
                    "counts BLOB, tokens BLOB, names BLOB, bound BLOB, counted INTEGER NOT NULL DEFAULT 1, "
                    "aside INTEGER NOT NULL DEFAULT 0, lines BLOB)")
        con.execute("INSERT INTO files_before SELECT path, mtime, size, total, counts, tokens, names, bound, counted, "
                    "aside, lines FROM files")
        con.execute("DROP TABLE files")
        con.execute("ALTER TABLE files_before RENAME TO files")
        con.commit()
    finally:
        con.close()


def test_a_store_keeps_the_indexers_counts_and_an_old_one_read_only_reads_as_none(tmp_path):
    # why: Store.file_words is the walk's one read — the row's counts as written, and for a store a build before
    # them made, opened to read only (no column added: a reader never writes), the sentences with no counts, asked
    # once (not a failing query a file)
    from app import token_index as ti
    lines = [(text, [list(t) for t in tokens]) for text, tokens in _lines("ja")[:30]]
    f = tmp_path / "episode.srt"
    f.write_text("\n".join(text for text, _t in lines), encoding="utf-8")

    def tokenize_file(_path):
        return {"sentences": lines, "counts": {"猫|ネコ": 1}, "words": st.file_words(lines, "ja")}

    db = str(tmp_path / "token_store_ja.db")
    store = ti.open_store("ja", path=db)
    try:
        store.reconcile([str(f)], tokenize_file)
        sentences, words = store.file_words(str(f))
        assert sentences == store.file_tokens(str(f)) and words is not None
        assert all(words.line(no, tokens, text) is not None for no, (text, tokens) in enumerate(sentences)
                   if tokens and not any(link in text for link in st._NAME_LINKS))
        assert store.file_words(str(tmp_path / "not-indexed.srt")) == ([], None)
    finally:
        store.close()
    _old_shape(db)
    reader = ti.open_reader("ja", path=db)
    try:
        for _ in range(2):
            sentences, words = reader.file_words(str(f))
            assert words is None and sentences == reader.file_tokens(str(f)) and sentences
        assert reader._no_words
    finally:
        reader.close()


def test_apply_spans_reports_every_sentence_a_join_changed_and_no_other(monkeypatch):
    # why: the walk trusts a sentence's kept counts only when its tokens are the indexed ones — a join of two tokens,
    # one token made a name, or a term put where every piece was dropped (a == b) all move the places after it
    from app import names
    sentences = [["猫が来た", [["猫", "ネコ", "猫", "猫"], ["が", "ガ", "が", "が"], ["来る", "クル", "来た", "来"]]]
                 for _ in range(4)]
    name = ["平野", "ヒラノ", "平野", "平野"]
    joins = [(0, 0, 2, name), (1, 1, 2, name), (2, 3, 3, name)]          # two tokens · one · an insert at the end
    monkeypatch.setattr(names, "chosen", lambda *a, **k: iter(list(joins)))
    joined = set()
    out = names.apply_spans(sentences, ["any"], {"any": 1}, joined=joined)
    assert joined == {0, 1, 2}
    assert [len(tokens) for _text, tokens in out] == [2, 3, 4, 3]
    joins[:] = [(0, 0, 1, name)]
    assert names.apply_spans([["猫", [["猫", "ネコ", "猫", "猫"]]]], ["any"], {"any": 1})[0][1] == [name]   # no set
