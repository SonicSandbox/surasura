# SPDX-License-Identifier: GPL-3.0-or-later
"""The orchestration — the only place in this module that reads settings and writes to a collection.

Everything below this file is deliberately partial: the transport speaks to Anki but decides
nothing, the planner decides everything but touches nothing, the snapshot guards the way back but
writes no cards. This file is where those four meet, and therefore the only file that can do real
damage. It holds no logic of its own beyond sequencing, because sequencing *is* the risk:

    preflight  ->  gather  ->  resolve words  ->  plan  ->  SNAPSHOT  ->  write  ->  touch up
                                                                                  ->  refresh

**The snapshot comes before the first write and there is no second chance.** AnkiConnect's
`setSpecificValueOfCard` hardcodes `skip_undo_entry=True`, so a run that repositions 152 cards
creates zero Anki undo entries, and Anki's own Undo must never be offered as the way back — it would
revert whatever the user did *before* the run and leave every one of ours in place. `undo.save()` is
the entire recovery story (invariant I3), which is why it is called on the line above `set_due` and
why a failure to write it aborts the run rather than being logged and stepped over.

WP-L's touch-ups ride in the same order, deliberately at the END: a tag, a frequency entry and an
extra sentence are written only for the notes whose cards *actually moved*, and only after the
positions have landed. Their prior values are in the same snapshot, saved on the same line, before
the first write of any kind reaches the wire — a wrong `due` comes back out of that file, but a
clobbered note field exists nowhere else at all.

Preflight refuses rather than repairs
-------------------------------------
Four gates, all of which must pass before a single card moves: Anki is up and grants access; this
AnkiConnect actually exposes `setSpecificValueOfCard` and `multi`; every deck in scope inserts new
cards **sequentially** (`new.order != 0`); and the list this run follows exists — which since WP-M
is either `priority_learning_list.csv` or `progressive_learning_list.csv`, and the message names the
one the user actually chose rather than the other. The deck-options gate is the
one worth spelling out — with `new.order == 0` Anki gathers new cards in random order and card
positions are simply ignored, so the whole run would be a silent, syncing no-op. This module tells
the user and stops. It does **not** call `saveDeckConfig`: deck options are the user's, changing them
behind a reorder button would be exactly the kind of surprise §15 #5 forbids.

And one thing it deliberately only *warns* about: a `master_manifest.json` newer than the priority
list means the library has changed since the last analysis, so the order about to be written is
slightly out of date. That is worth saying and not worth blocking — and, per spec §15 #5, it must
not offer to re-run the journey. A reposition takes seconds; an analysis takes minutes, and
hijacking one into the other is the surprise Reels was criticised for.

Order and markers (WP-M / WP-N)
-------------------------------
`junban_order` picks which of Surasura's two orderings to follow — `"content"` (the default: the
order the words will actually be met in) or `"priority"` (raw leverage). `junban_only_markers`
narrows the run to words carrying ✦ / ⚖ / 📖, and does it by narrowing the RANK INDEX rather than by
inventing a placement: a word the filter excludes is simply unmatched, which already means "keeps
its existing relative order, at the back". Nothing is stranded, no card goes unpositioned, and the
contiguous block from `min(due)` is untouched. The markers themselves are computed here at run time
from `logic.priority_markers`, never read out of a CSV column — they are a render-time setting, and
storing them would turn a threshold change into a full re-analysis.

Scope
-----
`junban_scope` is `"deck"` (the nominated `junban_deck`) or `"all"` (every deck that actually holds
unsuspended new cards — `deck_names_with_new` has already dropped the empty and the entirely
suspended). Subdecks are included, because plain `deck:"X"` is Anki's own search semantics and what
the user expects (§15 #4) — which also means a parent and its child can both appear in an "all" run
and return the same card twice, so card ids are de-duplicated on the way in.

Nothing here imports tkinter. The panel (WP-H) calls these four functions and renders what they
return; keeping the decision to write on this side of that line is what lets it be tested against a
mocked wire with no collection in the room.
"""

import os
import threading
import time

from app import anki_connect
from app.anki_match import _KANA_ONLY_RE      # card_key's own test for a word written in kana alone
from modules.junban import ankiconnect, first_touch, match, pairs, show_tags, spaced, touchup, undo, unlisted
from modules.junban.ankiconnect import AnkiError
from modules.junban.plan import TRY_CARDS, plan, try_front as plan_try_front
from modules.junban.undo import RestoreRefused

PRIORITY_CSV_NAME = "priority_learning_list.csv"
PROGRESSIVE_CSV_NAME = "progressive_learning_list.csv"
LIBRARY_MAP_NAME = "library_frequency.json"
PHRASE_CACHE_NAME = "phrase_places.json"
MANIFEST_NAME = "master_manifest.json"

DEFAULT_CHUNK = 150

# WP-M. Two genuinely different orders over the same library, and the default is the one the report
# itself opens on: `content` follows `progressive_learning_list.csv` — file order (the manifest's
# study order), then within-file score — so the front of the queue is whatever the user is about to
# watch or read. `priority` follows `priority_learning_list.csv` — raw leverage, which maximises
# payoff per word learned but can leave rank 0 unmet for months.
DEFAULT_ORDER = "content"
ORDERS = ("content", "priority")

# Each order's file, and the name to call it by when it is missing. A user who chose "as I'll meet
# it" and has no progressive list needs to be told which file, not told about the other one.
ORDER_FILES = {
    "content": (PROGRESSIVE_CSV_NAME, "content-order list (progressive_learning_list.csv)"),
    "priority": (PRIORITY_CSV_NAME, "priority learning list"),
}

# Where the cards the list does not have go (`junban_unlisted`, Junban_Backlog_Spec §11 / §12.2):
#   "list_first" — the default, the panel's "List first": the list's words come first, because
#       they are the ones frequent enough to learn now — and among them, each with its episode's
#       words, the phrases the library meets as often as the list's words (a phrase is two words to
#       the list, so it can never be on it); then every rarer card by its own sentence (i+1 first);
#       known words last.
#   "journey" — "List first" off: a word the list cut off is placed where the journey meets it,
#       among the list's own words (§11.1 as first built).
#   "back" — v1: every card the list does not have keeps its existing order behind the list's.
# Anything else is refused in preflight rather than quietly treated as one of them — a setting that
# silently does something other than what it says is worse than one that is missing. A new key, not
# v1's `junban_unmatched`: every existing settings.json holds that one's old default.
DEFAULT_UNLISTED = "list_first"
SUPPORTED_UNLISTED = ("list_first", "journey", "back")

# The "why" of a card placed as a list word because the user said it is one (§16): the same words
# in the preview after a tick and in the run that reads the recorded answer.
MATCHED_BY_YOU = " · you matched it"
# Sonic (2026-10-23, M-W2-1): an empty list — every file watched or Finished, nothing that counts — puts nothing away.
# Every card would be "not on your list"; the run puts none away and says so (`_plan_scope`). A pinned item's parked
# card still comes back (*Study its cards first*), and a Put back still puts back: neither puts a card away.
EMPTY_LIST = "Your list is empty: no card is put away"
# M-W2-1 (review #2): a list that can't be read is no empty list — the run refuses, so the window's re-order tries again
LIST_UNREADABLE = "Surasura couldn't read your list. Press Generate, then reorder again."

STALE_WARNING = ("Your library has changed since the last analysis, so this order is a little out of "
                 "date. Reordering will still work — re-run Generate in Surasura when you want the "
                 "list caught up.")


# --------------------------------------------------------------------------- #
# Settings, read defensively
# --------------------------------------------------------------------------- #
def _language(settings):
    """The target language, which is what decides *whose* User Files the snapshot lives in."""
    return str((settings or {}).get("target_language") or "ja")


def _script(settings):
    """The Chinese script the list is spelled in (`zh_script`, app/zh_script.py) — "asis" for
    Japanese and for anyone who never chose one."""
    from app.zh_script import effective
    return effective(_language(settings), (settings or {}).get("zh_script"))


def _url(settings):
    return anki_connect.address(settings)


def _chunk_size(settings):
    """`junban_chunk_size`, clamped. A garbage value must not become a 5,000-action `multi`.

    AnkiConnect runs on Anki's Qt GUI thread with a 25 ms poll, so an oversized batch freezes the
    app with no progress bar and no cancel — and leaves no partial-progress checkpoint if it dies.
    """
    try:
        size = int((settings or {}).get("junban_chunk_size", DEFAULT_CHUNK))
    except (TypeError, ValueError):
        return DEFAULT_CHUNK
    return max(1, min(size, 1000))


def _word_fields(settings):
    """A **copy** of the per-note-type override map.

    `settings_manager._optional_module_defaults()` merges module defaults with a shallow
    `dict.update()`, so the `{}` sitting in loaded settings *is the very object* inside
    `SETTINGS_DEFAULTS` (spec §13 #12). Copying on the way in means nothing downstream can poison
    the process-wide default by accident.
    """
    overrides = (settings or {}).get("junban_word_fields")
    return dict(overrides) if isinstance(overrides, dict) else {}


def _unlisted(settings):
    return str((settings or {}).get("junban_unlisted") or DEFAULT_UNLISTED).strip().lower()


def _ready_first(settings):
    """`junban_ready_first`: the panel's "i+1 first" (§17). Off unless explicitly switched on."""
    return (settings or {}).get("junban_ready_first") is True


def _phrase_rows(settings, language):
    """Settings' "Idioms and set phrases on your list" (logic.phrase_rows, on by default), Japanese only: the list
    has rows for set phrases, so a phrase card is looked up as one (`match.card_key`'s phrase step) and a phrase that
    waits for a new word is no i+1 card (`_place_the_rest`)."""
    return language == "ja" and ((settings or {}).get("logic") or {}).get("phrase_rows", True) is not False


def _phrases(settings):
    """`junban_phrases`: whether a phrase card the library meets often enough is placed as the list's
    words are (the panel's "Phrases"). On unless explicitly switched off."""
    return (settings or {}).get("junban_phrases", True) is not False


def _order(settings):
    """`junban_order`, lowercased and trimmed — **not** validated. Preflight owns that.

    An unrecognised value reaches preflight as a problem rather than being quietly repaired here,
    for the same reason an unrecognised scope does: silently picking an order on the strength of a
    typo writes a real reordering the user never asked for.
    """
    return str((settings or {}).get("junban_order") or DEFAULT_ORDER).strip().lower()


def _only_markers(settings):
    """`junban_only_markers` as a tuple of known marker names. A **copy**, never the settings list.

    Like `junban_word_fields`, this container is the very object inside `SETTINGS_DEFAULTS` once
    `settings_manager` has shallow-merged the module defaults (spec §13 #12), so nothing downstream
    may hold or edit it.
    """
    return match.normalize_markers((settings or {}).get("junban_only_markers"))


def _tiers(settings):
    """Whether the run places cards by tiers — the cards not on the list "After it" or "Mixed in" (never "At the back"),
    and no *Only words marked* pick (a marker filter keeps its promise: only the chosen words move)."""
    return _unlisted(settings) in ("list_first", "journey") and not _only_markers(settings)


def first_applies(settings, language):
    """Whether the "First" switches — `junban_phrases` and `junban_ready_first` — take part in a run for `settings`
    and `language`: Japanese only, and only where the run places by tiers (`_tiers`). The one rule: the run asks it,
    and so does the Settings page before it shows the two switches (Q31). Pure: no Anki, no file."""
    return language == "ja" and _tiers(settings)


def _excluded(settings):
    """`junban_exclude_cards` — the card ids the user deselected in the preview (WP-O).

    A **run-time** key and nothing else: the panel puts it into the dict it hands the engine and it
    is deliberately absent from `SETTINGS_DEFAULTS`, so it never reaches `settings.json`. A
    remembered exclusion is a trap — the user would come back tomorrow to a run quietly leaving
    cards out for a reason that is no longer on screen.

    Only genuine ints are honoured, for the same reason the planner insists on them: `True` is an
    `int` in Python, and a stray one here would silently drop card id 1 from the run.
    """
    raw = (settings or {}).get("junban_exclude_cards") or ()
    if isinstance(raw, (str, bytes, dict)):
        return set()
    try:
        return {cid for cid in raw if isinstance(cid, int) and not isinstance(cid, bool)}
    except TypeError:
        return set()


def _thresholds(settings):
    """The ✦ / ⚖ thresholds from `logic.priority_markers` — a render-time setting, read at run time.

    Never hardcoded: the report recomputes these marks in the browser from the same block, so the
    preview and the report agree the moment a threshold moves, with no re-analysis (spec WP-N).
    """
    return match.marker_thresholds(settings)


def priority_csv_path():
    """`results/priority_learning_list.csv` — the leverage-first order.

    Imported inside the function on purpose: the tests redirect `app.path_utils` with an autouse
    fixture, and a name bound at module import time is not reached by that patch
    (`testing.md` §5.2).
    """
    from app.path_utils import get_user_file
    return get_user_file(os.path.join("results", PRIORITY_CSV_NAME))


def progressive_csv_path():
    """`results/progressive_learning_list.csv` — the order the words will actually be met in."""
    from app.path_utils import get_user_file
    return get_user_file(os.path.join("results", PROGRESSIVE_CSV_NAME))


def order_csv_path(settings):
    """Which of the two lists this run follows (WP-M).

    An unrecognised `junban_order` resolves to the default rather than to nothing, so `dry_run`
    still has a file to read — but preflight has already refused the run by then, so no write can
    reach the collection on the back of a typo.
    """
    return priority_csv_path() if _order(settings) == "priority" else progressive_csv_path()


def library_map_path():
    """`results/library_frequency.json` — every word in the library, below the list's cut-off
    included, with the journey's own numbers (every run writes it since ENGINE_REVISION 11)."""
    from app.path_utils import get_user_file
    return get_user_file(os.path.join("results", LIBRARY_MAP_NAME))


def phrase_cache_path():
    """`results/phrase_places.json` — where the phrase cards were met in the library (L9), kept
    against the library map it was read with (`anki_match.phrase_places`)."""
    from app.path_utils import get_user_file
    return get_user_file(os.path.join("results", PHRASE_CACHE_NAME))


def journey_sort(order, numbers, rank=None):
    """Where the journey puts a word, as one sortable key — the user's D7: the cards Surasura can
    place are ordered "identical to the journey they would experience" (Junban_Backlog_Spec §11.1).

    `numbers` is `(file, score, total)`; `rank` is the word's row on the list, or None for a
    library word below its cut-off. "content" orders as the progressive list does — the file in
    study order the word is first met in, then Score, then occurrences, both highest first — so a
    library word lands between the listed words of its file; a listed word keeps its row as the
    last tiebreak. "priority" orders by Score, as the priority list does, a listed word first on a
    tie.
    """
    first_file, score, total = numbers or (0, 0, 0)
    listed = 0 if rank is not None else 1
    if order == "priority":
        return (-score, listed, rank if rank is not None else first_file, -total)
    return (first_file, -score, -total, listed, rank if rank is not None else 0)


def _file_names(language):
    """The library's files in study order, by the short names the sentence dictionary uses (release
    tags, ids and quality tags trimmed) — for the "why" column. [] when the library cannot be read."""
    try:
        from app import analyzer
        from app.sentence_corpus import short_name
        return [short_name(os.path.splitext(os.path.basename(path))[0])
                for path, _label, _weight, _type in analyzer.resolve_found_files(language, verbose=False)]
    except Exception:
        return []


def _where(numbers, names):
    """"8× · Honzuki no Gekokujou S4 - 21": how often the library says it, and the file in study
    order it is first met in — the two things that placed it. ("library" alone said nothing: in a
    large library nearly every word is somewhere — the user, 2026-09-23.)"""
    first_file, _score, total = numbers
    name = names[first_file - 1] if 1 <= first_file <= len(names) else f"file {first_file:,}"
    return f"{total:,}× · {name}"


def _freqsort(fields):
    """The card's `FreqSort` (JPDB's rank, which anki_miner writes on most cards) as an int, or None."""
    text = str((fields or {}).get("FreqSort") or "").strip()
    return int(text) if text.isdigit() and int(text) > 0 else None


def _tokenizer(language):
    """The analyzer's tokenizer for a Japanese plan — SANITIZE_JA on first, as every run sets it — or
    None: Chinese, or no fugashi (I4: the ladder then goes without L6–L8)."""
    if language != "ja":
        return None
    try:
        from app import analyzer
        analyzer.SANITIZE_JA = True
        return analyzer.JapaneseTokenizer().tokenize
    except Exception:
        return None


def _card_reader(language, script):
    """The analyzer's Chinese tokenizer, in the list's script, to read a Chinese card's word alone for `card_key`
    (认真地 is 认真) — never its sentence: Chinese cards the list doesn't hold still go by FreqSort (D8). None for
    Japanese (`_tokenizer` reads its cards) or without jieba: the exact keys and the user's answers then, as before."""
    if language != "zh":
        return None
    try:
        from app import analyzer
        return analyzer.ChineseTokenizer(script=script).tokenize
    except Exception:
        return None


def _card_verb(language):
    """The test a Chinese card's 了 / 过 / 着 ending comes off by (analyzer.chinese_verb, jieba's own tags, read only
    when a card asks), or None for Japanese."""
    if language != "zh":
        return None
    try:
        from app import analyzer
        return analyzer.chinese_verb
    except Exception:
        return None


_FILE_MEMO = {}
_PARKED_READ = {}       # M-W1: (language, decks) -> the list file's key at its last parked-cards read (Connect off)


def _parked_read_key(settings, decks, tag, pinned):
    """M-W1: `((language, decks), (the list file, its mtime, size, the later tag, the pins))` — the list the job ranks
    by, as the last Generate wrote it, and what is pinned (`pins.read`'s `(item, pinned_at)`s) — or None when the list
    can't be read (then every job looks)."""
    path = order_csv_path(settings)
    try:
        st = os.stat(path)
    except OSError:
        return None
    pins = tuple((item_id, at) for item_id, _path, at in (pinned or ((),))[0])
    return (_language(settings), tuple(sorted(decks))), (path, st.st_mtime_ns, st.st_size, tag, pins)


def _memo_file(name, path, load, language=None):
    """`load()`'s answer for `path` as it stands, read again only when the file changes (its size and mtime): the
    fast re-plan's jobs read the last Generate's library map once per Generate, not once per move. Callers never
    change what they're handed."""
    try:
        st = os.stat(path)
        key = (path, st.st_mtime_ns, st.st_size)
    except OSError:
        return load()
    name = (name, language)
    hit = _FILE_MEMO.get(name)
    if hit is not None and hit[0] == key:
        return hit[1]
    value = load()
    _FILE_MEMO[name] = (key, value)
    return value


_KNOWN_MEMO = {}


def _known_memo(language, settings):
    """A fast re-plan job's known words (E3.1): `(_known_sets(...), {word: known?})`, read again only when one of
    the files they come from changes (KnownWord.json — its parse held the window's thread ~200 ms at every move —
    and the three word lists), the Chinese script does, or what else they read does (review 3 R5): the token store's
    known-words key (the names, phrases and pronouns switches, the library's name tables) and the key it holds, and
    the library's names while Ignore names is on."""
    from app.path_utils import get_user_files_path
    user_files = get_user_files_path(language)
    key = [_script(settings)]
    for name in ("KnownWord.json", "IgnoreList.txt", "Blacklist.txt", "GraduatedList.txt"):
        try:
            st = os.stat(os.path.join(user_files, name))
            key.append((name, st.st_mtime_ns, st.st_size))
        except OSError:
            key.append((name, None))
    key.append(_known_inputs(language, settings, os.path.join(user_files, "KnownWord.json")))
    key = tuple(key)
    hit = _KNOWN_MEMO.get(language)
    if hit is None or hit[0] != key:
        hit = _KNOWN_MEMO[language] = (key, _known_sets(language, settings), {})
    return hit[1], hit[2]


def _known_inputs(language, settings, known_file):
    """`_known_sets`' inputs that aren't files: the known-words key the token store would ask for now and the one it
    holds (`Store._known_key`: the switches and the name tables), and the library's names Ignore names adds."""
    from app import token_index
    try:
        store = token_index.open_store(language)
        try:
            known = (store._known_key(token_index.known_signature(known_file, _script(settings))),
                     store.get_meta("known_sig"))
        finally:
            store.close()
    except Exception:
        known = None
    try:
        names = tuple(token_index.ignored_names(language))
    except Exception:
        names = None
    return known, names


def _library_counts(language):
    """What the last Generate counted — (uses per word, the list's cut-off) from the library map — for the list's
    own learning rule (`_learning`); None for Chinese, before the first Generate, or when it can't be read."""
    if language != "ja":
        return None
    try:
        from app import analyzer
        counts, floor = analyzer.library_counts(library_map_path(), language)
    except Exception:
        return None
    return (counts, floor) if counts is not None else None


def _learning(language, sets, library=None, tagger=None, singles=True):
    """How 順 reads a card's sentence — the list's own learning rule (analyzer.LearningView), so "i+1" here is
    "i+1" in the report: a word is still to learn when it has Japanese, is a word the list can offer (a one-character
    word only a one-kanji dictionary word, with Settings' "List one-kanji words only when they're dictionary words" on
    — `singles`; where it stands as a piece of something else, `_skip` leaves it out), and is neither known nor
    ignored nor read already — through its known word (利用者 with 利用 known) or as a compound none of whose parts is
    an unknown (上層部). A compound too rare for the list (`library`: what the last Generate counted) is its parts
    when all of them are free: a 自動車学校 sentence waits for 自動車. `sets` = (known_tuples, known_lemmas, ignore);
    `tagger` is reused when given.
    -> (unknown(lemma, reading, surface), units(token), view) — tokens as the analyzer yields them,
    (lemma, reading, surface, ...)."""
    from app import analyzer
    known_tuples, known_lemmas, ignore = sets
    japanese = language == "ja"
    rule = japanese and singles

    def known(key):
        return key[0] in ignore or key[0] in known_lemmas or key in known_tuples
    view = analyzer.LearningView(*(library or (None, 0)), known=known, tagger=tagger,
                                 parts=None if japanese else {}, joins=None if japanese else {})

    has, parts, joins = analyzer.has_target_language, view.parts, view.joins

    def unknown(lemma, reading, surface):
        if not (has(lemma, language) or has(surface, language)):
            return False                # a number, markup, Latin — never a word (as a run)
        if rule and analyzer.single_kind((lemma, reading)) == 1:
            return False                # a one-character word the list never offers, as the analyzer reads it
        key = (lemma, reading)
        if lemma in ignore or lemma in known_lemmas or key in known_tuples:
            return False
        # read already: only a word with a suffix or a compound can be (most words are neither)
        return not ((lemma in joins or key in parts) and view.readable(key))

    def units(token):
        key = (token[0], token[1])
        found = view.units(key)
        return (token,) if found == (key,) else tuple((lemma, reading, lemma, lemma) for lemma, reading in found)
    return unknown, units, view


def _skip(language, singles=True):
    """`skip(text, tokens)` -> the tokens of a card's sentence the list can't offer there (analyzer.unoffered: a
    one-character word it never lists, or a one-kanji word standing as a piece of something else — 年 in 三年) — or
    None: Chinese, or Settings' "List one-kanji words only when they're dictionary words" off."""
    if language != "ja" or not singles:
        return None
    from app import analyzer
    return analyzer.unoffered


def _singles(settings):
    """Settings -> "List one-kanji words only when they're dictionary words" (exclude_single, on by default)."""
    return bool((settings or {}).get("exclude_single", True))


