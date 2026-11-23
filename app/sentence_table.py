"""The sentence table (the sentence choice, SPEC § 3): every candidate sentence of every list word, kept as numbers.

Generate writes it (`results/sentences.bin`) beside the plan file while `plan_rules.SENTENCE_TABLE >= 1`; a reader
opens its head once, then reads only its own words' blocks. A line is kept if and only if its word is a row of the
list, it is a sentence of a file the Generate read, and — but for a file's first sentence of the word, kept with the
OVER mark and never chosen — it is no longer than *Never longer than*. Its text is not kept: a reader takes the text
of the few lines it shows from the token store (`Store.file_tokens`).

What is kept for a line (one row of the table is a line and its word):
  its file (the plan's numbering: its files, then the Finished ones) · its place in the file (the sentence number) ·
  its length in characters · its marks (OVER) · a fingerprint of its text (0 when no other line of the word says the
  same words) · the other words in it that are new, as co-words — each a formula over the list's rows ("known once
  any of these groups of rows is taught"), so "new when studied" is worked out for whatever the order has become ·
  the set phrases in it, as their rows · how many words besides the word it says · where the word starts.

The file: MAGIC, three little-endian 4-byte lengths, the head (zlib JSON: the format's version, the engine, the run's
signature, the language, every list row's (word, reading), the rows that have lines and each one's sizes — the head
is the index), the sources (zlib JSON: [rel, kind, digest]), the formulas (zlib, four int32 arrays), then one zlib
block a row: its lines' columns one after another, lines in (file, place) order. Little-endian always; the head's
keys in a fixed order; one compression level; no time, path of this PC or process id inside: the same run writes
the same bytes, packed as the walk goes or at the end.

The walk's side is `Packer`: lines are appended as the files are read, words, co-words and phrases by whatever key
the walk holds them by; `finish` resolves the keys (rows, formulas numbered by key) only at the end, so one file's
lines are a function of that file alone — a pool of workers could each pack its share and the main process join
them by key, in the plan's file order (SPEC § 8.3; not built).

numpy is imported here only (it arrives with pandas); the cost of a line is E-SCORE's (`app/sentence_score.py`).
"""
import json
import os
import struct
import zlib
from array import array

import numpy as np

TABLE_FILE = "sentences.bin"
MAGIC = b"SURATBL\n"
VERSION = 1
LEVEL = 3                       # zlib: 0.44 s for 7.01 MB at 20,000 files (lighter 7.42 MB, harder 1.15 s: SPEC § 8.2)

OVER = 1 << 2                   # marks: over *Never longer than* (a file's first sentence of the word; never chosen)
STARTS_PAST = 255               # where the word starts: 255 = at or past 255 characters
_SEP = (",", ":")

# One block's columns, in the order written: (name, little-endian dtype). `src` is written as the step from the line
# before (mostly 0) and read back whole.
COLUMNS = (("src", "<i4"), ("number", "<i4"), ("chars", "<u2"), ("marks", "u1"), ("ncow", "<u2"), ("nphr", "<u2"),
           ("fp", "<u4"), ("besides", "u1"), ("starts", "u1"))
_BYTES = sum(np.dtype(t).itemsize for _n, t in COLUMNS)


