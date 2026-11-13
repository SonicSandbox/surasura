"""A tester's field report on 3.0.0 (item 5): book parts Anki Miner failed on could not be mined again, every
press refused, and the journey still listed their words as unmined. Sonic's rule: nothing is silently refused — a
failed part is offered again (*Try again*), and the words count only what's really on cards.

The cause, two halves:
- **Why they failed:** Anki refused one note of a part's batch (AnkiConnect's *cannot create note …*: Anki Miner's
  MINING_FAILED, not transient), so the whole batch failed. 3.0.0 sent the same words again, the same refusal came back,
  and the part ended `failed` (`runner._fail_mining`) with none of its words made — the ones Anki would take too. Now,
  after Anki refused a batch, the next sends each word alone (`runner._mine_batch`): the others get their cards, and the
  failure line names the words Anki refused with Anki's own reason.
- **Why no press worked:** the failed job was finished, so Connect's record (open jobs only) forgot it; the row read *N
  in Anki* (cards made) or *No cards in Anki … cards you deleted aren't made again* (none made), and every *Mine* skips
  a file in Anki or one whose cards were deleted (*Nothing to ask for*). Now Connect's record names each item whose
  newest job failed (`status`'s `failed`), the feed gives it a FAILED stone, and its row reads *Try again*, a button.

What a wrong answer would cost: a learner whose parts Anki stumbled on can never get those words onto cards — the
words stay listed as unmined, every press says there is nothing to do; one bad card costing a part all its others;
or a part offered *Try again* that has no failure, or one whose new try is already under way.

Against `FakeSteps` (Anki Miner stops mid-batch: `crash_mid_batch` + `crash_always`; Anki refuses a word's note:
`refuse_words`) and a real ledger read by the real status record and feed; real Japanese words. Never a live Anki, no
sleeps.
"""
import os

import pytest

from app.connect import feed, runner, status
from app.connect.ledger import Ledger, _now
from app.services import view_rows
from tests.connect.fake_steps import FakeSteps

WORDS = [("上層部", "じょうそうぶ"), ("一生懸命", "いっしょうけんめい"), ("気配", "けはい")]


def _failed_part(tmp_path, made_first=1):
    """Part 1 of a book, mined by Connect: Anki Miner stops on its batch twice, each time after `made_first` cards
    (so 1 → two of its three words made, 0 → none)."""
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "words": {"1": WORDS},
            "crash_mid_batch": made_first, "crash_always": True}
    steps = FakeSteps(str(tmp_path), plan)
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        assert [j["state"] for j in ledger.jobs("ja")] == ["failed"], "why: the part must fail, or this proves nothing"
    return steps, path


def _record(path):
    return status.read(languages=["ja"], path=path)


def _in_anki(n):
    return view_rows.Status("in_anki", str(n), view_rows.STRINGS["tip_in_anki"].format(n=n), "ok")


DELETED = view_rows.Status("deleted", view_rows.STRINGS["deleted"], view_rows.STRINGS["tip_deleted"], "faint")


def test_a_part_anki_miner_failed_on_is_named_in_connects_record_with_what_it_made(tmp_path):
    _steps, path = _failed_part(tmp_path)
    rec = _record(path)["languages"]["ja"]
    assert [(f["item"], f["made"], f["words"]) for f in rec["failed"]] == [(1, 2, 3)], rec.get("failed")
    assert rec["failed"][0]["reason"] == runner.MINE_FAILED


def test_its_row_offers_try_again_over_its_cards_in_anki(tmp_path):
    """Two cards made, one never: the row's ✓2 would hide the word still unmined — *Try again* says it."""
    _steps, path = _failed_part(tmp_path)
    item = feed.build(_record(path), "ja").items[1]
    assert item.kind == feed.FAILED and (item.made, item.total) == (2, 3)
    st = view_rows._connected(_in_anki(2), item, "book")
    assert st.kind == "retry" and st.tone == "warn"
    assert st.label == view_rows.STRINGS["retry"]
    assert st.tip == view_rows.STRINGS["tip_retry"].format(tip=runner.MINE_FAILED, k=2, n=3)


