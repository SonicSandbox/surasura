"""The suite's machinery: the evaluator registry, the run context, the determinism pins, and `evaluate`.

Both modes use it the same way — the guard (test_parsing_suite.py, one pytest test per case) and the scorecard
(scorecard.py, every case in one run):

    load_evaluators()                         # evaluators.py + every evaluators_<area>.py
    ctx = Context(scratch_folder)             # one per run
    result = evaluate(case, ctx)              # Result(observed, verdict, problems), under the pins

An evaluator is `run(case, ctx) -> observed` (JSON-serializable: what the app does, never a judgement) registered
for a layer with `@evaluator(layer, expects=...)`; its `compare(observed, expect)` lists the problems — none is a
pass. docs/agent instructions/Parsing_Suite.md has the whole contract.
"""
import contextlib
import copy
import csv
import importlib
import io
import json
import os
import pkgutil
import subprocess
import sys
from collections import namedtuple
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import analyzer, anki_match, names, settings_manager, token_index  # noqa: E402

DATA = os.path.join(HERE, "data")               # frozen snapshots of the user's data (snapshot.py)
BASELINES = os.path.join(HERE, "baselines")     # the scorecard's runs

# The settings every case runs under: data/<this>/settings.json, the tracked settings.json as it was on that day.
# Never the live file — a settings edit must not move the suite. Moving it on is deliberate: take a snapshot
# (snapshot.py), point this at it, and read the scorecard's diff.
SETTINGS_SNAPSHOT = "2026-09-26"
# The library's name tables every Japanese case runs under (app/names.py: names that recur in the library, kanji names
# with a library floor): data/names/library_tables.json, written by data/names/library_names.py from the user's library
# through the app's own code. Frozen, like the settings: a library change must not move the suite.
NAMES_TABLES = os.path.join(DATA, "names", "library_tables.json")


# --- the registry --------------------------------------------------------------------------------------------- #
Evaluator = namedtuple("Evaluator", "layer run expects compare show")
EVALUATORS = {}


def evaluator(layer, expects, compare=None, show=None):
    """Register `run(case, ctx) -> observed` as the judge of `layer`.

    `expects` names the expectation keys the layer reads — the guard rejects a case using any other, so a typo
    can't pass silently. `compare(observed, expect) -> [problem, ...]` (default `compare_keys`: each expected key
    equals the observed one); `show(observed) -> str` is the one line the guard and the scorecard print (default:
    JSON)."""
    def register(run):
        held = EVALUATORS.get(layer)
        if held and (held.run.__module__, held.run.__qualname__) != (run.__module__, run.__qualname__):
            raise ValueError(f"layer {layer!r} is already judged by {held.run.__module__}.{held.run.__qualname__}")
        EVALUATORS[layer] = Evaluator(layer, run, tuple(expects), compare or compare_keys, show or show_json)
        return run
    return register


def load_evaluators():
    """Import evaluators.py and every evaluators_<area>.py beside it (each registers its layers)."""
    importlib.import_module("tests.parsing.evaluators")
    for info in sorted(pkgutil.iter_modules([HERE]), key=lambda info: info.name):
        if info.name.startswith("evaluators_"):
            importlib.import_module(f"tests.parsing.{info.name}")
    return EVALUATORS


_ABSENT = "(absent)"


