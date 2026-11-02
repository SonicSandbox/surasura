"""Freeze the user's data for the parsing suite — copies, never modifies.

    python tests/parsing/snapshot.py                    # -> tests/parsing/data/<today>/
    python tests/parsing/snapshot.py --name 2026-10-02  # a name of your own
    python tests/parsing/snapshot.py --results-lang zh  # results/ holds the last run's language (default: settings)

Cases that read the user's real data name a snapshot (ctx={"snapshot": "2026-09-26"}), so they give the same
answer however the live files change. A snapshot is never rewritten: this refuses an existing name. The settings
the suite runs under (harness.SETTINGS_SNAPSHOT) are the settings.json frozen in one of them.

Copied, where present: User Files/<lang>/ KnownWord.json, anki_backlog.json, junban_pairs.json, IgnoreList.txt,
Blacklist.txt, GraduatedList.txt for ja and zh; results/ priority_learning_list.csv, progressive_learning_list.csv,
library_frequency.json into the folder of the language that run was for; settings.json. MANIFEST.json records
where each file came from, its size, sha256 and time, and the git state.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.path_utils import get_user_file, get_user_files_path  # noqa: E402
from tests.parsing.harness import DATA, git_state  # noqa: E402

USER_FILES = ("KnownWord.json", "anki_backlog.json", "junban_pairs.json",
              "IgnoreList.txt", "Blacklist.txt", "GraduatedList.txt")
RESULTS = ("priority_learning_list.csv", "progressive_learning_list.csv", "library_frequency.json")


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def take(name, results_lang):
    folder = os.path.join(DATA, name)
    if os.path.exists(folder):
        raise SystemExit(f"{folder} exists — a snapshot is never rewritten; choose another --name")
    plan = [(os.path.join(get_user_files_path(lang), file), f"{lang}/{file}")
            for lang in ("ja", "zh") for file in USER_FILES]
    plan += [(os.path.join(get_user_file("results"), file), f"{results_lang}/{file}") for file in RESULTS]
    plan.append((get_user_file("settings.json"), "settings.json"))
    files = {}
    for source, target in plan:
        if not os.path.isfile(source):
            continue
        destination = os.path.join(folder, *target.split("/"))
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copy2(source, destination)                   # read-only on the source
        if _sha256(source) != _sha256(destination):
            raise SystemExit(f"copy of {source} differs from its source")
        stat = os.stat(source)
        files[target] = {"from": os.path.relpath(source, ROOT).replace(os.sep, "/"), "bytes": stat.st_size,
                         "sha256": _sha256(destination),
                         "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")}
    manifest = {"name": name, "taken": datetime.now().isoformat(timespec="seconds"), "git": git_state(),
                "results_language": results_lang, "files": files}
    with open(os.path.join(folder, "MANIFEST.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=1)
    return folder, files


def main(argv=None):
    parser = argparse.ArgumentParser(description="Freeze the user's data for the parsing suite (copies only).")
    parser.add_argument("--name", default=date.today().isoformat(), help="the snapshot's name (default: today)")
    parser.add_argument("--results-lang", choices=("ja", "zh"), default=None,
                        help="the language results/ was generated for (default: settings.json's target_language)")
    args = parser.parse_args(argv)
    results_lang = args.results_lang
    if results_lang is None:
        try:
            with open(get_user_file("settings.json"), encoding="utf-8") as handle:
                results_lang = json.load(handle).get("target_language") or "ja"
        except (OSError, ValueError):
            results_lang = "ja"
    folder, files = take(args.name, results_lang)
    print(f"snapshot {args.name}: {len(files)} files -> {folder} (results as {results_lang})")
    for target, info in sorted(files.items()):
        print(f"  {target:<40} {info['bytes']:>12,} bytes  from {info['from']}")


if __name__ == "__main__":
    main()
