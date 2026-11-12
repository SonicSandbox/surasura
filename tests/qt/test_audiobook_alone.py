"""An audiobook brought in alone (Kantan-B3; Mattias in #testers, 2026-11-12: he dropped his audiobook in without its
book, was told *Only text and subtitle files can be added* — "Ah, has to be srt then I guess"). Words PROVISIONAL.

What the window does now, at each door the learner may use:
  * dropped from Explorer (a file or its folder), or picked with + Add → *Files…*: listed on a worker (the bar's arc
    meanwhile); an audiobook by the look's own rule (`audiobooks.find`: 20 minutes or more, never beside a video) is
    never a file *left out*: one card names it, the folder its yes reads where it is (+ Add → *A folder…*), anything
    else read there with it, and where it shows; a subtitle or text dropped from that folder waits for the answer (Yes:
    it comes with the folder; No: added as before); anything else (a song, a video, a folder without one) goes on as
    before (AD-4); a folder that can't be read where it is (a whole drive, the user folder) is said, never offered;
  * setup's *Choose a file…*: audiobooks shown in its picker, the audiobook named and its folder offered (*Choose its
    folder*), never "reads subtitles, texts and EPUBs only".

What a wrong answer would cost a learner: the dead end he met (a subtitle file sounds needed for an audiobook), a
folder such as Downloads read and watched without his say (or without saying what else comes in), a folder listed on
the window's thread (a freeze), a song called an audiobook, or the subtitles he dropped beside it lost or added twice.

Real MP3 / M4B files (tests/test_audiobooks' builders: real tags and lengths), a real subtitle from tests/Test
Resources, made-up titles.
"""
import os
import threading

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QFileDialog

from app.qt import add_menu, strings
from app.qt import press as qpress
from app.qt import wizard_strings as WS
from tests import services_helpers as h
from tests.qt.conftest import wait_until
from tests.qt.test_drag import FakeWriter, _drop_files, calls, lst_of, open_window  # noqa: F401
from tests.test_audiobooks import _m4b, _mp3
from tests.fixtures import window_seed

GINGA = "銀河鉄道の夜"


class Looks:
    """The window's looks as + Add's *A folder…* calls them: each folder asked recorded."""

    def __init__(self):
        self.added = []
        self.on_result = self.on_progress = None

    def add(self, path, then=None, first=False):
        self.added.append(path)
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
def world(qapp, monkeypatch):
    made = []
    monkeypatch.setattr(add_menu, "_refused", lambda language, folder: None)   # (no store here: every folder can be)

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


def _audiobook(root, name=GINGA, n=3, seconds=3600, where="Audiobooks"):
    """A folder of `n` chapter MP3s of an audiobook (`seconds` in all), as a learner keeps one."""
    folder = os.path.join(str(root), where, name)
    return folder, [_mp3(os.path.join(folder, f"{i:02d}.mp3"), seconds=seconds / n,
                         frames={"TALB": name, "TRCK": str(i)}) for i in range(1, n + 1)]


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


def _inserted(writer):
    return [c[2]["files"] for c in calls(writer, "insert_at")]


# --- the drop ------------------------------------------------------------------------------------------------------- #
def test_an_audiobook_file_dropped_alone_is_named_an_audiobook_never_left_out(world, tmp_path):
    win, writer = world()
    m4b = _m4b(os.path.join(tmp_path, "Downloads", f"{GINGA}.m4b"), 3600, tags={"album": GINGA})
    _drop(win, [m4b])
    q = _asked(win)
    assert q.title.text() == strings.AUDIOBOOK_IN_TITLE.format(name=GINGA)      # its own title, from its tags
    assert q.body.text() == strings.AUDIOBOOK_IN_BODY.format(folders="「Downloads」")   # the folder, named first
    assert "New arrivals" in q.body.text() and "Needs you" in q.body.text()
    _no_subtitle_hint(q.title.text(), q.body.text(), win.bar_line.full())
    assert _inserted(writer) == []                               # nothing handed to the writer: no "left out" note
    assert win.looks.added == []                                 # nothing read before his yes


