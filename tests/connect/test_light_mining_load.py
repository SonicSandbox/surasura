"""Mining that leaves the PC usable (Michi-LP, 2026-11-18; words PROVISIONAL).

- **Clips cut at once** (`power.clip_cuts`, `connect_clip_cuts`): Anki Miner cuts up to 6 clips side by side by
  default (3.13.0 `config/config.py` `max_parallel_workers = 6`) and Connect never asked for fewer. Now each Connect run
  file names a number picked from this PC — one cut per 4 logical CPUs, at most what half the free memory holds, halved
  on battery, 1 to 6 and never more than the profile's own value — or the learner's own pick (Settings, 1–6). It goes
  in the run's `config` (API.md "mine": applied on top, nothing saved), so Anki Miner's own setting for manual mining
  never changes. Per PC: an imported settings file never brings another PC's pick.
- **Run Anki Miner at low priority** (`connect_low_priority`, Beta, off): every Anki Miner call Connect's run starts
  goes at idle priority (`power.popen_idle`), and its ffmpeg children inherit it.

What a wrong answer would cost: a laptop with 8 threads still cutting 6 clips at once (the fans, a stuttering window
while it mines); a desktop slowed to 1; the learner's own Anki Miner setting changed behind their back; a desktop's
pick carried to a laptop by Import settings; a priority that can't be set stopping a mine.

The words are real: one line of the library episode (`ja/library_episode.ass`) and a Chinese one.
"""
import json
import os
import subprocess
import sys

import pytest

from app.connect import anki_miner, power, runfile
from app.connect.fields import Mapping

MAPPING = Mapping("Mining", "Lapis", {"word": "Expression", "sentence": "Sentence", "audio": "SentenceAudio"},
                  "Expression", "Sentence", None, None)
WORDS = {"ja": [{"word": "時間", "reading": "じかん", "surface": "時間", "line_start": 12.4, "line_expansion": [0, 0],
                 "sent": ["時間"], "predicted_class": None}],
         "zh": [{"word": "夜市", "reading": "", "surface": "夜市", "line_start": 4.1, "line_expansion": [0, 0],
                 "sent": ["夜市"], "predicted_class": None}]}
INFO = {"app": "3.13.0", "features": ["named-words-whitelisted", "word-from-line", "bold-target", "sentence-rules-off"]}


# --- how many clips at once ---------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("cpus, cuts", [(1, 1), (2, 1), (4, 1), (8, 2), (12, 3), (16, 4), (24, 6), (64, 6)])
def test_automatic_cuts_one_clip_per_four_logical_cpus_from_one_to_six(cpus, cuts):
    """The rule: a laptop's 8 threads cut 2 clips at once, this desktop's 24 (a Ryzen 9 3900X) cut 6, Anki Miner's own
    default, and never more however many there are; a 2-thread machine still cuts one."""
    assert power.clip_cuts("auto", cpus=cpus, free_mb=64_000, battery=False) == cuts


def test_automatic_halves_on_battery_and_never_reaches_zero():
    # on battery Connect mines only when you asked it to (`runner`): even then it works half as hard
    assert power.clip_cuts("auto", cpus=24, free_mb=64_000, battery=True) == 3
    assert power.clip_cuts("auto", cpus=8, free_mb=64_000, battery=True) == 1
    assert power.clip_cuts("auto", cpus=4, free_mb=64_000, battery=True) == 1


def test_automatic_cuts_no_more_than_half_the_free_memory_holds():
    each = power.CUT_MB
    assert power.clip_cuts("auto", cpus=24, free_mb=each * 2 * 3, battery=False) == 3
    assert power.clip_cuts("auto", cpus=24, free_mb=each, battery=False) == 1     # little free: one, never none
    assert power.clip_cuts("auto", cpus=24, free_mb=None, battery=False) == 6     # memory not told: the CPUs decide


@pytest.mark.parametrize("own, cuts", [(2, 2), (4, 4), (6, 6), (12, 6), (None, 6), (0, 6), (True, 6), ("3", 6),
                                       (25, 6)])
