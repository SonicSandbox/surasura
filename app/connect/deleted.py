"""A deleted card asks why (Kyou-DW, 3.0.18; the review loop's fourth move, WL ⑧ / WL-35; ROLES.md *The review loop*;
every learner-visible word PROVISIONAL). A card Connect made that you delete in Anki is seen by Connect's deleted-card
look (`runner.Steps.notes_gone`, once a run: the store takes the note out and keeps the word, never made again unless
you ask — `Store.notes_gone`, `made_words`); this module is what that look now remembers, and *Needs you*'s quiet card
that asks why — **Known · Ignore · Parsing mistake · Bad card**, one line a card, *Same for all*, an Undo for each.

- **The record is Connect's own** (no new log): the made card's outcome in the ledger (`outcomes`: its word, reading,
  sentence, line and note) is read for what the card showed; the look's stamp and your answer sit beside it by note id
  in the same ledger (table `deleted`; `outcomes` itself is written by `INSERT OR REPLACE`, which would drop an added
  column). Only the look's deletes are stamped: Tidy's and *Undo this batch*'s are Surasura's own, never asked
  (a note a tidy holds is skipped even before Tidy told the store: `_tidied`).
- **Never asked:** a card whose word was already Known or Ignored when the look saw it gone (kept as `state`
  `known` / `ignored`: WL-6, WL-44), one deleted more than `ASK_DAYS` ago (WL-31: it goes, unanswered), and one whose
  word has a newer card from Connect (a later note id whose card may still be in Anki: neither one the
  look saw gone nor one Surasura's Tidy deleted — a Bad card's new card its Undo took back asks again).
- **The answers** (`answer`, on the window's worker): Known → the word lists' one writer (`word_marks.apply`, Kyou-LR's
  rules); Ignore → the loop's Ignore (`unknow=True`); Parsing mistake → that Ignore + the card's line into Send report's
  list (`flags.add(source="loop")`, J-FLAGS: shown and untickable before anything is sent); Bad card → Swap's one maker
  (`swap.make_card(..., by=BY_BAD_CARD)`: a new card from another line — Swap chooses it, never this card's line).
  **Parsing mistake asks one more thing** (Kyou-DW 3, 3.0.19; Sonic's yes, PROVISIONAL): *The word is wrong* (`PARSING`,
  no word at all: as above) or *Only in this sentence* (`LINE`: the word is real, this line read it wrong — the line
  into Send report's list as the same parsing report, and the word a new card from another sentence through Bad card's
  door; Swap keeps that line out of every later swap of the word, `swap._avoid`, until the answer is undone). Which
  one is offered first is the look's guess (`likely`, kept with the card): a word a dictionary holds (the shipped
  meanings, the learner's own) that the last Generate kept sentences of in `SEVERAL` other files → `LINE` first, else
  `PARSING`; the learner always picks. A word Known or Ignored since is skipped, said. **Undo** (`undo`): each answer
  taken back while its word is as the answer left it (the mark as it was before, the line off the list, the new card
  through Swap's own Undo).
- **The old deletes, once** (the Discord promise: cards deleted as parsing mistakes before the loop could ask): at the
  look's first run in this version the words already deleted (`Store.unmined_words`) are kept as one list (ledger meta
  `old-deletes:<lang>`), never grown; *Needs you* shows it once, and *Forget* frees a word through the store's
  `allow_again` (the window's writer: one toast, one Undo) so its card may be made again once its cut is fixed. The
  learner's other deletes are never touched.

Qt-free; the window calls `answer` / `undo` on a worker, `status_of` reads the ledger read-only (Connect's record).
"""
import datetime
import json
import logging

log = logging.getLogger("surasura-cli")

KNOWN, IGNORE, PARSING, BAD = "known", "ignore", "parsing", "bad"
LINE = "line"                   # Kyou-DW 3: Parsing mistake › *Only in this sentence* (PARSING: *The word is wrong*)
WHYS = (KNOWN, IGNORE, PARSING, BAD, LINE)
SEVERAL = 3                     # Kyou-DW 3 (PROVISIONAL): "said in several other files" — the guess's count
WAS_KNOWN, WAS_IGNORED = "known", "ignored"     # `state`: never asked (the word was already so when the card went)
ASK_DAYS = 14                   # WL-31 (PROVISIONAL): an unanswered card goes after this long, never asked again
OLD_KEY = "old-deletes:{lang}"  # ledger meta: the one-time list of deletes from before the loop asked
FLAG_KEY = "note:{note}"        # Send report's line key for a card's line (`flags.add`'s `key`)
REFUSED = {
    "changed": "it changed since",
    "known": "already known",
    "ignored": "already ignored",
    "busy": "your word lists are busy",
}

