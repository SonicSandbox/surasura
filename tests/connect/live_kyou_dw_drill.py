"""Kyou-DW's proof on DevTest: a Connect card the learner deletes in Anki asks why, each answer does what it says and
its Undo takes it back, and the deletes from before the loop asked are offered once (never run by the suites; by hand,
under `with-lock.sh anki`, Anki open — the drill loads DevTest and puts the profile back at the end).

    python tests/connect/live_kyou_dw_drill.py --profile DevTest

- One episode's batch "mined" in DevTest (real words, Basic notes with the job's tag), ended as the runner ends a job
  (`end_batch` with each card's sentence and its deck, the library's made words), plus one older card whose delete the
  old version's look already told the store (`library.notes_gone` with no stamp: a delete from before the loop asked).
- The learner deletes four cards by hand (`deleteNotes`); Connect's real look (`runner.Steps.notes_gone`, twice: two
  runs) records them once and keeps the one-time list of older deletes.
- *Known* on one (the word lists' writer) and *Bad card* on another (Swap's maker: its look queues a job, the job
  "mines" the new card in DevTest and ends through the runner's record step, Swap's next look marks it made); then
  *Same for all* (Ignore) on the two the card still asks about. Each one's Undo: the word back as it was, the Bad
  card's new card deleted with a backup by Swap's own Undo (`swap.act_undo`, as the window presses it) — every card
  asks again.
- The one-time list: its *Needs you* card, *Forget* (the store's `allow_again`), its Undo.

`getActiveProfile == "DevTest"` before anything and before teardown. Teardown: every note with the drill's tag deleted
(a test-only delete, holding `anki-writer`), Tidy's own decks deleted once empty, counted back to 0. The ledger, the
library, the word lists and the backups are in a temp root (`SURASURA_TEST_ROOT`): Sonic's are never opened.
"""
import argparse
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# (word, the card's line) — Connect's batch: known, bad card, then two for Same for all; then the older delete
CARDS = [("約束", "明日の約束を忘れないでね。"), ("気配", "誰かの気配がした。"),
         ("溜め息", "思わず溜め息が出た。"), ("夕焼け", "夕焼けがとてもきれいだ。")]
