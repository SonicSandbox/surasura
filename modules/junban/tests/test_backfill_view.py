# SPDX-License-Identifier: GPL-3.0-or-later
"""Anki Backfill's view model (`backfill_view.py`, W3.4 row 5): the Tk window's rules moved out of its class, headless.

What a wrong answer would cost, most costly first:

  * **Fill pressed without a preview of the choices on screen** (the preview is the only confirmation) — a fill of
    notes the user never saw. `fill_ready` and `Choices.key` (Tk: `_sync_buttons`, `_key`).
  * **Two Anki writers at once, or a write after the window closed** — `submit_write`: a `backfill` job, never beside
    順's reorder in this process; cancelled before it starts, it never writes.
  * **Restore putting back what nobody asked about** — `restore_plan`: Connect's unfinished fill first, the snapshot's
    time read before the question.
  * **The command line filling while the window is open** — `WindowLock` holds `backfill-window`.
  * **The library set swapped under a reader** — `BuildWatch` hands the swap over only when idle.

Real Japanese words on Lapis field names; no Anki (the engine's fakes), no Qt.
"""
import threading
import time
from unittest import mock

import pytest

from app import locks
from app.services import jobs
from modules.junban import backfill, undo
from modules.junban import backfill_view as V
from modules.junban import qt_strings as S
from modules.junban.tests.test_backfill import FIELD, FIRST_NOTE, _fake, _lapis, _Session, _settings
from modules.junban.tests.test_reposition import _patched

PATTERNS, SENTENCE = backfill.FILLS


def _result(rows=None, edits=None, models=None, by_fill=None):
    rows = rows if rows is not None else [(FIRST_NOTE, "探検", "Patterns", "fill", FIELD["探検"], "patterns"),
                                          (FIRST_NOTE + 1, "大切", "Patterns", "filled", "", "patterns"),
                                          (FIRST_NOTE + 2, "話が弾む", "Patterns", "phrase", "", "patterns")]
    return {"scope": {"models": models if models is not None else
                      {"Lapis": {"fields": ["Expression", "Patterns"], "count": 3, "mapped": {"patterns": "Patterns"}}},
                      "notes": []},
            "edits": edits if edits is not None else {FIRST_NOTE: {"Patterns": {"before": "", "after": FIELD["探検"]}}},
            "rows": rows, "by_fill": by_fill or {"patterns": {"fill": 1, "filled": 1, "phrase": 1}}}


# --- the choices and the preview key (Tk: _choices, _key, _save) -------------------------------------------------- #
def test_the_choices_read_from_settings_and_hand_out_fresh_containers_every_time():
    saved = {"junban_backfill_deck": " TheBank ", "junban_backfill_cards": "new", "junban_backfill_replace": True,
             "junban_backfill_fills": ["sentence", "patterns"], "junban_backfill_fields": {"patterns": {"Lapis": ""}},
             "junban_backfill_note_languages": {"Lapis": "ja", "Odd": "fr"}}
    c = V.Choices.from_settings(saved)
    assert (c.deck, c.cards, c.replace, c.fills) == ("TheBank", "new", True, ("patterns", "sentence"))
    assert c.note_languages == {"Lapis": "ja"}                       # not a language: not a setting
    a, b = c.settings(), c.settings()
    assert a == b and a["junban_backfill_fields"] is not b["junban_backfill_fields"]
    assert a["junban_backfill_fields"]["patterns"] is not saved["junban_backfill_fields"]["patterns"]
    a["junban_backfill_fields"]["patterns"]["Lapis"] = "Patterns"     # a caller's edit never reaches the choices
    assert c.fields == {"patterns": {"Lapis": ""}}


def test_a_save_writes_only_the_keys_the_user_changed():
    before = V.Choices.from_settings({})
    after = before.but(deck="TheBank")
    assert after.changed(before) == {"junban_backfill_deck": "TheBank"}
    assert before.but().changed(before) == {}
    fields = after.but(fields={"patterns": {"Lapis": "Patterns"}})
    assert set(fields.changed(after)) == {"junban_backfill_fields"}


def test_the_preview_key_names_the_language_and_every_choice():
    c = V.Choices.from_settings({"junban_backfill_fills": ["patterns"]})
    key = c.key("ja")
    assert key == c.but().key("ja")
    assert key != c.key("zh")                                       # another language's preview is no confirmation
    for other in (c.but(deck="TheBank"), c.but(cards="new"), c.but(replace=True), c.but(fills=["sentence"]),
                  c.but(fields={"patterns": {"Lapis": "Patterns"}}), c.but(note_languages={"Lapis": "zh"})):
        assert other.key("ja") != key


