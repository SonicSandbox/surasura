"""The journey kept current in the background (E3.2; research/17 §2.7, the debounce): one Generate after the moves stop.

A move re-plans in milliseconds (the plan engine), but the journey — the lists, the sentences, the report — needs a full
Generate. `JourneyKeeper` (one per window and language) runs that Generate by itself, quietly, once the moves stop:

- `changed(reason)` after every store command that moved the order or the pins, a placement from New arrivals (E2.2's
  provisional numbers) and a level or band change. A background run already in flight is withdrawn at once (a second
  burst: cancelled before *Writing your list*, else it finishes) and the settle timer starts again.
- When nothing has changed for the settle time — `journey_settle_s` (3 s), or `journey_settle_battery_s` (30 s) while
  the computer runs on its battery (Sonic, E3.2-1, 2026-10-08; both in advanced settings) — it asks, on the timer's
  thread, whether the journey is pending (`analyzer.journey_is_current`: a burst that came back to the analysed order
  asks for nothing, S19), and if so the Generate controller for one quiet run (`quiet=True`, `settle=0`). The
  controller's registry keeps it to one Generate at a time, and an automatic run yields to the user's own.
- After a Generate of its language finishes (any Generate, told by the run itself: `GenerateController.on_end`):
  shadow mode (E1.1 05 §3) — the engine built from the plan the run replaced, re-planned to the run's order, against
  the run's own lists: a difference writes one line to `replan_shadow.log` — then `on_done(plan_path)` when the plan is
  new, so the window re-baselines its engine from it.
- `close()` (the window closes, or its language changes) leaves nothing: no timer, its own run withdrawn, no listener.

Nothing here waits on the caller's thread: `changed` and `close` only arm or cancel a timer; the settings, the battery,
the journey check, the request and the shadow compare are read and run on the timer's thread or the controller's. The
battery is read with the standard library only (unknown: plugged in).
"""
import os
import subprocess
import sys
import threading
import time

SETTLE_S = 3.0              # seconds after the last move (Sonic: "every 3 seconds unless it's on a laptop")
SETTLE_BATTERY_S = 30.0     # ... and on a laptop's battery, every 30 seconds
SETTLE_MAX_S = 3600.0       # a hand-edited setting is held to an hour (a Timer can't wait for ever)
FIRST_LOOK_S = 0.5          # a burst's timer looks this soon at most, so a shorter setting is never a burst late
SHADOW_LOG = "replan_shadow.log"


