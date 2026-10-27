"""The arrivals worker's client (E2.2 D10, K9; the window's spec 04 §4.1): asks the warm worker process
(`app_entry.py arrivals-worker`, `app/arrivals_worker.py`) for an arrival's estimate and pick, from any thread, without
waiting on it.

    worker = ArrivalsWorker(registry, "ja")
    worker.estimate(path, placed=(), callback=lambda answer: …)     # returns the request's id at once
    worker.stop()                                                   # the window closing (the registry's quit does it too)

The process starts on first use, as a job in the registry (kind `arrivals-<language>`, automatic, `on_quit="cancel"`: it
shares nothing, so it never waits for another job — a Japanese and a Chinese worker run side by side — and the window's
quit ends it). What the worker prints (a crash's traceback) goes to `arrivals-worker-<language>.log` in the logs folder,
started again when it passes `LOG_CAP`. Requests are written and answers read on
the client's own threads; each answer goes to its request's callback (or `on_answer`) on the reader thread — a window
posts it to its own queue. The worker ends by itself after its idle minutes: the next request starts it again, and a
request the ending worker never answered is sent once more to the new one. A worker that crashed answers each request
it held with {"id", "error"}. Nothing here imports Qt, Tk, pandas or the analyzer (the import guard).
"""
import itertools
import json
import os
import queue
import subprocess
import sys
import threading
import time

from app.services import jobs as jobs_module

KIND = "arrivals"               # the job's kind is this and the language: `kind_of`
LABEL = "Counting new arrivals"
GRACE = 2.0                     # s a worker asked to stop has to end before it is stopped
STUCK = 120.0                   # s a request may wait for its answer before the worker is taken as stuck and ended
LOG_CAP = 1 << 20               # bytes: a worker's log past this starts again (the last one kept as .old)


def kind_of(language):
    """The registry kind of `language`'s worker: one per language, never two of one (`jobs.RESOURCES`)."""
    return f"{KIND}-{language}"


def _log_file(language):
    """The worker's stderr: its log in the logs folder, opened to append (DEVNULL when it can't be)."""
    try:
        from app.path_utils import get_local_data_path
        folder = os.path.join(get_local_data_path(), "logs")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"arrivals-worker-{language}.log")
        try:
            if os.path.getsize(path) > LOG_CAP:
                os.replace(path, path + ".old")
        except OSError:
            pass
        return open(path, "ab")
    except Exception:
        return subprocess.DEVNULL


def command_line(language, args=()):
    """The worker's process command: the frozen app's own verb, or app_entry.py from source."""
    from app.path_utils import is_frozen
    verb = ["arrivals-worker", "--headless", "--language", language] + list(args)
    if is_frozen():
        return [sys.executable] + verb
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return [sys.executable, os.path.join(root, "app_entry.py")] + verb