def test_a_part_that_made_no_card_is_try_again_never_cards_you_deleted(tmp_path):
    """None made: its receipt with no card read as *cards you deleted aren't made again* — a lie, and no way on."""
    _steps, path = _failed_part(tmp_path, made_first=0)
    item = feed.build(_record(path), "ja").items[1]
    assert item.kind == feed.FAILED and (item.made, item.total) == (0, 3)
    st = view_rows._connected(DELETED, item, "book")
    assert st.kind == "retry"
    assert st.tip == view_rows.STRINGS["tip_retry_none"].format(tip=runner.MINE_FAILED)


def test_a_books_row_reads_try_again_from_its_failed_part_though_the_part_has_cards(tmp_path):
    """The book's closed row: its failed part has a card, so the row's own rule (never an episode in Anki: a level
    job on a mined one is no reason to turn the row) passed it by. A failed one is no such episode."""
    _steps, path = _failed_part(tmp_path)
    connect = feed.build(_record(path), "ja").items
    from types import SimpleNamespace
    eps = [SimpleNamespace(id=7, cards=4, deleted=False, online=None),      # part 7: mined, its cards in Anki
           SimpleNamespace(id=1, cards=2, deleted=False, online=None)]      # part 1: the failed one
    st = view_rows._row_connected(view_rows.Status("mine_rest", "2/3 · Mine rest", "", "ok"), eps, connect, "book")
    assert st.kind == "retry"


def test_a_new_try_under_way_or_one_that_went_through_is_no_failure_any_more(tmp_path):
    """*Try again* pressed: the store's ask makes an asked job (no open job holds the item), which mines the words
    the part's cards don't hold yet — never the one already made. While it is queued its own stone shows (Asked);
    once done, no FAILED stone, and the part's *Needs you* entry is fixed by itself."""
    steps, path = _failed_part(tmp_path)
    steps.plan.update(crash_mid_batch=None, crash_always=False, queue={})
    with Ledger(path) as ledger, ledger.transaction():
        assert ledger.ask("ja", 1, _now(), store_id="store-1")[0] == "queued"
    assert _record(path)["languages"]["ja"]["failed"] == [], "an open job holds the item: no failure named"
    item = feed.build(_record(path), "ja").items[1]
    assert item.kind == feed.ASKED, "the new try's own stone, never the old failure's"
    with Ledger(path) as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        assert [j["state"] for j in ledger.jobs("ja")] == ["failed", "done"]
        assert not [n for n in ledger.needs("ja") if n["kind"] in runner.FAILED_KINDS], "fixed once the part went through"
    mined = [e for e in steps.log if e[0] == "mine"]
    assert mined[-1][3] == [WORDS[2][0]], "only the word not on a card yet"
    assert sorted(steps.anki.words()) == sorted(w for w, _r in WORDS), "every word on a card, each once"
    rec = _record(path)["languages"]["ja"]
    assert rec["failed"] == [] and 1 not in feed.build(_record(path), "ja").items


def test_a_try_that_fails_again_is_named_again_though_you_dismissed_the_first(tmp_path):
    """Every press reacts: a second failure is a new entry that counts in the badge, never the first one's dismissal
    hiding it — and the row is *Try again* again."""
    steps, path = _failed_part(tmp_path)
    with Ledger(path) as ledger:
        first = [n for n in ledger.needs("ja") if n["kind"] in runner.FAILED_KINDS]
        assert len(first) == 1
    status.dismiss(first[0]["id"], path=path)
    with Ledger(path) as ledger, ledger.transaction():
        ledger.ask("ja", 1, _now(), store_id="store-1")
    steps.plan.update(queue={}, crash_mid_batch=0)      # Anki Miner stops on its first word now: none made
    with Ledger(path) as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        assert [j["state"] for j in ledger.jobs("ja")] == ["failed", "failed"]
        listed = [n for n in ledger.needs("ja") if n["kind"] in runner.FAILED_KINDS]
        assert len(listed) == 1 and listed[0]["id"] != first[0]["id"] and not listed[0].get("seen_at")
    rec = _record(path)["languages"]["ja"]
    assert rec["unseen"] == 1
    assert feed.build(_record(path), "ja").items[1].kind == feed.FAILED


