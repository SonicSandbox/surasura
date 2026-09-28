"""A subtitle's own conventions for what is not speech.

- SDH sound cues in square brackets — [無線] 'over the radio', ［拍手］ 'applause', [音乐] — go, as the parenthesised
  sounds and labels always have (decided 2026-09-27: every parenthesised group keeps going).
- A speaker's Name： label opening a Japanese line goes — 《田中:もう春か…｡, ⸨アサ：… — but a clause before a colon
  is speech (a name holds no hiragana), and Chinese keeps its 他说：… (no such tell).
- Sung lines the FILE marks as song — karaoke timing (\\k, \\K, \\kf, \\ko) — are skipped; a ♪ line is dialogue and
  stays (decided 2026-09-27).
- .ssa, the .ass format's predecessor, is read by the scan like .ass.

The Japanese lines are made up in the shapes subtitles write them (a cue or a label before the line, a voice-over
bracket, a ♪ at the end); the Chinese ones are ordinary Mandarin.
"""
from app import analyzer, path_utils


def _clean(text, language="ja"):
    return analyzer.clean_subtitle_text(text, language)


def _sentences(path, language="ja"):
    tokenizer = analyzer.JapaneseTokenizer() if language == "ja" else analyzer.ChineseTokenizer()
    return [s for s, _t in tokenizer.tokenize_sentences(analyzer.extract_text(str(path), language))]


# --- SDH sound cues --------------------------------------------------------------------------------- #
def test_square_bracket_sound_cues_go_in_either_width():
    """[無線] (25 cues in one series) and ［拍手］ are notes on what is heard, not what is said."""
    assert _clean("[無線](佐藤)こっちは準備できてるっすよ｡") == "こっちは準備できてるっすよ｡"
    assert _clean("［拍手］") == ""
    assert _clean("[笑い]そうですね") == "そうですね"
    assert _clean("[音乐]我们走吧", "zh") == "我们走吧"


def test_parentheses_keep_going_as_decided():
    """Decided 2026-09-27: every group goes, a thought line with them, until a library shows one."""
    assert _clean("そうだね（心の声）") == "そうだね"
    assert _clean("（どうしよう…）") == ""


# --- speaker labels ---------------------------------------------------------------------------------- #
def test_a_name_and_a_colon_opening_a_line_is_a_label():
    """《田中: and ⸨アサ： name the speaker of a voice-over; the bracket is the line's own and stays."""
    assert _clean("《田中:もう春か…｡") == "《もう春か…｡"
    assert _clean("⸨アサ：山の向こうで育ったのは➨") == "⸨山の向こうで育ったのは➨"
    assert _clean("《ﾀﾅｶ:いずれ分かる｡") == "《いずれ分かる｡", "half-width katakana names too"
    assert _clean("アサ：") == "", "a label alone leaves nothing"


def test_a_clause_before_a_colon_is_speech():
    """Particles and endings are hiragana, names are not: 理由は簡単 is a clause, so the line is kept whole."""
    assert _clean("理由は簡単：お前が弱いからだ") == "理由は簡単：お前が弱いからだ"
    assert _clean("10:30に会おう") == "10:30に会おう", "a time is no label"
    assert _clean("https://example.comで検索して") == "https://example.comで検索して", "nor is a URL scheme"


def test_chinese_keeps_its_colon():
    """他说：我们走吧 is speech; Chinese has no hiragana to tell a clause from a name, so no label rule."""
    assert _clean("他说：我们走吧", "zh") == "他说：我们走吧"


# --- songs: only what the file marks ------------------------------------------------------------------ #
def test_a_karaoke_event_is_sung_and_skipped():
    r"""\k (and \K, \kf, \ko) time each sung syllable: the file itself marks the line as song."""
    assert analyzer.ass_dialogue_text("{\\k40}夢{\\k30}の{\\k45}中{\\k30}で{\\k60}君を探した") == ""
    assert analyzer.ass_dialogue_text("{\\kf45}夢の中で") == ""
    assert analyzer.ass_dialogue_text("{\\an8\\ko20}夢の中で") == ""
    assert analyzer.ass_dialogue_text("{\\fnKozuka Gothic}夢の中で") == "夢の中で", "a font name is no \\k"


def test_a_note_marked_line_is_dialogue():
    """♪ marks sung dialogue (今日はお団子を作るんだヨー♪) — still what the character says."""
    assert _clean("今日はお団子を作るんだヨー♪") == "今日はお団子を作るんだヨー♪"


def test_an_op_file_end_to_end(tmp_path):
    """The OP's karaoke event goes; the episode's dialogue in the same file stays."""
    path = tmp_path / "ep13.ja.ass"
    path.write_text(
        "[Script Info]\nScriptType: v4.00+\n\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:01:30.00,0:01:34.00,OP,,0,0,0,,{\\k40}夢{\\k30}の{\\k45}中{\\k30}で{\\k60}君を探した\n"
        "Dialogue: 0,0:01:34.00,0:01:36.00,Default,,0,0,0,,本当にそう思うの。\n", encoding="utf-8")
    assert _sentences(path) == ["本当にそう思うの。"]


# --- .ssa --------------------------------------------------------------------------------------------- #
def test_ssa_is_content_and_a_subtitle():
    """The scan, the indexer and the Content Manager share is_content_file; the badge types it a subtitle."""
    assert path_utils.is_content_file("第01話.ssa")
    assert path_utils.is_content_file("第01話.SSA")
    assert path_utils.infer_source_type("data/ja/HighPriority/第01話.ssa") == "subtitle"
    assert not path_utils.is_content_file("第01話.vtt"), "only what the analyzer can read"


def test_an_ssa_file_reads_like_ass(tmp_path):
    """SSA v4's [Events] start each line with a Marked field; the Format line says where Text is."""
    path = tmp_path / "old.ssa"
    path.write_text(
        "[Script Info]\nScriptType: v4.00\n\n[Events]\n"
        "Format: Marked, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: Marked=0,0:00:02.00,0:00:04.50,Default,,0000,0000,0000,,（三玖）本当にそう思うの。\n",
        encoding="utf-8")
    assert _sentences(path) == ["本当にそう思うの。"]


# --- empty states ------------------------------------------------------------------------------------ #
def test_a_subtitle_of_nothing_but_cues_and_labels_gives_no_sentence(tmp_path):
    path = tmp_path / "sounds.srt"
    path.write_text("1\n00:00:01,000 --> 00:00:02,000\n［拍手］\n\n"
                    "2\n00:00:02,000 --> 00:00:03,000\n[音楽]\n\n"
                    "3\n00:00:03,000 --> 00:00:04,000\nアサ：\n", encoding="utf-8")
    assert _sentences(path) == []
