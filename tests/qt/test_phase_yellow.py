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


_HELD = {}          # the entries a test put on *Needs you* (`_entries`): what the page's own gather lands from then on


@pytest.fixture(autouse=True)
def _gathered(monkeypatch):
    """The page's own gather lands the entries the test put on the page, never the seed's over them: it gathers on a
    worker as the window opens and again when opening the page marks its cards seen, and a real gather landing after the
    test's entries took away the card the press had just washed (the in-file flake, 1-2 tests red every run,
    2026-10-30)."""
    real = service.entries
    monkeypatch.setattr(service, "entries", lambda *a, **k: _HELD["entries"] if "entries" in _HELD else real(*a, **k))
    yield
    _HELD.clear()


def _entries(ny, *entries):
    """*Needs you* holding `entries` (as its gather lands them) behind a failure card that comes first — a gather
    already under way is dropped (`refresh` asks again: its answer is no longer the last asked)."""
    failure = service.Entry(key="failure:1:x", kind=service.FAILURE, title="Generate stopped (exit code 1).",
                            lines=(), actions=("open_logs", "save_logs"), unseen=True, say="", data={"at": 1})
    ny.entries = _HELD["entries"] = (failure,) + tuple(entries)
    ny._paint()
    ny.refresh()
    assert wait_until(lambda: not ny._running, 10)
    assert ny.entries == _HELD["entries"]
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
@pytest.mark.parametrize("language", LANGUAGES)
def test_a7_episodes_held_by_any_connect_need_open_its_card_whatever_its_kind(world, language, washed):
    """a7: a prepare step's need (Anki's known words to sync first, a store it can't read …) holds every episode —
    Anki Miner amber, *Waiting for you: see Needs you* — and its press finds that card, whatever its kind: every card
    of Connect's record is Anki Miner's place, never only the kinds the strip knew."""
    from app.connect import feed
    seed, win, writer, ny = world(language, looks=Looks())
    entry = _connect_entry(language, kind="known-sync")
    _entries(ny, entry)
    _mirror(win, _item(feed.HELD, "Anki's known words are read first: sync them"),
            _item(feed.HELD, "Anki's known words are read first: sync them"))
    assert win.phase.states[P.MINER].needs == "Waiting for you: see Needs you · 2 episodes"
    win._circle_pressed(P.MINER)
    _settle()
    assert ny.revealed == entry.key and washed == [ny.cards.card(entry.key)]


def test_a7_amber_waits_for_its_card_and_goes_when_the_card_is_put_away(world, washed, monkeypatch):
    """a7 (and at startup): a wait on you is amber only while its *Needs you* card is on the
    page — before the page's first gather it is a plain wait (the press opens the settings), amber once the card lands,
    and a plain wait again when *Not now* puts the card away (nothing left to land on)."""
    from app.connect import feed
    seed, win, writer, ny = world("ja", looks=Looks())
    opened = []
    monkeypatch.setattr(win, "open_setting", lambda target, *a, **k: opened.append(target))
    _entries(ny)
    _mirror(win, _item(feed.NOT_TIMED, f"{EPISODE['ja']}: Not timed to its video"))
    st = win.phase.states[P.MINER]
    assert st.needs is None and st.waiting and win.phase.go(P.MINER) is None
    win._circle_pressed(P.MINER)
    assert opened == ["connect_enabled"] and washed == []
    entry = _connect_entry("ja")
    _entries(ny, entry)                                                   # the gather lands its card: amber
    assert win.phase.states[P.MINER].needs and win.phase.go(P.MINER) is not None
    win._circle_pressed(P.MINER)
    _settle()
    assert ny.revealed == entry.key and washed == [ny.cards.card(entry.key)]
    ny._hidden_now[entry.key] = None                                      # *Not now* (its press's first frame)
    ny._paint()
    assert win.phase.states[P.MINER].needs is None and win.phase.go(P.MINER) is None


# --- A7N-3: Connect's own Generate failing is a fault — ス red with its words, never amber ------------------------ #
GENERATE_FAILED = ("Generate didn't finish after Connect made its cards: your list catches up at the next one. "
                   "Generate stopped (exit code 1).")


def _look_at(win, circle):
    """The hover shown on `circle` and left (`_leave_hover`): what it said is looked at."""
    s = win.phase
    s._looking = (circle, tuple(s._marks(circle, s.states[circle])))
    s.tooltips = type("T", (), {"shown": (s, s.rect_of(circle).toAlignedRect()), "hide": lambda self: None,
                                "request": lambda self, *a: None, "retext": lambda self, *a: None,
                                "hide_part_unless": lambda self, *a: None})()
    s._leave_hover(None)


