"""Three lints for the bugs people kept finding after 3.0.0, read from the source — never by running it or importing the
app — so each fails at once, on every run and every machine. Run by tests/test_guard_lints.py (the guard set, `python
run_tests.py --guards`). Of 82 defects fixed after 3.0.0, people found 61; the largest class was two pieces of the app
disagreeing about who owns a decision, and the tests missed them because each tested against stand-ins it wrote.

* `names_off_the_window`: every `getattr` / `hasattr` of the window (`ShellWindow`) or its services (`Services`) with a
  written-out name, under app/, names an attribute the real class defines or the app assigns on it. A name only a
  test's stand-in carries turns a typo or a rename into a feature silently off in the shipped app (`sort_screen` read
  `shell.chores`; the real window has `shell.services.chores`). Anything else is listed in `NAME_SEAMS`, with why.
* `anki_writes` and `shared_readers` (the roles lint, 3.0/ROLES.md): each call that changes a card in Anki (suspend,
  unsuspend, tags, flags, deck, position, delete) comes only from a listed (file, function), each naming its piece and
  the ROLES.md row that lets it (`ANKI_WRITERS`); each shared idea — which list file "your list" is, the deck, the
  side-by-side pair, the song rule, the known-word test — is read only by its owner and the readers listed beside it
  (`SHARED_OWNERS`, `SHARED_READERS`). A new place fails until it is written down.
* `duplicate_definitions` and `store_aliases`: no name is defined twice in one block of the app's code (the later one
  silently wins: pyflakes' F811, as an `ast` scan, no new dependency); every `Store.x = _store_x` is bound once and
  every `_store_*` function of the library store is bound.

Each list names a place by (file, the function or class it is in) and says why; a place that no longer needs its entry
fails too (a fix landed, a function renamed, a file gone), so the lists stay true. A place in a module this checkout
hasn't at all (a private module, on GitHub's public checkout) is no stale entry.
"""
import ast
import os
import re

from tests.flake_lints import ROOT, _parse, _text, app_files

SHELL_FILE = "app/qt/shell.py"


def _code(root=ROOT):
    """The app's own code (app/ and modules/, their tests and a vendored copy of another project's code left out)."""
    return [f for f in app_files(root) if "/vendor/" not in f]


def _app_only(root=ROOT):
    return [f for f in _code(root) if f.startswith("app/")]


def _may(root, path, words):
    """Read as text first: parsed only where a find may be (a parse and a walk of the whole app take seconds)."""
    text = _text(root, path)
    return any(w in text for w in words)


class _Facts:
    """One walk of a file's tree, kept for the run: what the lints read, and the function or class each node is in
    (dotted, outermost first, as flake_lints' `_owners` names it)."""
    __slots__ = ("owner", "calls", "strings", "functions", "dicts", "parents", "docs", "blocks")

    def __init__(self, tree):
        self.owner, self.parents, self.docs = {}, {}, set()
        self.calls, self.strings, self.functions, self.dicts, self.blocks = [], [], [], [], []
        stack = [(tree, "")]
        while stack:
            node, name = stack.pop()
            body = getattr(node, "body", None)
            if isinstance(body, list):
                self.blocks += [b for b in (body, getattr(node, "orelse", None), getattr(node, "finalbody", None))
                                if isinstance(b, list) and b]
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and body and \
                        isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                    self.docs.add(id(body[0].value))         # a docstring: prose, never a reader of what it names
            for child in ast.iter_child_nodes(node):
                inner = name
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    inner = f"{name}.{child.name}" if name else child.name
                    if not isinstance(child, ast.ClassDef):
                        self.functions.append(child)
                self.owner[child] = inner or "<module>"
                if isinstance(child, ast.Call):
                    self.calls.append(child)
                    if child.args:
                        self.parents[id(child.args[0])] = child
                elif isinstance(child, ast.Constant) and isinstance(child.value, str):
                    self.strings.append(child)
                elif isinstance(child, ast.Dict):
                    self.dicts.append(child)
                    self.parents.update((id(k), child) for k in child.keys if k is not None)
                elif isinstance(child, ast.Subscript):
                    self.parents[id(child.slice)] = child
                stack.append((child, inner))


_FACTS = {}


def _facts(root, path):
    key = (root, path)
    if key not in _FACTS:
        _FACTS[key] = _Facts(_parse(root, path))
    return _FACTS[key]


# --- 1. a name the real window or its services lacks ---------------------------------------------------------------- #
def _class(tree, name):
    return next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name), None)


def class_attributes(cls):
    """Every name a class defines: its methods and class attributes, and every `self.<name>` any of its methods
    assigns (a nested function's too)."""
    out = set()
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                out |= {e.id for e in ast.walk(target) if isinstance(e, ast.Name)}
    for node in ast.walk(cls):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                out |= {e.attr for e in ast.walk(target) if isinstance(e, ast.Attribute)
                        and isinstance(e.value, ast.Name) and e.value.id == "self"}
    return out


