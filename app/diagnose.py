"""What Send report would show about this PC, short: for Piyo's `surasura_diagnose` (app/cli/mcp_server.py), so the
learner's AI can say why Surasura is doing something without a zip. Qt-free.

**One source.** Every part is read by the report's own collectors (`app/report.py`: the build, the logs it takes,
Connect's status record and job ledger, the Anki sync's record, settings with their secrets blanked), a log as the
scrub reads text (`scrub.decode`), and every string goes through the report's scrub (`app/scrub.py`: the learner's
Windows name, PC, home folder, Anki profiles, install keys and emails written as placeholders). The answer goes to the
learner's AI, not to Sonic, so a free line of text (a log line, an error) also loses what the learner watched or read —
its paths, quoted names and Japanese or Chinese (`report.content_free`), before the scrub. Then the scrub's matcher
reads each part again, as written and as the legacy encodings would garble it (`scrub._views`): a hit leaves that
part out, said so — the same matcher checking itself, never a second set of rules.

**Short.** Logs are never whole: only their newest lines that say something went wrong, waited or was refused, each
cut short. Connect's jobs are their states and the counts the report keeps; a failed part names its refused words (the
word alone, as the report does). `area` asks for one part only.

**Read-only.** Nothing is written, started or sent: no setting, no file, no Anki change. What it can't help: Connect's
status asks whether Connect runs by trying its lock for an instant (as Send report and `surasura-cli status` do), a
read of a database in WAL mode keeps SQLite's own -shm beside it, and the local data folder is made when missing (it is
there in every install: the server's own log is in it). The one call is the Anki part's look at AnkiConnect, on this
computer only (127.0.0.1), and only when that part is asked for by name. No drive is touched: a folder offline is never
waited for.
"""
import json
import os
import platform
import re
import sys

AREAS = ("app", "connect", "anki", "library", "hato")
LOG_LINES = 24                  # the newest log lines that matter, at most, over every log
LOG_LINES_PER_FILE = 8
LOG_READ = 256 * 1024           # each log's last bytes read
LINE_MAX = 220                  # a log line is cut here
JOBS_SHOWN = 8                  # Connect's open jobs and failed parts shown per language
# A log line that matters: something failed, waited, was refused or stopped
MATTERS = re.compile(r"error|exception|fail|refus|couldn.t|could not|can.t|cannot|timed? ?out|denied|not found|"
                     r"missing|warn|wait|busy|stopp|skipp|gave up|unreadable|damaged", re.IGNORECASE)
STAMP = re.compile(r"^\d{4}-\d\d-\d\d[ T][\d:.,]+\S*\s*(?:\[\d+\]\s*)?")    # a log line's time and process
NOISE = re.compile(r"^\s*(?:Traceback \(most recent call last\)|File \"|\^+\s*$)")
LEFT = "left out: it may name you"
RUN_STAMP = "run_signature.txt"  # the last Generate's stamp in results/ (analyzer.RUN_STAMP_FILE; not imported: pandas)


def diagnose(area=None, language=None):
    """-> {"surasura": the build, then one key per area asked for (all of them when `area` is None)}. Raises
    ValueError for an area that isn't one of AREAS."""
    from app import scrub
    if area is not None and area not in AREAS:
        raise ValueError(f"area is one of {', '.join(AREAS)}, or left out for all of them")
    ident = scrub.identity(fresh=True)
    settings = _settings()
    lang = language or settings.get("language") or "ja"
    out = {"surasura": _part(_build, ident)}
    for name in AREAS:
        if area in (None, name):
            out[name] = _part(lambda name=name: PARTS[name](lang, settings, area == name, ident), ident)
    return out


def _part(make, ident):
    """One part, read, scrubbed and checked; a part that can't be read says why, never stops the rest."""
    try:
        value = make()
    except Exception as e:                                       # one part's failure is said, never raised
        from app import report
        value = {"unreadable": report.content_free(ident.scrub(f"{type(e).__name__}: {e}"))}
    value = _scrubbed(_compact(value), ident)
    from app import scrub
    text = json.dumps(value, ensure_ascii=False)
    if any(ident.found(v) for v in scrub._views(text, None)):     # the scrub's matcher read again (its views too)
        return LEFT
    return value


