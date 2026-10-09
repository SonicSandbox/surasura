"""End-to-end check that the analyzer applies density-band selection by DEFAULT (min_freq retired).

Uses real Japanese text where one word recurs and the rest are one-offs, and verifies:
  - default run (no args)   -> the default band drops one-off words,
  - --min-freq 1 (override) -> every word is kept (the legacy raw-count escape hatch).

This guards the Phase 2b wiring (analyzer reads logic.selection and applies band_floor_count).
"""

import json
import os
import shutil
import time
from pathlib import Path

import pytest
import pandas as pd
from unittest.mock import patch

from app import analyzer
from app import word_selection

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
    # (The SQLite token store is isolated to a temp dir by the autouse conftest fixture.) The env's
    # settings.json is the one the run reads (settings_manager.load_settings) — and so the one its run
    # signature hashes, which reads the settings as the run does.
    with patch("app.analyzer.get_user_file", side_effect=env["guf"]), \
         patch("app.settings_manager.get_user_file", side_effect=env["guf"]), \
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

    # The report's own logic keys: the templates read them from the logic block the report embeds, and no run reads
    # them, so the run signature leaves them out — each must re-render instead ("Show 'Target Met' inline", "Hide
    # Audio Button", the page size, the ✦ / ⚖ thresholds).
    import copy
    from app import settings_manager

    def logic(**over):
        block = copy.deepcopy(settings_manager.DEFAULT_SETTINGS["logic"])
        for key, value in over.items():
            block[key] = dict(block[key], **value) if isinstance(block.get(key), dict) else value
        return block

    shown = dict(words_per_day=5, show_words_per_day=True, source_display="off")
    as_shipped = sig(**shown, logic=logic())
    for over in ({"inline_completed_files": True}, {"hide_audio_button": True}, {"chunk_size": 100},
                 {"priority_markers": {"priority_threshold": 0.6}}, {"priority_markers": {"priority_min": 4}},
                 {"priority_markers": {"lopsided_threshold": 0.9}}):
        assert sig(**shown, logic=logic(**over)) != as_shipped, f"{over} must re-render"
    assert sig(**shown, logic=logic(priority_markers={"_comment": "edited"})) == as_shipped, \
        "a note to the reader of settings.json is no change to the report"
    assert sig(**shown, logic=logic(hide_audio_button=False)) == as_shipped, \
        "Hide Audio Button written at its default, as the dashboard saves it, is the same report as left out"


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
    def _fake(theme="default", app_mode=False, zen_limit=0, open_browser=True):
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


