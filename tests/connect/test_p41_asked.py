"""Asked mining (P4.1 row 4.1.3; C2 / C3; IK S1, S3, S4): *Mine now*, *Mine this* and *Mine it too* are all the
store's `ask_mining`; Connect reads the asks at every inbox look (`library.asked`, `inbox.consume`) and the runner
mines a job carrying one first (`runner._ordered`), never dropping it for being out of the top 20 (`runner._job`,
`inbox.keeps`).

What a wrong answer would cost: these jobs write the user's Anki unattended. A *Mine this* below the line dropped as
"left the top 20" makes no card the user asked for; an ask mined twice makes every card twice; an ask made while
Connect was off mines the user's history (G1.1-2); *Mine now* bringing back a card the user deleted breaks G1.3-4
(N15: only *Mine this* / *Mine it too* may); an ask undone but still mined writes Anki against the user's undo; a
failed, skipped or not-timed asked job that is queued again at every look loops on Anki for ever (IK S4).

Real subtitles (the suite's own) in a store built from folders; real Japanese words; Anki and Anki Miner are
`FakeSteps`' stand-ins (a JSON file of notes) — never a live Anki.
"""
import os

import pytest

from app.connect import inbox, library, runner
from app.connect.ledger import ASKED, Ledger, stamp
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.connect.fake_steps import FakeSteps

# Real words each episode's pick finds, by place (the test's own item ids are mapped onto them)
WORDS = [[("上層部", "ジョウソウブ"), ("一生懸命", "イッショウケンメイ")],
         [("一生懸命", "イッショウケンメイ"), ("気配", "ケハイ")],
         [("約束", "ヤクソク"), ("勇気", "ユウキ")],
         [("溜め息", "タメイキ"), ("走り出す", "ハシリダス")]]


class StoreSteps(FakeSteps):
    """FakeSteps over the real store and the real inbox: the top 20, the asks, the receipts and the made words are
    the library's own; only Anki and Anki Miner are stand-ins. The pick counts as carded what the real pick does:
    Anki's cards and `library.made_words_for` (every word Connect made, or for an asked job only those whose card
    the store still holds)."""

    _open = runner.Steps._open
    text_only = runner.Steps.text_only

    def __init__(self, folder, lang="ja", plan=None):
        super().__init__(folder, plan)
        self.lang = lang

    def consume(self, lang, ledger):
        with c.store(lang) as s:
            inbox.consume(s, lang, ledger)

    def mine_line(self, lang):
        with c.store(lang) as s:
            return library.mine_line(s)

    def store_id(self, lang):
        with c.store(lang) as s:
            return library.store_id(s)

    def record(self, lang, job, made, mined_at, batch):
        super().record(lang, job, made, mined_at, batch)
        with c.store(lang) as s:
            library.record_batch(s, job["item_id"], made, mined_at, batch)

    def _carded(self):
        return set(self.anki.words()) | getattr(self, "_made", set())

    def pick(self, lang, job, video):
        with c.store(lang) as s:
            self._made = library.made_words_for(s, job)
        return super().pick(lang, job, video)


def _library(lang="ja", line=2):
    """The suite's real files in NOW, the top `line` mined by Connect; Connect's first look made (its watermarks)."""
    c.library(lang)
    with c.store(lang) as s:
        s.bookkeeping({"mine_line": line}, copy_carries=True)
        ids = s.ids("now")
        kinds = {i: os.path.splitext(s.item(i)["rel_path"])[1] for i in ids}
    _look(lang)
    return ids, kinds


def _look(lang="ja"):
    with c.store(lang) as s, Ledger() as ledger:
        return inbox.consume(s, lang, ledger)


def _ask(item_ids, lang="ja"):
    with c.store(lang) as s:
        return s.ask_mining(list(item_ids))


def _steps(tmp_path, words, lang="ja", **plan):
    return StoreSteps(str(tmp_path), lang, dict(plan, words={str(i): w for i, w in words.items()}))


def _run(steps, lang="ja", looks=1):
    with Ledger() as ledger:
        return runner.run({}, [lang], steps=steps, ledger=ledger, sleep=lambda s: None, looks=looks)


