"""DSA-WALK: the token store keeps each file's tokens once, as int32 ids into one vocabulary (G1's layout), and a
reconcile with nothing changed reads only the small columns (G2).

Real Japanese and Chinese files from tests/Test Resources, copied into a temp folder (nested, with an empty file and
a CRLF one). What these prove:
  - **stored once:** the `tokens` JSON column is gone; each distinct token (lemma, reading, surface, orth) is one row
    of `types`, and each file is `ids` (its sentences' starts + type ids) and `texts` — so a Generate's walk can look
    a token's state up by its id (session 2) instead of decoding every token's JSON;
  - **every reader reads what it read before:** `file_tokens`, `file_texts`, `some_texts`, `file_words` and the kept
    text give exactly the tokenizer's sentences (as the JSON blob gave them), with no token JSON decoded;
  - **a reconcile with nothing changed reads no blob:** its first look is one covering index (path, mtime, size,
    total, counted, aside); a file's counts are read only when it changed, left or moved class (20k: 13 s cold → the
    index's pages);
  - **an old store is never read as this one:** a reader opening a store of another schema gets None (the indexer
    builds it again).
"""
import json
import os
import shutil
import sqlite3
import zlib

import pytest

from app import token_index as ti

_JA_FILES = ("placed_episode.srt", "library_episode.ass", "phrases_sample.srt", "rare_compound_episode.ja.srt",
             "context_test.txt")
_ZH_FILES = ("night_market.srt", "chinese_text_1.txt", "mixed_script_transcript.txt", "context_test.txt")


def _library(tmp_path, resources, names):
    """The real files in a nested folder, plus an empty file and one with CRLF line ends (the edge cases)."""
    root = tmp_path / "lib"
    paths = []
    for at, name in enumerate(names):
        folder = root / ("show" if at % 2 else "books") / f"part{at}"
        folder.mkdir(parents=True)
        shutil.copy(os.path.join(resources, name), folder / name)
        paths.append(str(folder / name))
    empty = root / "empty.txt"
    empty.write_text("", encoding="utf-8")
    first = open(paths[-1], encoding="utf-8").read()
    crlf = root / "crlf.txt"
    crlf.write_bytes(first.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))
    return paths + [str(empty), str(crlf)]


def _made(tmp_path, language, resources, names):
    paths = _library(tmp_path, resources, names)
    store = ti.open_store(language, path=str(tmp_path / "store.db"))
    store.reconcile(paths, ti.make_tokenizer(language))
    return store, paths


def _truth(language, path):
    """The sentences as the tokenizer gives them, as the store's JSON gave them back (lists, not tuples)."""
    return json.loads(json.dumps(ti.make_tokenizer(language)(path)["sentences"], ensure_ascii=False))


@pytest.fixture(params=["ja", "zh"])
def made(request, tmp_path, ja_resources_dir, zh_resources_dir):
    language = request.param
    if language == "ja":
        store, paths = _made(tmp_path, "ja", ja_resources_dir, _JA_FILES)
    else:
        store, paths = _made(tmp_path, "zh", zh_resources_dir, _ZH_FILES)
    store.switches = (False, False, False)     # the tokens as stored: no name table joins them (test_names' work)
    yield language, store, paths
    store.close()


def test_each_files_tokens_are_kept_once_as_ids_into_one_vocabulary(made):
    # why: G1 — a Generate decoded every token's JSON of every file at every run (2k: 4.07 M tokens, 76 MB, 2.46 s
    # before a single word was looked at); the standard layout keeps each distinct token once and each file as ids,
    # so a token's state is an array lookup. Red on the JSON layout: no `types`, no `ids`.
    language, store, paths = made
    columns = [r[1] for r in store.conn.execute("PRAGMA table_info(files)")]
    assert "tokens" not in columns and {"ids", "texts"} <= set(columns), columns
    assert columns.index("ids") == len(columns) - 1, "the biggest column last: every small one read before it"
    rows = store.conn.execute("SELECT id, lemma, reading, surface, orth FROM types").fetchall()
    assert len({r[1:] for r in rows}) == len(rows), "each distinct token once"
    met = {tuple(token) for p in paths for _text, tokens in _truth(language, p) for token in tokens}
    assert {r[1:] for r in rows} == met, "the vocabulary is exactly the library's tokens"
    by_id = {r[0]: list(r[1:]) for r in rows}
    for p in paths:
        blob, texts = store.conn.execute("SELECT ids, texts FROM files WHERE path=?", (ti._norm(p),)).fetchone()
        starts, ids = ti._read_ids(blob)
        truth = _truth(language, p)
        assert len(starts) == len(truth) + 1 and starts[0] == 0 and starts[-1] == len(ids)
        assert [[by_id[i] for i in ids[starts[n]:starts[n + 1]]] for n in range(len(truth))] == \
            [tokens for _text, tokens in truth], p
        assert ti._read_texts(texts) == [text for text, _tokens in truth], p


