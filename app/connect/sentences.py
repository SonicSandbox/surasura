"""The sentence dial — which sentence a word's card is cut from (Kantan-SD, 3.0.18; the mining model, MODEL.md § 2 and
Sonic's rounds 3 and 4). The one picker: Connect's maker, Swap's maker, the journey's *which sentence comes first* and
anything else that chooses a word's sentence call `choose`; the line inside the episode it chooses is `pick.pick`'s,
handed the same young words and `never`.

Two choices (`connect_sentence_dial`, Connect's setting; `DIALS`):
- **Nearest** — the episode's own sentence. A line with another new word in it becomes i+1 by the other word's card
  coming first (Junban's order: nothing here orders cards); a better sentence is the learner's Swap.
- **Best** (the default, PROVISIONAL) — the best sentence anywhere in the library: understandable first (the fewest
  other words you don't know: i+1 before i+2), then one whose media can be cut (`reach`: its video or audio is there;
  a book's or a text's sentence has no audio and comes after), then the weight — the young words it also holds and the
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

Reads the token store and its index only (`sentence_corpus.files_holding`, then `collect` over those files): never
tokenizes the library. Light: nothing written.
"""
import os
from collections import namedtuple
from datetime import datetime, timezone

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
MOST_FILES = 200            # a word's first files only, in context order (a common word is in nearly every file)

# One sentence a word can be cut from: its file and item (None: no library item), the text, how many other words in it
# you don't know, its weight (young words + context), whether it is the episode being mined, whether it has audio
Choice = namedtuple("Choice", "file item_id text others weight here audio")


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


def _library(language, store=None):
    """{normalised path: (item id, context, audio)} for the library's items, read once: the store's items, their
    show's dates (`seen_dates`), their own (`watched_dates`) and the order ahead (`library.ahead`). {} with no store."""
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
        root = get_data_path(language)
        out = {}
        with store._reading():
            rows = store.conn.execute("SELECT i.id, i.rel_path, i.tier, i.watched, i.work_id, i.parent_folder, "
                                      "i.source_type, w.media_type FROM items i LEFT JOIN works w ON w.id = i.work_id"
                                      ).fetchall()
        now = datetime.now(timezone.utc)
        for item_id, rel, tier, watched, work, folder, source_type, media in rows:
            show = shows.get(library_store._show_of(item_id, work, folder)) or {}
            seen = dated.get(item_id) or show.get("watched_at") or show.get("finished_at")
            if not seen and (show.get("finished") or tier == "graduated"):
                seen = "earlier"
            path = os.path.join(root, *str(rel).replace("\\", "/").split("/"))
            text = library.text_only({"rel_path": rel, "source_type": source_type})
            out[os.path.normcase(os.path.abspath(path))] = (
                item_id, context(seen, place.get(item_id), tier, now), not text)
        return out
    finally:
        if own:
            store.close()


def choose(language, keys, *, here=None, dial=None, never=None, young=None, files=None, reach=None, store=None):
    """The sentences each word's card can be cut from -> {(lemma, reading): [Choice, …]}, best first by the dial
    (the module's docstring); a word with no sentence: []. `keys`: [(lemma, reading)]; `here`: the episode's subtitle
    (Nearest: its lines first; Best: one candidate, kept on a tie); `dial`: NEAREST / BEST, None = the learner's
    setting; `never`: {key: {line text}} — never the same line (Swap passes the old card's sentence); `young`: {lemma:
    weight}, None = `young_weights`; `files`: the library's paths (None = `sentence_corpus.library_files`); `reach(item
    id) -> bool`: can its media be cut (Connect passes its video look-up; None = the file is there) — a sentence whose
    media can't be cut is no choice. A sentence of the library outside the learner's length range is not a candidate
    (the corpus's window), so a word met only in short lines gets [] here and keeps its own episode's line."""
    from app import settings_manager, sentence_corpus, analyzer, token_index
    keys = list(dict.fromkeys(tuple(k) for k in keys or ()))
    if not keys:
        return {}
    settings = settings_manager.load_settings()
    dial = dial if dial in DIALS else dial_of(settings)
    young = young_weights(language) if young is None else dict(young)
    never = {tuple(k): v for k, v in (never or {}).items() if v}
    if files is None:
        files = sentence_corpus.library_files(language)
    here_key = os.path.normcase(os.path.abspath(here)) if here else None
    info = _library(language, store)
    norm = [os.path.normcase(os.path.abspath(f)) for f in files or ()]
    if here_key and here_key not in norm:
        norm.append(here_key)
    # The order the corpus ties on: the most remembered context first, the episode being mined first among equals —
    # so a word's eight kept sentences are the best-placed ones (`collect` keeps at most 8 a word, 2 a file)
    order = sorted(range(len(norm)), key=lambda n: (-(info.get(norm[n], (None, 0.0, True))[1]), norm[n] != here_key, n))
    ordered = [norm[n] for n in order]
    if dial == NEAREST and here_key:
        holding = [here_key]
    else:
        holding = sentence_corpus.files_holding(language, ordered, keys, most=MOST_FILES)
        if here_key and here_key not in holding:
            holding = [here_key] + holding
    out = {key: [] for key in keys}
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
        if item_id not in reached:
            try:
                reached[item_id] = bool(reach(item_id)) if reach is not None and item_id is not None \
                    else os.path.isfile(path)
            except Exception:
                reached[item_id] = False
        return reached[item_id]

    for key in keys:
        word = words.get(key)
        found = []
        for position, (rank, text, fidx, _surface) in enumerate(word.best.result() if word and word.best else ()):
            path = holding[fidx]
            if same_line(text, never.get(key)):
                continue
            item_id, ctx, audio = info.get(path, (None, 0.0, True))
            is_here = path == here_key
            if not is_here and not can_cut(path, item_id):
                continue
            found.append((Choice(path, item_id, text, rank[0], round(ctx + max(0.0, -rank[2]), 4), is_here, audio),
                          position))
        found.sort(key=lambda c: _rank(c[0], dial) + (c[1],))
        out[key] = [c for c, _p in found]
    return out


def _rank(choice, dial):
    """A choice's sort key by the dial (lower first): Nearest — the episode's own first, then as Best; Best — the
    fewest other unknown words, audio, the weight, the episode being mined on a tie."""
    best = (choice.others, not choice.audio, -choice.weight, not choice.here)
    return ((not choice.here),) + best if dial == NEAREST else best


def better(choice, than):
    """Is `choice` strictly better than `than` (Best's rank without the tie to the episode being mined)? A word moves
    to another episode only for a better sentence, never for an equal one."""
    return _rank(choice, BEST)[:3] < _rank(than, BEST)[:3]


def _line(text):
    """A line as `never` compares it: its own characters, spaces and line breaks aside."""
    return "".join(str(text or "").split())


def same_line(text, old):
    """Is `text` one of the lines `old` ({line text}, Swap's old card's sentence) holds — the same characters, or one
    inside the other (an old card's sentence may hold its line's neighbours too)? Never with nothing in `old`."""
    line = _line(text)
    if not line or not old:
        return False
    return any(line == was or line in was or (was and was in line) for was in (_line(t) for t in old))
