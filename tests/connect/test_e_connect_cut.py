"""The cut takes the score's line (the sentence choice, release 1; SPEC § 11, overlap 78; the lead's ruling, 2026-11-23):
at `plan_rules.SENTENCE_TABLE` >= 1 the cut (`pick.pick`) is handed the score's lines of each word inside the file it
cuts (`sentences.lines_in`, through `verbs.pick`'s `ranked`), best first, and takes the first one it can make. It keeps
its own refusals (sung, inside tsubasa's undetermined spans, Swap's old card's line) and its own rule after them, or
for a word the score holds no line of there; "a line no other word took" stays ahead of the score's order
(PROVISIONAL). Level 0: the cut as today.

What each test holds — the shapes the DevTest drill traced (drill 1, 2026-11-23): the mined episode's card has the
score's line there, not the cut's own earliest (友達 / られる); another episode a word is cut from, and a book, the same
(とく / スマホ / ソロ: `verbs.pick` asks for the file it cuts, `_borrow`'s and the level job's too); a word the score
holds no line of in the file keeps the cut's own rule (メタル); a refused line hands the card to the score's next;
two words never share a line; level 0, no table, a failing ask: the cut's own line.

Real subtitles written into the sandbox's data folder (the score's table over them in SPEC § 3.3's shape, as
`tests/connect/test_e_connect_score.py`), lines as `tests/Test Resources/ja|zh` write them; the cut reads them with
the cue reader and the tokenizer, as a mine does.
"""
import inspect
from types import SimpleNamespace

import pytest

from app import analyzer, cues, plan_rules
from app.cli import verbs
from app.connect import pick, sentences
from tests.connect.test_e_connect_score import World
from tests.test_sentence_score import FESTIVAL, NIGHT, PREPARE, SIGN

FEST = ("文化祭", "ブンカサイ")         # the cut's own key for the word (the tokenizer's reading)
MARKET = ("夜市", "")
SHORT_ZH = "夜市好热闹。"                                 # 6 characters: under the Length's 14
SHOP_ZH = "我们在夜市买了很多好吃的小吃。"                   # 15
CASES = [("ja", FEST, "文化祭", SIGN, FESTIVAL, PREPARE), ("zh", MARKET, "夜市", SHORT_ZH, NIGHT, SHOP_ZH)]


@pytest.fixture(autouse=True)
def _no_young(monkeypatch):
    monkeypatch.setattr(sentences, "young_weights", lambda language: {})


def _world(monkeypatch, lang, key, word, episodes, level=1):
    analyzer.SANITIZE_JA = lang == "ja"
    w = World(monkeypatch, lang, level=level)
    w.table(key, episodes, word)
    for n, (name, _lines) in enumerate(episodes, 1):
        w.place(name, n, ctx=0.2)
    return w


def _verbs_pick(monkeypatch, w, lang, name, new, **ns):
    """`verbs.pick` on one sandbox episode, the words in `new` unknown — the cut as a mine runs it (no video: no run
    file) -> {word: its line's text}."""
    monkeypatch.setattr(verbs, "settings", lambda: dict(w.settings, target_language=lang))
    monkeypatch.setattr(verbs, "require_set_up", lambda language: None)
    monkeypatch.setattr(verbs, "_known_test", lambda *a: (lambda k: k[0] not in new))
    monkeypatch.setattr(pick, "carded", lambda *a, **k: (set(), "anki"))
    out = verbs.pick(SimpleNamespace(**dict(dict(lang=lang, file=w.path(name), video=None, words="unknown", job="c1",
                                                 wait=0.0, made=set(), listed={}, reading=None), **ns)))
    return {x["word"]: x["line_text"] for x in out["words"]}


def _cut(w, lang, name, new, ranked=True, **kw):
    """`pick.pick` on one episode with the score's lines of its file (`ranked`) -> the chosen words."""
    path = w.path(name)
    read = cues.read(path, lang)
    tokens = cues.tokens(read, lang)
    asked = (lambda keys: sentences.lines_in(lang, keys, path, young={})) if ranked is True else ranked
    return pick.pick(read, tokens, lang, lambda k: k[0] not in new, mode="unknown", **_ranked(asked), **kw)


