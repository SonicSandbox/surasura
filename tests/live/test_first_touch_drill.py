"""The live drill of FT (row FT.5): the first-touch backup and "Put Anki back the way it was before Surasura", one
real Anki.

**Skipped unless `SURASURA_LIVE_ANKI=DevTest`** — it writes to Anki. Only on the DevTest profile, holding the
program's `anki.lock`, under Sonic's standing DevTest go:

    SURASURA_LIVE_ANKI=DevTest python -m pytest tests/live/test_first_touch_drill.py -s -p no:randomly

Before anything, AnkiConnect's `getActiveProfile` must answer DevTest, or the drill stops and writes nothing; it is
asked again before every step that writes. It never syncs (`anki_connect.sync` is replaced, and every request is
checked: a `sync`, `loadProfile` or `guiExitAnki` is refused before it leaves this process), never loads a profile.

In a scratch data root (`debug/FT/drill-root`: its own settings.json, results, User Files, locks — never the user's):
a deck of its own in DevTest, "FT drill", of one Basic note per word of `tests/Test Resources/ja/expected_output.csv`
(Front = the word as written, Back = its first example sentence; tag `surasura-ft-drill`) in the CSV's order; every
card's `due` read (the "before" order). Then Surasura's writes through the real code paths: a 順 run
(`reposition.run`, the deck, the Junban tag on, the frequency entry in Back, the cards not on the list tagged
`Surasura::later` + flagged + suspended), then an automatic acting job (`auto.reorder`, `junban_auto_actions` on, a
`spaced.Job(automatic=True)` made actions there: the first spaced full respace), its list 20 words shorter so it has
cards of its own to act on. The user's side: two notes added, one kept card studied (`answerCards`), one other new
card suspended by hand (the two added cards are put at the front by hand, the later-made first, so the
put-back has to move them). Then `first_touch.plan()` and `put_back(fields=True, profile=plan's)`, read back card by card,
and a second `put_back` that must change nothing. Last, the deck is deleted with its notes and read back gone.
Results: `debug/FT/drill/drill-<time>.json` and the printed summary.
"""
import csv
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
DECK = "FT drill"
TAG = "surasura-ft-drill"
DRILL = os.path.join(_ROOT, "debug", "FT", "drill-root")
OUT = os.path.join(_ROOT, "debug", "FT", "drill")
CSV = os.path.join(_ROOT, "tests", "Test Resources", "ja", "expected_output.csv")
OFF_LIST_RUN = 40           # the last 40 words are on neither list: the 順 run suspends their cards
OFF_LIST_AUTO = 20          # 20 more leave the automatic job's list: it has cards of its own to act on
NEVER = ("sync", "loadProfile", "guiExitAnki")


