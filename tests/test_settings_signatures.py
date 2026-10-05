"""Which settings make Generate run again: a full analysis when a setting the run reads changes (the run signature,
analyzer.compute_run_signature), a re-render when only the report shows it (compute_render_signature), nothing else.

The user's report: after a change in the Junban window, Preview turned into "Generate & preview" and Generate did a full
run although nothing the analysis reads had changed. The window saved every loaded default, which put back the retired
`reinforce_segmentation` the dashboard's own save drops — and the run signature hashed settings.json as written. So:

- The run signature hashes the settings AS THE RUN READS THEM (settings_manager.load_settings: the defaults filled in, a
  saved value always winning). A key written at its default and one left out are then the same settings, as they are to
  the run; a saved value that isn't the default counts, and changing it is a new run.
- Settings no run reads are out of it; the report's own are in the render signature instead; each language's run
  signature holds that language's settings only.
- The windows that save settings.json write only their own keys onto the file as it is (settings_manager.save_keys).
- The Rarity slider counts with the three library-name switches as Settings has them now.
- Every setting is placed — analysis, report or neither — and checked by flipping it (the last test). A setting nobody
  placed still counts as analysis (compute_run_signature hashes it): forgetting costs a needless run, never a stale list.

Real Japanese and Chinese text from tests/Test Resources; every file in the per-test sandbox (SURASURA_TEST_ROOT).
"""
import copy
import json
import os
import queue
import shutil
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app import analyzer, settings_manager

RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources")
LIBRARY = {"ja": ("context_test.txt", "runaway_transcript.txt", "phrases_sample.srt"), "zh": ("chinese_text_1.txt",)}
KNOWN = {"ja": "KnownWord.json", "zh": "KnownWords.json"}
THEMES = ("Default (Dark)", "Dark Flow", "Midnight (Vibrant)", "Modern Light", "Zen Mode")
LANGUAGES = ("ja", "zh")
NAME_TABLES = ("names_recurring", "names_kanji", "names_work_terms")
JAPANESE_ONLY = {"exclude_single": False, "logic.paren_readings": "any", "logic.names_katakana": False,
                 "logic.names_recurring": False, "logic.names_kanji": False, "logic.names_work_terms": False,
                 "logic.phrases_and_titles": False, "logic.pronoun_bases": False, "logic.phrase_rows": False,
                 "logic.ignore_names": True}
OLD_ZH_ENDS = "。！？!?\n；;……｡"     # 2.3's Chinese sentence ends: …… and ； ended one


# --- the sandbox ------------------------------------------------------------------------------------------------ #
def _root():
    return os.environ["SURASURA_TEST_ROOT"]


