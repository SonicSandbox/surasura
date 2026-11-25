"""Swap, the simple version (Kantan-SL, 3.0.18; ROLES.md's *Swap*: gives a card a better sentence — simple: a new card;
the full Swap, 3.1 #385, rewrites the old card in place from the same record). The review loop's ⇄ (Suspend + Green
flag, WL-46b) queues the word (Kyou-LR's `swap_queue`); Swap makes it a NEW card from another line, through Connect's
own maker — a job of kind `swap` (`ledger.SWAP`) that picks, cuts, fills and orders as every Connect card does, and so
waits as every one does (never while you review, the cap, Anki closed): there is no second path into Anki — **but
one, named** (AM-FIX, the lead's ruling 1, 2026-11-23): when the old card is of the note type Connect's cards are
made in, Anki Miner's `mine` refuses the new card as the old card's duplicate (its check before adding: 3.13 and 3.5.0
alike), so that card is added here, beside the old one (`add_new_card`: the old card's word side, `render`'s sentence side for the
new line, AnkiConnect `addNote` with the duplicate allowed) — through Connect's own AnkiConnect writer
(`app/anki_connect.py`, the field writer's lock), never a transport of its own, and in the same job, so it waits as
any card does. An Anki Miner without `render` (older than 3.11) can't make that card: the swap waits on *Needs you*'s
*Update Anki Miner to swap this card's sentence* (`UPDATE_TO_SWAP`), which leads to Connect's update offer.

- **The one maker** (`make_card`): "a new card for this word from another line" — the swap queue's entries and Kyou-DW's
  *Bad card* both call it. It records the ask (Connect's ledger, table `swaps`) and wakes Connect; Connect's next look
  (`look`) turns it into a job. Never for a word now Known or Ignored (`word_state`: the entry dropped, with why).
- **The line** (`choose_line`): the line the learner picked (`line_id`), else **only the one picker's** (Kantan-SD's
  `sentences.choose`, over Generate's list: Swap ranks and searches nothing itself) whose episode Connect can cut —
  **never a line the old card holds** (the picker's `sentences.same_line`, by its text: the old card's sentence from Connect's record, else
  from Anki). No picker yet, or no other line: the ask waits, said once on *Needs you* (`WAITS`), and is looked at
  again when the library has changed (`RETRY_S`).
- **Made** (by the job's `mine`, or beside the old card — `add_new_card`, above): the swap queue's entry marked made
  with the new note (`swap_queue.made`: the pair old note → new note, the
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
"""
import base64
import datetime
import json
import logging
import os
import re
import time

from app.connect import sentences, swap_queue, tidy

log = logging.getLogger("surasura-cli")

SWAP_TAG = "surasura::swapped"
LEARNED_PREFIX = "surasura::learned::"  # FS-1, decision 15: the episode a card was first made from (`learned_tag`)
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
# FS-1 (the full Swap, 3.1; SCOPE.md § 8, Sonic 2026-11-23): a swap's kind, decided when its job is made (`_kind_of`)
IN_PLACE, NEW_CARD = "in place", "new card"
SETTING = "swap_in_place"       # settings.json: True = *Same card, new sentence*; False = *A new card* (True the default since 3.0.18)
MARK = "（前の文）"               # before a kept translation of the old line, until Piyo writes the new one's (decision 2)
CHANGED = "This card changed since the swap: nothing was undone."
HAND_EDITED = "its sentence was changed by hand: a new card instead"     # decision 5 (the row's why, said once)
NOT_CONNECTS = "Surasura didn't make that card: a new card instead"     # decision 6
NO_RENDER = "Update Anki Miner to keep the same card: a new card instead"      # decision 12
# AM-FIX 2 (the lead's ruling 2, 2026-11-23): an old card of Connect's note type with an Anki Miner without `render`
# (3.5-3.10): its `mine` refuses the card as the old card's duplicate, so the swap waits on this, said once (`runner`)
UPDATE_TO_SWAP = "Update Anki Miner to swap this card's sentence"
NOT_APPLIED = "Close the card in Anki's editor: Surasura rewrites it after."
TOO_OLD = "That swap is too old to undo: its old clip and picture were kept 30 days."     # decision 7
KEPT_DIR = "swap-kept"          # in Connect's folder: an in-place swap's old media, one folder a write (decision 7)
# The sentence side (SCOPE § 1): the only roles an in-place swap writes — everything else of the note is the word's or
# the learner's and is never written (an allow-list: a role not here is never touched)
SENTENCE_SIDE = ("sentence", "audio", "picture")
TRANSLATIONS = ("sentence_translation",)
HINT = "Hint"                   # Lapis: the 翻訳 toggle (`card_translations.HINT`)
FURIGANA = "SentenceFurigana"   # the layout's sentence furigana (AJT's colours): emptied, Backfill's ふりがな refills it
# Anki Miner's source line (`<title> - 02 @ 00:17:27`): the source field is rewritten only while it holds one (decision 4)
MINER_SOURCE = re.compile(r"^[^<>\[\]]* @ \d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?\s*$")

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
    have = {r[1] for r in ledger.conn.execute("PRAGMA table_info(swaps)")}
    if "took" not in have:
        ledger.conn.execute("ALTER TABLE swaps ADD COLUMN took TEXT")   # a journey ⇄'s cards it suspended (JSON ids)
    if "kind" not in have:      # FS-1: IN_PLACE / NEW_CARD (none: an ask from before, a new card as it was made)
        ledger.conn.execute("ALTER TABLE swaps ADD COLUMN kind TEXT")
    if "wrote" not in have:     # FS-1: the field writer's record of an in-place swap (`sentence_audio.replace`)
        ledger.conn.execute("ALTER TABLE swaps ADD COLUMN wrote TEXT")
    if "kind_why" not in have:  # FS-1: why a swap the setting would make in place makes a new card (said once)
        ledger.conn.execute("ALTER TABLE swaps ADD COLUMN kind_why TEXT")


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


