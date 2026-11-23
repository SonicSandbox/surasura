# SPDX-License-Identifier: GPL-3.0-or-later
"""Kyou-AF's proof on DevTest: a card asked from the journey (*Add now*, journey v3 D3) is first among the new cards
Anki will show after Junban's run, the asks in the order asked, every other card in the order it had (never run by
the suites; by hand, under `with-lock.sh anki`, Anki open — the drill loads DevTest and puts the profile back).

    python modules/junban/tests/live_asked_first_drill.py --profile DevTest

- A scratch root (`SURASURA_TEST_ROOT`): the P1.4 scene's list, library map and known words
  (`test_preview_gate.SCENE`); Connect's ledger there, never Sonic's.
- A drill deck `DevTest::Kyou-AF <run>` of the scene's new cards (real Japanese on the scene's sentences; 冒険 and 眼鏡
  carry Connect's job tag), added in the scene's order, each note tagged with the drill's own tag.
- Step 1, Junban's run (the 順 window's, `reposition.run`): the order without an ask, read back from Anki.
- Step 2, two asks recorded as the journey's `card/make` records them (Swap's `make_card`, `by` "add now", then
  made with the note): 眼鏡 (at the back without it), then 冒険. Junban's run again: read back — the two first, in that
  order; every other card in step 1's order; the block's span unchanged.
- Step 3, an automatic re-order (`spaced.Job(automatic=True)`, the known-words sync's and the fast re-plan's host):
  the order as step 2 left it (it numbers on its own spaced ladder, so its positions may be rewritten, never
  reordered).
- Step 4, 眼鏡's ask undone (Swap's state `undone`): Junban's run puts it back where step 1 had it.

`getActiveProfile == "DevTest"` before every write and at teardown. Teardown: every note with the drill's tag
deleted, the drill deck deleted once empty, counted back to 0, then the profile `--back-to` (Sonic's 'User 1').
"""
import argparse
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


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
    root = tempfile.mkdtemp(prefix="kyou-af-drill-")
    os.environ["SURASURA_TEST_ROOT"] = root
    os.environ.pop("SURASURA_NO_ANKI_SYNC", None)
    sys.path.insert(0, REPO)
    from app import anki_connect
    from app.connect import swap
    from app.connect import ledger as ledger_mod
    from app.connect.ledger import Ledger
    from modules.junban import reposition, spaced
    from modules.junban.tests.connect_scene import settings as scene_settings
    from modules.junban.tests.test_preview_gate import CONNECT_TAG, KNOWN, SCENE
    from modules.junban.tests.test_reposition import _JOURNEY, _LIBRARY, _known, _results

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
        with anki_connect.writer("Kyou-AF drill", wait=60):
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
    deck = f"DevTest::Kyou-AF {run}"
    tag = f"surasura::junban::test-kyou-af-{run}"
    try:
        if ask("getActiveProfile") != "DevTest":
            sys.exit("REFUSED: Anki isn't on DevTest")
        _results(root, progressive=_JOURNEY, library=_LIBRARY, floor=11)
        _known(root, KNOWN)
        out["ledger_in_temp_root"] = os.path.abspath(ledger_mod.path()).startswith(os.path.abspath(root))
        if not out["ledger_in_temp_root"]:
            sys.exit("REFUSED: the ledger isn't in the drill's temp root")
        models = ask("modelNames")
        model = "Lapis" if "Lapis" in models else ("Basic" if "Basic" in models else models[0])
        names = ask("modelFieldNames", modelName=model)
        front, back = ("Expression", "Sentence") if model == "Lapis" else tuple(names[:2])
        rows = [r for r in SCENE if r[4] == 0]                  # the scene's new cards (老婆, parked, left out)
        with anki_connect.writer("Kyou-AF drill", wait=60):
            ask("createDeck", deck=deck)
            ids = []
            for word, sentence, _freq, tags, _queue in rows:        # one by one: Anki numbers them in this order
                ids.append(ask("addNote", note={"deckName": deck, "modelName": model,
                                                "options": {"allowDuplicate": True}, "tags": [tag, *tags],
                                                "fields": {front: word, back: sentence}}))
        note = {r[0]: n for r, n in zip(rows, ids)}
        settings = scene_settings(junban_url=a.url, junban_deck=deck, junban_word_fields={model: front})
        out["model"] = model

        def order():
            cards = ask("cardsInfo", cards=ask("findCards", query=f'"deck:{deck}" is:new -is:suspended'))
            cards.sort(key=lambda c: (c["due"], c["cardId"]))
            word_of = {n: w for w, n in note.items()}
            return [word_of[c["note"]] for c in cards], [c["due"] for c in cards]

        def junban(job=None):
            if ask("getActiveProfile") != "DevTest":
                sys.exit("REFUSED: Anki left DevTest")
            report = reposition.run(settings, refresh=False, job=job)
            return {"ok": report.get("ok"), "written": len(report.get("written") or []), "problems": report.get("problems")}

        out["added"] = order()[0]
        out["step1_run"] = junban()
        plain, plain_dues = order()
        out["step1_order"] = plain
        with Ledger() as ledger:
            made = []
            for word in ("眼鏡", "冒険"):
                got = swap.make_card("ja", word, line_id="1:3000", by=swap.BY_ADD_NOW, ledger=ledger, wake=False,
                                     state_of=lambda _w, _r: None)
                swap._set(ledger, got["id"], state=swap.MADE, new_note=note[word])
                made.append(got["id"])
        out["asked_first_read"] = swap.asked_first("ja")
        out["step2_run"] = junban()
        asked, asked_dues = order()
        out["step2_order"] = asked
        out["step2_first_two_as_asked"] = asked[:2] == ["眼鏡", "冒険"]
        out["step2_rest_kept"] = asked[2:] == [w for w in plain if w not in ("眼鏡", "冒険")]
        out["step2_span_kept"] = sorted(asked_dues) == sorted(plain_dues)
        out["step3_run"] = junban(spaced.Job(automatic=True))
        out["step3_order_same"] = order()[0] == asked
        with Ledger() as ledger:
            swap._set(ledger, made[0], state=swap.UNDONE)
        out["step4_run"] = junban()
        out["step4_order"] = order()[0]
        out["step4_glasses_back_in_place"] = out["step4_order"] == ["冒険"] + [w for w in plain if w != "冒険"]
    finally:
        if ask("getActiveProfile") == "DevTest":
            with anki_connect.writer("Kyou-AF drill teardown", wait=60):
                left = ask("findNotes", query=f"tag:{tag}")
                if left:
                    ask("deleteNotes", notes=left)
                if deck in ask("deckNames") and not ask("findCards", query=f'"deck:{deck}"'):
                    ask("deleteDecks", decks=[deck], cardsToo=True)
            out["teardown_left"] = len(ask("findNotes", query=f"tag:{tag}"))
            out["drill_deck_left"] = deck in ask("deckNames")
        if a.back_to and a.back_to != "DevTest":
            write("loadProfile", name=a.back_to)
            on(a.back_to)
            out["profile_back"] = ask("getActiveProfile")
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
