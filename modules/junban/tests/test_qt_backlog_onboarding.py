# SPDX-License-Identifier: GPL-3.0-or-later
"""The 順 window's backlog onboarding (Sonic 2026-10-29): *Undo the last reorder* said plainly, the backlog's picture
before the first reorder only, *Try it on my cards* and *Show them in Anki*.

What a wrong answer would cost, most first:
  * **Try it pressed on a preview that no longer describes it** — it is a real write: the same gate as Reorder (I5),
    a `junban` job of the window's, and the window previews again after it;
  * the picture shown again after the first reorder (Sonic: "only for the first reorder"), or never written down;
  * a control without its tooltip or name, or the undo line missing beside its button.

The engine is `test_qt_junban`'s fake (the planner's real rows over real words); never Anki.
"""
import pytest

pytest.importorskip("PyQt6")

from modules.junban import junban_view as view  # noqa: E402
from modules.junban import qt_strings as qs  # noqa: E402
from modules.junban import reposition, undo  # noqa: E402
from modules.junban.tests.test_qt_junban import engine, main, opened, previewed  # noqa: E402,F401
from tests.qt.conftest import _per_test_window_state, qapp, wait_until  # noqa: E402,F401
from tests.qt.test_wiring import problems  # noqa: E402


@pytest.fixture
def tried(monkeypatch):
    """`reposition.try_front` as Anki would answer it: every call recorded."""
    calls = []

    def try_front(settings, **kwargs):
        calls.append((settings, kwargs))
        return {"ok": True, "message": "Moved your next 5 cards to the front. Undo the last reorder puts them back "
                "exactly.", "warnings": [], "problems": [], "written": [1], "failures": [], "front": [1],
                "browsed": "sorted"}
    monkeypatch.setattr(reposition, "try_front", try_front)
    return calls


def _with_known(stats, n=2):
    """The engine's rows with the last `n` cards placed as words you already know."""
    order = list(stats["order"])
    for i in range(len(order) - n, len(order)):
        order[i] = order[i]._replace(tier="known")
    tiers = dict(stats.get("tiers") or {})
    tiers["known"] = n
    return dict(stats, order=order, tiers=tiers)


def test_the_undo_line_sits_right_above_its_button_from_the_start(main, engine):
    win = opened(main)
    assert win.undo_note.text() == qs.JUNBAN_UNDO_NOTE and win.undo_note.toolTip() == qs.JUNBAN_UNDO_NOTE_TIP
    assert win.undo_note.isVisible() and win.undo_note.parentWidget() is win.btn_restore.parentWidget()
    note, button = win.undo_note.geometry(), win.btn_restore.geometry()
    assert note.bottom() < button.top() and note.right() > button.left()     # its own line, over the right end


def test_the_picture_shows_after_the_first_preview_with_its_numbers_wired_and_tipped(main, engine):
    engine.stats = _with_known(engine.stats)
    win = opened(main)
    assert win.picture_box.isHidden()                      # nothing to say before a preview
    previewed(win)
    assert wait_until(lambda: win.picture_box.isVisible())
    considered = engine.stats["considered"]
    assert win.picture_title.text() == f"Your backlog: {considered} new cards"
    assert "you already know" in win.known_line.text() and win.btn_show_known.isVisible()
    assert win.btn_try.text() == "Try it on my next 5 cards" and win.btn_try.isEnabled()
    found, _walked = problems(win)
    assert found == []


def test_try_is_off_until_a_preview_and_off_again_while_a_change_throws_it_away(main, engine, tried):
    win = previewed(opened(main))
    assert win.btn_try.isEnabled()
    win.cb_phrases.click()                                 # a change throws the preview away (I5)
    assert not win.btn_try.isEnabled() and win.picture_box.isHidden()
    win.on_try()
    assert tried == []


def test_try_is_a_junban_job_with_the_windows_job_and_the_lines_say_where_the_browser_is(main, engine, tried):
    win = previewed(opened(main))
    win.btn_try.click()
    assert wait_until(lambda: tried and not win.busy())
    settings, kwargs = tried[0]
    assert kwargs["job"] is not None and settings["junban_deck"] == "TheBank"
    assert any("moved ones are on top" in t for t in win.messages.texts())
    assert not win.btn_reorder.isEnabled()                 # Anki moved on: a new preview first (D1c)
    assert "backlog_picture:ja" not in (main.services.settings.get().get("hints_seen") or ())    # not the first reorder
    win.on_preview(user=False)                             # the window's own re-preview (its timer, off in tests)
    assert wait_until(lambda: win.btn_try.isEnabled() and win.picture_box.isVisible())