def test_every_reader_reads_the_tokenizers_sentences_with_no_token_json(made, monkeypatch):
    # why: every caller (anki_match, arrivals, the sentence dictionary, Connect, the pick) reads through the Store, so
    # the layout moves under them unseen: the same sentences, texts, lines asked alone and kept text as the JSON blob
    # gave — and none of them decodes a token's JSON any more (red on the JSON layout: `_decode_tokens` a read)
    language, store, paths = made
    calls = []
    real = ti._decode_tokens
    monkeypatch.setattr(ti, "_decode_tokens", lambda blob: calls.append(1) or real(blob))
    fresh = ti.open_store(language, path=store.path)
    fresh.switches = (False, False, False)
    try:
        for p in paths:
            truth = _truth(language, p)
            assert fresh.file_tokens(p) == truth, p
            assert fresh.file_texts(p) == [t for t, _ in truth], p
            sentences, _words = fresh.file_words(p)
            assert sentences == truth, p
            asked = [n for n in range(0, len(truth) + 2, 2)]
            assert fresh.some_texts({p: asked})[p] == {n: truth[n][0] for n in asked if n < len(truth)}, p
        assert fresh.file_tokens(os.path.join(os.path.dirname(paths[0]), "no such file.srt")) == []
        assert fresh.some_texts({"no such file.srt": [0]}) == {"no such file.srt": {}}
        assert calls == [], "a token's JSON decoded"
        # a read hands out its own lists: a caller that joins tokens in place (names.apply_spans) changes nobody's
        first = fresh.file_tokens(paths[0])
        first[0][1][0:2] = [["x", "x", "x", "x"]]
        assert fresh.file_tokens(paths[0]) == _truth(language, paths[0])
    finally:
        fresh.close()


def test_a_files_kept_text_is_rebuilt_from_its_texts(made):
    # why: a counted file gone from the disk keeps its text rebuilt from its cached sentences (`_text_of`): from the
    # `texts` column alone now, one line a sentence, as before
    language, store, paths = made
    key = ti._norm(paths[0])
    row = {"mtime": 1.0, "size": 2}
    text, facts, mtime, size = store._text_of(store.conn.cursor(), key, row, None, None)
    assert text == "\n".join(t for t, _ in _truth(language, paths[0])) and facts["rebuilt"] and (mtime, size) == (1.0, 2)


def test_a_reconcile_with_nothing_changed_reads_only_the_covering_index(made):
    # why: G2 — reconcile's first look read every row's counts and bound to reach the small flags behind them (20k:
    # 13.08 s cold, 724 MB); the standard is the small columns in an index of their own, the blobs read by path only
    # for a file that changed, left or moved class. Red on the old query: it names counts and bound over every row.
    language, store, paths = made
    seen = []
    store.conn.set_trace_callback(seen.append)
    try:
        store.reconcile(paths, ti.make_tokenizer(language))
    finally:
        store.conn.set_trace_callback(None)
    scans = [s for s in seen if s.lstrip().upper().startswith("SELECT") and " FROM FILES" in s.upper()
             and "WHERE" not in s.upper()]
    assert scans, seen
    for statement in scans:
        assert not any(blob in statement for blob in ("counts", "bound", "names", "texts", "ids", "words")), statement
        plan = " ".join(str(r[-1]) for r in store.conn.execute("EXPLAIN QUERY PLAN " + statement))
        assert "COVERING INDEX" in plan.upper(), (statement, plan)
    blobs = [s for s in seen if "counts" in s and "FROM files" in s]
    assert blobs == [], "nothing changed: no file's counts read"


def test_a_changed_file_still_moves_its_old_counts_out(made, tmp_path):
    # why: the blobs are read by path now: a changed file's stale counts must still come out of the aggregate, a
    # leaving file's too, and a file moving to kept its counts — the sums as a full build gives them
    language, store, paths = made
    tok = ti.make_tokenizer(language)
    changed = paths[1]
    with open(changed, "a", encoding="utf-8") as f:
        f.write("\n" + open(paths[0], encoding="utf-8").read())
    os.utime(changed, (os.stat(changed).st_mtime + 10,) * 2)
    store.reconcile(paths[1:-1], tok, kept=[paths[-1]])        # paths[0] leaves, the last moves to kept
    whole = ti.open_store(language, path=str(tmp_path / "whole.db"))
    try:
        whole.reconcile(paths[1:-1], tok, kept=[paths[-1]])
        agg = "SELECT lemma, reading, count FROM aggregate ORDER BY lemma, reading"
        assert store.conn.execute(agg).fetchall() == whole.conn.execute(agg).fetchall()
        assert store.total_tokens() == whole.total_tokens()
        bound = "SELECT lemma, reading, count FROM bound ORDER BY lemma, reading"
        assert store.conn.execute(bound).fetchall() == whole.conn.execute(bound).fetchall()
    finally:
        whole.close()


