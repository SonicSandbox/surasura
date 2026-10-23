"""W-1: a real Generate with a watched episode, exact counts.

Two shows in NOW, three episodes each, cut from the bundled samples' real text; one real line seeded into Show A's
first episode alone (W_only: a word met nowhere else) and the same word in two real lines, one in Show A's first
episode and one in Show B's third (W_later). Generate runs as the dashboard starts it (`analyzer.py`, its own process,
every word met listed: `--min-freq 1`). Then:

  - both words are listed;
  - Show A's first episode marked watched → `order_version` +1 → Generate: W_only leaves the list; W_later stays with
    exactly its uses outside that episode — counted here, file by file, through the token store's own tokenizer, never
    read back from a list — and every other word with exactly the first run's count less that episode's uses (the
    first run's own per-file record, its plan file; each word the tokenizer counts as the list does checked against
    that tokenizer too); the name tables are byte for byte what they were, the episode set aside in the token store;
    例文 (`sentence_corpus.best_for`) still finds W_only's sentence in the watched episode;
  - un-marked → Generate: the list is the first run's, byte for byte;
  - with *Keep studying watched episodes* on, the stone changes nothing in the list;
  - the set-aside episode is part of what a run reads (the run signature's "reference" part): nothing moved, Generate
    skips; that episode edited alone (a line added), Generate runs — its names and sentences may have changed.

What a wrong answer would cost a learner: words he has already met counted as still ahead of him (the list ranks
them over words to come), or words still ahead lost from it; a stone that changes what a name is; an Undo that
leaves the list different from before the click. Japanese and Chinese alike, under the per-test SURASURA_TEST_ROOT.
"""
import csv
import io
import json
import os
import subprocess
import sys
from collections import Counter

import pytest

from app import analyzer, library_store as ls, plan_engine, token_index as ti
from tests.plan_file_cases import _split_lines, _split_srt, child_env
from tests.test_library_store_support import LANGUAGES, entry, roots, write_manifest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIST = "priority_learning_list.csv"

# Show A and Show B: each a bundled sample cut in three (A's a subtitle, cut at its cues)
SHOWS = {"ja": ("samples/ja/HighPriority/H_priority_sample_2.srt", "samples/ja/HighPriority/H_priority_sample_1.txt"),
         "zh": ("samples/zh/HighPriority/H_priority_sample_1.txt", "samples/zh/HighPriority/H_priority_sample_2.txt")}
# A real line added to the watched episode, to edit it alone
EDIT = {"ja": "冒険は危険だが、価値がある。", "zh": "冒险总是伴随着巨大的挑战。"}
REUSED = "Nothing affecting the analysis changed"
FOLDERS = {"ja": ("五等分", "学校"), "zh": ("魔王", "龙神")}
# (W_only, its line in A-Ep01), (W_later, its line in A-Ep01, its line in B-Ep03) — real lines from Test Resources
SEEDS = {"ja": (("冒険", "彼は毎日冒険に出かけます。"),
                ("文化祭", "文化祭まで、あと三日しかないよ。", "文化祭の準備、手伝ってくれない？")),
         "zh": (("夜市", "今天我们要去台北的夜市吃东西。"),
                ("冒险", "我们需要去寻找新的冒险。", "这是一个非常刺激的冒险。"))}


def _read(rel):
    with open(os.path.join(REPO, *rel.split("/")), encoding="utf-8-sig") as f:
        return f.read()


def _with_line(text, line, subtitle):
    """`text` with one more real line at its end: a cue of its own in a subtitle."""
    if subtitle:
        return text.rstrip("\n") + f"\n\n900\n00:59:00,000 --> 00:59:02,000\n{line}\n"
    return text.rstrip("\n") + "\n" + line + "\n"


