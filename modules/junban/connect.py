# SPDX-License-Identifier: GPL-3.0-or-later
"""Junban and Backfill for Surasura Connect (P1.4; the spec: `docs/agent instructions/3.0/P1.5-connect/`, RUNBOOK-P1.4).

Everything here changes a run **only while the Connect preview is on** (`connect_enabled`, read once per run through
`preview_on`). Off, every Junban and Backfill run is 2.5's, byte for byte (`tests/test_preview_gate.py`).

What Connect's runs add:

* **Your own cards first** (HC-N54, row 1.4.3; P1.4-1, Sonic 2026-10-06): a new card without Connect's tag
  (`surasura::connect::<job>`) that you mined after Connect made its first card (Yomitan, Anki Miner's window) — and
  any card carrying the tag you name (`junban_own_tag`, "immersion"), whenever mined — goes ahead of every other new
  card, in the order you mined it, and is never tagged, flagged or suspended as "not on your list". Your backlog from
  before Connect keeps Junban's order. `junban_order_all` puts every new card, yours too, in the list's order (still
  never suspended).
* **A returning word's card** (MR-R3, row 1.4.4): a card Junban parked (suspended, carrying its `::later` tag) whose
  word is back on your list is unsuspended and placed with the list. In 2.6 / 2.7 only in a run you start in 順;
  unattended (Connect's step, `junban --auto`) **only from 3.0** (`UNATTENDED_SUSPEND`, G1.3-8).
* **A sentence with no bold mark** (K56, row 1.4.5): the card's word found in its sentence by its forms — the lemma,
  the dictionary spelling or the surface the tokenizer reads, a kana word by its kana — when neither a `<b>` mark nor
  the word as written is there. Two different words that could both be it: no guess; the card stays where its
  sentence can't place it, and the preview names it.

Pure apart from `parked_query` / `first_connect_note`'s reads: no Tk, no settings file, no writes.
"""

from modules.junban import match

# Connect's job tag (`app/connect/runfile.TAG_PREFIX`): every note one of its jobs makes carries `<prefix><job id>`.
TAG_PREFIX = "surasura::connect::"

# G1.3-8 (Sonic, 2026-10-05: "For junban suspending, just reorder for this version but for 3.0 it should suspend if
# you have that in settings for junban"): in 2.6 / 2.7 an unattended run only reorders — no suspend, no unsuspend.
# The 3.0 line sets this to True: an unattended run then suspends as Junban's suspend setting says, and unsuspends a
# returning word's card, each recorded in that run's own snapshot.
# 3.0 LINE ONLY (W3.5 row 7, the lead's 🧭): True here; 2.x-dev keeps False. A take-in from 2.x-dev keeps 3.0's side.
UNATTENDED_SUSPEND = True

# HY-6 (Sonic, 2026-10-13: "once they go through the onboarding which asks whether or not it's ok to do these things
# … it just works"): on 3.0 Connect being on no longer makes every automatic re-order positions only — your
# `junban_auto_actions` and the actions' own settings decide, for the window's re-order host and Connect's step alike
# (`auto.decide_actions`). 2.x-dev keeps False (G1.3-8's "just reorder for this version"). `junban --auto` and `resort`
# stay positions only on both lines (their `positions_only`).
# 3.0 LINE ONLY (P3.3 C2, the lead's 🧭): True here; 2.x-dev keeps False. A take-in from 2.x-dev keeps 3.0's side.
UNATTENDED_ACTIONS = True

# *Study its cards first* (G1.6-10; E1.1 03 §8; P2.2): the user's own pins go first in every Junban run. ✅ E1.3-3
# ("no pinning until 3.0s window"): in 2.x no writer reads a pin — every run is 2.5's, request for request. The 3.0
# line sets this to True, where the store reads them (`Store.pinned()`, `cards_of()`: L3.1) and the window makes them
# — only the user's own pins: nothing pins or un-pins by itself (HC-N7 as amended; P2.2's 2.2.7 guard).
# 3.0 LINE ONLY (P4.2 row P4.2.1): True here; 2.x-dev keeps False. A take-in from 2.x-dev keeps 3.0's side.
PINS = True

