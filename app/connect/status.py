"""Connect's status record (P2.5 row 2.5.2; P1.5 03-actors §4, 05-surface U1–U3; RUNBOOK-P2.5 *The status contract*):
what the window shows — Connect's line, *Needs you*, *Undo this batch*, the shelf — and what `surasura-cli status`
answers under `connect`.

- **Read-only** (W3): the ledger opened `mode=ro` and never made (no ledger → the empty record: *Up to date*), the
  library store `mode=ro` for the episodes' titles and places. The window reads it on a worker, never the Tk thread.
- **Only what changed** (S19, charter): `stamp()` is two `stat` calls and a look at Connect's lock; the window reads
  the record again only when it differs from the last one.
- **Keyed by language** (D31): every part of the record is one language's; the rows carry their language.
- **The window's two writes** (short, the ledger's own): `mark_seen` when *Needs you* is shown (the badge stops
  counting them; they stay listed), `dismiss` (the entry leaves the list until it happens again after its fix).

Light: the standard library, the ledger's names and the store's file name; nothing here starts Anki or Connect.
"""
import datetime
import json
import os
import pathlib
import sqlite3

from app.connect import ledger as book

SCHEMA = 1
LANGUAGES = ("ja", "zh")
# The step a working job is at, in plain words (U1's parenthesis)
STEP_WORDS = {"picking": "choosing words", "fit-check": "checking the timing", "mining": "Anki Miner",
              "filling": "filling fields", "ordering": "ordering"}
UNDO_SHOWN = 100                # *Undo this batch*: the newest batches listed (any batch can be undone by its job)
SHELF_WORDS = 20                # words named per shelf restore point
FINISHED_WITH_CARDS = ("done", "failed", "skipped")


def _today():
    return datetime.datetime.now().astimezone().date()