def asked_first(language, db_path=None):
    """The new notes of the made *Add now* asks (journey v3 D3: `BY_ADD_NOW`, the journey's pick for a word with no
    card), in the order they were asked (the swaps' `id`), each once -> [note id]: Junban's order puts their cards
    first (`modules/junban`, `plan(asked=)`). An undone ask is none. Read-only as `ledger.listed_of` (never made, no
    schema written, no write lock); [] with no ledger, one from a newer Surasura (never read, as `TooNew` says) or
    before any swap was asked; raises sqlite3.Error when it can't be read just now (busy, locked)."""
    import sqlite3
    from pathlib import Path
    from app.connect import ledger as ledger_mod
    db_path = db_path or ledger_mod.path()
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(Path(os.path.abspath(db_path)).as_uri() + "?mode=rw", uri=True, timeout=2.0)
    try:
        conn.execute("PRAGMA query_only=ON")
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'swaps'").fetchone():
            return []
        schema = conn.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
        if schema and str(schema[0]).isdigit() and int(schema[0]) > ledger_mod.SCHEMA:
            return []
        rows = conn.execute("SELECT new_note FROM swaps WHERE language = ? AND by = ? AND state = ? AND new_note IS "
                            "NOT NULL ORDER BY id", (language, BY_ADD_NOW, MADE)).fetchall()
    finally:
        conn.close()
    return list(dict.fromkeys(int(n) for (n,) in rows))


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
    # The score's line first, one asked (every line returned is read); one it can't use (a file outside the library:
    # no item) -> asked again for the picker's TOP, as before. Today's path answers whole the first time
    for top in (1, sentences.TOP):
        try:
            ranked = picker.choose(language, sorted(keys), never={k: set(avoid) for k in keys}, files=files,
                                   reach=reach, top=top)
        except Exception:
            log.info("Swap: the sentence picker didn't answer for a word; the swap waits", exc_info=True)
            return None
        for key in sorted(keys):
            for c in ranked.get(key) or ():
                if c.item_id is not None and c.item_id not in bad and not sentences.same_line(c.text, avoid):
                    return c.item_id, c.text
        if not any(getattr(c, "cost", None) is not None for key in keys for c in ranked.get(key) or ()):
            return None                 # (not the score's: nothing more to ask for)
    return None


def _resolve_line_id(steps, language, text, word=None):
    """The learner's picked line -> (item id, its text), or None when it no longer exists (the item gone, its subtitle
    gone or re-timed past it). `word`: the word it was picked for (`line_cue`)."""
    got = line_cue(steps, language, text, word)
    return (got[0], got[1].text) if got else None


def line_cue(steps, language, text, word=None):
    """A line id (`line_id()`'s form) -> (item id, its `cues.Cue`, the subtitle it is in), or None when it no longer
    exists — the one way a picked line is found: Swap's (`_resolve_line_id`) and the journey's clip (`clips.cut`).
    The cue at the id's own start, else the nearest within 5 ms (a subtitle re-timed a little); two that start
    together (two speakers at once) share one id: `word`, the word the line was pressed for, tells them apart
    (`_pressed`)."""
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
        near = []
        for cue in cues.read(subtitle, language):
            off = abs(int(round(seconds(cue.start) * 1000)) - ms)
            if off <= 5:
                near.append((off, cue))
        if near:
            least = min(off for off, _cue in near)
            return item_id, _pressed([cue for off, cue in near if off == least], language, word), subtitle
    except Exception:
        log.info("Swap: a picked line couldn't be read", exc_info=True)
    return None


def _pressed(same, language, word):
    """Of the cues at one start (in the file's order) the line pressed. With `word` (the door's, a swap's: the list's
    word, its dictionary form) the first the analyzer reads it in — 読む in 読んでない, never 本 inside 日本 — else the
    first that writes it (a set phrase the tokenizer reads as parts), else the first. With none (the page's ▶ asks a
    clip by its id alone) the one that ends last: its span holds every voice said then (E-JOURNEY 3)."""
    if len(same) == 1:
        return same[0]
    if not word:
        return max(same, key=lambda cue: cue.end)       # (the first of those that end together)
    texts = [cue.text or "" for cue in same]
    try:
        from app import analyzer
        if language == "zh":            # the list's words are in the learner's script: the lines read in it too
            from app import settings_manager, zh_script
            script = zh_script.effective(language, settings_manager.load_settings().get("zh_script"))
            texts = [zh_script.convert(t, script) for t in texts]
            tokenize = analyzer.ChineseTokenizer().tokenize
        else:
            tokenize = analyzer.JapaneseTokenizer().tokenize
        for cue, t in zip(same, texts):
            if any(word in (token[0], token[3]) for token in tokenize(t)):
                return cue
    except Exception:
        log.info("Swap: the words of a line pressed couldn't be read", exc_info=True)
    return next((cue for cue, t in zip(same, texts) if word in t), same[0])


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
    """Every line the swap's new card must not be cut from: its old card's, those of the other asks of the same word
    still open (one new card serves them all), and every line a made swap of the word moved away from (Kyou-DW 3: a
    line swapped away from — a deleted card's *Only in this sentence*, a Bad card, a ⇄ — is never used for the word
    again; an undone swap gives its line back) -> a list, or None while one of them can't be read."""
    out = []
    rows = [row] + [r for r in _rows(ledger, "language = ? AND word = ? AND state IN (?, ?) AND id != ?",
                                     (row["language"], row["word"], ASKED, WAITS, row["id"])) if _same_word(r, row)]
    for r in rows:
        lines = json.loads(r["avoid"]) if r.get("avoid") else _old_lines(ledger, r, anki)
        if lines is None:
            return None
        out += [x for x in lines if x not in out]
    for r in _rows(ledger, "language = ? AND word = ? AND state = ? AND id != ? AND avoid IS NOT NULL",
                   (row["language"], row["word"], MADE, row["id"])):
        if _same_word(r, row):
            out += [x for x in json.loads(r["avoid"]) if x not in out]
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
    _purge_kept()
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
    _tag_waiting(ledger, language, anki, flag=_swap_flag)
    return out


