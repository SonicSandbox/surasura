# SPDX-License-Identifier: GPL-3.0-or-later
""""Put Anki back the way it was before Surasura…" without a toolkit (W3.4 row 6; FT-RUNBOOK D8).

The text helpers below were `first_touch_gui.py`'s (moved as they are: that file imports tkinter at its top, so a Qt
window importing them from there would drag Tk in); `first_touch_gui` imports them from here. Below them, the flow's
steps as plain functions — the Tk `PutBack`'s workers and its `_planned` decision, for a window that asks its own way
(the Qt window's in-window confirmations, `qt_put_back.py`): `plan_work` (reads only), `outcome` (what the plan says
to do next: one line and stop, or the questions), `put_back_work` (the write) and `finished_lines`.

Everything that reads or writes Anki lives in `first_touch` (`plan` reads only, `put_back` writes, holding the Anki-write
lock, saving the stand-aside settings strictly first and checking the profile the confirmation described).
"""

from datetime import datetime

BUTTON_TEXT = "Put Anki back the way it was before Surasura…"
BUTTON_TIP = ("Puts Anki's new cards back in the order they had before Surasura first changed them: the cards "
              "you've studied since stay as they are, and cards added since go after them in the order you added "
              "them. Unsuspends only the cards Surasura suspended, takes Surasura's tags and flags off, and offers "
              "Backfill's fields back where you haven't edited them. Asks first, with the counts. Needs Anki open.")
TITLE = "Put Anki back"

# `first_touch`'s own lines (ANKI_CLOSED, NOTHING), repeated so this file imports nothing of Junban's at the top.
ANKI_CLOSED = "Open Anki first: nothing was changed."
NOTHING = "Surasura hasn't changed this language's Anki cards."
NOTHING_LEFT = "Nothing left to put back: nothing was changed."
ONE_WAY = "This can't be undone. To have Surasura's order again, re-order in 順."         # C15


def _module():
    """`first_touch`, read at call time (a test stubs its functions on the module)."""
    from modules.junban import first_touch
    return first_touch


def available(language):
    """Is there anything to put back for `language`? Local files only, never Anki; False on any failure."""
    try:
        return bool(_module().has_anything(language))
    except Exception:
        return False


def _count(number, one, many=None):
    number = int(number or 0)
    return f"{number:,} {one if number == 1 else (many or one + 's')}"


def _date(taken_at):
    """`2026-10-13T21:04:00` -> `13 October 2026`; the text as it is when it isn't a date."""
    try:
        when = datetime.fromisoformat(str(taken_at))
        return f"{when.day} {when:%B %Y}"
    except (TypeError, ValueError):
        return str(taken_at or "") or "an unknown date"


def confirm_text(plan):
    """-> `(question, details)`: D8's one confirm, from `plan()`'s counts. `earlier` names the order Surasura kept
    then, never "before Surasura" — no order from before it was ever kept."""
    when = _date(plan.get("taken_at"))
    if plan.get("earlier"):
        question = f"Put Anki back the way Surasura kept it on {when}?"
        order = f"in the order Surasura kept on {when}"
    else:
        question = "Put Anki back the way it was before Surasura?"
        order = f"in their order of {when}"
    details = []
    cards = int(plan.get("cards_back") or 0)
    added = int(plan.get("added_after") or 0)
    made = int(plan.get("made_after") or 0)
    if cards:
        details.append(f"{_count(cards, 'new card')} back {order}; cards you've studied since stay as they are")
    if added:
        details.append(f"{_count(added, 'card')} added since go after them, in the order you added them")
    if made:                                    # C18: never counted as yours
        details.append(f"{_count(made, 'card')} Surasura made go after yours")
    if plan.get("unsuspend"):
        details.append(f"{_count(plan['unsuspend'], 'card')} Surasura suspended unsuspended")
    if plan.get("tags_off"):
        details.append(f"Surasura's tags off {_count(plan['tags_off'], 'note')}")
    if plan.get("flags"):
        details.append(f"{_count(plan['flags'], 'flag')} cleared")
    if not details:
        details.append("Nothing is out of place.")
    # C17: what Surasura stops doing by itself, said before anything is written (FT-1).
    if plan.get("stands_aside"):
        details.append(f"Surasura won't re-order {plan['stands_aside']} by itself until you pick it in 順 again")
    if plan.get("backfill_fills") is not None and int(plan.get("fields_unedited") or 0):
        details.append(f"If you put the fields back, {backfill_line(plan, will=True)}")
    # K14 / C15: Anki keeps no undo of its own for any of it.
    details.append(ONE_WAY)
    return question, details


