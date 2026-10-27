"""Anki Miner in the setup wizard (W3.5 part 3; P1.5 04-onboarding §2–3): the page's look, and the install route.

- `look(settings, language)` (a worker: it asks Anki and runs Anki Miner's `--api` reads) — Connect's own setup checks
  (`connect.setup.checks(settings, language, keep=False)`: the wizard's look never writes the setup record) as the
  page shows them -> `{"state", "version", "dots", "fix"}`:
  - `state`: `missing` (not installed, or not where the setting says) · `too-old` (older than 3.5.0: no `--api`) ·
    `needs-setup` (installed, its profile or its own setup not finished, or it couldn't be asked) · `ready` (no
    Anki Miner check needs you, and its own setup is finished — or waits only for Anki to open);
  - `version`: what Anki Miner answered, else its installer's (`anki_miner.installed_version`), else None;
  - `dots`: four `(name, state, tip)` — *Anki* (open, its profile) · *AnkiWeb* · *Anki Miner* (installed, its version) ·
    *Its setup* (its profile, its own `check`); a dot is `ok`, `warn` (only you can fix it) or `off` (closed, waiting
    by itself, not checked yet), the worst of its checks; the tip names the state in words and Connect's sentence
    (status is never colour alone);
  - `fix`: Connect's own `{"say", "do", "update"}` for the first of those checks only you can fix (one that stops
    Connect first), else None; `update` when updating Anki Miner is the fix it leads with. The known-words sync is page 2's, never this page's fix.
  Never raises: a look that fails is every dot off and the state from whether Anki Miner is found.

- `install(on_progress, cancel, on_end, confirm=None) -> str` — **G1.3-2 option b**, the in-Surasura install.
  Blocking: the caller runs it on a worker, never the window's thread. **The network call** (CLAUDE.md §1: an
  existing core touchpoint's kind, Sonic's yes 2026-10-15 as relayed by the W3.5 lead; the §1 line is the lead's):
  Anki Miner's official installer from its own GitHub releases, checked by GitHub's sha256, only when the learner
  presses Install and says yes. `DOWNLOAD_ENABLED` (True as shipped) is the one switch: False opens Anki Miner's
  approved release's page in the browser (`am_release.approved_page`; 2.x opened `setup.RELEASES`) -> `"opened-releases"`, `_fetch` never called.
  On: Windows only · never while Anki Miner runs or a Connect run holds its lock (`"busy"`, nothing opened) ·
  `confirm()` once, **before any byte**: no `confirm` handed in -> the releases page, nothing fetched; False ->
  `"declined"`, nothing fetched or opened · the release of `0xzerolight/anki_miner` Surasura has approved
  (`am_release.APPROVED`, alpha 4 M5: the version its drill passed at; never GitHub's latest — his installer refuses
  a downgrade, so a newer one you installed stays) · exactly one
  `*-Windows-x86_64-Setup.exe` asset, its size under `SIZE_CAP`, GitHub's `sha256:` digest present and the one
  approved with it (`am_release.APPROVED_SHA256`) · streamed into a staging folder under local data
  (`path_utils.get_local_data_path()`), only from GitHub's hosts (`HOSTS`, https; a redirect elsewhere is refused),
  with `on_progress(done, total)`, `cancel` looked at every chunk and the cap counted as it comes · the digest and
  size must match · his installer opened as he made it (`updater.launch_installer`: visible, his licence page, his
  folder choice; never silent, never rehosted) and waited for · `"installer-closed"`, staging cleaned. Off Windows, a
  missing asset or digest, a mismatch, a cap hit, a foreign host, a cancel, Windows blocking the file, or any other
  failure -> the releases page (`"opened-releases"`), staging cleaned: never a half file left. `on_end(result)` is
  told once, at every end (the page checks again).
- `install_as_job(registry, on_progress, cancel, on_end, confirm=None)` — `install`, listed in the window's job
  registry as an `anki-miner-install` job (W AD-5 / IK-11) from the learner's yes until the route ends: the bottom bar
  shows it and its progress, its Cancel (and the quit's) sets `cancel`. Nothing is listed before the yes, nor when the
  route ends without one.

Every byte from the network goes through ONE function, `_fetch`. Standard library only; no Tk, no Qt.
"""
import fnmatch
import hashlib
import json
import os
import shutil
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

