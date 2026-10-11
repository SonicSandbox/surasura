"""The warm arrivals worker, the estimate and the pick prepared at arrival (E2.2 RUNBOOK row 2.2.7: D10, D11, K9).

RP-2's libraries (`plan_file_cases`, ja + zh; one show's files in a folder of their own) are Generated; then an arrival
lands in the show's folder — T7's "recap", lines the library already holds, so no gate moves — with a subtitle in
hato's drop folder. The worker (`app_entry.py arrivals-worker --headless`, a real child process under the root) answers
each: the list words, *N new* at the top of NOW and after its show, and *% known* are what a full Generate of the
library with the file scheduled there writes (its plan line, its first places, its Baseline %); the record it returns
is one `Engine.add` takes, and the engine's *N new* is the worker's. The pick equals Connect's own pick
(`pick.pick` over `cues.read` / `cues.tokens`, the known words and the list read as the command line reads them). The
worker writes nothing under the root (every file hashed before and after; app_entry's own start line in the app's log
aside); a second ask works nothing out again; it ends when its input closes and when idle; a language with no plan
answers "no-plan". The client (`app/services/arrivals.py`) starts it on first use as a registry job, answers on its
reader thread, starts it again after an idle end, sends a request the ending worker never answered once more, and
answers what a crashed worker held with an error.
"""
import csv
import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time

import pytest

from app import analyzer, plan_engine
from tests import plan_file_cases as cases
from tests.test_arrivals_parity import RECAP, _lines, _schedule, _write
from tests.test_plan_file import read_run

RES = os.path.join(cases.REPO, "tests", "Test Resources")
# One show per library, moved into a folder of its own: (its folder, its files — the first of NOW, in order).
SHOWS = {"rp2-ja": ("HighPriority/Gotoubun", ("gotoubun_ep01.srt", "gotoubun_ep02.srt", "gotoubun_ep03.srt")),
         "rp2-zh": ("HighPriority/Daily", ("zh_high_1.txt", "zh_high_2.txt"))}
# Two more arrivals in the show's folder, made of lines from 6+ Months (words the show hasn't met yet), the second
# overlapping the first: asked alone, and with the first placed before it (`placed`).
LATE = {"rp2-ja": (("eighty_six_ch2.txt", "runaway_transcript.txt"), 0, 12, 6, 18),
        "rp2-zh": (("patterns_zh_sample.txt", "mixed_script_transcript.txt"), 0, 10, 5, 15)}
SUBTITLE = {"rp2-ja": ("ja", "library_episode.ass"), "rp2-zh": ("zh", "night_market.srt")}
LOG = "local/logs/app_debug_log.txt"        # app_entry.py's start line, written by every verb


def _language(case):
    return cases.ALL_CASES[case][0]


def _build(root, case):
    """The case's library with its show's files in the show's folder (the manifest following)."""
    cases.build(root, case)
    language = _language(case)
    folder, names = SHOWS[case]
    data = os.path.join(root, "data", language)
    os.makedirs(os.path.join(data, *folder.split("/")), exist_ok=True)
    for name in names:
        os.replace(os.path.join(data, "HighPriority", name), os.path.join(data, *folder.split("/"), name))
    path = os.path.join(root, "User Files", language, "master_manifest.json")
    with open(path, encoding="utf-8") as f:
        manifest = json.load(f)
    for phase in manifest["schedule"].values():
        for entry in phase:
            if entry["physical_path"].split("/")[-1] in names:
                entry["physical_path"] = f"{folder}/{entry['physical_path'].split('/')[-1]}"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def _text(case, sources, start, end):
    return "\n".join(_lines(case, sources)[start:end]) + "\n"


def _hashes(root):
    """Every file's sha256 and every folder under `root` (app_entry's log and its folders aside)."""
    out = {}
    for folder, _dirs, files in os.walk(root):
        here = os.path.relpath(folder, root).replace("\\", "/")
        if here not in ("local", "local/logs"):
            out[here + "/"] = "folder"
        for name in files:
            path = os.path.join(folder, name)
            rel = os.path.relpath(path, root).replace("\\", "/")
            if rel != LOG:
                with open(path, "rb") as f:
                    out[rel] = hashlib.sha256(f.read()).hexdigest()
    return out


