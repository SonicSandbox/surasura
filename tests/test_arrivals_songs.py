"""New arrivals leave a show's songs out as a Generate does (Kotoba-OP2; app/arrivals.py `songs_out`, `read`).

A Generate leaves a show's opening and ending out of its counts while *Count song lyrics (OP / ED)* is off (the default;
app/song_lines.py, analyzer.songs_left_out); an arrival's estimate (its % known, its new words) counted them until the
next Generate. The arrival is read by the same rule, beside its work's other episodes the token store holds.

The shows are the song tests' own (tests/Test Resources/<lang>/songs_*): 星祭り's four episodes (an opening in ♪, an
ending with no mark), 星星节's three (Chinese, no mark), 風の歌's one (an opening in an OPJP .ass style).
"""
import os
import shutil
from unittest.mock import patch

import pytest

from app import analyzer, arrivals
from app import token_index as ti

RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources")
JA_SHOW = os.path.join(RES, "ja", "songs_show")
ZH_SHOW = os.path.join(RES, "zh", "songs_show")
JA_STYLED = os.path.join(RES, "ja", "songs_styled")


@pytest.fixture(autouse=True)
def _a_run():
    analyzer.SANITIZE_JA = True             # as analyzer.main sets it (conftest restores the global)


def _library(tmp_path, language, show, arriving):
    """`show`'s episodes in a work folder of a library, all but `arriving` indexed into a store of their own ->
    (the store, the data folder, every episode's path, the arrival's path)."""
    data_dir = tmp_path / "data" / language
    work = data_dir / "HighPriority" / os.path.basename(show)
    shutil.copytree(show, work)
    paths = sorted(str(work / name) for name in os.listdir(work))
    arrival = str(work / arriving)
    db = str(tmp_path / "store.db")
    ti.reconcile_language(language, [p for p in paths if p != arrival], path=db)
    return ti.open_store(language, db), str(data_dir), paths, arrival


def _view(language, store, data_dir, songs=True):
    """The parts of a view `songs_out` and `read` read, as `View.build` makes them."""
    with patch("app.path_utils.get_data_path", side_effect=lambda l=None: data_dir):
        works = arrivals._spoken_works(store, language, analyzer._source_typer()) if songs else {}
    tokenizer = analyzer.JapaneseTokenizer() if language == "ja" else analyzer.ChineseTokenizer()
    return arrivals.View(language=language, store=store, tokenizer=tokenizer, songs=songs, works=works,
                         names_tables=None)


def _read(view, path, data_dir):
    with patch("app.path_utils.get_data_path", side_effect=lambda l=None: data_dir):
        return arrivals.read(view, path)[0]


def _generates(store, paths, language):
    """{path: sentence numbers} a Generate leaves out of the whole work (every episode in the store)."""
    ti.reconcile_language(language, paths, path=store.path)
    return analyzer.songs_left_out([(p, lines) for p, lines in store.file_lines(paths).items()])


@pytest.mark.parametrize("language, show, arriving", [
    ("ja", JA_SHOW, "Hoshi Matsuri - 04.ja.srt"),
    ("zh", ZH_SHOW, "Xingxing Jie - 03.zh.srt"),
])
def test_an_arriving_episode_loses_the_song_lines_the_next_generate_leaves_out(tmp_path, language, show, arriving):
    """The arrival's song lines are the ones a Generate over the whole work leaves out of it — found beside the
    episodes the store holds (星星节's opening has no mark: only the pairs across episodes find it)."""
    store, data_dir, paths, arrival = _library(tmp_path, language, show, arriving)
    try:
        view = _view(language, store, data_dir)
        read = _read(view, arrival, data_dir)
        emptied = {no for no, (_text, tokens) in enumerate(read) if not tokens}
        fresh = list(view.tokenizer.tokenize_sentences(analyzer.extract_text(arrival, language)))
        already = {no for no, (_text, tokens) in enumerate(fresh) if not tokens}
        found = _generates(store, paths, language)[arrival]
        assert found and emptied - already == found
        assert len(read) == len(fresh), "every sentence keeps its place"
        assert [t for no, (_s, t) in enumerate(read) if no not in found] == \
               [t for no, (_s, t) in enumerate(fresh) if no not in found], "the dialogue's words stay"
    finally:
        store.close()


