"""a7 — a yellow circle always has a decision behind it (Sonic, 2026-10-29, alpha 6's report: "If yellow i would expect
it to let me go somewhere to make a decision that is highlighted. If no decision it shouldn't be yellow but something
else."). One rule for the five circles of the bottom bar (`app/services/phase.py`'s `Go`, `app/qt/phase_strip.py`): a
circle is amber only while a wait on you names where it is decided, and its press opens that place with the row
highlighted — *Needs you* at its card, or 順's window at its control; with nothing to decide it is never amber and its
press opens its settings.

What a wrong answer would cost a learner: a yellow circle that sends them looking for a problem that isn't there (Sonic's
順 was amber for days because *Only i+1 sentences* was on, while Generate re-ordered Anki all along), or a press that
lands on a page where nothing is highlighted and nothing asks anything.

Each icon state is a test: 順 (a deck to pick, an unfinished reorder, Only i+1, Anki closed, a fault), Anki Miner (its
episodes waiting on you), Anki (a prompt or another profile; closed), 届 (a folder gone; offline). Japanese and Chinese
libraries from the suite's seed (`window_seed`), Connect's lines as its runner words them.
"""
import time

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from app import replan_preview as rp
from app.connect import anki_session, runner
from app.qt import motion, strings, windows
from app.services import needs as service
from app.services import phase as P
from app.services import status as S
from app.services.jobs import JobRegistry
from tests.qt.conftest import wait_until
from tests.qt.test_needs_gone_folder import Looks, _gone_row, _told, _away_row, world  # noqa: F401  (`world`)
from tests.qt.test_phase_strip import _snap, junban_world  # noqa: F401  (`junban_world`: the fixture)

LANGUAGES = ("ja", "zh")
EPISODE = {"ja": "雲の上の郵便屋さん - 01", "zh": "云上的邮递员 - 01"}


@pytest.fixture
def washed(monkeypatch):
    """Every widget `motion.wash` highlights, in order (the wash itself fades on the clock; frozen in the suite)."""
    got = []
    real = motion.wash
    monkeypatch.setattr(motion, "wash", lambda widget, radius=0.0: got.append(widget) or real(widget, radius))
    return got


def _settle():
    for _ in range(5):
        QApplication.processEvents()


def _entries(ny, *entries):
    """*Needs you* holding `entries` (as its gather lands them) behind a failure card that comes first."""
    failure = service.Entry(key="failure:1:x", kind=service.FAILURE, title="Generate stopped (exit code 1).",
                            lines=(), actions=("open_logs", "save_logs"), unseen=True, say="", data={"at": 1})
    ny.entries = (failure,) + tuple(entries)
    ny._paint()
    _settle()


def _connect_entry(language, kind="not-timed"):
    return service.Entry(key=f"connect:{kind}:7", kind=kind,
                         title=f"{EPISODE[language]}: Not timed to its video, so no cards. Mine anyway…", lines=(),
                         actions=("mine_anyway", "dismiss"), unseen=True, say="",
                         data={"need_id": 7, "item_id": None, "connect": True, "at": 0})


def _anki_entry(reason):
    return service.Entry(key="anki:abc:s1", kind=service.ANKI_WAIT, title="Anki needs you: 1 episode waits for it",
                         lines=(), actions=(), unseen=True, say=reason, data={"episodes": 1, "reason": reason})


def _mirror(win, *items):
    """Connect's feed with `items` mirrored into the window's registry as the status service does (`mirror_connect`),
    shown on the strip a few seconds on (an automatic wait shows after REVEAL_S)."""
    from app.connect import feed
    registry = JobRegistry()
    got = feed.Feed(True, None, {i: it for i, it in enumerate(items)}, "", "", 0, False)
    S.mirror_connect(registry, got)
    win.phase.now = lambda: time.time() + 5
    win.phase.set_jobs(registry.snapshot())
    return registry


def _item(kind, tip, words=""):
    from app.connect import feed
    return feed.Item(kind, words or feed.WORDS.get(kind, ""), tip, None, None, None)