class _Worker:
    """The worker as a child process under `root`, asked one request at a time."""

    def __init__(self, root, language, args=()):
        cmd = [sys.executable, os.path.join(cases.REPO, "app_entry.py"), "arrivals-worker", "--headless",
               "--language", language] + list(args)
        self.started = time.perf_counter()
        self.p = subprocess.Popen(cmd, cwd=cases.REPO, env=cases.child_env(root), stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.lines, self.err = queue.Queue(), []
        threading.Thread(target=lambda: [self.lines.put(line) for line in self.p.stdout], daemon=True).start()
        threading.Thread(target=lambda: [self.err.append(line) for line in self.p.stderr], daemon=True).start()

    def ask(self, request, timeout=180):
        self.p.stdin.write((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
        self.p.stdin.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                answer = json.loads(self.lines.get(timeout=0.5).decode("utf-8"))
                break
            except queue.Empty:
                if self.p.poll() is not None or time.monotonic() > deadline:
                    raise AssertionError("no answer:\n" + b"".join(self.err).decode("utf-8", "replace")[-4000:]) \
                        from None
        assert "error" not in answer, (answer, b"".join(self.err).decode("utf-8", "replace")[-4000:])
        return answer

    def close(self, timeout=60):
        self.p.stdin.close()
        return self.p.wait(timeout)


def _path(root, language, rel):
    return os.path.join(root, "data", language, *rel.split("/"))


@pytest.fixture(scope="module")
def library(tmp_path_factory):
    """Each library Generated, then its arrivals written (the recap and a second one in the show's folder, a subtitle in
    hato's drop folder) and one worker session asked about them — the root hashed before and after."""
    out = {}
    for case in SHOWS:
        language = _language(case)
        root = str(tmp_path_factory.mktemp(f"{case}-worker"))
        _build(root, case)
        cases.generate(root, case)
        folder = SHOWS[case][0]
        rels = {"recap": f"{folder}/recap.txt", "late": f"{folder}/late.txt", "late2": f"{folder}/late2.txt",
                "subtitle": f"HighPriority/Hato/{SUBTITLE[case][1]}"}
        _write(root, language, rels["recap"], _text(case, *RECAP[case]))
        sources, a, b, c, d = LATE[case]
        _write(root, language, rels["late"], _text(case, sources, a, b))
        _write(root, language, rels["late2"], _text(case, sources, c, d))
        with open(os.path.join(RES, *SUBTITLE[case]), encoding="utf-8") as f:
            _write(root, language, rels["subtitle"], f.read())
        before = _hashes(root)
        worker = _Worker(root, language, cases.ALL_CASES[case][3])
        paths = {name: _path(root, language, rel) for name, rel in rels.items()}
        answers = {"recap": worker.ask({"id": 1, "op": "estimate", "path": paths["recap"]})}
        answers["stats1"] = worker.ask({"id": 2, "op": "stats"})
        answers["again"] = worker.ask({"id": 3, "op": "estimate", "path": paths["recap"]})
        answers["stats2"] = worker.ask({"id": 4, "op": "stats"})
        answers["subtitle"] = worker.ask({"id": 5, "op": "estimate", "path": paths["subtitle"]})
        answers["late"] = worker.ask({"id": 6, "op": "estimate", "path": paths["late"]})
        answers["late2"] = worker.ask({"id": 7, "op": "estimate", "path": paths["late2"]})
        answers["late2_placed"] = worker.ask({"id": 8, "op": "estimate", "path": paths["late2"],
                                              "placed": [paths["late"]]})
        answers["quit"] = worker.ask({"id": 9, "op": "quit"})
        assert worker.p.wait(60) == 0
        out[case] = {"root": root, "rels": rels, "paths": paths, "answers": answers, "before": before,
                     "after": _hashes(root)}
    return out


@pytest.fixture(scope="module")
def placed(library, tmp_path_factory):
    """Each library Generated with the recap scheduled at the top of NOW, and after its show's last file."""
    out = {}
    for case in SHOWS:
        language = _language(case)
        rel = library[case]["rels"]["recap"]
        for name, at in (("top", 0), ("after", len(SHOWS[case][1]))):
            root = str(tmp_path_factory.mktemp(f"{case}-{name}"))
            _build(root, case)
            _write(root, language, rel, _text(case, *RECAP[case]))
            _schedule(root, language, rel, "now", at)
            cases.generate(root, case)
            out[(case, name)] = read_run(root)
    return out


def _line(run, rel):
    plan = run["plan"]
    f = next(f for f, entry in enumerate(plan["files"]) if entry[0] == rel)
    return f, plan["per_file"][f]


def _new_at(run, rel):
    """How many of the plan's keys a Generate first meets in the file `rel` (its first places: library_frequency)."""
    f, _line_ = _line(run, rel)
    seq = f + 1
    return sum(1 for word, reading, *_rest in run["plan"]["keys"]
               if run["library_frequency"][f"{word}|{reading}"][4] == seq)


@pytest.mark.parametrize("case", list(SHOWS))
def test_the_estimate_is_the_next_generates_numbers(library, placed, case):
    """List words, N new at the top of NOW and after its show, % known: each what a full Generate with the recap
    scheduled there writes; no gate moves (exact)."""
    rel = library[case]["rels"]["recap"]
    answer = library[case]["answers"]["recap"]
    assert (answer["exact"], answer["moved"], answer["cached"]) == (True, [], False)
    top, after = placed[(case, "top")], placed[(case, "after")]
    _f, line = _line(top, rel)
    keys = top["plan"]["keys"]
    rows = top["plan"]["rows"]
    want = [[keys[k][0], keys[k][1]] for k in list(line["main"][0::2]) + list(line["ph"][0::2]) if rows[k] is not None]
    assert answer["words"] == want and want
    assert answer["n_new_top"] == _new_at(top, rel) > 0
    folder, names = SHOWS[case]
    assert answer["after"] == f"{folder}/{names[-1]}"
    assert answer["n_new_after_show"] == _new_at(after, rel)
    assert answer["n_new_after_show"] < answer["n_new_top"], "the show's own files met its words first"
    # % known: the plan line's progressive sums, and the Baseline % the Generate's progressive list shows for it.
    assert [answer["counted"], answer["known"]] == line["prog"][:2]
    shown = {row["Baseline %"] for row in top["progressive"] if row["Source File"] == "recap.txt"}
    assert len(shown) == 1 and float(shown.pop()) == answer["known_pct"]
    # The record's uses, word by word (each plan numbers its own keys).
    base = plan_engine.load(os.path.join(library[case]["root"], "results", analyzer.PLAN_FILE)).keys
    main = answer["record"]["main"]
    assert [(base[k][:2], n) for k, n in zip(main[0::2], main[1::2])] ==         [(keys[k][:2], n) for k, n in zip(line["main"][0::2], line["main"][1::2])]


@pytest.mark.parametrize("case", list(SHOWS))
def test_the_record_is_one_the_engine_adds_and_its_n_new_is_the_engines(library, case):
    """The answer's record goes into `Engine.add` as it is (JSON): at the top of NOW and after the show's last file the
    engine's *N new* is the worker's (the recap, and lines from 6+ Months the show hasn't met) — and with another
    arrival of the show placed first (`placed`: after the show), the next follows that one and counts only what it
    didn't bring."""
    root, rels, answers = library[case]["root"], library[case]["rels"], library[case]["answers"]
    plan = plan_engine.load(os.path.join(root, "results", analyzer.PLAN_FILE))
    for name in ("recap", "late", "late2"):
        answer = answers[name]
        for place, want in ((dict(), answer["n_new_top"]), (dict(after_id=answer["after"]), answer["n_new_after_show"])):
            eng = plan_engine.Engine(plan)
            eng.add(rels[name], answer["record"], "now", **place)
            assert eng.result().n_new[rels[name]] == want, (name, place)
    late, alone, then = answers["late"], answers["late2"], answers["late2_placed"]
    assert late["after"] == alone["after"] == f"{SHOWS[case][0]}/{SHOWS[case][1][-1]}" and then["after"] == rels["late"]
    assert alone["n_new_after_show"] > 0
    eng = plan_engine.Engine(plan)
    eng.add(rels["late"], late["record"], "now", after_id=late["after"])
    eng.add(rels["late2"], alone["record"], "now", after_id=rels["late"])
    assert eng.result().n_new[rels["late2"]] == then["n_new_after_show"] < alone["n_new_after_show"]
    assert then["n_new_top"] == alone["n_new_top"] and then["cached"] is False


# Connect's pick, its inputs read as the command line reads them: the known words read afresh, the ignore lists, the
# list from the last Generate's priority CSV, the library's name tables (`app/cli/verbs.py`'s pick).
_PICK_CHILD = r"""
import csv, json, os, sys
from app import analyzer, cues, names, token_index
from app.connect import pick
from app.path_utils import get_user_files_path
language, path = sys.argv[1], sys.argv[2]
analyzer.SANITIZE_JA = language == "ja"
if language == "ja":
    names.use_library_tables(token_index.read_names_tables("ja"), pin=True)
tokenizer = analyzer.JapaneseTokenizer() if language == "ja" else analyzer.ChineseTokenizer()
folder = get_user_files_path(language)
tuples, lemmas = analyzer.load_known_words(os.path.join(folder, "KnownWord.json"), tokenizer)
ignore = analyzer.load_ignore_set(folder, "asis", language)
is_known = lambda key: key in tuples or key[0] in lemmas or key[0] in ignore
listed = {}
with open(os.path.join(analyzer.RESULTS_DIR, "priority_learning_list.csv"), encoding="utf-8-sig", newline="") as f:
    for row in csv.DictReader(f):
        listed.setdefault((row["Word"], row["Reading"]), len(listed))
phrase_set = None
if language == "ja":
    from app import phrases
    phrase_set = phrases.load()
read = cues.read(path, language)
out = pick.pick(read, cues.tokens(read, language, "asis", tokenizer), language, is_known, mode="list", listed=listed,
                carded=None, readable=analyzer.LearningView(known=is_known).readable if language == "ja" else None,
                phrase_set=phrase_set)
print("OUT " + json.dumps(out, ensure_ascii=False))
"""


@pytest.mark.parametrize("case", list(SHOWS))
def test_the_pick_is_connects_pick_on_the_same_cues(library, case):
    """D11: a subtitle's pick (its words and lines) = `pick.pick` over the same cues with the command line's inputs; a
    text file has none."""
    root, paths, answers = library[case]["root"], library[case]["paths"], library[case]["answers"]
    language = _language(case)
    p = subprocess.run([sys.executable, "-c", _PICK_CHILD, language, paths["subtitle"]], cwd=cases.REPO,
                       env=cases.child_env(root), capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stderr[-4000:]
    want = json.loads(next(line for line in p.stdout.splitlines() if line.startswith("OUT "))[4:])
    got = answers["subtitle"]["pick"]
    assert got == want
    assert got["words"], "the subtitle holds list words to make cards from"
    assert answers["recap"]["pick"] is None


@pytest.mark.parametrize("case", list(SHOWS))
def test_the_worker_writes_nothing_and_a_second_ask_works_nothing_out_again(library, case):
    """Every file under the root is byte-identical after the session (the token store, results/, the known words,
    the kept text — app_entry's start line in the app's log aside); asked again, the answer is the one kept: no
    arrival read again, no estimate worked out again, no view built again."""
    lib = library[case]
    assert lib["after"] == lib["before"]
    first, again = lib["answers"]["recap"], lib["answers"]["again"]
    assert again["cached"] is True
    assert {k: v for k, v in again.items() if k not in ("id", "cached")} == \
        {k: v for k, v in first.items() if k not in ("id", "cached")}
    s1, s2 = lib["answers"]["stats1"], lib["answers"]["stats2"]
    assert (s1["views"], s1["reads"], s1["estimates"]) == (1, 1, 1)
    assert (s2["views"], s2["reads"], s2["estimates"]) == (1, 1, 1)
    assert s1["plan"] is True and s1["memory"] is None or s1["memory"]["private_mb"] > 0


def test_the_worker_reloads_its_view_when_the_plan_or_the_known_words_change(tmp_path):
    """The same plan written again keeps the view (and the answer kept); a Generate run beside the live worker (it
    holds no file open) gives a new plan, which the next answer is read against; edited known words build it again."""
    case, language = "rp2-ja", "ja"
    root = str(tmp_path / "root")
    _build(root, case)
    cases.generate(root, case)
    rel = f"{SHOWS[case][0]}/recap.txt"
    _write(root, language, rel, _text(case, *RECAP[case]))
    with open(os.path.join(RES, "ja", "library_episode.ass"), encoding="utf-8") as f:
        path = _write(root, language, "HighPriority/Hato/library_episode.ass", f.read())
    worker = _Worker(root, language)
    first = worker.ask({"id": 1, "op": "estimate", "path": path})
    plan_path = os.path.join(root, "results", analyzer.PLAN_FILE)
    os.utime(plan_path, (cases.MTIME, cases.MTIME))
    assert worker.ask({"id": 2, "op": "estimate", "path": path})["cached"] is True
    assert worker.ask({"id": 3, "op": "stats"})["views"] == 1
    _schedule(root, language, rel, "now", 0)
    cases.generate(root, case)
    second = worker.ask({"id": 4, "op": "estimate", "path": path})
    signature = plan_engine.load(plan_path).header["run_signature"]
    assert second["cached"] is False and second["record"]["plan"] == signature != first["record"]["plan"]
    assert worker.ask({"id": 5, "op": "stats"})["views"] == 2
    known = os.path.join(root, "User Files", language, "KnownWord.json")
    os.utime(known, (cases.MTIME + 60, cases.MTIME + 60))
    assert worker.ask({"id": 6, "op": "estimate", "path": path})["cached"] is False
    assert worker.ask({"id": 7, "op": "stats"})["views"] == 3
    assert worker.close() == 0


def test_a_language_with_no_plan_answers_no_plan(library):
    """results/ hold the Japanese plan: a Chinese worker has none — its estimate says so, with the numbers it can
    give without one (% known), and writes nothing."""
    root = library["rp2-ja"]["root"]
    path = _write(root, "zh", "HighPriority/Hato/night_market.srt",
                  open(os.path.join(RES, "zh", "night_market.srt"), encoding="utf-8").read())
    before = _hashes(root)
    worker = _Worker(root, "zh")
    answer = worker.ask({"id": 1, "op": "estimate", "path": path})
    assert worker.close() == 0
    assert (answer["exact"], answer["reason"], answer["words"], answer["pick"]) == (False, "no-plan", [], None)
    assert answer["counted"] > 0 and answer["known_pct"] is not None
    assert _hashes(root) == before


def test_the_worker_ends_when_its_input_closes(library):
    """Its parent died (stdin closed): it ends, exit 0, with or without a request answered."""
    root = library["rp2-ja"]["root"]
    worker = _Worker(root, "ja")
    worker.ask({"id": 1, "op": "stats"})
    assert worker.close(timeout=60) == 0
    silent = _Worker(root, "ja")
    assert silent.close(timeout=60) == 0


def test_the_worker_ends_when_idle(library):
    """No request for its idle time (`--idle-seconds`, `IDLE_SECONDS` = 2 minutes by default): it ends by itself."""
    from app import arrivals_worker
    assert arrivals_worker.IDLE_SECONDS == 120
    root = library["rp2-ja"]["root"]
    worker = _Worker(root, "ja", ["--idle-seconds", "1"])
    worker.ask({"id": 1, "op": "stats"})
    asked = time.perf_counter()
    assert worker.p.wait(timeout=30) == 0
    assert time.perf_counter() - asked >= 0.9


# --- the client (app/services/arrivals.py) ------------------------------------------------------------------------- #

def _client_env(monkeypatch, root):
    for name, value in cases.child_env(root).items():
        monkeypatch.setenv(name, value)


def test_the_client_starts_the_worker_on_first_use_and_again_after_it_idles(library, monkeypatch):
    """A registry job (`arrivals`, automatic, cancelled on quit) started by the first request — never on the caller's
    thread: the answer comes on the reader thread; idle, the worker and its job end; the next request starts it again;
    `stop` ends it."""
    from app.services import jobs
    from app.services.arrivals import ArrivalsWorker
    lib = library["rp2-ja"]
    _client_env(monkeypatch, lib["root"])
    registry = jobs.JobRegistry()
    client = ArrivalsWorker(registry, "ja", args=["--idle-seconds", "3"])
    got, threads = queue.Queue(), []

    def on(answer):
        threads.append(threading.current_thread().name)
        got.put(answer)
    assert registry.live() == ()
    client.estimate(lib["paths"]["recap"], callback=on)
    first = registry.live("arrivals")
    assert len(first) == 1 and first[0].automatic and first[0].on_quit == "cancel"
    answer = got.get(timeout=300)
    want = lib["answers"]["recap"]
    assert {k: v for k, v in answer.items() if k not in ("id", "cached")} == \
        {k: v for k, v in want.items() if k not in ("id", "cached")}
    assert threads == ["arrivals-reader"]
    deadline = time.monotonic() + 60
    while registry.live("arrivals") and time.monotonic() < deadline:
        time.sleep(0.1)
    assert registry.live("arrivals") == () and not client.running        # idle: ended by itself
    client.stats(callback=on)
    again = got.get(timeout=300)
    assert again["op"] == "stats" and again["views"] == 1                 # a new worker
    second = registry.live("arrivals")
    assert len(second) == 1 and second[0].id != first[0].id
    client.stop()
    registry.quit(timeout=30)
    assert registry.live("arrivals") == () and not client.running
    late = []
    client.stats(callback=late.append)
    assert late and "error" in late[0]                                    # stopped: no request starts it again


# A stand-in worker: the first run takes a request and ends without answering (an idle end in between); the second
# answers; with "crash" it ends with exit code 3 instead.
_FAKE = r"""
import json, os, sys
marker, mode = sys.argv[1], sys.argv[2]
line = sys.stdin.buffer.readline()
if mode == "crash":
    sys.exit(3)
if not os.path.exists(marker):
    open(marker, "w").close()
    sys.exit(0)
request = json.loads(line)
sys.stdout.buffer.write((json.dumps({"id": request["id"], "op": request["op"], "run": 2}) + "\n").encode())
sys.stdout.buffer.flush()
"""


@pytest.mark.parametrize("mode", ["idle", "crash"])
def test_a_request_the_ending_worker_never_answered(tmp_path, mode):
    """Taken by a worker that ended as it idled: sent once more to a new one, which answers. Held by one that crashed:
    answered with an error, the job failed."""
    from app.services import jobs
    from app.services.arrivals import ArrivalsWorker
    registry = jobs.JobRegistry()
    marker = str(tmp_path / "ran-once")
    client = ArrivalsWorker(registry, "ja", command=[sys.executable, "-c", _FAKE, marker, mode])
    got = queue.Queue()
    client.stats(callback=got.put)
    answer = got.get(timeout=60)
    if mode == "idle":
        assert answer == {"id": 1, "op": "stats", "run": 2}
    else:
        assert answer["id"] == 1 and "exit code 3" in answer["error"]
        assert [job.state for job in registry.snapshot()] == [jobs.FAILED]
    client.stop()