def backfill_line(plan, will=False):
    """C16: Backfill's automatic step, switched off with the fields put back — named with what it fills."""
    deck = str((plan or {}).get("backfill_fills") or "").strip()
    fills = deck if deck else "all your decks"
    return (f"Backfill's automatic step {'will be' if will else 'is'} off — it fills {fills}; turn it back on in "
            "Settings.")


def fields_question(plan):
    """The second question, asked only when the old text can go back somewhere (`fields_unedited`). K14: Junban's
    own field writes (the frequency field) are named beside Backfill's."""
    unedited = int(plan.get("fields_unedited") or 0)
    filled = unedited + int(plan.get("fields_edited") or 0)
    who = f"Backfill and 順 (the frequency field) filled {_count(filled, 'note')}"
    if filled == unedited:
        return f"{who}: put the old text back in them?"
    return f"{who}: put the old text back in the {unedited:,} you haven't edited?"


def older_question(plan):
    """K4: the changes from before the record, in its decks, offered once Anki holds them (`older_suspended`,
    `older_tags`). C10: said as Anki shows them — the cards carry Surasura's tag; who suspended them it can't know."""
    suspended = int(plan.get("older_suspended") or 0)
    tagged = int(plan.get("older_tags") or 0)
    cards = f"{_count(suspended, 'suspended card')} carry Surasura's 'later' tag"
    notes = f"{_count(tagged, 'note')} carry Surasura's tags"
    if suspended and tagged:
        return (f"{cards}, and {notes}, from before it kept this record. Unsuspend those cards and take the older "
                "tags off?")
    if suspended:
        return f"{cards}, from before it kept this record. Unsuspend them?"
    return f"{notes} from before it kept this record. Take them off?"


def closing_lines(plan, report):
    """K5 / K6: what the put-back left alone, and what Surasura stopped doing by itself (`settings_changed`)."""
    lines = []
    made = int((plan or {}).get("made_left") or 0) if report.get("ok") else 0
    if made == 1:
        lines.append("1 card Surasura made is left as it is; Connect's Undo this batch removes it.")
    elif made:
        lines.append(f"{made:,} cards Surasura made are left as they are; Connect's Undo this batch removes them.")
    changed = report.get("settings_changed") or ()
    if "junban_replan_deck" in changed:
        lines.append("Surasura won't re-order this deck by itself until you pick it in 順 again.")
    if "junban_auto_backfill" in changed:      # C16: only when its step went off, and what it fills
        lines.append(backfill_line(plan))
    return lines


# --- the flow's steps, for a window that asks its own way (W3.4 row 6) -------------------------------------------- #
def plan_settings(language, settings=None):
    """The settings to hand `first_touch` (the Tk `PutBack._settings`): the door's, or — on a worker — the file's.
    C29: a file that can't be read gives Surasura's defaults (never an empty dict) and says so. -> (settings, line)."""
    if settings is not None:
        return dict(settings, target_language=language), None
    from app import settings_manager
    line = None
    try:
        loaded = settings_manager.load_settings(strict=True) or {}
    except Exception as e:
        line = f"Your settings couldn't be read ({e}): Surasura's defaults are used."
        loaded = settings_manager.load_settings() or {}
    return dict(loaded, target_language=language), line


