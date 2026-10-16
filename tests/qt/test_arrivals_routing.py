"""New arrivals' routing, end to end (W3.2 B; the RUNBOOK's *Routing* row, §5a IK-6 / IK-9, followups IK0-5; Sonic's
W3.2-2): on a real 3.0 store (`arrivals_on`), the open window's reader woken by the store's bell and the tree watch
(`shell.library_lookout`), the window's writer, and the YouTube downloader's `on_complete` (`windows.youtube_arrivals`).

What a wrong answer would cost a learner:
  * hato's episode (or one he dropped in hato's folder) sitting unseen until the window is reopened — or seen only
    because the window looks at the store ten times a second all day (L3.1-4: the bell, with the slow look as the
    fallback);
  * an episode he copied into a show's folder by hand waiting in New arrivals instead of joining its show (D28, IK-9);
  * a YouTube download that never reaches the library (left in Processed, which no sync walks), placed where he set no
    rule, or placed by the YouTube rule when his rule for that channel says otherwise;
  * a download written to a store that can't be saved, then lost without a word.

Real Japanese / Chinese names: the store's library from tests/Test Resources (`names`), the downloads named the same.
"""
import os
import threading
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QApplication

from app import library_store as ls
from app import library_watch, settings_manager
from app.qt import bridge, shell, strings, windows
from app.services import library_reader
from app.services import moves as moves_module
from tests.qt.conftest import wait_until
from tests.test_library_store_support import migrated, names, roots
from tests.test_services_moves import LockHolder, short_lock_wait  # noqa: F401  (the fixture, by name)

pytestmark = pytest.mark.skipif(not library_watch.watchable(), reason="the bell and the tree watch are Windows'")


# --- helpers ------------------------------------------------------------------------------------------------------ #
def _download(data_dir, name, channel, video, folder="Processed", language="ja"):
    """A transcript as the YouTube downloader writes it (its header, its cue sidecar), with real text."""
    words = names(language)
    path = os.path.join(data_dir, *folder.split("/"), f"{channel} - {name} [{video}].txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"{name}\n{channel} | 2026-10-14 | 12:34\nCaptions: {language} (manual)\nhttps://www.youtube.com/watch"
                f"?v={video}\n\n------------------------------------------------------------\n\n"
                + " ".join(words[:15]) + "\n")
    with open(os.path.splitext(path)[0] + ".surasura.json", "w", encoding="utf-8") as f:
        f.write('{"video_id": "%s", "url": "https://www.youtube.com/watch?v=%s", "title": "%s", "cues": []}'
                % (video, video, name))
    return path


def _episode(data_dir, rel, text):
    path = os.path.join(data_dir, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)                              # whole, as a copy lands (the watch skips .part names)
    return path


def _arrival_ids(view):
    return {i for a in (view.arrivals if view is not None else ()) for i in a.item_ids}


def _current_ids(view):
    return {e.id for r in (view.rows if view is not None else ()) for e in r.episodes}


def _item(store, data_dir, path):
    return store.item_id(ls.library_rel(data_dir, path))


@pytest.fixture
def real(qapp):
    """The window on a real migrated 3.0 store: the reader on the bell and the watch, the writer beside it."""
    made = []

    def make(language="ja", rules=None, watch=True):
        store = migrated(language)                     # the outside writer's handle (hato, another program)
        store.set_library_options(arrivals_on=True)
        settings_manager.save_keys({"target_language": language})      # the window's language is its library's (P0)
        if rules is not None:
            settings_manager.save_keys({"placing_rules": rules})
        opener = moves_module.store_opener(language)
        reader = library_reader.LibraryReader(opener, language, watch=shell.library_lookout if watch else None)
        writer = moves_module.Writer(opener, language, journal_file=moves_module.journal_path(language),
                                     words=strings.MOVE_WORDS, retry=0.05)
        services = shell.Services(library=reader, writer=writer)
        win = shell.open_window(qapp, services)
        win.resize(1280, 900)
        win.show()
        page = win.page_widgets["current"]
        assert wait_until(lambda: page.view_model is not None and page.view_model.state == "full", 15)
        if watch:
            assert wait_until(lambda: reader._lookout is not None and reader.syncs >= 1, 10)   # the open's sync
        made.append((win, services, store))
        return SimpleNamespace(store=store, win=win, reader=reader, writer=writer, page=page, language=language,
                               data_dir=roots(language)[0])
    yield make
    for win, services, store in made:
        win.close()
        services.shutdown(2.0)
        store.close()


