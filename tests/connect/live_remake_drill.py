"""REMAKE's proof on DevTest, part 1 (session 1): *Make my new cards again…* against a real Anki — the selection (Anki's
own `is:new` and its subdeck search), the sync asked under the write lock, the backup read back, the delete, and Undo
field for field (never run by the suites; by hand, under `with-lock.sh anki`, Anki open — the drill loads DevTest and
puts the profile back at the end). Session 2 adds the re-check before the delete (`phone`: a card answered as the second
sync is asked, as a phone review arriving then would be: kept, named, marked kept in the backup). Connect mining the
words again is part 2, `live_remake_mine_drill.py`.

    python tests/connect/live_remake_drill.py --profile DevTest --lang ja

- Every card is in the drill's own top-level deck (`Surasura Remake Drill <run>`, and one subdeck of it), never
  DevTest's own: the remake takes every never-reviewed card of Connect's note type in Surasura's decks, so the drill
  gives it a deck holding only its own cards. A scratch ledger and library (a temp `SURASURA_TEST_ROOT`): one finished
  job made the notes (outcomes `made`, the made words, the home deck).
- The cases (real words of the language): made and plain · suspended · buried · edited (these go); reviewed ·
  reviewed then suspended (not new: never read) · answered then reset to new (read, kept: studied) · Suspend + red
  flag (Ignore) · Suspend + Mark (Known) · moved into the subdeck (never read) · studied on the phone during the copy
  (planned, then kept at the last read); from before: new (goes with the tick)
  · reviewed (stays) · another note type (kept: Surasura didn't make it).
- `tidy.remake_plan`, then `tidy.remake(before=True)`; the backup read back; then `tidy.restore` and each removed note
  compared with how it was (fields, tags, note type, each card's deck, queue and flags).

`getActiveProfile == "DevTest"` before anything and before teardown. Teardown: every note with the drill's tag
deleted, the drill's decks and Tidy's own deck removed (holding `anki-writer`), counted back to 0.
"""
import argparse
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORDS = {"ja": ["上層部", "一生懸命", "走り出す", "気配", "溜め息", "約束", "雰囲気", "手作り", "眼差し", "仰ぐ",
                "撒く", "泥塗れ", "見込み", "眩しい"],
         "zh": ["遗憾", "漂亮", "哎呀", "约定", "叹气", "气氛", "学习", "眼神", "约翰", "仰望", "撒谎", "泥土", "希望", "耀眼"]}
MADE = ["plain", "suspended", "buried", "edited", "reviewed", "reviewed_suspended", "reset", "ignore", "known",
        "subdeck", "phone"]
BEFORE = ["before_new", "before_reviewed", "before_other_model"]
GO = {"plain", "suspended", "buried", "edited", "before_new"}


