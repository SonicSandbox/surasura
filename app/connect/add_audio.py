"""*Add audio to these cards* (Kura-AB3, 2026-11-11; spec: TheForge `tracks/pipeline/work/AB3/add-audio-spec.md`;
PROVISIONAL): the narrator's voice put on the cards Connect made from a book before its audiobook was lined up.

- **Which cards** (`plan`, read only): the notes Connect made from the book's parts (the store's made words, the parts
  by the EPUB's `<epub>#<n>` origins), still in Anki, whose sentence-audio field — Anki Miner's role `audio` in the
  profile's mapping — is empty; each one's sentence (its sentence field, markup out) and word placed in the book's
  line-up (`runner.Steps.lined_up`: its own subtitle checked or trusted, or a finished sync of grade A/B) by
  `place` — the one cue of the whole book that is (or holds) that sentence, else the one cue inside it holding the word
  as the sentence writes it (its bold), never a neighbour's (review A1 S1, S3). -> *N can get the narrator's
  voice · M weren't heard (a skipped passage, a sentence the line-up didn't find) · K have audio already · J gone*.
- **The clips** (`cut`): Anki Miner's `media`, CUT_LINES lines a call (a book's thousand cards never one call: S6),
  one episode per audio file, each cue cut once (two cards of one cue share its clip); each answered line matched back
  to its cue by its start and its text, never by its place alone (S2); a line it cut no clip for is that card skipped —
  never another line's clip.
- **The write** (`run`): `sentence_audio.fill` — the one sentence-audio writer (only an empty field, read again under
  Anki's write lock; tagged `TAG`; one Undo record) — then the clips' run folder deleted (Anki holds them now).
- **Who asks** (`act`, the command line's `add-audio` and the window's one sequence): Connect on, Surasura set up, the
  ledger there (no ledger: Connect never made a card); the plan without `confirm`; `undo` by the record's id (an
  *Add audio*'s only); Anki's sync owed after any write, a partial one too, whose Undo id the error carries (S5); every
  failure in plain words (S4).

Light: the standard library; Anki through `sentence_audio.AnkiConnectNotes`, Anki Miner through `anki_miner`.
"""
import html
import json
import os
import re
import shutil
import sqlite3
import time

TAG = "surasura::audio-added"
BY = "add-audio"
NO_LEDGER = "Connect hasn't made any cards yet, so there are none to add audio to."
NOT_LINED = ("「{title}」 isn't lined up with its audiobook yet, so there's nothing to cut the audio from. Pair it with its "
             "audiobook and let Connect line it up (or trust its subtitle's timing) first.")
NO_BOOK = "That book isn't in the library: {book}"
NO_AUDIO_FIELD = "Anki Miner's field mapping names no field for the sentence's audio, so there's nowhere to put it."
REVIEWING = "You're reviewing in Anki. Add audio again when you're done."
NO_UNDO = "There's no audio added with that number."
NO_MINER = "Anki Miner isn't installed: it cuts the clips."
PART_WRITTEN = ("Some cards got their audio before this stopped ({why}). Undo takes them back: "
                "surasura-cli add-audio --undo {id}")
FILE_TROUBLE = "A file Add audio needs couldn't be read or written just now: "
NO_CLIP = "Anki Miner cut no clip for {n} of its lines (past the audio's end?)"
NOT_THE_LINES = "{n} of Anki Miner's answers weren't the lines asked for"
OTHER_COUNT = "Anki Miner answered another number of lines than asked"
CUT_LINES = 100                 # lines a `media` call (S6: each call bounded, never one for a whole book)
_MARKUP = re.compile(r"<[^>]*>")
_RUBY = re.compile(r"<(rt|rp)\b[^>]*>.*?</\1\s*>", re.I | re.S)       # furigana over the text: not the sentence
_BRACKETS = re.compile(r"\[[ぁ-ゖァ-ヺー]+\]")                         # Anki's 彼[かれ] furigana (kana only)
_BOLD = re.compile(r"<b\b[^>]*>(.*?)</b\s*>", re.I | re.S)


