"""Recency reinforcement in example-sentence selection.

All else equal (same i+1 cost, same length), a word's example sentence should be the one whose OTHER
words you met recently — reinforcing what you just studied instead of vocabulary from months ago.

The fixture is built so the competing sentences are IDENTICAL in every pre-existing criterion:
same length, same structure, and every token except one shared across all of them. The only thing
that separates them is WHEN the learner met that one differing word. If recency is off, the sort is
stable and encounter order wins; if it's on, the recently-met word wins.
"""

import json
from unittest.mock import patch

import pandas as pd
import pytest

from app import analyzer

# One file per "episode". 廃墟 is met in ep01 (long ago), 森 in ep02, 灯台 in ep06 (recent).
# ep07 introduces the target 遭遇 in three sentences that differ ONLY by which of those it reuses.
EPISODES = {
    "ep01.txt": "廃墟を歩いた。廃墟は静かだ。廃墟が見える。廃墟に入った。",
    "ep02.txt": "森を歩いた。森は深い。森が広がる。森に入った。",
    "ep03.txt": "河川を眺めた。河川は広い。河川が流れる。河川に沿った。",
    "ep04.txt": "山脈を越えた。山脈は高い。山脈が続く。山脈に登った。",
    "ep05.txt": "青空を見上げた。青空は青い。青空が広がる。青空に雲がある。",
    "ep06.txt": "灯台を見た。灯台は白い。灯台が光る。灯台に登った。",
    "ep07.txt": "森で遭遇した。廃墟で遭遇した。灯台で遭遇した。",
}

FIRST = "森で遭遇した。"      # the word's own/original sentence — always pinned to Context 1
OLD = "廃墟で遭遇した。"      # reuses a word met 6 files ago
RECENT = "灯台で遭遇した。"   # reuses a word met 1 file ago


@pytest.fixture
def env(tmp_path):
    uf = tmp_path / "User Files" / "ja"; uf.mkdir(parents=True)
    high = tmp_path / "data" / "ja" / "HighPriority"; high.mkdir(parents=True)
    results = tmp_path / "results"; results.mkdir()
    (uf / "KnownWord.json").write_text(json.dumps({"words": []}), encoding="utf-8")
    for name, text in EPISODES.items():
        (high / name).write_text(text, encoding="utf-8")

    def guf(path): return str(tmp_path / path)
    def gdp(lang=None): return str(tmp_path / "data" / lang) if lang else str(tmp_path / "data")
    def gufp(lang=None): return str(tmp_path / "User Files" / lang) if lang else str(tmp_path / "User Files")
    return {"root": tmp_path, "results": results, "guf": guf, "gdp": gdp, "gufp": gufp}


def _run(env):
    """Run a full analysis and return the priority CSV as a DataFrame."""
    results = env["results"]
    csv = results / "priority_learning_list.csv"
    if csv.exists():
        csv.unlink()
    with patch("app.analyzer.get_user_file", side_effect=env["guf"]), \
         patch("app.analyzer.get_data_path", side_effect=env["gdp"]), \
         patch("app.analyzer.get_user_files_path", side_effect=env["gufp"]), \
         patch("app.analyzer.RESULTS_DIR", str(results)), \
         patch("app.analyzer.OUTPUT_CSV", str(csv)), \
         patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
         patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
         patch("sys.argv", ["analyzer.py", "--language", "ja", "--min-freq", "1"]):
        analyzer.main()
    return pd.read_csv(csv)


def _contexts(df, word):
    row = df[df["Word"] == word]
    assert not row.empty, f"'{word}' missing from the priority list"
    r = row.iloc[0]
    return [str(r.get(f"Context {i}", "") or "").strip() for i in (1, 2, 3)]


def test_recency_promotes_the_sentence_reusing_a_recently_met_word(env):
    """Default (recency_files=1): the sentence reusing 灯台 (met one file earlier) outranks the one
    reusing 廃墟 (met six files earlier), even though both are equal on cost and length."""
    ctx = _contexts(_run(env), "遭遇")
    assert ctx[0] == FIRST, "Context 1 stays the word's own first sentence"
    assert ctx[1] == RECENT, f"the recently-met co-word should win the tiebreak, got {ctx[1]!r}"
    assert ctx[2] == OLD


def test_recency_disabled_falls_back_to_encounter_order(env):
    """recency_files=-1 turns the tiebreaker off — the stable sort then keeps encounter order, which
    is exactly the behaviour before this feature. Proves the assertion above is caused by recency."""
    with patch.dict(analyzer.LOGIC["context"], {"recency_files": -1}):
        ctx = _contexts(_run(env), "遭遇")
    assert ctx[0] == FIRST
    assert ctx[1] == OLD, "without recency the earlier-encountered sentence keeps its place"
    assert ctx[2] == RECENT


def test_recency_window_of_zero_means_same_file_only(env):
    """recency_files=0 counts only co-words first met in the SAME file. Neither competitor qualifies
    (both were met in earlier files), so the tiebreak goes inert and encounter order stands."""
    with patch.dict(analyzer.LOGIC["context"], {"recency_files": 0}):
        ctx = _contexts(_run(env), "遭遇")
    assert ctx[1] == OLD


def test_recency_is_only_a_tiebreaker_never_beats_i_plus_one(env, tmp_path):
    """A recency hit must NOT promote a sentence that is harder (more unknown words). Cost is sorted
    before recency, so the cleaner sentence wins even with no recent reinforcement at all."""
    high = tmp_path / "data" / "ja" / "HighPriority"
    # ep07 gains a sentence that reuses the RECENT word but drags in two never-seen words.
    (high / "ep07.txt").write_text(
        "森で遭遇した。灯台と螺旋階段で怪物に遭遇した。", encoding="utf-8")
    ctx = _contexts(_run(env), "遭遇")
    assert ctx[0] == FIRST, "the clean i+1 sentence must stay first despite the other's recency hit"
    assert "螺旋階段" not in ctx[0]


def test_recency_does_not_change_word_selection_or_counts(env):
    """Guard the blast radius: this is a sentence-ordering change only. Which words are selected,
    their scores and their occurrence counts must be identical with recency on and off."""
    on = _run(env)
    with patch.dict(analyzer.LOGIC["context"], {"recency_files": -1}):
        off = _run(env)

    cols = ["Word", "Reading", "Score", "Occurrences", "Count (High)", "Count (Low)", "Count (Goal)"]
    pd.testing.assert_frame_equal(
        on[cols].sort_values("Word").reset_index(drop=True),
        off[cols].sort_values("Word").reset_index(drop=True),
        check_dtype=False,
    )