def _ranked(asked):
    # (the code before has no `ranked`: there the cut runs as it did, so a red is the choice's, not the call's)
    return {"ranked": asked} if "ranked" in inspect.signature(pick.pick).parameters else {}


@pytest.mark.parametrize("lang, key, word, first, best, other", CASES)
def test_the_mined_episodes_card_has_the_scores_line_not_the_cuts_own_earliest(monkeypatch, lang, key, word, first,
                                                                              best, other):
    # why: drill 1's 友達 / られる — the score's first line was in the mined episode, the card had another line of it
    # (the cut's own rule: the earliest of equals). The score chooses the line; the cut only refuses
    w = _world(monkeypatch, lang, key, word, [("ep01", [first, best])])
    assert _verbs_pick(monkeypatch, w, lang, "ep01", {word}) == {word: best}
    assert sentences.lines_in(lang, [key], w.path("ep01"), young={})[key] == [best, first]
    # level 0: the cut as today (its earliest of equals), the score never asked
    monkeypatch.setattr(plan_rules, "SENTENCE_TABLE", 0)
    assert sentences.lines_in(lang, [key], w.path("ep01")) is None
    assert _verbs_pick(monkeypatch, w, lang, "ep01", {word}) == {word: first}


@pytest.mark.parametrize("lang, key, word, first, best, other", CASES)
def test_another_episode_a_word_is_cut_from_gives_the_scores_line_there(monkeypatch, lang, key, word, first, best,
                                                                       other):
    # why: drill 1's とく / スマホ — Best moved the word to the score's episode, and `_borrow`'s pick there (`Steps.pick`
    # with `only`) cut that episode's own earliest line, not the score's. `verbs.pick` asks for the file it cuts
    w = _world(monkeypatch, lang, key, word, [("ep01", [other]), ("ep02", [first, best])])
    assert _verbs_pick(monkeypatch, w, lang, "ep02", {word}, only=[key], aside="from-1") == {word: best}


def test_verbs_pick_hands_the_cut_the_scores_lines_of_the_file_it_cuts(monkeypatch, tmp_path):
    # why: one door for every cut — the mined episode, another episode's (`only`), a book's (`reading`): the score is
    # asked for the words the cut may send, inside the file it reads, at the moment's young words
    subtitle = tmp_path / "話1.srt"
    subtitle.write_text("1\n00:00:01,000 --> 00:00:02,500\n約束だよ\n", encoding="utf-8")
    monkeypatch.setattr(verbs, "settings", lambda: {"target_language": "ja"})
    monkeypatch.setattr(verbs, "require_set_up", lambda lang: None)
    monkeypatch.setattr(verbs, "_listed", lambda args, lang: {("約束", "ヤクソク"): 0})
    monkeypatch.setattr(verbs, "_level_job", lambda job, lang: None)
    monkeypatch.setattr(verbs, "_connect_folder", lambda: str(tmp_path / "connect"))
    monkeypatch.setattr(pick, "carded", lambda *a, **k: (set(), "anki"))
    monkeypatch.setattr(sentences, "young_weights", lambda language: {"約束": 0.5})
    asked = []
    monkeypatch.setattr(sentences, "lines_in", lambda *a, **k: asked.append((a, k)) or {})
    got = []

    def choose(*a, **kw):
        got.append(kw["ranked"]([("約束", "ヤクソク")]))
        return {"words": [], "not_offered": []}
    monkeypatch.setattr(pick, "pick", choose)
    base = dict(lang="ja", file=str(subtitle), video=None, words="list", job="8", wait=0.0)
    for ns in (SimpleNamespace(**base), SimpleNamespace(**base, only=[("約束", "ヤクソク")], aside="from-3")):
        verbs.pick(ns)
    assert got == [{}, {}]
    assert asked == [(("ja", [("約束", "ヤクソク")], str(subtitle)), {"young": {"約束": 0.5}})] * 2