def on_battery():
    """Whether the computer runs on its battery now — False when plugged in, without a battery, or when it can't be
    told. Windows `GetSystemPowerStatus`, Linux `/sys/class/power_supply`, macOS `pmset -g batt`."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class _Status(ctypes.Structure):
                _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                            ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                            ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]
            status = _Status()
            if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
                return False
            return status.ACLineStatus == 0         # 0 offline (the battery), 1 online, 255 unknown
        if sys.platform == "darwin":
            out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=2).stdout
            return "Battery Power" in out
        base = "/sys/class/power_supply"
        supplies = os.listdir(base)
        for name in supplies:
            try:
                with open(os.path.join(base, name, "type")) as f:
                    kind = f.read().strip()
                if kind == "Mains":
                    with open(os.path.join(base, name, "online")) as f:
                        if f.read().strip() == "1":
                            return False
            except OSError:
                continue
        for name in supplies:
            try:
                with open(os.path.join(base, name, "status")) as f:
                    if f.read().strip() == "Discharging":
                        return True
            except OSError:
                continue
    except Exception:
        pass
    return False


def settle_seconds(settings, battery):
    """The quiet time before the background Generate: the settings' own (advanced settings), else the defaults; held
    to [0, an hour] — a word, a negative number, infinity or NaN in a hand-edited file reads as the default."""
    key, default = ("journey_settle_battery_s", SETTLE_BATTERY_S) if battery else ("journey_settle_s", SETTLE_S)
    try:
        value = float((settings or {}).get(key, default))
    except (TypeError, ValueError):
        return default
    if not 0 <= value < float("inf"):
        return default
    return min(value, SETTLE_MAX_S)


class JourneyKeeper:
    """One per window and language. `controller`: the window's `GenerateController`. `settings()`: the settings now
    (the window's settings service `get`; default `settings_manager.load_settings`). `pending()`: whether the journey
    needs a Generate (default: `analyzer.journey_is_current` is not True), asked on the timer's thread. `on_done(path)`:
    after a Generate of this language lands with a new plan, with the plan file's path. `battery()`: `on_battery` (a
    test's stand-in). `launcher`: how the controller starts the child (`GenerateController.request`'s; default its own).
    `enabled()`: whether the background Generate is on (D29's one switch, the window's; default always)."""

    def __init__(self, controller, language, settings=None, pending=None, on_done=None, battery=None,
                 plan_path=None, launcher=None, enabled=None):
        self.controller = controller
        self.language = language
        self._settings = settings
        self._pending = pending
        self._on_done = on_done
        self._battery = battery or on_battery
        self._plan_path = plan_path
        self._launcher = launcher
        self._enabled = enabled
        self._lock = threading.Lock()
        self._timer = None
        self._armed = 0             # which arming the timer is: a timer already firing as it was cancelled is stale
        self._last_change = 0.0     # time.monotonic() of the last `changed`
        self._settle = SETTLE_S     # the quiet time as the timer last read it (settings, battery)
        self._run = None            # the background run this keeper asked for (withdrawn by the next burst)
        self._previous = None       # the plan the run in flight will replace (shadow mode)
        self._closed = False
        self._last_plan = None      # the plan the last Generate wrote (shadow mode for a run the keeper didn't ask for)
        self._handed = None         # the run signature of the plan last handed to `on_done` (S19: never twice)
        self.reasons = []           # why the journey moved since the last request (the window's log; tests)
        self.asked = 0              # background runs asked for
        controller.on_end(self._ended)

    # --- the window's calls -------------------------------------------------------------------------------------- #
    def changed(self, reason="move"):
        """The order, the pins or the level moved (or an arrival was placed): withdraw a background run in flight and
        start the quiet time again. Reads nothing (no settings, no battery, no journey check): the timer's thread does,
        and waits the rest of the quiet time they ask for. Withdrawing a run in flight asks it to stop exactly as the
        controller's `cancel` does (a cancel file written; ≤ 4 ms, safe on a window's thread)."""
        with self._lock:
            if self._closed:
                return
            self.reasons.append(reason)
            self._last_change = time.monotonic()
            run, self._run = self._run, None
            self._arm(min(self._settle, FIRST_LOOK_S))
        if run is not None and not run.done:
            self.controller.withdraw(run)

    def close(self):
        """The window closes, or its language changes: no timer left, nothing asked from here on, the keeper's own run
        withdrawn (a user's is never the keeper's), no listener left on the controller, `on_done` never called again."""
        with self._lock:
            self._closed = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            run, self._run = self._run, None
        self.controller.unsubscribe(self._ended)
        if run is not None and not run.done:
            self.controller.withdraw(run)

    # --- inside --------------------------------------------------------------------------------------------------- #
    def _arm(self, delay):
        """(Inside `self._lock`.) The timer, started again. A cancelled timer may already be firing: its `_fire` sees
        that it is no longer the armed one and does nothing."""
        if self._timer is not None:
            self._timer.cancel()
        self._armed += 1
        self._timer = threading.Timer(max(0.0, delay), self._fire, args=(self._armed,))
        self._timer.daemon = True
        self._timer.start()

    def _read_settings(self):
        if self._settings is not None:
            return self._settings()
        from app import settings_manager
        return settings_manager.load_settings(strict=True)   # unreadable now: no run on the defaults' analysis

    def _is_pending(self):
        if self._pending is not None:
            return self._pending()
        from app import analyzer, run_args
        return analyzer.journey_is_current(run_args.analyzer_args(self._read_settings(), self.language),
                                           self.language) is not True

    def _fire(self, armed):
        """The moves stopped (the timer's thread): one quiet Generate if the journey is pending — once the quiet time
        the settings and the battery ask for now has passed since the last move."""
        try:
            settle = settle_seconds(self._read_settings(), self._battery())
        except Exception as e:              # settings.json unreadable this moment: no run on guessed settings
            print(f"Journey: the settings can't be read now ({e}); the next move asks again")
            return
        with self._lock:
            if self._closed or armed != self._armed:
                return                      # closed, or a newer move armed another timer
            self._timer = None
            self._settle = settle
            left = self._last_change + settle - time.monotonic()
            if left > 0.005:
                self._arm(left)             # on the battery, or a longer quiet time set: wait the rest
                return
        if self._enabled is not None and not self._enabled():
            return                          # the background Generate is switched off (D29)
        try:
            pending = self._is_pending()
        except Exception as e:
            print(f"Journey: the check failed ({e}); generating to be sure")
            pending = True
        if not pending:
            with self._lock:
                if armed == self._armed:
                    self.reasons = []
            return
        try:
            self._ask(armed)
        except Exception as e:              # the timer's thread: said, never silent; the next move tries again
            print(f"Journey: the background Generate couldn't be asked for: {e}")

    def _ask(self, armed):
        settings = self._read_settings()
        with self._lock:
            previous = self._last_plan
        if previous is None:
            previous = _load_plan(self._path())
        with self._lock:
            if self._closed or armed != self._armed:
                return                      # closed, or a new move came while checking: its own timer asks
            self._previous = previous
            self.asked += 1
            self.reasons = []
        # Outside the lock: the controller tells its listeners from inside `request`.
        run = self.controller.request(self.language, settings=settings, quiet=True, settle=0, launcher=self._launcher)
        with self._lock:
            mine = run.quiet                # a user's request still settling keeps its place (`request`): not ours
            late = mine and (self._closed or armed != self._armed)
            if mine and not late:
                self._run = run
        if late:
            self.controller.withdraw(run)   # a move (or the window closing) came while it was being asked for

    def _path(self):
        if self._plan_path is not None:
            return self._plan_path
        from app import analyzer
        from app.path_utils import get_user_file
        return os.path.join(get_user_file("results"), analyzer.PLAN_FILE)

    def _ended(self, run, outcome):
        """A run ended (`GenerateController.on_end`: told by the run itself, so one that ends while another request
        waits is told too). One that finished — any Generate, the user's too — gets shadow mode and `on_done`, on a
        thread of its own, so the controller never waits on a plan file's read."""
        if outcome != "current":
            return
        with self._lock:
            if self._closed:
                return
            previous, self._previous = self._previous or self._last_plan, None
        threading.Thread(target=self._landed, args=(previous,), name="journey-landed", daemon=True).start()

    def _landed(self, previous):
        path = self._path()
        plan = _load_plan(path)
        if plan is None:
            print(f"Journey: a Generate finished but its plan file can't be read ({path})")
            return
        if plan.header.get("language") != self.language:
            return                          # another language's Generate: not this keeper's journey
        signature = plan.header.get("run_signature")
        with self._lock:
            self._last_plan = plan
            new = signature != self._handed
        try:
            difference = shadow(previous, plan, _lists(), stamp=True)
        except Exception as e:              # a list that can't be read (being written again, damaged): said
            difference = f"the comparison failed: {e}"
        if difference:
            _log_shadow(f"{self.language} · {difference}")
        with self._lock:
            if self._closed or not new:
                return                      # closed meanwhile, or the same plan as last time (S19)
            self._handed = signature
        if self._on_done is not None:
            try:
                self._on_done(path)
            except Exception as e:
                print(f"Journey: the window's re-baseline failed: {e}")


# --- shadow mode (E1.1 05 §3; the comparison as 2.x's replan_preview makes it) --------------------------------------- #
PRIORITY_COLUMNS = ("Word", "Reading", "Score", "Occurrences", "Count (High)", "Count (Low)", "Count (Goal)", "Orth",
                    "Forms", "Tier")
PROGRESSIVE_COLUMNS = ("Sequence", "Source File", "Word", "Reading", "Score", "Occurrences (Global)",
                       "Occurrences (File)", "Count (High)", "Count (Low)", "Count (Goal)", "Known Count",
                       "Total Count", "Baseline %", "Current %", "New %", "Orth", "Forms", "Tier")


def _load_plan(path):
    try:
        from app import plan_engine
        return plan_engine.load(path) if path and os.path.exists(path) else None
    except Exception:
        return None


def shadow(previous, plan, lists, stamp=False):
    """The first difference between the engine — built from `previous`, re-planned to `plan`'s order — and the lists a
    Generate wrote for that order (`lists`: {"priority": rows, "progressive": rows}), or "". Only when the two plans
    share the order-free signature (the same library and settings: a re-plan could have served it) and differ in the
    run's. `stamp`: the lists are `results/`'s now — compared only while the run stamp still names `plan`'s run (a
    Generate started since may be writing them: nothing compared, nothing logged)."""
    if previous is None or plan is None or previous is plan:
        return ""
    h0, h1 = previous.header, plan.header
    if h0.get("order_free_signature") != h1.get("order_free_signature") or \
            h0.get("run_signature") == h1.get("run_signature") or h0.get("language") != h1.get("language"):
        return ""
    try:
        from app import plan_engine
        if plan_engine.stands_aside(previous):
            return ""
        engine = plan_engine.Engine(previous, [entry[0] for entry in previous.files])
        result = engine.replan([(entry[0], entry[1]) for entry in plan.files])
        if stamp and not _stamped(h1.get("run_signature")):
            return ""
        return _differs(result, lists)
    except Exception as e:
        return f"the comparison failed: {e}"


def _stamped(run_signature):
    """Whether `results/`'s run stamp still names this run (`analyzer.read_run_stamp`)."""
    from app import analyzer
    from app.path_utils import get_user_file
    return analyzer.read_run_stamp(get_user_file("results")) == run_signature


def _lists():
    import csv
    from app.path_utils import get_user_file
    out = {}
    for name, key in (("priority_learning_list.csv", "priority"), ("progressive_learning_list.csv", "progressive")):
        try:
            with open(os.path.join(get_user_file("results"), name), encoding="utf-8-sig", newline="") as f:
                out[key] = list(csv.DictReader(f))
        except OSError:
            out[key] = []
    return out


def _same_value(want, got):
    if isinstance(got, bool) or isinstance(got, str) or got is None:
        return (want or "") == (got or "")
    if isinstance(got, int):
        try:
            return int(want) == got
        except (TypeError, ValueError):
            return False
    if isinstance(got, float):
        try:
            return abs(float(want) - got) <= 1e-9
        except (TypeError, ValueError):
            return False
    return (want or "") == (got or "")


def _differs(result, lists):
    """The first difference between the engine's columns and a Generate's lists (05 §1's plan columns), or ""."""
    for name, rows, columns in (("priority", result.priority, PRIORITY_COLUMNS),
                                ("progressive", result.progressive, PROGRESSIVE_COLUMNS)):
        want = lists.get(name) or []
        if len(want) != len(rows):
            return f"{name}: {len(rows)} rows, the Generate wrote {len(want)}"
        for i, (w, r) in enumerate(zip(want, rows)):
            for column in columns:
                if not _same_value(w.get(column), r.get(column)):
                    return (f"{name} row {i + 1} ({w.get('Word')}): {column} {r.get(column)!r}, "
                            f"the Generate wrote {w.get(column)!r}")
    return ""


def _log_shadow(line):
    """One line to `replan_shadow.log` in the local data folder's logs. Never raises."""
    try:
        from app.path_utils import get_local_data_path
        folder = os.path.join(get_local_data_path(), "logs")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, SHADOW_LOG), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + " · " + line + "\n")
    except Exception:
        pass
