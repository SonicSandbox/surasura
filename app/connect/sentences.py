"""The sentence dial — which sentence a word's card is cut from (Kantan-SD, 3.0.18; the mining model, MODEL.md § 2 and
Sonic's rounds 3 and 4). The one picker: Connect's maker, Swap's maker, the journey's *which sentence comes first* and
anything else that chooses a word's sentence call `choose`; the line inside the episode it chooses is `pick.pick`'s,
handed the same young words and `never`.

Two choices (`connect_sentence_dial`, Connect's setting; `DIALS`):
- **Nearest** — the episode's own sentence. A line with another new word in it becomes i+1 by the other word's card
  coming first (Junban's order: nothing here orders cards); a better sentence is the learner's Swap.
- **Best** (the default, PROVISIONAL) — the best sentence anywhere in the library: understandable first (the fewest
  other words you don't know: i+1 before i+2), then how it is heard (`heard`: its own clip first — a video's, an
  audio file's, a book's paired audiobook —, then the AI voice's, then none: a book's or a text's line with neither
  comes last, and is no choice for a caller that cuts media), then the weight — the young words it also holds and the
  context you remember (`context`) — then the episode being mined (a tie stays where it is), then the corpus's own
  order (a sentence of a good length first: `sentence_corpus.collect`).

**Young words** (round 4): a sentence that also holds a word you are still learning — a studied card not yet mature,
under 21 days (`anki_sync.young_words`: `User Files/<lang>/anki_young.json`, read only) — weighs more, the younger the
more (`young_weights`). Without Anki's record: the words that became known recently (`recently_known`: the seam for the
review loop's known dates). A young word never outranks an understandable sentence or one whose media can be cut: it
is weight, after both.

**Context** (Kura-WD's dates, `Store.seen_dates` / `watched_dates`): a show watched or finished a week ago weighs about
four fifths, eight months ago about a tenth, the episodes just ahead of you about a third to a half, Soon less, Goal
and New arrivals nothing (`context`: PROVISIONAL numbers).

**Where a word's sentences come from** (2026-11-22: Generate is the one source of a word's sentences): Best's
candidates are the word's row in the list — the pool the last Generate kept for it in the plan file
(`plan_engine.candidates`: its first sentence, its shortlist of 60, up to 15 lines of what you watched or finished),
each with the list's own count of its other unknown words. Here they are only put in Best's order by what the moment
of mining knows (how a line is heard, the dates, the young words, `never`) and checked: a sentence whose file changed
or left since that Generate (the plan's digest of the file), or whose media can't be cut, is no choice. A word that
is no row of the list (under its cut-off: *Cards for every new word*; a known word: Swap) — or any word before the
first Generate — is looked for in the library itself (`sentence_corpus.files_holding`, then `collect` over those
files), a second pool under the same order (`_rank`). So the cost of a call follows the wanted words and their
candidates (at most 76 a row), never the library — except for a word with no row, whose search reads every file's
counts.

Reads the plan file, the library store and the token store only: never tokenizes the library. Light: nothing written.
"""
import functools
import logging
import os
import re
import threading
import time
import unicodedata
from collections import namedtuple
from datetime import datetime, timezone

log = logging.getLogger("surasura-cli")

NEAREST, BEST = "nearest", "best"
DIALS = (NEAREST, BEST)
DEFAULT = BEST              # the lead's lean (PROVISIONAL)
SETTING = "connect_sentence_dial"

YOUNG_DAYS = 21             # Anki's mature line (anki_sync.MATURE_DAYS): younger than this is a young word
SEEN_HALF_DAYS = 30         # context: a show seen this many days ago weighs half of one seen today
AHEAD_WEIGHT = 0.5          # ...the next episode ahead of you
AHEAD_HALF = 20             # ...and the one this many places ahead half of that
SOON_WEIGHT = 0.15          # Soon past the episodes ahead; Goal, New arrivals: 0
EARLIER_WEIGHT = 0.1        # finished *Earlier* (no date)
MOST_FILES = 30             # a word's first files only, in context order (a common word is in nearly every file;
#                             timed 2026-11-22: 200 files a word read 1,426 of 2,016 episodes, 14 s for one episode's
#                             35 words; 30 read 320, 1.5 s, the same best sentence for each)

# How a sentence is heard (`heard`): its own clip, the AI voice's (Sonic 2026-11-22: a book with no audiobook counts
# when the AI voice can make its audio), or not at all
REAL, AI_VOICE, SILENT = "real", "ai", None

TOP = 8                     # the choices a word gets back at most, best first (the corpus's eight: SENTENCES_PER_WORD)
YOUNG_LINES = 4             # ...and how many of a row's leading candidates have their young words read (each one is
#                             a file of the token store decoded; the rest weigh by their context alone)
GROW = 4                    # the score's path: a row whose best lines the cut can't make is asked again for this many
GROW_MOST = 2048            # ...times more lines, up to this many (or every line it has)
DATES_KEPT_S = 3600         # the library's dates kept between picks while the store's file is unchanged: an hour at most
DATES_AHEAD_WAIT_S = 30     # ...and a read of them waits this long at most for the one read ahead (`dates_ahead`)

# One sentence a word can be cut from: its file and item (None: no library item), the text, how many other words in it
# you don't know, its weight (young words + context), whether it is the episode being mined, whether it is heard at
# all (`audio`), whether that is the AI voice's (`ai`), and its place among its file's sentences as the token store
# keeps them (`number`: what a reader finds its cue by; None for a sentence the library search found), and — chosen by
# the score (`sentence_score`, at `plan_rules.SENTENCE_TABLE` >= 1) — its cost (`cost`: lower is better; None otherwise)
Choice = namedtuple("Choice", "file item_id text others weight here audio ai number cost",
                    defaults=(False, None, None))


def dial_of(settings):
    """The learner's choice: NEAREST or BEST (anything else, or nothing yet: DEFAULT)."""
    value = (settings or {}).get(SETTING)
    return value if value in DIALS else DEFAULT


def recently_known(language):
    """{lemma: days since it became known} for words known in the last YOUNG_DAYS — the seam for the review loop's
    known dates (Kyou-LR keeps the date a word became known): {} until its reader lands."""
    return {}


