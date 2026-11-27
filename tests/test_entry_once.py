"""One module everywhere (ENTRY-ONCE, 3.0.21): a module the app runs as a script runs the ONE imported module.

Run as a script (`python app/analyzer.py`: the source window's Generate, the benches), the file was a second copy of
the module, `__main__`, beside `app.analyzer`, which `names.py` and the token store import. `names.one_word` makes a
katakana name an `app.analyzer.JoinedWord`, and `__main__`'s own `isinstance(word, JoinedWord)` said no, so a known
katakana name's pieces were never marked known (オノデラ known: デラ listed), while the frozen app (`analyzer` verb, one
import) read them known. The same split held for the library store's helper from source (its errors and its
per-process write locks) and the window run as `python -m app.qt.shell` (its one Connect feed). Each entry now hands
over to the imported module before its body runs (`app/replan_preview.py`'s helper handed over after its body: now
before it too).
"""
import csv
import json
import os
import shutil
import subprocess
import sys

import pytest

from tests import plan_file_cases as cases

RESOURCES = os.path.join(cases.REPO, "tests", "Test Resources")
CLOSED_PORT = "http://127.0.0.1:9"          # nothing listens: Anki is "closed"

# A katakana name the tagger cuts (オノ | デラ) and names.py joins; its piece デラ is also a name of its own here.
NAME_LINES = ("オノデラさんは駅の前で待っていた。\n"
              "デラは笑って手を振った。\n"
              "オノデラさんとデラは同じ学校に通っている。\n"
              "デラが来ると、みんな静かになった。\n")

_STAND_IN = r"""
import importlib, json, runpy, sys
how, name, attr, path = sys.argv[1:5]
one = importlib.import_module(name)
ran = []
def stand_in(*a, **k):
    # (the script's own module, `__main__` while it runs: its body never ran if it never defined the entry)
    ran.append([list(sys.argv[1:]), hasattr(sys.modules["__main__"], attr)])
    return 0
setattr(one, attr, stand_in)
if name == "app.qt.shell":
    # A second copy of the window's module would open a window: its QApplication refuses here instead.
    import PyQt6.QtWidgets as widgets
    class NoWindow:
        @staticmethod
        def instance():
            raise RuntimeError("a second copy of app.qt.shell ran its own main")
    widgets.QApplication = NoWindow
sys.argv = [path] + sys.argv[5:]
code = "none"
try:
    if how == "module":
        runpy.run_module(name, run_name="__main__", alter_sys=True)
    else:
        runpy.run_path(path, run_name="__main__")
except SystemExit as e:
    code = e.code
except Exception as e:
    code = repr(e)
sys.stdout.write("\nENTRY " + json.dumps({"ran": ran, "code": code}) + "\n")
"""


@pytest.mark.parametrize("how, name, attr, rel, args", [
    ("path", "app.analyzer", "main", "app/analyzer.py", ["--language=ja", "--no-open"]),     # the window's Generate
    ("path", "app.library_store", "main", "app/library_store.py", ["sync", "--language", "zh"]),  # the store's helper
    ("path", "app.replan_preview", "helper_main", "app/replan_preview.py", ["--language", "ja"]),  # the re-plan's
    ("module", "app.qt.shell", "main", "app/qt/shell.py", []),                                # python -m app.qt.shell
])
def test_each_script_entry_runs_the_one_imported_modules_main(tmp_path, how, name, attr, rel, args):
    # why: the imported module's `main` (a stand-in here) is the one the script runs, with the script's own
    # arguments, and the file's body never runs as `__main__` (handed over before it); before, the file ran its body
    # again as `__main__` and called that copy's main.
    root = tmp_path / "root"
    root.mkdir()
    path = os.path.join(cases.REPO, *rel.split("/"))
    env = cases.child_env(str(root))
    env["QT_QPA_PLATFORM"] = "offscreen"
    p = subprocess.run([sys.executable, "-c", _STAND_IN, how, name, attr, path] + args, cwd=cases.REPO, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=110)
    lines = [l for l in p.stdout.splitlines() if l.startswith("ENTRY ")]
    assert lines, p.stdout[-2000:] + p.stderr[-2000:]
    got = json.loads(lines[-1][len("ENTRY "):])
    assert got["ran"] == [[args, False]], (got, p.stderr[-2000:])
    assert got["code"] == 0


