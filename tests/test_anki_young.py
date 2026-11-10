"""Anki's young cards, recorded by the known-words sync for Piyo's practice rounds (`anki_sync.sync_young`), against a
fake AnkiConnect — never live Anki.

**Why it matters:** the record is what a round ranks first ("practise these"), read with Anki closed, so it must be
right without Anki and never half-written: every young card's word with its shortest interval, nothing mature, new or
suspended; light on Anki (one request of interval searches, `notesInfo` only for a note it doesn't hold yet or one
edited); a failed or busy read keeps the last record; the write is atomic and under its own lock.

`YoungCollection` extends test_anki_sync's `FakeCollection` (it evaluates the deck / `-is:new` / `-is:suspended` /
`edited:n` terms itself) with each note's card intervals and Anki's `prop:ivl=n` / `prop:ivl<n` searches, so a test
fails if the engine asks the wrong search. Real Japanese (tests/Test Resources/ja/context_test.txt) and Chinese
(tests/Test Resources/zh/chinese_text_1.txt).
"""
import json
import os
import re
import threading
from unittest import mock

import pytest

from app import anki_sync, locks
from app.path_utils import get_user_files_path
from tests.test_anki_sync import URL, FakeCollection, _ok

JA = ["冒険", "準備", "危険", "価値", "冒険家", "有名", "素晴らしい", "求める"]
ZH = ["总统", "通话", "问题", "关系", "重要"]


class YoungCollection(FakeCollection):
    """FakeCollection whose notes carry their cards' intervals (`ivls`, in days; 0 = still in its learning steps)."""

    def young(self, word, ivls, **kw):
        note_id = self.add(word, **kw)
        self.note(note_id)["ivls"] = list(ivls)
        return note_id

    def _answer(self, payload):
        if payload["action"] == "findNotes" and "prop:ivl" in payload["params"]["query"]:
            query = payload["params"]["query"]
            if "edited:" in query and not self.edited_search:
                return {"result": None, "error": "Invalid search: edited:"}
            found = set(self._find(query))
            op, days = re.search(r"prop:ivl(=|<)(\d+)", query).groups()
            days = int(days)
            match = (lambda ivl: ivl == days) if op == "=" else (lambda ivl: ivl < days)
            return _ok([n["noteId"] for n in self.notes
                        if n["noteId"] in found and any(match(ivl) for ivl in n.get("ivls") or [])])
        return super()._answer(payload)

    def requests_of(self, action):
        return [r for r in self.requests if r["action"] == action]


def _path(language="ja"):
    return os.path.join(get_user_files_path(language), anki_sync.YOUNG_FILE)


def _record(language="ja"):
    with open(_path(language), encoding="utf-8") as f:
        return json.load(f)


def _bytes(language="ja"):
    with open(_path(language), "rb") as f:
        return f.read()


def _young(fake, decks=("TheBank",), fields=(), language="ja"):
    with mock.patch("urllib.request.urlopen", fake):
        return anki_sync.sync_young(language, URL, list(decks), list(fields))


def _deck(words=JA):
    """A real-looking deck: young cards of 3, 0 and 5 days (one note's other card is mature), a mature note, a new
    card and a suspended young one."""
    fake = YoungCollection()
    ids = {
        "冒険": fake.young("冒険", [3]),
        "準備": fake.young("準備", [0]),                   # still in its first learning steps
        "危険": fake.young("危険", [40, 5]),               # recognition mature, production young: young at 5
        "価値": fake.young("価値", [30]),                  # mature
        "冒険家": fake.young("冒険家", [0], new=True),      # never studied: a new card is at 0 days in Anki too
        "有名": fake.young("有名", [2], suspended=True),    # put away, not being learned
    }
    return fake, ids


