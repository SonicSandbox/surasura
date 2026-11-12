"""The window's short writes to Connect's ledger that start work (P4.1), beside `status.mark_seen` and `status.dismiss`.

- `mine_anyway(language, need_id)` (row 4.1.9; G1.3-6, 06-edges E16): *Mine anyway* on a *Needs you* entry that says
  an episode isn't timed to its video — the entry fixed, the item's job queued again with `picked.forced`, so its next
  pick mines it untimed (`runner._fit`: tsubasa isn't asked, no shift; logged *mined anyway: not timed*). The choice
  holds for the pairing it was made on: a pairing changed since (hato re-timed it, a new subtitle) is picked again and
  checked again, as any. On hato's name-only pairings (`verdict: untimed`) the entry carries `feed.UNTIMED_WARNING`.
- `make_cards(language, gap_id)` (P4.1 WF; IK D-1 lean (a), P2.1-3): *Make their cards* on a *Needs you* gap — the
  gap's episodes queued as Connect's ordinary jobs (kind `mine`, by `user`), never an ask: a word Connect ever made,
  a deleted card's included, is never made again (`library.made_words_for`, N15 / G1.3-4); the gap marked noticed.

- `stop(language, job_id)` (laptop round 8 #47): *Stop* on the episode Connect is making cards for: the press
  recorded at once (`Ledger.ask_stop`) and Connect woken (`kick.wake`). Connect stops the job at its next safe
  point: before its next step, or Anki Miner's batch cancelled within a second, every card it made kept, whole and
  recorded (what reached Anki is found by the job's tag: never half-written, never made twice). The episode then waits
  (`runner.STOPPED_BY_YOU`) until you press *Mine now*; Connect goes on with the next one. Once its cards are being
  filled and ordered (seconds) the job finishes (`stoppable`).

- `speech_model(language, need_id, yes)` (Michi-AB Stage B, AB-Q2 PROVISIONAL): the speech model's one question —
  *Download it* (Anki Miner's own setup downloads it at Connect's next look; then every book paired with its audiobook
  is lined up by itself, and an audiobook's own subtitles are spot-checked) or *Not now* (their cards without sentence
  audio). The answer kept for good (`lineup.set_answer`), the question fixed, every episode it held queued again.
- `book_audiobook(language, need_id)` (Kura-AB2, PROVISIONAL): *Mine without audio* on a book's *Do you have 「…」's
  audiobook?* — kept for that book for good (the ledger's meta), the question fixed, every part it held queued
  again.
- `add_audio(language, need_id, settings)` / `add_audio_book(language, epub, settings)` (the book row's ⋯, whose
  entry `add_audio_offer` asks for) / `add_audio_undo(language, record_id, settings)` (Kura-AB3 A2,
  PROVISIONAL): *Add the narrator's voice* on a book's *「…」: N of its cards were made before its audiobook was lined
  up* — `add_audio.act` with `--confirm`'s sequence (only empty sentence-audio fields, one Undo record, Anki's sync
  owed) for the book its line names; the line fixed once there's nothing left to add. Not a short write: Anki's
  cards are written on the worker (the writer's lock; never while you review). Its toast's *Undo* is `add_audio_undo`.

Each runs on the window's worker, one short ledger transaction; the caller kicks Connect after (`kick.kick`). No
ledger → nothing written (the window never makes one). Light: the standard library and the ledger.
"""
import json
import os

from app.connect import ledger as book

NOTHING_ADDED = "「{title}」: no card got the narrator's voice (each was filled or changed meanwhile)."
NONE_TO_ADD = "「{title}」: no card can get the narrator's voice — {why}."
NONE_WHY = ("{n} have sentence audio already", "{n} aren't said in its audiobook", "{n} are gone from Anki")
PART_STOPPED = ("Some of 「{title}」's cards got the narrator's voice before this stopped ({why}). Undo takes them back; "
                "adding again does the rest.")


def mine_anyway(language, need_id, path=None):
    """*Mine anyway* -> True when the job was queued again; False (nothing written) when there's no ledger, the entry
    isn't an open *not timed* one of this language, or its item has no open job any more (dropped, finished)."""
    path = path or book.path()
    if not os.path.exists(path):
        return False
    with book.Ledger(path) as ledger, ledger.transaction():
        row = ledger.conn.execute("SELECT item_id, job_id FROM needs WHERE id = ? AND language = ? AND kind = "
                                  "'not-timed' AND fixed_at IS NULL", (need_id, language)).fetchone()
        if row is None or row[0] is None:
            return False
        item_id, job_id = row
        job = ledger.job_by_id(job_id) if job_id is not None else None
        if job is None or job.get("item_id") != item_id or job.get("state") not in book.OPEN:
            job = ledger.job(language, item_id)
        if job is None or job.get("state") not in book.NOT_STARTED:
            return False                # dropped, finished, or past its pick already: nothing of it to force
        picked = ledger.picked(job["id"]) or {}
        picked["forced"] = True
        ledger.set_state(job["id"], "queued", picked=picked)        # its reason and resume step cleared: picks anew
        ledger.conn.execute("UPDATE needs SET fixed_at = ? WHERE id = ?", (book._now(), need_id))
    return True


