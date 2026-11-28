"""TOP-UP (3.0.21, Sonic § 114: A + B, "We should be able to mine from them"): the episodes Connect already mined get
the words that join the list later — by themselves when the list grows (a rarity change, new content, a re-Generate),
and at once on *Mine the new words* (an episode's ⋯, its show's).

Why: from 3.0.18 (Kantan-MO) a raise mined no episode again, so a word met only in mined episodes never got a card — a
tester widened his rarity and his mined episodes sat at 15–42 *new* each with no way to mine them.

What each test holds (what a wrong answer costs: a second card for a word, an existing card touched, a move to Rare
mining hundreds of episodes past the cap, a word never carded):
  * a raise names, for each mined episode still ahead (soonest first), only its newly listed words no card Connect made
    holds — never an unmined, watched or taken-out episode — ja and zh;
  * the job is the cap's (no ask) and *Mine only pre-studied*'s, kept by the runner and the inbox, placed in the cap's
    window by its own words;
  * the press names the same words by the same rule (no card holds them, Connect never made them; read against the
    whole list), carries its time (first, past the cap), joins a waiting top-up, and the inbox never un-asks it;
  * the whole flow: an episode mined → the list grows → Connect's own look → the runner makes cards for only the new
    words, the old cards untouched, no word carded twice.

The suite's real subtitles in a store built from folders; real Japanese and Chinese words; no Anki, no network.
"""
import os

import pytest

from app.connect import actions, inbox, level, library, runner
from app.connect.ledger import LEVEL, Ledger
from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.connect.fake_steps import FakeSteps

# The list before and after a raise: (Word, Reading), the pick's identity — real words of each language
WORDS = {
    "ja": ({("冒険", "ボウケン"), ("散歩", "サンポ"), ("図書館", "トショカン")},
           {("眼鏡", "メガネ"), ("老婆", "ロウバ"), ("駐車場", "チュウシャジョウ")}),
    "zh": ({("冒险", "mào xiǎn"), ("散步", "sàn bù"), ("图书馆", "tú shū guǎn")},
           {("眼镜", "yǎn jìng"), ("老太婆", "lǎo tài pó"), ("停车场", "tíng chē chǎng")}),
}


def _lists(lang):
    before, added = WORDS[lang]
    return before, before | added, sorted(added)


def _line(lang="ja", n=3):
    """A library whose top `n` episodes are the mine line -> [(item id, file name)], in order."""
    c.library(lang)
    with c.store(lang) as s:
        s.bookkeeping({"mine_line": n}, copy_carries=True)
        return [(i, os.path.basename(s.item(i)["rel_path"])) for i in library.mine_line(s)]


def _mine(lang, *item_ids):
    with c.store(lang) as s:
        for item_id in item_ids:
            s.receipt(item_id, "2026-10-07T09:00:00Z")


def _check(lang, listed, signature, file_words):
    with c.store(lang) as s:
        return level.check(s, lang, listed, signature, file_words)


def _made(lang, item_id, *words):
    """Connect's made-words record: `words` carded from `item_id` (as `library.record_batch` writes it)."""
    from app import library_store
    with c.store(lang) as s, s._writing():
        for sql in library_store.ADDED_TABLES_SQL:
            s.conn.execute(sql)
        for n, word in enumerate(words):
            s.conn.execute("INSERT INTO made_words (item_id, word, note_ids, made_at, batch) VALUES (?, ?, ?, ?, ?)",
                           (item_id, word, f"[{1789712000001 + n}]", "2026-10-06T10:00:00Z", "job-7"))


def _level_jobs(lang="ja"):
    with Ledger() as ledger:
        return [ledger.job_by_id(j["id"]) for j in ledger.jobs(lang) if j["kind"] == LEVEL]