def _place_the_rest(cards, notes, language, settings, rank_of=None, answers=None, tokenize=None, library=None,
                    forms=False, lean=False, known_memo=None):
    """Junban_Backlog_Spec §5.4 / §5.5 for every card the list, the library and the phrase lookup left
    unplaced — and, before that, for every card whose word the learner already KNOWS, which goes last
    (D3) whatever else matched it: a known phrase is still known.

    The rest are read against their own sentence: none of its other words unknown makes the card
    **i+1** (the one new thing is the card); otherwise **multi**, fewest unknowns first; no sentence
    to read, or no tokenizer, **rest**. Each by the card's FreqSort, then as it was (D4). Chinese keeps
    exact keys only in v1 (D8): its cards go by FreqSort. Sets `tier`, `sort` and `why` on each card.

    §16, with `rank_of`: a card placed by its sentence whose word may be a list word spelled another
    way gets `check` — the suggestion (`match.suggest`), the user's earlier answer for it, and the
    line of its sentence to judge it by. So does a card placed by an earlier "yes" (`matched`), so the
    answer can be seen and changed. Nothing here places a card by a suggestion.

    A sentence is read as the list reads it (`_learning`; `library`: what the last Generate counted).

    `forms` (Connect's preview, K56): a sentence with no bold mark that doesn't hold the card's word as written is
    read with the word found by its forms (`connect.find_unbolded`); two words that could each be it, never guessed.
    `lean` (an automatic job, E3.1): no fallback for a card placed with the list and no §16 suggestion — both are the
    順 window's, for a card the user takes off the list or answers; every card's place is the same. `known_memo`
    (`_known_memo`, a job's): the known sets as last read, and each word's "known?" answer, kept while their files
    are unchanged.
    """
    from app import analyzer
    from modules.junban import connect
    # BEFORE the known words are read, as every run sets it (analyzer.py:1304, indexer.py:65). The
    # dashboard process never runs the analyzer, so its default (False) read KnownWord.json with
    # UniDic's raw lemmas (パーティー-party) while the sentences below were read clean — and the first
    # preview placed a card differently from the Reorder that followed it.
    analyzer.SANITIZE_JA = language == "ja"
    if known_memo is not None:
        (known_tuples, known_lemmas, ignore), answered = known_memo
    else:
        (known_tuples, known_lemmas, ignore), answered = _known_sets(language, settings), None
    japanese = language == "ja"
    if japanese and tokenize is None:
        tokenize = analyzer.JapaneseTokenizer().tokenize
    if forms and japanese and tokenize:
        connect.find_unbolded(cards, notes, tokenize, language)

    def known(lemma, reading):
        return lemma in ignore or lemma in known_lemmas or (lemma, reading) in known_tuples

    # The tokenizer's own tagger reads a word through its known word, when `tokenize` is a tokenizer's.
    word_unknown, units, _view = _learning(language, (known_tuples, known_lemmas, ignore), library,
                                           getattr(getattr(tokenize, "__self__", None), "tagger", None),
                                           _singles(settings))
    skip = _skip(language, _singles(settings))

    def unknown(token):
        return word_unknown(token[0], token[1], token[2])

    # A set phrase that waits for a word the learner doesn't know yet (本題に入る while 本題 is new) is two new
    # things in its sentence, never an i+1 card: its waiting words count beside it (the list's own rule,
    # app/phrases.py — with "Idioms and set phrases on your list" on).
    phrase_set = None
    if japanese and tokenize and _phrase_rows(settings, language):
        try:
            from app import phrases as phrase_rules
            phrase_set = phrase_rules.load()
        except Exception:
            phrase_set = None

    def waiting(word):
        if phrase_set is None:
            return 0
        index = phrase_set.of_word("".join(token[0] for token in tokenize(word)))
        if index is None:
            return 0
        return len(phrase_rules.waiting(phrase_set.entry(index),
                                        lambda key: not word_unknown(key[0], key[1], key[0]),
                                        lambda key: analyzer.single_kind(key, _singles(settings)) != 1)[0])

    def by_sentence(card):
        """`(tier, sort, why)` from the card's own sentence: i+1, then fewest unknowns, then the rest."""
        word = card.get("word") or ""
        note = (notes or {}).get(card.get("note")) or {}
        fields = note.get("fields") or {}
        rank = _freqsort(fields)
        by_freq = rank if rank is not None else float("inf")
        unknowns = (match.unknowns_beside(word, connect.sentence_of(note), tokenize, unknown, units, skip)
                    if tokenize and word else None)
        if unknowns is None and note.get("unsure"):
            return "rest", (by_freq,), connect.UNSURE
        if unknowns is not None:
            unknowns += waiting(word)
        if unknowns == 0:
            return "i+1", (by_freq,), "i+1"
        if unknowns:
            return "multi", (unknowns, by_freq), f"{unknowns} unknown"
        return "rest", (by_freq,), f"FreqSort {rank:,}" if rank is not None else "no sentence"

    def check(card):
        """§16: what "Same word as one on your list?" shows for this card, or None."""
        word = card.get("word") or ""
        sentence = connect.sentence_of((notes or {}).get(card.get("note")))
        found = match.suggest(word, sentence, tokenize, rank_of, language)
        answer = (answers or {}).get(word) or {}
        if card.get("matched"):             # placed by an earlier "yes": shown as answered
            if found is None or found.key != answer.get("target"):
                found = match.Suggestion(answer.get("target"), answer.get("via") or "", "", "")
            state = "yes"
        elif found is None:
            return None
        else:
            state = "no" if answer.get("answer") == "no" and answer.get("target") == found.key else None
        return {"found": found, "answer": state,
                "excerpt": match.sentence_excerpt(sentence, word, tokenize=tokenize)}

    suggesting = japanese and bool(tokenize) and bool(rank_of)
    for card in cards:
        # Known first, for EVERY card (D3): a list key does not make a known word new again. When only
        # the cards the list missed were tested, a card for any of 93 known words that are list keys
        # too (65 kana-only; measured 2026-09-26) took a list slot — だいぶ on the loanword ダイブ's row,
        # 好き in 好く's Forms, ぐっと on a グッ row misread from ぐっちゃぐっちゃ. It leaves the list with
        # its key, so nothing later ("i+1 first", the touch-ups) places it there.
        word = card.get("word") or ""
        if answered is None:
            is_known = is_known_word(word, known, known_lemmas, ignore, tokenize, known_tuples)
        else:
            is_known = answered.get(word)
            if is_known is None:
                is_known = answered[word] = is_known_word(word, known, known_lemmas, ignore, tokenize, known_tuples)
        if is_known:
            card.update(tier="known", sort=(), why="known", key="")
            continue
        # Placed WITH the list — its own words, the phrases held to its bar, journey-placed library
        # words — each also gets the place its sentence would give it, its `fallback`: where it goes
        # if the user takes it off the list in the preview (§13, the user 2026-09-23).
        with_list = bool(card.get("key")) or card.get("tier") in ("library", "phrase")
        if with_list and lean:
            continue
        if with_list:
            card["fallback"] = by_sentence(card)
            if suggesting and card.get("matched"):
                card["check"] = check(card)
            continue
        card["tier"], card["sort"], card["why"] = by_sentence(card)
        if suggesting and not lean:
            card["check"] = check(card)


class _SentenceWords:
    """The words of a Japanese sentence as the analyzer reads them, plus what `tokenize` leaves out:
    where each sits — and the learner's known words, to say which are easy — for "i+1 first" (§17).
    Imported here, never at import time (spec I4)."""

    def __init__(self, language, settings, library=None):
        from app import analyzer
        from app.analyzer import _sanitize_term
        analyzer.SANITIZE_JA = True             # before the known words are read (see _place_the_rest)
        self._analyzer, self._sanitize, self.language = analyzer, _sanitize_term, language
        self.known_tuples, self.known_lemmas, self.ignore = _known_sets(language, settings)
        self._tagger = analyzer.JapaneseTokenizer().tagger
        # The list's own learning rule (`_learning`): read already, and a rare compound as its parts.
        self._unknown, _units, self.view = _learning(
            language, (self.known_tuples, self.known_lemmas, self.ignore), library, self._tagger, _singles(settings))
        # A one-kanji word standing as a piece of something else is no word of the sentence (analyzer.bound_uses).
        self._skip = _skip(language, _singles(settings))
        # Without what the last Generate counted no compound is too rare, so none is taken apart (an empty table).
        self._compounds = self.view.parts if library else {}

    def of(self, text):
        """`(lemma, reading, surface, orth, at)` per word — what the analyzer counts as one
        (`analyzer.word_lemma`: no punctuation, symbol or number; デルタ counts as デルタ), less the one-character
        words the list can't offer there (`_skip`). A name is a word like any other (the user, 2026-09-30: "you would
        still need to learn names"), unless Settings' Ignore names makes the library's names ignored words — the
        known sets then hold them."""
        at, words = 0, []
        for word in self._analyzer.join_affixes(self._tagger(text or "")):
            surface, feature = word.surface, word.feature
            found = text.find(surface, at) if surface else -1
            if found >= 0:
                at = found + len(surface)
            lemma = self._analyzer.word_lemma(word)
            if lemma is not None:
                words.append((self._sanitize(lemma), feature.lForm or feature.kana or "", surface, feature, found))
        skipped = (self._skip(text, words, spans=[(w[4], w[4] + len(w[2])) if w[4] >= 0 else None for w in words])
                   if self._skip is not None and words else ())
        for n, (lemma, reading, surface, feature, found) in enumerate(words):
            if n in skipped:
                continue
            key = (lemma, reading)
            if key in self._compounds:
                parts = self.view.units(key)
                if parts != (key,):
                    # A compound too rare for the list is the words it counts toward, where it stands.
                    for part_lemma, part_reading in parts:
                        yield part_lemma, part_reading, surface, part_lemma, found
                    continue
            yield key[0], key[1], surface, self._sanitize(feature.orthBase or surface), found

    def easy(self, lemma, reading, surface):
        """Nothing to learn here: not a word (markup, digits), a one-character word the list never offers,
        known or ignored, or read already (`_learning`)."""
        return not self._unknown(lemma, reading, surface)


def _ready_first_pass(cards, notes, rank_of, journey_of, order, language, settings, library=None):
    """The panel's "i+1 first" (Junban_Backlog_Spec §17, the user 2026-09-24): a card placed with the
    list whose OWN sentence holds a word from the list that comes AFTER it is not i+1 when it comes up.

      * When every such word has a new card of its own, and each of THOSE cards is i+1 right there —
        counting only the known words and what comes before the card in need, never that card itself
        (the loop: if 入れ替わり needs 従兄 and 従兄 needs 入れ替わり, neither moves) — they are brought
        forward to sit just before it: "bring the other word first AND THEN review the card right
        there".
      * Otherwise the card waits with the cards of more new words ("multi"), fewest first.

    One pass, in list order, and no chains: a card brought forward never brings anything itself, and
    only the cards brought forward change what counts as learned for the cards after them — a card
    that waits holds nobody back. A name counts like any other word, as the report counts it (the user,
    2026-09-30) — unless Ignore names makes the library's names ignored words. Words too rare for the list
    never count (waiting would never teach them), nor do one-character words the list can't offer there, or the
    user's own answers to "Same word as one on your list?" (so a tick previews as the run writes, I5). A sentence
    is read as the list reads it (`_learning`; `library`: what the last Generate counted).
    Returns `{"pulled", "held"}`; changes the cards' `sort`, `why`, `tier` in place.
    """
    words = _SentenceWords(language, settings, library)

    def place(key):
        return journey_sort(order, journey_of.get(key), rank_of[key])

    def span_of(card):
        from modules.junban import connect
        raw = connect.sentence_of((notes or {}).get(card.get("note")))
        found = match.sentence_span(raw, card.get("word") or "")
        if found is not None:
            return found
        text = match.normalize_word(raw) if isinstance(raw, str) else ""
        return text, -1, -1

    def blockers(card, key, before, learned):
        """The list words of the card's own sentence not learned by `before`, in sentence order."""
        text, start, end = span_of(card)
        out = []
        for lemma, reading, surface, orth, at in words.of(text):
            if 0 <= at < end and at + len(surface) > start:
                continue                                    # the card's own word
            if words.easy(lemma, reading, surface):
                continue
            other = match.lookup(orth, rank_of, language) or match.lookup(lemma, rank_of, language)
            if (not other or other in learned or (key and rank_of[other] == rank_of[key])
                    or place(other) < before):
                continue
            if other not in out:
                out.append(other)
        return out

    with_list = [card for card in cards if not card.get("matched") and card.get("sort") is not None
                 and (card.get("key") or card.get("tier") in ("phrase", "library"))]
    with_list.sort(key=lambda card: (card["sort"], card.get("due") or 0, card.get("card_id") or 0))
    card_of = {}
    for card in with_list:
        if card.get("key"):
            card_of.setdefault(card["key"], card)

    learned, moved, pulled, held = set(), set(), 0, 0
    for card in with_list:
        if card["card_id"] in moved:
            continue                                        # already brought forward: no chains
        before = card["sort"]
        needed = blockers(card, card.get("key"), before, learned)
        if not needed:
            continue
        bring = []
        for other in needed:
            other_card = card_of.get(other)
            if (other_card is None or other_card["card_id"] in moved
                    or blockers(other_card, other, before, learned)):
                bring = None
                break
            bring.append(other_card)
        if bring is None:
            freq = _freqsort(((notes or {}).get(card.get("note")) or {}).get("fields") or {})
            card.update(tier="multi", sort=(len(needed), freq if freq is not None else float("inf")),
                        why="waits for " + "、".join(needed) + " · " + (card.get("why") or ""),
                        fallback=None, held=True)
            held += 1
            continue
        for n, other_card in enumerate(bring):
            other_card.update(sort=tuple(before) + (0, n), pulled=True,
                              why="first, for " + card["word"] + " · " + (other_card.get("why") or ""))
            moved.add(other_card["card_id"])
            learned.add(other_card["key"])
            pulled += 1
        # The move first: a phrase's own reason is long, and the column cuts the end off.
        card.update(sort=tuple(before) + (1,), why="after " + "、".join(needed) + " · " + (card.get("why") or ""))
    return {"pulled": pulled, "held": held}


# The "not in your library" banner (§5.4, D9): a source with at least this many cards the library
# cannot place is named, with the fix. Kept quiet by design (the user's note): normally the mined
# episodes ARE in the library, so it should rarely have anything to say.
BANNER_MIN = 10


def is_known_word(word, known, known_lemmas, ignore, tokenize, known_tuples=None):
    """Is a card's word one the learner already knows — 順's "known" tier (Junban_Backlog_Spec §5.5)?

    The word itself on the known or ignore lists, or ONE word — an ending written onto it aside
    (`match.one_word`: 努力する is 努力, the user 2026-09-26: "I'd prefer them to be one word") — whose
    lemma and reading are known. `known(lemma, reading)` is the caller's own test; `tokenize` is None
    where there is no tokenizer (Chinese in v1). Shared with the Anki Backfill window, which skips
    exactly these cards.

    A word written in kana alone is known by its own letters, as `match.card_key` reads it
    (2026-09-27): read alone, kana is the tagger's guess — かに comes out か + に, かする か + する, うに
    うー + に, カミ the lemma 上. The letters ARE the word's reading, so the one word counts only as a word
    known WITH that reading — its `(lemma, reading)` among `known_tuples` — or as a lemma the ignore
    lists hold (they carry no reading, and the analyzer ignores it in every reading); never as a lemma
    known in another reading (上 known as うえ says nothing of a かみ card, 止める as とめる nothing of
    やめる), and never as a single kana (か, う: a particle or an ending — as the list card_key reads keeps
    one off it). あおぐ is still 仰ぐ known as あおぐ; ホッとする still ほっと + する.

    A word the dictionary keeps apart from the one it is read as is never known through it
    (`match.word_of_its_own`: 心する is no 心 + する, 揚げる no 上げる, ことに — 殊に — no 事 + に): only
    as itself."""
    if not word:
        return False
    if word in known_lemmas or word in ignore:
        return True
    if tokenize:
        tokens = list(tokenize(word))
        token = match.one_word(tokens)
        if token is None or match.word_of_its_own(word, tokens, token):
            return False
        if _KANA_ONLY_RE.match(word):
            return len(token[2]) > 1 and (token[0] in ignore or (token[0], token[1]) in (known_tuples or ()))
        return known(token[0], token[1])
    return False


def known_test(language, settings, tokenizer=None):
    """-> `is_known(word)` for a card's word, read the way `_place_the_rest` reads it. `tokenizer`
    reuses a `JapaneseTokenizer` the caller already holds (one fugashi tagger per window, not two)."""
    from app import analyzer
    analyzer.SANITIZE_JA = language == "ja"       # as every run sets it; see `_place_the_rest`
    known_tuples, known_lemmas, ignore = _known_sets(language, settings)
    tokenize = None
    if language == "ja":
        tokenize = (tokenizer or analyzer.JapaneseTokenizer()).tokenize

    def known(lemma, reading):
        return lemma in ignore or lemma in known_lemmas or (lemma, reading) in known_tuples
    if language == "zh":
        # The known words are keyed in the user's script: a Traditional card (學習) must meet a
        # Simplified list's 学习 (Patterns_Chinese_Spec.md §7, S7). Japanese is never converted.
        from app.zh_script import convert
        script = _script(settings)
        return lambda word: is_known_word(convert(word or "", script), known, known_lemmas, ignore, tokenize)
    return lambda word: is_known_word(word, known, known_lemmas, ignore, tokenize, known_tuples)


def _known_sets(language, settings):
    """`(known_tuples, known_lemmas, ignore)` — the analyzer's own sets, read the way Generate reads
    them: the token store's cached known words, else `load_known_words`, plus the ignore, black and
    graduated lists. Imported here, never at import time (spec I4)."""
    from app import analyzer, token_index
    from app.path_utils import get_user_files_path
    script = _script(settings)
    user_files = get_user_files_path(language)
    known_file = os.path.join(user_files, "KnownWord.json")
    cached = None
    try:
        store = token_index.open_store(language)
        try:
            cached = store.get_cached_known(token_index.known_signature(known_file, script))
        finally:
            store.close()
    except Exception:
        cached = None
    if cached is None:
        tok = (analyzer.ChineseTokenizer(script=script) if language == "zh"
               else analyzer.JapaneseTokenizer())
        cached = analyzer.load_known_words(known_file, tok)
    ignore = set()
    for name in ("IgnoreList.txt", "Blacklist.txt", "GraduatedList.txt"):
        ignore |= analyzer.load_simple_list(os.path.join(user_files, name), script, language)
    ignore |= analyzer.load_ignored_entries(user_files, script, language)    # KnownWord.json's IGNORED entries
    return cached[0], cached[1], ignore


def _banner(cards, notes, language):
    """`[{"source", "cards"}]` — sources with `BANNER_MIN` or more cards the library could not place, whose name
    matches no file of the library (§5.4). anki_miner writes the source into `MiscInfo` as "<source> @ hh:mm:ss"; a card
    without one says nothing. Whether a source is a file of the library is the one source-name rule
    (`source_names`: both of Anki Miner's forms, the old bare name and 3.5's `folder — name`, exact keys, never a
    substring; Mattias's note 13: a 3.5 source was compared whole to bare file names, so a show in the library was
    named as missing)."""
    from modules.junban import source_names
    counts, keys = {}, {}
    for card in cards:
        if card.get("tier") not in ("i+1", "multi", "rest"):
            continue
        fields = ((notes or {}).get(card.get("note")) or {}).get("fields") or {}
        misc = fields.get("MiscInfo")
        source = source_names.source_text(misc)
        if source and len(source) <= 200:
            counts[source] = counts.get(source, 0) + 1
            keys[source] = source_names.card_key(misc)
    wanted = {source: n for source, n in counts.items() if n >= BANNER_MIN}
    if not wanted:
        return []
    from app import analyzer
    from modules.junban import backlog_shows
    bare = any(source_names.only_counted(keys.get(source)) for source in wanted)     # (an `Audio — …` deck too)
    names = set()
    for path, _label, _weight, _type in analyzer.resolve_found_files(language, verbose=False):
        names |= source_names.names_of(path, bare=bare)
    try:                                    # the store's counted items too: their originals and paired videos (a
        names |= backlog_shows.counted_names(language, bare=bare) or set()     # hato copy's name never was the video's)
    except Exception:
        pass
    missing = [{"source": source, "cards": n} for source, n in wanted.items() if keys.get(source) not in names]
    return sorted(missing, key=lambda entry: -entry["cards"])


def manifest_path(language):
    """`User Files/<lang>/master_manifest.json` — the library's own record of what is in it."""
    from app.path_utils import get_user_files_path
    return os.path.join(get_user_files_path(language), MANIFEST_NAME)


def _made_by_connect(language):
    """{note id: the list's word Connect made its card for} (`connect.library.made_notes_of`; LOOP-F2) — {} without
    Connect's record. Read whole once a plan, never kept between plans (F-7, left, measured 2026-10-28: 59 ms at 20,000
    made words, 175 ms at 60,000, on the plan's worker — a kept copy would need its own "what changed" check)."""
    try:
        from app.connect import library
        return library.made_notes_of(language)
    except Exception:
        return {}


def _journey_pending(language, csv_path=None):
    """The store's "journey pending" (True / False), or None outside store mode — and None while the list
    itself is missing ("is the list missing at all?" is preflight's question, as below)."""
    try:
        from app import library_store
        from app.path_utils import get_data_path, get_user_files_path
        if not os.path.isfile(csv_path or priority_csv_path()):
            return None
        store = library_store.open_store(language, get_data_path(language), get_user_files_path(language),
                                         role="reader")
        if store is None:
            return None
        with store:
            return store.journey_pending()
    except Exception:
        return None


def list_is_stale(language, csv_path=None):
    """True when the library has changed since the list this run follows was written.

    A manifest newer than the CSV means an analysis has not caught up, which spec §13 #11 names as
    the likeliest cause of a disappointing result. Never fatal, and never actioned automatically —
    see the module docstring.

    `csv_path` names the list actually in use (WP-M): checking the priority list's timestamp while
    ordering by the progressive one would report the staleness of a file this run never opened.

    With a library store (2.5) the answer is the store's own: "journey pending", the order the last
    Generate read is older than the library's (`analysed_order_version < order_version`,
    Library_Store_Spec §7). A move and its reverse, or a Generate that already covered the change, are
    then not stale. Without one, the timestamps as before.
    """
    pending = _journey_pending(language, csv_path)
    if pending is not None:
        return pending
    try:
        csv_path = csv_path or priority_csv_path()
        manifest = manifest_path(language)
        if not os.path.isfile(csv_path) or not os.path.isfile(manifest):
            return False            # "is the list missing at all?" is preflight's question, not this one
        return os.path.getmtime(manifest) > os.path.getmtime(csv_path)
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# Scope
# --------------------------------------------------------------------------- #
def _scope_mode(settings):
    """"all" or "deck" — the scope MODE, which the undo snapshot records (see undo.restore_pairs)."""
    scope = str((settings or {}).get("junban_scope") or "deck").strip().lower()
    return "all" if scope == "all" else "deck"


def _resolve_decks(settings, url):
    """Which decks this run covers. Returns `(decks, problems)`; never raises.

    An unrecognised `junban_scope` is a problem rather than a fallback: defaulting an unknown value
    to "all" would reorder every deck the user owns on the strength of a typo.
    """
    scope = str((settings or {}).get("junban_scope") or "deck").strip().lower()

    if scope == "deck":
        deck = str((settings or {}).get("junban_deck") or "").strip()
        if not deck:
            return [], ["Choose a deck to reorder first — no deck is selected."]
        return [deck], []

    if scope == "all":
        try:
            decks = ankiconnect.deck_names_with_new(url)
        except AnkiError as e:
            return [], [str(e)]
        if not decks:
            return [], ["No deck has any unsuspended new cards, so there is nothing to reorder."]
        return decks, []

    return [], [f"Unknown scope {scope!r} — Junban reorders either one deck or all decks."]


# --------------------------------------------------------------------------- #
# Preflight
# --------------------------------------------------------------------------- #
# R1 (2026-10-23; Sonic: "When I reorder, that it faithfully reorders accordingly"): Anki's v3 scheduler serves new
# cards by two more of the deck's options than its insertion order, both in `getDeckConfig`'s top level (the installed
# Anki 26.9's own enums): the gather order (`newGatherPriority`: 0 Deck, 1 Ascending position, 2 Descending position,
# 3 Random notes, 4 Random cards, 5 Deck then random notes) and the sort order (`newSortOrder`: 0 Card type then order
# gathered, 1 Order gathered, 2 Card type then random, 3 Random note then card type, 4 Random). A key the reply lacks
# (an Anki before them) is no problem. Read only: Junban never changes the deck's options.
GATHER_WORDS = {2: "Descending position", 3: "Random notes", 4: "Random cards", 5: "Deck, then random notes"}
SORT_WORDS = {2: "Card type, then random", 3: "Random note, then card type", 4: "Random"}


