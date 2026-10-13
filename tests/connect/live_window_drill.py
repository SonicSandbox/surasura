"""P3.1's window proof on DevTest (row 3.1.10 (a)): the Connect preview driven through the 2.x dashboard's own code on a
real Tk root against the real Anki. Never run by the suites; by hand, with locks/anki.lock taken by hand (board lines)
and Anki open on DevTest:

    python tests/connect/live_window_drill.py --profile DevTest [--shots <folder>] [--scale 1.0]

- **Switch on** through Settings' own handler (`_connect_switch_toggled`): the watermarks, `connect_enabled` saved, the
  line's row built.
- **A batch** seeded as live_undo_drill.py seeds one: four Basic notes in deck DevTest, each front a real word, one
  finished job of a scratch ledger on an item of a scratch library (its subtitle a real one, its title synthetic); two
  more notes put on the shelf as two restore points; one *Needs you* entry on the item.
- **The row**: its line and the filled badge; the window opened from it; what it shows marked seen (the badge
  outlined); the entry dismissed (the badge gone).
- **Undo this batch** pressed in the window, its question answered yes: exactly the two untouched notes go; the
  studied and the edited stay, each with its why.
- **Put back** pressed on one restore point in the window (asked yes): its card un-suspended.
- **Switch off** with a card still on the shelf: the put-back question (answered yes), the card back, the switch saved
  off, the row gone.
- DPI-aware screenshots of the dashboard row and the Connect window at each step (`--shots`).

`getActiveProfile == "DevTest"` before every write and before teardown. Teardown: every note with the drill's tag
deleted (a test-only delete, holding `anki-writer`) and counted back to 0. Everything else lives under a temp
`SURASURA_TEST_ROOT`: Sonic's settings, library, ledger and Anki Miner are never opened; no Anki Miner runs; Connect is
never kicked (kick refuses under a test root).
"""
import argparse
import ctypes
import json
import os
import shutil
import sys
import tempfile
import time
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESOURCES = os.path.join(REPO, "tests", "Test Resources")
WORDS = ["上層部", "一生懸命", "走り出す", "気配"]          # the batch: untouched ×2, studied, edited
SHELF_WORDS = ["溜め息", "約束"]                          # two restore points: put back in the window, at switch-off
TITLE = "Drill Show - 01"


def say(*parts):
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


