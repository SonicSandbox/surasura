"""Kantan-SL: Swap, the simple version (the review loop's ⇄ = Suspend + Green flag; ROLES.md's Swap: a new card from
another line; the full Swap, 3.1, rewrites the old card in place from the same record).

What each test holds still:
- **never the same line:** the new card is never cut from a line its old card holds (by the line's text: markup,
  furigana and punctuation aside, a line inside the old card's sentence counts as it); an episode that says the word
  only there gives no card (`only-line`, the picker's one rule), and the swap tries another episode, then waits;
- **never for a word now Known or Ignored:** checked at the ask, at the job's start and at its end — the swap queue's
  entry dropped with why ("known" · "ignored");
- **one maker:** the swap queue's entries and Kyou-DW's *Bad card* both ask through `make_card`; Connect's job of kind
  `swap` picks only that word (whatever the list, its old card), is never moved by a store ask nor un-asked, and makes
  no receipt;
- **the record:** made → the queue's entry made with the new note (the pair), the old card tagged `surasura::swapped`
  only (never while you review; a deleted old card: nothing to tag); two greens for one word share one new card;
- **Undo:** the new card deleted with a backup (Tidy's), the old card unsuspended, its green flag off, its tag gone;
  twice: nothing more; a new card you studied stays and nothing changes;
- **said:** *Needs you* — a made swap with *Undo* · *OK*; ONE quiet card for the words with no other line.

What a wrong answer costs: a new card from the very line the learner wanted gone, a card for a word they marked Known
or Ignored, a second card for a word, an old card changed beyond the learner's own move, or an Undo that loses a card.
Real Japanese and Chinese lines from tests/Test Resources; the ledger is real; Anki is Tidy's fake (a real package).
"""
import calendar
import json
import os
import time

import pytest

from app import analyzer, cues
from app.connect import inbox, library, pick, sentences, status, swap, swap_queue, tidy
from app.connect.ledger import OPEN, SWAP, Ledger
from app.services import needs
from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.connect.test_kyou_sh2_tidy import FakeAnki as TidyAnki
from tests.connect.test_kantan_sd_list import BOUKEN, EASY, HARD, TODAY, _no_library_search, placed  # noqa: F401
from tests.connect.test_kantan_sd_list import _place as _sd_place, _plan as _sd_plan, _write as _sd_write

RESOURCES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Test Resources")
JA = os.path.join(RESOURCES, "ja", "library_episode.ass")
ZH = os.path.join(RESOURCES, "zh", "night_market.srt")
# The word, the old card's line, the other line the word is said in (both real lines of the files above)
CASES = {"ja": ("借りる", "すみません、この本を借りたいんですが。", "ペンを借りてもいいですか"),
         "zh": ("我们", "今天我们要去台北的夜市吃东西。", "我们先点一碗牛肉面")}
MINING = "日本語::Mining"       # the deck a batch makes its cards in (Tidy's fake's own): each made card's home
SHOWN = "Surasura::日本語"      # the deck Surasura shows for new cards (Settings: `fields.surasura_deck`)


@pytest.fixture(autouse=True)
def _a_run():
    analyzer.SANITIZE_JA = True             # as analyzer.main sets it (conftest restores the global)


def _read(lang):
    read = cues.read(JA if lang == "ja" else ZH, lang)
    return read, cues.tokens(read, lang)


def _swap_pick(lang, avoid, line=None, known=(), carded=(), word=None):
    read, tokens = _read(lang)
    spec = {"word": word or CASES[lang][0], "reading": "", "avoid": list(avoid), "line": line}
    return pick.pick(read, tokens, lang, lambda key: key[0] in known, mode="list", listed={}, carded=set(carded),
                     swap=spec)


# --------------------------------------------------------------------------- #
# The pick: only the word, never the old card's line
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_swap_sends_its_word_from_another_line_never_the_old_cards_though_it_has_a_card(lang):
    word, old, other = CASES[lang]
    # the word has a card (the old one) and the list doesn't hold it: a swap sends it all the same, alone
    got = _swap_pick(lang, [old], carded={word})
    assert [w["word"] for w in got["words"]] == [word]
    assert other in got["words"][0]["line_text"] and not sentences.same_line(got["words"][0]["line_text"], [old])


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_an_episode_saying_the_word_only_in_its_old_cards_lines_gives_no_card(lang):
    word, old, other = CASES[lang]
    got = _swap_pick(lang, [old, other])
    assert got["words"] == [] and [n["reason"] for n in got["not_offered"]] == ["only-line"]


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_known_or_ignored_word_is_never_sent_by_a_swap(lang):
    word, old, _other = CASES[lang]
    assert _swap_pick(lang, [old], known={word})["words"] == []


def test_the_old_cards_sentence_as_anki_holds_it_still_counts_as_its_line():
    # the card's Sentence field: bold, Anki's furigana brackets, a nbsp — the same line
    word, old, _other = CASES["ja"]
    field = "すみません、この<b>本</b>[ほん]を&nbsp;<b>借</b>[か]りたいんですが。"
    got = _swap_pick("ja", [field])
    assert got["words"] and not sentences.same_line(got["words"][0]["line_text"], [old])


def test_the_line_the_learner_picked_wins_when_the_episode_says_it_there():
    # two other lines say 借りる; the learner's pick is the later one
    read = cues.read(JA, "ja")
    lines = [c.text for c in read if "借り" in (c.text or "")]
    assert len(lines) >= 2
    got = _swap_pick("ja", [], line=lines[-1])
    assert sentences.same_line(got["words"][0]["line_text"], [lines[-1]])


def test_same_line_reads_text_not_markup_and_never_an_empty_line():
    assert sentences.same_line("「借りたい」", ["借りたい"]) and sentences.same_line("借りたい", ["本を<b>借りたい</b>んです"])
    assert not sentences.same_line("返します", ["借りたい"])
    assert not sentences.same_line("…", ["…"]) and not sentences.same_line("あ", ["あいう"])
    # an old card whose sentence is only markup or punctuation avoids nothing (it must never block every line)
    assert not sentences.same_line("借りたい", ["", "<b></b>", "……"])


def test_a_line_id_names_an_item_and_its_start():
    assert swap.line_id(12, 93.1) == "12:93100" and swap._parse_line_id("12:93100") == (12, 93100)
    assert swap._parse_line_id("nonsense") is None


# --------------------------------------------------------------------------- #
# The maker, the look, the record
# --------------------------------------------------------------------------- #
@pytest.fixture
def ledger(tmp_path, monkeypatch):
    from app.connect import ledger as ledger_mod
    path = str(tmp_path / "connect" / "ledger.sqlite")
    monkeypatch.setattr(ledger_mod, "path", lambda: path)
    book = Ledger(path)
    try:
        yield book
    finally:
        book.close()


class Anki(TidyAnki):
    def add_tags(self, ids, tag):
        self.log.append(("add_tags", tuple(ids), tag))
        for i in ids:
            self.notes_[int(i)]["tags"].append(tag)

    def remove_tags(self, ids, tag):
        self.log.append(("remove_tags", tuple(ids), tag))
        for i in ids:
            self.notes_[int(i)]["tags"] = [t for t in self.notes_[int(i)]["tags"] if t != tag]

    def unsuspend(self, ids):
        self.log.append(("unsuspend", tuple(ids)))
        for i in ids:
            self.cards_[int(i)]["queue"] = 0

    def set_flag(self, ids, flag):
        self.log.append(("set_flag", tuple(ids), flag))
        for i in ids:
            self.cards_[int(i)]["flags"] = flag


class Steps:
    url = None

    def __init__(self, subtitle=None):
        self._subtitle = subtitle

    def subtitle(self, lang, job):
        return self._subtitle

    def video(self, lang, job):
        return "episode.mkv"

    def reading(self, lang, job):
        return None


def _lists(lang, known=(), ignored=()):
    folder = os.path.join(h.root(), "User Files", lang)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "KnownWord.json"), "w", encoding="utf-8") as f:
        json.dump({"words": [{"dictForm": w, "knownStatus": "KNOWN"} for w in known]}, f, ensure_ascii=False)
    with open(os.path.join(folder, "IgnoreList.txt"), "w", encoding="utf-8") as f:
        f.write("".join(f"{w}\n" for w in ignored))


def _queued(lang, word, card=9000, note=900, line_id=None):
    entry = swap_queue.add(lang, word, card, note, "sync-1", line_id=line_id)
    assert entry is not None
    return entry


def _old_card(anki, lang, note=900, word=None):
    anki.add(note, "Japanese", word or CASES[lang][0], 1, cards=[{"reps": 3, "type": 2, "queue": -1, "flags": 3}])
    anki.notes_[note]["tags"] = ["Japanese"]
    return anki


