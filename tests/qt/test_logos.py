"""The services' logos on Settings › Connections (W3.3 PL: `app/qt/logos.py`, `app/assets/logos/`, the logos' credits).

What a wrong answer would cost: a logo shipped that its owner never cleared (AniList, YouTube: name only); a logo
changed from its owner's file (Anki's licence and TMDB's terms allow it only unmodified); a blurred or wrongly sized
logo at 125–200 % scaling; a decode on the GUI thread or one per paint (the window's 4 ms step); a crash when a file is
missing; an SVG that could run or fetch something; a build that leaves the folder out; or a notice the owners ask for
missing from the credits.
"""
import hashlib
import os
import re
import threading

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtGui import QColor, QImageReader

from app import credits
from app.qt import logos
from tests.qt.conftest import wait_until

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCALES = (1.0, 1.25, 1.5, 1.75, 2.0)

# Every file in app/assets/logos/, its sha256 as sourced (the planning folder's logos/<service>/<file>, copied as
# bytes: no logo may be changed — Anki's licence and TMDB's terms ask for it unmodified).
SHIPPED = {
    "anki-icon-vector.svg": ("anki/anki-icon-vector.svg",
                             "917f1fb9c56930f1c34bed01659ffe53e924c5335ea25b6f1a71a8847f3ab490"),
    "LICENSE-anki.txt": ("anki/LICENSE-anki.txt", "bde7d05790a05f1d1776b77a93ac32765310c8e6e578136183c2560475c500ef"),
    "anki_miner.svg": ("anki-miner/anki_miner.svg", "1937c82371ad4daf808eb2d8b2645ad72ce9be71408b19f83916a3a73591b444"),
    "LICENSE-anki_miner.txt": ("anki-miner/LICENSE-anki_miner.txt",
                               "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986"),
    "hato-32.png": ("hato/hato-32.png", "b5126208b2a805c9b3506d940d5d47e862ca133843cca219bd0025bf4580c677"),
    "hato-64.png": ("hato/hato-64.png", "d5ffcd9cb3f5767c4c1bc4f0083913d814515b2e77af5f42c79accf1a3b8ce13"),
    "hato-128.png": ("hato/hato-128.png", "9f182807a6835a5256aa41c4dbd8a101bf1deb519290cdf40f82c9849a950787"),
    "tsubasa-32.png": ("tsubasa/icon-32.png", "d3be58c6e0d527a493be1f70af403d3e367386f0457b3b5fadb14b6456485851"),
    "tsubasa-64.png": ("tsubasa/icon-64.png", "a67bb27ccd5d50bee63b3437ed0ada7110ed4631c57096cc3d1eb65e08c8683d"),
    "tsubasa-128.png": ("tsubasa/icon-128.png", "3ca5a31ee9518f7e1f130a16994c61dd2a2399349a2543cf9145e508633d4554"),
    "tmdb_blue_short.svg": ("tmdb/tmdb_blue_short.svg",
                            "8e7b30f73a4020692ccca9c88bafe5dcb6f8a62a4c6bc55cd9ba82bb2cd95f6c"),
}


@pytest.fixture(autouse=True)
def _fresh_cache(qapp):
    logos.clear()
    yield
    wait_until(lambda: not logos._WAITING, timeout=5.0)
    logos.clear()


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _ask(name, px, dpr):
    """logo(...) and the event loop run until its answer. -> the QPixmap or None."""
    got = []
    logos.logo(name, px, got.append, dpr=dpr)
    assert wait_until(lambda: got, timeout=10.0), f"{name} at {px} px × {dpr} never answered"
    return got[0]


@pytest.fixture
def decodes(monkeypatch):
    """Every decode, with whether it ran on the GUI (main) thread."""
    seen = []
    real = logos._decode

    def recording(name, px, dpr):
        seen.append((name, px, dpr, threading.current_thread() is threading.main_thread()))
        return real(name, px, dpr)

    monkeypatch.setattr(logos, "_decode", recording)
    return seen


# --- the files ----------------------------------------------------------------------------------------------------- #
def test_the_folder_holds_exactly_the_cleared_files_byte_for_byte():
    """Every file as sourced (sha256), nothing else in the folder: no AniList or YouTube file ever ships."""
    folder = logos.folder()
    assert sorted(os.listdir(folder)) == sorted(SHIPPED)
    for name, (_source, sha) in SHIPPED.items():
        assert _sha(os.path.join(folder, name)) == sha, name
    named = {f for files in logos.CLEARED.values() for f in files}
    assert named <= set(SHIPPED)


def test_the_files_match_the_sourced_logos_when_that_folder_is_here():
    """The same check against the sourced files themselves (SURASURA_LOGOS_SOURCE: the planning folder's logos/,
    which only the developer's machine has)."""
    source = os.environ.get("SURASURA_LOGOS_SOURCE", "")
    if not source or not os.path.isdir(source):
        pytest.skip("the sourced logos folder isn't here (SURASURA_LOGOS_SOURCE)")
    for name, (sourced, sha) in SHIPPED.items():
        assert _sha(os.path.join(source, *sourced.split("/"))) == sha == _sha(os.path.join(logos.folder(), name))


