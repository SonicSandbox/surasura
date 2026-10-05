"""The live drill for the Anki-write lock (E1.4 row E1.4.6): two Surasura processes, one real Anki.

**Skipped unless `SURASURA_LIVE_ANKI=DevTest`** — it writes to Anki. Run only on the DevTest profile,
holding the program's `anki.lock`, with the program lead's go (the DevTest profile's deck is "DevTest", renamed
from "The Accelerator" after the first run; the profile is not signed in to AnkiWeb):

    SURASURA_LIVE_ANKI=DevTest SURASURA_LIVE_ANKI_DECK=DevTest python -m pytest tests/live -s

Before anything, AnkiConnect's `getActiveProfile` must answer DevTest, or the drill stops and writes
nothing. It never sends `sync` (refused by `anki_connect` anyway), never loads a profile.

A: a 順 reorder of the deck, chunk 1, slowed by a test hook on its transport so it writes for 10 s or
more. B: a Backfill fill started 2 s into A (its field values come from a stub, never the library),
which must wait for A. Both processes share one lock folder the way two real windows do: `APPDATA` and
`LOCALAPPDATA` point into the copy (`.appdata`, `.localappdata`) and each process's user data is the
copy's `.drill` folder, so nothing touches the real folders. Each logs every request's send and answer
time (`time.time()`). Then Junban's and Backfill's Restore put the deck back, checked card by card.
"""
import json
import os
import shutil
import subprocess
import sys
import time

import pytest

LIVE = os.environ.get("SURASURA_LIVE_ANKI") == "DevTest"
pytestmark = pytest.mark.skipif(not LIVE, reason="writes to Anki: SURASURA_LIVE_ANKI=DevTest only")

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
URL = os.environ.get("SURASURA_LIVE_ANKI_URL", "http://127.0.0.1:8765")
DECK = os.environ.get("SURASURA_LIVE_ANKI_DECK", "")
DRILL = os.path.join(_ROOT, ".drill")
MARK = "<div>E1.4 drill</div>"

_CHILD = r"""
import io, json, os, sys, time, urllib.request
from app import anki_connect, path_utils
drill = os.environ["SURASURA_DRILL"]
path_utils.get_user_data_path = lambda: drill
role, settings, slow, limit = sys.argv[1], json.loads(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4])
if anki_connect.invoke("getActiveProfile", settings["anki_connect_url"]) != "DevTest":
    print("result " + json.dumps({"refused": "not DevTest"}), flush=True)
    sys.exit(0)
real, log = urllib.request.urlopen, []

def hooked(request, timeout=None):
    payload = json.loads(request.data.decode("utf-8"))
    subs = [e.get("action") for e in (payload.get("params") or {}).get("actions") or [] if isinstance(e, dict)]
    sent = time.time()
    with real(request, timeout=timeout) as response:
        body = response.read()
    answered = time.time()
    log.append([sent, answered, payload["action"], subs])
    if slow and "setSpecificValueOfCard" in subs:
        time.sleep(slow)                      # A writes for 10 s or more
    return io.BytesIO(body)

urllib.request.urlopen = hooked
waited = []
on_wait = lambda holder: (waited.append(holder), print("waiting", anki_connect.waiting_line(holder), flush=True))
if role == "reorder":
    from modules.junban import reposition
    report = reposition.run(settings, refresh=False, wait=None, on_wait=on_wait)
else:
    from modules.junban import backfill

    class Stub:
        language = "ja"
        def __init__(self):
            self.given = 0
        def is_known(self, word):
            return False
        def prepare(self, *args, **kwargs):
            pass
        def value(self, fill, note, field):
            self.given += 1
            return ("<div>E1.4 drill</div>", None) if self.given <= limit else ("", "phrase")
        def close(self):
            pass
    report = backfill.run(settings, Stub(), wait=None, on_wait=on_wait)
print("result " + json.dumps({"report": {k: report.get(k) for k in ("ok", "busy", "message", "problems", "written")},
                              "log": log, "waited": waited}, ensure_ascii=False), flush=True)
"""


def _env():
    env = {k: v for k, v in os.environ.items() if k not in ("SURASURA_TEST_ROOT", "PYTEST_CURRENT_TEST")}
    env.update(APPDATA=os.path.join(_ROOT, ".appdata"), LOCALAPPDATA=os.path.join(_ROOT, ".localappdata"),
               SURASURA_DRILL=DRILL, PYTHONIOENCODING="utf-8")
    return env


def _start(role, settings, slow=0.0, limit=0):
    return subprocess.Popen([sys.executable, "-c", _CHILD, role, json.dumps(settings), str(slow), str(limit)],
                            cwd=_ROOT, env=_env(), stdout=subprocess.PIPE, text=True, encoding="utf-8")


def _result(process):
    out, _ = process.communicate(timeout=600)
    found = [json.loads(line[len("result "):]) for line in out.splitlines() if line.startswith("result ")]
    assert found, out
    assert "refused" not in found[0], found[0]
    return found[0]


def _writes(log):
    from app import anki_connect
    return [(sent, answered) for sent, answered, action, subs in log
            if anki_connect._write_in(action, {"actions": [{"action": name} for name in subs]})]


@pytest.fixture
def drill(monkeypatch):
    """The parent reads and restores through the same user data the children use."""
    from app import path_utils
    os.makedirs(os.path.join(DRILL, "results"), exist_ok=True)
    monkeypatch.setattr(path_utils, "get_user_data_path", lambda: DRILL)
    monkeypatch.setattr(path_utils, "get_persistent_user_data_path", lambda: os.path.join(_ROOT, ".appdata"))
    yield DRILL


