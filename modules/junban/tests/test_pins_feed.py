# SPDX-License-Identifier: GPL-3.0-or-later
"""Which cards are a pinned item's (P2.2 row 2.2.3; E1.1 03 §8, Kura's L2.2 §5.6).

*Study its cards first* is only as good as its idea of "its cards". Two sources, both checked here on real-shaped
data: the notes the store knows for the item (its Anki links and Connect's made words, 3.0's `cards_of`), and the
cards Anki Miner made by hand before Connect, found by the source Anki Miner writes into `MiscInfo` — which, as
Anki Miner 3.5.0 builds it, is `"<the video's folder> — <the video's name> @ HH:MM:SS"` with release tags taken off.
The rule must never take another show's card (exact, never a substring) and must never pin anything in 2.x.

Titles are made up (a synthetic seed, never the user's own); the words are real Japanese.
"""
import sqlite3
from collections import namedtuple

import pytest

from modules.junban import connect, pins

Pin = namedtuple("Pin", "item_id rel_path tier pinned_at")

VIDEO = "D:\\動画\\星の旅人\\星の旅人 - 05 [WEBRip-1080p][JA]-Trix.mkv"
ITEM = "Hato/星の旅人 - 05.ja.ass"


def test_the_source_is_anki_miners_label_without_its_time_or_release_tags():
    assert pins.source_of("星の旅人 — 星の旅人 - 05 @ 00:03:12") == "星の旅人/星の旅人05"
    assert pins.source_of("星の旅人 — 星の旅人 - 05 [WEBRip-1080p][JA]-Trix @ 1:02:03") == "星の旅人/星の旅人05"
    assert pins.source_of("夜の港 — 第1話 @ 12:07") == "夜の港/第1話"      # mm:ss
    # Not Anki Miner's shape: a Migaku note's hint, a bare title, an empty field, a time with no source
    for misc in ("この単語は「旅」の意味です", "星の旅人 - 05", "", None, " @ 00:01:00", "星の旅人 @ soon"):
        assert pins.source_of(misc) is None
    # As Anki stores a field: HTML entities read as their characters
    assert pins.source_of("夜&nbsp;の港 &amp; 月 — 第1話 @ 00:01:00") == "夜の港月/第1話"
    assert pins.source_of("&#x661F;の旅人 — 星の旅人 - 05 @ 00:03:12") == "星の旅人/星の旅人05"
    # the folder and the name stay apart: folder `Show` + file `01` is never a file named `Show01`
    assert pins.source_of("Show — 01 @ 00:00:01") == "show/01" != pins.source_of("Show01 @ 00:00:01")


def test_an_items_names_cover_its_paired_video_and_its_own_file():
    names = pins.names_of(ITEM, VIDEO)
    assert "星の旅人/星の旅人05" in names         # the video's folder — its name, release tags off (Anki Miner 3.5+)
    assert "hato/星の旅人05ja" in names and "hato/星の旅人05" in names     # the library copy's own folder and name
    assert "星の旅人05" not in names              # never the bare name: these keys move cards in Anki
    assert pins.names_of("番組/01.srt") == {"番組/01"}


def test_a_pin_on_an_ova_never_takes_another_shows_bare_ova_card():
    """The review's MUST 1: `OVA`, `Movie`, `Special 01` are every show's. A pin (an Anki write: its cards first, or
    taken out) never claims a card by a bare name, and the counted rule never takes one that names no episode."""
    cards = [_card(1, 800), _card(2, 801)]
    notes = _notes(n800="OVA @ 00:03:00", n801="星の旅人 — OVA @ 00:03:00")
    pinned = ([(7, "星の旅人/OVA.ja.srt", "2026-10-07T10:00:00Z")], {}, {}, set())
    assert pins.groups("ja", cards, notes, pinned=pinned) == [[2]]
    from modules.junban import source_names
    for stem in ("OVA", "Movie", "NCOP", "Special 01", "Part 1", "01"):
        assert all("/" in k for k in source_names.names_of(f"他の番組/{stem}.ja.srt")), stem
    assert "星の旅人05" in source_names.names_of("星の旅人/星の旅人 - 05.ja.srt")       # a show and its episode: counted
    # without a pairing, the item's own folder and name (the language tag taken off) still count
    assert pins.names_of("星の旅人/星の旅人 - 05.jpn.srt") == {"星の旅人/星の旅人05", "星の旅人/星の旅人05jpn"}
    assert pins.names_of("", None) == set()


def _card(card_id, note):
    return {"card_id": card_id, "note": note}


def _notes(**misc_by_note):
    return {int(n[1:]): {"fields": {"MiscInfo": value, "Expression": "冒険"}} for n, value in misc_by_note.items()}


PINNED = ([(7, ITEM, "2026-10-07T10:00:00Z"), (9, "夜の港/夜の港 - 10.srt", "2026-10-06T08:00:00Z")],
          {7: [501], 9: []}, {7: VIDEO})


def test_groups_take_the_stores_notes_and_the_cards_whose_source_names_the_item_oldest_pin_first():
    cards = [_card(1, 501), _card(2, 502), _card(3, 503), _card(4, 504), _card(5, 505), _card(6, 506)]
    notes = _notes(n502="星の旅人 — 星の旅人 - 05 @ 00:03:12",          # Anki Miner, by hand, from the paired video
                   n503="夜の港 — 夜の港 - 10 @ 00:10:00",              # the older pin's show
                   n504="星の旅人 — 星の旅人 - 50 @ 00:01:00",          # episode 50: never episode 5's
                   n505="星の旅人 — 星の旅人 - 05 extra @ 00:01:00",    # a longer label: not a substring match
                   n506="")
    assert pins.groups("ja", cards, notes, pinned=PINNED) == [[3], [1, 2]]


