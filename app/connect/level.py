"""The level raise (P2.2 row 2.2.6; HC-N38 / N53; P1.5 06-edges E23) — since the mining model (Kantan-MO, 3.0.18;
MODEL.md, ADVERSARY.md F1) a raise **never mines an episode again**.

When the list gains words — the level raised by hand, or automatic rarity moving it — the newly listed words just join
the study order: Connect cards them as it meets them in the episodes ahead, each up to the cap's window. Until 3.0.17
a raise queued a `level` job for every already-mined episode (the top 20, then the rest of Current and Goal), each
opening its video again for its newly listed words: on a big library, hundreds of Anki Miner jobs for one move of the
slider (Sonic: a move to Rare must not mine a lot again). A `level` job queued before the update and not yet started is
dropped by the runner (`runner.LEVEL_DROPPED`); one under way finishes, by its own words (`restrict`).

Lowering the level mines nothing either (N38: the words that left keep their cards). Either way the deck is re-sorted
(`resort_due`, paid by the runner's ordering step, P2.4): the list's words moved.

**One exception, not a raise: new files.** A new episode placed on top is mined before its Generate, from the
re-plan's list (`replan`'s "new-files"); the Generate after mining then lists words only that episode brought. Those
episodes alone — mined in that run, before Connect's own Generate (`Ledger.mark_new_files`, taken here) — get a
`level` job for their newly listed words (`NEW_FILES`, its source: the runner keeps it), as P4.1 C5 built it.

- **Newly listed** = the list's keys now (`(Word, Reading)`: the pick's identity) minus the keys of the list Connect
  last looked at (the ledger's `listed`) — counted (`new`), never queued. The first look records the list (✅ G1.1-2:
  from the moment Connect is on, never your history); switched on again, `forget` makes the next look a first look. A
  look at the same run signature does nothing.

Pure apart from the ledger it is handed; the caller reads the list under `results` (`app/cli/connect_verbs.py`).
Light: the standard library only.
"""
import os

from app.connect import library
from app.connect.ledger import Ledger


# A level job for an episode mined before its own Generate (new files): kept by the runner, unlike a raise's
NEW_FILES = "new-files"


def check(store, language, listed, signature, file_words, ledger=None):
    """One look at the list -> {"queued": [item ids], "new": n newly listed, "first": bool, "waiting": bool}.

    `listed`: the list's keys `{(word, reading), …}` (None: no list of this language in `results/`); `signature`: the
    run that wrote it (`read_run_stamp`); `file_words`: `{file name: [lemma, …]}` (the last Generate's
    `file_words.json`). Queued only for the new-files exception (the module's docstring)."""
    out = {"queued": [], "new": 0, "first": False, "waiting": False}
    if listed is None or not signature:
        return out
    own = ledger is None
    ledger = ledger or Ledger()
    try:
        now = {(str(w), str(r)) for w, r in listed}
        with ledger.transaction():
            recorded_signature, recorded = ledger.recorded_list(language)
            if recorded_signature == signature:
                return out
            if recorded_signature is None:
                ledger.take_new_files(language)  # a first look lists every word as it is: no episode lacks its own
                ledger.record_list(language, signature, now)
                out["first"] = True
                return out
            if ledger.in_flight(language):
                out["waiting"] = True
                return out
            new = now - recorded
            out["new"] = len(new)                # they join the study order: no episode is mined again (F1) ...
            mined = ledger.take_new_files(language)
            if new and mined:                    # ... but the new files Connect mined before its own Generate
                out["queued"] = _queue(store, language, ledger, new, file_words or {}, mined)
            ledger.record_list(language, signature, now)
            ledger.owe_resort(language)
        return out
    finally:
        if own:
            ledger.close()


def _queue(store, language, ledger, new, file_words, mined):
    by_lemma = {}
    for word, reading in new:
        by_lemma.setdefault(word, set()).add((word, reading))
    made = library.made_words_all(store)
    queued = []
    for item_id in mined:
        item = store.item(item_id)
        if not wants(item):
            continue                        # taken out of the learning order (D14), or watched (#49): no level job
        lemmas = set(file_words.get(os.path.basename(item.get("rel_path") or "")) or ())
        words = {key for lemma in lemmas if lemma not in made for key in by_lemma.get(lemma, ())}
        if words and ledger.queue_level(language, item_id, words, source=NEW_FILES,
                                        store_id=library.store_id(store)) is not None:
            queued.append(item_id)
    return queued


def forget(language, ledger=None):
    """Connect switched on again (the preview's switch, P3.1, beside `library.switch_on`): the list it last looked at
    is forgotten, so the next look records the list as it is and mines nothing it gained while Connect was off
    (✅ G1.1-2)."""
    own = ledger is None
    ledger = ledger or Ledger()
    try:
        with ledger.transaction():
            ledger.forget_list(language)
    finally:
        if own:
            ledger.close()


# 3.0's rule (laptop round 8 #49, LF4-1 = A; Sonic 2026-10-22: "new words never come from a watched episode YET. This
# is critical, as in 3.1, it will pick the best sentence which often may come from watched episodes / series"): Connect
# makes no new cards on its own from an episode you've watched — neither its first mining nor a level raise; your ask
# (*Mine this*, *Mine now*) always does. 3.1's best-sentence pick (P6.1, Swap and the sentence library) lifts it: False.
WATCHED_GIVES_NO_NEW_CARDS = True


def watched_out(item):
    """Is this item one Connect makes no new cards from on its own (`WATCHED_GIVES_NO_NEW_CARDS`: you've watched it)?"""
    return WATCHED_GIVES_NO_NEW_CARDS and bool((item or {}).get("watched"))


def wants(item):
    """Does a level raise mine this (already mined) item? Never one taken out of the learning order (D14), never one
    you've watched (`watched_out`: its new words go to the episodes ahead of you, so the card comes before the word; the
    runner drops a job whose episode was marked watched since, `runner.WATCHED`)."""
    return item is not None and item.get("in_learning_order") != 0 and not watched_out(item)


def restrict(listed, job):
    """A level job's list: only its words (`pick` sends Anki Miner nothing else). Any other job: `listed` as is."""
    if not job or job.get("kind") != "level":
        return listed
    only = set(job.get("words") or ())
    return {key: rank for key, rank in (listed or {}).items() if key in only}
