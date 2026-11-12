"""The window's short writes to Connect's ledger that start work (P4.1), beside `status.mark_seen` and `status.dismiss`.

- `mine_anyway(language, need_id)` (row 4.1.9; G1.3-6, 06-edges E16): *Mine anyway* on a *Needs you* entry that says
  an episode isn't timed to its video — the entry fixed, the item's job queued again with `picked.forced`, so its next
  pick mines it untimed (`runner._fit`: tsubasa isn't asked, no shift; logged *mined anyway: not timed*). The choice
  holds for the pairing it was made on: a pairing changed since (hato re-timed it, a new subtitle) is picked again and
  checked again, as any. On hato's name-only pairings (`verdict: untimed`) the entry carries `feed.UNTIMED_WARNING`.
- `check_again(language, item_id)` (Michi-NT, Mattias #XP44T6): *Check again* on a *Not timed* row or its ⋯ — the
  item's entry fixed (listed or dismissed) and its job queued, so its timing is checked anew: a subtitle you fixed is
  seen (the copy, or the same subtitle re-timed beside its video, `runner.retimed_beside`); still not timed, its entry
  is back in *Needs you*.
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

Each runs on the window's worker, one short ledger transaction; the caller kicks Connect after (`kick.kick`). No
ledger → nothing written (the window never makes one). Light: the standard library and the ledger.
"""
import json
import os

from app.connect import ledger as book


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


def check_again(language, item_id, path=None):
    """Michi-NT (Mattias #XP44T6, #7J3960): *Check again* on an episode Connect found not timed to its video (its row,
    or its ⋯) -> True when its job was queued again; False (nothing written) when there's no ledger, the item has no
    open *not timed* entry in this language (listed or dismissed), or no job of it is waiting any more. The entry fixed
    and the job queued (its reason, resume step and timing-check count cleared; the subtitle beside its video looked
    for again, and tsubasa may re-time its copy once more: Michi-NT2), so its next pick checks its timing anew — a subtitle you fixed since is seen; still not timed, a new
    entry counts in *Needs you* (its *Mine anyway*), a dismissed one included. The caller kicks Connect after."""
    path = path or book.path()
    if not os.path.exists(path):
        return False
    with book.Ledger(path) as ledger, ledger.transaction():
        open_ = ledger.conn.execute("SELECT 1 FROM needs WHERE language = ? AND item_id = ? AND kind = 'not-timed' "
                                    "AND fixed_at IS NULL", (language, item_id)).fetchone()
        job = ledger.job(language, item_id)
        if open_ is None or job is None or job.get("state") not in book.NOT_STARTED:
            return False
        picked = ledger.picked(job["id"]) or {}
        for key in ("beside", "copy", "beside_at", "checked"):
            picked.pop(key, None)
        ledger.set_state(job["id"], "queued", picked=picked)       # its reason and resume step cleared: picks anew
        ledger.forget_stop(job["id"])       # your press is your go, as a newer *Mine now* is (a *Stop* it waited by)
        ledger.conn.execute("DELETE FROM meta WHERE key IN (?, ?)",      # runner.FIT_TRY, runner.RETIMED: your
                            (f"fit_try:{int(job['id'])}", f"retimed:{int(job['id'])}"))     # press asks them anew
        ledger.conn.execute("UPDATE needs SET fixed_at = ? WHERE language = ? AND item_id = ? AND kind = 'not-timed' "
                            "AND fixed_at IS NULL", (book._now(), language, item_id))
    return True


SKIPPED_ON, SKIPPED_OWES = "on", "owes"   # Michi-RM3 review r2 N1: what a skip did, for the bar's words