def _serve_order(deck, config, names, siblings=lambda deck: False):
    """Does Anki serve `deck`'s new cards by their positions (R1)? -> (problems, warnings) in plain words. `names()`:
    Anki's deck names (for the subdecks; None when unread), asked only for a deck-by-deck gather — an Anki without
    the option is asked nothing more than before. `siblings(deck)`: does a new card in scope belong to a note of
    several cards? Asked only for the sort 'Card type, then order gathered' (drill A3, gap 1)."""
    problems, warnings = [], []
    gather, sort = config.get("newGatherPriority"), config.get("newSortOrder")
    if gather in GATHER_WORDS:
        how = ("serves the last position first, so the order would come out backwards" if gather == 2
               else "ignores card positions")
        problems.append(
            f"'{deck}' gathers new cards by '{GATHER_WORDS[gather]}', which {how}. Change that deck's options to "
            "'New card gather order: Deck' (or 'Ascending position') and try again — Junban will not change your "
            "deck options for you.")
    elif gather == 0 and any(str(n).startswith(f"{deck}::") for n in names() or ()):
        warnings.append(
            f"'{deck}' has subdecks and gathers new cards deck by deck, so Anki shows one subdeck's cards before "
            "the next one's whatever their order. To follow one order across them, set that deck's 'New card "
            "gather order' to 'Ascending position'.")
    if sort == 0 and siblings(deck):
        warnings.append(
            f"'{deck}' sorts new cards by 'Card type, then order gathered', and some of its notes have more than one "
            "card: Anki shows every note's first card before any second one, whatever their order. To keep each "
            "note's cards where Junban puts them, set that deck's 'New card sort order' to 'Order gathered'.")
    if sort in SORT_WORDS:
        problems.append(
            f"'{deck}' sorts new cards by '{SORT_WORDS[sort]}', which ignores card positions. Change that deck's "
            "options to 'New card sort order: Order gathered' (or 'Card type, then order gathered') and try again "
            "— Junban will not change your deck options for you.")
    return problems, warnings


def preflight(settings, probe=None):
    """Everything that must be true before a card moves. Returns a dict; never raises.

    `{"ok": bool, "problems": [str], "warnings": [str], "decks": [str], "probe": {...}}`

    `problems` block the run; `warnings` are shown and stepped over. The split is the whole point of
    this function: a stale word list makes the result *worse*, while a random new-card order makes
    the result *nothing at all*, and those two deserve different answers.

    `probe`: `probe(settings)`'s answer, asked a moment ago by the run's caller (the fast re-plan's job, E3.1-B2:
    it probes before reading the library) — not asked again.
    """
    problems, warnings = [], []
    per_day = {}                # each deck's New cards/day — the fast re-plan's "tomorrow" (D6)
    url = _url(settings)

    # 1. Liveness, permission, and the apiReflect capability gate in one call. `probe` never raises
    #    and reports the missing actions by name, so an AnkiConnect too old to do this says so here
    #    rather than at the moment of writing.
    report = probe if probe is not None else probe_anki(settings)
    if not report.get("ok"):
        problems.append(report.get("error") or f"Could not reach Anki at {url}. Is Anki running?")
        # Without a connection nothing below can be checked; the file checks still can, and are worth
        # reporting together so the user fixes everything in one go.
        decks = []
    else:
        decks, deck_problems = _resolve_decks(settings, url)
        problems.extend(deck_problems)

        # 3. Deck options. `new.order == 0` is random insertion order: positions are ignored, so the
        #    run would write, sync, and change nothing the user can see. R1: so do a random gather or sort
        #    order, and a descending gather reverses it (`_serve_order`).
        read = []

        def names():                            # Anki's deck names, read once, only when a check needs them
            if not read:
                try:
                    got = ankiconnect.invoke("deckNames", url)
                except AnkiError:
                    got = None
                read.append(got if isinstance(got, list) else None)
            return read[0]
        # A deck tree is said once, at its top (scope "all" lists a parent and its subdecks; a parent's search holds them)
        tops = [d for d in decks if not any(d.startswith(f"{p}::") for p in decks if p != d)]
        many = {}

        def siblings(deck):                     # a new card that is a note's second card or later: one request in all
            if deck not in tops:
                return False
            if not many:
                try:
                    replies = ankiconnect.multi([{"action": "findCards", "params": {
                        "query": ankiconnect.new_card_query(top) + " -card:1"}} for top in tops], url)
                except AnkiError:
                    replies = []
                for top, reply in zip(tops, list(replies) + [None] * len(tops)):
                    found = reply.get("result") if isinstance(reply, dict) and reply.get("error") is None else None
                    many[top] = bool(found) if isinstance(found, list) else False
            return many.get(deck, False)
        for deck in decks:
            try:
                config = ankiconnect.deck_config(url, deck)
            except AnkiError as e:
                warnings.append(f"Could not read the deck options for '{deck}' ({e}).")
                continue
            new = config.get("new") if isinstance(config, dict) else None
            order = new.get("order") if isinstance(new, dict) else None
            per_day[deck] = new.get("perDay") if isinstance(new, dict) else None
            if order == 0:
                problems.append(
                    f"'{deck}' inserts new cards in RANDOM order, so Anki ignores card positions "
                    "and reordering it would do nothing. Change that deck's options to "
                    "'Sequential' (Insertion order) and try again — Junban will not change your "
                    "deck options for you.")
            elif order is None:
                warnings.append(f"Could not read the new-card insertion order for '{deck}'.")
            if isinstance(config, dict):
                served = _serve_order(deck, config, names if deck in tops else (lambda: None), siblings)
                problems.extend(served[0])
                warnings.extend(served[1])

    # `junban_unlisted` decides where the cards the list does not have are placed. Checked here so
    # an unsupported value stops the run instead of being silently ignored.
    placement = _unlisted(settings)
    if placement not in SUPPORTED_UNLISTED:
        problems.append(
            f"Junban can put the cards your list doesn't have after it, among it by your journey, or "
            f"at the back of the queue — not {placement!r} (junban_unlisted).")

    # WP-M. An order this version does not know is refused rather than resolved: the two orders put
    # genuinely different words at the front of the queue, and guessing which one a typo meant would
    # write a reordering the user never chose.
    order = _order(settings)
    if order not in ORDERS:
        problems.append(
            f"Junban does not know the order {order!r}. Choose either the order you will meet the "
            "words in, or Surasura's priority order.")

    # WP-N. Same reasoning, and sharper: an unrecognised marker name silently narrows to nothing,
    # and a filter that matches nothing is indistinguishable from no filter at all — it would
    # reorder every card the user asked to leave alone.
    unknown = match.unknown_markers((settings or {}).get("junban_only_markers"))
    if unknown:
        problems.append(
            f"Junban does not know the marker{'' if len(unknown) == 1 else 's'} "
            f"{', '.join(unknown)}. Choose from: {', '.join(match.MARKERS)}.")

    # A tag with whitespace is SEVERAL tags to Anki ("Surasura order" -> "Surasura" and "order"),
    # and Restore would then take "order" off notes the user had tagged that way themselves.
    tag = touchup.options(settings).get("tag") or ""
    if any(ch.isspace() for ch in tag):
        problems.append(f"The tag {tag!r} contains a space, which Anki reads as separate tags. "
                        "Use a single word, such as Surasura or Surasura_order.")

    # 4. The list itself — whichever of the two this run follows.
    csv_path = order_csv_path(settings)
    _file_name, list_label = ORDER_FILES.get(order, ORDER_FILES[DEFAULT_ORDER])
    if not os.path.isfile(csv_path):
        problems.append(f"There is no {list_label} yet — run an analysis in Surasura "
                        "first, then come back.")
    elif list_is_stale(_language(settings), csv_path):
        # WARN ONLY here: spec §15 #5. With the dashboard behind it, the panel asks the Generate
        # button's own question instead and swaps this line for its "Generate & preview" (§16.9).
        warnings.append(STALE_WARNING)

    return {"ok": not problems, "problems": problems, "warnings": warnings,
            "decks": decks, "probe": report, "per_day": per_day}


def probe_anki(settings):
    """`preflight`'s own question to Anki — up, permitted, and the actions this run needs (`ankiconnect.probe`)."""
    return ankiconnect.probe(_url(settings), extra=unlisted.required_actions(unlisted.options(settings)))


# --------------------------------------------------------------------------- #
# Gathering
# --------------------------------------------------------------------------- #
def _field_names(note):
    """One note's field names in Anki's own order.

    Mirrors `match.target_word`'s ordering because it answers the neighbouring question — *which*
    field was chosen, for the panel to show — rather than what the field contains. Anki's field
    order is the `order` value, not the dict's insertion order: a JSON round-trip has no obligation
    to preserve the latter, and "field 0" means nothing if the wrong one is trusted.
    """
    fields = note.get("fields")
    if not isinstance(fields, dict):
        return []

    def _order(name):
        value = fields.get(name)
        if isinstance(value, dict) and isinstance(value.get("order"), int):
            return value["order"]
        return len(fields)

    return sorted(fields.keys(), key=lambda name: (_order(name), name))


def _scope_cards(url, decks, parked_tag=None):
    """Every unsuspended new card in scope, as `cardsInfo` rows. Raises `AnkiError`.

    `parked_tag` (Connect's preview, MR-R3): the cards Junban parked in scope too — suspended, carrying that tag
    (`connect.parked_query`) — each row marked `parked`.

    Card ids are de-duplicated: a parent deck's query includes its subdecks, so an "all decks" run
    genuinely returns the same card under two names. Writing it twice is harmless; counting it twice
    would make every number the confirmation states wrong.
    """
    card_ids, seen = [], set()
    for deck in decks:
        for card_id in ankiconnect.find_new_cards(url, ankiconnect.new_card_query(deck)):
            if card_id not in seen:
                seen.add(card_id)
                card_ids.append(card_id)
    parked = set()
    if parked_tag:
        from modules.junban import connect
        for deck in decks:
            for card_id in ankiconnect.find_cards(url, connect.parked_query(deck, parked_tag)):
                if card_id not in seen:
                    seen.add(card_id)
                    parked.add(card_id)
                    card_ids.append(card_id)
    if not card_ids:
        return []
    rows = ankiconnect.cards_info(url, card_ids)
    for row in rows if parked else ():
        if row.get("cardId") in parked:
            row["parked"] = True
    return rows


def _note_values(note):
    """`{field_name: value}` for one `notesInfo` note — the flat shape the touch-ups reason about."""
    fields = note.get("fields")
    if not isinstance(fields, dict):
        return {}
    values = {}
    for name, value in fields.items():
        if isinstance(value, dict):
            value = value.get("value")
        values[str(name)] = value if isinstance(value, str) else ""
    return values


def _parked_rows(url, decks, parked_tag, have):
    """M-W1: the cards Junban parked in scope (`connect.parked_query`) not in `have`, as `cardsInfo` rows marked
    `parked` — one `findCards` a deck, and a `cardsInfo` only when there are any."""
    from modules.junban import connect
    ids = []
    for deck in decks:
        for card_id in ankiconnect.find_cards(url, connect.parked_query(deck, parked_tag)):
            if card_id not in have and card_id not in ids:
                ids.append(card_id)
    rows = ankiconnect.cards_info(url, ids) if ids else []
    for row in rows:
        row["parked"] = True
    return rows


def _gather(url, decks, overrides, language=None, parked_tag=None, card_map=None, parked_map=False):
    """Read the scope out of Anki and join every card to its note's word.

    Returns `(cards, detail)` where `cards` is the planner's input shape and `detail` carries what
    the touch-ups and the panel need: the resolved word field per note type, every field NAME seen
    (so the panel's field pickers offer the user's real fields rather than a guess), the note id of
    each card, and each note's current fields and tags.

    The notes are kept rather than thrown away after the word is read because WP-L's writes are
    **read-modify-write** — a frequency `<li>` is appended to what is there, and a sentence is only
    offered if the note does not already hold it. Re-fetching them later would be a second read of
    the same 152 notes and a window in which they could change underneath the plan.

    Raises `AnkiError` — this is the half of the run that talks to Anki, and the caller decides
    whether a dead connection is a report or an exception.

    `card_map` (the fast re-plan's preview, 03 §3.2): a `CardMap` kept between jobs answers the reads,
    asking Anki only for what changed; the rows and notes it returns are joined below exactly as these.
    It reads the unsuspended new cards alone, so a run that also gathers the parked cards (`parked_tag`,
    Connect's preview) reads afresh, without it — unless `parked_map` (M-W1: the 3.0 host's job with Connect off): the
    map answers for the unsuspended cards and the parked ones are read beside it (`_parked_rows`).
    """
    empty = {"fields_by_model": {}, "field_names": [], "note_by_card": {}, "notes": {}}
    if parked_tag and not parked_map:
        card_map = None
    read_notes = None
    if card_map is not None:
        rows, read_notes = card_map.read(url, decks)
        extra = _parked_rows(url, decks, parked_tag, {row.get("cardId") for row in rows}) if parked_tag else []
        if extra:
            rows = list(rows) + extra
            if read_notes is not None:
                have = {note.get("noteId") for note in read_notes}
                more = sorted({row.get("note") for row in extra if isinstance(row.get("note"), int)} - have)
                read_notes = list(read_notes) + (ankiconnect.notes_info(url, more) if more else [])
    else:
        rows = _scope_cards(url, decks, parked_tag)
    if not rows:
        return [], empty

    note_ids, seen_notes = [], set()
    for row in rows:
        note_id = row.get("note")
        if isinstance(note_id, int) and note_id not in seen_notes:
            seen_notes.add(note_id)
            note_ids.append(note_id)

    words, fields_by_model, notes, field_names = {}, {}, {}, set()
    # A warm map keeps each note's join while the note is the very one it read (re-read: a new object) and
    # the overrides and language are the same: re-reading 5,000 notes' words was two thirds of a refresh.
    joined = card_map.joined if card_map is not None else None
    context = (repr(sorted(overrides.items())), language) if joined is not None else None
    for note in (read_notes if read_notes is not None else ankiconnect.notes_info(url, note_ids)):
        note_id = note.get("noteId")
        if not isinstance(note_id, int):
            continue
        hit = joined.get(note_id) if joined is not None else None
        if hit is not None and hit[0] is note and hit[1] == context:
            word, values, tags = hit[2]
        else:
            word = match.target_word(note, overrides, language)       # a Japanese card's ONE word
            values = _note_values(note)
            raw = note.get("tags")
            tags = [str(name) for name in raw] if isinstance(raw, list) else []
            if joined is not None:
                joined[note_id] = (note, context, (word, values, tags))
        words[note_id] = word
        model = note.get("modelName") or ""
        if model and model not in fields_by_model:
            fields_by_model[model] = match.resolve_word_field(model, _field_names(note), overrides)
        field_names.update(values)
        notes[note_id] = {"fields": dict(values), "tags": list(tags)}

    cards = [{"card_id": row.get("cardId"),
              "due": row.get("due"),
              "type": row.get("type"),
              "queue": row.get("queue"),
              "word": words.get(row.get("note"), ""),
              "note": row.get("note"),
              "deck": row.get("deckName"),
              "flags": row.get("flags"),
              **({"parked": True} if row.get("parked") else {})}
             for row in rows]
    detail = {"fields_by_model": fields_by_model,
              "field_names": sorted(field_names),
              "note_by_card": {row.get("cardId"): row.get("note") for row in rows},
              "notes": notes}
    return cards, detail


class CardMap:
    """A deck's new cards and their notes, kept between jobs in one process (E1.1 03 §3.2).

    The fast re-plan's preview re-orders Anki about once a second while you move content; reading every
    card and note each time (`cardsInfo` + `notesInfo` for thousands) would be most of the job. So the
    first `read` gathers as `_gather` always has, and later ones ask only what changed: `findCards` for
    the ids, then `cardsModTime` and `notesModTime` (one light request each, no fields), and `cardsInfo`
    / `notesInfo` for the new or modified ids alone. Notes are asked too because editing a note's word
    leaves its cards' mod time alone. A different profile or scope reads afresh (03 §3.1), and so does
    an AnkiConnect that refuses `notesModTime`. A mod time is whole seconds, so anything modified within
    a second of the last read is read again.

    Renaming a note type or a field in Anki moves no mod time at all, so every warm read also asks
    `modelFieldNames` for the note types in scope (one `multi`): a name or field list that changed reads
    afresh.

    The rows and notes it returns have `_scope_cards` / `notesInfo`'s shapes; `_gather` joins them.
    Not thread-safe: one job at a time, under the Anki-write lock, as every job runs.

    Every request costs a round trip (AnkiConnect answers on a 25 ms timer in Anki's window: 20–90 ms a request on
    DevTest, E3.1's drill), so a warm read asks in as few as it can (E3.1-B2): the profile, the ids and the note
    types' fields in one `multi`; both kinds of mod time in one (at most MOD_IDS ids a request, so a big deck never
    holds Anki's window long in one go); the changed cards and notes in one (at most INFO_IDS). A new card's note
    is read with its mod time (`notesInfo` carries it), never asked for separately.
    """

    MOD_IDS = 4000              # mod times a request at most (~0.1 s of Anki's own time per 1,000)
    INFO_IDS = 500              # cardsInfo / notesInfo ids a request at most (`cards_info`'s 250 each)

    def __init__(self):
        self.key = None             # (profile, address, scope) of the last read
        self.rows = {}              # card id -> its cardsInfo row (with "mod")
        self.notes = {}             # note id -> its notesInfo note
        self.note_mods = {}         # note id -> mod time
        self.read_at = 0            # the clock, in whole seconds, when the last read began
        self.fresh = 0              # reads that gathered everything (the first, a profile change, ...)
        self.reads = 0              # every read (a run knows whether the map it holds was read for it)
        self.models = {}            # note type -> its field names, as the last read saw them
        self.joined = {}            # note id -> (the note read, overrides + language, its join): `_gather`

    def read(self, url, decks):
        """`(rows, notes)` for the unsuspended new cards in `decks`, as `_gather` reads them. Raises
        `AnkiError` when Anki can't be read."""
        started = int(time.time())
        self.reads += 1
        profile, ids, models = self._look(url, decks, self.models)
        key = (profile, url, tuple(decks))
        if key != self.key or not self.rows or models != self.models:
            return self._fresh(key, url, ids, started)
        recent = self.read_at - 1
        known = self._note_ids([card_id for card_id in ids if card_id in self.rows])
        try:
            card_mods, note_mods = self._mod_times(url, ids, known)
        except AnkiError as e:
            if e.kind != "action":
                raise
            return self._fresh(key, url, ids, started)      # no cardsModTime / notesModTime here: read afresh
        changed = [card_id for card_id in ids
                   if card_id not in self.rows or card_mods.get(card_id) != self.rows[card_id].get("mod")
                   or (card_mods.get(card_id) or 0) >= recent]
        stale = [note_id for note_id in known
                 if note_id not in self.notes or note_mods.get(note_id) != self.note_mods.get(note_id)
                 or (note_mods.get(note_id) or 0) >= recent]
        replies = _reads(url, [("cardsInfo", "cards", changed), ("notesInfo", "notes", stale)], self.INFO_IDS)
        for row in replies["cardsInfo"]:
            self.rows[row.get("cardId")] = row
        for note in replies["notesInfo"]:
            self.notes[note.get("noteId")] = note
        wanted = set(ids)
        self.rows = {card_id: row for card_id, row in self.rows.items() if card_id in wanted}
        note_ids = self._note_ids(ids)
        checked = set(known)
        arrived_mods = self._notes_with_mods(url, [note_id for note_id in note_ids if note_id not in checked])
        if arrived_mods is None:
            return self._fresh(key, url, ids, started)      # a new card's note, and no notesModTime here
        note_mods.update(arrived_mods)
        self.note_mods = dict(note_mods)
        arrived = {note.get("modelName") for note in self.notes.values()} - set(self.models)
        arrived = {name for name in arrived if isinstance(name, str) and name}
        if arrived:                                 # a note type new to the map: watched from now on (review 3 #6)
            self.models.update(self._models(url, {name: () for name in arrived}))
        keep = set(note_ids)
        self.notes = {note_id: note for note_id, note in self.notes.items() if note_id in keep}
        self.note_mods = {note_id: mod for note_id, mod in self.note_mods.items() if note_id in keep}
        self.read_at = started
        return self._out(ids)

    def _fresh(self, key, url, ids, started):
        self.key, self.rows, self.notes, self.note_mods, self.joined = key, {}, {}, {}, {}
        self.fresh += 1
        for row in ankiconnect.cards_info(url, ids) if ids else []:
            self.rows[row.get("cardId")] = row
        mods = self._notes_with_mods(url, self._note_ids(ids))
        if mods is None:
            self.key = None             # no notesModTime: every read gathers afresh
        self.note_mods = mods or {}
        names = {note.get("modelName") for note in self.notes.values()}
        self.models = self._models(url, {name: () for name in names if isinstance(name, str) and name})
        self.read_at = started
        return self._out(ids)

    def _notes_with_mods(self, url, note_ids):
        """Read `note_ids` into the map -> `{note id: mod}`: from `notesInfo` itself (one read: the note and its mod
        time agree), or from `notesModTime` for an AnkiConnect whose `notesInfo` has none — None when that one
        refuses `notesModTime` too. Raises `AnkiError` otherwise."""
        mods = {}
        for note in ankiconnect.notes_info(url, note_ids) if note_ids else []:
            self.notes[note.get("noteId")] = note
            if isinstance(note.get("mod"), int) and not isinstance(note.get("mod"), bool):
                mods[note.get("noteId")] = note["mod"]
        missing = [note_id for note_id in note_ids if note_id not in mods]
        if missing:
            try:
                mods.update(ankiconnect.mod_times(url, "notesModTime", missing))
            except AnkiError as e:
                if e.kind != "action":
                    raise
                return None
        return mods

    @classmethod
    def _mod_times(cls, url, card_ids, note_ids):
        """`({card id: mod}, {note id: mod})`, both kinds in one request (`_reads`). Raises `AnkiError`."""
        replies = _reads(url, [("cardsModTime", "cards", card_ids), ("notesModTime", "notes", note_ids)],
                         cls.MOD_IDS)
        out = []
        for action, field in (("cardsModTime", "cardId"), ("notesModTime", "noteId")):
            out.append({entry[field]: entry["mod"] for entry in replies[action]
                        if isinstance(entry.get(field), int) and isinstance(entry.get("mod"), int)})
        return out[0], out[1]

    @staticmethod
    def _look(url, decks, models):
        """One request: the open profile, the scope's card ids (de-duplicated across decks — `_scope_cards`' own
        first half) and the field names of the note types in `models` (`_models`; None for a name Anki no longer
        has). Raises `AnkiError`."""
        names = sorted(models)
        actions = ([{"action": "getActiveProfile"}]
                   + [{"action": "findCards", "params": {"query": ankiconnect.new_card_query(deck)}} for deck in decks]
                   + [{"action": "modelFieldNames", "params": {"modelName": name}} for name in names])
        replies = ankiconnect.multi(actions, url)
        if len(replies) != len(actions):
            raise AnkiError("'multi' did not answer every action.", kind="protocol")
        profile = first_touch.profile_name(_answer(replies[0], "getActiveProfile"))     # C22: "" names none
        card_ids, seen = [], set()
        for reply in replies[1:1 + len(decks)]:
            found = _answer(reply, "findCards")
            for card_id in anki_connect._int_ids(found if isinstance(found, list) else []):
                if card_id not in seen:
                    seen.add(card_id)
                    card_ids.append(card_id)
        fields = {}
        for name, reply in zip(names, replies[1 + len(decks):]):
            result = reply.get("result") if isinstance(reply, dict) and reply.get("error") is None else None
            fields[name] = tuple(result) if isinstance(result, list) else None
        return profile, card_ids, fields

    @staticmethod
    def _models(url, models):
        """`{note type: (field names)}` for the note types named in `models`, in one request; a name Anki no
        longer has (renamed) reads as None."""
        names = sorted(models)
        if not names:
            return {}
        replies = ankiconnect.multi([{"action": "modelFieldNames", "params": {"modelName": name}}
                                     for name in names], url)
        out = {}
        for name, reply in zip(names, replies):
            result = reply.get("result") if isinstance(reply, dict) and reply.get("error") is None else None
            out[name] = tuple(result) if isinstance(result, list) else None
        return out

    def _note_ids(self, ids):
        out, seen = [], set()
        for card_id in ids:
            note_id = (self.rows.get(card_id) or {}).get("note")
            if isinstance(note_id, int) and note_id not in seen:
                seen.add(note_id)
                out.append(note_id)
        return out

    def _out(self, ids):
        rows = [dict(self.rows[card_id]) for card_id in ids if card_id in self.rows]
        notes = [self.notes[note_id] for note_id in self._note_ids(ids) if note_id in self.notes]
        return rows, notes


