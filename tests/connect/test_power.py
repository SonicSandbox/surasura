"""Connect's power policy (P2.4 row 2.4.6): Connect makes cards only on mains power, at below-normal priority.

What a wrong answer would cost: a laptop unplugged mid-run would keep Anki Miner grinding on its battery (the user's
battery and fan pay for every card), and a desktop reporting "unknown" (255) or a status Windows can't read would be
held back forever. So only "AC offline" (0) counts as battery; AC online (1), unknown (255), no status (None) and a
status call that raises all go on. Off Windows there is no check at all. The status and OS calls are stand-ins passed
in (the module's own `status=` / `platform=` / `set_class=` / `nice=` seams), so these tests never touch the real
power API or the real process priority.
"""
from app.connect import power


def _recorder(answer):
    """A stand-in for Windows' status call that records every call, so 'the check was skipped' can be asserted."""
    calls = []

    def status():
        calls.append(1)
        return answer
    return status, calls


def test_on_windows_only_an_ac_offline_status_counts_as_battery():
    # AC offline is the one answer that means 'on battery'; the others are mains, unknown or absent.
    assert power.on_battery("win32", lambda: {"ac": power.AC_OFFLINE, "percent": 61}) is True
    assert power.on_battery("win32", lambda: {"ac": 1, "percent": 61}) is False, "mains power is not battery"
    assert power.on_battery("win32", lambda: {"ac": 255, "percent": 0}) is False, "unknown is not battery"
    assert power.on_battery("win32", lambda: None) is False, "no status is not battery"


def test_a_status_call_that_raises_reads_as_not_on_battery():
    # A failing OS call must never stop the runner or make it wait as if unplugged.
    def boom():
        raise OSError("GetSystemPowerStatus failed")
    assert power.on_battery("win32", boom) is False


def test_off_windows_the_power_check_is_skipped_and_the_job_runs():
    # Off Windows there is no check: the status is never asked, and the answer is always 'not on battery'.
    status, calls = _recorder({"ac": power.AC_OFFLINE})
    assert power.on_battery("linux", status) is False
    assert calls == [], "a non-Windows machine never asks the Windows status call"


def test_lower_priority_on_windows_sets_the_below_normal_class_and_reports_it():
    # Connect's own process goes to BELOW_NORMAL (0x4000); its children inherit it. The return value says it worked.
    seen = []

    def set_class(value):
        seen.append(value)
        return 1
    assert power.lower_priority("win32", set_class=set_class, nice=lambda n: 1 / 0) is True
    assert seen == [0x4000], "Windows is asked for BELOW_NORMAL_PRIORITY_CLASS and nothing else"


def test_lower_priority_elsewhere_uses_nice_five_and_a_failing_call_never_raises():
    # Off Windows the process is niced by 5; a failing priority call leaves things as they were, without an exception.
    niced = []
    assert power.lower_priority("linux", set_class=lambda v: 1 / 0, nice=lambda n: niced.append(n)) is True
    assert niced == [power.NICE] == [5]

    def refuse(n):
        raise PermissionError("nice refused")
    assert power.lower_priority("linux", nice=refuse) is False
    assert power.lower_priority("win32", set_class=refuse) is False
