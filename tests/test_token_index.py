"""Tests for the SQLite token store (app/token_index.py).

Real Japanese/Chinese text (per testing.md), not dummy ASCII. Reconciliation (delta detection,
add/remove, out-of-band edits) is verified with a call-counting wrapper around the real tokenizer
so we can assert *which* files got re-tokenized. Plus SQLite-specific edges: transaction rollback,
corruption self-heal, persistence across reopen, and the cheap needs_reconcile pre-check.

Every store is opened with an explicit temp `path` so tests never touch the real %APPDATA%.
"""

import json
import os
import sqlite3
import pytest

from app import token_index as ti

JA_ADVENTURE = (
    "冒険だ。\n冒険する？\n今夜は冒険。\n彼は毎日冒険に出かけます。\n"
    "私たちは新しい冒険を求めている。\n冒険は危険だが、価値がある。\n冒険！\n"
)
JA_OTHER = (
    "今日はいい天気です。\n猫と犬が好きです。\n公園を散歩しました。\n音楽を聞くのが趣味です。\n"
)
ZH_ADVENTURE = (
    "冒险。\n去冒险吗？\n冒险很难。\n我们需要去寻找新的冒险。\n危险往往是冒险的一部分。\n冒险！\n"
)


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _db(tmp_path, name="store.db"):
    return str(tmp_path / name)


def _counting_tokenizer(language):
    inner = ti.make_tokenizer(language)
    calls = []

    def wrapped(path):
        calls.append(ti._norm(path))
        return inner(path)

    wrapped.calls = calls
    return wrapped


def _bump_mtime(path, seconds=10):
    now = os.stat(path).st_mtime
    os.utime(path, (now + seconds, now + seconds))


def _agg_has(store, lemma):
    return store.conn.execute(
        "SELECT 1 FROM aggregate WHERE lemma=? LIMIT 1", (lemma,)).fetchone() is not None


def _agg_sum(store):
    r = store.conn.execute("SELECT COALESCE(SUM(count),0) FROM aggregate").fetchone()
    return int(r[0])


# --------------------------------------------------------------------------- #
def test_reconcile_builds_store_from_real_ja(tmp_path):
    f = tmp_path / "adv.txt"; _write(f, JA_ADVENTURE)
    tok = _counting_tokenizer("ja")
    store = ti.open_store("ja", path=_db(tmp_path))
    store.reconcile([str(f)], tok)

    assert store.total_tokens() > 0
    assert _agg_has(store, "冒険")
    # Invariant: every token is in the aggregate exactly once => SUM(aggregate) == total_tokens.
    assert _agg_sum(store) == store.total_tokens()
    assert len(tok.calls) == 1
    store.close()


def test_reconcile_idempotent_no_retokenize(tmp_path):
    f = tmp_path / "adv.txt"; _write(f, JA_ADVENTURE)
    tok = _counting_tokenizer("ja")
    store = ti.open_store("ja", path=_db(tmp_path))
    store.reconcile([str(f)], tok)
    first = store.total_tokens()
    tok.calls.clear()

    store.reconcile([str(f)], tok)   # nothing changed
    assert tok.calls == []
    assert store.total_tokens() == first
    store.close()


def test_changed_file_retokenizes_only_that_file(tmp_path):
    a = tmp_path / "a.txt"; _write(a, JA_ADVENTURE)
    b = tmp_path / "b.txt"; _write(b, JA_OTHER)
    tok = _counting_tokenizer("ja")
    store = ti.open_store("ja", path=_db(tmp_path))
    store.reconcile([str(a), str(b)], tok)
    assert _agg_has(store, "天気")
    tok.calls.clear()

    _write(b, JA_OTHER + "新しい文章を追加しました。\n"); _bump_mtime(b)
    store.reconcile([str(a), str(b)], tok)
    assert tok.calls == [ti._norm(str(b))]
    assert _agg_sum(store) == store.total_tokens()
    store.close()


def test_removed_file_is_subtracted(tmp_path):
    a = tmp_path / "a.txt"; _write(a, JA_ADVENTURE)
    b = tmp_path / "b.txt"; _write(b, JA_OTHER)
    tok = _counting_tokenizer("ja")
    store = ti.open_store("ja", path=_db(tmp_path))
    store.reconcile([str(a), str(b)], tok)
    assert _agg_has(store, "天気")
    total_with_b = store.total_tokens()

    b.unlink(); tok.calls.clear()
    store.reconcile([str(a)], tok)
    assert tok.calls == []
    assert not _agg_has(store, "天気")
    assert store.total_tokens() < total_with_b
    assert _agg_sum(store) == store.total_tokens()
    store.close()


def test_added_file_only_tokenizes_new(tmp_path):
    a = tmp_path / "a.txt"; _write(a, JA_ADVENTURE)
    tok = _counting_tokenizer("ja")
    store = ti.open_store("ja", path=_db(tmp_path))
    store.reconcile([str(a)], tok)
    base = store.total_tokens(); tok.calls.clear()

    b = tmp_path / "b.txt"; _write(b, JA_OTHER)
    store.reconcile([str(a), str(b)], tok)
    assert tok.calls == [ti._norm(str(b))]
    assert _agg_has(store, "天気")
    assert store.total_tokens() > base
    store.close()


def test_one_pass_that_removes_changes_and_adds_leaves_the_aggregate_of_a_fresh_build(tmp_path):
    """The pass sums every file's change and writes the aggregate once: a word only the removed file had goes, a
    word the changed file lost goes, a new file's words come in — row for row what a fresh build of the same
    library holds."""
    lib = tmp_path / "lib"; lib.mkdir()
    a = lib / "a.txt"; _write(a, JA_ADVENTURE)
    b = lib / "b.txt"; _write(b, JA_OTHER)
    c = lib / "c.txt"; _write(c, "図書館で本を読んだ。\n")
    store = ti.open_store("ja", path=_db(tmp_path))
    store.reconcile([str(a), str(b), str(c)], ti.make_tokenizer("ja"))

    b.unlink()                                                         # removed: 天気 goes
    _write(c, "図書館で新聞を読んだ。\n"); _bump_mtime(c)                 # changed: 本 goes, 新聞 comes
    d = lib / "d.txt"; _write(d, "公園を散歩しました。\n")                 # added: 散歩 comes back
    store.reconcile([str(a), str(c), str(d)], ti.make_tokenizer("ja"))
    rows = store.conn.execute("SELECT lemma, reading, count FROM aggregate").fetchall()
    store.close()
    assert not any(r[0] in ("天気", "本") for r in rows) and any(r[0] == "新聞" for r in rows)

    fresh = ti.open_store("ja", path=_db(tmp_path, "fresh.db"))
    fresh.reconcile([str(a), str(c), str(d)], ti.make_tokenizer("ja"))
    expected = fresh.conn.execute("SELECT lemma, reading, count FROM aggregate").fetchall()
    fresh.close()
    assert sorted(rows) == sorted(expected)


def test_out_of_band_edit_detected_by_signature(tmp_path):
    """A file edited directly on disk (never via the importer) is caught via (mtime, size)."""
    f = tmp_path / "adv.txt"; _write(f, JA_ADVENTURE)
    tok = _counting_tokenizer("ja")
    store = ti.open_store("ja", path=_db(tmp_path))
    store.reconcile([str(f)], tok)
    assert not _agg_has(store, "天気")
    tok.calls.clear()

    _write(f, JA_OTHER); _bump_mtime(f)          # manual edit
    assert store.needs_reconcile([str(f)]) is True
    store.reconcile([str(f)], tok)
    assert tok.calls == [ti._norm(str(f))]
    assert _agg_has(store, "天気") and not _agg_has(store, "冒険")
    store.close()


