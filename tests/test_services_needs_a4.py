"""Alpha 4's *Needs you* (Mattias #4, Sonic 2026-10-27): `app/services/needs.py`, Qt-free, with real Japanese and
Chinese titles from tests/Test Resources/ — the seen file read while it is written (the keep_waiting flake), *Not now*
(back the next day) and *Stop asking* (never again, with Undo), one line for many cards that share a reason, the line
for every missing file, and the card for a library whose files are mostly gone (K3).

What a wrong answer would cost a learner: an answer lost because the file was being read as it was written (*Keep
waiting* that keeps nothing, a card that comes back after a restart); a card that can't be put away, or one put away
for ever when he only said "not now"; a hundred cards with no one answer for them; a dead library offered file by file.
"""
import os
import threading
import time
from types import SimpleNamespace

import pytest

from app.services import needs
from tests.test_library_store_support import LANGUAGES, names

GONE = "{t}/{t} - {n:02d}.srt"            # each show in a folder of its own (K3: a shared folder is one card)


def view(language, n=4, missing=None, start=0):
    """`n` shows of one episode each with real titles; `missing`: how many of them are gone (all by default)."""
    titles = names(language)
    rows = []
    for i in range(n):
        t = f"{titles[(start + i) % len(titles)]} {start + i}"
        ep = SimpleNamespace(id=start + i + 1, label=f"Ep {i + 1}", number=i + 1, rel_path=GONE.format(t=t, n=i + 1),
                             missing=i < (n if missing is None else missing))
        rows.append(SimpleNamespace(key=f"w{start + i}", work_id=start + i, title=t, media="anime", tier="now",
                                    episodes=(ep,)))
    return SimpleNamespace(mode="store", rows=tuple(rows), loading=False, needs=())


def folder_rows(language, n):
    return [{"id": 10 + i, "path": f"C:\\Users\\Michael\\Downloads\\{names(language)[i]}", "items": 3,
             "shows": [names(language)[i]], "finished": False, "found_in": []} for i in range(n)]


# --- E: the seen file written while it is read ------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_the_seen_file_is_never_lost_when_it_is_read_while_it_is_written(language):
    """The keep_waiting flake (#180) and Michi's PermissionError on needs_seen_ja.json: on Windows a reader holding the
    file open makes the writer's replace fail — the answer (*Keep waiting*, a seen key) was lost. A reader on another
    thread reads while every answer is written: every answer is kept, none raises."""
    stop, errors = threading.Event(), []

    def reader():
        while not stop.is_set():
            try:
                needs.read_answered(language)
                needs.read_seen(language)
            except Exception as e:              # (a read never raises: it reads as empty)
                errors.append(e)

    threads = [threading.Thread(target=reader, daemon=True) for _ in range(3)]
    for t in threads:
        t.start()
    try:
        keys = [f"line:offline:c:\\users\\michael\\{names(language)[i % 10]}\\{i}" for i in range(150)]
        for k in keys:
            needs.answer(language, [k])          # *Keep waiting*'s write, one at a time as pressed
    finally:
        stop.set()
        for t in threads:
            t.join(5)
    assert errors == []
    assert set(keys) <= needs.read_answered(language)


# --- D2: Not now and Stop asking ----------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_not_now_hides_a_card_today_and_it_comes_back_the_next_day(language, monkeypatch):
    v = view(language, 1)
    [card] = [e for e in needs.entries(v) if e.kind == needs.GONE]
    assert needs.put_off(language, [card.key]) == 1
    assert needs.put_off(language, [card.key]) == 0              # the same press again writes nothing (S19)
    assert card.key in needs.read_hidden(language)
    assert needs.entries(v, hidden=needs.read_hidden(language)) == []
    monkeypatch.setattr(needs, "_today", lambda: "2999-01-01")   # the next day: it still needs you, so it is back
    assert needs.read_hidden(language) == frozenset()
    assert [e.key for e in needs.entries(v, hidden=needs.read_hidden(language))] == [card.key]


@pytest.mark.parametrize("language", LANGUAGES)
def test_stop_asking_keeps_the_card_off_for_good_and_undo_brings_it_back(language, monkeypatch):
    v = view(language, 1)
    [card] = needs.entries(v)
    assert needs.stop_asking(language, [card.key]) == 1
    monkeypatch.setattr(needs, "_today", lambda: "2999-01-01")   # days later: still never asked
    assert needs.entries(v, hidden=needs.read_hidden(language)) == []
    assert needs.read_answered(language) == frozenset()          # the item and its words: nothing answered for it
    assert needs.ask_again(language, [card.key]) == 1            # the toast's Undo
    assert [e.key for e in needs.entries(v, hidden=needs.read_hidden(language))] == [card.key]