def _kind(expr):
    """"shell" when `expr` reads as the window (`shell`, `self.shell`, `self._shell`, `getattr(x, "shell", …)`),
    "services" when it reads as its services (`services`, `self.services`, `win.services`, `getattr(x, "services",
    …)`), else None."""
    if isinstance(expr, ast.Call) and getattr(expr.func, "id", None) == "getattr" and len(expr.args) >= 2 and \
            isinstance(expr.args[1], ast.Constant):
        name = expr.args[1].value
    elif isinstance(expr, ast.Attribute):
        name = expr.attr
    elif isinstance(expr, ast.Name):
        name = expr.id
    else:
        return None
    name = str(name).lstrip("_")
    return name if name in ("shell", "services") else None


def _named(call):
    """(the object read, the name) of a `getattr(x, "name", …)` / `hasattr(x, "name")` / `setattr(x, "name", v)`."""
    if isinstance(call, ast.Call) and getattr(call.func, "id", None) in ("getattr", "hasattr", "setattr") and \
            len(call.args) >= 2 and isinstance(call.args[1], ast.Constant) and isinstance(call.args[1].value, str):
        return call.args[0], call.args[1].value
    return None, None


# `self.shell.name = …` / `services.a, other.b = …` / `services.n += 1` / `setattr(self.services, "name", …)`: an
# assignment on the window or its services, read as text (a parse of every file that names either takes seconds): a
# statement that starts its line with its targets (a chain `a = services.b = …` too), each target read on its own —
# never a call's keyword argument or a comment. Another object whose name ends in either word may let a name through; it can never fail one.
_ASSIGN = re.compile(r"[ \t]*((?:[\w.]+[ \t]*,[ \t]*)*[\w.]+)[ \t]*(?::[^=\n]+)?(?:[-+*/|&%^@]|//|\*\*|>>|<<)?=(?!=)")
_TARGET = re.compile(r"(?:^|\.)_?(shell|services)\.(\w+)$")
_SETATTR_TEXT = re.compile(r"setattr\(\s*(?:[\w.]*\.)?_?(shell|services)\s*,\s*[\"'](\w+)[\"']")


def window_names(root=ROOT, files=None):
    """{"shell": names, "services": names}: what the real `ShellWindow` / `Services` define, and every name the app
    assigns on one (`services.arrivals_worker = …`, `setattr(shell, "x", …)`) anywhere under app/."""
    tree = _parse(root, SHELL_FILE)
    out = {"shell": class_attributes(_class(tree, "ShellWindow")), "services": class_attributes(_class(tree, "Services"))}
    for path in files if files is not None else _app_only(root):
        text = _text(root, path)
        if "shell." not in text and "services." not in text and "setattr(" not in text:
            continue
        for line in text.splitlines():
            if "shell." not in line and "services." not in line:
                continue
            at, m = 0, _ASSIGN.match(line)
            while m:
                for target in m.group(1).split(","):
                    hit = _TARGET.search(target.strip())
                    if hit:
                        out[hit.group(1)].add(hit.group(2))
                at = m.end()
                m = _ASSIGN.match(line, at)
        for m in _SETATTR_TEXT.finditer(text):
            out[m.group(1)].add(m.group(2))
    return out


_GETATTR_TEXT = re.compile(r"\b(?:get|has)attr\s*\(\s*(?:getattr\s*\(|(?:[\w.()]*\.)?_?(?:shell|services)\s*,)")


def names_off_the_window(root=ROOT, files=None, known=None):
    """[(file, owner, line, name, call)] for every getattr / hasattr of the window or its services (the window's and
    the services' own `self` in their classes too) with a name neither defines nor the app assigns."""
    known = known if known is not None else window_names(root)
    found = []
    for path in files if files is not None else _app_only(root):
        if path != SHELL_FILE and not ("attr" in _text(root, path) and _GETATTR_TEXT.search(_text(root, path))):
            continue
        facts = _facts(root, path)
        for node in facts.calls:
            if getattr(node.func, "id", None) not in ("getattr", "hasattr"):
                continue
            obj, name = _named(node)
            if name is None:
                continue
            owner = facts.owner[node]
            kind = _kind(obj)
            if kind is None and path == SHELL_FILE and isinstance(obj, ast.Name) and obj.id == "self":
                kind = {"ShellWindow": "shell", "Services": "services"}.get(owner.split(".")[0])
            if kind and name not in known[kind]:
                found.append((path, owner, node.lineno, name, ast.unparse(node)))
    return sorted(found, key=lambda f: (f[0], f[2], f[3]))


