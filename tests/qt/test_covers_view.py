"""Covers in the window (W3.2 Q6): `app/qt/covers.py`, its wiring into the rows (`rows.cover` / `rows.art`, the opened
row's standing cover), Goal's dock, the shell (no decode before the first frame, the disk scan once per open) and
*Change cover…* (*Choose an image…*, *Use a generated cover*), offscreen.

What a wrong answer would cost a learner:
  * the poster beside his show's files never shown — the list stays a wall of gradients he can't scan by eye;
  * a broken or vanished image painted as a hole (or an error) instead of the generated cover;
  * the window stuttering at its first frame or while scrolling because covers decode on its thread, or decoding the
    same picture again and again (a laptop's battery), or covers growing memory without end at 200 %;
  * a picture landing repainting the whole list (S19: only what shows that title);
  * the image he chose lost when he chooses another (no dated backup), or no way to take the choice back (Undo).

Real data: the shows are named with real Japanese and Chinese words (tests/Test Resources), the images are real PNG /
JPEG bytes, the stores real migrated ones where anything is written (the writer's commands, the scan).
"""
import os
import threading
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from app import library_store as ls
from app import path_utils, settings_manager
from app.qt import covers as qcovers
from app.qt import rows, shell, stones, strings
from app.services import library_reader
from app.services import moves as moves_module
from app.services import view_rows
from tests.fixtures import window_seed
from tests.qt.conftest import wait_until
from tests.qt.pixels import rgb_array
from tests.test_library_store_support import migrated, roots
from tests.test_services_covers import jpeg, png, write

ROSE = (200, 60, 90)                    # the test poster's one colour


@pytest.fixture(autouse=True)
def _covers_state(qapp):
    """Each test starts with nothing held, no window's hold, the decode count at 0 (and the stones' sheet drawn, as
    test_current's, so no sheet landing shifts a render count)."""
    qcovers.clear()
    qcovers.use_library("ja")                                   # the data folder the test root's (not a window's before)
    qcovers.decodes[0] = 0
    key = stones._key(1.0, "M")
    if key not in stones._SHEETS:
        stones._landed(key, stones.build(*key))
    yield
    qcovers.stop_scan()
    qcovers.clear()
    qcovers.use_library("ja")


def settle(n=20):
    for _ in range(n):
        QApplication.processEvents()


def ref_of(work_id, rel=None, source="file", path=None, locked=False):
    return view_rows.CoverRef(work_id, source, rel, path, locked)


def poster(language, rel, data=None):
    """A poster written in the data folder at `rel` (data-folder relative)."""
    return write(os.path.join(path_utils.get_data_path(language), *rel.split("/")),
                 data if data is not None else png(40, 60, ROSE))


def landed(ref, w, h, dpr=1.0, shape="row", timeout=5):
    """Ask for `ref`'s picture and wait until it is held (or the decode gave up)."""
    qcovers.decoded(ref, w, h, dpr, shape)
    key = qcovers._key(ref, shape, w, h, dpr)
    assert wait_until(lambda: key not in qcovers._running, timeout)
    return qcovers.decoded(ref, w, h, dpr, shape)


