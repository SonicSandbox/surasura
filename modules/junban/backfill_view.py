# SPDX-License-Identifier: GPL-3.0-or-later
"""Anki Backfill's view model on the 3.0 line (W3.4 row 5): what the Qt window (`qt_backfill.py`) shows and allows,
decided here, Qt-free, so it is tested headless and the window only paints the answers.

The rules are the Tk window's (`backfill_gui.py`, left as it is for 2.x), moved out of its class (inv §5), each named by
the Tk method it replaces:

* **The preview is the confirmation** — `Choices.key` (`_key`), `fill_ready` (`_sync_buttons`' Fill rule): Fill only
  while idle, with a preview of the choices and language on screen that has something to write.
* **Nothing slow on the window's thread** (inv defect 1): `read_readiness` (`data_ready`, `general_ready`,
  `rebuild_tip` — SQLite and the token store) runs on a worker and the window keeps its answer; `needs_build`,
  `show_get_data` and `show_rebuild` read that answer, never the disk.
* **The session per language** (`_session_for`) — `SessionKeeper`, on workers only (Windows won't replace an open
  database: it is closed before an install, a build's end and a promote).
* **The window-lifetime lock** (`_hold_window_lock` / `_close`) — `WindowLock`: `backfill-window`, so `surasura-cli
  backfill` stands aside while the window is open.
* **Every Fill and Restore is a `backfill` job** (`submit_write`): one Anki writer in this process beside 順's reorder,
  Connect's mining and the re-plan (`jobs.RESOURCES`), and `anki_connect.take_writer` across processes, as before.
* **The restore order** (`on_restore`) — `restore_plan`: Connect's unfinished fill first; else the snapshot, its time
  read before the question so a restore that waited never puts back another.
* **One reader of a build's lines** (`_build_worker`'s own regex dropped) — `build_library` reads through
  `backfill.read_build`, the background build's reader.
* **The background build** (`_watch_build`) — `BuildWatch`: its quiet line, and the new set put in only at an idle
  moment, the session closed first.
"""
import html
import re
import threading

from app import locks
from modules.junban import backfill, undo
from modules.junban import qt_strings as S

MAX_PREVIEW_ROWS = 4000
# A note type's language in the Fields window (Patterns_Chinese_Spec.md D7): set, or not — "Language?".
LANGUAGE_LABELS = {"ja": S.BF_LANGUAGE_JA, "zh": S.BF_LANGUAGE_ZH}
LANGUAGE_NAMES = LANGUAGE_LABELS

# Pasted into a note type's Styling, it styles the パターン lines on any card (Anki_Card_Layout_Spec.md §5). Plain CSS.
CARD_STYLE = """/* Surasura パターン */
.pat-particle, .pat-form, .pat-frame, .pat-colloc { font-size: .85em; line-height: 1.7; }
.pat-particle, .pat-form, .pat-frame { opacity: .8; }
.pat-register { display: inline-block; margin-top: .4em; padding: .1em .6em; font-size: .75em;
                border: 1px solid currentColor; border-radius: 6px; opacity: .6; }
"""


