# SPDX-License-Identifier: GPL-3.0-or-later
""""Put Anki back the way it was before Surasura…" — the button, its questions, and what a click may write (FT D8).

What this file holds still, in order of the damage its absence does:

1. **Nothing is written without a yes.** `put_back` runs only after the confirm; a dismissed or declined question,
   Anki closed, the wrong profile open, or nothing kept writes nothing — and the fields question's answer is the
   `fields` the writer is handed, exactly.
2. **The Tk thread never waits on Anki.** `plan()` and `put_back()` run on workers; the window hears back only
   through its own queue.
3. **The guidelines:** a tooltip on the button, Esc closes the window this adds, the button greyed with nothing
   kept, and refused while 順's own run is going.

Behaviour only — no pixel positions. `first_touch` (worker A's module) is stubbed: `has_anything`, `plan` and
`put_back` are replaced on the module itself, which a stand-in provides while the real module isn't there yet.
Nothing reaches Anki. One Tk root per file (`testing.md` §5.4).
"""
import sys
import threading
import time
import tkinter as tk
import types
from tkinter import ttk

import pytest

import modules.junban as junban
from modules.junban import first_touch_gui
from modules.junban import gui as junban_gui

# A real deck and profile as a learner names them (the suites' own: TheBank, a Japanese profile name).
_PROFILE = "ユーザー 1"
_PLAN = {"ok": True, "problems": [], "profile": "User 1", "taken_at": "2026-10-13T21:04:00", "earlier": False,
         "cards_back": 1234, "added_after": 56, "unsuspend": 12, "tags_off": 340, "flags": 3,
         "fields_unedited": 220, "fields_edited": 10, "nothing": False, "anki_closed": False,
         "wrong_profile": None}
_REPORT = {"ok": True, "message": ("Put back: 1,234 new cards back in their order from before Surasura (2026-10-13); 56 "
                                   "cards added since after them · 12 cards unsuspended."),
           "problems": [], "done": {"cards": 1234, "added_after": 56, "unsuspended": 12, "tags_off": 340,
                                    "flags": 3, "fields": 220},
           "settings_changed": ["junban_replan_deck"]}


@pytest.fixture(scope="module")
def root():
    try:
        window = tk.Tk()
    except tk.TclError as exc:                      # pragma: no cover - headless machine
        pytest.skip(f"no display: {exc}")
    window.withdraw()
    yield window
    try:
        window.destroy()
    except tk.TclError:
        pass


@pytest.fixture
def ft(monkeypatch):
    """`first_touch`, its three calls stubbed and recorded: `calls["plan"]` holds the thread each plan ran on.
    While worker A's module isn't there yet a stand-in takes its place, for this test only."""
    try:
        from modules.junban import first_touch
    except ImportError:
        first_touch = types.ModuleType("modules.junban.first_touch")
        monkeypatch.setitem(sys.modules, "modules.junban.first_touch", first_touch)
        monkeypatch.setattr(junban, "first_touch", first_touch, raising=False)
    state = {"kept": True, "plan": dict(_PLAN), "report": dict(_REPORT)}
    calls = {"plan": [], "put_back": []}

    def plan(settings, language=None, url=None):
        calls["plan"].append((threading.current_thread(), language, settings.get("target_language")))
        return dict(state["plan"])

    def put_back(settings, language=None, fields=False, progress=None, wait=0.0, cancel=None, on_wait=None,
                 url=None, **extra):
        calls["put_back"].append(dict(extra, thread=threading.current_thread(), language=language, fields=fields,
                                      wait=wait, cancel=cancel))
        if progress is not None:
            progress(1, 2)
            progress(2, 2)
        return dict(state["report"])

    monkeypatch.setattr(first_touch, "has_anything", lambda language: state["kept"], raising=False)
    monkeypatch.setattr(first_touch, "plan", plan, raising=False)
    monkeypatch.setattr(first_touch, "put_back", put_back, raising=False)
    return types.SimpleNamespace(state=state, calls=calls)


