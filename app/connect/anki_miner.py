"""Calling Anki Miner (P1.3 row 1.3.5; API.md, the Integration Spec §4.1 and §4.4, 06-edges E7–E14 and W1).

Anki Miner is a separate program, called at arm's length: `AnkiMiner.exe --api <command>`, one JSON verdict on the
last line of stdout, exit 0 whenever a verdict was written (BUSY and SETUP_ERROR included); any other exit is a crash.
Its stdout is a pipe and its stderr goes nowhere (without a stdout handle its verdict is lost); every call has a
timeout and is killed at it; nothing opens a window (CREATE_NO_WINDOW).

- `find(settings)` — where it is: `connect_anki_miner_path`, then its installer's uninstall key (InstallLocation), then
  its default folder (%LOCALAPPDATA%\\Programs\\AnkiMiner). Absent -> None: the mine step is `skipped`, never an error.
- `version`, `profiles`, `check`, `settings_export` — read before every batch, never cached (E10: it updates itself).
- `mine_batch(...)` — one batch, holding Surasura's Anki-write lock (`anki-writer`, E1.4) from start to end: the
  version and `features` read again, the profile chosen (`choose_profile`), the whitelist file rewritten (N10, until
  Z-1), the run file written (`runfile`: from 3.7, one entry a word, its `surface` and reading — Z-2), `mine` called,
  its results read back as Surasura's outcomes (IS §4.4): `made` with the note id,
  `duplicate`, `not_found`, `no_definition`, `media_failed`, `refused`, `not_attempted`, `uncertain`. Each returned
  `line_start` is checked against the one sent: off by more than 0.05 s, the card took another line, and the row says
  so. Then the cards made for names get `surasura::name` (G1.3: Anki Miner's tags belong to an episode, never to one
  word): one `addTags`, still inside the hold; when Anki doesn't take it, the note ids come back as `tag_pending`, a
  step of its own Connect's ledger resumes (`tag_names`; the notes are findable by the job's tag).

Failures are AnkiMinerError with a `kind` the runner (P2.4) acts on: `busy` (its window is open, or another run works:
retry later, E8), `writer-busy` (another Surasura program writes Anki), `reviewing` (you're reviewing: E2), `anki-closed` (E1), `quarantined` (Windows Security blocked it: WinError 225, never retried
silently, W1), `crashed` / `timeout` (the batch is `uncertain`: checked in Anki by the job's tag before any retry,
E11/E14), `unknown-version` (a schema Surasura wasn't built for, E12), `refused` (a run file it refused), `setup` (its
setup is incomplete: `check`'s items name what), `absent`.
"""
import json
import os
import subprocess
import sys

from app.connect import runfile

API_SCHEMA = 1
QUICK_TIMEOUT = 60.0            # version / profiles / check / settings-export
MINE_TIMEOUT = 3 * 60 * 60.0    # one mine call (sim.py's 3 h; R03:249)
LINE_TOLERANCE = 0.05           # seconds: a returned line_start further off is another line (sim.py, IS:311)
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{15B09250-AC39-4792-A15A-B73BD8E218A1}_is1"
EXE = "AnkiMiner.exe"
CREATE_NO_WINDOW = 0x08000000
WINERROR_VIRUS = 225            # "Operation did not complete successfully because the file contains a virus"

# Anki Miner's `features` names (Z-4; 3.7.0 `cli/api/contract.py` FEATURES), and the ask each answers. A name not
# here is a later addition: ignored until Surasura knows it.
FEATURES = {"named-words-whitelisted": "Z-1", runfile.WORD_FROM_LINE: "Z-2", "settings-import": "Z-3",
            runfile.SENTENCE_RULES_OFF: "Z-4", runfile.BOLD_TARGET: "Z-5", "filter-names": "Z-6",
            runfile.DRY_RUN: "Z-7", "fetch": "Z-8", "render": "Z-10", "media": "Z-10", "setup": "Z-11",
            "script-fold": "Z-12", "beside-window": "Z-13"}

