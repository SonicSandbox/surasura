"""P1.3's proof run (row 1.3.9; 07-tests §2): real cards, end to end, on the DevTest profile only — then every one
deleted and counted back to zero. Never run by the suites; run by hand, holding Anki's machine lock and with Sonic's OK:

    locks/with-lock.sh anki "Michi (pipeline) · P1.3" "<base folder + DevTest>" "1.3.9 proof" -- \\
        python tests/connect/live_drill.py --profile DevTest --deck DevTest \\
            --anki-miner <throwaway AnkiMiner.exe> --am-home <its throwaway home> \\
            --subtitle <public subtitle> --video <its short test video> [--words 5] [--url http://127.0.0.1:8765]

It refuses: any Anki profile but DevTest (asked of AnkiConnect, `getActiveProfile`), any deck but DevTest (Anki Miner's
export for its "Surasura" profile must name it), the user's own Anki Miner (its installer's folder) or home
(~/.anki_miner). Surasura's side runs in a scratch test root: no library, known words or settings of anyone's.

The mark: every note carries `surasura::connect::test-<run id>`. Teardown is counted, never assumed: the notes with
that tag are deleted (holding `anki-writer`) and found again; anything left fails the drill and is named.
"""
import argparse
import datetime
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _args():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--profile", required=True)
    ap.add_argument("--deck", required=True)
    ap.add_argument("--anki-miner", required=True, help="the throwaway Anki Miner's program")
    ap.add_argument("--am-home", required=True, help="its throwaway home (ANKI_MINER_HOME)")
    ap.add_argument("--subtitle", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--words", type=int, default=5, help="how many words to make cards for")
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--root", default=os.path.join(REPO, ".p13-drill"),
                    help="Surasura's scratch root: fixed, so the throwaway \"Surasura\" profile's whitelist points at "
                         "<root>/local/connect/whitelist-ja.txt once")
    ap.add_argument("--show-whitelist", action="store_true", help="print the whitelist path to set up, and stop")
    return ap.parse_args()


def refuse(why):
    sys.exit(f"REFUSED: {why}")


def main():
    a = _args()
    if a.profile != "DevTest" or a.deck != "DevTest":
        refuse("the drill runs on the DevTest profile and deck only")
    home = os.path.realpath(a.am_home)
    if home == os.path.realpath(os.path.join(os.path.expanduser("~"), ".anki_miner")):
        refuse("that is the user's own Anki Miner home")
    own = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "AnkiMiner")
    if os.path.realpath(a.anki_miner).startswith(os.path.realpath(own)):
        refuse("that is the user's own Anki Miner install")
    os.environ["ANKI_MINER_HOME"] = home                      # the child inherits it: the throwaway home only
    root = os.path.abspath(a.root)
    os.makedirs(root, exist_ok=True)
    os.environ["SURASURA_TEST_ROOT"] = root                   # Surasura's side: a scratch root, nobody's data
    sys.path.insert(0, REPO)

    from app import analyzer, anki_connect, cues
    from app.connect import anki_miner, fields, pick, runfile
    if a.show_whitelist:
        print(anki_miner.whitelist_path("ja"))
        return 0

    active = anki_connect.invoke("getActiveProfile", a.url, timeout=10)
    if active != a.profile:
        refuse(f'Anki is open on profile "{active}", not {a.profile}')

    analyzer.SANITIZE_JA = True
    read = cues.read(a.subtitle, "ja")
    chosen = pick.pick(read, cues.tokens(read, "ja"), "ja", lambda key: False, mode="unknown")
    words = [w for w in chosen["words"] if w["predicted_class"] is None][:a.words]
    if not words:
        refuse("the subtitle gave no words to make cards from")
    run_id = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    job = f"test-{run_id}"
    tag = runfile.job_tag(job)
    run_dir = os.path.join(root, "runs", job)
    os.makedirs(run_dir, exist_ok=True)

    miner = a.anki_miner
    info, profile = anki_miner.preflight(miner, "ja", "Surasura")
    mapping = fields.from_export(anki_miner.settings_export(miner, "ja", os.path.join(run_dir, "export.json"),
                                                            profile))
    if mapping.deck != a.deck:
        refuse(f'the "Surasura" profile mines into "{mapping.deck}", not {a.deck}')
    model = anki_connect.invoke("modelFieldNames", a.url, modelName=mapping.note_type)
    fields.check_note_type(mapping, model)

    print(f"Anki Miner {info.get('app')} · profile {a.profile} · deck {mapping.deck} · tag {tag}")
    print("words:", ", ".join(f"{w['word']} @ {w['line_start']}s" for w in words))
    done = anki_miner.mine_batch(miner, "ja", job, a.video, a.subtitle, words, mapping, "Surasura", run_dir, a.url,
                                 timeout=30 * 60)
    for o in done["outcomes"]:
        print(f"  {o['outcome']:13} {o['word']:10} note {o['note_id']}  line {o['line_start']} -> "
              f"{o['returned_start']}{'  (another line)' if o['other_line'] else ''}")
    made = [o for o in done["outcomes"] if o["outcome"] == "made"]

    # Teardown, counted
    query = anki_miner.tag_query(tag)
    with anki_connect.writer("P1.3 proof run teardown", wait=60):
        ids = anki_connect.find_notes(a.url, query)
        if ids:
            anki_connect.invoke("deleteNotes", a.url, notes=ids)
    left = anki_connect.find_notes(a.url, query)
    print(f"made {len(made)} of {len(words)}; deleted {len(ids)}; left with the tag: {len(left)}")
    if left:
        print(f"FAILED: notes left with {tag}: {left}")
        return 1
    if not made:
        print("FAILED: no card was made")
        return 1
    print("DRILL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
