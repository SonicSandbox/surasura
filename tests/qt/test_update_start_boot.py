"""UPDATE-START (3.0.21, PROVISIONAL): the window boots at the first screen's cache, whatever its numbers wait on.

Every start used to boot only after the numbers' first answer and the library reader's first full read: the cached
first screen was shown at once, but built *loading*, so it never counted (`ShellWindow.show_library`). On a laptop an
ordinary start booted 6-8 s after the process began, and the first start after an update — the plan another engine
wrote, its staleness answered first — up to ~20 s; until then nothing in the background started. Now the cached first
screen boots the window at its paint (its numbers faded until the fresh answer lands), and the one press that needs
what the cache doesn't hold — a title's last ✓ Done, whose rule reads Goal, New arrivals and Finished — marks the file
at once, says *updating your library…*, and is asked again on the first view from disk (`DragMoves._from_disk`).

What a wrong answer would cost a learner: a window that looks open but starts nothing for many seconds after every
update; or, the other way, a last Done on the cache that offers *finished with it?* for a title that should have
finished or joined its next part by itself — or that is dropped.

The boot half runs a real `library_store` (a migrated library of real Japanese and Chinese show names, tests/Test
Resources) with a plan of real words, the reader's own cache written by an earlier window, and the numbers' load held
at a gate the test opens. The Done half runs on the window seed (tests/qt/test_drag.py's `world`), ja + zh.
"""
import os
import threading

import pytest

from app import settings_manager
from app.qt import strings
from app.services import moves as M
from tests.qt.test_boot_first import STARTED, _Reader, _started, gated, lines, wait_until  # noqa: F401
from tests.qt.test_drag import _all_but_one, calls, rows_of, world  # noqa: F401
from tests.test_library_store_support import LANGUAGES, migrated, roots
from tests.test_window_numbers_gc import _wait, _write_plan


@pytest.fixture
def held(monkeypatch):
    """The numbers' load, open until the test closes it (`held.clear()`), then held until it opens it again."""
    g = threading.Event()
    g.set()
    real = M.Numbers._load_plan

    def load(self):
        assert g.wait(30), "the test never opened the gate"
        return real(self)
    monkeypatch.setattr(M.Numbers, "_load_plan", load)
    yield g
    g.set()


@pytest.fixture
def library(language, held, tmp_path):
    """-> make(): (numbers, reader) over a migrated store and a plan of real words, the first screen's cache in
    `tmp_path` (the same file each window), nothing started."""
    store = migrated(language)
    with store:
        order = store.scheduled_ids()
        rel = {i: store.item(i)["rel_path"] for i, _t in order}
    plan_file = os.path.join(roots(language)[1], "plan.json.gz")
    _write_plan(plan_file, [rel[i] for i, _t in order], [t for _i, t in order], language)
    cache = str(tmp_path / "first_screen.json")
    made = []

    def make():
        _opener, numbers, reader = M.open_library(language, cache_file=cache, poll=0.02)
        numbers.plan_file = plan_file
        made.append((numbers, reader))
        return numbers, reader
    yield make
    for numbers, reader in made:
        reader.stop(timeout=30)
        numbers.idle(30)
        numbers.close()


def _last_window(make):
    """An earlier window's session: its list with numbers, its cache written as it closes."""
    numbers, reader = make()
    numbers.load()
    reader.start()
    assert _wait(lambda: reader.view() is not None and not reader.view().cached and
                 (reader._numbers_version or 0) >= 1, 30), numbers.why()
    reader.stop(timeout=30)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_start_whose_numbers_are_slow_still_boots_at_the_cached_screens_paint(language, library, held, gated,
                                                                                lines):
    _last_window(library)
    held.clear()                                            # this start's numbers: slow (the update's stale plan)
    numbers, reader = library()
    numbers.load()
    reader.start()
    assert _wait(lambda: reader.view() is not None, 10), "the first screen's cache, shown at once"
    first = reader.view()
    assert first.cached and first.rows, "the cache an earlier window wrote"
    gated.win.language = language                           # (the stand-in window's: a view of another is dropped)
    gated.services.library = _Reader(first)
    gated.win.start_duties()
    gated.win.show_library(first)
    assert wait_until(lambda: gated.services.boot.is_set()), "booted at the cache's paint, its numbers still out"
    assert numbers.wait_first(0) is False and reader.view().cached, "(nothing from disk yet: the numbers held)"
    assert wait_until(lambda: set(_started(gated)) == set(STARTED)), "the background goes after the boot as before"
    assert len([m for a, m in lines if a == "shell" and m.startswith("booted")]) == 1
    held.set()
    assert _wait(lambda: not reader.view().cached, 30), numbers.why()
    gated.win.show_library(reader.view())
    assert any(a == "shell" and m.startswith("the list from disk drawn") for a, m in lines), \
        "the list from disk, after a boot at the cache, still says when it came (a Send report reads it)"
    gated.win.show_library(reader.view())
    assert len([m for a, m in lines if m.startswith("the list from disk drawn")]) == 1, "said once"


