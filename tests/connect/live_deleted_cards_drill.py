"""Kura-AB3's proof on DevTest (Mattias's 3.0.2 question: "what is he to do with the cards already made text-only?"):
does deleting a card in Anki let Surasura make it again, and does *Undo this batch*? Never run by the suites; by hand,
with locks/anki.lock taken (`with-lock.sh anki`) and Anki open on DevTest.

    python tests/connect/live_deleted_cards_drill.py --profile DevTest

- A real library store (a temp root: `SURASURA_TEST_ROOT`) holding one item, a real subtitle of the suite; a scratch
  ledger with one finished job for it; three Basic notes in deck DevTest — real words — as that job's batch (its tag
  `surasura::connect::<ledger uid>-<job>`, and the drill's own tag for the teardown), recorded in the store's made
  words as Connect records a batch (`library.record_batch`).
- The learner deletes the first note by hand in Anki; Connect's deleted-card look (`shelf.gone_notes` +
  `library.notes_gone`, the two calls `runner.Steps.notes_gone` makes) finds it gone.
- Then the third card is studied (`answerCards`), and *Undo this batch* runs (`undo.plan` + `undo.run`, holding
  `anki-writer`).
- What is made again is read from the store as Connect's pick reads it (`library.made_words_for`): a job of its own
  (`mine`) and an ask (`asked`).

Passes when: the hand-deleted word stays made (never made again by Connect, nor by Undo); Undo deletes only the
unstudied note and frees its word; the studied card stays and its word stays made. `getActiveProfile == "DevTest"`
before anything and before teardown. Teardown: every note with the drill's tag deleted and counted back to 0. Sonic's
ledger and library are never opened.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORDS = ["約束", "気配", "溜め息"]


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
    root = tempfile.mkdtemp(prefix="ab3-deleted-")
    os.environ["SURASURA_TEST_ROOT"] = root
    os.environ.pop("SURASURA_NO_ANKI_SYNC", None)
    sys.path.insert(0, REPO)
    from app import anki_connect
    from app.connect import library, shelf, undo
    from app.connect.ledger import ASKED, MINE, Ledger
    from tests.test_audiobook_items import _settle
    from tests.test_sources_scan import _drive, _empty, _look

    def ask(action, **params):
        return anki_connect.invoke(action, a.url, timeout=120, **params)

    def devtest():
        try:
            return ask("getActiveProfile") == "DevTest"
        except anki_connect.AnkiError:
            return False

    def made(kind):
        with library.open_store("ja") as s:
            return sorted(library.made_words_for(s, {"kind": kind}) & set(WORDS))

    if not devtest():
        sys.exit("REFUSED: Anki isn't open on DevTest")
    run = time.strftime("%Y%m%d%H%M%S")
    drill_tag = f"surasura::connect::test-ab3deleted-{run}"
    out = {"root": root, "drill_tag": drill_tag}
    ledger = Ledger(os.path.join(root, "ledger.sqlite"))
    try:
        store, _data_dir = _empty("ja")
        src = _drive("driveA")
        shutil.copy(os.path.join(REPO, "tests", "Test Resources", "ja", "placed_episode.srt"),
                    os.path.join(src, "placed_episode.ja.srt"))
        _settle(os.path.join(src, "placed_episode.ja.srt"))     # an old file: the look takes it in at once
        with store:
            _look(store, "ja", store.add_source(src), first=True)
            [(item_id,)] = store.conn.execute("SELECT id FROM items").fetchall()
        job_id = ledger.queue("ja", item_id, "user", None, store_id="drill")
        job_tag = f"surasura::connect::{ledger.tag_id(job_id)}"
        model = "Basic" if "Basic" in ask("modelNames") else ask("modelNames")[0]
        front, back = ask("modelFieldNames", modelName=model)[:2]
        notes = [{"deckName": a.deck, "modelName": model, "options": {"allowDuplicate": True},
                  "tags": [drill_tag, job_tag], "fields": {front: w, back: f"AB3 drill {i} (text only)"}}
                 for i, w in enumerate(WORDS)]
        with anki_connect.writer("AB3 deleted-cards drill", wait=60):
            ids = ask("addNotes", notes=notes)
        by_hand, untouched, studied = ids
        ledger.end_batch(job_id, 1, "done", [{"word": w, "reading": "", "outcome": "made", "note_id": n}
                                             for n, w in zip(ids, WORDS)])
        ledger.set_state(job_id, "done")
        with library.open_store("ja") as s:
            library.record_batch(s, item_id, {w: [n] for w, n in zip(WORDS, ids)}, "2026-11-01T00:00:00Z")
        say("batch made", job_tag, ids)
        out["made_before"] = {"mine": made(MINE), "asked": made(ASKED)}

        # the learner deletes one card by hand in Anki; Connect's next run looks
        with anki_connect.writer("AB3 deleted-cards drill (learner)", wait=60):
            ask("deleteNotes", notes=[by_hand])
        with library.open_store("ja") as s:
            gone = shelf.gone_notes(shelf.AnkiConnectAnki(a.url), library.note_ids(s))
            library.notes_gone(s, gone)
        out["gone_seen"] = gone
        out["made_after_delete"] = {"mine": made(MINE), "asked": made(ASKED)}
        say("deleted by hand", gone, out["made_after_delete"])

        # one card studied, then Undo this batch
        time.sleep(undo.GRACE_S + 2)
        [card] = ask("findCards", query=f"nid:{studied}")
        with anki_connect.writer("AB3 deleted-cards drill (study)", wait=60):
            try:
                ask("answerCards", answers=[{"cardId": card, "ease": 3}])
            except anki_connect.AnkiError:
                ask("setSpecificValueOfCard", card=card, keys=["reps", "type", "queue"], newValues=["1", "2", "2"],
                    warning_check=True)
        uanki = undo.AnkiConnectUndo(a.url)
        plan = undo.plan(uanki, ledger, job_id)
        done = undo.run(uanki, ledger, job_id, open_store=lambda: library.open_store("ja"))
        out["plan"] = {"delete": plan["delete"], "keep": plan["keep"], "gone": plan["gone"]}
        out["deleted"], out["freed"] = sorted(done["deleted"]), done["freed"]
        out["made_after_undo"] = {"mine": made(MINE), "asked": made(ASKED)}
        out["left_in_anki"] = sorted(ask("findNotes", query=f'"tag:{drill_tag}"'))
        say("undo", out["deleted"], out["freed"], out["made_after_undo"])
        out["passed"] = (out["made_before"]["mine"] == sorted(WORDS)
                         and gone == [by_hand]
                         and out["made_after_delete"] == {"mine": sorted(WORDS), "asked": sorted([WORDS[1], WORDS[2]])}
                         and out["deleted"] == [untouched] and out["freed"] == [WORDS[1]]
                         and sorted(plan["gone"]) == [by_hand]
                         and out["made_after_undo"]["mine"] == sorted([WORDS[0], WORDS[2]])
                         and out["left_in_anki"] == [studied])
    finally:
        ledger.close()
        if devtest():
            left = ask("findNotes", query=f'"tag:{drill_tag}"')
            if left:                        # the drill's own notes only (a test-only delete)
                with anki_connect.writer("AB3 deleted-cards drill teardown", wait=60):
                    ask("deleteNotes", notes=left)
            out["teardown_left"] = len(ask("findNotes", query=f'"tag:{drill_tag}"'))
        else:
            out["teardown_left"] = "NOT CHECKED: Anki left DevTest"
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0 if out.get("passed") and out.get("teardown_left") == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
