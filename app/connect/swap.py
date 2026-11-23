"""Swap, the simple version (Kantan-SL, 3.0.18; ROLES.md's *Swap*: gives a card a better sentence — simple: a new card;
the full Swap, 3.1 #385, rewrites the old card in place from the same record). The review loop's ⇄ (Suspend + Green
flag, WL-46b) queues the word (Kyou-LR's `swap_queue`); Swap makes it a NEW card from another line, through Connect's
own maker — a job of kind `swap` (`ledger.SWAP`) that picks, cuts, fills and orders as every Connect card does, and so
waits as every one does (never while you review, the cap, Anki closed): there is no second path into Anki.

- **The one maker** (`make_card`): "a new card for this word from another line" — the swap queue's entries and Kyou-DW's
  *Bad card* both call it. It records the ask (Connect's ledger, table `swaps`) and wakes Connect; Connect's next look
  (`look`) turns it into a job. Never for a word now Known or Ignored (`word_state`: the entry dropped, with why).
- **The line** (`choose_line`): the line the learner picked (`line_id`), else **only the one picker's** (Kantan-SD's
  `sentences.choose`, over Generate's list: Swap ranks and searches nothing itself) whose episode Connect can cut —
  **never a line the old card holds** (the picker's `sentences.same_line`, by its text: the old card's sentence from Connect's record, else
  from Anki). No picker yet, or no other line: the ask waits, said once on *Needs you* (`WAITS`), and is looked at
  again when the library has changed (`RETRY_S`).
- **Made:** the swap queue's entry marked made with the new note (`swap_queue.made`: the pair old note → new note, the
  record the full Swap reads); the old card stays as the learner left it (suspended, green) and gains the tag
  `surasura::swapped` (`SWAP_TAG`) — Swap's only write to it. Said on *Needs you*: *A new card for 「…」 · Undo · OK*.
  **The journey's ⇄** (`BY_JOURNEY`) is the same ask from the page, so it is one out, one in too: once its new card is
  made (never at the press), Swap suspends the old card's cards still in reviews, as the learner would have, through
  the shelf's writer (`JOURNEY_TAKES_OLD`, `_take_old`: the cards it took recorded first, `took`), and never flags them.
- **The cap:** the swap's job carries its time as an ask (`asked_at`): never held by the cap, the learner's move is the
  yes — the old card left the count when it was suspended, the new one counts as any Connect card (one out, one in).
  Tidy never takes it by itself: you asked for it (`new_cards`, read by `tidy.asked_for`); only its Undo does.
- **Undo** (`undo`): the new card removed with a backup, as Tidy removes one (`tidy.run`, why `swap`: notes, media and
  an Anki package kept; a card you studied or changed stays, and then nothing is undone), the old card unsuspended,
  its Swap flag off (the learner's pick, `review_loop.move_flags`) and its tag gone — a journey ⇄'s old card gets
  back only the cards the press took (`took`), its flags untouched: as it was before the press —, then the queue's entry `undone`
  (`swap_queue.undone`) with the ledger's row in one step. Twice: nothing more.

**The one record of a swap is the swap queue's entry** (waiting · made · dropped · undone, with why). The ledger's
`swaps` holds what Connect's job needs (the line, what to avoid, the episodes tried, the job, the new note, the tag
written, the backup), keyed by the entry's id (`ref`); its `state` is the job's phase — asked → queued (its job) →
waits (no other line) — and, once over, the queue's outcome copied (made · dropped · undone, with the queue's why),
written with the queue's in one step (Undo: the queue's write inside the ledger's transaction) or followed from the
queue at every look (`_follow`: an entry the reader dropped — taken back, its sync undone — or a write that failed
half-way). An ask with no queue entry (`ref` None) has the ledger's record only.
Qt-free; Anki only through the adapter handed in (tests hand a fake).
Qt-free; Anki only through the adapter handed in (tests hand a fake).
"""
import datetime
import json
import logging
import os
import re
import time

from app.connect import sentences, swap_queue, tidy

log = logging.getLogger("surasura-cli")

SWAP_TAG = "surasura::swapped"
BY_SWAP, BY_BAD_CARD = "swap", "bad card"
BY_JOURNEY, BY_ADD_NOW = "journey", "add now"   # the journey page's ⇄ and *Add now* (`door_routes`): the line pressed
JOURNEY_TAKES_OLD = True        # a journey ⇄ is one out, one in: its old card suspended once the new one is made (the
                                # lead's ruling, PROVISIONAL — OPEN-FOR-SONIC 72 a); False: two cards, the old one tagged only
ASKED, QUEUED, MADE, WAITS, DROPPED, UNDONE = "asked", "queued", "made", "waits", "dropped", "undone"
TRIES = 3                       # episodes tried before an ask waits (each cut no card: its lines were the old card's)
RETRY_S = 6 * 3600              # a waiting ask is looked at again this long after, or when the library has more files
GREEN = 3                       # Anki's flag numbers: 3 green (Swap's move by default: the learner's pick is
                                # `review_loop.move_flags`), 0 none
