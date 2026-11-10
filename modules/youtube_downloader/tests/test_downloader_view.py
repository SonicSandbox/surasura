# SPDX-License-Identifier: GPL-3.0-or-later
"""The transcript downloader's rules, Qt-free (W3.4 row 4; `downloader_view.py`; `downloader.extract`'s stop).

What a wrong answer would cost: a file that was already in Processed handed on as "created" (W3.2 would route it into
the library twice), or a new one missed; a time estimate in the safety question that isn't the one the Tk window gave;
a closed window that keeps downloading for half an hour; bilibili.com fetched though it can't give subtitles; a run's
lines lost (the Tk window's Activity box is now *Open the log*). Each test names the Tk method it replaces. yt-dlp is
always faked; the folders are the suite's temp SURASURA_TEST_ROOT.
"""
import os

import pytest

from app.path_utils import get_data_path
from modules.youtube_downloader import downloader as core
from modules.youtube_downloader import downloader_view as view
from tests.test_library_store_support import names


# --- links and the caption language (gui.py `on_extract`, `_default_lang`) ---------------------------------------- #
def test_links_are_one_per_non_blank_line():
    text = "  https://youtu.be/dQw4w9WgXcQ  \r\n\n\thttps://www.bilibili.tv/en/play/1001/2002\n   \n"
    assert view.links(text) == ["https://youtu.be/dQw4w9WgXcQ", "https://www.bilibili.tv/en/play/1001/2002"]
    assert view.links("") == [] and view.links(None) == []


def test_the_caption_language_starts_on_the_windows_language():
    assert view.default_caption_language("ja") == "Japanese"
    assert view.default_caption_language("zh") == "Chinese"
    assert view.default_caption_language("ko") == core.DEFAULT_LANG


# --- the created-files diff (gui.py `_run_extract`; W3.2 L1 B2: at any depth) ------------------------------------ #
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_run_extract_hands_on_only_the_new_content_files_at_any_depth(language):
    """A new video written into a channel's folder an earlier download made is new though its folder isn't (B2: the
    top-level diff handed `[]` on, and the file stayed in Processed); what was there before, and sidecars, never."""
    words = names(language)
    out = view.processed_folder(language)
    assert out == os.path.join(get_data_path(language), "Processed")
    channel = os.path.join(out, words[4])
    os.makedirs(channel)
    for path in (os.path.join(out, f"{words[0]} [aaaaaaaaaaa].txt"),
                 os.path.join(channel, f"{words[5]} [ccccccccccc].txt")):
        with open(path, "w", encoding="utf-8") as f:
            f.write(words[0])
    seen = {}
    playlist = os.path.join(out, f"{words[2]} - {words[3]} (playlist)")

    def fake_extract(urls, folder, lang, keep_timestamps, channel_first, log, should_stop):
        seen.update(urls=urls, folder=folder, lang=lang, keep=keep_timestamps, channel=channel_first,
                    stop=should_stop)
        os.makedirs(playlist)
        for path in (os.path.join(folder, f"{words[1]} [bbbbbbbbbbb].txt"),
                     os.path.join(playlist, f"{words[6]} [ddddddddddd].srt"),
                     os.path.join(channel, f"{words[7]} [eeeeeeeeeee].txt")):
            with open(path, "w", encoding="utf-8") as f:
                f.write(words[1])
            with open(os.path.splitext(path)[0] + ".surasura.json", "w", encoding="utf-8") as f:
                f.write("{}")
        log("done")
    stop = (lambda: False)
    lines = []
    created = view.run_extract(["https://youtu.be/dQw4w9WgXcQ"], language, "Japanese", True, False, lines.append,
                               should_stop=stop, ensure=lambda log: True, extract=fake_extract)
    assert created == sorted([os.path.join(out, f"{words[1]} [bbbbbbbbbbb].txt"),
                              os.path.join(playlist, f"{words[6]} [ddddddddddd].srt"),
                              os.path.join(channel, f"{words[7]} [eeeeeeeeeee].txt")])
    assert seen == {"urls": ["https://youtu.be/dQw4w9WgXcQ"], "folder": out, "lang": "Japanese", "keep": True,
                    "channel": False, "stop": stop}
    assert lines == ["done"]


def test_run_extract_without_yt_dlp_downloads_nothing():
    lines = []
    created = view.run_extract(["https://youtu.be/dQw4w9WgXcQ"], "ja", "Japanese", False, True, lines.append,
                               ensure=lambda log: None, extract=lambda *a, **k: pytest.fail("downloaded"))
    assert created == [] and lines == ["Cannot proceed without yt-dlp."]