class FakeShell(QObject):
    """The main window as `youtube_arrivals` reads it: its services (the writer, the settings) and its bottom bar."""

    def __init__(self, writer, rules=None):
        super().__init__()
        self.services = SimpleNamespace(writer=writer, settings=SimpleNamespace(get=lambda: {"placing_rules": rules or {}}))
        self.lines = []
        self.bar_line = SimpleNamespace(set_full=self.lines.append)


# --- the bell (IK0-5) ---------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_hatos_register_from_another_handle_shows_in_the_open_windows_new_arrivals_within_half_a_second(real, language):
    """hato's hand-off (another program's handle) commits; the bell wakes the reader; the window's view holds the
    arrival within 0.5 s (RD-G5). The file sits where no watch looks: only the bell can have told the window."""
    lib = real(language)
    assert not lib.reader._lookout.deaf                # the bell is live: nothing polls
    words = names(language)
    path = _download(lib.data_dir, words[5], words[6], "Hato0000001", language=language)
    record = {"schema": 1, "producer": "hato", "content_key": "v1-" + "ab" * 32, "show": {"title": words[6],
                                                                                           "episode": 1}}
    lib.store.register(path, record)
    t0 = time.perf_counter()
    item = _item(lib.store, lib.data_dir, path)
    assert lib.store.place_of(item)[0] == "arrivals"
    assert wait_until(lambda: item in _arrival_ids(lib.page.view_model), 2)
    took = time.perf_counter() - t0
    print(f"hato's register -> the window's New arrivals: {took * 1000:.0f} ms")
    assert took <= 0.5


def test_with_the_bell_live_an_idle_window_never_looks_every_tenth_of_a_second(real):
    """Idle and watched, the reader sleeps on the bell (a look or two for its own retries), where the poll looked ten
    times a second; a commit still wakes it at once."""
    lib = real()
    time.sleep(0.6)                                    # the open's sync, the cache's quiet look
    QApplication.processEvents()
    before = lib.reader.looks
    t_end = time.monotonic() + 1.0
    while time.monotonic() < t_end:
        QApplication.processEvents()
        time.sleep(0.02)
    idle = lib.reader.looks - before
    print(f"looks in an idle second: watched {idle}")
    assert idle <= 2

    poll = library_reader.LibraryReader(moves_module.store_opener("ja"), "ja").start()   # no watch: the old poll
    try:
        assert wait_until(lambda: poll.view() is not None, 10)
        time.sleep(0.3)
        start = poll.looks
        time.sleep(1.0)
        assert poll.looks - start >= 5                 # what the bell saves
    finally:
        poll.stop()
    goal = lib.store.ids("goal")
    lib.store.move([goal[-1]], "goal", before_id=goal[0])                        # another program's move
    assert wait_until(lambda: lib.page.view_model.rows is not None and
                      lib.reader.view().rows is not None and lib.reader.looks > before + idle, 1)


def test_the_reader_closes_its_watch_and_its_bell_when_it_stops(real):
    lib = real()
    lookout = lib.reader._lookout
    bell = lookout.bell
    assert bell.slot is not None and lookout.tree.alive
    lib.reader.stop()
    assert lib.reader._lookout is None and bell.slot is None and not lookout.tree.alive
    assert lib.reader._syncer is None


# --- the tree watch: hato's drop folder, a hand copy (IK-9, D28) --------------------------------------------------- #
def test_a_file_dropped_in_hatos_drop_folder_lands_in_new_arrivals_and_shows_in_the_open_window(real):
    lib = real()
    words = names("ja")
    t0 = time.perf_counter()
    path = _episode(lib.data_dir, f"{ls.HATO_FOLDER}/{words[7]} 第01話.srt",
                    f"1\n00:00:01,000 --> 00:00:03,000\n{words[7]}\n")

    def shown():
        item = _item(lib.store, lib.data_dir, path)
        return item is not None and item in _arrival_ids(lib.page.view_model)
    assert wait_until(shown, 5)
    print(f"a file in hato folder -> the window's New arrivals: {(time.perf_counter() - t0) * 1000:.0f} ms "
          f"(the watch's settle {library_watch.SETTLE_S * 1000:.0f} ms included)")
    assert lib.store.place_of(_item(lib.store, lib.data_dir, path))[0] == "arrivals"


