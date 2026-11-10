"""The string's stones as ready-made pictures (W3.1a row A; the RUNBOOK's §1 *The string*, §3 speed rules).

What a wrong answer would cost: a stone that isn't the reference page's for the same seed (the kit's randomness off by
one bit draws every stone differently from the design Sonic signed); a stone that changes between two paints (the
string shimmers); a facet in a colour the theme doesn't own (a fourth palette nobody maintains); sheets that grow past
their budget at every scale and text size the window has shown (memory that only climbs); a sheet drawn on the GUI
thread (the first paint of a row stalls the window); stones that don't sit on the string's one hairline.

The kit's numbers below were read from gem-kit.js itself, run in Edge headless (2026-10-14; the page loaded the kit and
printed its `hash`, `prng`, `character`, `seedOf` and SVG): the port matched all 145 reference pictures point for point.
"""
import os
import subprocess
import sys
import threading

import numpy as np
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QImage, QPainter

from app import theme
from app.qt import stones
from tests.qt.conftest import wait_until
from tests.qt.pixels import count, rgb_array

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def _fresh_sheets(qapp):
    # every test starts with no sheet held and leaves no build running behind it
    stones.clear()
    yield
    wait_until(lambda: not stones._BUILDING, timeout=10)
    stones.clear()


def _picture(sheet, what):
    """The picture's pixels as an (h, w, 4) BGRA array (premultiplied), cut from its sheet."""
    _i, src, _anchor, _size = sheet.entries[what]
    image = sheet.images[0].copy(src.toRect()).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    ptr = image.constBits()
    ptr.setsize(image.sizeInBytes())
    arr = np.frombuffer(ptr, np.uint8).reshape(image.height(), image.bytesPerLine() // 4, 4)[:, :image.width(), :]
    return arr.copy()


# --- The kit's randomness, bit-exact ---------------------------------------------------------------------------------- #
@pytest.mark.parametrize("seed, salt, expected", [
    (1, 1, 1364121231), (7, 2, 1837757736), ("abc", 3, 2384471743), ("ナルト", 1, 378038239),
    ("w|v#3", 0, 1717057024), (123456, 2, 3200350893),
])
def test_the_seed_hash_is_gem_kits_fnv1a_to_the_bit(seed, salt, expected):
    # Edge ran gem-kit.js's `hash` on these: Japanese text counts by its UTF-16 units, as JavaScript does
    assert stones.hash_seed(seed, salt) == expected


@pytest.mark.parametrize("seed, salt, expected", [
    (1, 1, [0.9568336715456098, 0.4768093437887728, 0.8521551778540015]),
    (1, 2, [0.14855472487397492, 0.1554363719187677, 0.11284433212131262]),
    (42, 3, [0.7413041219115257, 0.3926021046936512, 0.47206294094212353]),
    ("ナルト", 1, [0.358169533777982, 0.7395981450099498, 0.9667044556699693]),
])
def test_mulberry32_gives_the_kits_numbers_exactly(seed, salt, expected):
    r = stones.prng(seed, salt)
    assert [r(), r(), r()] == expected                     # equal floats, not approximately


def test_the_character_and_the_trillions_seed_match_the_kit():
    c = stones.character(1)
    assert c["rot"] == -0.7028905502520502
    assert c["v"][:3] == [-0.7580271270126104, 0.9609729801304638, 0.9277478768490255]
    assert len(c["v"]) == 56
    assert stones.seed_of("tri:1") == 3469 and stones.seed_of("tri:ep-12") == 5373 and stones.seed_of("ナルト") == 6257


def test_a_cut_stone_is_the_reference_pages_stone_corner_for_corner():
    # gem-kit's stone('cut', 'anime', 1, {imp: .7}) as Edge wrote it: the crown facet, then the dark lower facet
    ops = stones.stone_ops("cut", "sapphire", 1)
    crown = [(round(x, 2), round(y, 2)) for x, y in ops[0][1]]
    assert crown == [(-0.81, -7.88), (-4.5, -1.13), (1.48, -1.16)]
    assert ops[0][2] == (0xd6, 0xe7, 0xff) and ops[0][3] == .95       # the edge colour at .95
    dark = ops[5]
    assert [(round(x, 2), round(y, 2)) for x, y in dark[1]] == [(5.44, 2.95), (-1.16, 8.05), (-1.7, 2.87)]
    assert dark[2] == (0x13, 0x33, 0x71)                              # mix(base, black, .35), rounded as the kit
    rock = stones.stone_ops("rock", "emerald", 2)
    assert [(round(x, 2), round(y, 2)) for x, y in rock[0][1]] == [(-0.36, -1.24), (1.37, -6.69), (7.77, -4.2)]
    assert rock[0][2] == (0x4a, 0x50, 0x59)


def test_the_trillion_is_the_reference_pages_play_stone():
    # list-r14m's trillionSVG(true, 34, 'video', 1): its first facet (before the whole stone's 5.63° turn)
    ops = stones.trillion_ops("ruby", 1)
    assert ops[0][2] == (0xeb, 0x7f, 0x94) and ops[1][2] == (0x79, 0x1a, 0x2e)
    assert len([op for op in ops if op[0] == "fill"]) == 10              # three facets a side and the table


# --- Same seed, same picture ---------------------------------------------------------------------------------------- #
def test_the_same_seed_draws_identical_pixels_and_two_seeds_differ(qapp):
    a, b = stones.build(1.5, "M"), stones.build(1.5, "M")
    for what in [("stone", "cut", "ruby", 3, "next"), ("stone", "rock", "emerald", 0, "waiting"),
                 ("ore", "sapphire", 2, 1, 1), ("group", "emerald", 120), ("trillion", stones.UNLINKED)]:
        assert np.array_equal(_picture(a, what), _picture(b, what)), what
    one, two = _picture(a, ("stone", "raw", "sapphire", 0, "watched")), _picture(a, ("stone", "raw", "sapphire", 1, "watched"))
    assert one.shape != two.shape or not np.array_equal(one, two)
    # every variant of a state and gem is its own stone
    shapes = {_picture(a, ("stone", "cut", "emerald", v, "watched")).tobytes() for v in range(stones.VARIANTS)}
    assert len(shapes) == stones.VARIANTS


def test_a_cut_stones_lit_facet_holds_its_gems_light(qapp):
    sheet = stones.build(2.0, "L")
    for gem, (base, light, edge) in theme.GEM.items():
        rgb = rgb_array(sheet.images[0].copy(sheet.entries[("stone", "cut", gem, 0, "next")][1].toRect()))
        assert count(rgb, light, 3) >= 150, gem                       # two facets in the light, unmixed
        assert count(rgb, base, 3) >= 80, gem
        for other, colours in theme.GEM.items():
            if other != gem:
                assert count(rgb, colours[1], 3) == 0, (gem, other)    # never another gem's light


def test_the_ring_is_the_rooms_cyan(qapp):
    sheet = stones.build(2.0, "M")
    rgb = rgb_array(sheet.images[0].copy(sheet.entries[("ring", "next")][1].toRect()))
    assert count(rgb, theme.ROOM["ring"], 6) >= 100


# --- The sheet: its set, its anchors, its budget ---------------------------------------------------------------------- #
def test_the_sheet_holds_the_whole_fixed_set(qapp, monkeypatch):
    monkeypatch.setattr(stones, "FOLLOWS_TEXT_SIZE", True)        # the mechanism, were the string to follow the size
    sheet = stones.build(1.0, "S")
    singles = [w for w in sheet.entries if w[0] == "stone"]
    assert len(singles) == 3 * 3 * stones.VARIANTS * 3
    assert len([w for w in sheet.entries if w[0] == "group"]) == 9
    assert len([w for w in sheet.entries if w[0] == "ore"]) == 3 * 4 * 4 * 2
    assert {w[1] for w in sheet.entries if w[0] == "trillion"} == set(theme.GEM) | {stones.UNLINKED}
    assert {w[1] for w in sheet.entries if w[0] == "ring"} == set(stones.SIZES)
    # the sizes follow the reference (a watched stone 11 × 17 × 1.15; the next × 1.22; waiting × .84) and the text size
    w_, n_, s_ = (sheet.size_of(("stone", "cut", "sapphire", 0, size)).height() for size in ("watched", "next", "waiting"))
    assert n_ > w_ > s_
    assert 17 * 1.15 <= w_ <= 17 * 1.15 + 5
    large = stones.build(1.0, "L")
    assert large.size_of(("group", "ruby", 60)).height() > sheet.size_of(("group", "ruby", 60)).height() * 1.2


def test_the_anchors_put_every_stones_vertical_centre_on_one_line(qapp):
    sheet = stones.build(2.0, "M")
    for what, (_i, src, anchor, _size) in sheet.entries.items():
        if what[0] not in ("stone", "ring"):
            continue
        alpha = _picture(sheet, what)[:, :, 3]
        rows = np.nonzero(alpha.max(axis=1) > 40)[0]
        centre = (rows[0] + rows[-1] + 1) / 2                         # device px from the picture's top
        assert abs(centre - anchor.y() * sheet.dpr) <= 1.0, (what, centre, anchor.y() * sheet.dpr)
    # and a blit lands it there: drawn with its anchor on y = 40, its middle is on 40
    image = QImage(80, 80, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    p = QPainter(image)
    sheet_1 = stones.build(1.0, "M")
    sheet_1.draw(p, QPointF(40, 40), ("stone", "raw", "ruby", 2, "next"))
    p.end()
    ptr = image.constBits()
    ptr.setsize(image.sizeInBytes())
    alpha = np.frombuffer(ptr, np.uint8).reshape(80, 80, 4)[:, :, 3]
    rows = np.nonzero(alpha.max(axis=1) > 40)[0]
    assert abs((rows[0] + rows[-1] + 1) / 2 - 40) <= 1.0


def test_sheets_at_every_scale_and_text_size_stay_within_the_budget_oldest_dropped(qapp, monkeypatch):
    monkeypatch.setattr(stones, "FOLLOWS_TEXT_SIZE", True)        # the worst case: a sheet per text size too
    order = [(dpr, size) for dpr in (1.0, 1.5, 2.0) for size in ("S", "M", "L")]
    landed = []
    for key in order:
        sheet = stones.build(*key)
        assert sheet.bytes == sum(im.width() * im.height() * 4 for im in sheet.images)
        stones._landed(stones._key(*key), sheet)
        landed.append(stones._key(*key))
        held = list(stones._SHEETS)
        assert stones.held_bytes() <= stones.BUDGET_BYTES
        assert held[-1] == landed[-1]                                 # the newest always stays
        assert held == landed[-len(held):]                            # what went is the oldest, in order
    assert len(stones._SHEETS) < len(order)                           # the nine together are over 16 MB: some went
    assert stones.held_bytes() > 0


def test_the_sheet_is_built_off_the_gui_thread_and_get_answers_none_until_it_lands(qapp, monkeypatch):
    builds, ready, signalled = [], [], []
    real = stones.build

    def counted(dpr, size):
        builds.append(threading.get_ident())
        return real(dpr, size)

    monkeypatch.setattr(stones, "build", counted)
    stones.notifier().ready.connect(signalled.append)
    assert stones.get(1.25, "M", ready=ready.append) is None
    assert stones.get(1.25, "M") is None                              # still building: no second build
    assert wait_until(lambda: ready, timeout=10)
    sheet = ready[0]
    assert len(builds) == 1 and builds[0] != threading.get_ident()    # drawn on a worker
    assert sheet.thread_id != threading.get_ident()
    assert stones.get(1.25, "M") is sheet                             # then it is the sheet, at once
    assert signalled == [(1.25, "M")]                                 # the view repaints once
    assert stones.held_bytes() == sheet.bytes


def test_AD13_clear_lets_go_of_a_hold_no_window_will_release(qapp, monkeypatch):
    """A window built but never painted nor destroyed (a test's, dropped) holds every build back; `clear()` lets go of
    it and its deferred builds, so the next ask starts its build at once instead of waiting forever."""
    started = []
    monkeypatch.setattr(stones, "_start", started.append)
    stones.clear()
    stones.hold(object())                                             # a window that never paints, never goes
    assert stones.get(1.75, "M") is None and started == []           # deferred
    stones.clear()
    assert not stones._HELD and not stones._DEFERRED and (1.75, "M") not in stones._BUILDING
    assert stones.get(1.75, "M") is None and started == [(1.75, "M")]
    stones._BUILDING.pop((1.75, "M"), None)                           # (never built: the stand-in started nothing)


def test_AD13_the_window_fixture_lets_go_of_a_hold_a_test_left_behind():
    """The per-test fixture (tests/qt/conftest.py) releases whatever hold the last test left: the order of the tests
    never decides whether rows paint with their stones."""
    assert not stones._HELD
    stones.hold(object())                                             # left behind on purpose: the next test sees none


def test_AD13_no_hold_is_left_from_the_test_before():
    assert not stones._HELD


def test_nothing_is_built_when_the_module_loads():
    # The first frame is never held up for the stones: importing the module draws nothing and starts no worker.
    code = ("import os; os.environ['QT_QPA_PLATFORM'] = 'offscreen'\n"
            "from PyQt6.QtWidgets import QApplication; app = QApplication([])\n"
            "from app.qt import stones, rows, shell\n"
            "from PyQt6.QtCore import QThreadPool\n"
            "assert not stones._SHEETS and not stones._BUILDING and not stones._notifier\n"
            "assert QThreadPool.globalInstance().activeThreadCount() == 0\n")
    env = dict(os.environ)
    env.pop("QT_SCALE_FACTOR", None)
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr


# --- The keys a row asks with ------------------------------------------------------------------------------------------ #
def test_a_files_variant_is_stable_and_spread():
    assert stones.variant_of("葬送のフリーレン|1", 0) == stones.variant_of("葬送のフリーレン|1", 0)
    seen = [stones.variant_of("葬送のフリーレン|1", i) for i in range(48)]
    assert all(0 <= v < stones.VARIANTS for v in seen)
    assert len(set(seen)) == stones.VARIANTS                          # 48 episodes use every variant
    assert seen != [stones.variant_of("ぼっち・ざ・ろっく！|", i) for i in range(48)]


@pytest.mark.parametrize("n, bucket", [(1, 0), (11, 0), (12, 1), (35, 1), (36, 2), (119, 2), (120, 3), (400, 3)])
def test_an_ores_size_bucket(n, bucket):
    assert stones.size_bucket(n) == bucket


@pytest.mark.parametrize("mined, n, step", [(0, 13, 0), (1, 13, 1), (6, 13, 1), (7, 13, 2), (12, 13, 2), (13, 13, 3)])
def test_an_ores_mined_step(mined, n, step):
    assert stones.mined_step(mined, n) == step


def test_by_default_the_string_keeps_the_references_size_at_every_text_size(qapp):
    # Why: the reference draws the string in plain px; scaled with the text, a twelve-still-to-come row runs out of room
    # at 1024 Medium (worker C's finding). One sheet per device-pixel ratio, whatever the text size.
    assert stones.FOLLOWS_TEXT_SIZE is False
    assert stones._key(1.5, "S") == stones._key(1.5, "L") == stones._key(1.5, "M")
    small, large = stones.build(1.0, "S"), stones.build(1.0, "L")
    what = ("stone", "cut", "sapphire", 0, "watched")
    assert small.size_of(what) == large.size_of(what)


def test_a_stone_variant_is_the_string_plans_one_hash():
    from app.services import stone_plan
    for key, i in (("p12", 0), ("p12", 7), ("work-9", 130)):
        assert stones.variant_of(key, i) == stone_plan.variant(key, i)