@pytest.fixture
def answers(monkeypatch):
    """`gui.ask` answering from a list, in order (the conftest's default is a no); every question asked is kept."""
    replies, asked = [], []

    def ask(parent, message, details=None, title=None, yes=None, no=None, default=True):
        asked.append((message, list(details or ()), default))
        return replies.pop(0) if replies else False
    monkeypatch.setattr(junban_gui, "ask", ask)
    return types.SimpleNamespace(replies=replies, asked=asked)


def _panel(root):
    panel = junban_gui.JunbanGui(root)
    root.update_idletasks()
    return panel


def _close(panel):
    try:
        panel._close()
    except tk.TclError:
        pass


def _pump(window, until, timeout=5.0):
    """Run the window's queue on this (the Tk) thread until `until()` — the workers post, this thread renders."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        window._drain_once()
        window.update()
        if until():
            return True
        time.sleep(0.01)
    return False


def _messages(panel):
    return panel.messages.get("1.0", "end")


def _run(root, ft):
    """Press the button in 順 and wait for the flow to end. -> the panel."""
    panel = _panel(root)
    panel._sync_buttons()
    panel.on_put_back()
    if not _pump(panel, lambda: not panel.busy):
        _close(panel)                                 # its `junban-window` hold let go even when the test fails here
        raise AssertionError("the flow never finished")
    return panel


# ------------------------------------------------------------------------------------------------- the button
def test_the_button_is_in_the_actions_with_a_wrapped_tooltip(root, ft):
    panel = _panel(root)
    try:
        assert panel.btn_put_back.cget("text") == "Put Anki back the way it was before Surasura…"
        assert panel.btn_put_back.bind("<Enter>"), "no tooltip"
        tip = junban_gui.ToolTip(ttk.Button(panel, text="x"), first_touch_gui.BUTTON_TIP)
        tip._show()
        assert tip.tip.winfo_children()[0].cget("wraplength") > 0      # over 50 characters: wrapped
        tip._hide()
    finally:
        _close(panel)


def test_the_button_is_greyed_with_nothing_kept_and_live_with_something(root, ft):
    """`has_anything` is the language's own files, never Anki: nothing kept, nothing to press."""
    ft.state["kept"] = False
    panel = _panel(root)
    try:
        panel._sync_buttons()
        assert str(panel.btn_put_back.cget("state")) == "disabled"
        ft.state["kept"] = True
        panel._first_touch_changed()                    # C21: what a run, a restore or a put-back does
        panel._sync_buttons()
        assert str(panel.btn_put_back.cget("state")) == "normal"
    finally:
        _close(panel)


def test_the_button_is_greyed_while_the_first_touch_module_is_missing(root, monkeypatch):
    """An install without worker A's module (or a broken one) offers nothing rather than raising."""
    monkeypatch.setitem(sys.modules, "modules.junban.first_touch", None)
    monkeypatch.delattr(junban, "first_touch", raising=False)
    panel = _panel(root)
    try:
        panel._sync_buttons()
        assert str(panel.btn_put_back.cget("state")) == "disabled"
    finally:
        _close(panel)


# --------------------------------------------------------------------------------------------- what a click does
def test_a_click_reads_anki_off_the_tk_thread_for_this_language(root, ft, answers):
    panel = _run(root, ft)
    try:
        assert len(ft.calls["plan"]) == 1
        thread, language, target = ft.calls["plan"][0]
        assert thread is not threading.main_thread()
        assert language == target == panel._lang_code()
    finally:
        _close(panel)


