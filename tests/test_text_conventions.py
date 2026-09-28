"""What a text file's own format writes around its text is not the text.

- The transcript downloader's header (title, 'channel | date | duration', captions, URL, a rule of 60 dashes), its
  '[00:01:02] ' timestamps and the captions' sound cues ([音楽]) — the app's own output, skipped exactly. A .txt
  without that header is read as written: a web novel's [ステータス] stays.
- Aozora Bunko's notation (青空文庫 注記): 《ruby》 after kanji, ｜, ［＃…］ notes, the legend at the top and the colophon
  at the end — while 《…》 quoting a message stays.
- A scripture's apparatus: reference lines (1ニフ12・20－23 — ニフ was row #1 of the list), footnote marks ①②, and
  verse numbers glued to their verses (7わが子よ read 7わ as a count, 把).
- Markdown's markup in a .md file.

The transcript and scripture lines are made up in their formats' own shapes; こころ is as 青空文庫 distributes it.
"""
from app import analyzer

TRANSCRIPT_HEADER = ("【原作解説】『夜明けの図書館』をもう一度読む\n"
                     "ことば研究室 | 2023-06-14 | 18:05\n"
                     "Captions: Japanese (native auto)\n"
                     "https://www.youtube.com/watch?v=A1b2C3d4E5f\n\n" + "-" * 60 + "\n")