# --- A: the list grows, the mined episodes are topped up by themselves ------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_raise_tops_up_each_mined_episode_ahead_with_only_its_new_words(lang):
    # why: the tester's case — mined episodes, then a wider rarity: each gets the words that joined the list, soonest
    # first; an episode never mined gets nothing here (its first mining reads the list as it is now)
    before, raised, added = _lists(lang)
    (a, fa), (b, fb), (d, fd) = _line(lang)
    _mine(lang, a, d)
    old = sorted(before)[0][0]
    files = {fa: [added[0][0], old], fb: [added[1][0]], fd: [added[0][0], added[2][0], added[1][0]]}
    assert _check(lang, before, "run-1", files)["first"] is True
    out = _check(lang, raised, "run-2", files)
    assert out["queued"] == [a, d], "the mined ones, in the line's order — b was never mined"
    ja, jd = sorted(_level_jobs(lang), key=lambda j: j["id"])
    assert ja["source"] == jd["source"] == level.TOP_UP
    assert ja["words"] == [added[0]], "only its newly listed word: the word it was mined with stays out"
    assert jd["words"] == sorted([added[0], added[1], added[2]])
    assert not ja.get("asked_at") and not jd.get("asked_at"), "Connect's own: the cap holds it as a first mining"
    with c.store(lang) as s:
        assert ja["store_id"] == library.store_id(s) and ja["store_id"]


def test_a_word_connect_made_from_another_episode_or_show_is_never_named():
    # why: "a word mined from another episode or show counts as carded" — and a card you deleted is never made again
    # by itself (G1.3-4): the made-words record, any item
    before, raised, added = _lists("ja")
    (a, fa), (b, _fb), _d = _line()
    _mine("ja", a)
    _made("ja", b, added[0][0])
    _check("ja", before, "run-1", {fa: [w for w, _r in added]})
    _check("ja", raised, "run-2", {fa: [w for w, _r in added]})
    assert [j["words"] for j in _level_jobs()] == [added[1:]]


def test_watched_taken_out_and_never_mined_episodes_get_no_top_up():
    # why: 3.0's rule (LF4-1): no new cards on Connect's own from an episode you've watched, nor one taken out of the
    # learning order (D14) — their words go to the episodes ahead
    before, raised, added = _lists("ja")
    (a, fa), (b, fb), (d, fd) = _line()
    _mine("ja", a, b)
    with c.store() as s:
        s.set_watched([a])
        with s._writing():
            s.conn.execute("UPDATE items SET in_learning_order = 0 WHERE id = ?", (b,))
    files = {fa: [added[0][0]], fb: [added[0][0]], fd: [added[0][0]]}
    _check("ja", before, "run-1", files)
    assert _check("ja", raised, "run-2", files)["queued"] == [] and _level_jobs() == []


def test_a_mined_episode_past_the_top_20_is_topped_up_after_the_line():
    # why: soonest first — the line's episodes, then the rest of Current in order (`library.ahead`); an episode an
    # ask mined below the line is still yours to study
    before, raised, added = _lists("ja")
    _line(n=1)
    with c.store() as s:
        (a, fa), (b, fb) = [(i, os.path.basename(s.item(i)["rel_path"])) for i in library.ahead(s)[:2]]
    _mine("ja", b, a)
    files = {fa: [added[0][0]], fb: [added[1][0]]}
    _check("ja", before, "run-1", files)
    assert _check("ja", raised, "run-2", files)["queued"] == [a, b]
    assert sorted((j["item_id"], j["source"], j["words"]) for j in _level_jobs()) == sorted(
        [(a, level.TOP_UP, [added[0]]), (b, level.TOP_UP, [added[1]])]), "each its own new words, never the other's"


def test_the_same_list_again_and_a_lowered_level_queue_nothing():
    before, raised, added = _lists("ja")
    (a, fa), _b, _d = _line()
    _mine("ja", a)
    files = {fa: [w for w, _r in added]}
    _check("ja", raised, "run-1", files)
    assert _check("ja", raised, "run-1", files)["queued"] == []
    assert _check("ja", before, "run-2", files)["queued"] == [] and _level_jobs() == []


