"""Kyou-SH2: Tidy, Connect's backlog cleared (Sonic 2026-11-20 plan v2 point 3; 2026-11-21 MODEL.md round 3: the clutter
clears by itself too, at about 1.5 x the cap; ROLES.md: Tidy never deletes without a backup).

What each test holds still:
- **when:** by itself only past 1.5 × the cap; your *Tidy now* past the cap; no cap → never; a quick look (what the
  count read, the ledger: no Anki call of its own) — Connect's runner asks it after the cap's count, a tidy that
  can't go never holds mining and isn't tried again that run;
- **what:** only Connect's own cards past the window, the lowest in the study order first (set aside / off the list
  first), until no more than the cap wait — never yours, a pinned show's, an episode you asked for; read again under
  the lock: a studied, edited, suspended, flagged, filtered-deck or untagged card stays;
- **a backup first:** notes.json, the media byte for byte, a package holding exactly those notes — a package that
  doesn't hold them deletes nothing and puts every card back in its deck;
- **Surasura's delete:** the deleted cards' words are free again (N15 doesn't hold them, nor does the deleted-card
  look that ran in between), their lines gone; the ledger says so;
- **Undo:** the media back, the package imported, the cards in their decks again, the made words, receipt and lines
  back as they were; a second Undo refused; a kill half-way finished by the next look;
- **said:** the status record's `tidied` and *Needs you*'s card with *Undo* · *OK*.

What a wrong answer costs: a learner's card deleted (a studied one, his own), a deletion with no way back, a word
blocked for ever by Surasura's own delete, or clutter that grows with nothing said. Anki is a fake that writes and
reads a real package (SQLite in a zip); the ledger and the library store are real (the suite's library). ja + zh.
"""
import calendar
import contextlib
import hashlib
import json
import os
import sqlite3
import time
import zipfile

import pytest

from app.connect import library, runner, shelf, status, tidy
from app.connect.ledger import Ledger
from app.services import needs
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

WORDS = {"ja": ["上層部", "一生懸命", "走り出す", "気配", "溜め息", "約束"],
         "zh": ["遗憾", "漂亮", "哎呀", "约定", "叹气", "气氛"]}


