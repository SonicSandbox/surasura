"""A file's encoding is a property of the FILE, not of its text.

Every reader used to open a user's file as UTF-8. A CP932 subtitle, a UTF-16 or GBK text file
contributed nothing — silently — and a KnownWord.json or a word list saved with a BOM, as UTF-16
(Notepad's "Unicode") or in Windows' "ANSI" stopped Generate. `path_utils.read_text` is now the one
reader: a BOM names the encoding; otherwise strict UTF-8; otherwise the language's Windows
encodings, each tried strictly — CP932 for Japanese; GB18030, then Big5 as Windows writes it (cp950)
for Chinese — the first that reads the file as standard characters winning (a reading holding a
Private Use character is not taken). Nothing is dropped silently: a file no encoding reads whole is
read with each bad sequence marked U+FFFD and a warning, or refused outright by a caller that writes
the file back.

Every file below is real Japanese / Chinese — the repo's own test resources and samples — written
at test time in the encoding under test, byte for byte as an editor saves it.
"""
import codecs
import json
import os
from types import SimpleNamespace

import pytest

from app import analyzer, path_utils, settings_manager, token_index
from app.path_utils import read_text

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RES = os.path.join(_ROOT, "tests", "Test Resources")


def _resource(*parts):
    with open(os.path.join(*parts), encoding="utf-8-sig") as f:
        return f.read()


JA = _resource(_RES, "ja", "context_test.txt")                   # 冒険だ。 … 冒険！ (11 lines)
ZH = _resource(_RES, "zh", "context_test.txt")                   # 冒险。 … 冒险！ (Simplified)
TW = _resource(_RES, "zh", "traditional_news.txt")               # 台灣經濟部今天公布… (Traditional)
SAMPLE_SRT = os.path.join(_ROOT, "samples", "ja", "HighPriority", "H_priority_sample_2.srt")
# Its first 300 cues (of 424), CRLF as the file has them: the three after close a quote with 〞, which
# CP932 has no byte for (a CP932 release writes 〟) — so these are what a legacy copy can hold.
SAMPLE_CUES = "\r\n\r\n".join(_resource(SAMPLE_SRT).split("\n\n")[:300]).replace("\n", "\r\n") + "\r\n"


def _save(folder, name, text, encoding):
    """`text` saved as an editor saves it: 'utf-16' writes its BOM (little-endian here), a
    'utf-16-be' file is given its BOM by hand as Notepad's "Unicode big endian" does."""
    raw = text.encode(encoding)
    if encoding == "utf-16-be":
        raw = codecs.BOM_UTF16_BE + raw
    path = os.path.join(str(folder), name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(raw)
    return path


def _write_bytes(folder, name, raw):
    path = os.path.join(str(folder), name)
    with open(path, "wb") as f:
        f.write(raw)
    return path


# --- the rule: every encoding an editor saves reads back as the same text --------------------------- #
@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "utf-16-be", "utf-32", "cp932"])
def test_japanese_reads_back_the_same_in_every_encoding_an_editor_saves(tmp_path, encoding):
    """UTF-8 with or without a BOM, UTF-16 either way round and UTF-32 (their BOM decides — UTF-32
    LE's begins with UTF-16 LE's), and Shift_JIS as Japanese Windows writes it (CP932): one text,
    whatever the bytes."""
    path = _save(tmp_path, "novel.txt", JA, encoding)
    assert read_text(path, "ja") == JA


@pytest.mark.parametrize("text, encoding", [(ZH, "utf-8"), (ZH, "utf-8-sig"), (ZH, "utf-16"), (ZH, "gbk"),
                                            (ZH, "gb18030"), (TW, "big5"), (TW, "cp950")])
def test_chinese_reads_back_the_same_in_every_encoding_an_editor_saves(tmp_path, text, encoding):
    """Simplified in GBK / GB18030 (mainland Windows' "ANSI"), Traditional in Big5 (Taiwan's)."""
    path = _save(tmp_path, "news.txt", text, encoding)
    assert read_text(path, "zh") == text


