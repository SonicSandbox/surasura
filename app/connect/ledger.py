"""Connect's ledger (P1.5 02-data-model §1 N4, §3): `<local data>/connect/ledger.sqlite`, per install, never in the
library or a cloud folder (K58, RD-D15). It holds work in flight — the jobs, one per item mined — and nothing that
lasts: lose it and Connect rebuilds what it needs from the store and Anki's tags, and mines nothing twice.

P2.1 builds the jobs table the inbox fills (`queued`, `dropped`); the rest of a job's life (`waiting` → … → `done`,
word outcomes, undo records) is P2.4's, on the same table. Short transactions, standard library `sqlite3`, like the
store.

P2.2 (SCHEMA 2, a SCHEMA 1 ledger upgraded in place): a job's `kind` — `mine` (an item's first cards) or `level` (the
newly listed words of an item already mined, HC-N38) — and its `words` (a level job's `[[word, reading], …]`; None: the
whole list); the list Connect last looked at (`listed`, with its run signature), so a level raise is told from the
first look; and `resort_due`, a re-sort owed after the list moved (the runner's ordering step pays it, P2.4).

P2.4 (SCHEMA 3, a SCHEMA 2 ledger upgraded in place by added columns and tables; one newer than this Surasura reads is
refused, never used — `TooNew`, P2.2 adversary #12): the runner's whole job (02 §2): its states, each saved before and
after its step (`set_state`; a job waiting mid-way keeps the step it resumes at, `resume`); the store it was queued
from (`store_id`: a store set up again can't mine another item under the same id, P2.1 adversary #12); what its pick
chose (`picked`, with the pairing's version and the Anki Miner profile it picked for); its batches (N5: the run folder,
the attempt, the Anki Miner that ran it); each word's outcome (N6: word, spelling, reading, its line's start, end and
sentence, the predicted class, the outcome, the note id — ✅ D1: the line stays here); the undo record (N9: the note ids
a job made, `undo_record`); and what Connect needs you for (`needs`: each named once, P2.5 shows them).

P2.5 (SCHEMA 4, a SCHEMA 3 ledger upgraded in place): *Needs you* as 03 §4 rules it — seen ≠ gone (`seen_at`: shown,
no longer counted, still listed), `dismissed_at` (left the list), `fixed_at` (its cause went away: `fix`); one open
entry per language + kind + item (open = not fixed), so a need raised again while open writes nothing (S19) and one
raised after its fix is new and counts again. `undos`: each *Undo this batch* (N9, Q2-6), what it deleted and what it
kept and why. `run:<lang>` in meta: when the run working on the language began (the status line's *i of n*).

P4.1 (still SCHEMA 4: one added column and one meta key, both read as absent by a Surasura before them — an older one
reads an asked job as a first mining, never a wrong write): a job's `asked_at`, the ask it answers (C2 / C3: the
store's `mine_asked` — *Mine now*, *Mine this*, *Mine it too*), kept whatever way the job ends so an ask is used up
once (IK S4); a job an ask made is of kind `asked`. `asks_from:<lang>` in meta: the asks watermark (asks made before it
— while Connect was off — are never mined; written by `resume.turned_on` at every off → on, never by a look: none
set, every unanswered ask counts, F-2).
Also P4.1: `generating:<lang>` in meta, set while Connect's own Generate runs (F9: the status line's
*Connect is updating your list*), cleared when it ends and by the next run when a crash left it.

The help cards (still SCHEMA 4, the P4.1 way: a SCHEMA bump would make a 3.0.0 refuse the ledger): a job's
`reason_at`, when its `reason` was last set — the window's *since 14:02* on a wait. Kept by one SQLite trigger over
every writer (`drop`, the wait, `set_state`, `reopen_skipped`, and any later): a new reason stamps it, the same reason
written again keeps it, a cleared reason clears it; a job inserted with a reason is stamped too. Rows from before stay
NULL (their wait shows no *since*). A Surasura before it ignores the column, and the trigger still runs harmlessly.
"""
import datetime
import json
import logging
import os
import sqlite3
import time
import uuid

_log = logging.getLogger("surasura-cli")
SCHEMA = 4
# A job's states (02 §2). Open = not finished one way or the other; not started = still droppable.
OPEN = ("queued", "waiting", "picking", "fit-check", "mining", "filling", "ordering")
NOT_STARTED = ("queued", "waiting")
IN_FLIGHT = tuple(s for s in OPEN if s not in NOT_STARTED)
DONE = "done"
DROPPED = "dropped"
FINISHED = (DONE, DROPPED, "failed", "undone", "skipped")
STATES = OPEN + FINISHED
# The steps a job waiting mid-way resumes at (`resume`): before mining it can still be dropped (02 §2: an item that
# leaves the top 20 before mining; once mining has started, it finishes).
BEFORE_MINING = (None, "picking", "fit-check")
BOOK_AUDIO_NEED = "book-audiobook"      # `runner.BOOK_AUDIO_NEED`: a book's one audiobook question (Kura-AB2)
# A job's kinds (P2.2): an item's first cards, or the newly listed words of one already mined; P4.1: one an ask made
# (*Mine this*, *Mine it too*: C3) — the only kind that makes again a word whose card you deleted (N15, IK S1).
MINE, LEVEL, ASKED = "mine", "level", "asked"
# Michi-EO (2026-11-17: a show is one unit): an earlier part of a show Connect queued a later part of, never mined and
# never a job before — queued with that part, by its person and its event (`event_id`), and mined ahead of it
# (`runner._ordered`); kept below the top 20 while it is in Current (`inbox.keeps`)
SHOW = "show"
# Kantan-SL (Swap, the simple version, 3.0.18): one word's new card from another line, the old card's line never
# (`app/connect/swap.py`): it carries the swap's time as its `asked_at` — the learner's own move, never held by the cap
# nor dropped off the top 20 — makes no receipt (as a level job), and no ask of the store moves onto it
SWAP = "swap"
# P4.1: the asks watermark's meta key, `asks_from:<lang>` (C1 / IK B2: `resume.turned_on` writes it at every off → on)
ASKS_FROM = "asks_from:"
# Laptop round 8 #47 (*Stop*): `stop:<job id>` — you asked the job to stop (the window's press, `ask_stop`); `stopped:<job
# id>` — the runner stopped it, holding the ask it carried then: it waits until a newer ask (*Mine now*) (`held_by_stop`)
STOP, STOPPED = "stop:", "stopped:"
STOPPED_REASON = "Stopped: its cards so far are kept. Press Mine now to go on."      # `runner.STOPPED_BY_YOU`
# Kantan-B2b: a job the placement log queued, set aside by the first run's *Not now* (`set_aside_first_run`):
# nothing mines by itself until your yes; *Make cards* queues it again (`back_from_aside`)
FIRST_RUN_ASIDE = "Set aside: you said Not now to the first cards"
# Laptop round 8 #52 (review A6): a word Anki Miner had no definition for in this many episodes is no card anywhere
UNCARDABLE_AFTER = 2


def stoppable(state, resume=None, progress=None):
    """Can a job in `state` (waiting at `resume`; mining at `progress`, its saved step) still be stopped? Until its
    cards are made: queued, waiting before filling, picking, the fit check, mining up to Anki Miner's run's end.
    Naming the clips, filling and ordering finish (review A3; row 56: naming is past the stop point — its cards are
    made, and their clips are named before Anki's next sync — so too a job whose naming waits, you reviewing: round 2),
    and a job waiting to fill or order (Anki closed) finishes too once it can."""
    if naming(progress) and (state == "mining" or (state == "waiting" and resume == "mining")):
        return False
    if state == "waiting":
        return resume not in ("filling", "ordering")
    return state in ("queued", "picking", "fit-check", "mining")


def naming(progress):
    """Row 56: is a mining job naming its clips (Anki Miner's run over)? `progress`: the job's saved progress, as the
    ledger keeps it (JSON text) or read (a dict; the status record's carries the same `step`)."""
    if isinstance(progress, str):
        try:
            progress = json.loads(progress)
        except ValueError:
            return False
    return isinstance(progress, dict) and progress.get("step") == "naming"

