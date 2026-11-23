"""The sentence score — one cost for every candidate sentence of a word at the moment it is asked, and the one reader
every piece asks (the card, Swap, *Bad card*, later the list and the journey): `choose`.

**The cost** (`cost`), in units of "one more new word in the sentence"; the lowest wins:

    other new words still unknown when the card is studied (the list's count, at whatever the order has become)
  + 1 for each new set phrase in it
  + the length rule: characters outside the learner's *Length* · fewer than two other words · the late word
  − CONTEXT × how well its file is remembered now (× UNWATCHED when only its show was seen)
  + how its file is heard now
  − YOUNG × the youngest word in it you are still learning

Every rate is one named constant in the block below and is read through one door, `rates()`: nothing else in the app
holds one of these numbers. A changed rate needs no new table — the next call uses it.

**The table** (Generate's, `app/sentence_table.py`: every candidate line of every list row, kept as numbers) is read
here through `_table` (its head, kept per process while the file's stamp holds) and `_take` (the asked rows' blocks)
only. The cost takes its columns as arrays and numbers — no Python object per line — so the
work behind `choose` can change language later.

**Pure in `plan_rules`' sense:** the standard library at the top; numpy is imported inside the functions that need it;
no Tk, Qt, pandas, tokenizer, settings, library store, Anki or Junban. What only the moment knows (the dates, how a
file is heard, the young words, the words known since the Generate) and the learner's Length are handed in by the
caller. The reader reads the token store for the text of the few lines it returns, and checks each line's file is the
one the Generate read.

Ties: the file's own path (from the data folder, "/" separators, as text), then the line's place in the file — never
a file's number, which a Generate changes.

Nothing imports this module while `plan_rules.SENTENCE_TABLE` is 0.
"""
import math
import os
from collections import namedtuple

# --------------------------------------------------------------------------------------------------------------- #
# The rates — every number of the score, in one block (SPEC § 4.1; whose each is: the lane's register)
# --------------------------------------------------------------------------------------------------------------- #

NEW_WORD = 1.0              # another new word in the sentence: the unit
NEW_PHRASE = 1.0            # a new set phrase in it
OUTSIDE = 0.03              # each character shorter or longer than the learner's Length (the zone)
FEW_WORDS = 2               # a line saying fewer than this many other words besides the word...
FEW_WORDS_COST = 0.5        # ...costs this much
LATE_FROM = 2 / 3           # the late word: in a line longer than the zone, the word starting at or past this share...
LATE_COST = 0.3             # ...costs this much
LATE_HABIT = 0.5            # ...unless the word sits there in more than this share of its own long lines
LATE_HABIT_LINES = 5        # ...judged from at least this many long lines (fewer: charged like any other word)
CONTEXT = 0.9               # how well its file is remembered (0 to 1: Connect's `context`) is worth this much
UNWATCHED = 0.8             # an unwatched episode of a started show: its show's context × this
HEARD_REAL = 0.0            # its own clip
HEARD_AI = 0.15             # the AI voice's
HEARD_SILENT = 0.4          # no audio at all: weighed, never removed
YOUNG = 0.3                 # the youngest word in it you are still learning (its weight 0 to 1) is worth this much
YOUNG_LINES = 4             # the leading lines a word already known at the Generate is looked for in (Connect's reach)

Rates = namedtuple("Rates", "new_word new_phrase outside few_words few_words_cost late_from late_cost late_habit "
                            "late_habit_lines context unwatched heard_real heard_ai heard_silent young young_lines")


def rates():
    """The one door to the rates: the block above, as it is now (a later lane lets a learner's own choice in here)."""
    return Rates(NEW_WORD, NEW_PHRASE, OUTSIDE, FEW_WORDS, FEW_WORDS_COST, LATE_FROM, LATE_COST, LATE_HABIT,
                 LATE_HABIT_LINES, CONTEXT, UNWATCHED, HEARD_REAL, HEARD_AI, HEARD_SILENT, YOUNG, YOUNG_LINES)


# --------------------------------------------------------------------------------------------------------------- #
# The shapes a caller hands in and gets back
# --------------------------------------------------------------------------------------------------------------- #

# How a file is heard (Connect's `sentences.heard`, the same values): its own clip, the AI voice's, none
REAL, AI_VOICE, SILENT = "real", "ai", None
_HEARD_CODE = {REAL: 0, AI_VOICE: 1, SILENT: 2}