def kept_folder():
    """Where an in-place swap keeps the old clip and picture it replaced (`sentence_audio.replace`'s `keep_dir`)."""
    from app.cli.verbs import _connect_folder
    return os.path.join(_connect_folder(), KEPT_DIR)


_PURGED = {}                    # kept_folder() -> when this process last purged it (`_purge_kept`)
PURGE_EVERY_S = 12 * 60 * 60


def _purge_kept():
    """Decision 7: the kept copies go 30 days after they were written (the trash clock's rule and its one purge,
    `path_utils.cleanup_trash_async`, by each file's time: a copy is written, never moved, so its clock starts then);
    an Undo past it is refused (`TOO_OLD`). Never raises."""
    try:
        folder = kept_folder()
        if os.path.isdir(folder) and time.time() - _PURGED.get(folder, 0) >= PURGE_EVERY_S:
            _PURGED[folder] = time.time()           # a 30-day clock needs no look every few minutes
            from app import path_utils
            path_utils.cleanup_trash_async(folder)
    except Exception:
        log.info("Swap: the kept copies weren't looked at this time", exc_info=True)


def _swap_flag():
    """The learner's Swap flag (`review_loop.move_flags`), read when an in-place swap puts its card back in reviews."""
    from app import settings_manager
    from app.connect import review_loop
    return review_loop.move_flags(settings_manager.load_settings())[review_loop.SWAP]


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
    picked = _resolve_line_id(steps, language, row["line_id"], row["word"]) if row.get("line_id") else None
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
    kind, kind_why = _kind_of(ledger, row, anki)
    if kind is None:
        return                              # the old card can't be read now: the next look decides
    with ledger.transaction():              # the job and its swap together: a job of kind swap never without its record
        job_id = ledger.queue_swap(language, item_id, row["word"], row.get("reading") or "", row["at"],
                                   store_id=store_id)
        if job_id is not None:
            _update(ledger.conn, row["id"], state=QUEUED, why=None, item_id=item_id, line=text, job_id=job_id,
                    avoid=json.dumps(avoid, ensure_ascii=False), kind=kind, kind_why=kind_why)
    if job_id is None:
        return                              # the episode has an open job: tried again after it
    out["queued"] += 1


def in_place_on(settings=None):
    """The learner's *Swap gives a card a better sentence* (`SETTING`): True = *Same card, new sentence*, False = *A new
    card* — True the default (decision 1; on since 3.0.18). A value that isn't True or False reads as the default
    (`DEFAULT_SETTINGS`, the one place it turns)."""
    from app import settings_manager
    if settings is None:
        settings = settings_manager.load_settings()
    value = (settings or {}).get(SETTING)
    return value if isinstance(value, bool) else settings_manager.DEFAULT_SETTINGS[SETTING] is True


def _sentence_of(info):
    """A note's sentence field's value (notesInfo's shape): `Sentence`, else the first field named like a sentence that
    isn't its audio, furigana or translation (`_old_lines`' rule) — or None."""
    fields = info.get("fields") or {}
    for name in sorted(fields, key=lambda n: (n.lower() != "sentence", n)):
        low = name.lower()
        if "sentence" in low and not any(x in low for x in ("audio", "furigana", "translat", "hint")):
            value = fields[name].get("value") if isinstance(fields[name], dict) else fields[name]
            return value or ""
    return None


def _kind_of(ledger, row, anki, settings=None):
    """The swap's kind when its job is made (decision 10: a waiting swap follows the setting then) -> (kind, why):
    IN_PLACE only with the setting on, for the loop's flag or the journey's ⇄ (a *Bad card*'s card is gone: decision
    11; *Add now* has none), on a card Connect made (decision 6) whose sentence still holds Connect's line (`same_line`
    against its record: a card changed there by hand gets a new card, decision 5); else NEW_CARD with why. (None,
    None) while Anki can't be read now (the next look decides)."""
    if not in_place_on(settings) or row.get("by") not in (BY_SWAP, BY_JOURNEY) or not row.get("old_note"):
        return NEW_CARD, None
    made = [r[0] for r in ledger.conn.execute("SELECT sentence FROM outcomes WHERE note_id = ? AND outcome = 'made' "
                                              "AND sentence IS NOT NULL", (int(row["old_note"]),)) if r[0]]
    if not made:
        return NEW_CARD, NOT_CONNECTS
    if anki is None:
        return None, None
    try:
        info = next((n for n in anki.notes([int(row["old_note"])]) or () if isinstance(n, dict) and n.get("noteId")),
                    None)
    except Exception:
        log.info("Swap: the old card couldn't be read to choose the swap's kind", exc_info=True)
        return None, None
    if info is None:
        return NEW_CARD, None               # deleted since the flag: nothing to rewrite
    now = _sentence_of(info)
    if now is None:
        return NEW_CARD, None               # a note type with no sentence field: not one Swap rewrites
    if not sentences.same_line(now, made):
        return NEW_CARD, HAND_EDITED
    return IN_PLACE, None


