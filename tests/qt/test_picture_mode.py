"""Report a problem's picture mode (`app/qt/report.py` `PictureMode`, `take_pictures`; Send report SR-2,
`tracks/ship/work/send-report/SPEC.md` §2.4): while a window's picture is taken, every name and path it shows is drawn
scrubbed, and everything is put back after.

What a wrong answer would cost: a picture that draws the tester's Windows name or home folder (C:\\Users\\Zoë…) — the
line under Send report ("No personal data or identification is included") made untrue in pixels; half a name left by a
label that shortened the path first (C:\\Users\\Zoë Ta…); a field left changed after the picture, a search or a setting
fired by its `textChanged`, the cursor jumped, the undo history lost; a crash mid-grab that leaves the window showing
<you>; a painter added later that draws a path straight past the scrub (the audits below fail on one).
"""
import ast
import os
import pathlib

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QComboBox, QLabel, QLineEdit, QListWidget, QPlainTextEdit, QPushButton, QStyledItemDelegate,
                             QWidget)

from app import scrub
from app.qt import report as report_ui
from app.qt import settings_controls as sc
from app.qt import settings_rules, shell, windows
from tests import scrub_probe as probe_person

QT_DIR = pathlib.Path(report_ui.__file__).parent


@pytest.fixture
def main(qapp):
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.show()
    yield win
    win.close()
    services.shutdown(0.5)


@pytest.fixture
def person(tmp_path, monkeypatch):
    """The probe person (Zoë Tanaka-Probe on DESKTOP-PROBE7, Anki profile *Probe Anki*), their Identity ready."""
    p = probe_person.make(tmp_path, monkeypatch)
    scrub.identity()
    yield p
    scrub.reset()


def _names_in(text, person):
    """Any identifying string (or its first four letters, the most a shortened label could leave) in `text`."""
    probes = [probe_person.FOLDER, probe_person.FOLDER[:4], probe_person.ACCOUNT, probe_person.MACHINE,
              probe_person.PROFILE, probe_person.ORG]
    return [s for s in probes if s.casefold() in (text or "").casefold()]


def _settings_like(main, person):
    """A Surasura window showing what Settings, the Content Manager and Connect show: a data folder, a video folder,
    an Anki Miner path in a field (typed, with its own undo history), a log, Anki's profile in a drop-down and a
    button, a list of folders, a narrow label that shortens a home path, and Connect's status mark."""
    other = windows.SecondaryWindow(main, "Settings")
    home = person.home
    w = {"label": QLabel(f"Your data lives in {home}\\AppData\\Roaming\\Surasura", other)}
    w["field"] = QLineEdit(other)
    w["field"].insert(f"{home}\\Tools\\Anki Miner\\anki_miner.exe")     # typed: the field's own undo history
    w["field"].setCursorPosition(5)
    w["log"] = QPlainTextEdit(other)
    w["log"].insertPlainText(f'Traceback (most recent call last):\n  File "{home}\\AppData\\Local\\Surasura\\app.py"\n')
    w["combo"] = QComboBox(other)
    w["combo"].addItems(["User 1", probe_person.PROFILE])
    w["combo"].setCurrentIndex(1)
    w["button"] = QPushButton(f"Use {probe_person.PROFILE}", other)
    w["list"] = QListWidget(other)
    w["list"].addItems([f"{home}\\Videos\\葬送のフリーレン", "D:\\Anime\\薬屋のひとりごと"])
    w["narrow"] = report_ui.ElidedLabel(f"{home}\\Videos\\葬送のフリーレン\\第01話.srt", other)
    w["mark"] = sc.StatusMark(True, f"Anki is open on the profile {probe_person.PROFILE}", parent=other)
    w["anime"] = QLabel("葬送のフリーレン 第01話", other)                   # a title: stays
    w["folders"] = sc.Tablets(value=[f"{home}\\Videos\\アニメ", "D:\\Anime"], parent=other)   # Connect's video folders
    for x in w.values():
        other.body.addWidget(x)
    other.resize(700, 600)
    other.show()
    w["narrow"].setFixedWidth(140)
    return other, w


def _during_grab(monkeypatch, window, look):
    """`look()` called while `window` is grabbed (picture mode is on then)."""
    seen = []
    real = QWidget.grab

    def watch(self, *a):
        if self is window:
            seen.append(look())
        return real(self, *a)
    monkeypatch.setattr(QWidget, "grab", watch)
    return seen


