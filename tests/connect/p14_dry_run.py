"""P1.4's proof, its first half (row 1.4.9): `surasura-cli junban --dry-run` with the Connect preview on, on a deck Sonic
names, beside the 順 window's own preview of the same deck — they must match. Run by hand, only with his go:

    python tests/connect/p14_dry_run.py --tree "<his Surasura folder>" --deck "<the deck he names>" [--language ja]

Read only, everywhere. His files are never opened for writing: his list (`results/`), his known words and answers
(`User Files/<lang>/`), his settings and his token store are COPIED into a scratch root first (a preview may refresh a
cache in `results/`), and Surasura runs there with the preview switched on in the copy only. Anki is asked only for
reads (a dry run sends no write action; the drill counts what it sent and fails on any write). Prints both previews'
numbers and the first difference, and leaves the scratch root for a look (deleted with `--clean`).
"""
import argparse
import io
import json
import os
import queue
import shutil
import sys
from types import SimpleNamespace

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# The only actions this run may send: reads. Anything else — a write, a sync, a GUI action — is refused in this
# process before a byte reaches Anki (the run fails, nothing is sent).
READS = {"version", "requestPermission", "apiReflect", "deckNames", "getDeckConfig", "findCards", "cardsInfo",
         "notesInfo", "findNotes", "modelNames", "modelFieldNames", "guiReviewActive", "getActiveProfile",
         "cardsToNotes", "multi"}


class Refused(Exception):
    pass


def _actions(payload):
    yield payload.get("action")
    if payload.get("action") == "multi":
        for inner in (payload.get("params") or {}).get("actions") or []:
            yield from _actions(inner)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tree", required=True, help="his Surasura folder (read only)")
    ap.add_argument("--deck", default=None, help="default: the deck his 順 settings name, else TheBank")
    ap.add_argument("--language", default="ja")
    ap.add_argument("--root", default=os.path.join(REPO, ".p14-dry-run"))
    ap.add_argument("--clean", action="store_true")
    a = ap.parse_args()
    tree, lang, root = os.path.abspath(a.tree), a.language, os.path.abspath(a.root)
    if os.path.isdir(root):
        shutil.rmtree(root)
    shutil.copytree(os.path.join(tree, "results"), os.path.join(root, "results"))
    shutil.copytree(os.path.join(tree, "User Files", lang), os.path.join(root, "User Files", lang),
                    ignore=shutil.ignore_patterns(".trash"))
    shutil.copy2(os.path.join(tree, "settings.json"), os.path.join(root, "settings.his.json"))
    with open(os.path.join(root, "settings.his.json"), "r", encoding="utf-8") as f:
        settings = json.load(f)
    deck = a.deck or str(settings.get("junban_deck") or "").strip() or "TheBank"
    print(f"deck: {deck}")
    settings.update(target_language=lang, connect_enabled=True, junban_scope="deck", junban_deck=deck)
    with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False)
    store = os.path.join(os.environ.get("APPDATA", ""), "SonicSandbox", "Surasura", f"token_store_{lang}.db")
    appdata = os.path.join(root, "appdata")
    os.makedirs(os.path.join(appdata, "SonicSandbox", "Surasura"))
    for part in ("", "-wal", "-shm"):                   # the SQLite file with its journal, copied before anything reads
        if os.path.isfile(store + part):
            shutil.copy2(store + part, os.path.join(appdata, "SonicSandbox", "Surasura"))
    os.environ.update(SURASURA_TEST_ROOT=root, APPDATA=appdata)
    os.environ.pop("SURASURA_NO_ANKI_SYNC", None)
    sys.path.insert(0, REPO)

    import urllib.request
    sent = []
    real = urllib.request.urlopen

    def watching(request, *args, **kwargs):          # reads only: anything else never leaves this process
        names = list(_actions(json.loads(request.data.decode("utf-8"))))
        bad = [name for name in names if name not in READS]
        if bad:
            raise Refused(f"refused before sending: {bad}")
        sent.extend(names)
        return real(request, *args, **kwargs)
    urllib.request.urlopen = watching

    from app import settings_manager
    from app.cli import __main__ as cli
    from modules.junban import gui
    out = io.StringIO()
    code = cli.main(["junban", "--dry-run", "--lang", lang], out=out)
    line = json.loads(out.getvalue().splitlines()[-1])
    window = SimpleNamespace(q=queue.Queue(), _is_list_current=lambda args, language: True,
                             _context_counts=lambda s, decks: {})
    gui.JunbanGui._preview_worker(window, dict(settings_manager.load_settings(), target_language=lang), "key")
    tag, stats, checks, _key = window.q.get_nowait()
    from app import anki_connect
    print(f"Anki profile: {anki_connect.invoke('getActiveProfile', settings.get('anki_connect_url') or 'http://127.0.0.1:8765')}")
    writes = sorted(set(sent) - READS)
    print(f"command line: exit {code} · {line}")
    print(f"the window:   to_write {stats.get('to_write')} · unmatched {stats.get('unmatched')} · "
          f"yours {len(stats.get('yours') or [])} · returning {len(stats.get('returning') or [])} · "
          f"unsure {stats.get('unsure')}")
    print(f"actions sent: {sorted(set(sent))}")
    ok = (code == 0 and tag == "__PREVIEW__" and checks.get("ok") and line.get("moves") == stats.get("to_write")
          and line.get("not_on_list") == stats.get("unmatched") and not writes)
    if writes:
        print(f"FAILED: write actions were sent: {writes}")
    print("DRY RUN MATCHES THE WINDOW" if ok else "FAILED: the dry run and the window differ")
    if a.clean:
        shutil.rmtree(root, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