# --- the safety gate (Tk: _sync_buttons' Fill rule) ----------------------------------------------------------------- #
def test_fill_needs_idle_a_preview_of_exactly_the_choices_on_screen_and_something_to_write():
    c = V.Choices.from_settings({})
    key, preview = c.key("ja"), _result()
    assert V.fill_ready(False, key, key, preview) is True
    assert V.fill_ready(True, key, key, preview) is False             # a job runs
    assert V.fill_ready(False, None, key, preview) is False           # no preview
    assert V.fill_ready(False, c.key("zh"), key, preview) is False    # a preview of something else
    assert V.fill_ready(False, key, key, _result(edits={})) is False  # nothing to write
    assert V.fill_ready(False, key, key, None) is False


def test_build_and_preview_only_while_a_ticked_fill_of_this_language_has_nothing_to_fill_from():
    c = V.Choices.from_settings({"junban_backfill_fills": ["patterns"]})
    assert V.needs_build(c, "ja", data_ready=False) is True
    assert V.needs_build(c, "ja", data_ready=True) is False
    assert V.needs_build(c.but(fills=[]), "ja", data_ready=False) is False
    assert V.preview_button(True) == (S.BF_BUILD_PREVIEW, S.BF_BUILD_PREVIEW_TIP)
    assert V.preview_button(False) == (S.BF_PREVIEW, S.BF_PREVIEW_TIP)


def test_get_data_shows_only_without_a_general_database_and_rebuild_only_with_a_library_set():
    assert V.show_get_data("ja", general_ready=False) is True
    assert V.show_get_data("ja", general_ready=True) is False
    assert V.show_get_data("ja", general_ready=None) is False        # not read yet: nothing shown
    assert V.show_rebuild("zh", data_ready=True) is True
    assert V.show_rebuild("zh", data_ready=False) is False
    assert V.show_rebuild("zh", data_ready=None) is False            # not read yet: nothing shown (mutant V10)
    assert V.show_rebuild("fr", data_ready=True) is False            # a language never offered パターン
    assert V.fill_tip(PATTERNS, "fr") == S.BF_NOT_OFFERED_TIP and V.fill_tip(PATTERNS, "zh") == PATTERNS.tip


# --- what the window shows ------------------------------------------------------------------------------------------ #
def test_the_fill_button_says_where_it_goes():
    lapis = {"fields": ["Patterns"], "count": 3, "mapped": {"patterns": "Patterns"}}
    migaku = {"fields": ["Sentence"], "count": 2, "mapped": {"patterns": None}}
    assert V.target_text(PATTERNS, {}) == S.BF_TARGET_NONE
    assert V.target_text(PATTERNS, {"Migaku Japanese": migaku}) == S.BF_TARGET_CHOOSE
    assert V.target_text(PATTERNS, {"Lapis": lapis, "Migaku Japanese": migaku}) == "Lapis → Patterns"
    assert V.target_text(PATTERNS, {"Lapis": lapis, "Other": dict(lapis)}) == "2 note types"


def test_the_table_lists_writes_first_and_says_how_many_more_past_its_cap():
    rows = [(FIRST_NOTE + i, f"単語{i}", "Patterns", "filled", "", "patterns") for i in range(5)]
    rows.append((FIRST_NOTE + 9, "探検", "Patterns", "fill", FIELD["探検"], "patterns"))
    shown, more = V.preview_rows({"rows": rows}, cap=3)
    assert more == 3 and len(shown) == 3
    assert shown[0] == ("探検", "パターン", "fill", "〜に 34% · 〜を 24%", True)
    assert shown[1][4] is False and shown[1][2] == "already filled"
    assert V.preview_rows({"rows": rows})[1] == 0


def test_the_summary_line_and_its_empty_states():
    c = V.Choices.from_settings({"junban_backfill_fills": ["patterns"]})
    assert V.summary_line(_result(), c, {}) == "Fill 1 note · 2 skipped"
    assert V.summary_line(_result(rows=[]), c.but(fills=[]), {}) == S.BF_SUMMARY_TICK
    assert V.summary_line(_result(rows=[]), c, {"Lapis": {}}) == S.BF_SUMMARY_CHOOSE_FIELD
    assert V.summary_line(_result(rows=[]), c, {}) == S.BF_SUMMARY_NO_CARDS


