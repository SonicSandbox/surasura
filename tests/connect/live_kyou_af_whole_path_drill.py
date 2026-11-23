"""Kyou-AF with J-SWAP, on DevTest: the whole path of a card asked from the journey (journey v3 D3) against a real
Anki (never run by the suites; by hand, under `with-lock.sh anki`, Anki open — the drill loads DevTest and puts the
profile back at the end).

    python tests/connect/live_kyou_af_whole_path_drill.py --profile DevTest

- A scratch root (`SURASURA_TEST_ROOT`): the case's real subtitle as the library (J-SWAP's `_library`), the P1.4
  scene's list, library map and known words; Connect's ledger there, never Sonic's.
- A drill deck `DevTest::Kyou-AF path <run>`: the scene's new cards (冒険 and 眼鏡 carry Connect's job tag) and
  借りる's card as Connect made it (still new), every note tagged with the drill's own tag.
- Step 1, Junban's run (`reposition.run`): the order with no ask.
- Step 2, *Add now* twice through the route (`door_routes.card_route`, the page's `card/make`): 延長, then 住所, each
  from the line pressed. Connect's look queues the first, its job "mines" the card in the drill deck (`addNote` with the
  job's tag, the batch ended as the runner ends it), the next look marks it made and queues the second, and so on.
  Junban's run: the two first in the order pressed, every other card where Junban puts it with no ask (its own
  preview with the ask read off: `dry_run`).
- Step 3, ⇄ on 借りる through the route (`swap_route`, `swap/queue`): the new card mined; the look suspends the old one
  (one out, one in). Junban's run: the two asks still first, the ⇄'s new card where Junban puts it with no ask (never
  lifted), the old card suspended and out of the new cards.
- Step 4, 延長's ask undone as *Needs you* presses it (`swap.act_undo`: Tidy's backup, the card deleted). Junban's
  run: 住所 first, every other card where Junban puts it with no ask.

`getActiveProfile == "DevTest"` before every write and at teardown. Teardown: every note with the drill's tag
deleted, Tidy's own decks and the drill deck deleted once empty, counted back to 0, then the profile `--back-to`
(Sonic's 'User 1').
"""
import argparse
import json
import os
import sys
import tempfile
import time
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASKS = (("延長", "延長もできますよ"), ("住所", "お名前と住所を書いてください"))


