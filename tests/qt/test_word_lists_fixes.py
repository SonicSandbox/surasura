"""*Words to leave out* (W3.3 FX-wl): *Paste text* reads in a child process (S2, n16 "a worker process"), and an add
or a ✕ touches only its own rows of the list (S4, S19).

What a wrong answer would cost: the tokenizer loaded into the window's process (a stutter on a large paste, ~100 MB
held for the rest of the session); a child that crashed or hung read as "no words" or changing the chips, or left
running after the window closed; every row of a 3,000-word list made again for one add (~32 ms on the window's thread);
a row-by-row update that leaves the list showing other words than the file holds.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from app import path_utils
from app.qt import word_lists_strings as s
from app.qt.word_lists_window import SOURCE, WORD
from app.services import word_lists
from tests.qt.conftest import wait_until
from tests.qt.test_word_lists_window import _chips, _click_mark, _fresh_session, _open, _put, main  # noqa: F401

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HANG = [sys.executable, "-c", "import time; time.sleep(60)"]


@pytest.fixture
def known_file(ja_resources_dir):
    """The real Migaku export (11,176 entries, 46 IGNORED: the Ignore list's "known words file" rows)."""
    dst = os.path.join(path_utils.get_user_files_path("ja"), "KnownWord.json")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(os.path.join(ja_resources_dir, "KnownWord.json"), dst)
    return dst


@pytest.fixture
def children(monkeypatch):
    """Every paste child the window starts (its Popen), in order."""
    seen = []
    real = word_lists.Paste._started

    def record(self, proc):
        seen.append(proc)
        return real(self, proc)
    monkeypatch.setattr(word_lists.Paste, "_started", record)
    return seen


def _sentences(folder, name, n):
    with open(os.path.join(folder, name), encoding="utf-8") as f:
        return "\n".join(f.read().splitlines()[:n])


def _bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _model_rows(w):
    return [(w.model.item(i).data(WORD), w.model.item(i).data(SOURCE)) for i in range(w.model.rowCount())]


def _signals(w):
    seen = {"inserted": [], "removed": [], "reset": 0}
    w.model.rowsInserted.connect(lambda _p, first, last: seen["inserted"].append((first, last)))
    w.model.rowsRemoved.connect(lambda _p, first, last: seen["removed"].append((first, last)))
    w.model.modelReset.connect(lambda: seen.__setitem__("reset", seen["reset"] + 1))
    return seen


# --- S2: the tokenizer never loads in the window's process ----------------------------------------------------------- #
_ALONE = r"""
import json, os, sys, time
from PyQt6.QtWidgets import QApplication
app = QApplication(["fxw"])
from app.qt import bridge, shell, style, windows
from app.qt.word_lists_window import WordListsWindow
style.apply(app, "night", "M", "ja")
HEAVY = ("app.analyzer", "fugashi", "jieba", "unidic_lite")

def wait(pred, timeout=120.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if pred():
            return True
        time.sleep(0.005)
    return pred()

services = shell.Services()
main = shell.open_window(app, services)
main.show()
report = {}
for language, text in json.loads(sys.argv[1]):
    if language != "ja":
        services.settings.set({"target_language": language})
        wait(lambda: w.language == language and w.entries is not None)
    else:
        w = windows.show(main, "word-lists", WordListsWindow)
        wait(lambda: w.entries is not None)
    before = sorted(m for m in HEAVY if m in sys.modules)
    w.paste_button.click()
    w.text.setPlainText(text)
    w.find()
    found = wait(lambda: w.candidates is not None)
    report[language] = {"before": before, "after": sorted(m for m in HEAVY if m in sys.modules),
                        "chips": [w.chips.item(i).text() for i in range(w.chips.count())] if found else None}
    w.paste_button.click()
print(json.dumps(report, ensure_ascii=False))
sys.stdout.flush()
w.close()
services.shutdown(0.5)
bridge.wait_for_workers(10000)
os._exit(0)
"""


def test_a_paste_never_loads_the_tokenizer_in_the_windows_process(ja_resources_dir, zh_resources_dir):
    # A fresh interpreter holds the window alone (this test process has long imported the analyzer): before and after a
    # Japanese and a Chinese paste, none of the analyzer, fugashi, UniDic or jieba is in its sys.modules — and the
    # chips came back, so the child did the reading.
    texts = [("ja", _sentences(ja_resources_dir, "context_test.txt", 6)),
             ("zh", _sentences(zh_resources_dir, "chinese_text_1.txt", 6))]
    env = dict(os.environ, PYTHONPATH=ROOT, PYTHONIOENCODING="utf-8")
    proc = subprocess.run([sys.executable, "-c", _ALONE, json.dumps(texts, ensure_ascii=False)], cwd=ROOT, env=env,
                          capture_output=True, timeout=300)
    lines = [l for l in proc.stdout.decode("utf-8", "replace").splitlines() if l.startswith("{")]
    assert lines, proc.stderr.decode("utf-8", "replace")[-3000:]
    report = json.loads(lines[-1])
    assert report["ja"]["before"] == [] and report["ja"]["after"] == [], report
    # The language switch's settings save imports the deprecated Immersion Architect's defaults, which import the
    # analyzer (never the tokenizer: fugashi and jieba load lazily) — not the paste's doing: the paste adds nothing.
    assert report["zh"]["after"] == report["zh"]["before"], report
    assert not {"fugashi", "jieba", "unidic_lite"} & set(report["zh"]["after"]), report
    assert "冒険" in report["ja"]["chips"] and "特朗普" in report["zh"]["chips"]


def test_the_window_finds_through_the_child_never_words_in(main, monkeypatch):
    # The in-process read is the child's body alone: called from the window's process, it fails the test.
    monkeypatch.setattr(word_lists, "words_in", lambda *a, **kw: pytest.fail("words_in ran in the window's process"))
    w = _open(main)
    w.paste_button.click()
    w.text.setPlainText("冒険の準備で灯台の砂時計を見た。")
    w.find_button.click()
    assert wait_until(lambda: w.candidates is not None, 60)
    assert [c.word for c in w.candidates] == ["冒険", "準備", "灯台", "砂時計", "見る"]


# --- S2: a child that fails, hangs or is no longer wanted ------------------------------------------------------------ #
def test_a_child_that_fails_is_said_and_changes_nothing(main, monkeypatch, ja_resources_dir):
    path = _put("冒険\n")
    w = _open(main)
    w.paste_button.click()
    w.text.setPlainText(_sentences(ja_resources_dir, "context_test.txt", 4))
    w.find_button.click()
    assert wait_until(lambda: w.candidates is not None, 60)
    chips, candidates = _chips(w), list(w.candidates)
    monkeypatch.setattr(word_lists, "find_command",
                        lambda: [sys.executable, "-c", "import sys; sys.stderr.write('MeCab failed\\n'); sys.exit(3)"])
    w.text.setPlainText("彼は毎日冒険に出かけます。")
    w.find_button.click()
    prefix = s.WORD_LISTS_FIND_FAILED.format(why="")
    assert wait_until(lambda: w.status.text().startswith(prefix), 60)
    assert "exit code 3" in w.status.text() and "MeCab failed" in w.status.text()
    assert _chips(w) == chips and w.candidates == candidates        # the chips as they were
    assert _bytes(path) == "冒険\n".encode("utf-8")


def test_a_child_that_hangs_is_stopped_at_the_timeout_and_said(main, monkeypatch, children):
    path = _put("冒険\n")
    monkeypatch.setattr(word_lists, "find_command", lambda: HANG)
    monkeypatch.setattr(word_lists, "FIND_TIMEOUT", 1.0)
    w = _open(main)
    w.paste_button.click()
    w.text.setPlainText("冒険の準備")
    w.find_button.click()
    assert wait_until(lambda: "longer than 1 seconds" in w.status.text(), 30)
    assert w.status.text().startswith(s.WORD_LISTS_FIND_FAILED.format(why=""))
    assert len(children) == 1 and children[0].poll() is not None     # killed, not left running
    assert w.candidates is None and w.chips.count() == 0
    assert _bytes(path) == "冒険\n".encode("utf-8")


def test_closing_the_window_mid_paste_kills_its_child(main, monkeypatch, children):
    path = _put("冒険\n")
    monkeypatch.setattr(word_lists, "find_command", lambda: HANG)
    w = _open(main)
    w.paste_button.click()
    w.text.setPlainText("冒険の準備")
    w.find_button.click()
    assert wait_until(lambda: len(children) == 1, 30)
    assert children[0].poll() is None
    w.close()
    assert wait_until(lambda: children[0].poll() is not None, 10)
    QApplication.processEvents()
    assert s.WORD_LISTS_FIND_FAILED.format(why="") not in (main.bar_line.full() or "")   # a cancel is never a failure
    assert _bytes(path) == "冒険\n".encode("utf-8")


def test_hiding_the_text_mid_paste_kills_its_child_and_says_nothing(main, monkeypatch, children):
    monkeypatch.setattr(word_lists, "find_command", lambda: HANG)
    w = _open(main)
    w.paste_button.click()
    w.text.setPlainText("冒険の準備")
    w.find_button.click()
    assert wait_until(lambda: len(children) == 1, 30)
    assert w.status.text() == s.WORD_LISTS_FINDING
    w.paste_button.click()                                           # hidden
    assert wait_until(lambda: children[0].poll() is not None, 10)
    assert wait_until(lambda: w.status.text() == "", 10)
    assert w.candidates is None


def test_a_new_paste_kills_the_older_ones_child_and_shows_its_own_words(main, monkeypatch, children):
    with monkeypatch.context() as patched:      # scoped: an undo() would also undo the harness's test root
        patched.setattr(word_lists, "find_command", lambda: HANG)
        w = _open(main)
        w.paste_button.click()
        w.text.setPlainText("冒険の準備")
        w.find_button.click()
        assert wait_until(lambda: len(children) == 1, 30)
    # the real child again
    w.text.setPlainText("灯台の砂時計")
    w.find_button.click()
    assert wait_until(lambda: w.candidates is not None, 60)
    assert children[0].poll() is not None
    assert [c.word for c in w.candidates] == ["灯台", "砂時計"]
    assert not w.status.text().startswith(s.WORD_LISTS_FIND_FAILED.format(why=""))


# --- S4: an add or a ✕ touches its own rows ------------------------------------------------------------------------ #
def _real_list(ja_resources_dir, n):
    """`n` real words, one a line (KnownWord.json's first KNOWN dictForms), under the header a new list gets."""
    with open(os.path.join(ja_resources_dir, "KnownWord.json"), encoding="utf-8") as f:
        entries = json.load(f)["words"]
    words = list(dict.fromkeys(e["dictForm"].strip() for e in entries
                               if e.get("knownStatus") == "KNOWN" and str(e.get("dictForm") or "").strip()))[:n]
    return words, "# Add words to ignore here (one per line)\n" + "\n".join(words) + "\n"


def test_an_add_inserts_its_row_alone_before_the_known_words_rows(main, known_file, ja_resources_dir):
    words, text = _real_list(ja_resources_dir, 300)
    _put(text)
    w = _open(main)
    assert w.model.rowCount() == len(word_lists.read("ignore", "ja").entries) > 300   # the list + the known rows
    seen, paints = _signals(w), w.list_paints
    w.add_field.setText("冒険家")
    w.add_typed()
    assert wait_until(lambda: w.list_paints == paints + 1 and not w.busy(), 30)
    assert seen == {"inserted": [(300, 300)], "removed": [], "reset": 0}
    assert _model_rows(w) == [tuple(e) for e in word_lists.read("ignore", "ja").entries]
    assert _model_rows(w)[300] == ("冒険家", "list") and _model_rows(w)[301][1] == "known"


def test_a_cross_removes_its_row_alone(main, known_file, ja_resources_dir):
    words, text = _real_list(ja_resources_dir, 300)
    path = _put(text)
    w = _open(main)
    seen, paints = _signals(w), w.list_paints
    _click_mark(w, 1)
    assert wait_until(lambda: w.list_paints == paints + 1 and not w.busy(), 30)
    assert seen == {"inserted": [], "removed": [(1, 1)], "reset": 0}
    assert words[1] not in _bytes(path).decode("utf-8").splitlines()
    assert _model_rows(w) == [tuple(e) for e in word_lists.read("ignore", "ja").entries]


def test_a_list_or_language_switch_makes_every_row_again(main):
    _put("冒険\n毎日\n")
    _put("灯台\n", "blacklist")
    _put("东西\n", "blacklist", "zh")
    w = _open(main)
    seen = _signals(w)
    w.kind_buttons["blacklist"].click()
    assert wait_until(lambda: _model_rows(w) == [("灯台", "list")])
    assert seen["reset"] >= 1
    resets = seen["reset"]
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: w.language == "zh" and _model_rows(w) == [("东西", "list")])
    assert seen["reset"] > resets


