"""⇄ Swap: a card's sentence changed to another line of the learner's own library, the card kept (Michi-SW, 3.1
prototype; the 3.0 plan's `tracks/pipeline/work/swap/SWAP-PROTO.md`; VISION § 11 *The journey and Swap*).

The journey page asks through the door (`app/door.py`): `candidates` (the card, and the word's sentences from the plan
file, easiest first), `preview` (one line's clip and picture, cut on demand by Anki Miner's `media`: no card, no Anki),
`swap` (Anki Miner's `render` builds the line's note with nothing sent to Anki — API.md: "a caller can store it under
that name and update a note with the fields as given" — then its sentence-side fields go into the card with
`updateNoteFields`) and `undo` (the snapshot put back).

- **The card keeps** its note (so its scheduling, reviews, deck, tags), its word side, `Hint` (its translation, K18)
  and `MiscInfo`. **Replaced:** Anki Miner's sentence-side roles (`ROLES`); the layout's `SentenceFurigana` is blanked
  when Anki Miner doesn't map it (AJT fills it on add, never on an update: the card would still show the old line).
- **Snapshot first:** the note's old values (and the new ones) are written to `undo-<lang>.json` before Anki's first
  write; Undo puts them back only while the note still holds what Swap wrote. The old line's media stay in Anki (Undo
  plays them again; *Check Media* lists them once nothing does).
- **Anki** only through the adapter, holding `anki-writer` from the note's read to the last write, never while you
  review (K88: asked inside the hold, before the first store and again before the fields); Anki Miner's `render` and
  `media` take no lock and write nothing to Anki, so they run before the hold.
- Media are named by the line (`media_names.line_name`, `sl-…`): a line swapped in twice uploads once.
"""
import base64
import hashlib
import html
import json
import os
import re
import secrets
import threading
import time

from app.connect import media_names

# Anki Miner's sentence-side roles (`anki_note_builder`): the line's own. Everything else on the note stays.
ROLES = ("sentence", "sentence_furigana", "sentence_reading", "audio", "picture", "source")
LAYOUT_FURIGANA = "SentenceFurigana"            # Anki_Card_Layout_Spec §3 row 3: shown before `Sentence`
# Never written, whatever a role maps to: the card's translation (K18) and its ヒント band — Anki Miner's Lapis preset
# puts `source` in MiscInfo (`miner_settings.NAMES`), where the learner's ヒント lives (layout §3 row 6), so a swap
# keeps the old line's source name there (SWAP-PROTO.md open question 6)
KEEP = frozenset(("Hint", "MiscInfo"))
TAG = "surasura::swapped"
PREVIEW_KEEP = 40                               # previews kept (each a clip and a picture); the oldest go
ASKS = frozenset(("Z-10",))                     # `render` and `media` (Anki Miner 3.11)
WRITER_WAIT = 10.0
SETUP_FOR_S = 15 * 60
MEDIA_TIMEOUT = 120.0
RENDER_TIMEOUT = 300.0
_TAGS = re.compile(r"<[^>]+>")

NO_MINER = "Swap needs Anki Miner 3.11 or later (Settings → Anki & mining)."
ANKI_CLOSED = "Open Anki to swap this card's sentence."
NOT_TIMED = "Its timing to the video isn't checked yet, so it can't be cut."
NO_VIDEO = "Its video isn't on this computer."
GONE = "That line isn't in its subtitle any more."
CHANGED = "This card changed since the swap: nothing was undone."
SAME = "That line is on the card already."
NOT_APPLIED = ("Anki didn't take the change (is the card open in Anki's editor?): close it and press again.")
NOT_THE_CARD = "That card isn't this word's card in your mining deck: nothing was changed."


class SwapError(Exception):
    """A refusal in plain words; `kind` for the page (anki-closed, no-miner, reviewing, busy, …)."""

    def __init__(self, message, kind="refused"):
        super().__init__(message)
        self.message, self.kind = message, kind