def _library(language):
    """Show A Ep01–Ep03 then Show B Ep01–Ep03 in NOW, with the seeds -> (store, {name: path}, {name: item id})."""
    data_dir, user_files_dir = roots(language)
    (only, only_line), (later, later_a, later_b) = SEEDS[language]
    a_src, b_src = SHOWS[language]
    a_sub = a_src.endswith(".srt")
    a_eps = _split_srt(_read(a_src), 3) if a_sub else _split_lines(_read(a_src), 3)
    b_eps = _split_lines(_read(b_src), 3)
    a_eps[0] = _with_line(_with_line(a_eps[0], only_line, a_sub), later_a, a_sub)
    b_eps[2] = _with_line(b_eps[2], later_b, False)
    texts = {}
    for show, eps, ext in (("A", a_eps, ".srt" if a_sub else ".txt"), ("B", b_eps, ".txt")):
        folder = FOLDERS[language][show == "B"]
        for n, text in enumerate(eps, 1):
            texts[f"{show}{n}"] = (f"HighPriority/{folder}/ep0{n}{ext}", text)
    doc = {"schedule": {p: [] for p in ls.PHASES}}
    paths = {}
    for name, (rel, text) in texts.items():
        path = os.path.join(data_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        paths[name] = path
        doc["schedule"][ls.TIERS["now"][0]].append(entry(rel))
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    ids = {name: store.item_id(os.path.relpath(path, data_dir).replace("\\", "/")) for name, path in paths.items()}
    return store, paths, ids


def _generate(root, language, said=False):
    """A full Generate in its own process, as the dashboard runs it (the store's helper after) -> the list's bytes
    (`said`: and what the run printed)."""
    cmd = [sys.executable, os.path.join(REPO, "app", "analyzer.py"), f"--language={language}", "--static",
           "--no-open", "--min-freq", "1"]
    p = subprocess.run(cmd, cwd=REPO, env=child_env(root), capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    assert p.returncode == 0, (p.stdout + p.stderr)[-3000:]
    subprocess.run([sys.executable, os.path.join(REPO, "app", "library_store.py"), "maintain", "--language", language],
                   cwd=REPO, env=child_env(root), capture_output=True)
    with open(os.path.join(root, "results", LIST), "rb") as f:
        return (f.read(), p.stdout) if said else f.read()


def _occurrences(raw):
    """{(Word, Reading): Occurrences} of a list's bytes."""
    rows = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    return {(row["Word"], row.get("Reading") or ""): int(row["Occurrences"]) for row in rows}


def _uses(language, paths):
    """{name: Counter((lemma, reading) -> uses)}: each file tokenized alone by the token store's own tokenizer
    (`token_index.make_tokenizer`), counted as the store counts a file — every word holding the language's script,
    less a one-kanji word's uses as a piece of something else."""
    tokenize = ti.make_tokenizer(language)
    out = {}
    for name, path in paths.items():
        got = tokenize(path)
        counts = Counter(got["counts"])
        counts.subtract(got.get("bound") or {})
        out[name] = Counter({tuple(key.split("|", 1)): n for key, n in counts.items() if n > 0})
    return out


def _child(root, code):
    """The last line `code` prints in a process with Generate's environment (its token store, its library store)."""
    p = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=child_env(root), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stderr[-2000:]
    return p.stdout.strip().splitlines()[-1]


def _token_store(root, language):
    """The token store Generate wrote: (counted files, set-aside files, the name tables byte for byte — the tables
    and the names Ignore names reads, as stored, and the records the arrivals gate sums)."""
    return json.loads(_child(root, (
        "import hashlib, json; from app import token_index as ti; "
        f"s = ti.open_store({language!r}); "
        "names = repr((s.get_meta('names_tables'), s.get_meta('names_words'), s.names_records())); "
        "print(json.dumps([len(s.counted_files()), len(s.aside_files()), s.get_meta('names_tables') is not None, "
        "hashlib.sha256(names.encode('utf-8')).hexdigest()])); s.close()")))


def _example_sentences(root, language, key):
    """例文's sentences for `key` (`sentence_corpus.best_for`), as Anki Backfill asks."""
    return json.loads(_child(root, (
        "import json; from app import sentence_corpus as sc; "
        f"found = sc.best_for({language!r}, {{{key!r}}}); "
        f"print(json.dumps([text for _o, text, _s, _f in found.get({key!r}, [])], ensure_ascii=False))")))


def _plan_uses(root, language, path):
    """{(Word, Reading): uses} the run counted in the file at `path`: its plan file's per-file record (each word's and
    each set phrase's uses there)."""
    plan = plan_engine.load(os.path.join(root, "results", analyzer.PLAN_FILE))
    rel = os.path.relpath(path, roots(language)[0]).replace("\\", "/")
    f = [ls.path_key(entry[0]) for entry in plan.files].index(ls.path_key(rel))
    line, out = plan.per_file[f], Counter()
    for table in ("main", "ph"):
        pairs = line.get(table) or []
        for k, n in zip(pairs[0::2], pairs[1::2]):
            out[tuple(plan.keys[k][:2])] += n
    return out


def _key(occurrences, word):
    keys = [key for key in occurrences if key[0] == word]
    assert len(keys) == 1, (word, keys)
    return keys[0]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_watched_episode_leaves_the_counts_exactly_and_un_marking_gives_the_list_back_byte_for_byte(language):
    root = os.environ["SURASURA_TEST_ROOT"]
    store, paths, ids = _library(language)
    (only, _l), (later, _a, _b) = SEEDS[language]
    uses = _uses(language, paths)
    total = sum(uses.values(), Counter())
    holders = {word: [n for n in paths if any(key[0] == word for key in uses[n])] for word in (only, later)}
    assert holders == {only: ["A1"], later: ["A1", "B3"]}, "the seeds are where this library puts them, and only there"

    first = _generate(root, language)
    listed = _occurrences(first)
    w_only, w_later = _key(listed, only), _key(listed, later)
    assert listed[w_only] == total[w_only] and listed[w_later] == total[w_later], "both listed, every use counted"
    episode_uses = _plan_uses(root, language, paths["A1"])
    tokens = _token_store(root, language)
    assert tokens[:2] == [6, 0] and (tokens[2] or language == "zh"), tokens

    v = store.versions()["order_version"]
    assert store.set_watched([ids["A1"]]) is not None
    assert store.versions()["order_version"] == v + 1 and store.journey_pending()
    watched = _occurrences(_generate(root, language))
    assert w_only not in watched, "a word met only in the watched episode steps back"
    assert watched[w_later] == total[w_later] - uses["A1"][w_later] == uses["B3"][w_later], "only its use ahead counts"
    # Every word: the first run's count less the episode's uses, exactly (a word left with none steps back)
    expected = {key: n - episode_uses[key] for key, n in listed.items() if n - episode_uses[key]}
    assert watched == expected
    # ...and the episode's uses as the token store's tokenizer counts them, for every word it counts as the list does
    # (the rest are set phrases and the names the library's tables join, which it reads alone)
    plain = [key for key, n in listed.items() if total[key] == n]
    assert len(plain) >= 0.9 * len(listed), len(plain)
    assert {key: episode_uses[key] for key in plain} == {key: uses["A1"][key] for key in plain}
    after = _token_store(root, language)
    assert after[:2] == [5, 1] and after[2:] == tokens[2:], "set aside: the name tables are what they were"

    with open(paths["A1"], encoding="utf-8") as f:
        episode = f.read()
    sentences = _example_sentences(root, language, w_only)
    assert sentences and all(text in episode for text in sentences), "例文 still finds the watched episode's sentence"

    assert store.set_watched([ids["A1"]], False) is not None
    assert _generate(root, language) == first, "un-marked: the list is the first run's, byte for byte"

    store.set_library_options(keep_watched=True)
    store.set_watched([ids["A1"]])
    assert _generate(root, language) == first, "Keep studying watched episodes: the stone changes nothing"

    store.set_library_options(keep_watched=False)                    # set aside again
    _generate(root, language)
    assert REUSED in _generate(root, language, said=True)[1], "nothing moved: Generate skips"
    with open(paths["A1"], encoding="utf-8") as f:
        text = f.read()
    with open(paths["A1"], "w", encoding="utf-8", newline="") as f:
        f.write(_with_line(text, EDIT[language], paths["A1"].endswith(".srt")))
    assert REUSED not in _generate(root, language, said=True)[1], "the watched episode edited alone: Generate runs"
    store.close()
