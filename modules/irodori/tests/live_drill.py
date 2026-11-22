# SPDX-License-Identifier: GPL-3.0-or-later
"""A by-hand proof on a test Anki profile named DevTest: the AI voice, for real, through the shared writer, into real
Lapis notes. Never run by the suites; by hand, with nothing else writing to Anki, Anki open on DevTest, and an
installed runtime:

    SURASURA_IRODORI_HOME=<an installed runtime> python modules/irodori/tests/live_drill.py --profile DevTest

- Three Lapis notes in deck DevTest, the drill's own tag on each: (a) a real sentence, SentenceAudio empty; (b) a
  recorded clip in SentenceAudio (a media file the drill stores first, as an anime card's); (c) text in SentenceAudio.
- `make.make_for_notes` on the three: the count, then the real voice (its own loopback server, the CPU), the clip
  written through the shared writer (`writer.fill` → `app/connect/sentence_audio.fill`).
- Undo (`irodori.undo` → the writer's `undo`).

Passes when: only (a) is asked of the voice and filled (`[sound:surasura-sa-…]`, the tag `surasura::ai-audio`, its
clip in Anki's media); (b) and (c) are byte-for-byte as they were, untagged; after Undo (a) is empty again, untagged,
its clip gone from Anki's media, (b) and (c) still untouched. `getActiveProfile == "DevTest"` before anything and
before the teardown. Teardown: the drill's notes and media deleted and counted back to 0. The learner's own ledger
and data are never opened (a temp SURASURA_TEST_ROOT).
"""
import argparse
import base64
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SENTENCES = ["駅前の新しいパン屋に、一緒に行ってみない？", "冒険の準備はできていますか？", "或春の日暮です。"]


def say(*parts):
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--profile", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--deck", default="DevTest")
    a = ap.parse_args()
    if a.profile != "DevTest" or a.deck != "DevTest":
        sys.exit("REFUSED: the drill runs on the DevTest profile and deck only")
    if not os.environ.get("SURASURA_IRODORI_HOME"):
        sys.exit("REFUSED: set SURASURA_IRODORI_HOME to an installed runtime")
    os.environ["SURASURA_TEST_ROOT"] = tempfile.mkdtemp(prefix="iro-drill-")
    sys.path.insert(0, REPO)
    from app import anki_connect
    import modules.irodori as irodori
    from modules.irodori import make, runtime, writer

    def ask(action, **params):
        return anki_connect.invoke(action, a.url, timeout=120, **params)

    def devtest():
        try:
            return ask("getActiveProfile") == "DevTest"
        except anki_connect.AnkiError:
            return False

    def media(pattern):
        with anki_connect.writer("AI voice drill (media look)", wait=60):      # not on the client's read list
            return ask("getMediaFilesNames", pattern=pattern)

    def fields(ids):        # tags lower-cased: Anki keeps a tag's case as it first met it (Surasura::…)
        return {n["noteId"]: (n["fields"]["SentenceAudio"]["value"], sorted(t.lower() for t in n["tags"]))
                for n in ask("notesInfo", notes=ids)}

    if not devtest():
        sys.exit("REFUSED: Anki isn't open on DevTest")
    if not runtime.ready() or not writer.available():
        sys.exit("REFUSED: the runtime isn't installed, or the shared writer isn't in this tree")
    run = time.strftime("%Y%m%d%H%M%S")
    tag = f"surasura::test-iro-drill-{run}".lower()
    recorded = f"surasura-iro-drill-{run}-recorded.mp3"
    out = {"tag": tag}
    ids = []
    try:
        with anki_connect.writer("AI voice drill (setup)", wait=60):
            ask("storeMediaFile", filename=recorded, data=base64.b64encode(b"ID3 drill recorded clip").decode())
            notes = [{"deckName": a.deck, "modelName": "Lapis", "options": {"allowDuplicate": True}, "tags": [tag],
                      "fields": {"Expression": w, "Sentence": s, "SentenceAudio": audio}}
                     for w, s, audio in (("パン屋", SENTENCES[0], ""), ("準備", SENTENCES[1], f"[sound:{recorded}]"),
                                         ("日暮", SENTENCES[2], "ナレーターの声"))]
            ids = ask("addNotes", notes=notes)
        before = fields(ids)
        say("notes", ids, before)
        settings = {"enable_irodori": True}
        count = make.make_for_notes(settings, "ja", ids, dry_run=True)
        out["count"] = make.count_line(count)
        say("count:", out["count"])
        t0 = time.time()
        report = make.make_for_notes(settings, "ja", ids, source="drill")
        out["seconds"] = round(time.time() - t0, 1)
        out["report"] = {k: report[k] for k in ("ok", "message", "problems", "todo", "made", "written", "run")}
        after = fields(ids)
        out["after"] = after
        names = media("surasura-sa-*")
        filled = after[ids[0]][0]
        clip = filled[len("[sound:"):-1] if filled.startswith("[sound:") else None
        out["clip_in_media"] = clip in names
        say("made", out["report"], f"{out['seconds']} s", after)
        undone = irodori.undo(settings, "ja", report["run"])
        out["undo"] = {k: undone.get(k) for k in ("ok", "message", "problems", "written")}
        after_undo = fields(ids)
        out["after_undo"] = after_undo
        out["clip_after_undo"] = clip in media("surasura-sa-*")
        say("undone", out["undo"], after_undo)
        out["passed"] = (count["todo"] == 1 and report["ok"] and report["written"] == [ids[0]]
                         and filled.startswith("[sound:surasura-sa-") and writer.AI_TAG in after[ids[0]][1]
                         and after[ids[1]] == before[ids[1]] and after[ids[2]] == before[ids[2]]
                         and out["clip_in_media"]
                         and undone["ok"] and after_undo[ids[0]] == ("", [tag])
                         and after_undo[ids[1]] == before[ids[1]] and after_undo[ids[2]] == before[ids[2]]
                         and not out["clip_after_undo"])
    finally:
        if devtest() and ids:
            with anki_connect.writer("AI voice drill (teardown)", wait=60):
                ask("deleteNotes", notes=ask("findNotes", query=f'"tag:{tag}"'))
                ask("deleteMediaFile", filename=recorded)
            out["left"] = len(ask("findNotes", query=f'"tag:{tag}"'))
            out["recorded_left"] = recorded in media("surasura-iro-drill-*")
        print(json.dumps(out, ensure_ascii=False, indent=1))
        print("PASS" if out.get("passed") and out.get("left") == 0 and not out.get("recorded_left") else "FAIL")


if __name__ == "__main__":
    main()
