"""Michi-NT (Mattias, problem reports #XP44T6 / #7J3960): *Not timed* had no press — his picture shows Re:Zero S04E16's
row reading "⧗ Not timed" with no button, and with its *Needs you* entry dismissed there was no tab to find *Mine
anyway* in. After fixing the subtitle he could not ask Surasura to look again.

Here, the window's side: a *Not timed* status (listed, or its entry dismissed: `feed.SKIPPED`) is a *Check again*
button on its pill and on the episode's ⋯ (`rows.action_of`, `mine_actions.check_again`); pressed, its pill turns at
once — painted before the worker is handed `actions.check_again` (the entry fixed, the job queued, Connect kicked) —
until its status moves; nothing to check again: the pill is its own again and the bar says so; Connect off: nothing
is asked and the tip says why. Connect's own side: `tests/connect/test_nt_not_timed_again.py`.

What a wrong answer would cost: a learner who fixed the subtitle staring at a status with nothing to press (3.0.2);
or a press that turns for ever, or asks for episodes that aren't waiting on their timing.

On the window's seed (Japanese titles) through a recording writer (`test_p41_actions`'s), and on statuses built as
`view_rows` builds them.
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from app.connect import feed
from app.qt import mine_actions, rows, strings
from app.services import press as press_service
from app.services import view_rows
from tests.qt.conftest import wait_until
from tests.qt.test_p41_actions import act, asks, click, lst_of, parts_of    # noqa: F401  (act: a fixture)

PLAIN = view_rows.Status("waiting", "Waiting", "In your top 20: it mines by itself, in turn", "dim")
SAID = "Example Show - 16: Its timing changes part-way through the video, so no cards."


def _status(kind=feed.NOT_TIMED):
    item = feed.Item(kind=kind, words=feed.WORDS[kind], tip=SAID if kind == feed.NOT_TIMED else feed.WORDS[kind],
                     job=51, made=0, total=10)
    return view_rows._connected(PLAIN, item, "video")


def _ep(st, n=16):
    return view_rows.Episode(id=n, label=f"Ep {n}", number=n, title="Re:ゼロから始める異世界生活", watched=False,
                             cards=0, mining=False, missing=False, removed=False, in_top=True, pct=0, n_new=0,
                             status=st, mark=None, rel_path=f"HighPriority/rezeroS04/S04E{n}.ja.srt", play_tip="",
                             can_play=True)


def test_not_timed_listed_or_dismissed_is_a_check_again_button_for_those_files_with_its_click_said():
    for kind in (feed.NOT_TIMED, feed.SKIPPED):
        st = _status(kind)
        name, tip, ask = rows.action_of(st, (_ep(st),), None, "video")
        assert name == rows.CHECK and ask.ids == (16,), kind
        assert tip == strings.ROWS_CHECK_AGAIN_TIP[True].format(tip=rows.status_tip(st)), kind
    assert rows.CHECK in rows.ASKS and rows.asks_connect(rows.CHECK, "video")
    assert strings.ROWS_ACTION_NAMES[rows.CHECK] == "Check again"


def test_a_rows_check_again_names_only_its_not_timed_episodes():
    nt, waiting = _status(), PLAIN
    eps = (_ep(nt, 16), _ep(waiting, 17), _ep(_status(feed.SKIPPED), 18), _ep(waiting, 19))
    name, tip, ask = rows.action_of(nt, eps, None, "video")
    assert name == rows.CHECK and ask.ids == (16, 18), "never the episodes waiting their turn"
    assert tip == strings.ROWS_CHECK_AGAIN_TIP[False].format(tip=rows.status_tip(nt), n=2)
    being_mined = (_ep(nt, 16)._replace(mining=True),)
    assert rows.action_of(nt, being_mined, None, "video")[0] == "status", "nothing to check: a plain status"


def test_connect_off_check_again_asks_nothing_and_says_why():
    st = _status()
    name, tip, _ask = rows.action_of(st, (_ep(st),), feed.OFF_CONNECT, "video")
    assert name == rows.CHECK and tip == strings.ROWS_ACTION_OFF.format(tip=rows.status_tip(st), why=feed.OFF_CONNECT)


def _not_timed_row(lst, kind=feed.NOT_TIMED):
    """A closed Current row (not Up Next) whose first episode Connect found not timed, scrolled to the top: (its
    index, the row)."""
    st = _status(kind)
    entries = list(lst.model().entries)
    i = next(n for n, e in enumerate(entries) if e[0] == rows.ROW and e[1].episodes and e[1].media_word == "video")
    row = entries[i][1]
    eps = type(row.episodes)((e._replace(status=st, cards=0, mining=False, deleted=False, missing=False) if k == 0
                              else e) for k, e in enumerate(row.episodes))
    row = row._replace(status=st, episodes=eps)
    entries[i] = (rows.ROW, row, entries[i][2])
    lst.set_entries(entries)
    lst.scrollTo(lst.model().index(i, 0), lst.ScrollHint.PositionAtTop)
    QApplication.processEvents()
    return i, row


def _watch(win, monkeypatch, answer=None):
    """The check handed over (`mine_actions`' worker call) recorded at the hand-over: the files Current's list shows
    turning then, and whether the window's press was live. The stand-in answers `answer` (None: every file queued)."""
    lst = lst_of(win)
    seen, calls = [], []
    real = mine_actions.bridge.run_in_worker

    def handed(fn, *args, **kw):
        if fn is win.mine.check_job:
            seen.append((set(lst.pressed_ids), win.presses.any_live()))
        return real(fn, *args, **kw)
    monkeypatch.setattr(mine_actions.bridge, "run_in_worker", handed)
    win.mine.check_job = lambda language, ids, settings: (calls.append((language, list(ids))),
                                                          list(ids) if answer is None else answer)[1]
    return seen, calls


def _check_part(lst, i):
    return next((p for p in parts_of(lst, i) if p[0] == rows.CHECK), None)


@pytest.mark.parametrize("kind", [feed.NOT_TIMED, feed.SKIPPED])
def test_check_again_on_the_pill_turns_it_before_the_worker_and_asks_for_that_file(act, monkeypatch, kind):
    _seed, win, writer = act()
    lst = lst_of(win)
    monkeypatch.setattr(win.services.status, "refresh_soon", lambda *names: None)
    i, row = _not_timed_row(lst, kind)
    seen, calls = _watch(win, monkeypatch)
    part = _check_part(lst, i)
    assert part is not None, "the row's pill is a button now"
    click(lst, part)
    ep = row.episodes[0]
    assert seen and seen[0] == ({ep.id}, True), "turning, and the press live, before the worker runs"
    assert wait_until(lambda: calls == [(win.language, [ep.id])])
    assert asks(writer) == [], "never an ask of the store (no toast, nothing to undo)"
    assert lst.pressed_ids == {ep.id}, "it turns until its status moves (Connect's feed)"


def test_nothing_to_check_again_puts_the_pill_back_and_says_so(act, monkeypatch):
    _seed, win, _writer = act()
    lst = lst_of(win)
    i, row = _not_timed_row(lst)
    _seen, calls = _watch(win, monkeypatch, answer=[])
    click(lst, _check_part(lst, i))
    press = win.presses.find(f"check:{win.language}:{row.episodes[0].id}")
    assert wait_until(lambda: press.state == press_service.FAILED)
    assert not lst.pressed_ids and win.bar_line.full() == strings.CHECK_AGAIN_NOTHING


def test_a_worker_that_fails_puts_the_pill_back_and_says_why(act, monkeypatch):
    _seed, win, _writer = act()
    lst = lst_of(win)
    i, row = _not_timed_row(lst)
    _watch(win, monkeypatch)

    def broken(language, ids, settings):
        raise OSError("the ledger can't be opened")
    win.mine.check_job = broken
    click(lst, _check_part(lst, i))
    assert wait_until(lambda: win.bar_line.full().startswith(strings.CHECK_AGAIN_FAILED.split("{")[0]))
    assert not lst.pressed_ids


def test_the_episodes_menu_offers_check_again_where_its_pill_is_check_again(act, monkeypatch):
    _seed, win, _writer = act()
    lst = lst_of(win)
    monkeypatch.setattr(win.services.status, "refresh_soon", lambda *names: None)
    i, row = _not_timed_row(lst)
    ep = row.episodes[0]
    entry = [e for e in win.items.episode_entries(row, ep) if e.name == "ep-" + rows.CHECK]
    assert [(e.label, e.ok) for e in entry] == [("Check again", True)]
    assert entry[0].tip == rows.action_of(ep.status, (ep,), None)[1], "the pill's own words"
    seen, calls = _watch(win, monkeypatch)
    win.items.episode_pick(row, ep, entry[0].name, entry[0].payload)
    assert seen and seen[0] == ({ep.id}, True)
    assert wait_until(lambda: calls == [(win.language, [ep.id])])


def test_connect_off_the_pill_and_the_menu_check_nothing(act, monkeypatch):
    _seed, win, _writer = act(connect_off=feed.OFF_CONNECT)
    lst = lst_of(win)
    i, row = _not_timed_row(lst)
    seen, calls = _watch(win, monkeypatch)
    click(lst, _check_part(lst, i))
    win.mine.check_again(rows.Ask(row.episodes[0].id, (row.episodes[0].id,), row.episodes[0]))
    QApplication.processEvents()
    assert seen == [] and calls == [] and not lst.pressed_ids
    assert win.bar_line.full() == feed.OFF_CONNECT
