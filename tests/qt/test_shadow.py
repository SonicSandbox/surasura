"""Cached shadows (M2.1 row 4; the window's spec 05 §5.3, A4 *Shadows*).

What a wrong answer would cost:
  * a shadow that isn't the mock's (CSS's box-shadow: the box moved, grown by its spread, a Gaussian of σ = blur / 2);
  * a toast's shadow drawn too dark (a short box's shadow is fainter than a long one's);
  * a cache that grows with every toast's width, or a pixmap made on every paint (05 §5.3: made once);
  * a shadow that takes the clicks meant for the list beneath it.
"""
import math

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint, QRectF, Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QApplication, QWidget

from app import theme
from app.qt import shadow


@pytest.fixture(autouse=True)
def _fresh_cache():
    shadow.clear()
    yield
    shadow.clear()


def _draw(name, rect, size=(1000, 1000), dpr=1.0):
    img = QImage(round(size[0] * dpr), round(size[1] * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    shadow.paint(p, QRectF(*rect), name)
    p.end()
    return img


def _expected(name, rect, x, y):
    """The closed form at pixel (x, y): α · Fx · Fy, each the share of a Gaussian over the shadow's box."""
    box = shadow.shape(QRectF(*rect), name)
    s = shadow.sigma(name)
    a = shadow.spec(name)[4].alpha()
    return a * shadow.profile(x + 0.5, box.left(), box.right(), s) * shadow.profile(y + 0.5, box.top(), box.bottom(), s)


def test_a_large_shadow_matches_the_closed_form_at_its_edge_one_sigma_out_its_middle_and_beyond():
    name, rect = "menu", (300, 300, 400, 300)          # 0 24px 50px -16px #000: σ 25
    img = _draw(name, rect)
    box = shadow.shape(QRectF(*rect), name)
    s = shadow.sigma(name)
    mid_x = int(box.center().x())
    top = int(box.top())
    for y, want in ((top, 0.5), (top - int(s), 0.159), (int(box.center().y()), 1.0)):
        got = img.pixelColor(mid_x, y).alpha()
        assert abs(got - _expected(name, rect, mid_x, y)) <= 3, (y, got)
        assert abs(got - 255 * want) <= 6, (y, got, want)
    assert img.pixelColor(mid_x, int(top - 3.2 * s)).alpha() == 0       # beyond 3σ: nothing drawn
    # a corner, off both edges: the product of the two profiles
    cx, cy = int(box.left() - s / 2), int(box.top() - s / 2)
    assert abs(img.pixelColor(cx, cy).alpha() - _expected(name, rect, cx, cy)) <= 3


def test_a_small_box_is_fainter_and_drawn_at_its_own_height():
    name = "toast"                                       # 0 20px 40px -14px: σ 20; a toast ~44 px tall -> a 16 px box
    rect = (300, 300, 420, 44)
    img = _draw(name, rect)
    box = shadow.shape(QRectF(*rect), name)
    cx, cy = int(box.center().x()), int(box.center().y())
    got = img.pixelColor(cx, cy).alpha()
    assert abs(got - _expected(name, rect, cx, cy)) <= 3
    assert got < 255 * 0.45                              # a 16 px box under σ 20: far from black (a slice would be)


def test_sliced_and_unsliced_agree_where_they_meet():
    name = "tooltip"                                     # σ 16: a side ≥ 6σ (96 px) is sliced
    s = shadow.sigma(name)
    corner = math.ceil(2 * shadow.REACH * s)
    long_w = 2 * corner + 1 - 2 * shadow.REACH * s       # just long enough to slice
    for w in (long_w + 0.5, long_w - 0.5):
        rect_w = w - 2 * theme.SHADOWS[name][3]         # the element's width for a box this wide (spread −12)
        img = _draw(name, (300, 300, rect_w, 300))
        box = shadow.shape(QRectF(300, 300, rect_w, 300), name)
        y = int(box.center().y())
        for x in (int(box.left()) - 10, int(box.left()), int(box.center().x())):
            assert abs(img.pixelColor(x, y).alpha() - _expected(name, (300, 300, rect_w, 300), x, y)) <= 3, (w, x)


def test_two_toast_widths_share_one_cached_image_and_a_repaint_makes_none():
    _draw("toast", (100, 100, 300, 44))
    assert shadow.cached()[0] == 1
    _draw("toast", (100, 100, 520, 44))                  # another width: the same short side, the same image
    _draw("toast", (100, 100, 300, 44))
    assert shadow.cached()[0] == 1
    first = shadow.image("toast", 1.0, None, 16.0)
    assert shadow.image("toast", 1.0, None, 16.0) is first        # a hit: the same pixmap
    shadow.image("toast", 1.5, None, 16.0)
    assert shadow.cached()[0] == 2                       # another device-pixel ratio: its own


def test_the_cache_stays_within_its_bound(monkeypatch):
    monkeypatch.setattr(shadow, "KEPT_BYTES", 200_000)
    for h in range(10, 40):
        shadow.image("toast", 1.0, None, float(h))
    count, held = shadow.cached()
    assert count <= 2 and (held <= 200_000 or count == 1)     # the newest always kept, the rest within the bound
    newest = shadow.image("toast", 1.0, None, 39.0)
    assert shadow.image("toast", 1.0, None, 39.0) is newest


def test_at_150_percent_the_image_is_made_at_the_device_ratio():
    img = _draw("menu", (100, 100, 400, 300), size=(700, 600), dpr=1.5)
    assert img.width() == 1050
    assert shadow.image("menu", 1.5, None, None).devicePixelRatio() == 1.5


def test_a_spread_larger_than_the_box_draws_nothing():
    img = _draw("toast", (300, 300, 20, 20))             # spread −14 on a 20 px box: no box left
    assert all(img.pixelColor(x, y).alpha() == 0 for x in range(250, 380, 7) for y in range(250, 380, 7))


def test_the_accent_glow_takes_the_themes_accent():
    img = _draw("primary-button", (300, 300, 200, 40))
    c = img.pixelColor(400, 330)
    assert c.alpha() > 0
    accent = shadow.spec("primary-button")[4]
    # premultiplied: the colour's hue is the accent's, whatever its alpha
    r, g, b = (c.red(), c.green(), c.blue())
    assert abs(r - accent.red()) <= 3 and abs(g - accent.green()) <= 3 and abs(b - accent.blue()) <= 3


def test_the_follower_tracks_its_overlay_and_never_takes_a_click(qapp):
    stage = QWidget()
    stage.resize(800, 600)
    under = QWidget(stage)
    under.setGeometry(0, 0, 800, 600)
    card = QWidget(stage)
    card.setGeometry(200, 200, 300, 60)
    follower = shadow.Follower(card, "toast")
    stage.show()
    QApplication.processEvents()
    left, top, right, bottom = shadow.margins("toast")
    assert follower.geometry() == card.geometry().adjusted(-left, -top, right, bottom)
    assert follower.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    card.move(220, 260)
    assert follower.geometry().topLeft() == card.geometry().topLeft() - QPoint(left, top)
    # a point in the shadow's reach, off the card: the widget beneath gets it, not the shadow
    assert stage.childAt(QPoint(card.x() + 10, card.geometry().bottom() + 10)) is under
    card.hide()
    assert follower.isHidden()
    stage.close()