# --- the choices ---------------------------------------------------------------------------------------------------- #
class Choices:
    """The six settings the window owns, as its controls read now. Never changed in place: an edit is a new one
    (`but`), and every container it hands out is fresh (settings_manager merges module defaults shallowly: §13 #12)."""
    KEYS = ("junban_backfill_deck", "junban_backfill_cards", "junban_backfill_replace", "junban_backfill_fills",
            "junban_backfill_fields", "junban_backfill_note_languages")

    def __init__(self, deck="", cards="all", replace=False, fills=(), fields=None, note_languages=None):
        self.deck = str(deck or "").strip()
        self.cards = cards if cards in backfill.CARDS else "all"
        self.replace = replace is True
        self.fills = tuple(key for key in backfill.FILL_KEYS if key in fills)
        self.fields = {str(fill): dict(models) for fill, models in (fields or {}).items()}
        self.note_languages = dict(note_languages or {})

    @classmethod
    def from_settings(cls, settings):
        """The window's choices as saved (`backfill._deck` … `_note_languages`, the engine's own readers)."""
        return cls(backfill._deck(settings), backfill._cards(settings), backfill._replace(settings),
                   backfill._fills(settings), backfill._field_map(settings), backfill._note_languages(settings))

    def but(self, **changes):
        values = dict(deck=self.deck, cards=self.cards, replace=self.replace, fills=self.fills, fields=self.fields,
                      note_languages=self.note_languages)
        values.update(changes)
        return Choices(**values)

    def settings(self):
        """`_choices`: the six keys, fresh containers every time."""
        return {"junban_backfill_deck": self.deck,
                "junban_backfill_cards": self.cards,
                "junban_backfill_replace": self.replace,
                "junban_backfill_fills": list(self.fills),
                "junban_backfill_fields": {fill: dict(models) for fill, models in self.fields.items()},
                "junban_backfill_note_languages": dict(self.note_languages)}

    def changed(self, other):
        """The keys whose value differs from `other`'s: the only ones a save writes (the window's own, changed)."""
        mine, theirs = self.settings(), other.settings()
        return {key: mine[key] for key in self.KEYS if mine[key] != theirs[key]}

    def key(self, language):
        """`_key`: what a preview was made for — the language, the field map, the note languages and the choices. A
        preview whose key is not the one on screen describes other cards."""
        fields = tuple(sorted((fill, tuple(sorted(models.items()))) for fill, models in self.fields.items()))
        languages = tuple(sorted(self.note_languages.items()))
        return (language, fields, languages, (self.deck, self.cards, self.replace, self.fills))


def engine_settings(saved, language, choices):
    """`_settings`: what the engine is handed — the saved settings, the window's language and its choices."""
    return dict(saved or {}, target_language=language, **choices.settings())


# --- what is offered, and the buttons ------------------------------------------------------------------------------ #
def offered(fill, language):
    """`_sync_availability`: whether `language` is offered `fill` (read afresh for the language on screen)."""
    return language in fill.languages


def fill_tip(fill, language):
    return fill.tip if offered(fill, language) else S.BF_NOT_OFFERED_TIP


def needs_build(choices, language, data_ready):
    """`_needs_build`: nothing to fill from yet (a library never built) — Preview builds it first. `data_ready` is the
    worker's answer (`read_readiness`), never read here."""
    return any(language in f.languages for f in backfill.FILLS if f.key in choices.fills) and not data_ready


def fill_ready(busy, preview_key, key, preview):
    """`_sync_buttons`' Fill rule — the safety gate: idle, a preview of exactly the choices and language on screen, and
    something in it to write."""
    return (not busy) and preview_key is not None and preview_key == key and bool((preview or {}).get("edits"))


def preview_button(build):
    """Preview, or "Build & preview" while there is nothing to fill from yet: (text, tip)."""
    return (S.BF_BUILD_PREVIEW, S.BF_BUILD_PREVIEW_TIP) if build else (S.BF_PREVIEW, S.BF_PREVIEW_TIP)


def show_get_data(language, general_ready):
    """`_show_get_data`: "Get data…" only while this computer has no general パターン database for the language."""
    return offered(backfill.FILLS[0], language) and general_ready is False


def show_rebuild(language, data_ready):
    """`_show_rebuild`: "Rebuild from my library" while the language has a library set to rebuild."""
    return offered(backfill.FILLS[0], language) and data_ready is True


def short(name, width=22):
    return name if len(name) <= width else name[:width - 1] + "…"


def target_text(fill, models):
    """`_target_text`: where a fill goes, on its button — "Lapis → Patterns", "2 note types", "Choose a field…"."""
    if not models:
        return S.BF_TARGET_NONE
    mapped = [(name, (info.get("mapped") or {}).get(fill.key)) for name, info in models.items()]
    mapped = [(name, field) for name, field in mapped if field]
    if not mapped:
        return S.BF_TARGET_CHOOSE
    if len(mapped) > 1:
        return S.BF_TARGET_MANY.format(n=len(mapped))
    return S.BF_TARGET_ONE.format(model=short(mapped[0][0]), field=mapped[0][1])