def test_the_needs_entry_says_try_again_makes_the_rest():
    assert "Try again" in runner.MINE_FAILED_SAY.format(title="葬送のフリーレン 第3章")


def test_a_level_job_after_a_failure_keeps_the_failure_named(tmp_path):
    """A level raise mines only an item's newly listed words: done, it says nothing of the words the failed job never
    made, so the part stays *Try again*."""
    steps, path = _failed_part(tmp_path)
    steps.plan.update(crash_mid_batch=None, crash_always=False, queue={},
                      level=[("ja", 1, [["溜め息", "ためいき"]])])
    with Ledger(path) as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        assert [(j["kind"], j["state"]) for j in ledger.jobs("ja")] == [("mine", "failed"), ("level", "done")]
    assert feed.build(_record(path), "ja").items[1].kind == feed.FAILED


def test_an_empty_ledger_names_no_failure(tmp_path):
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path):
        pass
    assert _record(path)["languages"]["ja"]["failed"] == []
    assert not os.path.exists(str(tmp_path / "none.sqlite"))
    assert "failed" in _record(str(tmp_path / "none.sqlite"))["languages"]["ja"]


# --- the cause in the field: Anki refused one note, and the batch held every word with it --------------------------- #
def _refused_part(tmp_path, refuse, words=WORDS):
    """Part 1, mined by Connect; Anki refuses the notes of `refuse` (AnkiConnect's *cannot create note …*: a batch that
    holds one fails whole, Anki Miner's MINING_FAILED, not transient)."""
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "words": {"1": words}, "refuse_words": list(refuse)}
    steps = FakeSteps(str(tmp_path), plan)
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    return steps, path


def test_one_card_anki_refuses_never_holds_back_the_parts_other_words(tmp_path):
    """3.0.0 sent the same three words twice and gave the part up with none made. Now, after Anki refused the batch,
    the next one sends each word alone: the two Anki takes get their cards, the one it refuses keeps the part
    *Try again*, named with Anki's own words."""
    steps, path = _refused_part(tmp_path, {WORDS[1][0]})
    sent = [e[3] for e in steps.log if e[0] == "mine"]
    assert sent[0] == [w for w, _r in WORDS], "the first batch: the part's words together, as always"
    assert sent[1:] == [[WORDS[0][0]], [WORDS[1][0]], [WORDS[2][0]]], "then a word at a time"
    assert sorted(steps.anki.words()) == sorted([WORDS[0][0], WORDS[2][0]])
    with Ledger(path) as ledger:
        assert [j["state"] for j in ledger.jobs("ja")] == ["failed"]
        say = [n["say"] for n in ledger.needs("ja") if n["kind"] in runner.FAILED_KINDS]
    assert len(say) == 1 and WORDS[1][0] in say[0] and "cannot create note for unknown reason" in say[0]
    assert WORDS[0][0] not in say[0] and "Skip this word" in say[0] and "Try again" not in say[0]   # (AUDIT B5)
    item = feed.build(_record(path), "ja").items[1]
    assert item.kind == feed.FAILED and (item.made, item.total) == (2, 3)


def test_a_part_whose_only_word_anki_refuses_is_named_with_it(tmp_path):
    """One word, refused (as in the field): nothing to split — two tries, then *Try again* naming it."""
    steps, path = _refused_part(tmp_path, {WORDS[0][0]}, words=WORDS[:1])
    assert [e[3] for e in steps.log if e[0] == "mine"] == [[WORDS[0][0]], [WORDS[0][0]]]
    with Ledger(path) as ledger:
        say = [n["say"] for n in ledger.needs("ja") if n["kind"] in runner.FAILED_KINDS]
    assert len(say) == 1 and WORDS[0][0] in say[0]
    assert feed.build(_record(path), "ja").items[1].kind == feed.FAILED


def test_a_crash_is_no_refusal_its_retry_goes_whole(tmp_path):
    """Anki Miner stopping (a crash, a timeout) says nothing of a card: the retry sends the words together, as before
    (a word at a time costs a run each)."""
    steps, _path = _failed_part(tmp_path)
    sent = [e[3] for e in steps.log if e[0] == "mine"]
    assert len(sent) == 2 and len(sent[1]) == 2, sent