def test_needs_reconcile_false_when_unchanged(tmp_path):
    f = tmp_path / "adv.txt"; _write(f, JA_ADVENTURE)
    store = ti.open_store("ja", path=_db(tmp_path))
    store.reconcile([str(f)], ti.make_tokenizer("ja"))
    assert store.needs_reconcile([str(f)]) is False
    store.close()


def test_known_word_change_refilters_without_retokenizing(tmp_path):
    f = tmp_path / "adv.txt"; _write(f, JA_ADVENTURE)
    store = ti.open_store("ja", path=_db(tmp_path))
    store.reconcile([str(f)], ti.make_tokenizer("ja"))

    before = store.unknown_frequencies(skip_singles=True)
    assert "冒険" in {ti.split_key(k)[0] for k, _ in before["unknown"]}

    after = store.unknown_frequencies(known_lemmas={"冒険"}, skip_singles=True)
    assert "冒険" not in {ti.split_key(k)[0] for k, _ in after["unknown"]}
    assert after["known_tokens"] > before["known_tokens"]
    assert after["total_tokens"] == before["total_tokens"]
    store.close()


def test_skip_singles_moves_single_chars_to_baseline_ja(tmp_path):
    """The one-character rule (analyzer.single_kind): off, every one-character word is a band word; on, only a
    one-kanji dictionary word is (彼, 私 — here), and grammar (は, だ, に) is baseline. The library's size is the same
    either way."""
    from app import analyzer
    f = tmp_path / "adv.txt"; _write(f, JA_ADVENTURE)
    store = ti.open_store("ja", path=_db(tmp_path))
    store.reconcile([str(f)], ti.make_tokenizer("ja"))

    with_s = store.unknown_frequencies(skip_singles=False)
    without = store.unknown_frequencies(skip_singles=True)
    assert any(ti.split_key(k)[0] == "は" for k, _ in with_s["unknown"])
    singles = {ti.split_key(k) for k, _ in without["unknown"] if len(ti.split_key(k)[0]) == 1}
    assert singles == {("彼", "カレ")} and all(analyzer.single_kind(key) == 2 for key in singles)
    assert without["total_tokens"] == with_s["total_tokens"]
    store.close()


def test_reconcile_zh_real_text(tmp_path):
    f = tmp_path / "adv_zh.txt"; _write(f, ZH_ADVENTURE)
    store = ti.open_store("zh", path=_db(tmp_path))
    store.reconcile([str(f)], ti.make_tokenizer("zh"))
    assert store.total_tokens() > 0 and _agg_has(store, "冒险")
    assert _agg_sum(store) == store.total_tokens()
    store.close()


def test_empty_library(tmp_path):
    tok = _counting_tokenizer("ja")
    store = ti.open_store("ja", path=_db(tmp_path))
    store.reconcile([], tok)
    assert store.total_tokens() == 0 and tok.calls == []
    res = store.unknown_frequencies(skip_singles=True)
    assert res["unknown"] == [] and res["total_tokens"] == 0
    store.close()


def test_crlf_and_mixed_scripts_index_cleanly(tmp_path):
    f = tmp_path / "mixed.txt"
    with open(f, "w", encoding="utf-8", newline="") as fh:
        fh.write("冒険 ABC123 だ。\r\n今夜は冒険。\r\n")
    store = ti.open_store("ja", path=_db(tmp_path))
    store.reconcile([str(f)], ti.make_tokenizer("ja"))
    assert _agg_has(store, "冒険") and not _agg_has(store, "ABC123")
    store.close()


def test_file_tokens_caches_sequences(tmp_path):
    """The store caches each file's tokenized SENTENCES so Generate can reuse them."""
    f = tmp_path / "adv.txt"; _write(f, JA_ADVENTURE)
    store = ti.open_store("ja", path=_db(tmp_path))
    store.reconcile([str(f)], ti.make_tokenizer("ja"))
    sents = store.file_tokens(str(f))
    assert sents, "sequences should be cached"
    lemmas = {tok[0] for _s, toks in sents for tok in toks}   # tok = [lemma, reading, surface]
    assert "冒険" in lemmas
    assert store.file_tokens(str(tmp_path / "missing.txt")) == []
    store.close()


def test_a_store_written_at_the_old_compression_reads_the_same_tokens(tmp_path):
    """The blobs are compressed at level 4 now (level 6, zlib's default, was a full re-read's biggest single cost);
    a store written before holds level-6 blobs and must read exactly as it did — no rebuild, the same tokens."""
    import zlib
    sample = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "samples", "ja", "LowPriority", "L_priority_sample_1.txt")
    result = ti.make_tokenizer("ja")(sample)
    counts = {k: n for k, n in result["counts"].items() if n > 0}
    old_tokens = zlib.compress(json.dumps(result["sentences"], ensure_ascii=False).encode("utf-8"), 6)
    old_counts = zlib.compress(json.dumps(counts, ensure_ascii=False).encode("utf-8"), 6)
    new_tokens, new_counts = ti._encode_tokens(result["sentences"]), ti._encode_counts(counts)
    assert old_tokens != new_tokens                     # really two compressions of one file
    assert ti._decode_tokens(old_tokens) == ti._decode_tokens(new_tokens) != []
    assert ti._decode_counts(old_counts) == ti._decode_counts(new_counts) == counts

    # A store row holding the old blob reads through file_tokens just as a new one does.
    store = ti.open_store("ja", path=_db(tmp_path))
    store.reconcile([sample], ti.make_tokenizer("ja"))
    fresh = store.file_tokens(sample)
    store.conn.execute("UPDATE files SET tokens = ? WHERE path = ?", (old_tokens, ti._norm(sample)))
    store.conn.commit()
    assert store.file_tokens(sample) == fresh
    store.close()


def test_a_files_counts_are_its_tokens_with_japanese_in_the_lemma_or_the_surface(tmp_path):
    """The count asks once per word whether a lemma holds Japanese (it ran on every token of a full re-read); the
    answer stays the rule's, token by token — across files, with the surface still asked when the lemma has none."""
    from collections import Counter
    from app import analyzer
    samples = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples", "ja")
    tokenize_file = ti.make_tokenizer("ja")
    for path in (os.path.join(samples, "LowPriority", "L_priority_sample_2.txt"),
                 os.path.join(samples, "HighPriority", "H_priority_sample_2.srt")):
        result = tokenize_file(path)
        expected = Counter(ti.make_key(lemma, reading) for _s, tokens in result["sentences"]
                           for lemma, reading, surface, _o in tokens
                           if analyzer.has_target_language(lemma, "ja") or analyzer.has_target_language(surface, "ja"))
        assert expected and result["counts"] == expected