def test_read_its_folder_reads_the_audiobooks_folder_where_it_is_once(world, tmp_path):
    win, writer = world()
    folder, mp3s = _audiobook(tmp_path)
    _drop(win, mp3s)
    q = _asked(win)
    assert q.title.text() == strings.AUDIOBOOK_IN_TITLE.format(name=GINGA)
    assert q.yes.text() == strings.AUDIOBOOK_IN_YES and q.yes.toolTip() == strings.AUDIOBOOK_IN_YES_TIP
    q.yes.click()
    assert wait_until(lambda: win.looks.added, 5)
    assert win.looks.added == [os.path.normpath(folder)]         # one folder, read once (three files dropped)
    assert _inserted(writer) == [] and win.adder.question is None


def test_cancel_reads_nothing(world, tmp_path):
    win, writer = world()
    _folder, mp3s = _audiobook(tmp_path)
    _drop(win, mp3s[:1])
    _asked(win).no.click()
    assert win.looks.added == [] and _inserted(writer) == []


def test_a_dropped_folder_holding_an_audiobook_is_listed_off_the_windows_thread_with_the_bars_arc(world, tmp_path,
                                                                                                  monkeypatch):
    win, writer = world()
    folder, _mp3s = _audiobook(tmp_path)
    main, listed, gate = threading.main_thread(), [], threading.Event()
    real = add_menu.audiobook_folders

    def spy(paths, language=None):
        listed.append(threading.current_thread() is main)
        gate.wait(5)
        return real(paths, language)
    monkeypatch.setattr(add_menu, "audiobook_folders", spy)
    _drop(win, [folder])
    key = ("audiobooks", (os.path.normpath(folder),))
    assert wait_until(lambda: listed, 5) and qpress.live(win, key)     # the press shows at once, while it is listed
    gate.set()
    q = _asked(win)
    assert listed == [False]                                     # its listing on a worker, never the window's thread
    assert q.title.text() == strings.AUDIOBOOK_IN_TITLE.format(name=GINGA)
    q.yes.click()
    assert wait_until(lambda: win.looks.added, 5)
    assert win.looks.added == [os.path.normpath(folder)] and _inserted(writer) == []


def test_a_disc_folder_inside_the_dropped_folder_counts(world, tmp_path):
    win, _writer = world()
    top = os.path.join(tmp_path, GINGA)
    _mp3(os.path.join(top, "Disc 1", "01.mp3"), seconds=2400, frames={"TALB": GINGA})
    _drop(win, [top])
    assert _asked(win).title.text() == strings.AUDIOBOOK_IN_TITLE.format(name=GINGA)


def test_subtitles_dropped_from_elsewhere_beside_an_audiobook_are_added_as_before(world, tmp_path):
    win, writer = world()
    srt = _subtitle(os.path.join(tmp_path, "Explorer"), "星降る街の工房 - 01.srt")
    _folder, mp3s = _audiobook(tmp_path)
    _drop(win, [srt, mp3s[0]])
    assert wait_until(lambda: calls(writer, "insert_at"), 5)
    assert _inserted(writer) == [[srt]]                          # the subtitle alone, as before
    assert _asked(win).title.text() == strings.AUDIOBOOK_IN_TITLE.format(name=GINGA)   # (one chapter: its audiobook)


def test_a_subtitle_from_the_audiobooks_own_folder_waits_for_the_answer(world, tmp_path):
    """The folder read where it is brings the subtitle too: never copied in AND read (twice). A No adds it as before;
    the card says what else comes in with the folder."""
    win, writer = world()
    folder, mp3s = _audiobook(tmp_path)
    srt = _subtitle(folder, "銀河鉄道の夜 - 字幕.srt")
    _drop(win, [srt, mp3s[0]])
    q = _asked(win)
    assert strings.AUDIOBOOK_IN_OTHERS.format(folders=f"「{GINGA}」") in q.body.text()
    assert _inserted(writer) == []
    q.yes.click()
    assert wait_until(lambda: win.looks.added, 5)
    assert win.looks.added == [os.path.normpath(folder)] and _inserted(writer) == []
    _drop(win, [srt, mp3s[0]])
    _asked(win).no.click()
    assert wait_until(lambda: calls(writer, "insert_at"), 5)
    assert _inserted(writer) == [[os.path.normpath(srt)]] and win.looks.added == [os.path.normpath(folder)]


