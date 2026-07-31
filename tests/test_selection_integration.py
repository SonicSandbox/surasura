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
    return {"root": tmp_path, "results": results, "guf": guf, "gdp": gdp, "gufp": gufp}


def _run(env, extra_args, clear=True):
    results = env["results"]
    csv = results / "priority_learning_list.csv"
    if clear and csv.exists():
        csv.unlink()
    # (The SQLite token store is isolated to a temp dir by the autouse conftest fixture.)
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


def test_generate_output_identical_warm_vs_cold_store(env):
    """Determinism guard: reusing cached tokens (warm store) yields byte-identical output to a
    cold run that tokenizes from scratch."""
    csv = env["results"] / "priority_learning_list.csv"
    _run(env, ["--min-freq", "1"])           # cold store -> tokenizes every file
    cold = csv.read_text(encoding="utf-8-sig")
    _run(env, ["--min-freq", "1"])           # warm store -> files unchanged -> reuses cached tokens
    warm = csv.read_text(encoding="utf-8-sig")
    assert cold == warm and cold.strip()


def test_run_signature_skips_unchanged_and_reruns_on_change(env):
    """#2: an identical re-run is skipped (outputs reused, not rewritten); a content change reruns."""
    import time
    csv = env["results"] / "priority_learning_list.csv"
    _run(env, [])                          # first run generates outputs + stores the signature
    m1 = csv.stat().st_mtime
    time.sleep(0.05)
    _run(env, [], clear=False)             # nothing changed + outputs present -> SKIP
    assert csv.stat().st_mtime == m1, "unchanged re-run should be skipped (output reused)"
    # Change a content file -> signature differs -> must re-run (rewrite the CSV).
    time.sleep(0.05)
    (env["root"] / "data" / "ja" / "HighPriority" / "t.txt").write_text(
        JA + "\n新しい冒険の物語が始まる。", encoding="utf-8")
    _run(env, [], clear=False)
    assert csv.stat().st_mtime != m1, "a content change must force a re-run"


def test_engine_revision_bump_forces_rerun_of_unchanged_inputs(env):
    """An engine change that alters OUTPUT (new columns, different sentence picking) must invalidate
    the stored signature even though every input is byte-identical.

    Before ENGINE_REVISION the only engine component was __version__, which moves once per RELEASE —
    so during development an output-changing edit left the stored signature matching and the analyzer
    happily served the report from BEFORE the change."""
    import time
    csv = env["results"] / "priority_learning_list.csv"
    _run(env, [])
    m1 = csv.stat().st_mtime
    time.sleep(0.05)
    _run(env, [], clear=False)
    assert csv.stat().st_mtime == m1, "sanity: unchanged inputs are skipped"

    time.sleep(0.05)
    with patch("app.analyzer.ENGINE_REVISION", analyzer.ENGINE_REVISION + 1):
        _run(env, [], clear=False)
    assert csv.stat().st_mtime != m1, "an ENGINE_REVISION bump must force a real re-run"


def test_render_signature_covers_everything_injected_into_the_report(env):
    """Anything static_html_generator INJECTS must be in the render signature, or editing it leaves
    the report stale. words_per_day / show_words_per_day were injected but unlisted, so the
    'At N words a day...' estimate kept showing the old number."""
    import types
    args = types.SimpleNamespace(theme="Dark Flow", zen_limit=0)

    def sig(**settings):
        with patch("app.settings_manager.load_settings", return_value=settings):
            return analyzer.compute_render_signature(args)

    base = sig(words_per_day=5, show_words_per_day=True, source_display="off")
    assert sig(words_per_day=20, show_words_per_day=True, source_display="off") != base, \
        "changing Words Per Day must force a re-render"
    assert sig(words_per_day=5, show_words_per_day=False, source_display="off") != base, \
        "toggling 'Show Target Days' must force a re-render"
    assert sig(words_per_day=5, show_words_per_day=True, source_display="icon") != base, \
        "changing the source badge must force a re-render"
    assert sig(words_per_day=5, show_words_per_day=True, source_display="off") == base, \
        "identical presentation must NOT re-render"


def test_run_signature_reruns_on_settings_change(env):
    """#2: a change to settings.json (GUI or manual edit) must force a re-run, not reuse."""
    import time, json as _json
    # env["guf"]("settings.json") maps to env["root"]/settings.json (what the analyzer reads).
    settings_file = env["root"] / "settings.json"
    settings_file.write_text(_json.dumps({"logic": {"selection": {"band": "occasional"}}}), encoding="utf-8")
    csv = env["results"] / "priority_learning_list.csv"
    _run(env, [])
    m1 = csv.stat().st_mtime
    time.sleep(0.05)
    _run(env, [], clear=False)
    assert csv.stat().st_mtime == m1                  # unchanged -> skipped
    time.sleep(0.05)
    settings_file.write_text(_json.dumps({"logic": {"selection": {"band": "rare"}}}), encoding="utf-8")
    _run(env, [], clear=False)
    assert csv.stat().st_mtime != m1, "a settings.json edit must force a re-run"


