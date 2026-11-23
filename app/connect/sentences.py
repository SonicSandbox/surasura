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
import logging
import os
import re
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

# One sentence a word can be cut from: its file and item (None: no library item), the text, how many other words in it
# you don't know, its weight (young words + context), whether it is the episode being mined, whether it is heard at
# all (`audio`), whether that is the AI voice's (`ai`), and its place among its file's sentences as the token store
# keeps them (`number`: what a reader finds its cue by; None for a sentence the library search found)
Choice = namedtuple("Choice", "file item_id text others weight here audio ai number", defaults=(False, None))


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
    book's with an audiobook paired (`paired`: Connect lines it up and cuts the narrator's clip) its own clip; a
    book's or a text's with none, the AI voice's while it can make it (`ai`: `ai_voice`; the card is mined without
    audio and the voice fills its empty SentenceAudio), else none."""
    if not text or paired:
        return REAL
    return AI_VOICE if ai else SILENT


def _library(language, store=None, ai=False, only=None):
    """{normalised path: (item id, context, how it is heard, a book or a text)} for the library's items, read once:
    the store's items, their show's dates (`seen_dates`), their own (`watched_dates`), the order ahead
    (`library.ahead`) and the books an audiobook is paired with (`library.paired_books`); `ai`: `heard`'s. {} with no
    store. `only`: the items of these paths alone ([rel_path], the data folder's, with either slash) — what a reader
    of a few candidates asks, so its read follows them, not the library."""
    from app.connect import library
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
        paired = {os.path.normcase(os.path.abspath(epub)) for epub, _ab, _sha in library.paired_books(store)}
        root = get_data_path(language)
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
        for item_id, rel, tier, watched, work, folder, source_type, media in rows:
            show = shows.get(library_store._show_of(item_id, work, folder)) or {}
            seen = dated.get(item_id) or show.get("watched_at") or show.get("finished_at")
            if not seen and (show.get("finished") or tier == "graduated"):
                seen = "earlier"
            path = os.path.join(root, *str(rel).replace("\\", "/").split("/"))
            text = library.text_only({"rel_path": rel, "source_type": source_type})
            key = os.path.normcase(os.path.abspath(path))
            out[key] = (item_id, context(seen, place.get(item_id), tier, now), heard(text, key in paired, ai), text)
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


def _from_list(language, kept, listed, here_key, never, young, files, reach, books, ai, store, window):
    """`choose` for the words that are rows of the list (`listed`: {key: its row}) -> {key: [Choice, …]}, at most TOP
    a word (and the mined episode's own line, when it is a candidate): each row's kept candidates (`_listed`) of a
    good length, in Best's order (`_rank`, then the list's own), each checked as it is taken — its file as the
    Generate read it (`files`' digest: its path, time and size; a watched or Finished source by the token store's
    stamp), its media there (`reach`), never a line of `never`. The young words are read for a row's first
    YOUNG_LINES of those only (a sentence's known words are the token store's, a file decoded for each): they order
    a row's best-placed candidates, the rest weigh by context. `window`: the learner's length range as the library
    search reads it (`sentence_corpus.length_range`)."""
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
                continue        # a length outside the learner's range is no candidate (the library search's window)
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
        return sum(sentence_corpus._young(young, word) for word in {(t[0], t[1]) for t in held[number][1]} - {key})

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
                if not is_here and text_only and not (books and (hear is not SILENT or reach is None)):
                    continue            # a book's line nothing can speak, where media is cut (`choose`'s `unheard`)
                if same_line(row[plan_rules.TEXT], banned):
                    continue
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


def choose(language, keys, *, here=None, dial=None, never=None, young=None, files=None, reach=None, store=None,
           books=True):
    """The sentences each word's card can be cut from -> {(lemma, reading): [Choice, …]}, best first by the dial
    (the module's docstring); a word with no sentence: []. `keys`: [(lemma, reading)]; `here`: the episode's subtitle
    (Nearest: its lines first; Best: one candidate, kept on a tie); `dial`: NEAREST / BEST, None = the learner's
    setting; `never`: {key: {line text}} — never the same line (Swap passes the old card's sentence); `young`: {lemma:
    weight}, None = `young_weights`; `files`: the library's paths (None = `sentence_corpus.library_files`); `reach(item
    id) -> bool`: can its media be cut (Connect passes its video look-up; None = the file is there) — a sentence whose
    media can't be cut is no choice; a book's or a text's line isn't asked (`heard`: with a `reach`, one heard by
    nothing is no choice); `books`: can a book's or a text's line be mined at all (Connect: while Anki Miner reads
    books). A sentence of the library outside the learner's length range is not a candidate
    (the corpus's window), so a word met only in short lines gets [] here and keeps its own episode's line.

    A word that is a row of the list gets the list's candidates (`_from_list`: the module's docstring) — Best, and
    Nearest asked with no `here`; at most TOP, and the mined episode's own line; its `Choice.number` says where the
    sentence stands in its file. Any other word, and Nearest's own lines, are read from the token store."""
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
    if dial == BEST or not here_key:
        # The list's candidates first (the module's docstring); a word with no row is looked for in the library below
        kept, rows = _listed(language)
        listed = {key: rows[(key[0], key[1] or "")] for key in keys if (key[0], key[1] or "") in rows}
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
            is_here = path == here_key
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
    to another episode only for a better sentence, never for an equal one."""
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
