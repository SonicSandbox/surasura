"""E-L2G: the level-2 Generate's gaps closed before the flip (SPEC § 6; inert at `plan_rules.SENTENCE_TABLE = 0`).

On RP-2's real Japanese and Chinese libraries (tests/plan_file_cases.py), each Generated at level 2 in a child process
as the dashboard runs it. What these prove:
  - **the redraw's word_stats.json (and its file_statistics.json / .txt) is written whole or not at all** (E-REDRAW's crash drill: a redraw killed while it
    wrote the file left it empty, and the next look ran a whole Generate): a redraw that dies part-way through that
    write leaves the last one as it was, and the next look redraws.
  - **a list call reads the lines' text without their tokens** (`token_index.Store.file_texts`; E-L2G: decoding each
    shown line's whole file was 0.70 of the level-2 pick's 0.78 s at 2k): no file's tokens decoded, the same columns —
    and, on any doubt, the full decode, the same columns again; the texts are `file_tokens`' over every file of the
    store and over made lines (quotes, backslashes, the cut inside a line, an empty token list, control characters).
  - ***Only i+1*'s second round reads nothing again** (row 15: round 2 repeated the whole pick, +1.29 s at 2k): one
    reader asked twice in two orders, as the Generate's rounds ask it, reads each file's text and the table's columns
    once, and answers what a fresh reader answers — and (E-L2G 4) parses the last run's shown.json.gz once and builds
    the rows' order-free arrays once: only the order's own are built again.
  - **a redraw whose lines are all kept makes no tagger** (row 11: 0.09 s of the redraw was a fresh Japanese tagger for
    `strip_verse_number` on a line led by digits): shown.json.gz keeps what Context shows of such a line beside its
    text, so a line read back from it is shown as the Generate showed it, with no tagger loaded.
"""
import json
import os
import subprocess
import sys
import zlib

import pytest

from app import analyzer, token_index
from tests import plan_file_cases as cases
from tests.test_e_redraw import LEVEL_2, _columns, _env, _generated, _move, _redraw


@pytest.fixture(scope="module", params=["ja", "zh"])
def gen(request, tmp_path_factory):
    """RP-2's library in one language, Generated at level 2 (read only)."""
    return request.param, _generated(request.param, tmp_path_factory.mktemp(f"e-l2g-{request.param}"))