def short(value, width=160):
    """`value` as one line of JSON, cut to `width` characters."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= width else text[:width - 1] + "…"


def show_json(observed):
    return json.dumps(observed, ensure_ascii=False, sort_keys=True)


def compare_keys(observed, expect):
    """The default comparison: every expected key equals the observed value of that name."""
    def quoted(value):
        return short(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return [f"{key}: expected {quoted(want)}, got {quoted(observed.get(key, _ABSENT))}"
            for key, want in expect.items() if observed.get(key, _ABSENT) != want]


def compare_members(problems, name, have, expect, present_key, absent_key):
    """Membership expectations: every item of expect[present_key] is in `have`, none of expect[absent_key] is."""
    missing = [item for item in expect.get(present_key, ()) if item not in have]
    if missing:
        problems.append(f"{present_key}: {short(missing)} not among the {name} {short(sorted(have))}")
    extra = [item for item in expect.get(absent_key, ()) if item in have]
    if extra:
        problems.append(f"{absent_key}: {short(extra)} found among the {name}")
    return problems


def key(lemma, reading):
    """A word's key, 'lemma|reading' — the analyzer's own (token_index.make_key; library_frequency.json's keys)."""
    return token_index.make_key(lemma, reading)


def split_key(text):
    """'lemma|reading' -> (lemma, reading); a bare 'lemma' has the reading "" (Chinese words, lemma-only checks)."""
    lemma, _, reading = str(text).partition("|")
    return lemma, reading


# --- evaluating a case ----------------------------------------------------------------------------------------- #
Result = namedtuple("Result", "observed verdict problems")


class Skip(Exception):
    """Raised by an evaluator when the case can't be judged on this machine as it stands — the reason in plain words
    (the installed パターン databases it reads predate the code's builder, which refuses them). Never for a wrong
    answer: the guard skips the case with the reason, the scorecard records it as "skip", and once the cause is gone
    (the databases rebuilt) the case runs again by itself."""


def evaluate(case, ctx, catch=False):
    """Run `case` through its layer under the pins -> Result(observed, verdict, problems); verdict "pass" when
    `compare` finds no problem, else "fail" — or "skip" when the evaluator can't judge it here (`Skip`: observed
    {"skipped": reason}, in either mode). With `catch` (the scorecard) an exception is recorded as verdict "error";
    without it (the guard) it propagates, so a broken case never passes for an expected failure."""
    try:
        judge = EVALUATORS.get(case.layer)
        if judge is None:
            raise KeyError(f"no evaluator for layer {case.layer!r} (load_evaluators(); evaluators_<area>.py)")
        with pinned(case), quiet():
            observed = judge.run(case, ctx)
        json.dumps(observed, ensure_ascii=False)        # a baseline must be able to hold it (TypeError if not)
        problems = list(judge.compare(observed, case.expect))
    except Skip as skip:
        return Result({"skipped": str(skip)}, "skip", [str(skip)])
    except Exception as exc:
        if not catch:
            raise
        message = f"{type(exc).__name__}: {exc}"
        return Result({"error": message}, "error", [message])
    return Result(observed, "fail" if problems else "pass", problems)


@contextlib.contextmanager
def quiet():
    """The app prints progress (load_known_words, the Chinese tokenizer's configuration); a case's output is its
    observed value, not that."""
    with contextlib.redirect_stdout(io.StringIO()):
        yield


@contextlib.contextmanager
def patched(owner, name, value):
    """`owner.name` replaced by `value` for the duration, then put back. Patch where the app LOOKS IT UP:
    `analyzer.join_affixes` reaches every caller that reads it off the module at call time (the tokenizer,
    see_through_base, sentence_corpus, the パターン builder) — a `from ... import` taken at import time is not."""
    old = getattr(owner, name)
    setattr(owner, name, value)
    try:
        yield
    finally:
        setattr(owner, name, old)


class Token:
    """A token shaped like a fugashi node (`surface`, `feature`, `is_unk`), for code that rebuilds a line's
    tokens — a variant's post-process, the tokens_ja evaluator. A fugashi node is only valid until the tagger's
    next call; a Token is a copy. A token made of several joins with `analyzer._joined` (a JoinedWord) instead."""
    __slots__ = ("surface", "feature", "is_unk")

    def __init__(self, surface, feature, is_unk=False):
        self.surface, self.feature, self.is_unk = surface, feature, is_unk


# --- determinism ----------------------------------------------------------------------------------------------- #
_LOGIC = None
_NAMES = []


def frozen_names():
    """The library's name tables as frozen (NAMES_TABLES) — read once."""
    if not _NAMES:
        if not os.path.isfile(NAMES_TABLES):
            raise FileNotFoundError(f"the frozen name tables {NAMES_TABLES} are missing — "
                                    "python tests/parsing/data/names/library_names.py --repo <repo>")
        with open(NAMES_TABLES, encoding="utf-8") as handle:
            _NAMES.append(json.load(handle)["tables"])
    return _NAMES[0]


def frozen_logic():
    """The analyzer's LOGIC as the frozen settings.json gives it, merged by the app's own settings_manager (the
    logic block is deep-merged over its defaults, which carry every key the analyzer's defaults do — so this IS
    what `LOGIC.update(load_settings()["logic"])` makes at import)."""
    global _LOGIC
    if _LOGIC is None:
        path = os.path.join(DATA, SETTINGS_SNAPSHOT, "settings.json")
        if not os.path.isfile(path):
            raise FileNotFoundError(f"the frozen settings {path} are missing — python tests/parsing/snapshot.py")
        with mock.patch.object(settings_manager, "get_settings_path", lambda: path), quiet():
            _LOGIC = settings_manager.load_settings().get("logic", {})
    return copy.deepcopy(_LOGIC)


@contextlib.contextmanager
def pinned(case):
    """The process-wide state a parse depends on, set as a run of the case's language sets it, and put back:
    SANITIZE_JA (every Japanese run sanitizes lemmas, a Chinese one doesn't), SKIP_SINGLE_CHARS (the default:
    skipped), LOGIC (the frozen settings — sentence boundaries included), the library's name tables (frozen, for
    Japanese; none for Chinese), Ignore names off as the frozen settings have it (token_index.ignored_names reads the
    live settings.json and the live token store — never here: a case switches it on with ctx["ignore_names"],
    `Context.known_sets`) and, for Chinese, jieba's reinforce tuning (case.ctx["reinforce"]). Nothing a case does
    leaks into the next case or into any other test."""
    saved = (analyzer.SANITIZE_JA, analyzer.SKIP_SINGLE_CHARS, copy.deepcopy(analyzer.LOGIC), dict(names._library),
             token_index.ignored_names)
    analyzer.SANITIZE_JA = case.lang == "ja"
    analyzer.SKIP_SINGLE_CHARS = True
    analyzer.LOGIC.clear()
    analyzer.LOGIC.update(frozen_logic())
    names.use_library_tables(frozen_names() if case.lang == "ja" else None, pin=True)
    token_index.ignored_names = lambda language: []
    try:
        if case.lang == "zh":
            with jieba_reinforce(bool(case.ctx.get("reinforce"))):
                yield
        else:
            yield
    finally:
        analyzer.SANITIZE_JA, analyzer.SKIP_SINGLE_CHARS = saved[0], saved[1]
        analyzer.LOGIC.clear()
        analyzer.LOGIC.update(saved[2])
        names._library.clear()
        names._library.update(saved[3])
        token_index.ignored_names = saved[4]


_REINFORCED = None


def _reinforced_words():
    """The words ChineseTokenizer(reinforce_segmentation=True) tunes, read off the app rather than copied: its
    jieba.suggest_freq calls are recorded — and not made — while the constructor runs."""
    global _REINFORCED
    if _REINFORCED is None:
        import jieba
        words = []

        def record(segment, tune=False):
            words.append(segment if isinstance(segment, str) else "".join(segment))
            return 0
        with mock.patch.object(jieba, "suggest_freq", record), quiet():
            analyzer.ChineseTokenizer(reinforce_segmentation=True)
        _REINFORCED = tuple(words)
    return _REINFORCED


@contextlib.contextmanager
def jieba_reinforce(on):
    """jieba with the app's reinforce tuning on or off for the duration, then exactly as it was before.

    The tuning is process-wide and one-way (ChineseTokenizer: "we can't easily undo suggest_freq"), so the first
    test to switch it on decided every later Chinese result. Its whole effect is on the tuned words: jieba's
    frequency entry for each (0 — none is a jieba dictionary word, and a 0 entry only marks a prefix) and its
    force-split set, which is what splits them. Off = not force-split; on = the app's own tuning; afterwards the
    entries, the total and the set are restored."""
    import jieba
    from jieba import finalseg
    with quiet():
        jieba.initialize()
    words = _reinforced_words()
    table = jieba.dt.FREQ
    prefixes = {word[:end] for word in words for end in range(1, len(word) + 1)}
    saved = ({piece: table[piece] for piece in prefixes if piece in table}, jieba.dt.total,
             {word for word in words if word in finalseg.Force_Split_Words})
    try:
        if on:
            with quiet():
                analyzer.ChineseTokenizer(reinforce_segmentation=True)
        else:
            finalseg.Force_Split_Words.difference_update(words)
        yield
    finally:
        for piece in prefixes:
            if piece in saved[0]:
                table[piece] = saved[0][piece]
            else:
                table.pop(piece, None)
        jieba.dt.total = saved[1]
        finalseg.Force_Split_Words.difference_update(words)
        finalseg.Force_Split_Words.update(saved[2])


# --- the run context --------------------------------------------------------------------------------------------- #
class Context:
    """What the cases of one run share: one fugashi tagger (in one JapaneseTokenizer), one ChineseTokenizer per
    script, a scratch folder for the files a case needs — never under User Files/, data/, results/ or %APPDATA% —
    and the frozen snapshots, each read once. One per pytest session (conftest.py), one per scorecard run (made
    inside its variant, so nothing it caches predates the variant)."""

    def __init__(self, scratch):
        self.scratch = scratch
        self._memo = {}
        self._files = 0

    def memo(self, name, make):
        """`make()`, once per run for `name` — for anything expensive an evaluator reads (a list, a database)."""
        if name not in self._memo:
            self._memo[name] = make()
        return self._memo[name]

    def script(self, case):
        """The case's Chinese script setting (ctx["script"]: asis | s | t); Japanese is always as-is."""
        return case.ctx.get("script", "asis") if case.lang == "zh" else "asis"

    def tokenizer(self, lang, script="asis"):
        """The app's tokenizer for `lang` — the same object for the whole run (reinforce is jieba's, pinned)."""
        if lang == "ja":
            return self.memo(("tokenizer", "ja"), analyzer.JapaneseTokenizer)
        return self.memo(("tokenizer", "zh", script), lambda: analyzer.ChineseTokenizer(script=script))

    def write(self, name, data):
        """A scratch file called `name` holding `data` (bytes as given; str as UTF-8) — in a folder of its own, so
        a case's file name is exactly its own. Returns the path."""
        self._files += 1
        folder = os.path.join(self.scratch, f"{self._files:05d}")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        with open(path, "wb") as handle:
            handle.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path

    def snapshot(self, case, name):
        """The path of `name` in the snapshot the case names (ctx["snapshot"]), in its language's folder — None
        when it names none. Snapshots are copies (snapshot.py); nothing here reads the live user files."""
        snap = case.ctx.get("snapshot")
        if not snap:
            return None
        folder = os.path.join(DATA, snap)
        if not os.path.isdir(folder):
            raise FileNotFoundError(f"snapshot {snap!r} is not in {DATA} — python tests/parsing/snapshot.py")
        return os.path.join(folder, case.lang, name)

    def load_known(self, case, entries):
        """(known_tuples, known_lemmas) — analyzer.load_known_words over a KnownWord.json holding `entries` (a
        dictForm string is a KNOWN entry; a dict is a whole entry), with the case's language's tokenizer."""
        words = [{"dictForm": entry, "knownStatus": "KNOWN"} if isinstance(entry, str) else entry
                 for entry in entries]
        path = self.write("KnownWord.json", json.dumps({"words": words}, ensure_ascii=False))
        return analyzer.load_known_words(path, self.tokenizer(case.lang, self.script(case)))

    def known_sets(self, case, extra=()):
        """(known_tuples, known_lemmas, ignore) as a run of the case's language holds them: the snapshot's
        KnownWord.json and its ignore, black and graduated lists (ctx["snapshot"]), plus the case's own entries
        (ctx["known"] and `extra`) and ignore lines (ctx["ignore"]: lines, or a whole file's text) — each read by
        the app's own loaders — and, with ctx["ignore_names"] (Settings' Ignore names), the case's names
        (`case_names`)."""
        script = self.script(case)
        tuples, lemmas, ignore = set(), set(), set()
        if case.ctx.get("snapshot"):
            held = self.memo(("known", case.ctx["snapshot"], case.lang, script),
                             lambda: self._snapshot_known(case, script))
            tuples |= held[0]
            lemmas |= held[1]
            ignore |= held[2]
        entries = list(case.ctx.get("known", ())) + list(extra)
        if entries:
            more = self.load_known(case, entries)
            tuples |= more[0]
            lemmas |= more[1]
        lines = case.ctx.get("ignore")
        if lines:
            content = lines if isinstance(lines, str) else "\n".join(lines) + "\n"
            ignore |= analyzer.load_simple_list(self.write("IgnoreList.txt", content), script)
        if case.ctx.get("ignore_names") and case.lang == "ja":
            ignore |= self.case_names(case)
        return tuples, lemmas, ignore

    def case_names(self, case):
        """The names Ignore names ignores for the case, as a run reads them (token_index.ignored_names): what the
        token store records of a library holding the case's text, its ctx "sentence" and "documents" — each read
        as the store reads a file (app/names.py Record) — and the frozen library tables' kanji names, through
        names.name_words."""
        import re
        texts = [case.text, case.ctx.get("sentence") or ""] + list(case.ctx.get("documents") or ())
        record = names.Record()
        tokenizer = self.memo(("tokenizer", "ja", "store"), lambda: analyzer.JapaneseTokenizer(library=False))
        for text in texts:
            for _sentence in tokenizer.tokenize_sentences(re.sub(r"<[^>]*>", "", str(text)), names=record):
                pass
        return set(names.name_words([record.data()], frozen_names(), analyzer._sanitize_term))

    def _snapshot_known(self, case, script):
        tuples, lemmas = analyzer.load_known_words(self.snapshot(case, "KnownWord.json"),
                                                   self.tokenizer(case.lang, script))
        ignore = set()
        for name in ("IgnoreList.txt", "Blacklist.txt", "GraduatedList.txt"):
            ignore |= analyzer.load_simple_list(self.snapshot(case, name), script)
        # KnownWord.json's IGNORED entries, as a run reads them (IGNORED-ENTRIES, decided 2026-09-29).
        ignore |= analyzer.load_ignored_entries(os.path.dirname(self.snapshot(case, "KnownWord.json")), script, case.lang)
        return frozenset(tuples), frozenset(lemmas), frozenset(ignore)

    def rank_of(self, case):
        """The list a card is matched against, indexed by `anki_match.build_index` (Orth, Word, Forms, the kana
        fold, the one-character rule): ctx["list"] — words, or rows with Word / Orth / Forms — else the snapshot's
        list (ctx["list_file"]: "priority", the default, or "progressive", Junban's order), else no list."""
        return self.index(case).rank_of

    def index(self, case):
        """`rank_of`'s whole `anki_match.Index` — its `words` and `orths` too, each row's own word and spelling
        (card_key reads them)."""
        rows = case.ctx.get("list")
        if rows is not None:
            return anki_match.build_index(self.write("list.csv", _list_csv(rows)), language=case.lang)
        path = self.snapshot(case, f"{case.ctx.get('list_file', 'priority')}_learning_list.csv")
        if path is None:
            return anki_match.Index({}, {}, {}, {})
        return self.memo(("index", path, case.lang), lambda: anki_match.build_index(path, language=case.lang))

    def answers(self, case):
        """The user's answers to "Same word as one on your list?": ctx["answers"] ({card word: {"target",
        "answer"}}), else the snapshot's junban_pairs.json, else none."""
        if "answers" in case.ctx:
            return case.ctx["answers"]
        path = self.snapshot(case, "junban_pairs.json")
        if path is None:
            return {}
        return self.memo(("answers", path), lambda: _read_pairs(path))


def _list_csv(rows):
    """A list file the way the analyzer writes one (UTF-8 with a BOM) from words or Word / Orth / Forms rows."""
    rows = [{"Word": row} if isinstance(row, str) else dict(row) for row in rows]
    columns = ["Word", "Orth", "Forms"] + sorted({name for row in rows for name in row} - {"Word", "Orth", "Forms"})
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode("utf-8-sig")


def _read_pairs(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle).get("pairs") or {}
    except (OSError, ValueError, AttributeError):
        return {}


def git_state():
    """{"rev", "dirty"} of the working tree — dirty means a TRACKED file differs from HEAD (tests/parsing/ and
    modules/ are gitignored, so they never count). None where git can't answer."""
    try:
        def run(*args):
            return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=20).stdout
        rev = run("rev-parse", "HEAD").strip()
        return {"rev": rev or None, "dirty": bool(run("status", "--porcelain", "--untracked-files=no").strip())}
    except Exception:
        return {"rev": None, "dirty": None}