def _make_the_job(ledger, row, note=950, tag="surasura::connect::x", record=False, deck=MINING):
    """Connect's job for the swap ends having made `note`, as the runner's `_mine` ends it: the batch's outcomes with
    the deck it made its cards in (`end_batch(deck=…)`: each made card's home, Kyou-SH4's `homes`; `deck` None only
    for a test of a card with no home on record — a lost or empty mapping deck); `record`: the mining's store write
    too — the runner's own step (`runner._record_made`, the library's made-words record), as every Connect job writes
    it before it ends (a library store must be there: `c.library`)."""
    ledger.end_batch(row["job_id"], 1, "done", [{"word": row["word"], "reading": "", "outcome": "made",
                                                 "note_id": note}], deck=deck)
    if record:
        from app.connect import runner
        runner._record_made(runner.Steps({}), ledger, row["language"], ledger.job_by_id(row["job_id"]), True)
    ledger.set_state(row["job_id"], "done")


def _opener(lang):
    return lambda: library.open_store(lang)


def _row(ledger, swap_id):
    return swap._rows(ledger, "id = ?", (swap_id,))[0]


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_queued_green_becomes_one_swap_job_then_made_with_the_pair_and_the_old_card_tagged(ledger, lang,
                                                                                               monkeypatch):
    word, old, other = CASES[lang]
    _lists(lang)
    entry = _queued(lang, word)
    picked = []
    monkeypatch.setattr(swap, "choose_line", lambda l, w, avoid, reachable, skip_items=(), reading=None: (
        picked.append((w, list(avoid))) or (7, other)))
    anki = _old_card(Anki(), lang)
    ledger.end_batch(ledger.queue(lang, 3, "user", None, store_id="s1"), 1, "done",
                     [{"word": word, "reading": "", "outcome": "made", "note_id": 900, "sentence": old}], deck=MINING)
    got = swap.look(Steps(), ledger, lang, store_id="s1", anki=anki, files=5)
    assert got["queued"] == 1 and picked == [(word, [old])]          # the old card's line from Connect's record
    row = swap._rows(ledger, "language = ?", (lang,))[0]
    job = ledger.job_by_id(row["job_id"])
    assert (job["kind"], job["item_id"], job["words"], job["state"]) == (SWAP, 7, [(word, "")], "queued")
    assert job["asked_at"]                                           # the learner's move: never held by the cap
    assert swap.spec_of(job["id"], lang) == {"word": word, "reading": "", "avoid": [old], "line": other}
    _make_the_job(ledger, row)
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    row = _row(ledger, row["id"])
    assert (row["state"], row["new_note"], row["tagged"]) == (swap.MADE, 950, 1)
    made = [e for e in swap_queue.load(lang) if e["id"] == entry["id"]][0]
    assert made["state"] == "made" and made["made"]["note"] == 950
    assert swap.SWAP_TAG in anki.notes_[900]["tags"]
    assert anki.cards_[9000]["queue"] == -1 and anki.cards_[9000]["flags"] == 3       # as the learner left it


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_word_known_or_ignored_between_queue_and_make_is_dropped_with_why(ledger, lang, monkeypatch):
    word = CASES[lang][0]
    _lists(lang, known=[word])
    entry = _queued(lang, word)
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: pytest.fail("no line for a known word"))
    swap.look(Steps(), ledger, lang, anki=Anki(), files=5)
    assert [e["why"] for e in swap_queue.load(lang) if e["id"] == entry["id"]] == ["known"]
    _lists(lang, ignored=[word])
    again = _queued(lang, word, card=9200)
    swap.look(Steps(), ledger, lang, anki=Anki(), files=5)
    assert [e["why"] for e in swap_queue.load(lang) if e["id"] == again["id"]] == ["ignored"]
    assert not ledger.jobs(lang)


def test_a_word_known_while_its_job_ran_is_dropped_at_the_end(ledger, monkeypatch):
    lang, (word, _old, other) = "ja", CASES["ja"]
    _lists(lang)
    entry = _queued(lang, word)
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: (7, other))
    swap.look(Steps(), ledger, lang, anki=Anki(), files=5)
    row = swap._rows(ledger, "1 = 1")[0]
    ledger.set_state(row["job_id"], "done")                 # the pick read it as known: nothing made
    _lists(lang, known=[word])
    swap.look(Steps(), ledger, lang, anki=Anki(), files=5)
    assert _row(ledger, row["id"])["state"] == swap.DROPPED
    assert [e["why"] for e in swap_queue.load(lang) if e["id"] == entry["id"]] == ["known"]


def test_no_other_line_waits_said_once_and_is_looked_at_again_when_the_library_grows(ledger, monkeypatch):
    lang, word = "ja", CASES["ja"][0]
    _lists(lang)
    _queued(lang, word)
    calls = []
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: calls.append(1))
    swap.look(Steps(), ledger, lang, anki=Anki(), files=5)
    swap.look(Steps(), ledger, lang, anki=Anki(), files=5)       # nothing new: not looked at again
    assert len(calls) == 1
    record = swap.status_of(ledger.conn, lang)
    assert [w["word"] for w in record["waits"]] == [word] and record["made"] == []
    swap.look(Steps(), ledger, lang, anki=Anki(), files=6)       # a new file: looked at again
    assert len(calls) == 2
    entries = needs._swap_entries({"swaps": record}, frozenset())
    assert [e.kind for e in entries] == [needs.SWAP_WAITS] and word in entries[0].title
    assert needs._swap_entries({"swaps": record}, frozenset(), answered={entries[0].key}) == []


def test_an_episode_whose_lines_are_all_the_old_cards_is_skipped_then_the_swap_waits(ledger, monkeypatch):
    lang, (word, _old, other) = "ja", CASES["ja"]
    _lists(lang)
    _queued(lang, word)
    seen = []

    def choose(l, w, avoid, reachable, skip_items=(), reading=None):
        seen.append(list(skip_items))
        return (10 + len(seen), other)
    monkeypatch.setattr(swap, "choose_line", choose)
    for _ in range(swap.TRIES):
        swap.look(Steps(), ledger, lang, anki=Anki(), files=5)
        row = swap._rows(ledger, "1 = 1")[0]
        if row["job_id"]:
            ledger.set_state(row["job_id"], "done")             # its pick: `only-line`, no card
    swap.look(Steps(), ledger, lang, anki=Anki(), files=5)
    assert seen == [[], [11], [11, 12]]
    assert swap._rows(ledger, "1 = 1")[0]["state"] == swap.WAITS


def test_a_line_id_that_no_longer_exists_falls_back_to_swaps_own_pick(ledger, tmp_path, monkeypatch):
    lang, (word, _old, other) = "ja", CASES["ja"]
    _lists(lang)
    _queued(lang, word, line_id="3:999999")
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: (7, other))
    swap.look(Steps(subtitle=JA), ledger, lang, anki=Anki(), files=5)
    row = swap._rows(ledger, "1 = 1")[0]
    assert (row["state"], row["item_id"], row["line"]) == (swap.QUEUED, 7, other)


def test_a_line_id_that_exists_is_the_line(ledger, monkeypatch):
    lang, word = "ja", CASES["ja"][0]
    _lists(lang)
    cue = [c for c in cues.read(JA, lang) if "ペンを借り" in (c.text or "")][0]
    _queued(lang, word, line_id=swap.line_id(3, cues.seconds(cue.start)))
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: pytest.fail("the learner picked a line"))
    swap.look(Steps(subtitle=JA), ledger, lang, anki=Anki(), files=5)
    row = swap._rows(ledger, "1 = 1")[0]
    assert (row["item_id"], row["line"]) == (3, cue.text)


def test_two_greens_for_one_word_share_one_new_card(ledger, monkeypatch):
    lang, (word, _old, other) = "ja", CASES["ja"]
    _lists(lang)
    first, second = _queued(lang, word, card=9000, note=900), _queued(lang, word, card=9100, note=910)
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: (7, other))
    anki = _old_card(_old_card(Anki(), lang, 900), lang, 910)
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    rows = swap._rows(ledger, "1 = 1")
    assert [r["state"] for r in rows] == [swap.QUEUED, swap.ASKED] and len(ledger.jobs(lang)) == 1
    _make_the_job(ledger, rows[0])
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    made = {e["id"]: e for e in swap_queue.load(lang)}
    assert made[first["id"]]["made"]["note"] == made[second["id"]]["made"]["note"] == 950
    assert all(swap.SWAP_TAG in anki.notes_[n]["tags"] for n in (900, 910))


