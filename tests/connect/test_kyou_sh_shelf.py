"""Kyou-SH (a tester's report, 2026-11-20; Sonic's go on plan v2 the same day): Connect never suspends a card by
itself, the cap counts only the cards still on your list, and the cards already set aside are said.

A tester had *Suspend them* off in 順 and found 236 of the cards Connect made suspended and tagged `surasura::shelf`:
at the card cap the shelf (P2.4-1) set aside the lowest-ranked waiting cards, and nothing he could see said so. The
count it made room against held his own mined cards too, so the shelf paid for them in Connect's. Sonic's ruling:
ranking and suspending are Junban's; Connect only makes cards. Now:

1. **Connect never suspends by itself** — at the cap the shelf is never asked, whatever *Suspend them* says; Connect
   waits (*Your N cards are waiting*) until you study. A job carrying an ask (*Mine now*) still goes past the cap.
2. **The cap counts only waiting cards still on your list** — Junban's own off-list test (`anki_match.lookup` over
   the list's keys, the kana fold included), your own cards read as Junban reads them (`target_word`). A card off
   the list never blocks mining; a pinned show's Connect cards always count; no list → every card counts, as before.
4. **Said in the window** — *Needs you* holds ONE card while cards Connect made sit on its shelf: *N cards made for
   you are set aside* · *Put back* (every restore point still holding cards) · *Leave them*.

What a wrong answer costs: cards suspended in Anki by a switch the learner turned off (the report); mining stopped by
cards Junban set aside; mining without a limit when the list can't be read; a set-aside pile no one sees. Against
`runner.Steps` with its Anki reads stubbed and the needs service's pure entries; no Anki, no network.
"""
import contextlib

import pytest

from app import anki_connect
from app.connect import runner, shelf
from app.services import needs


class _Shelf:
    """Stands in for `Steps.shelve` and `Steps._shelve`: counts every ask (none may come)."""

    def __init__(self):
        self.calls = 0

    def __call__(self, *args):
        self.calls += 1
        return 5


def _steps(count=12, **settings):
    """A run's steps at the cap: `count` cards waiting for a cap of 10."""
    steps = runner.Steps(dict({"connect_enabled": True}, **settings))
    steps.cap = lambda lang: 10
    steps.waiting_count = lambda lang: count
    steps.shelve = steps._shelve = _Shelf()
    return steps


TODO = [{"word": "撒く", "reading": "まく"}, {"word": "血塗れ", "reading": "ちまみれ"}]


# --- 1. Connect never suspends by itself ------------------------------------------------------------------------------ #
@pytest.mark.parametrize("suspend_them", [False, True, None])
def test_at_the_cap_nothing_goes_to_the_shelf_whatever_suspend_them_says(suspend_them):
    # why: the report — 236 cards suspended by Connect; suspending is Junban's alone now, so even with Suspend them on
    # Connect only waits
    steps = _steps(**({} if suspend_them is None else {"junban_later_suspend": suspend_them}))
    held = runner._at_cap(steps, None, "ja", TODO)
    assert isinstance(held, runner.Wait) and held.reason.startswith("Your 12 cards are waiting")
    assert steps.shelve.calls == 0, "the shelf never asked: nothing suspended"


def test_at_the_cap_the_next_job_waits_before_its_pick_with_no_shelf_try_first():
    # why: before, `_full` let a job be picked until the run's shelf had had its try; with no shelf at the cap a job
    # is held before its pick at once — never picked again at every look
    steps = _steps()
    held = runner._full(steps, "ja")
    assert isinstance(held, runner.Wait) and "12 cards are waiting" in held.reason
    assert steps.shelve.calls == 0


def test_mine_now_goes_past_the_cap_and_below_the_cap_nothing_waits():
    assert runner._full(_steps(), "ja", asked=True) is None, "your press is the yes for that episode"
    assert runner._at_cap(_steps(), None, "ja", TODO, asked=True) is None
    assert runner._at_cap(_steps(count=9), None, "ja", TODO) is None
    assert runner._full(_steps(count=10), "ja") is not None, "exactly at the cap is a full pile"


def test_no_cap_never_waits():
    steps = _steps()
    steps.cap = lambda lang: 0
    assert runner._at_cap(steps, None, "ja", TODO) is None and runner._full(steps, "ja") is None


