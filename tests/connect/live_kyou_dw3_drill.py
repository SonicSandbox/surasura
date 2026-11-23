"""Kyou-DW 3's proof on DevTest: a Connect card the learner deletes in Anki, answered *Parsing mistake* › *Only in
this sentence*, gets a new card from another sentence through Swap's maker (the Bad card way), its line goes in Send
report's list and is kept out of every later swap of the word; its Undo deletes the new card with a backup, takes the
line off the list and lifts the ban (never run by the suites; by hand, under `with-lock.sh anki`, Anki open — the
drill loads DevTest and puts the profile back at the end).

    python tests/connect/live_kyou_dw3_drill.py --profile DevTest

`getActiveProfile == "DevTest"` before anything and before teardown. Teardown: every note with the drill's tag deleted
(a test-only delete, holding `anki-writer`), Tidy's own decks deleted once empty, counted back to 0. The ledger, the
library, the word lists, Send report's list and the backups are in a temp root (`SURASURA_TEST_ROOT`): Sonic's are
never opened.
"""
import argparse
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# (word, the card's line) — Connect's batch; the deleted card's line read 気配 wrong, the word is real
CARDS = [("気配", "誰かの気配がした。"), ("約束", "明日の約束を忘れないでね。")]
OTHER = "春の気配を感じる。"              # the new card: another line saying 気配


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
    root = tempfile.mkdtemp(prefix="kyou-dw3-")
    os.environ["SURASURA_TEST_ROOT"] = root
    os.environ.pop("SURASURA_NO_ANKI_SYNC", None)
    sys.path.insert(0, REPO)
    from app import anki_connect
    from app.connect import deleted, library, runner, swap
    from app.connect import ledger as ledger_mod
    from app.connect.ledger import Ledger
    from app.services import flags, needs, word_marks
    from tests import cli_helpers as h
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
        with anki_connect.writer("Kyou-DW 3 drill", wait=60):
            return ask(action, **params)

    class Steps:                        # Connect's steps Swap's look asks: the episode's video is there
        url = a.url

        def subtitle(self, lang, job):
            return None

        def video(self, lang, job):
            return "episode.mkv"

        def reading(self, lang, job):
            return None

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
    checks = {}
    try:
        if ask("getActiveProfile") != "DevTest":
            sys.exit("REFUSED: Anki isn't on DevTest")
        drill_tag = f"surasura::test-kyoudw3-{run}"
        c.library("ja")
        folder = os.path.join(h.root(), "User Files", "ja")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "KnownWord.json"), "w", encoding="utf-8") as f:
            json.dump({"words": []}, f)
        with open(os.path.join(folder, "IgnoreList.txt"), "w", encoding="utf-8") as f:
            f.write("")
        if not os.path.abspath(ledger_mod.path()).startswith(os.path.abspath(root)):
            sys.exit("REFUSED: the ledger isn't in the drill's temp root")
        ledger = Ledger(ledger_mod.path())
        try:
            with c.store("ja") as s:
                items = s.ids("now")[:2]
            models = ask("modelNames")
            model = "Basic" if "Basic" in models else models[0]
            front, back = ask("modelFieldNames", modelName=model)[:2]

            def add(word, text, tags):
                with anki_connect.writer("Kyou-DW 3 drill", wait=60):
                    return ask("addNotes", notes=[{"deckName": "DevTest", "modelName": model,
                                                   "options": {"allowDuplicate": True}, "tags": [drill_tag] + tags,
                                                   "fields": {front: word, back: text}}])[0]

            def end_job(job, rows):
                ledger.end_batch(job, 1, "done", rows, deck="DevTest")
                runner._record_made(runner.Steps({}), ledger, "ja", ledger.job_by_id(job), True)
                ledger.set_state(job, "done")

            job = ledger.queue("ja", items[0], "user", None, store_id="drill")
            tag = f"surasura::connect::{ledger.tag_id(job)}"
            notes = [add(w, line, [tag]) for w, line in CARDS]
            end_job(job, [{"word": w, "reading": "", "outcome": "made", "note_id": n, "sentence": line,
                           "line_start": 10.0 + i} for i, ((w, line), n) in enumerate(zip(CARDS, notes))])
            gone = notes[0]
            write("deleteNotes", notes=[gone])           # the learner deletes it by hand; Connect's real look
            out["look"] = runner.Steps({"connect_enabled": True}).notes_gone("ja")
            rec = deleted.status_of(ledger.conn, "ja")
            checks["asked"] = [r["note_id"] for r in rec["asked"]] == [gone]
            (entry,) = [e for e in needs._deleted_entries({"deleted": rec}, set(), set(), asking=frozenset({gone}))
                        if e.kind == needs.DELETED]
            how = [ln for ln in entry.lines if ln.key == needs.deleted_how_key(gone)]
            checks["follow-up asked"] = len(how) == 1 and set(how[0].actions) == set(needs.HOW_ACTIONS)
            real_choose = swap.choose_line
            avoided = []

            def choose(language, word, avoid, *a_, **k):
                avoided.append(list(avoid))
                return (items[1], OTHER)
            swap.choose_line = choose
            try:
                got = deleted.answer("ja", [gone], deleted.LINE, ledger=ledger)
                checks["answered"] = got["done"] == [(gone, CARDS[0][0])]
                out["swap_look_1"] = swap.look(Steps(), ledger, "ja", anki=swap.AnkiSwap(a.url), files=5)
            finally:
                swap.choose_line = real_choose
            (row,) = swap._rows(ledger, "language = 'ja'")
            out["swap_row"] = {k: row[k] for k in ("by", "old_note", "state", "line", "avoid")}
            checks["asked the bad-card way"] = (row["by"], row["old_note"], row["state"], row["line"]) == \
                (swap.BY_BAD_CARD, gone, swap.QUEUED, OTHER) and avoided == [[CARDS[0][1]]]
            checks["word not ignored"] = word_marks.states("ja", [CARDS[0][0]])[CARDS[0][0]] is None
            lines = flags.read("ja")
            checks["line flagged"] = [(ln["line"], ln["source"], ln["reasons"]) for ln in lines] == \
                [(CARDS[0][1], "loop", ["parsing"])]
            new = add(CARDS[0][0], OTHER, [f"surasura::connect::{ledger.tag_id(row['job_id'])}"])
            time.sleep(1.5)
            end_job(row["job_id"], [{"word": CARDS[0][0], "reading": "", "outcome": "made", "note_id": new,
                                     "sentence": OTHER}])
            time.sleep(6)                   # past the grace: the batch "ended" before any mod could look like an edit
            ledger.conn.execute("UPDATE jobs SET updated_at = ?", (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),))
            ledger.conn.commit()
            time.sleep(7)
            out["swap_look_2"] = swap.look(Steps(), ledger, "ja", anki=swap.AnkiSwap(a.url), files=5)
            (row,) = swap._rows(ledger, "language = 'ja'")
            checks["new card made in DevTest"] = (row["state"], row["new_note"]) == (swap.MADE, new) and \
                ask("findNotes", query=f"nid:{new}") == [new]
            checks["ban in Swap's rule"] = CARDS[0][1] in swap._avoid(ledger, {"id": -1, "language": "ja",
                                                                               "word": CARDS[0][0], "reading": "",
                                                                               "old_note": None, "avoid": None})
            u = deleted.undo("ja", [gone], settings=settings)
            out["undo"] = u
            checks["undo done"] = u == {"done": [(gone, CARDS[0][0])], "skipped": []}
            checks["new card gone"] = ask("findNotes", query=f"nid:{new}") == []
            backups = ledger.conn.execute("SELECT COUNT(*) FROM tidies WHERE why = 'swap'").fetchone()[0]
            checks["backup kept"] = backups == 1 and all(os.path.isfile(os.path.join(r[0], "cards.apkg")) for r in ledger.conn.execute(
                    "SELECT folder FROM tidies WHERE why = 'swap'"))
            checks["line off the list"] = flags.read("ja") == []
            checks["ban lifted"] = CARDS[0][1] not in swap._avoid(ledger, {"id": -1, "language": "ja",
                                                                           "word": CARDS[0][0], "reading": "",
                                                                           "old_note": None, "avoid": None})
            checks["asked again"] = [r["note_id"] for r in deleted.status_of(ledger.conn, "ja")["asked"]] == [gone]
        finally:
            ledger.close()
            if ask("getActiveProfile") == "DevTest":
                with anki_connect.writer("Kyou-DW 3 drill teardown", wait=60):
                    left = ask("findNotes", query=f"tag:{drill_tag}")
                    if left:
                        ask("deleteNotes", notes=left)
                    for deck in ask("deckNames"):
                        if deck.startswith("Surasura Tidy ") and not ask("findCards", query=f'"deck:{deck}"'):
                            ask("deleteDecks", decks=[deck], cardsToo=True)
                out["teardown_left"] = len(ask("findNotes", query=f"tag:{drill_tag}"))
            else:
                out["teardown_left"] = "NOT CHECKED: Anki left DevTest"
    finally:
        if a.back_to and a.back_to != "DevTest":
            write("loadProfile", name=a.back_to)
            on(a.back_to)
            out["profile_back"] = ask("getActiveProfile")
        out["checks"] = checks
        out["passed"] = bool(checks) and all(checks.values()) and out.get("teardown_left") == 0
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0 if out["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