# --- Anki Miner: its episodes waiting on you ---------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_anki_miner_amber_opens_needs_you_at_its_episodes_card_highlighted(world, language, washed, monkeypatch):
    """Episodes not timed to their video wait on you: Anki Miner is amber, its hover says to decide in Needs you, and its
    press opens Needs you at that card (washed), never Connect's on/off switch."""
    from app.connect import feed
    seed, win, writer, ny = world(language, looks=Looks())
    opened = []
    monkeypatch.setattr(win, "open_setting", lambda target, *a, **k: opened.append(target))
    entry = _connect_entry(language)
    _entries(ny, entry)
    _mirror(win, _item(feed.NOT_TIMED, f"{EPISODE[language]}: Not timed to its video"))
    st = win.phase.states[P.MINER]
    assert st.needs == "Not timed to its video · 1 episode" and win.phase.go(P.MINER).place == "needs"
    assert strings.PHASE_PRESS_NEEDS in win.phase.hover_text(P.MINER)
    win._circle_pressed(P.MINER)
    _settle()
    assert win.current_tab() == "needs" and opened == []
    assert ny.revealed == entry.key and washed == [ny.cards.card(entry.key)]


# --- Anki: a prompt or another profile waits on you; closed is a plain wait ------------------------------------------- #
@pytest.mark.parametrize("reason", [anki_session.UNUSABLE, anki_session.OTHER_PROFILE.format("日本語", "User 1")])
def test_anki_asking_for_you_is_amber_and_opens_needs_yous_anki_line_highlighted(world, reason, washed, monkeypatch):
    from app.connect import feed
    seed, win, writer, ny = world("ja", looks=Looks())
    opened = []
    monkeypatch.setattr(win, "open_setting", lambda target, *a, **k: opened.append(target))
    entry = _anki_entry(reason)
    _entries(ny, entry)
    _mirror(win, _item(feed.ANKI, reason))
    assert win.phase.states[P.ANKI].needs and win.phase.go(P.ANKI) == P.Go("needs", (service.ANKI_WAIT,))
    win._circle_pressed(P.ANKI)
    _settle()
    assert win.current_tab() == "needs" and opened == [] and ny.revealed == entry.key
    assert washed == [ny.cards.card(entry.key)]


def test_anki_closed_is_a_plain_wait_never_amber_and_its_press_opens_its_settings(world, washed, monkeypatch):
    """Anki closed decides nothing (its cards are made once it opens): a still arc with its words in the hover; the
    press opens the known-words settings as at rest, and *Needs you* keeps its own line with *Open Anki*."""
    from app.connect import feed
    seed, win, writer, ny = world("ja", looks=Looks())
    opened = []
    monkeypatch.setattr(win, "open_setting", lambda target, *a, **k: opened.append(target))
    _entries(ny, _anki_entry(runner.ANKI_CLOSED))
    _mirror(win, _item(feed.ANKI, runner.ANKI_CLOSED))
    st = win.phase.states[P.ANKI]
    assert st.needs is None and st.waiting and win.phase.go(P.ANKI) is None
    assert "Waiting for Anki: it isn&#x27;t open · 1 episode" in win.phase.hover_text(P.ANKI)
    assert strings.PHASE_PRESS in win.phase.hover_text(P.ANKI)
    win._circle_pressed(P.ANKI)
    assert opened == ["known"] and washed == [] and ny.revealed is None


# --- 届: gone is a decision, offline is not ------------------------------------------------------------------------ #
@pytest.mark.parametrize("language", LANGUAGES)
def test_todoke_amber_for_a_gone_folder_opens_its_card_highlighted_and_offline_alone_is_words(world, language, washed,
                                                                                             monkeypatch):
    seed, win, writer, ny = world(language, looks=Looks())
    opened = []
    monkeypatch.setattr(win, "open_setting", lambda target, *a, **k: opened.append(target))
    _told(win, language, _gone_row(language), _away_row())
    assert wait_until(lambda: any(e.kind == service.FOLDER_GONE for e in ny.entries), 10)
    assert win.phase.states[P.ARRIVALS].needs and win.phase.go(P.ARRIVALS) == P.Go("needs", (service.FOLDER_GONE,))
    win._circle_pressed(P.ARRIVALS)
    _settle()
    gone = next(e.key for e in ny.entries if e.kind == service.FOLDER_GONE)
    assert win.current_tab() == "needs" and ny.revealed == gone and washed == [ny.cards.card(gone)]
    _told(win, language, _away_row())                                      # the drive away alone: nothing to decide
    st = win.phase.states[P.ARRIVALS]
    assert st.needs is None and not st.waiting and win.phase.go(P.ARRIVALS) is None
    assert "N:\\Media" in win.phase.hover_text(P.ARRIVALS)
    win.show_tab("current")
    win._circle_pressed(P.ARRIVALS)
    assert opened == ["library_folders"]