def _shown_words(window, w):
    """What each part shows during the grab: a label's / button's text, a field's stand-in, the list's delegate."""
    standins = [x for x in window.findChildren((QLineEdit, QPlainTextEdit, QComboBox))
                if x.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) and x.isVisible()]
    out = {"label": w["label"].text(), "button": w["button"].text(), "narrow": w["narrow"].text(),
           "anime": w["anime"].text(), "mark": scrub.shown(w["mark"].words()),
           "standins": [x.text() if isinstance(x, QLineEdit) else x.toPlainText() if isinstance(x, QPlainTextEdit)
                        else x.currentText() for x in standins],
           "delegate": type(w["list"].itemDelegate()).__name__}
    opt_text = []
    d = w["list"].itemDelegate()
    if isinstance(d, report_ui._ShownItems):
        from PyQt6.QtWidgets import QStyleOptionViewItem
        for row in range(w["list"].count()):
            opt = QStyleOptionViewItem()
            d.initStyleOption(opt, w["list"].model().index(row, 0))
            opt_text.append(opt.text)
    out["items"] = opt_text
    return out


# --- in the picture: nothing names you ------------------------------------------------------------------------- #
def test_every_name_and_path_is_drawn_scrubbed_while_the_picture_is_taken(main, person, monkeypatch):
    other, w = _settings_like(main, person)
    try:
        seen = _during_grab(monkeypatch, other, lambda: _shown_words(other, w))
        pictures, scrubbed = report_ui.take_pictures(main)
        assert scrubbed and len(pictures) == 2 and len(seen) == 1
        got = seen[0]
        for key in ("label", "button", "narrow", "mark"):
            assert _names_in(got[key], person) == [], (key, got[key])
        assert "<you>" in got["label"] and got["button"] == "Use <anki profile 1>"
        assert len(got["standins"]) == 3                                # the field, the log, the drop-down
        assert all(_names_in(t, person) == [] for t in got["standins"])
        assert got["delegate"] == "_ShownItems" and len(got["items"]) == 2
        assert all(_names_in(t, person) == [] for t in got["items"]) and "<you>" in got["items"][0]
        assert got["items"][1] == "D:\\Anime\\薬屋のひとりごと"            # a folder off home: a title, kept
        assert got["anime"] == "葬送のフリーレン 第01話"                   # titles stay (Sonic's call)
        stands = [x for x in other.findChildren(QWidget)
                  if x.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) and x.isVisible()]
        assert stands == []                                            # (gone after; their place checked below)
    finally:
        other.close()


def test_painted_words_reach_the_painter_scrubbed_a_folder_list_included(main, person, monkeypatch):
    # The adversary's 3: Settings' folder list (Connect's video folders) draws each folder as a tablet; every word a
    # painter draws during the grab is caught here, and none holds the probe person.
    from PyQt6.QtGui import QPainter
    other, w = _settings_like(main, person)
    try:
        drawn, real = [], QPainter.drawText

        def spy(self, *a):
            drawn.append(str(a[-1]))
            return real(self, *a)
        monkeypatch.setattr(QPainter, "drawText", spy)
        report_ui.take_pictures(main)
        assert any("<you>" in d for d in drawn) and "D:\\Anime" in drawn            # the folders were painted
        assert [d for d in drawn if _names_in(d, person)] == []
    finally:
        other.close()


def test_each_stand_in_lies_exactly_over_its_field_and_on_top(main, person, monkeypatch):
    other, w = _settings_like(main, person)
    try:
        def placed():
            out = []
            for field in (w["field"], w["log"], w["combo"]):
                kin = [x for x in field.parentWidget().children() if isinstance(x, QWidget)]
                stand = [x for x in kin if x is not field
                         and x.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                         and x.geometry() == field.geometry() and x.isVisible()]
                out.append(bool(stand) and kin.index(stand[0]) > kin.index(field))     # raised: drawn after it
            return out
        seen = _during_grab(monkeypatch, other, placed)
        report_ui.take_pictures(main)
        assert seen == [[True, True, True]]
    finally:
        other.close()