def test_the_quiet_generate_never_opens_the_report(env):
    """`--no-open`, the dashboard's automatic Generate after the Anki sync: the render is told not to
    open (first run) and an identical re-run does not open the existing report either."""
    from unittest.mock import patch
    import app.static_html_generator as shg
    with patch.object(shg, "generate_static_html", side_effect=_fake_render_writing_html(env)) as mock_gen, \
         patch.object(shg, "open_report") as mock_open:
        _run(env, ["--min-freq", "1", "--static", "--no-open"])
        _run(env, ["--min-freq", "1", "--static", "--no-open"], clear=False)
    assert mock_gen.call_args.kwargs.get("open_browser") is False
    assert mock_open.call_count == 0


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
        # every file in HighPriority listed (t.txt too): a sync that adds one at the top of NOW would push NOW's last
        # row below the Soon line (L3.1, G2.2-1) before the re-phase this test is about
        b_item = {"physical_path": "HighPriority/b.txt", "origin_source": "01_NOW" if b_now else "02_SOON"}
        manifest.write_text(_json.dumps({"schedule": {
            "PHASE_1_NOW": [{"physical_path": "HighPriority/t.txt", "origin_source": "01_NOW"},
                            {"physical_path": "HighPriority/a.txt", "origin_source": "01_NOW"}]
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


# --- Automatic rarity (logic.selection.auto) on the real samples/ja library -------------------- #
# samples/ja is ~8.7k tokens: at the shipped ppm floors every band below Core collapses to min_count
# (Core, then everything). bands_ppm is user-editable in settings.json; these floors spread the ladder
# on a library this small (a count of >= 21 / 11 / 7 / 5 / 4 / 3 / 2), so an automatic choice can
# land mid-ladder, where picking the wrong band would show.
SMALL_LIBRARY_BANDS_PPM = {"core": 2400, "common": 1200, "occasional": 750, "uncommon": 520,
                           "rare": 400, "very_rare": 290, "native": 1}


@pytest.fixture
def samples_env(project_root):
    """samples/ja under the per-test sandbox root (SURASURA_TEST_ROOT, set by conftest), so the
    analyzer and the dashboard's own path lookups meet the same library, known words, lists,
    settings.json and results/ — as they do in the app."""
    root = Path(os.environ["SURASURA_TEST_ROOT"])
    shutil.copytree(os.path.join(project_root, "samples", "ja"), str(root / "data" / "ja"))
    uf = root / "User Files" / "ja"
    uf.mkdir(parents=True)
    (uf / "KnownWord.json").write_text(json.dumps({"words": []}), encoding="utf-8")
    (root / "results").mkdir()
    return root


def _use_selection(root, **selection):
    """Write settings.json's selection block and load it as a fresh analyzer process would: the
    analyzer reads logic.* once, at import (conftest restores LOGIC after the test)."""
    from app import settings_manager
    (root / "settings.json").write_text(json.dumps({"logic": {"selection": selection}}), encoding="utf-8")
    analyzer.LOGIC["selection"] = settings_manager.load_settings()["logic"]["selection"]


def _run_samples(root, *extra_args):
    """One Generate over the sandbox library, its results/ redirected there. Returns the settings
    block of library_frequency.json — min_count is the floor the run applied."""
    results = root / "results"
    with patch("app.analyzer.RESULTS_DIR", str(results)), \
         patch("app.analyzer.OUTPUT_CSV", str(results / "priority_learning_list.csv")), \
         patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
         patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
         patch("sys.argv", ["analyzer.py", "--language", "ja", *extra_args]):
        analyzer.main()
    return json.loads((results / "library_frequency.json").read_text(encoding="utf-8"))["settings"]


def _band_counts():
    """The Rarity slider's "N words" per band over the run's token store — no known words and no
    lists in this library yet, so the plain unknown distribution — plus that distribution."""
    from app import token_index as ti
    store = ti.open_store("ja")
    try:
        freqs = store.unknown_frequencies(skip_singles=True)
    finally:
        store.close()
    previews = word_selection.band_previews(freqs, SMALL_LIBRARY_BANDS_PPM)
    return {band: p["word_count"] for band, p in previews.items()}, freqs


def _floor(band, lib):
    return word_selection.band_floor_count(band, lib["total_tokens"], SMALL_LIBRARY_BANDS_PPM, 2)


def test_automatic_rarity_lists_the_band_it_picks_and_library_frequency_follows(samples_env, capsys):
    """Automatic rarity on: the run lists the RAREST band holding auto_max_words words or fewer —
    the line drawn here at Uncommon's own count, mid-ladder — the log says which band and why, and
    library_frequency.json carries that band's floor (YouTube Preview, Junban and "In Anki" read
    their cut-off there, so they follow with no change). --min-freq and coverage mode still win over
    it, exactly as they win over a band picked by hand (I4)."""
    root = samples_env
    _use_selection(root, band="very_rare", bands_ppm=SMALL_LIBRARY_BANDS_PPM)
    _run_samples(root)                                   # the user's own band; seeds the token store
    counts, _freqs = _band_counts()
    line = counts["uncommon"]
    assert counts["occasional"] < line < counts["rare"], counts   # a real ladder around the line

    _use_selection(root, band="very_rare", bands_ppm=SMALL_LIBRARY_BANDS_PPM,
                   auto=True, auto_max_words=line)
    capsys.readouterr()
    lib = _run_samples(root)
    log = capsys.readouterr().out
    assert f"Selection band 'uncommon' (automatic: the rarest band with {line} words or fewer)" in log
    assert lib["min_count"] == pytest.approx(_floor("uncommon", lib))
    words = pd.read_csv(root / "results" / "priority_learning_list.csv")["Word"].tolist()
    assert len(words) == line, "the list is exactly the band the rule counted"

    assert _run_samples(root, "--min-freq", "3")["min_count"] == 3
    assert _run_samples(root, "--target-coverage", "90")["min_count"] == 2


def test_turning_automatic_rarity_on_re_runs_and_turning_it_off_lists_what_your_band_did(samples_env):
    """The switch lives in settings.json, which the run signature already hashes: turning it on
    re-runs Generate (the list changes) with no new signature input. Turning it off lists exactly
    what the hand-picked band listed before — byte for byte (I1: off changes nothing)."""
    root = samples_env
    csv = root / "results" / "priority_learning_list.csv"
    _use_selection(root, band="rare", bands_ppm=SMALL_LIBRARY_BANDS_PPM)   # a file from before the switch
    by_hand = _run_samples(root)
    by_hand_csv = csv.read_bytes()
    m1 = csv.stat().st_mtime_ns
    time.sleep(0.05)
    _run_samples(root)
    assert csv.stat().st_mtime_ns == m1, "sanity: nothing changed -> skipped"

    counts, _freqs = _band_counts()
    line = counts["occasional"]
    assert counts["common"] < line < counts["uncommon"], counts
    _use_selection(root, band="rare", bands_ppm=SMALL_LIBRARY_BANDS_PPM, auto=True, auto_max_words=line)
    time.sleep(0.05)
    auto_on = _run_samples(root)
    assert csv.stat().st_mtime_ns != m1, "turning automatic rarity on must re-run the analysis"
    assert auto_on["min_count"] == pytest.approx(_floor("occasional", auto_on))

    _use_selection(root, band="rare", bands_ppm=SMALL_LIBRARY_BANDS_PPM, auto=False, auto_max_words=line)
    off = _run_samples(root)
    assert off["min_count"] == by_hand["min_count"]
    assert csv.read_bytes() == by_hand_csv, "off lists exactly what the hand-picked band listed"


def test_the_automatic_band_moves_on_as_you_learn_without_writing_settings(samples_env):
    """Learning shrinks every band, so the next Generate moves on to a rarer one by itself. Nothing
    automatic writes settings.json (I2): it is in the run signature, and a quiet write would turn the
    Generate button blue after a correct run. So after the move the journey reads up to date — the
    Generate button's own check (journey_is_current)."""
    from app import token_index as ti
    root = samples_env
    _use_selection(root, band="very_rare", bands_ppm=SMALL_LIBRARY_BANDS_PPM)
    _run_samples(root)
    counts, freqs = _band_counts()
    line = counts["uncommon"]
    learned = counts["rare"] - line + 3        # the commonest words, enough to bring Rare under the line
    assert counts["very_rare"] - learned > line + 20, counts   # ...while Very Rare stays well over it

    _use_selection(root, band="very_rare", bands_ppm=SMALL_LIBRARY_BANDS_PPM,
                   auto=True, auto_max_words=line)
    before = _run_samples(root)
    assert before["min_count"] == pytest.approx(_floor("uncommon", before))
    settings_before = (root / "settings.json").read_bytes()

    known = [{"dictForm": ti.split_key(key)[0], "knownStatus": "KNOWN"} for key, _n in freqs["unknown"][:learned]]
    (root / "User Files" / "ja" / "KnownWord.json").write_text(
        json.dumps({"words": known}, ensure_ascii=False), encoding="utf-8")
    after = _run_samples(root)
    assert after["min_count"] == pytest.approx(_floor("rare", after)), "the band moved on by itself"
    assert (root / "settings.json").read_bytes() == settings_before, "nothing automatic writes settings.json"

    from app.main import journey_is_current
    assert journey_is_current(["analyzer.py", "--language", "ja"], "ja") is True


def test_the_band_the_dashboard_shows_is_the_band_generate_uses(samples_env):
    """I3. The analyzer's own ignore set reads a hiragana line through the tokenizer (する -> 為る);
    the dashboard can't (fugashi never enters the GUI process), so its preview counts 為る. The
    automatic choice is therefore made with the PREVIEW's recipe on both sides. The line is drawn one
    word under the preview's Rare: a run that decided on its own counts (為る ignored: one word fewer)
    would pick Rare, while the dashboard shows Uncommon. Known words come from the store's known
    cache on both sides (いる is read as 居る there, never by the dictForm approximation)."""
    from app.main import MasterDashboardApp
    root = samples_env
    uf = root / "User Files" / "ja"
    (uf / "IgnoreList.txt").write_text("# 無視する単語\nする\n", encoding="utf-8")
    (uf / "KnownWord.json").write_text(json.dumps({"words": [
        {"dictForm": "いる", "knownStatus": "KNOWN"}, {"dictForm": "言う", "knownStatus": "KNOWN"}]},
        ensure_ascii=False), encoding="utf-8")
    _use_selection(root, band="very_rare", bands_ppm=SMALL_LIBRARY_BANDS_PPM)
    _run_samples(root)                                   # seeds the store and its known cache

    sel = {"bands_ppm": SMALL_LIBRARY_BANDS_PPM, "min_count": 2}
    dashboard = MasterDashboardApp.__new__(MasterDashboardApp)       # no window: the worker's own read
    previews = dashboard._compute_band_previews("ja", sel, "asis")
    line = previews["rare"]["word_count"] - 1
    shown = word_selection.auto_band(previews, line)
    assert shown == "uncommon", {b: p["word_count"] for b, p in previews.items()}

    _use_selection(root, band="very_rare", bands_ppm=SMALL_LIBRARY_BANDS_PPM,
                   auto=True, auto_max_words=line)
    lib = _run_samples(root)
    assert lib["min_count"] == pytest.approx(_floor(shown, lib)), "Generate must use the band the dashboard shows"


def test_a_word_ignored_in_the_known_words_file_leaves_the_list_and_the_rarity_preview_alike(samples_env):
    """The user, 2026-09-29: KnownWord.json's IGNORED entries (Migaku's status — a word dismissed there) are
    ignored words. Generate leaves one off the list, and the Rarity slider — the dashboard's preview, and so
    automatic rarity — stops counting it too: both read the one reader of those entries."""
    from app import token_index as ti
    root = samples_env
    uf = root / "User Files" / "ja"
    _use_selection(root, band="very_rare", bands_ppm=SMALL_LIBRARY_BANDS_PPM)

    def listed_and_counted():
        _run_samples(root)
        listed = list(pd.read_csv(root / "results" / "priority_learning_list.csv")["Word"])
        store = ti.open_store("ja")
        try:
            counted = {key.split("|")[0] for key in dict(ti.preview_frequencies(store, "ja", str(uf))["unknown"])}
        finally:
            store.close()
        return listed, counted

    listed, counted = listed_and_counted()
    word = next(w for w in listed if len(w) > 1)
    assert word in counted
    (uf / "KnownWord.json").write_text(json.dumps({"words": [{"dictForm": word, "knownStatus": "IGNORED"}]},
                                                  ensure_ascii=False), encoding="utf-8")
    listed, counted = listed_and_counted()
    assert word not in listed, "Generate leaves an IGNORED word off the list"
    assert word not in counted, "and the Rarity preview no longer counts it"


def test_without_the_token_store_automatic_rarity_decides_on_the_runs_own_counts(samples_env, capsys):
    """The store can be locked or damaged; the run then tokenizes directly, and automatic rarity
    still picks its band — from the run's own counts (no known words or lists here, so they are the
    slider's counts too)."""
    import sqlite3
    root = samples_env
    _use_selection(root, band="very_rare", bands_ppm=SMALL_LIBRARY_BANDS_PPM)
    _run_samples(root)
    counts, _freqs = _band_counts()
    line = counts["uncommon"]
    _use_selection(root, band="very_rare", bands_ppm=SMALL_LIBRARY_BANDS_PPM,
                   auto=True, auto_max_words=line)
    capsys.readouterr()
    with patch("app.token_index.open_store", side_effect=sqlite3.OperationalError("database is locked")):
        lib = _run_samples(root)
    assert "could not open token store" in capsys.readouterr().out
    assert lib["min_count"] == pytest.approx(_floor("uncommon", lib))


def test_a_store_that_opens_but_cannot_be_read_at_the_cut_falls_back_to_the_runs_own_counts(
        samples_env, capsys):
    """The store opened, then reading the slider's numbers from it failed at the cut — locked by the
    indexer, an I/O error, a damaged table. The run kept your hand-picked band (Very Rare); the band
    isn't in the run signature, so the run was stamped current on a band the dashboard doesn't show
    (I3) and every later Generate skipped. Unreadable is the same as no store: its own counts."""
    import sqlite3
    root = samples_env
    _use_selection(root, band="very_rare", bands_ppm=SMALL_LIBRARY_BANDS_PPM)
    _run_samples(root)
    counts, _freqs = _band_counts()
    line = counts["uncommon"]
    _use_selection(root, band="very_rare", bands_ppm=SMALL_LIBRARY_BANDS_PPM,
                   auto=True, auto_max_words=line)
    capsys.readouterr()
    with patch("app.token_index.preview_frequencies",
               side_effect=sqlite3.OperationalError("database is locked")):
        lib = _run_samples(root)
    log = capsys.readouterr().out
    assert "could not read the token store (database is locked)" in log
    assert f"Selection band 'uncommon' (automatic: the rarest band with {line} words or fewer)" in log
    assert lib["min_count"] == pytest.approx(_floor("uncommon", lib))


def test_a_hand_edited_line_that_is_not_a_number_keeps_your_band_and_generate_still_runs(samples_env, capsys):
    """auto_max_words is edited in settings.json only, so it can be anything — "850" in quotes, say.
    Automatic rarity can't compare against that: the run says so and keeps the band you picked,
    instead of stopping Generate."""
    root = samples_env
    _use_selection(root, band="very_rare", bands_ppm=SMALL_LIBRARY_BANDS_PPM,
                   auto=True, auto_max_words="850")
    lib = _run_samples(root)
    log = capsys.readouterr().out
    assert "Warning: automatic rarity could not pick a band" in log
    assert "Selection band 'very_rare' ->" in log
    assert lib["min_count"] == pytest.approx(_floor("very_rare", lib))


def test_every_files_counts_share_each_words_one_key(samples_env, monkeypatch):
    """A Generate reads each file's tokens anew from the token store, so each file's counts (kept for the progressive
    pass) held a copy of its own of every word's key — and of the word's text — until the run ended: some 150 MB on a
    large library. Every file's counts now hold the one key each word was first met with. The same lists: only where
    the key lives changes."""
    from collections import Counter

    made = []

    class Recorded(Counter):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            made.append(self)

    monkeypatch.setattr(analyzer, "Counter", Recorded)
    _run_samples(samples_env)
    # Each file's counts: every token of the file, so the particle の too (never an unknown, so in no other count).
    files = [counts for counts in made if ("の", "ノ") in counts]
    assert len(files) >= 4, "the four sample files' counts (and the progressive pass's re-reads, if any)"
    first = {}
    shared = 0
    for counts in files:
        for key in counts:
            held = first.setdefault(key, key)
            assert held is key, f"{key}: one key object for every file"
            shared += held is key and counts is not files[0]
    assert shared, "words met in more than one file"


# --- Q4-3: the band Automatic remembers in the library store (2.6) ------------------------------ #

def _with_library_store(root):
    from app import library_store
    data_dir, user_files = str(root / "data" / "ja"), str(root / "User Files" / "ja")
    assert library_store.maintain("ja", data_dir, user_files, from_folders=True) == library_store.EXIT_DONE
    return library_store, data_dir, user_files


def test_the_remembered_band_is_kept_by_the_second_threshold(samples_env, capsys):
    # Why: Q4-3 — a band Automatic chose stays until its list passes ~1,100 words, so the list stops flipping. On
    # this small library every band is far under 1,100, so a remembered rarer band holds.
    root = samples_env
    _use_selection(root, band="very_rare", bands_ppm=SMALL_LIBRARY_BANDS_PPM)
    _run_samples(root)
    counts, _freqs = _band_counts()
    line = counts["uncommon"]
    ls, data_dir, user_files = _with_library_store(root)
    assert ls.record_auto_band("ja", data_dir, user_files, "rare", counts["rare"])
    _use_selection(root, band="very_rare", bands_ppm=SMALL_LIBRARY_BANDS_PPM, auto=True, auto_max_words=line)
    capsys.readouterr()
    lib = _run_samples(root)
    log = capsys.readouterr().out
    assert "Selection band 'rare' (automatic: kept until its list passes 1100 words)" in log
    assert lib["min_count"] == pytest.approx(_floor("rare", lib))
    assert ls.read_auto_band("ja", data_dir) == "rare"


def test_a_band_change_is_remembered_and_stamped_so_the_next_check_reuses_it(samples_env):
    # Why: the remembered band is a part of the run signature (it picks the list). A run that changes the band must
    # stamp, and write its plan with, the parts the NEXT check reads — else every band change would cost a second
    # Generate, and the re-plan would refuse the plan ("generate-first: auto_band"). Haya's E1.3 check.
    import gzip
    from app.main import journey_is_current
    root = samples_env
    _use_selection(root, band="very_rare", bands_ppm=SMALL_LIBRARY_BANDS_PPM)
    _run_samples(root)
    counts, _freqs = _band_counts()
    line = counts["uncommon"]
    ls, data_dir, user_files = _with_library_store(root)
    assert ls.read_auto_band("ja", data_dir) is None
    _use_selection(root, band="very_rare", bands_ppm=SMALL_LIBRARY_BANDS_PPM, auto=True, auto_max_words=line)
    _run_samples(root)                                          # nothing remembered → picks Uncommon → remembers it
    assert ls.read_auto_band("ja", data_dir) == "uncommon"
    argv = ["analyzer.py", "--language", "ja"]
    schedule, _versions = analyzer.read_library_schedule("ja")       # the files as the journey check reads them
    found = analyzer.resolve_found_files("ja", verbose=False, schedule=schedule)
    parts = analyzer.run_signature_parts("ja", found, analyzer.parse_analysis_args(argv[1:]))
    assert parts["auto_band"] == "uncommon"
    stamp = analyzer.read_run_stamp(str(root / "results"))
    assert stamp == analyzer.signature_digest(parts, chunked=False), "the stamp is the next check's signature"
    with gzip.open(root / "results" / analyzer.PLAN_FILE, "rt", encoding="utf-8") as f:
        header = json.loads(f.readline())
    assert header["order_free_signature"] == analyzer.signature_digest(parts, order_free=True)
    assert journey_is_current(argv, "ja") is True, "no second Generate"


def test_with_automatic_off_the_signature_has_no_band_part(samples_env):
    # Why: the part exists only with Automatic on, so nobody else's signature moved (no forced re-run in 2.6 beyond
    # its own engine bump).
    root = samples_env
    _use_selection(root, band="very_rare", bands_ppm=SMALL_LIBRARY_BANDS_PPM)
    parts = analyzer.run_signature_parts("ja", [], analyzer.parse_analysis_args(["--language", "ja"]))
    assert "auto_band" not in parts


def test_turning_automatic_off_forgets_its_band(samples_env):
    # Why: a band remembered from before Automatic was switched off would come back months later when it's switched
    # on again; switched off, the next run forgets it, so switching on starts from today's rule.
    root = samples_env
    _use_selection(root, band="very_rare", bands_ppm=SMALL_LIBRARY_BANDS_PPM)
    _run_samples(root)
    ls, data_dir, user_files = _with_library_store(root)
    assert ls.record_auto_band("ja", data_dir, user_files, "rare", 40)
    _run_samples(root)                                          # Automatic off
    assert ls.read_auto_band("ja", data_dir) is None


def test_automatic_with_no_library_store_still_stamps_a_run_the_next_check_reuses(samples_env):
    # Why: with no store to remember in (JSON mode), the run uses today's single line, its signature part says
    # nothing is remembered, and the stamp still matches the next check (no endless re-Generates).
    from app.main import journey_is_current
    root = samples_env
    _use_selection(root, band="very_rare", bands_ppm=SMALL_LIBRARY_BANDS_PPM)
    _run_samples(root)
    counts, _freqs = _band_counts()
    _use_selection(root, band="very_rare", bands_ppm=SMALL_LIBRARY_BANDS_PPM, auto=True,
                   auto_max_words=counts["uncommon"])
    lib = _run_samples(root)
    assert lib["min_count"] == pytest.approx(_floor("uncommon", lib))
    assert journey_is_current(["analyzer.py", "--language", "ja"], "ja") is True