_SQL = """CREATE TABLE IF NOT EXISTS deleted (
  language   TEXT NOT NULL,
  note_id    INTEGER NOT NULL,
  word       TEXT NOT NULL,
  reading    TEXT NOT NULL DEFAULT '',
  item_id    INTEGER,
  sentence   TEXT,
  line_start REAL,
  gone_at    TEXT NOT NULL,
  state      TEXT,
  why        TEXT,
  why_at     TEXT,
  undo       TEXT,
  likely     TEXT,
  PRIMARY KEY (language, note_id))"""


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure(ledger):
    ledger.conn.execute(_SQL)
    if "likely" not in {r[1] for r in ledger.conn.execute("PRAGMA table_info(deleted)")}:
        ledger.conn.execute("ALTER TABLE deleted ADD COLUMN likely TEXT")     # Kyou-DW 3: the look's guess


def _has(conn, table):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone() \
        is not None


# --------------------------------------------------------------------------- #
# The look: what it saw gone (Connect's runner)
# --------------------------------------------------------------------------- #
def _made(conn, language, note_id):
    """The newest `made` outcome Connect recorded for the note -> (word, reading, sentence, line_start, item_id) or
    None (not Connect's card: the learner's own)."""
    return conn.execute(
        "SELECT o.word, o.reading, o.sentence, o.line_start, j.item_id FROM outcomes o JOIN jobs j ON j.id = o.job_id "
        "WHERE j.language = ? AND o.note_id = ? AND o.outcome = 'made' ORDER BY o.rowid DESC LIMIT 1",
        (language, int(note_id))).fetchone()


def seen(language, gone, store=None, state_of=None, ledger=None, now=None, likely_of=None):
    """The deleted-card look's notes (`gone`, taken out of the store just now) remembered as deleted by you: each one
    Connect made gets its row (word, sentence, line, episode), its `state` `known` / `ignored` when its word already
    was (`state_of(word, reading)`, default Swap's — the pick's own test; unreadable → asked), and the follow-up's
    guess (`likely_of(language, [(note, word, reading, sentence)])`, default `likely`; none → *The word is wrong*
    first). Then, once ever per language, the old deletes kept (`store`: its `unmined_words` minus the ones just
    stamped). -> how many stamped."""
    from app.connect import ledger as ledger_mod
    own = ledger is None
    ledger = ledger or ledger_mod.Ledger()
    try:
        ensure(ledger)
        at = now or _now()
        rows = []
        tidied = _tidied(ledger.conn, language)
        for note in sorted({int(n) for n in gone or ()} - tidied):
            made = _made(ledger.conn, language, note)
            if made is not None:
                rows.append((note,) + tuple(made))
        if rows and state_of is None:
            state_of = _states(language)
        guess = {}
        if rows:
            try:
                guess = (likely_of or likely)(language, [(r[0], r[1], r[2] or "", r[3] or "") for r in rows]) or {}
            except Exception:
                log.info("Kyou-DW: no guess for the deleted cards' follow-up", exc_info=True)
        stamped = 0
        with ledger.transaction():
            for note, word, reading, sentence, start, item_id in rows:
                state = None
                if state_of is not None:
                    try:
                        state = state_of(word, reading or "")
                    except Exception:
                        state = None
                cur = ledger.conn.execute(
                    "INSERT OR IGNORE INTO deleted (language, note_id, word, reading, item_id, sentence, line_start, "
                    "gone_at, state, likely) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (language, note, word, reading or "", item_id, sentence, start, at,
                     state if state in (WAS_KNOWN, WAS_IGNORED) else None,
                     guess.get(note) if guess.get(note) in (LINE, PARSING) else None))
                stamped += cur.rowcount
        if store is not None:
            _keep_old(ledger, language, store)
        return stamped
    finally:
        if own:
            ledger.close()