_SCHEMA_SQL = (
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS jobs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      language TEXT NOT NULL,
      item_id INTEGER NOT NULL,
      state TEXT NOT NULL,
      reason TEXT,
      source TEXT,
      event_id INTEGER,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      kind TEXT NOT NULL DEFAULT 'mine',
      words TEXT)""",
    # One open job per item (N4): a re-read of the same events can never queue it twice
    "CREATE UNIQUE INDEX IF NOT EXISTS one_open_job ON jobs (language, item_id) WHERE state IN ({})".format(
        ", ".join(f"'{s}'" for s in OPEN)),
    # A gap in the placement log (✅ P2.1-3): the top-20 episodes with no cards when Connect lost track, from its last
    # read (`since`) to the gap's read (`until`) — never mined; named once (2.x: the start-up notice; 3.0: Needs you)
    """CREATE TABLE IF NOT EXISTS gaps (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      language TEXT NOT NULL,
      since TEXT,
      until TEXT NOT NULL,
      items TEXT NOT NULL,
      noticed INTEGER NOT NULL DEFAULT 0)""",
    # The list Connect last looked at (P2.2): its keys, the pick's identity (Word, Reading); its run signature is in
    # meta (`listed:<lang>`). A level raise is the words listed now and not then.
    """CREATE TABLE IF NOT EXISTS listed (
      language TEXT NOT NULL,
      word TEXT NOT NULL,
      reading TEXT NOT NULL,
      PRIMARY KEY (language, word, reading))""",
)
# SCHEMA 1 -> 2 -> 3: the columns P2.2 and P2.4 add to a ledger made before them (the table above has P2.2's).
_ADDED_COLUMNS = (("kind", "TEXT NOT NULL DEFAULT 'mine'"), ("words", "TEXT"),
                  ("store_id", "TEXT"), ("resume", "TEXT"), ("picked", "TEXT"),
                  ("attempt", "INTEGER NOT NULL DEFAULT 0"), ("failures", "INTEGER NOT NULL DEFAULT 0"),
                  ("skipped", "TEXT"), ("tag_pending", "TEXT"),
                  ("asked_at", "TEXT"),         # P4.1: the ask the job answers (no SCHEMA bump: see the docstring)
                  ("progress", "TEXT"),         # laptop round 5 #23: where Anki Miner's run stands (JSON; as above)
                  ("reason_at", "TEXT"))        # help cards: when `reason` was last set (the trigger below; as above)
# The help cards' *since*: `reason_at` follows `reason` through every writer (made after the column exists). The time
# is `_now()`'s shape, in UTC, by SQLite's clock — the same clock as the rest of the ledger's times.
_REASON_AT_SQL = (
    """CREATE TRIGGER IF NOT EXISTS reason_since AFTER UPDATE OF reason ON jobs WHEN NEW.reason IS NOT OLD.reason
       BEGIN UPDATE jobs SET reason_at = CASE WHEN NEW.reason IS NULL THEN NULL
                                              ELSE strftime('%Y-%m-%dT%H:%M:%SZ', 'now') END WHERE id = NEW.id; END""",
    """CREATE TRIGGER IF NOT EXISTS reason_since_new AFTER INSERT ON jobs WHEN NEW.reason IS NOT NULL
       BEGIN UPDATE jobs SET reason_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = NEW.id; END""",
)
# P2.4's tables (made IF NOT EXISTS, like the rest)
_RUNNER_SQL = (
    # N5, one Anki Miner call: `state` running · done · uncertain (words in doubt) · refused (it never ran)
    """CREATE TABLE IF NOT EXISTS batches (
      job_id INTEGER NOT NULL,
      attempt INTEGER NOT NULL,
      run_dir TEXT NOT NULL,
      anki_miner TEXT,
      state TEXT NOT NULL,
      started_at TEXT NOT NULL,
      ended_at TEXT,
      PRIMARY KEY (job_id, attempt))""",
    # N6, one word's outcome (made · duplicate · not_found · no_definition · uncertain · …), its line kept here (D1)
    """CREATE TABLE IF NOT EXISTS outcomes (
      job_id INTEGER NOT NULL,
      word TEXT NOT NULL,
      reading TEXT NOT NULL,
      orth TEXT,
      line_start REAL,
      line_end REAL,
      sentence TEXT,
      predicted TEXT,
      outcome TEXT NOT NULL,
      note_id INTEGER,
      attempt INTEGER NOT NULL,
      PRIMARY KEY (job_id, word, reading))""",
    # REMAKE (3.0.19): a made note's outcome found by its note (Tidy's `_done_ats`, every note of a tidy in one query a
    # chunk; a scan per note before). No schema change: an older Surasura keeps the index as it is.
    "CREATE INDEX IF NOT EXISTS outcomes_note ON outcomes (note_id)",
    # What Connect needs you for (03 §4; P2.5's columns are added by `_needs_v4`): one open entry per kind + item
    """CREATE TABLE IF NOT EXISTS needs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      language TEXT NOT NULL,
      item_id INTEGER,
      job_id INTEGER,
      kind TEXT NOT NULL,
      say TEXT NOT NULL,
      at TEXT NOT NULL,
      seen INTEGER NOT NULL DEFAULT 0)""",
    # P2.5: each *Undo this batch*, written before Anki is (the notes it will delete), finished after (`finished_at`;
    # `deleted`: the notes gone then; `kept`: [[note id, word, why], ...]) — one a kill left unfinished is finished
    # by the next look (`undo.finish_pending`)
    """CREATE TABLE IF NOT EXISTS undos (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      job_id INTEGER NOT NULL,
      language TEXT NOT NULL,
      at TEXT NOT NULL,
      deleted TEXT NOT NULL,
      kept TEXT NOT NULL,
      finished_at TEXT)""",
    # Kyou-SH4 (Sonic 2026-11-22: a card you moved into a deck of your own is yours): the deck Surasura last put each
    # note's cards in — made there by its batch (`end_batch`), moved there by *Move them to X* (`decks.move`) — so
    # Tidy tells your move from Surasura's own (`tidy.why_kept`). No schema change: an older Surasura ignores it.
    "CREATE TABLE IF NOT EXISTS homes (note_id INTEGER PRIMARY KEY, deck TEXT NOT NULL)",
)
# SCHEMA 3 -> 4: *Needs you*'s own columns (P2.5)
_NEEDS_COLUMNS = (("seen_at", "TEXT"), ("dismissed_at", "TEXT"), ("fixed_at", "TEXT"))
# The language's own needs, fixed by a run whose sync, known-sync and Generate went through (03 §4: fixed by itself)
PREPARE_KINDS = ("known-sync", "generate", "no-store", "no-profile")
# Needs that are a standing state (it stays until its cause goes): raised again while open, nothing is written (S19).
# Every other kind is a failure: one that happens again after you've seen it counts again, with its new words (03 §4)
STANDING = ("not-timed", "no-profile", "no-store", "no-subtitle")
# The columns `set_state` may write beside the state
_STATE_COLUMNS = frozenset(("reason", "resume", "picked", "attempt", "failures", "skipped", "store_id", "tag_pending",
                            "asked_at", "progress"))
# Anki Miner's outcomes that settle a word without a card (it turned it down): never sent again for the item
_NOT_MADE = ("made", "uncertain", "not_attempted")


class TooNew(Exception):
    """The ledger was written by a newer Surasura (its schema above SCHEMA): refused, never read or written — Connect
    says so in *Needs you* (P2.2 adversary #12)."""

    def __init__(self, schema):
        self.schema = schema
        super().__init__(f"Connect's ledger (schema {schema}) is newer than this Surasura reads. Update Surasura.")


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def folder():
    from app.path_utils import get_local_data_path
    return os.path.join(get_local_data_path(), "connect")


def path():
    return os.path.join(folder(), "ledger.sqlite")


# Kantan-MA (a tester's report 2026-11-21: *Mine again* made no card and said nothing; PROVISIONAL words): why a word
# of an episode Connect could have made a card for has none — Anki Miner's answer, kept per word (`declined_outcomes`),
# or the pick's own reason (`pick.REASONS`), each kept in the job's `picked` as `left` and read back by `left_of`
LEFT_WHY = {"not_found": "Anki Miner couldn't find it in its line",
            "no_definition": "Anki Miner's dictionary has no entry for it",
            "duplicate": "Anki Miner found a card for it already",
            "media_failed": "its sound or picture couldn't be cut",
            "refused": "Anki refused its card",
            "skipped": "you skipped it"}
LEFT_OTHER = "Anki Miner made no card for it"      # any other answer it gave
# Kantan-SD (the sentence dial's Best, PROVISIONAL words): a word of this episode cut from another episode's line
LEFT_ELSEWHERE = "its card comes from a better sentence elsewhere"
BEST_SOURCE = "best-sentence"                   # `level.BEST` (level imports the ledger: named here too)


def left_of(language, item_ids, db_path=None):
    """{item_id: [{"word", "why"}]} — the words of each item's newest pick that have no card from it, and why: the
    pick's `left` (left out before Anki Miner, or turned down by it in an earlier job) and that job's own words Anki
    Miner turned down (`LEFT_WHY`). Read-only, without the ledger's own open, as `listed_of`; [] for an item with no
    such pick, every item [] with no ledger, one from a newer Surasura or one older than `picked`. Raises
    sqlite3.Error when it can't be read just now."""
    db_path = db_path or path()
    out = {i: [] for i in item_ids}
    if not out or not os.path.exists(db_path):
        return out
    from pathlib import Path
    conn = sqlite3.connect(Path(os.path.abspath(db_path)).as_uri() + "?mode=rw", uri=True, timeout=2.0)
    try:
        conn.execute("PRAGMA query_only=ON")
        try:
            schema = conn.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
            cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                return out
            raise
        if (schema and str(schema[0]).isdigit() and int(schema[0]) > SCHEMA) or "picked" not in cols:
            return out
        newest, ids = {}, list(out)
        for k in range(0, len(ids), 500):
            chunk = ids[k:k + 500]
            for job_id, item_id, raw in conn.execute(     # only the newest pick of each item is read
                    f"SELECT id, item_id, picked FROM jobs WHERE id IN (SELECT MAX(id) FROM jobs WHERE language = ? "
                    f"AND picked IS NOT NULL AND item_id IN ({','.join('?' * len(chunk))}) GROUP BY item_id)",
                    [language] + chunk):
                newest[item_id] = (job_id, raw)
        for item_id, (job_id, raw) in newest.items():
            try:
                left = (json.loads(raw) or {}).get("left") or ()
            except (ValueError, AttributeError):
                left = ()
            named = {}
            for w in left if isinstance(left, list) else ():
                if isinstance(w, dict) and w.get("word") and w.get("why"):
                    named.setdefault(str(w["word"]), str(w["why"]))
            for word, outcome in conn.execute(
                    f"SELECT word, outcome FROM outcomes WHERE job_id = ? AND outcome IN "
                    f"({','.join('?' * len(LEFT_WHY))}) ORDER BY rowid", (job_id,) + tuple(LEFT_WHY)):
                if word:
                    named.setdefault(word, LEFT_WHY[outcome])
            out[item_id] = [{"word": w, "why": why} for w, why in named.items()]
    finally:
        conn.close()
    return out


def listed_of(language, item_ids, db_path=None):
    """{item_id: {word: True / False}} — whether each word a job of the item picked was on the list then (`pick`'s
    `listed`; a later job's pick over an earlier one's), read-only, without the ledger's own open (no schema written,
    no write lock): the ✓ chip's *at your level* / *below it* (Michi-CK2). Words picked before the pick said so are
    left out; none at all with no ledger, one from a newer Surasura (never read, as `TooNew` says) or one older than
    the `picked` column. Raises sqlite3.Error when it can't be read just now (busy, locked)."""
    db_path = db_path or path()
    out = {i: {} for i in item_ids}
    if not out or not os.path.exists(db_path):
        return out
    from pathlib import Path
    conn = sqlite3.connect(Path(os.path.abspath(db_path)).as_uri() + "?mode=rw", uri=True, timeout=2.0)
    try:
        conn.execute("PRAGMA query_only=ON")
        try:
            schema = conn.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
            cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                return out                             # a ledger never set up
            raise
        if (schema and str(schema[0]).isdigit() and int(schema[0]) > SCHEMA) or "picked" not in cols:
            return out                                 # (review L-C1, L-C3) newer: never read; older: no marks yet
        ids = list(out)
        for k in range(0, len(ids), 500):
            chunk = ids[k:k + 500]
            for item_id, raw in conn.execute(
                    f"SELECT item_id, picked FROM jobs WHERE language = ? AND picked IS NOT NULL AND item_id IN "
                    f"({','.join('?' * len(chunk))}) ORDER BY id", [language] + chunk):
                try:
                    words = (json.loads(raw) or {}).get("words") or ()
                except (ValueError, AttributeError):
                    continue
                if not isinstance(words, list):
                    continue                           # (review L-S2) an odd record: no marks, never an error
                for w in words:
                    if isinstance(w, dict) and w.get("word") and isinstance(w.get("listed"), bool):
                        out[item_id][w["word"]] = w["listed"]
    finally:
        conn.close()
    return out


def homes_of(note_ids, db_path=None):
    """{note id: the deck Surasura last put its cards in} (`homes`, Kyou-SH4) for those of `note_ids` with a record,
    read-only as `listed_of` (no schema written, no write lock): *Move them to X*'s strays (`decks._find`). {} with no
    ledger or one never set up. Raises TooNew for one from a newer Surasura (its homes unknown here), sqlite3.Error
    when it can't be read just now."""
    db_path = db_path or path()
    ids = sorted({int(n) for n in note_ids})
    if not ids or not os.path.exists(db_path):
        return {}
    from pathlib import Path
    conn = sqlite3.connect(Path(os.path.abspath(db_path)).as_uri() + "?mode=rw", uri=True, timeout=2.0)
    out = {}
    try:
        conn.execute("PRAGMA query_only=ON")
        try:
            schema = conn.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
            if schema and str(schema[0]).isdigit() and int(schema[0]) > SCHEMA:
                raise TooNew(int(schema[0]))
            for k in range(0, len(ids), 500):
                chunk = ids[k:k + 500]
                out.update((int(n), str(d)) for n, d in conn.execute(
                    f"SELECT note_id, deck FROM homes WHERE note_id IN ({','.join('?' * len(chunk))})", chunk))
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                return {}                              # a ledger never set up, or one from before homes
            raise
    finally:
        conn.close()
    return out



def note_lines(ledger_path, ids, language="ja", strict=False):
    """{note id: (item id, line start s, line end s, sentence)} of the notes Connect made (`outcomes`, this
    language's jobs: item ids are the language's store's), read only; {} when there's none or it can't be read now.
    The item is the one whose line the card was cut from: the job's own, or (Kantan-SD 6, *Card sentences: Best*) the
    other episode its pick names for the word (`from`). The one reader of a card's line: Piyo's translations
    (`card_translations`) and the card's sound (`sound_source`, AUDIO-FIND) ask it. `strict`: a ledger that can't be
    read just now (busy, damaged) raises its sqlite3.Error instead of answering {} — "no record" would be a wrong
    answer there. An id that isn't a number is no note."""
    if not ledger_path or not os.path.isfile(ledger_path) or not ids:
        return {}
    from pathlib import Path
    conn = sqlite3.connect(Path(ledger_path).as_uri() + "?mode=ro", uri=True, timeout=2.0, isolation_level=None)
    try:
        conn.execute("PRAGMA query_only=1")
        picks = "j.picked" if "picked" in {r[1] for r in conn.execute("PRAGMA table_info(jobs)")} else "NULL"
        ids, out, cut = sorted({int(n) for n in ids if isinstance(n, int) or str(n).isdigit()}), {}, {}
        for at in range(0, len(ids), 500):
            part = ids[at:at + 500]
            for note, item, start, end, sentence, word, reading, job, picked in conn.execute(
                    f"SELECT o.note_id, j.item_id, o.line_start, o.line_end, o.sentence, o.word, o.reading, j.id, "
                    f"{picks} FROM outcomes o JOIN jobs j ON j.id = o.job_id WHERE o.outcome = 'made' AND "
                    f"j.language = ? AND o.note_id IN ({','.join('?' * len(part))})", [language] + part):
                if job not in cut:
                    cut[job] = cut_from(picked)
                out[int(note)] = (cut[job].get((word, reading), item), start, end, sentence)
        return out
    except sqlite3.Error:
        if strict:
            raise
        return {}
    finally:
        conn.close()


def cut_from(picked):
    """{(word, reading): item id} of a job's words cut from another episode's line (its pick's `from`, the JSON text
    the ledger keeps); {} for none, or a pick that can't be read."""
    try:
        words = (json.loads(picked) or {}).get("words") or () if picked else ()
    except (TypeError, ValueError, AttributeError):
        return {}
    out = {}
    try:
        for w in words:
            if isinstance(w, dict) and isinstance(w.get("from"), int) and not isinstance(w.get("from"), bool):
                out[(w.get("word"), w.get("reading"))] = w["from"]
    except TypeError:                   # (`words` not a list, a word that can't be a key: a pick that can't be read)
        return {}
    return out


class Ledger:
    """One connection to the ledger; `with Ledger() as ledger:` closes it."""

    def __init__(self, db_path=None):
        db_path = db_path or path()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path, timeout=5.0, isolation_level=None)
        self.conn.execute("PRAGMA busy_timeout=5000")
        for wait in (0.05, 0.1, 0.2, 0.4, 0.8, 1.6, None):
            try:            # two Connects opening a new ledger at once: switching it to WAL skips the busy handler
                self.conn.execute("PRAGMA journal_mode=WAL")
                break
            except sqlite3.OperationalError as e:
                if wait is None or "locked" not in str(e):
                    self.conn.close()
                    raise
                time.sleep(wait)
        self._uid = None
        try:
            self._refuse_newer()
        except BaseException:
            self.conn.close()
            raise
        with self.transaction():
            for sql in _SCHEMA_SQL + _RUNNER_SQL:
                self.conn.execute(sql)
            have = {row[1] for row in self.conn.execute("PRAGMA table_info(jobs)")}
            for name, decl in _ADDED_COLUMNS:
                if name not in have:
                    self.conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {decl}")
            for sql in _REASON_AT_SQL:
                self.conn.execute(sql)
            self._needs_v4()
            self.conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('schema', ?)", (str(SCHEMA),))
            # this ledger's own name in its jobs' tags: a ledger made again never reuses a lost one's tags
            self.conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('uid', ?)", (uuid.uuid4().hex[:8],))
            self.conn.execute("UPDATE meta SET value = ? WHERE key = 'schema' AND CAST(value AS INTEGER) < ?",
                              (str(SCHEMA), SCHEMA))

    def _needs_v4(self):
        """SCHEMA 4's *Needs you* (inside the opening transaction): its columns, and one open entry per language +
        kind + item (SCHEMA 3's index counted only unseen ones; an older duplicate is closed as fixed first)."""
        have = {row[1] for row in self.conn.execute("PRAGMA table_info(needs)")}
        for name, decl in _NEEDS_COLUMNS:
            if name not in have:
                self.conn.execute(f"ALTER TABLE needs ADD COLUMN {name} {decl}")
                if name == "seen_at" and "seen" in have:        # SCHEMA 3's shown ones stay shown
                    self.conn.execute("UPDATE needs SET seen_at = at WHERE seen = 1")
        if self.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'one_open_need'").fetchone():
            return
        self.conn.execute("DROP INDEX IF EXISTS one_need")
        self.conn.execute("UPDATE needs SET fixed_at = at WHERE fixed_at IS NULL AND id NOT IN (SELECT MAX(id) FROM "
                          "needs WHERE fixed_at IS NULL GROUP BY language, kind, COALESCE(item_id, -1))")
        self.conn.execute("CREATE UNIQUE INDEX one_open_need ON needs (language, kind, COALESCE(item_id, -1)) "
                          "WHERE fixed_at IS NULL")

    def _refuse_newer(self):
        if not self.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'").fetchone():
            return
        row = self.conn.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
        try:
            schema = int(row[0]) if row else 0
        except (TypeError, ValueError):
            schema = SCHEMA + 1             # a schema that can't be read is no schema this Surasura knows
        if schema > SCHEMA:
            raise TooNew(row[0] if row else None)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self.conn.close()

    def transaction(self):
        return _Transaction(self.conn)

    def job(self, language, item_id):
        """The item's latest job as a dict, or None."""
        cur = self.conn.execute("SELECT * FROM jobs WHERE language = ? AND item_id = ? ORDER BY id DESC LIMIT 1",
                                (language, item_id))
        row = cur.fetchone()
        return None if row is None else self._tagged(dict(zip([d[0] for d in cur.description], row)))

    def jobs(self, language=None, states=None):
        sql, params = "SELECT * FROM jobs WHERE 1 = 1", []
        if language:
            sql += " AND language = ?"
            params.append(language)
        if states:
            sql += f" AND state IN ({','.join('?' * len(states))})"
            params += list(states)
        cur = self.conn.execute(sql + " ORDER BY id", params)
        names = [d[0] for d in cur.description]
        return [self._tagged(dict(zip(names, r))) for r in cur.fetchall()]

    def tag_id(self, job_id):
        """The job's name in its Anki tag and run folder (`<ledger uid>-<job id>`): unique past a lost ledger
        (adversary P2.4-A #14), so an old job's notes are never counted as a new one's."""
        if self._uid is None:
            row = self.conn.execute("SELECT value FROM meta WHERE key = 'uid'").fetchone()
            self._uid = row[0] if row else "0"
        return f"{self._uid}-{job_id}"

    def _tagged(self, job):
        job["tag"] = self.tag_id(job["id"])
        return job

    def has_work(self, language, item_id):
        """An open job, or one already done (its receipt may not be written yet): never queue the item again."""
        marks = ",".join("?" * (len(OPEN) + 1))
        return self.conn.execute(f"SELECT 1 FROM jobs WHERE language = ? AND item_id = ? AND state IN ({marks}) "
                                 "LIMIT 1", (language, item_id) + OPEN + (DONE,)).fetchone() is not None

    def queue(self, language, item_id, source, event_id, store_id=None, kind=MINE):
        """A `queued` job for the item -> its id, or None when it already has work. `store_id`: the store it was read
        from (the runner refuses a job of another store); `kind`: MINE, or SHOW (Michi-EO)."""
        if self.has_work(language, item_id):
            return None
        now = _now()
        cur = self.conn.execute("INSERT INTO jobs (language, item_id, state, source, event_id, created_at, updated_at, "
                                "store_id, kind) VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?)",
                                (language, item_id, source, event_id, now, now, store_id, kind))
        return cur.lastrowid

    def queue_swap(self, language, item_id, word, reading, asked_at, store_id=None):
        """Kantan-SL: a `queued` job of kind `swap` for the item, naming one word ((word, reading); reading "" when the
        old card doesn't say) -> its id, or None while the item has an open job (one open job per item, N4: the swap
        is tried again at the next look)."""
        marks = ",".join("?" * len(OPEN))
        if self.conn.execute(f"SELECT 1 FROM jobs WHERE language = ? AND item_id = ? AND state IN ({marks}) LIMIT 1",
                             (language, item_id) + OPEN).fetchone():
            return None
        now = _now()
        cur = self.conn.execute("INSERT INTO jobs (language, item_id, state, source, event_id, created_at, updated_at, "
                                "kind, words, store_id, asked_at) VALUES (?, ?, 'queued', 'swap', NULL, ?, ?, ?, ?, ?, ?)",
                                (language, item_id, now, now, SWAP, json.dumps([[str(word), str(reading or "")]],
                                                                               ensure_ascii=False), store_id, asked_at))
        return cur.lastrowid

    def ever_had_job(self, language, item_id):
        """Michi-EO: has the item had any job, in any state (a show's catch-up queues only a part that never had)? One
        the first run's *Not now* set aside (Kantan-B2b) doesn't count: your *Mine now* on a later part brings it."""
        return self.conn.execute("SELECT 1 FROM jobs WHERE language = ? AND item_id = ? AND NOT (state = 'skipped' "
                                 "AND reason IS ?) LIMIT 1", (language, item_id, FIRST_RUN_ASIDE)).fetchone() is not None

    def mined_from_log(self, language):
        """Kantan-B2b: has Connect ever finished an episode from the placement log in this language, with cards (a
        `done` job with its event, no ask, and a card made)? Only that lifts the first run's hold on an old unanswered
        line: a job only queued (3.0.15's, its episode never reached), one part-way, or one your *Mine now* moved
        first never does. An ask's, a gap's or a level job's carries no event."""
        return self.conn.execute(
            "SELECT 1 FROM jobs j WHERE j.language = ? AND j.event_id IS NOT NULL AND j.asked_at IS NULL AND "
            "j.state = ? AND EXISTS (SELECT 1 FROM outcomes o WHERE o.job_id = j.id AND o.outcome = 'made') LIMIT 1",
            (language, DONE)).fetchone() is not None

    def set_aside_first_run(self, language):
        """Kantan-B2b (*Not now* on the first run's line): every job the placement log queued that hasn't started (no
        ask on it, never reached Anki Miner) set aside — `skipped` for FIRST_RUN_ASIDE, its row the learner's *Mine*
        again — inside the caller's transaction or its own -> how many. A job part-way stays where it stopped, and one
        you stopped (*Stop*: its `stopped:` record) stays stopped, its reason kept (the review's refuter, KB2B-6)."""
        marks = ",".join("?" * (len(BEFORE_MINING) - 1))
        sql = (f"UPDATE jobs SET state = 'skipped', reason = ?, resume = NULL, updated_at = ? WHERE language = ? AND "
               f"event_id IS NOT NULL AND asked_at IS NULL AND (state = 'queued' OR (state = 'waiting' AND "
               f"(resume IS NULL OR resume IN ({marks})))) AND NOT EXISTS (SELECT 1 FROM batches b WHERE "
               f"b.job_id = jobs.id AND b.state != 'refused') AND NOT EXISTS (SELECT 1 FROM meta m WHERE "
               f"m.key = ? || jobs.id)")
        params = (FIRST_RUN_ASIDE, _now(), language) + BEFORE_MINING[1:] + (STOPPED,)
        if self.conn.in_transaction:
            return self.conn.execute(sql, params).rowcount
        with self.transaction():
            return self.conn.execute(sql, params).rowcount

    def back_from_aside(self, language):
        """Kantan-B2b (the first run's *Make cards*, after a *Not now*): the jobs it set aside queued again, oldest
        first, where the item has no other open job and none done (your *Mine now* mined it meanwhile) -> how many.
        One whose item left the top 20 meanwhile is dropped at its turn, as any (`runner._job`)."""
        marks = ",".join("?" * (len(OPEN) + 1))
        n = 0
        with self.transaction():            # one row at a time: never two open jobs of one item (one_open_job)
            for job_id, item_id in self.conn.execute("SELECT id, item_id FROM jobs WHERE language = ? AND state = "
                                                     "'skipped' AND reason = ? ORDER BY id",
                                                     (language, FIRST_RUN_ASIDE)).fetchall():
                n += self.conn.execute(
                    f"UPDATE jobs SET state = 'queued', reason = NULL, updated_at = ? WHERE id = ? AND NOT EXISTS "
                    f"(SELECT 1 FROM jobs o WHERE o.language = ? AND o.item_id = ? AND o.state IN ({marks}))",
                    (_now(), job_id, language, item_id) + OPEN + (DONE,)).rowcount
        return n

    def last_read(self, language):
        """When Connect last read the language's placement log, or None."""
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (f"last_read:{language}",)).fetchone()
        return row[0] if row else None

    def mark_read(self, language):
        self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (f"last_read:{language}", _now()))

    def add_gap(self, language, items):
        """A gap's record: the top-20 items with no cards, from the last read to now -> its id."""
        cur = self.conn.execute("INSERT INTO gaps (language, since, until, items) VALUES (?, ?, ?, ?)",
                                (language, self.last_read(language), _now(), json.dumps(list(items))))
        return cur.lastrowid

    def gaps(self, language, unnoticed=False):
        """Every gap recorded for the language (newest last), each {id, since, until, items, noticed}: what 3.0's
        *Needs you* offers (*Make their cards* · *Leave them*)."""
        cur = self.conn.execute("SELECT * FROM gaps WHERE language = ?" + (" AND noticed = 0" if unnoticed else "")
                                + " ORDER BY id", (language,))
        return [_gap_row(cur, r) for r in cur.fetchall()]

    def mark_noticed(self, ids):
        self.conn.executemany("UPDATE gaps SET noticed = 1 WHERE id = ?", [(i,) for i in ids])

    # --- P2.2: the level raise (HC-N38 / N53) ---------------------------------------------------------------- #

    def job_by_id(self, job_id):
        """One job as a dict (its `words` read back as a list of (word, reading)), or None."""
        cur = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cur.fetchone()
        if row is None:
            return None
        out = self._tagged(dict(zip([d[0] for d in cur.description], row)))
        out["words"] = _words(out.get("words"))
        return out

    def in_flight(self, language):
        """Is a job of the language past its start (picking … ordering, or waiting mid-way)? Then the list it reads
        may be the one just replaced: the level raise waits for it."""
        marks = ",".join("?" * len(IN_FLIGHT))
        return self.conn.execute(f"SELECT 1 FROM jobs WHERE language = ? AND (state IN ({marks}) OR (state = 'waiting' "
                                 "AND resume IS NOT NULL)) LIMIT 1", (language,) + IN_FLIGHT).fetchone() is not None

    def _not_started(self, job_id):
        """Queued, or waiting with nothing picked yet: it can still gain words or be dropped."""
        row = self.conn.execute("SELECT state, resume FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return row is not None and (row[0] == "queued" or (row[0] == "waiting" and row[1] is None))

    def mined(self, language, item_id):
        """Has Connect finished mining the item (a `done` job)? The store's receipt says so too, once written."""
        return self.conn.execute("SELECT 1 FROM jobs WHERE language = ? AND item_id = ? AND state = ? LIMIT 1",
                                 (language, item_id, DONE)).fetchone() is not None

    def queue_level(self, language, item_id, words, source="level", store_id=None, asked_at=None):
        """A `queued` job of kind `level` for an item already mined, naming only `words` ((word, reading) pairs) ->
        its id. A level job still waiting gains the words (-> its id). Another open job of the item -> None: a first
        mining not started picks from the list as it is now, so the new words are its already. Kantan-SD: a Best
        sentence's job (`level.BEST`) and a raise's never share one (each keeps its own rules: the watched drop, the
        unlisted word) -> None. TOP-UP (3.0.21): `asked_at` — *Mine the new words*' press time (`stamp`): the job goes
        first and past the cap as an ask does (`runner.held_by_cap`); a waiting job it joins gains it and `source`."""
        words = sorted({(str(w), str(r)) for w, r in words or ()})
        if not words:
            return None
        marks = ",".join("?" * len(OPEN))
        row = self.conn.execute(f"SELECT id, kind, state, words, source FROM jobs WHERE language = ? AND item_id = ? "
                                f"AND state IN ({marks}) ORDER BY id DESC LIMIT 1", (language, item_id) + OPEN).fetchone()
        now = _now()
        if row is not None:
            job_id, kind, state, had, was = row
            if kind != LEVEL or not self._not_started(job_id) or (was == BEST_SOURCE) != (source == BEST_SOURCE):
                return None
            merged = sorted(set(_words(had)) | set(words))
            self.conn.execute("UPDATE jobs SET words = ?, updated_at = ? WHERE id = ?",
                              (json.dumps(merged, ensure_ascii=False), now, job_id))
            if asked_at:                    # the press's job now (its source: the inbox never un-asks it)
                self.conn.execute("UPDATE jobs SET asked_at = ?, source = ? WHERE id = ?", (asked_at, source, job_id))
            return job_id
        cur = self.conn.execute("INSERT INTO jobs (language, item_id, state, source, event_id, created_at, updated_at, "
                                "kind, words, store_id, asked_at) VALUES (?, ?, 'queued', ?, NULL, ?, ?, ?, ?, ?, ?)",
                                (language, item_id, source, now, now, LEVEL, json.dumps(words, ensure_ascii=False),
                                 store_id, asked_at))
        return cur.lastrowid

    def mined_items(self, language):
        """TOP-UP: every item a first mining finished (`mined`, one read for all): a `done` job of any kind but a level
        top-up's or a swap's (those make no receipt)."""
        return {row[0] for row in self.conn.execute(
            "SELECT DISTINCT item_id FROM jobs WHERE language = ? AND state = ? AND kind NOT IN (?, ?)",
            (language, DONE, LEVEL, SWAP))}

    def recorded_list(self, language):
        """(the run signature of the list Connect last looked at, its keys as a set of (word, reading)), or
        (None, None) before the first look."""
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (f"listed:{language}",)).fetchone()
        if row is None:
            return None, None
        keys = {(w, r) for w, r in self.conn.execute("SELECT word, reading FROM listed WHERE language = ?",
                                                     (language,))}
        return row[0], keys

    def record_list(self, language, signature, keys):
        """The list as looked at now (inside the caller's transaction)."""
        self.conn.execute("DELETE FROM listed WHERE language = ?", (language,))
        self.conn.executemany("INSERT OR IGNORE INTO listed (language, word, reading) VALUES (?, ?, ?)",
                              [(language, str(w), str(r)) for w, r in keys])
        self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (f"listed:{language}", signature))

    def forget_list(self, language):
        """Connect switched on again: the next look records the list and mines nothing (inside the caller's
        transaction)."""
        self.conn.execute("DELETE FROM listed WHERE language = ?", (language,))
        self.conn.execute("DELETE FROM meta WHERE key = ?", (f"listed:{language}",))

    def mark_new_files(self, language, since):
        """Kantan-MO: Connect's own Generate after mining new files ran (`runner.Steps.generate_after`): the items
        mined since `since` (this run's start) were mined from a list that didn't have their own new words yet — the
        next list look gives them those (`level.check`). The mark names those items, never a time: an episode mined
        after it (from a list that already held its words) is never given a level job by it (train 56's keeper F1). A
        mark not yet taken keeps its items. Inside the caller's transaction."""
        items = set(self.take_new_files(language) or ()) | set(self.mined_since(language, since))
        self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                          (f"new_files:{language}", json.dumps(sorted(items))))

    def take_new_files(self, language):
        """The items the mark `mark_new_files` left, taken (cleared) — or None. A mark an older ledger wrote (a bare
        time) is dropped, never read as every episode mined since. Inside the caller's transaction."""
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (f"new_files:{language}",)).fetchone()
        if row is None:
            return None
        self.conn.execute("DELETE FROM meta WHERE key = ?", (f"new_files:{language}",))
        try:
            items = json.loads(row[0])
        except (TypeError, ValueError):
            return None
        return [i for i in items if isinstance(i, int)] if isinstance(items, list) else None

    def mined_since(self, language, since):
        """[item ids] with a job other than a level job that ended `done` at or after `since`, in the order they
        ended."""
        rows = self.conn.execute("SELECT item_id, MAX(updated_at) FROM jobs WHERE language = ? AND kind != ? AND "
                                 "state = 'done' AND updated_at >= ? GROUP BY item_id ORDER BY MAX(updated_at)",
                                 (language, LEVEL, since)).fetchall()
        return [r[0] for r in rows]

    def owe_resort(self, language):
        self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (f"resort_due:{language}", _now()))

    def resort_owed(self, language):
        """When a re-sort became owed (the list moved), or None: the runner's ordering step pays it (P2.4)."""
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (f"resort_due:{language}",)).fetchone()
        return row[0] if row else None

    def resort_paid(self, language):
        self.conn.execute("DELETE FROM meta WHERE key = ?", (f"resort_due:{language}",))

    def drop(self, language, item_id, reason):
        """The item's job, if it hasn't started (an item that left the top 20 before mining) -> dropped or not. Once
        mining has started, it finishes (02 §2)."""
        marks = ",".join("?" * (len(BEFORE_MINING) - 1))
        cur = self.conn.execute(f"UPDATE jobs SET state = 'dropped', reason = ?, resume = NULL, updated_at = ? "
                                f"WHERE language = ? AND item_id = ? AND (state = 'queued' OR (state = 'waiting' AND "
                                f"(resume IS NULL OR resume IN ({marks}))))",
                                (reason, _now(), language, item_id) + BEFORE_MINING[1:])
        if cur.rowcount > 0:                # its troubles went with it (03 §4: fixed by itself, IK P2.5 #3)
            # Kura-AB5 (11-20 report: the card went and came back as the parts left the top 20): a book's question
            # another waiting part still holds stays — `runner._book_orphans` lets it go once none does
            held = [r[0] for r in self.conn.execute(
                "SELECT n.say FROM needs n WHERE n.language = ? AND n.item_id = ? AND n.kind = ? AND "
                "n.fixed_at IS NULL AND EXISTS (SELECT 1 FROM jobs j WHERE j.language = n.language AND "
                "j.state = 'waiting' AND "
                "j.item_id != n.item_id AND j.reason = n.say)", (language, item_id, BOOK_AUDIO_NEED))]
            for row in self.fix(language, item_id=item_id, keep=held):
                _log.info("Connect: fixed by itself (%s, %s): %s", language, row["kind"], row["say"])
        return cur.rowcount > 0

    # --- P4.1: asked mining (C2 / C3) ------------------------------------------------------------------------- #

    def asks_from(self, language):
        """The asks watermark (`asks_from:<lang>`): an ask made before it is never mined, or None (never set)."""
        return asks_from_in(self.conn, language)

    def set_asks_from(self, language, at=None):
        """The asks watermark at `at` (default now, the store's stamp format), inside the caller's transaction."""
        self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                          (ASKS_FROM + language, at or stamp()))

    def ask(self, language, item_id, asked_at, store_id=None):
        """An ask for the item (the store's `mine_asked`, C2) -> ("queued", job id): a new job of kind `asked`, by
        `user`; ("moved", job id): the item's open job now carries it (it goes first — *Mine now* — and stays what it
        was: it makes no deleted word again, IK S1); None: a job already holds this very ask, however it ended (any
        ending uses the ask up, IK S4). Inside the caller's transaction."""
        if ask_recorded_in(self.conn, language, item_id, asked_at):
            return None
        marks = ",".join("?" * len(OPEN))
        row = self.conn.execute(f"SELECT id FROM jobs WHERE language = ? AND item_id = ? AND state IN ({marks}) "
                                "ORDER BY id DESC LIMIT 1", (language, item_id) + OPEN).fetchone()
        now = _now()
        if row is not None and self.conn.execute("SELECT kind FROM jobs WHERE id = ?", (row[0],)).fetchone()[0] == SWAP:
            return None                 # Kantan-SL: a swap's one word is under way: the ask is read again after it
        if row is not None:
            self.conn.execute("UPDATE jobs SET asked_at = ?, updated_at = ? WHERE id = ?", (asked_at, now, row[0]))
            # laptop round 8 #47 (review A4): *Mine now* after a *Stop* the runner hasn't reached yet — your later
            # press wins: the pending stop is dropped (a stop already made is released by `held_by_stop`)
            self.conn.execute("DELETE FROM meta WHERE key = ?", (f"{STOP}{int(row[0])}",))
            return "moved", row[0]
        cur = self.conn.execute("INSERT INTO jobs (language, item_id, state, source, event_id, created_at, updated_at, "
                                "kind, store_id, asked_at) VALUES (?, ?, 'queued', 'user', NULL, ?, ?, ?, ?, ?)",
                                (language, item_id, now, now, ASKED, store_id, asked_at))
        return "queued", cur.lastrowid

    # --- laptop round 8 #47: *Stop* — the current episode's job, at its next safe point ------------------------- #

    def ask_stop(self, job_id):
        """You pressed *Stop* on a job (the window, any process) -> True when the job is open: the runner stops it within
        a second or so — before its next step; a program it waits on ended within a second (tsubasa's check, Anki
        Miner's look-ups: laptop round 9 #56, `stopping`) and the job stopped before that step; or Anki Miner's batch
        cancelled (`anki_miner.cancel`), what it made kept — and it waits until you ask again. A job not under way (queued, or waiting) is stopped here
        and now, in the same transaction, so its stone says so at once even with Connect not running; the press is
        kept too, so a runner that took the job up meanwhile stops it at its next step. A job already ended -> False,
        nothing written. A press twice is one stop."""
        if self.conn.in_transaction:
            return self._ask_stop(job_id)
        with self.transaction():
            return self._ask_stop(job_id)

    def _ask_stop(self, job_id):
        row = self.conn.execute("SELECT state, asked_at, resume, progress FROM jobs WHERE id = ?",
                                (job_id,)).fetchone()
        if row is None or not stoppable(row[0], row[2], row[3]):
            return False
        self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (f"{STOP}{int(job_id)}", _now()))
        if row[0] in NOT_STARTED:
            self.conn.execute("UPDATE jobs SET state = 'waiting', reason = ?, updated_at = ? WHERE id = ?",
                              (STOPPED_REASON, _now(), job_id))
            self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                              (f"{STOPPED}{int(job_id)}", row[1] or ""))
        return True

    def stop_asked(self, job_id):
        """Has *Stop* been pressed on this job, not yet acted on? (one indexed read: the runner asks it often)"""
        return self.conn.execute("SELECT 1 FROM meta WHERE key = ?", (f"{STOP}{int(job_id)}",)).fetchone() is not None

    def mark_stopped(self, job_id, asked_at):
        """The runner stopped the job (inside the caller's transaction or alone): the press used up, the ask it carried
        then (`asked_at`, or none) kept, so only a newer ask lets it go on (`held_by_stop`)."""
        self.conn.execute("DELETE FROM meta WHERE key = ?", (f"{STOP}{int(job_id)}",))
        self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                          (f"{STOPPED}{int(job_id)}", asked_at or ""))

    def held_by_stop(self, job):
        """Does a job you stopped still wait (no ask newer than the one it carried when it stopped)? A newer ask — your
        *Mine now* — lets it go on: the stop's record is taken off then."""
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (f"{STOPPED}{int(job['id'])}",)).fetchone()
        if row is None:
            return False
        asked = job.get("asked_at")
        if not asked or (row[0] and stamp_key(asked) <= stamp_key(row[0])):
            return True                     # no ask, the one it stopped with, or an older one (an ask undone: A5)
        self.forget_stop(job["id"])         # your newer ask: the stop and any press it answered are over
        return False

    def is_stopped(self, job_id):
        """Does the job wait because you stopped it (its `stopped:` record)? A look only, nothing released."""
        return self.conn.execute("SELECT 1 FROM meta WHERE key = ?",
                                 (f"{STOPPED}{int(job_id)}",)).fetchone() is not None

    def forget_stop(self, job_id):
        """The job ended: its *Stop* records go (a press it outlived, or the stop it waited by)."""
        self.conn.execute("DELETE FROM meta WHERE key IN (?, ?)", (f"{STOP}{int(job_id)}", f"{STOPPED}{int(job_id)}"))

    def unask(self, job_id):
        """The ask a job carried, undone before its mining started: a job the ask made is dropped (*left: ask undone*);
        one it only moved first goes back to its place (inside the caller's transaction) -> "dropped" or "cleared"."""
        row = self.conn.execute("SELECT kind, language, item_id FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        if row[0] == ASKED:
            self.drop(row[1], row[2], "left: ask undone")
            return "dropped"
        self.conn.execute("UPDATE jobs SET asked_at = NULL, updated_at = ? WHERE id = ?", (_now(), job_id))
        return "cleared"

    # --- P2.4: the runner's job (02 §2, N5, N6, N9) ----------------------------------------------------------- #

    def set_state(self, job_id, state, **columns):
        """A job's state, saved now in its own short transaction (or the caller's), with any of `_STATE_COLUMNS`
        (`picked` and `skipped` as JSON). Leaving `waiting` clears its resume step, and an open state its reason,
        unless given."""
        if state not in STATES:
            raise ValueError(f"unknown state {state!r}")
        unknown = set(columns) - _STATE_COLUMNS
        if unknown:
            raise ValueError(f"unknown columns {sorted(unknown)}")
        if state != "waiting":
            columns.setdefault("resume", None)
            if state not in FINISHED:
                columns.setdefault("reason", None)
        for name in ("picked", "skipped", "progress"):
            if columns.get(name) is not None and not isinstance(columns[name], str):
                columns[name] = json.dumps(columns[name], ensure_ascii=False)
        sets = "".join(f", {name} = ?" for name in columns)
        sql = f"UPDATE jobs SET state = ?, updated_at = ?{sets} WHERE id = ?"
        params = (state, _now()) + tuple(columns.values()) + (job_id,)
        if self.conn.in_transaction:
            self._set(sql, params, job_id, state)
        else:
            with self.transaction():
                self._set(sql, params, job_id, state)

    def _set(self, sql, params, job_id, state):
        self.conn.execute(sql, params)
        if state in FINISHED:               # #47 (review A9): an ended job keeps no *Stop* record
            self.forget_stop(job_id)

    def picked(self, job_id):
        """What the job's pick chose (a dict), or None."""
        row = self.conn.execute("SELECT picked FROM jobs WHERE id = ?", (job_id,)).fetchone()
        try:
            return json.loads(row[0]) if row and row[0] else None
        except ValueError:
            return None

    def open_jobs(self, language):
        """Every open job of the language (oldest first), each with its `words` read back."""
        out = self.jobs(language, states=OPEN)
        for job in out:
            job["words"] = _words(job.get("words"))
        return out

    def start_batch(self, job_id, attempt, run_dir):
        """A batch about to call Anki Miner (N5): `running` until `end_batch`. One left `running` after a kill is a
        batch in doubt — its notes are found by the job's tag before anything is tried again (E25)."""
        with self.transaction():
            self.conn.execute("INSERT OR REPLACE INTO batches (job_id, attempt, run_dir, state, started_at) "
                              "VALUES (?, ?, ?, 'running', ?)", (job_id, attempt, run_dir, _now()))
            self.conn.execute("UPDATE jobs SET attempt = ?, updated_at = ? WHERE id = ?", (attempt, _now(), job_id))

    def end_batch(self, job_id, attempt, state, outcomes=(), anki_miner=None, deck=None):
        """The batch's end and its words' outcomes, in one transaction (a kill leaves the batch running, or both);
        `deck`: the deck the batch made its cards in (None: not known — a kill's batch read back by its tag), each
        made note's home (`homes`), never over one recorded before."""
        with self.transaction():
            self.record_outcomes(job_id, attempt, outcomes)
            self.conn.execute("UPDATE batches SET state = ?, anki_miner = ?, ended_at = ? WHERE job_id = ? AND "
                              "attempt = ?", (state, anki_miner, _now(), job_id, attempt))
            if deck:
                self.conn.executemany("INSERT OR IGNORE INTO homes (note_id, deck) VALUES (?, ?)",
                                      [(int(o["note_id"]), str(deck)) for o in outcomes
                                       if o.get("outcome") == "made" and o.get("note_id") is not None])

    def set_homes(self, note_ids, deck):
        """Surasura put `note_ids`' cards in `deck` (*Move them to X*); None takes the record away (its Undo putting
        it back as it was)."""
        with self.transaction():
            if deck is None:
                self.conn.executemany("DELETE FROM homes WHERE note_id = ?", [(int(n),) for n in note_ids])
            else:
                self.conn.executemany("INSERT OR REPLACE INTO homes (note_id, deck) VALUES (?, ?)",
                                      [(int(n), str(deck)) for n in note_ids])

    def homes(self, note_ids):
        """{note id: the deck Surasura last put its cards in} for those of `note_ids` it has a record of."""
        ids, out = sorted({int(n) for n in note_ids}), {}
        for at in range(0, len(ids), 500):
            chunk = ids[at:at + 500]
            out.update((int(n), d) for n, d in self.conn.execute(
                f"SELECT note_id, deck FROM homes WHERE note_id IN ({','.join('?' * len(chunk))})", chunk))
        return out

    def carry_homes(self, id_map):
        """A note Anki gave a new id (an Undo's import) keeps the home of the note it was, inside the caller's
        transaction."""
        for old, new in id_map.items():
            if int(old) != int(new):
                self.conn.execute("INSERT OR IGNORE INTO homes (note_id, deck) SELECT ?, deck FROM homes "
                                  "WHERE note_id = ?", (int(new), int(old)))

    def record_outcomes(self, job_id, attempt, outcomes):
        """N6 rows, inside the caller's transaction: a later attempt's row replaces an earlier one's, never a word
        already `made`."""
        for o in outcomes:
            had = self.conn.execute("SELECT outcome FROM outcomes WHERE job_id = ? AND word = ? AND reading = ?",
                                    (job_id, o["word"], o["reading"])).fetchone()
            if had and had[0] == "made" and o.get("outcome") != "made":
                continue
            self.conn.execute(
                "INSERT OR REPLACE INTO outcomes (job_id, word, reading, orth, line_start, line_end, sentence, "
                "predicted, outcome, note_id, attempt) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (job_id, o["word"], o["reading"], o.get("orth"), o.get("line_start"), o.get("line_end"),
                 o.get("sentence"), o.get("predicted"), o["outcome"], o.get("note_id"), attempt))

    def batches(self, job_id):
        cur = self.conn.execute("SELECT * FROM batches WHERE job_id = ? ORDER BY attempt", (job_id,))
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]

    def outcomes(self, job_id):
        cur = self.conn.execute("SELECT * FROM outcomes WHERE job_id = ? ORDER BY rowid", (job_id,))
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]

    def undo_record(self, job_id):
        """N9: the note ids the job made (its `made` outcomes), for *Undo this batch* (P2.5)."""
        return [r[0] for r in self.conn.execute("SELECT note_id FROM outcomes WHERE job_id = ? AND outcome = 'made' "
                                                "AND note_id IS NOT NULL ORDER BY rowid", (job_id,))]

    def declined(self, language, item_id):
        """(word, reading) of every word Anki Miner turned down for the item, in any of its jobs (not found, no
        definition …): a later pick never sends them again (adversary P2.4-A #19)."""
        marks = ",".join("?" * len(_NOT_MADE))
        return {(w, r) for w, r in self.conn.execute(
            f"SELECT o.word, o.reading FROM outcomes o JOIN jobs j ON j.id = o.job_id WHERE j.language = ? AND "
            f"j.item_id = ? AND o.outcome NOT IN ({marks})", (language, item_id) + _NOT_MADE)}

    def declined_outcomes(self, language, item_id):
        """{(word, reading): outcome} of `declined`'s words, the newest answer each (Kantan-MA: said with the word)."""
        marks = ",".join("?" * len(_NOT_MADE))
        return {(w, r): o for w, r, o in self.conn.execute(
            f"SELECT o.word, o.reading, o.outcome FROM outcomes o JOIN jobs j ON j.id = o.job_id WHERE j.language = ? "
            f"AND j.item_id = ? AND o.outcome NOT IN ({marks}) ORDER BY o.rowid", (language, item_id) + _NOT_MADE)}

    def uncardable(self, language, app=None):
        """(word, reading) of every word Anki Miner answered *no definition* for in this language, in any episode
        (laptop round 8 #52, LF4-4 ⭐ A: a name its dictionary has no entry for — ルーデウス — is no card in any
        episode): a pick never sends one again, and the window marks it on the journey. `app`: only the answers of that
        Anki Miner version (a new one, with another dictionary, is asked again); None: every version's."""
        query = ("SELECT o.word, o.reading FROM outcomes o JOIN jobs j ON j.id = o.job_id "
                 "JOIN batches b ON b.job_id = o.job_id AND b.attempt = o.attempt "
                 "WHERE j.language = ? AND o.outcome = 'no_definition'")
        args = (language,)
        if app is not None:
            query += " AND b.anki_miner = ?"
            args += (str(app),)
        # in two episodes or more (review A6): Anki Miner reads a word from its line, and one odd line's answer is no
        # verdict on the word
        query += " GROUP BY o.word, o.reading HAVING COUNT(DISTINCT j.item_id) >= ?"
        args += (UNCARDABLE_AFTER,)
        return {(w, r) for w, r in self.conn.execute(query, args)}

    def skipped_words(self, language, app=None):
        """Michi-RM3: (word, reading) of every word you skipped in this language (*Skip this word* on a part whose
        card Anki refused: outcome `skipped`, `actions.skip_refused`), in any part: a pick never sends one again. `app`:
        only those skipped with that Anki Miner version (a new one may write the card Anki takes: asked once more);
        None: every version's."""
        query = ("SELECT o.word, o.reading FROM outcomes o JOIN jobs j ON j.id = o.job_id "
                 "JOIN batches b ON b.job_id = o.job_id AND b.attempt = o.attempt "
                 "WHERE j.language = ? AND o.outcome = 'skipped'")
        args = (language,)
        if app is not None:
            query += " AND (b.anki_miner = ? OR b.anki_miner IS NULL)"     # (unknown: every version's, review N2)
            args += (str(app),)
        return {(w, r) for w, r in self.conn.execute(query, args)}

    def skipped_for(self, language, reason):
        """Is any job of the language `skipped` for `reason`?"""
        return self.conn.execute("SELECT 1 FROM jobs WHERE language = ? AND state = 'skipped' AND reason = ? LIMIT 1",
                                 (language, reason)).fetchone() is not None

    def reopen_skipped(self, language, item_ids, reason):
        """Jobs `skipped` for `reason` (Anki Miner wasn't installed) of these items queued again, where the item has
        no other open job -> how many (intent keeper P2.4-A #11: installed later, they're mined in turn)."""
        marks = ",".join("?" * len(OPEN))
        n = 0
        for item_id in item_ids:
            cur = self.conn.execute(
                f"UPDATE jobs SET state = 'queued', reason = NULL, resume = NULL, skipped = NULL, updated_at = ? "
                f"WHERE id = (SELECT MAX(id) FROM jobs WHERE language = ? AND item_id = ?) AND state = 'skipped' AND "
                f"reason = ? AND NOT EXISTS (SELECT 1 FROM jobs WHERE language = ? AND item_id = ? AND state IN "
                f"({marks}))", (_now(), language, item_id, reason, language, item_id) + OPEN)
            n += cur.rowcount
        return n

    def need(self, language, kind, say, item_id=None, job_id=None, standing=False):
        """Something Connect needs you for (`kind` + item) -> True when it counts (again) in the badge. Open already:
        a standing state (`STANDING`, or `standing`: the language's own trouble, alpha 6 try #6) is left as it is,
        nothing written (S19); a failure you've seen happens again → it counts again with its new words (03 §4); one
        not seen yet, or dismissed (it stays dismissed until its fix), is left as it is. Fixed earlier → a new entry."""
        cur = self.conn.execute("INSERT OR IGNORE INTO needs (language, item_id, job_id, kind, say, at) "
                                "VALUES (?, ?, ?, ?, ?, ?)", (language, item_id, job_id, kind, say, _now()))
        if cur.rowcount > 0:
            return True
        if standing:
            # the language's own trouble in new words (another deck, another field): its words follow — a new
            # decision, counted again unless dismissed; the same words write nothing (S19)
            where = ("WHERE language = ? AND kind = ? AND COALESCE(item_id, -1) = COALESCE(?, -1) AND fixed_at IS NULL "
                     "AND say != ?")
            row = self.conn.execute(f"SELECT id, dismissed_at FROM needs {where}",
                                    (language, kind, item_id, say)).fetchone()
            if row is None:
                return False
            self.conn.execute("UPDATE needs SET say = ?, at = ?, job_id = ?, seen_at = CASE WHEN dismissed_at IS NULL "
                              "THEN NULL ELSE seen_at END WHERE id = ?", (say, _now(), job_id, row[0]))
            return row[1] is None
        if kind in STANDING:
            return False
        cur = self.conn.execute("UPDATE needs SET seen_at = NULL, say = ?, at = ?, job_id = ? "
                                "WHERE language = ? AND kind = ? AND COALESCE(item_id, -1) = COALESCE(?, -1) AND "
                                "fixed_at IS NULL AND seen_at IS NOT NULL AND dismissed_at IS NULL",
                                (say, _now(), job_id, language, kind, item_id))
        return cur.rowcount > 0

    def needs(self, language=None, unseen=False, listed=True):
        """The open needs (not fixed), oldest first: `listed` — not dismissed either (what *Needs you* lists);
        `unseen` — not seen yet either (the badge)."""
        sql, params = "SELECT * FROM needs WHERE fixed_at IS NULL", []
        if language:
            sql += " AND language = ?"
            params.append(language)
        if listed:
            sql += " AND dismissed_at IS NULL"
        if unseen:
            sql += " AND seen_at IS NULL"
        cur = self.conn.execute(sql + " ORDER BY id", params)
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]

    def mark_seen(self, ids):
        """*Needs you* shown: these stop counting in the badge and stay listed -> how many changed (one seen already
        is not written again)."""
        ids = [int(i) for i in ids or ()]
        if not ids:
            return 0
        with self.transaction():
            now = _now()
            return sum(self.conn.execute("UPDATE needs SET seen_at = ? WHERE id = ? AND seen_at IS NULL",
                                         (now, i)).rowcount for i in ids)

    def dismiss(self, need_id):
        """*Dismiss*: the entry leaves the list. It stays open (raised again, it stays dismissed) until its cause goes
        away; after that, the same trouble is a new entry -> True when it changed."""
        with self.transaction():
            now = _now()
            return self.conn.execute("UPDATE needs SET dismissed_at = ?, seen_at = COALESCE(seen_at, ?) WHERE id = ? "
                                     "AND dismissed_at IS NULL AND fixed_at IS NULL",
                                     (now, now, int(need_id))).rowcount > 0

    def fix(self, language, kinds=None, item_id=None, keep=()):
        """Needs whose cause went away (03 §4: fixed by itself; nothing open → nothing written, no lock taken) -> the
        fixed rows (the caller logs each): every open need of `item_id`, or the language's own needs (no item) of
        `kinds`; never one whose words are in `keep` (a step the job ended without: its trouble stands). Nothing open →
        nothing written."""
        if item_id is not None:
            where, params = "language = ? AND item_id = ?", [language, item_id]
        elif kinds:
            where = f"language = ? AND item_id IS NULL AND kind IN ({','.join('?' * len(kinds))})"
            params = [language] + list(kinds)
        else:
            return []
        cur = self.conn.execute(f"SELECT * FROM needs WHERE fixed_at IS NULL AND {where}", params)
        names = [d[0] for d in cur.description]
        rows = [dict(zip(names, r)) for r in cur.fetchall() if r[names.index("say")] not in set(keep or ())]
        if not rows:
            return []
        now = _now()
        # exactly the rows read, with the words read: one raised again meanwhile (new words) is not fixed unread
        update = "UPDATE needs SET fixed_at = ? WHERE id = ? AND fixed_at IS NULL AND say = ?"
        if self.conn.in_transaction:
            return [r for r in rows if self.conn.execute(update, (now, r["id"], r["say"])).rowcount]
        with self.transaction():
            return [r for r in rows if self.conn.execute(update, (now, r["id"], r["say"])).rowcount]

    def fix_said(self, language, says):
        """The open needs of one episode each whose words are one of `says` — a trouble of the whole language an
        earlier Connect recorded once per episode (alpha 6 try #6) — fixed -> the fixed rows. Nothing open → nothing
        written."""
        says = tuple(says or ())
        if not says:
            return []
        cur = self.conn.execute(f"SELECT * FROM needs WHERE fixed_at IS NULL AND language = ? AND item_id IS NOT NULL "
                                f"AND say IN ({','.join('?' * len(says))})", (language,) + says)
        names = [d[0] for d in cur.description]
        rows = [dict(zip(names, r)) for r in cur.fetchall()]
        if not rows:
            return []
        now = _now()
        update = "UPDATE needs SET fixed_at = ? WHERE id = ? AND fixed_at IS NULL"
        if self.conn.in_transaction:
            return [r for r in rows if self.conn.execute(update, (now, r["id"])).rowcount]
        with self.transaction():
            return [r for r in rows if self.conn.execute(update, (now, r["id"])).rowcount]

    # --- P2.5: the run's start, the undos ------------------------------------------------------------------- #

    def mark_run(self, language):
        """A run began working on the language now (the status line counts its jobs from here)."""
        self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (f"run:{language}", _now()))

    def run_started(self, language):
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (f"run:{language}",)).fetchone()
        return row[0] if row else None

    # --- P4.1 row 4.1.7 (F9): Connect's own Generate, for the status line --------------------------------------- #

    def mark_updating(self, language):
        """Connect's own Generate for the language starts now (`generating:<lang>` in meta): the status line says
        *Connect is updating your list* while it runs."""
        self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (f"generating:{language}", _now()))

    def updating(self, language):
        """When Connect's Generate for the language began, or None (none running, or none marked)."""
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (f"generating:{language}",)).fetchone()
        return row[0] if row else None

    def updated(self, language):
        """Connect's Generate ended (or a run found a mark a crash left): the mark cleared."""
        self.conn.execute("DELETE FROM meta WHERE key = ?", (f"generating:{language}",))

    # --- alpha 3 A2: a look working through a language's episodes, for the status record ------------------------ #

    def mark_working(self, language):
        """This look began making the language's episodes' cards (`working:<lang>` in meta): until its pass ends, an
        episode with no reason of its own waits its turn (`status._turns`), also between two episodes."""
        self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (f"working:{language}", _now()))

    def working(self, language):
        """When this look began working through the language's episodes, or None."""
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (f"working:{language}",)).fetchone()
        return row[0] if row else None

    def worked(self, language):
        """The look's pass over the language ended (or a run found a mark a crash left): the mark cleared."""
        self.conn.execute("DELETE FROM meta WHERE key = ?", (f"working:{language}",))

    def start_undo(self, job_id, language, planned, kept):
        """*Undo this batch* about to write Anki (its own transaction): the notes it will delete (`planned`) and those
        it keeps ([[note id, word, why], ...]) -> its id. Written first, so a kill after Anki's delete is finished
        by the next look, never read as cards you deleted (intent keeper P2.5 #4)."""
        with self.transaction():
            cur = self.conn.execute("INSERT INTO undos (job_id, language, at, deleted, kept) VALUES (?, ?, ?, ?, ?)",
                                    (job_id, language, _now(), json.dumps(sorted(planned)),
                                     json.dumps([list(k) for k in kept], ensure_ascii=False)))
            return cur.lastrowid

    def finish_undo(self, undo_id, deleted, kept):
        """The undo done (inside the caller's transaction): the notes gone now, the ones kept."""
        self.conn.execute("UPDATE undos SET deleted = ?, kept = ?, finished_at = ? WHERE id = ?",
                          (json.dumps(sorted(deleted)), json.dumps([list(k) for k in kept], ensure_ascii=False),
                           _now(), undo_id))

    def pending_undos(self, language):
        """Undos a kill left unfinished (Anki may have deleted their notes), oldest first."""
        return self._undo_rows("language = ? AND finished_at IS NULL", (language,))

    def undos(self, job_id):
        return self._undo_rows("job_id = ?", (job_id,))

    def _undo_rows(self, where, params):
        cur = self.conn.execute(f"SELECT * FROM undos WHERE {where} ORDER BY id", params)
        names = [d[0] for d in cur.description]
        out = []
        for r in cur.fetchall():
            row = dict(zip(names, r))
            row["deleted"], row["kept"] = json.loads(row["deleted"]), json.loads(row["kept"])
            out.append(row)
        return out