def test_the_details_explain_each_skip_and_say_nothing_without_one():
    title, sections = V.details(_result())
    assert title == "" and ("1 already filled", backfill.REASON_HELP["already filled"], "") in sections
    assert any(h == "1 phrase" for h, _l, _e in sections)
    assert V.details(_result(by_fill={"patterns": {"fill": 3}})) == ("", [])
    both = V.details(_result(by_fill={"patterns": {"fill": 1, "phrase": 1}, "sentence": {"fill": 2}}))[1]
    assert ("パターン", "1 to fill · 1 skipped", "") in both and ("例文", "2 to fill", "") in both
    assert "&lt;b&gt;" in V.help_html(("", [("<b>", "x", "")]))       # escaped for the bubble


def test_the_fields_window_edits_are_fresh_containers_and_unset_a_language():
    c = V.Choices.from_settings({"junban_backfill_note_languages": {"Lapis": "ja"}})
    models = {"Lapis": {"fields": ["Patterns", "Notes"], "count": 3, "mapped": {"patterns": "Patterns"},
                        "language": "ja"}}
    c2, m2 = V.with_mapping(c, models, "patterns", "Lapis", S.BF_FIELDS_SKIP)
    assert c2.fields == {"patterns": {"Lapis": backfill.SKIP}} and m2["Lapis"]["mapped"]["patterns"] is None
    assert models["Lapis"]["mapped"]["patterns"] == "Patterns" and c.fields == {}      # the old ones untouched
    c3, m3 = V.with_note_language(c2, m2, "Lapis", S.BF_LANGUAGE_UNSET)
    assert c3.note_languages == {} and m3["Lapis"]["language"] is None and c2.note_languages == {"Lapis": "ja"}
    c4, _ = V.with_note_language(c3, m3, "Lapis", S.BF_LANGUAGE_ZH)
    assert c4.note_languages == {"Lapis": "zh"}
    rows = V.fields_rows(PATTERNS, {"B": {"fields": ["x"], "count": 9, "mapped": {}},
                                    "A": {"fields": ["P"], "count": 1, "mapped": {"patterns": "P"}}})
    assert [r[0] for r in rows] == ["A", "B"] and rows[0][3] == "P" and rows[1][3] == S.BF_FIELDS_SKIP


def test_lines_from_a_job():
    assert V.status_numbers("Reading your library: 900 / 1,987 files…") == (900, 1987)
    assert V.status_numbers("Reading your cards…") is None
    assert V.download_line(3_400_000, 32_000_000) == ("Downloading… 3 / 32 MB", 3)
    assert V.download_line(10, 0)[0] == S.BF_SUMMARY_DOWNLOADING
    assert V.build_line(None) == "" and V.build_line(("ja", 0, 0)) == S.BF_BUILD_LINE
    assert V.build_line(("ja", 120, 1987)) == S.BF_BUILD_LINE_FILES.format(done="120", total="1,987")


# --- read on a worker (inv defect 1) -------------------------------------------------------------------------------- #
def test_readiness_is_read_in_one_place_and_a_failing_read_counts_as_not_ready():
    with mock.patch.object(backfill, "data_ready", lambda language: True), \
            mock.patch.object(backfill, "general_ready", lambda language: False), \
            mock.patch.object(backfill, "rebuild_tip", lambda language: "Built 2026-10-01 from 12 files."):
        ready = V.read_readiness("ja")
    assert (ready.language, ready.data, ready.general) == ("ja", True, False)
    assert ready.tip == "Built 2026-10-01 from 12 files."

    def broken(language):
        raise OSError("database is locked")
    with mock.patch.object(backfill, "data_ready", broken), mock.patch.object(backfill, "general_ready", broken):
        ready = V.read_readiness("zh")
    assert (ready.data, ready.general, ready.tip) == (False, False, S.BF_REBUILD_TIP)


