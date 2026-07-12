"""End-to-end check that the analyzer applies density-band selection by DEFAULT (min_freq retired).

Uses real Japanese text where one word recurs and the rest are one-offs, and verifies:
  - default run (no args)   -> the default band drops one-off words,
  - --min-freq 1 (override) -> every word is kept (the legacy raw-count escape hatch).

This guards the Phase 2b wiring (analyzer reads logic.selection and applies band_floor_count).
"""

import json
import pytest
import pandas as pd
from unittest.mock import patch

from app import analyzer

# '冒険' recurs (>=3x -> clears the default floor); '林檎' and friends appear once (one-offs).
JA = "冒険。冒険する。冒険だ。林檎を食べる。"


@pytest.fixture
def env(tmp_path):
    uf = tmp_path / "User Files" / "ja"; uf.mkdir(parents=True)
    high = tmp_path / "data" / "ja" / "HighPriority"; high.mkdir(parents=True)
    results = tmp_path / "results"; results.mkdir()
    (uf / "KnownWord.json").write_text(json.dumps({"words": []}), encoding="utf-8")
    (high / "t.txt").write_text(JA, encoding="utf-8")

    def guf(path): return str(tmp_path / path)
    def gdp(lang=None): return str(tmp_path / "data" / lang) if lang else str(tmp_path / "data")
    def gufp(lang=None): return str(tmp_path / "User Files" / lang) if lang else str(tmp_path / "User Files")
    return {"results": results, "guf": guf, "gdp": gdp, "gufp": gufp}


def _run(env, extra_args):
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
         patch("sys.argv", ["analyzer.py", "--language", "ja"] + extra_args):
        analyzer.main()
    if not csv.exists():
        return []
    return pd.read_csv(csv)["Word"].tolist()


def test_default_band_drops_one_offs(env):
    """No selection args -> the default band excludes single-occurrence words."""
    words = _run(env, [])
    assert "冒険" in words, "a recurring word must survive the default band"
    assert "林檎" not in words, "a one-off word must be dropped by the default band floor"


def test_min_freq_override_keeps_everything(env):
    """--min-freq 1 is the retained raw-count override: it bypasses the band and keeps one-offs."""
    words = _run(env, ["--min-freq", "1"])
    assert "冒険" in words and "林檎" in words


def test_run_persists_token_index(env):
    """A run seeds the token index (results/token_index_ja.json) so the preview needs no re-run."""
    import json as _json
    from app import token_index as ti
    _run(env, ["--min-freq", "1"])
    idx_file = env["results"] / "token_index_ja.json"
    assert idx_file.exists(), "the run should persist a token index"
    index = _json.loads(idx_file.read_text(encoding="utf-8"))
    # The recurring word is captured; the index round-trips through the read layer.
    assert any(k.startswith("冒険|") for k in index["aggregate"])
    freqs = ti.unknown_frequencies(index, skip_singles=True)
    assert freqs["total_tokens"] > 0