def young_weights(language, read=None):
    """{lemma: weight in (0, 1]} of the words you are still learning: Anki's young cards (`anki_sync.young_words`),
    a card one day old ~1, twenty days ~0.05; none there (never synced, every card mature, the file unreadable): the
    words known recently (`recently_known`), weighed alike. `read`: a stand-in for `young_words` (tests)."""
    rows = []
    try:
        if read is None:
            from app import anki_sync
            read = anki_sync.young_words
        rows = read(language) or []
    except Exception:
        rows = []
    out = {}
    for word, days in rows:
        if isinstance(word, str) and word and isinstance(days, int) and not isinstance(days, bool):
            out.setdefault(word, _fresh(days))
    if not out:
        for word, days in (recently_known(language) or {}).items():
            if isinstance(word, str) and word and isinstance(days, (int, float)):
                out.setdefault(word, _fresh(days))
    return {w: v for w, v in out.items() if v > 0}


def _fresh(days):
    return max(0.0, (YOUNG_DAYS - max(0, days)) / YOUNG_DAYS)


def _days_since(stamp, now):
    try:
        then = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return max(0.0, (now - then).total_seconds() / 86400)


def context(seen, place=None, tier=None, now=None):
    """How much context you remember from a sentence's episode, 0 to 1 (PROVISIONAL numbers): `seen` the date you
    watched it or finished its show (the store's stamp; "earlier" for a show finished with no date) — 1 today, a half
    after SEEN_HALF_DAYS; not seen, `place` its place among the episodes ahead of you (0 = next) — AHEAD_WEIGHT,
    halved AHEAD_HALF places on; else Soon a little, Goal / New arrivals / anything else nothing."""
    now = now or datetime.now(timezone.utc)
    if seen == "earlier":
        return EARLIER_WEIGHT
    if seen:
        days = _days_since(seen, now)
        if days is not None:
            return 1.0 / (1.0 + days / SEEN_HALF_DAYS)
    if place is not None:
        return AHEAD_WEIGHT / (1.0 + place / AHEAD_HALF)
    return SOON_WEIGHT if tier == "soon" else 0.0


def ai_voice(settings, language):
    """Can the AI voice (the beta `modules.irodori`) make a sentence's audio — switched on, installed, this language?
    The one place the picker knows of it (its public `on`, read lazily): the folder absent or failing -> False."""
    try:
        from modules import irodori
        return bool(irodori.on(settings or {}, language))
    except Exception:
        return False


def heard(text, paired, ai):
    """How an item's sentence is heard -> REAL, AI_VOICE or SILENT: a video's or an audio file's (not `text`) and a
    book's with an audiobook paired whose line-up can still give it (`paired`: `lineup.reach` — Connect lines it up
    and cuts the narrator's clip) its own clip; a
    book's or a text's with none, the AI voice's while it can make it (`ai`: `ai_voice`; the card is mined without
    audio and the voice fills its empty SentenceAudio), else none."""
    if not text or paired:
        return REAL
    return AI_VOICE if ai else SILENT


def _heard_line(hear, line_text, ai):
    """How one line of an item is heard: the item's answer (`_library`'s), or — a book lined up with its audiobook
    (`lineup.Reach`) — the narrator's clip only for a line its line-up says (`lineup.said`); one it doesn't (a chapter
    outside the audiobook's reach, a passage the narrator skipped) is a book's line with no audiobook (`heard`): the AI
    voice's while it can make it, else none — never a clip its card can't get (Kyou-PB)."""
    from app.connect import lineup
    if isinstance(hear, lineup.Reach):
        return REAL if lineup.said(hear, line_text) else heard(True, False, ai)
    return hear


def _library(language, store=None, ai=False, only=None, scored=False):
    """{normalised path: (item id, context, how it is heard, a book or a text)} for the library's items, read once:
    the store's items, their show's dates (`seen_dates`), their own (`watched_dates`; a watched mark with no date and
    a show with none is "earlier", as a finished show with none), the order ahead (`library.ahead`) and the parts of
    the books an audiobook is paired with (`library.paired_parts`, by item: Kyou-PB), each book's line-up read once
    (`lineup.reach`: how it is heard is then a `lineup.Reach`, read line by line by `_heard_line`); `ai`: `heard`'s.
    {} with no store. `only`: the items of these paths alone ([rel_path], the data folder's, with either slash) — what a reader
    of a few candidates asks, so its read follows them, not the library. `scored` (the score's moment, `_moment`): each
    value also says whether its date is only its show's — an unwatched episode of a started show, not Finished (the
    score's UNWATCHED) and, a paired book's, (its book's key, its audiobook's record: what `_heard_now` asks
    `lineup.reach` again) — and an unread chapter of a started book takes no show date: its place alone (the lead's
    ruling on OPEN 78 a, 2026-11-23)."""
    from app.connect import library, lineup
    from app.path_utils import get_data_path
    from app import library_store
    own = store is None
    if own:
        try:
            store = library.open_store(language, role="window")
        except Exception:
            store = None
    if store is None:
        return {}
    try:
        shows = store.seen_dates()
        dated = store.watched_dates()
        place = {item_id: n for n, item_id in enumerate(library.ahead(store))}
        paired = library.paired_parts(store)
        root = get_data_path(language)
        # (the score's read, every file: a path from the folder's own join, the same string as os.path.join(root,
        # *parts) for parts that are neither empty nor a drive — the others take os.path.join itself)
        head = os.path.join(root, "x")[:-1] if scored else None
        out = {}
        query = ("SELECT i.id, i.rel_path, i.tier, i.watched, i.work_id, i.parent_folder, i.source_type, w.media_type "
                 "FROM items i LEFT JOIN works w ON w.id = i.work_id")
        with store._reading():
            if only is None:
                rows = store.conn.execute(query).fetchall()
            else:
                asked = sorted({form for rel in only for form in (rel.replace("\\", "/"), rel.replace("/", "\\"))})
                rows = []
                for at in range(0, len(asked), 500):
                    batch = asked[at:at + 500]
                    rows += store.conn.execute(f"{query} WHERE i.rel_path IN ({','.join('?' * len(batch))})",
                                               batch).fetchall()
        now = datetime.now(timezone.utc)
        reach = {}              # a paired book -> its line-up's reach (`lineup.reach`), read once for its parts asked
        for item_id, rel, tier, watched, work, folder, source_type, media in rows:
            show = shows.get(library_store._show_of(item_id, work, folder)) or {}
            own_date = dated.get(item_id)
            seen = own_date or show.get("watched_at") or show.get("finished_at")
            if not seen and (watched or show.get("finished") or tier == "graduated"):
                seen = "earlier"            # a mark made before the store kept dates (Kyou-PB, PROVISIONAL)
            slashed = str(rel).replace("\\", "/")
            parts = slashed.split("/")
            if head is not None and "" not in parts and ":" not in slashed:
                path = head + os.sep.join(parts)
            else:
                path = os.path.join(root, *parts)
            text = library.text_only({"rel_path": rel, "source_type": source_type})
            show_only = False
            if (scored and not own_date and not watched and tier != "graduated" and not show.get("finished")
                    and show.get("watched_at") and seen == show.get("watched_at")):
                if text:
                    seen = None             # a book's unread chapter: by its place in the order alone
                else:
                    show_only = True        # an unwatched episode of a started show: its show's date, × UNWATCHED
            key = os.path.normcase(os.path.abspath(path))
            book = paired.get(item_id) if text else None
            if book is not None and book[0] not in reach:
                try:
                    reach[book[0]] = lineup.reach(book[2])
                except Exception:   # a line-up's state not as written (by hand, a half copy): no clip promised
                    reach[book[0]] = None
            got = reach.get(book[0]) if book is not None else None
            hear = got if isinstance(got, lineup.Reach) else heard(text, got is not None, ai)
            out[key] = (item_id, context(seen, place.get(item_id), tier, now), hear, text) +                 ((show_only, book[:3:2] if book is not None else None) if scored else ())
        return out
    finally:
        if own:
            store.close()


