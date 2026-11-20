"""A row that looks like a show you already have offers *Join <show>*, and *Same show as…* reaches the shows inside a
group (Kura-HJ, 3.0.17; a Send report of 2026-11-19 — Sonic ruled both: one press, Undo).

Why these matter: the report's hato episodes stood as their own row ("Hato/<show> · Ep 5–7") beside
the real show, and there was no way to join them: *Same show as…* lists only shows standing in a row of their own,
and the real show sat inside a group ("<show> + 2 more"), so it was never offered. What a wrong
answer would cost: a learner who sees the same show twice and can't make it one; a join with no Undo; or a *Join*
offered for a show of another name (a wrong merge). The store's own heal (`test_library_store_hato_series.py`) makes
these rare; this is the learner's own way for the rest.
"""
from app.qt import drag, item_menu, strings
from tests.qt.conftest import wait_until
from tests.qt.test_item_menu import (_same_show, _state, calls, real, rows_of, settle, two_shows,  # noqa: F401
                                     world)


def _join_show(win, row):
    return next((e for e in win.items.entries(row) if e.name == "join-show"), None)


def _retitled(win, i, title):
    """Row `i` shown under another name (the rest of the view as it was) -> the row."""
    view = win.page_widgets["current"].view_model
    rs = list(view.rows)
    rs[i] = rs[i]._replace(title=title)
    win.show_library(view._replace(rows=type(view.rows)(rs)))
    settle()
    return rows_of(win)[i]


def _grouped(win, i):
    """Row `i` shown as a group of its show and one more, its episodes naming their show as `view_rows._group` makes
    them (each its own work and show name) -> the group row."""
    view = win.page_widgets["current"].view_model
    rs = list(view.rows)
    r = rs[i]
    eps = tuple(e._replace(work_id=r.work_id, show=r.title) for e in r.episodes)
    rs[i] = r._replace(group=True, works=(r.work_id, 987654), title=f"{r.title} + 1 more", episodes=eps)
    win.show_library(view._replace(rows=type(view.rows)(rs)))
    settle()
    return rows_of(win)[i]


def test_a_row_named_like_a_show_already_there_offers_join_show_first_and_one_press_joins_with_undo(world):
    """`Hato/<show>` (the old rule's name) and `<show>!` (punctuation apart) both read as `<show>`: *Join <show>* is
    the first entry of the row's own ⋯ (its tooltip says what it does and that Undo takes it back); one press is the
    same merge as *Same show as…* with no question — the picked show keeps its name — and its toast carries Undo."""
    _seed, win, writer = world()
    b, a = two_shows(win)
    show = rows_of(win)[a]
    assert _join_show(win, rows_of(win)[b]) is None, "a show of another name: no Join"
    for name in (f"Hato/{show.title}", f"{show.title}!"):
        row = _retitled(win, b, name)
        entry = win.items.entries(row)[0]
        assert entry.name == "join-show" and entry.ok
        assert entry.label == strings.ITEM_MENU["join-show"][0].format(title=show.title)
        assert entry.tip == strings.ITEM_MENU["join-show"][1].format(title=show.title) and "Undo" in entry.tip
        assert entry.payload.work_id == show.work_id
    win.items.menu_pick(row, "join-show", entry.payload)
    assert win.items.question is None, "one press, no question"
    assert calls(writer) == [("merge_works", [], {"keep_id": show.work_id, "other_ids": [row.work_id]})]
    assert wait_until(lambda: win.toasts.card.message == strings.ITEM_SAME_SHOW_DONE.format(b=row.title,
                                                                                           a=show.title), 5)
    assert win.toasts.card.buttons, "its Undo"


def test_same_show_as_reaches_a_show_inside_a_group_and_join_show_finds_it_there(world):
    """The report's case: the show stands inside a group. *Same show as…* lists it by its own name (never the group's),
    where the group stands; a row named like it offers *Join <show>* for that show."""
    _seed, win, _writer = world()
    b, a = two_shows(win)
    show = rows_of(win)[a]
    group = _grouped(win, a)
    picks = [c.payload for c in _same_show(win, rows_of(win)[b]).children]
    inside = [s for s in picks if s.work_id == show.work_id]
    assert len(inside) == 1 and inside[0].title == show.title and inside[0].key == group.key
    assert group.title not in [s.title for s in picks], "the group is no show of its own"
    assert inside[0].where == strings.ITEM_JOIN_WHERE[group.tier if group.tier == "soon" else "now"].format(n=a + 1)
    assert _same_show(win, group) is None and _join_show(win, group) is None, "a group's ⋯ is no one show's"
    row = _retitled(win, b, f"Hato/{show.title}")
    assert _join_show(win, row).payload.work_id == show.work_id


def test_two_shows_of_that_name_offer_no_join_same_show_as_asks_which(world, monkeypatch):
    """Two shows the row's name could mean (two titles of one name the learner kept apart): no *Join*, *Same show as…*
    still lists both."""
    _seed, win, _writer = world()
    b, a = two_shows(win)
    show = rows_of(win)[a]
    row = _retitled(win, b, show.title)
    twin = item_menu.Show("twin", 424242, show.title, strings.ITEM_JOIN_WHERE["goal"])
    real_shows = win.items.same_shows
    monkeypatch.setattr(win.items, "same_shows", lambda r: real_shows(r) + [twin])
    assert _join_show(win, row) is None
    assert {s.work_id for s in win.items.same_shows(row) if s.title == show.title} == {show.work_id, 424242}


def test_real_store_join_show_makes_one_title_and_one_undo_makes_two(real):
    """On the store: a show the window shows as `Hato/<show>` (a title an older version named by hato's folder) —
    *Join <show>* makes its files the show's (no file moves, nothing changes section) and the toast's Undo makes two."""
    store, win, _writer = real()
    b, a = two_shows(win)
    show, row = rows_of(win)[a], rows_of(win)[b]
    store.rename_work(row.work_id, f"Hato/{show.title}")      # the name the old rule gave hato's folder
    assert wait_until(lambda: any(r.key == row.key and r.title == f"Hato/{show.title}" for r in rows_of(win)), 5)
    row = next(r for r in rows_of(win) if r.key == row.key)
    before = _state(store)
    entry = _join_show(win, row)
    assert entry is not None and entry.payload.work_id == show.work_id
    win.items.menu_pick(row, "join-show", entry.payload)
    assert wait_until(lambda: {store.item(i)["work_id"] for i in drag.ids_of(row)} == {show.work_id}, 5)
    assert _state(store)[0] == before[0], "no file changes section or place"
    assert wait_until(lambda: win.toasts.card.message == strings.ITEM_SAME_SHOW_DONE.format(b=row.title,
                                                                                           a=show.title), 5)
    win.toasts.card.buttons[0].click()
    assert wait_until(lambda: _state(store) == before, 5)
