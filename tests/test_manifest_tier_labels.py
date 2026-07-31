"""A file's tier must come from the SCHEDULE, not from where it used to live.

`master_manifest.json` holds the plan: which phase list an entry sits in. Each entry also carries an
`origin_source` note recording the folder it was in when the Immersion Architect planned. Those two
disagree by design — re-phasing content is the Architect's whole job — and the Content Manager
doesn't write a tier into `origin_source` at all ("Manual Import").

The analyzer used to read the schedule for a file's WEIGHT (-> Score) but `origin_source` for its
LABEL (-> Count High/Low/Goal, which drive the report's ✦ / ⚖ markers). So the markers described the
old folder layout, and anything added by hand fell through to GoalContent regardless of which tab it
was dropped into. These tests pin both to the schedule.
"""

import json
from unittest.mock import patch

import pandas as pd
import pytest

from app import analyzer

# One distinctive word per tier so each file's contribution is unambiguous in the output.
NOW_TEXT = "灯台へ向かう船が見えた。灯台の光は強い。灯台を目指して進む。"
SOON_TEXT = "酒場の奥に扉があった。酒場は静かだった。酒場を抜けて歩く。"
LATER_TEXT = "雪原の果てに山が見えた。雪原は白く広い。雪原を越えていく。"


@pytest.fixture
def env(tmp_path):
    uf = tmp_path / "User Files" / "ja"; uf.mkdir(parents=True)
    data = tmp_path / "data" / "ja"
    for tier in ("HighPriority", "LowPriority", "GoalContent"):
        (data / tier).mkdir(parents=True)
    results = tmp_path / "results"; results.mkdir()
    (uf / "KnownWord.json").write_text(json.dumps({"words": []}), encoding="utf-8")

    # Note the DELIBERATE mismatch between the folder a file sits in and where it gets scheduled.
    (data / "GoalContent" / "now.txt").write_text(NOW_TEXT, encoding="utf-8")
    (data / "HighPriority" / "soon.txt").write_text(SOON_TEXT, encoding="utf-8")
    (data / "LowPriority" / "later.txt").write_text(LATER_TEXT, encoding="utf-8")

    def guf(path): return str(tmp_path / path)
    def gdp(lang=None): return str(tmp_path / "data" / lang) if lang else str(tmp_path / "data")
    def gufp(lang=None): return str(tmp_path / "User Files" / lang) if lang else str(tmp_path / "User Files")
    return {"root": tmp_path, "uf": uf, "results": results, "guf": guf, "gdp": gdp, "gufp": gufp}


def _write_manifest(env, entries):
    """entries: {phase_key: [(relative path, origin_source), ...]}"""
    schedule = {p: [{"physical_path": rel, "title": rel.split("/")[-1], "origin_source": origin}
                    for rel, origin in rows]
                for p, rows in entries.items()}
    (env["uf"] / "master_manifest.json").write_text(
        json.dumps({"schedule": schedule}, ensure_ascii=False), encoding="utf-8")


def _run(env):
    results = env["results"]
    csv = results / "priority_learning_list.csv"
    with patch("app.analyzer.get_user_file", side_effect=env["guf"]), \
         patch("app.analyzer.get_data_path", side_effect=env["gdp"]), \
         patch("app.analyzer.get_user_files_path", side_effect=env["gufp"]), \
         patch("app.analyzer.RESULTS_DIR", str(results)), \
         patch("app.analyzer.OUTPUT_CSV", str(csv)), \
         patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
         patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
         patch("sys.argv", ["analyzer.py", "--language", "ja", "--min-freq", "1"]):
        analyzer.main()
    return pd.read_csv(csv)


def _counts(df, word):
    row = df[df["Word"] == word]
    assert not row.empty, f"'{word}' missing from the priority list"
    r = row.iloc[0]
    return int(r["Count (High)"]), int(r["Count (Low)"]), int(r["Count (Goal)"])


