# SPDX-License-Identifier: GPL-3.0-or-later
"""順's view model (W3.4 row 6; `junban_view.py`, `put_back_view.py`): the rules the Qt window paints, without a toolkit.

What a wrong answer would cost, in order:
  * a Reorder written from a preview of another deck, option set, language or collection state (the I5 key missing a
    part, or a redraw stamping it again — the Tk window's D1): cards moved, notes tagged or the sort number OVERWRITTEN
    in a way the sentence on screen never said;
  * the run going ahead after "Same word?" answers failed to save (it would write what the user never confirmed);
  * a settings write the user never made (S16), or the (language, deck) pair recorded for another language;
  * the settings defaults poisoned in place (spec §13 #12);
  * "Generating…" stuck forever after a Generate that never started (D4);
  * a Restore offered for the wrong snapshot, or the put-back's questions losing "can't be undone" / the older
    question's No.

Real Japanese words from the shared export (`tests/Test Resources/ja/expected_output.csv`); never Anki.
"""
import csv
import os
import time
from unittest import mock

import pytest

import modules.junban as junban
from modules.junban import junban_view as view
from modules.junban import put_back_view, spaced
from modules.junban.plan import plan

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_CSV = os.path.join(_ROOT, "tests", "Test Resources", "ja", "expected_output.csv")
_UNRANKED = ["須藤", "鳥取", "美術館", "新幹線", "味噌汁"]


def _rank_of():
    index = {}
    with open(_CSV, "r", encoding="utf-8-sig", newline="") as handle:
        for rank, row in enumerate(csv.DictReader(handle)):
            for key in ((row.get("Orth") or "").strip(), (row.get("Word") or "").strip()):
                if key and key not in index:
                    index[key] = rank
    return index


RANK_OF = _rank_of()
RANKED = [w for w, _r in sorted(RANK_OF.items(), key=lambda p: p[1])][:6]


def real_stats():
    """A genuine dry run: the planner's own rows over real words mined out of order (as test_gui's)."""
    cards = [{"card_id": 1700 + i, "due": 2830 + i, "type": 0, "queue": 0, "word": w, "deck": "TheBank",
              "note": 2700 + i} for i, w in enumerate(reversed(RANKED))]
    cards += [{"card_id": 1800 + i, "due": 2840 + i, "type": 0, "queue": 0, "word": w, "deck": "The Accelerator",
               "note": 2800 + i} for i, w in enumerate(_UNRANKED)]
    _writes, stats = plan(cards, RANK_OF)
    stats["decks"] = ["TheBank"]
    stats["fields"] = {"Lapis": "Expression"}
    return stats


def saved(**over):
    base = dict(junban.SETTINGS_DEFAULTS)
    base.update({"target_language": "ja", "junban_deck": "TheBank"})
    base.update(over)
    return base


def controls(**over):
    c = view.controls_from(saved(), connect_row=False)
    c.update(over)
    return c


# --- the I5 key ------------------------------------------------------------------------------------------------------ #
@pytest.mark.parametrize("change", [
    {"scope": "all"}, {"deck": "The Accelerator"}, {"order": "priority"}, {"list_first": False}, {"phrases": False},
    {"ready_first": True}, {"only_markers": ("star",)}, {"tag_on": False}, {"tag_name": "mine"},
    {"markers_on": True}, {"freq_on": True}, {"freq_field": "Freq"}, {"freqsort_on": True}, {"later_tag": True},
    {"later_flag": True}, {"later_suspend": True},
])
def test_every_part_of_the_scope_key_changes_it(change):
    # Each control changes what Reorder writes, so a preview made without it is no confirmation of a run with it.
    base = controls(tag_on=True)
    assert view.scope_key("ja", base, False) != view.scope_key("ja", dict(base, **change), False)


def test_the_language_the_own_tag_row_and_the_replan_switch_are_in_the_key_too():
    c = controls()
    key = view.scope_key("ja", c, False)
    assert view.scope_key("zh", c, False) != key
    assert view.scope_key("ja", c, True) != key
    with_row = dict(c, own_tag="", order_all=False)
    assert view.scope_key("ja", with_row, False) != key
    assert view.scope_key("ja", dict(with_row, order_all=True), False) != view.scope_key("ja", with_row, False)
    assert view.scope_key("ja", dict(with_row, own_tag="immersion"), False) != view.scope_key("ja", with_row, False)