def test_while_you_review_the_old_card_waits_for_its_tag_and_a_deleted_one_needs_none(ledger, monkeypatch):
    lang, (word, _old, other) = "ja", CASES["ja"]
    _lists(lang)
    _queued(lang, word)
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: (7, other))
    anki = _old_card(Anki(), lang)
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    _make_the_job(ledger, swap._rows(ledger, "1 = 1")[0])
    anki.busy = True
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    assert swap._rows(ledger, "1 = 1")[0]["tagged"] == 0 and not [x for x in anki.log if x[0] == "add_tags"]
    anki.busy = False
    del anki.notes_[900]                                    # the learner deleted the old card meanwhile
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    assert swap._rows(ledger, "1 = 1")[0]["tagged"] == 1 and not [x for x in anki.log if x[0] == "add_tags"]


def test_anki_closed_leaves_the_tag_for_a_later_look(ledger, monkeypatch):
    lang, (word, _old, other) = "zh", CASES["zh"]
    _lists(lang)
    _queued(lang, word)
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: (7, other))
    anki = _old_card(Anki(), lang)
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    _make_the_job(ledger, swap._rows(ledger, "1 = 1")[0])

    def closed(_ids):
        raise OSError("Anki closed")
    anki.notes = closed
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    assert swap._rows(ledger, "1 = 1")[0]["tagged"] == 0


def test_kyou_dws_bad_card_asks_the_same_maker_for_a_deleted_card(ledger, monkeypatch):
    lang, (word, old, other) = "ja", CASES["ja"]
    _lists(lang)
    got = swap.make_card(lang, word, old_note=900, by=swap.BY_BAD_CARD, ledger=ledger, wake=False)
    assert got["state"] == swap.ASKED and got["new"]
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: (7, other))
    swap.look(Steps(), ledger, lang, anki=Anki(), files=5)
    assert swap._rows(ledger, "1 = 1")[0]["state"] == swap.QUEUED


def test_the_swap_job_is_never_moved_by_a_store_ask_nor_un_asked_and_waits_for_an_open_job(ledger):
    lang = "ja"
    job = ledger.queue_swap(lang, 7, "借りる", "", "2026-11-20T01:00:00Z", store_id="s1")
    assert ledger.ask(lang, 7, "2026-11-20T02:00:00Z") is None        # the ask waits for the swap's one word
    assert ledger.queue_swap(lang, 7, "返す", "", "2026-11-20T01:00:00Z") is None
    assert inbox.keeps(ledger.job_by_id(job)) is True
    inbox._asks(_NoStore(), lang, ledger, {}, [], [], [])          # no store ask holds it: it stays asked
    assert ledger.job_by_id(job)["asked_at"] and ledger.job_by_id(job)["state"] in OPEN


class _NoStore:
    def __getattr__(self, name):
        raise AssertionError(f"no store read expected ({name})")


# --------------------------------------------------------------------------- #
# Undo
# --------------------------------------------------------------------------- #
def _made_swap(ledger, monkeypatch, lang="ja", old_here=False, home=MINING, deck=MINING):
    """A swap made as Connect makes it: its job's card in the ledger (`made`, with its batch's deck: its home) and in
    the library's made-words record (the runner's own write) — the records Tidy's guarantee asks of a card Surasura
    made (Kyou-SH3, Kyou-SH4). `old_here`: the old card is Connect's too, made from the episode the swap's line comes
    from. `home`: the deck on record (None: none, a lost or empty mapping deck); `deck`: where Anki has the card."""
    word, _old, other = CASES[lang]
    c.library(lang)
    _lists(lang)
    _queued(lang, word)
    with c.store(lang) as s:
        item = s.ids("now")[0]
        if old_here:                # the old card Connect made from this same episode, recorded for the word there
            library.record_batch(s, item, {word: [900]}, "2026-11-21T10:00:00Z", batch="t-1")
    if old_here:
        job = ledger.queue(lang, item, "user", None, store_id="s1")
        ledger.end_batch(job, 1, "done", [{"word": word, "reading": "", "outcome": "made", "note_id": 900,
                                           "sentence": _old}], deck=MINING)
        ledger.set_state(job, "done")
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: (item, other))
    anki = _old_card(Anki(), lang)
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    row = swap._rows(ledger, "1 = 1")[0]
    tag = "surasura::connect::" + ledger.tag_id(row["job_id"])
    _make_the_job(ledger, row, record=True, deck=home)
    done_at = calendar.timegm(time.strptime(ledger.job_by_id(row["job_id"])["updated_at"], "%Y-%m-%dT%H:%M:%SZ"))
    anki.add(950, tag, word, done_at - 60, deck=deck, sound="swap-new.mp3")      # untouched since its job made it
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    return anki, row["id"]


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_undo_deletes_the_new_card_with_a_backup_and_puts_the_old_one_back_to_study(ledger, lang, monkeypatch):
    anki, swap_id = _made_swap(ledger, monkeypatch, lang)
    got = swap.undo(anki, ledger, lang, swap_id, open_store=_opener(lang))
    assert got["undone"] and anki.deleted == [950]
    folder = [r for r in ledger.conn.execute("SELECT folder, why FROM tidies")][0]
    assert folder[1] == "swap" and os.path.isfile(os.path.join(folder[0], "cards.apkg"))
    old = anki.cards_[9000]
    assert (old["queue"], old["flags"]) == (0, 0) and swap.SWAP_TAG not in anki.notes_[900]["tags"]
    assert status._tidied(ledger.conn, lang) is None                  # a swap's Undo isn't a tidy
    with pytest.raises(swap.tidy.Refused) as twice:
        swap.undo(anki, ledger, lang, swap_id, open_store=_opener(lang))
    assert twice.value.say == swap.ALREADY and anki.deleted == [950]


def test_a_new_card_you_studied_stays_and_undo_changes_nothing(ledger, monkeypatch):
    anki, swap_id = _made_swap(ledger, monkeypatch)
    anki.cards_[9500].update(reps=2, type=2, queue=2)
    with pytest.raises(swap.tidy.Refused) as kept:
        swap.undo(anki, ledger, "ja", swap_id, open_store=_opener("ja"))
    assert kept.value.say == swap.KEPT and anki.deleted == []
    assert anki.cards_[9000]["queue"] == -1 and _row(ledger, swap_id)["state"] == swap.MADE


# --------------------------------------------------------------------------- #
# Undo and where the new card is (Kyou-SH4: Tidy takes a card only where Surasura put it)
# --------------------------------------------------------------------------- #
def _undone(anki, ledger, swap_id):
    old = anki.cards_[9000]
    assert anki.deleted == [950] and _row(ledger, swap_id)["state"] == swap.UNDONE
    assert (old["queue"], old["flags"]) == (0, 0), "the old card back in reviews, its green flag off"
    assert swap.SWAP_TAG not in anki.notes_[900]["tags"]


def _unchanged(anki, ledger, swap_id):
    old = anki.cards_[9000]
    assert anki.deleted == [] and _row(ledger, swap_id)["state"] == swap.MADE
    assert (old["queue"], old["flags"]) == (-1, 3) and swap.SWAP_TAG in anki.notes_[900]["tags"], \
        "a refused Undo leaves the old card as it was"


@pytest.mark.parametrize("lang", ["ja", "zh"])
@pytest.mark.parametrize("home, deck", [(MINING, MINING), (None, SHOWN)], ids=["its-home", "no-home-in-surasuras-deck"])
def test_undo_takes_back_a_swaps_card_in_its_home_or_with_no_home_in_surasuras_deck(ledger, lang, home, deck,
                                                                                    monkeypatch):
    # Why: Undo removes the new card only through Tidy (ROLES row 81), and Tidy takes a card only where Surasura put
    # it: the deck its batch recorded (its home), or — no home on record (a lost or empty mapping deck) — the deck
    # Surasura shows for new cards, handed in as an ordinary tidy hands it. Without that deck a swap's card with no
    # home could never be undone (train 62's join).
    anki, swap_id = _made_swap(ledger, monkeypatch, lang, home=home, deck=deck)
    assert ledger.homes([950]) == ({950: home} if home else {})
    assert swap.undo(anki, ledger, lang, swap_id, open_store=_opener(lang), ours=SHOWN)["undone"]
    _undone(anki, ledger, swap_id)


