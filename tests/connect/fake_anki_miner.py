"""A fake Anki Miner for the tests (P1.5 07-tests §1): the `--api` contract as API.md documents it for 3.5.0 / 3.6.0,
and 3.7.0's additions where the plan's `features` names them (as 3.7.0 `cli/api/files.py`, `settings.py` check them:
`surface` / `reading` on a word with `word-from-line`, `bold_target_in_sentence` with `bold-target`, `dry_run` with
`dry-run`, the two sentence keys only as false with `sentence-rules-off`; each row's `from_line` and `filter`). Run as
a child process exactly as the real one is (`AnkiMiner.exe --api <command> …`), and never Anki, never media.

What it does is read from the plan file named by FAKE_ANKI_MINER_PLAN (JSON; every key optional):

    {"app": "3.5.0", "schema": 1, "features": [],        # `version`'s answer (schema ≠ 1: an unknown version)
     "profiles": [{"id": "default", "name": "Default"}, {"id": "p-surasura", "name": "Surasura"}],
     "check": {"ready": true, "items": [...]},            # `check`'s answer
     "export": {...},                                      # what `settings-export` writes to --out
     "mine": "ok" | "busy" | "anki-closed" | "crash" | "hang" | "no-stdout" | "refuse-sentence-keys"
             | "mining-failed" | "garbage" | "video-unreadable" | "crash-after-result" | "internal-after-result",
     "statuses": {"<word>": "<status>"},                   # each named word's status (default created)
     "shift": {"<word>": 1.5},                             # seconds added to a word's returned line_start
     "fail_after": 2,                                      # mining-failed: rows past this many are uncertain
     "forms": {"<word>": "<mined_form>"},                  # a word Anki Miner placed by another form
     "from_line": ["<word>"],                              # (word-from-line) made from its named line
     "filter": {"<word>": "duplicate-expression"},         # (filter-names) why a not_found word was dropped
     "replay": {"<command>": {...}},                       # answer a command with a recorded verdict, as it is
     "progress": [[1, 5, 0, 0], [3, 5, 2, 6], …],         # each episode's progress.json, written in turn …
     "progress_every": 0.3,                                # … this many seconds apart (API.md's stage/stages/done/total)
     "cancel_at": 1}                                       # waits (≤ 5 s) for the run's cancel file before this row:
                                                           # 0 -> CANCELLED, no result; n -> rows from n not_attempted
    {"slow": {"<command>": 30}}                            # row 56: sleeps this long before it answers that command
    {"export_cut": true}                                   # row 56: half its export written, then it hangs
    {"clear_leftovers": 0.3}                               # 3.10: this long after it starts, before its setup, an
                                                           # unconsumed cancel file is deleted once (runfolder.py)
    {"media": true,                                        # #BS0A1K: a clip in the run's media folder (its stage 3)
     "deaf": 30}                                           # … then, after its progress rows, this long in a step that
                                                           # never reads the cancel file (3.11's whole-book parse)

Round 2's Z-9 (`reading` in `features`; the request's own JSON, `tracks/pipeline/work/AM-round2/send/`): an episode
may name `reading_file` instead of `video_file` + `subtitle_file`, a word `unit_index` beside `line_text`; each row of a
reading episode adds `unit_index` and `location`, its `line_start` / `start` / `end` null, its `sentence` the unit's:

    {"units": [{"index": 0, "location": "一", "text": "吾輩は猫である。"}, ...],  # the source's units (Z-19's list);
                                                           # none: a .txt's sentences, each at location "ch.0"
     "mine": "source-unreadable"}                          # SOURCE_UNREADABLE before any Anki write, no result
    {"cover": true, "chapters": [{"title": "一", "index": 0}]}   # `inspect` (Z-19, with `inspect` in features):
                                                           # each source's answer; "units": true writes inspect-<n>.json

Round 2's Z-16 (`audio-episodes` in `features`, 3.11.0 `cli/api/files.py`): an episode may name `audio_file` instead of
`video_file` (with its `subtitle_file`; exactly one of the three), as a video episode's keys otherwise:

    {"mine": "audio-unreadable"}                           # AUDIO_UNREADABLE before any Anki write, no result

Z-24 (`extract`, 3.11; Michi-ST): a video named in "tracks" is inspected as a video (its `tracks`, API.md § inspect),
and `extract` copies a track's text as the plan gives it into `<run_dir>/<run_id>/extract-1/` with `extract-1.json`:

    {"tracks": {"<video file name>": [{"index": 2, "kind": "subtitle", "codec": "ass", "language": "jpn",
                                       "title": null, "default": true, "forced": false, "text": true}, ...]
                                      | "VIDEO_UNREADABLE"},       # that source's error
     "track_files": {"<video file name>#<index>": "<the track's text>"},   # .ass unless the codec says srt / webvtt
     "track_errors": {"<video file name>#<index>": "TRACK_NOT_TEXT"},      # that run's error
     "extract": "setup-error",                             # the whole call refused (no ffmpeg)
     "extract_warning": "…"}                               # ffmpeg's note on every run (a damaged source)

Michi-AB Stage B (3.11's Z-17 `sync`, Z-22 `setup --speech-model`, Z-18 `transcribe`, Z-10 `media` of an audio file):
the speech models installed live in the test's Anki Miner home (`ANKI_MINER_HOME/fake-models.json`: {"installed": [..],
"profiles": {id: model}, "model"}); `check` names `speech_model` ok while the profile's model is installed;
`settings-import` of `asr_model` sets a profile's model; `setup --speech-model --model M` installs M (and sets it).

    {"speech": {"installed": ["small"], "model": "large-v3"},   # the home as it starts (else none installed, large-v3)
     "speech_setup": "installed" | "failed" | "busy" | "hang",  # setup's outcome (hang: until its cancel file, <= 5 s)
     "sync": {"files": {"<audio file name>": {"status": "synced", "srt": "<the SRT's text>"}},   # each file's answer
              "report": {"grade": "A", "sentence_pct": 93, "audio_pct": 94, "unheard": []},
              "error": "SETUP_ERROR" | "SOURCE_UNREADABLE" | ...,  # the run's error (SETUP_ERROR: the whole call)
              "hold": 2.0},                                       # seconds it runs (progress written, cancel seen)
     "heard": {"<clip's line text start>": "<what the speech model hears>"},  # `transcribe` of a `media` clip
     "deaf": true}                                                  # `transcribe` hears nothing it was given

Every call is appended to FAKE_ANKI_MINER_LOG (one JSON line: argv, and the run file's bytes' facts for `mine`), so a
test can see what was asked and in what order; so is each progress step it couldn't write (`progress_skipped`, as
Anki Miner warns and goes on). The run file is checked as Anki Miner checks it: strict UTF-8 with no
BOM, the 3.5.0 keys only (and, with refuse-sentence-keys, main's refusal of the two sentence keys).
"""
import json
import os
import re
import shutil
import sys
import time