def _jobs(item_id=None, lang="ja"):
    with Ledger() as ledger:
        return [j for j in ledger.jobs(lang) if item_id is None or j["item_id"] == item_id]


def _mined(steps):
    """The items Anki Miner was called for, in order."""
    return [e[1] for e in steps.log if e[0] == "mine"]


def _place_top(item_id, lang="ja"):
    """A drag to the top of NOW: the item enters the top 20 (an `entered_mine_line` event -> a `mine` job)."""
    with c.store(lang) as s:
        top = s.ids("now")[0]
        library.place(s, item_id, "now", before_id=top, source="user")


def _srt(ids, kinds):
    return [i for i in ids if kinds[i] == ".srt"]


def test_an_ask_below_the_line_is_a_job_never_dropped_and_mined_first(tmp_path):
    ids, kinds = _library()
    episodes = _srt(ids, kinds)
    below, placed = episodes[-1], episodes[-2]
    _place_top(placed)                                  # a top-20 job, queued first
    _ask([below])                                       # *Mine this* below the line, after it
    got = _look()
    assert got["asked"] == [below] and below in got["queued"]
    job = _jobs(below)[0]
    assert (job["kind"], job["source"], job["state"]) == (ASKED, "user", "queued") and job["asked_at"]
    steps = _steps(tmp_path, {below: WORDS[2], placed: WORDS[3]})
    out = _run(steps)
    with c.store() as s:
        assert below not in library.mine_line(s), "it never entered the top 20"
    assert _mined(steps) == [below, placed], "the asked job first, though it is out of the line"
    assert sorted(out["languages"]["ja"]["done"]) == sorted([below, placed])
    assert _jobs(below)[0]["state"] == "done", "never dropped as 'left the top 20'"
    assert set(steps.anki.words()) == {"約束", "勇気", "溜め息", "走り出す"}


def test_mine_now_on_a_waiting_top_job_moves_that_job_next_and_makes_no_second(tmp_path):
    ids, kinds = _library()
    a, b = _srt(ids, kinds)[-2:]
    _place_top(b)
    _place_top(a)                                       # a above b: a would go first
    _look()
    steps = _steps(tmp_path, {a: WORDS[2], b: WORDS[3]}, blocked=runner.ANKI_CLOSED)
    _run(steps)                                         # Anki closed: both wait
    assert {j["item_id"]: j["state"] for j in _jobs()} == {a: "waiting", b: "waiting"}
    _ask([b])                                           # *Mine now* on b (its hover names the wait: it doesn't jump it)
    assert _look()["queued"] == [], "the ask moved b's own job: no second one"
    jobs = _jobs(b)
    assert len(jobs) == 1 and jobs[0]["kind"] == "mine" and jobs[0]["asked_at"]
    steps.plan["blocked"] = None
    _run(steps)
    assert _mined(steps) == [b, a], "b goes next, then the line's order"


def _mine_first(tmp_path, item_id, words):
    """The item mined once by Connect (its receipt and made words in the store), then every card it made deleted in
    Anki and the store told (the run's deleted-card check, `library.notes_gone`)."""
    _place_top(item_id)
    _look()
    steps = _steps(tmp_path, {item_id: words})
    _run(steps)
    assert _jobs(item_id)[0]["state"] == "done"
    notes = steps.anki.notes()
    data = steps.anki._load()
    data["notes"] = {}
    steps.anki._save(data)                              # deleted by the user in Anki
    with c.store() as s:
        assert library.notes_gone(s, set(notes)) == sorted(notes)
    return steps


def test_an_ask_on_a_mined_item_whose_cards_were_deleted_makes_them_again_only_for_that_job(tmp_path):
    ids, kinds = _library()
    a, b = _srt(ids, kinds)[-2:]
    steps = _mine_first(tmp_path, a, WORDS[0])          # 上層部, 一生懸命 made, then deleted
    _place_top(b)                                       # b holds 一生懸命 too: an ordinary job
    _look()
    steps.plan["words"] = {str(a): WORDS[0], str(b): WORDS[1]}
    steps.log.clear()
    _run(steps)
    assert [e[3] for e in steps.log if e[0] == "mine"] == [["気配"]], \
        "G1.3-4: a word whose card was deleted is never made again by an ordinary job"
    _ask([a])                                           # *Mine this* on the mined episode
    _look()
    assert [j["kind"] for j in _jobs(a)] == ["mine", ASKED], "a mined item's ask is a job of its own"
    steps.log.clear()
    _run(steps)
    assert [e[3] for e in steps.log if e[0] == "mine"] == [["上層部", "一生懸命"]], \
        "N15: the job the ask made makes the deleted cards again"
    assert _jobs(a)[-1]["state"] == "done"