def details(preview):
    """`_details`: behind the summary's ⓘ — how many were replaced and why the rest wait, per fill when more than one is
    ticked. -> (title, [(header, line, example)]); no sections when there is nothing to say."""
    by_fill = (preview or {}).get("by_fill") or {}
    lines = []
    for fill in backfill.FILLS:
        counts = by_fill.get(fill.key)
        if counts is None:
            continue
        reasons = backfill.skipped(counts)
        if len(by_fill) > 1:
            done = counts.get("fill", 0) + counts.get("replace", 0)
            skipped = S.BF_DETAILS_SKIPPED.format(n=f"{sum(n for _l, n in reasons):,}") if reasons else ""
            lines.append((fill.label, S.BF_DETAILS_FILL.format(n=f"{done:,}") + skipped, ""))
        if counts.get("replace"):
            lines.append((S.BF_DETAILS_REPLACED.format(n=f"{counts['replace']:,}"), backfill.REASON_HELP["replace"],
                          ""))
        for label, n in reasons:
            name = S.BF_DETAILS_PHRASE if label == "phrases" and n == 1 else label
            lines.append((f"{n:,} {name}", backfill.REASON_HELP.get(label, ""), ""))
    return "", lines if any(header[0].isdigit() for header, _line, _ex in lines) else []


def help_html(content):
    """A "?" or "ⓘ" popup's (title, sections) as the bubble's rich text — every piece escaped."""
    title, sections = content
    parts = [f"<b>{html.escape(title)}</b>"] if title else []
    for header, line, example in sections:
        piece = f"<b>{html.escape(header)}</b><br>{html.escape(line)}"
        if example:
            piece += f"<br><i>{html.escape(example)}</i>"
        parts.append(piece)
    return "<br><br>".join(parts)


def lines_of(value):
    """A field's lines as one row of text: `〜に 34% · 〜を 24% / 探検する 19%`."""
    parts = re.split(r"(?i)</div>|<br\s*/?>", value or "")
    return " / ".join(t for t in (html.unescape(re.sub(r"<[^>]+>", "", p)).strip() for p in parts) if t)


def preview_rows(result, cap=MAX_PREVIEW_ROWS):
    """`_show_preview`'s rows: the ones that write first, each `(word, fill label, result, what goes in, writes)`, at
    most `cap` — and how many more there are (inv defect 2: the table is the confirmation, so it says so). -> (rows,
    more)."""
    rows = sorted(result.get("rows") or [], key=lambda r: (r[3] not in ("fill", "replace"), r[3], r[1]))
    labels = {fill.key: fill.label for fill in backfill.FILLS}
    shown = []
    for _note_id, word, _field, action, value, fill_key in rows[:cap]:
        writing = action in ("fill", "replace")
        shown.append((word, labels.get(fill_key, fill_key), backfill.reason(action),
                      lines_of(value) if writing else "", writing))
    return shown, max(0, len(rows) - cap)


def summary_line(result, choices, models):
    """The one line over the table: the counts, or what the empty state needs."""
    if result.get("rows"):
        return backfill.summary(result)
    if not choices.fills:
        return S.BF_SUMMARY_TICK
    if models:
        return S.BF_SUMMARY_CHOOSE_FIELD
    return S.BF_SUMMARY_NO_CARDS


def models_of(result):
    """The deck's note types a preview found ({name: {fields, count, mapped, language}}), copied."""
    return {name: dict(info) for name, info in ((result.get("scope") or {}).get("models") or {}).items()}


class Shown:
    """A preview as the window paints it, made on the preview's worker (AD5-1: sorting every row and cleaning up to
    4,000 fields' HTML would hold the window's thread on a big deck): the note types, the table's rows and how many
    more, the summary line, and the ⓘ's rich text ("" when it has nothing to say)."""
    __slots__ = ("models", "rows", "more", "summary", "details")

    def __init__(self, models, rows, more, summary, details_tip):
        self.models, self.rows, self.more, self.summary, self.details = models, rows, more, summary, details_tip


def shown(result, choices):
    """(The preview's worker.) -> `Shown` for `result`, made with the `choices` it was asked for."""
    models = models_of(result)
    rows, more = preview_rows(result)
    content = details(result)
    return Shown(models, rows, more, summary_line(result, choices, models), help_html(content) if content[1] else "")