VERB = "Swap"
NO_LINE = "no other line"
GONE = "That swap can't be undone now."
ALREADY = "That swap is undone already."
NOT_MADE = "That swap's card isn't made yet."
KEPT = "The new card stays: you've studied or changed it."

_SQL = """CREATE TABLE IF NOT EXISTS swaps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  language TEXT NOT NULL,
  word TEXT NOT NULL,
  reading TEXT NOT NULL DEFAULT '',
  old_note INTEGER,
  old_card INTEGER,
  line_id TEXT,
  ref TEXT,
  by TEXT NOT NULL,
  state TEXT NOT NULL,
  why TEXT,
  item_id INTEGER,
  line TEXT,
  avoid TEXT,
  tried TEXT,
  job_id INTEGER,
  new_note INTEGER,
  tagged INTEGER NOT NULL DEFAULT 0,
  at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  tried_at REAL,
  tried_files INTEGER,
  tidy_id INTEGER,
  took TEXT)"""


def ensure(ledger):
    ledger.conn.execute(_SQL)
    if "took" not in {r[1] for r in ledger.conn.execute("PRAGMA table_info(swaps)")}:
        ledger.conn.execute("ALTER TABLE swaps ADD COLUMN took TEXT")   # a journey ⇄'s cards it suspended (JSON ids)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_cards(ledger, language, note_ids):
    """The notes of `note_ids` that are a made swap's new card (the ledger's `swaps`, state made) -> frozenset; none
    before any swap was asked. Tidy's `asked_for` reads it: your green flag asked for that card."""
    ids = {int(n) for n in note_ids}
    if not ids or not ledger.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'swaps'"
                                          ).fetchone():
        return frozenset()
    return frozenset(int(n) for (n,) in ledger.conn.execute(
        "SELECT DISTINCT new_note FROM swaps WHERE language = ? AND state = ? AND new_note IS NOT NULL",
        (language, MADE)) if int(n) in ids)


def _rows(ledger, where, params=()):
    cur = ledger.conn.execute(f"SELECT * FROM swaps WHERE {where} ORDER BY id", params)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def _set(ledger, swap_id, **values):
    with ledger.transaction():
        _update(ledger.conn, swap_id, **values)


def _update(conn, swap_id, **values):
    """`_set` inside a transaction the caller holds."""
    values["updated_at"] = _now()
    conn.execute(f"UPDATE swaps SET {', '.join(f'{k} = ?' for k in values)} WHERE id = ?",
                 list(values.values()) + [swap_id])


def _same_word(a, b):
    """Two swaps of one word: the same lemma, and the same reading where both say one (生 なま is not 生 せい)."""
    return a["word"] == b["word"] and (not a.get("reading") or not b.get("reading") or a["reading"] == b["reading"])


def line_id(item_id, start_s):
    """A line's id, as the journey's door and the swap queue carry it: `<item id>:<start ms>` (PROVISIONAL)."""
    return f"{int(item_id)}:{int(round(float(start_s) * 1000))}"