# --------------------------------------------------------------------------- #
# What the record holds
# --------------------------------------------------------------------------- #
def test_the_first_read_records_each_young_word_with_its_shortest_interval_and_nothing_mature_new_or_suspended():
    fake, ids = _deck()
    assert _young(fake) == (3, None)
    notes = _record()["notes"]
    assert notes == {str(ids["準備"]): {"word": "準備", "interval": 0},
                     str(ids["冒険"]): {"word": "冒険", "interval": 3},
                     str(ids["危険"]): {"word": "危険", "interval": 5}}
    assert anki_sync.young_words("ja") == [("準備", 0), ("冒険", 3), ("危険", 5)]
    # light on Anki: one multi of the 21 interval searches and the decks' studied notes (no edits asked on a first
    # read), then the words of the young notes only — no cardsInfo (it renders every card), no getIntervals (a search
    # per card)
    multi, info = fake.requests_of("multi"), fake.requests_of("notesInfo")
    assert len(multi) == 1 and len(multi[0]["params"]["actions"]) == anki_sync.MATURE_DAYS + 1 == 22
    queries = [a["params"]["query"] for a in multi[0]["params"]["actions"]]
    assert queries[:2] == [
        '(deck:"TheBank") -is:new -is:suspended prop:ivl=0', '(deck:"TheBank") -is:new -is:suspended prop:ivl=1']
    assert queries[-1] == '(deck:"TheBank") -is:new -is:suspended', "the decks' studied notes, mature ones too"
    assert sorted(i for r in info for i in r["params"]["notes"]) == sorted([ids["冒険"], ids["準備"], ids["危険"]])
    assert set(fake.actions) == {"multi", "notesInfo"}


def test_the_words_come_from_the_word_field_as_the_backlog_reads_them():
    """撒く<br>まく is 撒く (anki_match.card_word), and the chosen word field is read, never the "Also read" one."""
    fake = YoungCollection()
    fake.young("撒く", [4], fields=[("Sentence", "種を撒く。"), ("Word", "撒く<br>まく")])
    _young(fake, fields=["Word", "Sentence"])
    assert anki_sync.young_words("ja") == [("撒く", 4)]


def test_one_word_on_two_notes_is_listed_once_at_its_shortest_interval_and_equal_intervals_put_the_newest_first():
    fake = YoungCollection()
    fake.young("準備", [9])
    fake.young("冒険", [2])
    fake.young("準備", [1])
    fake.young("求める", [2])                          # the newest of the two at 2 days
    _young(fake)
    assert anki_sync.young_words("ja") == [("準備", 1), ("求める", 2), ("冒険", 2)]


def test_a_note_with_no_word_is_kept_as_no_word_and_never_read_again():
    """An English-only word field holds no Japanese: never a practice word, and not asked for at every sync."""
    fake = YoungCollection()
    english = fake.young("adventure", [3])
    fake.young("冒険", [3])
    _young(fake)
    assert anki_sync.young_words("ja") == [("冒険", 3)] and anki_sync.count_young("ja") == 1
    assert _record()["notes"][str(english)] == {"word": "", "interval": 3}
    fake.requests.clear()
    _young(fake)
    assert fake.requests_of("notesInfo") == []


# --------------------------------------------------------------------------- #
# Later reads: delta, and only when something changed
# --------------------------------------------------------------------------- #
def test_a_second_read_with_nothing_changed_asks_one_request_and_leaves_the_file_as_it_is():
    fake, _ids = _deck()
    _young(fake)
    before, mtime = _bytes(), os.stat(_path()).st_mtime_ns
    fake.requests.clear()
    assert _young(fake) == (3, None)
    assert fake.actions == ["multi"], "the intervals and the edits in one request; no word read again"
    assert len(fake.requests[0]["params"]["actions"]) == 23 and "edited:" in \
        fake.requests[0]["params"]["actions"][-1]["params"]["query"]
    assert _bytes() == before and os.stat(_path()).st_mtime_ns == mtime


def test_reviews_move_intervals_a_card_that_grows_mature_leaves_and_a_newly_studied_one_is_read_alone():
    fake, ids = _deck()
    _young(fake)
    fake.note(ids["冒険"])["ivls"] = [8]                  # reviewed: no edit, a longer interval
    fake.note(ids["準備"])["ivls"] = [25]                 # grown mature
    fresh = fake.young("求める", [1])                     # studied for the first time today
    fake.requests.clear()
    _young(fake)
    assert anki_sync.young_words("ja") == [("求める", 1), ("危険", 5), ("冒険", 8)]
    assert [i for r in fake.requests_of("notesInfo") for i in r["params"]["notes"]] == [fresh]


def test_a_lapsed_card_comes_back_as_young():
    """A mature card forgotten in review relearns at a short interval: a word to practise again."""
    fake, ids = _deck()
    _young(fake)
    fake.note(ids["価値"])["ivls"] = [1]
    _young(fake)
    assert ("価値", 1) in anki_sync.young_words("ja")


def test_a_young_note_edited_in_anki_is_read_again_with_its_corrected_word():
    fake, ids = _deck()
    _young(fake)
    fake.edit(ids["冒険"], [("Expression", "冒険家"), ("Sentence", "冒険家の例文です。"), ("Meaning", "adventurer")])
    fake.requests.clear()
    _young(fake)
    assert ("冒険家", 3) in anki_sync.young_words("ja") and ("冒険", 3) not in anki_sync.young_words("ja")
    assert [i for r in fake.requests_of("notesInfo") for i in r["params"]["notes"]] == [ids["冒険"]]