# A verdict's error code -> the kind Surasura acts on
KINDS = {"BUSY": "busy", "ANKI_UNREACHABLE": "anki-closed", "SETUP_ERROR": "setup", "PROFILE_UNREADABLE": "setup",
         "BAD_RUN_FILE": "refused", "BAD_ARGUMENTS": "refused", "SUBTITLE_UNREADABLE": "unreadable",
         "VIDEO_UNREADABLE": "unreadable", "MINING_FAILED": "failed", "CANCELLED": "cancelled",
         "INTERNAL": "crashed"}

# The outcome of each status (IS §4.4)
OUTCOMES = {"created": "made", "duplicate": "duplicate", "not_found": "not_found", "no_definition": "no_definition",
            "media_failed": "media_failed", "refused": "refused", "not_attempted": "not_attempted",
            "uncertain": "uncertain"}
# A run that stopped with one of these and wrote no result never reached Anki: refused, never uncertain
BEFORE_ANKI = frozenset(("VIDEO_UNREADABLE", "SUBTITLE_UNREADABLE", "ANKI_UNREACHABLE", "SETUP_ERROR",
                         "PROFILE_UNREADABLE", "BAD_RUN_FILE", "CANCELLED"))
# When a word went as two entries (its card front, and Surasura's Word), the better outcome is the word's
_BEST = ("made", "duplicate", "uncertain", "media_failed", "refused", "no_definition", "not_attempted", "not_found")


class AnkiMinerError(Exception):
    """A call that gave no usable verdict, or a verdict refusing the work: `kind` (above), `message` (plain words or
    Anki Miner's own), `code` (Anki Miner's error code, when it gave one)."""

    def __init__(self, kind, message, code=None, verdict=None):
        super().__init__(message)
        self.kind, self.message, self.code, self.verdict = kind, message, code, verdict


