# SPDX-License-Identifier: GPL-3.0-or-later
"""順's view model (W3.4 row 6): everything the 順 window decides, without a toolkit.

The Tk window (`gui.py`, left as it is for 2.x and the `dashboard` verb) kept these rules inside its class; the Qt
window (`qt_junban.py`) paints what this file answers. Each piece names the Tk method it replaces (the inventory's §5):

* the engine settings from the controls (`engine_settings`, `touchup_settings`, `own_values`, `unlisted_value`:
  `_settings`, `_touchup_settings`, `_own_values`, `_unlisted_value`) — a fresh dict and fresh containers every time,
  an unticked box sends the disabling value, the clicked-off rows ride along as `junban_exclude_cards`, never saved;
* **the I5 scope key** (`scope_key`: `_scope_key`, its eleven parts) and **the gate** (`Session`): a preview is valid
  only for the key read when Preview was pressed. A redraw (a click, a tick, the earlier answers shown) never stamps
  it again — the Tk window's defect D1, fixed here: a preview that lands after a change, a language switch, a finished
  Reorder / Restore and a put-back each throw the preview away, so Reorder stays off until a new one;
* the keys the window saves (`window_keys`, `changed_keys`) and the (language, deck) pair rule (`pair_keys`:
  `_replan_values`) — only what changed, and the pair only on the user's own deck pick in the window's language;
* the button rules (`buttons`: `_sync_buttons`) and the Generate & preview state (`Session.must_generate`,
  `Session.list_updated`: `_must_generate`, `on_list_updated`; a Generate that never starts no longer sticks, D4);
* the workers' bodies (`preview_work`, `context_counts`, `reorder_work`, `restore_work`: `_preview_worker`,
  `_context_counts`, `on_reorder`'s answers + `_reorder_worker`, `_restore_worker`) and the restore decision
  (`restore_question`: `on_restore`);
* the preview itself (`preview_view`: `_show_preview` + `_with_deselection` + `_render_checks` +
  `_in_display_order`) → the rows, the counts, the match and fields lines and every message line — the sentence is
  Reorder's only confirmation (I5) — computed on a worker (4,000 rows re-planned take ~14 ms: never the GUI thread);
* the answers to record (`changed_ticks`, `answers_to_record`), the clauses (moved as they are), the report's lines
  (`report_lines`: `_show_report`) and the window's lifetime lock (`WindowLock`: `_hold_window_lock` / `_close`).

`window_job` is the Tk file's, repeated here as it is there (that file imports tkinter): the 順 window's own preview and
run carry a spaced job, so `anki_sync_rule` gives a manual re-order its session sync (IK-11, settled by Haya: the
rule's header says what 3.0 does).
"""
import threading
from collections import namedtuple

from modules.junban import match, reposition, spaced, touchup, undo, unlisted

# The report's glyphs — text, never emoji (gui.py's reasons) — and the preview's own marks.
MARKER_GLYPHS = {"star": "☆", "lopsided": "⚖︎", "reading": "文"}
DESELECTED_GLYPH = "✗"
CHECK_OFF, CHECK_ON = "☐", "☑"
CHECK_ROWS = 4
MAX_PREVIEW_ROWS = 4000
MARKS_HEADER = "".join(MARKER_GLYPHS[m] for m in match.MARKERS)

# The controls the window keeps, by name (`Controls`). `own_tag` is None when the Connect row isn't shown.
CONTROL_NAMES = ("scope", "deck", "order", "list_first", "phrases", "ready_first", "only_markers", "own_tag",
                 "order_all", "tag_on", "tag_name", "markers_on", "freq_on", "freq_field", "freqsort_on",
                 "later_tag", "later_flag", "later_suspend")
LATER = ("tag", "flag", "suspend")


def window_job(settings):
    """The 順 window's own preview and run: spaced numbers (E1.1 03; one numbering for every Junban writer), its
    snapshot as in 2.5 (not automatic). 3.0 (E1.1 04 §5, W3.5 row 7): always (gui.py's `window_job`, as it is)."""
    return spaced.Job()


def returning_clause(stats):
    """" Back on your list: unsuspend 2 cards Junban had set aside." — MR-R3's promise (Connect's preview), stated
    before the write (I5); "" when there are none."""
    count = len((stats or {}).get("returning") or ())
    if not count:
        return ""
    return f" Back on your list: unsuspend {count} card{'' if count == 1 else 's'} Junban had set aside."


def marker_glyphs(marks):
    """The glyphs for one word's markers, in a stable order. `""` when it carries none."""
    marks = marks or ()
    return "".join(MARKER_GLYPHS[name] for name in match.MARKERS if name in marks)


# --- the controls -------------------------------------------------------------------------------------------------- #
def controls_from(saved, connect_row):
    """The controls as the window opens (the Tk `_build_*` initial values), from the saved settings. -> a dict."""
    saved = saved or {}
    chosen = set(match.normalize_markers(saved.get("junban_only_markers")))
    controls = {
        "scope": "all" if saved.get("junban_scope") == "all" else "deck",
        "deck": str(saved.get("junban_deck") or ""),
        "order": "priority" if saved.get("junban_order") == "priority" else "content",
        "list_first": str(saved.get("junban_unlisted") or "").strip().lower() != "journey",
        "phrases": saved.get("junban_phrases", True) is not False,
        "ready_first": saved.get("junban_ready_first") is True,
        "only_markers": tuple(name for name in match.MARKERS if name in chosen),
        "own_tag": None, "order_all": False,
        "tag_on": bool(str(saved.get("junban_tag") or "").strip()),
        "tag_name": str(saved.get("junban_tag") or "Surasura"),
        "markers_on": bool(saved.get("junban_tag_markers")),
        "freq_on": bool(saved.get("junban_write_frequency")),
        "freq_field": str(saved.get("junban_frequency_field") or "Frequency"),
        "freqsort_on": bool(saved.get("junban_write_freqsort")),
    }
    for name in LATER:
        controls[f"later_{name}"] = saved.get(f"junban_later_{name}") is True
    if connect_row:
        from modules.junban import connect
        controls["own_tag"] = connect.own_tag(saved)
        controls["order_all"] = connect.order_all(saved)
    return controls


def unlisted_value(controls, unlisted_saved):
    """`junban_unlisted` as "List first" says it: unticked "journey"; ticked "list_first" — or "back", kept when the
    file held it (the Tk `_unlisted_value`)."""
    if not controls.get("list_first"):
        return "journey"
    return "back" if str(unlisted_saved or "").strip().lower() == "back" else "list_first"