def _local_day(utc_text):
    try:
        at = datetime.datetime.strptime(utc_text[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return None
    return at.astimezone().date()


def _file_stat(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return [st.st_size, st.st_mtime_ns]


def running():
    """Is Connect running now? Two quick looks at its lock (a holder holds it all along)."""
    from app import locks
    from app.connect import kick
    return locks.in_use(kick.LOCK, looks=2, gap=0.0)


def stamp(path=None, languages=None):
    """What the record is read from, as it stands: the ledger's and its WAL's size and modified time, whether Connect
    runs, today's date (*cards made today*), each language's library file (the titles), and Anki Miner's release
    state, the setup record and the installer's version in the registry (P3.2-AMN: the update notice; a hand update
    moves the stamp, ~10 µs a look). The same stamp → the same record: the window reads and redraws nothing (S19)."""
    path = path or book.path()
    out = [_file_stat(path), _file_stat(path + "-wal"), running(), _today().isoformat()]
    for lang in languages or LANGUAGES:
        db = _store_path(lang)
        out += [_file_stat(db), _file_stat(db + "-wal")] if db else [None, None]
    return out + _release_stat()


def _release_stat():
    try:
        from app.connect import am_release, anki_miner, setup
        return [_file_stat(am_release.path()), _file_stat(setup.record_path()), anki_miner.installed_version()]
    except Exception:
        return [None, None, None]


def anki_miner_update():
    """P3.2-AMN: {"version", "url"} when a newer Anki Miner is out than the one installed, else None. No fetch (the
    check is Connect's, once a day); never raises."""
    try:
        from app.connect import am_release
        return am_release.notice(am_release.installed())
    except Exception:
        return None


def language_record(record, lang):
    """One language's record from `read`'s, with the Anki Miner notice the window and the row show."""
    return dict(record["languages"][lang], anki_miner_update=record.get("anki_miner_update"))


def _store_path(lang):
    try:
        from app import library_store
        from app.path_utils import get_data_path
        return library_store.library_db_path(lang, get_data_path(lang))
    except Exception:
        return None


def _empty(lang):
    return {"line": "Up to date", "state": "idle", "jobs": [], "needs": [], "unseen": 0, "undo": [],
            "shelf": {"on_shelf": 0, "runs": [], "swap_ins": 0}, "made_today": 0, "updating": False}


def read(languages=None, words=False, path=None):
    """The status record (RUNBOOK-P2.5): {"schema", "running", "stamp", "anki_miner_update", "languages": {lang:
    {...}}}. `words`: each job's not-made words too (N7, `status --words`). A ledger made by a newer Surasura → each
    language says so. `anki_miner_update` (P3.2-AMN): null, or {"version", "url"} when a newer Anki Miner is out."""
    path = path or book.path()
    languages = tuple(languages or LANGUAGES)
    out = {"schema": SCHEMA, "running": False, "stamp": stamp(path, languages),
           "anki_miner_update": anki_miner_update(), "languages": {}}
    out["running"] = out["stamp"][2]
    if out["stamp"][0] is None:
        out["languages"] = {lang: _empty(lang) for lang in languages}
        return out
    conn = sqlite3.connect(pathlib.Path(path).as_uri() + "?mode=ro", uri=True, timeout=2.0, isolation_level=None)
    try:
        conn.execute("PRAGMA query_only=1")
        conn.execute("BEGIN")               # one read: a job and its outcomes as one moment
        try:
            schema = int((conn.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone() or ["0"])[0])
        except (sqlite3.Error, ValueError, TypeError):
            schema = book.SCHEMA + 1
        for lang in languages:
            if schema > book.SCHEMA:
                rec = _empty(lang)
                rec.update(line="Connect's records are newer than this Surasura reads. Update Surasura.",
                           state="waiting")
                out["languages"][lang] = rec
                continue
            out["languages"][lang] = _language(conn, lang, out["running"], words)
        conn.execute("COMMIT")
    except sqlite3.Error:
        out["languages"] = {lang: dict(_empty(lang), line="Connect's status can't be read just now.",
                                       state="waiting") for lang in languages}
    finally:
        conn.close()
    return out


def _rows(conn, sql, params=()):
    cur = conn.execute(sql, params)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def _has(conn, table, column=None):
    if column is None:
        return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone() \
            is not None
    return column in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _language(conn, lang, is_running, words):
    rec = _empty(lang)
    marks = ",".join("?" * len(book.OPEN))
    open_jobs = _rows(conn, f"SELECT * FROM jobs WHERE language = ? AND state IN ({marks}) ORDER BY id",
                      (lang,) + book.OPEN)
    fin = ",".join("?" * len(FINISHED_WITH_CARDS))
    undoable = _rows(conn, f"SELECT j.id, j.item_id, j.kind, j.updated_at, COUNT(o.note_id) AS made FROM jobs j JOIN "
                           f"outcomes o ON o.job_id = j.id AND o.outcome = 'made' AND o.note_id IS NOT NULL WHERE "
                           f"j.language = ? AND j.state IN ({fin}) GROUP BY j.id "
                           f"ORDER BY j.updated_at DESC, j.id DESC LIMIT ?", (lang,) + FINISHED_WITH_CARDS + (UNDO_SHOWN,))
    needs = _needs(conn, lang)
    items = _items(lang, {j["item_id"] for j in open_jobs} | {u["item_id"] for u in undoable}
                   | {n["item_id"] for n in needs if n["item_id"] is not None})

    for job in open_jobs:
        counts = {}
        for outcome, n in conn.execute("SELECT outcome, COUNT(*) FROM outcomes WHERE job_id = ? GROUP BY outcome",
                                       (job["id"],)):
            counts[outcome] = n
        entry = {"job": job["id"], "item": job["item_id"], "title": items.get(job["item_id"], {}).get("title"),
                 "kind": job.get("kind") or "mine", "state": job["state"], "reason": job.get("reason"),
                 "resume": job.get("resume"),  # row 56: the step a waiting job goes on at (the feed's Stop rule)
                 "step": STEP_WORDS.get(job["state"]) or STEP_WORDS.get(job.get("resume") or ""),
                 "words": len(_picked_words(job.get("picked"))), "made": counts.pop("made", 0),
                 "not_made": counts, "progress": _progress(job) if job["state"] in book.IN_FLIGHT else _naming(job),
                 # laptop round 9 #56: *Stop* pressed, the job not stopped yet (the window shows *Stopping…*): from
                 # the press until the runner has stopped it (it keeps the press through the tidy-up), only while
                 # Connect runs, and never past the stop point (naming the clips)
                 "stopping": bool(is_running and job["state"] in book.IN_FLIGHT
                                  and book.stoppable(job["state"], job.get("resume"), job.get("progress"))
                                  and conn.execute("SELECT 1 FROM meta WHERE key = ?",
                                                   (f"{book.STOP}{int(job['id'])}",)).fetchone() is not None)}
        if words:
            entry["not_made_words"] = _rows(conn, "SELECT word, reading, outcome FROM outcomes WHERE job_id = ? AND "
                                                  "outcome != 'made' ORDER BY rowid", (job["id"],))
        rec["jobs"].append(entry)
    _turns(rec["jobs"], is_running)

    rec["needs"] = [{"id": n["id"], "kind": n["kind"], "say": n["say"], "item": n["item_id"],
                     "title": items.get(n["item_id"], {}).get("title") if n["item_id"] is not None else None,
                     "at": n["at"], "seen_at": n.get("seen_at")} for n in reversed(needs)]
    rec["unseen"] = sum(1 for n in needs if not n.get("seen_at"))
    rec["undo"] = [{"job": u["id"], "item": u["item_id"], "title": items.get(u["item_id"], {}).get("title"),
                    "kind": u["kind"] or "mine", "made": u["made"], "at": u["updated_at"],
                    "not_made": _not_made(conn, u["id"])} for u in undoable]
    if words:                               # N7: each finished batch's not-made words too (IK P2.5 #9)
        for entry in rec["undo"]:
            entry["not_made_words"] = _rows(conn, "SELECT word, reading, outcome FROM outcomes WHERE job_id = ? AND "
                                                  "outcome != 'made' ORDER BY rowid", (entry["job"],))
    rec["made_today"] = _made_today(conn, lang)
    rec["shelf"] = _shelf(conn, lang)
    # F9 (P4.1 row 4.1.7): Connect's own Generate under way — only while Connect runs (a mark a crash left says nothing)
    rec["updating"] = bool(is_running and (conn.execute("SELECT value FROM meta WHERE key = ?",
                                                         (f"generating:{lang}",)).fetchone() or [None])[0])
    rec["line"], rec["state"] = _line(conn, lang, rec, open_jobs, items, is_running, {n["say"] for n in needs})
    return rec


def _turns(entries, is_running):
    """Laptop round 9 #56: while Connect works on one job, every other open job with no reason of its own waits its
    turn — `reason` runner.TURN and `behind` the item in flight, in the record only (never the ledger's)."""
    working = next((e for e in entries if e["state"] in book.IN_FLIGHT), None)
    if not is_running or working is None:
        return
    from app.connect import runner
    for entry in entries:
        if entry is not working and entry["state"] not in book.IN_FLIGHT and not entry["reason"]:
            entry.update(reason=runner.TURN, behind=working["item"])


# An episode's way through Connect as one percent (laptop round 5 #23, Sonic 2026-10-22 M-2 A: "one number that moves
# through the whole episode", the step on hover), from each step's measured share of its time (work/LF-mining
# timing.md, after the run's look-ups are kept: Anki Miner's run about half, naming its clips about a third)
STEP_AT = {"picking": (0, "Choosing words"), "fit-check": (4, "Checking the timing"),
           "filling": (94, "Filling fields"), "ordering": (97, "Ordering your cards")}
MINE_FROM, MINE_TO = 8, 60                  # Anki Miner's own run (its percent, `anki_miner.percent`), mapped here
NAMING = (62, "Naming the clips")
STAGE_WORDS = {1: "Reading the subtitles", 2: "Finding the words", 3: "Cutting clips", 4: "Looking up definitions",
               5: "Adding cards"}           # Anki Miner's stages (its progress file)


def _naming(job):
    """A waiting job's progress for the feed's Stop rule (row 56, round 2): `{"step": "naming"}` while its clips'
    naming waits (Anki busy: past the stop point), else None."""
    return {"step": "naming"} if job["state"] == "waiting" and book.naming(job.get("progress")) else None


def _progress(job):
    """Where an episode Connect is working on stands (laptop round 5 #23) -> {"percent", "doing"} (+ Anki Miner's
    "stage", "stages", "done", "total" while it runs): the job's step, and inside mining the run's own progress
    (saved by `runner._Progress`) or the clips' naming after it."""
    from app.connect import anki_miner
    if job["state"] != "mining":
        percent, doing = STEP_AT.get(job["state"], (0, "Choosing words"))
        return {"percent": percent, "doing": doing}
    try:
        got = json.loads(job.get("progress") or "null")
    except (TypeError, ValueError):
        got = None
    if book.naming(got):
        return {"percent": NAMING[0], "doing": NAMING[1], "step": "naming"}    # row 56: past the stop point
    keys = ("stage", "stages", "done", "total")
    if not (isinstance(got, dict) and all(isinstance(got.get(k), int) and not isinstance(got.get(k), bool)
                                          and got[k] >= 0 for k in keys)) or not got["stage"]:
        return {"percent": MINE_FROM, "doing": "Starting Anki Miner"}
    out = {k: got[k] for k in keys}
    out["percent"] = MINE_FROM + (MINE_TO - MINE_FROM) * anki_miner.percent(out) // 100
    doing = STAGE_WORDS.get(out["stage"], "Starting Anki Miner")
    out["doing"] = f"{doing} ({out['done']} of {out['total']})" if out["total"] else doing
    return out


def _not_made(conn, job_id):
    """{outcome: n} of a job's words with no card (N7: each not-made word with its reason)."""
    return {o: n for o, n in conn.execute("SELECT outcome, COUNT(*) FROM outcomes WHERE job_id = ? AND outcome != "
                                          "'made' GROUP BY outcome", (job_id,))}


def _picked_words(text):
    try:
        return (json.loads(text) or {}).get("words") or [] if text else []
    except (ValueError, AttributeError):
        return []


def _needs(conn, lang):
    """The open needs *Needs you* lists (not fixed, not dismissed), oldest first; a SCHEMA 3 ledger (Connect hasn't
    run since this Surasura came) has only its unseen ones, none seen yet."""
    if _has(conn, "needs", "fixed_at"):
        return _rows(conn, "SELECT * FROM needs WHERE language = ? AND fixed_at IS NULL AND dismissed_at IS NULL "
                           "ORDER BY id", (lang,))
    if not _has(conn, "needs"):
        return []
    return [dict(r, seen_at=None) for r in _rows(conn, "SELECT * FROM needs WHERE language = ? AND seen = 0 "
                                                       "ORDER BY id", (lang,))]


def _made_today(conn, lang):
    """Cards Connect made today (local time): its made outcomes whose batch ended today."""
    rows = conn.execute("SELECT b.ended_at, COUNT(*) FROM outcomes o JOIN jobs j ON j.id = o.job_id JOIN batches b ON "
                        "b.job_id = o.job_id AND b.attempt = o.attempt WHERE j.language = ? AND o.outcome = 'made' "
                        "AND j.state != 'undone' AND b.ended_at IS NOT NULL GROUP BY b.ended_at", (lang,)).fetchall()
    today = _today()
    return sum(n for at, n in rows if _local_day(at) == today)


def _shelf(conn, lang):
    """The shelf's restore points (newest first) with their words, how many cards are on it now and how many the
    swap-in brought back today."""
    if not _has(conn, "shelf"):
        return {"on_shelf": 0, "runs": [], "swap_ins": 0}
    runs = []
    for run, cards, why, at, back in conn.execute(
            "SELECT run, COUNT(*), MIN(why), MIN(shelved_at), SUM(back_at IS NOT NULL) FROM shelf WHERE language = ? "
            "GROUP BY run ORDER BY MIN(shelved_at) DESC", (lang,)):
        words = [r[0] for r in conn.execute("SELECT DISTINCT word FROM shelf WHERE run = ? AND word IS NOT NULL "
                                            "ORDER BY word LIMIT ?", (run, SHELF_WORDS))]
        runs.append({"run": run, "cards": cards, "back": back or 0, "why": why, "at": at, "words": words})
    on = conn.execute("SELECT COUNT(DISTINCT card_id) FROM shelf WHERE language = ? AND back_at IS NULL",
                      (lang,)).fetchone()[0]
    swap_ins = 0                            # cards Surasura itself brought back today (the swap-in, ✅ P2.5-2)
    if _has(conn, "shelf", "back_by"):
        today = _today()
        swap_ins = sum(1 for (at,) in conn.execute("SELECT back_at FROM shelf WHERE language = ? AND back_by = "
                                                   "'surasura'", (lang,)) if _local_day(at) == today)
    return {"on_shelf": on, "runs": runs, "swap_ins": swap_ins}


NEEDS_YOU_LINE = "Waiting for you: see Needs you."
UPDATING_LINE = "Connect is updating your list"     # F9: its own Generate (before mining, or after it)


def _line(conn, lang, rec, open_jobs, items, is_running, need_says=()):
    """U1's line and its state (working · waiting · idle). A job waiting on something *Needs you* lists says so in
    its own words there; the line points at it instead of repeating them (the contract: never Needs you's words).
    While Connect runs its own Generate (F9, `rec["updating"]`) and no job is mid-step: *Connect is updating your
    list*."""
    working = [j for j in open_jobs if j["state"] in book.IN_FLIGHT]
    if working and is_running:
        job = working[0]
        started = (conn.execute("SELECT value FROM meta WHERE key = ?", (f"run:{lang}",)).fetchone() or [None])[0]
        finished = 0
        if started:
            fin = ",".join("?" * len(book.FINISHED))
            finished = conn.execute(f"SELECT COUNT(*) FROM jobs WHERE language = ? AND state IN ({fin}) AND "
                                    f"updated_at >= ?", (lang,) + book.FINISHED + (started,)).fetchone()[0]
        total = finished + len(open_jobs)
        title = items.get(job["item_id"], {}).get("title") or "an episode"
        return f"Making cards {finished + 1} of {total} — {title} ({STEP_WORDS[job['state']]})", "working"
    if rec.get("updating"):                 # F9: a mining job's line wins; then Connect's own Generate
        return UPDATING_LINE, "working"
    if open_jobs:
        first = sorted(open_jobs, key=lambda j: (items.get(j["item_id"], {}).get("place", (9, 0.0)), j["id"]))[0]
        if first.get("reason"):
            return (NEEDS_YOU_LINE if first["reason"] in need_says else first["reason"]), "waiting"
        n = len(open_jobs)
        noun = "episode waits" if n == 1 else "episodes wait"
        return f"{n} {noun} for their cards: Connect makes them at its next start.", "waiting"
    if rec["made_today"]:
        return f"Up to date · {rec['made_today']} cards made today", "idle"
    return "Up to date", "idle"


def _items(lang, ids):
    """{item id: {"title", "place"}} from the library store, read-only (`mode=ro`): the title as Connect names an
    episode (the entry's title, else the file's name); the place NOW first, in order. {} when it can't be read."""
    ids = sorted(i for i in ids if i is not None)
    if not ids:
        return {}
    try:
        from app import library_store
        from app.path_utils import get_data_path
        db = library_store.library_db_path(lang, get_data_path(lang))
        if not os.path.exists(db):
            return {}
        conn = sqlite3.connect(pathlib.Path(db).as_uri() + "?mode=ro", uri=True, timeout=1.0, isolation_level=None)
    except Exception:
        return {}
    out = {}
    try:
        conn.execute("PRAGMA query_only=1")
        for at in range(0, len(ids), 500):
            part = ids[at:at + 500]
            for item_id, rel_path, entry, tier, ord_ in conn.execute(
                    f"SELECT id, rel_path, entry, tier, ord FROM items WHERE id IN ({','.join('?' * len(part))})",
                    part):
                try:
                    title = (json.loads(entry) or {}).get("title")
                except (ValueError, AttributeError):
                    title = None
                out[item_id] = {"title": title or os.path.basename(rel_path or "") or None,
                                "place": (0 if tier == "now" else 1, ord_)}
    except sqlite3.Error:
        return out
    finally:
        conn.close()
    return out


# --------------------------------------------------------------------------- #
# The window's two writes (*Needs you*)
# --------------------------------------------------------------------------- #
def mark_seen(ids, path=None):
    """*Needs you* was shown: `ids` stop counting in the badge, still listed -> how many changed. No ledger → 0 (the
    window never makes one)."""
    path = path or book.path()
    if not ids or not os.path.exists(path):
        return 0
    with book.Ledger(path) as ledger:
        return ledger.mark_seen(ids)


def dismiss(need_id, path=None):
    """*Dismiss*: the entry leaves the list -> True when it did."""
    path = path or book.path()
    if not os.path.exists(path):
        return False
    with book.Ledger(path) as ledger:
        return ledger.dismiss(need_id)


# --------------------------------------------------------------------------- #
# Logs (03 §4: *Open logs folder*, *Save logs to a file…*)
# --------------------------------------------------------------------------- #
LOG_DAYS = 7
NEVER_SAVED = ("settings-export.json",)     # Anki Miner's settings may hold a key (CLAUDE.md §6): never in the zip


def logs_folder():
    from app.cli import contract
    return contract.log_folder()


def save_logs(dest, now=None):
    """One zip at `dest`: Surasura's logs folder (the command line's, Generate's) and Anki Miner's result files of
    the last 7 days from Connect's run folders — never a run's `settings-export.json` -> the names written."""
    import time
    import zipfile
    now = now or time.time()
    names = []
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        folder = logs_folder()
        target = os.path.normcase(os.path.abspath(dest))
        for root, _dirs, files in os.walk(folder):
            for name in sorted(files):
                full = os.path.join(root, name)
                try:
                    if os.path.normcase(os.path.abspath(full)) == target or \
                            now - os.path.getmtime(full) > LOG_DAYS * 86400:
                        continue        # the zip itself, or older than 7 days
                except OSError:
                    continue
                arc = os.path.join("logs", os.path.relpath(full, folder))
                z.write(full, arc)
                names.append(arc)
        runs = os.path.join(os.path.dirname(book.path()), "runs")
        for root, _dirs, files in os.walk(runs):
            for name in sorted(files):
                if name in NEVER_SAVED or not (name.startswith("result") and name.endswith(".json")):
                    continue
                full = os.path.join(root, name)
                try:
                    if now - os.path.getmtime(full) > LOG_DAYS * 86400:
                        continue
                except OSError:
                    continue
                arc = os.path.join("anki-miner", os.path.relpath(full, runs))
                z.write(full, arc)
                names.append(arc)
    return names
