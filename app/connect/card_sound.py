"""*Add sound* — the *Card sound* row's writer (AUDIO-FILL, 3.0.21; Sonic § 106 + § 108, TheForge
`research/audio-fill-2026-11-26/PLAN.md` lane 2; ROLES *Card sound*). `sound_source` decides (read only); this module
cuts, writes and takes back. The AI voice (`modules.irodori`) only makes a clip for a line it is handed.

- **Which cards** (decision 1): the notes in the deck Surasura works on (`fields.for_run`'s deck) whose sentence-audio
  field (Anki Miner's role `audio`) is exactly empty, never a suspended one — plus the notes still holding exactly an
  AI clip Surasura wrote (`ai_held`: the writer's own records), for decision 3.
- **Real sound first, for every card at once** (decision 2, never metered): `sound_source.plan`'s LINE / ELSEWHERE cut
  by `clips.cut` (the direct cut, the same bytes as Anki Miner's), AUDIOBOOK by `add_audio.cut` (Anki Miner's `media`),
  then ONE `sentence_audio.fill` (tag `TAG`). A card holding an untouched AI clip gets the real one through
  `sentence_audio.replace` (decision 3: only while the field still holds that clip; its own record).
- **The AI voice last, metered** (§ 106 1): only while the voice is on (`modules.irodori.on`), only the cards due in
  the window (`sound_source.due_days`, `days` 1 / 3 / 7, soonest first), Japanese only; the module hands the clips
  back (`irodori.clips_for_notes`: the by-line voice, the source's paragraph for a quote's middle sentence, the
  listen-back) and this module writes them (tag `AI_TAG`).
- **The card type follows its sound** (decision 4), for the cards Connect made only (its ledger's record), never one
  whose marks aren't the pair Anki Miner writes (an "x" in one mark field, the other empty): a sentence card made for
  want of sound (BOOK-CARD) becomes the learner's audio card once it has sound; an audio card still silent after the
  run becomes the sentence card until sound comes. Each through `sentence_audio.replace` (only while both marks are
  as read).
- **One Undo a run** (decision 9): the run's record (`RUN<id>` in the ledger's meta: its writer records, in order)
  undone newest first, each only where the note still holds what it wrote. **Remove all AI audio**: a count first, then
  every field still holding an AI clip emptied (Iro-C's hand-made ones too, by their tag: a copy of each kept first),
  each card's type following.
- Never the learner's audio (only an empty field, or Surasura's own untouched AI clip), never the schedule, never a
  field but the sound field and the two marks. Anki's sync is owed after any write (`undo.owe_sync`).

Costs (the DSA floor): one `findNotes` and one `notesInfo` (chunks of 50) for the candidates; the AI-held look is ONE
read of the writer's records (`ai_held`: {note: value}, records + notes, never a read a note); the plan's own costs
(`sound_source`); the window's `due_days` (days + ~40 id searches); one `fill` a kind; `replace` once a note only for a
real-over-AI swap or a type flip. Standard library; Anki through `sentence_audio.AnkiConnectNotes`.
"""
import json
import logging
import os
import re
import time

from app.connect import sentence_audio as sa

log = logging.getLogger(__name__)

TAG = sa.TAG                                    # real sound (Kura-AB3's, *Add audio*'s): "surasura::audio-added"
AI_TAG = "surasura::ai-audio"                   # the AI voice's clips (Iro-AA's tag, Iro-C's hand-made cards too)
BY, BY_AI, BY_SWAP, BY_TYPE, BY_REMOVE = ("card-sound", "card-sound-ai", "card-sound-swap", "card-sound-type",
                                          "card-sound-remove")
AI_BY = ("ai-audio", BY_AI)                     # the records that wrote an AI clip (the module's own before 3.0.21)
RUN = "card_sound_run:"                         # ledger meta: a run's id -> {"at", "records", "counts", "state"}
VERB = "Adding sound to cards"
DAYS = (1, 3, 7)                                # the AI voice's window (Sonic § 106 1: three choices)
DAYS_DEFAULT = 3                                # PROVISIONAL (the lead's lean)
MARK = "x"                                      # what Anki Miner writes into a card type's mark field
CHUNK = 50
_ONE_SOUND = re.compile(r"\s*\[sound:([^\]]+)\]\s*")
STOPPED = "stopped before its turn"             # `not_cut`'s why for a card a stop left (the next run cuts it)


def days_of(settings):
    """The AI voice's window from the settings (`card_sound_days`: 1 / 3 / 7; anything else the default)."""
    got = (settings or {}).get("card_sound_days")
    return got if got in DAYS else DAYS_DEFAULT


class Anki(sa.AnkiConnectNotes):
    """The writer's Anki, plus the two reads the press needs (a search, the due window)."""

    def find(self, query):
        from app import anki_connect
        return anki_connect.find_notes(self.url, query)

    def due(self, deck, days):
        from app.connect import sound_source
        return sound_source.due_days(self.url, deck, days)


# --- what the writer's records say --------------------------------------------------------------------------- #
def _records(ledger, after=""):
    """The writer's records after the id `after` (every one: ""), oldest first: [(id, record)] (one read of the meta
    table, by its key's index)."""
    out = []
    for key, value in ledger.conn.execute("SELECT key, value FROM meta WHERE key > ? AND key < ? ORDER BY key",
                                          (sa.RECORD + after, sa.RECORD[:-1] + chr(ord(sa.RECORD[-1]) + 1))):
        try:
            rec = json.loads(value)
        except (TypeError, ValueError):
            continue
        if isinstance(rec, dict):
            out.append((key[len(sa.RECORD):], rec))
    return out


def ai_held(ledger, records=None):
    """{note id: the AI clip's value} of the notes whose LAST write by Surasura was an AI clip still standing (its
    record done, not undone): what decision 3 may replace and *Remove all AI audio* takes off — still only where the
    field holds exactly that value (the caller compares). One pass over the records — those after the fold
    (`sa.FOLD`, made by `fold` once a day) on top of its snapshot, or `records` alone when handed in."""
    if records is not None:
        return _held_over(records, {})
    held, upto = _folded(ledger)
    return _held_over(_records(ledger, upto), held)


FOLD_MIN = 200                                  # records past the fold, a day old or more, before it moves on
FOLD_AGE_S = 86400