def test_a_mined_episode_with_a_job_open_gets_no_second_one():
    # why: one open job an item — a first mining not started reads the list as it is; an episode being mined keeps its
    # own pick
    before, raised, added = _lists("ja")
    (a, fa), _b, _d = _line()
    _mine("ja", a)
    _check("ja", before, "run-1", {fa: [added[0][0]]})
    with Ledger() as ledger:
        ledger.queue("ja", a, "user", None, store_id="s")
    assert _check("ja", raised, "run-2", {fa: [added[0][0]]})["queued"] == []


def test_the_cap_the_prestudied_switch_the_runner_and_the_inbox_treat_a_top_up_as_connects_own_pick():
    # why: "the same cap and order as a first mine" and "Mine only pre-studied episodes is honoured" — and a raise's
    # job from before 3.0.18 (source "level") is still dropped, never mistaken for a top-up
    job = {"kind": LEVEL, "source": level.TOP_UP, "words": [("眼鏡", "メガネ")]}
    assert runner.held_by_cap(job.get("asked_at")), "no ask: the cap's window holds it"
    assert runner.held_by_prestudy(job), "Connect's own pick: held until its episode is pre-studied"
    assert set(level.TOP_UPS) <= set(level.KEPT) and "level" not in level.KEPT
    assert inbox.keeps(job) and inbox.keeps(job, "left_mine_line")
    assert not inbox.keeps(job, "finished") and not inbox.keeps(job, "removed")
    pressed = dict(job, asked_at="2026-11-28T09:00:00.000000Z")
    assert not runner.held_by_cap(pressed["asked_at"]) and not runner.held_by_prestudy(pressed), "the press: a yes"


def test_by_leverage_a_top_up_is_placed_in_the_window_by_its_own_new_words(monkeypatch):
    # why: the cap's window places a job by the best word it would card; a top-up's episode holds words already
    # carded (made) and words it isn't asked for — only its new ones may lift it into the window
    steps = runner.Steps({}, live=False)
    monkeypatch.setattr(steps, "_file_words", lambda lang: {"ep.ja.srt": ["散歩", "眼鏡"]})

    class Store:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def item(self, item_id):
            return {"rel_path": "NOW/ep.ja.srt"}
    monkeypatch.setattr(steps, "_open", lambda lang: Store())
    monkeypatch.setattr(library, "made_words_all", lambda store: set())
    ranks = {"散歩": 1, "眼鏡": 40}
    job = {"id": 9, "item_id": 3, "kind": LEVEL, "source": level.TOP_UP, "words": [("眼鏡", "メガネ")]}
    assert steps._job_rank("ja", job, {}, lambda w, item: ranks.get(w, 10 ** 6)) == 40
    assert steps._job_rank("ja", dict(job, source=level.NEW_FILES), {}, lambda w, item: ranks.get(w, 10 ** 6)) == 1


# --- B: the press, *Mine the new words* ----------------------------------------------------------------------------- #
def _read(listed, files):
    return lambda lang: ("run-9", listed, files)


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_press_names_the_words_no_card_holds_and_connect_never_made_and_goes_first(lang):
    # why: B — "the press does the same at once": the automatic top-up's rule, read against the whole list (an
    # episode whose words joined in 3.0.18–3.0.20 had no top-up queued), carrying the press's time (first, past the
    # cap); a word Connect made is never named; an episode never mined is *Mine now*'s
    from app.connect.ledger import stamp, stamp_key
    before, raised, added = _lists(lang)
    (a, fa), (b, fb), (d, _fd) = _line(lang)
    _mine(lang, a)
    old = sorted(before)
    _made(lang, a, old[0][0])                       # its first mining carded one word
    _made(lang, d, added[2][0])                     # ... and another episode's mining another
    files = {fa: [old[0][0], old[1][0], added[0][0], added[2][0]], fb: [added[1][0]]}
    with Ledger():
        pass                                        # (the ledger exists, as once Connect ran)
    pressed = stamp()
    assert actions.top_up(lang, [a, b, a], read_list=_read(raised, files)) == [a]
    (job,) = _level_jobs(lang)
    assert job["source"] == level.TOP_UP_PRESS and stamp_key(job["asked_at"]) >= stamp_key(pressed), "the press's time"
    assert job["words"] == sorted([old[1], added[0]]), \
        "the listed words no card holds: never the one it carded, nor one carded from another episode"


