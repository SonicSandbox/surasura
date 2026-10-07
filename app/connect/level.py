"""The level raise (P2.2 row 2.2.6; HC-N38 / N53; P1.5 06-edges E23, signed at G1.3-16).

When the list gains words — the level raised by hand, or automatic rarity moving it — Connect mines **only the newly
listed words**, skipping the words already mined, for the episodes it has already mined, **the top 20 first**. In 2.x
only the top 20 (the rest of the already-mined content waits for 3.0, HC-N53's "the rest in the background", P3.3);
lowering the level mines nothing (N38: the words that left keep their cards, at the back); either way the deck is
re-sorted (`resort_due`, paid by the runner's ordering step, P2.4).

- **Newly listed** = the list's keys now (`(Word, Reading)`: the pick's identity) minus the keys of the list Connect
  last looked at (the ledger's `listed`). The first look records the list and mines nothing (✅ G1.1-2: from the
  moment Connect is on, never your history). A look at the same run signature does nothing.
- **For whom:** each item of the top 20 (`library.mine_line`), in order, already mined (its receipt, or a `done` job)
  and with no other job open: its newly listed words (the last Generate's `file_words.json` for its file), minus any
  an item higher up took (one card per word, the top first), minus the words Connect already made for it (`made_words`,
  N15) → one `level` job naming just them. A job past its start (picking … ordering) → the whole look waits, nothing
  recorded, and the next look sees the same raise.
- **Only in the `list` mode** of *Which words become cards* (`connect_mine_words`, the default): the other two don't
  read the list, so a level raise gives them nothing new. The list is recorded whatever the mode.

Pure apart from the ledger it is handed and the store's reads (the top 20, receipts, made words); the caller reads
the list under `results` (`app/cli/connect_verbs.py`). Light: the standard library only.
"""
import os

from app.connect import library
from app.connect.ledger import Ledger


def check(store, language, listed, signature, file_words, mode="list", ledger=None):
    """One look at the list -> {"queued": [item ids], "new": n newly listed, "first": bool, "waiting": bool}.

    `listed`: the list's keys `{(word, reading), …}` (None: no list of this language in `results/`); `signature`: the
    run that wrote it (`read_run_stamp`); `file_words`: `{file name: [lemma, …]}` (the last Generate's
    `file_words.json`)."""
    out = {"queued": [], "new": 0, "first": False, "waiting": False}
    if listed is None or not signature:
        return out
    own = ledger is None
    ledger = ledger or Ledger()
    try:
        recorded_signature, recorded = ledger.recorded_list(language)
        if recorded_signature == signature:
            return out
        now = {(str(w), str(r)) for w, r in listed}
        with ledger.transaction():
            if recorded_signature is None:
                ledger.record_list(language, signature, now)
                out["first"] = True
                return out
            if ledger.in_flight(language):
                out["waiting"] = True
                return out
            new = now - recorded
            out["new"] = len(new)
            if new and mode == "list":
                out["queued"] = _queue(store, language, ledger, new, file_words or {})
            ledger.record_list(language, signature, now)
            ledger.owe_resort(language)
        return out
    finally:
        if own:
            ledger.close()


def _queue(store, language, ledger, new, file_words):
    by_lemma = {}
    for word, reading in new:
        by_lemma.setdefault(word, set()).add((word, reading))
    taken, queued = set(), []
    for item_id in library.mine_line(store):
        item = store.item(item_id)
        if item is None:
            continue
        lemmas = set(file_words.get(os.path.basename(item.get("rel_path") or "")) or ())
        made = library.made_words(store, item_id)
        words = {key for lemma in lemmas if lemma not in made for key in by_lemma.get(lemma, ())} - taken
        if not words:
            continue
        if library.mined_at(store, item_id) is not None or ledger.mined(language, item_id):
            if ledger.queue_level(language, item_id, words) is not None:
                queued.append(item_id)
            taken |= words
        elif ledger.has_work(language, item_id):
            # Its first mining, not started yet, reads the list as it is now: the new words are its, not a lower one's.
            taken |= words
    return queued


def restrict(listed, job):
    """A level job's list: only its words (`pick` sends Anki Miner nothing else). Any other job: `listed` as is."""
    if not job or job.get("kind") != "level":
        return listed
    only = set(job.get("words") or ())
    return {key: rank for key, rank in (listed or {}).items() if key in only}
