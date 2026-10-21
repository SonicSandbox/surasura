"""The wizard's words read whole (Sonic's first try of the 3.0 test build, 2026-10-21: on page 5 *Cards made for you*
Anki Miner's "no profile called Surasura" line and its steps were squeezed beside *Star it on GitHub* and *Check
again* into one line's height — the lines ran over each other, the first was cut at the right, the path was
unreadable). Tier: looks — behaviour tests, no mutants.

What a wrong answer would cost: a learner who can't read what to do next (the update, or the steps by hand and the
file to pick) and can't make cards; a path they can't copy whole; a switch or a choice cut off at the page's edge.

**Every page, every text size, the window's least size and a laptop's**, each scale in its own process. Every label
shown must have the height its words need at its width (no line cut or drawn over another), every button its own
width, and nothing may run past the visible area's right edge (the page scrolls only up and down) or over another
label or button. The process runs on Qt's offscreen platform, whose fonts measure wider than Windows' (a title ~1.6×):
what fits there fits on Windows. `QT_SCALE_FACTOR` (100 %, 250 %) changes the device pixels only — a page's logical
room is the window's, so the least window at Large text is the narrowest room the page gets (a 250 % screen too small
for the least window is the window's own minimum, not a page's).
"""
import json
import os
import subprocess
import sys

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtWidgets import QAbstractButton, QApplication, QLabel, QPushButton

from app.qt import wizard as W
from app.qt import wizard_strings as S
from tests.qt.conftest import wait_until
from tests.qt.test_settings_connect import make as make_settings, miner_result, world  # noqa: F401  (world: fixture)
from tests.qt.test_wizard import FakeMiner, go_to, make, miner_look  # noqa: F401  (make: the wizard fixture)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PATH = r"C:\Users\Michael\AppData\Local\Houseki\Surasura\connect\whitelist-ja.txt"
STEPS = "In Anki Miner: Manage profiles… → New, name it Surasura; then in its Settings, Whitelist → choose file: " + PATH
# the fix exactly as Sonic saw it (3.0-dev 7d8cc74, Anki Miner 3.5)
SEEN = {"say": 'Anki Miner has no profile called "Surasura". Make it once in Anki Miner (a copy of your profile, its '
               "whitelist on), as Surasura's Connections page shows.", "do": STEPS}
# the same check as app/connect/setup.py gives it now before 3.7: marked `update` (the wizard leads with the update)
BEFORE_37 = dict(SEEN, update=True)
# a footer line as long as the wizard says (a save that failed, with its file)
LONG_SAY = ("Your choices on this page couldn't be saved: [Errno 13] Permission denied: "
            r"'C:\Users\Michael\AppData\Roaming\SonicSandbox\Surasura\settings.json'")
WINDOWS = ((1000, 620), (1333, 860))           # the window's least size (theme.WINDOW_MIN); a 150 % laptop's
# what a learner's own names look like at their longest: a nested deck, a show's folder deep on a drive
DECKS = [("日本語::Mining::Anime::Sentence cards from subtitles", 2140), ("Core 2k/6k Optimized Japanese Vocabulary",
                                                                      1980), ("Kanji Practice", 610),
         ("日本語::Mining::Anime::2024 Fall season::Sentence cards with audio and pictures from every episode", 88)]
ROWS = [{"name": "星空ダイナー", "count": 12, "folder": r"E:\Anime\Shows I'm watching\Hoshizora Diner (2024) [1080p]",
         "kind": "shows"},
        {"name": "夜の図書館", "count": 1, "folder": r"E:\Books\Light novels\yoru-no-toshokan-vol-1.epub",
         "kind": "reading"}]


def fit_problems(wiz):
    """Every label and button shown on the page and in the footer: its words' needed size inside its own, inside the
    visible area's width, over no other. -> [problem, …]"""
    page = wiz.page
    view = page.parentWidget()                    # the scroll area's viewport: what can be seen across
    problems = []
    if page.width() > view.width():
        problems.append(f"the page is {page.width()} px wide in a view {view.width()} px wide")
    shown = [w for w in page.findChildren(QLabel) + page.findChildren(QAbstractButton) + [wiz.say_line]
             if w.isVisibleTo(wiz) and (not isinstance(w, QLabel) or w.text())]
    rects = []
    for w in shown:
        what = f"{type(w).__name__}#{w.objectName()} {(w.text() if hasattr(w, 'text') else '')[:40]!r}"
        if isinstance(w, QLabel) and w.wordWrap():
            need = w.heightForWidth(w.width())
            if need > w.height():
                problems.append(f"{what}: needs {need} px high, has {w.height()}")
        elif isinstance(w, W.Choice):                 # a painted choice: the width its words are drawn in
            need = w.needed_width() if hasattr(w, "needed_width") else 0
            if need > w.width():
                problems.append(f"{what}: its words need {need} px, it has {w.width()}")
        elif isinstance(w, (QLabel, QPushButton)):    # (a switch draws to its own size)
            hint = w.sizeHint()
            if hint.width() > w.width() or (isinstance(w, QLabel) and hint.height() > w.height()):
                problems.append(f"{what}: needs {hint.width()}x{hint.height()}, has {w.width()}x{w.height()}")
        if w is wiz.say_line:
            continue
        r = QRect(w.mapTo(view, QPoint(0, 0)), w.size())
        if r.right() >= view.width():
            problems.append(f"{what}: runs {r.right() + 1 - view.width()} px past the view's right edge")
        if w.parentWidget() is not None and isinstance(w.parentWidget(), QAbstractButton):
            continue                                  # (a button's own words)
        rects.append((what, r))
    for i, (a, ra) in enumerate(rects):
        for b, rb in rects[i + 1:]:
            if ra.intersects(rb):
                problems.append(f"{a} overlaps {b}")
    return problems