from app.connect import am_release
from app.connect.setup import RELEASES  # noqa: F401  (2.x's page; the fallback opens the approved release's, alpha 4 M5)

DOWNLOAD_ENABLED = True         # the download (Sonic's yes, 2026-10-15); False = the releases page, as 2.x

STAR_URL = f"https://github.com/{am_release.REPO}"      # = connect.settings_panel.STAR_URL (a Tk module: not imported)
ASSET_PATTERN = "*-Windows-x86_64-Setup.exe"
# GitHub's own hosts: the API, the release's download link and the asset stores it redirects to. Nothing else.
HOSTS = frozenset({"api.github.com", "github.com", "objects.githubusercontent.com",
                   "release-assets.githubusercontent.com", "github-releases.githubusercontent.com"})
SIZE_CAP = 400 * 1024 * 1024    # 3.6.0's installer is 179.6 MB: about twice that, and no more
JSON_CAP = 1024 * 1024          # GitHub's release answer: 1 MB, far above a release's, and no more
# The installer's link: Anki Miner's own release downloads (owner and repository compared as GitHub does, by case)
DOWNLOAD_PATH = f"/{am_release.REPO}/releases/download/".lower()
TIMEOUT_S = 30                  # urllib's per-socket wait
CHUNK = 1 << 16
STAGING = "anki-miner-install"  # under local data; emptied before, after and on every failure
MINER_EXE = "AnkiMiner.exe"

OPENED_RELEASES, INSTALLER_CLOSED, BUSY, DECLINED = "opened-releases", "installer-closed", "busy", "declined"
CANCELLED = "cancelled"         # the learner's own Cancel: nothing more opens (no releases page: IK-13, W AD-6)

# What the page shows (the wizard's strings module may word them again; the states are these)
DOT_NAMES = ("Anki", "AnkiWeb", "Anki Miner", "Its setup")
_DOT_CHECKS = (("anki", "anki_profile"), ("ankiweb",), ("anki_miner", "anki_miner_version"),
               ("anki_miner_profile", "anki_miner_setup"))
STATE_WORDS = {"ok": "Ready", "warn": "Needs you", "off": "Not now"}
NOT_CHECKED_TIP = "It couldn't be checked."
OK, WARN, OFF = "ok", "warn", "off"
_RANK = {OK: 0, OFF: 1, WARN: 2}
_MINER_CHECKS = ("anki_miner", "anki_miner_version", "anki_miner_profile", "anki_miner_setup")

open_url = None                 # the browser: webbrowser.open, looked up when used (a test hands in its own)
_ONE_INSTALL = threading.Lock()  # held for an install's whole route: one at a time, and the look never cleans under it


class _Refused(Exception):
    """The download route stops here: the releases page instead."""


# --------------------------------------------------------------------------- #
# The look
# --------------------------------------------------------------------------- #
def _dot_state(check_state):
    if check_state == "ok":
        return OK
    if check_state == "needs-you":
        return WARN
    return OFF                  # waiting (it waits by itself), not-checked, skipped


def _tip(name, state, say):
    return f"{name}: {STATE_WORDS[state]}. {say}" if say else f"{name}: {STATE_WORDS[state]}."


def _version(found):
    from app.connect import anki_miner
    app_version = (found or {}).get("app")
    if isinstance(app_version, str) and app_version.strip():
        return app_version.strip()
    try:
        return anki_miner.installed_version()
    except Exception:
        return None


def _off(settings):
    """A look that failed: every dot off, the state from whether Anki Miner is found at all."""
    try:
        from app.connect import anki_miner
        state = "missing" if anki_miner.find(settings) is None else "needs-setup"
    except Exception:
        state = "missing"
    return {"state": state, "version": None, "fix": None,
            "dots": [(name, OFF, _tip(name, OFF, NOT_CHECKED_TIP)) for name in DOT_NAMES]}


