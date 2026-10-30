import sys
import os
import traceback
import logging

# Ensure the application is importable
app_root = os.path.dirname(os.path.abspath(__file__))
if app_root not in sys.path:
    sys.path.insert(0, app_root)

def log_error(msg):
    # The app's log lives in the per-install local data folder (P0.3 02-contract §6), never in the folder Surasura was
    # started from; each line stamped with its time and process (path_utils.write_app_log). Logging never stops the app.
    try:
        from app.path_utils import write_app_log
        write_app_log(msg)
    except Exception:
        pass

# Windows Taskbar Icon Fix (Set AppUserModelID)
if sys.platform == "win32":
    try:
        import ctypes
        from app import __version__
        myappid = f'SonicSandbox.Surasura.ReadabilityAnalyzer.{__version__}'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

import multiprocessing


def _error_box(title, text):
    """The app's one error route before any window exists: a Tk message box (never on a headless call)."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, text)
        root.destroy()
    except Exception:
        pass


def _start_checks(headless):
    """The frozen program's checks at start (S3.1 D18): hold `<data name>.Running` for the process's life (Inno
    Setup's AppMutex), and refuse to run when this program and its `_internal` folder are different builds (their build
    stamp): logged, shown unless headless, exit 2 (`version-skew`). -> None to go on, else the exit code."""
    from app import build_info
    build_info.hold_running_mutex()
    skew = build_info.stamp_skew()
    if not skew:
        return None
    log_error(f"version-skew: this program {skew['program']}, its folder {skew['folder']}")
    if not headless:
        _error_box("Surasura", build_info.skew_text(skew))
    return 2


def _qt_window():
    """The 3.0 window's module (app/qt/shell.py), or None when PyQt6 isn't installed: then the Tk dashboard opens and
    the log says why (a build or a checkout without the 3.0 line's dependency). Imported here, inside a function, so
    no headless verb ever loads Qt (tests/test_import_guard.py)."""
    try:
        from app.qt import shell
        return shell
    except ImportError as e:
        if (getattr(e, "name", None) or "").split(".")[0] == "PyQt6":
            log_error(f"The window needs PyQt6, which isn't installed ({e}): opening the Tk dashboard")
            return None
        raise


_run = {}      # the command this process runs and when it began (`run`), for its one end line (`_log_end`)


def _log_end(code):
    """The command's end, once: how long it ran and its exit code (a7: the log had no times, so a Generate's length,
    or how many ran in a burst, could only be guessed). A process that ends by `os._exit` calls it first (the
    arrivals worker); a killed one writes none."""
    import time
    started = _run.pop("started", None)
    if started is not None:
        log_error(f"Ended {_run.get('command')} after {time.monotonic() - started:.1f} s (exit {code})")


def run():
    """The program: one command (`main`, the dispatch), its end logged (`_log_end`)."""
    import time
    args = [arg for arg in sys.argv[1:] if arg != "--headless"]
    command = args[0] if args else "window"
    if command == "--multiprocessing-fork":         # a frozen run's pool worker (freeze_support): no command of its own
        return main()
    _run.update(command=command, started=time.monotonic())
    code = 0
    try:
        main()
    except SystemExit as e:
        code = 0 if e.code is None else e.code
        raise
    except BaseException as e:
        code = type(e).__name__
        raise
    finally:
        _log_end(code)


def main():
    # Force UTF-8 for stdout/stderr to avoid UnicodeEncodeError in frozen Windows builds
    if sys.platform == "win32":
        try:
            import io
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
        except Exception:
            pass

    multiprocessing.freeze_support()
    # --headless: another program started this subcommand (surasura-cli's generate, P0.3 02-contract §1). A crash is
    # logged and exits 1, never a Critical Error box; an unknown or missing command exits 2, never opens the dashboard.
    headless = "--headless" in sys.argv[1:]
    use_tk = False
    if headless:
        sys.argv = [arg for arg in sys.argv if arg != "--headless"]
    try:
        log_error(f"App starting. Args: {sys.argv}")
        
        # Ensure the bundle root is in sys.path
        if getattr(sys, 'frozen', False):
            bundle_dir = sys._MEIPASS
            if bundle_dir not in sys.path:
                sys.path.insert(0, bundle_dir)
            log_error(f"Frozen mode. Bundle dir: {bundle_dir}")
            code = _start_checks(headless)
            if code:
                sys.exit(code)
        else:
            log_error("Source mode.")

        if len(sys.argv) > 1:
            command = sys.argv[1]
            log_error(f"Dispatching command: {command}")
            
            # Dispatch Logic
            if command == 'library_maintain':
                # The library store's helper (Library_Store_Spec §6.7): `library_maintain [maintain | sync]
                # --language <l> …`. Dialog-free — it never reaches the crash dialog below — and it ends with
                # its exit code. An unknown command must never fall through to the dashboard (K8).
                code = 1
                try:
                    from app import library_store
                    rest = sys.argv[2:]
                    if not rest or rest[0] not in ("maintain", "sync"):
                        rest = ["maintain"] + rest
                    code = library_store.main(rest)
                except Exception:
                    log_error(f"library_maintain failed:\n{traceback.format_exc()}")
                sys.exit(code)

            elif command == 'apkg_known_import' or command == 'extract':
                # The 3.0 window's tools (W3.4 row 2): the .apkg known-words import (app/anki_db_import.py) and Extract
                # (app/extract.py), each a child of the window. Dialog-free; it ends with its exit code.
                code = 1
                try:
                    if command == 'extract':
                        from app import extract as tool
                    else:
                        from app import anki_db_import as tool
                    code = tool.main(sys.argv[2:])
                except Exception:
                    log_error(f"{command} failed:\n{traceback.format_exc()}")
                sys.exit(code)

            elif command == 'replan_helper':
                # The fast re-plan's helper (E3.1-B1, app/replan_preview.py): one window's re-order jobs in a process
                # of its own, talking to that window over a local pipe. Dialog-free; it ends when its window goes.
                code = 1
                try:
                    from app import replan_preview
                    code = replan_preview.helper_main(sys.argv[2:])
                except Exception:
                    log_error(f"replan_helper failed:\n{traceback.format_exc()}")
                sys.exit(code)

            elif command == 'analyzer':
                from app import analyzer
                sys.argv = [sys.argv[0]] + sys.argv[2:]
                # Its exit code: 1 when the report couldn't be written, 3 when another program held results/
                # (P0.3 04 §1) — the caller reads it (surasura-cli's generate; the window's log).
                sys.exit(analyzer.main() or 0)

            elif command == 'epub_importer':
                from app import epub_importer
                sys.argv = [sys.argv[0]] + sys.argv[2:]
                epub_importer.main()
                return

            elif command == 'migaku_importer':
                from app import migaku_db_importer_gui
                sys.argv = [sys.argv[0]] + sys.argv[2:]
                migaku_db_importer_gui.main()
                return
                
            elif command == 'jiten_importer':
                from app import jiten_db_importer_gui
                sys.argv = [sys.argv[0]] + sys.argv[2:]
                jiten_db_importer_gui.main()
                return
                
            elif command == 'static_generator':
                from app import static_html_generator
                sys.argv = [sys.argv[0]] + sys.argv[2:]
                static_html_generator.main() 
                return 
                
            elif command == 'convert_db':
                from app import migaku_converter
                sys.argv = [sys.argv[0]] + sys.argv[2:] 
                migaku_converter.main()
                return

            elif command == 'convert_jiten':
                from app import jiten_converter
                sys.argv = [sys.argv[0]] + sys.argv[2:] 
                jiten_converter.main()
                return

            elif command == 'content_importer':
                from app import content_importer_gui
                sys.argv = [sys.argv[0]] + sys.argv[2:] 
                content_importer_gui.main()
                return

            elif command == 'frequency_list_manager':
                from app import frequency_list_gui
                sys.argv = [sys.argv[0]] + sys.argv[2:]
                frequency_list_gui.main()
                return

            elif command == 'anki_importer':
                from app import anki_db_importer_gui
                sys.argv = [sys.argv[0]] + sys.argv[2:]
                anki_db_importer_gui.main()
                return

            elif command == 'index':
                from app import indexer
                sys.argv = [sys.argv[0]] + sys.argv[2:]
                indexer.main()
                return

            elif command == 'arrivals-worker':
                # The warm arrivals worker (E2.2 D10, K9): `arrivals-worker --headless --language <l> …` — JSON lines
                # on stdin / stdout; it ends when its input closes, on "quit", or idle. Started by the window's
                # services (app/services/arrivals.py), never by a user.
                from app import arrivals_worker
                sys.exit(arrivals_worker.main(sys.argv[2:], before_exit=_log_end) or 0)

            elif command == 'word-lists-find':
                # *Words to leave out*'s Paste text (W3.3 FX-wl, n16 "a worker process"): `word-lists-find --headless`,
                # the text as JSON on stdin, its words as JSON on stdout. One per paste, started by the window's
                # services (app/services/word_lists.py `find_words`), never by a user.
                from app.services import word_lists
                sys.exit(word_lists.find_main() or 0)

            elif command == 'sentence_corpus':
                from app import sentence_corpus
                sys.argv = [sys.argv[0]] + sys.argv[2:]
                sentence_corpus.main()
                return

            elif command == 'junban_patterns':
                # The Anki Backfill window's "Build & preview" (Patterns_Spec §17.2): the library's
                # パターン data, counted in its own process. Guarded — the module may be absent.
                try:
                    from modules.junban import patterns_build
                except ImportError:
                    log_error("junban_patterns: the Junban module is not installed")
                    sys.exit(1)
                sys.argv = [sys.argv[0]] + sys.argv[2:]
                sys.exit(patterns_build.main())
            elif command == 'youtube_preview':
                # The YouTube preview's scoring child (W3.4 row 4): the transcript scored against the library in a
                # process of its own, never the window's. Guarded — the module may be absent.
                try:
                    from modules.youtube_downloader import preview
                except ImportError:
                    log_error("youtube_preview: the YouTube module is not installed")
                    sys.exit(1)
                sys.exit(preview.child_main(sys.argv[2:]))
            elif command == 'dashboard':
                # The 2.x Tk dashboard, kept reachable on the 3.0 line until nothing opens a Tk window (W3.4's last row
                # retires it; W2.1 RUNBOOK G-1, IK-14). Falls through to the default start below, in Tk.
                use_tk = True
            else:
                log_error(f"Unknown command: {command}")

        if headless:
            log_error("Headless: nothing to run; the dashboard never opens headless")
            sys.exit(2)

        # Telemetry Initialization (either window)
        try:
            from app import telemetry
            telemetry.init()
        except Exception as e:
            log_error(f"Telemetry init failed: {e}")

        # Default: the window. On the 3.0 line that is the PyQt6 window (W2.1, the window's spec 01 §1.6); the Tk
        # dashboard opens for `dashboard`, or when PyQt6 is missing.
        window = None if use_tk else _qt_window()
        if window is not None:
            log_error("Launching the window")
            sys.exit(window.main(list(sys.argv)) or 0)

        log_error("Launching Dashboard")
        from app import main as dashboard
        dashboard.main()
        
    except Exception as e:
        err_msg = f"CRITICAL ERROR:\n{traceback.format_exc()}"
        log_error(err_msg)
        if headless:
            sys.exit(1)
        # Also try to show a message box if possible
        _error_box("Critical Error", err_msg)
        sys.exit(1)

if __name__ == "__main__":
    run()
