# SPDX-License-Identifier: GPL-3.0-or-later
"""The YouTube module's Qt windows (W3.4 row 4; `qt_window.py`: the transcript downloader; `qt_preview.py`: the
preview against the library; the RUNBOOK's row 4, IK-2, IK-5, IK-15).

What a wrong answer would cost: the risk acknowledgment written on open, by anything but the user's own tick, or
reverted; Download before it is acknowledged; a file that was already in Processed handed to the library as new, or the
new ones silently dropped; a long network run (the timestamp fill) started without asking with its count and time; a
closed window that keeps downloading; the preview hidden because the add was refused; a playlist question that, once
its window closed, leaves the run waiting forever; the preview's workspace left in %TEMP% after Esc (inv defect 4).

On the harness's terms (offscreen, one QApplication — the window tests' own `tests/qt/conftest.py` fixtures, imported
here — the suite's temp SURASURA_TEST_ROOT, the network guard); yt-dlp is always faked.
"""
import json
import os
import subprocess
import sys
import threading
import time

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QCheckBox  # noqa: E402

from tests.qt.conftest import _per_test_window_state, qapp, wait_until  # noqa: E402,F401  (the window harness)
from tests.qt.test_wiring import problems  # noqa: E402
from app.qt import strings, windows  # noqa: E402
from tests.test_library_store_support import names  # noqa: E402

import modules.youtube_downloader as yt  # noqa: E402
from app.path_utils import get_data_path  # noqa: E402
from modules.youtube_downloader import downloader as core  # noqa: E402
from modules.youtube_downloader import downloader_view as view  # noqa: E402
from modules.youtube_downloader import preview as pv  # noqa: E402
from modules.youtube_downloader import qt_preview, qt_window, ytdlp_manager  # noqa: E402
from modules.youtube_downloader import qt_strings as S  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
VIDEO = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.fixture
def main(qapp, monkeypatch):
    """The real main window on the test's own root: no indexer, Anki sync, update check or browser."""
    for name in ("SURASURA_NO_AUTOINDEX", "SURASURA_NO_ANKI_SYNC", "SURASURA_NO_UPDATE_CHECK", "SURASURA_NO_UI_TIMERS"):
        monkeypatch.setenv(name, "1")
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: pytest.fail("a browser opened"))
    from app.qt import shell
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.show()
    sets = []
    real = services.settings.set
    monkeypatch.setattr(services.settings, "set", lambda changes, **kw: sets.append(dict(changes)) or
                        real(changes, **kw))
    win.sets = sets
    yield win
    win.close()
    services.shutdown(0.5)


@pytest.fixture
def opened(monkeypatch):
    from app.qt import press as qpress
    from app.qt import windows
    calls = []
    monkeypatch.setattr(windows, "open_url", calls.append)
    monkeypatch.setattr(qpress, "open_now", calls.append)      # round 8 row 45: a press opens it, on a worker
    return calls


def _confirm(window):
    from app.qt import confirm
    cards = [c for c in window.findChildren(confirm.Confirm) if c.answer is None]
    return cards[-1] if cards else None


def _esc():
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Escape)
    QApplication.processEvents()


# ====================================================================================================================
# The downloader
# ====================================================================================================================
def _downloader(main, on_complete=None, ack=False):
    if ack:
        main.services.settings.set({"youtube_risk_acknowledged": True})
        main.sets.clear()
    return qt_window.open(main, on_complete=on_complete)


@pytest.fixture
def fake_ytdlp(monkeypatch):
    """yt-dlp ready, and a download that writes one new transcript per link into the folder it is given."""
    monkeypatch.setattr(ytdlp_manager, "ensure_available", lambda log: "yt-dlp.exe")
    calls = []

    def extract(urls, folder, lang, keep_timestamps, channel_first, log, should_stop=None):
        calls.append(dict(urls=urls, folder=folder, lang=lang, keep=keep_timestamps, channel=channel_first,
                          on_gui=threading.current_thread() is threading.main_thread()))
        for i, _u in enumerate(urls):
            with open(os.path.join(folder, f"{names('ja')[i]} [dQw4w9WgXc{i}].txt"), "w", encoding="utf-8") as f:
                f.write(names("ja")[i + 1])
            log(f"  [ok] (manual) {names('ja')[i]}")
    monkeypatch.setattr(core, "extract", extract)
    return calls


def test_the_downloader_is_wired_tipped_and_named(main):
    w = _downloader(main)
    found, walked = problems(w)
    # try a9.1: the risk tick, ⋯ and Download on the window; ⋯'s five items (Fill, Update, Open folder, Open the log,
    # the risk tick), its two separators and its own menu action
    assert walked == 11 and found == []
    assert w.windowTitle() == "Video Transcripts — Surasura" and w.parentWidget() is main


def test_the_window_is_condensed_one_way_in_one_action_and_the_rest_folded_into_more(main):
    """Try a9.1 (Sonic: "as few buttons / most visual and condensed yet balanced as possible"): on the window, the
    links, the captions, ⋯ and Download — the one action; what were four buttons are ⋯'s items, every one tipped;
    what the window does sits behind its ? (a hover). Nothing it did is gone."""
    w = _downloader(main, ack=True)
    from PyQt6.QtWidgets import QPushButton
    assert [b.text() for b in w.findChildren(QPushButton)] == [S.MORE, S.DOWNLOAD]
    items = [a for a in w.more_menu.actions() if not a.isSeparator()]
    assert [a.text() for a in items] == [S.BACKFILL, S.UPDATE, S.OPEN_FOLDER, S.OPEN_LOG, S.RISK]
    assert all(a.toolTip() and a.toolTip() != a.text() for a in items)
    assert w.help.toolTip() == S.HELP_TIP and w.help.accessibleName() == S.HELP_NAME
    assert w.more.toolTip() == S.MORE_TIP and w.more.accessibleName() == S.MORE_NAME


def test_the_risk_tick_is_on_the_window_until_given_then_in_more_where_it_can_be_taken_back(main):
    """The one-time acknowledgment: shown on the window until it is given; once given, the window opens without it
    and ⋯ holds it ticked — unticked there, it is written and back on the window, and Download is off again."""
    w = _downloader(main)
    assert w.risk.isVisibleTo(w) and not w.risk_item.isChecked() and not w.download.isEnabled()
    w.risk.click()
    assert main.sets == [{"youtube_risk_acknowledged": True}] and w.risk_item.isChecked()
    assert w.risk.isVisibleTo(w), "ticked just now: it stays where the learner ticked it"
    w.close()
    QApplication.processEvents()
    w = _downloader(main)
    assert not w.risk.isVisibleTo(w) and w.risk_item.isChecked() and w.download.isEnabled()
    main.sets.clear()
    w.risk_item.trigger()                                            # taken back in ⋯
    assert main.sets == [{"youtube_risk_acknowledged": False}]
    assert w.risk.isVisibleTo(w) and not w.risk.isChecked() and not w.download.isEnabled()


def test_a_run_shows_as_a_bar_its_count_and_each_transcript_by_its_name(main, monkeypatch):
    """A run is shown, not written out: the bar turns until the run counts its videos, then fills (`… 2 of 5 videos
    read`), the line says `2 of 5 videos`, a written transcript shows as ✓ its name (the whole line in the log); idle,
    no bar. Wrong, a long playlist would look hung, or the line would read as yt-dlp's raw output."""
    monkeypatch.setattr(ytdlp_manager, "ensure_available", lambda log: "yt-dlp.exe")
    gate, stage = threading.Event(), {"n": 0}
    title = names("ja")[3]

    def extract(urls, folder, lang, keep_timestamps, channel_first, log, should_stop=None):
        log("  … 2 of 5 videos read")
        stage["n"] = 1
        gate.wait(5)
        gate.clear()
        log(f"  [ok] (manual) Tsubasa no Kitchen - {title} [dQw4w9WgXcQ].txt")
        stage["n"] = 2
        gate.wait(5)
    monkeypatch.setattr(core, "extract", extract)
    w = _downloader(main, ack=True)
    assert not w.progress.isVisibleTo(w)
    w.links.setPlainText(VIDEO)
    w.download.click()
    assert w.progress.isVisibleTo(w)
    assert wait_until(lambda: w.status.text() == S.COUNTED.format(done=2, total=5))
    assert (w.progress.minimum(), w.progress.maximum(), w.progress.value()) == (0, 5, 2)
    gate.set()
    assert wait_until(lambda: w.status.text() == S.WROTE.format(name=f"Tsubasa no Kitchen - {title}"))
    gate.set()
    assert wait_until(lambda: w.running is None) and not w.progress.isVisibleTo(w)


def test_the_inventorys_controls_are_all_here(main):
    # inv §1.1: links, language, Channel name first, the risk tick, Download (was Extract), the state (now the status
    # line), 📂 / ⏱ / ⟳ (now named), and the Activity box (now the status line + Open the log). Alpha 8 (Sonic): no
    # *Keep timestamps* — the times always go beside the text (its cue sidecar), never into it. Try a9.1 (Sonic: "we
    # don't need the channel first anymore"): no *Channel name first* — the channel always leads (the run's True).
    w = _downloader(main)
    assert w.links.placeholderText() == S.LINKS_HINT
    assert [w.caption.itemData(i) for i in range(w.caption.count())] == list(core.LANGS)
    assert w.caption.currentData() == "Japanese"
    assert not hasattr(w, "keep_timestamps") and not hasattr(w, "channel_first") and not w.risk.isChecked()
    assert [b.text() for b in w.findChildren(QCheckBox)] == [S.RISK], "the risk tick is the window's one checkbox"
    assert [b.text() for b in (w.download, w.backfill, w.update_button, w.open_folder, w.open_log)] == \
        [S.DOWNLOAD, S.BACKFILL, S.UPDATE, S.OPEN_FOLDER, S.OPEN_LOG]
    assert "Terms of Service" in w.risk.toolTip()


