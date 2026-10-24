"""R47 (laptop rows 47 + 56, the window's half of Michi's #152): *Stop* on a *Mining* pill. Connect's seam is
`connect.actions.stop(language, job_id)` on a worker, offered only while `feed.Item.stoppable` and Connect may run;
`feed.Item.stopping` while it stops; then the item waits, its tip `runner.STOPPED_BY_YOU`, and *Mine now* goes on.
On the window's seed (Japanese titles), the stop handed to a stand-in (no ledger, no Connect).

What a wrong answer would cost a learner:
  * a *Mining 4%* pill that looks like a button and does nothing (row 56: his click reached nothing), or a Stop that
    paints nothing until Connect answers, so it is pressed again;
  * a Stop offered when it can't act (past the stop point, Connect off) — a press that silently fails;
  * *Stopping…* dropped before the job has stopped, or held after it — no *Mine now* to go on with;
  * a refused stop that leaves the pill saying *Stopping…*, or says nothing about why;
  * an ask Connect has read still shown as a plain *Waiting* (Sonic's case), its reason hidden.
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint, QRectF
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.connect import feed, runner
from app.qt import mine_actions, rows, strings
from app.services import press as press_service
from app.services import view_rows
from tests.qt.conftest import wait_until
from tests.qt.test_p41_actions import act, click, lst_of, parts_of    # noqa: F401  (act: a fixture)

JOB = 41
PLAIN = view_rows.Status("waiting", "Waiting", "In your top 20: it mines by itself, in turn", "dim")


def _item(kind=feed.MINING, tip="", job=JOB, stoppable=True, stopping=None, progress=None, doing=None):
    return feed.Item(kind, feed.WORDS[kind], tip or feed.WORDS[kind], job, 2, 12, progress, doing, stoppable, stopping)


def _mining(lst, item=None):
    """A closed Current row (not Up Next) made Connect's *Mining* — its first episode the one mined, as the feed makes
    it (`view_rows._connected`) — scrolled to the top: (its index, the row)."""
    st = view_rows._connected(PLAIN, item or _item(), "video")
    entries = list(lst.model().entries)
    i = next(n for n, e in enumerate(entries) if e[0] == rows.ROW and e[1].episodes and e[1].media_word == "video")
    row = entries[i][1]
    eps = type(row.episodes)((e._replace(status=st, cards=0, mining=True, deleted=False, missing=False) if k == 0
                              else e) for k, e in enumerate(row.episodes))
    row = row._replace(status=st, episodes=eps)
    entries[i] = (rows.ROW, row, entries[i][2])
    lst.set_entries(entries)
    lst.scrollTo(lst.model().index(i, 0), lst.ScrollHint.PositionAtTop)
    QApplication.processEvents()
    return i, row


def _moved(lst, key, status):
    """The reader's next view, as Connect's feed makes it: row `key`'s mined episode (and the row) now `status`."""
    entries = []
    for kind, row, lines in lst.model().entries:
        if kind == rows.ROW and row.key == key:
            row = row._replace(status=status, episodes=type(row.episodes)(
                (e._replace(status=status) if k == 0 else e) for k, e in enumerate(row.episodes)))
        entries.append((kind, row, lines))
    lst.set_entries(entries)


def _stop_part(lst, i):
    return next((p for p in parts_of(lst, i) if p[0] == rows.STOP), None)


def _watch_stop(win, monkeypatch, answer=True):
    """The stop handed over (`mine_actions`' worker call) recorded at the hand-over: whether the file was already
    marked *Stopping…* in Current's list, how often its viewport had painted, whether the window's press was live. The
    stand-in `actions.stop` answers `answer` (True: recorded; False: refused)."""
    from tests.qt.test_press import Paints
    lst = lst_of(win)
    paints = Paints(lst.viewport())
    QApplication.processEvents()
    seen, calls = [], []
    real = mine_actions.bridge.run_in_worker

    def handed(fn, *args, **kw):
        if fn is win.mine.stop_job:
            seen.append((set(lst.stopping_ids), paints.n, win.presses.any_live()))
        return real(fn, *args, **kw)
    monkeypatch.setattr(mine_actions.bridge, "run_in_worker", handed)
    win.mine.stop_job = lambda language, job: (calls.append((language, job)), answer)[1]
    return seen, calls, paints.n