# Why a card stays where its sentence can't place it, when two words in it could be the card's.
UNSURE = "which word? (no bold)"


def preview_on(settings):
    """Is the Connect preview on? Only an explicit True: a missing or garbled key is off, as on every 2.5 install."""
    return (settings or {}).get("connect_enabled") is True


def suspends_unattended(settings):
    """May an unattended run suspend (the cards not on the list) and unsuspend (a returning word's card)? From 3.0
    only, while the preview is on and Junban's own suspend setting is on (G1.3-8)."""
    return UNATTENDED_SUSPEND and preview_on(settings) and (settings or {}).get("junban_later_suspend") is True


def unsuspends(settings, unattended, acting=False):
    """Does this run unsuspend a returning word's card (MR-R3)? A run you start in 順, while the preview is on and
    Junban's suspend setting is on; an unattended one only as `suspends_unattended` says. With that setting off, the
    `::later` tag marks cards Junban only tagged: one you suspended yourself stays suspended.

    `acting` (M-W1; the lead's W-1 rule — a stone's cards step back and come back the same way): an automatic job that
    applies Junban's actions (`job.actions`: the window's re-order host, AutoJunban). On 3.0 (`UNATTENDED_SUSPEND`) it
    may suspend with Connect off (`auto.decide_actions` keeps Junban's suspend setting), so it brings back what it
    parked, Connect on or off. A run you start in 順 with Connect off stays 2.5's (`tests/test_preview_gate.py`)."""
    if (settings or {}).get("junban_later_suspend") is not True:
        return False
    if acting and UNATTENDED_SUSPEND:
        return True
    if not preview_on(settings):
        return False
    return suspends_unattended(settings) if unattended else True


def is_connects(tags):
    """Did Connect make this note? Anki's tags are case-insensitive, and a test run's tag is Connect's too."""
    return any(str(tag).lower().startswith(TAG_PREFIX) for tag in tags or ())


def first_connect_note(url):
    """The id of the oldest note Connect made — a note id is its creation time in ms — in any deck, studied or not;
    None when it has made none. One `findNotes`, ids only."""
    from app import anki_connect
    found = anki_connect.find_notes(url, f'"tag:{TAG_PREFIX}*"')
    return min(found) if found else None


def own_tag(settings):
    """The tag the user marks their own cards with (`junban_own_tag`, P1.4-1), or "" (none)."""
    value = (settings or {}).get("junban_own_tag")
    return value.strip() if isinstance(value, str) else ""


def order_all(settings):
    """`junban_order_all` (P1.4-1): every new card in the list's order, yours too. Only an explicit True."""
    return (settings or {}).get("junban_order_all") is True


def carries(tags, tag):
    """Does a note carry `tag` — or one under it (`immersion::yt`)? Anki's tags are case-insensitive."""
    tag = str(tag or "").strip().lower()
    return bool(tag) and any(str(t).lower() == tag or str(t).lower().startswith(tag + "::") for t in tags or ())


def mark_yours(cards, notes, first, tag=""):
    """Mark the cards you mined yourself: `yours` on each card dict whose note carries `tag` (the user's own tag,
    whenever mined), or carries no Connect tag and is newer than `first` (None: Connect has made nothing yet). Returns
    their card ids, in the order you mined them."""
    yours = []
    for card in cards:
        note_id = card.get("note")
        if not isinstance(note_id, int):
            continue
        tags = ((notes or {}).get(note_id) or {}).get("tags")
        if not (carries(tags, tag) or (first is not None and note_id > first and not is_connects(tags))):
            continue
        card["yours"] = True
        yours.append(card["card_id"])
    return sorted(yours)


def parked_query(deck, parent_tag):
    """The search for the cards Junban parked in `deck`: new, suspended, carrying its `::later` tag (Junban suspends
    only with that tag on, `unlisted.py`), never in a filtered deck."""
    from app.anki_connect import escape_query
    return (f'deck:"{escape_query(deck)}" is:new is:suspended "tag:{escape_query(parent_tag)}" '
            f'-deck:filtered')