def test_a_whole_run_at_the_cap_shelves_nothing(tmp_path):
    # why: the runner end to end (FakeSteps' shelf would free room if asked): the job waits, no shelving
    from app.connect.ledger import Ledger
    from tests.connect.fake_steps import FakeSteps
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        steps = FakeSteps(str(tmp_path), {"line": {"ja": [1]}, "queue": {"ja": [1]}, "cap": 300, "waiting": 320,
                                          "shelf_frees": 40})
        summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=2)
        assert not any(e[0] == "shelve" for e in steps.log), steps.log
        assert summary["languages"]["ja"]["waiting"][1].startswith("Your 320 cards are waiting")
        assert ledger.jobs("ja")[0]["state"] == "waiting"


# --- 2. the cap counts only the waiting cards still on your list ------------------------------------------------------ #
class _Store:
    pass


def _counting(monkeypatch, lang, notes, made, listed, theirs=None, pinned=(), csv_rows=None, tmp_path=None):
    """`Steps.waiting_count` over a stubbed Anki: `notes` the waiting notes Anki finds (the decks' and Connect's),
    `made` {note: (item, word)} the store's, `listed` the list's (Word, Reading) keys, `theirs` {note: word} your own
    cards' Word fields; `csv_rows` the last Generate's list in results/ (Orth / Forms) when given."""
    steps = runner.Steps({"connect_enabled": True, "anki_sync_decks": {lang: ["日本語::Mining"]}})
    steps._open = lambda _lang: contextlib.nullcontext(_Store())
    monkeypatch.setattr(shelf, "made_notes", lambda store: dict(made))
    monkeypatch.setattr(shelf, "pinned_items", lambda store: set(pinned))
    monkeypatch.setattr(anki_connect, "find_notes", lambda url, query: list(notes))
    reads = []

    def notes_info(url, ids):
        reads.append(list(ids))
        return [{"noteId": n, "modelName": "Lapis", "fields": {"Word": {"value": (theirs or {}).get(n, ""), "order": 0}}}
                for n in ids]
    monkeypatch.setattr(anki_connect, "notes_info", notes_info)
    steps._plan_now = lambda _lang: None                    # no re-plan: the last Generate's list
    steps.list_reads = []
    steps._list_order = lambda _lang: steps.list_reads.append(_lang) or (
        None if listed is None else {k: i for i, k in enumerate(listed)})
    from app.cli import verbs
    if csv_rows is None:
        monkeypatch.setattr(verbs, "_results_language", lambda: "none")
    else:
        import csv
        with open(tmp_path / verbs.PRIORITY_CSV, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["Word", "Reading", "Orth", "Forms"])
            w.writeheader()
            w.writerows(csv_rows)
        monkeypatch.setattr(verbs, "_results_language", lambda: lang)
        monkeypatch.setattr(verbs, "_results_dir", lambda: str(tmp_path))
    return steps, reads


LIST_JA = [("撒く", "マク"), ("血塗れ", "チマミレ"), ("眼鏡", "メガネ"), ("するり", "スルリ")]


def test_connects_cards_off_the_list_never_count_toward_the_cap(monkeypatch):
    # why: the report's other half — cards set aside off the list (Junban's later cards) blocked mining; only the
    # words still on the list are cards you'll meet
    made = {1: (7, "撒く"), 2: (7, "眼鏡"), 3: (8, "海原"), 4: (8, "怒涛")}
    steps, _reads = _counting(monkeypatch, "ja", [1, 2, 3, 4], made, LIST_JA)
    assert steps.waiting_count("ja") == 2


def test_your_own_cards_count_by_junbans_reading_of_their_word(monkeypatch):
    # why: your own mined cards in 日本語::Mining count only while their word is on the list (Junban's test), so a
    # backlog of your own off-list cards no longer fills the cap; スルリ finds するり by the kana fold
    theirs = {10: "眼鏡", 11: "スルリ", 12: "蝸牛", 13: ""}
    steps, reads = _counting(monkeypatch, "ja", [10, 11, 12, 13], {}, LIST_JA, theirs=theirs)
    assert steps.waiting_count("ja") == 2
    assert steps.waiting_count("ja") == 2
    assert reads == [[10, 11, 12, 13]], "each of your notes read from Anki once a run (S19)"
    assert steps.list_reads == ["ja"], "the list read once while it is the same (`_full` asks before every pick)"