def test_ignored_entries_are_read_again_only_when_the_known_words_change(tmp_path, monkeypatch):
    """Every Rarity slider refresh asks for KnownWord.json's IGNORED entries: the file is parsed again only when it
    changes (its time or size), and the answer is always the file's."""
    from app import path_utils
    known = tmp_path / "KnownWord.json"

    def write(ignored):
        known.write_text(json.dumps({"words": [{"dictForm": w, "knownStatus": "IGNORED"} for w in ignored]
                                     + [{"dictForm": "天気", "knownStatus": "KNOWN"}]}, ensure_ascii=False),
                         encoding="utf-8")
    write(["冒険"])
    assert ti.ignored_entries(str(tmp_path), "ja") == ["冒険"]
    reads = []
    real = path_utils.read_text
    monkeypatch.setattr(path_utils, "read_text", lambda *a, **k: reads.append(a) or real(*a, **k))
    assert ti.ignored_entries(str(tmp_path), "ja") == ["冒険"]
    assert reads == []                                   # unchanged: not parsed again
    write(["冒険", "散歩"]); _bump_mtime(known)
    assert ti.ignored_entries(str(tmp_path), "ja") == ["冒険", "散歩"]
    assert len(reads) == 1


def test_persists_across_reopen(tmp_path):
    db = _db(tmp_path)
    f = tmp_path / "adv.txt"; _write(f, JA_ADVENTURE)
    s1 = ti.open_store("ja", path=db)
    s1.reconcile([str(f)], ti.make_tokenizer("ja"))
    total = s1.total_tokens(); s1.close()

    s2 = ti.open_store("ja", path=db)              # reopen same DB
    assert s2.total_tokens() == total
    assert _agg_has(s2, "冒険")
    assert s2.needs_reconcile([str(f)]) is False   # signatures survived
    s2.close()


def test_reconcile_rolls_back_on_tokenizer_error(tmp_path):
    """A tokenizer failure mid-reconcile rolls the whole transaction back — no partial state."""
    a = tmp_path / "a.txt"; _write(a, JA_ADVENTURE)
    b = tmp_path / "b.txt"; _write(b, JA_OTHER)
    store = ti.open_store("ja", path=_db(tmp_path))
    store.reconcile([str(a)], ti.make_tokenizer("ja"))
    before = store.total_tokens()

    def boom(path):
        raise RuntimeError("tokenizer exploded")

    with pytest.raises(RuntimeError):
        store.reconcile([str(a), str(b)], boom)    # b is new -> boom -> rollback
    assert store.total_tokens() == before          # unchanged
    assert not _agg_has(store, "天気")
    store.close()


def test_corrupt_db_self_heals(tmp_path):
    db = _db(tmp_path)
    with open(db, "wb") as f:
        f.write(b"this is definitely not a sqlite database" * 50)
    store = ti.open_store("ja", path=db)           # must rebuild, not crash
    assert store.total_tokens() == 0
    f = tmp_path / "adv.txt"; _write(f, JA_ADVENTURE)
    store.reconcile([str(f)], ti.make_tokenizer("ja"))
    assert store.total_tokens() > 0
    store.close()


def test_schema_version_mismatch_rebuilds(tmp_path):
    db = _db(tmp_path)
    f = tmp_path / "adv.txt"; _write(f, JA_ADVENTURE)
    s = ti.open_store("ja", path=db)
    s.reconcile([str(f)], ti.make_tokenizer("ja"))
    s.close()
    # Simulate a future/older schema -> next open must rebuild empty.
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA user_version = 999")
    conn.commit(); conn.close()
    s2 = ti.open_store("ja", path=db)
    assert s2.total_tokens() == 0
    s2.close()


def test_a_store_from_before_the_lemma_reading_key_is_rebuilt(tmp_path):
    """v4 -> v5: Japanese words are keyed by the lemma's reading now. A v4 store's cached sentences
    and aggregate carry the conjugated readings (辿り着いた -> タドリツイ), and reusing them would bring
    the per-conjugation split straight back — so it must be dropped and rebuilt, never read."""
    db = _db(tmp_path)
    f = tmp_path / "journey.txt"
    _write(f, "長い旅の末に、ついに城へ辿り着いた。\nこの道を行けば、必ず海に辿り着く。\n")
    s = ti.open_store("ja", path=db)
    s.reconcile([str(f)], ti.make_tokenizer("ja"))
    s.close()
    conn = sqlite3.connect(db)      # what a v4 store holds for the first line
    conn.execute("UPDATE aggregate SET reading = 'タドリツイ' WHERE lemma = '辿り着く'")
    conn.execute("PRAGMA user_version = 4")
    conn.commit(); conn.close()

    s2 = ti.open_store("ja", path=db)
    assert s2.total_tokens() == 0, "a v4 store was reused"
    s2.reconcile([str(f)], ti.make_tokenizer("ja"))
    rows = s2.conn.execute("SELECT reading, count FROM aggregate WHERE lemma = '辿り着く'").fetchall()
    assert rows == [("タドリツク", 2)]
    s2.close()


def test_a_store_from_before_words_kept_their_affixes_is_rebuilt(tmp_path):
    """v5 -> v6: prefixes and suffixes are joined to their word (Patterns_Quality_Spec §6.6). A v5
    store's cached sentences hold the pieces — 新 + 幹線 — and reusing them would keep counting 幹線, so
    it must be dropped and rebuilt, never read."""
    db = _db(tmp_path)
    f = tmp_path / "trains.txt"
    _write(f, "新幹線に乗って東京へ行った。\n新幹線はとても速い。\n")
    s = ti.open_store("ja", path=db)
    s.reconcile([str(f)], ti.make_tokenizer("ja"))
    s.close()
    conn = sqlite3.connect(db)      # what a v5 store holds: the pieces
    conn.execute("UPDATE aggregate SET lemma = '幹線', reading = 'カンセン' WHERE lemma = '新幹線'")
    conn.execute("PRAGMA user_version = 5")
    conn.commit(); conn.close()

    s2 = ti.open_store("ja", path=db)
    assert s2.total_tokens() == 0, "a v5 store was reused"
    s2.reconcile([str(f)], ti.make_tokenizer("ja"))
    rows = s2.conn.execute("SELECT lemma, reading, count FROM aggregate WHERE lemma IN ('新幹線', '幹線')").fetchall()
    assert rows == [("新幹線", "シンカンセン", 2)]
    s2.close()


def test_a_store_from_before_each_polite_word_was_decided_once_is_rebuilt(tmp_path):
    """v6 -> v7: the join table decides an お / ご word once for all its spellings (Patterns_Quality_Spec
    §15.9) — おやすみ now joins, as お休み did. A v6 store's cached sentences hold おやすみ in pieces, and
    reusing them would keep counting 休む, so it must be dropped and rebuilt."""
    db = _db(tmp_path)
    f = tmp_path / "night.txt"
    _write(f, "おやすみなさい。\nおやすみ、また明日ね。\n")
    s = ti.open_store("ja", path=db)
    s.reconcile([str(f)], ti.make_tokenizer("ja"))
    s.close()
    conn = sqlite3.connect(db)      # what a v6 store holds: お + 休む
    conn.execute("UPDATE aggregate SET lemma = '休む', reading = 'ヤスム' WHERE lemma = 'おやすみ'")
    conn.execute("PRAGMA user_version = 6")
    conn.commit(); conn.close()

    s2 = ti.open_store("ja", path=db)
    assert s2.total_tokens() == 0, "a v6 store was reused"
    s2.reconcile([str(f)], ti.make_tokenizer("ja"))
    rows = s2.conn.execute("SELECT lemma, reading, count FROM aggregate WHERE lemma IN ('おやすみ', '休む')").fetchall()
    assert rows == [("おやすみ", "オヤスミ", 2)]
    s2.close()


