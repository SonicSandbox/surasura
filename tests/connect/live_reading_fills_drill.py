"""Kantan-PF's proof on DevTest: ふりがな and アクセント fill a card's empty SentenceFurigana / PitchPosition — through
Connect's fill of the cards it makes (`backfill.run_named`) and through Backfill's own run (`backfill.run`) — and touch
nothing else. Never run by the suites; by hand, under `locks/with-lock.sh anki …`, with Anki open.

    python tests/connect/live_reading_fills_drill.py --profile DevTest

1. Read (only) the learner's cards in User 1 whose shape it copies: the 13 of batches 36f67c74-245…249 with an empty
   SentenceFurigana, a few with no PitchPosition, and two with AJT's furigana and pitch (the controls). User 1 is
   never written.
2. Load DevTest; add the copies to deck `DevTest::kantan-pf` (tag `surasura::test-kantan-pf-<run>`), then set each
   field exactly as the original holds it (AJT fills on add when Anki isn't in front: the copy is made empty again).
3. Connect's run (Backfill's ticks at their default, its deck another one): every empty SentenceFurigana filled, a
   one-word card's empty PitchPosition filled, a phrase's left empty, the controls and every other field unchanged;
   run again: nothing to fill; its Restore: the fields empty again.
4. Backfill's own run on the deck (ふりがな + アクセント ticked): the same fills; its Restore.
5. Teardown: the run's notes deleted and counted back to 0; User 1 loaded back (`getActiveProfile`).
"""
import argparse
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORTED_BATCHES = "tag:Surasura::connect::36f67c74-245 OR tag:Surasura::connect::36f67c74-246 OR " \
                   "tag:Surasura::connect::36f67c74-247 OR tag:Surasura::connect::36f67c74-248 OR " \
                   "tag:Surasura::connect::36f67c74-249"
PITCHLESS = ("分かり合う", "魔族", "砕け散る", "滅び", "気にしない", "一緒に")
CONTROLS = (1794251555175, 1794251285817)       # どうかした, 口調: AJT's furigana and pitch on them
DECK = "DevTest::kantan-pf"
HOME = "User 1"


def say(*parts):
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--profile", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    a = ap.parse_args()
    if a.profile != "DevTest":
        sys.exit("REFUSED: the drill writes on the DevTest profile only")
    sys.stdout.reconfigure(encoding="utf-8")
    root = tempfile.mkdtemp(prefix="kantan-pf-drill-")
    os.environ["SURASURA_TEST_ROOT"] = root
    os.environ.pop("SURASURA_NO_ANKI_SYNC", None)
    sys.path.insert(0, REPO)
    from app import anki_connect

    def ask(action, **params):
        return anki_connect.invoke(action, a.url, timeout=120, **params)

    def profile():
        return ask("getActiveProfile")

    out = {"run": time.strftime("%Y%m%d-%H%M%S")}
    tag = f"surasura::test-kantan-pf-{out['run']}"
    if ask("guiReviewActive") is True:
        sys.exit("REFUSED: a review is on screen in Anki: the drill never switches profile under it")
    if profile() != HOME:
        sys.exit(f"REFUSED: Anki is on {profile()!r}, not {HOME!r}: the copies are read from {HOME!r}")
    # 1. read only
    ids = ask("findNotes", query=f"({REPORTED_BATCHES}) SentenceFurigana:")
    for word in PITCHLESS:
        ids += ask("findNotes", query=f'tag:Surasura::connect::* "Expression:{word}" PitchPosition:')[:1]
    ids += list(CONTROLS)
    originals = [n for n in ask("notesInfo", notes=ids) if n.get("noteId")]
    say(f"read {len(originals)} notes of {HOME} (read only)")
    try:
        with anki_connect.writer("Kantan-PF drill: DevTest", wait=60):
            ask("loadProfile", name=a.profile)
        time.sleep(3)
        if profile() != "DevTest":
            sys.exit("REFUSED: DevTest didn't load")
        if "Lapis" not in ask("modelNames"):
            sys.exit("STOP: DevTest has no Lapis note type")
        out.update(_drill(ask, profile, originals, tag, root))
    finally:
        with anki_connect.writer("Kantan-PF drill: teardown", wait=60):
            _teardown(ask, profile, tag, out)
            ask("loadProfile", name=HOME)
        time.sleep(3)
        out["profile_after"] = profile()
    print(json.dumps(out, ensure_ascii=False, indent=1))
    ok = out.get("ok") and out.get("teardown_left") == 0 and out["profile_after"] == HOME
    sys.exit(0 if ok else 1)


def _values(note):
    return {name: field["value"] for name, field in note["fields"].items()}


