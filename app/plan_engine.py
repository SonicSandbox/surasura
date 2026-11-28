"""The fast re-plan's engine (E1.1 02, RP-4): the plan file + an order -> the order's columns, without the tokenizer.

A full Generate writes `results/plan.json.gz` (`analyzer.plan_lines`, 01 §7): every use of every list word per file,
as the analyzer counted it. From it this module recomputes, for any order of the same files, what the order changes —
Score and the tier counts, first places, the priority order, *N new*, `Orth` / `Forms` where spellings tie, the
progressive list — and the rows Junban's match index is built from. Everything else (sentences, the report, words
under the list's floor) stays as the last Generate left it until the next one (D1).

    plan = plan_engine.load(path)                      # PlanError: missing, corrupt, another format
    plan_engine.check(plan, language, engine, run_stamp, signature_parts, epoch)
    eng = plan_engine.Engine(plan, ids)                # ids: the store's item id of each plan file (Store.item_id)
    eng.replan(order, pins)                            # from scratch: order = [(item_id, tier)], NOW, Soon, 6+ Months
    eng.move(item_ids, tier, before_id=None, after_id=None)   # incremental, as Store.move places a block
    eng.add(item_id, record, tier, before_id=None, after_id=None, exact=True, moved=())   # an arrival (E2.2 D9)
    eng.set_pins(pins)
    result = eng.result()
    new, before = eng.words_of(item_ids)               # Hover-W: a title's words (the window's word card)
    eng.leave_out(lemmas)                              # Kotoba-K: words marked Known / Ignore since, out at once
    first_sentences(path)                              # Hover-W: each listed word's first sentence per file

**Pure** (rule 3): the standard library and `app.plan_rules` only — no Qt, Tk, pandas or tokenizer, no settings, no
store, no Anki; the only I/O is reading the plan file it is given. The caller runs it on a worker.

**Exact** (05 §1): `result()` equals a full Generate of the same order on the plan columns. The analyzer and this
module share `plan_rules` — the spelling a row shows and the progressive pass are one implementation. `move` keeps the
live numbers (Score, counts, first places, *N new*, the priority order) up to date in place and equals `replan`
(05 §2); the progressive list and spelling ties are worked out again by `result()`. `add` counts in a file the plan
doesn't hold from its arrival record (`arrivals.record`) the same way; when the gates found nothing else it moves
(`arrivals.Gates`), the result is the next Generate's.
"""
import bisect
import gzip
import io
import json
import os
import sys
import zlib
from array import array
from collections import namedtuple

from app import plan_rules

# The newest plan file this engine reads; FORMATS: every one it reads — 1 (2.x), 2 (3.0: `spell` and
# `phrase_entries`, E2.2 D8), 3 (F7: the rows' example-sentence pools, `finished`, `sentences`, `cowords`, `pools`,
# `fs`), 4 (each phrase row's dictionary spelling in `phrase_entries`: its `Kana`), 5 (the sentence choice's release 2,
# `plan_rules.SENTENCE_TABLE >= 2`: the sentences live in the sentence table beside the plan, `app/sentence_table.py`;
# the plan's own pools and first sentences are never read, and a format-4 plan reads "Generate first", SPEC § 3.6)
FORMAT = 5 if plan_rules.SENTENCE_TABLE >= 2 else 4
FORMATS = (1, 2, 3, 4, 5) if plan_rules.SENTENCE_TABLE >= 2 else (1, 2, 3, 4)    # (5 unknown below release 2)
PICKS_IN_TABLE = 5                         # from this format on a row's sentences are the table's (`Engine.contexts`)
TIERS = ("now", "soon", "goal")            # the analysed tiers, in the order a Generate reads them
_SLOT = {"now": 0, "soon": 1, "goal": 2}
# What `Engine._numbers` works out for an order: the plan's own order's, at the first ask (`Engine.__getattr__`)
_LIVE = frozenset(("_order", "_order_v", "_tier", "_pos", "_tier_count", "_raw", "_counts", "_first", "_first_idx",
                   "_n_new", "_rank_of", "_ranked"))
_GAP = 1 << 40                             # room between two items' places: a move takes a place between its
                                           # neighbours, so 40 drags into one spot before every item is numbered again
_SHORT = 256                               # a word met in at most this many files finds its first file by looking
                                           # at each; a commoner one by walking the order (`move`, `_numbers`)
ORDER_MODES = ("content", "priority")      # Junban's `junban_order_mode`: the progressive list, or the priority list


class PlanError(Exception):
    """The plan can't be used as it is: missing, damaged, another format, or the library it describes changed."""


# --------------------------------------------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------------------------------------------- #

class Plan:
    """A plan file read: `header` (dict), `files` [[rel_path, tier, digest(, kind)], …], `keys` [[Word, Reading,
    is_phrase, half, Occurrences], …], `rows` (parallel to keys: [Tier, phrase Tier, Modality, Sources, Orth, Forms,
    [Context 1, Src 1, …]] or None), `ties` [[k, {orth: n}, {surface: n}, {orth: Tier} | None], …], `per_file` (one
    dict per file, in the run's order: "main", "ph", "sp", "prog", "fs") and `spell` ({k: ({orth: n}, {surface: n})}
    for every other listed word, each in the order first met — format 2; empty for format 1). Format 3 (F7), the
    example sentences: `finished` [[rel_path, kind, finish rank], …] (sources after the files), `sentences` [[text,
    shown or None, short, long, source, [co-words], [phrase rows], sentence number], …], `cowords` [[own row or -1,
    [[rows], …]], …] and `pools` {k: (first sentence or -1, [shortlist + Finished], [audio])}; empty before."""

    __slots__ = ("header", "files", "keys", "rows", "ties", "per_file", "spell", "finished", "sentences", "cowords",
                 "pools", "picks", "firsts")

    def __init__(self, header, files, keys, rows, ties, per_file, spell=None, finished=None, sentences=None,
                 cowords=None, pools=None, picks=True, firsts=None):
        self.header, self.files, self.keys, self.rows, self.ties, self.per_file = \
            header, files, keys, rows, ties, per_file
        self.spell = {} if spell is None else spell
        self.finished = [] if finished is None else finished
        self.sentences = [] if sentences is None else sentences
        self.cowords = [] if cowords is None else cowords
        self.pools = {} if pools is None else pools
        self.picks = picks                  # the example-sentence tables were read (`load(pools=…)`)
        self.firsts = firsts                # each row's first sentence in each file, without its text (format 3)


_PICK_TABLES = tuple(b'{"' + name + b'":' for name in (b"finished", b"sentences", b"cowords", b"pools", b"firsts"))