def test_no_svg_could_run_or_fetch_anything():
    """Read as text only: no script, no on…= handler, no foreignObject, no link outside the file."""
    folder = logos.folder()
    for name in [f for f in os.listdir(folder) if f.lower().endswith(".svg")]:
        with open(os.path.join(folder, name), "rb") as f:
            text = f.read().decode("utf-8", "replace").lower()
        assert "<script" not in text, name
        assert not re.search(r"\son[a-z]+\s*=", text), name
        assert "foreignobject" not in text, name
        for link in re.findall(r"href\s*=\s*[\"']([^\"']*)[\"']", text):
            assert link.startswith("#"), (name, link)
        assert not re.search(r"url\(\s*[\"']?(?!#)", text), name


def test_the_build_carries_the_folder():
    """Surasura.spec's datas carry app/assets whole, which holds app/assets/logos/."""
    with open(os.path.join(ROOT, "packaging", "Surasura.spec"), encoding="utf-8") as f:
        spec = f.read()
    assert "(os.path.join(project_root, 'app', 'assets'), 'app/assets')" in spec
    assert os.path.normcase(logos.folder()) == os.path.normcase(os.path.join(ROOT, "app", "assets", "logos"))


# --- the logos ----------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("dpr", SCALES)
def test_every_cleared_logo_is_readable_and_sharp_at_every_scale(dpr):
    """Each logo `px` logical pixels tall at the scale's own device pixels, its aspect kept, never blank."""
    for name, files in logos.CLEARED.items():
        for px in (16, 24, 32):
            pix = _ask(name, px, dpr)
            assert pix is not None and not pix.isNull(), (name, px, dpr)
            assert pix.devicePixelRatio() == dpr
            assert pix.height() == round(px * dpr), (name, px, dpr)
            image = pix.toImage()
            assert any(image.pixelColor(x, image.height() // 2).alpha() > 0 for x in range(image.width())), name
            if files[0].endswith(".svg"):
                from PyQt6.QtSvg import QSvgRenderer
                box = QSvgRenderer(os.path.join(logos.folder(), files[0])).viewBoxF()
                assert abs(pix.width() - pix.height() * box.width() / box.height()) <= 1, (name, "aspect")
            else:
                assert pix.width() == pix.height(), name


def test_a_png_set_reads_the_smallest_source_at_least_as_tall_as_asked():
    """32 px at 100 % is hato-32 itself and at 200 % hato-64 itself (no rescale, so nothing blurs); 24 px at 175 %
    (42 device px) is the 64 scaled down, never the 32 scaled up."""
    folder = logos.folder()
    for dpr, source in ((1.0, "hato-32.png"), (2.0, "hato-64.png")):
        got = logos._decode("hato", 32, dpr)
        want = QImageReader(os.path.join(folder, source)).read()
        want.setDevicePixelRatio(dpr)
        assert got == want, (dpr, source)
    assert logos._decode("hato", 64, 2.0).height() == 128          # the 128 for 200 % at the larger size
    assert logos._decode("tsubasa", 24, 1.75).height() == 42


def test_anki_miners_tile_gets_a_surface_tile_behind_it_and_no_other_logo_does():
    image = _ask("anki_miner", 32, 1.0).toImage()
    edge = image.pixelColor(0, image.height() // 2)
    assert edge.name() == "#2d2d2d" and edge.alpha() == 255
    assert any(image.pixelColor(x, y) == QColor("#000000") for x in range(image.width()) for y in range(image.height()))
    for name in ("hato", "tsubasa", "anki"):
        other = _ask(name, 32, 1.0).toImage()
        assert other.pixelColor(0, 0).name() != "#2d2d2d" or other.pixelColor(0, 0).alpha() < 255, name


def test_anki_and_ankiweb_show_the_same_classic_icon():
    assert logos.CLEARED["anki"] == logos.CLEARED["ankiweb"] == ("anki-icon-vector.svg",)


def test_anilist_youtube_and_every_other_row_have_no_logo(decodes):
    """Not cleared: the name only — answered at once, nothing decoded."""
    for name in ("anilist", "youtube", "jimaku", "more_from_houseki", ""):
        got = []
        logos.logo(name, 24, got.append, dpr=1.0)
        assert got == [None], name
        assert name not in logos.CLEARED
    assert decodes == []


# --- off the GUI thread, once -------------------------------------------------------------------------------------- #
def test_the_decode_runs_on_a_worker_once_per_name_size_and_scale(decodes):
    first = _ask("anki", 24, 1.5)
    again = []
    logos.logo("anki", 24, again.append, dpr=1.5)
    assert again == [first]                                          # from the cache, at once, the same pixmap
    assert decodes == [("anki", 24, 1.5, False)]
    _ask("anki", 24, 2.0)                                            # a new scale is a new decode
    _ask("anki", 32, 2.0)                                            # so is a new size
    assert [d[:3] for d in decodes] == [("anki", 24, 1.5), ("anki", 24, 2.0), ("anki", 32, 2.0)]
    assert not any(d[3] for d in decodes)


def test_asks_while_a_decode_is_under_way_wait_for_that_one(decodes):
    got = []
    for _ in range(3):
        logos.logo("tmdb", 20, got.append, dpr=1.25)
    assert wait_until(lambda: len(got) == 3, timeout=10.0)
    assert got[0] is not None and got[0] is got[1] is got[2]
    assert len(decodes) == 1


# --- a file missing or unreadable ---------------------------------------------------------------------------------- #
def test_a_missing_or_unreadable_file_answers_none_never_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(logos, "folder", lambda: str(tmp_path))
    assert _ask("anki", 24, 1.0) is None                             # missing
    (tmp_path / "anki_miner.svg").write_bytes("鉱 is not a picture".encode("utf-8"))
    (tmp_path / "hato-32.png").write_bytes(b"\x89PNG broken")
    assert _ask("anki_miner", 24, 1.0) is None                       # unreadable SVG
    assert _ask("hato", 24, 1.0) is None                             # unreadable PNG set


# --- the credits --------------------------------------------------------------------------------------------------- #
def test_the_credits_carry_each_owners_notice():
    lines = (
        "Anki® is a registered trademark of Ankitects Pty Ltd. Surasura is not affiliated with or endorsed by Anki.",
        "https://apps.ankiweb.net",
        "AGPL-3.0",
        "Anki Miner icon © 0xzerolight (Zero), GPL-3.0",
        "This application uses TMDB and the TMDB APIs but is not endorsed, certified, or otherwise approved by TMDB.",
    )
    for line in lines:
        assert line in credits.LOGO_CREDITS, line
        assert line in credits.all_credits(), line
    assert credits.all_credits().startswith(credits.data_credits())


# --- the rows (Phase B: Settings' rows) ---------------------------------------------------------------------------- #
def _row_view(row_id):
    from app.qt import settings_catalog as catalog
    from app.qt import settings_page as sp
    view = sp.RowView(catalog.ROW[row_id])
    view.resize(600, 60)
    return view


def _shown(view):
    from PyQt6.QtWidgets import QLabel
    return view.findChild(QLabel, "settingslogo")


def test_each_cleared_row_shows_its_logo_before_its_words(decodes):
    for row_id, name in logos.ROWS.items():
        view = _row_view(row_id)
        label = logos.show(view)
        assert wait_until(lambda: not label.pixmap().isNull(), timeout=10.0), row_id
        assert view.layout().itemAt(0).widget() is label                 # before the label and help
        assert label.pixmap().height() == round(logos.row_px() * view.devicePixelRatioF())
        assert label.accessibleName() == name
        assert not label.isHidden()


def test_no_row_without_a_cleared_logo_shows_one(decodes):
    from app.qt import settings_catalog as catalog
    for row in catalog.ROWS:
        if row.id in logos.ROWS:
            continue
        view = _row_view(row.id)
        assert logos.show(view) is None, row.id
        assert _shown(view) is None, row.id
    assert {"jimaku", "anilist", "more_from_houseki"} <= set(catalog.ROW)
    assert decodes == []


def test_a_restyle_at_a_new_size_asks_for_that_size_once(decodes, qapp):
    """The row's own restyle (the page's, after a live text size) asks for the new size once; the same size again
    decodes nothing and keeps the same pixmap, and the row keeps one logo label."""
    from app.qt import style
    small = logos.row_px()
    view = _row_view("hato")                                         # built: its restyle shows the logo at M
    label = _shown(view)
    assert wait_until(lambda: not label.pixmap().isNull(), timeout=10.0)
    first = label.pixmap().cacheKey()
    view.restyle()
    assert label.pixmap().cacheKey() == first
    style.apply(qapp, "night", "L", "ja")                            # text size L (the harness puts M back)
    view.restyle()
    view.restyle()
    big = logos.row_px()
    assert big > small
    assert wait_until(lambda: label.pixmap().height() == round(big * view.devicePixelRatioF()), timeout=10.0)
    assert [d[:2] for d in decodes] == [("hato", small), ("hato", big)]
    assert len(view.findChildren(type(label), "settingslogo")) == 1


def test_the_settings_page_shows_the_logos_on_its_rows_and_nowhere_else():
    from tests.qt.test_settings_page import make_page
    page, _store = make_page()
    for row_id in logos.ROWS:
        view = page.row(row_id)
        if view is None:                                             # a row the page doesn't show here
            continue
        assert wait_until(lambda: _shown(view) is not None and not _shown(view).pixmap().isNull(), timeout=10.0), row_id
    shown = [rid for rid, view in page.rows.items() if _shown(view) is not None]
    assert set(shown) <= set(logos.ROWS)
    assert "hato" in shown and "anki_miner" in shown


def test_a_row_whose_file_is_gone_keeps_its_name_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(logos, "folder", lambda: str(tmp_path))
    view = _row_view("anki_miner")
    label = logos.show(view)
    wait_until(lambda: not logos._WAITING, timeout=10.0)
    assert label.isHidden() and label.pixmap().isNull()
    assert view.label.text()