def likely(language, rows):
    """Kyou-DW 3: which answer the follow-up offers first, for each deleted card -> {note: LINE | PARSING}; {} when it
    can't be read (never raises). `rows`: [(note, word, reading, sentence)]. A word the last Generate kept sentences
    of in `SEVERAL` files other than this line's (`sentences.files_saying`: the plan's pools) **and** a dictionary
    holds — the shipped meanings (`journey_render.Meanings`: JMdict EN · CC-CEDICT) or the learner's own
    (`own_dicts.lookup`: only whether it holds the word; its text is never kept) — is a real word this line read
    wrong: LINE; anything else PARSING (today's order). The dictionaries are read only for the words said that often."""
    try:
        from app.connect import sentences
        said = sentences.files_saying(language, [(w, r, s) for _n, w, r, s in rows])
        often = list(dict.fromkeys((w, r or "") for _n, w, r, _s in rows if said.get((w, r or ""), 0) >= SEVERAL))
        held = set()
        if often:
            from app import journey_render, own_dicts
            shipped = journey_render.Meanings(language)
            shipped.prepare([(w, r, "") for w, r in often])
            held = {(w, r) for w, r in often if shipped.of(w, r, "")}
            try:                        # the learner's own: one that can't be read takes nothing from the shipped
                held |= set(own_dicts.lookup([k for k in often if k not in held]) or ())
            except Exception:
                log.info("Kyou-DW: the learner's own dictionaries couldn't be read for the guess", exc_info=True)
        return {n: LINE if (w, r or "") in held else PARSING for n, w, r, _s in rows}
    except Exception:
        log.info("Kyou-DW: the follow-up's guess couldn't be read", exc_info=True)
        return {}


def _tidied(conn, language):
    """The notes Surasura's own Tidy took (or is taking) out of Anki for `language` — a tidy writing, done, or being
    undone (`tidies.notes`): a look that sees one gone before Tidy told the store (a *Tidy now* while Connect runs, a
    store write that failed) never takes it for the learner's delete. A tidy undone gave its notes back: a later delete
    of one is the learner's."""
    if not _has(conn, "tidies"):
        return set()
    out = set()
    for (notes,) in conn.execute("SELECT notes FROM tidies WHERE language = ? AND state IN ('writing', 'done', "
                                 "'restoring')", (language,)):
        try:
            out.update(int(n) for n in json.loads(notes or "{}"))
        except (TypeError, ValueError):
            continue
    return out


def keep_old(language, store, ledger=None):
    """Once ever per language (the look's, after the store forgot its gone notes): the deletes from before the loop
    asked (`_keep_old`)."""
    from app.connect import ledger as ledger_mod
    own = ledger is None
    ledger = ledger or ledger_mod.Ledger()
    try:
        ensure(ledger)
        _keep_old(ledger, language, store)
    finally:
        if own:
            ledger.close()


def _states(language):
    """Swap's Known / Ignored tester (the pick's own rule: `swap.states`), or None when it can't be read (every card
    is then asked; an answer is checked again at its press)."""
    try:
        from app.connect import swap
        return swap.states(language)
    except Exception:
        log.info("Kyou-DW: the words' states couldn't be read: every deleted card is asked", exc_info=True)
        return None


def _keep_old(ledger, language, store):
    """Once ever per language: the words deleted before the loop asked (the store's deleted words, none stamped by a
    look) with the newest sentence Connect recorded for each -> the ledger's meta (`OLD_KEY`); never grown after."""
    key = OLD_KEY.format(lang=language)
    if ledger.conn.execute("SELECT 1 FROM meta WHERE key = ?", (key,)).fetchone():
        return
    stamped = {r[0] for r in ledger.conn.execute("SELECT word FROM deleted WHERE language = ?", (language,))}
    old = []
    for entry in store.unmined_words():
        word = entry.get("word")
        if not word or word in stamped:
            continue
        line = ledger.conn.execute(
            "SELECT o.sentence, o.reading FROM outcomes o JOIN jobs j ON j.id = o.job_id WHERE j.language = ? AND "
            "o.word = ? AND o.outcome = 'made' ORDER BY o.rowid DESC LIMIT 1", (language, word)).fetchone()
        old.append({"word": word, "sentence": (line or (None,))[0] or "", "items": list(entry.get("items") or ())})
    ledger.conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)", (key, json.dumps(old,
                                                                                                ensure_ascii=False)))


