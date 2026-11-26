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

# numpy's BLAS (OpenBLAS, in numpy's own wheels) starts a thread and reserves a buffer for every CPU thread at numpy's
# first import: 759 MB of private memory on a 24-thread desktop, 20 MB held to one (measured, E-FAST). Nothing the
# score or the table does calls BLAS (counts, sorts and reductions: no dot, matmul or linalg), so the first import
# through here holds it to one thread; the variables are put back at once, so no child process (Anki Miner's speech
# model) is given them. One the learner set is left as it is.
_BLAS_THREADS = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")


def numpy_one_thread():
    """numpy, imported once a process with its BLAS held to one thread (`_BLAS_THREADS`) — or as it is when something
    imported it already. The score's own door to it (`_table`) and Connect's (`connect.sentences.known_since`)."""
    import sys
    if "numpy" not in sys.modules:
        mine = [name for name in _BLAS_THREADS if name not in os.environ]
        try:
            os.environ.update({name: "1" for name in mine})
            import numpy  # noqa: F401
        finally:
            for name in mine:
                os.environ.pop(name, None)
    import numpy
    return numpy

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
_HEARD_OF = {code: heard for heard, code in _HEARD_CODE.items()}

# A line's mark (SPEC § 3.2, the table's one byte: `sentence_table.OVER`, a test keeps them equal). A sung line has no
# mark: Connect's cut refuses it (the lead, 2026-11-23)
OVER_WALL = 4               # over *Never longer than*: kept as a file's first sentence for the word card, never chosen

# What the moment knows of one file: its library item (None: none), how well it is remembered (0 to 1), how it is
# heard, whether its date is only its show's (an unwatched episode of a started show: UNWATCHED applies), and — a book
# lined up with its audiobook (Kyou-PB) — which of its lines its line-up says (`said`: line text -> bool; None: every
# line is heard as the file is) and how a line it never says is heard (`unsaid`: the book with no audiobook's)
Seen = namedtuple("Seen", "item_id context heard show_only said unsaid",
                  defaults=(None, 0.0, REAL, False, None, SILENT))

# The moment: `files` {normalised path (os.path.normcase(os.path.abspath(...))): Seen} — a file it does not name is
# remembered not at all and heard as `unnamed` says · `young` {lemma: weight in (0, 1]} (Connect's `young_weights`) ·
# `known` the list rows' keys {(lemma, reading)} known since the Generate (a key with no reading: every row of the
# lemma) · `root` the data folder the table's paths are from (None: the language's own) · `unnamed` (its path) -> how
# a file `files` does not name is heard, REAL / AI_VOICE / SILENT (Connect's rule for a file outside its library: a
# book or a text by its extension), so the score's order is the caller's; None, or no answer: by its own clip
Moment = namedtuple("Moment", "files young known root unnamed", defaults=(None, None, None, None, None))

# One line returned: its file's path and item, its text, its cost, how many other new words and set phrases it holds,
# its characters, the context it was weighed with, how it is heard, and its place among its file's sentences
Line = namedtuple("Line", "file item_id text cost others chars context heard number")

BIG = 1 << 30               # a place no row has: a row off the list, a co-word never known
_RANK_DIGITS = 9            # costs equal to this many decimals are a tie (the same terms summed in another order)
_TIE = 10.0 ** -_RANK_DIGITS
_LATER = object()           # a line's text not known yet (`_choose`'s `peek`): read once the walk is over
_Later = namedtuple("_Later", "src number")     # (where a line taken so sits in its Line until then)
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