def test_declining_the_confirm_writes_nothing(root, ft, answers):
    """The conftest's safe default, a no: the counts are asked about, and nothing is put back."""
    panel = _run(root, ft)
    try:
        assert ft.calls["put_back"] == []
        assert len(answers.asked) == 1
        question, details, _default = answers.asked[0]
        assert question == "Put Anki back the way it was before Surasura?"
        assert details[0] == ("1,234 new cards back in their order of 13 October 2026; cards you've studied "
                              "since stay as they are")
        assert "56 cards added since go after them, in the order you added them" in details
        assert "Nothing was changed." in _messages(panel)
    finally:
        _close(panel)


@pytest.mark.parametrize("fields_answer", [True, False])
def test_yes_puts_back_once_with_the_fields_as_answered(root, ft, answers, fields_answer):
    answers.replies.extend([True, fields_answer])
    panel = _run(root, ft)
    try:
        assert len(ft.calls["put_back"]) == 1
        call = ft.calls["put_back"][0]
        assert call["fields"] is fields_answer
        assert call["thread"] is not threading.main_thread()
        assert call["cancel"] is panel._stop            # closing 順 stops a wait for another Anki writer
        assert call["profile"] == "User 1"              # C8: the profile the confirm counted, or nothing is written
        assert answers.asked[1][0] == ("Backfill and 順 (the frequency field) filled 230 notes: put the old text back "
                                       "in the 220 you "
                                       "haven't edited?")
        shown = _messages(panel)
        assert shown.count(_REPORT["message"]) == 1     # the closing line names D7's step too: said once
        assert panel.progress["value"] == 2
        assert panel._preview_scope is None             # the collection moved: no preview confirms a reorder
    finally:
        _close(panel)


def test_no_fields_question_when_backfill_has_nothing_to_give_back(root, ft, answers):
    ft.state["plan"].update(fields_unedited=0, fields_edited=4)
    answers.replies.append(True)
    panel = _run(root, ft)
    try:
        assert len(answers.asked) == 1
        assert [call["fields"] for call in ft.calls["put_back"]] == [False]
    finally:
        _close(panel)


def test_anki_closed_says_so_and_writes_nothing(root, ft, answers):
    ft.state["plan"].update(ok=False, anki_closed=True)
    answers.replies.extend([True, True])
    panel = _run(root, ft)
    try:
        assert ft.calls["put_back"] == [] and answers.asked == []
        assert "Open Anki first: nothing was changed." in _messages(panel)
    finally:
        _close(panel)


def test_the_wrong_profile_names_the_right_one_and_writes_nothing(root, ft, answers):
    ft.state["plan"].update(ok=False, wrong_profile=_PROFILE)
    answers.replies.extend([True, True])
    panel = _run(root, ft)
    try:
        assert ft.calls["put_back"] == [] and answers.asked == []
        assert f'Open the profile "{_PROFILE}" in Anki first: nothing was changed.' in _messages(panel)
    finally:
        _close(panel)


def test_nothing_kept_never_asks_anki(root, ft, answers):
    """Pressed from Settings, where the button isn't greyed: no files, no plan, one plain line."""
    ft.state["kept"] = False
    panel = _panel(root)
    try:
        first_touch_gui.PutBack(panel, "zh", post=lambda fn: panel.q.put(("__CALL__", fn)), show=panel._write,
                                busy=panel._set_busy).start()
        assert _pump(panel, lambda: not panel.busy)
        assert ft.calls["plan"] == [] and ft.calls["put_back"] == []
        assert "Surasura hasn't changed this language's Anki cards." in _messages(panel)
    finally:
        _close(panel)


def test_refused_while_a_run_of_the_windows_own_is_going(root, ft, answers):
    panel = _panel(root)
    try:
        panel.busy = True
        panel.on_put_back()
        time.sleep(0.05)
        assert ft.calls["plan"] == []
    finally:
        _close(panel)