def stamp():
    """Now in the store's own stamp format (`library_store._now`: microseconds), so the asks watermark and the store's
    `mine_asked` compare as written."""
    t = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".%06dZ" % int((t % 1) * 1e6)


def stamp_key(text):
    """A UTC stamp as a sortable key, whichever format wrote it (the store's microseconds or Connect's seconds):
    `2026-10-15T09:00:00Z` sorts as `…00.000000`."""
    text = str(text or "").rstrip("Z")
    return text if "." in text else text + ".000000"


def asks_from_in(conn, language):
    """The asks watermark read on any connection to the ledger (the window's look opens it read-only), or None."""
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (ASKS_FROM + language,)).fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def ask_recorded_in(conn, language, item_id, asked_at):
    """Does a job of the item hold this very ask (any state: an ask is used up once)? On any connection."""
    try:
        return conn.execute("SELECT 1 FROM jobs WHERE language = ? AND item_id = ? AND asked_at = ? LIMIT 1",
                            (language, item_id, asked_at)).fetchone() is not None
    except sqlite3.Error:
        return False


def _words(text):
    """A job's `words` column -> [(word, reading)], or None (the whole list)."""
    if text is None:
        return None
    try:
        return [(str(w), str(r)) for w, r in json.loads(text)]
    except (ValueError, TypeError):
        return []


def _gap_row(cur, row):
    out = dict(zip([d[0] for d in cur.description], row))
    out["items"] = json.loads(out["items"])
    return out


class _Transaction:
    """BEGIN IMMEDIATE … COMMIT, rolled back on any exception."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.conn.execute("COMMIT")
        else:
            self.conn.execute("ROLLBACK")
        return False