def own_values(controls):
    """`junban_own_tag` / `junban_order_all` as shown; {} when the Connect row isn't there (nothing handed on)."""
    if controls.get("own_tag") is None:
        return {}
    return {"junban_own_tag": str(controls["own_tag"]).strip(), "junban_order_all": bool(controls.get("order_all"))}


def touchup_settings(controls):
    """WP-L's keys as the controls read them: an unticked box sends the disabling value (an empty tag), so the engine
    is never handed a half-off switch and the preview describes the boxes the user can see."""
    return {
        "junban_tag": str(controls.get("tag_name") or "").strip() if controls.get("tag_on") else "",
        "junban_tag_markers": bool(controls.get("markers_on")),
        "junban_write_frequency": bool(controls.get("freq_on")),
        "junban_frequency_field": str(controls.get("freq_field") or "").strip(),
        "junban_write_freqsort": bool(controls.get("freqsort_on")),
        "junban_later_tag": bool(controls.get("later_tag")),
        "junban_later_flag": bool(controls.get("later_flag")),
        "junban_later_suspend": bool(controls.get("later_suspend")),
    }


def replan_on(saved, language):
    """The fast re-plan's switch for this window's language. Not built on 3.0 (`app/replan_preview.py`: never read;
    the RUNBOOK's superseded row) — read from the settings, as the Tk window opened it, and carried in the key."""
    from app import replan_preview
    saved = saved or {}
    return saved.get("junban_replan_preview") is True and replan_preview.preview_language(saved) == language


def engine_settings(saved, controls, language, deselected=(), unlisted_saved=None):
    """What the engine is handed: the saved settings plus what the controls say. A **fresh** dict, with a fresh
    `junban_word_fields` and `junban_only_markers` (a container in loaded settings is the one inside
    `SETTINGS_DEFAULTS` after the shallow merge: spec §13 #12)."""
    saved = dict(saved or {})
    overrides = saved.get("junban_word_fields")
    return dict(saved,
                target_language=language,
                junban_scope=controls.get("scope"),
                junban_deck=str(controls.get("deck") or "").strip(),
                junban_word_fields=dict(overrides) if isinstance(overrides, dict) else {},
                junban_order="priority" if controls.get("order") == "priority" else "content",
                junban_unlisted=unlisted_value(controls, unlisted_saved),
                junban_phrases=bool(controls.get("phrases")),
                junban_ready_first=bool(controls.get("ready_first")),
                junban_only_markers=list(controls.get("only_markers") or ()),
                junban_replan_preview=replan_on(saved, language),
                junban_exclude_cards=sorted(deselected),
                **own_values(controls),
                **touchup_settings(controls))


def scope_key(language, controls, replan, unlisted_saved=None):
    """What a preview is valid for — the I5 key, its eleven parts (the Tk `_scope_key`): the language, the scope, the
    deck, the order, List first, Phrases, i+1 first, the markers, the own-tag row, every touch-up and later action,
    and the re-plan switch. Changing ANY of it throws the preview away."""
    return (language, controls.get("scope"), str(controls.get("deck") or "").strip(),
            "priority" if controls.get("order") == "priority" else "content",
            unlisted_value(controls, unlisted_saved), bool(controls.get("phrases")),
            bool(controls.get("ready_first")), tuple(controls.get("only_markers") or ()),
            tuple(sorted(own_values(controls).items())),
            tuple(sorted(touchup_settings(controls).items())),
            bool(replan))


def window_keys(controls, unlisted_saved=None):
    """Every key the window owns, as the controls say them (the Tk `_save_scope`'s dict, without the pair)."""
    keys = {
        "junban_scope": controls.get("scope"),
        "junban_deck": str(controls.get("deck") or "").strip(),
        "junban_order": "priority" if controls.get("order") == "priority" else "content",
        "junban_unlisted": unlisted_value(controls, unlisted_saved),
        "junban_phrases": bool(controls.get("phrases")),
        "junban_ready_first": bool(controls.get("ready_first")),
        "junban_only_markers": list(controls.get("only_markers") or ()),
    }
    keys.update(own_values(controls))
    keys.update(touchup_settings(controls))
    return keys


def changed_keys(last, now):
    """The keys whose value differs from what the window last read or saved — the only ones it saves (the RUNBOOK:
    the window's own keys, only those the user changed). A fresh list for a list (never the caller's)."""
    out = {}
    for key, value in now.items():
        if key not in last or last[key] != value:
            out[key] = list(value) if isinstance(value, list) else value
    return out


def pair_keys(deck, window_language, main_language, picked):
    """3.0 (Haya's G3, W3.5 row 7): the user's pick of the deck in this window records the pair — this window's
    language and its deck — and only that pick, only while the main window shows the window's language (a deck still
    shown in another language's window is never recorded for it). Never 順's own first-deck pre-selection."""
    deck = str(deck or "").strip()
    if not (picked and deck) or window_language != main_language:
        return {}
    return {"junban_replan_language": window_language, "junban_replan_deck": deck}


def recorded_deck(saved, language):
    """The deck the user picked in `language`'s window (the recorded pair), or "" (IK-86: one deck key for both
    languages until W3.3's per-language deck — after a switch, the new language's own deck is the one shown)."""
    if saved.get("junban_replan_language") != language:
        return ""
    return str(saved.get("junban_replan_deck") or "").strip()


def previews_by_itself_after_a_switch(saved, language, controls):
    """After a language switch, may the window preview by itself (AD6-7)? `junban_deck` is one key for both languages:
    only a deck the user picked in this language's window (the recorded pair, `pair_keys`) is this language's — any
    other waits for the user's Preview (all decks too: they hold the other language's)."""
    deck = str(controls.get("deck") or "").strip()
    return bool(controls.get("scope") == "deck" and deck and saved.get("junban_replan_language") == language
                and str(saved.get("junban_replan_deck") or "").strip() == deck)


def touch_summary(controls):
    """What the "Also update the cards" caption lists as on, and whether "Cards not on your list" reads "No action"
    (the Tk `_sync_touchups`). -> (parts, no_action)."""
    parts = []
    if controls.get("tag_on") and str(controls.get("tag_name") or "").strip():
        parts.append("tag" + (" + markers" if controls.get("markers_on") else ""))
    if controls.get("freq_on") and str(controls.get("freq_field") or "").strip():
        parts.append("frequency")
    if controls.get("freqsort_on"):
        parts.append("sort number")
    later = [name for name in LATER if controls.get(f"later_{name}")]
    if later:
        parts.append("not on your list: " + " + ".join(later))
    return parts, not later