def test_a_failing_plan_is_shown_and_nothing_is_written(root, ft, answers, monkeypatch):
    from modules.junban import first_touch

    def broken(settings, language=None, url=None):
        raise OSError("anki_first_touch\\order-TheBank.json: permission denied")
    monkeypatch.setattr(first_touch, "plan", broken)
    panel = _run(root, ft)
    try:
        assert ft.calls["put_back"] == []
        assert "permission denied" in _messages(panel)
        assert str(panel.btn_preview.cget("state")) == "normal"      # never left stuck on busy
    finally:
        _close(panel)


# ----------------------------------------------------------------------------------------------- the wording
def test_earlier_names_the_order_surasura_kept_never_before_surasura():
    question, details = first_touch_gui.confirm_text(dict(_PLAN, earlier=True, added_after=0, unsuspend=1))
    assert question == "Put Anki back the way Surasura kept it on 13 October 2026?"
    assert "before Surasura" not in question + " ".join(details)
    assert details[0].startswith("1,234 new cards back in the order Surasura kept on 13 October 2026")
    assert "1 card Surasura suspended unsuspended" in details
    assert not any("added since" in line for line in details)


def test_kept_but_already_back_asks_nothing_and_writes_nothing(root, ft, answers):
    """`plan`'s `nothing` with files kept: every count zero. No confirm for a put-back that changes nothing."""
    ft.state["plan"].update(cards_back=0, added_after=0, unsuspend=0, tags_off=0, flags=0, fields_unedited=0,
                            nothing=True)
    panel = _run(root, ft)
    try:
        assert answers.asked == [] and ft.calls["put_back"] == []
        assert "Nothing left to put back: nothing was changed." in _messages(panel)
    finally:
        _close(panel)


def test_a_refused_put_back_says_its_reason_once(root, ft, answers):
    """Anki closed between the plan and the write: `put_back` refuses, its problem IS its message."""
    ft.state["report"] = {"ok": False, "message": "Open Anki first: nothing was changed.",
                          "problems": ["Open Anki first: nothing was changed."], "settings_changed": []}
    answers.replies.extend([True, True])
    panel = _run(root, ft)
    try:
        assert _messages(panel).count("Open Anki first: nothing was changed.") == 1
    finally:
        _close(panel)


def test_the_confirm_says_it_cant_be_undone_and_how_to_have_surasuras_order_again():
    """K14 / C15 (IK2): Anki keeps no undo, and Undo the last reorder is no way back from a put-back — the user is
    told before saying yes, not after."""
    _question, details = first_touch_gui.confirm_text(_PLAN)
    assert details[-1] == "This can't be undone. To have Surasura's order again, re-order in 順."


# --------------------------------------------------------------------------- K4: the changes from before the record
@pytest.mark.parametrize("older_answer", [True, False])
def test_older_changes_are_a_third_question_defaulting_to_no(root, ft, answers, older_answer):
    ft.state["plan"].update(older_suspended=5, older_tags=7)
    answers.replies.extend([True, True, older_answer])
    panel = _run(root, ft)
    try:
        assert len(answers.asked) == 3
        question, _details, default = answers.asked[2]
        assert question == ("5 suspended cards carry Surasura's 'later' tag, and 7 notes carry Surasura's tags, "
                            "from before it kept this record. Unsuspend those cards and take the older tags off?")
        assert default is False                         # Enter keeps them; only a clicked yes takes them
        assert [(call["fields"], call["older"]) for call in ft.calls["put_back"]] == [(True, older_answer)]
    finally:
        _close(panel)


def test_without_older_changes_no_third_question_and_no_older_argument(root, ft, answers):
    answers.replies.extend([True, False])
    panel = _run(root, ft)
    try:
        assert len(answers.asked) == 2
        assert "older" not in ft.calls["put_back"][0]
    finally:
        _close(panel)