class FakeAnki:
    """Tidy's Anki: notes {id: {...}}, cards {id: {...}}, media {name: bytes}, decks by name; its package is a real zip
    holding a SQLite `collection.anki2` with the notes (and its cards), as Anki's exporter writes one."""

    def __init__(self):
        self.notes_, self.cards_, self.media = {}, {}, {}
        self.busy = False
        self.deleted, self.media_deleted, self.decks_deleted, self.log = [], [], [], []
        self.export_ok = True
        self.keep_ids = True          # the import keeps the note and card ids (they're free again)
        self.filtered = set()

    def add(self, note_id, tag, word, mod, deck="日本語::Mining", cards=None, sound=None):
        cards = cards or [{"reps": 0, "type": 0, "queue": 0}]
        ids = []
        for n, card in enumerate(cards):
            cid = note_id * 10 + n
            self.cards_[cid] = dict({"flags": 0}, **card, cardId=cid, note=note_id, ord=n, deckName=deck)
            ids.append(cid)
        fields = {"Word": {"value": word, "order": 0},
                  "SentenceAudio": {"value": f"[sound:{sound}]" if sound else "", "order": 1}}
        self.notes_[note_id] = {"noteId": note_id, "tags": [tag], "mod": mod, "cards": ids, "fields": fields,
                                "modelName": "Lapis"}
        if sound:
            self.media[sound] = f"clip of {word}".encode("utf-8")

    # --- reads
    def notes(self, ids):
        return [json.loads(json.dumps(self.notes_[int(i)])) for i in ids if int(i) in self.notes_]

    def cards(self, ids):
        return [dict(self.cards_[int(i)]) for i in ids if int(i) in self.cards_]

    def reviewing(self):
        return self.busy

    def writer(self, verb):
        self.log.append(("writer", verb))
        return contextlib.nullcontext()

    def find_cards(self, query):
        self.log.append(("find_cards", query))
        if query.startswith("deck:filtered cid:"):
            wanted = {int(x) for x in query.split("cid:")[1].split(",")}
            return sorted(wanted & self.filtered)
        deck = query.strip('"')[len("deck:"):]
        return sorted(c for c, card in self.cards_.items() if card["deckName"] == deck)

    def find_notes(self, query):
        deck = query.strip('"')[len("deck:"):]
        return sorted({card["note"] for card in self.cards_.values() if card["deckName"] == deck})

    def users(self, name):
        return [n for n, note in self.notes_.items() if name in json.dumps(note["fields"], ensure_ascii=False)]

    def media_bytes(self, name):
        return self.media.get(name)

    # --- writes
    def change_deck(self, card_ids, deck):
        self.log.append(("change_deck", tuple(card_ids), deck))
        for c_ in card_ids:
            self.cards_[int(c_)]["deckName"] = deck

    def delete_deck(self, deck):
        self.decks_deleted.append(deck)

    def export_package(self, deck, path):
        self.log.append(("export", deck))
        if not self.export_ok:
            return False
        notes = sorted({card["note"] for card in self.cards_.values() if card["deckName"] == deck})
        db = path + ".db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, data TEXT)")
        conn.execute("CREATE TABLE cards (id INTEGER PRIMARY KEY, data TEXT)")
        for n in notes:
            conn.execute("INSERT INTO notes VALUES (?, ?)", (n, json.dumps(self.notes_[n], ensure_ascii=False)))
            for cid in self.notes_[n]["cards"]:
                conn.execute("INSERT INTO cards VALUES (?, ?)", (cid, json.dumps(self.cards_[cid], ensure_ascii=False)))
        conn.commit()
        conn.close()
        with zipfile.ZipFile(path, "w") as z:
            z.write(db, "collection.anki2")
            z.writestr("media", "{}")
        os.remove(db)
        return True

    def import_package(self, path):
        self.log.append(("import", os.path.basename(path)))
        with zipfile.ZipFile(path) as z:
            data = z.read("collection.anki2")
        db = path + ".read"
        with open(db, "wb") as f:
            f.write(data)
        conn = sqlite3.connect(db)
        notes = [json.loads(r[0]) for r in conn.execute("SELECT data FROM notes")]
        cards = {r[0]: json.loads(r[1]) for r in conn.execute("SELECT id, data FROM cards")}
        conn.close()
        os.remove(db)
        for note in notes:
            if note["noteId"] in self.notes_:
                continue                        # Anki's importer: the same note there already
            new_id = note["noteId"] if self.keep_ids else note["noteId"] + 999
            ids = []
            for cid in note["cards"]:
                card = dict(cards[cid])
                new_cid = cid if self.keep_ids else cid + 999
                card.update(cardId=new_cid, note=new_id)
                self.cards_[new_cid] = card
                ids.append(new_cid)
            self.notes_[new_id] = dict(note, noteId=new_id, cards=ids)
        return True

    def delete_notes(self, ids):
        for i in ids:
            note = self.notes_.pop(int(i))
            for c_ in note["cards"]:
                self.cards_.pop(c_, None)
            self.deleted.append(int(i))

    def delete_media(self, name):
        self.media.pop(name, None)
        self.media_deleted.append(name)

    def store_media(self, name, data):
        self.media[name] = data


# --------------------------------------------------------------------------- #
# The setting: the library, a finished job that made six cards, Anki holding them
# --------------------------------------------------------------------------- #
@pytest.fixture
def ledger(tmp_path):
    book = Ledger(str(tmp_path / "connect" / "ledger.sqlite"))
    try:
        yield book
    finally:
        book.close()


def _mined(ledger, lang):
    """One episode mined: six notes 101–106 (WORDS[lang]) by one finished job (their outcomes `made`, tagged with it),
    recorded in the real store -> (item id, job tag, the job's end as epoch)."""
    c.library(lang)
    words = WORDS[lang]
    with c.store(lang) as s:
        item = s.ids("now")[0]
        library.record_batch(s, item, {w: [101 + i] for i, w in enumerate(words)}, "2026-11-21T10:00:00Z", batch="t-1")
    job_id = ledger.queue(lang, item, "user", None, store_id="s1")
    ledger.end_batch(job_id, 1, "done", [{"word": w, "reading": "", "outcome": "made", "note_id": 101 + i}
                                         for i, w in enumerate(words)])
    ledger.set_state(job_id, "done")
    done_at = calendar.timegm(time.strptime(ledger.job_by_id(job_id)["updated_at"], "%Y-%m-%dT%H:%M:%SZ"))
    return item, "surasura::connect::" + ledger.tag_id(job_id), done_at


def _anki(lang, tag, done_at):
    anki = FakeAnki()
    for i, w in enumerate(WORDS[lang]):
        anki.add(101 + i, tag, w, done_at - 60, sound=f"sl-{i:016x}.mp3")
    return anki


