"""The timing sweep's comparison and its sets (`tests/qt/bench_sweep.py`; Sonic, 2026-10-20 night: the ~15-minute sweep
in place of the full timed set for routine checks, the full set re-cut to ≤ 90 minutes).

What a wrong answer would cost: the sweep is the only timing a routine check gets. A comparison that misses a moment
gone slow lets the slowdown land unseen until the full set before a checkpoint; one that flags noise (a 0.6 ms toast
frame going to 0.95, one stray paint frame in five repetitions) teaches everyone to ignore its exit. The figures here
are hold 1's and the key case's own shapes (bench_drag at 20,000 files, 150 %).
"""
import copy
import io
import json
import sys

from tests.qt import bench_sweep


def _moment(p95, step, causes=None, frames=200):
    causes = causes or {}
    return {"reps": 5, "frames_n": frames, "frames_p95_ms": p95, "frames_max_ms": (p95 or 0) * 2,
            "slow_n": sum(causes.values()), "slow_causes": causes, "step_worst_p95_ms": step}


def _drag_doc(moments, files=20000, cycles=5, scales=(150,), reduced=False, cover=False, runs=None):
    """A bench_drag JSON as `bench_moments.scaled_runs` writes it: one result per run."""
    runs = runs or [moments]
    return {"bench": "bench_drag", "scales": list(scales), "runs_per_scale": len(runs), "reduced": reduced,
            "system_scale": 1.5,
            "meta": {"files": files, "cycles": cycles, "cover_scan": cover, "only": ["drag", "menu"]},
            "results": [{"scale": scales[0], "run": i + 1, "dpr": 1.5, "moments": m, "skipped": {}}
                        for i, m in enumerate(runs)]}


# The key case's 150 % figures (k1, 2026-10-20), cut to five moments.
BASE_MOMENTS = {
    "pickup": _moment(3.22, 18.3),
    "drop": _moment(3.28, 75.51),
    "menu-goal": _moment(35.81, 148.47, {"other-thread": 9, "gc": 1}),
    "key-up": _moment(10.44, 36.04, {"other-thread": 3}),
    "toast-connect": _moment(0.6, 1.5),
}


def _write(path, piece, doc):
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{piece}.json").write_text(json.dumps(doc), encoding="utf-8")


def _flat(moments, **kw):
    return {"drag": bench_sweep.flatten(_drag_doc(moments, **kw))}


def _flags(rows):
    return {(p, m): f for p, m, _, _, f, _ in rows if f}


def test_a_sweep_against_its_own_baseline_flags_nothing():
    base = _flat(BASE_MOMENTS)
    rows = bench_sweep.compare(copy.deepcopy(base), base)
    assert _flags(rows) == {}
    assert [m for _, m, *_ in rows] == list(BASE_MOMENTS)


def test_a_frame_p95_over_one_and_a_half_times_its_baseline_is_flagged_by_name():
    # pickup 3.22 -> 4.9 (×1.52, +1.68 ms): flagged; drop 3.28 -> 4.9 (×1.49): just under the ratio, not flagged.
    now = copy.deepcopy(BASE_MOMENTS)
    now["pickup"] = _moment(4.9, 18.3)
    now["drop"] = _moment(4.9, 75.51)
    flags = _flags(bench_sweep.compare(_flat(now), _flat(BASE_MOMENTS)))
    assert flags == {("drag", "pickup"): ["p95 ×1.52"]}


def test_a_tiny_frame_or_step_growing_past_the_ratio_by_less_than_the_floor_is_noise():
    # toast-connect's 0.6 ms frame -> 0.95 (×1.58 but +0.35 ms) and its 1.5 ms step -> 3.2 (×2.1 but +1.7 ms).
    now = copy.deepcopy(BASE_MOMENTS)
    now["toast-connect"] = _moment(0.95, 3.2)
    assert _flags(bench_sweep.compare(_flat(now), _flat(BASE_MOMENTS))) == {}


def test_a_typical_worst_step_over_one_and_a_half_times_its_baseline_is_flagged():
    # drop's step 75.51 -> 120 (×1.59): the reader's lock under a move, back (row4-causes B).
    now = copy.deepcopy(BASE_MOMENTS)
    now["drop"] = _moment(3.28, 120.0)
    assert _flags(bench_sweep.compare(_flat(now), _flat(BASE_MOMENTS))) == {("drag", "drop"): ["step ×1.59"]}


