"""鵜飼 Ukai's Allow card in the window (app/qt/ukai_allow.py, the shell's `ukai_extension` / `_ukai_allow`, the
bridge's `ukai_asked`; Ukai SPEC §0 U4: one Allow, nothing typed).

What a wrong answer would cost a learner: Ukai's ask never reaching the window (pairing impossible), or reaching it on
the door's thread (a crash); a card that pairs on Esc, a click beside it or *Not now*; a code on the card that isn't
the one Ukai's menu shows (nothing to match); and, while the class is off, any card at all.
"""
import http.client
import json
import socket
import threading

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtTest import QTest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

from app import door
from app.qt import confirm, shell, strings
from tests.qt.conftest import wait_until

ORIGIN = "chrome-extension://kbmfpngjjgdllneeigpgjifpgocmfgmb"


@pytest.fixture
def main(qapp):
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.resize(1100, 700)
    win.show()
    yield win
    win.close()
    services.shutdown(0.5)


def _free_port():
    with socket.socket() as s:
        s.bind((door.HOST, 0))
        return s.getsockname()[1]


@pytest.fixture
def paired_door(main, tmp_path, monkeypatch):
    """The window's own Ukai class, built on a thread as the door's start builds it, on a real door."""
    from app.services import ukai_pairing
    monkeypatch.setattr(door, "EXTENSION_ON", True)
    monkeypatch.setattr(door, "EXT_PORT", _free_port())
    monkeypatch.setattr(ukai_pairing, "path", lambda: str(tmp_path / "roaming" / ukai_pairing.FILE))
    built = []
    t = threading.Thread(target=lambda: built.append(main.ukai_extension()))
    t.start()
    t.join(10)
    d = door.Door({}, str(tmp_path / "results"), extension=built[0]).start()
    yield d
    d.stop()


def _call(d, method, path, body=None):
    """On a thread (the window's loop keeps running meanwhile) -> a box filled with (status, answer)."""
    box = []

    def run():
        conn = http.client.HTTPConnection(door.HOST, d.ext_port, timeout=10)
        headers = {"Host": f"{door.HOST}:{d.ext_port}", "Origin": ORIGIN} if method == "POST" else \
            {"Host": f"{door.HOST}:{d.ext_port}"}
        data = None if body is None else json.dumps(body).encode("utf-8")
        conn.request(method, path, body=data, headers=headers)
        r = conn.getresponse()
        box.append((r.status, json.loads(r.read().decode("utf-8"))))
        conn.close()

    threading.Thread(target=run, daemon=True).start()
    assert wait_until(lambda: box, 10)
    return box[0]


def _card(win):
    cards = [c for c in win.findChildren(confirm.Confirm) if c.isVisible()]
    return cards[0] if cards else None


def _texts(card):
    return " ".join(label.text() for label in card.findChildren(QLabel))


def _press(card, text):
    [button] = [b for b in card.findChildren(QPushButton) if b.text() == text]
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    QApplication.processEvents()


def test_ukais_ask_opens_the_allow_card_with_its_code_and_allow_pairs(main, paired_door):
    status, asked = _call(paired_door, "POST", "/v1/pair", {"version": "1.0.0"})
    assert status == 200
    assert wait_until(lambda: _card(main) is not None, 10), "the card opens on the window's thread"
    card = _card(main)
    words = _texts(card)
    assert strings.UKAI_ALLOW_TITLE in words and asked["code"] in words, "the same code as Ukai's menu"
    assert "⚠" in words, "no store has given this id yet: the warning line"
    assert _call(paired_door, "GET", "/v1/pair/" + asked["pair"])[1]["state"] == "waiting"
    _press(card, strings.UKAI_ALLOW_YES)
    status, got = _call(paired_door, "GET", "/v1/pair/" + asked["pair"])
    assert got["state"] == "allowed" and main.ukai_pairing.pairing() == (ORIGIN, got["token"])


@pytest.mark.parametrize("how", ["not now", "esc"])
def test_not_now_or_esc_pairs_nothing(main, paired_door, how):
    status, asked = _call(paired_door, "POST", "/v1/pair", {"version": "1.0.0"})
    assert wait_until(lambda: _card(main) is not None, 10)
    card = _card(main)
    if how == "esc":
        QTest.keyClick(QApplication.focusWidget() or card, Qt.Key.Key_Escape)
        QApplication.processEvents()
    else:
        _press(card, strings.UKAI_ALLOW_NO)
    assert _call(paired_door, "GET", "/v1/pair/" + asked["pair"])[1]["state"] == "denied"
    assert main.ukai_pairing.pairing() is None and main.isVisible()


def test_while_off_the_window_starts_its_door_with_no_pairing_and_no_card(main, monkeypatch):
    started = []
    from app.services import journey_door
    monkeypatch.setattr(journey_door, "enabled", lambda: True)
    monkeypatch.setattr(door, "start", lambda routes, folder, on_error=None, extension=None: started.append(extension))
    assert door.EXTENSION_ON is False
    shell.start_door(main).join(10)
    QApplication.processEvents()
    assert started == [None] and not hasattr(main, "ukai_pairing") and _card(main) is None
