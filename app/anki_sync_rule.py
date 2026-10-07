"""When Surasura asks Anki to sync with AnkiWeb — the sync rule (E1.1 04 §3, S1–S4; Sonic's Q4-4 and G1.5-7; one rule
with Connect, P1.5's N11). Only while the fast re-plan's preview is on: off, nothing here runs and no sync is asked.

  S1 · a session's first write — before Surasura's first Anki write of a session, one sync, so reviews made on another
       device arrive first: a position written over a card studied on the phone would otherwise win the next sync
       and the review would be lost. A session starts at the first write when there is no record yet, Anki's open
       profile changed, a Surasura program found Anki closed since, or no Surasura write for `SESSION_GAP_S`.
  S2 · Anki's close — Anki's own sync on close carries the order up; Surasura sends nothing (it can't see Anki close).
  S3 · a re-order that matters — a write that changed tomorrow's cards gets one sync `anki_sync_delay_min` minutes
       after the last such write (each restarts the wait: a burst of moves gives one sync). Lower writes never sync.
       A window that closes with one pending runs it at once; if Anki closed first, nothing is sent (S2 carried it).
  S4 · the setting — `anki_sync_delay_min`: minutes (default 1, 0 = right away) or "off" (S1 and S2 only).

Always: a sync holds the Anki-write lock (`anki_connect.writer`) like a write, and every decision is taken again
inside it, so two programs never each sync; never while the user reviews (tried again later); a profile with no
AnkiWeb login is skipped quietly (and said in the indicator); a full-sync demand is Anki's own and never waited on.

One small state file per Windows user, beside the `anki-writer` lock (`locks.folder`): the session (profile, when it
started, the last write), Anki last seen closed, the last write that changed tomorrow's cards, the last sync and what
it answered. Written atomically; a lost or unreadable file only starts a new session (one extra sync).

Standard library only, no Tk; every call that talks to Anki runs on a worker.
"""

import json
import os
import threading
import time

from app import anki_connect

STATE_NAME = "anki-sync.json"
SESSION_GAP_S = 3600            # an hour with no Surasura write: the next write starts a new session (S1)
S1_RETRY_S = 300                # a session's sync that failed is tried again at most this often
REVIEW_RETRY_S = 30             # a pending sync that met a review looks again after this
SETTING = "anki_sync_delay_min"
DEFAULT_DELAY_MIN = 1
VERB = "the Anki sync"


def delay_s(settings):
    """S4: the seconds S3 waits after the last write that changed tomorrow's cards, or None for "off"."""
    value = (settings or {}).get(SETTING, DEFAULT_DELAY_MIN)
    if isinstance(value, str):
        if value.strip().lower() == "off":
            return None
        try:
            value = float(value)
        except ValueError:
            value = DEFAULT_DELAY_MIN
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value < 0:
        value = DEFAULT_DELAY_MIN
    return float(min(value, 24 * 60)) * 60.0


def _path():
    from app import locks
    return os.path.join(locks.folder(anki_connect.WRITER_LOCK), STATE_NAME)


def read_state():
    """The state as written, or {} (none yet, or unreadable). Never raises."""
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            state = json.load(f)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(state):
    """Atomically (temp + replace). A failure only costs a later extra sync; never raises."""
    path = _path()
    temp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"     # two threads of one program never share one
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(temp, path)
    except OSError:
        try:
            os.remove(temp)
        except OSError:
            pass


def _update(**values):
    state = read_state()
    state.update(values)
    _write_state(state)
    return state


def closed_seen(now=None):
    """A Surasura program found Anki closed: the next write starts a new session (S1)."""
    state = read_state()
    if state.get("session_at") and state.get("closed_at", 0) <= state.get("session_at", 0):
        _update(closed_at=time.time() if now is None else now)


def _new_session(state, profile, now):
    return (not state.get("session_at") or state.get("profile") != profile
            or state.get("closed_at", 0) > state.get("session_at", 0)
            or now - float(state.get("last_write") or state.get("session_at") or 0) > SESSION_GAP_S)


def _profile(url):
    try:
        name = anki_connect.invoke("getActiveProfile", url, timeout=5)
    except anki_connect.AnkiError:
        return None
    return name if isinstance(name, str) else None


def before_write(url, wait=None, cancel=None, on_wait=None, locked=False):
    """S1, just before a write's first request: one sync when this write starts a session -> what the sync answered
    ("synced", "not-signed-in", "full-sync", "failed: …"), or None when no sync was due (or Anki can't be asked: the
    write finds that out itself). `locked`: the caller holds the Anki-write lock (Junban's run, its writes planned
    and about to go: a run that writes nothing never syncs); else the sync takes it (`wait` / `cancel` / `on_wait`).
    A review in progress: no sync now, the session not started — the next write asks again. A sync that failed
    (AnkiWeb unreachable, a timeout) starts no session either: the next write tries again, at most every
    S1_RETRY_S, so a write is never held up by a sync that keeps failing. Never raises."""
    try:
        profile = _profile(url)
        if profile is None:
            return None
        if not _new_session(read_state(), profile, time.time()):
            return None
        if locked:
            return _session_sync(url, profile)
        from app import locks
        try:
            held = anki_connect.writer(VERB, wait=wait, cancel=cancel, on_wait=on_wait)
        except locks.Busy:
            return None
        with held:
            return _session_sync(url, profile)
    except Exception as e:                          # a sync never takes the write down with it
        return f"failed: {e}"