def look(settings, language):
    """The page's state, its four dots and its one fix (module docstring). Never raises. First, an installer left in
    staging by a quit while it was open (AD-8: its `_clean` never ran) is emptied — never while an install runs."""
    if _ONE_INSTALL.acquire(blocking=False):
        try:
            _clean()
        finally:
            _ONE_INSTALL.release()
    try:
        from app.connect import anki_miner, setup
        result = setup.checks(settings, language, keep=False)
        by_id = {c.get("id"): c for c in result.get("checks") or () if isinstance(c, dict)}
        dots = []
        for name, ids in zip(DOT_NAMES, _DOT_CHECKS):
            worst = None
            for id_ in ids:
                check = by_id.get(id_)
                if check is None:
                    continue
                if worst is None or _RANK[_dot_state(check.get("state"))] > _RANK[_dot_state(worst.get("state"))]:
                    worst = check
            state = _dot_state(worst.get("state")) if worst else OFF
            dots.append((name, state, _tip(name, state, worst.get("say") if worst else NOT_CHECKED_TIP)))
        version = _version(result.get("anki_miner"))
        miner = [by_id.get(i) or {} for i in _MINER_CHECKS]
        if miner[0].get("state") != "ok":
            state = "missing"
        elif anki_miner.too_old(version) or (miner[1].get("state") == "needs-you"
                                             and miner[1].get("do") == f"Update Anki Miner ({setup.RELEASES})"):
            state = "too-old"
        elif not any(c.get("state") == "needs-you" for c in miner) and miner[3].get("state") in ("ok", "waiting"):
            state = "ready"
        else:
            state = "needs-setup"
        mine = [by_id[i] for ids in _DOT_CHECKS for i in ids if i in by_id]
        yours = [c for c in mine if c.get("state") == "needs-you"]
        first = next((c for c in yours if c.get("blocks")), None) or (yours[0] if yours else None)
        fix = ({"say": first.get("say"), "do": first.get("do"), "update": bool(first.get("update"))}
               if first else None)
        return {"state": state, "version": version, "dots": dots, "fix": fix}
    except Exception:
        return _off(settings)


# --------------------------------------------------------------------------- #
# The install route (option b)
# --------------------------------------------------------------------------- #
def _github(url):
    try:
        parts = urllib.parse.urlsplit(str(url))
    except (TypeError, ValueError):
        return False
    return parts.scheme == "https" and (parts.hostname or "").lower() in HOSTS and not parts.username \
        and parts.port in (None, 443)


def _own_release(url):
    """Is `url` a download from Anki Miner's own releases (`https://github.com/0xzerolight/anki_miner/releases/
    download/…`)? A GitHub host alone is not enough (AD-7): another account's release, a fork, a dot segment out of
    the path are never fetched. Its redirects to GitHub's asset hosts stay `_GitHubOnly`'s."""
    if not _github(url):
        return False
    parts = urllib.parse.urlsplit(str(url))
    path = urllib.parse.unquote(parts.path)
    return (parts.hostname or "").lower() == "github.com" and path.lower().startswith(DOWNLOAD_PATH) \
        and "\\" not in path and not any(segment in (".", "..") for segment in path.split("/"))


