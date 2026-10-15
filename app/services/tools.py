"""The child runner (W3.4 row 1; the RUNBOOK's *rules for every row*): a tool the window starts — the sentence
dictionary's export, an importer, the extractor — runs as a child process, as a job in the window's registry.

`run(registry, kind, label, argv, …)` submits a **gated** job of `kind` (`jobs.RESOURCES` names what it uses: the
export's `sentence-corpus` waits for Generate and the indexer, never two of a kind; the update's hold keeps it back while
an update waits for Surasura's programs). When the registry starts it, a thread of its own starts the child with
`path_utils.build_subprocess_env` (UTF-8 stdio, the project on PYTHONPATH in source mode, no inherited Qt platform),
writes every line it prints to the tool's own log (`<logs>/<kind>.log`, the command line's log folder, one run's
lines), hands each line to `on_line` and, when it ends, **its exit code decides**: 0 is done, anything else failed,
with the log's path. Cancelling the job ends the child. `on_end(returncode)` (None when it never started) is told last.

`command(argv)` is the frozen / source map the Tk dashboard's `run_command_async` holds (`SCRIPT_MAP`, kept as it is
there): a frozen build runs `Surasura.exe <subcommand>`, source runs `python app/<script>`. Qt-free: nothing here
waits on the caller's thread — `run` returns the job at once; callbacks run on the tool's thread.
"""
import os
import subprocess
import sys
import threading
import time
from collections import namedtuple

from app import path_utils

# The frozen build's subcommand for each script (app_entry.py's dispatch) — the Tk dashboard's map, as it is there.
SCRIPT_MAP = {
    'analyzer.py': 'analyzer',
    'epub_importer.py': 'epub_importer',
    'migaku_db_importer_gui.py': 'migaku_importer',
    'jiten_db_importer_gui.py': 'jiten_importer',
    'content_importer_gui.py': 'content_importer',
    'static_html_generator.py': 'static_generator',
    'migaku_converter.py': 'convert_db',
    'anki_db_importer_gui.py': 'anki_importer',
    'frequency_list_gui.py': 'frequency_list_manager',
    'indexer.py': 'index',
    'sentence_corpus.py': 'sentence_corpus',
}
CREATE_NO_WINDOW = 0x08000000           # Windows: a console child opens no console window


def command(argv, frozen=None, executable=None):
    """The command line that starts `argv` (`[script, *arguments]`): frozen, `[Surasura.exe, subcommand, --headless,
    *arguments]` (app_entry strips the flag: a crash exits 1, never a Critical Error box from an unseen child, and an
    unknown word exits 2, never a second window); from source, `[python, app/<script>, *arguments]`. Pure."""
    if frozen is None:
        frozen = path_utils.is_frozen()
    executable = executable or sys.executable
    script, rest = argv[0], list(argv[1:])
    if frozen:
        return [executable, SCRIPT_MAP.get(script, script), "--headless"] + rest
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return [executable, os.path.join(app_dir, script)] + rest


def log_path(kind):
    """The tool's own log: `<the command line's log folder>/<kind>.log`."""
    from app.cli import contract
    return os.path.join(contract.log_folder(), f"{kind}.log")


Result = namedtuple("Result", "code cancelled why log")


