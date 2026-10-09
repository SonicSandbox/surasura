"""Connect's power policy (P2.4 row 2.4.6; P1.5 06-edges E32, HC-B12): Connect makes cards only on mains power, at
below-normal priority, so a laptop on battery or in use never pays for it.

- **On battery** (`on_battery`): Windows' `GetSystemPowerStatus` (`ctypes`, the standard library): AC offline → the
  runner waits, *On battery*; AC online, or a status Windows can't tell (a desktop reports 255 for "unknown" on some
  machines) → it goes on. Off Windows there is no check: it runs (ORDER's fallback).
- **Below normal** (`lower_priority`): Connect's own process at `BELOW_NORMAL_PRIORITY_CLASS`; the programs it starts
  (Anki Miner, the analyzer) inherit it (Windows hands a below-normal class down). Off Windows: `os.nice`.

A machine asleep runs nothing, so there is nothing to check. Never raises: a call that fails leaves things as they were.
"""
import os
import sys

BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
AC_OFFLINE = 0
NICE = 5


def _status():
    """Windows' SYSTEM_POWER_STATUS as a dict, or None."""
    import ctypes
    from ctypes import wintypes

    class SystemPowerStatus(ctypes.Structure):
        _fields_ = [("ACLineStatus", wintypes.BYTE), ("BatteryFlag", wintypes.BYTE),
                    ("BatteryLifePercent", wintypes.BYTE), ("SystemStatusFlag", wintypes.BYTE),
                    ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]

    status = SystemPowerStatus()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return None
    return {"ac": status.ACLineStatus & 0xFF, "battery_flag": status.BatteryFlag & 0xFF,
            "percent": status.BatteryLifePercent & 0xFF}


def on_battery(platform=None, status=None):
    """Is this machine running on its battery now? Only Windows says (off Windows: False, the check skipped).
    `status`: a stand-in for Windows' answer (tests)."""
    if (platform or sys.platform) != "win32":
        return False
    try:
        answer = (status or _status)()
    except Exception:
        return False
    return bool(answer) and answer.get("ac") == AC_OFFLINE


def lower_priority(platform=None, set_class=None, nice=None):
    """Connect's process to below-normal priority (its children inherit it) -> True when lowered. `set_class` /
    `nice`: stand-ins for the OS calls (tests)."""
    try:
        if (platform or sys.platform) == "win32":
            if set_class is None:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                return bool(kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS))
            return bool(set_class(BELOW_NORMAL_PRIORITY_CLASS))
        (nice or os.nice)(NICE)
        return True
    except Exception:
        return False
