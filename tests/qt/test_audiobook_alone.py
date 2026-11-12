"""An audiobook brought in alone (Kantan-B3; Mattias in #testers, 2026-11-12: he dropped his audiobook in without its
book, was told *Only text and subtitle files can be added* — "Ah, has to be srt then I guess"). Words PROVISIONAL.

What the window does now, at each door the learner may use:
  * dropped from Explorer (a file or its folder), or picked with + Add → *Files…*: an audio file is an audiobook — never
    a file *left out*: one card names it and what happens (its folder read where it is, then its book found or asked
    for), and *Read its folder* reads it as + Add → *A folder…* does; a subtitle or text in the same drop is added as
    before; a video, a picture or a folder without audio is still named as left out (AD-4);
  * setup's *Choose a file…*: the audiobook is named, its folder offered (*Choose its folder*), never "reads subtitles,
    texts and EPUBs only".

What a wrong answer would cost a learner: the dead end he met (a subtitle file sounds needed for an audiobook), a
folder such as Downloads read and watched without his say, a folder listed on the window's thread (a freeze), or the
subtitles he dropped beside it lost.

Real MP3 / M4B files (tests/test_audiobooks' builders: real tags and lengths), a real subtitle from tests/Test
Resources, made-up titles.
"""
import os
import threading

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint

from app.qt import add_menu, strings
from app.qt import wizard_strings as WS
from tests import services_helpers as h
from tests.qt.conftest import wait_until
from tests.qt.test_drag import FakeWriter, _drop_files, calls, lst_of, open_window  # noqa: F401
from tests.test_audiobooks import _m4b, _mp3
from tests.fixtures import window_seed

GINGA = "銀河鉄道の夜"


class Looks:
    """The window's looks as + Add's *A folder…* calls them: each folder asked recorded (with the thread)."""

    def __init__(self):
        self.added = []
        self.on_result = self.on_progress = None

    def add(self, path, then=None, first=False):
        self.added.append((path, threading.current_thread() is threading.main_thread()))
        return True

    def busy(self):
        return False

    def asked(self, focused=False, refreshed=False, shown=True):
        return True

    def set_shown(self, shown):
        pass

    def listing(self):
        return True

    def close(self):
        pass


@pytest.fixture
def world(qapp):
    made = []

    def make(looks=True):
        seed = window_seed.build()
        writer = FakeWriter(seed.library, apply=False)
        win, services = open_window(qapp, seed, writer)
        if looks:
            win.looks = Looks()
        made.append((win, services))
        return win, writer
    yield make
    for win, services in made:
        q = getattr(win.adder, "question", None)
        if q is not None:
            q._answer(False)
        win.close()
        services.shutdown(0.5)


def _audiobook(root, name=GINGA, n=3):
    """A folder of `n` chapter MP3s of an audiobook (an hour in all), as a learner keeps one."""
    folder = os.path.join(str(root), "Audiobooks", name)
    return folder, [_mp3(os.path.join(folder, f"{i:02d}.mp3"), seconds=3600 / n, frames={"TALB": name, "TRCK": str(i)})
                    for i in range(1, n + 1)]


def _subtitle(folder, name):
    with open(os.path.join(h.RESOURCES, "ja", "phrases_sample.srt"), encoding="utf-8") as f:
        text = f.read()
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _drop(win, paths):
    lst = lst_of(win)
    rect = lst.visualRect(lst.model().index(0, 0))
    return _drop_files(lst, [str(p) for p in paths], QPoint(rect.center().x(), rect.top() + 3))


def _asked(win):
    assert wait_until(lambda: getattr(win.adder, "question", None) is not None, 5)
    return win.adder.question


def _no_subtitle_hint(*texts):
    """Nothing said about an audiobook may sound like a subtitle file is needed (the field report's dead end)."""
    for t in texts:
        low = (t or "").lower()
        assert "subtitle" not in low and "srt" not in low and "left out" not in low, t


