"""Reading pixels (W2.1; the stack pack: look at the pixels, not the stylesheet). A grab is read as an RGB array; a
colour is "there" within a small tolerance per channel. Used by the tests and by tests/qt/capture.py."""
import numpy as np
from PyQt6.QtGui import QImage

from app import theme


def rgb_array(image):
    """A QImage (or QPixmap) -> an (h, w, 3) uint8 array, RGB."""
    if not isinstance(image, QImage):
        image = image.toImage()
    image = image.convertToFormat(QImage.Format.Format_RGB32)
    w, h = image.width(), image.height()
    ptr = image.constBits()
    ptr.setsize(image.sizeInBytes())
    arr = np.frombuffer(ptr, np.uint8).reshape(h, image.bytesPerLine() // 4, 4)[:, :w, :]
    return arr[:, :, [2, 1, 0]].copy()                 # BGRA in memory -> RGB


def rgb(hex_colour):
    r, g, b, _a = theme.parse(hex_colour)
    return np.array([int(r), int(g), int(b)], dtype=np.int16)


def count(arr, hex_colour, tolerance=2):
    """How many pixels of `arr` are `hex_colour` (± tolerance per channel)."""
    diff = np.abs(arr.astype(np.int16) - rgb(hex_colour))
    return int(np.all(diff <= tolerance, axis=2).sum())


def share(arr, hex_colour, tolerance=2):
    return count(arr, hex_colour, tolerance) / float(arr.shape[0] * arr.shape[1])


WINDOWS_BLUES = ("#0078d4", "#0067c0", "#005fb8", "#0063b1", "#3399ff")   # Windows 10 / 11's accents and selection
