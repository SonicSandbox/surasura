"""The live drill of the fast re-plan's preview (E1.1 05 §7; RUNBOOK E3.1.6): the Content Manager, one real Anki.

**Skipped unless `SURASURA_LIVE_ANKI=DevTest`** — it writes to Anki. Only on the DevTest profile, holding the program's
`anki.lock`, with Sonic's OK through the program lead (E3.1-A1); `sync` only with E3.1-A2's OK
(`SURASURA_LIVE_SYNC=1`, DevTest's throwaway AnkiWeb account):

    SURASURA_LIVE_ANKI=DevTest [SURASURA_LIVE_SYNC=1] [SURASURA_LIVE_CARDS=2000] python -m pytest tests/live/test_replan_drill.py -s

Before anything, AnkiConnect's `getActiveProfile` must answer DevTest, or the drill stops and writes nothing.

What it does, in a scratch data root inside the copy (`.drill-e31`: its own settings.json, library, results, store,
lock folder — never the user's): RP-2's Japanese library generated with the preview on; a deck of its own, "E3.1
drill", of SURASURA_LIVE_CARDS made-up notes (note type Basic: Front = a word of the library's list or of the shipped
frequency list, Back = a sentence; tag `surasura-e31-drill`), queued in the reverse of the list's order. Then the real
Content Manager window (in this process): its open (the host warms), the first job (the one full spacing, timed), then
moves of the study's kinds, each timed from the move: tomorrow's cards landed, every card landed, with the window's
thread watched by a 1 ms timer (its worst gap). Every AnkiConnect request is logged with its time (the warm map's
Anki side, the re-check's `cardsInfo`). Last, the drill's notes are deleted (`deleteNotes` by its tag), and the
deck deleted, both read back. Results: `debug/E3.1/drill/drill-<time>.json` and the printed summary.
"""
import io
import json
import os
import shutil
import time
import urllib.request

import pytest

LIVE = os.environ.get("SURASURA_LIVE_ANKI") == "DevTest"
pytestmark = pytest.mark.skipif(not LIVE, reason="writes to Anki: SURASURA_LIVE_ANKI=DevTest only")

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
URL = os.environ.get("SURASURA_LIVE_ANKI_URL", "http://127.0.0.1:8765")
CARDS = int(os.environ.get("SURASURA_LIVE_CARDS", "2000"))
SYNC = os.environ.get("SURASURA_LIVE_SYNC") == "1"
DECK = "E3.1 drill"
TAG = "surasura-e31-drill"
DRILL = os.path.join(_ROOT, ".drill-e31")
OUT = os.path.join(_ROOT, "debug", "E3.1", "drill")


def _words(root, n):
    """The library's own list words first (so the plan places them), then the shipped frequency list's."""
    import csv
    from tests.test_replan_preview import _list_words
    words = _list_words(root)
    path = os.path.join(_ROOT, "tests", "Test Resources", "ja", "expected_output.csv")
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            key = (row.get("Orth") or row.get("Word") or "").strip()
            if key and key not in words:
                words.append(key)
            if len(words) >= n:
                break
    return words[:n]


