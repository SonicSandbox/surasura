"""The Finished importer's job (W3.2 S5; the window's spec 05 §5.8, A2 #77, RUNBOOK §1's *Finished* row, §5a N15):
*Add what you finished before…* — content the user finished before Surasura, put in Finished, dated *Earlier*. Qt-free,
Tk-free, pandas-free (the import guard); nothing here runs on the window's thread or opens the store.

    job = ImportJob(language, sources, writer, registry).start()     # a job in the registry; returns at once

- **A job** (`jobs.JobRegistry.submit`: kind `finished-import` — never two at once — label *Adding what you finished
  before*, `on_quit="cancel"`, cancellable): on its own thread it copies with `library_store.copy_into_finished` (each
  content file picked, or in a folder picked — the folder keeping its name — into `data/<lang>/Graduated/`, which the
  disk sync never walks; a file already in the library is listed where it is, never copied; nothing overwritten, the
  user's files left where they were), its progress the bar's (*Copying*, n of N), then hands every path to the writer
  in one command: `writer.import_finished(paths, copied=<the files this job copied>)` — journalled, queued while the
  store is busy, its Undo sending only those copies to the trash.
- **Again, nothing twice:** a copy that comes out the same bytes as a file already in Finished's folder (the same
  folder picked again: `name_1.ext` beside `name.ext`) goes to the trash and that file is listed instead, so the store
  sees rows it holds already and adds nothing (`Store.import_finished` skips a file in Finished).
- **Cancel** stops between files: no row is written, and the copies the job made go to the data folder's trash (30
  days, `library_store.trash_file`) — nothing half-imported, no `.part`. A store that can't be written refuses before
  anything is copied (E4); one that turns read-only after the copy sends the copies to the trash and says why. A copy
  that fails (a full disk, a file that can't be read) does the same, its job `failed` with the reason.
- **N15:** an imported file is never counted — `Store.text_lists()`' set-aside list (Finished is reference, W-1b),
  which the indexer's `token_store_lists` hands the token store: its sentences go to 例文 and the sentence dictionary,
  and its names to the name tables' evidence.

`outcome` after the job ends — the job waits for the writer's answer (S2): `imported` (saved) · `nothing` (nothing
new to add) · `cancelled` · `refused` (the store can't be written, before the copy or as the command landed: its
copies in the trash) · `failed` (a copy, or the store's command: the same) · `pending` (Stop pressed while the store
saved it: the writer's now — the outcome follows the writer's answer when it comes, W3.2 H T3) · `stopped` (the writer
stopped first — the quit, a language switch: the command stays in its journal and lands at the next start, T2);
`paths` / `copied` what it handed on. A copy that can't go to the trash is listed (imported as it stands), never left
hidden in Finished's folder, which no sync walks.
"""
import filecmp
import os
import re
import threading

KIND = "finished-import"
LABEL = "Adding what you finished before"
STEP = "Copying"
WAIT_S = 0.1                                  # the job asks whether it was cancelled this often while the store saves
_NUMBERED = re.compile(r"^(.*)_(\d+)$")       # `copy_into_finished`'s taken-name form: name_1.ext


def _ls():
    from app import library_store
    return library_store