def test_the_last_generates_spellings_count_too(monkeypatch, tmp_path):
    # why: Junban's index holds a row's Orth and Forms, so a card written まみれ is on the list as 血塗れ's form
    rows = [{"Word": "血塗れ", "Reading": "チマミレ", "Orth": "血まみれ", "Forms": "まみれ|血みどろ"}]
    theirs = {20: "血まみれ", 21: "まみれ", 22: "蝸牛"}
    steps, _reads = _counting(monkeypatch, "ja", [20, 21, 22], {}, [("血塗れ", "チマミレ")], theirs=theirs,
                              csv_rows=rows, tmp_path=tmp_path)
    assert steps.waiting_count("ja") == 2


def test_the_last_generates_list_of_another_language_is_never_read(monkeypatch, tmp_path):
    # why: results/ hold one language's list; a Chinese count must never read the Japanese CSV's keys
    rows = [{"Word": "血塗れ", "Reading": "チマミレ", "Orth": "血まみれ", "Forms": "まみれ"}]
    steps, _reads = _counting(monkeypatch, "zh", [30, 31], {30: (1, "学习"), 31: (1, "血まみれ")}, [("学习", "xué xí")],
                              csv_rows=rows, tmp_path=tmp_path)
    from app.cli import verbs
    monkeypatch.setattr(verbs, "_results_language", lambda: "ja")
    assert steps.waiting_count("zh") == 1


def test_a_pinned_shows_connect_cards_always_count(monkeypatch):
    # why: Study its cards first puts a pinned show's cards at the front, whatever the list says (a finished show's
    # words leave it) — they are the next cards you meet
    made = {1: (7, "海原"), 2: (8, "怒涛")}
    steps, _reads = _counting(monkeypatch, "ja", [1, 2], made, LIST_JA, pinned={7})
    assert steps.waiting_count("ja") == 1


@pytest.mark.parametrize("listed", [None, []])
def test_with_no_list_to_read_every_waiting_card_counts_as_before(monkeypatch, listed):
    # why: a list that can't be read must never mean "nothing waits" — Connect would mine without a limit
    made = {1: (7, "海原"), 2: (8, "怒涛")}
    steps, reads = _counting(monkeypatch, "ja", [1, 2, 10], made, listed, theirs={10: "蝸牛"})
    assert steps.waiting_count("ja") == 3
    assert reads == [], "no list: no note read"


def test_chinese_counts_by_its_own_list(monkeypatch):
    made = {1: (1, "学习"), 2: (1, "熊猫")}
    steps, _reads = _counting(monkeypatch, "zh", [1, 2, 10, 11], made, [("学习", "xué xí"), ("朋友", "péng you")],
                              theirs={10: "朋友", 11: "自行车"})
    assert steps.waiting_count("zh") == 2


def test_anki_not_answering_your_notes_is_a_wait_never_a_count(monkeypatch):
    steps, _reads = _counting(monkeypatch, "ja", [10], {}, LIST_JA, theirs={10: "眼鏡"})

    def refused(url, ids):
        raise anki_connect.AnkiError("connection refused", kind="offline")
    monkeypatch.setattr(anki_connect, "notes_info", refused)
    monkeypatch.setattr(runner, "_anki_wait", lambda url, step, e: runner.Wait("Anki isn't open", resume=step))
    with pytest.raises(runner.Wait):
        steps.waiting_count("ja")


# --- 4. said in *Needs you* ------------------------------------------------------------------------------------------- #
def _connect(on_shelf=236, runs=None):
    runs = runs if runs is not None else [
        {"run": "shelf-20261120-171012", "cards": 236, "back": 0, "why": "the cap", "at": "2026-11-20T17:10:12Z",
         "words": ["撒く", "血塗れ"]},
        {"run": "shelf-20261118-090000", "cards": 12, "back": 12, "why": "the cap", "at": "2026-11-18T09:00:00Z",
         "words": ["眼鏡"]}]
    return {"shelf": {"on_shelf": on_shelf, "runs": runs, "swap_ins": 0}, "needs": [], "gaps": []}


