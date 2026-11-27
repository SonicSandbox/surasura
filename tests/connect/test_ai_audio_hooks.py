"""Connect's Card sound hooks (AUDIO-FILL, 3.0.21; Iro-AA's AI-audio hooks before it): a part's new cards noted when
it fills, Card sound's automatic pass once the run's jobs are through (`runner._card_sound` → `Steps.card_sound` →
`card_sound.auto`), the AI voice started only while the PC is quiet — Connect's side only (the voice itself is
`modules/irodori`, private and absent in a public checkout: every hook is guarded). The book's *Make AI audio* answer
and Best's AI mark are gone (Sonic § 106 decision 10): an older ledger's answer is read as *Mine without audio*.

What a wrong answer would cost: a part held back while sound is cut or voiced (it must run after every part); a note
that fails and stops a part filling; audio made on battery or while the learner reviews; the AI voice started on a
busy PC; the voice still working after the learner switched it off.
"""
import os

import pytest

from app.connect import card_sound, runner
from app.connect.ledger import Ledger
from tests.connect.test_lineup_book_ask import _AskSteps, _got, _hold


def test_an_older_make_ai_audio_answer_is_read_as_mine_without_audio(tmp_path):
    """A ledger from before 3.0.21 holding the book's *Make AI audio* answer ("ai"): the book is answered (never asked
    again), mined as the book, and no part is marked for the AI voice any more."""
    ledger_path = str(tmp_path / "ledger.db")
    got = _got()
    with Ledger(ledger_path) as ledger:
        a = ledger.queue("ja", 11, "mine", None, "store-1")
        with ledger.transaction():
            ledger.conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (f"{runner.BOOK_SAID}ja:{got['key']}", "ai"))
        assert _hold(_AskSteps(got), ledger, a, 11) is None
        assert not [k for (k,) in ledger.conn.execute("SELECT key FROM meta") if k.startswith("ai_audio_job:")]


class _FillSteps:
    """What `_fill` asks of Connect's steps, recorded."""

    def __init__(self):
        self.filled = []

    def fill(self, lang, job, ids):
        self.filled.append(list(ids))

    def update_staged(self):
        return False

    def enabled(self):
        return True

    def blocked(self, *a, **k):
        return None


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_part_notes_its_new_cards_for_card_sound_when_it_fills(tmp_path, monkeypatch, lang):
    monkeypatch.setattr(runner, "_blocked", lambda *a, **k: None)
    with Ledger(str(tmp_path / "ledger.db")) as ledger:
        jid = ledger.queue(lang, 21, "mine", None, "store-1")
        ledger.set_state(jid, "filling")
        monkeypatch.setattr(ledger, "undo_record", lambda j: [1700000000101, 1700000000104])
        steps = _FillSteps()
        runner._fill(steps, ledger, lang, ledger.job_by_id(jid))
        assert steps.filled == [[1700000000101, 1700000000104]]          # Backfill fills as before
        assert card_sound._meta_json(ledger, card_sound.NEW + lang, []) == [1700000000101, 1700000000104]