# --------------------------------------------------------------------------- #
# Read-only: Connect's record (`status.read`)
# --------------------------------------------------------------------------- #
def status_of(conn, language, now=None):
    """-> {"asked": [{note_id, word, reading, sentence, item_id, gone_at, likely}], newest first; "known": n,
    "ignored": n (the cards never asked, of the last `ASK_DAYS`); "old": the one-time list}. Read-only: nothing made or
    written. `likely`: the look's guess for the follow-up (None: a card stamped before Kyou-DW 3)."""
    out = {"asked": [], "known": 0, "ignored": 0, "old": []}
    if not _has(conn, "meta"):
        return out
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (OLD_KEY.format(lang=language),)).fetchone()
    try:
        out["old"] = [e for e in json.loads(row[0]) if isinstance(e, dict) and e.get("word")] if row else []
    except (TypeError, ValueError):
        out["old"] = []
    if not _has(conn, "deleted"):
        return out
    since = ((now or datetime.datetime.now(datetime.timezone.utc)) - datetime.timedelta(days=ASK_DAYS)
             ).strftime("%Y-%m-%dT%H:%M:%SZ")
    for state, n in conn.execute("SELECT state, COUNT(*) FROM deleted WHERE language = ? AND state IS NOT NULL AND "
                                 "gone_at >= ? GROUP BY state", (language, since)):
        if state in (WAS_KNOWN, WAS_IGNORED):
            out[state] = n
    guessed = "likely" in {r[1] for r in conn.execute("PRAGMA table_info(deleted)")}   # (a ledger before Kyou-DW 3)
    rows = conn.execute(
        f"SELECT d.note_id, d.word, d.reading, d.sentence, d.item_id, d.gone_at, {'d.likely' if guessed else 'NULL'} "
        "FROM deleted d WHERE d.language = ? AND d.state IS NULL AND d.why IS NULL AND d.gone_at >= ? "
        "ORDER BY d.gone_at DESC, d.note_id DESC", (language, since)).fetchall()
    newer = _newer_cards(conn, language, {r[1] for r in rows}) if rows else {}
    out["asked"] = [{"note_id": r[0], "word": r[1], "reading": r[2], "sentence": r[3] or "", "item_id": r[4],
                     "gone_at": r[5], "likely": r[6]} for r in rows if not any(n > r[0] for n in newer.get(r[1], ()))]
    return out


REPORTED = (KNOWN, IGNORE)      # SEND-EASY: the answers Send report carries as cards not wanted (Parsing mistake goes
#                                 as a flagged sentence, Bad card and Only in this sentence as a swap already)


def report_rows(language, notes=()):
    """Send report's read (SEND-EASY): the deleted cards answered Known or Ignore -> ([{note_id, word, sentence, why,
    why_at}], {note: the sentence Connect made it from} for `notes`, the review loop's red cards); ([], {}) with no
    ledger. Read only: a read-only connection, as `swap._report_rows`. Raises sqlite3.Error when it can't be read
    now."""
    import os
    import sqlite3
    from pathlib import Path
    from app.connect import ledger as ledger_mod
    db_path = ledger_mod.path()
    if not os.path.exists(db_path):
        return [], {}
    conn = sqlite3.connect(Path(os.path.abspath(db_path)).as_uri() + "?mode=rw", uri=True, timeout=2.0)
    try:
        conn.execute("PRAGMA query_only=ON")
        rows = []
        if _has(conn, "deleted"):
            cur = conn.execute(f"SELECT note_id, word, sentence, why, why_at FROM deleted WHERE language = ? AND "
                               f"why IN ({', '.join('?' * len(REPORTED))}) ORDER BY why_at DESC, note_id DESC",
                               (language,) + REPORTED)
            rows = [dict(zip(("note_id", "word", "sentence", "why", "why_at"), r)) for r in cur.fetchall()]
        sentences = {}
        wanted = sorted({n for n in (_int(x) for x in notes or ()) if n is not None})
        if wanted and _has(conn, "outcomes"):
            for at in range(0, len(wanted), 500):
                part = wanted[at:at + 500]
                for note, sentence in conn.execute(
                        f"SELECT note_id, sentence FROM outcomes WHERE outcome = 'made' AND sentence IS NOT NULL AND "
                        f"note_id IN ({', '.join('?' * len(part))})", part):
                    sentences.setdefault(int(note), sentence)
    finally:
        conn.close()
    return rows, sentences