def test_opening_writes_nothing_and_download_waits_for_the_acknowledgment(main):
    from app import path_utils
    before = os.path.exists(path_utils.get_settings_path())
    w = _downloader(main)
    QApplication.processEvents()
    assert main.sets == [] and not main.services.settings.pending()
    assert os.path.exists(path_utils.get_settings_path()) == before
    assert not w.download.isEnabled()


def test_the_acknowledgment_is_saved_alone_by_the_users_tick_and_kept(main):
    w = _downloader(main)
    w.risk.click()
    assert main.sets == [{"youtube_risk_acknowledged": True}] and w.download.isEnabled()
    main.services.settings.flush(5)
    from app import path_utils
    with open(path_utils.get_settings_path(), encoding="utf-8") as f:
        assert json.load(f) == {"youtube_risk_acknowledged": True}
    w.close()
    QApplication.processEvents()
    w2 = _downloader(main)
    assert w2.risk.isChecked() and w2.download.isEnabled() and main.sets == [{"youtube_risk_acknowledged": True}]
    w2.risk.click()                                                  # the user's own untick is theirs to save
    assert main.sets[-1] == {"youtube_risk_acknowledged": False} and not w2.download.isEnabled()


def test_the_download_itself_refuses_without_the_acknowledgment(main, fake_ytdlp):
    # The button is off until the tick; the run's own guard holds too (a keyboard shortcut or a later caller).
    w = _downloader(main)
    w.links.setPlainText(VIDEO)
    w._download()
    QApplication.processEvents()
    assert w.running is None and fake_ytdlp == [] and w.status.text() == ""


def test_no_links_says_so_and_downloads_nothing(main, fake_ytdlp):
    w = _downloader(main, ack=True)
    w.links.setPlainText("   \n")
    w.download.click()
    assert w.status.text() == S.NO_LINKS and fake_ytdlp == []


def test_a_download_hands_on_only_the_new_files_to_on_complete(main, fake_ytdlp):
    processed = view.processed_folder("ja")
    old = os.path.join(processed, f"{names('ja')[5]} [aaaaaaaaaaa].txt")
    with open(old, "w", encoding="utf-8") as f:
        f.write(names("ja")[6])
    handed = []
    w = _downloader(main, on_complete=handed.append, ack=True)
    w.links.setPlainText(f"{VIDEO}\nhttps://youtu.be/9bZkp7q19f0\n")
    w.caption.setCurrentIndex(w.caption.findData("English"))
    w.download.click()
    assert w.status.text() == S.DOWNLOADING and not w.download.isEnabled() and not w.backfill.isEnabled()
    assert wait_until(lambda: w.running is None)
    assert handed == [sorted(os.path.join(processed, f"{names('ja')[i]} [dQw4w9WgXc{i}].txt") for i in (0, 1))]
    assert w.status.text() == S.NEW_ROUTED.format(what=S.transcripts_handed(2)) and w.download.isEnabled()
    assert fake_ytdlp == [dict(urls=[VIDEO, "https://youtu.be/9bZkp7q19f0"], folder=processed, lang="English",
                               keep=False, channel=True, on_gui=False)]
    assert main.sets == []                                           # a download writes no setting


def test_without_on_complete_the_files_stay_in_processed_and_the_line_says_so(main, fake_ytdlp):
    w = _downloader(main, ack=True)
    w.links.setPlainText(VIDEO)
    w.download.click()
    assert wait_until(lambda: w.running is None)
    assert w.status.text() == S.NEW_IN_PROCESSED.format(what=S.new_transcripts(1))


def test_the_run_is_in_the_log_the_window_opens(main, fake_ytdlp, opened):
    w = _downloader(main, ack=True)
    w.links.setPlainText(VIDEO)
    w.download.click()
    assert wait_until(lambda: w.running is None)
    w.open_log.trigger()
    assert wait_until(lambda: opened)
    assert opened == [view.log_path("download")]
    with open(view.log_path(), encoding="utf-8") as f:
        assert f"[ok] (manual) {names('ja')[0]}" in f.read()


def test_x_mid_download_tucks_it_into_its_icon_and_the_icons_stop_ends_the_run_between_videos(main, monkeypatch):
    """Try a9.1 (Sonic: "if they X out of the youtube while it's going, shouldn't it either minimize or warn them? And
    if minimize they can right click on it for an option to stop it"): X mid-download puts the window into its icon and
    the run goes on — the bar says how to stop it, the first time only; the icon's right-click offers Show · Stop ·
    Close, and Stop ends the run between videos with the window still open. Wrong, X would throw a long download away
    unasked, or leave a run going with no way to stop it."""
    monkeypatch.setattr(ytdlp_manager, "ensure_available", lambda log: "yt-dlp.exe")
    seen = {"stops": [], "finished": threading.Event()}

    def extract(urls, folder, lang, keep_timestamps, channel_first, log, should_stop=None):
        for _ in range(500):                                         # "between videos": it asks each time
            seen["stops"].append(should_stop())
            if should_stop():
                break
            time.sleep(0.01)
        seen["finished"].set()
    monkeypatch.setattr(core, "extract", extract)
    handed = []
    w = _downloader(main, on_complete=handed.append, ack=True)
    w.links.setPlainText(VIDEO)
    w.download.click()
    assert wait_until(lambda: len(seen["stops"]) >= 2)
    w.close()                                                        # X: into its icon, the run going on
    QApplication.processEvents()
    assert not w.gone and w.tucked() and w.running == "download" and not seen["finished"].is_set()
    assert main.bar_line.full() == S.KEPT_DOWNLOADING
    icon = main.tool_icons.icons[id(w)]
    assert strings.TOOL_MENU_TIP in icon.toolTip()
    menu = icon.menu()
    assert [a.text() for a in menu.actions()] == ["Show", "Stop", "Close"] and all(a.toolTip() for a in menu.actions())
    main.bar_line.set_full("")
    windows.bring_back(w)
    w.close()                                                        # a second X: tucked again, said no more
    QApplication.processEvents()
    assert w.tucked() and main.bar_line.full() == "" and not seen["finished"].is_set()
    next(a for a in icon.menu().actions() if a.text() == "Stop").trigger()
    assert seen["finished"].wait(5) and seen["stops"][-1] is True and handed == []
    assert wait_until(lambda: w.running is None) and not w.gone and w.status.text() == S.STOPPED
    assert [a.text() for a in icon.menu().actions()] == ["Show", "Close"], "nothing running: no Stop"
    w.close()                                                        # idle: X closes
    assert w.gone


def test_the_icons_close_mid_download_closes_the_window_and_stops_the_run(main, held_extract):
    w = _start_download(main)
    assert wait_until(lambda: held_extract["calls"])
    w.close()
    QApplication.processEvents()
    next(a for a in main.tool_icons.icons[id(w)].menu().actions() if a.text() == "Close").trigger()
    assert w.gone and wait_until(lambda: held_extract["stops"] == [True])

def test_fill_missing_timestamps_asks_first_with_the_count_and_the_time(main, monkeypatch):
    words = names("ja")
    folder = os.path.join(get_data_path("ja"), "GoalContent", words[2])
    os.makedirs(folder)
    for i in range(3):
        with open(os.path.join(folder, f"{words[i]} [dQw4w9WgXc{i}].txt"), "w", encoding="utf-8") as f:
            f.write(words[i + 4])
    monkeypatch.setattr(ytdlp_manager, "ensure_available", lambda log: "yt-dlp.exe")
    runs = []
    monkeypatch.setattr(core, "backfill_cues", lambda root, lang, log, should_stop: runs.append(
        (root, lang, should_stop())))
    w = _downloader(main)
    w.backfill.trigger()                                               # no risk tick needed: nothing new is downloaded
    assert wait_until(lambda: _confirm(w) is not None)
    card = _confirm(w)
    assert "3 transcripts have" in card.body.text() and S.minutes(view.backfill_minutes(3)) in card.body.text()
    assert card.yes.text() == "Fetch 3 cue times" and "(s)" not in card.body.text()
    _esc()
    QApplication.processEvents()
    assert runs == [] and w.running is None
    w.backfill.trigger()
    assert wait_until(lambda: _confirm(w) is not None)
    _confirm(w).yes.click()
    assert wait_until(lambda: runs and w.running is None)
    assert runs == [(get_data_path("ja"), "Japanese", False)] and w.status.text() == S.FINISHED


def test_nothing_to_fill_asks_nothing(main):
    w = _downloader(main)
    w.backfill.trigger()
    assert wait_until(lambda: w.status.text() == S.NOTHING_TO_FILL) and _confirm(w) is None


def test_update_yt_dlp_runs_off_the_window(main, monkeypatch):
    ran = []
    monkeypatch.setattr(ytdlp_manager, "update", lambda log, should_stop=None: ran.append(threading.current_thread() is
                                                                        threading.main_thread()) or log("Updated."))
    w = _downloader(main)
    w.update_button.trigger()
    assert wait_until(lambda: w.running is None and ran)
    assert ran == [False] and w.status.text() == S.FINISHED


def test_open_the_processed_folder(main, opened):
    w = _downloader(main)
    w.open_folder.trigger()
    assert wait_until(lambda: opened)
    assert opened == [os.path.join(get_data_path("ja"), "Processed")]