@pytest.mark.parametrize("lang", ["ja", "zh"])
@pytest.mark.parametrize("home, moved_to", [(None, None), (MINING, "自分の単語")], ids=["no-home-elsewhere", "moved-by-you"])
def test_undo_refuses_a_swaps_card_outside_surasuras_decks_with_the_words_undo_has(ledger, lang, home, moved_to,
                                                                                  monkeypatch):
    # Why: Sonic's 56 c — Undo is refused once you have studied or changed the new card, and moving it to a deck of
    # your own is changing it (Kyou-SH4's MOVED); with no home on record and outside Surasura's deck Tidy can't tell
    # whose it is: kept, never a guess. Refused with Undo's own words, and nothing changes.
    anki, swap_id = _made_swap(ledger, monkeypatch, lang, home=home)       # made in MINING; ours below is SHOWN
    if moved_to:
        anki.cards_[9500]["deckName"] = moved_to
    with pytest.raises(swap.tidy.Refused) as kept:
        swap.undo(anki, ledger, lang, swap_id, open_store=_opener(lang), ours=SHOWN)
    assert kept.value.say == swap.KEPT == "The new card stays: you've studied or changed it."
    _unchanged(anki, ledger, swap_id)


def test_the_windows_undo_hands_tidy_the_deck_settings_show_through_the_same_function_an_ordinary_tidy_uses(
        ledger, monkeypatch):
    # Why: *Undo* on Needs you (`act_undo`) reads Surasura's deck as Connect's tidy does (`fields.surasura_deck` on
    # the settings: Settings' *New cards a day* deck) — no second rule of its own.
    anki, swap_id = _made_swap(ledger, monkeypatch, "ja", home=None, deck=SHOWN)
    monkeypatch.setattr(swap, "AnkiSwap", lambda url: anki)
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    assert swap.act_undo({}, "ja", swap_id) == {"why": swap.KEPT}, "no deck shown: Anki Miner's own, no home: kept"
    _unchanged(anki, ledger, swap_id)
    assert swap.act_undo({"junban_deck": SHOWN, "junban_scope": "deck"}, "ja", swap_id)["undone"]
    _undone(anki, ledger, swap_id)


@pytest.mark.parametrize("lang", ["ja", "zh"])
@pytest.mark.parametrize("old_flag, left", [(4, 0), (3, 3)], ids=["the-swap-flag-off", "a-green-flag-of-your-own-stays"])
def test_the_windows_undo_takes_off_the_swap_flag_you_picked_and_only_that_one(ledger, lang, old_flag, left,
                                                                                monkeypatch):
    # Why: since Mado-LT the Swap move's flag is the learner's pick on Settings' move cards (`review_loop.move_flags`),
    # not always green. A card still carrying it is never known (`known_signal.not_known_flags`), so an Undo that only
    # cleared green would leave a Blue-Swap learner's old card unknowable; a green flag that isn't the Swap move's is
    # the learner's own and stays.
    anki, swap_id = _made_swap(ledger, monkeypatch, lang, home=None, deck=SHOWN)
    anki.cards_[9000]["flags"] = old_flag
    monkeypatch.setattr(swap, "AnkiSwap", lambda url: anki)
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    got = swap.act_undo({"junban_deck": SHOWN, "junban_scope": "deck", "loop_swap_flag": 4}, lang, swap_id)
    assert got["undone"] and anki.deleted == [950]
    assert (anki.cards_[9000]["queue"], anki.cards_[9000]["flags"]) == (0, left)


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_swapped_card_is_in_both_of_surasuras_records_and_tidys_guarantee_takes_it_as_its_own(ledger, lang,
                                                                                                 monkeypatch):
    # Why: Undo deletes the new card only through Tidy's guarantee (Kyou-SH3), which takes a card as Surasura's only
    # when the library's made-words record AND Connect's ledger both made it — a tag alone never. A swap's card is made
    # by a Connect job like any other: both records must hold it, or Undo can never take back a swap.
    anki, swap_id = _made_swap(ledger, monkeypatch, lang)
    assert tidy._made_notes(_opener(lang), [950, 900]) == {950}, "the made-words record holds the new card"
    assert tidy._done_at(ledger, 950) is not None, "Connect's ledger made it: its job ended"
    go, kept, _infos, _cards = tidy.check(anki, ledger, [950, 900], tidy._made_notes(_opener(lang), [950, 900]))
    assert go == [950], "the guarantee takes the swap's new card as Surasura's own, never studied, unchanged"
    assert kept == [[900, tidy.NOT_MADE]], "the old card is never Tidy's (here: Connect didn't make it)"
    # the guarantee isn't loosened for a swap: without the made-words record (no store) the new card stays
    with pytest.raises(swap.tidy.Refused) as refused:
        swap.undo(anki, ledger, lang, swap_id, open_store=lambda: None)
    assert refused.value.say == swap.KEPT and anki.deleted == [] and _row(ledger, swap_id)["state"] == swap.MADE
    assert anki.cards_[9000]["queue"] == -1, "a refused Undo leaves the old card as it was"
    assert swap.undo(anki, ledger, lang, swap_id, open_store=_opener(lang))["undone"] and anki.deleted == [950]


def _connect_card(ledger, anki, lang, note=960, word=None):
    """An ordinary Connect card beside the swap's: its own job made it in the deck it records (the runner's steps:
    the batch's end with its deck, the made-words record, done), never studied, untouched since."""
    from app.connect import runner
    word = word or {"ja": "本", "zh": "夜市"}[lang]
    with c.store(lang) as s:
        item = s.ids("now")[-1]                     # another episode than the swap's (one job an item)
    job = ledger.queue(lang, item, "user", None, store_id="s1")
    assert job is not None
    ledger.end_batch(job, 1, "done", [{"word": word, "reading": "", "outcome": "made", "note_id": note}], deck=MINING)
    runner._record_made(runner.Steps({}), ledger, lang, ledger.job_by_id(job), True)
    ledger.set_state(job, "done")
    done_at = calendar.timegm(time.strptime(ledger.job_by_id(job)["updated_at"], "%Y-%m-%dT%H:%M:%SZ"))
    anki.add(note, "surasura::connect::" + ledger.tag_id(job), word, done_at - 60, sound=f"plain-{note}.mp3")
    return note


@pytest.mark.parametrize("lang", ["ja", "zh"])
@pytest.mark.parametrize("why", [tidy.AUTO, tidy.NOW])
def test_an_ordinary_tidy_never_deletes_a_swaps_new_card_you_asked_for_and_the_swaps_undo_still_does(
        ledger, lang, why, monkeypatch):
    # Why (OPEN 56 g, PROVISIONAL): your ⇄ asked for the swap's new card — it is never held by the cap (56 f), so it
    # must never be tidied for being past the cap either: the old card stays suspended, and a tidied new card left the
    # word with no card in reviews until someone pressed Undo. It is Tidy's rule (`tidy.asked_for`, the clause ASKED):
    # an ordinary Connect card beside it still goes, the old card is never touched, and only the swap's own Undo
    # (why "swap") takes the new card back.
    anki, swap_id = _made_swap(ledger, monkeypatch, lang, old_here=True)     # the old card Connect's own too
    plain = _connect_card(ledger, anki, lang)
    assert tidy.asked_for(ledger, lang, [950, 900, plain]) == {950}, "the swap's new card only"
    assert tidy.asked_for(ledger, lang, [950], swap.BY_SWAP) == frozenset(), "not in the swap's own Undo"
    assert tidy.asked_for(ledger, "zh" if lang == "ja" else "ja", [950]) == frozenset(), "one language's swaps"
    done = tidy.run(anki, ledger, lang, [950, 900, plain], why=why, open_store=_opener(lang))
    assert done["deleted"] == [plain], "an ordinary Connect card beside it still goes"
    assert dict(done["kept"])[950] == tidy.ASKED and dict(done["kept"])[900] != tidy.NOT_MADE
    with pytest.raises(tidy.Refused) as alone:                                 # past the cap, never studied: kept
        tidy.run(anki, ledger, lang, [950], why=why, open_store=_opener(lang))
    assert alone.value.say == tidy.ALL_KEPT and 950 not in anki.deleted
    old = anki.cards_[9000]
    assert (old["queue"], old["flags"]) == (-1, 3) and swap.SWAP_TAG in anki.notes_[900]["tags"], \
        "the old card stays suspended, green and tagged: Tidy never changes it"
    assert swap.undo(anki, ledger, lang, swap_id, open_store=_opener(lang))["undone"]
    assert anki.deleted == [plain, 950], "the swap's Undo takes its new card back"
    assert (anki.cards_[9000]["queue"], anki.cards_[9000]["flags"]) == (0, 0), "the old card back in reviews"
    assert tidy.asked_for(ledger, lang, [950]) == frozenset(), "an undone swap asks for nothing"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_connects_own_tidy_past_the_cap_reads_on_past_a_swaps_new_card_and_takes_the_next_one(ledger, lang,
                                                                                               monkeypatch):
    # Why: the swap's card is one of Connect's own in the count (one out, one in), so Connect's look may choose it
    # past the cap; Tidy keeps it (ASKED) and reads the next candidate instead (`candidates`: a kept one is skipped),
    # so the pile still shrinks by what is past the cap.
    anki, _swap_id = _made_swap(ledger, monkeypatch, lang)
    plain = _connect_card(ledger, anki, lang)
    done = tidy.run(anki, ledger, lang, [950, plain], why=tidy.AUTO, open_store=_opener(lang), limit=1)
    assert done["deleted"] == [plain] and dict(done["kept"]) == {950: tidy.ASKED}


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_swap_from_its_old_cards_own_episode_adds_its_note_to_the_words_record_and_undo_takes_back_only_that(
        ledger, lang, monkeypatch):
    # Why: the made-words record has one row per episode and word. When the swap's other line is in the episode its old
    # card came from, the row already exists: the new note must be added to it (else Tidy never takes the swap's card
    # back), and Undo must take out only the new note — the old card's record stays, so the word is never made again.
    word = CASES[lang][0]
    anki, swap_id = _made_swap(ledger, monkeypatch, lang, old_here=True)
    with c.store(lang) as s:
        item = s.ids("now")[0]
        assert s.made(item)[word] == [900, 950]
    assert swap.undo(anki, ledger, lang, swap_id, open_store=_opener(lang))["undone"] and anki.deleted == [950]
    with c.store(lang) as s:
        assert s.made(item)[word] == [900], "the old card's record stays: the word isn't free to make again"