def _folded(ledger):
    """The fold's snapshot -> ({note: clip}, the last record id in it), or ({}, "") (none, or one that can't be read)."""
    upto = _upto(ledger)
    got = _meta_json(ledger, sa.FOLD, {}) if upto else {}
    try:
        if str(got.get("upto") or "") != upto:
            return {}, ""                       # (the two keys disagree: read every record)
        return {int(n): v for n, v in (got.get("held") or {}).items() if isinstance(v, str)}, upto
    except (TypeError, ValueError, AttributeError):
        return {}, ""


def _upto(ledger):
    got = _meta_json(ledger, sa.FOLD_UPTO, "")
    return got if isinstance(got, str) else ""


def fold(ledger):
    """The records a day old or more folded into `sa.FOLD` (`ai_held`'s snapshot), once FOLD_MIN of them are past the
    last fold — never past a record still being written (its Undo can still change it). An Undo of a folded record
    drops the fold (`sentence_audio._write_record`). -> how many were folded. Never raises."""
    try:
        cut = f"{time.time_ns() - FOLD_AGE_S * 10 ** 9}"
        with ledger.transaction():              # read and written together: an Undo meanwhile waits (it drops it)
            upto = _upto(ledger)
            n = ledger.conn.execute("SELECT count(*) FROM meta WHERE key > ? AND key < ?",
                                    (sa.RECORD + upto, sa.RECORD + cut)).fetchone()[0]
            if n < FOLD_MIN:
                return 0                        # (counted by the key's index: no record parsed)
            held, upto = _folded(ledger)
            old = []
            for rid, rec in _records(ledger, upto):
                if rid >= cut or rec.get("state") == sa.WRITING:
                    break
                old.append((rid, rec))
            if len(old) < FOLD_MIN:
                return 0
            held = _held_over(old, held)
            snap = {"upto": old[-1][0], "held": {str(n): v for n, v in sorted(held.items())}}
            ledger.conn.executemany("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                                    [(sa.FOLD, json.dumps(snap)), (sa.FOLD_UPTO, json.dumps(old[-1][0]))])
        return len(old)
    except Exception:
        log.info("Card sound: the writer's records weren't folded", exc_info=True)
        return 0


def _held_over(records, held):
    held = dict(held)
    for _rid, rec in records:
        notes = rec.get("notes") or {}
        done = rec.get("state") == sa.DONE
        ai = done and rec.get("tag") == AI_TAG and rec.get("mode") != sa.REPLACE and rec.get("by") in AI_BY
        for n, value in notes.items():
            try:
                n = int(n)
            except (TypeError, ValueError):
                continue
            if ai and isinstance(value, str):
                held[n] = value
            elif done and not (isinstance(value, dict) and n in held and held[n] in value.values()):
                held.pop(n, None)              # a later write of Surasura's: that one stands (a flip that wrote the
                #                                same AI clip back — decision 4's `_flips` — leaves it held)
    return held


# --- the run's own record -------------------------------------------------------------------------------------- #
def _new_run(ledger):
    return sa.new_id(ledger, RUN)                 # (past the newest run's: `last_run` takes the newest)


def _save_run(ledger, rid, rec):
    with ledger.transaction():
        ledger.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                            (RUN + rid, json.dumps(rec, ensure_ascii=False)))


def _save_some(ledger, rid, rec):
    """The run's record saved at its first write and every CHUNK after (a kill in between leaves the newest writes'
    own records, each with its Undo; the run's end or stop saves it whole)."""
    n = len(rec.get("records") or ())
    if n == 1 or n % CHUNK == 0:
        _save_run(ledger, rid, rec)


def run_record(ledger, rid):
    row = ledger.conn.execute("SELECT value FROM meta WHERE key = ?", (RUN + str(rid),)).fetchone()
    try:
        got = json.loads(row[0]) if row else None
    except (TypeError, ValueError):
        return None
    return got if isinstance(got, dict) else None


def last_run(ledger, language=None):
    """The newest run not undone (of `language`, when given) -> (id, record) or None."""
    rows = ledger.conn.execute("SELECT key, value FROM meta WHERE key LIKE ? ORDER BY key DESC", (RUN + "%",))
    for key, value in rows:
        try:
            rec = json.loads(value)
        except (TypeError, ValueError):
            continue
        if isinstance(rec, dict) and rec.get("state") != sa.UNDONE and rec.get("records") and (
                language is None or rec.get("language") == language):
            return key[len(RUN):], rec
    return None


# --- the card's two marks -------------------------------------------------------------------------------------- #
def _value(note, field):
    entry = ((note or {}).get("fields") or {}).get(field) if field else None
    if entry is None:
        return None
    return str(entry.get("value") or "") if isinstance(entry, dict) else str(entry)


def flip_of(note, marks, has_sound):
    """Decision 4 for one note -> (new, was) for `replace`, or None. `marks` (the sentence card's mark field, the audio
    card's): a note holding the sentence card's pair ("x", "") that has sound now becomes the audio card; one holding
    the audio card's pair ("", "x") still silent becomes the sentence card. Any other value in either (a type the
    learner set, another note type) is left as it is."""
    if not marks or not marks[0] or not marks[1]:
        return None
    s_mark, a_mark = marks
    s, a = _value(note, s_mark), _value(note, a_mark)
    if s is None or a is None:
        return None
    if has_sound and s == MARK and a == "":
        return {s_mark: "", a_mark: MARK}, {s_mark: MARK, a_mark: ""}
    if not has_sound and a == MARK and s == "":
        return {s_mark: MARK, a_mark: ""}, {s_mark: "", a_mark: MARK}
    return None


# --- the press ------------------------------------------------------------------------------------------------- #
def _notes(anki, ids):
    out = {}
    ids = sorted({int(n) for n in ids})
    for at in range(0, len(ids), CHUNK):
        out.update(sa._by_id(anki.notes(ids[at:at + CHUNK])))
    return out


def candidates(anki, deck, field):
    """The unsuspended notes in `deck` whose `field` is exactly empty (Anki's own search: `"<field>:"` matches only an
    empty field, a note type without it never)."""
    from app import anki_connect
    query = f'"{anki_connect.escape_query(field)}:" -is:suspended'
    if deck:
        query = f'"deck:{anki_connect.escape_query(deck)}" {query}'
    return [int(n) for n in anki.find(query) or ()]


