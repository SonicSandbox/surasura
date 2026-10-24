"""The phase strip's rules (`app/services/phase.py`, Qt-free): which circle each piece of work lights, and how.

What a wrong answer would cost a learner:
  * a job that runs while its circle stays dim (a new kind nobody placed) — "I can't tell what my actions trigger";
  * a circle that flickers for every short automatic read, or one stuck lit after the work ended;
  * a failure that vanishes before it was seen, or one that never goes;
  * Connect's episode that waits on you (not timed, Anki closed) shown nowhere.
"""
import ast
import os

from app.services import jobs as J
from app.services import phase as P
from app.services import status as S
from app.services.jobs import JobRegistry
from app.services.press import Presses

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --- every kind the window can register is placed (like `PLACED`) ------------------------------------------------- #
def _constants(tree):
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value.value
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value
    return out


def registered_kinds():
    """(kinds, the calls whose kind couldn't be read) of every job the code registers: `….registry.submit(kind, …)`,
    `registry.record(kind, …)`, `tools.run(registry, kind, …)` in `app/` and `modules/` (tests aside)."""
    files, consts = [], {}
    for top in ("app", "modules"):
        for folder, dirs, names in os.walk(os.path.join(ROOT, top)):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__")]
            for name in names:
                if name.endswith(".py"):
                    path = os.path.join(folder, name)
                    tree = ast.parse(open(path, encoding="utf-8").read())
                    files.append((path, tree))
                    for k, v in _constants(tree).items():
                        consts.setdefault(k, v)
    kinds, unread = set(J.RESOURCES), []
    for path, tree in files:
        own = _constants(tree)

        def value(arg):
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                return {arg.value}
            name = arg.id if isinstance(arg, ast.Name) else arg.attr if isinstance(arg, ast.Attribute) else None
            got = own.get(name, consts.get(name)) if name else None
            if isinstance(got, str):
                return {got}
            if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and arg.func.attr == "get":
                table = own.get(getattr(arg.func.value, "id", None))          # `_CHILD_KINDS.get(cmd, "child")`
                out = value(arg.args[1]) if len(arg.args) > 1 else set()
                if isinstance(table, ast.Dict) and out is not None:
                    return out | {v.value for v in table.values if isinstance(v, ast.Constant)}
            if isinstance(arg, ast.Call) and getattr(arg.func, "id", getattr(arg.func, "attr", None)) == "kind_of":
                return set()                                                  # arrivals-<lang>: in RESOURCES
            return None

        passed = set()                    # a function's own parameter (`tools.run`'s `kind`): its callers are read
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for call in ast.walk(fn):
                    if isinstance(call, ast.Call):
                        names = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
                        if any(isinstance(a, ast.Name) and a.id in names for a in call.args[:2]):
                            passed.add(id(call))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or id(node) in passed:
                continue
            receiver = ast.unparse(node.func.value)
            arg = None
            if node.func.attr in ("submit", "record") and ("registry" in receiver or receiver.endswith("[0]")):
                arg = node.args[0] if node.args else None
            elif node.func.attr == "run" and receiver == "tools" and len(node.args) > 1:
                arg = node.args[1]
            if arg is None:
                continue
            got = value(arg)
            if got is None:
                unread.append(f"{os.path.relpath(path, ROOT)}:{node.lineno} {ast.unparse(arg)}")
            else:
                kinds |= got
    return kinds, unread


def test_every_job_kind_the_window_can_register_names_its_circle_or_none():
    """A new kind nobody placed would run with its circle dim: the table names every one (None: no circle, Q7)."""
    kinds, unread = registered_kinds()
    unread = [u for u in unread if not u.endswith(" self.kind")       # importers' `kind` class attributes: below
              and not u.startswith(os.path.join("app", "services", "status.py"))]   # Connect's slots: below
    assert not unread, unread
    kinds |= {"known-import", "extract"}                              # `qt/importers.py`'s two `kind = …` classes
    kinds |= {kind for kind, _label in S._SLOTS.values()}             # `status.mirror_connect`'s recorded episodes
    missing = sorted(k for k in kinds if k not in P.KINDS)
    assert not missing, f"place these job kinds in app/services/phase.py KINDS: {missing}"
    assert all(c in P.CIRCLES or c is None for c in P.KINDS.values())
    assert P.KINDS["update"] is None and P.KINDS["backfill"] == P.JUNBAN         # Q7, Q2
    assert {P.KINDS[k] for k in ("generate", "indexer", "sentence-corpus")} == {P.SURASURA}