def test_an_untouched_entry_leaves_the_key_as_it_was():
    c = controls()
    assert view.scope_key("ja", c, False) == view.scope_key("ja", dict(c), False)
    # The tag's name while the tag is off writes nothing: it changes nothing the run does.
    off = controls(tag_on=False)
    assert view.scope_key("ja", off, False) == view.scope_key("ja", dict(off, tag_name="other"), False)


# --- the engine settings --------------------------------------------------------------------------------------------- #
def test_the_engine_settings_are_fresh_and_never_touch_the_defaults():
    s = saved()
    fields_before = dict(junban.SETTINGS_DEFAULTS["junban_word_fields"])
    out = view.engine_settings(s, controls(only_markers=("star",)), "ja", {1802, 1701})
    out["junban_word_fields"]["Lapis"] = "poison"
    out["junban_only_markers"].append("reading")
    assert junban.SETTINGS_DEFAULTS["junban_word_fields"] == fields_before
    assert junban.SETTINGS_DEFAULTS["junban_only_markers"] == []
    assert out["junban_exclude_cards"] == [1701, 1802]          # sorted, from this preview's clicks only
    assert out["target_language"] == "ja" and out["junban_deck"] == "TheBank"


def test_an_unticked_box_sends_its_disabling_value():
    out = view.touchup_settings(controls(tag_on=False, tag_name="Surasura", markers_on=False, freq_on=False,
                                         freqsort_on=False))
    assert out["junban_tag"] == "" and out["junban_write_frequency"] is False and out["junban_write_freqsort"] is False
    on = view.touchup_settings(controls(tag_on=True, tag_name=" mine ", freqsort_on=True, later_suspend=True))
    assert on["junban_tag"] == "mine" and on["junban_write_freqsort"] is True and on["junban_later_suspend"] is True


def test_list_first_keeps_a_hand_set_back_and_unticked_is_journey():
    assert view.unlisted_value({"list_first": True}, "back") == "back"
    assert view.unlisted_value({"list_first": True}, "") == "list_first"
    assert view.unlisted_value({"list_first": False}, "back") == "journey"


def test_the_connect_row_is_handed_on_only_when_shown():
    assert view.own_values(controls()) == {}
    c = view.controls_from(saved(connect_enabled=True, junban_own_tag="immersion"), connect_row=True)
    assert view.own_values(c) == {"junban_own_tag": "immersion", "junban_order_all": False}


# --- what is saved ------------------------------------------------------------------------------------------------- #
def test_only_the_keys_that_changed_are_saved():
    c = controls()
    last = view.window_keys(c)
    assert view.changed_keys(last, view.window_keys(c)) == {}
    changed = view.changed_keys(last, view.window_keys(dict(c, phrases=False, deck="The Accelerator")))
    assert changed == {"junban_phrases": False, "junban_deck": "The Accelerator"}


def test_the_pair_is_recorded_only_on_a_deck_pick_in_the_windows_language():
    assert view.pair_keys("TheBank", "ja", "ja", picked=True) == {"junban_replan_language": "ja",
                                                                  "junban_replan_deck": "TheBank"}
    assert view.pair_keys("TheBank", "ja", "ja", picked=False) == {}
    assert view.pair_keys("TheBank", "ja", "zh", picked=True) == {}
    assert view.pair_keys("", "ja", "ja", picked=True) == {}


# --- the gate ---------------------------------------------------------------------------------------------------------- #
def _landed(session, key=("k",)):
    generation = session.ask()
    assert session.land(generation, key, key, real_stats(), {"ok": True}, {})
    return generation


def test_a_preview_unlocks_reorder_only_for_its_own_key():
    s = view.Session()
    assert not s.ready(("k",))
    _landed(s)
    assert s.ready(("k",)) and not s.ready(("other",))
    assert not s.ready(("k",), busy=True)