def test_the_window_says_each_swap_with_undo_and_ok(ledger, monkeypatch):
    _anki, swap_id = _made_swap(ledger, monkeypatch)
    record = swap.status_of(ledger.conn, "ja")
    entries = needs._swap_entries({"swaps": record}, frozenset())
    assert [(e.kind, e.actions, e.data["id"]) for e in entries] == [(needs.SWAPPED, ("undo_swap", "leave_swap"),
                                                                     swap_id)]
    assert CASES["ja"][0] in entries[0].title


# --------------------------------------------------------------------------- #
# The line: only the one picker's (Generate's list is the one source of a word's sentences)
# --------------------------------------------------------------------------- #
def test_choose_line_never_reads_the_library_itself_and_waits_without_the_picker(monkeypatch):
    # Why: a sentence Swap found by its own search could be one the journey never showed; without the picker: None.
    from app import sentence_corpus, token_index
    for name in ("library_files", "files_holding", "best_for", "collect"):
        monkeypatch.setattr(sentence_corpus, name, lambda *a, **k: pytest.fail("Swap searched the library itself"))
    monkeypatch.setattr(token_index, "open_store", lambda *a, **k: pytest.fail("Swap read the token store itself"))
    monkeypatch.setattr(swap, "_picker", lambda: None)
    word, old, _other = CASES["ja"]
    assert swap.choose_line("ja", word, [old]) is None


# --------------------------------------------------------------------------- #
# The runner: a swap job makes no receipt
# --------------------------------------------------------------------------- #
def test_a_swap_job_writes_its_cards_but_no_receipt_and_an_empty_one_none_either(tmp_path, monkeypatch):
    # Why: a receipt (mined_at) says "this episode was mined"; a swap's one word from another line is not that episode's
    # mining — a receipt there would hide the episode's own words from Connect (as a level job's would).
    from app.connect import runner
    from tests.connect.fake_steps import FakeSteps

    class SwapSteps(FakeSteps):
        def pick(self, lang, job, video):        # a swap job names its one word, as `verbs.pick` reads it for the job
            if job.get("kind") == SWAP:              # item 2: its only line is the old card's (nothing to make)
                job = dict(job, kind="level", words=[] if job["item_id"] == 2 else job["words"])
            return super().pick(lang, job, video)

    monkeypatch.setattr(runner, "_swap_look", lambda *a, **k: None)     # the swap queue isn't this test's
    steps = SwapSteps(str(tmp_path), {"line": {"ja": [1, 2, 3]}, "queue": {"ja": [3]}})
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        with ledger.transaction():
            made = ledger.queue_swap("ja", 1, "上層部", "ジョウソウブ", "2026-11-19T10:00:00", store_id="store-1")
            empty = ledger.queue_swap("ja", 2, "雰囲気", "フンイキ", "2026-11-19T10:00:01", store_id="store-1")
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=2)
        jobs = {j["id"]: j for j in ledger.jobs("ja")}
    by_item = {item: (cards, receipt) for item, cards, receipt in steps.records}
    assert jobs[made]["state"] == "done" and jobs[empty]["state"] == "done", jobs
    assert set(by_item[1][0]) == {"上層部"}, "the swap's one word is made and written to the store"
    assert by_item[1][1] is False, "a swap job's cards are written with no receipt"
    assert by_item[2] == ({}, False), "a swap job with nothing to make writes no receipt either"
    assert by_item[3][1] is True, "an ordinary job beside them still writes its receipt"


# --------------------------------------------------------------------------- #
# The review's fixes (Kantan-SL 2)
# --------------------------------------------------------------------------- #
def _sentence_card(anki, note, word, line, card=None):
    """An old card Connect didn't make: its line only in Anki's Sentence field."""
    _old_card(anki, "ja", note, word)
    anki.notes_[note]["fields"]["Sentence"] = {"value": line, "order": 2}
    return anki


def test_an_old_cards_line_anki_cant_read_now_waits_never_a_job_with_nothing_to_avoid(ledger, monkeypatch):
    # Why: a card Connect didn't make has its line only in Anki; with Anki closed at the first look, an empty `avoid`
    # kept for good would let the new card be cut from the very line the learner wanted gone.
    lang, (word, old, other) = "ja", CASES["ja"]
    _lists(lang)
    _queued(lang, word)
    asked = []
    monkeypatch.setattr(swap, "choose_line", lambda l, w, avoid, *a, **k: asked.append(list(avoid)) or (7, other))
    anki = _sentence_card(Anki(), 900, word, old)

    def closed(_ids):
        raise OSError("Anki closed")
    anki.notes, opened = closed, anki.notes
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    assert swap._rows(ledger, "1 = 1")[0]["state"] == swap.ASKED and asked == [] and not ledger.jobs(lang)
    anki.notes = opened
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    row = swap._rows(ledger, "1 = 1")[0]
    assert row["state"] == swap.QUEUED and asked == [[old]] and json.loads(row["avoid"]) == [old]


def test_two_greens_from_two_old_cards_avoid_both_lines_and_a_later_one_on_its_own_line_gets_its_own(ledger,
                                                                                                    monkeypatch):
    # Why: one new card serves every green of a word, so it must avoid every one of their old lines, not the first's.
    lang = "ja"
    read = cues.read(JA, lang)
    word = CASES[lang][0]
    lines = [c.text for c in read if "借り" in (c.text or "")][:2]
    lines.append(next(c.text for c in read if c.text and "借り" not in c.text and len(c.text) > 6))   # the job's line
    _lists(lang)
    anki = _sentence_card(_sentence_card(Anki(), 900, word, lines[0]), 910, word, lines[1])
    first, second = _queued(lang, word, card=9000, note=900), _queued(lang, word, card=9100, note=910)
    asked = []
    monkeypatch.setattr(swap, "choose_line", lambda l, w, avoid, *a, **k: asked.append(list(avoid)) or (7, lines[2]))
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    assert asked == [[lines[0], lines[1]]]
    row = swap._rows(ledger, "state = ?", (swap.QUEUED,))[0]
    assert json.loads(row["avoid"]) == [lines[0], lines[1]]
    # a third green, asked while the job ran, whose old card holds the very line the job cut: not that card's swap
    _sentence_card(anki, 920, word, lines[2])
    third = _queued(lang, word, card=9200, note=920)
    swap.make_card(lang, word, old_note=920, old_card=9200, ref=third["id"], ledger=ledger, wake=False,
                   state_of=lambda w, r="": None)
    _make_the_job(ledger, row)
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    by_ref = {r["ref"]: r for r in swap._rows(ledger, "1 = 1")}
    assert by_ref[first["id"]]["state"] == by_ref[second["id"]]["state"] == swap.MADE
    assert by_ref[third["id"]]["state"] != swap.MADE and by_ref[third["id"]]["new_note"] is None


def test_greens_on_one_spelling_with_two_readings_are_two_swaps(ledger, monkeypatch):
    # Why: 生 read なま and 生 read せい are two words; one's new card must never be called the other's.
    a = {"word": "生", "reading": "ナマ"}
    assert swap._same_word(a, {"word": "生", "reading": "ナマ"}) and swap._same_word(a, {"word": "生", "reading": ""})
    assert not swap._same_word(a, {"word": "生", "reading": "セイ"})


