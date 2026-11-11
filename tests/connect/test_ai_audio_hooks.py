"""Connect's AI-audio hooks (Iro-AA): the book's *Make AI audio (beta)* answer, the part's cards queued when it fills,
the AI voice's pass once the run's jobs are through — Connect's side only (the module itself is `modules/irodori`,
private and absent in a public checkout: every hook is guarded).

What a wrong answer would cost: a part held back while an AI voice works for minutes (it must run after every part);
AI audio for a book the learner answered *Mine without audio*; a queue that fails and stops a part filling; audio made
on battery.
"""
import os

import pytest

from app.connect import actions, runner
from app.connect.ledger import Ledger
from tests.connect.test_lineup_book_ask import _AskSteps, _asks, _got, _hold


def _answer(ledger_path, ledger, answer_fn):
    [need] = _asks(ledger)
    return answer_fn("ja", need["id"], path=ledger_path)


@pytest.mark.parametrize("answer, marked", [(actions.book_ai_audio, True), (actions.book_audiobook, False)])
def test_only_make_ai_audio_marks_the_books_parts_for_the_ai_voice(tmp_path, answer, marked):
    ledger_path = str(tmp_path / "ledger.db")
    got = _got()
    with Ledger(ledger_path) as ledger:
        a = ledger.queue("ja", 11, "mine", None, "store-1")
        steps = _AskSteps(got)
        assert isinstance(_hold(steps, ledger, a, 11), runner.Wait)
    with Ledger(ledger_path) as ledger:
        assert _answer(ledger_path, ledger, answer) is True
    with Ledger(ledger_path) as ledger:
        said = runner._meta(ledger, f"{runner.BOOK_SAID}ja:{got['key']}")
        assert said == (runner.AI_AUDIO if marked else runner.NO_AUDIOBOOK)
        assert _hold(steps, ledger, a, 11) is None              # answered: mined as the book (never held again)
        assert (runner._meta(ledger, f"{runner.AI_JOB}{a}") == "1") is marked


class _FillSteps:
    """What `_fill` asks of Connect's steps, recorded."""

    def __init__(self, queue_fails=False):
        self.queued, self.filled, self.queue_fails = [], [], queue_fails

    def queue_ai_audio(self, lang, ids, job):
        if self.queue_fails:
            raise OSError("disk full")
        self.queued.append((lang, list(ids), job["id"]))

    def fill(self, lang, job, ids):
        self.filled.append(list(ids))

    def update_staged(self):
        return False

    def enabled(self):
        return True

    def blocked(self, *a, **k):
        return None


def _filling_job(ledger, ids, marked):
    jid = ledger.queue("ja", 21, "mine", None, "store-1")
    ledger.set_state(jid, "filling")
    if marked:
        with ledger.transaction():
            ledger.conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (f"{runner.AI_JOB}{jid}", "1"))
    return jid


@pytest.mark.parametrize("marked", [True, False])
def test_a_marked_part_queues_its_new_cards_once_when_it_fills(tmp_path, monkeypatch, marked):
    monkeypatch.setattr(runner, "_blocked", lambda *a, **k: None)
    with Ledger(str(tmp_path / "ledger.db")) as ledger:
        jid = _filling_job(ledger, [], marked)
        monkeypatch.setattr(ledger, "undo_record", lambda j: [1700000000101, 1700000000104])
        steps = _FillSteps()
        runner._fill(steps, ledger, "ja", ledger.job_by_id(jid))
        assert steps.queued == ([("ja", [1700000000101, 1700000000104], jid)] if marked else [])
        assert steps.filled == [[1700000000101, 1700000000104]]          # Backfill fills as before
        assert runner._meta(ledger, f"{runner.AI_JOB}{jid}") is None      # the mark gone: queued once
        runner._fill(steps, ledger, "ja", ledger.job_by_id(jid))
        assert len(steps.queued) == (1 if marked else 0)