def test_a_preview_landing_after_a_change_is_dropped():
    # D1 (a): the control changed while it was read (the window clears on every change): it never lands, and a click
    # afterwards has nothing to re-stamp.
    s = view.Session()
    generation = s.ask()
    s.clear()
    assert not s.land(generation, ("k",), ("k",), real_stats(), {"ok": True}, {})
    assert s.stats is None and not s.toggle_row(1700) and not s.ready(("k",))


def test_a_thrown_away_previews_list_state_never_lands():
    # Haiku H2: an earlier preview read "the list is current" and landed after a newer one found it out of date —
    # Reorder came on over a list known to be stale.
    s = view.Session()
    earlier = s.ask()
    newer = s.ask()
    assert s.land(newer, ("k",), ("k",), real_stats(), {"ok": True, "list_current": False}, {})
    assert not s.ready(("k",))
    assert not s.land(earlier, ("k",), ("k",), real_stats(), {"ok": True, "list_current": True}, {})
    assert s.list_current is False and not s.ready(("k",))


def test_a_preview_made_for_another_key_is_dropped():
    s = view.Session()
    generation = s.ask()
    assert not s.land(generation, ("old",), ("new",), real_stats(), {"ok": True}, {})
    assert not s.ready(("old",)) and not s.ready(("new",))


def test_a_click_never_stamps_the_key_again():
    s = view.Session()
    generation = _landed(s, ("k",))
    stats = s.stats
    assert s.toggle_row(stats["order"][0].card_id)
    token = s.replan_asked()
    assert not s.ready(("k",))                                   # the click's re-plan hasn't landed: Reorder off
    assert s.replan_landed(generation, token, view.preview_view(**_frozen(s)))
    assert s.ready(("k",)) and s.scope == ("k",)
    assert not s.ready(("other",))                               # still the key it was made for, never the controls'


def _frozen(s):
    f = s.frozen()
    return dict(stats=f["stats"], checks=f["checks"], deselected=f["deselected"], ticked=f["ticked"],
                display_order=f["display_order"], show_earlier=f["show_earlier"], settings=f["settings"])


def test_a_late_replan_of_a_thrown_away_preview_never_lands():
    s = view.Session()
    generation = _landed(s)
    s.toggle_row(s.stats["order"][0].card_id)
    token = s.replan_asked()
    shown = view.preview_view(**_frozen(s))
    s.clear()                                                    # a write finished meanwhile (D1 c / d)
    assert not s.replan_landed(generation, token, shown) and not s.ready(("k",))


def test_an_older_replan_never_overwrites_a_newer_one():
    s = view.Session()
    generation = _landed(s)
    first = s.replan_asked()
    second = s.replan_asked()
    assert not s.replan_landed(generation, first, view.preview_view(**_frozen(s)))
    assert not s.ready(("k",))
    assert s.replan_landed(generation, second, view.preview_view(**_frozen(s)))
    assert s.ready(("k",))


def test_a_list_known_out_of_date_keeps_reorder_off_and_offers_generate():
    s = view.Session()
    generation = s.ask()
    s.land(generation, ("k",), ("k",), real_stats(), {"ok": True, "list_current": False}, {})
    assert not s.ready(("k",)) and s.must_generate(True) and not s.must_generate(False)
    assert view.tail_lines(s, True)[-1][0].startswith("Your list is out of date")


def test_a_generate_that_never_started_ends_the_generating_state():
    # D4: the Tk window stayed "Generating…" with every button off when the run never started.
    s = view.Session()
    s.generating = True
    assert s.list_updated(busy=False) is True and s.generating is False and s.list_current is None
    s.generating = True
    assert s.list_updated(busy=True) is False and s.generating is False


def test_someone_elses_generate_leaves_a_working_preview_alone():
    s = view.Session()
    _landed(s)
    assert s.list_updated(busy=False) is False and s.ready(("k",))