def test_an_idle_downloader_follows_the_main_windows_language(main):
    w = _downloader(main)
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: w.language == "zh")
    assert w.caption.currentData() == "Chinese"


def test_the_modules_opener_opens_the_qt_window_and_keeps_one(main):
    handed = []
    w = yt.open_downloader(main, on_complete=handed.append)
    assert isinstance(w, qt_window.DownloaderWindow) and yt.open_downloader(main) is w
    assert w.on_complete == handed.append


# ====================================================================================================================
# The preview
# ====================================================================================================================
@pytest.fixture
def run_preview(monkeypatch):
    """`preview.run_preview` replaced: records each call, answers from `outcome` (a function of the call)."""
    calls = []
    box = {"outcome": lambda call: pv.Outcome(html="preview.html")}

    def fake(url, lang, add_front, ask_playlist, status, should_stop=None, **_kw):
        call = dict(url=url, lang=lang, add=add_front, ask=ask_playlist, status=status, stop=should_stop)
        calls.append(call)
        status(pv.LOOKING_UP)
        return box["outcome"](call)
    monkeypatch.setattr(pv, "run_preview", fake)
    reports = []
    monkeypatch.setattr(pv, "open_report", lambda path, app_mode=False: reports.append((path, app_mode)))
    cleaned = []
    monkeypatch.setattr(pv, "cleanup_workspace", lambda: cleaned.append(True))
    return calls, box, reports, cleaned


def _preview(main):
    return qt_preview.open(main)


def test_the_preview_is_wired_tipped_and_named(main):
    w = _preview(main)
    found, walked = problems(w)
    assert walked == 2 and found == []                               # the add toggle and Preview
    assert w.windowTitle() == "Preview Against Library — Surasura"
    assert not w.add_front.isChecked() and "Current" in w.add_front.text()


def test_enter_in_the_link_starts_a_preview_and_it_opens(main, run_preview):
    calls, _box, reports, _c = run_preview
    w = _preview(main)
    w.link.setText(f"  {VIDEO} ")
    QTest.keyClick(w.link, Qt.Key.Key_Return)
    assert wait_until(lambda: not w.running and reports)
    assert calls[0]["url"] == VIDEO and calls[0]["lang"] == "ja" and calls[0]["add"] is False
    assert reports == [("preview.html", False)] and w.status.text() == S.PREVIEW_OPENED
    assert main.sets == []                                           # the add choice is never saved


def test_a_refused_add_still_opens_the_preview_and_says_why(main, run_preview):
    calls, box, reports, _c = run_preview
    box["outcome"] = lambda call: pv.Outcome(html="preview.html", note=pv.STORE_BUSY)
    w = _preview(main)
    w.add_front.click()
    w.link.setText(VIDEO)
    w.go.click()
    assert wait_until(lambda: not w.running and reports)
    assert calls[0]["add"] is True and w.status.text() == S.PREVIEW_NOT_ADDED.format(why=pv.STORE_BUSY)


def test_an_added_transcript_is_named_in_the_line(main, run_preview):
    _calls, box, reports, _c = run_preview
    box["outcome"] = lambda call: pv.Outcome(html="preview.html", added=("a.txt",))
    w = _preview(main)
    w.add_front.click()
    w.link.setText(VIDEO)
    w.go.click()
    assert wait_until(lambda: not w.running and reports)
    assert w.status.text() == S.PREVIEW_ADDED.format(what=S.files(1))


def test_an_error_opens_nothing_and_says_it(main, run_preview):
    _calls, box, reports, _c = run_preview
    box["outcome"] = lambda call: pv.Outcome(error=pv.ALREADY_IN_LIBRARY)
    w = _preview(main)
    w.link.setText(VIDEO)
    w.go.click()
    assert wait_until(lambda: not w.running)
    assert reports == [] and w.status.text() == pv.ALREADY_IN_LIBRARY


def _asking(box, answers):
    def outcome(call):
        answers.append(call["ask"](4))
        return pv.Outcome(html="preview.html") if answers[-1] is not None else pv.Outcome()
    box["outcome"] = outcome


def test_the_playlist_question_esc_is_just_this_video(main, run_preview):
    _calls, box, reports, _c = run_preview
    answers = []
    _asking(box, answers)
    w = _preview(main)
    w.link.setText(VIDEO + "&list=PLabcdefghijk")
    w.go.click()
    assert wait_until(lambda: _confirm(w) is not None)
    card = _confirm(w)
    assert "4 videos" in card.body.text() and card.yes.text() == S.PLAYLIST_FULL and card.no.text() == S.PLAYLIST_ONE
    _esc()
    assert wait_until(lambda: not w.running)
    assert answers == [False] and reports


def test_the_playlist_question_full_playlist(main, run_preview):
    _calls, box, _reports, _c = run_preview
    answers = []
    _asking(box, answers)
    w = _preview(main)
    w.link.setText(VIDEO + "&list=PLabcdefghijk")
    w.go.click()
    assert wait_until(lambda: _confirm(w) is not None)
    _confirm(w).yes.click()
    assert wait_until(lambda: not w.running) and answers == [True]


def test_closing_with_the_question_open_ends_the_run_and_cleans_the_workspace(main, run_preview):
    calls, box, reports, cleaned = run_preview
    answers = []
    _asking(box, answers)
    w = _preview(main)
    w.link.setText(VIDEO + "&list=PLabcdefghijk")
    w.go.click()
    assert wait_until(lambda: _confirm(w) is not None)
    w.close()
    assert wait_until(lambda: answers == [None])
    assert reports == [] and calls[0]["stop"]() is True


def test_a_preview_finishing_after_its_window_closed_never_opens(main, run_preview, tmp_path):
    calls, box, reports, _c = run_preview
    release = threading.Event()
    workspace = tmp_path / "ws_late"
    workspace.mkdir()

    def late(call):
        release.wait(5)
        return pv.Outcome(html=str(workspace / "preview.html"), workspace=str(workspace))
    box["outcome"] = late
    w = _preview(main)
    w.link.setText(VIDEO)
    w.go.click()
    assert wait_until(lambda: calls)
    w.close()
    release.set()
    assert wait_until(lambda: not workspace.exists())                # its own run removed it (AD4-3)
    assert reports == []


def test_esc_cleans_the_workspace(main, run_preview, tmp_path):
    _calls, box, reports, _c = run_preview
    workspace = tmp_path / "ws_esc"
    workspace.mkdir()
    box["outcome"] = lambda call: pv.Outcome(html=str(workspace / "preview.html"), workspace=str(workspace))
    w = _preview(main)
    w.link.setText(VIDEO)
    w.go.click()
    assert wait_until(lambda: not w.running and reports) and workspace.exists()
    QTest.keyClick(w, Qt.Key.Key_Escape)
    assert w.gone and wait_until(lambda: not workspace.exists())


def test_no_list_asks_for_a_generate_and_previews_when_it_lands(main, run_preview, monkeypatch):
    from app.services import generate as G
    calls, box, reports, _c = run_preview
    box["outcome"] = lambda call: (pv.Outcome(error=pv.NO_CACHE, generate=True) if len(calls) == 1
                                   else pv.Outcome(html="preview.html"))
    generated = []
    monkeypatch.setattr(main.services, "generate", lambda: generated.append(True))
    w = _preview(main)
    w.add_front.click()
    w.link.setText(VIDEO)
    w.go.click()
    assert wait_until(lambda: _confirm(w) is not None)
    assert _confirm(w).body.text() == pv.NO_CACHE
    _confirm(w).yes.click()
    assert wait_until(lambda: generated) and w.status.text() == S.GENERATING
    state = G.State(G.CURRENT, None, None, None, None, None, None, 1)
    main.bridge.generate_changed.emit(state)                         # "current" before it ran: not this Generate's
    QApplication.processEvents()
    assert len(calls) == 1
    main.bridge.generate_changed.emit(state._replace(state=G.RUNNING, seq=2))
    main.bridge.generate_changed.emit(state._replace(seq=3))
    assert wait_until(lambda: len(calls) == 2 and reports)
    assert calls[1]["url"] == VIDEO and calls[1]["add"] is True


def test_no_list_and_no_thanks_starts_nothing(main, run_preview, monkeypatch):
    calls, box, _reports, _c = run_preview
    box["outcome"] = lambda call: pv.Outcome(error=pv.OTHER_LANGUAGE, generate=True)
    monkeypatch.setattr(main.services, "generate", lambda: pytest.fail("generated"))
    w = _preview(main)
    w.link.setText(VIDEO)
    w.go.click()
    assert wait_until(lambda: _confirm(w) is not None)
    _esc()
    assert w.status.text() == pv.OTHER_LANGUAGE and len(calls) == 1


def test_the_modules_opener_opens_the_qt_preview(main):
    w = yt.open_preview(main)
    assert isinstance(w, qt_preview.PreviewWindow) and yt.open_preview(main) is w


