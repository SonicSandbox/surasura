"""The sentence dial reads the list (Kantan-SD, 3.0.18): Best's candidates for a word that is a row of the list are
the pool the last Generate kept for it in the plan file (`plan_engine.candidates`), put in Best's order when a card is
mined (`app/connect/sentences.py` `_from_list`) — never a search of the library. What each test holds:

  * a row's candidates come from the plan, in Best's order, with the list's own count of other unknown words, the
    sentence's place in its file, and no look at the library's files;
  * a file changed or removed since that Generate gives no candidate; nor does a sentence the token store no longer
    holds at its place (the file read again in between);
  * the young words reorder a row's leading candidates; the mined episode's own line is always handed back;
  * `never` gives the next candidate (Swap); a book's line nothing can speak is no choice where media is cut;
  * no plan, a damaged one, another language's: the library search, as before; a word with no row beside rows too;
  * the reader stops before the plan's per-file tables (most of a large library's plan);
  * a word met in hundreds of files costs its candidates only.

Real Japanese and Chinese lines (natural sentences written for these tests, no show's lines); a plan file written as
`analyzer.plan_lines` writes it (its tables' own shapes), over real files in the sandbox.
"""
import gzip
import json
import os
import zlib

import pytest

from app import analyzer, plan_engine, plan_rules
from app import sentence_corpus as sc
from app.connect import sentences
from app.path_utils import get_data_path, get_user_file

EASY = "明日から冒険に出かけよう。"          # every word known but 冒険
TODAY = "今日から冒険に出かけよう。"         # the same, 今日 for 明日
HARD = "未知の迷宮で壮絶な冒険が始まった。"    # 未知 迷宮 壮絶 unknown too
BOUKEN = ("冒険", "ボウケン")


@pytest.fixture(autouse=True)
def _a_fresh_read():
    analyzer.SANITIZE_JA = True
    sentences._KEPT.clear()
    yield
    sentences._KEPT.clear()


@pytest.fixture
def placed(monkeypatch):
    """The library store's answer for a file, handed in by the test: {path: (item id, context, heard, a text)}; every
    path asked for is noted in `placed.asked`."""
    info = {}
    asked = []

    def library(language, store=None, ai=False, only=None):
        asked.append(only)
        return info
    monkeypatch.setattr(sentences, "_library", library)
    info_of = type("Placed", (), {})()
    info_of.info, info_of.asked = info, asked
    return info_of


def _place(placed, path, item_id, ctx=0.0, hear=sentences.REAL, text=False):
    placed.info[os.path.normcase(os.path.abspath(path))] = (item_id, ctx, hear, text)