# --- the buttons ---------------------------------------------------------------------------------------------------- #
def test_the_button_rules():
    b = view.buttons(False, False, True, False, True, "deck")
    assert b == {"preview_text": "preview", "preview": True, "restore": True, "recheck": True, "reorder": True,
                 "put_back": True, "deck": True}
    assert view.buttons(True, False, True, False, True, "all")["reorder"] is False
    busy = view.buttons(True, False, True, False, True, "all")
    assert not any(busy[k] for k in ("preview", "restore", "recheck", "put_back")) and busy["deck"] is False
    assert view.buttons(False, True, True, True, True, "deck")["preview_text"] == "generating"
    assert view.buttons(False, False, False, True, False, "deck")["preview_text"] == "generate"
    assert view.buttons(False, False, True, False, False, "deck")["put_back"] is False


# --- the preview's words ---------------------------------------------------------------------------------------------- #
def test_the_preview_sentence_states_every_write_before_reorder():
    stats = real_stats()
    stats["touchups"] = {"counts": {"tag": 3, "freqsort": 2}}
    stats["later"] = {"counts": {"suspend": 4}}
    shown = view.preview_view(stats, {"warnings": ["a heads-up"]}, settings=saved())
    sentence = [text for text, tone in shown.lines if text.startswith("Reorder will move")]
    assert sentence and "OVERWRITE the sort number on 2 notes" in sentence[0] and "suspend 4 cards" in sentence[0]
    assert shown.lines[0] == ("a heads-up", "warning")
    assert len(shown.rows) == len(stats["order"]) and shown.rows[0][0] == "1"


def test_a_clicked_off_row_stays_in_place_with_its_cross_and_the_rest_renumber():
    stats = real_stats()
    first = view.preview_view(stats, {}, settings=saved())
    victim = first.card_ids[0]
    again = view.preview_view(stats, {}, deselected=frozenset({victim}), display_order=first.display_order,
                              settings=saved())
    assert again.card_ids[0] == victim and again.rows[0][0] == view.DESELECTED_GLYPH
    numbers = [row[0] for row in again.rows if row[0] != view.DESELECTED_GLYPH]
    assert numbers == [str(i) for i in range(1, len(numbers) + 1)]


def test_a_preview_past_the_cap_says_so():
    cards = [{"card_id": i, "due": i, "type": 0, "queue": 0, "word": f"語{i}", "deck": "D", "note": i + 9000}
             for i in range(view.MAX_PREVIEW_ROWS + 3)]
    _w, stats = plan(cards, {})
    shown = view.preview_view(stats, {}, settings=saved())
    assert len(shown.rows) == view.MAX_PREVIEW_ROWS
    assert any("Showing the first 4000 of 4003 cards." == text for text, _t in shown.lines)


def test_no_preview_says_so():
    shown = view.preview_view(None, {"problems": ["Anki is not running."]})
    assert shown.empty and shown.rows == () and ("Anki is not running.", "problem") in shown.lines


def test_the_marker_glyphs_are_the_reports_and_the_tags_are_named_as_written():
    assert view.MARKS_HEADER == "☆⚖︎文"
    assert view.marker_tag_names("Surasura") == ["Surasura::☆", "Surasura::⚖", "Surasura::文"]


# --- the answers, the run ------------------------------------------------------------------------------------------ #
_SUGGESTIONS = [{"word": "おばあさん", "key": "お婆さん", "rank": 10, "answer": None, "via": "kana"},
                {"word": "眼鏡", "key": "メガネ", "rank": 20, "answer": "yes", "via": None}]


def test_the_answers_recorded_are_every_new_one_and_each_changed_earlier_one():
    stats = {"suggestions": _SUGGESTIONS}
    ticks = view.initial_ticks(stats)
    assert ticks == {"おばあさん": False, "眼鏡": True}
    assert view.answers_to_record(stats, ticks) == [("おばあさん", "お婆さん", False, "kana")]
    ticks["眼鏡"] = False
    assert view.changed_ticks(stats, ticks) == {"眼鏡": False}
    assert ("眼鏡", "メガネ", False, None) in view.answers_to_record(stats, ticks)


def test_answers_that_cannot_be_saved_stop_the_run_before_any_write():
    with mock.patch("modules.junban.pairs.record", side_effect=OSError("disk full")), \
            mock.patch("modules.junban.reposition.run") as run:
        report = view.reorder_work(saved(), "ja", [("おばあさん", "お婆さん", True, None)])
    assert run.call_count == 0 and report["ok"] is False and "nothing was reordered" in report["message"]