def _child():
    """(In its own process, the scale set by the parent.) Every page at every text size and window, page 5 with each
    fix -> RESULT json."""
    import tempfile
    from PyQt6.QtCore import Qt
    os.environ.setdefault("SURASURA_TEST_ROOT", tempfile.mkdtemp())
    os.environ["QT_QPA_PLATFORM"] = "windows"         # (tests/qt/conftest.py, imported above, set offscreen)
    import ctypes                                     # Windows' scale stood in for over this desktop's own
    ctypes.windll.shcore.SetProcessDpiAwareness(2)    # (tests/qt/capture.py's way: 150 % on a 150 % desktop is 1)
    system = ctypes.windll.user32.GetDpiForSystem() / 96.0
    os.environ["QT_SCALE_FACTOR"] = f"{float(os.environ['WIZARD_TEXT_SCALE']) / system:.6f}"
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
                anki = {"open": True, "say": None, "decks": list(DECKS), "preselected": [DECKS[0][0]]}
                shell = T.FakeShell(T.FakeSettings({}))
                wiz = W.SetupWizard(shell, parent=shell.centralWidget(),
                                    api=T.FakeApi(anki=anki, rows=ROWS, numbers=T.NUMBERS),
                                    miner=T.FakeMiner(T.miner_look("needs-setup", "3.5.0", fix)))
                shell.centralWidget().layout().addWidget(wiz)
                shell.setFixedSize(w, h)                  # a real window never outgrows the screen
                shell.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)      # (Windows' own platform: never shown)
                shell.show()
                app.processEvents()
                wiz.say(LONG_SAY)
                for pid in W.PAGES:
                    if name == "before-3.7" and pid != "cards":
                        continue                          # (the other pages don't read the fix)
                    T.go_to(wiz, pid)
                    wiz.page.entered()
                    T.wait_until(lambda: not wiz._anki_looking, 2.0)
                    if pid == "cards":
                        T.wait_until(lambda: wiz.page.look is not None, 3.0)
                    if pid == "shows":
                        T.wait_until(lambda: getattr(wiz.page, "row_paints", 1) >= 1, 3.0)
                    wiz.say(LONG_SAY)
                    for _ in range(4):
                        app.processEvents()
                    checked += 1
                    out += [f"{size} {w}x{h} {pid} {name}: {p}" for p in fit_problems(wiz)]
                shell.close()
                shell.deleteLater()
                app.processEvents()
    from app.qt import bridge                         # (page 5's switch saved on starts Connect's marks on a worker:
    bridge.wait_for_workers(5000)                     # one still running as the process ends crashes it, as at quit)
    print("RESULT " + json.dumps([out, checked, app.primaryScreen().devicePixelRatio()]), flush=True)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' own fonts and scaling (the app's platform)")
@pytest.mark.parametrize("scale", ["1", "2.5"])
def test_every_page_reads_whole_at_100_and_250_percent_every_text_size_and_the_least_window(scale, tmp_path):
    env = dict(os.environ, WIZARD_TEXT_SCALE=scale, QT_QPA_PLATFORM="windows", SURASURA_FREEZE_MOTION="1",
               SURASURA_TEST_ROOT=str(tmp_path), PYTHONIOENCODING="utf-8")
    code = "from tests.qt.test_wizard_text import _child\n_child()\n"
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True,
                          encoding="utf-8", timeout=300)
    line = next((l for l in done.stdout.splitlines() if l.startswith("RESULT ")), None)
    assert line is not None, done.stdout[-2000:] + done.stderr[-4000:]
    problems, checked, dpr = json.loads(line[len("RESULT "):])
    assert abs(dpr - float(scale)) < 0.01
    assert checked == 3 * 2 * (len(W.PAGES) + 1) and problems == [], "\n".join(problems[:40])


# --- the words before 3.7, from 3.7 ------------------------------------------------------------------------------------ #
def test_before_37_the_update_leads_with_its_button_and_the_steps_by_hand_follow_with_the_path(make):
    wiz, *_ = make(miner=FakeMiner(miner_look("needs-setup", "3.6.0", BEFORE_37)))
    go_to(wiz, "cards")
    page = wiz.page
    assert wait_until(lambda: page.look is not None)
    assert page.name.text() == S.MINER_UPDATE_FIRST and page.dot.state == "warn"
    assert not page.btn_install.isHidden() and page.btn_install.text() == S.UPDATE_MINER
    assert page.btn_install.toolTip() == S.UPDATE_MINER_TIP and not page.btn_check.isHidden()
    # the buttons come straight under the update line, before the steps by hand
    assert page.btn_install.mapTo(page, QPoint(0, 0)).y() < page.steps.mapTo(page, QPoint(0, 0)).y()
    assert page.sub.isHidden() and not page.steps.isHidden()
    assert page.steps.text().startswith(S.MINER_BY_HAND + chr(10)) and page.steps.text().endswith("choose file:")
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
        assert r.right() < card.width(), (buttons[i].text(), "runs past the card")