def _write(language, name, lines):
    folder = os.path.join(get_data_path(language), "HighPriority")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def _plan(language, files, rows, tail=b"", header=None):
    """A plan file as a Generate leaves it, holding only what the candidates' reader reads: `files` the run's paths;
    `rows` {(word, reading): [(file index, sentence number, text, other unknown words), …]} — each row's pool in the
    list's order. `tail`: bytes put after the tables (the per-file tables' place)."""
    root = get_data_path(language)
    table = []
    for path in files:
        rel = os.path.relpath(path, root).replace("\\", "/")
        st = os.stat(path)
        table.append([rel, "now", plan_rules.file_digest([os.path.join(root, rel), [st.st_mtime, st.st_size], None,
                                                          None, "subtitle"]), "subtitle"])
    keys, cowords, lines, pools = [], [], [], []
    for k, key in enumerate(rows):
        keys.append([key[0], key[1], False, False, len(rows[key])])
        cowords.append([k, []])                                 # the row's own word: never one of its "others"
    strangers = len(cowords)
    cowords += [[-1, []] for _ in range(8)]                     # words that are no rows: unknown for good
    for k, key in enumerate(rows):
        pool = []
        for f, number, text, others in rows[key]:
            pool.append(len(lines))
            lines.append([text, None, 0, 0, f, [k] + list(range(strangers, strangers + others)), [], number,
                          zlib.crc32(text.encode("utf-8")), len(text)])
        pools.append([k, -1, pool, []])
    head = {"format": 4, "language": language}
    head.update(header or {})
    body = [head, {"files": table}, {"keys": keys}, {"rows": [None] * len(keys)}, {"finished": []},
            {"sentences": lines}, {"cowords": cowords}, {"pools": pools}]
    data = "\n".join(json.dumps(line, ensure_ascii=False, separators=(",", ":")) for line in body).encode("utf-8")
    path = os.path.join(get_user_file("results"), analyzer.PLAN_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(gzip.compress(data + b"\n" + tail) if tail is not None else gzip.compress(data))
    sentences._KEPT.clear()
    return path


def _texts(choices):
    return [c.text for c in choices]


def _no_library_search(monkeypatch):
    def searched(*a, **k):
        raise AssertionError("the library was searched for a word that is a row of the list")
    monkeypatch.setattr(sc, "files_holding", searched)
    monkeypatch.setattr(sc, "library_files", searched)
    monkeypatch.setattr(sc, "collect", searched)


def test_a_row_of_the_list_gets_its_kept_candidates_in_bests_order_and_the_library_is_never_searched(
        placed, monkeypatch):
    # why: Generate is the one source of a word's sentences — Best only orders the row's kept candidates
    here, other = _write("ja", "第01話.srt", [HARD]), _write("ja", "第02話.srt", ["……", EASY])
    _place(placed, here, 1)
    _place(placed, other, 2)
    _plan("ja", [here, other], {BOUKEN: [(0, 0, HARD, 3), (1, 1, EASY, 0)]})
    _no_library_search(monkeypatch)
    got = sentences.choose("ja", [BOUKEN], here=here, dial=sentences.BEST, young={})[BOUKEN]
    assert _texts(got) == [EASY, HARD], "the fewest other unknown words first, whatever the pool's order"
    assert (got[0].others, got[0].item_id, got[0].number, got[0].here) == (0, 2, 1, False)
    assert (got[1].others, got[1].item_id, got[1].number, got[1].here) == (3, 1, 0, True)
    assert os.path.normcase(got[0].file) == os.path.normcase(other)
    assert sentences.better(got[0], got[1])
    # the store is asked for the candidates' two files only, by their rel_path
    assert [sorted(only) for only in placed.asked] == [["HighPriority/第01話.srt", "HighPriority/第02話.srt"]]
    # Swap: never the old card's line again -> the next candidate
    swapped = sentences.choose("ja", [BOUKEN], dial=sentences.BEST, young={}, never={BOUKEN: {EASY}})[BOUKEN]
    assert _texts(swapped) == [HARD]
    # `files` given: only candidates of those files (and the mined episode)
    only_here = sentences.choose("ja", [BOUKEN], here=here, dial=sentences.BEST, young={}, files=[here])[BOUKEN]
    assert _texts(only_here) == [HARD]


def test_a_file_changed_or_removed_since_the_generate_gives_no_candidate(placed, monkeypatch):
    # why: the picker must never name a line that may no longer be there — the plan is as fresh as its Generate
    a, b = _write("ja", "第01話.srt", [HARD]), _write("ja", "第02話.srt", [EASY])
    _place(placed, a, 1)
    _place(placed, b, 2)
    _plan("ja", [a, b], {BOUKEN: [(0, 0, HARD, 3), (1, 0, EASY, 0)]})
    _no_library_search(monkeypatch)

    def best():
        return _texts(sentences.choose("ja", [BOUKEN], dial=sentences.BEST, young={})[BOUKEN])
    assert best() == [EASY, HARD]
    with open(b, "a", encoding="utf-8") as f:
        f.write("冒険はもう終わった。\n")              # edited: another size, another time
    assert best() == [HARD]
    os.remove(b)
    assert best() == [HARD]
    os.remove(a)
    assert best() == []


def test_a_sentence_the_token_store_no_longer_holds_at_its_place_is_dropped_and_young_words_reorder_the_rest(
        monkeypatch):
    # why: a file read again between the Generate and the mining (the indexer runs beside Connect) may have lost the
    # line; and round 4 — a sentence that also holds a word you are still learning comes first among equals
    known = sorted({"明日", "今日", "から", "に", "出掛ける", "出かける", "よう", "う"})
    first = _write("ja", "第01話.txt", [EASY])
    second = _write("ja", "第02話.txt", [TODAY])
    user_files = os.path.join(get_user_file("User Files"), "ja")
    os.makedirs(user_files, exist_ok=True)
    with open(os.path.join(user_files, "KnownWord.json"), "w", encoding="utf-8") as f:
        json.dump({"words": [{"dictForm": w, "knownStatus": "KNOWN"} for w in known]}, f, ensure_ascii=False)
    sc.build("ja", os.path.join(os.environ["SURASURA_TEST_ROOT"], "corpus-ja.zip"), progress=lambda message: None)
    info = {os.path.normcase(os.path.abspath(p)): (n, 0.0, sentences.REAL, False)
            for n, p in enumerate((first, second), 1)}
    monkeypatch.setattr(sentences, "_library", lambda language, store=None, ai=False, only=None: info)
    key = next((t[0], t[1]) for _t, tokens in analyzer.JapaneseTokenizer().tokenize_sentences(EASY)
               for t in tokens if t[0] == "冒険")
    _plan("ja", [first, second], {key: [(0, 0, EASY, 0), (1, 0, TODAY, 0)]})
    assert _texts(sentences.choose("ja", [key], dial=sentences.BEST, young={})[key]) == [EASY, TODAY]
    got = sentences.choose("ja", [key], dial=sentences.BEST, young={"今日": 1.0})[key]
    assert _texts(got) == [TODAY, EASY] and got[0].weight == 1.0 and got[1].weight == 0.0
    assert _texts(sentences.choose("ja", [key], dial=sentences.BEST, young={"冒険": 1.0})[key]) == [EASY, TODAY], \
        "its own word is never a young word it practises"
    # the plan names a place the token store holds another sentence at: read again since -> no choice (asked only
    # while young words are weighed: the file's own stamp is the first check, above)
    _plan("ja", [first, second], {key: [(0, 0, EASY, 0), (1, 0, "今日から長い冒険に出かけよう。", 0)]})
    assert _texts(sentences.choose("ja", [key], dial=sentences.BEST, young={"今日": 1.0})[key]) == [EASY]


def test_the_mined_episodes_own_line_is_always_handed_back_and_a_tie_stays_there(placed, monkeypatch):
    # why: the runner compares the best sentence with the episode's own (`better`): past the best eight the own line
    # is still looked for, and an equal sentence elsewhere never moves the word
    lines = [f"第{n}の冒険に出かけよう。" for n in range(1, 13)]
    paths = [_write("ja", f"第{n:02d}話.srt", [line]) for n, line in enumerate(lines, 1)]
    for n, path in enumerate(paths, 1):
        _place(placed, path, n, ctx=0.5 if n <= 10 else 0.0)
    _plan("ja", paths, {BOUKEN: [(n, 0, line, 0) for n, line in enumerate(lines)]})
    _no_library_search(monkeypatch)
    got = sentences.choose("ja", [BOUKEN], here=paths[11], dial=sentences.BEST, young={})[BOUKEN]
    assert len(got) == sentences.TOP + 1 and got[-1].here and got[-1].text == lines[11]
    assert _texts(got[:sentences.TOP]) == lines[:sentences.TOP], "equals keep the list's own order"
    tie = sentences.choose("ja", [BOUKEN], here=paths[3], dial=sentences.BEST, young={})[BOUKEN]
    assert tie[0].here and tie[0].text == lines[3] and not sentences.better(tie[1], tie[0])


def test_a_books_line_nothing_can_speak_is_no_choice_where_media_is_cut(placed, monkeypatch):
    # why: Best's second key — a line with its own clip, then the AI voice's, then none; a caller that cuts media
    # (`reach`) never gets a line heard by nothing, and a video whose media is gone is no choice either
    video, book, gone = (_write("ja", "第01話.srt", [HARD]), _write("ja", "本.txt", [EASY]),
                         _write("ja", "第03話.srt", [TODAY]))
    _place(placed, video, 1)
    _place(placed, gone, 3)
    rows = {BOUKEN: [(0, 0, HARD, 2), (1, 0, EASY, 0), (2, 0, TODAY, 0)]}
    _no_library_search(monkeypatch)

    def best(hear, **kw):
        _place(placed, book, 2, hear=hear, text=True)
        _plan("ja", [video, book, gone], rows)
        return sentences.choose("ja", [BOUKEN], dial=sentences.BEST, young={}, **kw)[BOUKEN]
    reach = {"reach": lambda item_id: item_id != 3}
    assert _texts(best(sentences.SILENT, **reach)) == [HARD]
    spoken = best(sentences.AI_VOICE, **reach)
    assert _texts(spoken) == [EASY, HARD] and spoken[0].ai and spoken[0].audio
    assert _texts(best(sentences.AI_VOICE, books=False, **reach)) == [HARD], "Anki Miner not reading books"
    assert _texts(best(sentences.SILENT)) == [TODAY, EASY, HARD], "no media cut: a silent line is a choice, last of its ease"


def test_chinese_rows_are_read_the_same_way(placed, monkeypatch):
    easy, hard = "他接到电话了。", "那个陌生人打来的电话很奇怪。"
    here, other = _write("zh", "第01集.srt", [hard]), _write("zh", "第02集.srt", [easy])
    _place(placed, here, 1)
    _place(placed, other, 2)
    key = ("电话", "")
    _plan("zh", [here, other], {key: [(0, 0, hard, 2), (1, 0, easy, 0)]})
    _no_library_search(monkeypatch)
    got = sentences.choose("zh", [key], here=here, dial=sentences.BEST, young={})[key]
    assert _texts(got) == [easy, hard] and got[0].others == 0 and got[1].here


def test_no_plan_a_damaged_one_or_another_languages_leaves_the_library_search(monkeypatch):
    # why: before the first Generate, or with a plan that can't be read, Best still finds the library's sentence
    monkeypatch.setattr(sentences, "_library", lambda language, store=None, ai=False, only=None: {})
    here = _write("ja", "第01話.txt", [EASY])
    user_files = os.path.join(get_user_file("User Files"), "ja")
    os.makedirs(user_files, exist_ok=True)
    with open(os.path.join(user_files, "KnownWord.json"), "w", encoding="utf-8") as f:
        json.dump({"words": []}, f)
    sc.build("ja", os.path.join(os.environ["SURASURA_TEST_ROOT"], "corpus-ja.zip"), progress=lambda message: None)
    key = next((t[0], t[1]) for _t, tokens in analyzer.JapaneseTokenizer().tokenize_sentences(EASY)
               for t in tokens if t[0] == "冒険")
    path = os.path.join(get_user_file("results"), analyzer.PLAN_FILE)

    def best(keys=(key,)):
        sentences._KEPT.clear()
        return sentences.choose("ja", list(keys), dial=sentences.BEST, files=[here], young={})
    assert plan_engine.candidates(path) is None and _texts(best()[key]) == [EASY]         # no plan
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"not a plan")
    assert plan_engine.candidates(path) is None and _texts(best()[key]) == [EASY]         # damaged
    _plan("ja", [here], {key: [(0, 0, "別の文の冒険。", 0)]}, header={"language": "zh"})
    assert plan_engine.candidates(path, "ja") is None and _texts(best()[key]) == [EASY]   # another language's
    _plan("ja", [here], {key: [(0, 0, EASY, 0)]}, header={"format": 2})
    assert plan_engine.candidates(path, "ja") is None                                     # a plan before the pools
    # a word with no row beside one with a row: the row from the list, the other from the library
    other = ("明日", "アシタ")
    _plan("ja", [here], {other: [(0, 0, EASY, 1)]})
    got = best((key, other))
    assert _texts(got[key]) == [EASY] and got[key][0].number is None, "no row: the library's sentence"
    assert _texts(got[other]) == [EASY] and got[other][0].number == 0 and got[other][0].others == 1
    # a row whose pool is empty, and a word nowhere: no sentence
    _plan("ja", [here], {key: []})
    assert best((key, ("竜巻", "タツマキ"))) == {key: [], ("竜巻", "タツマキ"): []}


