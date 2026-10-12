"""P2.3's proof run (row 2.3.9): Connect's setup checks, its session sync and *Open Anki for me* against the real Anki,
on the DevTest profile only. Never run by the suites; run by hand, holding Anki's machine lock (DevTest: Sonic's
standing go, 2026-10-07):

    locks/with-lock.sh --max 20 anki "Michi (pipeline) · P2.3" "<Anki: DevTest>" "2.3.9 drill" -- \\
        python tests/connect/live_session_drill.py --profile DevTest [--anki-miner <am.py guard>] \\
            [--steps setup,session,open] [--anki <Anki.exe>]

- `setup`: `app/connect/setup.py`'s checks, Anki asked read-only, Anki Miner through the guard given (a test copy's
  own home: never the user's), Anki's profile recorded as Connect's.
- `session`: `anki_session.begin` twice — one real AnkiWeb sync on DevTest's throwaway account, then none (one sync a
  session).
- `open`: Anki closed through AnkiConnect (`guiExitAnki`: its own sync on close runs), then the window's first look
  (`anki_session.at_window(opening=True)`) with *Open Anki for me* on starts it on DevTest (`-p DevTest`), waits for
  AnkiConnect, and syncs the new session. Anki is left open on DevTest, as found.

`getActiveProfile == "DevTest"` is asked before anything, and again before every write or sync: anything else stops the
drill. Surasura's side runs in a scratch test root (its sync state and setup record live there): nobody's data.
"""
import argparse
import json
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _args():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--profile", required=True)
    ap.add_argument("--steps", default="setup,session,open")
    ap.add_argument("--anki-miner", default=None, help="Anki Miner through its guard (a test copy's home)")
    ap.add_argument("--anki", default=os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Anki", "anki.exe"))
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--root", default=None, help="Surasura's scratch root (default: a new temp folder)")
    return ap.parse_args()


def say(*parts):
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


def main():
    a = _args()
    if a.profile != "DevTest":
        sys.exit("REFUSED: the drill runs on the DevTest profile only")
    root = os.path.abspath(a.root or tempfile.mkdtemp(prefix="p23-drill-"))
    os.makedirs(os.path.join(root, "User Files", "ja"), exist_ok=True)
    os.environ["SURASURA_TEST_ROOT"] = root
    os.environ.pop("SURASURA_NO_ANKI_SYNC", None)
    os.environ["SURASURA_ANKI_PROGRAM"] = a.anki            # under a test root, open_anki starts only what it's told
    sys.path.insert(0, REPO)
    from app import anki_connect
    from app.connect import anki_session, open_anki, setup

    settings = {"connect_enabled": True, "connect_open_anki": True, "anki_connect_url": a.url,
                "anki_sync_delay_min": 1, "target_language": "ja", "anki_sync_decks": {"ja": ["DevTest"]}}
    if a.anki_miner:
        settings["connect_anki_miner_path"] = a.anki_miner
    with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False)
    summary = {"root": root, "steps": {}}

    def devtest():
        try:
            return anki_connect.invoke("getActiveProfile", a.url, timeout=5) == "DevTest"
        except anki_connect.AnkiError:
            return False

    def syncs():
        from app import anki_sync_rule                     # E3.1's: the session and open steps need it
        return anki_sync_rule.read_state()

    steps = [s.strip() for s in a.steps.split(",") if s.strip()]
    # `--steps open` alone may start from Anki closed by hand on DevTest (Anki 26.9 ignores `guiExitAnki`: P1.4, P2.3):
    # Connect's record then names DevTest, as the setup step would have
    closed_already = steps == ["open"] and anki_session.look(a.url) == "closed" and not open_anki.running()
    if closed_already:
        setup.write_record({"anki_profile": "DevTest"})
    elif not devtest():
        sys.exit("REFUSED: Anki isn't open on DevTest")

    if "setup" in steps:
        result = setup.checks(settings, "ja")
        for check in result["checks"]:
            say(f"  {check['id']:20} {check['state']:12} {check['say']}" + (f"  → {check['do']}" if check["do"] else ""))
        summary["steps"]["setup"] = {"ready": result["ready"], "anki_profile": result["anki_profile"],
                                     "anki_miner": result["anki_miner"],
                                     "states": {c["id"]: c["state"] for c in result["checks"]}}
        assert result["anki_profile"] == "DevTest", result["anki_profile"]

    if "session" in steps:
        assert devtest(), "not DevTest before the sync"
        first = anki_session.begin(a.url, settings)
        assert devtest(), "not DevTest before the second look"
        second = anki_session.begin(a.url, settings)
        say("session: first", first, "· second", second, "· state", json.dumps(syncs(), ensure_ascii=False))
        summary["steps"]["session"] = {"first": first, "second": second}
        assert first == "synced" and second is None

    if "open" in steps and not closed_already:
        assert devtest(), "not DevTest before closing Anki"
        with anki_connect.writer("P2.3 drill: closing Anki on DevTest"):
            anki_connect.invoke("guiExitAnki", a.url, timeout=10)
        deadline = time.time() + 90
        while time.time() < deadline and (anki_session.look(a.url) != "closed" or open_anki.running()):
            time.sleep(1)
        closed = anki_session.look(a.url) == "closed" and not open_anki.running()
        say("open: Anki closed:", closed)
        if not closed:
            sys.exit("FAILED: Anki didn't close; nothing was started (close its DevTest window, then --steps open)")
    if "open" in steps:
        lines = []
        started = time.time()
        done = anki_session.at_window(settings, opening=True, say=lines.append)
        took = round(time.time() - started, 1)
        on = devtest()
        say("open:", json.dumps(done), "· lines", lines, "· DevTest", on, "·", took, "s")
        summary["steps"]["open"] = {"done": done, "lines": lines, "devtest": on, "seconds": took}
        if not done or done.get("anki") != "open":
            open_anki.start()                                  # never leave Anki closed: a plain start
            sys.exit("FAILED: Anki didn't answer within two minutes of the start (started again, plainly)")
        assert on and done["opened"], done          # the session's sync is reported as it came (Anki syncs on open too)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
