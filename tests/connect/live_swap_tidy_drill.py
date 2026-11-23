"""Kantan-SL 5's proof on DevTest: a swap's new card survives an ordinary tidy (you asked for it), and the swap's own
Undo takes it back — with a home on record, and with none while it sits in the deck Surasura shows (never run by the
suites; by hand, under `with-lock.sh anki`, Anki open — the drill loads DevTest and puts the profile back at the end).

    python tests/connect/live_swap_tidy_drill.py --profile DevTest

- Two old cards of the learner's in DevTest (real words), each Suspended + Green as the review loop's ⇄ leaves it,
  queued in a scratch swap queue (`swap_queue.add`); Connect's look (`swap.look`, the line handed in: no Anki Miner
  here) turns each into a job of kind swap. Each job "mines" its new card in DevTest (`addNotes` with the job's tag),
  its batch ended as the runner ends it — the first with its deck recorded (`end_batch(deck="DevTest")`: a home), the
  second with none (a lost or empty mapping deck) — recorded in a scratch library's made words, then the next look
  marks each swap made and tags its old card `surasura::swapped`. One ordinary Connect card beside them (its own job,
  its home DevTest).
- *Tidy now* (`tidy.run`, why now, `ours` = DevTest): the ordinary card goes; both swaps' new cards stay (`ASKED`),
  the old cards untouched (suspended, green, tagged).
- *Undo* on each swap as the window presses it (`swap.act_undo` with settings naming DevTest as Surasura's deck):
  both new cards deleted with a backup; each old card back in reviews, its flag off, its tag gone.

`getActiveProfile == "DevTest"` before anything and before teardown. Teardown: every note with the drill's tag deleted
(a test-only delete, holding `anki-writer`), Tidy's own decks deleted once empty, counted back to 0. The ledger, the
library, the swap queue and the backups are in a temp root (`SURASURA_TEST_ROOT`): Sonic's are never opened.
"""
import argparse
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# (the word, its old card's line, the other line its new card is cut from) — real lines
SWAPS = [("約束", "明日の約束を忘れないでね。", "約束は必ず守るよ。"),
         ("気配", "誰かの気配がした。", "春の気配を感じる。")]
