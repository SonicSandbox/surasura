"""The sentence dictionary window (W3.4 row 1; `app/qt/sentence_dictionary_window.py`, the Tk dashboard's export
dialog ported).

What a wrong answer would cost (inv-youtube-koe-dict §4): "ready" for a dictionary that wasn't made (the Tk dialog
judged by the file's time alone — an exit 1 beside a fresh file, a stale file); the remembered answer changed by Cancel,
or saved by rewriting the dashboard's ~45 keys; two exports racing on one file; a run on an empty library; the result
lost when the window closed before the export ended; Yomitan's "delete the older one first" warning dropped.
"""
import json
import os
import time
import zipfile

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QApplication, QFileDialog

from app import sentence_corpus
from app.qt import sentence_dictionary_window as sdw
from app.qt import shell, strings, windows
from app.services import jobs as jobs_module
from app.services import tools
from tests.qt.conftest import wait_until
from tests.qt.test_wiring import problems


@pytest.fixture
def main(qapp):
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.show()
    yield win
    win.close()
    services.shutdown(0.5)


def _library(lines):
    root = os.environ["SURASURA_TEST_ROOT"]
    now = os.path.join(root, "data", "ja", "HighPriority")
    os.makedirs(now, exist_ok=True)
    with open(os.path.join(now, "第01話.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.makedirs(os.path.join(root, "User Files", "ja"), exist_ok=True)


def _context_lines(ja_resources_dir):
    with open(os.path.join(ja_resources_dir, "context_test.txt"), encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def _zip(path, description="2,345 words · 8 sentences each"):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("index.json", json.dumps({"title": "Surasura Corpus (ja)", "description": description}))


class FakeRun:
    """`tools.run` recorded: the argv, and the end handed back when the test says (exit code, and what's on disk)."""

    def __init__(self, monkeypatch):
        self.calls = []
        monkeypatch.setattr(tools, "run", self)

    def __call__(self, registry, kind, label, argv, on_end=None, before=None, on_result=None, **kw):
        job = registry.submit(kind, label, start=lambda j: None)
        self.calls.append({"kind": kind, "label": label, "argv": argv, "on_end": on_end, "job": job,
                           "before": before, "on_result": on_result})
        return job

    def end(self, code, i=-1, cancelled=False, before=True):
        """As the real runner ends a job: on its own thread, `before` first (when it got that far), then the end."""
        import threading
        call = self.calls[i]

        def tool():
            if before and call["before"] is not None:
                call["before"]()
            call["job"].finish(ok=code == 0 or cancelled, cancelled=cancelled)
            if call["on_end"] is not None:
                call["on_end"](code)
            if call["on_result"] is not None:
                call["on_result"](tools.Result(code, cancelled, None, tools.log_path("sentence-corpus")))
        t = threading.Thread(target=tool)
        t.start()
        t.join(10)


@pytest.fixture
def save_to(monkeypatch, tmp_path):
    out = str(tmp_path / "Surasura Corpus (ja).zip")
    asked = []

    def save(*a, **k):
        asked.append(a)
        return (out if save.answer else "", strings.DICT_SAVE_FILTER)
    save.answer = True
    save.asked = asked
    save.path = out
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(save))
    return save


@pytest.fixture
def content(monkeypatch):
    monkeypatch.setattr(sdw, "library_has_content", lambda language: True)


def _open(main):
    return windows.show(main, "sentence-dictionary", sdw.SentenceDictionaryWindow)


def _export(w):
    w.export_button.click()


# --- every control of the Tk dialog (inv-youtube-koe-dict §4.1) ------------------------------------------------ #
def test_every_control_is_here_wired_tipped_and_named(main):
    w = _open(main)
    assert w.windowTitle() == "Sentence dictionary — Surasura"
    assert w.heading.text() == "Surasura Corpus (ja)"                       # §4.1 #1
    assert w.source.text() == strings.DICT_SOURCE and not w.source.isChecked()   # #2, off by default
    assert "hovering a sentence" in w.source.toolTip()                       # #3, the hint folded into its tooltip
    assert w.export_button.text() == strings.DICT_EXPORT                     # #4 (#5 Cancel: ✕ / Esc)
    found, walked = problems(w)
    assert walked >= 4 and found == []


def test_an_empty_library_says_so_and_nothing_runs(main, save_to, monkeypatch):
    runs = FakeRun(monkeypatch)
    w = _open(main)
    _export(w)                                           # the real check: this test root has no library
    assert wait_until(lambda: w.status.text() == strings.DICT_EMPTY)
    assert save_to.asked == [] and runs.calls == [] and w.export_button.isEnabled() and not w.busy()


def test_cancel_at_save_as_runs_nothing_and_saves_nothing(main, save_to, content, monkeypatch):
    runs = FakeRun(monkeypatch)
    saved = []
    monkeypatch.setattr(main.services.settings, "set", lambda changes, **k: saved.append(changes))
    w = _open(main)
    w.source.setChecked(True)
    save_to.answer = False
    _export(w)
    assert wait_until(lambda: save_to.asked)
    QApplication.processEvents()
    assert runs.calls == [] and saved == [] and w.export_button.isEnabled() and not w.busy()


def test_export_saves_the_one_key_alone_and_runs_with_show_source(main, save_to, content, monkeypatch):
    runs = FakeRun(monkeypatch)
    saved = []
    monkeypatch.setattr(main.services.settings, "set", lambda changes, **k: saved.append(changes))
    w = _open(main)
    w.source.setChecked(True)
    _export(w)
    assert wait_until(lambda: runs.calls)
    assert saved == [{"sentence_dictionary_source": True}]
    call = runs.calls[0]
    assert call["kind"] == "sentence-corpus" and call["label"] == strings.DICT_JOB
    assert call["argv"] == ["sentence_corpus.py", "--language", "ja", "--output", save_to.path, "--show-source"]


def test_an_unchanged_answer_saves_nothing_and_runs_without_show_source(main, save_to, content, monkeypatch):
    runs = FakeRun(monkeypatch)
    saved = []
    monkeypatch.setattr(main.services.settings, "set", lambda changes, **k: saved.append(changes))
    w = _open(main)
    _export(w)
    assert wait_until(lambda: runs.calls)
    assert saved == []
    assert runs.calls[0]["argv"] == ["sentence_corpus.py", "--language", "ja", "--output", save_to.path]


def test_the_settings_are_written_before_the_child_starts(main, save_to, content, monkeypatch):
    runs = FakeRun(monkeypatch)
    flushed = []
    monkeypatch.setattr(main.services.settings, "flush", lambda timeout=None: flushed.append(timeout) or True)
    w = _open(main)
    _export(w)
    assert wait_until(lambda: runs.calls)
    runs.calls[0]["before"]()
    assert flushed == [10.0]


# --- success is exit 0 and a fresh file ---------------------------------------------------------------------------- #
def test_exit_0_and_a_fresh_file_is_ready_with_the_yomitan_note_and_open_folder(main, save_to, content, monkeypatch):
    runs = FakeRun(monkeypatch)
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url) or True))
    w = _open(main)
    _export(w)
    assert wait_until(lambda: runs.calls)
    assert not w.export_button.isEnabled() and w.status.text() == strings.DICT_RUNNING.format(
        title="Surasura Corpus (ja)")
    _zip(save_to.path)
    runs.end(0)
    assert wait_until(lambda: w.export_button.isEnabled())
    assert w.status.text() == "Surasura Corpus (ja) is ready. 2,345 words · 8 sentences each"
    assert w.note.text() == strings.DICT_NOTE and "older one" in w.note.text()      # the warning kept, one line
    assert w.folder_button.isVisibleTo(w) and not w.log_button.isVisibleTo(w)
    w.folder_button.click()
    assert opened and opened[0].isLocalFile()
    assert os.path.normcase(os.path.normpath(opened[0].toLocalFile())) == \
        os.path.normcase(os.path.dirname(save_to.path))