def speech_model(language, need_id, yes, path=None):
    """*Download it* (`yes`) / *Not now* -> True when the question was open (answered now); False (nothing written)
    when there's no ledger or no such open question of this language."""
    path = path or book.path()
    if not os.path.exists(path):
        return False
    from app.connect import lineup
    with book.Ledger(path) as ledger, ledger.transaction():
        row = ledger.conn.execute("SELECT 1 FROM needs WHERE id = ? AND language = ? AND kind = 'speech-model' AND "
                                  "fixed_at IS NULL", (need_id, language)).fetchone()
        if row is None:
            return False
        says = {r[0] for r in ledger.conn.execute("SELECT say FROM needs WHERE language = ? AND kind = 'speech-model' "
                                                  "AND fixed_at IS NULL", (language,))}
        lineup.set_answer(yes)
        for job in ledger.jobs(language, states=("waiting",)):      # either wording, asked before or since (B-6)
            if job.get("reason") in says or lineup.asks_speech(job.get("reason")):
                ledger.set_state(job["id"], "queued")      # its reason cleared: picks anew, the answer read then
        ledger.conn.execute("UPDATE needs SET fixed_at = ? WHERE language = ? AND kind = 'speech-model' AND "
                            "fixed_at IS NULL", (book._now(), language))
    return True


def book_audiobook(language, need_id, path=None):
    """Kura-AB2 *Mine without audio* on *Do you have 「…」's audiobook?* -> True when the question was open (answered
    now); False (nothing written) when there's no ledger or no such open question of this language. The answer kept
    for the book for good (the ledger's meta, by the key its question was asked with: `runner.BOOK_ASKED` /
    `BOOK_SAID`), the question fixed, every part it held queued again (its pick reads the answer then). *Pick its
    audiobook…* needs nothing here: the pair is the store's, and the next look finds it (`runner._book_answered`)."""
    path = path or book.path()
    if not os.path.exists(path):
        return False
    from app.connect import runner
    with book.Ledger(path) as ledger, ledger.transaction():
        row = ledger.conn.execute("SELECT item_id, say FROM needs WHERE id = ? AND language = ? AND kind = ? AND "
                                  "fixed_at IS NULL", (need_id, language, runner.BOOK_AUDIO_NEED)).fetchone()
        asked = runner._json_or_none(runner._meta(ledger, f"{runner.BOOK_ASKED}{language}:{row[0]}")) \
            if row is not None and row[0] is not None else None
        if not asked or not asked.get("key"):
            return False
        ledger.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                            (f"{runner.BOOK_SAID}{language}:{asked['key']}", runner.NO_AUDIOBOOK))
        for job in ledger.jobs(language, states=("waiting",)):
            if job.get("reason") == row[1]:
                ledger.set_state(job["id"], "queued")      # its reason cleared: picks anew, the answer read then
        ledger.conn.execute("UPDATE needs SET fixed_at = ? WHERE id = ?", (book._now(), need_id))
    return True


def make_cards(language, gap_id, path=None, store_id=None):
    """*Make their cards* -> how many of the gap's episodes were queued (0: none left to queue — each has an open job
    or was mined); False (nothing written) when there's no ledger, no such gap of this language, or the library's
    identity can't be read. Each episode with no open job and never mined (`ledger.mined`) gets an ordinary `mine` job
    stamped with the library's identity (`store_id`: read from the library, read-only, unless given — a job without
    one is never mined into this library, `runner._job`); the gap marked noticed."""
    path = path or book.path()
    if not os.path.exists(path):
        return False
    store_id = store_id or _store_id(language)
    if not store_id:
        return False
    queued = 0
    with book.Ledger(path) as ledger, ledger.transaction():
        row = ledger.conn.execute("SELECT items FROM gaps WHERE id = ? AND language = ?", (gap_id, language)).fetchone()
        if row is None:
            return False
        for item_id in dict.fromkeys(json.loads(row[0] or "[]")):
            job = ledger.job(language, item_id)
            if (job is not None and job.get("state") in book.OPEN) or ledger.mined(language, item_id):
                continue
            if ledger.queue(language, item_id, "user", None, store_id) is not None:
                queued += 1
        ledger.mark_noticed([gap_id])
    return queued


