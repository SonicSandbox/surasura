"""surasura-cli's first real verbs (P0.3 03, P1.2): `status`, `list`, `known`, `known-sync`, `generate`, `junban`.

Each takes the parsed arguments and returns its result's fields, or raises `contract.CliError`. The rules every verb
follows are `contract.py`'s; what each verb answers and writes is 03-verbs.md's. The window's rules they share live in
Tk-free code both call (`app/run_args.py`, `analyzer.journey_check`, `anki_sync.may_sync`, `modules/junban/auto.py`).

Light by rule (02 §5): nothing here imports Tk, Qt, pandas or requests; the quick verbs (`status`, `list`, `known` on
a fresh cache) read no text, so fugashi and jieba stay out of them too. Every import is inside the verb that needs it.
"""
import csv
import datetime
import re
import importlib.util
import json
import os
import subprocess
import sys
import time

from app.cli import contract
from app.cli.contract import CliError

LANGUAGES = ("ja", "zh")
PRIORITY_CSV = "priority_learning_list.csv"
PROGRESSIVE_CSV = "progressive_learning_list.csv"


def _han():
    from app.unicode_ranges import HAN
    return re.compile(f"[{HAN}]")


_HAN = _han()


# --------------------------------------------------------------------------- #
# Shared
# --------------------------------------------------------------------------- #
def add_language(parser):
    parser.add_argument("--lang", choices=LANGUAGES, default=None,
                        help="ja or zh (default: the language Surasura is set to)")


def add_wait(parser):
    parser.add_argument("--wait", type=float, default=0.0, metavar="SECONDS",
                        help="wait up to this long for another program's lock (default: answer busy at once)")


def settings():
    """settings.json as the window reads it, strictly: unreadable -> `bad-data` (a fallback to the defaults would be
    a silent lie, and a later save would write it back)."""
    from app import settings_manager
    try:
        return settings_manager.load_settings(strict=True)
    except settings_manager.SettingsError as e:
        raise CliError("bad-data", "Surasura's settings (settings.json) can't be read. Open Surasura, or fix the file.",
                       detail=str(e)) from None


def language(args, loaded):
    lang = getattr(args, "lang", None) or loaded.get("target_language") or "ja"
    return lang if lang in LANGUAGES else "ja"


def require_set_up(lang):
    """`not-set-up` (exit 2) until Surasura has made this language's folders."""
    from app.path_utils import get_user_files_path
    if not os.path.isdir(get_user_files_path(lang)):
        raise CliError("not-set-up", "Surasura isn't set up for this language yet. Open Surasura once to set it up.",
                       language=lang)


def read_run_stamp_here():
    from app import analyzer
    return analyzer.read_run_stamp(_results_dir())


def _results_dir():
    from app.path_utils import get_user_file
    return get_user_file("results")


def _results_language():
    """The language results/ holds now (one at a time): `library_frequency.json`'s, written by every run. None when
    it can't tell."""
    try:
        with open(os.path.join(_results_dir(), "library_frequency.json"), encoding="utf-8") as f:
            return (json.load(f).get("settings") or {}).get("language")
    except (OSError, ValueError, AttributeError):
        return None


def _iso(seconds):
    return datetime.datetime.fromtimestamp(seconds).isoformat(timespec="seconds")


def _in_use(name):
    from app import locks
    return locks.in_use(name)