def _scrubbed(obj, ident):
    if isinstance(obj, str):
        return ident.scrub(obj)
    if isinstance(obj, dict):
        return {ident.scrub(str(k)): _scrubbed(v, ident) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrubbed(v, ident) for v in obj]
    return obj


def _compact(obj):
    """Empty values and the report's "(left out)" dropped: what is there is all that's said."""
    from app import report
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            v = _compact(v)
            if v in (None, "", [], {}, report.BLANKED):
                continue
            out[k] = v
        return out
    if isinstance(obj, list):
        return [_compact(v) for v in obj]
    return obj


def _settings():
    """settings.json as read, its keys, tokens and passwords blanked (the report's rule), or {}."""
    from app import path_utils, report
    path = path_utils.get_settings_path()
    if not os.path.isfile(path) or report.why_not(path):
        return {}
    try:
        data = json.loads(path_utils.read_text(path))
    except (OSError, ValueError):
        return {"unreadable": True}
    return report.strip_secrets(data) if isinstance(data, dict) else {}


# --- the parts ------------------------------------------------------------------------------------------------------ #
def _build():
    from app import report
    b = report.build()
    return {"version": b.get("version"), "build": b.get("build_id"), "commit": b.get("commit"),
            "installed": bool(b.get("frozen")), "system": platform.platform(), "python": sys.version.split()[0]}


def _app(lang, settings, _asked, ident):
    from app import path_utils, report, send_report
    out = {"language": lang, "settings": "unreadable" if settings.get("unreadable") else None}
    saved = report.listed(os.path.join(path_utils.persistent_root(), report.REPORTS_DIR))     # (never made)
    waiting = send_report.waiting()
    out["reports"] = {"saved": len(saved), "sent_today": send_report.sent_today(),
                      "a_send_waiting": waiting is not None or None} if saved or waiting else None
    out["log"] = log_lines(language=lang, ident=ident)
    return out


def log_lines(limit=LOG_LINES, language=None, ident=None):
    """The newest lines that matter (`MATTERS`) in the logs the report takes (`status.log_files`, the last 7 days; never
    Anki Miner's run results), newest file first, read as the scrub reads text, what the learner watched or read taken
    out (`report.content_free`), each cut to LINE_MAX: ["<log> | <line>"]. An event of the command line's
    (`cli-events.jsonl`) is its time, verb, code and message."""
    from app import report, scrub
    from app.connect import status
    ident = ident or scrub.identity()
    files = [(full, name) for full, name in status.log_files() if name.replace("\\", "/").startswith("logs/")]
    files.sort(key=lambda f: _mtime(f[0]), reverse=True)
    out = []
    for full, name in files:
        if len(out) >= limit:
            break
        try:
            with open(full, "rb") as f:
                start = max(0, os.path.getsize(full) - LOG_READ)
                f.seek(start)
                raw = f.read()
        except OSError:
            continue
        if start:                                              # read from the middle: its first line is a part
            raw = raw[raw.find(b"\n") + 1:]
        text = scrub.decode(raw, language)
        if text is None:                                       # not text the scrub can read: never shown
            continue
        lines = text.splitlines()
        if name.endswith(".jsonl"):
            lines = [_event(ln) for ln in lines]
        lines = [report.content_free(ident.scrub(ln.strip())) for ln in lines         # (the identity first: a home
                 if ln and MATTERS.search(ln) and not NOISE.match(ln)]                 # ... folder's spaces)
        picked, last = [], None
        for line in reversed(lines):                         # the newest first, a line repeated said once
            said = STAMP.sub("", line)
            if said == last:
                continue
            last = said
            picked.append(line if len(line) <= LINE_MAX else line[:LINE_MAX - 1] + "…")
            if len(picked) >= min(LOG_LINES_PER_FILE, limit - len(out)):
                break
        short = os.path.basename(name)
        out += [f"{short} | {line}" for line in picked]
    return out


def _event(line):
    """A command-line event (JSON) as one line: its time, verb, code and message."""
    try:
        e = json.loads(line)
    except ValueError:
        return ""
    if not isinstance(e, dict):
        return ""
    return " ".join(str(x) for x in (e.get("time"), e.get("verb"), e.get("code"), e.get("message")) if x)


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0


