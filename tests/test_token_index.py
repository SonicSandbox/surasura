"""Tests for the persistent, incremental token index (app/token_index.py).

These use REAL Japanese/Chinese text (per testing.md) — not dummy ASCII — because the whole
point of the index is to mirror what the real tokenizer counts. Reconciliation logic (delta
detection, add/remove, out-of-band edits) is verified with a call-counting wrapper around the
real tokenizer so we can assert *which* files got re-tokenized.

Edge cases covered: success path, empty library, changed/added/removed files, out-of-band edits
(files touched outside any importer), known-word changes re-filtering without re-tokenizing,
single-char handling (ja vs zh), encoding/CRLF, and persistence round-trip.
"""

import os
import json
import pytest

from app import token_index as ti

# --- Real linguistic fixtures (kept small & self-contained) --------------------------------- #
# '冒険' (adventure) repeats heavily -> a natural high-frequency word to assert on.
JA_ADVENTURE = (
    "冒険だ。\n冒険する？\n今夜は冒険。\n彼は毎日冒険に出かけます。\n"
    "私たちは新しい冒険を求めている。\n冒険は危険だが、価値がある。\n冒険！\n"
)
# Distinct vocab (天気/猫/犬/公園/散歩) that does NOT overlap with the adventure file — lets us
# tell deltas apart cleanly.
JA_OTHER = (
    "今日はいい天気です。\n猫と犬が好きです。\n公園を散歩しました。\n音楽を聞くのが趣味です。\n"
)
ZH_ADVENTURE = (
    "冒险。\n去冒险吗？\n冒险很难。\n我们需要去寻找新的冒险。\n危险往往是冒险的一部分。\n冒险！\n"
)


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _counting_tokenizer(language):
    """Real tokenizer wrapped to record which paths it was asked to tokenize."""
    inner = ti.make_tokenizer(language)
    calls = []

    def wrapped(path):
        calls.append(ti._norm(path))
        return inner(path)

    wrapped.calls = calls
    return wrapped


def _bump_mtime(path, seconds=10):
    """Force a distinctly newer mtime so a rewrite is unambiguously 'changed' even if a fast
    test rewrite happened within the filesystem's mtime resolution."""
    now = os.stat(path).st_mtime
    os.utime(path, (now + seconds, now + seconds))


def _has(index, lemma):
    return any(k.startswith(lemma + "|") for k in index["aggregate"])


# --------------------------------------------------------------------------- #
def test_reconcile_builds_index_from_real_ja(tmp_path):
    """Happy path: a real ja file produces a non-empty aggregate whose counts sum to total."""
    f = tmp_path / "adv.txt"
    _write(f, JA_ADVENTURE)

    tok = _counting_tokenizer("ja")
    index = ti.reconcile([str(f)], tok)

    assert index["total_tokens"] > 0
    assert _has(index, "冒険"), "the repeated word should be indexed"
    # Invariant: the running aggregate must equal the sum of per-file totals.
    assert sum(index["aggregate"].values()) == index["total_tokens"]
    assert len(tok.calls) == 1


def test_reconcile_is_idempotent_no_retokenize(tmp_path):
    """Re-running with unchanged files must tokenize NOTHING (the core performance guarantee)."""
    f = tmp_path / "adv.txt"
    _write(f, JA_ADVENTURE)
    tok = _counting_tokenizer("ja")

    index = ti.reconcile([str(f)], tok)
    first_total = index["total_tokens"]
    tok.calls.clear()

    ti.reconcile([str(f)], tok, index)      # nothing changed on disk
    assert tok.calls == [], "unchanged file must not be re-tokenized"
    assert index["total_tokens"] == first_total


def test_changed_file_retokenizes_only_that_file(tmp_path):
    """Editing one file re-tokenizes only it; the other file is reused."""
    a = tmp_path / "a.txt"; _write(a, JA_ADVENTURE)
    b = tmp_path / "b.txt"; _write(b, JA_OTHER)
    tok = _counting_tokenizer("ja")
    index = ti.reconcile([str(a), str(b)], tok)
    assert _has(index, "天気")
    tok.calls.clear()

    _write(b, JA_OTHER + "新しい文章を追加しました。\n")  # change b only
    _bump_mtime(b)
    ti.reconcile([str(a), str(b)], tok, index)

    assert tok.calls == [ti._norm(str(b))], "only the edited file should re-tokenize"
    assert sum(index["aggregate"].values()) == index["total_tokens"]