def _opener(lang):
    return lambda: library.open_store(lang)


# --------------------------------------------------------------------------- #
# When, and which cards (pure)
# --------------------------------------------------------------------------- #
def _pile(n_mine, n_yours=0, start=0):
    return ([tidy.Card(1000 + i, f"w{i}", 1, place=start + i, mine=True) for i in range(n_mine)]
            + [tidy.Card(5000 + i, f"y{i}", None, place=-1) for i in range(n_yours)])


def test_by_itself_tidy_waits_until_one_and_a_half_times_the_cap():
    # why: Sonic's line — below it the overflow is only the window sliding, not clutter worth deleting
    assert tidy.choose(_pile(15), cap=10) == [], "15 is exactly 1.5 × 10: nothing yet"
    chosen = tidy.choose(_pile(16), cap=10)
    assert [c.note for c in chosen] == [1015, 1014, 1013, 1012, 1011, 1010], "the lowest first, down to the cap"


def test_your_press_tidies_past_the_cap_and_no_cap_never_tidies():
    assert [c.note for c in tidy.choose(_pile(12), cap=10, now=True)] == [1011, 1010]
    assert tidy.choose(_pile(10), cap=10, now=True) == []
    assert tidy.choose(_pile(500), cap=0) == [] and tidy.choose(_pile(500), cap=0, now=True) == []


def test_yours_and_a_pinned_shows_never_go_even_when_they_are_the_overflow():
    # why: Tidy keeps Anki uncluttered of Connect's cards only (ROLES.md); your own cards are never its to delete
    pile = _pile(4, start=100) + [tidy.Card(9000 + i, f"y{i}", None, place=i) for i in range(14)]
    chosen = tidy.choose(pile, cap=10)
    assert {c.note for c in chosen} <= {1000, 1001, 1002, 1003} and len(chosen) == 4


def test_the_windows_last_card_is_never_taken_even_when_the_overflow_holds_none_of_connects():
    # mutant M2: the window is exactly the first `cap` — the cap-th card is in it, whatever lies past it
    pile = [tidy.Card(1000, "a", 1, place=0, mine=True), tidy.Card(1001, "b", 1, place=1, mine=True),
            tidy.Card(5000, "y0", None, place=2), tidy.Card(5001, "y1", None, place=3)]
    assert tidy.choose(pile, cap=2) == [], "past the window only your own cards wait: nothing of Connect's goes"


def test_a_set_aside_card_goes_before_one_at_the_same_place_and_off_list_before_listed():
    pile = _pile(10) + [tidy.Card(3000, "off", 1, place=shelf.NOT_LISTED, mine=True),
                        tidy.Card(3001, "off2", 1, place=shelf.NOT_LISTED, mine=True, shelved=True)] + \
        [tidy.Card(4000 + i, f"x{i}", 1, place=50 + i, mine=True) for i in range(4)]
    chosen = tidy.choose(pile, cap=10)
    assert [c.note for c in chosen[:3]] == [3001, 3000, 4003]


# --------------------------------------------------------------------------- #
# The tidy: backup, delete, Surasura's delete
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_tidy_backs_up_byte_for_byte_then_deletes_and_frees_the_words(ledger, lang):
    item, tag, done_at = _mined(ledger, lang)
    anki = _anki(lang, tag, done_at)
    clip = dict(anki.media)
    done = tidy.run(anki, ledger, lang, [104, 105, 106], open_store=_opener(lang))
    assert sorted(anki.deleted) == [104, 105, 106] and sorted(done["deleted"]) == [104, 105, 106]
    row = tidy.tidy_row(ledger, done["id"])
    assert row["state"] == tidy.DONE
    # the backup: the package holds exactly those notes; the media byte for byte; the notes as Anki described them
    assert tidy.package_notes(os.path.join(row["folder"], "cards.apkg")) == {104, 105, 106}
    record = json.load(open(os.path.join(row["folder"], "notes.json"), encoding="utf-8"))
    assert {n["noteId"] for n in record["notes"]} == {104, 105, 106}
    for i in (3, 4, 5):
        name = f"sl-{i:016x}.mp3"
        assert open(os.path.join(row["folder"], "media", name), "rb").read() == clip[name]
        assert record["media"][name] == hashlib.sha1(clip[name]).hexdigest()
    assert sorted(anki.media_deleted) == [f"sl-{i:016x}.mp3" for i in (3, 4, 5)]
    # the export went through a deck of the tidy's own, removed once empty; nothing else moved
    assert anki.decks_deleted == [tidy.TEMP_DECK.format(id=done["id"])]
    # Surasura's delete: the words are free (made again if they climb back), the others still made
    with c.store(lang) as s:
        made = library.made_words_all(s)
        assert set(WORDS[lang][3:]).isdisjoint(made) and set(WORDS[lang][:3]) <= made
        assert s.unmined_words() == [], "never listed as a card you deleted"
        assert library.mined_at(s, item) is not None, "the episode's other cards are in Anki: its receipt stays"