def load(path, pools=True, trusted=False):
    """The plan file at `path`, checked whole. The file is read in one go and closed before anything is decoded, so a
    Generate replacing it never waits on this reader (Windows refuses to replace a file someone holds open). Raises
    PlanError: missing, unreadable, damaged (gzip CRC, a line that isn't JSON), another format, or tables that don't
    fit together. `pools` False (the window's readers: the numbers, Anki's order, Connect): format 3's example-sentence
    tables are left undecoded (F7; most of a large plan) — its engine re-picks nothing (`Engine.contexts` None).
    `trusted` (the analyzer's redraw, of the plan its own Generate wrote: F7): the gzip and JSON checks, the header and
    every table's size against it, but not each value's type and range — a damaged value there is an error the
    redraw catches, and it Generates instead; a plan of another library or run is `check`'s to refuse, as ever."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        raise PlanError(f"no plan file ({e.__class__.__name__})") from None
    try:
        lines = gzip.decompress(data).split(b"\n")
    except (OSError, EOFError, zlib.error) as e:
        raise PlanError(f"the plan file is damaged ({e.__class__.__name__})") from None
    if lines and lines[-1] == b"":
        lines.pop()
    if not pools or _in_table(lines):
        lines = [line for line in lines if not line.startswith(_PICK_TABLES)]
        pools = False
    try:
        decoded = [json.loads(line) for line in lines]
    except ValueError:
        raise PlanError("the plan file is damaged (a line isn't JSON)") from None
    if not decoded or not isinstance(decoded[0], dict):
        raise PlanError("the plan file has no header")
    header = decoded[0]
    if header.get("format") not in FORMATS:
        raise PlanError(f"the plan file's format is {header.get('format')!r}, not one of {FORMATS}")
    tables = {"files": [], "keys": [], "rows": [], "ties": []}
    if header["format"] >= 2:
        tables["spell"] = []
    if header["format"] >= 3:
        tables.update(finished=[], sentences=[], cowords=[], pools=[], firsts=[])
    per_file = []
    for line in decoded[1:]:
        if not isinstance(line, dict):
            raise PlanError("the plan file is damaged (a line isn't a table)")
        if "f" in line:
            if line["f"] != len(per_file):
                raise PlanError("the plan file's files are out of order")
            per_file.append(line)
            continue
        if len(line) != 1:
            raise PlanError("the plan file is damaged (a table line holds two tables)")
        (name, chunk), = line.items()
        if name not in tables or not isinstance(chunk, list):
            raise PlanError(f"the plan file holds an unknown table {name!r}")
        if per_file:
            raise PlanError("the plan file's tables come after its files")
        tables[name].extend(chunk)
    plan = Plan(header, tables["files"], tables["keys"], tables["rows"], tables["ties"], per_file,
                _spell_table(tables.get("spell", ())), tables.get("finished"), tables.get("sentences"),
                tables.get("cowords"), _pools_table(tables.get("pools", ())), picks=pools,
                firsts=_firsts_table(tables.get("firsts"), deep=not trusted))
    _validate(plan, deep=not trusted)
    return plan


def _in_table(lines):
    """Whether the plan's header says format 5 or later: its rows' sentences are the sentence table's, so its own
    example-sentence tables (if a Generate still wrote them) are left undecoded, as in a lean load."""
    try:
        return json.loads(lines[0]).get("format", 0) >= PICKS_IN_TABLE if lines else False
    except (ValueError, AttributeError, TypeError):
        return False


def _firsts_table(chunks, deep=True):
    """The packed per-file first sentences (`plan_rules.Firsts`), or None (an older plan, a lean load)."""
    if not chunks:
        return None
    if len(chunks) != 1:
        raise PlanError("the plan file's first sentences are damaged")
    try:
        return plan_rules.Firsts(chunks[0], deep)
    except ValueError as e:
        raise PlanError(f"the plan file's {e}") from None


def _pools_table(rows):
    """{k: (first, pool, audio)} from the `pools` table's rows; a row that isn't [k, first, […], […]] or lists a row
    twice is a PlanError (`_validate` checks the rest)."""
    pools = {}
    for row in rows:
        if not (isinstance(row, list) and len(row) == 4 and type(row[0]) is int and type(row[1]) is int
                and isinstance(row[2], list) and isinstance(row[3], list)):
            raise PlanError("the plan file's pools are damaged")
        if row[0] in pools:
            raise PlanError("the plan file's pools list a row twice")
        pools[row[0]] = (row[1], row[2], row[3])
    return pools


def _spell_table(rows):
    """{k: (orths, surfaces)} from the `spell` table's rows; a row that isn't [k, …, …] is a PlanError (`_validate`
    checks the rest)."""
    spell = {}
    for row in rows:
        if not (isinstance(row, list) and len(row) == 3 and type(row[0]) is int):
            raise PlanError("the plan file's spell table is damaged")
        if row[0] in spell:
            raise PlanError("the plan file's spell table lists a word twice")
        spell[row[0]] = (row[1], row[2])
    return spell


def read_header(path, formats=None):
    """The plan file's header (its first line), or None when there is no readable plan of this format (`formats`: of
    one of these — the window's numbers ask `FORMATS`, a plan an older format wrote too: UPDATE-START). The whole
    stream is read through, so a damaged file (the gzip CRC, a cut-off end) is None too: what the analyzer asks
    before it reuses a run (E1.1 01 §7, E1.2-1; 2.x only with the preview on), cheaper than `load` (nothing past the
    first line is decoded)."""
    try:
        with open(path, "rb") as f:
            data = f.read()
        stream = gzip.GzipFile(fileobj=io.BytesIO(data))
        first = stream.readline()
        while stream.read(1 << 20):
            pass
        header = json.loads(first)
    except (OSError, EOFError, zlib.error, ValueError):
        return None
    if not isinstance(header, dict) or header.get("format") not in (formats or (FORMAT,)):
        return None
    return header


def _validate(plan, deep=True):
    """Every value the engine reads, checked by type and range, every table against the header: a damaged or
    hand-edited plan is refused whole with a PlanError, never half-used and never a crash later (a TypeError in
    `result()` on a worker). `format` 1 to 4 as `analyzer.plan_lines` writes it (01 §7; 2 adds `spell` and the
    header's `phrase_entries`, E2.2 D8; 3 the example-sentence pools; 4 each phrase entry's dictionary spelling)."""
    h = plan.header
    for name, kinds in (("language", str), ("engine", str), ("run_signature", str), ("order_free_signature", str),
                        ("weights", dict), ("files", int), ("keys", int), ("shared_phrases", list)):
        if not isinstance(h.get(name), kinds):
            raise PlanError(f"the plan file's header has no {name!r}")
    if "max_contexts" in h and not (type(h["max_contexts"]) is int and 0 <= h["max_contexts"] <= 50):
        raise PlanError("the plan file's header 'max_contexts' is damaged")
    for name, kinds in (("store", (dict, type(None))), ("order_free_parts", dict),
                        ("target_coverage", (int, float)), ("only_i_plus_one", (bool, int))):
        if name in h and not isinstance(h[name], kinds):
            raise PlanError(f"the plan file's header {name!r} is damaged")
    n_files, n_keys = len(plan.files), len(plan.keys)
    if h["files"] != n_files or len(plan.per_file) != n_files:
        raise PlanError("the plan file's files don't match its header")
    if h["keys"] != n_keys or len(plan.rows) != n_keys:
        raise PlanError("the plan file's keys don't match its header")
    weights = h["weights"]
    if set(weights) != set(TIERS) or not all(_number(w) for w in weights.values()):
        raise PlanError("the plan file's weights are damaged")
    for entry in plan.files:
        if not (isinstance(entry, list) and len(entry) in (2, 3, 4) and isinstance(entry[0], str)
                and isinstance(entry[1], str) and entry[1] in _SLOT and all(isinstance(x, str) for x in entry[2:])):
            raise PlanError("the plan file's files table is damaged")
    seen = set()
    for key in plan.keys:
        if not (isinstance(key, list) and len(key) == 5 and isinstance(key[0], str) and isinstance(key[1], str)
                and type(key[2]) is bool and type(key[3]) is bool and type(key[4]) is int and key[4] > 0):
            raise PlanError("the plan file's keys table is damaged")
        if (key[0], key[1]) in seen:
            raise PlanError("the plan file lists a word twice")          # every result is keyed by (Word, Reading)
        seen.add((key[0], key[1]))
    for row in plan.rows:
        if row is not None and not (
                isinstance(row, list) and len(row) == 7 and all(isinstance(x, str) for x in row[:6] if x is not None)
                and isinstance(row[0], str) and isinstance(row[6], list) and all(isinstance(x, str) for x in row[6])):
            raise PlanError("the plan file's rows table is damaged")
    for tie in plan.ties:
        if not (isinstance(tie, list) and len(tie) == 4 and _index(tie[0], n_keys)
                and _counts(tie[1]) and _counts(tie[2])
                and (tie[3] is None or (isinstance(tie[3], dict) and all(isinstance(v, str) for v in tie[3].values())
                                        and set(tie[3]) <= set(tie[1])))):
            raise PlanError("the plan file's ties table is damaged")
    ties = {tie[0]: tie for tie in plan.ties}
    # Format 2 and on: every listed word not in `ties` has its spelling counts (`spell`), and each phrase row names the phrase
    # whose entry holds it. A format-1 plan holds neither.
    if h.get("format") in (2, 3, 4, 5):
        listed_untied = {k for k, row in enumerate(plan.rows) if row is not None and k not in ties}
        if set(plan.spell) != listed_untied or not all(_counts(o) and _counts(s) for o, s in plan.spell.values()):
            raise PlanError("the plan file's spell table is damaged")
        entries = h.get("phrase_entries")
        size = 3 if h["format"] >= 4 else 2         # format 4: and the phrase's dictionary spelling
        if not (isinstance(entries, list) and all(
                isinstance(e, list) and len(e) == size and _index(e[0], n_keys) and type(e[1]) is int and e[1] >= 0
                and (size == 2 or isinstance(e[2], str)) for e in entries)
                and [e[0] for e in entries] == [k for k, key in enumerate(plan.keys) if key[2]]):
            raise PlanError("the plan file's header 'phrase_entries' is damaged")
    elif plan.spell:
        raise PlanError("a format-1 plan file holds a spell table")
    if h.get("format") in (3, 4):
        if plan.picks and deep:
            _validate_pools(plan)
    elif h.get("format", 0) >= PICKS_IN_TABLE:
        pass                                # (its sentences are the table's: a file's `fs`, if written, is never read)
    elif plan.sentences or plan.pools or plan.cowords or plan.finished or any("fs" in line for line in plan.per_file):
        raise PlanError("an older plan file holds example-sentence pools")
    if not deep:
        return                              # (`load(trusted=True)`: the sizes above are the plan's own)
    uses = [0] * n_keys
    phrases = {k for k, key in enumerate(plan.keys) if key[2]}
    for line in plan.per_file:
        for table, is_phrase in (("main", False), ("ph", True)):
            ks, us = _pairs(line.get(table), n_keys, "a file's uses are damaged")
            # A use is counted (the writer's records start at 1): a 0 would give a file where nothing counted a
            # word's first place (02 §2.3). A word listed once per table.
            if (us and min(us) < 1) or len(set(ks)) != len(ks):
                raise PlanError("a file's uses are damaged")
            if (set(ks) <= phrases) if is_phrase else phrases.isdisjoint(ks):
                for k, u in zip(ks, us):
                    uses[k] += u
            else:
                # A word counted as a phrase's own uses, or the reverse: the insertion order a Generate keeps
                # (words first, then phrases) couldn't be told from the plan.
                raise PlanError("a file's uses mix a word and a phrase row")
        sps = line.get("sp", [])
        if not isinstance(sps, list) or not all(
                isinstance(sp, list) and len(sp) == 3 and sp[0] in ties and _strings(sp[1]) and _strings(sp[2])
                and set(sp[1]) <= set(ties[sp[0]][1]) and set(sp[2]) <= set(ties[sp[0]][2]) for sp in sps):
            raise PlanError("a file's spellings are damaged")
        prog = line.get("prog")
        if not (isinstance(prog, list) and len(prog) == 7 and type(prog[0]) is int and type(prog[1]) is int
                and 0 <= prog[1] <= prog[0] < _LIMIT):
            raise PlanError("a file's progressive record is damaged")
        for table in (prog[2], prog[3], prog[4], prog[5]):
            _pairs(table, n_keys, "a file's progressive record is damaged")
        if not isinstance(prog[6], list) or not all(
                isinstance(sib, list) and len(sib) == 2 and isinstance(sib[0], str) and _count(sib[1])
                for sib in prog[6]):
            raise PlanError("a file's progressive record is damaged")
    if uses != [key[4] for key in plan.keys]:
        raise PlanError("the plan file's uses don't add up to its words' Occurrences")


Candidates = namedtuple("Candidates", "header files finished keys sentences cowords pools")
_CANDIDATE_TABLES = tuple(b'{"' + name + b'":' for name in (b"files", b"keys", b"finished", b"sentences", b"cowords",
                                                              b"pools"))
_PER_FILE_TABLES = (b'\n{"firsts":', b'\n{"f":')      # what follows the tables `candidates` reads (`plan_lines`' order)


def candidates(path, language=None):
    """Each listed row's example-sentence candidates as the last Generate kept them (F7: `pools`, `sentences`,
    `cowords`, with `files`, `finished` and `keys` to read them by) — for a reader that orders a word's candidates
    itself (the sentence dial, `app/connect/sentences.py`) -> `Candidates`, `pools` as `Plan.pools` ({k: (first
    sentence or -1, [shortlist + Finished], [audio])}); None when there is no readable plan of a format that holds
    them (3 on), it is `language`'s no longer, or a table is damaged. Light: the stream is read only as far as those
    tables go — they stand before the per-file tables (`firsts` and the files' lines: most of a large library's
    plan), which are never unzipped, so the read follows the list's rows, not the library — and nothing else is
    decoded. No check that the plan is still the library's (`check`): the reader checks each file it takes a
    sentence from (`files`' digests)."""
    try:
        with open(path, "rb") as f:
            data = f.read()
        unzip, parts, cut, at = zlib.decompressobj(31), [], -1, 0
        while data and cut < 0:
            parts.append(unzip.decompress(data, 1 << 20))
            data = unzip.unconsumed_tail
            if not parts[-1]:
                break
            text = b"".join(parts[-2:])             # (a mark may stand across two pieces)
            for mark in _PER_FILE_TABLES:
                found = text.find(mark)
                if found >= 0 and (cut < 0 or found < cut):
                    cut = found
            if cut >= 0:
                parts[-2:] = [text[:cut]]
        lines = b"".join(parts).split(b"\n")
        header = json.loads(lines[0])
        if not isinstance(header, dict) or header.get("format") not in (3, 4) or (
                language is not None and header.get("language") != language):
            return None
        tables = {name: [] for name in ("files", "keys", "finished", "sentences", "cowords", "pools")}
        for line in lines[1:]:
            if line.startswith(_CANDIDATE_TABLES):
                (name, chunk), = json.loads(line).items()
                tables[name].extend(chunk)
        pools = _pools_table(tables["pools"])
    except (OSError, EOFError, zlib.error, ValueError, TypeError, AttributeError, PlanError):
        return None
    return Candidates(header, tables["files"], tables["finished"], tables["keys"], tables["sentences"],
                      tables["cowords"], pools)


Counts = namedtuple("Counts", "header files keys per_file")
_COUNT_TABLES = (b'{"files":', b'{"keys":')
_COUNT_LINES = _COUNT_TABLES + (b'{"f":',)
_COUNT_MARK = max(len(mark) for mark in _COUNT_LINES)     # a line's first bytes that tell whether `counts` reads it
_PIECE = 1 << 20                                          # the zipped bytes `counts` unzips at a time


def counts(path):
    """The plan file's per-file counts only, for the journey (J-CUT: each word's count ahead and each episode's *%
    known*, `journey_render._ahead` / `_plan_pcts`) -> `Counts`: the header, `files` (each one's [path]), `keys`, and
    `per_file` (each file's {"main", "ph", "prog"}); None when there is no readable plan of a format this engine reads.
    Light where `load` is whole: the stream is unzipped a piece at a time and only these tables are kept — the rows,
    the ties, the spellings, the example sentences and each file's `fs` are never held (at 20,000 files `load(pools=
    False)` held ~130 MB more at the render's peak). No check that the plan is this run's or this library's: the caller
    compares its header's `run_signature` (`analyzer._journey_plan`)."""
    try:
        with open(path, "rb") as f:
            data = f.read()
        unzip, rest, header, files, keys, per_file = zlib.decompressobj(31), b"", None, [], [], []

        def take(line):
            nonlocal header
            if header is None:
                header = json.loads(line)
                if not isinstance(header, dict) or header.get("format") not in FORMATS:
                    raise PlanError("not a plan file this engine reads")
            elif line.startswith(b'{"f":'):
                found = json.loads(line)
                if found["f"] != len(per_file):
                    raise PlanError("the plan file's files are out of order")
                per_file.append({"main": found["main"], "ph": found["ph"], "prog": found["prog"]})
            elif line.startswith(_COUNT_TABLES):
                (name, chunk), = json.loads(line).items()
                if name == "files":
                    files.extend([entry[0]] for entry in chunk)
                else:
                    keys.extend(chunk)

        skip = False                                # inside a line the count never reads: dropped as it streams

        def ended(piece):
            nonlocal skip
            if skip:
                cut = piece.find(b"\n")
                if cut < 0:
                    return b""
                piece, skip = piece[cut + 1:], False
            return piece

        for at in range(0, len(data), _PIECE):
            lines = (rest + ended(unzip.decompress(data[at:at + _PIECE]))).split(b"\n")
            rest = lines.pop()
            for line in lines:
                take(line)
            if header is not None and len(rest) >= _COUNT_MARK and not rest.startswith(_COUNT_LINES):
                rest, skip = b"", True
        rest += ended(unzip.flush())
        for line in rest.split(b"\n"):
            if line:
                take(line)
        if header is None or len(per_file) != len(files):
            raise PlanError("the plan file's files don't match its tables")
    except (OSError, EOFError, zlib.error, ValueError, TypeError, KeyError, IndexError, AttributeError, PlanError):
        return None
    return Counts(header, files, keys, per_file)


COUNTS_FILE = "plan_counts.bin"         # results/: the journey's counts, beside the plan (`CountsTable`)
COUNTS_FORMAT = 2                       # its head's "counts" (2, E-NAMES: its files are paths; 1 held report names)
_NO_PHRASES = ()


class CountsTable:
    """The journey's counts, written once beside the plan by the pass that writes it (J-CUT, the lead's ruling): the
    plan's own numbers, cut to what a page draws — each file's uses of the *listed* rows (main and phrases summed: the
    only words a Generate's page or the redraw's can show; `journey_render._ahead` sums them so) and its `prog`'s first
    two numbers, the tokens counted and those known before any file (*% known*, `_plan_pcts`). `analyzer.plan_lines`
    hands each file's line here as it makes it; `write` puts the table beside the plan once that is written;
    `read_counts` reads it as `counts` reads the plan. Format 2 (E-NAMES): its files are the plan's paths (1: their
    report names, two shows' 第01集 one file). The file: one JSON line (the run, the keys, the files, the
    arrays' lengths and CRC), then the arrays as 32-bit ints — at 20,000 files the render held 44 MB of the plan's
    tables, and reading the table's 578,317 uses as JSON took 0.26 s."""

    def __init__(self):
        self._renumber, self.keys, self.files = {}, [], []
        self.uses, self.at, self.total, self.baseline = array("i"), array("i", [0]), array("i"), array("i")

    def start(self, keys, rows, names):
        """The plan's keys, its rows (None: not listed) and its files' paths (the plan's `files`: what tells two files
        of one name apart, E-NAMES), before its first file's line."""
        self.__init__()
        for k, row in enumerate(rows):
            if row is not None:
                self._renumber[k] = len(self.keys)
                self.keys.append([keys[k][0], keys[k][1]])
        self.files = list(names)

    def add(self, main, phrases, prog):
        """One file's line as the plan has it ([k, uses, …] twice, its `prog`), in the plan's order."""
        renumber, counts = self._renumber, {}
        for table in (main, phrases):
            for k, n in zip(table[0::2], table[1::2]):
                j = renumber.get(k)
                if j is not None:
                    counts[j] = counts.get(j, 0) + n
        for j, n in counts.items():
            self.uses.extend((j, n))
        self.at.append(len(self.uses))
        self.total.append(prog[0])
        self.baseline.append(prog[1])

    def write(self, results_dir, run_signature):
        """Write the table (atomically: a temp file, then `os.replace`) for the plan `run_signature` wrote. -> True,
        or False (an old table stays, for its own run: never read for this one). Never raises."""
        if len(self.total) != len(self.files):
            return False
        path = os.path.join(results_dir, COUNTS_FILE)
        tmp = f"{path}.{os.getpid()}.tmp"
        try:
            body = b"".join(a.tobytes() for a in _little(self.at, self.total, self.baseline, self.uses))
            head = {"counts": COUNTS_FORMAT, "run_signature": run_signature, "keys": self.keys, "files": self.files,
                    "uses": len(self.uses), "crc": zlib.crc32(body)}
            with open(tmp, "wb") as f:
                f.write(json.dumps(head, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
                f.write(body)
            os.replace(tmp, path)
            return True
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False


def _little(*arrays):
    """The arrays as the table keeps them, little-endian (copies on a big-endian machine)."""
    if sys.byteorder == "little":
        return arrays
    out = []
    for a in arrays:
        a = array(a.typecode, a)
        a.byteswap()
        out.append(a)
    return out


class _Strings:
    """Strings kept as one string and its offsets (`read_counts`: at 20,000 files the table's 30,399 keys as lists of
    two strings were 7.3 MB of the render's peak, this ~1 MB) -> each one, made when asked."""
    __slots__ = ("_text", "_at")

    def __init__(self, strings):
        self._text = "".join(strings)
        self._at = array("i", [0])
        n = 0
        for one in strings:
            n += len(one)
            self._at.append(n)

    def __len__(self):
        return len(self._at) - 1

    def __getitem__(self, i):
        if not -len(self) <= i < len(self):
            raise IndexError(i)
        i %= len(self)
        return self._text[self._at[i]:self._at[i + 1]]


class _Names:
    """`read_counts`' files, each read as `counts` gives one ([its path]), kept packed (`_Strings`) rather than a list
    a file."""
    __slots__ = ("_names",)

    def __init__(self, names):
        self._names = _Strings(names)

    def __len__(self):
        return len(self._names)

    def __getitem__(self, f):
        return [self._names[f]]


class _Keys:
    """`read_counts`' keys, each read as `counts` gives one ([Word, Reading]), kept packed (`_Strings`)."""
    __slots__ = ("_parts",)

    def __init__(self, keys):
        self._parts = _Strings([part for key in keys for part in key])

    def __len__(self):
        return len(self._parts) // 2

    def __getitem__(self, k):
        if not -len(self) <= k < len(self):
            raise IndexError(k)
        k %= len(self)
        return [self._parts[2 * k], self._parts[2 * k + 1]]

    def __iter__(self):
        parts = self._parts
        return ([parts[i], parts[i + 1]] for i in range(0, len(parts), 2))


class _CountLines:
    """`read_counts`' per-file lines, kept as the table's arrays and each read as `counts` gives a line: {"main": [k,
    uses, …], "ph": (), "prog": (total, baseline)}."""
    __slots__ = ("_uses", "_at", "_total", "_baseline")

    def __init__(self, uses, at, total, baseline):
        self._uses, self._at, self._total, self._baseline = uses, at, total, baseline

    def __len__(self):
        return len(self._total)

    def __getitem__(self, f):
        if f < 0:
            f += len(self._total)
        return {"main": self._uses[self._at[f]:self._at[f + 1]], "ph": _NO_PHRASES,
                "prog": (self._total[f], self._baseline[f])}

    def prog(self, f):
        """A file's `prog` alone (`journey_render._plan_pcts` reads every file's: no line made for it)."""
        return self._total[f], self._baseline[f]


def read_counts(path, run_signature):
    """The counts table `CountsTable.write` put beside the plan -> `Counts`, shaped as `counts` reads the plan (`files`
    [[its path]], `keys` [[Word, Reading]], `per_file`: each file's
    {"main", "ph", "prog"}, the listed rows' uses under "main", `prog`'s first two numbers), so the journey reads
    either alike; None when absent, damaged (its CRC, its
    lengths, a key out of range), or another run's. Held lean for the render's peak (the lead's ruling: no cost bought
    back elsewhere): the keys and names packed (`_Keys`, `_Names`), the uses 16-bit when every one fits."""
    try:
        with open(path, "rb") as f:
            head = json.loads(f.readline())
            body = f.read()
        if not isinstance(head, dict) or head.get("counts") != COUNTS_FORMAT or not run_signature or \
                head.get("run_signature") != run_signature or zlib.crc32(body) != head["crc"]:
            return None
        keys, files, n = head["keys"], head["files"], head["uses"]
        if not all(isinstance(k, list) and len(k) == 2 for k in keys) or \
                not all(isinstance(rel, str) for rel in files) or len(body) != 4 * (3 * len(files) + 1 + n):
            return None
        arrays, view, at = [], memoryview(body), 0
        for size in (len(files) + 1, len(files), len(files), n):
            a = array("i")
            a.frombytes(view[at:at + 4 * size])
            at += 4 * size
            arrays.append(a)
        view.release()
        at, total, baseline, uses = _little(*arrays)
        if at[0] != 0 or at[-1] != n or any(at[f] > at[f + 1] for f in range(len(files))) or \
                any(d % 2 for d in (at[f + 1] - at[f] for f in range(len(files)))) or \
                (n and not 0 <= min(uses[0::2]) <= max(uses[0::2]) < len(keys)):
            return None
        if n and max(uses) < 1 << 16 and min(uses) >= 0:
            uses = array("H", uses)         # the narrower type when every key and count fits (2 bytes a number, not 4)
        return Counts({"run_signature": run_signature, "counts": COUNTS_FORMAT}, _Names(files), _Keys(keys),
                      _CountLines(uses, at, total, baseline))
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return None


def _validate_pools(plan):
    """Format 3's example-sentence tables (F7), checked as the rest: every source, co-word, row and sentence an index
    that exists, the lengths 0 or 1, every listed row's pools there once and no other row's."""
    h = plan.header
    n_files, n_keys = len(plan.files), len(plan.keys)
    if not (type(h.get("recency_files")) is int and isinstance(h.get("ensure_audio"), bool)
            and type(h.get("max_chars")) is int and type(h.get("near_files")) is int and h["near_files"] >= 0):
        raise PlanError("the plan file's header has no pick settings")
    if any(len(entry) != 4 for entry in plan.files):
        raise PlanError("the plan file's files table is damaged")
    for entry in plan.finished:
        if not (isinstance(entry, list) and len(entry) == 3 and isinstance(entry[0], str) and isinstance(entry[1], str)
                and _count(entry[2])):
            raise PlanError("the plan file's finished table is damaged")
    n_sources, n_cowords, n_sentences = n_files + len(plan.finished), len(plan.cowords), len(plan.sentences)
    for c in plan.cowords:
        if not (isinstance(c, list) and len(c) == 2 and type(c[0]) is int and -1 <= c[0] < n_keys
                and isinstance(c[1], list) and all(isinstance(clause, list) and clause for clause in c[1])):
            raise PlanError("the plan file's co-words are damaged")
        for clause in c[1]:
            if not set(map(type, clause)) <= {int} or min(clause) < 0 or max(clause) >= n_keys:
                raise PlanError("the plan file's co-words are damaged")
    for st in plan.sentences:
        if not (isinstance(st, list) and len(st) == 10 and isinstance(st[0], str)
                and (st[1] is None or isinstance(st[1], str)) and type(st[2]) is int and type(st[3]) is int
                and st[2] in (0, 1) and st[3] in (0, 1) and _index(st[4], n_sources) and _count(st[7])
                and type(st[8]) is int and 0 <= st[8] < 1 << 32 and _count(st[9]) and isinstance(st[5], list)
                and isinstance(st[6], list)):
            raise PlanError("the plan file's sentences are damaged")
        for ids, n in ((st[5], n_cowords), (st[6], n_keys)):
            if ids and (not set(map(type, ids)) <= {int} or min(ids) < 0 or max(ids) >= n):
                raise PlanError("the plan file's sentences are damaged")
    firsts = plan.firsts
    if firsts is None:
        raise PlanError("the plan file has no first sentences")
    cols = firsts.cols
    if firsts.n and (min(cols["src"]) < 0 or max(cols["src"]) >= n_files or min(cols["number"]) < 0
                     or min(cols["chars"]) < 0 or any(f not in (0, 1, 2, 3) for f in set(cols["flags"]))):
        raise PlanError("the plan file's first sentences are damaged")
    for flat, n in (("cow", n_cowords), ("crowd", n_keys)):
        if cols[flat] and (min(cols[flat]) < 0 or max(cols[flat]) >= n):
            raise PlanError("the plan file's first sentences are damaged")
    listed = {k for k, row in enumerate(plan.rows) if row is not None}
    if set(plan.pools) != listed:
        raise PlanError("the plan file's pools don't match its rows")
    for first, pool, audio in plan.pools.values():
        if not (first == -1 or _index(first, n_sentences)):
            raise PlanError("the plan file's pools are damaged")
        for ids in (pool, audio):
            if ids and (not set(map(type, ids)) <= {int} or min(ids) < 0 or max(ids) >= n_sentences):
                raise PlanError("the plan file's pools are damaged")
    src = cols["src"]
    for f, line in enumerate(plan.per_file):
        ks, ids = _pairs(line.get("fs", []), n_keys, "a file's first sentences are damaged")
        if not set(ks) <= listed or len(set(ks)) != len(ks) or any(
                not 0 <= s - n_sentences < firsts.n or src[s - n_sentences] != f for s in ids):
            raise PlanError("a file's first sentences are damaged")


def _pairs(table, n, damaged):
    """A flat `[k, n, k, n, …]` table checked in bulk — every value an int, each k an index into the keys, each count
    within `_count` — and returned as (keys, counts)."""
    if not isinstance(table, list) or len(table) % 2 or not set(map(type, table)) <= {int}:
        raise PlanError(damaged)
    ks, us = table[0::2], table[1::2]
    if ks and (min(ks) < 0 or max(ks) >= n or min(us) < 0 or max(us) >= _LIMIT):
        raise PlanError(damaged)
    return ks, us


def _index(value, n):
    return type(value) is int and 0 <= value < n


_LIMIT = 1 << 31                    # counts are kept in compact arrays of 32-bit ints


def _count(value):
    return type(value) is int and 0 <= value < _LIMIT


def _number(value):
    return type(value) in (int, float)


def _strings(value):
    return isinstance(value, list) and all(isinstance(x, str) for x in value)


def _counts(value):
    return isinstance(value, dict) and all(type(n) is int for n in value.values())


# --------------------------------------------------------------------------------------------------------------- #
# Is the plan still the library's?
# --------------------------------------------------------------------------------------------------------------- #

def check(plan, language, engine, run_stamp, signature_parts, epoch=None, added=(), chunked=True):
    """Whether `plan` describes the library as it stands (01 §1, 04 §4). `engine`: the running app's
    `"<version>|schema<SCHEMA_VERSION>|rev<ENGINE_REVISION>"`; `run_stamp`: `analyzer.read_run_stamp(results)`;
    `signature_parts`: `analyzer.run_signature_parts(...)` for the library now (the caller computes it on its worker);
    `epoch`: the store's (None: not checked); `added`: the digests (`plan_rules.file_digest`) of the files the engine
    added since the plan (`Engine.add`, E2.2 D9); `chunked`: `plan_rules.signature_digest`'s (False: one call of the C
    encoder, for a caller no thread waits beside — the redraw's own process, G3). Returns

      None                        the plan is the library's: re-plan any order of it;
      ("replan-now", parts)       only the known words ("known"), the word lists ("lists"), files that left the
                                  counted tiers ("files-removed") or files the engine added, none changed or removed
                                  ("files-added"), set-aside files that only left ("reference-removed"), counted
                                  files set aside — a watched mark, a finish ("reference-joined", Haya-W, Haya-FN) —
                                  or only the set-aside files' ranks as sentence sources ("finished", F7) moved:
                                  re-plan now from the plan, then Generate;
      ("generate-first", reason)  anything else — another language, another app version, a run that didn't finish,
                                  files added or changed, a setting, the set-aside files otherwise ("reference": a
                                  file the plan never counted set aside, an un-marking or a Put back the plan has no
                                  line for): a Generate first;
      ("stand-aside", reason)     the plan is current but the engine can't replay it exactly: coverage mode
                                  ("coverage"), i+1 mode ("i+1"), a row two set phrases share ("shared-phrase") or a
                                  weight that isn't a whole number ("weights") — the preview stands aside (D7)."""
    h = plan.header
    if h.get("language") != language:
        return ("generate-first", "language")
    if plan_rules.SENTENCE_TABLE >= 2 and h.get("format") != FORMAT:
        return ("generate-first", "format")             # (release 2: an older plan's sentences aren't the table's)
    if h.get("engine") != engine:
        return ("generate-first", "engine")
    if not h.get("run_signature") or h["run_signature"] != run_stamp:
        return ("generate-first", "unstamped")          # the run that wrote it never finished, or another run since
    store = h.get("store") or {}
    if epoch is not None and store.get("epoch") != epoch:
        return ("generate-first", "epoch")
    if signature_parts is None:
        return ("generate-first", "signature")
    verdict = None
    now = plan_rules.signature_digest(signature_parts, order_free=True, chunked=chunked)
    if now is None:
        return ("generate-first", "signature")                    # the parts can't be read: never "current"
    if now != h["order_free_signature"]:
        verdict = _what_moved(plan, signature_parts, added)
        if verdict[0] == "generate-first":
            return verdict
    aside = stands_aside(plan)
    return ("stand-aside", aside) if aside else verdict


def only_order(header, language, engine, run_stamp, signature_parts, epoch=None):
    """Whether `check` answers None — the plan is the library's in all but its order and its pins — for the plan whose
    header (`read_header`) this is. `check` reads nothing but the header on its way to None (a signature that moved,
    the one road to the plan's files, never ends in None), so the header alone answers it exactly (Sonic 2026-11-06,
    A: the one question behind *no Generate after a plain move*). None (no readable header) is False."""
    if not isinstance(header, dict):
        return False
    return check(Plan(header, [], [], [], [], None), language, engine, run_stamp, signature_parts, epoch) is None


NUMBERS_EXACT = ("i+1",)          # stand-aside reasons whose *N new* the engine still follows exactly (`Engine`)


def stands_aside(plan):
    """Why the engine can't replay `plan` exactly, or None (check's "stand-aside" reasons)."""
    reasons = aside_reasons(plan)
    return reasons[0] if reasons else None


def aside_reasons(plan):
    """Every reason the engine can't replay `plan` exactly, in `stands_aside`'s order -> a list."""
    h = plan.header
    out = []
    if h.get("target_coverage"):
        out.append("coverage")
    if h.get("only_i_plus_one"):
        out.append("i+1")
    if h.get("shared_phrases"):
        out.append("shared-phrase")
    if not all(type(w) is int for w in h["weights"].values()):
        out.append("weights")
    return out


def _what_moved(plan, parts, added=()):
    kept = plan.header.get("order_free_parts")
    if not isinstance(kept, dict):
        return ("generate-first", "signature")
    try:
        now = plan_rules.part_digests(parts)
    except Exception:
        return ("generate-first", "signature")
    moved = sorted(name for name in set(kept) | set(now) if kept.get(name) != now.get(name))
    replan = []
    memo = {}                                       # the counted files' digests, worked out once (20k files: ~80 ms)
    for name in moved:
        if name in ("known", "lists"):
            replan.append(name)
        elif name == "files" and _only_removed(plan, parts, memo):
            replan.append("files-removed")
        elif name == "files" and _only_added(plan, parts, added, memo):
            replan.append("files-added")
        elif name == "reference" and _only_left(plan, parts):
            replan.append("reference-removed")
        elif name == "reference" and _only_joined(plan, parts, memo):
            replan.append("reference-joined")
        elif name == "finished":
            if "reference" not in moved:    # (F7) only their ranks — a title of watched episodes finished: no file
                replan.append("finished")   # the order reads moved (Haya-FN); with "reference", it says which
        else:
            return ("generate-first", name)
    if not replan:
        return ("generate-first", "signature")                     # the whole moved but no part: not ours to guess
    if ("reference-removed" in replan or "reference-joined" in replan) and "files-added" in replan:
        return ("generate-first", "reference")                     # a set-aside file may be back among the counted
    return ("replan-now", tuple(replan))


def _counted(parts, memo):
    """The digests (`plan_rules.file_digest`) of the files the library counts now, once per check (`memo`)."""
    if "counted" not in memo:
        memo["counted"] = {plan_rules.file_digest(entry) for entry in parts["files"]}
    return memo["counted"]


def _only_removed(plan, parts, memo=None):
    """True when every file the library counts now is one the plan holds, unchanged, and some plan file is gone."""
    held = {entry[2] for entry in plan.files if len(entry) > 2}
    if len(held) != len(plan.files):
        return False                                              # a plan from before the per-file digests
    try:
        now = _counted(parts, {} if memo is None else memo)
    except Exception:
        return False
    return now < held


def _only_left(plan, parts):
    """True when the set-aside files now are some of the plan's, unchanged (W-1): one only left them — removed, or a
    watched episode moved to Finished — so nothing ahead of the learner moved; one brought back or edited is a Generate
    first (one set aside: `_only_joined`)."""
    held = plan.header.get("reference")
    if not isinstance(held, list):
        return False                                              # a plan from before the set-aside digests
    try:
        return set(parts.get("reference") or ()) < set(held)      # none left: the part is gone
    except Exception:
        return False


def _only_joined(plan, parts, memo=None):
    """True when every file new among the set-aside files is a file of the plan's that left the counted files,
    unchanged — a watched mark (Haya-W, Sonic 2026-11-06: "Responsiveness is key") or a finish, a drag to Finished or a
    title finishing by itself (Haya-FN, 2026-11-09: the watched mark's rule, never a second one): its digest is the one
    its plan line holds (`analyzer.aside_files` signs a set-aside file as the counted files are signed), so the engine
    drops its uses as for a file removed ("files" is then "files-removed") and nothing new joins the name tables'
    evidence (counted and set-aside files are both its evidence). The list's edge — a word crossing the cut-off, a
    name — is the Generate after's. A file the plan never counted (added since it, or edited) set aside: a Generate
    first."""
    held = plan.header.get("reference")
    if not isinstance(held, list):
        return False                                              # a plan from before the set-aside digests
    files = {entry[2] for entry in plan.files if len(entry) > 2}
    if len(files) != len(plan.files):
        return False                                              # a plan from before the per-file digests
    try:
        joined = set(parts.get("reference") or ()) - set(held)
        counted = _counted(parts, {} if memo is None else memo)
    except Exception:
        return False
    return bool(joined) and joined <= files - counted


def _only_added(plan, parts, added, memo=None):
    """True when the library counts every plan file, unchanged, and more: each of them a file the engine added
    (`added`, their digests)."""
    held = {entry[2] for entry in plan.files if len(entry) > 2}
    if len(held) != len(plan.files) or not added:
        return False
    try:
        now = _counted(parts, {} if memo is None else memo)
    except Exception:
        return False
    return held < now and now - held <= set(added)


# --------------------------------------------------------------------------------------------------------------- #
# The engine
# --------------------------------------------------------------------------------------------------------------- #

class Result:
    """One order's columns (02 §1). Keys are (Word, Reading), as every output names a row.

    `priority`, `progressive`: the two lists' rows, in order, as dicts shaped like the CSVs' (the columns a re-plan
    computes, and the order-free ones as the plan keeps them); `first`: key -> the item where the word is first met;
    `n_new`: item -> how many words are first met there; `score`, `counts` (High, Low, Goal): key -> numbers;
    `sequence`: item -> its place (1 = the first item of NOW); `pinned`: the pinned items, in groups, oldest pin
    first (02 §7); `dropped`: plan items not in the order (02 §6); `added`: the items the engine added since the
    plan (`Engine.add`, E2.2 D9); `provisional`: those of them added while a gate moved (`exact=False`: the next
    Generate may move numbers beyond the item's own words) and `reasons`: {item: [the gates that moved]} (E2.2 K10)."""

    __slots__ = ("priority", "progressive", "first", "n_new", "score", "counts", "sequence", "pinned", "dropped",
                 "added", "provisional", "reasons")

    def __init__(self, **values):
        for name in self.__slots__:
            setattr(self, name, values[name])

    def rows(self, order_mode="content"):
        """The rows Junban's match index is built from (`anki_match.build_index(rows=…)`), in Junban's order:
        "content" — the progressive list, "priority" — the priority list (`junban_order_mode`)."""
        if order_mode not in ORDER_MODES:
            raise ValueError(f"unknown order mode {order_mode!r}")
        return self.progressive if order_mode == "content" else self.priority

    def front(self, n, items=None, order_mode="content"):
        """The first `n` words of Junban's order (D6: tomorrow's cards), as (Word, Reading) keys. `items`: E6.4's
        day's content (CASE-02) — not built yet (02 §6)."""
        if items is not None:
            raise NotImplementedError("front(items=…) is E6.4's")
        out, seen = [], set()
        for row in self.rows(order_mode):
            key = (row["Word"], row["Reading"])
            if key not in seen:
                seen.add(key)
                out.append(key)
                if len(out) == n:
                    break
        return out


class Engine:
    """The re-plan over one plan file. `ids`: each plan file's item id (parallel to `plan.files`; None for a file
    the store no longer holds); by default its rel_path. `numbers_only`: a plan the engine stands aside for i+1 alone
    (`NUMBERS_EXACT`) is read all the same, for its numbers — the order, the first places and *N new* (the window's,
    laptop row 36), which follow any order and move exactly there (an i+1 list's words don't hang on the order; proven
    against each order's Generate) — never for its list: `result()` and an added file are a PlanError. Coverage, a
    shared phrase row or a weight that isn't whole stand aside still, alone or with i+1 (coverage's numbers aren't its
    Generate's)."""

    def __init__(self, plan, ids=None, numbers_only=False):
        # `self.plan` keeps the tables only (header, files, keys, rows, ties), never the per-file lines.
        if plan.per_file is None:
            raise PlanError("an engine's own copy holds no per-file lines: load the plan file again")
        reasons = aside_reasons(plan)
        if reasons and not (numbers_only and all(r in NUMBERS_EXACT for r in reasons)):
            raise PlanError(f"the engine stands aside: {reasons[0]}")
        self.numbers_only = ", ".join(reasons) or None      # why the list is refused (None: the engine's whole)
        # The engine keeps what it reads, not the plan's per-file lines (most of a loaded plan's memory): once the
        # caller lets its plan go, only the tables below stay.
        self.plan = Plan(plan.header, plan.files, plan.keys, plan.rows, plan.ties, None, plan.spell, plan.finished,
                         plan.sentences, plan.cowords, plan.pools, plan.picks, plan.firsts)
        files, keys = plan.files, plan.keys
        ids = [entry[0] for entry in files] if ids is None else list(ids)
        if len(ids) != len(files):
            raise PlanError("one item id per plan file")
        self._ids = ids
        self._f_of = {}
        for f, item in enumerate(ids):
            if item is None:
                continue
            if item in self._f_of:
                raise PlanError(f"two plan files are one item ({item!r})")
            self._f_of[item] = f
        w = plan.header["weights"]
        self._w = [w["now"], w["soon"], w["goal"]]
        n = len(keys)
        self._n = n
        self._half = [bool(key[3]) for key in keys]
        self._phrase = [1 if key[2] else 0 for key in keys]
        self._listed = [row is not None for row in plan.rows]
        self._lemma = [key[0] for key in keys]
        self._occ = [key[4] for key in keys]           # Occurrences, grown by the files the engine adds
        self._source = [entry[0].rsplit("/", 1)[-1] for entry in files]      # each file's Source File
        self._path = [entry[0] for entry in files]                           # and its Source Path (E-NAMES)
        # Per file: its keys and uses (words, then the phrase rows' own entries) — a Generate's insertion order: files
        # in the order, each file's words as first counted, phrases after words. A key's place in `ks` is its place
        # in that order within the file (words before phrases, as the rank needs).
        self._uses = []
        files_of = [[] for _ in range(n)]
        idx_in = [array("i") for _ in range(n)]
        for f, line in enumerate(plan.per_file):
            ks, us = array("i"), array("i")
            for table in (line["main"], line["ph"]):
                ks.extend(table[0::2])
                us.extend(table[1::2])
            for i, k in enumerate(ks):
                files_of[k].append(f)
                idx_in[k].append(i)
            self._uses.append((ks, us))
        self._files_of = [array("i", fs) for fs in files_of]
        self._common = frozenset(k for k in range(n) if len(files_of[k]) > _SHORT)
        self._rare_held = sum(len(files_of[k]) for k in range(n) if k not in self._common)
        # A rare key's place among each of its files' keys (parallel to `_files_of`): its first file's is its
        # insertion order (`_numbers`). None for a common key, which the walk finds.
        self._idx_in = [None if k in self._common else idx_in[k] for k in range(n)]
        self._prog = [self._prog_file(line) for line in plan.per_file]   # the progressive pass's input
        # F7: each file's listed rows and their first sentence there ([k, sentence id, …]): a row's Context 1 is its
        # first sentence in its first file, wherever the order puts that file, and those of the next NEAR_FILES
        # files holding it are candidates too (`contexts`).
        # Format 5: none — a row's sentences are the sentence table's, and a move reads no first sentence (SPEC § 6.1
        # row 8).
        in_table = plan.header.get("format", 0) >= PICKS_IN_TABLE
        self._fs = [array("i", line.get("fs", ()) if plan.picks and not in_table else ()) for line in plan.per_file]
        self._ties = {tie[0]: tie for tie in plan.ties}
        # Each phrase row's dictionary spelling (format 4): its `Kana` is that of the spelling it shows
        # (`plan_rules.display_reading`, the Generate's rule). An older plan has none: `Kana` stays empty.
        self._display = {e[0]: e[2] for e in plan.header.get("phrase_entries") or () if len(e) > 2}
        self._sp = {}
        for f, line in enumerate(plan.per_file):
            if line.get("sp"):
                self._sp[f] = {sp[0]: (sp[1], sp[2]) for sp in line["sp"]}
        self._pins = []
        self._gone = frozenset()             # (Kotoba-K) the keys `leave_out` holds out of every file's uses
        self._whole = {}                     # ... and the uses of each file it took them from, as the plan has them
        self._added, self._reasons = [], {}     # the items `add` placed, in order; {item: [gates]}: those not exact
        self.renumbered = 0                  # how many times a move found no room and spaced every item afresh
        self.unread = 0                      # (F7) the shown sentences the last re-pick couldn't read the text of
        # The plan's own order, checked now (a bad one is a PlanError here, as ever) and its live numbers worked out at
        # the first ask (`__getattr__`) — never when a `replan` comes first (a redraw's): one pass over every use, not
        # the plan's order's and then the replan's (G3)
        self._plan_order = self._checked([(ids[f], entry[1]) for f, entry in enumerate(files) if ids[f] is not None])

    def __getattr__(self, name):
        """Only reached for an attribute not set: the live numbers (`_LIVE`) before the first `_numbers`, for the plan's
        own order."""
        pending = self.__dict__.get("_plan_order")
        if pending is None or name not in _LIVE:
            raise AttributeError(name)
        self._numbers(None, pending)
        return self.__dict__[name]

    # ----------------------------------------------------------------------------------------------------------- #
    # From scratch (02 §2): the referee
    # ----------------------------------------------------------------------------------------------------------- #

    def replan(self, order, pins=None, pick=False, texts=None, chooser=None):
        """The order's live numbers from scratch. `order`: [(item_id, tier)] — the analysed tiers' items, NOW then
        Soon then 6+ Months, each in the store's order. An item the plan doesn't hold is a PlanError (the library
        changed: Generate first); a plan item not in `order` is dropped (it left the counted tiers, 02 §6: the
        remaining words' places are right, the list's membership waits for the next Generate)."""
        self._numbers(order)
        if pins is not None:
            self.set_pins(pins)
        return self.result(pick, texts, chooser)

    def _checked(self, order):
        """`order` ([(item_id, tier)]) as ([plan file], [tier slot]), or a PlanError: an item the plan doesn't hold,
        one twice, an unknown tier, the tiers out of order."""
        fs, tiers = [], []
        seen = set()
        last = 0
        for item, tier in order:
            f = self._f_of.get(item)
            if f is None:
                raise PlanError(f"the plan doesn't hold item {item!r}: the library changed, Generate first")
            if f in seen:
                raise PlanError(f"item {item!r} is in the order twice")
            slot = _SLOT.get(tier)
            if slot is None:
                raise PlanError(f"unknown tier {tier!r}")
            if slot < last:
                raise PlanError("the order isn't NOW, then Soon, then 6+ Months")
            last = slot
            seen.add(f)
            fs.append(f)
            tiers.append(slot)
        return fs, tiers

    def _numbers(self, order, checked=None):
        """The live numbers from scratch for `order` (replan's checks and work, without the result); `checked`: its
        `_checked` already."""
        fs, tiers = checked if checked is not None else self._checked(order)
        self.__dict__.pop("_plan_order", None)      # (from here on the order's numbers, never the plan's own)
        n_files = len(self._uses)
        self._order = fs
        self._order_v = self.__dict__.get("_order_v", 0) + 1     # Hover-W: what `words_of`'s spellings are kept for
        self._tier = [None] * n_files
        self._pos = [None] * n_files
        for i, (f, slot) in enumerate(zip(fs, tiers)):
            self._tier[f] = slot
            self._pos[f] = (i + 1) * _GAP
        self._tier_count = [tiers.count(s) for s in range(3)]

        n = self._n
        by_tier = ([0] * n, [0] * n, [0] * n)
        first = [None] * n
        first_idx = [0] * n                 # the word's place among its first file's words: a Generate's insertion order
        uses = self._uses
        # First files: the walk below finds the common keys', each rare key looks among its own files after it — unless
        # the order holds fewer uses than the rare keys have plan files (most items left out): then the walk finds all.
        walk_all = sum(len(uses[f][0]) for f in fs) < self._rare_held
        unseen = (set(range(n)) if walk_all else set(self._common)) - self._gone   # the keys the walk looks for
        # One pass over every use (most of a re-plan's time): each tier's counts only; the weights are whole numbers
        # (stands_aside), so the Score summed from the tiers' counts is the Score summed use by use.
        for f, slot in zip(fs, tiers):
            ks, us = uses[f]
            c = by_tier[slot]
            for k, u in zip(ks, us):
                c[k] += u
            if unseen and not unseen.isdisjoint(ks):
                for i, k in enumerate(ks):
                    if k in unseen:                  # never a rare key while it walks for the common ones only:
                                                     # the walk skips files, a rare key's first may be one of them
                        first[k] = f
                        first_idx[k] = i
                unseen.difference_update(ks)
        # The rare keys (and a common one no file in the order holds): each one's first file in the order, from its own
        # files' places in the order (a file left out is placed after every one in it).
        missing = len(fs)
        seq = [missing] * n_files
        for i, f in enumerate(fs):
            seq[f] = i
        place = seq.__getitem__
        gone = self._gone
        for k in () if walk_all else range(n):
            if first[k] is not None or k in gone:
                continue
            held = self._files_of[k]
            i = min(map(place, held), default=missing)
            if i < missing:
                f = fs[i]
                first[k] = f
                idx = self._idx_in[k]
                first_idx[k] = uses[f][0].index(k) if idx is None else idx[held.index(f)]
        w0, w1, w2 = self._w
        now, soon, goal = by_tier
        raw = [w0 * a + w1 * b + w2 * c for a, b, c in zip(now, soon, goal)]
        counts = [[a, b, c] for a, b, c in zip(now, soon, goal)]
        self._raw, self._counts, self._first, self._first_idx = raw, counts, first, first_idx
        self._n_new = [0] * n_files
        for f in first:
            if f is not None:
                self._n_new[f] += 1
        self._rank_of = [None] * n
        ranked = []
        for k in range(n):
            if self._listed[k] and first[k] is not None:
                r = self._rank(k)
                self._rank_of[k] = r
                ranked.append(r)
        ranked.sort()
        self._ranked = ranked

    def _score(self, k):
        return self._raw[k] // 2 if self._half[k] else self._raw[k]

    def _rank(self, k):
        """The priority list's sort key (`analyzer.py`'s, 02 §2.5): Score down, first place, the phrase flag, then a
        Generate's insertion order — the word's place among its first file's words (or phrases); `k` last, never
        reached (two keys can't share a first file's place)."""
        return (-self._score(k), self._pos[self._first[k]], self._phrase[k], self._first_idx[k], k)

    # ----------------------------------------------------------------------------------------------------------- #
    # Incremental (02 §3)
    # ----------------------------------------------------------------------------------------------------------- #

    def move(self, item_ids, tier, before_id=None, after_id=None, n_new_was=None):
        """Place a block of items as `Store.move` does: in their current relative order, contiguous before or after
        the anchor (neither: the top of `tier`). `item_ids`: one id, or any collection of ids. Returns (the words
        whose Score, tier counts or first item changed, as (Word, Reading); the items moved). Only the block
        re-weights and only its words can change first place; the others keep theirs (a move pushes no other item
        across a line, RP-2). `n_new_was` (a dict, DSA-START): filled with {file: its *N new* before} for every file
        whose *N new* this move touched — the only ones it can change (the window's numbers walk these, never every
        file)."""
        if isinstance(item_ids, (str, bytes, int)) or not hasattr(item_ids, "__iter__"):
            items = [item_ids]
        else:
            items = list(dict.fromkeys(item_ids))
        slot = _SLOT.get(tier)
        if slot is None:
            raise PlanError(f"unknown tier {tier!r}")
        pos = self._pos
        block = []
        for item in items:
            f = self._f_of.get(item)
            if f is None or pos[f] is None:
                raise PlanError(f"item {item!r} isn't in the order")
            block.append(f)
        if not block:
            return [], []
        block.sort(key=pos.__getitem__)
        anchor = before_id if before_id is not None else after_id
        if anchor is not None:
            a = self._f_of.get(anchor)
            if a is None or pos[a] is None or self._tier[a] != slot:
                raise PlanError("the anchor is not in that tier")
            if a in block:
                return [], []
        block_set = set(block)
        old = self._order
        # Where a moved word's next file is looked for: the first item after the block's first, in the old order,
        # that stays — every file before the old first file of a word lacks it.
        i = old.index(block[0])
        if len(block) == 1:
            walk_from = old[i + 1] if i + 1 < len(old) else None
        else:
            walk_from = next((g for g in old[i + 1:] if g not in block_set), None)
        touched = {}                                # word -> its numbers before the move
        holders = {}                                # word -> the block's files that hold it, in the block's order
        for f in block:
            for k in self._uses[f][0]:
                if k not in touched:
                    touched[k] = (self._raw[k], tuple(self._counts[k]), self._first[k])
                    holders[k] = [f]
                else:
                    holders[k].append(f)
        if len(block) == 1:
            order = old
            del order[i]
        else:
            order = [f for f in old if f not in block_set]
        for f in block:
            self._tier_count[self._tier[f]] -= 1
        at = sum(self._tier_count[:slot]) if anchor is None else order.index(a) + (1 if before_id is None else 0)
        order[at:at] = block
        self._order = order
        self._order_v += 1
        old_tier = [self._tier[f] for f in block]
        for f in block:
            self._tier[f] = slot
            self._tier_count[slot] += 1
        if not self._place(at, len(block)):
            self._respace()

        w = self._w
        for f, moved_from in zip(block, old_tier):
            if moved_from == slot:
                continue
            ks, us = self._uses[f]
            delta = w[slot] - w[moved_from]
            for k, u in zip(ks, us):
                self._raw[k] += delta * u
                c = self._counts[k]
                c[moved_from] -= u
                c[slot] += u
        firsts = self._new_firsts([k for k, before in touched.items() if before[2] in block_set], block_set, holders,
                                  walk_from)
        changed = []
        for k, before in touched.items():
            was = before[2]
            new = firsts[k] if was in block_set else min([was] + holders[k], key=pos.__getitem__)
            if new != was:
                if n_new_was is not None:
                    n_new_was.setdefault(was, self._n_new[was])
                    n_new_was.setdefault(new, self._n_new[new])
                self._n_new[was] -= 1
                self._n_new[new] += 1
                self._first[k] = new
                self._first_idx[k] = self._uses[new][0].index(k)
            if self._listed[k]:
                r = self._rank(k)
                if r != self._rank_of[k]:
                    ranked = self._ranked
                    del ranked[bisect.bisect_left(ranked, self._rank_of[k])]
                    bisect.insort(ranked, r)
                    self._rank_of[k] = r
            if (self._raw[k], tuple(self._counts[k]), new) != before:
                changed.append(k)
        keys = self.plan.keys
        return [(keys[k][0], keys[k][1]) for k in changed], [self._ids[f] for f in block]

    def _new_firsts(self, pending, block_set, holders, walk_from):
        """The first file of each word whose first file moved (in `block`): the earliest of the block's files that
        hold it and — for a word in few files, by looking at each of them; for a commoner one, by walking the new
        order from `walk_from` (the first item that stayed, after the block's old place) until a file holds it, which
        for a common word is a few items on."""
        pos = self._pos
        out, walk = {}, set()
        for k in pending:
            files = self._files_of[k]
            if len(files) <= _SHORT:
                out[k] = min((f for f in files if pos[f] is not None), key=pos.__getitem__)
            elif len(files) == len(holders[k]):
                out[k] = min(holders[k], key=pos.__getitem__)     # every file of it moved: nothing to walk for
            else:
                walk.add(k)
        if walk:
            found = {}
            if walk_from is not None:
                order, uses = self._order, self._uses
                # Past the latest of the walked words' own earliest block holder, nothing found could come first.
                limit = max(min(pos[f] for f in holders[k]) for k in walk)
                for j in range(order.index(walk_from), len(order)):
                    g = order[j]
                    if g in block_set:
                        continue
                    if pos[g] > limit:
                        break
                    for k in uses[g][0]:
                        if k in walk and k not in found:
                            found[k] = g
                    if len(found) == len(walk):
                        break
            for k in walk:
                candidates = list(holders[k])
                if k in found:
                    candidates.append(found[k])
                out[k] = min(candidates, key=pos.__getitem__)
        return out

    def _place(self, at, m):
        """Places for the block now at order[at:at+m], between its neighbours' (the very top and the very end have
        room without end); False when there is none."""
        order, pos = self._order, self._pos
        if at + m < len(order):
            high = pos[order[at + m]]
            low = pos[order[at - 1]] if at > 0 else high - (m + 1) * _GAP
        else:
            low = pos[order[at - 1]] if at > 0 else 0
            high = low + (m + 1) * _GAP
        step = (high - low) // (m + 1)
        if step < 1:
            return False
        for i in range(m):
            pos[order[at + i]] = low + (i + 1) * step
        return True

    def _respace(self):
        """No room left between two places (40 drags into one gap): every item gets a fresh, evenly spaced place in
        the same order. Only places change — Score, counts, first files and N new stay; the rank keys hold places, so
        the rank is sorted again."""
        self.renumbered += 1
        pos = self._pos
        for i, f in enumerate(self._order):
            pos[f] = (i + 1) * _GAP
        ranked = []
        for k, r in enumerate(self._rank_of):
            if r is not None:
                r = self._rank_of[k] = self._rank(k)
                ranked.append(r)
        ranked.sort()
        self._ranked = ranked

    # ----------------------------------------------------------------------------------------------------------- #
    # Arrivals (E2.2 D9)
    # ----------------------------------------------------------------------------------------------------------- #

    def add(self, item_id, record, tier, before_id=None, after_id=None, exact=True, moved=()):
        """A new file joins the order, counted from its arrival record (`arrivals.record`: its plan line — `main`,
        `ph`, `sp`, `prog` — and its spelling counts `spc`, with the plan it was read against): placed as `Store.move`
        places an item (before or after the anchor; neither: the top of `tier`). Its uses join Score, the tier
        counts and Occurrences; only its words can change first place, *N new* and the rank, as in `move`; its
        spellings join the tied words' counts. `exact`: the gates found nothing else the arrival moves
        (`arrivals.Gates.check`) — then `result()` is the next full Generate's plan columns; False: the item is
        provisional (`Result.provisional`, with `moved` as its `reasons`) — still a valid order to re-plan and re-order
        Anki by (E2.2 K10), corrected when the next Generate's plan replaces this engine. "The plan columns" are 05 §1's:
        a priority row's `Sources`, `Modality` and example sentences (`Context n` / `Src n`) stay the plan's — the next
        Generate may give the arrival's words a new source kind or a better sentence. Returns (the words whose
        Score, tier counts or first item changed, as (Word, Reading); [item_id]). A record read against another plan,
        or one that doesn't fit this plan's words, is a PlanError."""
        if self.numbers_only:
            raise PlanError(f"the engine stands aside: {self.numbers_only}; its numbers only")
        if item_id is None or item_id in self._f_of:
            raise PlanError(f"item {item_id!r} is in the plan already")
        slot = _SLOT.get(tier)
        if slot is None:
            raise PlanError(f"unknown tier {tier!r}")
        pos = self._pos
        anchor = before_id if before_id is not None else after_id
        if anchor is not None:
            a = self._f_of.get(anchor)
            if a is None or pos[a] is None or self._tier[a] != slot:
                raise PlanError("the anchor is not in that tier")
        ks, us, prog, sp, spc = self._arrival(record)

        # The file, as the engine holds every plan file (`__init__`).
        f = len(self._uses)
        self._ids.append(item_id)
        self._f_of[item_id] = f
        if self._gone and not self._gone.isdisjoint(ks):     # (Kotoba-K) a word marked since stays out of it too
            self._whole[f] = (ks, us)
            ks, us = self._without(ks, us)
        self._uses.append((ks, us))
        self._source.append(str(record.get("name") or str(item_id).replace("\\", "/").rsplit("/", 1)[-1]))
        self._path.append(str(record.get("path") or str(item_id).replace("\\", "/")))
        self._prog.append(prog)
        self._fs.append(array("i"))         # (its sentences aren't the plan's: none is a row's, until the Generate)
        if sp:
            self._sp[f] = sp
            self._order_v += 1                  # (a new file's tied spellings: the kept ones are stale)
        whole = self._whole.get(f)
        for i, k in enumerate(ks if whole is None else whole[0]):     # (a held-out word's files: all of them)
            self._files_of[k].append(f)
            if self._idx_in[k] is not None:
                if whole is None:
                    self._idx_in[k].append(i)
                    self._rare_held += 1
                else:
                    self._idx_in[k] = None              # (its place among the file's words: found by looking)
        for k, (orths, surfaces) in spc.items():
            tie = self._ties.get(k)
            if tie is not None:                         # the tied words' counts, which `result()` works Orth out from
                self._ties[k] = [k, _summed(tie[1], orths), _summed(tie[2], surfaces), tie[3]]
        self._n_new.append(0)
        self._tier.append(None)
        self._pos.append(None)

        # Its place: the top of the tier, or beside the anchor, between its neighbours' places (`move`'s).
        order = self._order
        at = sum(self._tier_count[:slot]) if anchor is None else order.index(a) + (1 if before_id is None else 0)
        order.insert(at, f)
        self._tier[f] = slot
        self._tier_count[slot] += 1
        if not self._place(at, 1):
            self._respace()

        weight = self._w[slot]
        changed = []
        for i, (k, u) in enumerate(zip(ks, us)):
            self._raw[k] += weight * u
            self._counts[k][slot] += u
            self._occ[k] += u
            was = self._first[k]
            if was is None or pos[f] < pos[was]:
                if was is not None:
                    self._n_new[was] -= 1
                self._n_new[f] += 1
                self._first[k] = f
                self._first_idx[k] = i
            if self._listed[k]:
                r = self._rank(k)
                ranked = self._ranked
                if self._rank_of[k] is not None:
                    del ranked[bisect.bisect_left(ranked, self._rank_of[k])]
                bisect.insort(ranked, r)
                self._rank_of[k] = r
            changed.append(k)
        self._added.append(item_id)
        if not exact:
            self._reasons[item_id] = list(moved)
        keys = self.plan.keys
        return [(keys[k][0], keys[k][1]) for k in changed], [item_id]

    def _arrival(self, record):
        """An arrival record checked against this plan, as `_validate` checks a plan file's lines: (keys, uses — words
        then phrase rows, as a file's line —, the progressive pass's line, its tied spellings {k: (orths, surfaces)},
        its spelling counts {k: (orths, surfaces)})."""
        h = self.plan.header
        if not isinstance(record, dict) or record.get("plan") != h["run_signature"] or record.get("keys") != self._n:
            raise PlanError("the arrival was read against another plan: read it again")
        n, phrases = self._n, self._phrase
        ks, us = array("i"), array("i")
        for table, is_phrase in (("main", 0), ("ph", 1)):
            tks, tus = _pairs(record.get(table), n, "the arrival's uses are damaged")
            if (tus and min(tus) < 1) or len(set(tks)) != len(tks) or any(phrases[k] != is_phrase for k in tks):
                raise PlanError("the arrival's uses are damaged")
            ks.extend(tks)
            us.extend(tus)
        if len(set(ks)) != len(ks):
            raise PlanError("the arrival's uses are damaged")
        line = {"prog": record.get("prog")}
        prog = line["prog"]
        if not (isinstance(prog, list) and len(prog) == 7 and type(prog[0]) is int and type(prog[1]) is int
                and 0 <= prog[1] <= prog[0] < _LIMIT):
            raise PlanError("the arrival's progressive record is damaged")
        for table in (prog[2], prog[3], prog[4], prog[5]):
            _pairs(table, n, "the arrival's progressive record is damaged")
        if not isinstance(prog[6], list) or not all(
                isinstance(sib, list) and len(sib) == 2 and isinstance(sib[0], str) and _count(sib[1])
                for sib in prog[6]):
            raise PlanError("the arrival's progressive record is damaged")
        ties = self._ties
        sps = record.get("sp", [])
        if not isinstance(sps, list) or not all(
                isinstance(x, list) and len(x) == 3 and x[0] in ties and _strings(x[1]) and _strings(x[2]) for x in sps):
            raise PlanError("the arrival's spellings are damaged")
        spc = {}
        for k, counts in (record.get("spc") or {}).items():
            try:
                k = int(k)                              # a JSON round trip writes the keys as text
            except (TypeError, ValueError):
                raise PlanError("the arrival's spelling counts are damaged") from None
            if not (0 <= k < n and isinstance(counts, (list, tuple)) and len(counts) == 2
                    and _counts(counts[0]) and _counts(counts[1])):
                raise PlanError("the arrival's spelling counts are damaged")
            spc[k] = (counts[0], counts[1])
        return ks, us, self._prog_file(line), {x[0]: (x[1], x[2]) for x in sps}, spc

    # ----------------------------------------------------------------------------------------------------------- #
    # Pins (02 §7)
    # ----------------------------------------------------------------------------------------------------------- #

    def set_pins(self, pins):
        """The pinned items, `[(item_id, pinned_at)]` from the store's `pinned()` — any tier, Finished included. A pin
        moves an item's cards to the front of Anki's queue (03 §8), never a word: no column changes here."""
        self._pins = [(item, at) for item, at in (pins or ())]

    def _pinned(self):
        """`plan_rules.pin_groups` (oldest pin first; one `pin` command, one group), each group's items listed in the
        order's sequence, then the items outside the analysed tiers by id — display only: the cards of a group go in
        Junban's own order (03 §8)."""
        pos = self._pos

        def place(item):
            f = self._f_of.get(item)
            p = pos[f] if f is not None else None
            return (0, p, "") if p is not None else (1, 0, str(item))
        return plan_rules.pin_groups(self._pins, place)

    # ----------------------------------------------------------------------------------------------------------- #
    # The result
    # ----------------------------------------------------------------------------------------------------------- #

    def result(self, pick=False, texts=None, chooser=None):
        """The order's columns (02 §1): the live numbers as kept, the priority rows in rank order, and the progressive
        list and spelling ties worked out again for this order. Never for a numbers-only engine (its list can't be).
        `pick` (F7, a format-3 plan): the example sentences too — this order's re-pick (`contexts`), the Generate's
        own; else (and for an older plan) they stay as the last Generate wrote them (D1). A format-5 plan's are the
        sentence table's, asked of `chooser` (`contexts`)."""
        if self.numbers_only:
            raise PlanError(f"the engine stands aside: {self.numbers_only}; its numbers only")
        plan, keys, rows = self.plan, self.plan.keys, self.plan.rows
        order = self._order
        seq_of = {f: i for i, f in enumerate(order, 1)}
        spelled = self._spellings(order)
        spelling = self._spelling
        score = [self._score(k) for k in range(self._n)]
        counts = self._counts
        rank = (lambda k: (score[k], self._occ[k]))
        passes = list(plan_rules.progressive_pass((self._prog[f] for f in order), set(), set(),
                                                  self._lemma.__getitem__, self._listed.__getitem__, rank))
        # (format 5) each word's first row in this order's progressive list: the place the sentence table's own
        # `places` are (what is taught before it when it is studied, `sentence_table.Table.places`)
        self._study, at = {}, 0
        for file_rows, _baseline, _total in (passes if pick and plan.header.get("format", 0) >= PICKS_IN_TABLE
                                             else ()):
            for row_ in file_rows:
                self._study.setdefault(row_[0], at)
                at += 1
        picked = (self.contexts(texts, chooser) if pick else None) or {}
        # the columns: Sentences per word's number, or under All (0) as many as the row given the most has
        n_contexts = plan_rules.context_columns(plan.header.get("max_contexts") or 0, (
            len(picked.get(k, rows[k][6] if rows[k] is not None else ())) // 2 for k in range(self._n)))

        priority = []
        for r in self._ranked:
            k = r[-1]
            orth, forms, tier = spelling(k, spelled)
            row = rows[k]
            out = {"Word": keys[k][0], "Reading": keys[k][1], "Kana": self._kana(k, orth), "Orth": orth,
                   "Forms": forms, "Tier": tier,
                   "Score": score[k], "Occurrences": self._occ[k], "Count (High)": counts[k][0],
                   "Count (Low)": counts[k][1], "Count (Goal)": counts[k][2], "Sources": row[3], "Modality": row[2]}
            _contexts(out, picked.get(k, row[6]), n_contexts)
            priority.append(out)

        progressive = []
        for (f, (file_rows, baseline_pct, total)) in zip(order, passes):
            seq = seq_of[f]
            source, source_path = self._source[f], self._path[f]
            for k, count, known_count, start_pct, end_pct in file_rows:
                orth, forms, _tier = spelling(k, spelled)
                row = rows[k]
                out = {"Sequence": seq, "Source File": source, "Source Path": source_path, "Word": keys[k][0],
                       "Orth": orth, "Forms": forms, "Reading": keys[k][1], "Kana": self._kana(k, orth),
                       "Tier": row[1] or row[0], "Score": score[k],
                       "Occurrences (Global)": self._occ[k], "Occurrences (File)": count,
                       "Count (High)": counts[k][0],
                       "Count (Low)": counts[k][1], "Count (Goal)": counts[k][2], "Modality": row[2]}
                _contexts(out, picked.get(k, row[6]), n_contexts)
                out.update({"Baseline %": baseline_pct, "Current %": start_pct, "New %": end_pct,
                            "Known Count": known_count, "Total Count": total})
                progressive.append(out)

        ids = self._ids
        key_of = [(key[0], key[1]) for key in keys]
        return Result(
            priority=priority, progressive=progressive,
            first={key_of[k]: ids[f] for k, f in enumerate(self._first) if f is not None},
            n_new={ids[f]: self._n_new[f] for f in order},
            score={key_of[k]: score[k] for k in range(self._n)},
            counts={key_of[k]: tuple(counts[k]) for k in range(self._n)},
            sequence={ids[f]: seq_of[f] for f in order},
            pinned=self._pinned(),
            dropped=[ids[f] for f in range(len(ids)) if ids[f] is not None and self._pos[f] is None],
            added=list(self._added), provisional=[item for item in self._added if item in self._reasons],
            reasons={item: list(gates) for item, gates in self._reasons.items()})

    def contexts(self, texts=None, chooser=None):
        """Format 5 (the sentence choice's release 2, SPEC § 5.2): the rows' sentences are the one reader's, over the
        sentence table — handed over to `chooser(keys, order) -> {(Word, Reading): [Context 1, Src 1, …]}` (the
        caller's: this module reads no table, store or settings), `keys` the listed rows in this order's rank order,
        `order` {key: its first row in this order's progressive list} (the table's `places`: what is taught before a
        word when it is studied; `result` works it out first); a row it leaves out keeps the last Generate's columns. A PlanError when there is no
        chooser or it has no answer (no table: the caller Generates).

        Before: F7: every listed row's example sentences for this order — the Generate's pick (`plan_rules.ContextPicker`,
        one rule) down this order's list, on the plan's order-free pools: {k: [Context 1, Src 1, …]}; None for a plan
        before format 3 or one read without them (`load(pools=False)`). Context 1 is a row's first sentence in its
        first file, and its first sentences in the next `near_files` files holding it are candidates beside its pools
        (the plan holds every file's: `fs`, kept without their text). The text of the few of those it shows is asked
        of `texts({rel_path: [sentence number, …]}) -> {(rel_path, number): (text, shown)}` (the caller's token
        store); one unanswered shows empty. A sentence of a file that left the order is no candidate."""
        plan = self.plan
        h = plan.header
        if h.get("format", 0) >= PICKS_IN_TABLE:
            return self._chosen(chooser)
        if h.get("format") not in (3, 4) or not plan.picks:
            return None
        files, finished = plan.files, plan.finished
        n_files = len(files)
        pos, order = self._pos, self._order
        seq_of = {f: i for i, f in enumerate(order, 1)}
        sentences = plan_rules.SentenceView(plan.sentences, plan.firsts)
        near_files, max_chars = h.get("near_files", 0), h.get("max_chars", 0)
        firsts = {}                                 # k -> [its first sentence, then the next near_files files' ones]
        for f in order:
            fs = self._fs[f]
            for j in range(0, len(fs), 2):
                found = firsts.get(fs[j])
                if found is None:
                    firsts[fs[j]] = [fs[j + 1]]
                elif len(found) <= near_files:
                    found.append(fs[j + 1])

        def place(src):
            if src >= n_files:
                return (finished[src - n_files][2], 0)
            return (plan_rules.NOT_FINISHED, seq_of.get(src, 0))

        def audio(src):
            kind = files[src][3] if src < n_files else finished[src - n_files][1]
            return 0 if kind == "youtube" else (1 if kind in ("subtitle", "bilibili") else 2)

        def where(src):
            return files[src][0] if src < n_files else finished[src - n_files][0]

        def live(ids):
            return [s for s in ids if sentences[s][4] >= n_files or pos[sentences[s][4]] is not None]

        n_contexts = plan_rules.context_limit(h.get("max_contexts") or 0)      # 0: All, every kept candidate
        picker = plan_rules.ContextPicker(sentences, plan.cowords, n_contexts, place, audio,
                                          only_i_plus_one=bool(h.get("only_i_plus_one")),
                                          ensure_audio=h.get("ensure_audio"), recency_files=h.get("recency_files", 1))
        out = {}
        for r in self._ranked:
            k = r[-1]
            seq = seq_of[self._first[k]]
            mine = firsts.get(k) or [None]
            near = [s for s in mine[1:] if sentences[s][plan_rules.CHARS] <= max_chars]
            _first, pool, audio_pool = plan.pools.get(k, (-1, (), ()))
            chosen = picker.pick(k, seq, mine[0], live(pool) + near, live(audio_pool))
            if chosen is None:
                continue                            # (Only i+1, no i+1 sentence: the word is skipped, never learned)
            picker.learn(k, bool(self._phrase[k]), seq)
            out[k] = list(chosen or ())
        # The text of those kept without it: the sentence table's own where it holds the same sentence (the last
        # Generate's shortlists and its nearest files), else read once each (the files a move brought nearer)
        held = None
        wanted = {}
        for chosen in out.values():
            for j, s in enumerate(chosen):
                if sentences[s][plan_rules.TEXT] is None:
                    st = sentences[s]
                    if held is None:
                        held = {(t[plan_rules.SRC], t[plan_rules.NUMBER], t[plan_rules.HASH]): i
                                for i, t in enumerate(plan.sentences)}
                    twin = held.get((st[plan_rules.SRC], st[plan_rules.NUMBER], st[plan_rules.HASH]))
                    if twin is not None:
                        chosen[j] = twin
                    else:
                        wanted.setdefault(files[st[plan_rules.SRC]][0], set()).add(st[plan_rules.NUMBER])
        answered = {}
        if wanted and texts is not None:
            try:
                answered = texts({rel: sorted(numbers) for rel, numbers in wanted.items()}) or {}
            except Exception:
                answered = {}
        self.unread = 0
        for k, chosen in out.items():
            kept = []
            for s in chosen:
                st = sentences[s]
                shown = picker.shown(s)
                if shown is None:
                    found = answered.get((files[st[plan_rules.SRC]][0], st[plan_rules.NUMBER]))
                    shown = found[1] if found else ""
                    self.unread += not found        # (the caller decides: the redraw Generates instead)
                kept += (shown, where(st[plan_rules.SRC]))
            out[k] = kept
        return out

    def _chosen(self, chooser):
        """`contexts` for a format-5 plan: the listed rows, in rank order, handed to `chooser` -> {k: columns}."""
        keys = self.plan.keys
        ranked = [r[-1] for r in self._ranked]
        asked = [(keys[k][0], keys[k][1]) for k in ranked]
        study = getattr(self, "_study", None)       # (None: asked outside `result` — the table's own order)
        order = None if study is None else {(keys[k][0], keys[k][1]): at for k, at in study.items()}
        got = chooser(asked, order) if chooser is not None else None
        if got is None:
            raise PlanError("no sentence table to choose the sentences from: Generate first")
        self.unread = 0
        return {k: list(got[key]) for k, key in zip(ranked, asked) if key in got}

    def leave_out(self, lemmas):
        """Kotoba-K: the words marked Known or Ignore since the plan (`lemmas`: every such word now — the whole set,
        not a change) left out of the numbers at once, as the next Generate leaves them out: no first place, no *N new*,
        no rank, never in `words_of`; every other word's numbers as that Generate's (a word's place among its first
        file's words counts only the words still there). A word taken out of `lemmas` again (an undo, a clear) comes
        back with its plan numbers (worked out from scratch; a mark is taken out in place). -> True when the numbers
        changed."""
        lemmas = frozenset(lemmas or ())
        gone = frozenset(k for k, lemma in enumerate(self._lemma) if lemma in lemmas) if lemmas else frozenset()
        if gone == self._gone:
            return False
        only_added = self._gone <= gone             # a mark (the common case): its keys taken out in place
        touched = set()
        for k in gone ^ self._gone:
            touched.update(self._files_of[k])
        added = gone - self._gone
        self._gone = gone
        for f in touched:
            ks, us = self._whole.get(f) or self._uses[f]
            if gone.isdisjoint(ks):
                self._whole.pop(f, None)
                self._uses[f] = (ks, us)
            else:
                self._whole[f] = (ks, us)
                self._uses[f] = self._without(ks, us)
            idx_in = self._idx_in
            for k in ks:                            # a place among the file's words moved: found by looking
                idx_in[k] = None
        if only_added:
            self._taken_out(added, touched)
        else:                                       # a clear brings words back: worked out from scratch
            self._numbers([(self._ids[f], TIERS[self._tier[f]]) for f in self._order])
        return True

    def _taken_out(self, keys, touched):
        """`keys` just held out (their files' uses already without them): each loses its first place, its *N new* and
        its rank; a word still in a touched file whose first file that is takes its place among the words left there
        (the rank's tie-break, a Generate's insertion order), its rank moved with it. Equals `_numbers` (the tests)."""
        first, ranked = self._first, self._ranked
        for k in keys:
            f = first[k]
            if f is not None:
                self._n_new[f] -= 1
                first[k] = None
            if self._rank_of[k] is not None:
                del ranked[bisect.bisect_left(ranked, self._rank_of[k])]
                self._rank_of[k] = None
            self._raw[k] = 0
            self._counts[k] = [0, 0, 0]
        for f in touched:
            for i, k in enumerate(self._uses[f][0]):
                if first[k] == f and self._first_idx[k] != i:
                    self._first_idx[k] = i
                    if self._rank_of[k] is not None:
                        del ranked[bisect.bisect_left(ranked, self._rank_of[k])]
                        r = self._rank(k)
                        bisect.insort(ranked, r)
                        self._rank_of[k] = r

    def _without(self, ks, us):
        gone = self._gone
        kept = [(k, u) for k, u in zip(ks, us) if k not in gone]
        return array("i", (k for k, _u in kept)), array("i", (u for _k, u in kept))

    def words_of(self, item_ids):
        """Hover-W: a title's words in this order — `item_ids` its files (any not held or out of the order are left
        out). -> (new, before): `new` the words first met in one of its files, the list's order (Score down, first
        place, …, as `_rank`); `before` its other words, each first met in an earlier file — in journey order (where
        they are taught), each place's most useful first. Every one a `TitleWord`; `len(new)` is always the sum of its
        files' *N new*. `at` the title's own file where the word is first met (its sentence's file); `taught` the file
        whose *N new* counts it."""
        fs = []
        for item in dict.fromkeys(item_ids):
            f = self._f_of.get(item)
            if f is not None and self._pos[f] is not None:
                fs.append(f)
        fs.sort(key=self._pos.__getitem__)
        held = set(fs)
        at = {}
        for f in fs:
            for k in self._uses[f][0]:
                if k not in at:
                    at[k] = f
        first, pos, score = self._first, self._pos, self._score
        new, before = [], []
        for k in at:
            if first[k] is not None:
                (new if first[k] in held else before).append(k)
        new.sort(key=lambda k: (-score(k), pos[first[k]], self._phrase[k], self._first_idx[k], k))
        before.sort(key=lambda k: (pos[first[k]], -score(k), self._first_idx[k], k))
        spelled = {}
        if self._ties and not self._ties.keys().isdisjoint(at):
            kept = getattr(self, "_spelled", None)       # the tied spellings' walk is every file (~3 ms at 20k):
            if kept is None or kept[0] != self._order_v:  # once per order, not once per card
                kept = self._spelled = (self._order_v, self._spellings(self._order))
            spelled = kept[1]
        ids, keys = self._ids, self.plan.keys

        def word(k):
            return TitleWord(keys[k][0], keys[k][1], self._label(k, spelled), bool(self._phrase[k]), ids[at[k]],
                             ids[first[k]], at[k], k)
        return [word(k) for k in new], [word(k) for k in before]

    def _label(self, k, spelled):
        """The spelling a row shows (`Orth`, ties worked out in this order); a word the list doesn't hold: its Word."""
        if self.plan.rows[k] is None:
            return self.plan.keys[k][0]
        return self._spelling(k, spelled)[0] or self.plan.keys[k][0]

    @staticmethod
    def _prog_file(line):
        """A file's line of the progressive pass (`plan_rules.progressive_pass`) from its plan record (01 §7): the
        tokens as three compact arrays (keys, counts, the uses a phrase took — nearly always none), siblings, credits
        and phrase uses as pairs."""
        total, baseline, tokens, given, credits, phrases, siblings = line["prog"]
        keys = array("i", tokens[0::2])
        if given:
            given = dict(zip(given[::2], given[1::2]))
            bounds = array("i", [given.get(k, 0) for k in keys])
        else:
            bounds = array("i", bytes(4 * len(keys)))
        flat = (keys, array("i", tokens[1::2]), bounds)
        return (total, baseline, flat, [tuple(s) for s in siblings], list(zip(credits[::2], credits[1::2])),
                list(zip(phrases[::2], phrases[1::2])))

    def _spellings(self, order):
        """For each tied word, its tied spellings and surfaces in the order this order meets them (K108)."""
        spelled = {}
        for f in order:
            for k, (orths, surfaces) in self._sp.get(f, {}).items():
                o, s = spelled.setdefault(k, ([], []))
                o.extend(x for x in orths if x not in o)
                s.extend(x for x in surfaces if x not in s)
        return spelled

    def _kana(self, k, orth):
        """`Kana` for row k showing `orth`: a phrase row's spelling's own reading where it isn't the row's Reading
        (`plan_rules.display_reading`, as the Generate writes it), else ""."""
        display = self._display.get(k)
        if display is None:
            return ""
        reading = self.plan.keys[k][1]
        kana = plan_rules.display_reading(orth, display, reading)
        return "" if kana == reading else kana

    def _spelling(self, k, spelled):
        """(Orth, Forms, Tier) for row k: as the plan keeps them, or — where spellings tie — worked out again by the
        analyzer's own rule (`plan_rules.display_orth` / `display_forms`) on the counts, met in this order."""
        row = self.plan.rows[k]
        tie = self._ties.get(k)
        if tie is None:
            return row[4], row[5], row[0]
        _k, orth_counts, surface_counts, tiers = tie
        o_order, s_order = spelled.get(k, ((), ()))
        orths = {x: orth_counts[x] for x in o_order}
        orths.update((x, c) for x, c in orth_counts.items() if x not in orths)
        surfaces = {x: surface_counts[x] for x in s_order}
        surfaces.update((x, c) for x, c in surface_counts.items() if x not in surfaces)
        word = self.plan.keys[k][0]
        orth = plan_rules.display_orth(word, orths)
        return orth, plan_rules.display_forms(word, orths, surfaces), (tiers.get(orth, row[0]) if tiers else row[0])


TitleWord = namedtuple("TitleWord", "word reading label phrase at taught f k")
#   Hover-W (`Engine.words_of`): the key (Word, Reading), the spelling shown, whether it is a set phrase, the title's
#   item where it is first met and the item that teaches it (its first place); `f`, `k`: the plan's file and key


class FirstSentences:
    """Hover-W: every listed word's first sentence in each file, as the plan keeps it (F7's per-file `fs` and the
    packed `firsts`; the text stays in the token store) — read from the plan file, never decoded in a lean load. `of(f)`
    -> {k: (sentence number in the file, the text's hash)} (`plan_rules.text_hash_of`: a text read back is shown only
    when its hash is this one). `files` the plan's rel paths; `key` the file's (mtime_ns, size) when read."""

    def __init__(self, files, fs, number, hashes, offset, key=None):
        self.files, self._fs, self._number, self._hash, self._offset, self.key = files, fs, number, hashes, offset, key

    def of(self, f):
        if not 0 <= f < len(self._fs):
            return {}
        pairs, out = self._fs[f], {}
        for j in range(0, len(pairs), 2):
            i = pairs[j + 1] - self._offset
            if 0 <= i < len(self._number):
                out.setdefault(pairs[j], (self._number[i], self._hash[i]))
        return out

    def of_files(self, asked):
        """{f: rows} -> {f: `of(f)`} (the rows are `TableFirsts`'; here each file's every row)."""
        return {f: self.of(f) for f in asked}


def first_sentences(path):
    """`FirstSentences` from the plan file at `path` (format 3 or 4), or None: no plan, another format, one without
    first sentences (format 1 or 2), or tables that don't fit together. Its own read of the file — the window's numbers
    load it lean — on the caller's worker (at 20,000 files ~0.7 s, ~13 MB kept: Hover-W's register). At level 2 of the
    sentence table the word card reads the table first (`sentence_table.TableFirsts`, through
    `title_words.first_sentences`), this read its fall-back."""
    import base64
    import os
    try:
        st = os.stat(path)
        with open(path, "rb") as fh:
            lines = gzip.decompress(fh.read()).split(b"\n")
        header = json.loads(lines[0])
        if header.get("format") not in (3, 4):
            return None
        files, fs, offset, cols = [], [], 0, None
        for line in lines[1:]:
            if line.startswith(b'{"f":'):
                fs.append(array("i", json.loads(line).get("fs", ())))
            elif line.startswith(b'{"files":'):
                files += [entry[0] for entry in json.loads(line)["files"]]
            elif line.startswith(b'{"sentences":'):
                offset += len(json.loads(line)["sentences"])
            elif line.startswith(b'{"firsts":'):
                packed = json.loads(line)["firsts"]
                if len(packed) != 1 or packed[0].get("order") != sys.byteorder:
                    return None
                cols = {}
                for name, code in (("number", "i"), ("hash", "I")):
                    arr = array(code)
                    arr.frombytes(base64.b64decode(packed[0][name], validate=True))
                    cols[name] = arr
        del lines
    except (OSError, EOFError, ValueError, KeyError, TypeError, AttributeError, zlib.error):
        return None
    if cols is None or len(fs) != len(files) or len(cols["number"]) != len(cols["hash"]):
        return None
    return FirstSentences(files, fs, cols["number"], cols["hash"], offset, (st.st_mtime_ns, st.st_size))


def _contexts(out, kept, n):
    """The Context / Src columns as the last Generate wrote them (not re-planned, D1)."""
    for i in range(n):
        out[f"Context {i + 1}"] = kept[2 * i] if 2 * i < len(kept) else ""
        out[f"Src {i + 1}"] = kept[2 * i + 1] if 2 * i + 1 < len(kept) else ""


def _summed(counts, more):
    """`counts` with `more` added: a new dict, its keys in the order first met (the plan's first, then the new ones)."""
    out = dict(counts)
    for key, n in more.items():
        out[key] = out.get(key, 0) + n
    return out