def test_removed_file_is_subtracted(tmp_path):
    """A file that disappears has its counts subtracted from the aggregate and totals."""
    a = tmp_path / "a.txt"; _write(a, JA_ADVENTURE)
    b = tmp_path / "b.txt"; _write(b, JA_OTHER)
    tok = _counting_tokenizer("ja")
    index = ti.reconcile([str(a), str(b)], tok)
    assert _has(index, "天気")  # unique to b
    total_with_b = index["total_tokens"]

    b.unlink()
    tok.calls.clear()
    ti.reconcile([str(a)], tok, index)   # b no longer listed

    assert tok.calls == [], "removal must not require tokenizing anything"
    assert not _has(index, "天気"), "b's unique words should be gone"
    assert index["total_tokens"] < total_with_b
    assert sum(index["aggregate"].values()) == index["total_tokens"]


def test_added_file_only_tokenizes_new(tmp_path):
    """Adding a file tokenizes just the newcomer and grows the aggregate."""
    a = tmp_path / "a.txt"; _write(a, JA_ADVENTURE)
    tok = _counting_tokenizer("ja")
    index = ti.reconcile([str(a)], tok)
    base_total = index["total_tokens"]
    tok.calls.clear()

    b = tmp_path / "b.txt"; _write(b, JA_OTHER)
    ti.reconcile([str(a), str(b)], tok, index)

    assert tok.calls == [ti._norm(str(b))]
    assert _has(index, "天気")
    assert index["total_tokens"] > base_total


def test_out_of_band_edit_detected_by_signature(tmp_path):
    """A file edited directly on disk (never via the content importer) is still caught, because
    reconcile compares (mtime, size) — not UI events. This is the guardrail."""
    f = tmp_path / "adv.txt"; _write(f, JA_ADVENTURE)
    tok = _counting_tokenizer("ja")
    index = ti.reconcile([str(f)], tok)
    assert not _has(index, "天気")
    tok.calls.clear()

    # Simulate a manual edit: different content (and size), bumped mtime — no importer involved.
    _write(f, JA_OTHER)
    _bump_mtime(f)
    ti.reconcile([str(f)], tok, index)

    assert tok.calls == [ti._norm(str(f))], "out-of-band edit must be re-tokenized"
    assert _has(index, "天気") and not _has(index, "冒険")


def test_known_word_change_refilters_without_retokenizing(tmp_path):
    """The read layer applies the known filter over the raw aggregate — so a known-word change
    re-runs only this cheap pass, never the tokenizer."""
    f = tmp_path / "adv.txt"; _write(f, JA_ADVENTURE)
    index = ti.reconcile([str(f)], ti.make_tokenizer("ja"))

    before = ti.unknown_frequencies(index, skip_singles=True)
    unknown_words = {ti.split_key(k)[0] for k, _ in before["unknown"]}
    assert "冒険" in unknown_words

    # Mark '冒険' known — no re-tokenization, just a re-filter of the SAME index object.
    after = ti.unknown_frequencies(index, known_lemmas={"冒険"}, skip_singles=True)
    after_words = {ti.split_key(k)[0] for k, _ in after["unknown"]}
    assert "冒険" not in after_words
    assert after["known_tokens"] > before["known_tokens"]
    assert after["total_tokens"] == before["total_tokens"], "total library size is unaffected"


def test_skip_singles_moves_single_chars_to_baseline_ja(tmp_path):
    """For ja, single-char tokens (particles) are baseline, not learnable words — skip_singles
    must exclude them from 'unknown' while still counting them toward the library total."""
    f = tmp_path / "adv.txt"; _write(f, JA_ADVENTURE)
    index = ti.reconcile([str(f)], ti.make_tokenizer("ja"))

    with_singles = ti.unknown_frequencies(index, skip_singles=False)
    without = ti.unknown_frequencies(index, skip_singles=True)

    assert any(len(ti.split_key(k)[0]) == 1 for k, _ in with_singles["unknown"]), \
        "the ja text should contain single-char tokens"
    assert all(len(ti.split_key(k)[0]) > 1 for k, _ in without["unknown"]), \
        "skip_singles must drop every single-char word"
    assert without["known_tokens"] >= with_singles["known_tokens"]
    assert without["total_tokens"] == with_singles["total_tokens"]