@pytest.mark.parametrize("kind, held", [("generate", False), ("known-sync", True)])
def test_a7n3_an_episode_waiting_on_connects_failed_generate_is_a_plain_wait_never_amber(kind, held):
    """A7N-3 (Sonic 2026-10-30: red, never yellow): an episode waiting on Connect's own Generate that failed has nothing
    to decide — a plain wait in Connect's words on Anki Miner, never amber; a need you can act on (Anki's known words to
    sync) still holds it amber."""
    from app.connect import feed
    rec = {"running": True, "languages": {"ja": {"line": "", "state": "working", "skipped": [],
                                                 "needs": [{"id": 7, "kind": kind, "say": GENERATE_FAILED, "item": 1}],
                                                 "jobs": [{"item": 1, "job": 101, "state": "waiting", "kind": "mine",
                                                           "reason": GENERATE_FAILED}]}}}
    got = feed.build(rec, "ja")
    assert got.items[1].kind == (feed.HELD if held else feed.WAITING) and got.items[1].tip == GENERATE_FAILED
    registry = JobRegistry()
    S.mirror_connect(registry, got)
    miner = P.read(registry.snapshot(), now=time.time() + 5)[P.MINER]
    assert bool(miner.needs) is held and miner.waiting is not held
    assert not held or miner.go == P.Go("needs", ("no-video", P.CONNECT_CARDS))


def _generate_need(at):
    """*Needs you*'s entry for Connect's failed Generate after mining, as the page's gather makes it from Connect's
    record (`services.needs.entries`: one for the language, no episode)."""
    record = {"needs": [{"id": 9, "kind": "generate", "say": GENERATE_FAILED, "item": None, "at": at}]}
    return next(e for e in service.entries(None, connect=record) if e.kind == "generate")


@pytest.mark.parametrize("language", LANGUAGES)
def test_a7n3_connects_generate_failing_after_mining_makes_surasura_red_with_its_words(world, language, washed):
    """A7N-3: Connect's Generate after mining failed — its *Needs you* card stays, and ス is red with its words as a
    Generate you start is (nothing amber: there is nothing to decide); looked at, still said in the hover (its tail: the
    hover shortens long words in the middle) but no longer red; the same failure again (Connect reopens it: a new time)
    red again; gone with the card. A card you can act on (Anki's known words to sync), or one not Connect's, makes ス
    nothing."""
    entry, again = _generate_need("2026-10-30T10:00:00"), _generate_need("2026-10-30T11:00:00")
    seed, win, writer, ny = world(language, looks=Looks())
    s = win.phase
    _entries(ny, _connect_entry(language, kind="known-sync"),
             entry._replace(key="mine:generate", data={"at": 1}))            # (a kind of the same name, not Connect's)
    assert not s.states[P.SURASURA].failed
    _entries(ny, entry)
    assert s.states[P.SURASURA].failed == GENERATE_FAILED and "(exit code 1)" in s.hover_text(P.SURASURA)
    assert not s.states[P.SURASURA].needs and not s.states[P.MINER].needs
    _look_at(win, P.SURASURA)
    assert not s.states[P.SURASURA].failed and "(exit code 1)" in s.hover_text(P.SURASURA)
    _entries(ny, again)
    assert s.states[P.SURASURA].failed == GENERATE_FAILED
    assert s.hover_text(P.SURASURA).count("(exit code 1)") == 1                 # said once: the one before is gone
    ny._hidden_now[again.key] = None                                       # *Not now*
    ny._paint()
    assert not s.states[P.SURASURA].failed and "(exit code 1)" not in s.hover_text(P.SURASURA)


def test_a7_a_junban_fault_looked_at_stays_said_and_the_same_fault_again_is_red_again(junban_world):
    """a7: a fault the hover has shown stays in the hover (no longer red), and the same fault said again after the
    host's next run is news again: red, said once."""
    win = junban_world.win
    s = win.phase
    fault = rp.Fails("Anki not re-ordered: the deck's new cards are shown in random order")

    def look_at_it():
        s._looking = (P.JUNBAN, tuple(s._marks(P.JUNBAN, s.states[P.JUNBAN])))
        s.tooltips = type("T", (), {"shown": (s, s.rect_of(P.JUNBAN).toAlignedRect()), "hide": lambda self: None,
                                    "request": lambda self, *a: None, "retext": lambda self, *a: None,
                                    "hide_part_unless": lambda self, *a: None})()
        s._leave_hover(None)
    win.show_status(win.services.status.snapshot()._replace(replan=fault))
    assert s.states[P.JUNBAN].failed == str(fault) and s.hover_text(P.JUNBAN).count("random order") == 1
    look_at_it()
    st = s.states[P.JUNBAN]
    assert not st.failed and st.lines == (str(fault),) and "random order" in s.hover_text(P.JUNBAN)
    win.show_status(win.services.status.snapshot()._replace(replan="Anki: placing tomorrow's 20 cards…"))
    win.show_status(win.services.status.snapshot()._replace(replan=fault))
    assert s.states[P.JUNBAN].failed == str(fault) and s.hover_text(P.JUNBAN).count("random order") == 1


def test_a7_the_keyboard_reaches_every_circle_a_press_can_open(junban_world):
    """a7: the keyboard's circles are the pointer's — an amber one with a place too."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtCore import QEvent
    win = junban_world.win
    s = win.phase
    s.set_opens({P.ARRIVALS})
    s.set_extra(P.ANKI, "asks", "needs", "Waiting for Anki's profile", P.Go("needs", ("anki-wait",)))
    s._focus = P.ARRIVALS
    s.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier))
    assert s._focus == P.ANKI


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
