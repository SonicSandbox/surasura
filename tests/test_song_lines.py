"""Songs out of the counts (Settings -> Language & Parsing, *Count song lyrics (OP / ED)*; logic.count_song_lyrics, off
by default; app/song_lines.py, analyzer.songs_left_out).

A show's opening and ending songs come back in its subtitles every episode; counted each time they lift a song's words
over the words the show really uses. Off (the default), a run leaves out of its counts — per work — a subtitle line in
an .ass song style, a run of four lines or more whose ordered pairs recur in a quarter of the work's episodes (at least
3, at most 6), and a ♪ line that is one of them; only the song's copy goes, the same words said keep their counts.

The shows are made up for these tests (tests/Test Resources/<lang>/songs_*): 星祭り's four episodes (an opening in ♪,
an ending with no mark, a flashback in two episodes, interjections in every episode, the ending sung once inside the
third, a song made up once in the fourth, a next-episode preview each), 風の歌's one episode (its opening in an .ass
style named OPJP), and 星星节's three Chinese episodes (an opening and an ending with no mark).
"""
import json
import os
import shutil
from unittest.mock import patch

import pandas as pd
import pytest

from app import analyzer, song_lines
from app import token_index as ti

RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources")
JA_SHOW = os.path.join(RES, "ja", "songs_show")
JA_STYLED = os.path.join(RES, "ja", "songs_styled")
ZH_SHOW = os.path.join(RES, "zh", "songs_show")

OPENING_JA = ("夜明けの風が背中を押す", "まだ見ぬ道へ走り出そう", "涙の跡も光に変えて", "君と描いた地図を広げる",
              "遠い空の向こうへ", "約束の場所で待っている")
ENDING_JA = ("帰り道に咲いた小さな花", "名前も知らずに笑っていた", "明日がまた来ることを", "信じて灯りを消した",
             "おやすみ また会う日まで")
FLASHBACK = ("あの日のこと覚えてる", "川で溺れかけた時", "お前が手をつかんでくれた", "忘れるわけないだろ")


def _plain(text):
    return song_lines.plain(text)


def _read(folder, language, names=None):
    """{name: (sentences, lines)} of a folder's files, each read as the token store reads it."""
    tokenize = ti.make_tokenizer(language)
    out = {}
    for name in sorted(names or os.listdir(folder)):
        result = tokenize(os.path.join(folder, name))
        out[name] = (result["sentences"], result["lines"])
    return out


def _left_out(read, folder):
    """{name: [the plain text of each sentence left out]} — the run's rule over every file of `read`."""
    out = analyzer.songs_left_out([(os.path.join(folder, name), lines) for name, (_s, lines) in read.items()])
    return {name: [_plain(read[name][0][no][0]) for no in sorted(out[os.path.join(folder, name)])] for name in read}


def _kept(read, left, name):
    return [_plain(s) for s, _t in read[name][0] if _plain(s) not in left[name]]


# --- the pieces ------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("style", ["OPJP", "EDCN", "ED-JP", "OP3-JP", "ED2-JP", "OP - JP", "EDCN-CHS", "jp-op", "jp-ed",
                                   "edj", "opj", "Opening", "Ending", "Opening furigana", "IN-JP", "Insert", "Song",
                                   "Lyrics", "Karaoke", "ylmusic", "主题曲", "片头", "片尾", "插曲", "歌詞", "ＯＰ"])
def test_a_style_named_for_a_song_is_a_song_style(style):
    """The names the library's subtitlers gave their song styles (measured over 92 styles in 746 files): OP / ED with
    a language or a number joined on, the words opening / ending / song, and the Chinese and Japanese ones."""
    assert song_lines.song_style(style)


@pytest.mark.parametrize("style", ["Default", "*Default", "Dial-JP", "Text - JP", "Text - JP - top", "Default-JP_UP",
                                   "JP", "CN", "STAFF", "Title", "Sign", "Caption", "Main", "Speed", "Credit",
                                   "Comment", "FURIGANA", "jp-up", "警示标语", "", None])
def test_a_dialogue_sign_or_credit_style_is_no_song_style(style):
    """Every other style in the library — dialogue, signs, credits, furigana — and a line with no style (.srt)."""
    assert not song_lines.song_style(style)


def test_a_line_is_the_same_however_it_is_marked_spaced_or_punctuated():
    """♪, spaces and punctuation are the file's way of writing a line, not the line: one key. A line with no Japanese
    or Chinese script (♪～ alone, an English line) is no line at all."""
    key = song_lines.line_key("♪ 夜明けの風が背中を押す")
    assert key and key == song_lines.line_key("夜明けの風が、背中を押す。") == song_lines.line_key("夜明けの風が 背中を押す♪")
    assert key != song_lines.line_key("夜明けの風が背中を押した")
    assert song_lines.line_key("清晨的风吹过我的脸") != 0
    for nothing in ("♪～", "～♪", "", "   ", "Fighting Dream", None):
        assert song_lines.line_key(nothing) == 0