def _library(root, language):
    """A NOW library of real test files, its known words, and settings with Anki on a closed port. Japanese: a file
    with a katakana name, the name known through KnownWord.json (オノデラ) and its piece (デラ) used alone."""
    high = os.path.join(root, "data", language, "HighPriority")
    os.makedirs(high)
    user = os.path.join(root, "User Files", language)
    os.makedirs(user)
    known_name = {"ja": "KnownWord.json", "zh": "KnownWords.json"}[language]
    with open(os.path.join(RESOURCES, language, known_name), encoding="utf-8") as f:
        known = json.load(f)
    if language == "ja":
        shutil.copy2(os.path.join(RESOURCES, "ja", "context_test.txt"), high)
        with open(os.path.join(high, "names_episode.txt"), "w", encoding="utf-8") as f:
            f.write(NAME_LINES)
        words = known["words"] if isinstance(known, dict) else known
        words.append({"dictForm": "オノデラ", "knownStatus": "KNOWN"})
    else:
        shutil.copy2(os.path.join(RESOURCES, "zh", "chinese_text_1.txt"), high)
        shutil.copy2(os.path.join(RESOURCES, "zh", "context_test.txt"), high)
    with open(os.path.join(user, "KnownWord.json"), "w", encoding="utf-8") as f:
        json.dump(known, f, ensure_ascii=False)
    with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as f:
        json.dump({"target_language": language, "anki_connect_url": CLOSED_PORT}, f)


def _generate(root, language, entry):
    """A Generate of the root's library, started the way `entry` says -> results/'s two lists' bytes.
    `script`: `python app/analyzer.py` (services/generate.command_line from source); `verb`: the frozen app's own
    `analyzer` verb (app_entry.py), which imports the module once."""
    argv = [f"--language={language}", "--no-open", "--min-freq", "1"]
    if entry == "script":
        cmd = [sys.executable, os.path.join(cases.REPO, "app", "analyzer.py")] + argv
    else:
        cmd = [sys.executable, os.path.join(cases.REPO, "app_entry.py"), "analyzer", "--headless"] + argv
    env = cases.child_env(root)
    env["SURASURA_FORCE_RUN"] = "1"          # a whole run each time: never the last run's list reused
    p = subprocess.run(cmd, cwd=cases.REPO, env=env, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=300)
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
    out = {}
    for name in ("priority_learning_list.csv", "progressive_learning_list.csv"):
        with open(os.path.join(root, "results", name), "rb") as f:
            out[name] = f.read()
    return out


def _words(blob):
    return {row["Word"] for row in csv.DictReader(blob.decode("utf-8-sig").splitlines())}


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_script_and_the_frozen_apps_verb_write_the_same_lists(tmp_path, language):
    # why: source results/ (the window from source, the benches, the trains) must read the way the shipped app does:
    # one module, one reading. Each run has a root of its own: one token store's cached known words would hand the
    # second run the first one's reading. Chinese has no katakana join; it guards the rest of the split.
    out = {}
    for entry in ("verb", "script"):
        root = str(tmp_path / entry / "root")
        _library(root, language)
        out[entry] = _generate(root, language, entry)
    words = _words(out["script"]["priority_learning_list.csv"])
    assert words                                                 # the run listed the library's words
    if language == "ja":
        # The rule "a known joined word marks its pieces known" held only in the frozen app: run as a script, the
        # known name オノデラ's piece デラ (used alone, three times) was listed as a word to learn.
        assert "デラ" not in words
    assert out["script"] == out["verb"]