# --- no Tk ---------------------------------------------------------------------------------------------------------- #
def test_both_windows_open_without_tkinter(tmp_path):
    script = (
        "import json, sys\n"
        "from PyQt6.QtWidgets import QApplication\n"
        "from app.qt import shell\n"
        "app = QApplication(['yt-no-tk'])\n"
        "services = shell.Services(); win = shell.open_window(app, services); win.show()\n"
        "import modules.youtube_downloader as yt, modules.youtube_downloader.preview\n"
        "a = yt.open_downloader(win); b = yt.open_preview(win); app.processEvents()\n"
        "print(json.dumps([type(a).__name__, type(b).__name__, sorted(m for m in sys.modules if 'tkinter' in m),\n"
        "                  'app.analyzer' in sys.modules]))\n"
        "a.close(); b.close(); win.close(); services.shutdown(0.5)\n"
        "shell.quiet_exit(workers_ms=5000, gone=(win,))\n")   # the app's own quit: the windows deleted and no pool
    #                                     worker left before Python's teardown (closed but left to it, the main window
    #                                     crashed the exit, 0xC0000005: junban's twin, 07fbcea; flakes-2026-11-05 #6)
    env = dict(os.environ, PYTHONPATH=ROOT, SURASURA_TEST_ROOT=str(tmp_path), QT_QPA_PLATFORM="offscreen",
               SURASURA_FREEZE_MOTION="1", SURASURA_NO_AUTOINDEX="1", SURASURA_NO_UPDATE_CHECK="1",
               SURASURA_NO_ANKI_SYNC="1", SURASURA_INSTANCE_NAME=f"yt-no-tk-{os.getpid()}",
               APPDATA=str(tmp_path / "appdata"), LOCALAPPDATA=str(tmp_path / "localappdata"))
    proc = subprocess.run([sys.executable, "-c", script], cwd=str(tmp_path), env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=180)
    assert proc.returncode == 0, proc.stderr[-3000:]
    a, b, tk, analyzer = json.loads(proc.stdout.strip().splitlines()[-1])
    assert (a, b, tk) == ("DownloaderWindow", "PreviewWindow", [])
    assert analyzer is False                      # the preview's pipeline never loads the analyzer here (AD4-2)


# ====================================================================================================================
# The fix round (2026-10-14): downloads are jobs (IK-31, AD4-9), the log on the run's thread (AD4-5), the lines
# (IK-32, AD4-14, AD4-15)
# ====================================================================================================================
@pytest.fixture
def held_extract(monkeypatch):
    """yt-dlp ready, and a download that holds until released — `obeys`: whether it ends at the run's stop (a
    playlist's one yt-dlp call before the fix round could not be cut)."""
    monkeypatch.setattr(ytdlp_manager, "ensure_available", lambda log: "yt-dlp.exe")
    box = {"release": threading.Event(), "obeys": True, "calls": [], "stops": []}

    def extract(urls, folder, lang, keep_timestamps, channel_first, log, should_stop=None):
        box["calls"].append(urls)
        n = len(box["calls"])
        log(f"  [ok] (manual) {names('ja')[0]}")
        while not box["release"].wait(0.02):
            if box["obeys"] and should_stop():
                box["stops"].append(True)
                return
        with open(os.path.join(folder, f"{names('ja')[n]} [dQw4w9WgXc{n}].txt"), "w", encoding="utf-8") as f:
            f.write(names("ja")[9])
    monkeypatch.setattr(core, "extract", extract)
    yield box
    box["release"].set()


def _youtube_jobs(main):
    return [v for v in main.services.registry.live("youtube")]


def _job(main, state=None):
    return next(j for j in main.services.registry._jobs if j.kind == "youtube" and (state is None or j.state == state))


def _start_download(main, on_complete=None):
    w = _downloader(main, on_complete=on_complete, ack=True)
    w.links.setPlainText(VIDEO)
    w.download.click()
    return w


# --- Mado-Y2 (Sonic 2026-11-02): the video it downloads, beside the bar — only with *Download covers* on ----------- #
class _Thumbs:
    """The covers' fetcher as the window asks it (`video_cover`): a real PNG written into the covers cache, or
    `answer` (None: off, offline, failed). Records each ask and whether it came on the window's thread."""

    def __init__(self, answer="png", language="ja"):
        self.answer = answer
        self.language = language
        self.asked = []

    def video_cover(self, video_id):
        from app import path_utils
        from tests.test_services_covers import png
        self.asked.append((video_id, threading.current_thread() is threading.main_thread()))
        answer = self.answer(video_id) if callable(self.answer) else self.answer
        if answer != "png":
            if isinstance(answer, Exception):
                raise answer
            return answer
        name = f"youtube-test-{video_id}.png"
        with open(os.path.join(path_utils.get_covers_cache_path(), name), "wb") as f:
            f.write(png(48, 36))
        return "cache:" + name


@pytest.fixture
def thumbs(main, monkeypatch):
    fake = _Thumbs()
    monkeypatch.setattr(main, "cover_fetcher", lambda: fake)
    return fake


def _covers(main, on):
    main.services.settings.set({"covers_download": on})
    main.sets.clear()


def test_with_download_covers_on_the_video_shows_beside_the_bar_fetched_off_the_window(main, held_extract, thumbs):
    """Covers on: the link's video's thumbnail shows beside the bar while it downloads — asked of the covers' fetcher on
    a worker, never the window's thread —, a 16:9 picture as tall as four lines; the run ended, it goes with the bar."""
    _covers(main, True)
    w = _start_download(main)
    assert wait_until(lambda: w.picture.isVisibleTo(w)), "the link's video shows while it downloads"
    assert thumbs.asked == [("dQw4w9WgXcQ", False)]
    pix = w.picture.pixmap()
    assert not pix.isNull() and w.picture.width() * 9 == pytest.approx(w.picture.height() * 16, abs=16)
    assert w.picture.accessibleName() == S.PICTURE_NAME
    held_extract["release"].set()
    assert wait_until(lambda: w.running is None)
    assert not w.picture.isVisibleTo(w) and not w.progress.isVisibleTo(w), "done: the window as it was"


def _playlist_run(main, monkeypatch, spaced=0.0):
    """A playlist link (it names no video) whose six transcripts are written `spaced` s apart, then a bilibili one;
    the run holds until `gate` is set."""
    monkeypatch.setattr(ytdlp_manager, "ensure_available", lambda log: "yt-dlp.exe")
    gate = threading.Event()

    def extract(urls, folder, lang, keep_timestamps, channel_first, log, should_stop=None):
        for i in range(6):
            log(f"  [ok] (manual) Tsubasa no Kitchen - {names('ja')[i]} [dQw4w9WgXc{i}].txt")
            time.sleep(spaced)
        log(f"  [ok] (manual) {names('zh')[0]} [bilibili-4001234].txt")
        gate.wait(10)
    monkeypatch.setattr(core, "extract", extract)
    _covers(main, True)
    w = _downloader(main, ack=True)
    w.links.setPlainText("https://www.youtube.com/playlist?list=PLx0sYbCqOb8TBPRdmBHs5Iftvv9TPboYG")
    w.download.click()
    return w, gate


def test_a_playlists_transcripts_show_the_newest_video_once_its_gap_passed_the_ones_between_never_asked(
        main, monkeypatch, thumbs):
    """A playlist link names no video: the picture comes with the first transcript written (`[ok] … [id].txt`), then
    — once `PICTURE_GAP_S` has passed — the newest; the ones written between are never asked (no request per video it
    didn't show); a bilibili transcript changes nothing."""
    monkeypatch.setattr(qt_window, "PICTURE_GAP_S", 0.5)
    w, gate = _playlist_run(main, monkeypatch, spaced=0.03)
    assert wait_until(lambda: [a for a, _t in thumbs.asked][-1:] == ["dQw4w9WgXc5"] and w.picture.isVisibleTo(w))
    asked = [a for a, _t in thumbs.asked]
    assert asked[0] == "dQw4w9WgXc0" and len(asked) <= 2, asked
    gate.set()
    assert wait_until(lambda: w.running is None) and not w.picture.isVisibleTo(w)


def test_transcripts_written_seconds_apart_still_ask_at_most_one_picture_a_gap(main, monkeypatch, thumbs):
    """(The adversary's probe: transcripts a few tenths of a second apart each got a request.) Within the gap, however
    they are spaced, the first video is the only one asked."""
    w, gate = _playlist_run(main, monkeypatch, spaced=0.1)
    assert wait_until(lambda: thumbs.asked) and wait_until(lambda: w.picture.isVisibleTo(w))
    end = time.monotonic() + 1.0
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.02)
    assert [a for a, _t in thumbs.asked] == ["dQw4w9WgXc0"]
    gate.set()
    assert wait_until(lambda: w.running is None)


def test_a_newer_video_whose_picture_fails_never_keeps_the_older_ones_picture(main, monkeypatch):
    """Video A shown, video B's fetch fails: no picture rather than A's picture labelled as B."""
    fake = _Thumbs(lambda vid: "png" if vid == "dQw4w9WgXc0" else None)
    monkeypatch.setattr(main, "cover_fetcher", lambda: fake)
    monkeypatch.setattr(qt_window, "PICTURE_GAP_S", 0.3)
    w, gate = _playlist_run(main, monkeypatch, spaced=0.1)
    assert wait_until(lambda: w.picture.isVisibleTo(w))
    assert wait_until(lambda: len(fake.asked) == 2 and not w._picture["busy"])
    QApplication.processEvents()
    assert not w.picture.isVisibleTo(w) and w.picture.pixmap().isNull()
    gate.set()
    assert wait_until(lambda: w.running is None)


def test_a_fetcher_already_on_the_next_language_is_never_asked(main, held_extract, monkeypatch):
    """The main window switched language mid-run (the window's own switch waits for its run): the shell's fetcher
    is the next language's, and its cache names would be: nothing asked, no picture."""
    fake = _Thumbs(language="zh")
    monkeypatch.setattr(main, "cover_fetcher", lambda: fake)
    _covers(main, True)
    w = _start_download(main)
    for _ in range(20):
        QApplication.processEvents()
        time.sleep(0.01)
    assert fake.asked == [] and not w.picture.isVisibleTo(w)