def test_a_store_from_before_the_parsing_fixes_is_rebuilt(tmp_path):
    """v7 -> v8: the parsing fixes (2026-09-27) change what a file's text becomes —
    here the tagger reading NFKC: half-width ﾅｲﾌ is the word ナイフ, which a v7 store never counted. Reusing a
    v7 store would keep it uncounted, so it must be dropped and rebuilt."""
    db = _db(tmp_path)
    f = tmp_path / "knife.txt"
    _write(f, "ﾅｲﾌを持ってる。\nﾅｲﾌは危ない。\n")
    s = ti.open_store("ja", path=db)
    s.reconcile([str(f)], ti.make_tokenizer("ja"))
    knife = s.conn.execute("SELECT lemma, reading, count FROM aggregate WHERE reading = 'ナイフ'").fetchall()
    s.close()
    assert knife and knife[0][2] == 2
    conn = sqlite3.connect(db)      # what a v7 store holds: nothing for ﾅｲﾌ
    conn.execute("DELETE FROM aggregate WHERE reading = 'ナイフ'")
    conn.execute("PRAGMA user_version = 7")
    conn.commit(); conn.close()

    s2 = ti.open_store("ja", path=db)
    assert s2.total_tokens() == 0, "a v7 store was reused"
    s2.reconcile([str(f)], ti.make_tokenizer("ja"))
    assert s2.conn.execute("SELECT lemma, reading, count FROM aggregate WHERE reading = 'ナイフ'").fetchall() == knife
    s2.close()


def test_a_store_from_before_names_stayed_whole_is_rebuilt(tmp_path):
    """v8 -> v9: a name the tagger cuts into pieces is one word now (app/names.py) — here the made-up katakana name
    ミロナイ, which a v8 store holds as ミロ + ナイ — and the store records each file's name candidates in a column a
    v8 store lacks. Reusing a v8 store would keep the pieces, so it must be dropped and rebuilt."""
    db = _db(tmp_path)
    f = tmp_path / "village.txt"
    _write(f, "昨日、ミロナイが村に来た。\nミロナイは森に帰った。\n")
    s = ti.open_store("ja", path=db)
    s.reconcile([str(f)], ti.make_tokenizer("ja"))
    name = s.conn.execute("SELECT lemma, reading, count FROM aggregate WHERE lemma = 'ミロナイ'").fetchall()
    s.close()
    assert name and name[0][2] == 2
    conn = sqlite3.connect(db)      # what a v8 store holds: the pieces, never the name
    conn.execute("DELETE FROM aggregate WHERE lemma = 'ミロナイ'")
    conn.execute("PRAGMA user_version = 8")
    conn.commit(); conn.close()

    s2 = ti.open_store("ja", path=db)
    assert s2.total_tokens() == 0, "a v8 store was reused"
    s2.reconcile([str(f)], ti.make_tokenizer("ja"))
    assert s2.conn.execute("SELECT lemma, reading, count FROM aggregate WHERE lemma = 'ミロナイ'").fetchall() == name
    s2.close()


def test_a_store_from_before_stretched_words_were_read_is_rebuilt(tmp_path):
    """v9 -> v10: the text a file becomes reads differently — here 𠮟 (the 常用漢字表's other form of 叱), which a v9
    store dropped as a symbol and now reads as 叱る. Reusing a v9 store would keep the old tokens, so it must be
    dropped and rebuilt."""
    db = _db(tmp_path)
    f = tmp_path / "scold.txt"
    _write(f, "先生に𠮟られた。\n母にも𠮟られた。\n")
    s = ti.open_store("ja", path=db)
    s.reconcile([str(f)], ti.make_tokenizer("ja"))
    scold = s.conn.execute("SELECT lemma, reading, count FROM aggregate WHERE lemma = '叱る'").fetchall()
    s.close()
    assert scold and scold[0][2] == 2
    conn = sqlite3.connect(db)      # what a v9 store holds: no 叱る — 𠮟 was dropped as a symbol
    conn.execute("DELETE FROM aggregate WHERE lemma = '叱る'")
    conn.execute("PRAGMA user_version = 9")
    conn.commit(); conn.close()

    s2 = ti.open_store("ja", path=db)
    assert s2.total_tokens() == 0, "a v9 store was reused"
    s2.reconcile([str(f)], ti.make_tokenizer("ja"))
    assert s2.conn.execute("SELECT lemma, reading, count FROM aggregate WHERE lemma = '叱る'").fetchall() == scold
    s2.close()


def test_a_store_from_before_compounds_were_one_word_is_rebuilt(tmp_path):
    """v10 -> v11: a word made of words is one word now — here 上層部, which the tagger cuts and a v10 store holds as
    上層 + 部. Reusing a v10 store would keep the pieces, so it must be dropped and rebuilt."""
    db = _db(tmp_path)
    f = tmp_path / "office.txt"
    _write(f, "会社の上層部が決めた。\n上層部は何も言わない。\n")
    s = ti.open_store("ja", path=db)
    s.reconcile([str(f)], ti.make_tokenizer("ja"))
    word = s.conn.execute("SELECT lemma, reading, count FROM aggregate WHERE lemma = '上層部'").fetchall()
    s.close()
    assert word == [("上層部", "ジョウソウブ", 2)]
    conn = sqlite3.connect(db)      # what a v10 store holds: the pieces, never the word
    conn.execute("DELETE FROM aggregate WHERE lemma = '上層部'")
    conn.execute("PRAGMA user_version = 10")
    conn.commit(); conn.close()

    s2 = ti.open_store("ja", path=db)
    assert s2.total_tokens() == 0, "a v10 store was reused"
    s2.reconcile([str(f)], ti.make_tokenizer("ja"))
    assert s2.conn.execute("SELECT lemma, reading, count FROM aggregate WHERE lemma = '上層部'").fetchall() == word
    s2.close()


def test_a_store_from_before_names_were_recorded_is_rebuilt(tmp_path):
    """v11 -> v12: each file's record now holds the words that are people's names there, and the store keeps the
    library's (Settings' Ignore names reads them). A v11 store's records hold none — reused, the switch would hide no
    name from any file read before — so it must be dropped and rebuilt."""
    db = _db(tmp_path)
    f = tmp_path / "village.txt"
    _write(f, "須藤は村に来た。\n須藤は森に帰った。\n")
    s = ti.open_store("ja", path=db)
    s.reconcile([str(f)], ti.make_tokenizer("ja"))
    assert json.loads(s.get_meta("names_words")) == ["スドウ"]
    s.close()
    conn = sqlite3.connect(db)      # what a v11 store holds: records without names, no library names kept
    conn.execute("DELETE FROM meta WHERE key = 'names_words'")
    conn.execute("PRAGMA user_version = 11")
    conn.commit(); conn.close()

    s2 = ti.open_store("ja", path=db)
    assert s2.total_tokens() == 0, "a v11 store was reused"
    s2.reconcile([str(f)], ti.make_tokenizer("ja"))
    assert json.loads(s2.get_meta("names_words")) == ["スドウ"]
    s2.close()