def _answer(reply, action):
    """One `multi` slot's result, or `AnkiError` as `invoke` raises it for that action alone."""
    if not isinstance(reply, dict) or "result" not in reply or "error" not in reply:
        raise AnkiError(f"Unexpected reply shape from '{action}' — is this really AnkiConnect?", kind="protocol")
    if reply["error"] is not None:
        raise anki_connect.refusal(action, reply["error"])
    return reply["result"]


def _reads(url, pieces, per_request):
    """Read actions over id lists in as few requests as `per_request` ids a request allows (E3.1-B2): `pieces` is
    `[(action, its ids parameter, ids)]` -> `{action: [the non-empty entries answered, in order]}`. An empty list asks
    nothing. Raises `AnkiError` (kind "action" when Anki refused one)."""
    per_request = max(1, int(per_request or 1))
    requests, current, room = [], [], per_request
    for action, key, ids in pieces:
        ids = list(ids or [])
        while ids:                                  # each request filled to the cap, an action split across two
            if room == 0:
                requests.append(current)
                current, room = [], per_request
            chunk, ids = ids[:room], ids[room:]
            current.append((action, key, chunk))
            room -= len(chunk)
    if current:
        requests.append(current)
    out = {action: [] for action, _key, _ids in pieces}
    for request in requests:
        replies = ankiconnect.multi([{"action": action, "params": {key: chunk}} for action, key, chunk in request],
                                    url)
        if len(replies) != len(request):
            raise AnkiError("'multi' did not answer every action.", kind="protocol")
        for (action, _key, _chunk), reply in zip(request, replies):
            result = _answer(reply, action)
            if not isinstance(result, list):
                raise AnkiError(f"'{action}' did not return a list.", kind="protocol")
            # As `_info`: an id Anki no longer has comes back as {} — dropped here.
            out[action].extend(entry for entry in result if isinstance(entry, dict) and entry)
    return out


# F1 (E2.1.4): the first preview of a session builds the tables its matching reads — JMdict's spellings (0.3 s),
# the tokenizer's join tables (0.2 s), the compound and phrase tables — once per process. Built strictly after
# Anki answered, they made a cold 1,000-card preview 1.2 s against I8's 1 s. Now they are built on a thread of
# their own while Anki answers the reads (a socket wait, which leaves the interpreter free), and the plan waits
# for that thread before it reads a word, so no table is ever read half-built.
_WARMING = {}                   # language -> the thread warming its tables, started once per process
_WARMING_LOCK = threading.Lock()


def _warm(language, settings):
    """Start building this language's matching tables, once per process; the thread to wait for, or None."""
    if language != "ja":
        return None
    with _WARMING_LOCK:
        thread = _WARMING.get(language)
        if thread is None:
            thread = threading.Thread(target=_warm_tables, args=(language, _phrase_rows(settings, language)),
                                      name="junban-warm", daemon=True)
            _WARMING[language] = thread
            thread.start()
    return thread


def _warm_tables(language, phrase_rows):
    """The tables a Japanese plan reads, built the way the plan builds them. Never raises: warming is only ever
    early, and whatever fails here the plan builds for itself."""
    try:
        from app import analyzer, anki_match
        anki_match._dictionary_entries()
        tokenize = _tokenizer(language)
        if tokenize is not None:
            tokenize("今日は図書館で本を読んだ。")
        analyzer.compound_parts()
        if phrase_rows:
            from app import phrases
            phrases.load()
    except Exception:
        pass


def prepare(settings):
    """A fast re-plan host's warm-up (E3.1, at its window's open, on its worker): the matching tables, the library
    map's reads and the known words an automatic job reads — so the first move pays for none of them. Never raises."""
    try:
        language = _language(settings)
        thread = _warm(language, settings)
        if thread is not None:
            thread.join()
        _memo_file("counts", library_map_path(), lambda: _library_counts(language), language)
        _memo_file("floor", library_map_path(), lambda: match.library_floor(library_map_path()), language)
        if _unlisted(settings) == "journey":
            _memo_file("library", library_map_path(), lambda: match.load_library(library_map_path(), language), language)
        _known_memo(language, settings)
    except Exception:
        pass


def _numbering(language, decks, job, front=None):
    """The fast re-plan's numbering for `plan` (03 §2): the spaced ladder from the recorded bottom
    (E2.1-1), new cards after the others in a tie, tomorrow's own numbers first when a move would push
    more than tomorrow out of it (`front`: N, E3.3), or None — 2.5's dense block — when there is no job."""
    if job is None:
        return None
    record = undo.ladder(language, decks)
    return spaced.Numbering(floor=record["floor"], after=record["seen"], front=front)


def _front(job, per_day):
    """N, tomorrow's cards (D6): the job's own `front`, else the scope's decks' highest *New cards/day*
    (`per_day`: {deck: perDay}), at least 20 — one figure for the numbering and the requests (E3.3)."""
    if job.front is not None:
        return job.front
    days = [value for value in (per_day or {}).values() if isinstance(value, int) and not isinstance(value, bool)]
    return spaced.front_size(max(days) if days else None)


def _per_day(url, decks):
    """{deck: its New cards/day} as `preflight` reads it, for a preview that runs no preflight; a deck whose
    options can't be read is left out (the figure falls back to 20)."""
    out = {}
    for deck in decks:
        try:
            config = ankiconnect.deck_config(url, deck)
        except AnkiError:
            continue
        new = config.get("new") if isinstance(config, dict) else None
        out[deck] = new.get("perDay") if isinstance(new, dict) else None
    return out


def _plan_scope(settings, decks, url, job=None, unattended=False, front=None, out_read=None):
    """Gather the scope and decide the new order. The shared body of `dry_run` and `run`.

    Deliberately one function, called once per run: the preview the user confirms and the writes
    that follow must come from the same pass, or the confirmation is describing a different
    calculation from the one that reaches the collection (invariant I5).

    `out_read` (P4.1 L2, TF fix 10): the run's one read of what is taken out (`pins.read_out`), when its Put back
    already read it; None: read here.
    """
    # Connect's preview (P1.4), read once for the run: off, nothing below differs from 2.5 (`connect.py`).
    from modules.junban import connect
    preview = connect.preview_on(settings)
    acting = bool(job is not None and job.automatic and job.actions)
    parked_tag = (unlisted.later_tag(touchup.options(settings).get("tag"))
                  if connect.unsuspends(settings, unattended, acting=acting) else None)
    # M-W1: with Connect off, the 3.0 host's job looks for its parked cards once per list and pin set (a word comes
    # back to the list only with a Generate, a parked card otherwise only by a pin; a move or a Finish adds none): the
    # move budget's moves send nothing more (E2.1). The look counts as done only once all it found is back (`run`).
    pinned_read = None
    parked_key = None
    if parked_tag and acting and not preview:
        if connect.PINS:
            from modules.junban import pins as pin_feed
            pinned_read = pin_feed.read(_language(settings))
        parked_key = _parked_read_key(settings, decks, parked_tag, pinned_read)
    elif acting and not preview:
        _PARKED_READ.pop((_language(settings), tuple(sorted(decks))), None)     # the suspend setting off: look again
    if parked_key is not None and _PARKED_READ.get(parked_key[0]) == parked_key[1]:
        parked_tag = None
    warming = _warm(_language(settings), settings)     # F1: the tables build while Anki answers
    try:
        cards, detail = _gather(url, decks, _word_fields(settings), _language(settings), parked_tag,
                                card_map=job.cards if job is not None else None, parked_map=parked_key is not None)
    finally:
        if warming is not None:
            warming.join()                              # never outlives the read, even when Anki died
    # A Chinese list read as one script spells its words in THAT script; a card keeps whatever its
    # user wrote. Convert the LOOKUP KEY only — nothing converted is ever written to the card.
    script = _script(settings)
    if script != "asis":
        from app.zh_script import convert
        for card in cards:
            card["word"] = convert(card["word"], script)
    opts = touchup.options(settings)
    only = _only_markers(settings)
    # `only` narrows the RANK index alone — a word it excludes becomes unmatched, which the planner
    # already knows how to place — while `marks_of` covers every row so the preview can still show
    # why a word was left out.
    language = _language(settings)
    # The fast re-plan hands in its engine's rows (02 §4): the same index, read from the order you just
    # made instead of the last Generate's CSV.
    index = match.build_index(order_csv_path(settings), thresholds=_thresholds(settings), only=only,
                              language=language, rows=job.rows if job is not None else None)
    rank_of, marks_of = index.rank_of, index.marks_of
    if not marks_of and index.words is None:
        # M-W2-1 (review #2): the list couldn't be read (`build_index` gives no rows and no words) — refused, never
        # "empty": an empty list's answer is ok, and the window's re-order would count the order as written
        return [], {"decks": list(decks), "problems": [LIST_UNREADABLE], "order": [], "to_write": 0,
                    "total": len(cards), "considered": 0, "matched": 0, "unmatched": 0}
    # *Study its cards first* (P2.2; E1.1 03 §8): the user's own pins, read once for the run — never in 2.x
    # (`connect.PINS`, ✅ E1.3-3), where this is None and nothing below differs.
    pins = None
    outs = {}
    if connect.PINS:
        from modules.junban import pins as pin_feed
        pins = pin_feed.groups(language, cards, detail["notes"], pinned=pinned_read)
        # --- P4.1 L2: *Take its new cards out* (D14) — the taken-out items' cards, by the pins' own matching (the run's
        # one read, `out_read`: TF fix 10) ---
        outs = pin_feed.out_cards(cards, detail["notes"],
                                  pin_feed.read_out(language) if out_read is None else out_read)
        # TF fix 3 (P4.1-7 ⭐ (b), IK Decision 2; the shelf's rule P2.4-5): a card whose word is still on your list
        # stays in, placed by the list like any — only the cards whose words left it go last and out
        word_of = {card["card_id"]: card.get("word") or "" for card in cards}
        outs = {card_id: items for card_id, items in outs.items()
                if not match.lookup(word_of.get(card_id) or "", marks_of or {}, language)}
        # --- end P4.1 L2 ---
    if not marks_of and not any(pins or ()):
        # M-W2-1: no list at all (`marks_of` covers every row; `only` narrows `rank_of` alone) and no pinned item — nothing
        # is placed, tagged or suspended: the run writes nothing (`_run`), the preview says the list is empty. With a pin
        # (review #1) the plan goes on, the pinned item's cards first and its parked ones back, and still puts none away
        return [], {"decks": list(decks), "problems": [], "order": [], "to_write": 0, "total": len(cards),
                    "considered": 0, "matched": 0, "unmatched": 0, "empty_list": True}
    # MR-R3: a parked card whose word is on the list again is planned with the rest (the run unsuspends it first);
    # one still not on it is left out, as before. ✅ E1.3-2: so is a pinned item's card Junban itself parked — by
    # Junban's lasting record of what it parked (P4.2.2, #9: never a card you suspended after Junban only tagged it).
    gathered = cards
    cards, back = (connect.returning(cards, marks_of, language,
                                     pinned={i for g in pins or () for i in g} - _excluded(settings),
                                     parked=first_touch.parked(language), out=outs)
                   if parked_tag else (cards, []))
    later_back = _later_back(gathered, back, parked_tag)
    if parked_tag and parked_key is not None:
        if back:
            parked_memo = parked_key            # set by `run` once every returning card is back
        else:
            _PARKED_READ[parked_key[0]] = parked_key[1]     # nothing to bring back: the next job of this list looks no more
            parked_memo = None
    else:
        parked_memo = None
    # Where the cards the list does not have go — see DEFAULT_UNLISTED. A marker filter (WP-N) keeps
    # its promise instead: only the chosen words move, and everything else keeps its order at the back.
    placement = _unlisted(settings)
    tiers = _tiers(settings)
    journey = tiers and placement == "journey"
    order = _order(settings)
    # "List first": a phrase joins the list's words, where the journey meets it, when the library
    # meets it as often as the list's own cut-off asks of a word. "journey": every word the list cut
    # off is placed among it.
    # An automatic job (the fast re-plan's, E3.1) runs at every move: it reads the last Generate's library map once
    # per Generate (`_memo_file`), and leaves out what only the 順 window shows (`lean`: the "why" file names, each
    # list card's sentence-placed fallback, "Same word as one on your list?").
    lean = job is not None and job.automatic
    memo = ((lambda name, path, load: _memo_file(name, path, load, language)) if job is not None
            else (lambda _name, _path, load: load()))
    library = (memo("library", library_map_path(), lambda: match.load_library(library_map_path(), language))
               if journey else {})
    floor = (memo("floor", library_map_path(), lambda: match.library_floor(library_map_path()))
             if tiers and not journey else None)
    # And never below the bar the list's own words actually cleared: under the "coverage" selection
    # the map's min_count is only the pre-filter (2 by default) and greedy coverage cuts the list
    # further (analyzer.py:1713, :2011). Under the density band the two agree.
    listed = [numbers[2] for numbers in index.journey_of.values()]
    if floor is not None and listed:
        floor = max(floor, min(listed))
    names = _file_names(language) if tiers and not lean else []
    # RP-10 (E3.1): with the engine's rows, the library map's and the phrase places' file numbers are the last
    # Generate's — each read through the new order (`spaced.Job.places`) until the next Generate writes them again.
    places = getattr(job, "places", None) if job is not None else None

    def moved(numbers):
        if not places or not numbers:
            return numbers
        return (places.get(numbers[0], numbers[0]),) + tuple(numbers[1:])
    # §16: the user's answers to "Same word as one on your list?". A "yes" is as good as an exact
    # key from then on, in every run — the automatic one included; a "no" is never asked again.
    answers = pairs.load(language)
    tokenize = _tokenizer(language)
    reader = tokenize or _card_reader(language, script)     # a Chinese card's word read alone, for card_key only
    verb = _card_verb(language)                             # 吃了 is 吃: a 了 / 过 / 着 after a verb comes off
    # What the last Generate counted, so 順 reads a sentence as the list does (`_learning`).
    counted = memo("counts", library_map_path(), lambda: _library_counts(language))
    # Which list key each card's word reaches: itself, a spelling the content used, or the kana
    # fold (Junban_Backlog_Spec §5.1, L1–L4); the user's "yes"; or — no question asked — the word
    # with an ending written onto it taken off, 努力する -> 努力, バシッと -> バシッ (L7,
    # Anki_Match_Consistency_Scope.md item 2; `match.card_key`, shared with the report's label). The
    # touch-ups and the preview look a card up by its OWN word, so a card that matched through another
    # key is filed under it as well.
    phrase_rows = _phrase_rows(settings, language)
    # LOOP-F2: a card Connect made goes on the row Connect mined it for (its record, `made_words`) when its own word
    # finds no row of its own — ヒトリ's card, mined as ひとり, is never "not the name" — never over its exact row,
    # your "yes" or your "no" (`match.connect_row`, the report's label's rule too). Japanese: Connect makes no
    # Chinese cards (and the label reads Japanese only)
    made = _made_by_connect(language) if cards and language == "ja" else {}
    for card in cards:
        key, via = match.card_key(card["word"], rank_of, language, answers, reader, index.words, index.orths,
                                  phrases=phrase_rows, verb=verb)
        key, via = match.connect_row(made.get(card.get("note")), key, via, card["word"], rank_of, answers,
                                     index.words)
        if via == "yes":
            card["matched"] = True
        card["key"] = key
        if key and key != card["word"] and key in marks_of:
            marks_of.setdefault(card["word"], marks_of[key])
        if key and (tiers or card.get("matched")):
            card["why"] = f"list #{rank_of[key] + 1:,}" + (MATCHED_BY_YOU if card.get("matched") else "")
        if key and tiers:
            card["sort"] = journey_sort(order, index.journey_of.get(key), rank_of[key])
        if key and index.journey_of.get(key):
            card["file"] = index.journey_of[key][0]     # #50: the show it's for (`show_tags`)
        if not key and library:
            found = match.card_key(card["word"], library, language, None, reader, phrases=phrase_rows,
                                   verb=verb)[0]
            if found:
                card["tier"] = "library"
                card["sort"] = journey_sort(order, moved(library[found]))
                card["file"] = moved(library[found])[0]
                card["why"] = _where(moved(library[found]), names)
    banner = []
    # Japanese only, like the lookup itself (jieba already cuts Chinese into whole words), so a
    # Chinese preview never promises phrases after the next Generate.
    phrases_on = first_applies(settings, language) and _phrases(settings)
    if phrases_on:
        # L9: a phrase or compound card (気がつく, 騎士団), found as that run of words in the library —
        # one pass over it, cached per Generate (§11.1 item 2). Switched off, a phrase card is simply
        # one the list does not have: by its sentence, below.
        unplaced = [card for card in cards if not card["key"] and card.get("tier") != "library"]
        phrases = match.phrase_places([card["word"] for card in unplaced], language,
                                      phrase_cache_path(), library_map_path())
        for card in unplaced:
            numbers = moved(phrases.get(card["word"]))
            if numbers is None or (not journey and (floor is None or numbers[2] < floor)):
                continue                # too rare for the list's own bar: by its sentence, below
            card["tier"] = "library" if journey else "phrase"
            card["sort"] = journey_sort(order, numbers)
            card["file"] = numbers[0]
            card["why"] = "phrase · " + _where(numbers, names)
    suggestions = {}
    if tiers:
        # Known words last; everything still unplaced by its own sentence, then FreqSort (§5.4).
        _place_the_rest(cards, detail["notes"], language, settings, rank_of=rank_of, answers=answers,
                        tokenize=tokenize, library=counted, forms=preview, lean=lean,
                        known_memo=_known_memo(language, settings) if job is not None else None)
        banner = _banner(cards, detail["notes"], language)
        # §16: one entry per card word for "Same word as one on your list?", and on each card the
        # place a tick gives it (`suggestion`) — the very place a recorded "yes" gives it in a run.
        for card in cards:
            found = card.pop("check", None)
            if not found or found["found"].key not in rank_of:
                continue
            key = found["found"].key
            rank = rank_of[key]
            card["suggestion"] = (key, rank, journey_sort(order, index.journey_of.get(key), rank),
                                  f"list #{rank + 1:,}{MATCHED_BY_YOU}")
            entry = suggestions.setdefault(card["word"], {
                "word": card["word"], "key": key, "rank": rank, "reading": found["found"].reading,
                "evidence": found["found"].evidence, "via": found["found"].via,
                "excerpt": found["excerpt"], "answer": found["answer"], "card_ids": []})
            entry["card_ids"].append(card["card_id"])
    # §17, "i+1 first": a list card whose own sentence is not ready gets the word it needs brought
    # right before it, or waits. Before the plan, so the preview and the run are one pass (I5).
    ready_first = (_ready_first_pass(cards, detail["notes"], rank_of, index.journey_of, order, language,
                                     settings, counted)
                   if first_applies(settings, language) and _ready_first(settings) else None)
    # HC-N54: the cards you mined yourself since Connect's first go ahead of every other, in the order you mined them.
    yours = (connect.mark_yours(cards, detail["notes"], connect.first_connect_note(url), connect.own_tag(settings))
             if preview else [])
    for card in cards if not connect.order_all(settings) else ():      # "Order all": yours keep the list's order
        if card.get("yours"):
            card.update(tier="yours", sort=(card["card_id"],), why="yours")
    # --- P4.1 L2, TF fix 2 (P4.1-6 ⭐ (b), ruling P1.4-1: "never suspended"): your own cards are never taken out ---
    if outs and yours:
        mine = set(yours)
        outs = {card_id: items for card_id, items in outs.items() if card_id not in mine}
    # --- end P4.1 L2 ---
    # WP-O. The rows the user clicked off in the preview ride in with the settings and are planned
    # as unmatched — the same pass, so the run writes the order the preview showed (I5).
    excluded = _excluded(settings)
    number = _numbering(language, decks, job, front)
    writes, stats = plan(cards, rank_of, exclude=excluded, number=number, pins=pins, out=set(outs))
    if number is not None:
        stats["number"] = number        # the panel re-plans a click with the run's own numbering (I5)
    if parked_tag and not preview:      # M-W1: the 3.0 host's job brings back what it parked with Connect off too
        stats["returning"], stats["later_back"] = back, later_back
        if parked_memo is not None:
            stats["parked_memo"] = parked_memo
    if preview:
        stats["yours"] = yours
        stats["returning"] = back
        stats["later_back"] = later_back
        # #50 (LF4-3): the show each card is ordered for — only the notes whose label changes are written; never
        # read for a positions-only move, which writes none
        if _show_tags(settings):
            placed = {row.card_id for row in stats.get("order") or [] if row.tier in unlisted.PLACED_WITH_LIST}
            stats["show_tags"] = show_tags.plan([c if c.get("card_id") in placed else dict(c, file=None)
                                                 for c in cards],
                                                show_tags.file_shows(language, current=getattr(job, "rows", None)
                                                                     is not None), detail["notes"])
        stats["unsure"] = sorted({card.get("word") or "" for card in cards
                                  if ((detail["notes"] or {}).get(card.get("note")) or {}).get("unsure")})
    stats["decks"] = list(decks)
    stats["fields"] = detail["fields_by_model"]   # note type -> the field the word was read from
    stats["field_names"] = detail["field_names"]  # every field name in scope, for the panel's pickers
    stats["ranked"] = len(rank_of)
    # WP-M/WP-N, for the panel: which order this preview is of, which markers each word carries, and
    # which filter produced it. The preview is the confirmation, so it has to be able to say all
    # three without recomputing any of them.
    stats["order_mode"] = _order(settings)
    stats["marks"] = marks_of
    stats["only_markers"] = list(only)
    # Tiers on, but no library map to place by until the next Generate — and the panel says so rather
    # than leaving it to be guessed. "journey": none carrying the journey's numbers (none yet, or one
    # written before ENGINE_REVISION 11), so the words the list cut off wait at the back. "List
    # first": none to read the list's cut-off from, so the phrases go with the rarer cards — which is
    # nothing to mention when the phrases are switched off anyway.
    stats["unlisted"] = placement
    stats["ready_first"] = ready_first
    stats["library_missing"] = tiers and (not library if journey else phrases_on and floor is None)
    stats["banner"] = banner

    # The touch-ups are planned in the SAME pass as the writes, so the preview states what will
    # actually happen rather than a second calculation's opinion of it (invariant I5).
    stats["note_by_card"] = detail["note_by_card"]
    moved = _moved_notes(writes, stats.get("order") or [], detail["note_by_card"])
    stats["touchups"] = touchup.plan(moved, detail["notes"], opts, marks_of=marks_of)
    # §16: "Same word as one on your list?", best rank first — and, when there is anything to
    # tick, the touch-ups of every card that could end up on the list once it is: the panel narrows
    # this to the cards actually moving after a tick (`touchup.restrict`), as the run would plan them.
    stats["suggestions"] = sorted(suggestions.values(), key=lambda entry: (entry["rank"], entry["word"]))
    if suggestions:
        could = {row.card_id: row for row in stats.get("order") or []}
        wider_marks = dict(marks_of)
        candidates = []
        for card in cards:
            row = could.get(card["card_id"])
            note_id = detail["note_by_card"].get(card["card_id"])
            if row is None or not isinstance(note_id, int):
                continue
            if row.rank is not None:
                candidates.append((row.card_id, note_id, row.word, row.rank))
            elif card.get("suggestion"):
                key, rank = card["suggestion"][:2]
                candidates.append((row.card_id, note_id, row.word, rank))
                if key in marks_of:
                    wider_marks.setdefault(row.word, marks_of[key])
        stats["touchups_all"] = touchup.plan(candidates, detail["notes"], opts, marks_of=wider_marks)
        stats["suggested_marks"] = {card["word"]: marks_of[card["suggestion"][0]] for card in cards
                                    if card.get("suggestion") and card["suggestion"][0] in marks_of}
    # §13: what happens to the cards NOT on the list — planned in the same pass for the same reason,
    # from the rows, because those cards often do not move at all.
    # A card the user clicked OFF the list is acted on like any card not on it; one they clicked to
    # leave alone is not. The panel re-plans the same way on every click, from what is kept here.
    taken = set(stats.get("taken_off_ids") or ())
    stats["flags_of"] = {card["card_id"]: card.get("flags") for card in cards}
    stats["note_tags"] = {note_id: {"tags": note.get("tags") or []}
                          for note_id, note in (detail["notes"] or {}).items()}
    # M-W2-1: an empty list (a pinned item's run, review #1) puts no card away
    stats["later"] = {} if not marks_of else unlisted.plan(stats.get("order") or [], marks_of, language,
                                                           stats["flags_of"], stats["note_tags"],
                                                           unlisted.options(settings), parent=opts.get("tag"),
                                                           exclude=(excluded - taken) | set(yours), taken_off=taken,
                                                           out=outs)
    # P4.1 L2: what *Take its new cards out* does — planned in the same pass (I5); a run acts on it only when its
    # caller records it (`spaced.Job.cards_out`)
    if outs:                            # only when something is out: a plan with nothing out returns what it always did
        stats["cards_out"] = unlisted.plan_out(stats.get("order") or [], outs, stats["note_tags"],
                                               parent=opts.get("tag"), exclude=excluded | set(yours))
    return writes, stats