def _shelf_entries(connect, cards_on=True, answered=frozenset(), seen=frozenset()):
    return [e for e in needs.entries(None, connect=connect, cards_on=cards_on, answered=answered, seen=seen)
            if e.kind == needs.SHELVED]


def test_cards_on_the_shelf_are_one_card_with_put_back_and_leave_them():
    [entry] = _shelf_entries(_connect())
    assert entry.title == "236 cards made for you are set aside."
    assert entry.actions == ("put_back_shelf", "leave_shelf")
    assert entry.unseen, "a new shelving counts on the tab"
    assert entry.data["runs"] == ["shelf-20261120-171012"], "only restore points still holding cards are put back"
    assert entry.data["cards"] == 236
    assert "surasura::shelf" in entry.say and "no longer" in entry.say


def test_one_card_says_so_in_the_singular():
    connect = _connect(on_shelf=1, runs=[{"run": "shelf-1", "cards": 1, "back": 0, "words": ["撒く"]}])
    [entry] = _shelf_entries(connect)
    assert entry.title == "A card made for you is set aside."


def test_nothing_on_the_shelf_is_no_card():
    assert _shelf_entries(_connect(on_shelf=0, runs=[{"run": "shelf-1", "cards": 4, "back": 4}])) == []
    assert _shelf_entries({"shelf": {"on_shelf": 0, "runs": []}}) == []
    assert _shelf_entries({}) == [] and _shelf_entries(None) == []


def test_with_cards_made_for_you_off_there_is_no_card():
    # Put back is Connect's own restore: with its switch off it can't run (the switch's own put-back asks then)
    assert _shelf_entries(_connect(), cards_on=False) == []


def test_leave_them_is_answered_until_more_are_set_aside():
    [entry] = _shelf_entries(_connect())
    answered = frozenset(needs.answer_keys(entry))
    assert _shelf_entries(_connect(), answered=answered) == []
    newer = _connect(on_shelf=250, runs=[{"run": "shelf-20261121-080000", "cards": 14, "back": 0}]
                     + _connect()["shelf"]["runs"])
    [again] = _shelf_entries(newer, answered=answered)
    assert again.title == "250 cards made for you are set aside."
    assert again.data["runs"] == ["shelf-20261121-080000", "shelf-20261120-171012"]


def test_leave_them_holds_when_the_newest_restore_point_is_back_and_an_older_one_still_holds_cards():
    # the review: the key names the newest restore point, never falling back to an older one once it is put back
    older = {"run": "shelf-20261118-090000", "cards": 12, "back": 0}
    [entry] = _shelf_entries(_connect(on_shelf=248, runs=[_connect()["shelf"]["runs"][0], older]))
    answered = frozenset(needs.answer_keys(entry))
    newest_back = dict(_connect()["shelf"]["runs"][0], back=236)
    assert _shelf_entries(_connect(on_shelf=12, runs=[newest_back, older]), answered=answered) == []


def test_a_seen_card_stops_counting():
    [entry] = _shelf_entries(_connect())
    [seen] = _shelf_entries(_connect(), seen=frozenset({entry.key}))
    assert not seen.unseen and needs.badge([seen]) == 0


def test_the_list_is_read_again_once_its_file_changes(monkeypatch, tmp_path):
    # why: a Generate meanwhile writes a new list; the cap must follow it within the run, not keep the old keys
    rows = [{"Word": "血塗れ", "Reading": "チマミレ", "Orth": "血まみれ", "Forms": ""}]
    steps, _reads = _counting(monkeypatch, "ja", [20], {}, [("血塗れ", "チマミレ")], theirs={20: "眼鏡"},
                              csv_rows=rows, tmp_path=tmp_path)
    assert steps.waiting_count("ja") == 0
    import csv
    import os
    from app.cli import verbs
    path = tmp_path / verbs.PRIORITY_CSV
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Word", "Reading", "Orth", "Forms"])
        w.writeheader()
        w.writerows(rows + [{"Word": "眼鏡", "Reading": "メガネ", "Orth": "眼鏡", "Forms": ""}])
    st = os.stat(path)
    os.utime(path, (st.st_atime, st.st_mtime + 5))
    assert steps.waiting_count("ja") == 1 and steps.list_reads == ["ja", "ja"]