# --------------------------------------------------------------------------- #
# Finding it
# --------------------------------------------------------------------------- #
def _registry_location():
    """InstallLocation from Anki Miner's per-user uninstall key (its Inno installer is per-user only), or None."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            return winreg.QueryValueEx(key, "InstallLocation")[0] or None
    except OSError:
        return None


def _default_location():
    base = os.environ.get("LOCALAPPDATA")
    return os.path.join(base, "Programs", "AnkiMiner") if base and sys.platform == "win32" else None


def find(settings):
    """The path of Anki Miner's program, or None when it isn't installed (E7)."""
    chosen = str((settings or {}).get("connect_anki_miner_path") or "").strip()
    if chosen:
        return chosen if os.path.isfile(chosen) else None
    if os.environ.get("SURASURA_TEST_ROOT"):
        return None             # a test (and a child it starts) never finds, let alone runs, a real Anki Miner
    for folder in (_registry_location(), _default_location()):
        if folder and os.path.isfile(os.path.join(folder, EXE)):
            return os.path.join(folder, EXE)
    return None


def _command(path):
    # A .py is run by this Python: the tests' fake Anki Miner (tests/connect/fake_anki_miner.py), a source checkout.
    return [sys.executable, path] if path.lower().endswith(".py") else [path]


# --------------------------------------------------------------------------- #
# One call
# --------------------------------------------------------------------------- #
def _stop(proc):
    """Stop a call past its timeout with every process it started (Anki Miner's ffmpeg children too)."""
    if sys.platform == "win32":
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
                           creationflags=CREATE_NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            pass
    proc.kill()
    proc.communicate()


def api(path, args, timeout=QUICK_TIMEOUT):
    """Run `<path> --api <args…>` and return its verdict (a dict). Raises AnkiMinerError for a call with no verdict
    (absent, quarantined, crashed, timeout, unknown-version); a verdict with `ok: false` is returned as it is."""
    flags = CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        proc = subprocess.Popen(_command(path) + ["--api", *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, creationflags=flags)
    except FileNotFoundError:
        raise AnkiMinerError("absent", "Anki Miner isn't installed where Surasura looked.") from None
    except OSError as e:
        if getattr(e, "winerror", None) == WINERROR_VIRUS:
            raise AnkiMinerError("quarantined", "Windows Security blocked Anki Miner. Check Windows Security → "
                                 "Protection history, then allow it if you trust it.") from None
        raise AnkiMinerError("crashed", f"Anki Miner couldn't be started: {e}") from None
    try:
        stdout, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _stop(proc)
        raise AnkiMinerError("timeout", f"Anki Miner didn't answer within {int(timeout)} s, so it was stopped.") \
            from None
    lines = [line for line in stdout.decode("ascii", "replace").splitlines() if line.strip()]
    if proc.returncode != 0 or not lines:
        raise AnkiMinerError("crashed", f"Anki Miner stopped without an answer (exit code {proc.returncode}).")
    try:
        verdict = json.loads(lines[-1])
    except ValueError:
        raise AnkiMinerError("crashed", "Anki Miner's answer couldn't be read.") from None
    if not isinstance(verdict, dict) or verdict.get("schema") != API_SCHEMA:
        raise AnkiMinerError("unknown-version", "This Anki Miner isn't one Surasura has been checked with. "
                             "Update Surasura, or wait for an update that knows it.", verdict=verdict)
    return verdict


def _result(verdict):
    if not verdict.get("ok"):
        code = verdict.get("error")
        raise AnkiMinerError(KINDS.get(code, "failed"), verdict.get("message") or code or "Anki Miner refused.",
                             code=code, verdict=verdict)
    return verdict.get("result") or {}


def version(path):
    """{"app", "schema", "commands", "features"}: what this Anki Miner is and can do (read every batch, E10)."""
    result = _result(api(path, ["version"]))
    if result.get("schema") != API_SCHEMA:
        raise AnkiMinerError("unknown-version", f"Anki Miner {result.get('app')} isn't one Surasura has been "
                             "checked with. Update Surasura, or wait for an update that knows it.")
    result.setdefault("features", [])
    return result


def features(info):
    """The Z-asks this Anki Miner says it answers (from `version`'s `features`)."""
    return {FEATURES[name] for name in info.get("features") or () if name in FEATURES}


def profiles(path):
    return _result(api(path, ["profiles"])).get("profiles") or []


def check(path, language, profile=None):
    """`check`'s {"ready", "items"} for `language` under `profile`."""
    args = ["check", "--language", language] + (["--profile", profile] if profile else [])
    return _result(api(path, args))


def settings_export(path, language, out, profile=None):
    """The export `--api settings-export` writes to `out`, read back."""
    args = ["settings-export", "--language", language, "--out", out] + (["--profile", profile] if profile else [])
    _result(api(path, args))
    try:
        with open(out, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise AnkiMinerError("crashed", f"Anki Miner's settings export couldn't be read: {e}") from None


def profile_id(listed, name):
    """The id of the profile called `name` (or with that id) among `profiles`' list, or None (E9)."""
    for entry in listed:
        if name in (entry.get("id"), entry.get("name")):
            return entry.get("id")
    return None


def choose_profile(info, listed, name):
    """The Anki Miner profile Connect mines with: the id of the one `connect_anki_miner_profile` names when Anki Miner
    has it; else, once every named word is whitelisted (Z-1, 3.7), None — Anki Miner's active profile, your usual one
    (Sonic, 2026-10-07: the separate profile is optional). Before Z-1 the named profile is needed (its whitelist is how
    the named words pass the name lists, IS-R3, N10): AnkiMinerError `needs-you` when it's missing (E9)."""
    found = profile_id(listed, name) if name else None
    if found is not None or "Z-1" in features(info):
        return found
    raise AnkiMinerError("needs-you", f'Anki Miner has no profile called "{name or "Surasura"}". Make it once in Anki '
                         "Miner (a copy of your profile, its whitelist on), as Surasura's Connections page shows.")


# --------------------------------------------------------------------------- #
# The whitelist file (N10): until Z-1, how the named words pass Anki Miner's name lists
# --------------------------------------------------------------------------- #
def whitelist_path(language):
    from app.path_utils import get_local_data_path
    return os.path.join(get_local_data_path(), "connect", f"whitelist-{language}.txt")


def write_whitelist(language, names):
    """Rewrite `whitelist-<lang>.txt` with this batch's names, one a line, UTF-8 without a BOM, atomically. The
    "Surasura" profile points its whitelist at this file (set up once, P1.5-14)."""
    path = whitelist_path(language)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(f"{name}\n" for name in dict.fromkeys(names)))
    os.replace(tmp, path)
    return path


# --------------------------------------------------------------------------- #
# A batch
# --------------------------------------------------------------------------- #
def cancel(run_dir, run_id):
    """Ask a running (or queued) episode to stop: Anki Miner polls `<run_dir>/<run_id>/cancel` every 0.2 s."""
    folder = os.path.join(run_dir, run_id)
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "cancel"), "a").close()


