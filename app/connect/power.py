"""Connect's power policy (P2.4 row 2.4.6; P1.5 06-edges E32, HC-B12): Connect makes cards only on mains power, at
below-normal priority, so a laptop on battery or in use never pays for it.

- **On battery** (`on_battery`): Windows' `GetSystemPowerStatus` (`ctypes`, the standard library): AC offline → the
  runner waits, *On battery*; AC online, or a status Windows can't tell (a desktop reports 255 for "unknown" on some
  machines) → it goes on. Off Windows there is no check: it runs (ORDER's fallback).
- **Below normal** (`lower_priority`): Connect's own process at `BELOW_NORMAL_PRIORITY_CLASS`; the programs it starts
  (Anki Miner, the analyzer) inherit it (Windows hands a below-normal class down). Off Windows: `os.nice`.
- **The window's background work below normal too** (`popen_below_normal`, a7: alpha 6's Generates beside the window):
  each Generate, the indexer, New arrivals' worker and the store's helper start below normal, and what they start in
  turn inherits it (the indexer's and a look's pools). *Use every core* still means how many cores, never priority:
  a below-normal run takes every idle cycle, and the window — at normal priority — comes first when it needs them.

- **How hard Anki Miner works** (Michi-LP, 2026-11-18; words PROVISIONAL): Anki Miner cuts up to 6 clips at once by
  default (3.13.0 `config/config.py` `max_parallel_workers`) and Connect never asked for fewer. `clip_cuts` picks a
  number from this PC for every Connect run file (`runfile.config`: applied on top of the profile for that run alone,
  nothing saved, so Anki Miner's own setting for manual mining never changes): one cut per CORES_PER_CUT logical CPUs,
  at most what half the free memory holds (CUT_MB each), halved on battery, 1 to CLIP_CUTS_MAX and never more than the
  profile's own value (`profile_cuts`) — or the learner's own pick (`connect_clip_cuts` 1–6, Settings › Anki & mining,
  per PC: an import never brings another PC's, `settings_io.read`). Beta (`connect_low_priority`, off): Connect's
  Anki Miner calls start at idle priority instead (`popen_idle`, `anki_miner.LOW_PRIORITY`), and the ffmpeg it starts
  inherits it. Where this sits beside *Run things by themselves* and the bar's pause (Mado-PZ): those say whether
  Surasura works by itself; these, how hard it works while it does.

- **Which machines need it more gently** (Haya-LD, 3.0.18; Sonic 2026-11-20: "is there a way to tell which machines
  need more gently vs not?" — automatic, no setting at first): `gentle()` reads the PC — its logical CPUs, its total
  memory, on battery or not. Fewer than STRONG_CPUS logical CPUs, less than STRONG_RAM_MB of memory, or on battery →
  gentle: the window's background work goes one heavy job at a time, in an order (`app/services/gentle.py`), and
  Connect's next step waits while a Generate runs. A strong desktop (this one: 24 logical CPUs, 32 GB) runs them side
  by side as before. `CpuLoad` is the system's CPU busy share between two samples (every core, every program: Windows'
  `GetSystemTimes`), the load the window's scheduler watches on every machine (BUSY).
  Why these numbers: Sonic's laptop (8 logical CPUs, the 3.0.16 report #8158GX) lagged with six jobs at once; a
  12-thread PC with 16 GB still has two or three cores free beside a Generate's pool (half the logical CPUs, K5) and
  Anki; and 70 % busy across every core is the point past which Windows' scheduler starts sharing time slices with the
  foreground (Anki, the window), so a background step there would be felt.

A machine asleep runs nothing, so there is nothing to check. Never raises: a call that fails leaves things as they were.
"""
import os
import sys

BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
IDLE_PRIORITY_CLASS = 0x00000040
AC_OFFLINE = 0
NICE = 5
NICE_IDLE = 19                  # off Windows: the lowest a process can be

