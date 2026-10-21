"""The wizard's words read whole (Sonic's first try of the 3.0 test build, 2026-10-21: on page 5 *Cards made for you*
Anki Miner's "no profile called Surasura" line and its steps were squeezed beside *Star it on GitHub* and *Check
again* into one line's height — the lines ran over each other, the first was cut at the right, the path was
unreadable). Tier: looks — behaviour tests, no mutants.

What a wrong answer would cost: a learner who can't read what to do next (the update, or the steps by hand and the
file to pick) and can't make cards; a path they can't copy whole.

Each scale (100 %, 250 %) runs in its own process (`QT_SCALE_FACTOR`, tests/qt/capture.py's way), at every text size,
at the window's least size and a laptop's, with the words Sonic saw and the words Anki Miner before 3.7 now gets.
Every label shown must have the height its words need at its width (no line cut or drawn over another), every button
its own width, and nothing may run past the page's right edge or over another label or button.
"""
import json
import os
import subprocess
import sys

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtWidgets import QAbstractButton, QApplication, QLabel

from app.qt import wizard as W
from app.qt import wizard_strings as S
from tests.qt.conftest import wait_until
from tests.qt.test_settings_connect import make as make_settings, miner_result, world  # noqa: F401  (world: fixture)
from tests.qt.test_wizard import FakeMiner, go_to, make, miner_look  # noqa: F401  (make: the wizard fixture)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PATH = r"C:\Users\Michael\AppData\Local\Houseki\Surasura\connect\whitelist-ja.txt"
# the fix exactly as Sonic saw it (3.0-dev 7d8cc74, Anki Miner 3.5)
SEEN = {"say": 'Anki Miner has no profile called "Surasura". Make it once in Anki Miner (a copy of your profile, its '
               "whitelist on), as Surasura's Connections page shows.",
        "do": "In Anki Miner: Manage profiles… → New, name it Surasura; then in its Settings, Whitelist → choose file: "
              + PATH}
# the fix Anki Miner before 3.7 gets now (app/connect/setup.py): the update first, the steps by hand after
BEFORE_37 = {"say": "Anki Miner 3.7 or newer needs no setup here. Update it and press Check again.",
             "do": "Or keep this Anki Miner and make its profile by hand: in Anki Miner, Manage profiles… → New, "
                   "name it Surasura; then in its Settings, Whitelist → choose file: " + PATH,
             "update": True}
# a footer line as long as the wizard says (a save that failed, with its file)
LONG_SAY = ("Your choices on this page couldn't be saved: [Errno 13] Permission denied: "
            r"'C:\Users\Michael\AppData\Roaming\SonicSandbox\Surasura\settings.json'")
WINDOWS = ((1000, 620), (1333, 860))           # the window's least size (theme.WINDOW_MIN); a 150 % laptop's


def fit_problems(wiz):
    """Every label and button shown on the page and in the footer: its words' needed size inside its own, inside the
    page's width, over no other. -> [problem, …]"""
    page = wiz.page
    problems = []
    shown = [w for w in page.findChildren(QLabel) + page.findChildren(QAbstractButton) + [wiz.say_line]
             if w.isVisibleTo(wiz) and (not isinstance(w, QLabel) or w.text())]
    rects = []
    for w in shown:
        what = f"{type(w).__name__}#{w.objectName()} {(w.text() if hasattr(w, 'text') else '')[:40]!r}"
        if isinstance(w, QLabel) and w.wordWrap():
            need = w.heightForWidth(w.width())
            if need > w.height():
                problems.append(f"{what}: needs {need} px high, has {w.height()}")
        else:
            hint = w.sizeHint()
            if hint.width() > w.width() or (isinstance(w, QLabel) and hint.height() > w.height()):
                problems.append(f"{what}: needs {hint.width()}x{hint.height()}, has {w.width()}x{w.height()}")
        if w is wiz.say_line:
            continue
        r = QRect(w.mapTo(page, QPoint(0, 0)), w.size())
        if r.right() > page.width():
            problems.append(f"{what}: runs {r.right() - page.width()} px past the page's right edge")
        rects.append((what, r))
    for i, (a, ra) in enumerate(rects):
        for b, rb in rects[i + 1:]:
            if ra.intersects(rb):
                problems.append(f"{a} overlaps {b}")
    return problems


