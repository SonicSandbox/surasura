# SPDX-License-Identifier: GPL-3.0-or-later
"""Junban's automatic reorder — a TEST option, switched on by hand in settings.json.

The user (2026-09-23): run it "like the anki sync", after a Generate and when coming back to
Surasura, "super uninvasive for the checks", a line in settings they can switch to true. So:

    "junban_auto_reorder": true    — reorder automatically (off by default)
    "junban_auto_actions": true    — and apply everything the panel has saved, the touch-ups and
                                     the cards-not-on-your-list actions (suspend included) — off,
                                     it moves positions and writes nothing else

**It writes without a preview**, the one thing the panel exists to prevent (invariant I5), which is
why it is opt-in by hand and holds to every other guard: the same preflight, the same snapshot before
the first write — so `Undo the last reorder` in the panel undoes the last automatic run — and the
same refusal after an interrupted run. On top of those, it only ever acts when nothing about the
moment is unusual, and stays silent when it does not:

  * one nominated deck — never "All decks" automatically (the user's A4);
  * Anki running (a closed port is simply "not now");
  * not while the user is reviewing in Anki (`guiReviewActive`, A5);
  * a list that is up to date — the Generate button's own question, asked by the dashboard
    (`list_current`); without it, a list no older than the library;
  * and it does not send Anki's window to the deck list afterwards (`refresh=False`).

The dashboard calls `run_quietly` on a background thread (`app/main.py` `_maybe_junban_auto`) and
shows a spinner on the 順 button while it runs, as it does on the Anki button for the known-words sync.

The automatic Backfill (2026-09-24, a test option too)
-----------------------------------------------------
    "junban_auto_backfill": true    — after the reorder, fill the NEW cards' EMPTY fields

One job, two switches, a fixed order: the reorder first (when it is on), then the Backfill (when it
is on) — each can run without the other. The Backfill step writes only empty fields on new cards,
whatever the Backfill window is set to (`backfill.run_auto`), under the same "nothing unusual about
the moment" guards: Anki running, the user not reviewing. It keeps its own snapshot, so the window's
Restore undoes it without touching the reorder's.
"""

import os

from app import anki_connect
from modules.junban import ankiconnect, connect, reposition, spaced

# What "reorder only" leaves out: every note or card write beyond the positions themselves.
_POSITIONS_ONLY = {"junban_tag": "", "junban_tag_markers": False, "junban_write_frequency": False,
                   "junban_write_freqsort": False,
                   "junban_later_tag": False, "junban_later_flag": False, "junban_later_suspend": False,
                   "junban_show_tags": False}


def _reorder_on(settings):
    return settings.get("junban_auto_reorder") is True


def _backfill_on(settings):
    return settings.get("junban_auto_backfill") is True


def enabled(settings):
    """On only when the module and at least one automatic step are switched on — explicitly True."""
    settings = settings or {}
    return settings.get("enable_junban") is True and (_reorder_on(settings) or _backfill_on(settings))


def window_open():
    """Is a 順 window open — in this program or another? While open it holds the `junban-window` lock (P0.3 04 §2;
    `gui.JunbanGui`), so this asks the lock, never a widget: a reader's look (`locks.in_use`) that takes no turn and
    writes no record, so two looks at once never read each other as an open window."""
    from app import locks
    return locks.in_use("junban-window")


def blocked(settings, window=True):
    """Why no automatic reorder may run now — a short reason — or None. The guards every caller shares (the
    dashboard's trigger, `surasura-cli junban --auto`), moved out of the dashboard (P1.2):

      * `SURASURA_NO_ANKI_SYNC` (the test suites, a developer's run): Anki is never reached;
      * the module switched off (`enable_junban`);
      * an update waits for Surasura's programs (K75; the window's own hold — the command line answers
        `update-staged` before it gets here);
      * a 順 window is open — the user is ordering by hand there, and a write underneath would make the preview on
        their screen describe a queue that has moved (`window=False` leaves this one look, a lock file's, to the
        caller's worker: the dashboard asks the rest on its own thread).
    """
    if os.environ.get("SURASURA_NO_ANKI_SYNC"):
        return "Anki is switched off for this run (SURASURA_NO_ANKI_SYNC)"
    if (settings or {}).get("enable_junban") is not True:
        return "順 is switched off"
    try:
        from app import updater
        if updater.children_held():
            return "an update is waiting"
    except Exception:
        pass
    if window and window_open():
        return "the 順 window is open"
    return None