AUTO = "auto"
CLIP_CUTS_MAX = 6               # Anki Miner's own default (3.13.0 `config/config.py`): automatic never asks for more
CORES_PER_CUT = 4               # one clip at once per 4 logical CPUs: this desktop's 24 -> 6, a laptop's 8 -> 2
CUT_MB = 200                    # one cut's ffmpeg, with headroom (measured: the register, Michi-LP)
OWN_RANGE = (1, 20)             # what Anki Miner's settings take (`config.py`: an integer from 1 to 20)
# Haya-LD: which PCs run their background work one job at a time (the module docstring's *Which machines*)
STRONG_CPUS = 12                # logical CPUs: a laptop's 8 is gentle, a 12-thread desktop isn't
STRONG_RAM_MB = 15 * 1024       # total memory: a "16 GB" PC reports ~15.8 GB, an 8 GB one is gentle
BUSY = 0.70                     # the system's CPU busy share over the scheduler's window: the next background step waits
QUIET = 0.55                    # ... until it is below this again (no flapping at the line)


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
                # Its own WinDLL, the handle typed (Michi-LP, measured: ctypes' default int cut the 64-bit
                # pseudo-handle, Windows refused it, and nothing — Connect, Anki Miner, ffmpeg — was ever lowered)
                import ctypes
                from ctypes import wintypes
                kernel32 = ctypes.WinDLL("kernel32")
                kernel32.GetCurrentProcess.restype = wintypes.HANDLE
                kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
                return bool(kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS))
            return bool(set_class(BELOW_NORMAL_PRIORITY_CLASS))
        (nice or os.nice)(NICE)
        return True
    except Exception:
        return False


def popen_below_normal(args, popen=None, platform=None, **kwargs):
    """`popen(args, **kwargs)` (default `subprocess.Popen`) started below normal priority: on Windows its creation flags
    gain `BELOW_NORMAL_PRIORITY_CLASS` (set before it runs a line: its own children inherit it); off Windows the
    child's niceness is raised by `NICE` once it runs. A priority that can't be set leaves the child at normal, never
    unstarted. -> the Popen."""
    return _popen_at(BELOW_NORMAL_PRIORITY_CLASS, lambda now: now + NICE, args, popen, platform, kwargs)


def popen_idle(args, popen=None, platform=None, **kwargs):
    """`popen_below_normal` at idle instead (Beta *Run Anki Miner at low priority*): Windows' `IDLE_PRIORITY_CLASS`,
    which its own children inherit (Anki Miner's ffmpeg, its speech model); off Windows niceness `NICE_IDLE`. -> the
    Popen, started whatever the priority's answer."""
    return _popen_at(IDLE_PRIORITY_CLASS, lambda now: max(now, NICE_IDLE), args, popen, platform, kwargs)


def _popen_at(priority_class, nice, args, popen, platform, kwargs):
    if (platform or sys.platform) == "win32":
        kwargs["creationflags"] = (kwargs.get("creationflags") or 0) | priority_class
    if popen is None:
        import subprocess
        popen = subprocess.Popen
    proc = popen(args, **kwargs)
    if (platform or sys.platform) != "win32":
        try:
            os.setpriority(os.PRIO_PROCESS, proc.pid, nice(os.getpriority(os.PRIO_PROCESS, proc.pid)))
        except Exception:
            pass
    return proc


def _free_mb():
    """Physical memory free now, in MB, or None (the indexer's reading: `token_index._free_memory_mb`)."""
    try:
        from app.token_index import _free_memory_mb
        return _free_memory_mb()
    except Exception:
        return None


def _own(value):
    """An Anki Miner `max_parallel_workers` as its settings take it (an int, never a bool, 1–20), else None."""
    low, high = OWN_RANGE
    return value if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high else None


def profile_cuts(export):
    """The profile's own clips-at-once (`max_parallel_workers`) in an Anki Miner settings export, or None."""
    settings = export.get("settings") if isinstance(export, dict) else None
    return _own(settings.get("max_parallel_workers")) if isinstance(settings, dict) else None