def test_mine_now_on_a_waiting_job_never_makes_a_deleted_card_again(tmp_path):
    """IK S1: *Mine now* only moves a job first — 一生懸命, deleted from the other episode, stays deleted."""
    ids, kinds = _library()
    a, b = _srt(ids, kinds)[-2:]
    steps = _mine_first(tmp_path, a, WORDS[0])
    _place_top(b)
    _look()
    steps.plan.update(words={str(b): WORDS[1]}, blocked=runner.REVIEWING)
    _run(steps)
    assert _jobs(b)[0]["state"] == "waiting"
    _ask([b])                                           # *Mine now*
    _look()
    steps.plan["blocked"] = None
    steps.log.clear()
    _run(steps)
    assert [e[3] for e in steps.log if e[0] == "mine"] == [["気配"]]
    assert "一生懸命" not in steps.anki.words()


@pytest.mark.parametrize("ending", ["failed", "skipped", "not-timed"])
def test_an_asked_job_that_ends_without_cards_uses_the_ask_up(tmp_path, ending):
    """IK S4: any ending uses the ask up — no second job at the next looks, though no receipt answers it."""
    ids, kinds = _library()
    below = _srt(ids, kinds)[-1]
    plan = {"failed": {"crash_mid_batch": 0, "crash_always": True}, "skipped": {"absent": ["anki-miner"]},
            "not-timed": {"verdict": "not_timed"}}[ending]
    steps = _steps(tmp_path, {below: WORDS[2]}, **plan)
    _ask([below])
    _run(steps)
    state = _jobs(below)[0]["state"]
    assert state == {"failed": "failed", "skipped": "skipped", "not-timed": "waiting"}[ending]
    for _ in range(2):
        _run(steps)
        assert _look()["queued"] == []
    assert len(_jobs(below)) == 1, "one job for one ask, however it ended"
    with c.store() as s:
        assert inbox.pending(s) is False, "nothing left for Connect to read"


def test_an_asked_book_ends_skipped_with_k67s_line_and_the_ask_used_up(tmp_path):
    """IK S3 (defensive: the window sends *Mine this* on a book to Anki Miner's own window, no ask): a job asked for a
    text item ends skipped, never picked, never waiting for a video it can't have."""
    ids, kinds = _library()
    text = [i for i in ids if kinds[i] == ".txt"][-1]
    steps = _steps(tmp_path, {text: WORDS[2]})
    _ask([text])
    _run(steps)
    job = _jobs(text)[-1]
    assert (job["kind"], job["state"], job["reason"]) == (ASKED, "skipped", runner.TEXT_ONLY)
    assert ("pick", text) not in steps.log and steps.anki.words() == []
    _run(steps)
    assert len(_jobs(text)) == 1, "the ask used up: no second job"


def test_asks_made_while_connect_was_off_are_never_mined(tmp_path):
    ids, kinds = _library()
    early, late = _srt(ids, kinds)[-2:]
    _ask([early])                                       # while Connect is off …
    with Ledger() as ledger, ledger.transaction():
        ledger.set_asks_from("ja", stamp())             # … switched on (`resume.turned_on` writes the watermark)
    assert _look()["asked"] == [], "asked before the watermark: history"
    _ask([late])
    assert _look()["asked"] == [late]
    steps = _steps(tmp_path, {early: WORDS[2], late: WORDS[3]})
    _run(steps)
    assert _mined(steps) == [late] and _jobs(early) == []