def marker_tag_names(tag):
    """The marker sub-tags the run writes (`touchup.marker_tag`): the tooltip names them as they are written (the Tk
    tooltip's "Surasura::star…" was stale: D6)."""
    return [touchup.marker_tag(tag or "Surasura", name) for name in match.MARKERS]


# --- the buttons --------------------------------------------------------------------------------------------------- #
def buttons(busy, generating, reorder_ready, must_generate, first_touch_kept, scope):
    """Who may be pressed now (the Tk `_sync_buttons`). `reorder_ready`: the session's gate. -> a dict; `preview_text`
    is "generating" · "generate" · "preview" (the window's words)."""
    idle = not busy and not generating
    return {"preview_text": "generating" if generating else "generate" if must_generate else "preview",
            "preview": idle, "restore": idle, "recheck": idle, "reorder": idle and bool(reorder_ready),
            "put_back": idle and bool(first_touch_kept), "deck": scope == "deck"}


# --- the gate and the session -------------------------------------------------------------------------------------- #
class Session:
    """One window's preview state, on the GUI thread. **The gate (I5):** `scope` is the key a preview was made for —
    set in `land` and nowhere else; `clear` (any control change, a language switch, a finished write, a put-back) bumps
    `generation`, so a preview asked for before it never lands. `ready(key)` is Reorder's one rule."""

    def __init__(self):
        self.generation = 0
        self.scope = None                 # the key the preview on screen was made for (None: no preview)
        self.stats = None                 # the last dry run, before any click
        self.checks = None
        self.settings = None              # the engine settings the preview was made with (a click re-plans with them)
        self.deselected = set()
        self.ticked = None
        self.display_order = []
        self.show_earlier = False
        self.view = None                  # the last view painted
        self.replanning = 0               # the newest re-plan asked for (a click's worker), 0: none pending
        self.replanned = 0
        self.list_current = None          # §16.9: is the list the preview reads up to date? None: can't tell
        self.generating = False
        self.generate_tried = False
        self.generate_run = None

    # --- asking and landing -------------------------------------------------------------------------------------- #
    def clear(self):
        """Throw the preview away — the rows, the clicked-off cards, the ticks — and every preview still on its way."""
        self.generation += 1
        self.scope = None
        self.stats = self.checks = self.settings = self.view = None
        self.deselected = set()
        self.ticked = None
        self.display_order = []
        self.show_earlier = False
        self.replanning = self.replanned = 0

    def ask(self):
        """Preview pressed: the old preview goes; -> the generation the new one must still match when it lands."""
        self.clear()
        return self.generation

    def land(self, generation, key, now_key, stats, checks, settings):
        """A preview arrived. Kept only when nothing was thrown away since it was asked (`generation`) and the key it
        was made for is still the controls' (`now_key`); else dropped. -> True when kept. The list's state is taken
        from its checks either way (§16.9)."""
        checks = checks or {}
        if "list_current" in checks and generation == self.generation:
            self.list_current = checks.get("list_current")
            if self.list_current is not False:
                self.generate_tried = False
        if generation != self.generation or key != now_key:
            return False
        self.stats, self.checks, self.settings = stats, checks, settings
        if stats is not None and self.ticked is None:
            self.ticked = initial_ticks(stats)
        self.scope = key if stats is not None else None
        return True

    def ready(self, now_key, busy=False):
        """Reorder's one rule: idle, a preview of THIS key on screen (I5), no click still being re-planned, and the
        list not known to be out of date (§16.9)."""
        return (not busy and not self.generating and self.stats is not None and self.scope is not None
                and self.scope == now_key and self.replanning == self.replanned and self.list_current is not False)

    # --- a click, a tick ----------------------------------------------------------------------------------------- #
    def toggle_row(self, card_id):
        """A row in or out of the run. The key is never stamped again; the window re-plans on a worker."""
        if self.stats is None or card_id is None:
            return False
        if card_id in self.deselected:
            self.deselected.discard(card_id)
        else:
            self.deselected.add(card_id)
        return True

    def toggle_tick(self, word):
        if self.stats is None or self.ticked is None or word is None:
            return False
        self.ticked[word] = not self.ticked.get(word)
        return True

    def toggle_earlier(self):
        if self.stats is None:
            return False
        self.show_earlier = not self.show_earlier
        return True

    def replan_asked(self):
        self.replanning += 1
        return self.replanning

    def replan_landed(self, generation, token, view):
        """A click's view came back: painted only if it is the newest asked for, of this same preview."""
        if generation != self.generation or token != self.replanning or self.stats is None:
            return False
        self.replanned = token
        self.view = view
        self.display_order = list(view.display_order)
        return True

    def replan_failed(self, generation, token):
        """The newest click's re-plan raised (AD6-11): the sentence on screen is not the run's, so the preview is
        thrown away (Reorder stays off until a new one). -> True when it was this preview's newest."""
        if generation != self.generation or token != self.replanning:
            return False
        self.clear()
        return True

    def frozen(self):
        """A copy of what a re-plan reads (for the worker: nothing it holds changes under it)."""
        return dict(stats=self.stats, checks=self.checks or {}, deselected=frozenset(self.deselected),
                    ticked=dict(self.ticked or {}), display_order=list(self.display_order),
                    show_earlier=self.show_earlier, settings=dict(self.settings or {}))

    # --- the list up to date (§16.9) ----------------------------------------------------------------------------- #
    def must_generate(self, can_generate):
        """Out of date, with a Generate to offer: Preview order generates."""
        return self.list_current is False and bool(can_generate)

    def list_updated(self, busy):
        """Any Generate ended (the Tk `on_list_updated`). -> True when this window was waiting for one and should
        preview again (it is idle); the generating state ends either way — a Generate that never started included
        (D4: it stuck, every button off until the window was reopened)."""
        waiting = self.generating or self.list_current is False
        self.generating = False
        self.generate_run = None
        if waiting and not busy:
            self.list_current = None      # the preview's worker asks again
            return True
        return False


def initial_ticks(stats):
    """§16: the ticks start as the answers the run would read — an earlier "yes" ticked."""
    return {entry["word"]: entry.get("answer") == "yes" for entry in (stats or {}).get("suggestions") or []}