# --- the feed in the statuses (Qt-free) ------------------------------------------------------------------------- #
def test_a_stoppable_mining_job_carries_its_stop_and_one_past_the_stop_point_says_it_is_finishing():
    """The pill is a Stop exactly while the feed says the job can be stopped (`stoppable`); once it names its clips
    (`stoppable` None) it is a plain *Mining* whose hover says it is finishing; while stopping it reads *Stopping…*."""
    st = view_rows._connected(PLAIN, _item(), "video")
    assert (st.kind, st.stop) == ("mining", JOB)
    pct = view_rows._connected(PLAIN, _item(progress=4, doing="Cutting clips"), "video")
    assert (pct.label, pct.stop) == ("Mining · 4%", JOB)
    late = view_rows._connected(PLAIN, _item(stoppable=None, progress=70, doing="Naming the clips"), "video")
    assert late.stop is None and late.label == "Mining · 70%"
    assert late.tip.endswith(view_rows.STRINGS["tip_finishing"])
    going = view_rows._connected(PLAIN, _item(stoppable=None, stopping=True), "video")
    assert (going.kind, going.label, going.tip, going.stop) == ("mining", "Stopping…",
                                                                view_rows.STRINGS["tip_stopping"], None)
    # a cached first screen never offers a Stop (Connect's state isn't known from a cache)
    cached = view_rows._row_from(view_rows._plain(view_rows.Row(*([None] * len(view_rows.Row._fields)))._replace(
        status=st, episodes=(), chips=(), works=(), next_index=0, media=None, key="k", source=None)))
    assert cached.status.stop is None and cached.status[:4] == st[:4]


def test_stop_is_offered_on_the_pill_only_while_stoppable_and_connect_may_run():
    """`rows.action_of`, the pill's and the ⋯'s one rule: *Stop* (its tip naming the click) with the mined file and its
    job; Connect off, or past the stop point, the status alone with its own tip."""
    st = view_rows._connected(PLAIN, _item(), "video")
    ep = view_rows.Episode(id=7, label="第7話", number=7, title="葬送のフリーレン", watched=False, cards=0, mining=True,
                           missing=False, removed=False, in_top=True, pct=0, n_new=0, status=st, mark=None,
                           rel_path="HighPriority/葬送のフリーレン/第7話.srt", play_tip="", can_play=True)
    name, tip, ask = rows.action_of(st, (ep,))
    assert name == rows.STOP and (ask.ids, ask.job) == ((7,), JOB)
    assert tip == strings.ROWS_STOP_TIP.format(tip=st.tip) and "cards made so far are kept" in tip
    assert rows.action_of(st, (ep,), feed.OFF_CONNECT)[::2] == ("status", None)
    late = view_rows._connected(PLAIN, _item(stoppable=None), "video")
    assert rows.action_of(late, (ep._replace(status=late),))[::2] == ("status", None)


def test_an_ask_connect_has_read_is_its_own_status_with_its_reason_and_a_turn_says_so_in_the_hover():
    """Sonic's case (scope §3.6): an asked job Connect has read is *Asked* — the pressed mark, still, no words, its
    hover the reason — never a plain *Waiting* (no second *Mine now* on it). A job waiting its turn says
    `runner.TURN`'s words in its hover."""
    asked = view_rows._connected(PLAIN, _item(feed.ASKED, stoppable=None), "video")
    assert (asked.kind, rows.pill_text(asked)) == ("asked", "")
    assert rows.status_tip(asked) == strings.ROWS_WAITING_TIP.format(label="Asked", tip="Its cards come next")
    behind = view_rows._connected(PLAIN, _item(feed.ASKED, tip=runner.TURN, stoppable=None), "video")
    assert rows.status_tip(behind).endswith(runner.TURN)
    assert rows.action_of(asked, ())[0] == "status"
    turn = view_rows._connected(PLAIN, _item(feed.WAITING, tip=runner.TURN, stoppable=None), "video")
    assert turn.kind == "waiting" and runner.TURN in rows.status_tip(turn)


