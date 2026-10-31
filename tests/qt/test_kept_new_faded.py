"""U-1 (Sonic, 2026-10-31: "show faded but without the updating. So only faded, that's all. Make sure that change
doesn't lag everything else so it's not a full redraw"): while the last Generate no longer matches the library, a row's
kept *N new* (the numbers' `moves.Kept` table) paints faded — no words, nothing else — and the fade comes and goes by
repainting only the rows whose look changes: the list's "same" refresh, never a reset or a relayout.

What a wrong answer would cost: every row redrawn (a hitch on a 20,000-file library each time a plan goes stale or
fresh); a row with no figure redrawn for nothing; a fade that sticks after the fresh plan, or never shows.
"""
from app.qt import rows
from app.services import moves, view_rows
from tests.qt.conftest import wait_until
from tests.qt.test_drag import world  # noqa: F401 (a fixture)


def _settle():
    for _ in range(25):
        wait_until(lambda: False, 0.02)


def _on_screen(lst):
    port = lst.viewport().rect()
    return [i for i in range(lst.model().rowCount()) if lst.visualRect(lst.model().index(i, 0)).intersects(port)]


def _shows_figure(entry):
    payload = entry[1]
    if entry[0] == rows.HERO:
        return payload.episodes[payload.next_index].n_new is not None
    return entry[0] == rows.ROW and payload.n_new is not None


def _publish(seed, table, changed=None):
    """A new numbers version; `changed` the item ids it changed (None: unknown), as `moves.Numbers.changed` says it —
    so the reader rebuilds only those rows (U-A2: the partial rebuild run end to end)."""
    n = seed.numbers
    n.table = table
    n.version += 1
    n.history[n.version] = changed


def _tracked(seed):
    n = seed.numbers
    n.history = {}

    def changed(since):
        if since == n.version:
            return set()
        out = set()
        for v in range(since + 1, n.version + 1):
            ids = n.history.get(v)
            if ids is None:
                return None
            out |= ids
        return out
    n.changed = changed


def _figured(table):
    return {i for i, (_k, _c, new) in table.items() if new is not None}


def test_the_fade_comes_and_goes_repainting_only_the_rows_that_show_a_figure(world):  # noqa: F811
    seed, win, _writer = world()
    lst = win.page_widgets["current"].list
    model = lst.model()
    _settle()
    _tracked(seed)
    bare = next(e[1] for i in reversed(_on_screen(lst)) for e in [model.entries[i]] if e[0] == rows.ROW)
    table = dict(seed.numbers.table)                                        # one row on screen with no figure
    for ep in bare.episodes:
        known, counted, _n = table.get(ep.id, (0, 0, None))
        table[ep.id] = (known, counted, None)
    _publish(seed, table)
    assert wait_until(lambda: any(e[1].key == bare.key and e[1].n_new is None for e in model.entries
                                  if e[0] == rows.ROW), 10)
    _settle()
    resets, layouts = [], []
    on_reset, on_layout = (lambda: resets.append(1)), (lambda *a: layouts.append(1))
    model.modelReset.connect(on_reset)
    model.layoutChanged.connect(on_layout)
    try:
        _the_fade(seed, lst, model, resets, layouts)
    finally:
        model.modelReset.disconnect(on_reset)
        model.layoutChanged.disconnect(on_layout)


def _the_fade(seed, lst, model, resets, layouts):
    shown = _on_screen(lst)
    figured = [i for i in shown if _shows_figure(model.entries[i])]
    plain = [i for i in shown if model.entries[i][0] == rows.ROW and not _shows_figure(model.entries[i])]
    assert figured and plain, "the seed shows rows with a figure and rows without one"
    kept_pix = {model.entries[i][1].key: lst.delegate._sprites["row"] for i in plain}
    before = {k: [v[1] for key, v in sprites.items() if key[1] == k] for k, sprites in kept_pix.items()}

    lst.delegate.renders = 0
    bare_obj = next(e[1] for e in model.entries if e[0] == rows.ROW and e[1].n_new is None)
    _publish(seed, moves.Kept(seed.numbers.table), _figured(seed.numbers.table))   # stale: figures kept, faded
    assert wait_until(lambda: all(getattr(model.entries[i][1], "new_faded", False) or model.entries[i][0] == rows.HERO
                                  for i in figured), 10)
    _settle()
    lst.viewport().repaint()
    assert resets == [] and layouts == [], "a 'same' refresh: never a reset or a relayout"
    assert 0 < lst.delegate.renders <= len(figured), (lst.delegate.renders, len(figured))
    assert any(e[1] is bare_obj for e in model.entries), "the bare row never rebuilt: the same object"
    for i in plain:                                                         # a row with no figure: its picture kept
        assert not model.entries[i][1].new_faded
        k = model.entries[i][1].key
        assert [v[1] for key, v in lst.delegate._sprites["row"].items() if key[1] == k] == before[k]

    lst.delegate.renders = 0
    _publish(seed, moves.Kept(seed.numbers.table), set())                  # still stale, nothing new: nothing drawn
    _settle()
    lst.viewport().repaint()
    assert lst.delegate.renders == 0

    lst.delegate.renders = 0
    _publish(seed, dict(seed.numbers.table), _figured(seed.numbers.table))  # the fresh plan: the fade goes
    assert wait_until(lambda: not any(getattr(model.entries[i][1], "new_faded", False) for i in figured), 10)
    _settle()
    lst.viewport().repaint()
    assert resets == [] and layouts == []
    assert 0 < lst.delegate.renders <= len(figured)


def test_a_kept_table_fades_each_figure_and_nothing_without_one():
    """`view_rows.build` over a `moves.Kept` table: every row and episode with a figure `new_faded`, none without one;
    over a plain table, none."""
    from tests.fixtures import window_seed
    seed = window_seed.build()
    h = seed.opener
    h.check()
    store = h.handle()
    feed = store.read_feed()
    assert feed is not None
    items = {r["id"]: r for r in feed["items"]}
    works = {w["id"]: w for w in feed["works"]}
    plain = view_rows.build(items, works, {}, numbers=(1, seed.numbers.table))
    kept = view_rows.build(items, works, {}, numbers=(2, moves.Kept(seed.numbers.table)))
    assert not any(r.new_faded for r in plain.rows)
    with_figure = [r for r in kept.rows if r.n_new is not None]
    assert with_figure and all(r.new_faded for r in with_figure)
    assert not any(r.new_faded for r in kept.rows if r.n_new is None)
    eps = [e for r in kept.rows for e in r.episodes]
    assert all(e.new_faded == (e.n_new is not None) for e in eps)
