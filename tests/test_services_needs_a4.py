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
    out = needs.entries(view("ja", 3000), library_gone=True)
    assert time.perf_counter() - t < 1.0
    assert out[0].kind == needs.LIBRARY_GONE and sum(1 for e in out if e.kind == needs.GONE) == 3000
