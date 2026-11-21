"""A list word Generate counted only inside a rare compound of an episode is found there by Connect's pick (Kantan-MA,
a tester's report 2026-11-21: 大衆 in Dungeon Meshi S01 Ep 1 never got its card, and *Mine again* didn't make it).

Generate counts a compound too rare for the list (under its cut-off) toward its free parts (`analyzer.LearningView`,
`credits`): the episode's one 大衆食堂 is a use of 大衆, and the list names the episode for 大衆. Connect's pick read the
words with no counts (every compound itself), so it met 大衆食堂, which isn't on the list, and never 大衆: the word was
left out silently at the first mining, at every level job and at *Mine again*. Now the pick reads the list's own counts
(`verbs._counted`, the last Generate's library_frequency.json): the part is an occurrence too, a line where the word
stands on its own still first.

The subtitle is tests/Test Resources/ja/rare_compound_episode.ja.srt (natural Japanese, written for these tests);
the counts are a library_frequency.json as Generate writes it, in the test's own results folder.
"""
import json
import os
from types import SimpleNamespace

import pytest

from app import analyzer, cues
from app.cli import verbs
from app.connect import pick

DAISHU, SHOKUDOU, DAISHU_SHOKUDOU = ("大衆", "タイシュウ"), ("食堂", "ショクドウ"), ("大衆食堂", "タイシュウショクドウ")


@pytest.fixture(autouse=True)
def _a_japanese_run():
    analyzer.SANITIZE_JA = True             # as analyzer.main sets it (conftest restores the global)


@pytest.fixture
def episode(ja_resources_dir):
    return os.path.join(ja_resources_dir, "rare_compound_episode.ja.srt")