# --- the Fields window's edits -------------------------------------------------------------------------------------- #
def fields_rows(fill, models):
    """The Fields window's rows, mapped first, then the most notes, then by name: `(name, count, field labels, the field
    chosen, the language label)`."""
    order = sorted(models.items(), key=lambda m: (not (m[1].get("mapped") or {}).get(fill.key), -m[1]["count"], m[0]))
    return [(name, info["count"], [S.BF_FIELDS_SKIP] + list(info["fields"]),
             (info.get("mapped") or {}).get(fill.key) or S.BF_FIELDS_SKIP,
             LANGUAGE_LABELS.get(info.get("language"), S.BF_LANGUAGE_UNSET)) for name, info in order]


def with_mapping(choices, models, fill_key, model, label):
    """`_on_mapping`: one note type's field for one fill — "— skip —" is `backfill.SKIP`. -> (choices, models), new."""
    choice = backfill.SKIP if label == S.BF_FIELDS_SKIP else label
    fields = {fill: dict(m) for fill, m in choices.fields.items()}
    fields.setdefault(fill_key, {})[model] = choice
    models = {name: dict(info) for name, info in models.items()}
    if model in models:
        models[model]["mapped"] = dict(models[model].get("mapped") or {}, **{fill_key: choice or None})
    return choices.but(fields=fields), models


def with_note_language(choices, models, model, label):
    """`_on_note_language`: one note type's language — "Language?" removes it (the kana rule decides again). ->
    (choices, models), new."""
    code = next((code for code, name in LANGUAGE_LABELS.items() if name == label), None)
    languages = dict(choices.note_languages)
    if code:
        languages[model] = code
    else:
        languages.pop(model, None)
    models = {name: dict(info) for name, info in models.items()}
    if model in models:
        models[model]["language"] = code
    return choices.but(note_languages=languages), models


# --- lines from a job ----------------------------------------------------------------------------------------------- #
WAITS_FOR = "waits for "                 # the registry's reason for a job held back by another (jobs._schedule)


def job_line(state, reason, label):
    """The write's own line from its job's state (IK-75): waiting its turn — behind what — or writing; else None."""
    from app.services import jobs
    if state == jobs.WAITING:
        reason = reason or ""
        if reason.startswith(WAITS_FOR):
            return S.BF_JOB_WAITING_FOR.format(what=reason[len(WAITS_FOR):])
        return S.BF_JOB_WAITING.format(reason=reason) if reason else S.BF_JOB_WAITING_TURN
    if state == jobs.RUNNING:
        return S.BF_JOB_RUNNING.format(label=label)
    return None


def auto_preview_due(connected, already, env):
    """"It just works" (`_on_connection`): the first connection arms one automatic preview (the choices are made and a
    preview only reads) — once per window, and never under test (`SURASURA_NO_UI_TIMERS`, `SURASURA_NO_ANKI_SYNC`:
    it reads Anki)."""
    return bool(connected and not already and not env.get("SURASURA_NO_UI_TIMERS")
                and not env.get("SURASURA_NO_ANKI_SYNC"))


def status_numbers(line):
    """`_status`: the "n / m" of a slow step's line ("Reading your library: 900 / 1,987 files…"), or None."""
    found = re.search(r"([\d,]+) / ([\d,]+)", line or "")
    if not found:
        return None
    return int(found.group(1).replace(",", "")), int(found.group(2).replace(",", ""))


def download_line(done, total):
    """`_download_progress`: bytes in, as whole MB. -> (the line, the MB it shows) — the window says it once per MB."""
    mb = int(done / 1e6)
    return (S.BF_SUMMARY_DOWNLOADING_MB.format(mb=mb, total=max(1, round(total / 1e6))) if total
            else S.BF_SUMMARY_DOWNLOADING), mb


def build_line(state):
    """The quiet line while a background build runs (`backfill.background()`), else ""."""
    if not state:
        return ""
    _language, done, total = state
    return S.BF_BUILD_LINE_FILES.format(done=f"{done:,}", total=f"{total:,}") if total else S.BF_BUILD_LINE


# --- read on a worker, kept by the window --------------------------------------------------------------------------- #
class Readiness:
    """What the window would otherwise read on its own thread (inv defect 1): the language's library set built
    (`data`), a general database here (`general`), and "Rebuild from my library"'s tooltip (`tip`)."""
    __slots__ = ("language", "data", "general", "tip")

    def __init__(self, language, data, general, tip):
        self.language, self.data, self.general, self.tip = language, data, general, tip