class ImportJob:
    def __init__(self, language, sources, writer, registry, data_dir=None, on_done=None, label=LABEL):
        self.language = language
        self.sources = [os.fspath(s) for s in sources]
        self.writer = writer
        self.registry = registry
        self.data_dir = data_dir
        self.on_done = on_done                  # on_done(job): on the job's thread, after it ended
        self.label = label
        self.job = None
        self.outcome = None
        self.paths, self.copied = [], []
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()           # the job's end and the writer's late answer (T3)

    def start(self):
        """Ask the registry for the job (it starts at once unless another import runs). -> the Job, or None when the
        store can't be written (E4: refused before anything is copied)."""
        if not self.writer.can_write():
            self.outcome = "refused"
            return None
        self.job = self.registry.submit(KIND, self.label, start=self._begin, cancel=self._cancel, on_quit="cancel")
        return self.job

    def cancel(self):
        return self.job.cancel() if self.job is not None else False

    def wait(self, timeout=None):
        """(A worker's or a test's call.) True once the job's thread ended."""
        if self.job is not None and not self.job.wait(timeout):
            return False
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
            return not thread.is_alive()
        return True

    # --- the job's side -------------------------------------------------------------------------------------- #
    def _begin(self, job):
        self._thread = threading.Thread(target=self._run, args=(job,), name=f"finished-import-{self.language}",
                                        daemon=True)
        self._thread.start()

    def _cancel(self, job):
        self._stop.set()                        # a job cancelled before it started never runs `_run`
        if job.state == "done" and self.outcome is None:
            self.outcome = "cancelled"

    def _run(self, job):
        ls = _ls()
        data_dir = self.data_dir
        made = []
        try:
            if data_dir is None:
                from app.path_utils import get_data_path
                data_dir = get_data_path(self.language)
            if not self.writer.can_write():
                self._end(job, "refused", ok=False, message=self.writer.reason())
                return
            before = _finished_files(data_dir)
            try:
                out = ls.copy_into_finished(data_dir, self.sources,
                                            progress=lambda done, total: job.progress(STEP, done, total),
                                            cancel=self._stop.is_set)
            except BaseException:
                made = [rel for key, rel in _finished_files(data_dir).items() if key not in before]   # its copies
                raise
            made = _made(out, before)
            paths, copied = self._same_as_before(ls, data_dir, out, made, before)
            made = copied
            if self._stop.is_set():
                left, made = self._trash(ls, data_dir, made), []
                self._list_left(data_dir, left)
                self._end(job, "cancelled", cancelled=True)
                return
            if not paths:
                self._end(job, "nothing")
                return
            self.paths = [os.path.join(data_dir, *p.split("/")) for p in paths]
            self.copied = [os.path.join(data_dir, *p.split("/")) for p in copied]
            landed = threading.Event()
            answer = {}
            if self.writer.import_finished(self.paths, copied=self.copied, label=self.label,
                                           answer=lambda cmd: self._answered(cmd, answer, landed)) is None:
                self._trash(ls, data_dir, made)
                self.paths, self.copied = [], []
                self._end(job, "refused", ok=False, message=self.writer.reason())
                return
            made = []                               # queued: the copies are the writer's now (never trashed here)
            stopped = getattr(self.writer, "stopped", None)
            while not landed.wait(WAIT_S):          # the writer's answer (S2); a quit meanwhile leaves it journalled
                if self._stop.is_set() or (stopped is not None and stopped()):
                    break                           # T2: a writer that stopped answers nothing more
            with self._lock:
                if not landed.is_set():             # T3: Stop pressed, or the writer stopped: the writer's answer, when
                    outcome = "stopped" if stopped is not None and stopped() else "pending"   # it comes, decides
                    self._end(job, outcome, completed=True)
                    return
            if not answer.get("saved"):             # refused or failed as it landed: the writer trashed
                self.paths, self.copied = [], []    # the copies, nothing was written
                refused = "refused" in answer
                self._end(job, "refused" if refused else "failed", ok=False,
                          message=answer.get("refused") if refused else answer.get("failed"))
                return
            self._end(job, "imported", completed=self._stop.is_set())
        except BaseException as e:
            self._list_left(data_dir, self._trash(ls, data_dir, made))
            self._end(job, "failed", ok=False, message=f"{e}")
            if not isinstance(e, Exception):
                raise

    def _same_as_before(self, ls, data_dir, out, made, before):
        """(paths, copied) after the copy: a copy that holds the same bytes as a file already in Finished's folder under
        the name it was given a number beside (`name_1.ext` and `name.ext`, or an earlier `name_k.ext`) goes to the
        trash and that file is listed in its place."""
        made_keys = {ls.path_key(r) for r in made}
        paths, copied = [], []
        for rel in out:
            if ls.path_key(rel) not in made_keys:
                paths.append(rel)
                continue
            same = _earlier_twin(ls, data_dir, rel, before)
            if same is None or self._trash(ls, data_dir, [rel]):
                paths.append(rel)                   # (a twin that couldn't go to the trash is listed as it
                copied.append(rel)                  # stands — never left hidden in Finished's folder)
            elif same not in paths:
                paths.append(same)
        return paths, copied

    @staticmethod
    def _trash(ls, data_dir, rels):
        """Each copy to the data folder's trash. -> the rels that couldn't go (the caller lists them)."""
        left = []
        for rel in rels:
            try:
                ls.trash_file(data_dir, rel)
            except OSError as e:
                print(f"Finished import: a copy couldn't go to the trash: {e!r}")
                left.append(rel)
        return left

    def _list_left(self, data_dir, left):
        """Copies that couldn't go to the trash (a cancel, a failure) are listed — imported as they stand, with
        their Undo — never left in Finished's folder, which no sync walks. A store that can't take them: said."""
        if not left:
            return
        full = [os.path.join(data_dir, *rel.split("/")) for rel in left]
        try:
            if self.writer.import_finished(full, copied=full, label=self.label) is not None:
                return
        except Exception as e:
            print(f"Finished import: copies that couldn't go to the trash couldn't be listed: {e!r}")
            return
        print(f"Finished import: {len(left)} copies that couldn't go to the trash stay in Finished's folder unlisted")

    def _answered(self, cmd, answer, landed):
        """(The writer's thread.) Its answer for the import: the job's outcome when the job ended before it came
        (T3: Stop pressed meanwhile — never *imported* for a command the writer then refused)."""
        with self._lock:
            answer.update(cmd)
            landed.set()
            if self.outcome in ("pending", "stopped"):
                if cmd.get("saved"):
                    self.outcome = "imported"
                else:
                    self.outcome = "refused" if "refused" in cmd else "failed"
                    self.paths, self.copied = [], []

    def _end(self, job, outcome, ok=True, message=None, cancelled=False, completed=False):
        self.outcome = outcome
        job.finish(ok=ok, message=message, cancelled=cancelled, completed=completed)
        if self.on_done is not None:
            try:
                self.on_done(self)
            except Exception as e:
                print(f"Finished import: its listener failed: {e!r}")