def test_the_answers_are_saved_before_the_run_reads_them():
    order = []
    with mock.patch("modules.junban.pairs.record", side_effect=lambda *a: order.append("answers")), \
            mock.patch("modules.junban.reposition.run",
                       side_effect=lambda *a, **k: order.append(("run", type(k["job"]))) or {"ok": True}):
        view.reorder_work(saved(), "ja", [("おばあさん", "お婆さん", True, None)])
    assert order == ["answers", ("run", spaced.Job)]


def test_the_windows_own_run_always_carries_its_spaced_job():
    # IK-11 (Haya): every manual run carries the job — the session sync before its first write comes with it.
    for settings in (saved(), saved(junban_replan_preview=False, connect_enabled=False), saved(enable_junban=False)):
        assert isinstance(view.window_job(settings), spaced.Job)


def test_the_sync_first_guess_reads_the_rules_state():
    from app import anki_sync_rule
    with mock.patch.object(anki_sync_rule, "read_state", return_value={}):
        assert view.session_sync_likely() is True                 # no session yet: S1 syncs first
    fresh = {"session_at": time.time(), "profile": "User 1", "last_write": time.time()}
    with mock.patch.object(anki_sync_rule, "read_state", return_value=fresh):
        assert view.session_sync_likely() is False
    failed = {"s1_failed_at": time.time()}
    with mock.patch.object(anki_sync_rule, "read_state", return_value=failed):
        assert view.session_sync_likely() is False                # failed a moment ago: not tried again yet


def test_a_run_that_raises_is_a_report_never_a_traceback():
    with mock.patch("modules.junban.reposition.run", side_effect=RuntimeError("Anki went away")):
        report = view.reorder_work(saved(), "ja", [])
    assert report["ok"] is False and report["problems"] == ["Anki went away"]
    with mock.patch("modules.junban.reposition.restore", side_effect=RuntimeError("gone")):
        assert view.restore_work(saved(), confirmed="2026-10-14T10:00:00")["message"] == "Nothing was restored."


def test_restore_offers_an_unfinished_automatic_run_first_then_the_snapshot_it_names():
    with mock.patch("modules.junban.undo.unfinished", return_value="run-7"), \
            mock.patch("modules.junban.undo.describe_run", return_value="run-7: 12 cards in TheBank"), \
            mock.patch("modules.junban.undo.restorable") as restorable:
        q = view.restore_question("ja", saved())
    assert q == {"kind": "run", "run": "run-7", "body": "run-7: 12 cards in TheBank"} and restorable.call_count == 0
    snapshot = {"written_at": "2026-10-14T10:00:00", "cards": {"1": 2}, "scope": ["TheBank"]}
    with mock.patch("modules.junban.undo.unfinished", return_value=None), \
            mock.patch("modules.junban.undo.restorable", return_value=snapshot):
        q = view.restore_question("ja", saved())
    assert q["kind"] == "snapshot" and q["confirmed"] == "2026-10-14T10:00:00" and "1 card saved from TheBank" in q["body"]
    with mock.patch("modules.junban.undo.unfinished", return_value=None), \
            mock.patch("modules.junban.undo.restorable", return_value=None):
        assert view.restore_question("ja", saved())["kind"] == "none"


def test_restore_asks_only_for_the_windows_own_decks():
    # Haiku H5: asked with no scope, Restore offered (and could write back) a snapshot taken for another deck.
    from modules.junban import undo
    with mock.patch("modules.junban.undo.unfinished", return_value=None), \
            mock.patch("modules.junban.undo.restorable", return_value=None) as restorable:
        view.restore_question("ja", saved(junban_scope="deck", junban_deck="Kanji"))
        view.restore_question("ja", saved(junban_scope="all"))
    assert [c.args for c in restorable.call_args_list] == [("ja", ["Kanji"]), ("ja", undo.ALL_DECKS)]