def test_the_candidates_reader_stops_before_the_per_file_tables(placed):
    # why: those tables are most of a large library's plan (25 of 45 MB at 20,000 files) — the mining never unzips
    # them, so its read follows the list's rows; a stream damaged there still gives its candidates
    here = _write("ja", "第01話.srt", [EASY])
    _place(placed, here, 1)
    tail = b'{"firsts":[' + b'{"damaged' * 50000 + b"\n" + b'{"f":0,"main":[' + os.urandom(1 << 16).hex().encode()
    path = _plan("ja", [here], {BOUKEN: [(0, 0, EASY, 0)]}, tail=tail)
    with open(path, "rb") as f:
        data = f.read()
    with open(path, "wb") as f:
        f.write(data[:-4096])                       # the stream's end cut off: its CRC, the per-file tables' tail
    with pytest.raises(Exception):
        gzip.decompress(data[:-4096])
    kept = plan_engine.candidates(path, "ja")
    assert kept is not None and len(kept.sentences) == 1 and kept.pools[0] == (-1, [0], [])
    with pytest.raises(plan_engine.PlanError):      # (the whole plan's reader still checks the stream)
        plan_engine.load(path)
    assert _texts(sentences.choose("ja", [BOUKEN], dial=sentences.BEST, young={})[BOUKEN]) == [EASY]


