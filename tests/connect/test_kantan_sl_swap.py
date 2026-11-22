"""Kantan-SL: Swap, the simple version (the review loop's ⇄ = Suspend + Green flag; ROLES.md's Swap: a new card from
another line; the full Swap, 3.1, rewrites the old card in place from the same record).

What each test holds still:
- **never the same line:** the new card is never cut from a line its old card holds (by the line's text: markup,
  furigana and punctuation aside, a line inside the old card's sentence counts as it); an episode that says the word
  only there gives no card (`same-line`), and the swap tries another episode, then waits;
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
from app.connect import inbox, pick, status, swap, swap_queue
from app.connect.ledger import OPEN, SWAP, Ledger
from app.services import needs
from tests import cli_helpers as h
from tests.connect.test_kyou_sh2_tidy import FakeAnki as TidyAnki

RESOURCES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Test Resources")
JA = os.path.join(RESOURCES, "ja", "library_episode.ass")
ZH = os.path.join(RESOURCES, "zh", "night_market.srt")
# The word, the old card's line, the other line the word is said in (both real lines of the files above)
CASES = {"ja": ("借りる", "すみません、この本を借りたいんですが。", "ペンを借りてもいいですか"),
         "zh": ("我们", "今天我们要去台北的夜市吃东西。", "我们先点一碗牛肉面")}


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
    assert other in got["words"][0]["line_text"] and not swap.same_line(got["words"][0]["line_text"], [old])


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_an_episode_saying_the_word_only_in_its_old_cards_lines_gives_no_card(lang):
    word, old, other = CASES[lang]
    got = _swap_pick(lang, [old, other])
    assert got["words"] == [] and [n["reason"] for n in got["not_offered"]] == ["same-line"]


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_known_or_ignored_word_is_never_sent_by_a_swap(lang):
    word, old, _other = CASES[lang]
    assert _swap_pick(lang, [old], known={word})["words"] == []


def test_the_old_cards_sentence_as_anki_holds_it_still_counts_as_its_line():
    # the card's Sentence field: bold, Anki's furigana brackets, a nbsp — the same line
    word, old, _other = CASES["ja"]
    field = "すみません、この<b>本</b>[ほん]を&nbsp;<b>借</b>[か]りたいんですが。"
    got = _swap_pick("ja", [field])
    assert got["words"] and not swap.same_line(got["words"][0]["line_text"], [old])


def test_the_line_the_learner_picked_wins_when_the_episode_says_it_there():
    # two other lines say 借りる; the learner's pick is the later one
    read = cues.read(JA, "ja")
    lines = [c.text for c in read if "借り" in (c.text or "")]
    assert len(lines) >= 2
    got = _swap_pick("ja", [], line=lines[-1])
    assert swap.same_line(got["words"][0]["line_text"], [lines[-1]])


def test_same_line_reads_text_not_markup_and_never_an_empty_line():
    assert swap.same_line("「借りたい」", ["借りたい"]) and swap.same_line("借りたい", ["本を<b>借りたい</b>んです"])
    assert not swap.same_line("返します", ["借りたい"])
    assert not swap.same_line("…", ["…"]) and not swap.same_line("あ", ["あいう"])


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


def _make_the_job(ledger, row, note=950, tag="surasura::connect::x"):
    """Connect's job for the swap ends having made `note` (what its steps would leave in the ledger)."""
    ledger.end_batch(row["job_id"], 1, "done", [{"word": row["word"], "reading": "", "outcome": "made",
                                                 "note_id": note}])
    ledger.set_state(row["job_id"], "done")


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
                     [{"word": word, "reading": "", "outcome": "made", "note_id": 900, "sentence": old}])
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
            ledger.set_state(row["job_id"], "done")             # its pick: `same-line`, no card
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
    job = ledger.queue_swap(lang, 7, "借りる", "", "2026-11-22T01:00:00Z", store_id="s1")
    assert ledger.ask(lang, 7, "2026-11-22T02:00:00Z") is None        # the ask waits for the swap's one word
    assert ledger.queue_swap(lang, 7, "返す", "", "2026-11-22T01:00:00Z") is None
    assert inbox.keeps(ledger.job_by_id(job)) is True
    inbox._asks(_NoStore(), lang, ledger, {}, [], [], [])          # no store ask holds it: it stays asked
    assert ledger.job_by_id(job)["asked_at"] and ledger.job_by_id(job)["state"] in OPEN


class _NoStore:
    def __getattr__(self, name):
        raise AssertionError(f"no store read expected ({name})")


