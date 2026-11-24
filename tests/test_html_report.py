"""The report's data, after the old journey page retired (J-RETIRE, 2026-11-23): the journey page carries each
word's lemma and spelling and never the automation switch; the YouTube preview's page (templates/web_app.html,
`modules/youtube_downloader/preview.py`) names a card by its spelling and keys Ignore on its lemma.

Retired with the old page, held on the journey page elsewhere: the page written and opened after a Generate and a
quiet one never opening it (test_journey_cutover's `test_the_automatic_generate_writes_the_journey_without_opening_it`),
data that can't end its <script> early (`test_a_sentence_or_a_file_name_holding_a_script_close_never_breaks_the_page`).
"""
import gzip
import json
import os


def test_the_report_never_embeds_d29s_automation_switch():
    """`logic.automation` (D29, 3.0) is read by no page and placed "neither": the journey page's settings are its own
    rows (`journey_render.page_settings`), so the switch never reaches the page and flipping it never re-renders."""
    from app import journey_render as jr
    for automation in (True, False):
        settings = {"target_language": "ja", "logic": {"automation": automation}}
        assert "automation" not in json.dumps(jr.page_settings(settings))
        assert jr.page_settings(settings) == jr.page_settings({"target_language": "ja", "logic": {}})
    assert settings["logic"]["automation"] is False, "the loaded settings are never changed in place"


# There is no JS engine in this suite, so the templates are asserted as string contracts (the
# convention here — see test_modality_badge.py / test_context_display_trim.py), alongside a Python
# mirror of the two-line helper and an end-to-end render that checks what the payload carries.

WEB_APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "templates", "web_app.html")

# The helper, byte-for-byte, in the YouTube preview's page (web_app.html; Zen's page, which duplicated it, retired
# with the old journey page, J-RETIRE 2026-11-23).
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
    """Python mirror of displayWord() in web_app.html, pinned to DISPLAY_WORD_JS above."""
    orth = data.get("Orth")
    return orth if isinstance(orth, str) and orth.strip() else data.get("Word")


def _records(language, rows):
    """The journey page's word records for `rows` (`journey_render.build`): [word, orth, reading, kana, forms, …]."""
    from app import journey_render as jr
    out = jr.build(language, rows, [{"File": "ep01.srt", "Total Words": 10, "Known Count": 8, "Coverage (%)": 80.0}],
                   stamp=1)
    return [w for blob in out.chunks for w in json.loads(gzip.decompress(blob).decode("utf-8"))["w"]]


def _row(word, orth=None):
    """A progressive row as the analyzer writes it since D4: the lemma and the spelling side by side (no `Orth` key:
    a result folder from before D4). スドウ/須藤 is the most visible form of the bug — UniDic lemmatizes proper nouns to
    their reading."""
    row = {"Sequence": 1, "Source File": "ep01.srt", "Word": word, "Reading": "スドウ", "Forms": "",
           "Occurrences (Global)": 4.0, "Occurrences (File)": 4.0, "Count (High)": 4.0, "Count (Low)": 0.0,
           "Context 1": "須藤は鳥取へ行く。", "Src 1": "Show/ep01.srt"}
    if orth is not None:
        row["Orth"] = orth
    return row


def test_the_report_payload_carries_both_the_lemma_and_the_spelling():
    """The journey page needs both: the spelling to name the word (`w[1] || w[0]`), the lemma to key it (Anki, the
    word's id). Dropping either breaks one half (ported from the old page's globalData, J-RETIRE). A spelling the
    lemma already is is left out (the page's fallback names it)."""
    records = _records("ja", [_row("スドウ", "須藤"), {**_row("冒険", "冒険"), "Reading": "ボウケン"}])
    assert [(w[0], w[1]) for w in records] == [("スドウ", "須藤"), ("冒険", "")]


def test_a_result_folder_without_an_orth_column_still_names_its_words():
    """Backward compatibility: results generated before D4 have no `Orth` column at all — the record's spelling is
    empty and the page names the word by its lemma (`w[1] || w[0]`), never blank."""
    records = _records("ja", [_row("冒険")])
    assert records[0][0] == "冒険" and records[0][1] == ""
    page = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "journey",
                             "page.html"), encoding="utf-8").read()
    assert "esc(w[1] || w[0])" in page


def test_a_blank_orth_falls_back_to_the_lemma(tmp_path):
    """The other half of the fallback: the column exists but the cell is empty (pandas gives NaN,
    which reaches the browser as the JS `NaN` value, not a string) or whitespace-only."""
    assert display_word({"Word": "スドウ", "Orth": ""}) == "スドウ"
    assert display_word({"Word": "スドウ", "Orth": "   "}) == "スドウ"
    assert display_word({"Word": "スドウ", "Orth": float("nan")}) == "スドウ"
    assert display_word({"Word": "スドウ", "Orth": None}) == "スドウ"


def test_the_preview_page_resolves_the_display_name():
    assert DISPLAY_WORD_JS in _read_template(WEB_APP), "web_app.html lost displayWord()"


def test_web_card_is_named_by_the_orth_at_every_render_site():
    html = _read_template(WEB_APP)
    # The full card and the compact sentence row both go through the helper.
    assert html.count("const word = displayWord(data);") == 2
    # The old direct read must not come back.
    assert "const word = data.Word;" not in html
    assert "const word = escapeHtml(data.Word);" not in html


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