def test_a_store_from_before_kanji_terms_were_recorded_is_rebuilt(tmp_path):
    """v12 -> v13: each Japanese file also records its runs of one-kanji tokens (a story's own kanji terms may be one),
    how often each kanji stands alone, and whether it is a transcript of auto-generated captions. A v12 store's records
    lack them, so no term could ever join: it must be dropped and rebuilt."""
    db = _db(tmp_path)
    f = tmp_path / "technique.txt"
    _write(f, "焔魄陣を放った。\n彼の焔魄陣は強い。\n")
    s = ti.open_store("ja", path=db)
    s.reconcile([str(f)], ti.make_tokenizer("ja"))
    record = ti._decode_counts(s.conn.execute("SELECT names FROM files").fetchone()[0])
    s.close()
    assert record["q"] == {"焔": 2, "魄": 2, "陣": 2, "彼": 1}
    assert [span[5:] for span in record["s"]] == [["w", "焔魄陣", 0, "ccc"]] * 2 and "a" not in record
    conn = sqlite3.connect(db)      # what a v12 store holds: no runs, no lone uses
    old = dict(record, s=[], q={})
    conn.execute("UPDATE files SET names = ?", (ti._encode_counts(old),))
    conn.execute("PRAGMA user_version = 12")
    conn.commit(); conn.close()

    s2 = ti.open_store("ja", path=db)
    assert s2.total_tokens() == 0, "a v12 store was reused"
    s2.reconcile([str(f)], ti.make_tokenizer("ja"))
    assert ti._decode_counts(s2.conn.execute("SELECT names FROM files").fetchone()[0]) == record
    s2.close()


def test_a_store_from_before_words_the_text_writes_as_words_is_rebuilt(tmp_path):
    """v13 -> v14: a word general text writes as words, though the tagger reads it otherwise alone, is one word — here
    出来損ない, which a sentence cuts into 出来 + 損ない and a v13 store holds as those two — and a verb's stem may stand
    in a noun the dictionaries mark (待ち + 時間). Reusing a v13 store would keep the pieces, so it must be dropped and
    rebuilt."""
    db = _db(tmp_path)
    f = tmp_path / "plans.txt"
    _write(f, "この出来損ないの計画はもう捨てよう。\n駅での待ち時間はいつも長い。\n")
    s = ti.open_store("ja", path=db)
    s.reconcile([str(f)], ti.make_tokenizer("ja"))
    words = s.conn.execute("SELECT lemma, reading, count FROM aggregate WHERE lemma IN ('出来損ない', '待ち時間') "
                           "ORDER BY lemma").fetchall()
    s.close()
    assert words == [("出来損ない", "デキソコナイ", 1), ("待ち時間", "マチジカン", 1)]
    conn = sqlite3.connect(db)      # what a v13 store holds: the pieces, never the words
    conn.execute("DELETE FROM aggregate WHERE lemma IN ('出来損ない', '待ち時間')")
    conn.execute("PRAGMA user_version = 13")
    conn.commit(); conn.close()

    s2 = ti.open_store("ja", path=db)
    assert s2.total_tokens() == 0, "a v13 store was reused"
    s2.reconcile([str(f)], ti.make_tokenizer("ja"))
    assert s2.conn.execute("SELECT lemma, reading, count FROM aggregate WHERE lemma IN ('出来損ない', '待ち時間') "
                           "ORDER BY lemma").fetchall() == words
    s2.close()


def test_a_store_from_before_sounds_were_words_is_rebuilt(tmp_path):
    """v14 -> v15: two fillers the tagger cut out of one interjection are that word — まあ, which a v14 store holds as
    the fillers ま + あ — and a sound said three times or more that the dictionary doesn't know is the sound word said
    twice (ハァハァハァ is はあはあ, a word of its own before). Reusing a v14 store would keep the pieces, so it must be
    dropped and rebuilt."""
    db = _db(tmp_path)
    f = tmp_path / "trip.txt"
    _write(f, "旅行は大変だったんですけどまあやっぱり楽しかったです。\nハァハァハァ…もう走れない。\n")
    s = ti.open_store("ja", path=db)
    s.reconcile([str(f)], ti.make_tokenizer("ja"))
    words = s.conn.execute("SELECT lemma, reading, count FROM aggregate WHERE lemma IN ('まあ', 'はあはあ') "
                           "ORDER BY lemma").fetchall()
    s.close()
    assert words == [("はあはあ", "ハアハア", 1), ("まあ", "マア", 1)]
    conn = sqlite3.connect(db)      # what a v14 store holds: the fillers and the unknown sound, never the words
    conn.execute("DELETE FROM aggregate WHERE lemma IN ('まあ', 'はあはあ')")
    conn.execute("PRAGMA user_version = 14")
    conn.commit(); conn.close()

    s2 = ti.open_store("ja", path=db)
    assert s2.total_tokens() == 0, "a v14 store was reused"
    s2.reconcile([str(f)], ti.make_tokenizer("ja"))
    assert s2.conn.execute("SELECT lemma, reading, count FROM aggregate WHERE lemma IN ('まあ', 'はあはあ') "
                           "ORDER BY lemma").fetchall() == words
    s2.close()


def test_a_store_from_before_one_kanji_pieces_were_recorded_is_rebuilt(tmp_path):
    """v15 -> v16: each Japanese file also records how often each one-kanji word stands there as a piece of something
    else (年 in 三年, 前 in 三年前 — analyzer.bound_uses), summed in the `bound` table, so the Rarity slider counts a
    one-kanji list word by its uses on its own, as the list does. A v15 store records none: it must be dropped and
    rebuilt."""
    db = _db(tmp_path)
    f = tmp_path / "town.txt"
    _write(f, "三年前にこの町へ来た。\n年が明けて、雪が降った。\n")
    s = ti.open_store("ja", path=db)
    s.reconcile([str(f)], ti.make_tokenizer("ja"))
    pieces = s.bound_counts()
    record = ti._decode_counts(s.conn.execute("SELECT bound FROM files").fetchone()[0])
    s.close()
    assert pieces == {("年", "ネン"): 1, ("前", "マエ"): 1} and record == {"年|ネン": 1, "前|マエ": 1}
    conn = sqlite3.connect(db)      # what a v15 store holds: no pieces recorded
    conn.execute("UPDATE files SET bound = NULL")
    conn.execute("DELETE FROM bound")
    conn.execute("PRAGMA user_version = 15")
    conn.commit(); conn.close()

    s2 = ti.open_store("ja", path=db)
    assert s2.total_tokens() == 0, "a v15 store was reused"
    s2.reconcile([str(f)], ti.make_tokenizer("ja"))
    assert s2.bound_counts() == pieces
    s2.close()


def test_a_store_from_before_chinese_was_cut_by_the_dictionary_is_rebuilt(tmp_path):
    """v16 -> v17: Chinese is cut by analyzer.chinese_cut — jieba's guesses off, CC-CEDICT's words, numbers no words,
    doubled forms at their word, the new sentence ends. A v16 store holds the old pieces (他来 as one word): it must be
    dropped and rebuilt."""
    db = _db(tmp_path)
    f = tmp_path / "trip.txt"
    _write(f, "他来了，我们一起吃了一碗饭。\n大家都开开心心的。\n")
    s = ti.open_store("zh", path=db)
    s.reconcile([str(f)], ti.make_tokenizer("zh"))
    words = {lemma for (lemma, _reading) in s.word_counts()[0]}
    s.close()
    assert {"他", "来", "碗", "开心"} <= words and not {"他来", "一碗", "一", "开开心心"} & words
    conn = sqlite3.connect(db)      # what a v16 store is: the version it was written with
    conn.execute("PRAGMA user_version = 16")
    conn.commit(); conn.close()

    s2 = ti.open_store("zh", path=db)
    assert s2.total_tokens() == 0, "a v16 store was reused"
    s2.reconcile([str(f)], ti.make_tokenizer("zh"))
    assert {lemma for (lemma, _reading) in s2.word_counts()[0]} == words
    s2.close()