class _GitHubOnly(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to another of GitHub's hosts."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _github(newurl):
            raise urllib.error.HTTPError(newurl, code, "a redirect away from GitHub's hosts", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch(url, as_json=False):
    """THE network function: every byte of this route comes through here, redirects followed only within GitHub's
    hosts. `as_json`: GitHub's release answer (the dict) — it names the installer and its sha256, so it is the trust
    anchor and comes the download's way too (AD-6): its final address checked, read up to `JSON_CAP`; else the open
    response (a context manager: `read(n)`, `geturl()`, `headers`)."""
    if not DOWNLOAD_ENABLED:
        raise _Refused("the download isn't enabled")
    if not _github(url):
        raise _Refused(f"not one of GitHub's hosts: {url}")
    from app import update_checker
    headers = {"User-Agent": update_checker._USER_AGENT}
    if as_json:
        headers["Accept"] = "application/vnd.github+json"
    opener = urllib.request.build_opener(_GitHubOnly())
    response = opener.open(urllib.request.Request(url, headers=headers), timeout=TIMEOUT_S)
    if not as_json:
        return response
    with response:
        if not _github(response.geturl()):
            raise _Refused(f"the release answer came from outside GitHub's hosts: {response.geturl()}")
        body = response.read(JSON_CAP + 1)
    if len(body) > JSON_CAP:
        raise _Refused("the release answer is larger than any release's")
    return json.loads(body.decode("utf-8"))


def staging_folder():
    from app import path_utils
    return os.path.join(path_utils.get_local_data_path(), STAGING)


def _clean():
    try:
        shutil.rmtree(staging_folder(), ignore_errors=True)
    except Exception:
        pass


def _stopped(cancel):
    if cancel is None:
        return False
    try:
        return bool(cancel.is_set() if hasattr(cancel, "is_set") else cancel())
    except Exception:
        return False


def _miner_running():
    """Is Anki Miner's program running now (its window, or a run of its own)? One look at the process list."""
    from app import updater
    return any(str(exe).lower() == MINER_EXE.lower() for _pid, _parent, exe in updater._snapshot())


def _busy():
    """Anki Miner running, or a Connect run holding its lock -> True. A look that can't be made counts as busy."""
    try:
        from app.connect import status
        return bool(status.running() or _miner_running())
    except Exception:
        return True


def _asset(release):
    """The release's one Windows installer -> (version, name, url, size, sha256), else _Refused."""
    if not isinstance(release, dict):
        raise _Refused("no release answer")
    found = [a for a in release.get("assets") or () if isinstance(a, dict)
             and fnmatch.fnmatchcase(str(a.get("name") or ""), ASSET_PATTERN)]
    if len(found) != 1:
        raise _Refused(f"{len(found)} Windows installers in the release")
    asset = found[0]
    name, url, size, digest = asset.get("name"), asset.get("browser_download_url"), asset.get("size"), \
        str(asset.get("digest") or "")
    if os.path.basename(name.replace("\\", "/")) != name or name in (".", ".."):
        raise _Refused(f"an installer name that isn't a plain file name: {name!r}")
    if not _own_release(url):
        raise _Refused(f"the installer isn't one of Anki Miner's own release downloads: {url}")
    if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= SIZE_CAP:
        raise _Refused(f"the installer's size is {size!r}")
    algorithm, _, hexdigest = digest.partition(":")
    hexdigest = hexdigest.lower()
    if algorithm.lower() != "sha256" or len(hexdigest) != 64 or any(c not in "0123456789abcdef" for c in hexdigest):
        raise _Refused("GitHub gives no sha256 for the installer")
    version = str(release.get("tag_name") or "").strip().lstrip("vV") or None
    return version, name, url, size, hexdigest


def _download(url, path, size, sha256, on_progress, cancel):
    """Stream the installer to `path`; _Refused on a foreign host, a cap hit, a cancel or a mismatch."""
    digest, done = hashlib.sha256(), 0
    with _fetch(url) as response:
        if not _github(response.geturl()):
            raise _Refused(f"the download came from outside GitHub's hosts: {response.geturl()}")
        try:
            total = int(response.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            total = 0
        if total > SIZE_CAP or (total and total != size):
            raise _Refused(f"the download is {total} bytes, not {size}")
        with open(path, "wb") as out:
            while True:
                if _stopped(cancel):
                    raise _Refused("cancelled")
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                done += len(chunk)
                if done > size or done > SIZE_CAP:
                    raise _Refused("the download is larger than the release says")
                out.write(chunk)
                digest.update(chunk)
                if on_progress:
                    try:
                        on_progress(done, size)
                    except Exception:
                        pass
    if done != size or digest.hexdigest() != sha256:
        raise _Refused("the installer's sha256 doesn't match GitHub's")


def _sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _launch(path):
    """His installer, opened as he made it (Surasura's own installer hand-off): the started process."""
    from app import updater
    return updater.launch_installer({"path": path, "args": []})


def _releases():
    try:
        (open_url or webbrowser.open)(am_release.approved_page())     # alpha 4 M5: the approved release's page
    except Exception:
        pass
    return OPENED_RELEASES


def release_api():
    """GitHub's answer for the approved release's tag (alpha 4 M5: never `releases/latest`)."""
    return f"https://api.github.com/repos/{am_release.REPO}/releases/tags/v{am_release.APPROVED}"


def _approved(asset):
    """The approved release's installer (alpha 4 M5): its version and its sha256 the ones Surasura approved, else
    _Refused (the releases page opens instead)."""
    version, _name, _url, _size, sha256 = asset
    if version != am_release.APPROVED or sha256 != am_release.APPROVED_SHA256.lower():
        raise _Refused(f"Anki Miner {version} isn't the approved {am_release.APPROVED}, or its installer changed")
    return asset


def _route(on_progress, cancel, confirm):
    if not DOWNLOAD_ENABLED or sys.platform != "win32":
        return _releases()
    if _busy():
        return BUSY
    if confirm is None:             # no one said yes: nothing is fetched
        return _releases()
    if not confirm():               # the one confirm, before any byte
        return DECLINED
    try:
        _version, name, url, size, sha256 = _approved(_asset(_fetch(release_api(), as_json=True)))
        _clean()
        folder = staging_folder()
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        _download(url, path, size, sha256, on_progress, cancel)
        if _busy():                 # Anki Miner or Connect started while it downloaded
            _clean()
            return BUSY
        if _sha256_of(path) != sha256:      # the file opened is the file checked (AD-9), not only the stream
            raise _Refused("the installer on disk changed after its check")
        process = _launch(path)
        process.wait()              # his installer's own window; its Finish page starts his setup wizard
        _clean()
        return INSTALLER_CLOSED
    except Exception:               # _Refused, the network, the disk, Windows blocking the file (WinError 225)
        _clean()
        if _stopped(cancel):        # the learner stopped it: the page says so, no browser opens behind the window
            return CANCELLED
        return _releases()


JOB_KIND = "anki-miner-install"     # its kind in the window's registry (`jobs.RESOURCES`)
JOB_LABEL = "Getting Anki Miner"   # the bottom bar's words while it downloads and its installer is open
JOB_FELL_BACK = "Anki Miner's download didn't finish: its page opened in your browser"


def install_as_job(registry, on_progress, cancel, on_end, confirm=None):
    """`install` as an `anki-miner-install` job in `registry` from the learner's yes until the route ends (the job's
    cancel sets `cancel`; the quit cancels it) -> `install`'s result. No registry, or no `confirm`: `install` alone."""
    if registry is None or confirm is None:
        return install(on_progress, cancel, on_end, confirm)
    job = []

    def asked():
        yes = confirm()
        if yes:
            job.append(registry.record(JOB_KIND, JOB_LABEL, cancel=lambda _job: cancel.set(), on_quit="cancel"))
        return yes

    def progress(done, total):
        on_progress(done, total)
        if job:
            job[0].progress(JOB_LABEL, done, total)
    result = BUSY
    try:
        result = install(progress, cancel, on_end, confirm=asked)
    finally:
        if job:
            fell_back = result == OPENED_RELEASES      # the download failed: its page opened in the browser
            job[0].finish(ok=not fell_back, message=JOB_FELL_BACK if fell_back else None,
                          cancelled=result == CANCELLED)
    return result


def install(on_progress, cancel, on_end, confirm=None):
    """The in-Surasura install route (module docstring) -> "opened-releases" · "installer-closed" · "busy" ·
    "declined" · "cancelled". Blocking: run it on a worker. `on_end(result)` is told once, at the end. Never raises. One at a time
    in the process (AD-9: the wizard closed mid-install, then *Set up again*): a second one is `"busy"`."""
    if not _ONE_INSTALL.acquire(blocking=False):
        result = BUSY
    else:
        try:
            result = _route(on_progress, cancel, confirm)
        except Exception:
            _clean()
            result = _releases()
        finally:
            _ONE_INSTALL.release()
    if on_end:
        try:
            on_end(result)
        except Exception:
            pass
    return result