def test_an_edited_note_deleted_before_its_word_is_read_never_keeps_its_old_word():
    """Edited, then deleted between the search and the read: its old word must not stay as a practice word."""
    fake, ids = _deck()
    _young(fake)
    fake.edit(ids["冒険"], [("Expression", "冒険家"), ("Sentence", "冒険家の例文です。"), ("Meaning", "adventurer")])
    answer = fake._answer

    def deleted(payload):
        if payload["action"] == "notesInfo":
            return _ok([{} for _ in payload["params"]["notes"]])
        return answer(payload)
    fake._answer = deleted
    _young(fake)
    assert [w for w, _i in anki_sync.young_words("ja")] == ["準備", "危険"]


def test_an_edit_that_keeps_the_word_moves_the_edits_cursor_once_a_day_so_it_isnt_read_again_for_ever():
    """A Hint or a Meaning edited (/anki-clean, Backfill): the word is the same, so nothing it holds changed — but the
    record's time is the `edited:n` cursor, and a cursor that never moves reads that note again at every sync."""
    fake, ids = _deck()
    _young(fake)
    record = _record()
    record["synced_at"] = "2026-10-20T09:00:00"            # last written days ago
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False)
    fields = list(fake.note(ids["冒険"])["fields"])
    fields[2] = ("Meaning", "a journey into the unknown")
    fake.edit(ids["冒険"], fields)
    _young(fake)
    assert _record()["synced_at"] != "2026-10-20T09:00:00", "rewritten once: the cursor moved to now"
    before = _bytes()
    _young(fake)
    assert _bytes() == before, "under a day old: nothing it holds changed, the file stays as it is"


def test_an_anki_too_old_for_edited_still_records_the_intervals():
    fake, _ids = _deck()
    fake.edited_search = False
    _young(fake)
    _young(fake)
    assert anki_sync.young_words("ja") == [("準備", 0), ("冒険", 3), ("危険", 5)]


@pytest.mark.parametrize("change", ["decks", "fields"])
def test_other_decks_or_fields_read_every_young_note_again(change):
    fake, ids = _deck()
    fake.young("重要", [6], deck="中文")
    _young(fake)
    fake.requests.clear()
    if change == "decks":
        _young(fake, decks=("TheBank", "中文"))
        assert ("重要", 6) in anki_sync.young_words("ja")
    else:
        _young(fake, fields=["Expression"])
    read = {i for r in fake.requests_of("notesInfo") for i in r["params"]["notes"]}
    assert {ids["冒険"], ids["準備"], ids["危険"]} <= read


def test_a_record_from_another_version_or_one_that_cant_be_read_is_read_again_in_full():
    fake, _ids = _deck()
    os.makedirs(os.path.dirname(_path()), exist_ok=True)
    with open(_path(), "w", encoding="utf-8") as f:
        f.write('{"version": 1, "notes": {"1": ')            # cut off mid-write by something else
    assert anki_sync.young_words("ja") == [] and anki_sync.count_young("ja") == 0
    assert _young(fake) == (3, None)
    record = _record()
    record["version"] = 0
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(record, f)
    fake.requests.clear()
    _young(fake)
    assert len([i for r in fake.requests_of("notesInfo") for i in r["params"]["notes"]]) == 3
    assert _record()["version"] == anki_sync.YOUNG_VERSION


def test_a_hand_edited_record_of_the_wrong_types_gives_only_its_good_words():
    """Read with Anki closed, so a record edited by hand must never break a round: odd entries are passed over."""
    os.makedirs(os.path.dirname(_path()), exist_ok=True)
    notes = {"1789712080047": {"word": "冒険", "interval": 3}, "1789712080048": {"word": "準備", "interval": "2"},
             "1789712080049": {"word": 42, "interval": 1}, "1789712080050": ["危険", 1],
             "1789712080051": {"word": "価値", "interval": True}, "not-an-id": {"word": "求める", "interval": 0},
             "1789712080052": {"interval": 1}}
    for record in ({"notes": notes}, {"notes": [["冒険", 3]]}, {"notes": "冒険"}, ["冒険"]):
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False)
        expected = [("求める", 0), ("冒険", 3)] if record == {"notes": notes} else []
        assert anki_sync.young_words("ja") == expected
        assert anki_sync.count_young("ja") == (4 if expected else 0)   # 準備 and 価値 hold a word, odd intervals