RUN_KEYS = {"schema", "run_dir", "profile", "language", "config", "episodes"}
EPISODE_KEYS = {"run_id", "video_file", "subtitle_file", "subtitle_offset", "audio_track_override",
                "source_label_override", "secondary_subtitle_file", "secondary_subtitle_offset", "series_name_override",
                "episode_name_override", "tags", "words"}
WORD_KEYS = {"word", "line_start", "line_text", "line_expansion"}
AUDIO_EPISODE_KEYS = EPISODE_KEYS - {"video_file"} | {"audio_file"}
READING_EPISODE_KEYS = {"run_id", "reading_file", "source_label_override", "series_name_override",
                        "episode_name_override", "tags", "words"}
# 3.7.0 (contract.py FEATURES): what each name adds to what the run file may hold
FEATURES_37 = ["sentence-rules-off", "bold-target", "named-words-whitelisted", "script-fold", "filter-names",
               "word-from-line", "dry-run", "render", "media", "settings-import", "setup", "fetch", "beside-window"]
CONFIG_KEYS = {"anki_deck_name", "anki_note_type", "anki_fields", "card_type", "card_type_marker_fields",
               "allow_duplicate_cards", "merge_incomplete_cues", "max_parallel_workers", "min_frequency_rank",
               "max_frequency_rank", "use_blacklist", "use_whitelist", "deduplicate_sentences", "use_i_plus_one_filter",
               "max_sentence_duration_seconds", "max_sentence_chars", "exclude_hiragana_only_words",
               "exclude_katakana_only_words"}
SENTENCE_KEYS = ("deduplicate_sentences", "use_i_plus_one_filter")

LAPIS_EXPORT = {"anki_miner_settings": 1, "app_version": "3.5.0", "config_schema_version": 9, "configured": True,
                "settings": {"anki_deck_name": "DevTest", "anki_note_type": "Lapis",
                             "anki_fields": {"word": "Expression", "sentence": "Sentence",
                                             "definition": "MainDefinition", "glossary": "", "picture": "Picture",
                                             "audio": "SentenceAudio", "source": "MiscInfo", "frequency_sort": ""}}}