def _in_deck(anki, deck, ids):
    """Of `ids`, those in `deck` and not suspended (one search) — the AI-held notes the press may swap."""
    if not ids:
        return set()
    from app import anki_connect
    query = "-is:suspended " + (f'"deck:{anki_connect.escape_query(deck)}" ' if deck else "") + \
        "nid:" + ",".join(str(int(n)) for n in sorted(ids))
    return {int(n) for n in anki.find(query) or ()}


def look(anki, ledger, language, mapping, steps, deck=None, ledger_path=None, only=None):
    """Read only: what *Add sound* would do now -> {"cards", "real", "ai", "silent", "swap", "plan", "notes", ...}:
    `cards` the soundless cards it would look at, `real` how many get real sound, `ai` how many wait for the AI voice
    (Japanese), `silent` none (Chinese), `swap` AI clips real sound would replace. `only`: these notes alone (the
    automatic pass: Connect's new cards and the AI voice's window), else every card in the deck."""
    from app.connect import sound_source
    field = (mapping.fields or {}).get("audio") if mapping is not None else None
    out = {"cards": 0, "real": 0, "ai": 0, "silent": 0, "swap": 0, "field": field, "plan": {}, "notes": {},
           "held": {}, "deck": deck}
    if not field:
        return out
    empty = candidates(anki, deck, field)
    held = ai_held(ledger)
    if only is not None:
        only = {int(n) for n in only}
        empty = [n for n in empty if n in only]
        held = {n: v for n, v in held.items() if n in only}
    swap = _in_deck(anki, deck, set(held) - set(empty))
    notes = _notes(anki, set(empty) | swap)
    held_now = {n: v for n, v in held.items() if n in swap and _value(notes.get(n), field) == v}
    blank = []
    for n in sorted(notes):
        note = notes[n]
        if n in held_now:                       # as if empty: may real sound replace it? (decision 3)
            fields = dict(note.get("fields") or {})
            fields[field] = dict(fields.get(field) or {}, value="")
            note = dict(note, fields=fields)
        blank.append(note)
    planned = sound_source.plan(language, blank, mapping, steps, ledger_path=ledger_path)
    for n, src in planned.items():
        if n in held_now:
            if src.kind != sound_source.NONE:
                out["swap"] += 1
            continue
        if src.kind != sound_source.NONE:
            out["real"] += 1
        elif src.why == sound_source.AI:
            out["ai"] += 1
        elif src.why == sound_source.SILENT:
            out["silent"] += 1
    out.update(cards=out["real"] + out["ai"] + out["silent"], plan=planned, notes=notes, held=held_now)
    return out


def _cut_real(language, planned, settings, steps, cut_line, cut_book, run_dir, should_stop=None):
    """The real clips -> ({note id: clip path}, {note id: why not}). A line's cut once for every card of it;
    `should_stop()` asked between two lines (a part come in goes first: the rest wait for the next run)."""
    from app.connect import sound_source
    clips, why, lines, book = {}, {}, {}, {}
    for n, src in planned.items():
        if src.kind in (sound_source.LINE, sound_source.ELSEWHERE) and src.line_id:
            lines.setdefault(src.line_id, []).append(n)
        elif src.kind == sound_source.AUDIOBOOK and src.cue is not None:
            book[n] = src.cue
    for line_id, nids in sorted(lines.items()):
        if should_stop and should_stop():
            for n in planned:
                if n not in clips:
                    why.setdefault(n, STOPPED)
            return clips, why
        try:
            path = cut_line(language, line_id, settings, steps)
        except Exception as e:                  # (`clips.Refused`, a disk): those cards wait for the next run
            for n in nids:
                why[n] = getattr(e, "message", None) or str(e) or type(e).__name__
            continue
        for n in nids:
            clips[n] = path
    if book:
        try:
            got = cut_book(language, book, run_dir) or {}
        except Exception as e:
            got = {}
            for n in book:
                why[n] = getattr(e, "message", None) or str(e) or type(e).__name__
        clips.update({int(n): p for n, p in got.items()})
        for n in book:
            if n not in clips:
                why.setdefault(n, "no clip was cut for its line")
    return clips, why


def _fill(anki, ledger, clips, field, tag, by, records):
    if not clips:
        return {"filled": [], "skipped": {}}
    got = sa.fill(anki, ledger, clips, field=field, tag=tag, by=by, verb=VERB)
    if got.get("id"):
        records.append(got["id"])
    return got


def _replace(anki, ledger, n, new, was, records, media=None, keep_dir=None, tag=None, by=BY_TYPE):
    got = sa.replace(anki, ledger, n, new, was, media=media, keep_dir=keep_dir, tag=tag, by=by, verb=VERB)
    if got.get("id"):
        records.append(got["id"])
    return bool(got.get("filled"))


def _keep_dir():
    from app.cli.verbs import _connect_folder
    return os.path.join(_connect_folder(), "card-sound", "kept")