def test_a_refused_batch_then_taken_whole_part_is_done(tmp_path):
    """Anki refused the batch once and then took every card alone: the part is done, nothing to try again."""
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "words": {"1": WORDS}, "refuse_words": [WORDS[1][0]]}
    steps = FakeSteps(str(tmp_path), plan)
    path = str(tmp_path / "ledger.sqlite")
    original = steps.mine

    def once(lang, job, picked, words, attempt):        # Anki takes it the second time (its trouble went away)
        got = original(lang, job, picked, words, attempt)
        steps.plan["refuse_words"] = []
        return got
    steps.mine = once
    with Ledger(path) as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        assert [j["state"] for j in ledger.jobs("ja")] == ["done"]
    assert sorted(steps.anki.words()) == sorted(w for w, _r in WORDS)
    assert _record(path)["languages"]["ja"]["failed"] == []


# --- Steps' reading of Anki Miner's run verdict (`_mine_one`) -------------------------------------------------------- #
@pytest.mark.parametrize("run, error, said", [
    # Anki refused a note: MINING_FAILED, not transient — the field's answer (its run file written, the write in doubt)
    ({"run_id": "j-1", "ok": False, "error": "MINING_FAILED", "file": "result-1.json", "failure_is_transient": False,
      "message": "AnkiConnect error in 'addNotes': ['cannot create note for unknown reason']"}, None,
     "AnkiConnect error in 'addNotes': ['cannot create note for unknown reason']"),
    # a dropped connection: running again can get past it — no refusal of a card
    ({"run_id": "j-1", "ok": False, "error": "MINING_FAILED", "file": "result-1.json", "failure_is_transient": True,
      "message": "AnkiConnect connection reset"}, None, None),
    # Anki Miner crashed after writing its result: no answer of Anki's
    ({"run_id": "j-1", "ok": False, "error": "MINING_FAILED", "file": "result-1.json", "failure_is_transient": False,
      "message": "x"}, "crashed", None),
    ({"run_id": "j-1", "ok": True, "error": None, "file": "result-1.json"}, None, None),
])
def test_steps_tell_a_card_anki_refused_from_a_crash(monkeypatch, tmp_path, run, error, said):
    from app.cli import verbs
    from app.connect import anki_miner
    words = [{"word": w, "reading": r, "line_start": 1.0} for w, r in WORDS]
    done = {"run": run, "outcomes": [{"word": w["word"], "reading": w["reading"], "outcome": "uncertain"}
                                     for w in words], "app": "3.11.0"}
    if error:
        done["error"] = error
    monkeypatch.setattr(anki_miner, "find", lambda loaded: "AnkiMiner.exe")
    monkeypatch.setattr(verbs, "_anki_miner_setup", lambda *a, **k: (None, None, object()))
    monkeypatch.setattr(anki_miner, "mine_batch", lambda *a, **k: done)
    steps = runner.Steps({"connect_enabled": True})
    monkeypatch.setattr(steps, "_anki_miner_held", lambda lang: {})
    monkeypatch.setattr(steps, "run_dir", lambda job: str(tmp_path))
    monkeypatch.setattr(steps, "show", lambda lang, job: None)
    got = steps._mine_one("ja", {"id": 1, "item_id": 1, "tag": "t-1"}, {"video": "v", "subtitle": "s"}, words, 1)
    assert got["anki_said"] == said
    assert got["doubt"] is (not run["ok"] or bool(error))