def test_a_view_still_loading_with_no_cache_is_still_no_boot(gated, lines):
    """Neither the cache nor the list from disk (a store still opening, no first screen saved): no boot until one,
    or until its limit."""
    from tests.qt.test_boot_first import _settle, _view
    gated.services.library = _Reader(_view(loading=True))
    gated.win.start_duties()
    gated.win.show_library(_view(loading=True))
    _settle()
    assert not gated.services.boot.is_set() and _started(gated) == []


def _cached(win):
    """The window shown its first screen's cache: Current's own view as the reader builds it from the cache
    (`view_rows.from_cache`: *loading*, `cached`)."""
    view = win.page_widgets["current"].view_model
    cached = view._replace(cached=True, loading=True, state="loading", finished=(), needs=())
    win.show_library(cached)
    assert win.page_widgets["current"].view_model.cached
    return cached


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_last_done_on_the_cache_marks_at_once_and_finishes_once_the_list_is_read(world, language):
    settings_manager.save_keys({"target_language": language})      # the window's language is its library's (P0)
    seed, win, writer = world(language=language)
    row = _all_but_one(seed, win, 4)
    _cached(win)
    win.moves.done(row, row.episodes[-1])
    assert [c[0] for c in calls(writer)] == ["set_watched"], "the mark goes at once: never refused, never held"
    assert win.toasts.card.base == strings.DONE_UPDATING.format(
        text=strings.DONE_ONE.format(title=row.title, ep=row.episodes[-1].label)), "it says it's updating"
    assert row.key in win.moves._fresh_asking
    win.show_library(seed_view := win.moves.reader.view())   # the list from disk lands (the reader's own view)
    assert not seed_view.cached
    assert wait_until(lambda: [c[0] for c in calls(writer)] == ["set_watched", "set_tier"], 3), \
        "R3 on the view from disk: it finishes by itself, as the same Done would have from disk"
    assert win.moves._fresh_asking == {}


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_list_read_before_the_marks_write_lands_still_finishes_it(world, language):
    """The store still busy with the mark when the list from disk arrives (it shows the file unwatched): asked as the
    press would have been — its own mark counted watched, its own write no other command on its way — so it finishes."""
    settings_manager.save_keys({"target_language": language})
    seed, win, writer = world(language=language)
    row = _all_but_one(seed, win, 4)
    _cached(win)
    writer.stuck = True
    win.moves.done(row, row.episodes[-1])
    assert win.moves.tickets, "(the mark still on its way)"
    fresh = win.moves.reader.view()
    assert not fresh.cached and not next(r for r in fresh.rows if r.key == row.key).episodes[-1].watched
    win.show_library(fresh)
    assert wait_until(lambda: [c[0] for c in calls(writer)] == ["set_watched", "set_tier"], 3)
    writer.free()


@pytest.mark.parametrize("language", LANGUAGES)
def test_up_next_done_on_the_cache_with_every_file_watched_waits_then_finishes(world, language):
    settings_manager.save_keys({"target_language": language})      # the window's language is its library's (P0)
    seed, win, writer = world(language=language)
    row = rows_of(win)[4]
    seed.library.commit(items=[{"id": e.id, "watched": 1} for e in row.episodes])
    assert wait_until(lambda: all(e.watched for e in rows_of(win)[4].episodes), 3)
    row = rows_of(win)[4]
    _cached(win)
    win.moves.done(row, None)
    assert calls(writer) == [], "nothing to mark, nothing offered from the cache"
    win.show_library(win.moves.reader.view())
    assert wait_until(lambda: [c[0] for c in calls(writer)] == ["set_tier"], 3)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_done_on_the_cache_whose_mark_is_undone_first_is_let_go(world, language):
    settings_manager.save_keys({"target_language": language})      # the window's language is its library's (P0)
    seed, win, writer = world(language=language)
    row = _all_but_one(seed, win, 4)
    _cached(win)
    win.moves.done(row, row.episodes[-1])
    win.toasts.card.buttons[0].click()                                  # its toast's Undo, before the list is read
    assert wait_until(lambda: "set_watched" in [c.op for c in writer.undone], 3)
    win.show_library(win.moves.reader.view())
    wait_until(lambda: False, 0.3)
    assert "set_tier" not in [c[0] for c in calls(writer)], "an undone mark finishes nothing later"
    assert win.moves._fresh_asking == {}


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_file_unwatched_again_before_the_list_is_read_finishes_nothing(world, language):
    """Another file of the title marked not watched meanwhile (another window, an older Undo): the view from disk
    shows a file still to watch, so nothing finishes by itself."""
    settings_manager.save_keys({"target_language": language})
    seed, win, writer = world(language=language)
    row = _all_but_one(seed, win, 4)
    _cached(win)
    win.moves.done(row, row.episodes[-1])
    first = row.episodes[0].id
    seed.library.commit(items=[{"id": first, "watched": 0}])
    assert wait_until(lambda: not next(e for r in win.moves.reader.view().rows for e in r.episodes
                                       if e.id == first).watched, 3)
    win.show_library(win.moves.reader.view())
    wait_until(lambda: False, 0.3)
    assert [c[0] for c in calls(writer)] == ["set_watched"] and win.moves._fresh_asking == {}