def run(anki, ledger, language, mapping, steps, settings=None, deck=None, ai=None, days=None, should_stop=None,
        cut_line=None, cut_book=None, make_ai=None, kinds=None, paragraphs=None, run_dir=None, ledger_path=None,
        keep_dir=None, marks=None, only=None, due=None, ai_hold=None):
    """*Add sound* once -> {"id" (the run's Undo, None when nothing was written), "real", "swapped", "ai", "flipped",
    "waiting" (AI cards outside the window, or the voice off), "silent", "not_cut" {note: why}, "ai_report"}.
    `ai`: the AI voice's maker is called (None: while `modules.irodori.on`); `make_ai(note ids, kinds, paragraphs)` ->
    the module's report with `files` {note id: clip}; `cut_line(language, line_id, settings, steps)` -> a clip path
    (`clips.cut`); `cut_book(language, {note: cue}, run_dir)` -> {note: clip} (`add_audio.cut`); `marks` (the sentence
    card's mark field, the audio card's) for decision 4 (None: no flips); `only` as `look`'s; `due` the window
    already read ({note: day}; None: read here); `ai_hold()` True: the AI voice isn't started this run (the PC busy:
    asked once before it starts, never between its sentences — its own load would stop it). Raises the writer's
    Reviewing / Busy and AnkiConnect's errors; a write already made keeps its record, and the run's record names it
    (its Undo works)."""
    from app.connect import sound_source
    settings = settings or {}
    seen = look(anki, ledger, language, mapping, steps, deck=deck, ledger_path=ledger_path, only=only)
    field, planned, notes, held = seen["field"], seen["plan"], seen["notes"], seen["held"]
    out = {"id": None, "real": 0, "swapped": 0, "ai": 0, "flipped": 0, "waiting": 0, "silent": seen["silent"],
           "not_cut": {}, "ai_report": None, "kinds": {n: _kind(s) for n, s in planned.items() if n not in held}}
    if not field or not planned:
        return out
    rid, records = _new_run(ledger), []
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "language": language, "records": records,
           "counts": {}, "state": sa.WRITING}
    keep_dir = keep_dir or _keep_dir()
    try:
        real = {n: s for n, s in planned.items() if s.kind != sound_source.NONE}
        clips, out["not_cut"] = _cut_real(language, real, settings, steps, cut_line or _cut_line,
                                          cut_book or _cut_book(settings, language), run_dir, should_stop)
        got = _fill(anki, ledger, {n: p for n, p in clips.items() if n not in held}, field, TAG, BY, records)
        if records:
            _save_run(ledger, rid, rec)
        out["real"] = len(got["filled"])
        wrote = set(got["filled"])
        for n in sorted(set(clips) & set(held)):                # decision 3: only over its own untouched AI clip
            name = sa.clip_name(clips[n])[0]
            if _replace(anki, ledger, n, {field: sa.sound(name)}, {field: held[n]}, records,
                        media={name: clips[n]}, keep_dir=keep_dir, tag=TAG, by=BY_SWAP):
                out["swapped"] += 1
                wrote.add(n)
                _save_some(ledger, rid, rec)
        ai_turn = {n for n, s in planned.items() if s.kind == sound_source.NONE and s.why == sound_source.AI
                   and n not in held}
        voice_on = _voice_on(settings, language) if ai is None else bool(ai)
        if ai_turn and voice_on and not (should_stop and should_stop()) and not (ai_hold and ai_hold()):
            due = due if due is not None else anki.due(deck, days if days is not None else days_of(settings))
            order = sorted((n for n in ai_turn if n in due), key=lambda n: (due[n], n))      # soonest first
            out["waiting"] = len(ai_turn) - len(order)
            if order:
                items = _items_or_none(language, steps, order, ledger_path) \
                    if kinds is None or paragraphs is None else None
                report = (make_ai or _make_ai(settings, language, should_stop))(
                    order, kinds if kinds is not None else _kinds(language, steps, order, ledger_path, items),
                    paragraphs if paragraphs is not None else _paragraphs(language, steps, order, notes, mapping,
                                                                         ledger_path, items))
                out["ai_report"] = report
                files = {int(n): p for n, p in ((report or {}).get("files") or {}).items()}
                got = _fill(anki, ledger, files, field, AI_TAG, BY_AI, records)
                out["ai"] = len(got["filled"])
                wrote |= set(got["filled"])
                if records:
                    _save_run(ledger, rid, rec)
        else:
            out["waiting"] = len(ai_turn)
        if marks:                               # the cards written now, and those whose type is off already (as read)
            off = {n for n, note in notes.items() if n not in wrote and _value(note, field) is not None
                   and flip_of(note, marks, bool(_value(note, field)))}
            out["flipped"] = _flips(anki, ledger, language, sorted(wrote | off), field, marks, records, ledger_path,
                                    lambda: _save_some(ledger, rid, rec))
    except BaseException as e:
        inner = getattr(e, "sentence_audio_id", None)
        if inner and inner not in records:
            records.append(inner)
        e.card_sound_report = out["ai_report"]          # (auto keeps a refused clip's day even so)
        if records:
            e.card_sound_id = rid
            try:
                _save_run(ledger, rid, dict(rec, state=sa.DONE, stopped=True))
            except Exception:
                log.warning("Card sound: a stopped run's record couldn't be saved", exc_info=True)
        raise
    if records:
        rec.update(state=sa.DONE, counts={k: out[k] for k in ("real", "swapped", "ai", "flipped")})
        _save_run(ledger, rid, rec)
        out["id"] = rid
    return out


def _flips(anki, ledger, language, nids, field, marks, records, ledger_path, saved):
    """Decision 4 over `nids` after the writes -> how many flipped: the cards Connect made (its ledger), read again
    (one `notesInfo`), each one's type made to follow its sound now — the sound field written back as it is in the
    same `replace`, so a sound added or taken off meanwhile refuses the flip (CHANGED)."""
    from app.connect import ledger as ledger_mod
    made = set(ledger_mod.note_lines(ledger_path or ledger_mod.path(), list(nids), language))
    if not made:
        return 0
    now, flipped = _notes(anki, made), 0
    for n in sorted(made):
        sound = _value(now.get(n), field)
        flip = flip_of(now.get(n), marks, bool(sound)) if sound is not None else None
        if flip and _replace(anki, ledger, n, dict(flip[0], **{field: sound}), dict(flip[1], **{field: sound}),
                             records, by=BY_TYPE):
            flipped += 1
            saved()
    return flipped