def test_the_first_look_that_reads_asks_mines_none_made_before_it(tmp_path):
    """A ledger without an asks watermark (one before P4.1): the first look sets it, as the placement reader is set at
    the first look — nothing asked before Connect read asks is mined (G1.1-2)."""
    c.library()
    with c.store() as s:
        s.bookkeeping({"mine_line": 2}, copy_carries=True)
        below = s.ids("now")[-1]
        s.ask_mining([below])
    assert _look()["asked"] == []
    with Ledger() as ledger:
        assert ledger.asks_from("ja") is not None
    assert _jobs() == []


def test_an_ask_undone_before_mining_drops_its_job_and_mine_now_undone_puts_it_back(tmp_path):
    ids, kinds = _library()
    a, below = _srt(ids, kinds)[-2:]
    _place_top(a)
    _look()
    with c.store() as s:
        asked_below = s.ask_mining([below])             # *Mine this*
        asked_a = s.ask_mining([a])                     # *Mine now* on a's waiting job
    _look()
    assert _jobs(below)[0]["kind"] == ASKED and _jobs(a)[0]["asked_at"]
    with c.store() as s:
        s.undo(asked_below)                             # the window's undo (the store's command)
        s.undo(asked_a)
    got = _look()
    assert got["dropped"] == [below]
    dropped = _jobs(below)[0]
    assert (dropped["state"], dropped["reason"]) == ("dropped", "left: ask undone")
    back = _jobs(a)[0]
    assert (back["state"], back["asked_at"]) == ("queued", None), "an ask that only moved a job: the job stays"
    steps = _steps(tmp_path, {a: WORDS[2], below: WORDS[3]})
    _run(steps)
    assert _mined(steps) == [a], "nothing mined for the undone ask"


class _Unreadable:
    """A store connection whose read fails (locked, damaged): what `asks_in` meets on a bad moment."""

    def execute(self, *args):
        import sqlite3
        raise sqlite3.OperationalError("database is locked")


def test_asks_that_cant_be_read_change_nothing_never_read_as_every_ask_undone(monkeypatch):
    # why (adversary AD-6): an unreadable asks read once read as "no asks" -> every asked job dropped as undone, and
    # the ask, held by that dropped job, never mined again; now it reads as unknown and the look leaves the jobs be
    assert library.asks_in(_Unreadable()) is None
    ids, kinds = _library()
    below = _srt(ids, kinds)[-1]
    _ask([below])
    assert _look()["asked"] == [below]
    monkeypatch.setattr(library, "asks", lambda store: library.asks_in(_Unreadable()))
    got = _look()
    assert got["dropped"] == [] and got["asked"] == []
    job = _jobs(below)[0]
    assert (job["state"], job["kind"]) == ("queued", ASKED) and job["asked_at"]
    with c.store() as s:
        assert inbox.pending(s) is False, "an unreadable read is nothing unread, never an error"


def test_an_ask_undone_once_its_mining_started_leaves_the_job_to_finish():
    # why (mutant M04): an asked job waiting mid-mining (its resume step past the pick) finishes (02 §2) — the undo
    # neither drops it nor counts it dropped
    ids, kinds = _library()
    below = _srt(ids, kinds)[-1]
    with c.store() as s:
        asked = s.ask_mining([below])
    _look()
    job = _jobs(below)[0]
    with Ledger() as ledger:
        ledger.set_state(job["id"], "waiting", resume="mining")
    with c.store() as s:
        s.undo(asked)
    got = _look()
    assert got["dropped"] == []
    after = _jobs(below)[0]
    assert (after["state"], after["resume"], after["asked_at"]) == ("waiting", "mining", job["asked_at"])


def test_a_mined_ask_is_answered_by_its_receipt_and_a_second_look_queues_nothing(tmp_path):
    ids, kinds = _library()
    below = _srt(ids, kinds)[-1]
    _ask([below])
    steps = _steps(tmp_path, {below: WORDS[2]})
    _run(steps)
    with c.store() as s:
        assert s.item(below)["mined_at"], "its receipt"
        # the receipt answers it — or, mined within the ask's own second (Connect's receipts count whole seconds),
        # the ledger's job holding it does
        assert library.asked(s) == [] or _jobs(below)[0]["asked_at"] == library.asked(s)[0][1]
        assert inbox.pending(s) is False
    assert _look()["queued"] == []
    _run(steps)
    assert len(_jobs(below)) == 1 and _mined(steps) == [below]