def read_readiness(language):
    """(A worker.) -> `Readiness` for `language`. Never raises: a read that fails counts as not ready."""
    def safe(fn, default):
        try:
            return fn(language)
        except Exception as e:
            print(f"Backfill: {fn.__name__} failed ({e}).")
            return default
    data = bool(safe(backfill.data_ready, False))
    general = bool(safe(backfill.general_ready, False))
    tip = safe(backfill.rebuild_tip, S.BF_REBUILD_TIP) if data else S.BF_REBUILD_TIP
    return Readiness(language, data, general, tip)


class RestorePlan:
    """What Restore would put back, read before the question (`on_restore`): `kind` is "run" (one of Connect's fills
    that never finished: `run`), "snapshot" (the window's fills: `confirmed`, the snapshot's time when asked) or
    "nothing". `line` is the question's second line."""
    __slots__ = ("language", "kind", "run", "confirmed", "line")

    def __init__(self, language, kind, run=None, confirmed=None, line=""):
        self.language, self.kind, self.run, self.confirmed, self.line = language, kind, run, confirmed, line

    def title(self):
        return S.BF_ASK_RUN if self.kind == "run" else S.BF_ASK_RESTORE


def restore_plan(language):
    """(A worker: it reads the undo files.) Connect's unfinished fill comes first — it refuses every fill until it is
    put back, so Restore names it even when the window filled nothing; else the window's snapshot, its `written_at`
    read now, before the question (a restore that waits then refuses once a fill replaced it, E1.4 §W)."""
    run = undo.unfinished(language, "backfill")
    if run is not None:
        return RestorePlan(language, "run", run=run, line=undo.describe_run(language, run))
    confirmed = (undo.load(language, kind="backfill") or {}).get("written_at")
    line = backfill.describe(language)
    if not line:
        return RestorePlan(language, "nothing")
    return RestorePlan(language, "snapshot", confirmed=confirmed, line=line)


def restore_work(plan, settings, stop, on_wait):
    """The restore a plan's "yes" asked for: exactly that Connect run, or exactly the snapshot asked about."""
    if plan.kind == "run":
        return lambda: backfill.restore(settings, wait=None, cancel=stop, on_wait=on_wait, run=plan.run)
    return lambda: backfill.restore(settings, wait=None, cancel=stop, on_wait=on_wait, confirmed=plan.confirmed)


def fill_work(settings, keeper, planned, stop, on_wait, progress=None):
    """The fill a preview's "yes" asked for: only what was previewed (`planned`), each note re-read inside the lock."""
    return lambda: backfill.run(settings, keeper.get(settings), planned=planned, progress=progress, wait=None,
                                cancel=stop, on_wait=on_wait)


class SessionKeeper:
    """`_session_for`: the window's `backfill.Session` — made on first use and again when the language changes, closed
    before anything replaces its databases. Workers only (it opens and closes SQLite); one job uses it at a time."""

    def __init__(self, make=None):
        self._make = make                    # None: the engine's `backfill.Session`, looked up when made
        self._lock = threading.Lock()
        self.session = None
        self.language = None

    def get(self, settings):
        language = (settings or {}).get("target_language") or "ja"
        with self._lock:
            if self.session is None or self.language != language:
                old, self.session = self.session, None
                if old is not None:
                    old.close()
                self.session = (self._make or backfill.Session)(settings)
                self.language = language
            return self.session

    def close(self):
        with self._lock:
            old, self.session, self.language = self.session, None, None
        if old is not None:
            old.close()


class WindowLock:
    """`backfill-window`, held for as long as the window is open (`_hold_window_lock` / `_close`): `surasura-cli
    backfill` stands aside instead of filling the notes the window's preview describes. Taken and let go on workers;
    the hold outlives the worker that takes it (`locks.take`'s `owner`). A close before the take lands lets it go."""
    NAME = "backfill-window"

    def __init__(self):
        self._guard = threading.Lock()
        self._held = None
        self._closing = False
        self._owner = object()

    def hold(self):
        """(A worker.) -> True when it is held now."""
        try:
            held = locks.take(self.NAME, S.BF_LOCK_VERB, wait=2.0, owner=self._owner)
        except Exception:
            return False
        with self._guard:
            if not self._closing:
                self._held, held = held, None
        if held is not None:                    # closed meanwhile
            held.release()
            return False
        return True

    def release(self):
        """(A worker.) Let it go, now or as soon as the take lands."""
        with self._guard:
            self._closing = True
            held, self._held = self._held, None
        if held is not None:
            held.release()

    def held(self):
        with self._guard:
            return self._held is not None


