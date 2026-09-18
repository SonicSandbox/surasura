
import pytest
import os
import re
import json
import shutil
import pandas as pd
from unittest.mock import patch, MagicMock
from app.static_html_generator import generate_static_html


def _fixture_csvs(tmp_path):
    """A one-word priority list for the generator to render.

    Without patching PRIORITY_CSV the generator falls through to the developer's real
    results/priority_learning_list.csv — 14 MB parsed by pandas and rendered in full. Two tests here
    did exactly that, which made this the slowest file in the suite (7.8s for 3 tests, 21% of the
    whole run) and quietly coupled them to whatever library the machine happened to hold.

    The progressive path is left non-existent on purpose: the generator guards it with
    os.path.exists, and none of these assertions need the per-file view."""
    priority = tmp_path / "priority_learning_list.csv"
    pd.DataFrame([
        {"Word": "冒険", "Reading": "ボウケン", "Tier": "Outside", "Score": 30, "Occurrences": 3,
         "Count (High)": 3, "Count (Low)": 0, "Count (Goal)": 0, "Sources": "a_novel.txt",
         "Context 1": "彼は毎日冒険に出かけます。"},
    ]).to_csv(priority, index=False, encoding="utf-8-sig")
    return priority, tmp_path / "progressive_learning_list.csv"


def test_html_generation(tmp_path):
    """
    Test that generate_static_html creates an output file and injects data.
    """
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    
    output_html = results_dir / "reading_list_static.html"
    
    # Needs a template file to read
    template_path = tmp_path / "web_app.html"
    with open(template_path, "w", encoding="utf-8") as f:
        f.write("<html><head></head><body><h1>Surasura List</h1><script>let globalData = null;</script></body></html>")
        
    # Mock paths and settings
    mock_settings = {
        "theme": "Default (Dark)",
        "target_language": "ja",
        "words_per_day": 5,
        "show_words_per_day": True,
        "logic": {"test": "data"}
    }
    priority_csv, progressive_csv = _fixture_csvs(tmp_path)
    with patch("app.static_html_generator.RESULTS_DIR", str(results_dir)), \
         patch("app.static_html_generator.OUTPUT_FILE", str(output_html)), \
         patch("app.static_html_generator.WEB_APP_FILE", str(template_path)), \
         patch("app.static_html_generator.PRIORITY_CSV", str(priority_csv)), \
         patch("app.static_html_generator.PROGRESSIVE_CSV", str(progressive_csv)), \
         patch("app.static_html_generator.settings_manager.load_settings", return_value=mock_settings), \
         patch("app.path_utils.get_icon_path", return_value="dummy_icon.png"):

         # Run generator
         generate_static_html(theme="default")
         
         assert output_html.exists()
         
         with open(output_html, "r", encoding="utf-8") as f:
             content = f.read()
             
         # Verify injection
         assert "let globalData = {" in content
         assert "let globalTheme = 'default';" in content
         assert "let globalLogic = {\"test\": \"data\"};" in content
         # Verify logo injection wasn't attempted if icon missing (mocked exists check? no, we didn't mock os.path.exists)
         # That's fine, we just want to ensure it runs without crashing.


def test_report_is_still_opened_after_generation(tmp_path):
    """Opening the report is INTENDED behaviour, not an accident of the tests.

    The suite-wide `no_browser_launch` fixture suppresses the real launch (several tests call
    generate_static_html purely to inspect the HTML, and a run used to spawn a browser tab each
    time). This test asserts the behaviour it suppresses still happens — and picks the right one
    for the window mode — so the fixture can never quietly turn the feature off.
    """
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    output_html = results_dir / "reading_list_static.html"
    template_path = tmp_path / "web_app.html"
    with open(template_path, "w", encoding="utf-8") as f:
        f.write("<html><head></head><body><script>let globalData = null;</script></body></html>")

    priority_csv, progressive_csv = _fixture_csvs(tmp_path)
    common = [
        patch("app.static_html_generator.RESULTS_DIR", str(results_dir)),
        patch("app.static_html_generator.OUTPUT_FILE", str(output_html)),
        patch("app.static_html_generator.WEB_APP_FILE", str(template_path)),
        patch("app.static_html_generator.PRIORITY_CSV", str(priority_csv)),
        patch("app.static_html_generator.PROGRESSIVE_CSV", str(progressive_csv)),
        patch("app.static_html_generator.settings_manager.load_settings", return_value={}),
    ]

    # Default: hand the report to the user's normal browser.
    with common[0], common[1], common[2], common[3], common[4], common[5], \
         patch("webbrowser.open") as mock_browser, \
         patch("app.static_html_generator.open_as_app") as mock_app:
        generate_static_html(theme="default")
        assert mock_browser.called, "the finished report must still be opened"
        assert not mock_app.called
        assert str(output_html) in mock_browser.call_args[0][0]

    # "Open in New Window": route through the app-mode launcher instead.
    with common[0], common[1], common[2], common[3], common[4], common[5], \
         patch("webbrowser.open") as mock_browser, \
         patch("app.static_html_generator.open_as_app") as mock_app:
        generate_static_html(theme="default", app_mode=True)
        assert mock_app.called, "app-mode must use the dedicated window launcher"
        assert not mock_browser.called