@pytest.mark.parametrize("change", ["middle", "duplicates", "first", "last", "grow", "empty", "many", "refill"])
def test_a_read_that_changed_the_file_leaves_the_rows_exactly_the_files(main, ja_resources_dir, change):
    # A hand edit between two reads, of every shape: whatever the diff does, the rows end as the read's entries, in
    # order — rows touched one by one up to _REBUILD_OVER changed rows, every row made again past it.
    words, text = _real_list(ja_resources_dir, 400)
    _put(text)
    w = _open(main)
    old = [(word, "list") for word in words] + [("良い", "known")]
    w._show(w._asked, word_lists.Listing([word_lists.Entry(*e) for e in old]))
    new = {"middle": old[:150] + [("冒険", "list"), ("灯台", "list")] + old[153:],
           "duplicates": old[:10] + [old[3]] + old[10:20] + [old[3]] + old[21:],
           "first": [("冒険", "list")] + old[1:],
           "last": old[:-1],
           "grow": old + [("砂時計", "list")] * 3,
           "empty": [],
           "many": old[:100] + [(f"冒険{i}", "list") for i in range(150)] + old[250:],
           "refill": [("冒険", "list")]}[change]
    seen = _signals(w)
    w._show(w._asked, word_lists.Listing([word_lists.Entry(*e) for e in new]))
    assert _model_rows(w) == new
    assert w.entries == new
    assert (seen["reset"] == 1) == (change in ("many", "refill", "empty"))
    if change in ("middle", "first", "last"):
        assert len(seen["inserted"]) + len(seen["removed"]) <= 4


def test_a_search_still_filters_after_rows_are_inserted_and_removed(main):
    _put("冒険\n冒険家\n毎日\n")
    w = _open(main)
    w.search.setText("冒険")
    w.add_field.setText("冒険者")
    w.add_typed()
    assert wait_until(lambda: w.shown.rowCount() == 3 and not w.busy(), 30)
    assert w.count.text() == s.WORD_LISTS_COUNT_SHOWN.format(shown=3, n=4)
    w.remove("冒険家")
    assert wait_until(lambda: w.shown.rowCount() == 2 and not w.busy(), 30)
    assert [w.shown.index(i, 0).data(WORD) for i in range(2)] == ["冒険", "冒険者"]
