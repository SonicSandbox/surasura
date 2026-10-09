"""P2.4's probes (row 2.4.0; P1.5 07-tests §3), ahead of what they de-risk: run by hand, never by the suites.

    locks/anki.lock taken by hand (board lines), then:
    python tests/connect/live_probes.py --profile DevTest --steps profile,review,tag [--url http://127.0.0.1:8765]

- `profile`: `getActiveProfile` answers on this AnkiConnect (E3), and AnkiConnect's own `version`.
- `review` (K88, E2): `guiReviewActive` is False in the deck list and in the browser, True in the review screen
  (`guiDeckReview` on deck DevTest, a test note added first when the deck has no card to show), and Connect's own
  guard (`runner.Steps.blocked`) answers *Waiting while you review* there; back to the deck list after.
- `tag` (Part B, 2.4.14's premise): a note made with a test job's tag is found by `findNotes "tag:…"`, deleted (as a
  person deletes it), and then found no more — `findNotes` answers ids of notes still in Anki only.
- E8 (Anki Miner open → `BUSY`) is answered from Anki Miner 3.7.0's own source, not here: it reports the feature
  `beside-window` — `--api mine` runs beside an open window and answers `BUSY` only while that window is mining or
  another run holds its run lock (`anki_miner/cli/entry.py` `acquire_run_lock`); `version` is never locked (checked
  live through the guard, 2026-10-08: it answered with its window up or not).

`getActiveProfile == "DevTest"` is asked before any Anki step and before every write: anything else stops it. Every note
it adds carries `surasura::connect::test-p24probe-<time>` and is deleted; the count is checked back to 0.
"""
import argparse
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def say(*parts):
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--profile", default=None)
    ap.add_argument("--steps", default="profile,review,tag")
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--deck", default="DevTest")
    a = ap.parse_args()
    sys.path.insert(0, REPO)
    steps = [s.strip() for s in a.steps.split(",") if s.strip()]
    out = {}
    anki_steps = steps
    if anki_steps and a.profile != "DevTest":
        sys.exit("REFUSED: the Anki probes run on the DevTest profile only")
    from app import anki_connect

    def ask(action, **params):
        return anki_connect.invoke(action, a.url, timeout=10, **params)

    def devtest():
        try:
            return ask("getActiveProfile") == "DevTest"
        except anki_connect.AnkiError:
            return False

    if anki_steps and not devtest():
        sys.exit("REFUSED: Anki isn't open on DevTest")
    held = anki_connect.writer("P2.4 probes", wait=30)       # the GUI actions and the test notes write Anki
    held.__enter__()
    tag = "surasura::connect::test-p24probe-" + time.strftime("%Y%m%d%H%M%S")

    if "profile" in steps:
        out["profile"] = {"getActiveProfile": ask("getActiveProfile"), "ankiconnect_version": ask("version")}
        say("profile", out["profile"])

    if "review" in steps:
        made = []
        try:
            ask("guiDeckBrowser")
            time.sleep(1.0)
            deck_list = ask("guiReviewActive")
            ask("guiBrowse", query=f'deck:"{a.deck}"')
            time.sleep(1.0)
            browser = ask("guiReviewActive")
            ask("guiDeckBrowser")
            if not devtest():
                sys.exit("STOPPED: the profile changed")
            if not ask("findCards", query=f'deck:"{a.deck}" (is:new OR is:due)'):
                made.append(_test_note(ask, a.deck, tag, "一生懸命"))
            ask("guiDeckReview", name=a.deck)
            time.sleep(1.5)
            reviewing = ask("guiReviewActive")
            from app.connect import runner
            guard = runner.Steps({"connect_enabled": True, "anki_connect_url": a.url}).blocked("ja") \
                if not os.environ.get("SURASURA_NO_ANKI_SYNC") else None
            out["review"] = {"deck_list": deck_list, "browser": browser, "review_screen": reviewing,
                             "connect_guard": guard if isinstance(guard, str) else repr(guard)}
            say("review", out["review"])
        finally:
            ask("guiDeckBrowser")
            if made and devtest():
                ask("deleteNotes", notes=made)
            left = ask("findNotes", query=f'"tag:{tag}"') if made else []
            out.setdefault("review", {})["left"] = len(left)

    if "tag" in steps:
        if not devtest():
            sys.exit("STOPPED: the profile changed")
        note = _test_note(ask, a.deck, tag, "気配")
        found = ask("findNotes", query=f'"tag:{tag}"')
        ask("deleteNotes", notes=[note])
        after = ask("findNotes", query=f'"tag:{tag}"')
        by_id = ask("findNotes", query=f"nid:{note}")
        out["tag"] = {"before_delete": found, "after_delete": after, "by_nid_after": by_id}
        say("tag", out["tag"])

    held.__exit__(None, None, None)
    print(json.dumps(out, ensure_ascii=False, indent=1))


def _test_note(ask, deck, tag, word):
    """A Basic test note in the deck, carrying the probe's tag -> its id."""
    models = ask("modelNames")
    model = "Basic" if "Basic" in models else models[0]
    fields = ask("modelFieldNames", modelName=model)
    note = {"deckName": deck, "modelName": model, "fields": {fields[0]: word, fields[1]: "probe"},
            "tags": [tag], "options": {"allowDuplicate": True}}
    return ask("addNote", note=note)


if __name__ == "__main__":
    main()