def test_a_store_from_before_the_dictionary_words_the_tagger_cuts_is_rebuilt(tmp_path):
    """v17 -> v18: a verb + its negative or causative and a word + particles the dictionary lists are one word, a
    pronoun + a suffix the lists carry is one, a katakana word stretched inside is read without the stretch where that
    is a word. A v17 store holds them in pieces (いつ + も): it must be dropped and rebuilt."""
    db = _db(tmp_path)
    f = tmp_path / "late.txt"
    _write(f, "彼はいつも遅れてくる。\nそんなくだらない話はやめろ。\n")
    s = ti.open_store("ja", path=db)
    s.reconcile([str(f)], ti.make_tokenizer("ja"))
    words = {lemma for (lemma, _reading) in s.word_counts()[0]}
    s.close()
    assert {"いつも", "くだらない"} <= words and not {"何時", "下る"} & words
    conn = sqlite3.connect(db)      # what a v17 store is: the version it was written with
    conn.execute("PRAGMA user_version = 17")
    conn.commit(); conn.close()

    s2 = ti.open_store("ja", path=db)
    assert s2.total_tokens() == 0, "a v17 store was reused"
    s2.reconcile([str(f)], ti.make_tokenizer("ja"))
    assert {lemma for (lemma, _reading) in s2.word_counts()[0]} == words
    s2.close()


def test_a_store_from_before_a_counters_one_kanji_word_was_a_piece_is_rebuilt(tmp_path):
    """v18 -> v19: a one-kanji word right after a number's counter written in kanji is a piece of the count — the 目
    of ２時間目 'second period' — and each file records it among its pieces; a v18 store counted it as a use of 目 'eye':
    it must be dropped and rebuilt. (Pinned at 19 until v20, the caption cleaner: below.)"""
    assert ti.SCHEMA_VERSION >= 19
    db = _db(tmp_path)
    f = tmp_path / "school.txt"
    _write(f, "２時間目は数学の授業だ。\n目が疲れた。\n")
    s = ti.open_store("ja", path=db)
    s.reconcile([str(f)], ti.make_tokenizer("ja"))
    pieces = s.bound_counts()
    s.close()
    assert pieces == {("目", "メ"): 1}, "the 目 of ２時間目 is a piece; 目が疲れた is the word"
    conn = sqlite3.connect(db)      # what a v18 store is: the version it was written with
    conn.execute("PRAGMA user_version = 18")
    conn.commit(); conn.close()

    s2 = ti.open_store("ja", path=db)
    assert s2.total_tokens() == 0, "a v18 store was reused"
    s2.reconcile([str(f)], ti.make_tokenizer("ja"))
    assert s2.bound_counts() == pieces
    s2.close()


def test_a_store_from_before_the_caption_cleaner_is_rebuilt_without_the_reading_rows(tmp_path):
    """v19 -> v20 (P1.3-1 a): an .ass file is read through the caption cleaner — a TV caption's small-type reading row
    (もんばん over 門番) is no line and no words; a v19 store counted its kana: it must be dropped and rebuilt. Pinned
    exactly: the next bump updates this knowingly."""
    assert ti.SCHEMA_VERSION == 20
    import shutil
    db = _db(tmp_path)
    f = tmp_path / "tv_captions.ass"
    shutil.copy2(os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources", "ja", "tv_captions.ass"), f)
    s = ti.open_store("ja", path=db)
    s.reconcile([str(f)], ti.make_tokenizer("ja"))
    words = {t[0] for _s, tokens in s.file_tokens(str(f)) for t in tokens}
    s.close()
    assert "門番" in words and not words & {"もんばん", "ちょうろう"}
    conn = sqlite3.connect(db)      # what a v19 store is: the version it was written with
    conn.execute("PRAGMA user_version = 19")
    conn.commit(); conn.close()
    s2 = ti.open_store("ja", path=db)
    assert s2.total_tokens() == 0, "a v19 store was reused"
    s2.close()


def test_a_files_pieces_leave_the_store_with_it(tmp_path):
    """The bound table is kept as the aggregate is: a changed file's old pieces are taken off before its new ones go
    on, and a removed file's go with it — never summed again over the whole library."""
    db = _db(tmp_path)
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    _write(a, "三年前にこの町へ来た。\n")
    _write(b, "十年ぶりに兄と会った。\n")
    s = ti.open_store("ja", path=db)
    s.reconcile([str(a), str(b)], ti.make_tokenizer("ja"))
    assert s.bound_counts() == {("年", "ネン"): 2, ("前", "マエ"): 1}
    _write(a, "年が明けて、雪が降った。\n")
    _bump_mtime(a)
    s.reconcile([str(a), str(b)], ti.make_tokenizer("ja"))
    assert s.bound_counts() == {("年", "ネン"): 1}
    s.reconcile([str(a)], ti.make_tokenizer("ja"))
    assert s.bound_counts() == {}
    assert s.conn.execute("SELECT COUNT(*) FROM bound").fetchone()[0] == 0
    s.close()


def test_concurrent_reader_sees_committed_writes(tmp_path):
    """WAL: a second connection reads the committed state; no corruption from two connections."""
    db = _db(tmp_path)
    f = tmp_path / "adv.txt"; _write(f, JA_ADVENTURE)
    writer = ti.open_store("ja", path=db)
    reader = ti.open_store("ja", path=db)          # separate connection, same DB
    assert reader.total_tokens() == 0
    writer.reconcile([str(f)], ti.make_tokenizer("ja"))
    assert reader.total_tokens() == writer.total_tokens() > 0   # reader sees the commit
    writer.close(); reader.close()


def test_concurrent_writers_serialize_without_double_apply(tmp_path):
    """Two writers (a Generate run + the background indexer) reconciling the SAME library at the
    same time must serialize — WAL + BEGIN IMMEDIATE + busy_timeout — and leave a consistent
    aggregate: never double-counted, deadlocked, or corrupt. This guards the concurrency the
    migration introduced (the background indexer writes while Generate may also be writing)."""
    import threading
    f1 = tmp_path / "a.txt"; _write(f1, JA_ADVENTURE)
    f2 = tmp_path / "b.txt"; _write(f2, JA_OTHER)
    files = [str(f1), str(f2)]

    # Reference = a single clean reconcile's exact aggregate + total.
    ref = ti.open_store("ja", path=_db(tmp_path, "ref.db"))
    ref.reconcile(files, ti.make_tokenizer("ja"))
    expected_total = ref.total_tokens()
    expected_rows = dict(ref.conn.execute("SELECT lemma||'|'||reading, count FROM aggregate").fetchall())
    ref.close()
    assert expected_total > 0

    # Two threads, each its OWN connection to one shared DB, released together for max contention.
    db = _db(tmp_path, "shared.db")
    # A timeout on the barrier, and daemon workers: if one worker fails BEFORE reaching the barrier
    # (e.g. 'database is locked' on a loaded machine), the other must not wait forever. Without
    # them it did — the join below timed out, the test failed, and then pytest itself hung at exit
    # on the still-blocked non-daemon thread.
    barrier = threading.Barrier(2, timeout=30)
    errors = []

    def worker():
        store = None
        try:
            store = ti.open_store("ja", path=db)
            tok = ti.make_tokenizer("ja")      # build before the barrier: test DB contention, not tok init
            barrier.wait()
            store.reconcile(files, tok)
        except Exception as e:                 # pragma: no cover - only on a real concurrency failure
            errors.append(repr(e))
            barrier.abort()                    # release the partner at once instead of at the timeout
        finally:
            if store is not None:
                store.close()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(2)]
    for t in threads: t.start()
    for t in threads: t.join(timeout=60)

    assert not any(t.is_alive() for t in threads), "a concurrent reconcile never finished"
    assert not errors, f"concurrent reconcile raised: {errors}"
    final = ti.open_store("ja", path=db)
    try:
        assert final.file_count() == 2
        assert final.total_tokens() == expected_total          # serialized, NOT doubled
        got = dict(final.conn.execute("SELECT lemma||'|'||reading, count FROM aggregate").fetchall())
        assert got == expected_rows                            # per-word counts consistent, no drift
    finally:
        final.close()


