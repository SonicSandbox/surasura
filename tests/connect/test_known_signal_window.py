"""The Known-from-Anki window (P2.4 row K4): what the user sees after Surasura marks words known from Anki.

What a wrong answer would cost: a window that opens with nothing to say (a stray pop-up on every launch), one that
ignores Esc (a window the keyboard can't dismiss), Undo buttons without their tooltips (a button the user can't learn
the meaning of), or a pending offer that never offers its two choices. The window is built on a withdrawn Tk root
that the fixture destroys; no Anki is reached, and marks and offers are passed in directly.
"""
import tkinter as tk
from tkinter import ttk

import pytest

from app.connect import known_signal, known_signal_window

URL = "http://127.0.0.1:8765"

# Two words the user really meets in Japanese text, as known_signal.read records them.
MARKED = [
    {"word": "上層部", "card": 11, "note": 21, "at": "2026-10-08T15:00:00"},
    {"word": "一生懸命", "card": 12, "note": 22, "at": "2026-10-08T15:00:00"},
]


class Tips(list):
    """Stands in for the app's ToolTip: records every (widget, text) call the window makes."""

    def __call__(self, widget, text):
        self.append((widget, text))


@pytest.fixture
def root():
    r = tk.Tk()
    r.withdraw()
    try:
        yield r
    finally:
        r.destroy()  # tears down every window the test opened, even when an assertion failed


def _buttons(widget):
    """Every ttk.Button under a widget, however deep it sits in the window's frames."""
    found = []
    for child in widget.winfo_children():
        if isinstance(child, ttk.Button):
            found.append(child)
        found.extend(_buttons(child))
    return found


def test_no_marked_words_and_no_offer_opens_no_window(root):
    # Why: on a launch with nothing marked and no pending offer, the user must see nothing at all.
    tips = Tips()
    win = known_signal_window.show(root, "ja", URL, tips, offer={}, marked=[])
    assert win is None
    assert tips == []
    assert not [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]


def test_two_marked_words_open_titled_window_with_undo_and_tooltip_per_word(root):
    # Why: each marked word gets its own Undo, and each Undo explains itself in a tooltip (the GUI guidelines).
    tips = Tips()
    win = known_signal_window.show(root, "ja", URL, tips, offer={}, marked=MARKED)
    assert isinstance(win, tk.Toplevel)
    assert win.title() == "Known from Anki"

    undo = [b for b in _buttons(win) if b.cget("text") == "Undo"]
    assert len(undo) == 2  # one per marked word, not one per card or none at all

    undo_tips = [(widget, text) for widget, text in tips if text.startswith("Take ")]
    assert len(undo_tips) == 2
    assert {widget for widget, _ in undo_tips} == set(undo)  # each Undo has its own tooltip
    assert any("上層部" in text for _, text in undo_tips)
    assert any("一生懸命" in text for _, text in undo_tips)
    # No offer was pending, so the offer's two choices must not appear.
    assert "Mark them known" not in {b.cget("text") for b in _buttons(win)}


def test_escape_closes_the_window(root):
    # Why: Esc is the window's only keyboard exit; a window that ignores it traps the keyboard user.
    win = known_signal_window.show(root, "ja", URL, Tips(), offer={}, marked=MARKED)
    assert win is not None
    root.update()  # map the window first: an unmapped Toplevel does not take the key
    win.focus_force()
    root.update()
    win.event_generate("<Escape>")
    root.update()
    assert win.winfo_exists() == 0


def test_pending_offer_adds_mark_them_known_and_leave_them(root):
    # Why: the one-time offer for already-suspended cards must give the user a yes and a no, each with a tooltip.
    tips = Tips()
    offer = {"state": "pending", "cards": [31, 32, 33]}
    win = known_signal_window.show(root, "ja", URL, tips, offer=offer, marked=[])
    assert isinstance(win, tk.Toplevel)

    texts = {b.cget("text") for b in _buttons(win)}
    assert {"Mark them known", "Leave them"} <= texts
    assert "Undo" not in texts  # nothing was marked, so there is nothing to undo
    offer_tips = {text for _, text in tips}
    assert any(text.startswith("Every word of those suspended cards") for text in offer_tips)
    assert any(text.startswith("Leave them:") for text in offer_tips)


def test_the_listed_words_are_saved_as_shown_off_the_screens_thread(root, monkeypatch):
    # Why: once the window has listed the marked words, they are saved as shown, so the same words don't come back
    # at every sync. The save runs on a worker, never on the screen's thread.
    import threading
    done = threading.Event()
    calls = []

    def mark_shown(language, words=None):
        calls.append((language, set(words), threading.current_thread() is threading.main_thread()))
        done.set()

    monkeypatch.setattr(known_signal, "mark_shown", mark_shown)
    win = known_signal_window.show(root, "ja", URL, Tips(), offer={}, marked=MARKED, taken=[])
    assert isinstance(win, tk.Toplevel)
    assert done.wait(5.0), "the listed words were never saved as shown"
    assert calls == [("ja", {"上層部", "一生懸命"}, False)]


def _record_with_shown_and_undone_marks():
    """A record holding one live mark, one shown signal mark, one undone signal mark and one undone offer mark, plus a pending offer.
    Real words, as known_signal.read records them."""
    return {
        "marked": [
            {"word": "上層部", "card": 11, "note": 21, "at": "2026-10-08T15:00:00", "why": "signal",
             "shown": False, "undone": None},
            {"word": "一生懸命", "card": 12, "note": 22, "at": "2026-10-08T15:00:00", "why": "signal",
             "shown": False, "undone": "2026-10-09T10:00:00"},
            {"word": "気配", "card": 13, "note": 23, "at": "2026-10-08T15:00:00", "why": "offer",
             "shown": False, "undone": "2026-10-09T10:00:00"},
            # shown already: the user saw this row in an earlier window (known_signal.py sets shown to True then)
            {"word": "見切り発車", "card": 14, "note": 24, "at": "2026-10-08T15:00:00", "why": "signal",
             "shown": True, "undone": None},
        ],
        "offer": {"state": "pending", "cards": [{"word": "溜め息", "card": 31, "note": 41}]},
        "terms": ["suspended"],
    }


def test_view_leaves_out_marks_already_shown_or_undone():
    # Why: a word the user already saw in the window, or undid, must not come back as a row or as a taken word.
    known_signal._save("ja", _record_with_shown_and_undone_marks())
    v = known_signal_window.view("ja")
    assert [m["word"] for m in v["marked"]] == ["上層部"]  # the undone 一生懸命 and the shown 見切り発車 are not listed
    assert v["taken"] == []  # the undone offer word 気配 is not listed as taken


def test_pending_offer_shows_on_first_look_only_and_not_on_later_looks():
    # Why: the offer is shown once per dashboard session; the first look gets it, a later look gets nothing.
    known_signal._save("ja", _record_with_shown_and_undone_marks())
    assert known_signal_window.view("ja")["offer"]["state"] == "pending"
    assert known_signal_window.view("ja", with_offer=False)["offer"] == {}