def context_of(language, path, store=None):
    """The context weight of one library file (`context`: 0 for a file outside the store, or with no store) — what
    the mined episode's own line weighs when the list keeps no line of that episode to say it (the runner's `_best`:
    a tie stays where it is only when both sides are weighed alike)."""
    from app.path_utils import get_data_path
    try:
        rel = os.path.relpath(path, get_data_path(language)).replace("\\", "/")
        placed = _library(language, store, False, only=[rel]).get(os.path.normcase(os.path.abspath(path)))
        return round(placed[1], 4) if placed else 0.0
    except Exception:
        return 0.0


_KEPT = {}                  # language -> (the plan file's path, time and size, its candidates, {key: its row}): `_listed`
_LEMMAS = {}                # language -> (the rows `_listed` read, {lemma: their row numbers}): `_row_of`


def _listed(language):
    """(the list's candidates — `plan_engine.candidates`: each listed row's pool as the last Generate kept it —,
    {(word, reading): its row}), read once per version of the plan file; (None, {}) with no readable plan."""
    from app import analyzer, plan_engine
    from app.path_utils import get_user_file
    path = os.path.join(get_user_file("results"), analyzer.PLAN_FILE)
    try:
        st = os.stat(path)
    except OSError:
        return None, {}
    stamp = (path, st.st_mtime_ns, st.st_size)
    hit = _KEPT.get(language)
    if hit is None or hit[0] != stamp:
        kept = plan_engine.candidates(path, language)
        if kept is None:
            return None, {}     # not kept: a read that failed once (the file held open) is tried again next time
        rows = {(key[0], key[1] or ""): k for k, key in enumerate(kept.keys) if k in kept.pools}
        hit = _KEPT[language] = (stamp, kept, rows)
    return hit[1], hit[2]


def _row_of(language, kept, rows, key, old=None):
    """The list's row for `key` -> its number, or None (no row: the library search looks for the word). The exact
    (lemma, reading); a key with no reading (a swap from the review loop's queue: Anki's ⇄ carries none) is the
    lemma's row when the list has one. Two or more (one spelling, two words: 今日 きょう / こんにち) -> only the one whose
    kept sentences hold the old card's line (`old`, by `same_line`: the Generate's own reading of that line says which
    word it is), else None as before — a guess could give the card the other word's sentences."""
    k = rows.get((key[0], key[1] or ""))
    if k is not None or key[1]:
        return k
    hit = _LEMMAS.get(language)
    if hit is None or hit[0] is not rows:
        index = {}
        for (lemma, _reading), n in rows.items():
            index.setdefault(lemma, []).append(n)
        hit = _LEMMAS[language] = (rows, index)
    same = hit[1].get(key[0]) or []
    if len(same) == 1:
        return same[0]
    from app import plan_rules
    held = [n for n in same if old and any(
        0 <= s < len(kept.sentences) and same_line(kept.sentences[s][plan_rules.TEXT], old)
        for s in list(kept.pools[n][1]) + [kept.pools[n][0]])]
    return held[0] if len(held) == 1 else None


def files_saying(language, words):
    """How many files the last Generate kept sentences of each word from -> {(lemma, reading): n}, for each (lemma,
    reading, line) of `words` that is a row of the list (`_listed`, `_row_of`): the files of the row's kept pool, the
    file holding `line` (`same_line`) left out — the files other than that one line's. A word with no row, or no
    readable plan, is left out. Reads the plan's candidates only (as `choose`), never the library (Kyou-DW 3: which
    answer a deleted card's follow-up offers first)."""
    from app import plan_rules
    kept, rows = _listed(language)
    out = {}
    if kept is None:
        return out
    for lemma, reading, line in words:
        key = (lemma, reading or "")
        k = _row_of(language, kept, rows, key, {line} if line else None)
        if k is None:
            continue
        first, pool, audio = kept.pools[k]
        said = [kept.sentences[s] for s in dict.fromkeys([first] + list(pool) + list(audio))
                if 0 <= s < len(kept.sentences)]
        own = {row[plan_rules.SRC] for row in said if line and same_line(row[plan_rules.TEXT], {line})}
        out[key] = len({row[plan_rules.SRC] for row in said} - own)
    return out