def undo(anki, ledger, rid):
    """A run's one Undo -> {"emptied", "kept", "refused"?}: its records undone newest first (each only where the note
    still holds what it wrote: an edit of yours since stays), then the run closed."""
    rec = run_record(ledger, rid)
    if rec is None or rec.get("state") == sa.UNDONE:
        return {"emptied": [], "kept": {}, "refused": "nothing to undo"}
    emptied, kept = [], {}
    for record_id in reversed(rec.get("records") or ()):
        got = sa.undo(anki, ledger, record_id, verb=VERB)
        emptied += [n for n in got.get("emptied") or () if n not in emptied]
        kept.update(got.get("kept") or {})
    _save_run(ledger, rid, dict(rec, state=sa.UNDONE, undone_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
    return {"emptied": sorted(emptied), "kept": kept}


def ai_cards(anki, ledger, field, deck=None):
    """Read only: the notes *Remove all AI audio* would empty -> {note id: the field's value}: every note whose field
    still holds exactly the AI clip Surasura's writer put there (`ai_held`), and every note tagged `AI_TAG` (Iro-C's
    hand-made cards) whose field holds that one clip alone and nothing else."""
    from app import anki_connect
    held = ai_held(ledger)
    if deck and held:
        inside = _in_deck(anki, deck, set(held))
        held = {n: v for n, v in held.items() if n in inside}
    query = f'"tag:{AI_TAG}"' + (f' "deck:{anki_connect.escape_query(deck)}"' if deck else "")
    tagged = set(anki.find(query) or ())
    notes = _notes(anki, set(held) | tagged)
    out = {}
    for n, note in notes.items():
        value = _value(note, field)
        if not value:
            continue
        if n in held:
            if value == held[n]:
                out[n] = value
        elif n in tagged and _ONE_SOUND.fullmatch(value):
            out[n] = value
    return out


def remove_ai_audio(anki, ledger, language, field, deck=None, confirm=False, marks=None, ledger_path=None, keep_dir=None):
    """*Remove all AI audio* -> {"cards": n} without `confirm` (the count first); with it {"id", "removed", "flipped"}:
    each field still holding an AI clip emptied through `replace` (a copy of the clip kept, so the run's Undo puts it
    back), then each such card Connect made, now silent, becomes the sentence card (decision 4)."""
    found = ai_cards(anki, ledger, field, deck)
    if not confirm:
        return {"cards": len(found)}
    rid, records = _new_run(ledger), []
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "language": language, "records": records,
           "counts": {}, "state": sa.WRITING, "kind": "remove-ai"}
    removed, flipped = [], 0
    keep_dir = keep_dir or _keep_dir()
    try:
        for n, value in sorted(found.items()):
            if _replace(anki, ledger, n, {field: ""}, {field: value}, records, keep_dir=keep_dir, by=BY_REMOVE):
                removed.append(n)
                _save_some(ledger, rid, rec)
        if marks and removed:
            flipped = _flips(anki, ledger, language, removed, field, marks, records, ledger_path,
                             lambda: _save_some(ledger, rid, rec))
    except BaseException as e:
        if records:
            e.card_sound_id = rid
            try:
                _save_run(ledger, rid, dict(rec, state=sa.DONE, stopped=True))
            except Exception:
                log.warning("Card sound: a stopped removal's record couldn't be saved", exc_info=True)
        raise
    if not records:
        return {"id": None, "removed": [], "flipped": 0}
    _save_run(ledger, rid, dict(rec, state=sa.DONE, counts={"removed": len(removed), "flipped": flipped}))
    return {"id": rid, "removed": removed, "flipped": flipped}


# --- the real pieces each default stands for ------------------------------------------------------------------- #
def _cut_line(language, line_id, settings, steps):
    from app.connect import clips
    return clips.cut(language, line_id, settings=settings, steps=steps)


def _cut_book(settings, language):
    def cut(lang, can, run_dir):
        from app.cli.verbs import _anki_miner_setup
        from app.connect import add_audio, anki_miner
        os.makedirs(run_dir, exist_ok=True)
        setup = _anki_miner_setup(settings, lang, run_dir, held=_HELD.setdefault(lang, {}))   # AM-START 2: the press's
        if setup is None:
            return {}
        return add_audio.cut(anki_miner.find(settings), lang, setup[1], can, run_dir)
    return cut


def _voice_on(settings, language):
    try:
        from modules import irodori
    except ImportError:
        return False
    try:
        return bool(irodori.on(settings, language))
    except Exception:
        return False


def _make_ai(settings, language, should_stop):
    def make(note_ids, kinds, paragraphs):
        from modules import irodori
        return irodori.clips_for_notes(settings, language, note_ids, kinds=kinds, paragraphs=paragraphs,
                                       should_stop=should_stop, source="card-sound")
    return make


def _items(language, steps, nids, ledger_path):
    """{note id: (item id, rel path)} of the notes Connect made (its ledger, then one read of the store)."""
    from app.connect import ledger as ledger_mod
    lines = ledger_mod.note_lines(ledger_path or ledger_mod.path(), list(nids), language)
    ids = sorted({int(v[0]) for v in lines.values() if v and v[0] is not None})
    if not ids:
        return {}
    rel = {}
    with steps._open(language) as store:
        with store._reading():
            for at in range(0, len(ids), 500):
                part = ids[at:at + 500]
                rel.update(store.conn.execute(f"SELECT id, rel_path FROM items WHERE id IN ({','.join('?' * len(part))})",
                                              part).fetchall())
    return {n: (int(v[0]), rel.get(int(v[0]))) for n, v in lines.items() if v and v[0] is not None}


def _items_or_none(language, steps, nids, ledger_path):
    try:
        return _items(language, steps, nids, ledger_path)
    except Exception:
        log.info("Card sound: the cards' items couldn't be read", exc_info=True)
        return {}


def _is_book(rel):
    from app import cues
    low = str(rel or "").lower()
    return bool(low) and not low.endswith(cues.SUBTITLES)


def _kinds(language, steps, nids, ledger_path, items=None):
    """{note id: "book"} for the cards Connect made from a book or a text (their narration: a narrator); the rest are
    left out (speech: a conversational voice, IRO-P's P2). `items`: `_items`' answer already read."""
    if items is None:
        items = _items_or_none(language, steps, nids, ledger_path)
    return {n: "book" for n, (_item, rel) in items.items() if _is_book(rel)}


PARAGRAPH_BEFORE = 8                            # sentences before the card's read as its paragraph (a quote's start)


def _paragraphs(language, steps, nids, notes, mapping, ledger_path, items=None):
    """`_paragraph_texts`, never raising: a token store that can't be read gives none (each line read alone)."""
    try:
        return _paragraph_texts(language, steps, nids, notes, mapping, ledger_path, items)
    except Exception:
        log.info("Card sound: the paragraphs couldn't be read", exc_info=True)
        return {}


def _paragraph_texts(language, steps, nids, notes, mapping, ledger_path, items=None):
    """{note id: the text around its sentence in its book} — the sentences before it and itself, from the token
    store's texts of its item (one read a book part), so the by-line rule sees a long quote's middle sentence inside
    its 「」 (IRO-P's note). A note not found there has none (the rule reads the line alone)."""
    from app.connect import add_audio, lineup
    if items is None:
        items = _items_or_none(language, steps, nids, ledger_path)
    items = {n: v for n, v in items.items() if _is_book(v[1])}
    if not items:
        return {}
    from app import token_index
    from app.path_utils import get_data_path
    root = get_data_path(language)
    by_path = {}
    for n, (_item, rel) in items.items():
        path = os.path.join(root, *str(rel).replace("\\", "/").split("/"))
        by_path.setdefault(path, []).append(n)
    out = {}
    store = token_index.open_store(language)
    try:
        for path, ns in by_path.items():
            try:
                texts = store.file_texts(path) or []
            except Exception:
                continue
            at = {}
            for i, text in enumerate(texts):
                at.setdefault(lineup.clean(text), i)
            for n in ns:
                raw = _value(notes.get(n), mapping.sentence) if mapping is not None else None
                i = at.get(lineup.clean(add_audio._text(raw or "")))
                if i is not None:
                    out[n] = "".join(texts[max(0, i - PARAGRAPH_BEFORE):i + 1])
    finally:
        store.close()
    return out


# --- the one door: the window's press, its Undo, *Remove all AI audio*, and the command line ------------------- #
NOTHING = "No card here is missing its sentence audio."
NO_MINER = "Anki Miner isn't installed: it reads which field holds a card's sound."
NO_FIELD = "Anki Miner's field mapping names no field for the sentence's audio, so there's nowhere to put it."
NO_UNDO = "There's no Add sound with that number."
UNDO_OFF = "Connect is off, so the sound couldn't be taken back"
_HELD = {}                                      # language -> the Anki Miner set `_anki_miner_setup` keeps (15 min)


def act(settings, language, confirm=False, undo_id=None, remove_ai=False, should_stop=None, ai=None):
    """*Add sound* as the window and the command line ask it -> without `confirm` the count (`look`'s numbers, nothing
    written); with it the run (`run`'s answer); `undo_id` that run's Undo; `remove_ai` *Remove all AI audio* (its
    count first, then with `confirm` the removal); {"skipped": why} with Connect off or Anki switched off for the run.
    Anki's sync is owed after any write (a partial one too). Raises CliError in plain words (`add_audio._plain`)."""
    import shutil
    from app.cli.contract import CliError
    from app.connect import add_audio, undo as undoing
    if not (settings or {}).get("connect_enabled"):
        return {"skipped": undoing.PREVIEW_OFF}
    from app.cli.verbs import require_set_up
    require_set_up(language)
    if os.environ.get("SURASURA_NO_ANKI_SYNC"):
        return {"skipped": undoing.NO_ANKI}
    from app import anki_connect
    from app.connect.ledger import Ledger
    anki = Anki(anki_connect.address(settings))
    run_dir = None
    try:
        with Ledger() as ledger:
            if undo_id is not None:
                if run_record(ledger, undo_id) is None:
                    raise CliError("bad-data", NO_UNDO, undo=undo_id)
                try:
                    done = undo(anki, ledger, undo_id)
                except BaseException:
                    undoing.owe_sync(settings)          # a part already put back: its sync is owed
                    raise
                if done.get("emptied"):
                    undoing.owe_sync(settings)
                return dict(done, language=language, undo=undo_id)
            from app.connect import fields, runner
            run_dir, mapping = _mapping(settings, language)
            if mapping is None:
                return {"language": language, "skipped": NO_MINER}
            field = (mapping.fields or {}).get("audio")
            if not field:
                raise CliError("needs-you", NO_FIELD)
            marks = fields.marks(mapping)
            if remove_ai:
                done = remove_ai_audio(anki, ledger, language, field, deck=mapping.deck, confirm=confirm,
                                       marks=marks)
                if done.get("id"):
                    undoing.owe_sync(settings)
                return dict(done, language=language, confirm=bool(confirm))
            steps = runner.Steps(settings)
            if not confirm:
                seen = look(anki, ledger, language, mapping, steps, deck=mapping.deck)
                return {"language": language, "confirm": False,
                        **{k: seen[k] for k in ("cards", "real", "ai", "silent", "swap")},
                        "voice": _voice_on(settings, language), "days": days_of(settings)}
            done = run(anki, ledger, language, mapping, steps, settings=settings, deck=mapping.deck, ai=ai,
                       should_stop=should_stop, run_dir=run_dir, marks=marks)
            if done["id"]:
                undoing.owe_sync(settings)
            _recount_quietly(anki, ledger, language, mapping, steps, known=done.pop("kinds", None))
            report = done.pop("ai_report") or {}
            return dict(done, language=language, confirm=True, problems=list(report.get("problems") or ()),
                        not_cut=len(done["not_cut"]))
    except CliError as e:
        rid = getattr(e, "card_sound_id", None)
        if rid is None:
            raise
        undoing.owe_sync(settings)
        raise CliError(e.code, e.message, **dict(e.context, undo=rid)) from None
    except BaseException as e:
        rid = getattr(e, "card_sound_id", None)
        if rid is not None:
            undoing.owe_sync(settings)
        err = add_audio._plain(e)
        if err is None:
            raise
        if rid is not None:
            err = CliError(err.code, err.message, **dict(err.context, undo=rid))
        raise err from None
    finally:
        if run_dir:
            shutil.rmtree(run_dir, ignore_errors=True)      # the clips are Anki's now (or were never written)


def _mapping(settings, language):
    """A run's folder and Anki Miner's field mapping (None: Anki Miner isn't installed) — the set held 15 min a
    language (`_anki_miner_setup`'s `held`)."""
    from app.cli.verbs import _anki_miner_setup, _connect_folder
    run_dir = os.path.join(_connect_folder(), "card-sound", f"{time.time_ns()}")
    os.makedirs(run_dir, exist_ok=True)
    setup = _anki_miner_setup(settings, language, run_dir, held=_HELD.setdefault(language, {}))
    return run_dir, (setup[2] if setup is not None else None)


# --- Connect's automatic pass (§ 106: new cards get sound by themselves while the switch is on) ---------------- #
NEW = "card_sound_new:"                         # ledger meta: <lang> -> the cards Connect made, not looked at yet
TRIED = "card_sound_tried:"                     # ledger meta: <lang> -> {"day", "notes"}: no AI clip passed today
NEW_MAX = 5000                                  # the waiting list's cap (oldest dropped: the press still finds them)


def _meta_json(ledger, key, default):
    row = ledger.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    try:
        got = json.loads(row[0]) if row else default
    except (TypeError, ValueError):
        return default
    return got if isinstance(got, type(default)) else default


def _put_meta(ledger, key, value):
    with ledger.transaction():
        if value:
            ledger.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, json.dumps(value)))
        else:
            ledger.conn.execute("DELETE FROM meta WHERE key = ?", (key,))