def test_big5_is_read_as_big5_although_gb18030_also_decodes_it(tmp_path):
    """The trap the evidence rule exists for: GB18030 reads almost any byte pair, so Big5 decodes
    as GB18030 without an error — into nonsense holding Private Use characters (every Big5 ，。
    is one). The Big5 reading, which holds none, wins."""
    raw = TW.encode("big5")
    wrong = raw.decode("gb18030")                          # no error: the trap is real
    assert wrong != TW and any("\ue000" <= ch <= "\uf8ff" for ch in wrong)
    assert read_text(_write_bytes(tmp_path, "news.txt", raw), "zh") == TW


def test_gbk_is_still_read_as_gbk_when_big5_could_decode_it_too(tmp_path):
    """The other way round: a short GBK line is also valid Big5 (nonsense). GB18030 comes first and
    reads it cleanly, so Big5 is never considered."""
    line = "我们走吧。\n"
    raw = line.encode("gbk")
    assert raw.decode("big5") != line                      # Big5 would accept it — wrongly
    assert read_text(_write_bytes(tmp_path, "line.txt", raw), "zh") == line


def test_big5_as_windows_writes_it_keeps_its_eten_characters(tmp_path):
    """Code page 950 carries 恒 裏 碁 (F9D6–F9DC) and €, which the plain Big5 table refuses: one 恒
    must not cost the whole file."""
    line = "他們的友誼是永恒的，裏面還有€。\n"
    raw = line.encode("cp950")
    with pytest.raises(UnicodeDecodeError):
        raw.decode("big5")
    assert read_text(_write_bytes(tmp_path, "friend.txt", raw), "zh") == line


def test_half_width_katakana_in_cp932_is_read_as_written(tmp_path):
    """CP932's single-byte katakana (ｶﾀｶﾅ) decode as written; making them ナイフ is NFKC's job
    (another fix), not the reader's."""
    line = "ﾅｲﾌを持って冒険に出かけた。\n"
    assert read_text(_save(tmp_path, "knife.txt", line, "cp932"), "ja") == line


def test_empty_and_bom_only_files_read_as_empty_text(tmp_path):
    """An empty file — or one holding nothing but its BOM — is no text in any encoding: it reads as
    "" and stops nothing, down every content path."""
    for n, raw in enumerate((b"", codecs.BOM_UTF8, codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE, codecs.BOM_UTF32_LE)):
        for ext in (".txt", ".srt", ".ass"):
            path = _write_bytes(tmp_path, f"empty{n}{ext}", raw)
            assert read_text(path, "ja") == ""
            assert analyzer.extract_text(path, "ja") == ""


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "cp932"])
def test_crlf_lf_and_a_lone_cr_all_end_a_line(tmp_path, encoding):
    """A file edited on two machines mixes line ends; each is a line end, as open() reads them, and
    no \\r survives — in UTF-16 too, where the \\r is two bytes."""
    lines = JA.splitlines()
    mixed = lines[0] + "\r\n" + lines[1] + "\n" + lines[2] + "\r" + lines[3] + "\r\n"
    text = read_text(_save(tmp_path, "mixed.txt", mixed, encoding), "ja")
    assert text == "\n".join(lines[:4]) + "\n"
    assert "\r" not in text


# --- nothing is dropped silently ------------------------------------------------------------------ #
def _damaged(text):
    """`text` as UTF-8 with one stray byte after its first line — at a character boundary, so the
    damage is exactly one byte."""
    raw = text.encode("utf-8")
    cut = raw.index(b"\n") + 1
    return raw[:cut] + b"\xff" + raw[cut:], cut


def test_a_damaged_file_keeps_every_character_but_the_bad_byte_and_says_so(tmp_path, capsys):
    """No encoding reads it whole, so it is read as UTF-8 with the bad byte marked U+FFFD — visible,
    never dropped as errors='ignore' did — and a warning names the file."""
    raw, cut = _damaged(JA)
    text = read_text(_write_bytes(tmp_path, "damaged.txt", raw), "ja")
    first = JA.index("\n") + 1
    assert text == JA[:first] + "\ufffd" + JA[first:]
    assert "damaged.txt" in capsys.readouterr().out