# (file, the function it is in, the name) -> why the real window or its services needn't have it.
NAME_SEAMS = {
    ("app/qt/settings_live.py", "Live._text_size", "set_text_size"):
        "dead while `LIVE_TEXT_SIZE` is off (the signed ruling, FXP S5): ShellWindow has no `set_text_size` and the "
        "branch falls back to `set_look`; kept with the live path for M4.1 — whoever turns it on adds the method to "
        "the window or drops this lookup",
    ("app/qt/shell.py", "ShellWindow.__init__", "arrivals"):
        "a test seam: a test's `services.arrivals` (a stand-in arrivals client, tests/qt/test_arrivals*.py) in place "
        "of the warm worker process the real window makes (`library_for` decides there)",
    ("app/qt/shell.py", "ShellWindow.arrivals_worker", "arrivals"):
        "a test seam: a test's `services.arrivals` first, in place of the `ArrivalsWorker` process the real window "
        "starts (tests/qt/test_arrivals.py and others hand one)",
    ("app/qt/shell.py", "ShellWindow._fetcher_for", "cover_fetcher_factory"):
        "a test seam: tests/qt/test_covers_wiring.py's factory in place of `covers_online.Fetcher`, which would reach "
        "AniList / YouTube; the real window always takes the real Fetcher",
    ("app/qt/shell.py", "ShellWindow._words_provider", "title_words"):
        "a test seam: tests/qt/test_word_peek.py's provider in place of the `TitleWords` built over the writer's "
        "numbers; the real window always builds its own",
    ("app/qt/shell.py", "ShellWindow._open_looks", "source_looks"):
        "a test seam: a test's `services.source_looks` (tests/qt/test_needs_seams.py, test_window_sources.py and "
        "others) in place of the `SourceLooks` worker over the library's own store handle",
}


def unexplained_names(found, allow=None):
    allow = NAME_SEAMS if allow is None else allow
    return [f for f in found if (f[0], f[1], f[3]) not in allow]


def stale_names(found, allow=None, root=ROOT):
    allow = NAME_SEAMS if allow is None else allow
    seen = {(f[0], f[1], f[3]) for f in found}
    return sorted(k for k in allow if k not in seen and _here(root, k[0]))


# --- 2a. the roles lint: who may change a card in Anki -------------------------------------------------------------- #
# AnkiConnect's actions that change a card or a note's state (a field write — Backfill's, Swap's, the one sentence
# field writer's — is not on this list: no ROLES.md row forbids it by itself).
ANKI_ACTIONS = frozenset({"suspend", "unsuspend", "addTags", "removeTags", "replaceTags", "clearUnusedTags",
                          "updateNoteTags", "setSpecificValueOfCard", "changeDeck", "repositionNewCards",
                          "deleteNotes", "deleteDecks", "removeEmptyNotes", "forgetCards", "relearnCards",
                          "setDueDate", "setEaseFactors"})
# The app's own doors to those actions: Junban's (modules/junban/ankiconnect.py) and Connect's adapters
# (app/connect/shelf.py `AnkiConnectAnki`, app/connect/undo.py `AnkiConnectUndo`, app/connect/tidy.py
# `AnkiConnectTidy`). A call by one of these names is a write as much as the action itself.
ANKI_DOORS = frozenset({"suspend", "unsuspend", "add_tags", "remove_tags", "add_tag", "remove_tag", "set_flags",
                        "set_due", "set_due_checked", "delete_notes", "change_deck", "delete_deck"})


# A call that sends an action named by its first argument: `anki_connect.invoke`, Junban's `_suspend_action` /
# `_tag_action`, a request or a `multi` (never `later.get("suspend")`: a plan's key, not a write).
_SENDER = re.compile(r"invoke|action|request|^_?call$|^multi$|^_?send")


def _action_names(expr):
    """The action names a call's first argument writes out: a string, or either side of `"a" if x else "b"`."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return [expr.value]
    if isinstance(expr, ast.IfExp):
        return _action_names(expr.body) + _action_names(expr.orelse)
    return []


_WRITE_TEXT = tuple(f'"{a}"' for a in sorted(ANKI_ACTIONS)) + tuple(f"'{a}'" for a in sorted(ANKI_ACTIONS)) + \
    tuple(f"{d}(" for d in sorted(ANKI_DOORS))


def anki_writes(root=ROOT, files=None):
    """[(file, owner, line, what)] for every place that changes a card in Anki: an AnkiConnect action written out as a
    call's first argument (`invoke("suspend", …)`) or as a request's `"action"` (`{"action": "repositionNewCards"}`),
    or a call to one of the app's doors (`ankiconnect.suspend(…)`, `anki.delete_notes(…)`)."""
    found = []
    for path in files if files is not None else _code(root):
        if not _may(root, path, _WRITE_TEXT):
            continue
        facts = _facts(root, path)
        for node in facts.calls:
            what = []
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
            if node.args and name and _SENDER.search(name):
                what += [a for a in _action_names(node.args[0]) if a in ANKI_ACTIONS]
            if name in ANKI_DOORS:
                what.append(f"{ast.unparse(node.func)}()")
            found += [(path, facts.owner[node], node.lineno, w) for w in what]
        for node in facts.dicts:
            found += [(path, facts.owner[node], node.lineno, v.value) for k, v in zip(node.keys, node.values)
                      if isinstance(k, ast.Constant) and k.value == "action" and isinstance(v, ast.Constant)
                      and v.value in ANKI_ACTIONS]
    return sorted(found, key=lambda f: (f[0], f[2], f[3]))


