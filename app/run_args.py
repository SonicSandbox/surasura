"""Generate's analyzer arguments, from the settings: one builder for the window and the command line (P0.3 03, P1.2).

The dashboard reads its widgets into the settings' shape and calls `analyzer_args`; `surasura-cli generate` calls it
with settings.json as it is. Same settings, same argv, so a headless Generate and the window's hash to the same run
signature (`analyzer.compute_run_signature` reads these args) and skip each other's finished run.

Light by rule (02 §5): the standard library and `app.zh_script` only — no Tk, no pandas.
"""

from app.zh_script import effective as _effective_zh_script

# The report themes as the settings name them (the window's combobox) -> the analyzer's --theme.
THEME_ARGS = {
    "Default (Dark)": "default",
    "Dark Flow": "world-class",
    "Midnight (Vibrant)": "midnight-vibrant",
    "Modern Light": "modern-light",
    "Zen Mode": "zen-focus",
}


def analyzer_args(settings, language=None, headless=False):
    """The analyzer's argv (`['analyzer.py', ...]`) for Generate with `settings` (settings.json's shape).

    `language`: the one to generate (default: the settings' `target_language`). `headless`: started by another
    program (`surasura-cli generate`) — always `--no-open` and never `--app-mode`, so nothing opens on the desktop.
    Neither is in the run signature: the report a headless run writes is the one the window would reopen."""
    settings = settings or {}
    language = language or settings.get("target_language") or "ja"
    context = ((settings.get("logic") or {}).get("context") or {})
    args = ['analyzer.py']
    if not settings.get("exclude_single", True):
        args.append('--include-single-chars')

    if settings.get("strategy", "freq") == "coverage":
        args.append(f'--target-coverage={settings.get("target_coverage", 90)}')
    # else: density-band selection. The analyzer reads logic.selection (band + ppm floors)
    # from settings, which are saved before this run. Raw --min-freq is retired from the UI
    # (kept only as a CLI override); the band slider writes logic.selection.band.

    args.append('--static')
    args.append(f'--language={language}')

    # Chinese script: only when one is chosen, so an as-is run passes exactly the old args.
    zh_mode = _effective_zh_script(language, settings.get("zh_script", "asis"))
    if zh_mode != "asis":
        args.append(f'--zh-script={zh_mode}')

    if settings.get("ensure_audio_example", False):
        args.append('--ensure-audio-example')

    if settings.get("only_i_plus_one", False):
        args.append('--only-i-plus-one')

    args.append(f'--context-min={context.get("min_chars", 10)}')
    args.append(f'--context-max={context.get("preferred_max_chars", 50)}')

    max_c = context.get("max_contexts", 3)
    if max_c != 3:
        args.append(f'--max-contexts={max_c}')

    args.append(f'--theme={THEME_ARGS.get(settings.get("theme", "Dark Flow"), "default")}')

    if settings.get("open_app_mode", False) and not headless:
        args.append('--app-mode')

    # Zen Limit (passed to analyzer just in case, or for consistency)
    zen_limit = settings.get("zen_limit", 50)
    if zen_limit > 0:
        args.append(f'--zen-limit={zen_limit}')
    if headless:
        args.append('--no-open')
    return args