class Stop(Exception):
    pass


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--profile", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--deck", default="DevTest")
    ap.add_argument("--shots", default=None)
    ap.add_argument("--scale", type=float, default=1.0)
    a = ap.parse_args()
    if a.profile != "DevTest" or a.deck != "DevTest":
        sys.exit("REFUSED: the drill runs on the DevTest profile and deck only")
    root_dir = tempfile.mkdtemp(prefix="p31-window-")
    os.environ["SURASURA_TEST_ROOT"] = root_dir
    for name in ("SURASURA_NO_UI_TIMERS", "SURASURA_NO_UPDATE_CHECK", "SURASURA_NO_AUTOINDEX"):
        os.environ[name] = "1"
    os.environ.pop("SURASURA_NO_ANKI_SYNC", None)          # undo.act reaches Anki only without it
    os.environ.pop("SURASURA_CONNECT_KICK", None)          # no Connect started by the drill
    sys.path.insert(0, REPO)
    os.chdir(REPO)
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    from app import anki_connect

    def ask(action, **params):
        return anki_connect.invoke(action, a.url, timeout=120, **params)

    def devtest():
        try:
            return ask("getActiveProfile") == "DevTest"
        except anki_connect.AnkiError:
            return False

    def guard(what):
        if not devtest():
            raise Stop(f"Anki isn't on DevTest before {what}")

    if not devtest():
        sys.exit("REFUSED: Anki isn't open on DevTest")
    run = time.strftime("%Y%m%d%H%M%S")
    drill_tag = f"surasura::connect::test-p31window-{run}"
    out = {"root": root_dir, "drill_tag": drill_tag, "checks": {}, "times": {}, "shots": []}
    checks = out["checks"]
    started = time.monotonic()

    # --- the scratch library and settings ------------------------------------------------------------------- #
    data = os.path.join(root_dir, "data", "ja", "HighPriority")
    os.makedirs(data, exist_ok=True)
    shutil.copy2(os.path.join(RESOURCES, "ja", "phrases_sample.srt"), os.path.join(data, f"{TITLE}.ja.srt"))
    user = os.path.join(root_dir, "User Files", "ja")
    os.makedirs(user, exist_ok=True)
    shutil.copy2(os.path.join(RESOURCES, "ja", "KnownWord.json"), os.path.join(user, "KnownWord.json"))
    settings = {"target_language": "ja", "onboarding_completed": True, "anki_connect_url": a.url,
                "enable_junban": True, "junban_deck": "DevTest", "anki_sync_decks": {"ja": ["DevTest"]},
                "anki_sync_auto": False, "connect_open_anki": False}
    with open(os.path.join(root_dir, "settings.json"), "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False)
    from app import library_store
    from app.path_utils import get_data_path, get_user_files_path
    assert library_store.maintain("ja", get_data_path("ja"), get_user_files_path("ja"),
                                  from_folders=True) == library_store.EXIT_DONE

    # --- the dashboard, on a real Tk root ------------------------------------------------------------------- #
    import tkinter as tk
    from PIL import ImageGrab
    from app import main as dashboard_main
    tk_root = tk.Tk()
    tk_root.tk.call("tk", "scaling", a.scale * 96 / 72)
    with mock.patch.object(dashboard_main.MasterDashboardApp, "check_updates_thread"):
        app = dashboard_main.MasterDashboardApp(tk_root)

    def pump(until=lambda: False, timeout=10.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            tk_root.update()
            if until():
                return True
            time.sleep(0.02)
        return bool(until())

    def shot(win, name):
        if not a.shots:
            return
        os.makedirs(a.shots, exist_ok=True)
        win.deiconify()
        win.lift()
        win.attributes("-topmost", True)
        pump(timeout=0.8)
        x, y, w, h = win.winfo_rootx(), win.winfo_rooty(), win.winfo_width(), win.winfo_height()
        path = os.path.join(a.shots, f"drill-{name}_{int(a.scale * 100)}.png")
        ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(path)
        win.attributes("-topmost", False)
        out["shots"].append(path)
        say("shot", path, w, h)

    def row_text():
        return app._connect_row.line.cget("text") if app._connect_row is not None else None

    ledger = None
    ids, cards = {}, {}
    try:
        pump(timeout=0.6)
        tk_root.deiconify()
        app.toggle_settings_window()
        pump(timeout=0.6)

        # --- switch on, through Settings' handler --------------------------------------------------------- #
        t = time.monotonic()
        app.var_connect_enabled.set(True)
        app._connect_switch_toggled()
        checks["switched_on"] = pump(lambda: "disabled" not in app.chk_connect.state()
                                     and app._connect_row is not None, timeout=30)
        out["times"]["switch_on_s"] = round(time.monotonic() - t, 2)
        with open(os.path.join(root_dir, "settings.json"), encoding="utf-8") as f:
            checks["saved_on"] = json.load(f).get("connect_enabled") is True
        shot(app.settings_window, "0-settings-on")
        app.settings_window.withdraw()
        say("switched on", checks["switched_on"], checks["saved_on"], row_text())

        # --- a batch, two restore points and one need (seeded) -------------------------------------------- #
        from app.connect import library, shelf, status, undo
        from app.connect.ledger import Ledger
        store = library.open_store("ja")
        with store:
            item = store.ids("now")[0]
            sid = library.store_id(store)
        guard("the batch")
        ledger = Ledger()
        job_id = ledger.queue("ja", item, "user", None, store_id=sid)
        job_tag = f"surasura::connect::{ledger.tag_id(job_id)}"
        model = "Basic" if "Basic" in ask("modelNames") else ask("modelNames")[0]
        front, back = ask("modelFieldNames", modelName=model)[:2]
        notes = [{"deckName": a.deck, "modelName": model, "options": {"allowDuplicate": True},
                  "tags": [drill_tag] + ([job_tag] if i < len(WORDS) else []),
                  "fields": {front: w, back: f"P3.1 window drill {i}"}} for i, w in enumerate(WORDS + SHELF_WORDS)]
        ledger.start_batch(job_id, 1, os.path.join(root_dir, "run"))
        with anki_connect.writer("P3.1 window drill", wait=60):
            made = ask("addNotes", notes=notes)
        for key, n in zip(("untouched1", "untouched2", "studied", "edited", "shelf_a", "shelf_b"), made):
            ids[key] = n
        ledger.end_batch(job_id, 1, "done", [{"word": w, "reading": "", "outcome": "made", "note_id": ids[k]}
                                             for k, w in zip(("untouched1", "untouched2", "studied", "edited"),
                                                             WORDS)])
        ledger.set_state(job_id, "done")
        card_of = {c["note"]: c["cardId"] for c in anki_connect.cards_info(
            a.url, ask("findCards", query=f'"tag:{drill_tag}"'))}
        cards.update({k: card_of[n] for k, n in ids.items()})
        sanki = shelf.AnkiConnectAnki(a.url)
        run_a = shelf.shelve(sanki, ledger, "ja", [shelf.Card(cards["shelf_a"], ids["shelf_a"], SHELF_WORDS[0],
                                                              item)], "the cap: more than 300 cards waiting")
        time.sleep(0.01)
        run_b = shelf.shelve(sanki, ledger, "ja", [shelf.Card(cards["shelf_b"], ids["shelf_b"], SHELF_WORDS[1],
                                                              item)], "the cap: more than 300 cards waiting")
        need_say = f"{TITLE}.ja.srt: Anki Miner stopped twice while making its cards."
        ledger.need("ja", "mine-failed", need_say, item_id=item, job_id=job_id)
        ledger.close()
        ledger = None
        out.update(job=job_id, item=item, job_tag=job_tag, notes=ids, runs=[run_a, run_b])
        say("seeded", job_tag, ids, run_a, run_b)

        # the learner's hand, after the grace: one card studied, one note edited
        time.sleep(undo.GRACE_S + 2)
        guard("the learner's hand")
        with anki_connect.writer("P3.1 window drill (learner)", wait=60):
            try:
                ask("answerCards", answers=[{"cardId": cards["studied"], "ease": 3}])
            except anki_connect.AnkiError:
                ask("setSpecificValueOfCard", card=cards["studied"], keys=["reps", "type", "queue"],
                    newValues=["1", "2", "2"], warning_check=True)
            ask("updateNoteFields", note={"id": ids["edited"], "fields": {back: "edited by hand"}})

        # --- the row: its line and the filled badge ------------------------------------------------------ #
        row = app._connect_row
        t = time.monotonic()
        row.refresh()
        checks["row_filled"] = pump(lambda: row.badge_shown == "filled" and row.record is not None
                                    and bool(row.record.get("undo")), timeout=15)
        out["times"]["row_redraw_s"] = round(time.monotonic() - t, 2)
        out["row_line"] = row_text()
        out["badge_text"] = row.badge.cget("text")
        checks["row_line"] = out["row_line"] == "Connect: " + (row.record or {}).get("line", "?")
        checks["badge_count"] = out["badge_text"] == "Needs you (1)"
        tk_root.geometry("")
        shot(tk_root, "1-dashboard-row-filled")
        say("row", out["row_line"], out["badge_text"])

        # --- the window: Needs you shown (marked seen), dismissed ---------------------------------------- #
        t = time.monotonic()
        app._open_connect_window()
        checks["window_opened"] = pump(lambda: app._connect_window is not None, timeout=15)
        out["times"]["window_open_s"] = round(time.monotonic() - t, 2)
        win = app._connect_window
        needs = (win.record or {}).get("needs") or []
        checks["need_listed"] = [n["say"] for n in needs] == [need_say]
        checks["seen_outlined"] = pump(lambda: row.badge_shown == "outlined", timeout=15)
        shot(win.win, "2-window-needs")
        shot(tk_root, "3-dashboard-row-seen")
        need_id = needs[0]["id"] if needs else None
        win.buttons[("needs", need_id, "Dismiss")].invoke()
        checks["dismissed_badge_gone"] = pump(lambda: row.badge_shown is None, timeout=15)
        checks["dismissed_listed_none"] = status.read(["ja"])["languages"]["ja"]["needs"] == []
        say("needs", checks["need_listed"], checks["seen_outlined"], checks["dismissed_badge_gone"])

        # --- Undo this batch, from the window ------------------------------------------------------------ #
        asked = []
        win.confirm = lambda title, text: (asked.append((title, text)), True)[1]
        win.tabs.select(1)
        shot(win.win, "4-window-batches")
        note = win.notes[("batch", job_id)]
        guard("the undo")
        t = time.monotonic()
        win.buttons[("batch", job_id, "Undo this batch")].invoke()
        pump(lambda: "deleted" in note.cget("text") or "Not done" in note.cget("text")
             or "isn't" in note.cget("text") or "couldn't" in note.cget("text").lower(), timeout=180)
        out["times"]["undo_s"] = round(time.monotonic() - t, 2)
        out["undo_note"] = note.cget("text")
        out["undo_question"] = asked[0][1] if asked else None
        shot(win.win, "5-window-undone")
        left = sorted(ask("findNotes", query=f'"tag:{drill_tag}"'))
        out["left_after_undo"] = left
        checks["undo_exact"] = left == sorted([ids["studied"], ids["edited"], ids["shelf_a"], ids["shelf_b"]])
        checks["undo_question"] = bool(asked) and asked[0][1].startswith(window_question()) \
            and "2 cards go." in asked[0][1] and "2 stay:" in asked[0][1]
        with Ledger() as lg:
            checks["job_undone"] = lg.job_by_id(job_id)["state"] == "undone"
        say("undo", out["undo_note"], left)

        # --- the shelf: one restore point put back from the window --------------------------------------- #
        old = app._connect_window
        app._open_connect_window()
        pump(lambda: app._connect_window is not None and app._connect_window is not old, timeout=15)
        win = app._connect_window
        win.confirm = lambda title, text: (asked.append((title, text)), True)[1]
        win.tabs.select(2)
        shelf_rec = (win.record or {}).get("shelf") or {}
        checks["shelf_listed"] = sorted(r["run"] for r in shelf_rec.get("runs") or ()) == sorted([run_a, run_b]) \
            and shelf_rec.get("on_shelf") == 2
        shot(win.win, "6-window-shelf")
        note = win.notes[("shelf", run_a)]
        guard("the put-back")
        t = time.monotonic()
        win.buttons[("shelf", run_a, "Put back")].invoke()
        pump(lambda: "back in your new cards" in note.cget("text") or "Not done" in note.cget("text")
             or "weren't" in note.cget("text"), timeout=180)
        out["times"]["put_back_s"] = round(time.monotonic() - t, 2)
        out["put_back_note"] = note.cget("text")
        shot(win.win, "7-window-shelf-back")
        suspended = set(ask("findCards", query=f'"tag:{drill_tag}" is:suspended'))
        checks["put_back_one"] = cards["shelf_a"] not in suspended and cards["shelf_b"] in suspended
        say("put back", out["put_back_note"], sorted(suspended))

        # --- switch off, a card still on the shelf: the put-back question ------------------------------- #
        questions = []
        if app.__dict__.get("settings_window") is None or not app.settings_window.winfo_exists():
            app.toggle_settings_window()
        else:
            app.settings_window.deiconify()
        pump(timeout=0.5)
        guard("the switch-off")
        t = time.monotonic()
        with mock.patch.object(dashboard_main.messagebox, "askyesno",
                               lambda title, text, **k: (questions.append(text), True)[1]):
            app.var_connect_enabled.set(False)
            app._connect_switch_toggled()
            checks["switched_off"] = pump(lambda: "disabled" not in app.chk_connect.state()
                                          and app._connect_row is None, timeout=120)
        out["times"]["switch_off_s"] = round(time.monotonic() - t, 2)
        out["off_question"] = questions
        checks["off_asked_once"] = questions == ["Put the 1 shelved card back into your new cards?"]
        checks["off_put_back"] = not ask("findCards", query=f'"tag:{drill_tag}" is:suspended')
        with open(os.path.join(root_dir, "settings.json"), encoding="utf-8") as f:
            checks["saved_off"] = json.load(f).get("connect_enabled") is False
        checks["row_gone"] = app._connect_row is None and app._connect_window is None
        app.settings_window.withdraw()
        shot(tk_root, "8-dashboard-off")
        say("switched off", checks["switched_off"], questions)
    except Stop as e:
        out["stopped"] = str(e)
        say("STOPPED", e)
    except Exception as e:
        import traceback
        out["error"] = traceback.format_exc()
        say("ERROR", e)
    finally:
        if ledger is not None:
            ledger.close()
        if devtest():
            left = ask("findNotes", query=f'"tag:{drill_tag}"')
            if left:                        # the drill's own notes only (a test-only delete)
                with anki_connect.writer("P3.1 window drill teardown", wait=60):
                    ask("deleteNotes", notes=left)
            out["teardown_deleted"] = len(left)
            out["teardown_left"] = len(ask("findNotes", query=f'"tag:{drill_tag}"'))
        else:
            out["teardown_left"] = "NOT CHECKED: Anki left DevTest"
        try:
            tk_root.destroy()
        except Exception:
            pass
        out["times"]["total_s"] = round(time.monotonic() - started, 1)
        out["passed"] = bool(checks) and all(checks.values()) and "error" not in out and "stopped" not in out
        text = json.dumps(out, ensure_ascii=False, indent=1, default=str)
        if a.shots:
            summary = os.path.join(a.shots, f"drill-summary_{int(a.scale * 100)}.json")
            with open(summary, "w", encoding="utf-8") as f:
                f.write(text)
        sys.stdout.buffer.write(text.encode("utf-8") + b"\n")
    return 0 if out.get("passed") and out.get("teardown_left") == 0 else 1


def window_question():
    from app.connect import connect_window
    return connect_window.QUESTION


if __name__ == "__main__":
    sys.exit(main())
