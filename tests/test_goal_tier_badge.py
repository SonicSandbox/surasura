"""The report sidebar marks files from the 6+ months list with a quiet "6+" chip.

The marker existed as a green "G" badge but had never once appeared: the generator looked for each
file under User Files/<lang>/GoalContent — a folder that never exists (content lives in
data/<lang>/...). It now takes the tier from where the file is SCHEDULED (the manifest phase, via the
analyzer's own resolve_found_files), never from its folder: after a Smart Sort the two differ, and
the analysis follows the schedule, so the chip must too (see tests/test_manifest_tier_labels.py).
"""

import json
import os
import re
from unittest.mock import patch

import pandas as pd
import pytest

TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "templates", "web_app.html")


def _entry(physical_path):
    return {"title": os.path.basename(physical_path), "physical_path": physical_path,
            "parent_folder": "", "origin_source": "Manual Import", "type": "File", "status": "New"}


def _library(files, schedule=None):
    """Write content files (tier-relative paths) and, optionally, a manifest into the sandbox."""
    root = os.environ["SURASURA_TEST_ROOT"]
    for rel in files:
        path = os.path.join(root, "data", "ja", rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("冒険に出かけた。図書館で本を読んだ。\n")
    if schedule is not None:
        user_files = os.path.join(root, "User Files", "ja")
        os.makedirs(user_files, exist_ok=True)
        manifest = {"schedule": {phase: [_entry(p) for p in paths] for phase, paths in schedule.items()}}
        with open(os.path.join(user_files, "master_manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False)


def _render_sidebar(tmp_path, filenames):
    """Render a report whose per-file view lists `filenames`; return {filename: is_goal_content}."""
    results = tmp_path / "results"
    results.mkdir()
    pd.DataFrame([{"Word": "冒険", "Reading": "ボウケン", "Tier": "Outside", "Score": 10,
                   "Occurrences": 4, "Count (High)": 1, "Count (Low)": 1, "Count (Goal)": 2,
                   "Sources": "now.txt", "Context 1": "冒険に出かけた。"}]
                 ).to_csv(results / "priority_learning_list.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([{"Sequence": i, "Source File": name, "Word": f"単語{i}", "Reading": "タンゴ",
                   "Tier": "Outside", "Score": 10, "Occurrences (Global)": 2, "Occurrences (File)": 2,
                   "Count (High)": 0, "Count (Low)": 0, "Count (Goal)": 2, "Context 1": "冒険に出かけた。"}
                  for i, name in enumerate(filenames, 1)]
                 ).to_csv(results / "progressive_learning_list.csv", index=False, encoding="utf-8-sig")

    from app import static_html_generator as gen
    out = results / "reading_list_static.html"
    with patch.object(gen, "RESULTS_DIR", str(results)), \
         patch.object(gen, "PRIORITY_CSV", str(results / "priority_learning_list.csv")), \
         patch.object(gen, "PROGRESSIVE_CSV", str(results / "progressive_learning_list.csv")), \
         patch.object(gen, "OUTPUT_FILE", str(out)):
        gen.generate_static_html(theme="default")

    payload = re.search(r"let globalData = (\{.*?\});\n", out.read_text(encoding="utf-8"), re.S)
    return {f["filename"]: f["is_goal_content"] for f in json.loads(payload.group(1))["progressive"]}


def test_chip_follows_the_schedule_not_the_folder(tmp_path):
    """moved.txt sits in LowPriority but a Smart Sort scheduled it for 6+ months; promoted.txt sits
    in GoalContent but is scheduled NOW. The chip must answer "when will I meet this?"."""
    _library(["HighPriority/now.txt", "GoalContent/later.txt", "LowPriority/moved.txt",
              "GoalContent/promoted.txt"],
             schedule={"PHASE_1_NOW": ["HighPriority/now.txt", "GoalContent/promoted.txt"],
                       "PHASE_2_SOON": [],
                       "PHASE_3_LATER": ["GoalContent/later.txt", "LowPriority/moved.txt"]})

    marked = _render_sidebar(tmp_path, ["now.txt", "promoted.txt", "later.txt", "moved.txt"])

    assert marked == {"now.txt": False, "promoted.txt": False, "later.txt": True, "moved.txt": True}


def test_without_a_manifest_the_6_months_folder_decides(tmp_path):
    """No manifest yet: the analyzer falls back to scanning the tier folders, and so does the chip."""
    _library(["HighPriority/now.txt", "GoalContent/someday/later.txt"])

    marked = _render_sidebar(tmp_path, ["now.txt", "later.txt"])

    assert marked == {"now.txt": False, "later.txt": True}


def test_an_empty_library_marks_nothing_and_still_renders(tmp_path):
    assert _render_sidebar(tmp_path, ["orphan.txt"]) == {"orphan.txt": False}


def test_the_chip_is_quiet_and_hidden_from_dictionary_extensions():
    """Themed outline, text drawn by CSS (so Yomitan/Migaku never read it), a plain-language hover
    — and no trace of the old saturated green "G" or its internal "Goal Content" name."""
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    assert 'class="tier-chip" data-content="6+"' in html
    assert 'title="From your 6+ months list" migaku_ignore data-yomichan-ignore' in html
    assert ".tier-chip::after" in html
    assert 'title="Goal Content">G</span>' not in html