def _results(folder, words, floor=5):
    """The last Generate's counts as library_frequency.json holds them: {(lemma, reading): uses}, the cut-off."""
    os.makedirs(folder, exist_ok=True)
    data = {"settings": {"min_count": floor, "language": "ja"},
            "words": {f"{w}|{r}": [n, 0, 0, n, 1, n * 2, w] for (w, r), n in words.items()}}
    with open(os.path.join(folder, "library_frequency.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return folder


@pytest.fixture
def verb(monkeypatch, tmp_path):
    """`verbs.pick` as Connect calls it (the list handed in), with its results folder the test's own; Anki closed."""
    results = str(tmp_path / "results")
    monkeypatch.setattr(verbs, "_results_dir", lambda: results)
    monkeypatch.setattr(verbs, "settings", lambda: {"target_language": "ja"})
    monkeypatch.setattr(verbs, "require_set_up", lambda lang: None)
    monkeypatch.setattr(verbs, "_anki_miner_setup", lambda *a, **k: None)
    monkeypatch.setattr(pick, "carded", lambda *a, **k: (set(), "anki"))
    verbs._COUNTED.clear()

    def run(file, listed, new, mode="list", lang="ja"):
        monkeypatch.setattr(verbs, "_known_test", lambda *a: (lambda key: key not in new))
        return verbs.pick(SimpleNamespace(lang=lang, file=file, video=None, words=mode, job="ma", wait=0.0,
                                          made=set(), listed=listed, reading=None))
    run.results = results
    return run


def test_a_list_word_said_only_inside_a_rare_compound_is_sent_from_that_line(verb, episode):
    # why: the report's case — the list names this episode for 大衆 (Generate counted 大衆食堂, said once, as 大衆);
    # the pick found only 大衆食堂, so the word was never sent, at the first mining, a level job or *Mine again*
    _results(verb.results, {DAISHU: 30, SHOKUDOU: 40, DAISHU_SHOKUDOU: 1})
    out = verb(episode, {DAISHU: 0}, {DAISHU, SHOKUDOU, DAISHU_SHOKUDOU})
    (word,) = [w for w in out["words"] if w["word"] == "大衆"]
    assert word["reading"] == "タイシュウ" and word["line_start"] == 4.1        # 地上の町には大衆食堂がたくさんあるのに。
    assert word["surface"] == "大衆" and word["sent"] == ["大衆"]           # Anki Miner finds 大衆 written in the line
    assert word["front_reading"] == "たいしゅう"
    assert word["line_text"] == "地上の町には大衆食堂がたくさんあるのに。"


def test_before_the_first_generate_every_word_is_itself(verb, episode):
    # why: no counts yet (no library_frequency.json): no compound is rare, as the list has none — the pick as before,
    # and nothing fails for want of the file
    out = verb(episode, {DAISHU: 0}, {DAISHU, SHOKUDOU, DAISHU_SHOKUDOU})
    assert [w["word"] for w in out["words"]] == []


def test_a_compound_at_the_cut_off_stays_one_word(verb, episode):
    # why: 大衆食堂 said often enough is a list word of its own (its own card): it never counts as 大衆
    _results(verb.results, {DAISHU: 30, SHOKUDOU: 40, DAISHU_SHOKUDOU: 5})
    out = verb(episode, {DAISHU: 0, DAISHU_SHOKUDOU: 1}, {DAISHU, SHOKUDOU, DAISHU_SHOKUDOU})
    assert [w["word"] for w in out["words"]] == ["大衆食堂"]


def test_a_known_compound_is_never_taken_apart(verb, episode):
    # why: a compound you know is no rare compound (`LearningView.rare`): its parts get no use from it
    _results(verb.results, {DAISHU: 30, SHOKUDOU: 40, DAISHU_SHOKUDOU: 1})
    out = verb(episode, {DAISHU: 0}, {DAISHU, SHOKUDOU})
    assert out["words"] == []


def test_the_compounds_line_counts_its_parts_as_the_lines_new_words(verb, episode):
    # why: in its line a rare compound is its parts (`units`), as the report reads it: with 食堂 known, 大衆 is the
    # line's one new word — i+1 — not "大衆食堂 besides"
    _results(verb.results, {DAISHU: 30, SHOKUDOU: 40, DAISHU_SHOKUDOU: 1})
    out = verb(episode, {DAISHU: 0}, {DAISHU, DAISHU_SHOKUDOU})
    (word,) = out["words"]
    assert word["word"] == "大衆" and word["other_new"] == 0


def test_with_cards_for_every_new_word_the_part_is_sent_beside_the_compound(verb, episode):
    # why: the `unknown` mode sends every new word of the episode; 大衆 is one of them as the list counts it
    _results(verb.results, {DAISHU: 30, SHOKUDOU: 40, DAISHU_SHOKUDOU: 1})
    out = verb(episode, None, {DAISHU, DAISHU_SHOKUDOU}, mode="unknown")
    assert {"大衆", "大衆食堂"} <= {w["word"] for w in out["words"]}


def test_a_line_where_the_word_stands_on_its_own_is_taken_first(tmp_path):
    # why: Generate takes a word's example only where it stands on its own; a card does too, the compound's line only
    # when there is no other — even an earlier one
    path = tmp_path / "episode.ja.srt"
    path.write_text("1\n00:00:01,000 --> 00:00:03,000\n大衆食堂で昼ご飯を食べた。\n\n"
                    "2\n00:00:05,000 --> 00:00:07,000\n大衆の声を聞くべきだ。\n", encoding="utf-8")
    read = cues.read(str(path), "ja")
    tokens = cues.tokens(read, "ja")
    new = {DAISHU, DAISHU_SHOKUDOU}
    view = analyzer.LearningView({DAISHU: 30, DAISHU_SHOKUDOU: 1}, 5, known=lambda key: key not in new)
    out = pick.pick(read, tokens, "ja", lambda key: key not in new, listed={DAISHU: 0}, view=view)
    assert [(w["word"], w["line_start"]) for w in out["words"]] == [("大衆", 5.0)]


def test_a_part_the_compound_writes_otherwise_takes_the_compounds_own_spelling_of_it():
    # why: the card names the word as the line writes it (こと自体's 事 is こと there), else Anki Miner can't find it;
    # a part the line doesn't write at all can make no card from it
    token = SimpleNamespace(node=None, written="大衆食堂", cue=0, sentence="s")
    assert pick._credited(token, DAISHU).surface == "大衆"
    assert pick._credited(token, ("民衆", "ミンシュウ")) is None
    tagger = analyzer.JapaneseTokenizer()
    ((_sentence, word, node),) = [t for t in cues._read(tagger, "こと自体", "ja", None)]
    found = pick._credited(cues.Token(*word, 0, "s", node, "こと自体"), ("事", "コト"))
    assert found is not None and found.surface == "こと" and found.lemma == "事"


def test_chinese_reads_no_counts(verb, tmp_path):
    # why: Chinese has no compound table: its pick never reads the counts (and never fails for them)
    _results(verb.results, {DAISHU: 30})
    assert verbs._counted("zh") == (None, 0)


def test_the_counts_are_read_once_while_the_file_is_unchanged(verb, monkeypatch):
    # why: a run asks for every episode it mines; a 4 MB file read once is enough until Generate writes a new one
    _results(verb.results, {DAISHU: 30, DAISHU_SHOKUDOU: 1})
    reads = []
    real = analyzer.library_counts
    monkeypatch.setattr(analyzer, "library_counts", lambda *a: reads.append(a) or real(*a))
    first = verbs._counted("ja")
    assert verbs._counted("ja") is first and len(reads) == 1
    path = os.path.join(verb.results, "library_frequency.json")
    _results(verb.results, {DAISHU: 30, DAISHU_SHOKUDOU: 2, SHOKUDOU: 9})
    os.utime(path, ns=(os.stat(path).st_atime_ns, os.stat(path).st_mtime_ns + 10 ** 9))
    assert verbs._counted("ja")[0][SHOKUDOU] == 9 and len(reads) == 2


def test_a_part_that_is_a_persons_name_is_still_a_name():
    # why: Ignore names keeps a name out of the cards; a name met only inside a compound is read through its piece
    # (`_Part`), which must answer the name check as the tagger's own node does — else it slips past Ignore names
    tagger = analyzer.JapaneseTokenizer()
    ((_sentence, _word, node),) = [t for t in cues._read(tagger, "田中", "ja", None)]
    assert pick._is_name(node), "the test's name must be one, or this proves nothing"
    assert pick._is_name(pick._Part(node.surface, node.feature))


@pytest.mark.parametrize("skip_single, offered", [(True, {"出版社", "出版"}), (False, {"出版社", "出版", "社"})])
def test_a_one_character_part_the_list_never_offers_is_never_credited(tmp_path, skip_single, offered):
    # why: Generate gives a rare compound's use to a part only where the list can offer it (`_never`: 社 alone, with
    # "List one-kanji words only when they're dictionary words" on); every new word mode sends nothing more than that
    path = tmp_path / "episode.ja.srt"
    path.write_text("1\n00:00:01,000 --> 00:00:03,000\n姉は出版社に勤めている。\n", encoding="utf-8")
    read = cues.read(str(path), "ja")
    tokens = cues.tokens(read, "ja")
    new = {("出版社", "シュッパンシャ"), ("出版", "シュッパン"), ("社", "シャ")}
    known = lambda key: key not in new                                          # noqa: E731
    view = analyzer.LearningView({("出版社", "シュッパンシャ"): 1}, 5, known=known)
    out = pick.pick(read, tokens, "ja", known, mode="unknown", view=view, skip_single=skip_single)
    assert {w["word"] for w in out["words"]} == offered