# A line's mark (SPEC § 3.2, the table's one byte: `sentence_table.OVER`, a test keeps them equal). A sung line has no
# mark: Connect's cut refuses it (the lead, 2026-11-23)
OVER_WALL = 4               # over *Never longer than*: kept as a file's first sentence for the word card, never chosen

# What the moment knows of one file: its library item (None: none), how well it is remembered (0 to 1), how it is
# heard, and whether its date is only its show's (an unwatched episode of a started show: UNWATCHED applies)
Seen = namedtuple("Seen", "item_id context heard show_only", defaults=(None, 0.0, REAL, False))

# The moment: `files` {normalised path (os.path.normcase(os.path.abspath(...))): Seen} — a file it does not name is
# heard by its own clip, remembered not at all · `young` {lemma: weight in (0, 1]} (Connect's `young_weights`) ·
# `known` the list rows' keys {(lemma, reading)} known since the Generate (a key with no reading: every row of the
# lemma) · `root` the data folder the table's paths are from (None: the language's own)
Moment = namedtuple("Moment", "files young known root", defaults=(None, None, None, None))

# One line returned: its file's path and item, its text, its cost, how many other new words and set phrases it holds,
# its characters, the context it was weighed with, how it is heard, and its place among its file's sentences
Line = namedtuple("Line", "file item_id text cost others chars context heard number")

BIG = 1 << 30               # a place no row has: a row off the list, a co-word never known
_RANK_DIGITS = 9            # costs equal to this many decimals are a tie (the same terms summed in another order)
_LINE_COLUMNS = ("row", "src", "number", "chars", "flags", "besides", "start", "hash", "ncow", "ncrowd")
_MOMENT_ARRAYS = ("placed", "placed_now", "known_at", "own", "lemma", "ctx", "show_only", "hear", "young")


# --------------------------------------------------------------------------------------------------------------- #
# The cost: arrays and numbers only
# --------------------------------------------------------------------------------------------------------------- #

def known_at(formulas, placed):
    """Per co-word, the place in the list from which it is known: the least, over its clauses ("known once any of
    these groups of list rows is taught"), of the last place of the clause's rows (-1: an empty clause, known from the
    start; BIG: no clause, never). `formulas`: (own, clauses a co-word, rows a clause, the rows) as arrays; `placed`:
    by row, its place (-1: known already)."""
    import numpy as np
    _own, ncl, cl_len, cl_rows = (np.asarray(a, np.int64) for a in formulas)
    placed = np.asarray(placed, np.int64)
    cl_max = np.full(len(cl_len), -1, np.int64)
    some = cl_len > 0
    if some.any():
        starts = (np.cumsum(cl_len) - cl_len)[some]
        cl_max[some] = np.maximum.reduceat(placed[cl_rows], starts)
    out = np.full(len(ncl), BIG, np.int64)
    some = ncl > 0
    if some.any():
        starts = (np.cumsum(ncl) - ncl)[some]
        out[some] = np.minimum.reduceat(cl_max, starts)
    return out


def _arrays_only(name, values):
    import numpy as np
    for key, value in values.items():
        if not isinstance(value, np.ndarray):
            raise TypeError(f"sentence_score.cost: {name}[{key!r}] is a {type(value).__name__}, not an array")