def test_a_drop_the_watch_reports_while_the_store_is_busy_is_synced_once_the_store_frees(real, short_lock_wait):
    """Another program holds the store when the watch reports hato's drop: the sync keeps it owed and tries again —
    the drop is never forgotten until the next report."""
    lib = real()
    words = names("ja")
    holder = LockHolder(lib.store.db_path)
    try:
        path = _episode(lib.data_dir, f"{ls.HATO_FOLDER}/{words[18]} 第02話.srt",
                        f"1\n00:00:01,000 --> 00:00:03,000\n{words[18]}\n")
        time.sleep(library_watch.SETTLE_S + 0.6)          # reported, settled, tried against the held store
        assert _item(lib.store, lib.data_dir, path) is None
    finally:
        holder.release()
    assert wait_until(lambda: _item(lib.store, lib.data_dir, path) in _arrival_ids(lib.page.view_model), 5)


def test_a_file_copied_by_hand_into_a_shows_folder_in_current_joins_its_show_never_new_arrivals(real):
    lib = real()
    show_items = [i for i in lib.store.ids("now") if "/" in lib.store.item(i)["rel_path"][len("HighPriority/"):]]
    last = show_items[-1]
    folder = os.path.dirname(lib.store.item(last)["rel_path"])
    show = folder.rsplit("/", 1)[-1]
    path = _episode(lib.data_dir, f"{folder}/{show}_第05話.srt", f"1\n00:00:01,000 --> 00:00:03,000\n{show} 5\n")

    def joined():
        item = _item(lib.store, lib.data_dir, path)
        return item is not None and item in _current_ids(lib.page.view_model)
    assert wait_until(joined, 5)
    item = _item(lib.store, lib.data_dir, path)
    assert item not in _arrival_ids(lib.page.view_model)
    tier = lib.store.place_of(item)[0]
    order = lib.store.ids(tier)
    assert order.index(item) == (order.index(last) + 1 if last in order else 0)    # right after its show's last


# --- YouTube's downloads (Sonic's W3.2-2) ------------------------------------------------------------------------- #
def test_youtube_record_reads_the_sidecar_and_the_header_and_bilibili_names_no_channel(tmp_path):
    words = names("zh")
    path = _download(str(tmp_path), words[3], words[4], "Zx9_-Ab3CdE", language="zh")
    rec = windows.youtube_record(path, "zh")
    assert rec["producer"] == "youtube" and rec["content_key"] == "youtube:Zx9_-Ab3CdE"
    assert rec["channel_id"] == words[4] and rec["show"] == {"title": words[4]} and rec["title"] == words[3]
    assert rec["media_type"] == "youtube" and rec["url"].endswith("Zx9_-Ab3CdE")
    bili = tmp_path / f"{words[5]} [bilibili-4791234].txt"
    bili.write_text(f"{words[5]}\nUnknown | 2026-10-14 | 23:40\n\n{words[6]}\n", encoding="utf-8")
    rec = windows.youtube_record(str(bili), "zh")
    assert rec["content_key"] == "bilibili:4791234" and "channel_id" not in rec and "show" not in rec


def test_youtubes_on_complete_registers_both_files_as_youtube_with_their_channel_and_says_they_wait(real):
    """The door's `on_complete` with two created files: both through the writer (not this thread's store), producer
    `youtube` with the channel the header names, waiting in New arrivals (no rule); the window shows them and the
    bottom bar says where they went."""
    lib = real()
    words = names("ja")
    a = _download(lib.data_dir, words[8], words[9], "AbCdEfGhIj1")
    b = _download(lib.data_dir, words[10], words[9], "AbCdEfGhIj2")
    called_on = []
    real_register = lib.writer.register

    def register(*args, **kw):
        called_on.append(threading.current_thread() is threading.main_thread())
        return real_register(*args, **kw)
    lib.writer.register = register
    complete = windows.youtube_arrivals(lib.win)
    complete([a, b])
    ids = lambda: {_item(lib.store, lib.data_dir, p) for p in (a, b)}            # noqa: E731
    assert wait_until(lambda: None not in ids() and ids() <= _arrival_ids(lib.page.view_model), 5)
    from app.connect import library
    records = [library.pairing_of(lib.store, i) for i in ids()]
    assert {(r["producer"], r["channel_id"]) for r in records} == {("youtube", words[9])}
    assert called_on == [True]                         # one call on the window's thread: the writer does the rest
    assert wait_until(lambda: lib.win.bar_line.full() == strings.YT_ARRIVED_WAITING.format(
        what=strings.yt_transcripts(2)), 3)
    assert len({lib.store.item(i)["work_id"] for i in ids()}) == 1                 # one channel: one title