def _text(value):
    """A field's text as read aloud: furigana (ruby and Anki's brackets) and markup out, entities read."""
    text = _BRACKETS.sub("", _MARKUP.sub("", _RUBY.sub("", str(value or ""))))
    return html.unescape(text).replace("\xa0", " ").strip()


def _form(sentence_value, word):
    """The word as its sentence writes it (S3: Anki Miner bolds it there — 食べた, never the note's 食べる) when the
    sentence holds it (the bold sharing the word's kanji first), else the note's word when the sentence holds that, else
    None (the sentence alone says where)."""
    from app.connect import lineup
    want = lineup.clean(_text(sentence_value))
    bolds = [_text(m) for m in _BOLD.findall(str(sentence_value or ""))]
    kanji = {ch for ch in str(word or "") if "\u4e00" <= ch <= "\u9fff"}
    shared = [b for b in bolds if kanji & set(b)]      # r2 N7: a stray bold (emphasis) never stands for the word
    for form in shared + bolds + [word]:
        if lineup.clean(form) and lineup.clean(form) in want:
            return form
    return None


def place(sentence, form, found):
    """The cue a card's clip is cut from -> a Cue, or None (unheard). Across the WHOLE book (review A1 S1: an earlier
    short line inside the sentence never wins over the sentence's own cue): the one cue that IS the sentence; else the
    one cue holding it whole (MIN_CHARS or longer); else, of the cues inside it (MIN_CHARS or longer each: the sentence
    said over several cues), the one holding `form` (any of them when `form` is None) — two answers at any step is no
    answer (B-14), never a guess."""
    from app.connect import lineup
    want = lineup.clean(sentence)
    if not want:
        return None
    exact = [c for c in found if c.text == want]
    if exact:                                   # its words word for word (r3 S1: a longer line holding them elsewhere
        return exact[0] if len(exact) == 1 else None      # is never this one's rival)
    holders = [c for c in found if c.text and want in c.text] if len(want) >= lineup.MIN_CHARS else []
    if holders:
        return holders[0] if len(holders) == 1 else None
    hold = lineup.clean(form) if form else ""
    hits = [c for c in found if c.text and len(c.text) >= lineup.MIN_CHARS and c.text in want and
            (not hold or hold in c.text)]
    return hits[0] if len(hits) == 1 else None


def book_items(store, epub):
    """The book's live parts in the library (origins `<epub>#<n>`) -> [item ids]."""
    from app import library_store
    lo = library_store.SOURCE_KEY + library_store.path_key(os.path.abspath(epub)) + "#"
    with store._reading():
        return sorted({r[0] for r in store.conn.execute(
            f"SELECT p.item_id FROM pairings p WHERE p.content_key >= ? AND p.content_key < ? AND "
            f"{library_store._LIVE_ORIGIN}", (lo, lo[:-1] + "$"))})


def made_notes(store, items):
    """{note id: the made word} of the notes Connect made from `items` (the store's made words)."""
    want, out = set(items), {}
    if not want or not store.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'made_words'").fetchone():
        return out
    with store._reading():
        for item_id, word, ids in store.conn.execute("SELECT item_id, word, note_ids FROM made_words"):
            if item_id not in want:
                continue
            try:
                for note in json.loads(ids):
                    out[int(note)] = word
            except (TypeError, ValueError):
                continue
    return out


