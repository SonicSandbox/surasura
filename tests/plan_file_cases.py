"""Four real libraries, each run through a full Generate as the dashboard runs it, and a hash of every file it writes.

The plan file's proof (E1.1 01 §6, RUNBOOK E1.2.0): every output a Generate wrote before the plan file existed is
byte for byte the same with it. `tests/Test Resources/plan_file_base_hashes.json` holds the hashes the base
(2.x-dev 42325db, before any E1.2 change) wrote; `test_plan_file.py` runs the same Generates and compares.

    python tests/plan_file_cases.py --record      # re-record the hash list (only on purpose: it is the proof)

The libraries: the bundled samples (ja, zh) with tests/Test Resources' known words, and RP-2's two libraries
(E0.1: the samples and Test Resources split into a dozen files across NOW / Soon / 6+ Months, with the shipped word
lists), all real text. Each Generate is a child process (`app/analyzer.py --static --no-open`, the dashboard's
command) under its own SURASURA_TEST_ROOT, APPDATA and LOCALAPPDATA, with PYTHONHASHSEED fixed: word_stats.json
lists each word's sources from a set, so its bytes follow the hash seed. Every file's mtime is pinned, so a run's
signature is the same each time. Paths are the root's, so the root is written as <ROOT> before hashing; the run
signature (results/run_signature.txt) hashes the root itself and is proven apart (`test_plan_file.py`).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(REPO, "tests", "Test Resources")
SAMPLES = os.path.join(REPO, "samples")
BASE_HASHES = os.path.join(RES, "plan_file_base_hashes.json")
TIER_FOLDER = {"now": "HighPriority", "soon": "LowPriority", "goal": "GoalContent"}
PHASE = {"now": "PHASE_1_NOW", "soon": "PHASE_2_SOON", "goal": "PHASE_3_LATER"}
MTIME = 1_759_000_000           # every library file's mtime (2025-09-27): a run's signature is the same each time
# Written by the run but not part of the comparison: the plan file is the new output; the stamp is the run signature,
# which hashes the root's own path (the formula is proven on its own).
NOT_COMPARED = {"plan.json.gz", "run_signature.txt"}


def _read(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


def _split_lines(text, n):
    lines = text.splitlines(keepends=True)
    size = -(-len(lines) // n)
    return ["".join(lines[i:i + size]) for i in range(0, len(lines), size)]


def _split_srt(text, n):
    blocks = [b for b in text.replace("\r\n", "\n").split("\n\n") if b.strip()]
    size = -(-len(blocks) // n)
    return ["\n\n".join(blocks[i:i + size]) + "\n" for i in range(0, len(blocks), size)]


def _samples(language):
    """[(tier, name, text)]: the bundled samples as they ship, NOW then Soon."""
    out = []
    for tier, folder in (("now", "HighPriority"), ("soon", "LowPriority")):
        d = os.path.join(SAMPLES, language, folder)
        for name in sorted(os.listdir(d)):
            out.append((tier, name, _read(os.path.join(d, name))))
    return out


def _rp2(language):
    """[(tier, name, text)] in RP-2's order A (E0.1's order probe, which split the same texts)."""
    s = os.path.join(SAMPLES, language)
    r = os.path.join(RES, language)
    if language == "ja":
        ep = _split_srt(_read(os.path.join(s, "HighPriority", "H_priority_sample_2.srt")), 3)
        h1 = _split_lines(_read(os.path.join(s, "HighPriority", "H_priority_sample_1.txt")), 2)
        l1 = _split_lines(_read(os.path.join(s, "LowPriority", "L_priority_sample_1.txt")), 3)
        return [
            ("now", "gotoubun_ep01.srt", ep[0]), ("now", "gotoubun_ep02.srt", ep[1]),
            ("now", "gotoubun_ep03.srt", ep[2]),
            ("now", "novel_school_part1.txt", h1[0]), ("now", "novel_school_part2.txt", h1[1]),
            ("soon", "eighty_six_part1.txt", l1[0]), ("soon", "eighty_six_part2.txt", l1[1]),
            ("soon", "eighty_six_part3.txt", l1[2]),
            ("soon", "phrases_sample.srt", _read(os.path.join(r, "phrases_sample.srt"))),
            ("goal", "eighty_six_ch2.txt", _read(os.path.join(s, "LowPriority", "L_priority_sample_2.txt"))),
            ("goal", "context_test.txt", _read(os.path.join(r, "context_test.txt"))),
            ("goal", "runaway_transcript.txt", _read(os.path.join(r, "runaway_transcript.txt"))),
        ]
    c1 = _split_lines(_read(os.path.join(r, "chinese_text_1.txt")), 2)
    return [
        ("now", "zh_high_1.txt", _read(os.path.join(s, "HighPriority", "H_priority_sample_1.txt"))),
        ("now", "zh_high_2.txt", _read(os.path.join(s, "HighPriority", "H_priority_sample_2.txt"))),
        ("now", "bbc_part1.txt", c1[0]),
        ("soon", "zh_low_1.txt", _read(os.path.join(s, "LowPriority", "L_priority_sample_1.txt"))),
        ("soon", "zh_low_2.txt", _read(os.path.join(s, "LowPriority", "L_priority_sample_2.txt"))),
        ("soon", "bbc_part2.txt", c1[1]),
        ("soon", "traditional_news.txt", _read(os.path.join(r, "traditional_news.txt"))),
        ("goal", "mixed_script_transcript.txt", _read(os.path.join(r, "mixed_script_transcript.txt"))),
        ("goal", "patterns_zh_sample.txt", _read(os.path.join(r, "patterns_zh_sample.txt"))),
        ("goal", "context_test.txt", _read(os.path.join(r, "context_test.txt"))),
    ]


# RP-2's Japanese library with nothing known and a cut-off of one use: every word met is listed — one-kanji words met
# as pieces too, words a set phrase takes — so the plan's every branch moves an output; at two uses a lemma's rare
# reading sits below the cut-off beside its listed one (a sibling). Not in the base's hash list (they came with the
# plan file).
EDGE_CASES = {"every-ja": ("ja", lambda: _rp2("ja"), False, ["--min-freq", "1"]),
              "every-ja-2": ("ja", lambda: _rp2("ja"), False, ["--min-freq", "2"]),
              # The one-kanji rule off: every one-character word listed, and its uses as pieces (三年's 年) counted.
              "every-ja-singles": ("ja", lambda: _rp2("ja"), False, ["--min-freq", "1", "--include-single-chars"])}

# name -> (language, the library, the shipped word lists too, extra analyzer args)
CASES = {
    "samples-ja": ("ja", lambda: _samples("ja"), False, ["--min-freq", "1"]),
    "samples-zh": ("zh", lambda: _samples("zh"), False, []),
    "rp2-ja": ("ja", lambda: _rp2("ja"), True, []),
    "rp2-zh": ("zh", lambda: _rp2("zh"), True, []),
}

# The shipped word lists (git-tracked in User Files/<lang>/): the frequency list's Tier column, the default lists.
SHIPPED = {"ja": ["Blacklist.txt", "IgnoreList.txt", "frequency_list_ja_global50k.csv"],
           "zh": ["Blacklist.txt", "IgnoreList.txt"]}


def build(root, case, order=None):
    """A case's library under `root`, every file's mtime pinned. `order`: [(tier, name)] in place of the case's own
    (the same files; RP-2's other orders)."""
    language, library, shipped, _args = ALL_CASES[case]
    for sub in ("results", "appdata", "localappdata"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    shutil.copytree(os.path.join(REPO, "templates"), os.path.join(root, "templates"), dirs_exist_ok=True)
    data = os.path.join(root, "data", language)
    uf = os.path.join(root, "User Files", language)
    os.makedirs(uf, exist_ok=True)
    known = "KnownWord.json" if language == "ja" else "KnownWords.json"
    pinned = []
    if case not in EDGE_CASES:
        pinned.append(os.path.join(uf, "KnownWord.json"))
        shutil.copy(os.path.join(RES, language, known), pinned[0])
    if shipped:
        for name in SHIPPED[language]:
            with open(os.path.join(uf, name), "wb") as f:
                f.write(_shipped(language, name))
            pinned.append(os.path.join(uf, name))
    texts = {name: (tier, text) for tier, name, text in library()}
    schedule = {p: [] for p in PHASE.values()}
    for tier, name in (order or [(tier, name) for name, (tier, _t) in texts.items()]):
        folder = os.path.join(data, TIER_FOLDER[texts[name][0]])
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(texts[name][1])
        pinned.append(path)
        schedule[PHASE[tier]].append({"physical_path": f"{TIER_FOLDER[texts[name][0]]}/{name}", "title": name,
                                      "origin_source": "Manual Import"})
    with open(os.path.join(uf, "master_manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"schedule": schedule}, f, ensure_ascii=False, indent=2)
    for path in pinned:
        os.utime(path, (MTIME, MTIME))


def _shipped(language, name):
    """A shipped list as committed (`git show HEAD:`): the working tree's copy is user data the app edits when run
    from source (the Ignore button). Without git, the file."""
    rel = f"User Files/{language}/{name}"
    try:
        p = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=REPO, capture_output=True)
        if p.returncode == 0:
            return p.stdout
    except OSError:
        pass
    with open(os.path.join(REPO, rel), "rb") as f:
        return f.read()


ALL_CASES = dict(CASES, **EDGE_CASES)


def child_env(root):
    env = os.environ.copy()
    env.update(SURASURA_TEST_ROOT=root, APPDATA=os.path.join(root, "appdata"),
               LOCALAPPDATA=os.path.join(root, "localappdata"), PYTHONIOENCODING="utf-8", PYTHONHASHSEED="0",
               PYTHONPATH=REPO + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""))
    env.pop("SURASURA_DEBUG_WORD_STATS", None)
    return env


def generate(root, case, extra_env=None):
    """A full Generate of the case's library, as the dashboard runs it; the store's helper finished after. Returns
    the analyzer's output (stdout + stderr)."""
    language, _library, _shipped_lists, args = ALL_CASES[case]
    env = child_env(root)
    env.update(extra_env or {})
    cmd = [sys.executable, os.path.join(REPO, "app", "analyzer.py"), f"--language={language}", "--static",
           "--no-open"] + args
    p = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = p.stdout + "\n--- stderr ---\n" + p.stderr
    if p.returncode != 0:
        raise RuntimeError(f"Generate failed ({p.returncode}):\n{out[-3000:]}")
    # The run may have started the store's helper (the library copy's export): let it finish, so the root can go.
    subprocess.run([sys.executable, os.path.join(REPO, "app", "library_store.py"), "maintain", "--language",
                    language], cwd=REPO, env=child_env(root), capture_output=True)
    return out


def _root_spellings(root):
    root = os.path.abspath(root)
    forms = {root, root.replace("\\", "/"), json.dumps(root)[1:-1], json.dumps(root.replace("\\", "/"))[1:-1]}
    return sorted(forms, key=len, reverse=True)


def output_hashes(root):
    """{relative path under results/: sha256} of every file the run wrote there but NOT_COMPARED, the root's path
    written as <ROOT>."""
    results = os.path.join(root, "results")
    out = {}
    spellings = [s.encode("utf-8") for s in _root_spellings(root)]
    for folder, _dirs, files in os.walk(results):
        for name in files:
            if name in NOT_COMPARED or name.endswith(".tmp"):
                continue
            path = os.path.join(folder, name)
            with open(path, "rb") as f:
                data = f.read()
            for s in spellings:
                data = data.replace(s, b"<ROOT>")
            out[os.path.relpath(path, results).replace("\\", "/")] = hashlib.sha256(data).hexdigest()
    return dict(sorted(out.items()))


# The run signature on fixed inputs (paths that exist nowhere, so no stat, no root): the base's digests are the proof
# that the signature's formula is unchanged — the Generates' own stamps hash their root's path.
SIGNATURE_INPUTS = {
    "ja-ordered": ("ja", [["C:/library/data/ja/HighPriority/ep01.srt", "HighPriority", 10, "subtitle"],
                          ["C:/library/data/ja/HighPriority/小説 第1巻.txt", "HighPriority", 10, "text"],
                          ["C:/library/data/ja/LowPriority/ep02.srt", "LowPriority", 5, "subtitle"],
                          ["C:/library/data/ja/GoalContent/動画.srt", "GoalContent", 2, "youtube"]], []),
    "ja-moved": ("ja", [["C:/library/data/ja/LowPriority/ep02.srt", "HighPriority", 10, "subtitle"],
                        ["C:/library/data/ja/HighPriority/ep01.srt", "HighPriority", 10, "subtitle"],
                        ["C:/library/data/ja/HighPriority/小説 第1巻.txt", "LowPriority", 5, "text"],
                        ["C:/library/data/ja/GoalContent/動画.srt", "GoalContent", 2, "youtube"]], []),
    "zh-ordered": ("zh", [["C:/library/data/zh/HighPriority/新闻.txt", "HighPriority", 10, "text"],
                          ["C:/library/data/zh/GoalContent/bbc.txt", "GoalContent", 2, "text"]], ["--zh-script", "s"]),
    "ja-empty": ("ja", [], ["--min-freq", "3", "--only-i-plus-one"]),
}


def signatures(root, order_free=False):
    """{input name: compute_run_signature(...)} in a child process under an empty `root` (settings: the defaults)."""
    code = r"""
import json, sys
from app import analyzer
inputs, order_free = json.loads(sys.stdin.read()), sys.argv[1] == "1"
out = {}
for name, (language, found, argv) in inputs.items():
    args = analyzer.parse_analysis_args(["--language", language] + argv)
    found = [tuple(f) for f in found]
    out[name] = (analyzer.compute_run_signature(language, found, args, order_free=True) if order_free
                 else analyzer.compute_run_signature(language, found, args))
print(json.dumps(out))
"""
    os.makedirs(root, exist_ok=True)
    p = subprocess.run([sys.executable, "-c", code, "1" if order_free else "0"], cwd=REPO, env=child_env(root),
                       input=json.dumps(SIGNATURE_INPUTS), capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        raise RuntimeError("signature run failed:\n" + p.stderr[-3000:])
    return json.loads(p.stdout.strip().splitlines()[-1])


def record(base_dir):
    """Every case's hash list, from the code as it stands (run on the base, on purpose only)."""
    hashes = {"signatures": signatures(os.path.join(base_dir, "signatures"))}
    for case in CASES:
        root = os.path.join(base_dir, case)
        shutil.rmtree(root, ignore_errors=True)
        build(root, case)
        generate(root, case)
        hashes[case] = output_hashes(root)
        print(case, len(hashes[case]), "files")
    return hashes


if __name__ == "__main__":
    import tempfile
    if "--record" not in sys.argv:
        raise SystemExit(__doc__)
    work = tempfile.mkdtemp(prefix="plan-file-cases-")
    hashes = record(work)
    hashes["_base"] = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True,
                                     text=True).stdout.strip()
    with open(BASE_HASHES, "w", encoding="utf-8") as f:
        json.dump(hashes, f, ensure_ascii=False, indent=1)
        f.write("\n")
    shutil.rmtree(work, ignore_errors=True)
    print("recorded", BASE_HASHES)