def junbans(card, parked):
    """Did Junban park this card (suspended, its `::later` tag on)? P4.2.2 (P2.2 adversary #9): by its lasting record
    (`parked`: `first_touch.parked`'s) — a card whose suspend landed and that Surasura hasn't unsuspended since. One
    the record names otherwise (Junban only tagged it, or put it back since) is yours: you suspended it, and it stays
    so. A card the record never names that was made before the record began falls back to today's rule, the tag
    alone (Junban may have parked it before the record existed); one made since is yours. `parked` None: the tag
    alone (no record handed in)."""
    if parked is None:
        return True
    card_id = card.get("card_id")
    if card_id in parked["cards"]:
        return True
    if card_id in parked["named"] or card.get("note") in parked["notes"]:
        return False
    since = parked.get("since")
    return since is None or (isinstance(card_id, int) and card_id < since)


def returning(cards, marks_of, language, pinned=(), parked=None, out=()):
    """The parked cards (`parked` on the card dict) whose word is on the list again, in any form — the test
    `unlisted.plan` parked them by (`match.lookup` over every row of the list). Each one is made movable here
    (`queue` 0: the run unsuspends it before its position is written) and kept; the rest are dropped from the plan, so a
    run sees them exactly as 2.5 did: not at all. Returns (the cards to plan, the returning card ids).

    `pinned` (✅ E1.3-2, 3.0 only: `PINS`): the card ids of *Study its cards first* items — a parked one comes back
    too, whatever the list says (a finished show's words have left it), and the pin puts it first.

    `parked` (P4.2.2, #9): Junban's lasting record of the cards it parked (`first_touch.parked`); only a card Junban
    parked comes back, by the list or a pin — never one you suspended after Junban only tagged it (`junbans`).

    `out` (P4.1 L2): the card ids of items taken out of the learning order (`pins.out_cards`) — one never comes back
    while its item is out: it stays parked. (TF fix 3, P4.1-7: a card whose word is on the list is never `out`.)"""
    pinned = set(pinned or ())
    gone = set(out or ())
    kept, back = [], []
    for card in cards:
        if not card.get("parked"):
            kept.append(card)
            continue
        if not junbans(card, parked) or card.get("card_id") in gone:
            continue
        if card.get("card_id") in pinned or match.lookup(card.get("word") or "", marks_of or {}, language):
            card["queue"] = 0
            card["returning"] = True
            kept.append(card)
            back.append(card["card_id"])
    return kept, sorted(back)


# --- K56: the card's word in a sentence with no bold mark ------------------------------------------- #
def _key(text, language):
    if language == "ja":
        return match.fold_kana(text or "")
    if language == "zh":
        try:
            from app.zh_script import convert
            return convert(text or "", "s")
        except Exception:
            return text or ""
    return text or ""


def _is_kana(text):
    return bool(text) and all("ぁ" <= ch <= "ゖ" or "ァ" <= ch <= "ヺ" or ch == "ー" for ch in text)


# The endings a card's bold mark covers with its word (Anki Miner marks the word as said: <b>持っています</b>), read
# from UniDic's tags: an auxiliary (ます, た, ない, れる), a connective て / で, and after it the aspect verbs a
# dictionary's deinflection folds into the word (〜ている, 〜てしまう, 〜ておく, 〜ていく, 〜てくる) — never 〜てください,
# which the marks leave out. Measured on the 200 marked sentences of tests/Test Resources/ja/testAnki.apkg.
_ASPECT = {"居る", "仕舞う", "置く", "行く", "来る"}