def in_place_row(ledger, job_id):
    """The in-place swap a job of kind `swap` is for (its `swaps` row, kind IN_PLACE, the job's own), or None — the
    runner's batch renders it instead of mining (`runner.Steps.swap_in_place`)."""
    if not ledger.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'swaps'").fetchone():
        return None
    ensure(ledger)
    rows = _rows(ledger, "job_id = ? AND state = ? AND kind = ?", (int(job_id), QUEUED, IN_PLACE))
    return rows[-1] if rows else None


def new_card_row(ledger, job_id):
    """AM-FIX: the simple swap a job of kind `swap` is for when it has an old card on record (its `swaps` row, the job's
    own, not in place), or None — the runner's batch makes its card beside the old one (`add_new_card`) when that card
    is of the note type Connect's cards are made in (`runner.Steps.swap_new_card`)."""
    if not ledger.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'swaps'").fetchone():
        return None
    ensure(ledger)
    rows = [r for r in _rows(ledger, "job_id = ? AND state = ?", (int(job_id), QUEUED))
            if r.get("kind") != IN_PLACE and r.get("old_note")]
    return rows[-1] if rows else None


def twin_fields(info, rendered, mapping):
    """AM-FIX: the simple swap's new card, made beside its old card of the same note type (`add_new_card`) -> {field:
    value}: the old card's own fields — its word side (the word, its reading, definitions, word audio, pitch, with
    their media already in Anki) — with the sentence side `render` gave for the new line (`new_fields`, the full Swap's
    allow-list), the translation render's or none (never the old line's behind `MARK`), and the source render's (the
    new line's episode)."""
    out = _values(info)
    out.update(new_fields(info, rendered, mapping))
    for name in {mapping.fields.get(r) for r in TRANSLATIONS} | {HINT}:
        if name and name in out and out[name].startswith(MARK):
            out[name] = ""
    source = mapping.source
    if source and source in out and str(rendered.get(source) or "").strip():
        out[source] = str(rendered[source])
    return out


def add_new_card(anki, info, rendered, mapping, tags):
    """AM-FIX: the simple swap's new card beside its old card (`twin_fields`), in Connect's deck (`mapping.deck`) with
    `tags` (the job's, as a mined card's) -> its note id. Anki Miner's `mine` can't make this one: its check before
    adding refuses a note whose first field another note of its note type holds — the old card — and its
    `allow_duplicate_cards` only narrows that to the deck (3.13 `services/anki_service.py` `_probe_duplicates`,
    `services/anki_note_builder.py` `build_note`; 3.5.0 the same, drilled). So the note is added here, holding the
    writer, never while you review, with the duplicate allowed (AnkiConnect `addNote`, `allowDuplicate`): the line's
    clip and picture stored first under their names (`rendered["named"]` / `files`), and taken back out when Anki
    refuses the note. A note of this job's already there (`tags[0]`, the job's own tag: an earlier try's `addNote` that
    went through, its answer lost) is the answer: never a second card. Raises sentence_audio.Reviewing, the writer's
    Busy, AnkiConnect's errors, ValueError (render gave no sentence, or a file its fields name can't be read: nothing
    written)."""
    from app.connect import sentence_audio
    fields = rendered.get("fields") or {}
    side = new_fields(info, fields, mapping)
    files = {os.path.basename(p): p for p in rendered.get("files") or ()}
    files.update(rendered.get("named") or {})
    named = sorted({m for v in side.values() for m in sentence_audio.media_in(v)})
    if not str(side.get(mapping.fields.get("sentence")) or "").strip() or \
            any(m not in files or not os.path.isfile(files[m]) for m in named):
        raise ValueError("render gave no sentence, or not the files it names")
    try:
        data = {}
        for name in named:
            with open(files[name], "rb") as f:
                data[name] = base64.b64encode(f.read()).decode("ascii")
    except OSError as e:
        raise ValueError(f"a file render named can't be read: {e}") from None
    values = twin_fields(info, fields, mapping)
    writer = anki.field_writer()
    if writer.reviewing():
        raise sentence_audio.Reviewing()
    with writer.writer(VERB):
        if writer.reviewing():
            raise sentence_audio.Reviewing()
        mine = tags[0] if tags else ""
        before = [int(n) for n in (anki.find_notes(f'"tag:{mine}"') if mine else ()) or ()
                  if int(n) != int(info.get("noteId") or 0)]
        if before:
            return before[0]                        # an earlier try's note: its answer was lost, never a second card
        stored = []
        try:
            for name in named:
                got = writer.store(name, data[name])
                got = got if isinstance(got, str) and got else name
                stored.append(got)
                if got != name:                     # Anki's name for it is the one written
                    values = {k: v.replace(name, got) for k, v in values.items()}
            note = {"deckName": mapping.deck, "modelName": info.get("modelName") or mapping.note_type,
                    "fields": values, "tags": [t for t in tags if t], "options": {"allowDuplicate": True}}
            return int(anki.add_note(note))
        except BaseException:
            for name in stored:                     # stored for a note Anki didn't take: none left behind
                try:
                    if not writer.users(name):
                        writer.delete_media(name)
                except Exception:
                    log.info("Swap: a clip stored for a refused new card couldn't be taken out", exc_info=True)
            raise


