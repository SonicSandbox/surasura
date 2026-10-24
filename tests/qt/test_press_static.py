"""Every press goes through `app/qt/press.py` — the static check (round 8 row 45, P6; the scope `row45-54-scope.md`
§3.7; the Qt guide §3 *Every press reacts at once*).

What a wrong answer would cost a learner: a button or a menu item whose slot hands its work straight to a worker,
another program or the writer, so nothing shows it was pressed until the work ends (Sonic's *Mark them known*) — it is
pressed again, and the work runs twice.

The check reads the source (AST, never imports it): every slot connected to `clicked` / `triggered` / `activated` /
`returnPressed` under `app/qt/` and the modules' window files (`modules/*/qt_*.py`, none when `modules/` is absent) —
a lambda, a bound method of its class, a function of its scope or `partial(…)` of one, or a slot handed to a button
helper that connects its own parameter (`self._button(text, tip, self._save)`) — and, one level in, the methods and
functions it calls the same way, must not call `bridge.run_in_worker`, `windows.open_url`,
`screens.open_with_system` or a writer method (`Writer`'s, `app/services/moves.py`) except through `press.*`: what is
handed to a press (`qpress.run(btn, key, fn)`, `qpress.open(win, path)`) is the press's, a call after a
`qpress.begin(…)` in the same slot is marked, and a function handed on is not called there (a writer ticket's lambda
to `_give`: its toast is the mark). The deliberate ones — instant, or already marked another way — are in `ALLOWED`,
each with its reason.
"""
import ast
import os
import re

from tests.qt.test_wiring import ROOT, _window_sources

SIGNALS = {"clicked", "triggered", "activated", "returnPressed"}
DIRECT = {"run_in_worker", "open_url", "open_with_system"}  # bridge.run_in_worker, windows.open_url, screens.…
WRITERS = {"writer", "_writer"}                             # what a writer is called: `self.writer`, `writer`
# Writer's methods that ask about or run the writer itself, never a change to the library.
NOT_WRITES = {"for_language", "can_write", "reason", "can_undo", "pending", "landed_empty", "idle", "stopped", "hold",
              "release", "start", "finish"}
HANDED = {"run", "open"}                                    # the press calls whose work is handed to them
_CONNECT = re.compile(r"\.(?:clicked|triggered|activated|returnPressed)\.connect\(")
_PRESS_IMPORT = re.compile(r"^\s*from app\.qt import ([^#\n]*\bpress\b[^#\n]*)", re.M)

# "file.py:Class.method" (the function whose body makes the call) -> why it may.
ALLOWED = {
    # instant (Sonic, Q6): the press's answer is on screen in its own turn; the worker only records it behind
    "shell.py:ShellWindow.show_tab": "instant: the tab shows at once; Needs you's and the update's *seen* marks are "
                                     "written behind it",
    "shell.py:ShellWindow._failure_dismissed": "instant: ✕ takes the failure off the bar at once; its *dismissed* "
                                               "record is written behind it",
    "settings_connect.py:MinerCard._answer": "instant: the ⭐ suggestion gives way to its link at once; its answer "
                                             "is written to star.json behind it",
    # marked another way: the window's own status line names the wait (and its button waits) before the worker — the
    # scope's audit (§2) found these already reacting ("none")
    "anki_window.py:AnkiWindow.refresh_connection": "marked another way: ANKI_STATE_CHECKING painted on the state "
                                                    "line first",
    "anki_window.py:AnkiWindow._read_restore_point": "marked another way: `on_restore`'s `_begin` "
                                                     "(ANKI_READING_BACKUP) first",
    "importers.py:DeckWindow.choose": "marked another way: APKG_READING in the window's line first",
    "importers.py:ExtractWindow.choose": "marked another way: APKG_READING in the window's line first",
    "importers.py:ExtractWindow.check": "marked another way: the window writing (`begin_write`) and "
                                        "EXTRACT_CHECKING first",
    "importers.py:MigakuWindow.find_it": "marked another way: MIGAKU_LOOKING in the window's line first",
    "importers.py:MigakuWindow.read": "pressed (*Choose…*, `control`), it is `qpress.run` and returns; the worker "
                                      "after it is *Find it*'s answer read on, after MIGAKU_LOOKING",
    "sentence_dictionary_window.py:SentenceDictionaryWindow.export": "marked another way: the window exporting and "
                                                                     "DICT_CHECKING first",
    "settings_connect.py:MinerCard.check": "marked another way: MINER_CHECKING on the card first",
    "start_gate.py:Gate.pick": "marked another way: `_looking` (LOOKING on its stage line) first",
    "start_gate.py:Gate.try_again": "marked another way: `_looking` (LOOKING on its stage line) first",
    "start_gate.py:Gate._run": "marked another way: the working / preparing screen first",
    "word_lists_window.py:WordListsWindow.find": "marked another way: WORD_LISTS_FINDING in the window's line first",
    "modules/junban/qt_backfill.py:BackfillWindow._start": "marked another way: `_set_working` (its spinner and "
                                                           "line) first, every Backfill worker's one door",
    "modules/koe/qt_window.py:KoeWindow._test": "marked another way: TESTING in the window's line first",
    "modules/youtube_downloader/qt_window.py:DownloaderWindow._ask_backfill": "marked another way: SCANNING in the "
                                                                              "window's line first",
    # P3–P5 left
    "settings_connect.py:install_anki_miner": "P3–P5 left: *Install Anki Miner…* opens the wizard (its reaction); "
                                              "only when no wizard can open does the releases page open, on the "
                                              "window's thread — its answer is synchronous (test_shell_hookups pins "
                                              "it), so `press.open` is more than a one-line move",
}