_CONNECT = "Connect: makes cards — never another card's state, except undoing its own batch / bringing its own " \
           "set-aside card back"
_JUNBAN = "Junban: orders Anki's new cards; your own cards off the list: Leave them · At the back · Set aside"
_SHELF = "overlaps: Connect's shelf vs Junban's Suspend them (Kyou-SH 3.0.17) — the shelf's code has no caller, " \
         "kept for its tests, listed to retire"
_TIDY = "Tidy / Torii: keep Anki uncluttered — Connect's own never-studied cards past the window, backup + Undo; " \
        "never delete anything without a backup"

# (file, function) -> (the piece, its ROLES.md row, why this place may change a card).
ANKI_WRITERS = {
    # --- the doors themselves
    ("modules/junban/ankiconnect.py", "_write_action"): ("Junban", _JUNBAN, "the door: a position (or a flag) "
                                                         "written as `setSpecificValueOfCard`, for its callers below"),
    ("modules/junban/ankiconnect.py", "_native_action"): ("Junban", _JUNBAN, "the door: Anki's own "
                                                          "`repositionNewCards`, for its callers below"),
    ("modules/junban/ankiconnect.py", "suspend"): ("Junban", _JUNBAN, "the door: `suspend`"),
    ("modules/junban/ankiconnect.py", "unsuspend"): ("Junban", _JUNBAN, "the door: `unsuspend`"),
    ("modules/junban/ankiconnect.py", "add_tags"): ("Junban", _JUNBAN, "the door: `addTags`"),
    ("modules/junban/ankiconnect.py", "remove_tags"): ("Junban", _JUNBAN, "the door: `removeTags`"),
    ("modules/junban/ankiconnect.py", "set_due_checked"): ("Junban", _JUNBAN, "the door: positions read back "
                                                           "before each request (`set_due`)"),
    ("app/connect/shelf.py", "AnkiConnectAnki.suspend"): ("Connect", _SHELF, "the shelf's Anki adapter: its one "
                                                          "caller, `shelve`, is unreachable in the app (below)"),
    ("app/connect/shelf.py", "AnkiConnectAnki.unsuspend"): ("Connect", _CONNECT, "the shelf's Anki adapter: its own "
                                                            "set-aside cards back"),
    ("app/connect/shelf.py", "AnkiConnectAnki.add_tag"): ("Connect", _CONNECT, "the shelf's Anki adapter: the "
                                                          "shelf's own tag"),
    ("app/connect/shelf.py", "AnkiConnectAnki.remove_tag"): ("Connect", _CONNECT, "the shelf's Anki adapter: the "
                                                             "shelf's own tag off"),
    ("app/connect/undo.py", "AnkiConnectUndo.delete_notes"): ("Connect", _CONNECT, "Undo this batch's adapter"),
    ("app/connect/tidy.py", "AnkiConnectTidy.change_deck"): ("Tidy", _TIDY, "Tidy's adapter: the cards it tidies "
                                                             "into a deck of their own for the package backup, and "
                                                             "back to their decks (a failed backup, a card that "
                                                             "changed meanwhile, the next look after a kill, Undo)"),
    ("app/connect/tidy.py", "AnkiConnectTidy.delete_deck"): ("Tidy", _TIDY, "Tidy's adapter: its own deck, removed "
                                                             "once no card is in it (`_drop_temp`)"),
    # --- Connect
    ("app/connect/anki_miner.py", "tag_names"): ("Connect", _CONNECT, "the batch it just made: `surasura::name` on "
                                                 "the cards made for names"),
    ("app/connect/runner.py", "Steps.tag_names"): ("Connect", _CONNECT, "the same names' tag, added after its own "
                                                   "batch when Anki didn't take it"),
    ("app/connect/decks.py", "_change"): ("Connect", _CONNECT, "One deck (Michi-DK): its own cards (the store's "
                                          "`made_words`) moved into the deck shown, on the learner's press, "
                                          "with a snapshot and Undo"),
    ("app/connect/shelf.py", "shelve"): ("Connect", _SHELF, "suspends at the cap: unreachable in the app since "
                                         "Kyou-SH — its callers `Steps._shelve` (only from `Steps.shelve`) and "
                                         "`shelve_item` are called by tests only"),
    ("app/connect/shelf.py", "bring_back"): ("Connect", _CONNECT, "the swap-in: its own shelved cards back"),
    ("app/connect/shelf.py", "_untag"): ("Connect", _CONNECT, "the shelf's own tag off the cards it brought back"),
    ("app/connect/shelf.py", "tidy"): ("Connect", _CONNECT, "the shelf's own tag off a card the learner "
                                       "un-suspended in Anki (the card itself untouched)"),
    ("app/connect/shelf.py", "restore"): ("Connect", _CONNECT, "Put back: its own shelved cards back"),
    ("app/connect/undo.py", "run"): ("Connect", _CONNECT, "Undo this batch: its own never-studied notes"),
    ("app/connect/tidy.py", "run"): ("Tidy", _TIDY, "the tidy itself: Connect's own never-studied notes past the "
                                     "cap, deleted only once their package backup holds every note, each read again "
                                     "just before"),
    ("app/connect/tidy.py", "_backup"): ("Tidy", _TIDY, "the cards of the notes it will tidy (already checked) into "
                                         "its own deck, so the package holds exactly them"),
    ("app/connect/tidy.py", "_cards_home"): ("Tidy", _TIDY, "only cards found in its own deck, back to the decks its "
                                             "ledger recorded"),
    ("app/connect/tidy.py", "_drop_temp"): ("Tidy", _TIDY, "its own deck, only when a search finds no card in it"),
    ("app/connect/sentence_audio.py", "AnkiConnectNotes.tag"): (
        "the one sentence-field writer (Add audio, the AI audio, Piyo's translations)",
        "Backfill: fills fields of existing cards; Piyo: writes cards only when asked",
        "the tag naming which path filled an empty field, put on (or off, its Undo) with that field's write"),
    ("app/connect/known_signal.py", "undo"): (
        "the review loop (Known from Anki)", "The review loop: reads the learner's moves — never edits cards",
        "Undo of one word marked known: its cards un-suspended when the signal included `suspended` (Sonic's ruling "
        "P2.4-6, 2026-10-08) — a card edit ROLES.md's row doesn't name: listed for the lead"),
    # --- Junban
    ("modules/junban/first_touch.py", "_put_back"): ("Junban", _JUNBAN, "the first-run put back: its own positions "
                                                     "and tags undone"),
    ("modules/junban/first_touch.py", "_unsuspend_checked"): ("Junban", _JUNBAN, "the first-run put back: its own "
                                                              "suspends off, each card read again first"),
    ("modules/junban/first_touch.py", "_flags_checked"): ("Junban", _JUNBAN, "the first-run put back: its own flags "
                                                          "back"),
    ("modules/junban/reposition.py", "_run"): ("Junban", _JUNBAN, "a reorder: positions, and the cards it takes "
                                               "out / puts back (its own tags)"),
    ("modules/junban/reposition.py", "_write_spaced"): ("Junban", _JUNBAN, "the fast re-plan's positions"),
    ("modules/junban/reposition.py", "_try_front"): ("Junban", _JUNBAN, "a card brought to the front: positions "
                                                     "only"),
    ("modules/junban/reposition.py", "_apply_later"): ("Junban", _JUNBAN, "Set aside: tag, flag and suspend the "
                                                       "cards past the list as planned"),
    ("modules/junban/reposition.py", "_apply_clear"): ("Junban", _JUNBAN, "the clean-up: its own flag and tag off"),
    ("modules/junban/reposition.py", "_later_back_on"): ("Junban", _JUNBAN, "a restore: its own `::later` tag back "
                                                         "before it suspends again"),
    ("modules/junban/reposition.py", "_later_off_on"): ("Junban", _JUNBAN, "a restore: the `::later` tag its "
                                                        "clean-up took off, back"),
    ("modules/junban/reposition.py", "_put_back_out"): ("Junban", _JUNBAN, "Put back: what its out tag still "
                                                        "marks, restored"),
    ("modules/junban/reposition.py", "_restore"): ("Junban", _JUNBAN, "a restore from its own snapshot"),
    ("modules/junban/reposition.py", "_restore_run"): ("Junban", _JUNBAN, "undoes one run from its snapshot — "
                                                       "only what that run changed"),
    ("modules/junban/show_tags.py", "apply"): ("Junban", _JUNBAN, "a show's label tags: the old label off, the new "
                                               "one on"),
}