def cost(columns, moment, low, high, r=None):
    """Every line of `columns` at `moment` -> (cost, other new words + new set phrases, new words alone, the youngest
    co-word's weight), arrays of one value a line; a line over *Never longer than* or sung costs inf.

    `columns` (a word's block or several, each row's lines together): per line "row" (its list row), "src" (its
    file), "number" (its place in the file), "chars", "flags", "besides" (other words it says besides the word),
    "start" (where the word starts, in characters), "hash", "ncow", "ncrowd"; flat "cow" (its other new words, as
    co-words) and "crowd" (its set phrases, as list rows), found by the two counts. `moment`: by row "placed" (its
    place in the list now), "placed_now" (the same, -1 for a row known since the Generate) and "lemma" (one number a lemma:
    a row's other readings are never its young word); by co-word "known_at"
    (`known_at` over "placed_now"), "own" (its own row, -1: none) and "young" (its weight while you are still learning
    it); by file "ctx" (0 to 1), "show_only" (its date is its show's) and "hear" (0 its own clip, 1 the AI voice, 2
    none). `low`, `high`: the learner's Length. `r`: the rates (None: `rates()`)."""
    import numpy as np
    _arrays_only("columns", columns)
    _arrays_only("moment", moment)
    r = r or rates()
    low, high = int(low), int(high)
    row = columns["row"].astype(np.int64)
    n = len(row)
    chars = columns["chars"].astype(np.int64)
    flags = columns["flags"].astype(np.int64)
    src = columns["src"].astype(np.int64)
    placed, placed_now = moment["placed"], moment["placed_now"]
    mine = placed[row]

    # Other new words: a co-word that is not the word itself and not known above it
    lines = np.arange(n, dtype=np.int64)
    cow = columns["cow"].astype(np.int64)
    cow_line = np.repeat(lines, columns["ncow"].astype(np.int64))
    own_c = moment["own"][cow]
    its_own = own_c == row[cow_line]
    known = moment["known_at"][cow] < mine[cow_line]
    words = np.bincount(cow_line[~its_own & ~known], minlength=n)
    # New set phrases: a phrase row that is not the word's own and not taught above it
    crowd = columns["crowd"].astype(np.int64)
    crowd_line = np.repeat(lines, columns["ncrowd"].astype(np.int64))
    new_phrase = (crowd != row[crowd_line]) & ~(placed_now[crowd] < mine[crowd_line])
    phrases = np.bincount(crowd_line[new_phrase], minlength=n)

    # The length rule (SPEC § 4.2): the zone, fewer than two other words, the late word
    outside = np.where(chars < low, low - chars, np.where(chars > high, chars - high, 0))
    few = columns["besides"].astype(np.int64) < r.few_words
    usable = (flags & OVER_WALL) == 0
    long_ = usable & (chars > high)
    late = long_ & (columns["start"].astype(np.float64) >= r.late_from * chars - 1e-9)   # (at exactly 2/3: late)
    _rows, at = np.unique(row, return_inverse=True)
    n_long = np.bincount(at, weights=long_, minlength=len(_rows))
    n_late = np.bincount(at, weights=late, minlength=len(_rows))
    lives_there = (n_long >= r.late_habit_lines) & (n_late > r.late_habit * n_long)
    late_cost = late & ~lives_there[at]

    # The moment: remembered context, how it is heard, the youngest word still being learned
    ctx = moment["ctx"].astype(np.float64) * np.where(moment["show_only"].astype(bool), r.unwatched, 1.0)
    heard = np.asarray((r.heard_real, r.heard_ai, r.heard_silent), np.float64)[moment["hear"].astype(np.int64)]
    young = np.zeros(n)
    lemma = moment["lemma"]            # (never one of the word's own other readings)
    learning = ~its_own & known & (own_c >= 0) & (lemma[np.maximum(own_c, 0)] != lemma[row[cow_line]])
    if learning.any():
        np.maximum.at(young, cow_line[learning], moment["young"].astype(np.float64)[cow[learning]])

    total = (r.new_word * words + r.new_phrase * phrases + r.outside * outside + r.few_words_cost * few
             + r.late_cost * late_cost - r.context * ctx[src] + heard[src] - r.young * young)
    total[~usable] = np.inf
    return total, words + phrases, words, young


# --------------------------------------------------------------------------------------------------------------- #
# The reader
# --------------------------------------------------------------------------------------------------------------- #

_HEAD = {}                  # language -> ((the table's path, time, size, the run's stamp), the table, its head read)


def _table(language):
    """The table the last Generate wrote for `language` (`results/sentences.bin`, `app/sentence_table.py`), its head read
    once a process while the file's (path, time, size) and the run's stamp hold (SPEC § 5.3) — or None: none written,
    another language, engine or run, damaged. Never an exception."""
    try:
        from app import analyzer, sentence_table
        from app.path_utils import get_user_file
        results = get_user_file("results")
        run = analyzer.read_run_stamp(results)
        if not run:
            return None
        path = os.path.join(results, sentence_table.TABLE_FILE)
        st = os.stat(path)
        stamp = (path, st.st_mtime_ns, st.st_size, run)
        hit = _HEAD.get(language)
        if hit is not None and hit[0] == stamp:
            return hit[1]
        _HEAD.pop(language, None)
        tab = sentence_table.open_table(path, language=language, engine=analyzer.engine_id(), run_signature=run)
        if tab is not None:
            _HEAD[language] = (stamp, tab)
        return tab
    except Exception:
        return None


# The cost's columns and the table's own names for them (`sentence_table.COLUMNS`)
_FROM_BLOCK = (("src", "src"), ("number", "number"), ("chars", "chars"), ("flags", "marks"), ("besides", "besides"),
               ("start", "starts"), ("hash", "fp"), ("ncow", "ncow"), ("ncrowd", "nphr"))