# --- the drop -------------------------------------------------------------------------------------------------------- #
def test_an_audiobook_file_dropped_alone_is_named_an_audiobook_never_left_out(world, tmp_path):
    win, writer = world()
    m4b = _m4b(os.path.join(tmp_path, "Downloads", f"{GINGA}.m4b"), 3600, tags={"album": GINGA})
    _drop(win, [m4b])
    q = _asked(win)
    assert GINGA in q.title.text() and "audiobook" in q.title.text().lower()
    assert "Downloads" in q.body.text()                          # the folder that would be read, named before it is
    _no_subtitle_hint(q.title.text(), q.body.text(), win.bar_line.full())
    assert calls(writer, "insert_at") == []                      # nothing handed to the writer: no "left out" note
    assert win.looks.added == []                                 # nothing read before his yes


def test_read_its_folder_reads_the_audiobooks_folder_where_it_is(world, tmp_path):
    win, writer = world()
    folder, mp3s = _audiobook(tmp_path)
    _drop(win, mp3s)
    q = _asked(win)
    assert q.yes.text() == strings.AUDIOBOOK_IN_YES
    q.yes.click()
    assert wait_until(lambda: win.looks.added, 5)
    assert win.looks.added == [(os.path.normpath(folder), False)] or \
        [p for p, _t in win.looks.added] == [os.path.normpath(folder)]   # one folder, read once (three files dropped)
    assert calls(writer, "insert_at") == []


def test_cancel_reads_nothing(world, tmp_path):
    win, writer = world()
    _folder, mp3s = _audiobook(tmp_path)
    _drop(win, mp3s[:1])
    _asked(win).no.click()
    assert win.looks.added == [] and calls(writer, "insert_at") == []


def test_a_dropped_folder_holding_an_audiobook_is_read_by_its_yes_and_listed_off_the_windows_thread(world, tmp_path,
                                                                                                    monkeypatch):
    win, writer = world()
    folder, _mp3s = _audiobook(tmp_path)
    main, listed = threading.main_thread(), []
    real = add_menu.audiobook_folders

    def spy(paths):
        listed.append(threading.current_thread() is main)
        return real(paths)
    monkeypatch.setattr(add_menu, "audiobook_folders", spy)
    _drop(win, [folder])
    q = _asked(win)
    assert listed == [False]                                     # its listing on a worker, never the window's thread
    assert GINGA in q.title.text()
    q.yes.click()
    assert wait_until(lambda: win.looks.added, 5)
    assert [p for p, _t in win.looks.added] == [os.path.normpath(folder)] and calls(writer, "insert_at") == []


def test_a_disc_folder_inside_the_dropped_folder_counts(world, tmp_path):
    win, _writer = world()
    top = os.path.join(tmp_path, GINGA)
    _mp3(os.path.join(top, "Disc 1", "01.mp3"), seconds=2400, frames={"TALB": GINGA})
    _drop(win, [top])
    assert GINGA in _asked(win).title.text()


def test_subtitles_dropped_beside_an_audiobook_are_added_as_before(world, tmp_path):
    win, writer = world()
    srt = _subtitle(os.path.join(tmp_path, "Explorer"), "星降る街の工房 - 01.srt")
    _folder, mp3s = _audiobook(tmp_path)
    _drop(win, [srt, mp3s[0]])
    assert wait_until(lambda: calls(writer, "insert_at"), 5)
    assert [c[2]["files"] for c in calls(writer, "insert_at")] == [[srt]]   # the subtitle alone, as before
    assert _asked(win).title.text() == strings.AUDIOBOOK_IN_TITLE.format(name="01.mp3")


def test_subtitles_alone_still_go_straight_to_the_writer_with_no_card(world, tmp_path):
    win, writer = world()
    srt = _subtitle(os.path.join(tmp_path, "Explorer"), "星降る街の工房 - 01.srt")
    _drop(win, [srt])
    assert [c[2]["files"] for c in calls(writer, "insert_at")] == [[srt]]   # at once: no worker in the way
    assert getattr(win.adder, "question", None) is None