def test_with_count_song_lyrics_on_the_arrival_keeps_its_songs(tmp_path):
    store, data_dir, _paths, arrival = _library(tmp_path, "ja", JA_SHOW, "Hoshi Matsuri - 04.ja.srt")
    try:
        with patch.dict(analyzer.LOGIC, {"count_song_lyrics": True}):
            view = _view("ja", store, data_dir, songs=not analyzer.LOGIC["count_song_lyrics"])
        read = _read(view, arrival, data_dir)
        fresh = list(view.tokenizer.tokenize_sentences(analyzer.extract_text(arrival, "ja")))
        assert [t for _s, t in read] == [t for _s, t in fresh]
    finally:
        store.close()


def test_a_styled_opening_leaves_an_arrival_with_no_episodes_beside_it(tmp_path):
    # 風の歌's one episode, nothing in the store: its OPJP lines are songs by their style alone; 風の歌が聞こえる？,
    # said, stays
    data_dir = str(tmp_path / "data" / "ja")
    view = arrivals.View(language="ja", store=None, tokenizer=analyzer.JapaneseTokenizer(), songs=True, works={},
                         names_tables=None)
    read = _read(view, os.path.join(JA_STYLED, "Kaze no Uta - 01.ja.ass"), data_dir)
    assert [(text, bool(tokens)) for text, tokens in read] == [
        ("おはよう、今日は晴れだね。", True), ("風の歌が聞こえる。", False), ("青い海を越えて。", False),
        ("まだ知らない明日へ。", False), ("海に行きたいな。", True), ("明日、一緒に行こう。", True),
        ("風の歌が聞こえる？", True)]


def test_a_book_or_a_rule_that_fails_never_loses_a_word(tmp_path):
    view = arrivals.View(language="ja", store=None, tokenizer=None, songs=True, works={}, names_tables=None)
    sentences = [("♪ 夜明けの風が背中を押す", [("夜明け", "ヨアケ", "夜明け", "夜明け")])]
    book = str(tmp_path / "第一章.txt")
    assert arrivals.songs_out(view, book, sentences) is sentences          # a book: never a song rule
    with patch("app.analyzer.songs_left_out", side_effect=RuntimeError("damaged")):
        assert arrivals.songs_out(view, str(tmp_path / "ep01.ja.srt"), sentences) is sentences


def test_a_works_episodes_are_read_from_the_store_once_for_all_its_arrivals(tmp_path):
    """The warm worker's view holds no store (it closes it after the build): the work's lines are read once, opened
    to read only, and kept for the next arrival of the same show (a drag brings several)."""
    store, data_dir, _paths, arrival = _library(tmp_path, "ja", JA_SHOW, "Hoshi Matsuri - 04.ja.srt")
    view = _view("ja", store, data_dir)
    store.close()
    view.store = None
    opened = []

    def reader(language, path=None):
        opened.append(language)
        return ti.open_store(language, str(tmp_path / "store.db"))
    with patch("app.token_index.open_reader", side_effect=reader):
        first = _read(view, arrival, data_dir)
        again = _read(view, arrival, data_dir)
    assert opened == ["ja"] and first == again
    assert sum(1 for _s, tokens in first if not tokens) > 3, "the songs found beside the stored episodes"


def test_an_arrival_outside_the_data_folder_is_read_alone(tmp_path):
    # A file beside the library, in a folder named like one of its works: never grouped with that work by its name
    store, data_dir, paths, _arrival = _library(tmp_path, "ja", JA_SHOW, "Hoshi Matsuri - 04.ja.srt")
    try:
        view = _view("ja", store, data_dir)
        outside = tmp_path / "data" / os.path.basename(JA_SHOW)        # the work's own folder name
        outside.mkdir()
        copy = shutil.copy(paths[-1], outside / "Hoshi Matsuri - 04.ja.srt")
        read = _read(view, str(copy), data_dir)
        fresh = list(view.tokenizer.tokenize_sentences(analyzer.extract_text(str(copy), "ja")))
        # alone, only its ♪ lines that are songs of its own file could go: 星祭り's opening is found by the pairs
        assert [t for _s, t in read] == [t for _s, t in fresh]
    finally:
        store.close()