def test_exit_1_is_a_failure_even_with_a_fresh_file_there(main, save_to, content, monkeypatch):
    runs = FakeRun(monkeypatch)
    w = _open(main)
    _export(w)
    assert wait_until(lambda: runs.calls)
    _zip(save_to.path)
    runs.end(1)
    assert wait_until(lambda: w.status.text() == strings.DICT_FAILED)
    assert w.log_button.isVisibleTo(w) and not w.folder_button.isVisibleTo(w) and w.note.text() == ""


def test_a_stale_file_with_exit_0_is_a_failure(main, save_to, content, monkeypatch):
    runs = FakeRun(monkeypatch)
    _zip(save_to.path)
    old = time.time() - 60
    os.utime(save_to.path, (old, old))                   # an older export the run never replaced
    w = _open(main)
    _export(w)
    assert wait_until(lambda: runs.calls)
    runs.end(0)
    assert wait_until(lambda: w.status.text() == strings.DICT_FAILED)


def test_no_file_with_exit_0_is_a_failure(main, save_to, content, monkeypatch):
    runs = FakeRun(monkeypatch)
    w = _open(main)
    _export(w)
    assert wait_until(lambda: runs.calls)
    runs.end(0)
    assert wait_until(lambda: w.status.text() == strings.DICT_FAILED)