def _writes():
    """The writer methods that change the library: `Writer`'s public ones, read from `moves.py`, but `NOT_WRITES`."""
    with open(os.path.join(ROOT, "app", "services", "moves.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Writer":
            return {n.name for n in node.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")} \
                - NOT_WRITES
    raise AssertionError("moves.py has no Writer")


def _press_names(source):
    """The names `app/qt/press.py` goes by in this file (`from app.qt import press as qpress`, anywhere in it)."""
    names = set()
    for found in _PRESS_IMPORT.findall(source):
        for part in found.strip("() ").split(","):
            words = part.split()
            if words and words[0] == "press":
                names.add(words[-1])
    return names


_SCOPE = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _statements(scope):
    """`scope`'s statements, those of its if / try / with / for blocks among them — never a nested function's."""
    todo = list(getattr(scope, "body", []))
    while todo:
        node = todo.pop()
        yield node
        if not isinstance(node, _SCOPE):
            for field in ("body", "orelse", "finalbody", "handlers"):
                todo += getattr(node, field, [])


class _Source:
    """One file's functions: each with its qualified name, its class and the scopes it is written in."""

    def __init__(self, tree):
        self.where = {}             # function node -> (qualname, class node or None, [its enclosing scopes, outermost
        #                             first])
        self._defs = {}
        self._walk(tree, [], None, [tree])

    def _walk(self, scope, names, cls, chain):
        for node in _statements(scope):
            if isinstance(node, ast.ClassDef):
                self._walk(node, names + [node.name], node, chain + [node])
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.where[node] = (".".join(names + [node.name]), cls, chain)
                self._walk(node, names + [node.name], cls, chain + [node])

    def defs(self, scope):
        """The functions written directly in `scope` (a module, a class, a function), by name."""
        got = self._defs.get(scope)
        if got is None:
            got = self._defs[scope] = {n.name: n for n in _statements(scope)
                                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        return got

    def resolve(self, expr, cls, chain):
        """The function `expr` names — `self.m` (its class's), a name of its scopes, `partial(f, …)` — or None."""
        if isinstance(expr, ast.Call) and _name(expr.func) == "partial" and expr.args:
            return self.resolve(expr.args[0], cls, chain)
        if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name) and expr.value.id == "self":
            return self.defs(cls).get(expr.attr) if cls is not None else None
        if isinstance(expr, ast.Name):
            for scope in reversed(chain):
                if not isinstance(scope, ast.ClassDef) and expr.id in self.defs(scope):
                    return self.defs(scope)[expr.id]
        return None


def _name(f):
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else None


def _calls(body, press):
    """The calls `body` makes itself, in source order: never inside `press.run` / `press.open` (their work is the
    press's), a lambda or a function written there (handed on, not called)."""
    found, todo = [], list(body) if isinstance(body, list) else [body]
    while todo:
        node = todo.pop()
        if isinstance(node, (ast.Lambda,) + _SCOPE):
            continue
        if isinstance(node, ast.Call):
            found.append(node)
            f = node.func
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in press \
                    and f.attr in HANDED:
                continue
        todo += ast.iter_child_nodes(node)
    return sorted(found, key=lambda c: (c.lineno, c.col_offset))


def _param(slot, fn):
    """The parameter of `fn` a connected slot calls — `slot`, `lambda: slot()`, `lambda s=slot: s()` — or None (a
    button helper: `_button(text, tip, slot)`)."""
    if isinstance(slot, ast.Lambda):
        body = slot.body
        if not (isinstance(body, ast.Call) and isinstance(body.func, ast.Name)):
            return None
        bound = dict(zip([a.arg for a in slot.args.args][::-1], slot.args.defaults[::-1]))
        slot = bound.get(body.func.id, body.func)
    if isinstance(slot, ast.Name) and slot.id in [a.arg for a in fn.args.args + fn.args.kwonlyargs]:
        return slot.id
    return None


def _argument(call, fn, param):
    """The argument `call` (of the helper `fn`) passes as `param`, or None."""
    for k in call.keywords:
        if k.arg == param:
            return k.value
    names = [a.arg for a in fn.args.args]
    if names and names[0] == "self" and isinstance(call.func, ast.Attribute):
        names = names[1:]
    i = names.index(param) if param in names else len(call.args)
    return call.args[i] if i < len(call.args) else None


def offenders(name, source, writes=None):
    """`name`'s slots that hand work over without a press: ["<name>:<line> <Class.method> calls <what> (a <signal>
    slot, line <n>)"], `ALLOWED` left out. A slot handed to a button helper (a function that connects its own
    parameter) is followed from each call of the helper."""
    if not _CONNECT.search(source):
        return []
    writes = _writes() if writes is None else writes
    press = _press_names(source)
    src = _Source(ast.parse(source))
    text = source.splitlines()
    out = []

    def what(call):
        """The direct call `call` makes, named, or None."""
        f = call.func
        attr = _name(f)
        if attr in DIRECT:
            return attr
        if isinstance(f, ast.Attribute) and attr in writes and _name(f.value) in WRITERS:
            return f"writer.{attr}"
        return None

    def look(body, fn, signal, at, depth, state):
        """`body` (of the function `fn`), run as the slot: each direct call before a `press.begin` named."""
        qual, cls, chain = src.where[fn]
        for call in _calls(body, press):
            f = call.func
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in press:
                state["marked"] |= f.attr == "begin"
                continue
            got = what(call)
            if got is not None:
                if not state["marked"] and f"{name}:{qual}" not in ALLOWED:
                    out.append(f"{name}:{call.lineno} {qual} calls {got} (a {signal} slot, line {at})")
                continue
            if depth == 0:
                target = src.resolve(f, cls, chain + [fn])
                if target is not None and target in src.where and target not in state["seen"]:
                    state["seen"].add(target)
                    look(target.body, target, signal, at, 1, state)

    def slot_of(slot, fn, signal, at):
        """`slot`, connected in `fn` to `signal` at line `at`, read as the press it is."""
        state = {"marked": False, "seen": set()}
        if isinstance(slot, ast.Lambda):
            look(slot.body, fn, signal, at, 0, state)
            return
        got = what(ast.Call(func=slot, args=[], keywords=[]))
        if got is not None:
            qual = src.where[fn][0]
            if f"{name}:{qual}" not in ALLOWED:
                out.append(f"{name}:{at} {qual} connects {got} itself (a {signal} slot)")
            return
        _, cls, chain = src.where[fn]
        target = src.resolve(slot, cls, chain + [fn])
        if target is not None and target in src.where:
            state["seen"].add(target)
            look(target.body, target, signal, at, 0, state)

    def sites(pattern):
        """(function, call) for each call on a line `pattern` finds, in the statement written there."""
        lines = {n for n, line in enumerate(text, 1) if pattern.search(line)}
        for fn in list(src.where):
            if not any(fn.lineno <= n <= fn.end_lineno for n in lines):
                continue
            for stmt in fn.body:
                if isinstance(stmt, _SCOPE) or not any(stmt.lineno <= n <= stmt.end_lineno for n in lines):
                    continue
                for call in _calls([stmt], press):
                    yield fn, call

    helpers = {}                                        # function node -> (its parameter connected, the signal)
    for fn, call in sites(_CONNECT):
        f = call.func
        if not (isinstance(f, ast.Attribute) and f.attr == "connect" and isinstance(f.value, ast.Attribute)
                and f.value.attr in SIGNALS and call.args):
            continue
        param = _param(call.args[0], fn)
        if param is not None:
            helpers[fn] = (param, f.value.attr)
        else:
            slot_of(call.args[0], fn, f.value.attr, call.lineno)
    if helpers:
        named = re.compile(r"\b(?:%s)\(" % "|".join(sorted({re.escape(h.name) for h in helpers})))
        for fn, call in sites(named):
            _, cls, chain = src.where[fn]
            helper = src.resolve(call.func, cls, chain + [fn])
            if helper in helpers:
                param, signal = helpers[helper]
                slot = _argument(call, helper, param)
                if slot is not None:
                    slot_of(slot, fn, signal, call.lineno)
    return out


def test_no_press_hands_its_work_over_except_through_press():
    # Every slot under app/qt and the module windows: no direct worker, open or writer call (the list names each).
    writes = _writes()
    found = []
    for name, source in _window_sources():
        found += offenders(name, source, writes)
    assert found == []


def test_every_allowed_entry_still_names_a_function_and_says_why():
    # An entry outliving its code would let a new offender of the same name through unseen; one without a reason
    # is a gap nobody decided.
    sources = dict(_window_sources())
    stale = []
    for entry, why in ALLOWED.items():
        file, _, qual = entry.partition(":")
        if file.startswith("modules/") and not os.path.isdir(os.path.join(ROOT, "modules")):
            continue                                     # the private modules absent: their entries rest
        quals = {q for q, _, _ in _Source(ast.parse(sources.get(file, ""))).where.values()}
        if qual not in quals or not why.strip():
            stale.append(entry)
    assert stale == []


PLANTED = '''from app.qt import bridge, windows
from app.qt import press as qpress


class Card:
    def build(self, button, act, field, win):
        button.clicked.connect(self._go)
        act.triggered.connect(lambda: self._helper())
        field.returnPressed.connect(lambda: windows.open_url("https://jiten.moe"))
        button.clicked.connect(lambda: qpress.run(button, "k", self._work))
        act.triggered.connect(self._marked)

        def local():
            win.writer.remove([1])
        act.activated.connect(local)
        act.triggered.connect(lambda: self._give(lambda t: win.writer.move([1], "now", label=t)))
        act.triggered.connect(win.writer.undo)
        self.pin = self._button("Pin", self._pin)
        self.quiet = qpress.room(self._button("Pin", lambda: qpress.run(self.pin, "pin", self._work)))

    def _button(self, text, slot):
        b = QPushButton(text)
        b.clicked.connect(lambda _c=False: slot())
        return b

    def _pin(self):
        self.writer.pin([1])

    def _go(self):
        bridge.run_in_worker(self._work)

    def _helper(self):
        bridge.run_in_worker(self._work)
        self._deeper()

    def _deeper(self):
        bridge.run_in_worker(self._work)

    def _marked(self):
        bridge.run_in_worker(self._work)
        p = qpress.begin(None, "k", win=self)
        bridge.run_in_worker(self._work, then=lambda _v: qpress.end(p, self))

    def _work(self):
        return 1
'''


WRITES = {"move", "remove", "undo", "pin"}


def test_the_check_names_a_planted_offender_and_passes_what_goes_through_press():
    # Proof the check can fail: a bound method, a lambda's method one level in, a link opened at once, a local
    # function's write, a writer method connected itself, a slot handed to a button helper, and a call before its
    # press's `begin` are named, by line and function; work handed to a press, handed on, after `begin`, or two
    # levels in is not.
    found = sorted(f.split(" (")[0] for f in offenders("planted.py", PLANTED, WRITES))
    assert found == sorted([
        "planted.py:27 Card._pin calls writer.pin",
        "planted.py:30 Card._go calls run_in_worker",
        "planted.py:33 Card._helper calls run_in_worker",
        "planted.py:9 Card.build calls open_url",
        "planted.py:40 Card._marked calls run_in_worker",
        "planted.py:14 Card.build.local calls writer.remove",
        "planted.py:17 Card.build connects writer.undo itself",
    ])
    # An allow-listed function is let through, by its file and qualified name.
    ALLOWED["planted.py:Card._go"] = "the planted proof"
    try:
        assert not any("Card._go" in f for f in offenders("planted.py", PLANTED, WRITES))
    finally:
        del ALLOWED["planted.py:Card._go"]
