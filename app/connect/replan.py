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
  * `generate-first` for a setting that re-cuts the list (the level, the band and their kin, `RECUT`): no re-plan —
    mine from the list as it is — and Generate after mining ("after");
  * anything else (no plan, another language or engine, a run that didn't finish, a new or changed file, the store
    set up again) and `stand-aside`: today's path, Generate first ("first").

Any error reading it is "first" (logged): never worse than today. Read-only: nothing here writes the store, the plan
or Anki. Light: no Qt, Tk or pandas (the analyzer's signature, the engine and the store are the command line's own).
"""
import logging
import os

log = logging.getLogger("surasura-cli")

# `generate-first` reasons the engine can't serve but mining from the list as it is serves (a level or band change
# and their kin: the words already listed keep their places until the Generate re-cuts it)
RECUT = ("settings", "auto_band", "args", "freq")


class Current:
    """What Connect works from now: `verdict` (`plan_engine.check`'s, or ("generate-first", why) when it couldn't be
    read), `generate` ("no" · "after" · "first"), `reason` (plain words for the log and the mark), `result` (the
    engine's `Result`, or None), `plan` and `ids` (the plan and each plan file's item id), `versions` (the store's,
    read with the order), `listed` ({(Word, Reading): place} in the result's priority order, or None), `places`
    (RP-10, or None) and `key` (what it was read at: `key`)."""

    __slots__ = ("verdict", "generate", "reason", "result", "plan", "ids", "versions", "listed", "places", "key",
                 "plan_key")

    def __init__(self, verdict, generate, reason, result=None, plan=None, ids=None, versions=None, key=None,
                 plan_key=None):
        self.verdict, self.generate, self.reason = verdict, generate, reason
        self.result, self.plan, self.ids, self.versions = result, plan, ids, versions
        self.key, self.plan_key = key, plan_key
        self.listed = self.places = None
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


def current(language, settings, store, previous=None):
    """The plan for the library as it stands -> a `Current` (see the module docstring). `previous`: the last one read,
    whose loaded plan is kept while the plan file is the same (the window's host keeps it the same way)."""
    try:
        return _current(language, settings, store, previous)
    except Exception as e:                  # never worse than today: the Generate runs first
        log.warning("Connect couldn't read its plan (%s); it Generates first: %s", language, e)
        return Current(("generate-first", "error"), "first", f"the plan couldn't be read: {e}")


def _current(language, settings, store, previous):
    from app import analyzer, library_store, plan_engine, replan_preview, run_args
    from app.path_utils import get_user_file
    versions, order = replan_preview._snapshot(store)
    path = replan_preview.plan_path()
    plan_key = _stat(path)
    at = key(store, versions)
    if plan_key is None:
        return Current(("generate-first", "no-plan"), "first", "no plan yet", versions=versions, key=at)
    if previous is not None and previous.plan is not None and previous.plan_key == plan_key:
        plan = previous.plan
    else:
        try:
            plan = plan_engine.load(path)
        except plan_engine.PlanError as e:
            return Current(("generate-first", "plan"), "first", f"plan: {e}", versions=versions, key=at)
    # The run signature's parts for the library as it stands (`Host._parts`): a missing item keeps its place
    found = analyzer.resolve_found_files(language, verbose=False, schedule=store.schedule(), missing=True)
    args = analyzer.parse_analysis_args(run_args.analyzer_args(settings, language)[1:])
    parts = analyzer.run_signature_parts(language, found, args)
    verdict = plan_engine.check(plan, language, analyzer.engine_id(), analyzer.read_run_stamp(get_user_file("results")),
                                parts, store.versions().get("epoch"))
    if verdict is not None and verdict[0] == "generate-first" and verdict[1] in RECUT:
        return Current(verdict, "after", verdict[1], plan=plan, versions=versions, key=at, plan_key=plan_key)
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
    return Current(verdict, "after", ",".join(verdict[1]), result, plan, ids, versions, at, plan_key)