def test_a_word_met_in_hundreds_of_files_costs_its_candidates_only(placed, monkeypatch):
    # why: the search's cost followed the library (every file's counts were read); now a row's cost is its pool's —
    # here 60 candidates out of a 400-file run: the store is asked for 60 paths, at most TOP + 1 files are looked at
    held = [_write("ja", f"第{n:03d}話.srt", [f"冒険の旅、その{n}。"]) for n in range(60)]
    for n, path in enumerate(held):
        _place(placed, path, n + 1)
    _plan("ja", held, {BOUKEN: [(n, 0, f"冒険の旅、その{n}。", n % 3) for n in range(60)]})
    plan = os.path.join(get_user_file("results"), analyzer.PLAN_FILE)
    kept = plan_engine.candidates(plan, "ja")
    # the run's other 340 files: rows of the plan's `files` no candidate comes from (never on disk here)
    extra = [[f"GoalContent/別の番組/第{n:03d}話.srt", "goal", "0" * 16, "subtitle"] for n in range(340)]
    monkeypatch.setattr(plan_engine, "candidates", lambda path, language=None: kept._replace(files=kept.files + extra))
    _no_library_search(monkeypatch)
    looked = []
    real_stat = os.stat

    def stat(path, *a, **k):
        if str(path).endswith(".srt"):
            looked.append(path)
        return real_stat(path, *a, **k)
    monkeypatch.setattr(os, "stat", stat)
    got = sentences.choose("ja", [BOUKEN], dial=sentences.BEST, young={})[BOUKEN]
    assert len(got) == sentences.TOP and all(c.others == 0 for c in got)
    assert len(placed.asked) == 1 and len(placed.asked[0]) == 60
    assert len({os.path.normcase(str(path)) for path in looked}) <= sentences.TOP + 1