@pytest.mark.parametrize("language", LANGUAGES)
def test_stop_asking_goes_with_its_trouble_so_gone_again_later_it_asks_again(language):
    """Like *Keep waiting*: a key goes with its trouble (`prune`), never by age — the file back, then gone again, asks."""
    v = view(language, 1)
    [card] = needs.entries(v)
    needs.stop_asking(language, [card.key])
    needs.put_off(language, ["gone:other:0000000000"])
    back = view(language, 1, missing=0)
    assert needs.prune(language, back) == 2
    assert needs.read_hidden(language) == frozenset()
    assert [e.key for e in needs.entries(v, hidden=needs.read_hidden(language))] == [card.key]


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_older_seen_file_reads_as_before_and_keeps_every_answer_when_a_card_is_put_off(language):
    needs.answer(language, ["item:7"])
    needs.mark_seen(language, ["gone:1:abc"])
    needs.put_off(language, ["gone:2:def"])
    needs.stop_asking(language, ["gone:3:ghi"])
    assert needs.read_answered(language) == {"item:7"} and needs.read_seen(language) == {"gone:1:abc"}
    assert needs.read_hidden(language) == {"gone:2:def", "gone:3:ghi"}


# --- D2: one line for many cards that share a reason -------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_three_gone_folders_bring_one_line_on_top_that_answers_them_all(language):
    out = needs.entries(None, gone_folders=folder_rows(language, 3))
    assert out[0].kind == needs.BULK and out[0].title == "3 source folders are gone"
    assert out[0].actions == ("later_all",) and out[0].unseen is False
    assert out[0].data["keys"] == tuple(e.key for e in out[1:])
    assert needs.badge(out) == 3                                  # the line is never a trouble of its own


@pytest.mark.parametrize("language", LANGUAGES)
def test_two_cards_of_one_reason_bring_no_line_and_hidden_cards_leave_it(language):
    assert [e.kind for e in needs.entries(None, gone_folders=folder_rows(language, 2))] == [needs.FOLDER_GONE] * 2
    rows = folder_rows(language, 3)
    first = needs.folder_key(rows[0]["path"])
    out = needs.entries(None, gone_folders=rows, hidden={first})
    assert [e.kind for e in out] == [needs.FOLDER_GONE] * 2       # 2 left: no line


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_bulk_answer_names_the_cards_it_covers_and_offers_forget_every_missing_file(language):
    out = needs.entries(view(language, 38))
    bulk = out[0]
    assert bulk.kind == needs.BULK and bulk.data["labels"]["remove_all"] == "Forget every missing file (38)"
    assert set(bulk.data["keys"]) == {e.key for e in out if e.kind == needs.GONE} and len(bulk.data["keys"]) == 38
    assert len(bulk.data["item_ids"]) == 38


@pytest.mark.parametrize("language", LANGUAGES)
def test_gone_folders_come_on_top_before_the_shows_files(language):
    """A gone folder explains its shows' gone files, and 届's press opens the page at it: never under 3,000 cards."""
    out = needs.entries(view(language, 5), gone_folders=folder_rows(language, 1))
    kinds = [e.kind for e in out]
    assert kinds.index(needs.FOLDER_GONE) < kinds.index(needs.GONE)