def stoppable(state, resume=None, progress=None):
    """Can a job in `state` (waiting at `resume`; mining at `progress`) still be stopped (the window offers *Stop* only
    then)? The ledger's one rule (`ledger.stoppable`): until its cards are made — never once their clips are named."""
    return book.stoppable(state, resume, progress)


def stop(language, job_id, path=None):
    """*Stop* -> True when the press was recorded (the job is open, of this language, not yet past mining); False
    (nothing written) otherwise. Wakes a running Connect so it acts within a second or two, not at its next look: a
    program the job waits on is ended within a second (tsubasa's check, Anki Miner's look-ups; laptop round 9 #56) or
    cancelled (Anki Miner's run, its cards so far kept)."""
    path = path or book.path()
    if not os.path.exists(path):
        return False
    with book.Ledger(path) as ledger:
        job = ledger.job_by_id(job_id)
        if job is None or job.get("language") != language or not stoppable(job.get("state"), job.get("resume"),
                                                                           job.get("progress")):
            return False
        if not ledger.ask_stop(job_id):
            return False
    from app.connect import kick
    kick.wake()
    return True


def _store_id(language):
    """The library's identity (`library.store_id`), read-only (`mode=ro`: never made or written), or None."""
    from app.connect import window_link
    conn = window_link._store_ro(language)
    if conn is None:
        return None
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'store_id'").fetchone()
        return row[0] if row else None
    except Exception:
        return None
    finally:
        conn.close()


def add_audio(language, need_id, settings, path=None):
    """Kura-AB3 A2: *Add the narrator's voice* on the book's *Needs you* line -> `add_audio_book`'s answer for the book
    the line names. Nothing open (fixed, another language's or kind's, no ledger): {"ok": False, "say": None}."""
    from app.connect import runner
    path = path or book.path()
    if not os.path.exists(path):
        return {"ok": False, "say": None}
    with book.Ledger(path) as ledger:
        row = ledger.conn.execute("SELECT item_id FROM needs WHERE id = ? AND language = ? AND kind = ? AND "
                                  "fixed_at IS NULL", (need_id, language, runner.ADD_AUDIO_NEED)).fetchone()
        asked = None
        if row is not None:
            for _key, value in ledger.conn.execute("SELECT key, value FROM meta WHERE key >= ? AND key < ?", (
                    f"{runner.ADD_AUDIO_ASKED}{language}:", f"{runner.ADD_AUDIO_ASKED}{language};")):
                got = runner._json_or_none(value) or {}
                if got.get("item") == row[0]:
                    asked = got
    if not asked or not asked.get("epub"):
        return {"ok": False, "say": None}
    return add_audio_book(language, asked["epub"], settings, path=path, title=asked.get("title"))


def add_audio_book(language, epub, settings, path=None, title=None):
    """Kura-AB3 A2: *Add the narrator's voice* for the book `epub` (its line's press, or its row's ⋯) — `add_audio.act`
    with `--confirm` -> {"ok": True, "filled", "id" (its Undo), "title", "not_cut", "why", "say": None} or {"ok":
    False, "say": plain words} (nothing added: the line stays, pressed again it asks again). A press that ran keeps
    the book's notes it looked at (`runner.ADD_AUDIO_SEEN`: the row offers only newer ones) and, once something was
    added or nothing is left, fixes the book's line."""
    from app.cli.contract import CliError
    from app.connect import add_audio as adding
    from app.connect import runner
    path = path or book.path()
    title = title or os.path.splitext(os.path.basename(epub))[0]
    try:
        done = adding.act(settings, language, book=epub, confirm=True)
    except CliError as e:
        rid = e.context.get("undo")
        if rid:                                 # stopped part-way: its Undo in the window, in its own words (r1 S4)
            return {"ok": False, "id": rid, "say": PART_STOPPED.format(title=title, why=e.context.get("why") or "")}
        return {"ok": False, "say": e.message}
    if done.get("skipped"):
        return {"ok": False, "say": done["skipped"]}
    title = done.get("book") or title
    if not done.get("filled") and done.get("can"):      # all filled or refused meanwhile: nothing added
        return {"ok": False, "say": NOTHING_ADDED.format(title=title)}
    answer = {"ok": True, "filled": done.get("filled") or 0, "id": done.get("id"), "title": title,
              "not_cut": done.get("not_cut", 0), "why": done.get("not_cut_why"), "say": None}
    if not done.get("filled"):                  # nothing could get it: why, in plain words (r1 S3); the line goes
        why = [w.format(n=done[k]) for w, k in zip(NONE_WHY, ("has_audio", "unheard", "gone")) if done.get(k)]
        answer = {"ok": False, "say": NONE_TO_ADD.format(title=title, why=", ".join(why) or "none is left")}
    key = runner.book_key(epub, runner_sha(settings, language, epub))
    with book.Ledger(path) as ledger, ledger.transaction():
        seen_key = f"{runner.ADD_AUDIO_SEEN}{language}:{key}"
        seen = set(_ids(runner._meta(ledger, seen_key))) | {int(n) for n in done.get("looked") or ()}   # merged (r2 B2)
        ledger.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (seen_key, json.dumps(sorted(seen))))
        asked = runner._json_or_none(runner._meta(ledger, f"{runner.ADD_AUDIO_ASKED}{language}:{key}")) or {}
        if asked.get("item") is not None:
            ledger.conn.execute("UPDATE needs SET fixed_at = ? WHERE language = ? AND kind = ? AND item_id = ? AND "
                                "fixed_at IS NULL", (book._now(), language, runner.ADD_AUDIO_NEED, asked["item"]))
    return answer