def test_with_download_covers_off_nothing_is_asked_and_no_picture_shows(main, held_extract, monkeypatch):
    """Covers off (the default): the window is as it was — no picture, and the covers' fetcher never even asked."""
    fake = _Thumbs()
    asked = []
    monkeypatch.setattr(main, "cover_fetcher", lambda: asked.append(True) or fake)
    w = _start_download(main)
    assert main.services.settings.get().get("covers_download") is not True
    for _ in range(20):
        QApplication.processEvents()
        time.sleep(0.01)
    assert asked == [] and fake.asked == []
    assert not w.picture.isVisibleTo(w) and w.progress.isVisibleTo(w)


@pytest.mark.parametrize("answer", [None, OSError("offline")])
def test_offline_or_failed_is_quietly_no_picture_and_the_run_goes_on(main, held_extract, monkeypatch, answer):
    """No answer (offline, refused, an error on the worker): no picture, nothing said — the run's own line stays."""
    fake = _Thumbs(answer)
    monkeypatch.setattr(main, "cover_fetcher", lambda: fake)
    _covers(main, True)
    w = _start_download(main)
    assert wait_until(lambda: fake.asked) and wait_until(lambda: not w._picture["busy"])
    QApplication.processEvents()
    assert not w.picture.isVisibleTo(w) and w.running == "download"
    assert "offline" not in w.status.text()


def test_the_real_fetcher_shows_a_cached_thumbnail_and_sends_nothing(main, held_extract, monkeypatch):
    """The covers' own fetcher end to end: the video's thumbnail already in the covers cache (a title's cover of it)
    shows with no request — the network door fails the test if anything is sent; offline with nothing cached, no
    picture, quietly."""
    from app import path_utils
    from app.services import covers_online as O
    from tests.test_services_covers import png
    sent = []

    def door(request, allowed):
        sent.append(request.full_url)
        raise OSError("the network is blocked in tests")
    monkeypatch.setattr(O, "_open", door)
    _covers(main, True)
    f = O.Fetcher("ja", object(), settings=main.services.settings.get, background=False)
    monkeypatch.setattr(main, "cover_fetcher", lambda: f)
    name = O._cache_name("ja", "youtube", "dQw4w9WgXcQ", ".png")
    with open(os.path.join(path_utils.get_covers_cache_path(), name), "wb") as fh:
        fh.write(png(48, 36))
    w = _start_download(main)
    assert wait_until(lambda: w.picture.isVisibleTo(w)) and sent == []
    held_extract["release"].set()
    assert wait_until(lambda: w.running is None)
    os.remove(os.path.join(path_utils.get_covers_cache_path(), name))
    held_extract["release"].clear()
    w.download.click()
    assert wait_until(lambda: sent == ["https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"])
    assert wait_until(lambda: not w._picture["busy"]) and not w.picture.isVisibleTo(w)
    held_extract["release"].set()
    assert wait_until(lambda: w.running is None)


def test_a_download_is_a_youtube_job_that_the_apps_quit_cancels(main, held_extract):
    w = _start_download(main)
    assert wait_until(lambda: held_extract["calls"])
    [job] = _youtube_jobs(main)
    assert job.on_quit == "cancel" and job.label == S.JOB_DOWNLOAD and job.can_cancel
    main.services.registry.quit(5.0)                                  # what quitting does to it
    assert held_extract["stops"] == [True] and _youtube_jobs(main) == []
    assert wait_until(lambda: w.running is None)


def test_cancelling_the_job_in_the_bar_stops_the_download_and_the_window_says_so(main, held_extract):
    w = _start_download(main)
    assert wait_until(lambda: held_extract["calls"])
    _job(main, "running").cancel()
    assert wait_until(lambda: w.running is None)
    assert held_extract["stops"] == [True] and w.status.text() == S.STOPPED and w.download.isEnabled()


def test_the_bar_shows_the_runs_last_line_while_it_runs(main, held_extract):
    _start_download(main)
    assert wait_until(lambda: _youtube_jobs(main) and _youtube_jobs(main)[0].progress is not None)
    assert _youtube_jobs(main)[0].progress.step == f"[ok] (manual) {names('ja')[0]}"


def test_a_run_ending_after_its_window_closed_says_its_last_line_in_the_bar(main, held_extract):
    held_extract["obeys"] = False                                     # still finishing what it started
    w = _start_download(main)
    assert wait_until(lambda: held_extract["calls"])
    w.close_for_good()                                                # its icon's Close (X tucks it: a9.1)
    held_extract["release"].set()
    assert wait_until(lambda: main.bar_line.full() == S.STOPPED_KEPT.format(what=S.new_transcripts(1)))


def test_a_closed_windows_run_holds_the_next_download_back_until_it_ends(main, held_extract):
    # AD4-9: one yt-dlp run at a time across windows — a reopened downloader never starts a second run beside the old
    # one (both would write Processed, and the old one's late files would read as the new run's).
    held_extract["obeys"] = False
    w = _start_download(main)
    assert wait_until(lambda: held_extract["calls"])
    w.close_for_good()                                                # its icon's Close (X tucks it: a9.1)
    QApplication.processEvents()
    w2 = _start_download(main)
    assert w2 is not w
    assert wait_until(lambda: w2.status.text() == S.WAITING)
    assert len(held_extract["calls"]) == 1 and not w2.download.isEnabled()
    assert [v.state for v in _youtube_jobs(main)] == ["cancelling", "waiting"]
    held_extract["obeys"] = True
    held_extract["release"].set()
    assert wait_until(lambda: len(held_extract["calls"]) == 2 and w2.running is None)


def test_cancelling_a_waiting_download_frees_its_window(main, held_extract):
    held_extract["obeys"] = False
    w = _start_download(main)
    assert wait_until(lambda: held_extract["calls"])
    w.close_for_good()                                                # its icon's Close (X tucks it: a9.1)
    w2 = _start_download(main)
    assert wait_until(lambda: w2.status.text() == S.WAITING)
    _job(main, "waiting").cancel()
    assert wait_until(lambda: w2.running is None) and w2.status.text() == S.STOPPED and w2.download.isEnabled()


def test_the_run_log_is_made_on_the_runs_thread(main, fake_ytdlp, monkeypatch):
    # AD4-5: the log file is opened (and truncated) by the run, never on the window's thread.
    threads = []
    real = view.RunLog._open

    def recorded(self):
        threads.append(threading.current_thread() is threading.main_thread())
        return real(self)
    monkeypatch.setattr(view.RunLog, "_open", recorded)
    w = _start_download(main)
    assert wait_until(lambda: w.running is None)
    assert threads == [False]


@pytest.mark.parametrize("n", [1, 2])
def test_new_transcripts_are_said_to_wait_in_processed(main, fake_ytdlp, n):
    # IK-32: 3.0 has no Content Manager to send the user to; until W3.2's arrivals, the files wait in Processed.
    w = _downloader(main, ack=True)
    w.links.setPlainText("\n".join([VIDEO, "https://youtu.be/9bZkp7q19f0"][:n]))
    w.download.click()
    assert wait_until(lambda: w.running is None)
    assert w.status.text() == ("1 new transcript waits in Processed." if n == 1 else
                               "2 new transcripts wait in Processed.")


def test_a_later_opener_never_takes_a_running_downloads_files(main, held_extract):
    # AD4-15: the files go to the callback the run started with.
    first, later = [], []
    w = _start_download(main, on_complete=first.append)
    assert wait_until(lambda: held_extract["calls"])
    assert qt_window.open(main, on_complete=later.append) is w
    held_extract["obeys"] = False
    held_extract["release"].set()
    assert wait_until(lambda: w.running is None)
    assert len(first) == 1 and later == []


def test_a_fill_the_language_switch_overtook_says_why_it_did_nothing(main, monkeypatch):
    words = names("ja")
    folder = os.path.join(get_data_path("ja"), "LowPriority")
    os.makedirs(folder)
    with open(os.path.join(folder, f"{words[0]} [dQw4w9WgXcQ].txt"), "w", encoding="utf-8") as f:
        f.write(words[1])
    monkeypatch.setattr(core, "backfill_cues", lambda *a, **k: pytest.fail("filled"))
    w = _downloader(main)
    w.backfill.trigger()
    assert wait_until(lambda: _confirm(w) is not None)
    w.language = "zh"                                                # switched while the question was open
    _confirm(w).yes.click()
    assert w.status.text() == S.FILL_LANGUAGE_CHANGED and w.running is None


def test_open_the_log_before_any_run_says_there_is_none(main, opened):
    w = _downloader(main)
    w.open_log.trigger()
    assert wait_until(lambda: w.status.text() == S.NO_LOG) and opened == []


# ====================================================================================================================
# The fix round (2026-10-14): the preview's scoring in a child, its fetch a job (AD4-2, IK-29, IK-31); a workspace per
# run (AD4-3); nothing started on a thread at close (IK-28)
# ====================================================================================================================
_FAKE_SCORER = r'''
import json, sys, time
mode, out = sys.argv[1], sys.argv[sys.argv.index("--out") + 1]
if mode == "hang":
    time.sleep(60)
open(out, "w", encoding="utf-8").write("<html></html>")
print("@result " + json.dumps({"html": out}), flush=True)
'''