def _session_sync(url, profile):
    """S1's sync, holding the Anki-write lock: every decision taken again inside it."""
    state = read_state()
    now = time.time()
    if not _new_session(state, profile, now):
        return None                                 # another program started this session while we waited
    if now - float(state.get("s1_failed_at") or 0) < S1_RETRY_S:
        return None                                 # it failed a moment ago: not again yet
    if anki_connect.reviewing(url):
        return None
    answer = anki_connect.sync(url)
    now = time.time()
    if answer.startswith("failed"):
        state.update(s1_failed_at=now, sync="failed", sync_error=answer)
        _write_state(state)
        return answer
    state.update(profile=profile, session_at=now, last_write=now, sync=answer, sync_error="", s1_failed_at=0)
    if answer == "synced":
        state.update(synced_at=now, front_pending=False)     # it carried every write before it
    _write_state(state)
    return answer


def drop_pending():
    """The preview switched off: a pending S3 sync is let go (nothing will run it; Anki's own sync on close carries
    the order). Never raises."""
    if read_state().get("front_pending"):
        _update(front_pending=False)


def wrote(front_changed, settings=None, now=None):
    """After a write (whoever wrote): the session's last write, and — when it changed tomorrow's cards — S3's clock.
    Returns when the S3 sync is due (wall time), or None (no S3 pending, or "off")."""
    now = time.time() if now is None else now
    values = {"last_write": now}
    if front_changed:
        values.update(front_at=now, front_pending=True)
    state = _update(**values)
    return due_at(settings, state)


def due_at(settings, state=None):
    """When the pending S3 sync is due (wall time), or None: none pending, already synced since, or "off"."""
    state = read_state() if state is None else state
    wait = delay_s(settings)
    if wait is None or state.get("front_pending") is not True:
        return None
    return float(state.get("front_at") or 0) + wait


def sync_if_due(url, settings, force=False, wait=None, cancel=None):
    """S3: the pending sync, when its time has come (or at once with `force`: a window closing). Returns
    ("synced" | "not-signed-in" | "full-sync" | "failed: …" | "anki-closed" | None, the next time to look or None).
    Never raises."""
    try:
        due = due_at(settings)
        if due is None:
            return None, None
        now = time.time()
        if not force and now < due:
            return None, due
        if not anki_connect.probe(url, timeout=3).get("ok"):
            # Anki closed after the write: its own sync on close (S2) carried the order. Nothing to send.
            _update(settled_at=now, front_pending=False)
            closed_seen(now)
            return "anki-closed", None
        if anki_connect.reviewing(url):
            return None, now + REVIEW_RETRY_S
        from app import locks
        try:
            held = anki_connect.writer(VERB, wait=wait, cancel=cancel)
        except locks.Busy:
            return None, now + REVIEW_RETRY_S
        with held:
            due = due_at(settings)
            if due is None:
                return None, None                       # another program synced it while we waited
            if not force and time.time() < due:
                return None, due                        # a newer write restarted the wait
            answer = anki_connect.sync(url)
            now = time.time()
            state = read_state()
            state.update(settled_at=now, front_pending=False, sync=answer.split(":")[0],
                         sync_error=answer if answer.startswith("failed") else "")
            if answer == "synced":
                state["synced_at"] = now
            _write_state(state)
            return answer, None
    except Exception as e:
        return f"failed: {e}", None


def status(settings, now=None):
    """The AnkiWeb indicator's words (E1.1 04 §3: Surasura's own requests only): "AnkiWeb: synced 18:42",
    "AnkiWeb: syncing in 45 s", "AnkiWeb: not signed in", "AnkiWeb: sync failed" — or "" before any."""
    state = read_state()
    now = time.time() if now is None else now
    due = due_at(settings, state)
    if due is not None:
        return f"AnkiWeb: syncing in {max(0, int(round(due - now)))} s"
    answer = state.get("sync")
    if answer == "not-signed-in":
        return "AnkiWeb: not signed in"
    if answer == "full-sync":
        return "AnkiWeb: needs a full sync in Anki"
    if answer == "failed":
        return "AnkiWeb: sync failed"
    if state.get("synced_at"):
        return "AnkiWeb: synced " + time.strftime("%H:%M", time.localtime(float(state["synced_at"])))
    return ""