def _int(value):
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError):
        return None


def _newer_cards(conn, language, words):
    """{word: the note ids Connect made for it that may still be in Anki}: none the look saw gone (`deleted`), none
    Surasura's own Tidy deleted (`tidies`, done — a Bad card's or a swap's new card its Undo took back among them)."""
    gone = {int(n) for (n,) in conn.execute("SELECT note_id FROM deleted WHERE language = ?", (language,))} \
        if _has(conn, "deleted") else set()     # (the journey's ⇄ asks before any deleted-card look ran)
    if _has(conn, "tidies"):
        for (deleted_notes,) in conn.execute("SELECT deleted FROM tidies WHERE language = ? AND state = 'done' AND "
                                             "deleted IS NOT NULL", (language,)):
            try:
                gone.update(int(n) for n in json.loads(deleted_notes) or ())
            except (TypeError, ValueError):
                continue
    words = sorted(words)
    out = {}
    for i in range(0, len(words), 500):
        part = words[i:i + 500]
        for word, note in conn.execute(
                "SELECT o.word, o.note_id FROM outcomes o JOIN jobs j ON j.id = o.job_id WHERE j.language = ? AND "
                f"o.outcome = 'made' AND o.note_id IS NOT NULL AND o.word IN ({','.join('?' * len(part))})",
                [language] + part):
            if int(note) not in gone:
                out.setdefault(word, set()).add(int(note))
    return out


# --------------------------------------------------------------------------- #
# The answers (the window's worker)
# --------------------------------------------------------------------------- #
def _rows(conn, language, note_ids, answered):
    notes = sorted({int(n) for n in note_ids or ()})
    if not notes:
        return []
    cur = conn.execute(
        f"SELECT note_id, word, reading, sentence, item_id, line_start, why, undo FROM deleted WHERE language = ? AND "
        f"why IS {'NOT' if answered else ''} NULL AND note_id IN ({','.join('?' * len(notes))}) ORDER BY note_id",
        [language] + notes)
    return [dict(zip(("note_id", "word", "reading", "sentence", "item_id", "line_start", "why", "undo"), r))
            for r in cur.fetchall()]


def _place(language, item_id, open_store):
    """(show, episode) names of the card's episode, never a path (`flags.place`) -> ('', '') when unknown."""
    if item_id is None or open_store is None:
        return "", ""
    try:
        from app.services import flags
        store = open_store(language)
        if store is None:
            return "", ""
        with store:
            item = store.item(int(item_id))
        return flags.place(item["rel_path"]) if item and item.get("rel_path") else ("", "")
    except Exception:
        return "", ""


def _default_store(language):
    from app.connect import library
    return library.open_store(language, role="reader")