def test_build_signature_reads_the_retired_reinforce_as_off():
    """Chinese `reinforce` is retired (a hand list of two pairs the dictionary's cut already splits): a store
    reads "reinforce=False" whatever an old settings.json says — the string a store built as shipped holds —
    in either language."""
    assert ti.build_signature("ja", True) == ti.build_signature("ja", False) == "ja|reinforce=False"
    assert ti.build_signature("zh", True) == ti.build_signature("zh", False) == "zh|reinforce=False"


def test_reconcile_rebuilds_when_build_signature_changes(tmp_path):
    """A tokenizer-config change (the Chinese script) must invalidate the WHOLE cache: the files
    are unchanged on disk, so the (mtime,size) delta sees nothing — but their cached tokenization is
    stale. A changed build signature forces every file to be re-tokenized."""
    db = _db(tmp_path)
    f1 = tmp_path / "a.txt"; _write(f1, ZH_ADVENTURE)
    f2 = tmp_path / "b.txt"; _write(f2, ZH_ADVENTURE + "危险的旅程。")
    files = [str(f1), str(f2)]

    store = ti.open_store("zh", path=db)
    store.reconcile(files, ti.make_tokenizer("zh"), build_signature=ti.build_signature("zh", False))

    # Same signature + unchanged files -> normal delta fast-path, nothing re-tokenized.
    tok = _counting_tokenizer("zh")
    store.reconcile(files, tok, build_signature=ti.build_signature("zh", False))
    assert tok.calls == [], "same build signature + unchanged files must not re-tokenize"

    # the script flips -> different signature -> ALL files re-tokenized despite no disk change.
    tok2 = _counting_tokenizer("zh")
    store.reconcile(files, tok2, build_signature=ti.build_signature("zh", False, "s"))
    assert set(tok2.calls) == {ti._norm(str(f1)), ti._norm(str(f2))}, \
        "a script switch must re-tokenize every file (stale tokens)"
    assert store.total_tokens() > 0
    store.close()


def _write_boundaries(ja):
    """settings.json (the sandboxed one) with the Japanese sentence boundaries set to `ja`."""
    from app.path_utils import get_user_file
    with open(get_user_file("settings.json"), "w", encoding="utf-8") as handle:
        json.dump({"logic": {"sentence_boundaries": {"ja": ja}}}, handle, ensure_ascii=False)


def test_the_default_sentence_boundaries_in_any_order_keep_the_old_signature():
    """Spec I2: the user's own settings.json holds 。！？!?\\n｡ — the default's characters in another
    order (settings_manager adds any default one an old copy lacks). No suffix, so upgrading rebuilds no
    one's store; the Chinese set is untouched by the Japanese one."""
    from app import settings_manager
    default = settings_manager.DEFAULT_SETTINGS["logic"]["sentence_boundaries"]["ja"]
    assert ti.build_signature("ja") == "ja|reinforce=False"            # no settings.json: the default
    _write_boundaries("。！？!?\n｡")
    assert ti.build_signature("ja") == "ja|reinforce=False"
    assert ti.build_signature("zh", False, "s") == "zh|reinforce=False|script=s"
    _write_boundaries("。！？!?\n｡…")                                  # a learner who ends sentences at …
    edited = sorted(set(default + "…"))
    assert ti.build_signature("ja") == "ja|reinforce=False|boundaries=" + json.dumps(edited, ensure_ascii=False)
    assert "\\n" in ti.build_signature("ja") and "\n" not in ti.build_signature("ja"), "one printable line"
    assert ti.build_signature("zh", False, "s") == "zh|reinforce=False|script=s", "only the set that was edited"


def test_edited_sentence_boundaries_rebuild_the_store_and_undoing_the_edit_rebuilds_it_again(tmp_path):
    """The boundaries decide where every file splits. The files are unchanged on disk, so the
    (mtime, size) delta sees nothing — but every cached sentence is stale, so an edit re-tokenizes
    every file, once, and so does taking it back."""
    db = _db(tmp_path)
    f1 = tmp_path / "a.txt"; _write(f1, JA_ADVENTURE)
    f2 = tmp_path / "b.txt"; _write(f2, JA_OTHER)
    files = [str(f1), str(f2)]
    store = ti.open_store("ja", path=db)
    store.reconcile(files, ti.make_tokenizer("ja"), build_signature=ti.build_signature("ja"))

    _write_boundaries("。！？!?\n｡…")
    tok = _counting_tokenizer("ja")
    store.reconcile(files, tok, build_signature=ti.build_signature("ja"))
    assert set(tok.calls) == {ti._norm(str(f1)), ti._norm(str(f2))}, "an edited set re-tokenizes every file"
    tok2 = _counting_tokenizer("ja")
    store.reconcile(files, tok2, build_signature=ti.build_signature("ja"))
    assert tok2.calls == [], "the same edited set, unchanged files: nothing to do"

    _write_boundaries("。！？!?\n｡")
    tok3 = _counting_tokenizer("ja")
    store.reconcile(files, tok3, build_signature=ti.build_signature("ja"))
    assert set(tok3.calls) == {ti._norm(str(f1)), ti._norm(str(f2))}, "back to the default: rebuilt again"
    store.close()


def test_a_settings_file_that_cannot_be_read_keeps_the_old_signature(monkeypatch):
    """The signature is asked for on every indexer check: a settings read that fails leaves the
    signature as it was, never an error."""
    from app import settings_manager

    def broken():
        raise OSError("settings.json is locked")

    monkeypatch.setattr(settings_manager, "load_settings", broken)
    assert ti.build_signature("ja") == "ja|reinforce=False"
    assert ti.build_signature("zh", True, "t") == "zh|reinforce=False|script=t"     # reinforce is retired