def changed_ticks(stats, ticked):
    """`{card_word: ticked}` where the ticks differ from what the run would read today (the Tk `_changed_ticks`)."""
    entries = (stats or {}).get("suggestions") or []
    recorded = {entry["word"]: entry.get("answer") == "yes" for entry in entries}
    return {word: on for word, on in (ticked or {}).items() if word in recorded and recorded[word] != on}


def answers_to_record(stats, ticked):
    """What Reorder records (the Tk `_answers_to_record`): every word still to check (ticked = yes, unticked = no),
    and an earlier answer only where the user changed it."""
    out = []
    for entry in (stats or {}).get("suggestions") or []:
        on = bool((ticked or {}).get(entry["word"]))
        if entry.get("answer") is None or (entry.get("answer") == "yes") != on:
            out.append((entry["word"], entry["key"], on, entry.get("via")))
    return out


# --- the workers' bodies (each runs off the GUI thread) ------------------------------------------------------------ #
def list_current_of(settings, language):
    """Is the list the preview reads up to date? The Generate button's own question (`analyzer.journey_is_current`,
    as the Generate controller asks it); None when it can't tell. A worker's call."""
    try:
        from app import analyzer, run_args
        return analyzer.journey_is_current(run_args.analyzer_args(settings, language), language)
    except Exception:
        return None


def context_counts(settings, decks):
    """How many cards in scope 順 will NOT touch (the Tk `_context_counts`, as it is): review / learning and suspended,
    counted directly; best-effort, a failure omits its clause."""
    from modules.junban import ankiconnect
    url = reposition._url(settings)
    scope = decks if decks else []
    if not scope:
        return {}
    out = {}
    for key, clause in (("context_review", "-is:new -is:suspended"),
                        ("context_suspended", "is:suspended")):
        total = 0
        try:
            for deck in scope:
                safe = ankiconnect.escape_query(deck)
                total += len(ankiconnect.invoke("findCards", url, query=f'deck:"{safe}" {clause}'))
            out[key] = total
        except Exception:
            pass
    return out


def preview_work(settings, is_current=None):
    """The Tk `_preview_worker`: preflight → is the list current (the library-only warning dropped when it can tell)
    → `dry_run` with the window's job → the untouched counts. Writes nothing. -> (stats or None, checks)."""
    language = settings.get("target_language") or "ja"
    current = is_current(settings, language) if is_current is not None else None
    checks = dict(reposition.preflight(settings), list_current=current)
    if current is not None:
        checks["warnings"] = [line for line in checks.get("warnings") or [] if line != reposition.STALE_WARNING]
    if not checks["ok"]:
        return None, checks
    try:
        _writes, stats = reposition.dry_run(settings, job=window_job(settings))
    except Exception as e:
        return None, {"ok": False, "problems": [str(e)], "warnings": checks["warnings"], "decks": [],
                      "list_current": current}
    stats = dict(stats)
    stats.update(context_counts(settings, checks.get("decks") or []))
    stats["reordered_before"] = undo.has_reordered(language)    # backlog onboarding: the picture's rule
    return stats, checks


def probe_work(settings):
    """The Tk `_probe_worker`, handed its settings (D2: the Tk one read the widgets from the worker). -> (report,
    decks, warning line or None)."""
    from modules.junban import ankiconnect
    url = reposition._url(settings)
    report = ankiconnect.probe(url)
    decks, line = [], None
    if report.get("ok"):
        try:
            decks = ankiconnect.deck_names_with_new(url)
        except Exception as e:
            line = f"Could not list your decks: {e}"
    return report, decks, line


def session_sync_likely(now=None):
    """Will this run's first write start an AnkiWeb session — S1's ~2 s sync just before the first position request
    (IK-11, Haya: shown in the window and the bar, never a freeze)? Read from the sync rule's state as it stands (the
    profile it last saw): a guess for the words only, never a decision — the rule decides again inside the lock. A
    worker's call (it reads a file)."""
    import time
    try:
        from app import anki_sync_rule
        state = anki_sync_rule.read_state()
        now = time.time() if now is None else now
        if now - float(state.get("s1_failed_at") or 0) < anki_sync_rule.S1_RETRY_S:
            return False
        return bool(anki_sync_rule._new_session(state, state.get("profile"), now))
    except Exception:
        return False


def reorder_work(settings, language, answers, progress=None, cancel=None, on_wait=None):
    """Reorder's job: **the answers first** (§16: the run reads them; none saved → nothing reordered), then
    `reposition.run` with the window's job (another Anki writer waited for here; `cancel` stops the wait). Never past
    a traceback. -> the report."""
    if answers:
        try:
            from modules.junban import pairs
            pairs.record(language, answers)
        except OSError as e:
            return {"ok": False, "message": f"Could not save your answers, so nothing was reordered: {e}",
                    "problems": [], "warnings": [], "written": [], "failures": [], "unsaved": True}
    try:
        return reposition.run(settings, progress=progress, wait=None, cancel=cancel, on_wait=on_wait,
                              job=window_job(settings))
    except Exception as e:                          # a window must never lose a write to a traceback
        return {"ok": False, "message": "Junban did not finish.", "problems": [str(e)],
                "warnings": [], "written": [], "failures": []}


def put_back_then_reorder_work(settings, language, answers, runs, progress=None, cancel=None, on_wait=None):
    """*Put that one back, then reorder* (Junban-X2, Sonic 2026-11-13): a Reorder refused only for other decks' stopped
    runs of Connect's (`put_back_first`). Each of those runs put back exactly (`reposition.restore_run`: only the cards
    still where it put them — another deck's, so this deck's preview still holds), then Reorder's own job. One that
    can't be put back stops it there: nothing reordered, said. Never past a traceback. -> the report."""
    for run in runs or ():
        try:
            done = reposition.restore_run(settings, run, wait=None, cancel=cancel, on_wait=on_wait)
        except Exception as e:                      # a window must never lose a write to a traceback
            done = {"ok": False, "problems": [str(e)]}
        if not done.get("ok"):
            return dict(done, ok=False, message=PUT_BACK_FIRST_FAILED, warnings=done.get("warnings") or [],
                        written=[], failures=done.get("failures") or [])
    return reorder_work(settings, language, answers, progress=progress, cancel=cancel, on_wait=on_wait)