@pytest.mark.parametrize("episodes, need", [(1, 3), (3, 3), (12, 3), (13, 4), (16, 4), (17, 5), (24, 6), (57, 6)])
def test_a_pair_must_recur_in_a_quarter_of_the_episodes_at_least_three_and_at_most_six(episodes, need):
    """A quarter of a short season, never fewer than 3 (two episodes are a recap); never more than 6, so a long show's
    second opening (sung in a few dozen of its 135 episodes) still is one."""
    assert song_lines.need(episodes) == need


def test_the_store_keeps_one_line_for_each_sentence_with_its_marks():
    """`lines` is beside the sentences, one for one: ♪ lines marked NOTE, the opening's in the order they were sung."""
    read = _read(JA_SHOW, "ja", ["Hoshi Matsuri - 01.ja.srt"])
    sentences, lines = read["Hoshi Matsuri - 01.ja.srt"]
    assert len(lines) == len(sentences)
    marks = {_plain(s): m for (s, _t), (_k, m) in zip(sentences, lines)}
    assert all(marks[_plain(line)] & song_lines.NOTE for line in OPENING_JA)
    assert not any(marks[_plain(line)] & song_lines.NOTE for line in ENDING_JA)


def test_an_ass_event_in_a_song_style_is_marked_styled():
    """風の歌's opening lines (style OPJP) are STYLED; its dialogue (Default) is not."""
    read = _read(JA_STYLED, "ja")
    sentences, lines = read["Kaze no Uta - 01.ja.ass"]
    styled = [_plain(s) for (s, _t), (_k, m) in zip(sentences, lines) if m & song_lines.STYLED]
    assert styled == ["風の歌が聞こえる", "青い海を越えて", "まだ知らない明日へ"], "the dialogue's 風の歌が聞こえる？ is not"


def test_nothing_in_nothing_out():
    """Empty states: no files, a file with no lines (None or []), an empty file's lines."""
    assert analyzer.songs_left_out([]) == {}
    assert song_lines.file_lines([]) == []
    out = analyzer.songs_left_out([("a - 01.srt", None), ("a - 02.srt", []), ("a - 03.srt", None)])
    assert out == {"a - 01.srt": set(), "a - 02.srt": set(), "a - 03.srt": set()}


# --- a show, as a run reads it ---------------------------------------------------------------------------------------- #
def test_the_opening_and_the_ending_are_left_out_of_every_episode():
    """The ♪ opening and the unmarked ending — the same run of lines in all four episodes — leave every episode."""
    read = _read(JA_SHOW, "ja")
    left = _left_out(read, JA_SHOW)
    for name in read:
        assert {_plain(x) for x in OPENING_JA} <= set(left[name]), name
        assert {_plain(x) for x in ENDING_JA} <= set(left[name]), name


def test_dialogue_a_flashback_interjections_and_a_song_sung_once_stay():
    """Only songs go: the dialogue (地図 said in the third episode, though the opening sings it too), a flashback seen in
    two episodes (under the bar of three), えっ？ / はい / うん repeated in every episode (alone, never a run), the next
    episode's preview, and a song made up once in the story (♪ ラララ…)."""
    read = _read(JA_SHOW, "ja")
    left = _left_out(read, JA_SHOW)
    third, second, fourth = "Hoshi Matsuri - 03.ja.srt", "Hoshi Matsuri - 02.ja.srt", "Hoshi Matsuri - 04.ja.srt"
    assert "この地図どこで手に入れたの" in _kept(read, left, third)
    assert set(FLASHBACK) <= set(_kept(read, left, second)) and set(FLASHBACK) <= set(_kept(read, left, third))
    assert {"えっ", "はい"} <= set(_kept(read, left, third)) and "うん" in _kept(read, left, second)
    assert "次回森の入り口" in _kept(read, left, third)
    assert "ラララお団子ひとつ" in _kept(read, left, fourth)
    # the fourth episode's 遠い空の向こうへ said (no ♪) stays; only the opening's copy goes
    assert [_plain(t) for t, _k in read[fourth][0]].count("遠い空の向こうへ") == 2
    assert left[fourth].count("遠い空の向こうへ") == 1