def plan_work(language, settings=None):
    """(A worker.) The Tk `_plan_worker`: nothing kept → `{"ok": False, "nothing": True}`; else `first_touch.plan`
    (reads only), with the settings it was made with under `_settings`; a failure is its answer. A settings line
    (C29) rides along as `_line`."""
    line = None
    try:
        if not _module().has_anything(language):
            result = {"ok": False, "nothing": True}
        else:
            settings, line = plan_settings(language, settings)
            result = _module().plan(settings, language=language)
            result = dict(result or {}, _settings=settings)
    except Exception as e:                      # a window must never lose its answer to a traceback
        result = {"ok": False, "problems": [str(e)]}
    if line:
        result = dict(result, _line=line)
    return result


def outcome(plan):
    """What the plan says to do next (the Tk `_planned`, its decisions alone). -> a dict:
    `lines` [(text, tone)] said first (a broken order file set aside, K10); then either `end` (a final line, tone)
    with nothing written, or `ask`: the confirmation's (question, details), `fields` (the fields question, or None
    when nothing can go back) and `older` (K4's question, or None)."""
    plan = plan or {}
    lines = []
    if plan.get("_line"):
        lines.append((plan["_line"], "warning"))
    older = int(plan.get("older_suspended") or 0) + int(plan.get("older_tags") or 0)
    aside = list(plan.get("set_aside") or ())
    if aside:                                   # K10: a broken order file was set aside (never deleted)
        lines.append((f"{_count(len(aside), 'saved order')} couldn't be read and "
                      f"{'was' if len(aside) == 1 else 'were'} set aside: {', '.join(aside)}.", "warning"))
    if plan.get("nothing") and not (plan.get("ok") and older):  # nothing kept, or all of it already back
        return {"lines": lines, "end": (NOTHING_LEFT if plan.get("ok") else NOTHING, "warning")}
    if plan.get("anki_closed"):
        return {"lines": lines, "end": (ANKI_CLOSED, "problem")}
    if plan.get("wrong_profile"):
        return {"lines": lines,
                "end": (f'Open the profile "{plan["wrong_profile"]}" in Anki first: nothing was changed.', "problem")}
    if not plan.get("ok"):
        problems = list(plan.get("problems") or ())
        lines += [(line, "problem") for line in problems[:-1]]
        return {"lines": lines, "end": (problems[-1] if problems else "Nothing was changed.", "problem")}
    return {"lines": lines, "ask": confirm_text(plan),
            "fields": fields_question(plan) if int(plan.get("fields_unedited") or 0) else None,
            "older": older_question(plan) if older else None}


def put_back_work(language, settings, fields, older, plan, progress=None, cancel=None, on_wait=None):
    """(A worker.) The Tk `_put_back_worker`: `first_touch.put_back` with the answers — `older` only when K4's
    question was asked (None: not asked), the profile the confirmation was about (C8) — never past a traceback."""
    extra = {} if older is None else {"older": older}
    if (plan or {}).get("profile") is not None:     # C8: the profile the confirm was about, or nothing is written
        extra["profile"] = plan["profile"]
    try:
        report = _module().put_back(settings, language=language, fields=fields, progress=progress,
                                    wait=None, cancel=cancel, on_wait=on_wait, **extra)
    except Exception as e:
        report = {"ok": False, "message": "Nothing was put back.", "problems": [str(e)]}
    return report or {}


def finished_lines(report, plan=None):
    """The Tk `_finished`'s lines: warnings, problems but the message (said once), the message, then K5 / K6's
    closing lines. -> [(text, tone)]."""
    report = report or {}
    message = report.get("message") or ""
    lines = [(line, "warning") for line in report.get("warnings") or ()]
    lines += [(line, "problem") for line in report.get("problems") or () if line != message]
    lines.append((message, "good" if report.get("ok") else "problem"))
    lines += [(line, "") for line in closing_lines(plan, report)]
    return [(text, tone) for text, tone in lines if text]
