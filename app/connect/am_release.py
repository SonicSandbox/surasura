"""Anki Miner's update notice (P3.2-AMN; RUNBOOK-AMN): under Connect, Anki Miner runs headless (`--api`), so its own
GitHub update notice — shown when its window opens — is never seen. Connect asks GitHub instead.

- **The call** (CLAUDE.md §1, a core touchpoint; Sonic's yes, 2026-10-12): Anki Miner's latest release
  (`api.github.com/repos/0xzerolight/anki_miner/releases/latest`, which skips pre-releases), **at most once a day,
  only while Connect's preview is on**, in Connect's own process on a daemon thread (`start`, from `runner.run`).
  Surasura's own HTTP helper (`update_checker._http_json`); no new HTTP code. urllib's TIMEOUT_S bounds each socket
  wait, not the whole look (a name lookup isn't covered); what is bounded is Connect's exit (`finish`): it waits what
  is left of TIMEOUT_S + 1 s from the check's start, then leaves the daemon thread behind. Every failure is swallowed
  and logged to Connect's log, never a *Needs you*. Nothing is downloaded or installed.
- **What is kept:** `am_release.json` beside `setup.json` in Connect's local data — `{checked_at, latest, url}`. The
  attempt time is saved **before** GitHub is asked (`_claim`, on the run's own thread in `start`), the last good
  `latest` and `url` kept: a check cut off (a raise at exit, an update stop, a hang past the exit's wait, the process
  killed) is still the day's one try, and a Connect started meanwhile (`_kick`) finds none due. An attempt that can't
  be saved asks nothing. Written atomically; the answer written again only when it changed.
- **What shows:** `notice(installed)` → `{version, url}` when the kept `latest` is newer than the Anki Miner installed
  (`installed()`: what Connect already knows — the installer's version, the setup record's `version` answer; never a
  new probe; only a version with digits counts), else None. No fetch: an Anki Miner updated by hand clears it at once
  (the registry's version is in `status.stamp`, so the row reads again at its next look). The status record carries it
  (`status.read`'s `anki_miner_update`); the dashboard's row and the Connect window show *Anki Miner 3.8 is out*,
  a link to the releases page (never a download).

Light: the standard library; `update_checker` (urllib) is imported only when it's used. `SURASURA_NO_UPDATE_CHECK`
(the gate Surasura's own update check honours, set for every test) stops the real fetch.
"""
import datetime
import json
import logging
import os
import re
import threading
import time

REPO = "0xzerolight/anki_miner"
STATE = "am_release.json"
RELEASES = f"https://github.com/{REPO}/releases"
EVERY_S = 24 * 3600             # at most once a day
TIMEOUT_S = 5                   # urllib's per-socket-wait timeout; Connect's exit waits this (+1 s) at most
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
    return _load() or {}


def _load():
    """The kept state; {} when there is none or it is torn (not an object); None when the file is there but can't be
    opened just now (another program holding it), which `_claim` reads as not due. Never raises."""
    try:
        with open(path(), "r", encoding="utf-8") as f:
            state = json.load(f)
        return state if isinstance(state, dict) else {}
    except FileNotFoundError:
        return {}
    except ValueError:
        return {}
    except Exception:
        return None


def _write(state):
    """Atomically (temp + replace) -> written or not. Never raises (its path is named inside the guard too)."""
    temp = None
    try:
        target = path()
        temp = f"{target}.{os.getpid()}.{threading.get_ident()}.tmp"
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        os.replace(temp, target)
        return True
    except Exception as e:
        log.warning("Anki Miner's release check: its state wasn't written (%s)", e)
        if temp:
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


def _allowed(settings, fetch):
    """May a check read or write anything: Connect's preview on, and the real fetch not gated (NO_CHECK_ENV)."""
    return bool((settings or {}).get("connect_enabled")) and not (fetch is None and os.environ.get(NO_CHECK_ENV))


