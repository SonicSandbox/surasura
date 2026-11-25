"""E-PICK: the level-2 pick step faster, with the same answers (SPEC § 6; the rows against each one's fastest-ever).

On RP-2's real Japanese and Chinese libraries (tests/plan_file_cases.py), each Generated at level 2 in a child process
(test_e_l2g's `gen`). What these prove — every piece gives what it gave before, only sooner:
  - **a file's lines read alone are its texts** (`Store.some_texts`): the walk read each shown line's whole file
    (158,000 texts decoded at 2k for its 1,461 lines); now only the lines it took are decoded — over every file of a
    real store the same texts, none in doubt; and every text a wrong cut could hide behind is read in full.
  - **a line whose text is gone is walked again as before**: the walk takes a line before reading its text, so a row
    with a line that has none is walked again reading as it goes — the next line in, never a line short.
  - **the table's co-words regrouped without one sort of all of them** (`sentence_table._regroup`; 1.69 M ids at a
    400-file Chinese library): the same ids, the same starts, the same types, as the one sort gave.
  - ***Only i+1*'s rounds cost what the cost worked out whole gives**: the order-free parts kept from round 1 (the
    co-words, the length rule, how a line is heard), round 2 the same floats bit for bit — with and without a young
    word weighed.
The list's own sentences at level 2 stay pinned byte for byte by test_plan_file's hashes.
"""
import json
import os
import zlib

import numpy as np
import pytest

from app import sentence_score, sentence_table, token_index
from tests.test_e_l2g import _MADE, _blob, _child, gen  # noqa: F401  (gen: the module's fixture)
from tests.test_e_redraw import _columns


# ---------------------------------------------------------------------------------------------------- #
# A file's lines read alone
# ---------------------------------------------------------------------------------------------------- #
_SOME_TEXTS = r"""
import json, sys
from app import token_index
st = token_index.open_reader(sys.argv[1])
paths = [r[0] for r in st.conn.execute("SELECT path FROM files")]
same = doubt = past = 0
for at in range(0, len(paths), 40):
    batch = paths[at:at + 40]
    whole = {p: st.file_texts(p) for p in batch}
    asked = {p: list(range(len(t) + 2)) for p, t in whole.items() if t is not None}
    got = st.some_texts(asked)
    for p, texts in whole.items():
        if texts is None:
            continue
        if got[p] is None:
            doubt += 1
        elif got[p] == dict(enumerate(texts)):
            same += 1
            past += len(texts) + 2 - len(got[p])
print(json.dumps({"files": len(paths), "same": same, "doubt": doubt, "past": past,
                  "gone": st.some_texts({"no such file.srt": [0]})}))
"""


def test_every_files_lines_read_alone_are_its_texts(gen):
    # why: E-PICK F1 — the walk reads only the lines it took (`some_texts`), never a whole file's texts; over every
    # file of a real store each line read alone is the whole read's, a number past a file's end is left out (the
    # walk's "no text"), a file the store doesn't hold is {} — and none is in doubt on real data (each would cost a
    # whole read again)
    language, root = gen
    got = _child(root, _SOME_TEXTS, language)
    assert got["files"] > 0 and got["same"] == got["files"] and got["doubt"] == 0, got
    assert got["past"] == 2 * got["files"] and got["gone"] == {"no such file.srt": {}}, got


@pytest.mark.parametrize("text", [", 続きは明日。", "] これで終わり", ", ", "]"])
def test_a_text_starting_where_a_wrong_cut_would_end_is_read_in_full(text):
    # why: a cut too many (a string ending in the cut's own characters) is always followed by ", " or "]"; the pieces
    # are not read one by one, so a file holding those bytes after a cut is read in full instead — the same texts
    sentences = _MADE[:3] + [(text, [["続き", "ツヅキ", "続き", "続き"]])] + _MADE[3:]
    blob, lines = _blob(sentences)
    assert token_index._decode_some(blob, lines, range(len(sentences))) is None
    assert token_index._decode_texts(blob, lines) == [s[0] for s in sentences], "the full read: the truth"