def test_presentation_settings_change_does_not_invalidate_run(env):
    """A PRESENTATION setting written to settings.json (theme / Open-in-New-Window / zen limit) must
    NOT force a re-analysis — the GUI rewrites settings.json when you toggle those, and hashing the
    whole file used to trigger a full recompute. An ANALYSIS setting still re-runs."""
    import time, json as _json
    settings_file = env["root"] / "settings.json"
    csv = env["results"] / "priority_learning_list.csv"

    def write(open_new, theme, band):
        settings_file.write_text(_json.dumps({
            "open_app_mode": open_new, "theme": theme, "zen_limit": 55,
            "logic": {"selection": {"band": band}},
        }), encoding="utf-8")

    write(open_new=False, theme="Dark Flow", band="occasional")
    _run(env, ["--min-freq", "1"])
    m1 = csv.stat().st_mtime
    time.sleep(0.05)
    # Toggle "Open in New Window" + change theme + zen limit -> presentation only -> must SKIP.
    write(open_new=True, theme="Zen Mode", band="occasional")
    _run(env, ["--min-freq", "1"], clear=False)
    assert csv.stat().st_mtime == m1, "toggling theme / Open-in-New-Window must not re-analyze"
    time.sleep(0.05)
    # Change an ANALYSIS setting (the selection band) -> must re-run.
    write(open_new=True, theme="Zen Mode", band="rare")
    _run(env, ["--min-freq", "1"], clear=False)
    assert csv.stat().st_mtime != m1, "changing the selection band must re-analyze"


def test_presentation_args_do_not_invalidate_the_run(env):
    """Merged 'Generate Journey': a THEME change (or Zen limit / window) must NOT trigger a
    re-analysis. The run-signature excludes presentation args, so an unchanged library is skipped
    even when the theme differs — while a real content change still re-runs."""
    import time
    csv = env["results"] / "priority_learning_list.csv"
    _run(env, ["--min-freq", "1", "--theme=world-class"])                    # cold
    m1 = csv.stat().st_mtime
    time.sleep(0.05)
    _run(env, ["--min-freq", "1", "--theme=modern-light"], clear=False)      # only the theme changed
    assert csv.stat().st_mtime == m1, "a theme change must not trigger a re-analysis"
    time.sleep(0.05)
    (env["root"] / "data" / "ja" / "HighPriority" / "t.txt").write_text(
        JA + "\n新しい冒険が始まる。", encoding="utf-8")                        # real change -> must re-run
    _run(env, ["--min-freq", "1", "--theme=modern-light"], clear=False)
    assert csv.stat().st_mtime != m1, "a content change must still re-run"


def _fake_render_writing_html(env):
    """A generate_static_html stand-in that actually creates the report file, so the analyzer's
    'does the HTML exist?' fast-path check behaves realistically without opening a real browser."""
    def _fake(theme="default", app_mode=False, zen_limit=0):
        (env["results"] / "reading_list_static.html").write_text("<html></html>", encoding="utf-8")
    return _fake


def test_skip_rerenders_when_theme_changes(env):
    """Analysis skipped but PRESENTATION changed (theme): the report must be RE-RENDERED with the
    new theme (no re-analysis). This is what let the separate 'View' step be merged in."""
    from unittest.mock import patch
    import app.static_html_generator as shg
    with patch.object(shg, "generate_static_html", side_effect=_fake_render_writing_html(env)) as mock_gen, \
         patch.object(shg, "open_report") as mock_open:
        _run(env, ["--min-freq", "1", "--static", "--theme=world-class"])                   # cold: render
        _run(env, ["--min-freq", "1", "--static", "--theme=modern-light"], clear=False)     # skip + theme changed
    assert mock_gen.call_count == 2, "a theme change on an unchanged library must re-render"
    assert mock_gen.call_args_list[1].kwargs["theme"] == "modern-light"
    assert mock_open.call_count == 0


def test_skip_same_presentation_opens_without_rerender(env):
    """The fast 'same setting' path: neither analysis NOR presentation changed, so the existing
    report is OPENED without re-rendering (no template work, and pandas is never imported)."""
    from unittest.mock import patch
    import app.static_html_generator as shg
    with patch.object(shg, "generate_static_html", side_effect=_fake_render_writing_html(env)) as mock_gen, \
         patch.object(shg, "open_report") as mock_open:
        _run(env, ["--min-freq", "1", "--static", "--theme=world-class"])                   # cold: render
        _run(env, ["--min-freq", "1", "--static", "--theme=world-class"], clear=False)      # identical -> open only
    assert mock_gen.call_count == 1, "an identical re-run must NOT re-render"
    assert mock_open.call_count == 1, "an identical re-run must open the existing report"