def test_known_words_cache_reuse_and_invalidation(tmp_path):
    """#1: the known-words cache is reused when KnownWord.json is unchanged, and invalidated on
    any edit OR deletion (so a change to your known words is always reflected)."""
    kw = tmp_path / "KnownWord.json"
    kw.write_text('{"words":[]}', encoding="utf-8")
    store = ti.open_store("ja", path=_db(tmp_path))

    sig1 = ti.known_signature(str(kw))
    assert store.get_cached_known(sig1) is None                 # nothing cached yet
    store.set_cached_known(sig1, {("冒険", "ボウケン")}, {"冒険"})
    assert store.get_cached_known(sig1) == ({("冒険", "ボウケン")}, {"冒険"})   # reused, exact

    # Edit -> new (mtime,size) -> different signature -> cache misses.
    kw.write_text('{"words":[{"dictForm":"猫","knownStatus":"KNOWN"}]}', encoding="utf-8")
    _bump_mtime(kw)
    sig2 = ti.known_signature(str(kw))
    assert sig2 != sig1 and store.get_cached_known(sig2) is None

    # Delete -> a distinct 'missing' signature -> cache misses (differs from any 'exists' sig).
    kw.unlink()
    sig3 = ti.known_signature(str(kw))
    assert sig3 != sig1 and sig3 != sig2 and store.get_cached_known(sig3) is None
    store.close()


def test_ppm_and_coverage_helpers():
    assert ti.to_ppm(10, 1_000_000) == 10.0
    assert ti.to_ppm(1, 615_221) == pytest.approx(1.625, abs=1e-2)
    assert ti.to_ppm(5, 0) == 0.0
    assert ti.coverage_percent(95, 100) == 95.0
    assert ti.coverage_percent(0, 0) == 0.0


def test_a_migrated_chinese_set_keeps_the_default_signature():
    """A saved settings.json still holding the old Chinese set (…… and ；ending sentences) loads as today's default
    (settings_manager), so its store's signature carries no boundaries suffix: the upgrade's SCHEMA bump rebuilds it
    once, and nothing rebuilds it again."""
    from app.path_utils import get_user_file
    with open(get_user_file("settings.json"), "w", encoding="utf-8") as handle:
        json.dump({"logic": {"sentence_boundaries": {"zh": "。！？!?\n；;……｡"}}}, handle, ensure_ascii=False)
    assert ti.build_signature("zh") == "zh|reinforce=False"
    with open(get_user_file("settings.json"), "w", encoding="utf-8") as handle:
        json.dump({"logic": {"sentence_boundaries": {"zh": "。！？!?\n；;……｡．"}}}, handle, ensure_ascii=False)
    assert ti.build_signature("zh").startswith("zh|reinforce=False|boundaries="), "a hand edit is the user's own set"


def test_has_tokens_is_total_tokens_above_zero(tmp_path):
    """The Rarity slider asks only whether the store holds a token before it counts (`preview_frequencies`): the same
    answer as summing every file's total — none for an empty store or one holding only empty files."""
    store = ti.open_store("ja", path=_db(tmp_path))
    try:
        assert store.has_tokens() is False and store.total_tokens() == 0
        empty, words = tmp_path / "empty.txt", tmp_path / "adventure.txt"
        _write(empty, "")
        store.reconcile([str(empty)], ti.make_tokenizer("ja"))
        assert store.file_count() == 1 and store.has_tokens() is False and store.total_tokens() == 0
        assert ti.preview_frequencies(store, "ja", str(tmp_path)) is None, "no token: no numbers"
        _write(words, JA_ADVENTURE)
        store.reconcile([str(empty), str(words)], ti.make_tokenizer("ja"))
        assert store.has_tokens() is True and store.total_tokens() > 0
    finally:
        store.close()


def test_the_known_cache_is_parsed_once_and_each_caller_gets_sets_of_its_own(tmp_path, monkeypatch):
    """Every slider refresh, and the dashboard's check before it launches the indexer, read the cached known words:
    they are parsed again only when the cached values change. A caller changing the sets it got changes nothing for
    the next caller."""
    store = ti.open_store("ja", path=_db(tmp_path))
    try:
        signature = ti.known_signature(str(tmp_path / "KnownWord.json"))
        store.set_cached_known(signature, {("学校", "ガッコウ"), ("先生", "センセイ")}, {"学校", "先生"})
        first = store.get_cached_known(signature)
        assert first == ({("学校", "ガッコウ"), ("先生", "センセイ")}, {"学校", "先生"})
        first[0].add(("冒険", "ボウケン"))
        first[1].clear()
        parsed = []
        real_loads = ti.json.loads
        known = (store.get_meta("known_tuples"), store.get_meta("known_lemmas"))
        monkeypatch.setattr(ti.json, "loads", lambda text, *a, **k: parsed.append(text) or real_loads(text, *a, **k))
        assert store.get_cached_known(signature) == ({("学校", "ガッコウ"), ("先生", "センセイ")}, {"学校", "先生"})
        assert not set(known) & set(parsed), "the same values: not parsed again"
        store.set_cached_known(signature, {("冒険", "ボウケン")}, {"冒険"})
        assert store.get_cached_known(signature) == ({("冒険", "ボウケン")}, {"冒険"}), "new values are read"
        assert {store.get_meta("known_tuples"), store.get_meta("known_lemmas")} <= set(parsed)
        _write(tmp_path / "KnownWord.json", json.dumps({"words": []}))
        changed = ti.known_signature(str(tmp_path / "KnownWord.json"))
        assert store.get_cached_known(changed) is None, "the file changed: no cache"
        store.set_meta("known_tuples", "not json")
        assert store.get_cached_known(signature) is None, "a value that won't read: no cache, as before"
    finally:
        store.close()


def test_prepare_preview_decodes_ahead_and_changes_no_number(tmp_path, monkeypatch):
    """The dashboard decodes, in the background as its window opens, what the slider's first refresh reads besides the
    store — the compound table, the one-kanji words, KnownWord.json's ignored entries (`prepare_preview`). The numbers
    are the same with it or without; it never raises (no user files, Chinese, a table that won't read)."""
    from app import analyzer
    uf = tmp_path / "User Files" / "ja"
    uf.mkdir(parents=True)
    (uf / "KnownWord.json").write_text(json.dumps({"words": [
        {"dictForm": "冒険", "knownStatus": "IGNORED"}, {"dictForm": "今夜", "knownStatus": "KNOWN"}]},
        ensure_ascii=False), encoding="utf-8")
    path = tmp_path / "adventure.txt"
    _write(path, JA_ADVENTURE + JA_OTHER)
    store = ti.open_store("ja", path=_db(tmp_path))
    try:
        store.reconcile([str(path)], ti.make_tokenizer("ja"))
        before = ti.preview_frequencies(store, "ja", str(uf))
        ti._IGNORED_ENTRIES.clear()
        ti.prepare_preview("ja", str(uf))
        assert ti._IGNORED_ENTRIES[os.path.join(str(uf), "KnownWord.json")][1] == ["冒険"], "read ahead"
        assert "compound_parts" in analyzer._MERGED, "the compound table decoded"
        assert ti.preview_frequencies(store, "ja", str(uf)) == before
    finally:
        store.close()
    ti.prepare_preview("ja", str(tmp_path / "missing"))
    ti.prepare_preview("zh", str(tmp_path / "missing"))
    monkeypatch.setattr(analyzer, "compound_parts", lambda: 1 / 0)
    ti.prepare_preview("ja", str(uf))