def test_made_lines_read_alone_are_their_texts_and_a_wrong_cut_is_never_read():
    # why: the hazards test_e_l2g reads in full (quotes, backslashes, the cut inside a line, CRLF, control
    # characters, an empty text) read alone give the texts; every cut too many — even one the count agrees with —
    # gives None, never a shifted text
    truth = [s[0] for s in _MADE]
    blob, lines = _blob(_MADE)
    assert token_index._decode_some(blob, lines, range(len(_MADE))) == dict(enumerate(truth))
    assert token_index._decode_some(blob, lines, [5, 2, 99, -1]) == {5: truth[5], 2: truth[2]}
    assert token_index._decode_some(blob, lines, []) == {}
    text_ends_in_cut = ("配列の終わりは ]], [", [["配列", "ハイレツ", "配列", "配列"]])
    token_ends_in_cut = ("記号だ", [["]], [", "", "]], [", "]], ["], ["だ", "ダ", "だ", "だ"]])
    for wrong in (text_ends_in_cut, token_ends_in_cut):
        made = _MADE[:2] + [wrong] + _MADE[2:]
        assert token_index._decode_some(*_blob(made), [0, 1]) is None, "a wrong cut after the asked lines too"
        assert token_index._decode_some(*_blob([wrong]), [0]) is None
    blob = token_index._encode_tokens([token_ends_in_cut])
    pieces = zlib.decompress(blob).decode("utf-8")[3:].split(token_index._CUT)
    agreeing = token_index._encode_tokens([1] * len(pieces))
    assert len(pieces) > 1 and token_index._decode_some(blob, agreeing, [0]) is None, "a count that agrees"
    blob, lines = _blob(_MADE)
    assert token_index._decode_some(blob, token_index._encode_tokens([1] * (len(_MADE) - 1)), [0]) is None
    assert token_index._decode_some(blob, None, [0]) is None, "no `lines` column: read in full"
    assert token_index._decode_some(blob[:-3], lines, [0]) is None, "a damaged blob: read in full"
    assert token_index._decode_some(*_blob([[None, []]]), [0]) is None, "a line held badly: read in full"


# ---------------------------------------------------------------------------------------------------- #
# A line whose text is gone
# ---------------------------------------------------------------------------------------------------- #
_GONE = r"""
import json, os, sys
from app import analyzer, sentence_score, sentence_table, token_index
language, results, keys, gone = sys.argv[1], sys.argv[2], [tuple(k) for k in json.loads(sys.argv[3])], sys.argv[4]
analyzer._read_shown = lambda results_dir, run_signature, forms=None, silent=None: {}
some, whole = token_index.Store.some_texts, token_index.Store.file_texts
def is_gone(p):
    return os.path.normcase(p).endswith(os.path.normcase(gone))
def without(self, asked):                       # (the file's row gone from the store: neither read finds it)
    return {p: ({} if is_gone(p) else v) for p, v in some(self, asked).items()}
def as_read(*args, **kwargs):
    return analyzer.ListSentences(language, 3, False, results_dir=results)(keys, None)
token_index.Store.some_texts = without
token_index.Store.file_texts = lambda self, p: [] if is_gone(p) else whole(self, p)
lazy = as_read()
token_index.Store.some_texts = None             # (no reading alone: every file read whole as it goes)
eager = as_read()
print(json.dumps({"lazy": [[list(k), v] for k, v in lazy.items()], "eager": [[list(k), v] for k, v in eager.items()]},
                 ensure_ascii=False))
"""


def test_a_line_whose_text_is_gone_is_walked_again_as_before(gen):
    # why: the walk takes a line before its text is read; a file whose texts are gone since (its row left the store)
    # gives those lines none, and their rows are walked again reading as they go — the next lines in, the same answer
    # as a walk that reads each file as it meets it, never a row a line short or a line with no text
    language, root = gen
    results = os.path.join(root, "results")
    listed = _columns(results)
    shown = {}
    for cols in listed.values():
        for src in cols[1::2]:
            if src:
                shown[src] = shown.get(src, 0) + 1
    gone = max(shown, key=lambda s: (shown[s], s))          # the file the most rows showed a line of
    keys = json.dumps([list(k) for k in listed], ensure_ascii=False)
    got = _child(root, _GONE, language, results, keys, gone.replace("/", os.sep))
    lazy, eager = dict((tuple(k), v) for k, v in got["lazy"]), dict((tuple(k), v) for k, v in got["eager"])
    assert lazy == eager
    assert all(src != gone for cols in lazy.values() for src in cols[1::2]), "no line of the file whose text is gone"
    assert all(text for cols in lazy.values() for text in cols[0::2] if cols), "every line taken has its text"
    lost = [k for k in listed if gone in listed[k][1::2]]
    assert lost and all(lazy[k] != listed[k] for k in lost), "each row that showed a line of it walked again"