def test_a_press_right_after_try_lands_writes_nothing_until_a_new_preview(main, engine, tried):
    # The session is thrown away when Try's report lands; the picture is still on screen until the re-preview (I5).
    win = previewed(opened(main))
    win.btn_try.click()
    assert wait_until(lambda: tried and not win.busy())
    assert win._picture is not None and not win.btn_try.isEnabled()
    win.on_try()
    assert len(tried) == 1


def test_try_is_off_and_says_so_when_the_next_cards_are_already_first(main, engine, tried, monkeypatch):
    real = view.backlog_picture
    monkeypatch.setattr(view, "backlog_picture",
                        lambda stats, settings=None: real(stats, settings)._replace(try_moves=0,
                                                                                    try_line="Your next 5 cards are "
                                                                                             "already first."))
    win = previewed(opened(main))
    assert win.picture_box.isVisible() and not win.btn_try.isEnabled()
    assert win.try_line.text() == "Your next 5 cards are already first."
    win.on_try()
    assert tried == []


def test_the_first_real_reorder_puts_the_picture_away_for_good(main, engine):
    win = previewed(opened(main))
    assert win.picture_box.isVisible()
    win.on_reorder()
    assert wait_until(lambda: engine.runs and not win.busy())
    assert wait_until(lambda: "backlog_picture:ja" in (main.services.settings.get().get("hints_seen") or ()))
    assert win.picture_box.isHidden()
    previewed(win)
    assert win.picture_box.isHidden()


def test_a_failed_reorder_keeps_the_picture(main, engine):
    engine.report = {"ok": False, "message": "Junban did not make any changes.", "warnings": [],
                     "problems": ["Anki closed"]}
    win = previewed(opened(main))
    win.on_reorder()
    assert wait_until(lambda: engine.runs and not win.busy())
    assert "backlog_picture:ja" not in (main.services.settings.get().get("hints_seen") or ())


def test_someone_who_reordered_before_never_sees_the_picture(main, engine, monkeypatch):
    monkeypatch.setattr(undo, "has_reordered", lambda language="ja": True)
    win = previewed(opened(main))
    assert win.picture_box.isHidden() and not win.btn_try.isEnabled()


def test_a_hint_already_seen_keeps_the_picture_away_and_other_hints_are_kept(main, engine):
    main.services.settings.set({"hints_seen": ["keep_watched:abc", "backlog_picture:ja"]})
    win = previewed(opened(main))
    assert win.picture_box.isHidden()
    main.services.settings.set({"hints_seen": ["keep_watched:abc"]})
    win.on_preview()
    assert wait_until(lambda: win.picture_box.isVisible())
    win.on_reorder()
    assert wait_until(lambda: "backlog_picture:ja" in (main.services.settings.get().get("hints_seen") or ()))
    assert "keep_watched:abc" in main.services.settings.get()["hints_seen"]


def test_show_them_in_anki_opens_the_browser_on_the_known_cards_only(main, engine, monkeypatch):
    engine.stats = _with_known(engine.stats)
    shown = []
    monkeypatch.setattr(view, "show_work", lambda settings, ids: shown.append(list(ids)) or "sorted")
    win = previewed(opened(main))
    win.btn_show_known.click()
    assert wait_until(lambda: shown and win.btn_show_known.isEnabled())
    assert shown == [[row.card_id for row in engine.stats["order"][-2:]]]
    assert engine.runs == []


def test_show_them_in_anki_with_anki_closed_says_so(main, engine, monkeypatch):
    engine.stats = _with_known(engine.stats)

    def closed(settings, ids):
        raise reposition.AnkiError("Could not reach Anki.", kind="offline")
    monkeypatch.setattr(view, "show_work", closed)
    win = previewed(opened(main))
    win.btn_show_known.click()
    assert wait_until(lambda: any("browser couldn't be opened" in t for t in win.messages.texts()))