def _take(tab, rows):
    """The cost's columns for `rows`' lines, each row's lines together, read from their blocks only."""
    import numpy as np
    parts = [(k, got) for k in rows for got in [tab.block(k)] if got is not None]

    def joined(values):
        return np.concatenate([np.asarray(v, np.int64) for v in values]) if values else np.zeros(0, np.int64)
    cols = {"row": joined([np.full(len(block[0]["number"]), k, np.int64) for k, block in parts])}
    for mine, theirs in _FROM_BLOCK:
        cols[mine] = joined([block[0][theirs] for _k, block in parts])
    cols["cow"] = joined([block[1] for _k, block in parts])
    cols["crowd"] = joined([block[2] for _k, block in parts])
    return cols


def _tokens(language):
    """The token store, opened to read only (the text of the lines returned), or None."""
    try:
        from app import token_index
        return token_index.open_reader(language)
    except Exception:
        return None


def _key_rows(keys):
    """{(lemma, reading): row} and {lemma: [rows]} of the table's list rows."""
    exact, by_lemma = {}, {}
    for k, (lemma, reading) in enumerate(keys):
        exact.setdefault((lemma, reading or ""), k)
        by_lemma.setdefault(lemma, []).append(k)
    return exact, by_lemma


def _row_of(key, exact, by_lemma):
    k = exact.get((key[0], key[1] or ""))
    if k is None and not key[1] and len(by_lemma.get(key[0], ())) == 1:
        k = by_lemma[key[0]][0]         # a key with no reading: the lemma's one row
    return k


def _young(moment):
    """The young words' weights; one that is no finite number is left out (a broken moment never drops a line)."""
    out = {}
    for lemma, weight in (moment.young or {}).items():
        weight = float(weight)
        if math.isfinite(weight) and weight > 0:
            out[lemma] = weight
    return out


def _moment_arrays(tab, moment, order, root, srcs=None):
    """The moment as the cost's arrays, and {file: (path, normalised path, rel, kind, digest, Seen)} for the files
    `srcs` (None: every file); the list's order is `order` when one is handed in, else the table's `places`."""
    import numpy as np
    keys = tab.head["keys"]
    rows = len(keys)
    placed = np.full(rows + 1, BIG, np.int64)
    if order is None:
        for k, at in enumerate(tab.places()):   # the Generate's list order, by row (< 0: not on the list)
            if at >= 0:
                placed[k] = int(at)
    else:
        order = {(key[0], key[1] or ""): place for key, place in order.items()}
        for k, (lemma, reading) in enumerate(keys):
            at = order.get((lemma, reading or ""))
            if at is not None:
                placed[k] = int(at)
    placed_now = placed.copy()
    known = moment.known or ()
    if known:
        exact, by_lemma = _key_rows(keys)
        for key in known:
            hits = by_lemma.get(key[0], ()) if not key[1] else [exact.get((key[0], key[1]))]
            for k in hits:
                if k is not None:
                    placed_now[k] = -1
    codes = {}
    lemma = np.fromiter((codes.setdefault(key[0], len(codes)) for key in keys), np.int64, rows)
    formulas = tab.formulas()
    own = np.asarray(formulas[0], np.int64)
    young_of = _young(moment)
    young = np.fromiter((young_of.get(keys[o][0], 0.0) if 0 <= o < rows else 0.0 for o in own.tolist()),
                        np.float64, len(own))
    files = moment.files or {}
    base = os.path.join(root, "")
    sources = tab.sources()
    ctx, show_only, hear = np.zeros(len(sources)), np.zeros(len(sources), bool), np.zeros(len(sources), np.int8)
    placed_files = {}
    for s in (range(len(sources)) if srcs is None else srcs):
        rel, kind, digest = sources[s]
        path = rel if os.path.isabs(rel) else base + rel.replace("/", os.sep)
        at = os.path.normcase(os.path.abspath(path))
        seen = files.get(at) or Seen()
        placed_files[s] = (path, at, rel, kind, digest, seen)
        context = float(seen.context or 0.0)
        ctx[s] = context if math.isfinite(context) else 0.0
        show_only[s] = bool(seen.show_only)
        hear[s] = _HEARD_CODE.get(seen.heard, 2)
    arrays = {"placed": placed, "placed_now": placed_now, "known_at": known_at(formulas, placed_now), "own": own,
              "lemma": lemma, "ctx": ctx, "show_only": show_only, "hear": hear, "young": young}
    return arrays, placed_files