def _finished_files(data_dir):
    """{path_key: rel} of every file under Finished's folder now (what the job's copies are told apart from)."""
    ls = _ls()
    root = os.path.join(data_dir, ls.GRADUATED_FOLDER)
    out = {}
    for folder, _dirs, files in os.walk(root):
        for name in files:
            rel = ls.library_rel(data_dir, os.path.join(folder, name))
            if rel is not None:
                out[ls.path_key(rel)] = rel
    return out


def _made(out, before):
    """The paths of `out` this job copied: in Finished's folder (every copy lands there), not there before it ran — a
    file listed where it already was (anywhere in the library) is never one."""
    ls = _ls()
    inside = ls.GRADUATED_FOLDER.lower() + "/"
    return [r for r in out if r.lower().startswith(inside) and ls.path_key(r) not in before]


def _earlier_twin(ls, data_dir, rel, before):
    """The file in Finished's folder before the job that `rel` (a copy named `name_k.ext`) is byte for byte, or None."""
    stem, ext = os.path.splitext(rel)
    m = _NUMBERED.match(stem)
    if m is None:
        return None
    base, k = m.group(1), int(m.group(2))
    full = os.path.join(data_dir, *rel.split("/"))
    for candidate in [f"{base}{ext}"] + [f"{base}_{j}{ext}" for j in range(1, k)]:
        key = ls.path_key(candidate)
        if key not in before:
            continue
        try:
            if filecmp.cmp(os.path.join(data_dir, *before[key].split("/")), full, shallow=False):
                return before[key]
        except OSError:
            continue
    return None