def test_the_backup_comes_before_any_delete_and_a_package_that_doesnt_hold_them_deletes_nothing(ledger):
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    anki.export_ok = False
    with pytest.raises(tidy.Refused):
        tidy.run(anki, ledger, "ja", [104, 105], open_store=_opener("ja"))
    assert anki.deleted == [] and anki.media_deleted == []
    assert {anki.cards_[1040]["deckName"], anki.cards_[1050]["deckName"]} == {"日本語::Mining"}, "back in their deck"
    (row,) = ledger.conn.execute("SELECT state FROM tidies").fetchall()
    assert row[0] == tidy.FAILED
    with c.store("ja") as s:
        assert set(WORDS["ja"]) <= library.made_words_all(s)


def test_a_package_that_misses_one_of_the_notes_deletes_none_of_them(ledger):
    # mutant M4: a package Anki wrote but that doesn't hold every note (one lost on the way) is no backup of it
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    export = anki.export_package

    def one_short(deck, path):
        anki.cards_[1050]["deckName"] = "elsewhere"          # its card wasn't in the deck Anki exported
        ok = export(deck, path)
        anki.cards_[1050]["deckName"] = deck
        return ok
    anki.export_package = one_short
    with pytest.raises(tidy.Refused):
        tidy.run(anki, ledger, "ja", [104, 105], open_store=_opener("ja"))
    assert anki.deleted == [] and anki.cards_[1050]["deckName"] == "日本語::Mining"


def test_only_connects_untouched_cards_go_studied_edited_suspended_flagged_filtered_untagged_stay(ledger):
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    anki.cards_[1010].update(reps=2, type=2, queue=2)          # studied
    anki.notes_[102]["mod"] = done_at + 3600                   # you edited it
    anki.cards_[1030].update(queue=-1)                         # you suspended it
    anki.cards_[1040].update(flags=3)                          # you flagged it
    anki.filtered = {1050}                                     # you pulled it into a filtered deck
    anki.notes_[106]["tags"] = ["my-own"]                      # not Connect's
    with pytest.raises(tidy.Refused):
        tidy.run(anki, ledger, "ja", [101, 102, 104, 105, 106, 103], open_store=_opener("ja"))
    assert anki.deleted == [], "every one of them is yours in some way"


def test_a_lowest_card_you_studied_stays_and_the_next_one_goes_in_its_place(ledger):
    # why: the lowest candidates being yours to keep (studied, edited) must never stop every tidy for good
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    anki.cards_[1060].update(reps=1, type=1, queue=1)          # the lowest: studied
    done = tidy.run(anki, ledger, "ja", [106, 105, 104, 103], open_store=_opener("ja"), limit=2)
    assert sorted(anki.deleted) == [104, 105] and done["kept"][0][0] == 106


def test_the_quick_look_below_the_line_asks_nothing_more(ledger, monkeypatch):
    # why: Steps.tidy runs before every job's pick — below the line it reads no list, no store, no job
    steps = runner.Steps({"connect_enabled": True})
    steps.cap = lambda _l: 10
    _seen(steps, "ja", list(range(1, 16)), {n: (1, f"w{n}") for n in range(1, 16)})
    steps._open = lambda _l: pytest.fail("no store read below the line")
    steps._places = lambda *a: pytest.fail("no list read below the line")
    assert steps.tidy("ja", ledger) is None


def test_while_you_review_nothing_is_written(ledger):
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    anki.busy = True
    with pytest.raises(tidy.Reviewing):
        tidy.run(anki, ledger, "ja", [104], open_store=_opener("ja"))
    assert anki.deleted == [] and not any(e[0] == "change_deck" for e in anki.log)