def test_a_swap_job_with_no_swap_record_sends_nothing(ledger, monkeypatch):
    # Why: a job of kind swap read as an ordinary pick would mine the episode's whole list, with no receipt.
    from app.connect import ledger as ledger_mod
    with ledger.transaction():
        job = ledger.queue_swap("ja", 7, "借りる", "", "2026-11-20T01:00:00Z")
    swap.ensure(ledger)
    assert ledger_mod.path() and swap.spec_of(job, "ja") == {"word": "", "reading": "", "avoid": [], "line": None}
    read, tokens = _read("ja")
    spec = swap.spec_of(job, "ja")
    assert pick.pick(read, tokens, "ja", lambda key: False, mode="unknown", listed={}, carded=set(), swap=spec)["words"] == []


def test_a_queue_entry_whose_write_failed_is_put_in_step_at_the_next_look(ledger, monkeypatch):
    # Why: the swap queue file busy at the moment a card is made must not leave the learner's entry waiting for good.
    lang, (word, _old, other) = "ja", CASES["ja"]
    _lists(lang)
    entry = _queued(lang, word)
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: (7, other))
    anki = _old_card(Anki(), lang)
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    _make_the_job(ledger, swap._rows(ledger, "1 = 1")[0])
    real = swap_queue.made

    def busy(*a, **k):
        raise OSError("the swap queue is busy")
    monkeypatch.setattr(swap_queue, "made", busy)
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    assert [e["state"] for e in swap_queue.load(lang) if e["id"] == entry["id"]] == ["waiting"]
    monkeypatch.setattr(swap_queue, "made", real)
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    got = [e for e in swap_queue.load(lang) if e["id"] == entry["id"]][0]
    assert got["state"] == "made" and got["made"]["note"] == 950


def test_undo_after_you_deleted_the_new_card_puts_the_old_one_back_and_deletes_nothing(ledger, monkeypatch):
    # Why: a new card already gone is nothing to delete; Undo must still give the learner their old card back.
    anki, swap_id = _made_swap(ledger, monkeypatch)
    del anki.notes_[950]
    got = swap.undo(anki, ledger, "ja", swap_id, open_store=_opener("ja"))
    assert got["undone"] and anki.deleted == []
    assert (anki.cards_[9000]["queue"], anki.cards_[9000]["flags"]) == (0, 0)
    assert swap.SWAP_TAG not in anki.notes_[900]["tags"] and _row(ledger, swap_id)["state"] == swap.UNDONE


def test_undo_of_one_card_of_a_note_keeps_the_tag_its_other_swapped_card_still_needs(ledger, monkeypatch):
    # Why: the tag is the note's; the note's other card is still swapped (suspended, its new card made).
    anki, swap_id = _made_swap(ledger, monkeypatch)
    with ledger.transaction():
        ledger.conn.execute("INSERT INTO swaps (language, word, reading, old_note, old_card, by, state, new_note, "
                            "tagged, at, updated_at) SELECT language, word, reading, old_note, 9001, by, state, 951, "
                            "1, at, updated_at FROM swaps WHERE id = ?", (swap_id,))
    swap.undo(anki, ledger, "ja", swap_id, open_store=_opener("ja"))
    assert swap.SWAP_TAG in anki.notes_[900]["tags"] and anki.cards_[9000]["queue"] == 0


def test_a_swap_undone_while_the_look_waited_for_anki_is_never_tagged_again(ledger, monkeypatch):
    # Why: the look reads the swaps to tag, then waits for Anki's write lock that Undo holds; it must read them again.
    lang, (word, _old, other) = "ja", CASES["ja"]
    _lists(lang)
    _queued(lang, word)
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: (7, other))
    anki = _old_card(Anki(), lang)
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    row = swap._rows(ledger, "1 = 1")[0]
    _make_the_job(ledger, row)
    anki.busy = True                                    # you review: the tag waits
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    anki.busy = False
    import contextlib

    @contextlib.contextmanager
    def held(verb):                                     # Undo finished while this look waited on the lock
        swap._set(ledger, row["id"], state=swap.UNDONE)
        yield
    anki.writer = held
    swap._tag_waiting(ledger, lang, anki)
    assert swap.SWAP_TAG not in anki.notes_[900]["tags"]


def test_same_line_reads_past_colons_dashes_and_slashes():
    assert sentences.same_line("先生：借りてもいいですか", ["先生:借りてもいいですか"])
    assert sentences.same_line("A-借りたい/です", ["A借りたいです"])


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_with_the_sentence_picker_there_choose_line_takes_its_best_line_never_the_old_one(lang, monkeypatch):
    # Why: Kantan-SD's one picker (the sentence dial) chooses a word's sentence for every maker; Swap hands it the old
    # card's lines as `never` and what Connect can cut as `reach`, and still refuses the old line itself.
    import types
    from collections import namedtuple
    from app import sentence_corpus, token_index
    word, old, other = CASES[lang]
    Choice = namedtuple("Choice", "file item_id text others weight here audio")
    asked = []

    def choose(language, keys, *, never=None, reach=None, files=None, **kw):
        asked.append((language, list(keys), never, files))
        ranked = [Choice("a.srt", 1, old, 0, 1.0, False, True),          # the picker missed the old line: Swap won't
                  Choice("b.srt", 2, other + "!", 0, 0.9, False, True),  # an episode Connect can't cut
                  Choice("c.srt", 3, other, 0, 0.5, False, True)]
        return {k: [c for c in ranked if reach(c.item_id)] for k in keys}
    monkeypatch.setattr(swap, "_picker", lambda: types.SimpleNamespace(choose=choose))     # the one seam
    for name in ("library_files", "files_holding", "best_for", "collect"):
        monkeypatch.setattr(sentence_corpus, name, lambda *a, **k: pytest.fail("the picker ranks, not Swap"))
    monkeypatch.setattr(token_index, "open_store", lambda *a, **k: pytest.fail("the picker reads, not Swap"))
    assert swap.choose_line(lang, word, [old], reachable=lambda item: item != 2) == (3, other)
    assert asked == [(lang, [(word, "")], {(word, ""): {old}}, None)]
    assert swap.choose_line(lang, word, [old], reachable=lambda item: True, skip_items=[2]) == (3, other)

    def broken(*a, **k):
        raise RuntimeError("the picker failed")
    monkeypatch.setattr(swap, "_picker", lambda: types.SimpleNamespace(choose=broken))
    assert swap.choose_line(lang, word, [old]) is None                 # the picker failed: the swap waits


# --------------------------------------------------------------------------- #
# Each layer's own Known / Ignored check, and the picked line (mutants M8-M11, M18)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_maker_itself_drops_a_known_or_ignored_word_at_once(ledger, lang):
    # Why: Kyou-DW's *Bad card* and the journey's ⇄ call the maker directly; they must hear "known" / "ignored" at
    # once, with nothing asked, not a look later.
    word = CASES[lang][0]
    _lists(lang, known=[word])
    got = swap.make_card(lang, word, old_note=900, ledger=ledger, wake=False)
    assert (got["state"], got["why"]) == (swap.DROPPED, "known")
    _lists(lang, ignored=[word])
    got = swap.make_card(lang, word, old_note=901, ledger=ledger, wake=False)
    assert (got["state"], got["why"]) == (swap.DROPPED, "ignored")
    assert not swap._rows(ledger, "state = ?", (swap.ASKED,))


def test_an_ask_whose_word_became_known_before_its_job_is_dropped_when_it_starts(ledger, monkeypatch):
    # Why: an ask recorded while the word was new, then known before Connect's look: no job, the entry dropped.
    lang, (word, _old, other) = "ja", CASES["ja"]
    _lists(lang)
    got = swap.make_card(lang, word, old_note=900, ledger=ledger, wake=False)
    assert got["state"] == swap.ASKED
    _lists(lang, known=[word])
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: pytest.fail("no line for a known word"))
    swap.look(Steps(), ledger, lang, anki=Anki(), files=5)
    assert (_row(ledger, got["id"])["state"], _row(ledger, got["id"])["why"]) == (swap.DROPPED, "known")
    assert not ledger.jobs(lang)


def test_a_word_known_while_its_last_try_ran_is_dropped_not_left_waiting(ledger, monkeypatch):
    # Why: on its third episode an ask would wait 6 h; a word known meanwhile is dropped at the job's end instead.
    lang, (word, _old, other) = "ja", CASES["ja"]
    _lists(lang)
    entry = _queued(lang, word)
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: (7, other))
    swap.look(Steps(), ledger, lang, anki=Anki(), files=5)
    row = swap._rows(ledger, "1 = 1")[0]
    swap._set(ledger, row["id"], tried=json.dumps([5, 6]))           # two episodes tried before this one
    ledger.set_state(row["job_id"], "done")                          # nothing made
    _lists(lang, known=[word])
    swap.look(Steps(), ledger, lang, anki=Anki(), files=5)
    assert (_row(ledger, row["id"])["state"], _row(ledger, row["id"])["why"]) == (swap.DROPPED, "known")
    assert [e["why"] for e in swap_queue.load(lang) if e["id"] == entry["id"]] == ["known"]


