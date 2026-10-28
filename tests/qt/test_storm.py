"""The window while the library grows under it (alpha 4, A2 + A4; Mattias #8: "the window drags while background work
runs"; Sonic: "New arrivals feels slow when adding"). A + Add, a source look or an import commits in the store's batches
(≤ 200 files a command) while the window is open; a learner reading Current must not pay for each batch.

What a wrong answer would cost a learner: a window that stutters for the whole length of an import — every batch a view
built and every page diffed, a show landing anywhere resetting the list (the hover, the keyboard's row and the scroll
place lost, every row on screen repainted) — at 20,000 files several times a second.

The counts must not grow with the library: views at most four a second, Current never reset, no row drawn afresh on a
page whose rows didn't change. `tests/qt/bench_storm.py` is the harness (and the bench at 20,000 + 20,000).
"""
import pytest

pytest.importorskip("PyQt6")

from tests.fixtures import window_seed
from tests.qt import bench_storm


@pytest.fixture
def opened(qapp):
    made = []

    def make(files, language="ja"):
        seed = window_seed.build(files=files, language=language)
        win, services = bench_storm.open_window(qapp, seed)
        made.append((win, services))
        return seed, win
    yield make
    for win, services in made:
        win.close()
        services.shutdown(0.5)
    from app.qt import style
    style.apply(qapp, "night", "M", "ja")          # the harness puts back theme and size, not the language


@pytest.mark.parametrize("files,language", [(2000, "ja"), (2000, "zh"), (20000, "ja")])
def test_an_import_landing_while_the_window_is_open_costs_a_few_views_a_second_and_never_resets_current(opened, files,
                                                                                                         language):
    """2,000 more files in ten batches, 50 ms apart, into New arrivals, into shows' runs in Current and at Soon's end.
    Whatever the library's size: the reader hands the window at most four views a second (and the last batch is in
    the last view), Current's list is never reset — a show added is put in where it lands — Finished and Needs you
    are never relisted (nothing of theirs changed), and no row is drawn afresh on Finished."""
    seed, win = opened(files, language)
    out = bench_storm.run(win, seed, more=2000, batch=200, gap_s=0.05)
    assert out["settled"], out
    assert out["views"] <= out["views_bound"], out                     # ≤ ceil(seconds × 4) + 1
    assert out["shown"] <= out["views"] + 1
    cur, fin = out["pages"]["current"], out["pages"]["finished"]
    assert cur["resets"] == 0, cur
    assert cur["inserted"] > 0, cur                                     # the shows at Soon's end were put in
    assert fin["changed"] == 0 and fin["resets"] == 0 and fin["row_renders"] == 0, fin
    assert out["pages"]["needs"]["resets"] == 0
    landed = {r["id"] for r in seed.library.items()}
    shown = {e.id for r in win.page_widgets["current"].view_model.rows for e in r.episodes}
    shown |= {i for a in win.page_widgets["current"].view_model.arrivals for i in a.item_ids}
    current_or_arrivals = {r["id"] for r in seed.library.items() if r["tier"] in ("now", "soon", "arrivals")}
    missing = current_or_arrivals - shown
    assert not missing, sorted((r["id"], r["tier"], r["title"]) for r in seed.library.items() if r["id"] in missing)[:5]
    assert shown <= landed


def test_the_counts_do_not_grow_with_the_library(opened):
    """The same import at 2,000 and at 20,000 files: as many views (both bounded by the time), no reset at either, and
    Current's own work on the window's thread no more than a few times the small library's."""
    small_seed, small = opened(2000)
    a = bench_storm.run(small, small_seed, more=1000, batch=200, gap_s=0.05)
    big_seed, big = opened(20000)
    b = bench_storm.run(big, big_seed, more=1000, batch=200, gap_s=0.05)
    assert a["settled"] and b["settled"]
    for out in (a, b):
        assert out["views"] <= out["views_bound"], out
        assert out["pages"]["current"]["resets"] == 0, out
    assert b["pages"]["current"]["set_view"] <= a["pages"]["current"]["set_view"] + 3
