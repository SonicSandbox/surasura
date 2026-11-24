"""Kyou-SH4's proof on DevTest: a card you moved into a deck of your own survives a tidy; one Surasura moved (its
*Move them to X*), one Junban reordered (its due and the card's mod moved, never its deck) and one moved and moved back
are still Tidy's (never run by the suites; by hand, under `with-lock.sh anki`, Anki open — the drill loads DevTest and
puts the profile back at the end).

    python tests/connect/live_tidy_own_deck_drill.py --profile DevTest

- A test batch in deck DevTest, real words, one finished job of a scratch ledger (Connect's own: `ledger.path()` in a
  temp root) whose batch records each card's home (`end_batch(deck="DevTest")`), recorded in a scratch library's made
  words, each note tagged with the job's tag and the drill's own; one more note made in a deck standing in for Anki
  Miner's own (its home that deck, a second batch), then moved into DevTest by *Move them to X* (`decks.move`, the
  learner's press: Surasura's move, which records DevTest as its home).
- The learner's moves (`changeDeck`, as Anki's browser does): one card to a top-level deck of their own, one to a
  subdeck they made under DevTest, one to their deck and back. Junban's reorder: `setSpecificValueOfCard` `due`
  (Junban's plain-AnkiConnect write) on one card.
- `tidy.run` (*Tidy now*) over every note, with no deck shown (`ours` None: only the homes on record count): the
  control, the reordered, the moved-back and the Surasura-moved go; the two you moved stay (`MOVED`), each where you
  put it. *Needs you*'s strays card counts the card in "Anki Miner's" deck before *Move them to X*, and none after
  your moves (the card you filed is yours, never a stray). Then the tidy undone (`tidy.restore`), so the drill leaves nothing behind but what it deletes itself.

`getActiveProfile == "DevTest"` before anything and before teardown. Teardown: every note with the drill's tag deleted
(a test-only delete, holding `anki-writer`), the drill's decks deleted once empty, counted back to 0. The ledger, the
library and the backup are in a temp root (`SURASURA_TEST_ROOT`): Sonic's are never opened.
"""
import argparse
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORDS = ["上層部", "一生懸命", "走り出す", "気配", "溜め息", "約束"]
CASES = ["control", "reordered_by_junban", "moved_by_hand", "moved_to_your_subdeck", "moved_and_back",
         "moved_by_surasura"]


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
    root = tempfile.mkdtemp(prefix="kyou-sh4-tidy-")
    os.environ["SURASURA_TEST_ROOT"] = root
    os.environ.pop("SURASURA_NO_ANKI_SYNC", None)
    sys.path.insert(0, REPO)
    from app import anki_connect
    from app.connect import decks, library, tidy
    from app.connect import ledger as ledger_mod
    from app.connect.ledger import Ledger
    from tests import connect_helpers as c

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
        with anki_connect.writer("Kyou-SH4 tidy drill", wait=60):
            return ask(action, **params)

    found = ask("getActiveProfile")
    if ask("guiReviewActive"):
        sys.exit("REFUSED: someone is reviewing in Anki")
    if found != "DevTest":
        say("loading DevTest (found", found, ")")
        write("loadProfile", name="DevTest")
        on("DevTest")
    out = {"root": root, "profile_found": found}
    open_store = lambda: library.open_store("ja")      # noqa: E731
    run = time.strftime("%Y%m%d%H%M%S")
    miner_deck = f"Kyou-SH4 Anki Miner {run}"
    own_deck = f"Kyou-SH4 自分の単語帳 {run}"
    sub_deck = f"DevTest::Kyou-SH4 後で {run}"
    settings = {"junban_scope": "deck", "junban_deck": "DevTest", "junban_replan_deck": "DevTest",
                "junban_replan_language": "ja"}
    try:
        if ask("getActiveProfile") != "DevTest":
            sys.exit("REFUSED: Anki isn't on DevTest")
        drill_tag = f"surasura::test-tidy4-{run}"
        c.library("ja")
        out["ledger"] = ledger_mod.path()
        out["ledger_in_temp_root"] = os.path.abspath(ledger_mod.path()).startswith(os.path.abspath(root))
        if not out["ledger_in_temp_root"]:
            sys.exit("REFUSED: the ledger isn't in the drill's temp root")
        ledger = Ledger(ledger_mod.path())
        try:
            with c.store("ja") as s:
                item = s.ids("now")[0]
            job_id = ledger.queue("ja", item, "user", None, store_id="drill")
            job_tag = f"surasura::connect::{ledger.tag_id(job_id)}"
            models = ask("modelNames")
            model = "Basic" if "Basic" in models else models[0]
            front, back = ask("modelFieldNames", modelName=model)[:2]
            with anki_connect.writer("Kyou-SH4 tidy drill", wait=60):
                ask("createDeck", deck=miner_deck)
                ids = ask("addNotes", notes=[
                    {"deckName": miner_deck if case == "moved_by_surasura" else "DevTest", "modelName": model,
                     "options": {"allowDuplicate": True}, "tags": [drill_tag, job_tag],
                     "fields": {front: w, back: f"Tidy4 {case}"}}
                    for case, w in zip(CASES, WORDS)])
            note = dict(zip(CASES, ids))
            word = dict(zip(CASES, WORDS))
            time.sleep(1.5)
            # Connect's batches: five made in DevTest, one in "Anki Miner's" deck — each card's home is its batch's deck
            ledger.end_batch(job_id, 1, "done", [{"word": word[cs], "reading": "", "outcome": "made",
                                                  "note_id": note[cs]} for cs in CASES if cs != "moved_by_surasura"],
                             deck="DevTest")
            ledger.start_batch(job_id, 2, root)
            ledger.end_batch(job_id, 2, "done", [{"word": word["moved_by_surasura"], "reading": "", "outcome": "made",
                                                  "note_id": note["moved_by_surasura"]}], deck=miner_deck)
            ledger.set_state(job_id, "done")
            with c.store("ja") as s:
                library.record_batch(s, item, {word[cs]: [note[cs]] for cs in CASES},
                                     time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), batch="drill")
            card = {cs: ask("findCards", query=f"nid:{n}")[0] for cs, n in note.items()}
            time.sleep(6)                   # past the grace: the batch "ended" before any mod could look like an edit
            ledger.conn.execute("UPDATE jobs SET updated_at = ? WHERE id = ?",
                                (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), job_id))
            out["homes_made"] = {cs: h for cs, h in zip(CASES, [ledger.homes([note[cs]]).get(note[cs]) for cs in CASES])}
            time.sleep(7)                   # every move below comes after Connect's last write + the grace
            # Surasura's move first (it moves every made card outside DevTest, so before any of the learner's)
            decks.forget()                  # *Needs you*'s strays card: the one in "Anki Miner's" deck (its home)
            out["strays_before_move_them"] = decks.strays(settings, "ja")
            moved = decks.move(settings, "ja", "DevTest", wait=60)
            out["move_them"] = {"ok": moved.get("ok"), "moved": moved.get("moved"), "say": moved.get("say")}
            out["home_after_move_them"] = ledger.homes([note["moved_by_surasura"]]).get(note["moved_by_surasura"])
            mod_before = ask("cardsInfo", cards=[card["reordered_by_junban"]])[0].get("mod")
            write("setSpecificValueOfCard", card=card["reordered_by_junban"], keys=["due"], newValues=[1],
                  warning_check=True)
            after = ask("cardsInfo", cards=[card["reordered_by_junban"]])[0]
            out["junban_card_mod_moved"] = after.get("mod") != mod_before
            out["junban_card_deck"] = after.get("deckName")
            write("changeDeck", cards=[card["moved_by_hand"]], deck=own_deck)
            write("changeDeck", cards=[card["moved_to_your_subdeck"]], deck=sub_deck)
            write("changeDeck", cards=[card["moved_and_back"]], deck=own_deck)
            write("changeDeck", cards=[card["moved_and_back"]], deck="DevTest")
            decks.forget()                  # your filing is no stray: the card never counts it (None)
            out["strays_after_your_moves"] = decks.strays(settings, "ja")
            anki = tidy.AnkiConnectTidy(a.url)
            done = tidy.run(anki, ledger, "ja", ids, why=tidy.NOW, open_store=open_store, ours=None)
            by_note = {v: k for k, v in note.items()}
            out["now_deleted"] = sorted(by_note[n] for n in done["deleted"])
            out["now_kept"] = {by_note[n]: why for n, why in done["kept"]}
            decks_now = {i["cardId"]: i["deckName"] for i in ask("cardsInfo", cards=ask("findCards",
                                                                                        query=f"tag:{drill_tag}"))}
            out["kept_where_you_put_them"] = {cs: decks_now.get(card[cs]) for cs in ("moved_by_hand",
                                                                                     "moved_to_your_subdeck")}
            back_ = tidy.restore(anki, ledger, done["id"], open_store)
            out["restore"] = {"back": back_["back"], "missing": back_["missing"]}
            out["left_after_undo"] = len(ask("findNotes", query=f"tag:{drill_tag}"))
        finally:
            ledger.close()
            if ask("getActiveProfile") == "DevTest":
                with anki_connect.writer("Kyou-SH4 tidy drill teardown", wait=60):
                    left = ask("findNotes", query=f"tag:{drill_tag}")
                    if left:
                        ask("deleteNotes", notes=left)
                    for deck in ask("deckNames"):
                        if (deck.startswith("Surasura Tidy ") or run in deck) and not ask(
                                "findCards", query=f'"deck:{deck}"'):
                            ask("deleteDecks", decks=[deck], cardsToo=True)
                out["teardown_left"] = len(ask("findNotes", query=f"tag:{drill_tag}"))
                out["drill_decks_left"] = [d for d in ask("deckNames") if run in d]
    finally:
        if a.back_to and a.back_to != "DevTest":
            write("loadProfile", name=a.back_to)
            on(a.back_to)
            out["profile_back"] = ask("getActiveProfile")
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