def plan(anki, steps, lang, epub, mapping):
    """What *Add audio* would do now, read only -> {"title", "lined" (bool), "field", "can" {note id: lineup.Cue},
    "has_audio", "unheard", "gone" [note ids]}."""
    from app.connect import library, lineup
    from app.connect import sentence_audio as sa
    field = (mapping.fields or {}).get("audio") if mapping is not None else None
    with steps._open(lang) as store:
        items = book_items(store, epub)
        notes = made_notes(store, items)
        book = library.book_of(store, epub)
    title = (book or {}).get("title") or os.path.splitext(os.path.basename(epub))[0]
    out = {"title": title, "lined": False, "field": field, "can": {}, "has_audio": [], "unheard": [], "gone": [],
           "items": items}
    lined = steps.lined_up(lang, epub)
    if not lined:
        return out
    out["lined"] = True
    found = lineup.cues(lined["lineup"])
    info = {int(n["noteId"]): n for n in anki.notes(sorted(notes)) or () if isinstance(n, dict) and n.get("noteId")}
    for note_id in sorted(notes):
        note = info.get(note_id)
        if note is None:
            out["gone"].append(note_id)
            continue
        fields = note.get("fields") or {}
        if not field or field not in fields:
            out["unheard"].append(note_id)
            continue
        if sa._why_not(note, field) is not None:
            out["has_audio"].append(note_id)
            continue
        raw = (fields.get(mapping.sentence) or {}).get("value") if mapping.sentence else ""
        sentence = _text(raw)
        word = _text((fields.get(mapping.word) or {}).get("value")) or notes[note_id]
        cue = place(sentence, _form(raw, word), found) if sentence and found else None
        if cue is None:
            out["unheard"].append(note_id)
        else:
            out["can"][note_id] = cue
    return out


def cut(miner, lang, profile, can, run_dir, timeout=None, troubles=None):
    """The clips of `can` ({note id: Cue}) -> {note id: clip path}: Anki Miner's `media`, CUT_LINES cues a call (S6), an
    episode per audio file, each cue once (two cards of one cue share its clip). Each answered line is matched back to
    its cue only when its `line_start` and its length are the cue's (within `anki_miner.LINE_TOLERANCE`: two cues of
    one start are two cues, Anki Miner's nearest line the first's — r2 S1) and its text holds the cue's or sits inside
    it (Anki Miner drops a speaker tag) — else, a line it cut no clip for, an answer of another length or a run that
    refused that file, those cards are left out. A refusal of the first call is raised; of a later one, the cutting
    stops with what was cut (pressed again, only the cards still empty are cut). Why cards were left out goes into
    `troubles` (a list); nothing cut at all for a refusal is raised in Anki Miner's words (r2 S2)."""
    from app.connect import anki_miner, lineup
    cards = {}
    for note_id, cue in can.items():
        cards.setdefault(cue, []).append(note_id)
    order = sorted(cards, key=lambda c: (c.audio, c.subtitle, c.start, c.text))
    if not order:
        return {}
    os.makedirs(run_dir, exist_ok=True)
    clips, why, kind = {}, troubles if troubles is not None else [], None
    for c, at in enumerate(range(0, len(order), CUT_LINES), 1):
        runs = {}                                # run_id -> (audio, subtitle, [its cues in order])
        for cue in order[at:at + CUT_LINES]:
            key = next((k for k, v in runs.items() if v[:2] == (cue.audio, cue.subtitle)), None)
            if key is None:
                key = f"c{c}e{len(runs) + 1}"
                runs[key] = (cue.audio, cue.subtitle, [])
            runs[key][2].append(cue)
        job = {"schema": 1, "run_dir": run_dir, "language": lang,
               "episodes": [{"run_id": run_id, "audio_file": os.path.abspath(audio),
                             "subtitle_file": os.path.abspath(sub),
                             "lines": [{"line_start": cue.start, "line_expansion": [0, 0]} for cue in cues]}
                            for run_id, (audio, sub, cues) in runs.items()]}
        if profile:
            job["profile"] = profile
        path = os.path.join(run_dir, f"media-{c}.json")
        lineup._write_json(path, job)
        try:
            verdict = anki_miner.api(miner, ["media", path], timeout=timeout or lineup.SPOT_TIMEOUT)
            if not verdict.get("runs"):
                anki_miner._result(verdict)     # a refusal of the whole call: raised
        except anki_miner.AnkiMinerError as e:
            if c == 1 or not clips:
                raise
            why.append(e.message)
            break                               # what was cut is kept; a press again cuts the rest
        for run_id, (audio, _sub, cues) in runs.items():
            name = os.path.basename(audio)              # r3 N4: each reason names its file
            run = next((r for r in verdict.get("runs") or () if isinstance(r, dict) and r.get("run_id") == run_id),
                       None)
            if run is None or not run.get("ok"):
                code = (run or {}).get("error")
                kind = kind or anki_miner.KINDS.get(code, "failed")       # r3 N3: Anki Miner's own kind
                why.append(f"{name}: {(run or {}).get('message') or code or 'no answer for that file'}")
                continue
            made = lineup._read_json(os.path.join(run_dir, run_id, os.path.basename(str(run.get("file") or "")))) or {}
            lines = [line for line in made.get("lines") or () if isinstance(line, dict)]
            if len(lines) != len(cues):
                why.append(f"{name}: {OTHER_COUNT}")    # merged or dropped: which answer is which line is unknown
                continue
            other = none = 0
            for cue, line in zip(cues, lines):
                if not _is_line(cue, line):
                    other += 1
                    continue
                clip = os.path.join(run_dir, run_id, line["audio"]) if isinstance(line.get("audio"), str) else None
                if clip and os.path.isfile(clip):
                    for note_id in cards[cue]:
                        clips[note_id] = clip
                else:
                    none += 1
            why.extend(f"{name}: {say.format(n=n)}" for say, n in ((NOT_THE_LINES, other), (NO_CLIP, none)) if n)
    if not clips and why:                       # r3 S2: nothing cut always says why
        raise anki_miner.AnkiMinerError(kind or "refused", f"Anki Miner couldn't cut the clips: {why[0]}")
    return clips


