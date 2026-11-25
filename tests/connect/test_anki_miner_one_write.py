"""One settings write at a time on an Anki Miner (CONNECT-RACE, 2026-11-25; found by E-HIST 2's Best smokes).

Anki Miner 3.13's `settings-import` rewrites a profile's file (`ProfileStore.write_profile`: a temp file replaced in)
under its run lock, but `check`, `settings-export`, `media`, `render` … read that file with no lock. On Best with the
speech model not installed (a learner's default), Connect's speech check (`speech_ready`, on the thread that hears
releases beside the mining) set `asr_model` on Surasura's profile while the mine's own calls ran: a read beside the
replace failed (Errno 13 → PROFILE_UNREADABLE: "Profile 'surasura' cannot be read", the job *Needs you*), or the mine
met the write's run lock (BUSY: "Anki Miner is open: close it to make cards") — the job ended waiting with 0 cards,
2 of 5 Best smokes. `anki_miner.api`, the one place Connect's calls start, now lets a write run alone on its program.

What a wrong answer would cost: a learner's whole episode waits with no cards and a message telling them to close a
window that isn't open, or to fix a profile that is fine; or, the other way, a guard that holds a mine behind a
speech check for minutes, or one that never lets the check write again (no sentence audio checks at all).

The overlaps are made by events, never by sleeps: the suite's fake Anki Miner (run as a child process exactly as the
real one is) holds a call open until a gate file exists (`until`), and each step waits for the thing it needs to
see — the fake's log naming a call, or the guard naming a call that waits.
"""
import os
import threading
import time

import pytest

from app.connect import anki_miner, stopping


@pytest.fixture(autouse=True)
def fresh_speech():
    anki_miner._SPEECH.clear()
    yield
    anki_miner._SPEECH.clear()


