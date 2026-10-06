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
    eng.set_pins(pins)
    result = eng.result()

**Pure** (rule 3): the standard library and `app.plan_rules` only — no Qt, Tk, pandas or tokenizer, no settings, no
store, no Anki; the only I/O is reading the plan file it is given. The caller runs it on a worker.

**Exact** (05 §1): `result()` equals a full Generate of the same order on the plan columns. The analyzer and this
module share `plan_rules` — the spelling a row shows and the progressive pass are one implementation. `move` keeps the
live numbers (Score, counts, first places, *N new*, the priority order) up to date in place and equals `replan`
(05 §2); the progressive list and spelling ties are worked out again by `result()`.
"""
import bisect
import gzip
import json
import zlib
from array import array

from app import plan_rules

FORMAT = 1
TIERS = ("now", "soon", "goal")            # the analysed tiers, in the order a Generate reads them
_SLOT = {"now": 0, "soon": 1, "goal": 2}
_GAP = 1 << 40                             # room between two items' places: a move takes a place between its
                                           # neighbours, so 40 drags into one spot before every item is numbered again
_SHORT = 256                               # a word met in at most this many files finds its first file by looking
                                           # at each; a commoner one by walking the order (`move`)
ORDER_MODES = ("content", "priority")      # Junban's `junban_order_mode`: the progressive list, or the priority list


class PlanError(Exception):
    """The plan can't be used as it is: missing, damaged, another format, or the library it describes changed."""


# --------------------------------------------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------------------------------------------- #

class Plan:
    """A plan file read: `header` (dict), `files` [[rel_path, tier, digest], …], `keys` [[Word, Reading, is_phrase,
    half, Occurrences], …], `rows` (parallel to keys: [Tier, phrase Tier, Modality, Sources, Orth, Forms, [Context 1,
    Src 1, …]] or None), `ties` [[k, {orth: n}, {surface: n}, {orth: Tier} | None], …] and `per_file` (one dict per
    file, in the run's order: "main", "ph", "sp", "prog")."""

    __slots__ = ("header", "files", "keys", "rows", "ties", "per_file")

    def __init__(self, header, files, keys, rows, ties, per_file):
        self.header, self.files, self.keys, self.rows, self.ties, self.per_file = \
            header, files, keys, rows, ties, per_file


def load(path):
    """The plan file at `path`, checked whole. The file is read in one go and closed before anything is decoded, so a
    Generate replacing it never waits on this reader (Windows refuses to replace a file someone holds open). Raises
    PlanError: missing, unreadable, damaged (gzip CRC, a line that isn't JSON), another format, or tables that don't
    fit together."""
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
    try:
        decoded = [json.loads(line) for line in lines]
    except ValueError:
        raise PlanError("the plan file is damaged (a line isn't JSON)") from None
    if not decoded or not isinstance(decoded[0], dict):
        raise PlanError("the plan file has no header")
    header = decoded[0]
    if header.get("format") != FORMAT:
        raise PlanError(f"the plan file's format is {header.get('format')!r}, not {FORMAT}")
    tables = {"files": [], "keys": [], "rows": [], "ties": []}
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
    plan = Plan(header, tables["files"], tables["keys"], tables["rows"], tables["ties"], per_file)
    _validate(plan)
    return plan