def run(registry, kind, label, argv, env=None, on_line=None, on_end=None, before=None, on_quit="cancel",
        automatic=False, frozen=None, on_result=None):
    """`argv` as a child, a gated job of `kind` labelled `label` (the user's words). `env`: variables for this child
    only, over `build_subprocess_env` (a secret goes here, never in `argv`) — the environment is taken here, on the
    asker's thread, so a job that waits starts with the environment it was asked with. `before()`: run on the tool's
    thread just before the child starts (the settings written first: every child reads settings.json). The end is told
    once, on the tool's thread: `on_end(returncode)` (None when it never started) and `on_result(Result(code,
    cancelled, why, log))` — whether it was stopped, why it couldn't start or ended early, its log (None: no log).
    -> the Job, at once."""
    state = {"process": None, "cancelled": False, "started": False, "told": False}
    lock = threading.Lock()
    child_env = path_utils.build_subprocess_env(frozen)
    child_env.update(env or {})
    asked_root = os.environ.get("SURASURA_TEST_ROOT")

    def ended(result):
        with lock:                                            # told once, whichever side gets there first
            if state["told"]:
                return
            state["told"] = True
        _told(on_end, result.code, label)
        _told(on_result, result, label)

    def cancel(_job):
        with lock:
            state["cancelled"] = True
            process, started = state["process"], state["started"]
        if not started:                                       # ended before it started: its owner still hears the end
            ended(Result(None, True, None, None))
        elif process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def start(job):
        with lock:
            state["started"] = True
        try:
            threading.Thread(target=_body, args=(job,), name=f"tool-{kind}", daemon=True).start()
        except BaseException as e:                            # the registry fails the job; its owner still hears
            ended(Result(None, False, str(e), None))
            raise

    def _body(job):
        code, why, path, log, process = None, None, None, None, None
        try:
            if os.environ.get("SURASURA_TEST_ROOT") == asked_root:      # (a root changed under the job: no log)
                try:
                    path = log_path(kind)
                except Exception:                             # no log folder: the child runs without a log
                    path = None
            if before is not None:
                try:
                    before()
                except Exception as e:                        # the child still runs; it reads the file as it is
                    print(f"Tools: before {label}: {e}")
            with lock:
                if state["cancelled"]:
                    raise _Cancelled()
            args = command(argv, frozen)
            log = _open_log(path) if path else None
            _write(log, f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {label}\n")
            process = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True,
                encoding="utf-8", errors="replace", bufsize=1, env=child_env,
                creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            with lock:
                state["process"] = process
                stop = state["cancelled"]
            job.started_process(process.pid)
            if stop:
                process.terminate()
            for line in process.stdout:
                line = line.rstrip("\r\n")
                _write(log, line + "\n")
                if on_line is not None:
                    try:
                        on_line(line)
                    except Exception as e:                    # a listener's fault never stops the child's pipe
                        print(f"Tools: a line listener failed: {e}")
            code = process.wait()
            _write(log, f"[exit {code}]\n")
        except _Cancelled:
            pass
        except Exception as e:
            why = str(e) or type(e).__name__
            _write(log, f"[{why}]\n")
            if process is not None and process.poll() is None:    # never a child left running untracked
                try:
                    process.terminate()
                    process.wait(5)
                except Exception:
                    pass
        finally:
            if log is not None:
                log.close()
        cancelled = state["cancelled"]
        if code == 0:
            job.finish(ok=True, completed=cancelled)          # a cancel that came as it exited 0: done, not cancelled
            cancelled = False
        elif cancelled:
            job.finish(ok=True, cancelled=True)
        elif why is not None and process is None:
            job.finish(ok=False, message=f"{label}: couldn't start ({why})")
        elif why is not None:
            job.finish(ok=False, message=f"{label}: ended ({why})" + (f" — {path}" if path else ""))
        else:
            job.finish(ok=False, message=f"{label}: ended with code {code}" + (f" — {path}" if path else ""))
        ended(Result(code, cancelled, why, path))

    return registry.submit(kind, label, start, cancel=cancel, automatic=automatic, on_quit=on_quit)


class _Cancelled(Exception):
    pass


def _told(on_end, code, label):
    if on_end is None:
        return
    try:
        on_end(code)
    except Exception as e:
        print(f"Tools: {label}'s end listener failed: {e}")


def _open_log(path):
    """The tool's log, written fresh for this run — or None when it can't be opened (the child runs anyway)."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return open(path, "w", encoding="utf-8", errors="replace")
    except OSError:
        return None


def _write(log, text):
    if log is None:
        return
    try:
        log.write(text)
        log.flush()
    except (OSError, ValueError):
        pass
