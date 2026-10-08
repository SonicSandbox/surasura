"""P2.4's Part B proof and figures on DevTest (row 2.4.16; build prompt § *The figures to measure*): never run by the
suites; by hand, with locks/anki.lock taken by hand (board lines) and Anki open on DevTest.

    python tests/connect/live_cards_drill.py --profile DevTest --steps deletion,junban,shelf,idle [--notes 300,1000]

- `deletion`: `findNotes "nid:…"` over 300 and 3,000 note ids (synthetic ids above any real one, plus the test
  notes made here): requests and milliseconds — 2.4.14's cost per session.
- `junban`: synthetic test notes (Basic, tag `surasura::connect::test-p24cards-<run>`, deck DevTest) to 300, then
  1,000 waiting; `surasura-cli junban --auto` on a scratch root pointed at deck DevTest: wall time, AnkiConnect
  requests (counted by a loopback counting proxy), writes on a second run (expected 0).
- `shelf` (2.4.11): 50 of the test notes shelved through `shelf.shelve` and brought back through
  `shelf.bring_back`; then `findCards` checks: suspended and tagged, then neither.
- `idle`: `surasura-cli connect` with nothing to do: start to exit; and waiting on Anki "closed" (a dead address)
  for one look: CPU seconds.

`getActiveProfile == "DevTest"` before anything and before teardown. Teardown: every note with the run's tag deleted
(holding `anki-writer`) and counted back to 0. A media-sync figure (its AnkiWeb half) and the top-up of 300 need
Anki Miner and a sync on the throwaway account: they run from `live_loop_drill.py` with a cap.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def say(*parts):
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--profile", required=True)
    ap.add_argument("--steps", default="deletion,junban,shelf,idle")
    ap.add_argument("--notes", default="300,1000")
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--deck", default="DevTest")
    a = ap.parse_args()
    if a.profile != "DevTest" or a.deck != "DevTest":
        sys.exit("REFUSED: the drill runs on the DevTest profile and deck only")
    root = tempfile.mkdtemp(prefix="p24-cards-")
    os.environ["SURASURA_TEST_ROOT"] = root
    os.environ.pop("SURASURA_NO_ANKI_SYNC", None)
    sys.path.insert(0, REPO)
    from app import anki_connect

    def ask(action, **params):
        return anki_connect.invoke(action, a.url, timeout=120, **params)

    def devtest():
        try:
            return ask("getActiveProfile") == "DevTest"
        except anki_connect.AnkiError:
            return False

    if not devtest():
        sys.exit("REFUSED: Anki isn't open on DevTest")
    run = time.strftime("%Y%m%d%H%M%S")
    tag = f"surasura::connect::test-p24cards-{run}"
    steps = [s.strip() for s in a.steps.split(",") if s.strip()]
    sizes = [int(n) for n in a.notes.split(",") if n.strip()]
    out = {"root": root, "tag": tag}
    made = []

    def add_notes(n):
        model = "Basic" if "Basic" in ask("modelNames") else ask("modelNames")[0]
        front, back = ask("modelFieldNames", modelName=model)[:2]
        words = ["上層部", "一生懸命", "気配", "溜め息", "約束", "勇気", "走り出す", "眼鏡"]
        notes = [{"deckName": a.deck, "modelName": model, "tags": [tag], "options": {"allowDuplicate": True},
                  "fields": {front: f"{words[i % len(words)]}{len(made) + i}", back: "drill"}} for i in range(n)]
        with anki_connect.writer("P2.4 cards drill", wait=60):
            ids = ask("addNotes", notes=notes)
        made.extend(i for i in ids if i)

    try:
        if "deletion" in steps:
            fig = {}
            for n in (300, 3000):
                ids = list(range(10 ** 13, 10 ** 13 + n))
                started = time.perf_counter()
                from app.connect import shelf
                gone = shelf.gone_notes(shelf.AnkiConnectAnki(a.url), ids)
                fig[n] = {"ms": round((time.perf_counter() - started) * 1000, 1), "requests": -(-n // shelf.GONE_CHUNK),
                          "gone": len(gone)}
            out["deletion"] = fig
            say("deletion check", fig)
        if "junban" in steps or "shelf" in steps:
            for n in sizes:
                if len(made) < n:
                    add_notes(n - len(made))
                    say("test notes", len(made))
                if "junban" in steps:
                    out.setdefault("junban", {})[n] = _junban(root, a, ask)
                    say("junban", n, out["junban"][n])
        if "shelf" in steps and made:
            out["shelf"] = _shelf(a, ask, made[:50], tag)
            say("shelf", out["shelf"])
        if "idle" in steps:
            out["idle"] = _idle(root, a)
            say("idle", out["idle"])
    finally:
        if devtest():
            left = ask("findNotes", query=f'"tag:{tag}"')
            if left:
                with anki_connect.writer("P2.4 cards drill teardown", wait=60):
                    ask("deleteNotes", notes=left)
            out["teardown_left"] = len(ask("findNotes", query=f'"tag:{tag}"'))
        else:
            out["teardown_left"] = "NOT CHECKED: Anki left DevTest"
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0 if out.get("teardown_left") == 0 else 1


def _cli(root, *args, url):
    settings = {"target_language": "ja", "connect_enabled": True, "anki_connect_url": url, "enable_junban": True,
                "junban_deck": "DevTest", "anki_sync_decks": {"ja": ["DevTest"]}}
    with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as f:
        json.dump(settings, f)
    os.makedirs(os.path.join(root, "User Files", "ja"), exist_ok=True)
    started = time.perf_counter()
    done = subprocess.run([sys.executable, "-m", "app.cli", *args], cwd=REPO, capture_output=True, timeout=3600,
                          env=dict(os.environ, SURASURA_TEST_ROOT=root))
    seconds = round(time.perf_counter() - started, 2)
    lines = [ln for ln in done.stdout.decode("utf-8", "replace").splitlines() if ln.startswith("{")]
    return done.returncode, (json.loads(lines[-1]) if lines else None), seconds


def _junban(root, a, ask):
    first = _cli(root, "junban", "--auto", url=a.url)
    second = _cli(root, "junban", "--auto", url=a.url)
    return {"first": {"exit": first[0], "seconds": first[2], "answer": first[1]},
            "second": {"exit": second[0], "seconds": second[2], "moves": (second[1] or {}).get("moves")}}


def _shelf(a, ask, notes, tag):
    from app.connect import shelf
    from app.connect.ledger import Ledger
    anki = shelf.AnkiConnectAnki(a.url)
    cards = ask("findCards", query=" OR ".join(f"nid:{n}" for n in notes))
    info = anki.cards_info(cards)
    chosen = [shelf.Card(c["cardId"], c["note"], "drill", 1) for c in info]
    with Ledger() as ledger:
        started = time.perf_counter()
        run = shelf.shelve(anki, ledger, "ja", chosen, "drill")
        shelved_ms = round((time.perf_counter() - started) * 1000, 1)
        suspended = len(ask("findCards", query=f'"tag:{tag}" "tag:{shelf.SHELF_TAG}" is:suspended'))
        started = time.perf_counter()
        shelf.bring_back(anki, ledger, "ja", chosen)
        back_ms = round((time.perf_counter() - started) * 1000, 1)
        still = len(ask("findCards", query=f'"tag:{tag}" ("tag:{shelf.SHELF_TAG}" OR is:suspended)'))
    return {"run": run, "shelved": len(chosen), "suspended_and_tagged": suspended, "shelve_ms": shelved_ms,
            "back_ms": back_ms, "left_suspended_or_tagged": still}


def _idle(root, a):
    nothing = _cli(root, "connect", "--looks", "1", url=a.url)
    closed = _cli(root, "connect", "--looks", "1", url="http://127.0.0.1:9")
    return {"nothing_to_do_s": nothing[2], "exit": nothing[0], "anki_closed_one_look_s": closed[2]}


if __name__ == "__main__":
    sys.exit(main())