def _drill(ask, profile, originals, tag, root):
    from app import anki_connect
    copies = {}
    with anki_connect.writer("Kantan-PF drill: copies", wait=60):
        _copy(ask, profile, originals, tag, copies)
    now = {n["noteId"]: _values(n) for n in ask("notesInfo", notes=list(copies))}
    assert now == copies, "the copies aren't the originals' shape"
    say(f"copied {len(copies)} notes into {DECK}")
    return _fills(ask, profile, copies, root)


def _copy(ask, profile, originals, tag, copies):
    ask("createDeck", deck=DECK)
    for note in originals:
        values = _values(note)
        added = ask("addNote", note={"deckName": DECK, "modelName": "Lapis", "fields": values, "tags": [tag],
                                     "options": {"allowDuplicate": True}})
        assert profile() == "DevTest"
        ask("updateNoteFields", note={"id": added, "fields": values})       # empty again where AJT filled it on add
        copies[added] = values


def _fills(ask, profile, copies, root):
    from app import analyzer
    from modules.junban import backfill, readings
    tagger = analyzer.JapaneseTokenizer().tagger
    expect = {}
    for nid, values in copies.items():
        want = {}
        if not values["SentenceFurigana"].strip():
            want["SentenceFurigana"] = readings.sentence_furigana(values["Sentence"], tagger)
        if not values["PitchPosition"].strip():
            from modules.junban.match import normalize_word
            accent, _why = readings.pitch(values["Expression"], normalize_word(values["ExpressionReading"]), tagger)
            if accent:
                want["PitchPosition"] = accent
        expect[nid] = want
    result = {"copies": len(copies), "furigana_expected": sum("SentenceFurigana" in w for w in expect.values()),
              "pitch_expected": sum("PitchPosition" in w for w in expect.values())}
    base = {"target_language": "ja", "junban_url": "http://127.0.0.1:8765", "junban_chunk_size": 150,
            "junban_backfill_fills": ["patterns"], "junban_backfill_deck": "DevTest::elsewhere"}

    def check(label):
        got = {n["noteId"]: _values(n) for n in ask("notesInfo", notes=list(copies))}
        bad = []
        for nid, values in copies.items():
            for field, before in values.items():
                after = got[nid][field]
                if after != expect[nid].get(field, before):
                    bad.append((nid, field, before[:30], after[:60]))
        result[label] = "ok" if not bad else bad[:6]
        return not bad

    session = backfill.Session(base)
    try:
        assert profile() == "DevTest"
        report = backfill.run_named(base, session, list(copies), run_id="backfill-20261121-130000-000",
                                    verb="Kantan-PF drill")
        result["connect_run"] = {k: report.get(k) for k in ("ok", "message", "skipped", "planned")}
        filled = check("connect_fill")
        again = backfill.run_named(base, session, list(copies), run_id="backfill-20261121-130001-000",
                                   verb="Kantan-PF drill")
        result["connect_again"] = again.get("message")
        back = backfill.restore_run(base, "backfill-20261121-130000-000")
        result["connect_restore"] = back.get("message")
        got = {n["noteId"]: _values(n) for n in ask("notesInfo", notes=list(copies))}
        result["connect_restored"] = got == copies
        # 4. Backfill's own run on the deck, ふりがな + アクセント ticked
        own = dict(base, junban_backfill_fills=["furigana", "pitch"], junban_backfill_deck=DECK,
                   junban_backfill_cards="all")
        assert profile() == "DevTest"
        planned = backfill.preview(own, session)
        result["own_preview"] = {"counts": planned.get("counts"), "edits": len(planned.get("edits") or {})}
        ran = backfill.run(own, session, planned=planned, wait=10.0, verb="Kantan-PF drill")
        result["own_run"] = {k: ran.get(k) for k in ("ok", "message")} if isinstance(ran, dict) else str(ran)[:200]
        own_ok = check("own_fill")
        undone = backfill.restore(own, wait=10.0)
        result["own_restore"] = {k: undone.get(k) for k in ("ok", "message")} if isinstance(undone, dict) else None
        got = {n["noteId"]: _values(n) for n in ask("notesInfo", notes=list(copies))}
        result["own_restored"] = got == copies
    finally:
        session.close()
    result["ok"] = bool(filled and own_ok and result["connect_restored"] and result["own_restored"]
                        and result["connect_again"] == "Nothing to fill.")
    result["root"] = root
    return result


def _teardown(ask, profile, tag, out):
    if profile() != "DevTest":
        out["teardown_left"] = "NOT CHECKED: Anki left DevTest"
        return
    ids = ask("findNotes", query=f'"tag:{tag}"')
    if ids:
        ask("deleteNotes", notes=ids)
    out["teardown_left"] = len(ask("findNotes", query=f'"tag:{tag}"'))
    if not ask("findCards", query=f'"deck:{DECK}"'):
        ask("deleteDecks", decks=[DECK], cardsToo=True)


if __name__ == "__main__":
    main()
