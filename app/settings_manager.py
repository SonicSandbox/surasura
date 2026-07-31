import json
import os
import copy
import importlib
from typing import Any, Dict
from app.path_utils import get_user_file

# --- SETTINGS TEMPLATE (DEFAULTS) ---
DEFAULT_SETTINGS = {
    "exclude_single": True,
    "open_app_mode": False,
    "theme": "Dark Flow",
    "strategy": "freq",
    "target_coverage": 90,
    "split_length": 3000,
    "target_language": "ja",
    "reinforce_segmentation": False,
    "telemetry_enabled": True,
    "words_per_day": 5,
    "show_words_per_day": True,
    "zen_limit": 50,
    "onboarding_completed": False,
    "open_count": 0,
    "hide_satoru": True,  # This is the "internal" default
    "only_i_plus_one": False,
    "add_graduated_words": True,
    "auto_update_enabled": True,   # one-click in-place updates for minor releases
    "skipped_version": "",          # a version the user skipped or that failed to auto-apply
    # Per-sentence source badge in the report: "off" | "icon" | "filename" | "full".
    # Presentation only — it never changes the analysis, just how each example sentence is labelled.
    "source_display": "off",
    "logic": {
        "inline_completed_files": False,
        "weights": {
            "_comment": "Multipliers for word scores based on folder. Higher = more important.",
            "high": 10,
            "low": 5,
            "goal": 2
        },
        "tiers": {
            "_comment": "Frequency rank thresholds for Tiers 1-4. Rank > last value = Tier 5.",
            "thresholds": [2500, 5000, 7500, 10000]
        },
        "context": {
            "_comment": "min_chars/preferred_max_chars: ideal sentence length range. max_chars: hard cap — sentences longer than this are excluded from candidate examples (a word's own/original sentence is still kept as a fallback). recency_files: tiebreaker only — among sentences that are otherwise equal (same i+1 cost, same length) prefer the one whose other words you met in this file or up to N files earlier; 0 = same file only, -1 = disable.",
            "search_range": 20,
            "min_chars": 10,
            "max_extra": 2,
            "preferred_max_chars": 50,
            "max_contexts": 3,
            "max_chars": 150,
            "recency_files": 1
        },
        "sentence_boundaries": {
            "_comment": "Characters that trigger a sentence split for each language. Includes the HALFWIDTH ideographic full stop \uff61, which anime subtitles use throughout (alongside halfwidth katakana) \u2014 without it their sentences never end and run together into one huge block.",
            "ja": "\u3002\uff61\uff01\uff1f!?\n",
            "zh": "\u3002\uff61\uff01\uff1f!?\n\uff1b;\u2026\u2026"
        },
        "gui": {
            "_comment": "tooltip_delay: ms before tooltip appears.",
            "tooltip_delay": 500
        },
        "priority_markers": {
            "_comment": "Star (Priority): (High+Low)/Total >= priority_threshold AND Total >= priority_min. Scale (Lopsided): High/Total >= lopsided_threshold.",
            "priority_threshold": 0.5,
            "priority_min": 3,
            "lopsided_threshold": 0.85
        },
        "selection": {
            "_comment": "Density-band word selection (used when top-level 'strategy' == 'freq'; 'coverage' uses target_coverage instead). bands_ppm: per-band parts-per-million floors — how common a word must be to be included; scale-stable across library sizes; 'native' is a tiny 1ppm floor (~= min_count on typical libraries). band: the chosen tier. min_count: universal floor that drops one-off words from every band. minutes_per_file: immersion minutes per file, for the 'meet each word every N hours' estimate. These are the single source of truth (no magic numbers in code).",
            "band": "occasional",
            "min_count": 2,
            "minutes_per_file": 18,
            "bands_ppm": {"core": 2000, "common": 150, "occasional": 25, "uncommon": 10, "rare": 4, "very_rare": 2.5, "native": 1}
        },
        "modality": {
            "_comment": "Reading-vs-listening card routing. target_hours: a word counts as 'you'll hear it' if fewer than this many hours of listening pass between encounters — estimated from bundled reference data (app/reference_data.py), then overridden by your OWN subtitle/YouTube files wherever you have enough material. Observation can only ever REMOVE a reading badge, never add one. min_series: distinct works a word must appear in before it counts as general vocabulary rather than one story's jargon; skipped entirely until the library holds min_library_series works, since on a small library that says more about the library than the word. min_lib_count: universal floor, as in selection.",
            "target_hours": 32.5,
            "min_series": 5,
            "min_lib_count": 3,
            "min_library_series": 10
        },
        "importer": {
            "_comment": "split_overflow: max chars to search past target length for a clean boundary.",
            "split_overflow": 150
        },
        "chunk_size": 50
    }
}