def test_a_short_damaged_file_is_not_taken_for_shift_jis(tmp_path):
    """CP932 as Python decodes it gives the bytes it has no character for (0xA0, 0xFD–0xFF) Private
    Use characters instead of failing, so a short UTF-8 file with one such stray byte "reads" as
    Shift_JIS mojibake. A reading holding a Private Use character is not taken: the file is UTF-8,
    marked where it is damaged."""
    raw = "冒険".encode("utf-8") + b"\xff"
    assert raw.decode("cp932")                             # no error: the trap is real
    assert read_text(_write_bytes(tmp_path, "tiny.txt", raw), "ja") == "冒険\ufffd"


def test_strict_reading_refuses_a_damaged_file(tmp_path):
    """A caller that writes the file back (the Anki sync, the importers) must not keep a guess."""
    raw, _cut = _damaged(JA)
    with pytest.raises(UnicodeDecodeError):
        read_text(_write_bytes(tmp_path, "damaged.txt", raw), "ja", errors="strict")


def test_without_a_language_no_legacy_encoding_is_guessed(tmp_path, capsys):
    """CP932 is Japanese Windows' encoding, GBK Chinese Windows': with no language to say which, the
    bytes are marked, not guessed at."""
    path = _save(tmp_path, "ansi.txt", JA, "cp932")
    assert read_text(path, "ja") == JA
    assert "\ufffd" in read_text(path)
    assert "ansi.txt" in capsys.readouterr().out


# --- KnownWord.json: the crash the plan names ------------------------------------------------------- #
def _known_json(words):
    return json.dumps({"words": [{"dictForm": w, "knownStatus": "KNOWN"} for w in words]}, ensure_ascii=False)


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "cp932"])
def test_a_known_words_file_saved_by_notepad_no_longer_stops_generate(tmp_path, encoding):
    """THE crash: json.load refused a BOM ("Unexpected UTF-8 BOM") and a UTF-16 / CP932 file failed
    to decode — load_known_words raised and Generate stopped. Each now loads its words."""
    path = _save(tmp_path, "KnownWord.json", _known_json(["冒険", "準備", "価値"]), encoding)
    _tuples, lemmas = analyzer.load_known_words(path, analyzer.JapaneseTokenizer())
    assert {"冒険", "準備", "価値"} <= lemmas


def test_a_chinese_known_words_file_in_gbk_loads_through_the_chinese_tokenizer(tmp_path, zh_resources_dir):
    """The tokenizer names the language, so a Chinese file's GBK is tried, not CP932. The repo's own
    Chinese known-words fixture, re-saved as GBK."""
    with open(os.path.join(zh_resources_dir, "KnownWords.json"), encoding="utf-8") as f:
        data = f.read()
    path = _save(tmp_path, "KnownWord.json", data, "gbk")
    _tuples, lemmas = analyzer.load_known_words(path, analyzer.ChineseTokenizer())
    expected = {w["dictForm"] for w in json.loads(data)["words"] if w.get("knownStatus") == "KNOWN"}
    assert expected and expected <= lemmas


def test_a_missing_known_words_file_is_still_just_empty(tmp_path):
    """Nothing to read is not an error (a brand-new install)."""
    assert analyzer.load_known_words(str(tmp_path / "KnownWord.json"), analyzer.JapaneseTokenizer()) == (set(), set())


# --- the word lists and the frequency lists ------------------------------------------------------------ #
def test_a_word_list_saved_with_a_bom_matches_its_first_entry(tmp_path):
    """The BOM stuck to the first line, so a list starting with a word (not a # comment) never
    ignored that word — with or without a language to say which legacy encodings to try."""
    path = _save(tmp_path, "IgnoreList.txt", "一人\r\n彼\r\n", "utf-8-sig")
    assert analyzer.load_simple_list(path, language="ja") == {"一人", "彼"}
    assert analyzer.load_simple_list(path) == {"一人", "彼"}