def test_open_the_log_opens_the_exports_log(main, save_to, content, monkeypatch):
    runs = FakeRun(monkeypatch)
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url) or True))
    w = _open(main)
    _export(w)
    assert wait_until(lambda: runs.calls)
    runs.end(1)
    assert wait_until(lambda: w.log_button.isVisibleTo(w))
    w.log_button.click()
    assert os.path.normcase(opened[0].toLocalFile()) == os.path.normcase(
        tools.log_path("sentence-corpus").replace("\\", "/"))


# --- one at a time, and the window closing --------------------------------------------------------------------- #
def test_export_is_off_while_one_runs_and_a_second_press_starts_nothing(main, save_to, content, monkeypatch):
    runs = FakeRun(monkeypatch)
    w = _open(main)
    _export(w)
    assert wait_until(lambda: runs.calls)
    assert not w.export_button.isEnabled() and w.export_button.toolTip() == strings.DICT_EXPORT_BUSY_TIP
    w.export()
    QApplication.processEvents()
    assert len(runs.calls) == 1


def test_a_run_that_ends_after_the_window_closed_says_its_line_in_the_bar(main, save_to, content, monkeypatch):
    runs = FakeRun(monkeypatch)
    w = _open(main)
    _export(w)
    assert wait_until(lambda: runs.calls)
    w.close()
    QApplication.processEvents()
    _zip(save_to.path)
    runs.end(0)
    assert wait_until(lambda: main.bar_line.full().startswith("Surasura Corpus (ja) is ready."))


def test_a_language_switch_waits_for_the_export_then_shows_the_other_dictionary(main, save_to, content, monkeypatch):
    runs = FakeRun(monkeypatch)
    w = _open(main)
    _export(w)
    assert wait_until(lambda: runs.calls)
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: w._language_waiting == "zh")
    assert w.heading.text() == "Surasura Corpus (ja)"    # never cut: the run is ja's
    _zip(save_to.path)
    runs.end(0)
    assert wait_until(lambda: w.heading.text() == "Surasura Corpus (zh)")
    assert main.bar_line.full().startswith("Surasura Corpus (ja) is ready.")
    assert w.note.text() == "" and not w.folder_button.isVisibleTo(w)


# --- the real thing, end to end ---------------------------------------------------------------------------------- #
def test_the_window_builds_a_real_dictionary_through_the_job_registry(main, save_to, ja_resources_dir):
    _library(_context_lines(ja_resources_dir))
    w = _open(main)
    w.source.setChecked(True)
    _export(w)
    assert wait_until(lambda: w.job is not None, 30)
    view = w.job.view()
    assert view.kind == "sentence-corpus" and view.label == strings.DICT_JOB
    assert wait_until(lambda: w.export_button.isEnabled(), 180), w.status.text()
    assert w.status.text().startswith("Surasura Corpus (ja) is ready."), w.status.text()
    with zipfile.ZipFile(save_to.path) as zf:
        assert "index.json" in zf.namelist()
    assert main.services.registry.snapshot()[-1].state == jobs_module.DONE