def say(*parts):
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--profile", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--back-to", default="User 1", help="the profile loaded at the end (lane rules: Sonic's own)")
    a = ap.parse_args()
    if a.profile != "DevTest":
        sys.exit("REFUSED: the drill runs on the DevTest profile only")
    root = tempfile.mkdtemp(prefix="kyou-af2-drill-")
    os.environ["SURASURA_TEST_ROOT"] = root
    os.environ.pop("SURASURA_NO_ANKI_SYNC", None)
    sys.path.insert(0, REPO)
    from app import anki_connect
    from app.connect import door_routes, runner, swap
    from app.connect import ledger as ledger_mod
    from app.connect.ledger import Ledger
    from modules.junban import reposition
    from modules.junban.tests.connect_scene import settings as scene_settings
    from modules.junban.tests.test_preview_gate import CONNECT_TAG, KNOWN, SCENE
    from modules.junban.tests.test_reposition import _JOURNEY, _LIBRARY, _known, _results
    from tests.connect.test_j_swap_door import _library, _line
    from tests.connect.test_kantan_sl_swap import CASES, JA, Steps

    def ask(action, **params):
        return anki_connect.invoke(action, a.url, timeout=120, **params)

    def on(profile):
        for _ in range(60):
            try:
                if ask("getActiveProfile") == profile:
                    return True
            except anki_connect.AnkiError:
                pass
            time.sleep(1)
        return False

    def write(action, **params):
        with anki_connect.writer("Kyou-AF 2 drill", wait=60):
            return ask(action, **params)

    found = ask("getActiveProfile")
    if ask("guiReviewActive"):
        sys.exit("REFUSED: someone is reviewing in Anki")
    if found != "DevTest":
        say("loading DevTest (found", found, ")")
        write("loadProfile", name="DevTest")
        on("DevTest")
    out = {"root": root, "profile_found": found}
    run = time.strftime("%Y%m%d%H%M%S")
    deck = f"DevTest::Kyou-AF path {run}"
    tag = f"surasura::junban::test-kyou-af2-{run}"
    try:
        if ask("getActiveProfile") != "DevTest":
            sys.exit("REFUSED: Anki isn't on DevTest")
        item = _library("ja")                       # the case's subtitle in NOW, Connect on (settings in the root)
        _results(root, progressive=_JOURNEY, library=_LIBRARY, floor=11)
        _known(root, KNOWN)
        out["ledger_in_temp_root"] = os.path.abspath(ledger_mod.path()).startswith(os.path.abspath(root))
        if not out["ledger_in_temp_root"]:
            sys.exit("REFUSED: the ledger isn't in the drill's temp root")
        models = ask("modelNames")
        model = "Lapis" if "Lapis" in models else ("Basic" if "Basic" in models else models[0])
        names = ask("modelFieldNames", modelName=model)
        front, back = ("Expression", "Sentence") if model == "Lapis" else tuple(names[:2])
        out["model"] = model
        word, old_line, other = CASES["ja"]
        label = {}

        def add(text_word, text, tags):
            if ask("getActiveProfile") != "DevTest":
                sys.exit("REFUSED: Anki left DevTest")
            return write("addNote", note={"deckName": deck, "modelName": model, "options": {"allowDuplicate": True},
                                          "tags": [tag, *tags], "fields": {front: text_word, back: text}})

        write("createDeck", deck=deck)
        for w, sentence, _freq, tags, queue in SCENE:
            if queue == 0:                          # the scene's new cards (老婆, parked, left out)
                label[add(w, sentence, tags)] = w
        old = add(word, old_line, [CONNECT_TAG])
        label[old] = word + " (old)"
        with Ledger(ledger_mod.path()) as ledger:   # 借りる's card as Connect made it: its batch, its line
            job = ledger.queue("ja", item, "user", None, store_id="s1")
            ledger.end_batch(job, 1, "done", [{"word": word, "reading": "", "outcome": "made", "note_id": old,
                                               "sentence": old_line}], deck=deck)
            ledger.set_state(job, "done")
        old_cards = ask("findCards", query=f"nid:{old}")
        settings = scene_settings(junban_url=a.url, junban_deck=deck, junban_word_fields={model: front})
        anki = swap.AnkiSwap(a.url)

        def cards_of(notes):
            return sorted(ask("findCards", query=" OR ".join(f"nid:{n}" for n in notes))) if notes else []

        def order():
            cards = ask("cardsInfo", cards=ask("findCards", query=f'"deck:{deck}" is:new -is:suspended'))
            cards.sort(key=lambda c: (c["due"], c["cardId"]))
            return [c["cardId"] for c in cards], {c["cardId"]: label.get(c["note"], c["note"]) for c in cards}

        def junban():
            """Junban's run, after its own preview with the ask read off (where each card goes with no ask) -> what it
            wrote, Anki's order after, and that order as the asks first + the rest as the no-ask preview had them."""
            if ask("getActiveProfile") != "DevTest":
                sys.exit("REFUSED: Anki left DevTest")
            with mock.patch.object(reposition, "_asked_first", lambda _language, _cards: []):
                _w, stats = reposition.dry_run(settings)
            unasked = [row.card_id for row in stats["order"]]
            asked = cards_of(swap.asked_first("ja"))
            report = reposition.run(settings, refresh=False)
            ids, words = order()
            rest = [c for c in unasked if c in set(ids) and c not in asked]
            return {"ok": report.get("ok"), "written": len(report.get("written") or []),
                    "problems": report.get("problems"), "order": [words[c] for c in ids],
                    "asks_first_rest_as_without": ids == [c for c in asked if c in set(ids)] + rest}

        def mined(ledger, row, text_word, text):
            """Connect's job for the ask "mines" its card in the drill deck and ends as the runner ends it."""
            note = add(text_word, text, [f"surasura::connect::{ledger.tag_id(row['job_id'])}"])
            time.sleep(1.5)
            ledger.end_batch(row["job_id"], 1, "done", [{"word": text_word, "reading": "", "outcome": "made",
                                                         "note_id": note}], deck=deck)
            runner._record_made(runner.Steps({}), ledger, "ja", ledger.job_by_id(row["job_id"]), True)
            ledger.set_state(row["job_id"], "done")
            time.sleep(6)                   # past the grace: the batch "ended" before any mod could look like an edit
            ledger.conn.execute("UPDATE jobs SET updated_at = ?", (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),))
            ledger.conn.commit()
            time.sleep(7)
            return note

        out["step1"] = junban()

        # --- step 2: *Add now* twice, through the route
        presses = []
        for w, text in ASKS:
            got = door_routes.card_route({"lang": "ja", "word": w, "line_id": _line("ja", item, text)[0]}, None)
            presses.append(got)
        out["step2_presses"] = presses
        made = []
        with Ledger(ledger_mod.path()) as ledger:
            for (w, text), got in zip(ASKS, presses):
                swap.look(Steps(subtitle=JA), ledger, "ja", anki=anki, files=5)
                row = swap._rows(ledger, "id = ?", (got["id"],))[0]
                if row["state"] != swap.QUEUED:
                    sys.exit(f"STOPPED: {w}'s ask is {row['state']}, not queued")
                note = mined(ledger, row, w, swap._rows(ledger, "id = ?", (got["id"],))[0]["line"] or text)
                label[note] = w + " (asked)"
                made.append(note)
            swap.look(Steps(subtitle=JA), ledger, "ja", anki=anki, files=5)
            out["step2_states"] = [swap._rows(ledger, "id = ?", (g["id"],))[0]["state"] for g in presses]
        out["step2_asked_first"] = swap.asked_first("ja") == made
        out["step2"] = junban()
        out["step2_asks_first_as_pressed"] = out["step2"]["order"][:2] == [w + " (asked)" for w, _t in ASKS]

        # --- step 3: ⇄ on 借りる, through the route
        got = door_routes.swap_route({"lang": "ja", "word": word, "line_id": _line("ja", item, other)[0]}, None)
        out["step3_press"] = got
        with Ledger(ledger_mod.path()) as ledger:
            swap.look(Steps(subtitle=JA), ledger, "ja", anki=anki, files=5)
            row = swap._rows(ledger, "id = ?", (got["id"],))[0]
            out["step3_old_after_ask"] = [c["queue"] for c in ask("cardsInfo", cards=old_cards)]
            new = mined(ledger, row, word, row["line"] or other)
            label[new] = word + " (⇄ new)"
            swap.look(Steps(), ledger, "ja", anki=anki, files=5)
            row = swap._rows(ledger, "id = ?", (got["id"],))[0]
            out["step3_made"] = (row["by"], row["state"], row["new_note"] == new, row["took"])
        out["step3_old_after_made"] = [c["queue"] for c in ask("cardsInfo", cards=old_cards)]
        out["step3_asked_first_unchanged"] = swap.asked_first("ja") == made
        out["step3"] = junban()
        out["step3_swap_card_not_lifted"] = (word + " (⇄ new)") not in out["step3"]["order"][:2]
        out["step3_old_after_junban"] = [c["queue"] for c in ask("cardsInfo", cards=old_cards)]

        # --- step 4: 延長's ask undone, as *Needs you* presses it
        out["step4_undo"] = swap.act_undo({"junban_scope": "deck", "junban_deck": deck}, "ja", presses[0]["id"])
        out["step4_card_left"] = ask("findNotes", query=f"nid:{made[0]}")
        out["step4_asked_first"] = swap.asked_first("ja") == made[1:]
        out["step4"] = junban()
        out["step4_other_ask_first"] = out["step4"]["order"][:1] == [ASKS[1][0] + " (asked)"]
    finally:
        try:
            if ask("getActiveProfile") == "DevTest":
                with anki_connect.writer("Kyou-AF 2 drill teardown", wait=60):
                    left = ask("findNotes", query=f"tag:{tag}")
                    if left:
                        ask("deleteNotes", notes=left)
                    for d in ask("deckNames"):
                        if (d == deck or d.startswith("Surasura Tidy ")) and not ask("findCards", query=f'"deck:{d}"'):
                            ask("deleteDecks", decks=[d], cardsToo=True)
                out["teardown_left"] = len(ask("findNotes", query=f"tag:{tag}"))
                out["drill_deck_left"] = deck in ask("deckNames")
        finally:
            if a.back_to and a.back_to != "DevTest":
                write("loadProfile", name=a.back_to)
                on(a.back_to)
                out["profile_back"] = ask("getActiveProfile")
            print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