def _parse_line_id(text):
    m = re.fullmatch(r"\s*(\d+):(\d+)\s*", str(text or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


# --------------------------------------------------------------------------- #
# Known · Ignored
# --------------------------------------------------------------------------- #
def states(language):
    """A word -> "ignored" (on your Ignore list), "known" (known by the analyzer's rule: the pick's own test), or None;
    the lists read once (one look's)."""
    from app import settings_manager
    from app.cli import verbs
    loaded = settings_manager.load_settings()
    tokenizer, script = verbs._reading(loaded, language)
    ignored = verbs._ignored(language, script)
    known = verbs._known_test(language, tokenizer, script)
    return lambda word, reading="": "ignored" if word in ignored else ("known" if known((word, reading or "")) else None)


def word_state(language, word, reading=None):
    """`states` for one word."""
    return states(language)(word, reading or "")


# --------------------------------------------------------------------------- #
# The one maker
# --------------------------------------------------------------------------- #
def make_card(language, word, reading=None, old_note=None, old_card=None, line_id=None, by=BY_SWAP, ref=None,
              ledger=None, wake=True, state_of=None):
    """**A new card for this word from another line** — the one function the swap queue (`look`) and Kyou-DW's *Bad
    card* call. `old_note` / `old_card`: the card it replaces (its line is never used; a deleted one's line too, from
    Connect's record); `line_id`: the line the learner picked (`line_id()`'s form), else Swap picks; `ref`: the swap
    queue's entry id (one ask an entry). Records the ask and wakes Connect (`wake`) -> {"id", "state", "why"}:
    `asked` (Connect makes it at its next look), `dropped` with why "known" / "ignored" (nothing asked; a queue entry
    dropped with that why), or the ask already recorded for `ref` (`new` False). `state_of`: `states`' tester."""
    from app.connect import ledger as ledger_mod
    own = ledger is None
    ledger = ledger or ledger_mod.Ledger()
    try:
        ensure(ledger)
        if ref is not None:
            had = _rows(ledger, "language = ? AND ref = ?", (language, str(ref)))
            if had:
                last = had[-1]
                if last["state"] == DROPPED:            # the queue's entry still waits: its earlier write failed
                    _queue_drop(language, ref, last["why"])     # (only a waiting entry moves: idempotent)
                elif last["state"] in (MADE, UNDONE) and last.get("new_note"):
                    _queue_made(language, ref, last["new_note"])
                return {"id": last["id"], "state": last["state"], "why": last["why"], "new": False}
        why = state_of(word, reading or "") if state_of is not None else word_state(language, word, reading)
        now = _now()
        with ledger.transaction():
            cur = ledger.conn.execute(
                "INSERT INTO swaps (language, word, reading, old_note, old_card, line_id, ref, by, state, why, at, "
                "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (language, str(word), str(reading or ""), _int(old_note), _int(old_card), line_id,
                 None if ref is None else str(ref), by, DROPPED if why else ASKED, why, now, now))
            swap_id = cur.lastrowid
    finally:
        if own:
            ledger.close()
    if why:
        _queue_drop(language, ref, why)
    elif wake:
        try:
            from app.connect import kick
            kick.wake()
        except Exception:
            log.info("Swap: Connect wasn't woken (it reads the ask at its next look)", exc_info=True)
    return {"id": swap_id, "state": DROPPED if why else ASKED, "why": why, "new": True}


def _int(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _queue_drop(language, ref, why):
    if ref is None:
        return
    try:
        swap_queue.drop(language, str(ref), why)
    except Exception:
        log.warning("Swap: the swap queue's entry %s wasn't dropped (%s)", ref, why, exc_info=True)


def _queue_made(language, ref, note):
    if ref is None:
        return
    try:
        swap_queue.made(language, str(ref), int(note))
    except Exception:
        log.warning("Swap: the swap queue's entry %s wasn't marked made", ref, exc_info=True)


# --------------------------------------------------------------------------- #
# The line (the one seam until Kantan-SD's picker)
# --------------------------------------------------------------------------- #
def choose_line(language, word, avoid=(), reachable=None, skip_items=(), reading=None):
    """The word's other line -> (item id, line text), or None: **only the one picker's** (Kantan-SD's
    `sentences.choose`, over Generate's list, the one source of a word's sentences) — never one `sentences.same_line` finds in
    `avoid`, never an item of `skip_items`, only one `reachable(item id)` says Connect can cut. Swap has no ranking or
    search of its own: no picker yet, or nothing it offers, is None (the swap waits, as for a word with one line)."""
    return _chosen(language, {(word, reading or "")}, avoid, None, set(skip_items or ()), reachable)


def _picker():
    """Kantan-SD's one picker (`app/connect/sentences.py`): the one seam Swap's choice goes through (a test hands
    None: no picker, the swap waits)."""
    return sentences


def _chosen(language, keys, avoid, files, bad, reachable):
    """The picker's best line for the word -> (item id, text), or None (no picker, nothing it can offer, an error)."""
    picker = _picker()
    if picker is None:
        return None

    def reach(item):
        return item is not None and item not in bad and (reachable is None or bool(reachable(item)))
    try:
        ranked = picker.choose(language, sorted(keys), never={k: set(avoid) for k in keys}, files=files,
                               reach=reach)
    except Exception:
        log.info("Swap: the sentence picker didn't answer for a word; the swap waits", exc_info=True)
        return None
    for key in sorted(keys):
        for c in ranked.get(key) or ():
            if c.item_id is not None and c.item_id not in bad and not sentences.same_line(c.text, avoid):
                return c.item_id, c.text
    return None


def _resolve_line_id(steps, language, text):
    """The learner's picked line -> (item id, its text), or None when it no longer exists (the item gone, its subtitle
    gone or re-timed past it)."""
    got = _parse_line_id(text)
    if got is None:
        return None
    item_id, ms = got
    try:
        subtitle = steps.subtitle(language, {"id": 0, "item_id": item_id})
        if not subtitle or not os.path.isfile(subtitle):
            return None
        from app import cues
        from app.cues import seconds
        for cue in cues.read(subtitle, language):
            if abs(int(round(seconds(cue.start) * 1000)) - ms) <= 5:
                return item_id, cue.text
    except Exception:
        log.info("Swap: a picked line couldn't be read", exc_info=True)
    return None


# --------------------------------------------------------------------------- #
# The old card's line
# --------------------------------------------------------------------------- #
def _old_lines(ledger, row, anki=None):
    """The old card's sentence(s): Connect's record of the note (`outcomes`), else the note's Sentence field in Anki (a
    card Connect didn't make); [] when neither has one (a deleted card Connect didn't make), None when Anki can't be read
    now: the swap then waits for a look that can (never a new card with nothing to avoid)."""
    out = []
    note = row.get("old_note")
    if note is not None:
        out = [r[0] for r in ledger.conn.execute("SELECT sentence FROM outcomes WHERE note_id = ? AND outcome = 'made' "
                                                 "AND sentence IS NOT NULL", (int(note),)) if r[0]]
        if not out and anki is None:
            return None
        if not out:
            try:
                for info in anki.notes([int(note)]) or ():
                    fields = info.get("fields") or {}
                    names = sorted(fields, key=lambda n: (n.lower() != "sentence", n))
                    for name in names:
                        low = name.lower()
                        if "sentence" in low and not any(x in low for x in ("audio", "furigana", "translat", "hint")):
                            value = fields[name].get("value") if isinstance(fields[name], dict) else fields[name]
                            if value:
                                out.append(value)
                                break
            except Exception:
                log.info("Swap: the old card's sentence couldn't be read from Anki", exc_info=True)
                return None
    return out


def _avoid(ledger, row, anki=None):
    """Every line the swap's new card must not be cut from: its old card's, and those of the other asks of the same word
    still open (one new card serves them all) -> a list, or None while one of them can't be read."""
    out = []
    rows = [row] + [r for r in _rows(ledger, "language = ? AND word = ? AND state IN (?, ?) AND id != ?",
                                     (row["language"], row["word"], ASKED, WAITS, row["id"])) if _same_word(r, row)]
    for r in rows:
        lines = json.loads(r["avoid"]) if r.get("avoid") else _old_lines(ledger, r, anki)
        if lines is None:
            return None
        out += [x for x in lines if x not in out]
    return out


# --------------------------------------------------------------------------- #
# Connect's look (the runner calls it before its jobs and after a swap's job)
# --------------------------------------------------------------------------- #
def look(steps, ledger, language, store_id=None, anki=None, files=None):
    """One look: the swaps whose job ended finished (`_finish`), the swap queue's new entries asked (`make_card`), each
    ask turned into a job (`_start`), the old cards' tags written where they wait. Never raises: a swap that can't go
    now is looked at again. -> {"queued", "made", "waits", "dropped"} counts."""
    out = {"queued": 0, "made": 0, "waits": 0, "dropped": 0}
    entries = _entries(language)
    waiting = [e for e in (entries or {}).values() if e.get("state") == swap_queue.WAITING]
    if not waiting and not ledger.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'swaps'"
                                               ).fetchone():
        return out                          # nothing ever asked: an idle look writes nothing (S19)
    ensure(ledger)
    anki = anki if anki is not None else _anki(steps)
    _follow(ledger, language, entries)
    for row in _rows(ledger, "language = ? AND state = ?", (language, QUEUED)):
        try:
            _finish(ledger, language, row, out, anki=anki)
        except Exception:
            log.warning("Swap: swap %s wasn't finished this look", row["id"], exc_info=True)
    state_of = None
    for entry in waiting:
        try:
            state_of = state_of or states(language)
            got = make_card(language, entry.get("word"), old_note=entry.get("note"), old_card=entry.get("card"),
                            line_id=entry.get("line_id"), ref=entry.get("id"), ledger=ledger, wake=False,
                            state_of=state_of)
            out["dropped"] += int(got["new"] and got["state"] == DROPPED)
        except Exception:
            log.warning("Swap: a swap queue entry wasn't read (%s)", entry.get("id"), exc_info=True)
    count = files                           # the library's file count, read once a look (when a wait needs it)
    for row in _rows(ledger, "language = ? AND state IN (?, ?)", (language, ASKED, WAITS)):
        if row["state"] == WAITS:
            if count is None:
                count = _file_count(language) if files is None else files
            if not _due(row, count):
                continue
        try:
            state_of = state_of or states(language)
            _start(steps, ledger, language, row, store_id, anki, out, count, state_of)
        except Exception:
            log.warning("Swap: swap %s wasn't started this look", row["id"], exc_info=True)
    if out["made"]:
        _follow(ledger, language, _entries(language))  # a swap taken back while its job ran: never tagged
    _tag_waiting(ledger, language, anki)
    return out


def _entries(language):
    """The swap queue's entries by id, or None when it can't be read (the look then follows nothing)."""
    try:
        return {str(e.get("id")): e for e in swap_queue.load(language)}
    except Exception:
        log.info("Swap: the swap queue couldn't be read this look", exc_info=True)
        return None


def _follow(ledger, language, entries):
    """The ledger follows the queue, the one record: an entry dropped (the reader: taken back, its sync undone) drops an
    ask not now a job's and a made one; an entry undone undoes a made one; a ledger outcome the queue didn't take (its
    write failed) is written to it again (a waiting entry: `make_card`'s look; a made one: here, `undone`). A swap
    whose job is running is followed when the job ends (Connect never stops a mining job)."""
    if not entries:
        return
    for row in _rows(ledger, "language = ? AND ref IS NOT NULL AND state != ?", (language, QUEUED)):
        e = entries.get(str(row["ref"]))
        if e is None:
            continue
        q = e.get("state")
        if q == swap_queue.DROPPED and row["state"] != DROPPED:
            _set(ledger, row["id"], state=DROPPED, why=e.get("why"))
        elif q == swap_queue.UNDONE and row["state"] != UNDONE:
            _set(ledger, row["id"], state=UNDONE)
        elif q == swap_queue.MADE and row["state"] == UNDONE:
            try:
                swap_queue.undone(language, str(row["ref"]))
            except Exception:
                log.warning("Swap: the swap queue's entry %s wasn't marked undone", row["ref"], exc_info=True)


def _anki(steps):
    url = getattr(steps, "url", None)
    if not url:
        return None
    return AnkiSwap(url)


def _file_count(language):
    try:
        from app import sentence_corpus
        return len(sentence_corpus.library_files(language))
    except Exception:
        return None


def _due(row, count):
    """A waiting ask is looked at again once RETRY_S has passed or the library holds another number of files."""
    if row.get("tried_at") is None:
        return True
    if count is not None and row.get("tried_files") is not None and count != row["tried_files"]:
        return True
    return time.time() - float(row["tried_at"]) >= RETRY_S


def _start(steps, ledger, language, row, store_id, anki, out, count=None, state_of=None):
    from app.connect import ledger as ledger_mod
    why = (state_of or states(language))(row["word"], row.get("reading") or "")
    if why:
        _set(ledger, row["id"], state=DROPPED, why=why)
        _queue_drop(language, row["ref"], why)
        out["dropped"] += 1
        return
    if any(_same_word(r, row) for r in _rows(ledger, "language = ? AND word = ? AND state = ? AND id != ?",
                                             (language, row["word"], QUEUED, row["id"]))):
        return                              # two greens for one word: the first's card serves both (`_finish`)
    avoid = _avoid(ledger, row, anki)
    if avoid is None:
        return                              # an old card's sentence can't be read now: the next look
    tried = json.loads(row["tried"]) if row.get("tried") else []
    picked = _resolve_line_id(steps, language, row["line_id"]) if row.get("line_id") else None
    if picked is not None and (sentences.same_line(picked[1], avoid) or picked[0] in tried):
        picked = None                       # never the old card's line, even picked
    if picked is None:
        def reachable(item):
            job = {"id": 0, "item_id": item, "kind": ledger_mod.SWAP}
            try:
                return bool(steps.video(language, job) or steps.reading(language, job))
            except Exception:
                return False
        picked = choose_line(language, row["word"], avoid, reachable, skip_items=tried, reading=row.get("reading"))
    if picked is None:
        _set(ledger, row["id"], state=WAITS, why=NO_LINE, avoid=json.dumps(avoid, ensure_ascii=False),
             tried_at=time.time(), tried_files=count if count is not None else _file_count(language))
        out["waits"] += 1
        return
    item_id, text = picked
    with ledger.transaction():              # the job and its swap together: a job of kind swap never without its record
        job_id = ledger.queue_swap(language, item_id, row["word"], row.get("reading") or "", row["at"],
                                   store_id=store_id)
        if job_id is not None:
            _update(ledger.conn, row["id"], state=QUEUED, why=None, item_id=item_id, line=text, job_id=job_id,
                    avoid=json.dumps(avoid, ensure_ascii=False))
    if job_id is None:
        return                              # the episode has an open job: tried again after it
    out["queued"] += 1


def _finish(ledger, language, row, out, state_of=None, anki=None):
    from app.connect.ledger import OPEN
    job = ledger.job_by_id(row["job_id"]) if row.get("job_id") else None
    if job is not None and job.get("state") in OPEN:
        return
    note = None
    if job is not None:
        for o in ledger.outcomes(job["id"]):
            if o.get("outcome") == "made" and o.get("note_id") and o.get("word") == row["word"]:
                note = int(o["note_id"])
    if note is not None:
        # another ask of the same word shares its card, unless the card's line is that ask's own old card's, or can't be
        # read now (it then gets its own job: never the same line)
        twins = [row]
        for r in _rows(ledger, "language = ? AND word = ? AND state IN (?, ?) AND id != ?",
                       (language, row["word"], ASKED, WAITS, row["id"])):
            lines = json.loads(r["avoid"]) if r.get("avoid") else _old_lines(ledger, r, anki)
            if _same_word(r, row) and lines is not None and not sentences.same_line(row.get("line") or "", lines):
                twins.append(r)
        for r in twins:
            _set(ledger, r["id"], state=MADE, why=None, new_note=note, job_id=row["job_id"], item_id=row["item_id"],
                 line=row["line"])
            _queue_made(language, r["ref"], note)
            out["made"] += 1
        return
    why = (state_of or states(language))(row["word"], row.get("reading") or "")
    if why:
        _set(ledger, row["id"], state=DROPPED, why=why)
        _queue_drop(language, row["ref"], why)
        out["dropped"] += 1
        return
    # no card cut from that episode (its lines were the old card's, sung, unsure; the job failed or was dropped):
    # another episode next look — after TRIES of them, the ask waits
    tried = (json.loads(row["tried"]) if row.get("tried") else []) + [row["item_id"]]
    state = WAITS if len(tried) >= TRIES else ASKED
    _set(ledger, row["id"], state=state, why=NO_LINE if state == WAITS else None, tried=json.dumps(tried),
         job_id=None, tried_at=time.time() if state == WAITS else None)
    out["waits"] += int(state == WAITS)


def _tag_waiting(ledger, language, anki):
    """The old cards of made swaps tagged `SWAP_TAG` (Swap's only write to them), under Anki's write lock and never while
    you review; Anki closed or busy: looked at again. A deleted old card: nothing to tag."""
    where = ("language = ? AND state = ? AND tagged = 0", (language, MADE))
    if anki is None or not _rows(ledger, *where):
        return
    try:
        with anki.writer(VERB):
            if anki.reviewing():
                return
            rows = _rows(ledger, *where)    # again under the lock: an Undo that held it may have undone one
            notes = sorted({int(r["old_note"]) for r in rows if r.get("old_note")})
            infos = [n for n in anki.notes(notes) if isinstance(n, dict) and n.get("noteId")] if notes else []
            have = {int(n["noteId"]) for n in infos}
            for r in rows:
                if r.get("by") == BY_JOURNEY and JOURNEY_TAKES_OLD:
                    _take_old(anki, ledger, r, infos)
            if have:
                anki.add_tags(sorted(have), SWAP_TAG)
    except Exception:
        log.info("Swap: the old cards weren't tagged this look", exc_info=True)
        return
    for r in rows:
        _set(ledger, r["id"], tagged=1)


def _take_old(anki, ledger, row, infos):
    """A journey ⇄'s old card out of reviews (one out, one in), under the caller's write lock: its cards in reviews now
    are added to the record first (`took`: a retry after a failed write keeps the cards it suspended), then suspended
    through Junban's door. A card the learner had suspended isn't taken, so Undo leaves it so."""
    cards = [int(c) for n in infos if int(n["noteId"]) == int(row["old_note"] or 0) for c in n.get("cards") or ()]
    now = {int(c["cardId"]) for c in (anki.cards(cards) if cards else [])
           if isinstance(c, dict) and c.get("cardId") and c.get("queue") != -1}
    took = sorted(set(_took(row)) | now)
    if row.get("took") is None or now - set(_took(row)):
        _set(ledger, row["id"], took=json.dumps(took))
        row["took"] = json.dumps(took)
    if took:
        anki.suspend(took)


# --------------------------------------------------------------------------- #
# Anki
# --------------------------------------------------------------------------- #
class AnkiSwap(tidy.AnkiConnectTidy):
    """Swap's Anki: Tidy's adapter (reads, the writer, the package backup) plus tags, unsuspend and the flag."""

    def add_tags(self, note_ids, tag):
        from app import anki_connect
        anki_connect.invoke("addTags", self.url, notes=list(note_ids), tags=tag)

    def remove_tags(self, note_ids, tag):
        from app import anki_connect
        anki_connect.invoke("removeTags", self.url, notes=list(note_ids), tags=tag)

    def suspend(self, card_ids):
        """A journey ⇄'s old card out of reviews, through the app's one suspend door (Junban's `ankiconnect.suspend`,
        the shelf's adapter's too); a card Anki didn't take raises, so the look tries again."""
        from app import anki_connect
        from modules.junban import ankiconnect
        failures = (ankiconnect.suspend(self.url, card_ids) or ((), ()))[1]
        if failures:
            raise anki_connect.AnkiError(f"Anki didn't take suspend for {len(failures)}: {failures[0][1]}")

    def unsuspend(self, card_ids):
        from app import anki_connect
        anki_connect.invoke("unsuspend", self.url, cards=list(card_ids))

    def set_flag(self, card_ids, flag):
        from app import anki_connect
        for card in card_ids:
            got = anki_connect.invoke("setSpecificValueOfCard", self.url, card=int(card), keys=["flags"],
                                      newValues=[int(flag)])
            if got != [True]:
                raise anki_connect.AnkiError(f"Anki didn't change the card's flag ({got!r})")


# --------------------------------------------------------------------------- #
# Undo
# --------------------------------------------------------------------------- #
def undo(anki, ledger, language, swap_id, open_store=None, ours=None, flag=GREEN):
    """One swap undone -> {"undone": True, "word"}: the new card removed with a backup (`tidy.run`, why "swap": a card
    you studied or changed stays — moved to a deck of your own too — `tidy.Refused`, and nothing here changes), then
    the old card back to study (unsuspended, its Swap flag off — `flag`, the learner's pick — `SWAP_TAG` gone; a
    journey ⇄'s: only the cards its press took, no flag; while another made swap keeps it out, none: `_old_back`), then
    the swap `undone` in the queue and the ledger together (the queue's write fails: neither changes, and a retry
    finishes it — the new card isn't deleted twice). `ours`: the deck Surasura shows for the language's new cards (`fields.surasura_deck`), handed to
    Tidy as an ordinary tidy hands it — a card with no home on record is Surasura's only there. Refused (`Refused`)
    when it isn't made or is undone already (the queue's word first); Anki's Reviewing / Busy / errors, and a queue
    that can't be read or written, raise as Tidy's do."""
    ensure(ledger)
    rows = _rows(ledger, "id = ? AND language = ?", (int(swap_id), language))
    if not rows:
        raise tidy.Refused(GONE)
    row = rows[0]
    entry = _entry(language, row)
    if entry is not None and entry.get("state") == swap_queue.UNDONE and row["state"] != UNDONE:
        _set(ledger, row["id"], state=UNDONE)               # the ledger follows the queue (its write failed after)
        row["state"] = UNDONE
    if row["state"] == UNDONE:
        raise tidy.Refused(ALREADY)
    if row["state"] != MADE or not row.get("new_note") or (entry or {}).get("state") == swap_queue.DROPPED:
        raise tidy.Refused(NOT_MADE)
    if entry is not None and entry.get("state") == swap_queue.WAITING:
        _queue_made(language, row["ref"], row["new_note"])  # the queue's made write had failed: it takes it first
    others = _rows(ledger, "language = ? AND new_note = ? AND state = ? AND id != ?",
                   (language, row["new_note"], MADE, row["id"]))
    gone = not any(isinstance(n, dict) and n.get("noteId") for n in anki.notes([int(row["new_note"])]) or ())
    if not others and not row.get("tidy_id") and not gone:     # a card two greens share goes with the last of them;
        try:                                                    # one you deleted yourself: nothing to delete
            tidied = tidy.run(anki, ledger, language, [int(row["new_note"])], why=BY_SWAP, open_store=open_store,
                              ours=ours)
        except tidy.Refused as e:
            raise tidy.Refused(KEPT if e.say == tidy.ALL_KEPT else e.say) from None
        _set(ledger, row["id"], tidy_id=tidied.get("id"))   # a retry after the old card's write failed skips it
    with anki.writer(VERB):
        if anki.reviewing():
            raise tidy.Reviewing()
        row = _rows(ledger, "id = ?", (row["id"],))[0]     # again under the lock: a look in the gap may have taken it
        still = _rows(ledger, "language = ? AND old_note = ? AND state = ? AND id != ?",
                      (language, row["old_note"], MADE, row["id"]))
        journey = [r for r in still if r.get("by") == BY_JOURNEY]
        took = _took(row) if row.get("by") == BY_JOURNEY else None
        back = _old_back(anki, row, keep_tag=bool(still), flag=flag, took=took,
                         hold=bool(still) if took is not None else bool(journey))
        with ledger.transaction():      # under the lock (a look never tags it again), the queue's write inside the
            _update(ledger.conn, row["id"], state=UNDONE)       # ledger's: either fails, neither changes
            if journey and back:        # a journey ⇄ still holds the old card out: these go back with its Undo
                _update(ledger.conn, journey[-1]["id"], took=json.dumps(sorted(set(back) | set(_took(journey[-1])))))
            if entry is not None:
                if swap_queue.undone(language, str(row["ref"])) is None:
                    raise RuntimeError(f"the swap queue's entry {row['ref']} isn't made: nothing was undone there")
    return {"undone": True, "word": row["word"]}


def _entry(language, row):
    """The swap's queue entry, or None (an ask with no entry); raises when the queue can't be read (an Undo then
    changes nothing: it can't keep the one record)."""
    if row.get("ref") is None:
        return None
    return next((e for e in swap_queue.load(language) if str(e.get("id")) == str(row["ref"])), None)


def _took(row):
    return [int(c) for c in json.loads(row["took"])] if row.get("took") else []


def _old_back(anki, row, keep_tag=False, flag=GREEN, took=None, hold=False):
    """The old card back as the swap found it, `SWAP_TAG` gone -> the suspended cards it puts back. The loop's move
    (`took` None) took it out of reviews: unsuspended, its Swap flag off. A journey ⇄ (`took`: the cards its press
    suspended) gets back only those, no flag changed: a card the learner had put away stays so. `hold`: another made
    swap still keeps the card out (its Undo puts them back: `undo` hands a journey ⇄ the list), so none unsuspended."""
    cards = [int(row["old_card"])] if row.get("old_card") else []
    if row.get("old_note") and not cards:
        for info in anki.notes([int(row["old_note"])]) or ():
            cards = [int(c) for c in info.get("cards") or ()]
    infos = [c for c in (anki.cards(cards) if cards else []) if isinstance(c, dict) and c.get("cardId")]
    back = [int(c["cardId"]) for c in infos if c.get("queue") == -1 and (took is None or int(c["cardId"]) in took)]
    flagged = [int(c["cardId"]) for c in infos if c.get("flags") == flag] if took is None else []
    if back and not hold:
        anki.unsuspend(back)
    if flagged:
        anki.set_flag(flagged, 0)
    if row.get("old_note") and infos and not keep_tag:      # the note's other card still swapped: its tag stays
        anki.remove_tags([int(row["old_note"])], SWAP_TAG)
    return back


def act_undo(settings, language, swap_id):
    """*Undo* on a swap (Needs you) -> {"undone": True} or {"why": plain words}; anything else (a disk or ledger error)
    raises to the window's press, which says it failed."""
    from app import anki_connect, locks
    from app.connect import fields, library, review_loop
    from app.connect.ledger import Ledger, TooNew, path
    from app.connect.undo import NO_ANKI, NO_LEDGER, Reviewing
    if os.environ.get("SURASURA_NO_ANKI_SYNC"):
        return {"why": NO_ANKI}
    if not os.path.exists(path()):
        return {"why": NO_LEDGER}
    try:
        with Ledger() as ledger:
            return undo(AnkiSwap(anki_connect.address(settings)), ledger, language, swap_id,
                        lambda: library.open_store(language), ours=fields.surasura_deck(settings, language),
                        flag=review_loop.move_flags(settings)[review_loop.SWAP])
    except tidy.Refused as e:
        return {"why": e.say}
    except Reviewing:
        return {"why": anki_connect.REVIEWING}
    except locks.Busy as e:
        return {"why": anki_connect.busy_message(e)}
    except anki_connect.AnkiError as e:
        return {"why": f"Anki didn't answer ({e})."}
    except TooNew as e:
        return {"why": str(e)}


# --------------------------------------------------------------------------- #
# Read-only: the pick's spec, the window's record
# --------------------------------------------------------------------------- #
def spec_of(job_id, language):
    """`pick`'s `swap` for Connect's job `job_id` (a job of kind `swap` of `language`), or None. Read-only (a pick never
    writes Connect's ledger); raises sqlite3.Error when the ledger can't be read."""
    import sqlite3
    from app.connect import ledger as ledger_mod
    if not os.path.exists(ledger_mod.path()):
        return None
    conn = sqlite3.connect(f"file:{ledger_mod.path()}?mode=ro", uri=True, timeout=5.0)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'swaps'").fetchone():
            return None
        if (conn.execute("SELECT kind FROM jobs WHERE id = ? AND language = ?", (job_id, language)).fetchone()
                or (None,))[0] != ledger_mod.SWAP:
            return None
        row = conn.execute("SELECT word, reading, avoid, line FROM swaps WHERE job_id = ? AND language = ? "
                           "ORDER BY id DESC LIMIT 1", (job_id, language)).fetchone()
    finally:
        conn.close()
    if row is None:
        return {"word": "", "reading": "", "avoid": [], "line": None}     # a swap job with no record: nothing to send
    word, reading, avoid, line = row
    return {"word": word, "reading": reading or "", "avoid": json.loads(avoid) if avoid else [], "line": line}


def status_of(conn, language, newest=5):
    """The window's record (Connect's status, *Needs you*): {"made": [{"id", "word", "at"}] (the newest made swaps not
    undone, newest first), "waits": [{"id", "word"}] (the asks with no other line)} — read-only on `conn`."""
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'swaps'").fetchone():
            return {"made": [], "waits": []}
        made = [{"id": r[0], "word": r[1], "at": r[2]} for r in conn.execute(
            "SELECT id, word, updated_at FROM swaps WHERE language = ? AND state = ? ORDER BY id DESC LIMIT ?",
            (language, MADE, int(newest)))]
        waits = [{"id": r[0], "word": r[1]} for r in conn.execute(
            "SELECT id, word FROM swaps WHERE language = ? AND state = ? ORDER BY id", (language, WAITS))]
    except Exception:
        return {"made": [], "waits": []}
    return {"made": made, "waits": waits}