# ---------------------------------------------------------------------------------------------------- #
# The table's co-words regrouped
# ---------------------------------------------------------------------------------------------------- #
def _regroup_by_one_sort(line, ids, order, n_lines):
    """The regroup as it was before E-PICK: one sort of (the line's place in `order`, its id) over every id."""
    pos = np.full(n_lines, -1, np.int64)
    pos[order] = np.arange(len(order), dtype=np.int64)
    at = pos[line] if len(line) else np.zeros(0, np.int64)
    good = (ids >= 0) & (at >= 0)
    at, ids = at[good], ids[good]
    counts = np.bincount(at, minlength=len(order))
    size = int(ids.max()) + 1 if len(ids) else 1
    at *= size
    at += ids
    at.sort()
    return (at % size).astype(np.int32), np.concatenate(([0], np.cumsum(counts, dtype=np.int64)))


def _case(rng, n_lines, most, share, drop):
    per = rng.integers(0, most + 1, n_lines)
    line = np.repeat(np.arange(n_lines, dtype=np.int32), per)
    ids = rng.integers(0, max(2, n_lines // 3), len(line)).astype(np.int32)
    ids[rng.random(len(line)) < drop] = -1                  # (a co-word known from the start: no id)
    order = rng.permutation(n_lines)[:int(n_lines * share)]
    return line, ids, order, n_lines


@pytest.mark.parametrize("seed", range(6))
def test_the_co_words_regrouped_are_what_one_sort_of_them_all_gave(seed):
    # why: E-PICK F2 — `_regroup` sorted every co-word of the table at once (1.69 M at a 400-file Chinese library:
    # 0.1 s of the Generate's end); each line's ids sorted where they lie, then the lines gathered in order, give the
    # same arrays — the lines taken in any order, some never, ids repeated in a line, -1 left out, lines with none
    rng = np.random.default_rng(seed)
    for n_lines, most, share, drop in ((2000, 12, 0.7, 0.1), (300, 30, 1.0, 0.0), (500, 3, 0.2, 0.5),
                                       (1, 5, 1.0, 0.0), (50, 0, 1.0, 0.0), (40, 6, 1.0, 1.0)):
        case = _case(rng, n_lines, most, share, drop)
        want, got = _regroup_by_one_sort(*case), sentence_table._regroup(*case)
        for w, g in zip(want, got):
            assert w.dtype == g.dtype and np.array_equal(w, g), (n_lines, most, share, drop)


def test_the_co_words_regrouped_with_nothing_to_regroup_are_empty():
    # why: an empty library, a table whose lines were all dropped, no line taken: the same empty arrays as before
    empty = np.zeros(0, np.int32)
    for case in ((empty, empty, np.zeros(0, np.int64), 0), (empty, empty, np.zeros(0, np.int64), 5),
                 (np.zeros(3, np.int32), np.array([4, 2, 9], np.int32), np.zeros(0, np.int64), 1)):
        want, got = _regroup_by_one_sort(*case), sentence_table._regroup(*case)
        for w, g in zip(want, got):
            assert w.dtype == g.dtype and np.array_equal(w, g), case


# ---------------------------------------------------------------------------------------------------- #
# Only i+1's rounds: the cost
# ---------------------------------------------------------------------------------------------------- #
_ROUNDS_COST = r"""
import json, os, sys
import numpy as np
from app import analyzer, sentence_score as S, sentence_table
from app.path_utils import get_data_path
language, results = sys.argv[1], sys.argv[2]
tab = sentence_table.open_table(os.path.join(results, sentence_table.TABLE_FILE), language=language)
keys = [tuple(k) for k in tab.head["keys"]]
root = get_data_path(language)
out = {}
for name, young in (("plain", None), ("young", {keys[i][0]: 0.5 + 0.1 * (i % 5) for i in range(1, len(keys), 3)})):
    moment = S.Moment(young=young, root=root)
    want = sorted(set(tab.rows().values()))
    columns = S._take(tab, want)
    srcs = np.unique(columns["src"]).tolist()
    memo, kept, same, reused = {}, {}, True, True
    orders = [None, {k: at for at, k in enumerate(reversed(keys))}, {k: at for at, k in enumerate(keys[1::2])}]
    for order in orders:
        S._kept(memo, tab, moment, order, root)
        arrays, _files = S._moment_arrays(tab, moment, order, root, srcs, memo)
        got = S.cost(columns, arrays, 10, 50, kept=kept)
        fresh_arrays, _files = S._moment_arrays(tab, moment, order, root, srcs)
        whole = S.cost(columns, fresh_arrays, 10, 50)
        same = same and all(g.dtype == w.dtype and np.array_equal(g.view(np.uint8), w.view(np.uint8))
                            for g, w in zip(got, whole))
        if order is not None:
            reused = reused and kept["free"] is first
        first = kept["free"]
    out[name] = {"same": same, "reused": reused, "young": bool((got[3] > 0).any()), "lines": len(got[0])}
print(json.dumps(out))
"""


def test_only_i_plus_ones_rounds_cost_what_the_cost_worked_out_whole_gives(gen):
    # why: E-PICK F3 — *Only i+1* asked the cost again whole at each round (103 / 107 / 118 ms at zh400): the parts no
    # order changes are kept from the first round and read back, and each round's arrays are the whole cost's bit for
    # bit (the same floats summed in the same order) — with no young word and with young words weighed
    language, root = gen
    got = _child(root, _ROUNDS_COST, language, os.path.join(root, "results"))
    for name in ("plain", "young"):
        assert got[name]["lines"] > 0 and got[name]["same"] and got[name]["reused"], got
    assert got["young"]["young"], "young words weighed lower some line"


def test_the_cost_kept_for_other_columns_or_another_length_is_worked_out_again():
    # why: what the cost keeps is for its columns, Length and rates alone: another Length (or columns) never reads
    # the kept parts — a stale length rule would cost every line wrongly
    rng = np.random.default_rng(3)
    n, rows = 400, 30
    ncow = rng.integers(0, 6, n)
    columns = {"row": np.sort(rng.integers(0, rows, n)).astype(np.int64), "src": rng.integers(0, 9, n),
               "chars": rng.integers(3, 90, n), "flags": np.zeros(n, np.int64), "besides": rng.integers(0, 6, n),
               "start": rng.integers(0, 40, n), "cow": rng.integers(0, 50, int(ncow.sum())), "ncow": ncow,
               "crowd": rng.integers(0, rows, 20), "ncrowd": np.bincount(rng.integers(0, n, 20), minlength=n)}
    moment = {"placed": rng.permutation(rows + 1), "placed_now": rng.permutation(rows + 1),
              "known_at": rng.integers(0, rows, 50), "own": rng.integers(-1, rows, 50),
              "lemma": rng.integers(0, rows, rows + 1), "young": np.zeros(50), "ctx": rng.random(9),
              "show_only": rng.random(9) < 0.3, "hear": rng.integers(0, 3, 9).astype(np.int8)}
    kept = {}
    sentence_score.cost(columns, moment, 10, 50, kept=kept)
    for low, high in ((10, 50), (5, 30)):
        got, whole = sentence_score.cost(columns, moment, low, high, kept=kept), sentence_score.cost(columns, moment,
                                                                                                     low, high)
        assert all(np.array_equal(g, w) for g, w in zip(got, whole)), (low, high)
    other = dict(columns, chars=columns["chars"] + 7)
    got, whole = sentence_score.cost(other, moment, 5, 30, kept=kept), sentence_score.cost(other, moment, 5, 30)
    assert all(np.array_equal(g, w) for g, w in zip(got, whole)), "other columns"