def _tie_ranks(sources, srcs=None):
    """Each file's rank by its own path from the data folder ("/" separators, compared as text), among `srcs` (None:
    every file; the rest BIG)."""
    import numpy as np
    pick = range(len(sources)) if srcs is None else srcs
    rels = {s: str(sources[s][0]).replace("\\", "/") for s in pick}
    out = np.full(len(sources), BIG, np.int64)
    for rank, s in enumerate(sorted(rels, key=lambda s: (rels[s], s))):
        out[s] = rank
    return out


def _spans(row):
    """{row: (first line, past its last)} of columns whose rows' lines sit together."""
    import numpy as np
    if not len(row):
        return {}
    cut = np.flatnonzero(row[1:] != row[:-1]) + 1
    starts = np.concatenate(([0], cut))
    ends = np.concatenate((cut, [len(row)]))
    return {int(row[a]): (int(a), int(b)) for a, b in zip(starts, ends)}


def _ranked(total, number, tie, src, a, b):
    """The lines a..b that can be chosen, the lowest cost first; ties by the file's path, then the line's place."""
    import numpy as np
    c = total[a:b]
    cand = np.flatnonzero(np.isfinite(c))
    by = np.lexsort((number[a:b][cand], tie[src[a:b][cand]], np.round(c[cand], _RANK_DIGITS)))
    return (cand[by] + a).tolist()


def choose(language, keys, *, n=1, moment, length, never=None, order=None, only=None, heard_first=False,
           clean_only=False, shown=None, whole=False, table=None):
    """The best `n` sentences of each list row asked, at `moment` -> {(lemma, reading): [Line, …]}, best first ([] for
    a row with no line it can use; a key that is no row of the list is left out: the caller's library search); None
    when there is no table for `language` — the caller takes today's path. "New when studied" is weighed by `order`
    when one is handed in, else by the table's `places` (the last Generate's list).

    `keys` the rows asked · `moment` a `Moment` · `length` the learner's Length (low, high) · `never` {key: {line text}}
    lines never returned (Swap's old card: Connect's `same_line`) · `order` {key: place} the list's order when it is
    not the last Generate's (after a move) · `only` the files to stay inside (paths) · `heard_first` the first line is
    the best heard one whenever the word has one (*Ensure an audio example*) · `clean_only` only lines with no other
    new word (*Only i+1*) · `shown` {(rel, number): text} the kept text of lines already shown, read before the token
    store · `whole` every row of the table scored in one pass (the redraw) · `table` a table in memory (tests; inside
    Generate)."""
    try:
        tab = table if table is not None else _table(language)
    except Exception:
        tab = None
    if tab is None:
        return None
    try:
        return _choose(tab, language, keys, n, moment, length, never, order, only, heard_first, clean_only, shown,
                       whole)
    except Exception:
        return None             # a table damaged inside its blocks, a moment it can't read: the caller's own path