def test_automatic_never_asks_for_more_than_the_profiles_own_value(own, cuts):
    """A learner who set Anki Miner to 2 keeps 2 on any PC; one set above 6 (or not readable: a bool, text, out of
    Anki Miner's 1–20) gets the PC's number, at most 6."""
    assert power.clip_cuts("auto", own=own, cpus=24, free_mb=64_000, battery=False) == cuts


@pytest.mark.parametrize("setting", [1, 2, 3, 4, 5, 6])
def test_a_number_you_pick_is_sent_as_it_is_on_any_pc(setting):
    for cpus, battery in ((2, True), (64, False)):
        assert power.clip_cuts(setting, own=2, cpus=cpus, free_mb=100, battery=battery) == setting


@pytest.mark.parametrize("setting", ["auto", None, 0, 7, -1, True, False, "3", 2.0, [3]])
def test_anything_else_in_the_setting_reads_as_automatic(setting):
    """A hand-edited settings.json (0, 7, "3", true) is never sent as it is: Anki Miner refuses a bool or a value
    outside 1–20 (BAD_RUN_FILE), and the whole run would stop on it."""
    assert power.clip_cuts(setting, cpus=8, free_mb=64_000, battery=False) == 2


def test_the_machine_is_read_when_nothing_is_handed_in(monkeypatch):
    monkeypatch.setattr(power.os, "cpu_count", lambda: 12)
    monkeypatch.setattr(power, "on_battery", lambda: False)
    monkeypatch.setattr(power, "_free_mb", lambda: 64_000)
    assert power.clip_cuts("auto") == 3


def test_the_profiles_own_value_is_read_from_anki_miners_settings_export():
    assert power.profile_cuts({"settings": {"max_parallel_workers": 3}}) == 3
    for export in (None, {}, {"settings": None}, {"settings": {}}, {"settings": {"max_parallel_workers": "x"}}):
        assert power.profile_cuts(export) is None


# --- the run file ---------------------------------------------------------------------------------------------------- #
def test_the_run_files_config_names_the_cuts_only_when_asked():
    assert runfile.config(MAPPING, "3.13.0", INFO["features"], workers=2)["max_parallel_workers"] == 2
    assert "max_parallel_workers" not in runfile.config(MAPPING, "3.13.0", INFO["features"])


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_mine_call_writes_the_cuts_into_its_run_file(tmp_path, monkeypatch, language):
    monkeypatch.setattr(anki_miner, "preflight", lambda *a, **k: (INFO, "surasura"))
    sent = []
    monkeypatch.setattr(anki_miner.runfile, "write", lambda path, data: sent.append(data) or path)

    class Sent(Exception):
        pass
    monkeypatch.setattr(anki_miner, "result_names", lambda *a: (_ for _ in ()).throw(Sent()))
    with pytest.raises(Sent):
        anki_miner._mine_held("am.exe", language, "lp-1", "v.mp4", "v.srt", WORDS[language], MAPPING, "Surasura",
                              str(tmp_path), 1, 0.0, 60, workers=3)
    assert sent[0]["config"]["max_parallel_workers"] == 3


# --- Connect's mine step --------------------------------------------------------------------------------------------- #
def _mine_step(monkeypatch, settings, held_export=None, lang="ja"):
    """The runner's mine step with Anki Miner and its look-ups stood in: what it hands `mine_batch`."""
    from types import SimpleNamespace

    from app.cli import verbs
    from app.connect import runner
    monkeypatch.setattr(anki_miner, "LOW_PRIORITY", False)         # restored after: never leaks to another test
    monkeypatch.setattr(anki_miner, "find", lambda loaded: "am.exe")
    mapping = SimpleNamespace(word="Expression")

    def setup(loaded, lang, run_dir, held=None):
        if held is not None and held_export is not None:
            held.update(set=(INFO, "surasura", mapping, held_export))
        return INFO, "surasura", mapping
    monkeypatch.setattr(verbs, "_anki_miner_setup", setup)
    monkeypatch.setattr(verbs, "settings", lambda: dict(settings))
    monkeypatch.setattr(power, "_free_mb", lambda: 64_000)
    monkeypatch.setattr(power, "on_battery", lambda: False)
    monkeypatch.setattr(power.os, "cpu_count", lambda: 24)
    seen = {}

    def mine_batch(*a, **k):
        seen.update(k, low=anki_miner.LOW_PRIORITY)
        return {"outcomes": [], "app": "3.13.0"}
    monkeypatch.setattr(anki_miner, "mine_batch", mine_batch)
    picked = {"video": "v.mp4", "subtitle": "v.srt", "offset": 0.0, "profile": None}
    runner.Steps({}).mine(lang, {"id": 1, "item_id": 1, "tag": f"{lang}-1"}, picked, WORDS[lang], 1)
    return seen