PLAIN = ("溜め息", "思わず溜め息が出た。")


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
    root = tempfile.mkdtemp(prefix="kantan-sl5-swap-")
    os.environ["SURASURA_TEST_ROOT"] = root
    os.environ.pop("SURASURA_NO_ANKI_SYNC", None)
    sys.path.insert(0, REPO)
    from app import anki_connect
    from app.connect import library, runner, swap, swap_queue, tidy
    from app.connect import ledger as ledger_mod
    from app.connect.ledger import Ledger
    from tests import connect_helpers as c
    from tests import cli_helpers as h

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
        with anki_connect.writer("Kantan-SL 5 swap drill", wait=60):
            return ask(action, **params)

    class Steps:                        # Connect's steps the look asks: the episode's video is there
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
    open_store = lambda: library.open_store("ja")      # noqa: E731
    run = time.strftime("%Y%m%d%H%M%S")
    settings = {"junban_scope": "deck", "junban_deck": "DevTest"}
    try:
        if ask("getActiveProfile") != "DevTest":
            sys.exit("REFUSED: Anki isn't on DevTest")
        drill_tag = f"surasura::test-swap5-{run}"
        c.library("ja")
        folder = os.path.join(h.root(), "User Files", "ja")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "KnownWord.json"), "w", encoding="utf-8") as f:
            json.dump({"words": []}, f)
        with open(os.path.join(folder, "IgnoreList.txt"), "w", encoding="utf-8") as f:
            f.write("")
        out["ledger_in_temp_root"] = os.path.abspath(ledger_mod.path()).startswith(os.path.abspath(root))
        if not out["ledger_in_temp_root"]:
            sys.exit("REFUSED: the ledger isn't in the drill's temp root")
        ledger = Ledger(ledger_mod.path())
        anki = swap.AnkiSwap(a.url)
        try:
            with c.store("ja") as s:
                items = s.ids("now")[:3]
            models = ask("modelNames")
            model = "Basic" if "Basic" in models else models[0]
            front, back = ask("modelFieldNames", modelName=model)[:2]

            def add(word, text, tags):
                with anki_connect.writer("Kantan-SL 5 swap drill", wait=60):
                    return ask("addNotes", notes=[{"deckName": "DevTest", "modelName": model,
                                                   "options": {"allowDuplicate": True}, "tags": [drill_tag] + tags,
                                                   "fields": {front: word, back: text}}])[0]
            # the learner's old cards, swapped in the review loop: Suspend + Green
            old = {}
            for word, line, _other in SWAPS:
                note = add(word, line, [])
                card = ask("findCards", query=f"nid:{note}")[0]
                write("suspend", cards=[card])
                with anki_connect.writer("Kantan-SL 5 swap drill", wait=60):
                    anki.set_flag([card], swap.GREEN)
                old[word] = (note, card)
                swap_queue.add("ja", word, card, note, f"drill-{run}")
            picks = {word: (items[n], other) for n, (word, _line, other) in enumerate(SWAPS)}
            real_choose = swap.choose_line
            swap.choose_line = lambda language, word, *a_, **k: picks[word]     # the line, handed in
            try:
                out["look_1"] = swap.look(Steps(), ledger, "ja", anki=anki, files=5)
            finally:
                swap.choose_line = real_choose
            rows = {r["word"]: r for r in swap._rows(ledger, "language = 'ja'")}
            new = {}
            for n, (word, _line, other) in enumerate(SWAPS):
                job = rows[word]["job_id"]
                note = add(word, other, [f"surasura::connect::{ledger.tag_id(job)}"])
                new[word] = note
            job_plain = ledger.queue("ja", items[2], "user", None, store_id="drill")
            plain = add(PLAIN[0], PLAIN[1], [f"surasura::connect::{ledger.tag_id(job_plain)}"])
            time.sleep(1.5)
            # the runner's record step: the batch's end with its deck (the second swap: none), the made words, done
            for n, (word, _line, _other) in enumerate(SWAPS):
                job = rows[word]["job_id"]
                ledger.end_batch(job, 1, "done", [{"word": word, "reading": "", "outcome": "made",
                                                   "note_id": new[word]}], deck="DevTest" if n == 0 else None)
                runner._record_made(runner.Steps({}), ledger, "ja", ledger.job_by_id(job), True)
                ledger.set_state(job, "done")
            ledger.end_batch(job_plain, 1, "done", [{"word": PLAIN[0], "reading": "", "outcome": "made",
                                                     "note_id": plain}], deck="DevTest")
            runner._record_made(runner.Steps({}), ledger, "ja", ledger.job_by_id(job_plain), True)
            ledger.set_state(job_plain, "done")
            time.sleep(6)                   # past the grace: the batch "ended" before any mod could look like an edit
            ledger.conn.execute("UPDATE jobs SET updated_at = ?", (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),))
            ledger.conn.commit()
            out["homes"] = {w: ledger.homes([new[w]]).get(new[w]) for w, _l, _o in SWAPS}
            time.sleep(7)
            out["look_2"] = swap.look(Steps(), ledger, "ja", anki=anki, files=5)
            rows = {r["word"]: r for r in swap._rows(ledger, "language = 'ja'")}
            out["made"] = {w: (rows[w]["state"], rows[w]["new_note"] == new[w]) for w, _l, _o in SWAPS}
            # an ordinary tidy, Settings' *Tidy now*: the plain card goes, the swaps' new cards stay
            done = tidy.run(tidy.AnkiConnectTidy(a.url), ledger, "ja", [new[w] for w, _l, _o in SWAPS] + [plain],
                            why=tidy.NOW, open_store=open_store, ours="DevTest")
            names = {v: k for k, v in new.items()}
            names[plain] = "plain"
            out["tidy_deleted"] = [names.get(n, n) for n in done["deleted"]]
            out["tidy_kept"] = {names.get(n, n): why for n, why in done["kept"]}
            olds = ask("cardsInfo", cards=[old[w][1] for w, _l, _o in SWAPS])
            out["old_after_tidy"] = {i["cardId"]: (i["queue"], i.get("flags")) for i in olds}
            out["old_tagged"] = [swap.SWAP_TAG.lower() in [t.lower() for t in n.get("tags") or ()]
                                 for n in ask("notesInfo", notes=[old[w][0] for w, _l, _o in SWAPS])]
            # the swaps' Undo, as *Needs you* presses it
            out["undo"] = {w: swap.act_undo(settings, "ja", rows[w]["id"]) for w, _l, _o in SWAPS}
            out["new_left"] = ask("findNotes", query=" or ".join(f"nid:{new[w]}" for w, _l, _o in SWAPS))
            olds = ask("cardsInfo", cards=[old[w][1] for w, _l, _o in SWAPS])
            out["old_after_undo"] = {i["cardId"]: (i["queue"], i.get("flags")) for i in olds}
            out["old_tag_after_undo"] = [swap.SWAP_TAG.lower() in [t.lower() for t in n.get("tags") or ()]
                                         for n in ask("notesInfo", notes=[old[w][0] for w, _l, _o in SWAPS])]
            out["backups"] = [os.path.isfile(os.path.join(r[0], "cards.apkg"))
                              for r in ledger.conn.execute("SELECT folder FROM tidies WHERE why = 'swap'")]
        finally:
            ledger.close()
            if ask("getActiveProfile") == "DevTest":
                with anki_connect.writer("Kantan-SL 5 swap drill teardown", wait=60):
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