def test_an_empty_library_gives_every_word_an_empty_list(monkeypatch):
    monkeypatch.setattr(sentences, "_library", lambda language, store=None, ai=False, only=None: {})
    for language, key in (("ja", BOUKEN), ("zh", ("电话", ""))):
        assert sentences.choose(language, [key], dial=sentences.BEST, young={}) == {key: []}
        assert sentences.choose(language, [], dial=sentences.BEST) == {}


def test_two_lines_are_compared_by_one_rule_a_cards_field_and_its_subtitle_line_are_the_same_line():
    # why: `never` (Swap's old card) must stop the card's own line coming back — a card's sentence field carries
    # markup, kana in brackets and a sound tag the subtitle's line never had; one rule, the picker's
    card = "<b>明日</b>から 冒険[ぼうけん]に出かけよう！[sound:line.mp3]"
    assert sentences.norm_line(card) == sentences.norm_line(EASY) == "明日から冒険に出かけよう"
    assert sentences.same_line(EASY, {card}) and sentences.same_line("冒険に出かけよう", {card})
    assert not sentences.same_line(HARD, {card}) and not sentences.same_line(EASY, set())
    assert not sentences.same_line("。", {"。"}) and not sentences.same_line("あ", {"あ。"}), "two characters at least"
    assert sentences.same_line("ＡＢＣの冒険", {"ABCの冒険"}), "full-width and half-width letters are the same line"


def test_the_mined_episodes_own_context_is_what_its_line_weighs_when_the_list_keeps_none_of_its_lines(placed):
    # why: the runner moves a word only for a strictly better sentence — with the own line weighed 0, any sentence
    # elsewhere with a little context would take every word away from the episode being mined
    here, outside = _write("ja", "第01話.srt", [EASY]), _write("ja", "第02話.srt", [TODAY])
    _place(placed, here, 1, ctx=0.4762)
    assert sentences.context_of("ja", here) == 0.4762
    assert placed.asked == [["HighPriority/第01話.srt"]], "one item asked of the store, never the library"
    assert sentences.context_of("ja", outside) == 0.0 and sentences.context_of("ja", "") == 0.0
    mine = sentences.Choice(here, 1, EASY, 0, sentences.context_of("ja", here), True, True)
    assert not sentences.better(sentences.Choice(outside, 2, TODAY, 0, 0.2, False, True), mine)
    assert sentences.better(sentences.Choice(outside, 2, TODAY, 0, 0.8, False, True), mine), "a show you saw lately"
