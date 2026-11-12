# SPDX-License-Identifier: GPL-3.0-or-later
"""The preview's pipeline for the 3.0 window (W3.4 row 4; `preview.run_preview`, `preview.add_to_front`), Qt-free:
the Tk `PreviewGui._run`, moved, with the RUNBOOK's fixes (IK-2; inv §2.10 defects 1, 2, 3, 6).

What a wrong answer would cost: the preview writing `master_manifest.json` itself beside the library store (on 3.0 the
manifest is the store's copy: the helper's next copy erases the entry after the window said "Added" — IK-2, G4); a
busy store read as "needs repair"; an add refused by the store hiding the preview the user waited for; a video scored
against the other language's list (results/ holds one language's run); a video already in the library fetched again;
bilibili.com fetched though it can't give subtitles; a playlist question answered by a closed window starting a
fetch. yt-dlp is always faked; the store is real, on the suite's temp SURASURA_TEST_ROOT, for Japanese and Chinese.
"""
import json
import os
import tempfile
from unittest.mock import patch

import pytest

from app import library_store as ls
from modules.youtube_downloader import preview as pv
from tests.test_library_store_support import LANGUAGES, library, names, read_doc, roots, write_manifest

VIDEO = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
IN_LIST = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLabcdefghijk"
PLAYLIST = "https://www.youtube.com/playlist?list=PLabcdefghijk"


@pytest.fixture(autouse=True)
def _no_helper(monkeypatch):
    calls = []
    monkeypatch.setattr(ls, "spawn_maintain", lambda language, *extra: calls.append(language))
    return calls


def _cache(language, cached_language=None):
    path = pv.library_index_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    settings = {"min_count": 2, "total_tokens": 1000}
    if cached_language is not None:
        settings["language"] = cached_language
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"settings": settings, "words": {}}, f, ensure_ascii=False)


class Pipe:
    """The faked world: yt-dlp's lookup and download, the scorer, the report — each recorded in order."""

    def __init__(self, language, info=None, transcripts=1):
        self.language = language
        self.info = info if info is not None else {"_type": "video", "id": "dQw4w9WgXcQ"}
        self.transcripts = transcripts
        self.steps = []
        self.lines = []

    def probe(self, url, _log):
        self.steps.append(("probe", url))
        return self.info

    def ensure(self, _log):
        self.steps.append(("ensure",))
        return True

    def extract(self, urls, ws, lang, channel_first, log, should_stop=None):
        self.steps.append(("extract", tuple(urls), lang))
        words = names(self.language)
        for i in range(self.transcripts):
            with open(os.path.join(ws, f"{words[i]} - {words[i + 3]} [dQw4w9WgXc{i}].txt"), "w",
                      encoding="utf-8") as f:
                f.write(words[i] + words[i + 1] + "\n")

    def run(self, url, add_front=False, ask=None, should_stop=None):
        with patch.object(pv, "analyze_transcript", side_effect=lambda t, lang: self.steps.append(("score",)) or
                          ([], None)), \
             patch.object(pv, "generate_preview_html", side_effect=self._html):
            return pv.run_preview(url, self.language, add_front, ask or (lambda n: pytest.fail("asked")),
                                  self.lines.append, should_stop=should_stop, probe=self.probe, extract=self.extract,
                                  ensure=self.ensure)

    def _html(self, files, lang, out):
        self.steps.append(("html",))
        with open(out, "w", encoding="utf-8") as f:
            f.write("<html></html>")


def _paths(language):
    data_dir, user_files_dir = roots(language)
    return (patch.object(pv, "get_data_path", return_value=data_dir),
            patch.object(pv, "get_user_files_path", return_value=user_files_dir))


def _files(root):
    return sorted(os.path.relpath(os.path.join(r, n), root) for r, _d, fs in os.walk(root) for n in fs)


def _store(language):
    data_dir, user_files_dir, doc = library(language)
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    return data_dir, user_files_dir


