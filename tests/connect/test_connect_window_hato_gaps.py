"""The Connect window's *Ask hato again*: the gaps the P3.2 mutant pass found (research/mutants/JUDGED-P3.2.md) —
planted bugs in app/connect/connect_window.py that test_connect_window.py let through. Each test names its mutant.

`hato.backfill` is stood in for (recording its language and thread); real Japanese / Chinese words, synthetic titles."""
import gc
import threading

import pytest

from app.connect import connect_window
from tests.connect_tk_helpers import Pump, Tips, tk_root

NO_PAIRING = {"id": 21, "kind": "no-pairing", "item": None, "title": None, "at": "2026-10-12T09:00:00Z",
              "seen_at": None, "say": "4 files in hato's folder have no pairing from hato, so Connect can't tell which "
                                      "video they belong to."}
ERROR = {"id": 11, "kind": "error", "say": "Example Show - 05: Anki Miner stopped twice while making its cards.",
         "item": 4, "title": "Example Show - 05", "at": "2026-10-11T09:00:00Z", "seen_at": None}
RECORD = {"line": "Up to date · 3 cards made today", "state": "idle", "jobs": [], "unseen": 2, "made_today": 3,
          "needs": [], "undo": [], "shelf": {"on_shelf": 0, "swap_ins": 0, "runs": []}}


@pytest.fixture
def root():
    r = tk_root()
    try:
        yield r
    finally:
        r.destroy()
        r = None
        gc.collect()        # freed here on the Tk thread, never by a collection on a worker (test_connect_window.py's fix)


def _summary(lang="ja", **more):
    from app.connect import hato
    out = {"language": lang, "hato": hato.ASKED, "new": 2, "same": 61, "replaced": 0, "refused": [],
           "unpaired": ["a.srt", "b.srt"], "stopped": None, "skipped": None, "need": "raised"}
    out.update(more)
    return out


def _show(root, language, needs, pump):
    return connect_window.show(root, language, Tips(), dict(RECORD, needs=needs), act=lambda *a, **k: {},
                               settings=lambda: {"connect_enabled": True}, writer_busy=lambda: False,
                               confirm=lambda t, x: True, junban=True, post=pump.put, mark_seen=lambda ids: 1)


def test_ask_hato_again_acts_on_its_own_entry_when_another_need_is_listed_after_it(root, monkeypatch):
    """P3.2-W20. The no-pairing entry listed above another need: its *Ask hato again* asks hato and writes its words
    in its own entry's note — the button is bound to its entry, not to whichever need the list ended on."""
    from app.connect import hato
    calls = []
    monkeypatch.setattr(hato, "backfill", lambda lang, settings, **k: (calls.append(lang), _summary())[1])
    pump = Pump()
    win = _show(root, "ja", [NO_PAIRING, ERROR], pump)
    win.buttons[("needs", 21, "Ask hato again")].invoke()
    note = win.notes[("needs", 21)]
    assert pump.run(root, lambda: note.cget("text").startswith("hato's pairings (Japanese): 2 new, 61 already there."))
    assert calls == ["ja"]


def test_ask_hato_again_is_greyed_while_hato_is_being_asked(root, monkeypatch):
    """P3.2-B68. hato is given up to a minute: while its worker runs the button is greyed, so a second press can't
    start a second back-fill; it comes back once the answer is in."""
    from app.connect import hato
    gate, started = threading.Event(), threading.Event()

    def backfill(lang, settings, **k):
        started.set()
        gate.wait(10)
        return _summary()
    monkeypatch.setattr(hato, "backfill", backfill)
    pump = Pump()
    win = _show(root, "ja", [NO_PAIRING], pump)
    key = ("needs", 21, "Ask hato again")
    win.buttons[key].invoke()
    try:
        assert started.wait(10)
        root.update()
        assert str(win.buttons[key].cget("state")) == "disabled"
    finally:
        gate.set()
    assert pump.run(root, lambda: str(win.buttons[key].cget("state")) == "normal")


def test_the_chinese_windows_ask_hato_again_back_fills_chinese(root, monkeypatch):
    """P3.2-B70. Each language has its own window and its own no-pairing entry: the Chinese one asks hato for
    Chinese's pairings (`--lang zh`), never Japanese's."""
    from app.connect import hato
    calls = []
    monkeypatch.setattr(hato, "backfill", lambda lang, settings, **k: (calls.append(lang), _summary(lang))[1])
    pump = Pump()
    win = _show(root, "zh", [NO_PAIRING], pump)
    win.buttons[("needs", 21, "Ask hato again")].invoke()
    note = win.notes[("needs", 21)]
    assert pump.run(root, lambda: note.cget("text").startswith("hato's pairings (Chinese): 2 new"))
    assert calls == ["zh"]