def test_a_new_watched_cause_is_flagged_from_two_frames_and_noted_below_that():
    now = copy.deepcopy(BASE_MOMENTS)
    now["pickup"] = _moment(3.22, 18.3, {"other-thread": 3})      # new, 3 frames: flagged
    now["drop"] = _moment(3.28, 75.51, {"paint": 1})                # new, 1 frame: a note
    now["key-up"] = _moment(10.44, 36.04, {"other-thread": 9})      # had it already: not new, however many
    now["toast-connect"] = _moment(0.6, 1.5, {"machine": 4, "unexplained": 2})   # not a watched cause
    rows = bench_sweep.compare(_flat(now), _flat(BASE_MOMENTS))
    assert _flags(rows) == {("drag", "pickup"): ["new cause other-thread 3"]}
    notes = {m: n for _, m, _, _, _, n in rows if n}
    assert notes == {"drop": ["new cause paint 1"]}


def test_a_moment_missing_or_drawing_no_frames_is_flagged():
    now = copy.deepcopy(BASE_MOMENTS)
    del now["menu-goal"]
    now["toast-connect"] = _moment(None, 1.5, frames=0)
    flags = _flags(bench_sweep.compare(_flat(now), _flat(BASE_MOMENTS)))
    assert flags == {("drag", "menu-goal"): ["missing"], ("drag", "toast-connect"): ["no frames"]}


def test_a_piece_not_run_failed_or_run_at_other_settings_is_flagged_and_a_new_one_only_noted():
    base = {"drag": bench_sweep.flatten(_drag_doc(BASE_MOMENTS)),
            "drag-cover": bench_sweep.flatten(_drag_doc(BASE_MOMENTS, cover=True))}
    failed = _drag_doc(BASE_MOMENTS, files=2000)               # a dry run's 2,000 files against a 20k baseline
    failed["results"][0]["error"] = "no result (exit 1): Traceback"
    now = {"drag": bench_sweep.flatten(failed),
           "goal-only": bench_sweep.flatten(_drag_doc({"goal-sheet": _moment(7.12, 108.74)}))}
    rows = bench_sweep.compare(now, base)
    flags = _flags(rows)
    assert [f for p, m, _, _, f, _ in rows if p == "drag" and m == "-"] == [
        ["other settings than the baseline: files"], ["run failed: no result (exit 1): Traceback"]]
    assert flags[("drag-cover", "-")] == ["piece not run"]
    assert [n for p, m, _, _, f, n in rows if p == "goal-only"] == [["new piece (no baseline)"]]
    assert not any(f for p, _, _, _, f, _ in rows if p == "goal-only")


def test_flatten_takes_the_worse_run_per_moment_and_sums_the_causes():
    run1 = {"drop": _moment(3.1, 80.0, {"paint": 1}), "pickup": _moment(3.5, 17.0)}
    run2 = {"drop": _moment(6.4, 60.0, {"paint": 2, "other-thread": 1})}
    flat = bench_sweep.flatten(_drag_doc({}, runs=[run1, run2]))
    assert flat["moments"]["drop"] == {"p95": 6.4, "step": 80.0, "causes": {"paint": 3, "other-thread": 1},
                                       "frames": 400}
    assert flat["moments"]["pickup"]["p95"] == 3.5
    assert flat["settings"]["files"] == 20000 and "only" not in flat["settings"]


def test_baseline_then_compare_through_the_command_line_writes_the_table_and_exits_one_on_a_flag(tmp_path):
    clean, slow = tmp_path / "clean", tmp_path / "slow"
    _write(clean, "drag", _drag_doc(BASE_MOMENTS))
    base_path = tmp_path / "keep" / "baseline.json"
    assert bench_sweep.main(["baseline", str(clean), "--save", str(base_path), "--commit", "b71092d"]) == 0
    saved = json.loads(base_path.read_text(encoding="utf-8"))
    assert saved["commit"] == "b71092d" and list(saved["pieces"]) == ["drag"]

    assert bench_sweep.main(["compare", str(clean), "--baseline", str(base_path)]) == 0
    assert "**No flags.**" in (clean / "sweep.md").read_text(encoding="utf-8")

    worse = copy.deepcopy(BASE_MOMENTS)
    worse["menu-goal"] = _moment(60.0, 148.47, {"other-thread": 9, "gc": 1})
    _write(slow, "drag", _drag_doc(worse))
    assert bench_sweep.main(["compare", str(slow), "--baseline", str(base_path)]) == 1
    md = (slow / "sweep.md").read_text(encoding="utf-8")
    assert "**FLAGGED: 1** — drag · menu-goal (p95 ×1.68)" in md
    assert "| drag | menu-goal | 35.81 → 60 | 148.47 → 148.47 | other-thread 9 gc 1 | **p95 ×1.68** |" in md