# --- the restore order (Tk: on_restore) ----------------------------------------------------------------------------- #
def test_restore_names_connects_unfinished_fill_first_and_otherwise_the_snapshot_read_before_asking():
    assert V.restore_plan("ja").kind == "nothing"
    fake = _fake(_lapis(0, "探検", "たんけん"))
    with _patched(fake):
        backfill.run(_settings(), _Session())
    plan = V.restore_plan("ja")
    assert plan.kind == "snapshot" and plan.confirmed == undo.load("ja", kind="backfill")["written_at"]
    assert plan.line.startswith("1 note filled") and plan.title() == S.BF_ASK_RESTORE
    run_id = "backfill-20261006-040000-000"
    undo.save([], ["TheBank"], kind="backfill", run_id=run_id,
              fields={FIRST_NOTE: {"Patterns": {"before": "", "after": FIELD["探検"]}}})
    plan = V.restore_plan("ja")
    assert plan.kind == "run" and plan.run == run_id and plan.title() == S.BF_ASK_RUN and run_id in plan.line


def test_the_restore_a_yes_runs_is_exactly_the_one_it_was_asked_about():
    seen = []
    with mock.patch.object(backfill, "restore", lambda settings, **k: seen.append(k) or {"ok": True}):
        stop = threading.Event()
        V.restore_work(V.RestorePlan("ja", "run", run="r1"), {}, stop, None)()
        V.restore_work(V.RestorePlan("ja", "snapshot", confirmed="2026-10-14T10:00"), {}, stop, None)()
    assert seen[0]["run"] == "r1" and "confirmed" not in seen[0]
    assert seen[1]["confirmed"] == "2026-10-14T10:00" and "run" not in seen[1]
    assert all(k["wait"] is None and k["cancel"] is stop for k in seen)


def test_the_fill_a_yes_runs_writes_only_the_preview_it_was_asked_about():
    seen = {}

    def run(settings, session, **k):
        seen.update(k, session=session)
        return {"ok": True}
    keeper = V.SessionKeeper(make=lambda settings: _Session())
    planned, stop = _result(), threading.Event()
    with mock.patch.object(backfill, "run", run):
        V.fill_work(_settings(), keeper, planned, stop, None)()
    assert seen["planned"] is planned and seen["wait"] is None and seen["cancel"] is stop
    assert seen["session"] is keeper.session


# --- the session, the window lock --------------------------------------------------------------------------------- #
class _Counted:
    made = []

    def __init__(self, settings):
        self.language, self.closed = settings["target_language"], False
        _Counted.made.append(self)

    def close(self):
        self.closed = True


def test_the_session_is_made_once_per_language_and_closed_before_another():
    _Counted.made = []
    keeper = V.SessionKeeper(make=_Counted)
    a = keeper.get({"target_language": "ja"})
    assert keeper.get({"target_language": "ja"}) is a
    b = keeper.get({"target_language": "zh"})
    assert a.closed and not b.closed and len(_Counted.made) == 2
    keeper.close()
    keeper.close()                                  # twice is fine
    assert b.closed and keeper.session is None


def test_the_window_lock_is_held_until_released_and_a_release_before_the_take_lets_it_go():
    lock = V.WindowLock()
    assert lock.hold() is True and lock.held()
    assert locks.in_use("backfill-window")                          # surasura-cli backfill stands aside
    assert locks.read_holder("backfill-window")["verb"] == S.BF_LOCK_VERB
    lock.release()
    assert not lock.held() and not locks.in_use("backfill-window")
    late = V.WindowLock()
    late.release()                                  # the window closed before its worker took the lock
    assert late.hold() is False and not locks.in_use("backfill-window")


def test_a_second_window_lock_waits_then_gives_up_while_the_first_is_held():
    first, second = V.WindowLock(), V.WindowLock()
    assert first.hold()
    start = time.monotonic()
    assert second.hold() is False and time.monotonic() - start >= 1.5     # waited its 2 s, then no
    first.release()