def result_names(run_dir, run_id):
    """The `result-<n>.json` files a run's folder holds now."""
    try:
        return {name for name in os.listdir(os.path.join(run_dir, run_id))
                if name.startswith("result-") and name.endswith(".json") and name[7:-5].isdigit()}
    except OSError:
        return set()


def read_result(run_dir, run_id, name=None, before=()):
    """A run's result: the file its verdict names, else the newest written since `before` (the names there were
    before the call: an older attempt's result is never taken for this one) — or None. A file that can't be read is
    AnkiMinerError `crashed`: the batch is then checked in Anki by its tag."""
    if name is None:
        fresh = sorted(result_names(run_dir, run_id) - set(before), key=lambda n: int(n[7:-5]))
        if not fresh:
            return None
        name = fresh[-1]
    try:
        with open(os.path.join(run_dir, run_id, os.path.basename(name)), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise AnkiMinerError("crashed", f"Anki Miner's result couldn't be read: {e}") from None


def outcomes(words, rows, run_failed=False, features=()):
    """Surasura's outcome for each picked word (pick's `words`), from one run's result rows — one row per entry
    (`runfile.entries` under these `features`), in the run file's order: [{word, reading, outcome, note_id, mined_form,
    line_start, returned_start, other_line, from_line, filter, statuses}]. A word sent as two entries takes the better
    one. `from_line`: made from its line (Z-2, counted as made); `filter`: why Anki Miner dropped it, where it says
    (Z-6, `duplicate-expression`). No rows at all (the run wrote no result) is `uncertain` when the run failed (it may
    have written to Anki), `not_attempted` otherwise."""
    rows, out, at = list(rows or ()), [], 0
    for word in words:
        names = runfile.entries(word, features)
        mine = rows[at:at + len(names)]
        at += len(names)
        # a row that isn't the entry it stands for (another build's order or count) proves nothing: uncertain
        statuses = [OUTCOMES.get(row.get("status"), "uncertain") if row.get("word") == name else "uncertain"
                    for row, name in zip(mine, names)] or ["uncertain" if run_failed else "not_attempted"]
        outcome = min(statuses, key=_BEST.index)
        row = next((r for r, s in zip(mine, statuses) if s == outcome), {})
        returned = row.get("line_start")
        other = returned is not None and abs(float(returned) - float(word["line_start"])) > LINE_TOLERANCE
        out.append({"word": word["word"], "reading": word["reading"], "outcome": outcome,
                    "note_id": row.get("note_id"), "mined_form": row.get("mined_form"),
                    "line_start": word["line_start"], "returned_start": returned, "other_line": other,
                    "from_line": row.get("from_line") is True, "filter": row.get("filter"),
                    "statuses": {r.get("word"): r.get("status") for r in mine}})
    return out


def preflight(path, language, profile_name):
    """Before every batch (E9, E10): what this Anki Miner is (`version`, never cached), the id of the profile Connect
    mines with (`choose_profile`; None: the active one), and its `check` for the language. Raises AnkiMinerError:
    `needs-you` when an Anki Miner before 3.7 has no such profile, `anki-closed` when Anki isn't reachable, `setup`
    naming what Anki Miner's own setup lacks."""
    info = version(path)
    profile = choose_profile(info, profiles(path), profile_name)
    ready = check(path, language, profile)
    items = {item.get("name"): item for item in ready.get("items") or ()}
    if items.get("anki") and not items["anki"].get("ok"):
        raise AnkiMinerError("anki-closed", "Anki isn't open (or AnkiConnect isn't installed).")
    if not ready.get("ready"):
        missing = [f"{name}: {item.get('message') or 'not ready'}" for name, item in items.items()
                   if not item.get("ok")]
        raise AnkiMinerError("setup", "Anki Miner's setup isn't finished — " + "; ".join(missing))
    return info, profile


def tag_names(url, words, outcomes):
    """Add `surasura::name` to the cards made for names (pick marks each `name`): one `addTags`. The caller holds
    `anki-writer`. Returns the note ids tagged; raises anki_connect.AnkiError when Anki refuses or is gone."""
    from app import anki_connect
    ids = [o["note_id"] for w, o in zip(words, outcomes)
           if w.get("name") and o["outcome"] == "made" and o.get("note_id") is not None]
    if ids:
        anki_connect.invoke("addTags", url, notes=ids, tags=runfile.NAME_TAG)
    return ids


def mine_batch(path, language, job, video, subtitle, words, mapping, profile_name, run_dir, url, attempt=1,
               subtitle_offset=0.0, timeout=MINE_TIMEOUT, wait=0.0):
    """One batch of one episode, end to end (§ above), holding `anki-writer` (waiting up to `wait` s for another
    writer; still held -> AnkiMinerError `busy`). `words`: pick's; `mapping`: fields.Mapping (from this profile's
    export); `profile_name`: `connect_anki_miner_profile`; `url`: AnkiConnect's address, for the names' tag. Returns
    {"run_file", "run", "result", "outcomes", "app", "features", "tagged", "tag_pending"}; raises AnkiMinerError
    (busy, anki-closed, needs-you, setup, refused, crashed …)."""
    from app import anki_connect, locks
    try:
        held = anki_connect.writer("Connect's mine step", wait=wait)
    except locks.Busy as e:
        raise AnkiMinerError("writer-busy", anki_connect.busy_message(e)) from None
    with held:
        if anki_connect.reviewing(url):         # E2: never a write while you review, checked inside the hold
            raise AnkiMinerError("reviewing", "You're reviewing in Anki. Cards are made once you've finished.")
        try:
            done = _mine_held(path, language, job, video, subtitle, words, mapping, profile_name, run_dir, attempt,
                              subtitle_offset, timeout)
        except runfile.RunFileError as e:
            raise AnkiMinerError("refused", f"The run file for Anki Miner couldn't be written: {e}") from None
        done["tagged"], done["tag_pending"] = [], []
        try:
            if anki_connect.reviewing(url):
                raise anki_connect.AnkiError(anki_connect.REVIEWING, "refused")
            done["tagged"] = tag_names(url, words, done["outcomes"])
        except anki_connect.AnkiError:
            done["tag_pending"] = [o["note_id"] for w, o in zip(words, done["outcomes"])
                                   if w.get("name") and o["outcome"] == "made" and o.get("note_id") is not None]
        return done


def _mine_held(path, language, job, video, subtitle, words, mapping, profile_name, run_dir, attempt,
               subtitle_offset, timeout):
    info, profile = preflight(path, language, profile_name)
    asks, named = features(info), info.get("features")
    if "Z-1" not in asks:
        write_whitelist(language, [name for word in words for name in runfile.entries(word, named)])
    run_id = f"{job}-{attempt}"
    episode = runfile.episode(run_id, video, subtitle, runfile.word_requests(words, named),
                              tags=runfile.job_tag(job), subtitle_offset=subtitle_offset)
    data = runfile.build(run_dir, language, [episode], profile=profile,
                         run_config=runfile.config(mapping, info.get("app"), named))
    run_path = runfile.write(os.path.join(run_dir, f"run-{attempt}.json"), data)
    before = result_names(run_dir, run_id)
    done = {"run_file": run_path, "run": None, "result": None, "app": info.get("app"), "features": sorted(asks),
            "error": None}
    try:
        verdict = api(path, ["mine", run_path], timeout=timeout)
        refused = (not verdict.get("ok") and verdict.get("error") == "BAD_RUN_FILE"
                   and any(k in (verdict.get("message") or "") for k in runfile.SENTENCE_KEYS))
        if refused and any(k in data.get("config", {}) for k in runfile.SENTENCE_KEYS):
            # A build that refuses the two sentence keys while it reports 3.6 (am-upstream D1): once more without them
            run_path = done["run_file"] = runfile.write(run_path, runfile.without_sentence_keys(data))
            verdict = api(path, ["mine", run_path], timeout=timeout)
    except AnkiMinerError as e:
        # A crash or a timeout after the run: Anki Miner writes the result before its verdict, so a complete one
        # may be there. Without it, the batch is uncertain: the caller checks Anki by the job's tag (E11, E14).
        if e.kind not in ("crashed", "timeout"):
            raise
        result = read_result(run_dir, run_id, before=before)
        if result is None:
            raise
        done.update(result=result, error=e.kind, outcomes=outcomes(words, result.get("words"), True, named))
        return done
    run = next((r for r in verdict.get("runs") or [] if r.get("run_id") == run_id), None)
    if not verdict.get("ok") and run is None:
        result = read_result(run_dir, run_id, before=before) if verdict.get("error") == "INTERNAL" else None
        if result is None:
            _result(verdict)                # a refusal of the whole call: busy, anki-closed, refused, setup …
        done.update(result=result, error="crashed", outcomes=outcomes(words, result.get("words"), True, named))
        return done
    if run is not None and not run.get("ok") and not run.get("file") and run.get("error") in BEFORE_ANKI:
        # stopped before anything reached Anki (a video or subtitle it can't read, Anki gone at its own check,
        # cancelled before the run began): nothing is uncertain; the batch is refused with its reason
        raise AnkiMinerError(KINDS.get(run["error"], "failed"), run.get("message") or run["error"], code=run["error"])
    result = read_result(run_dir, run_id, run["file"]) if run is not None and run.get("file") else None
    done.update(run=run, result=result,
                outcomes=outcomes(words, (result or {}).get("words"), run is None or not run.get("ok"), named))
    return done


def tag_query(tag):
    """A search for one tag as written: Anki reads _ and * in a search as wildcards."""
    from app import anki_connect
    return 'tag:"' + anki_connect.escape_query(tag).replace("_", "\\_").replace("*", "\\*") + '"'


def uncertain_by_tag(url, job, words, word_field):
    """After a crash or a timeout (E11, E14): which words did reach Anki? Reads the notes carrying the job's tag
    (read-only) and marks a word `made` when a note's word field holds one of its names, its Word or its spelling —
    or the kana fold of one: Anki Miner writes the form it placed the word by, which can be the dictionary form
    rather than the name sent. Returns outcomes as `outcomes` does, the rest left `uncertain`."""
    from app import anki_connect, anki_match
    ids = anki_connect.find_notes(url, tag_query(runfile.job_tag(job)))
    notes = anki_connect.notes_info(url, ids) if ids else []
    made = {}
    for note in notes:
        value = ((note.get("fields") or {}).get(word_field) or {}).get("value")
        if value:
            value = anki_match.card_word(value) or value.strip()
            made.setdefault(value, note.get("noteId"))
            made.setdefault(anki_match.fold_kana(value), note.get("noteId"))
    out = []
    for word in words:
        names = [n for n in (*word["sent"], word["word"], word.get("orth")) if n]
        names += [anki_match.fold_kana(n) for n in names]
        note_id = next((made[n] for n in names if n in made), None)
        out.append({"word": word["word"], "reading": word["reading"],
                    "outcome": "made" if note_id is not None else "uncertain", "note_id": note_id,
                    "mined_form": None, "line_start": word["line_start"], "returned_start": None,
                    "other_line": False, "from_line": False, "filter": None, "statuses": {}})
    return out