def test_the_press_with_nothing_left_to_card_queues_nothing_and_no_list_is_no_press():
    before, raised, added = _lists("ja")
    (a, fa), _b, _d = _line()
    _mine("ja", a)
    _made("ja", a, added[0][0])
    with Ledger():
        pass
    assert actions.top_up("ja", [a], read_list=_read(raised, {fa: [added[0][0]]})) == []
    assert actions.top_up("ja", [a], read_list=lambda lang: None) == []
    assert _level_jobs() == []


def test_the_press_joins_a_waiting_top_up_and_the_inbox_never_un_asks_it():
    # why: the raise queued a top-up still waiting at the cap; your press makes it go now (one job, its words and the
    # press's time) — and with no ask of the store's behind it, the inbox's undo pass must never drop it
    before, raised, added = _lists("ja")
    (a, fa), _b, _d = _line()
    _mine("ja", a)
    files = {fa: [added[0][0], added[1][0]]}
    _check("ja", before, "run-1", {fa: [added[0][0]]})
    _check("ja", raised, "run-2", {fa: [added[0][0]]})
    (waiting,) = _level_jobs()
    assert actions.top_up("ja", [a], read_list=_read(raised, files)) == [a]
    (job,) = _level_jobs()
    assert job["id"] == waiting["id"] and job["asked_at"] and job["words"] == sorted(added[:2])
    with c.store() as s, Ledger() as ledger, ledger.transaction():
        dropped = []
        inbox._asks(s, "ja", ledger, {}, [], dropped, [], {})
    assert dropped == [] and _level_jobs()[0]["state"] == "queued"
    assert _level_jobs()[0]["asked_at"] == job["asked_at"], "the press's time kept: never un-asked"


def test_a_mine_again_undone_puts_a_waiting_automatic_top_up_back_in_its_place():
    # why: *Mine again* (a store ask) moves the episode's open job first — a waiting automatic top-up — and undone,
    # the inbox takes the ask back: the top-up waits for the cap again, never stuck first (only the press's own is kept)
    before, raised, added = _lists("ja")
    (a, fa), _b, _d = _line()
    _mine("ja", a)
    _check("ja", before, "run-1", {fa: [added[0][0]]})
    _check("ja", raised, "run-2", {fa: [added[0][0]]})
    (waiting,) = _level_jobs()
    with Ledger() as ledger, ledger.transaction():
        assert ledger.ask("ja", a, "2026-11-28T01:00:00Z", store_id="s") == ("moved", waiting["id"])
    with c.store() as s, Ledger() as ledger, ledger.transaction():
        dropped = []
        inbox._asks(s, "ja", ledger, {}, [], dropped, [], {})       # the store holds no ask for it any more
    (job,) = _level_jobs()
    assert dropped == [] and job["state"] == "queued" and job["asked_at"] is None
    assert job["source"] == level.TOP_UP


def test_a_raise_job_from_before_3_0_18_joined_by_a_top_up_becomes_the_top_up():
    # why: a level job of the old source (`level`) still waiting is dropped by the runner (`LEVEL_DROPPED`): a top-up
    # joining it must not lose its words with it
    before, raised, added = _lists("ja")
    (a, fa), _b, _d = _line()
    _mine("ja", a)
    with Ledger() as ledger, ledger.transaction():
        ledger.queue_level("ja", a, [added[1]], store_id="s")      # (the default source: a 3.0.17 raise's)
    _check("ja", before, "run-1", {fa: [added[0][0]]})
    assert _check("ja", raised, "run-2", {fa: [added[0][0]]})["queued"] == [a]
    (job,) = _level_jobs()
    assert job["source"] == level.TOP_UP and job["words"] == sorted(added[:2]) and job["asked_at"] is None