def test_a_finished_runs_lines_keep_card_and_note_failures_apart():
    lines = view.report_lines({"ok": False, "message": "Junban did not finish.", "problems": ["refused"],
                               "failures": [(1701, "x")], "note_failures": [(2701, "y")]})
    assert [t for t, _ in lines] == ["refused", "Junban did not finish.",
                                     "1 card(s) could not be changed; the first was 1701.",
                                     "1 note(s) could not be updated; the first was 2701."]


# --- the window's lock ------------------------------------------------------------------------------------------------ #
def test_the_window_lock_is_held_then_let_go():
    from modules.junban import auto
    lock = view.WindowLock()
    assert lock.hold() and lock.holding() and auto.window_open()
    lock.release()
    deadline = time.monotonic() + 5
    while auto.window_open() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not auto.window_open() and not lock.holding()


def test_a_hold_landing_after_the_window_closed_lets_go_at_once():
    from modules.junban import auto
    lock = view.WindowLock()
    lock.release()                                   # closed before the hold's worker got there (the Tk D5)
    assert lock.hold() is False and not lock.holding()
    assert not auto.window_open()


# --- Put Anki back's flow ------------------------------------------------------------------------------------------- #
_PLAN = {"ok": True, "taken_at": "2026-10-13T21:04:00", "cards_back": 12, "added_after": 3, "unsuspend": 2,
         "fields_unedited": 4, "fields_edited": 1, "older_suspended": 5, "older_tags": 0, "profile": "User 1"}


def test_the_put_back_confirmation_keeps_its_counts_and_one_way_line():
    out = put_back_view.outcome(_PLAN)
    question, details = out["ask"]
    assert question == "Put Anki back the way it was before Surasura?"
    assert details[-1] == put_back_view.ONE_WAY and any("12 new cards back" in d for d in details)
    assert out["fields"].endswith("the 4 you haven't edited?") and out["older"].endswith("Unsuspend them?")


@pytest.mark.parametrize("plan_, line", [
    ({"ok": False, "nothing": True}, put_back_view.NOTHING),
    ({"ok": True, "nothing": True}, put_back_view.NOTHING_LEFT),
    ({"ok": False, "anki_closed": True}, put_back_view.ANKI_CLOSED),
    ({"ok": False, "wrong_profile": "User 1"}, 'Open the profile "User 1" in Anki first: nothing was changed.'),
    ({"ok": False, "problems": ["one", "two"]}, "two"),
])
def test_a_plan_that_writes_nothing_ends_in_one_line(plan_, line):
    out = put_back_view.outcome(plan_)
    assert "ask" not in out and out["end"][0] == line


def test_the_plan_reads_only_and_the_write_carries_the_profile_it_described():
    from modules.junban import first_touch
    calls = []
    with mock.patch.object(first_touch, "has_anything", return_value=True), \
            mock.patch.object(first_touch, "plan", side_effect=lambda s, language: calls.append("plan") or _PLAN), \
            mock.patch.object(first_touch, "put_back",
                              side_effect=lambda s, **k: calls.append(("put_back", k.get("profile"),
                                                                       k.get("older"), k["fields"]))
                              or {"ok": True, "message": "Put back."}):
        planned = put_back_view.plan_work("ja", saved())
        assert calls == ["plan"] and planned["_settings"]["target_language"] == "ja"
        report = put_back_view.put_back_work("ja", planned["_settings"], True, False, planned)
    assert calls[1] == ("put_back", "User 1", False, True) and report["ok"]


def test_nothing_kept_ends_before_anki_is_asked_anything():
    # The Tk worker's first step: with no saved order at all, the plan never reaches Anki — the answer is "nothing to
    # put back", not whatever a read of Anki says (closed, another profile) about cards Surasura never moved.
    from modules.junban import first_touch
    with mock.patch.object(first_touch, "has_anything", return_value=False), \
            mock.patch.object(first_touch, "plan", side_effect=AssertionError("Anki was asked")) as asked:
        planned = put_back_view.plan_work("ja", saved())
    assert planned == {"ok": False, "nothing": True} and not asked.called
    assert put_back_view.outcome(planned)["end"][0] == put_back_view.NOTHING