PUT_BACK_FIRST_FAILED = "The stopped reorder couldn't be put back, so nothing was reordered."      # PROVISIONAL


def try_work(settings, language, answers, progress=None, cancel=None, on_wait=None):
    """*Try it on my cards*' job (backlog onboarding): the answers first, as Reorder's (the order on screen is the one
    it reads), then `reposition.try_front` with the window's job — the preview's order, the sync rule as a Reorder —
    never past a traceback. -> the report."""
    if answers:
        try:
            from modules.junban import pairs
            pairs.record(language, answers)
        except OSError as e:
            return {"ok": False, "message": f"Could not save your answers, so nothing was moved: {e}",
                    "problems": [], "warnings": [], "written": [], "failures": [], "unsaved": True}
    try:
        return reposition.try_front(settings, progress=progress, wait=None, cancel=cancel, on_wait=on_wait,
                                    job=window_job(settings))
    except Exception as e:                          # a window must never lose a write to a traceback
        return {"ok": False, "message": "Junban did not make any changes.", "problems": [str(e)],
                "warnings": [], "written": [], "failures": []}


def show_work(settings, card_ids):
    """*Show them in Anki* (the backlog's picture: the cards you already know): Anki's browser on exactly those
    cards, sorted by due. Writes nothing. -> "sorted" / "plain"; raises `AnkiError` when Anki can't be reached."""
    from modules.junban import ankiconnect
    return ankiconnect.browse(reposition._url(settings), ankiconnect.cards_query(card_ids))


def restore_question(language, settings):
    """What Restore offers (the Tk `on_restore`'s decision; contract 10). An unfinished Connect run comes first —
    named, and offered even with no snapshot of the window's own; then the manual run's snapshot or today's baseline
    for the window's deck. A worker's call (it reads files). -> a dict: `kind` "run" (`run`, `body`) · "snapshot"
    (`confirmed`: the snapshot the user is asked about, `body`) · "none" (`line`)."""
    run = undo.unfinished(language, "reorder")
    if run is not None:
        return {"kind": "run", "run": run, "body": undo.describe_run(language, run)}
    snapshot = undo.restorable(language, reposition._restore_scope(settings))
    if not snapshot:
        return {"kind": "none", "line": undo.describe(None)}
    return {"kind": "snapshot", "confirmed": snapshot.get("written_at"), "body": undo.describe(snapshot),
            "both": bool(snapshot.get("finished_automatic")) and snapshot.get("complete") is not False}   # Disc-T1:
    # the Undo says it puts back both — once yours finished it (cut too, it is the plain question: nothing finished)


def restore_work(settings, confirmed=None, run=None, progress=None, cancel=None, on_wait=None):
    """Restore's job: only the confirmed snapshot (`confirmed`) or run id. Never past a traceback."""
    try:
        return reposition.restore(settings, progress=progress, wait=None, cancel=cancel, on_wait=on_wait,
                                  confirmed=confirmed, run=run)
    except Exception as e:
        return {"ok": False, "message": "Nothing was restored.", "problems": [str(e)],
                "warnings": [], "written": [], "failures": []}


def generate_argv(settings, language):
    """Generate & preview's run: the Generate controller's argv, quiet — the report not opened (the user,
    2026-09-23) — as the user's own request (never an automatic one that a click would replace)."""
    from app import run_args
    from app.services import generate
    return run_args.analyzer_args(settings, language) + [generate.PROGRESS_FLAG, "--no-open"]


# --- the clauses (moved as they are: gui.py's static methods) ------------------------------------------------------ #
def unmatched_clause(stats):
    count = (stats or {}).get("unmatched") or 0
    if not count:
        return ""
    return (f" {count} unmatched card{'' if count == 1 else 's'} (greyed) "
            f"keep{'s its' if count == 1 else ' their'} order at the back.")


def deselected_clause(stats):
    stats = stats or {}
    taken = stats.get("taken_off") or 0
    alone = (stats.get("deselected") or 0) - taken
    text = ""
    if taken:
        text += (" 1 you took off your list goes" if taken == 1 else
                 f" {taken} you took off your list go") + " with the cards not on it."
    if alone == 1:
        text += " 1 you left alone keeps its current order."
    elif alone:
        text += f" {alone} you left alone keep their current order."
    return text


def later_acts(stats):
    later = (stats or {}).get("later") or {}
    tagged = set(later.get("tag_notes") or ())
    flags, suspend = later.get("flags") or {}, set(later.get("suspend") or ())
    acts = {}
    for card_id in later.get("cards") or []:
        names = [name for name, hit in (("tag", (later.get("note_of") or {}).get(card_id) in tagged),
                                        ("flag", card_id in flags),
                                        ("suspend", card_id in suspend)) if hit]
        if names:
            acts[card_id] = " + ".join(names)
    return acts


def later_clause(stats):
    counts = ((stats or {}).get("later") or {}).get("counts") or {}
    parts = []
    for key, verb, noun, tail in (("tag", "tag", "note", ""),
                                  ("flag", "flag", "card", " purple"),
                                  ("suspend", "suspend", "card", "")):
        count = counts.get(key) or 0
        if count:
            parts.append(f"{verb} {count} {noun}{'' if count == 1 else 's'}{tail}")
    if not parts:
        return returning_clause(stats)
    text = " Not on your list: " + ", ".join(parts[:-1] + [("and " if len(parts) > 1 else "") + parts[-1]]) + "."
    kept = counts.get("flag_kept") or 0
    if kept:
        text += f" {kept} you flagged another colour keep{'s' if kept == 1 else ''} it."
    return text + returning_clause(stats)


def touchup_clause(stats):
    counts = ((stats or {}).get("touchups") or {}).get("counts") or {}
    parts = []
    tagged = counts.get("tag") or 0
    if tagged:
        parts.append(f"tag {tagged} note{'' if tagged == 1 else 's'}")
    marked = counts.get("markers") or 0
    if marked:
        parts.append(f"add marker tags to {marked} note{'' if marked == 1 else 's'}")
    frequency = counts.get("frequency") or 0
    if frequency:
        parts.append(f"add the frequency number to {frequency} "
                     f"note{'' if frequency == 1 else 's'}")
    freqsort = counts.get("freqsort") or 0
    if freqsort:
        parts.append(f"OVERWRITE the sort number on {freqsort} "
                     f"note{'' if freqsort == 1 else 's'}")
    if not parts:
        return ""
    return ", and " + ", ".join(parts[:-1] + [("and " if len(parts) > 1 else "") + parts[-1]])