@pytest.mark.parametrize("lang, lines, encoding", [("ja", "# 無視する\n一人\n彼\n", "utf-16"),
                                                   ("ja", "一人\r\n彼\r\n", "cp932"),
                                                   ("zh", "冒险\r\n勇者\r\n", "gbk"),
                                                   ("zh", "冒險\r\n勇者\r\n", "utf-16")])
def test_a_word_list_saved_as_utf16_or_ansi_no_longer_stops_generate(tmp_path, lang, lines, encoding):
    """UnicodeDecodeError out of load_simple_list stopped the run for every list the analyzer merges
    (Ignore, Blacklist, Graduated). Now each reads its entries."""
    path = _save(tmp_path, "Blacklist.txt", lines, encoding)
    expected = {line.strip() for line in lines.splitlines() if line.strip() and not line.startswith("#")}
    assert analyzer.load_simple_list(path, language=lang) == expected


@pytest.mark.parametrize("encoding", ["utf-8-sig", "cp932"])
def test_a_frequency_list_saved_by_excel_loads_its_words(tmp_path, encoding):
    """Excel's "CSV UTF-8" starts with a BOM, which glued to the Word header skipped every row —
    0 words, silently. Japanese Excel's plain CSV is CP932, which failed to load at all."""
    path = _save(tmp_path, "frequency_list_ja_Novel.csv", "Word,Rank\r\n冒険,1500\r\n準備,820\r\n", encoding)
    assert analyzer.load_yomitan_frequency_list(path, language="ja") == {"冒険": 1500, "準備": 820}


# --- subtitles: every format through the analyzer's own path ---------------------------------------------- #
def test_pysrt_reads_the_real_sample_exactly_as_before(tmp_path):
    """extract_text now hands pysrt the decoded text (from_string) instead of the path: on a UTF-8
    subtitle — BOM, CRLF, trailing spaces and all — every cue must come out the same as pysrt.open."""
    import pysrt
    before = [(s.index, str(s.start), str(s.end), s.text) for s in pysrt.open(SAMPLE_SRT)]
    after = [(s.index, str(s.start), str(s.end), s.text) for s in pysrt.from_string(read_text(SAMPLE_SRT, "ja"))]
    assert before and after == before


@pytest.mark.parametrize("encoding", ["cp932", "utf-16", "utf-16-be", "utf-32"])
def test_the_real_sample_subtitle_reads_the_same_in_a_legacy_encoding(tmp_path, encoding):
    """A CP932 or UTF-16 copy of the sample contributes exactly what the UTF-8 original does (it
    contributed nothing before: pysrt raised and the file was skipped). UTF-32, which pysrt read by
    its BOM, still reads."""
    original = analyzer.extract_text(_save(tmp_path, "utf8.srt", SAMPLE_CUES, "utf-8"), "ja")
    copy = _save(tmp_path, "legacy.srt", SAMPLE_CUES, encoding)
    assert "お前も俺の邪魔をするのか！" in original and analyzer.extract_text(copy, "ja") == original


@pytest.mark.parametrize("lang, line, encoding", [("ja", "本当にそう思うの。", "cp932"),
                                                  ("ja", "本当にそう思うの。", "utf-16"),
                                                  ("zh", "我们一起学习中文。", "gbk"),
                                                  ("zh", "我們一起學習中文。", "big5")])
def test_an_ass_file_in_a_legacy_encoding_is_read(tmp_path, lang, line, encoding):
    """parse_ass read with errors='ignore': a CP932 / UTF-16 / GBK / Big5 .ass came out empty."""
    content = ("[Script Info]\r\nScriptType: v4.00+\r\n\r\n[Events]\r\n"
               "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\r\n"
               f"Dialogue: 0,0:00:02.00,0:00:03.50,Default,,0,0,0,,{{\\an8}}{line}\r\n")
    assert analyzer.extract_text(_save(tmp_path, "ep01.ass", content, encoding), lang) == line