def test_afterwards_every_part_is_as_it_was_with_no_signal_cursor_or_undo_lost(main, person, monkeypatch):
    other, w = _settings_like(main, person)
    try:
        before = {"label": w["label"].text(), "field": w["field"].text(), "log": w["log"].toPlainText(),
                  "combo": w["combo"].currentText(), "button": w["button"].text(), "narrow": w["narrow"].text(),
                  "item": w["list"].item(0).text()}
        delegate = w["list"].itemDelegate()
        fired = []
        w["field"].textChanged.connect(lambda t: fired.append(("field", t)))
        w["log"].textChanged.connect(lambda: fired.append("log"))
        w["log"].document().contentsChanged.connect(lambda: fired.append("doc"))
        w["combo"].currentTextChanged.connect(lambda t: fired.append(("combo", t)))
        log_doc = w["log"].document()
        report_ui.take_pictures(main)
        after = {"label": w["label"].text(), "field": w["field"].text(), "log": w["log"].toPlainText(),
                 "combo": w["combo"].currentText(), "button": w["button"].text(), "narrow": w["narrow"].text(),
                 "item": w["list"].item(0).text()}
        assert after == before and fired == []
        assert w["field"].cursorPosition() == 5 and w["field"].isUndoAvailable()
        assert w["log"].document() is log_doc and log_doc.isUndoAvailable()
        assert w["list"].itemDelegate() is delegate
        stray = [x for x in other.findChildren(QWidget)
                 if x.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) and x.isVisible()]
        assert stray == []                                             # every stand-in gone
        w["field"].undo()                                              # the history is the tester's own
        assert w["field"].text() == ""
    finally:
        other.close()


def test_a_grab_that_fails_still_puts_everything_back(main, person, monkeypatch):
    other, w = _settings_like(main, person)
    try:
        label, button = w["label"].text(), w["button"].text()

        def broken(self, *a):
            raise RuntimeError("the window went away mid-grab")
        monkeypatch.setattr(QWidget, "grab", broken)
        pictures, _scrubbed = report_ui.take_pictures(main)
        assert pictures == []
        assert w["label"].text() == label and w["button"].text() == button
        assert scrub.shown(f"{person.home}\\x") == f"{person.home}\\x"      # picture mode is off again
        assert type(w["list"].itemDelegate()) is QStyledItemDelegate
    finally:
        other.close()


def test_before_the_identity_is_ready_nothing_is_changed_and_the_picture_is_not_marked(main, person, monkeypatch):
    other, w = _settings_like(main, person)
    try:
        scrub.reset()                                                  # not worked out yet
        seen = _during_grab(monkeypatch, other, lambda: (w["label"].text(), type(w["list"].itemDelegate())))
        pictures, scrubbed = report_ui.take_pictures(main)
        assert not scrubbed and len(pictures) == 2
        assert seen[0][0].startswith("Your data lives in " + person.home) and seen[0][1] is QStyledItemDelegate
    finally:
        other.close()


def test_a_shortened_label_scrubs_its_whole_text_before_it_cuts(main, person, monkeypatch):
    """Cut first, then scrubbed, `C:\\…\\Users\\Zoë Ta…` would leave half the name: each label that shortens its text
    fits it again from the whole text, scrubbed (the report's rows, a source's *From …*, the bar's line)."""
    other = windows.SecondaryWindow(main, "Content")
    path = f"{person.home}\\Videos\\薬屋のひとりごと\\第02話.ass"
    labels = [report_ui.ElidedLabel(path, other), settings_rules._SourceWords(path, other), shell.ElidingLabel(other)]
    labels[2].set_full(path)
    cut_at = len(person.home) - len(probe_person.FOLDER) + 6            # its room ends inside the name
    modes = [Qt.TextElideMode.ElideRight, Qt.TextElideMode.ElideMiddle, Qt.TextElideMode.ElideRight]
    for x, mode in zip(labels, modes):
        other.body.addWidget(x)
        fm = x.fontMetrics()
        room = fm.horizontalAdvance(path[:cut_at] + "…") + 2
        if mode == Qt.TextElideMode.ElideMiddle:
            room = fm.horizontalAdvance(path[:cut_at] + "…" + path[-cut_at:]) + 2
        x.setFixedWidth(room)
    other.show()
    try:
        own = [x.text() for x in labels]
        assert any(_names_in(t, person) for t in own)                   # cut, the name shows in part: the case
        seen = _during_grab(monkeypatch, other, lambda: [x.text() for x in labels])
        report_ui.take_pictures(main)
        assert all(_names_in(t, person) == [] for t in seen[0]), seen[0]
        assert [x.text() for x in labels] == own                        # back to the whole path's own cut
    finally:
        other.close()