# --- the states ---------------------------------------------------------------------------------------------------- #
def _views(registry):
    return registry.snapshot()


def test_a_users_job_lights_its_circle_at_once_running_then_done_and_waiting_is_a_still_arc():
    registry = JobRegistry()
    gen = registry.submit("generate", "Generating", lambda j: None)
    queued = registry.submit("indexer", "Indexing your library", lambda j: None)       # waits for Generate
    got = P.read(_views(registry), now=gen.started_at)
    assert got[P.SURASURA].running and not got[P.SURASURA].waiting                     # running wins over waiting
    assert got[P.SURASURA].lines == ("Generating", "Indexing your library · waits for Generating")
    assert all(got[c] == P.IDLE for c in P.CIRCLES if c != P.SURASURA)
    queued.cancel()
    gen.finish()
    last = P.fold({}, _views(registry))
    got = P.read(_views(registry), last=last)
    assert not got[P.SURASURA].running and got[P.SURASURA].done == gen.id                # the tick's run
    assert got[P.SURASURA].last.state == "done"
    sync = registry.submit("anki-sync", "Updating known words from Anki", lambda j: None)
    held = registry.submit("known-import", "Importing known words", lambda j: None)      # the same resource: waits
    got = P.read(_views(registry))
    assert got[P.ANKI].running and got[P.ANKI].lines[1].startswith("Importing known words · waits for")
    sync.finish()
    got = P.read(_views(registry))
    assert got[P.ANKI].running and not got[P.ANKI].waiting                               # the import runs now
    held.finish()


def test_an_automatic_job_shows_only_after_a_second_and_one_never_shown_ends_with_no_tick():
    """Q6: a short automatic read doesn't flicker its circle."""
    registry = JobRegistry()
    job = registry.submit("arrivals-ja", "Counting new arrivals", lambda j: None, automatic=True)
    t0 = job.started_at
    got = P.read(_views(registry), now=t0 + 0.5)
    assert not got[P.ARRIVALS].running and got[P.ARRIVALS].lines == ("Counting new arrivals",)   # the hover knows
    assert P.reveal_at(_views(registry), t0 + 0.5) == t0 + P.REVEAL_S
    assert P.read(_views(registry), now=t0 + 1.0)[P.ARRIVALS].running
    assert P.reveal_at(_views(registry), t0 + 1.0) is None


def test_a_failure_stays_red_until_seen_or_the_next_run_and_a_job_that_ended_waiting_is_no_run():
    registry = JobRegistry()
    job = registry.submit("junban", "Re-ordering Anki", lambda j: None)
    job.finish(ok=False, message="Anki stopped answering")
    last = P.fold({}, _views(registry))
    got = P.read(_views(registry), last=last)
    assert got[P.JUNBAN].failed == "Anki stopped answering" and got[P.JUNBAN].done is None
    assert P.read(_views(registry), last=last, seen={job.id})[P.JUNBAN].failed is None       # hovered
    again = registry.submit("backfill", "Filling your cards", lambda j: None)               # the next run (Q2: 順)
    got = P.read(_views(registry), last=P.fold(last, _views(registry)))
    assert got[P.JUNBAN].running and got[P.JUNBAN].failed is None
    again.finish()
    last = P.fold(last, _views(registry))
    assert last[P.JUNBAN].id == again.id and P.read(_views(registry), last=last)[P.JUNBAN].failed is None
    # an episode's wait that went (recorded waiting, then ended) is no run: no Done, no tick
    wait = registry.record("mine-wait", "Connect", automatic=True, reason="Waiting to make its cards")
    wait.finish()
    assert P.MINER not in P.fold({}, _views(registry))
    assert P.fold(last, ()) is last                                                         # nothing newer: the same