# --- the success rule (Qt-free: sentence_corpus.export_result) --------------------------------------------------- #
def test_the_success_rule_wants_exit_0_and_a_file_written_since_the_start(tmp_path):
    path = str(tmp_path / "Surasura Corpus (zh).zip")
    started = time.time()
    assert sentence_corpus.export_result(path, started, 0) == (False, "")            # no file
    _zip(path, "1,024 words")
    assert sentence_corpus.export_result(path, started, 0) == (True, "1,024 words")
    assert sentence_corpus.export_result(path, started, 1) == (False, "")            # exit 1, fresh file
    assert sentence_corpus.export_result(path, started, None) == (False, "")         # never started
    assert sentence_corpus.export_result(path, started, -15) == (False, "")          # ended by a signal
    stale = started - sentence_corpus.FRESH_SLACK - 1
    os.utime(path, (stale, stale))
    assert sentence_corpus.export_result(path, started, 0) == (False, "")
    edge = started - sentence_corpus.FRESH_SLACK
    os.utime(path, (edge, edge))                                                      # within the clock's slack
    assert sentence_corpus.export_result(path, started, 0)[0] is True


def test_a_made_dictionary_without_a_readable_index_is_still_made(tmp_path):
    path = tmp_path / "Surasura Corpus (ja).zip"
    path.write_bytes(b"not a zip")
    assert sentence_corpus.export_result(str(path), time.time(), 0) == (True, "")


def test_the_command_line_names_the_language_the_file_and_the_choice():
    assert sentence_corpus.export_command("zh", "D:/x/y.zip", False) == [
        "sentence_corpus.py", "--language", "zh", "--output", "D:/x/y.zip"]
    assert sentence_corpus.export_command("ja", "D:/x/y.zip", True)[-1] == "--show-source"


# --- the fix round (AD1-6…10, IK-21, IK-22) ------------------------------------------------------------------------- #
def test_the_result_is_judged_off_the_windows_thread(main, save_to, content, monkeypatch):
    # AD1-6: the zip's time and index were read on the window's thread (a sleeping USB disk froze it).
    import threading
    gui = threading.current_thread()
    seen = []
    real = sentence_corpus.export_result

    def judged(*a):
        seen.append(threading.current_thread() is gui)
        return real(*a)
    monkeypatch.setattr(sentence_corpus, "export_result", judged)
    runs = FakeRun(monkeypatch)
    w = _open(main)
    _export(w)
    assert wait_until(lambda: runs.calls)
    _zip(save_to.path)
    runs.end(0)
    assert wait_until(lambda: w.export_button.isEnabled())
    assert seen == [False]
    assert w.status.text().startswith("Surasura Corpus (ja) is ready.")


def test_a_stopped_export_says_so_offers_no_log_and_leaves_no_temporary(main, save_to, content, monkeypatch):
    # IK-22 / AD1-7 / AD1-10: a stop is not "the log says why"; the child's half-built .tmp doesn't stay behind.
    runs = FakeRun(monkeypatch)
    w = _open(main)
    _export(w)
    assert wait_until(lambda: runs.calls)
    with open(save_to.path + ".tmp", "wb") as f:
        f.write(b"half a dictionary")
    runs.end(1, cancelled=True)
    assert wait_until(lambda: w.status.text() == strings.DICT_STOPPED)
    assert not w.log_button.isVisibleTo(w) and not w.folder_button.isVisibleTo(w)
    assert not os.path.exists(save_to.path + ".tmp")


def test_a_failed_export_leaves_no_temporary_and_never_touches_the_users_file(main, save_to, content, monkeypatch):
    runs = FakeRun(monkeypatch)
    _zip(save_to.path)
    old = time.time() - 600
    os.utime(save_to.path, (old, old))                    # an earlier dictionary at that name
    w = _open(main)
    _export(w)
    assert wait_until(lambda: runs.calls)
    with open(save_to.path + ".tmp", "wb") as f:
        f.write(b"half")
    runs.end(1)
    assert wait_until(lambda: w.status.text() == strings.DICT_FAILED)
    assert not os.path.exists(save_to.path + ".tmp") and os.path.exists(save_to.path)


def test_an_export_waiting_behind_generate_says_so(main, save_to, content, monkeypatch):
    # IK-22: "Building…" while it waits was untrue; the window says what it waits for.
    runs = FakeRun(monkeypatch)
    registry = main.services.registry
    generate = registry.submit("generate", "Generate", start=lambda j: None)
    w = _open(main)
    _export(w)
    assert wait_until(lambda: runs.calls)
    assert wait_until(lambda: w.status.text() == strings.DICT_WAITING_FOR.format(what="Generate"))
    generate.finish()
    assert wait_until(lambda: w.status.text() == strings.DICT_RUNNING.format(title="Surasura Corpus (ja)"))
    runs.end(1, cancelled=True)