def _later_back_on(url, snapshot, again, note_of, chunk):
    """#50: a restore puts the `::later` tag back on the notes of the returning cards it sets aside again — BEFORE it
    suspends them, so no card of Junban's is ever suspended without its tag (Known from Anki would read it as
    yours) -> `[(note id, why)]` for the notes it couldn't tag, as Anki's other tag writes report them."""
    failures = []
    for tag, notes in undo.restore_later_back(snapshot, {note_of.get(card_id) for card_id in again or ()}).items():
        _done, failed = ankiconnect.add_tags(url, notes, tag, chunk=chunk)
        failures += list(failed)
    return failures


def _later_back(cards, back, tag):
    """Laptop round 8 #50: `{tag: [note ids]}` — the returning cards' notes whose `::later` tag comes off with their
    unsuspend (Sonic: a card back on the list kept "Surasura::later", which was no longer true). Never a note another
    card of which stays parked: its tag is that card's record (`connect.parked_query`, and Known from Anki never
    counts a suspension carrying it)."""
    if not back or not tag:
        return {}
    back = set(back)
    note_of = {card.get("card_id"): card.get("note") for card in cards or ()}
    staying = {card.get("note") for card in cards or () if card.get("parked") and card.get("card_id") not in back}
    notes = sorted({note_of.get(card_id) for card_id in back} - staying - {None})
    return {tag: [n for n in notes if isinstance(n, int)]} if notes else {}


def _moved_notes(writes, placements, note_by_card):
    """`[(card_id, note_id, word, rank)]` for the cards that are matched AND actually moving.

    Both halves are the spec's: an unmatched card has no rank and no sentence so it gets no
    touch-up, and a card already in the right place was not moved by this run so nothing claims it
    was. The tag is the answer to "which of these did Surasura touch?", and it has to be true.
    """
    by_card = {row.card_id: row for row in placements}
    moved = []
    for card_id, _due in writes or []:
        row = by_card.get(card_id)
        if row is None or row.rank is None:
            continue
        note_id = (note_by_card or {}).get(card_id)
        if isinstance(note_id, int):
            moved.append((card_id, note_id, row.word, row.rank))
    return moved


def dry_run(settings, job=None, unattended=False):
    """The preview: `(writes, stats)` for the scope, with **nothing written anywhere**.

    Reads Anki (`findCards`, `cardsInfo`, `notesInfo`) and the priority CSV, and that is all — no
    `setSpecificValueOfCard`, no snapshot, no deck-options change. `stats["order"]` carries the
    `Placement` rows the panel's preview table renders, and `stats["to_write"]` is the number the
    confirmation must state before the real run.

    Raises `AnkiError` if Anki goes away mid-read; the panel already has to handle that, and a
    preview that silently returns "0 cards" when the connection died would read as "nothing to do".

    `job` (a `spaced.Job`): the fast re-plan's preview — the order numbered on the spaced ladder, as
    the run with the same job will write it. None is 2.5's preview. `unattended`: planned as an
    unattended run plans (`surasura-cli resort --dry-run`, P2.2: what that run will do, no more).
    """
    url = _url(settings)
    decks, problems = _resolve_decks(settings, url)
    if problems:
        # No usable scope. An empty plan with the reason attached beats raising: the panel shows this
        # in the same place it shows a real preview.
        return [], {"decks": [], "problems": problems, "order": [], "to_write": 0,
                    "total": 0, "considered": 0, "matched": 0, "unmatched": 0}
    try:
        front = None if job is None else _front(job, _per_day(url, decks) if job.front is None else None)
        return _plan_scope(settings, decks, url, job, unattended, front=front)
    except spaced.SpacedError as e:
        return [], {"decks": list(decks), "problems": [str(e)], "order": [], "to_write": 0,
                    "total": 0, "considered": 0, "matched": 0, "unmatched": 0}


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #
def _refresh_anki(url):
    """Drop the reviewer's stale queue so the new order is what the user actually studies.

    Best-effort by design: the writes have already landed, and failing the whole run because a
    cosmetic refresh did not answer would misreport a successful reposition as a broken one.
    """
    for action in ("reloadCollection", "guiDeckBrowser"):
        try:
            ankiconnect.invoke(action, url, timeout=15)
        except AnkiError:
            pass


def _report(ok, message, **extra):
    """The shape every entry point returns, so the panel renders one thing rather than four."""
    report = {"ok": ok, "message": message, "problems": [], "warnings": [], "decks": [],
              "written": [], "failures": [], "snapshot": None, "stats": {},
              # WP-L. Note ids, kept apart from the card ids above: they are a different id space
              # and "3 failed" over both would name nothing the user could look up.
              "notes_updated": [], "tagged": [], "note_failures": [], "fields_skipped": 0,
              # WP-N. Kept apart from `tagged`: one answers "which notes did Surasura move?", the
              # other "which of those carry a marker?", and merging them would overstate both.
              "marker_tagged": []}
    report.update(extra)
    return report


def run(settings, progress=None, refresh=True, wait=0.0, cancel=None, on_wait=None, verb="順 reorder",
        unattended=False, run_id=None, job=None):
    """Reposition the scope, holding the Anki-write lock from the first read to the last write (E1.4
    §W): `wait` / `cancel` / `on_wait` say how long to wait for another writer
    (`anki_connect.take_writer`); still held, or refused after the wait, it returns the usual refusal
    with `busy: True`. The run itself: `_run`. `job`: the fast re-plan's preview (`spaced.Job`).

    Connect's preview (P1.4): `unattended` is a run nobody started in 順 (the automatic step, `junban --auto`) — it
    never unsuspends a returning word's card before 3.0 (`connect.unsuspends`); `run_id` gives the run a snapshot of
    its own (`undo.save(run_id=)`), never the window's.

    With a `job` (the preview on; on 3.0 every run of the 順 window too, `gui.window_job`), the sync rule (E1.1 04
    §3, `app/anki_sync_rule.py`) goes with every run: a
    session's first write syncs Anki first (S1, `_write_spaced`: just before the first request, so a run that writes
    nothing never syncs) — reviews made on the phone arrive before a position lands on them — and a run that changed
    tomorrow's cards starts S3's clock. None: 2.5's run, request for request."""
    held, problem = anki_connect.take_writer(verb, _url(settings), wait, cancel, on_wait)
    if held is None:
        return _report(False, "Junban did not make any changes.", problems=[problem], busy=True)
    if job is not None:                                 # P4.1 L2: this run's Put back, never a reused job's last one
        job.put_back, job.put_back_owed = [], None
    with held:
        report = _run(settings, progress, refresh, unattended, run_id, job)
    if job is not None and getattr(job, "put_back", None):
        report["put_back"] = list(job.put_back)        # P4.1 L2: the records its Put back restored (`pins.record`)
    _put_back_owed(report, getattr(job, "put_back_owed", None) if job is not None else None)
    if job is not None and report.get("written"):
        from app import anki_sync_rule
        anki_sync_rule.wrote(bool(set(report["written"]) & set(job.front_ids)), settings)
    return report


def _write_spaced(url, stats, checks, job, settings, progress=None, map_read=False, profile=None):
    """The fast re-plan's writes (E1.1 03 §3.4–6) -> `(written, failures, left)`.

    Request 1 is tomorrow's cards — every changed card among the plan's first N (`job.front`, else the
    deck's New cards/day, at least 20: D6) and every card pushed out of that front — so that once it
    lands Anki's first N new cards are the plan's; then the rest, `junban_chunk_size` at a time, each
    request in new-position order. Before each request its cards are read again: one no longer new, or
    no longer where it was read, is left for the next job (`left`).

    `map_read` (E3.1-B2): the job's warm card map was read for this run — its profile spares S1 a request, and,
    when no sync ran since, its mod times make the re-check light (`set_due_checked`'s `mods`).

    `profile` (FT C7): the open profile the run read under the lock a moment ago for its first-touch record (the map's,
    else its one `getActiveProfile`) — S1 is handed it, so a positions-only move asks no more than before the record;
    "" (Anki named none) starts no session, as S1's own read would have said."""
    order = stats.get("order") or []
    current = [(row.card_id, row.due) for row in order]
    front = _front(job, checks.get("per_day"))     # the numbering's own N (E3.3: tomorrow's numbers first)
    news = [row.position for row in order]
    # For the caller's line (E3.1: "placing tomorrow's 20 cards…"), before the first request goes.
    job.front_size, job.kind = front, (stats.get("numbering") or {}).get("kind")
    job.front_ids = frozenset(card_id for card_id, _new in spaced.front_group(current, news, front))
    batches = spaced.requests(current, news, front, _chunk_size(settings))
    card_map = job.cards if map_read else None
    synced = None
    if batches:
        # S1, holding the lock, just before the first request (the re-check below then reads every card again: one
        # the sync made no longer new, or moved, is left for the next job).
        from app import anki_sync_rule
        if card_map is not None and card_map.key:
            profile = card_map.key[0]
        synced = (None if profile == "" and card_map is None
                  else anki_sync_rule.before_write(url, locked=True, profile=profile))
    # An automatic job stops between requests when a review starts (04 §6: never while reviewing): the rest wait.
    def stop_if(active=None):
        if anki_connect.reviewing(url) if active is None else active:
            job.stopped_for_review = True
            return True
        return False
    stop_if = stop_if if job.automatic else None
    mods = since = None
    if card_map is not None and synced is None:     # a sync may have changed any card: the long re-check then
        mods = {card_id: row.get("mod") for card_id, row in card_map.rows.items()}
        since = card_map.read_at - 1
    return ankiconnect.set_due_checked(url, batches, dict(current), progress=progress, stop_if=stop_if,
                                       mods=mods, since=since, on_busy=lambda: setattr(job, "anki_busy", True))


def _restore_scope(settings):
    """The decks a Restore is for, before Anki is asked: the nominated deck, or `undo.ALL_DECKS` (the decks
    themselves are known only by asking Anki) — the one scope the window, its confirm check and the
    restore all ask `undo.restorable` with."""
    if _scope_mode(settings) == "deck":
        return [str(settings.get("junban_deck") or "").strip()]
    return undo.ALL_DECKS


def _taken_back(language, snapshot):
    """A Restore took the way back: a manual run's snapshot is marked complete (I3, as ever), and
    today's baseline ends whichever was put back (03 §5) — with no baseline, exactly 2.5's step."""
    if not undo.is_baseline(snapshot):
        undo.mark_complete(language)
    undo.end_baseline(language)


def _save_baseline(pairs, scope, language="ja", mode="deck", **_touchups):
    """`undo.save`'s place for an automatic re-order (03 §5): today's baseline. Positions only — an
    automatic re-order writes nothing else — so the touch-ups' keys carry nothing to keep."""
    return undo.save_baseline(pairs, scope, language=language, mode=mode)[0]