def test_a_damaged_subtitle_loses_only_its_bad_byte(tmp_path):
    """One stray byte used to cost the whole .srt (pysrt raised on it). Now every cue is read; the
    damaged one carries the mark."""
    text = read_text(SAMPLE_SRT, "ja")
    raw = text.encode("utf-8")
    cut = raw.index("何だ".encode("utf-8"))
    path = _write_bytes(tmp_path, "damaged.srt", raw[:cut] + b"\xff" + raw[cut:])
    got = analyzer.extract_text(path, "ja")
    assert "\ufffd何だ" in got
    assert got.replace("\ufffd", "") == analyzer.extract_text(SAMPLE_SRT, "ja")


# --- the token store: a nested library of mixed encodings ------------------------------------------------ #
def test_the_token_store_reads_a_nested_library_whatever_each_file_is_saved_in(tmp_path):
    """The store's own tokenize_file (make_tokenizer — the indexer's and Generate's path) over a
    library whose files sit in nested folders, each saved differently: every one counts exactly what
    its UTF-8 twin counts."""
    tokenize_file = token_index.make_tokenizer("ja")
    twin = _save(tmp_path, os.path.join("utf8", "novel.txt"), JA, "utf-8")
    expected = tokenize_file(twin)["counts"]
    assert expected[token_index.make_key("冒険", "ボウケン")] >= 10
    for n, encoding in enumerate(("utf-8-sig", "utf-16", "cp932")):
        path = _save(tmp_path, os.path.join("HighPriority", "Series", f"Vol{n}", "novel.txt"), JA, encoding)
        assert tokenize_file(path)["counts"] == expected, encoding


# --- the other readers reach the same helper ----------------------------------------------------------- #
def test_extract_reads_a_file_in_its_own_encoding(tmp_path):
    """The Content Manager's Extract (epub_importer) read text with errors='replace' — a CP932 file
    came out as a page of replacement marks — and subtitles with errors='ignore'."""
    from app.epub_importer import FileImporterApp
    importer = FileImporterApp.__new__(FileImporterApp)      # no window: the reading methods only
    importer.language = "ja"
    text, error = importer.extract_text_from_generic(_save(tmp_path, "novel.txt", JA, "cp932"))
    assert error is None and text == JA
    subs, error = importer.extract_text_from_subtitle(
        _save(tmp_path, "sample.srt", read_text(SAMPLE_SRT, "ja"), "utf-16"))
    assert error is None and "センサー" in subs


def test_the_report_finds_a_cp932_subtitles_anchor_and_cue(tmp_path):
    """The report's source badge reads each file to find an anchor and its cue time: with the file
    read as the analyzer reads it, a CP932 subtitle's sentence gets both."""
    from app.static_html_generator import AnchorFinder
    path = _save(tmp_path, "sample.srt", SAMPLE_CUES, "cp932")
    finder = AnchorFinder(language="ja")
    anchor = finder.anchor(path, "クソあの５人だけでなくお前も俺の邪魔をするのか！")
    assert anchor
    assert finder.cue_time(path, anchor) == 7


def test_settings_saved_with_a_bom_are_the_users_not_the_defaults():
    """settings.json is hand-edited (the reveal gates). Saved with a BOM it loaded the DEFAULTS —
    and the dashboard's next save wrote them over the user's own settings."""
    path = path_utils.get_user_file("settings.json")        # the test sandbox (conftest)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(codecs.BOM_UTF8 + json.dumps({"words_per_day": 17, "target_language": "zh"}).encode("utf-8"))
    settings = settings_manager.load_settings()
    assert settings["words_per_day"] == 17 and settings["target_language"] == "zh"