def test_the_deleted_card_look_in_between_never_blocks_surasuras_delete(ledger):
    # why: a kill after Anki's delete, then the next run's deleted-card look first (`notes_gone` keeps the word
    # blocked: N15) — finishing the tidy still frees it: Surasura deleted it, not you
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    real_finish = tidy.finish
    tidy.finish = lambda *a, **k: {"deleted": [], "kept": [], "freed": [], "pending": True}
    try:
        tidy.run(anki, ledger, "ja", [105], open_store=_opener("ja"))
    finally:
        tidy.finish = real_finish
    ledger.conn.execute("UPDATE tidies SET state = ?", (tidy.WRITING,))
    with c.store("ja") as s:
        s.notes_gone([105])
        assert [e["word"] for e in s.unmined_words()] == [WORDS["ja"][4]], "the look reads it as yours, for now"
    assert tidy.finish_pending(anki, ledger, "ja", _opener("ja")) == 1
    with c.store("ja") as s:
        assert s.unmined_words() == [] and WORDS["ja"][4] not in library.made_words_all(s)


def test_a_kill_after_the_move_before_the_export_puts_the_cards_back_and_deletes_nothing(ledger):
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)

    def killed(deck, path):
        raise KeyboardInterrupt
    anki.export_package = killed
    with pytest.raises(KeyboardInterrupt):
        tidy.run(anki, ledger, "ja", [104, 105], open_store=_opener("ja"))
    ledger.conn.execute("UPDATE tidies SET state = ?", (tidy.WRITING,))    # the process died: no `_fail` ran
    for cid in (1040, 1050):
        anki.cards_[cid]["deckName"] = tidy.TEMP_DECK.format(id=1)
    assert tidy.finish_pending(anki, ledger, "ja", _opener("ja")) == 1
    assert anki.deleted == [] and anki.cards_[1040]["deckName"] == "日本語::Mining"
    with c.store("ja") as s:
        assert set(WORDS["ja"]) <= library.made_words_all(s)


# --------------------------------------------------------------------------- #
# Undo
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
@pytest.mark.parametrize("keep_ids", [True, False])
def test_undo_puts_back_exactly_what_went(ledger, lang, keep_ids):
    item, tag, done_at = _mined(ledger, lang)
    anki = _anki(lang, tag, done_at)
    anki.cards_[1050]["deckName"] = "日本語::Mining::Later"
    before = {n: json.loads(json.dumps(anki.notes_[n])) for n in (104, 105, 106)}
    media = dict(anki.media)
    with c.store(lang) as s:
        rows = library.made_rows(s, [104, 105, 106])
    done = tidy.run(anki, ledger, lang, [104, 105, 106], open_store=_opener(lang))
    anki.keep_ids = keep_ids
    back = tidy.restore(anki, ledger, done["id"], _opener(lang))
    assert back["back"] == 3 and back["missing"] == []
    ids = sorted(n for n in anki.notes_ if n not in (101, 102, 103))
    assert len(ids) == 3
    by_word = {anki.notes_[n]["fields"]["Word"]["value"]: anki.notes_[n] for n in ids}
    for old, note in before.items():
        now = by_word[note["fields"]["Word"]["value"]]
        assert now["fields"] == note["fields"] and now["tags"] == note["tags"]
        assert (now["noteId"] == old) is keep_ids
    assert anki.cards_[max(by_word[WORDS[lang][4]]["cards"])]["deckName"] == "日本語::Mining::Later"
    assert {anki.cards_[c_]["deckName"] for n in ids for c_ in anki.notes_[n]["cards"]} <= {
        "日本語::Mining", "日本語::Mining::Later"}, "every card back in its own deck"
    assert anki.media == media, "the clips are back, byte for byte"
    with c.store(lang) as s:
        now_rows = library.made_rows(s, ids)
        mapped = {old: by_word[before[old]["fields"]["Word"]["value"]]["noteId"] for old in before}
        assert sorted((r[0], r[1], [mapped.get(n, n) for n in r[2]], r[3], r[4]) for r in rows["words"]) == \
            sorted((r[0], r[1], r[2], r[3], r[4]) for r in now_rows["words"])
        assert set(WORDS[lang]) <= library.made_words_all(s)
    assert tidy.tidy_row(ledger, done["id"])["state"] == tidy.UNDONE
    with pytest.raises(tidy.Refused):
        tidy.restore(anki, ledger, done["id"], _opener(lang))