def answer(language, note_ids, why, ledger=None, state_of=None, open_store=_default_store, now=None):
    """The learner's answer for these deleted cards (one, or *Same for all*) -> {"done": [(note_id, word)],
    "skipped": [(note_id, word, why)], "error": text or None}. Each card is claimed first (its `why` written: a second
    press, or a second window, finds none), then answered; a card its answer couldn't do is given back (asked again).
    A word Known or Ignored since the look is never asked again (its `state` set, counted)."""
    if why not in WHYS:
        raise ValueError(f"unknown answer {why!r}")
    if why in (BAD, LINE):
        from app.connect import swap  # noqa: F401  (Swap's maker absent: nothing claimed, the press says it failed)
    from app.connect import ledger as ledger_mod
    own = ledger is None
    ledger = ledger or ledger_mod.Ledger()
    out = {"done": [], "skipped": [], "error": None}
    try:
        ensure(ledger)
        if state_of is None:
            state_of = _states(language) or (lambda _w, _r="": None)
        at = now or _now()
        asked = []
        with ledger.transaction():
            for r in _rows(ledger.conn, language, note_ids, answered=False):
                state = state_of(r["word"], r["reading"] or "")
                if state in (WAS_KNOWN, WAS_IGNORED):
                    ledger.conn.execute("UPDATE deleted SET state = ? WHERE language = ? AND note_id = ?",
                                        (state, language, r["note_id"]))
                    out["skipped"].append((r["note_id"], r["word"], REFUSED[state]))
                    continue
                ledger.conn.execute("UPDATE deleted SET why = ?, why_at = ? WHERE language = ? AND note_id = ? AND "
                                    "why IS NULL", (why, at, language, r["note_id"]))
                asked.append(r)
        undos = {}
        try:
            undos = _act(language, asked, why, out, open_store)
        finally:                    # whatever `_act` did is recorded; a card it didn't do is given back
            with ledger.transaction():
                for r in asked:
                    if r["note_id"] in undos:
                        ledger.conn.execute("UPDATE deleted SET undo = ? WHERE language = ? AND note_id = ?",
                                            (json.dumps(undos[r["note_id"]], ensure_ascii=False), language,
                                             r["note_id"]))
                        out["done"].append((r["note_id"], r["word"]))
                    else:
                        ledger.conn.execute("UPDATE deleted SET why = NULL, why_at = NULL WHERE language = ? AND "
                                            "note_id = ?", (language, r["note_id"]))
                        if why in (BAD, LINE) and r["word"] in (swap_state := _swap_state(out, r)):
                            ledger.conn.execute("UPDATE deleted SET state = ? WHERE language = ? AND note_id = ?",
                                                (swap_state[r["word"]], language, r["note_id"]))
        return out
    finally:
        if own:
            ledger.close()


def _swap_state(out, row):
    """{word: state} for a Bad card Swap dropped because its word is Known / Ignored now (its own test)."""
    for note, word, reason in out["skipped"]:
        if note == row["note_id"]:
            state = next((s for s in (WAS_KNOWN, WAS_IGNORED) if REFUSED[s] == reason), None)
            return {word: state} if state else {}
    return {}


def _act(language, rows, why, out, open_store):
    """Do the answer for `rows` -> {note_id: what its Undo needs}; a card it couldn't do is in `out["skipped"]`."""
    if not rows:
        return {}
    undos = {}
    if why in (BAD, LINE):
        from app.connect import swap
        for r in rows:
            try:
                got = swap.make_card(language, r["word"], r["reading"] or None, old_note=r["note_id"],
                                     by=swap.BY_BAD_CARD)
            except Exception as e:      # this one isn't asked (given back); the ones before it stand, recorded
                log.warning("Kyou-DW: Swap didn't take the ask for %s", r["word"], exc_info=True)
                out["skipped"].append((r["note_id"], r["word"], str(e) or type(e).__name__))
                continue
            if got.get("state") == swap.DROPPED:
                out["skipped"].append((r["note_id"], r["word"], REFUSED.get(got.get("why"), got.get("why") or "")))
                continue
            undos[r["note_id"]] = {"swap": got.get("id")}
            if why == LINE:             # only this sentence: its line is a parsing report too (Swap asked first:
                undos[r["note_id"]]["flag"] = _flag(language, r, out, open_store)   # nothing flagged for a drop)
        return undos
    from app.services import word_marks
    mark = "known" if why == KNOWN else "ignore"
    words = list(dict.fromkeys(r["word"] for r in rows))
    marked = word_marks.apply(language, [(w, mark) for w in words], undoable=False, unknow=mark == "ignore")
    if marked.error is not None:
        out["error"] = marked.error
        for r in rows:
            out["skipped"].append((r["note_id"], r["word"], REFUSED["busy"] if marked.busy else marked.error))
        return {}
    before = {w: b for w, b, _a in marked.done}
    for r in rows:
        undo = {"mark": mark, "before": before.get(r["word"], mark), "wrote": r["word"] in before}
        if why == PARSING:
            undo["flag"] = _flag(language, r, out, open_store)
        undos[r["note_id"]] = undo
    return undos


