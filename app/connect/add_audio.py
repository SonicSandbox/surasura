"""*Add audio to these cards* (Kura-AB3, 2026-11-11; spec: TheForge `tracks/pipeline/work/AB3/add-audio-spec.md`;
PROVISIONAL): the narrator's voice put on the cards Connect made from a book before its audiobook was lined up.

- **Which cards** (`plan`, read only): the notes Connect made from the book's parts (the store's made words, the parts
  by the EPUB's `<epub>#<n>` origins), still in Anki, whose sentence-audio field — Anki Miner's role `audio` in the
  profile's mapping — is empty; each one's sentence (its sentence field, markup out) and word placed in the book's
  line-up (`runner.Steps.lined_up`: its own subtitle checked or trusted, or a finished sync of grade A/B) by
  `lineup.place` — the one cue holding that sentence and that word, never a neighbour's. -> *N can get the narrator's
  voice · M weren't heard (a skipped passage, a sentence the line-up didn't find) · K have audio already · J gone*.
- **The clips** (`cut`): Anki Miner's `media`, one call, one episode per audio file, each cue cut once (two cards of
  one cue share its clip); a line it cut no clip for is that card skipped — never another line's clip.
- **The write** (`run`): `sentence_audio.fill` — the one sentence-audio writer (only an empty field, read again under
  Anki's write lock; tagged `TAG`; one Undo record) — then the clips' run folder deleted (Anki holds them now).
- **Who asks** (`act`, the command line's `add-audio` and the window's one sequence): Connect on, Surasura set up, the
  ledger there (no ledger: Connect never made a card); the plan without `confirm`; `undo` by the record's id; Anki's
  sync owed after a write (the session's rule).

Light: the standard library; Anki through `sentence_audio.AnkiConnectNotes`, Anki Miner through `anki_miner`.
"""
import json
import os
import re
import shutil
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
_MARKUP = re.compile(r"<[^>]*>")


def _text(value):
    return _MARKUP.sub("", str(value or "")).replace("&nbsp;", " ").strip()


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
        sentence = _text((fields.get(mapping.sentence) or {}).get("value")) if mapping.sentence else ""
        word = _text((fields.get(mapping.word) or {}).get("value")) or notes[note_id]
        cue = lineup.place(sentence, word, found) if sentence and found else None
        if cue is None:
            out["unheard"].append(note_id)
        else:
            out["can"][note_id] = cue
    return out


def cut(miner, lang, profile, can, run_dir, timeout=None):
    """The clips of `can` ({note id: Cue}) -> {note id: clip path}: Anki Miner's `media`, one call, an episode per audio
    file, each cue's start once; a line it cut no clip for (or a call that refused that file) leaves its cards out."""
    from app.connect import anki_miner, lineup
    groups = {}
    for note_id, cue in can.items():
        groups.setdefault((cue.audio, cue.subtitle), {}).setdefault(cue.start, []).append(note_id)
    if not groups:
        return {}
    os.makedirs(run_dir, exist_ok=True)
    runs = []                                   # [(run_id, its starts in order, {start: [note ids]})]
    for k, ((audio, subtitle), starts) in enumerate(sorted(groups.items()), 1):
        runs.append((f"a{k}", audio, subtitle, sorted(starts), starts))
    job = {"schema": 1, "run_dir": run_dir, "language": lang,
           "episodes": [{"run_id": run_id, "audio_file": os.path.abspath(audio), "subtitle_file": os.path.abspath(sub),
                         "lines": [{"line_start": start, "line_expansion": [0, 0]} for start in order]}
                        for run_id, audio, sub, order, _s in runs]}
    if profile:
        job["profile"] = profile
    path = os.path.join(run_dir, "media.json")
    lineup._write_json(path, job)
    verdict = anki_miner.api(miner, ["media", path], timeout=timeout or lineup.SPOT_TIMEOUT)
    if not verdict.get("runs"):
        anki_miner._result(verdict)             # a refusal of the whole call: raised
    clips = {}
    for run_id, _audio, _sub, order, starts in runs:
        run = next((r for r in verdict.get("runs") or () if isinstance(r, dict) and r.get("run_id") == run_id), None)
        if run is None or not run.get("ok"):
            continue
        made = lineup._read_json(os.path.join(run_dir, run_id, os.path.basename(str(run.get("file") or "")))) or {}
        lines = [line for line in made.get("lines") or () if isinstance(line, dict)]
        if len(lines) != len(order):
            continue                            # merged or dropped: no line is matched by its place (never a guess)
        for start, line in zip(order, lines):
            clip = os.path.join(run_dir, run_id, line["audio"]) if isinstance(line.get("audio"), str) else None
            if clip and os.path.isfile(clip):
                for note_id in starts[start]:
                    clips[note_id] = clip
    return clips


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
    from app import anki_connect, locks
    from app.cli import contract
    from app.connect import sentence_audio as sa
    from app.connect.ledger import Ledger, TooNew, path
    if not os.path.exists(path()):
        raise CliError("bad-data", NO_LEDGER)
    anki = sa.AnkiConnectNotes(anki_connect.address(settings))
    try:
        with Ledger() as ledger:
            if undo_id is not None:
                if sa.record(ledger, undo_id) is None:
                    raise CliError("bad-data", NO_UNDO, undo=undo_id)
                done = sa.undo(anki, ledger, undo_id)
                if done.get("emptied"):
                    undoing.owe_sync(settings)
                return dict(done, language=language, undo=undo_id)
            return _add(settings, language, book, confirm, anki, ledger)
    except TooNew as e:
        raise CliError("needs-you", str(e), ask="Update Surasura") from None
    except sa.Reviewing:
        raise CliError("anki-busy", REVIEWING) from None
    except locks.Busy as e:
        raise contract.busy_error("anki-writer", e.holder, undoing.WRITER_BUSY) from None
    except anki_connect.AnkiError as e:
        raise CliError("anki-closed", f"Anki isn't open (or stopped answering): {e}") from None


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
            raise CliError("skipped", "Anki Miner isn't installed: it cuts the clips.")
        _version, profile, mapping = setup
        found = plan(anki, steps, language, book, mapping)
        counts = {"language": language, "book": found["title"], "can": len(found["can"]),
                  "unheard": len(found["unheard"]), "has_audio": len(found["has_audio"]), "gone": len(found["gone"])}
        if not found["lined"]:
            raise CliError("needs-you", NOT_LINED.format(title=found["title"]), book=book)
        if not found["field"]:
            raise CliError("needs-you", NO_AUDIO_FIELD)
        if not confirm or not found["can"]:
            return dict(counts, confirm=False)
        clips = cut(anki_miner.find(settings), language, profile, found["can"], run_dir)
        done = sa.fill(anki, ledger, clips, field=found["field"], tag=TAG, by=BY)
        if done["filled"]:
            from app.connect import undo as undoing
            undoing.owe_sync(settings)
        return dict(counts, confirm=True, id=done["id"], filled=len(done["filled"]),
                    skipped={str(k): v for k, v in done["skipped"].items()},
                    not_cut=len(set(found["can"]) - set(clips)))
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)       # the clips are Anki's now (or were never written)