def test_reconcile_zh_real_text(tmp_path):
    """Chinese path works end to end with the real Jieba tokenizer."""
    f = tmp_path / "adv_zh.txt"; _write(f, ZH_ADVENTURE)
    index = ti.reconcile([str(f)], ti.make_tokenizer("zh"))
    assert index["total_tokens"] > 0
    assert _has(index, "冒险")
    assert sum(index["aggregate"].values()) == index["total_tokens"]


def test_empty_library(tmp_path):
    """No files -> empty, valid index; read layer returns nothing without crashing."""
    tok = _counting_tokenizer("ja")
    index = ti.reconcile([], tok)
    assert index["total_tokens"] == 0
    assert index["aggregate"] == {}
    assert tok.calls == []

    res = ti.unknown_frequencies(index, skip_singles=True)
    assert res["unknown"] == []
    assert res["total_tokens"] == 0
    assert ti.coverage_percent(res["known_tokens"], res["total_tokens"]) == 0


def test_crlf_and_mixed_scripts_index_cleanly(tmp_path):
    """CRLF line endings and Latin/digit noise mixed into ja text must not break indexing, and
    non-target tokens must not inflate the totals."""
    f = tmp_path / "mixed.txt"
    with open(f, "w", encoding="utf-8", newline="") as fh:
        fh.write("冒険 ABC123 だ。\r\n今夜は冒険。\r\n")
    index = ti.reconcile([str(f)], ti.make_tokenizer("ja"))
    assert _has(index, "冒険")
    assert not _has(index, "ABC123"), "ASCII-only tokens must be filtered out"


def test_persistence_roundtrip(tmp_path):
    """save_index -> load_index preserves the aggregate, totals and file signatures; a version
    mismatch discards the cache and rebuilds empty."""
    f = tmp_path / "adv.txt"; _write(f, JA_ADVENTURE)
    index = ti.reconcile([str(f)], ti.make_tokenizer("ja"))

    path = tmp_path / "token_index_ja.json"
    ti.save_index(index, str(path))
    loaded = ti.load_index(str(path))
    assert loaded["total_tokens"] == index["total_tokens"]
    assert loaded["aggregate"] == index["aggregate"]
    assert set(loaded["files"].keys()) == set(index["files"].keys())

    # Corrupt the version -> discard & rebuild empty (never crash a run).
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = 999
    path.write_text(json.dumps(data), encoding="utf-8")
    assert ti.load_index(str(path)) == ti.empty_index()


def test_build_index_from_precomputed_counts(tmp_path):
    """build_index seeds an index from already-tokenized per-file counts (no tokenizer), reading
    signatures from disk — the 'seed for free from a run' path."""
    a = tmp_path / "a.txt"; _write(a, JA_ADVENTURE)
    b = tmp_path / "b.txt"; _write(b, JA_OTHER)
    per_file = {
        str(a): {"冒険|ボウケン": 5, "危険|キケン": 1},
        str(b): {"天気|テンキ": 2},
    }
    index = ti.build_index(per_file)
    assert index["total_tokens"] == 8
    assert index["aggregate"]["冒険|ボウケン"] == 5
    assert index["aggregate"]["天気|テンキ"] == 2
    assert sum(index["aggregate"].values()) == index["total_tokens"]
    # Signatures were captured, so a subsequent reconcile with unchanged files re-tokenizes nothing.
    tok = _counting_tokenizer("ja")
    ti.reconcile([str(a), str(b)], tok, index)
    assert tok.calls == []


def test_ppm_and_coverage_helpers():
    """The scale-invariant density + coverage math."""
    assert ti.to_ppm(10, 1_000_000) == 10.0
    assert ti.to_ppm(1, 615_221) == pytest.approx(1.625, abs=1e-2)
    assert ti.to_ppm(5, 0) == 0.0          # no divide-by-zero on an empty library
    assert ti.coverage_percent(95, 100) == 95.0
    assert ti.coverage_percent(0, 0) == 0.0
