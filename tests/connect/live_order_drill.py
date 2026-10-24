"""Drill A3 on DevTest (the confidence audit 2026-10-23, Area 3 (e); Michi's R2): after Surasura re-orders, do the new
cards Anki SERVES follow the library's order? Never run by the suites; by hand, with locks/anki.lock taken by hand
(board lines) and Anki open on DevTest.

    python tests/connect/live_order_drill.py --profile DevTest --deck "DevTest::A3 drill"

- Library: `tests/plan_file_cases.build(root, "rp2-ja")` plus `library_episode.ass` and `placed_episode.srt` in Soon,
  a real Generate under a scratch SURASURA_TEST_ROOT. Settings: 順's deck = the drill deck, content order, List first,
  the cards not on the list tagged + suspended, 順's actions on (3.0's host applies them).
- Deck: the drill deck (made here, deleted at teardown) on a preset of its own cloned from Default (DevTest's decks
  all share Default; Default is never written). Base options: Sequential, gather Deck (0), sort Order gathered (1).
- Notes (tag `surasura::junban::test-a3-<run>`): the first 60 list keys, Basic, due reversed (added last key
  first); two of those keys as Basic (and reversed card); two list keys as Lapis notes whose `MiscInfo` names one item
  (the pin); the words Finish takes off the list (up to 4); three words not on the list.
- The oracle, the drill's own (never Junban's plan): the rows of the engine re-planned here for the store's order
  (`plan_engine.Engine(...).replan`, the rows the host hands Junban — the order the run follows; after a Generate, the
  progressive CSV it wrote, which those rows equal), each card's key (its first field: the notes are written with the
  list's own keys) at the row where the key is first met; within a word (old due, cardId); pinned cards first; a card
  whose key is on no row after every listed one.
- Steps, each read back as `findCards deck:"<deck>" is:new -is:suspended` + `cardsInfo` sorted by (due, cardId),
  required EXACTLY equal to the oracle: 1 catch-up; 2 NOW's first item <-> Soon's first (`moves.Writer.move`);
  3 pin the MiscInfo item; 4 Finish runaway_transcript.txt; 5 skipped (the W-1 stone, R3); 6 Generate, then the job:
  zero `setSpecificValueOfCard`; 7 Restore: every still-new card's due = the baseline; 8 the order re-applied, one
  note's word edited, then a catch-up (audit gap 3: the edited note is placed again).
- What Anki serves (after step 2): `guiDeckReview` -> `guiCurrentCard` = oracle[0], suspended out of the way (never
  answered), read again: 5 cards; unsuspended. Then sort "Card type, then order gathered" (0); then gather "Random
  cards" (4): preflight must refuse; then a subdeck under gather Deck (0) vs Ascending position (1).

`getActiveProfile == "DevTest"` before every write and at teardown. Teardown: every note with the tag deleted, the
drill decks deleted, Default's options compared with the start, notes counted back to 0.
"""
import argparse
import csv
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RES = os.path.join(REPO, "tests", "Test Resources", "ja")
UNLISTED = ["冷蔵庫", "宇宙船", "掃除機"]
SOON_EXTRA = ["library_episode.ass", "placed_episode.srt"]
# The item Finished: the one of 6+ Months whose words the list loses when it leaves (runaway_transcript.txt, the audit's
# pick, gives the list no word of its own: none is first met there).
FINISH = "eighty_six_ch2.txt"
PIN = "context_test.txt"
_URLOPEN = urllib.request.urlopen
WRITES = {"set": 0, "requests": 0, "what": []}
_SET = re.compile(rb'"action"\s*:\s*"setSpecificValueOfCard"')       # a write, never the probe's apiReflect list


def say(*parts):
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