def _child():
    """(In its own process, the scale set by the parent.) Page 5 at every text size, window and fix -> RESULT json."""
    import tempfile
    os.environ.setdefault("SURASURA_TEST_ROOT", tempfile.mkdtemp())
    app = QApplication(["wizard-text"])
    from app.qt import style, windows
    from tests.qt import test_wizard as T
    windows.launch = lambda *a, **k: None
    windows.open_url = lambda url: None
    windows.module_present = lambda name: True
    out, checked = [], 0
    for size in ("S", "M", "L"):
        style.apply(app, "night", size, "ja")
        for w, h in WINDOWS:
            for name, fix in (("seen", SEEN), ("before-3.7", BEFORE_37)):
                shell = T.FakeShell(T.FakeSettings({}))
                wiz = W.SetupWizard(shell, parent=shell.centralWidget(), api=T.FakeApi(),
                                    miner=T.FakeMiner(T.miner_look("needs-setup", "3.5.0", fix)))
                shell.centralWidget().layout().addWidget(wiz)
                shell.setFixedSize(w, h)                  # a real window never outgrows the screen
                shell.show()
                app.processEvents()
                T.go_to(wiz, "cards")
                T.wait_until(lambda: wiz.page.look is not None, 3.0)
                wiz.say(LONG_SAY)
                for _ in range(4):
                    app.processEvents()
                checked += 1
                out += [f"{size} {w}x{h} {name}: {p}" for p in fit_problems(wiz)]
                shell.close()
                shell.deleteLater()
                app.processEvents()
    print("RESULT " + json.dumps([out, checked, app.primaryScreen().devicePixelRatio()]))


@pytest.mark.parametrize("scale", ["1", "2.5"])
def test_page_five_reads_whole_at_100_and_250_percent_every_text_size_and_the_least_window(scale, tmp_path):
    env = dict(os.environ, QT_SCALE_FACTOR=scale, QT_QPA_PLATFORM="offscreen", SURASURA_FREEZE_MOTION="1",
               SURASURA_TEST_ROOT=str(tmp_path), PYTHONIOENCODING="utf-8")
    code = "from tests.qt.test_wizard_text import _child\n_child()\n"
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True,
                          encoding="utf-8", timeout=240)
    line = next((l for l in done.stdout.splitlines() if l.startswith("RESULT ")), None)
    assert line is not None, done.stdout[-2000:] + done.stderr[-4000:]
    problems, checked, dpr = json.loads(line[len("RESULT "):])
    assert abs(dpr - float(scale)) < 0.01
    assert checked == 12 and problems == []


# --- the words before 3.7, from 3.7 ------------------------------------------------------------------------------------ #
def test_before_37_the_update_leads_with_its_button_and_the_steps_by_hand_follow_with_the_path(make):
    wiz, *_ = make(miner=FakeMiner(miner_look("needs-setup", "3.6.0", BEFORE_37)))
    go_to(wiz, "cards")
    page = wiz.page
    assert wait_until(lambda: page.look is not None)
    assert page.name.text() == BEFORE_37["say"] and page.dot.state == "warn"
    assert not page.btn_install.isHidden() and page.btn_install.text() == S.UPDATE_MINER
    assert page.btn_install.toolTip() == S.UPDATE_MINER_TIP and not page.btn_check.isHidden()
    # the buttons come straight under the update line, before the steps by hand
    assert page.btn_install.mapTo(page, QPoint(0, 0)).y() < page.steps.mapTo(page, QPoint(0, 0)).y()
    assert page.sub.isHidden() and not page.steps.isHidden()
    assert page.steps.text().startswith("Or keep this Anki Miner") and page.steps.text().endswith("choose file:")
    assert not page.path.isHidden() and page.path.text().replace("\u200b", "") == PATH
    assert page.path_text == PATH and not page.btn_copy.isHidden()