class Packer:
    """The walk's side: lines appended as the files are read, as compact arrays (no Python object per line)."""

    def __init__(self):
        self._ids, self._keys = {}, []          # any key (a word, a co-word) -> its provisional id; id -> key
        self.word, self.src, self.number = array("i"), array("i"), array("i")
        self.chars, self.marks, self.hash = array("i"), array("B"), array("I")
        self.besides, self.starts = array("B"), array("B")
        self.ncow, self.cow = array("i"), array("i")      # co-words: provisional ids
        self.nphr, self.phr = array("i"), array("i")      # set phrases: the walk's own numbers

    def _id(self, key):
        found = self._ids.get(key)
        if found is None:
            found = self._ids[key] = len(self._keys)
            self._keys.append(key)
        return found

    def __len__(self):
        return len(self.word)

    def add(self, word, src, number, chars, text_hash, cowords=(), phrases=(), besides=0, starts=0, over=False):
        """One candidate line of `word` (the key its row is found by): sentence `number` of source `src`, `chars`
        long, its text's `text_hash` (`plan_rules.text_hash_of`), its other new words `cowords` (keys) and set phrases
        `phrases`, the words `besides` the word it says, where the word `starts`; `over` *Never longer than*."""
        self.word.append(self._id(word))
        self.src.append(src)
        self.number.append(number)
        self.chars.append(chars)
        self.marks.append(OVER if over else 0)
        self.hash.append(text_hash & 0xFFFFFFFF)
        self.besides.append(min(besides, 255))
        self.starts.append(min(starts, STARTS_PAST))
        ids = [self._id(c) for c in cowords]
        self.ncow.append(len(ids))
        self.cow.extend(ids)
        self.nphr.append(len(phrases))
        self.phr.extend(phrases)

    def finish(self, keys, row_of, clauses_of, own_row, key_order, phrase_row, sources, head):
        """-> the Table. `keys`: every list row's (word, reading), by row · `row_of(word key)` -> its row or None
        (not a row: its lines are dropped) · `clauses_of(co-word key)` -> its formula (`plan_rules` clauses; TRUE:
        known from the start, left out) · `own_row(co-word key)` -> its own row or -1 · `key_order(co-word key)`:
        the order co-words are numbered in (the plan's `_coword_key`) · `phrase_row(phrase)` -> its row or None ·
        `sources`: [[rel, kind, digest]] · `head`: {engine, run_signature, language}."""
        from app import plan_rules
        n_ids = len(self._keys)
        rows = np.full(n_ids, -1, np.int64)
        for p, key in enumerate(self._keys):
            k = row_of(key)
            if k is not None and k >= 0:
                rows[p] = k
        word = _np(self.word, np.int64)
        line_row = rows[word] if len(word) else np.zeros(0, np.int64)
        keep = line_row >= 0
        src, number = _np(self.src, np.int64), _np(self.number, np.int64)
        # every line once for its row, in (row, file, place) order — a line the walk offered twice is kept once
        order = np.lexsort((number, src, line_row))
        order = order[keep[order]]
        if len(order):
            same = np.zeros(len(order), bool)
            same[1:] = ((line_row[order][1:] == line_row[order][:-1]) & (src[order][1:] == src[order][:-1])
                        & (number[order][1:] == number[order][:-1]))
            order = order[~same]

        # co-words: only those a kept line names, numbered by key; known from the start (TRUE) left out
        ncow, cow = _np(self.ncow, np.int64), _np(self.cow, np.int64)
        cow_line = np.repeat(np.arange(len(ncow), dtype=np.int64), ncow)
        used = np.zeros(n_ids, bool)
        used[cow[keep[cow_line]]] = True
        formulas, final = [], np.full(n_ids, -1, np.int64)
        named = sorted((key_order(self._keys[p]), p) for p in np.flatnonzero(used).tolist())
        for _order, p in named:
            clauses = clauses_of(self._keys[p])
            if clauses != plan_rules.TRUE:
                final[p] = len(formulas)
                formulas.append((own_row(self._keys[p]), clauses))
        cow_ids, cow_at = _regroup(ncow, final[cow] if len(cow) else cow, order)

        nphr, phr = _np(self.nphr, np.int64), _np(self.phr, np.int64)
        prow = {int(x): phrase_row(int(x)) for x in np.unique(phr).tolist()}
        mapped = np.fromiter(((-1 if prow[x] is None else prow[x]) for x in phr.tolist()), np.int64, len(phr))
        phr_ids, phr_at = _regroup(nphr, mapped, order)

        line_row = line_row[order]
        hashes = _np(self.hash, np.int64)[order]
        # the fingerprint: kept only where another line of the same word says the same words (never 0 then)
        if len(order):
            _u, inverse, counts = np.unique((line_row << 32) | hashes, return_inverse=True, return_counts=True)
            fp = np.where(counts[inverse] > 1, np.maximum(hashes, 1), 0)
        else:
            fp = hashes
        cols = {"src": src[order], "number": number[order],
                "chars": np.minimum(_np(self.chars, np.int64)[order], 0xFFFF), "marks": _np(self.marks, np.int64)[order],
                "ncow": np.diff(cow_at), "nphr": np.diff(phr_at), "fp": fp,
                "besides": _np(self.besides, np.int64)[order], "starts": _np(self.starts, np.int64)[order]}
        t = Table()
        with_lines, starts = np.unique(line_row, return_index=True)
        bounds = np.append(starts, len(line_row)).tolist()
        t.head = {"v": VERSION, "engine": head["engine"], "run_signature": head["run_signature"],
                  "language": head["language"], "keys": [[k[0], k[1]] for k in keys],
                  "rows": with_lines.tolist(), "lines": np.diff(bounds).tolist()}
        t._sources = [list(s) for s in sources]
        t._form = _pack_formulas(formulas)
        t._parts = {}
        for i, k in enumerate(t.head["rows"]):
            a, b = bounds[i], bounds[i + 1]
            ca, cb, pa, pb = int(cow_at[a]), int(cow_at[b]), int(phr_at[a]), int(phr_at[b])
            t._parts[k] = ({name: cols[name][a:b] for name, _t in COLUMNS}, cow_ids[ca:cb], phr_ids[pa:pb])
        return t