def _counting(request, *args, **kwargs):
    data = getattr(request, "data", None) or b""
    found = len(_SET.findall(data))
    if found:
        WRITES["requests"] += 1
        WRITES["set"] += found
        if found <= 5:
            WRITES["what"].append(data.decode("utf-8", "replace")[:600])
    return _URLOPEN(request, *args, **kwargs)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--profile", required=True)
    ap.add_argument("--deck", default="DevTest::A3 drill")
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--out", default=None, help="the JSON result's file (default: printed only)")
    ap.add_argument("--preset", type=int, default=None,
                    help="an earlier run's drill preset id to use again (a preset can't be deleted without a full sync)")
    a = ap.parse_args()
    if a.profile != "DevTest" or not a.deck.startswith("DevTest::"):
        sys.exit("REFUSED: the drill runs on the DevTest profile, in a deck under DevTest:: only")
    deck, sub = a.deck, a.deck + "::Sub"

    def raw(action, **params):
        body = json.dumps({"action": action, "version": 6, "params": params}).encode("utf-8")
        req = urllib.request.Request(a.url, body, {"Content-Type": "application/json"})
        with _URLOPEN(req, timeout=120) as r:
            reply = json.loads(r.read().decode("utf-8"))
        if reply.get("error"):
            raise RuntimeError(f"{action}: {reply['error']}")
        return reply.get("result")

    def devtest():
        try:
            return raw("getActiveProfile") == "DevTest"
        except Exception:
            return False

    def guard():
        if not devtest():
            raise SystemExit("STOPPED: Anki isn't on DevTest")

    if not devtest():
        sys.exit("REFUSED: Anki isn't open on DevTest")

    root = tempfile.mkdtemp(prefix="a3-order-")
    sys.path.insert(0, REPO)
    from tests import plan_file_cases as cases
    env = cases.child_env(root)
    for name in ("SURASURA_TEST_ROOT", "APPDATA", "LOCALAPPDATA"):
        os.environ[name] = env[name]
    os.environ.pop("SURASURA_NO_ANKI_SYNC", None)
    urllib.request.urlopen = _counting

    run = time.strftime("%Y%m%d%H%M%S")
    tag = f"surasura::junban::test-a3-{run}"
    out = {"root": root, "tag": tag, "deck": deck, "steps": {}, "served": {}}
    start_default = raw("getDeckConfig", deck="DevTest")
    out["live_config_default"] = {k: start_default.get(k) for k in ("newGatherPriority", "newSortOrder", "newMix")}
    out["live_config_default"]["new.order"] = (start_default.get("new") or {}).get("order")
    out["live_config_default"]["keys"] = sorted(start_default)
    state = {"writer": None, "preset": None}
    try:
        _drill(a, raw, guard, cases, root, deck, sub, tag, out, state)
    except SystemExit as e:
        out["stopped"] = str(e)
    except Exception as e:                       # the drill's own failure: recorded, the teardown still runs
        import traceback
        out["error"] = f"{type(e).__name__}: {e}"
        out["traceback"] = traceback.format_exc()[-3000:]
    finally:
        out["teardown"] = _teardown(raw, devtest, deck, sub, tag, start_default, state)
        text = json.dumps(out, ensure_ascii=False, indent=1, default=str)
        if a.out:
            with open(a.out, "w", encoding="utf-8") as f:
                f.write(text)
        print(text.encode(sys.stdout.encoding or "utf-8", "replace").decode(sys.stdout.encoding or "utf-8"))
    return 0 if out["teardown"].get("notes_left") == 0 else 1


# --------------------------------------------------------------------------------------------------------------- #

def _settings(root, deck, url):
    settings = {"target_language": "ja", "enable_junban": True, "junban_scope": "deck", "junban_deck": deck,
                "junban_replan_language": "ja", "junban_replan_deck": deck, "junban_order": "content",
                "junban_unlisted": "list_first", "junban_later_tag": True, "junban_later_suspend": True,
                "junban_auto_actions": True, "anki_connect_url": url, "anki_sync_delay_min": "off"}
    with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False)


def _library(cases, root):
    cases.build(root, "rp2-ja")
    folder = os.path.join(root, "data", "ja", "LowPriority")
    manifest = os.path.join(root, "User Files", "ja", "master_manifest.json")
    with open(manifest, encoding="utf-8") as f:
        doc = json.load(f)
    for name in SOON_EXTRA:
        path = os.path.join(folder, name)
        shutil.copy(os.path.join(RES, name), path)
        os.utime(path, (cases.MTIME, cases.MTIME))
        doc["schedule"]["PHASE_2_SOON"].append({"physical_path": f"LowPriority/{name}", "title": name,
                                                "origin_source": "Manual Import"})
    with open(manifest, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)