def test_tier_follows_the_schedule_not_the_original_folder(env):
    """The Architect re-phases content, so origin_source and the phase list disagree. The counts
    must follow the phase — that is where the learner will actually meet the word."""
    _write_manifest(env, {
        # scheduled NOW, but the note says it came from the 6+ months folder
        "PHASE_1_NOW":   [("GoalContent/now.txt", "03_LATER")],
        # scheduled Soon, but the note says it came from NOW
        "PHASE_2_SOON":  [("HighPriority/soon.txt", "01_NOW")],
        # scheduled 6+ months, but the note says it came from Soon
        "PHASE_3_LATER": [("LowPriority/later.txt", "02_SOON")],
    })
    df = _run(env)

    high, low, goal = _counts(df, "灯台")
    assert (high, low, goal) == (3, 0, 0), "a NOW-scheduled file must count as High"
    high, low, goal = _counts(df, "酒場")
    assert (high, low, goal) == (0, 3, 0), "a Soon-scheduled file must count as Low"
    high, low, goal = _counts(df, "雪原")
    assert (high, low, goal) == (0, 0, 3), "a 6+months-scheduled file must count as Goal"


def test_content_manager_entries_are_no_longer_dumped_into_goal(env):
    """The Content Manager writes origin_source="Manual Import" — not a tier. That used to fall
    through to GoalContent, so a file dropped into the NOW tab contributed as someday-content and
    its words could never earn a ✦ or ⚖."""
    _write_manifest(env, {
        "PHASE_1_NOW":  [("GoalContent/now.txt", "Manual Import")],
        "PHASE_2_SOON": [("HighPriority/soon.txt", "Disk Sync")],
    })
    df = _run(env)

    assert _counts(df, "灯台") == (3, 0, 0), "hand-added NOW content must count as High"
    assert _counts(df, "酒場") == (0, 3, 0), "disk-synced Soon content must count as Low"


def test_a_missing_origin_source_is_harmless(env):
    """Older manifests may have no origin_source at all; the schedule still decides."""
    schedule = {"PHASE_1_NOW": [{"physical_path": "GoalContent/now.txt", "title": "now.txt"}]}
    (env["uf"] / "master_manifest.json").write_text(
        json.dumps({"schedule": schedule}, ensure_ascii=False), encoding="utf-8")
    df = _run(env)
    assert _counts(df, "灯台") == (3, 0, 0)


def test_priority_markers_can_now_fire_for_a_hand_built_library(env):
    """End-to-end consequence: with every entry written by the Content Manager, High and Low used to
    be zero for every word, so neither marker could ever fire. Recreate the report's own rule."""
    _write_manifest(env, {
        "PHASE_1_NOW":  [("GoalContent/now.txt", "Manual Import")],
        "PHASE_2_SOON": [("HighPriority/soon.txt", "Manual Import")],
    })
    df = _run(env)

    pm = {"priority_threshold": 0.5, "priority_min": 3, "lopsided_threshold": 0.85}
    occ = df["Occurrences"]
    lopsided = (occ > 0) & (df["Count (High)"] / occ >= pm["lopsided_threshold"])
    priority = (~lopsided) & (occ >= pm["priority_min"]) & \
               ((df["Count (High)"] + df["Count (Low)"]) / occ >= pm["priority_threshold"])

    assert (lopsided | priority).any(), "no word earned a marker — the tally is still empty"
    assert lopsided.any(), "NOW-only content should read as lopsided (⚖)"


def test_weight_and_label_stay_consistent(env):
    """Score and the tier tally are two views of the same decision; they must not diverge again."""
    _write_manifest(env, {
        "PHASE_1_NOW":  [("GoalContent/now.txt", "03_LATER")],
        "PHASE_3_LATER": [("LowPriority/later.txt", "01_NOW")],
    })
    df = _run(env)

    now_row = df[df["Word"] == "灯台"].iloc[0]
    later_row = df[df["Word"] == "雪原"].iloc[0]
    # Same occurrence count in both files, so Score differences come purely from the tier weight.
    assert now_row["Occurrences"] == later_row["Occurrences"]
    assert now_row["Score"] > later_row["Score"], "NOW-scheduled content must outweigh 6+ months"
    assert int(now_row["Count (High)"]) > 0 and int(later_row["Count (Goal)"]) > 0


def test_fallback_scan_without_a_manifest_is_unchanged(env):
    """With no manifest the analyzer walks the folders, and there the folder IS the tier."""
    df = _run(env)
    assert _counts(df, "酒場") == (3, 0, 0), "HighPriority/ folder -> High"
    assert _counts(df, "雪原") == (0, 3, 0), "LowPriority/ folder -> Low"
    assert _counts(df, "灯台") == (0, 0, 3), "GoalContent/ folder -> Goal"