def centre(pix):
    arr = rgb_array(pix)
    return tuple(int(v) for v in arr[arr.shape[0] // 2, arr.shape[1] // 2])


def near(a, b, tol=6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


# --- the decoder ---------------------------------------------------------------------------------------------------- #
def test_a_poster_beside_the_files_is_decoded_off_the_window_thread_and_painted(qapp):
    rel = "HighPriority/進撃の巨人/poster.png"
    poster("ja", rel)
    seen = []
    real_decode = qcovers.decode

    def spy(*args):
        seen.append(threading.current_thread() is threading.main_thread())
        return real_decode(*args)
    qcovers.decode, saved = spy, real_decode
    try:
        pix = landed(ref_of(7, rel), 44, 63)
    finally:
        qcovers.decode = saved
    assert seen == [False]                                      # decoded on a worker, never the window's thread
    assert pix is not None and (pix.width(), pix.height()) == (44, 63)
    assert near(centre(pix), ROSE)


def test_a_current_rows_art_is_its_poster_as_a_strip_faded_out_at_its_right(qapp):
    rel = "HighPriority/ダンジョン飯/poster.png"
    poster("ja", rel)
    pix = landed(ref_of(8, rel), 120, 60, 1.0, "art")
    assert pix is not None and (pix.width(), pix.height()) == (120, 60)
    img = pix.toImage()
    left, right = img.pixelColor(10, 30), img.pixelColor(119, 30)
    assert near((left.red(), left.green(), left.blue()), ROSE) and left.alpha() == 255     # opaque for its first part
    assert right.alpha() < 10                                                            # gone at its right edge


def test_without_a_picture_the_generated_cover_comes_at_once_and_nothing_is_decoded(qapp):
    title = "鋼の錬金術師"
    for ref in (None, ref_of(3, source="generated"), ref_of(3, source="file", rel=None)):
        assert qcovers.decoded(ref, 44, 63, 1.0) is None
        assert qcovers.pixmap_for(ref, title, 44, 63, 1.0) is rows.cover(title, 44, 63, 1.0)
    assert qcovers.pixmap_for(None, title, 120, 60, 1.0, "art") is rows.art(title, 120, 60, 1.0)
    settle()
    assert qcovers.decodes[0] == 0 and not qcovers._running


@pytest.mark.parametrize("what", ["text renamed .jpg", "truncated jpeg", "vanished"])
def test_a_broken_or_vanished_image_gives_the_generated_cover_quietly_and_is_not_tried_again(qapp, what):
    rel = "HighPriority/呪術廻戦/poster.jpg"
    if what == "text renamed .jpg":
        poster("ja", rel, "呪術廻戦 第1話\n".encode("utf-8") * 8)
    elif what == "truncated jpeg":
        poster("ja", rel, jpeg(32, 48)[:-40])
    ref = ref_of(11, rel)
    heard = []
    qcovers.notifier().ready.connect(heard.append)
    try:
        assert landed(ref, 44, 63) is None
        assert qcovers.pixmap_for(ref, "呪術廻戦", 44, 63, 1.0) is rows.cover("呪術廻戦", 44, 63, 1.0)
        settle()
        assert qcovers.decodes[0] == 1 and heard == []          # no repaint for nothing, never asked again
    finally:
        qcovers.notifier().ready.disconnect(heard.append)


def test_one_decode_per_work_shape_size_and_ratio(qapp):
    rel = "HighPriority/葬送のフリーレン/cover.png"
    poster("ja", rel)
    ref = ref_of(5, rel)
    for _ in range(3):                                          # asked while it runs: it waits for the same answer
        assert qcovers.decoded(ref, 44, 63, 1.0) is None
    assert landed(ref, 44, 63) is not None
    for _ in range(3):
        assert qcovers.decoded(ref, 44, 63, 1.0) is not None
    assert qcovers.decodes[0] == 1
    assert landed(ref, 44, 63, 2.0) is not None                 # another ratio is another picture
    assert landed(ref, 44, 63, 1.0, "tile") is not None         # another shape too
    assert qcovers.decodes[0] == 3


def test_on_ready_runs_once_on_the_window_thread_and_says_which_work(qapp):
    rel = "GoalContent/薬屋のひとりごと/folder.png"
    poster("ja", rel)
    ref = ref_of(21, rel)
    calls, heard = [], []
    qcovers.notifier().ready.connect(heard.append)
    try:
        pix = qcovers.pixmap_for(ref, "薬屋のひとりごと", 26, 37, 1.0, "stack",
                                 on_ready=lambda: calls.append(threading.current_thread() is threading.main_thread()))
        assert pix is rows.cover("薬屋のひとりごと", 26, 37, 1.0)        # the generated one meanwhile
        assert wait_until(lambda: calls, 5)
        assert calls == [True] and heard == [21]
    finally:
        qcovers.notifier().ready.disconnect(heard.append)


@pytest.mark.parametrize("dpr", [1.0, 1.5, 2.0])
def test_the_pictures_held_stay_within_their_byte_budget_at_every_ratio(qapp, monkeypatch, dpr):
    monkeypatch.setattr(qcovers, "DISK_MB", 1)
    rel = "HighPriority/ゆるキャン/poster.png"
    poster("ja", rel)
    for w in range(40, 100, 4):                                 # 15 sizes of one work (each its own key)
        landed(ref_of(9, rel), w, round(w * 1.5), dpr, "stand")
        assert qcovers.held_bytes() <= 1024 * 1024
    assert qcovers.held_bytes() == sum(p.width() * p.height() * 4 for p, _f, _s in qcovers._held.values())
    newest = qcovers._key(ref_of(9, rel), "stand", 96, 144, dpr)
    assert newest in qcovers._held                              # the oldest went first, the newest stays


def test_the_whole_budget_holds_at_200_percent_with_every_row_shape(qapp):
    """rows.py's generated covers and art (8 + 8 MB) and the decoded pictures (16 MB) stay inside the 64 MB budget."""
    assert rows.COVERS_MB + rows.ART_MB + qcovers.DISK_MB <= 64
    rel = "HighPriority/チェンソーマン/poster.png"
    poster("ja", rel)
    for k in range(60):
        landed(ref_of(100 + k, rel), 44, 63, 2.0, "row")
    assert 0 < qcovers.held_bytes() <= qcovers.DISK_MB * 1024 * 1024


def test_nothing_decodes_while_a_window_waits_for_its_first_frame(qapp):
    rel = "HighPriority/ぼっち・ざ・ろっく/poster.png"
    poster("ja", rel)
    token = object()
    qcovers.hold(token)
    assert qcovers.decoded(ref_of(4, rel), 44, 63, 1.0) is None
    settle()
    time.sleep(0.1)
    settle()
    assert qcovers.decodes[0] == 0 and qcovers._DEFERRED
    qcovers.release(token)
    assert wait_until(lambda: qcovers.decoded(ref_of(4, rel), 44, 63, 1.0) is not None, 5)
    assert qcovers.decodes[0] == 1


def test_a_poster_replaced_in_place_is_let_go_at_the_recheck(qapp):
    rel = "HighPriority/推しの子/poster.png"
    poster("ja", rel)
    ref = ref_of(31, rel)
    assert near(centre(landed(ref, 44, 63)), ROSE)
    later = time.time() + 5
    poster("ja", rel, png(40, 60, (30, 140, 200)))
    os.utime(os.path.join(path_utils.get_data_path("ja"), *rel.split("/")), (later, later))
    heard = []
    qcovers.notifier().ready.connect(heard.append)
    try:
        qcovers.recheck()
        assert wait_until(lambda: heard == [31], 5)
        assert near(centre(landed(ref, 44, 63)), (30, 140, 200))
    finally:
        qcovers.notifier().ready.disconnect(heard.append)


# --- the window ------------------------------------------------------------------------------------------------------ #
def open_seed(qapp, seed, size=(1280, 900)):
    reader = library_reader.LibraryReader(seed.opener, language=seed.language, numbers=seed.numbers,
                                          mining=seed.mining, poll=0.02)
    services = shell.Services(library=reader)
    win = shell.open_window(qapp, services)
    win.resize(*size)
    win.show()
    page = win.page_widgets["current"]
    assert wait_until(lambda: page.view_model is not None and not page.view_model.loading, 10)
    settle(50)
    return win, services


@pytest.fixture
def seeded(qapp):
    made = []

    def make(language="ja", before=None):
        seed = window_seed.build(language=language)
        if before is not None:
            before(seed)
        win, services = open_seed(qapp, seed)
        made.append((win, services))
        return seed, win
    yield make
    for win, services in made:
        win.close()
        services.shutdown(0.5)


def _give_poster(seed, work_id, colour=ROSE):
    """A poster beside one work's files, recorded as the scan records it (`set_cover(w, "file", ref=…)`)."""
    rel = next(it["rel_path"] for it in seed.items if it["work_id"] == work_id).rsplit("/", 1)[0] + "/poster.png"
    poster(seed.language, rel, png(40, 60, colour))
    return {"id": work_id, "cover_source": "file", "cover_ref": rel, "cover_path": None}


def test_up_next_paints_its_poster_once_decoded(seeded):
    seen = {}

    def before(seed):
        seed.library.commit(works=[_give_poster(seed, seed.hero_work)])
        seen["seed"] = seed
    seed, win = seeded(before=before)
    lst = win.page_widgets["current"].list
    hero = lst.model().entries[0][1]
    assert hero.work_id == seed.hero_work and hero.cover.source == "file"
    rect = lst.visualRect(lst.model().index(0, 0))
    cov = lst.delegate._hero_geometry(hero, rect)["cover"]

    def painted():
        settle()
        arr = rgb_array(lst.viewport().grab(cov))
        return near(tuple(int(v) for v in arr[arr.shape[0] // 2, arr.shape[1] // 2]), ROSE)
    assert wait_until(painted, 5)


def test_a_picture_landing_repaints_only_the_rows_of_its_title(seeded):
    seed, win = seeded()
    lst = win.page_widgets["current"].list
    entries = lst.model().entries
    i = next(k for k, (kind, p, _l) in enumerate(entries) if kind == rows.ROW and k >= 2 and p.work_id is not None
             and sum(1 for _k, q, _ in entries if getattr(q, "work_id", None) == p.work_id) == 1)
    work = entries[i][1].work_id
    token = object()
    qcovers.hold(token)                                         # the picture waits: the record lands first
    try:
        seed.library.commit(works=[_give_poster(seed, work)])
        assert wait_until(lambda: getattr(lst.model().entries[i][1], "cover", None) is not None and
                          lst.model().entries[i][1].cover.source == "file", 5)
        settle(30)
        kept = {k: v[1] for k, v in lst.delegate._sprites["row"].items()
                if getattr(v[0], "work_id", None) != work}
        before = lst.delegate.renders
    finally:
        qcovers.release(token)
    assert wait_until(lambda: qcovers.held_bytes() > 0, 5)
    settle(30)
    assert lst.delegate.renders - before == 1                   # its one row, drawn again with its picture
    for k, pix in kept.items():                                 # every other row's picture kept as it was
        hit = lst.delegate._sprites["row"].get(k)
        assert hit is None or hit[1] is pix


def test_the_opened_row_stands_its_whole_cover_at_its_left(seeded):
    seed, win = seeded()
    lst = win.page_widgets["current"].list
    entries = lst.model().entries
    i = next(k for k, (kind, p, _l) in enumerate(entries) if kind == rows.ROW and len(p.episodes) == 1)
    row = entries[i][1]
    closed_h = lst.visualRect(lst.model().index(i, 0)).height()
    lst.toggle(lst.model().index(i, 0))
    settle(30)
    rect = lst.visualRect(lst.model().index(i, 0))
    slab = lst.delegate.slab_of(rect)
    stand = lst.delegate.stand_rect(slab)
    assert rect.height() >= closed_h + lst.delegate.stand_h()   # one episode: the row grows to stand its cover
    assert rect.contains(stand)
    first_ep = lst.delegate._episode_rows(row, rect)[0][0]
    assert stand.right() < first_ep.left() + 12                 # left of the episodes' stones
    gen = rows.cover(row.cover_title, stand.width(), stand.height(), 1.0, large=True)
    arr = rgb_array(lst.viewport().grab(stand))
    want = rgb_array(gen)
    mid = (arr.shape[0] // 2, arr.shape[1] // 3)
    assert near(tuple(int(v) for v in arr[mid]), tuple(int(v) for v in want[mid]), 10)     # the generated, standing


def test_goals_hand_takes_a_titles_poster_once_decoded(seeded):
    def before(seed):
        goal_work = next(it["work_id"] for it in seed.items if it["tier"] == "goal")
        seed.library.commit(works=[_give_poster(seed, goal_work)])
    seed, win = seeded(before=before)
    dock = win.dock
    assert any(ref is not None and ref.source == "file" for ref in dock.goal.cover_refs)
    # the hand is drawn with the generated cover first, then once more when the picture lands — never per paint
    assert wait_until(lambda: (settle() or True) and dock._hand_key is not None and dock._hand_key[2][0], 5)
    hands = dock.hands
    settle(30)
    dock.update()
    settle(10)
    assert dock.hands == hands and hands <= 3


# --- the shell: the scan after the first frame ------------------------------------------------------------------ #
@pytest.fixture
def real(qapp):
    made = []

    def make(language="ja", art=None):
        store = migrated(language)
        if art is not None:
            art(store)
        settings_manager.save_keys({"target_language": language})      # the window's language is its library's (P0)
        opener = moves_module.store_opener(language)
        reader = library_reader.LibraryReader(opener, language, poll=0.02)
        writer = moves_module.Writer(opener, language, journal_file=moves_module.journal_path(language),
                                     words=strings.MOVE_WORDS, retry=0.05)
        services = shell.Services(library=reader, writer=writer)
        frames = []
        win = shell.open_window(qapp, services)
        win.first_frame.connect(lambda: frames.append((qcovers.decodes[0], bool(qcovers._HELD))))
        win.resize(1280, 900)
        win.show()
        page = win.page_widgets["current"]
        assert wait_until(lambda: page.view_model is not None and page.view_model.state == "full", 15)
        made.append((win, services, store))
        return store, win, writer, frames
    yield make
    for win, services, store in made:
        win.close()
        services.shutdown(2.0)
        store.close()


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_window_scans_after_its_first_frame_and_shows_the_poster_it_found(real, language):
    def art(store):
        rel = store.item(store.ids("now")[0])["rel_path"].rsplit("/", 1)[0] + "/poster.png"
        poster(language, rel)
    store, win, writer, frames = real(language, art)
    assert wait_until(lambda: frames, 5)
    assert frames[0] == (0, True)                               # at the first frame: nothing decoded, still held
    lst = win.page_widgets["current"].list
    work = store.item(store.ids("now")[0])["work_id"]
    assert wait_until(lambda: store._work_row(work)["cover_source"] == "file", 10)       # the scan recorded it
    assert wait_until(lambda: any(getattr(p, "work_id", None) == work and getattr(p, "cover", None) is not None
                                  and p.cover.source == "file" for _k, p, _l in lst.model().entries), 10)
    assert wait_until(lambda: (settle() or True) and qcovers.held_bytes() > 0, 10)        # and its picture decoded


# --- Change cover… on a real store ---------------------------------------------------------------------------------- #
class Library:
    def __init__(self, language):
        self.language = language
        self.store = migrated(language)
        self.data_dir, self.user_files_dir = roots(language)
        self.saved = []
        self.writer = moves_module.Writer(ls.StoreOpener(language, self.data_dir, self.user_files_dir, role="window"),
                                          language, journal_file=moves_module.journal_path(language), retry=0.05,
                                          words=strings.MOVE_WORDS, on_saved=lambda c, label: self.saved.append(c))
        self.writer.start()
        qcovers.use_library(language, self.data_dir, self.writer)

    def row(self, item_id):
        work = self.store._work_row(self.store.item(item_id)["work_id"])
        return SimpleNamespace(key=f"i{item_id}", work_id=work["id"], title=work["title"], cover_title=work["title"],
                               cover=view_rows.cover_of(dict(work)))

    def record(self, work_id):
        r = self.store._work_row(work_id)
        return r["cover_source"], r["cover_path"], bool(r["cover_locked"])

    def close(self):
        self.writer.finish(time.monotonic() + 5)
        self.store.close()


@pytest.fixture(params=["ja", "zh"])
def lib(request, qapp):
    library = Library(request.param)
    yield library
    library.close()


def test_change_cover_offers_choose_an_image_and_a_generated_cover_with_their_tips(lib):
    row = lib.row(lib.store.ids("now")[0])
    entries = qcovers.cover_menu_entries(row)
    assert [e[0] for e in entries] == ["cover-choose", "cover-generated"]
    assert [e[1] for e in entries] == ["Choose an image…", "Use a generated cover"]
    assert all(e[2] and callable(e[3]) for e in entries)       # a tooltip on each
    assert qcovers.cover_menu_entries(SimpleNamespace(work_id=None, cover=None)) == []


def test_choose_an_image_copies_it_keeps_the_old_one_dated_and_undo_takes_it_back(lib, tmp_path):
    item = lib.store.ids("now")[0]
    row = lib.row(item)
    work = row.work_id
    before = lib.record(work)
    first = write(str(tmp_path / "表紙.png"), png(30, 45, ROSE))
    assert qcovers.choose_image(row, path=first)
    assert wait_until(lambda: (settle() or True) and lib.record(work)[0] == "user", 5)
    source, path, locked = lib.record(work)
    assert locked and path.startswith("user:")
    covers_dir = os.path.join(path_utils.get_user_files_path(lib.language), "covers")
    kept = os.path.join(covers_dir, path[len("user:"):])
    with open(kept, "rb") as f, open(first, "rb") as g:
        assert f.read() == g.read()                            # copied whole into User Files
    picked = lib.row(item)
    assert near(centre(landed(picked.cover, 30, 45)), ROSE)    # and painted
    second = write(str(tmp_path / "poster2.png"), png(30, 45, (30, 140, 200)))
    assert qcovers.choose_image(picked, path=second)
    assert wait_until(lambda: (settle() or True) and lib.record(work)[1] not in (path, None), 5)
    trash = os.path.join(covers_dir, ".trash")
    assert any(n.startswith(path[len("user:"):].rsplit(".", 1)[0]) for n in os.listdir(trash))   # dated backup
    assert os.path.isfile(kept)                                # ... and still there for the Undo
    n = len(lib.saved)
    lib.writer.undo()
    assert wait_until(lambda: lib.record(work) == (source, path, True), 5)
    lib.writer.undo()
    assert wait_until(lambda: lib.record(work) == before, 5)
    assert len(lib.saved) == n


def test_a_file_that_isnt_a_picture_records_nothing(lib, tmp_path):
    row = lib.row(lib.store.ids("now")[0])
    said = []
    qcovers._library["window"] = SimpleNamespace(say=said.append)
    text = write(str(tmp_path / "第1話.png"), "これは画像ではありません\n".encode("utf-8") * 10)
    before = lib.record(row.work_id)
    assert qcovers.choose_image(row, path=text)
    assert wait_until(lambda: (settle() or True) and said, 5)
    assert said == [strings.COVER_NOT_IMAGE] and lib.record(row.work_id) == before


def test_use_a_generated_cover_locks_it_and_undo_takes_it_back(lib):
    row = lib.row(lib.store.ids("soon")[0])
    before = lib.record(row.work_id)
    assert qcovers.use_generated(row)
    assert wait_until(lambda: lib.record(row.work_id) == ("generated", None, True), 5)
    locked = lib.row(lib.store.ids("soon")[0])
    assert [e[0] for e in qcovers.cover_menu_entries(locked)] == ["cover-choose"]     # already the generated, kept
    lib.writer.undo()
    assert wait_until(lambda: lib.record(row.work_id) == before, 5)


def test_a_read_only_library_changes_no_cover_and_says_so(lib, tmp_path):
    row = lib.row(lib.store.ids("now")[0])
    said = []
    qcovers._library["window"] = SimpleNamespace(say=said.append)
    lib.writer.opener.mode, lib.writer.opener.reason = "read-only", "damaged"
    lib.writer.opener.check = lambda: "read-only"
    assert qcovers.choose_image(row, path=write(str(tmp_path / "a.png"), png())) is False
    assert qcovers.use_generated(row) is False
    assert said == [strings.COVER_CANT] * 2