def _generate(cases, root):
    from app import run_args
    with open(os.path.join(root, "settings.json"), encoding="utf-8") as f:
        settings = json.load(f)
    started = time.perf_counter()
    cases.generate(root, "rp2-ja", argv=run_args.analyzer_args(settings, "ja", headless=True)[1:])
    return round(time.perf_counter() - started, 1)


def _store():
    from app import library_store
    from app.path_utils import get_data_path, get_user_files_path
    return library_store.open_store("ja", get_data_path("ja"), get_user_files_path("ja"))


def _key(row):
    """The word a card carries for a row (the list's own key: Orth, or Word for a one-character spelling of a longer
    word — `anki_match.build_index`'s guard)."""
    word, orth = (row.get("Word") or "").strip(), (row.get("Orth") or "").strip()
    key = orth or word
    if len(key) == 1 and key != word:
        key = word
    return key


def _first_index(rows):
    first = {}
    for i, row in enumerate(rows):
        k = _key(row)
        if k and k not in first:
            first[k] = i
    return first


def _engine_rows(drop=(), swap=False):
    """The oracle's rows: the plan file's engine re-planned HERE for the store's order now (NOW, Soon, 6+ Months, each
    in `ord, id`), the items in `drop` left out — the rows the host hands Junban, computed without the host."""
    from app import analyzer, plan_engine
    from app.path_utils import get_user_file
    plan = plan_engine.load(os.path.join(get_user_file("results"), analyzer.PLAN_FILE))
    store = _store()
    try:
        ids = [store.item_id(entry[0]) for entry in plan.files]
        held = set(i for i in ids if i is not None)
        tiers = {tier: [i for i in store.ids(tier) if i in held and i not in drop] for tier in ("now", "soon", "goal")}
        if swap:                             # step 2's order, worked out ahead: NOW's first <-> Soon's first
            now, soon = tiers["now"], tiers["soon"]
            now[0], soon[0] = soon[0], now[0]
        order = [(i, tier) for tier in ("now", "soon", "goal") for i in tiers[tier]]
    finally:
        store.close()
    return plan_engine.Engine(plan, ids).replan(order).rows("content")


def _csv_rows():
    from app.path_utils import get_user_file
    with open(os.path.join(get_user_file("results"), "progressive_learning_list.csv"), encoding="utf-8-sig",
              newline="") as f:
        return list(csv.DictReader(f))


def _cards(raw, query):
    ids = raw("findCards", query=query)
    info = raw("cardsInfo", cards=ids) if ids else []
    for c in info:
        fields = c.get("fields") or {}
        first = min(fields.items(), key=lambda kv: kv[1].get("order", 0))[1]["value"] if fields else ""
        c["key"] = first
    return info


def _queue(raw, deck):
    """Anki's new, unsuspended cards in the deck, sorted (due, cardId)."""
    return sorted(_cards(raw, f'deck:"{deck}" is:new -is:suspended'), key=lambda c: (c["due"], c["cardId"]))


def _oracle(rows, cards, old_due, pinned=()):
    first = _first_index(rows)
    pinned = set(pinned)

    def k(c):
        return (first[c["key"]], old_due.get(c["cardId"], c["due"]), c["cardId"])
    listed = [c for c in cards if c["key"] in first and c["cardId"] not in pinned]
    pins = sorted([c for c in cards if c["cardId"] in pinned and c["key"] in first], key=k)
    pins += sorted([c for c in cards if c["cardId"] in pinned and c["key"] not in first],
                   key=lambda c: (old_due.get(c["cardId"], c["due"]), c["cardId"]))
    rest = sorted([c for c in cards if c["key"] not in first and c["cardId"] not in pinned],
                  key=lambda c: (old_due.get(c["cardId"], c["due"]), c["cardId"]))
    return pins + sorted(listed, key=k) + rest