@pytest.mark.parametrize("lang", ["ja", "zh"])
@pytest.mark.parametrize("settings, export, cuts", [
    ({}, None, 6),                                                      # automatic, this desktop's 24 CPUs
    ({"connect_clip_cuts": "auto"}, {"settings": {"max_parallel_workers": 2}}, 2),   # the profile's own 2 kept
    ({"connect_clip_cuts": 4}, {"settings": {"max_parallel_workers": 2}}, 4),        # your pick in Surasura
    ({"connect_clip_cuts": 9}, None, 6),                                # hand-edited: automatic
])
def test_connects_mine_step_asks_for_the_cuts_settings_json_says_now(monkeypatch, settings, export, cuts, lang):
    assert _mine_step(monkeypatch, settings, export, lang)["workers"] == cuts


@pytest.mark.parametrize("settings, low", [({}, False), ({"connect_low_priority": False}, False),
                                           ({"connect_low_priority": "yes"}, False), ({"connect_low_priority": True}, True)])
def test_connects_mine_step_runs_anki_miner_at_low_priority_only_while_the_beta_switch_is_on(monkeypatch, settings, low):
    assert _mine_step(monkeypatch, settings)["low"] is low


def test_connects_run_takes_the_beta_switch_as_it_starts(monkeypatch):
    """Anki Miner calls before the first mine (a spot-check's `media` / `transcribe`, a book's `sync`) follow the
    switch too: the run sets it as it lowers its own priority."""
    from app.connect import runner
    monkeypatch.setattr(anki_miner, "LOW_PRIORITY", False)
    monkeypatch.setattr(power, "lower_priority", lambda: True)
    runner.Steps({"connect_low_priority": True}).lower_priority()
    assert anki_miner.LOW_PRIORITY is True
    runner.Steps({}).lower_priority()
    assert anki_miner.LOW_PRIORITY is False


# --- Connect's own below normal (found measuring: it never took) ---------------------------------------------------- #
@pytest.mark.skipif(sys.platform != "win32", reason="Windows priority classes")
def test_connects_run_really_goes_below_normal_and_the_programs_it_starts_inherit_it():
    """Measured on DevTest (Michi-LP): Anki Miner ran at NORMAL under Connect. `lower_priority` handed Windows the
    process's pseudo-handle through ctypes' default int (64-bit Python cuts it), so SetPriorityClass refused, returned
    False and nothing was lowered — not Connect, not Anki Miner, not its ffmpeg. In a child process: the test's own
    process keeps its priority."""
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    code = ("import ctypes, subprocess, sys; sys.path.insert(0, sys.argv[1]); from app.connect import power; "
            "k = ctypes.WinDLL('kernel32'); k.GetCurrentProcess.restype = ctypes.c_void_p; "
            "k.GetPriorityClass.argtypes = [ctypes.c_void_p]; "
            "ok = power.lower_priority(); own = k.GetPriorityClass(k.GetCurrentProcess()); "
            "child = subprocess.run([sys.executable, '-c', 'import ctypes; k = ctypes.WinDLL(\"kernel32\"); "
            "k.GetCurrentProcess.restype = ctypes.c_void_p; k.GetPriorityClass.argtypes = [ctypes.c_void_p]; "
            "print(k.GetPriorityClass(k.GetCurrentProcess()))'], capture_output=True, text=True).stdout.strip(); "
            "print(ok, own, child)")
    out = subprocess.run([sys.executable, "-c", code, repo], capture_output=True, text=True, timeout=120)
    ok, own, child = out.stdout.split()
    assert ok == "True", out.stderr
    assert int(own) == power.BELOW_NORMAL_PRIORITY_CLASS and int(child) == power.BELOW_NORMAL_PRIORITY_CLASS