def _ids(text):
    try:
        got = json.loads(text or "[]")
    except (TypeError, ValueError):
        return []
    return [int(n) for n in got if isinstance(n, int) and not isinstance(n, bool)] if isinstance(got, list) else []


def runner_sha(settings, language, epub):
    """The EPUB's sha256 as the library holds it (the book's key: a moved book is the same one), or None."""
    from app.connect import runner
    try:
        return runner.Steps(settings).made_before(language, epub)[2]
    except Exception:
        return None


def add_audio_offer(language, item_ids, settings, steps=None, path=None):
    """Kura-AB3 A2: the book row's ⋯ (asked on a worker as it opens) — whether a row of `item_ids` is a book whose
    cards Connect made are lined up for the narrator's voice -> {"epub", "title", "n" (its Connect notes no press
    looked at yet)}, or None (Connect off, another row, no line-up, nothing new). The store and the line-up read only;
    Anki isn't asked (the press's plan says what each card holds)."""
    if not (settings or {}).get("connect_enabled") or not item_ids:
        return None
    import sqlite3
    from app.connect import add_audio as adding
    from app.connect import library, runner
    steps = steps or runner.Steps(settings)
    want = set(item_ids)
    try:
        with steps._open(language) as store:            # one open: the pairs, the book's parts, its notes, its title
            found = None
            for epub, _item, sha in library.paired_books(store):
                parts = adding.book_items(store, epub)
                if want & set(parts):
                    found = (epub, parts, sha)
                    break
            if found is None:
                return None
            notes = adding.made_notes(store, found[1])
            title = (library.book_of(store, found[0]) or {}).get("title") or \
                os.path.splitext(os.path.basename(found[0]))[0]
        if not notes or not steps.lined_up(language, found[0]):
            return None
        path = path or book.path()
        asked, seen = None, []
        if os.path.exists(path):
            key = runner.book_key(found[0], found[2])
            with book.Ledger(path) as ledger:
                asked = runner._json_or_none(runner._meta(ledger, f"{runner.ADD_AUDIO_ASKED}{language}:{key}"))
                seen = _ids(runner._meta(ledger, f"{runner.ADD_AUDIO_SEEN}{language}:{key}"))
    except (runner.Wait, runner.Needs, OSError, sqlite3.Error, ValueError):
        return None                                     # (Connect writing, a record unread: no entry this time)
    # the cards made before it lined up (the asked record's, else every one: not asked yet) — never those mined since,
    # which carry the narrator already (r2 B2) — less what a press looked at
    before = set(_ids(json.dumps(asked["notes"]))) if asked and isinstance(asked.get("notes"), list) else set(notes)
    rest = (before & set(notes)) - set(seen)
    if not rest:
        return None
    return {"epub": found[0], "title": title, "n": len(rest)}


def add_audio_undo(language, record_id, settings):
    """Kura-AB3 A2: the toast's *Undo* of `add_audio` -> {"ok", "emptied" (how many), "kept" (how many: edited since,
    gone), "say"}."""
    from app.cli.contract import CliError
    from app.connect import add_audio as adding
    try:
        done = adding.act(settings, language, undo_id=record_id)
    except CliError as e:
        return {"ok": False, "say": e.message, "emptied": 0, "kept": 0}
    if done.get("skipped") or done.get("refused"):
        return {"ok": False, "say": done.get("skipped") or None, "emptied": 0, "kept": 0}
    return {"ok": True, "emptied": len(done.get("emptied") or ()), "kept": len(done.get("kept") or {}), "say": None}