def _run(settings, progress=None, refresh=True, unattended=False, run_id=None, job=None):
    """Reposition the scope. Preflight, snapshot, write, refresh — in that order, always.

    `refresh=False` skips telling Anki's window to reload (the automatic run, `auto.py`): that
    call sends Anki to its deck list, and an automatic run must never pull the user out of what
    they are doing. Anki builds its new-card queue when a deck is opened, so the order still
    applies from the next study session.

    Returns a report dict: `ok`, `message`, `problems`, `warnings`, `decks`, `snapshot` (the path of
    the undo file), `written` (card ids that genuinely changed), `failures` (`[(card_id, reason)]`)
    and `stats` (the planner's counts, including the `order` the preview showed).

    Partial progress is reported honestly rather than raised: if Anki disappears halfway through, the
    cards already written stay written, the snapshot stays on disk covering **all** of them, and
    `failures` names the rest. That is the only outcome in which the undo file earns its existence,
    so it must survive the failure that made it necessary.

    `job` (a `spaced.Job`) is the fast re-plan's preview (E1.1 03): the same order, numbered on the
    spaced ladder; the writes go front first (`_write_spaced`), each request re-checked. A run from the
    順 window keeps 2.5's snapshot and refusal exactly, and ends today's baseline; an automatic one
    (`job.automatic`) writes positions only, and keeps today's baseline instead of the snapshot — once
    a day, never a reason to refuse (03 §5). With no job, 2.5's run, request for request.

    3.0 (W3.5 row 7, Haya's G2b): an automatic job `auto.reorder` hands in (`job.actions`) comes with its settings
    already decided, and applies them in 2.5's order — the returning words' cards unsuspended, the positions, the
    touch-ups on the notes that moved, then tag → flag → suspend. With an action to write it keeps one restore point
    instead of today's baseline: the window's snapshot, or the run's own (`run_id`). A review that stopped the job, or
    a card left for the next one, means no actions this run; and one `cardsInfo` read just before them drops a card
    off the list no longer new or already suspended (`_still_new`) — and, Anki not answering it, none at all. The
    window's re-order host sets `actions` too on 3.0 (its settings from `auto.decide_actions`); 2.x-dev's never.
    """
    if job is not None and job.automatic:
        put_back = _put_back_since(settings)
        if put_back is not None:                        # FT C1: a put-back cleared the deck while this one waited
            return _report(False, "Junban did not make any changes.", problems=[put_back], stands_aside=True)
        if _scope_mode(settings) == "all":              # rule 6: never on All decks automatically
            return _report(False, "Junban did not make any changes.",
                           problems=["An automatic re-order runs for one deck only — choose one in the 順 window."],
                           one_deck=True)             # a7: the deck to pick in 順 (the re-order host's amber)
        if not job.actions:
            # An automatic re-order moves positions only — but the one `auto.reorder` hands in, whose settings it
            # already decided (2.x-dev has no `actions`: every automatic job is positions only there).
            from modules.junban.auto import _POSITIONS_ONLY
            settings = dict(settings, **_POSITIONS_ONLY)
    checks = preflight(settings, probe=job.probe if job is not None else None)
    if not checks["ok"]:
        return _report(False, "Junban did not make any changes.",
                       problems=checks["problems"], warnings=checks["warnings"],
                       decks=checks["decks"])

    url = _url(settings)
    decks = checks["decks"]

    # A run that died halfway left the only copy of how the deck really was. Starting another would
    # snapshot the half-written order over it, so the way back must be taken first.
    # 2.x-dev keeps I3 for every run; 3.0: a run nobody started never stops the automation it belongs to — an
    # automatic job that finds an automatic run's window snapshot unfinished (`"automatic": true`: cut by Anki
    # closing) goes on. With nothing to act on it leaves that snapshot alone (today's baseline is a file of its own);
    # with an action to write it takes it over (`cut`, below). Disc-T1 (Mattias, 3.0.0; Sonic 2026-11-12: "yes to the
    # Junban recovery one"; HY-11 before): nor does it stop a run you start in 順 — yours takes it over for the same
    # deck and finishes the job, and one Undo puts back both (`finished_automatic`). Every other unfinished window
    # snapshot still refuses: one you started (a run of yours), a 2.5 file, another deck's cut run.
    automatic = job is not None and job.automatic
    previous = undo.load(_language(settings))
    cut = None
    if previous and previous.get("complete") is False:
        if previous.get("automatic") is not True:
            return _unfinished_refusal(checks, decks)
        if not automatic and not _same_scope(previous, decks, settings):
            return _unfinished_refusal(checks, decks)       # another deck's: only its own Restore puts it back
        cut = previous
    # One of Connect's runs left unfinished (P1.4, §7.2): its snapshot is the only way back from it. An automatic job
    # goes on (lead 2026-11-07, Mattias's alpha-3 notes; Sonic's W3.5 row 7, "a run nobody started never stops the
    # automation"; PROVISIONAL): one without a run of its own (the re-plan's, 順's automatic step) takes that run over in
    # the window's snapshot for the same deck, as row 7 takes over the window's own cut run (`connect_cuts`, below): one
    # Undo then goes back past both, never the older first. Connect's own next run (`run_id`) leaves it as it is: its
    # Undo still offered first. Junban-X (Sonic 2026-11-13, overturning the lead's 2026-11-07 ruling): a reorder you
    # start (順's Reorder) takes over every such run too when their record is complete (`_connect_cuts`: each readable,
    # for this deck and scope mode) — else it asks for their Undo first, as before.
    unfinished = undo.unfinished(_language(settings), "reorder")
    connect_cuts, blocked = [], None    # [(run id, its snapshot)] this run takes over; the runs it can't (`_connect_cuts`)
    if unfinished is not None and automatic and run_id is None:
        connect_cut = undo.load(_language(settings), run_id=unfinished)
        connect_cuts = [(unfinished, connect_cut)] if connect_cut else []
    elif unfinished is not None and not automatic:
        connect_cuts, blocked = _connect_cuts(settings, decks)
        if blocked and blocked["held"]:     # Junban-X2 (Sonic 2026-11-13): a file held a moment (an antivirus, a cloud
            _held_wait()                    # folder) is read again once, quietly, before you're asked for its Undo
            connect_cuts, blocked = _connect_cuts(settings, decks)
    if unfinished is not None and not automatic and blocked:
        # Junban-X2: only other decks' runs in the way (none held) -> the window offers one press, *Put that one back,
        # then reorder* (`put_back_first`: their ids; their decks named)
        elsewhere = [] if blocked["held"] or blocked["overlapping"] else blocked["elsewhere"]
        named = _decks_named(settings, elsewhere) if elsewhere else ""
        problem = (UNFINISHED_ELSEWHERE.format(decks=named) if elsewhere else
                   f"An automatic reorder ({unfinished}) did not finish, and its saved order is the only way back "
                   "from it. Press Undo the last reorder first, then reorder again.")
        return _report(False, "Junban did not make any changes.", problems=[problem], warnings=checks["warnings"],
                       decks=decks, unfinished=unfinished, restore_first=True,
                       **({"put_back_first": elsewhere, "put_back_decks": named} if elsewhere else {}))
    went_on = None if automatic or cut is not None else _went_on(previous, connect_cuts, decks, settings)
    # Backlog onboarding: Try it's numbers from before, carried (`carry_forward_tried`) — only while no automatic write
    # came after it (today's baseline newer than the window's snapshot): that write's baseline is the way back then.
    window_snapshot = None if undo.newer_baseline(_language(settings), previous) else previous
    if run_id is not None:
        previous = cut = None           # a run's own snapshot carries nothing over from the window's

    # --- P4.1 L2: *Take its new cards out* (D14) — only in a run whose caller records it (`job.cards_out`): an item
    # back in the learning order has exactly its recorded cards restored first, so this run places them ---
    recording = bool(automatic and job.actions and getattr(job, "cards_out", False))
    out_read = None
    if recording:
        from modules.junban import pins as pin_feed
        out_read = pin_feed.read_out(_language(settings))      # TF fix 10 (IK #10): read once for the run ({} in 2.x)
    if job is not None:
        put_back = (_put_back_out(url, settings, decks, out_read) if recording
                    else {key: [] for key in _NOTHING_PUT_BACK})
        job.put_back = put_back["restored"]
        job.put_back_owed = put_back                            # TF fix 6: what is still owed rides the report
    # --- end P4.1 L2 ---

    reads = job.cards.reads if job is not None and job.cards is not None else None
    try:
        writes, stats = _plan_scope(settings, decks, url, job, unattended=unattended,
                                    front=None if job is None else _front(job, checks.get("per_day")),
                                    out_read=out_read)
    except (AnkiError, spaced.SpacedError) as e:
        # `anki_error`: Anki stopped answering mid-read (its kind) — the fast re-plan's job tries again (E3.1 review 3
        # R2), where a refusal only the user can clear is said once. `anki_busy`: Anki busy with a collection operation
        # (its sync, #370) — not now, quietly, for every automatic caller.
        return _report(False, "Junban did not make any changes.",
                       problems=[str(e)], warnings=checks["warnings"], decks=decks,
                       **({"anki_error": e.kind} if isinstance(e, AnkiError) else {}),
                       **({"anki_busy": True} if anki_connect.is_busy(e) else {}))

    if stats.get("problems"):
        # M-W2-1 (review #2): the list couldn't be read — nothing written, and never ok (the caller tries again)
        return _report(False, "Junban did not make any changes.", problems=list(stats["problems"]),
                       warnings=checks["warnings"], decks=decks)
    if stats.get("empty_list"):
        # M-W2-1: an empty list puts nothing away — no write, no snapshot (one of nothing would replace your route
        # back from the last run), no ladder record
        return _report(True, EMPTY_LIST, warnings=checks["warnings"], decks=decks, stats=stats, empty_list=True)
    later = stats.get("later") or {}
    back = stats.get("returning") or []
    out = (stats.get("cards_out") or {}) if recording else {}       # P4.1 L2: positions-only runs place them last
    labels = stats.get("show_tags")         # #50: none planned for a positions-only move (`_show_tags`)
    if not writes and not unlisted.has_work(later) and not back and not unlisted.has_work(out):
        if job is not None:
            placed = [row.card_id for row in stats.get("order") or []]
            if placed:                                   # every card where the plan puts it: none new any more
                undo.record_ladder(_language(settings), decks, seen=max(placed))
        if (show_tags.has_work(labels) and not (job is not None and job.stopped_for_review)
                and not ((automatic or unattended) and anki_connect.reviewing(url))):    # round 2 B3: never in a review
            # #50: the order stands, but a card's show label is behind it (a list moved, a show renamed): only those
            # labels, never a snapshot (one of nothing would replace your route back from the last run)
            labelled, label_failures = show_tags.apply(url, labels, _chunk_size(settings))
            _finish_cut(settings, cut, automatic, decks, stats, connect_cuts, previous, window_snapshot, went_on)
            return _report(True, "Every card is already in the right place — nothing to change." +
                           _labels_clause(labelled), warnings=checks["warnings"] + _labels_warning(label_failures),
                           decks=decks, stats=stats)
        # Idempotence, and the common answer on a second press. No snapshot: overwriting the saved
        # order with an empty one would throw away the user's only route back from the *previous*
        # run, and they would not find out until they pressed Restore. (With the cards not on the
        # list still to tag, flag or suspend, the run goes ahead, snapshot first, positions or not.)
        _finish_cut(settings, cut, automatic, decks, stats, connect_cuts, previous, window_snapshot, went_on)
        return _report(True, "Every card is already in the right place — nothing to change.",
                       warnings=checks["warnings"], decks=decks, stats=stats)

    # An unattended run (Connect's preview) asks again inside the writer's hold, right before its snapshot: planning
    # takes seconds, and a review started meanwhile is never written into (§7.2). Nothing written, no snapshot.
    if unattended and anki_connect.reviewing(url):
        return _report(False, "Junban did not make any changes.", problems=[anki_connect.REVIEWING],
                       warnings=checks["warnings"], decks=decks, stats=stats, reviewing=True)

    # --- I3: the snapshot reaches disk BEFORE the first write ------------------------------- #
    # Every movable card in scope, at its CURRENT position — not just the ones about to change — so
    # the file describes the whole scope as it stood and a restore puts all of it back, including
    # after a run that only half finished.
    original = [(row.card_id, row.due) for row in stats.get("order", [])]
    in_scope = original
    # Backlog onboarding: a card *Try it on my cards* moved, still where it put it, is saved at its number from before
    # Try it — the window's snapshot and today's baseline — so one Restore puts back the order from before Try it.
    carried = undo.carry_forward_tried(window_snapshot, in_scope)
    if run_id is not None:              # one of Connect's runs: exactly the cards it moves, and where it puts them
        due_of = dict(original)
        original = [(card_id, due_of[card_id]) for card_id, _due in writes]
    else:
        original = carried
    touchups = stats.get("touchups") or {}
    # An automatic re-order with the preview on keeps today's baseline instead (03 §5): written once a
    # day, before its first write, never the window's snapshot. Every other run saves the window's
    # snapshot exactly as before — and one of Connect's runs (`run_id`) its own snapshot as well, even when
    # automatic: it is the only way back from that run, and an unfinished one refuses the next (P1.4, §7.2).
    # 3.0 (Haya's G2b): an automatic job with an action to write keeps one restore point instead of the
    # baseline — the window's snapshot (2.5's automatic step's), or the run's own given a `run_id`.
    acting = automatic and job.actions and bool(unlisted.has_work(later) or _has_touchups(touchups) or back
                                                or unlisted.has_work(out))
    connect_cuts = [(cut_id, saved) for cut_id, saved in connect_cuts      # another deck's: left as it is, its own
                    if _same_scope(saved, decks, settings)]                 # Undo puts it back
    taking = bool(connect_cuts)         # this run's window snapshot takes Connect's cut runs over (lead 2026-11-07)
    taken = [cut, went_on] + [saved for _cut_id, saved in connect_cuts]
    if automatic and not acting:
        cut = None                      # a positions-only job leaves the cut run's snapshot alone, restorable
    elif cut is not None and (undo.normalize_scope(cut.get("scope")) != undo.normalize_scope(decks)
                              or (cut.get("mode") == "all") != (_scope_mode(settings) == "all")):
        return _unfinished_refusal(checks, decks, stats)    # another deck's: only its own Restore puts it back

    def save_snapshot(touchups, later):
        # The touch-ups' prior values go in here too, and for the same reason: a field junban
        # overwrites exists nowhere else afterwards, so the copy has to be on disk BEFORE the write
        # reaches the wire, not after it. FT (K8): this run's own field writes in the first-touch journal first.
        first_touch.note(_language(settings), "reorder", profile, decks, fields=touchups.get("fields"))
        return undo.save(original, decks, language=_language(settings),
                         fields=_carried_fields([saved for _cut_id, saved in connect_cuts] + [previous],
                                                touchups.get("fields")),
                         profile=profile,
                         tags=touchups.get("tags"),
                         tag=touchups.get("tag"),
                         marker_tags=_with_later_tag(_with_later_tag(touchups.get("marker_tags"), later), out),
                         mode=_scope_mode(settings),
                         suspended=(sorted(set(later.get("suspend") or []) | set(out["suspend"]))
                                    if out.get("suspend") else later.get("suspend")),
                         flags=later.get("flags"),
                         **({"run_id": run_id, "after": writes} if run_id is not None else {}),
                         **({"unsuspended": back} if back else {}),
                         **({"later_back": stats.get("later_back")} if stats.get("later_back") else {}),
                         automatic=automatic and (acting or taking) and run_id is None,
                         cut=taken, finished_automatic=not automatic and (cut is not None or taking))
    map_read = reads is not None and job.cards.reads > reads
    try:
        parked = set(back)
        # FT D2: the order before Surasura, once — the unsuspended new cards (a returning word's card is still parked)
        profile = _keep_order(settings, decks, [pair for pair in in_scope if pair[0] not in parked], job, url,
                              map_read)
        if automatic and not acting:
            snapshot = _save_baseline(carried, decks, language=_language(settings), mode=_scope_mode(settings))
        held = _held_files(_language(settings), connect_cuts) if taking and not automatic else None
        if run_id is not None or not automatic or acting or taking:
            snapshot = save_snapshot(touchups, later)
        for cut_id, _saved in connect_cuts:     # the window's snapshot now holds their way back: never refused or
            if not undo.mark_complete(_language(settings), run_id=cut_id, taken_over=True) and held is not None:
                _put_back_files(held)           # offered again — or, one not marked, nothing changed (a run you start)
                raise OSError(f"Connect's run {cut_id} could not be marked as taken over")
    except OSError as e:
        # Refusing here is the entire point of I3. A reposition with no undo file is a one-way door:
        # AnkiConnect writes no undo entry, and Anki's own Undo would revert the wrong thing.
        return _report(False, "Junban did not make any changes.",
                       problems=[f"Could not save the undo snapshot, so nothing was changed ({e})."],
                       warnings=checks["warnings"], decks=decks, stats=stats)
    if not automatic or (acting and run_id is None):
        undo.end_baseline(_language(settings))     # a manual run ends today's baseline (03 §5); so does the window's
                                                   # snapshot an automatic run with actions keeps (3.0)

    # MR-R3 first: a returning word's card leaves the suspended pile before its position is written.
    returned, return_failures = (ankiconnect.unsuspend(url, back, chunk=_chunk_size(settings)) if back
                                 else ([], []))
    still = sorted({card_id for card_id, _error in return_failures})
    if still:
        # M-W1 (adversary #3): the journal took them as unsuspended before the write; they're still the cards Junban
        # parked, so a later run brings them back (`first_touch.parked`)
        first_touch.noted(_language(settings), "reorder", profile, decks, landed=True,
                          with_tag=unlisted.later_tag(touchup.options(settings).get("tag")), suspended=still)
        back = [card_id for card_id in back if card_id not in set(still)]   # a snapshot saved again names only these
    elif back and stats.get("parked_memo"):
        memo = stats["parked_memo"]
        _PARKED_READ[memo[0]] = memo[1]         # M-W1: all back — the next job of this list looks no more
    # #50: their `::later` tag off the notes whose returning cards all left the suspended pile (one that didn't keeps
    # it: it is still parked)
    later_notes, later_untag_failures = stats.get("later_back") or {}, []
    if returned and later_notes:
        note_by_card = stats.get("note_by_card") or {}
        failed = {note_by_card.get(card_id) for card_id in set(back) - set(returned)}
        for tag, notes in later_notes.items():
            notes = [n for n in notes if n not in failed]
            if notes:
                _done, untag_failures = ankiconnect.remove_tags(url, notes, tag, chunk=_chunk_size(settings))
                later_untag_failures += list(untag_failures)
    left = []
    if job is None:
        written, failures = ankiconnect.set_due(url, writes, chunk=_chunk_size(settings),
                                                progress=progress)
    else:
        written, failures, left = _write_spaced(url, stats, checks, job, settings, progress, map_read=map_read,
                                                profile=profile)
        if written:                                 # a card is on the ladder: its bottom, and that it was laid
            undo.record_floor(_language(settings), decks, (stats.get("numbering") or {}).get("base"))
        placed = [row.card_id for row in stats.get("order") or []]
        if placed and not failures and not left:     # every card is where the plan put it: none new any more
            undo.record_ladder(_language(settings), decks, seen=max(placed))
    failures = list(return_failures) + list(failures)

    # Narrowed to the notes whose cards genuinely moved: if Anki went away halfway, a tag saying
    # "Surasura ordered this" on a card that never budged is a lie the user cannot see. The snapshot
    # still covers the superset, so the undo is complete either way.
    moved_notes = {(stats.get("note_by_card") or {}).get(card_id) for card_id in written}
    moved_notes = {note_id for note_id in moved_notes if isinstance(note_id, int)}
    out_owed = []                                   # P4.1 L2 (TF fix 6): a take-out planned, not acted on
    held_back = False                               # round 2 B3: a review found at the re-check: no labels either
    if acting:
        # 3.0 (Haya's G2b): a review that stopped the job, or a card left for the next one — no actions this run
        # (they wait for the next); otherwise the cards off the list are read once more, just before them, and
        # Anki is asked in the same request whether a review began after the last position request (04 §6). The
        # snapshot is saved again with what will really be written, so a Restore never unsuspends a card the run
        # didn't suspend (one you suspended meanwhile).
        planned, planned_out = later, out
        if job.stopped_for_review or left:
            touchups, later, out = {}, {}, {}
        else:
            later = _still_new(url, later, _has_touchups(touchup.restrict(touchups, moved_notes,
                                                                          touchup.options(settings))))
            if later is None:                   # a review, or Anki stopped answering: nothing is acted on
                touchups, later, out, held_back = {}, {}, {}, True
            elif out:                           # P4.1 L2: the taken-out cards read once more the same way
                out = _still_new(url, out)
                if out is None:
                    touchups, later, out, held_back = {}, {}, {}, True
        if later is not planned or out is not planned_out:
            try:
                snapshot = save_snapshot(touchups, later)
            except OSError:
                touchups, later, out = {}, {}, {}   # the copy on disk still names them: then none is written
        # P4.1 L2, TF fix 6 (adversary S3): a take-out planned and not acted on (a review, a card left, Anki not
        # answering) is your one click, re-derived from nothing: it stays owed (`left`), so neither caller records the
        # plan as written and the next look tries again. A card studied meanwhile only narrows it: never owed.
        if unlisted.has_work(planned_out) and not out:
            out_owed = list(planned_out.get("suspend") or [])

    applied = touchup.restrict(touchups, moved_notes, touchup.options(settings))
    notes_updated, note_failures = ankiconnect.update_notes(
        url, touchup.edits_for_wire(applied.get("fields")), chunk=_chunk_size(settings))
    tagged, tag_failures = ankiconnect.add_tags(url, applied.get("tags"), applied.get("tag"),
                                                chunk=_chunk_size(settings))
    # WP-N. One call per marker tag, because `addTags` applies one tag to a batch of notes and each
    # marker went on a different subset. Three calls at most, sorted so a run is reproducible.
    marker_tagged, marker_failures = _apply_marker_tags(
        ankiconnect.add_tags, url, applied.get("marker_tags"), _chunk_size(settings))
    note_failures = note_failures + tag_failures + marker_failures
    # #50 (LF4-3): the show each placed card is for, where it changed — not when a review stopped this job's actions.
    # A label that didn't go on is a warning, never an unfinished run (round 2 B4): it's in no snapshot, and the next
    # re-order writes it again.
    labelled, label_failures = 0, []
    if show_tags.has_work(labels) and not held_back and not (job is not None and (job.stopped_for_review or left)):
        labelled, label_failures = show_tags.apply(url, labels, _chunk_size(settings))

    # §13, last: the cards not on the list. Suspending last of all, once their positions are written.
    # P4.1 L2: a taken-out item's cards with them — their own tag first, their suspend in the same last request
    out_done, out_note_failures = {"tag": [], "suspend": []}, []
    out_sent = {"tag": [], "suspend": []}       # TF fix 4 (adversary S6): what was asked, for the store's record
    if out:
        out_done["tag"], out_note_failures = ankiconnect.add_tags(url, out.get("tag_notes"), out.get("tag"),
                                                                  chunk=_chunk_size(settings))
        untagged = {note_id for note_id, _reason in out_note_failures}
        if untagged:                            # a card is suspended only once its note carries the tag Put back
            out = dict(out, suspend=[card_id for card_id in out.get("suspend") or []    # finds it by (TF fix 4)
                                     if (out.get("note_of") or {}).get(card_id) not in untagged])
        out_sent = {"tag": list(out.get("tag_notes") or []), "suspend": list(out.get("suspend") or [])}
    later_done, later_failures, later_note_failures = _apply_later(
        url, dict(later or {}, suspend=sorted(set((later or {}).get("suspend") or []) | set(out.get("suspend") or [])))
        if out else later, _chunk_size(settings))
    if out:
        gone = set(out.get("suspend") or [])
        out_done["suspend"] = [card_id for card_id in later_done["suspend"] if card_id in gone]
        later_done["suspend"] = [card_id for card_id in later_done["suspend"] if card_id not in gone]
        later_note_failures = list(later_note_failures) + list(out_note_failures)
    record_problem = None
    if later:                                   # FT K3: what landed, so only a suspend that did is ever undone
        try:
            first_touch.note(_language(settings), "reorder", profile, decks, landed=True, with_tag=later.get("tag"),
                             suspended=later_done["suspend"], tags={later.get("tag") or "": later_done["tag"]},
                             flags={card_id: [(later.get("flags") or {}).get(card_id, 0), unlisted.FLAG_PURPLE]
                                    for card_id in later_done["flag"]})
        except (OSError, ValueError) as e:      # C11: said — those suspends stay among the older changes offered
            record_problem = (f"Surasura couldn't note which cards it suspended ({e}): Put Anki back… offers them "
                              "with its older changes.")
    if out:                                     # P4.1 L2: the taken-out cards' suspends, journalled as §13's are
        try:
            first_touch.note(_language(settings), "reorder", profile, decks, landed=True, with_tag=out.get("tag"),
                             suspended=out_done["suspend"], tags={out.get("tag") or "": out_done["tag"]})
        except (OSError, ValueError) as e:
            record_problem = (f"Surasura couldn't note which cards it suspended ({e}): Put Anki back… offers them "
                              "with its older changes.")
    failures = list(failures) + later_failures
    note_failures = note_failures + later_note_failures + later_untag_failures

    if refresh:
        _refresh_anki(url)

    ok = not failures and not note_failures
    if ok and (run_id is not None or not automatic or acting or taking):
        # A run's own snapshot keeps in `after` the cards it wrote: one the re-check left (`left`) it never moved.
        sent = set(written)
        undo.mark_complete(_language(settings), run_id=run_id,
                           after=[pair for pair in writes if pair[0] in sent] if run_id is not None and left else None)
    if not failures:
        message = f"Reordered {len(written)} card{'' if len(written) == 1 else 's'}"
    else:
        message = (f"Reordered {len(written)} of {len(writes)} cards — {len(failures)} could not be "
                   "changed")
    message += _touchup_clause(notes_updated, tagged, applied.get("tag"), marker_tagged) + "."
    message += _labels_clause(labelled)
    message += _later_clause(later_done)
    if out_done["suspend"]:                     # P4.1 L2
        message += (f" Taken out of your order: suspended {len(out_done['suspend'])} "
                    f"card{'' if len(out_done['suspend']) == 1 else 's'}.")
    if returned:
        message += (f" Back on your list: unsuspended {len(returned)} card{'' if len(returned) == 1 else 's'} "
                    "Junban had set aside.")
    if left and job is not None and getattr(job, "anki_busy", False):
        message += (f" Anki was busy (syncing, or another operation), so {len(left)} "
                    f"card{'' if len(left) == 1 else 's'} wait for the next re-order.")
    elif left:
        message += (f" {len(left)} card{'' if len(left) == 1 else 's'} changed in Anki while Junban "
                    "worked and wait for the next re-order.")
    kind = (stats.get("numbering") or {}).get("kind") if job is not None else None
    if kind == spaced.FULL and written:         # 03 §2: the one full spacing is said, not hidden
        message = ("Spaced your new cards out again, so later moves are quick. "
                   if stats["numbering"].get("laid") else
                   "Spaced your new cards out once, so later moves are quick. ") + message
    elif kind == spaced.DENSE and written:      # 03 §2: the fallback is said too
        message += (" There was too little room below Anki's highest position to space them out, so they "
                    "were numbered one after another.")
    if failures or note_failures:
        message += " Your previous order is still saved, so you can restore it."
    return _report(ok, message, warnings=checks["warnings"] + _labels_warning(label_failures), decks=decks, stats=stats,
                   snapshot=snapshot, written=written, failures=failures,
                   notes_updated=notes_updated, tagged=tagged, note_failures=note_failures,
                   marker_tagged=marker_tagged, later=later_done,
                   **({"cards_out": _out_records(out, out_sent, profile)} if out else {}),    # P4.1 L2: `pins.record`
                   **({"cards_taken_out": len(out_done["suspend"])} if out_done["suspend"] else {}),   # (TF fix 10)
                   **({"returned": returned, "run": run_id} if run_id is not None or returned else {}),
                   **({"left": list(left) + [c for c in out_owed if c not in set(left)],     # (TF fix 6)
                       "numbering": stats.get("numbering")} if job is not None else {}),
                   **({"anki_busy": True} if job is not None and getattr(job, "anki_busy", False) else {}),
                   problems=([] if ok else
                             [reason for _id, reason in (list(failures) + note_failures)[:1]])
                   + ([record_problem] if record_problem else []))


# --- Try it on my cards (backlog onboarding, Sonic 2026-10-29; the lead's lean, PROVISIONAL) ----------------------- #
def try_front(settings, count=None, progress=None, wait=0.0, cancel=None, on_wait=None, job=None):
    """*Try it on my cards*: the plan's next `count` cards (`TRY_CARDS`) moved to the front of the scope's new
    cards — a real reorder of those cards alone, holding the Anki-write lock as `run` does, with the window's own
    snapshot (`undo.save(tried=)`), so *Undo the last reorder* puts them back exactly — then Anki's browser opened on
    the deck's new cards sorted by due (`ankiconnect.browse`), after the lock is let go. `job`: the window's (its
    preview's order, the sync rule's S1 before the write, as `run`). -> `run`'s report, plus `front` (the cards'
    ids, in order) and `browsed` ("sorted" / "plain" / None: not opened, `browse_problem` says why)."""
    held, problem = anki_connect.take_writer("順 try it", _url(settings), wait, cancel, on_wait)
    if held is None:
        return _report(False, "Junban did not make any changes.", problems=[problem], busy=True)
    with held:
        report = _try_front(settings, TRY_CARDS if count is None else count, progress, job)
    if report.get("written"):
        from app import anki_sync_rule
        anki_sync_rule.wrote(True, settings)           # tomorrow's first cards changed: S3's clock, as `run`
    front = report.get("front") or []
    report["browsed"] = None
    if report.get("ok") and front:
        try:
            report["browsed"] = ankiconnect.browse(_url(settings), browse_query(report.get("decks")), front)
        except AnkiError as e:
            report["browse_problem"] = str(e)
    return report


def browse_query(decks):
    """The scope's new cards, as `new_card_query` finds them (every deck of an All-decks scope)."""
    queries = [ankiconnect.new_card_query(deck) for deck in decks or ()]
    return queries[0] if len(queries) == 1 else " OR ".join(f"({query})" for query in queries)


def _try_front(settings, count, progress=None, job=None):
    """`try_front`'s body, holding the lock: `_run`'s preflight and refusals, the plan read as the preview reads it,
    `plan_try_front`, then FT's order file and the snapshot BEFORE the first write (I3), the positions, the refresh.
    Positions only: nothing tagged, flagged, suspended or filled."""
    checks = preflight(settings, probe=job.probe if job is not None else None)
    if not checks["ok"]:
        return _report(False, "Junban did not make any changes.", problems=checks["problems"],
                       warnings=checks["warnings"], decks=checks["decks"])
    url, decks, language = _url(settings), checks["decks"], _language(settings)
    previous = undo.load(language)
    if previous and previous.get("complete") is False:
        return _unfinished_refusal(checks, decks)
    unfinished = undo.unfinished(language, "reorder")
    if unfinished is not None:
        return _report(False, "Junban did not make any changes.",
                       problems=[f"An automatic reorder ({unfinished}) did not finish, and its saved order is the "
                                 "only way back from it. Press Undo the last reorder first, then reorder again."],
                       warnings=checks["warnings"], decks=decks, unfinished=unfinished, restore_first=True)
    try:
        _writes, stats = _plan_scope(settings, decks, url, job,
                                     front=None if job is None else _front(job, checks.get("per_day")))
    except (AnkiError, spaced.SpacedError) as e:
        return _report(False, "Junban did not make any changes.", problems=[str(e)], warnings=checks["warnings"],
                       decks=decks)
    if stats.get("problems"):
        return _report(False, "Junban did not make any changes.", problems=list(stats["problems"]),
                       warnings=checks["warnings"], decks=decks)
    if stats.get("empty_list"):
        return _report(True, EMPTY_LIST, warnings=checks["warnings"], decks=decks, stats=stats, empty_list=True)
    order = [(row.card_id, row.due) for row in stats.get("order") or []]
    try:
        writes, front = plan_try_front(order, count)
    except ValueError as e:
        return _report(False, "Junban did not make any changes.", problems=[str(e)], warnings=checks["warnings"],
                       decks=decks, stats=stats)
    if not front:
        return _report(True, "There are no new cards in this scope.", warnings=checks["warnings"], decks=decks,
                       stats=stats)
    if not writes:
        n = len(front)
        return _report(True, f"Your next {n} card{'' if n == 1 else 's'} {'is' if n == 1 else 'are'} already "
                             "first — nothing to change.", warnings=checks["warnings"], decks=decks, stats=stats,
                       front=front)

    # Its way back: the cards it moves at their numbers now — and an earlier Try's cards still where that one put
    # them (else this snapshot, taking the window's place, would lose their way back) — each at its number from
    # before any Try (`carry_forward_tried`); `tried`: where each is after this one.
    current, moved = dict(order), dict(writes)
    earlier = (previous or {}).get("tried") or {}
    kept = [card_id for card_id, due in order if card_id not in moved and earlier.get(str(card_id)) == due]
    touched = list(moved) + kept
    original = undo.carry_forward_tried(previous, [(card_id, current[card_id]) for card_id in touched])
    try:
        profile = _keep_order(settings, decks, order, job, url)     # FT D2: before Surasura's first write, once
        snapshot = undo.save(original, decks, language=language, profile=profile, mode=_scope_mode(settings),
                             tried=[(card_id, moved.get(card_id, current[card_id])) for card_id in touched])
    except OSError as e:
        return _report(False, "Junban did not make any changes.",
                       problems=[f"Could not save the undo snapshot, so nothing was changed ({e})."],
                       warnings=checks["warnings"], decks=decks, stats=stats)
    undo.end_baseline(language)                         # a manual run ends today's baseline (03 §5)
    if job is not None and profile != "":               # S1: the session's first write syncs first, as `run`'s
        from app import anki_sync_rule
        anki_sync_rule.before_write(url, locked=True, profile=profile)
    # Each request's cards read again just before it (`set_due_checked`, I1): one studied meanwhile — a review the
    # sync above just brought in — or moved since the plan's read is left alone, never written blind.
    size = _chunk_size(settings)
    ordered = sorted(writes, key=lambda pair: (pair[1], pair[0]))
    written, failures, left = ankiconnect.set_due_checked(
        url, [ordered[start:start + size] for start in range(0, len(ordered), size)], current, progress=progress)
    _refresh_anki(url)
    ok = not failures
    if ok:
        undo.mark_complete(language)
    n = len(front)
    if ok:
        message = f"Moved your next {n} card{'' if n == 1 else 's'} to the front"
        others = len([card_id for card_id in written if card_id not in set(front)])
        if others:
            message += (f" ({others} card{'' if others == 1 else 's'} that held the first places took "
                        f"{'its' if others == 1 else 'their'} places)")
        message += ". Undo the last reorder puts them back exactly."
        if left:
            message += (f" {len(left)} card{'' if len(left) == 1 else 's'} changed in Anki meanwhile and "
                        f"{'was' if len(left) == 1 else 'were'} left where {'it is' if len(left) == 1 else 'they are'}.")
    else:
        message = (f"Moved {len(written)} of {len(writes)} cards — {len(failures)} could not be changed. "
                   "Undo the last reorder puts back the ones that moved.")
    return _report(ok, message, warnings=checks["warnings"], decks=decks, stats=stats, snapshot=snapshot,
                   written=written, failures=failures, left=list(left), front=front, tried=True,
                   problems=[] if ok else [reason for _id, reason in failures[:1]])


def _show_tags(settings):
    """#50 (LF4-3): does this run label each card with the show it's for? Off for positions only (`auto._POSITIONS_ONLY`
    lays `junban_show_tags: False` over the settings: `surasura-cli junban --auto`, an automatic re-order whose
    actions are off)."""
    return settings.get("junban_show_tags", True) is not False


def _labels_warning(failures):
    """#50 (round 2 B4): the show labels Anki didn't take, as one warning line ([] for none)."""
    if not failures:
        return []
    count = len({note for note, _why in failures})
    return [f"{count} card{'' if count == 1 else 's'} kept an old show label ({failures[0][1]}); the next re-order "
            "tries again."]


def _labels_clause(labelled):
    """#50: what the show labels did, in a few words ("" for none)."""
    if not labelled:
        return ""
    return f" Labelled {labelled} card{'' if labelled == 1 else 's'} with the show {'it is' if labelled == 1 else 'they are'} for."


