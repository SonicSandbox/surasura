"""E-L2G: the level-2 Generate's gaps closed before the flip (SPEC § 6; inert at `plan_rules.SENTENCE_TABLE = 0`).

On RP-2's real Japanese and Chinese libraries (tests/plan_file_cases.py), each Generated at level 2 in a child process
as the dashboard runs it. What these prove:
  - **the redraw's word_stats.json is written whole or not at all** (E-REDRAW's crash drill: a redraw killed while it
    wrote the file left it empty, and the next look ran a whole Generate): a redraw that dies part-way through that
    write leaves the last one as it was, and the next look redraws.
  - **a list call reads the lines' text without their tokens** (`token_index.Store.file_texts`; E-L2G: decoding each
    shown line's whole file was 0.70 of the level-2 pick's 0.78 s at 2k): no file's tokens decoded, the same columns —
    and, on any doubt, the full decode, the same columns again; the texts are `file_tokens`' over every file of the
    store and over made lines (quotes, backslashes, the cut inside a line, an empty token list, control characters).
"""
import json
import os
import subprocess
import sys

import pytest

from app import token_index
from tests import plan_file_cases as cases
from tests.test_e_redraw import _columns, _env, _generated, _move, _redraw


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

# Loaded first in the child (a sitecustomize on its path): the first write to word_stats.json — the file itself or a
# temp beside it — writes half its text and the process dies there, as a crash would.
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
    if "w" in mode and os.path.basename(str(file)).startswith("word_stats.json"):
        return _Dying(f)
    return f


builtins.open = _opened
"""


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
analyzer._read_shown = lambda results_dir, run_signature: {}
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
    blob, lines = _blob(_MADE)
    assert token_index._decode_texts(blob, token_index._encode_tokens([1] * (len(_MADE) - 1))) is None
    assert token_index._decode_texts(blob, None) is None, "no `lines` column: read in full"
    assert token_index._decode_texts(blob[:-3], lines) is None, "a damaged blob: read in full"
    assert token_index._decode_texts(token_index._encode_tokens([]), None) is None, "no line: the store's [] in full"
    assert token_index._decode_texts(*_blob([[None, []]])) is None, "a line held badly: read in full"