def test_the_report_window_itself_is_never_pictured(main, person):
    main.report_button.click()
    try:
        assert all(not isinstance(x, report_ui.ReportWindow) for x in report_ui.surasura_windows(main))
    finally:
        w = windows.opened(main, report_ui.NAME)
        if w is not None:
            w.close()


def test_the_bug_press_with_picture_mode_stays_quick(main, person):
    """The key case's guard (the timed run measures it on its slot): a press with Settings-like windows open stays
    well inside a frame budget's order — picture mode is a walk of the visible widgets, never a read of a file."""
    import time
    other, _w = _settings_like(main, person)
    try:
        report_ui.take_pictures(main)                                  # warm (fonts, the matcher)
        t = time.perf_counter()
        for _ in range(5):
            report_ui.take_pictures(main)
        assert (time.perf_counter() - t) / 5 < 0.5
    finally:
        other.close()


# --- the audits: every painter and every shortened text reads through the scrub -------------------------------- #
# Every `drawText` / `drawStaticText` in app/qt whose text isn't `scrub.shown(...)` itself, with why it can't draw a
# name or a path (or where it was scrubbed first). A new painter fails here until it is one or the other.
DRAWN = {
    ("frame.py", "KnownCorner.paintEvent", "number"): "a count",
    ("frame.py", "KnownCorner.paintEvent", "word"): "the word 'known'",
    ("needs.py", "paint_stone", "text"): "a count on its stone",
    ("phase_strip.py", "PhaseStrip._paint_circle", "strings.PHASE_MARKS[circle]"): "a constant mark",
    ("report.py", "BugButton.paintEvent", "str(self.count)"): "a count",
    ("rows.py", "Text.draw", "st"): "made by Text.static, which scrubs the whole text before it cuts",
    ("rows.py", "cover", "text"): "cover_label of the title, scrubbed at the top of cover()",
    ("rows.py", "cover", "ch"): "a character of that scrubbed title",
    ("search.py", "HitRow.paintEvent", "text"): "the parts of the title, scrubbed (`whole`) before it is cut",
    ("settings_controls.py", "paint_tick", "TICK"): "a constant mark",
    ("settings_controls.py", "Tablets.paintEvent", "CROSS"): "a constant mark",
    ("settings_controls.py", "LevelSlider.paintEvent", "name"): "a band's name",
    ("shell.py", "Wordmark.paintEvent", "first"): "the wordmark",
    ("shell.py", "Wordmark.paintEvent", "second"): "the wordmark",
    ("shell.py", "TabButton.paintEvent", "self.name"): "a tab's name",
    ("shell.py", "TabButton.paintEvent", "text"): "a tab's count",
    ("sort_screen.py", "_FadeLine.paintEvent", "self.text()"): "a QLabel's own text: picture mode swaps it",
    ("tool_icons.py", "ToolIcon.paintEvent", "self.mark"): "a tool's constant mark, else its window's name's letter",
    ("wizard.py", "StepList.paintEvent", "mark"): "a step's mark",
    ("wizard.py", "StepList.paintEvent", "S.STEPS[pid]"): "a step's name",
    ("wizard.py", "Choice.paintEvent", "title"): "scrub.shown(self.title) just above",
    ("wizard.py", "Choice.paintEvent", "S.RECOMMENDED"): "a constant",
    ("wizard.py", "GlyphChoice.paintEvent", "self.glyph"): "a glyph",
    ("wizard.py", "GlyphChoice.paintEvent", "self.title"): "a channel's name (a constant)",
    ("wizard.py", "DeckChip.paintEvent", '"✓"'): "a constant mark",
    ("wizard.py", "DeckChip.paintEvent", "name"): "cut from scrub.shown(self.name)",
    ("wizard.py", "DeckChip.paintEvent", "S.DECK_CARDS.format(n=self.count or 0)"): "a count",
    ("wizard.py", "Dot.paintEvent", "self.name"): "a step dot's name (a constant)",
    ("wizard.py", "FadedSentence.paintEvent", "word"): "the sample sentence's words",
    ("wizard.py", "CardsPicture.paintEvent", "name"): "the sample picture's words",
    ("wizard.py", "CardsPicture.paintEvent", "word"): "the sample picture's words",
    ("wizard.py", "CardsPicture.paintEvent", "S.ORDER_EPISODE.format(n=S.ORDER_EPISODES[i])"): "a sample",
    ("wizard.py", "MinePicture.paintEvent", "line"): "the sample picture's words",
    ("wizard.py", "MinePicture.paintEvent", '"→"'): "a constant mark",
    ("wizard.py", "MinePicture.paintEvent", "reading"): "the sample picture's words",
    ("wizard.py", "MinePicture.paintEvent", "word"): "the sample picture's words",
    ("wizard.py", "CoversPicture.paintEvent", '"→"'): "a constant mark",
    ("wizard.py", "LevelSlider.paintEvent", "name"): "a band's name",
    ("wizard.py", "LevelSlider.paintEvent", "S.SLIDER_LOW"): "a constant",
    ("wizard.py", "LevelSlider.paintEvent", "S.SLIDER_HIGH"): "a constant",
    ("wizard.py", "_Tile.paintEvent", "self.title[:1]"): "one letter names no one",
    ("word_lists_window.py", "_RemoveDelegate.paint", "s.WORD_LISTS_REMOVE_MARK"): "a constant mark",
}
# Every `elidedText` in app/qt that doesn't cut `scrub.shown(...)`, with why.
CUT = {
    ("rows.py", "cover_label", "t"): "the title cover() scrubbed first",
    ("rows.py", "Text.static", "text"): "scrub.shown(text) at the top of static()",
    ("search.py", "HitRow.paintEvent", "whole"): "scrub.shown(self.hit.title) just above",
}