def test_a_works_folder_is_one_work_and_a_loose_file_its_own(tmp_path):
    data_dir = tmp_path / "data" / "ja"
    show, tier = data_dir / "HighPriority" / "Hoshi Matsuri", data_dir / "LowPriority"
    shutil.copytree(JA_SHOW, show)
    tier.mkdir(parents=True)
    loose = [shutil.copy(show / name, tier / f"loose {n}.ja.srt") for n, name in enumerate(sorted(os.listdir(show))[:2])]
    (show / "あらすじ.txt").write_text("星祭りの夜、町の人々が集まる。\n", encoding="utf-8")     # a book: never an episode
    db = str(tmp_path / "store.db")
    ti.reconcile_language("ja", [str(show / n) for n in os.listdir(show)] + [str(p) for p in loose], path=db)
    store = ti.open_store("ja", db)
    try:
        with patch("app.path_utils.get_data_path", side_effect=lambda l=None: str(data_dir)):
            works = arrivals._spoken_works(store, "ja", analyzer._source_typer())
    finally:
        store.close()
    assert sorted(len(v) for v in works.values()) == [1, 1, 4]
    assert os.path.normcase("Hoshi Matsuri") in works


@pytest.mark.parametrize("count_songs", [False, True])
def test_the_view_reads_count_song_lyrics_and_groups_the_stores_spoken_files(tmp_path, count_songs):
    """`View.build` (the worker's): off, the songs rule on and every stored episode of the show in its work; on, no
    rule and no works held."""
    from app import plan_engine
    store, data_dir, paths, arrival = _library(tmp_path, "ja", JA_SHOW, "Hoshi Matsuri - 04.ja.srt")
    bare = plan_engine.Plan({"floor": 0, "run_signature": None, "phrase_entries": []}, [], [], [], [], [])
    try:
        with patch.dict(analyzer.LOGIC, {"count_song_lyrics": count_songs}), \
             patch("app.path_utils.get_data_path", side_effect=lambda l=None: data_dir):
            view = arrivals.View.build("ja", bare, store, analyzer.parse_analysis_args(["--language=ja"]))
    finally:
        store.close()
    assert view.songs is not count_songs
    assert view.works == ({} if count_songs else {os.path.normcase("songs_show"): [
        ti._norm(p) for p in paths if p != arrival]})


def test_a_book_in_a_shows_folder_keeps_every_word(tmp_path):
    # A text file is never a spoken file: the rule never reads it, even beside the show's episodes
    store, data_dir, paths, arrival = _library(tmp_path, "ja", JA_SHOW, "Hoshi Matsuri - 04.ja.srt")
    try:
        view = _view("ja", store, data_dir)
        lines = [line for line in open(arrival, encoding="utf-8").read().splitlines()
                 if line.strip() and not line.strip().isdigit() and "-->" not in line]
        book = os.path.join(os.path.dirname(arrival), "Hoshi Matsuri - 04.txt")
        with open(book, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        read = _read(view, book, data_dir)
        fresh = list(view.tokenizer.tokenize_sentences(analyzer.extract_text(book, "ja")))
        assert [t for _s, t in read] == [t for _s, t in fresh]
    finally:
        store.close()


def test_an_episode_the_store_already_holds_is_read_as_it_is_now(tmp_path):
    """Placed again after an edit (two lines said added at its end): its stored copy is never one of its own
    neighbours — the rule reads the file as it is now beside the other episodes, as the next Generate will."""
    store, data_dir, paths, arrival = _library(tmp_path, "ja", JA_SHOW, "Hoshi Matsuri - 04.ja.srt")
    store.close()
    ti.reconcile_language("ja", paths, path=str(tmp_path / "store.db"))          # ep04 in the store as it was
    with open(arrival, "a", encoding="utf-8") as f:
        f.write("\n99\n00:23:50,000 --> 00:23:52,000\nまた来週、駅で会おう。\n\n"
                "100\n00:23:53,000 --> 00:23:55,000\n寝坊するなよ。\n")
    store = ti.open_store("ja", str(tmp_path / "store.db"))
    try:
        view = _view("ja", store, data_dir)
        read = _read(view, arrival, data_dir)
        fresh = list(view.tokenizer.tokenize_sentences(analyzer.extract_text(arrival, "ja")))
        others = [p for p in paths if p != arrival]
        from app import song_lines
        expected = analyzer.songs_left_out([(p, lines) for p, lines in store.file_lines(others).items()]
                                           + [(arrival, song_lines.file_lines(fresh))])[arrival]
        emptied = {no for no, (_s, t) in enumerate(read) if not t} - {no for no, (_s, t) in enumerate(fresh) if not t}
        assert expected and emptied == expected
        assert read[-1][1] and read[-2][1], "the lines said at its end stay"
    finally:
        store.close()