def test_older_changes_alone_are_still_offered(root, ft, answers):
    """Every recorded change already back (`nothing`), but Anki holds older ones: the user is still asked."""
    ft.state["plan"].update(cards_back=0, added_after=0, unsuspend=0, tags_off=0, flags=0, fields_unedited=0,
                            nothing=True, older_suspended=0, older_tags=2)
    answers.replies.extend([True, True])
    panel = _run(root, ft)
    try:
        assert answers.asked[-1][0] == "2 notes carry Surasura's tags from before it kept this record. Take them off?"
        assert ft.calls["put_back"][0]["older"] is True
    finally:
        _close(panel)


# ---------------------------------------------------------------------------------- K5 / K6 / K10: the lines
def test_the_closing_lines_name_what_stays_and_what_surasura_stopped_doing(root, ft, answers):
    ft.state["plan"].update(made_left=3, backfill_fills="TheBank")
    ft.state["report"]["settings_changed"] = ["junban_auto_backfill", "junban_replan_deck"]
    answers.replies.extend([True, True])
    panel = _run(root, ft)
    try:
        shown = _messages(panel)
        assert "3 cards Surasura made are left as they are; Connect's Undo this batch removes them." in shown
        assert "Surasura won't re-order this deck by itself until you pick it in 順 again." in shown
        assert ("Backfill's automatic step is off — it fills TheBank; turn it back on in Settings." in shown)  # C16
    finally:
        _close(panel)


def test_no_settings_line_when_nothing_was_switched_off():
    report = dict(_REPORT, settings_changed=[], done=dict(_REPORT["done"], fields=0))
    assert first_touch_gui.closing_lines({"made_left": 0}, report) == []
    # C16: fields put back while Backfill's automatic step fills another deck (or is off) — it stays as it was.
    assert first_touch_gui.closing_lines({"made_left": 0}, dict(report, done=dict(report["done"], fields=220))) == []
    assert first_touch_gui.closing_lines({"made_left": 1}, report) == [
        "1 card Surasura made is left as it is; Connect's Undo this batch removes it."]


def test_a_set_aside_order_file_is_named(root, ft, answers):
    ft.state["plan"]["set_aside"] = ["order-TheBank-User 1.json.unreadable-20261013-2304"]
    panel = _run(root, ft)
    try:
        assert ("1 saved order couldn't be read and was set aside: order-TheBank-User 1.json.unreadable-20261013-2304."
                in _messages(panel))
    finally:
        _close(panel)


# ------------------------------------------------------------------------------------------- Settings' door
def test_settings_window_runs_the_same_flow_and_esc_closes_it(root, ft, answers):
    answers.replies.extend([True, False])
    host = types.SimpleNamespace(var_language=tk.StringVar(root, value="ja"), root=root, settings_window=None)
    window = first_touch_gui.open_put_back(host)
    try:
        assert _pump(window, lambda: not window.busy)
        assert [call["fields"] for call in ft.calls["put_back"]] == [False]
        assert _REPORT["message"] in window.messages.get("1.0", "end")
        assert window.btn_close.bind("<Enter>"), "no tooltip"
        assert window.bind("<Escape>")
        window.deiconify()
        window.update()
        window.focus_force()
        window.event_generate("<Escape>", when="now")
        root.update()
        assert not window.winfo_exists()
    finally:
        try:
            window.destroy()
        except tk.TclError:
            pass


def test_settings_door_refuses_while_the_junban_window_is_busy(root, ft, answers):
    panel = _panel(root)
    try:
        panel.busy = True
        host = types.SimpleNamespace(var_language=tk.StringVar(root, value="ja"), root=root, settings_window=None,
                                     junban_window=panel)
        assert first_touch_gui.open_put_back(host) is None
        assert ft.calls["plan"] == []
    finally:
        _close(panel)


# ------------------------------------------------------------------------------ the build review's fixes (worker C)
def test_the_confirm_counts_surasuras_made_cards_apart_from_yours():
    """C18: Connect's mined cards go after yours — never counted as cards you added."""
    _question, details = first_touch_gui.confirm_text(dict(_PLAN, made_after=4))
    assert "4 cards Surasura made go after yours" in details
    assert "56 cards added since go after them, in the order you added them" in details