def _is_line(cue, line):
    """Is Anki Miner's answered `line` this cue's (its start and its length, within LINE_TOLERANCE, and its text)?"""
    from app.connect import anki_miner, lineup
    start = line.get("line_start")
    if isinstance(start, bool) or not isinstance(start, (int, float)) or \
            abs(float(start) - float(cue.start)) > anki_miner.LINE_TOLERANCE:
        return False
    end, begun = line.get("end"), line.get("start")
    if not all(isinstance(t, (int, float)) and not isinstance(t, bool) for t in (end, begun)) or \
            abs((float(end) - float(begun)) - (float(cue.end) - float(cue.start))) > 2 * anki_miner.LINE_TOLERANCE:
        return False                            # no times (r3 N6), or another line of the same start (its length)
    text = lineup.clean(line.get("text"))
    return bool(text) and (cue.text in text or text in cue.text)


def act(settings, language, book=None, confirm=False, undo_id=None):
    """*Add audio to these cards* for `book` (its EPUB), or `undo_id`'s Undo, as the command line and the window both
    ask it -> the command line's answer: the plan's counts without `confirm` (nothing written); with it what was
    written ({"id", "filled", "skipped", "not_cut"}); {"skipped": why} with Connect off or Anki switched off for the
    run. Raises CliError in plain words."""
    from app.cli.contract import CliError
    from app.connect import undo as undoing
    if not (settings or {}).get("connect_enabled"):
        return {"skipped": undoing.PREVIEW_OFF}
    from app.cli.verbs import require_set_up
    require_set_up(language)
    if os.environ.get("SURASURA_NO_ANKI_SYNC"):
        return {"skipped": undoing.NO_ANKI}
    from app import anki_connect
    from app.connect import sentence_audio as sa
    from app.connect.ledger import Ledger, path
    if not os.path.exists(path()):
        raise CliError("bad-data", NO_LEDGER)
    anki = sa.AnkiConnectNotes(anki_connect.address(settings))
    try:
        with Ledger() as ledger:
            if undo_id is not None:
                rec = sa.record(ledger, undo_id)
                if rec is None or rec.get("by") != BY:     # another path's record (the AI audio's) is its own Undo
                    raise CliError("bad-data", NO_UNDO, undo=undo_id)
                done = sa.undo(anki, ledger, undo_id)
                if done.get("emptied"):
                    undoing.owe_sync(settings)
                return dict(done, language=language, undo=undo_id)
            return _add(settings, language, book, confirm, anki, ledger)
    except CliError:
        raise
    except BaseException as e:
        rid = getattr(e, "sentence_audio_id", None)
        if rid is not None:                     # S5: a write stopped part-way: its cards' sync owed, its Undo named
            undoing.owe_sync(settings)
        err = _plain(e)
        if err is None:
            raise
        if rid is not None:
            err = CliError(err.code, PART_WRITTEN.format(why=err.message.rstrip("."), id=rid),
                           **dict(err.context, undo=rid, why=err.message.rstrip(".")))
        raise err from None