def test_injected_data_escapes_script_close(tmp_path):
    """A literal </script> in user content (a context sentence pulled from subtitles/ebooks)
    must be escaped so it cannot close the inline <script> block and blank the whole report
    (finding output-html-01)."""
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    output_html = results_dir / "reading_list_static.html"
    template_path = tmp_path / "web_app.html"
    with open(template_path, "w", encoding="utf-8") as f:
        f.write("<html><head></head><body><script>let globalData = null;</script></body></html>")

    # Priority CSV whose context tries to break out of the <script> block.
    priority_csv = results_dir / "priority_learning_list.csv"
    breakout = "</script><script>alert(1)</script>"
    pd.DataFrame([{"Word": "テスト", "Context 1": f"これは{breakout}です"}]).to_csv(
        priority_csv, index=False, encoding="utf-8"
    )

    mock_settings = {
        "theme": "Default (Dark)", "target_language": "ja",
        "words_per_day": 5, "show_words_per_day": True, "logic": {},
    }
    with patch("app.static_html_generator.RESULTS_DIR", str(results_dir)), \
         patch("app.static_html_generator.OUTPUT_FILE", str(output_html)), \
         patch("app.static_html_generator.WEB_APP_FILE", str(template_path)), \
         patch("app.static_html_generator.PRIORITY_CSV", str(priority_csv)), \
         patch("app.static_html_generator.PROGRESSIVE_CSV", str(tmp_path / "progressive_learning_list.csv")), \
         patch("app.static_html_generator.settings_manager.load_settings", return_value=mock_settings), \
         patch("app.path_utils.get_icon_path", return_value="dummy_icon.png"):
        generate_static_html(theme="default")

    content = output_html.read_text(encoding="utf-8")
    # The data still carries the text, but its closing tag is neutralised to <\/script>.
    assert "<\\/script>" in content
    # The raw breakout sequence must NOT survive into the document.
    assert breakout not in content


# --- D4: the report NAMES a word by `Orth` but KEYS it by `Word` --------------------------------
# `Word` is UniDic's canonical lemma: correct for counting (いう + 言う are one verb), wrong as a
# label — it is frequently a spelling nobody writes (スドウ for 須藤, 引き摺る for 引きずる). `Orth`
# is how the learner's own content spells it, so that is what the card shows. Everything that KEYS
# a word stays on `Word`; getting that backwards would orphan every ignore a user has saved.
#
# There is no JS engine in this suite, so the templates are asserted as string contracts (the
# convention here — see test_modality_badge.py / test_context_display_trim.py), alongside a Python
# mirror of the two-line helper and an end-to-end render that checks what the payload carries.

WEB_APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "templates", "web_app.html")
ZEN_APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "templates", "zen_app.html")

# The helper, byte-for-byte. Both templates duplicate the card builder rather than sharing it, so
# the resolution has to exist — identically — in each: a fix applied to only one silently leaves
# Zen users reading lemmas.
DISPLAY_WORD_JS = (
    "function displayWord(data) {\n"
    "            const orth = data.Orth;\n"
    "            return (typeof orth === 'string' && orth.trim()) ? orth : data.Word;\n"
    "        }"
)


