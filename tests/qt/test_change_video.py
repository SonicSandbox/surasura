"""Mattias's 3.0.6 field report: Dungeon Meshi E07's subtitle was linked by hand to E08's video (picked in the file
dialog while the videos read as unreadable), tsubasa rightly answered "not the same episode", and nothing let him pick
again — *Link…* is offered only while an episode has no video.

Now an episode with its video offers *Change its video…* in its ⋯ (`MineActions.change_video`), and *Not timed*'s card
*Choose its video…*: the picker opens at the video it has now, the one picked is linked as *Link…* links one (the
writer's `link_video`, its Undo), and once saved its timing is checked again against it (`check_job`).

What a wrong answer would cost: a wrong video kept for good (the field report), or the entry where it misleads — on a
book, on an episode with no video yet (that's *Link…*), or while it is being mined."""
import pytest

pytest.importorskip("PyQt6")

from app.services import view_rows
from app.qt import mine_actions, rows, strings
from tests.qt.conftest import wait_until
from tests.qt.test_p41_actions import _ep, _waiting_episode, act, lst_of  # noqa: F401  (act: a fixture)


def _names(entries):
    return [e.name for e in entries]


def test_an_episode_with_its_video_offers_change_its_video_and_the_rest_do_not(act):
    _seed, win, _writer = act()
    row, ep = _waiting_episode(lst_of(win))
    entries = win.mine.episode_entries(row, ep)
    [change] = [e for e in entries if e.name == "ep-change-video"]
    assert (change.label, change.tip, change.ok) == (strings.ROWS_CHANGE_VIDEO, strings.ROWS_CHANGE_VIDEO_TIP, True)
    in_anki = _ep(view_rows.Status("in_anki", "In Anki", "Its cards are in Anki", "ok"))
    assert "ep-change-video" not in _names(win.mine.episode_entries(row, in_anki)), "its cards are made already"
    no_video = _ep(view_rows.Status("no_media", "No video", "Its video isn't on this computer", "warn"))
    name = rows.action_of(no_video.status, (no_video,), win.mine.off, "video")[0]
    assert name == "no-media" and "ep-change-video" not in _names(win.mine.episode_entries(row, no_video)), \
        "no video yet: that is *Link…*"
    book = _ep(view_rows.Status("waiting", "Waiting", "In your top 20", "dim"))._replace(media_word="EPUB")
    assert "ep-change-video" not in _names(win.mine.episode_entries(row, book))


def test_the_video_picked_is_linked_and_its_timing_checked_again_once_saved(act, monkeypatch):
    _seed, win, writer = act()
    row, ep = _waiting_episode(lst_of(win))
    monkeypatch.setattr(mine_actions, "_current_video_folder", lambda opener, item_id: r"D:\Anime\Show S01")
    asked, checked = [], []
    win.mine.pick_file = lambda title, folder, patterns: asked.append((title, folder, patterns)) or \
        r"D:\Anime\Show S01\Show S01E07.mkv"
    win.mine.check_job = lambda lang, ids, get: checked.append(list(ids)) or ids
    [change] = [e for e in win.mine.episode_entries(row, ep) if e.name == "ep-change-video"]
    change.payload()
    assert wait_until(lambda: [c for c in writer.calls if c[0] == "link_video"], 5)
    assert [c for c in writer.calls if c[0] == "link_video"] == [("link_video", [ep.id],
                                                                   {"path": r"D:\Anime\Show S01\Show S01E07.mkv"})]
    title, folder, patterns = asked[0]
    assert title == strings.CHANGE_VIDEO_TITLE.format(label=ep.label) and folder == r"D:\Anime\Show S01"
    assert "*.mkv" in patterns
    assert wait_until(lambda: checked == [[ep.id]], 5), "its timing checked again once the link was saved"


def test_a_picker_closed_with_nothing_picked_links_nothing(act, monkeypatch):
    _seed, win, writer = act()
    row, ep = _waiting_episode(lst_of(win))
    monkeypatch.setattr(mine_actions, "_current_video_folder", lambda opener, item_id: None)
    picked = []
    win.mine.pick_file = lambda *a: picked.append(a) or ""
    [change] = [e for e in win.mine.episode_entries(row, ep) if e.name == "ep-change-video"]
    change.payload()
    assert wait_until(lambda: picked, 5)
    assert [c for c in writer.calls if c[0] == "link_video"] == []


def test_the_folder_the_picker_opens_at_is_the_video_it_has_now():
    class Store:
        def __init__(self, video):
            self.video = video

    class Opener:
        mode = "store"

        def __init__(self, video):
            self.store, self.closed = Store(video), False

        def handle(self):
            return self.store

        def close(self):
            self.closed = True

    import app.connect.library as library
    real = library.pairing_of
    try:
        library.pairing_of = lambda store, item_id: {"video_path": store.video} if store.video else {}
        opener = Opener(r"\\hemma\data\Anime\Show S01\Show S01E08.mkv")
        assert mine_actions._current_video_folder(opener, 7) == r"\\hemma\data\Anime\Show S01"
        assert opener.closed
        assert mine_actions._current_video_folder(Opener(None), 7) is None
        assert mine_actions._current_video_folder(None, 7) is None
    finally:
        library.pairing_of = real


def test_not_timeds_card_offers_choose_its_video_and_it_is_the_episodes_own_change(qapp, monkeypatch):
    """*Not timed*'s card: *Choose its video…* beside *Check again* — the episode's own `change_video`, for its item
    and with its title."""
    from tests.qt import test_needs_you as tny
    makers = []
    gen = tny.world.__wrapped__(qapp) if hasattr(tny.world, "__wrapped__") else None
    if gen is None:
        pytest.skip("needs-you's world fixture can't be driven from here")
    make = next(gen)
    try:
        calls = {"check_again": lambda *a: True, "mine_anyway": lambda *a: True, "dismiss": lambda *a: True}
        connect = {"jobs": [], "gaps": [],
                   "needs": [{"id": 11, "kind": "not-timed", "say": "E07 isn't timed to its video (refused)",
                              "item": 3, "title": "Dungeon Meshi S01E07", "seen_at": None,
                              "at": "2026-11-13T06:49:31Z"}]}
        _seed, win, _writer, ny = make(connect=connect, connect_calls=calls)
        entry = next(e for e in ny.entries if (e.data or {}).get("need_id") == 11)
        b = tny.button(ny, entry.key, "change_video")
        assert b.text() == strings.NEEDS_ACTIONS["change_video"][0] and b.toolTip()
        got = []
        monkeypatch.setattr(win.mine, "change_video", lambda item_id, label, rel_path=None: got.append((item_id, label)))
        b.click()
        assert wait_until(lambda: got, 5) and got == [(3, "Dungeon Meshi S01E07")]
    finally:
        try:
            next(gen)
        except StopIteration:
            pass