def _from_list(language, kept, listed, here_key, never, young, files, reach, books, ai, store, window):
    """`choose` for the words that are rows of the list (`listed`: {key: its row}) -> {key: [Choice, …]}, at most TOP
    a word (and the mined episode's own line, when it is a candidate): each row's kept candidates (`_listed`) of a
    good length, in Best's order (`_rank`, then the list's own), each checked as it is taken — its file as the
    Generate read it (`files`' digest: its path, time and size; a watched or Finished source by the token store's
    stamp), its media there (`reach`), never a line of `never`. The young words are read for a row's first
    YOUNG_LINES of those only (a sentence's known words are the token store's, a file decoded for each): they order
    a row's best-placed candidates, the rest weigh by context. `window`: the learner's length range as the library
    search reads it (`sentence_corpus.length_range`: at `plan_rules.SENTENCE_TABLE` >= 2 from one character)."""
    from app import plan_rules, token_index, sentence_corpus
    from app.connect import library
    from app.path_utils import get_data_path
    root = get_data_path(language)
    sentences, sources, n_files = kept.sentences, kept.files, len(kept.files)
    own = [c[0] for c in kept.cowords]
    allowed = None if files is None else {os.path.normcase(os.path.abspath(f)) for f in files} | {here_key}
    lines = {}                  # key -> its candidates' ids, the list's order: the shortlist, the watched, the first
    for key, k in listed.items():
        first, pool, _audio = kept.pools[k]
        seen, line = set(), []
        for s in list(pool) + ([first] if first >= 0 else []):
            row = sentences[s] if 0 <= s < len(sentences) else None
            if (row is None or not row[plan_rules.TEXT] or not window[0] <= len(row[plan_rules.TEXT]) <= window[1]
                    or row[plan_rules.HASH] in seen):
                continue        # a length outside the library search's window is no candidate
            seen.add(row[plan_rules.HASH])
            line.append(s)
        lines[key] = line
    placed = {}                 # a source -> (its path as written, its key, its rel_path, its kind, its digest or None)
    for src in {sentences[s][plan_rules.SRC] for line in lines.values() for s in line}:
        if src < n_files:
            rel, _tier, digest, kind = sources[src]
        else:
            (rel, kind, _rank_no), digest = kept.finished[src - n_files], None
        path = rel if os.path.isabs(rel) else os.path.join(root, "") + rel.replace("/", os.sep)
        placed[src] = (path, os.path.normcase(os.path.abspath(path)), rel, kind, digest)
    info = dict(_library(language, store, ai, only=[p[2] for p in placed.values() if not os.path.isabs(p[2])]))
    for path, at, _rel, _kind, _digest in placed.values():
        if at not in info:              # outside the store (or none): a book or a text by its own extension
            text = library.text_only({"rel_path": path})
            info[at] = (None, 0.0, heard(text, False, ai), text)
    tokens = [None]             # the token store, opened for the first stamp or sentence asked of it
    stamps, there, reached, read = {}, {}, {}, {}

    def store_of():
        if tokens[0] is None:
            tokens[0] = token_index.open_reader(language) or False
        return tokens[0]

    def as_read(src):
        """Is the source's file the one the Generate read — there, its time and size the plan's (or, a watched or
        Finished one's, the token store's)?"""
        if src not in there:
            path, at, rel, kind, digest = placed[src]
            try:
                st = os.stat(path)
                if digest is not None:
                    # (the run signs a file's path as it resolved it: the store's rel_path joined as it is written)
                    there[src] = any(plan_rules.file_digest([signed, [st.st_mtime, st.st_size], None, None, kinds])
                                     == digest for signed in dict.fromkeys((os.path.join(root, rel), path))
                                     for kinds in ((kind, None) if not kind else (kind,)))
                else:
                    cache = store_of()
                    if at not in stamps and cache:
                        stamps.update(cache.file_stamps([at]))
                    there[src] = stamps.get(at) == [st.st_mtime, st.st_size]
            except Exception:
                there[src] = False
        return there[src]

    def can_cut(at, item_id):
        spot = item_id if item_id is not None else at       # a file outside the store: its own answer
        if spot not in reached:
            try:
                reached[spot] = bool(reach(item_id)) if reach is not None and item_id is not None \
                    else os.path.isfile(at)
            except Exception:
                reached[spot] = False
        return reached[spot]

    def fresh(key, at, number, text):
        """The young words sentence `number` of the file holds beside `key` (their weights' sum), as the token store
        keeps it; None when that sentence is no longer `text` there (the file was read again since the Generate)."""
        cache = store_of()
        if not cache:
            return 0.0          # no token store to ask: no young words, the sentence taken as the plan has it
        if at not in read:
            read[at] = cache.file_tokens(at)
        held = read[at]
        if not (0 <= number < len(held)) or str(held[number][0]).strip() != text:
            return None
        me = {key, (kept.keys[listed[key]][0], kept.keys[listed[key]][1] or "")}    # a key with no reading: its row's
        return sum(sentence_corpus._young(young, word) for word in {(t[0], t[1]) for t in held[number][1]} - me)

    out = {}
    try:
        for key, line in lines.items():
            k, banned, found = listed[key], never.get(key), []
            for position, s in enumerate(line):
                row = sentences[s]
                path, at, _rel, _kind, _digest = placed[row[plan_rules.SRC]]
                item_id, ctx, hear, text_only = info[at]
                is_here = at == here_key
                if allowed is not None and at not in allowed:
                    continue
                if same_line(row[plan_rules.TEXT], banned):
                    continue
                hear = _heard_line(hear, row[plan_rules.TEXT], ai)
                if not is_here and text_only and not (books and (hear is not SILENT or reach is None)):
                    continue            # a book's line nothing can speak, where media is cut (`choose`'s `unheard`)
                others = sum(1 for c in row[plan_rules.COWORDS] if own[c] != k)
                found.append((Choice(path, item_id, row[plan_rules.TEXT], others, round(ctx, 4), is_here,
                                     hear is not SILENT, hear == AI_VOICE, row[plan_rules.NUMBER]), position, s))
            found.sort(key=lambda c: _rank(c[0], BEST) + (c[1],))
            taken, mine = [], None
            for choice, position, s in found:
                if len(taken) >= TOP and (mine is not None or not choice.here):
                    continue            # past the best TOP only the mined episode's own line is still looked for
                src = sentences[s][plan_rules.SRC]
                at = placed[src][1]
                if not as_read(src):
                    continue
                if not choice.here and (reach is None or not info[at][3]) and not can_cut(at, choice.item_id):
                    continue            # a book's line is judged by how it is heard (above), and is there
                if placed[src][4] is None and fresh(key, at, choice.number, choice.text) is None:
                    continue            # a watched or Finished source read again since: its line may have moved
                if choice.here:
                    mine = choice
                taken.append((choice, position, at))
            if young and taken:
                lead = _rank(taken[0][0], BEST)[:2]
                weighed = []
                for n, (choice, position, at) in enumerate(taken):
                    if n < YOUNG_LINES and _rank(choice, BEST)[:2] == lead:
                        more = fresh(key, at, choice.number, choice.text)
                        if more is None:
                            continue    # read again since the Generate: the line may be gone
                        choice = choice._replace(weight=round(choice.weight + max(0.0, more), 4))
                    weighed.append((choice, position, at))
                taken = sorted(weighed, key=lambda c: _rank(c[0], BEST) + (c[1],))
            out[key] = [choice for choice, _position, _at in taken]
    finally:
        if tokens[0]:
            tokens[0].close()
    return out


