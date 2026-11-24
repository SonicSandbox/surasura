"""FS-1's proof on DevTest: a flagged card Connect made gets its new sentence IN PLACE — its reviews, interval and due
kept — and its Undo puts every field back (never run by the suites; by hand, under `with-lock.sh anki`, Anki open — the
drill loads DevTest and puts the profile back at the end).

    python tests/connect/live_full_swap_drill.py --profile DevTest
    ANKI_MINER_HOME=<a throwaway home> python tests/connect/live_full_swap_drill.py --profile DevTest \
        --miner <Anki Miner 3.11+'s program> --episode "<the episode's video, without .mkv>"

- Three Lapis cards as Connect makes them (DevTest, the drill's tag, each recorded made by a job in a scratch ledger),
  their old clip and picture in Anki's media. Card A is studied twice (`answerCards`), then Suspend + Green as the
  review loop leaves it; card B the same, its sentence changed by hand; card C is the journey's ⇄ (never suspended).
- `swap_in_place` on for the drill only. Connect's look (`swap.look`, the line handed in) decides each kind: A and C in
  place, B a new card (hand edited). A's and C's write is the real one (`swap.write_in_place` through Swap's Anki, the
  field writer's replace mode, the media named by the line, the first-episode tag); `render`'s answer is handed in as
  files in its shape — this PC's Anki Miner has no `render` (it needs 3.11) — then the job's batch ends as the runner
  ends it, Backfill's ふりがな runs for real (`run_named(rewritten=)`), and the next look puts A back in reviews.
- `--miner` (FS-R): A's and C's new lines are two real lines of `--episode` (its `.mkv` and `.ja.ass`, read only) and
  the write is Connect's own step, `runner.Steps.swap_in_place`: Anki Miner's real `render` of the word on its line
  (that Anki Miner, its profile *Surasura*, the field mapping read from it), the media named by the line, then the
  write. The cards are made in that mapping's fields. Each press is timed (`render` alone, and the step whole).
  Refused without `ANKI_MINER_HOME` at a home of its own: the drill never runs Anki Miner on the learner's home.
- Read back: each card's reps, interval, due, lapses and review log unchanged; only the sentence side changed, each
  value exactly as written (refuter R14: Anki keeps what it is given); the ふりがな filled; A unsuspended, flag off;
  C never out of reviews; the tags. Then *Undo* on A and C: every field back, the old media stored again, the first-
  episode tag gone, the learner's own tag kept.

`getActiveProfile == "DevTest"` before anything and before teardown. Teardown: the drill's notes deleted and the media
it stored deleted (holding `anki-writer`), counted back to 0. The ledger, the library and the kept copies are in a
temp root (`SURASURA_TEST_ROOT`): Sonic's are never opened.
"""
import argparse
import base64
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# (the word, its card's line, the other line its new sentence is from) — real lines (tests/Test Resources/ja)
CARDS = {"A": ("約束", "明日の約束を忘れないでね。", "約束は必ず守るよ。"),
         "B": ("気配", "誰かの気配がした。", "春の気配を感じる。"),
         "C": ("溜め息", "思わず溜め息が出た。", "彼は深い溜め息をついた。")}
SIDE = ("Sentence", "SentenceFurigana", "SentenceAudio", "Picture", "MiscInfo", "Hint")
# --miner: the new line is a real one of the episode (Bocchi the Rock! 02's .ja.ass), found by these words — lines
# with no half-width characters: Anki Miner 3.13 answers not_found for a word named on a line holding any (ﾗｲﾌﾞ, ｡),
# its render and its mine alike (FS-R, 2026-11-23: kantan-fs-register.md § FS-R)
REAL = {"A": ("音楽", "音楽を聴くのが好きだ。", "好きな音楽の話"),
        "B": ("社会", "社会の勉強をした。", "社会が怖い"),
        "C": ("説明", "詳しい説明をお願いします。", "説明しよう")}