def test_undo_brings_back_the_receipt_of_an_episode_tidied_whole(ledger):
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    with c.store("ja") as s:
        mined = library.mined_at(s, item)
    done = tidy.run(anki, ledger, "ja", list(range(101, 107)), open_store=_opener("ja"))
    with c.store("ja") as s:
        assert library.mined_at(s, item) is None, "nothing of it left in Anki: mined again if it climbs back"
    tidy.restore(anki, ledger, done["id"], _opener("ja"))
    with c.store("ja") as s:
        assert library.mined_at(s, item) == mined


def test_an_undo_whose_import_never_took_stays_offered(ledger):
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    done = tidy.run(anki, ledger, "ja", [104], open_store=_opener("ja"))
    anki.import_package = lambda path: (_ for _ in ()).throw(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        tidy.restore(anki, ledger, done["id"], _opener("ja"))
    ledger.conn.execute("UPDATE tidies SET state = ?", (tidy.RESTORING,))    # the process died mid-import
    tidy.finish_pending(anki, ledger, "ja", _opener("ja"))
    assert tidy.tidy_row(ledger, done["id"])["state"] == tidy.DONE, "nothing came back: its Undo is still there"
    rec = status._tidied(ledger.conn, "ja")
    assert rec is not None and rec["id"] == done["id"]


# --------------------------------------------------------------------------- #
# Connect's runner asks it, and it never holds mining
# --------------------------------------------------------------------------- #
def _steps(count, tidied=None, raises=None):
    steps = runner.Steps({"connect_enabled": True})
    steps.cap = lambda lang: 10
    counts = iter(count if isinstance(count, list) else [count, count])
    steps.waiting_count = lambda lang: next(counts)
    calls = []

    def tidy_(lang, ledger, now=False):
        calls.append(lang)
        if raises:
            raise raises
        return tidied
    steps.tidy = tidy_
    return steps, calls


def test_the_cap_asks_tidy_after_its_count_and_counts_again_after_a_tidy(ledger):
    steps, calls = _steps([20, 10], tidied={"cards": 10, "id": 1})
    held = runner._full(steps, "ja", ledger=ledger)
    assert calls == ["ja"] and isinstance(held, runner.Wait) and "10 cards" in held.reason


def test_a_tidy_that_cant_go_never_holds_mining_and_isnt_tried_again_this_run(ledger):
    steps, calls = _steps(3, raises=tidy.Reviewing())
    assert runner._full(steps, "ja", ledger=ledger) is None, "below the cap: mining goes on"
    runner._full(steps, "ja", ledger=ledger)
    assert calls == ["ja"], "one try a run"


def _seen(steps, lang, notes, made, pinned=(), counted=None):
    """What `waiting_count` keeps for Tidy: the counted notes with the item their place is read by."""
    counted = notes if counted is None else counted
    steps._waiting_seen = {lang: (frozenset(notes), dict(made), frozenset(pinned),
                                  {n: (made[n][1], runner.PINNED if made[n][0] in pinned else made[n][0])
                                   if n in made else (None, runner.YOURS) for n in counted})}


def _by_list(words):
    """The window's order (`Steps._places`, Kantan-MO's) as *By leverage* gives it: a word's place on the list."""
    def places(lang, loaded, keys):
        return lambda word, item, ahead_only=False: (runner.FRONT if item in (runner.YOURS, runner.PINNED)
                                                     else words.index(word) if word in words else runner.OFF_LIST)
    return places


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_steps_tidy_takes_connects_lowest_and_never_yours_a_pinned_shows_or_an_asked_episode(ledger, lang,
                                                                                              monkeypatch):
    words = WORDS[lang]
    steps = runner.Steps({"connect_enabled": True})
    steps.cap = lambda _l: 2
    steps._open = lambda _l: contextlib.nullcontext(object())
    monkeypatch.setattr(shelf, "finished_items", lambda store, made: set())
    steps._places = _by_list(words)
    steps._listed_keys = lambda _l: {w: True for w in words}
    made = {101: (1, words[0]), 102: (1, words[1]), 103: (2, words[2]), 104: (3, words[3]), 105: (1, words[5])}
    # 101..105 Connect's (item 2 pinned, item 3 asked); 900, 901 yours; 105's word listed last
    _seen(steps, lang, [101, 102, 103, 104, 105, 900, 901], made, pinned={2})
    asked = ledger.queue(lang, 3, "user", None, store_id="s1")
    ledger.conn.execute("UPDATE jobs SET asked_at = '2026-11-21T00:00:00Z' WHERE id = ?", (asked,))
    took = []
    monkeypatch.setattr(tidy, "run", lambda anki, ledger_, lang_, notes, why, open_store, limit: took.append(
        (sorted(notes[:limit]), why)) or {"deleted": notes[:limit], "id": 7})
    steps.after_write = lambda _l: None
    assert steps.tidy(lang, ledger) == {"cards": 3, "id": 7}, "7 waiting > 1.5 × 2"
    assert took == [([101, 102, 105], tidy.AUTO)], "Connect's own, past the window, lowest first"


def test_steps_tidy_counts_the_old_shelf_and_connects_off_list_cards_without_asking_anki(ledger, monkeypatch):
    words = WORDS["ja"]
    steps = runner.Steps({"connect_enabled": True})
    steps.cap = lambda _l: 2
    steps._open = lambda _l: contextlib.nullcontext(object())
    monkeypatch.setattr(shelf, "finished_items", lambda store, made: set())
    steps._places = _by_list(words[:2])
    steps._listed_keys = lambda _l: {w: True for w in words[:2]}
    made = {101: (1, words[0]), 102: (1, words[1]), 103: (1, words[2]), 104: (1, words[3]), 105: (1, words[4])}
    _seen(steps, "ja", [101, 102, 103], made, counted=[101, 102])          # 103 off the list
    with ledger.transaction():
        shelf.ensure(ledger)
        for n in (104, 105):                                                # set aside by the old shelf
            ledger.conn.execute("INSERT INTO shelf (card_id, note_id, language, item_id, word, run, why, shelved_at) "
                                "VALUES (?, ?, 'ja', 1, ?, 'shelf-1', 'the cap', '2026-11-19T00:00:00Z')",
                                (n * 10, n, made[n][1]))
    monkeypatch.setattr("app.anki_connect.invoke", lambda *a, **k: pytest.fail("no Anki call for the look"))
    took = []
    monkeypatch.setattr(tidy, "run", lambda anki, ledger_, lang_, notes, why, open_store, limit: took.append(
        sorted(notes[:limit])) or {"deleted": notes[:limit], "id": 1})
    steps.after_write = lambda _l: None
    steps.tidy("ja", ledger)
    assert took == [[103, 104, 105]], "5 > 3: the set-aside and off-list ones go, the window stays"


# --------------------------------------------------------------------------- #
# Said in the window
# --------------------------------------------------------------------------- #
def test_the_status_record_and_needs_you_say_it_with_undo_and_ok(ledger, tmp_path, monkeypatch):
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    done = tidy.run(anki, ledger, "ja", [104, 105, 106], open_store=_opener("ja"))
    rec = status.read(["ja"], path=str(tmp_path / "connect" / "ledger.sqlite"))["languages"]["ja"]
    assert rec["tidied"] == {"id": done["id"], "cards": 3, "at": rec["tidied"]["at"], "why": tidy.AUTO}
    entry = needs._tidy_entry(rec, frozenset())
    assert entry.kind == needs.TIDIED and entry.actions == ("undo_tidy", "leave_tidy")
    assert entry.title == needs.STRINGS["tidied_title"].format(n=3) and entry.data["id"] == done["id"]
    assert needs._tidy_entry(rec, frozenset(), frozenset({entry.key})) is None, "OK holds it until the next tidy"
    tidy.restore(anki, ledger, done["id"], _opener("ja"))
    rec = status.read(["ja"], path=str(tmp_path / "connect" / "ledger.sqlite"))["languages"]["ja"]
    assert rec["tidied"] is None and needs._tidy_entry(rec, frozenset()) is None


# --------------------------------------------------------------------------- #
# The review's fixes (register rows F1–F8, S2)
# --------------------------------------------------------------------------- #
def test_a_backup_that_failed_and_cards_that_couldnt_go_home_are_put_home_by_the_next_look(ledger):
    # F1: a failed tidy is never revisited, so one whose cards are still in its own deck stays `writing`
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    anki.export_ok = False
    moves = anki.change_deck

    def first_ok_then_fail(ids, deck):
        if deck != "日本語::Mining":
            return moves(ids, deck)
        raise OSError("Anki stopped answering")
    anki.change_deck = first_ok_then_fail
    with pytest.raises(tidy.Refused):
        tidy.run(anki, ledger, "ja", [104], open_store=_opener("ja"))
    assert ledger.conn.execute("SELECT state FROM tidies").fetchone()[0] == tidy.WRITING
    anki.change_deck = moves
    tidy.finish_pending(anki, ledger, "ja", _opener("ja"))
    assert anki.cards_[1040]["deckName"] == "日本語::Mining" and anki.deleted == []
    assert ledger.conn.execute("SELECT state FROM tidies").fetchone()[0] == tidy.FAILED


def test_a_library_that_cant_be_read_now_writes_nothing_to_anki(ledger):
    # F2: without the made-words record no Undo could put the words back, and N15 would hold them: nothing goes
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)

    def busy():
        raise sqlite3.OperationalError("database is locked")
    with pytest.raises(sqlite3.OperationalError):
        tidy.run(anki, ledger, "ja", [104, 105], open_store=busy)
    assert anki.deleted == [] and not any(e[0] == "change_deck" for e in anki.log)
    assert ledger.conn.execute("SELECT COUNT(*) FROM tidies").fetchone()[0] == 0