def test_stop_between_two_words_alone_stops_there_its_cards_kept(tmp_path):
    """#47's Stop, a word at a time: pressed after one word's run, the next word isn't started; the card made is kept
    and the job waits for your *Mine now*, the rest unmade — your Stop is no failure of Anki's."""
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "words": {"1": WORDS}, "refuse_words": [WORDS[2][0]]}
    steps = FakeSteps(str(tmp_path), plan)
    path = str(tmp_path / "ledger.sqlite")
    original = steps.mine
    with Ledger(path) as ledger:
        def press_after_the_first_alone(lang, job, picked, words, attempt):
            got = original(lang, job, picked, words, attempt)
            if attempt == 2:                # the first word of the word-at-a-time batch
                ledger.ask_stop(job["id"])
            return got
        steps.mine = press_after_the_first_alone
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        job = ledger.jobs("ja")[0]
        assert (job["state"], job["reason"]) == ("waiting", runner.STOPPED_BY_YOU)
        assert (job["failures"] or 0) == 1, "only Anki's refusal of the whole batch counts"
    assert [e[3] for e in steps.log if e[0] == "mine"] == [[w for w, _r in WORDS], [WORDS[0][0]]]
    assert steps.anki.words() == [WORDS[0][0]]


# --- the adversary's round 1 (B1, N1–N3, N5) ------------------------------------------------------------------------- #
def test_a_wait_between_two_words_alone_is_a_wait_never_a_failure_blaming_anki(tmp_path):
    """B1: you start reviewing before the second word's run. The part waits (its card so far kept), no failure is
    counted for words never sent, and nothing names them as refused; later the part goes on a word at a time."""
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "words": {"1": WORDS}, "refuse_words": [WORDS[0][0]]}
    steps = FakeSteps(str(tmp_path), plan)
    path = str(tmp_path / "ledger.sqlite")
    original = steps.mine

    def review_before_the_second_word(lang, job, picked, words, attempt):
        if attempt == "2-1":
            raise runner.Wait(runner.REVIEWING)
        return original(lang, job, picked, words, attempt)
    steps.mine = review_before_the_second_word
    with Ledger(path) as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        job = ledger.jobs("ja")[0]
        assert (job["state"], job["reason"], job["resume"]) == ("waiting", runner.REVIEWING, "mining")
        assert (job["failures"] or 0) == 1, "only the whole batch Anki refused counts"
        assert not [n for n in ledger.needs("ja") if n["kind"] in runner.FAILED_KINDS]
    steps.mine = original                       # done reviewing: the next look goes on, a word at a time
    with Ledger(path) as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        assert [j["state"] for j in ledger.jobs("ja")] == ["failed"]
        say = [n["say"] for n in ledger.needs("ja") if n["kind"] in runner.FAILED_KINDS][0]
    assert sorted(steps.anki.words()) == sorted([WORDS[1][0], WORDS[2][0]])
    assert WORDS[0][0] in say and WORDS[1][0] not in say and WORDS[2][0] not in say


def test_every_word_is_tried_alone_though_the_first_ones_are_refused(tmp_path):
    """Review r2 B2: two bad cards first never cost the good ones after them — each word is tried (a deck or note
    type Anki Miner can't use is its setup check's, before every call); the line names the refused ones."""
    words = WORDS + [("溜め息", "ためいき"), ("約束", "やくそく")]
    steps, path = _refused_part(tmp_path, {WORDS[0][0], WORDS[1][0]}, words=words)
    assert [e[3] for e in steps.log if e[0] == "mine"][1:] == [[w] for w, _r in words]
    assert sorted(steps.anki.words()) == sorted(w for w, _r in words[2:])
    with Ledger(path) as ledger:
        say = [n["say"] for n in ledger.needs("ja") if n["kind"] in runner.FAILED_KINDS][0]
    assert f"{WORDS[0][0]}, {WORDS[1][0]} (" in say and words[2][0] not in say