def _choose(tab, language, keys, n, moment, length, never, order, only, heard_first, clean_only, shown, whole):
    import numpy as np
    keys = list(dict.fromkeys(tuple(k) for k in keys or ()))
    exact, by_lemma = _key_rows(tab.head["keys"])
    asked = {key: k for key in keys for k in [_row_of(key, exact, by_lemma)] if k is not None}
    out = {key: [] for key in asked}
    if not asked:
        return out
    root = moment.root
    if root is None:
        from app.path_utils import get_data_path
        root = get_data_path(language)
    with_lines = set(tab.rows().values())
    columns = _take(tab, sorted(with_lines) if whole else sorted({k for k in asked.values() if k in with_lines}))
    srcs = np.unique(columns["src"]).tolist()
    arrays, files = _moment_arrays(tab, moment, order, root, srcs)
    low, high = length
    total, others, words, co_young = cost(columns, arrays, low, high)
    spans = _spans(columns["row"])
    tie = _tie_ranks(tab.sources(), srcs)
    src_a, num_a, hash_a, chars_a = columns["src"], columns["number"], columns["hash"], columns["chars"]
    inside = None if only is None else {os.path.normcase(os.path.abspath(p)) for p in only}
    never_rows = {}             # by row: a key named with or without its reading is the same row's
    for key, texts in (never or {}).items():
        k = _row_of(tuple(key), exact, by_lemma)
        if texts and k is not None:
            never_rows.setdefault(k, []).extend(texts)
    young_of = _young(moment)
    hear = arrays["hear"]
    r = rates()

    tokens = [None]
    read, there, stamps = {}, {}, {}

    def store():
        if tokens[0] is None:
            tokens[0] = _tokens(language) or False
        return tokens[0]

    def held(src):
        at = files[src][1]
        if at not in read:
            cache = store()
            try:
                read[at] = cache.file_tokens(at) if cache else []
            except Exception:
                read[at] = []
        return read[at]

    def as_read(src):
        """Is the file the one the Generate read: there, its digest (path, time, size, kind) the table's — or, with
        no digest (a watched or Finished source), its time and size the token store's?"""
        if src not in there:
            path, at, rel, kind, digest, _seen = files[src]
            try:
                st = os.stat(path)
                if digest is not None:
                    from app import plan_rules
                    there[src] = any(plan_rules.file_digest([signed, [st.st_mtime, st.st_size], None, None, kinds])
                                     == digest for signed in dict.fromkeys((os.path.join(root, rel), path))
                                     for kinds in ((kind, None) if not kind else (kind,)))
                else:
                    cache = store()
                    if at not in stamps and cache:
                        stamps.update(cache.file_stamps([at]))
                    there[src] = stamps.get(at) == [st.st_mtime, st.st_size]
            except Exception:
                there[src] = False
        return there[src]

    def text_of(src, number):
        if shown is not None:
            got = shown.get((files[src][2], number))
            if got is not None:
                return got
        sentences = held(src)
        return str(sentences[number][0]).strip() if 0 <= number < len(sentences) else None

    def young_in(src, number):
        """The youngest word the line holds that is no row of the list, read from the token store: a word known before
        the Generate is no co-word of the table (a row's young weight is the cost's, by its place)."""
        sentences = held(src)
        if not (0 <= number < len(sentences)):
            return 0.0
        return max((young_of.get(t[0], 0.0) for t in sentences[number][1] if t and t[0] not in by_lemma),
                   default=0.0)

    same_line = None
    if never_rows:
        from app.connect.sentences import same_line
    try:
        for key, k in asked.items():
            a, b = spans.get(k, (0, 0))
            if a == b:
                continue
            banned = never_rows.get(k)
            # (a word with no heard line it could use is walked as without the ask: never every line of it)
            heard_ask = heard_first and bool((np.isfinite(total[a:b]) & (hear[src_a[a:b]] != 2)).any())
            taken, texts = [], set()
            heard_one = False
            for i in _ranked(total, num_a, tie, src_a, a, b):
                if len(taken) >= max(n, YOUNG_LINES if young_of else 0) and (not heard_ask or heard_one):
                    break
                src, number, repeat = int(src_a[i]), int(num_a[i]), int(hash_a[i])
                if repeat and repeat in texts:
                    continue            # the same sentence twice: never
                if inside is not None and files[src][1] not in inside:
                    continue
                if clean_only and words[i]:
                    continue
                if not as_read(src):
                    continue            # its file changed or left since the Generate: every line of it skipped
                text = text_of(src, number)
                if text is None or (banned and same_line(text, banned)):
                    continue
                if repeat:
                    texts.add(repeat)
                line_cost = float(total[i])
                if young_of and len(taken) < YOUNG_LINES:
                    held_young = young_in(src, number)
                    old = line_cost
                    # (the co-words' youngest is in the cost already: only a younger one moves it)
                    line_cost = old - r.young * max(0.0, held_young - float(co_young[i]))
                seen = files[src][5]
                heard_one = heard_one or _HEARD_CODE.get(seen.heard, 2) != 2
                taken.append((round(line_cost, _RANK_DIGITS), int(tie[src]), number, len(taken),
                              Line(files[src][0], seen.item_id, text, round(line_cost, 4), int(others[i]),
                                   int(chars_a[i]), round(float(arrays["ctx"][src]) * (r.unwatched if seen.show_only
                                                                                       else 1.0), 4),
                                   seen.heard, number)))
            lead = sorted(taken[:YOUNG_LINES]) if young_of else taken[:YOUNG_LINES]
            ordered = [t[-1] for t in lead + taken[YOUNG_LINES:]]
            if heard_ask and ordered and _HEARD_CODE.get(ordered[0].heard, 2) == 2:
                first = next((line for line in ordered if _HEARD_CODE.get(line.heard, 2) != 2), None)
                if first is not None:
                    ordered = [first] + [line for line in ordered if line is not first]
            out[key] = ordered[:n]
    finally:
        if tokens[0]:
            try:
                tokens[0].close()
            except Exception:
                pass
    return out
