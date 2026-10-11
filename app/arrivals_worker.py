"""The warm arrivals worker (E2.2 D10–D11, K9): `app_entry.py arrivals-worker --headless --language <ja|zh> [analyzer
arguments]` — one process per language that keeps the tokenizer, the last Generate's plan and its view (`arrivals.View`,
`arrivals.Gates`) loaded, and answers each arrival in one pass, so a drag never waits on a tokenizer or on Python's lock
in the window (the window's spec 04 §4.1).

JSON lines on stdin, one answer line each on stdout (UTF-8):

    {"id": 1, "op": "estimate", "path": "<file>", "placed": [<file> | {"path", "tier", "before", "after"}, …]}
        -> {"id": 1, "op": "estimate", "path", "words", "n_new_top", "n_new_after_show", "after", "known_pct",
            "known", "counted", "exact", "moved", "record", "pick", "cached"}     (`arrivals.estimate`, `pick_words`)
           with no plan for this language yet: {"exact": false, "reason": "no-plan", "known_pct", …} (the numbers a
           plan isn't needed for)
    {"id": 2, "op": "reload"}  -> the view built again          {"op": "stats"} -> what it has worked out, its memory
    {"op": "quit"}             -> it answers, then ends

`placed`: the files placed since the plan, in the order placed — each counted in with this one by the gates, and in
the order *N new* reads (a bare path, or a tier of None: after its folder's last item, else the top of NOW; anchors are
data-folder-relative ids, as the plan names its files). A request it can't answer gets {"id", "error"}.

It ends when its input closes (its parent died), on "quit", and after `IDLE_SECONDS` without a request (Sonic, E2.2-2;
`--idle-seconds` for a test). It reloads the view by itself when the plan file's run signature or the known words
change. An answer is kept by (path, mtime, size, the plan's run signature, the known words' signature, what was
placed): asked again, nothing is worked out again (S19). **It writes nothing** — not the token store (the store is
opened only to build the view, and closed: the arrival is read here, `arrivals.read`), not results/, no known-words
cache (`read_known_words(keep=False)`).
"""
import argparse
import json
import os
import queue
import sys
import threading
from collections import OrderedDict

IDLE_SECONDS = 120              # Sonic (E2.2-2): "could even be after 1-2 minutes"
KEEP = 64                       # answers (and arrivals read) kept, newest last
# A line each language's warm-up reads through every step of an answer (`Worker._warm_up`).
SAMPLE = {"ja": "今日は駅前の本屋で、友達と待ち合わせをしたんだけど、結局来なかった。", "zh": "今天我在车站前的书店等朋友，结果他没来。"}


