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
    ap.add_argument("--steps", default=None,
                    help="P1.4's drill instead (row 1.4.9): junban,backfill on test notes of its own — no Anki Miner")
    ap.add_argument("--anki-miner", help="Anki Miner's program")
    home = ap.add_mutually_exclusive_group()
    home.add_argument("--am-home", help="a test copy's home (ANKI_MINER_HOME)")
    home.add_argument("--own", action="store_true", help="the user's own Anki Miner and home (his recorded OK only)")
    ap.add_argument("--subtitle")
    ap.add_argument("--video")
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
    if a.profile != "DevTest" or not a.deck.endswith("DevTest"):
        refuse("the drill runs on the DevTest profile and deck only")
    if a.steps and set(a.steps.split(",")) & {"scan", "resort", "pins"}:
        return drill_p22(a)
    if a.steps:
        return drill_p14(a)
    if a.deck != "DevTest" or not a.anki_miner or not a.subtitle or not a.video or not (a.am_home or a.own):
        refuse("P1.3's drill needs --deck DevTest, --anki-miner, --am-home or --own, --subtitle and --video")
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


# --------------------------------------------------------------------------- #
# P1.4's drill (row 1.4.9): Junban and Backfill as Connect runs them, on test notes of its own
# --------------------------------------------------------------------------- #
# (word, its sentence with no bold mark): words of the fixture list, conjugated where a verb is (K56)
P14_NOTES = [("冒険", "冒険が始まった。"), ("散歩", "毎朝散歩した。"), ("走る", "毎朝公園まで走った。"),
             ("図書館", "図書館で本を読んだ。"), ("眼鏡", "新しい眼鏡を買った。")]


def drill_p14(a):
    """`--steps junban,backfill`: on DevTest only, holding Anki's machine lock (with-lock.sh anki) and with Sonic's OK.

    Adds five new notes tagged `surasura::connect::test-<run id>` to the deck, then — Surasura in a scratch root, the
    Connect preview on — runs Connect's ordering step (`auto.reorder`, positions only, its own snapshot) and Connect's
    Backfill of the tag (the source field, K40), checks what each wrote, puts both back by their run snapshots and
    checks every card of the deck sits where it sat before. Then deletes the tagged notes and counts them back to 0."""
    import csv
    import json
    import shutil
    root = os.path.abspath(a.root.replace(".p13-drill", ".p14-drill"))
    if os.path.isdir(root):
        shutil.rmtree(root)
    os.makedirs(os.path.join(root, "results"))
    os.makedirs(os.path.join(root, "User Files", "ja"))
    os.environ["SURASURA_TEST_ROOT"] = root
    os.environ["APPDATA"] = os.path.join(root, "appdata")     # no one's token store or パターン data: a scratch one
    os.environ.pop("SURASURA_NO_ANKI_SYNC", None)
    sys.path.insert(0, REPO)
    from app import anki_connect
    from modules.junban import auto, backfill, reposition, undo

    steps = {s.strip() for s in a.steps.split(",") if s.strip()}
    active = anki_connect.invoke("getActiveProfile", a.url, timeout=10)
    if active != a.profile:
        refuse(f'Anki is open on profile "{active}", not {a.profile}')
    models = anki_connect.invoke("modelNames", a.url) or []
    if "Lapis" not in models:
        refuse("DevTest has no Lapis note type")
    lapis = anki_connect.invoke("modelFieldNames", a.url, modelName="Lapis") or []
    source_field = next((f for f in ("MiscInfo", "MigakuCardId") if f in lapis), None)
    shutil.copy2(os.path.join(REPO, "tests", "Test Resources", "ja", "expected_output.csv"),
                 os.path.join(root, "results", "priority_learning_list.csv"))
    with open(os.path.join(root, "results", "priority_learning_list.csv"), "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        for word, _sentence in P14_NOTES:       # every drill word on the list, at its back
            writer.writerow([word, word] + [""] * 3)
    settings = {"target_language": "ja", "anki_connect_url": a.url, "connect_enabled": True, "enable_junban": True,
                "junban_scope": "deck", "junban_deck": a.deck, "junban_order": "priority", "junban_unlisted": "back",
                "junban_backfill_deck": a.deck, "junban_backfill_fills": ["patterns"]}
    with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False)
    from app import settings_manager
    loaded = dict(settings_manager.load_settings(), target_language="ja")

    run_id = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    tag = f"surasura::connect::test-{run_id}"
    before = {}
    for card in anki_connect.cards_info(a.url, anki_connect.find_cards(a.url, f'deck:"{a.deck}" is:new')):
        before[card["cardId"]] = (card["due"], card["queue"])
    notes = [{"deckName": a.deck, "modelName": "Lapis", "tags": [tag],
              "fields": {lapis[0]: word, **({"Sentence": sentence} if "Sentence" in lapis else {})},
              "options": {"allowDuplicate": True}} for word, sentence in P14_NOTES]
    failed = []
    try:
        with anki_connect.writer("P1.4 drill: test notes", wait=60):
            made = [n for n in anki_connect.invoke("addNotes", a.url, notes=notes) or [] if isinstance(n, int)]
        print(f"Anki {active} · deck {a.deck} · {tag} · {len(made)} test notes made")
        if "junban" in steps:
            reorder_id = undo.new_run_id("reorder")
            done = auto.reorder(loaded, list_current=True, positions_only=True, run_id=reorder_id)
            report = done.get("report") or {}
            print(f"junban --auto: {done['outcome']} · moved {len(report.get('written') or [])} · undo {reorder_id}")
            if done["outcome"] != "ran" or any((report.get("later") or {}).values()):
                failed.append(f"junban: {done['outcome']} {report.get('later')}")
            put = reposition.restore_run(loaded, reorder_id, wait=60)
            print(f"  restore: {put['message']}")
            if not put["ok"]:
                failed.append(f"junban restore: {put['problems']}")
        if "backfill" in steps:
            session = backfill.Session(loaded)
            fill_id = undo.new_run_id("backfill")
            source = ("Surasura P1.4 drill · " + run_id, "Lapis", source_field) if source_field else None
            try:
                report = backfill.run_named(loaded, session, made, source=source, run_id=fill_id, wait=60)
            finally:
                session.close()
            print(f"backfill: {report['message']} · skipped {report['skipped']} · undo {fill_id}")
            if not report["ok"] or (source and not report["filled"]):
                failed.append(f"backfill: {report}")
            put = backfill.restore_run(loaded, fill_id, wait=60)
            print(f"  restore: {put['message']}")
            if not put["ok"]:
                failed.append(f"backfill restore: {put['problems']}")
        now = {card["cardId"]: (card["due"], card["queue"]) for card in
               anki_connect.cards_info(a.url, list(before))}
        moved = sorted(c for c, was in before.items() if now.get(c) != was)
        print(f"the deck's own {len(before)} new cards: {len(moved)} not back where they were")
        if moved:
            failed.append(f"cards not back: {moved[:10]}")
    finally:
        with anki_connect.writer("P1.4 drill teardown", wait=60):
            ids = anki_connect.find_notes(a.url, f'"tag:{tag}"')
            if ids:
                anki_connect.invoke("deleteNotes", a.url, notes=ids)
        left = anki_connect.find_notes(a.url, f'"tag:{tag}"')
        print(f"deleted {len(ids)}; left with the tag: {len(left)}")
        if left:
            failed.append(f"notes left with {tag}: {left}")
    if failed:
        print("FAILED: " + " | ".join(failed))
        return 1
    print("DRILL PASSED")
    return 0


