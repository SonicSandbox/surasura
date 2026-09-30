import app.analyzer as analyzer
from app.analyzer import _sanitize_term, load_yomitan_frequency_list, load_simple_list
import json
import os
import tempfile
import pytest

@pytest.fixture(autouse=True)
def reset_sanitize_ja():
    """Ensure SANITIZE_JA is reset after each test."""
    original = analyzer.SANITIZE_JA
    yield
    analyzer.SANITIZE_JA = original

def test_sanitize_term_analyzer():
    # Helper should always work when called directly
    assert _sanitize_term("アイリス-iris") == "アイリス"
    assert _sanitize_term("apple-fruit") == "apple"
    assert _sanitize_term(" 精霊 ") == "精霊"

def test_load_simple_list_toggle():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as tmp:
        tmp.write("アイリス-iris\n")
        tmp.write("精霊-spirit\n")
        tmp_path = tmp.name
    
    try:
        # Case 1: SANITIZE_JA = False
        analyzer.SANITIZE_JA = False
        results = load_simple_list(tmp_path)
        assert "アイリス-iris" in results
        assert "アイリス" not in results
        
        # Case 2: SANITIZE_JA = True
        analyzer.SANITIZE_JA = True
        results = load_simple_list(tmp_path)
        assert "アイリス" in results
        assert "アイリス-iris" not in results
    finally:
        os.remove(tmp_path)

def test_load_yomitan_frequency_list_respects_sanitize_toggle():
    # Frequency-list words are sanitized ONLY when JA term sanitization is active, so the loader
    # stays consistent with the analysis lemmas. Chinese (and JA with the toggle off) keep the
    # raw word instead of the Japanese -suffix stripper corrupting it (finding xc-lang-parity-01).
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as tmp:
        tmp.write("Word,Rank\n")
        tmp.write("アイリス-iris,1\n")
        tmp_path = tmp.name

    try:
        analyzer.SANITIZE_JA = False
        freq_data = load_yomitan_frequency_list(tmp_path)
        assert "アイリス-iris" in freq_data
        assert "アイリス" not in freq_data

        analyzer.SANITIZE_JA = True
        freq_data = load_yomitan_frequency_list(tmp_path)
        assert "アイリス" in freq_data
        assert "アイリス-iris" not in freq_data
    finally:
        os.remove(tmp_path)