def test_the_ending_sung_inside_an_episode_is_the_song_too():
    """The third episode's 「♪ 帰り道に咲いた小さな花」, sung inside the story, is the ending's line: it goes — the line
    said next to it stays."""
    read = _read(JA_SHOW, "ja")
    left = _left_out(read, JA_SHOW)
    third = "Hoshi Matsuri - 03.ja.srt"
    assert left[third].count("帰り道に咲いた小さな花") == 2        # the copy in the story and the ending's own
    assert "その歌好きなの" in _kept(read, left, third)


def test_a_song_styled_line_leaves_a_show_of_one_episode():
    """With one episode there are no repeats to read; the style alone says song."""
    read = _read(JA_STYLED, "ja")
    left = _left_out(read, JA_STYLED)["Kaze no Uta - 01.ja.ass"]
    assert left == ["風の歌が聞こえる", "青い海を越えて", "まだ知らない明日へ"]


def test_a_line_said_that_is_also_a_lyric_of_the_same_file_stays():
    """風の歌's dialogue asks 風の歌が聞こえる？ — the opening's first line, word for word: the style is matched by place,
    so only the opening's copy goes."""
    read = _read(JA_STYLED, "ja")
    sentences = [_plain(s) for s, _t in read["Kaze no Uta - 01.ja.ass"][0]]
    assert sentences.count("風の歌が聞こえる") == 2
    assert _left_out(read, JA_STYLED)["Kaze no Uta - 01.ja.ass"].count("風の歌が聞こえる") == 1


def test_a_line_with_no_script_is_a_gap_and_two_never_join_a_run():
    """♪～ (no Japanese or Chinese) never pairs: two pairs that recur in every episode, two ♪～ apart, are two short
    runs — never one run of four that would take the said lines with it."""
    def lines(*texts):
        return [[song_lines.line_key(t), song_lines.NOTE if "♪" in t else 0] for t in texts]
    episode = lines("おはよう", "はい", "♪～", "♪～", "ありがとう", "ございます")
    out = song_lines.left_out([(f"e{n}", n, episode) for n in range(6)])
    assert not any(out.values())


def test_with_fewer_than_three_episodes_a_repeated_run_stays():
    """Two episodes are a recap's shape as much as a song's: under three, only song styles leave."""
    read = _read(JA_SHOW, "ja", ["Hoshi Matsuri - 01.ja.srt", "Hoshi Matsuri - 02.ja.srt"])
    assert not any(_left_out(read, JA_SHOW).values())


def test_two_copies_of_one_episode_are_one_episode(tmp_path):
    """The library holds an .srt and an .ass of one episode at times: one episode, so with the second episode the show
    has two — and its opening stays (two episodes, under the bar); a third episode makes it a song."""
    read = _read(JA_SHOW, "ja")
    first = read["Hoshi Matsuri - 01.ja.srt"][1]
    two = [(str(tmp_path / "Hoshi Matsuri - 01.ja.srt"), first), (str(tmp_path / "Hoshi Matsuri - 01.ja.ass"), first),
           (str(tmp_path / "Hoshi Matsuri - 02.ja.srt"), read["Hoshi Matsuri - 02.ja.srt"][1])]
    assert not any(analyzer.songs_left_out(two).values())
    three = two + [(str(tmp_path / "Hoshi Matsuri - 03.ja.srt"), read["Hoshi Matsuri - 03.ja.srt"][1])]
    assert all(analyzer.songs_left_out(three).values())


def test_a_chinese_shows_opening_and_ending_with_no_mark_leave_its_dialogue_stays():
    """星星节's three episodes: the opening and the ending recur as runs in all three; 什么？ / 对 repeat alone; the
    dialogue, holding the opening's 地图, stays."""
    read = _read(ZH_SHOW, "zh")
    left = _left_out(read, ZH_SHOW)
    for name in read:
        assert {"清晨的风吹过我的脸", "打开你画的地图", "回家的路上开着小花", "晚安我们再见"} <= set(left[name]), name
    third = "Xingxing Jie - 03.zh.srt"
    assert {"这张地图是从哪里来的", "什么", "对"} <= set(_kept(read, left, third))