def _until(done, seconds=30.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if done():
            return True
        time.sleep(0.02)
    raise AssertionError("it never happened")


def _waiting(path):
    """How many calls the guard holds back on `path` (0 before the guard existed: the red run's answer)."""
    calls = getattr(anki_miner, "_CALLS", None)
    return calls.waiting(path) if calls is not None else 0


class _Call(threading.Thread):
    """One Anki Miner call on a thread of its own: its answer or its error kept for the test."""

    def __init__(self, call, check=None):
        super().__init__(daemon=True)
        self._call, self._check = call, check
        self.answer = self.error = None

    def run(self):
        try:
            if self._check is None:
                self.answer = self._call()
            else:
                with stopping.watching(self._check):
                    self.answer = self._call()
        except BaseException as e:      # (the test reads it)
            self.error = e


def _gate(fake_miner, tmp_path, command, **plan):
    gate = str(tmp_path / f"release-{command}")
    fake_miner.plan(until={command: gate}, **plan)
    return gate


def _release(gate, *calls):
    with open(gate, "w", encoding="utf-8") as f:
        f.write("go")
    for call in calls:
        call.join(30)
        assert not call.is_alive(), "a call never ended"


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_profile_write_waits_for_a_read_under_way_and_starts_only_once_it_has_ended(tmp_path, fake_miner, language):
    """dev's smoke 4: the speech check's `settings-import` beside a read of the same profile (here `check`, held
    open). The write must not start its program until the read has ended — then it runs, once."""
    gate = _gate(fake_miner, tmp_path, "check", speech={"installed": [], "model": "large-v3"})
    read = _Call(lambda: anki_miner.check(fake_miner.path, language, "p-surasura"))
    read.start()
    _until(lambda: "check" in fake_miner.commands())
    write = _Call(lambda: anki_miner.settings_import(fake_miner.path, language, {"asr_model": "small"},
                                                     str(tmp_path / "speech"), profile="p-surasura"))
    write.start()
    _until(lambda: _waiting(fake_miner.path) == 1 or "settings-import" in fake_miner.commands())
    assert "settings-import" not in fake_miner.commands(), "the write started beside a read of the same profile"
    _release(gate, read, write)
    assert read.error is None and write.error is None, (read.error, write.error)
    assert fake_miner.commands() == ["check", "settings-import"]
    assert write.answer["profile"] == "p-surasura"


def test_a_read_asked_while_a_profile_write_runs_waits_for_it(tmp_path, fake_miner):
    """The other order (flip's smoke 3 and dev's smoke 4 alike: the mine's own calls came after the write started):
    a call asked while the write runs waits until it has ended, then runs and answers."""
    gate = _gate(fake_miner, tmp_path, "settings-import", speech={"installed": [], "model": "large-v3"})
    write = _Call(lambda: anki_miner.settings_import(fake_miner.path, "ja", {"asr_model": "small"},
                                                     str(tmp_path / "speech"), profile="p-surasura"))
    write.start()
    _until(lambda: "settings-import" in fake_miner.commands())
    read = _Call(lambda: anki_miner.settings_export(fake_miner.path, "ja", str(tmp_path / "export.json"),
                                                    profile="p-surasura"))
    read.start()
    _until(lambda: _waiting(fake_miner.path) == 1 or "settings-export" in fake_miner.commands())
    assert "settings-export" not in fake_miner.commands(), "a read started beside the profile's write"
    _release(gate, write, read)
    assert write.error is None and read.error is None, (write.error, read.error)
    assert fake_miner.commands() == ["settings-import", "settings-export"]
    assert read.answer["settings"]["asr_model"] == "small", "the read saw the write's whole file"


def test_the_speech_check_beside_a_mine_under_way_starts_no_write_and_is_asked_again_soon(tmp_path, fake_miner):
    """The E-HIST race itself: Best, no speech model, a mine under way on the run's own thread while the check beside
    the mining asks. `check` (a read) runs beside the mine as it always could; its `settings-import` would only meet
    the mine's run lock (BUSY) — so it starts nothing, the answer is no, and it is asked again in SPEECH_BUSY_S, not
    in SPEECH_NO_S (Michi-T1's busy no)."""
    gate = _gate(fake_miner, tmp_path, "mine", speech={"installed": [], "model": "large-v3"})
    run_file = tmp_path / "run.json"
    run_file.write_text("{}", encoding="utf-8")     # (the fake holds `mine` before it reads the run file)
    mine = _Call(lambda: anki_miner.api(fake_miner.path, ["mine", str(run_file)], timeout=60))
    mine.start()
    _until(lambda: "mine" in fake_miner.commands())
    assert anki_miner.speech_ready(fake_miner.path, "ja", "p-surasura", str(tmp_path / "speech")) is False
    assert fake_miner.commands() == ["mine", "check"], "a profile write started beside the mine"
    ok, at, set_to = anki_miner._SPEECH[(fake_miner.path, "ja", "p-surasura")]
    assert set_to is None
    assert time.monotonic() - at >= anki_miner.SPEECH_NO_S - anki_miner.SPEECH_BUSY_S, "asked again soon"
    _release(gate, mine)


def test_a_profile_write_beside_a_started_call_is_busy_at_once(tmp_path, fake_miner):
    """A call `start` left running (a book's `sync`, the speech model's `setup`: hours) holds the profile too: a write
    beside it is `busy` at once, nothing started — never a wait of hours. Once it has ended, the write runs."""
    gate = _gate(fake_miner, tmp_path, "sync")
    out = tmp_path / "sync.out"
    proc = anki_miner.start(fake_miner.path, ["sync", str(tmp_path / "sync.json")], str(out))
    try:
        _until(lambda: "sync" in fake_miner.commands())
        with pytest.raises(anki_miner.AnkiMinerError) as e:
            anki_miner.settings_import(fake_miner.path, "ja", {}, str(tmp_path / "setup"), profile="p-surasura")
        assert e.value.kind == "busy"
        assert fake_miner.commands() == ["sync"]
    finally:
        _release(gate)
        proc.wait(30)
    anki_miner.settings_import(fake_miner.path, "ja", {}, str(tmp_path / "setup"), profile="p-surasura")
    assert fake_miner.commands() == ["sync", "settings-import"]


def test_a_stop_pressed_while_a_call_waits_for_the_write_ends_the_wait_and_starts_nothing(tmp_path, fake_miner):
    """The run closing (the check's thread) or the job's *Stop* while a call waits behind the write: `Stopped`, as a
    look-up's Stop is (row 56), and its program never started."""
    gate = _gate(fake_miner, tmp_path, "settings-import")
    write = _Call(lambda: anki_miner.settings_import(fake_miner.path, "ja", {}, str(tmp_path / "setup"),
                                                     profile="p-surasura"))
    write.start()
    _until(lambda: "settings-import" in fake_miner.commands())
    pressed = threading.Event()
    read = _Call(lambda: anki_miner.check(fake_miner.path, "ja", "p-surasura"), check=pressed.is_set)
    read.start()
    _until(lambda: _waiting(fake_miner.path) == 1 or "check" in fake_miner.commands())
    pressed.set()
    read.join(30)
    assert not read.is_alive() and isinstance(read.error, stopping.Stopped), read.error
    _release(gate, write)
    assert fake_miner.commands() == ["settings-import"]


def test_reads_still_run_side_by_side_and_another_anki_miner_never_waits(tmp_path, fake_miner):
    """Only a write runs alone: two reads of one profile overlap as before (the check beside the mining stays beside
    it), and a call to another Anki Miner (another program path) never waits for this one's write."""
    gate = _gate(fake_miner, tmp_path, "check")
    first = _Call(lambda: anki_miner.check(fake_miner.path, "ja", "p-surasura"))
    first.start()
    _until(lambda: fake_miner.commands().count("check") == 1)
    second = _Call(lambda: anki_miner.check(fake_miner.path, "zh", "p-surasura"))
    second.start()
    _until(lambda: fake_miner.commands().count("check") == 2)
    assert _waiting(fake_miner.path) == 0
    other = str(tmp_path / "other" / os.path.basename(fake_miner.path))
    os.makedirs(os.path.dirname(other))
    with open(fake_miner.path, "rb") as f, open(other, "wb") as g:
        g.write(f.read())
    anki_miner.settings_import(other, "ja", {}, str(tmp_path / "setup"), profile="p-surasura")
    _release(gate, first, second)
    assert first.error is None and second.error is None
    assert fake_miner.commands() == ["check", "check", "settings-import"]