def _keep_order(settings, decks, in_scope, job, url, map_read=False):
    """FT D2: the scope's order before Surasura's first write to it, kept once (`first_touch.keep_order`) — every
    unsuspended new card in scope (`in_scope`, the whole scope for Connect's runs too) -> the open profile, which the
    run's journal lines carry (K1) and S1 is handed (C7): from the job's warm card map when this run read it
    (`map_read`, C4: a map held over from another run may name another profile), else one `getActiveProfile`.
    Raises `OSError`: the run then writes nothing."""
    card_map = job.cards if job is not None and map_read else None
    profile = (first_touch.profile_name(card_map.key[0]) if card_map is not None and card_map.key
               else first_touch.open_profile(url))
    first_touch.keep_order(_language(settings), decks, _scope_mode(settings), in_scope, profile=profile)
    return profile


def _put_back_since(settings):
    """FT C1 (FT-1): an automatic job's settings were read before it waited for the Anki-write lock, and a put-back
    holding the lock meanwhile may have cleared the recorded (language, deck) pair. Read again now the job holds it:
    the pair it was handed gone from the file, or naming another deck -> the line the host shows (it stands aside);
    else None. A job handed no pair (2.x's automatic step) goes on as ever, and so does one whose file can't be
    read just now."""
    from app import replan_preview, settings_manager
    deck = str((settings or {}).get(replan_preview.DECK) or "").strip()
    if not deck:
        return None
    try:
        fresh = settings_manager.load_settings(strict=True)
    except Exception:
        return None
    if str(fresh.get(replan_preview.DECK) or "").strip() == deck:
        return None
    return (replan_preview.stands_aside(fresh, _language(settings))
            or f"Anki's deck {deck} was put back the way it was: pick it in 順 to re-order it again")


def _same_scope(snapshot, decks, settings):
    """`snapshot` was saved for this run's deck(s) and scope mode (a cut run that may be taken over)."""
    return (undo.normalize_scope(snapshot.get("scope")) == undo.normalize_scope(decks)
            and (snapshot.get("mode") == "all") == (_scope_mode(settings) == "all"))


def _finish_cut(settings, cut, automatic, decks, stats, connect_cuts=(), previous=None, window_snapshot=None,
                went_on=None):
    """Disc-T1: a run you start that takes over a cut automatic run and finds nothing left to write still ends it —
    a snapshot of its own takes the cut run over, as one with writes does (every card in scope where it is, the cut
    run's originals winning), saved complete and `finished_automatic`, and today's baseline ended. Newest, it is what
    Undo offers: never a baseline a positions-only job wrote after the cut (the adversary's MUST: that one knows
    nothing of the cut run's tags, flags and suspends). Not saved: the cut snapshot stays unfinished, as it was.
    Junban-X: Connect's cut runs it takes over (`connect_cuts`) the same way, each then marked taken over; and, as the
    writes path does, the fields' true originals of the window's snapshot it replaces (`previous`) and Try it's numbers
    from before (`window_snapshot`) carried."""
    if (cut is None and not connect_cuts) or automatic:
        return
    language = _language(settings)
    try:
        held = _held_files(language, connect_cuts)
        pairs = undo.carry_forward_tried(window_snapshot, [(row.card_id, row.due) for row in stats.get("order") or []])
        undo.save(pairs, decks, language=language, mode=_scope_mode(settings),
                  fields=_carried_fields([saved for _cut_id, saved in connect_cuts] + [previous or cut], None),
                  cut=[cut, went_on] + [saved for _cut_id, saved in connect_cuts], finished_automatic=True)
    except OSError:
        return
    for cut_id, _saved in connect_cuts:         # one not marked: every file back as it was, nothing changed (as the
        if not undo.mark_complete(language, run_id=cut_id, taken_over=True):           # writes path, round 3)
            _put_back_files(held)
            return
    undo.end_baseline(language)
    undo.mark_complete(language)


def _connect_cuts(settings, decks):
    """Junban-X (Sonic 2026-11-13: "a manual would be a priority BUT if the data until that point isn't prepped than the
    manual isn't ready to run yet"): the runs of Connect's a run you start takes over -> `(taken, blocked)`: `taken`
    `[(run id, its snapshot)]`, newest first; `blocked` None, or — when one can't be taken, its record not complete —
    `{"held": [...], "elsewhere": [...], "overlapping": [...]}`, the run ids of the files that can't be read just now
    (`undo.runs`' unreadable) and of the unfinished runs for another deck or scope mode, whose way back this run's
    snapshot wouldn't hold — `elsewhere` those sharing no card with this run's decks (`_apart`), whose put-back leaves
    this deck's preview as it is (Junban-X2's one press), `overlapping` the rest (all decks, a parent or a subdeck). Every unfinished one, never only the newest (an older one left would put its half writes back), and every
    finished run of this deck newer than the oldest of them, neither put back nor taken over yet (Connect's own next
    runs go on past a cut one): one Undo then puts back the deck from before them all, never a mix of the two."""
    runs = undo.runs(_language(settings), "reorder")
    cuts = [index for index, (_cut_id, saved) in enumerate(runs) if saved.get("complete") is False]
    taken, held, elsewhere, overlapping = [], [], [], []
    for cut_id, saved in runs[:max(cuts) + 1] if cuts else ():
        if saved.get("complete") is False:
            if saved.get("unreadable") or not isinstance(saved.get("cards"), dict):
                held.append(cut_id)
                continue
            if not _same_scope(saved, decks, settings):
                (elsewhere if _apart(saved, decks, settings) else overlapping).append(cut_id)
                continue
        elif (saved.get("restored_at") or saved.get("taken_over_at") or not isinstance(saved.get("cards"), dict)
              or not _same_scope(saved, decks, settings)):
            continue                    # put back, taken over, or another deck's: nothing of this deck to go back past
        taken.append((cut_id, saved))
    blocked = held or elsewhere or overlapping
    return taken, ({"held": held, "elsewhere": elsewhere, "overlapping": overlapping} if blocked else None)


# Junban-X2: how long a run you start waits before it reads a held run's file once more (Sonic 2026-11-13: "a quiet
# retry a second later, then the same ask")
HELD_RETRY = 1.0
# Junban-X2: what a run you start says when only other decks' stopped runs are in its way (PROVISIONAL)
UNFINISHED_ELSEWHERE = "An automatic reorder of {decks} stopped part way. Put it back first, then reorder."


def _held_wait():
    time.sleep(HELD_RETRY)


def _apart(saved, decks, settings):
    """Do this run of Connect's and a run on `decks` share no card? Never across All decks; a deck's search holds its
    subdecks (`new_card_query`), so a parent or a subdeck of one of `decks` is not apart."""
    if saved.get("mode") == "all" or _scope_mode(settings) == "all":
        return False
    for one in undo.normalize_scope(saved.get("scope")):
        for other in undo.normalize_scope(decks):
            if one == other or one.startswith(other + "::") or other.startswith(one + "::"):
                return False
    return bool(undo.normalize_scope(saved.get("scope")))


def _reaches(settings, url, snapshot):
    """Junban-X2 (adversaries 1 and 2): does a card this run of Connect's changed sit in the window's deck (or a
    subdeck) now — moved there since it stopped? -> "" when none does, else the line that says so (or why it can't be
    told). Read from Anki (`cardsInfo`), no write; raises `AnkiError`."""
    decks, problems = _resolve_decks(settings, url)
    if problems:
        return problems[0]
    if _scope_mode(settings) == "all":
        return PUT_BACK_REACHES
    ids = {int(card_id) for card_id in snapshot.get("cards") or {} if str(card_id).isdigit()}
    ids |= set(undo.restore_suspended(snapshot)) | set(undo.restore_unsuspended(snapshot))
    rows = ankiconnect.cards_info(url, sorted(ids)) if ids else []
    inside = any(str(row.get("deckName") or "") == deck or str(row.get("deckName") or "").startswith(deck + "::")
                 for row in rows for deck in decks)
    return PUT_BACK_REACHES if inside else ""


PUT_BACK_REACHES = ("Some of that reorder's cards are in this deck now. Undo the last reorder, then preview "
                    "again.")                                                                      # PROVISIONAL


def _decks_named(settings, run_ids):
    """The decks of these runs of Connect's, for a sentence: "Kanji", "Kanji and Mining", or "all decks"."""
    names = []
    for run_id in run_ids:
        saved = undo.load(_language(settings), run_id=run_id) or {}
        for name in (["all decks"] if saved.get("mode") == "all" else undo.normalize_scope(saved.get("scope"))):
            if name not in names:
                names.append(name)
    if not names:
        return "another deck"
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _went_on(previous, connect_cuts, decks, settings):
    """The window's snapshot of an automatic job that went on past the oldest of Connect's cut runs a run you start
    takes over (it took over a newer one, lead 2026-11-07), for this deck -> that snapshot, to take over with them; else
    None. Its way back (and that of the run it took over) is in it alone: replaced, one Undo would leave its cards
    where it put them (round 2's SHOULD 3). A snapshot older than the cut run is your last reorder: replaced as ever."""
    cuts = [saved.get("written_at") or "" for _cut_id, saved in connect_cuts if saved.get("complete") is False]
    if (not previous or previous.get("automatic") is not True or not cuts or not _same_scope(previous, decks, settings)
            or (previous.get("written_at") or "") < min(cuts)):    # the same second: taken, never left half
        return None
    return previous


def _held_files(language, connect_cuts):
    """The window's snapshot file and each run's to be taken over, as they are on disk now (`{path: bytes or None}`), so
    a take-over that can't mark a run puts them back (`_put_back_files`) and changes nothing. Raises `OSError`."""
    held = {}
    for path in [undo.snapshot_path(language)] + [undo.snapshot_path(language, run_id=cut_id)
                                                  for cut_id, _saved in connect_cuts]:
        try:
            with open(path, "rb") as handle:
                held[path] = handle.read()
        except FileNotFoundError:
            held[path] = None
    return held


def _put_back_files(held):
    """`_held_files`' files back as they were (one that wasn't there removed), each atomically; best effort."""
    for path, data in held.items():
        try:
            if data is None:
                if os.path.exists(path):
                    os.remove(path)
                continue
            with open(path + ".tmp", "wb") as handle:
                handle.write(data)
            os.replace(path + ".tmp", path)
        except OSError:
            pass


def _carried_fields(snapshots, fields):
    """`fields` for a snapshot that replaces or takes over `snapshots` (Connect's cut runs, the window's last one): each
    field's true original carried back through every one of them, newest first, so the oldest's wins — one that
    carried an earlier one first would stop at a value Surasura wrote (the adversary's BLOCKER, Junban-X). Two written
    in the same second keep the order handed in: the window's last snapshot goes last, as the older (round 2's NIT)."""
    for earlier in sorted((snapshot for snapshot in snapshots if snapshot),
                          key=lambda snapshot: snapshot.get("written_at") or "", reverse=True):
        fields = undo.carry_forward_fields(earlier, fields)
    return fields


def _unfinished_refusal(checks, decks, stats=None):
    """The window's snapshot is unfinished and only its Restore may go on from here (I3): nothing written.
    `restore_first`: the window's re-order host says where that Restore is."""
    return _report(False, "Junban did not make any changes.",
                   problems=["The last reorder did not finish, and its saved order is the only "
                             "way back to how your cards were. Press Undo the last reorder "
                             "first, then reorder again."],
                   warnings=checks["warnings"], decks=decks, restore_first=True,
                   **({"stats": stats} if stats is not None else {}))


def _has_touchups(touchups):
    """Will the run write a touch-up (a field, its tag, a marker tag)?"""
    touchups = touchups or {}
    return bool(touchups.get("fields") or touchups.get("tags") or touchups.get("marker_tags"))


def _still_new(url, later, touchups=False):
    """The cards off the list as planned (§13), less any no longer new or already suspended — read once, after the
    positions and just before the actions (3.0, Haya's G2b): a card studied on the phone meanwhile (the session's sync
    brought it) is never suspended, nor one you suspended yourself recorded as Junban's. Returns `later` itself when
    every card is still as planned, else the plan narrowed — a note keeps its tag only while one of its cards does.

    In the same request, `guiReviewActive` (04 §6: never while you review — `stop_if` is asked before each position
    request, never after the last); with no card to read it is asked alone while `touchups` are still to write, and
    with nothing at all to write nothing is asked. A review, or Anki not answering: `None` — nothing is acted on this
    run, not even the touch-ups."""
    cards = list((later or {}).get("cards") or [])
    reading = bool(unlisted.has_work(later) and cards)
    if not reading and not touchups:
        return later
    try:
        if not reading:
            return None if ankiconnect.invoke("guiReviewActive", url, timeout=5) is True else later
        actions = [{"action": "cardsInfo", "params": {"cards": batch}} for batch in ankiconnect._chunks(cards, 250)]
        replies = ankiconnect.multi(actions + [{"action": "guiReviewActive"}], url)
    except AnkiError:
        return None
    if not isinstance(replies, list) or len(replies) != len(actions) + 1:
        return None
    review = replies[-1]
    if isinstance(review, dict) and review.get("error") is None and review.get("result") is True:
        return None
    rows = []
    for reply in replies[:-1]:
        if not isinstance(reply, dict) or reply.get("error") is not None or not isinstance(reply.get("result"), list):
            return None
        rows.extend(row for row in reply["result"] if isinstance(row, dict) and row)
    still = _new_card_ids(rows)
    if still >= set(cards):
        return later
    note_of = {card_id: note_id for card_id, note_id in (later.get("note_of") or {}).items() if card_id in still}
    kept_notes = set(note_of.values())
    narrowed = dict(later, cards=[card_id for card_id in cards if card_id in still], note_of=note_of,
                    tag_notes=[note_id for note_id in later.get("tag_notes") or [] if note_id in kept_notes],
                    flags={card_id: flag for card_id, flag in (later.get("flags") or {}).items() if card_id in still},
                    suspend=[card_id for card_id in later.get("suspend") or [] if card_id in still])
    narrowed["counts"] = dict(later.get("counts") or {}, cards=len(narrowed["cards"]), tag=len(narrowed["tag_notes"]),
                              flag=len(narrowed["flags"]), suspend=len(narrowed["suspend"]))
    return narrowed


def _apply_marker_tags(action, url, marker_tags, chunk):
    """Add (or remove) every WP-N marker tag. Returns `(note_ids, failures)`.

    One call per tag, not one per note: `addTags`/`removeTags` take one tag for a batch of notes,
    and there are at most three tags. Sorted, so two identical runs hit the wire identically.
    """
    touched, failures = [], []
    for name in sorted((marker_tags or {}).keys()):
        done, failed = action(url, (marker_tags or {})[name], name, chunk=chunk)
        touched.extend(done)
        failures.extend(failed)
    return sorted(set(touched)), failures


def _with_later_tag(marker_tags, later):
    """The snapshot's `marker_tags` with §13's `Surasura::later` beside the marker tags — it is one
    more tag on one more subset of notes, and restore already takes exactly that back off."""
    merged = dict(marker_tags or {})
    if (later or {}).get("tag") and later.get("tag_notes"):
        merged[later["tag"]] = list(later["tag_notes"])
    return merged


def _apply_later(url, later, chunk):
    """Tag, flag purple and suspend the cards not on the list, as planned (§13). Returns
    `(done, card_failures, note_failures)`; `done` is `{"tag": [nid], "flag": [cid], "suspend": [cid]}`.
    Suspension goes last: a card is only suspended once everything else about it has landed."""
    done = {"tag": [], "flag": [], "suspend": []}
    if not later:
        return done, [], []
    done["tag"], note_failures = ankiconnect.add_tags(url, later.get("tag_notes"), later.get("tag"),
                                                      chunk=chunk)
    done["flag"], card_failures = ankiconnect.set_flags(
        url, [(card_id, unlisted.FLAG_PURPLE) for card_id in sorted(later.get("flags") or {})],
        chunk=chunk)
    done["suspend"], suspend_failures = ankiconnect.suspend(url, later.get("suspend"), chunk=chunk)
    return done, card_failures + suspend_failures, note_failures


# --- P4.1 L2: *Take its new cards out* (05 §5.7, D14) — the record for the store, and Put back ------------------- #
# What a run's Put back left owed, when it ran none (TF fix 6): see `_put_back_out`.
_NOTHING_PUT_BACK = {"restored": [], "unsuspended": [], "left": [], "failures": [], "note_failures": [], "found": []}


def _out_records(out, sent, profile=None):
    """The store's `anki_changes` rows for what the run asked Anki for (`pins.out_records`), in the open profile."""
    from modules.junban import pins as pin_feed
    return pin_feed.out_records(out, sent, profile=profile)


def _put_back_out(url, settings, decks, read):
    """T-5, with the review's fixes (TF fixes 4, 5, 7, 9): before the plan, so this run places them, the items back in
    the learning order (*Put back*, *Put them back in the order*, an undo, a pin) have what Junban's out tag still
    marks restored. `read`: the run's `pins.read_out`. -> `{"restored": [record ids the caller closes], "left": [card
    ids still owed: the next run tries again], "failures": [(card id, reason)], "note_failures": [(note id, reason)],
    "found": [records for the store]}`.

      * **Per open record of this Anki profile** (TF fix 5, D31: a card id is one collection's — a record of another
        profile waits, open, for that one): its cards still suspended and new **on a note that still carries its
        tag** are unsuspended (adversary S1: a card a Restore or *Put Anki back…* already gave back — the undo took the
        tag off — and you then suspended yourself stays suspended; one you studied or deleted is left as it is).
      * **A suspend no record names** (adversary S6, N6: a store write that failed, a run that ended before the record):
        a note carrying the out tag with a suspended new card, named by no open record, is put back when an item in
        the learning order claims it (T-3), recorded now (`found`) for the out items that claim it, else (a removed
        item's, a tag you put there) left alone. Looked for only while something is out or owed back (`read`), so a
        library that never took anything out sends Anki nothing more.
      * **The tag** comes off the records' tagged notes still carrying it and the found notes put back — but stays on
        a note while a card of an item still out stays suspended on it (TF fix 7: a note two items claim).
      * **Never while you review** (TF fix 9): `guiReviewActive` in the same request as the cards' read (`_still_new`'s
        way); a review, or Anki not answering, restores nothing and keeps the records open (`left`). What landed is
        journalled as a restore is (FT D4), a request that failed part way too (`finally`)."""
    from modules.junban import pins as pin_feed
    result = {key: [] for key in _NOTHING_PUT_BACK}
    if not read:                        # nothing out, nothing owed back: not one request more than before
        return result
    language = _language(settings)
    chunk = _chunk_size(settings)

    def after(row):
        return row.get("after") if isinstance(row.get("after"), dict) else {}

    def ints(values):
        return [value for value in values or () if _is_int(value)]

    def answers(replies, count):
        """Each reply's result, or None when the request isn't what was asked (N4) or one of them failed."""
        if not isinstance(replies, list) or len(replies) != count:
            return None
        if any(not isinstance(reply, dict) or reply.get("error") is not None for reply in replies):
            return None
        return [reply.get("result") for reply in replies]

    back, held = list(read.get("back") or []), list(read.get("held") or [])
    current = unlisted.out_tag(touchup.options(settings).get("tag"))
    tags = sorted({current} | {after(row).get("tag") for row in back + held if after(row).get("tag")})

    def owed(rows):
        result["left"] = sorted({card for row in rows for card in ints(after(row).get("suspended"))})
        return result
    try:
        got = answers(ankiconnect.multi(
            [{"action": "findNotes", "params": {"query": f'"tag:{ankiconnect.escape_query(tag)}" is:suspended is:new'}}
             for tag in tags] + [{"action": "getActiveProfile"}], url), len(tags) + 1)
    except AnkiError:
        got = None
    if got is None:
        return owed(back)
    profile = first_touch.profile_name(got[-1])
    mine = [row for row in back if after(row).get("profile") in (None, profile or None)]
    named = {note for row in back + held for note in ints(row.get("notes"))}
    suspects = sorted({note for found in got[:-1] if isinstance(found, list) for note in ints(found)} - named)
    if not mine and not suspects:
        return result

    try:
        found = answers(ankiconnect.multi(
            [{"action": "findCards", "params": {"query": f"nid:{','.join(str(n) for n in part)} is:suspended is:new"}}
             for part in ankiconnect._chunks(suspects, 250)], url),
            len(range(0, len(suspects), 250))) if suspects else []
    except AnkiError:
        found = None
    if found is None:
        return owed(mine)
    suspect_cards = sorted({card for part in found if isinstance(part, list) for card in ints(part)})
    candidates = {note for row in mine for note in ints(after(row).get("tagged"))} | set(suspects)
    guard = {card for row in held if set(ints(row.get("notes"))) & candidates
             for card in ints(after(row).get("suspended"))}
    wanted = sorted({card for row in mine for card in ints(after(row).get("suspended"))} | set(suspect_cards) | guard)
    batches = list(ankiconnect._chunks(wanted, 250))
    try:
        got = answers(ankiconnect.multi([{"action": "cardsInfo", "params": {"cards": batch}} for batch in batches]
                                        + [{"action": "guiReviewActive"}], url), len(batches) + 1)
        if got is not None and got[-1] is not True:
            info = {row.get("cardId"): row for part in got[:-1] if isinstance(part, list)
                    for row in part if isinstance(row, dict) and row}
            notes = sorted({row.get("note") for row in info.values() if _is_int(row.get("note"))} | candidates)
            read_notes = answers(ankiconnect.multi(
                [{"action": "notesInfo", "params": {"notes": part}} for part in ankiconnect._chunks(notes, 250)],
                url), len(range(0, len(notes), 250))) if notes else []
        else:
            read_notes = None
    except AnkiError:
        read_notes = None
    if read_notes is None:              # a review, or Anki not answering: nothing restored blind, nothing closed
        return owed(mine)
    tags_of, misc_of = {}, {}
    for part in read_notes:
        for note in part if isinstance(part, list) else ():
            if isinstance(note, dict) and _is_int(note.get("noteId")):
                tags_of[note["noteId"]] = note.get("tags") or []
                misc = (note.get("fields") or {}).get("MiscInfo")
                misc_of[note["noteId"]] = misc.get("value") if isinstance(misc, dict) else misc

    def carries(note, tag):
        return bool(tag) and touchup.carries_tag(tags_of.get(note) or [], tag)

    def suspended_new(card):
        row = info.get(card)
        return bool(row) and row.get("type") == 0 and row.get("queue") == -1

    restore, untag = set(), {}
    for row in mine:
        tag = after(row).get("tag") or current
        restore |= {card for card in ints(after(row).get("suspended"))
                    if suspended_new(card) and carries(info[card].get("note"), tag)}
        for note in ints(after(row).get("tagged")):
            if carries(note, tag):
                untag.setdefault(tag, set()).add(note)
    claim, found_of = None, {}
    for card in suspect_cards:
        note = (info.get(card) or {}).get("note")
        tag = next((t for t in tags if carries(note, t)), None)
        if tag is None or not suspended_new(card):
            continue
        if claim is None:
            claim = pin_feed.claimer(read if "kept_notes" in read else pin_feed.read_out(language, claims=True))
        who = claim(note, misc_of.get(note))
        if who == "kept":
            restore.add(card)
            untag.setdefault(tag, set()).add(note)
        for item_id in who if who != "kept" else ():
            entry = found_of.setdefault((item_id, tag), {"cards": set(), "notes": set()})
            entry["cards"].add(card)
            entry["notes"].add(note)
    staying = {info[card].get("note") for card in guard if card not in restore and suspended_new(card)}
    for tag in untag:
        untag[tag] -= staying

    unsuspended, untagged = [], {}
    try:
        if restore:
            unsuspended, failures = ankiconnect.unsuspend(url, sorted(restore), chunk=chunk)
            result["failures"] += failures
        for tag in sorted(untag):
            if untag[tag]:
                untagged[tag], failures = ankiconnect.remove_tags(url, sorted(untag[tag]), tag, chunk=chunk)
                result["note_failures"] += failures
    finally:                            # TF fix 9 (H1): whatever landed is journalled, a request that raised too
        if unsuspended or any(untagged.values()):
            first_touch.noted(language, "reorder", profile, decks, unsuspended=unsuspended, tags_off=untagged)
    result["unsuspended"] = list(unsuspended)
    done_cards = set(unsuspended)
    done_notes = {tag: set(notes) for tag, notes in untagged.items()}
    for row in mine:
        tag = after(row).get("tag") or current
        cards = ints(after(row).get("suspended"))
        if (all(card in done_cards or card not in restore for card in cards)
                and all(note in done_notes.get(tag, ()) or note in staying or not carries(note, tag)
                        for note in ints(after(row).get("tagged")))):
            result["restored"].append(row["id"])
        else:
            result["left"] += [card for card in cards if card not in done_cards]
    result["left"] = sorted(set(result["left"]))
    for (item_id, tag), entry in sorted(found_of.items()):
        notes = sorted(entry["notes"])
        result["found"].append((item_id, pin_feed.OUT_ACTION, notes, {"queue": 0, "tagged": []},
                                dict({"queue": -1, "suspended": sorted(entry["cards"]), "tag": tag, "tagged": notes,
                                      "found": True}, **({"profile": profile} if profile else {}))))
    return result