def _rows():
    """The CSV's rows with a word written in it, one per spelling, in the CSV's order."""
    with open(CSV, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        header, rows, seen = reader.fieldnames, [], set()
        for row in reader:
            front = (row.get("Orth") or row.get("Word") or "").strip()
            if front and front not in seen:
                seen.add(front)
                rows.append(row)
    return header, rows


def _write_list(path, header, rows):
    """`results/priority_learning_list.csv` as the analyzer writes it: the CSV's own columns and rows."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _devtest():
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


def _state():
    """Every card and note of the drill's deck as Anki holds them now (reads only)."""
    from app import anki_connect
    cards = anki_connect.cards_info(URL, anki_connect.find_cards(URL, f'deck:"{DECK}"'))
    notes = anki_connect.notes_info(URL, sorted({card["note"] for card in cards}))
    return ({card["cardId"]: {k: card[k] for k in ("due", "queue", "type", "interval", "reps", "flags", "note")}
             for card in cards},
            {note["noteId"]: {"fields": {name: f["value"] for name, f in note["fields"].items()},
                              "tags": sorted(note.get("tags") or [])} for note in notes})


def _surasura_tags(tags):
    return [tag for tag in tags if tag.casefold() == "surasura" or tag.casefold().startswith("surasura::")]


def test_put_back_puts_a_real_deck_back_the_way_it_was_before_surasura(monkeypatch):
    from app import anki_connect, locks
    assert anki_connect.invoke("getActiveProfile", URL) == "DevTest", "not DevTest: the drill writes nothing"

    # --- the scratch root ----------------------------------------------------------------------------------- #
    shutil.rmtree(DRILL, ignore_errors=True)
    os.makedirs(OUT, exist_ok=True)
    root = os.path.join(DRILL, "lib")
    os.makedirs(root, exist_ok=True)
    monkeypatch.setenv("SURASURA_TEST_ROOT", root)
    monkeypatch.setenv("APPDATA", os.path.join(root, "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", os.path.join(root, "localappdata"))
    monkeypatch.delenv("SURASURA_NO_UI_TIMERS", raising=False)
    from app import path_utils, settings_manager
    from app.path_utils import ensure_data_setup
    ensure_data_setup("ja")
    import modules.junban as junban
    from modules.junban import auto, first_touch, reposition, spaced
    header, rows = _rows()
    listed_run = rows[:-OFF_LIST_RUN]
    listed_auto = rows[:-(OFF_LIST_RUN + OFF_LIST_AUTO)]
    saved = {"target_language": "ja", "anki_connect_url": URL, "enable_junban": True,
             "junban_scope": "deck", "junban_deck": DECK, "junban_order": "priority",
             "junban_word_fields": {"Basic": "Front"}, "junban_tag": "Surasura",
             "junban_write_frequency": True, "junban_frequency_field": "Back",
             "junban_later_tag": True, "junban_later_flag": True, "junban_later_suspend": True,
             "junban_auto_reorder": True, "junban_auto_actions": True,
             "junban_replan_deck": DECK, "junban_replan_language": "ja"}
    settings_path = path_utils.get_settings_path()
    assert os.path.dirname(os.path.abspath(settings_path)).startswith(os.path.abspath(DRILL)), settings_path
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(saved, f, ensure_ascii=False)

    def settings():
        with open(settings_path, encoding="utf-8") as f:
            return dict(junban.SETTINGS_DEFAULTS, **json.load(f))
    monkeypatch.setattr(anki_connect, "sync", lambda url, timeout=120: "failed: no sync in this drill")

    # --- every request, logged; the forbidden ones never leave ---------------------------------------------- #
    real, log = urllib.request.urlopen, []

    def logged(request, timeout=None):
        payload = json.loads(request.data.decode("utf-8"))
        params = payload.get("params") or {}
        subs = [e.get("action") for e in params.get("actions") or [] if isinstance(e, dict)]
        assert not set([payload["action"]] + subs) & set(NEVER), f"refused: {payload['action']} {subs}"
        sent = time.perf_counter()
        with real(request, timeout=timeout) as response:
            body = response.read()
        log.append({"at": sent, "took": time.perf_counter() - sent, "action": payload["action"], "subs": subs,
                    "write": bool(anki_connect._write_in(payload["action"], params))})
        return io.BytesIO(body)
    monkeypatch.setattr(urllib.request, "urlopen", logged)

    # --- FT's own steps, timed ------------------------------------------------------------------------------ #
    touches = []
    real_keep = reposition._keep_order

    def keep_order(*args, **kwargs):
        started = time.perf_counter()
        n0 = len(log)
        try:
            return real_keep(*args, **kwargs)
        finally:
            touches.append({"s": round(time.perf_counter() - started, 4), "log_at": n0,
                            "requests": [e["action"] for e in log[n0:]]})
    monkeypatch.setattr(reposition, "_keep_order", keep_order)
    notes_timed = []
    real_note = first_touch.note

    def note(*args, **kwargs):
        started = time.perf_counter()
        try:
            return real_note(*args, **kwargs)
        finally:
            notes_timed.append(round(time.perf_counter() - started, 4))
    monkeypatch.setattr(first_touch, "note", note)

    summary = {"cards": 0, "checks": {}, "timings": {}}
    checks = summary["checks"]

    def check(name, ok, detail=None):
        checks[name] = {"ok": bool(ok), **({"detail": detail} if detail is not None else {})}
        _say(f"{'PASS' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail is not None and not ok else ""))

    try:
        # 1. The deck, in a known order -------------------------------------------------------------------- #
        assert _devtest(), "Anki left DevTest"
        with locks.take(anki_connect.WRITER_LOCK, "the FT drill"):
            assert _devtest()
            anki_connect.invoke("createDeck", URL, deck=DECK)
            notes = [{"deckName": DECK, "modelName": "Basic", "tags": [TAG],
                      "fields": {"Front": (row.get("Orth") or row.get("Word")).strip(),
                                 "Back": (row.get("Context 1") or "").strip()
                                 or f"{(row.get('Orth') or row.get('Word')).strip()}を使った文。"},
                      "options": {"allowDuplicate": True}} for row in rows]
            note_ids = anki_connect.invoke("addNotes", URL, timeout=120, notes=notes)
        assert all(isinstance(n, int) for n in note_ids), "every note added"
        before_cards, before_notes = _state()
        before = {card: row["due"] for card, row in before_cards.items()}
        summary["cards"] = len(before)
        summary["before_due_range"] = [min(before.values()), max(before.values())]
        _say(f"deck '{DECK}' made: {len(before)} cards, dues {summary['before_due_range']}")

        # 2a. A 順 run: positions, the Junban tag, the frequency entry, the later actions ----------------- #
        _write_list(reposition.priority_csv_path(), header, listed_run)
        assert _devtest(), "Anki left DevTest"
        n_run = len(log)
        t0 = time.perf_counter()
        run = reposition.run(settings(), refresh=False)
        summary["timings"]["run_s"] = round(time.perf_counter() - t0, 2)
        summary["run"] = {k: run.get(k) for k in ("ok", "message", "problems", "warnings", "later")}
        _say(f"順 run: {run.get('message')} {run.get('problems') or ''}")
        assert run.get("ok"), run.get("problems")
        files = [name for name in os.listdir(first_touch.folder("ja")) if name.startswith("order-")]
        check("one order file after the 順 run", len(files) == 1, files)
        order_path = os.path.join(first_touch.folder("ja"), files[0])
        with open(order_path, "rb") as f:
            order_bytes = f.read()
        order = json.loads(order_bytes.decode("utf-8"))
        check("the order file holds the before order",
              {int(c): int(d) for c, d in order["cards"]} == before
              and order["profile"] == "DevTest" and order["earlier"] is False,
              {"cards": len(order["cards"]), "profile": order["profile"], "earlier": order["earlier"]})
        first_write = next((i for i, e in enumerate(log[n_run:], n_run) if e["write"]), None)
        check("the order file was kept before the first write",
              touches and first_write is not None and touches[0]["log_at"] <= first_write
              and not any(e["write"] for e in log[n_run:touches[0]["log_at"]]))
        suspended_run = list((run.get("later") or {}).get("suspend") or [])
        check("the 順 run suspended cards off its list", len(suspended_run) > 0, len(suspended_run))

        # 2b. The automatic acting job: the first spaced full respace ------------------------------------- #
        _write_list(reposition.priority_csv_path(), header, listed_auto)
        assert _devtest(), "Anki left DevTest"
        job = spaced.Job(automatic=True)
        t0 = time.perf_counter()
        done = auto.reorder(settings(), list_current=True, job=job)
        summary["timings"]["auto_s"] = round(time.perf_counter() - t0, 2)
        report = done.get("report") or {}
        summary["auto"] = {"outcome": done.get("outcome"), "error": done.get("error"), "kind": job.kind,
                           "actions": job.actions, **{k: report.get(k) for k in ("ok", "message", "problems",
                                                                                 "later")}}
        _say(f"automatic job: {done.get('outcome')} {job.kind} — {report.get('message')} "
             f"{report.get('problems') or done.get('error') or ''}")
        assert done.get("outcome") == "ran" and report.get("ok"), summary["auto"]
        check("the automatic job was the full respace", job.kind == spaced.FULL, job.kind)
        suspended_auto = list((report.get("later") or {}).get("suspend") or [])
        check("the automatic job suspended cards of its own", len(suspended_auto) > 0, len(suspended_auto))
        files_after = sorted(name for name in os.listdir(first_touch.folder("ja")) if name.startswith("order-"))
        with open(order_path, "rb") as f:
            unchanged = f.read() == order_bytes
        check("the order file was kept once, never replaced", files_after == files and unchanged, files_after)
        lines = first_touch.journal("ja")
        landed = [line for line in lines if line.get("landed") is True]
        landed_suspends = {int(c) for line in landed for c in line.get("suspended") or []}
        landed_tags = {tag for line in lines for tag in (line.get("tags") or {})}
        landed_flags = {int(c) for line in landed for c in (line.get("flags") or {})}
        check("the journal holds the landed suspends", landed_suspends == set(suspended_run) | set(suspended_auto),
              {"journal": len(landed_suspends), "runs": len(set(suspended_run) | set(suspended_auto))})
        check("the journal holds Surasura's tags", {"Surasura", "Surasura::later"} <= landed_tags,
              sorted(landed_tags))
        check("the journal holds the purple flags", landed_flags >= set(suspended_run) | set(suspended_auto),
              len(landed_flags))
        check("the journal holds the fields written", any(line.get("fields") for line in lines))
        surasura_cards, surasura_notes = _state()
        summary["after_surasura"] = {
            "suspended": sum(1 for row in surasura_cards.values() if row["queue"] == -1),
            "purple": sum(1 for row in surasura_cards.values() if row["flags"] == 7),
            "tagged_notes": sum(1 for row in surasura_notes.values() if _surasura_tags(row["tags"])),
            "fields_changed": sum(1 for n, row in surasura_notes.items()
                                  if row["fields"] != before_notes[n]["fields"]),
            "moved": sum(1 for c, row in surasura_cards.items() if row["due"] != before[c])}
        _say(f"after Surasura: {summary['after_surasura']}")

        # 3. The user's side: two notes added, one kept card studied, one other suspended by hand --------- #
        assert _devtest(), "Anki left DevTest"
        free = sorted((row["due"], c) for c, row in surasura_cards.items() if row["queue"] == 0 and row["type"] == 0)
        studied, by_hand = free[4][1], free[9][1]
        reflect = anki_connect.invoke("apiReflect", URL, scopes=["actions"], actions=["answerCards"])
        can_answer = "answerCards" in (reflect or {}).get("actions", [])
        with locks.take(anki_connect.WRITER_LOCK, "the FT drill (the user's side)"):
            assert _devtest()
            added_ids = anki_connect.invoke("addNotes", URL, notes=[
                {"deckName": DECK, "modelName": "Basic", "tags": [TAG],
                 "fields": {"Front": front, "Back": back}, "options": {"allowDuplicate": True}}
                for front, back in (("新しい", "新しい本を買った。"), ("届く", "手紙が昨日届いた。"))])
            # Anki numbers a new card at its next-position counter, which a write of `due` never moves: after the
            # put-back that is already behind the kept cards. So the two are put at the very front by hand, the
            # later-made one first — the put-back then has to move them, after the kept cards and in card-id order.
            added_now = sorted(row["cardId"] for row in anki_connect.cards_info(
                URL, anki_connect.find_cards(URL, " or ".join(f"nid:{n}" for n in added_ids))))
            anki_connect.multi([{"action": "setSpecificValueOfCard",
                                 "params": {"card": card, "keys": ["due"], "newValues": [due]}}
                                for card, due in zip(added_now, (2, 1))], URL)
            if can_answer:
                answered = anki_connect.invoke("answerCards", URL, answers=[{"cardId": studied, "ease": 3}])
                summary["answered"] = answered
            anki_connect.invoke("suspend", URL, cards=[by_hand])
        summary["studied"] = studied if can_answer else "skipped: this AnkiConnect has no answerCards"
        summary["suspended_by_hand"] = by_hand
        user_cards, user_notes = _state()
        added_cards = sorted(c for c, row in user_cards.items() if row["note"] in set(added_ids))
        check("two cards added after the order file, put at the front", len(added_cards) == 2
              and all(c > int(order["taken_ms"]) for c in added_cards)
              and [user_cards[c]["due"] for c in added_cards] == [2, 1], {c: user_cards[c]["due"] for c in added_cards})
        if can_answer:
            check("the studied card is no longer new", user_cards[studied]["type"] != 0, user_cards[studied])

        # 4. plan(), then put_back(fields=True) ----------------------------------------------------------- #
        assert _devtest(), "Anki left DevTest"
        t0 = time.perf_counter()
        planned = first_touch.plan(settings(), "ja", url=URL)
        summary["timings"]["plan_s"] = round(time.perf_counter() - t0, 3)
        summary["plan"] = {k: v for k, v in planned.items() if not isinstance(v, (list, dict)) or k == "problems"}
        _say(f"plan: {summary['plan']}")
        assert planned.get("ok"), planned
        check("plan counts the 2 added cards going after", planned.get("added_after") == 2, planned.get("added_after"))
        assert _devtest(), "Anki left DevTest"
        t0 = time.perf_counter()
        back = first_touch.put_back(settings(), "ja", fields=True, url=URL, profile=planned["profile"])
        summary["timings"]["put_back_s"] = round(time.perf_counter() - t0, 3)
        summary["put_back"] = {k: back.get(k) for k in ("ok", "message", "problems", "warnings", "done",
                                                        "settings_changed")}
        _say(f"put back: {back.get('message')}")
        check("put_back finished", back.get("ok"), back.get("problems"))

        # 5. Read back --------------------------------------------------------------------------------------- #
        after_cards, after_notes = _state()
        kept = [c for c in before if c != studied and c != by_hand]
        wrong = {c: [before[c], after_cards[c]["due"]] for c in kept
                 if after_cards[c]["type"] == 0 and after_cards[c]["due"] != before[c]}
        check("every kept card still new is at its before due", not wrong, dict(list(wrong.items())[:5]))
        highest = max(after_cards[c]["due"] for c in kept if after_cards[c]["type"] == 0)
        added_dues = [after_cards[c]["due"] for c in added_cards]
        check("the 2 added cards come after the highest kept number, in card-id order",
              all(d > highest for d in added_dues) and added_dues == sorted(added_dues)
              and len(set(added_dues)) == 2, {"highest": highest, "added": added_dues})
        if can_answer:
            keys = ("due", "queue", "type", "interval", "reps")
            check("the studied card is untouched",
                  {k: after_cards[studied][k] for k in keys} == {k: user_cards[studied][k] for k in keys},
                  [user_cards[studied], after_cards[studied]])
        check("the card suspended by hand stays suspended (and where it was)",
              after_cards[by_hand]["queue"] == -1 and after_cards[by_hand]["due"] == user_cards[by_hand]["due"],
              after_cards[by_hand])
        still = [c for c in set(suspended_run) | set(suspended_auto) if after_cards[c]["queue"] == -1]
        check("no card Surasura suspended stays suspended", not still, still[:5])
        tagged = {n: _surasura_tags(row["tags"]) for n, row in after_notes.items() if _surasura_tags(row["tags"])}
        check("no Surasura tag Surasura added remains", not tagged, dict(list(tagged.items())[:5]))
        purple = [c for c, row in after_cards.items() if row["flags"]]
        check("no flag Surasura set remains", not purple, purple[:5])
        fields = [n for n in before_notes if after_notes[n]["fields"] != before_notes[n]["fields"]]
        check("the fields Surasura wrote are back", not fields,
              [[before_notes[n]["fields"], after_notes[n]["fields"]] for n in fields[:2]])
        on_file = settings()
        check("the recorded deck pair is cleared", not on_file.get("junban_replan_deck"),
              on_file.get("junban_replan_deck"))

        # A second put_back changes nothing ----------------------------------------------------------------- #
        assert _devtest(), "Anki left DevTest"
        n_again = len(log)
        again = first_touch.put_back(settings(), "ja", fields=True, url=URL, profile=planned["profile"])
        summary["put_back_again"] = {k: again.get(k) for k in ("ok", "message", "done")}
        again_cards, again_notes = _state()
        writes_again = [e["action"] for e in log[n_again:] if e["write"]
                        and e["action"] not in ("guiDeckBrowser",)]
        check("a second put_back changes nothing", again.get("ok") and not any((again.get("done") or {}).values())
              and again_cards == after_cards and again_notes == after_notes,
              {"done": again.get("done"), "writes": writes_again})
        summary["timings"]["first_touch_s"] = [t["s"] for t in touches]
        summary["timings"]["first_touch_requests"] = [t["requests"] for t in touches]
        summary["timings"]["journal_lines_s"] = notes_timed
    finally:
        monkeypatch.setattr(urllib.request, "urlopen", real)
        # --- clean-up: the drill's deck deleted with its notes, read back ------------------------------------ #
        try:
            if not _devtest():
                raise RuntimeError("Anki is not on DevTest: nothing deleted — the deck stays")
            with locks.take(anki_connect.WRITER_LOCK, "the FT drill (clean-up)", wait=180):
                if not _devtest():
                    raise RuntimeError("Anki left DevTest while the clean-up waited: nothing deleted")
                if DECK in anki_connect.deck_names(URL):
                    anki_connect.invoke("deleteDecks", URL, decks=[DECK], cardsToo=True)
                left = anki_connect.find_notes(URL, f"tag:{TAG}")
                if left:
                    anki_connect.invoke("deleteNotes", URL, notes=left)
            summary["left_after_cleanup"] = (len(anki_connect.find_notes(URL, f"tag:{TAG}"))
                                             + (DECK in anki_connect.deck_names(URL)))
        except Exception as e:
            summary["cleanup_error"] = str(e)
            summary["left_after_cleanup"] = -1
        summary["requests"] = len(log)
        summary["syncs"] = sum(1 for e in log if e["action"] == "sync" or "sync" in e["subs"])
        path = os.path.join(OUT, time.strftime("drill-%Y%m%d-%H%M%S.json"))
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "log": log}, f, ensure_ascii=False, indent=1)
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        _say(f"written {path}")
    assert summary["left_after_cleanup"] == 0
    assert summary["syncs"] == 0
    failed = [name for name, result in checks.items() if not result["ok"]]
    assert not failed, failed