def test_a_youtube_rule_and_a_channels_rule_place_downloads_through_the_door(real):
    """`youtube` → Finished, `youtube:<channel>` → the top of Current (beating `youtube`), read from the user's
    settings; the line says they were placed."""
    words = names("ja")
    lib = real(rules={"youtube": "finished", f"youtube:{words[12]}": "top"})
    plain = _download(lib.data_dir, words[11], words[11], "PlainVideo1")
    chan = _download(lib.data_dir, words[13], words[12], "ChanVideo01")
    windows.youtube_arrivals(lib.win)([plain, chan])
    assert wait_until(lambda: None not in (_item(lib.store, lib.data_dir, plain), _item(lib.store, lib.data_dir, chan)),
                      5)
    assert lib.store.place_of(_item(lib.store, lib.data_dir, plain))[0] == "graduated"
    assert lib.store.ids("now")[0] == _item(lib.store, lib.data_dir, chan)
    assert wait_until(lambda: lib.win.bar_line.full() == strings.YT_ARRIVED_PLACED.format(
        what=strings.yt_transcripts(2)), 3)


def test_the_downloaders_window_hands_its_files_to_new_arrivals_and_its_done_line_names_the_tray(real):
    """The real door (`_open_downloader`): its run's `on_complete` registers what it made; its own status line says
    they're in New arrivals once they land."""
    pytest.importorskip("modules.youtube_downloader.qt_window")
    lib = real()
    words = names("ja")
    a = _download(lib.data_dir, words[14], words[15], "DoorVideo01")
    dl = windows._open_downloader(lib.win)
    assert dl.on_complete is not None
    relay = bridge.Relay(parent=lib.win)
    dl._write = False                                  # as its run sets it (`_start`)
    dl._ended(relay, ("download", [a], None, False, dl.on_complete))
    assert wait_until(lambda: dl.status.text() == strings.YT_ARRIVED_WAITING.format(what=strings.yt_transcripts(1)),
                      5)
    assert lib.store.place_of(_item(lib.store, lib.data_dir, a))[0] == "arrivals"
    dl.close()


def test_without_a_writer_the_door_hands_nothing_and_the_files_wait_in_processed(qapp):
    """L1 N2: the door is always the callable (the downloader's window is kept and raised, so one opened before the
    library opens must still hand its files over); with no library open it says so and the files wait."""
    shell_ = FakeShell(None)
    complete = windows.youtube_arrivals(shell_)
    with pytest.raises(RuntimeError) as got:
        complete([os.path.join(roots("ja")[0], "Processed", "ぼっち・ざ・ろっく！ 第1話 [AbCdEfGhIj1].txt")])
    assert str(got.value) == strings.YT_NO_LIBRARY


def test_L1_N2_a_downloader_opened_before_the_library_hands_its_files_to_the_library_opened_since(real):
    words = names("ja")
    lib = real()
    shell_ = FakeShell(None)
    complete = windows.youtube_arrivals(shell_)          # made while no library was open
    shell_.services.writer = lib.writer                  # P0 opens the library after the first frame
    path = _download(lib.data_dir, words[90], words[91], "LateLibrary")
    complete([path])
    assert wait_until(lambda: _item(lib.store, lib.data_dir, path) in _arrival_ids(lib.page.view_model), 5)


def test_L1_S3_files_from_the_other_languages_processed_are_refused_with_the_words_and_never_queued(qapp):
    """The language switched mid-download: the files are under the old data/<lang>. Each record used to be refused
    on its own and only printed, while the downloader said *handed to your library*; now the hand-off fails at once
    and the downloader says why (they wait in the other library's Processed)."""
    writer = moves_module.Writer(moves_module.store_opener("ja"), "ja", journal_file=moves_module.journal_path("ja"),
                                 words=strings.MOVE_WORDS)
    words = names("zh")
    path = os.path.join(roots("zh")[0], "Processed", f"{words[3]} [Zx9_-Ab3CdE].txt")
    with pytest.raises(RuntimeError) as got:
        windows.youtube_arrivals(FakeShell(writer))([path])
    assert str(got.value) == strings.YT_OTHER_LIBRARY
    assert writer.pending() == 0