def fall_back(ledger, row, why):
    """An in-place swap that can't rewrite its card makes a new card instead, said once (`why`: decisions 5, 6, 12)."""
    _set(ledger, row["id"], kind=NEW_CARD, kind_why=why)


def _values(info):
    return {k: (v.get("value") if isinstance(v, dict) else v) or "" for k, v in (info.get("fields") or {}).items()}


def new_fields(info, rendered, mapping):
    """The old card's new sentence side (SCOPE § 1) from `render`'s note (`rendered` {Anki field: value}) -> {field:
    value}: the sentence, its audio and picture (render's; a field render left out is emptied — a book's line has no
    picture); the sentence furigana emptied (Backfill's ふりがな refills it; AJT's colours of the old line never stay
    under a new sentence); the translation render's when it gives one, else the old one kept behind `MARK`; the source
    field only while it holds what Anki Miner wrote (`MINER_SOURCE`, decision 4). Never another field: the word's side,
    pitch, パターン / 例文, a ヒント, `Is*Card` (an allow-list)."""
    have = _values(info)
    out = {}
    for role in SENTENCE_SIDE:
        name = mapping.fields.get(role)
        if name and name in have:
            out[name] = str(rendered.get(name) or "")
    furigana = mapping.fields.get("sentence_furigana") or FURIGANA
    if furigana in have and have[furigana]:
        out[furigana] = ""
    for name in {mapping.fields.get(r) for r in TRANSLATIONS} | {HINT}:
        if not name or name not in have:
            continue
        given = str(rendered.get(name) or "")
        if given.strip():
            out[name] = given
        elif have[name].strip() and not have[name].startswith(MARK):
            out[name] = MARK + have[name]
    source = mapping.source
    if source and source in have and source not in out and MINER_SOURCE.match(have[source] or "") \
            and str(rendered.get(source) or "").strip():
        out[source] = str(rendered[source])
    return out


def learned_tag(ledger, note, open_store):
    """Decision 15 (*it keeps what it came from*: the episode you learned it from) -> the tag naming the episode a card
    was first made from — `surasura::learned::<show>::s<season>e<episode>` (PROVISIONAL), lowercase: the show as its
    `Surasura::from::` tag names it (`runfile.show_slug`), the episode as Connect places it in its show
    (`library.part_of`, `s01e02`); an item with no place in a show (a book, a channel's video): `…::<show>` alone, its
    file's name when it has no show — or None when the ledger or the store can't say (no tag, never a wrong one)."""
    got = ledger.conn.execute("SELECT j.item_id FROM outcomes o JOIN jobs j ON j.id = o.job_id WHERE o.note_id = ? "
                              "AND o.outcome = 'made' ORDER BY o.job_id, o.rowid LIMIT 1", (int(note),)).fetchone()
    if got is None or got[0] is None or open_store is None:
        return None
    from app.connect import library, runfile
    try:
        store = open_store()
        if store is None:
            return None
        with store:
            item = store.item(int(got[0]))
            if item is None:
                return None
            title = library.show_title(store, int(got[0]))
            place = library.part_of(store, int(got[0]), item.get("rel_path"))
    except Exception:
        log.info("Swap: the episode a card was first made from couldn't be read", exc_info=True)
        return None
    name = title or os.path.splitext(os.path.basename(str(item.get("rel_path") or "")))[0]
    show = runfile.show_slug(name).lower()
    if not show:
        return None
    if not place:
        return LEARNED_PREFIX + show
    season, number = place
    number = f"{int(number):02d}" if float(number).is_integer() else str(number)
    return f"{LEARNED_PREFIX}{show}::s{int(season):02d}e{number}"


def _first_in_place(ledger, row, info):
    """Is this the card's first in-place swap (decision 15's tag written then, never changed after)? No other in-place
    swap of the note standing, and no `LEARNED_PREFIX` tag on it (one its Undo took off is written again; one the
    learner took off stays off)."""
    if any(str(t).lower().startswith(LEARNED_PREFIX) for t in info.get("tags") or ()):
        return False
    return not ledger.conn.execute("SELECT 1 FROM swaps WHERE old_note = ? AND kind = ? AND wrote IS NOT NULL AND "
                                   "state != ? AND id != ?",
                                   (int(row["old_note"]), IN_PLACE, UNDONE, int(row["id"]))).fetchone()