def _plan():
    path = os.environ.get("FAKE_ANKI_MINER_PLAN")
    if not path:
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _log(entry):
    path = os.environ.get("FAKE_ANKI_MINER_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _ok(command, **fields):
    return {"schema": 1, "command": command, "ok": True, "error": None, "message": None, **fields}


def _failed(command, code, message):
    return {"schema": 1, "command": command, "ok": False, "error": code, "message": message, "runs": []}


def _say(verdict):
    sys.stdout.write(json.dumps(verdict, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def _read_run_file(path, plan):
    raw = open(path, "rb").read()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("a BOM")
    data = json.loads(raw.decode("utf-8"))          # strict: a lone surrogate in the bytes refuses here
    features = set(plan.get("features", []))
    run_keys = RUN_KEYS | ({"dry_run"} if "dry-run" in features else set())
    if set(data) - run_keys:
        raise ValueError(f"unknown keys {sorted(set(data) - run_keys)}")
    if data.get("schema") != 1 or not {"run_dir", "language", "episodes"} <= set(data):
        raise ValueError("schema must be 1; run_dir, language and episodes are required")
    if not isinstance(data.get("dry_run", False), bool):
        raise ValueError("dry_run must be true or false.")
    if not os.path.isdir(data["run_dir"]):
        raise ValueError("run_dir must be an existing folder")
    config = data.get("config", {})
    if not isinstance(config, dict):
        raise ValueError("config must be an object")
    allowed = CONFIG_KEYS - (set(SENTENCE_KEYS) if plan.get("mine") == "refuse-sentence-keys" else set())
    allowed |= {"bold_target_in_sentence"} if "bold-target" in features else set()
    if set(config) - allowed:
        raise ValueError(f"These config keys are not allowed: {', '.join(sorted(set(config) - allowed))}")
    if "sentence-rules-off" in features and any(config.get(k, False) is not False for k in SENTENCE_KEYS):
        raise ValueError("deduplicate_sentences is always off for API runs: send false, or leave it out.")
    word_keys = WORD_KEYS | ({"surface", "reading"} if "word-from-line" in features else set())
    word_keys |= {"unit_index"} if "reading" in features else set()
    for episode in data["episodes"]:
        if "reading" in features and "reading_file" in episode:
            if set(episode) - READING_EPISODE_KEYS or not {"run_id", "reading_file", "words"} <= set(episode):
                raise ValueError("unknown or missing episode keys")
        elif "audio-episodes" in features and "audio_file" in episode:
            if set(episode) - AUDIO_EPISODE_KEYS or not {"run_id", "audio_file", "subtitle_file", "words"} <= \
                    set(episode):
                raise ValueError("unknown or missing episode keys")
        elif set(episode) - EPISODE_KEYS or not {"run_id", "video_file", "subtitle_file", "words"} <= set(episode):
            raise ValueError("unknown or missing episode keys")
        if not isinstance(episode.get("tags", ""), str) or not isinstance(episode.get("subtitle_offset", 0.0), float):
            raise ValueError("tags must be a string, subtitle_offset a number")
        if not episode.get("words"):
            raise ValueError("words must list at least one word")
        for word in episode["words"]:
            if set(word) - word_keys or not isinstance(word.get("word"), str):
                raise ValueError("unknown word keys")
            for key in ("surface", "reading"):
                if key in word and (not isinstance(word[key], str) or not word[key].strip()):
                    raise ValueError(f"words.{key} is empty.")
            expansion = word.get("line_expansion")
            if expansion is not None and not (isinstance(expansion, list) and len(expansion) == 2 and all(
                    isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in expansion)):
                raise ValueError("line_expansion must be [before, after]")
            if word.get("line_start") is not None and not isinstance(word["line_start"], float):
                raise ValueError("line_start must be a number")
            unit = word.get("unit_index")
            if "unit_index" in word and (isinstance(unit, bool) or not isinstance(unit, int) or unit < 0):
                raise ValueError("unit_index must be a whole number of 0 or more")
    return data


def _units(path, plan):
    """A reading source's units: the plan's, else a .txt's sentences (each at "ch.0"); a file that isn't there: None."""
    if not os.path.isfile(path):
        return None
    if "units" in plan:
        return plan["units"]
    if not path.lower().endswith(".txt"):
        return []
    with open(path, encoding="utf-8") as f:
        text = "".join(f.read().split())
    out, at = [], 0
    for n, ch in enumerate(text):
        if ch in "。！？":
            out.append({"index": len(out), "location": "ch.0", "text": text[at:n + 1]})
            at = n + 1
    if text[at:]:
        out.append({"index": len(out), "location": "ch.0", "text": text[at:]})
    return out


def _unit_of(request, units):
    """The unit a word names: its `unit_index`, else the first unit holding its `line_text` (whitespace ignored)."""
    if isinstance(request.get("unit_index"), int):
        return next((u for u in units if u["index"] == request["unit_index"]), None)
    line = "".join(str(request.get("line_text") or "").split())
    return next((u for u in units if line and (line in "".join(u["text"].split())
                                               or "".join(u["text"].split()) in line)), None)


def _mine(argv, plan):
    how = plan.get("mine", "ok")
    if how == "busy":
        return _failed("mine", "BUSY", "Anki Miner is already running (its window is open).")
    if how == "anki-closed":
        return _failed("mine", "ANKI_UNREACHABLE", "AnkiConnect did not answer.")
    try:
        data = _read_run_file(argv[1], plan)
    except (OSError, ValueError, UnicodeDecodeError) as e:
        return _failed("mine", "BAD_RUN_FILE", str(e))
    _log({"run_file": data})
    if plan.get("clear_leftovers") is not None:            # Anki Miner 3.10's `clear_leftovers`, once per call
        time.sleep(plan["clear_leftovers"])
        for episode in data["episodes"]:
            try:
                os.remove(os.path.join(data["run_dir"], episode["run_id"], "cancel"))
                _log({"cleared": episode["run_id"]})
            except OSError:
                pass
    if how == "crash":
        sys.exit(3)
    if how == "hang":
        time.sleep(60)
    if how == "video-unreadable":       # refused at its own check, before any Anki write: no result file
        runs = [{"run_id": e["run_id"], "ok": False, "error": "VIDEO_UNREADABLE",
                 "message": f"The video cannot be opened: {e['video_file']}", "file": None} for e in data["episodes"]]
        return {**_ok("mine", runs=runs), "ok": False}
    if how == "audio-unreadable":       # Z-16: the audio file doesn't open, before any Anki write: no result file
        runs = [{"run_id": e["run_id"], "ok": False, "error": "AUDIO_UNREADABLE",
                 "message": f"The audio file cannot be opened: {e.get('audio_file')}", "file": None}
                for e in data["episodes"]]
        return {**_ok("mine", runs=runs), "ok": False}
    readings = {e["run_id"]: _units(e["reading_file"], plan) for e in data["episodes"] if "reading_file" in e}
    if how == "source-unreadable" or any(units is None for units in readings.values()):
        runs = [{"run_id": e["run_id"], "ok": False, "error": "SOURCE_UNREADABLE",
                 "message": "The book has no readable text (DRM?)", "file": None} for e in data["episodes"]]
        return {**_ok("mine", runs=runs), "ok": False}
    runs, made_from_line = [], "word-from-line" in plan.get("features", [])
    dry = data.get("dry_run") is True
    for episode in data["episodes"]:
        folder = os.path.join(data["run_dir"], episode["run_id"])
        os.makedirs(folder, exist_ok=True)
        for stage, stages, done, total in plan.get("progress") or ():     # as 3.9.0's ProgressFile writes it
            tmp = os.path.join(folder, "progress.json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"schema": 1, "run_id": episode["run_id"], "stage": stage, "stages": stages, "done": done,
                           "total": total}, f)
            try:
                os.replace(tmp, os.path.join(folder, "progress.json"))
            except OSError as e:
                # on Windows a replace onto a file Connect's poll holds open that instant is refused ([WinError 5]).
                # Anki Miner's own progress file write catches OSError, logs a warning and goes on (the file is a
                # hint): so does the fake, its warning a line in the call log, so a test sees each skipped step
                _log({"progress_skipped": [stage, stages, done, total], "error": type(e).__name__})
            time.sleep(plan.get("progress_every", 0.3))
        if plan.get("media"):
            os.makedirs(os.path.join(folder, "media"), exist_ok=True)
            open(os.path.join(folder, "media", "clip-1.mp3"), "wb").close()
        if plan.get("deaf"):
            _log({"deaf": episode["run_id"]})
            time.sleep(plan["deaf"])
            _log({"heard": episode["run_id"]})
        rows, note = [], 1727000000000
        cancelled = False
        for n, request in enumerate(episode["words"]):
            if plan.get("cancel_at") == n and not cancelled:
                cancelled = _cancel_seen(folder)
                if cancelled and n == 0:            # nothing reached Anki: CANCELLED, no result file
                    runs.append({"run_id": episode["run_id"], "ok": False, "error": "CANCELLED",
                                 "message": "Cancelled.", "file": None})
                    break
            status = plan.get("statuses", {}).get(request["word"], "created")
            if cancelled:
                status = "not_attempted"
            if how == "mining-failed" and n >= plan.get("fail_after", 0):
                status = "uncertain" if n == plan.get("fail_after", 0) else "not_attempted"
            if dry and status == "created":
                status = "ready"                    # a dry run: what it would mine, nothing written
            unit = None
            if episode["run_id"] in readings:      # Z-9: the word's unit, by its index or its line
                unit = _unit_of(request, readings[episode["run_id"]])
                if unit is None and status in ("created", "ready"):
                    status = "not_found"
            note += 1
            start = request.get("line_start")
            if start is not None:
                start += plan.get("shift", {}).get(request["word"], 0.0)
            form = plan.get("forms", {}).get(request["word"], request["word"])   # placed by its dictionary form
            row = {"word": request["word"], "mined_form": form if status != "not_found" else None,
                   "status": status, "note_id": note if status == "created" else None, "media_missing": [],
                   "line_start": start if status != "not_found" else None, "sentence": None, "start": start,
                   "end": None, "filter": plan.get("filter", {}).get(request["word"]) if status == "not_found" else None}
            if episode["run_id"] in readings:
                row.update(line_start=None, start=None, end=None, sentence=unit and unit["text"],
                           unit_index=unit and unit["index"], location=unit and unit["location"])
            if made_from_line:                      # 3.7: every row says whether its word was made from its line
                row["from_line"] = status not in ("not_found", "not_attempted") and \
                    request["word"] in plan.get("from_line", [])
            rows.append(row)
        if cancelled and not rows:
            continue
        if cancelled:
            result = {"schema": 1, "run_id": episode["run_id"], "outcome": "cancelled", "anki_write_state": "partial",
                      "failure_is_transient": False, "error": "CANCELLED", "message": "Cancelled.",
                      "media_store_failures": 0, "words": rows}
            name = "result-1.json"
            with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)
            runs.append({"run_id": episode["run_id"], "ok": False, "error": "CANCELLED", "message": "Cancelled.",
                         "file": name})
            continue
        failed = how == "mining-failed"
        result = {"schema": 1, "run_id": episode["run_id"], "outcome": "failed" if failed else "success",
                  "anki_write_state": "partial" if failed else "complete", "failure_is_transient": False,
                  "error": "MINING_FAILED" if failed else None, "message": "addNotes failed" if failed else None,
                  "media_store_failures": 0, "words": rows}
        if "dry-run" in plan.get("features", []):
            result["dry_run"] = dry
        numbers = [int(p[7:-5]) for p in os.listdir(folder) if p.startswith("result-") and p.endswith(".json")]
        name = f"result-{max(numbers, default=0) + 1}.json"
        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
        runs.append({"run_id": episode["run_id"], "ok": not failed, "error": "MINING_FAILED" if failed else None,
                     "message": "addNotes failed" if failed else None, "file": name})
    if how == "crash-after-result":     # a native crash at teardown: the result is written, the verdict never is
        sys.exit(3)
    if how == "internal-after-result":  # shared.close() raising after the runs: INTERNAL, runs []
        return _failed("mine", "INTERNAL", "RuntimeError: closing the lookup services failed")
    return {**_ok("mine", runs=runs), "ok": all(r["ok"] for r in runs)}


def _inspect(argv, plan):
    """Z-19 (`inspect` in features): each source's kind, title, units and chapter map; "units": true on a source also
    writes `inspect-<n>.json` (its units) in the run folder. No Anki, no lock."""
    with open(argv[1], encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for n, source in enumerate(data.get("sources") or (), 1):
        tracks = (plan.get("tracks") or {}).get(os.path.basename(source["path"]))
        if isinstance(tracks, str):                 # Z-24: a source's own error, the call still ok
            out.append({"path": source["path"], "kind": None, "error": tracks, "message": "cannot read it"})
            continue
        if tracks is not None:
            out.append({"path": source["path"], "kind": "video", "title": os.path.splitext(os.path.basename(
                source["path"]))[0], "units": None, "chapters": [], "needs": [], "warnings": [], "duration": 1420,
                "tracks": tracks, "file": None, "error": None, "message": None})
            continue
        units = _units(source["path"], plan)
        if units is None:
            return _failed("inspect", "SOURCE_UNREADABLE", f"Cannot read {source['path']}")
        out.append({"path": source["path"], "kind": "book", "title": os.path.splitext(os.path.basename(
            source["path"]))[0], "cover": bool(plan.get("cover")), "units": len(units),
            "chapters": plan.get("chapters", []), "needs": [], "warnings": []})
        if source.get("units"):
            with open(os.path.join(data["run_dir"], f"inspect-{n}.json"), "w", encoding="utf-8") as f:
                json.dump({"units": units}, f, ensure_ascii=False)
    return {**_ok("inspect"), "result": {"sources": out}}


_SUFFIX = {"ass": ".ass", "ssa": ".ass", "subrip": ".srt", "srt": ".srt", "webvtt": ".vtt"}


def _extract(argv, plan):
    """Z-24: each episode's track copied as the plan gives its text, or that run's error."""
    if plan.get("extract") == "setup-error":
        return _failed("extract", "SETUP_ERROR", "ffmpeg was not found")
    with open(argv[1], encoding="utf-8") as f:
        data = json.load(f)
    runs = []
    for episode in data.get("episodes") or ():
        run_id, video, index = episode["run_id"], episode["video_file"], episode["track"]
        name = f"{os.path.basename(video)}#{index}"
        tracks = (plan.get("tracks") or {}).get(os.path.basename(video))
        track = next((t for t in tracks if t.get("index") == index), None) if isinstance(tracks, list) else None
        error = (plan.get("track_errors") or {}).get(name) or (None if track is not None else "TRACK_NOT_FOUND")
        folder = os.path.join(data["run_dir"], run_id)
        if error is None and os.path.exists(os.path.join(folder, "cancel")):
            error = "CANCELLED"
        if error:
            runs.append({"run_id": run_id, "ok": False, "error": error, "message": error, "file": None,
                         "failure_is_transient": False})
            continue
        out_dir = os.path.join(folder, "extract-1")
        os.makedirs(out_dir, exist_ok=True)
        tag = f".{track['language']}" if track.get("language") not in (None, "und") else ""
        dest = os.path.join(out_dir, os.path.splitext(os.path.basename(video))[0] + tag +
                            _SUFFIX.get(track.get("codec"), ".srt"))
        with open(dest, "w", encoding="utf-8", newline="\n") as f:
            f.write((plan.get("track_files") or {}).get(name, ""))
        with open(os.path.join(folder, "extract-1.json"), "w", encoding="utf-8") as f:
            json.dump({"subtitle_file": dest, "language": track.get("language"), "codec": track.get("codec"),
                       "warning": plan.get("extract_warning")}, f, ensure_ascii=False)
        runs.append({"run_id": run_id, "ok": True, "error": None, "message": None, "file": "extract-1.json",
                     "failure_is_transient": False})
    return {**_ok("extract"), "ok": all(r["ok"] for r in runs), "runs": runs}


def _models():
    path = os.path.join(os.environ.get("ANKI_MINER_HOME") or ".", "fake-models.json")
    try:
        with open(path, encoding="utf-8") as f:
            return path, json.load(f)
    except (OSError, ValueError):
        return path, None


def _speech_state(plan):
    path, state = _models()
    if state is None:
        start = plan.get("speech") or {}
        state = {"installed": list(start.get("installed") or ()), "profiles": {},
                 "model": start.get("model", "large-v3")}
    return path, state


def _save_models(path, state):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f)


def _profile_of(argv):
    return argv[argv.index("--profile") + 1] if "--profile" in argv else "default"


def _speech_ok(argv, plan):
    _path, state = _speech_state(plan)
    model = state["profiles"].get(_profile_of(argv), state["model"])
    return model in state["installed"], model


def _check(argv, plan):
    answer = json.loads(json.dumps(plan.get("check", {"ready": True, "items": [
        {"name": "anki", "ok": True, "message": None}]})))
    if "speech" in plan or "speech_setup" in plan:
        ok, model = _speech_ok(argv, plan)
        answer["items"] = [i for i in answer.get("items") or () if i.get("name") != "speech_model"] + [
            {"name": "speech_model", "ok": ok, "message": None if ok else f"The speech model {model} is not installed."}]
    return _ok("check", result=answer)


def _settings_import(argv, plan):
    with open(argv[1], encoding="utf-8") as f:
        values = json.load(f)
    profile = argv[argv.index("--profile") + 1] if "--profile" in argv else None
    if profile is None or profile == plan.get("active_profile"):
        return _failed("settings-import", "BAD_ARGUMENTS", "settings-import never changes the active profile")
    if "asr_model" in values:
        path, state = _speech_state(plan)
        state["profiles"][profile] = values["asr_model"]
        _save_models(path, state)
    return _ok("settings-import", result={"profile": profile, "created": False, "invalid_fields": []})


def _setup(argv, plan):
    progress = argv[argv.index("--progress") + 1]
    model = argv[argv.index("--model") + 1] if "--model" in argv else None
    outcome = plan.get("speech_setup", "installed")
    if outcome == "busy":
        return _failed("setup", "BUSY", "Anki Miner's window is open")
    if outcome == "hang" and _cancel_seen(os.path.dirname(progress)):
        return {**_ok("setup"), "result": {"speech_model": {"name": model, "status": "not_attempted",
                                                            "message": None}}}
    if outcome == "failed":
        return {**_ok("setup"), "ok": False, "result": {"speech_model": {"name": model, "status": "failed",
                                                                         "message": "the download failed"}}}
    path, state = _speech_state(plan)
    if model not in state["installed"]:
        state["installed"].append(model)
    state["profiles"][_profile_of(argv)] = model
    _save_models(path, state)
    return {**_ok("setup"), "result": {"speech_model": {"name": model, "status": "installed", "message": None}}}


def _jobs_file(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _progress(folder, run_id, stage, stages):
    with open(os.path.join(folder, "progress.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": 1, "run_id": run_id, "stage": stage, "stages": stages, "done": 0, "total": 100}, f)


def _sync(argv, plan):
    """Z-17: per episode, a timed SRT per audio file (`sync-1/<name>.srt`) and `sync-1.json`, as the plan gives them."""
    said = plan.get("sync") or {}
    data = _jobs_file(argv[1])
    profile_argv = ["check"] + (["--profile", data["profile"]] if data.get("profile") else [])
    if said.get("error") == "SETUP_ERROR" or (("speech" in plan or "speech_setup" in plan)
                                              and not _speech_ok(profile_argv, plan)[0]):
        return _failed("sync", "SETUP_ERROR", "The speech model is not installed.")
    runs = []
    for episode in data["episodes"]:
        run_id, audio = episode["run_id"], episode["audio"]
        audio = audio if isinstance(audio, list) else [audio]
        folder = os.path.join(data["run_dir"], run_id)
        os.makedirs(folder, exist_ok=True)
        stages, error = 2 * len(audio), said.get("error")
        deadline = time.monotonic() + float(said.get("hold") or 0)
        k = 0
        while time.monotonic() < deadline and not os.path.exists(os.path.join(folder, "cancel")):
            _progress(folder, run_id, min(stages, 1 + 2 * (k % len(audio))), stages)
            k += 1
            time.sleep(0.1)
        if os.path.exists(os.path.join(folder, "cancel")):
            os.remove(os.path.join(folder, "cancel"))
            error = "CANCELLED"
        if not error and not os.path.isfile(episode["book"]):
            error = "SOURCE_UNREADABLE"
        if error:
            runs.append({"run_id": run_id, "ok": False, "error": error, "message": error, "file": None,
                         "failure_is_transient": False})
            continue
        out = os.path.join(folder, "sync-1")
        os.makedirs(out, exist_ok=True)
        files = []
        for a in audio:
            name = os.path.basename(a)
            got = (said.get("files") or {}).get(name) or {"status": "no_match", "srt": ""}
            srt = os.path.join(out, os.path.splitext(name)[0] + ".srt")
            with open(srt, "w", encoding="utf-8", newline="\n") as f:
                f.write(got.get("srt") or "")
            cues = [{"n": n, "index": n} for n in range(1, (got.get("srt") or "").count("-->") + 1)]
            files.append({"audio_file": a, "subtitle_file": srt, "status": got.get("status", "synced"), "cues": cues})
        report = dict({"sentence_pct": None, "audio_pct": None, "grade": None, "unheard": []},
                      **(said.get("report") or {}))
        with open(os.path.join(folder, "sync-1.json"), "w", encoding="utf-8") as f:
            json.dump(dict(report, schema=1, run_id=run_id, files=files), f, ensure_ascii=False)
        runs.append({"run_id": run_id, "ok": True, "error": None, "message": None, "file": "sync-1.json",
                     "failure_is_transient": False})
    return {**_ok("sync"), "ok": all(r["ok"] for r in runs), "runs": runs}


def _srt_lines(path):
    with open(path, encoding="utf-8-sig") as f:
        blocks = [b.strip().split("\n") for b in f.read().replace("\r\n", "\n").split("\n\n") if b.strip()]
    out = []

    def sec(t):
        h, m, rest = t.strip().replace(",", ".").split(":")
        return int(h) * 3600 + int(m) * 60 + float(rest)
    for b in blocks:
        at = next(i for i, line in enumerate(b) if "-->" in line)
        a, _arrow, z = b[at].partition("-->")
        out.append((sec(a), sec(z), "".join(b[at + 1:])))
    return out


def _media(argv, plan):
    """Z-10 for an audio episode: each line's clip (a file holding the lines' text: the fake's speech model hears it)
    and its lines merged as asked, within 30 s."""
    data = _jobs_file(argv[1])
    runs = []
    for episode in data["episodes"]:
        run_id = episode["run_id"]
        folder = os.path.join(data["run_dir"], run_id)
        out = os.path.join(folder, "media-1")
        os.makedirs(out, exist_ok=True)
        lines = _srt_lines(episode["subtitle_file"])
        _log({"media_lines": episode["lines"], "audio_file": episode.get("audio_file")})
        rows = []
        for k, request in enumerate(episode["lines"], 1):
            at = min(range(len(lines)), key=lambda i: abs(lines[i][0] - request["line_start"]))
            after = (request.get("line_expansion") or [0, 0])[1]
            end = at
            while end < at + after and end + 1 < len(lines) and lines[end + 1][1] - lines[at][0] <= 30.0:
                end += 1
            # as Anki Miner's _clean_line_text answers it: a leading speaker tag and mid-line kana in brackets out
            text = re.sub(r"（[ぁ-ゖ]+）", "", re.sub(r"^（[^）]*）", "", "".join(t for _s, _e, t in lines[at:end + 1])))
            past = plan.get("audio_seconds") is not None and lines[at][0] > plan["audio_seconds"]
            if not past:                    # a line past the audio's end is cut into no clip (its `audio` null)
                with open(os.path.join(out, f"{k}.mp3"), "w", encoding="utf-8") as f:
                    f.write(text)
            rows.append({"line_start": lines[at][0], "start": lines[at][0], "end": lines[end][1], "unit_index": None,
                         "location": None, "text": text, "picture": None,
                         "audio": None if past else f"media-1/{k}.mp3"})
        with open(os.path.join(folder, "media-1.json"), "w", encoding="utf-8") as f:
            json.dump({"schema": 1, "run_id": run_id, "lines": rows}, f, ensure_ascii=False)
        runs.append({"run_id": run_id, "ok": True, "error": None, "message": None, "file": "media-1.json",
                     "failure_is_transient": False})
    return {**_ok("media"), "runs": runs}


def _transcribe(argv, plan):
    """Z-18: a clip `media` cut is heard as its text (or as the plan's `heard` says, keyed by the text's start)."""
    data = _jobs_file(argv[1])
    profile_argv = ["check"] + (["--profile", data["profile"]] if data.get("profile") else [])
    if ("speech" in plan or "speech_setup" in plan) and not _speech_ok(profile_argv, plan)[0]:
        return _failed("transcribe", "SETUP_ERROR", "The speech model is not installed.")
    runs = []
    for episode in data["episodes"]:
        run_id = episode["run_id"]
        folder = os.path.join(data["run_dir"], run_id)
        out = os.path.join(folder, "transcribe-1")
        os.makedirs(out, exist_ok=True)
        if "video_file" in episode:                 # Michi-NS: a whole episode's audio, as `heard_videos` says
            runs.append(_heard_video(episode, folder, out, plan))
            continue
        with open(episode["audio_file"], encoding="utf-8") as f:
            said = f.read()
        if any(said.startswith(k) for k in plan.get("unreadable_clips") or ()):    # a clip of silence it refuses
            runs.append({"run_id": run_id, "ok": False, "error": "AUDIO_UNREADABLE", "message": "no audio",
                         "file": None, "failure_is_transient": False})
            continue
        heard = "" if plan.get("deaf") else next((v for k, v in (plan.get("heard") or {}).items()
                                                   if said.startswith(k)), said)
        srt = os.path.join(out, os.path.splitext(os.path.basename(episode["audio_file"]))[0] + ".srt")
        with open(srt, "w", encoding="utf-8") as f:
            f.write(f"1\n00:00:00,000 --> 00:00:30,000\n{heard}\n")
        with open(os.path.join(folder, "transcribe-1.json"), "w", encoding="utf-8") as f:
            json.dump({"schema": 1, "run_id": run_id, "subtitle_file": srt, "status": "generated"}, f,
                      ensure_ascii=False)
        runs.append({"run_id": run_id, "ok": True, "error": None, "message": None, "file": "transcribe-1.json",
                     "failure_is_transient": False})
    return {**_ok("transcribe"), "runs": runs}


def _heard_video(episode, folder, out, plan):
    """Michi-NS: `transcribe` of a video episode -> its run's verdict. `heard_videos` {video file name: the SRT it
    writes | "no_speech" | "VIDEO_UNREADABLE"}; `transcribe_hold` seconds it runs (progress written, its cancel seen:
    CANCELLED, no json, its folder gone — API.md)."""
    run_id, name = episode["run_id"], os.path.basename(episode["video_file"])
    hold = float(plan.get("transcribe_hold") or 0)
    if hold:
        _progress(folder, run_id, 1, 2)
        if _cancel_seen(folder, hold):
            shutil.rmtree(out, ignore_errors=True)
            return {"run_id": run_id, "ok": False, "error": "CANCELLED", "message": "cancelled", "file": None,
                    "failure_is_transient": False}
        _progress(folder, run_id, 2, 2)
    heard = (plan.get("heard_videos") or {}).get(name, "no_speech")
    if heard == "VIDEO_UNREADABLE":
        shutil.rmtree(out, ignore_errors=True)
        return {"run_id": run_id, "ok": False, "error": heard, "message": "no audio", "file": None,
                "failure_is_transient": False}
    srt = None
    if heard != "no_speech":
        srt = os.path.join(out, os.path.splitext(name)[0] + ".srt")
        with open(srt, "w", encoding="utf-8") as f:
            f.write(heard)
    with open(os.path.join(folder, "transcribe-1.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": 1, "run_id": run_id, "subtitle_file": srt,
                   "status": "no_speech" if srt is None else "generated"}, f, ensure_ascii=False)
    return {"run_id": run_id, "ok": True, "error": None, "message": None, "file": "transcribe-1.json",
            "failure_is_transient": False, "status": "no_speech" if srt is None else "generated"}


def _fetch(argv, plan):
    """Z-8 (Michi-YT): `fetch` of one YouTube video as the plan's `fetch` says — {"video": the video file's text,
    "subtitle": the caption file's (an .srt; "vtt": true writes it as WebVTT), "error": a run's code ("message",
    "transient"), "call": the whole call's code ("message"), "hold": seconds it downloads (progress at stage 2, its
    cancel seen: CANCELLED, its folder gone — API.md), "outside": the json names a file outside its folder}. The yt-dlp
    PATH would give it is logged (`fetch_ytdlp`)."""
    try:
        data = _jobs_file(argv[1])
    except (OSError, ValueError, IndexError):
        return _failed("fetch", "BAD_RUN_FILE", "The fetch file can't be read.")
    spec = plan.get("fetch") or {}
    _log({"fetch_ytdlp": shutil.which("yt-dlp"), "episodes": data["episodes"], "profile": data.get("profile")})
    if spec.get("call"):
        return _failed("fetch", spec["call"], spec.get("message") or "refused")
    runs = []
    for n, episode in enumerate(data["episodes"], 1):
        run_id = episode["run_id"]
        folder = os.path.join(data["run_dir"], run_id)
        out = os.path.join(folder, "fetch-1")
        os.makedirs(out, exist_ok=True)
        hold = float(spec.get("hold") or 0)
        if hold:
            with open(os.path.join(folder, "progress.json"), "w", encoding="utf-8") as f:
                json.dump({"schema": 1, "stage": 2, "stages": 3, "done": 40, "total": 100}, f)
            if _cancel_seen(folder, hold):
                shutil.rmtree(out, ignore_errors=True)
                runs.append({"run_id": run_id, "ok": False, "error": "CANCELLED", "message": "The run was cancelled.",
                             "file": None, "failure_is_transient": False})
                continue
        if spec.get("error"):
            shutil.rmtree(out, ignore_errors=True)
            runs.append({"run_id": run_id, "ok": False, "error": spec["error"], "message": spec.get("message"),
                         "file": None, "failure_is_transient": bool(spec.get("transient"))})
            continue
        vid = "dQw4w9WgXcQ"
        video = os.path.join(out, f"{vid}.mp4")
        with open(video, "w", encoding="utf-8") as f:
            f.write(spec.get("video", "a fetched video"))
        sub = os.path.join(out, f"{vid}.ja.{'vtt' if spec.get('vtt') else 'srt'}")
        with open(sub, "w", encoding="utf-8") as f:
            f.write(spec.get("subtitle", "1\n00:00:01,000 --> 00:00:03,500\n今日はいい天気ですね\n"))
        if spec.get("outside"):
            video = os.path.join(data["run_dir"], "..", "elsewhere.mp4")    # a real file, outside its folder
            with open(video, "w", encoding="utf-8") as f:
                f.write("a video somewhere else")
        with open(os.path.join(folder, "fetch-1.json"), "w", encoding="utf-8") as f:
            json.dump({"schema": 1, "run_id": run_id, "video_file": video, "subtitle_file": sub, "sub_source": "manual",
                       "video_id": vid, "title": "a fetched video", "duration": 180,
                       "episode_name_override": f"YT:{vid}", "series_name_override": "YouTube",
                       "source_label_override": "a fetched video"}, f, ensure_ascii=False)
        runs.append({"run_id": run_id, "ok": True, "error": None, "message": None, "file": "fetch-1.json",
                     "failure_is_transient": False})
    return {**_ok("fetch"), "runs": runs}


def _cancel_seen(folder, wait=5.0):
    """API.md: Anki Miner polls `<run_dir>/<run_id>/cancel` every 0.2 s."""
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if os.path.exists(os.path.join(folder, "cancel")):
            return True
        time.sleep(0.05)
    return False


def main(argv):
    plan = _plan()
    _log({"argv": argv})
    if not argv or argv[0] != "--api":
        return 2
    argv = argv[1:]
    command = argv[0] if argv else None
    time.sleep(float((plan.get("slow") or {}).get(command, 0)))     # row 56: a look-up still under way at a Stop
    if plan.get("mine") == "garbage" and command == "mine":
        sys.stdout.write("Traceback (most recent call last): …\n")
        return 0
    if plan.get("mine") == "no-stdout" and command == "mine":
        return 0
    if command in plan.get("replay", {}):         # a verdict a real build gave, word for word
        _say(plan["replay"][command])
        return 0
    if command == "version":
        verdict = {**_ok("version"), "result": {"schema": plan.get("schema", 1), "app": plan.get("app", "3.5.0"),
                                                "commands": ["mine", "check", "version", "profiles",
                                                             "settings-export"],
                                                "features": plan.get("features", [])}}
    elif command == "profiles":
        listed = plan.get("profiles", [{"id": "default", "name": "Default"}, {"id": "p-surasura", "name": "Surasura"}])
        verdict = {**_ok("profiles"), "result": {"profiles": [dict({"active": False}, **p) for p in listed]}}
    elif command == "check":
        verdict = _check(argv, plan)
    elif command == "settings-export":
        out = argv[argv.index("--out") + 1]
        text = json.dumps(plan.get("export", LAPIS_EXPORT), ensure_ascii=False)
        with open(out, "w", encoding="utf-8") as f:
            if plan.get("export_cut"):  # row 56: still writing when the job's Stop ends it — half on disk
                f.write(text[:len(text) // 2])
                f.flush()
                time.sleep(30)
            f.write(text)
        verdict = _ok("settings-export")
    elif command == "mine":
        verdict = _mine(argv, plan)
    elif command == "inspect" and ("inspect" in plan.get("features", []) or "tracks" in plan):
        verdict = _inspect(argv, plan)
    elif command == "extract":
        verdict = _extract(argv, plan)
    elif command == "settings-import":
        verdict = _settings_import(argv, plan)
    elif command == "setup" and "--speech-model" in argv:
        verdict = _setup(argv, plan)
    elif command == "sync":
        verdict = _sync(argv, plan)
    elif command == "media":
        verdict = _media(argv, plan)
    elif command == "transcribe":
        verdict = _transcribe(argv, plan)
    elif command == "fetch":
        verdict = _fetch(argv, plan)
    else:
        verdict = _failed(command, "BAD_ARGUMENTS", "unknown command")
    if plan.get("schema", 1) != 1:
        verdict["schema"] = plan["schema"]
    _say(verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