def _np(values, dtype):
    return np.frombuffer(values, dtype=values.typecode and np.dtype(values.typecode)).astype(dtype) \
        if len(values) else np.zeros(0, dtype)


def _regroup(counts, ids, order):
    """A flat list of per-line ids (`counts` a line), -1 dropped, each line's ids ascending, lines taken in `order`
    -> (the ids, each taken line's start among them, one more at the end)."""
    line = np.repeat(np.arange(len(counts), dtype=np.int64), counts)
    pos = np.full(len(counts), -1, np.int64)
    pos[order] = np.arange(len(order), dtype=np.int64)
    at = pos[line] if len(line) else line
    good = (ids >= 0) & (at >= 0)
    at, ids = at[good], ids[good]
    by = np.lexsort((ids, at))
    at, ids = at[by], ids[by]
    starts = np.concatenate(([0], np.cumsum(np.bincount(at, minlength=len(order)), dtype=np.int64)))
    return ids, starts


def _pack_formulas(formulas):
    """[(own row or -1, clauses of rows)] -> (own, clauses a co-word, rows a clause, the rows) as int32 arrays."""
    own = np.array([f[0] for f in formulas], "<i4")
    ncl = np.array([len(f[1]) for f in formulas], "<i4")
    cl_len = np.array([len(c) for f in formulas for c in f[1]], "<i4")
    cl_rows = np.array([r for f in formulas for c in f[1] for r in c], "<i4")
    return own, ncl, cl_len, cl_rows


def _zjson(value):
    return zlib.compress(json.dumps(value, separators=_SEP, ensure_ascii=False, sort_keys=True).encode("utf-8"), LEVEL)