@pytest.fixture
def real_pipeline(monkeypatch, tmp_path):
    """The real `run_preview` and `Runs` behind the window: a cached list for Japanese, yt-dlp's lookup and download
    faked, the scoring child a stand-in script (the analyzer must never be called in this process), the report
    recorded."""
    path = pv.library_index_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"settings": {"min_count": 2, "total_tokens": 1000, "language": "ja"}, "words": {}}, f)
    monkeypatch.setattr(core, "_probe", lambda url, log: {"_type": "video", "id": "dQw4w9WgXcQ"})
    monkeypatch.setattr(ytdlp_manager, "ensure_available", lambda log: "yt-dlp.exe")

    def extract(urls, ws, lang, channel_first, log, should_stop=None):
        with open(os.path.join(ws, f"{names('ja')[0]} [dQw4w9WgXcQ].txt"), "w", encoding="utf-8") as f:
            f.write(names("ja")[1])
    monkeypatch.setattr(core, "extract", extract)
    monkeypatch.setattr(pv, "analyze_transcript", lambda *a: pytest.fail("scored in the window's process"))
    script = tmp_path / "fake_scorer.py"
    script.write_text(_FAKE_SCORER, encoding="utf-8")
    box = {"mode": "ok", "reports": []}
    monkeypatch.setattr(pv, "child_argv", lambda lang, out, transcripts, frozen=None: [str(script), box["mode"],
                                                                                        "--out", out] + transcripts)
    monkeypatch.setattr(pv, "open_report", lambda path, app_mode=False: box["reports"].append(path))
    return box


def test_the_windows_preview_fetches_in_a_job_and_scores_in_a_child(main, real_pipeline):
    w = _preview(main)
    w.link.setText(VIDEO)
    w.go.click()
    assert wait_until(lambda: not w.running and real_pipeline["reports"], timeout=60)
    [report] = real_pipeline["reports"]
    assert os.path.basename(report) == "preview.html" and w.status.text() == S.PREVIEW_OPENED
    youtube = [v for v in main.services.registry.snapshot() if v.kind == "youtube"]
    assert [v.state for v in youtube] == ["done", "done"] and all(v.on_quit == "cancel" for v in youtube)
    assert youtube[1].pid                                            # the scoring was a process of its own


def test_closing_while_the_child_scores_ends_it_and_removes_the_runs_workspace(main, real_pipeline, monkeypatch):
    real_pipeline["mode"] = "hang"
    made, real_new = [], pv.new_workspace
    monkeypatch.setattr(pv, "new_workspace", lambda: made.append(real_new()) or made[-1])
    w = _preview(main)
    w.link.setText(VIDEO)
    w.go.click()
    assert wait_until(lambda: any(v.kind == "youtube" and v.pid for v in main.services.registry.live()), timeout=30)
    w.close()
    assert wait_until(lambda: not main.services.registry.live("youtube"), timeout=30)
    assert wait_until(lambda: made and not os.path.exists(made[0]))      # removed by its own run as it ended
    assert real_pipeline["reports"] == []
    [scoring] = [v for v in main.services.registry.snapshot() if v.kind == "youtube" and v.pid]
    assert scoring.cancelled


def test_an_opened_previews_workspace_stays_until_its_window_closes(main, real_pipeline):
    w = _preview(main)
    w.link.setText(VIDEO)
    w.go.click()
    assert wait_until(lambda: not w.running and real_pipeline["reports"], timeout=60)
    workspace = os.path.dirname(real_pipeline["reports"][0])
    assert os.path.isfile(real_pipeline["reports"][0])
    w.close()
    assert wait_until(lambda: not os.path.exists(workspace))


def test_a_run_that_opened_nothing_removes_its_workspace_at_once(main, run_preview, tmp_path):
    _calls, box, _reports, _c = run_preview
    workspace = tmp_path / "ws_failed"
    workspace.mkdir()
    box["outcome"] = lambda call: pv.Outcome(error=pv.NO_TRANSCRIPT, workspace=str(workspace))
    w = _preview(main)
    w.link.setText(VIDEO)
    w.go.click()
    assert wait_until(lambda: not w.running)
    assert not workspace.exists() and not w.gone


def test_closing_the_preview_starts_no_thread_and_imports_nothing(main, run_preview, tmp_path, monkeypatch):
    # IK-28: a thread started (or a module imported) as the window closes could still be running Python as the app's
    # process ends (the 0xC0000005 at exit).
    _calls, box, _reports, _c = run_preview
    workspace = tmp_path / "ws_opened"
    workspace.mkdir()
    box["outcome"] = lambda call: pv.Outcome(html=str(workspace / "preview.html"), workspace=str(workspace))
    w = _preview(main)
    w.link.setText(VIDEO)
    w.go.click()
    assert wait_until(lambda: not w.running)
    started = []
    real_start = threading.Thread.start
    monkeypatch.setattr(threading.Thread, "start", lambda self: started.append(self.name) or real_start(self))
    before = set(sys.modules)
    w.close()
    assert started == [] and set(sys.modules) == before
    assert wait_until(lambda: not workspace.exists())                # the kept one goes on a pool worker


def test_W32_2_the_done_line_links_to_the_new_arrivals_tray(main, fake_ytdlp, monkeypatch):
    # IK-L1-2: with a library (the tray there), the line says where the transcripts went and its link opens the tray
    trays = []
    monkeypatch.setattr(main, "arrivals_tray", object(), raising=False)
    monkeypatch.setattr(main, "open_arrivals", lambda: trays.append(1), raising=False)
    w = _downloader(main, on_complete=lambda _paths: None, ack=True)
    w.links.setPlainText(VIDEO)
    w.download.click()
    assert wait_until(lambda: w.running is None)
    assert w.status.textFormat() == Qt.TextFormat.RichText
    assert S.SEE_IN_ARRIVALS in w.status.text() and 'href="arrivals"' in w.status.text()
    w.status.linkActivated.emit("arrivals")
    assert trays == [1]


# --- round 8 row 45: every press reacts at once ------------------------------------------------------------------- #
def test_open_folder_paints_its_arc_before_the_folder_is_looked_for_and_opened(main, opened, monkeypatch):
    # *Open folder* showed nothing until its worker had found the folder and the system had opened it (on the
    # window's thread): its arc now turns, painted before the work is handed over — since try a9.1 an item of ⋯, so
    # the window's corner arc (a menu's press, IK-2).
    from tests.qt.press_handover import HandOver, corner_turning
    w = _downloader(main)
    assert QTest.qWaitForWindowExposed(w)
    handed = HandOver(monkeypatch, w, lambda: corner_turning(w))
    w.open_folder.trigger()
    work = handed.at("work")
    assert work.shown and work.painted >= 1
    assert wait_until(lambda: opened and not corner_turning(w))


def test_preview_paints_its_arc_before_its_run_starts_and_is_never_greyed(main, run_preview, monkeypatch):
    # *Preview* greyed with no words until the run's first step: its arc now turns from the press (painted before the
    # run's thread starts) until the run ends; the steps' words come as before.
    from tests.qt.press_handover import Paints, arc_turning
    _calls, _box, reports, _c = run_preview
    w = _preview(main)
    assert QTest.qWaitForWindowExposed(w)
    paints, seen, real = Paints(w.go), [], qt_preview.threading.Thread

    def watched(*args, **kw):
        seen.append((arc_turning(w.go), paints.n, w.go.isEnabled()))
        return real(*args, **kw)
    monkeypatch.setattr(qt_preview.threading, "Thread", watched)
    w.link.setText(VIDEO)
    w.go.click()
    shown, painted, enabled = seen[0]
    assert shown and painted >= 1 and enabled
    assert wait_until(lambda: not w.running and reports and not arc_turning(w.go))


# ====================================================================================================================
# Alpha 8: setup's *YouTube* (`fetch_first`)
# ====================================================================================================================
def test_setups_fetch_runs_as_a_youtube_job_and_hands_back_its_files_and_why_not(main, monkeypatch):
    """`yt.fetch_first`: each link's first video (`first_only`), on a `youtube` job off the window's thread; its end
    on the window's thread with the new transcripts and the plain-words lines of what went wrong."""
    monkeypatch.setattr(ytdlp_manager, "ensure_available", lambda log: "yt-dlp.exe")
    seen = {}

    def extract(urls, folder, lang, keep_timestamps, channel_first, log, should_stop=None, first_only=False):
        seen.update(urls=urls, lang=lang, keep=keep_timestamps, first=first_only,
                    on_gui=threading.current_thread() is threading.main_thread())
        with open(os.path.join(folder, f"{names('ja')[0]} [lecture0001].txt"), "w", encoding="utf-8") as f:
            f.write(names("ja")[1])
        log("  [ok] (manual) " + names("ja")[0])
        log("  ! could not read https://www.youtube.com/playlist?list=PLx: the video is private or no longer there")
    monkeypatch.setattr(core, "extract", extract)
    ended = []
    job = yt.fetch_first(main, ["https://www.youtube.com/watch?v=lecture0001", "https://www.youtube.com/playlist?list=PLx"],
                         "ja", lambda _line: None,
                         lambda created, problems: ended.append((created, problems,
                                                                 threading.current_thread() is threading.main_thread())))
    assert job is not None
    assert wait_until(lambda: ended, 10)
    created, found, on_gui = ended[0]
    assert on_gui and [os.path.basename(p) for p in created] == [f"{names('ja')[0]} [lecture0001].txt"]
    assert found == ["could not read https://www.youtube.com/playlist?list=PLx: the video is private or no longer there"]
    assert seen == dict(urls=["https://www.youtube.com/watch?v=lecture0001", "https://www.youtube.com/playlist?list=PLx"],
                        lang="Japanese", keep=False, first=True, on_gui=False)


def test_setups_fetch_without_yt_dlp_says_so_in_plain_words(main, monkeypatch):
    monkeypatch.setattr(ytdlp_manager, "ensure_available",
                        lambda log: log("Could not download yt-dlp: <urlopen error timed out>") or None)
    monkeypatch.setattr(core, "extract", lambda *a, **k: pytest.fail("fetched without yt-dlp"))
    ended = []
    yt.fetch_first(main, ["https://www.youtube.com/watch?v=lecture0001"], "ja", lambda _l: None,
                   lambda created, problems: ended.append((created, problems)))
    assert wait_until(lambda: ended, 10)
    assert ended[0] == ([], [view.NO_READER])