def _child(root, script, *args):
    """`script` run in a child on `root`'s own data (its token store lives in the root's local data folder) -> its
    last line, read as JSON."""
    p = subprocess.run([sys.executable, "-c", script, *args], cwd=cases.REPO, env=_env(root), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
    return json.loads(p.stdout.strip().splitlines()[-1])

# Loaded first in the child (a sitecustomize on its path): the first write to word_stats.json (or the file
# E_L2G_DIE_IN names) — the file itself or a temp beside it — writes half its text and the process dies there, as a
# crash would.
_DIE_IN_WORD_STATS = r"""
import builtins, os
_open = builtins.open


class _Dying:
    def __init__(self, f):
        self._f = f

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return self._f.__exit__(*exc)

    def write(self, text):
        self._f.write(text[:len(text) // 2])
        self._f.flush()
        os._exit(9)

    def __getattr__(self, name):
        return getattr(self._f, name)


def _opened(file, mode="r", *args, **kwargs):
    f = _open(file, mode, *args, **kwargs)
    if "w" in mode and os.path.basename(str(file)).startswith(os.environ.get("E_L2G_DIE_IN", "word_stats.json")):
        return _Dying(f)
    return f


builtins.open = _opened
"""


def _killed_in(language, tmp_path, name):
    """A level-2 library, one show moved, and its redraw killed half-way through writing results/`name` -> (the
    file before, after, the root)."""
    root = _generated(language, tmp_path / "lib")
    _move(root, language, "top")
    stats = os.path.join(root, "results", name)
    with open(stats, encoding="utf-8") as f:
        before = f.read()
    hook = tmp_path / "hook"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text(_DIE_IN_WORD_STATS, encoding="utf-8")
    env = _env(root)
    env["PYTHONPATH"] = str(hook) + os.pathsep + env.get("PYTHONPATH", "")
    env["E_L2G_DIE_IN"] = name
    p = subprocess.run([sys.executable, os.path.join(cases.REPO, "app", "analyzer.py"), f"--language={language}",
                        "--static", "--no-open", "--from-plan"], cwd=cases.REPO, env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 9, f"the redraw died inside {name}'s write: " + (p.stdout + p.stderr)[-1500:]
    with open(stats, encoding="utf-8") as f:
        return before, f.read(), root


@pytest.mark.parametrize("language, name", [("ja", "file_statistics.json"), ("zh", "file_statistics.json"),
                                            ("ja", "file_statistics.txt"), ("zh", "file_statistics.txt")])
def test_a_redraw_killed_while_it_writes_the_file_statistics_leaves_the_last_ones_and_the_next_look_redraws(
        language, name, tmp_path):
    # why: the lead's ruling 3 — the redraw rewrote file_statistics.json and .txt in place, so a kill there left them
    # cut until the next redraw; each is written whole or not at all, as word_stats.json
    before, after, root = _killed_in(language, tmp_path, name)
    assert after == before, f"a redraw killed mid-write leaves the last {name} whole"
    if name.endswith(".json"):
        json.loads(after)
    out = _redraw(root, language)
    assert "Redrew the journey" in out and "generating" not in out.lower(), out[-1500:]


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_redraw_killed_while_it_writes_word_stats_leaves_the_last_one_and_the_next_look_redraws(language,
                                                                                                    tmp_path):
    root = _generated(language, tmp_path / "lib")
    _move(root, language, "top")
    stats = os.path.join(root, "results", "word_stats.json")
    with open(stats, encoding="utf-8") as f:
        before = f.read()
    hook = tmp_path / "hook"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text(_DIE_IN_WORD_STATS, encoding="utf-8")
    env = _env(root)
    env["PYTHONPATH"] = str(hook) + os.pathsep + env.get("PYTHONPATH", "")
    p = subprocess.run([sys.executable, os.path.join(cases.REPO, "app", "analyzer.py"), f"--language={language}",
                        "--static", "--no-open", "--from-plan"], cwd=cases.REPO, env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 9, "the redraw died inside word_stats.json's write: " + (p.stdout + p.stderr)[-1500:]
    with open(stats, encoding="utf-8") as f:
        after = f.read()
    assert after == before, "a redraw killed mid-write leaves the last word_stats.json whole"
    json.loads(after)
    out = _redraw(root, language)               # the next look: a redraw, never a whole Generate
    assert "Redrew the journey" in out and "generating" not in out.lower(), out[-1500:]


# Loaded first in the redraw's child: every memo the one reader hands the score, and at the child's exit how many
# entries they still hold.
_MEMO_LEFT = r"""
import atexit, json, os
from app import sentence_score
_choose, _memos = sentence_score.choose, []


def _asked(*args, **kwargs):
    if kwargs.get("memo") is not None:
        _memos.append(kwargs["memo"])
    return _choose(*args, **kwargs)


def _said():
    with open(os.environ["E_L2G_MEMO"], "w") as f:
        json.dump({"asks": len(_memos), "left": sum(len(m) for m in _memos)}, f)


sentence_score.choose = _asked
atexit.register(_said)
"""


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_redraw_lets_its_readers_memo_go_once_its_one_call_is_over(language, tmp_path):
    # why: E-L2G 3, row 11's memory — the redraw's one reader kept its memo (every file's text, the rows' columns and
    # arrays) to the redraw's end, through the list and the journey written after it: the redraw's memory rose 576 →
    # 671 MB at 20,000 files against the same redraw with no memo. Its one call over, the memo is let go
    root = _generated(language, tmp_path / "lib")
    _move(root, language, "top")
    hook = tmp_path / "hook"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text(_MEMO_LEFT, encoding="utf-8")
    env = _env(root)
    env["PYTHONPATH"] = str(hook) + os.pathsep + env.get("PYTHONPATH", "")
    env["E_L2G_MEMO"] = str(tmp_path / "memo.json")
    p = subprocess.run([sys.executable, os.path.join(cases.REPO, "app", "analyzer.py"), f"--language={language}",
                        "--static", "--no-open", "--from-plan"], cwd=cases.REPO, env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0 and "Redrew the journey" in p.stdout, (p.stdout + p.stderr)[-1500:]
    with open(env["E_L2G_MEMO"], encoding="utf-8") as f:
        got = json.load(f)
    assert got["asks"] >= 1 and got["left"] == 0, got


# The one reader asked for the list's rows as the level-2 Generate asks it (no kept text read: every line from the
# token store), each file's whole-token decode counted; `doubt`: every text read is in doubt (the full decode instead).
_COUNTED_READER = r"""
import json, sys
from app import analyzer, token_index
language, results, keys, clean, doubt = sys.argv[1], sys.argv[2], json.loads(sys.argv[3]), sys.argv[4], sys.argv[5]
n = {"tokens": 0, "texts": 0}
tokens, texts = token_index.Store.file_tokens, getattr(token_index.Store, "file_texts", None)
def counted_tokens(self, path):
    n["tokens"] += 1
    return tokens(self, path)
def counted_texts(self, path):
    n["texts"] += 1
    return texts(self, path)
token_index.Store.file_tokens = counted_tokens
if texts is not None:
    token_index.Store.file_texts = counted_texts
if doubt == "1":
    token_index._decode_texts = lambda blob, lines: None
analyzer._read_shown = lambda results_dir, run_signature, forms=None: {}
got = analyzer.ListSentences(language, 3, clean == "1", results_dir=results)([tuple(k) for k in keys], None)
print(json.dumps({"n": n, "got": [[list(k), v] for k, v in got.items()]}, ensure_ascii=False))
"""


@pytest.mark.parametrize("clean", [False, True])
def test_a_list_call_reads_its_lines_text_without_decoding_any_files_tokens(gen, clean):
    # why: E-L2G, row 1 — the level-2 pick's walk decoded one whole file's tokens (json.loads: 78 % of its read) for
    # each line it showed, only for the line's text; a list call weighs no young word, so the text is read alone
    # (`file_texts`). No token decoded, the Generate's own columns; every read in doubt: the full decode, the same
    language, root = gen
    results = os.path.join(root, "results")
    listed = _columns(results)
    keys = json.dumps([list(k) for k in listed], ensure_ascii=False)
    fast = _child(root, _COUNTED_READER, language, results, keys, "1" if clean else "0", "0")
    doubted = _child(root, _COUNTED_READER, language, results, keys, "1" if clean else "0", "1")
    assert fast["n"]["tokens"] == 0, f"a list call decoded {fast['n']['tokens']} files' tokens for their texts"
    assert fast["n"]["texts"] > 0 and doubted["n"]["tokens"] >= fast["n"]["texts"], (fast["n"], doubted["n"])
    assert fast["got"] == doubted["got"], "the same lines, read either way"
    if not clean:
        got = {tuple(k): v for k, v in fast["got"]}
        assert {k: v for k, v in got.items() if v} == {k: v for k, v in listed.items() if v}, "the list's columns"


# The one reader asked as Connect's pick asks it, with a young word weighed (each line's youngest word is read from its
# tokens), each file's token decode and text-only read counted.
_YOUNG_READER = r"""
import json, os, sys
from app import sentence_corpus, sentence_score, sentence_table, settings_manager, token_index
from app.path_utils import get_data_path
language, results, keys = sys.argv[1], sys.argv[2], [tuple(k) for k in json.loads(sys.argv[3])]
n = {"tokens": 0, "texts": 0}
tokens, texts = token_index.Store.file_tokens, token_index.Store.file_texts
def counted_tokens(self, path):
    n["tokens"] += 1
    return tokens(self, path)
def counted_texts(self, path):
    n["texts"] += 1
    return texts(self, path)
token_index.Store.file_tokens, token_index.Store.file_texts = counted_tokens, counted_texts
tab = sentence_table.open_table(os.path.join(results, sentence_table.TABLE_FILE), language=language)
_lo, _hi, low, high = sentence_corpus.length_range(settings_manager.load_settings())
moment = sentence_score.Moment(young={keys[1][0]: 1.0}, root=get_data_path(language))
got = sentence_score.choose(language, keys[:5], n=3, length=(low, high), moment=moment, table=tab)
print(json.dumps({"n": n, "rows": sum(1 for v in got.values() if v)}))
"""


def test_a_pick_that_weighs_a_young_word_still_reads_each_files_tokens(gen):
    # why: E-L2G — `file_texts` stands in for a file's tokens only when no young word is weighed: a young word is found
    # in a line's tokens (Connect's pick weighs a card's young co-words), so with one weighed every file the walk reads
    # decodes its tokens, and none is read as text alone
    language, root = gen
    results = os.path.join(root, "results")
    keys = json.dumps([list(k) for k in _columns(results)], ensure_ascii=False)
    got = _child(root, _YOUNG_READER, language, results, keys)
    assert got["rows"] > 0 and got["n"]["tokens"] > 0, got
    assert got["n"]["texts"] == 0, f"a pick weighing a young word read {got['n']['texts']} files' texts alone"


_ALL_TEXTS = r"""
import json, sys
from app import token_index
st = token_index.open_reader(sys.argv[1])
paths = [r[0] for r in st.conn.execute("SELECT path FROM files")]
same = doubt = 0
for p in paths:
    texts = st.file_texts(p)
    if texts is None:
        doubt += 1
    elif texts == [s[0] for s in st.file_tokens(p)]:
        same += 1
print(json.dumps({"files": len(paths), "same": same, "doubt": doubt}))
"""


def test_every_files_texts_read_alone_are_its_tokens_texts(gen):
    # why: `file_texts` stands in for `file_tokens`' texts in every list call — over every file of a real store
    # (kept, set aside and counted alike), the same texts, and none read in doubt
    language, root = gen
    got = _child(root, _ALL_TEXTS, language)
    assert got["files"] > 0 and got["same"] == got["files"] and got["doubt"] == 0, got


# Real lines as a subtitle or a book holds them, each a JSON hazard: quotes and backslashes (escaped), the cut's own
# characters inside a line (`"` escaped there: no cut), CRLF and control characters, a line no token holds.
_MADE = [
    ("「\"ねえ\"って言ったでしょ？」", [["ねえ", "ネエ", "ねえ", "ねえ"], ["言う", "イウ", "言っ", "言っ"]]),
    ("C:\\Users\\データ\\字幕.srt を開いて。", [["開く", "ヒラク", "開い", "開い"]]),
    ("配列は ]], [\"a\" と書く。", [["配列", "ハイレツ", "配列", "配列"], ["書く", "カク", "書く", "書く"]]),
    ("一行目\r\n二行目\t\x00\x1f終わり", [["一", "イチ", "一", "一"]]),
    ("……", []),
    ("我們明天見吧！\u2028", [["我們", "", "我們", "我們"], ["見", "", "見", "見"]]),
    ("", []),
    ("🎌 旗だ", [["旗", "ハタ", "旗", "旗"]]),
]


def _blob(sentences):
    return token_index._encode_tokens(sentences), token_index._encode_tokens([1] * len(sentences))


def test_made_lines_texts_read_alone_are_the_texts_and_a_line_that_would_cut_wrong_is_read_in_full():
    # why: the text is cut out of the tokens' JSON — a quote inside a line is escaped, so the cut is a sentence's end;
    # only a string ending in the cut's own characters cuts once too often, and the count (the row's `lines`)
    # says so: in doubt, never a wrong text
    truth = [s[0] for s in _MADE]
    assert token_index._decode_texts(*_blob(_MADE)) == truth
    for one in _MADE:
        assert token_index._decode_texts(*_blob([one])) == [one[0]]
    text_ends_in_cut = ("配列の終わりは ]], [", [["配列", "ハイレツ", "配列", "配列"]])
    token_ends_in_cut = ("記号だ", [["]], [", "", "]], [", "]], ["], ["だ", "ダ", "だ", "だ"]])
    for wrong in (text_ends_in_cut, token_ends_in_cut):
        assert token_index._decode_texts(*_blob(_MADE[:2] + [wrong] + _MADE[2:])) is None
        assert token_index._decode_texts(*_blob([wrong])) is None
    # a cut too many that the count can't see (a `lines` column that agrees with it): each piece after a wrong cut
    # starts inside a token, no line's start — that alone says so
    blob = token_index._encode_tokens([token_ends_in_cut])
    pieces = zlib.decompress(blob).decode("utf-8")[3:].split(token_index._CUT)
    assert len(pieces) > 1 and token_index._decode_texts(blob, token_index._encode_tokens([1] * len(pieces))) is None
    blob, lines = _blob(_MADE)
    assert token_index._decode_texts(blob, token_index._encode_tokens([1] * (len(_MADE) - 1))) is None
    assert token_index._decode_texts(blob, None) is None, "no `lines` column: read in full"
    assert token_index._decode_texts(blob[:-3], lines) is None, "a damaged blob: read in full"
    assert token_index._decode_texts(token_index._encode_tokens([]), None) is None, "no line: the store's [] in full"
    assert token_index._decode_texts(*_blob([[None, []]])) is None, "a line held badly: read in full"


# The Generate's *Only i+1* rounds, as its loop asks them of one reader: every row in the list's order, then the rows
# left (those with no clean line, or with none: every seventh) in their own order — each file's text read and the
# table's columns taken counted; then a fresh reader asked the second round alone (today's: a reader a call).
_ROUNDS = r"""
import collections, json, os, sys
from app import analyzer, sentence_score, sentence_table, token_index
language, results, keys = sys.argv[1], sys.argv[2], [tuple(k) for k in json.loads(sys.argv[3])]
reads, taken = collections.Counter(), [0]
tokens, texts, take = token_index.Store.file_tokens, getattr(token_index.Store, "file_texts", None), sentence_score._take
def counted_tokens(self, path):
    reads[path] += 1
    return tokens(self, path)
def counted_texts(self, path):
    reads[path] += 1
    got = texts(self, path)
    if got is None:
        reads[path] -= 1                # (in doubt: its file_tokens read counts it)
    return got
def counted_take(tab, want):
    taken[0] += 1
    return take(tab, want)
token_index.Store.file_tokens, sentence_score._take = counted_tokens, counted_take
if texts is not None:
    token_index.Store.file_texts = counted_texts
analyzer._read_shown = lambda results_dir, run_signature, forms=None: {}
table = sentence_table.open_table(os.path.join(results, sentence_table.TABLE_FILE), language=language,
                                  engine=analyzer.engine_id(), run_signature=analyzer.read_run_stamp(results))
one = analyzer.ListSentences(language, 3, True, results_dir=results, table=table)     # (the Generate's own table)
first = one(keys, {k: at for at, k in enumerate(keys)})
left = [k for k in keys if first.get(k)]
if len(left) == len(keys):              # (every word has a clean line: every seventh left off, as a round would)
    left = [k for at, k in enumerate(keys) if at % 7]
order = {k: at for at, k in enumerate(left)}
second = one(left, order)
counts = {"files": len(reads), "twice": sum(1 for n in reads.values() if n > 1), "taken": taken[0]}
fresh = analyzer.ListSentences(language, 3, True, results_dir=results)(left, dict(order))
print(json.dumps({"counts": counts, "left": len(left), "same": second == fresh, "first": len(first)}))
"""


def test_only_i_plus_ones_second_round_reads_no_files_text_and_no_column_again(gen):
    # why: E-L2G, row 15 — *Only i+1* asks the reader again for the words left, in their own order; each call made a
    # new moment and no memo, so round 2 took every column and decoded every file's text again. One reader keeps
    # what no order changes: each file read once, the columns taken once, the answer a fresh reader's
    language, root = gen
    keys = json.dumps([list(k) for k in _columns(os.path.join(root, "results"))], ensure_ascii=False)
    got = _child(root, _ROUNDS, language, os.path.join(root, "results"), keys)
    assert got["first"] > got["left"] > 0, got
    assert got["counts"]["twice"] == 0 and got["counts"]["taken"] == 1, got
    assert got["counts"]["files"] > 0 and got["same"], got


# One reader asked twice, as the Generate's *Only i+1* rounds ask it (the second round: the words left, in their own
# order), its two answers' row arrays and each parse of the last run's shown.json.gz kept; then the table's run
# signature changed under it and a third ask; then fresh readers asked each round alone.
_ROUNDS_ONCE = r"""
import json, os, sys
from app import analyzer, sentence_score, sentence_table
language, results, keys = sys.argv[1], sys.argv[2], [tuple(k) for k in json.loads(sys.argv[3])]
parsed, built = [0], []
read_shown, moment_arrays = analyzer._read_shown, sentence_score._moment_arrays
def counted_read(*args, **kwargs):
    parsed[0] += 1
    return read_shown(*args, **kwargs)
def kept_arrays(*args, **kwargs):
    arrays, files = moment_arrays(*args, **kwargs)
    built.append(dict(arrays))          # (the arrays themselves held: an id is never reused while they live)
    return arrays, files
analyzer._read_shown, sentence_score._moment_arrays = counted_read, kept_arrays
table = sentence_table.open_table(os.path.join(results, sentence_table.TABLE_FILE), language=language,
                                  engine=analyzer.engine_id(), run_signature=analyzer.read_run_stamp(results))
one = analyzer.ListSentences(language, 3, True, results_dir=results, table=table)     # (the Generate's own table)
first = one(keys, {k: at for at, k in enumerate(keys)})
left = [k for k in keys if first.get(k)]
if len(left) == len(keys):              # (every word has a clean line: every seventh left off, as a round would)
    left = [k for at, k in enumerate(keys) if at % 7]
order = {k: at for at, k in enumerate(left)}
second = one(left, order)
counts = {"parsed": parsed[0], "asks": len(built),
          "free_once": all(built[-1][name] is built[0][name] for name in ("own", "lemma", "young")),
          "placed_again": built[-1]["placed"] is not built[0]["placed"],
          "read_only": not any(built[-1][name].flags.writeable for name in ("own", "lemma", "young"))}
run = table.head.get("run_signature")
table.head["run_signature"] = "another run"
third = one(left, dict(order))          # (another run: its own shown.json.gz, none here — every text from the store)
table.head["run_signature"] = run
counts["parsed_another_run"] = parsed[0]
fresh_first = analyzer.ListSentences(language, 3, True, results_dir=results)(keys, {k: at for at, k in enumerate(keys)})
fresh = analyzer.ListSentences(language, 3, True, results_dir=results)(left, dict(order))
print(json.dumps({"counts": counts, "left": len(left), "first": len(first), "same_first": first == fresh_first,
                  "same": second == fresh, "same_third": third == second}))
"""


def test_only_i_plus_ones_second_round_parses_shown_once_and_builds_no_order_free_row_array_again(gen):
    # why: E-L2G 4, row 15 (+0.79 s at 2k, +0.60 s zh400 against today) — round 2 built again the rows' arrays that no
    # order changes (each row's lemma code, each co-word's row, its young weight) beside the order's own, and each
    # round gunzipped and parsed the last run's shown.json.gz. Built and parsed once; the order's arrays (`placed`)
    # still built at each order; another run's signature reads its own file; each round the answer a fresh reader gives
    language, root = gen
    results = os.path.join(root, "results")
    assert os.path.isfile(os.path.join(results, analyzer.SHOWN_FILE)), "the level-2 Generate keeps the shown lines"
    keys = json.dumps([list(k) for k in _columns(results)], ensure_ascii=False)
    got = _child(root, _ROUNDS_ONCE, language, results, keys)
    counts = got["counts"]
    assert got["first"] > got["left"] > 0 and counts["asks"] >= 2, got
    assert counts["parsed"] == 1, f"shown.json.gz parsed {counts['parsed']} times for one run's two rounds"
    assert counts["free_once"], "round 2 built the order-free row arrays again"
    assert counts["placed_again"] and counts["parsed_another_run"] == 2, counts
    assert counts["read_only"], "the arrays the memo's orders share are read-only"
    assert got["same_first"] and got["same"] and got["same_third"], got


# One reader asked for some of the list's words, its shown lines kept (results/shown.json.gz written: they differ from
# the Generate's), then asked for every word and kept again — in a copy of results/ (the fixture's stays as it is).
_KEPT_AGAIN = r"""
import json, os, shutil, sys
from app import analyzer, sentence_table
language, results, keys, mine = sys.argv[1], sys.argv[2], [tuple(k) for k in json.loads(sys.argv[3])], sys.argv[4]
shutil.copy2(os.path.join(results, analyzer.SHOWN_FILE), os.path.join(mine, analyzer.SHOWN_FILE))
table = sentence_table.open_table(os.path.join(results, sentence_table.TABLE_FILE), language=language,
                                  engine=analyzer.engine_id(), run_signature=analyzer.read_run_stamp(results))
run = table.head.get("run_signature")
one = analyzer.ListSentences(language, 3, False, results_dir=mine, table=table)
one(keys[: max(1, len(keys) // 3)], None)
one.keep()
some = analyzer._read_shown(mine, run)
one(keys, None)
one.keep()
every = analyzer._read_shown(mine, run)
print(json.dumps({"some": len(some), "every": len(every), "as_kept": every == one.kept}))
"""


def test_a_reader_asked_again_after_it_kept_its_lines_keeps_the_new_ones(gen, tmp_path):
    # why: E-L2G 4 — a reader parses shown.json.gz once for its run's calls; once its keep() has written the file, the
    # file is what the reader read no more: a later call reads it again, so its keep() compares against what is
    # written and writes the new lines (else it would see its old read, call them kept, and leave the file short)
    language, root = gen
    results = os.path.join(root, "results")
    keys = json.dumps([list(k) for k in _columns(results)], ensure_ascii=False)
    got = _child(root, _KEPT_AGAIN, language, results, keys, str(tmp_path))
    assert 0 < got["some"] < got["every"] and got["as_kept"], got


# Loaded first in the Generate's child: every progressive pass's `files` (each file as the pass reads it) held, and at
# the child's exit how many passes ran and how many `files` were built for them.
_PASSES = r"""
import atexit, json, os
from app import plan_rules
_pass, _files = plan_rules.progressive_pass, []


def _counted(files, *args, **kwargs):
    _files.append(files)                # (held: an id is never reused while it lives)
    return _pass(files, *args, **kwargs)


def _said():
    with open(os.environ["E_L2G_PASSES"], "w") as f:
        json.dump({"passes": len(_files), "built": len({id(files) for files in _files})}, f)


plan_rules.progressive_pass = _counted
atexit.register(_said)
"""


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_only_i_plus_ones_rounds_read_each_file_for_the_progressive_pass_once(language, tmp_path):
    # why: E-L2G 4, row 15 — each round of *Only i+1* at level 2 ran the progressive pass again over every file, and
    # built again each file as the pass reads it (its words not known before any file, their counts: the same at every
    # round — only the words listed change). Profiled at 2,000 files: 1.07 s of the 2 rounds' 2.15 s. Built once for
    # the rounds; the pass itself still runs at each (the words listed are the round's); the list is the reader's
    hook = tmp_path / "hook"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text(_PASSES, encoding="utf-8")
    counted = tmp_path / "passes.json"
    env = dict(LEVEL_2, PYTHONPATH=str(hook) + os.pathsep + cases.REPO, E_L2G_PASSES=str(counted))
    root = str(tmp_path / "lib")
    cases.build(root, f"rp2-{language}")
    cases.generate(root, f"rp2-{language}", extra_env=env, extra_args=["--only-i-plus-one"])
    with open(counted, encoding="utf-8") as f:
        got = json.load(f)
    assert got["passes"] >= 2, f"no second round on this library: {got}"
    assert got["built"] == 1, f"{got['built']} builds of every file's pass input for {got['passes']} rounds"
    listed = _columns(os.path.join(root, "results"))
    assert listed and all(cols and cols[0] for cols in listed.values()), "every word left on shows a sentence"


# Loaded first in the redraw's child: at its exit, whether a Japanese tagger was ever loaded (fugashi is imported only
# to make one: `JapaneseTokenizer`).
_TAGGER_LOADED = r"""
import atexit, json, os, sys


def _said():
    with open(os.environ["E_L2G_LOADED"], "w") as f:
        json.dump({"fugashi": "fugashi" in sys.modules}, f)


atexit.register(_said)
"""


def _with_verses(folder):
    """RP-2's Japanese library with an episode whose captions read verses aloud, each led by its number (Test
    Resources' verses_sample.srt: a book's text file loses them before the token store), among the now shows,
    Generated at level 2."""
    root = str(folder)
    cases.build(root, "rp2-ja")
    with open(os.path.join(cases.RES, "ja", "verses_sample.srt"), encoding="utf-8") as f:
        text = f.read()
    folder = os.path.join(root, "data", "ja", cases.TIER_FOLDER["now"])
    path = os.path.join(folder, "verses_episode.srt")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.utime(path, (cases.MTIME, cases.MTIME))
    manifest = os.path.join(root, "User Files", "ja", "master_manifest.json")
    with open(manifest, encoding="utf-8") as f:
        plan = json.load(f)
    plan["schedule"][cases.PHASE["now"]].append({"physical_path": f"{cases.TIER_FOLDER['now']}/verses_episode.srt",
                                                 "title": "verses_episode.srt", "origin_source": "Manual Import"})
    with open(manifest, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    os.utime(manifest, (cases.MTIME, cases.MTIME))
    cases.generate(root, "rp2-ja", extra_env=LEVEL_2)
    return root


def test_a_redraw_whose_lines_are_all_kept_loads_no_tagger_and_shows_the_verse_lines_as_the_generate(tmp_path):
    # why: E-L2G, row 11 — the redraw's child loaded a Japanese tagger (0.09 s) only to strip a verse number off a
    # line led by digits, a line the Generate had already shown stripped. Its shown form is kept with its text: the
    # redraw of the Generate's own plan, nothing moved, loads none and shows every line as the Generate did
    root = _with_verses(tmp_path / "lib")
    results = os.path.join(root, "results")
    listed = _columns(results)
    kept = analyzer._read_shown(results, analyzer.read_run_stamp(results))
    led = {text for text in kept.values() if analyzer._LEADING_DIGITS_RE.match(text)}
    shown = {v for cols in listed.values() for v in cols[0::2] if v}
    assert any(text not in shown and text.lstrip("0123456789") in shown for text in led), (
        "a verse line is shown, its number cut", sorted(led)[:5])
    os.remove(os.path.join(results, analyzer.REDRAW_FILE))      # (not today's: the keeper redraws it)
    hook = tmp_path / "hook"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text(_TAGGER_LOADED, encoding="utf-8")
    env = _env(root)
    env["PYTHONPATH"] = str(hook) + os.pathsep + env.get("PYTHONPATH", "")
    env["E_L2G_LOADED"] = str(tmp_path / "loaded.json")
    p = subprocess.run([sys.executable, os.path.join(cases.REPO, "app", "analyzer.py"), "--language=ja", "--static",
                        "--no-open", "--from-plan"], cwd=cases.REPO, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert p.returncode == 0 and "Redrew the journey" in p.stdout, (p.stdout + p.stderr)[-1500:]
    with open(env["E_L2G_LOADED"], encoding="utf-8") as f:
        assert json.load(f) == {"fugashi": False}, "a redraw of kept lines loads no tagger"
    assert _columns(results) == listed, "every line shown as the Generate showed it"