# --- K1: most of the library's files gone (Kura's card: `settled`, every folder had its look) --------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_library_whose_files_are_mostly_gone_is_one_card_on_top_once_every_folder_had_its_look(language):
    dead = view(language, 40, missing=30)
    assert needs.LIBRARY_GONE not in [e.kind for e in needs.entries(dead)]          # a look still to come: no card
    out = needs.entries(dead, settled=True)
    assert out[0].kind == needs.LIBRARY_GONE and out[0].title == "Most of your library's files are gone (30 of 40)"
    assert out[0].actions == ("start_fresh", "choose_folder")
    few = view(language, 40, missing=10)                                             # a quarter: each show's card
    assert needs.LIBRARY_GONE not in [e.kind for e in needs.entries(few, settled=True)]
    small = view(language, 6)                                                       # 6 of 6, but only 6
    assert needs.LIBRARY_GONE not in [e.kind for e in needs.entries(small, settled=True)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_library_on_a_drive_only_offline_is_never_called_gone(language):
    dead = view(language, 40)
    root = needs.Root(path="E:\\Anime", rel="", label="Drive E:", files=40)
    out = needs.entries(dead, offline_roots=[root], settled=True)
    assert needs.LIBRARY_GONE not in [e.kind for e in out]


def test_3000_cards_are_worked_out_off_the_window_in_well_under_a_second():
    """The gather (a worker's) at Mattias's size: 3,000 shows with a file gone — one library card holding them all."""
    t = time.perf_counter()
    out = needs.entries(view("ja", 3000), hidden=frozenset(), settled=True)
    assert time.perf_counter() - t < 1.0
    assert out[0].kind == needs.LIBRARY_GONE and len(out[0].lines) == 3000


# --- the review round (fix-t) IK-10: the answers are one library's ---------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_new_library_drops_the_old_ones_stop_asking_and_not_now_and_its_file_ids_but_keeps_its_own(language):
    v = view(language, 2)
    cards = needs.entries(v)
    needs.stop_asking(language, [cards[0].key])
    needs.put_off(language, [cards[1].key])
    needs.mark_seen(language, ["item:1", "line:offline:N:"])
    needs.answer(language, ["item:2"])
    needs.offer(language)
    assert needs.keep_to_library(language, "store-a") == 0      # the first library named: every answer is its own
    assert needs.read_hidden(language) == {cards[0].key, cards[1].key}
    before = os.stat(needs.seen_path(language)).st_mtime_ns
    assert needs.keep_to_library(language, "store-a") == 0      # the same library: nothing written (S19)
    assert os.stat(needs.seen_path(language)).st_mtime_ns == before
    assert needs.keep_to_library(language, None) == 0           # no library known yet: nothing judged
    assert needs.keep_to_library(language, "store-b") == 4      # a new library: its ids name other files
    assert needs.read_hidden(language) == frozenset()
    assert needs.read_seen(language) == {"line:offline:N:"}     # a line's key isn't an id: kept
    assert needs.read_answered(language) == frozenset()
    assert needs.read_offers(language) == {needs.FIRST_CARDS}   # a step's offer stays answered once
    needs.stop_asking(language, [cards[0].key])
    assert needs.read_hidden(language) == {cards[0].key}        # the new library's own answers count
    assert needs.keep_to_library(language, "store-b") == 0


# --- alpha 5 (Mado): the Needs-you counts read with a thousands comma -------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_alpha5_counts_of_a_thousand_or_more_read_with_a_comma(language):
    """3,000 shows with a file gone, not settled (no library card): the bulk line and its answers say *3,000*, never
    *3000*; a folder's show list says *and 1,000 more*; a small count reads as before."""
    out = needs.entries(view(language, 3000))
    bulk = out[0]
    assert bulk.kind == needs.BULK and bulk.title == "3,000 files are gone in 3,000 shows"
    assert bulk.data["labels"]["remove_all"] == "Forget every missing file (3,000)"
    assert bulk.data["labels"]["keep_all"] == "Keep all their words (3,000)"
    titles = [f"{names(language)[i % len(names(language))]} {i}" for i in range(1003)]
    assert needs._shows(titles).endswith(" and 1,000 more")
    assert needs._shows(titles[:5]).endswith(" and 2 more")
    assert needs.STRINGS["anki_n"].format(n=1200) == "1,200 episodes"


# --- A5K-2 (Sonic ✅ 2026-10-28): the library folder emptied under its record ------------------------------------- #
NOTE = {"at": "2026-10-28T22:04:37.031967Z", "files": 3895}


@pytest.mark.parametrize("language", LANGUAGES)
def test_a5k2_the_emptied_folder_is_one_card_first_start_fresh_or_keep_my_old_library(language):
    """The store's note is ONE card leading the page — before K1's, the bulk line and every show's — with *Start
    fresh* and *Keep my old library*, its files counted with a comma; no note, no card."""
    out = needs.entries(view(language, 30), emptied=NOTE, settled=True)
    first = out[0]
    assert first.kind == needs.LIBRARY_EMPTIED and first.actions == ("start_fresh", "keep_old")
    assert first.title == "Your library folder was emptied: sort your library again?"
    assert "(3,895 files)" in first.say and first.unseen and first.lines == ()
    assert out[1].kind == needs.LIBRARY_GONE                                  # K1's follows when it holds too
    assert all(e.kind != needs.LIBRARY_EMPTIED for e in needs.entries(view(language, 30), emptied=None))


@pytest.mark.parametrize("language", LANGUAGES)
def test_a5k2_keep_my_old_library_hides_it_for_good_and_a_new_emptying_asks_again(language, tmp_path, monkeypatch):
    """*Keep my old library* = *Stop asking* on its key (the seen file, its Undo): hidden from then, never pruned by
    a gather (its key names the note's time, a kind no prune judges); emptied again later — a new note — it asks."""
    monkeypatch.setenv("SURASURA_TEST_ROOT", str(tmp_path))
    key = needs.entries(None, emptied=NOTE)[0].key
    assert key == f"emptied:{NOTE['at']}"
    needs.stop_asking(language, [key])
    hidden = needs.read_hidden(language)
    assert key in hidden and needs.entries(view(language, 2), emptied=NOTE, hidden=hidden)[0].kind != \
        needs.LIBRARY_EMPTIED
    needs.prune(language, view(language, 2))
    assert key in needs.read_hidden(language)                               # kept: no prune judges it
    later = dict(NOTE, at="2026-11-02T08:00:00.000001Z")
    assert needs.entries(view(language, 2), emptied=later, hidden=needs.read_hidden(language))[0].kind == \
        needs.LIBRARY_EMPTIED