def queue_new(ledger, language, ids):
    """A part's new cards (`runner._fill`), for the automatic pass to look at once. Never raises."""
    try:
        got = dict.fromkeys(int(n) for n in _meta_json(ledger, NEW + language, []))
        got.update(dict.fromkeys(int(n) for n in ids or ()))
        _put_meta(ledger, NEW + language, list(got)[-NEW_MAX:])
    except Exception:
        log.warning("Card sound couldn't note %d new cards (%s)", len(ids or ()), language, exc_info=True)


def _today():
    return time.strftime("%Y-%m-%d")


def _tried(ledger, language):
    got = _meta_json(ledger, TRIED + language, {})
    return {int(n) for n in got.get("notes") or ()} if got.get("day") == _today() else set()


def auto(settings, language, ledger, steps=None, should_stop=None, ai_hold=None, ai_stop=None,
         ledger_path=None):
    """Connect's automatic pass (`runner._card_sound`, the end of its pass) -> `run`'s answer, or {"skipped": why}:
    the cards Connect made since the last pass (`queue_new`) get their real sound; while the AI voice is on and
    `ai_hold()` says go (the PC quiet: asked once, after the real sound), the soundless cards due in the window get
    the voice too, soonest
    first — but none whose clip the voice's check refused today (tried again tomorrow, never every pass).
    `ledger`, `steps`: Connect's own (the pass's). `should_stop` between two lines and two sentences; `ai_stop` the
    voice's own (its switch read again).
    Costs: the waiting list and the window's ids only (never the whole deck's plan): one search of the deck's
    soundless cards, the window (`due_days`), then `run` over those alone."""
    import shutil
    from app.connect import undo as undoing
    if not (settings or {}).get("connect_enabled") or os.environ.get("SURASURA_NO_ANKI_SYNC"):
        return {"skipped": undoing.PREVIEW_OFF}
    from app import anki_connect
    from app.connect import fields, runner
    anki, run_dir = Anki(anki_connect.address(settings)), None
    try:
        new = [int(n) for n in _meta_json(ledger, NEW + language, [])]
        ai = _voice_on(settings, language)
        if not new and not ai and _meta_json(ledger, COUNT + language, {}).get("day") == _today():
            return {"skipped": NOTHING}         # (counted today, nothing new: a new day or `forget` counts again)
        run_dir, mapping = _mapping(settings, language)
        if mapping is None:
            return {"skipped": NO_MINER}
        tried = _tried(ledger, language)
        if ai and ai_hold is not None and ai_hold():
            ai = False                          # the PC busy: real sound only this pass (asked once, never between)
        due = {n: d for n, d in (anki.due(mapping.deck, days_of(settings)) if ai else {}).items()
               if n not in tried}
        only = set(new) | set(due)
        done = {"id": None}
        if only:
            done = run(anki, ledger, language, mapping, steps or runner.Steps(settings), settings=settings,
                       deck=mapping.deck, ai=ai, due=due, only=only, should_stop=should_stop,
                       make_ai=_make_ai(settings, language, ai_stop or should_stop), run_dir=run_dir,
                       marks=fields.marks(mapping), ledger_path=ledger_path)
        _recount_quietly(anki, ledger, language, mapping, steps or runner.Steps(settings), ledger_path,
                         known=done.pop("kinds", None))
        unheard = {int(n) for n in ((done.get("ai_report") or {}).get("unheard") or ())}
        if unheard:
            _put_meta(ledger, TRIED + language, {"day": _today(), "notes": sorted(tried | unheard)})
        looked = set(new) - {n for n, why in (done.get("not_cut") or {}).items() if why == STOPPED}
        _put_meta(ledger, NEW + language, [n for n in _meta_json(ledger, NEW + language, []) if n not in looked])
        if done.get("id"):
            undoing.owe_sync(settings)
        return done
    except BaseException as e:
        if getattr(e, "card_sound_id", None) is not None:
            undoing.owe_sync(settings)              # a part written before the stop: its Undo works, its sync is owed
        unheard = {int(n) for n in ((getattr(e, "card_sound_report", None) or {}).get("unheard") or ())}
        if unheard:
            try:
                kept = sorted(_tried(ledger, language) | unheard)
                _put_meta(ledger, TRIED + language, {"day": _today(), "notes": kept})
            except Exception:
                pass
        raise
    finally:
        if run_dir:
            shutil.rmtree(run_dir, ignore_errors=True)