# --- idle priority --------------------------------------------------------------------------------------------------- #
class _Popen:
    def __init__(self, args, **kwargs):
        self.args, self.kwargs, self.pid = args, kwargs, 4242


def test_popen_idle_starts_the_program_at_idle_on_windows_keeping_its_own_flags():
    proc = power.popen_idle(["AnkiMiner.exe", "--api", "mine"], popen=_Popen, platform="win32", creationflags=0x8000000)
    assert proc.kwargs["creationflags"] == 0x8000000 | power.IDLE_PRIORITY_CLASS
    assert not proc.kwargs["creationflags"] & power.BELOW_NORMAL_PRIORITY_CLASS


def test_popen_idle_off_windows_raises_the_childs_niceness_and_a_refusal_still_starts_it(monkeypatch):
    asked = []
    monkeypatch.setattr(power.os, "getpriority", lambda which, pid: 5, raising=False)
    monkeypatch.setattr(power.os, "setpriority", lambda which, pid, n: asked.append((pid, n)), raising=False)
    monkeypatch.setattr(power.os, "PRIO_PROCESS", 0, raising=False)
    proc = power.popen_idle(["anki-miner"], popen=_Popen, platform="linux")
    assert asked == [(4242, power.NICE_IDLE)] and "creationflags" not in proc.kwargs

    def refused(*a):
        raise PermissionError("not allowed")
    monkeypatch.setattr(power.os, "setpriority", refused, raising=False)
    assert power.popen_idle(["anki-miner"], popen=_Popen, platform="linux").pid == 4242


@pytest.mark.parametrize("low", [False, True])
def test_anki_miners_calls_start_at_idle_only_while_low_priority_is_on(monkeypatch, tmp_path, low):
    started = []

    class Proc:
        returncode, pid, _handle = 0, 1, 0

        def __init__(self, args, **kwargs):
            started.append(kwargs.get("creationflags") or 0)

    monkeypatch.setattr(anki_miner, "LOW_PRIORITY", low)
    monkeypatch.setattr(anki_miner.subprocess, "Popen", Proc)
    monkeypatch.setattr(anki_miner, "_bind", lambda proc: None)
    monkeypatch.setattr(anki_miner, "_communicate", lambda *a, **k: b'{"schema": 1, "ok": true}\n')
    monkeypatch.setattr(power.sys, "platform", "win32")
    monkeypatch.setattr(anki_miner.sys, "platform", "win32")
    anki_miner.api("am.exe", ["version"])
    anki_miner.start("am.exe", ["sync", "job"], str(tmp_path / "out.json"))
    assert [bool(f & power.IDLE_PRIORITY_CLASS) for f in started] == [low, low]


# --- the fake Anki Miner, for real: the run file it reads and the priority it and its child run at ------------------ #
@pytest.mark.parametrize("low", [False, True])
def test_a_real_mine_call_sends_the_cuts_and_anki_miner_and_its_child_run_at_the_priority_asked(tmp_path, fake_miner,
                                                                                               monkeypatch, low):
    from app.connect import fields
    from tests.connect.fake_anki_miner import LAPIS_EXPORT
    episode = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Test Resources", "ja",
                           "library_episode.ass")
    video = tmp_path / "episode.mkv"
    video.write_bytes(b"\x1aE\xdf\xa3")
    fake_miner.plan(child_priority=True)
    monkeypatch.setattr(anki_miner, "LOW_PRIORITY", low)
    anki_miner.mine_batch(fake_miner.path, "ja", "job-1", str(video), episode, WORDS["ja"],
                          fields.from_export(LAPIS_EXPORT), "Surasura", str(tmp_path / "runs" / "job-1"),
                          "http://127.0.0.1:9", workers=2)
    assert fake_miner.run_files()[-1]["config"]["max_parallel_workers"] == 2
    priorities = [c["priority"] for c in fake_miner.calls() if "priority" in c]
    if sys.platform != "win32":
        return
    # Connect's own process may be below normal already (`power.lower_priority`): off, Anki Miner is at most that
    want = power.IDLE_PRIORITY_CLASS if low else None
    assert len(priorities) == 1
    for name in ("self", "child"):
        if want:
            assert priorities[0][name] == want, (name, priorities)
        else:
            assert priorities[0][name] != power.IDLE_PRIORITY_CLASS, (name, priorities)


