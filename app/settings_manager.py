import json
import os
import copy
import importlib
from typing import Any, Dict
from app.path_utils import get_user_file

# --- SETTINGS TEMPLATE (DEFAULTS) ---
DEFAULT_SETTINGS = {
    "exclude_single": True,
    "min_freq": 3,
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
            "_comment": "min_chars/preferred_max_chars: ideal sentence length range. max_chars: hard cap — sentences longer than this are excluded from candidate examples (a word's own/original sentence is still kept as a fallback).",
            "search_range": 20,
            "min_chars": 10,
            "max_extra": 2,
            "preferred_max_chars": 50,
            "max_contexts": 3,
            "max_chars": 150
        },
        "sentence_boundaries": {
            "_comment": "Characters that trigger a sentence split for each language.",
            "ja": "\u3002\uff01\uff1f!?\n",
            "zh": "\u3002\uff01\uff1f!?\n\uff1b;\u2026\u2026"
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