def _compare(expected, got):
    e, g = [c["cardId"] for c in expected], [c["cardId"] for c in got]
    key_of = {c["cardId"]: c["key"] for c in expected + got}
    mism = [{"pos": i, "expected": key_of.get(x), "got": key_of.get(y)}
            for i, (x, y) in enumerate(zip(e, g)) if x != y]
    return {"exact": e == g, "n_expected": len(e), "n_got": len(g), "mismatches": mism[:15],
            "n_mismatches": len(mism), "missing": [key_of[c] for c in set(e) - set(g)],
            "extra": [key_of[c] for c in set(g) - set(e)], "first10": [key_of[c] for c in g[:10]],
            "expected10": [key_of[c] for c in e[:10]]}


def _check(raw, deck, rows, before, pinned=(), lines=None, writes=None):
    got = _queue(raw, deck)
    expected = _oracle(rows, got, before, pinned)
    result = _compare(expected, got)
    result["host_line"] = (lines or [""])[-1] if lines else ""
    if writes is not None:
        result["set_writes"] = writes
    return result, got


def _dues(raw, deck):
    return {c["cardId"]: c["due"] for c in _cards(raw, f'deck:"{deck}"')}


def _job(host, kind, guard):
    guard()
    WRITES["set"] = WRITES["requests"] = 0
    WRITES["what"] = []
    if kind == "catch-up":
        host._anki_looked = -1e9
    host._job(kind)
    return {"set": WRITES["set"], "requests": WRITES["requests"], "what": list(WRITES["what"])}


def _writer_do(state, what, *args, **kw):
    from app.services import moves
    if state["writer"] is None:
        from app.qt.strings import MOVE_WORDS     # the window's own words (plain strings; no Qt imported)
        state["writer"] = moves.Writer.for_language("ja", words=MOVE_WORDS).start()
    w = state["writer"]
    getattr(w, what)(*args, **kw)
    if not w.idle(timeout=30):
        raise RuntimeError(f"the writer's {what} didn't land")


def _served(raw, deck, n=5):
    """What Anki shows: Study on the deck, the current card, suspended out of the way (never answered), again."""
    seen = []
    try:
        raw("guiDeckReview", name=deck)
        time.sleep(1.0)
        for _ in range(n):
            card = raw("guiCurrentCard")
            if not card:
                break
            seen.append((card["cardId"], card.get("fields", {})))
            raw("suspend", cards=[card["cardId"]])
            raw("guiDeckBrowser")
            time.sleep(0.5)
            raw("guiDeckReview", name=deck)
            time.sleep(1.0)
    finally:
        raw("guiDeckBrowser")
        time.sleep(0.5)
        if seen:
            raw("unsuspend", cards=[c for c, _f in seen])
    return [c for c, _f in seen]


def _set_options(raw, preset, **values):
    config = raw("getDeckConfig", deck=preset["deck"])
    for k, v in values.items():
        if k == "order":
            config["new"]["order"] = v
        else:
            config[k] = v
    raw("saveDeckConfig", config=config)
    return {k: (config["new"]["order"] if k == "order" else config[k]) for k in values}