# --- Settings --------------------------------------------------------------------------------------------------------- #
def test_the_cuts_row_is_under_more_options_with_connect_on_and_automatic_says_this_pcs_number(monkeypatch):
    from app import settings_manager
    from app.qt import settings_catalog as catalog
    from app.qt import settings_strings
    row = catalog.ROW["connect_clip_cuts"]
    assert row.keys == ("connect_clip_cuts",) and row.section == "anki" and row.adv
    assert row.when({"connect_enabled": True}, "ja", set()) and row.when({"connect_enabled": True}, "zh", set())
    assert not row.when({"connect_enabled": False}, "ja", set())
    assert settings_manager.DEFAULT_SETTINGS["connect_clip_cuts"] == "auto"
    monkeypatch.setattr(power, "clip_cuts", lambda setting="auto", **k: 3)
    choices = catalog.options(row, {}, "ja")
    assert [v for v, _l, _line in choices] == ["auto", 1, 2, 3, 4, 5, 6]
    assert "3" in choices[0][1], "Automatic names what it picks on this PC"
    assert settings_strings.ROWS["connect_clip_cuts"][1]


def test_the_low_priority_switch_is_the_beta_lists_and_off_as_shipped():
    """One Beta list at the end of Settings (the AI voice's group): a switch, one ? line, off."""
    from app import settings_manager
    from app.qt import settings_catalog as catalog
    from app.qt import settings_strings
    row = catalog.ROW["connect_low_priority"]
    assert row.kind == "toggle" and row.keys == ("connect_low_priority",) and row.section == "app"
    assert settings_manager.DEFAULT_SETTINGS["connect_low_priority"] is False
    rows = catalog.rows("app")
    at = rows.index(row)
    group = next(r.group for r in reversed(rows[:at + 1]) if r.group)
    assert group == "beta", "under the Beta group's name"
    assert "beta" in settings_strings.ROWS["connect_low_priority"][2].lower(), "its tooltip says Beta"
    assert row.when({"connect_enabled": True}, "ja", set()) and not row.when({"connect_enabled": False}, "ja", set())


def test_neither_setting_is_in_a_runs_signature():
    from app import analyzer, settings_placement
    for key in ("connect_clip_cuts", "connect_low_priority"):
        assert settings_placement.PLACED[key] == "neither"
    plain = analyzer.settings_signature({"target_language": "ja"}, "ja")
    assert analyzer.settings_signature({"target_language": "ja", "connect_clip_cuts": 2,
                                        "connect_low_priority": True}, "ja") == plain


@pytest.mark.parametrize("here, kept", [({"connect_clip_cuts": 2}, 2), ({}, None)])
def test_an_imported_settings_file_never_brings_another_pcs_cuts_and_keeps_this_pcs(tmp_path, here, kept):
    """Per PC: a desktop's 6 imported on a laptop would be the load this was made to stop, and an import replaces
    settings.json whole — so the file's pick is left out and this PC's own (or none: automatic) is kept. The file's other
    settings come in as they are, the low-priority switch (a preference, not the machine's) among them."""
    from app.services import settings_io
    from tests.test_settings_io import _file, _install
    _install(dict({"target_language": "ja", "connect_low_priority": False}, **here))
    path = tmp_path / "Surasura settings.json"
    path.write_text(json.dumps({settings_io.MARK: 1, "version": "3.0.0", "language": "ja",
                                "settings": {"connect_clip_cuts": 6, "connect_low_priority": True,
                                             "target_language": "ja"}}), encoding="utf-8")
    plan = settings_io.read(str(path))
    assert plan.refused is None
    assert "connect_clip_cuts" not in plan.settings and plan.settings["connect_low_priority"] is True
    assert "connect_clip_cuts" not in plan.dropped, "not a setting this version doesn't use: this PC's own"
    assert settings_io.apply(plan).ok
    after = _file()
    assert after.get("connect_clip_cuts") == kept and after["connect_low_priority"] is True