# --------------------------------------------------------------------------- #
# A hiragana list line also names the kanji word it is typed for
# --------------------------------------------------------------------------- #
def _list_file(tmp_path, lines):
    path = tmp_path / "IgnoreList.txt"
    path.write_text("# my ignores\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def test_a_hiragana_line_also_ignores_the_kanji_word_it_is_typed_for(tmp_path):
    """The report's Ignore button writes lemmas (為る, 其れ); a line typed the way Japanese is written — する,
    ある, それ, こと — matched no lemma and ignored nothing. Read alone, each is ONE word spelled with a
    kanji and sounding as the line: that word is ignored too, and the line itself is kept."""
    analyzer.SANITIZE_JA = True
    lines = ["する", "ある", "それ", "こと", "冒険"]
    assert load_simple_list(_list_file(tmp_path, lines)) == set(lines) | {"為る", "有る", "其れ", "事"}


def test_a_kanji_line_or_a_line_read_as_another_sound_stays_the_lemma_it_names(tmp_path):
    """The user's Blacklist 為る reads alone as 成る — a kanji line is never read, so it never ignores なる.
    どん reads as 何の (ドノ) and いい as 良い (ヨイ): another sound, left as typed (an open question).
    かける reads as the name カケル, no kanji word. A katakana line is a lemma the report wrote for a loanword
    or a name (ハイ, read alone はい; コト, read alone 事), かっこいい is two words, お one kana (alone, the
    prefix 御) — none is read."""
    analyzer.SANITIZE_JA = True
    lines = ["為る", "どん", "いい", "かける", "ハイ", "コト", "かっこいい", "お", "そう-様態"]
    assert load_simple_list(_list_file(tmp_path, lines)) == \
        {"為る", "どん", "いい", "かける", "ハイ", "コト", "かっこいい", "お", "そう"}


def test_chinese_or_a_list_with_no_hiragana_line_builds_no_tokenizer_and_a_missing_one_changes_nothing(
        tmp_path, monkeypatch):
    """A Chinese list (SANITIZE_JA off) is read as it is written, even a kana line in it; a Japanese list
    with no hiragana line needs no tokenizer; and a tokenizer that cannot be built (fugashi missing)
    leaves the lines as they are — the list still loads, as it did before."""
    built = []

    class _NoTagger:
        def __init__(self):
            built.append(True)
            raise RuntimeError("fugashi is not installed")

    monkeypatch.setattr(analyzer, "JapaneseTokenizer", _NoTagger)
    analyzer.SANITIZE_JA = False
    assert load_simple_list(_list_file(tmp_path, ["东西", "する"])) == {"东西", "する"}
    analyzer.SANITIZE_JA = True
    assert load_simple_list(_list_file(tmp_path, ["為る", "冒険", "ハイ"])) == {"為る", "冒険", "ハイ"}
    assert built == [], "no hiragana line, no tokenizer"
    assert load_simple_list(_list_file(tmp_path, ["する", "冒険"])) == {"する", "冒険"}
    assert built == [True]


# --------------------------------------------------------------------------- #
# KnownWord.json's IGNORED entries (Migaku's status) are ignored words
# --------------------------------------------------------------------------- #
def _known_words(folder, entries, encoding="utf-8"):
    (folder / "KnownWord.json").write_bytes(json.dumps(
        {"words": [{"dictForm": form, "knownStatus": status} for form, status in entries]},
        ensure_ascii=False).encode(encoding))


def test_an_ignored_entry_in_the_known_words_file_is_ignored_as_a_list_line_is(tmp_path):
    """Migaku marks a word the user dismissed IGNORED. It is an ignored word, read as a line of the Ignore
    list is — a hiragana one also names the kanji word it is typed for (する -> 為る) — while KNOWN, LEARNING
    and UNKNOWN entries are not ignored. The Rarity preview reads the same entries, from the same reader, as
    plain lines like its lists. A file saved with a BOM reads the same."""
    from app import token_index
    analyzer.SANITIZE_JA = True
    _known_words(tmp_path, [("冒険", "IGNORED"), ("する", "IGNORED"), ("準備", "KNOWN"), ("危険", "LEARNING"),
                            ("価値", "UNKNOWN"), ("", "IGNORED")], "utf-8-sig")
    assert analyzer.load_ignored_entries(str(tmp_path), "asis", "ja") == {"冒険", "する", "為る"}
    assert token_index.preview_ignore_set(str(tmp_path), "ja") == {"冒険", "する"}


def test_a_chinese_ignored_entry_is_read_in_the_librarys_script_and_a_broken_file_ignores_nothing(tmp_path):
    """A Chinese library read in Simplified reads an IGNORED 學習 as 学习, as it reads its lists; a known
    words file that won't parse, or none at all, ignores nothing — Generate still runs."""
    from app import token_index
    analyzer.SANITIZE_JA = False
    _known_words(tmp_path, [("學習", "IGNORED")])
    assert analyzer.load_ignored_entries(str(tmp_path), "s", "zh") == {"学习"}
    assert token_index.preview_ignore_set(str(tmp_path), "zh", "s") == {"学习"}
    (tmp_path / "KnownWord.json").write_text("{\"words\": [", encoding="utf-8")
    assert analyzer.load_ignored_entries(str(tmp_path), "asis", "zh") == set()
    os.remove(tmp_path / "KnownWord.json")
    assert analyzer.load_ignored_entries(str(tmp_path), "asis", "zh") == set()
    assert token_index.preview_ignore_set(str(tmp_path), "zh") == set()


# --------------------------------------------------------------------------- #
# A known entry is cut at a gloss, never inside a sentence
# --------------------------------------------------------------------------- #
def test_a_known_sentence_with_a_space_stays_whole_and_every_word_in_it_is_known(tmp_path):
    """The Anki window's "Also read" field syncs whole sentences into the known words, and a subtitle line often holds
    a space, full width or half. The cut Migaku's glosses need (アイリス-iris) used to cut such a sentence at its
    space: only そうだ became known. It now cuts only when what follows the space or hyphen holds no Japanese."""
    analyzer.SANITIZE_JA = True
    full_width = "そうだ" + chr(0x3000) + "女の子だ"
    _known_words(tmp_path, [(full_width, "KNOWN"), ("雨が降った 傘を持った", "KNOWN"), ("アイリス-iris", "KNOWN"),
                            ("精霊-spirit", "KNOWN")])
    _tuples, lemmas = analyzer.load_known_words(str(tmp_path / "KnownWord.json"), analyzer.JapaneseTokenizer())
    assert {"そう", "女の子", "雨", "降る", "傘", "持つ"} <= lemmas, "every word of both sentences"
    assert {"アイリス", "精霊"} <= lemmas and not {"アイリス-iris", "iris", "精霊-spirit", "spirit"} & lemmas, \
        "a gloss is still cut off"


def test_the_known_word_cut_leaves_the_lemma_cut_as_it_was():
    """Only a known entry keeps a sentence whole: `_sanitize_term`, which the tokenizer's lemmas, the lists and the
    frequency lists read, still cuts at the first space or hyphen (UniDic's パーティー-party is パーティー)."""
    full_width = "そうだ" + chr(0x3000) + "女の子だ"
    assert analyzer._known_term(full_width) == full_width
    assert analyzer._known_term(" アイリス-iris ") == "アイリス"
    assert _sanitize_term(full_width) == "そうだ" and _sanitize_term("パーティー-party") == "パーティー"


if __name__ == "__main__":
    test_sanitize_term_analyzer()
    test_load_simple_list_toggle()
    test_load_yomitan_frequency_list_respects_sanitize_toggle()
    print("Sanitization tests for analyzer.py PASSED.")