def test_a_kills_tidy_is_finished_under_the_lock_and_never_while_you_review(ledger):
    # F3: finishing moves cards (Anki writes): the one writer, and never during your reviews
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    anki.export_package = lambda deck, path: (_ for _ in ()).throw(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        tidy.run(anki, ledger, "ja", [104], open_store=_opener("ja"))
    anki.busy = True
    anki.log.clear()
    with pytest.raises(tidy.Reviewing):
        tidy.finish_pending(anki, ledger, "ja", _opener("ja"))
    assert [e for e in anki.log if e[0] == "change_deck"] == []
    anki.busy = False
    assert tidy.finish_pending(anki, ledger, "ja", _opener("ja")) == 1
    assert anki.log[0] == ("writer", tidy.VERB) and anki.cards_[1040]["deckName"] == "日本語::Mining"


def test_a_card_you_answer_while_anki_exports_stays_and_goes_home(ledger):
    # F6: the lock doesn't stop Anki's own reviewer: read once more just before the delete
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    export = anki.export_package

    def answered_meanwhile(deck, path):
        ok = export(deck, path)
        anki.cards_[1050].update(reps=1, type=1, queue=1)
        return ok
    anki.export_package = answered_meanwhile
    done = tidy.run(anki, ledger, "ja", [104, 105, 106], open_store=_opener("ja"))
    assert sorted(done["deleted"]) == [104, 106] and 105 in anki.notes_
    assert anki.cards_[1050]["deckName"] == "日本語::Mining"
    assert [k for k in done["kept"] if k[0] == 105] == [[105, "you've studied it"]], "said once, with its own why"
    with c.store("ja") as s:
        assert WORDS["ja"][4] in library.made_words_all(s), "its word stays made: its card is in Anki"


def test_an_undo_whose_media_put_back_failed_stays_offered(ledger):
    # S2: the card went away until the next run though nothing came back
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    done = tidy.run(anki, ledger, "ja", [104], open_store=_opener("ja"))
    anki.store_media = lambda name, data: (_ for _ in ()).throw(OSError("Anki stopped answering"))
    with pytest.raises(OSError):
        tidy.restore(anki, ledger, done["id"], _opener("ja"))
    assert tidy.tidy_row(ledger, done["id"])["state"] == tidy.DONE


def test_an_undo_says_which_clips_the_backup_couldnt_give_back(ledger):
    # F5: a damaged backup file is never put into Anki, and the answer names it
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    done = tidy.run(anki, ledger, "ja", [104], open_store=_opener("ja"))
    row = tidy.tidy_row(ledger, done["id"])
    with open(os.path.join(row["folder"], "media", f"sl-{3:016x}.mp3"), "wb") as f:
        f.write(b"damaged")
    back = tidy.restore(anki, ledger, done["id"], _opener("ja"))
    assert back["media_missing"] == [f"sl-{3:016x}.mp3"] and f"sl-{3:016x}.mp3" not in anki.media


def test_connects_own_look_never_waits_for_another_writer(monkeypatch):
    # F8: the window's press waits up to 10 s for the lock; Connect's look takes it only if it's free
    from app import anki_connect
    asked = []
    monkeypatch.setattr(anki_connect, "writer", lambda verb, wait=0.0: asked.append(wait) or contextlib.nullcontext())
    tidy.AnkiConnectTidy("http://127.0.0.1:8765", wait=0.0).writer(tidy.VERB)
    tidy.AnkiConnectTidy("http://127.0.0.1:8765").writer(tidy.VERB)
    assert asked == [0.0, 10.0]