def _write(settings):
    with open(os.path.join(_root(), "settings.json"), "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=4)


def _read():
    with open(os.path.join(_root(), "settings.json"), encoding="utf-8") as f:
        return json.load(f)


def _get(settings, path):
    for part in path.split("."):
        settings = settings[part]
    return settings


def _put(settings, path, value):
    parts = path.split(".")
    for part in parts[:-1]:
        settings = settings.setdefault(part, {})
    settings[parts[-1]] = value


def _with(path, value, base=None):
    """`base` (default: a file holding only the language) with the setting at `path` set to `value`."""
    settings = copy.deepcopy(base) if base is not None else {"target_language": "ja"}
    _put(settings, path, value)
    return settings


@pytest.fixture
def library():
    """A Japanese and a Chinese library in the sandbox — files from tests/Test Resources — with their known words."""
    for lang, names in LIBRARY.items():
        folder = os.path.join(_root(), "data", lang, "HighPriority")
        os.makedirs(folder, exist_ok=True)
        for name in names:
            shutil.copy2(os.path.join(RESOURCES, lang, name), os.path.join(folder, name))
        user_files = os.path.join(_root(), "User Files", lang)
        os.makedirs(user_files, exist_ok=True)
        shutil.copy2(os.path.join(RESOURCES, lang, KNOWN[lang]), os.path.join(user_files, "KnownWord.json"))
    return _root()


# --- what the dashboard's Generate computes ----------------------------------------------------------------------- #
class _Var:
    """A widget variable holding what the dashboard's load_settings sets."""

    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def _argv(lang, settings=None):
    """The analyzer's argv as the dashboard's Generate builds it: the real MasterDashboardApp._analyzer_args over the
    values the dashboard's load_settings sets from `settings` (default: settings.json as loaded). Checked against the
    real dashboard's own in test_first_start_after_an_update_keeps_the_journey_current."""
    from app.main import MasterDashboardApp
    s = settings_manager.load_settings() if settings is None else settings
    context = s["logic"].get("context", {})
    script = s.get("zh_script", "asis")
    dashboard = SimpleNamespace(
        var_exclude_single=_Var(s.get("exclude_single", True)), var_strategy=_Var(s.get("strategy", "freq")),
        var_target_coverage=_Var(s.get("target_coverage", 90)), var_language=_Var(lang),
        var_zh_script=_Var(script if script in MasterDashboardApp.ZH_SCRIPT_LABELS else "asis"),
        var_ensure_audio=_Var(s.get("ensure_audio_example", False)),
        var_only_i_plus_one=_Var(s.get("only_i_plus_one", False)),
        var_context_min_chars=_Var(context.get("min_chars", 10)),
        var_context_max_chars=_Var(context.get("preferred_max_chars", 50)),
        var_max_contexts=_Var(context.get("max_contexts", 3)),
        combo_theme=_Var(s.get("theme") if s.get("theme") in THEMES else "Dark Flow"),
        var_open_app_mode=_Var(s.get("open_app_mode", False)), var_zen_limit=_Var(s.get("zen_limit", 50)))
    dashboard._effective_zh_script = lambda language: MasterDashboardApp._effective_zh_script(dashboard, language)
    return MasterDashboardApp._analyzer_args(dashboard)


def _signatures(lang="ja"):
    """(run, render) for `lang`, as Generate — and the dashboard's fast path — computes them now."""
    args = analyzer.parse_analysis_args(_argv(lang)[1:])
    found = analyzer.resolve_found_files(lang, verbose=False)
    return analyzer.compute_run_signature(lang, found, args), analyzer.compute_render_signature(args)


def _run_sig(lang="ja"):
    signature = _signatures(lang)[0]
    assert signature, "the run signature could be computed"
    return signature


def _render_sig(lang="ja"):
    return _signatures(lang)[1]


def _seed_generate(lang="ja"):
    """What a finished Generate leaves for the settings as they are now: the store's last run signature, the results
    stamp and the three outputs journey_is_current looks for."""
    from app import token_index
    signature = _run_sig(lang)
    results = os.path.join(_root(), "results")
    os.makedirs(results, exist_ok=True)
    for name in ("priority_learning_list.csv", "progressive_learning_list.csv", "word_stats.json"):
        with open(os.path.join(results, name), "w", encoding="utf-8") as f:
            f.write("x")
    analyzer._set_run_stamp(results, signature)
    store = token_index.open_store(lang)
    try:
        store.set_meta("last_run_signature", signature)
    finally:
        store.close()


def _journey_current(lang="ja"):
    """The question the Generate button and the Junban window's Preview ask: is the list up to date?"""
    from app.main import journey_is_current
    return journey_is_current(_argv(lang), lang)


def _pre_24_settings():
    """settings.json as 2.3's dashboard saved it: every key it knew at its default — but none of the seven 2.4 added
    (Ignore names, the work-terms switch, phrase rows, phrases and titles, pronouns with a suffix, Automatic rarity and
    its line), the old Chinese sentence ends, and the retired reinforce_segmentation."""
    settings = copy.deepcopy(settings_manager.DEFAULT_SETTINGS)
    settings["reinforce_segmentation"] = False
    logic = settings["logic"]
    for key in ("ignore_names", "names_work_terms", "phrase_rows", "phrases_and_titles", "pronoun_bases"):
        del logic[key]
    del logic["selection"]["auto"], logic["selection"]["auto_max_words"]
    logic["sentence_boundaries"]["zh"] = OLD_ZH_ENDS
    logic["hide_audio_button"] = False
    return settings


@pytest.fixture
def start_dashboard(monkeypatch):
    """Starts the real dashboard as the suite builds it (Tk withdrawn, no update check, Speech's helper not started).
    Starting it saves settings.json, as every start does."""
    import tkinter as tk
    import app.main as main_module
    roots = []

    def start():
        try:
            root = tk.Tk()
        except tk.TclError:
            pytest.skip("Tk is not available in this environment")
        root.withdraw()
        roots.append(root)
        monkeypatch.setattr(tk, "_default_root", root)
        with patch.object(main_module.MasterDashboardApp, "check_updates_thread"), \
                patch.object(main_module.MasterDashboardApp, "apply_koe_state", lambda self: None):
            return main_module.MasterDashboardApp(root)

    yield start
    for root in roots:
        try:
            root.destroy()
        except tk.TclError:
            pass


# --- the windows' own saves, each handed the values already saved (a save that changes nothing) ------------------- #
def _junban_panel_save(**changes):
    from modules.junban.gui import JunbanGui
    s = dict(settings_manager.load_settings(), **changes)
    panel = SimpleNamespace(scope=_Var(s["junban_scope"]), deck=_Var(s["junban_deck"]),
                            _order_value=lambda: s["junban_order"], _unlisted_value=lambda: s["junban_unlisted"],
                            _phrases_value=lambda: s["junban_phrases"],
                            _ready_first_value=lambda: s["junban_ready_first"],
                            _only_marker_values=lambda: tuple(s["junban_only_markers"]),
                            _touchup_settings=lambda: {k: s[k] for k in JUNBAN_TOUCHUPS},
                            _write=MagicMock())
    JunbanGui._save_scope(panel)
    panel._write.assert_not_called()


def _backfill_save(**changes):
    from modules.junban.backfill_gui import BackfillGui
    s = dict(settings_manager.load_settings(), **changes)
    window = SimpleNamespace(_choices=lambda: {k: s[k] for k in BACKFILL_KEYS}, _write=MagicMock())
    BackfillGui._save(window)
    window._write.assert_not_called()


def _architect_launch(words_per_day=None):
    from modules.immersion_architect.gui import ImmersionArchitectGui
    s = settings_manager.load_settings()
    window = SimpleNamespace(wpd_var=_Var(words_per_day or s.get("words_per_day", 5)))
    ImmersionArchitectGui._apply_words_per_day(window)


def _speech_save(**changes):
    from modules.koe.gui import KoeSettingsGui
    s = dict(settings_manager.load_settings(), **changes)
    window = SimpleNamespace(var_key=_Var(""), var_voice=_Var(s["koe_voice"]), var_model=_Var(s["koe_model"]),
                             var_style=_Var(s["koe_style"]), var_temp=_Var(str(s["koe_temperature"])),
                             var_cap=_Var(str(s["koe_daily_cap"])), _float=KoeSettingsGui._float,
                             _int=KoeSettingsGui._int, app=None, _set_status=MagicMock())
    with patch("modules.koe.server.restart"):
        KoeSettingsGui._save(window)


def _onboarding_complete(language="ja"):
    from app.onboarding_gui import OnboardingGuide
    guide = SimpleNamespace(language_var=_Var(language), on_complete_callback=None, window=MagicMock())
    with patch("app.telemetry.init"):
        OnboardingGuide.complete(guide)


def _youtube_ack(value):
    """The YouTube downloader opened from the Content Manager (no dashboard): the one-time risk acknowledgment."""
    from modules.youtube_downloader.gui import YoutubeDownloaderGui
    YoutubeDownloaderGui._ack_set(SimpleNamespace(app=None), value)


JUNBAN_TOUCHUPS = ("junban_tag", "junban_tag_markers", "junban_write_frequency", "junban_frequency_field",
                   "junban_write_freqsort", "junban_later_tag", "junban_later_flag", "junban_later_suspend")
JUNBAN_KEYS = ("junban_scope", "junban_deck", "junban_order", "junban_unlisted", "junban_phrases",
               "junban_ready_first", "junban_only_markers") + JUNBAN_TOUCHUPS
BACKFILL_KEYS = ("junban_backfill_deck", "junban_backfill_cards", "junban_backfill_replace", "junban_backfill_fills",
                 "junban_backfill_fields", "junban_backfill_note_languages")
SPEECH_KEYS = ("koe_voice", "koe_model", "koe_style", "koe_temperature", "koe_daily_cap")


@pytest.fixture
def speech_sandbox(tmp_path, monkeypatch):
    """Speech keeps its key and client token in the persistent data dir, which SURASURA_TEST_ROOT doesn't cover."""
    persistent = tmp_path / "persistent"
    persistent.mkdir()
    monkeypatch.setattr("app.path_utils.get_persistent_user_data_path", lambda: str(persistent), raising=False)


# === 1. The settings as the run reads them ========================================================================= #
def test_a_key_written_at_its_default_leaves_the_run_signature(library):
    """A key left out of settings.json and the same key written at its default are the same settings to the run
    (load_settings fills the default in). They are the same to the run signature now — 2.4's first start writes seven new
    defaults into every file and the dashboard's start drops the retired key, and neither is a new analysis."""
    sparse = {"target_language": "ja", "logic": {"selection": {"band": "occasional"}}}
    written = {"target_language": "ja", "reinforce_segmentation": False,
               "logic": {"phrase_rows": True, "phrases_and_titles": True, "ignore_names": False,
                         "names_work_terms": True, "pronoun_bases": True,
                         "selection": {"band": "occasional", "auto": False, "auto_max_words": 850}}}
    for lang in LANGUAGES:
        _write(sparse)
        before = _run_sig(lang)
        _write(written)
        assert _run_sig(lang) == before, f"{lang}: the defaults written out are no new analysis"
        _write(settings_manager.load_settings())
        assert _run_sig(lang) == before, f"{lang}: every default written out, as a window that saves them all does"

    _write(_with("logic.sentence_boundaries.zh", OLD_ZH_ENDS))
    old_ends = _run_sig("zh")
    _write({"target_language": "ja"})
    assert _run_sig("zh") == old_ends, "2.3's Chinese sentence ends read as today's default, by the run and its signature"


@pytest.mark.parametrize("path, saved, again", [
    ("exclude_single", False, None),
    ("only_i_plus_one", True, None),
    ("logic.weights.high", 12, 15),
    ("logic.tiers.thresholds", [2000, 4000, 6000, 9000], [2500, 5000, 7500, 12000]),
    ("logic.context.max_chars", 120, 90),
    ("logic.context.recency_files", 3, -1),
    ("logic.selection.band", "rare", "core"),
    ("logic.selection.bands_ppm", {"rare": 5}, {"rare": 6}),
    ("logic.selection.min_count", 3, 4),
    ("logic.modality.target_hours", 40, 80),
    ("logic.names_kanji", False, None),
    ("logic.paren_readings", "any", "off"),
    ("logic.sentence_boundaries.ja", "。｡．！？!?\n…", "。｡．！？!?\n～"),
])
def test_a_saved_value_always_wins_in_the_run_signature(library, path, saved, again):
    """The user, approving this fix: it must not ignore their saved setting. The signature hashes what load_settings
    returns, where a value saved in settings.json always wins over the default — the value the run itself reads. So a
    saved value that isn't the default counts (its signature is not the defaults'), and counts the same however the
    rest of the file is written; every change to it is a new run; and taking it out of the file again is the defaults'
    run again."""
    _write({"target_language": "ja"})
    defaults = _run_sig("ja")

    _write(_with(path, saved))
    loaded = _get(settings_manager.load_settings(), path)
    if isinstance(saved, dict):
        assert {k: loaded[k] for k in saved} == saved, "the saved floors win; the bands left out keep their default"
    elif path.startswith("logic.sentence_boundaries."):
        assert set(saved) <= set(loaded), "the saved sentence ends are kept (the essential ones added to them)"
    else:
        assert loaded == saved, "the run reads the saved value"
    first = _run_sig("ja")
    assert first != defaults, f"a saved {path} that isn't the default counts"
    _write(settings_manager.load_settings())
    assert _get(settings_manager.load_settings(), path) == loaded
    assert _run_sig("ja") == first, "the same saved value with every default written out beside it: the same run"

    if again is not None:
        _write(_with(path, again))
        assert _run_sig("ja") not in (first, defaults), f"changing the saved {path} again is a new run"

    _write({"target_language": "ja"})
    assert _run_sig("ja") == defaults, "out of the file again, the default is back — and so is its run"


def test_first_start_after_an_update_keeps_the_journey_current(library, start_dashboard):
    """The first start after an update rewrites settings.json once: the dashboard writes the new defaults in, updates the
    old Chinese sentence ends and drops the retired key. None of it changes what a run reads, so a list that was up to
    date before the start is up to date after it — no full Generate for the update's sake."""
    _write(_pre_24_settings())
    _seed_generate("ja")
    assert _journey_current("ja") is True

    app = start_dashboard()                      # its start saves settings.json from its widgets
    rewritten = _read()
    assert "reinforce_segmentation" not in rewritten and rewritten["logic"]["phrase_rows"] is True
    assert rewritten["logic"]["sentence_boundaries"]["zh"] != OLD_ZH_ENDS, "the start did rewrite the file"
    assert app._analyzer_args() == _argv("ja"), "the dashboard's own argv is the one these tests rebuild"
    assert _journey_current("ja") is True, "the update's first start is no new analysis"


def test_junban_panel_save_keeps_the_journey_current(library, start_dashboard):
    """The user's report, end to end. After a dashboard save and a Generate, a Junban panel save that changes nothing
    must leave the list up to date — and so must the dashboard's next save. The panel used to put the retired key back
    (Preview read "Generate & preview" and Generate ran in full), and the dashboard's next save dropped it again (another
    full run)."""
    pytest.importorskip("modules.junban.gui")
    app = start_dashboard()
    app.save_settings(skip_ui=True)
    _seed_generate("ja")
    assert _journey_current("ja") is True

    _junban_panel_save()
    assert _journey_current("ja") is True, "a Junban save that changes nothing leaves the list up to date"
    app.save_settings(skip_ui=True)
    assert _journey_current("ja") is True, "and so does the dashboard's next save"


def test_backfill_and_architect_saves_keep_the_journey_current(library, start_dashboard):
    """The same for Anki Backfill's choices and the Immersion Architect's launch (it saves the words a day)."""
    pytest.importorskip("modules.junban.backfill_gui")
    pytest.importorskip("modules.immersion_architect.gui")
    app = start_dashboard()
    app.save_settings(skip_ui=True)
    _seed_generate("ja")
    for save in (_backfill_save, _architect_launch):
        save()
        assert _journey_current("ja") is True, f"{save.__name__} that changes nothing leaves the list up to date"
        app.save_settings(skip_ui=True)
        assert _journey_current("ja") is True, f"and so does the dashboard's next save ({save.__name__})"


def test_a_file_with_its_defaults_written_out_generates_byte_identical_output(library):
    """Hashing the settings as the run reads them is right only if the run reads them that way: a settings.json without
    2.4's defaults and the same settings with every default written out must be the same analysis, byte for byte.
    Two Generates over the Japanese test library, each from a cold store into empty results: every output — the lists,
    the stats, the report, and the results stamp (the run signature itself) — is identical."""
    from app import static_html_generator, token_index
    results = os.path.join(_root(), "results")
    outputs = []
    for settings in (_pre_24_settings(), "written out"):
        _write(settings_manager.load_settings() if settings == "written out" else settings)
        shutil.rmtree(results, ignore_errors=True)
        os.makedirs(results)
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(token_index.store_path_for("ja") + suffix):
                os.remove(token_index.store_path_for("ja") + suffix)
        analyzer.LOGIC.update(settings_manager.load_settings()["logic"])   # as a fresh analyzer process loads it
        with patch.object(analyzer, "RESULTS_DIR", results), \
                patch.object(analyzer, "OUTPUT_CSV", os.path.join(results, "priority_learning_list.csv")), \
                patch.object(analyzer, "OUTPUT_STATS", os.path.join(results, "file_statistics.txt")), \
                patch.object(analyzer, "OUTPUT_PROGRESSIVE", os.path.join(results, "progressive_learning_list.csv")), \
                patch.object(static_html_generator, "RESULTS_DIR", results), \
                patch.object(static_html_generator, "PROGRESSIVE_CSV",
                             os.path.join(results, "progressive_learning_list.csv")), \
                patch.object(static_html_generator, "PRIORITY_CSV",
                             os.path.join(results, "priority_learning_list.csv")), \
                patch.object(static_html_generator, "OUTPUT_FILE", os.path.join(results, "reading_list_static.html")), \
                patch("sys.argv", _argv("ja") + ["--no-open"]):
            analyzer.main()
        written = {}
        for name in sorted(os.listdir(results)):
            with open(os.path.join(results, name), "rb") as f:
                written[name] = f.read()
        outputs.append(written)

    first, second = outputs
    assert {"priority_learning_list.csv", "progressive_learning_list.csv", "reading_list_static.html",
            "run_signature.txt"} <= set(first)
    assert len(first["priority_learning_list.csv"].splitlines()) > 1, "the test library lists words"
    assert set(first) == set(second)
    for name in first:
        assert first[name] == second[name], f"{name} differs between the two files of the same settings"


# === 2. The retired key ============================================================================================ #
def test_the_retired_reinforce_setting_never_changes_the_run_signature(library):
    """`reinforce_segmentation` is retired: ChineseTokenizer ignores it. It is out of the defaults, so no window writes
    it back, and out of the run signature, so a file that still holds it — any value — is the same analysis."""
    assert "reinforce_segmentation" not in settings_manager.DEFAULT_SETTINGS
    _write({"target_language": "ja"})
    plain = {lang: _run_sig(lang) for lang in LANGUAGES}
    for value in (False, True):
        _write({"target_language": "ja", "reinforce_segmentation": value})
        assert {lang: _run_sig(lang) for lang in LANGUAGES} == plain, value


def _dashboard_saved():
    """What the dashboard's save writes — MasterDashboardApp.save_settings itself, on a stand-in for its window — as a
    dict whose KEYS are exactly the dashboard's (its widget values are stand-ins)."""
    from app.main import MasterDashboardApp
    loaded = settings_manager.load_settings()
    app = MagicMock()
    app._current_settings = loaded
    app.logic_settings = loaded["logic"]
    app._iv = lambda var, fallback: fallback
    saved = {}
    with patch.object(settings_manager, "save_settings", side_effect=lambda s, **k: saved.update(s)):
        MasterDashboardApp.save_settings(app, skip_ui=True)
    assert saved, "the dashboard's save ran"
    return saved


VALUE_DICTS = {"bands_ppm", "anki_sync_decks", "anki_sync_fields", "junban_word_fields", "junban_backfill_fields",
               "junban_backfill_note_languages"}


def _paths(settings, prefix=""):
    """Every setting in `settings` as a dotted path. A block of settings is descended into; a dict that is ONE setting's
    value (the Rarity floors, the decks or fields per language or note type) is not."""
    out = []
    for key, value in settings.items():
        path = prefix + key
        if isinstance(value, dict) and value and key not in VALUE_DICTS:
            out += _paths(value, path + ".")
        else:
            out.append(path)
    return out


def test_the_dashboard_leaves_out_only_excluded_defaults(library):
    """The dashboard rebuilds settings.json from its own widgets on every save, so a default it doesn't write is
    dropped from the file. e464ee5 stopped writing reinforce_segmentation while the defaults still held it, and every
    window that saved the defaults put it back. So any setting load_settings() returns that the dashboard's save leaves
    out must be one no run reads: flipping it in the file never changes a run signature."""
    _write({"target_language": "ja"})
    loaded = copy.deepcopy(settings_manager.load_settings())
    written = set(_paths(_dashboard_saved()))
    left_out = [path for path in _paths(loaded) if path not in written]
    _write(loaded)
    before = {lang: _run_sig(lang) for lang in LANGUAGES}
    moved = []
    for path in left_out:
        _write(_with(path, _flip(path, _get(loaded, path)), loaded))
        moved += [f"{path} ({lang})" for lang in LANGUAGES if _run_sig(lang) != before[lang]]
    assert not moved, f"the dashboard drops these from settings.json, yet a run reads them: {moved}"


# === 3. Settings no run reads ====================================================================================== #
@pytest.mark.parametrize("path, value", [
    ("telemetry_enabled", False),
    ("auto_update_enabled", False),
    ("onboarding_completed", True),
    ("split_length", 5000),
    ("add_graduated_words", False),
    ("logic.gui.tooltip_delay", 900),
    ("logic.importer.split_overflow", 400),
    ("logic.context.search_range", 40),
    ("logic.context.max_extra", 5),
    ("logic.context.min_words", 6),
])
def test_app_and_importer_settings_never_change_the_run_signature(library, path, value):
    """The app's own (telemetry, automatic updates, the welcome guide), the importers' (the EPUB part size and its split,
    Add Words on 'Graduate'), the tooltip delay, and three context keys no code reads: no run reads any of them, so
    changing one is no new analysis — and no new report."""
    _write({"target_language": "ja"})
    before = {lang: _signatures(lang) for lang in LANGUAGES}
    _write(_with(path, value))
    assert {lang: _signatures(lang) for lang in LANGUAGES} == before


def test_comments_never_change_the_run_signature(library):
    """settings.json's "_comment" strings are notes to whoever edits it by hand, at any depth: no code reads them."""
    comments = [path for path in _paths(settings_manager.DEFAULT_SETTINGS) if path.endswith("._comment")]
    assert len(comments) >= 8
    full = copy.deepcopy(settings_manager.load_settings())
    _write(full)
    before = {lang: _signatures(lang) for lang in LANGUAGES}
    for path in comments:
        _write(_with(path, _get(full, path) + " (edited by hand)", full))
        assert {lang: _signatures(lang) for lang in LANGUAGES} == before, path
        _write(_with(path, "", full))
        assert {lang: _signatures(lang) for lang in LANGUAGES} == before, path


def test_rarity_or_coverage_reaches_the_run_through_its_args(library):
    """`strategy` and `target_coverage` are out of the settings the run signature hashes because no run reads either key:
    their whole effect is the --target-coverage the dashboard passes in coverage mode, and the args are in the
    signature. So in Rarity mode the coverage target (its field hidden there) is no new run; switching to coverage, or
    changing the target in coverage mode, is."""
    _write({"target_language": "ja"})
    rarity = _run_sig("ja")
    _write({"target_language": "ja", "target_coverage": 80})
    assert "--target-coverage=80" not in _argv("ja")
    assert _run_sig("ja") == rarity, "Rarity mode reads no coverage target"
    _write({"target_language": "ja", "strategy": "coverage"})
    assert "--target-coverage=90" in _argv("ja")
    at_90 = _run_sig("ja")
    assert at_90 != rarity, "switching to coverage is a new analysis"
    _write({"target_language": "ja", "strategy": "coverage", "target_coverage": 80})
    assert _run_sig("ja") not in (at_90, rarity), "a new coverage target in coverage mode is a new analysis"


# === 4. The report's own settings ================================================================================== #
@pytest.mark.parametrize("path, value", [
    ("logic.inline_completed_files", True),
    ("logic.hide_audio_button", True),
    ("logic.chunk_size", 100),
    ("logic.priority_markers.priority_threshold", 0.6),
    ("logic.priority_markers.priority_min", 5),
    ("logic.priority_markers.lopsided_threshold", 0.9),
])
def test_report_only_logic_settings_re_render_and_never_re_analyze(library, path, value):
    """"Show 'Target Met' inline", "Hide Audio Button", the page size and the ✦ / ⚖ thresholds: the templates read them
    from the logic block the report embeds, and no run reads them. Changing one re-renders the report (about 3 s) —
    never a full analysis (about 13 s on a large library)."""
    _write({"target_language": "ja"})
    before = {lang: _signatures(lang) for lang in LANGUAGES}
    _write(_with(path, value))
    for lang in LANGUAGES:
        run, render = _signatures(lang)
        assert run == before[lang][0], f"{lang}: no new analysis"
        assert render != before[lang][1], f"{lang}: a new report"


# === 5. Each language's own settings =============================================================================== #
def test_the_japanese_run_signature_ignores_chinese_only_settings(library):
    """The Chinese script and the Chinese sentence ends never reach a Japanese run (its args carry no script)."""
    _write({"target_language": "ja"})
    japanese = _run_sig("ja")
    for path, value in (("zh_script", "s"), ("zh_script", "t"),
                        ("logic.sentence_boundaries.zh", "。｡！？!?\n；")):
        _write(_with(path, value))
        assert _run_sig("ja") == japanese, f"{path} = {value!r}"


def test_the_chinese_run_signature_follows_its_script_and_sentence_ends(library):
    """A Chinese run reads its script and its sentence ends — each a new analysis — and never the Japanese ones."""
    _write({"target_language": "zh"})
    chinese = _run_sig("zh")
    _write(_with("zh_script", "s", {"target_language": "zh"}))
    assert "--zh-script=s" in _argv("zh")
    assert _run_sig("zh") != chinese, "the Chinese script"
    _write(_with("logic.sentence_boundaries.zh", "。｡！？!?\n；", {"target_language": "zh"}))
    assert _run_sig("zh") != chinese, "the Chinese sentence ends"
    _write(_with("logic.sentence_boundaries.ja", "。｡．！？!?\n…", {"target_language": "zh"}))
    assert _run_sig("zh") == chinese, "the Japanese sentence ends are not Chinese's"


def test_the_chinese_run_signature_ignores_japanese_only_switches(library):
    """Measured on a Chinese Generate of the Chinese test library (every output compared byte for byte): flipping any
    of these leaves a Chinese run's output the same — each is read where a Japanese run reads it (the paren readings in
    Japanese books, the names and phrases in the Japanese tokenizer's joins, the one-character rule for Japanese). So
    each is a new analysis for Japanese only. If a Chinese run ever reads one, take it out of _JAPANESE_ONLY_LOGIC."""
    _write({"target_language": "ja"})
    before = {lang: _run_sig(lang) for lang in LANGUAGES}
    for path, value in JAPANESE_ONLY.items():
        _write(_with(path, value))
        assert _run_sig("ja") != before["ja"], f"{path}: a Japanese run reads it"
        assert _run_sig("zh") == before["zh"], f"{path}: a Chinese run doesn't"


# === 6. Speech's port ============================================================================================== #
def test_koe_port_re_renders_only_while_speech_is_on(library):
    """The report embeds Speech's port to reach its helper — only while Speech is on. Then a new port is a new report;
    with Speech off, the report holds no port and nothing changes. Never a new analysis."""
    _write({"target_language": "ja", "koe_port": 8787})
    off = _signatures("ja")
    _write({"target_language": "ja", "koe_port": 8790})
    assert _signatures("ja") == off, "Speech off: the report holds no port"
    _write({"target_language": "ja", "enable_koe": True, "koe_port": 8787})
    on_run, on_render = _signatures("ja")
    _write({"target_language": "ja", "enable_koe": True, "koe_port": 8790})
    run, render = _signatures("ja")
    assert render != on_render, "Speech on: a new port is a new report"
    assert run == on_run == off[0], "never a new analysis"


# === 7. The Rarity slider and the library's name tables ============================================================ #
def test_the_rarity_preview_follows_the_name_switches_without_a_restart():
    """The Rarity slider counts with the library's name tables (a joined name counts once, its pieces no more), and the
    store reads which tables apply from analyzer.LOGIC — which the dashboard's process loaded once, at its first
    import. So a switch flipped in Settings kept counting the old way until a restart; and the slider's fingerprint
    didn't hold the switches, so even a refresh kept the old numbers. Now the fingerprint holds them, and a refresh sets
    them from the dashboard's settings before it counts."""
    from app import token_index
    from app.main import MasterDashboardApp

    app = MasterDashboardApp.__new__(MasterDashboardApp)                   # no window: the slider's own reads
    sel = {"band": "occasional"}
    app._current_settings = {"logic": {}}
    on = app._preview_signature("ja", sel)
    assert on is not None
    for key in NAME_TABLES:
        app._current_settings = {"logic": {key: False}}
        assert app._preview_signature("ja", sel) != on, f"{key} is in the slider's fingerprint"
    app._current_settings = {"logic": {key: True for key in NAME_TABLES}}
    assert app._preview_signature("ja", sel) == on, "written on, as the dashboard saves them, reads as left out"

    # A refresh counts with the switches as Settings has them now — not as this process imported them.
    analyzer.LOGIC.update({key: True for key in NAME_TABLES})
    counted, done = [], threading.Event()

    def compute(lang, selection, script):
        counted.append(token_index._library_switches(lang))
        done.set()

    app.var_language, app.var_zh_script = _Var("ja"), _Var("asis")
    app.var_band_coverage, app.gui_queue = MagicMock(), queue.Queue()
    app._compute_band_previews = compute
    app._current_settings = {"logic": {"names_recurring": True, "names_kanji": False, "names_work_terms": True,
                                       "selection": sel}}
    app._refresh_band_preview()
    assert done.wait(10)
    assert counted == [(True, False, True)], "the slider counts without the kanji names, as Settings now says"

    # ...and the store's counts follow those switches: each combination of tables joins its own words.
    store = token_index.open_store("ja")
    try:
        store.set_meta("names_adjust", json.dumps({
            "111": {"counts": [["一護", "イチゴ", 3], ["一", "イチ", -3], ["護", "マモル", -3]], "total": -3},
            "101": {"counts": [], "total": 0}}, ensure_ascii=False))
        assert ("一護", "イチゴ") not in store.word_counts()[0], "kanji names off: no joined name"
        analyzer.LOGIC["names_kanji"] = True
        assert store.word_counts()[0][("一護", "イチゴ")] == 3, "kanji names on: the joined name counts"
    finally:
        store.close()


def test_a_name_switch_refreshes_the_rarity_slider_at_once(start_dashboard):
    """Settings → Language & Parsing: like Ignore names and phrase rows, the names switches refresh the slider when
    flipped (its numbers follow at once; the list at the next Generate)."""
    app = start_dashboard()
    app.create_settings_window()
    boxes = {str(box.cget("variable")): box for box in app.names_frame.winfo_children()}
    with patch.object(app, "_refresh_band_preview") as refresh:
        boxes[str(app.var_names_kanji)].invoke()
    assert app.var_names_kanji.get() is False
    assert _read()["logic"]["names_kanji"] is False, "saved"
    refresh.assert_called()


# === 8. Each window writes only its own keys ====================================================================== #
def _dashboard_style_file():
    """settings.json as the dashboard writes it for someone who never turned Speech on: no koe_* key at all."""
    settings = copy.deepcopy(settings_manager.load_settings())
    for key in [key for key in settings if key.startswith("koe_")]:
        del settings[key]
    settings["logic"]["hide_audio_button"] = False
    return settings


@pytest.mark.parametrize("window", ["junban", "backfill", "architect", "speech", "onboarding", "youtube"])
def test_module_windows_write_only_their_own_keys(library, speech_sandbox, window):
    """Each window that saves settings.json writes its own keys onto the file as it is — never the loaded settings,
    which carry every default and every installed module's: those put back the retired key the dashboard drops (a full
    Generate after every click), and wrote Speech's hidden keys for users who never turned Speech on. After each save,
    every other key is exactly as it was."""
    saves = {
        "junban": ("modules.junban.gui", lambda: _junban_panel_save(
            junban_scope="all", junban_deck="日本語::Mining", junban_order="priority", junban_tag="surasura",
            junban_only_markers=["star"]),
            {"junban_scope": "all", "junban_deck": "日本語::Mining", "junban_order": "priority",
             "junban_tag": "surasura", "junban_only_markers": ["star"]}, JUNBAN_KEYS),
        "backfill": ("modules.junban.backfill_gui", lambda: _backfill_save(
            junban_backfill_deck="日本語::Mining", junban_backfill_fills=["sentence"]),
            {"junban_backfill_deck": "日本語::Mining", "junban_backfill_fills": ["sentence"]}, BACKFILL_KEYS),
        "architect": ("modules.immersion_architect.gui", lambda: _architect_launch(12), {"words_per_day": 12},
                      ("words_per_day",)),
        "speech": ("modules.koe.gui", lambda: _speech_save(koe_voice="Iapetus", koe_temperature=0.9),
                   {"koe_voice": "Iapetus", "koe_temperature": 0.9}, SPEECH_KEYS),
        "onboarding": ("app.onboarding_gui", lambda: _onboarding_complete("zh"), {"target_language": "zh"},
                       ("target_language",)),
        "youtube": ("modules.youtube_downloader.gui", lambda: _youtube_ack(True), {"youtube_risk_acknowledged": True},
                    ("youtube_risk_acknowledged",)),
    }
    module, save, expected, own = saves[window]
    pytest.importorskip(module)
    before = _dashboard_style_file()
    if window == "speech":
        before["enable_koe"] = False                     # Speech's window opens only once Speech is revealed
    settings_manager.save_settings(before)               # as every save writes it (no hide_satoru without the module)
    before = _read()

    save()
    after = _read()
    assert {k: after[k] for k in expected} == expected, "the window's own choices are saved"
    assert set(after) - set(before) <= set(own), "nothing new but the window's own keys"
    assert {k: v for k, v in after.items() if k not in own} == {k: v for k, v in before.items() if k not in own}, \
        "every other key exactly as it was"
    if window != "speech":
        assert not [key for key in after if key.startswith("koe_")], "no Speech key for someone who never turned it on"
    assert "reinforce_segmentation" not in after


@pytest.mark.parametrize("on_disk", ["not json {", "[1, 2, 3]", None])
def test_save_keys_falls_back_to_the_loaded_settings_when_the_file_cannot_be_read(on_disk):
    """A settings.json that isn't a JSON object — or isn't there — can't take a window's keys as it is: the save falls
    back to the loaded settings (the defaults), as the Anki window's own save does, and the file is whole again."""
    path = os.path.join(_root(), "settings.json")
    if on_disk is not None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(on_disk)
    saved = settings_manager.save_keys({"words_per_day": 9})
    assert saved["words_per_day"] == 9
    after = _read()
    assert after["words_per_day"] == 9 and after["logic"]["selection"]["band"] == "occasional"


def test_save_keys_reads_a_file_saved_with_a_bom():
    """Notepad saves settings.json with a byte-order mark: the window's save still writes onto that file as it is."""
    with open(os.path.join(_root(), "settings.json"), "w", encoding="utf-8-sig") as f:
        json.dump({"target_language": "zh", "theme": "Zen Mode"}, f)
    settings_manager.save_keys({"words_per_day": 7})
    assert _read() == {"target_language": "zh", "theme": "Zen Mode", "words_per_day": 7}


# === 10. Every setting placed ====================================================================================== #
# What flipping each setting must do. "analysis": a run reads it, so the run signature moves — in both languages, or in
# the one named ("analysis:ja"). "report": only the report shows it, so the render signature moves and the run's
# doesn't. "neither": no run and no report reads it. A setting missing here fails the test below: place it when you
# add it. Until it is placed, compute_run_signature hashes it — a needless run at worst, never a stale list.
PLACED = {
    "exclude_single": "analysis:ja", "open_app_mode": "neither", "theme": "report", "strategy": "analysis",
    "target_coverage": "analysis", "split_length": "neither", "target_language": "analysis",
    "zh_script": "analysis:zh", "telemetry_enabled": "neither", "words_per_day": "report",
    "show_words_per_day": "report", "zen_limit": "report", "onboarding_completed": "neither", "open_count": "neither",
    "hide_satoru": "neither", "only_i_plus_one": "analysis", "ensure_audio_example": "analysis",
    "add_graduated_words": "neither", "auto_update_enabled": "neither", "skipped_version": "neither",
"source_display": "report", "word_search_enabled": "report",
    "word_search_category": "report", "sentence_dictionary_source": "neither", "anki_connect_url": "neither",
    "anki_sync_auto": "neither", "anki_sync_decks": "neither", "anki_sync_fields": "neither",
    "anki_sync_include_suspended": "neither", "anki_backlog_on_generate": "report", "anki_auto_generate": "neither",
    "logic.inline_completed_files": "report", "logic.hide_audio_button": "report", "logic.chunk_size": "report",
    "logic.paren_readings": "analysis:ja", "logic.names_katakana": "analysis:ja",
    "logic.names_recurring": "analysis:ja", "logic.names_kanji": "analysis:ja", "logic.names_work_terms": "analysis:ja",
    "logic.phrases_and_titles": "analysis:ja", "logic.pronoun_bases": "analysis:ja", "logic.phrase_rows": "analysis:ja",
    "logic.ignore_names": "analysis:ja",
    "logic.weights.high": "analysis", "logic.weights.low": "analysis", "logic.weights.goal": "analysis",
    "logic.tiers.thresholds": "analysis",
    "logic.context.search_range": "neither", "logic.context.min_chars": "analysis", "logic.context.max_extra": "neither",
    "logic.context.preferred_max_chars": "analysis", "logic.context.max_contexts": "analysis",
    "logic.context.max_chars": "analysis", "logic.context.recency_files": "analysis",
    "logic.sentence_boundaries.ja": "analysis:ja", "logic.sentence_boundaries.zh": "analysis:zh",
    "logic.gui.tooltip_delay": "neither",
    "logic.priority_markers.priority_threshold": "report", "logic.priority_markers.priority_min": "report",
    "logic.priority_markers.lopsided_threshold": "report",
    "logic.selection.band": "analysis", "logic.selection.auto": "analysis", "logic.selection.auto_max_words": "analysis",
    "logic.selection.min_count": "analysis", "logic.selection.minutes_per_file": "analysis",
    "logic.selection.bands_ppm": "analysis",
    "logic.modality.target_hours": "analysis", "logic.modality.min_series": "analysis",
    "logic.modality.min_lib_count": "analysis", "logic.modality.min_library_series": "analysis",
    "logic.importer.split_overflow": "neither",
    # The optional modules' switches and their own tunables (each module's SETTINGS_DEFAULTS).
    "enable_youtube_transcripts": "neither", "enable_youtube_preview": "neither", "youtube_risk_acknowledged": "neither",
    "enable_koe": "report", "koe_port": "report", "koe_voice": "neither", "koe_model": "neither", "koe_style": "neither",
    "koe_temperature": "neither", "koe_daily_cap": "neither",
    "enable_reels": "neither", "reels_context_cues": "neither", "reels_exclude_numerals": "neither",
    "reels_exclude_proper_nouns": "neither", "reels_ffmpeg_dir": "neither", "reels_gap_seconds": "neither",
    "reels_max_folder_gb": "neither", "reels_max_unknown": "neither", "reels_open_player": "neither",
    "reels_output_dir": "neither", "reels_subsync_path": "neither", "reels_words_per_part": "neither",
    "enable_junban": "neither", "junban_auto_actions": "neither", "junban_auto_backfill": "neither",
    "junban_auto_reorder": "neither", "junban_backfill_cards": "neither", "junban_backfill_deck": "neither",
    "junban_backfill_fields": "neither", "junban_backfill_fills": "neither", "junban_backfill_note_languages": "neither",
    "junban_backfill_replace": "neither", "junban_chunk_size": "neither", "junban_deck": "neither",
    "junban_frequency_field": "neither", "junban_later_flag": "neither", "junban_later_suspend": "neither",
    "junban_later_tag": "neither", "junban_only_markers": "neither", "junban_order": "neither",
    "junban_phrases": "neither", "junban_ready_first": "neither", "junban_scope": "neither", "junban_tag": "neither",
    "junban_tag_markers": "neither", "junban_unlisted": "neither", "junban_url": "neither",
    "junban_word_fields": "neither", "junban_write_freqsort": "neither", "junban_write_frequency": "neither",
}
# Which optional module a setting belongs to: without the module (a checkout without modules/) it doesn't exist.
OWNERS = (("junban_", "modules.junban"), ("enable_junban", "modules.junban"), ("koe_", "modules.koe"),
          ("enable_koe", "modules.koe"), ("reels_", "modules.reels"), ("enable_reels", "modules.reels"),
          ("enable_youtube_", "modules.youtube_downloader"), ("youtube_", "modules.youtube_downloader"))


def _installed(path):
    """Whether the optional module `path` belongs to is installed — a core setting always is."""
    import importlib.util
    owner = next((module for prefix, module in OWNERS if path.startswith(prefix)), None)
    try:
        return owner is None or importlib.util.find_spec(owner) is not None
    except ImportError:
        return False


# A setting read only in some state is flipped from that state.
WHILE = {"target_coverage": {"strategy": "coverage"},     # coverage mode only (Rarity mode reads no target: above)
         "koe_port": {"enable_koe": True}}                 # in the report only while Speech is on
# A valid other value, where "not" or "add one" wouldn't be one.
FLIPS = {"theme": "Modern Light", "strategy": "coverage", "target_language": "zh", "zh_script": "s",
         "source_display": "icon", "word_search_category": "anime", "logic.paren_readings": "any",
         "logic.selection.band": "rare", "logic.selection.bands_ppm": {"very_rare": 3},
         "logic.sentence_boundaries.ja": "。｡．！？!?\n…",
         "logic.sentence_boundaries.zh": "。｡！？!?\n；",
         "anki_sync_decks": {"ja": ["日本語::Mining"]}, "anki_sync_fields": {"ja": ["Expression"]}}


def _flip(path, value):
    if path in FLIPS:
        return FLIPS[path]
    if path.endswith("._comment"):
        return str(value) + " (edited by hand)"
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value + 1
    if isinstance(value, str):
        return value + "x"
    if isinstance(value, list):
        return list(value) + ["x"]
    if isinstance(value, dict):
        return dict(value, x="y")
    return "x"


def test_every_setting_is_classified_for_the_signatures(library):
    """Every setting — the core defaults (every level), each optional module's SETTINGS_DEFAULTS, and every key the
    dashboard's save writes — is placed in PLACED, and does what its place says when flipped in settings.json: an
    analysis setting moves the run signature (in the languages that read it), a report setting moves the render
    signature and never the run's, and any other moves neither. "_comment" notes are always neither."""
    _write({"target_language": "ja", "enable_koe": False})          # Speech revealed: the dashboard writes its keys
    keys = set(_paths(settings_manager.DEFAULT_SETTINGS))
    keys |= set(_paths(settings_manager._optional_module_defaults()))
    keys |= set(_paths(_dashboard_saved()))
    unplaced = sorted(path for path in keys if path not in PLACED and not path.endswith("._comment"))
    assert not unplaced, f"place each new setting in PLACED (analysis / report / neither): {unplaced}"
    gone = sorted(path for path in PLACED if path not in keys and _installed(path))
    assert not gone, f"settings that no longer exist: take them out of PLACED: {gone}"

    base = copy.deepcopy(settings_manager.load_settings())
    base["enable_koe"] = False
    base["logic"]["hide_audio_button"] = False
    wrong = []
    for path in sorted(keys):
        place = "neither" if path.endswith("._comment") else PLACED[path]
        start = dict(copy.deepcopy(base), **WHILE.get(path, {}))
        _write(start)
        before = {lang: _signatures(lang) for lang in LANGUAGES}
        _write(_with(path, _flip(path, _get(start, path)), start))
        after = {lang: _signatures(lang) for lang in LANGUAGES}
        run = {lang for lang in LANGUAGES if after[lang][0] != before[lang][0]}
        render = {lang for lang in LANGUAGES if after[lang][1] != before[lang][1]}
        if place.startswith("analysis"):
            expected = {place.split(":")[1]} if ":" in place else set(LANGUAGES)
            if run != expected:
                wrong.append(f"{path} ({place}): the run signature moved for {sorted(run) or 'neither language'}")
        elif place == "report":
            if run or render != set(LANGUAGES):
                wrong.append(f"{path} (report): run moved for {sorted(run)}, render for {sorted(render)}")
        elif run or render:
            wrong.append(f"{path} (neither): run moved for {sorted(run)}, render for {sorted(render)}")
    assert not wrong, "\n".join(wrong)
