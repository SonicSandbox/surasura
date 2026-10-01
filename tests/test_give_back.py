"""The one learning rule (analyzer.LearningView): a compound too rare for the list counts toward its free parts, and a
compound none of whose parts is an unknown is read already — the same in the list, the Rarity slider, 例文 and the
sentence dictionary.

A made-up library under the sandbox root. Its compounds are dictionary words — 前言撤回 (前言 is never used alone:
bound), トランスジェンダー, 千載一遇 (both halves bound), 秘密結社, 経済成長 and 経済成長期 (whose parts are 経済成長 +
期) — joined here by a fixture table (both the tokenizer's join and its parts table are patched), so these tests
hold whatever the shipped table holds. Floors are raw counts (--min-freq) unless a test says otherwise.
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from app import analyzer, word_selection

# spelling -> (lemma, reading, parts: (part lemma, part reading, free))
TABLE = {
    "前言撤回": ("前言撤回", "ゼンゲンテッカイ", (("前言", "ゼンゲン", False), ("撤回", "テッカイ", True))),
    "トランスジェンダー": ("トランスジェンダー", "トランスジェンダー",
                   (("トランス", "トランス", True), ("ジェンダー", "ジェンダー", True))),
    "千載一遇": ("千載一遇", "センザイイチグウ", (("千載", "センザイ", False), ("一遇", "イチグウ", False))),
    "秘密結社": ("秘密結社", "ヒミツケッシャ", (("秘密", "ヒミツ", True), ("結社", "ケッシャ", True))),
    "経済成長": ("経済成長", "ケイザイセイチョウ", (("経済", "ケイザイ", True), ("成長", "セイチョウ", True))),
    "経済成長期": ("経済成長期", "ケイザイセイチョウキ", (("経済成長", "ケイザイセイチョウ", True), ("期", "キ", True))),
}
PARTS = {(lemma, reading): parts for lemma, reading, parts in TABLE.values()}

# File 1 meets the compounds; file 2 meets some of their parts on their own.
FIRST = "\n".join([
    "大臣は前言撤回を迫られた。",
    "市長も前言撤回に追い込まれた。",
    "トランスジェンダーの選手が出場した。",
    "トランスジェンダーについて学んだ。",
    "千載一遇の好機が訪れた。",
    "秘密結社が暗躍している。",
    "秘密結社の会合が開かれた。",
    "秘密結社に入った。",
    "秘密結社を追う。",
    "経済成長期の日本を振り返る。",
    "経済成長が鈍った。",
])
SECOND = "\n".join([
    "彼は発言を撤回した。",
    "ジェンダーの問題を考える。",
    "トランスの音楽を聴く。",
    "トランスの曲が好きだ。",
    "経済が回復した。",
    "選手が走った。",
    "選手が笑った。",
    "好機が来た。",
    "好機を待つ。",
])


@pytest.fixture
def compounds(monkeypatch):
    """The fixture table as the tokenizer's compounds: a run of nodes spelling a TABLE word is one JoinedWord with
    its lemma and reading (after the real joins — a word the shipped table already joined gets the fixture's key),
    and analyzer.compound_parts() is TABLE's parts."""
    real = analyzer.join_affixes

    def join(words, joins=None, library=True, **options):
        words = real(words, joins, library, **options)
        out, i = [], 0
        while i < len(words):
            word = words[i]
            if isinstance(word, analyzer.JoinedWord) and word.surface in TABLE:
                lemma, reading, _parts = TABLE[word.surface]
                out.append(analyzer.JoinedWord(word.surface, word.feature._replace(lemma=lemma, lForm=reading),
                                               word.parts, word.white_space))
                i += 1
                continue
            for n in (3, 2):
                run = words[i:i + n]
                spelling = "".join(w.surface for w in run)
                if len(run) == n and spelling in TABLE:
                    lemma, reading, _parts = TABLE[spelling]
                    out.append(analyzer._joined(run, spelling, "名詞", (lemma, reading)))
                    i += n
                    break
            else:
                out.append(word)
                i += 1
        return out
    monkeypatch.setattr(analyzer, "join_affixes", join)
    monkeypatch.setattr(analyzer, "compound_parts", lambda: PARTS)


@pytest.fixture
def library(compounds):
    """The two files under the sandbox root (SURASURA_TEST_ROOT, set by conftest), no known words yet."""
    root = Path(os.environ["SURASURA_TEST_ROOT"])
    high = root / "data" / "ja" / "HighPriority"
    high.mkdir(parents=True)
    (high / "a_first.txt").write_text(FIRST, encoding="utf-8")
    (high / "b_second.txt").write_text(SECOND, encoding="utf-8")
    uf = root / "User Files" / "ja"
    uf.mkdir(parents=True)
    _known(root, [])
    (root / "results").mkdir()
    return root


def _known(root, words):
    (root / "User Files" / "ja" / "KnownWord.json").write_text(
        json.dumps({"words": [{"dictForm": w, "knownStatus": "KNOWN"} for w in words]}, ensure_ascii=False),
        encoding="utf-8")


def _run(root, *extra_args):
    """One Generate over the sandbox library -> (priority list rows by Word, library_frequency.json)."""
    results = root / "results"
    listed = results / "priority_learning_list.csv"
    if listed.exists():
        listed.unlink()                     # a run that lists nothing writes none
    with patch("app.analyzer.RESULTS_DIR", str(results)), \
            patch("app.analyzer.OUTPUT_CSV", str(results / "priority_learning_list.csv")), \
            patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
            patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
            patch("sys.argv", ["analyzer.py", "--language", "ja", *extra_args]):
        analyzer.main()
    rows = pd.read_csv(listed).fillna("").to_dict("records") if listed.exists() else []
    lib = json.loads((results / "library_frequency.json").read_text(encoding="utf-8"))
    return {row["Word"]: row for row in rows}, lib


def _contexts(row):
    return [row[k] for k in row if k.startswith("Context ") and row[k]]


# --- the view itself --------------------------------------------------------------------------------------------- #
def _view(counts, floor=3, known=()):
    return analyzer.LearningView(counts, floor, lambda key: key[0] in known, parts=PARTS, joins={})


def test_a_rare_compound_is_its_free_parts_and_a_bound_part_keeps_it_whole():
    """トランスジェンダー (both parts free) is two words to learn; 千載一遇 (both bound) and 前言撤回 (前言 bound) stay one
    in a sentence — though 前言撤回 still counts toward 撤回 on the list. A listed compound (秘密結社, 4 uses) is
    itself; without counts (before the first Generate) nothing is rare."""
    view = _view({("トランスジェンダー", "トランスジェンダー"): 2, ("千載一遇", "センザイイチグウ"): 1,
                  ("前言撤回", "ゼンゲンテッカイ"): 2, ("秘密結社", "ヒミツケッシャ"): 4})
    assert view.units(("トランスジェンダー", "トランスジェンダー")) == (("トランス", "トランス"), ("ジェンダー", "ジェンダー"))
    assert view.units(("千載一遇", "センザイイチグウ")) == (("千載一遇", "センザイイチグウ"),)
    assert view.units(("前言撤回", "ゼンゲンテッカイ")) == (("前言撤回", "ゼンゲンテッカイ"),)
    assert view.credits(("前言撤回", "ゼンゲンテッカイ")) == (("撤回", "テッカイ"),)
    assert view.credits(("千載一遇", "センザイイチグウ")) == ()
    assert view.units(("秘密結社", "ヒミツケッシャ")) == (("秘密結社", "ヒミツケッシャ"),)
    assert view.credits(("秘密結社", "ヒミツケッシャ")) == ()
    unread = _view(None)
    assert unread.units(("トランスジェンダー", "トランスジェンダー")) == (("トランスジェンダー", "トランスジェンダー"),)
    assert unread.credits(("前言撤回", "ゼンゲンテッカイ")) == ()


def test_a_rare_part_is_taken_apart_in_turn_and_a_known_compound_is_never_rare():
    """経済成長期 -> 経済成長 + 期 -> 経済 + 成長 + 期 when 経済成長 is rare too; listed, 経済成長 is a word of its own.
    A compound the learner knows is never taken apart, however rare."""
    rare_both = _view({("経済成長期", "ケイザイセイチョウキ"): 1, ("経済成長", "ケイザイセイチョウ"): 1})
    assert rare_both.units(("経済成長期", "ケイザイセイチョウキ")) == (
        ("経済", "ケイザイ"), ("成長", "セイチョウ"), ("期", "キ"))
    assert rare_both.credits(("経済成長期", "ケイザイセイチョウキ")) == (
        ("経済", "ケイザイ"), ("成長", "セイチョウ"), ("期", "キ"))
    listed_part = _view({("経済成長期", "ケイザイセイチョウキ"): 1, ("経済成長", "ケイザイセイチョウ"): 5})
    assert listed_part.units(("経済成長期", "ケイザイセイチョウキ")) == (("経済成長", "ケイザイセイチョウ"), ("期", "キ"))
    known = _view({("トランスジェンダー", "トランスジェンダー"): 1}, known={"トランスジェンダー"})
    assert known.units(("トランスジェンダー", "トランスジェンダー")) == (("トランスジェンダー", "トランスジェンダー"),)
    # the word a sentence is ranked for is never its own parts against it
    assert rare_both.units(("経済成長期", "ケイザイセイチョウキ"), keep=("経済成長期", "ケイザイセイチョウキ")) == (
        ("経済成長期", "ケイザイセイチョウキ"),)
    assert rare_both.units(("経済成長期", "ケイザイセイチョウキ"), keep=("経済成長", "ケイザイセイチョウ")) == (
        ("経済成長", "ケイザイセイチョウ"), ("期", "キ"))


def test_a_compound_none_of_whose_parts_is_an_unknown_is_read_already():
    """秘密結社 with 秘密 and 結社 known reads already; with one part unknown it doesn't — and a part that is itself
    such a compound counts as read (経済成長期 with 経済, 成長 and 期 known)."""
    view = _view({}, known={"秘密", "結社", "経済", "成長", "期"})
    known = lambda key: key[0] in {"秘密", "結社", "経済", "成長", "期"}
    assert view.readable(("秘密結社", "ヒミツケッシャ"), known)
    assert not view.readable(("秘密結社", "ヒミツケッシャ"), lambda key: key[0] == "秘密")
    assert view.readable(("経済成長期", "ケイザイセイチョウキ"), known)
    assert not view.readable(("撤回", "テッカイ"), known)          # no compound, no known base


# A table that went wrong: an entry holding itself, and two holding each other — no dictionary word is its own part,
# but a table build can write one (a verb read as itself + an ending). Such an entry must be one word, never a crash.
BAD = {
    ("教える", "オシエル"): (("教える", "オシエル", True), ("得る", "エル", True)),
    ("表裏", "ヒョウリ"): (("裏表", "ウラオモテ", True), ("一体", "イッタイ", True)),
    ("裏表", "ウラオモテ"): (("表裏", "ヒョウリ", True), ("反対", "ハンタイ", True)),
    ("表裏関係", "ヒョウリカンケイ"): (("表裏", "ヒョウリ", True), ("関係", "カンケイ", True)),
}
TEACH, FRONT, BACK, RELATION = ("教える", "オシエル"), ("表裏", "ヒョウリ"), ("裏表", "ウラオモテ"), ("表裏関係", "ヒョウリカンケイ")


def test_an_entry_that_holds_itself_or_its_own_holder_is_one_word_never_a_crash():
    """教える = 教える + 得る and 表裏 / 裏表 holding each other: each is one unit, credits nothing and is never read
    through its parts (the parts would lead back to it). A compound around one (表裏関係) is still taken apart, the bad
    entry staying one unit; and every other entry of the same table gives what it always gives."""
    table = {**PARTS, **BAD}
    counts = {key: 1 for key in table}
    view = analyzer.LearningView(counts, 3, lambda key: False, parts=table, joins={})
    for key in (TEACH, FRONT, BACK):
        assert view.units(key) == (key,)
        assert view.units(key, keep=RELATION) == (key,)
        assert view.credits(key) == ()
    assert view.units(RELATION) == (FRONT, ("関係", "カンケイ"))
    assert view.credits(RELATION) == (("関係", "カンケイ"),)
    known = lambda key: key[0] in {"得る", "一体", "反対", "関係"}    # every part of them but themselves
    assert not view.readable(TEACH, known)
    assert not view.readable(FRONT, known) and not view.readable(BACK, known)
    assert not view.readable(RELATION, known)
    assert view.readable(RELATION, lambda key: known(key) or key == FRONT)
    # the rest of the table, untouched
    assert view.units(("トランスジェンダー", "トランスジェンダー")) == (("トランス", "トランス"), ("ジェンダー", "ジェンダー"))
    assert view.credits(("前言撤回", "ゼンゲンテッカイ")) == (("撤回", "テッカイ"),)


def test_a_table_that_holds_itself_leaves_the_slider_and_generate_working(library, monkeypatch):
    """The same bad entries in the tokenizer's table: the Rarity slider's numbers and a whole Generate still come out
    — 教える, met once (too rare for the list), is one word — with every other word as it was."""
    from app import token_index
    table = {**PARTS, **BAD}
    monkeypatch.setattr(analyzer, "compound_parts", lambda: table)
    counts = {TEACH: 1, FRONT: 1, BACK: 1, RELATION: 2, ("関係", "カンケイ"): 1, ("得る", "エル"): 1}
    freqs = token_index.unknown_distribution(counts, 50, skip_singles=True, language="ja")
    previews = word_selection.band_previews(freqs, BANDS_PPM, 2)
    assert previews["native"]["word_count"] == 1                   # 関係: its own use + 表裏関係's two
    (library / "data" / "ja" / "HighPriority" / "c_third.txt").write_text("先生が数学を教える。", encoding="utf-8")
    rows, lib = _run(library, "--min-freq", "3")
    assert lib["words"]["教える|オシエル"][0] == 1
    assert rows["撤回"]["Occurrences"] == 3 and rows["ジェンダー"]["Occurrences"] == 3


# --- the list ---------------------------------------------------------------------------------------------------- #
def test_a_rare_compound_lists_its_free_parts_and_never_its_bound_ones(library):
    """At a floor of 3: 撤回 is met once alone and twice inside 前言撤回 (2 uses: rare) — listed with 3; ジェンダー once
    + twice inside トランスジェンダー; 経済 once + once inside 経済成長 + once inside 経済成長期 (whose part 経済成長 is
    rare too). The bound 前言, 千載 and 一遇 never gain a use; the listed 秘密結社 (4 uses) gives nothing to 秘密 or
    結社; 成長 (2 uses, both inside) stays under the floor."""
    rows, _lib = _run(library, "--min-freq", "3")
    assert rows["撤回"]["Occurrences"] == 3
    assert rows["ジェンダー"]["Occurrences"] == 3
    assert rows["トランス"]["Occurrences"] == 4
    assert rows["経済"]["Occurrences"] == 3
    assert rows["秘密結社"]["Occurrences"] == 4
    for word in ("前言", "千載", "一遇", "秘密", "結社", "成長", "前言撤回", "トランスジェンダー", "千載一遇", "経済成長"):
        assert word not in rows, word


def test_a_word_takes_example_sentences_only_where_it_stands_on_its_own(library):
    """撤回 is on the list through 前言撤回, but a 前言撤回 sentence is no example of it — on a card the word isn't
    the word on the page."""
    rows, _lib = _run(library, "--min-freq", "3")
    assert _contexts(rows["撤回"]) == ["彼は発言を撤回した。"]
    assert _contexts(rows["ジェンダー"]) == ["ジェンダーの問題を考える。"]
    assert _contexts(rows["経済"]) == ["経済が回復した。"]
    assert all("トランスジェンダー" not in c for c in _contexts(rows["トランス"]))


def test_in_a_sentence_a_rare_compound_is_its_parts_unless_one_is_bound(library, monkeypatch):
    """How hard a sentence is: トランスジェンダー (rare, free halves) is トランス + ジェンダー; 千載一遇 (rare, bound
    halves) stays one word. Read off the candidate sentences the run kept for 選手 and 好機."""
    monkeypatch.setenv("SURASURA_DEBUG_WORD_STATS", "1")
    _run(library, "--min-freq", "3")
    stats = json.loads((library / "results" / "word_stats.json").read_text(encoding="utf-8"))

    def units_with(word, text):
        return {tuple(lr) for ctx in stats[word]["candidate_contexts"] if ctx[4] == text for lr in ctx[3]}
    players = units_with("選手|センシュ", "トランスジェンダーの選手が出場した。")
    assert {("トランス", "トランス"), ("ジェンダー", "ジェンダー")} <= players
    assert ("トランスジェンダー", "トランスジェンダー") not in players
    chance = units_with("好機|コウキ", "千載一遇の好機が訪れた。")
    assert ("千載一遇", "センザイイチグウ") in chance
    assert not chance & {("千載", "センザイ"), ("一遇", "イチグウ")}


def test_the_library_map_keeps_each_rare_compound_with_its_own_uses_and_no_tokens_are_added(library):
    """library_frequency.json has 前言撤回 (2), 千載一遇 (1) and 経済成長 (1 — its use inside 経済成長期 is that word's,
    never credited to it: which compounds are rare is fixed before anything is credited). The library's size is the
    tokenizer's: crediting adds no tokens, so the floor a band gives is the one the slider shows."""
    _rows, lib = _run(library, "--min-freq", "3")
    words = lib["words"]
    assert words["前言撤回|ゼンゲンテッカイ"][0] == 2
    assert words["千載一遇|センザイイチグウ"][0] == 1
    assert words["経済成長|ケイザイセイチョウ"][0] == 1
    assert words["撤回|テッカイ"][0] == 3
    stats = json.loads((library / "results" / "file_statistics.json").read_text(encoding="utf-8"))
    assert lib["settings"]["total_tokens"] == sum(s["Total Words"] for s in stats)
    assert lib["settings"]["language"] == "ja"


def test_a_word_met_first_inside_a_compound_has_its_row_in_that_file_and_no_coverage_from_it(library):
    """The progressive list: 撤回 is first met inside 前言撤回, in the first file — its row sits there, counting those
    2 uses; learning it makes none of that file's tokens known (they are 前言撤回's), so the file's coverage never
    passes 100%."""
    _run(library, "--min-freq", "3")
    prog = pd.read_csv(library / "results" / "progressive_learning_list.csv")
    retract = prog[prog["Word"] == "撤回"].iloc[0]
    assert retract["Sequence"] == 1 and retract["Occurrences (File)"] == 2
    assert retract["New %"] == retract["Current %"]
    assert (prog["New %"] <= 100).all()


def test_a_compound_of_known_parts_stays_on_the_list_at_half_score(library):
    """秘密結社 with 秘密 and 結社 known: still a word to learn (its card, its reading), listed lower — as a word read
    through its known word is."""
    rows, _lib = _run(library, "--min-freq", "3")
    full = rows["秘密結社"]["Score"]
    _known(library, ["秘密", "結社"])
    rows, _lib = _run(library, "--min-freq", "3")
    assert rows["秘密結社"]["Score"] == full // 2


def test_without_the_token_store_the_list_is_the_same(library):
    """The store can be locked or damaged: the run then counts the library first and aggregates second — the same
    rare compounds, so the same list, never a silently different one."""
    import sqlite3
    _run(library, "--min-freq", "3")
    with_store = (library / "results" / "priority_learning_list.csv").read_bytes()
    (library / "results" / "priority_learning_list.csv").unlink()
    with patch("app.token_index.open_store", side_effect=sqlite3.OperationalError("database is locked")):
        _run(library, "--min-freq", "3")
    assert (library / "results" / "priority_learning_list.csv").read_bytes() == with_store


# --- 例文 and the sentence dictionary ----------------------------------------------------------------------------- #
def _collect(texts, known, library, wanted):
    """sentence_corpus.collect over `texts` as one file, the learner knowing the lemmas `known` -> {key: others of
    its best sentence}."""
    from app import sentence_corpus
    analyzer.SANITIZE_JA = True
    tokenizer = analyzer.JapaneseTokenizer()
    sentences = [(text, [list(t) for t in tokens]) for line in texts for text, tokens in tokenizer.tokenize_sentences(line)]
    words = sentence_corpus.collect(["f"], lambda path: sentences, "ja", (set(), set(known), set()),
                                    (1, 10 ** 9, 1, 10 ** 9), wanted=set(wanted), library=library)
    return {key: word.best.result()[0][0][0] for key, word in words.items()
            if word.best is not None and word.best.result()}


COMMON = {"の", "が", "を", "出場", "為る", "た", "訪れる", "開く", "れる"}
PLAYER, CHANCE, MEETING = ("選手", "センシュ"), ("好機", "コウキ"), ("会合", "カイゴウ")
TRANS, ONCE = ("トランスジェンダー", "トランスジェンダー"), ("千載一遇", "センザイイチグウ")


def test_the_dictionary_counts_a_sentence_in_the_lists_units(compounds):
    """Before the first Generate (no counts) トランスジェンダー is one unknown beside 選手; once the list says it is
    rare, it is two (トランス, ジェンダー) — and 千載一遇, rare with bound halves, stays one beside 好機."""
    texts = ["トランスジェンダーの選手が出場した。", "千載一遇の好機が訪れた。"]
    before = _collect(texts, COMMON, None, {PLAYER, CHANCE})
    assert before[PLAYER] == 1 and before[CHANCE] == 1
    after = _collect(texts, COMMON, ({TRANS: 2, ONCE: 1}, 3), {PLAYER, CHANCE})
    assert after[PLAYER] == 2 and after[CHANCE] == 1


def test_a_rare_compound_keeps_its_own_sentences_and_its_parts_get_none(compounds):
    """A card mined as a rare compound keeps its 例文, ranked with its own parts never counted against it; the parts
    it counts toward take no sentence from it (examples only where a word stands on its own)."""
    found = _collect(["トランスジェンダーの選手が出場した。"], COMMON, ({TRANS: 2}, 3),
                     {TRANS, ("トランス", "トランス"), ("ジェンダー", "ジェンダー")})
    assert found == {TRANS: 1}                         # 選手 is its one unknown; トランス / ジェンダー have none


def test_a_compound_of_known_parts_is_no_unknown_in_the_dictionary(compounds):
    """秘密結社 with 秘密 and 結社 known is read already: 会合's sentence has nothing else to learn."""
    texts = ["秘密結社の会合が開かれた。"]
    assert _collect(texts, COMMON, None, {MEETING})[MEETING] == 1
    assert _collect(texts, COMMON | {"秘密", "結社"}, None, {MEETING})[MEETING] == 0


# --- the Rarity slider ------------------------------------------------------------------------------------------- #
# The library is 100-odd tokens: these floors put the bands at 2, 3, 4 … uses.
BANDS_PPM = {"core": 60000, "common": 45000, "occasional": 30000, "uncommon": 20000, "rare": 12000,
             "very_rare": 6000, "native": 1}


def test_the_slider_keeps_only_the_parts_a_use_can_reach_the_list_through(compounds):
    """token_index.unknown_distribution, the slider's input: a bound part (前言) and a known one (トランス) are
    dropped; a one-kanji dictionary word (期) is kept, as the list keeps it (a one-character part the list can never
    offer is dropped); a compound part (経済成長 — never met alone, 0 uses) is kept with its own parts, so a band can
    take it apart in turn. At a floor of 3 撤回 reaches the list; at 2 前言撤回 itself is listed and gives nothing."""
    from app import token_index
    counts = {("前言撤回", "ゼンゲンテッカイ"): 2, ("撤回", "テッカイ"): 1, ("トランスジェンダー", "トランスジェンダー"): 2,
              ("経済成長期", "ケイザイセイチョウキ"): 1, ("経済", "ケイザイ"): 2}
    freqs = token_index.unknown_distribution(counts, 8, known_lemmas={"トランス"}, skip_singles=True, language="ja")
    uses, parts, bases = freqs["compounds"]
    assert parts[("前言撤回", "ゼンゲンテッカイ")] == (("撤回", "テッカイ", True),)
    assert parts[("トランスジェンダー", "トランスジェンダー")] == (("ジェンダー", "ジェンダー", True),)
    assert parts[("経済成長期", "ケイザイセイチョウキ")] == (("経済成長", "ケイザイセイチョウ", True), ("期", "キ", True))
    assert uses[("経済成長", "ケイザイセイチョウ")] == 0
    assert bases["撤回|テッカイ"] == 1 and bases["経済|ケイザイ"] == 2
    given = word_selection._given_back(freqs["compounds"], (2, 3))
    assert given[3] == {"撤回|テッカイ": 2, "ジェンダー|ジェンダー": 2, "経済|ケイザイ": 1, "成長|セイチョウ": 1,
                        "期|キ": 1}
    assert "撤回|テッカイ" not in given[2]
    # one band alone gives what the sweep gives it
    assert word_selection._given_back(freqs["compounds"], (3,))[3] == given[3]
    assert "compounds" not in token_index.unknown_distribution(counts, 8, language="zh")


def test_the_band_preview_counts_the_list_generate_writes_at_every_band(library):
    """The slider's "N words" for each band is the length of the list Generate writes at that band — rare compounds
    counted toward their parts on both sides (token_index.unknown_distribution + word_selection.preview). Without
    that the two disagree here, as they did (the preview counted the tokenizer's words)."""
    from app import settings_manager, token_index
    root = library
    counted = {}
    for band in word_selection.BANDS_ORDER:
        (root / "settings.json").write_text(json.dumps({"logic": {"selection": {
            "band": band, "bands_ppm": BANDS_PPM, "min_count": 2}}}), encoding="utf-8")
        analyzer.LOGIC["selection"] = settings_manager.load_settings()["logic"]["selection"]
        rows, lib = _run(root)
        counted[band] = (len(rows), lib["settings"]["min_count"])
    store = token_index.open_store("ja")
    try:
        freqs = token_index.preview_frequencies(store, "ja", str(root / "User Files" / "ja"))
    finally:
        store.close()
    previews = word_selection.band_previews(freqs, BANDS_PPM, 2)
    assert {band: p["word_count"] for band, p in previews.items()} == {band: n for band, (n, _f) in counted.items()}
    assert len({floor for _n, floor in counted.values()}) >= 3, counted          # a real ladder
    plain = word_selection.band_previews({k: v for k, v in freqs.items() if k != "compounds"}, BANDS_PPM, 2)
    assert any(plain[band]["word_count"] != counted[band][0] for band in counted), "give-back is exercised"