def test_the_confirm_says_what_stops_by_itself_before_anything_is_written():
    """C17 / C16: the automatic re-order standing aside for the deck, and Backfill's automatic step going off with
    the fields (named with what it fills), are said in the confirm — not only after."""
    _question, details = first_touch_gui.confirm_text(dict(_PLAN, stands_aside="TheBank", backfill_fills=""))
    assert "Surasura won't re-order TheBank by itself until you pick it in 順 again" in details
    assert ("If you put the fields back, Backfill's automatic step will be off — it fills all your decks; turn it "
            "back on in Settings.") in details
    _question, details = first_touch_gui.confirm_text(dict(_PLAN, stands_aside=None, backfill_fills=None))
    assert not [line for line in details if "by itself" in line or "Backfill" in line]


def test_the_record_is_looked_for_once_until_a_run_a_restore_or_a_put_back(root, ft, answers, monkeypatch):
    """C21 (IK16 / H18): `has_anything` lists a folder — not at every button sync on the Tk thread."""
    from modules.junban import first_touch
    looked = []
    monkeypatch.setattr(first_touch, "has_anything", lambda language: looked.append(language) or True)
    panel = _panel(root)
    try:
        for _ in range(5):
            panel._sync_buttons()
        assert len(looked) == 1
        panel.q.put(("__REPORT__", {"ok": True, "message": "Restored 3 cards.", "problems": [], "warnings": [],
                                    "written": [], "failures": []}))
        panel._drain_once()
        panel._sync_buttons()
        assert len(looked) == 2
        panel._put_back_done({"ok": True})
        assert len(looked) == 3
    finally:
        _close(panel)


def test_closing_the_settings_window_by_its_parent_stops_a_waiting_put_back(root, ft):
    """C24 (A-N6): the Settings window destroyed with its parent — the put-back waiting for the Anki-write lock
    stops, as it does when the window's own Close is pressed."""
    window = first_touch_gui.PutBackWindow(root, "ja")
    stop = window._stop
    window.destroy()
    root.update()
    assert stop.is_set()


def test_settings_that_cant_be_read_give_the_defaults_and_say_so(monkeypatch):
    """C29 (H16): never an empty dict (the put-back reads Junban's address and tags from it) — the defaults, and a
    line saying why."""
    from app import settings_manager
    real = settings_manager.load_settings

    def load(strict=False):
        if strict:
            raise settings_manager.SettingsError("settings.json can't be read: Expecting value: line 1 column 1")
        return real()

    monkeypatch.setattr(settings_manager, "load_settings", load)
    shown, posted = [], []
    flow = first_touch_gui.PutBack(None, "ja", post=posted.append, show=lambda line, tag=None: shown.append((line, tag)))
    settings = flow._settings()
    for step in posted:
        step()
    assert set(real()) <= set(settings) and settings["target_language"] == "ja"
    assert shown and shown[0][1] == "warning" and "can't be read" in shown[0][0]


def test_a_step_that_raises_is_shown_and_the_rest_still_run(root, ft):
    """C30 (H19): one faulty step never stops the pump — in Settings' window and in 順's."""
    def faulty():
        raise RuntimeError("a fault in a step")

    ran = []
    window = first_touch_gui.PutBackWindow(root, "ja")
    try:
        window.q.put(faulty)
        window.q.put(lambda: ran.append("settings"))
        window._drain_once()
        assert ran == ["settings"] and "a fault in a step" in window.messages.get("1.0", "end")
    finally:
        window.destroy()
    panel = _panel(root)
    try:
        panel.q.put(("__CALL__", faulty))
        panel.q.put(("__CALL__", lambda: ran.append("順")))
        panel._drain_once()
        assert ran == ["settings", "順"] and "a fault in a step" in _messages(panel)
    finally:
        _close(panel)