def test_a_note_that_fails_never_stops_the_part_filling(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_blocked", lambda *a, **k: None)

    def broken(*a):
        raise OSError("disk full")
    monkeypatch.setattr(card_sound, "_put_meta", broken)
    with Ledger(str(tmp_path / "ledger.db")) as ledger:
        jid = ledger.queue("ja", 22, "mine", None, "store-1")
        ledger.set_state(jid, "filling")
        monkeypatch.setattr(ledger, "undo_record", lambda j: [101])
        steps = _FillSteps()
        runner._fill(steps, ledger, "ja", ledger.job_by_id(jid))
        assert steps.filled == [[101]] and ledger.job_by_id(jid)["state"] == "ordering"


class _PassSteps:
    def __init__(self, staged=False, battery=False, raises=False):
        self.staged, self.battery, self.raises, self.calls = staged, battery, raises, []

    def update_staged(self):
        return self.staged

    def enabled(self):
        return True

    def on_battery(self):
        return self.battery

    why = None
    before = None                                           # run before the pass asks whether to stop

    def blocked(self, lang):
        return self.why

    def card_sound(self, lang, ledger, should_stop):
        if self.raises:
            raise RuntimeError("the cut broke")
        if self.before:
            self.before()
        self.calls.append((lang, should_stop()))


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.db")) as led:
        yield led


def test_the_sound_pass_runs_and_is_told_when_to_stop(ledger):
    steps = _PassSteps()
    assert runner._card_sound(steps, ledger, "ja", {}) is False
    assert steps.calls == [("ja", False)]
    steps.battery = True
    runner._card_sound(steps, ledger, "ja", {})
    assert steps.calls[-1] == ("ja", True)                  # on battery: it stops between two lines / sentences
    steps.battery, steps.why = False, runner.REVIEWING
    runner._card_sound(steps, ledger, "ja", {})
    assert steps.calls[-1] == ("ja", True)                  # you review now: it stops before the next one
    steps.why = runner.GENERATE_FIRST
    runner._card_sound(steps, ledger, "ja", {})
    assert steps.calls[-1] == ("ja", True)                  # a gentle PC's Generate goes first


def test_a_part_that_comes_in_stops_the_sound_and_the_pass_goes_on(ledger):
    # why: sound never holds a part back (Iro-AA review r1 #1) — a *Mine now* meanwhile goes first
    steps = _PassSteps()
    steps.before = lambda: ledger.queue("ja", 31, "mine", None, "store-1")
    assert runner._card_sound(steps, ledger, "ja", {}) is True
    assert steps.calls == [("ja", True)]


def test_a_part_this_pass_already_tried_never_stops_the_sound(ledger):
    jid = ledger.queue("ja", 32, "mine", None, "store-1")
    steps = _PassSteps()
    assert runner._card_sound(steps, ledger, "ja", {}, tried={jid}) is False
    assert steps.calls == [("ja", False)]


def test_no_sound_pass_while_an_update_is_staged_and_an_error_never_ends_the_run(ledger):
    staged = _PassSteps(staged=True)
    assert runner._card_sound(staged, ledger, "ja", {}) is False
    assert not staged.calls
    assert runner._card_sound(_PassSteps(raises=True), ledger, "ja", {}) is False      # logged, never raised


def test_the_sound_pass_comes_after_every_part_in_the_runner():
    src = open(os.path.join(os.path.dirname(runner.__file__), "runner.py"), encoding="utf-8").read()
    loop = src[src.index("def _language("):src.index("def _after_mining(")]
    assert loop.index("_after_mining(steps, ledger, lang, out") < loop.index("_card_sound(steps, ledger, lang") < \
        loop.index("job = _ordered(jobs, line)[0]")


def test_a_kick_while_the_sound_works_stops_it_so_a_placement_goes_first(ledger):
    # why: a library placement becomes a job only at the loop's next look (Iro-AA review r2 #3)
    from app.connect import kick
    steps = _PassSteps()
    steps.before = kick.wake
    assert runner._card_sound(steps, ledger, "ja", {}) is True
    assert steps.calls == [("ja", True)]


def test_connect_reads_the_voices_switch_again_and_the_pc_once_before_the_voice(monkeypatch, ledger):
    """`Steps.card_sound`: settings.json read at the pass (the switch on), the voice's own stop true once the learner
    turns it off in Settings (Iro-AA review r2 #4), and the CPU asked through `ai_hold`."""
    from app import settings_manager
    switch = {"connect_enabled": True, "enable_irodori": True}
    monkeypatch.setattr(settings_manager, "load_settings", lambda strict=False: dict(switch))
    monkeypatch.setattr(card_sound, "_voice_on", lambda s, l: bool(s.get("enable_irodori")))
    monkeypatch.setattr(runner, "_cpu_busy", lambda: (lambda: False))
    seen = {}

    def auto(settings, lang, led, steps=None, should_stop=None, ai_hold=None, ai_stop=None):
        seen.update(settings=settings, led=led is ledger, hold=ai_hold(), before=ai_stop())
        switch["enable_irodori"] = False
        seen["after"] = ai_stop()
        return {"id": None}
    monkeypatch.setattr(card_sound, "auto", auto)
    runner.Steps({}).card_sound("ja", ledger, lambda: False)
    assert seen == {"settings": {"connect_enabled": True, "enable_irodori": True}, "led": True, "hold": False,
                    "before": False, "after": True}


class _Load:
    def __init__(self, shares):
        self.shares = list(shares)

    def sample(self):
        got = self.shares.pop(0)
        if isinstance(got, Exception):
            raise got
        return got


@pytest.fixture(autouse=True)
def _quiet_before(monkeypatch):
    # why: Connect's process keeps the busy line's last answer (its hysteresis); each test starts from a quiet one
    monkeypatch.setattr(runner, "_CPU_BUSY", [False])


@pytest.mark.parametrize("share, busy", [(0.95, True), (0.70, True), (0.69, False), (None, False),
                                         (OSError("no counters"), False)])
def test_the_ai_voice_waits_on_a_busy_cpu_by_the_window_schedulers_own_line(share, busy):
    """`_cpu_busy`: the window scheduler's line (`power.BUSY`, every program's CPU share since the pass began, waited
    out to its 5 s window when the real sound took less); a reading that fails is quiet (never a reason to hold sound
    forever)."""
    from app.services import gentle
    now, slept = [100.0], []
    busy_now = runner._cpu_busy(_Load([None, share]), clock=lambda: now[0], sleep=slept.append)
    now[0] += 2.0                                            # the real sound took 2 s
    assert busy_now() is busy
    assert slept == [pytest.approx(gentle.LOAD_WINDOW_S - 2.0)]


@pytest.mark.parametrize("was, share, busy", [(True, 0.60, True), (True, 0.55, True), (True, 0.54, False),
                                              (False, 0.60, False), (True, None, True),
                                              (True, OSError("no counters"), True)])
def test_a_busy_computer_is_quiet_again_only_under_the_quiet_line_across_passes(was, share, busy):
    """The lead on A5: the scheduler's rule whole — busy at `power.BUSY`, quiet again only under `power.QUIET` — so a
    pass after a busy one doesn't start the voice at 60 % CPU; a reading that fails keeps the last answer."""
    runner._CPU_BUSY[0] = was
    now = [0.0]
    busy_now = runner._cpu_busy(_Load([None, share]), clock=lambda: now[0], sleep=lambda s: None)
    now[0] += 10.0
    assert busy_now() is busy and runner._CPU_BUSY[0] is busy


def test_connect_and_the_window_ask_the_one_busy_line(monkeypatch):
    # why: one rule for both processes (the lead on A5), never a copy that drifts from the scheduler's
    from app.services import gentle
    asked = []
    monkeypatch.setattr(gentle, "busy_line", lambda share, was: asked.append((share, was)) or "the line's answer")
    busy_now = runner._cpu_busy(_Load([None, 0.42]), clock=lambda: 99.0, sleep=lambda s: None)
    assert busy_now() == "the line's answer" and asked == [(0.42, False)]


def test_a_long_real_sound_half_is_its_own_window_and_never_waits_more():
    now, slept = [0.0], []
    busy_now = runner._cpu_busy(_Load([None, 0.1]), clock=lambda: now[0], sleep=slept.append)
    now[0] += 60.0
    assert busy_now() is False and slept == []


def test_steps_without_the_voice_module_still_give_real_sound(monkeypatch, ledger):
    # why: the voice is optional — a checkout or build without modules/irodori must run Card sound's real half
    import builtins
    real = builtins.__import__

    def no_module(name, *a, **k):
        if name == "modules" and a and a[2] and "irodori" in a[2]:
            raise ImportError("no irodori")
        if name.startswith("modules.irodori"):
            raise ImportError("no irodori")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_module)
    assert card_sound._voice_on({"enable_irodori": True}, "ja") is False