def test_anki_closing_before_the_next_word_and_its_tag_check_is_a_wait_never_a_failure(tmp_path):
    """Review r2 B1: the word-at-a-time batch cut short by Anki closing (`then`), and the tag check after it meeting
    Anki gone too — still a wait: no failure for the words never sent, Anki's refusal of the first kept."""
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "words": {"1": WORDS}, "refuse_words": [WORDS[0][0]]}
    steps = FakeSteps(str(tmp_path), plan)
    path = str(tmp_path / "ledger.sqlite")
    mine, by_tag = steps.mine, steps.by_tag
    closed = {"now": False}

    def anki_closes_before_the_second_word(lang, job, picked, words, attempt):
        if attempt == "2-1":
            closed["now"] = True
            raise runner.Wait(runner.ANKI_CLOSED)
        return mine(lang, job, picked, words, attempt)

    def tag_check(lang, job, picked, words):
        if closed["now"]:
            raise runner.Wait(runner.ANKI_CLOSED)
        return by_tag(lang, job, picked, words)
    steps.mine, steps.by_tag = anki_closes_before_the_second_word, tag_check
    with Ledger(path) as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        job = ledger.jobs("ja")[0]
        assert (job["state"], job["resume"]) == ("waiting", "mining") and (job["failures"] or 0) == 1
        assert runner._alone(ledger, job["id"])["words"] == [WORDS[0][0]]
    closed["now"] = False
    steps.mine, steps.by_tag = mine, by_tag           # Anki open again: the next look goes on, a word at a time
    with Ledger(path) as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        assert [j["state"] for j in ledger.jobs("ja")] == ["failed"]
    assert sorted(steps.anki.words()) == sorted([WORDS[1][0], WORDS[2][0]])


def test_a_crash_then_a_refusal_never_names_words_anki_never_refused_alone(tmp_path):
    """N2: Anki Miner crashed first, then Anki refused the whole batch: no word was ever refused alone, so the line
    says Anki Miner stopped — it names no word as refused."""
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "words": {"1": WORDS}, "crash_mid_batch": 0}
    steps = FakeSteps(str(tmp_path), plan)
    original = steps.mine

    def refuse_after_the_crash(lang, job, picked, words, attempt):
        if attempt == 2:
            steps.plan["refuse_words"] = [WORDS[1][0]]
        return original(lang, job, picked, words, attempt)
    steps.mine = refuse_after_the_crash
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        assert [j["state"] for j in ledger.jobs("ja")] == ["failed"]
        say = [n["say"] for n in ledger.needs("ja") if n["kind"] in runner.FAILED_KINDS][0]
    assert say == runner.MINE_FAILED_SAY.format(title=steps.title("ja", {"item_id": 1}) or "An episode")


def test_the_failure_line_stays_through_a_level_raise(tmp_path):
    """N3: a level job's end fixes the item's needs — never the failed part's line, whose words it didn't try."""
    steps, path = _failed_part(tmp_path)
    steps.plan.update(crash_mid_batch=None, crash_always=False, queue={},
                      level=[("ja", 1, [["溜め息", "ためいき"]])])
    with Ledger(path) as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        assert [n["kind"] for n in ledger.needs("ja")] == ["mine-failed"]


def test_a_book_row_shows_a_later_part_mining_over_an_earlier_failed_one():
    """N5: the row keeps the mining part's progress and *Stop*; with none mining it is *Try again*."""
    from types import SimpleNamespace
    mining = feed.Item(kind=feed.MINING, words=feed.WORDS[feed.MINING], tip="", job=9, made=1, total=4)
    failed = feed.Item(kind=feed.FAILED, words=feed.WORDS[feed.FAILED], tip=runner.MINE_FAILED, job=4, made=0,
                       total=3)
    waiting = feed.Item(kind=feed.WAITING, words=feed.WORDS[feed.WAITING], tip="", job=5, made=0, total=2)
    eps = [SimpleNamespace(id=n, cards=0, deleted=n == 1, online=None) for n in (1, 2, 3)]
    plain = view_rows.Status("mine", "Mine", "", "ink")
    assert view_rows._row_connected(plain, eps, {1: failed, 3: mining}, "book").kind == "mining"
    assert view_rows._row_connected(plain, eps, {1: failed, 2: waiting}, "book").kind == "retry"
    assert view_rows._row_connected(plain, eps, {2: waiting, 3: mining}, "book").kind == "waiting", "as before"


def test_an_open_level_job_holds_the_item_its_stone_not_the_failure(tmp_path):
    """While a level raise's job is open on the failed part (queued, waiting), that job is the item's stone: the
    record names no failure until it has ended."""
    _steps, path = _failed_part(tmp_path)
    with Ledger(path) as ledger, ledger.transaction():
        ledger.queue_level("ja", 1, [("溜め息", "ためいき")], store_id="store-1")
    assert _record(path)["languages"]["ja"]["failed"] == []
    assert feed.build(_record(path), "ja").items[1].kind != feed.FAILED