# --- 2b. the roles lint: one owner for each shared idea ------------------------------------------------------------- #
_LIST_FILES = frozenset({"priority_learning_list.csv", "progressive_learning_list.csv"})
_NOTES = re.compile("[♪♫♬🎵🎶〽]")
_SONG_WORDS = re.compile(r"(?i)song|lyric|karaoke|opening|ending|歌|主题|片头|片尾")
_RE_CALLS = frozenset({"compile", "search", "match", "fullmatch", "findall", "finditer", "sub", "split"})
_KNOWN_TEST = re.compile(r"^_*(is_known|known_test)|_known_test$")


def _list_file(node, parents, docs):
    return isinstance(node, ast.Constant) and node.value in _LIST_FILES


def _deck_read(node, parents, docs):
    """A read of the deck setting: the key named anywhere (`x.get("junban_deck")`, `x["junban_deck"]`, a tuple of keys
    read in a loop, a set of keys a change is tested against) but as a write — a dict literal's key, an assignment's
    target — which is the setting's own page."""
    if not (isinstance(node, ast.Constant) and node.value == "junban_deck") or id(node) in docs:
        return False
    parent = parents.get(id(node))
    if isinstance(parent, ast.Dict):
        return False
    return not (isinstance(parent, ast.Subscript) and not isinstance(parent.ctx, ast.Load))