def _drill(a, raw, guard, cases, root, deck, sub, tag, out, state):
    from app import replan_preview
    from app.path_utils import ensure_data_setup
    from modules.junban import reposition

    # --- the library and its Generate ---
    _library(cases, root)
    _settings(root, deck, a.url)
    ensure_data_setup("ja")
    out["generate_s"] = _generate(cases, root)
    rows = _engine_rows()
    csv_rows = _csv_rows()
    out["engine_rows_equal_csv_after_generate"] = [_key(r) for r in rows] == [_key(r) for r in csv_rows]
    first = _first_index(rows)
    keys = sorted(first, key=first.get)
    store = _store()
    try:
        by_name = {store.item(i)["rel_path"].replace("\\", "/").rsplit("/", 1)[-1]: i
                   for t in ("now", "soon", "goal") for i in store.ids(t)}
        pin_item, finish_item = by_name[PIN], by_name[FINISH]
        pin_path = store.item(pin_item)["rel_path"].replace("\\", "/")
        out["order_at_start"] = {t: [store.item(i)["rel_path"] for i in store.ids(t)] for t in ("now", "soon", "goal")}
    finally:
        store.close()
    gone = set(_first_index(_engine_rows(drop={finish_item}))) ^ set(first)
    only = [k for k in keys if k in gone and k not in keys[:62]][:4]
    base = keys[:60]
    pin_keys = keys[60:62]
    texts = "".join(open(os.path.join(dp, f), encoding="utf-8", errors="replace").read()
                    for dp, _d, fs in os.walk(os.path.join(root, "data", "ja")) for f in fs
                    if f.endswith((".srt", ".txt", ".ass")))
    unlisted = [w for w in UNLISTED if w not in texts and w not in first]
    folder, stem = os.path.basename(os.path.dirname(pin_path)), os.path.splitext(os.path.basename(pin_path))[0]
    misc = f"{folder} — {stem} @ 00:01:23"
    ahead = [k for k in sorted(_first_index(_engine_rows(swap=True)).items(), key=lambda kv: kv[1]) if k[0] in base]
    reversed_keys = [ahead[1][0], ahead[3][0]]       # near the front once step 2 has run: the served check meets them
    out["notes_plan"] = {"base": len(base), "reversed": reversed_keys, "pin": pin_keys, "pin_misc": misc,
                         "only_words": only, "unlisted": unlisted, "gone_on_finish": len(gone)}

    # --- the deck, its own preset, the notes ---
    guard()
    raw("createDeck", deck=deck)
    preset_id = a.preset or raw("cloneDeckConfigId", name=f"A3 drill {tag[-14:]}", cloneFrom=1)
    raw("setDeckConfigId", decks=[deck], configId=preset_id)
    state["preset"] = {"id": preset_id, "deck": deck}
    out["base_options"] = _set_options(raw, state["preset"], order=1, newGatherPriority=0, newSortOrder=1)
    live = raw("getDeckConfig", deck=deck)
    out["live_config_drill"] = {k: live.get(k) for k in ("newGatherPriority", "newSortOrder", "newMix")}
    out["live_config_drill"]["new.order"] = live["new"]["order"]
    out["live_config_drill"]["perDay"] = live["new"]["perDay"]

    def note(model, fields):
        return {"deckName": deck, "modelName": model, "tags": [tag], "options": {"allowDuplicate": True},
                "fields": fields}
    wanted = []
    for k in base:
        model = "Basic (and reversed card)" if k in reversed_keys else "Basic"
        wanted.append(note(model, {"Front": k, "Back": "A3 drill"}))
    for k in pin_keys:
        wanted.append(note("Lapis", {"Expression": k, "MiscInfo": misc}))
    for k in only + unlisted:
        wanted.append(note("Basic", {"Front": k, "Back": "A3 drill"}))
    wanted.reverse()                         # added last key first: the list's first word at the back (due reversed)
    from app import anki_connect
    with anki_connect.writer("A3 order drill", wait=60):
        guard()
        ids = raw("addNotes", notes=wanted)
    out["notes_made"] = len([i for i in ids if i])
    baseline = _dues(raw, deck)
    state["snaps"] = {"baseline": baseline}
    out["cards_made"] = len(baseline)
    pinned_cards = [c["cardId"] for c in _cards(raw, f'deck:"{deck}" note:Lapis')]

    lines = []
    host = replan_preview.Host("ja", say=lines.append)
    steps = out["steps"]

    # 1 the catch-up job: the first ladder
    before = _dues(raw, deck)
    state.setdefault("snaps", {})[f"before job {len(state.get('snaps', {}))}"] = before
    w = _job(host, "catch-up", guard)
    rows = _engine_rows()
    steps["1_catch_up"], q = _check(raw, deck, rows, before, lines=lines, writes=w)
    steps["1_catch_up"]["unlisted_state"] = [
        {"key": c["key"], "queue": c["queue"]} for c in _cards(raw, f'deck:"{deck}" "tag:Surasura::later"')]
    say("step 1", steps["1_catch_up"]["exact"], lines[-1:] if lines else "")

    # 2 swap NOW's first item with Soon's first (Writer.move)
    store = _store()
    try:
        now_first, soon_first = store.ids("now")[0], store.ids("soon")[0]
        soon_second = store.ids("soon")[1]
    finally:
        store.close()
    guard()
    _writer_do(state, "move", [soon_first], "now", before_id=now_first)
    _writer_do(state, "move", [now_first], "soon", before_id=soon_second)
    before = _dues(raw, deck)
    state.setdefault("snaps", {})[f"before job {len(state.get('snaps', {}))}"] = before
    w = _job(host, "move", guard)
    rows = _engine_rows()
    steps["2_swap"], q = _check(raw, deck, rows, before, lines=lines, writes=w)
    store = _store()
    try:
        steps["2_swap"]["order"] = {t: [store.item(i)["rel_path"] for i in store.ids(t)][:3] for t in ("now", "soon")}
    finally:
        store.close()
    say("step 2", steps["2_swap"]["exact"], lines[-1:])

    # --- what Anki serves (base options: gather Deck, sort Order gathered) ---
    served = out["served"]
    oracle_ids = [c["cardId"] for c in _oracle(rows, q, {c["cardId"]: c["due"] for c in q})]
    key_of = {c["cardId"]: c["key"] for c in q}
    guard()
    got = _served(raw, deck)
    served["base"] = {"served": [key_of.get(c, c) for c in got], "oracle": [key_of[c] for c in oracle_ids[:5]],
                      "pass": got == oracle_ids[:5]}
    say("served base", served["base"])
    guard()
    _set_options(raw, state["preset"], newSortOrder=0)
    back = [i for i, c in enumerate(oracle_ids) if raw_model(q, c) == "Basic (and reversed card)"]
    n = 20                                   # a day's new cards (perDay 20): where the reversed notes' backs come
    got = _served(raw, deck, n=n)
    served["sort_card_type_then_gathered"] = {"served": [key_of.get(c, c) for c in got],
                                              "oracle": [key_of[c] for c in oracle_ids[:n]],
                                              "pass": got == oracle_ids[:n],
                                              "reversed_at": back,
                                              "reversed_notes": out["notes_plan"]["reversed"],
                                              "preflight": _preflight(host, reposition)}
    say("served sort 0", served["sort_card_type_then_gathered"])
    guard()
    _set_options(raw, state["preset"], newSortOrder=1, newGatherPriority=4)
    served["gather_random_cards"] = {"preflight": _preflight(host, reposition)}
    WRITES["set"] = 0
    lines_at = len(lines)
    host._force = True                       # a job that runs owed or not: does the run refuse the random gather?
    w = _job(host, "move", guard)
    host._force = False
    served["gather_random_cards"]["host_job"] = {"set_writes": w, "lines": lines[lines_at:]}
    say("gather 4", served["gather_random_cards"])
    # a subdeck: the first 3 oracle cards moved into it
    guard()
    _set_options(raw, state["preset"], newGatherPriority=0)
    raw("createDeck", deck=sub)
    raw("setDeckConfigId", decks=[sub], configId=state["preset"]["id"])
    moved = oracle_ids[:3]
    raw("changeDeck", cards=moved, deck=sub)
    got = _served(raw, deck)
    served["subdeck_gather_deck"] = {"in_sub": [key_of[c] for c in moved], "served": [key_of.get(c, c) for c in got],
                                     "oracle": [key_of[c] for c in oracle_ids[:5]], "pass": got == oracle_ids[:5],
                                     "preflight": _preflight(host, reposition)}
    guard()
    _set_options(raw, state["preset"], newGatherPriority=1)
    got = _served(raw, deck)
    served["subdeck_ascending_position"] = {"served": [key_of.get(c, c) for c in got],
                                            "oracle": [key_of[c] for c in oracle_ids[:5]],
                                            "pass": got == oracle_ids[:5], "preflight": _preflight(host, reposition)}
    say("subdeck", served["subdeck_gather_deck"], served["subdeck_ascending_position"])
    guard()
    raw("changeDeck", cards=moved, deck=deck)
    if not raw("findCards", query=f'deck:"{sub}"'):
        raw("deleteDecks", decks=[sub], cardsToo=True)          # empty: Anki deletes a deck only with its cards
    _set_options(raw, state["preset"], order=1, newGatherPriority=0, newSortOrder=1)
    after, _ = _check(raw, deck, rows, {c["cardId"]: c["due"] for c in q})
    served["queue_unchanged_after"] = after["exact"]

    # 3 pin the MiscInfo item: its 2 cards first
    guard()
    _writer_do(state, "pin", [pin_item])
    before = _dues(raw, deck)
    state.setdefault("snaps", {})[f"before job {len(state.get('snaps', {}))}"] = before
    w = _job(host, "move", guard)
    rows = _engine_rows()
    steps["3_pin"], q = _check(raw, deck, rows, before, pinned=pinned_cards, lines=lines, writes=w)
    steps["3_pin"]["pinned_keys"] = pin_keys
    say("step 3", steps["3_pin"]["exact"], lines[-1:])

    # 4 Finish runaway_transcript: its only-words suspended and tagged, the rest match
    guard()
    _writer_do(state, "set_finished", [finish_item])
    before = _dues(raw, deck)
    state.setdefault("snaps", {})[f"before job {len(state.get('snaps', {}))}"] = before
    w = _job(host, "move", guard)
    rows = _engine_rows()
    steps["4_finish"], q = _check(raw, deck, rows, before, pinned=pinned_cards, lines=lines, writes=w)
    later = {c["key"]: c["queue"] for c in _cards(raw, f'deck:"{deck}" "tag:Surasura::later"')}
    steps["4_finish"]["only_words"] = {k: later.get(k, "not tagged") for k in only}
    steps["4_finish"]["only_words_pass"] = bool(only) and all(later.get(k) == -1 for k in only)
    say("step 4", steps["4_finish"]["exact"], steps["4_finish"]["only_words"], lines[-1:])

    steps["5_stone"] = {"skipped": "the W-1 stone: after W-1 lands (R3 / M-W2)"}

    # 6 Generate, then the job: zero setSpecificValueOfCard
    if state["writer"] is not None:
        state["writer"].finish(time.monotonic() + 30)
        state["writer"] = None
    out["generate2_s"] = _generate(cases, root)
    rows_before = rows                       # step 4's rows: the fast re-plan's list before the Generate
    queue_before = {c["cardId"]: c["key"] for c in q}
    before = _dues(raw, deck)
    state.setdefault("snaps", {})[f"before job {len(state.get('snaps', {}))}"] = before
    w = _job(host, "generate", guard)
    csv_rows = _csv_rows()
    steps["6_generate"], q = _check(raw, deck, csv_rows, before, pinned=pinned_cards, lines=lines, writes=w)
    steps["6_generate"]["zero_writes"] = w["set"] == 0
    in_queue = {c["cardId"] for c in q}
    steps["6_generate"]["left_the_queue"] = [k for cid, k in queue_before.items() if cid not in in_queue]
    steps["6_generate"]["written_keys"] = [queue_before.get(int(m), m) for m in
                                           re.findall(r'"card": (\d+)', " ".join(w["what"]))]
    steps["6_generate"]["left_the_list_at_generate"] = sorted(set(_first_index(rows_before)) - set(_first_index(csv_rows)))
    steps["6_generate"]["joined_the_list_at_generate"] = sorted(set(_first_index(csv_rows)) - set(_first_index(rows_before)))
    steps["6_generate"]["engine_rows_equal_csv"] = [_key(r) for r in _engine_rows()] == [_key(r) for r in csv_rows]
    say("step 6", steps["6_generate"]["exact"], w, lines[-1:])

    # 7 Restore: every still-new card's due = the baseline
    guard()
    settings = host._settings()
    restored = reposition.restore(settings)
    now = _cards(raw, f'deck:"{deck}"')
    snaps = state["snaps"]
    new_due = {c["cardId"]: c["due"] for c in now if c["type"] == 0}
    steps_7_matches = [name for name, snap in snaps.items()
                       if all(snap.get(cid) == due for cid, due in new_due.items())]
    differ = [{"key": c["key"], "due": c["due"], "baseline": baseline.get(c["cardId"]), "queue": c["queue"]}
              for c in now if c["type"] == 0 and c["due"] != baseline.get(c["cardId"])]
    steps["7_restore"] = {"ok": restored.get("ok"), "problems": restored.get("problems"),
                          "message": restored.get("message"), "differ": differ[:15], "n_differ": len(differ),
                          "still_suspended": [c["key"] for c in now if c["queue"] == -1],
                          "pass": bool(restored.get("ok")) and not differ,
                          "dues_equal_the_state_before": steps_7_matches}
    say("step 7", steps["7_restore"]["pass"], restored.get("message"))

    # 8 the order re-applied (two moves), one note's word edited, then a catch-up (gap 3)
    store = _store()
    try:
        a1 = store.ids("now")[0]
        a2 = store.ids("now")[1]
    finally:
        store.close()
    guard()
    _writer_do(state, "move", [a2], "now", before_id=a1)
    _writer_do(state, "move", [a1], "now", before_id=a2)
    before = _dues(raw, deck)
    state.setdefault("snaps", {})[f"before job {len(state.get('snaps', {}))}"] = before
    w = _job(host, "move", guard)
    rows = _engine_rows()
    reapplied, q = _check(raw, deck, rows, before, pinned=pinned_cards, lines=lines, writes=w)
    listed = [c for c in q if c["key"] in _first_index(rows) and c["cardId"] not in pinned_cards]
    edited = listed[-1]
    new_word = keys[0]
    note_id = edited["note"]
    guard()
    raw("updateNoteFields", note={"id": note_id, "fields": {"Front": new_word}})
    before = _dues(raw, deck)
    state.setdefault("snaps", {})[f"before job {len(state.get('snaps', {}))}"] = before
    w = _job(host, "catch-up", guard)
    steps["8_edit"], q = _check(raw, deck, rows, before, pinned=pinned_cards, lines=lines, writes=w)
    steps["8_edit"]["reapplied_exact"] = reapplied["exact"]
    steps["8_edit"]["edited"] = {"from": edited["key"], "to": new_word,
                                 "position_now": [c["cardId"] for c in q].index(edited["cardId"])
                                 if edited["cardId"] in [c["cardId"] for c in q] else None}
    say("step 8", steps["8_edit"]["exact"], steps["8_edit"]["edited"])
    out["host_lines"] = lines[-30:]