def _state(url, deck):
    """Every new card's position, and every note's fields and tags, as Anki holds them now (reads only)."""
    from app import anki_connect
    from modules.junban import ankiconnect
    cards = anki_connect.cards_info(url, ankiconnect.find_new_cards(url, ankiconnect.new_card_query(deck)))
    notes = anki_connect.notes_info(url, sorted({card["note"] for card in cards}))
    return ({card["cardId"]: card["due"] for card in cards},
            {note["noteId"]: ({name: f["value"] for name, f in note["fields"].items()}, sorted(note.get("tags") or []))
             for note in notes}, cards, notes)


def test_two_processes_never_write_anki_at_once_and_restore_puts_the_deck_back(drill):
    from app import anki_connect
    import modules.junban as junban
    from modules.junban import auto, backfill, reposition

    assert DECK, "name a DevTest deck: SURASURA_LIVE_ANKI_DECK"
    assert anki_connect.invoke("getActiveProfile", URL) == "DevTest", "not DevTest: nothing written"
    dues, notes, cards, infos = _state(URL, DECK)
    assert cards, f"no new cards in {DECK}"

    # A priority list that ranks the deck's own words in the reverse of their queue order: every card moves.
    by_due = sorted(cards, key=lambda card: card["due"])
    words = {note["noteId"]: reposition._note_values(note) for note in infos}
    first = {note["noteId"]: sorted(note["fields"].items(), key=lambda kv: kv[1]["order"])[0][1]["value"]
             for note in infos}
    ranked = list(dict.fromkeys(first[card["note"]] for card in reversed(by_due) if first.get(card["note"])))
    with open(os.path.join(DRILL, "results", "priority_learning_list.csv"), "w", encoding="utf-8-sig",
              newline="") as handle:
        handle.write("Word,Orth,Reading,Tier\n")
        for word in ranked:
            handle.write('"{0}","{0}","",NOW\n'.format(word.replace('"', '""')))
    del words

    reorder = dict(junban.SETTINGS_DEFAULTS, **auto._POSITIONS_ONLY)
    reorder.update(target_language="ja", anki_connect_url=URL, junban_scope="deck", junban_deck=DECK,
                   junban_order="priority", junban_chunk_size=1)
    models = sorted({note["modelName"] for note in infos})
    fill = dict(junban.SETTINGS_DEFAULTS, target_language="ja", anki_connect_url=URL, junban_backfill_deck=DECK,
                junban_backfill_fills=["patterns"], junban_backfill_cards="new", junban_backfill_replace=True,
                junban_chunk_size=1, junban_backfill_note_languages={model: "ja" for model in models})

    assert len(cards) >= 2, "A needs two writes or more to write for 10 s"
    slow = 12.0 / (len(cards) - 1)
    holder = os.path.join(_ROOT, ".localappdata", "SonicSandbox", "Surasura", "locks", "anki-writer.holder.json")
    a = _start("reorder", reorder, slow=slow)
    deadline = time.monotonic() + 120
    while not os.path.exists(holder) and time.monotonic() < deadline and a.poll() is None:
        time.sleep(0.05)
    time.sleep(2.0)                     # 2 s into A, which holds the lock
    b = _start("fill", fill, limit=10)
    try:
        a_out, b_out = _result(a), _result(b)       # inside: a child that dies still gets the deck restored
        assert a_out["report"]["ok"] and a_out["report"]["written"], a_out["report"]
        assert b_out["report"]["ok"] and b_out["report"]["written"], b_out["report"]
        a_writes, b_writes = _writes(a_out["log"]), _writes(b_out["log"])
        assert a_writes[-1][1] - a_writes[0][0] >= 10.0, "A wrote for at least 10 s"
        assert [holder["verb"] for holder in b_out["waited"]] == ["順 reorder"], "B waited, naming A"
        for b_sent, b_answered in b_writes:
            for a_sent, a_answered in a_writes:
                assert b_answered <= a_sent or a_answered <= b_sent, "no write of B overlaps one of A's"
        assert b_writes[0][0] >= a_writes[-1][1]
        # Anki's own clock, whole seconds: a cross-check only.
        a_mod = max(card["mod"] for card in anki_connect.cards_info(URL, a_out["report"]["written"]))
        b_mod = min(note["mod"] for note in anki_connect.notes_info(URL, b_out["report"]["written"]))
        assert b_mod >= a_mod
        print(f"\nA: {len(a_writes)} writes over {a_writes[-1][1] - a_writes[0][0]:.1f} s; "
              f"B: {len(b_writes)} writes from {b_writes[0][0] - a_writes[-1][1]:+.3f} s after A's last; "
              f"mod A {a_mod} <= B {b_mod}")
    finally:
        # The way back, whatever happened above: both children gone, then Junban's Restore, then Backfill's.
        for child in (a, b):
            if child.poll() is None:
                child.kill()
                child.wait(30)
        assert anki_connect.invoke("getActiveProfile", URL) == "DevTest"
        restored = reposition.restore(reorder)
        refilled = backfill.restore(fill)
        print(f"restore: {restored['message']} / {refilled['message']}")
    after_dues, after_notes, _cards, _infos = _state(URL, DECK)
    assert after_dues == dues, "every card back where it was"
    assert after_notes == notes, "every field and tag back as it was"
    shutil.rmtree(DRILL, ignore_errors=True)
    shutil.rmtree(os.path.join(_ROOT, ".localappdata"), ignore_errors=True)     # the two children's lock folder