def test_a_wait_on_you_is_amber_at_once_and_an_ended_one_stays_until_seen():
    """Q1: each on its own circle — not timed → Anki Miner, Anki closed → Anki."""
    registry = JobRegistry()
    registry.record("mine-wait", "Connect", automatic=True, reason="Not timed to its video",
                    needs="Not timed to its video")
    got = P.read(_views(registry))                                    # (automatic, but a wait on you shows at once)
    assert got[P.MINER].needs == "Not timed to its video" and not got[P.MINER].waiting
    sync = registry.submit("anki-sync", "Updating known words from Anki", lambda j: None)
    sync.finish(needs="Anki is closed")                               # Michi's ask: Anki closed during a sync
    last = P.fold({}, _views(registry))
    got = P.read(_views(registry), last=last)
    assert got[P.ANKI].needs == "Anki is closed" and got[P.ANKI].last.state == "needs" and got[P.ANKI].done is None
    assert P.read(_views(registry), last=last, seen={sync.id})[P.ANKI].needs is None


def test_presses_entries_and_the_windows_own_light_their_circles():
    presses = Presses()
    presses.get("known:sync").press()                                 # the count's click, before its sync exists
    presses.get("needs:ja:answer:x").press()                          # a Needs-you card's answer: no circle
    entries = (S.Entry("Command line (generate): it failed", "t1", False, "cli:generate"),
               S.Entry("Command line (status): it failed", "t2", False, "cli:status"),       # no circle: Needs you only
               S.Entry("Generate failed", "t3", True, "generate"))                           # seen already
    extra = {P.ARRIVALS: [("needs", "D:\\Anime can't be reached"), ("waiting", "Saving your moves…")]}
    got = P.read((), presses.live_ones(), entries, extra)
    assert got[P.ANKI].waiting and not got[P.ANKI].running
    assert got[P.SURASURA].failed == "Command line (generate): it failed"
    assert P.read((), (), entries, seen={("entry", entries[0].text, "t1")})[P.SURASURA].failed is None
    assert got[P.ARRIVALS].needs == "D:\\Anime can't be reached" and got[P.ARRIVALS].waiting
    assert got[P.ARRIVALS].lines == ("D:\\Anime can't be reached", "Saving your moves…")
    assert got[P.JUNBAN] == got[P.MINER] == P.IDLE
    assert P.press_circle("mine:ja:12") == P.MINER and P.press_circle(("known", 1)) == P.ANKI
    assert P.press_circle("generate") == P.SURASURA and P.press_circle("sources:refresh") == P.ARRIVALS
    assert P.press_circle("update:start") is None and P.press_circle("open:guide") is None


# --- the registry's waits on you (jobs.py) and Connect's episodes (status.py) ------------------------------------- #
def test_a_recorded_job_can_wait_on_its_owner_then_run_and_a_gated_ones_waits_stay_the_registrys():
    registry = JobRegistry()
    heard = []
    registry.subscribe(heard.append)
    job = registry.record("mine-wait", "Connect", reason="Waiting to make its cards")
    assert job.view().state == J.WAITING and job.view().reason == "Waiting to make its cards" and not job.view().needs
    job.hold("Not timed to its video", needs="Not timed to its video")
    assert (job.view().state, job.view().needs) == (J.WAITING, "Not timed to its video")
    told = len(heard)
    job.hold("Not timed to its video", needs="Not timed to its video")               # the same again: no news (S19)
    assert len(heard) == told
    job.resume()
    assert job.view().state == J.RUNNING and job.view().reason is None and job.view().needs is None
    gated = registry.submit("generate", "Generating", lambda j: None)
    gated.hold("mine")                                                                # not its owner's to hold
    assert gated.view().state == J.RUNNING
    gated.finish(needs="never")
    assert gated.view().needs == "never" and gated.view().state == J.DONE