# --- *Needs you*'s count (Connect keeps it; the window reads it) ------------------------------------------------ #
COUNT = "card_sound_count:"                     # ledger meta: <lang> -> {"cards", "real", "ai", "silent", "at"}
SEEN = "card_sound_seen:"                       # ledger meta: <lang> -> {"day", "kinds": {note: REAL / AI / SILENT}}
REAL, AI, SILENT, OTHER = "real", "ai", "silent", "other"


def _kind(src):
    from app.connect import sound_source
    return (OTHER if src is None else REAL if src.kind != sound_source.NONE else
            AI if src.why == sound_source.AI else SILENT if src.why == sound_source.SILENT else OTHER)


def recount(anki, ledger, language, mapping, steps, ledger_path=None, known=None):
    """*Needs you*'s count -> {"cards", "real", "ai", "silent", "at"} (kept in the ledger, COUNT), or None (no audio
    field): of the deck's soundless unsuspended cards, how many can get real sound now, how many wait for the AI
    voice, how many have none. Each card is planned once a day (SEEN: its answer kept; a card that got sound since
    drops out with the next search): one `findNotes`, then `sound_source.plan` over the cards not planned today
    only — never the whole deck at every pass. Its answer for a card can lag a day behind a library change (an
    episode added) — the press itself plans every card again. `known` ({note: kind}: the run just made, `run`'s
    `kinds`) stands for those cards' plans (never planned twice in one press). Folds the writer's old records too."""
    field = (mapping.fields or {}).get("audio") if mapping is not None else None
    if not field:
        return None
    empty = set(candidates(anki, mapping.deck, field))
    memo = _meta_json(ledger, SEEN + language, {})
    kinds = {}
    if memo.get("day") == _today():
        for n, kind in (memo.get("kinds") or {}).items():
            try:
                if int(n) in empty:
                    kinds[int(n)] = kind
            except (TypeError, ValueError):
                continue
    for n, kind in (known or {}).items():
        if n in empty:
            kinds[n] = kind
    todo = empty - set(kinds)
    if todo:
        planned = look(anki, ledger, language, mapping, steps, deck=mapping.deck, ledger_path=ledger_path,
                       only=todo)["plan"]
        for n in todo:
            kinds[n] = _kind(planned.get(n))
    counts = {k: sum(1 for v in kinds.values() if v == k) for k in (REAL, AI, SILENT)}
    counts.update(day=_today(), cards=counts[REAL] + counts[AI] + counts[SILENT], at=time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                                                     time.gmtime()))
    _put_meta(ledger, SEEN + language, {"day": _today(), "kinds": {str(n): k for n, k in sorted(kinds.items())}})
    _put_meta(ledger, COUNT + language, counts)
    fold(ledger)
    return counts