def write_in_place(anki, ledger, row, rendered, mapping, keep_dir, learned=None):
    """The in-place swap's one write (the field writer's replace mode, `sentence_audio.replace`): the old card's
    sentence side rewritten from `render`'s note (`rendered` {"fields", "files"}), only while each field still holds
    what was read here, its old media kept in `keep_dir` first, tagged `SWAP_TAG` -> (IN_PLACE, the note id), or
    (NEW_CARD, why) when the card can't be rewritten (gone, its sentence changed by hand since the look), or (None,
    NOT_APPLIED) when Anki didn't keep the write (the note open in its editor: tried again). `learned`: the card's
    first-episode tag (`learned_tag`), put on with the write at its first in-place swap only, and taken off by that
    swap's Undo (the writer's record holds it); the learner's own tags are never touched."""
    from app.connect import sentence_audio
    note = int(row["old_note"])
    writer = anki.field_writer() if hasattr(anki, "field_writer") else anki
    if row.get("wrote"):
        sentence_audio.settle(writer, ledger, row["wrote"])     # a write a kill or an error stopped: put back first
    info = next((n for n in writer.notes([note]) or () if isinstance(n, dict) and n.get("noteId")), None)
    if info is None:
        return NEW_CARD, None
    made = [r[0] for r in ledger.conn.execute("SELECT sentence FROM outcomes WHERE note_id = ? AND outcome = 'made' "
                                              "AND sentence IS NOT NULL", (note,)) if r[0]]
    if not sentences.same_line(_sentence_of(info) or "", made):
        return NEW_CARD, HAND_EDITED
    new = new_fields(info, rendered.get("fields") or {}, mapping)
    have = _values(info)
    files = {os.path.basename(p): p for p in rendered.get("files") or ()}
    files.update(rendered.get("named") or {})          # the line's names (`media_names.by_line`): what is stored
    named = [m for v in new.values() for m in sentence_audio.media_in(v)]
    if not str(new.get(mapping.fields.get("sentence")) or "").strip() or             any(m not in files or not os.path.isfile(files[m]) for m in named):
        return NEW_CARD, None                   # render gave no sentence, or a clip it didn't hand over: never written
    media = {m: files[m] for m in named}
    first = (learned,) if learned and _first_in_place(ledger, row, info) else ()
    try:
        got = sentence_audio.replace(writer, ledger, note, new, {f: have[f] for f in new}, media=media,
                                     keep_dir=keep_dir, tag=SWAP_TAG, by=BY_SWAP, verb=VERB, extra=first,
                                     on_record=lambda rid: _set(ledger, row["id"], wrote=rid),   # before Anki
                                     loose=(mapping.fields.get("sentence_furigana") or FURIGANA,))  # Backfill's after
    except BaseException as e:
        if getattr(e, "sentence_audio_id", None):
            _set(ledger, row["id"], wrote=e.sentence_audio_id)     # its record: settled when it is tried again
        raise
    if got.get("id"):
        _set(ledger, row["id"], wrote=got["id"])    # tagged with its fields; `_tag_waiting` puts it back in reviews
        return IN_PLACE, note
    why = (got.get("skipped") or {}).get(note)
    if why == sentence_audio.NOT_APPLIED:
        _set(ledger, row["id"], wrote=None)     # its record closed undone: nothing of it on the card
        return None, NOT_APPLIED
    return NEW_CARD, HAND_EDITED if why == sentence_audio.CHANGED else None


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
            if row.get("kind") == IN_PLACE and r.get("old_note") != row.get("old_note"):
                continue                    # an in-place card is its own old card's: never another card's swap
            lines = json.loads(r["avoid"]) if r.get("avoid") else _old_lines(ledger, r, anki)
            if _same_word(r, row) and lines is not None and not sentences.same_line(row.get("line") or "", lines):
                twins.append(r)
        for r in twins:
            own = {"kind_why": row.get("kind_why")} if r["id"] == row["id"] else {}
            own["wrote"] = row.get("wrote")             # a twin of an in-place swap (the same card): one write, one Undo
            _set(ledger, r["id"], state=MADE, why=None, new_note=note, job_id=row["job_id"], item_id=row["item_id"],
                 line=row["line"], kind=row.get("kind"), **own)
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


def _tag_waiting(ledger, language, anki, flag=None):
    """The old cards of made swaps tagged `SWAP_TAG` (Swap's only write to them), under Anki's write lock and never while
    you review; Anki closed or busy: looked at again. A deleted old card: nothing to tag. An in-place swap (its tag
    written with its fields) from the loop's flag: its card back in your reviews — unsuspended, its Swap flag off
    (`flag()`: the learner's pick; decision 8) — a journey ⇄'s card was never out of them: nothing."""
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
            back_flag = None
            for r in rows:
                if r.get("kind") == IN_PLACE:
                    if r.get("by") == BY_SWAP and r.get("old_note") and int(r["old_note"]) in have:
                        if back_flag is None:
                            back_flag = flag() if callable(flag) else GREEN
                        _old_back(anki, r, keep_tag=True, flag=back_flag)
                    continue
                if r.get("by") == BY_JOURNEY and JOURNEY_TAKES_OLD:
                    _take_old(anki, ledger, r, infos)
            have -= {int(r["old_note"]) for r in rows if r.get("kind") == IN_PLACE and r.get("old_note")}
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

    def field_writer(self):
        """The one field writer's Anki (`sentence_audio.AnkiConnectNotes`): an in-place swap's write and its Undo."""
        from app.connect import sentence_audio
        return sentence_audio.AnkiConnectNotes(self.url)

    def add_note(self, note):
        """AM-FIX: a simple swap's new card added beside its old card (`add_new_card`) -> its note id."""
        from app import anki_connect
        return anki_connect.invoke("addNote", self.url, note=note)

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
    if row.get("kind") == IN_PLACE:
        return _undo_in_place(anki, ledger, language, row, entry, open_store)
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


