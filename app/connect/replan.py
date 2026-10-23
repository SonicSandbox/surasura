"""Connect on the fast re-plan (P3.3, K78; F11): what Connect mines and orders from after a move, a placement, a
known-words sync or a level change — the plan the last Generate wrote, re-planned to the store's order, instead of a
full Generate in the loop.

    got = replan.current(language, settings, store)     # the verdict and, when the engine serves it, the re-plan
    got.generate                                         # "no" · "after" (mining first, then Generate) · "first"
    got.listed                                           # {(Word, Reading): place} — the pick's ranks — or None
    got.rows(junban_order), got.places                   # Junban's rows and RP-10's file numbers (`spaced.Job`)

**One classifier** (RUNBOOK-P3.3's table): the plan's verdict (`plan_engine.check`, the window's re-order host's own
recipe: `replan_preview`'s `_snapshot`, `plan_path`, `places`) decides —

  * `None` (only the order or the pins moved): re-plan; mine and order from it; **no Generate** ("no");
  * `replan-now` (known words, word lists, items left): re-plan now — provisional (E2.2-1 (b)) — and Generate after
    mining ("after");
  * `generate-first` for **files added** alone (P4.1 C5, row 4.1.4: a new episode placed before its Generate) —
    every file the plan holds still there, unchanged, and more, nothing else moved but the known words or the word
    lists: re-plan now the files the plan knows (the new ones wait for the Generate), mine — the pick reads each
    episode's own lines as for every job, so a new episode's words already on the list are picked by the re-plan's
    ranks — and Generate after mining ("after", reason `new-files`); the level look on that Generate's list then
    gives the episode the words it newly lists. A word that Generate drops from the list keeps its card, at the back
    (N38);
  * `generate-first` for a **level raise proven** (`_level_raised`): the band alone moved,
    to a rarer one (more words: later in `word_selection.BANDS_ORDER`) — with Automatic rarity on, the band it
    remembers — and nothing else moved but the known words or the word lists: no re-plan — mine from the list as it
    is (its words keep their places; the raise only adds words) — and Generate after mining ("after");
  * anything else (no plan, another language or engine, a run that didn't finish, a changed or removed file, the store
    set up again, a level lowered — its Generate drops words the old list would have mined — another setting, the
    args, a frequency list, the band with any of them, a band not found, the set-aside files — W-1: a watched mark
    either way, as the window's host reads it) and `stand-aside`: today's path, Generate first ("first").

Any error reading it is "first" (logged): never worse than today. Read-only: nothing here writes the store, the plan
or Anki. Light: no Qt, Tk or pandas (the analyzer's signature, the engine and the store are the command line's own).
"""
import logging
import os

log = logging.getLogger("surasura-cli")

# What may move with a level raise and still be mined from the list as it is: the known words and the word lists (the
# Generate after mining counts them); anything else — a file, the args, a frequency list, the engine — Generates first
WITH_THE_LEVEL = ("known", "lists")


class Current:
    """What Connect works from now: `verdict` (`plan_engine.check`'s, or ("generate-first", why) when it couldn't be
    read), `generate` ("no" · "after" · "first"), `reason` (plain words for the log and the mark), `result` (the
    engine's `Result`, or None), `plan` and `ids` (the plan and each plan file's item id), `versions` (the store's,
    read with the order), `listed` ({(Word, Reading): place} in the result's priority order, or None), `places`
    (RP-10, or None), `key` (what it was read at: `key`), `plan_key` (the plan file's (mtime, size) when it was
    loaded: the next read keeps the loaded plan while it is the same) and `settings_key` (the settings it was read
    with: `settings_key`, set by `current`; None: read again next time)."""

    __slots__ = ("verdict", "generate", "reason", "result", "plan", "ids", "versions", "listed", "places", "key",
                 "plan_key", "settings_key")

    def __init__(self, verdict, generate, reason, result=None, plan=None, ids=None, versions=None, key=None,
                 plan_key=None):
        self.verdict, self.generate, self.reason = verdict, generate, reason
        self.result, self.plan, self.ids, self.versions = result, plan, ids, versions
        self.key, self.plan_key = key, plan_key
        self.listed = self.places = self.settings_key = None
        if result is not None:
            listed = {}
            for row in result.priority:
                listed.setdefault((row.get("Word", ""), row.get("Reading", "")), len(listed))
            self.listed = listed
            from app import replan_preview
            self.places = replan_preview.places(plan, ids, result)

    def rows(self, mode="content"):
        """Junban's rows from the re-plan (`Result.rows`), in 順's order (`junban_order`: content · priority)."""
        mode = str(mode or "content").strip().lower()
        return self.result.rows(mode if mode in ("content", "priority") else "content")