def _read_template(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def display_word(data):
    """Python mirror of displayWord() in both templates, pinned to DISPLAY_WORD_JS above."""
    orth = data.get("Orth")
    return orth if isinstance(orth, str) and orth.strip() else data.get("Word")


def _orth_csv(tmp_path):
    """A priority list as the analyzer writes it since D4: the lemma and the spelling side by side.

    スドウ/須藤 is the most visible form of the bug — UniDic lemmatizes proper nouns to their
    reading — and 冒険 is the ordinary case where the two agree."""
    priority = tmp_path / "priority_with_orth.csv"
    pd.DataFrame([
        {"Word": "スドウ", "Orth": "須藤", "Reading": "スドウ", "Tier": "Outside", "Score": 30,
         "Occurrences": 4, "Sources": "a_novel.txt", "Context 1": "須藤は鳥取へ行く。"},
        {"Word": "冒険", "Orth": "冒険", "Reading": "ボウケン", "Tier": "Outside", "Score": 20,
         "Occurrences": 3, "Sources": "a_novel.txt", "Context 1": "彼は毎日冒険に出かけます。"},
    ]).to_csv(priority, index=False, encoding="utf-8")
    return priority


def _render(tmp_path, priority_csv):
    """Render the real template against `priority_csv` and return the injected globalData.

    PRIORITY_CSV is bound at import, so it MUST be patched — unpatched, this parses the
    developer's real 14 MB library (see tests/test_report_tests_are_isolated.py)."""
    results_dir = tmp_path / "results"
    results_dir.mkdir(exist_ok=True)
    output_html = results_dir / "reading_list_static.html"
    with patch("app.static_html_generator.RESULTS_DIR", str(results_dir)), \
         patch("app.static_html_generator.OUTPUT_FILE", str(output_html)), \
         patch("app.static_html_generator.PRIORITY_CSV", str(priority_csv)), \
         patch("app.static_html_generator.PROGRESSIVE_CSV", str(tmp_path / "missing_progressive.csv")), \
         patch("app.static_html_generator.settings_manager.load_settings",
               return_value={"target_language": "ja", "logic": {}}):
        generate_static_html(theme="default")

    html = output_html.read_text(encoding="utf-8")
    match = re.search(r"let globalData = (\{.*?\});\n", html, re.S)
    assert match, "the report was rendered without its data"
    return json.loads(match.group(1)), html


def _priority_rows(payload):
    """The compressed {keys, rows} payload back as dicts, the way the template expands it."""
    block = payload["priority"]
    return [dict(zip(block["keys"], row)) for row in block["rows"]]


def test_the_report_payload_carries_both_the_lemma_and_the_spelling(tmp_path):
    """The template needs both: `Orth` to name the card, `Word` to key the ignore list. Dropping
    either from the payload breaks one half of the feature."""
    payload, _html = _render(tmp_path, _orth_csv(tmp_path))
    rows = _priority_rows(payload)

    assert [r["Word"] for r in rows] == ["スドウ", "冒険"]
    assert [r["Orth"] for r in rows] == ["須藤", "冒険"]
    assert display_word(rows[0]) == "須藤", "the card must be named by the spelling the text uses"


def test_a_result_folder_without_an_orth_column_still_names_its_words(tmp_path):
    """Backward compatibility: results generated before D4 have no `Orth` column at all. The row
    simply has no such key, and the card falls back to the lemma rather than rendering blank."""
    priority, _progressive = _fixture_csvs(tmp_path)
    payload, _html = _render(tmp_path, priority)
    rows = _priority_rows(payload)

    assert "Orth" not in rows[0]
    assert display_word(rows[0]) == "冒険"


def test_a_blank_orth_falls_back_to_the_lemma(tmp_path):
    """The other half of the fallback: the column exists but the cell is empty (pandas gives NaN,
    which reaches the browser as the JS `NaN` value, not a string) or whitespace-only."""
    assert display_word({"Word": "スドウ", "Orth": ""}) == "スドウ"
    assert display_word({"Word": "スドウ", "Orth": "   "}) == "スドウ"
    assert display_word({"Word": "スドウ", "Orth": float("nan")}) == "スドウ"
    assert display_word({"Word": "スドウ", "Orth": None}) == "スドウ"


def test_both_templates_resolve_the_display_name_identically():
    """They duplicate the card builder, so the helper has to be present — and the same — in both."""
    for path in (WEB_APP, ZEN_APP):
        assert DISPLAY_WORD_JS in _read_template(path), f"{os.path.basename(path)} lost displayWord()"


def test_web_card_is_named_by_the_orth_at_every_render_site():
    html = _read_template(WEB_APP)
    # The full card and the compact sentence row both go through the helper.
    assert html.count("const word = displayWord(data);") == 2
    # The old direct read must not come back.
    assert "const word = data.Word;" not in html
    assert "const word = escapeHtml(data.Word);" not in html


def test_zen_card_is_named_by_the_orth_too():
    html = _read_template(ZEN_APP)
    assert "const word = displayWord(data);" in html
    assert "const word = data.Word;" not in html


def test_the_ignore_list_is_still_keyed_on_the_lemma():
    """The critical half. `ignoredWords` is persisted to localStorage and re-applied on every
    later render by `w.Word`, so the Ignore button must submit the LEMMA — ignoring 須藤 under its
    orth would write a key that filter can never match, and every previously saved ignore would
    stay hidden behind a key the report no longer produces."""
    html = _read_template(WEB_APP)
    assert "const safeLemma = escapeHtml(data.Word);" in html
    assert "onclick=\"ignoreWord('${safeLemma}', this)\"" in html
    assert "onclick=\"ignoreWord('${safeWord}', this)\"" not in html
    # The saved set and the filter that consumes it are untouched.
    assert "surasura_ignored_words_${langSuffix}" in html
    assert "ignoredWords.has(w.Word)" in html