# --------------------------------------------------------------------------- #
# The empty state, and failures: the last record kept
# --------------------------------------------------------------------------- #
def test_no_young_cards_writes_an_empty_record_and_every_card_grown_mature_empties_it():
    fake = YoungCollection()
    fake.young("価値", [30])
    assert _young(fake) == (0, None)
    assert _record()["notes"] == {} and anki_sync.young_words("ja") == []
    fake.young("冒険", [3])
    _young(fake)
    assert anki_sync.young_words("ja") == [("冒険", 3)]
    for note in fake.notes:
        note["ivls"] = [21]                                 # 21 days: mature, Anki's own line
    _young(fake)
    assert anki_sync.young_words("ja") == []


def test_no_sync_yet_gives_no_young_words_and_no_decks_asks_nothing():
    assert anki_sync.young_words("ja") == [] and anki_sync.load_young("ja") == {}
    fake = YoungCollection()
    assert _young(fake, decks=()) == (0, "Choose at least one deck first.")
    assert fake.requests == [] and not os.path.exists(_path())


def test_decks_with_no_studied_note_at_all_keep_the_last_record():
    """Anki open on another profile, or the decks renamed: no young card is no answer, and the last record stands."""
    fake, _ids = _deck()
    _young(fake)
    before = _bytes()
    for note in fake.notes:
        note["deck"] = "Default"                            # what another profile's search finds for "TheBank": none
    count, error = _young(fake)
    assert count == 3 and "another profile" in error
    assert _bytes() == before


def test_anki_closed_keeps_the_last_record_byte_for_byte():
    fake, _ids = _deck()
    _young(fake)
    before = _bytes()
    fake.offline = True
    count, error = _young(fake)
    assert count == 3 and error
    assert _bytes() == before


def test_one_interval_search_failing_keeps_the_last_record():
    """A record missing some intervals would rank words wrongly: nothing is written."""
    fake, _ids = _deck()
    _young(fake)
    before = _bytes()
    answer = fake._answer

    def failing(payload):
        if payload["action"] == "findNotes" and payload["params"]["query"].endswith("prop:ivl=7"):
            return {"result": None, "error": "collection is not available"}
        return answer(payload)
    fake._answer = failing
    count, error = _young(fake)
    assert count == 3 and "collection is not available" in error
    assert _bytes() == before


def test_a_write_that_fails_leaves_the_last_record_whole_and_no_temp_file():
    """The write is a temp file + os.replace: a failure at the swap never leaves half a file."""
    fake, ids = _deck()
    _young(fake)
    before = _bytes()
    fake.note(ids["冒険"])["ivls"] = [9]
    with mock.patch.object(anki_sync.os, "replace", side_effect=OSError(28, "No space left on device")):
        count, error = _young(fake)
    assert count == 3 and "Could not save your Anki young cards" in error
    assert _bytes() == before
    assert os.listdir(os.path.dirname(_path())) == [anki_sync.YOUNG_FILE]


# --------------------------------------------------------------------------- #
# The lock
# --------------------------------------------------------------------------- #
def test_the_record_is_written_while_its_lock_is_held():
    fake, _ids = _deck()
    seen = []
    write = anki_sync._atomic_write_json

    def watched(path, data, indent=2):
        seen.append(locks.held_here(anki_sync.young_lock_name("ja")))
        return write(path, data, indent=indent)
    with mock.patch.object(anki_sync, "_atomic_write_json", watched):
        _young(fake)
    assert seen == [True]
    assert not locks.held_in_process(anki_sync.young_lock_name("ja")), "let go after the write"


def test_a_read_while_another_holds_the_lock_writes_nothing_and_says_so(monkeypatch):
    """Two programs syncing at once (the window and surasura-cli): the second waits, then gives up without a write."""
    monkeypatch.setattr(anki_sync, "KNOWN_LOCK_WAIT", 0.3)
    fake, _ids = _deck()
    _young(fake)
    before = _bytes()
    taken, done = threading.Event(), threading.Event()

    def holder():
        held = locks.take(anki_sync.young_lock_name("ja"), "another sync")
        taken.set()
        done.wait(10)
        held.release()
    thread = threading.Thread(target=holder)
    thread.start()
    try:
        assert taken.wait(10)
        fake.requests.clear()
        count, error = _young(fake)
    finally:
        done.set()
        thread.join(10)
    assert count == 3 and "weren't read this time" in error
    assert fake.requests == [] and _bytes() == before
    assert _young(fake) == (3, None), "the next sync reads them"