def test_the_anki_sync_reads_a_known_words_file_saved_with_a_bom_and_refuses_a_damaged_one():
    """The sync appends to KnownWord.json: a BOM'd file is read (it was refused), and a file no
    encoding reads whole is still refused, strictly — nothing is written over a guess."""
    from app import anki_sync
    path = os.path.join(path_utils.get_user_files_path("ja"), "KnownWord.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(codecs.BOM_UTF8 + _known_json(["冒険"]).encode("utf-8"))
    _data, words = anki_sync._read_known_file("ja")
    assert [w["dictForm"] for w in words] == ["冒険"]
    with open(path, "wb") as f:
        f.write(_known_json(["冒険"]).encode("utf-8").replace("冒".encode("utf-8"), b"\xff\xfe\xfd"))
    with pytest.raises(anki_sync._KnownFileError):
        anki_sync._read_known_file("ja")


def test_the_anki_importer_merges_into_a_known_words_file_saved_with_a_bom():
    """The Anki importer refused ("could not be read, so nothing was changed") a BOM'd file; it now
    merges into it, keeping every existing entry."""
    from app.anki_db_importer_gui import AnkiImporterApp
    path = os.path.join(path_utils.get_user_files_path("ja"), "KnownWord.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(codecs.BOM_UTF8 + _known_json(["冒険"]).encode("utf-8"))
    AnkiImporterApp.update_known_words(SimpleNamespace(language="ja"), [("準備", "ジュンビ")])
    with open(path, encoding="utf-8") as f:
        forms = [w["dictForm"] for w in json.load(f)["words"]]
    assert "冒険" in forms and "準備" in forms


def test_the_dashboards_preview_reads_the_lists_and_known_words_in_their_own_encoding():
    """The band preview's own quick reads (no tokenizer) skipped a list or KnownWord.json it could
    not decode — the preview then counted those words as unknown."""
    from app.main import MasterDashboardApp
    folder = path_utils.get_user_files_path("ja")
    _save(folder, "IgnoreList.txt", "# 無視する\n一人\n", "utf-16")
    _save(folder, "Blacklist.txt", "彼\r\n", "cp932")
    _save(folder, "KnownWord.json", _known_json(["冒険"]), "utf-8-sig")
    assert MasterDashboardApp._load_ignore_for_preview(None, "ja") == {"一人", "彼"}
    assert MasterDashboardApp._load_known_approx(None, "ja") == {"冒険"}


# --- adding to a word list: in its own encoding ------------------------------------------------------------------ #
# The Content Manager's graduation appended UTF-8 to GraduatedList.txt whatever it was saved in; a Shift_JIS list then
# read as no encoding, and its own words came out U+FFFD. path_utils.append_text adds in the file's own encoding.
_GRADUATED = "# 卒業した言葉\n勉強\n練習\n"
_ADDED = "\n# Source: 第一話.srt (2 words graduated)\n頑張る\n約束\n"


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "utf-16-be", "cp932"])
def test_words_added_to_a_list_read_back_with_the_list_in_its_own_encoding(tmp_path, encoding):
    path = _save(tmp_path, "GraduatedList.txt", _GRADUATED.replace("\n", "\r\n"), encoding)
    path_utils.append_text(path, _ADDED, "ja")
    assert read_text(path, "ja", errors="strict") == _GRADUATED + _ADDED
    raw = open(path, "rb").read()
    boms = [codecs.BOM_UTF8, codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE]
    assert sum(raw.count(bom) for bom in boms) <= 1, "no second BOM in the middle of the file"
    assert "\n" not in raw.decode(path_utils._decoding(raw, "ja")[1]).replace("\r\n", ""), "the file's CRLF kept"


def test_a_new_list_is_started_in_utf8(tmp_path):
    path = os.path.join(str(tmp_path), "GraduatedList.txt")
    path_utils.append_text(path, _ADDED, "ja")
    assert open(path, "rb").read() == _ADDED.encode("utf-8")


def test_a_word_the_lists_encoding_cant_hold_rewrites_it_in_utf8_after_a_backup(tmp_path):
    # 𠮟 has no Shift_JIS code: the list is kept whole in UTF-8, the original copied to .trash first.
    path = _save(tmp_path, "GraduatedList.txt", _GRADUATED, "cp932")
    before = open(path, "rb").read()
    path_utils.append_text(path, "𠮟る\n", "ja")
    assert open(path, "rb").read() == (_GRADUATED + "𠮟る\n").encode("utf-8")
    trash = os.path.join(str(tmp_path), ".trash")
    backups = os.listdir(trash)
    assert len(backups) == 1 and open(os.path.join(trash, backups[0]), "rb").read() == before
    assert not os.path.exists(path + ".tmp")