def _module_present(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #
def status_args(parser):
    add_language(parser)
    parser.add_argument("--anki", action="store_true", help="also ask whether Anki is reachable (~1 s when it's closed)")


def status(args):
    """Writes nothing: a read-only journey check (`analyzer.journey_check`), every store `mode=ro`, no disk sync, no
    store helper, no lock taken (a look at the indexer's)."""
    from app import analyzer, anki_sync, library_store, run_args
    loaded = settings()
    lang = language(args, loaded)
    require_set_up(lang)
    argv = run_args.analyzer_args(loaded, lang, headless=True)
    last_run = analyzer._token_store_meta(lang, "last_run_signature")
    stamp = analyzer.read_run_stamp(_results_dir())
    last_generate = None
    if last_run and stamp == last_run:
        try:
            last_generate = _iso(os.path.getmtime(os.path.join(_results_dir(), analyzer.RUN_STAMP_FILE)))
        except OSError:
            pass
    sync_state = anki_sync.load_state(lang)
    anki = {"last_sync": sync_state.get("last_sync"), "backlog": anki_sync.count_backlog(lang)}
    if args.anki:
        from app import anki_connect
        anki["reachable"] = bool(anki_connect.probe(anki_connect.address(loaded)).get("ok"))
    return {
        "language": lang,
        "journey_current": analyzer.journey_check(argv, lang),
        "last_generate": last_generate,
        "run_signature": last_run,
        "known_words": anki_sync.count_known(lang),
        "anki": anki,
        "junban": "present" if _module_present("modules.junban.reposition") else "absent",
        "backfill": "present" if _module_present("modules.junban.backfill") else "absent",
        "indexer": "busy" if _in_use("indexer") else "idle",
        "update_staged": bool(library_store.update_staged()),
        "logs": contract.log_folder(),          # cli.log, cli-events.jsonl, generate.log: where to look when one fails
    }


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #
def list_args(parser):
    add_language(parser)
    add_wait(parser)
    parser.add_argument("--file", default=None, help="only this library file's words, in the file's own order")
    parser.add_argument("--order", choices=("leverage", "encounter"), default="leverage",
                        help="leverage (the list's order, default) or encounter (the journey's order)")
    parser.add_argument("--limit", type=_count, default=None, help="at most this many words")


def _count(text):
    import argparse
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("a count can't be negative")
    return value


def _kinds(lang):
    """word -> kind for the rows that aren't plain words: phrase (a set phrase's row), compound (a word made of
    words), one_kanji (Japanese, one character). The tables the run itself reads; Chinese keeps every word a word."""
    if lang != "ja":
        return lambda word: "word"
    phrases, compounds = set(), set()
    try:
        from app import phrases as _phrases
        loaded = _phrases.load()
        phrases = {entry.word for entry in loaded.entries} if loaded else set()
    except Exception:
        pass
    try:
        from app import reference_data
        compounds = {lemma or form for form, (lemma, *_rest) in reference_data.compound_joins().items()}
    except Exception:
        pass

    def kind(word):
        if word in phrases:
            return "phrase"
        if word in compounds:
            return "compound"
        if len(word) == 1 and _HAN.match(word):
            return "one_kanji"
        return "word"
    return kind


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _read_rows(path):
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        raise CliError("bad-data", "Surasura's list (results) can't be read. Generate again.", detail=str(e)) from None


def list_words(args):
    """The list as the last Generate left it (results/), read under the `results` lock so a Generate never hands it
    over half-written."""
    loaded = settings()
    lang = language(args, loaded)
    require_set_up(lang)
    with contract.take_lock("results", "reading the list", wait=args.wait):
        holds = _results_language()
        if holds and holds != lang:
            return {"language": lang, "words": [], "skipped": f"results hold {holds}"}
        if read_run_stamp_here() is None and os.path.exists(os.path.join(_results_dir(), PRIORITY_CSV)):
            raise CliError("bad-data", "The last Generate didn't finish, so its list may be cut short. Generate again.")
        if args.file is not None or args.order == "encounter":
            rows = _read_rows(os.path.join(_results_dir(), PROGRESSIVE_CSV))
        else:
            rows = _read_rows(os.path.join(_results_dir(), PRIORITY_CSV))
    out = {"language": lang}
    if args.file is not None:
        name = os.path.basename(args.file)
        rows = [row for row in rows if row.get("Source File") == name]
        out["file"] = name
    kind = _kinds(lang)
    words, seen = [], set()
    for row in rows:
        if args.limit is not None and len(words) >= args.limit:
            break
        key = (row.get("Word", ""), row.get("Reading", ""))
        if key in seen:                     # the journey meets a word once; a file's rows are its own
            continue
        seen.add(key)
        word = {"word": key[0], "orth": row.get("Orth") or key[0], "reading": key[1], "score": _int(row.get("Score")),
                "occurrences": _int(row.get("Occurrences", row.get("Occurrences (Global)"))),
                "kind": kind(key[0])}
        if args.file is not None:
            word["file_order"] = len(words) + 1
            word["file_occurrences"] = _int(row.get("Occurrences (File)"))
        words.append(word)
    out["words"] = words
    return out


# --------------------------------------------------------------------------- #
# known
# --------------------------------------------------------------------------- #
def known_args(parser):
    add_language(parser)


def _cached_known(lang, script):
    """The token store's known-words cache, read `mode=ro`, when it matches KnownWord.json as it is: (tuples, lemmas)
    or None."""
    import pathlib
    import sqlite3
    from app import token_index
    from app.path_utils import get_user_files_path
    path = token_index.store_path_for(lang)
    if not os.path.isfile(path):
        return None
    signature = token_index.known_signature(os.path.join(get_user_files_path(lang), "KnownWord.json"), script)
    try:
        conn = sqlite3.connect(pathlib.Path(path).as_uri() + "?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error:
        return None
    try:
        reader = token_index.Store.__new__(token_index.Store)     # its reads, over this read-only connection
        reader.conn, reader.language = conn, lang
        return reader.get_cached_known(signature)
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def _spellings(lang):
    """lemma|reading -> the commonest spelling, from the last run (`library_frequency.json`), when it was this
    language's."""
    if _results_language() not in (None, lang):
        return {}
    try:
        with open(os.path.join(_results_dir(), "library_frequency.json"), encoding="utf-8") as f:
            words = json.load(f).get("words") or {}
        return {key: entry[6] for key, entry in words.items() if isinstance(entry, list) and len(entry) > 6}
    except (OSError, ValueError, AttributeError):
        return {}


def known(args):
    """The known words: always the lemma as `word` (S9), the reading, and the commonest spelling when the list knows
    it. From the token store's cache when it matches KnownWord.json; else read now (`computed`: the tokenizer loads)."""
    from app import zh_script
    from app.path_utils import get_user_files_path
    loaded = settings()
    lang = language(args, loaded)
    require_set_up(lang)
    script = zh_script.effective(lang, loaded.get("zh_script", "asis"))
    cached, source = _cached_known(lang, script), "cache"
    if cached is None:
        source = "computed"
        from app import analyzer
        tokenizer = (analyzer.ChineseTokenizer(script=script) if lang == "zh" else analyzer.JapaneseTokenizer())
        analyzer.SANITIZE_JA = (lang == "ja")
        try:
            cached = analyzer.load_known_words(os.path.join(get_user_files_path(lang), "KnownWord.json"), tokenizer)
        except (ValueError, UnicodeDecodeError) as e:
            raise CliError("bad-data", "Your known words (KnownWord.json) can't be read; nothing was changed.",
                           detail=str(e)) from None
    tuples, _lemmas = cached
    spelled = _spellings(lang)
    words = [{"word": word, "reading": reading, "orth": spelled.get(f"{word}|{reading}", word)}
             for word, reading in sorted(tuples)]
    return {"language": lang, "words": words, "count": len(words), "source": source}


# --------------------------------------------------------------------------- #
# known-sync
# --------------------------------------------------------------------------- #
def known_sync_args(parser):
    add_language(parser)
    add_wait(parser)
    parser.add_argument("--full", action="store_true", help="read every studied card again, not just the new ones")


def known_sync(args):
    """New known words from Anki into KnownWord.json (append-only), and the decks' new cards into the backlog — the
    window's automatic sync, with its gates (`anki_sync.may_sync`), under the `known-words-<lang>` lock."""
    from app import anki_connect, anki_sync
    loaded = settings()
    lang = language(args, loaded)
    require_set_up(lang)
    gate = anki_sync.may_sync(lang, loaded, throttle=not args.full)
    if gate is not None:
        why, words = gate
        if why in ("off", "throttled"):
            return {"language": lang, "added": 0, "total": anki_sync.count_known(lang),
                    "backlog": anki_sync.count_backlog(lang), "last_sync": anki_sync.load_state(lang).get("last_sync"),
                    "skipped": words}
        raise CliError("needs-you", words, ask=words)
    decks = list((loaded.get("anki_sync_decks") or {}).get(lang) or [])
    fields = list((loaded.get("anki_sync_fields") or {}).get(lang) or [])
    url = anki_connect.address(loaded)
    with contract.take_lock(anki_sync.known_lock_name(lang), "surasura-cli known-sync", wait=args.wait):
        try:
            anki_sync._read_known_file(lang)
        except anki_sync._KnownFileError as e:
            raise CliError("bad-data", "Your known words (KnownWord.json) can't be read; nothing was changed.",
                           detail=str(e)) from None
        if not anki_connect.probe(url).get("ok"):
            raise CliError("anki-closed", "Anki isn't open (or AnkiConnect isn't installed). Open Anki, then try again.")
        contract.emit_progress("reading Anki", 0, 2)
        result = anki_sync.sync(lang, url, decks, fields,
                                include_suspended=bool(loaded.get("anki_sync_include_suspended", False)),
                                full=args.full)
        if result.error:
            raise CliError("failed", result.error)
        contract.emit_progress("reading Anki's new cards", 1, 2)
        anki_sync.sync_backlog(lang, url, decks, fields)
    return {"language": lang, "added": result.added, "total": result.total_known,
            "backlog": anki_sync.count_backlog(lang), "last_sync": anki_sync.load_state(lang).get("last_sync")}


# --------------------------------------------------------------------------- #
# generate
# --------------------------------------------------------------------------- #
CREATE_NO_WINDOW = 0x08000000
CHILD_WAIT = 10.0           # the analyzer's own wait for `results` (SURASURA_RESULTS_WAIT): the hand-over's moment


def generate_args(parser):
    add_language(parser)
    add_wait(parser)
    parser.add_argument("--force", action="store_true", help="run the analysis even when nothing changed")


def _backlog_read(loaded, lang):
    """The Anki backlog read the window fires before Generate (WP-B7), awaited here: the report marks the cards
    waiting in Anki. Nothing without decks, with the switch off, or with Anki closed."""
    if not loaded.get("anki_backlog_on_generate", True) or os.environ.get("SURASURA_NO_ANKI_SYNC"):
        return
    decks = list((loaded.get("anki_sync_decks") or {}).get(lang) or [])
    if not decks:
        return
    try:
        from app import anki_connect, anki_sync
        url = anki_connect.address(loaded)
        if anki_connect.probe(url).get("ok"):
            anki_sync.sync_backlog(lang, url, decks, list((loaded.get("anki_sync_fields") or {}).get(lang) or []))
    except Exception as e:
        contract.log.warning("the Anki backlog wasn't read: %s", e)


def _nothing_changed(argv, lang):
    """The window's own "reopen, don't run" question (`_report_reusable`): the analysis is current and the report
    already shows it. Asked without pandas."""
    from app import analyzer
    if analyzer.journey_is_current(argv, lang) is not True:
        return False
    if not os.path.exists(os.path.join(_results_dir(), "reading_list_static.html")):
        return False
    rendered = analyzer._token_store_meta(lang, "last_render_sig")
    return rendered == analyzer.compute_render_signature(analyzer.parse_analysis_args(argv[1:]))


def child_command(argv):
    """The analyzer child: `Surasura.exe analyzer --headless …` beside this program when frozen, else `app_entry.py`'s
    same route — `--headless` turns its crash dialog into a log line and exit 1."""
    from app.path_utils import is_frozen
    if is_frozen():
        exe = os.path.join(os.path.dirname(sys.executable), "Surasura.exe" if sys.platform == "win32" else "Surasura")
        return [exe, "analyzer", "--headless"] + argv[1:]
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return [sys.executable, os.path.join(root, "app_entry.py"), "analyzer", "--headless"] + argv[1:]


def _count_rows(path):
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            return max(0, sum(1 for _row in csv.reader(f)) - 1)
    except OSError:
        return 0


def generate(args):
    """Generate as the window's button does, headless: the same argv (`run_args`, always `--no-open`, never
    `--app-mode`), `ran: false` when nothing changed (no analyzer, no pandas), else the analyzer as a child that
    holds `results` itself — so a killed command line never leaves a writer without the lock. `ran` says whether the
    analysis ran (a new run stamp): a re-render alone, or the analyzer's own "nothing changed", is `ran: false`.
    `--force` runs it anyway."""
    from app import analyzer, path_utils, run_args
    loaded = settings()
    lang = language(args, loaded)
    require_set_up(lang)
    argv = run_args.analyzer_args(loaded, lang, headless=True)
    started = time.monotonic()
    deadline = started + max(0.0, args.wait or 0.0)
    with contract.take_lock("results", "Generate (command line)", wait=args.wait):
        contract.emit_progress("reading Anki's backlog", 0, None)
        _backlog_read(loaded, lang)
        if not args.force and _nothing_changed(argv, lang):
            return {"language": lang, "ran": False, "run_signature": analyzer.read_run_stamp(_results_dir()),
                    "words": _count_rows(os.path.join(_results_dir(), PRIORITY_CSV)),
                    "seconds": round(time.monotonic() - started, 3)}
    # Let go, then start the child: it takes `results` itself, waiting for this moment what is left of --wait (never
    # less than CHILD_WAIT): a window's Generate pressed meanwhile may start first, and then this one waits its turn.
    log_path = os.path.join(contract.log_folder(), "generate.log")
    stamp = os.path.join(_results_dir(), analyzer.RUN_STAMP_FILE)
    stamped = _mtime(stamp)
    env = path_utils.build_subprocess_env(path_utils.is_frozen())
    env["SURASURA_RESULTS_WAIT"] = str(round(max(CHILD_WAIT, deadline - time.monotonic()), 3))
    if args.force:
        env["SURASURA_FORCE_RUN"] = "1"     # the analyzer runs even when its own signature says nothing changed
    contract.emit_progress("generating", 0, None)
    with open(log_path, "w", encoding="utf-8", errors="replace") as child_log:
        if sys.platform == "win32":
            detached = {"creationflags": CREATE_NO_WINDOW}
        else:
            detached = {"start_new_session": True}      # Ctrl+C in the caller's terminal never stops it mid-write
        child = subprocess.Popen(child_command(argv), stdin=subprocess.DEVNULL, stdout=child_log,
                                 stderr=subprocess.STDOUT, env=env, **detached)
        contract.log.info("generate: analyzer child pid=%s", child.pid)
        code = child.wait()
    seconds = round(time.monotonic() - started, 3)
    if code == analyzer.RESULTS_BUSY:
        from app import locks
        raise contract.busy_error("results", locks.read_holder("results"))
    if code != 0:
        raise CliError("crashed-child", f"Generate failed (the analyzer stopped with code {code}). The details are "
                                        f"in its log: {log_path}", child_exit=code, log=log_path)
    contract.emit_progress("generating", 1, 1)
    return {"language": lang, "ran": _mtime(stamp) != stamped,
            "run_signature": analyzer.read_run_stamp(_results_dir()),
            "words": _count_rows(os.path.join(_results_dir(), PRIORITY_CSV)), "seconds": seconds}


def _mtime(path):
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


# --------------------------------------------------------------------------- #
# junban
# --------------------------------------------------------------------------- #
def junban_args(parser):
    add_language(parser)
    add_wait(parser)
    how = parser.add_mutually_exclusive_group(required=True)
    how.add_argument("--dry-run", action="store_true", help="the reorder the 順 window would preview; writes nothing")
    how.add_argument("--auto", action="store_true",
                     help="the automatic reorder: one deck, positions only, never while you review in Anki")


def _junban_settings(loaded, lang):
    out = dict(loaded)
    out["target_language"] = lang
    return out


def junban(args):
    """`--dry-run`: `reposition.dry_run`, the 順 window's preview, writing nothing. `--auto`: the automatic reorder
    (`modules/junban/auto.py`) with every guard it has in the window, positions only. Junban not installed:
    `skipped` (RD-S10)."""
    loaded = settings()
    lang = language(args, loaded)
    require_set_up(lang)
    try:
        from modules.junban import auto, reposition
    except ImportError:
        return {"language": lang, "moves": 0, "unchanged": 0, "not_on_list": 0, "undo": None,
                "skipped": "junban absent"}
    junban_settings = _junban_settings(loaded, lang)
    if os.environ.get("SURASURA_NO_ANKI_SYNC"):         # the test suites, a developer's run: Anki is never reached
        return {"language": lang, "moves": 0, "unchanged": 0, "not_on_list": 0, "undo": None,
                "skipped": "Anki is switched off for this run (SURASURA_NO_ANKI_SYNC)"}
    if args.dry_run:
        return _junban_dry_run(lang, junban_settings, reposition)
    return _junban_auto(args, lang, junban_settings, auto)


def _junban_dry_run(lang, junban_settings, reposition):
    from app import anki_connect
    if not anki_connect.probe(reposition._url(junban_settings)).get("ok"):
        raise CliError("anki-closed", "Anki isn't open (or AnkiConnect isn't installed). Open Anki, then try again.")
    try:
        writes, stats = reposition.dry_run(junban_settings)
    except reposition.AnkiError as e:
        raise CliError("anki-closed", f"Anki stopped answering: {e}") from None
    if stats.get("problems"):
        raise CliError("needs-you", stats["problems"][0], ask=stats["problems"][0])
    return {"language": lang, "moves": len(writes), "unchanged": max(0, stats.get("total", 0) - len(writes)),
            "not_on_list": stats.get("unmatched", 0), "undo": None, "decks": stats.get("decks") or []}


def _junban_auto(args, lang, junban_settings, auto):
    from app import analyzer, locks, run_args
    why = auto.blocked(junban_settings, window=False)
    if why is not None:
        return {"language": lang, "moves": 0, "unchanged": 0, "not_on_list": 0, "undo": None, "skipped": why}
    # The 順 window holds `junban-window` while open: looked at (never held, so a window opened meanwhile still takes
    # it), and waited for up to --wait.
    deadline = time.monotonic() + max(0.0, args.wait or 0.0)
    while auto.window_open():
        if time.monotonic() >= deadline:
            raise contract.busy_error("junban-window", locks.read_holder("junban-window"),
                                      "The 順 window is open: Surasura leaves the order to you there. Try again once "
                                      "it's closed.")
        time.sleep(locks.POLL)
    argv = run_args.analyzer_args(junban_settings, lang, headless=True)
    done = auto.reorder(junban_settings, list_current=analyzer.journey_is_current(argv, lang), positions_only=True)
    outcome, report = done["outcome"], done.get("report") or {}
    if outcome == "needs-deck":
        raise CliError("needs-you", "The automatic reorder runs for one deck only: choose one in the 順 window.",
                       ask="choose a deck in 順")
    if outcome == "anki-closed":
        raise CliError("anki-closed", "Anki isn't open (or AnkiConnect isn't installed). Open Anki, then try again.")
    if outcome == "reviewing":
        raise CliError("anki-busy", "You're reviewing in Anki. Surasura reorders once you've finished.")
    if outcome == "busy":
        raise contract.busy_error("anki-writer", locks.read_holder("anki-writer"),
                                  (report.get("problems") or ["Another program is writing to Anki."])[0])
    if outcome == "list-stale":
        return {"language": lang, "moves": 0, "unchanged": 0, "not_on_list": 0, "undo": None,
                "skipped": "the list is out of date: Generate first"}
    if outcome in ("refused", "failed"):
        problem = (report.get("problems") or [done.get("error") or "it could not finish"])[0]
        raise CliError("failed", f"Junban did not make any changes: {problem}")
    stats = report.get("stats") or {}
    written = report.get("written") or []
    snapshot = report.get("snapshot")
    return {"language": lang, "moves": len(written), "unchanged": max(0, stats.get("total", 0) - len(written)),
            "not_on_list": stats.get("unmatched", 0),
            "undo": os.path.basename(snapshot) if snapshot and written else None}
