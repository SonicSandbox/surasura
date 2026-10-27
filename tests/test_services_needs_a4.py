"""Alpha 4's *Needs you* (Mattias #4, Sonic 2026-10-27): `app/services/needs.py`, Qt-free, with real Japanese and
Chinese titles from tests/Test Resources/ — the seen file read while it is written (the keep_waiting flake), *Not now*
(back the next day) and *Stop asking* (never again, with Undo), one line for many cards that share a reason, the line
for every missing file, and the card for a library whose files are mostly gone (K3).

What a wrong answer would cost a learner: an answer lost because the file was being read as it was written (*Keep
waiting* that keeps nothing, a card that comes back after a restart); a card that can't be put away, or one put away
for ever when he only said "not now"; a hundred cards with no one answer for them; a dead library offered file by file.
"""
import time
from types import SimpleNamespace

import pytest

from app.services import needs
from tests.test_library_store_support import LANGUAGES, names

GONE = "Library/{t}/{t} - {n:02d}.srt"


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


# --- K3: most of the library's files gone ------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_library_whose_files_are_mostly_gone_is_one_card_on_top_only_when_its_answers_are_there(language):
    dead = view(language, 40, missing=30)
    assert needs.LIBRARY_GONE not in [e.kind for e in needs.entries(dead)]          # Kura's calls absent: no card
    out = needs.entries(dead, library_gone=True)
    assert out[0].kind == needs.LIBRARY_GONE and out[0].title == "Most of this library's files are gone (30 of 40)"
    assert out[0].actions == ("find_library", "start_fresh")
    few = view(language, 40, missing=10)                                             # a quarter: each show's card
    assert needs.LIBRARY_GONE not in [e.kind for e in needs.entries(few, library_gone=True)]
    small = view(language, 6)                                                       # 6 of 6, but only 6
    assert needs.LIBRARY_GONE not in [e.kind for e in needs.entries(small, library_gone=True)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_library_on_a_drive_only_offline_is_never_called_gone(language):
    dead = view(language, 40)
    root = needs.Root(path="E:\\Anime", rel="Library", label="Drive E:", files=40)
    out = needs.entries(dead, offline_roots=[root], library_gone=True)
    assert needs.LIBRARY_GONE not in [e.kind for e in out]


def test_3000_cards_are_worked_out_off_the_window_in_well_under_a_second():
    """The gather (a worker's) at Mattias's size: 3,000 shows with a file gone."""
    t = time.perf_counter()
    out = needs.entries(view("ja", 3000), hidden=frozenset(), library_gone=True)
    assert time.perf_counter() - t < 1.0
    assert out[0].kind == needs.LIBRARY_GONE and sum(1 for e in out if e.kind == needs.GONE) == 3000
