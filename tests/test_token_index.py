"""Tests for the SQLite token store (app/token_index.py).

Real Japanese/Chinese text (per testing.md), not dummy ASCII. Reconciliation (delta detection,
add/remove, out-of-band edits) is verified with a call-counting wrapper around the real tokenizer
so we can assert *which* files got re-tokenized. Plus SQLite-specific edges: transaction rollback,
corruption self-heal, persistence across reopen, and the cheap needs_reconcile pre-check.

Every store is opened with an explicit temp `path` so tests never touch the real %APPDATA%.
"""

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
    f = tmp_path / "adv.txt"; _write(f, JA_ADVENTURE)
    store = ti.open_store("ja", path=_db(tmp_path))
    store.reconcile([str(f)], ti.make_tokenizer("ja"))

    with_s = store.unknown_frequencies(skip_singles=False)
    without = store.unknown_frequencies(skip_singles=True)
    assert any(len(ti.split_key(k)[0]) == 1 for k, _ in with_s["unknown"])
    assert all(len(ti.split_key(k)[0]) > 1 for k, _ in without["unknown"])
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
    barrier = threading.Barrier(2)
    errors = []

    def worker():
        try:
            store = ti.open_store("ja", path=db)
            tok = ti.make_tokenizer("ja")      # build before the barrier: test DB contention, not tok init
            barrier.wait()
            store.reconcile(files, tok)
            store.close()
        except Exception as e:                 # pragma: no cover - only on a real concurrency failure
            errors.append(repr(e))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads: t.start()
    for t in threads: t.join(timeout=30)

    assert not errors, f"concurrent reconcile raised: {errors}"
    final = ti.open_store("ja", path=db)
    try:
        assert final.file_count() == 2
        assert final.total_tokens() == expected_total          # serialized, NOT doubled
        got = dict(final.conn.execute("SELECT lemma||'|'||reading, count FROM aggregate").fetchall())
        assert got == expected_rows                            # per-word counts consistent, no drift
    finally:
        final.close()


def test_build_signature_normalizes_ja_and_reflects_zh_reinforce():
    """ja tokenization is fixed, so its build signature must IGNORE reinforce (else the analyzer and
    the background indexer, deriving it slightly differently, would thrash the ja store). zh must
    reflect reinforce so a toggle invalidates."""
    assert ti.build_signature("ja", True) == ti.build_signature("ja", False)
    assert ti.build_signature("zh", True) != ti.build_signature("zh", False)


def test_reconcile_rebuilds_when_build_signature_changes(tmp_path):
    """A tokenizer-config change (Chinese `reinforce`) must invalidate the WHOLE cache: the files
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

    # reinforce flips -> different signature -> ALL files re-tokenized despite no disk change.
    tok2 = _counting_tokenizer("zh")
    store.reconcile(files, tok2, build_signature=ti.build_signature("zh", True))
    assert set(tok2.calls) == {ti._norm(str(f1)), ti._norm(str(f2))}, \
        "a reinforce toggle must re-tokenize every file (stale segmentation)"
    assert store.total_tokens() > 0
    store.close()


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