# --------------------------------------------------------------------------- #
# Undo
# --------------------------------------------------------------------------- #
def _made_swap(ledger, monkeypatch, lang="ja"):
    word, _old, other = CASES[lang]
    _lists(lang)
    _queued(lang, word)
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: (7, other))
    anki = _old_card(Anki(), lang)
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    row = swap._rows(ledger, "1 = 1")[0]
    tag = "surasura::connect::" + ledger.tag_id(row["job_id"])
    _make_the_job(ledger, row)
    done_at = calendar.timegm(time.strptime(ledger.job_by_id(row["job_id"])["updated_at"], "%Y-%m-%dT%H:%M:%SZ"))
    anki.add(950, tag, word, done_at - 60, sound="swap-new.mp3")      # untouched since its job made it
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    return anki, row["id"]


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_undo_deletes_the_new_card_with_a_backup_and_puts_the_old_one_back_to_study(ledger, lang, monkeypatch):
    anki, swap_id = _made_swap(ledger, monkeypatch, lang)
    got = swap.undo(anki, ledger, lang, swap_id, open_store=lambda: None)
    assert got["undone"] and anki.deleted == [950]
    folder = [r for r in ledger.conn.execute("SELECT folder, why FROM tidies")][0]
    assert folder[1] == "swap" and os.path.isfile(os.path.join(folder[0], "cards.apkg"))
    old = anki.cards_[9000]
    assert (old["queue"], old["flags"]) == (0, 0) and swap.SWAP_TAG not in anki.notes_[900]["tags"]
    assert status._tidied(ledger.conn, lang) is None                  # a swap's Undo isn't a tidy
    with pytest.raises(swap.tidy.Refused) as twice:
        swap.undo(anki, ledger, lang, swap_id, open_store=lambda: None)
    assert twice.value.say == swap.ALREADY and anki.deleted == [950]


def test_a_new_card_you_studied_stays_and_undo_changes_nothing(ledger, monkeypatch):
    anki, swap_id = _made_swap(ledger, monkeypatch)
    anki.cards_[9500].update(reps=2, type=2, queue=2)
    with pytest.raises(swap.tidy.Refused) as kept:
        swap.undo(anki, ledger, "ja", swap_id, open_store=lambda: None)
    assert kept.value.say == swap.KEPT and anki.deleted == []
    assert anki.cards_[9000]["queue"] == -1 and _row(ledger, swap_id)["state"] == swap.MADE


def test_the_window_says_each_swap_with_undo_and_ok(ledger, monkeypatch):
    _anki, swap_id = _made_swap(ledger, monkeypatch)
    record = swap.status_of(ledger.conn, "ja")
    entries = needs._swap_entries({"swaps": record}, frozenset())
    assert [(e.kind, e.actions, e.data["id"]) for e in entries] == [(needs.SWAPPED, ("undo_swap", "leave_swap"),
                                                                     swap_id)]
    assert CASES["ja"][0] in entries[0].title


# --------------------------------------------------------------------------- #
# The seam until Kantan-SD's picker: the best other line Connect can cut
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_choose_line_takes_the_best_other_line_connect_can_cut_never_the_old_one(lang, monkeypatch):
    from app import sentence_corpus, token_index
    word, old, other = CASES[lang]
    files = ["a.srt", "b.srt", "c.srt"]
    monkeypatch.setattr(sentence_corpus, "library_files", lambda l: files)
    monkeypatch.setattr(sentence_corpus, "files_holding", lambda l, f, wanted, runs=(), most=None: list(f))
    monkeypatch.setattr(swap, "_items_of", lambda l, paths: {"a.srt": 1, "b.srt": 2, "c.srt": 3})

    class Store:
        def file_tokens(self, path):
            return {"a.srt": [(old, [[word, "R", word]])], "c.srt": [(other, [[word, "R", word]])]}.get(path, [])

        def close(self):
            pass
    monkeypatch.setattr(token_index, "open_store", lambda l: Store())
    asked = []
    # ranked best first: the old card's own line, then a line in an episode with no video, then the good one
    ranked = [(0, old, word, 0), (0, other + "。", word, 1), (1, other, word, 2)]
    monkeypatch.setattr(sentence_corpus, "best_for", lambda l, w, files=None: asked.append(set(w)) or {(word, "R"): ranked})
    assert swap.choose_line(lang, word, [old], reachable=lambda item: item != 2) == (3, other)
    assert asked == [{(word, "R")}]                  # its reading from the token store: the word's own key
    assert swap.choose_line(lang, word, [old], reachable=lambda item: True, skip_items=[2]) == (3, other)
    # nothing ranked (no sentence of a good length): any line of the files that says it, never the old one
    monkeypatch.setattr(sentence_corpus, "best_for", lambda *a, **k: {})
    assert swap.choose_line(lang, word, [old]) == (3, other)
    assert swap.choose_line(lang, word, [old, other]) is None