# --- a whole run ------------------------------------------------------------------------------------------------------ #
def _generate(tmp_path, language, show):
    """One real run (Generate) over a library holding `show` (a work's folder in HighPriority), every word listed ->
    the priority list's rows."""
    uf = tmp_path / "User Files" / language
    uf.mkdir(parents=True)
    (uf / ("KnownWord.json" if language == "ja" else "KnownWords.json")).write_text(json.dumps({"words": []}),
                                                                                       encoding="utf-8")
    work = tmp_path / "data" / language / "HighPriority" / os.path.basename(show)
    shutil.copytree(show, work)
    results = tmp_path / "results"
    results.mkdir()
    with patch("app.analyzer.get_user_file", side_effect=lambda p: str(tmp_path / p)), \
         patch("app.analyzer.get_data_path",
               side_effect=lambda l=None: str(tmp_path / "data" / l) if l else str(tmp_path / "data")), \
         patch("app.analyzer.get_user_files_path",
               side_effect=lambda l=None: str(tmp_path / "User Files" / l) if l else str(tmp_path / "User Files")), \
         patch("app.analyzer.RESULTS_DIR", str(results)), \
         patch("app.analyzer.OUTPUT_CSV", str(results / "priority_learning_list.csv")), \
         patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
         patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
         patch("sys.argv", ["analyzer.py", "--language", language, "--min-freq", "1"]):
        analyzer.main()
    return pd.read_csv(results / "priority_learning_list.csv", encoding="utf-8-sig", keep_default_na=False)


def _contexts(rows):
    return " ".join(str(v) for c in rows.columns if c.startswith("Context") for v in rows[c])


@pytest.mark.parametrize("language, show, sung, said", [
    ("ja", JA_SHOW, {"背中", "約束", "涙"}, {"本屋", "地図", "噂"}),
    ("zh", ZH_SHOW, {"清晨", "眼泪", "约定"}, {"书店", "地图", "抽屉"}),
])
def test_a_run_leaves_the_songs_words_out_and_on_counts_them_again(tmp_path, language, show, sung, said):
    """Off (the default — settings.json without the key), the words only the songs sing are off the list and no
    example sentence is a song's line; the words said stay — 地图 / 地図 counted once, as said, though the opening sings
    it every episode. On, the run counts the songs again."""
    off = _generate(tmp_path / "off", language, show)
    words = set(off["Word"])
    assert not sung & words, "the songs' own words are out"
    assert said <= words
    row = off[off["Word"] == ("地図" if language == "ja" else "地图")]
    assert int(row["Occurrences"].iloc[0]) == 1, "only its use in dialogue counts"
    text = _contexts(off)
    assert "背中を押す" not in text and "吹过我的脸" not in text, "no song line is an example sentence"
    with patch.dict(analyzer.LOGIC, {"count_song_lyrics": True}):    # as a run started after the switch reads it
        on = _generate(tmp_path / "on", language, show)
    assert sung <= set(on["Word"]), "on, the songs count again"


def test_the_store_reads_back_each_files_lines_one_for_one_with_its_sentences(tmp_path):
    """What the token store keeps is what the reader made, beside the sentences a run reads (`Store.file_lines`, one
    query): a run's song numbers point at the right sentences. A path the store doesn't hold is left out."""
    folder = tmp_path / "Hoshi Matsuri"
    shutil.copytree(JA_SHOW, folder)
    paths = sorted(str(folder / name) for name in os.listdir(folder))
    db = str(tmp_path / "store.db")
    ti.reconcile_language("ja", paths, path=db)
    store = ti.open_store("ja", db)
    try:
        held = store.file_lines(paths + [str(tmp_path / "gone.srt")])
        assert set(held) == set(paths)
        read = _read(str(folder), "ja")
        for path in paths:
            assert held[path] == read[os.path.basename(path)][1]
            assert len(held[path]) == len(store.file_tokens(path))
    finally:
        store.close()


def test_a_rule_that_fails_never_stops_a_generate(tmp_path):
    """The run says so and counts the songs, as before the rule — never a Generate lost."""
    with patch("app.song_lines.left_out", side_effect=RuntimeError("boom")):
        rows = _generate(tmp_path, "ja", JA_SHOW)
    assert {"背中", "約束"} <= set(rows["Word"])


def test_a_marked_run_needs_only_three_episodes_in_a_long_show():
    """A 24-episode show (bar 6): a second ending sung with ♪ in only four episodes is a song (a run half marked needs
    3); the same four lines unmarked in four episodes — a flashback — stay under the bar."""
    def lines(texts, note):
        return [[song_lines.line_key(t), song_lines.NOTE if note else 0] for t in texts]
    said = ["今日はどこへ行くの", "駅まで歩こう", "雨が降りそうだね", "傘を持ってきた"]
    ending = ["星の降る夜に", "君の名前を呼んだ", "遠く離れても", "この歌を忘れない"]
    files = []
    for n in range(24):
        body = lines([f"第{n}話の台詞です"], False)
        if n < 4:
            body += lines(ending, True) + lines([f"第{n}話の次の台詞", f"第{n}話のまた別の台詞"], False)
            body += lines(said, False)
        files.append((f"e{n}", n, body))
    assert song_lines.need(24) == 6
    out = song_lines.left_out(files)
    assert out["e0"] == {1, 2, 3, 4}, "the ♪ ending's four lines"
    assert not out["e10"]