def _validate(plan):
    """Every value the engine reads, checked by type and range, every table against the header: a damaged or
    hand-edited plan is refused whole with a PlanError, never half-used and never a crash later (a TypeError in
    `result()` on a worker). `format` 1 as `analyzer.plan_lines` writes it (01 §7)."""
    h = plan.header
    for name, kinds in (("language", str), ("engine", str), ("run_signature", str), ("order_free_signature", str),
                        ("weights", dict), ("files", int), ("keys", int), ("shared_phrases", list)):
        if not isinstance(h.get(name), kinds):
            raise PlanError(f"the plan file's header has no {name!r}")
    for name, kinds in (("store", (dict, type(None))), ("max_contexts", int), ("order_free_parts", dict),
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
        if not (isinstance(entry, list) and len(entry) in (2, 3) and isinstance(entry[0], str)
                and isinstance(entry[1], str) and entry[1] in _SLOT and (len(entry) == 2 or isinstance(entry[2], str))):
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
    uses = [0] * n_keys
    phrase = [key[2] for key in plan.keys]
    for line in plan.per_file:
        for table, is_phrase in (("main", False), ("ph", True)):
            pairs = line.get(table)
            if not isinstance(pairs, list) or len(pairs) % 2:
                raise PlanError("a file's uses are damaged")
            met = set()
            for i in range(0, len(pairs), 2):
                k, u = pairs[i], pairs[i + 1]
                # A use is counted (the writer's records start at 1): a 0 would give a file where nothing counted a
                # word's first place (02 §2.3).
                if not (_index(k, n_keys) and type(u) is int and u > 0) or k in met:
                    raise PlanError("a file's uses are damaged")
                met.add(k)
                if phrase[k] != is_phrase:
                    # A word counted as a phrase's own uses, or the reverse: the insertion order a Generate keeps
                    # (words first, then phrases) couldn't be told from the plan.
                    raise PlanError("a file's uses mix a word and a phrase row")
                uses[k] += u
        sps = line.get("sp", [])
        if not isinstance(sps, list) or not all(
                isinstance(sp, list) and len(sp) == 3 and _index(sp[0], n_keys) and _strings(sp[1])
                and _strings(sp[2]) for sp in sps):
            raise PlanError("a file's spellings are damaged")
        prog = line.get("prog")
        if not (isinstance(prog, list) and len(prog) == 7 and type(prog[0]) is int and type(prog[1]) is int
                and 0 <= prog[1] <= prog[0]):
            raise PlanError("a file's progressive record is damaged")
        for table in (prog[2], prog[3], prog[4], prog[5]):
            if not isinstance(table, list) or len(table) % 2 or not all(
                    _index(table[i], n_keys) and type(table[i + 1]) is int for i in range(0, len(table), 2)):
                raise PlanError("a file's progressive record is damaged")
        if not isinstance(prog[6], list) or not all(
                isinstance(sib, list) and len(sib) == 2 and isinstance(sib[0], str) and type(sib[1]) is int
                for sib in prog[6]):
            raise PlanError("a file's progressive record is damaged")
    if uses != [key[4] for key in plan.keys]:
        raise PlanError("the plan file's uses don't add up to its words' Occurrences")


def _index(value, n):
    return type(value) is int and 0 <= value < n


def _number(value):
    return type(value) in (int, float)


def _strings(value):
    return isinstance(value, list) and all(isinstance(x, str) for x in value)


def _counts(value):
    return isinstance(value, dict) and all(type(n) is int for n in value.values())


# --------------------------------------------------------------------------------------------------------------- #
# Is the plan still the library's?
# --------------------------------------------------------------------------------------------------------------- #

def check(plan, language, engine, run_stamp, signature_parts, epoch=None):
    """Whether `plan` describes the library as it stands (01 §1, 04 §4). `engine`: the running app's
    `"<version>|schema<SCHEMA_VERSION>|rev<ENGINE_REVISION>"`; `run_stamp`: `analyzer.read_run_stamp(results)`;
    `signature_parts`: `analyzer.run_signature_parts(...)` for the library now (the caller computes it on its worker);
    `epoch`: the store's (None: not checked). Returns

      None                        the plan is the library's: re-plan any order of it;
      ("replan-now", parts)       only the known words ("known"), the word lists ("lists") or files that left the
                                  counted tiers ("files-removed") moved: re-plan now from the plan, then Generate;
      ("generate-first", reason)  anything else — another language, another app version, a run that didn't finish,
                                  files added or changed, a setting: a Generate first;
      ("stand-aside", reason)     the plan is current but the engine can't replay it exactly: coverage mode
                                  ("coverage"), i+1 mode ("i+1"), a row two set phrases share ("shared-phrase") or a
                                  weight that isn't a whole number ("weights") — the preview stands aside (D7)."""
    h = plan.header
    if h.get("language") != language:
        return ("generate-first", "language")
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
    now = plan_rules.signature_digest(signature_parts, order_free=True)
    if now is None:
        return ("generate-first", "signature")                    # the parts can't be read: never "current"
    if now != h["order_free_signature"]:
        verdict = _what_moved(plan, signature_parts)
        if verdict[0] == "generate-first":
            return verdict
    aside = stands_aside(plan)
    return ("stand-aside", aside) if aside else verdict


def stands_aside(plan):
    """Why the engine can't replay `plan` exactly, or None (check's "stand-aside" reasons)."""
    h = plan.header
    if h.get("target_coverage"):
        return "coverage"
    if h.get("only_i_plus_one"):
        return "i+1"
    if h.get("shared_phrases"):
        return "shared-phrase"
    if not all(type(w) is int for w in h["weights"].values()):
        return "weights"
    return None


def _what_moved(plan, parts):
    kept = plan.header.get("order_free_parts")
    if not isinstance(kept, dict):
        return ("generate-first", "signature")
    try:
        now = plan_rules.part_digests(parts)
    except Exception:
        return ("generate-first", "signature")
    moved = sorted(name for name in set(kept) | set(now) if kept.get(name) != now.get(name))
    replan = []
    for name in moved:
        if name in ("known", "lists"):
            replan.append(name)
        elif name == "files" and _only_removed(plan, parts):
            replan.append("files-removed")
        else:
            return ("generate-first", name)
    if not replan:
        return ("generate-first", "signature")                     # the whole moved but no part: not ours to guess
    return ("replan-now", tuple(replan))


def _only_removed(plan, parts):
    """True when every file the library counts now is one the plan holds, unchanged, and some plan file is gone."""
    held = {entry[2] for entry in plan.files if len(entry) > 2}
    if len(held) != len(plan.files):
        return False                                              # a plan from before the per-file digests
    try:
        now = {plan_rules.file_digest(entry) for entry in parts["files"]}
    except Exception:
        return False
    return now < held


# --------------------------------------------------------------------------------------------------------------- #
# The engine
# --------------------------------------------------------------------------------------------------------------- #

class Result:
    """One order's columns (02 §1). Keys are (Word, Reading), as every output names a row.

    `priority`, `progressive`: the two lists' rows, in order, as dicts shaped like the CSVs' (the columns a re-plan
    computes, and the order-free ones as the plan keeps them); `first`: key -> the item where the word is first met;
    `n_new`: item -> how many words are first met there; `score`, `counts` (High, Low, Goal): key -> numbers;
    `sequence`: item -> its place (1 = the first item of NOW); `pinned`: the pinned items, in groups, oldest pin
    first (02 §7); `dropped`: plan items not in the order (02 §6)."""

    __slots__ = ("priority", "progressive", "first", "n_new", "score", "counts", "sequence", "pinned", "dropped")

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
    the store no longer holds); by default its rel_path."""

    def __init__(self, plan, ids=None):
        aside = stands_aside(plan)
        if aside:
            raise PlanError(f"the engine stands aside: {aside}")
        # The engine keeps what it reads, not the plan's per-file lines (most of a loaded plan's memory): once the
        # caller lets its plan go, only the tables below stay.
        self.plan = Plan(plan.header, plan.files, plan.keys, plan.rows, plan.ties, None)
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
        self._occ = [key[4] for key in keys]
        # Per file: its keys and uses (words, then the phrase rows' own entries) — a Generate's insertion order: files
        # in the order, each file's words as first counted, phrases after words. A key's place in `ks` is its place
        # in that order within the file (words before phrases, as the rank needs).
        self._uses = []
        files_of = [[] for _ in range(n)]
        for f, line in enumerate(plan.per_file):
            ks, us = array("i"), array("i")
            for table in (line["main"], line["ph"]):
                ks.extend(table[0::2])
                us.extend(table[1::2])
            for k in ks:
                files_of[k].append(f)
            self._uses.append((ks, us))
        self._files_of = [array("i", fs) for fs in files_of]
        self._prog = [self._prog_file(line) for line in plan.per_file]   # the progressive pass's input
        self._ties = {tie[0]: tie for tie in plan.ties}
        self._sp = {}
        for f, line in enumerate(plan.per_file):
            if line.get("sp"):
                self._sp[f] = {sp[0]: (sp[1], sp[2]) for sp in line["sp"]}
        self._pins = []
        self.renumbered = 0                  # how many times a move found no room and spaced every item afresh
        self._numbers([(ids[f], entry[1]) for f, entry in enumerate(files) if ids[f] is not None])

    # ----------------------------------------------------------------------------------------------------------- #
    # From scratch (02 §2): the referee
    # ----------------------------------------------------------------------------------------------------------- #

    def replan(self, order, pins=None):
        """The order's live numbers from scratch. `order`: [(item_id, tier)] — the analysed tiers' items, NOW then
        Soon then 6+ Months, each in the store's order. An item the plan doesn't hold is a PlanError (the library
        changed: Generate first); a plan item not in `order` is dropped (it left the counted tiers, 02 §6: the
        remaining words' places are right, the list's membership waits for the next Generate)."""
        self._numbers(order)
        if pins is not None:
            self.set_pins(pins)
        return self.result()

    def _numbers(self, order):
        """The live numbers from scratch for `order` (replan's checks and work, without the result)."""
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
        n_files = len(self._uses)
        self._order = fs
        self._tier = [None] * n_files
        self._pos = [None] * n_files
        for i, (f, slot) in enumerate(zip(fs, tiers)):
            self._tier[f] = slot
            self._pos[f] = (i + 1) * _GAP
        self._tier_count = [tiers.count(s) for s in range(3)]

        n = self._n
        raw = [0] * n
        counts = [[0, 0, 0] for _ in range(n)]
        first = [None] * n
        w = self._w
        uses = self._uses
        for f, slot in zip(fs, tiers):
            weight = w[slot]
            ks, us = uses[f]
            for k, u in zip(ks, us):
                raw[k] += weight * u
                counts[k][slot] += u
                if first[k] is None:
                    first[k] = f
        self._raw, self._counts, self._first = raw, counts, first
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
        f = self._first[k]
        return (-self._score(k), self._pos[f], self._phrase[k], self._uses[f][0].index(k), k)

    # ----------------------------------------------------------------------------------------------------------- #
    # Incremental (02 §3)
    # ----------------------------------------------------------------------------------------------------------- #

    def move(self, item_ids, tier, before_id=None, after_id=None):
        """Place a block of items as `Store.move` does: in their current relative order, contiguous before or after
        the anchor (neither: the top of `tier`). `item_ids`: one id, or any collection of ids. Returns (the words
        whose Score, tier counts or first item changed, as (Word, Reading); the items moved). Only the block
        re-weights and only its words can change first place; the others keep theirs (a move pushes no other item
        across a line, RP-2)."""
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
        order = [f for f in old if f not in block_set]
        for f in block:
            self._tier_count[self._tier[f]] -= 1
        at = sum(self._tier_count[:slot]) if anchor is None else order.index(a) + (1 if before_id is None else 0)
        order[at:at] = block
        self._order = order
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
                self._n_new[was] -= 1
                self._n_new[new] += 1
                self._first[k] = new
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
            else:
                walk.add(k)
        if walk:
            found = {}
            if walk_from is not None:
                order, uses = self._order, self._uses
                for g in order[order.index(walk_from):]:
                    if g in block_set:
                        continue
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

    def result(self):
        """The order's columns (02 §1): the live numbers as kept, the priority rows in rank order, and the progressive
        list and spelling ties worked out again for this order."""
        plan, keys, rows = self.plan, self.plan.keys, self.plan.rows
        order = self._order
        seq_of = {f: i for i, f in enumerate(order, 1)}
        spelled = self._spellings(order)
        spelling = self._spelling
        score = [self._score(k) for k in range(self._n)]
        counts = self._counts
        n_contexts = plan.header.get("max_contexts") or 0

        priority = []
        for r in self._ranked:
            k = r[-1]
            orth, forms, tier = spelling(k, spelled)
            row = rows[k]
            out = {"Word": keys[k][0], "Reading": keys[k][1], "Orth": orth, "Forms": forms, "Tier": tier,
                   "Score": score[k], "Occurrences": keys[k][4], "Count (High)": counts[k][0],
                   "Count (Low)": counts[k][1], "Count (Goal)": counts[k][2], "Sources": row[3], "Modality": row[2]}
            _contexts(out, row[6], n_contexts)
            priority.append(out)

        progressive = []
        rank = (lambda k: (score[k], self._occ[k]))
        passes = plan_rules.progressive_pass((self._prog[f] for f in order), set(), set(),
                                             self._lemma.__getitem__, self._listed.__getitem__, rank)
        for (f, (file_rows, baseline_pct, total)) in zip(order, passes):
            seq = seq_of[f]
            source = plan.files[f][0].rsplit("/", 1)[-1]
            for k, count, known_count, start_pct, end_pct in file_rows:
                orth, forms, _tier = spelling(k, spelled)
                row = rows[k]
                out = {"Sequence": seq, "Source File": source, "Word": keys[k][0], "Orth": orth, "Forms": forms,
                       "Reading": keys[k][1], "Tier": row[1] or row[0], "Score": score[k],
                       "Occurrences (Global)": keys[k][4], "Occurrences (File)": count, "Count (High)": counts[k][0],
                       "Count (Low)": counts[k][1], "Count (Goal)": counts[k][2], "Modality": row[2]}
                _contexts(out, row[6], n_contexts)
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
            dropped=[ids[f] for f in range(len(ids)) if ids[f] is not None and self._pos[f] is None])

    @staticmethod
    def _prog_file(line):
        """A file's line of the progressive pass (`plan_rules.progressive_pass`) from its plan record (01 §7): the
        tokens with the uses a phrase took beside each (one compact array), siblings, credits and phrase uses as
        pairs."""
        total, baseline, tokens, given, credits, phrases, siblings = line["prog"]
        given = dict(zip(given[::2], given[1::2]))
        flat = array("i")
        for i in range(0, len(tokens), 2):
            k = tokens[i]
            flat.extend((k, tokens[i + 1], given.get(k, 0)))
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


def _contexts(out, kept, n):
    """The Context / Src columns as the last Generate wrote them (not re-planned, D1)."""
    for i in range(n):
        out[f"Context {i + 1}"] = kept[2 * i] if 2 * i < len(kept) else ""
        out[f"Src {i + 1}"] = kept[2 * i + 1] if 2 * i + 1 < len(kept) else ""
