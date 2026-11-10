"""P2.5's proof on DevTest (row 2.5.9; ORDER: "undoing a test batch removes exactly its unstudied cards"): never run by
the suites; by hand, with locks/anki.lock taken by hand (board lines) and Anki open on DevTest.

    python tests/connect/live_undo_drill.py --profile DevTest

- A test batch: six Basic notes in deck DevTest, each front a real word, as one finished job of a scratch ledger
  (its outcomes `made`, with the notes' ids). Five carry the job's tag (`surasura::connect::<ledger uid>-<job>`), one
  doesn't; every one carries the drill's own tag (`surasura::connect::test-p25undo-<run>`) for the teardown.
- The shelf shown and put back: two of the batch's cards shelved (`shelf.shelve`), the status record lists the
  restore point, `undo.restore_shelf` puts it back; the ledger records them as yours (`back_by` you: never shelved
  again, ✅ P2.5-2).
- Then: one card studied (`answerCards`), one note edited (its field, after the grace), one card suspended by you.
- *Undo this batch* (`undo.run`, holding `anki-writer`): exactly the two untouched notes go (one of them the shelved
  and put back one: the shelf's own writes are Connect's); the studied, edited, suspended and untagged stay, each
  with its why; the job `undone`; a second undo is refused.

`getActiveProfile == "DevTest"` before anything and before teardown. Teardown: every note with the drill's tag
deleted (a test-only delete, holding `anki-writer`) and counted back to 0. The ledger is a scratch file under a
temp root (`SURASURA_TEST_ROOT`): Sonic's ledger and library are never opened.
"""
import argparse
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORDS = ["上層部", "一生懸命", "走り出す", "気配", "溜め息", "約束"]


def say(*parts):
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--profile", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--deck", default="DevTest")
    a = ap.parse_args()
    if a.profile != "DevTest" or a.deck != "DevTest":
        sys.exit("REFUSED: the drill runs on the DevTest profile and deck only")
    root = tempfile.mkdtemp(prefix="p25-undo-")
    os.environ["SURASURA_TEST_ROOT"] = root
    os.environ.pop("SURASURA_NO_ANKI_SYNC", None)
    sys.path.insert(0, REPO)
    from app import anki_connect
    from app.connect import shelf, status, undo
    from app.connect.ledger import Ledger

    def ask(action, **params):
        return anki_connect.invoke(action, a.url, timeout=120, **params)

    def devtest():
        try:
            return ask("getActiveProfile") == "DevTest"
        except anki_connect.AnkiError:
            return False

    if not devtest():
        sys.exit("REFUSED: Anki isn't open on DevTest")
    run = time.strftime("%Y%m%d%H%M%S")
    drill_tag = f"surasura::connect::test-p25undo-{run}"
    path = os.path.join(root, "ledger.sqlite")
    out = {"root": root, "drill_tag": drill_tag}
    ledger = Ledger(path)
    try:
        job_id = ledger.queue("ja", 1, "user", None, store_id="drill")
        job_tag = f"surasura::connect::{ledger.tag_id(job_id)}"
        model = "Basic" if "Basic" in ask("modelNames") else ask("modelNames")[0]
        front, back = ask("modelFieldNames", modelName=model)[:2]
        notes = [{"deckName": a.deck, "modelName": model, "options": {"allowDuplicate": True},
                  "tags": [drill_tag] + ([job_tag] if i < 5 else []),
                  "fields": {front: w, back: f"P2.5 drill {i}"}} for i, w in enumerate(WORDS)]
        with anki_connect.writer("P2.5 undo drill", wait=60):
            ids = ask("addNotes", notes=notes)
        untouched, shelved, studied, edited, suspended, untagged = ids
        ledger.end_batch(job_id, 1, "done", [{"word": w, "reading": "", "outcome": "made", "note_id": n}
                                             for n, w in zip(ids, WORDS)])
        ledger.set_state(job_id, "done")
        card_of = {c["note"]: c["cardId"] for c in anki_connect.cards_info(
            a.url, ask("findCards", query=f'"tag:{drill_tag}"'))}
        say("batch made", job_tag, ids)

        # the shelf shown and put back
        sanki = shelf.AnkiConnectAnki(a.url)
        restore = shelf.shelve(sanki, ledger, "ja", [shelf.Card(card_of[shelved], shelved, WORDS[1], 1)], "drill")
        record = status.read(["ja"], path=path)["languages"]["ja"]["shelf"]
        out["shelf_listed"] = [r["run"] for r in record["runs"]] == [restore] and record["on_shelf"] == 1
        out["shelf_back"] = undo.restore_shelf(sanki, ledger, restore)
        out["shelf_kept_as_yours"] = card_of[shelved] in shelf.kept(ledger)
        out["shelf_left_suspended"] = len(ask("findCards", query=f'"tag:{drill_tag}" is:suspended'))
        say("shelf", restore, out["shelf_back"], out["shelf_kept_as_yours"])

        # the learner's hand: studied, edited (after the grace), suspended
        time.sleep(undo.GRACE_S + 2)
        with anki_connect.writer("P2.5 undo drill (learner)", wait=60):
            try:
                ask("answerCards", answers=[{"cardId": card_of[studied], "ease": 3}])
            except anki_connect.AnkiError:
                ask("setSpecificValueOfCard", card=card_of[studied], keys=["reps", "type", "queue"],
                    newValues=["1", "2", "2"], warning_check=True)
            ask("updateNoteFields", note={"id": edited, "fields": {back: "edited by hand"}})
            ask("suspend", cards=[card_of[suspended]])

        uanki = undo.AnkiConnectUndo(a.url)
        plan = undo.plan(uanki, ledger, job_id)
        done = undo.run(uanki, ledger, job_id)
        out["deleted"] = sorted(done["deleted"])
        out["kept"] = {str(n): why for n, _w, why in done["keep"]}
        out["expected_deleted"] = sorted([untouched, shelved])
        out["plan_matched"] = sorted(plan["delete"]) == out["expected_deleted"]
        out["job_state"] = ledger.job_by_id(job_id)["state"]
        out["left_in_anki"] = sorted(ask("findNotes", query=f'"tag:{drill_tag}"'))
        try:
            undo.plan(uanki, ledger, job_id)
            out["second_undo_refused"] = False
        except undo.Refused:
            out["second_undo_refused"] = True
        out["passed"] = (out["deleted"] == out["expected_deleted"] and out["plan_matched"]
                         and out["kept"] == {str(studied): undo.STUDIED, str(edited): undo.CHANGED,
                                             str(suspended): undo.SUSPENDED, str(untagged): undo.NOT_ITS_TAG}
                         and out["left_in_anki"] == sorted([studied, edited, suspended, untagged])
                         and out["job_state"] == "undone" and out["second_undo_refused"]
                         and out["shelf_listed"] and out["shelf_back"] == 1 and out["shelf_kept_as_yours"]
                         and out["shelf_left_suspended"] == 0)
        say("undo", out["deleted"], out["kept"])
    finally:
        ledger.close()
        if devtest():
            left = ask("findNotes", query=f'"tag:{drill_tag}"')
            if left:                        # the drill's own notes only (a test-only delete)
                with anki_connect.writer("P2.5 undo drill teardown", wait=60):
                    ask("deleteNotes", notes=left)
            out["teardown_left"] = len(ask("findNotes", query=f'"tag:{drill_tag}"'))
        else:
            out["teardown_left"] = "NOT CHECKED: Anki left DevTest"
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0 if out.get("passed") and out.get("teardown_left") == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
