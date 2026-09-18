"""`anki_utils.clean_field_html` — turning one raw Anki field into the plain text Surasura stores.

The live Anki sync stores the cleaned field itself as a known word's `dictForm`, so anything the
cleaner leaves behind becomes a "word": a furigana reading fused onto its kanji (漢字かんじ), two
`<div>` lines fused into one nonsense token, a literal `&quot;`. Each case below is a shape real
decks produce (Lapis/Kiku bracket furigana, Yomitan ruby, AnkiMobile `<br>`), built on real Japanese
from `tests/Test Resources/ja/` — never ASCII placeholders (`testing.md` §1).

`extract_field_text` (the `.apkg` importer and the EPUB importer's path) now calls the same cleaner.
Its word fields must come out byte-identical on the existing `.apkg` fixtures; fields holding
multi-line HTML (dictionary glossaries) may only differ by the line breaks and whitespace the old
cleaner used to fuse — never by a character of text.
"""
import os
import re

import pytest

from app.anki_utils import clean_field_html, extract_field_text, load_anki_data, cleanup_temp_dir


@pytest.fixture
def ja_sentences(ja_resources_dir):
    """Real Japanese sentences from the shared test resources."""
    with open(os.path.join(ja_resources_dir, "context_test.txt"), "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


# --------------------------------------------------------------------------- #
# clean_field_html
# --------------------------------------------------------------------------- #
def test_ruby_readings_are_dropped_not_fused_onto_the_word():
    """<rt>/<rp> must go before tags are stripped, or the reading survives as text."""
    assert clean_field_html("<ruby>冒険<rp>(</rp><rt>ぼうけん</rt><rp>)</rp></ruby>家") == "冒険家"


def test_bracket_furigana_and_its_leading_space_are_removed():
    """Anki's {{furigana:}} syntax: ` 漢字[かな]`, with one ASCII space before each kanji group.
    Both go, so the stored word is the word — not `冒険[ぼうけん]` and not ` 冒険`."""
    assert clean_field_html(" 冒険[ぼうけん]") == "冒険"
    assert clean_field_html("彼は 毎日[まいにち] 冒険[ぼうけん]に 出[で]かけます。") == "彼は毎日冒険に出かけます。"
    assert clean_field_html("時々[ときどき]") == "時々", "々 belongs to the kanji group"


def test_brackets_that_are_not_furigana_survive():
    """Only a kana reading directly after kanji is furigana; anything else in brackets is content."""
    assert clean_field_html("[注意] 冒険") == "[注意] 冒険"
    assert clean_field_html("ねとり[2]") == "ねとり[2]"


def test_line_breaks_become_newlines_instead_of_fusing_lines(ja_sentences):
    """`<br>`, `</div>` and `</p>` end a line. Stripped without a newline, two sentences fuse and the
    tokenizer sees a word that spans them."""
    first, second, third = ja_sentences[3], ja_sentences[4], ja_sentences[5]
    raw = f"<div>{first}</div><div>{second}<br />{third}</div><p>冒険！</p>"
    assert clean_field_html(raw).split("\n") == [first, second, third, "冒険！"]
    assert clean_field_html(f"{first}<BR>{second}") == f"{first}\n{second}", "case-insensitive"


def test_html_entities_are_all_unescaped():
    """The old cleaner handled four entities by hand; `&quot;` and numeric ones leaked through."""
    assert clean_field_html("&quot;冒険&quot;&#12398;準備&amp;&lt;旅&gt;") == '"冒険"の準備&<旅>'


def test_sound_tags_and_markup_are_removed():
    raw = '<b>冒険</b>[sound:yomichan_ぼうけん.mp3]<img src="冒険.jpg">'
    assert clean_field_html(raw) == "冒険"


def test_whitespace_is_stripped_and_runs_collapse():
    """`&nbsp;` padding and editor-inserted spaces must not become part of the stored word."""
    assert clean_field_html("&nbsp; 冒険 &nbsp;&nbsp; 家\t ") == "冒険 家"
    assert clean_field_html("冒険\r\n\r\n\r\n危険") == "冒険\n危険", "CRLF and blank-line runs"


@pytest.mark.parametrize("raw", ["", None, "   ", "<br><div></div>", "[sound:冒険.mp3]", "&nbsp;"])
def test_an_empty_field_cleans_to_an_empty_string(raw):
    """Empty after cleaning means "no word here" to every caller — never None, never whitespace."""
    assert clean_field_html(raw) == ""


def test_a_chinese_field_passes_through_cleanly():
    """The zh path is identical; pinyin in brackets is not kana furigana and is left alone."""
    assert clean_field_html("<div>冒险</div><div>汉字[hàn zì]</div>") == "冒险\n汉字[hàn zì]"


# --------------------------------------------------------------------------- #
# extract_field_text on the existing .apkg fixtures
# --------------------------------------------------------------------------- #
def _legacy_extract(notes, model_field_map, target_field):
    """The pre-clean_field_html cleaner, kept verbatim as the oracle for "unchanged output"."""
    tag_re = re.compile(r'<[^<]+?>')
    sound_re = re.compile(r'\[sound:[^\]]+?\]')
    ruby_re = re.compile(r'<rp>.*?</rp>|<rt>.*?</rt>', re.IGNORECASE | re.DOTALL)
    lines = []
    for mid, flds in notes:
        fields = [name.lower() for name in model_field_map.get(mid, [])]
        if target_field.lower() not in fields:
            continue
        values = flds.split('\x1f')
        idx = fields.index(target_field.lower())
        if idx < len(values):
            text = sound_re.sub('', tag_re.sub('', ruby_re.sub('', values[idx])))
            text = text.replace('&nbsp;', ' ').replace('&gt;', '>').replace('&lt;', '<').replace('&amp;', '&')
            if text.strip():
                lines.append(text.strip())
    return "\n".join(lines)


# The word fields each fixture deck actually carries; these must come out byte-identical.
WORD_FIELDS = [("testAnki.apkg", "Expression"), ("testAnki2.apkg", "Front"),
               ("ankiTest3.apkg", "Front"), ("ankiTest3.apkg", "Sentence")]


@pytest.mark.parametrize("apkg, field", WORD_FIELDS)
def test_extract_field_text_word_fields_are_unchanged_on_real_decks(ja_resources_dir, apkg, field):
    """The `.apkg` importer's known-words output must not shift under existing users."""
    path = os.path.join(ja_resources_dir, apkg)
    if not os.path.exists(path):
        pytest.skip(f"{apkg} not found")
    _fields, notes, model_map, temp_dir = load_anki_data(path)
    try:
        new = extract_field_text(notes, model_map, field)
        assert new, f"{field} extracted nothing from {apkg}"
        assert new == _legacy_extract(notes, model_map, field)
    finally:
        cleanup_temp_dir(temp_dir)


@pytest.mark.parametrize("apkg", ["testAnki.apkg", "testAnki2.apkg", "ankiTest3.apkg"])
def test_extract_field_text_only_changes_line_breaks_and_spacing(ja_resources_dir, apkg):
    """Every field of every fixture: the new cleaner may split fused lines (glossaries built of
    `<div>`s) and collapse spaces, but must never add or lose a single non-space character."""
    path = os.path.join(ja_resources_dir, apkg)
    if not os.path.exists(path):
        pytest.skip(f"{apkg} not found")
    fields, notes, model_map, temp_dir = load_anki_data(path)
    try:
        for field in fields:
            new = extract_field_text(notes, model_map, field)
            old = _legacy_extract(notes, model_map, field)
            assert "".join(new.split()) == "".join(old.split()), f"{apkg}:{field} lost or gained text"
            assert "<div>" not in new and "[sound:" not in new
    finally:
        cleanup_temp_dir(temp_dir)