# --- 順: a deck to pick or an unfinished reorder opens its window there; nothing else is amber ------------------------ #
class _Junban:
    def __init__(self):
        self.highlighted = []

    def highlight(self, control):
        self.highlighted.append(control)


@pytest.mark.parametrize("line, control", [(rp.InJunban(rp.RESTORE_FIRST), "restore"),
                                           (rp.InJunban(rp.ONE_DECK), "deck"),
                                           (rp.InJunban("順's deck 日本語::Mining isn't recorded for Japanese — pick it in "
                                                        "順's window in Japanese"), "deck")])
def test_junban_amber_opens_its_window_at_the_control_to_decide(junban_world, monkeypatch, line, control):
    win = junban_world.win
    shown = _Junban()
    launched, opened = [], []
    monkeypatch.setattr(windows, "launch", lambda shell, op: launched.append(op.name) or shown)
    win.open_setting = lambda target: opened.append(target) or True
    assert wait_until(lambda: P.JUNBAN in win.phase.opens)
    win.show_status(win.services.status.snapshot()._replace(replan=line))
    assert win.phase.states[P.JUNBAN].needs == str(line)
    win._circle_pressed(P.JUNBAN)
    assert launched == ["junban"] and shown.highlighted == [control] and opened == []


@pytest.mark.parametrize("line", [rp.GivesUp(rp.AFTER_GENERATE.format(mode="Only i+1 sentences")),
                                  rp.GivesUp(rp.NOT_BY_ITSELF.format(mode="Coverage %")),
                                  rp.GivesUp(rp.CLOSED), rp.GivesUp(rp.PRESS_GENERATE), rp.GivesUp(rp.NEW_CONTENT),
                                  rp.Fails("Re-ordering as you move stopped: disk full")])
def test_junban_with_nothing_to_decide_is_never_amber_and_its_press_opens_its_settings(junban_world, monkeypatch,
                                                                                         line):
    """Sonic's case first: Only i+1 on, Generate re-ordering Anki — a fact, said in the hover, never amber. A fault is
    red, not amber."""
    win = junban_world.win
    launched, opened = [], []
    monkeypatch.setattr(windows, "launch", lambda shell, op: launched.append(op.name))
    win.open_setting = lambda target: opened.append(target) or True
    assert wait_until(lambda: P.JUNBAN in win.phase.opens)
    win.show_status(win.services.status.snapshot()._replace(replan=line))
    st = win.phase.states[P.JUNBAN]
    assert st.needs is None and win.phase.go(P.JUNBAN) is None
    assert bool(st.failed) is isinstance(line, rp.Fails)
    win._circle_pressed(P.JUNBAN)
    assert launched == [] and opened == ["junban"]


# --- the one rule, across every circle -------------------------------------------------------------------------- #
def test_every_amber_circle_names_where_to_decide_and_none_is_amber_without_one(junban_world):
    """Whatever lights them, no circle is amber without a `go`; every `go` is a place the shell opens."""
    from app.connect import feed
    win = junban_world.win
    registry = JobRegistry()
    registry.record("mine-wait", "Connect", automatic=True, reason="x", needs="No video · 2 episodes")
    registry.record("mine-anki", "Connect", automatic=True, reason="y", needs="Waiting for Anki's profile · 1 episode")
    registry.record("anki-session", "Looking at Anki", automatic=True, reason="z", needs="Anki is closed")
    win.phase.now = lambda: time.time() + 5
    win.phase.set_jobs(registry.snapshot())
    win.show_status(win.services.status.snapshot()._replace(replan=rp.GivesUp(rp.CLOSED)))
    win.phase.set_extra(P.ARRIVALS, "offline", "info", "N:\\Media isn't there now")
    for c in P.CIRCLES:
        st = win.phase.states[c]
        assert bool(st.needs) is (st.go is not None), c
        if st.go is not None:
            assert st.go.place in ("needs", "junban")
    assert {c for c in P.CIRCLES if win.phase.states[c].needs} == {P.MINER, P.ANKI}
    assert feed.ANKI in S.CONNECT_WAITS and S.CONNECT_WAITS[feed.NO_VIDEO] == "needs"
