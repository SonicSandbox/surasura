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
    runs, today's date (*cards made today*) and each language's library file (the titles). The same stamp → the
    same record: the window reads and redraws nothing (S19)."""
    path = path or book.path()
    out = [_file_stat(path), _file_stat(path + "-wal"), running(), _today().isoformat()]
    for lang in languages or LANGUAGES:
        db = _store_path(lang)
        out.append(_file_stat(db) if db else None)
    return out


def _store_path(lang):
    try:
        from app import library_store
        from app.path_utils import get_data_path
        return library_store.library_db_path(lang, get_data_path(lang))
    except Exception:
        return None


def _empty(lang):
    return {"line": "Up to date", "state": "idle", "jobs": [], "needs": [], "unseen": 0, "undo": [],
            "shelf": {"on_shelf": 0, "runs": []}, "made_today": 0}


def read(languages=None, words=False, path=None):
    """The status record (RUNBOOK-P2.5): {"schema", "running", "stamp", "languages": {lang: {...}}}. `words`: each job's
    not-made words too (N7, `status --words`). A ledger made by a newer Surasura → each language says so."""
    path = path or book.path()
    languages = tuple(languages or LANGUAGES)
    out = {"schema": SCHEMA, "running": False, "stamp": stamp(path, languages), "languages": {}}
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
                 "step": STEP_WORDS.get(job["state"]) or STEP_WORDS.get(job.get("resume") or ""),
                 "words": len(_picked_words(job.get("picked"))), "made": counts.pop("made", 0),
                 "not_made": counts}
        if words:
            entry["not_made_words"] = _rows(conn, "SELECT word, reading, outcome FROM outcomes WHERE job_id = ? AND "
                                                  "outcome != 'made' ORDER BY rowid", (job["id"],))
        rec["jobs"].append(entry)

    rec["needs"] = [{"id": n["id"], "kind": n["kind"], "say": n["say"], "item": n["item_id"],
                     "title": items.get(n["item_id"], {}).get("title") if n["item_id"] is not None else None,
                     "at": n["at"], "seen_at": n.get("seen_at")} for n in reversed(needs)]
    rec["unseen"] = sum(1 for n in needs if not n.get("seen_at"))
    rec["undo"] = [{"job": u["id"], "item": u["item_id"], "title": items.get(u["item_id"], {}).get("title"),
                    "kind": u["kind"] or "mine", "made": u["made"], "at": u["updated_at"],
                    "not_made": _not_made(conn, u["id"])} for u in undoable]
    rec["made_today"] = _made_today(conn, lang)
    rec["shelf"] = _shelf(conn, lang)
    rec["line"], rec["state"] = _line(conn, lang, rec, open_jobs, items, is_running)
    return rec


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
                        "AND b.ended_at IS NOT NULL GROUP BY b.ended_at", (lang,)).fetchall()
    today = _today()
    return sum(n for at, n in rows if _local_day(at) == today)


def _shelf(conn, lang):
    """The shelf's restore points (newest first) with their words, and how many cards are on it now."""
    if not _has(conn, "shelf"):
        return {"on_shelf": 0, "runs": []}
    runs = []
    for run, cards, why, at, back in conn.execute(
            "SELECT run, COUNT(*), MIN(why), MIN(shelved_at), SUM(back_at IS NOT NULL) FROM shelf WHERE language = ? "
            "GROUP BY run ORDER BY MIN(shelved_at) DESC", (lang,)):
        words = [r[0] for r in conn.execute("SELECT DISTINCT word FROM shelf WHERE run = ? AND word IS NOT NULL "
                                            "ORDER BY word LIMIT ?", (run, SHELF_WORDS))]
        runs.append({"run": run, "cards": cards, "back": back or 0, "why": why, "at": at, "words": words})
    on = conn.execute("SELECT COUNT(DISTINCT card_id) FROM shelf WHERE language = ? AND back_at IS NULL",
                      (lang,)).fetchone()[0]
    return {"on_shelf": on, "runs": runs}


def _line(conn, lang, rec, open_jobs, items, is_running):
    """U1's line and its state (working · waiting · idle)."""
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
    if open_jobs:
        first = sorted(open_jobs, key=lambda j: (items.get(j["item_id"], {}).get("place", (9, 0.0)), j["id"]))[0]
        if first.get("reason"):
            return first["reason"], "waiting"
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
        for root, _dirs, files in os.walk(folder):
            for name in sorted(files):
                full = os.path.join(root, name)
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