def cost(columns, moment, low, high, r=None, kept=None):
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
    none); optionally by line "line_hear" (how that line is heard, as "hear"; -1: its file's — a lined-up book's line
    its line-up does or doesn't say). `low`, `high`: the learner's Length. `r`: the rates (None: `rates()`). `kept`: a
    dict a caller keeps across asks of the same columns in other orders (*Only i+1*'s rounds): what no order changes
    is worked out at the first and read back at the next (`_cost_free`) — only the order's own parts are worked out
    again, the same values summed in the same order."""
    import numpy as np
    _arrays_only("columns", columns)
    _arrays_only("moment", moment)
    r = r or rates()
    low, high = int(low), int(high)
    free = _cost_free(columns, moment, low, high, r, kept)
    row, n, src, cow, cow_x, line_x = (free[name] for name in ("row", "n", "src", "cow", "cow_x", "line_x"))
    placed, placed_now = moment["placed"], moment["placed_now"]
    mine = placed[row]

    # Other new words: a co-word that is not the word itself (`_cost_free`) and not known above it
    words = np.bincount(line_x[~(moment["known_at"][cow_x] < mine[line_x])], minlength=n)
    # New set phrases: a phrase row that is not the word's own and not taught above it
    crowd, crowd_line = free["crowd"], free["crowd_line"]
    new_phrase = free["not_own_phrase"] & ~(placed_now[crowd] < mine[crowd_line])
    phrases = np.bincount(crowd_line[new_phrase], minlength=n)

    outside, few, usable, late_cost, ctx, heard = (free[name] for name in ("outside", "few", "usable", "late_cost",
                                                                           "ctx", "heard"))
    young = np.zeros(n)
    lemma = moment["lemma"]            # (never one of the word's own other readings)
    weights = moment["young"].astype(np.float64, copy=False)
    # (np.maximum from zeros leaves a line as it was for a weight <= 0, so only the co-words with another weight are
    # read — none at all for a learner with no young card: 1.69 M co-words at a 400-file Chinese library, E-FAST 6)
    has = ~(weights <= 0)
    if has.any():
        some = np.flatnonzero(has[cow])
        line_of = np.searchsorted(free["cow_at"], some, side="right") - 1      # (each co-word's line)
        own_s = moment["own"][cow[some]]
        row_s = row[line_of]
        known_s = moment["known_at"][cow[some]] < mine[line_of]
        learning = (own_s != row_s) & known_s & (own_s >= 0) & (lemma[np.maximum(own_s, 0)] != lemma[row_s])
        if learning.any():
            np.maximum.at(young, line_of[learning], weights[cow[some][learning]])

    total = (r.new_word * words + r.new_phrase * phrases + r.outside * outside + r.few_words_cost * few
             + r.late_cost * late_cost - r.context * ctx[src] + heard - r.young * young)
    total[~usable] = np.inf
    return total, words + phrases, words, young


def _cost_free(columns, moment, low, high, r, kept):
    """What `cost` reads that no order changes, for these columns, Length, rates and the moment's order-free arrays
    — the co-words that are not their line's own word (`cow_x`, `line_x`: 32 bits a value where they fit), the
    phrases' rows, the length rule, how each line is heard — worked out now, or read back from `kept` (a dict) when
    its last were for the same ones (*Only i+1* asked the cost again whole at each of its rounds: E-PICK)."""
    import numpy as np
    mark = (columns, moment["own"], moment["ctx"], moment["show_only"], moment["hear"], moment.get("line_hear"))
    if kept is not None:
        was = kept.get("for")
        # (the columns by identity; the moment's arrays by value too: a round in the table's own order reads them
        # from the picks' cache, a round in another from the memo — the same values, other objects)
        if (was is not None and was[1:] == (low, high, r) and len(was[0]) == len(mark) and was[0][0] is mark[0]
                and all(a is b or (isinstance(a, np.ndarray) and isinstance(b, np.ndarray) and a.dtype == b.dtype
                                   and np.array_equal(a, b)) for a, b in zip(was[0][1:], mark[1:]))):
            return kept["free"]
    # (copy=False: a column already int64 — every one `_take` hands in — is read as it is, never copied; nothing below
    # writes into one)
    row = columns["row"].astype(np.int64, copy=False)
    n = len(row)
    chars = columns["chars"].astype(np.int64, copy=False)
    flags = columns["flags"].astype(np.int64, copy=False)
    src = columns["src"].astype(np.int64, copy=False)
    lines = np.arange(n, dtype=np.int64)
    cow = columns["cow"].astype(np.int64, copy=False)
    ncow = columns["ncow"].astype(np.int64, copy=False)
    cow_line = np.repeat(lines, ncow)
    other = np.flatnonzero(moment["own"][cow] != row[cow_line])      # (a co-word that is its line's own word: never)
    narrow = np.int32 if n < 2 ** 31 and (not len(cow) or int(cow.max()) < 2 ** 31) else np.int64
    cow_x, line_x = cow[other].astype(narrow), cow_line[other].astype(narrow)
    del cow_line, other
    cow_at = np.zeros(n + 1, np.int64)
    np.cumsum(ncow, out=cow_at[1:])
    crowd = columns["crowd"].astype(np.int64, copy=False)
    crowd_line = np.repeat(lines, columns["ncrowd"].astype(np.int64, copy=False))
    not_own_phrase = crowd != row[crowd_line]

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

    # The moment: remembered context, how it is heard
    ctx = moment["ctx"].astype(np.float64) * np.where(moment["show_only"].astype(bool), r.unwatched, 1.0)
    hear = moment["hear"].astype(np.int64)[src]
    line_hear = moment.get("line_hear")
    if line_hear is not None:
        line_hear = line_hear.astype(np.int64)
        hear = np.where(line_hear >= 0, line_hear, hear)
    heard = np.asarray((r.heard_real, r.heard_ai, r.heard_silent), np.float64)[hear]
    free = {"row": row, "n": n, "src": src, "cow": cow, "cow_x": cow_x, "line_x": line_x, "cow_at": cow_at,
            "crowd": crowd, "crowd_line": crowd_line, "not_own_phrase": not_own_phrase, "outside": outside,
            "few": few, "usable": usable, "late_cost": late_cost, "ctx": ctx, "heard": heard}
    if kept is not None:
        kept["for"], kept["free"] = (mark, low, high, r), free
    return free


# --------------------------------------------------------------------------------------------------------------- #
# The reader
# --------------------------------------------------------------------------------------------------------------- #

_HEAD = {}                  # language -> ((the table's path, time, size, the run's stamp), the table, its head read)


def _table(language):
    """The table the last Generate wrote for `language` (`results/sentences.bin`, `app/sentence_table.py`), its head read
    once a process while the file's (path, time, size) and the run's stamp hold (SPEC § 5.3) — or None: none written,
    another language, engine or run, damaged. Never an exception."""
    try:
        numpy_one_thread()
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
    got = tab.blocks(rows)                  # (the table's file opened once for every asked row's block)
    parts = [(k, got[k]) for k in rows if got.get(k) is not None]

    def joined(values):
        # (one join, then one conversion: the same numbers as each block's own made int64 before the join)
        return np.concatenate(values).astype(np.int64, copy=False) if values else np.zeros(0, np.int64)
    cols = {"row": np.repeat(np.asarray([k for k, _block in parts], np.int64),
                             [len(block[0]["number"]) for _k, block in parts])}
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


_INDEX = []                 # [(the table, its `_key_rows`, its rows that hold lines)]: the last table asked


def _table_rows(tab):
    """`_key_rows` of the table's keys and the rows that hold lines — the table's alone, so worked out once a table
    (`_table` keeps one a process), never once a caller's memo: Connect's Swap brings a new memo each call (G12)."""
    hit = _INDEX[0] if _INDEX else None            # (one read: another thread may replace the entry)
    if hit is None or hit[0] is not tab:
        hit = (tab, _key_rows(tab.head["keys"]), frozenset(tab.rows().values()))
        _INDEX[:] = [hit]
    return hit[1], hit[2]


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


def _line_text(sentence):
    """A line's text as the token store holds it, stripped — None for an entry held badly (that line unread alone)."""
    try:
        return str(sentence[0]).strip()
    except Exception:
        return None


def _youngest(sentence, young_of, by_lemma):
    """A line's youngest word that is no row of the list: the highest of `young_of`'s weights among its tokens, 0 with
    none (every weight is above 0: `_young`) or for an entry held badly (that line alone)."""
    best = 0.0
    try:
        for t in sentence[1] or ():
            if t and t[0] in young_of and t[0] not in by_lemma:
                weight = young_of[t[0]]
                if weight > best:
                    best = weight
    except Exception:
        return 0.0
    return best


def _moment_arrays(tab, moment, order, root, srcs=None, kept=None):
    """The moment as the cost's arrays, and {file: (path, normalised path, rel, kind, digest, Seen)} for the files
    `srcs` (None: every file); the list's order is `order` when one is handed in, else the table's `places`. `kept` (a
    pick's memo, `_kept`): the rows' arrays built at its first ask and each file's entry once, the files a later ask
    adds read then (the lead's waste card F6) — the arrays handed back are a copy an ask may add to."""
    sources = tab.sources()
    if kept is not None and "arrays" in kept:
        arrays, placed_files = kept["arrays"], kept["files"]
    else:
        by_file, placed_files = _files_kept(tab, moment, root)
        arrays = dict(_rows_kept(tab, moment, order, kept))
        arrays.update(by_file)
        if kept is not None:
            kept["arrays"], kept["files"] = arrays, placed_files
    ctx, show_only, hear = arrays["ctx"], arrays["show_only"], arrays["hear"]
    files = moment.files or {}
    base = os.path.join(root, "")
    for s in (range(len(sources)) if srcs is None else srcs):
        if s in placed_files:
            continue
        rel, kind, digest = sources[s]
        path = rel if os.path.isabs(rel) else base + rel.replace("/", os.sep)
        at = os.path.normcase(os.path.abspath(path))
        seen = files.get(at) or Seen(heard=_unnamed(moment, path))
        context = float(seen.context or 0.0)
        ctx[s] = context if math.isfinite(context) else 0.0
        show_only[s] = bool(seen.show_only)
        hear[s] = _HEARD_CODE.get(seen.heard, 2)
        placed_files[s] = (path, at, rel, kind, digest, seen)     # (last: a placed file's arrays are written)
    return dict(arrays), placed_files


def _unnamed(moment, path):
    """How a file the moment does not name is heard: `moment.unnamed`'s answer — none, or one it can't give: its own
    clip."""
    if moment.unnamed is None:
        return REAL
    try:
        got = moment.unnamed(path)
    except Exception:
        return REAL
    return got if got in _HEARD_CODE else REAL


_FILES = []                 # [((the table, its sources, the moment's files, its `unnamed`), the data folder, kept)]


def _files_kept(tab, moment, root):
    """The files' arrays ("ctx", "show_only", "hear") and {file: entry} that `_moment_arrays` fills, kept across picks
    for one table, data folder and moment's `files` and `unnamed` (the same objects: Connect keeps its dates while the
    store is unchanged) — each pick placed every file of its words' lines again. Filled as asks name files; a moment's
    `files` is read as it was handed in (another dict, another moment: placed again)."""
    import numpy as np
    held = (tab, tab.sources(), moment.files, moment.unnamed)
    hit = _FILES[0] if _FILES else None            # (one read: another thread may replace the entry)
    if hit is not None and all(a is b for a, b in zip(hit[0], held)) and hit[1] == root:
        return hit[2]
    n = len(held[1])
    kept = ({"ctx": np.zeros(n), "show_only": np.zeros(n, bool), "hear": np.zeros(n, np.int8)}, {})
    _FILES[:] = [(held, root, kept)]
    return kept


_ROWS = []                  # [(the table, its keys and places, the moment's known and young words, the rows' arrays)]


def _rows_kept(tab, moment, order, kept=None):
    """`_row_arrays`, kept across picks for one table while its keys and places (the same objects: the entry holds them)
    and the moment's known and young words are the same (a session's picks: the arrays were built at every pick); with
    an `order` handed in (a move's, a Generate's round), the order's arrays built each time over the order-free ones
    (`_row_free`) a pick's memo `kept` holds across its orders — *Only i+1*'s second round built them again (E-L2G 4).
    The kept arrays (across picks, across a memo's orders) are read-only: a reader that wrote into them would fail (its
    caller's own path), never change the next pick's."""
    if order is not None:
        if kept is None:
            return _row_arrays(tab, moment, order)
        if "free" not in kept:
            free = _row_free(tab, moment)
            for a in free.values():
                a.flags.writeable = False   # (shared by the memo's orders: read-only, as the arrays kept across picks)
            kept["free"] = free
        return _row_arrays(tab, moment, order, kept["free"], kept.get("rows"))
    try:
        key = (frozenset(moment.known or ()), tuple(sorted(_young(moment).items())))
    except TypeError:                       # (a moment whose words can't be compared: built each time)
        return _row_arrays(tab, moment, order)
    held = (tab, tab.head.get("keys"), tab.head.get("places"))
    hit = _ROWS[0] if _ROWS else None              # (one read: another thread may replace the entry)
    if hit is not None and all(a is b for a, b in zip(hit[0], held)) and hit[1] == key:
        return hit[2]
    arrays = _row_arrays(tab, moment, order)
    for a in arrays.values():
        a.flags.writeable = False
    _ROWS[:] = [(held, key, arrays)]
    return arrays


def _row_free(tab, moment):
    """The moment's arrays over the table's rows that no order changes: each row's lemma code ("lemma"), each co-word's
    row ("own") and its young weight ("young")."""
    import numpy as np
    keys = tab.head["keys"]
    rows = len(keys)
    codes = {}
    lemma = np.fromiter((codes.setdefault(key[0], len(codes)) for key in keys), np.int64, rows)
    own = np.asarray(tab.formulas()[0], np.int64)
    young_of = _young(moment)
    young = np.fromiter((young_of.get(keys[o][0], 0.0) if 0 <= o < rows else 0.0 for o in own.tolist()),
                        np.float64, len(own))
    return {"own": own, "lemma": lemma, "young": young}


def _row_arrays(tab, moment, order, free=None, key_rows=None):
    """The moment's arrays over the table's rows: the list's order, the words known since, the young words. `free`:
    `_row_free`'s for this table and moment (None: built now); `key_rows`: `_key_rows`' of its keys (None: made now)."""
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
            if at is not None and at >= 0:       # < 0: off the list, as in `places`
                placed[k] = int(at)
    placed_now = placed.copy()
    known = moment.known or ()
    if known:
        exact, by_lemma = key_rows if key_rows is not None else _table_rows(tab)[0]
        for key in known:
            hits = by_lemma.get(key[0], ()) if not key[1] else [exact.get((key[0], key[1]))]
            for k in hits:
                if k is not None:
                    placed_now[k] = -1
    if free is None:
        free = _row_free(tab, moment)
    return {"placed": placed, "placed_now": placed_now, "known_at": known_at(tab.formulas(), placed_now), **free}


def _kept(memo, tab, moment, order, root):
    """A pick's memo (`choose`'s `memo`) for this table, moment, order and data folder — what its asks share, built at
    the first and kept for the rest; emptied when any of the four differs from the asks before — but for another
    order alone, which keeps what no order changes (the rows' index, the columns taken, each file's text, check and
    stamp: *Only i+1*'s second round read them all again, E-L2G; the rows' order-free arrays, `_row_free`: E-L2G 4)
    and drops the rows' other arrays and the costs, which are the order's. None: no memo."""
    if memo is None:
        return None
    was = memo.get("for")
    if was is not None and was[0] is tab and was[1] is moment and was[3] == root:
        if was[2] is not order:
            for name in ("arrays", "files", "costed"):
                memo.pop(name, None)
            memo["for"] = (tab, moment, order, root)
        return memo
    memo.clear()
    memo["for"] = (tab, moment, order, root)
    return memo


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


_RANK_FIRST = 64            # the lines `_ranked` puts in order before the walk asks for more (a pick takes one or two)


def _ranked(total, number, tie, src, a, b, within=None, first=_RANK_FIRST):
    """The lines a..b that can be chosen, the lowest cost first; ties by the file's path, then the line's place —
    `within` (file numbers): only those files' lines. Yielded as the walk takes them: the `first` lowest, with every
    line tied with the last of them, put in order, the rest only when the walk goes past them — the whole sort's order
    (a common word's 40,000 lines were sorted for the line or two a pick reads)."""
    import numpy as np
    c = total[a:b]
    ok = np.isfinite(c)
    if within is not None:
        ok &= np.isin(src[a:b], within)
    cand = np.flatnonzero(ok)
    costs = np.round(c[cand], _RANK_DIGITS)
    parts = [slice(None)]
    if len(cand) > first:
        head = costs <= np.partition(costs, first - 1)[first - 1]
        parts = [head, ~head]               # (every line of the rest costs more than every line of the head)
    for part in parts:
        at = cand[part]
        by = np.lexsort((number[a:b][at], tie[src[a:b][at]], costs[part]))
        yield from (at[by] + a).tolist()


def choose(language, keys, *, n=1, moment, length, never=None, order=None, only=None, heard_first=False,
           clean_only=False, shown=None, whole=False, table=None, memo=None):
    """The best `n` sentences of each list row asked, at `moment` -> {(lemma, reading): [Line, …]}, best first ([] for
    a row with no line it can use; a key that is no row of the list is left out: the caller's library search); None
    when there is no table for `language`, or one it cannot read — the caller takes today's path. "New when studied" is weighed by `order`
    when one is handed in, else by the table's `places` (the last Generate's list).

    `keys` the rows asked · `moment` a `Moment` · `length` the learner's Length (low, high) · `never` {key: {line text}}
    lines never returned (Swap's old card: Connect's `same_line`) · `order` {key: place} the list's order when it is
    not the last Generate's (after a move) · `only` the files to stay inside (paths) · `heard_first` the first line is
    the best heard one whenever the word has one (*Ensure an audio example*) · `clean_only` only lines with no other
    new word (*Only i+1*) · `shown` {(rel, number): text} the kept text of lines already shown, read before the token
    store · `whole` every row of the table scored in one pass (the redraw) · `table` a table in memory (tests; inside
    Generate) · `memo` a dict one caller keeps across the asks of one pick (Connect's): the rows' index, the moment's
    arrays, each file's place, check and text built once for its table and moment (`_kept`), the choices the same."""
    try:
        tab = table if table is not None else _table(language)
    except Exception:
        tab = None
    if tab is None:
        return None
    try:
        return _choose(tab, language, keys, n, moment, length, never, order, only, heard_first, clean_only, shown,
                       whole, memo)
    except Exception:
        return None             # a table damaged inside its blocks, a moment it can't read: the caller's own path


def _choose(tab, language, keys, n, moment, length, never, order, only, heard_first, clean_only, shown, whole,
            memo=None):
    import numpy as np
    keys = list(dict.fromkeys(tuple(k) for k in keys or ()))
    root = moment.root
    if root is None:
        from app.path_utils import get_data_path
        root = get_data_path(language)
    kept = _kept(memo, tab, moment, order, root)
    shared = kept if kept is not None else {}
    key_rows, with_lines = _table_rows(tab)
    shared["rows"] = key_rows                       # (`_rows_kept`' arrays read it from the memo)
    exact, by_lemma = key_rows
    asked = {key: k for key in keys for k in [_row_of(key, exact, by_lemma)] if k is not None}
    out = {key: [] for key in asked}
    if not asked:
        return out
    want = sorted(with_lines) if whole else sorted({k for k in asked.values() if k in with_lines})
    inside = None if only is None else {os.path.normcase(os.path.abspath(p)) for p in only}
    # (a pick's later asks — more lines of a word, the mined episode's own — are rows its first ask took and costed at
    # the same moment and Length: a line's cost is its own row's alone, so those columns and costs, never again)
    done = shared.get("costed")
    again = done is not None and done[0].issuperset(want) and done[1] == (tuple(length), shown) and (
        done[2] is None or (inside is not None and inside <= done[2]))
    if again:
        columns, srcs, arrays, files, spans, tie = done[3]
    else:
        # (the rows' columns, their files and where each row's lines sit: the same at every order — `_kept`)
        taken = shared.get("taken")
        if taken is None or taken[0] != want:
            columns = _take(tab, want)
            srcs = np.unique(columns["src"]).tolist()
            taken = (want, columns, srcs, _spans(columns["row"]), _tie_ranks(tab.sources(), srcs))
            if kept is not None:
                shared["taken"] = taken
        _want, columns, srcs, spans, tie = taken
        arrays, files = _moment_arrays(tab, moment, order, root, srcs, kept)
    low, high = length
    src_a, num_a, hash_a, chars_a = columns["src"], columns["number"], columns["hash"], columns["chars"]
    never_rows = {}             # by row: a key named with or without its reading is the same row's
    for key, texts in (never or {}).items():
        k = _row_of(tuple(key), exact, by_lemma)
        if texts and k is not None:
            never_rows.setdefault(k, []).extend(texts)
    young_of = _young(moment)
    r = rates()

    tokens = [None]
    # (a file's text, its check and its stamp: the same for every ask of one pick)
    read, there, stamps, part = (shared.setdefault(name, {}) for name in ("read", "there", "stamps", "part"))

    def store():
        if tokens[0] is None:
            tokens[0] = _tokens(language) or False
        return tokens[0]

    def held(src):
        """What the walk reads of a file, decoded once: its lines' texts and, with young words, each line's youngest
        word that is no row — (texts, weights or None). Its tokens are let go at once: a list's call touches nearly
        every file, and a file's tokens weigh ~18× its texts (E-REDRAW: +337 MB at 2k); with no young word they are
        not decoded at all (`file_texts`: every list call; E-L2G)."""
        at = files[src][1]
        got = read.get(at)
        if got is None:
            cache = store()
            try:
                texts_of = None if young_of or not cache else getattr(cache, "file_texts", None)
                texts = texts_of(at) if texts_of is not None else None
                if texts is not None:
                    got = (tuple(text.strip() for text in texts), None)     # (`_line_text`'s, of a JSON string)
                else:
                    sentences = cache.file_tokens(at) if cache else []
                    got = (tuple(map(_line_text, sentences)),
                           tuple(_youngest(s, young_of, by_lemma) for s in sentences) if young_of else None)
            except Exception:
                got = ((), None)
            read[at] = got
        return got

    def as_read(src):
        """Is the file the one the Generate read: there, its digest (`sentence_table.source_digest`: its path in one
        spelling, time, size, kind) the table's — or, with no digest (a watched or Finished source), its time and size
        the token store's?"""
        if src not in there:
            path, at, _rel, kind, digest, _seen = files[src]
            try:
                st = os.stat(path)
                if digest is not None:
                    from app.sentence_table import source_digest
                    there[src] = any(source_digest(path, [st.st_mtime, st.st_size], kinds) == digest
                                     for kinds in ((kind, None) if not kind else (kind,)))
                else:
                    cache = store()
                    if at not in stamps and cache:
                        stamps.update(cache.file_stamps([at]))
                    there[src] = stamps.get(at) == [st.st_mtime, st.st_size]
            except Exception:
                there[src] = False
        return there[src]

    def peek(src, number):
        """A line's text when it is known already — shown, its file read whole, or the line read alone — else
        `_LATER` (None: the line has none)."""
        if shown is not None:
            got = shown.get((files[src][2], number))
            if got is not None:
                return got
        at = files[src][1]
        got = read.get(at)
        if got is not None:
            texts = got[0]
            return texts[number] if 0 <= number < len(texts) else None
        return part.get(at, {}).get(number, _LATER)

    def text_of(src, number):
        got = peek(src, number)
        if got is _LATER:
            texts = held(src)[0]
            got = texts[number] if 0 <= number < len(texts) else None
        return got

    def resolve(asked):
        """The texts of the lines a walk took before it read them, `asked` {src: numbers}: each file's lines alone
        (`Store.some_texts`: only theirs decoded, one query a batch of files), or the whole file as `held` reads it
        where that can't tell — the same text either way (E-PICK: the walk decoded 454 whole files at 2k for 1,461
        lines)."""
        by_file = {}
        for src, numbers in asked.items():
            at = files[src][1]
            if at not in read:
                have = part.get(at, {})
                need = [x for x in numbers if x not in have]
                if need:
                    by_file.setdefault(at, (src, set()))[1].update(need)
        if not by_file:
            return
        cache = store()
        got = None
        if cache and getattr(cache, "some_texts", None) is not None:
            try:
                got = cache.some_texts({at: sorted(numbers) for at, (_src, numbers) in by_file.items()})
            except Exception:
                got = None
        for at, (src, numbers) in by_file.items():
            texts = got.get(at) if got is not None else None
            if texts is None:
                held(src)                       # (in doubt: read whole, as a line read alone always was)
            else:
                mine = part.setdefault(at, {})
                for x in numbers:
                    text = texts.get(x)
                    mine[x] = None if text is None else text.strip()    # (`held`'s, of a JSON string)

    def young_in(src, number):
        """The youngest word the line holds that is no row of the list, read from the token store: a word known before
        the Generate is no co-word of the table (a row's young weight is the cost's, by its place)."""
        weights = held(src)[1]
        return weights[number] if weights is not None and 0 <= number < len(weights) else 0.0

    same_line = None
    if never_rows:
        from app.connect.sentences import same_line
    try:
        if again:
            line_code, total, others, words, co_young = done[4]
        else:
            line_code = arrays["hear"].astype(np.int64)[src_a]
            said = [s for s in srcs if files[s][5].said is not None and (inside is None or files[s][1] in inside)]
            if said:
                # Kyou-PB: a lined-up book is heard line by line — its line-up's answer for each of its lines (the text
                # read as for a line returned), handed to the cost as one more array (the lead's ruling, 2026-11-23)
                line_hear = np.full(len(src_a), -1, np.int8)
                for i in np.flatnonzero(np.isin(src_a, said)).tolist():
                    src, number = int(src_a[i]), int(num_a[i])
                    seen, text = files[src][5], text_of(src, number)
                    try:
                        says = text is not None and bool(seen.said(text))
                    except Exception:
                        says = False        # a line-up it can't read says nothing: no clip promised
                    line_hear[i] = 0 if says else _HEARD_CODE.get(seen.unsaid, 2)
                arrays["line_hear"] = line_hear
                line_code = np.where(line_hear >= 0, line_hear, line_code)
            # (*Only i+1*'s rounds ask the same columns in another order: the cost's order-free parts kept for them)
            total, others, words, co_young = cost(columns, arrays, low, high,
                                                  **({"kept": shared.setdefault("cost", {})} if clean_only else {}))
            if kept is not None:
                shared["costed"] = (frozenset(want), (tuple(length), shown), inside, (columns, srcs, arrays, files, spans,
                                                                                       tie),
                                    (line_code, total, others, words, co_young))
        # (an ask inside some files — the mined episode's own — ranks only their lines: the walk skipped the rest)
        within = None if inside is None else np.array(sorted(s for s in srcs if files[s][1] in inside), np.int64)

        def walk(k, lazy):
            """Row `k`'s lines -> (the best `n`, the lines it took before their text was read: [`_Later`]). `lazy`:
            a line whose text isn't known yet is taken as one that has a text — with no line barred by its text, a
            text's only say is whether there is one — its text read once every row has walked (`resolve`); a row
            with a line taken so that has none is walked again, reading as it goes: the same answer as always."""
            a, b = spans.get(k, (0, 0))
            later = []
            if a == b:
                return [], later
            banned = never_rows.get(k)
            lazy = lazy and not banned
            # (a word with no heard line it could use is walked as without the ask: never every line of it)
            heard_ask = heard_first and bool((np.isfinite(total[a:b]) & (line_code[a:b] != 2)).any())
            taken, texts = [], set()
            heard_one = False
            # (fewer than YOUNG_LINES asked, no heard ask: a young word lowers a line's cost by YOUNG × its weight at
            # most, so once a line's cost less that floor is above the nth best read so far, neither it nor any line
            # after it can be among the n returned — its file is not read for it; the answer is the same. One tie's
            # width more: a line after it, equal to 9 decimals, may be a hair cheaper before the rounding)
            floor = r.young * max(young_of.values()) if young_of and 0 < n < YOUNG_LINES and not heard_ask else None
            enough = max(n, YOUNG_LINES if young_of else 0)
            for i in _ranked(total, num_a, tie, src_a, a, b, within):
                if len(taken) >= enough and (not heard_ask or heard_one):
                    break
                if (floor is not None and len(taken) >= n
                        and round(float(total[i]), _RANK_DIGITS) - floor - _TIE > sorted(t[0] for t in taken)[n - 1]):
                    break
                # (the same sentence twice is told first, on its one number: at a 400-file Chinese library the walk
                # passed 119,660 copies to take 1,414 lines — E-PICK)
                repeat = int(hash_a[i])
                if repeat and repeat in texts:
                    continue            # the same sentence twice: never
                src, number = int(src_a[i]), int(num_a[i])
                if inside is not None and files[src][1] not in inside:
                    continue
                if clean_only and words[i]:
                    continue
                if not as_read(src):
                    continue            # its file changed or left since the Generate: every line of it skipped
                text = peek(src, number) if lazy else text_of(src, number)
                if text is None or (banned and same_line(text, banned)):
                    if repeat and text is not None:
                        texts.add(repeat)   # (the same text in other files is refused too: those copies never read)
                    continue
                if text is _LATER:
                    text = _Later(src, number)
                    later.append(text)
                if repeat:
                    texts.add(repeat)
                line_cost = float(total[i])
                if young_of and len(taken) < YOUNG_LINES:
                    held_young = young_in(src, number)
                    old = line_cost
                    # (the co-words' youngest is in the cost already: only a younger one moves it)
                    line_cost = old - r.young * max(0.0, held_young - float(co_young[i]))
                seen, code = files[src][5], int(line_code[i])
                heard_one = heard_one or code != 2
                taken.append((round(line_cost, _RANK_DIGITS), int(tie[src]), number, len(taken),
                              Line(files[src][0], seen.item_id, text, round(line_cost, 4), int(others[i]),
                                   int(chars_a[i]), round(float(arrays["ctx"][src]) * (r.unwatched if seen.show_only
                                                                                       else 1.0), 4),
                                   _HEARD_OF[code], number)))
            lead = sorted(taken[:YOUNG_LINES]) if young_of else taken[:YOUNG_LINES]
            ordered = [t[-1] for t in lead + taken[YOUNG_LINES:]]
            if heard_ask and ordered and _HEARD_CODE.get(ordered[0].heard, 2) == 2:
                first = next((line for line in ordered if _HEARD_CODE.get(line.heard, 2) != 2), None)
                if first is not None:
                    ordered = [first] + [line for line in ordered if line is not first]
            return ordered[:n], later

        lazy = not young_of
        waiting = {}
        for key, k in asked.items():
            out[key], later = walk(k, lazy)
            if later:
                waiting[key] = (k, later)
        if waiting:
            asked_lines = {}
            for _k, later in waiting.values():
                for src, number in later:
                    asked_lines.setdefault(src, set()).add(number)
            resolve(asked_lines)
            for key, (k, later) in waiting.items():
                if any(peek(src, number) is None for src, number in later):
                    out[key] = walk(k, False)[0]        # a line it took has no text: walked again, reading as it goes
                else:
                    out[key] = [line._replace(text=peek(*line.text)) if type(line.text) is _Later else line
                                for line in out[key]]
    finally:
        if tokens[0]:
            try:
                tokens[0].close()
            except Exception:
                pass
    return out