class ArrivalsWorker:
    """One warm worker for one language. `args`: the analyzer's arguments of the Generate the window runs (default:
    the worker reads them from settings, as the window's Generate does); `on_answer(answer)`: for requests asked
    without a callback; `command`: the child's command line (a test's)."""

    def __init__(self, registry, language, args=(), on_answer=None, command=None):
        self.registry = registry
        self.language = language
        self.args = list(args)
        self.on_answer = on_answer
        self._command = command
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._pending = {}              # id -> [request, callback, times sent again]
        self._outbox = queue.Queue()    # ids to write, in the order asked
        self._job = None                # the live job (True while it is being made)
        self._proc = None
        self._closed = False

    # --- asking ----------------------------------------------------------------------------------------------------- #
    def estimate(self, path, placed=(), callback=None, piece=None):
        """Ask for the estimate of the file at `path` (`placed`: the files placed since the plan, paths or
        {"path", "tier", "before", "after"}; or, with `piece` — a show's paths, one tuple its files' asks share — an
        index: the piece's first `placed` files, A4: held as the index and expanded only as it is written, so the
        worker reads the same request and keeps its answer under the same key). -> the request's id, at once."""
        if isinstance(placed, int) and not isinstance(placed, bool):
            return self._ask({"op": "estimate", "path": os.fspath(path), "placed": placed, "piece": piece or ()},
                             callback)
        placed = [os.fspath(p) if not isinstance(p, dict) else dict(p, path=os.fspath(p["path"])) for p in placed]
        return self._ask({"op": "estimate", "path": os.fspath(path), "placed": placed}, callback)

    def reload(self, callback=None):
        """Build the view again (it does so by itself when the plan or the known words change)."""
        return self._ask({"op": "reload"}, callback)

    def stats(self, callback=None):
        """What the worker has worked out, and its memory."""
        return self._ask({"op": "stats"}, callback)

    def stop(self):
        """End the worker (and answer what it still held with an error); no request starts it again."""
        with self._lock:
            self._closed = True
            job = self._job
        if job is not None and job is not True:
            job.cancel()
        else:
            self._fail_all("the arrivals worker was stopped")

    @property
    def running(self):
        with self._lock:
            return self._proc is not None

    # --- inside ----------------------------------------------------------------------------------------------------- #
    def _ask(self, request, callback):
        with self._lock:
            rid = next(self._ids)
            closed = self._closed
            if not closed:
                self._pending[rid] = [dict(request, id=rid), callback, 0]
                self._outbox.put(rid)
        if closed:
            self._deliver(callback, {"id": rid, "op": request.get("op"), "error": "the arrivals worker was stopped"})
            return rid
        self._ensure()
        return rid

    def _ensure(self):
        """A live worker job: made when there is none (the registry starts it at once: it shares nothing)."""
        with self._lock:
            if self._job is not None or self._closed:
                return
            self._job = True
        job = self.registry.submit(kind_of(self.language), LABEL, start=self._begin, cancel=self._cancel, automatic=True,
                                   on_quit="cancel")
        with self._lock:
            if self._job is True:
                self._job = job
            closed = self._closed
        if closed:                                  # `stop` came while it was being made: no worker after it
            job.cancel()

    def _begin(self, job):
        with self._lock:
            self._job = job
        threading.Thread(target=self._run, args=(job,), name="arrivals-writer", daemon=True).start()

    def _run(self, job):
        """Start the child, write the requests as they come, and once it has ended settle what it left."""
        try:
            from app.path_utils import build_subprocess_env, is_frozen
            command = self._command or command_line(self.language, self.args)
            log = _log_file(self.language)
            try:
                proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                                        env=build_subprocess_env(is_frozen()),
                                        creationflags=0x08000000 if sys.platform == "win32" else 0)  # CREATE_NO_WINDOW
            finally:
                if log is not subprocess.DEVNULL:
                    log.close()                     # the child holds its own handle
        except Exception as e:                      # it can't start: each request waiting is answered, none re-sent
            self._ended(job, None, set(), f"The arrivals worker couldn't start: {e}")
            return
        with self._lock:
            self._proc = proc
            stop = self._closed or job.cancelled
        job.started_process(getattr(proc, "pid", None))     # the update's wait list: this job's row alone
        if stop:
            _end_soon(proc)
        sent, sent_at, done, stuck = set(), {}, threading.Event(), False
        threading.Thread(target=self._read, args=(proc, done), name="arrivals-reader", daemon=True).start()
        while not done.is_set():
            try:
                rid = self._outbox.get(timeout=0.2)
            except queue.Empty:
                rid = None
            now = time.monotonic()
            with self._lock:
                entry = self._pending.get(rid) if rid is not None else None
                waiting = [t for r, t in sent_at.items() if r in self._pending]
            if waiting and now - min(waiting) > STUCK:
                stuck = True                        # alive but answering nothing: ended, its requests answered
                proc.kill()
                break
            if entry is None:
                continue
            sent.add(rid)                           # before writing: a worker that ends now is asked again after
            sent_at[rid] = now
            try:
                proc.stdin.write((json.dumps(_written(entry[0]), ensure_ascii=False) + "\n").encode("utf-8"))
                proc.stdin.flush()
            except (OSError, ValueError):
                break                               # it is ending: what it held is settled below
        done.wait()
        self._ended(job, proc.returncode, sent, "The arrivals worker stopped answering." if stuck else None)

    def _read(self, proc, done):
        try:
            for raw in proc.stdout:
                try:
                    answer = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue
                if not isinstance(answer, dict):
                    continue
                with self._lock:
                    entry = self._pending.pop(answer.get("id"), None)
                if entry is not None:
                    self._deliver(entry[1], answer)
        except (OSError, ValueError):
            pass
        finally:
            proc.wait()
            done.set()

    def _ended(self, job, returncode, sent, message=None):
        """The child ended: its job finishes; a request it took and never answered is sent once more to a new worker
        after an ordinary end (idle, its input closed), else answered with an error."""
        with self._lock:
            self._proc = None
            self._job = None
            stopping = self._closed or job.cancelled
            lost = [rid for rid in sorted(sent) if rid in self._pending]
            retry = []
            for rid in lost:
                entry = self._pending[rid]
                if returncode == 0 and not stopping and entry[2] < 1:
                    entry[2] += 1
                    retry.append(rid)
        ok = returncode == 0 or stopping
        if message is None and not ok:
            message = f"The arrivals worker stopped (exit code {returncode})."
        job.finish(ok=ok, message=None if ok else message, cancelled=job.cancelled)
        if stopping:
            self._fail_all("the arrivals worker was stopped")
            return
        if returncode is None:                      # it never started: every request waiting gets the reason; the
            self._fail_all(message)                 # next request tries again (never a loop of starts)
            return
        for rid in lost:
            if rid not in retry:
                self._fail(rid, message or "the arrivals worker ended before answering")
        for rid in retry:
            self._outbox.put(rid)
        with self._lock:
            waiting = bool(self._pending)
        if waiting:
            self._ensure()

    def _cancel(self, job):
        """The registry's cancel (the window quitting, or `stop`): close its input — it ends — and stop it if it
        hasn't after GRACE seconds. Returns at once."""
        with self._lock:
            self._closed = True
            proc = self._proc
        if proc is None:
            if job.state == jobs_module.DONE:           # ended before it started: nothing runs
                with self._lock:
                    self._job = None
                self._fail_all("the arrivals worker was stopped")
            return                                      # starting: `_run` sees it and ends it as below
        _end_soon(proc)

    def _fail(self, rid, message):
        with self._lock:
            entry = self._pending.pop(rid, None)
        if entry is not None:
            self._deliver(entry[1], {"id": rid, "op": entry[0].get("op"), "error": message})

    def _fail_all(self, message):
        with self._lock:
            ids = list(self._pending)
        for rid in ids:
            self._fail(rid, message)

    def _deliver(self, callback, answer):
        callback = callback or self.on_answer
        if callback is None:
            return
        try:
            callback(answer)
        except Exception as e:                          # a listener's fault never stops the reader
            print(f"Arrivals: a listener failed: {e}")


def _written(request):
    """A request as the worker reads it: an index into its piece (`estimate(..., placed=k, piece=)`) becomes the
    piece's first k paths — the same request the list form writes."""
    placed = request.get("placed")
    if not isinstance(placed, int) or isinstance(placed, bool):
        return request
    out = {k: v for k, v in request.items() if k != "piece"}
    out["placed"] = [os.fspath(p) for p in tuple(request.get("piece") or ())[:placed]]
    return out


def _end_soon(proc):
    """Close the worker's input (it ends), and stop it if it hasn't after GRACE seconds. Returns at once."""
    _close(proc.stdin)

    def later():
        try:
            proc.wait(timeout=GRACE)
        except subprocess.TimeoutExpired:
            proc.kill()
    threading.Thread(target=later, name="arrivals-stop", daemon=True).start()


def _close(stream):
    try:
        stream.close()
    except (OSError, ValueError):
        pass
