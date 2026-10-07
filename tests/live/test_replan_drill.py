"""The live drill of the fast re-plan's preview (E1.1 05 §7; RUNBOOK E3.1.6): the Content Manager, one real Anki.

**Skipped unless `SURASURA_LIVE_ANKI=DevTest`** — it writes to Anki. Only on the DevTest profile, holding the program's
`anki.lock`, with Sonic's OK through the program lead (E3.1-A1); `sync` only with E3.1-A2's OK (`SURASURA_LIVE_SYNC=1`,
DevTest's throwaway AnkiWeb account — without it every sync is refused and the log is checked for none); the phone
step only with E3.1-A3's (`SURASURA_LIVE_PHONE=1`: the drill waits for `debug/E3.1/drill/phone-done`):

    SURASURA_LIVE_ANKI=DevTest SURASURA_LIVE_SYNC=1 SURASURA_LIVE_PHONE=1 [SURASURA_LIVE_CARDS=2000]
        python -m pytest tests/live/test_replan_drill.py -s -p no:randomly

Before anything, AnkiConnect's `getActiveProfile` must answer DevTest, or the drill stops and writes nothing.

In a scratch data root (`debug/E3.1/drill-root`: its own settings.json, library, results, stores, lock folder and
sync state — never the user's): RP-2's Japanese library generated with the preview on; a deck of its own in DevTest,
"E3.1 drill", of SURASURA_LIVE_CARDS made-up notes (Basic: Front = a word of the library's list, then of the shipped
list; Back = a sentence; tag `surasura-e31-drill`), queued in the reverse of the list's order, synced up. With the
phone step, the drill then waits while one card is reviewed on the phone and synced. Then the real Content Manager
window (in this process): its open and the first job — the session sync (S1, which must bring the phone's review in:
that card is never written) and the one full spacing — timed; a second window opened and moved at once (the cold load
counted); then moves of the study's kinds in a warm window, each timed from the move: tomorrow's cards landed (the
first write request's answer) and every card landed, the window's thread watched by a 1 ms timer (its worst gap).
Every AnkiConnect request is logged with its time. Last, the deck is deleted with its cards and read back gone; Anki
stays open on DevTest. Results: `debug/E3.1/drill/drill-<time>.json` and the printed summary.
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
PHONE = os.environ.get("SURASURA_LIVE_PHONE") == "1"
DECK = "E3.1 drill"
TAG = "surasura-e31-drill"
DRILL = os.path.join(_ROOT, "debug", "E3.1", "drill-root")
OUT = os.path.join(_ROOT, "debug", "E3.1", "drill")
PHONE_DONE = os.path.join(OUT, "phone-done")


def _words(root, n):
    """The library's own list words first (so the plan places them), then the shipped list's."""
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
    base = list(words)
    while len(words) < n:                     # more cards than words: a word mined twice (another sentence)
        words.extend(base[: n - len(words)])
    return words[:n]


def _devtest():
    """Anki is on DevTest — asked again before every step that writes or syncs (the profile can change under a
    long wait)."""
    from app import anki_connect
    try:
        return anki_connect.invoke("getActiveProfile", URL, timeout=5) == "DevTest"
    except Exception:
        return False


def _say(text):
    print(time.strftime("%H:%M:%S"), text, flush=True)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "progress.log"), "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + text + "\n")


def test_the_preview_moves_reach_real_anki_tomorrow_first(monkeypatch):
    from app import anki_connect, locks
    assert anki_connect.invoke("getActiveProfile", URL) == "DevTest", "not DevTest: the drill writes nothing"

    # --- the scratch root ------------------------------------------------------------------------------------- #
    shutil.rmtree(DRILL, ignore_errors=True)
    os.makedirs(OUT, exist_ok=True)
    if os.path.exists(PHONE_DONE):
        os.remove(PHONE_DONE)
    root = os.path.join(DRILL, "lib")
    from tests import plan_file_cases as cases
    env = cases.child_env(root)
    for name in ("SURASURA_TEST_ROOT", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(name, env[name])
    for name in ("SURASURA_NO_ANKI_SYNC", "SURASURA_NO_UI_TIMERS"):
        monkeypatch.delenv(name, raising=False)
    cases.build(root, "rp2-ja")
    settings = {"junban_replan_preview": True, "junban_replan_language": "ja", "junban_deck": DECK,
                "junban_scope": "deck", "junban_order": "content", "anki_connect_url": URL, "target_language": "ja",
                "junban_word_fields": {"Basic": "Front"}, "anki_sync_delay_min": 1}
    with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False)
    from app.path_utils import ensure_data_setup
    ensure_data_setup("ja")
    from tests.test_replan_preview import _generate
    _generate(root)
    _say("library generated (preview on)")
    if not SYNC:
        monkeypatch.setattr(anki_connect, "sync", lambda url, timeout=120: "failed: no sync in this drill")

    # --- every request, timed --------------------------------------------------------------------------------- #
    real, log = urllib.request.urlopen, []

    def logged(request, timeout=None):
        payload = json.loads(request.data.decode("utf-8"))
        params = payload.get("params") or {}
        subs = [e for e in params.get("actions") or [] if isinstance(e, dict)]
        sent = time.perf_counter()
        with real(request, timeout=timeout) as response:
            body = response.read()
        log.append({"at": sent, "took": time.perf_counter() - sent, "action": payload["action"], "subs": len(subs),
                    "sub": subs[0].get("action") if subs else None,
                    "cards": [s["params"]["card"] for s in subs if s.get("action") == "setSpecificValueOfCard"]})
        return io.BytesIO(body)
    monkeypatch.setattr(urllib.request, "urlopen", logged)

    # --- the deck, synced up ------------------------------------------------------------------------------------ #
    words = _words(root, CARDS)
    with locks.take(anki_connect.WRITER_LOCK, "the E3.1 drill"):
        anki_connect.invoke("createDeck", URL, deck=DECK)
        note_ids = []
        for start in range(0, len(words), 250):
            notes = [{"deckName": DECK, "modelName": "Basic", "tags": [TAG],
                      "fields": {"Front": word, "Back": f"{word}を使った文。（{start + i}）"},
                      "options": {"allowDuplicate": True}} for i, word in enumerate(words[start:start + 250])]
            note_ids += anki_connect.invoke("addNotes", URL, timeout=120, notes=notes)
        cards = anki_connect.find_cards(URL, f'deck:"{DECK}"')
        info = anki_connect.cards_info(URL, cards)
        card_of = {row["note"]: row["cardId"] for row in info}
        in_order = [card_of[n] for n in note_ids if n in card_of]       # one card a note, as the words go
        pairs = [(card_id, 1000 + len(in_order) - 1 - i) for i, card_id in enumerate(in_order)]
        for start in range(0, len(pairs), 150):
            anki_connect.multi([{"action": "setSpecificValueOfCard",
                                 "params": {"card": c, "keys": ["due"], "newValues": [d]}}
                                for c, d in pairs[start:start + 150]], URL)
        if SYNC:
            summary_setup_sync = anki_connect.sync(URL)
        else:
            summary_setup_sync = "off"
    summary = {"cards": len(pairs), "sync": SYNC, "phone": PHONE, "setup_sync": summary_setup_sync, "moves": []}
    _say(f"deck '{DECK}' made: {len(pairs)} cards, synced: {summary_setup_sync}")

    if PHONE:
        first_word = words[-1]
        _say(f"PHONE: waiting for {PHONE_DONE} — on the phone, review the first new card of '{DECK}' "
             f"(its front should be {first_word}), then sync")
        deadline = time.monotonic() + 45 * 60
        while not os.path.exists(PHONE_DONE) and time.monotonic() < deadline:
            time.sleep(2)
        summary["phone_done"] = os.path.exists(PHONE_DONE)
        _say(f"PHONE: done={summary['phone_done']}")
    assert _devtest(), "Anki is no longer on DevTest: the drill stops here (its deck stays, said in the summary)"

    # --- the window ------------------------------------------------------------------------------------------- #
    import tkinter as tk
    from app import anki_sync_rule
    from app import content_importer_gui as cig
    from app.content_importer_gui import ContentImporterApp
    gaps, last = [], [time.perf_counter()]

    def open_window():
        cig._DIALOGS[0] = 0
        tk_root = tk.Tk()
        app = ContentImporterApp(tk_root, "ja")

        def tick():
            now = time.perf_counter()
            gaps.append(now - last[0])
            last[0] = now
            tk_root.after(1, tick)
        tk_root.after(1, tick)
        return tk_root, app

    def pump(tk_root, until, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            tk_root.update()
            if until():
                return True
            time.sleep(0.002)
        return False

    def close(tk_root, app):
        """Esc: a running job and a pending sync finish first (at most 15 s), then the window goes."""
        app._close_window()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                tk_root.update()
                tk_root.winfo_exists()
            except tk.TclError:
                return
            time.sleep(0.01)

    def timed_move(tk_root, app, name, pick):
        store = app._store()
        item, tier, before = pick(store)
        gaps.clear()
        n0 = len(log)
        t_move = time.perf_counter()
        change = store.move([item], tier, before_id=before)
        app._store_did(change, "Move")
        host = app.__dict__.get("_replan")
        ok = pump(tk_root, lambda: (app.__dict__.get("_replan") is not None and not app._replan.busy()
                                    and any(e["sub"] == "setSpecificValueOfCard" for e in log[n0:])), 60)
        if not ok:                                           # a move that changes no card's place writes nothing
            ok = app.__dict__.get("_replan") is not None and not app._replan.busy()
        host = app.__dict__.get("_replan")
        writes = [e for e in log[n0:] if e["sub"] == "setSpecificValueOfCard"]
        row = {"move": name, "ok": ok, "line": host.last if host else None,
               "requests": len(log) - n0, "write_requests": len(writes), "cards_written": sum(e["subs"] for e in writes),
               "tomorrow_landed_s": round(writes[0]["at"] + writes[0]["took"] - t_move, 3) if writes else None,
               "all_landed_s": round(writes[-1]["at"] + writes[-1]["took"] - t_move, 3) if writes else None,
               "tk_worst_gap_ms": round(max(gaps[1:]) * 1000, 1) if len(gaps) > 1 else None,
               "cardsInfo_ms": [round(e["took"] * 1000, 1) for e in log[n0:] if e["action"] == "cardsInfo"],
               "reads_ms": {a: [round(e["took"] * 1000, 1) for e in log[n0:] if e["action"] == a]
                            for a in ("findCards", "cardsModTime", "notesModTime", "getActiveProfile", "sync")}}
        summary["moves"].append(row)
        _say(f"move '{name}': {row['tomorrow_landed_s']} s tomorrow, {row['all_landed_s']} s all, "
             f"{row['cards_written']} cards, Tk worst {row['tk_worst_gap_ms']} ms — {row['line']}")
        return row

    kinds = [("6+ Months' last → NOW's top", lambda s: (s.ids("goal")[-1], "now", s.ids("now")[0])),
             ("within NOW, second → first", lambda s: (s.ids("now")[1], "now", s.ids("now")[0])),
             ("Soon's first → NOW's top", lambda s: (s.ids("soon")[0], "now", s.ids("now")[0])),
             ("NOW's top → 6+ Months' end", lambda s: (s.ids("now")[0], "goal", None)),
             ("6+ Months' first → Soon's top", lambda s: (s.ids("goal")[0], "soon", s.ids("soon")[0]))]
    tk_root = app = None
    try:
        # 1. The first window: its open's catch-up is the first job — S1, the one full spacing.
        tk_root, app = open_window()
        n0 = len(log)
        t0 = time.perf_counter()
        assert pump(tk_root, lambda: app.__dict__.get("_replan") is not None, 60), "no host: is the preview on?"
        assert pump(tk_root, lambda: not app._replan.busy() and log[n0:], 900), "the first job never finished"
        summary["first_job_s"] = round(time.perf_counter() - t0, 2)
        summary["first_line"] = app._replan.last
        summary["first_cards_written"] = sum(e["subs"] for e in log[n0:] if e["sub"] == "setSpecificValueOfCard")
        summary["first_syncs"] = [round(e["took"], 2) for e in log[n0:] if e["action"] == "sync"]
        reviewed = [row["cardId"] for row in anki_connect.cards_info(URL, cards) if row.get("type") != 0]
        written = {c for e in log[n0:] for c in e["cards"]}          # the preview's writes (not the set-up's)
        summary["phone_reviewed_cards"] = reviewed
        summary["phone_reviewed_written"] = sorted(set(reviewed) & written)
        _say(f"first job: {summary['first_job_s']} s, {summary['first_cards_written']} cards, syncs "
             f"{summary['first_syncs']}, reviewed on the phone {reviewed} (written: {summary['phone_reviewed_written']})")
        close(tk_root, app)
        # 2. A second window, moved at once: its engine and Junban's tables load inside that move.
        assert _devtest(), "Anki left DevTest"
        tk_root, app = open_window()
        pump(tk_root, lambda: app.__dict__.get("_replan") is not None, 30)
        timed_move(tk_root, app, "cold: " + kinds[0][0], kinds[0][1])
        # 3. Warm moves in the same window.
        for name, pick in kinds[1:]:
            timed_move(tk_root, app, name, pick)
        if SYNC:
            summary["sync_state"] = anki_sync_rule.read_state()
        close(tk_root, app)
    finally:
        try:
            if tk_root is not None:
                tk_root.destroy()
        except Exception:
            pass
        # --- put back: the drill's deck deleted with its cards, read back ---------------------------------------- #
        monkeypatch.setattr(urllib.request, "urlopen", real)
        try:
            host = app.__dict__.get("_replan") if app is not None else None
            if host is not None:
                host.stop()
            if not _devtest():
                raise RuntimeError("Anki is not on DevTest: nothing deleted, nothing synced — the deck stays")
            with locks.take(anki_connect.WRITER_LOCK, "the E3.1 drill (clean-up)", wait=180):
                if DECK in anki_connect.deck_names(URL):
                    anki_connect.invoke("deleteDecks", URL, decks=[DECK], cardsToo=True)
                notes = anki_connect.find_notes(URL, f"tag:{TAG}")
                if notes:
                    anki_connect.invoke("deleteNotes", URL, notes=notes)
                if SYNC and _devtest():
                    summary["cleanup_sync"] = anki_connect.sync(URL)     # the throwaway account loses the deck too
            summary["left_after_cleanup"] = (len(anki_connect.find_notes(URL, f"tag:{TAG}"))
                                             + (DECK in anki_connect.deck_names(URL)))
        except Exception as e:
            summary["cleanup_error"] = str(e)
            summary["left_after_cleanup"] = -1
        path = os.path.join(OUT, time.strftime("drill-%Y%m%d-%H%M%S.json"))
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "log": log}, f, ensure_ascii=False, indent=1)
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        _say(f"written {path}")
    assert summary["left_after_cleanup"] == 0
    assert not summary["phone_reviewed_written"], "a card reviewed on the phone was written"
    if not SYNC:
        assert not any(e["action"] == "sync" for e in log), "a sync in a drill without SURASURA_LIVE_SYNC"
    assert all(move["ok"] for move in summary["moves"]), summary["moves"]