def test_freshness_counts_from_the_childs_start_not_the_click(main, save_to, content, monkeypatch):
    # AD1-8: a gated export may wait minutes; a file written while it waited is no proof of this run.
    clock = {"now": 1_000_000.0}
    import types
    monkeypatch.setattr(sdw, "time", types.SimpleNamespace(time=lambda: clock["now"]))     # the window's clock only
    runs = FakeRun(monkeypatch)
    w = _open(main)
    _export(w)                                            # asked at 1,000,000
    assert wait_until(lambda: runs.calls)
    _zip(save_to.path)
    os.utime(save_to.path, (1_000_500.0, 1_000_500.0))    # written while it waited
    clock["now"] = 1_001_000.0                            # the child starts here
    runs.end(0)
    assert wait_until(lambda: w.status.text() == strings.DICT_FAILED)


def test_a_typed_name_that_gets_zip_added_and_exists_asks_first(main, save_to, content, monkeypatch, tmp_path):
    # AD1-9: the OS asked about the name typed; with ".zip" added after it, an existing file needs its own question.
    from app.qt import confirm
    runs = FakeRun(monkeypatch)
    typed = str(tmp_path / "My corpus")
    _zip(typed + ".zip")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (typed, strings.DICT_SAVE_FILTER)))
    w = _open(main)

    def card():
        cards = [c for c in w.findChildren(confirm.Confirm) if c.isVisible()]
        return cards[0] if cards else None
    _export(w)
    assert wait_until(lambda: card() is not None)
    assert card().title.text() == strings.DICT_REPLACE_ONE.format(name="My corpus.zip")
    assert QApplication.focusWidget() is card().no        # replacing: Cancel by default
    card().no.click()
    QApplication.processEvents()
    assert runs.calls == [] and w.export_button.isEnabled() and not w.busy()
    _export(w)
    assert wait_until(lambda: card() is not None)
    card().yes.click()
    assert wait_until(lambda: runs.calls)
    assert runs.calls[0]["argv"][4] == typed + ".zip"


def test_a_typed_name_with_zip_added_that_is_free_runs_without_asking(main, save_to, content, monkeypatch, tmp_path):
    runs = FakeRun(monkeypatch)
    typed = str(tmp_path / "New corpus")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (typed, strings.DICT_SAVE_FILTER)))
    w = _open(main)
    _export(w)
    assert wait_until(lambda: runs.calls)
    assert runs.calls[0]["argv"][4] == typed + ".zip"


def test_the_yomitan_note_is_one_short_line_with_the_file_in_its_tooltip(main, save_to, content, monkeypatch):
    # IK-21: less text — the path lives behind Open folder and in the tooltip, in Windows' own form.
    from PyQt6.QtCore import QDir
    runs = FakeRun(monkeypatch)
    w = _open(main)
    _export(w)
    assert wait_until(lambda: runs.calls)
    _zip(save_to.path)
    runs.end(0)
    assert wait_until(lambda: w.note.isVisibleTo(w))
    assert w.note.text() == strings.DICT_NOTE and "Delete" in w.note.text()
    assert QDir.toNativeSeparators(save_to.path) in w.note.toolTip()


def test_a_switch_while_the_library_is_looked_at_asks_nothing_and_runs_nothing(main, save_to, monkeypatch):
    # The look was for ja; the window moved to zh meanwhile: no Save-as for a dictionary of the other language.
    import threading
    looked, go_on = threading.Event(), threading.Event()

    def slow(language):
        looked.set()
        go_on.wait(10)
        return True
    monkeypatch.setattr(sdw, "library_has_content", slow)
    runs = FakeRun(monkeypatch)
    w = _open(main)
    _export(w)
    assert looked.wait(10)
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: w._language_waiting == "zh")
    go_on.set()
    assert wait_until(lambda: w.language == "zh")
    QApplication.processEvents()
    assert save_to.asked == [] and runs.calls == [] and w.export_button.isEnabled()