def _flag(language, r, out, open_store):
    """The card's line into Send report's list (source `loop`, reason parsing) -> its key, or None when the list
    refused it (Full, busy: the answer stands; the line is said missing)."""
    from app.services import flags
    show, episode = _place(language, r["item_id"], open_store)
    key = FLAG_KEY.format(note=r["note_id"])
    try:
        flags.add(language, r["sentence"] or r["word"], r["word"], "loop", key=key, show=show,
                  episode=episode, at=r["line_start"], reasons=(flags.PARSING,))
        return key
    except Exception as e:
        log.info("Kyou-DW: the line wasn't added to Send report's list (%s)", e)
        out.setdefault("unflagged", []).append((r["note_id"], r["word"], str(e)))
        return None


def undo(language, note_ids, ledger=None, settings=None):
    """Each answer taken back -> {"done": [(note_id, word)], "skipped": [(note_id, word, why)]}: the word's mark put as
    it was — only while it is still as the answer left it (`word_marks.states`) —, a Parsing mistake's line off Send
    report's list, a Bad card's new card through Swap's own Undo (`swap.act_undo`: refused, in Swap's words, while
    the card isn't made yet or once you've studied it); then the card asks again."""
    from app.connect import ledger as ledger_mod
    own = ledger is None
    ledger = ledger or ledger_mod.Ledger()
    out = {"done": [], "skipped": []}
    try:
        ensure(ledger)
        rows = _rows(ledger.conn, language, note_ids, answered=True)
        back = []
        marks = [r for r in rows if r["why"] in (KNOWN, IGNORE, PARSING)]
        if marks:
            from app.services import flags, word_marks
            now = word_marks.states(language, list({r["word"] for r in marks}))
            put, by_word = [], {}
            for r in marks:
                u = json.loads(r["undo"] or "{}")
                if u.get("wrote") and now.get(r["word"]) != u.get("mark"):
                    if now.get(r["word"]) == u.get("before"):   # put back already: an Undo whose record failed after
                        back.append((r, u))                     # (a locked ledger) finishes here, never "changed"
                        continue
                    out["skipped"].append((r["note_id"], r["word"], REFUSED["changed"]))
                    continue
                if u.get("wrote") and r["word"] not in by_word:
                    by_word[r["word"]] = u.get("before")
                    put.append((r["word"], u.get("before")))
                back.append((r, u))
            if put:
                got = word_marks.apply(language, put, undoable=False, unknow=True)  # as the loop's own Undo: what an
                # Ignore turned not known comes back (`review_loop.undo`)
                if got.error is not None:
                    out["skipped"] += [(r["note_id"], r["word"], REFUSED["busy"] if got.busy else got.error)
                                       for r, _u in back]
                    back = []
            for r, u in back:
                if u.get("flag"):
                    try:
                        flags.unflag(language, "loop", u["flag"], r["word"])
                    except Exception:
                        log.info("Kyou-DW: the line wasn't taken off Send report's list", exc_info=True)
        for r in rows:
            if r["why"] not in (BAD, LINE):
                continue
            from app.connect import swap
            u = json.loads(r["undo"] or "{}")
            got = swap.act_undo(settings or {}, language, u.get("swap")) if u.get("swap") is not None else {}
            if got.get("why") == swap.ALREADY:      # Swap undid it, then this record failed: the retry finishes it
                got = {}
            if got.get("why"):          # not made yet, studied, Anki closed: Swap's own words, the answer kept
                out["skipped"].append((r["note_id"], r["word"], got["why"]))     # (its line stays flagged too)
                continue
            if u.get("flag"):           # only this sentence: its line off Send report's list, once the card is back
                from app.services import flags
                try:
                    flags.unflag(language, "loop", u["flag"], r["word"])
                except Exception:
                    log.info("Kyou-DW: the line wasn't taken off Send report's list", exc_info=True)
            back.append((r, u))
        with ledger.transaction():
            for r, _u in back:
                ledger.conn.execute("UPDATE deleted SET why = NULL, why_at = NULL, undo = NULL WHERE language = ? AND "
                                    "note_id = ?", (language, r["note_id"]))
                out["done"].append((r["note_id"], r["word"]))
        return out
    finally:
        if own:
            ledger.close()