# --- the backlog's picture (backlog onboarding, Sonic 2026-10-29: "only for the first reorder") ------------------- #
PICTURE_HINT = "backlog_picture"        # settings.json's `hints_seen` gets "backlog_picture:<lang>" after the first
Picture = namedtuple("Picture", "title lines known_line known try_count try_moves try_line")


def _n(count, one, many):
    return f"{count:,} {one if count == 1 else many}"


def backlog_picture(stats, settings=None):
    """The preview's own numbers grouped for someone who has never reordered (`stats`: the planner's, the clicks
    applied) -> Picture: the title, one line per group that has cards (where each goes, in the window's words), the
    known cards' line and ids apart (*Show them in Anki* sits beside it), and what *Try it* would write, worked out
    here by the run's own `plan.try_front` so the press says it before the write (I5): `try_count` cards, `try_moves`
    cards written in all (0: nothing to do, Try is off), `try_line` its words — or None with no new card."""
    stats = stats or {}
    considered = stats.get("considered") or 0
    if not considered:
        return None
    tiers = stats.get("tiers") or {}
    unlisted_as = stats.get("unlisted") or (settings or {}).get("junban_unlisted") or "list_first"
    by_leverage = (settings or {}).get("junban_order") == "priority"
    yours = tiers.get("yours", 0)
    placed = tiers.get("list", 0) + tiers.get("phrase", 0)
    library = tiers.get("library", 0)
    known = tiers.get("known", 0)
    aside = max(0, (stats.get("deselected") or 0) - (stats.get("taken_off") or 0))     # clicked off: no tier
    rest = max(0, considered - yours - placed - library - known - aside)
    lines = []
    if yours:
        lines.append(f"{_n(yours, 'is a card', 'are cards')} you made yourself: they go first")
    if placed:
        lines.append(f"{_n(placed, 'is a word', 'are words')} from your shows on your list: "
                     + ("placed first, by leverage" if by_leverage else "placed where you'll meet them"))
    if library:
        lines.append(f"{_n(library, 'is', 'are')} too rare for your list: mixed in where your shows meet "
                     f"{'it' if library == 1 else 'them'}")
    if rest:
        one = rest == 1
        verb, its = ("isn't", "its") if one else ("aren't", "their")
        where = {"journey": f"{verb} in your shows: after the ones that are, by {its} own sentence",
                 "back": f"{verb} on your list: at the back, in {its} order"}.get(
            unlisted_as, f"{verb} on your list: after it, by {its} own sentence")
        lines.append(f"{rest:,} {where}")
    if aside:
        lines.append(f"{_n(aside, 'is a card', 'are cards')} you clicked off: left where "
                     f"{'it is' if aside == 1 else 'they are'}")
    known_line = (f"{_n(known, 'is a word', 'are words')} you already know: "
                  f"{'it goes' if known == 1 else 'they go'} last" if known else "")
    known_ids = tuple(row.card_id for row in stats.get("order") or [] if row.tier == "known")
    from modules.junban.plan import TRY_CARDS, try_front
    count = min(TRY_CARDS, considered)
    s, them = ("", "it") if count == 1 else ("s", "them")
    try:
        writes, front = try_front([(row.card_id, row.due) for row in stats.get("order") or []], count)
    except ValueError:
        writes, front, try_line = [], [], "Your next cards can't be put first without moving many others."
    else:
        others = len([card_id for card_id, _due in writes if card_id not in set(front)])
        if not writes:
            try_line = f"Your next {count} card{s} {'is' if count == 1 else 'are'} already first."
        elif others:
            try_line = (f"Moves the next {count} card{s} you'll meet to the front — the {_n(others, 'card', 'cards')} "
                        f"there now {'takes its place' if others == 1 else 'take their places'} — then shows {them} in Anki.")
        else:
            try_line = f"Moves only the next {count} card{s} you'll meet to the front, then shows {them} in Anki."
    return Picture(f"Your backlog: {_n(considered, 'new card', 'new cards')}", tuple(lines), known_line, known_ids,
                   count, len(writes), try_line)


def picture_due(stats, hints_seen, language):
    """Is the backlog's picture shown? Only before this language's first reorder: never once `hints_seen` holds its
    id, nor where a reorder of the window's own is on disk (`stats["reordered_before"]`, read on the preview's
    worker). A hand-edited `hints_seen` that isn't a list reads as none seen."""
    if not stats or stats.get("reordered_before") is not False:
        return False
    seen = [h for h in hints_seen if isinstance(h, str)] if isinstance(hints_seen, (list, tuple)) else []
    return f"{PICTURE_HINT}:{language}" not in seen


# --- the preview ----------------------------------------------------------------------------------------------------- #
CheckView = namedtuple("CheckView", "rows words pending earlier link")
View = namedtuple("View", "rows card_ids counts match fields lines field_names display_order checks empty to_write "
                  "picture", defaults=(0, None))    # to_write: how many cards Reorder moves (its button names it);
                                                    # picture: the backlog's (`backlog_picture`)


def with_deselection(stats, deselected, retold, settings, language):
    """The dry run with the clicked-off rows and the changed ticks re-planned by `plan` itself (the Tk
    `_with_deselection`, as it is): the same functions the run calls, never a second ordering (contract 5)."""
    if not stats:
        return stats
    rows = stats.get("order") or []
    dropped = {row.card_id for row in rows} & set(deselected)
    if not dropped and not retold:
        return stats
    from modules.junban.plan import replan, with_answers
    _writes, replanned = replan(with_answers(rows, retold) if retold else rows, dropped,
                                number=stats.get("number"))
    merged = dict(stats)
    for key in ("order", "matched", "library", "tiers", "unmatched", "deselected", "taken_off",
                "taken_off_ids", "to_write", "unchanged", "base"):
        merged[key] = replanned.get(key)
    if "numbering" in replanned:
        merged["numbering"] = replanned["numbering"]
    touchups = (stats.get("touchups_all") if retold else None) or stats.get("touchups")
    if touchups:
        still = {row.note_id for row in (replanned.get("order") or [])
                 if row.rank is not None and row.changed and row.note_id is not None}
        merged["touchups"] = touchup.restrict(touchups, still, touchup.options(settings))
    later_opts = unlisted.options(settings)
    if unlisted.is_active(later_opts):
        taken = set(replanned.get("taken_off_ids") or ())
        merged["later"] = unlisted.plan(
            replanned.get("order") or [], stats.get("marks") or {}, language,
            stats.get("flags_of") or {}, stats.get("note_tags") or {}, later_opts,
            parent=touchup.options(settings).get("tag"), exclude=set(dropped) - taken, taken_off=taken)
    return merged


