"""Kyou-SH2's proof on DevTest: Tidy's backup, delete and Undo against a real Anki (never run by the suites; by hand,
under `with-lock.sh anki`, Anki open — the drill loads DevTest and puts the profile it found back at the end).

    python tests/connect/live_tidy_drill.py --profile DevTest

- A test batch: four Basic notes in deck DevTest, real words, one finished job of a scratch ledger (outcomes `made`),
  each tagged with the job's tag and the drill's own; the first carries a clip (stored in Anki's media).
- One card studied (`answerCards`): Tidy keeps it (*you've studied it*).
- `tidy.run` (holding `anki-writer`): the other three go — the package Anki exported holds exactly them (its note ids
  read back), notes.json and the clip's bytes in the backup, the clip gone from Anki's media, the tidy's own deck gone.
- `tidy.restore`: the package imported (and once more: no second copy), the three notes back — the drill reports whether Anki kept their ids — with
  the same fields and tags, every card in DevTest again, the clip back byte for byte, the tidy's own deck gone.

`getActiveProfile == "DevTest"` before anything and before teardown. Teardown: every note with the drill's tag deleted
(a test-only delete, holding `anki-writer`), the clip deleted, both counted back to 0. The ledger and the backup are
in a temp root (`SURASURA_TEST_ROOT`): Sonic's ledger and library are never opened.
"""
import argparse
import base64
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORDS = ["上層部", "一生懸命", "走り出す", "気配"]


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
    root = tempfile.mkdtemp(prefix="kyou-sh2-tidy-")
    os.environ["SURASURA_TEST_ROOT"] = root
    os.environ.pop("SURASURA_NO_ANKI_SYNC", None)
    sys.path.insert(0, REPO)
    from app import anki_connect
    from app.connect import tidy, undo
    from app.connect.ledger import Ledger

    def ask(action, **params):
        return anki_connect.invoke(action, a.url, timeout=120, **params)

    def on(profile):
        """Wait (up to 60 s) until Anki has `profile` open: a profile switch takes a few seconds."""
        for _ in range(60):
            try:
                if ask("getActiveProfile") == profile:
                    return True
            except anki_connect.AnkiError:
                pass
            time.sleep(1)
        return False

    found = ask("getActiveProfile")
    if ask("guiReviewActive"):
        sys.exit("REFUSED: someone is reviewing in Anki")
    if found != "DevTest":
        say("loading DevTest (found", found, ")")
        with anki_connect.writer("Kyou-SH2 tidy drill", wait=60):
            ask("loadProfile", name="DevTest")
        on("DevTest")
    out = {"root": root, "profile_found": found}
    try:
        if ask("getActiveProfile") != "DevTest":
            sys.exit("REFUSED: Anki isn't on DevTest")
        run = time.strftime("%Y%m%d%H%M%S")
        drill_tag = f"surasura::test-tidy-{run}"
        clip = f"surasura-tidy-drill-{run}.mp3"
        clip_bytes = ("ID3 tidy drill " + run).encode("utf-8") * 40
        ledger = Ledger(os.path.join(root, "connect", "ledger.sqlite"))
        try:
            job_id = ledger.queue("ja", 1, "user", None, store_id="drill")
            job_tag = f"surasura::connect::{ledger.tag_id(job_id)}"
            models = ask("modelNames")
            model = "Basic" if "Basic" in models else models[0]
            front, back = ask("modelFieldNames", modelName=model)[:2]
            with anki_connect.writer("Kyou-SH2 tidy drill", wait=60):
                ask("storeMediaFile", filename=clip, data=base64.b64encode(clip_bytes).decode("ascii"))
                notes = [{"deckName": "DevTest", "modelName": model, "options": {"allowDuplicate": True},
                          "tags": [drill_tag, job_tag],
                          "fields": {front: w, back: (f"[sound:{clip}] " if i == 0 else "") + f"Tidy drill {i}"}}
                         for i, w in enumerate(WORDS)]
                ids = ask("addNotes", notes=notes)
            time.sleep(1.5)
            ledger.end_batch(job_id, 1, "done", [{"word": w, "reading": "", "outcome": "made", "note_id": n}
                                                 for n, w in zip(ids, WORDS)])
            ledger.set_state(job_id, "done")
            out["notes"] = ids
            studied = ids[3]
            card = ask("findCards", query=f"nid:{studied}")[0]
            with anki_connect.writer("Kyou-SH2 tidy drill", wait=60):
                out["answered"] = ask("answerCards", answers=[{"cardId": card, "ease": 3}])
            before = {n["noteId"]: n for n in ask("notesInfo", notes=ids[:3])}
            cards_before = {c["cardId"]: c["deckName"] for c in ask("cardsInfo", cards=ask("findCards",
                                                                                           query=f"tag:{drill_tag}"))}
            anki = tidy.AnkiConnectTidy(a.url)
            time.sleep(6)                   # past the grace: the batch "ended" before any mod could look like an edit
            ledger.conn.execute("UPDATE jobs SET updated_at = ? WHERE id = ?",
                                (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), job_id))
            done = tidy.run(anki, ledger, "ja", ids, why=tidy.NOW)
            row = tidy.tidy_row(ledger, done["id"])
            out["tidy"] = {"deleted": sorted(done["deleted"]), "kept": done["kept"], "state": row["state"]}
            out["package_notes"] = sorted(tidy.package_notes(os.path.join(row["folder"], "cards.apkg")) or [])
            out["package_names"] = __import__("zipfile").ZipFile(os.path.join(row["folder"], "cards.apkg")).namelist()
            out["backup_clip_same"] = open(os.path.join(row["folder"], "media", clip), "rb").read() == clip_bytes
            with anki_connect.writer("Kyou-SH2 tidy drill", wait=60):     # AnkiConnect's media reads are writes here
                out["clip_in_anki_after_tidy"] = bool(ask("retrieveMediaFile", filename=clip))
            out["left_after_tidy"] = ask("findNotes", query=f"tag:{drill_tag}")
            out["temp_deck_after_tidy"] = tidy.TEMP_DECK.format(id=done["id"]) in ask("deckNames")
            back = tidy.restore(anki, ledger, done["id"])
            out["restore"] = back
            now_ids = ask("findNotes", query=f"tag:{drill_tag}")
            out["ids_after_undo"] = sorted(now_ids)
            out["ids_kept"] = sorted(set(now_ids) & set(ids[:3])) == sorted(ids[:3])
            infos = {n["noteId"]: n for n in ask("notesInfo", notes=now_ids)}
            same = []
            for old, note in before.items():
                match = infos.get(old) or next((n for n in infos.values() if n["fields"] == note["fields"]), None)
                same.append(bool(match) and match["fields"] == note["fields"] and sorted(match["tags"]) == sorted(
                    note["tags"]))
            out["fields_tags_same"] = same
            cards_after = {c["cardId"]: c["deckName"] for c in ask("cardsInfo", cards=ask("findCards",
                                                                                          query=f"tag:{drill_tag}"))}
            out["decks_after_undo"] = sorted(set(cards_after.values()))
            out["card_ids_kept"] = sorted(cards_after) == sorted(cards_before)
            with anki_connect.writer("Kyou-SH2 tidy drill", wait=60):
                got = ask("retrieveMediaFile", filename=clip)
            out["clip_back_same"] = bool(got) and base64.b64decode(got) == clip_bytes
            out["temp_deck_after_undo"] = tidy.TEMP_DECK.format(id=done["id"]) in ask("deckNames")
            out["state_after_undo"] = tidy.tidy_row(ledger, done["id"])["state"]
            # the review's S7: a second import of the same package (an Undo pressed again after a half-way one) adds
            # no second copy of a note Anki has (the importer matches by its guid)
            with anki_connect.writer("Kyou-SH2 tidy drill", wait=60):
                anki.import_package(os.path.join(row["folder"], "cards.apkg"))
                tidy._drop_temp(anki, done["id"])
            out["notes_after_second_import"] = len(ask("findNotes", query=f"tag:{drill_tag}"))
        finally:
            ledger.close()
            if ask("getActiveProfile") == "DevTest":
                with anki_connect.writer("Kyou-SH2 tidy drill teardown", wait=60):
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
            with anki_connect.writer("Kyou-SH2 tidy drill", wait=60):
                ask("loadProfile", name=a.back_to)
            on(a.back_to)
            out["profile_back"] = ask("getActiveProfile")
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