def run_quietly(settings, list_current=None, job=None):
    """The automatic steps, in order — the reorder, then the Backfill — each only when switched on.
    Returns one line for the dashboard's log, or `""` when there is nothing worth saying. Never raises.

    `list_current` is the dashboard's answer to "would Generate compute anything new?"
    (`app.main.journey_is_current`) — the reorder waits on False; the Backfill does not read the list.
    `job`: the caller's `spaced.Job`, or None (`reorder`)."""
    settings = dict(settings or {})
    if not enabled(settings):
        return ""
    lines = []
    if _reorder_on(settings):
        lines.append(_reorder_quietly(dict(settings), list_current, job))
    if _backfill_on(settings):
        lines.append(_backfill_quietly(dict(settings)))
    return " ".join(line for line in lines if line)


def _backfill_quietly(settings):
    """One automatic Backfill: new cards, empty fields (`backfill.run_auto`). Never raises."""
    try:
        url = reposition._url(settings)
        if not ankiconnect.probe(url).get("ok"):
            return ""
        if anki_connect.patient("guiReviewActive", url) is True:
            return ""
        from modules.junban import backfill
        report = backfill.run_auto(settings)
    except Exception as e:          # a background job must never take the window down
        if anki_connect.is_busy(e):         # Anki busy with a collection operation (its sync, #370): not now
            return ""
        return f"Backfill (automatic) skipped: {e}"
    if report.get("busy") or report.get("anki_busy"):  # another writer holds Anki (E1.4), or Anki is busy: not now,
        return ""                                       # the next trigger tries again
    if not report.get("ok"):
        return f"Backfill (automatic) did not run: {(report.get('problems') or ['it could not finish'])[0]}"
    if not report.get("written"):
        return ""
    return f"Backfill (automatic): {report.get('message', '')}"


def decide_actions(settings, positions_only=False):
    """What an automatic re-order writes beyond the positions, decided in `settings` itself (and returned): every
    automatic caller asks here — this step, and on 3.0 the window's re-order (`app/replan_preview.Host`).

    2.x: while Connect's preview is on, the run is unattended: positions only, whatever `junban_auto_actions` says
    (G1.3-8: "just reorder for this version"). 3.0 (HY-6, `connect.UNATTENDED_ACTIONS`): Connect on strips nothing —
    `junban_auto_actions` and the actions' own settings decide. Positions only (with, from 3.0, the suspend setting's
    say while Connect is on) with the switch off, and with `positions_only`."""
    unattended = connect.preview_on(settings) and not connect.UNATTENDED_ACTIONS
    if positions_only or settings.get("junban_auto_actions") is not True or unattended:
        keep = {"junban_later_suspend"} if connect.suspends_unattended(settings) else set()
        settings.update({key: value for key, value in _POSITIONS_ONLY.items() if key not in keep})
    return settings


# Why an automatic reorder did not move anything — the dashboard stays silent, the command line answers with it.
NEEDS_DECK = "順 automatic reorder waits: it runs for one deck only — choose one in the 順 window."