def _read(tmp_path, text, name="case.txt", language="ja"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _sentences(path, language="ja"):
    tokenizer = analyzer.JapaneseTokenizer() if language == "ja" else analyzer.ChineseTokenizer()
    return list(tokenizer.tokenize_sentences(analyzer.extract_text(str(path), language)))


def _texts(path, language="ja"):
    return [s for s, _t in _sentences(path, language)]


def _lemmas(path, language="ja"):
    return {lemma for _s, tokens in _sentences(path, language) for lemma, _r, _surface, _o in tokens}


# --- the downloader's transcripts ------------------------------------------------------------------- #
def test_the_header_is_the_downloaders_label_not_speech(tmp_path):
    """93 of 原作's 160 uses came from one channel's headers: the title and channel line are no speech."""
    path = _read(tmp_path, TRANSCRIPT_HEADER + "[音楽] 今日は原作の話をしようと思います [拍手]\n")
    assert _texts(path) == ["今日は原作の話をしようと思います"]
    assert "音楽" not in _lemmas(path) and "拍手" not in _lemmas(path)


def test_a_cue_between_a_number_and_its_counter_goes_without_a_gap(tmp_path):
    """18 [笑い] 年後 is 18年後: with the cue gone the number guard sees the number, so 年後 is no word."""
    path = _read(tmp_path, TRANSCRIPT_HEADER + "そうですね。 なるほど。 18[笑い]年後 には何をしていたいですか?\n")
    assert any("18年後" in s for s in _texts(path)), _texts(path)
    assert "年後" not in _lemmas(path) and "笑い" not in _lemmas(path)


def test_kept_timestamps_are_the_downloaders_own_marks(tmp_path):
    """'[00:01:02] ' (or '[01:02] ' for a short video) opens each cue when timestamps are kept."""
    path = _read(tmp_path, TRANSCRIPT_HEADER + "[00:01:02] 今日はいい天気ですね\n[01:05] そうですね\n")
    assert _texts(path) == ["今日はいい天気ですね", "そうですね"]


def test_a_header_with_no_cues_gives_nothing(tmp_path):
    """Empty state: a transcript whose captions were all sound cues."""
    assert _texts(_read(tmp_path, TRANSCRIPT_HEADER + "[音楽]\n")) == []
    assert _texts(_read(tmp_path, TRANSCRIPT_HEADER + "\n", name="empty.txt")) == []


def test_a_windows_transcript_reads_the_same(tmp_path):
    """CRLF line ends (a copy saved by an editor): the header is still found."""
    path = tmp_path / "crlf.txt"
    path.write_bytes((TRANSCRIPT_HEADER + "[音楽] 今日は原作の話です\n").replace("\n", "\r\n").encode("utf-8"))
    assert _texts(path) == ["今日は原作の話です"]


def test_a_chinese_transcript(tmp_path):
    """The header and the sound cues are the downloader's and the captions' in any language."""
    header = TRANSCRIPT_HEADER.replace("Japanese (native auto)", "Chinese (manual)")
    path = _read(tmp_path, header + "[音乐] 欢迎光临时光照相馆。\n", language="zh")
    assert _texts(path, "zh") == ["欢迎光临时光照相馆。"]


def test_brackets_in_a_book_are_its_text(tmp_path):
    """No downloader header, no caption conventions: a web novel's [ステータス] is read as written."""
    path = _read(tmp_path, "【鑑定】と唱えると、[ステータス]が表示された。\n")
    assert _texts(path) == ["【鑑定】と唱えると、[ステータス]が表示された。"]


def test_a_line_that_merely_mentions_captions_is_no_header(tmp_path):
    """The header is the whole shape — a rule of 60 dashes on the sixth line — not one line that looks like it."""
    text = "字幕について\nCaptions: 日本語の字幕をつけました\n今日はいい天気ですね。\n"
    assert _texts(_read(tmp_path, text)) == ["字幕について", "Captions:日本語の字幕をつけました", "今日はいい天気ですね。"]


# --- Aozora Bunko ------------------------------------------------------------------------------------ #
KOKORO = ("こころ\n夏目漱石\n\n-------------------------------------------------------\n"
          "【テキスト中に現れる記号について】\n\n《》：ルビ\n（例）私《わたくし》\n\n"
          "｜：ルビの付く文字列の始まりを特定する記号\n（例）一｜人《ひとり》\n\n"
          "［＃］：入力者注　主に外字の説明や、傍点の位置の指定\n"
          "　　　（数字は、JIS X 0213の面区点番号またはUnicode、底本のページと行数）\n"
          "（例）※［＃「てへん＋劣」、第3水準1-84-77］\n"
          "-------------------------------------------------------\n\n"
          "　私《わたくし》はその人を常に先生と呼んでいた。だからここでもただ先生と書くだけで本名は打ち明けない。\n"
          "私に［＃「私に」は底本では「私は」］固より異議のありようはずがありません。\n"
          "｜夏目漱石《なつめそうせき》の本を読む。\n\n"
          "底本：「こころ」集英社文庫、集英社\n　　　１９９１（平成3）年2月25日第1刷\n入力：j.utiyama\n"
          "校正：伊藤時也\n青空文庫作成ファイル：\n"
          "このファイルは、インターネットの図書館、青空文庫（http://www.aozora.gr.jp/）で作られました。\n")


def test_aozora_notation_is_not_the_novel(tmp_path):
    """Ruby readings, ｜, notes, the legend and the colophon go; the title, the author and the text stay."""
    texts = _texts(_read(tmp_path, KOKORO))
    assert texts == ["こころ", "夏目漱石", "私はその人を常に先生と呼んでいた。", "だからここでもただ先生と書くだけで本名は打ち明けない。",
                     "私に固より異議のありようはずがありません。", "夏目漱石の本を読む。"], texts
    lemmas = _lemmas(_read(tmp_path, KOKORO, name="again.txt"))
    for apparatus in ("ルビ", "外字", "傍点", "底本", "校正", "青空"):
        assert apparatus not in lemmas, apparatus


def test_a_reading_is_kana_so_a_quoted_message_stays(tmp_path):
    """《…》 also quotes text (a signal's words): only kana right after kanji is a reading."""
    text = "信号があった。《直ちに着水せよ》。\n彼は漢字《かんじ》を覚えた。\n"
    assert _texts(_read(tmp_path, text)) == ["信号があった。", "《直ちに着水せよ》。", "彼は漢字を覚えた。"]


def test_the_same_notation_in_a_chinese_file_is_left_alone(tmp_path):
    """Aozora's notation is Japanese; a Chinese book title in 《》 is text (and holds no kana anyway)."""
    path = _read(tmp_path, "我读了《红楼梦》。\n", language="zh")
    assert _texts(path, "zh") == ["我读了《红楼梦》。"]


# --- scripture apparatus ---------------------------------------------------------------------------- #
FOOTNOTES = "2①\n1ニフ9・4－6\n2②\nアル63・9\n3①\nマタ5・9、1ニフ3・7\n"


def test_reference_lines_and_their_marks_give_nothing(tmp_path):
    """A chapter's footnote block — marks and book · chapter・verse references — is apparatus, not language."""
    path = _read(tmp_path, FOOTNOTES)
    assert _texts(path) == []
    assert not {"ニフ", "アル", "マタ"} & _lemmas(path)


def test_footnote_marks_go_and_stop_changing_the_parse(tmp_path):
    """①② tie words to notes: UniDic read them as 一 / 二, and ① made 罪 read ザイ."""
    path = _read(tmp_path, "2 見よ、山の民の①畑が今年は非常に豊かである。また、彼らは祭りのために②歌っている。\n")
    assert not {"一", "二"} & _lemmas(path)
    assert "山の民の畑が今年は非常に豊かである。" in "".join(_texts(path))


def test_verse_numbers_counting_up_go_before_the_text_is_read(tmp_path):
    """Three verses in a row, 6 7 8: the numbers are the book's, and 7わが子よ no longer reads 7わ as 把."""
    path = _read(tmp_path, "6さて、わたしはこの町で起きたことを少し書き記そう。\n"
                           "7わが子よ、この①約束を忘れずに守りなさい。\n"
                           "8見よ、朝の光はすでに山を照らしている。\n")
    assert _texts(path)[1] == "わが子よ、この約束を忘れずに守りなさい。"
    assert "我が" in _lemmas(path) and "把" not in _lemmas(path)


def test_counts_that_happen_to_count_up_stay(tmp_path):
    """1人目 / 2人目 / 3人目: every line of the run goes on with the same counter — a count, not a verse."""
    text = "1人目は太郎だ。\n2人目は花子だ。\n3人目は次郎だ。\n"
    assert _texts(_read(tmp_path, text)) == ["1人目は太郎だ。", "2人目は花子だ。", "3人目は次郎だ。"]


def test_a_number_outside_a_run_is_the_texts(tmp_path):
    """Two verses and a count: too short a run to be read as numbering here — the report still
    shows the verses without their numbers (strip_verse_number) — and 3人で is untouched."""
    text = ("13そこで王は、使者に言われたとおりにした。\n14そして彼らは、川の向こうに住む民を見つけた。\n"
            "3人で主に祈った。\n")
    assert _texts(_read(tmp_path, text))[2] == "3人で主に祈った。"


# --- Markdown ----------------------------------------------------------------------------------------- #
def test_markdown_markup_is_not_text(tmp_path):
    """CommonMark's # heading, ** strong, > quote, - item, `code` and [link](url)."""
    text = ("# 第一章\n\n**本**を読む。\n\n> 彼は*静かに*言った。\n\n- [図書館](https://example.com)へ行く\n"
            "1. `漢字`を覚える\n")
    assert _texts(_read(tmp_path, text, name="notes.md")) == [
        "第一章", "本を読む。", "彼は静かに言った。", "図書館へ行く", "漢字を覚える"]


def test_the_same_marks_in_a_txt_are_its_text(tmp_path):
    """Markdown is the .md file's format; a .txt keeps its asterisks and hashes as written."""
    assert _texts(_read(tmp_path, "**本**を読む。\n")) == ["**本**を読む。"]
