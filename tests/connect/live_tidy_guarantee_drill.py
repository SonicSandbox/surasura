"""Kyou-SH3's proof on DevTest: Tidy's guarantee against a real Anki — it takes only cards Surasura made that were
never reviewed and that you never changed; its backup reads back; Undo leaves out a card whose word was mined again
(never run by the suites; by hand, under `with-lock.sh anki`, Anki open — the drill loads DevTest and puts the profile
back at the end).

    python tests/connect/live_tidy_guarantee_drill.py --profile DevTest

- A test batch in deck DevTest, real words, one finished job of a scratch ledger (outcomes `made`) recorded in a
  scratch library's made words, each note tagged with the job's tag and the drill's own: two that may go (the
  controls, one with a clip) and the "nevers" — answered once (`answerCards`); answered then reset to new with its
  counts reset (`forgetCards` + reps/lapses 0: it reads new, its review log stays); edited (`updateNoteFields`);
  tagged by you (`addTags`); flagged and suspended by you; one made by hand with Surasura's tag (in no record). A
  filtered deck can't be made through AnkiConnect: that case is pinned on the suite's fake only.
- `tidy.run` by itself (AUTO) over the nevers alone: refused, nothing deleted; then *Tidy now* (NOW) over every note:
  only the two controls go, each never kept with its why; the backup read back (package, notes.json, the clip).
- One control's word mined again (a new note in Anki and in the made words), then `tidy.restore`: the other control
  back, the re-mined one left out (`skipped`), one card for that word, the tidy's own deck gone.

`getActiveProfile == "DevTest"` before anything and before teardown. Teardown: every note with the drill's tag deleted
(a test-only delete, holding `anki-writer`), the clip deleted, counted back to 0. The ledger, the library and the
backup are in a temp root (`SURASURA_TEST_ROOT`): Sonic's are never opened.
"""
import argparse
import base64
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORDS = ["上層部", "一生懸命", "走り出す", "気配", "溜め息", "約束", "雰囲気", "手作り", "眼差し"]
CASES = ["control", "control_mined_again", "answered_once", "answered_then_reset", "edited", "tagged_by_you",
         "flagged", "suspended_by_you", "made_by_hand"]


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
    root = tempfile.mkdtemp(prefix="kyou-sh3-tidy-")
    os.environ["SURASURA_TEST_ROOT"] = root
    os.environ.pop("SURASURA_NO_ANKI_SYNC", None)
    sys.path.insert(0, REPO)
    from app import anki_connect
    from app.connect import library, tidy
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
        with anki_connect.writer("Kyou-SH3 tidy drill", wait=60):
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
    try:
        if ask("getActiveProfile") != "DevTest":
            sys.exit("REFUSED: Anki isn't on DevTest")
        run = time.strftime("%Y%m%d%H%M%S")
        drill_tag = f"surasura::test-tidy3-{run}"
        clip = f"surasura-tidy3-drill-{run}.mp3"
        clip_bytes = ("ID3 tidy3 drill " + run).encode("utf-8") * 40
        c.library("ja")
        ledger = Ledger(os.path.join(root, "connect", "ledger.sqlite"))
        try:
            with c.store("ja") as s:
                item, other = s.ids("now")[:2]
            job_id = ledger.queue("ja", item, "user", None, store_id="drill")
            job_tag = f"surasura::connect::{ledger.tag_id(job_id)}"
            models = ask("modelNames")
            model = "Basic" if "Basic" in models else models[0]
            front, back = ask("modelFieldNames", modelName=model)[:2]
            with anki_connect.writer("Kyou-SH3 tidy drill", wait=60):
                ask("storeMediaFile", filename=clip, data=base64.b64encode(clip_bytes).decode("ascii"))
                ids = ask("addNotes", notes=[
                    {"deckName": "DevTest", "modelName": model, "options": {"allowDuplicate": True},
                     "tags": [drill_tag, job_tag],
                     "fields": {front: w, back: (f"[sound:{clip}] " if case == "control" else "") + f"Tidy3 {case}"}}
                    for case, w in zip(CASES, WORDS)])
            note = dict(zip(CASES, ids))
            word = dict(zip(CASES, WORDS))
            made = [cs for cs in CASES if cs != "made_by_hand"]
            time.sleep(1.5)
            ledger.end_batch(job_id, 1, "done", [{"word": word[cs], "reading": "", "outcome": "made",
                                                  "note_id": note[cs]} for cs in made], deck="DevTest")
            ledger.set_state(job_id, "done")
            with c.store("ja") as s:
                library.record_batch(s, item, {word[cs]: [note[cs]] for cs in made},
                                     time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), batch="drill")
            card = {cs: ask("findCards", query=f"nid:{n}")[0] for cs, n in note.items()}
            time.sleep(6)                   # past the grace: the batch "ended" before any mod could look like an edit
            ledger.conn.execute("UPDATE jobs SET updated_at = ? WHERE id = ?",
                                (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), job_id))
            time.sleep(7)                   # the learner's changes come after Connect's last write + the grace
            write("answerCards", answers=[{"cardId": card["answered_once"], "ease": 3}])
            write("answerCards", answers=[{"cardId": card["answered_then_reset"], "ease": 3}])
            write("forgetCards", cards=[card["answered_then_reset"]])
            write("setSpecificValueOfCard", card=card["answered_then_reset"], keys=["reps", "lapses"],
                  newValues=[0, 0], warning_check=True)
            write("updateNoteFields", note={"id": note["edited"], "fields": {back: "Tidy3 edited: 自分のメモ"}})
            write("addTags", notes=[note["tagged_by_you"]], tags="my::favourites")
            write("setSpecificValueOfCard", card=card["flagged"], keys=["flags"], newValues=[1])
            write("suspend", cards=[card["suspended_by_you"]])
            reset = ask("cardsInfo", cards=[card["answered_then_reset"]])[0]
            out["reset_card_reads_new"] = {k: reset.get(k) for k in ("reps", "type", "queue")}
            out["reset_card_review_log"] = len((write("getReviewsOfCards", cards=[card["answered_then_reset"]]) or {})
                                               .get(str(card["answered_then_reset"])) or [])
            anki = tidy.AnkiConnectTidy(a.url)
            nevers = [note[cs] for cs in CASES if not cs.startswith("control")]
            try:
                tidy.run(anki, ledger, "ja", nevers, why=tidy.AUTO, open_store=open_store)
                out["auto_over_nevers"] = "TIDIED (wrong)"
            except tidy.Refused as e:
                out["auto_over_nevers"] = e.say
            out["left_after_auto"] = len(ask("findNotes", query=f"tag:{drill_tag}"))
            done = tidy.run(anki, ledger, "ja", ids, why=tidy.NOW, open_store=open_store)
            row = tidy.tidy_row(ledger, done["id"])
            by_note = {v: k for k, v in note.items()}
            out["now_deleted"] = sorted(by_note[n] for n in done["deleted"])
            out["now_kept"] = {by_note[n]: why for n, why in done["kept"]}
            out["read_back"] = tidy._read_back(row["folder"], done["deleted"],
                                               json.load(open(os.path.join(row["folder"], "notes.json"),
                                                              encoding="utf-8"))["media"])
            # one control's word mined again: a new note for it, in Anki and in the made words (another episode)
            again = write("addNote", note={"deckName": "DevTest", "modelName": model, "tags": [drill_tag, job_tag],
                                           "options": {"allowDuplicate": True},
                                           "fields": {front: word["control_mined_again"], back: "Tidy3 mined again"}})
            with c.store("ja") as s:
                library.record_batch(s, other, {word["control_mined_again"]: [again]},
                                     time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), batch="drill-2")
            back_ = tidy.restore(anki, ledger, done["id"], open_store)
            out["restore"] = {"back": back_["back"], "skipped": [by_note[n] for n in back_["skipped"]],
                              "missing": back_["missing"], "media_missing": back_["media_missing"]}
            infos = ask("notesInfo", notes=ask("findNotes", query=f"tag:{drill_tag}"))
            out["notes_for_mined_again_word"] = sum(1 for n in infos if n["fields"][front]["value"] ==
                                                    word["control_mined_again"])
            out["control_back"] = any(n["fields"][front]["value"] == word["control"] for n in infos)
            out["temp_deck_after_undo"] = tidy.TEMP_DECK.format(id=done["id"]) in ask("deckNames")
            out["state_after_undo"] = tidy.tidy_row(ledger, done["id"])["state"]
            with anki_connect.writer("Kyou-SH3 tidy drill", wait=60):
                got = ask("retrieveMediaFile", filename=clip)
            out["clip_back_same"] = bool(got) and base64.b64decode(got) == clip_bytes
        finally:
            ledger.close()
            if ask("getActiveProfile") == "DevTest":
                with anki_connect.writer("Kyou-SH3 tidy drill teardown", wait=60):
                    left = ask("findNotes", query=f"tag:{drill_tag}")
                    if left:
                        ask("deleteNotes", notes=left)
                    ask("deleteMediaFile", filename=clip)
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