def submit_write(registry, label, work, on_end, stop):
    """A Fill or a Restore as a `backfill` job (`jobs.RESOURCES`: `anki-writer` — never beside 順's reorder, Connect's
    mining or the re-plan in this process; across processes `anki_connect.take_writer`, inside `work`, still decides).
    Quitting waits for it (an Anki write finishes its batch). When the registry starts it, a thread of its own runs
    `work()` -> the engine's report, and `on_end(report)` is told once, on that thread. Cancelled before it started
    (the window closed while it waited for another writer here) -> `on_end(None)`: nothing was written. Cancelling a
    running one sets `stop`: a wait for another program's writer ends there, writing nothing; a write under way
    finishes. -> the Job."""
    state = {"started": False, "told": False}
    guard = threading.Lock()

    def tell(report):
        with guard:
            if state["told"]:
                return
            state["told"] = True
        on_end(report)

    def body(job):
        try:
            report = work()
        except Exception as e:                  # the engine never raises; a fault here is still a failed job
            report = backfill._report(False, S.BF_NOTHING_WRITTEN, problems=[str(e)])
        if not isinstance(report, dict):
            report = backfill._report(False, S.BF_NOTHING_WRITTEN)
        if report.get("ok"):
            job.finish(ok=True)
        elif report.get("busy") and stop.is_set():
            job.finish(ok=True, cancelled=True)
        else:
            problems = [p for p in report.get("problems") or [] if p]
            job.finish(ok=False, message=" ".join([report.get("message") or ""] + problems[:1]).strip())
        tell(report)

    def start(job):
        with guard:
            if state["told"]:                   # cancelled as the registry started it: "nothing written" stands
                gone = True
            else:
                gone, state["started"] = False, True
        if gone:
            job.finish(ok=True, cancelled=True)
            return
        threading.Thread(target=body, args=(job,), name="backfill-write", daemon=True).start()

    def cancel(_job):
        stop.set()
        with guard:
            started = state["started"]
        if not started:
            tell(None)

    return registry.submit("backfill", label, start, cancel=cancel, on_quit="wait")


def build_library(language, reinforce, on_progress):
    """(A worker.) "Build & preview": the library's パターン built for `language` in its own process
    (`backfill.start_rebuild`), its lines read by the background build's reader (`backfill.read_build`). -> (ok, last
    line), or None while another library build runs (never two). Raises OSError when it can't start."""
    process = backfill.start_rebuild(language, reinforce)
    if process is None:
        return None
    return backfill.read_build(process, on_progress)


def rebuild_now(language, reinforce):
    """(A worker: it starts a child.) "Rebuild from my library" -> "started" · "building" (one runs already) ·
    "deferred" (an update waits for Surasura's programs: it starts if the update is cancelled — inv defect 3, never
    "could not start") · "failed"."""
    if backfill.building():
        return "building"
    waiting = backfill._update_waiting()
    if backfill.rebuild_in_background(language, reinforce):
        return "started"
    return "deferred" if waiting else "failed"


class BuildWatch:
    """`_watch_build`: a background build of the library's パターン — this window's or the automatic step's. `step(state)`
    with `backfill.background()` -> (its quiet line, whether one just started, whether one just ended);
    `take_swap(busy)` -> the language whose new set goes in now (the window idle: the session is closed first, then
    `backfill.promote`), else None — never while a job reads the set in use."""

    def __init__(self):
        self.building = None
        self.swap = None

    def step(self, state):
        if state:
            started = self.building is None
            self.building = state[0]
            return build_line(state), started, False
        if self.building is not None:
            self.swap, self.building = self.building, None
            return "", False, True
        return "", False, False

    def take_swap(self, busy):
        if self.swap is None or busy:
            return None
        language, self.swap = self.swap, None
        return language

    def active(self):
        return self.building is not None or self.swap is not None


def promote_now(keeper, language):
    """(A worker.) The idle moment after a background build: the session lets the old set go, then the new one goes
    in (`backfill.promote`; Windows won't replace a database a reader holds). -> whether it went in."""
    keeper.close()
    return backfill.promote(language)