# Optional modules may each expose a SETTINGS_DEFAULTS dict. Their keys are merged into the
# active settings only when the module is importable, keeping optional features fully "tacked
# on": the core defaults (and the shipped settings.json) stay free of their keys, and a build
# without the module never sees or persists them.
_OPTIONAL_MODULE_NAMES = ["modules.youtube_downloader"]


def _optional_module_defaults() -> Dict[str, Any]:
    """Collect SETTINGS_DEFAULTS from any present optional modules."""
    merged: Dict[str, Any] = {}
    for name in _OPTIONAL_MODULE_NAMES:
        try:
            module = importlib.import_module(name)
            defaults = getattr(module, "SETTINGS_DEFAULTS", None)
            if isinstance(defaults, dict):
                merged.update(defaults)
        except Exception:
            pass
    return merged


def load_settings() -> Dict[str, Any]:
    """Loads settings from disk and merges with defaults (plus any present optional modules)."""
    settings_path = get_user_file("settings.json")
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    # Optional modules contribute their own defaults, but only when importable.
    settings.update(_optional_module_defaults())

    if os.path.exists(settings_path):
        try:
            with open(settings_path, 'r', encoding='utf-8') as f:
                user_settings = json.load(f)
                # Deep merge for 'logic'
                if "logic" in user_settings and isinstance(user_settings["logic"], dict):
                    user_logic = user_settings["logic"]
                    if not isinstance(settings.get("logic"), dict):
                        settings["logic"] = {}
                        
                    for key, value in user_logic.items():
                        if key == "weights" and isinstance(value, dict) and isinstance(settings["logic"].get("weights"), dict):
                            settings["logic"]["weights"].update(value)
                        elif isinstance(value, dict) and isinstance(settings["logic"].get(key), dict):
                            settings["logic"][key].update(value)
                        else:
                            settings["logic"][key] = value
                
                # Update top-level settings (excluding logic which we handled)
                for key, value in user_settings.items():
                    if key != "logic":
                        settings[key] = value
        except Exception as e:
            print(f"Warning: Could not load settings, using defaults: {e}")

    # Sentence boundaries are user-editable, but a few characters are STRUCTURAL — without them
    # sentences simply never end. A saved settings.json overrides the defaults wholesale, so a user
    # who has ever opened the app carries their old copy forever; that's how the halfwidth '｡'
    # (which anime subtitles use throughout) stayed missing and let example sentences run through a
    # dozen subtitle cues. Union the configured set with the required base: custom additions are
    # kept, the essentials can't be lost.
    try:
        _boundaries = settings.setdefault("logic", {}).setdefault("sentence_boundaries", {})
        for _lang, _required in DEFAULT_SETTINGS["logic"]["sentence_boundaries"].items():
            if _lang.startswith("_"):
                continue
            _current = _boundaries.get(_lang) or ""
            _boundaries[_lang] = _current + "".join(c for c in _required if c not in _current)
    except Exception:
        pass

    # Selection: bands_ppm / min_count / minutes_per_file are user-editable (like 'weights'), but
    # fill any MISSING keys from defaults so a partial or older settings.json can't break the band
    # structure (e.g. a file predating the 'very_rare' band). User-provided values still win.
    try:
        default_sel = DEFAULT_SETTINGS["logic"]["selection"]
        sel = settings.setdefault("logic", {}).setdefault("selection", {})
        ppm = copy.deepcopy(default_sel["bands_ppm"])
        if isinstance(sel.get("bands_ppm"), dict):
            ppm.update(sel["bands_ppm"])      # user floors override; missing bands stay default
        sel["bands_ppm"] = ppm
        sel.setdefault("band", default_sel["band"])
        sel.setdefault("min_count", default_sel["min_count"])
        sel.setdefault("minutes_per_file", default_sel["minutes_per_file"])
    except Exception:
        pass

    return settings

def save_settings(settings: Dict[str, Any], clean_for_build: bool = False):
    """
    Saves settings to disk.
    If clean_for_build is True, or if the module is missing, 'hide_satoru' is stripped.
    """
    settings_path = get_user_file("settings.json")
    
    # 1. Start with a copy to avoid mutating the app's state
    # Ensure settings is a dict before calling copy
    if not isinstance(settings, dict):
        print(f"Error: save_settings expected dict, got {type(settings)}")
        return
        
    to_save = copy.deepcopy(settings)
    
    # 2. Check for module availability
    module_exists = False
    try:
        import modules.immersion_architect
        module_exists = True
    except (ImportError, ModuleNotFoundError):
        module_exists = False

    # 3. Strip internal/locked variables if necessary
    if clean_for_build or not module_exists:
        to_save.pop("hide_satoru", None)

    # 4. Write to disk
    try:
        with open(settings_path, 'w', encoding='utf-8') as f:
            json.dump(to_save, f, indent=4)
    except Exception as e:
        print(f"Error: Could not save settings: {e}")

def get_default_settings() -> Dict[str, Any]:
    """Returns a fresh copy of default settings."""
    return copy.deepcopy(DEFAULT_SETTINGS)