def test_connects_waiting_episodes_are_recorded_by_class_and_the_mining_kind_stays_alone():
    from app.connect import feed, runner
    registry = JobRegistry()

    def look(*kinds):
        got = {i: feed.Item(feed.WAITING, feed.WORDS[feed.WAITING], runner.STOPPED_BY_YOU, i, 0, 0) if k == "stopped"
               else feed.Item(k, feed.WORDS[k], feed.WORDS[k], i, 0, 0) for i, k in enumerate(kinds)}
        S.mirror_connect(registry, feed.Feed(on=True, mining=frozenset(), items=got, line="", state="ok", unseen=0,
                                             updating=False))
        return {(v.kind, v.reason, v.needs) for v in registry.live()}

    assert look(feed.WAITING, feed.ASKED, feed.NOT_TIMED, feed.NO_VIDEO, feed.NO_VIDEO, feed.ANKI) == {
        (S.CONNECT_WAIT_KIND, f"{feed.WORDS[feed.WAITING]}; {feed.WORDS[feed.ASKED]}", None),
        (S.CONNECT_WAIT_KIND, f"{feed.WORDS[feed.NOT_TIMED]}; {feed.WORDS[feed.NO_VIDEO]} (2)",
         f"{feed.WORDS[feed.NOT_TIMED]}; {feed.WORDS[feed.NO_VIDEO]} (2)"),
        (S.CONNECT_ANKI_KIND, feed.WORDS[feed.ANKI], feed.WORDS[feed.ANKI])}
    assert registry.live(S.CONNECT_JOB_KIND) == ()                    # the close names mining alone (row 35)
    got = P.read(registry.snapshot())
    assert got[P.MINER].needs and got[P.ANKI].needs == feed.WORDS[feed.ANKI]
    assert look("stopped") == {(S.CONNECT_WAIT_KIND, f"{feed.WORDS[feed.WAITING]}; {feed.WORDS[feed.ASKED]}", None),
                               (S.CONNECT_WAIT_KIND, f"{feed.WORDS[feed.NOT_TIMED]}; {feed.WORDS[feed.NO_VIDEO]} (2)",
                                f"{feed.WORDS[feed.NOT_TIMED]}; {feed.WORDS[feed.NO_VIDEO]} (2)"),
                               (S.CONNECT_ANKI_KIND, feed.WORDS[feed.ANKI], feed.WORDS[feed.ANKI])}  # one look: kept
    assert look("stopped") == set()                   # two: gone — one you stopped waits for your Mine now (no job)
    assert P.MINER not in P.fold({}, registry.snapshot())               # ended waiting: no run, no tick
    look(feed.NOT_TIMED)
    S.mirror_connect(registry, None)                                   # the feed gone (a language switch): at once
    assert registry.live() == ()


def test_the_status_line_leaves_out_what_a_circle_shows_and_every_line_still_counts():
    """Q5: no job said twice; `lines` still name every one (the header's hairline runs while any does)."""
    registry = JobRegistry()
    status = S.StatusService(registry, reader=_Quiet())
    registry.submit("generate", "Generating", lambda j: None)
    registry.submit("update", "Downloading the update", lambda j: None)
    assert status.snapshot().bar_lines is None
    status.leave_out(lambda v: P.circle_of(v) is not None)
    snap = status.snapshot()
    assert snap.lines == ("Generating", "Downloading the update") and snap.bar_lines == ("Downloading the update",)
    status.leave_out(lambda v: 1 / 0)                                  # a faulty rule leaves every job on the line
    assert status.snapshot().bar_lines == ("Generating", "Downloading the update")


def test_needs_you_entries_carry_their_source():
    registry = JobRegistry()
    status = S.StatusService(registry, reader=_Quiet(), providers={"generate": lambda: "Generate failed: exit 1"})
    status.refresh()
    assert status.snapshot().needs_you[0].source == "generate"
    assert S.Entry("x", "t", False).source is None


class _Quiet:
    def changed(self):
        return False

    def newest_to_show(self):
        return None