# ====================================================================================================================
# Alpha 8 (Sonic: "it should still get the whole playlist"): a playlist's rest, in the background (`bring_in_rest`)
# ====================================================================================================================
PLAYLIST = "https://www.youtube.com/playlist?list=PLsamplepodcast0000000000000000001"
PL_FOLDER = "hanashi radio - Everyday Japanese Podcast (playlist)"
OFFLINE = f"  ! could not read {PLAYLIST}: YouTube couldn't be reached: check your internet connection"
OFFLINE_WHY = "YouTube couldn't be reached: check your internet connection"


@pytest.fixture
def rest_run(monkeypatch):
    """yt-dlp ready; the rest's run faked at `core.extract` (what it writes and says set per test, `hold` keeps it
    running until released or stopped); the downloader's hand-over (`windows.youtube_arrivals`) recorded — `refuse`
    makes it raise as with no library open."""
    from app.qt import windows
    monkeypatch.setattr(ytdlp_manager, "ensure_available", lambda log: "yt-dlp.exe")
    box = {"calls": [], "write": 2, "say": [], "hold": None, "handed": [], "refuse": None, "quiet": [], "runs": 0}

    def extract(urls, folder, lang, keep_timestamps, channel_first, log, should_stop=None, new_only=False,
                written=None):
        box["calls"].append((list(urls), new_only, threading.current_thread() is threading.main_thread()))
        log("  … 1 of 3 videos read")
        for i in range(box["write"]):
            n = box["runs"] * 10 + i
            path = os.path.join(folder, PL_FOLDER, f"hanashi radio - {names('ja')[n]} [RestVid{n:04d}].txt")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(names("ja")[n + 30])
            written(path)
        box["runs"] += 1
        for line in (box["say"](box["runs"]) if callable(box["say"]) else box["say"]):
            log(line)
        while box["hold"] is not None and not box["hold"].wait(0.02):
            if should_stop():
                log("Stopped.")
                return
    monkeypatch.setattr(core, "extract", extract)

    def arrivals(shell, then=None, quiet=False):
        def complete(paths):
            if box["refuse"]:
                raise RuntimeError(box["refuse"])
            box["handed"].append(list(paths))
            box["quiet"].append(quiet)
            then(len(paths), 0, 0)
        return complete
    monkeypatch.setattr(windows, "youtube_arrivals", arrivals)
    return box


def _rest(language):
    """The rest's record, read as the app reads it: under its lock (`rest_update` holds it). A read outside it holds
    the file open on Windows while the worker's `os.replace` lands on it, which refuses the replace (Access is denied):
    the record's write then fails the run. The app never reads it outside the lock (FLAKES.md, 2026-11-10)."""
    with view._REST_LOCK:
        return view.rest_read(language)


def _waiting(n):
    from app.qt import strings
    return strings.YT_ARRIVED_WAITING.format(what=strings.yt_transcripts(n))


def test_a_playlists_rest_comes_in_on_a_youtube_job_and_its_videos_reach_new_arrivals(main, rest_run):
    """Setup's playlist: recorded, then one automatic `youtube` job off the window's thread reading only the videos
    not in yet (`new_only`); each transcript recorded as written, all handed to the downloader's own seam, quietly —
    the rest says its own line in the bar — and the playlist leaves the record."""
    yt.bring_in_rest(main, "ja", [PLAYLIST])
    assert wait_until(lambda: rest_run["handed"], 10)
    [(urls, new_only, on_gui)] = rest_run["calls"]
    assert urls == [PLAYLIST] and new_only and not on_gui
    assert [os.path.basename(os.path.dirname(p)) for p in rest_run["handed"][0]] == [PL_FOLDER] * 2
    assert rest_run["quiet"] == [True]
    assert wait_until(lambda: main.bar_line.full() == S.REST_CAME.format(what=_waiting(2)), 3)
    assert wait_until(lambda: not os.path.exists(view.rest_path("ja")), 3)


def test_the_rests_job_is_named_shows_its_count_in_the_bar_and_never_holds_the_window(main, rest_run):
    rest_run["hold"] = threading.Event()
    yt.bring_in_rest(main, "ja", [PLAYLIST])
    assert wait_until(lambda: _youtube_jobs(main) and _youtube_jobs(main)[0].progress is not None, 10)
    [job] = _youtube_jobs(main)
    assert job.label == S.rest_job(1) and job.on_quit == "cancel" and job.can_cancel and job.automatic
    assert job.progress.step == "… 1 of 3 videos read"
    rest_run["hold"].set()
    assert wait_until(lambda: rest_run["handed"], 10)


def test_offline_the_rest_waits_for_the_next_start_and_says_so_without_the_link(main, rest_run):
    """No connection: nothing came, the playlist stays (a fruitless try counted), and the bar says it goes on next time
    — in plain words, never the link."""
    rest_run["write"], rest_run["say"] = 0, [OFFLINE]
    yt.bring_in_rest(main, "ja", [PLAYLIST])
    assert wait_until(lambda: main.bar_line.full() == S.REST_LATER.format(why=OFFLINE_WHY), 10)
    assert _rest("ja") == {"playlists": [PLAYLIST], "unrouted": [], "tries": {PLAYLIST: 1}}
    assert rest_run["handed"] == [] and "list=" not in main.bar_line.full()


def test_after_three_fruitless_tries_the_rest_is_dropped_and_said(main, rest_run):
    """(A8P-8) YouTube refusing at every start: after `REST_TRIES` runs that brought nothing, it stops asking."""
    rest_run["write"], rest_run["say"] = 0, [OFFLINE]
    view.rest_update("ja", add=[PLAYLIST], tried=[PLAYLIST])
    view.rest_update("ja", tried=[PLAYLIST])
    yt.bring_in_rest(main, "ja")
    assert wait_until(lambda: main.bar_line.full() == S.REST_SPENT.format(why=OFFLINE_WHY, tries=3), 10)
    assert wait_until(lambda: not os.path.exists(view.rest_path("ja")), 3)


def test_a_stalled_run_that_brought_videos_goes_on_at_once(main, rest_run):
    """(A8P-1) A stall (or a run past its time) after some videos came: kept, and the rest goes on now — not only at the
    next start — reading only what it hadn't; the second run finishes it."""
    stalled = "  ! " + core.STALLED.format(minutes=2)
    rest_run["say"] = lambda run: [stalled] if run == 1 else []
    yt.bring_in_rest(main, "ja", [PLAYLIST])
    assert wait_until(lambda: len(rest_run["calls"]) == 2, 10)
    assert wait_until(lambda: len(rest_run["handed"]) == 2, 10)
    assert wait_until(lambda: not os.path.exists(view.rest_path("ja")), 5)


def test_youtubes_bot_check_mid_run_hands_over_what_came_and_never_runs_again_at_once(main, rest_run):
    """(Yt-B) The bot check after two videos came: they reach New arrivals, the playlist stays with no fruitless try
    counted, and no run starts again now (that would ask YouTube again straight away): it goes on at a start after
    the hold, and the bar says when."""
    from app import youtube_hold
    youtube_hold.hold()
    said = youtube_hold.words(youtube_hold.held())
    rest_run["say"] = [f"  ! video RestVid0002: {said}"]
    yt.bring_in_rest(main, "ja", [PLAYLIST])
    assert wait_until(lambda: rest_run["handed"], 10)
    assert wait_until(lambda: main.bar_line.full().endswith(S.REST_HELD.format(why=said)), 10)
    assert wait_until(lambda: _rest("ja")["playlists"] == [PLAYLIST], 3)
    time.sleep(0.5)
    assert len(rest_run["calls"]) == 1, "never again at once"
    assert _rest("ja") == {"playlists": [PLAYLIST], "unrouted": [], "tries": {}}


def test_a_start_during_the_hold_spends_no_try(main, rest_run):
    """(Yt-B) Each start while the hold runs meets it: the playlist is kept, never dropped after three such starts."""
    from app import youtube_hold
    youtube_hold.hold()
    said = youtube_hold.words(youtube_hold.held())
    rest_run["write"], rest_run["say"] = 0, [f"  ! {said}"]
    view.rest_update("ja", add=[PLAYLIST], tried=[PLAYLIST])
    view.rest_update("ja", tried=[PLAYLIST])
    yt.bring_in_rest(main, "ja")
    assert wait_until(lambda: main.bar_line.full() == S.REST_HELD.format(why=said), 10)
    assert _rest("ja") == {"playlists": [PLAYLIST], "unrouted": [], "tries": {PLAYLIST: 2}}


def test_a_video_without_captions_is_said_and_the_playlist_is_done(main, rest_run):
    rest_run["say"] = ["  – no Japanese captions: " + names("ja")[5]]
    yt.bring_in_rest(main, "ja", [PLAYLIST])
    assert wait_until(lambda: main.bar_line.full().endswith("no Japanese captions: " + names("ja")[5]), 10)
    assert wait_until(lambda: not os.path.exists(view.rest_path("ja")), 3)