def test_subtitles_alone_still_go_straight_to_the_writer_with_no_card(world, tmp_path):
    win, writer = world()
    srt = _subtitle(os.path.join(tmp_path, "Explorer"), "星降る街の工房 - 01.srt")
    _drop(win, [srt])
    assert _inserted(writer) == [[srt]]                          # at once: no worker in the way
    assert getattr(win.adder, "question", None) is None


def test_a_song_a_video_or_a_folder_without_an_audiobook_go_on_as_before(world, tmp_path):
    """AD-4 unchanged for what isn't an audiobook: a three-minute song (under the look's 20 minutes), a show folder
    whose audio sits beside its video, a video, an empty folder — the writer gets them (and names them left out)."""
    win, writer = world()
    song = _mp3(os.path.join(tmp_path, "Music", "オープニング.mp3"), seconds=180, frames={"TALB": "OST"})
    show = os.path.join(tmp_path, "Anime", "星降る街の工房")
    _mp3(os.path.join(show, "condensed 01.mp3"), seconds=1500, frames={"TALB": "星降る街の工房"})
    os.makedirs(show, exist_ok=True)
    video = os.path.join(show, "星降る街の工房 - 01.mkv")
    with open(video, "wb") as f:
        f.write(b"\x1aE\xdf\xa3" + b"\0" * (2 << 20))
    empty = os.path.join(tmp_path, "Explorer", "写真")
    os.makedirs(empty)
    _drop(win, [song, show, video, empty])
    assert wait_until(lambda: calls(writer, "insert_at"), 5)
    assert _inserted(writer) == [[os.path.normpath(p) for p in (song, show, video, empty)]]
    assert getattr(win.adder, "question", None) is None


def test_audio_deeper_than_the_look_into_a_dropped_folder_is_not_an_audiobook_of_it(tmp_path):
    deep = os.path.join(tmp_path, "a", "b", "c", "d", "e")
    _mp3(os.path.join(deep, "01.mp3"), seconds=2400, frames={"TALB": GINGA})
    found, rest, held = add_menu.audiobook_folders([os.path.join(tmp_path, "a")])
    assert found == [] and rest == [os.path.join(tmp_path, "a")] and held == []
    found, _rest, _held = add_menu.audiobook_folders([os.path.join(tmp_path, "a", "b", "c")])
    assert [f["name"] for f in found] == [GINGA]


def test_a_folder_that_cant_be_read_where_it_is_is_said_never_offered(world, tmp_path, monkeypatch):
    """A whole drive or the user folder (the store's own rule): the card would offer what + Add → A folder… refuses."""
    win, writer = world()
    why = "A whole drive holds too much to read; choose the folder your shows and books are in."
    monkeypatch.setattr(add_menu, "_refused", lambda language, folder: why)
    m4b = _m4b(os.path.join(tmp_path, f"{GINGA}.m4b"), 3600, tags={"album": GINGA})
    _drop(win, [m4b])
    assert wait_until(lambda: win.bar_line.full() == strings.AUDIOBOOK_IN_REFUSED.format(name=GINGA, why=why), 5)
    assert getattr(win.adder, "question", None) is None and win.looks.added == [] and _inserted(writer) == []


def test_a_listing_that_fails_says_so_and_never_leaves_the_audio_out_as_a_text(world, tmp_path, monkeypatch):
    win, writer = world()
    srt = _subtitle(os.path.join(tmp_path, "Explorer"), "星降る街の工房 - 01.srt")
    m4b = _m4b(os.path.join(tmp_path, "Downloads", f"{GINGA}.m4b"), 3600, tags={"album": GINGA})

    def broken(paths, language=None):
        raise PermissionError("access denied")
    monkeypatch.setattr(add_menu, "audiobook_folders", broken)
    _drop(win, [srt, m4b])
    assert wait_until(lambda: calls(writer, "insert_at"), 5)
    assert _inserted(writer) == [[os.path.normpath(srt)]]        # the subtitle as before; the audio never "left out"
    assert wait_until(lambda: win.bar_line.full().startswith(f"{GINGA}.m4b couldn't be read"), 5)


