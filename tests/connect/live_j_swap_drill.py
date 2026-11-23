"""J-SWAP 2's proof on DevTest: the journey page's two presses through their routes, against a real Anki (never run by
the suites; by hand, under `with-lock.sh anki`, Anki open — the drill loads DevTest and puts the profile back at the
end).

    python tests/connect/live_j_swap_drill.py --profile DevTest

- **Add now** (`card/make`, Chinese): a word with no card, the line pressed; Connect's look makes it a job, the job
  "mines" its card in DevTest (`addNotes` with the job's tag, the batch ended as the runner ends it), the next look
  marks it made; an ordinary *Tidy now* keeps it (you asked for it: `tidy.asked_for`).
- **⇄** (`swap/queue`, Japanese): the word's old card is Connect's, a note of two cards — the first in reviews, the
  second suspended and flagged orange by the learner. After the press and the first look (the job queued) the old
  card is still in reviews; once the new card is made, the first card is suspended and the note tagged
  `surasura::swapped`, the second as the learner left it. *Undo* as *Needs you* presses it (`swap.act_undo`): the new
  card deleted with a backup, the first card back in reviews, the second still suspended + orange, the tag gone.

`getActiveProfile == "DevTest"` before anything and before teardown. Teardown: every note with the drill's tag deleted
(a test-only delete, holding `anki-writer`), Tidy's own decks deleted once empty, counted back to 0. The ledger, the
library, the settings and the backups are in a temp root (`SURASURA_TEST_ROOT`): Sonic's are never opened.
"""
import argparse
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ORANGE = 2


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
    root = tempfile.mkdtemp(prefix="j-swap2-drill-")
    os.environ["SURASURA_TEST_ROOT"] = root
    os.environ.pop("SURASURA_NO_ANKI_SYNC", None)
    sys.path.insert(0, REPO)
    from app import anki_connect
    from app.connect import door_routes, library, runner, swap, tidy
    from app.connect import ledger as ledger_mod
    from app.connect.ledger import Ledger
    from tests.connect.test_j_swap_door import _connects_card, _library, _line
    from tests.connect.test_kantan_sl_swap import CASES, JA, ZH, Steps

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
        with anki_connect.writer("J-SWAP 2 drill", wait=60):
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
    settings = {"junban_scope": "deck", "junban_deck": "DevTest"}
    try:
        if ask("getActiveProfile") != "DevTest":
            sys.exit("REFUSED: Anki isn't on DevTest")
        drill_tag = f"surasura::test-jswap2-{run}"
        models = ask("modelNames")
        two = "Basic (and reversed card)" if "Basic (and reversed card)" in models else None
        model = two or ("Basic" if "Basic" in models else models[0])
        front, back = ask("modelFieldNames", modelName=model)[:2]
        out["model"] = model

        def add(word, text, tags):
            return write("addNotes", notes=[{"deckName": "DevTest", "modelName": model,
                                             "options": {"allowDuplicate": True}, "tags": [drill_tag] + tags,
                                             "fields": {front: word, back: text}}])[0]

        def state(cards):
            return [(i["queue"], i.get("flags")) for i in ask("cardsInfo", cards=cards)]

        def tagged(note):
            return swap.SWAP_TAG.lower() in [t.lower() for t in ask("notesInfo", notes=[note])[0].get("tags") or ()]

        def mined(ledger, lang, row, word, text):
            """Connect's job for the ask "mines" its card in DevTest and ends as the runner ends it; past the grace."""
            note = add(word, text, [f"surasura::connect::{ledger.tag_id(row['job_id'])}"])
            time.sleep(1.5)
            ledger.end_batch(row["job_id"], 1, "done", [{"word": word, "reading": "", "outcome": "made",
                                                         "note_id": note}], deck="DevTest")
            runner._record_made(runner.Steps({}), ledger, lang, ledger.job_by_id(row["job_id"]), True)
            ledger.set_state(row["job_id"], "done")
            time.sleep(6)                   # past the grace: the batch "ended" before any mod could look like an edit
            ledger.conn.execute("UPDATE jobs SET updated_at = ?", (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),))
            ledger.conn.commit()
            time.sleep(7)
            return note

        anki = swap.AnkiSwap(a.url)
        # --- Add now (Chinese)
        zword, _zold, zother = CASES["zh"]
        zitem = _library("zh")
        zline = _line("zh", zitem, zother)[0]
        out["ledger_in_temp_root"] = os.path.abspath(ledger_mod.path()).startswith(os.path.abspath(root))
        if not out["ledger_in_temp_root"]:
            sys.exit("REFUSED: the ledger isn't in the drill's temp root")
        got = door_routes.card_route({"lang": "zh", "word": zword, "line_id": zline}, None)
        out["add_now_press"] = got
        with Ledger(ledger_mod.path()) as ledger:
            out["add_now_look_1"] = swap.look(Steps(subtitle=ZH), ledger, "zh", anki=anki, files=5)
            row = swap._rows(ledger, "id = ?", (got["id"],))[0]
            znote = mined(ledger, "zh", row, zword, zother)
            out["add_now_look_2"] = swap.look(Steps(), ledger, "zh", anki=anki, files=5)
            row = swap._rows(ledger, "id = ?", (got["id"],))[0]
            out["add_now_made"] = (row["state"], row["new_note"] == znote)
            try:                            # the only card offered is kept: Tidy says so and deletes nothing
                done = tidy.run(tidy.AnkiConnectTidy(a.url), ledger, "zh", [znote], why=tidy.NOW,
                                open_store=lambda: library.open_store("zh"), ours="DevTest")
                out["add_now_tidy"] = {"deleted": done["deleted"], "kept": done["kept"]}
            except tidy.Refused as e:
                out["add_now_tidy"] = {"refused": e.say}
            out["add_now_asked_for"] = sorted(tidy.asked_for(ledger, "zh", [znote])) == [znote]
            out["add_now_note_left"] = ask("findNotes", query=f"nid:{znote}") == [znote]

        # --- ⇄ (Japanese)
        word, old_line, other = CASES["ja"]
        item = _library("ja")
        old = add(word, old_line, [])
        cards = sorted(ask("findCards", query=f"nid:{old}"))
        if len(cards) > 1:                  # the learner's own: suspended and orange before the press
            write("suspend", cards=[cards[1]])
            with anki_connect.writer("J-SWAP 2 drill", wait=60):
                anki.set_flag([cards[1]], ORANGE)
        out["old_before"] = state(cards)
        with Ledger(ledger_mod.path()) as ledger:
            _connects_card(ledger, "ja", item, note=old)
        got = door_routes.swap_route({"lang": "ja", "word": word, "line_id": _line("ja", item, other)[0]}, None)
        out["swap_press"] = got
        with Ledger(ledger_mod.path()) as ledger:
            out["swap_look_1"] = swap.look(Steps(subtitle=JA), ledger, "ja", anki=anki, files=5)
            out["old_after_look_1"] = state(cards)
            row = swap._rows(ledger, "id = ?", (got["id"],))[0]
            out["swap_queued"] = row["state"]
            new = mined(ledger, "ja", row, word, other)
            out["swap_look_2"] = swap.look(Steps(), ledger, "ja", anki=anki, files=5)
            row = swap._rows(ledger, "id = ?", (got["id"],))[0]
            out["swap_made"] = (row["state"], row["new_note"] == new, row["took"])
        out["old_after_made"] = state(cards)
        out["old_tagged_after_made"] = tagged(old)
        out["undo"] = swap.act_undo(settings, "ja", got["id"])
        out["new_left"] = ask("findNotes", query=f"nid:{new}")
        out["old_after_undo"] = state(cards)
        out["old_tagged_after_undo"] = tagged(old)
    finally:
        try:
            if ask("getActiveProfile") == "DevTest":
                with anki_connect.writer("J-SWAP 2 drill teardown", wait=60):
                    left = ask("findNotes", query=f"tag:{drill_tag}")
                    if left:
                        ask("deleteNotes", notes=left)
                    for deck in ask("deckNames"):
                        if deck.startswith("Surasura Tidy ") and not ask("findCards", query=f'"deck:{deck}"'):
                            ask("deleteDecks", decks=[deck], cardsToo=True)
                out["teardown_left"] = len(ask("findNotes", query=f"tag:{drill_tag}"))
        finally:
            if a.back_to and a.back_to != "DevTest":
                write("loadProfile", name=a.back_to)
                on(a.back_to)
                out["profile_back"] = ask("getActiveProfile")
            print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