def forget(ledger, language):
    """The day memo of `recount` dropped (a book lined up with its audiobook: its cards may get real sound now), so the
    pass's end plans every soundless card again. Inside the caller's transaction; never raises."""
    try:
        ledger.conn.execute("DELETE FROM meta WHERE key = ?", (SEEN + language,))
        count = _meta_json(ledger, COUNT + language, {})
        if count.pop("day", None) is not None:          # (the pass reads the count's day: counted again at its end)
            ledger.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                                (COUNT + language, json.dumps(count)))
    except Exception:
        log.info("Card sound: the day memo wasn't dropped (%s)", language, exc_info=True)


def _recount_quietly(anki, ledger, language, mapping, steps, ledger_path=None, known=None):
    try:
        return recount(anki, ledger, language, mapping, steps, ledger_path=ledger_path, known=known)
    except Exception:
        log.info("Card sound: the count for Needs you wasn't kept (%s)", language, exc_info=True)
        return None


def counted(language, ledger_path=None):
    """(The window's worker.) The count Connect last kept (`recount`) -> {"cards", "real", "ai", "silent", "at"} or
    None (none kept, no ledger, a ledger that can't be read now). Read only, one row."""
    import sqlite3
    from pathlib import Path
    from app.connect import ledger as ledger_mod
    path = ledger_path or ledger_mod.path()
    if not os.path.isfile(path):
        return None
    try:
        conn = sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True, timeout=2.0, isolation_level=None)
        try:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (COUNT + language,)).fetchone()
        finally:
            conn.close()
        got = json.loads(row[0]) if row else None
    except (sqlite3.Error, TypeError, ValueError):
        return None
    if not isinstance(got, dict):
        return None
    try:
        return {k: max(0, int(got.get(k) or 0)) for k in ("cards", "real", "ai", "silent")} | {"at": got.get("at")}
    except (TypeError, ValueError):
        return None


# --- the window's press (*Needs you*, Settings › Anki & mining › *Card sound*) ---------------------------------- #
def press(language, settings):
    """(A worker.) *Add sound*: real sound on every card that can get it now (`act`, the AI voice left to Connect's
    pass: it voices the window's cards while the PC is quiet), then Connect kicked -> {"ok", "id" (its Undo), "real",
    "say"}. A "couldn't" -> {"ok": False, "say": its plain words}."""
    from app.cli.contract import CliError
    try:
        done = act(settings, language, confirm=True, ai=False)
    except CliError as e:
        return {"ok": False, "id": getattr(e, "context", {}).get("undo"), "say": e.message, "real": 0}
    if done.get("skipped"):
        return {"ok": False, "id": None, "say": None, "real": 0}
    _kick(settings)
    return {"ok": True, "id": done.get("id"), "real": done.get("real", 0) + done.get("swapped", 0),
            "not_cut": done.get("not_cut", 0), "say": None}


def press_undo(language, rid, settings):
    """(A worker.) The toast's *Undo* -> {"ok", "emptied", "kept", "say"}."""
    from app.cli.contract import CliError
    try:
        done = act(settings, language, undo_id=rid)
    except CliError as e:
        return {"ok": False, "say": e.message, "emptied": 0, "kept": 0}
    if done.get("skipped"):
        return {"ok": False, "say": UNDO_OFF, "emptied": 0, "kept": 0}
    if done.get("refused"):
        return {"ok": False, "say": done.get("refused") if done.get("refused") != "nothing to undo" else None,
                "emptied": 0, "kept": 0}
    return {"ok": True, "emptied": len(done.get("emptied") or ()), "kept": len(done.get("kept") or {}), "say": None}


def press_remove(language, settings, confirm=False):
    """(A worker.) Settings' *Remove all AI audio* -> without `confirm` the count first {"ok", "cards", "voice"}; with
    it {"ok", "id" (its Undo: `press_undo`), "removed", "say"} — Anki's write, a copy of each clip kept. A "couldn't"
    -> {"ok": False, "say": its plain words}."""
    from app.cli.contract import CliError
    try:
        done = act(settings, language, remove_ai=True, confirm=confirm)
    except CliError as e:
        return {"ok": False, "id": getattr(e, "context", {}).get("undo"), "say": e.message, "cards": 0, "removed": 0}
    if done.get("skipped"):
        return {"ok": False, "id": None, "say": NO_MINER if done["skipped"] == NO_MINER else None, "cards": 0,
                "removed": 0}
    if not confirm:
        return {"ok": True, "cards": int(done.get("cards") or 0), "voice": _voice_on(settings, language)}
    return {"ok": True, "id": done.get("id"), "removed": len(done.get("removed") or ()), "say": None}


def _kick(settings):
    try:
        from app.connect import kick
        kick.kick(settings or {})
    except Exception:
        log.info("Card sound: Connect wasn't kicked", exc_info=True)