def test_a_video_or_a_folder_without_audio_is_still_handed_on_and_named_as_left_out(world, tmp_path):
    """AD-4 unchanged for what isn't an audiobook: the writer gets it (and names it left out), no card."""
    win, writer = world()
    video = os.path.join(tmp_path, "Explorer", "第1話.mkv")
    os.makedirs(os.path.dirname(video))
    with open(video, "wb") as f:
        f.write(b"\x1aE\xdf\xa3")
    empty = os.path.join(tmp_path, "Explorer", "写真")
    os.makedirs(empty)
    _drop(win, [video, empty])
    assert wait_until(lambda: calls(writer, "insert_at"), 5)
    assert calls(writer, "insert_at")[0][2]["files"] == [video, empty]
    assert getattr(win.adder, "question", None) is None


def test_without_the_looks_an_audiobook_drop_goes_on_as_before(world, tmp_path):
    """No looks (a 2.x library): nothing reads a folder where it is — the drop is the writer's, as before."""
    win, writer = world(looks=False)
    win.looks = None
    _folder, mp3s = _audiobook(tmp_path)
    _drop(win, mp3s[:1])
    assert wait_until(lambda: calls(writer, "insert_at"), 5)
    assert getattr(win.adder, "question", None) is None


# --- + Add → Files… ------------------------------------------------------------------------------------------------- #
def test_files_picker_shows_audiobooks_and_a_picked_one_is_named_an_audiobook(world, tmp_path, monkeypatch):
    win, writer = world()
    first = strings.ADD_PICK_FILTER.split(";;")[0]               # the picker's default: audiobooks shown in it
    assert "*.m4b" in first and "*.mp3" in first and "audiobook" in first.split("(")[0].lower()
    folder, mp3s = _audiobook(tmp_path)
    monkeypatch.setattr(add_menu, "pick_files", lambda _parent: list(mp3s))
    win.adder.run("files")
    q = _asked(win)
    assert q.title.text() == strings.AUDIOBOOK_IN_TITLE.format(name=GINGA)
    q.yes.click()
    assert wait_until(lambda: win.looks.added, 5)
    assert [p for p, _t in win.looks.added] == [os.path.normpath(folder)] and calls(writer, "insert_at") == []


def test_the_cards_words_never_hint_at_a_subtitle():
    _no_subtitle_hint(strings.AUDIOBOOK_IN_TITLE, strings.AUDIOBOOK_IN_TITLE_N, strings.AUDIOBOOK_IN_BODY,
                      strings.AUDIOBOOK_IN_YES, strings.AUDIOBOOK_IN_YES_TIP, WS.FILE_AUDIOBOOK,
                      WS.AUDIOBOOK_ITS_FOLDER_TIP)


# --- setup: *Choose a file…* --------------------------------------------------------------------------------------- #
def test_setup_names_an_audiobook_and_offers_its_folder(qapp, tmp_path):
    from app.qt import wizard as W
    from tests.qt import test_wizard as T
    shell = T.FakeShell(T.FakeSettings({}))
    wiz = W.SetupWizard(shell, parent=shell.centralWidget(), api=T.FakeApi(), miner=T.FakeMiner(T.miner_look("missing")))
    wiz.can_add = lambda name: True
    try:
        T.go_to(wiz, "shows")
        folder, mp3s = _audiobook(tmp_path)
        wiz.pick_files_dialog = lambda title, start: [mp3s[0]]
        wiz.pick_files()
        page = wiz.pages[2]
        line = page.refused_line.text()
        assert line == WS.FILE_AUDIOBOOK.format(name="01.mp3") and line != WS.FILE_NOT_READ.format(name="01.mp3")
        _no_subtitle_hint(line)
        assert not page.btn_its_folder.isHidden() and page._its_folder == os.path.normpath(folder)
        assert page.btn_its_folder.toolTip() == WS.AUDIOBOOK_ITS_FOLDER_TIP
        page.btn_its_folder.click()
        assert wait_until(lambda: page.has_folder(os.path.normpath(folder)), 5)
        wiz.pick_files_dialog = lambda title, start: [os.path.join(str(tmp_path), "第1話.mkv")]
        page.offer_folder(str(tmp_path))                          # a video's offer after it: the video's own tip back
        assert page.btn_its_folder.toolTip() == WS.VIDEO_ITS_FOLDER_TIP
    finally:
        wiz.close()
        shell.close()