def _pair_read(node, parents, docs):
    return isinstance(node, ast.Constant) and node.value == "side_by_side" and id(node) not in docs


def _song_test(node, parents, docs):
    """A song test of its own: a string holding a song's mark (♪ …), or a pattern handed to `re` that names songs."""
    if not (isinstance(node, ast.Constant) and isinstance(node.value, str)) or id(node) in docs:
        return False
    if _NOTES.search(node.value):
        return True
    parent = parents.get(id(node))
    return isinstance(parent, ast.Call) and getattr(parent.func, "attr", None) in _RE_CALLS and \
        getattr(parent.func.value, "id", None) == "re" and bool(parent.args) and parent.args[0] is node and \
        bool(_SONG_WORDS.search(node.value))


def _known_test(node, parents, docs):
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and bool(_KNOWN_TEST.search(node.name))


# idea -> (how a place reads it, what it means)
SHARED_IDEAS = {
    "the list file": (_list_file, "which file is \"your list\" (the ranked list a Generate writes): its name written "
                                  "out (rows 10, 72 of the audit: Piyo's soon and Junban read another list)"),
    "the deck": (_deck_read, "the deck Surasura shows for new cards: a read of `junban_deck` (row 65: Connect's "
                             "cards landed in another deck than the one shown)"),
    "the side-by-side pair": (_pair_read, "the titles taking turns while side by side is on: its key written out "
                                          "(row 46: the window and Anki picked different two titles)"),
    "the song rule": (_song_test, "which lines are songs: a ♪ mark or a song pattern of its own (row 64: Connect "
                                  "mined song lines a Generate leaves out)"),
    "the known test": (_known_test, "whether a card's word is known: a test of its own, by its name (row 74: "
                                    "Junban's known test read a kana card's word alone)"),
}

# idea -> the places that own it: (file, function or "*" for the whole file).
SHARED_OWNERS = {
    "the list file": {("app/analyzer.py", "*"): "the writer: a Generate's `OUTPUT_CSV` / `OUTPUT_PROGRESSIVE` (and "
                                                "its own checks that both are there)"},
    "the deck": {("app/services/setup_wizard.py", "junban_deck"): "順's deck for a language (none while it is the "
                                                                  "other language's)",
                 ("app/anki_deck_options.py", "deck_for"): "Settings' New cards a day deck (順's while its scope is "
                                                           "one deck); `connect.fields.surasura_deck` reads both"},
    "the side-by-side pair": {("app/library_store.py", "*"): "`side_pair`, the one rule, and `Store.side_by_side`"},
    "the song rule": {("app/song_lines.py", "*"): "`song_style`, `noted`, `left_out`: the one rule a Generate, "
                                                  "Connect's cue reader and New arrivals read"},
    "the known test": {("modules/junban/reposition.py", "is_known_word"):
                       "Junban's known test; the ✓ chip and Connect's cap read it (app/anki_match.py's rule for a "
                       "kana card's word)",
                       ("modules/junban/reposition.py", "known_test"): "its memo: `is_known_word` with the words read "
                                                                       "once"},
}