def _connect(lang, settings, _asked, ident):
    from app import report
    record = report.connect_record()
    out = {"on": bool(settings.get("connect_enabled")), "running": record.get("running"),
           "anki_miner_update": (record.get("anki_miner_update") or {}).get("version")}
    rec = (record.get("languages") or {}).get(lang) or {}
    ledger = report.ledger_record() or {}
    refused = {r.get("job_id"): r for r in ledger.get("refused") or []}
    jobs = []
    for job in (rec.get("jobs") or [])[:JOBS_SHOWN]:
        jobs.append({k: job.get(k) for k in ("job", "kind", "state", "reason", "since", "step", "words", "made",
                                              "not_made", "stopping")})
    failed = []
    for part in (rec.get("failed") or [])[:JOBS_SHOWN]:
        row = {k: part.get(k) for k in ("job", "made", "words", "reason")}
        said = refused.get(part.get("job"))
        if said:
            row["refused_words"] = said.get("words")
            row["anki_miner_said"] = report.content_free(ident.scrub(said.get("said") or ""), quoted=False)
        failed.append(row)
    states = {}
    for job in ledger.get("jobs") or []:
        if job.get("language") in (None, lang):
            states[job.get("state")] = states.get(job.get("state"), 0) + 1
    out[lang] = {"state": rec.get("state"), "updating": rec.get("updating"), "made_today": rec.get("made_today"),
                 "open_jobs": jobs, "failed_parts": failed,
                 "needs_you": [{"kind": n.get("kind"), "at": n.get("at")} for n in rec.get("needs") or []],
                 "jobs_by_state": states}
    return out


def _anki(lang, settings, asked, _ident):
    from app import anki_sync, report
    state = report.anki_record(lang) or {}
    out = {"known_words": anki_sync.count_known(lang), "waiting_cards": anki_sync.count_backlog(lang),
           "last_sync": state.get("last_sync"), "last_added": state.get("last_added"),
           "decks": state.get("decks"), "fields": state.get("fields"),
           "settings": {k: v for k, v in settings.items() if k.startswith(("anki_", "junban_"))
                        and not isinstance(v, (dict, list))}}
    if asked:                                                    # the one look off the file: AnkiConnect, loopback only
        from app import anki_connect
        try:
            out["anki_open"] = bool(anki_connect.probe(anki_connect.address(settings), timeout=2).get("ok"))
        except Exception as e:
            out["anki_open"] = f"couldn't be asked ({type(e).__name__})"
    return out


def _library(lang, _settings_, _asked, _ident):
    import pathlib
    import sqlite3
    from app import library_store, path_utils
    data_dir = path_utils.get_data_path(lang)
    db = library_store.library_db_path(lang, data_dir)
    if not os.path.isfile(db):
        return {"store": "none yet"}
    if os.path.exists(library_store.damaged_marker(db)):
        return {"store": "damaged (Surasura repairs it at its next start)"}
    conn = sqlite3.connect(pathlib.Path(db).as_uri() + "?mode=ro", uri=True, timeout=1.0, isolation_level=None)
    try:
        conn.execute("PRAGMA query_only=1")
        tiers = {library_store.TIER_LABELS.get(t, t): n for t, n in
                 conn.execute("SELECT tier, COUNT(*) FROM items GROUP BY tier")}
        state = {a: n for a, n in conn.execute("SELECT availability, COUNT(*) FROM items "
                                               "WHERE availability != 'available' GROUP BY availability")}
        roots = conn.execute("SELECT path, kind FROM roots WHERE kind IN ('source', 'source-off')").fetchall()
        schema = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
    on = [p for p, k in roots if k == "source"]
    out = {"items": tiers, "not_available": state, "schema": schema,
           "folders": {"read": len(on), "stopped": len(roots) - len(on)}}
    stamp = os.path.join(path_utils.get_user_data_path(), "results", RUN_STAMP)
    if os.path.isfile(stamp):
        import datetime
        out["last_generate"] = datetime.datetime.fromtimestamp(_mtime(stamp)).astimezone().isoformat(
            timespec="minutes")
    return out


def _hato(_lang, settings, _asked, _ident):
    from app import tools_entry
    entry = tools_entry.read("hato")
    out = {"found": entry is not None, "subs_with_hato": settings.get("subs_with_hato")}
    if entry:
        out.update({k: entry.get(k) for k in ("version", "verbs", "updated")})
    return out


PARTS = {"app": _app, "connect": _connect, "anki": _anki, "library": _library, "hato": _hato}
