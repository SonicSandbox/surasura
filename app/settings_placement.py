"""Where each setting belongs (W1.3; the window's spec 04 §4.2): `analysis` — a run reads it, so the run signature
moves (in both languages, or only in the one named: "analysis:ja"); `report` — only the report shows it, so the render
signature moves and the run's doesn't; `neither` — no run and no report reads it.

Moved here from tests/test_settings_signatures.py, which still proves every entry by flipping it and fails on a setting
nobody placed: place a new setting when you add it. Until it is placed, compute_run_signature hashes it — a needless
run at worst, never a stale list — so `kind()` answers "analysis" for it. The settings service (`app/services/
settings.py`) asks `kind()` whether a change makes the journey stale.

Pure: no Tk, no Qt, no pandas.
"""
import importlib.util

PLACED = {
    "exclude_single": "analysis:ja", "open_app_mode": "neither", "theme": "report", "strategy": "analysis",
    "target_coverage": "analysis", "split_length": "neither", "target_language": "analysis",
    "zh_script": "analysis:zh", "telemetry_enabled": "neither", "words_per_day": "report",
    "show_words_per_day": "report", "zen_limit": "report", "onboarding_completed": "neither", "open_count": "neither",
    "only_i_plus_one": "analysis", "ensure_audio_example": "analysis",
    "add_graduated_words": "neither", "auto_update_enabled": "neither", "skipped_version": "neither",
"source_display": "report", "word_search_enabled": "report",
    "word_search_category": "report", "sentence_dictionary_source": "neither", "index_pool_workers": "neither",
    "anki_connect_url": "neither",
    "connect_enabled": "neither", "placing_rules": "neither", "connect_mine_words": "neither",
    "connect_send_grammar": "neither", "connect_anki_miner_path": "neither", "connect_anki_miner_profile": "neither",
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
    "junban_tag_markers": "neither", "junban_unlisted": "neither",
    "junban_word_fields": "neither", "junban_write_freqsort": "neither", "junban_write_frequency": "neither",
}
# Which optional module a setting belongs to: without the module (a checkout without modules/) it doesn't exist.
OWNERS = (("junban_", "modules.junban"), ("enable_junban", "modules.junban"), ("koe_", "modules.koe"),
          ("enable_koe", "modules.koe"), ("reels_", "modules.reels"), ("enable_reels", "modules.reels"),
          ("enable_youtube_", "modules.youtube_downloader"), ("youtube_", "modules.youtube_downloader"))


def _installed(path):
    """Whether the optional module `path` belongs to is installed — a core setting always is."""
    owner = next((module for prefix, module in OWNERS if path.startswith(prefix)), None)
    try:
        return owner is None or importlib.util.find_spec(owner) is not None
    except ImportError:
        return False


def kind(key, language):
    """What changing `key` (a top-level key, or a dotted `logic.…` path) means for `language`: "analysis", "report"
    or "neither". A key under a placed one is the placed one's (`logic.selection.bands_ppm.rare`); "_comment" notes are
    neither; an unplaced key is "analysis", as the run signature counts it."""
    if key.endswith("._comment") or key == "_comment":
        return "neither"
    path = key
    while path not in PLACED and "." in path:
        path = path.rsplit(".", 1)[0]
    place = PLACED.get(path)
    if place is None:
        return "analysis"
    if place.startswith("analysis:"):
        return "analysis" if place.split(":", 1)[1] == language else "neither"
    return place