# (idea, file, function) -> why this place names the idea itself today (each a candidate to call the owner instead).
SHARED_READERS = {
    # --- the list file: no one owner today — each names the file itself (listed for the lead)
    ("the list file", "app/cli/verbs.py", "<module>"): "`PRIORITY_CSV` / `PROGRESSIVE_CSV`: the CLI's and Piyo's",
    ("the list file", "app/arrivals_worker.py", "Worker._listed"): "New arrivals' estimate reads the list",
    ("the list file", "app/exports.py", "<module>"): "Export's source table: the list file each export copies",
    ("the list file", "app/library_store.py", "_junban_current"): "the store's study order reads Junban's list",
    ("the list file", "app/replan_preview.py", "_lists"): "the fast re-plan reads both lists",
    ("the list file", "app/services/journey.py", "_lists"): "the journey reads both lists",
    ("the list file", "app/static_html_generator.py", "<module>"): "the report's pages read the list",
    ("the list file", "modules/junban/reposition.py", "<module>"): "Junban's order reads the list",
    ("the list file", "modules/youtube_downloader/preview.py", "library_contexts_path"):
        "the YouTube preview ranks by the list",
    # --- the deck
    ("the deck", "app/cli/verbs.py", "deck_aside"): "the CLI's re-sort: 順's scope check",
    ("the deck", "app/cli/verbs.py", "_junban_auto"): "the CLI's re-sort: the deck's new cards a day",
    ("the deck", "app/qt/settings_catalog.py", "<module>"): "the Settings catalog's row: which keys 順's row reaches "
                                                            "(a placement table, no read of the value)",
    ("the deck", "app/qt/settings_connect.py", "ConnectRows._written"): "Connect's rows read again when the deck's key "
                                                                        "was written (a change test, no read of the value)",
    ("the deck", "app/connect/miner_settings.py", "deck_for"): "Connect's setup: the deck among Anki's decks "
                                                               "(the recorded one first)",
    ("the deck", "app/replan_preview.py", "*"): "the fast re-plan: the deck recorded for a language, its set-aside "
                                                "line",
    ("the deck", "modules/junban/auto.py", "*"): "順's automatic run: its scope",
    ("the deck", "modules/junban/gui.py", "*"): "順's 2.x window: its own setting's field",
    ("the deck", "modules/junban/junban_view.py", "*"): "順's window: its own setting's field",
    ("the deck", "modules/junban/reposition.py", "*"): "順's run: its scope's deck",
    # --- the side-by-side pair
    ("the side-by-side pair", "app/services/moves.py", "*"): "the writer's moves carry the store's side-by-side "
                                                             "answer to the window",
    ("the side-by-side pair", "app/services/view_rows.py", "*"): "the rows show the store's side-by-side answer",
    ("the side-by-side pair", "app/qt/drag.py", "*"): "a drag reads the rows' side-by-side state",
    ("the side-by-side pair", "modules/junban/pins.py", "*"): "Junban's groups: the store's `side_by_side()` answer",
    # --- the song rule
    ("the song rule", "app/tracks.py", "<module>"): "which subtitle track to read: a track named for signs / songs "
                                                    "is read only when no other is there — a track's pick, never a "
                                                    "line's song test",
    # --- the known test
    ("the known test", "app/anki_sync.py", "_is_known"): "a KnownWord.json entry's own status (known / ignored), "
                                                         "not a card's word",
    ("the known test", "app/sentence_corpus.py", "collect._is_known"):
        "a word key known or readable by the list's view (`LearningView.readable`) — the list's test, not a card's",
    ("the known test", "modules/youtube_downloader/preview.py", "analyze_transcript.is_known"):
        "a word key known by the analyzer's rule — the list's test, not a card's",
    ("the known test", "app/cli/verbs.py", "_known_test"): "a word key (lemma, reading) known by the analyzer's rule "
                                                           "(the YouTube preview's) — the list's test, not a card's",
}


_SHARED_TEXT = tuple(sorted(_LIST_FILES)) + ("junban_deck", "side_by_side", "is_known", "known_test") + \
    tuple(_NOTES.pattern[1:-1])
_SONG_TEXT = re.compile(r"\bre\.(?:" + "|".join(sorted(_RE_CALLS)) + r")\(\s*[rbuRBU]*(?:\"[^\"\n]*|'[^'\n]*)(?i:" +
                        _SONG_WORDS.pattern[4:] + ")")


def shared_readers(root=ROOT, files=None):
    """[(idea, file, owner, line)] for every place that reads a shared idea itself."""
    found = []
    for path in files if files is not None else _code(root):
        text = _text(root, path)
        if not (_may(root, path, _SHARED_TEXT) or ("re." in text and _SONG_TEXT.search(text))):
            continue
        facts = _facts(root, path)
        found += [(idea, path, facts.owner[node], node.lineno) for node in facts.strings + facts.functions
                  for idea, (reads, _what) in SHARED_IDEAS.items() if reads(node, facts.parents, facts.docs)]
    return sorted(set(found), key=lambda f: (f[0], f[1], f[3]))


def _here(root, path):
    """Whether an entry's file can still explain anything: it is there — or it belongs to a module this checkout hasn't
    at all (a private module, on GitHub's public checkout). A public file renamed or deleted makes its entry stale."""
    if os.path.isfile(os.path.join(root, path)):
        return True
    parts = path.split("/")
    return not (parts[0] == "modules" and len(parts) > 2 and not os.path.isdir(os.path.join(root, *parts[:2])))


def _place(allow, path, owner):
    return (path, owner) in allow or (path, "*") in allow or (path, owner.split(".")[0]) in allow


def unexplained_writes(found, allow=None):
    allow = ANKI_WRITERS if allow is None else allow
    return [f for f in found if not _place(allow, f[0], f[1])]


def stale_writes(found, allow=None, root=ROOT):
    allow = ANKI_WRITERS if allow is None else allow
    return sorted(k for k in allow if not any(_place({k: 0}, f[0], f[1]) for f in found)
                  and _here(root, k[0]))


def unexplained_readers(found, owners=None, readers=None):
    owners = SHARED_OWNERS if owners is None else owners
    readers = SHARED_READERS if readers is None else readers
    return [f for f in found if not _place(owners.get(f[0], {}), f[1], f[2])
            and not _place({(p, o) for i, p, o in readers if i == f[0]}, f[1], f[2])]