def test_first_touch_gui_names_the_same_helpers():
    # A pure move: the Tk flow and Settings' 2.x door keep every name, the very same objects.
    pytest.importorskip("tkinter")
    from modules.junban import first_touch_gui
    for name in ("BUTTON_TEXT", "BUTTON_TIP", "TITLE", "ONE_WAY", "ANKI_CLOSED", "NOTHING", "NOTHING_LEFT",
                 "available", "confirm_text", "fields_question", "older_question", "closing_lines", "backfill_line",
                 "_count", "_date", "_module"):
        assert getattr(first_touch_gui, name) is getattr(put_back_view, name), name
    from modules.junban import gui
    assert isinstance(gui.window_job({}), spaced.Job) and gui.MARKER_GLYPHS == view.MARKER_GLYPHS
    assert gui.DESELECTED_GLYPH == view.DESELECTED_GLYPH and gui.MAX_PREVIEW_ROWS == view.MAX_PREVIEW_ROWS


def test_view_models_import_no_toolkit():
    import subprocess
    import sys
    code = ("import sys, modules.junban.junban_view, modules.junban.put_back_view; "
            "print([m for m in sys.modules if m.startswith(('tkinter', 'PyQt6'))])")
    out = subprocess.run([sys.executable, "-c", code], cwd=_ROOT, capture_output=True, text=True, timeout=120,
                         env=dict(os.environ, PYTHONPATH=_ROOT))
    assert out.returncode == 0, out.stderr and out.stdout.strip().endswith("[]")
    assert out.stdout.strip().splitlines()[-1] == "[]"



def test_a_thrown_away_preview_leaves_no_key_behind():
    # Two locks on one door: `ready` needs the dry run too, but a key that outlives its preview must not exist.
    s = view.Session()
    _landed(s)
    s.clear()
    assert s.scope is None and s.stats is None
    generation = s.ask()
    s.land(generation, ("k",), ("k",), None, {"ok": False, "problems": ["Anki is not running."]}, {})
    assert s.scope is None                                       # no preview read: no key either


def test_a_replan_of_an_earlier_preview_never_lands_on_a_new_one_with_the_same_token():
    s = view.Session()
    old_generation = _landed(s)
    s.toggle_row(s.stats["order"][0].card_id)
    s.replan_asked()                                             # token 1 of the old preview
    stale = view.preview_view(**_frozen(s))
    _landed(s)                                                   # a new preview (its tokens start again)
    token = s.replan_asked()                                     # token 1 of the new one
    assert not s.replan_landed(old_generation, token, stale)
    assert not s.ready(("k",))


def test_a_second_click_brings_the_row_back():
    s = view.Session()
    _landed(s)
    card_id = s.stats["order"][0].card_id
    assert s.toggle_row(card_id) and s.deselected == {card_id}
    assert s.toggle_row(card_id) and s.deselected == set()


def test_after_a_language_switch_only_the_new_languages_own_deck_previews_by_itself():
    # AD6-7: `junban_deck` is one key for both languages; after a switch the window previewed the Japanese deck
    # against the Chinese list by itself. Only a deck the user picked for this language (the recorded pair) does.
    paired = saved(junban_replan_language="zh", junban_replan_deck="中文")
    assert view.previews_by_itself_after_a_switch(paired, "zh", controls(scope="deck", deck="中文"))
    assert not view.previews_by_itself_after_a_switch(paired, "zh", controls(scope="deck", deck="TheBank"))
    assert not view.previews_by_itself_after_a_switch(saved(junban_replan_language="ja", junban_replan_deck="TheBank"),
                                                      "zh", controls(scope="deck", deck="TheBank"))
    assert not view.previews_by_itself_after_a_switch(paired, "zh", controls(scope="all", deck="中文"))
    assert not view.previews_by_itself_after_a_switch(saved(), "zh", controls(scope="deck", deck=""))


def test_the_recorded_deck_is_only_its_own_languages():
    # Mutant F22: a deck picked in the Chinese window is never offered as the Japanese one after a switch.
    paired = saved(junban_replan_language="zh", junban_replan_deck=" 中文::Mining ")
    assert view.recorded_deck(paired, "zh") == "中文::Mining"
    assert view.recorded_deck(paired, "ja") == ""
    assert view.recorded_deck(saved(), "ja") == ""
