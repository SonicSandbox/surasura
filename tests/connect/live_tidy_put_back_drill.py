"""Kyou-SH3 part 2's proof on DevTest: *Put back…* — an older tidy goes back with Undo's own rules, and never twice
(never run by the suites; by hand, under `with-lock.sh anki`, Anki open — the drill loads DevTest and puts the profile
back at the end).

    python tests/connect/live_tidy_put_back_drill.py --profile DevTest

- A test batch in deck DevTest, real words, one finished job of a scratch ledger (outcomes `made`) recorded in a
  scratch library's made words, each note tagged with the job's tag and the drill's own.
- Two tidies: *Tidy now* (NOW) takes the older's card, then one by itself (AUTO) the newer's; `tidy.past` lists both,
  newest first, each `can`.
- The OLDER put back (`tidy.restore` by its id): its card in Anki again, the newer's still deleted; the same tidy put
  back a second time is refused and adds no card; `tidy.past` then says it went back; the newer's Undo still works.

`getActiveProfile == "DevTest"` before anything and before teardown. Teardown: every note with the drill's tag deleted
(a test-only delete, holding `anki-writer`), counted back to 0, Tidy's empty decks removed. The ledger, the library and
the backups are in a temp root (`SURASURA_TEST_ROOT`): Sonic's are never opened.
"""
import argparse
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORDS = {"older": "雰囲気", "newer": "眼差し", "stays": "溜め息"}


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
    root = tempfile.mkdtemp(prefix="kyou-sh3-putback-")
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
        with anki_connect.writer("Kyou-SH3 put-back drill", wait=60):
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
        drill_tag = "surasura::test-putback-" + time.strftime("%Y%m%d%H%M%S")
        c.library("ja")
        ledger = Ledger(os.path.join(root, "connect", "ledger.sqlite"))
        try:
            with c.store("ja") as s:
                item = s.ids("now")[0]
            job_id = ledger.queue("ja", item, "user", None, store_id="drill")
            job_tag = f"surasura::connect::{ledger.tag_id(job_id)}"
            models = ask("modelNames")
            model = "Basic" if "Basic" in models else models[0]
            front, back = ask("modelFieldNames", modelName=model)[:2]
            ids = write("addNotes", notes=[
                {"deckName": "DevTest", "modelName": model, "options": {"allowDuplicate": True},
                 "tags": [drill_tag, job_tag], "fields": {front: w, back: f"Put back drill: {case}"}}
                for case, w in WORDS.items()])
            note = dict(zip(WORDS, ids))
            time.sleep(1.5)
            ledger.end_batch(job_id, 1, "done", [{"word": w, "reading": "", "outcome": "made", "note_id": note[cs]}
                                                 for cs, w in WORDS.items()], deck="DevTest")
            ledger.set_state(job_id, "done")
            with c.store("ja") as s:
                library.record_batch(s, item, {w: [note[cs]] for cs, w in WORDS.items()},
                                     time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), batch="drill")
            time.sleep(6)                   # past the grace: nothing reads as your edit
            anki = tidy.AnkiConnectTidy(a.url)
            older = tidy.run(anki, ledger, "ja", [note["older"]], why=tidy.NOW, open_store=open_store)
            newer = tidy.run(anki, ledger, "ja", [note["newer"]], why=tidy.AUTO, open_store=open_store)
            out["tidied"] = {"older": older["deleted"] == [note["older"]], "newer": newer["deleted"] == [note["newer"]]}
            label = {older["id"]: "older", newer["id"]: "newer"}
            out["past_before"] = [(label.get(p["id"]), p["can"], p["cards"]) for p in tidy.past(ledger, "ja")]

            def words_in_anki():
                infos = ask("notesInfo", notes=ask("findNotes", query=f"tag:{drill_tag}"))
                return sorted(n["fields"][front]["value"] for n in infos)
            back_ = tidy.restore(anki, ledger, older["id"], open_store, language="ja")
            out["older_back"] = {"back": back_["back"], "skipped": back_["skipped"], "missing": back_["missing"]}
            out["words_after_older"] = words_in_anki()
            try:
                tidy.restore(anki, ledger, older["id"], open_store, language="ja")
                out["older_twice"] = "PUT BACK AGAIN (wrong)"
            except tidy.Refused as e:
                out["older_twice"] = e.say
            out["words_after_twice"] = words_in_anki()
            out["past_after"] = [(label.get(p["id"]), p["can"]) for p in tidy.past(ledger, "ja")]
            out["newer_back"] = tidy.restore(anki, ledger, newer["id"], open_store, language="ja")["back"]
            out["words_at_end"] = words_in_anki()
            out["tidy_decks_left"] = [d for d in ask("deckNames")
                                      if d in {tidy.TEMP_DECK.format(id=i) for i in label}]
        finally:
            ledger.close()
            if ask("getActiveProfile") == "DevTest":
                with anki_connect.writer("Kyou-SH3 put-back drill teardown", wait=60):
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