def _stat(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def key(store, versions=None):
    """What a `Current` depends on, cheap to read again (a stat, a small file, the store's versions): the order and
    pins versions, the store's epoch, the plan file (mtime, size) and the run stamp. A move, a placement, a new plan or
    another run since -> another key."""
    from app import analyzer, replan_preview
    from app.path_utils import get_user_file
    v = store.versions() if versions is None else versions
    return (v.get("order_version"), v.get("pins_version"), v.get("epoch"), _stat(replan_preview.plan_path()),
            analyzer.read_run_stamp(get_user_file("results")))


def settings_key(settings, language):
    """What the verdict reads of `settings` (the run signature's settings part, `analyzer.settings_signature`, and
    the analyzer's args, `run_args.analyzer_args`): another one -> the verdict read again (a band lowered mid-run
    with the window closed moves neither the store nor the plan: the final adversary's #4, H10)."""
    from app import analyzer, run_args
    return analyzer.settings_signature(settings, language), tuple(run_args.analyzer_args(settings, language))


def current(language, settings, store, previous=None):
    """The plan for the library as it stands -> a `Current` (see the module docstring). `previous`: the last one read,
    whose loaded plan is kept while the plan file is the same (the window's host keeps it the same way)."""
    try:
        got = _current(language, settings, store, previous)
    except Exception as e:                  # never worse than today: the Generate runs first
        log.warning("Connect couldn't read its plan (%s); it Generates first: %s", language, e)
        got = Current(("generate-first", "error"), "first", f"the plan couldn't be read: {e}")
    try:
        got.settings_key = settings_key(settings, language)
    except Exception as e:                  # None: never the same as a key read later, so read again then
        log.warning("Connect couldn't sign the settings it read its plan with (%s): %s", language, e)
    return got


def _current(language, settings, store, previous):
    from app import analyzer, library_store, plan_engine, replan_preview, run_args
    from app.path_utils import get_user_file
    path = replan_preview.plan_path()
    plan_key = _stat(path)
    if plan_key is None:                    # no plan: nothing else to read
        versions = store.versions()
        return Current(("generate-first", "no-plan"), "first", "no plan yet", versions=versions,
                       key=key(store, versions))
    # One read of the store: the order, the files the run signature counts and the versions, in one transaction
    schedule, versions = store.schedule(with_versions=True, with_aside=True)
    order = replan_preview._order(schedule)
    at = key(store, versions)
    if previous is not None and previous.plan is not None and previous.plan_key == plan_key:
        plan = previous.plan
    else:
        try:
            plan = plan_engine.load(path)
        except plan_engine.PlanError as e:
            log.warning("Connect couldn't read its plan (%s); it Generates first: %s", language, e)
            return Current(("generate-first", "plan"), "first", f"plan: {e}", versions=versions, key=at)
    # The run signature's parts for the library as it stands (`Host._parts`): a missing item keeps its place
    found = analyzer.resolve_found_files(language, verbose=False, schedule=schedule, missing=True)
    args = analyzer.parse_analysis_args(run_args.analyzer_args(settings, language)[1:])
    parts = analyzer.run_signature_parts(language, found, args, analyzer.aside_files(language, schedule))
    engine_id, stamp = analyzer.engine_id(), analyzer.read_run_stamp(get_user_file("results"))
    verdict = plan_engine.check(plan, language, engine_id, stamp, parts, versions.get("epoch"))
    added = _added(plan, parts) if verdict == ("generate-first", "files") else ()
    if added:
        # P4.1 C5 (row 4.1.4): files added alone — the engine's own classifier asked again with them named as added
        # (`check`'s "files-added"): the plan's files are re-planned below and the new ones wait for the Generate
        # after mining; any other part moved with them (a setting, the args, a file changed) stays generate-first
        verdict = plan_engine.check(plan, language, engine_id, stamp, parts, versions.get("epoch"), added=added)
    if verdict is not None and verdict[0] == "generate-first" and verdict[1] in ("settings", "auto_band"):
        raised = _level_raised(plan, parts, language)
        if raised is not None:
            return Current(verdict, "after", f"the level raised ({raised[0]} -> {raised[1]})", plan=plan,
                           versions=versions, key=at, plan_key=plan_key)
        log.info("Connect (%s): %s moved since the plan, and not the level raised alone: it Generates first",
                 language, verdict[1])
    if verdict is not None and verdict[0] != "replan-now":
        return Current(verdict, "first", verdict[1], plan=plan, versions=versions, key=at, plan_key=plan_key)
    # The re-plan to the store's order (`Host._replan`): each plan file's item, ranked NOW, Soon, 6+ Months as the
    # store holds them; a plan file that left the counted tiers is dropped
    ids = [store.item_id(entry[0]) for entry in plan.files]
    engine = plan_engine.Engine(plan, ids)
    ranked = sorted(order[k] + (item_id,) for k, item_id in
                    ((library_store.path_key(entry[0]), item_id) for entry, item_id in zip(plan.files, ids)
                     if item_id is not None) if k in order)
    result = engine.replan([(item_id, tier) for _rank, _place, tier, item_id in ranked])
    if verdict is None:
        return Current(None, "no", "only the order moved", result, plan, ids, versions, at, plan_key)
    reason = ",".join("new-files" if part == "files-added" else part for part in verdict[1])
    return Current(verdict, "after", reason, result, plan, ids, versions, at, plan_key)


def _added(plan, parts):
    """The digests (`plan_rules.file_digest`) of the files the library counts that the plan doesn't hold — what
    `plan_engine.check` is asked again with (`added=`): its own `_only_added` decides whether they are files added
    alone (every plan file still counted, unchanged); a file changed or gone with them stays generate-first.

    No token store is read (P4.1 S2: one recipe): the engine re-plans only the files the plan holds, and the pick reads
    a new episode's own lines through the analyzer's tokenizer, as for every job — a file not yet indexed is served
    the same way, so a placed episode never waits for the background indexer."""
    from app import plan_rules
    held = {entry[2] for entry in plan.files if len(entry) > 2}
    try:
        return tuple(sorted({plan_rules.file_digest(entry) for entry in parts["files"]} - held))
    except Exception:
        return ()


def _level_raised(plan, parts, language):
    """(the plan's band, the band now) when the level alone was raised since the plan — the
    band in force moved to a rarer one (more words: later in `word_selection.BANDS_ORDER`) and nothing else moved but
    the known words or the word lists — else None (Generate first: a lowering, the band with another setting, a file
    or the args, a band that can't be told).

    The band in force is the analyzer's: `logic.selection.band`, or with Automatic rarity on (the signature's
    `auto_band` part is there) the band the store remembers. The plan's is found by putting each other band back —
    into the settings (`analyzer.settings_signature`), or as the `auto_band` part — and digesting it as
    `plan_rules.part_digests` digests that part: the one whose digest is the plan's."""
    from app import analyzer, plan_rules, settings_manager, word_selection
    kept = plan.header.get("order_free_parts")
    if not isinstance(kept, dict):
        return None
    now = plan_rules.part_digests(parts)
    moved = {name for name in set(kept) | set(now) if kept.get(name) != now.get(name)}
    part = "auto_band" if "auto_band" in parts else "settings"
    if part not in moved or moved - {part, *WITH_THE_LEVEL}:
        return None
    bands = word_selection.BANDS_ORDER
    if part == "auto_band":
        band, candidates = parts["auto_band"], [*bands, None]

        def digest(value):
            return plan_rules.part_digests({"files": [], "auto_band": value})["auto_band"]
    else:
        loaded = settings_manager.load_settings()
        if analyzer.settings_signature(loaded, language) != parts["settings"]:
            return None                     # settings.json changed since the parts were read: not ours to guess
        logic = loaded.get("logic") or {}
        selection = logic.get("selection") or {}
        band, candidates = selection.get("band", "occasional"), bands     # the analyzer's own default

        def digest(value):
            put_back = dict(loaded, logic=dict(logic, selection=dict(selection, band=value)))
            return plan_rules.part_digests({"files": [], "settings": analyzer.settings_signature(put_back,
                                                                                                language)})["settings"]
    if band not in bands:
        return None
    was = next((value for value in candidates if value != band and digest(value) == kept.get(part)), None)
    if was not in bands or bands.index(was) >= bands.index(band):
        return None                         # a lowering, or a band the plan wasn't cut at that can be named
    return was, band