# --------------------------------------------------------------------------------------------------------------- #
# The score's path (the sentence choice, release 1: `plan_rules.SENTENCE_TABLE` >= 1 with a table there)
# --------------------------------------------------------------------------------------------------------------- #
_DATES = {}                 # (language, ai) -> (the store file's stamp, when read, `_library`'s, the score's files,
                            # the store's own count of what changed then: `_store_state`)
_AHEAD = {}                 # (language, ai) -> the thread reading them ahead (`dates_ahead`), the last one started
_AHEAD_LOCK = threading.Lock()


def _store_stamp(language):
    """The library store's file and its write-ahead log as they stand (path, time, size): any commit — a watched
    mark, a move — changes it. None: no store file (nothing is kept)."""
    try:
        from app import library_store
        from app.path_utils import get_data_path
        path = library_store.library_db_path(language, get_data_path(language))
        out = [path]
        for name in (path, path + "-wal"):
            try:
                st = os.stat(name)
                out.append((st.st_mtime_ns, st.st_size))
            except OSError:
                out.append(None)
        return tuple(out) if out[1] is not None else None
    except Exception:
        return None


def _store_state(language):
    """The store's own count of what changed (`library_store.read_state`: its id, epoch and `state_version`), or None
    (can't tell): what the file's stamp moving says only when this moved too — the export's own commit after a move
    (`spawn_maintain`'s, a second or two into a Generate or redraw) and a checkpoint move the stamp, never this."""
    try:
        from app import library_store
        from app.path_utils import get_data_path
        return library_store.read_state(language, get_data_path(language))
    except Exception:
        return None


def _dates(language, ai, wait=True):
    """(`_library`'s answer with the show-only mark, the score's {path: Seen}) for the whole library, read once and
    kept between picks while the store's file is unchanged — or, its stamp moved, while the store's own count of what
    changed holds (`_store_state`: the export's commit after a move, a checkpoint) — an hour at most (days pass): one
    read of the store was nearly all of a pick's time (SPEC § 5.3); a paired book's hearing asked again at every pick
    (`_heard_now`). A read
    ahead of them still running (`dates_ahead`) is waited for, DATES_AHEAD_WAIT_S at most: its answer is then kept
    (`wait` False: that read's own call)."""
    ahead = _AHEAD.get((language, ai)) if wait else None
    if ahead is not None:
        ahead.join(DATES_AHEAD_WAIT_S)
        with _AHEAD_LOCK:                   # (waited for once: a read stuck past the wait is never waited for again)
            if _AHEAD.get((language, ai)) is ahead:
                del _AHEAD[(language, ai)]
    stamp = _store_stamp(language)          # (before the read: a commit during it is read again next time)
    now = time.monotonic()
    hit = _DATES.get((language, ai))
    kept = hit is not None and stamp is not None and now - hit[1] < DATES_KEPT_S
    if kept and hit[0] == stamp:
        return _heard_now(hit[2], hit[3], ai)
    state = _store_state(language) if stamp is not None else None      # (before the read too: as the stamp)
    if kept and state is not None and state == hit[4]:
        _DATES[(language, ai)] = (stamp,) + hit[1:]          # only bookkeeping since (the export's commit): kept
        return _heard_now(hit[2], hit[3], ai)
    from app import sentence_score
    from app.connect import lineup
    info = _library(language, None, ai, scored=True)
    seen = {at: _seen(v, ai, sentence_score.Seen, lineup) for at, v in info.items()}   # (two imports a read, not a file)
    if stamp is None or not info:           # (an empty answer — no store, or one busy at its open — is never kept)
        _DATES.pop((language, ai), None)
    else:
        _DATES[(language, ai)] = (stamp, now, info, seen, state)
    return _heard_now(info, seen, ai)       # (the same answers as the read's: the next pick's objects from the first)


def files_seen(language, ai):
    """The score's {path: Seen} for the whole library now — the dates Connect's card weighs (`_dates`: one read, kept
    while the store is unchanged, a read ahead waited for): what the level-2 list asks (`analyzer.ListSentences`), so
    the list shows what a card would get."""
    return _dates(language, ai)[1]


def dates_ahead(language, ai):
    """The library's dates (`_dates`) read now on a thread of its own, so the asker goes on — Connect's run to its
    shelf and its first job (SPEC § 6.3 row 16), a level-2 Generate or redraw to its plan (`analyzer.main`): the next
    read of (`language`, `ai`) waits for this one and takes what it kept. One read ahead at a time a (language, ai);
    one that failed leaves nothing kept (the next reads itself)."""
    key = (language, ai)
    with _AHEAD_LOCK:
        thread = _AHEAD.get(key)
        if thread is None or not thread.is_alive():
            thread = threading.Thread(target=_read_dates, args=key, name=f"surasura-dates-{language}", daemon=True)
            thread.start()                  # (kept once started: one that could not start is never waited for)
            _AHEAD[key] = thread
    return thread


def _read_dates(language, ai):
    try:
        _dates(language, ai, wait=False)
    except Exception:
        log.info("Connect: the library's dates weren't read ahead (%s)", language, exc_info=True)


def _seen_of(v, ai):
    """`_library`'s value -> the score's `Seen`: a lined-up book heard line by line, its line-up's answer (Kyou-PB)."""
    from app import sentence_score
    from app.connect import lineup
    return _seen(v, ai, sentence_score.Seen, lineup)


def _seen(v, ai, seen, lineup):
    if isinstance(v[2], lineup.Reach):
        return seen(v[0], v[1], REAL, v[4], functools.partial(lineup.said, v[2]), heard(True, False, ai))
    return seen(v[0], v[1], v[2], v[4])


_HEARD = {}                 # ai -> (the kept dates' {path: Seen}, each paired book's answer, `_heard_now`'s answer)