def in_display_order(order, display_order, retold):
    """The rows in the order already on screen (the Tk `_in_display_order`): a clicked-off row stays where it was
    drawn; a ticked card moves just after the card the plan now puts before it. -> (rows, display order)."""
    rows = list(order)
    if not display_order:
        return rows, [row.card_id for row in rows]
    display = list(display_order)
    if retold:
        moving = {row.card_id for row in rows if row.word in retold}
        display = [card_id for card_id in display_order if card_id not in moving]
        for i, row in enumerate(rows):
            if row.card_id in moving:
                before = rows[i - 1].card_id if i else None
                display.insert(display.index(before) + 1 if before in display else 0, row.card_id)
    rank = {card_id: i for i, card_id in enumerate(display)}
    unseen = len(rank)
    return sorted(rows, key=lambda row: rank.get(row.card_id, unseen)), list(display_order)


def checks_view(stats, ticked, show_earlier):
    """"Same word as one on your list?" (the Tk `_render_checks`' data): its rows, or the link line when only earlier
    answers are left. Row: (tick, card word, "→ list word   #rank", reading, excerpt, tone)."""
    entries = (stats or {}).get("suggestions") or []
    pending = [entry for entry in entries if entry.get("answer") is None]
    earlier = [entry for entry in entries if entry.get("answer") is not None]
    shown = pending + (earlier if show_earlier else [])
    rows, words = [], []
    for entry in shown:
        on = bool((ticked or {}).get(entry["word"]))
        tone = "ticked" if on else ("earlier" if entry.get("answer") is not None else "")
        rows.append((CHECK_ON if on else CHECK_OFF, entry["word"], f"→ {entry['key']}   #{entry['rank'] + 1:,}",
                     entry.get("reading") or "", entry.get("excerpt") or "", tone))
        words.append(entry["word"])
    link = None
    if not shown and earlier:
        link = f"{len(earlier)} word{'' if len(earlier) == 1 else 's'} you answered before about spellings — "
    return CheckView(tuple(rows), tuple(words), len(pending), len(earlier), link)


def preview_view(stats, checks, deselected=frozenset(), ticked=None, display_order=(), show_earlier=False,
                 settings=None, language="ja"):
    """One dry run as the window shows it (the Tk `_show_preview`, its rendering alone): the rows, the counts line,
    the match line, the fields line and every message line, the sentence last — Reorder's one confirmation (I5).
    Every number comes from the planner's own pass. -> View. A worker's call (it re-plans)."""
    checks = checks or {}
    settings = settings or {}
    raw = stats
    whys = {row.card_id: row.why for row in (stats or {}).get("order") or []}
    retold = changed_ticks(raw, ticked)
    stats = with_deselection(stats, deselected, retold, settings, language)
    lines = [(line, "warning") for line in checks.get("warnings") or []]
    lines += [(line, "problem") for line in checks.get("problems") or []]
    check_view = checks_view(raw, ticked, show_earlier)
    if stats is None:
        return View((), (), "Nothing was read from Anki.", "No preview — see below.", "", lines, [], [], check_view,
                    True)

    considered = stats.get("considered", 0)
    parts = [f"{considered} new card{'' if considered == 1 else 's'} to reorder"]
    review = stats.get("context_review")
    if review is not None:
        parts.append(f"{review} in review or learning (untouched)")
    suspended = stats.get("context_suspended")
    if suspended:
        parts.append(f"{suspended} suspended (untouched)")
    counts = " · ".join(parts)
    only = [name for name in stats.get("only_markers") or [] if name in MARKER_GLYPHS]
    filtered = (" · only " + " ".join(MARKER_GLYPHS[name] for name in only)) if only else ""
    tiers = stats.get("tiers") or {}
    library = stats.get("library") or 0
    phrases = tiers.get("phrase", 0)
    placed = f" · {library} more from your library" if library else ""
    if phrases:
        placed += f" · {phrases} frequent phrase{'' if phrases == 1 else 's'} with them"
    match_line = (f"{stats.get('matched', 0)} of {considered} new card{'' if considered == 1 else 's'} matched "
                  f"your current list{placed}{filtered}")
    if stats.get("library_missing") and stats.get("unlisted") == "journey":
        lines.append(("The words your list cut off wait at the back for now: press Generate in Surasura once, and "
                      "the next preview places them where your journey meets them.", "warning"))
    elif stats.get("library_missing"):
        lines.append(("Phrases wait with the rarer cards for now: press Generate in Surasura once, and the next "
                      "preview puts the ones you meet often with your list's words.", "warning"))
    rest = [(tiers.get("i+1", 0), "i+1"), (tiers.get("multi", 0), "with more new words"),
            (tiers.get("rest", 0), "by frequency")]
    rest = " · ".join(f"{count} {label}" for count, label in rest if count)
    if rest:
        lines.append((f"Then, by their own sentence: {rest}.", ""))
    ready = stats.get("ready_first") or {}
    moved = [f"{ready['pulled']} brought right before the card that needs {'it' if ready['pulled'] == 1 else 'them'}"
             if ready.get("pulled") else "",
             f"{ready['held']} wait{'s' if ready['held'] == 1 else ''} for a word "
             f"{'its' if ready['held'] == 1 else 'their'} sentence needs" if ready.get("held") else ""]
    moved = " · ".join(part for part in moved if part)
    if moved:
        lines.append((f"i+1 first: {moved}.", ""))
    known = tiers.get("known", 0)
    if known:
        lines.append((f"{known} card{' is a word' if known == 1 else 's are words'} you already know — they go last. "
                      "Suspend them in Anki if you don't need them.", ""))
    for entry in stats.get("banner") or []:
        lines.append((f"{entry['cards']} cards come from {entry['source']}, which isn't in your library. Add its "
                      "subtitles and Generate to rank them.", "warning"))
    fields = stats.get("fields") or {}
    resolved = ", ".join(f'{model} → "{field}"' for model, field in sorted(fields.items()))
    fields_line = f"note types: {resolved}" if resolved else ""

    ordered, display = in_display_order(stats.get("order") or [], display_order, retold)
    marks_of = stats.get("marks") or {}
    acts = later_acts(stats)
    taken_off = set(stats.get("taken_off_ids") or ())
    suggested_marks = stats.get("suggested_marks") or {}
    rows, card_ids = [], []
    index = 0
    for row in ordered[:MAX_PREVIEW_ROWS]:
        off = row.card_id in deselected
        if off:
            tone = "unmatched"
        else:
            index += 1
            with_list = row.tier in unlisted.PLACED_WITH_LIST
            tone = "unmatched" if not with_list else ("unchanged" if not row.changed else "")
        why = (row.why if row.word in retold else whys.get(row.card_id)) or row.why or "—"
        if row.suggestion and row.tier != "list" and not off:
            why = f"{why} · {row.suggestion[0]}?"
        if off and row.card_id in taken_off:
            why = f"{why}  → off your list" + (f", {acts[row.card_id]}" if acts.get(row.card_id) else "")
        elif off:
            why = f"{why}  · left alone"
        elif acts.get(row.card_id):
            why = f"{why}  → {acts[row.card_id]}"
        marks = marker_glyphs(marks_of.get(row.word) or (suggested_marks.get(row.word) if row.tier == "list"
                                                          else None))
        rows.append((DESELECTED_GLYPH if off else str(index), "" if off else str(row.position), row.word or "",
                     marks, why, row.deck or "", tone))
        card_ids.append(row.card_id)
    if len(ordered) > MAX_PREVIEW_ROWS:
        lines.append((f"Showing the first {MAX_PREVIEW_ROWS} of {len(ordered)} cards.", "warning"))

    to_write = stats.get("to_write", 0)
    if to_write:
        lines.append((f"Reorder will move {to_write} of {considered} card{'' if considered == 1 else 's'} in "
                      f"{', '.join(stats.get('decks') or []) or 'the chosen scope'}"
                      f"{touchup_clause(stats)}.{unmatched_clause(stats)}"
                      f"{deselected_clause(stats)}{later_clause(stats)}", "good"))
    elif considered and later_clause(stats):
        lines.append(("Every card is already in the right place."
                      f"{later_clause(stats)}{deselected_clause(stats)}", "good"))
    elif considered:
        lines.append(("Every card is already in the right place — Reorder would change nothing."
                      f"{deselected_clause(stats)}", "good"))
    elif stats.get("empty_list"):                 # M-W2-1: every file watched or Finished — said, not "no cards"
        lines.append((reposition.EMPTY_LIST, "good"))
    else:
        lines.append(("There are no new cards in this scope.", "warning"))
    return View(tuple(rows), tuple(card_ids), counts, match_line, fields_line, lines,
                list(stats.get("field_names") or []), display, check_view, False, to_write,
                backlog_picture(stats, settings))