def test_a_new_files_job_the_press_joins_becomes_the_press_job():
    # why: an ask the inbox can't find in the store is undone — a press's time on a new-files job would be dropped
    # at the next look unless the job is the press's own (its source)
    before, raised, added = _lists("ja")
    (a, fa), _b, _d = _line()
    _mine("ja", a)
    with Ledger() as ledger, ledger.transaction():
        ledger.queue_level("ja", a, [added[0]], source=level.NEW_FILES, store_id="s")
    assert actions.top_up("ja", [a], read_list=_read(raised, {fa: [added[1][0]]})) == [a]
    (job,) = _level_jobs()
    assert job["source"] == level.TOP_UP_PRESS and job["asked_at"] and job["words"] == sorted(added[:2])


# --- the whole flow --------------------------------------------------------------------------------------------- #
def _last_generate(words, signature, file_words):
    """A last Generate's files, as test_level writes them: the list, its run stamp, its language, file_words.json."""
    import json
    results = os.path.join(h.root(), "results")
    os.makedirs(results, exist_ok=True)
    with open(os.path.join(results, "priority_learning_list.csv"), "w", encoding="utf-8-sig", newline="") as f:
        f.write("Word,Reading,Orth\n" + "".join(f"{w},{r},{w}\n" for w, r in sorted(words)))
    with open(os.path.join(results, "run_signature.txt"), "w", encoding="utf-8") as f:
        f.write(signature)
    with open(os.path.join(results, "library_frequency.json"), "w", encoding="utf-8") as f:
        json.dump({"settings": {"language": "ja"}}, f)
    with open(os.path.join(results, "file_words.json"), "w", encoding="utf-8") as f:
        json.dump(file_words, f, ensure_ascii=False)


def test_the_whole_flow_mine_then_widen_the_rarity_then_only_the_new_words_get_cards(tmp_path):
    # why: the learner's flow end to end — an episode mined, the list widened (a re-Generate), Connect's own look
    # (the `connect` verb, as the window starts it) queues its top-up, the runner makes cards for the new words only:
    # the cards it made first are untouched and no word gets a second card
    before, raised, added = _lists("ja")
    (a, fa), _b, _d = _line()
    first = sorted(before)
    with c.store() as s:
        store_id = library.store_id(s)          # a job is mined only into the library it was queued from
    plan = {"queue": {"ja": [a]}, "line": {"ja": [a]}, "store_id": store_id, "queued_store": store_id,
            "words": {str(a): [list(k) for k in first]}}
    steps = FakeSteps(str(tmp_path), plan)
    with Ledger() as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    notes_before = steps.anki.notes()
    assert sorted(steps.anki.words()) == sorted(w for w, _r in first), "the first mining"
    files = {fa: [w for w, _r in first] + [added[0][0], added[1][0]]}
    _last_generate(before, "run-1", files)
    code, line = h.call("connect", "--consume-only")
    assert code == 0 and line["languages"]["ja"]["level"]["first"] is True, line
    _last_generate(raised, "run-2", files)
    code, line = h.call("connect", "--consume-only")
    assert code == 0 and line["languages"]["ja"]["level"]["queued"] == [a], line
    steps = FakeSteps(str(tmp_path), dict(plan, queue={}))
    with Ledger() as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    words = steps.anki.words()
    assert sorted(words) == sorted([w for w, _r in first] + [added[0][0], added[1][0]])
    assert len(words) == len(set(words)), "never a second card for a word"
    after = steps.anki.notes()
    assert all(after[n] == note for n, note in notes_before.items()), "the first cards untouched"
    (job,) = _level_jobs()
    assert job["state"] == "done" and job["source"] == level.TOP_UP, job
    # the row's numbers move as it lands: its new words recorded for the episode (the store's made words — the
    # row's card count, `cards_of`, and the ✓ chip's cards left read them; a level batch moves the store's version
    # so the window reads them again: test_fix_l33_level_batch_moves_state), no receipt written again
    assert [(i, sorted(m), receipt) for i, m, receipt in steps.records] == [
        (a, sorted([added[0][0], added[1][0]]), False)]