def _heard_now(info, seen, ai):
    """The kept dates with each paired book's hearing asked again (`lineup.reach`, once a book): a line-up that
    finished, was done again or lost its audio since writes nothing to the store, so the stamp can't tell -> fresh
    (info, seen) for those files, the kept ones as they are."""
    from app.connect import lineup
    paired = [at for at, v in info.items() if len(v) > 5 and v[5] is not None]
    if not paired:
        return info, seen
    reach = {}
    for at in paired:
        key, record = info[at][5]
        if key not in reach:
            try:
                reach[key] = lineup.reach(record)
            except Exception:       # a line-up's state not as written: no clip promised (`_library`'s rule)
                reach[key] = None
    # (each book's answer the same object as the pick before — `lineup.reach` keeps one while its files are unchanged —
    # so the fresh dates are the same: the same objects back, and the score keeps its files' arrays by them)
    was = _HEARD.get(ai)
    if was is not None and was[0] is seen and was[1].keys() == reach.keys() and all(
            was[1][k] is got for k, got in reach.items()):
        return was[2]
    kept_seen, info, seen = seen, dict(info), dict(seen)
    for at in paired:
        v = info[at]
        got = reach[v[5][0]]
        info[at] = v[:2] + (got if isinstance(got, lineup.Reach) else heard(v[3], got is not None, ai),) + v[3:]
        seen[at] = _seen_of(info[at], ai)
    _HEARD[ai] = (kept_seen, reach, (info, seen))
    return info, seen


_SINCE = {}                 # language -> (the table's and the two marks files' stamps, `known_since`'s answer)


def _stamp(path):
    try:
        st = os.stat(path)
        return st.st_mtime_ns, st.st_size
    except OSError:
        return None


def known_since(language):
    """The words marked Known or Ignore since the last Generate wrote its table -> {(lemma, "")} (every row of the
    lemma): the window's own rule (`word_marks.left_out`, what its numbers leave out at once) — so a sentence holding a
    word you marked since counts it known at once (SPEC § 5.4). {} when nothing was marked since, or unreadable. Kept
    while the table and both marks files (`word_marks.marks_files`) are as they were: a pick parsed them every time."""
    try:
        from app import sentence_score
        sentence_score.numpy_one_thread()           # (before the table brings numpy in: its BLAS held to one thread)
        from app import sentence_table
        from app.path_utils import get_user_file
        from app.services import word_marks
        table = os.path.join(get_user_file("results"), sentence_table.TABLE_FILE)
        stamps = (_stamp(table),) + tuple(_stamp(p) for p in word_marks.marks_files(language))
        hit = _SINCE.get(language)
        if hit is not None and hit[0] == stamps:
            return hit[1]
        got = frozenset((word, "") for word in word_marks.left_out(language, since_ns=os.stat(table).st_mtime_ns))
        _SINCE[language] = (stamps, got)
        return got
    except Exception:
        return set()


def read_ahead(language):
    """Connect's read-ahead for a session (its `prepare`): at level >= 1, the table's head read now and the library's
    dates on a thread of their own (`dates_ahead`: the run goes on to its shelf meanwhile), so the first pick of the
    session reads only its words' blocks -> True when a table was there. Level 0, no table, any failure: False,
    nothing kept, no thread. The window's process never calls it (SPEC § 6.3 row 16)."""
    from app import plan_rules
    if plan_rules.SENTENCE_TABLE < 1:
        return False
    try:
        from app import sentence_score, settings_manager
        if sentence_score.choose(language, (), moment=sentence_score.Moment(), length=(1, 1)) is None:
            return False
        dates_ahead(language, ai_voice(settings_manager.load_settings(), language))
        return True
    except Exception:
        log.info("Connect: the sentence table wasn't read ahead (%s)", language, exc_info=True)
        return False


_UNNAMED = {}               # ai -> how a file outside the store is heard (`_unnamed_of`)


def _unnamed_of(ai):
    """How a file outside the store is heard — a book or a text by its own extension -> REAL / AI_VOICE / SILENT: the
    moment's `unnamed`, one function for each `ai` (the score keeps its files' arrays while it is the same object)."""
    got = _UNNAMED.get(ai)
    if got is None:
        from app.connect import library

        def got(path):
            return heard(library.text_only({"rel_path": path}), False, ai)
        _UNNAMED[ai] = got
    return got


def _scored(language, keys, here_key, never, young, files, reach, books, ai, settings, only=None, top=TOP):
    """`choose` for the keys that are rows of the table, by the score (`sentence_score.choose`: one cost a line, the
    lowest first; every line of the word, not a kept few) -> {key: [Choice, …]} at most `top` a word, plus the mined
    episode's own best line (`here_key`) when it is not among them; None at level 0 or with no table for `language`
    (today's path). A key that is no row of the table is left out (the caller's path finds it).

    The moment is Connect's: the dates (`_dates`, the show-only mark), how each file is heard, the young words, the
    words marked since the Generate (`known_since`), the learner's Length (`sentence_corpus.length_range`'s own
    pair) and *Ensure an audio example* (`heard_first`). Only what the cut can't make is left out, never what is
    merely worse: a video whose media can't be cut (`reach`), a book's line where books can't be mined (`books`
    off); a silent line is weighed, never removed. A lined-up book's line its line-up never says is weighed as its
    own book with no audiobook inside the score (`_dates`: `Seen.said`, line by line — the lead's ruling, 2026-11-23);
    a file outside the store is heard inside the score by Connect's own rule (`_unnamed_of`); a line Connect hears
    otherwise than the score did is moved by the two hearing rates here."""
    from app import plan_rules
    if plan_rules.SENTENCE_TABLE < 1:
        return None
    from app import sentence_score, sentence_corpus
    from app.connect import library
    info, seen = _dates(language, ai)
    _lo, _hi, low, high = sentence_corpus.length_range(settings)
    moment = sentence_score.Moment(files=seen, young=dict(young or {}), known=known_since(language),
                                   unnamed=_unnamed_of(ai))
    rate = sentence_score.rates()
    hearing = {REAL: rate.heard_real, AI_VOICE: rate.heard_ai, SILENT: rate.heard_silent}
    inside = only
    if inside is None and files is not None:
        inside = list(files) + ([here_key] if here_key else [])
    reached = {}

    def can_cut(at, item_id):
        spot = item_id if item_id is not None else at       # a file outside the store: its own answer
        if spot not in reached:
            try:
                reached[spot] = bool(reach(item_id)) if reach is not None and item_id is not None                     else os.path.isfile(at)
            except Exception:
                reached[spot] = False
        return reached[spot]

    def as_choice(line):
        at = os.path.normcase(os.path.abspath(line.file))
        placed = info.get(at)
        if placed is None:                  # outside the store (or none): a book or a text by its own extension
            text = library.text_only({"rel_path": line.file})
            placed = (line.item_id, 0.0, heard(text, False, ai), text)
        item_id, _ctx, hear, text_only = placed[:4]
        hear = _heard_line(hear, line.text, ai)
        is_here = at == here_key
        if not is_here and text_only and not books:
            return None                     # a book's or a text's line, where books can't be mined
        if not is_here and (reach is None or not text_only) and not can_cut(at, item_id):
            return None                     # its media can't be cut: no card can be made from it
        cost = line.cost + hearing.get(hear, rate.heard_silent) - hearing.get(line.heard, rate.heard_silent)
        return Choice(line.file, item_id, line.text, line.others, line.context, is_here, hear is not SILENT,
                      hear == AI_VOICE, line.number, round(cost, 4))

    heard_first = bool(settings.get("ensure_audio_example", False))
    memo = {}       # what the score's asks of this pick share, built once (the lead's waste card F6)

    def ask(asked, n, within):
        return sentence_score.choose(language, asked, n=n, moment=moment, length=(low, high), never=never or None,
                                     only=within, heard_first=heard_first, memo=memo)

    out, asked, n = {}, list(keys), top
    while asked:
        got = ask(asked, n, inside)
        if got is None:
            if not out:
                return None
            break
        again = []
        for key, lines in got.items():
            choices = [c for c in map(as_choice, lines) if c is not None]
            out[key] = choices
            unheard = heard_first and lines and lines[0].heard is not SILENT and not any(c.audio for c in choices)
            if (len(choices) < top or unheard) and len(lines) >= n and n < GROW_MOST:
                again.append(key)           # some of its best lines (or its heard ones) can't be made: ask for more
        asked, n = again, n * GROW
    if here_key and only is None:
        lacking = [key for key, choices in out.items() if not any(c.here for c in choices)]
        got = ask(lacking, 1, [here_key]) if lacking else None
        for key, lines in (got or {}).items():
            out[key] = out[key][:top] + [c for c in map(as_choice, lines[:1]) if c is not None]
    for key, choices in out.items():
        choices.sort(key=lambda c: round(c.cost, 9))        # (stable: the score's own order among equals)
        if heard_first and choices and not choices[0].audio:
            first = next((c for c in choices if c.audio), None)
            if first is not None:
                choices.remove(first)
                choices.insert(0, first)
        mine = next((c for c in choices[top:] if c.here), None)
        out[key] = choices[:top] + ([mine] if mine is not None else [])
    return out