def _undo_in_place(anki, ledger, language, row, entry, open_store=None):
    """An in-place swap undone: the field writer's record put back (`sentence_audio.undo`: every old value, the old
    clip and picture stored again, the tag off — only while every field still holds what the swap wrote, else
    `CHANGED` and nothing changes); the swap job's made outcome for the card marked `undone` (the card's line is its
    old one again for the deleted-card look and Swap's own avoid list); the card left in your reviews (decision 8);
    then the queue's entry `undone` with the ledger's row in one step (a retry after the queue's write failed finds the
    record undone already and only finishes); last, the store's made words: the card back under the item its line is
    from again (`_store_back`). A kept copy past its 30 days: `TOO_OLD`, nothing changes."""
    from app.connect import sentence_audio
    writer = anki.field_writer() if hasattr(anki, "field_writer") else anki
    rec = sentence_audio.record(ledger, row["wrote"]) if row.get("wrote") else None
    if rec is None:
        raise tidy.Refused(GONE)
    if rec.get("state") != sentence_audio.UNDONE:
        got = sentence_audio.undo(writer, ledger, row["wrote"], verb=VERB)
        if got.get("refused") == sentence_audio.TOO_OLD:
            raise tidy.Refused(TOO_OLD)
        if got.get("kept") or not got.get("emptied"):
            raise tidy.Refused(CHANGED)
    with ledger.transaction():
        _update(ledger.conn, row["id"], state=UNDONE)
        ledger.conn.execute("UPDATE outcomes SET outcome = 'undone' WHERE job_id = ? AND note_id = ? AND outcome = "
                            "'made'", (int(row["job_id"]), int(row["new_note"])))
        if entry is not None and swap_queue.undone(language, str(row["ref"])) is None:
            raise RuntimeError(f"the swap queue's entry {row['ref']} isn't made: nothing was undone there")
    _store_back(ledger, row, open_store)
    return {"undone": True, "word": row["word"], "kind": IN_PLACE}


def rewritten(ledger, job_id):
    """The notes a swap job rewrote in place (its in-place swaps' old cards, written) -> [note id]: the runner records
    them under the job's item alone (`library.record_batch`'s `moved`) and hands them to Backfill as cards whose
    sentence is new (`run_named`'s `rewritten`: a studied card's ふりがな refilled)."""
    if not ledger.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'swaps'").fetchone():
        return []
    ensure(ledger)
    return sorted({int(r[0]) for r in ledger.conn.execute(
        "SELECT old_note FROM swaps WHERE job_id = ? AND kind = ? AND wrote IS NOT NULL AND old_note IS NOT NULL AND "
        "state != ?", (int(job_id), IN_PLACE, UNDONE))})


def _store_back(ledger, row, open_store):
    """An undone in-place swap's card recorded under the item of the line it shows again (the note's newest made
    outcome left, its first job's or an earlier swap's) and out of the swap job's (`library.record_batch`'s `moved`).
    Tidiness of the record (the word stays made either way, G1.3-4): a store that can't be written now is logged."""
    if open_store is None:
        return
    got = ledger.conn.execute("SELECT j.item_id, o.word, j.id FROM outcomes o JOIN jobs j ON j.id = o.job_id WHERE "
                              "o.note_id = ? AND o.outcome = 'made' ORDER BY o.job_id DESC LIMIT 1",
                              (int(row["new_note"]),)).fetchone()
    if got is None or got[0] is None:
        return
    try:
        from app.connect import library
        store = open_store()
        if store is None:
            return
        with store:
            library.record_batch(store, int(got[0]), {got[1]: [int(row["new_note"])]}, None, ledger.tag_id(got[2]),
                                 moved=[int(row["new_note"])])      # that job's batch, as its record named it
    except Exception:
        log.warning("Swap: the library's record of an undone swap's card wasn't moved back", exc_info=True)


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
    """The window's record (Connect's status, *Needs you*): {"made": [{"id", "word", "at", "kind", "kind_why", "by"}]
    (the newest made swaps not undone, newest first; `by` who asked: the flag, the journey, *Bad card* — FS-2's words),
    "waits": [{"id", "word"}] (the asks with no other line)} — read-only on `conn`."""
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'swaps'").fetchone():
            return {"made": [], "waits": []}
        have = {r[1] for r in conn.execute("PRAGMA table_info(swaps)")}     # each ALTER of `ensure` is its own
        kinds = ", ".join(c if c in have else "NULL" for c in ("kind", "kind_why"))
        made = [{"id": r[0], "word": r[1], "at": r[2], "kind": r[3] or NEW_CARD, "kind_why": r[4], "by": r[5]}
                for r in conn.execute(
            f"SELECT id, word, updated_at, {kinds}, by FROM swaps WHERE language "
            "= ? AND state = ? ORDER BY id DESC LIMIT ?", (language, MADE, int(newest)))]
        waits = [{"id": r[0], "word": r[1]} for r in conn.execute(
            "SELECT id, word FROM swaps WHERE language = ? AND state = ? ORDER BY id", (language, WAITS))]
    except Exception:
        return {"made": [], "waits": []}
    return {"made": made, "waits": waits}


# --------------------------------------------------------------------------- #
# Send report (SWAPS-REPORT, 3.0.19; Sonic's yes, OPEN-FOR-SONIC § 92): the learner's swaps, read only
# --------------------------------------------------------------------------- #
REPORT_FORMAT = 1
REPORT_LINE_MAX = 400           # a sentence as Send report carries it (the flagged lines' `flags.LINE_MAX`)