def test_L1_S3_the_done_line_says_how_many_werent_added():
    one, two = strings.yt_transcripts(1), strings.yt_transcripts(2)
    assert windows.arrived_line(2, 0, 0) == strings.YT_ARRIVED_WAITING.format(what=two)
    assert windows.arrived_line(1, 0, 1) == (strings.YT_ARRIVED_WAITING.format(what=one) + " · "
                                             + strings.YT_NOT_ADDED.format(what=one))
    assert windows.arrived_line(0, 0, 2) == strings.YT_NOT_ADDED.format(what=two)     # said even when none landed


def test_L1_N1_a_channel_whose_name_holds_a_bar_stays_whole_and_two_such_channels_stay_two_titles(tmp_path):
    def written(name, channel, video):                   # the downloader's file name holds no "|": the header does
        path = tmp_path / f"{name} [{video}].txt"
        path.write_text(f"{name}\n{channel} | 2026-10-14 | 12:34\nCaptions: ja (manual)\n\n{name}\n", encoding="utf-8")
        return str(path)
    a = written("日曜劇場 第1話", "TBS | 公式", "TbsVideo001")
    b = written("ニュース23", "TBS | NEWS", "TbsVideo002")
    ra, rb = windows.youtube_record(a, "ja"), windows.youtube_record(b, "ja")
    assert ra["channel_id"] == "TBS | 公式" and rb["channel_id"] == "TBS | NEWS"
    assert ra["show"] != rb["show"]


def test_L1_B2_two_downloads_into_one_channels_folder_both_reach_new_arrivals(real):
    """B2: from the second video of one channel the downloader writes into `Processed/<channel>/`, and a refreshed
    playlist into its old folder. The diff was top level only: the second batch was `[]`, *No new transcripts*, and
    its files stayed in Processed, which no sync walks. Now the new files are found at any depth."""
    view = pytest.importorskip("modules.youtube_downloader.downloader_view")
    lib = real()
    words = names("ja")
    channel = words[92]

    def fake(ks):
        def extract(urls, folder, lang, keep_timestamps, channel_first, log, should_stop):
            for k in ks:
                _download(lib.data_dir, words[k], channel, f"ChanVid{k:04d}", folder=f"Processed/{channel}")
        return extract
    complete = windows.youtube_arrivals(lib.win)
    run = lambda ks: view.run_extract(["https://youtu.be/dQw4w9WgXcQ"], "ja", "Japanese", True, True,  # noqa: E731
                                      lambda line: None, ensure=lambda log: True, extract=fake(ks))
    first = run((93, 94))
    assert len(first) == 2
    complete(first)
    second = run((95,))
    assert [os.path.basename(p) for p in second] == [f"{channel} - {words[95]} [ChanVid0095].txt"]
    complete(second)
    every = first + second
    assert wait_until(lambda: all(_item(lib.store, lib.data_dir, p) in _arrival_ids(lib.page.view_model)
                                  for p in every), 5)


def test_E4_a_read_only_store_refuses_the_downloads_and_says_they_wait_in_processed(qapp):
    store = migrated("ja")
    data_dir = roots("ja")[0]
    writer = moves_module.Writer(moves_module.store_opener("ja"), "ja", journal_file=moves_module.journal_path("ja"),
                                 words=strings.MOVE_WORDS)
    writer.start()
    try:
        store.close()
        ls.mark_damaged(ls.library_db_path("ja", data_dir), "test: a damaged store")
        assert wait_until(lambda: not writer.can_write(), moves_module.MODE_RECHECK_S * 3)
        words = names("ja")
        path = _download(data_dir, words[16], words[17], "ReadOnly001")
        complete = windows.youtube_arrivals(FakeShell(writer))
        with pytest.raises(RuntimeError) as got:
            complete([path])
        assert str(got.value) == strings.YT_READ_ONLY.format(reason="damaged")
        assert writer.pending() == 0
    finally:
        writer.finish(time.monotonic() + 2)