def test_a_label_two_library_items_share_names_neither():
    """`Season 01 — 01` from two shows' season folders: the label names no item, so pinning one show never pulls in
    the other's cards."""
    cards = [_card(1, 700), _card(2, 701)]
    notes = _notes(n700="Season 01 — 01 @ 00:02:00", n701="星の旅人 — 星の旅人 - 05 @ 00:03:12")
    pins_ = [(7, "星の旅人/Season 01/01.ja.srt", "2026-10-07T10:00:00Z")]
    videos = {7: "D:\動画\星の旅人\星の旅人 - 05.mkv"}
    assert pins.groups("ja", cards, notes, pinned=(pins_, {}, videos, set())) == [[1, 2]]
    assert pins.groups("ja", cards, notes, pinned=(pins_, {}, videos, {"season01/01"})) == [[2]]


def test_nothing_pinned_or_nothing_matching_is_no_pin():
    cards = [_card(1, 600)]
    assert pins.groups("ja", cards, _notes(n600="別の番組 — 第2話 @ 00:00:05"), pinned=([], {}, {})) is None
    assert pins.groups("ja", cards, _notes(n600="別の番組 — 第2話 @ 00:00:05"), pinned=PINNED) is None


class _Store:
    """A 3.0 store as Junban reads it (L3.1's `pinned()` / `cards_of()`, the pairings table)."""

    def __init__(self, with_pins=True):
        if with_pins:
            self.pinned = lambda: [Pin(7, ITEM, "now", "2026-10-07T10:00:00Z")]
            self.cards_of = lambda ids: {i: [501] for i in ids}
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE pairings (item_id INTEGER, pairing TEXT)")
        self.conn.execute("INSERT INTO pairings VALUES (7, ?)", ('{"video_path": "%s"}' % VIDEO.replace("\\", "\\\\"),))
        self.conn.execute("CREATE TABLE items (id INTEGER, rel_path TEXT)")
        # item 8 is another show's episode 1, in a folder named as item 9's: "夜の港 — 01" names neither
        self.conn.executemany("INSERT INTO items VALUES (?, ?)", [(7, ITEM), (8, "夜の港/01.srt"), (9, "夜の港/01.ja.srt")])
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True


def test_in_2_x_no_pin_is_ever_read(monkeypatch):
    """✅ E1.3-3: `PINS` off (2.x) — the store isn't even opened."""
    monkeypatch.setattr(connect, "PINS", False)
    monkeypatch.setattr(pins, "_open_store", lambda language: pytest.fail("2.x read a pin"))
    assert pins.read("ja") == ([], {}, {}, set())
    assert pins.groups("ja", [_card(1, 501)], {}) is None


def test_on_the_3_0_line_the_store_gives_the_pins_their_notes_and_videos(monkeypatch):
    monkeypatch.setattr(connect, "PINS", True)
    store = _Store()
    monkeypatch.setattr(pins, "_open_store", lambda language: store)
    assert pins.read("ja") == ([(7, ITEM, "2026-10-07T10:00:00Z")], {7: [501]}, {7: VIDEO}, {"夜の港/01"})
    assert store.closed


def test_a_store_without_pins_a_missing_store_or_a_broken_one_pins_nothing(monkeypatch):
    monkeypatch.setattr(connect, "PINS", True)
    monkeypatch.setattr(pins, "_open_store", lambda language: _Store(with_pins=False))   # a 2.x store
    assert pins.read("ja") == ([], {}, {}, set())
    monkeypatch.setattr(pins, "_open_store", lambda language: None)
    assert pins.read("ja") == ([], {}, {}, set())

    def broken(language):
        raise sqlite3.DatabaseError("database disk image is malformed")
    monkeypatch.setattr(pins, "_open_store", broken)
    assert pins.read("ja") == ([], {}, {}, set())


def test_two_files_of_one_title_with_one_name_still_name_it_for_a_pin(monkeypatch):
    """The review's SHOULD 8: two releases of one episode in one folder (`[Group] 星の旅人 - 05` and `星の旅人 - 05`)
    both carry Anki Miner 3.10's `星の旅人/星の旅人05`. A key is shared only across titles, so the pin still takes the
    card; another title's file of that name would make it name neither."""
    monkeypatch.setattr(connect, "PINS", True)

    class TitledStore(_Store):
        def __init__(self, other_title):
            super().__init__()
            self.conn.execute("DROP TABLE items")
            self.conn.execute("CREATE TABLE items (id INTEGER, rel_path TEXT, work_id INTEGER)")
            self.conn.executemany("INSERT INTO items VALUES (?, ?, ?)", [
                (7, "星の旅人/[Group] 星の旅人 - 05.ja.srt", 1), (8, "星の旅人/星の旅人 - 05.ja.srt", other_title)])
    monkeypatch.setattr(pins, "_open_store", lambda language: TitledStore(1))
    assert "星の旅人/星の旅人05" not in pins.read("ja")[3]
    monkeypatch.setattr(pins, "_open_store", lambda language: TitledStore(2))
    assert "星の旅人/星の旅人05" in pins.read("ja")[3]