def test_an_asked_pill_is_painted_as_the_pressed_mark_still(qapp, monkeypatch):
    """The *Asked* pill is the turning hourglass of the press, still (the same mark: the press goes on into it)."""
    from PyQt6.QtGui import QImage, QPainter
    marks = []
    monkeypatch.setattr(rows, "paint_pressed", lambda p, rect, turning, radius=None: marks.append((rect, turning)))
    img = QImage(80, 30, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    rows.paint_pill(p, view_rows._connected(PLAIN, _item(feed.ASKED, stoppable=None), "video"), QRectF(0, 0, 30, 22))
    p.end()
    assert marks == [(QRectF(0, 0, 30, 22), None)]


# --- the pill pressed --------------------------------------------------------------------------------------------- #
def test_stop_paints_stopping_on_the_pill_before_the_worker_and_holds_it_until_the_job_has_stopped(act, monkeypatch):
    """The press rule: a click on the *Mining* pill's Stop marks its file *Stopping…* and repaints it, and the
    window's press is live, before the stop is handed to the worker; a second click hands nothing. Recorded, the feed
    is looked at now. *Stopping…* holds through Connect's own *Stopping…* (`stopping`) and ends — the press done — only
    once the file leaves Mining: it waits, *Stopped: its cards so far are kept*, and its pill is *Mine now* again.
    Red first: the *Mining* pill was no button (row 56: the click reached nothing)."""
    _seed, win, writer = act()
    lst = lst_of(win)
    looked = []
    monkeypatch.setattr(win.services.status, "refresh_soon", lambda *names: looked.append(names))
    i, row = _mining(lst)
    ep = row.episodes[0]
    part = _stop_part(lst, i)
    assert part is not None and part[3].job == JOB
    seen, calls, before = _watch_stop(win, monkeypatch)
    click(lst, part)
    assert len(seen) == 1
    marked, painted, live = seen[0]
    assert marked == {ep.id} and painted > before and live           # Stopping… painted, the press live: then the work
    assert wait_until(lambda: calls == [(win.language, JOB)])
    assert wait_until(lambda: ("connect",) in looked)
    press = win.presses.find(f"stop:{win.language}:{JOB}")
    click(lst, part)                                                   # pressed again: nothing handed over
    QApplication.processEvents()
    assert len(seen) == 1 and press.live()
    assert next(p for p in parts_of(lst, i) if p[1] == part[1])[2] == view_rows.STRINGS["tip_stopping"]
    _moved(lst, row.key, view_rows._connected(PLAIN, _item(stoppable=None, stopping=True), "video"))
    assert lst.stopping_ids == {ep.id} and press.live()                 # Connect's own Stopping…: still held
    stopped = view_rows._connected(PLAIN, _item(feed.WAITING, tip=runner.STOPPED_BY_YOU, stoppable=None), "video")
    _moved(lst, row.key, stopped)
    assert not lst.stopping_ids and press.state == press_service.DONE and lst._turn is None
    assert rows.action_of(stopped, (ep._replace(status=stopped, mining=False),))[0] == "mine-now"
    assert runner.STOPPED_BY_YOU in rows.status_tip(stopped)


def test_stopping_is_painted_over_the_pill_and_the_hand_on_it_reads_stop(act, monkeypatch):
    """The look (PROVISIONAL): the hand on a stoppable pill paints *■ Stop* over it, pressed *Stopping…* over it — in
    the pill's own box (nothing moves); the hand leaving takes *■ Stop* off."""
    _seed, win, writer = act()
    lst = lst_of(win)
    monkeypatch.setattr(win.services.status, "refresh_soon", lambda *names: None)
    i, row = _mining(lst)
    part = _stop_part(lst, i)
    drawn = []
    real = rows.paint_stop
    monkeypatch.setattr(rows, "paint_stop", lambda p, rect, stopping, *a, **k: (drawn.append((QRectF(rect), stopping)),
                                                                                 real(p, rect, stopping, *a, **k)))
    QTest.mouseMove(lst.viewport(), part[1].center())
    QApplication.processEvents()
    assert lst.stop_hot is not None
    lst.viewport().repaint()
    assert any(not stopping and r.contains(QRectF(part[1]).center()) for r, stopping in drawn)
    QTest.mouseMove(lst.viewport(), QPoint(2, 2))
    QApplication.processEvents()
    assert lst.stop_hot is None
    drawn.clear()
    _watch_stop(win, monkeypatch)
    click(lst, part)
    assert any(stopping and r.contains(QRectF(part[1]).center()) for r, stopping in drawn)
    assert QRectF(part[1]) == QRectF(_stop_part(lst, i)[1] if _stop_part(lst, i) else
                                     next(p for p in parts_of(lst, i) if p[1] == part[1])[1])   # its box kept


def test_a_refused_stop_puts_the_pill_back_and_says_why_in_the_bar(act, monkeypatch):
    """Connect refused the stop (past its stop point, or the job gone: `actions.stop` False): the pill is its own
    again, the press failed, the bar says why — never *Stopping…* for good."""
    _seed, win, writer = act()
    lst = lst_of(win)
    monkeypatch.setattr(win.services.status, "refresh_soon", lambda *names: None)
    i, row = _mining(lst)
    _watch_stop(win, monkeypatch, answer=False)
    click(lst, _stop_part(lst, i))
    press = win.presses.find(f"stop:{win.language}:{JOB}")
    assert wait_until(lambda: press.state == press_service.FAILED)
    assert not lst.stopping_ids and win.bar_line.full() == strings.MINE_STOP_REFUSED
    assert _stop_part(lst, i) is not None                               # the Stop is there to press again


def test_no_stop_while_connect_is_off_or_past_the_stop_point_on_the_pill_or_in_the_menu(act, monkeypatch):
    """Connect off, or the job naming its clips: no Stop on the pill (a click does nothing) and none in the ⋯."""
    _seed, win, writer = act(connect_off=feed.OFF_CONNECT)
    lst = lst_of(win)
    seen, calls, _n = _watch_stop(win, monkeypatch)
    i, row = _mining(lst)
    assert _stop_part(lst, i) is None
    assert not [e for e in win.items.episode_entries(row, row.episodes[0]) if e.name == "ep-stop"]
    win.mine._off_read(None)                                            # Connect on again
    i, row = _mining(lst, _item(stoppable=None))                        # ... the job past its stop point
    assert _stop_part(lst, i) is None
    assert not [e for e in win.items.episode_entries(row, row.episodes[0]) if e.name == "ep-stop"]
    status = next(p for p in parts_of(lst, i) if p[0] == "status" and p[2] == row.status.tip)
    click(lst, status)
    assert seen == [] and calls == [] and not lst.stopping_ids


def test_the_episodes_menu_offers_stop_mining_and_its_press_paints_the_pill_before_the_worker(act, monkeypatch):
    """IK-2: the ⋯ closes as *Stop mining* is picked, so the pill of the episode it stops shows the press — marked and
    repainted before the worker, the bar untouched."""
    _seed, win, writer = act()
    lst = lst_of(win)
    monkeypatch.setattr(win.services.status, "refresh_soon", lambda *names: None)
    i, row = _mining(lst)
    ep = row.episodes[0]
    entry = [e for e in win.items.episode_entries(row, ep) if e.name == "ep-stop"]
    assert [(e.label, e.ok) for e in entry] == [(strings.MINE_STOP_ENTRY, True)]
    assert entry[0].tip == rows.action_of(ep.status, (ep,), None)[1]   # the pill's own words
    line = win.bar_line.full()
    seen, calls, before = _watch_stop(win, monkeypatch)
    win.items.episode_pick(row, ep, entry[0].name, entry[0].payload)
    assert seen and seen[0][0] == {ep.id} and seen[0][1] > before and seen[0][2]
    assert wait_until(lambda: calls == [(win.language, JOB)])
    assert win.bar_line.full() == line


def test_a_language_switch_lets_every_stopping_pill_go(act, monkeypatch):
    """`settle_all` (a language switch): no *Stopping…* of the old language left, its press ended."""
    _seed, win, writer = act()
    lst = lst_of(win)
    monkeypatch.setattr(win.services.status, "refresh_soon", lambda *names: None)
    i, row = _mining(lst)
    _watch_stop(win, monkeypatch)
    click(lst, _stop_part(lst, i))
    assert lst.stopping_ids
    win.mine.settle_all()
    assert not lst.stopping_ids and not win.presses.find(f"stop:{win.language}:{JOB}").live()


# --- the review's fix round (round8-r47-adversary.md) --------------------------------------------------------------- #
def test_a1_a_stop_connect_accepted_then_dropped_as_naming_began_ends_refused_with_words(act, monkeypatch):
    """R47-A1: a press that lands after Anki Miner's last batch and before naming is accepted (`actions.stop` True), then
    dropped as naming starts (`ledger.forget_stop`): the feed says Mining, not stopping, past the stop point. The pill
    held *Stopping…* through naming, filling and ordering, then ended done without a word. Now that state ends the press
    refused at once, the pill its own again and the bar saying it was too late. Red first: still *Stopping…*."""
    _seed, win, writer = act()
    lst = lst_of(win)
    monkeypatch.setattr(win.services.status, "refresh_soon", lambda *names: None)
    i, row = _mining(lst)
    ep = row.episodes[0]
    _seen, calls, _n = _watch_stop(win, monkeypatch)
    click(lst, _stop_part(lst, i))
    assert wait_until(lambda: calls)
    press = win.presses.find(f"stop:{win.language}:{JOB}")
    _moved(lst, row.key, view_rows._connected(PLAIN, _item(stoppable=None, stopping=None, progress=70,
                                                           doing="Naming the clips"), "video"))
    assert not lst.stopping_ids and press.state == press_service.FAILED
    assert win.bar_line.full() == strings.MINE_STOP_TOO_LATE
    assert ep.id not in lst.stopping_ids


def _mining_hero(lst):
    """Up Next (closed), its first episode made Connect's stoppable *Mining*: (its index, the card)."""
    st = view_rows._connected(PLAIN, _item(), "video")
    entries = list(lst.model().entries)
    h = next(n for n, e in enumerate(entries) if e[0] == rows.HERO)
    hero = entries[h][1]
    hero = hero._replace(status=st, episodes=type(hero.episodes)(
        (e._replace(status=st, cards=0, mining=True, deleted=False, missing=False) if k == 0 else e)
        for k, e in enumerate(hero.episodes)))
    entries[h] = (rows.HERO, hero, entries[h][2])
    lst.set_entries(entries)
    lst.scrollTo(lst.model().index(h, 0), lst.ScrollHint.PositionAtTop)
    QApplication.processEvents()
    return h, hero


@pytest.mark.parametrize("where", ["open-row-episode", "up-next"])
def test_a7_stopping_is_painted_on_an_open_rows_episode_pill_and_on_up_next_before_the_worker(act, monkeypatch, where):
    """R47-A7: the press's paint on the pills the closed-row test never reached — an opened row's episode pill (where
    the ⋯'s press shows) and Up Next's status — painted *Stopping…* before the stop is handed to the worker."""
    _seed, win, writer = act()
    lst = lst_of(win)
    monkeypatch.setattr(win.services.status, "refresh_soon", lambda *names: None)
    if where == "up-next":
        i, row = _mining_hero(lst)
        part = _stop_part(lst, i)
    else:
        i, row = _mining(lst)
        lst.toggle(lst.model().index(i, 0))
        assert wait_until(lambda: lst.model().open_key == row.key)
        QApplication.processEvents()
        part = [p for p in parts_of(lst, i) if p[0] == rows.STOP and p[3].id == row.episodes[0].id][-1]
    drawn, at_handover = [], []
    real = rows.paint_stop
    monkeypatch.setattr(rows, "paint_stop", lambda p, rect, stopping, *a, **k: (drawn.append((QRectF(rect), stopping)),
                                                                                 real(p, rect, stopping, *a, **k)))
    _watch_stop(win, monkeypatch)
    win.mine.stop_job = lambda language, job: (at_handover.append(list(drawn)), True)[1]
    click(lst, part)
    assert wait_until(lambda: at_handover)
    assert any(stopping and r.intersects(QRectF(part[1])) for r, stopping in at_handover[0])


def test_a7_a_stop_whose_worker_fails_puts_the_pill_back_and_says_why(act, monkeypatch):
    """R47-A7: `actions.stop` raising (a ledger that can't be opened): the press failed, the pill its own, the bar
    says Stop didn't reach Connect."""
    _seed, win, writer = act()
    lst = lst_of(win)
    i, row = _mining(lst)
    _watch_stop(win, monkeypatch)

    def broken(language, job):
        raise OSError("the ledger is locked")
    win.mine.stop_job = broken
    click(lst, _stop_part(lst, i))
    press = win.presses.find(f"stop:{win.language}:{JOB}")
    assert wait_until(lambda: press.state == press_service.FAILED)
    assert not lst.stopping_ids and win.bar_line.full().startswith(strings.MINE_STOP_FAILED.format(why="")[:10])


def test_a2_a_stop_on_a_file_no_list_shows_ends_with_its_worker(act, monkeypatch):
    """R47-A2: the ⋯ picked after the file left Current (nothing marked): the press ends with the worker's answer,
    never live for good (the header's hairline)."""
    _seed, win, writer = act()
    _watch_stop(win, monkeypatch)
    win.mine.stop(rows.Ask(10 ** 9, (10 ** 9,), None, JOB))
    press = win.presses.find(f"stop:{win.language}:{JOB}")
    assert wait_until(lambda: press.state == press_service.DONE)


def test_a3_a_refusal_after_a_language_switch_says_nothing_in_the_new_bar(act, monkeypatch):
    """R47-A3: the press already ended (a language switch) when the refusal arrives: no words in the bar."""
    _seed, win, writer = act()
    lst = lst_of(win)
    i, row = _mining(lst)
    _watch_stop(win, monkeypatch, answer=False)
    held = []
    real = mine_actions.bridge.run_in_worker
    monkeypatch.setattr(mine_actions.bridge, "run_in_worker", lambda fn, *a, **k: held.append((fn, a, k)))
    click(lst, _stop_part(lst, i))
    line = win.bar_line.full()
    win.mine.settle_all()
    fn, a, k = held[0]
    real(fn, *a, **k)
    _settle_then(lambda: True)                                          # the refusal delivered
    assert win.bar_line.full() == line


def _settle_then(check, n=40):
    import time
    for _ in range(n):
        QApplication.processEvents()
        time.sleep(0.01)
    return check()


def test_a4_the_rows_accessible_text_offers_stop_only_while_it_can_be_pressed(act, monkeypatch):
    """R47-A4: a screen reader hears "→ then Enter: Stop" on a stoppable row, never while its Stop is pressed."""
    from PyQt6.QtCore import Qt
    _seed, win, writer = act()
    lst = lst_of(win)
    i, row = _mining(lst)
    said = strings.ROWS_ACTION_KEY.format(action=strings.ROWS_ACTION_NAMES["stop"])
    text = lambda: lst.model().data(lst.model().index(i, 0), Qt.ItemDataRole.AccessibleDescriptionRole)  # noqa: E731
    assert text().endswith(said)
    lst.press_stop([row.episodes[0].id])
    assert said not in text()


def test_ik2_a_stop_marks_only_its_pill_and_a_stop_no_list_shows_turns_the_bars_arc(act, monkeypatch):
    """Intent keeper round 8, finding 2 (IK-2: one mark, on the thing acted on): Stop's pill reads *Stopping…* and the
    bottom bar's arc stays off — before the change both turned. A stop on a file no list shows has no pill, so the
    bar's arc is its mark until the worker answers. Red first: the bar's arc was on beside the pill."""
    _seed, win, writer = act()
    lst = lst_of(win)
    i, row = _mining(lst)
    part = _stop_part(lst, i)
    seen, _calls, _before = _watch_stop(win, monkeypatch)
    arcs = []
    real = mine_actions.bridge.run_in_worker
    monkeypatch.setattr(mine_actions.bridge, "run_in_worker",
                        lambda fn, *a, **kw: (fn is win.mine.stop_job and arcs.append(win.bar_arc.isVisible()),
                                              real(fn, *a, **kw))[1])
    click(lst, part)
    assert len(seen) == 1 and seen[0][0] == {row.episodes[0].id}       # the pill: Stopping…
    assert arcs == [False] and not win.bar_arc.isVisible()               # ... and nothing else turns
    press = win.presses.find(f"stop:{win.language}:{JOB}")
    _moved(lst, row.key, view_rows._connected(PLAIN, _item(feed.WAITING, tip=runner.STOPPED_BY_YOU,
                                                          stoppable=None), "video"))
    assert press.state == press_service.DONE
    other = "r47-ik2-elsewhere"
    win.mine.stop(rows.Ask(10 ** 9, (10 ** 9,), None, other))        # no pill on screen: the bar's arc, at once
    assert arcs[-1] is True
    late = win.presses.find(f"stop:{win.language}:{other}")
    assert wait_until(lambda: late.state == press_service.DONE) and not win.bar_arc.isVisible()