def tail_lines(session, can_generate):
    """The lines said last, from the session's state: the list out of date (§16.9) — one line, and the "didn't help"
    one after a Generate that tried."""
    lines = []
    if session.list_current is False and session.must_generate(can_generate):
        if session.generate_tried:
            lines.append(("Generate didn't bring the list up to date — see Surasura's log.", "problem"))
        lines.append(("Your list is out of date — press Generate & preview to bring it up to date first.", "warning"))
    return lines


def report_lines(report):
    """A finished run or restore (the Tk `_show_report`): problems verbatim (a refusal names both scopes), the
    message, the failed cards and notes apart (note ids are not card ids), the snapshot's place. -> [(text, tone)]."""
    report = report or {}
    lines = [(line, "warning") for line in report.get("warnings") or []]
    lines += [(line, "problem") for line in report.get("problems") or []]
    lines.append((report.get("message") or "", "good" if report.get("ok") else "problem"))
    failures = report.get("failures") or []
    if failures:
        lines.append((f"{len(failures)} card(s) could not be changed; the first was {failures[0][0]}.", "problem"))
    note_failures = report.get("note_failures") or []
    if note_failures:
        lines.append((f"{len(note_failures)} note(s) could not be updated; the first was {note_failures[0][0]}.",
                      "problem"))
    if report.get("browsed") == "sorted":
        lines.append(("Anki's browser shows your deck's new cards in order: the moved ones are on top.", ""))
    elif report.get("browsed") == "plain":
        lines.append(("Anki's browser shows the cards that moved.", ""))
    elif report.get("browse_problem"):
        lines.append((f"Anki's browser couldn't be opened ({report['browse_problem']}).", "warning"))
    if report.get("snapshot"):
        lines.append((f"Previous order saved to {report['snapshot']}", ""))
    return [(text, tone) for text, tone in lines if text]


# --- the window's lifetime lock ------------------------------------------------------------------------------------ #
class WindowLock:
    """`junban-window`, held for as long as the window is open (P0.3 04 §2): the automatic reorder (`auto.blocked`)
    and `surasura-cli junban --auto` stand aside instead of moving the queue the preview describes. `hold` on a worker
    (it waits up to 2 s, past another program's look); `release` from anywhere, once — a hold that lands after it lets
    go at once (the window closed meanwhile; the Tk window's D5: it could outlive its window)."""

    def __init__(self, name="junban-window", verb="the 順 window", wait=2.0):
        self.name, self.verb, self.wait = name, verb, wait
        self._guard = threading.Lock()
        self._held = None
        self._closing = False
        self._owner = object()        # the hold outlives the worker that takes it (locks.take's `owner`)

    def hold(self):
        try:
            from app import locks
            held = locks.take(self.name, self.verb, wait=self.wait, owner=self._owner)
        except Exception:
            return False
        with self._guard:
            if not self._closing:
                self._held, held = held, None
        if held is not None:
            held.release()
            return False
        return True

    def start(self, on_failed=None):
        """Hold it on a thread of its own (a 2 s wait never takes a pool worker). `on_failed()` (that thread) when it
        could not be taken while the window is still open (AD6-13: said, never silent)."""
        def hold():
            if not self.hold() and on_failed is not None:
                with self._guard:
                    closing = self._closing
                if not closing:
                    on_failed()
        thread = threading.Thread(target=hold, name="junban-window-lock", daemon=True)
        thread.start()
        return thread

    def holding(self):
        with self._guard:
            return self._held is not None

    def release(self):
        with self._guard:
            self._closing = True
            held, self._held = self._held, None
        if held is not None:
            threading.Thread(target=held.release, name="junban-window-release", daemon=True).start()