def test_copy_path_copies_the_path_as_it_is_and_says_so(make):
    wiz, *_ = make(miner=FakeMiner(miner_look("needs-setup", "3.6.0", BEFORE_37)))
    go_to(wiz, "cards")
    page = wiz.page
    assert wait_until(lambda: page.look is not None)
    QApplication.clipboard().setText("")
    page.btn_copy.click()
    assert QApplication.clipboard().text() == PATH               # no break marks: Anki Miner's file chooser takes it
    assert wiz.say_line.text() == S.PATH_COPIED


def test_from_37_ready_shows_no_profile_line_no_update_and_no_path(make):
    wiz, *_ = make(miner=FakeMiner(miner_look("ready", "3.10.0")))
    go_to(wiz, "cards")
    page = wiz.page
    assert wait_until(lambda: page.look is not None)
    assert page.name.text() == S.MINER_READY and "profile" not in page.sub.text()
    assert page.btn_install.isHidden() and page.steps.isHidden() and page.path.isHidden() and page.btn_copy.isHidden()
    assert not page.make.isHidden() and not page.rec.isHidden()


def test_a_fix_without_the_update_mark_keeps_its_steps_under_its_sentence_and_offers_no_update(make):
    fix = {"say": "Anki Miner's own setup isn't finished (its note type).",
           "do": "In Anki Miner: Settings → finish the setup"}
    wiz, *_ = make(miner=FakeMiner(miner_look("needs-setup", "3.7.0", fix)))
    go_to(wiz, "cards")
    page = wiz.page
    assert wait_until(lambda: page.look is not None)
    assert page.sub.text() == fix["do"] and page.steps.isHidden() and page.path.isHidden()
    assert page.btn_install.isHidden() and not page.btn_check.isHidden()


@pytest.mark.parametrize("text, words, path", [
    ("…Whitelist → choose file: " + PATH, "…Whitelist → choose file:", PATH),
    (r"choose file: D:\Anki Miner\Surasura lists\whitelist-zh.txt", "choose file:",
     r"D:\Anki Miner\Surasura lists\whitelist-zh.txt"),                      # a path with spaces, whole
    ("Open Anki Miner and finish its setup", "Open Anki Miner and finish its setup", ""),
    ("", "", ""),
    (None, "", ""),
])
def test_a_path_ending_a_fix_goes_on_its_own_line(text, words, path):
    assert W._split_path(text) == (words, path)


# --- Settings' Anki Miner card: the same squeeze ----------------------------------------------------------------------- #
@pytest.mark.parametrize("state", ["missing", "setup"])
def test_settings_anki_miner_card_never_squeezes_a_button_they_wrap_inside_the_card(world, state):
    # its buttons (Install, the star line, Browse…, Check again; the ⭐ suggestion and Not now) were one row wider than
    # the card: each was cut to a quarter of the card. They wrap now, each at its own width, inside the card.
    world.miner = miner_result(state)
    page, _store, rows, _fake = make_settings(world)
    page.resize(1333, 860)
    for _ in range(4):
        QApplication.processEvents()
    card = rows.miner
    buttons = [b for b in card.findChildren(QAbstractButton) if b.isVisibleTo(page)]
    assert len(buttons) >= 2
    for b in buttons:
        assert b.width() >= min(b.sizeHint().width(), card.width()), (b.text(), b.width(), b.sizeHint().width())
    placed = [QRect(b.mapTo(card, QPoint(0, 0)), b.size()) for b in buttons]
    for i, r in enumerate(placed):
        assert all(not r.intersects(o) for o in placed[i + 1:]), buttons[i].text()