def _claim(now):
    """-> (the state as kept, the attempt claimed or None). Due → the attempt time saved now, before GitHub is asked,
    with the last good `latest` and `url`: a check cut off still counts, a Connect started meanwhile finds none due.
    None when not due, or when the attempt couldn't be saved (asking anyway would ask every run)."""
    state = _load()
    if state is None:                   # there but held just now: not "never checked" (the final review)
        return {}, None
    if not due(state, now):
        return state, None
    claimed = {"checked_at": _iso(now), "latest": state.get("latest"), "url": state.get("url")}
    return state, (claimed if _write(claimed) else None)


def _ask(claimed, fetch=None):
    """GitHub asked once for a claimed attempt -> the state kept: a new release written over the claim, a failure
    leaving it as claimed (the attempt time, the last good one). Never raises."""
    latest, url = claimed["latest"], claimed["url"]
    try:
        reply = (fetch or _fetch)()
        from app import update_checker
        version = update_checker.version_string(str(reply.get("tag_name") or "")) if isinstance(reply, dict) else ""
        if version:
            latest, url = version, _page(reply.get("html_url"))
        else:
            log.info("Anki Miner's release check: no release version in GitHub's answer")
    except Exception as e:          # offline, a timeout, a 404, a torn answer: the last good one stays
        log.info("Anki Miner's release check failed: %s: %s", type(e).__name__, e)
    new = dict(claimed, latest=latest, url=url)
    if new != claimed:
        _write(new)
    return new


def check(settings, now=None, fetch=None):
    """One look when it's due -> the state kept (None: preview off or the gate set, nothing read or written). Only
    while Connect's preview is on; `fetch` a test's own (the real one is never called under NO_CHECK_ENV). The
    attempt is saved before GitHub is asked (`_claim`). Never raises."""
    try:
        if not _allowed(settings, fetch):
            return None
        state, claimed = _claim(time.time() if now is None else now)
        return state if claimed is None else _ask(claimed, fetch)
    except Exception:
        log.exception("Anki Miner's release check failed")
        return None


def start(settings):
    """At a Connect run's start: the attempt claimed here, on the run's thread (a small read; a write once a day), so
    a Connect `_kick` starts before this one's exit finds none due; then GitHub asked on a daemon thread, never
    waited for by mining -> the thread, or None (preview off, the gate set, not due, the attempt not saved: no
    thread)."""
    global _thread, _started
    try:
        if not _allowed(settings, None):
            return None
        claimed = _claim(time.time())[1]
        if claimed is None:
            return None
        _thread, _started = threading.Thread(target=_ask, args=(claimed,), daemon=True,
                                             name="anki-miner-release"), time.monotonic()
        _thread.start()
        return _thread
    except Exception:
        log.exception("Anki Miner's release check wasn't started")
        return None


def running():
    """-> True while a check started by this process is still running."""
    thread = _thread
    return thread is not None and thread.is_alive()


def finish():
    """At Connect's exit, outside its lock: a check still running is given what is left of TIMEOUT_S + 1 s from its
    start — this wait is what is bounded, not the fetch (urllib's timeout is per socket wait) — so a short run doesn't
    end it mid-fetch; past it the daemon thread is left (its attempt already saved). -> True when none is left
    running."""
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


def known(version):
    """A version counts as known only when it holds a digit ("unknown" is no version)."""
    return isinstance(version, str) and bool(re.search(r"\d", version))


def installed():
    """The Anki Miner installed, as Connect already knows it (never a new probe): the newer of its installer's version
    and the setup record's `version` answer — only a version with digits counts — or None."""
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
    seen = [str(v).strip() for v in seen if v is not None and known(str(v))]
    return max(seen, key=_key) if seen else None


def notice(installed_version, state=None):
    """{"version", "url"} when the kept latest is newer than `installed_version`, else None (nothing kept, Anki Miner
    not known to be installed, up to date). No fetch. Never raises."""
    try:
        state = read_state() if state is None else state
        latest = state.get("latest")
        if not known(latest) or not known(installed_version):
            return None
        if _key(latest) <= _key(installed_version):
            return None
        return {"version": latest, "url": _page(state.get("url"))}
    except Exception:
        return None