def clip_cuts(setting=AUTO, own=None, cpus=None, free_mb=None, battery=None):
    """How many clips Anki Miner cuts at once in a Connect run (the run file's `max_parallel_workers`). `setting`:
    `connect_clip_cuts` — a number 1–CLIP_CUTS_MAX is sent as it is; anything else (AUTO, a hand-edited 0, 9, "3",
    true) is automatic: cpus // CORES_PER_CUT, at most half the free memory // CUT_MB, halved on battery, 1 to
    CLIP_CUTS_MAX and never above `own` (`profile_cuts`, when it reads). `cpus` / `free_mb` / `battery`: stand-ins for
    this machine's (tests; None: read here, a memory that can't be read leaves the CPUs to decide)."""
    if isinstance(setting, int) and not isinstance(setting, bool) and 1 <= setting <= CLIP_CUTS_MAX:
        return setting
    cuts = (cpus if cpus is not None else (os.cpu_count() or 1)) // CORES_PER_CUT
    free_mb = free_mb if free_mb is not None else _free_mb()
    if free_mb is not None:
        cuts = min(cuts, int(free_mb * 0.5) // CUT_MB)
    if battery if battery is not None else on_battery():
        cuts //= 2
    return max(1, min(cuts, CLIP_CUTS_MAX, _own(own) or CLIP_CUTS_MAX))


def total_memory_mb():
    """Physical memory installed, in MB, or None when it can't be told."""
    try:
        if os.name == "nt":
            import ctypes

            class _Status(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = _Status()
            status.dwLength = ctypes.sizeof(_Status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return status.ullTotalPhys // (1024 * 1024)
            return None
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") // (1024 * 1024)
    except Exception:
        return None


def usable_cpus():
    """The logical CPUs this process may run on (Windows: its affinity mask — a PC's cores held to a few, a VM's share),
    else `os.cpu_count()`; at least 1."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            k = ctypes.WinDLL("kernel32")
            k.GetCurrentProcess.restype = wintypes.HANDLE
            k.GetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_size_t),
                                                 ctypes.POINTER(ctypes.c_size_t)]
            mine, system = ctypes.c_size_t(), ctypes.c_size_t()
            if k.GetProcessAffinityMask(k.GetCurrentProcess(), ctypes.byref(mine), ctypes.byref(system)) and mine.value:
                return bin(mine.value).count("1")
        elif hasattr(os, "sched_getaffinity"):
            return len(os.sched_getaffinity(0)) or 1
    except Exception:
        pass
    return os.cpu_count() or 1


def gentle(cpus=None, total_mb=None, battery=None):
    """Does this PC run its background work one heavy job at a time (Haya-LD)? -> (True, why) with why in plain words
    (*on battery*, *8 logical CPUs*, *8 GB of memory*), or (False, None) on a strong PC. `cpus` / `total_mb` /
    `battery`: stand-ins for this machine's (tests; None: read here — a memory that can't be read leaves the CPUs and
    the battery to decide)."""
    if battery if battery is not None else on_battery():
        return True, "on battery"
    cpus = cpus if cpus is not None else usable_cpus()
    if cpus < STRONG_CPUS:
        return True, f"{cpus} logical CPUs"
    total_mb = total_mb if total_mb is not None else total_memory_mb()
    if total_mb is not None and total_mb < STRONG_RAM_MB:
        return True, f"{total_mb / 1024:.0f} GB of memory"
    return False, None


class CpuLoad:
    """The system's CPU busy share (0.0–1.0, every core, every program) between two `sample()` calls — None at the
    first, and wherever it can't be read. Windows: `GetSystemTimes` (kernel time includes idle); elsewhere
    `/proc/stat`. `read`: a stand-in returning (idle, total) counters (tests)."""

    def __init__(self, read=None):
        self._read = read or _cpu_times
        self._last = None

    def sample(self):
        try:
            now = self._read()
        except Exception:
            now = None
        last, self._last = self._last, now
        if now is None or last is None:
            return None
        idle, total = now[0] - last[0], now[1] - last[1]
        if total <= 0:
            return None
        return max(0.0, min(1.0, 1.0 - idle / total))


def _cpu_times():
    """(idle, total) CPU time counters of the whole system, or None."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None

        def ticks(ft):
            return (ft.dwHighDateTime << 32) | ft.dwLowDateTime
        return ticks(idle), ticks(kernel) + ticks(user)
    with open("/proc/stat", encoding="ascii") as f:
        fields = [int(x) for x in f.readline().split()[1:]]
    return fields[3] + (fields[4] if len(fields) > 4 else 0), sum(fields)