def raw_model(cards, card_id):
    return next((c.get("modelName") for c in cards if c["cardId"] == card_id), None)


def _preflight(host, reposition):
    settings = host._settings()
    p = reposition.preflight(settings)
    return {"ok": p.get("ok"), "problems": p.get("problems"), "warnings": p.get("warnings")}


def _teardown(raw, devtest, deck, sub, tag, start_default, state):
    t = {}
    if state.get("writer") is not None:
        try:
            state["writer"].finish(time.monotonic() + 30)
        except Exception as e:
            t["writer"] = str(e)
    if not devtest():
        t["notes_left"] = "NOT CHECKED: Anki left DevTest"
        return t
    try:
        raw("guiDeckBrowser")
    except Exception:
        pass
    from app import anki_connect
    left = raw("findNotes", query=f'"tag:{tag}"')
    if left:
        with anki_connect.writer("A3 order drill teardown", wait=60):
            raw("deleteNotes", notes=left)
    names = raw("deckNames")
    gone = [d for d in (sub, deck) if d in names]
    if gone:
        raw("deleteDecks", decks=gone, cardsToo=True)
    t["decks_left"] = [d for d in (sub, deck) if d in raw("deckNames")]
    t["notes_left"] = len(raw("findNotes", query=f'"tag:{tag}"'))
    now_default = raw("getDeckConfig", deck="DevTest")
    t["default_options_unchanged"] = now_default == start_default
    t["preset_left"] = (state.get("preset") or {}).get("id")
    t["profile"] = raw("getActiveProfile")
    return t


if __name__ == "__main__":
    sys.exit(main())