def lines_in(language, keys, path, *, young=None):
    """The score's lines of each word inside one file, best first -> {(lemma, reading): [line text, …]} (a key that is
    no row of the table left out), at the moment `choose` reads (`_scored`, `only` the file): what the cut takes first
    (`pick.pick`'s `ranked`) — the score chooses the line, the cut refuses what it can't make (SPEC § 11, overlap 78;
    the lead's ruling, 2026-11-23). None at level 0, with no table, or on any failure: the cut's own rule, as today."""
    from app import plan_rules
    if plan_rules.SENTENCE_TABLE < 1 or not path:
        return None
    keys = list(dict.fromkeys(tuple(k) for k in keys or ()))
    if not keys:
        return {}
    try:
        from app import settings_manager
        settings = settings_manager.load_settings()
        here_key = os.path.normcase(os.path.abspath(path))
        got = _scored(language, keys, here_key, {}, young_weights(language) if young is None else dict(young), None,
                      None, True, ai_voice(settings, language), settings, only=[here_key], top=GROW_MOST)
    except Exception:                       # never the cut's fault: its own rule
        log.info("Connect: the score's lines in a file weren't read (%s)", language, exc_info=True)
        return None
    return None if got is None else {key: [c.text for c in choices] for key, choices in got.items()}


def choose(language, keys, *, here=None, dial=None, never=None, young=None, files=None, reach=None, store=None,
           books=True, top=TOP):
    """The sentences each word's card can be cut from -> {(lemma, reading): [Choice, …]}, best first by the dial
    (the module's docstring); a word with no sentence: []. `keys`: [(lemma, reading)]; `here`: the episode's subtitle
    (Nearest: its lines first; Best: one candidate, kept on a tie); `dial`: NEAREST / BEST, None = the learner's
    setting; `never`: {key: {line text}} — never the same line (Swap passes the old card's sentence); `young`: {lemma:
    weight}, None = `young_weights`; `files`: the library's paths (None = `sentence_corpus.library_files`); `reach(item
    id) -> bool`: can its media be cut (Connect passes its video look-up; None = the file is there) — a sentence whose
    media can't be cut is no choice; a book's or a text's line isn't asked (`heard`: with a `reach`, one heard by
    nothing is no choice); `books`: can a book's or a text's line be mined at all (Connect: while Anki Miner reads
    books). A sentence of the library outside the learner's length range is not a candidate
    (the corpus's window), so a word met only in short lines gets [] here and keeps its own episode's line — at
    `plan_rules.SENTENCE_TABLE` >= 2 only one over the range's top is: a short line is a candidate (SPEC § 4.6).

    A word that is a row of the list (a word with no reading: the lemma's one row, `_row_of`) gets the list's
    candidates (`_from_list`: the module's docstring) — Best, and Nearest asked with no `here`; at most TOP, and the
    mined episode's own line; its `Choice.number` says where the sentence stands in its file. Any other word, and
    Nearest's own lines, are read from the token store.

    At `plan_rules.SENTENCE_TABLE` >= 1 with a table there, a word that is a row of the table is chosen by the score
    instead (`_scored`: every line of the word, one cost, `Choice.cost` set) — Nearest inside the mined episode alone;
    with no table (never generated since, another engine, damaged) everything above, as today. `top`: how many of the
    score's lines a word gets back at most (the card reads its first and the mined episode's own, Swap the first it can
    use: each asks for 1 — every line returned is read from the token store); the score's lines only."""
    from app import settings_manager, sentence_corpus, analyzer, token_index
    keys = list(dict.fromkeys(tuple(k) for k in keys or ()))
    if not keys:
        return {}
    settings = settings_manager.load_settings()
    dial = dial if dial in DIALS else dial_of(settings)
    young = young_weights(language) if young is None else dict(young)
    never = {tuple(k): v for k, v in (never or {}).items() if v}
    here_key = os.path.normcase(os.path.abspath(here)) if here else None
    ai = ai_voice(settings, language)
    out = {key: [] for key in keys}
    nearest = dial == NEAREST and here_key
    try:
        scored = _scored(language, keys, here_key, never, young, files, reach, books, ai, settings,
                         only=[here_key] if nearest else None, top=top)
    except Exception:                       # the score's path never makes a pick worse than today's: today's
        log.info("Connect: the sentence score wasn't asked (%s)", language, exc_info=True)
        scored = None
    if scored:                              # (at level 0 None: nothing here runs)
        got = {key: c for key, c in scored.items() if c or not nearest}  # Nearest: an episode it holds no line of
        out.update(got)                                                   # is read as today
        keys = [key for key in keys if key not in got]
        if not keys:
            return out
    if dial == BEST or not here_key:
        # The list's candidates first (the module's docstring); a word with no row is looked for in the library below
        kept, rows = _listed(language)
        listed = {key: k for key in keys for k in [_row_of(language, kept, rows, key, never.get(key))]
                  if k is not None}
        if listed:
            try:
                out.update(_from_list(language, kept, listed, here_key, never, young, files, reach, books, ai, store,
                                      sentence_corpus.length_range(settings)))
            except Exception as e:          # a plan damaged inside its tables: its words go to the library search
                log.info("Connect: the list's sentences not read (%s): %s", language, e)
                listed = {}
            keys = [key for key in keys if key not in listed]
            if not keys:
                return out
    if files is None:
        files = sentence_corpus.library_files(language)
    info = dict(_library(language, store, ai))
    norm = [os.path.normcase(os.path.abspath(f)) for f in files or ()]
    if here_key and here_key not in norm:
        norm.append(here_key)
    from app.connect import library
    for path in norm:
        if path not in info:            # outside the store (or none): a book or a text by its own extension
            text = library.text_only({"rel_path": path})
            info[path] = (None, 0.0, heard(text, False, ai), text)

    def unheard(path):
        # a book's or a text's line that can't be a choice here (`books` off; heard by nothing while media is cut):
        # left out before the corpus keeps its few best a word, so it never stands in for a line that can
        _item, _ctx, hear, text = info[path]
        return path != here_key and text and not (books and (hear is not SILENT or reach is None))
    norm = [p for p in norm if not unheard(p)]
    # The order the corpus ties on: the most remembered context first, the episode being mined first among equals —
    # so a word's eight kept sentences are the best-placed ones (`collect` keeps at most 8 a word, 2 a file)
    order = sorted(range(len(norm)), key=lambda n: (-info[norm[n]][1], norm[n] != here_key, n))
    ordered = [norm[n] for n in order]
    if dial == NEAREST and here_key:
        holding = [here_key]
    else:
        holding = sentence_corpus.files_holding(language, ordered, keys, most=MOST_FILES)
        if here_key and here_key not in holding:
            holding = [here_key] + holding
    if not holding:
        return out
    analyzer.SANITIZE_JA = (language == "ja")
    tokens = token_index.open_store(language)
    try:
        words = sentence_corpus.collect(holding, tokens.file_tokens, language,
                                        sentence_corpus.known_sets(language, tokens, settings),
                                        sentence_corpus.length_range(settings), wanted=set(keys), young=young,
                                        library=sentence_corpus.library_counts(language),
                                        singles=bool(settings.get("exclude_single", True)))
    finally:
        tokens.close()
    reached = {}

    def can_cut(path, item_id):
        at = item_id if item_id is not None else path      # a file outside the store: its own answer
        if at not in reached:
            try:
                reached[at] = bool(reach(item_id)) if reach is not None and item_id is not None \
                    else os.path.isfile(path)
            except Exception:
                reached[at] = False
        return reached[at]

    for key in keys:
        word = words.get(key)
        found = []
        for position, (rank, text, fidx, _surface) in enumerate(word.best.result() if word and word.best else ()):
            path = holding[fidx]
            if same_line(text, never.get(key)):
                continue
            item_id, ctx, hear, text_only = info[path]
            hear = _heard_line(hear, text, ai)
            is_here = path == here_key
            if not is_here and text_only and not (books and (hear is not SILENT or reach is None)):
                continue                # a lined-up book's line its line-up never says (`_heard_line`): `unheard`'s
            if not is_here and (reach is None or not text_only) and not can_cut(path, item_id):
                continue                # a book's line is judged by how it is heard (`unheard`), and is there
            found.append((Choice(path, item_id, text, rank[0], round(ctx + max(0.0, -rank[2]), 4), is_here,
                                 hear is not SILENT, hear == AI_VOICE), position))
        found.sort(key=lambda c: _rank(c[0], dial) + (c[1],))
        out[key] = [c for c, _p in found]
    return out


