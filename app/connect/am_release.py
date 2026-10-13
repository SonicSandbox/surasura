"""Anki Miner's update notice (P3.2-AMN; RUNBOOK-AMN): under Connect, Anki Miner runs headless (`--api`), so its own
GitHub update notice — shown when its window opens — is never seen. Connect asks GitHub instead.

- **The call** (CLAUDE.md §1, a core touchpoint; Sonic's yes, 2026-10-12): Anki Miner's latest release
  (`api.github.com/repos/0xzerolight/anki_miner/releases/latest`, which skips pre-releases), **at most once a day,
  only while Connect's preview is on**, in Connect's own process on a daemon thread (`start`, from `runner.run`),
  bounded by TIMEOUT_S. Surasura's own HTTP helper (`update_checker._http_json`); no new HTTP code. Every failure is
  swallowed and logged to Connect's log, never a *Needs you*. Nothing is downloaded or installed.
- **What is kept:** `am_release.json` beside `setup.json` in Connect's local data — `{checked_at, latest, url}`. The
  attempt time is kept on a failure too (one try a day), the last good `latest` stays; written atomically, only when
  it changed.
- **What shows:** `notice(installed)` → `{version, url}` when the kept `latest` is newer than the Anki Miner installed
  (`installed()`: what Connect already knows — the installer's version, the setup record's `version` answer; never a
  new probe), else None. No fetch: an Anki Miner updated by hand clears it at once. The status record carries it
  (`status.read`'s `anki_miner_update`); the dashboard's row and the Connect window show *Anki Miner 3.8 is out*,
  a link to the releases page (never a download).

Light: the standard library; `update_checker` (urllib) is imported only when it's used. `SURASURA_NO_UPDATE_CHECK`
(the gate Surasura's own update check honours, set for every test) stops the real fetch.
"""
import datetime
import json
import logging
import os
import threading
import time

REPO = "0xzerolight/anki_miner"
STATE = "am_release.json"
RELEASES = f"https://github.com/{REPO}/releases"
EVERY_S = 24 * 3600             # at most once a day
TIMEOUT_S = 5                   # the fetch's bound (and how long Connect's exit waits for one still running)
NO_CHECK_ENV = "SURASURA_NO_UPDATE_CHECK"

log = logging.getLogger("surasura-cli")

_thread = None                  # the check this process started (`start`), and when
_started = 0.0


def path():
    from app.connect import ledger
    return os.path.join(ledger.folder(), STATE)


def _iso(at):
    return datetime.datetime.fromtimestamp(at, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seconds(text):
    try:
        return datetime.datetime.strptime(str(text)[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=datetime.timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def read_state():
    """The kept state, or {} (none yet, unreadable, not an object). Never raises."""
    try:
        with open(path(), "r", encoding="utf-8") as f:
            state = json.load(f)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(state):
    """Atomically (temp + replace) -> written or not. Never raises."""
    target = path()
    temp = f"{target}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        os.replace(temp, target)
        return True
    except OSError as e:
        log.warning("Anki Miner's release check: its state wasn't written (%s)", e)
        try:
            os.remove(temp)
        except OSError:
            pass
        return False


def due(state, now):
    """Is a check due: never checked, the last one 24 h ago or more, or one in the future (the clock went back)."""
    at = _seconds((state or {}).get("checked_at"))
    return at is None or now - at >= EVERY_S or at > now


def _fetch():
    """GitHub's latest-release answer (a dict), or None."""
    from app import update_checker
    return update_checker._http_json(update_checker._LATEST_RELEASE_API.format(repo=REPO), timeout=TIMEOUT_S)


def _page(url):
    """The release's page when GitHub names one of Anki Miner's, else its releases page: never a download."""
    return url if isinstance(url, str) and url.startswith(RELEASES + "/") and "/download/" not in url else RELEASES


def check(settings, now=None, fetch=None):
    """One look when it's due -> the state kept (None: preview off or the gate set, nothing read or written). Only
    while Connect's preview is on; `fetch` a test's own (the real one is never called under NO_CHECK_ENV). Never
    raises."""
    try:
        if not (settings or {}).get("connect_enabled"):
            return None
        if fetch is None and os.environ.get(NO_CHECK_ENV):
            return None
        now = time.time() if now is None else now
        state = read_state()
        if not due(state, now):
            return state
        latest, url = state.get("latest"), state.get("url")
        try:
            reply = (fetch or _fetch)()
            from app import update_checker
            version = update_checker.version_string(str(reply.get("tag_name") or "")) if isinstance(reply, dict) \
                else ""
            if version:
                latest, url = version, _page(reply.get("html_url"))
            else:
                log.info("Anki Miner's release check: no release version in GitHub's answer")
        except Exception as e:      # offline, a timeout, a 404, a torn answer: the last good one stays
            log.info("Anki Miner's release check failed: %s: %s", type(e).__name__, e)
        new = {"checked_at": _iso(now), "latest": latest, "url": url}
        if new != {k: state.get(k) for k in new}:
            _write(new)
        return new
    except Exception:
        log.exception("Anki Miner's release check failed")
        return None


def start(settings):
    """At a Connect run's start: the check on a daemon thread, never waited for by mining -> the thread, or None with
    Connect's preview off (no thread)."""
    global _thread, _started
    if not (settings or {}).get("connect_enabled"):
        return None
    _thread, _started = threading.Thread(target=check, args=(dict(settings),), daemon=True,
                                         name="anki-miner-release"), time.monotonic()
    _thread.start()
    return _thread


def finish():
    """At Connect's exit, outside its lock: a check still running is given what is left of its bound (TIMEOUT_S, and a
    second for its write), so a short run doesn't end it mid-fetch. -> True when none is left running."""
    thread = _thread
    if thread is None or not thread.is_alive():
        return True
    thread.join(max(0.0, _started + TIMEOUT_S + 1 - time.monotonic()))
    return not thread.is_alive()


def _key(version):
    """A version to compare: its numbers, trailing zeros dropped (3.8 is 3.8.0)."""
    from app import update_checker
    numbers = list(update_checker.parse_version(str(version)))
    while len(numbers) > 1 and numbers[-1] == 0:
        numbers.pop()
    return tuple(numbers)


def installed():
    """The Anki Miner installed, as Connect already knows it (never a new probe): the newer of its installer's version
    and the setup record's `version` answer, or None."""
    seen = []
    try:
        from app.connect import anki_miner
        seen.append(anki_miner.installed_version())
    except Exception:
        pass
    try:
        from app.connect import setup
        seen.append((setup.read_record().get("anki_miner") or {}).get("app"))
    except Exception:
        pass
    seen = [str(v) for v in seen if v]
    return max(seen, key=_key) if seen else None


def notice(installed_version, state=None):
    """{"version", "url"} when the kept latest is newer than `installed_version`, else None (nothing kept, Anki Miner
    not known to be installed, up to date). No fetch. Never raises."""
    try:
        state = read_state() if state is None else state
        latest = state.get("latest")
        if not latest or not installed_version or not isinstance(latest, str):
            return None
        if _key(latest) <= _key(installed_version):
            return None
        return {"version": latest, "url": _page(state.get("url"))}
    except Exception:
        return None
