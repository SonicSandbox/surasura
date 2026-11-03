"""Send report's request half (SR-4a; `tracks/ship/work/send-report/SPEC.md` §3–5 and the packet's gate answers).
Qt-free: the window (`app/qt/report.py`) calls it on workers, and nothing here runs but on a press.

**The press** (`build`): the saved reports' zip, scrubbed and checked (`report.make_send_zip`), written to the outbox
(`<persistent>/report_outbox/`, beside `reports/`, never inside it: the list would read it as a broken report) with a
nonce of its own, so sending it again is the same report. Over 10 MB packed, `results` is left out first, then each log
keeps only its last 1 MB; still over: TooBig.

**Send** (`send`): `POST <receiver>/report` with the zip's bytes and these headers, nothing else (no telemetry id, no
cookie; it goes with telemetry off too — the press is its own consent): `X-Surasura-Version`, `X-Surasura-Language`,
`X-Surasura-Env` (`test` from source and from a dev build or an alpha: the receiver keeps it a day and posts nothing),
`X-Report-Nonce` (32 hex), `X-Report-Sha256` (the zip's), `X-Report-Sender` (this PC's sender code, below) and, only
when typed, `X-Discord-Name` (the name's UTF-8 in base64url, unpadded). The receiver: `telemetry.report_receiver(env)`
(a test report: the test Worker).
Its answer: 201 (or 200 for a nonce it knows) with `{"id": "K3Q7PM"}` → sent: the reports in the zip leave the list
(`report._clear`, only those unchanged since) and the zip moves to `<persistent>/report_sent/<id>.zip`, kept 90 days.
Anything else keeps the outbox zip for *Send now* — never sent again by itself (Q4).

**On this PC** (`report_send.json`, written atomically): the day's count (5 a day, refused before any request), the
Discord name when one was typed, and the sender code: 8 random letters made once (never the telemetry id, nothing
read from the PC), sent with each report so Sonic can tell one sender's reports apart; *New code* makes another.
"""
import base64
import datetime
import hashlib
import json
import os
import re
import secrets
import threading
import urllib.parse

from app import __version__, path_utils, report, telemetry

OUTBOX_DIR = "report_outbox"
SENT_DIR = "report_sent"
STATE_FILE = "report_send.json"
OUTBOX_ZIP = "report.zip"
OUTBOX_META = "outbox.json"
BUILDING = "building.zip"
MAX_ZIP = 10 * 1024 * 1024
LOG_TAIL = 1024 * 1024
PER_DAY = 5
KEEP_DAYS = 90
NAME_MAX = 32
TIMEOUT = (10, 120)                 # connect, read (s)
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
SENDER_LEN = 8
_ID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{6}$")
_SENDER = re.compile(r"^[0-9A-HJKMNP-TV-Z]{8}$")
_NONCE = re.compile(r"^[0-9a-f]{32}$")
RESULTS_TOO_BIG = "to keep the report under 10 MB"

# What a send came to (the window's words for each: SPEC §3)
SENT, LIMIT, OFFLINE, BUSY, TOO_BIG, PAUSED, REFUSED = ("sent", "limit", "offline", "busy", "too big", "paused",
                                                         "refused")
_BUSY = threading.Lock()            # one build, send or discard at a time


class TooBig(Exception):
    """Over 10 MB packed even without results and with each log's last 1 MB only."""


class Outbox:
    """The zip waiting to be sent: `path`, `nonce`, `sha256`, `size`, `created` (ISO), `language`, `zipped`
    ({rid: report.json's sha256}), `removed`, `left_out`, `entries` ([(name, size)])."""

    def __init__(self, path, meta):
        self.path = path
        self.nonce = meta["nonce"]
        self.sha256 = meta["sha256"]
        self.size = int(meta["size"])
        self.created = str(meta.get("created") or "")
        self.language = meta.get("language") or "ja"
        self.zipped = dict(meta.get("zipped") or {})
        self.removed = list(meta.get("removed") or [])
        self.left_out = list(meta.get("left_out") or [])
        self.entries = [tuple(e) for e in meta.get("entries") or []]

    def describe(self):
        """Every file that goes and its size (the scrubbed names, as zipped), then what's left out and why."""
        lines = [f"{len(self.entries) + 1} files, {report._mb(self.size)} packed", ""]
        lines += [f"{name}  ({report._kb(size)})" for name, size in self.entries]
        lines.append("MANIFEST.txt  (this list, with each file's sha256)")
        return "\n".join(lines + ["", "Left out:"] + [f"  {x}" for x in self.left_out])


class Result:
    """`outcome` (SENT · LIMIT · OFFLINE · BUSY · TOO_BIG · PAUSED · REFUSED), `id` (the report's #ID once sent),
    `status` (the receiver's HTTP status, when it answered)."""

    def __init__(self, outcome, rid=None, status=None):
        self.outcome, self.id, self.status = outcome, rid, status

    def __repr__(self):
        return f"Result({self.outcome!r}, {self.id!r}, {self.status!r})"