def test_a_failed_read_lets_the_lock_go():
    fake, _ids = _deck()
    fake.offline = True
    _young(fake)
    assert not locks.held_in_process(anki_sync.young_lock_name("ja"))


# --------------------------------------------------------------------------- #
# Chinese, and the one sync order
# --------------------------------------------------------------------------- #
def test_a_chinese_deck_records_its_young_words_in_zh_user_files():
    fake = YoungCollection()
    fake.young("总统", [2], deck="中文")
    fake.young("问题", [0], deck="中文")
    fake.young("关系", [60], deck="中文")
    fake.young("重要", [11, 3], deck="中文")
    assert _young(fake, decks=["中文"], language="zh") == (3, None)
    assert anki_sync.young_words("zh") == [("问题", 0), ("总统", 2), ("重要", 3)]
    assert anki_sync.young_words("ja") == [] and _path("zh") != _path("ja")


def test_every_sync_reads_the_young_cards_after_the_new_cards_and_a_failed_sync_reads_none(monkeypatch):
    class Result:
        def __init__(self, error=None, read=None):
            self.added, self.total_known, self.error, self.read = 0, 5, error, read
    calls = []
    monkeypatch.setattr(anki_sync, "sync_backlog", lambda *a, **k: calls.append("backlog"))
    monkeypatch.setattr(anki_sync, "sync_young", lambda *a, **k: calls.append(("young", a, k)))
    monkeypatch.setattr(anki_sync, "read_known_signal", lambda *a, **k: calls.append("signal"))
    read = [{"noteId": 1789712080047}]
    monkeypatch.setattr(anki_sync, "sync", lambda *a, **k: Result(read=read))
    progress = []
    result, _signal = anki_sync.sync_all("ja", URL, ["TheBank"], ["Word"], {}, progress=lambda *p: progress.append(p))
    assert calls == ["backlog", ("young", ("ja", URL, ["TheBank"], ["Word"]), {"read": read}), "signal"]
    assert result.read == [], "the notes the sync read aren't kept past it"
    assert progress == [("reading Anki", 0, 3), ("reading Anki's new cards", 1, 3), ("reading Anki's young cards", 2, 3)]
    calls.clear()
    monkeypatch.setattr(anki_sync, "sync", lambda *a, **k: Result(error="KnownWord.json can't be read"))
    anki_sync.sync_all("ja", URL, ["TheBank"], [], {})
    assert calls == []


def test_a_young_read_that_raises_never_costs_the_sync_its_result(monkeypatch):
    class Result:
        added, total_known, error = 2, 9, None
    monkeypatch.setattr(anki_sync, "sync", lambda *a, **k: Result())
    monkeypatch.setattr(anki_sync, "sync_backlog", lambda *a, **k: None)
    monkeypatch.setattr(anki_sync, "sync_young", mock.Mock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(anki_sync, "read_known_signal", lambda *a, **k: None)
    result, _signal = anki_sync.sync_all("ja", URL, ["TheBank"], [], {})
    assert (result.added, result.total_known, result.error) == (2, 9, None)


def test_a_card_studied_today_is_read_once_by_the_sync_and_never_asked_for_again_by_the_young_read(monkeypatch):
    """The young read takes the words of the notes the known sync just read; it asks Anki only for a note the sync
    didn't read — a mature card forgotten back to young."""
    monkeypatch.setattr(anki_sync, "_connect_on", lambda: False)
    fake, ids = _deck()

    def sync_all():
        fake.requests.clear()
        with mock.patch("urllib.request.urlopen", fake):
            result, _signal = anki_sync.sync_all("ja", URL, ["TheBank"], [], {})
        assert result.error is None
        return [i for r in fake.requests_of("notesInfo") for i in r["params"]["notes"]]

    read = sync_all()                                       # the first sync reads every studied note, once
    assert sorted(read) == sorted(set(read)) and anki_sync.young_words("ja") == [("準備", 0), ("冒険", 3), ("危険", 5)]
    fresh = fake.young("求める", [1])
    assert sync_all() == [fresh], "studied today: the sync's own read, not a second one"
    assert ("求める", 1) in anki_sync.young_words("ja")
    fake.note(ids["価値"])["ivls"] = [1]                  # a mature card forgotten in review
    assert sync_all() == [ids["価値"]], "only the young read asks: the sync read it long ago"
    assert ("価値", 1) in anki_sync.young_words("ja")