# --- the order ----------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_bilibili_com_is_refused_before_anything_is_looked_up(language):
    _cache(language, language)
    pipe = Pipe(language)
    out = pipe.run("https://www.bilibili.com/bangumi/play/ep5137677")
    assert out.error == pv.BILIBILI_COM_REFUSED and out.html is None and pipe.steps == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_list_yet_asks_for_a_generate_and_fetches_nothing(language):
    pipe = Pipe(language)
    out = pipe.run(VIDEO)
    assert out.generate and out.error == pv.NO_CACHE and pipe.steps == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_another_languages_list_asks_for_a_generate_and_fetches_nothing(language):
    # inv defect 6: results/ holds one language's run; the Tk preview scored the video against it anyway.
    _cache(language, "zh" if language == "ja" else "ja")
    pipe = Pipe(language)
    out = pipe.run(VIDEO)
    assert out.generate and out.error == pv.OTHER_LANGUAGE and pipe.steps == []


def test_a_list_that_names_no_language_is_taken_as_it_is():
    _cache("ja")
    assert pv.cache_problem("ja") is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_video_already_in_the_library_is_never_fetched(language):
    _cache(language, language)
    data_dir, _u = roots(language)
    os.makedirs(os.path.join(data_dir, "LowPriority"), exist_ok=True)
    with open(os.path.join(data_dir, "LowPriority", f"{names(language)[0]} [dQw4w9WgXcQ].txt"), "w",
              encoding="utf-8") as f:
        f.write(names(language)[0])
    pipe = Pipe(language)
    with patch.object(pv, "get_data_path", return_value=data_dir):
        out = pipe.run(VIDEO)
    assert out.error == pv.ALREADY_IN_LIBRARY and pipe.steps == [("probe", VIDEO)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_preview_is_written_before_any_add_and_opens(language):
    _cache(language, language)
    pipe = Pipe(language)
    with patch.object(pv, "add_to_front", side_effect=lambda t, lang: pipe.steps.append(("add",)) or ["x.txt"]):
        out = pipe.run(VIDEO, add_front=True)
    assert [s[0] for s in pipe.steps] == ["probe", "ensure", "extract", "score", "html", "add"]
    assert out.html and os.path.exists(out.html) and out.added == ("x.txt",) and out.error is None
    assert pipe.lines == [pv.LOOKING_UP, pv.FETCHING, pv.SCORING]


def test_without_add_front_nothing_is_added():
    _cache("ja", "ja")
    pipe = Pipe("ja")
    with patch.object(pv, "add_to_front", side_effect=AssertionError("added")):
        out = pipe.run(VIDEO, add_front=False)
    assert out.html and out.added == () and out.note is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_refused_add_still_opens_the_preview_and_says_why(language):
    # inv defect 3: the Tk window jumped to the error and the preview it had built never opened.
    _cache(language, language)
    pipe = Pipe(language)
    with patch.object(pv, "add_to_front", side_effect=pv.PreviewError(pv.STORE_BUSY)):
        out = pipe.run(VIDEO, add_front=True)
    assert out.html and os.path.exists(out.html) and out.note == pv.STORE_BUSY and out.error is None


def test_the_playlist_question_just_this_video_fetches_only_the_video():
    _cache("ja", "ja")
    pipe = Pipe("ja", info={"_type": "playlist", "entries": [{}, {}, {}]})
    asked = []
    out = pipe.run(IN_LIST, ask=lambda n: asked.append(n) or False)
    assert asked == [3] and ("extract", (VIDEO,), "Japanese") in pipe.steps and out.html


def test_the_playlist_question_full_playlist_fetches_the_link():
    _cache("ja", "ja")
    pipe = Pipe("ja", info={"_type": "playlist", "entries": [{}, {}]})
    out = pipe.run(IN_LIST, ask=lambda n: True)
    assert ("extract", (IN_LIST,), "Japanese") in pipe.steps and out.html


def test_a_pure_playlist_asks_nothing():
    _cache("zh", "zh")
    pipe = Pipe("zh", info={"_type": "playlist", "entries": [{}]})
    out = pipe.run(PLAYLIST)
    assert ("extract", (PLAYLIST,), "Chinese") in pipe.steps and out.html


def test_a_question_the_closed_window_never_answered_fetches_nothing():
    _cache("ja", "ja")
    pipe = Pipe("ja", info={"_type": "playlist", "entries": [{}, {}]})
    out = pipe.run(IN_LIST, ask=lambda n: None)
    assert out == pv.Outcome() and [s[0] for s in pipe.steps] == ["probe"]


def test_a_window_closed_during_the_fetch_scores_and_adds_nothing():
    _cache("ja", "ja")
    pipe = Pipe("ja")
    closed = []
    real = pipe.extract

    def extract_then_close(*a, **k):
        real(*a, **k)
        closed.append(True)
    pipe.extract = extract_then_close
    with patch.object(pv, "add_to_front", side_effect=AssertionError("added")):
        out = pipe.run(VIDEO, add_front=True, should_stop=lambda: bool(closed))
    assert out._replace(workspace=None) == pv.Outcome() and out.workspace          # (its folder named for removal)
    assert "score" not in [s[0] for s in pipe.steps]


def test_a_window_closed_once_the_preview_is_written_adds_nothing():
    # The add is the run's last step and a write: a window closed while the preview was being written never adds.
    _cache("ja", "ja")
    pipe = Pipe("ja")
    with patch.object(pv, "add_to_front", side_effect=AssertionError("added")):
        out = pipe.run(VIDEO, add_front=True, should_stop=lambda: ("html",) in pipe.steps)
    assert out.html and out.added == () and out.note is None


def test_no_transcript_says_so():
    _cache("ja", "ja")
    pipe = Pipe("ja", transcripts=0)
    assert pipe.run(VIDEO).error == pv.NO_TRANSCRIPT


# --- the add: store mode only (IK-2) ------------------------------------------------------------------------------- #
def _transcript(language):
    word = names(language)[7]
    src = os.path.join(tempfile.mkdtemp(dir=os.environ["SURASURA_TEST_ROOT"]),     # the test's own folder (AD4-6)
                       f"{word} - {names(language)[8]} [dQw4w9WgXcQ].txt")
    with open(src, "w", encoding="utf-8") as f:
        f.write(word + "\n")
    return src


@pytest.mark.parametrize("language", LANGUAGES)
def test_store_mode_adds_with_one_insert_at_the_top_of_current(language, _no_helper):
    data_dir, user_files_dir = _store(language)
    src = _transcript(language)
    a, b = _paths(language)
    with a, b, patch.object(ls.Store, "insert", autospec=True, side_effect=ls.Store.insert) as insert:
        added = pv.add_to_front([src], language)
    assert added == [os.path.basename(src)] and insert.call_count == 1 and _no_helper == [language]
    with ls.open_store(language, data_dir, user_files_dir) as store:
        assert [e["physical_path"] for _i, e, _a in store.ordered("now")][0] == "HighPriority/" + os.path.basename(src)


@pytest.mark.parametrize("language", LANGUAGES)
def test_without_a_store_nothing_is_copied_and_the_manifest_is_left_alone(language):
    # IK-2: the Tk path's JSON fallback rewrote master_manifest.json itself; on 3.0 it says "busy, try again".
    data_dir, user_files_dir, doc = library(language)
    write_manifest(user_files_dir, doc)
    copy, files_before = read_doc(user_files_dir), _files(data_dir)
    a, b = _paths(language)
    with a, b, pytest.raises(pv.PreviewError) as refused:
        pv.add_to_front([_transcript(language)], language)
    assert str(refused.value) == pv.STORE_BUSY
    assert read_doc(user_files_dir) == copy and _files(data_dir) == files_before


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_damaged_store_refuses_and_copies_nothing(language):
    data_dir, user_files_dir = _store(language)
    ls.mark_damaged(ls.library_db_path(language, data_dir), "test")
    copy, files_before = read_doc(user_files_dir), _files(data_dir)
    a, b = _paths(language)
    with a, b, pytest.raises(pv.PreviewError) as refused:
        pv.add_to_front([_transcript(language)], language)
    assert str(refused.value) == pv.STORE_DAMAGED
    assert read_doc(user_files_dir) == copy and _files(data_dir) == files_before


@pytest.mark.parametrize("reason", ["busy", "io: disk I/O error"])
def test_a_busy_store_says_try_again_not_repair(reason):
    # inv defect 1: a momentarily locked database read as "can't take new files until it's repaired".
    data_dir, _u = _store("ja")
    files_before = _files(data_dir)
    a, b = _paths("ja")
    with a, b, patch.object(ls, "check_mode", return_value=("read-only", reason)), \
            pytest.raises(pv.PreviewError) as refused:
        pv.add_to_front([_transcript("ja")], "ja")
    assert str(refused.value) == pv.STORE_BUSY and _files(data_dir) == files_before


def test_a_probe_that_fails_is_busy_never_json():
    # inv defect 2: `_library_mode` fell open to JSON on any exception.
    data_dir, user_files_dir, doc = library("ja")
    write_manifest(user_files_dir, doc)
    copy = read_doc(user_files_dir)
    a, b = _paths("ja")
    with a, b, patch.object(ls, "check_mode", side_effect=OSError("held by antivirus")), \
            pytest.raises(pv.PreviewError, match="busy"):
        pv.add_to_front([_transcript("ja")], "ja")
    assert read_doc(user_files_dir) == copy


@pytest.mark.parametrize("probe", [lambda *a, **k: ("json", "no store"), lambda *a, **k: ("read-only", "busy"),
                                   OSError("held by antivirus")])
def test_the_add_never_opens_the_library_unless_it_reads_as_the_store(probe):
    # IK-2: the decision is the mode alone — no handle is asked for (and no folder made) unless the store is ready.
    data_dir, _u = roots("ja")
    a, b = _paths("ja")
    with a, b, patch.object(ls, "check_mode", side_effect=probe), \
            patch.object(ls, "open_store", side_effect=AssertionError("the library was opened")), \
            pytest.raises(pv.PreviewError, match="busy"):
        pv.add_to_front([_transcript("ja")], "ja")
    assert not os.path.exists(os.path.join(data_dir, "HighPriority"))


def test_the_add_waits_a_moment_for_a_busy_store_before_refusing():
    seen = []
    with patch.object(ls, "check_mode", side_effect=lambda lang, d, busy_wait: seen.append(busy_wait) or
                      ("json", "no store")), pytest.raises(pv.PreviewError):
        pv.add_to_front([], "ja")
    assert seen == [ls.BUSY_AT_OPEN]


def test_open_report_uses_the_app_window_only_when_asked():
    with patch("webbrowser.open") as browser, patch("app.static_html_generator.open_as_app") as app_window:
        pv.open_report("preview.html", app_mode=False)
        assert browser.call_count == 1 and app_window.call_count == 0
        pv.open_report("preview.html", app_mode=True)
        assert browser.call_count == 1 and app_window.call_count == 1


# ====================================================================================================================
# The fix round (2026-10-14): the scoring in a child, the fetch a job (AD4-2, IK-29, IK-31); a workspace per run (AD4-3)
# ====================================================================================================================
import subprocess  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

from app import path_utils  # noqa: E402
from app.services import jobs as jobs_module  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
RESOURCES = os.path.join(ROOT, "tests", "Test Resources")


def test_a_preview_never_touches_the_one_shared_workspace(monkeypatch):
    # AD4-3: each run makes its own folder; the old shared `surasura_preview` (another window's, the Tk preview's) is
    # never reset or removed by a 3.0 run.
    monkeypatch.setattr(pv, "reset_workspace", lambda: pytest.fail("the shared workspace was reset"))
    monkeypatch.setattr(pv, "cleanup_workspace", lambda: pytest.fail("the shared workspace was removed"))
    _cache("ja", "ja")
    first, second = Pipe("ja").run(VIDEO), Pipe("ja").run(VIDEO)
    assert first.workspace and second.workspace and first.workspace != second.workspace
    assert os.path.dirname(first.html) == first.workspace and os.path.isdir(second.workspace)


def test_a_run_that_made_no_workspace_names_none():
    _cache("ja", "ja")
    out = Pipe("ja").run("https://www.bilibili.com/bangumi/play/ep5137677")
    assert out.workspace is None


def test_a_failed_fetch_still_names_its_workspace_for_removal():
    _cache("ja", "ja")
    out = Pipe("ja", transcripts=0).run(VIDEO)
    assert out.error == pv.NO_TRANSCRIPT and out.workspace and os.path.isdir(out.workspace)


def test_the_lookups_yt_dlp_child_stops_with_the_window(monkeypatch):
    # The lookup stays on the window's worker; a close ends its yt-dlp child (`downloader.stopping`), never waited out.
    from modules.youtube_downloader import downloader as core
    seen = []
    _cache("ja", "ja")
    stop = (lambda: True)

    def probe(url, log):
        seen.append(core._stopping_now())
        return {"_type": "video", "id": "dQw4w9WgXcQ"}
    pv.run_preview(VIDEO, "ja", False, lambda n: None, lambda line: None, should_stop=stop, probe=probe)
    assert seen == [stop]


def test_removing_workspaces_takes_each_folder(tmp_path):
    folders = [tmp_path / "a", tmp_path / "b"]
    for f in folders:
        (f / "sub").mkdir(parents=True)
        (f / "sub" / "preview.html").write_text("<html></html>", encoding="utf-8")
    pv.remove_workspaces([str(f) for f in folders] + [str(tmp_path / "never-made")])
    assert not any(f.exists() for f in folders)


# --- the scoring child (child_main, preview_child.py, app_entry's youtube_preview) ---------------------------------- #
def _library_for_child(root, language):
    """A library list the child can score against, under the child's own test root."""
    results = os.path.join(root, "results")
    os.makedirs(results, exist_ok=True)
    with open(os.path.join(results, "library_frequency.json"), "w", encoding="utf-8") as f:
        json.dump({"settings": {"min_count": 1, "total_tokens": 1000, "language": language}, "words": {}}, f,
                  ensure_ascii=False)


@pytest.mark.parametrize("language, source", [("ja", "ja/runaway_transcript.txt"), ("zh", "zh/chinese_text_1.txt")])
def test_the_scoring_child_scores_a_real_transcript_and_answers_in_one_line(tmp_path, language, source):
    root = tmp_path / "child_root"
    root.mkdir()
    shutil_src = os.path.join(ROOT, "templates")
    import shutil
    shutil.copytree(shutil_src, str(root / "templates"))
    _library_for_child(str(root), language)
    src = os.path.join(RESOURCES, source)
    if os.path.isdir(src):
        src = next(os.path.join(src, n) for n in sorted(os.listdir(src)) if n.endswith(".txt"))
    out = str(tmp_path / "preview.html")
    env = path_utils.build_subprocess_env(False)
    env.update(SURASURA_TEST_ROOT=str(root), APPDATA=str(tmp_path / "appdata"),
               LOCALAPPDATA=str(tmp_path / "localappdata"))
    argv = pv.child_argv(language, out, [src], frozen=False)
    proc = subprocess.run([sys.executable] + argv, env=env, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=300)
    assert proc.returncode == 0, proc.stderr[-3000:]
    [answer] = [line for line in proc.stdout.splitlines() if line.startswith(pv.RESULT)]
    assert json.loads(answer[len(pv.RESULT):]) == {"html": out}
    with open(out, encoding="utf-8") as f:
        assert "let globalData = {" in f.read()


def test_the_scoring_child_says_a_preview_error_and_exits_cleanly(capsys, monkeypatch):
    monkeypatch.setattr(pv, "score_here", lambda *a: (_ for _ in ()).throw(pv.PreviewError("No library list.")))
    assert pv.child_main(["--language", "ja", "--out", "x.html", "a.txt"]) == 0
    assert capsys.readouterr().out.strip() == pv.RESULT + json.dumps({"error": "No library list."})


def test_the_scoring_childs_command_is_the_frozen_verb_or_the_script():
    assert pv.child_argv("zh", "o.html", ["a.txt"], frozen=True) == ["youtube_preview", "--language", "zh", "--out",
                                                                       "o.html", "a.txt"]
    assert pv.child_argv("ja", "o.html", ["a.txt"], frozen=False)[0] == pv.CHILD_SCRIPT
    assert os.path.isfile(pv.CHILD_SCRIPT)


# --- the window's runs (Runs): jobs, waited for off the window, ended by a cancel ----------------------------------- #
_FAKE_CHILD = r'''
import json, sys, time
mode, out = sys.argv[1], sys.argv[sys.argv.index("--out") + 1]
if mode == "hang":
    print("scoring", flush=True)
    time.sleep(60)
elif mode == "crash":
    sys.exit(3)
else:
    open(out, "w", encoding="utf-8").write("<html></html>")
    print("@result " + json.dumps({"html": out}), flush=True)
'''


@pytest.fixture
def fake_child(tmp_path, monkeypatch):
    script = tmp_path / "fake_scoring_child.py"
    script.write_text(_FAKE_CHILD, encoding="utf-8")
    box = {"mode": "ok"}
    monkeypatch.setattr(pv, "child_argv", lambda lang, out, transcripts, frozen=None: [str(script), box["mode"],
                                                                                        "--out", out] + transcripts)
    return box


def _registry():
    return jobs_module.JobRegistry()


def test_the_runs_fetch_is_a_youtube_job_off_the_asking_thread(tmp_path):
    registry, seen = _registry(), []

    def extract(urls, ws, lang, channel_first, log, should_stop=None):
        seen.append(threading.current_thread().name)
        with open(os.path.join(ws, f"{names('ja')[0]} [dQw4w9WgXcQ].txt"), "w", encoding="utf-8") as f:
            f.write(names("ja")[1])
    runs = pv.Runs(registry, "ja", VIDEO, "Previewing a video", extract=extract, ensure=lambda log: True)
    txts, problem = runs.fetch(VIDEO, str(tmp_path))
    assert problem is None and len(txts) == 1 and seen == ["youtube-preview-fetch"]
    [job] = [v for v in registry.snapshot() if v.kind == "youtube"]
    assert job.state == "done" and job.on_quit == "cancel" and job.label == "Previewing a video"


def test_cancelling_the_runs_fetch_ends_its_yt_dlp_child(tmp_path):
    registry, ended = _registry(), threading.Event()

    def extract(urls, ws, lang, channel_first, log, should_stop=None):
        from modules.youtube_downloader import downloader as core
        stop = core._stopping_now()
        while not stop():                                         # what ytdlp_manager.run asks every 0.2 s
            time.sleep(0.02)
        ended.set()
    runs = pv.Runs(registry, "ja", VIDEO, "Previewing a video", extract=extract, ensure=lambda log: True)
    threading.Timer(0.3, runs.cancel).start()
    assert runs.fetch(VIDEO, str(tmp_path)) == ([], None) and ended.wait(5)


def test_the_runs_scoring_is_a_child_job_and_its_answer_is_read(tmp_path, fake_child):
    registry = _registry()
    runs = pv.Runs(registry, "ja", VIDEO, "Previewing a video")
    out = str(tmp_path / "preview.html")
    assert runs.score([str(tmp_path / "a.txt")], out) == (out, None)
    [job] = [v for v in registry.snapshot() if v.kind == "youtube"]
    assert job.state == "done" and job.pid


def test_a_scoring_child_that_fails_says_so_with_its_log(tmp_path, fake_child):
    fake_child["mode"] = "crash"
    html, problem = pv.Runs(_registry(), "ja", VIDEO, "Previewing a video").score(["a.txt"], str(tmp_path / "p.html"))
    assert html is None and problem.startswith("Couldn't score the video")


def test_cancelling_the_runs_scoring_ends_the_child(tmp_path, fake_child):
    fake_child["mode"] = "hang"
    registry = _registry()
    runs = pv.Runs(registry, "ja", VIDEO, "Previewing a video")
    threading.Timer(1.0, runs.cancel).start()
    start = time.monotonic()
    assert runs.score(["a.txt"], str(tmp_path / "p.html")) == (None, None)
    assert time.monotonic() - start < 30
    [job] = [v for v in registry.snapshot() if v.kind == "youtube"]
    assert job.cancelled and job.state == "done"


def test_a_cancel_before_the_scoring_starts_runs_no_child(tmp_path, fake_child):
    registry = _registry()
    runs = pv.Runs(registry, "ja", VIDEO, "Previewing a video")
    runs.cancel()
    assert runs.score(["a.txt"], str(tmp_path / "p.html")) == (None, None)
    assert not os.path.exists(tmp_path / "p.html")
    assert registry.snapshot() == ()                                  # no job, so no child, was ever asked for


def test_the_packaged_app_dispatches_the_scoring_child_and_passes_its_answer_on(tmp_path):
    # A frozen build can start only its own subcommands: `youtube_preview` reaches child_main, which answers (no list
    # to score against here) in one line and exits 0 — never the window, never a dialog.
    root = tmp_path / "root"
    root.mkdir()
    env = path_utils.build_subprocess_env(False)
    env.update(SURASURA_TEST_ROOT=str(root), APPDATA=str(tmp_path / "appdata"),
               LOCALAPPDATA=str(tmp_path / "localappdata"))
    proc = subprocess.run([sys.executable, os.path.join(ROOT, "app_entry.py"), "youtube_preview", "--headless",
                           "--language", "ja", "--out", str(tmp_path / "p.html"), str(tmp_path / "a.txt")],
                          env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    assert proc.returncode == 0, proc.stderr[-3000:]
    [answer] = [line for line in proc.stdout.splitlines() if line.startswith(pv.RESULT)]
    assert "error" in json.loads(answer[len(pv.RESULT):])