def test_a_second_cards_question_stays_when_the_first_is_answered(world, tmp_path):
    win, _writer = world()
    _folder, mp3s = _audiobook(tmp_path)
    m4b = _m4b(os.path.join(tmp_path, "Downloads", "坊っちゃん.m4b"), 3600, tags={"album": "坊っちゃん"})
    first = win.adder.ask_audiobooks([{"folder": os.path.dirname(mp3s[0]), "name": GINGA, "n": 1, "others": False}])
    second = win.adder.ask_audiobooks([{"folder": os.path.dirname(m4b), "name": "坊っちゃん", "n": 1, "others": False}])
    first._answer(False)
    assert win.adder.question is second
    second._answer(False)
    assert win.adder.question is None


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
    from app import audiobooks
    win, writer = world()
    first = strings.ADD_PICK_FILTER.split(";;")[0]               # the picker's default: audiobooks shown in it
    assert all(f"*{ext}" in first for ext in audiobooks.AUDIO_EXTENSIONS)
    assert "audiobook" in first.split("(")[0].lower()
    folder, mp3s = _audiobook(tmp_path)
    monkeypatch.setattr(add_menu, "pick_files", lambda _parent: list(mp3s))
    win.adder.run("files")
    q = _asked(win)
    assert q.title.text() == strings.AUDIOBOOK_IN_TITLE.format(name=GINGA)
    q.yes.click()
    assert wait_until(lambda: win.looks.added, 5)
    assert win.looks.added == [os.path.normpath(folder)] and _inserted(writer) == []


def test_the_cards_words_never_hint_at_a_subtitle():
    _no_subtitle_hint(strings.AUDIOBOOK_IN_TITLE, strings.AUDIOBOOK_IN_TITLE_N, strings.AUDIOBOOK_IN_BODY,
                      strings.AUDIOBOOK_IN_BODY_N, strings.AUDIOBOOK_IN_YES, strings.AUDIOBOOK_IN_YES_N,
                      strings.AUDIOBOOK_IN_YES_TIP, strings.AUDIOBOOK_IN_REFUSED, WS.FILE_AUDIOBOOK,
                      WS.FILE_AUDIOBOOK_PLAIN, WS.AUDIOBOOK_ITS_FOLDER_TIP)


# --- setup: *Choose a file…* --------------------------------------------------------------------------------------- #
def test_setup_names_an_audiobook_and_offers_its_folder(qapp, tmp_path, monkeypatch):
    from app import audiobooks
    from app.qt import wizard as W
    from tests.qt import test_wizard as T
    shell = T.FakeShell(T.FakeSettings({}))
    wiz = W.SetupWizard(shell, parent=shell.centralWidget(), api=T.FakeApi(),
                        miner=T.FakeMiner(T.miner_look("missing")))
    wiz.can_add = lambda name: True
    wiz.api.read_folders = lambda *_a, **_k: None                # (the services read folders: its folder offered)
    try:
        T.go_to(wiz, "shows")
        filters = []
        monkeypatch.setattr(QFileDialog, "getOpenFileNames",
                            staticmethod(lambda parent, title, start, filt: (filters.append(filt), ([], ""))[1]))
        wiz._pick_files_dialog(WS.PICK_FILE_TITLE, str(tmp_path))
        assert all(f"*{ext}" in filters[0].split(";;")[0] for ext in audiobooks.AUDIO_EXTENSIONS)
        assert "audiobook" in WS.PICK_FILE_TIP
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
        page.offer_folder(str(tmp_path))                          # a video's offer after it: the video's own tip back
        assert page.btn_its_folder.toolTip() == WS.VIDEO_ITS_FOLDER_TIP
        wiz.api.read_folders = None                               # no folder read where it is: said, nothing offered
        page.refuse(None)
        wiz.pick_files_dialog = lambda title, start: [mp3s[1]]
        wiz.pick_files()
        assert page.refused_line.text() == WS.FILE_AUDIOBOOK_PLAIN.format(name="02.mp3")
        assert page.btn_its_folder.isHidden()
    finally:
        wiz.close()
        shell.close()