def skip_refused(language, need_id, path=None):
    """Michi-RM3: *Skip this word* on a part whose cards Anki refused for some words (its *Needs you* line, kind
    `mine-refused`) -> SKIPPED_ON when skipped and the part goes on to its fill; SKIPPED_OWES when skipped but the
    part still owes another word (its row's *Try again* tries it) or a try already open holds it; False (nothing
    written) with no ledger, no such open line of this language, no word named, or its job no longer failed. Those words' outcomes become `skipped` (never sent again: in this part, `declined`,
    and in any other for that Anki Miner, `Ledger.skipped_words`); the line fixed; and the part goes on to fill and
    order the cards it did make (waiting at `filling`: Connect's next look, the caller kicks it) — unless a new try of
    the item is open already (one open job an item), which finishes the part without those words."""
    path = path or book.path()
    if not os.path.exists(path):
        return False
    with book.Ledger(path) as ledger, ledger.transaction():
        row = ledger.conn.execute("SELECT item_id, job_id FROM needs WHERE id = ? AND language = ? AND kind = "
                                  "'mine-refused' AND fixed_at IS NULL", (need_id, language)).fetchone()
        if row is None or row[1] is None:
            return False
        item_id, job_id = row
        job = ledger.job_by_id(job_id)
        if job is None or job.get("state") != "failed" or job.get("item_id") != item_id:
            return False
        meta = ledger.conn.execute("SELECT value FROM meta WHERE key = ?", (f"alone:{int(job_id)}",)).fetchone()
        try:
            words = [str(w) for w in (json.loads(meta[0]).get("words") or ())] if meta is not None else []
        except (ValueError, AttributeError):
            words = []
        if not words:
            return False                # nothing Anki refused alone is named: nothing to skip (review B1)
        marks = ",".join("?" * len(words))
        ledger.conn.execute(f"UPDATE outcomes SET outcome = 'skipped' WHERE job_id = ? AND word IN ({marks}) AND "
                            "outcome IN ('uncertain', 'not_attempted')", [job_id] + words)
        picked = (ledger.picked(job_id) or {}).get("words") or ()
        owed = [w for w in picked if (ledger.conn.execute(
            "SELECT outcome FROM outcomes WHERE job_id = ? AND word = ? AND reading = ?",
            (job_id, w.get("word"), w.get("reading"))).fetchone() or [None])[0] in (None, "uncertain", "not_attempted")]
        marks = ",".join("?" * len(book.OPEN))
        answer = SKIPPED_OWES
        if not owed and ledger.conn.execute(f"SELECT 1 FROM jobs WHERE language = ? AND item_id = ? AND state IN "
                                            f"({marks})", (language, item_id) + book.OPEN).fetchone() is None:
            ledger.set_state(job_id, "waiting", reason=None, resume="filling")   # this part goes on to its fill
            answer = SKIPPED_ON
        # (a word it still owes that Anki never refused alone — a run that timed out —: the part stays failed, its
        # *Try again* tries that word; the skipped ones never again. A try already open finishes it: SKIPPED_OWES too,
        # the row says what it does)
        ledger.conn.execute("UPDATE needs SET fixed_at = ? WHERE id = ?", (book._now(), need_id))
    return answer


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


def book_audiobook(language, need_id, path=None, answer=None):
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
                            (f"{runner.BOOK_SAID}{language}:{asked['key']}", answer or runner.NO_AUDIOBOOK))
        for job in ledger.jobs(language, states=("waiting",)):
            if job.get("reason") == row[1]:
                ledger.set_state(job["id"], "queued")      # its reason cleared: picks anew, the answer read then
        ledger.conn.execute("UPDATE needs SET fixed_at = ? WHERE id = ?", (book._now(), need_id))
    return True


def book_ai_audio(language, need_id, path=None):
    """Iro-AA *Make AI audio (beta)* on the same question (PROVISIONAL): answered as *Mine without audio* is — mined as
    the book, kept for good — with the answer `runner.AI_AUDIO`, so each part's new cards are queued for the AI voice
    as it fills (`runner._mark_ai_audio`). -> `book_audiobook`'s answer."""
    from app.connect import runner
    return book_audiobook(language, need_id, path, answer=runner.AI_AUDIO)


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