def _put_back_owed(report, owed):
    """TF fix 6 (adversary S3): what this run's Put back left owed rides its report as §13's does — an unsuspend or a
    tag that failed in `failures` / `note_failures` (the run is then not `ok`), the cards of a record left open in
    `left` — so neither caller records the plan as written (`record_planned`) and the next look tries again; and the
    records it made for suspends no record named (`found`) join the run's `cards_out`, for `pins.record`."""
    if not owed:
        return
    if owed.get("unsuspended"):                 # TF fix 10: the host's line names it
        n = len(owed["unsuspended"])
        report["cards_put_back"] = n
        report["message"] = (str(report.get("message") or "") + f" Put back in your order: unsuspended {n} "
                             f"card{'' if n == 1 else 's'} taken out of it.").strip()
    if owed.get("found"):
        report["cards_out"] = list(report.get("cards_out") or []) + list(owed["found"])
    if owed.get("left"):
        left = list(report.get("left") or [])
        report["left"] = left + [card for card in owed["left"] if card not in set(left)]
    failed = list(owed.get("failures") or []) + list(owed.get("note_failures") or [])
    if failed:
        report["failures"] = list(report.get("failures") or []) + list(owed.get("failures") or [])
        report["note_failures"] = list(report.get("note_failures") or []) + list(owed.get("note_failures") or [])
        report["ok"] = False
        report["problems"] = list(report.get("problems") or []) + [
            f"Putting back the cards taken out of your order didn't finish ({failed[0][1]}): the next re-order tries "
            "again."]
# --- end P4.1 L2 ---


def _later_clause(done):
    """" Not on your list: tagged 40 notes 'Surasura::later', flagged 52 cards purple and suspended
    52." — or "" when nothing was done to them."""
    parts = []
    if done.get("tag"):
        parts.append(f"tagged {len(done['tag'])} note{'' if len(done['tag']) == 1 else 's'}")
    if done.get("flag"):
        parts.append(f"flagged {len(done['flag'])} card{'' if len(done['flag']) == 1 else 's'} purple")
    if done.get("suspend"):
        parts.append(f"suspended {len(done['suspend'])} card{'' if len(done['suspend']) == 1 else 's'}")
    if not parts:
        return ""
    return " Not on your list: " + ", ".join(parts[:-1] + [("and " if len(parts) > 1 else "") + parts[-1]]) + "."


def _touchup_clause(notes_updated, tagged, tag, marker_tagged=None):
    """" and tagged 47 notes" — the half of the sentence WP-L adds, or "" when nothing was touched.

    Written as a clause of the SAME sentence as the move on purpose: the preview is the only
    confirmation the user gets, and "it will reorder" followed elsewhere by "it will also edit your
    notes" is two claims they can read one of.
    """
    parts = []
    if notes_updated:
        parts.append(f"updated {len(notes_updated)} note{'' if len(notes_updated) == 1 else 's'}")
    if tagged:
        parts.append(f"tagged {len(tagged)} note{'' if len(tagged) == 1 else 's'} '{tag}'")
    if marker_tagged:
        # Named separately from the plain tag, because they answer different questions: one says
        # "Surasura moved this", the marker says which of ✦ / ⚖ / 📖 the word carries.
        parts.append(f"marked {len(marker_tagged)} note{'' if len(marker_tagged) == 1 else 's'}")
    if not parts:
        return ""
    return " and " + " and ".join(parts)


def _is_int(value):
    """True only for a genuine `int` — `True` is an `int` in Python, and a mock is neither."""
    return isinstance(value, int) and not isinstance(value, bool)


def _new_card_ids(rows):
    """The ids, out of raw `cardsInfo` rows, of the cards that are still genuinely new.

    The same belt-and-braces check the planner makes, for the same reason: `is:new` is a string
    interpreted by Anki's search parser and this is not. It matters even more on a restore — a card
    studied since the snapshot was taken is a review card now, and writing a queue position onto a
    review card silently reschedules it to a garbage date.
    """
    return {row.get("cardId") for row in rows
            if _is_int(row.get("cardId")) and row.get("type") == 0 and row.get("queue") == 0
            and _is_int(row.get("type")) and _is_int(row.get("queue"))}


def restore(settings, progress=None, wait=0.0, cancel=None, on_wait=None, confirmed=None, run=None):
    """`_restore`, holding the Anki-write lock (E1.4 §W) as `run` does. `confirmed` is the saved time
    (`written_at`) of the snapshot the user said yes to: after a wait, a snapshot on disk that is no
    longer that one (the writer it waited for saved a newer one) is refused. `run`: the id of one of
    Connect's unfinished runs the user said yes to (the window names it, P1.4) — exactly that run is put
    back, and nothing once it isn't the unfinished one any more; with `confirmed`, an unfinished run
    that turned up meanwhile is never put back in the window's place."""
    language = _language(settings)
    if run is not None:
        changed = lambda: undo.unfinished(language, "reorder") != run
    else:
        changed = None if confirmed is None else (
            lambda: (undo.restorable(language, _restore_scope(settings)) or {}).get("written_at") != confirmed)
    held, problem = anki_connect.take_writer("順 restore", _url(settings), wait, cancel, on_wait,
                                             changed=changed)
    if held is None:
        return _report(False, "Nothing was restored.", problems=[problem], busy=True)
    with held:
        return _restore(settings, progress, asked=run if run is not None else (None if confirmed is None else ""))


def _restore(settings, progress=None, asked=None):
    """Put the scope back where the saved snapshot says it was.

    Replays `{cardId: due}` through the same writer, so the way back is the same code path as the
    way there. Refuses — rather than half-applying — when the snapshot was taken for a different
    scope: those positions belong to another deck's queue, and writing them here would be a second
    mess on top of the first.

    Cards that are no longer new are skipped, not written: the user has studied them since, and
    their `due` is a day number now.
    """
    url = _url(settings)
    language = _language(settings)

    report = ankiconnect.probe(url)
    if not report.get("ok"):
        return _report(False, "Nothing was restored.",
                       problems=[report.get("error") or f"Could not reach Anki at {url}."])

    # One of Connect's runs that never finished blocks every reorder (P1.4, §7.2): Restore puts it back first — the
    # one the user was asked about (`asked`: its id, "" for the window's own snapshot), never another in its place.
    unfinished = undo.unfinished(language, "reorder")
    if unfinished is not None or asked:
        if asked is not None and unfinished != asked:
            return _report(False, "Nothing was restored.", problems=[RESTORE_CHANGED])
        return _restore_run(settings, unfinished, progress)

    decks, problems = _resolve_decks(settings, url)
    if problems:
        return _report(False, "Nothing was restored.", problems=problems)

    # The newer of the manual run's snapshot and today's baseline (03 §5); with no baseline, `load()`.
    snapshot = undo.restorable(language, _restore_scope(settings))     # the scope the window asked with
    if not snapshot:
        # Asked and answered before touching the collection at all — there is nothing to replay, so
        # reading 152 cards out of Anki to discover that would be work for no one.
        return _report(False, "Nothing was restored.", problems=[undo.describe(None)], decks=decks)

    try:
        # Asked BEFORE the first write — a restore now unsuspends cards before it can see their
        # positions, and a refusal must still mean nothing was touched.
        undo.check_restorable(snapshot, decks, mode=_scope_mode(settings))
    except RestoreRefused as e:
        # Shown verbatim: a restore is what the user reaches for when something has already gone
        # wrong, and "refused" without "for which deck" leaves them guessing.
        return _report(False, "Nothing was restored.", problems=[str(e)], decks=decks)

    # §13 first: a card Junban suspended is not in the new-card search, so its position could not be
    # put back while it stayed suspended. Only the cards Junban recorded — never one the user
    # suspended themselves.
    unsuspended, unsuspend_failures = ankiconnect.unsuspend(url, undo.restore_suspended(snapshot),
                                                            chunk=_chunk_size(settings))
    stopped = "Nothing was restored." if not unsuspended else (
        f"Restore stopped part way — {len(unsuspended)} card{'' if len(unsuspended) == 1 else 's'} "
        "Junban had suspended are unsuspended again. Press Restore again once Anki answers.")
    try:
        rows = _scope_cards(url, decks)
        pairs, skipped = undo.restore_pairs(snapshot, decks, existing_ids=_new_card_ids(rows),
                                            mode=_scope_mode(settings))
        # Backlog onboarding: a Try's snapshot holds only the cards it moved — each put back only while it is still
        # where Try it put it (as one of Connect's runs, `restore_run_pairs`); one moved since is left and counted.
        pairs, moved_on = undo.tried_pairs(snapshot, pairs, {row.get("cardId"): row.get("due") for row in rows})
        skipped = sorted(set(skipped) | set(moved_on))
    except (RestoreRefused, AnkiError) as e:
        return _report(False, stopped, problems=[str(e)], decks=decks)

    # WP-L's second section, undone whether or not there are positions left to put back: a note
    # whose card the user has since studied still carries the frequency entry junban appended.
    try:
        field_edits, fields_skipped, tag, tag_notes, marker_tags = _restore_touchups(url, snapshot)
        flag_pairs, flags_skipped = _restore_flags(url, snapshot)
    except AnkiError as e:
        return _report(False, stopped, problems=[str(e)], decks=decks)

    if not pairs and not field_edits and not tag_notes and not marker_tags and not flag_pairs \
            and not unsuspended and not undo.restore_unsuspended(snapshot):
        # Nothing left to put back is also "the way back is taken": an interrupted run must not keep
        # blocking new ones once none of its cards can be restored anyway.
        _taken_back(language, snapshot)
        return _report(True, "There was nothing left to restore — none of the saved cards are still "
                             "waiting to be learned.", decks=decks)

    written, failures = ankiconnect.set_due(url, pairs, chunk=_chunk_size(settings),
                                            progress=progress)
    # MR-R3 (Connect's preview): the returning words' cards the reorder unsuspended are set aside again — only those
    # still new and unsuspended.
    again = sorted(set(undo.restore_unsuspended(snapshot)) & set(_new_card_ids(rows)))
    note_of = {row.get("cardId"): row.get("note") for row in rows}
    retag_failures = _later_back_on(url, snapshot, again, note_of, _chunk_size(settings))
    untagged_back = {note for note, _why in retag_failures}
    again = [card_id for card_id in again if note_of.get(card_id) not in untagged_back]      # never untagged
    resuspended, resuspend_failures = (ankiconnect.suspend(url, again, chunk=_chunk_size(settings)) if again
                                       else ([], []))
    failures = list(failures) + list(resuspend_failures)
    notes_updated, note_failures = ankiconnect.update_notes(url, field_edits,
                                                            chunk=_chunk_size(settings))
    untagged, untag_failures = ankiconnect.remove_tags(url, tag_notes, tag,
                                                       chunk=_chunk_size(settings))
    unmarked, unmark_failures = _apply_marker_tags(ankiconnect.remove_tags, url, marker_tags,
                                                   _chunk_size(settings))
    note_failures = note_failures + untag_failures + unmark_failures + retag_failures
    unflagged, flag_failures = ankiconnect.set_flags(url, flag_pairs, chunk=_chunk_size(settings))
    failures = list(failures) + unsuspend_failures + flag_failures
    _note_restored(settings, snapshot, unsuspended, resuspended, flag_pairs, unflagged, tag, untagged,
                   marker_tags, unmarked, unmark_failures, field_edits, notes_updated)
    _refresh_anki(url)

    ok = not failures and not note_failures
    if ok:
        # The way back has been taken, so an interrupted run no longer blocks the next one.
        _taken_back(language, snapshot)
    message = f"Restored {len(written)} card{'' if len(written) == 1 else 's'} to their previous order."
    if failures:
        message = (f"Restored {len(written)} of {len(pairs)} cards — {len(failures)} could not be "
                   "changed. The saved order is still on disk.")
    if notes_updated or untagged or unmarked or unsuspended or unflagged:
        parts = []
        if unsuspended:
            parts.append(f"unsuspended {len(unsuspended)} card"
                         f"{'' if len(unsuspended) == 1 else 's'} Junban had suspended")
        if unflagged:
            parts.append(f"put {len(unflagged)} card{'' if len(unflagged) == 1 else 's'}' "
                         "flags back")
        if notes_updated:
            parts.append(f"put {len(notes_updated)} note"
                         f"{'' if len(notes_updated) == 1 else 's'} back as they were")
        if untagged:
            parts.append(f"removed the '{tag}' tag from {len(untagged)} "
                         f"note{'' if len(untagged) == 1 else 's'}")
        # The `…::later` tag rides in the marker-tag map (§13); named apart, since it is not a marker.
        later = {note for name, ids in marker_tags.items()
                 if name.endswith(touchup.TAG_SEPARATOR + unlisted.LATER_LEAF) for note in ids}
        marked = {note for name, ids in marker_tags.items()
                  if not name.endswith(touchup.TAG_SEPARATOR + unlisted.LATER_LEAF) for note in ids}
        unmarked_later = [note for note in unmarked if note in later]
        unmarked_markers = [note for note in unmarked if note in marked]
        if unmarked_markers:
            parts.append(f"removed the marker tags from {len(unmarked_markers)} "
                         f"note{'' if len(unmarked_markers) == 1 else 's'}")
        if unmarked_later:
            parts.append(f"removed the 'later' tag from {len(unmarked_later)} "
                         f"note{'' if len(unmarked_later) == 1 else 's'}")
        message += " Also " + " and ".join(parts) + "."
    if resuspended:
        message += (f" Set {len(resuspended)} card{'' if len(resuspended) == 1 else 's'} aside again that came "
                    "back on your list.")
    if skipped:
        message += f" {len(skipped)} card{'' if len(skipped) == 1 else 's'} had moved on and were left alone."
    if fields_skipped:
        # Named, not silently swallowed: the user needs to know their own later edit is the reason
        # a field did not come back — that is the promise that makes this safe to press.
        message += (f" {fields_skipped} field{'' if fields_skipped == 1 else 's'} had been edited "
                    "since the reorder and were left exactly as they are.")
    if flags_skipped:
        message += (f" {flags_skipped} card{'' if flags_skipped == 1 else 's'} had been flagged "
                    "again since and kept that flag.")
    return _report(ok, message, decks=decks, written=written, failures=failures,
                   notes_updated=notes_updated, note_failures=note_failures,
                   tagged=untagged, marker_tagged=unmarked, fields_skipped=fields_skipped,
                   snapshot=undo.snapshot_path(language, "baseline" if undo.is_baseline(snapshot) else "reorder"),
                   problems=([] if ok else
                             [reason for _id, reason in (list(failures) + note_failures)[:1]]))


def restore_run(settings, run_id, progress=None, wait=0.0, cancel=None, on_wait=None, verb="順 restore", away=False):
    """Put back exactly what one of Connect's runs changed (P1.4 row 1.4.2): `_restore_run`, holding the Anki-write
    lock as `restore` does. `away` (Junban-X2's one press): only while none of its cards sits in the window's decks."""
    held, problem = anki_connect.take_writer(verb, _url(settings), wait, cancel, on_wait)
    if held is None:
        return _report(False, "Nothing was restored.", problems=[problem], busy=True)
    with held:
        return _restore_run(settings, run_id, progress, away=away)


# The window asked about one thing to put back, and by the time it held Anki's writer that had changed (P1.4).
RESTORE_CHANGED = ("What Restore would put back changed while it waited (an automatic run didn't finish, or was put "
                   "back). Press Restore again to see it.")


def _restore_run(settings, run_id, progress=None, away=False):
    """Undo one of Connect's runs, and nothing after it. Its snapshot (`undo.load(run_id=)`) names what it changed:

      * the cards it suspended (3.0) are unsuspended — only those;
      * each position it wrote is put back, only while the card still sits where the run put it (`after`): a card a
        later run or you moved since stays, and is counted;
      * the returning words' cards it unsuspended (MR-R3) are suspended again, only those still new and unsuspended;
      * its tags and flags come off as the window's Restore takes them off — never a field or flag you changed since.

    Never raises; a run already put back, or not one of Junban's reorders, is refused untouched. `away` (Junban-X2,
    the adversary's SHOULD 1): first, holding the writer, its cards read — one that sits in the window's deck (or a
    subdeck) now refuses it untouched (`reaches`): putting it back would move a card under this deck's preview (I5)."""
    url = _url(settings)
    language = _language(settings)
    snapshot = undo.load(language, run_id=run_id)
    if not snapshot or snapshot.get("kind") != "reorder":
        return _report(False, "Nothing was restored.", problems=[f"There is no saved reorder run {run_id!r}."])
    if snapshot.get("restored_at"):
        return _report(False, "Nothing was restored.",
                       problems=[f"The automatic reorder {run_id} was already put back."])
    report = ankiconnect.probe(url)
    if not report.get("ok"):
        return _report(False, "Nothing was restored.",
                       problems=[report.get("error") or f"Could not reach Anki at {url}."])
    if away:
        try:
            reaches = _reaches(settings, url, snapshot)
        except AnkiError as e:
            return _report(False, "Nothing was restored.", problems=[str(e)])
        if reaches:
            return _report(False, "Nothing was restored.", problems=[reaches], reaches=True)
    chunk = _chunk_size(settings)
    unsuspended, unsuspend_failures = ankiconnect.unsuspend(url, undo.restore_suspended(snapshot), chunk=chunk)
    stopped = "Nothing was restored." if not unsuspended else "Restore stopped part way. Press Restore again."
    try:
        wanted = sorted({int(card_id) for card_id in snapshot.get("cards") or {}}
                        | set(undo.restore_unsuspended(snapshot)))
        rows = ankiconnect.cards_info(url, wanted) if wanted else []
        new = {row.get("cardId"): row for row in rows
               if _is_int(row.get("cardId")) and row.get("type") == 0}
        pairs, moved = undo.restore_run_pairs(snapshot, {card_id: row.get("due") for card_id, row in new.items()})
        field_edits, fields_skipped, tag, tag_notes, marker_tags = _restore_touchups(url, snapshot)
        flag_pairs, flags_skipped = _restore_flags(url, snapshot)
    except AnkiError as e:
        return _report(False, stopped, problems=[str(e)])
    again = [card_id for card_id in undo.restore_unsuspended(snapshot)
             if (new.get(card_id) or {}).get("queue") == 0]

    written, failures = ankiconnect.set_due(url, pairs, chunk=chunk, progress=progress)
    note_of = {card_id: row.get("note") for card_id, row in new.items()}
    retag_failures = _later_back_on(url, snapshot, again, note_of, chunk)
    untagged_back = {note for note, _why in retag_failures}
    again = [card_id for card_id in again if note_of.get(card_id) not in untagged_back]      # never untagged
    suspended, suspend_failures = ankiconnect.suspend(url, again, chunk=chunk) if again else ([], [])
    notes_updated, note_failures = ankiconnect.update_notes(url, field_edits, chunk=chunk)
    untagged, untag_failures = ankiconnect.remove_tags(url, tag_notes, tag, chunk=chunk)
    unmarked, unmark_failures = _apply_marker_tags(ankiconnect.remove_tags, url, marker_tags, chunk)
    unflagged, flag_failures = ankiconnect.set_flags(url, flag_pairs, chunk=chunk)
    _note_restored(settings, snapshot, unsuspended, suspended, flag_pairs, unflagged, tag, untagged,
                   marker_tags, unmarked, unmark_failures, field_edits, notes_updated)
    failures = list(failures) + list(unsuspend_failures) + list(suspend_failures) + list(flag_failures)
    note_failures = list(note_failures) + list(untag_failures) + list(unmark_failures) + list(retag_failures)
    ok = not failures and not note_failures
    if ok:
        undo.mark_complete(language, run_id=run_id, restored=True)
    message = (f"Put back the automatic reorder of {snapshot.get('written_at') or run_id}: "
               f"{len(written)} card{'' if len(written) == 1 else 's'} back where they were.")
    if unsuspended:
        message += f" Unsuspended {len(unsuspended)} it had suspended."
    if suspended:
        message += f" Set {len(suspended)} aside again."
    if moved:
        message += f" {moved} card{'' if moved == 1 else 's'} had moved since and were left where they are."
    if fields_skipped or flags_skipped:
        message += " What you changed since was left as it is."
    if not ok:
        message += " Some changes could not be made; the run's saved order is still on disk."
    return _report(ok, message, written=written, failures=failures, notes_updated=notes_updated,
                   note_failures=note_failures, tagged=untagged, marker_tagged=unmarked,
                   fields_skipped=fields_skipped, run=run_id, moved=moved, suspended=suspended,
                   unsuspended=unsuspended, snapshot=undo.snapshot_path(language, run_id=run_id),
                   problems=([] if ok else [reason for _id, reason in (failures + note_failures)[:1]]))


def _note_restored(settings, snapshot, unsuspended, suspended, flag_pairs, unflagged, tag, untagged, marker_tags,
                   unmarked, unmark_failures, field_edits, notes_updated):
    """FT D4: what a Restore undid, journalled once it landed (`first_touch.restored`; never a reason not to
    restore) — only what Anki took. A returning word's card set aside again carries the parked tag (K3)."""
    done = set(unflagged)
    failed = {note_id for note_id, _reason in unmark_failures}
    tags_off = {name: [note_id for note_id in ids if note_id in set(unmarked) and note_id not in failed]
                for name, ids in (marker_tags or {}).items()}
    if tag and untagged:
        tags_off[tag] = sorted(set(tags_off.get(tag) or []) | set(untagged))
    first_touch.restored(_language(settings), _url(settings), snapshot, snapshot.get("scope"),
                         unsuspended=unsuspended, suspended=suspended,
                         with_tag=unlisted.later_tag(touchup.options(settings).get("tag")),
                         flags=[pair for pair in flag_pairs if pair[0] in done], tags_off=tags_off,
                         fields={note_id: field_edits[note_id] for note_id in notes_updated if note_id in field_edits})


def _restore_flags(url, snapshot):
    """`([(card_id, flag)], skipped)` — §13's purple flags put back, read against the cards as they
    stand NOW: a card the user has flagged again since keeps their flag."""
    wanted = sorted(int(card_id) for card_id in (snapshot.get("flags") or {}))
    if not wanted:
        return [], 0
    current = {row.get("cardId"): row.get("flags") or 0
               for row in ankiconnect.cards_info(url, wanted) if _is_int(row.get("cardId"))}
    return undo.restore_flags(snapshot, current, unlisted.FLAG_PURPLE)


def _restore_touchups(url, snapshot):
    """Putting WP-L's and WP-N's note writes back. `(edits, skipped, tag, note_ids, marker_tags)`.

    The notes are re-read **now**, at restore time, because the whole point is to compare what is
    on the card today against what junban wrote: a field the user has edited since is left exactly
    as it is and counted, never reverted. Reverting it would destroy something they wrote after the
    run, which is worse than anything this module could have got wrong in the first place.
    """
    wanted = undo.note_ids(snapshot)
    if not wanted:
        return {}, 0, "", [], {}
    current = {}
    for note in ankiconnect.notes_info(url, wanted):
        note_id = note.get("noteId")
        if isinstance(note_id, int):
            current[note_id] = _note_values(note)
    edits, skipped = undo.restore_fields(snapshot, current)
    tag, tag_notes = undo.restore_tag(snapshot, existing_ids=current.keys())
    marker_tags = undo.restore_marker_tags(snapshot, existing_ids=current.keys())
    return edits, skipped, tag, tag_notes, marker_tags