def test_a_picked_line_that_is_the_old_cards_own_is_never_the_line(ledger, monkeypatch):
    # Why: the journey's ⇄ may hand the very line the learner swapped away from; Swap picks another itself.
    lang, (word, old, other) = "ja", CASES["ja"]
    _lists(lang)
    anki = _sentence_card(Anki(), 900, word, old)
    _queued(lang, word, line_id="3:1000")
    asked = []                              # the word the line is found by (two lines at one start: E-JOURNEY)
    monkeypatch.setattr(swap, "_resolve_line_id", lambda steps, l, text, word=None: asked.append(word) or (3, old))
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: (8, other))
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    row = swap._rows(ledger, "1 = 1")[0]
    assert (row["state"], row["item_id"], row["line"]) == (swap.QUEUED, 8, other)
    assert asked == [word]


def test_no_anki_to_read_an_old_cards_line_from_waits_too(ledger, monkeypatch):
    # Why: Connect with no Anki address can't read a card it didn't make: the ask waits, never a job blind.
    lang, (word, _old, other) = "ja", CASES["ja"]
    _lists(lang)
    _queued(lang, word)
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: pytest.fail("no line without the old one"))
    swap.look(Steps(), ledger, lang, anki=None, files=5)
    assert swap._rows(ledger, "1 = 1")[0]["state"] == swap.ASKED and not ledger.jobs(lang)


# --------------------------------------------------------------------------- #
# One record: the swap queue's entry; the ledger's row never says another outcome
# --------------------------------------------------------------------------- #
_OUTCOME = {swap.MADE: "made", swap.DROPPED: "dropped", swap.UNDONE: "undone"}


def _agree(ledger, lang):
    """Every swap with a queue entry: an outcome in the ledger is the queue's (and its why); a phase (asked, queued,
    waits) is the queue's *waiting*. -> {ref: the queue's state} for the test to read."""
    entries = {e["id"]: e for e in swap_queue.load(lang)}
    seen = {}
    for row in swap._rows(ledger, "language = ? AND ref IS NOT NULL", (lang,)):
        e = entries[row["ref"]]
        assert e["state"] == _OUTCOME.get(row["state"], "waiting"), (row["state"], e["state"])
        if row["state"] == swap.DROPPED:
            assert row["why"] == e["why"]
        seen[row["ref"]] = e["state"]
    return seen


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_after_an_undo_the_queue_and_the_ledger_both_say_undone_and_the_window_offers_no_undo(ledger, lang,
                                                                                               monkeypatch):
    # Why: the queue is the one record of a swap (the full Swap reads it); an Undo the queue never heard of left it
    # saying *made* for a card that is gone.
    anki, swap_id = _made_swap(ledger, monkeypatch, lang)
    ref = _row(ledger, swap_id)["ref"]
    assert _agree(ledger, lang) == {ref: "made"}
    swap.undo(anki, ledger, lang, swap_id, open_store=_opener(lang))
    assert _agree(ledger, lang) == {ref: "undone"}
    entry = [e for e in swap_queue.load(lang) if e["id"] == ref][0]
    assert entry["made"]["note"] == 950 and entry["undone"]            # the record kept, never deleted
    assert swap.status_of(ledger.conn, lang)["made"] == []
    swap.look(Steps(), ledger, lang, anki=anki, files=5)                # a later look changes neither
    assert _agree(ledger, lang) == {ref: "undone"} and swap.SWAP_TAG not in anki.notes_[900]["tags"]


def test_an_undo_whose_queue_write_fails_changes_neither_record_and_a_retry_finishes_it(ledger, monkeypatch):
    # Why: an Undo stopped half-way (the queue busy: the known-words lock held) must never leave the two records apart;
    # the retry must not delete a second card nor lose the old one.
    anki, swap_id = _made_swap(ledger, monkeypatch)
    ref = _row(ledger, swap_id)["ref"]
    real = swap_queue.undone

    def busy(language, swap_id):
        raise RuntimeError("Your known words are being updated by Anki known-words sync.")
    monkeypatch.setattr(swap_queue, "undone", busy)
    with pytest.raises(RuntimeError):
        swap.undo(anki, ledger, "ja", swap_id, open_store=_opener("ja"))
    assert _agree(ledger, "ja") == {ref: "made"}                        # both still say made
    assert anki.deleted == [950] and anki.cards_[9000]["queue"] == 0    # the steps before it done, kept
    monkeypatch.setattr(swap_queue, "undone", real)
    assert swap.undo(anki, ledger, "ja", swap_id, open_store=_opener("ja"))["undone"]
    assert _agree(ledger, "ja") == {ref: "undone"} and anki.deleted == [950]


def test_an_undo_the_queue_took_but_the_ledger_lost_is_followed_and_never_tagged_again(ledger, monkeypatch):
    # Why: the queue's word wins — a ledger left saying made after the queue said undone would tag the old card again
    # and offer a second Undo.
    anki, swap_id = _made_swap(ledger, monkeypatch)
    row = _row(ledger, swap_id)
    swap._old_back(anki, row)                                           # the Undo's Anki steps
    swap_queue.undone("ja", row["ref"])                                 # the queue took it; the ledger's write lost
    swap._set(ledger, swap_id, tagged=0)
    swap.look(Steps(), ledger, "ja", anki=anki, files=5)
    assert _agree(ledger, "ja") == {row["ref"]: "undone"} and swap.SWAP_TAG not in anki.notes_[900]["tags"]
    with pytest.raises(swap.tidy.Refused) as again:
        swap.undo(anki, ledger, "ja", swap_id, open_store=_opener("ja"))
    assert again.value.say == swap.ALREADY


def test_an_undo_with_the_ledger_ahead_of_the_queue_is_told_to_the_queue_at_the_next_look(ledger, monkeypatch):
    # Why: a ledger row undone the queue never heard of (an Undo before the queue had *undone*) is put in step.
    anki, swap_id = _made_swap(ledger, monkeypatch)
    ref = _row(ledger, swap_id)["ref"]
    swap._set(ledger, swap_id, state=swap.UNDONE)
    swap.look(Steps(), ledger, "ja", anki=anki, files=5)
    assert _agree(ledger, "ja") == {ref: "undone"}


def test_a_swap_taken_back_before_its_job_is_dropped_with_the_queues_why_and_no_card_is_made(ledger, monkeypatch):
    # Why: the learner took the green flag off (the reader drops the entry "taken back"): Swap must not go on and make a
    # card from its own copy of the ask.
    lang, (word, _old, other) = "ja", CASES["ja"]
    _lists(lang)
    entry = _queued(lang, word)
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: None)     # no other line yet: the ask waits
    anki = _old_card(Anki(), lang)
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    assert _row(ledger, 1)["state"] == swap.WAITS and _agree(ledger, lang) == {entry["id"]: "waiting"}
    swap_queue.drop(lang, entry["id"], "taken back")
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: (7, other))
    swap.look(Steps(), ledger, lang, anki=anki, files=6)               # the library grew: it would have tried again
    row = _row(ledger, 1)
    assert (row["state"], row["why"], row["job_id"]) == (swap.DROPPED, "taken back", None)
    assert _agree(ledger, lang) == {entry["id"]: "dropped"}
    assert not ledger.jobs(lang)