def say(*parts):
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--profile", required=True)
    ap.add_argument("--lang", choices=["ja", "zh"], required=True)
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--back-to", default="User 1", help="the profile loaded at the end (lane rules: Sonic's own)")
    a = ap.parse_args()
    if a.profile != "DevTest":
        sys.exit("REFUSED: the drill runs on the DevTest profile only")
    root = tempfile.mkdtemp(prefix="remake-drill-")
    os.environ["SURASURA_TEST_ROOT"] = root
    os.environ.pop("SURASURA_NO_ANKI_SYNC", None)
    sys.path.insert(0, REPO)
    from app import anki_connect
    from app.connect import library, tidy
    from app.connect.ledger import Ledger
    from tests import connect_helpers as c
    lang = a.lang

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
        with anki_connect.writer("REMAKE drill", wait=60):
            return ask(action, **params)

    found = ask("getActiveProfile")
    if ask("guiReviewActive"):
        sys.exit("REFUSED: someone is reviewing in Anki")
    if found != "DevTest":
        say("loading DevTest (found", found, ")")
        write("loadProfile", name="DevTest")
        on("DevTest")
    out = {"root": root, "lang": lang, "profile_found": found}
    open_store = lambda: library.open_store(lang)      # noqa: E731
    run = time.strftime("%Y%m%d%H%M%S")
    deck = f"Surasura Remake Drill {run}"
    sub = f"{deck}::Mine"
    drill_tag = f"surasura::test-remake-{run}"
    try:
        if ask("getActiveProfile") != "DevTest":
            sys.exit("REFUSED: Anki isn't on DevTest")
        c.library(lang)
        ledger = Ledger(os.path.join(root, "connect", "ledger.sqlite"))
        try:
            with c.store(lang) as s:
                item = s.ids("now")[0]
            job_id = ledger.queue(lang, item, "user", None, store_id="drill")
            job_tag = f"surasura::connect::{ledger.tag_id(job_id)}"
            models = ask("modelNames")
            model = "Basic" if "Basic" in models else models[0]
            other_model = next((m for m in models if m != model and len(ask("modelFieldNames", modelName=m)) >= 2),
                               None)
            front, back = ask("modelFieldNames", modelName=model)[:2]
            write("createDeck", deck=deck)
            write("createDeck", deck=sub)
            cases = MADE + BEFORE
            words = dict(zip(cases, WORDS[lang]))

            def note_of(case):
                m = other_model if case == "before_other_model" and other_model else model
                f, b = ask("modelFieldNames", modelName=m)[:2]
                tags = [drill_tag] + ([job_tag] if case in MADE else ["anki_miner"])
                return {"deckName": deck, "modelName": m, "options": {"allowDuplicate": True}, "tags": tags,
                        "fields": {f: words[case], b: f"Remake {case}"}}
            ids = write("addNotes", notes=[note_of(cs) for cs in cases])
            note = dict(zip(cases, ids))
            ledger.end_batch(job_id, 1, "done", [{"word": words[cs], "reading": "", "outcome": "made",
                                                  "note_id": note[cs]} for cs in MADE], deck=deck)
            ledger.set_state(job_id, "done")
            with c.store(lang) as s:
                library.record_batch(s, item, {words[cs]: [note[cs]] for cs in MADE},
                                     time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), batch="drill")
            card = {cs: ask("findCards", query=f"nid:{n}")[0] for cs, n in note.items()}
            write("suspend", cards=[card["suspended"]])
            write("setSpecificValueOfCard", card=card["buried"], keys=["queue"], newValues=[-3], warning_check=True)
            write("updateNoteFields", note={"id": note["edited"], "fields": {back: "Remake edited: 自分のメモ"}})
            for cs in ("reviewed", "reviewed_suspended", "reset", "before_reviewed"):
                write("answerCards", answers=[{"cardId": card[cs], "ease": 3}])
            write("suspend", cards=[card["reviewed_suspended"]])
            write("forgetCards", cards=[card["reset"]])
            write("setSpecificValueOfCard", card=card["reset"], keys=["reps", "lapses"], newValues=[0, 0],
                  warning_check=True)
            write("suspend", cards=[card["ignore"], card["known"]])
            write("setSpecificValueOfCard", card=card["ignore"], keys=["flags"], newValues=[1])
            write("addTags", notes=[note["known"]], tags="marked")
            write("changeDeck", cards=[card["subdeck"]], deck=sub)
            by_note = {v: k for k, v in note.items()}
            anki = tidy.AnkiConnectTidy(a.url)
            out["is_new_search"] = sorted(by_note.get(n, n) for n in tidy.remake_notes(anki, [deck]))
            with anki_connect.writer("REMAKE drill: the count", wait=60):     # the review log is read under it
                plan = tidy.remake_plan(anki, ledger, lang, {}, open_store)
            out["plan"] = {"made": sorted(by_note[n] for n in plan["made"]),
                           "before": sorted(by_note[n] for n in plan["before"]), "kept": plan["kept"],
                           "decks": plan["decks"], "models": plan["models"]}
            before = {n: (ask("notesInfo", notes=[n])[0], ask("cardsInfo", cards=[card[by_note[n]]])[0])
                      for n in ids}
            with anki_connect.writer("REMAKE drill: the sync's answer", wait=60):
                out["sync_answer"] = anki.sync()
            # session 2 (the lead's ruling): a review made on the phone while the copy was written arrives with the
            # second sync — played here by answering the `phone` card as that sync is asked (the remake holds the
            # writer: asked directly). Without the second sync and the read after it, the card would be deleted.
            syncs, plain_sync = [], anki.sync

            def phone_sync():
                syncs.append(ask("findCards", query='"deck:Surasura Tidy *"'))
                if len(syncs) == 2:
                    ask("answerCards", answers=[{"cardId": card["phone"], "ease": 3}])
                return plain_sync()
            anki.sync = phone_sync
            done = tidy.remake(anki, ledger, lang, {}, open_store, before=True)
            anki.sync = plain_sync
            out["syncs_in_the_remake"] = len(syncs)
            out["temp_deck_cards_at_the_second_sync"] = len(syncs[1]) if len(syncs) > 1 else None
            out["meanwhile"] = {by_note[n]: why for n, why in done.get("meanwhile") or ()}
            out["phone_card_kept"] = note["phone"] in ask("findNotes", query=f"tag:{drill_tag}")
            row = tidy.tidy_row(ledger, done["id"])
            out["deleted"] = sorted(by_note[n] for n in done["deleted"])
            out["kept"] = {by_note[n]: why for n, why in done["kept"]}
            out["deleted_is_the_never_reviewed_set"] = set(out["deleted"]) == GO
            out["phone_marked_kept"] = json.loads(row["notes"]).get(str(note["phone"]), {}).get("kept")
            out["read_back"] = tidy._read_back(row["folder"], [int(n) for n in json.loads(row["notes"])],   # every
                                               # note the copy was made of: the deleted and the one kept at the last read
                                               json.load(open(os.path.join(row["folder"], "notes.json"),
                                                              encoding="utf-8"))["media"])
            out["still_in_anki"] = sorted(by_note[n] for n in ask("findNotes", query=f"tag:{drill_tag}"))
            back_ = tidy.restore(anki, ledger, done["id"], open_store, word_of=tidy.card_word_of({}, lang))
            out["restore"] = {"back": back_["back"], "skipped": back_["skipped"], "missing": back_["missing"]}
            # the copy holds the phone card as it was before its review: Undo's import must leave the card Anki has
            phone_now = ask("cardsInfo", cards=[card["phone"]])[0]
            out["phone_after_undo"] = {"reps": phone_now.get("reps"), "type": phone_now.get("type"),
                                       "reviews": len((write("getReviewsOfCards", cards=[card["phone"]]) or {})
                                                      .get(str(card["phone"])) or [])}
            same = {}
            for n in done["deleted"]:
                was_note, was_card = before[n]
                now_note = ask("notesInfo", notes=[n])[0]
                now_card = ask("cardsInfo", cards=[card[by_note[n]]])[0]
                same[by_note[n]] = all([
                    {k: v["value"] for k, v in now_note["fields"].items()}
                    == {k: v["value"] for k, v in was_note["fields"].items()},
                    sorted(now_note["tags"]) == sorted(was_note["tags"]),
                    now_note["modelName"] == was_note["modelName"],
                    now_card["deckName"] == was_card["deckName"], now_card["queue"] == was_card["queue"],
                    now_card["flags"] == was_card["flags"]])
            out["undo_field_for_field"] = same
            out["temp_deck_after_undo"] = tidy.TEMP_DECK.format(id=done["id"]) in ask("deckNames")
            out["state_after_undo"] = tidy.tidy_row(ledger, done["id"])["state"]
            with c.store(lang) as s:
                out["words_made_again_after_undo"] = sorted(set(words[cs] for cs in MADE if cs in GO)
                                                            & library.made_words_all(s)) == sorted(
                    words[cs] for cs in MADE if cs in GO)
        finally:
            ledger.close()
            if ask("getActiveProfile") == "DevTest":
                with anki_connect.writer("REMAKE drill teardown", wait=60):
                    left = ask("findNotes", query=f"tag:{drill_tag}")
                    if left:
                        ask("deleteNotes", notes=left)
                    for d in ask("deckNames"):
                        if (d == deck or d.startswith(deck + "::") or d.startswith("Surasura Tidy ")) and not ask(
                                "findCards", query=f'"deck:{d}"'):
                            ask("deleteDecks", decks=[d], cardsToo=True)
                out["teardown_left"] = len(ask("findNotes", query=f"tag:{drill_tag}"))
                out["decks_left"] = [d for d in ask("deckNames") if d.startswith(deck)]
    finally:
        if a.back_to and a.back_to != "DevTest":
            write("loadProfile", name=a.back_to)
            on(a.back_to)
            out["profile_back"] = ask("getActiveProfile")
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