def drill_p22(a):
    """P2.2 row 2.2.9, `--steps scan,resort,pins`: DevTest only, holding Anki's machine lock (standing go, 2026-10-07).

      * `scan` (reads only): the deck's notes whose `MiscInfo` is in Anki Miner's source shape, and whether the pin
        step's rule names each one's own file (`pins.names_of("<folder>/<name>.ja.srt")` holds the source) — 03 §8's
        measurement on real labels;
      * `resort`: five tagged test notes, then `surasura-cli resort` (in-process, a scratch root, the Connect and
        re-plan previews on): the deck spaced out once, a second run that writes nothing new, the first run put back
        from its run snapshot and every card of the deck checked back in place;
      * `pins`: with `connect.PINS` on for this drill only and one stand-in pin naming the test notes' source, a resort
        puts their cards first; put back the same way.
    Then the tagged notes are deleted and counted back to 0."""
    import io
    import json
    import shutil
    root = os.path.abspath(a.root.replace(".p13-drill", ".p22-drill"))
    if os.path.isdir(root):
        shutil.rmtree(root)
    os.makedirs(os.path.join(root, "results"))
    os.makedirs(os.path.join(root, "User Files", "ja"))
    os.environ["SURASURA_TEST_ROOT"] = root
    os.environ["APPDATA"] = os.path.join(root, "appdata")
    os.environ.pop("SURASURA_NO_ANKI_SYNC", None)
    sys.path.insert(0, REPO)
    from app import anki_connect
    from app.cli import __main__ as cli
    from modules.junban import connect, pins, reposition

    steps = {s.strip() for s in a.steps.split(",") if s.strip()}
    active = anki_connect.invoke("getActiveProfile", a.url, timeout=10)
    if active != a.profile:
        refuse(f'Anki is open on profile "{active}", not {a.profile}')
    failed = []

    if "scan" in steps:
        ids = anki_connect.find_notes(a.url, f'deck:"{a.deck}"')
        shaped, named, separated = 0, 0, 0
        for note in anki_connect.invoke("notesInfo", a.url, notes=ids) or []:
            misc = ((note.get("fields") or {}).get("MiscInfo") or {}).get("value")
            source = pins.source_of(misc)
            if source is None:
                continue
            shaped += 1
            label = str(misc).rsplit(" @ ", 1)[0]
            if " — " in label:
                separated += 1
                folder, name = label.split(" — ", 1)
                named += source in pins.names_of(f"{folder}/{name}.ja.srt")
        print(f"scan: {len(ids)} notes in {a.deck} · {shaped} with an Anki Miner source · {separated} as "
              f"'<folder> — <name>' · {named} named by the rule from their own folder and name")
        if separated and named != separated:
            failed.append(f"scan: the rule named {named} of {separated}")

    if not steps & {"resort", "pins"}:
        return _verdict(failed)
    shutil.copy2(os.path.join(REPO, "tests", "Test Resources", "ja", "expected_output.csv"),
                 os.path.join(root, "results", "priority_learning_list.csv"))
    settings = {"target_language": "ja", "anki_connect_url": a.url, "connect_enabled": True, "enable_junban": True,
                "junban_scope": "deck", "junban_deck": a.deck, "junban_order": "priority", "junban_unlisted": "back",
                "junban_replan_preview": True}
    with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False)
    from app import analyzer, settings_manager
    loaded = dict(settings_manager.load_settings(), target_language="ja")
    analyzer.journey_is_current = lambda argv, lang: True     # the scratch root's list is current by fiat (no Generate)

    def resort():
        out = io.StringIO()
        code = cli.main(["resort", "--lang", "ja", "--wait", "60"], out=out)
        return code, json.loads(out.getvalue().splitlines()[-1])

    run_id = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    tag = f"surasura::connect::test-{run_id}"
    source = f"P22 drill — episode {run_id} @ 00:00:01"
    before = {c["cardId"]: (c["due"], c["queue"]) for c in
              anki_connect.cards_info(a.url, anki_connect.find_cards(a.url, f'deck:"{a.deck}" is:new'))}
    lapis = anki_connect.invoke("modelFieldNames", a.url, modelName="Lapis") or []
    notes = [{"deckName": a.deck, "modelName": "Lapis", "tags": [tag],
              "fields": {lapis[0]: word, **({"Sentence": sentence} if "Sentence" in lapis else {}),
                         **({"MiscInfo": source} if "MiscInfo" in lapis else {})},
              "options": {"allowDuplicate": True}} for word, sentence in P14_NOTES]
    ids = []
    try:
        with anki_connect.writer("P2.2 drill: test notes", wait=60):
            made = [n for n in anki_connect.invoke("addNotes", a.url, notes=notes) or [] if isinstance(n, int)]
        mine = set(anki_connect.find_cards(a.url, f'"tag:{tag}"'))
        print(f"Anki {active} · deck {a.deck} · {tag} · {len(made)} test notes, {len(mine)} cards")
        if "resort" in steps:
            code, first = resort()
            print(f"resort: exit {code} · {first.get('numbering')} · moved {first.get('moves')} · undo {first.get('undo')}")
            code2, second = resort()
            print(f"resort again: exit {code2} · {second.get('numbering')} · moved {second.get('moves')}")
            if code or first.get("numbering") not in ("full", "delta") or code2 or second.get("moves"):
                failed.append(f"resort: {first} / {second}")
            for undo_id in filter(None, (second.get("undo"), first.get("undo"))):
                put = reposition.restore_run(loaded, undo_id, wait=60)
                print(f"  restore {undo_id}: {put['message']}")
                if not put["ok"]:
                    failed.append(f"restore {undo_id}: {put['problems']}")
        if "pins" in steps and "MiscInfo" in lapis:
            connect.PINS = True
            pins.read = lambda language: ([(1, f"P22 drill/episode {run_id}.ja.srt", "2026-10-07T00:00:00Z")], {},
                                          {})
            code, line = resort()
            order = sorted((c for c in anki_connect.cards_info(a.url, list(before) + sorted(mine)) if c["queue"] == 0),
                           key=lambda c: (c["due"], c["cardId"]))
            first_ids = {c["cardId"] for c in order[:len(mine)]}
            print(f"pins: exit {code} · pinned first {line.get('pinned_first')} · the test cards lead: "
                  f"{first_ids == mine}")
            if code or line.get("pinned_first") != len(mine) or first_ids != mine:
                failed.append(f"pins: {line}")
            if line.get("undo"):
                put = reposition.restore_run(loaded, line["undo"], wait=60)
                print(f"  restore {line['undo']}: {put['message']}")
                if not put["ok"]:
                    failed.append(f"pins restore: {put['problems']}")
        now = {c["cardId"]: (c["due"], c["queue"]) for c in anki_connect.cards_info(a.url, list(before))}
        moved = sorted(c for c, was in before.items() if now.get(c) != was)
        print(f"the deck's own {len(before)} new cards: {len(moved)} not back where they were")
        if moved:
            failed.append(f"cards not back: {moved[:10]}")
    finally:
        with anki_connect.writer("P2.2 drill teardown", wait=60):
            ids = anki_connect.find_notes(a.url, f'"tag:{tag}"')
            if ids:
                anki_connect.invoke("deleteNotes", a.url, notes=ids)
        left = anki_connect.find_notes(a.url, f'"tag:{tag}"')
        print(f"deleted {len(ids)}; left with the tag: {len(left)}")
        if left:
            failed.append(f"notes left with {tag}: {left}")
    return _verdict(failed)


def _verdict(failed):
    if failed:
        print("FAILED: " + " | ".join(failed))
        return 1
    print("DRILL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