def test_without_a_baseline_the_table_shows_the_figures_and_passes(tmp_path):
    _write(tmp_path, "drag", _drag_doc(BASE_MOMENTS))
    assert bench_sweep.write_report(str(tmp_path), None) == 0
    md = (tmp_path / "sweep.md").read_text(encoding="utf-8")
    assert "No baseline: the figures only" in md
    assert "slow at 2,000 items that looks reasonable at 20,000" in md       # Sonic's blind spot, named


def test_the_sweep_runs_every_bench_at_the_hard_settings_and_its_passes():
    p = bench_sweep.pieces("sweep")
    assert {b for b, _ in p.values()} == {"bench_drag.py", "bench_scroll.py", "bench_motion.py", "bench_settings.py"}

    def arg(name, flag):
        args = p[name][1]
        return args[args.index(flag) + 1] if flag in args else None
    for name in ("drag", "scroll", "drag-reduced", "drag-cover"):
        assert arg(name, "--files") == "20000" and arg(name, "--scales") == "150"
    assert arg("drag", "--cycles") == arg("scroll", "--reps") == arg("motion", "--rounds") == "5"
    assert arg("settings-page", "--rounds") == "5"
    assert "--only" not in p["drag"][1]                          # every group of moments: hover-lift, the Goal sheet
    assert arg("drag-250", "--scales") == arg("scroll-250", "--scales") == "250"
    assert "--reduced" in p["drag-reduced"][1] and "--cover-scan" in p["drag-cover"][1]
    dry = bench_sweep.pieces("sweep", files=2000)
    assert dry["drag"][1][dry["drag"][1].index("--files") + 1] == "2000"


def test_the_full_set_runs_three_scales_ten_repetitions_and_the_2k_drag_once():
    p = bench_sweep.pieces("full")
    scales = {n: a[a.index("--scales") + 1] for n, (_, a) in p.items()}
    assert {scales[n] for n in ("drag-100", "drag-150", "drag-250")} == {"100", "150", "250"}
    assert scales["motion"] == scales["settings-page"] == "100,150,250"
    assert p["drag2k-150"][1][p["drag2k-150"][1].index("--files") + 1] == "2000"
    assert all(a[a.index(f) + 1] == "10" for _, a in p.values() for f in ("--cycles", "--reps", "--rounds") if f in a)
    assert sum("--reduced" in a for _, a in p.values()) == 4     # one Reduced pass of each bench
    names = [n for _, g in bench_sweep.plan("full") for n, _, _ in g]
    assert len(names) == len(set(names))


def test_a_baseline_figure_of_zero_flags_without_dividing_by_it():
    # A repetition whose only step also holds the next one's begin has no step of its own: its worst is 0.0.
    base = copy.deepcopy(BASE_MOMENTS)
    base["key-up"] = _moment(10.44, 0.0, {"other-thread": 3})
    now = copy.deepcopy(BASE_MOMENTS)
    now["key-up"] = _moment(10.44, 3.0, {"other-thread": 3})
    assert _flags(bench_sweep.compare(_flat(now), _flat(base))) == {("drag", "key-up"): ["step 3 (base 0)"]}


def _started(out, set_name="sweep", files=20000, reps=None):
    out.mkdir(parents=True, exist_ok=True)
    (out / "_run.json").write_text(json.dumps({"set": set_name, "files": files, "reps": reps, "commit": "b71092d",
                                               "dirty": False, "start": 1.0, "end": 901.0}), encoding="utf-8")


def test_without_a_baseline_a_planned_piece_with_no_json_is_flagged_and_the_exit_is_one(tmp_path):
    # The first sweep (the one stored as the baseline) and every full set have no baseline: a bench that crashed
    # before writing its JSON must not leave a clean table behind.
    _started(tmp_path)
    _write(tmp_path, "drag", _drag_doc(BASE_MOMENTS))
    assert bench_sweep.write_report(str(tmp_path), None) == 1
    md = (tmp_path / "sweep.md").read_text(encoding="utf-8")
    assert "scroll (piece not run)" in md and "drag-cover (piece not run)" in md
    assert "; drag (piece not run)" not in md and "— drag (piece not run)" not in md


def test_a_named_baseline_that_is_not_there_is_an_error_not_a_pass(tmp_path):
    _write(tmp_path, "drag", _drag_doc(BASE_MOMENTS))
    assert bench_sweep.write_report(str(tmp_path), str(tmp_path / "moved.json")) == 2
    assert not (tmp_path / "sweep.md").exists()


def test_a_run_at_another_scale_or_with_a_traceback_in_a_slot_is_a_failed_run():
    doc = _drag_doc(BASE_MOMENTS)
    doc["results"][0].update(scale_mismatch=True, dpr=1.0, extra={"stderr": "Traceback (most recent call last):"})
    assert bench_sweep.flatten(doc)["errors"] == ["ran at dpr 1.0, not 150 %", "a traceback in the child's stderr"]