def reorder(settings, list_current=None, positions_only=False, run_id=None, job=None, cards_out=False):
    """One automatic reorder, with every guard of the automatic step -> a dict:

      * `outcome`: "ran" (the report holds what was written), "needs-deck" (not one nominated deck), "anki-closed",
        "reviewing", "list-stale", "busy" (another Anki writer held the lock), "anki-busy" (Anki itself busy with a
        collection operation — its sync, Check Database — past `anki_connect.patient`'s wait, #370), "refused"
        (Junban's own refusal: `report["problems"]`), "failed" (`error`);
      * `report`: `reposition.run`'s report, when it ran or refused.

    `positions_only`: due positions and nothing else, whatever `junban_auto_actions` says (`surasura-cli junban
    --auto`, P0.3 03); otherwise the switch decides, as it always has. Never raises.

    Connect's preview (P1.4): the run is unattended — no returning word's card unsuspended before 3.0 — and, given a
    `run_id`, keeps a snapshot of its own. From 3.0 (`connect.UNATTENDED_SUSPEND`, G1.3-8) "positions only" still
    suspends the cards not on the list when Junban's suspend setting says so, recorded in that run's snapshot.

    `job` (a `spaced.Job`): the fast re-plan's preview is on (E1.1 03) — the run numbers spaced and is an
    automatic one (today's baseline, not the window's snapshot: 03 §5). None: 2.x-dev's 2.5 automatic reorder (dense)
    while the preview is off; 3.0 (E1.1 04 §5, W3.5 row 7): an automatic spaced job all the same, whatever D29, the
    language or the preview's box say.

    2.x-dev: a job moves positions only (04 §1). 3.0 (W3.5 row 7, Haya's G2b): the job handed on carries `actions`, so
    the run applies what this function decided below — after the positions, suspend last — and keeps one restore
    point: the window's snapshot (no `run_id`, as 2.5's automatic step did) or the run's own (`run_id`) instead of
    today's baseline whenever there is an action to write; with nothing to act on, today's baseline alone (and, given
    a `run_id`, the run's own snapshot too).

    `cards_out` (P4.1 L2): the caller records what the run changes for *Take its new cards out* in the store
    (`pins.record`, Connect's step) — the job says so (`spaced.Job.cards_out`); never with `positions_only`."""
    scope = str(settings.get("junban_scope") or "deck").strip().lower()
    if scope != "deck" or not str(settings.get("junban_deck") or "").strip():
        return {"outcome": "needs-deck"}
    try:
        url = reposition._url(settings)
        if not ankiconnect.probe(url).get("ok"):
            return {"outcome": "anki-closed"}
        if anki_connect.patient("guiReviewActive", url) is True:
            return {"outcome": "reviewing"}
        language = reposition._language(settings)
        if list_current is False or (list_current is None and reposition.list_is_stale(
                language, reposition.order_csv_path(settings))):
            return {"outcome": "list-stale"}
        decide_actions(settings, positions_only)
        extra = {"unattended": True, "run_id": run_id} if connect.preview_on(settings) else {}
        if job is None:
            # One numbering scheme (rule 8): every automatic reorder — 2.5's step where the preview can't run,
            # AutoJunban, the command line — numbers spaced. 3.0 (E1.1 04 §5, W3.5 row 7): always, whatever D29, the
            # language or the preview's box say (2.x numbered dense while the preview was off for this language).
            job = spaced.Job(automatic=True)
        # One already automatic is passed as it is: the caller reads back what the run filled in (E3.1's line).
        # 2.x-dev: `reposition._run` makes every automatic job positions only. 3.0 (Haya's G2b): the settings above are
        # already decided, so the job says so (`actions`) and the run applies them — as the window's re-order host's
        # job does on 3.0 (`decide_actions`, its settings decided the same way).
        extra["job"] = job if job.automatic else spaced.Job(automatic=True, rows=job.rows, cards=job.cards,
                                                            front=job.front, places=job.places)
        extra["job"].actions = True
        extra["job"].cards_out = bool(cards_out) and not positions_only        # P4.1 L2
        report = reposition.run(settings, refresh=False, verb=anki_connect.AUTOMATIC_STEP, **extra)
    except Exception as e:          # a background job must never take the window down
        if anki_connect.is_busy(e):
            return {"outcome": "anki-busy"}
        return {"outcome": "failed", "error": str(e)}
    if report.get("reviewing"):     # a review started while it planned: nothing written (P1.4, §7.2)
        return {"outcome": "reviewing", "report": report}
    if report.get("busy"):          # another writer holds Anki (E1.4)
        return {"outcome": "busy", "report": report}
    if report.get("anki_busy") and not report.get("written"):   # Anki busy with a collection operation: nothing
        return {"outcome": "anki-busy", "report": report}       # written (part written: it ran, the rest wait)
    if not report.get("ok"):
        return {"outcome": "refused", "report": report}
    return {"outcome": "ran", "report": report}


def _reorder_quietly(settings, list_current=None, job=None):
    """One automatic reorder, or a quiet reason not to. `""` when there is nothing worth saying
    (Anki closed, the user reviewing, the list out of date, every card already in place)."""
    done = reorder(settings, list_current, job=job)
    outcome, report = done["outcome"], done.get("report") or {}
    if outcome == "needs-deck":
        return NEEDS_DECK
    if outcome == "failed":
        return f"順 automatic reorder skipped: {done['error']}"
    if outcome == "refused":
        problems = report.get("problems") or ["it could not finish"]
        return f"順 automatic reorder did not run: {problems[0]}"
    if outcome != "ran":            # Anki closed or busy, reviewing, the list behind, another writer: not now, quietly
        return ""
    if report.get("empty_list"):                # M-W2-1: nothing put away, and said so
        return f"順 (automatic): {report.get('message', '')}"
    if not report.get("written") and not any((report.get("later") or {}).values()):
        return ""
    return f"順 (automatic): {report.get('message', '')}"