OLD = ("木漏れ日", "木漏れ日が揺れている。")
BAD_OTHER = "春の気配を感じる。"          # the Bad card's new card: another line saying 気配


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
    root = tempfile.mkdtemp(prefix="kyou-dw2-")
    os.environ["SURASURA_TEST_ROOT"] = root
    os.environ.pop("SURASURA_NO_ANKI_SYNC", None)
    sys.path.insert(0, REPO)
    from app import anki_connect
    from app.connect import deleted, library, runner, swap
    from app.connect import ledger as ledger_mod
    from app.connect.ledger import Ledger
    from app.services import needs, word_marks
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
        with anki_connect.writer("Kyou-DW 2 drill", wait=60):
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
        drill_tag = f"surasura::test-kyoudw2-{run}"
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
                with anki_connect.writer("Kyou-DW 2 drill", wait=60):
                    return ask("addNotes", notes=[{"deckName": "DevTest", "modelName": model,
                                                   "options": {"allowDuplicate": True}, "tags": [drill_tag] + tags,
                                                   "fields": {front: word, back: text}}])[0]

            def end_job(job, rows):
                ledger.end_batch(job, 1, "done", rows, deck="DevTest")
                runner._record_made(runner.Steps({}), ledger, "ja", ledger.job_by_id(job), True)
                ledger.set_state(job, "done")

            # Connect's batch, and the older card the old version's look saw deleted
            job = ledger.queue("ja", items[0], "user", None, store_id="drill")
            tag = f"surasura::connect::{ledger.tag_id(job)}"
            notes = [add(w, line, [tag]) for w, line in CARDS + [OLD]]
            end_job(job, [{"word": w, "reading": "", "outcome": "made", "note_id": n, "sentence": line,
                           "line_start": 10.0 + i} for i, ((w, line), n) in enumerate(zip(CARDS + [OLD], notes))])
            old_note = notes[-1]
            write("deleteNotes", notes=[old_note])
            with c.store("ja") as s:
                library.notes_gone(s, [old_note])           # the old version: the store told, nothing stamped
            # the learner deletes four cards by hand; Connect's look, two runs
            write("deleteNotes", notes=notes[:4])
            looks = [runner.Steps({"connect_enabled": True}).notes_gone("ja") for _ in range(2)]
            out["looks"] = looks
            stamped = ledger.conn.execute("SELECT COUNT(*) FROM deleted WHERE language = 'ja'").fetchone()[0]
            checks["recorded once"] = sorted(looks[0]) == sorted(notes[:4]) and looks[1] == [] and stamped == 4
            rec = deleted.status_of(ledger.conn, "ja")
            checks["four asked"] = sorted(r["note_id"] for r in rec["asked"]) == sorted(notes[:4])
            checks["old list once"] = [o["word"] for o in rec["old"]] == [OLD[0]]
            known, bad, rest = notes[0], notes[1], notes[2:4]
            # Known
            got = deleted.answer("ja", [known], deleted.KNOWN, ledger=ledger)
            checks["known"] = got["done"] == [(known, CARDS[0][0])] and \
                word_marks.states("ja", [CARDS[0][0]])[CARDS[0][0]] == "known"
            # Bad card -> Swap's maker, its look, its job made in DevTest through the runner's record step
            real_choose = swap.choose_line
            swap.choose_line = lambda language, word, *a_, **k: (items[1], BAD_OTHER)    # the line, handed in
            try:
                got = deleted.answer("ja", [bad], deleted.BAD, ledger=ledger)
                checks["bad asked"] = got["done"] == [(bad, CARDS[1][0])]
                out["swap_look_1"] = swap.look(Steps(), ledger, "ja", anki=swap.AnkiSwap(a.url), files=5)
            finally:
                swap.choose_line = real_choose
            (row,) = swap._rows(ledger, "language = 'ja'")
            out["swap_row"] = {k: row[k] for k in ("by", "old_note", "state", "line", "avoid")}
            checks["bad queued"] = (row["by"], row["old_note"], row["state"]) == (swap.BY_BAD_CARD, bad, swap.QUEUED) \
                and CARDS[1][1] in json.loads(row["avoid"] or "[]") and row["line"] == BAD_OTHER
            new = add(CARDS[1][0], BAD_OTHER, [f"surasura::connect::{ledger.tag_id(row['job_id'])}"])
            time.sleep(1.5)
            end_job(row["job_id"], [{"word": CARDS[1][0], "reading": "", "outcome": "made", "note_id": new,
                                     "sentence": BAD_OTHER}])
            time.sleep(6)                   # past the grace: the batch "ended" before any mod could look like an edit
            ledger.conn.execute("UPDATE jobs SET updated_at = ?", (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),))
            ledger.conn.commit()
            time.sleep(7)
            out["swap_look_2"] = swap.look(Steps(), ledger, "ja", anki=swap.AnkiSwap(a.url), files=5)
            (row,) = swap._rows(ledger, "language = 'ja'")
            checks["bad made"] = (row["state"], row["new_note"]) == (swap.MADE, new)
            # Same for all on the two the card still asks about, as the window passes them
            entries = needs._deleted_entries({"deleted": deleted.status_of(ledger.conn, "ja")}, set(), set())
            kinds = {e.kind: e for e in entries}
            same = list((kinds[needs.DELETED].data or {}).get("notes") or ())
            out["same_for_all_notes"] = same
            got = deleted.answer("ja", same, deleted.IGNORE, ledger=ledger)
            states = word_marks.states("ja", [w for w, _l in CARDS[2:4]])
            checks["same for all"] = sorted(same) == sorted(rest) and len(got["done"]) == 2 and \
                set(states.values()) == {"ignore"}
            checks["none asked"] = deleted.status_of(ledger.conn, "ja")["asked"] == []
            # each one's Undo
            u1 = deleted.undo("ja", [known], ledger=ledger, settings=settings)
            u2 = deleted.undo("ja", [bad], settings=settings)
            u3 = deleted.undo("ja", rest, ledger=ledger, settings=settings)
            out["undos"] = [u1, u2, u3]
            states = word_marks.states("ja", [w for w, _l in CARDS])
            checks["undos done"] = all(u["skipped"] == [] for u in (u1, u2, u3)) and \
                len(u1["done"]) + len(u2["done"]) + len(u3["done"]) == 4
            checks["words back"] = all(v is None for k, v in states.items() if k != CARDS[1][0])
            checks["bad card's new card gone"] = ask("findNotes", query=f"nid:{new}") == []
            checks["backup kept"] = all(os.path.isfile(os.path.join(r[0], "cards.apkg")) for r in ledger.conn.execute(
                "SELECT folder FROM tidies WHERE why = 'swap'")) and ledger.conn.execute(
                "SELECT COUNT(*) FROM tidies WHERE why = 'swap'").fetchone()[0] == 1
            checks["all asked again"] = sorted(r["note_id"] for r in deleted.status_of(ledger.conn, "ja")["asked"]) \
                == sorted(notes[:4])
            # the old deletes, once: the card, Forget, its Undo
            entries = needs._deleted_entries({"deleted": deleted.status_of(ledger.conn, "ja")}, set(), set())
            old_entry = next((e for e in entries if e.kind == needs.OLD_DELETES), None)
            out["old_entry"] = (old_entry.title, [ln.text for ln in old_entry.lines]) if old_entry else None
            with library.open_store("ja") as s:
                before = OLD[0] in library.made_words_all(s)
                change = s.allow_again([OLD[0]])
                forgotten = OLD[0] not in library.made_words_all(s)
                s.undo(change)
                back_again = OLD[0] in library.made_words_all(s)
            checks["old card shown"] = old_entry is not None and any(OLD[0] in t for t in out["old_entry"][1])
            checks["forget + undo"] = before and forgotten and back_again
        finally:
            ledger.close()
            if ask("getActiveProfile") == "DevTest":
                with anki_connect.writer("Kyou-DW 2 drill teardown", wait=60):
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