def test_the_preview_moves_reach_real_anki_tomorrow_first(monkeypatch):
    from app import anki_connect
    assert anki_connect.invoke("getActiveProfile", URL) == "DevTest", "not DevTest: the drill writes nothing"

    # --- the scratch root ------------------------------------------------------------------------------------- #
    shutil.rmtree(DRILL, ignore_errors=True)
    root = os.path.join(DRILL, "lib")
    from tests import plan_file_cases as cases
    env = cases.child_env(root)
    for name in ("SURASURA_TEST_ROOT", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(name, env[name])
    for name in ("SURASURA_NO_ANKI_SYNC", "SURASURA_NO_UI_TIMERS"):
        monkeypatch.delenv(name, raising=False)
    cases.build(root, "rp2-ja")
    settings = {"junban_replan_preview": True, "junban_deck": DECK, "junban_scope": "deck", "junban_order": "content",
                "anki_connect_url": URL, "target_language": "ja", "junban_word_fields": {"Basic": "Front"},
                "anki_sync_delay_min": 1 if SYNC else "off"}
    with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False)
    from app.path_utils import ensure_data_setup
    ensure_data_setup("ja")
    from tests.test_replan_preview import _generate
    _generate(root)

    # --- every request, timed --------------------------------------------------------------------------------- #
    real, log = urllib.request.urlopen, []

    def logged(request, timeout=None):
        payload = json.loads(request.data.decode("utf-8"))
        subs = [e.get("action") for e in (payload.get("params") or {}).get("actions") or [] if isinstance(e, dict)]
        sent = time.perf_counter()
        with real(request, timeout=timeout) as response:
            body = response.read()
        log.append({"at": sent, "took": time.perf_counter() - sent, "action": payload["action"],
                    "subs": len(subs), "sub": subs[0] if subs else None})
        return io.BytesIO(body)
    monkeypatch.setattr(urllib.request, "urlopen", logged)

    # --- the deck --------------------------------------------------------------------------------------------- #
    words = _words(root, CARDS)
    from app import locks
    with locks.take(anki_connect.WRITER_LOCK, "the E3.1 drill"):
        anki_connect.invoke("createDeck", URL, deck=DECK)
        for start in range(0, len(words), 250):
            notes = [{"deckName": DECK, "modelName": "Basic", "tags": [TAG],
                      "fields": {"Front": word, "Back": f"{word}を使った文。"},
                      "options": {"allowDuplicate": True}} for word in words[start:start + 250]]
            anki_connect.invoke("addNotes", URL, timeout=120, notes=notes)
        cards = anki_connect.find_cards(URL, f'deck:"{DECK}"')
        info = anki_connect.cards_info(URL, cards)
        by_word = {row["fields"]["Front"]["value"]: row["cardId"] for row in info}
        # Reverse of the list: the plan must move nearly every card (the first spacing), then tens per move.
        base = 1000
        pairs = [(by_word[w], base + i) for i, w in enumerate(reversed(words)) if w in by_word]
        for start in range(0, len(pairs), 150):
            anki_connect.multi([{"action": "setSpecificValueOfCard",
                                 "params": {"card": c, "keys": ["due"], "newValues": [d]}}
                                for c, d in pairs[start:start + 150]], URL)
    summary = {"cards": len(pairs), "sync": SYNC, "moves": []}

    # --- the window ------------------------------------------------------------------------------------------- #
    import tkinter as tk
    from app import content_importer_gui as cig
    from app.content_importer_gui import ContentImporterApp
    cig._DIALOGS[0] = 0
    tk_root = tk.Tk()
    app = ContentImporterApp(tk_root, "ja")
    gaps, last = [], [time.perf_counter()]

    def tick():
        now = time.perf_counter()
        gaps.append(now - last[0])
        last[0] = now
        tk_root.after(1, tick)
    tk_root.after(1, tick)

    def pump(until, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            tk_root.update()
            if until():
                return True
            time.sleep(0.002)
        return False

    try:
        pump(lambda: app.__dict__.get("_replan") is not None, 30)
        host = app._replan
        assert host is not None, "the window started no host: is the preview on?"
        t0 = time.perf_counter()
        n0 = len(log)
        assert pump(lambda: not host.busy() and log[n0:], 600), "the first job never finished"
        summary["first_spacing_s"] = round(time.perf_counter() - t0, 2)
        summary["first_line"] = host.last
        store = app._store()

        kinds = [("6+ Months' last → NOW's top", lambda: (store.ids("goal")[-1], "now", store.ids("now")[0])),
                 ("within NOW, second → first", lambda: (store.ids("now")[1], "now", store.ids("now")[0])),
                 ("Soon's first → NOW's top", lambda: (store.ids("soon")[0], "now", store.ids("now")[0])),
                 ("NOW's top → 6+ Months' end", lambda: (store.ids("now")[0], "goal", None)),
                 ("6+ Months' last → NOW's top (again)", lambda: (store.ids("goal")[-1], "now", store.ids("now")[0]))]
        for name, pick in kinds:
            item, tier, before = pick()
            gaps.clear()
            n0 = len(log)
            t_move = time.perf_counter()
            change = store.move([item], tier, before_id=before)
            app._store_did(change, "Move")
            ok = pump(lambda: not host.busy() and any(e["sub"] == "setSpecificValueOfCard" for e in log[n0:]), 120)
            pump(lambda: not host.busy(), 60)
            writes = [e for e in log[n0:] if e["sub"] == "setSpecificValueOfCard"]
            first_write_end = (writes[0]["at"] + writes[0]["took"] - t_move) if writes else None
            last_write_end = (writes[-1]["at"] + writes[-1]["took"] - t_move) if writes else None
            summary["moves"].append({
                "move": name, "ok": ok, "line": host.last,
                "requests": len(log) - n0, "write_requests": len(writes), "cards_written": sum(e["subs"] for e in writes),
                "tomorrow_landed_s": round(first_write_end, 3) if first_write_end is not None else None,
                "all_landed_s": round(last_write_end, 3) if last_write_end is not None else None,
                "tk_worst_gap_ms": round(max(gaps[1:]) * 1000, 1) if len(gaps) > 1 else None,
                "cardsInfo_ms": [round(e["took"] * 1000, 1) for e in log[n0:] if e["action"] == "cardsInfo"],
                "modtime_ms": [round(e["took"] * 1000, 1) for e in log[n0:]
                               if e["action"] in ("cardsModTime", "notesModTime", "findCards")]})
        if SYNC:
            from app import anki_sync_rule
            summary["sync_state"] = anki_sync_rule.read_state()
        app._close_window()
        pump(lambda: False, 2)
    finally:
        try:
            tk_root.destroy()
        except Exception:
            pass
        # --- put back: the drill's notes deleted, read back ------------------------------------------------- #
        monkeypatch.setattr(urllib.request, "urlopen", real)
        with locks.take(anki_connect.WRITER_LOCK, "the E3.1 drill (clean-up)"):
            notes = anki_connect.find_notes(URL, f"tag:{TAG}")
            if notes:
                anki_connect.invoke("deleteNotes", URL, notes=notes)
            if DECK in anki_connect.deck_names(URL):
                anki_connect.invoke("deleteDecks", URL, decks=[DECK], cardsToo=True)
        summary["left_after_cleanup"] = (len(anki_connect.find_notes(URL, f"tag:{TAG}"))
                                         + (DECK in anki_connect.deck_names(URL)))
        os.makedirs(OUT, exist_ok=True)
        path = os.path.join(OUT, time.strftime("drill-%Y%m%d-%H%M%S.json"))
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "log": log}, f, ensure_ascii=False, indent=1)
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        print("written", path)
    assert summary["left_after_cleanup"] == 0
    assert all(move["ok"] for move in summary["moves"]), summary["moves"]