def test_toggling_open_in_new_window_does_not_rerender(env):
    """'Open in New Window' (app_mode) changes only HOW the browser opens, not the report's bytes.
    Toggling it must OPEN the existing report (in the new window mode), never re-render."""
    from unittest.mock import patch
    import app.static_html_generator as shg
    with patch.object(shg, "generate_static_html", side_effect=_fake_render_writing_html(env)) as mock_gen, \
         patch.object(shg, "open_report") as mock_open:
        _run(env, ["--min-freq", "1", "--static", "--theme=world-class"])                              # cold render
        _run(env, ["--min-freq", "1", "--static", "--theme=world-class", "--app-mode"], clear=False)   # only app_mode
    assert mock_gen.call_count == 1, "toggling Open-in-New-Window must NOT re-render"
    assert mock_open.call_count == 1, "it must open the existing report"
    assert mock_open.call_args.kwargs.get("app_mode") is True, "opened in the chosen (new-window) mode"


def test_run_persists_token_store(env):
    """A run seeds the SQLite token store so the preview needs no re-run."""
    import os
    from app import token_index as ti
    _run(env, ["--min-freq", "1"])
    db = ti.store_path_for("ja")   # conftest isolates this to a temp dir
    assert os.path.exists(db), "the run should persist a token store"
    store = ti.open_store("ja", path=db)
    try:
        assert store.total_tokens() > 0
        freqs = store.unknown_frequencies(skip_singles=True)
        assert freqs["total_tokens"] > 0
        assert any(ti.split_key(k)[0] == "冒険" for k, _ in freqs["unknown"])
    finally:
        store.close()


def test_manifest_rephase_forces_rerun_not_skip(env):
    """Regression: the run-signature must be ORDER- and WEIGHT-sensitive. Re-phasing a file in
    master_manifest.json (the Immersion Architect's core job — identical file bytes, new schedule)
    changes its tier weight, so Score / the High-Low-Goal columns change. The run MUST regenerate;
    the old signature (sorted paths, weights dropped) was identical for both schedules -> it wrongly
    skipped and served STALE output."""
    import time, json as _json
    root = env["root"]
    high = root / "data" / "ja" / "HighPriority"
    (high / "a.txt").write_text("冒険。冒険する。冒険だ。", encoding="utf-8")
    (high / "b.txt").write_text("今日はいい天気。今日も。", encoding="utf-8")
    manifest = root / "User Files" / "ja" / "master_manifest.json"

    def write_manifest(b_now):
        b_item = {"physical_path": "HighPriority/b.txt", "origin_source": "01_NOW" if b_now else "02_SOON"}
        manifest.write_text(_json.dumps({"schedule": {
            "PHASE_1_NOW": [{"physical_path": "HighPriority/a.txt", "origin_source": "01_NOW"}]
                           + ([b_item] if b_now else []),
            "PHASE_2_SOON": [] if b_now else [b_item],
            "PHASE_3_LATER": [],
        }}), encoding="utf-8")

    csv = env["results"] / "priority_learning_list.csv"
    write_manifest(b_now=True)
    _run(env, ["--min-freq", "1"])                      # cold: b.txt weighted NOW (x10)
    m1 = csv.stat().st_mtime
    time.sleep(0.05)
    _run(env, ["--min-freq", "1"], clear=False)         # nothing changed -> legitimately skipped
    assert csv.stat().st_mtime == m1, "an identical re-run should be skipped"

    time.sleep(0.05)
    write_manifest(b_now=False)                         # re-phase b.txt NOW(x10) -> SOON(x5)
    _run(env, ["--min-freq", "1"], clear=False)
    assert csv.stat().st_mtime != m1, "a manifest re-phase (weight change) must force a re-run"


def test_unreadable_token_blob_is_retokenized_not_dropped(env):
    """Safety net: if a file's cached token blob is corrupt (disk damage) but its (mtime,size)
    still matches — so reconcile won't refresh it — the analyzer must RE-TOKENIZE the file rather
    than silently drop its entire contribution (which, with one file, would lose the word)."""
    import sqlite3
    from app import token_index as ti
    csv = env["results"] / "priority_learning_list.csv"

    assert "冒険" in _run(env, ["--min-freq", "1"])          # cold: seeds the store + writes the CSV

    # Corrupt the cached token sequence blob (garbage that won't zlib-decompress -> file_tokens []).
    con = sqlite3.connect(ti.store_path_for("ja"))
    con.execute("UPDATE files SET tokens = ?", (b"\x00 not a valid zlib blob",))
    con.commit(); con.close()

    csv.unlink()                                             # drop outputs -> forces re-aggregation
    words = _run(env, ["--min-freq", "1"], clear=False)
    assert "冒険" in words, "a file with an unreadable token blob must be re-tokenized, not dropped"