# --- every Fill and Restore a `backfill` job ----------------------------------------------------------------------- #
def _wait(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_a_write_is_a_backfill_job_and_waits_for_junbans_reorder_in_this_process():
    registry, ran, ended = jobs.JobRegistry(), [], []
    reorder = registry.submit("junban", "Reordering", lambda job: None)
    job = V.submit_write(registry, S.BF_JOB_FILL, lambda: ran.append(1) or {"ok": True, "message": "Filled 1 note."},
                         ended.append, threading.Event())
    assert job.kind == "backfill" and job.on_quit == "wait" and job.state == jobs.WAITING and ran == []
    reorder.finish()
    assert _wait(lambda: ended) and ran == [1] and ended[0]["ok"]
    assert _wait(lambda: job.state == jobs.DONE)


def test_a_write_cancelled_before_it_started_never_runs_and_says_so_once():
    registry, ran, ended, stop = jobs.JobRegistry(), [], [], threading.Event()
    reorder = registry.submit("junban", "Reordering", lambda job: None)
    job = V.submit_write(registry, S.BF_JOB_FILL, lambda: ran.append(1) or {"ok": True}, ended.append, stop)
    job.cancel()
    reorder.finish()
    time.sleep(0.2)
    assert ran == [] and ended == [None] and stop.is_set()
    assert job.state == jobs.DONE and job.cancelled


class _Recorded:
    """A registry that hands back the job's start and cancel callbacks, to drive them in a chosen order."""

    def __init__(self):
        self.calls = {}
        self.finished = []

    def submit(self, kind, label, start, cancel=None, automatic=False, on_quit="cancel"):
        self.calls = {"kind": kind, "start": start, "cancel": cancel}
        registry = self

        class Job:
            def finish(self, **kwargs):
                registry.finished.append(kwargs)
        self.job = Job()
        return self.job


def test_a_cancel_that_lands_as_the_registry_starts_the_write_never_runs_it():
    # Mutant V25's witness, and the race it exposed: the registry marks the job running, then calls `start` outside
    # its lock; a close's cancel in between found it "not started", said "nothing was written" — and the write then ran
    # anyway (a cancel only stops a wait for another writer, never a free lock). Told once, and never run after.
    registry, ran, ended, stop = _Recorded(), [], [], threading.Event()
    V.submit_write(registry, S.BF_JOB_FILL, lambda: ran.append(1) or {"ok": True}, ended.append, stop)
    registry.calls["cancel"](registry.job)
    registry.calls["start"](registry.job)
    time.sleep(0.2)
    assert ran == [] and ended == [None] and stop.is_set()
    assert registry.finished == [{"ok": True, "cancelled": True}]


def test_a_failed_write_is_a_failed_job_with_its_words_and_a_wait_stopped_by_the_window_is_cancelled():
    registry, ended = jobs.JobRegistry(), []
    report = backfill._report(False, "Nothing was filled.", problems=["The last fill did not finish."])
    job = V.submit_write(registry, S.BF_JOB_FILL, lambda: report, ended.append, threading.Event())
    assert _wait(lambda: job.state == jobs.FAILED)
    assert job.message == "Nothing was filled. The last fill did not finish." and ended == [report]
    stop = threading.Event()
    stop.set()
    busy = backfill._report(False, "Nothing was filled.", problems=["cancelled"], busy=True)
    job = V.submit_write(registry, S.BF_JOB_FILL, lambda: busy, ended.append, stop)
    assert _wait(lambda: job.state == jobs.DONE) and job.cancelled


def test_a_write_that_raises_is_still_a_failed_job_and_its_owner_hears():
    registry, ended = jobs.JobRegistry(), []

    def boom():
        raise RuntimeError("disk full")
    job = V.submit_write(registry, S.BF_JOB_RESTORE, boom, ended.append, threading.Event())
    assert _wait(lambda: job.state == jobs.FAILED) and ended and ended[0]["problems"] == ["disk full"]


def test_closing_mid_wait_through_the_job_writes_nothing():
    # Another program holds the Anki writer: the fill waits inside its job; the window closes (its stop event) and
    # the fill gives up without a single write.
    from app import anki_connect
    fake = _fake(_lapis(0, "探検", "たんけん"))
    with _patched(fake):
        planned = backfill.preview(_settings(), _Session())
    taken, done = threading.Event(), threading.Event()

    def hold():
        with anki_connect.writer("Backfill"):
            taken.set()
            done.wait(30)
    holder = threading.Thread(target=hold, daemon=True)
    holder.start()
    assert taken.wait(5)
    registry, ended, stop, waits = jobs.JobRegistry(), [], threading.Event(), []
    keeper = V.SessionKeeper(make=lambda settings: _Session())
    with _patched(fake):
        V.submit_write(registry, S.BF_JOB_FILL, V.fill_work(_settings(), keeper, planned, stop, waits.append),
                       ended.append, stop)
        assert _wait(lambda: waits)
        stop.set()
        assert _wait(lambda: ended, 10)
    done.set()
    holder.join(5)
    assert ended[0]["busy"] is True and fake.note_writes == []


# --- the library build -------------------------------------------------------------------------------------------- #
class _Process:
    def __init__(self, lines, code=0):
        self.stdout, self.code = iter(lines), code

    def wait(self):
        return self.code


def test_build_and_preview_reads_the_build_through_the_engines_one_reader():
    seen = []
    with mock.patch.object(backfill, "start_rebuild", lambda language, reinforce: _Process(
            ["PROGRESS 25/100", "PROGRESS 100/100", "Built: 1,987 words"], 0)):
        assert V.build_library("ja", False, lambda d, t: seen.append((d, t))) == (True, "Built: 1,987 words")
    assert seen == [(25, 100), (100, 100)]
    with mock.patch.object(backfill, "start_rebuild", lambda language, reinforce: None):
        assert V.build_library("ja", False, seen.append) is None             # never two at once
    assert backfill.read_build(_Process(["oops: no token store"], 1)) == (False, "oops: no token store")


def test_the_background_build_follows_through_the_same_reader():
    backfill._BACKGROUND.clear()
    backfill._FAILED.clear()
    seen = []
    real = backfill.read_build

    def spy(process, on_progress=None):
        seen.append(process)
        return real(process, on_progress)
    with mock.patch.object(backfill, "read_build", spy), mock.patch.object(backfill, "promote", lambda language: True):
        backfill._follow(_Process(["PROGRESS 5/9"], 1), "ja")
    assert seen and backfill._FAILED == {"ja": "it stopped"}
    backfill._FAILED.clear()


def test_a_rebuild_held_back_by_an_update_says_it_waits_never_that_it_failed():
    backfill._PROCESS = None
    backfill._BACKGROUND.clear()
    with mock.patch.object(backfill, "_update_waiting", lambda: True), \
            mock.patch.object(backfill, "rebuild_in_background", lambda *a, **k: False):
        assert V.rebuild_now("ja", False) == "deferred"
    with mock.patch.object(backfill, "_update_waiting", lambda: False), \
            mock.patch.object(backfill, "rebuild_in_background", lambda *a, **k: False):
        assert V.rebuild_now("ja", False) == "failed"
    with mock.patch.object(backfill, "_update_waiting", lambda: False), \
            mock.patch.object(backfill, "rebuild_in_background", lambda *a, **k: True):
        assert V.rebuild_now("ja", False) == "started"
    with mock.patch.object(backfill, "building", lambda: True):
        assert V.rebuild_now("ja", False) == "building"


def test_a_finished_background_build_goes_in_only_when_the_window_is_idle():
    watch = V.BuildWatch()
    assert watch.step(None) == ("", False, False) and not watch.active()
    line, started, ended = watch.step(("ja", 0, 0))
    assert started and not ended and line == S.BF_BUILD_LINE
    assert watch.step(("ja", 25, 100))[1] is False                  # started once
    assert watch.step(None) == ("", False, True)
    assert watch.take_swap(busy=True) is None and watch.active()    # a job reads the set in use: not yet
    assert watch.take_swap(busy=False) == "ja" and watch.take_swap(busy=False) is None


def test_the_promote_closes_the_session_before_the_set_is_replaced():
    order = []

    class Held:
        def close(self):
            order.append("close")
    keeper = V.SessionKeeper(make=lambda settings: Held())
    keeper.get({"target_language": "ja"})
    with mock.patch.object(backfill, "promote", lambda language: order.append(("promote", language)) or True):
        assert V.promote_now(keeper, "ja") is True
    assert order == ["close", ("promote", "ja")]


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_both_languages_are_offered_both_fills(language):
    assert V.offered(PATTERNS, language) and V.offered(SENTENCE, language)


# --- the fix round: AD5-1, AD5-2 -------------------------------------------------------------------------------- #
def test_a_preview_is_shown_as_the_worker_made_it_rows_summary_and_details():
    # AD5-1: everything the window paints for a preview comes from one call its worker makes.
    choices = V.Choices(fills=["patterns"])
    shown = V.shown(_result(), choices)
    assert shown.rows == V.preview_rows(_result())[0] and shown.more == 0
    assert shown.models == V.models_of(_result()) and shown.summary == V.summary_line(_result(), choices, shown.models)
    content = V.details(_result())
    assert shown.details == (V.help_html(content) if content[1] else "")


def test_the_engine_reads_the_window_makes_on_its_thread_touch_no_file():
    # AD5-2: `building`, `background`, `failed_note`, `help_for` and `shared_for` are read on the window's thread (every
    # sync, every 250 ms while a build runs): each is a table or a child's exit code, never a file, a lock or SQLite.
    import builtins
    import os
    import sqlite3
    from modules.junban import patterns_package

    def no(*_a, **_k):
        raise AssertionError("a file was touched")

    class Running:
        def poll(self):
            return None
    with mock.patch.object(backfill, "_PROCESS", Running()), \
            mock.patch.dict(backfill._BACKGROUND, {"language": "ja", "done": 3, "total": 9}), \
            mock.patch.dict(backfill._FAILED, {"zh": "disk full"}), \
            mock.patch.object(builtins, "open", no), mock.patch.object(os, "stat", no), \
            mock.patch.object(os.path, "exists", no), mock.patch.object(os, "listdir", no), \
            mock.patch.object(sqlite3, "connect", no):
        assert backfill.building() is True
        assert backfill.background() == ("ja", 3, 9)
        assert "disk full" in backfill.failed_note() and backfill.failed_note() == ""
        assert all(backfill.help_for(fill, language) for fill in backfill.FILLS for language in ("ja", "zh"))
        assert patterns_package.shared_for("ja")["sha256"]
        patterns_package.shared_for("zh")


def test_the_first_connection_arms_one_automatic_preview_never_under_test():
    # IK-80: "It just works": once per window, only when connected, never with the test switches on (it reads Anki).
    assert V.auto_preview_due(True, False, {}) is True
    assert V.auto_preview_due(True, True, {}) is False
    assert V.auto_preview_due(False, False, {}) is False
    assert V.auto_preview_due(True, False, {"SURASURA_NO_UI_TIMERS": "1"}) is False
    assert V.auto_preview_due(True, False, {"SURASURA_NO_ANKI_SYNC": "1"}) is False


def test_the_writes_own_line_names_what_it_waits_for_then_that_it_writes():
    # IK-75: the registry's reason, in the window's words.
    assert V.job_line(jobs.WAITING, "waits for Reordering", S.BF_JOB_FILL) == S.BF_JOB_WAITING_FOR.format(
        what="Reordering")
    assert V.job_line(jobs.WAITING, "Surasura is updating", S.BF_JOB_FILL) == S.BF_JOB_WAITING.format(
        reason="Surasura is updating")
    assert V.job_line(jobs.WAITING, None, S.BF_JOB_FILL) == S.BF_JOB_WAITING_TURN
    assert V.job_line(jobs.RUNNING, None, S.BF_JOB_RESTORE) == S.BF_JOB_RUNNING.format(label=S.BF_JOB_RESTORE)
    assert V.job_line(jobs.DONE, None, S.BF_JOB_FILL) is None and V.job_line(jobs.QUEUED, None, "x") is None


def test_a_refusal_the_window_did_not_cause_is_a_failed_job_never_a_cancel():
    # Haiku H12's witness: "busy" also means an update waiting, the user reviewing, or cards changed during a wait;
    # only the window's own stop makes it a cancel. Otherwise the bar says why nothing was written.
    registry, ended = jobs.JobRegistry(), []
    busy = backfill._report(False, "Nothing was filled.", problems=["An update is waiting to install."], busy=True)
    job = V.submit_write(registry, S.BF_JOB_FILL, lambda: busy, ended.append, threading.Event())
    assert _wait(lambda: job.state == jobs.FAILED) and not job.cancelled
    assert job.message == "Nothing was filled. An update is waiting to install." and ended == [busy]


def test_a_cancel_while_the_write_runs_never_says_nothing_was_written():
    # Haiku H13's witness: once the write runs, a cancel only stops a wait; its owner hears the write's own report,
    # once — never "nothing was written" while it writes.
    registry, ended, release, running = jobs.JobRegistry(), [], threading.Event(), threading.Event()
    report = backfill._report(True, "Filled 1 note.")

    def work():
        running.set()
        release.wait(5)
        return report
    stop = threading.Event()
    job = V.submit_write(registry, S.BF_JOB_FILL, work, ended.append, stop)
    assert running.wait(5)
    job.cancel()
    assert stop.is_set() and ended == []
    release.set()
    assert _wait(lambda: ended == [report])
