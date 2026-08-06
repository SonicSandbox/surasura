"""The ⌕ word-lookup button and its `\\` hotkey, in the main report template.

There is no JS engine in this suite, so the template is a string contract: these tests assert the
literal identifiers, classes and URL survive. That is the established convention here (see
test_modality_badge.py / test_sort_filter_feature.py), and it is what stops a rename from silently
removing a feature from the shipped report.

Unlike the 文 badge, this is deliberately a web_app-ONLY feature — Zen Mode has no card footer, no
Ignore button and none of the v/z/w/s hotkeys, and adding an outbound link there would break the
minimal reading surface it exists to be. test_zen_is_deliberately_untouched pins that decision so a
future reader doesn't "fix" the asymmetry by accident.
"""

import os

import pytest


@pytest.fixture
def web_html(project_root):
    with open(os.path.join(project_root, "templates", "web_app.html"), encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def zen_html(project_root):
    with open(os.path.join(project_root, "templates", "zen_app.html"), encoding="utf-8") as f:
        return f.read()


# --- the button ------------------------------------------------------------------------------- #

def test_button_renders_in_the_card_footer(web_html):
    assert 'class="btn-search"' in web_html
    assert "searchWord(this.dataset.word)" in web_html


def test_button_sits_to_the_left_of_ignore(web_html):
    """Placement is the requirement, not an accident — assert the order inside .actions."""
    stmt = web_html[web_html.index("footer.innerHTML ="):]
    stmt = stmt[:stmt.index("</div>`;") + len("</div>`;")]
    assert stmt.index("searchBtnHtml") < stmt.index("btn-ignore"), \
        "the lookup button must be concatenated before Ignore in the footer"


def test_word_travels_in_a_data_attribute_not_an_inline_js_string(web_html):
    """The documented rule for this file (see data-audio): a word interpolated into an onclick
    string breaks on any quote it contains, truncating the attribute."""
    assert 'data-word="${safeWord}"' in web_html, "must use the escaped word in a data-attribute"
    assert "searchWord('${" not in web_html, "word must not be interpolated into the onclick string"


def test_button_is_quiet_and_theme_tracking(web_html):
    """'Grayed out, out of the way' — borderless, half opacity, and coloured from the theme
    variable rather than a hard-coded hex, so it stays legible on the light theme too."""
    assert ".btn-search {" in web_html
    assert ".btn-search:hover {" in web_html
    css = web_html[web_html.index(".btn-search {"):web_html.index(".btn-search:hover {")]
    assert "border: none;" in css
    assert "opacity: 0.5;" in css
    assert "color: var(--text-secondary);" in css
    assert "fill: currentColor;" in web_html, "the icon must inherit the themed colour"


def test_button_carries_a_search_icon(web_html):
    """An icon button, not a text button — an inline SVG like .btn-audio, no external asset."""
    assert ".btn-search svg {" in web_html
    button_line = next(l for l in web_html.splitlines() if 'class="btn-search"' in l)
    idx = web_html.index(button_line)
    assert "<svg viewBox=\"0 0 24 24\">" in web_html[idx:idx + 1200]


# --- the URL ---------------------------------------------------------------------------------- #

def test_search_url_is_nadeshiko(web_html):
    assert "const WORD_SEARCH_URL = 'https://nadeshiko.co/en/search/';" in web_html


def test_word_is_url_encoded(web_html):
    """A lemma can carry a space or a slash; raw interpolation would truncate or re-path the URL.
    Japanese survives encodeURIComponent unchanged in the address bar."""
    assert "WORD_SEARCH_URL + encodeURIComponent(word)" in web_html


def test_opens_in_a_new_tab(web_html):
    """Reuses openInNewTab — window.open is unreliable from a file:// report."""
    fn = web_html[web_html.index("function searchWord(word)"):]
    fn = fn[:fn.index("\n        }")]
    assert "openInNewTab(" in fn


def test_blank_word_opens_nothing(web_html):
    """A row with no Word must not open a bare search page."""
    fn = web_html[web_html.index("function searchWord(word)"):]
    assert "if (!word) return;" in fn[:200]


# --- the hotkey ------------------------------------------------------------------------------- #

def test_backslash_is_declared_in_the_keydown_handler(web_html):
    assert "const isSearch = e.key === '\\\\';" in web_html


def test_backslash_survives_the_early_return_guard(web_html):
    """The real regression risk. The handler bails early on any key it doesn't know, so a flag
    declared but left out of that guard is dead — the button works and the hotkey silently doesn't.
    """
    guard = next(l for l in web_html.splitlines()
                 if "if (!isNext && !isPrev" in l and "return;" in l)
    assert "!isSearch" in guard, "isSearch missing from the keydown guard — the hotkey is dead"


def test_backslash_clicks_the_centered_cards_button(web_html):
    """Routes through the same button, so the two paths can't diverge."""
    block = web_html[web_html.index("if (isSearch) {"):]
    assert "querySelector('.btn-search')" in block[:400]


def test_backslash_does_not_advance_the_card(web_html):
    """Unlike `z`, you stay on the word you just looked up. `isNext` folds in `z` only."""
    is_next = next(l for l in web_html.splitlines() if "const isNext =" in l)
    assert "\\\\" not in is_next


def test_hotkey_is_listed_in_the_help_dialogue(web_html):
    hint = web_html[web_html.index('<div id="nav-hint">'):]
    hint = hint[:hint.index("</div>", hint.index("hint-tooltip"))]
    assert "<b>\\</b>" in hint, "the `\\` hotkey is missing from the Hotkeys Reference"
    assert "Search Word Online" in hint


# --- the settings: toggle + category ----------------------------------------------------------- #

def test_defaults_exist_and_are_on_and_unfiltered():
    """A feature that shipped visible must stay visible for anyone who never opens Settings."""
    from app.settings_manager import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["word_search_enabled"] is True
    assert DEFAULT_SETTINGS["word_search_category"] == "all"


def test_dashboard_offers_every_category(web_html):
    """The stored keys are sent to Nadeshiko verbatim as ?category=, so they are a contract."""
    from app.main import MasterDashboardApp
    assert list(MasterDashboardApp.WORD_SEARCH_LABELS) == ["all", "anime", "liveaction", "youtube"]


def test_unknown_category_label_falls_back_to_all():
    from app.main import MasterDashboardApp
    assert MasterDashboardApp._word_search_key("Anime") == "anime"
    assert MasterDashboardApp._word_search_key("Not a real option") == "all"


def test_toggle_hides_the_button_entirely(web_html):
    """'If not, it wont show' — the markup is never built, which is also what makes the hotkey
    correctly inert without needing its own check."""
    assert "const searchBtnHtml = !wordSearchEnabled() ? '' :" in web_html


def test_disabled_also_drops_the_hotkey_from_the_help_dialogue(web_html):
    assert 'id="hint-search"' in web_html
    assert "hintSearch.remove()" in web_html


def test_all_appends_no_query_other_categories_do(web_html):
    """'all' is the absence of a filter, so the plain URL must stay plain."""
    fn = web_html[web_html.index("function searchWord(word)"):]
    fn = fn[:fn.index("\n        }")]
    assert "category !== 'all' ? '?category=' + encodeURIComponent(category) : ''" in fn
    assert "WORD_SEARCH_URL + encodeURIComponent(word) + query" in fn


def test_missing_global_keeps_the_old_behaviour(web_html):
    """A report rendered before this option existed carries no globalWordSearch."""
    assert "typeof globalWordSearch !== 'undefined'" in web_html
    assert "wordSearchConfig().enabled !== false" in web_html, "absent config must mean 'shown'"


def test_category_is_validated_before_injection():
    """A hand-edited settings.json must not be able to put arbitrary text into the report's URL."""
    import inspect
    from app import static_html_generator
    src = inspect.getsource(static_html_generator.generate_static_html)
    assert '("all", "anime", "liveaction", "youtube")' in src
    assert 'word_search_category = "all"' in src


# --- the dashboard round-trip ------------------------------------------------------------------ #

def test_settings_round_trip_through_the_dashboard(tmp_path, monkeypatch):
    """load -> vars -> save must preserve both keys. A typo in either name fails silently: the
    control would work for the session and forget the choice on restart.

    Builds the real settings window (as test_flag_ui.py does) so the widgets are constructed too.
    """
    import tkinter as tk
    from app import settings_manager

    # Never write the developer's settings.json — testing.md §5.1.
    monkeypatch.setattr(settings_manager, "SETTINGS_FILE", str(tmp_path / "settings.json"),
                        raising=False)
    saved = {}
    monkeypatch.setattr(settings_manager, "save_settings", lambda s, **k: saved.update(s))
    monkeypatch.setattr(settings_manager, "load_settings",
                        lambda: {**settings_manager.get_default_settings(),
                                 "word_search_enabled": False,
                                 "word_search_category": "liveaction"})

    from app.main import MasterDashboardApp
    root = tk.Tk()
    root.withdraw()
    try:
        app = MasterDashboardApp(root)
        app.create_settings_window()

        # load_settings() ran during construction — the stored values must have reached the vars.
        assert app.var_word_search.get() is False
        assert app.var_word_search_category.get() == "liveaction"

        app.var_word_search.set(True)
        app.var_word_search_category.set("anime")
        app.save_settings()

        assert saved.get("word_search_enabled") is True
        assert saved.get("word_search_category") == "anime"
    finally:
        root.destroy()


def test_unknown_stored_category_falls_back_rather_than_breaking(tmp_path, monkeypatch):
    """A hand-edited or downgraded settings.json must not leave the combobox in a dead state."""
    import tkinter as tk
    from app import settings_manager

    monkeypatch.setattr(settings_manager, "save_settings", lambda s, **k: None)
    monkeypatch.setattr(settings_manager, "load_settings",
                        lambda: {**settings_manager.get_default_settings(),
                                 "word_search_category": "podcast"})

    from app.main import MasterDashboardApp
    root = tk.Tk()
    root.withdraw()
    try:
        app = MasterDashboardApp(root)
        assert app.var_word_search_category.get() == "all"
    finally:
        root.destroy()


# --- signature pairing (the part that silently breaks) ------------------------------------------ #

def test_settings_re_render_but_never_re_analyze():
    """Both keys are INJECTED, so they belong in the render signature and must be excluded from the
    run signature. Get this pair wrong and you either serve a stale report (missing from render) or
    force a full library re-analysis for a display toggle (present in run).
    """
    import inspect
    from app import analyzer
    run_src = inspect.getsource(analyzer.compute_run_signature)
    render_src = inspect.getsource(analyzer.compute_render_signature)
    for key in ("word_search_enabled", "word_search_category"):
        assert key in run_src, f"{key} missing from the run signature's non-analysis exclusions"
        assert key in render_src, f"{key} missing from the render signature — report goes stale"


def test_changing_a_setting_changes_the_render_signature(monkeypatch):
    """The exclusion list is only half of it — prove the render fingerprint actually moves."""
    import argparse
    from app import analyzer, settings_manager

    args = argparse.Namespace(theme="Dark Flow", zen_limit=50)
    base = dict(settings_manager.get_default_settings())

    def _with(**over):
        merged = {**base, **over}
        monkeypatch.setattr(settings_manager, "load_settings", lambda: merged)
        return analyzer.compute_render_signature(args)

    default = _with()
    assert _with(word_search_enabled=False) != default
    assert _with(word_search_category="anime") != default
    assert _with(word_search_category="all") == default


# --- scope ------------------------------------------------------------------------------------ #

def test_zen_is_deliberately_untouched(zen_html):
    """Zen has no footer, no Ignore and no action hotkeys — see this module's docstring."""
    assert "btn-search" not in zen_html
    assert "nadeshiko" not in zen_html


# --- end to end -------------------------------------------------------------------------------- #

def test_button_survives_into_the_generated_report(tmp_path, monkeypatch):
    """A template feature is useless if injection drops it. Renders a real report from a minimal
    CSV carrying genuine vocabulary and asserts the button and its URL arrive in the HTML.
    """
    import pandas as pd
    from app import static_html_generator

    results = tmp_path / "results"
    results.mkdir()

    rows = [
        # 聖文 is the word from the feature request; 覗き込む exercises a multi-character lemma.
        {"Word": "聖文", "Reading": "セイブン", "Tier": "Outside", "Score": 40,
         "Occurrences": 12, "Count (High)": 12, "Count (Low)": 0, "Count (Goal)": 0,
         "Modality": "", "Sources": "book.txt", "Context 1": "聖文を読み上げる。"},
        {"Word": "覗き込む", "Reading": "ノゾキコム", "Tier": "Outside", "Score": 30,
         "Occurrences": 9, "Count (High)": 9, "Count (Low)": 0, "Count (Goal)": 0,
         "Modality": "reading", "Sources": "book.txt", "Context 1": "窓を覗き込む。"},
    ]
    pd.DataFrame(rows).to_csv(results / "priority_learning_list.csv", index=False,
                              encoding="utf-8-sig")
    prog = [dict(r, Sequence=1, **{"Source File": "book.txt",
                                   "Occurrences (Global)": r["Occurrences"],
                                   "Occurrences (File)": r["Occurrences"]}) for r in rows]
    pd.DataFrame(prog).to_csv(results / "progressive_learning_list.csv", index=False,
                              encoding="utf-8-sig")

    # The generator resolves its paths ONCE at import, so each must be redirected individually —
    # patching RESULTS_DIR alone still writes into the developer's real results/ (testing.md §5.2).
    out = results / "reading_list_static.html"
    monkeypatch.setattr(static_html_generator, "RESULTS_DIR", str(results))
    monkeypatch.setattr(static_html_generator, "PRIORITY_CSV",
                        str(results / "priority_learning_list.csv"))
    monkeypatch.setattr(static_html_generator, "PROGRESSIVE_CSV",
                        str(results / "progressive_learning_list.csv"))
    monkeypatch.setattr(static_html_generator, "OUTPUT_FILE", str(out))

    static_html_generator.generate_static_html(theme="Dark Flow")

    html = out.read_text(encoding="utf-8")
    assert "https://nadeshiko.co/en/search/" in html
    assert 'class="btn-search"' in html
    assert "const isSearch = e.key === '\\\\';" in html
    # The settings the browser reads must arrive with them.
    assert "let globalWordSearch = " in html
    assert '"enabled": true' in html
    assert '"category": "all"' in html
    # The words themselves reach the payload, so the data-attribute has something to carry.
    # The word payload is dumped with the default ensure_ascii=True (static_html_generator.py:653),
    # so it arrives \u-escaped and the browser decodes it back — assert the form actually shipped.
    assert "\\u8056\\u6587" in html, "the word never reached the report payload"