def stale_readers(found, owners=None, readers=None, root=ROOT):
    """A listed reader with nothing left there (an owner may own an idea no one else reads: never stale)."""
    readers = SHARED_READERS if readers is None else readers
    return sorted(k for k in readers if not any(f[0] == k[0] and _place({k[1:]: 0}, f[1], f[2]) for f in found)
                  and _here(root, k[1]))


# --- 3. a name defined twice in one block --------------------------------------------------------------------------- #
def _twin_allowed(node):
    """A second definition that is meant: a property's setter / deleter, an `@overload`, a dispatch's `register`."""
    for d in getattr(node, "decorator_list", ()):
        text = ast.unparse(d)
        if text.endswith((".setter", ".getter", ".deleter")) or text in ("overload", "typing.overload") or \
                re.search(r"\.register\b", text):
            return True
    return False


_DEF_TEXT = re.compile(r"^([ \t]*)(?:async[ \t]+)?(?:def|class)[ \t]+(\w+)", re.M)


def _twice_as_text(text):
    """Whether one name may be defined twice in one block: twice at one indent with no shallower `def` / `class`
    between (which ends the block). A parse decides; this only spares the files that can't have one."""
    seen = {}
    for m in _DEF_TEXT.finditer(text):
        indent, name = len(m.group(1).expandtabs()), m.group(2)
        for deeper in [i for i in seen if i > indent]:
            del seen[deeper]
        names = seen.setdefault(indent, set())
        if name in names:
            return True
        names.add(name)
    return False


def duplicate_definitions(root=ROOT, files=None):
    """[(file, scope, line, name, first line)] for every `def` / `class` that defines a name already defined by a
    `def` / `class` earlier in the same block (a module, a class, a function, a branch): the later one silently
    wins."""
    found = []
    for path in files if files is not None else _code(root):
        if not _twice_as_text(_text(root, path)):
            continue
        facts = _facts(root, path)
        for block in facts.blocks:
            first = {}
            for stmt in block:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if stmt.name in first and not _twin_allowed(stmt):
                        scope = facts.owner[stmt].rpartition(".")[0] or "<module>"
                        found.append((path, scope, stmt.lineno, stmt.name, first[stmt.name]))
                    first.setdefault(stmt.name, stmt.lineno)
    return sorted(found)


STORE_FILE = "app/library_store.py"


def store_aliases(root=ROOT, path=STORE_FILE):
    """-> (twice: [(line, "Store.x")] each binding after a name's first, unbound: [(line, "_store_x")] each top-level
    `_store_*` function no `Store.x = …` binds)."""
    tree = _parse(root, path)
    bound, twice = {}, []
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Attribute) \
                and getattr(stmt.targets[0].value, "id", None) == "Store":
            attr = stmt.targets[0].attr
            if attr in bound:
                twice.append((stmt.lineno, f"Store.{attr}"))
            bound.setdefault(attr, ast.unparse(stmt.value))
    values = set(bound.values())
    unbound = [(s.lineno, s.name) for s in tree.body if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))
               and s.name.startswith("_store_") and s.name not in values]
    return twice, unbound


# --- the messages: each find with its file, its line and the fix ---------------------------------------------------- #
def name_message(finds):
    return "\n".join(f"{f[0]}:{f[2]} (in {f[1]}): {f[4]} — the real {'ShellWindow' if 'shell' in f[4] else 'Services'} "
                     f"has no `{f[3]}`, so the shipped app takes the default: use the name the window has, or list "
                     f"({f[0]!r}, {f[1]!r}, {f[3]!r}) in tests/guard_lints.py NAME_SEAMS with why" for f in finds)


def write_message(finds):
    return "\n".join(f"{f[0]}:{f[2]} (in {f[1]}): {f[3]} changes cards in Anki — ROLES.md says which piece may: call "
                     f"that piece's own door, or list ({f[0]!r}, {f[1]!r}) in tests/guard_lints.py ANKI_WRITERS with "
                     f"its piece, its ROLES.md row and why" for f in finds)


def reader_message(finds):
    return "\n".join(f"{f[1]}:{f[3]} (in {f[2]}): reads {f[0]} itself — call its owner "
                      f"({', '.join(f'{p}:{o}' for p, o in SHARED_OWNERS.get(f[0], {}))}), or list ({f[0]!r}, "
                      f"{f[1]!r}, {f[2]!r}) in tests/guard_lints.py SHARED_READERS with why" for f in finds)


def duplicate_message(finds):
    return "\n".join(f"{f[0]}:{f[2]}: `{f[3]}` is defined again in {f[1]} (first at line {f[4]}); the later one "
                      f"silently wins — keep one (prove the bodies' difference is the kept one's, by its tests)"
                      for f in finds)


def stale_message(entries, where):
    return "\n".join(f"{e} — nothing there needs it any more (fixed, moved or renamed): take it out of "
                      f"tests/guard_lints.py {where}" for e in entries)