# --------------------------------------------------------------------------- #
# The picker's answer for a listed word whose kept lines are all stale (Kantan-SD's refuter note, on the merged code)
# --------------------------------------------------------------------------- #
def test_a_listed_word_whose_kept_lines_all_changed_since_generate_waits_for_another_sentence_never_an_error(
        ledger, placed, monkeypatch):
    # Why: the picker gives a row of the list only the lines its Generate kept, and none from a file changed since
    # (it may no longer say them) — an empty answer, with no library search. For Swap that is "no other line yet":
    # the swap waits, said as *No other sentence for 「X」 yet*, and is looked at again later; never a failure, never
    # a card from a line that may be gone.
    monkeypatch.setattr(sentences, "_KEPT", {})
    word, reading = BOUKEN
    _lists("ja")
    here, there = _sd_write("ja", "第01話.srt", [HARD]), _sd_write("ja", "第02話.srt", ["……", EASY])
    _sd_place(placed, here, 1)
    _sd_place(placed, there, 2)
    _sd_plan("ja", [here, there], {BOUKEN: [(0, 0, HARD, 3), (1, 1, EASY, 0)]})
    _no_library_search(monkeypatch)
    assert swap.choose_line("ja", word, [TODAY], reading=reading) == (2, EASY), "fresh: the list's best kept line"
    for path in (here, there):
        with open(path, "a", encoding="utf-8") as f:
            f.write("冒険はもう終わった。\n")                  # edited after the Generate: another size, another time
    assert sentences.choose("ja", [BOUKEN], young={})[BOUKEN] == []
    anki = _sentence_card(Anki(), 900, word, TODAY)
    got = swap.make_card("ja", word, reading=reading, old_note=900, ledger=ledger, wake=False)
    assert got["state"] == swap.ASKED
    swap.look(Steps(), ledger, "ja", anki=anki, files=2)
    row = swap._rows(ledger, "1 = 1")[0]
    assert (row["state"], row["why"], row["job_id"]) == (swap.WAITS, swap.NO_LINE, None), "waits: no job, no card"
    entries = needs._swap_entries({"swaps": swap.status_of(ledger.conn, "ja")}, frozenset())
    assert [e.kind for e in entries] == [needs.SWAP_WAITS]
    assert entries[0].title == "No other sentence for 「冒険」 yet."


# --------------------------------------------------------------------------- #
# A listed word swapped from Anki: the review loop's queue carries no reading (the picker's match, `_row_of`)
# --------------------------------------------------------------------------- #
KYOU, KONNICHI = ("今日", "キョウ"), ("今日", "コンニチ")       # one spelling, two words
KYOU_LINES = ("今日は雨が降っている。", "今日から学校が始まる。")
KONNICHI_LINES = ("今日の日本では高齢化が進んでいる。", "今日に至るまで続いている伝統だ。")


def _searched(monkeypatch):
    """The library search's first step, noted (it finds nothing here): [the keys it was asked for]."""
    from app import sentence_corpus
    asked = []
    monkeypatch.setattr(sentence_corpus, "library_files", lambda language, *a, **k: asked.append(language) or [])
    return asked


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_listed_word_swapped_with_no_reading_reaches_the_lists_kept_lines_never_the_library_search(
        placed, lang, monkeypatch):
    # Why: a swap from the review loop's queue carries no reading; the list's rows are keyed (lemma, reading), so the
    # word missed its row and went to the slow library search and another pool. One row with that lemma is the word.
    if lang == "ja":
        key, lines, old = BOUKEN, [HARD, EASY], TODAY
    else:
        key, lines, old = ("电话", ""), ["那个陌生人打来的电话很奇怪。", "他接到电话了。"], "我刚才给妈妈打了电话。"
    _lists(lang)
    here, there = _sd_write(lang, "第01話.srt", [lines[0]]), _sd_write(lang, "第02話.srt", ["……", lines[1]])
    _sd_place(placed, here, 1)
    _sd_place(placed, there, 2)
    _sd_plan(lang, [here, there], {key: [(0, 0, lines[0], 3), (1, 1, lines[1], 0)]})
    _no_library_search(monkeypatch)
    no_reading = (key[0], "")
    got = sentences.choose(lang, [no_reading], dial=sentences.BEST, young={}, never={no_reading: {old}})
    assert [ch.text for ch in got[no_reading]] == [lines[1], lines[0]], "the row's kept lines, in Best's order"
    assert swap.choose_line(lang, key[0], [old]) == (2, lines[1]), "Swap's own ask, with no reading"
    assert swap.choose_line(lang, key[0], [lines[1]]) == (1, lines[0]), "never the old card's line"


def _homographs(placed):
    here, there = _sd_write("ja", "第01話.srt", list(KYOU_LINES)), _sd_write("ja", "第02話.srt", list(KONNICHI_LINES))
    _sd_place(placed, here, 1)
    _sd_place(placed, there, 2)
    _sd_plan("ja", [here, there], {KYOU: [(0, 0, KYOU_LINES[0], 1), (0, 1, KYOU_LINES[1], 1)],
                                   KONNICHI: [(1, 0, KONNICHI_LINES[0], 1), (1, 1, KONNICHI_LINES[1], 1)]})


@pytest.mark.parametrize("old, row", [(KONNICHI_LINES[0], KONNICHI), (KYOU_LINES[1], KYOU)],
                         ids=["konnichi", "kyou"])
def test_homographs_with_no_reading_take_the_row_whose_kept_lines_hold_the_old_cards_sentence(placed, old, row,
                                                                                              monkeypatch):
    # Why: 今日 is two words (きょう / こんにち), two rows of the list. A swap with no reading can't tell which — but its
    # old card's sentence was cut from one of them: the row whose kept lines hold it is the word (the Generate's own
    # reading of that line), and the new card gets that word's other line, never the other word's.
    _homographs(placed)
    _no_library_search(monkeypatch)
    key = ("今日", "")
    got = sentences.choose("ja", [key], dial=sentences.BEST, young={}, never={key: {old}})[key]
    want = KONNICHI_LINES if row == KONNICHI else KYOU_LINES
    assert [ch.text for ch in got] == [line for line in want if line != old]


@pytest.mark.parametrize("old", [None, "今日はいい天気ですね。", KYOU_LINES[0] + KONNICHI_LINES[0]],
                         ids=["no-old-line", "in-neither-row", "in-both-rows"])
def test_homographs_with_no_reading_and_no_telling_row_fall_back_to_the_library_search_as_before(placed, old,
                                                                                                 monkeypatch):
    # Why: with no old line to tell by (Bad card on a deleted card), or one neither row's kept lines hold, or one both
    # do, a guess could give the card the other word's sentence: the word is no row, as before this change — the
    # library search (here: it finds nothing).
    _homographs(placed)
    asked = _searched(monkeypatch)
    key = ("今日", "")
    got = sentences.choose("ja", [key], dial=sentences.BEST, young={}, never={key: {old}} if old else None)
    assert got == {key: []} and asked == ["ja"], "the library search, as for a word with no row"
    assert sentences.choose("ja", [KYOU], dial=sentences.BEST, young={})[KYOU], "a key with its reading: its row"
    other = ("今日", "ケフ")                        # a reading the list has no row for: another word, never a guess
    asked.clear()
    assert sentences.choose("ja", [other], dial=sentences.BEST, young={}, never={other: {KYOU_LINES[1]}}) ==         {other: []} and asked == ["ja"]


def test_a_key_with_no_reading_weighs_young_words_as_its_row_does_never_its_own_word(monkeypatch):
    # Why: matched to its row, a word with no reading must be ranked exactly as the row's own key is — the word itself
    # is never one of the young words a sentence practises (its own weight would lift every line it is in).
    from app import sentence_corpus as sc
    from app.path_utils import get_user_file
    known = sorted({"明日", "今日", "から", "に", "出掛ける", "出かける", "よう", "う"})
    first, second = _sd_write("ja", "第01話.txt", [EASY]), _sd_write("ja", "第02話.txt", [TODAY])
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
    assert key[1], "the row's key has its reading"
    _sd_plan("ja", [first, second], {key: [(0, 0, EASY, 0), (1, 0, TODAY, 0)]})
    for asked in (key, (key[0], "")):
        got = sentences.choose("ja", [asked], dial=sentences.BEST, young={"冒険": 1.0})[asked]
        assert [(ch.text, ch.weight) for ch in got] == [(EASY, 0.0), (TODAY, 0.0)], asked


def test_a_new_generates_plan_is_matched_by_its_own_rows_never_the_last_plans(placed, monkeypatch):
    # Why: the lemma's row is looked up in an index of the plan's rows; a new Generate numbers its rows anew, and an
    # index left from the last plan would hand the word another word's sentences.
    here, there = _sd_write("ja", "第01話.srt", [HARD]), _sd_write("ja", "第02話.srt", ["……", EASY])
    _sd_place(placed, here, 1)
    _sd_place(placed, there, 2)
    _no_library_search(monkeypatch)
    key = (BOUKEN[0], "")
    _sd_plan("ja", [here, there], {BOUKEN: [(0, 0, HARD, 3), (1, 1, EASY, 0)]})
    assert [ch.text for ch in sentences.choose("ja", [key], dial=sentences.BEST, young={})[key]] == [EASY, HARD]
    today = _sd_write("ja", "第03話.srt", [TODAY])
    _sd_place(placed, today, 3)
    _sd_plan("ja", [here, there, today], {KYOU: [(2, 0, TODAY, 0)], BOUKEN: [(0, 0, HARD, 3)]})    # 冒険: row 1 now
    assert [ch.text for ch in sentences.choose("ja", [key], dial=sentences.BEST, young={})[key]] == [HARD]