def test_a_queue_that_fails_never_stops_the_part_filling(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_blocked", lambda *a, **k: None)
    with Ledger(str(tmp_path / "ledger.db")) as ledger:
        jid = _filling_job(ledger, [], True)
        monkeypatch.setattr(ledger, "undo_record", lambda j: [101])
        steps = _FillSteps(queue_fails=True)
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
    before = None                                           # run before the voice asks whether to stop

    def blocked(self, lang):
        return self.why

    def ai_audio(self, lang, should_stop):
        if self.raises:
            raise RuntimeError("the voice broke")
        if self.before:
            self.before()
        self.calls.append((lang, should_stop()))


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.db")) as led:
        yield led


def test_the_ai_pass_runs_and_tells_the_voice_when_to_stop(ledger):
    steps = _PassSteps()
    assert runner._ai_audio(steps, ledger, "ja", {}) is False
    assert steps.calls == [("ja", False)]
    steps.battery = True
    runner._ai_audio(steps, ledger, "ja", {})
    assert steps.calls[-1] == ("ja", True)                  # on battery: the voice stops between two sentences
    steps.battery, steps.why = False, runner.REVIEWING
    runner._ai_audio(steps, ledger, "ja", {})
    assert steps.calls[-1] == ("ja", True)                  # you review now: it stops before the next sentence


def test_a_part_that_comes_in_stops_the_voice_and_the_pass_goes_on(ledger):
    # why: AI audio never holds a part back (review r1 #1) — a *Mine now* meanwhile goes first
    steps = _PassSteps()
    steps.before = lambda: ledger.queue("ja", 31, "mine", None, "store-1")
    assert runner._ai_audio(steps, ledger, "ja", {}) is True
    assert steps.calls == [("ja", True)]


def test_a_part_this_pass_already_tried_never_stops_the_voice(ledger):
    jid = ledger.queue("ja", 32, "mine", None, "store-1")
    steps = _PassSteps()
    assert runner._ai_audio(steps, ledger, "ja", {}, tried={jid}) is False
    assert steps.calls == [("ja", False)]


def test_no_ai_pass_while_an_update_is_staged_and_an_error_never_ends_the_run(ledger):
    staged = _PassSteps(staged=True)
    assert runner._ai_audio(staged, ledger, "ja", {}) is False
    assert not staged.calls
    assert runner._ai_audio(_PassSteps(raises=True), ledger, "ja", {}) is False      # logged, never raised


def test_steps_without_the_module_queue_and_make_nothing(monkeypatch):
    # why: the module is optional — a checkout or build without modules/irodori must run Connect unchanged
    import builtins
    real = builtins.__import__

    def no_module(name, *a, **k):
        if name == "modules" and a and a[2] and "irodori" in a[2]:
            raise ImportError("no irodori")
        if name.startswith("modules.irodori"):
            raise ImportError("no irodori")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_module)
    steps = runner.Steps({})
    assert steps.queue_ai_audio("ja", [1], {"id": 1}) == 0
    assert steps.ai_audio("ja", lambda: False) is None


def test_the_ai_pass_comes_after_every_part_in_the_runner():
    src = open(os.path.join(os.path.dirname(runner.__file__), "runner.py"), encoding="utf-8").read()
    loop = src[src.index("def _language("):src.index("def _after_mining(")]
    assert loop.index("_after_mining(steps, ledger, lang, out") < loop.index("_ai_audio(steps, ledger, lang") < \
        loop.index("job = _ordered(jobs, line)[0]")


def test_a_kick_while_the_voice_works_stops_it_so_a_placement_goes_first(ledger):
    # why: a library placement becomes a job only at the loop's next look (review r2 #3): a kick since the pass began
    from app.connect import kick
    steps = _PassSteps()
    steps.before = kick.wake
    assert runner._ai_audio(steps, ledger, "ja", {}) is True
    assert steps.calls == [("ja", True)]


def test_connect_reads_the_beta_switch_again_and_stops_when_it_is_turned_off(monkeypatch):
    # why: a Connect started with the beta on must stop once the learner turns it off in Settings (review r2 #4)
    irodori = pytest.importorskip("modules.irodori")
    from app import settings_manager
    seen = {}
    switch = {"enable_irodori": True}
    monkeypatch.setattr(settings_manager, "load_settings", lambda strict=False: dict(switch))

    def run_queue(settings, lang, should_stop=None, say=None):
        seen["settings"] = settings
        seen["before"] = should_stop()
        switch["enable_irodori"] = False
        seen["after"] = should_stop()
        return {"written": 0, "runs": [], "left": 0}
    monkeypatch.setattr(irodori, "run_queue", run_queue)
    runner.Steps({}).ai_audio("ja", lambda: False)
    assert seen == {"settings": {"enable_irodori": True}, "before": False, "after": True}