def _report_time(at):
    """The ledger's UTC stamp -> the local time the queue writes (ISO, seconds); None when there's none."""
    try:
        when = datetime.datetime.strptime(str(at), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return None
    return when.astimezone().replace(tzinfo=None).isoformat(timespec="seconds")


def _report_text(text):
    from app.card_translations import plain
    text = " ".join(plain(text).split())[:REPORT_LINE_MAX]
    return text or None


def _report_rows(language):
    """The ledger's swaps of `language`, read-only (as `asked_first`) -> ({ref: row}, [rows with no queue entry],
    {old note: its sentence Connect made it from}); ({}, [], {}) with no ledger or none from this Surasura. Raises
    sqlite3.Error when it can't be read now."""
    import sqlite3
    from pathlib import Path
    from app.connect import ledger as ledger_mod
    db_path = ledger_mod.path()
    if not os.path.exists(db_path):
        return {}, [], {}
    conn = sqlite3.connect(Path(os.path.abspath(db_path)).as_uri() + "?mode=rw", uri=True, timeout=2.0)
    try:
        conn.execute("PRAGMA query_only=ON")
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'swaps'").fetchone():
            return {}, [], {}
        schema = conn.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
        if schema and str(schema[0]).isdigit() and int(schema[0]) > ledger_mod.SCHEMA:
            return {}, [], {}
        cur = conn.execute("SELECT * FROM swaps WHERE language = ? AND by != ? ORDER BY id", (language, BY_ADD_NOW))
        names = [d[0] for d in cur.description]
        rows = [dict(zip(names, r)) for r in cur.fetchall()]
        olds = {}
        notes = sorted({int(r["old_note"]) for r in rows if r.get("old_note") is not None})
        for at in range(0, len(notes), 500):
            part = notes[at:at + 500]
            for note, sentence in conn.execute(
                    f"SELECT note_id, sentence FROM outcomes WHERE outcome = 'made' AND sentence IS NOT NULL AND "
                    f"note_id IN ({', '.join('?' * len(part))})", part):
                olds.setdefault(int(note), sentence)
    finally:
        conn.close()
    by_ref = {str(r["ref"]): r for r in rows if r.get("ref") is not None}
    return by_ref, [r for r in rows if r.get("ref") is None], olds


def _report_sentences(row, olds):
    """(the old card's sentence, the new card's) as the ledger holds them: the old one from Connect's record of the
    note, else the first line the swap avoided (`_avoid` puts the old card's own first); None where it holds none."""
    if row is None:
        return None, None
    old = olds.get(int(row["old_note"])) if row.get("old_note") is not None else None
    if not old and row.get("avoid"):
        try:
            avoided = json.loads(row["avoid"])
            old = avoided[0] if isinstance(avoided, list) and avoided else None
        except (TypeError, ValueError):
            old = None
    return _report_text(old), _report_text(row.get("line"))


def for_report(language, sent=None, newest=200):
    """The learner's swaps for Send report's zip -> [(id, state, swap)], newest first, at most `newest` (the flagged
    sentences' cap, `flags.MAX_LINES`). `swap` is exactly what `connect/swaps.json` holds for it: `word`, `old` and
    `new` (the two sentences, plain text, or None), `asked` (when), `state` (waiting · made · dropped · undone), `why`
    (a dropped one's), `at` (when it was made, dropped or undone, where the record says) and `by` (who asked: the
    review loop's flag `swap`, the journey's ⇄ `journey`, *Bad card* `bad card`). Never a card's or note's id.

    **Read only, from the one record** (`swap_queue`, the entry: word, when, state, why) — the ledger only for what
    the entry lacks (the two sentences), and for the asks with no entry (the journey's ⇄ and *Bad card*: their ledger
    row is their record). *Add now* is no swap (no old card). `sent` ({id: state}: what Send report already sent, its
    own record) leaves out a swap sent in the state it's in now. Raises `swap_queue.Unreadable` (the queue can't be
    read); a ledger that can't be read now leaves the sentences None and the ledger-only asks out."""
    sent = dict(sent or {})
    try:
        by_ref, alone, olds = _report_rows(language)
    except Exception:
        log.info("Swap: the ledger couldn't be read for Send report", exc_info=True)
        by_ref, alone, olds = {}, [], {}
    out = []
    for e in swap_queue.load(language):
        if not e.get("id") or e.get("state") not in (swap_queue.WAITING, swap_queue.MADE, swap_queue.DROPPED,
                                                     swap_queue.UNDONE):
            continue
        row = by_ref.get(str(e["id"]))
        old, new = _report_sentences(row, olds)
        state = e["state"]
        at = ((e.get("made") or {}).get("at") if state == swap_queue.MADE else e.get("undone")
              if state == swap_queue.UNDONE else _report_time(row.get("updated_at")) if row and state ==
              swap_queue.DROPPED else None)
        out.append((f"q:{e['id']}", state, {"word": e.get("word") or "", "old": old, "new": new,
                                            "asked": e.get("queued"), "state": state, "why": e.get("why"), "at": at,
                                            "by": (row or {}).get("by") or BY_SWAP}))
    for row in alone:
        state = row["state"] if row["state"] in (MADE, DROPPED, UNDONE) else swap_queue.WAITING
        old, new = _report_sentences(row, olds)
        out.append((f"l:{row['id']}", state, {"word": row.get("word") or "", "old": old, "new": new,
                                              "asked": _report_time(row.get("at")), "state": state,
                                              "why": row.get("why") if state == DROPPED else None,
                                              "at": None if state == swap_queue.WAITING else
                                              _report_time(row.get("updated_at")), "by": row.get("by") or BY_SWAP}))
    out = [x for x in out if sent.get(x[0]) != x[1]]
    out.sort(key=lambda x: str(x[2]["asked"] or ""), reverse=True)
    return out[:max(0, int(newest))]


def report_bytes(language, swaps):
    """`connect/swaps.json`'s bytes for `swaps` (`for_report`'s third parts), UTF-8."""
    return json.dumps({"format": REPORT_FORMAT, "language": language, "swaps": list(swaps)}, ensure_ascii=False,
                      indent=1).encode("utf-8")