def test_the_baseline_refuses_a_sweep_with_a_missing_or_failed_piece(tmp_path):
    _started(tmp_path)
    _write(tmp_path, "drag", _drag_doc(BASE_MOMENTS))
    try:
        bench_sweep.save_baseline(str(tmp_path), str(tmp_path / "base.json"))
    except SystemExit as e:
        assert "not a clean sweep" in str(e) and "scroll (piece not run)" in str(e)
    else:
        raise AssertionError("a partial sweep was stored as the baseline")
    assert not (tmp_path / "base.json").exists()


def test_the_report_prints_on_a_console_that_cannot_write_its_arrows(tmp_path, monkeypatch):
    # Git Bash's and a redirected log's stdout is cp1252: the table's arrows crashed the print after sweep.md was
    # written, and the exit said "flagged".
    _write(tmp_path, "drag", _drag_doc(BASE_MOMENTS))
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp1252"))
    assert bench_sweep.main(["compare", str(tmp_path)]) == 0
    sys.stdout.flush()
    assert "\u2192".encode("utf-8") in raw.getvalue()


def test_a_failed_piece_is_moved_aside_and_played_again_a_clean_one_is_kept(tmp_path):
    good, bad = tmp_path / "drag.json", tmp_path / "scroll.json"
    good.write_text(json.dumps(_drag_doc(BASE_MOMENTS)), encoding="utf-8")
    failed = _drag_doc({})
    failed["results"][0]["error"] = "no result (exit 1)"
    bad.write_text(json.dumps(failed), encoding="utf-8")
    assert bench_sweep._done(str(good)) is True
    assert bench_sweep._done(str(bad)) is False
    assert not bad.exists() and len(list(tmp_path.glob("_failed-scroll-*.json"))) == 1
    assert list(bench_sweep.load(str(tmp_path))) == ["drag"]                 # the failed copy is not a piece


class _Runs:
    """subprocess.run as `run` calls it: the with-lock call's argv recorded, its exits given in turn."""

    def __init__(self, exits):
        self.exits = list(exits)
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        code = self.exits.pop(0) if self.exits else 0
        return type("P", (), {"returncode": code})()


def _args(out, **kw):
    a = dict(out=str(out), set="sweep", files=20000, reps=None, baseline=None, lock="/locks/with-lock.sh",
             holder="Mado (timing sweep)", gap=60, plan=False)
    a.update(kw)
    return type("A", (), a)


def test_run_holds_each_group_through_with_lock_tries_again_after_75_and_skips_a_done_group(tmp_path, monkeypatch):
    runs, sleeps = _Runs([75, 0, 0]), []
    monkeypatch.setattr(bench_sweep.subprocess, "run", runs)
    monkeypatch.setattr(bench_sweep.time, "sleep", sleeps.append)
    monkeypatch.setattr(bench_sweep, "git_bash", lambda: "C:/Git/usr/bin/bash.exe")
    monkeypatch.setattr(bench_sweep, "_commit", lambda: ("b71092d", False))
    for p in ("drag", "drag-250"):                                           # group 1 already done
        _write(tmp_path, p, _drag_doc(BASE_MOMENTS))
    assert bench_sweep.run(_args(tmp_path)) == 1                             # the other pieces never wrote a JSON
    group = runs.calls[0]
    assert group[:9] == ["C:/Git/usr/bin/bash.exe", "/locks/with-lock.sh", "--max", "15", "timed",
                         "Mado (timing sweep)", bench_sweep.ROOT, "sweep scroll-motion-settings", "--"]
    assert group[11:] == ["_group", "--out", str(tmp_path), "--set", "sweep", "--files", "20000",
                          "scroll", "scroll-250", "motion", "settings-page"]
    assert runs.calls[1] == group                                            # gave up waiting (75): the same again
    assert runs.calls[2][7] == "sweep reduced-cover" and len(runs.calls) == 3
    assert sleeps == [60, 60]                                                # the retry's minute, the gap between
    info = json.loads((tmp_path / "_run.json").read_text(encoding="utf-8"))
    assert info["commit"] == "b71092d" and info["set"] == "sweep"
    assert set(info["groups"]) == {"scroll-motion-settings", "reduced-cover"}


def test_run_refuses_a_folder_holding_another_runs_pieces(tmp_path, monkeypatch):
    # A 2,000-file dry run's pieces carry the same names as the real sweep's: resuming over them would mix the two.
    _started(tmp_path, files=2000)
    runs = _Runs([])
    monkeypatch.setattr(bench_sweep.subprocess, "run", runs)
    assert bench_sweep.run(_args(tmp_path)) == 2
    assert runs.calls == []