# --- the safety question's numbers (gui.py `on_backfill`) ---------------------------------------------------------- #
@pytest.mark.parametrize("n", [1, 7, 19, 20, 21, 140, 1000])
def test_the_backfill_estimate_is_the_tk_windows(n):
    tk = max(1, round((n * (core.REQUEST_PAUSE + 2.0) + (n // core.BATCH_SIZE) * core.BATCH_PAUSE) / 60))
    assert view.backfill_minutes(n) == tk


def test_run_backfill_walks_the_whole_language_folder_and_passes_the_stop():
    seen = {}
    stop = (lambda: True)
    view.run_backfill("zh", "Chinese", print, stop, ensure=lambda log: True,
                      backfill=lambda root, lang, log, should_stop: seen.update(root=root, lang=lang, stop=should_stop))
    assert seen == {"root": get_data_path("zh"), "lang": "Chinese", "stop": stop}


def test_pending_backfill_finds_a_transcript_in_a_section_folder_without_its_sidecar():
    words = names("ja")
    folder = os.path.join(get_data_path("ja"), "LowPriority", words[4])
    os.makedirs(folder)
    path = os.path.join(folder, f"{words[4]} [dQw4w9WgXcQ].txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(words[5])
    assert view.pending_backfill("ja") == [(path, "dQw4w9WgXcQ")]


def test_the_run_log_keeps_every_line_and_hands_each_on(tmp_path, monkeypatch):
    monkeypatch.setattr(view, "log_path", lambda kind=None: str(tmp_path / "logs" / "youtube-transcripts.log"))
    said = []
    log = view.RunLog(said.append)
    log("Looking up 1 item(s) — language: Japanese …")
    log("  [ok] (manual) 東京の夜 [dQw4w9WgXcQ].txt")
    log.close()
    assert said[1].endswith(".txt")
    assert (tmp_path / "logs" / "youtube-transcripts.log").read_text(encoding="utf-8").splitlines() == said


# --- the core's stop and refusal (downloader.extract) -------------------------------------------------------------- #
def test_bilibili_com_is_refused_before_anything_is_fetched(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "_probe", lambda *a: pytest.fail("looked up"))
    monkeypatch.setattr(core, "_run_ytdlp", lambda *a, **k: pytest.fail("fetched"))
    lines = []
    summary = core.extract(["https://www.bilibili.com/bangumi/play/ep5137677"], str(tmp_path), log=lines.append)
    assert summary["errors"] == 1 and "bilibili.tv" in lines[0]


def test_a_stop_ends_the_run_between_lookups_and_between_downloads(monkeypatch, tmp_path):
    probed, fetched = [], []
    monkeypatch.setattr(core, "_probe", lambda url, log: probed.append(url) or {"id": url[-11:], "channel": "x"})
    monkeypatch.setattr(core, "plan_buckets", lambda results, folder: [([u], folder) for u, _i in results])
    monkeypatch.setattr(core, "_run_ytdlp", lambda args, timeout=0, **_k: fetched.append(args[-1]))
    urls = [f"https://youtu.be/{c * 11}" for c in "abc"]
    lines = []
    # The window closes once the second lookup is done: the third is never made, nothing is fetched.
    core.extract(urls, str(tmp_path), log=lines.append, should_stop=lambda: len(probed) >= 2)
    assert probed == urls[:2] and fetched == [] and lines[-1] == "Stopped."
    probed.clear()
    # It closes once the first download is done: the other buckets are never fetched.
    core.extract(urls, str(tmp_path), log=lines.append, should_stop=lambda: len(fetched) >= 1)
    assert probed == urls and fetched == urls[:1] and lines[-1] == "Stopped."


def test_a_stop_ends_a_buckets_downloads_between_sites(monkeypatch, tmp_path):
    # One bucket holding a YouTube link and a bilibili.tv one is two yt-dlp calls: a close after the first skips the
    # second.
    fetched = []
    monkeypatch.setattr(core, "_run_ytdlp", lambda args, timeout=0, **_k: fetched.append(args[-1]))
    urls = ["https://youtu.be/aaaaaaaaaaa", "https://www.bilibili.tv/en/play/1001/2002"]
    core._download_bucket(urls, str(tmp_path / "bucket"), core.LANGS["Japanese"], "Japanese", False, True,
                          lambda *_: None, {"written": 0, "no_transcript": 0, "errors": 0},
                          should_stop=lambda: len(fetched) >= 1)
    assert fetched == urls[:1]


def test_without_a_stop_every_bucket_is_fetched(monkeypatch, tmp_path):
    fetched = []
    monkeypatch.setattr(core, "_probe", lambda url, log: {"id": url[-11:]})
    monkeypatch.setattr(core, "plan_buckets", lambda results, folder: [([u], folder) for u, _i in results])
    monkeypatch.setattr(core, "_run_ytdlp", lambda args, timeout=0, **_k: fetched.append(args[-1]))
    urls = [f"https://youtu.be/{c * 11}" for c in "ab"]
    core.extract(urls, str(tmp_path), log=lambda *_: None)
    assert fetched == urls


# --- the fix round: yt-dlp a run can stop (the intent keeper's IK-31; the adversary's AD4-9) ----------------------- #
# A playlist's one yt-dlp call can take half an hour: a cancelled job, a closed window or the app's quit must end the
# child itself, never wait for it (or leave it running, unseen, after the window went).
_SLEEPER = "import time; time.sleep(60)"


def _sleeper_alive_after(stop_after, run):
    """Runs `run(should_stop)` with a stop that turns true after `stop_after` s. -> (raised, seconds it took)."""
    import time
    start = time.monotonic()
    raised = None
    try:
        run(lambda: time.monotonic() - start > stop_after)
    except Exception as e:
        raised = e
    return raised, time.monotonic() - start


def test_a_stop_ends_a_running_yt_dlp_child():
    import sys
    from modules.youtube_downloader import ytdlp_manager
    started = []
    real_popen = ytdlp_manager.subprocess.Popen

    def popen(*a, **k):
        started.append(real_popen(*a, **k))
        return started[-1]
    from unittest.mock import patch
    with patch.object(ytdlp_manager.subprocess, "Popen", popen):
        raised, took = _sleeper_alive_after(
            0.3, lambda stop: ytdlp_manager.run([sys.executable, "-c", _SLEEPER], 120, should_stop=stop))
    assert isinstance(raised, ytdlp_manager.Stopped) and took < 10
    assert started and started[0].poll() is not None                # the child itself ended, not only waited out


def test_a_finished_yt_dlp_child_answers_as_subprocess_run_did():
    import sys
    from modules.youtube_downloader import ytdlp_manager
    res = ytdlp_manager.run([sys.executable, "-c", "import sys; sys.stdout.reconfigure(encoding='utf-8'); print('東京'); sys.stderr.write('warn')"], 60,
                            should_stop=lambda: False)
    assert res.returncode == 0 and res.stdout.strip() == "東京" and res.stderr == "warn"


def test_a_yt_dlp_child_past_its_time_is_ended():
    import subprocess
    import sys
    from modules.youtube_downloader import ytdlp_manager
    with pytest.raises(subprocess.TimeoutExpired):
        ytdlp_manager.run([sys.executable, "-c", _SLEEPER], 0.5)


def test_the_downloads_yt_dlp_calls_stop_with_the_run(monkeypatch):
    # core._run_ytdlp (every lookup, download and cue fetch) ends its child when the run that asked stops.
    import sys
    from modules.youtube_downloader import ytdlp_manager
    monkeypatch.setattr(ytdlp_manager, "get_ytdlp_path", lambda: sys.executable)

    def run(stop):
        with core.stopping(stop):
            core._run_ytdlp(["-c", _SLEEPER])
    raised, took = _sleeper_alive_after(0.3, run)
    assert isinstance(raised, ytdlp_manager.Stopped) and took < 10


def test_run_extract_backfill_and_update_hand_the_stop_to_yt_dlp(monkeypatch):
    from modules.youtube_downloader import ytdlp_manager
    seen = []
    stop = (lambda: False)

    def record(*_a, **_k):
        seen.append(core._stopping_now())
    view.run_extract(["https://youtu.be/dQw4w9WgXcQ"], "ja", "Japanese", False, True, print, should_stop=stop,
                     ensure=lambda log: True, extract=record)
    view.run_backfill("ja", "Japanese", print, stop, ensure=lambda log: True, backfill=record)
    monkeypatch.setattr(ytdlp_manager, "is_available", lambda: True)
    monkeypatch.setattr(ytdlp_manager, "run", lambda cmd, timeout, should_stop=None: seen.append(should_stop) or
                        type("R", (), {"stdout": "yt-dlp is up to date", "stderr": ""})())
    view.run_update(print, should_stop=stop)
    assert seen == [stop, stop, stop]
    assert core._stopping_now() is None                              # set only for the run that asked


def test_the_run_log_is_opened_on_the_runs_thread_not_when_made(tmp_path, monkeypatch):
    # AD4-5: the window makes the log for a run; opening (and truncating) the file is the run's first write.
    path = tmp_path / "logs" / "youtube-download.log"
    monkeypatch.setattr(view, "log_path", lambda kind=None: str(path))
    log = view.RunLog(lambda line: None)
    assert not path.exists()
    log("[ok] (manual) 東京の夜")
    log.close()
    assert path.read_text(encoding="utf-8") == "[ok] (manual) 東京の夜\n"


def test_each_action_keeps_its_own_log():
    # AD4-14: an Update no longer overwrites the last download's log.
    paths = {view.log_path(kind) for kind in ("download", "fill", "update")}
    assert len(paths) == 3 and all(p.endswith(".log") for p in paths)