def _fold_b(text):
    """A field's text, markup out and NFKC, for comparing sentences."""
    import re
    import unicodedata
    return "".join(unicodedata.normalize("NFKC", re.sub(r"<[^>]+>", "", text or "")).split())


def media_names_in(ask, nid, mapping):
    """The media a note's clip and picture fields name now (the drill's teardown deletes them)."""
    from app.connect import sentence_audio
    have = ask("notesInfo", notes=[nid])[0]["fields"]
    return sentence_audio.media_in("".join((have.get(mapping.fields.get(r) or "") or {}).get("value") or ""
                                           for r in ("audio", "picture")))


def real_line(subtitle, wanted):
    """The cue of `subtitle` whose text holds `wanted` -> (start s, end s, its text as cues.read gives it)."""
    from app import cues
    for cue in cues.read(subtitle, "ja"):
        if wanted in cue.text:
            return cues.seconds(cue.start), cues.seconds(cue.end), cue.text
    sys.exit(f"STOP: no line of {subtitle} holds {wanted}")


def say(*parts):
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--profile", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--back-to", default="User 1", help="the profile loaded at the end (lane rules: Sonic's own)")
    ap.add_argument("--miner", help="FS-R: Anki Miner's program (3.11+): render for real")
    ap.add_argument("--episode", help="FS-R: the episode's video without .mkv (its .ja.ass beside it), read only")
    ap.add_argument("--line", nargs=3, action="append", default=[], metavar=("CARD", "WORD", "FOUND_BY"),
                    help="FS-R: card A, B or C's word and the words its new line of --episode is found by")
    a = ap.parse_args()
    if a.profile != "DevTest":
        sys.exit("REFUSED: the drill runs on the DevTest profile only")
    if a.miner:
        home = os.environ.get("ANKI_MINER_HOME") or ""
        if not home or os.path.abspath(home) == os.path.abspath(os.path.expanduser("~/.anki_miner")):
            sys.exit("REFUSED: --miner needs ANKI_MINER_HOME at a home of its own (never the learner's)")
        if not (a.episode and os.path.isfile(a.episode + ".mkv") and os.path.isfile(a.episode + ".ja.ass")):
            sys.exit("REFUSED: --miner needs --episode (its .mkv and .ja.ass)")
        CARDS.update(REAL)
        for key, word, found_by in a.line:
            CARDS[key] = (word, f"{word}のことを考えた。", found_by)
    root = tempfile.mkdtemp(prefix="fs1-full-swap-")
    os.environ["SURASURA_TEST_ROOT"] = root
    os.environ.pop("SURASURA_NO_ANKI_SYNC", None)
    sys.path.insert(0, REPO)
    from app import anki_connect
    from app.connect import fields, library, media_names, runner, sentence_audio, swap, swap_queue
    from app.connect import ledger as ledger_mod
    from app.connect.ledger import Ledger
    from modules.junban import backfill
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
        with anki_connect.writer("FS-1 full swap drill", wait=60):
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
    run = time.strftime("%Y%m%d%H%M%S")
    drill_tag = f"surasura::test-fs1-{run}"
    stored = set()
    notes = {}
    try:
        if ask("getActiveProfile") != "DevTest":
            sys.exit("REFUSED: Anki isn't on DevTest")
        if "Lapis" not in ask("modelNames"):
            sys.exit("STOP: DevTest has no Lapis note type")
        have = ask("modelFieldNames", modelName="Lapis")
        missing = [f for f in ("Expression", "ExpressionReading") + SIDE if f not in have]
        if missing:
            sys.exit(f"STOP: DevTest's Lapis has no {missing}")
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
        anki = swap.AnkiSwap(a.url)
        mapping = fields.Mapping("DevTest", "Lapis", {
            "word": "Expression", "sentence": "Sentence", "audio": "SentenceAudio", "picture": "Picture",
            "sentence_furigana": "SentenceFurigana", "source": "MiscInfo", "pitch_position": "PitchPosition"},
            "Expression", "Sentence", "MiscInfo", None, None)
        media_dir = os.path.join(root, "media")
        os.makedirs(media_dir)
        steps = None
        if a.miner:                         # Connect's own step against that Anki Miner, its mapping read from it
            from app.cli import verbs
            loaded = {"connect_enabled": True, "connect_anki_miner_path": a.miner,
                      "connect_anki_miner_profile": "Surasura", "anki_connect_url": a.url}
            steps = runner.Steps(loaded)
            got = verbs._anki_miner_setup(loaded, "ja", os.path.join(root, "setup"))
            mapping = got[2]
            out["miner"] = {"app": got[0].get("app"), "profile": got[1], "fields": dict(mapping.fields),
                            "source": mapping.source}
            out["lines"] = {k: real_line(a.episode + ".ja.ass", CARDS[k][2]) for k in CARDS}
            for k, (_start, _end, text) in out["lines"].items():
                CARDS[k] = (CARDS[k][0], CARDS[k][1], text)
        try:
            with c.store("ja") as s:
                items = s.ids("now")[:3]
            # --- the three cards as Connect makes them --------------------------------------------------------- #
            first_jobs = {}
            for n, (key, (word, line, _other)) in enumerate(CARDS.items()):
                job = ledger.queue("ja", items[n], "user", None, store_id="drill")
                old_clip, old_pic = f"sl-fs1drill{run}{key.lower()}.mp3", f"sl-fs1drill{run}{key.lower()}.webp"
                write("storeMediaFile", filename=old_clip, data=base64.b64encode(b"ID3 old " + line.encode()).decode())
                write("storeMediaFile", filename=old_pic, data=base64.b64encode(b"RIFF old " + key.encode()).decode())
                stored |= {old_clip, old_pic}
                values = {f: "" for f in have}
                values.update({"Expression": word, "Sentence": line.replace(word, f"<b>{word}</b>"),
                               "SentenceAudio": f"[sound:{old_clip}]", "Picture": f'<img src="{old_pic}">',
                               "SentenceFurigana": "AJT[いろ]の 古[ふる]い 行[ぎょう]", "Hint": "the old line's",
                               "MiscInfo": f"Drill - 0{n + 1} @ 00:01:0{n}"})
                if a.miner and mapping.source and mapping.source in have:
                    values[mapping.source] = f"Drill - 0{n + 1} @ 00:01:0{n}"     # where this Anki Miner writes it
                with anki_connect.writer("FS-1 full swap drill", wait=60):
                    nid = ask("addNote", note={"deckName": "DevTest", "modelName": "Lapis", "fields": values,
                                               "options": {"allowDuplicate": True},
                                               "tags": [drill_tag, f"surasura::connect::{ledger.tag_id(job)}",
                                                        "my_own"]})
                    ask("updateNoteFields", note={"id": nid, "fields": values})    # as written (AJT fills on add)
                ledger.end_batch(job, 1, "done", [{"word": word, "reading": "", "outcome": "made", "note_id": nid,
                                                   "sentence": line}], deck="DevTest")
                ledger.set_state(job, "done")
                notes[key], first_jobs[key] = nid, job
            cards = {k: ask("findCards", query=f"nid:{v}")[0] for k, v in notes.items()}
            try:
                answered = write("answerCards", answers=[{"cardId": cards["A"], "ease": 3}])
                time.sleep(1.1)
                answered += write("answerCards", answers=[{"cardId": cards["A"], "ease": 3}])
            except anki_connect.AnkiError as e:
                answered = f"answerCards: {e}"
            out["studied_A"] = answered
            for key in ("A", "B"):
                write("suspend", cards=[cards[key]])
                with anki_connect.writer("FS-1 full swap drill", wait=60):
                    anki.set_flag([cards[key]], swap.GREEN)
                swap_queue.add("ja", CARDS[key][0], cards[key], notes[key], f"drill-{run}-{key}")
            b_now = f"廊下の奥で誰かの<b>{CARDS['B'][0]}</b>を感じた。"              # the learner rewrote the line
            write("updateNoteFields", note={"id": notes["B"], "fields": {"Sentence": b_now}})       # a hand edit
            swap.make_card("ja", CARDS["C"][0], old_note=notes["C"], old_card=cards["C"], by=swap.BY_JOURNEY,
                           ledger=ledger, wake=False, state_of=lambda w, r: None)
            before_cards = {i["cardId"]: i for i in ask("cardsInfo", cards=list(cards.values()))}
            before_log = {str(k): len(v) for k, v in
                          (write("getReviewsOfCards", cards=[str(x) for x in cards.values()]) or {}).items()}
            before_notes = {n["noteId"]: n for n in ask("notesInfo", notes=list(notes.values()))}
            # --- the look: each swap's kind (the setting on for the drill only) --------------------------------- #
            picks = {CARDS[k][0]: (items[(i + 1) % 3], CARDS[k][2]) for i, k in enumerate(CARDS)}
            real_choose, real_on = swap.choose_line, swap.in_place_on
            swap.choose_line = lambda language, word, *a_, **k: picks[word]
            swap.in_place_on = lambda settings=None: True
            try:
                t_look = time.perf_counter()
                out["look_1"] = swap.look(Steps(), ledger, "ja", anki=anki, files=5)
                out["look_1_s"] = round(time.perf_counter() - t_look, 2)
            finally:
                swap.choose_line = real_choose
            rows = {r["word"]: r for r in swap._rows(ledger, "language = 'ja'")}
            out["kinds"] = {k: (rows[CARDS[k][0]]["kind"], rows[CARDS[k][0]]["kind_why"]) for k in CARDS}
            out["C_after_look_queue"] = ask("cardsInfo", cards=[cards["C"]])[0]["queue"]
            # --- the in-place writes (render's answer handed in), the batch's end, Backfill, the next look ------ #
            timed = {}

            def finish(key, word, other, row):      # the job's batch ends as the runner ends it, then Backfill
                job = ledger.job_by_id(row["job_id"])
                t1 = time.perf_counter()
                ledger.end_batch(job["id"], 1, "done", [{"word": word, "reading": "", "outcome": "made",
                                                         "note_id": notes[key], "sentence": other}], deck="DevTest")
                runner._record_made(runner.Steps({}), ledger, "ja", job, True)
                base = {"target_language": "ja", "junban_url": a.url, "junban_chunk_size": 150,
                        "junban_backfill_fills": ["patterns"], "junban_backfill_deck": "DevTest::elsewhere"}
                session = backfill.Session(base)
                try:
                    got = backfill.run_named(base, session, [notes[key]], run_id=f"backfill-{run}-00{key == 'C'}",
                                             verb="FS-1 drill", rewritten=swap.rewritten(ledger, job["id"]))
                finally:
                    session.close()
                out[f"backfill_{key}"] = {k: got.get(k) for k in ("ok", "filled", "skipped")}
                out[f"after_write_s_{key}"] = round(time.perf_counter() - t1, 2)
                ledger.set_state(job["id"], "done")

            renders = []
            if a.miner:
                from app.connect import anki_miner
                real_render = anki_miner.render_line

                def timed_render(*args, **kwargs):  # timed, its answer kept for the read-back
                    t = time.perf_counter()
                    answer = real_render(*args, **kwargs)
                    renders.append({"s": round(time.perf_counter() - t, 2), "answer": answer})
                    return answer
                anki_miner.render_line = timed_render
            for key in ("A", "C"):
                word, _line, other = CARDS[key]
                row = swap.in_place_row(ledger, rows[word]["job_id"])
                if row is None:
                    out[f"write_{key}"] = "not in place"
                    continue
                if a.miner:
                    start, end, text = out["lines"][key]
                    picked = {"video": a.episode + ".mkv", "subtitle": a.episode + ".ja.ass", "offset": 0.0}
                    words = [{"word": word, "reading": "", "sent": [word], "line_start": start, "line_end": end,
                              "line_text": text, "line_expansion": [0, 0]}]
                    job = ledger.job_by_id(row["job_id"])
                    t0 = time.perf_counter()
                    for tries in range(1, 41):      # Anki's media sync after the profile loads: the job waits
                        renders.clear()
                        try:
                            done = steps.swap_in_place("ja", job, picked, words, 1, ledger, row)
                            break
                        except runner.Wait as e:
                            if tries == 40:
                                raise
                            out.setdefault(f"waits_{key}", []).append(str(e.reason)[:160])
                            time.sleep(5)
                            t0 = time.perf_counter()
                            row = swap.in_place_row(ledger, rows[word]["job_id"]) or row
                    timed[key] = round(time.perf_counter() - t0, 2)
                    out[f"write_{key}_tries"] = tries
                    out[f"render_{key}"] = {
                        "s": [r["s"] for r in renders],
                        "fields": {f: v for r in renders for one in r["answer"].values()
                                   for f, v in one["fields"].items()},
                        "files": [os.path.basename(f) for r in renders for one in r["answer"].values()
                                  for f in one["files"]]}
                    if done is None:
                        out[f"write_{key}"] = ("fell back", swap._rows(ledger, "id = ?", (row["id"],))[0]["kind_why"])
                        continue
                    out[f"write_{key}"] = (swap.IN_PLACE if done.get("in_place") else None,
                                           done["outcomes"][0]["note_id"] == notes[key], None)
                    stored |= set(media_names_in(ask, notes[key], mapping))
                    finish(key, word, other, row)
                    continue
                clip, pic = os.path.join(media_dir, f"{word}_1_1.mp3"), os.path.join(media_dir, f"{word}_1_1.webp")
                with open(clip, "wb") as f:
                    f.write(b"ID3 new " + other.encode())
                with open(pic, "wb") as f:
                    f.write(b"RIFF new " + key.encode())
                rendered = {"Expression": word + "（別）", "Sentence": other.replace(word, f"<b>{word}</b>"),
                            "SentenceAudio": f"[sound:{os.path.basename(clip)}]",
                            "Picture": f'<img src="{os.path.basename(pic)}">', "SentenceFurigana": "",
                            "MiscInfo": f"Drill - 05 @ 00:03:1{key == 'C'}", "Hint": ""}
                values, named = media_names.by_line(rendered, {os.path.basename(p): p for p in (clip, pic)},
                                                    f"drill-{run}-{key}", 190.0, 192.5, other, "SentenceAudio",
                                                    "Picture")
                stored |= set(named)
                learned = swap.learned_tag(ledger, notes[key], lambda: library.open_store("ja"))
                t0 = time.perf_counter()
                for tries in range(1, 41):  # Anki's media sync after the profile loads refuses media: the app's
                    try:                    # job waits and its next look tries again — so does the drill
                        kind, said = swap.write_in_place(anki, ledger, row, {"fields": values, "files": [clip, pic],
                                                                             "named": named},
                                                         mapping, swap.kept_folder(), learned=learned)
                        break
                    except anki_connect.AnkiError as e:
                        if "syncing" not in str(e) or tries == 40:
                            raise
                        time.sleep(5)
                        row = swap.in_place_row(ledger, rows[word]["job_id"])   # its record named: settled first
                out[f"write_{key}_tries"] = tries
                timed[key] = round(time.perf_counter() - t0, 2)
                out[f"write_{key}"] = (kind, said == notes[key], learned)
                finish(key, word, other, row)
            if a.miner:                         # B, hand edited: the simple Swap's new card, made for real, timed
                word, _line, other = CARDS["B"]
                start, end, text = out["lines"]["B"]
                job = ledger.job_by_id(rows[word]["job_id"])
                picked = {"video": a.episode + ".mkv", "subtitle": a.episode + ".ja.ass", "offset": 0.0}
                words = [{"word": word, "reading": "", "sent": [word], "line_start": start, "line_end": end,
                          "line_text": text, "line_expansion": [0, 0]}]
                t0 = time.perf_counter()
                for tries in range(1, 41):
                    try:
                        # AM-FIX: the batch's own step (`runner._mine_batch`): B's old card is a Lapis note of its
                        # word, so a bare `mine` is refused as its duplicate (FS-R) — Swap makes it beside the old one
                        done = runner._mine_batch(steps, ledger, "ja", job, picked, words, 1)
                        break
                    except runner.Wait as e:
                        if tries == 40:
                            raise
                        out.setdefault("waits_B", []).append(str(e.reason)[:160])
                        time.sleep(5)
                        t0 = time.perf_counter()
                timed["B_simple"] = round(time.perf_counter() - t0, 2)
                got_b = (done.get("outcomes") or [{}])[0]
                out["simple_B"] = {k: got_b.get(k) for k in ("outcome", "note_id", "mined_form", "filter")}
                if got_b.get("note_id"):
                    write("addTags", notes=[int(got_b["note_id"])], tags=drill_tag)     # torn down with the drill's
                    stored |= set(media_names_in(ask, int(got_b["note_id"]), mapping))
                    new_b = ask("notesInfo", notes=[int(got_b["note_id"])])[0]
                    old_b = ask("notesInfo", notes=[notes["B"]])[0]
                    nf, of = ({f: v["value"] for f, v in n["fields"].items()} for n in (new_b, old_b))
                    sent = mapping.fields.get("sentence") or "Sentence"
                    media = media_names_in(ask, int(got_b["note_id"]), mapping)
                    out["new_B"] = {
                        "a_new_note": int(got_b["note_id"]) != notes["B"],
                        "word_side_the_old_cards": all(nf[f] == of[f] for f in ("Expression", "MainDefinition",
                                                                              "Glossary") if f in nf),
                        "sentence_the_new_line": _fold_b(nf.get(sent)) != _fold_b(of.get(sent)) and
                        _fold_b(word) in _fold_b(nf.get(sent)), "sentence": nf.get(sent),
                        "media_in_anki": {m: bool(write("retrieveMediaFile", filename=m)) for m in media},
                        "job_tag": f"surasura::connect::{runner._tag(job)}".lower() in
                        {x.lower() for x in new_b["tags"]},
                        "deck": ask("getDecks", cards=ask("findCards", query=f"nid:{got_b['note_id']}")),
                        "sentence_furigana": nf.get("SentenceFurigana")}
            out["write_seconds"] = timed
            time.sleep(1.5)
            try:
                out["look_2"] = swap.look(Steps(), ledger, "ja", anki=anki, files=5)
            finally:
                swap.in_place_on = real_on
            rows = {r["word"]: r for r in swap._rows(ledger, "language = 'ja'")}
            # --- read back ---------------------------------------------------------------------------------- #
            after_cards = {i["cardId"]: i for i in ask("cardsInfo", cards=list(cards.values()))}
            after_log = {str(k): len(v) for k, v in
                         (write("getReviewsOfCards", cards=[str(x) for x in cards.values()]) or {}).items()}
            after_notes = {n["noteId"]: n for n in ask("notesInfo", notes=list(notes.values()))}
            keep = ("reps", "interval", "due", "lapses", "type", "factor")
            for key in ("A", "C"):
                cid, nid = cards[key], notes[key]
                rec = sentence_audio.record(ledger, rows[CARDS[key][0]]["wrote"]) if rows[CARDS[key][0]].get(
                    "wrote") else {}
                wrote = (rec.get("notes") or {}).get(str(nid)) or {}
                old_v = {f: v["value"] for f, v in before_notes[nid]["fields"].items()}
                new_v = {f: v["value"] for f, v in after_notes[nid]["fields"].items()}
                out[key] = {
                    "schedule_kept": {k: before_cards[cid].get(k) == after_cards[cid].get(k) for k in keep},
                    "reps": after_cards[cid].get("reps"),
                    "review_log_kept": before_log.get(str(cid)) == after_log.get(str(cid)),
                    "queue": after_cards[cid]["queue"], "flag": after_cards[cid].get("flags"),
                    "changed": sorted(f for f in new_v if new_v[f] != old_v[f]),
                    "as_written": all(new_v.get(f) == v for f, v in wrote.items() if f != "SentenceFurigana"),
                    "furigana": new_v.get("SentenceFurigana"), "on_line_names": [
                        v for v in (new_v["SentenceAudio"], new_v["Picture"]) if "sl-" in v],
                    "tags": sorted(after_notes[nid]["tags"]), "row": rows[CARDS[key][0]]["state"]}
            out["B_note_unchanged"] = {f: v["value"] for f, v in after_notes[notes["B"]]["fields"].items()} == \
                {f: v["value"] for f, v in before_notes[notes["B"]]["fields"].items()}
            # --- Undo, as *Needs you* presses it -------------------------------------------------------------- #
            for key in ("A", "C"):
                row = rows[CARDS[key][0]]
                try:
                    out[f"undo_{key}"] = swap.undo(anki, ledger, "ja", row["id"],
                                                   open_store=lambda: library.open_store("ja"))
                except Exception as e:      # a refusal says why
                    out[f"undo_{key}"] = f"{type(e).__name__}: {getattr(e, 'say', e)}"
            undone = {n["noteId"]: n for n in ask("notesInfo", notes=[notes["A"], notes["C"]])}
            for key in ("A", "C"):
                nid = notes[key]
                old_v = {f: v["value"] for f, v in before_notes[nid]["fields"].items()}
                now_v = {f: v["value"] for f, v in undone[nid]["fields"].items()}
                out[f"after_undo_{key}"] = {
                    "every_field_back": now_v == old_v,
                    "differs": {f: (old_v[f], now_v[f]) for f in sorted(now_v) if now_v[f] != old_v[f]},
                    "tags": sorted(undone[nid]["tags"]),
                    "old_media_back": [bool(write("retrieveMediaFile", filename=m)) for m in
                                       sentence_audio.media_in(old_v["SentenceAudio"] + old_v["Picture"])]}
            out["after_undo_cards"] = {k: (i["queue"], i.get("reps")) for k, i in
                                       ((k, ask("cardsInfo", cards=[cards[k]])[0]) for k in ("A", "C"))}
        finally:
            ledger.close()
    finally:
        try:
            if ask("getActiveProfile") == "DevTest":
                with anki_connect.writer("FS-1 full swap drill teardown", wait=60):
                    left = ask("findNotes", query="tag:surasura::test-fs1-*")      # this run's and any earlier one's
                    if left:
                        ask("deleteNotes", notes=left)
                    for tries in range(40):
                        try:
                            for name in sorted(stored | set(ask("getMediaFilesNames", pattern="sl-fs1drill*"))):
                                ask("deleteMediaFile", filename=name)
                            break
                        except anki_connect.AnkiError as e:
                            if "syncing" not in str(e):
                                raise
                            time.sleep(5)
                    out["media_left"] = [m for m in sorted(stored) if ask("retrieveMediaFile", filename=m)] + \
                        ask("getMediaFilesNames", pattern="sl-fs1drill*")
                out["teardown_left"] = len(ask("findNotes", query="tag:surasura::test-fs1-*"))
        finally:
            if a.back_to and a.back_to != "DevTest":
                write("loadProfile", name=a.back_to)
                on(a.back_to)
                out["profile_back"] = ask("getActiveProfile")
            print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