def test_a_receipt_at_or_after_the_ask_answers_it():
    """C3: `record_batch`'s `mined_at` at or after `mine_asked` answers the ask (Connect's seconds against the store's
    microseconds): a lost ledger never mines an answered ask again."""
    found = {1: ("2026-10-15T09:00:00.250000Z", "2026-10-15T09:00:01Z"),      # mined after: answered
             2: ("2026-10-15T09:00:00.000000Z", "2026-10-15T09:00:00Z"),      # the same instant: answered
             3: ("2026-10-15T09:00:02.000000Z", "2026-10-15T09:00:01Z"),      # mined before the ask: open
             4: ("2026-10-15T09:00:03.000000Z", None)}                        # never mined: open
    assert library.unanswered(found) == [(4, "2026-10-15T09:00:03.000000Z"), (3, "2026-10-15T09:00:02.000000Z")]


def test_connect_off_queues_nothing_for_an_ask(tmp_path):
    ids, kinds = _library()
    below = _srt(ids, kinds)[-1]
    _ask([below])
    steps = _steps(tmp_path, {below: WORDS[2]}, switched_off=True)
    out = _run(steps)
    assert out.get("stopped") == runner.SWITCHED_OFF
    assert _jobs(below) == [] and steps.anki.words() == []


def test_a_chinese_ask_waits_for_chinese_cards(tmp_path):
    _library("zh")
    with c.store("zh") as s:
        below = s.ids("now")[-1]
    _ask([below], "zh")
    steps = _steps(tmp_path, {}, lang="zh")
    out = _run(steps, "zh")
    job = _jobs(below, "zh")[0]
    assert (job["kind"], job["state"], job["reason"]) == (ASKED, "waiting", runner.CHINESE)
    assert out["languages"]["zh"]["waiting"] == {below: runner.CHINESE} and steps.anki.words() == []


def test_an_unread_ask_is_pending_until_the_inbox_takes_it():
    """`inbox.pending` (Connect's exit look, the register verb's kick) sees an ask the inbox hasn't taken."""
    ids, kinds = _library()
    below = _srt(ids, kinds)[-1]
    with c.store() as s:
        assert inbox.pending(s) is False
    _ask([below])
    with c.store() as s:
        assert inbox.pending(s) is True
    _look()
    with c.store() as s:
        assert inbox.pending(s) is False


def test_an_ask_kept_through_a_gap_in_the_log():
    """A gap reconciles the jobs out of the top 20 — never one carrying an ask (only a removed item drops it)."""
    ids, kinds = _library()
    below = _srt(ids, kinds)[-1]
    _ask([below])
    _look()
    with c.store() as s, Ledger() as ledger:
        s.read_events = lambda reader: ([], True)        # the log pruned past Connect's watermark
        got = inbox.consume(s, "ja", ledger)
    assert got["reconciled"] and got["dropped"] == []
    assert _jobs(below)[0]["state"] == "queued"


def test_the_real_pick_hands_an_asked_job_only_the_words_whose_cards_are_kept(tmp_path, monkeypatch):
    """`Steps.pick` -> `verbs.pick`'s `made`: every word Connect made for a `mine` job, only those whose card the
    store still holds for an `asked` one (N15) — the real step, its Anki Miner pick stood in for."""
    from app.cli import verbs
    ids, kinds = _library()
    a = _srt(ids, kinds)[-1]
    with c.store() as s:
        library.record_batch(s, a, {"上層部": [111], "一生懸命": [112]}, "2026-10-15T09:00:00Z")
        library.notes_gone(s, {112})                    # 一生懸命's card deleted in Anki
    seen = []
    monkeypatch.setattr(verbs, "pick", lambda ns: seen.append(set(ns.made)) or {"words": []})
    steps = runner.Steps({})
    monkeypatch.setattr(steps, "_plan_now", lambda lang: None)
    steps.pick("ja", {"id": 1, "item_id": a, "kind": "mine"}, "/videos/a.mkv")
    steps.pick("ja", {"id": 2, "item_id": a, "kind": ASKED}, "/videos/a.mkv")
    assert seen == [{"上層部", "一生懸命"}, {"上層部"}]