@pytest.mark.parametrize("lang, key, word, first, best, other", CASES)
def test_a_word_the_score_holds_no_line_of_in_the_file_keeps_the_cuts_own_rule(monkeypatch, lang, key, word, first,
                                                                               best, other):
    # why: drill 1's メタル — the episode says the word only where the Generate counted it otherwise (inside
    # デスメタル): the score has no line of it there, so the cut's own rule, never no card
    w = _world(monkeypatch, lang, key, word, [("ep01", [other]), ("ep02", [first, best])])
    assert sentences.lines_in(lang, [key], w.path("ep02"), young={})[key] == [best, first]
    chosen = _cut(w, lang, "ep02", {word}, ranked=lambda keys: {})
    assert [x["line_text"] for x in chosen["words"]] == [first]
    chosen = _cut(w, lang, "ep02", {word}, ranked=lambda keys: {key: [other]})   # the score's line is elsewhere
    assert [x["line_text"] for x in chosen["words"]] == [first]


@pytest.mark.parametrize("lang, key, word, first, best, other", CASES)
def test_a_line_the_cut_refuses_hands_the_card_to_the_scores_next(monkeypatch, lang, key, word, first, best, other):
    # why: the cut keeps its refusals — Swap's old card's line, a line inside tsubasa's undetermined span, a sung
    # line — and takes the score's next line, not its own earliest
    lines = [first, other, best]
    w = _world(monkeypatch, lang, key, word, [("ep01", lines)])
    order = sentences.lines_in(lang, [key], w.path("ep01"), young={})[key]
    top, second = order[0], order[1]
    assert sorted(order) == sorted(lines) and first not in (top, second), "the cut's own earliest is the score's last"
    assert [x["line_text"] for x in _cut(w, lang, "ep01", {word})["words"]] == [top]
    assert [x["line_text"] for x in _cut(w, lang, "ep01", {word}, never={key: {top}})["words"]] == [second]
    at = 1 + lines.index(top)                               # its cue's start (the table's subtitles: n s)
    assert [x["line_text"] for x in _cut(w, lang, "ep01", {word}, unsure=[(at - 0.5, at + 0.5)])["words"]] == [second]
    # the score's only line refused: the cut's own rule (its earliest) takes the rest
    assert [x["line_text"] for x in _cut(w, lang, "ep01", {word}, ranked=lambda keys: {key: [top]},
                                         never={key: {top}})["words"]] == [first]
    # a sung line (a song's mark: a Generate leaves it out, so only a line inside it can point there): never cut
    w = _world(monkeypatch, lang, key, word, [("ep02", [first, f"♪{top}♪"])])
    assert [x["line_text"] for x in _cut(w, lang, "ep02", {word}, ranked=lambda keys: {key: [top]})["words"]] \
        == [first]


def test_two_words_never_share_a_line_the_second_takes_its_scores_next():
    # why: "a line no other word took" stays ahead of the score's order (no two cards share a sentence: PROVISIONAL)
    import os
    root = os.environ["SURASURA_TEST_ROOT"]
    path = os.path.join(root, "two.srt")
    lines = ["文化祭の看板は私が描くね。", "文化祭の準備、手伝ってくれない？看板も。", "文化祭まで、あと三日しかないよ。"]
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        for n, text in enumerate(lines, 1):
            f.write(f"{n}\n00:00:{n * 4:02d},000 --> 00:00:{n * 4 + 2:02d},000\n{text}\n\n")
    analyzer.SANITIZE_JA = True
    read = cues.read(path, "ja")
    tokens = cues.tokens(read, "ja")
    sign = ("看板", "カンバン")
    score = {FEST: [lines[1], lines[2]], sign: [lines[1], lines[0]]}
    chosen = pick.pick(read, tokens, "ja", lambda k: k[0] not in {"文化祭", "看板"}, mode="unknown",
                       **_ranked(lambda keys: {k: score[k] for k in keys if k in score}))
    got = {x["word"]: x["line_text"] for x in chosen["words"]}
    assert got == {"文化祭": lines[1], "看板": lines[0]}, "文化祭 first (met first), 看板 its score's next"


