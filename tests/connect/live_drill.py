"""P1.3's proof run (row 1.3.9; 07-tests §2): real cards, end to end, on the DevTest profile only — then every one
deleted and counted back to zero. Never run by the suites; run by hand, holding Anki's machine lock and with Sonic's OK:

    locks/with-lock.sh anki "Michi (pipeline) · P1.3" "<Anki: DevTest>" "1.3.9 proof" -- \\
        python tests/connect/live_drill.py --profile DevTest --deck DevTest --anki-miner <AnkiMiner.exe> \\
            [--am-home <a test copy's home> | --own] --subtitle <public subtitle> --video <its test video> \\
            [--words 5] [--url http://127.0.0.1:8765]

It refuses any Anki profile but DevTest (asked of AnkiConnect, `getActiveProfile`, before any write). The cards go to
deck DevTest whatever the Anki Miner profile's own deck: the run's `config` names it (an overlay for this run only,
never saved), so the "Surasura" profile itself is only read — its id, its note type and field mapping (its export,
deleted once read; nothing of it printed). `--own` is the user's own Anki Miner and home (only with his recorded OK:
QUESTIONS.md *P1.3-3, his own Anki Miner instead*); without it the drill refuses them and needs a test copy's home.
Surasura's side runs in a scratch test root: no library, known words or settings of anyone's.

The mark: every note carries `surasura::connect::test-<run id>`. Teardown is counted, never assumed: the notes with
that tag are deleted (holding `anki-writer`) and found again; anything left fails the drill and is named. Anki Miner's
selected profile is read before and after: the drill changes none of its settings.
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
    ap.add_argument("--anki-miner", required=True, help="Anki Miner's program")
    home = ap.add_mutually_exclusive_group(required=True)
    home.add_argument("--am-home", help="a test copy's home (ANKI_MINER_HOME)")
    home.add_argument("--own", action="store_true", help="the user's own Anki Miner and home (his recorded OK only)")
    ap.add_argument("--subtitle", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--words", type=int, default=5, help="how many words to make cards for")
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--root", default=os.path.join(REPO, ".p13-drill"),
                    help="Surasura's scratch root (its whitelist file is <root>/local/connect/whitelist-ja.txt)")
    ap.add_argument("--show-whitelist", action="store_true", help="print the whitelist path, and stop")
    return ap.parse_args()


def refuse(why):
    sys.exit(f"REFUSED: {why}")


def main():
    a = _args()
    if a.profile != "DevTest" or a.deck != "DevTest":
        refuse("the drill runs on the DevTest profile and deck only")
    own = os.path.realpath(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "AnkiMiner"))
    if not a.own:
        home = os.path.realpath(a.am_home)
        if home == os.path.realpath(os.path.join(os.path.expanduser("~"), ".anki_miner")):
            refuse("that is the user's own Anki Miner home (only with --own)")
        if os.path.realpath(a.anki_miner).startswith(own):
            refuse("that is the user's own Anki Miner install (only with --own)")
        os.environ["ANKI_MINER_HOME"] = home                  # the child inherits it: the test copy's home only
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
    listed = anki_miner.profiles(miner)
    selected = [p.get("id") for p in listed if p.get("active")]
    profile = anki_miner.profile_id(listed, "Surasura")
    if profile is None:
        refuse('Anki Miner has no "Surasura" profile')
    export = os.path.join(run_dir, "export.json")
    try:
        mapping = fields.from_export(anki_miner.settings_export(miner, "ja", export, profile))
    finally:
        if os.path.exists(export):
            os.remove(export)               # the profile's settings: read for three fields, never kept
    mapping = mapping._replace(deck=a.deck)                   # this run's deck, by the run's own config
    model = anki_connect.invoke("modelFieldNames", a.url, modelName=mapping.note_type)
    fields.check_note_type(mapping, model)

    # The profile's own deck may not be in DevTest: its `check` is read for what the run itself needs (Anki, the
    # dictionary, ffmpeg); deck and note type are checked here, against DevTest, as the run's config names them.
    info = anki_miner.version(miner)
    ready = anki_miner.check(miner, "ja", profile)
    missing = [i.get("name") for i in ready.get("items") or ()
               if not i.get("ok") and i.get("name") not in ("deck", "note_type", "fields")]
    if missing:
        refuse(f"Anki Miner isn't ready: {', '.join(missing)}")
    anki_miner.preflight = lambda path, language, name: (info, profile)

    print(f"Anki Miner {info.get('app')} · Anki {active} · deck {mapping.deck} · note type {mapping.note_type} · {tag}")
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
    after = [p.get("id") for p in anki_miner.profiles(miner) if p.get("active")]
    print(f"made {len(made)} of {len(words)}; deleted {len(ids)}; left with the tag: {len(left)}; "
          f"Anki Miner's selected profile {'unchanged' if after == selected else f'CHANGED {selected} -> {after}'}")
    if left:
        print(f"FAILED: notes left with {tag}: {left}")
        return 1
    if not made or after != selected:
        print("FAILED: " + ("no card was made" if not made else "the selected profile changed"))
        return 1
    print("DRILL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
