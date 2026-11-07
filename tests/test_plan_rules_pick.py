"""The shared pick's own rules (F7: app/plan_rules.py), unit by unit — the analyzer's and the plan engine's one
implementation: the order-free keepers (`keep_best`, `offer_spread` / `shortlist`) give the same shortlist whatever
order the candidates come in, at most PER_FILE a file unless the spread can't fill it, each text once in the uncapped
part; and `ContextPicker` breaks ties after the quality keys as Sonic asked — Finished (or watched) first, the most
recent first, then the sentences reusing what was just learned, then the file nearest the word's first meeting.

What a wrong answer would cost a learner: sentences that move when the order moves (the shortlist must not), a common
word's examples all from one episode, a song line said in every episode filling the shortlist, or a far sentence shown
where an equally easy one from the next episode was there. Real Japanese lines (tests/Test Resources/ja), no library.
"""
import random

from app import plan_rules as pr

LINES = ["灯台の光が見えた。", "夜の灯台は静かだった。", "白い灯台が海の近くにある。", "古い灯台が丘の上に立っている。",
         "灯台守は毎晩明かりをともした。", "遠くの灯台がかすかに光る。", "嵐の夜も灯台は消えなかった。",
         "灯台までの道は長かった。", "朝の灯台はとても白い。", "子どもたちは灯台を見に行った。"]


def _ctx(text, src, short=0, long=0, cost=0, unknowns=1):
    """A candidate shaped as the analyzer keeps one: (short, long, cost, lrs, text, src, marks, key, number, None)."""
    key = pr.order_free_key(short, long, cost, unknowns, text, f"file{src}.txt")
    return (short, long, cost, frozenset(), text, src, (), key, 0, None)


def _shortlist(candidates, size, per_file):
    spread, best = [], []
    for c in candidates:
        pr.offer_spread(spread, best, c, size, 7, 5, 4, per_file)
    return pr.shortlist(spread, best, size, 7, 4)


def test_the_shortlist_is_the_same_whatever_order_its_candidates_come_in():
    # why: a move must never change which sentences a word can show — only the pick follows the order
    rng = random.Random(7)
    candidates = [_ctx(f"{rng.choice(LINES)}{i}", rng.randrange(6), cost=rng.randrange(3), unknowns=rng.randrange(4))
                  for i in range(200)]
    want = [c[7] for c in _shortlist(candidates, 12, 2)]
    for _ in range(30):
        rng.shuffle(candidates)
        assert [c[7] for c in _shortlist(candidates, 12, 2)] == want


def test_a_file_gives_the_spread_at_most_per_file_and_the_rest_only_to_fill():
    # why: a very common word's examples come from many files; a word met in one file still keeps every good one
    # file 0 holds the 5 easiest sentences; files 1-7 one harder sentence each
    many = [_ctx(f"{LINES[i]}", 0) for i in range(5)] + [_ctx(f"{LINES[i]}!", i, cost=1) for i in range(1, 8)]
    shortlist = _shortlist(many, 8, 2)
    assert len(shortlist) == 8
    assert sum(1 for c in shortlist if c[5] == 0) == 2, "the spread: 2 of file 0's, never more, then the others"
    one_file = [_ctx(f"{LINES[i]}", 0) for i in range(10)]
    assert len(_shortlist(one_file, 8, 2)) == 8, "one file, ten sentences: the shortlist still fills"


def test_a_line_said_in_every_file_takes_one_place_in_the_uncapped_part():
    # why: a show's song line in 24 episodes filled 24 of 60 places; each text is kept once there, its best copy
    song = [_ctx("灯台の歌が聞こえる。", f) for f in range(24)]
    others = [_ctx(LINES[i % 10] + str(i), 30 + i, cost=1) for i in range(40)]   # (harder: the song leads)
    best = []
    for c in song + others:
        pr.keep_best(best, c, 20, 7, 5, 20, 4)
    texts = [c[4] for c in best]
    assert texts.count("灯台の歌が聞こえる。") == 1
    assert min(c[7] for c in song) in [c[7] for c in best], "its best copy (the same in any order)"
    assert len(pr.shortlist([], best, 20, 7, 4)) == 20


def _picker(rows, place, recency=1):
    """A picker over sentence rows (pr.TEXT … pr.CHARS) with no co-word, all of one kind of file."""
    return pr.ContextPicker(rows, [], 3, place, lambda src: 2, recency_files=recency)


def _row(text, src):
    return (text, None, 0, 0, src, (), (), 0, pr.text_hash_of(text), len(text))


def test_among_equally_easy_sentences_finished_comes_first_then_the_nearest_file():
    # why: Sonic, 2026-11-06 — "finished would be more valuable. Then recent"; then the episodes right after the word
    rows = [_row("灯台を見た。", 1), _row(LINES[1], 9), _row(LINES[2], 2), _row(LINES[3], 100), _row(LINES[4], 50)]
    place = {1: (pr.NOT_FINISHED, 1), 9: (pr.NOT_FINISHED, 9), 2: (pr.NOT_FINISHED, 2), 100: (0, 0),
             50: (3, 0)}.__getitem__
    chosen = _picker(rows, place).pick(row=7, seq=1, first=0, pool=[1, 2, 3, 4])
    assert chosen == [0, 3, 4], "Context 1 the first sentence; then Finished, the most recent (rank 0) first"
    chosen = _picker(rows[:3], place).pick(row=7, seq=1, first=0, pool=[1, 2])
    assert chosen == [0, 2, 1], "with no Finished line: the nearest file after the first meeting (2 before 9)"


def test_recency_breaks_a_tie_after_finished_and_before_the_nearest_file():
    # why: recency stays a tiebreak — never above Finished, always above a mere nearer file
    rows = [_row("灯台を見た。", 1), _row(LINES[1], 2), _row(LINES[2], 5)]
    cowords = [(3, ((3,),))]                                       # co-word 0: row 3's word, learned in file 4
    rows[2] = rows[2][:pr.COWORDS] + ((0,),) + rows[2][pr.COWORDS + 1:]
    picker = pr.ContextPicker(rows, cowords, 3, lambda src: (pr.NOT_FINISHED, src), lambda src: 2, recency_files=1)
    picker.learn(3, False, 4)
    assert picker.pick(row=7, seq=5, first=0, pool=[1, 2]) == [0, 2, 1], "the sentence reusing a word just learned"
    # a Finished line with no recent word still goes before the one reusing a word just learned
    place = {1: (pr.NOT_FINISHED, 1), 2: (0, 0), 5: (pr.NOT_FINISHED, 5)}.__getitem__
    picker = pr.ContextPicker(rows, cowords, 3, place, lambda src: 2, recency_files=1)
    picker.learn(3, False, 4)
    assert picker.pick(row=7, seq=5, first=0, pool=[1, 2]) == [0, 1, 2], "Finished first, recency only after it"