def folder():
    from app.connect import ledger
    return os.path.join(ledger.folder(), "swap")


def preview_folder():
    return os.path.join(folder(), "preview")


def undo_path(lang):
    return os.path.join(folder(), f"undo-{lang}.json")


def plain(value):
    """A field's text as the page shows it: no tags, entities read."""
    return html.unescape(_TAGS.sub("", value or "")).strip()


def line_id(path, start, text):
    return hashlib.sha256(f"{path}|{start}|{text}".encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# The session: what the door's routes share while the window runs
# --------------------------------------------------------------------------- #
class Session:
    """One window's Swap state: the lines offered (by id: the page names only ids, never a path), the plan engine
    (read again when the plan file changes), Anki Miner's look-ups (read once, again after SETUP_FOR_S), each episode's
    video and fit verdict. `steps`, `miner`, `setup`, `url` and `api` (Anki Miner's call) are what a test hands in."""

    def __init__(self, settings, steps=None, miner=None, setup=None, url=None, api=None):
        from app import anki_connect
        from app.connect import anki_miner
        self.settings = settings
        self.url = url or anki_connect.address(settings)
        self._steps, self._miner, self._setup = steps, miner, setup
        self._api = api or anki_miner.api
        self.lines = {}             # id -> the line (dict)
        self._plan = (None, None)   # (the plan file's (mtime, size), its Engine)
        self._miner_set = None      # (at, (info, profile, mapping))
        self._episodes = {}         # (lang, item id) -> (video, offset) or SwapError
        self._lock = threading.Lock()

    # --- the parts ------------------------------------------------------------------------------------------ #
    def steps(self):
        if self._steps is None:
            from app.connect import runner
            self._steps = runner.Steps(self.settings)
        return self._steps

    def miner(self):
        """Anki Miner's path — one with `render` and `media` — or SwapError no-miner."""
        from app.connect import anki_miner
        path = self._miner if self._miner is not None else anki_miner.find(self.settings)
        if not path:
            raise SwapError(NO_MINER, "no-miner")
        return path

    def setup(self, lang):
        """(info, profile, mapping) of the profile Connect mines with (`verbs._anki_miner_setup`), read once."""
        if self._setup is not None:
            return self._setup(lang)
        kept = self._miner_set
        if kept is not None and time.monotonic() - kept[0] < SETUP_FOR_S and kept[2] == lang:
            return kept[1]
        from app.cli import verbs
        from app.cli.contract import CliError
        from app.connect import anki_miner
        try:
            got = verbs._anki_miner_setup(self.settings, lang, os.path.join(folder(), "setup"))
        except CliError as e:
            raise SwapError(e.message if hasattr(e, "message") else str(e), "setup") from None
        if got is None:
            raise SwapError(NO_MINER, "no-miner")
        if not anki_miner.can(ASKS, got[0]):
            raise SwapError(NO_MINER, "no-miner")
        self._miner_set = (time.monotonic(), got, lang)
        return got

    def engine(self):
        from app import plan_engine, replan_preview
        path = replan_preview.plan_path()
        try:
            st = os.stat(path)
        except OSError:
            raise SwapError("Generate your list first: Swap offers the sentences it found.", "no-plan") from None
        key = (st.st_mtime_ns, st.st_size)
        if self._plan[0] != key:
            try:
                plan = plan_engine.load(path)
                self._plan = (key, plan_engine.Engine(plan, numbers_only=False))
            except plan_engine.PlanError as e:
                raise SwapError(f"Generate your list again: its plan can't be read ({e}).", "no-plan") from None
        return self._plan[1]

    # --- candidates ----------------------------------------------------------------------------------------- #
    def candidates(self, lang, word, reading):
        """The card (its note and its sentence now) and the word's sentences, easiest first. Anki closed: the
        sentences all the same, `note` None and `anki` the reason."""
        engine = self.engine()
        keys = engine.plan.keys
        k = next((i for i, key in enumerate(keys) if key[0] == word and key[1] == (reading or key[1])), None)
        found = engine.candidates(k) if k is not None else None
        if found is None:
            raise SwapError(f"{word} isn't on your list now: Generate first.", "not-listed")
        card, why = None, None
        try:
            card = self.card(lang, word)
        except SwapError as e:
            why = e.message
        from app.path_utils import get_data_path
        from app.static_html_generator import AnchorFinder
        finder = AnchorFinder(language=lang)
        data = get_data_path(lang)
        shows = self.shows(lang, [where for _s, where, _u, _a in found])
        rows = []
        for shown, where, unknown, audio in found:
            path = where if os.path.isabs(where) else os.path.join(data, *str(where).split("/"))
            start = end = None
            if audio == 1:                          # a subtitle's line: its times as Connect's line reader reads them
                start, end = finder.line(path, shown)
            lid = line_id(path, start, shown)
            row = {"id": lid, "text": shown, "unknown": unknown, "show": shows.get(where, ""),
                   "episode": os.path.splitext(os.path.basename(str(where)))[0], "timed": start is not None,
                   "start": start, "end": end, "audio": audio,
                   "now": bool(card) and plain(card["now"]) == shown}
            with self._lock:
                self.lines[lid] = dict(row, path=path, rel=str(where), lang=lang)
            rows.append(row)
        return {"note": card and card["note"], "now": card and plain(card["now"]), "hint": bool(card and card["hint"]),
                "anki": why, "candidates": rows}

    def shows(self, lang, rels):
        """{rel path: the show's title} — the store's work title, else the file's folder (never a tier's own folder:
        the learner sees NOW / Soon / 6+ Months, never HighPriority); "" when there's neither."""
        from app.connect import library
        from app.static_html_generator import _TIER_BUCKETS
        out = {}
        try:
            with self.steps()._open(lang) as store:
                for rel, item_id in zip(rels, store.item_ids(list(rels))):
                    out[rel] = (library.show_title(store, item_id) if item_id is not None else None) or ""
        except Exception:                           # (a busy store: the folders below)
            pass
        for rel in rels:
            name = os.path.basename(str(rel))
            if out.get(rel) in (name, os.path.splitext(name)[0]):
                out[rel] = ""                       # (a loose file's work is named by the file: the episode says it)
            if not out.get(rel):
                parts = str(rel).replace("\\", "/").split("/")
                out[rel] = parts[-2] if len(parts) > 1 and parts[-2] not in _TIER_BUCKETS else ""
        return out

    def card(self, lang, word):
        """{note, now, hint} for the word's card in Connect's deck, or SwapError (no card, several, Anki closed)."""
        from app import anki_connect
        _info, _profile, mapping = self.setup(lang)
        query = (f'deck:"{anki_connect.escape_query(mapping.deck)}" '
                 f'"{mapping.word}:{anki_connect.escape_query(word)}"')
        try:
            ids = anki_connect.find_notes(self.url, query)
            notes = anki_connect.notes_info(self.url, ids) if ids else []
        except anki_connect.AnkiError:
            raise SwapError(ANKI_CLOSED, "anki-closed") from None
        if not notes:
            raise SwapError(f"No card for {word} yet.", "no-card")
        if len(notes) > 1:
            raise SwapError(f"Several cards hold {word}: swap one from Anki's browser for now.", "several")
        fields = notes[0].get("fields") or {}
        value = lambda name: ((fields.get(name) or {}).get("value") or "") if name else ""     # noqa: E731
        return {"note": notes[0]["noteId"], "now": value(mapping.sentence),
                "hint": bool(value(mapping.fields.get("sentence_translation")))}

    # --- one line's episode ---------------------------------------------------------------------------------- #
    def line(self, lid):
        with self._lock:
            found = self.lines.get(lid)
        if found is None:
            raise SwapError("Open ⇄ again: that list is old.", "stale")
        if not found["timed"]:
            raise SwapError("A text's sentence has no clip to cut yet.", "text")
        return found

    def episode(self, line):
        """(the episode's media key, video, offset, expansion) for a line, or SwapError (no video, not timed, the
        line gone). The key is Connect's own (`runner.Steps._rename`): hato's `content_key`, else the item's
        `rel_key` — so a line swapped in shares the file a card mined from that line already has."""
        lang = line["lang"]
        with self.steps()._open(lang) as store:
            item_id = (store.item_ids([line["rel"]]) or [None])[0]
            item = store.item(item_id) if item_id is not None else None
        if item_id is None:
            raise SwapError(GONE, "gone")
        held = self._episodes.get((lang, item_id))
        if held is None:
            held = self._episode(lang, item_id, line["path"])
            self._episodes[(lang, item_id)] = held
        if isinstance(held, SwapError):
            raise held
        video, offset, pairing = held
        key = (pairing or {}).get("content_key") or (item or {}).get("rel_key") or f"item-{item_id}"
        return key, video, offset, expansion(line["path"], lang, line["start"], line["end"])

    def _episode(self, lang, item_id, subtitle):
        from app.connect import fit_check
        steps, job = self.steps(), {"item_id": item_id}
        try:
            video = steps.video(lang, job)
            if video is None:
                return SwapError(NO_VIDEO, "no-video")
            pairing = steps.pairing(lang, job)
            verdict, _who, _why, offset = steps.fit(lang, job, pairing, video, subtitle)
        except Exception:                           # the loop's Wait / Needs (a busy store): asked again next press
            raise SwapError("Surasura is busy with its library: press again in a moment.", "busy") from None
        if verdict != fit_check.TIMED:
            return SwapError(NOT_TIMED, "not-timed")
        return video, offset, pairing

    # --- ▶ ----------------------------------------------------------------------------------------------------- #
    def preview(self, lid):
        """The line's clip and picture (names the door's `clip/` serves), cut once by `media`, kept PREVIEW_KEEP."""
        line = self.line(lid)
        out = preview_folder()
        kept = {ext: f"{lid}{ext}" for ext in (".mp3", ".jpg", ".webp", ".png")}
        have = [n for n in kept.values() if os.path.isfile(os.path.join(out, n))]
        if any(n.endswith(".mp3") for n in have):
            return {"clip": f"{lid}.mp3", "picture": next((n for n in have if not n.endswith(".mp3")), None)}
        miner = self.miner()
        _info, profile, _mapping = self.setup(line["lang"])
        _item, video, offset, (before, after) = self.episode(line)
        run_dir = os.path.join(folder(), "media")
        os.makedirs(run_dir, exist_ok=True)
        run_id = f"p{lid}-{secrets.token_hex(4)}"
        data = {"schema": 1, "run_dir": run_dir, "language": line["lang"],
                "episodes": [{"run_id": run_id, "video_file": os.path.abspath(video),
                              "subtitle_file": os.path.abspath(line["path"]), "subtitle_offset": float(offset or 0.0),
                              "lines": [{"line_start": line["start"], "line_expansion": [before, after]}]}]}
        if profile:
            data["profile"] = profile
        path = os.path.join(run_dir, f"{run_id}.json")
        _write_json(path, data)
        try:
            return self._cut(miner, path, run_dir, run_id, lid, out)
        finally:                                    # the run's file and folder go, whatever happened
            _remove_tree(os.path.join(run_dir, run_id))
            try:
                os.remove(path)
            except OSError:
                pass

    def _cut(self, miner, path, run_dir, run_id, lid, out):
        from app.connect import anki_miner
        try:
            verdict = self._api(miner, ["media", path], timeout=MEDIA_TIMEOUT, look_up=True)
        except anki_miner.AnkiMinerError as e:
            raise SwapError(f"Anki Miner couldn't cut that line: {e.message}", "miner") from None
        run = next((r for r in verdict.get("runs") or () if isinstance(r, dict) and r.get("run_id") == run_id), None)
        if run is None or not run.get("ok") or not run.get("file"):
            raise SwapError(f"Anki Miner couldn't cut that line: {(run or verdict).get('message') or 'no answer'}",
                            "miner")
        try:
            with open(os.path.join(run_dir, run_id, os.path.basename(run["file"])), encoding="utf-8") as f:
                cut = (json.load(f).get("lines") or [{}])[0]
        except (OSError, ValueError, IndexError, AttributeError):
            raise SwapError("Anki Miner's clip couldn't be read.", "miner") from None
        os.makedirs(out, exist_ok=True)
        answer = {"clip": None, "picture": None}
        for key, role in (("audio", "clip"), ("picture", "picture")):
            got = cut.get(key)
            if not isinstance(got, str):
                continue
            ext = os.path.splitext(got)[1].lower()
            if role == "clip" and ext != ".mp3" or role == "picture" and ext not in (".jpg", ".webp", ".png"):
                continue                            # (a kind the door doesn't serve under this id)
            got = got.replace("\\", "/")
            if got.startswith("/") or ".." in got.split("/") or ":" in got:
                continue                            # (only a file inside the run's folder is taken)
            os.replace(os.path.join(run_dir, run_id, got), os.path.join(out, f"{lid}{ext}"))
            answer[role] = f"{lid}{ext}"
        _trim(out, PREVIEW_KEEP * 2)
        if answer["clip"] is None:
            raise SwapError("Anki Miner cut no audio for that line.", "miner")
        return answer

    # --- ⇄ ----------------------------------------------------------------------------------------------------- #
    def swap(self, note_id, lid):
        """The card `note_id`'s sentence → line `lid` -> {"undo": the snapshot's id, "now": the new sentence}."""
        line = self.line(lid)
        lang = line["lang"]
        from app import anki_connect
        from app.connect import anki_miner, runfile
        miner = self.miner()
        info, profile, mapping = self.setup(lang)
        key, video, offset, (before, after) = self.episode(line)
        try:
            note = (anki_connect.notes_info(self.url, [int(note_id)]) or [None])[0]
        except anki_connect.AnkiError:
            raise SwapError(ANKI_CLOSED, "anki-closed") from None
        if not note:
            raise SwapError("That card isn't in Anki any more.", "no-card")
        word = plain(((note.get("fields") or {}).get(mapping.word) or {}).get("value"))
        run_dir = os.path.join(folder(), "render")
        run_id = f"s{line['id'][:12]}-{secrets.token_hex(4)}"
        try:
            return self._swap(note_id, line, lang, info, profile, mapping, key, video, offset, before, after,
                              word, note, run_dir, run_id, miner, runfile, anki_miner)
        finally:                                    # the run's file and folder (its clips) go, whatever happened
            _remove_tree(os.path.join(run_dir, run_id))
            try:
                os.remove(os.path.join(run_dir, f"{run_id}.json"))
            except OSError:
                pass

    def _swap(self, note_id, line, lang, info, profile, mapping, key, video, offset, before, after, word, note,
              run_dir, run_id, miner, runfile, anki_miner):
        from app import anki_connect, locks
        rendered, files_dir = self._render(miner, lang, profile, info, mapping, word, video, line, offset,
                                           before, after, runfile, anki_miner, run_dir, run_id)
        new = self._fields(rendered, note, mapping, key, line)
        names = {new_name: os.path.join(files_dir, old) for old, new_name in new.pop("_media").items()}
        try:
            held = anki_connect.writer("⇄ Swap", wait=WRITER_WAIT)
        except locks.Busy as e:
            raise SwapError(anki_connect.busy_message(e), "busy") from None
        with held:
            if anki_connect.reviewing(self.url):
                raise SwapError(anki_connect.REVIEWING, "reviewing")
            try:
                now = anki_connect.notes_info(self.url, [int(note_id)])[0]
            except (anki_connect.AnkiError, IndexError):
                raise SwapError(ANKI_CLOSED, "anki-closed") from None
            self._check_card(now, mapping, word)
            fields = now.get("fields") or {}
            old = {f: (fields.get(f) or {}).get("value") or "" for f in new}
            if old == new:
                raise SwapError(SAME, "same")
            record = {"id": f"{int(time.time() * 1000)}-{note_id}", "note": int(note_id), "at": time.time(),
                      "word": word, "line": {k: line[k] for k in ("rel", "start", "end", "text")}, "old": old,
                      "new": new, "tagged": TAG not in (now.get("tags") or ()), "undone": False}
            _record(lang, record)                   # before Anki's first write: Undo always has the old values
            applied = False
            try:
                self._store(names)
                if anki_connect.reviewing(self.url):    # asked again before the fields (the stored files wait)
                    raise SwapError(anki_connect.REVIEWING, "reviewing")
                anki_connect.invoke("updateNoteFields", self.url, note={"id": int(note_id), "fields": new})
                written = anki_connect.notes_info(self.url, [int(note_id)])[0].get("fields") or {}
                if any(((written.get(f) or {}).get("value") or "") != v for f, v in new.items()):
                    raise SwapError(NOT_APPLIED, "not-applied")    # (a note open in Anki's editor keeps its own)
                applied = True
                if record["tagged"]:
                    anki_connect.invoke("addTags", self.url, notes=[int(note_id)], tags=TAG)
            except BaseException:
                if not applied:                     # the card never took it: no Undo offered, none blocked by it
                    _mark(lang, record["id"], failed=time.time())
                raise                               # (taken, only its tag failed: the record stays undoable)
        return {"undo": record["id"], "now": plain(new.get(mapping.sentence) or "") or line["text"]}

    def _check_card(self, note, mapping, word):
        """The note is this word's card in the mining deck, of the profile's note type (review 5: an id from an old
        page, or from anything else that read the door's file, never rewrites another note)."""
        from app import anki_connect
        fields = note.get("fields") or {}
        if note.get("modelName") != mapping.note_type or \
                plain((fields.get(mapping.word) or {}).get("value")) != word:
            raise SwapError(NOT_THE_CARD, "not-the-card")
        try:
            cards = anki_connect.cards_info(self.url, list(note.get("cards") or ())[:1])
        except anki_connect.AnkiError:
            raise SwapError(ANKI_CLOSED, "anki-closed") from None
        if not cards or cards[0].get("deckName") != mapping.deck:
            raise SwapError(NOT_THE_CARD, "not-the-card")

    def _render(self, miner, lang, profile, info, mapping, word, video, line, offset, before, after, runfile,
                anki_miner, run_dir, run_id):
        """Anki Miner's `render` of `word` on the line -> (its row's fields, the folder its files are in)."""
        named = info.get("features")
        os.makedirs(run_dir, exist_ok=True)
        words = runfile.word_requests([{"sent": [word], "line_start": line["start"],
                                        "line_expansion": [before, after]}], named)
        episode = runfile.episode(run_id, video, line["path"], words, tags="", subtitle_offset=float(offset or 0.0))
        data = runfile.build(run_dir, lang, [episode], profile=profile,
                             run_config=runfile.config(mapping, info.get("app"), named))
        path = runfile.write(os.path.join(run_dir, f"{run_id}.json"), data)
        try:
            verdict = self._api(miner, ["render", path], timeout=RENDER_TIMEOUT)
        except anki_miner.AnkiMinerError as e:
            kind = "anki-closed" if e.kind == "anki-closed" else "miner"
            raise SwapError(ANKI_CLOSED if kind == "anki-closed" else f"Anki Miner couldn't make that line: "
                            f"{e.message}", kind) from None
        run = next((r for r in verdict.get("runs") or () if isinstance(r, dict) and r.get("run_id") == run_id), None)
        if run is None or not run.get("file"):
            if verdict.get("error") == "ANKI_UNREACHABLE" or (run or {}).get("error") == "ANKI_UNREACHABLE":
                raise SwapError(ANKI_CLOSED, "anki-closed")
            raise SwapError(f"Anki Miner couldn't make that line: {(run or verdict).get('message') or 'no answer'}",
                            "miner")
        result = anki_miner.read_result(run_dir, run_id, run["file"]) or {}
        row = next((w for w in result.get("words") or () if isinstance(w, dict) and w.get("status") == "rendered"),
                   None)
        if row is None or not isinstance(row.get("fields"), dict):
            raise SwapError(f"Anki Miner didn't find {word} in that line.", "not-found")
        files_dir = os.path.join(run_dir, run_id, os.path.splitext(os.path.basename(run["file"]))[0])
        return row["fields"], files_dir

    def _fields(self, rendered, note, mapping, key, line):
        """The note's new sentence-side fields (`ROLES` the profile maps, the note has and `render` filled), the
        media in them named by the line; `_media` {render's name: the line's name}."""
        have = note.get("fields") or {}
        new, media = {}, {}
        keep = KEEP | {mapping.fields.get("sentence_translation")}
        for role in ROLES:
            name = mapping.fields.get(role)
            if not name or name not in have or name not in rendered or name in keep:
                continue
            value = rendered[name] or ""
            for pattern in (media_names._SOUND, media_names._IMG):
                old = media_names._named(value, pattern)
                if old and not old.startswith(media_names.PREFIX):
                    renamed = media.get(old) or media_names.line_name(
                        key, line["start"], line["end"], media_names.fingerprint(line["text"]),
                        os.path.splitext(old)[1] or ".bin")
                    media[old] = renamed
                    value = value.replace(old, renamed)
            new[name] = value
        if (not mapping.fields.get("sentence_furigana") and LAYOUT_FURIGANA in have
                and (have[LAYOUT_FURIGANA] or {}).get("value")):
            new[LAYOUT_FURIGANA] = ""               # AJT's colours of the OLD line: the card shows the new Sentence
        if not new.get(mapping.sentence or ""):
            raise SwapError("Anki Miner gave no sentence for that line.", "miner")
        new["_media"] = media
        return new

    def _store(self, names):
        """The line's files into Anki under their `sl-` names; a name Anki has already is used as it is."""
        from app import anki_connect
        for name, path in names.items():
            if anki_connect.invoke("getMediaFilesNames", self.url, pattern=name):
                continue
            with open(path, "rb") as f:
                data = base64.b64encode(f.read()).decode("ascii")
            anki_connect.invoke("storeMediaFile", self.url, filename=name, data=data, deleteExisting=False)

    # --- Undo -------------------------------------------------------------------------------------------------- #
    def undo(self, lang, undo_id):
        from app import anki_connect, locks
        record = next((r for r in _records(lang) if r.get("id") == undo_id), None)
        if record is None or record.get("undone") or record.get("failed"):
            raise SwapError("Nothing to undo.", "gone")
        try:
            held = anki_connect.writer("⇄ Swap's undo", wait=WRITER_WAIT)
        except locks.Busy as e:
            raise SwapError(anki_connect.busy_message(e), "busy") from None
        with held:
            records = _records(lang)                # read again holding the lock: a swap meanwhile is kept (review 1)
            record = next((r for r in records if r.get("id") == undo_id), None)
            if record is None or record.get("undone") or record.get("failed"):
                raise SwapError("Nothing to undo.", "gone")
            if anki_connect.reviewing(self.url):
                raise SwapError(anki_connect.REVIEWING, "reviewing")
            try:
                note = (anki_connect.notes_info(self.url, [record["note"]]) or [None])[0]
            except anki_connect.AnkiError:
                raise SwapError(ANKI_CLOSED, "anki-closed") from None
            if not note:
                raise SwapError("That card isn't in Anki any more.", "no-card")
            fields = note.get("fields") or {}
            if any(((fields.get(f) or {}).get("value") or "") != v for f, v in record["new"].items()):
                raise SwapError(CHANGED, "changed")
            anki_connect.invoke("updateNoteFields", self.url, note={"id": record["note"], "fields": record["old"]})
            if record.get("tagged") and not any(r is not record and r.get("note") == record["note"]
                                                and not r.get("undone") and not r.get("failed") for r in records):
                anki_connect.invoke("removeTags", self.url, notes=[record["note"]], tags=TAG)
            record["undone"] = time.time()
            _write_json(undo_path(lang), records)
        return {"now": plain(next(iter(record["old"].values()), ""))}


def expansion(path, lang, start, end):
    """(before, after): the lines a card cut from the line starting at `start` (s) holds to reach `end` (s) — the
    sentence's own span (sim.py's rule, research/03 § 2d step 10), at most `pick.SIDE` after."""
    from app import cues
    from app.connect import pick
    try:
        read = cues.read(path, lang)
    except OSError:
        raise SwapError(GONE, "gone") from None
    start_ms, end_ms = int(round(start * 1000)), int(round((end or start) * 1000))
    at = next((i for i, c in enumerate(read) if c.start == start_ms), None)
    if at is None:
        raise SwapError(GONE, "gone")
    after = 0
    while after < pick.SIDE and at + after + 1 < len(read) and read[at + after].end < end_ms:
        after += 1
    return 0, after


def _records(lang):
    try:
        with open(undo_path(lang), encoding="utf-8") as f:
            found = json.load(f)
        return found if isinstance(found, list) else []
    except (OSError, ValueError):
        return []


def _record(lang, record):
    records = _records(lang)
    records.append(record)
    _write_json(undo_path(lang), records[-200:])


def _mark(lang, record_id, **values):
    records = _records(lang)
    for r in records:
        if r.get("id") == record_id:
            r.update(values)
    _write_json(undo_path(lang), records)


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _remove_tree(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


def _trim(path, keep):
    try:
        names = sorted(os.listdir(path), key=lambda n: os.path.getmtime(os.path.join(path, n)))
    except OSError:
        return
    for name in names[:-keep] if len(names) > keep else ():
        try:
            os.remove(os.path.join(path, name))
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# The door's routes
# --------------------------------------------------------------------------- #
def _lang(body):
    lang = body.get("lang")
    if lang not in ("ja", "zh"):
        raise SwapError("Which language? The page didn't say.")
    return lang


def routes(session):
    """{route: fn(body)} for `door.start`: each SwapError answered as the door's RouteError."""
    from app import door

    def wrap(fn):
        def route(body):
            try:
                return fn(body)
            except SwapError as e:
                raise door.RouteError(e.message, e.kind) from None
        return route

    def candidates(body):
        word = body.get("word")
        if not isinstance(word, str) or not word.strip():
            raise SwapError("Which word?")
        return session.candidates(_lang(body), word, body.get("reading") or None)

    def note_id(body):
        note = body.get("note")
        if isinstance(note, bool) or not isinstance(note, int):
            raise SwapError("Which card?")
        return note

    return {"swap/candidates": wrap(candidates),
            "swap/preview": wrap(lambda body: session.preview(str(body.get("id") or ""))),
            "swap/do": wrap(lambda body: session.swap(note_id(body), str(body.get("id") or ""))),
            "swap/undo": wrap(lambda body: session.undo(_lang(body), str(body.get("undo") or "")))}


def start_door(settings):
    """The window's door with Swap's routes (`shell.main` after the first frame); never raises."""
    try:
        from app import door
        from app.path_utils import get_user_file
        os.makedirs(preview_folder(), exist_ok=True)
        return door.start(routes(Session(settings)), get_user_file("results"), clips=preview_folder())
    except Exception:
        return None