def test_cancelled_in_the_bar_what_came_is_handed_over_and_the_rest_is_dropped(main, rest_run):
    """(IK-3, PROVISIONAL) Cancel cancels: what came before it is in the library, the rest of the playlist is not
    asked for again (the YouTube window can bring it in), and the bar says so."""
    rest_run["hold"] = threading.Event()
    yt.bring_in_rest(main, "ja", [PLAYLIST])
    assert wait_until(lambda: _youtube_jobs(main) and _youtube_jobs(main)[0].progress is not None, 10)
    _job(main, "running").cancel()
    assert wait_until(lambda: rest_run["handed"], 10)
    assert len(rest_run["handed"][0]) == 2
    assert wait_until(lambda: main.bar_line.full() == S.REST_CAME.format(what=_waiting(2)) + " · " +
                      S.REST_CANCELLED, 3)
    assert wait_until(lambda: not os.path.exists(view.rest_path("ja")), 3)


def test_cancelled_before_it_started_the_rest_is_dropped_and_said(main, rest_run, held_extract):
    """(A8P-9) Queued behind another YouTube run and cancelled there: its record settled as a cancel, said as one."""
    w = _start_download(main)
    assert wait_until(lambda: held_extract["calls"])
    yt.bring_in_rest(main, "ja", [PLAYLIST])
    assert wait_until(lambda: len(_youtube_jobs(main)) == 2, 5)
    next(j for j in main.services.registry._jobs if j.kind == "youtube" and j.state == "waiting").cancel()
    assert wait_until(lambda: main.bar_line.full() == S.REST_CANCELLED, 5)
    assert wait_until(lambda: not os.path.exists(view.rest_path("ja")), 3)
    held_extract["release"].set()
    assert wait_until(lambda: w.running is None, 10)


def test_the_apps_quit_keeps_the_rest_for_the_next_start(main, rest_run):
    """A quit mid-way: what came is recorded as it was written; the playlist stays for the next start."""
    rest_run["hold"] = threading.Event()
    yt.bring_in_rest(main, "ja", [PLAYLIST])
    assert wait_until(lambda: len(_rest("ja")["unrouted"]) == 2, 10)      # recorded as written
    main.services.closing.set()                                       # (what the quit sets before the jobs' cancel)
    main.services.registry.quit(5.0)
    state = _rest("ja")
    assert state["playlists"] == [PLAYLIST]


def test_a_users_own_youtube_run_goes_first_and_the_rest_comes_after(main, rest_run, monkeypatch):
    """(IK-1, A8P-5) A Download pressed while the rest runs: the rest stops for it at once (what came is kept), the
    Download runs, then the rest goes on, reading only what it hadn't."""
    rest_extract, user = core.extract, {"calls": [], "release": threading.Event()}

    def extract(urls, folder, lang, keep_timestamps, channel_first, log, should_stop=None, **kw):
        if kw.get("new_only"):
            return rest_extract(urls, folder, lang, keep_timestamps, channel_first, log, should_stop, **kw)
        user["calls"].append(urls)                                    # the downloader window's own Download
        user["release"].wait(10)
    monkeypatch.setattr(core, "extract", extract)
    rest_run["hold"] = threading.Event()
    yt.bring_in_rest(main, "ja", [PLAYLIST])
    assert wait_until(lambda: rest_run["calls"], 10)
    w = _start_download(main)
    assert wait_until(lambda: user["calls"], 10)                      # the user's own run took over
    assert wait_until(lambda: main.bar_line.full().endswith(S.REST_YIELDED), 5)
    assert len(rest_run["handed"]) == 1                               # what came before is in the library
    rest_run["hold"] = None
    user["release"].set()
    assert wait_until(lambda: w.running is None, 10)
    assert wait_until(lambda: len(rest_run["calls"]) == 2, 10)        # the rest again, after it
    assert wait_until(lambda: not os.path.exists(view.rest_path("ja")), 5)


def test_files_a_run_wrote_but_never_handed_over_are_handed_at_the_next_start(main, rest_run):
    """The hand-over failed (no library to take them): the record keeps the transcripts; the next start's run hands
    them over with its own, though they are no longer new in Processed."""
    rest_run["refuse"] = "no library is open"
    yt.bring_in_rest(main, "ja", [PLAYLIST])
    assert wait_until(lambda: "no library is open" in main.bar_line.full(), 10)
    left = _rest("ja")["unrouted"]
    assert len(left) == 2
    rest_run["refuse"], rest_run["write"] = None, 0
    yt.bring_in_rest(main, "ja")                                       # the next start: no links given
    assert wait_until(lambda: rest_run["handed"], 10)
    assert sorted(rest_run["handed"][0]) == sorted(left)
    assert wait_until(lambda: not os.path.exists(view.rest_path("ja")), 3)


def test_a_playlist_asked_for_while_a_rest_runs_comes_after_it(main, rest_run):
    second = "https://www.youtube.com/playlist?list=PLsecondPlaylistOfHanashiRadio01"
    rest_run["hold"] = threading.Event()
    yt.bring_in_rest(main, "ja", [PLAYLIST])
    assert wait_until(lambda: rest_run["calls"], 10)
    yt.bring_in_rest(main, "ja", [second])
    assert wait_until(lambda: _rest("ja")["playlists"] == [PLAYLIST, second], 3)
    assert len(rest_run["calls"]) == 1                                 # one rest run at a time
    rest_run["hold"].set()
    assert wait_until(lambda: len(rest_run["calls"]) == 2, 10)
    assert rest_run["calls"][1][0] == [second]                          # the first one is done: only the new one
    assert wait_until(lambda: len(rest_run["handed"]) == 2, 10)
    assert not set(rest_run["handed"][0]) & set(rest_run["handed"][1])  # (A8P-11) the first's never handed twice
    assert wait_until(lambda: not os.path.exists(view.rest_path("ja")), 5)


def test_nothing_recorded_starts_nothing(main, rest_run):
    yt.bring_in_rest(main, "ja")
    QApplication.processEvents()
    time.sleep(0.3)
    QApplication.processEvents()
    assert rest_run["calls"] == [] and _youtube_jobs(main) == []


def test_a_record_holding_only_a_deleted_transcript_starts_nothing_and_goes(main, rest_run, tmp_path):
    """(A8P-4) The learner deleted the one transcript left to hand over: no job at this start (nor any after), and the
    record goes."""
    view.rest_update("ja", unrouted=[str(tmp_path / "deleted meanwhile [RestVid9999].txt")])
    yt.bring_in_rest(main, "ja")
    assert wait_until(lambda: not os.path.exists(view.rest_path("ja")), 5)
    QApplication.processEvents()
    assert rest_run["calls"] == [] and rest_run["handed"] == []        # never a job, never a hand-over of nothing
    assert not any(j.kind == "youtube" for j in main.services.registry._jobs)


@pytest.mark.parametrize("risk, starts", [(True, True), (False, False)])
def test_each_start_resumes_a_recorded_rest_only_with_the_risk_acknowledged(main, rest_run, monkeypatch, risk, starts):
    from app.qt import windows
    asked = []
    monkeypatch.setattr(yt, "bring_in_rest", lambda shell, language, playlists=(): asked.append(language))
    main.services.settings.set({"enable_youtube_transcripts": True, "youtube_risk_acknowledged": risk})
    view.rest_update("ja", add=[PLAYLIST])
    windows.resume_youtube(main)
    assert bool(wait_until(lambda: asked, 3)) == starts                       # (a resume only ever goes through it)
    assert _rest("ja")["playlists"] == [PLAYLIST]


def test_a_run_ending_while_the_window_is_in_its_icon_takes_its_bar_away_and_the_next_starts_afresh(main, held_extract):
    """Review (a9.1): the bar is hidden at a run's end even while the window is in its icon (X or minimise), so it is
    never found still turning beside an enabled Download, and the next run starts turning — never at the old count."""
    w = _start_download(main)
    assert wait_until(lambda: held_extract["calls"])
    w.progress.setRange(0, 5)
    w.progress.setValue(2)
    w.close()                                                        # X: into its icon
    QApplication.processEvents()
    assert w.tucked()
    held_extract["release"].set()
    assert wait_until(lambda: w.running is None)
    windows.bring_back(w)
    assert wait_until(lambda: w.isVisible())
    assert w.progress.isHidden() and w.download.isEnabled()
    held_extract["release"].clear()
    w.links.setPlainText(VIDEO)
    w.download.click()
    assert not w.progress.isHidden() and (w.progress.minimum(), w.progress.maximum()) == (0, 0)


def test_the_how_to_stop_line_keeps_the_bar_while_the_run_goes_on_saying_things(main, held_extract):
    """Review (a9.1): the first X's line ("right-click its icon to stop") holds the bar for its time — the run's next
    line in the bar never wipes it at once."""
    w = _start_download(main)
    assert wait_until(lambda: held_extract["calls"])
    w.close()
    QApplication.processEvents()
    main.bar_line.set_full(main.bar_line.full())                     # (the bar painted again, as a job's line does)
    main._paint_slot()
    assert main.bar_line.full() == S.KEPT_DOWNLOADING


def test_a_fills_count_moves_the_bar_and_keeps_its_words_and_a_titles_bracket_is_its_own():
    """Review (a9.1): only a line that starts with the run's count moves the bar; the fill's line keeps its words (why
    it pauses); a title's own bracket is never read as the caption kind."""
    assert qt_window._COUNTED.match("… 10/50 done, pausing 60s to stay under YouTube's limits").group(3) == "done"
    assert qt_window._COUNTED.match("[ok] 3 of 10 done [dQw4w9WgXcQ].txt") is None
    assert qt_window._WRITTEN.match("[ok] (Live) 歌枠 [dQw4w9WgXcQ].txt").group(1) == "(Live) 歌枠"
    assert qt_window._WRITTEN.match("[ok] (native auto) 朝ごはん [dQw4w9WgXcQ].txt").group(1) == "朝ごはん"