def _rank(choice, dial):
    """A choice's sort key by the dial (lower first): Nearest — the episode's own first, then as Best; Best — the
    fewest other unknown words, how it is heard (its own clip, the AI voice's, none), the weight, the episode being
    mined on a tie."""
    best = (choice.others, (not choice.audio, bool(choice.ai)), -choice.weight, not choice.here)
    return ((not choice.here),) + best if dial == NEAREST else best


def better(choice, than):
    """Is `choice` strictly better than `than` (Best's rank without the tie to the episode being mined)? A word moves
    to another episode only for a better sentence, never for an equal one. Two the score chose (`cost` set on both):
    the lower cost, strictly."""
    if choice.cost is not None and than.cost is not None:
        return round(choice.cost, 4) < round(than.cost, 4)
    return _rank(choice, BEST)[:3] < _rank(than, BEST)[:3]


# A line by its text — the one rule every reader compares two lines by (the picker's `never`, Swap's old card)
_TAGS = re.compile(r"<[^>]*>")
_SOUND = re.compile(r"\[sound:[^\]]*\]")
_FURIGANA = re.compile(r"\[[^\]]*\]")          # a card's kana in brackets: 漢字[かんじ]
_MARKS = re.compile(r"[\s　「」『』（）()【】〈〉《》“”\"'‘’…‥・、，,。．.！!？?～〜ー―—–\-:;/]+")


def norm_line(text):
    """A line's text as two lines are compared: a card's markup, its sound tags and its kana in brackets out, NFKC,
    then spaces, line breaks and punctuation out — so a card's sentence field and the subtitle's line it was cut from
    are the same line."""
    text = _SOUND.sub("", str(text or ""))
    text = _FURIGANA.sub("", _TAGS.sub("", text.replace("&nbsp;", " ")))
    return _MARKS.sub("", unicodedata.normalize("NFKC", text))


def same_line(text, old):
    """Is `text` one of the lines `old` ({line text}, Swap's old card's sentence) holds — the same line
    (`norm_line`), or one inside the other (an old card's sentence may hold its line's neighbours too)? Two
    characters at least: an empty line is no line. Never with nothing in `old`."""
    line = norm_line(text)
    if len(line) < 2 or not old:
        return False
    return any(len(was) >= 2 and (line == was or line in was or was in line) for was in map(norm_line, old))
