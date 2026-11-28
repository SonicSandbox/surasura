"""The level raise (P2.2 row 2.2.6; HC-N38 / N53; P1.5 06-edges E23) — since TOP-UP (3.0.21, Sonic § 114: "We should
be able to mine from them") a raise **tops up the episodes already mined**, under the cap.

When the list gains words — the level raised by hand, automatic rarity moving it, new content, a re-Generate — each
episode Connect has already mined and that is still ahead of you gets a `level` job naming only its **newly listed**
words (`TOP_UP`, its source): the same cap and the same order as a first mining — the cap's window holds it
(`runner._full`: it carries no ask; placed by its own words, `Steps._job_rank`), the soonest episode first (the top 20,
then the rest of Current and Goal, `library.ahead`, as `runner._ordered` runs them), *Mine only episodes I've
pre-studied* holds it as any of Connect's own picks (`runner.held_by_prestudy`). Only a word with no card anywhere: a
word Connect ever made from any episode or show (`library.made_words_all`, a deleted card's too: G1.3-4) is never
named, and the job's pick still skips a word any card holds by then (the known-words sync's carded set) — never a
second card for a word, never an existing card touched. A watched episode, or one taken out of the learning order,
gets none (`wants`); an episode never mined gets none either (its first mining reads the list as it is now).

Until 3.0.17 a raise queued such a job for every mined episode with no cap's window; Kantan-MO (3.0.18) then mined
none again (the newly listed words joined the study order only, so a word met only in mined episodes was never carded:
a tester's Dungeon Meshi episodes at 15–42 *new* each, 2026-11-28). The window is what keeps a move to Rare from
mining a lot at once: past it the jobs wait until you study (`Your N cards are waiting`).

**The press** (`actions.top_up`, *Mine the new words* on a mined episode's ⋯ and its show's): the same rule at once —
`new_words`, the episode's listed words no card holds and Connect never made (a card you deleted is never remade:
*Mine again* does that), read against the whole list rather than one raise's new words, so an episode whose words
joined while no top-up was queued (3.0.18–3.0.20 recorded those raises) is reached too. One rule, two triggers; the
job carries the press's time, so it goes first and past the cap as any press does (Sonic's M-3 A).

Lowering the level mines nothing (N38: the words that left keep their cards). Either way the deck is re-sorted
(`resort_due`, paid by the runner's ordering step, P2.4): the list's words moved.

**New files:** a new episode placed on top is mined before its Generate, from the re-plan's list (`replan`'s
"new-files"); the Generate after mining then lists words only that episode brought. Those episodes (`Ledger.
mark_new_files`, taken here) get their newly listed words as `NEW_FILES` jobs, as P4.1 C5 built it.

- **Newly listed** = the list's keys now (`(Word, Reading)`: the pick's identity) minus the keys of the list Connect
  last looked at (the ledger's `listed`). The first look records the list (✅ G1.1-2: from the moment Connect is on,
  never your history); switched on again, `forget` makes the next look a first look. A look at the same run signature
  does nothing.

Pure apart from the ledger and the store it is handed; the caller reads the list under `results`
(`app/cli/connect_verbs.py`). Light: the standard library only.
"""
import os

from app.connect import library
from app.connect.ledger import Ledger


# A level job for an episode mined before its own Generate (new files): kept by the runner, unlike a raise's
NEW_FILES = "new-files"
# Kantan-SD: a level job for a word whose best sentence is in this episode (the sentence dial's Best, `runner._best`)
# — kept by the runner, watched or finished too (the context you remember is why it was chosen)
BEST = "best-sentence"
# TOP-UP (3.0.21, Sonic § 114): an episode already mined, its newly listed words no card holds (a raise, new content,
# a re-Generate) — with the press's time: *Mine the new words*
TOP_UP = "top-up"
KEPT = (NEW_FILES, BEST, TOP_UP)


def check(store, language, listed, signature, file_words, ledger=None):
    """One look at the list -> {"queued": [item ids], "new": n newly listed, "first": bool, "waiting": bool}.

    `listed`: the list's keys `{(word, reading), …}` (None: no list of this language in `results/`); `signature`: the
    run that wrote it (`read_run_stamp`); `file_words`: `{file name: [lemma, …]}` (the last Generate's
    `file_words.json`). Queued: the mined episodes' new words, soonest first (the module's docstring)."""
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
                ledger.take_new_files(language)  # a first look (Connect on again too) lists every word: none lacks its own
                ledger.record_list(language, signature, now)
                out["first"] = True
                return out
            if ledger.in_flight(language):
                out["waiting"] = True
                return out
            new = now - recorded
            out["new"] = len(new)
            marked = ledger.take_new_files(language)    # taken whatever the raise: a mark is one look's
            if new:                              # TOP-UP: each mined episode ahead of you, its new words (the cap's)
                out["queued"] = _queue(store, language, ledger, new, file_words or {}, marked)
            ledger.record_list(language, signature, now)
            ledger.owe_resort(language)
        return out
    finally:
        if own:
            ledger.close()


def _by_lemma(keys):
    """{lemma: {(word, reading), …}} of the list's keys (an episode's `file_words` are lemmas)."""
    out = {}
    for word, reading in keys:
        out.setdefault(word, set()).add((word, reading))
    return out


def new_words(item, file_words, by_lemma, made):
    """TOP-UP's one rule for an episode's words still to card: its file's lemmas (the last Generate's `file_words`)
    that the list names (`by_lemma`: the keys looked at), none Connect ever made (`made`: any episode, any show, a
    deleted card's too) -> {(word, reading)}. Words any card holds are the pick's to skip (its carded set)."""
    lemmas = set(file_words.get(os.path.basename((item or {}).get("rel_path") or "")) or ())
    return {key for lemma in lemmas if lemma not in made for key in by_lemma.get(lemma, ())}


def mined_items(store, language, ledger):
    """Every item a first mining finished: the store's receipts (`mined_at`) and the ledger's `done` jobs, one read
    each (never a read per item)."""
    with store._reading():
        out = {row[0] for row in store.conn.execute("SELECT id FROM items WHERE mined_at IS NOT NULL")}
    return out | ledger.mined_items(language)


def _queue(store, language, ledger, new, file_words, marked):
    """The raise's jobs (inside the caller's transaction) -> [item ids queued], soonest first: the new files marked
    (`NEW_FILES`), then every other mined episode ahead of you (`TOP_UP`). One walk of the order, one read of the
    receipts and of the made words; an item read only when it was mined."""
    by_lemma = _by_lemma(new)
    made = library.made_words_all(store)
    marked = list(dict.fromkeys(marked or ()))
    first = set(marked)
    mined = mined_items(store, language, ledger)
    queued = []
    for item_id in marked + [i for i in library.ahead(store) if i in mined and i not in first]:
        item = store.item(item_id)
        if not wants(item):
            continue                        # taken out of the learning order (D14), or watched (#49): no level job
        words = new_words(item, file_words, by_lemma, made)
        source = NEW_FILES if item_id in first else TOP_UP
        if words and ledger.queue_level(language, item_id, words, source=source,
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
    """A level job's list: only its words (`pick` sends Anki Miner nothing else) — a Best word not on the list
    (*Cards for every new word*) after the listed ones. Any other job: `listed` as is."""
    if not job or job.get("kind") != "level":
        return listed
    only = set(job.get("words") or ())
    kept = {key: rank for key, rank in (listed or {}).items() if key in only}
    if job.get("source") == BEST:
        kept.update((key, len(listed or {})) for key in sorted(only - set(kept)))
    return kept