@pytest.mark.parametrize("lang, key, word, first, best, other", CASES)
def test_the_scores_order_first_and_at_one_place_its_own_line_before_one_holding_it(monkeypatch, lang, key, word,
                                                                                    first, best, other):
    # why: the token store may keep one cue as two sentences, so the score's line can be inside a cue (Swap's
    # `same_line`): the score's order first; where one of its lines is both a cue and inside another, the cue that is
    # that line
    w = _world(monkeypatch, lang, key, word, [("ep01", [best + first, first])])
    chosen = _cut(w, lang, "ep01", {word}, ranked=lambda keys: {key: [first]})
    assert [x["line_text"] for x in chosen["words"]] == [first]
    chosen = _cut(w, lang, "ep01", {word}, ranked=lambda keys: {key: [best, first]})
    assert [x["line_text"] for x in chosen["words"]] == [best + first], "the cue holding the score's first"


def test_a_book_cut_takes_the_scores_sentence(monkeypatch, tmp_path):
    # why: drill 1's ソロ — the book's level job cut its own first sentence of the word, not the score's: a book's
    # sentences are matched as the cut names them (`book_line`)
    analyzer.SANITIZE_JA = True
    book = tmp_path / "日記.txt"
    book.write_text("\n".join([SIGN, PREPARE, FESTIVAL]) + "\n", encoding="utf-8")
    read, tokens = cues.reading(str(book), "ja")
    asked = []

    def ranked(keys):
        asked.append(list(keys))
        return {FEST: [FESTIVAL, PREPARE]}
    chosen = pick.pick(read, tokens, "ja", lambda k: k[0] != "文化祭", mode="unknown", **_ranked(ranked),
                       sentence_length=(14, 25, 150))
    assert asked == [[FEST]] and [x["line_text"] for x in chosen["words"]] == [FESTIVAL]
    plain = pick.pick(read, tokens, "ja", lambda k: k[0] != "文化祭", mode="unknown", sentence_length=(14, 25, 150))
    assert [x["line_text"] for x in plain["words"]] == [PREPARE], "the cut's own rule: the first inside the Length"


def test_a_failing_ask_or_none_is_the_cuts_own_rule_and_swaps_own_line_is_never_asked(monkeypatch):
    # why: the score's path never makes a cut worse than today's; Swap's line is chosen already (the learner's, or
    # the score's at the press): the cut never asks again for it
    w = _world(monkeypatch, "ja", FEST, "文化祭", [("ep01", [SIGN, FESTIVAL])])

    def broken(keys):
        raise RuntimeError("a table damaged inside its blocks")
    for ranked in (broken, lambda keys: None, None):
        assert [x["line_text"] for x in _cut(w, "ja", "ep01", {"文化祭"}, ranked=ranked)["words"]] == [SIGN]
    asked = []
    swap = {"word": "文化祭", "reading": "", "avoid": [], "line": SIGN}
    chosen = _cut(w, "ja", "ep01", {"文化祭"}, ranked=lambda keys: asked.append(keys) or {FEST: [FESTIVAL]}, swap=swap)
    assert asked == [] and [x["line_text"] for x in chosen["words"]] == [SIGN]
    swap = dict(swap, line=None)                                # Swap with no line: any line, the score's first
    chosen = _cut(w, "ja", "ep01", {"文化祭"}, swap=swap)
    assert [x["line_text"] for x in chosen["words"]] == [FESTIVAL]


def test_lines_in_is_none_at_level_zero_with_no_table_or_a_failure_and_empty_for_no_words(monkeypatch):
    w = _world(monkeypatch, "zh", MARKET, "夜市", [("ep01", [SHORT_ZH, NIGHT])])
    path = w.path("ep01")
    assert sentences.lines_in("zh", [], path) == {}
    assert sentences.lines_in("zh", [MARKET], None) is None
    from app import sentence_score as SS
    monkeypatch.setattr(SS, "_table", lambda language: None)
    assert sentences.lines_in("zh", [MARKET], path, young={}) is None
    monkeypatch.setattr(sentences, "_scored", lambda *a, **k: 1 / 0)
    assert sentences.lines_in("zh", [MARKET], path, young={}) is None