def _ending(tagger, text, end):
    """Where the word that ends at `end` stops once its endings are counted with it (Japanese, UniDic's tags)."""
    if tagger is None:
        return end
    at, after_te = 0, False
    for word in tagger(text):
        surface, feature = word.surface, word.feature
        pos = text.find(surface, at) if surface else -1
        if pos < 0:
            continue
        at = pos + len(surface)
        if pos < end:
            continue
        if pos != end:
            break
        pos1, pos2, lemma = feature.pos1, feature.pos2, (feature.lemma or "").split("-")[0]
        if pos1 == "助動詞" or (pos1 == "助詞" and pos2 == "接続助詞" and lemma in ("て", "で"))                 or (after_te and pos1 == "動詞" and pos2 == "非自立可能" and lemma in _ASPECT):
            after_te = pos1 == "助詞"
            end = at
            continue
        break
    return end


def find_by_forms(raw, word, tokenize, language="ja", tagger=None):
    """Where the card's `word` sits in its sentence `raw` when no `<b>` mark says so and the word isn't there as
    written -> `(text, start, end)` (the plain sentence, as `anki_match.sentence_span` returns it), `None` (found as
    written or marked, so nothing to add; or not found at all), or `UNSURE` (two different words of the sentence could
    each be it — 掛ける and 欠ける for a かける card — never guessed between).

    A token is the card's word when the word is its lemma, its dictionary spelling or its surface (走る in 走った, a
    conjugated 撒け for 撒く), comparing kana as kana (Japanese) and Chinese in one script; a kana-only word also by its
    reading. The same word said twice is one word: the first time it's said. With `tagger` (Japanese: the tokenizer's
    own), the span takes in the word's endings, as a bold mark does (`_ending`)."""
    if tokenize is None or not isinstance(word, str) or not word or not isinstance(raw, str) or not raw.strip():
        return None
    if match.sentence_span(raw, word) is not None:
        return None
    text = match.normalize_word(raw)
    if not text:
        return None
    wanted = {_key(word, language)}
    if language == "ja" and word.endswith("じる"):
        wanted.add(_key(word[:-2] + "ずる", language))      # UniDic reads a じる verb as its ずる verb: 感じる is 感ずる
    kana = language == "ja" and _is_kana(word)
    found, at = {}, 0
    for token in tokenize(text):
        lemma, reading, surface = token[0], token[1], token[2]
        orth = token[3] if len(token) > 3 else surface
        pos = text.find(surface, at) if surface else -1
        if pos < 0:
            continue
        at = pos + len(surface)
        forms = {_key(lemma, language), _key(orth, language), _key(surface, language)}
        if kana and reading:
            forms.add(_key(reading, language))
        if wanted & forms:
            found.setdefault((lemma, reading), (pos, at))
    if len(found) > 1:
        return UNSURE
    if not found:
        return None
    start, end = next(iter(found.values()))
    return text, start, _ending(tagger, text, end) if language == "ja" else end


def bolded(found):
    """The sentence `find_by_forms` placed, with the word marked as Anki Miner marks it — what `anki_match` reads."""
    text, start, end = found
    return text[:start] + "<b>" + text[start:end] + "</b>" + text[end:]


def find_unbolded(cards, notes, tokenize, language):
    """For every card whose sentence has no bold mark and doesn't hold the word as written: its sentence with the word
    found by its forms marked (`notes[note]["sentence"]`, read by the planner in place of the field; the note's own
    fields are never touched), or the card's word in `unsure`. Returns the unsure words, sorted."""
    unsure = set()
    tagger = getattr(getattr(tokenize, "__self__", None), "tagger", None) if language == "ja" else None
    for card in cards:
        note = (notes or {}).get(card.get("note"))
        if not isinstance(note, dict) or "sentence" in note:
            continue
        found = find_by_forms((note.get("fields") or {}).get("Sentence"), card.get("word") or "", tokenize, language,
                              tagger)
        if found == UNSURE:
            note["unsure"] = True
            unsure.add(card.get("word") or "")
        elif found is not None:
            note["sentence"] = bolded(found)
    return sorted(unsure)


def sentence_of(note):
    """The sentence the planner reads for a note: the one `find_unbolded` marked, else the note's own field."""
    note = note or {}
    return note.get("sentence") or (note.get("fields") or {}).get("Sentence")