def _memory():
    """This process's memory, MB: {"private_mb", "working_set_mb"} (Windows), else {"max_rss_mb"} or None."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                    (name, ctypes.c_size_t) for name in (
                        "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                        "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage",
                        "PrivateUsage")]
            k = ctypes.WinDLL("kernel32")
            k.GetCurrentProcess.restype = wintypes.HANDLE
            psapi = ctypes.WinDLL("psapi")
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
            pmc = PMC()
            pmc.cb = ctypes.sizeof(PMC)
            if psapi.GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
                return {"private_mb": round(pmc.PrivateUsage / 1048576, 1),
                        "working_set_mb": round(pmc.WorkingSetSize / 1048576, 1)}
            return None
        import resource
        return {"max_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)}
    except Exception:
        return None


class Worker:
    """The worker's state: the warm view of the last Generate (built on first need, again when the plan or the known
    words change), and the answers kept."""

    def __init__(self, language, argv=()):
        from app import analyzer, settings_manager
        self.language = language
        settings = settings_manager.load_settings()
        if not argv:                                # the Generate the dashboard and the window run
            from app import run_args
            argv = run_args.analyzer_args(settings, language)[1:]
        self.args = analyzer.parse_analysis_args([f"--language={language}"] + list(argv))
        self.send_grammar = bool(settings.get("connect_send_grammar", True))
        self.plan_path = os.path.join(analyzer.RESULTS_DIR, analyzer.PLAN_FILE)
        self.warm = None                            # {"view", "gates", "order", "listed", "signature", ...}
        self.plan_stat = self.known_sig = None
        self.reads, self.answers = OrderedDict(), OrderedDict()
        self.counts = {"views": 0, "reads": 0, "estimates": 0}

    # --- the view ------------------------------------------------------------------------------------------------ #
    def _known_file(self):
        from app.path_utils import get_user_files_path
        return os.path.join(get_user_files_path(self.language), "KnownWord.json")

    def current(self, force=False):
        """The warm state for the plan and known words as they stand (built again only when either changed)."""
        from app import plan_engine, token_index, zh_script
        try:
            st = os.stat(self.plan_path)
            plan_stat = (st.st_mtime_ns, st.st_size)
        except OSError:
            plan_stat = None
        known_sig = token_index.known_signature(self._known_file(),
                                                zh_script.effective(self.language, self.args.zh_script))
        if not force and self.warm is not None and plan_stat == self.plan_stat and known_sig == self.known_sig:
            return self.warm
        plan = None
        if plan_stat is not None:
            try:
                plan = plan_engine.load(self.plan_path)
            except plan_engine.PlanError:
                plan = None
            if plan is not None and plan.header.get("language") != self.language:
                plan = None
        signature = plan.header.get("run_signature") if plan is not None else None
        if (not force and self.warm is not None and known_sig == self.known_sig
                and signature == self.warm["signature"]):
            self.plan_stat = plan_stat              # the same run's plan, written again: the view holds
            return self.warm
        self.warm = self._build(plan)
        self.plan_stat, self.known_sig = plan_stat, known_sig
        return self.warm

    def _build(self, plan):
        """The view of `plan` (None: no plan for this language — a bare view, its known words alone)."""
        from app import analyzer, arrivals, names, plan_engine, settings_manager, token_index
        analyzer.LOGIC.update(settings_manager.load_settings().get("logic", {}))      # as the Generate read them
        tokenizer = self.warm["view"].tokenizer if self.warm is not None else None
        self.counts["views"] += 1
        self.reads.clear()
        self.answers.clear()
        if plan is None:
            bare = plan_engine.Plan({"floor": 0, "run_signature": None, "phrase_entries": []}, [], [], [], [], [])
            view = arrivals.View.build(self.language, bare, None, self.args, tokenizer=tokenizer)
            return {"view": view, "gates": None, "order": None, "listed": {}, "signature": None}
        store = token_index.open_reader(self.language)     # read only: no schema made, no damaged file rebuilt
        try:
            view = arrivals.View.build(self.language, plan, store, self.args, tokenizer=tokenizer)
            if self.language == "ja":
                names.use_library_tables(view.names_tables, pin=True)     # never re-read while warm
            gates = arrivals.Gates.build(view, store) if store is not None else None     # None: never "exact"
        finally:
            if store is not None:
                store.close()                       # the arrivals are read here, never through the store
        view.store = None
        order = arrivals.Order(plan)
        # The plan's tables only from here on: its per-file lines (most of its memory) are read into `order`.
        view.plan = plan_engine.Plan(plan.header, plan.files, plan.keys, plan.rows, plan.ties, None, plan.spell)
        warm = {"view": view, "gates": gates, "order": order, "listed": self._listed(),
                "signature": plan.header.get("run_signature")}
        try:
            self._warm_up(warm)
        except Exception as e:                      # only a head start: the first arrival loads what this didn't
            print(f"arrivals worker: the warm-up failed: {e}", file=sys.stderr)
        return warm

    def _warm_up(self, warm):
        """One short line through every step an answer takes — reading it as the store would, the record, the gates,
        the pick over a cue — so the tables each step loads on first use are loaded with the view (the cold start pays
        for them, not the first arrival). Reads no file, writes nothing."""
        from app import arrivals, cues
        view, text = warm["view"], SAMPLE[self.language]
        sentences, names_record = arrivals.read_text(view, text)
        rec = arrivals.record(sentences, view, names=names_record)
        if warm["gates"] is not None:
            warm["gates"].check([rec])
        arrivals.estimate(view, warm["gates"], warm["order"], rec)
        arrivals.pick_cues(view, cues.Cues([cues.Cue(0, 0, 3000, text, 0, False, True)]), warm["listed"],
                           self.send_grammar)

    def _listed(self):
        """{(Word, Reading): its place} on the last Generate's list (its priority CSV, as Connect's pick reads it)."""
        import csv
        from app import analyzer
        out = {}
        try:
            with open(os.path.join(analyzer.RESULTS_DIR, "priority_learning_list.csv"), encoding="utf-8-sig",
                      newline="") as f:
                for row in csv.DictReader(f):
                    out.setdefault((row.get("Word", ""), row.get("Reading", "")), len(out))
        except (OSError, ValueError, csv.Error) as e:   # unreadable or damaged: the pick ranks by nothing listed
            print(f"arrivals worker: the list couldn't be read: {e}", file=sys.stderr)
            out = {}
        return out

    # --- the answers --------------------------------------------------------------------------------------------- #
    def _key(self, path, warm):
        st = os.stat(path)
        return (os.path.normcase(os.path.abspath(path)), st.st_mtime_ns, st.st_size, warm["signature"],
                self.known_sig)

    def _read(self, path, warm):
        """(record, pick) of one arrival, kept by its key."""
        from app import arrivals
        key = self._key(path, warm)
        held = self.reads.get(key)
        if held is not None:
            self.reads.move_to_end(key)
            return key, held
        view = warm["view"]
        sentences, names_record = arrivals.read(view, path)
        rec = arrivals.record(sentences, view, path, names=names_record)
        picked = None
        if warm["order"]:
            try:
                picked = arrivals.pick_words(view, path, warm["listed"], self.send_grammar)
            except Exception as e:                  # a subtitle the pick can't read: the estimate still answers
                print(f"arrivals worker: no pick for {os.path.basename(path)}: {e}", file=sys.stderr)
        self.counts["reads"] += 1
        self.reads[key] = (rec, picked)
        while len(self.reads) > KEEP:
            self.reads.popitem(last=False)
        return key, (rec, picked)

    def _rel(self, path):
        from app.path_utils import get_data_path
        try:
            rel = os.path.relpath(os.path.abspath(path), os.path.abspath(get_data_path(self.language)))
        except ValueError:                          # another drive: not in the library's data folder
            return None
        if rel == os.pardir or rel.startswith(os.pardir + os.sep) or os.path.isabs(rel):
            return None
        return rel.replace("\\", "/")

    def estimate(self, request):
        from app import arrivals
        path = request["path"]
        warm = self.current()
        placed_in = []
        for entry in request.get("placed") or ():
            entry = {"path": entry} if isinstance(entry, str) else dict(entry)
            placed_in.append(entry)
        key, (rec, picked) = self._read(path, warm)
        placed, keys = [], []
        for entry in placed_in:
            p_key, (p_rec, _p) = self._read(entry["path"], warm)
            keys.append((p_key, entry.get("tier"), entry.get("before"), entry.get("after")))
            placed.append({"id": self._rel(entry["path"]) or entry["path"], "record": p_rec,
                           "tier": entry.get("tier"), "before": entry.get("before"), "after": entry.get("after")})
        answer_key = (key, tuple(keys))
        held = self.answers.get(answer_key)
        if held is not None:
            self.answers.move_to_end(answer_key)
            return dict(held, cached=True)
        if warm["order"] is None:
            total, baseline = rec["prog"][0], rec["prog"][1]
            out = {"words": [], "n_new_top": None, "n_new_after_show": None, "after": None,
                   "known_pct": round(baseline / total * 100, 2) if total else None, "known": baseline,
                   "counted": total, "exact": False, "moved": [], "reason": "no-plan", "record": None, "pick": None}
        else:
            out = arrivals.estimate(warm["view"], warm["gates"], warm["order"], rec, self._rel(path), placed)
            out["pick"] = picked
        self.counts["estimates"] += 1
        self.answers[answer_key] = out
        while len(self.answers) > KEEP:
            self.answers.popitem(last=False)
        return dict(out, cached=False)

    def answer(self, request):
        op = request.get("op")
        out = {"id": request.get("id"), "op": op}
        if op == "estimate":
            out["path"] = request.get("path")
            out.update(self.estimate(request))
        elif op == "reload":
            warm = self.current(force=True)
            out["plan"] = warm["signature"] is not None
        elif op == "stats":
            out.update(self.counts, memory=_memory(), plan=self.warm is not None and self.warm["signature"] is not None)
        elif op != "quit":
            out["error"] = f"unknown op {op!r}"
        return out


def main(argv=None):
    """The worker: its loop, then the process ends — exit 0 when its input closed, on "quit", or idle. Ended with
    `os._exit`: the thread reading stdin is blocked in a read nothing can interrupt, and an interpreter shutting down
    around it aborts (the store is closed and every answer flushed by then: nothing is left to tidy)."""
    code = 1
    try:
        code = _loop(argv)
    except BaseException:
        import traceback
        traceback.print_exc()                       # to stderr (the client's log), then exit 1
    finally:
        try:
            sys.stderr.flush()
        except (OSError, ValueError):
            pass
        os._exit(code)


def _loop(argv):
    """-> the exit code (0: its input closed, "quit", or idle)."""
    parser = argparse.ArgumentParser(prog="arrivals-worker", add_help=False)
    parser.add_argument("--language", required=True, choices=("ja", "zh"))
    parser.add_argument("--idle-seconds", type=float, default=IDLE_SECONDS)
    ours, rest = parser.parse_known_args(sys.argv[1:] if argv is None else argv)
    stream = sys.stdout                             # held: the stream app_entry made, closed if it were let go
    out = stream.buffer
    sys.stdout = sys.stderr                         # anything the analyzer prints stays off the answer stream
    lines = queue.Queue()

    def pump():
        try:
            for raw in sys.stdin.buffer:
                lines.put(raw)
        except (OSError, ValueError):
            pass
        lines.put(None)                             # the input closed: the parent is gone
    threading.Thread(target=pump, name="arrivals-stdin", daemon=True).start()

    def send(answer):
        out.write((json.dumps(answer, ensure_ascii=False) + "\n").encode("utf-8"))
        out.flush()

    worker = Worker(ours.language, rest)
    try:
        worker.current()                            # warm before the first request (cold start)
    except Exception as e:
        print(f"arrivals worker: the view couldn't be built yet: {e}", file=sys.stderr)
    while True:
        try:
            raw = lines.get(timeout=ours.idle_seconds)
        except queue.Empty:
            return 0                                # idle: memory back to the system
        if raw is None:
            return 0
        try:
            request = json.loads(raw.decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("a request is a JSON object")
        except (ValueError, UnicodeDecodeError) as e:
            send({"id": None, "error": f"bad request: {e}"})
            continue
        try:
            answer = worker.answer(request)
        except Exception as e:                      # one arrival it can't read never ends the worker
            answer = {"id": request.get("id"), "op": request.get("op"), "error": f"{e.__class__.__name__}: {e}"}
        try:
            send(answer)
        except (OSError, ValueError):
            return 0                                # nobody reads the answers any more
        if request.get("op") == "quit":
            return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.exit(main())