def _folder(name):
    path = os.path.join(path_utils.get_persistent_user_data_path(), name)
    os.makedirs(path, exist_ok=True)
    return path


def _today(now=None):
    return (now or datetime.datetime.now().astimezone()).date().isoformat()


# --- this PC's record -------------------------------------------------------------------------------------------- #
def _state_path():
    return os.path.join(path_utils.get_persistent_user_data_path(), STATE_FILE)


def _state():
    try:
        with open(_state_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(data):
    report._atomic_write(_state_path(), report._json_bytes(data))


def sender_code():
    """This PC's sender code (made once, at random, and kept)."""
    data = _state()
    code = data.get("sender")
    if isinstance(code, str) and _SENDER.match(code):
        return code
    return _make_code()                 # (unlocked: `send` asks for it under _BUSY)


def new_code():
    """*New code*: a fresh sender code (later reports no longer group with the earlier ones). -> it. Under _BUSY:
    `report_send.json` also holds the day's count, which a send's end writes (`_sent`) — never one lost to the other."""
    with _BUSY:
        return _make_code()


def _make_code():
    data = _state()
    data["sender"] = "".join(secrets.choice(CROCKFORD) for _ in range(SENDER_LEN))
    _save_state(data)
    return data["sender"]


def remembered_name():
    """The Discord name typed last time, or ""."""
    name = _state().get("name")
    return name if isinstance(name, str) else ""


def _clean_name(name):
    name = " ".join(str(name or "").split())
    if len(name) > NAME_MAX:
        raise ValueError(f"a Discord name is at most {NAME_MAX} characters")
    return name


def remember_name(name):
    """Keep the typed name for next time (an empty one forgets it)."""
    name = _clean_name(name)
    data = _state()
    if name:
        data["name"] = name
    else:
        data.pop("name", None)
    _save_state(data)


def sent_today(now=None):
    data = _state()
    return int(data.get("sent") or 0) if data.get("day") == _today(now) else 0


# --- the press: the outbox zip ----------------------------------------------------------------------------------- #
def _outbox_paths():
    folder = _folder(OUTBOX_DIR)
    return folder, os.path.join(folder, OUTBOX_ZIP), os.path.join(folder, OUTBOX_META)


def waiting():
    """The zip waiting to be sent (a send that didn't go), or None. Reads only."""
    folder = os.path.join(path_utils.persistent_root(), OUTBOX_DIR)
    path, meta_path = os.path.join(folder, OUTBOX_ZIP), os.path.join(folder, OUTBOX_META)
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        ob = Outbox(path, meta)
        if not _NONCE.match(ob.nonce) or os.path.getsize(path) != ob.size:
            return None
        return ob
    except (OSError, ValueError, KeyError, TypeError):
        return None


def build(language, include_results=True, library=None, root=None, extra=None, now=None, step=None):
    """The press: the saved reports' zip, scrubbed and checked, as the outbox's (a zip waiting before it is replaced:
    its reports are still on the list, so they are in this one too). Raises ValueError (no reports), report.Unsafe
    (the guard's hit: no zip), TooBig. `step(done, total)`: each file as it is gathered (`report._write`; a try
    again smaller counts again). -> the Outbox."""
    with _BUSY:
        folder, path, meta_path = _outbox_paths()
        building = os.path.join(folder, BUILDING)
        tries = [dict(include_results=include_results)]
        if include_results:
            tries.append(dict(include_results=False, results_why=RESULTS_TOO_BIG))
        tries.append(dict(include_results=False, tail=LOG_TAIL,
                          results_why=RESULTS_TOO_BIG if include_results else None))
        try:
            for opts in tries:
                made = report.make_send_zip(building, language, library=library, root=root, extra=extra, step=step,
                                            **opts)
                size = os.path.getsize(building)
                if size <= MAX_ZIP:
                    break
            else:
                raise TooBig(f"{size // (1024 * 1024)} MB packed")
            with open(building, "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()
        except BaseException:
            try:
                os.remove(building)
            except FileNotFoundError:
                pass
            raise
        was = waiting()                                              # the same reports again: the same nonce, so a
        same = was is not None and was.zipped == made.zipped and was.removed == made.removed   # sent one keeps its #ID
        meta = {"nonce": was.nonce if same else secrets.token_hex(16), "sha256": digest, "size": size, "language": language,
                "created": (now or datetime.datetime.now().astimezone()).isoformat(timespec="seconds"),
                "zipped": made.zipped, "removed": made.removed, "left_out": made.left_out, "entries": made.entries}
        try:
            os.remove(meta_path)                                     # (the zip and its record are replaced together)
        except FileNotFoundError:
            pass
        os.replace(building, path)
        report._atomic_write(meta_path, report._json_bytes(meta))
        return Outbox(path, meta)


def discard(expect=None):
    """*Don't send*: the waiting zip deleted (its reports stay on the list). `expect`: the sha256 of the zip the caller
    showed — another one waiting instead (an older one kept, another window's newer one) is left alone; checked under
    _BUSY, so no build lands between the check and the delete. -> True when one was deleted."""
    with _BUSY:
        if expect is not None and getattr(waiting(), "sha256", None) != expect:
            return False
        folder = os.path.join(path_utils.persistent_root(), OUTBOX_DIR)
        gone = False
        for name in (OUTBOX_META, OUTBOX_ZIP):
            try:
                os.remove(os.path.join(folder, name))
                gone = True
            except FileNotFoundError:
                pass
        return gone


# --- send ---------------------------------------------------------------------------------------------------------- #
def env():
    """`production` only for a release build (frozen, its .env production); else `test`."""
    return "production" if path_utils.is_frozen() and telemetry.TELEMETRY_ENV == "production" else "test"


def headers(ob, name="", sender=None):
    """Exactly what goes with the zip (SPEC §4 + the sender code): never the telemetry id, never a cookie."""
    out = {"Content-Type": "application/zip", "User-Agent": "Surasura",
           "X-Surasura-Version": __version__, "X-Surasura-Language": ob.language, "X-Surasura-Env": env(),
           "X-Report-Nonce": ob.nonce, "X-Report-Sha256": ob.sha256, "X-Report-Sender": sender or sender_code()}
    name = _clean_name(name)
    if name:
        out["X-Discord-Name"] = base64.urlsafe_b64encode(name.encode("utf-8")).decode("ascii").rstrip("=")
    return out


def _endpoint(receiver):
    """`<receiver's origin>/report`: a kept address with a path (the heartbeat's /hb) or a query names the same
    Worker."""
    parts = urllib.parse.urlsplit(receiver)
    return f"{parts.scheme}://{parts.netloc}/report"


def _outcome(status):
    if status == 413:
        return TOO_BIG
    if status == 429:
        return BUSY
    if status == 503:
        return PAUSED
    if status >= 500:
        return OFFLINE
    return REFUSED


def send(name="", url=None, root=None, now=None, nonce=None):
    """*Send* (the What goes page's) or *Send now*: the waiting zip to the receiver, once. `name`: the Discord name in
    the field as pressed (remembered; empty forgets it); `nonce`: the Outbox the page showed (another one waiting
    instead is never sent). The 6th send of a day is refused before any request. Raises ValueError when nothing (or
    another zip) is waiting. -> a Result."""
    import requests
    with _BUSY:
        ob = waiting()
        if ob is None or (nonce is not None and ob.nonce != nonce):
            raise ValueError("no report is waiting to be sent" if ob is None else "another report is waiting now")
        name = _clean_name(name)
        remember_name(name)
        if sent_today(now) >= PER_DAY:
            return Result(LIMIT)
        with open(ob.path, "rb") as f:
            body = f.read()
        if hashlib.sha256(body).hexdigest() != ob.sha256:
            raise ValueError("the waiting zip changed since it was made")
        try:
            got = requests.post(_endpoint(url or telemetry.report_receiver(env())), data=body,
                                headers=headers(ob, name), timeout=TIMEOUT, allow_redirects=False)
        except requests.RequestException:
            return Result(OFFLINE)
        if got.status_code not in (200, 201):
            return Result(_outcome(got.status_code), status=got.status_code)
        try:
            rid = got.json().get("id")
        except (ValueError, AttributeError):
            rid = None
        if not isinstance(rid, str) or not _ID.match(rid):
            return Result(REFUSED, status=got.status_code)
        _sent(ob, rid, root, now)
        return Result(SENT, rid, got.status_code)


def _sent(ob, rid, root, now):
    """The receiver has it: counted, its reports off the list, the zip kept as `report_sent/<id>.zip`."""
    data = _state()
    day = _today(now)
    data["sent"] = (int(data.get("sent") or 0) if data.get("day") == day else 0) + 1
    data["day"] = day
    _save_state(data)
    report._clear(root or report.folder(), ob.zipped, ob.removed)
    kept = os.path.join(_folder(SENT_DIR), f"{rid}.zip")
    os.replace(ob.path, kept)
    stamp = (now or datetime.datetime.now().astimezone()).timestamp()
    os.utime(kept, (stamp, stamp))
    try:
        os.remove(os.path.join(os.path.dirname(ob.path), OUTBOX_META))
    except FileNotFoundError:
        pass


def sent_reports(now=None):
    """*Sent reports*: [(id, when sent, path)], newest first; a copy past its 90 days (the receiver's) deleted."""
    folder = os.path.join(path_utils.persistent_root(), SENT_DIR)
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    now = now or datetime.datetime.now().astimezone()
    out = []
    for name in names:
        rid, ext = os.path.splitext(name)
        path = os.path.join(folder, name)
        if ext != ".zip" or not _ID.match(rid) or not os.path.isfile(path):
            continue
        when = datetime.datetime.fromtimestamp(os.path.getmtime(path)).astimezone()
        if now - when > datetime.timedelta(days=KEEP_DAYS):
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        out.append((rid, when, path))
    out.sort(key=lambda t: t[1], reverse=True)
    return out
