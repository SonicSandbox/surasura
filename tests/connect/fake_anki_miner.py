"""A fake Anki Miner for the tests (P1.5 07-tests §1): the `--api` contract as API.md documents it for 3.5.0 / 3.6.0,
run as a child process exactly as the real one is (`AnkiMiner.exe --api <command> …`), and never Anki, never media.

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
     "forms": {"<word>": "<mined_form>"}}                  # a word Anki Miner placed by another form

Every call is appended to FAKE_ANKI_MINER_LOG (one JSON line: argv, and the run file's bytes' facts for `mine`), so a
test can see what was asked and in what order. The run file is checked as Anki Miner checks it: strict UTF-8 with no
BOM, the 3.5.0 keys only (and, with refuse-sentence-keys, main's refusal of the two sentence keys).
"""
import json
import os
import sys
import time

RUN_KEYS = {"schema", "run_dir", "profile", "language", "config", "episodes"}
EPISODE_KEYS = {"run_id", "video_file", "subtitle_file", "subtitle_offset", "audio_track_override",
                "source_label_override", "secondary_subtitle_file", "secondary_subtitle_offset", "series_name_override",
                "episode_name_override", "tags", "words"}
WORD_KEYS = {"word", "line_start", "line_text", "line_expansion"}
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
    if set(data) - RUN_KEYS:
        raise ValueError(f"unknown keys {sorted(set(data) - RUN_KEYS)}")
    if data.get("schema") != 1 or not {"run_dir", "language", "episodes"} <= set(data):
        raise ValueError("schema must be 1; run_dir, language and episodes are required")
    if not os.path.isdir(data["run_dir"]):
        raise ValueError("run_dir must be an existing folder")
    config = data.get("config", {})
    if not isinstance(config, dict):
        raise ValueError("config must be an object")
    allowed = CONFIG_KEYS - (set(SENTENCE_KEYS) if plan.get("mine") == "refuse-sentence-keys" else set())
    if set(config) - allowed:
        raise ValueError(f"These config keys are not allowed: {', '.join(sorted(set(config) - allowed))}")
    for episode in data["episodes"]:
        if set(episode) - EPISODE_KEYS or not {"run_id", "video_file", "subtitle_file", "words"} <= set(episode):
            raise ValueError("unknown or missing episode keys")
        if not isinstance(episode.get("tags", ""), str) or not isinstance(episode.get("subtitle_offset", 0.0), float):
            raise ValueError("tags must be a string, subtitle_offset a number")
        if not episode.get("words"):
            raise ValueError("words must list at least one word")
        for word in episode["words"]:
            if set(word) - WORD_KEYS or not isinstance(word.get("word"), str):
                raise ValueError("unknown word keys")
            expansion = word.get("line_expansion")
            if expansion is not None and not (isinstance(expansion, list) and len(expansion) == 2 and all(
                    isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in expansion)):
                raise ValueError("line_expansion must be [before, after]")
            if word.get("line_start") is not None and not isinstance(word["line_start"], float):
                raise ValueError("line_start must be a number")
    return data


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
    if how == "crash":
        sys.exit(3)
    if how == "hang":
        time.sleep(60)
    if how == "video-unreadable":       # refused at its own check, before any Anki write: no result file
        runs = [{"run_id": e["run_id"], "ok": False, "error": "VIDEO_UNREADABLE",
                 "message": f"The video cannot be opened: {e['video_file']}", "file": None} for e in data["episodes"]]
        return {**_ok("mine", runs=runs), "ok": False}
    runs = []
    for episode in data["episodes"]:
        folder = os.path.join(data["run_dir"], episode["run_id"])
        os.makedirs(folder, exist_ok=True)
        rows, note = [], 1727000000000
        for n, request in enumerate(episode["words"]):
            status = plan.get("statuses", {}).get(request["word"], "created")
            if how == "mining-failed" and n >= plan.get("fail_after", 0):
                status = "uncertain" if n == plan.get("fail_after", 0) else "not_attempted"
            note += 1
            start = request.get("line_start")
            if start is not None:
                start += plan.get("shift", {}).get(request["word"], 0.0)
            form = plan.get("forms", {}).get(request["word"], request["word"])   # placed by its dictionary form
            rows.append({"word": request["word"], "mined_form": form if status != "not_found" else None,
                         "status": status, "note_id": note if status == "created" else None, "media_missing": [],
                         "line_start": start if status != "not_found" else None, "sentence": None, "start": start,
                         "end": None, "filter": None})
        failed = how == "mining-failed"
        result = {"schema": 1, "run_id": episode["run_id"], "outcome": "failed" if failed else "success",
                  "anki_write_state": "partial" if failed else "complete", "failure_is_transient": False,
                  "error": "MINING_FAILED" if failed else None, "message": "addNotes failed" if failed else None,
                  "media_store_failures": 0, "words": rows}
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


def main(argv):
    plan = _plan()
    _log({"argv": argv})
    if not argv or argv[0] != "--api":
        return 2
    argv = argv[1:]
    command = argv[0] if argv else None
    if plan.get("mine") == "garbage" and command == "mine":
        sys.stdout.write("Traceback (most recent call last): …\n")
        return 0
    if plan.get("mine") == "no-stdout" and command == "mine":
        return 0
    if command == "version":
        verdict = {**_ok("version"), "result": {"schema": plan.get("schema", 1), "app": plan.get("app", "3.5.0"),
                                                "commands": ["mine", "check", "version", "profiles",
                                                             "settings-export"],
                                                "features": plan.get("features", [])}}
    elif command == "profiles":
        listed = plan.get("profiles", [{"id": "default", "name": "Default"}, {"id": "p-surasura", "name": "Surasura"}])
        verdict = {**_ok("profiles"), "result": {"profiles": [dict(p, active=False) for p in listed]}}
    elif command == "check":
        verdict = {**_ok("check"), "result": plan.get("check", {"ready": True, "items": [
            {"name": "anki", "ok": True, "message": None}]})}
    elif command == "settings-export":
        out = argv[argv.index("--out") + 1]
        with open(out, "w", encoding="utf-8") as f:
            json.dump(plan.get("export", LAPIS_EXPORT), f, ensure_ascii=False)
        verdict = _ok("settings-export")
    elif command == "mine":
        verdict = _mine(argv, plan)
    else:
        verdict = _failed(command, "BAD_ARGUMENTS", "unknown command")
    if plan.get("schema", 1) != 1:
        verdict["schema"] = plan["schema"]
    _say(verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