def _plain(e):
    """A failure in plain words (S4) -> CliError, or None (not one of these: raised as it is)."""
    from app import anki_connect, locks
    from app.cli import contract
    from app.cli.contract import CliError
    from app.connect import anki_miner, runner
    from app.connect import sentence_audio as sa
    from app.connect import undo as undoing
    from app.connect.ledger import TooNew
    if isinstance(e, TooNew):
        return CliError("needs-you", str(e), ask="Update Surasura")
    if isinstance(e, sa.Reviewing):
        return CliError("anki-busy", REVIEWING)
    if isinstance(e, locks.Busy):
        return contract.busy_error("anki-writer", e.holder, undoing.WRITER_BUSY)
    if isinstance(e, anki_connect.AnkiError):
        return CliError("anki-closed", f"Anki isn't open (or stopped answering): {e}")
    if isinstance(e, anki_miner.AnkiMinerError):
        from app.cli.verbs import _miner_error
        return _miner_error(e)
    if isinstance(e, runner.Wait):
        return CliError("busy", e.reason)
    if isinstance(e, runner.Needs):
        return CliError("needs-you", e.say, ask=e.say)
    first = (str(e).splitlines() or [type(e).__name__])[0][:160]
    if isinstance(e, sqlite3.Error):                    # the ledger or the library locked
        return CliError("failed", undoing.RECORDS + first)
    if isinstance(e, OSError):                          # a disk refusing a clip, the job file, the run folder
        return CliError("failed", FILE_TROUBLE + first)
    return None


def _add(settings, language, book, confirm, anki, ledger):
    from app.cli.contract import CliError
    from app.cli.verbs import _anki_miner_setup, _connect_folder
    from app.connect import anki_miner, runner
    from app.connect import sentence_audio as sa
    if not book or not os.path.isfile(book):
        raise CliError("bad-data", NO_BOOK.format(book=book), book=book)
    steps = runner.Steps(settings)
    run_dir = os.path.join(_connect_folder(), "add-audio", f"{time.time_ns()}")
    try:
        setup = _anki_miner_setup(settings, language, run_dir)
        if setup is None:
            return {"language": language, "skipped": NO_MINER}
        _version, profile, mapping = setup
        found = plan(anki, steps, language, book, mapping)
        counts = {"language": language, "book": found["title"], "can": len(found["can"]),
                  "unheard": len(found["unheard"]), "has_audio": len(found["has_audio"]), "gone": len(found["gone"])}
        if not found["lined"]:
            raise CliError("needs-you", NOT_LINED.format(title=found["title"]), book=book)
        if not found["field"]:
            raise CliError("needs-you", NO_AUDIO_FIELD)
        if not confirm or not found["can"]:
            seen = sorted(set(found["has_audio"]) | set(found["unheard"]) | set(found["gone"]))
            return dict(counts, confirm=False, **({"looked": seen} if confirm else {}))
        troubles = []
        clips = cut(anki_miner.find(settings), language, profile, found["can"], run_dir, troubles=troubles)
        done = sa.fill(anki, ledger, clips, field=found["field"], tag=TAG, by=BY)
        if done["filled"]:
            from app.connect import undo as undoing
            undoing.owe_sync(settings)
        missed = set(found["can"]) - set(clips)            # the press's looked: all but these (the row asks again)
        looked = sorted((set(found["can"]) | set(found["has_audio"]) | set(found["unheard"]) | set(found["gone"]))
                        - missed)
        return dict(counts, confirm=True, id=done["id"], filled=len(done["filled"]), looked=looked,
                    skipped={str(k): v for k, v in done["skipped"].items()},
                    not_cut=len(set(found["can"]) - set(clips)),
                    **({"not_cut_why": troubles[0]} if troubles and set(found["can"]) - set(clips) else {}))
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)       # the clips are Anki's now (or were never written)