def test_a_store_of_another_schema_is_not_read_as_this_one(made):
    # why: the JSON layout and the id layout can't be read as each other: a reader opening a store the indexer hasn't
    # built again yet (3.0.18's, v29) reads none — the callers' "no store" — never a crash or a wrong token
    language, store, paths = made
    path = store.path
    store.close()
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {ti.SCHEMA_VERSION - 1}")
    conn.commit()
    conn.close()
    assert ti.open_reader(language, path=path) is None
    again = ti.open_store(language, path=path)              # the writer builds it again
    try:
        assert again.conn.execute("PRAGMA user_version").fetchone()[0] == ti.SCHEMA_VERSION
        assert again.file_count() == 0
    finally:
        again.close()


def test_the_ids_and_texts_codecs_hold_every_edge():
    # why: the codecs alone — an empty file, an empty sentence, a sentence with no tokens, text with every hazard the
    # JSON layout had (quotes, backslashes, CRLF, control characters, the old cut's own characters) and both scripts
    sentences = [["", []], ['彼は「"冒険"だ」\\と言った。\r\n', [["彼", "カレ", "彼", "彼"], ["は", "ハ", "は", "は"]]],
                 ["]], [\"x", []], ["我们需要去寻找新的冒险。", [["我们", "", "我们", "我们"], ["冒险", "", "冒险", "冒险"]]],
                 ["\x00\x1f", [["\x00", "", "\x00", "\x00"]]]]
    types = {}
    blob = ti._encode_ids(sentences, lambda t: types.setdefault(tuple(t), len(types)))
    starts, ids = ti._read_ids(blob)
    back = {i: list(t) for t, i in types.items()}
    assert [[back[i] for i in ids[starts[n]:starts[n + 1]]] for n in range(len(sentences))] == [s[1] for s in sentences]
    assert ti._read_texts(ti._encode_texts(sentences)) == [s[0] for s in sentences]
    assert ti._read_texts(ti._encode_texts(sentences), [4, 0, 9]) == {4: "\x00\x1f", 0: ""}
    assert ti._read_ids(ti._encode_ids([], None)) == ([0], []) and ti._read_texts(ti._encode_texts([])) == []
    assert ti._read_texts(zlib.compress(b"broken")) is None and ti._read_ids(b"not zlib") is None


def test_the_walks_read_on_ids_joins_the_names_as_file_tokens_joins_them(tmp_path):
    # why: the name tables join a library's names at read (`Store._named`: メロンベンチ, 焔魄陣 one word in every file);
    # the walk reads ids, so each join is a splice of the ids — every sentence of every file must hold the very
    # tokens `file_tokens` gives (the joined ones too), and the sentences joined must be the ones it joins
    from tests.test_names import HOMURA, JIN, PARK, SHOP, STATION, _library as names_library
    store, paths = names_library(tmp_path / "lib", {"station.txt": STATION, "shop.txt": SHOP, "park.txt": PARK,
                                                    "a.txt": HOMURA, "b.txt": JIN})
    try:
        assert store.names_tables(), "the made-up library has name tables"
        extra = {}
        base = 1 << 30                          # the run's own numbers, past any the store gives

        def intern(token):
            return extra.setdefault(tuple(token), base + len(extra))
        joined_any = False
        for p in paths:
            starts, ids, joined, texts, _words = store.file_ids(p, intern)
            back = {i: list(t) for t, i in extra.items()}
            types = store._tokens_of([i for i in ids if i < base])
            rebuilt = [[text, [back[i] if i >= base else list(types[i]) for i in ids[starts[n]:starts[n + 1]]]]
                       for n, text in enumerate(ti._read_texts(texts))]
            assert rebuilt == store.file_tokens(p), p
            truth = set()
            store._named(store._stored(*store.conn.execute("SELECT texts, ids FROM files WHERE path=?",
                                                          (ti._norm(p),)).fetchone()),
                         store.conn.execute("SELECT names FROM files WHERE path=?", (ti._norm(p),)).fetchone()[0], truth)
            assert joined == truth, p
            joined_any = joined_any or bool(joined)
        assert joined_any, "some sentence was joined"
        assert store.file_ids(str(tmp_path / "no such file.txt"), intern) is None
    finally:
        store.close()


def test_a_splice_moves_every_later_sentences_start():
    # why: a join of two tokens, one token made a name, and a term put where every piece was dropped (a == b) each
    # move the starts after them — by one pass, never a wrong sentence's tokens
    from array import array
    starts, ids = array("i", [0, 3, 3, 6, 8]), array("i", [10, 11, 12, 20, 21, 22, 30, 31])
    joins = {0: [(0, 2, ["平野"])], 2: [(1, 2, ["名"]), (3, 3, ["末"])], 3: [(0, 2, ["全"])]}
    made = {"平野": 90, "名": 91, "末": 92, "全": 93}
    new_starts, new_ids = ti._spliced(starts, ids, joins, lambda t: made[t[0]])
    assert list(new_starts) == [0, 2, 2, 6, 7]
    assert list(new_ids) == [90, 12, 20, 91, 22, 92, 93]