class Table:
    """The table, made by `Packer.finish` or read by `open_table` (the head; blocks on demand)."""

    def __init__(self):
        self.head, self.path = None, None
        self._sources = self._form = None
        self._parts, self._blocks, self._at = {}, {}, None

    # ---- written by Generate ------------------------------------------------------------------------------- #
    def write(self, path):
        """Write the table whole through a temp file and `os.replace` -> its bytes. On any error the temp is removed,
        an older table stays as it was, and the error is raised for the caller to log."""
        blobs, cows, phrs = [], [], []
        for k in self.head["rows"]:
            cols, cow, phr = self._parts[k]
            src = cols["src"].astype(np.int64)
            step = src.copy()
            step[1:] -= src[:-1]
            data = [(step if name == "src" else cols[name]).astype(t).tobytes() for name, t in COLUMNS]
            blobs.append(zlib.compress(b"".join(data + [cow.astype("<i4").tobytes(), phr.astype("<i4").tobytes()]),
                                       LEVEL))
            cows.append(len(cow))
            phrs.append(len(phr))
        form = zlib.compress(b"".join(x.astype("<i4").tobytes() for x in self._form), LEVEL)
        head = _zjson(dict(self.head, cows=cows, phrs=phrs, sizes=[len(b) for b in blobs],
                           form=[len(x) for x in self._form]))
        sources = _zjson(self._sources)
        tmp = f"{path}.{os.getpid()}.tmp"
        try:
            with open(tmp, "wb") as f:
                f.write(MAGIC + struct.pack("<III", len(head), len(sources), len(form)))
                for part in (head, sources, form, *blobs):
                    f.write(part)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        return os.path.getsize(path)

    # ---- read ---------------------------------------------------------------------------------------------- #
    def sources(self):
        """[[rel, kind, digest]]: the plan's files, then the Finished ones."""
        if self._sources is None:
            with open(self.path, "rb") as f:
                f.seek(self._at[0])
                self._sources = json.loads(zlib.decompress(f.read(self._at[1])))
        return self._sources

    def formulas(self):
        """The co-words' formulas: (own row, clauses a co-word, rows a clause, the rows), int32 arrays."""
        if self._form is None:
            with open(self.path, "rb") as f:
                f.seek(self._at[0] + self._at[1])
                data = zlib.decompress(f.read(self._at[2]))
            out, at = [], 0
            for n in self.head["form"]:
                out.append(np.frombuffer(data, "<i4", n, at))
                at += 4 * n
            self._form = tuple(out)
        return self._form

    def block(self, row):
        """Row `row`'s lines: ({column: array}, its co-words' ids, its phrases' rows) — each line's co-words are the
        next `ncow` ids, its phrases the next `nphr` rows. None when the row has no line."""
        found = self._parts.get(row)
        if found is not None or row not in self._blocks:
            return found
        off, size, lines, cows, phrs = self._blocks[row]
        with open(self.path, "rb") as f:
            f.seek(off)
            data = zlib.decompress(f.read(size))
        if len(data) != lines * _BYTES + 4 * (cows + phrs):
            raise ValueError("a block of the wrong size")
        cols, at = {}, 0
        for name, t in COLUMNS:
            cols[name] = np.frombuffer(data, t, lines, at)
            at += lines * np.dtype(t).itemsize
        cols["src"] = np.cumsum(cols["src"], dtype=np.int64)
        cow = np.frombuffer(data, "<i4", cows, at)
        phr = np.frombuffer(data, "<i4", phrs, at + 4 * cows)
        return cols, cow, phr

    def rows(self):
        """{(word, reading): row} for the rows that have lines."""
        keys = self.head["keys"]
        return {(keys[k][0], keys[k][1]): k for k in self.head["rows"]}


def open_table(path, language=None, engine=None, run_signature=None):
    """The table at `path`, its head read (blocks on demand) — or None: no file, a damaged or half-written one,
    another format's version, or (when asked) another language, engine or run. Never raises."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if f.read(len(MAGIC)) != MAGIC:
                return None
            hl, sl, fl = struct.unpack("<III", f.read(12))
            head = json.loads(zlib.decompress(f.read(hl)))
        if head.get("v") != VERSION:
            return None
        for name, want in (("language", language), ("engine", engine), ("run_signature", run_signature)):
            if want is not None and head.get(name) != want:
                return None
        t = Table()
        t.head, t.path = head, path
        start = len(MAGIC) + 12 + hl
        t._at = (start, sl, fl)
        off = start + sl + fl
        for k, n, lines, cows, phrs in zip(head["rows"], head["sizes"], head["lines"], head["cows"], head["phrs"]):
            t._blocks[k] = (off, n, lines, cows, phrs)
            off += n
        if off != size or len(head["rows"]) != len(head["sizes"]):
            return None                         # half-written, or more than one table's bytes
        return t
    except (OSError, ValueError, KeyError, TypeError, struct.error, zlib.error):
        return None