def _calls(attrs):
    """(file, Class.function, the text argument's source) of every call to one of `attrs` in app/qt."""
    out = []
    for path in sorted(QT_DIR.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        stack = []

        class Walk(ast.NodeVisitor):
            def _scope(self, n):
                stack.append(n.name)
                self.generic_visit(n)
                stack.pop()
            visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _scope

            def visit_Call(self, n):
                f = n.func
                if isinstance(f, ast.Attribute) and f.attr in attrs and n.args:
                    arg = n.args[-1] if f.attr != "elidedText" else n.args[0]
                    out.append((path.name, ".".join(stack), ast.get_source_segment(src, arg)))
                self.generic_visit(n)
        Walk().visit(ast.parse(src))
    return out


def _scrubbed(segment):
    return segment.startswith(("scrub.shown(", "shown(")) or ".elidedText(scrub.shown(" in segment


def test_every_painter_in_the_window_draws_its_text_through_the_scrub_or_says_why_it_needs_none():
    found = _calls({"drawText", "drawStaticText"})
    assert len(found) >= 50                                            # (the audit sees them all)
    unlisted = [c for c in found if not _scrubbed(c[2]) and c not in DRAWN]
    assert unlisted == [], "a painter draws text past the scrub: read it through scrub.shown, or list why it can't " \
                           f"name anyone: {unlisted}"
    assert [k for k in DRAWN if k not in found] == []                  # (no stale line)


def test_every_shortened_text_in_the_window_is_scrubbed_before_it_is_cut():
    found = _calls({"elidedText"})
    unlisted = [c for c in found if not _scrubbed(c[2]) and c not in CUT]
    assert unlisted == [], f"a text is cut before it is scrubbed (half a name would show): {unlisted}"
    assert [k for k in CUT if k not in found] == []


def test_every_delegate_of_its_own_reads_its_words_through_the_scrub():
    """Qt's own delegate is swapped for `_ShownItems` during a picture; a delegate of the window's own can't be, so it
    paints through rows' text cache (which scrubs) or scrubs its `initStyleOption`."""
    own = {}
    for path in sorted(QT_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.ClassDef) and any(getattr(b, "id", "") in ("QStyledItemDelegate", "QItemDelegate")
                                                   for b in n.bases):
                own[(path.name, n.name)] = ast.get_source_segment(path.read_text(encoding="utf-8"), n)
    assert set(own) >= {("rows.py", "RowDelegate"), ("arrivals.py", "TrayDelegate"),
                        ("word_lists_window.py", "_RemoveDelegate"), ("report.py", "_ShownItems")}
    for (name, cls), src in own.items():
        through = ("TEXT.draw" in src or "paint_row(" in src or "scrub.shown(option.text)" in src
                   or "self.ident.scrub(option.text)" in src)
        assert through, f"{name} {cls}: its words reach the picture unscrubbed"
