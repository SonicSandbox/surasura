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
    builds it again);
  - **the walk on ids** (session 2, `token_index.Walk`): a file's totals, known count, multiset (in the order first
    met) and the tokens with something to do are what walking its tokens one by one gives — song lines with no words,
    the name joins' tokens, a file read as tokens — and a Generate builds the tokens of only the sentences that hold
    something to do (RP-2, ja + zh: every sentence of every file before).
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import zlib
from collections import Counter

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



# ---------------------------------------------------------------------------------------------------- #
# The walk on ids (session 2)
# ---------------------------------------------------------------------------------------------------- #
def _classes(tokens):
    """A made rule for each token's class (token_index.W_*), on the real words: the commonest lemmas known, a lemma of
    no kana or kanji skipped where its surface has none either, one-character words named or bound by turns — every
    class met, decided by the token alone, as the walk's `_class_of` decides it."""
    common = [lemma for lemma, _n in Counter(t[0] for t in tokens).most_common(12)]

    def classify(token):
        lemma, reading, surface, _orth = token
        key = (lemma, reading)
        if not any("぀" <= ch <= "鿿" for ch in lemma + surface):
            return ti.W_SKIP, key
        if lemma in common:
            return ti.W_KNOWN, key
        if len(lemma) == 1:
            return (ti.W_ONE, ti.W_NAMED, ti.W_BOUND)[ord(lemma) % 3], key
        return ti.W_UNKNOWN, key
    return classify


def _walked_by_hand(sentences, classify):
    """What walking each token one by one gives: (total, known, the multiset in the order first met, {sentence:
    [(token number, class, key)]} of the tokens from W_NAMED up)."""
    total = known = 0
    counter, hot = Counter(), {}
    for s_no, (_text, tokens) in enumerate(sentences):
        for t_no, token in enumerate(tokens):
            c, key = classify(tuple(token))
            counter[key] += 1
            if c >= ti.W_KNOWN:
                total += 1
            if ti.W_KNOWN <= c <= ti.W_NAMED:
                known += 1
            if c >= ti.W_NAMED:
                hot.setdefault(s_no, []).append((t_no, c, key))
    return total, known, list(counter.items()), hot


def _as_walked(sentences):
    return [(text, [tuple(t) for t in tokens]) for text, tokens in sentences]


def test_the_walk_counts_each_file_as_walking_its_tokens_one_by_one_does(made):
    # why: G1 — the walk looked every token up in Python (2k: 4.07 M tokens, 10.2 s of a 15.3 s Generate); on ids each
    # type is decided once and a file is array lookups. Every number the walk reads of a file must be what the token by
    # token walk gave: its totals, known count, its multiset in the order first met (`file_token_cache`, read by the
    # progressive pass and *Only i+1*'s rounds), and the tokens it still walks — for every file (an empty one too), a
    # file with its song lines blanked, and a file read as tokens (the store couldn't give it)
    language, store, paths = made
    every = [tuple(t) for p in paths for _s, tokens in store.file_tokens(p) for t in tokens]
    classify = _classes(every)
    walk = ti.Walk(store, classify)
    seen = set()
    for p in paths:
        truth = store.file_tokens(p)
        got = walk.file(p)
        if not truth:
            assert got is None, "a file with no sentence is read as tokens (a non-empty one tokenized again there)"
            continue
        total, known, counts, hot = _walked_by_hand(truth, classify)
        seen.update(c for found in hot.values() for _t, c, _k in found)
        assert got.counted() == (total, known), p
        assert list(got.counter().items()) == counts, p
        assert got.where(got.cls >= ti.W_NAMED) == hot, p
        assert [got[n] for n in range(len(got))] == _as_walked(truth), p
        assert got.sentences(got.cls >= ti.W_NAMED) == sorted(hot)
        as_read = walk.read(truth)
        assert (as_read.counted(), list(as_read.counter().items())) == ((total, known), counts), p
        assert as_read.where(as_read.cls >= ti.W_NAMED) == hot and as_read[len(truth) - 1] == _as_walked(truth)[-1]
        blank = {0, 2, len(truth) + 5}          # (a number past the file's last sentence: none)
        songs = walk.file(p, blank)
        left = [(t, [] if n in blank else k) for n, (t, k) in enumerate(truth)]
        total, known, counts, hot = _walked_by_hand(left, classify)
        assert (songs.counted(), list(songs.counter().items())) == ((total, known), counts), p
        assert songs.where(songs.cls >= ti.W_NAMED) == hot and len(songs) == len(truth)
        assert [songs[n] for n in range(len(songs))] == _as_walked(left), p
    assert seen == {ti.W_NAMED, ti.W_BOUND, ti.W_UNKNOWN}, "every class with something to do met"
    with pytest.raises(IndexError):
        walk.file(paths[0])[10 ** 6]
    assert walk.file(os.path.join(os.path.dirname(paths[0]), "no such file.srt")) is None


def test_the_walk_decides_each_type_once_and_joins_the_names_as_file_tokens_does(tmp_path):
    # why: the name tables join a library's names at read (メロンベンチ one word in every file): on ids a join is the
    # run's own id (past any the store gives, whatever another process adds meanwhile); the walk's sentences must be
    # `file_tokens`' own, and each type — a joined one too — is asked of once a run, however many files hold it
    from tests.test_names import HOMURA, JIN, PARK, SHOP, STATION, _library as names_library
    store, paths = names_library(tmp_path / "lib", {"station.txt": STATION, "shop.txt": SHOP, "park.txt": PARK,
                                                    "a.txt": HOMURA, "b.txt": JIN})
    try:
        asked = Counter()
        rule = _classes([tuple(t) for p in paths for _s, tokens in store.file_tokens(p) for t in tokens])

        def classify(token):
            asked[token] += 1
            return rule(token)
        walk = ti.Walk(store, classify)
        for _twice in range(2):
            for p in paths:
                truth = store.file_tokens(p)
                got = walk.file(p)
                assert [got[n] for n in range(len(got))] == _as_walked(truth), p
                total, known, counts, hot = _walked_by_hand(truth, rule)
                assert (got.counted(), list(got.counter().items())) == ((total, known), counts), p
                assert got.where(got.cls >= ti.W_NAMED) == hot, p
        assert walk.own, "some token was a join's (the run's own id)"
        assert all(i >= ti._RUN for i in walk.own_ids.values())
        assert max(asked.values()) == 1, "each type asked of once a run"
    finally:
        store.close()


# A Generate's sentences built in Python (each sentence whose tokens became lists), counted in the child, and what the
# progressive pass's rank gives (loaded first: a sitecustomize on its path).
_COUNT_BUILT = r"""
import atexit, json, os
from app import token_index as ti
seen = {"built": 0, "tokens": 0}
_stored = ti.Store._stored


def _counted(self, *args, **kwargs):
    out = _stored(self, *args, **kwargs)
    seen["built"] += len(out)
    seen["tokens"] += sum(len(s[1]) for s in out)
    return out
ti.Store._stored = _counted
if hasattr(ti, "WalkFile"):
    _get = ti.WalkFile.__getitem__

    def _one(self, no):
        new = no not in self._built
        out = _get(self, no)
        if new:
            seen["built"] += 1
            seen["tokens"] += len(out[1])
        return out
    ti.WalkFile.__getitem__ = _one
from app import plan_rules
_pass = plan_rules.progressive_pass
seen["ranks"] = []


def _counted_pass(files, known, lemmas, lemma_of, keep, rank, *args, **kwargs):
    def _rank(key):
        got = rank(key)
        kind = type(got).__name__
        if kind not in seen["ranks"]:
            seen["ranks"].append(kind)
        return got
    return _pass(files, known, lemmas, lemma_of, keep, _rank, *args, **kwargs)
plan_rules.progressive_pass = _counted_pass
atexit.register(lambda: json.dump(seen, open(os.environ["DSA_WALK_COUNT"], "w")))
"""

_STORE_SIZE = r"""
import json, sys
from app import token_index as ti
st = ti.open_reader(sys.argv[1])
n = tokens = 0
for (blob,) in st.conn.execute("SELECT ids FROM files WHERE counted=1"):
    held = ti._read_ids(blob)
    n += len(held[0]) - 1
    tokens += len(held[1])
counts, total = st.word_counts()
common, at = [], 0
for (lemma, _reading), uses in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
    if at >= 0.97 * total:
        break                       # the words a learner knows: those that cover 97 % of the library's words
    common.append(lemma)
    at += uses
print(json.dumps({"sentences": n, "tokens": tokens, "common": common}, ensure_ascii=False))
"""


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_generate_builds_the_tokens_of_only_the_sentences_with_something_to_do(tmp_path, language):
    # why: G1 — every Generate built every sentence's tokens of every file as Python lists and walked them one by one
    # (2k: 692,968 sentences, 4.07 M tokens), though most sentences are an example for no word; on ids only a sentence
    # holding an unknown, a word to name, a possible piece or a set phrase is built. RP-2's library, Generated twice at
    # level 2 (the second a warm Generate, forced: the store indexed), the learner knowing the words that cover 97 %
    # of it — the second counted
    from tests import plan_file_cases as cases
    from tests.test_e_redraw import LEVEL_2
    root = str(tmp_path / "root")
    cases.build(root, f"rp2-{language}")
    cases.generate(root, f"rp2-{language}", extra_env=LEVEL_2)
    q = subprocess.run([sys.executable, "-c", _STORE_SIZE, language], cwd=cases.REPO, env=cases.child_env(root),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert q.returncode == 0, q.stderr[-2000:]
    size = json.loads(q.stdout.strip().splitlines()[-1])
    known_path = os.path.join(root, "User Files", language, "KnownWord.json")
    with open(known_path, encoding="utf-8-sig") as f:
        known = json.load(f)
    words = known["words"] if isinstance(known, dict) else known
    words.extend({"dictForm": lemma, "knownStatus": "KNOWN"} for lemma in size["common"])
    with open(known_path, "w", encoding="utf-8") as f:
        json.dump(known, f, ensure_ascii=False)
    hook = tmp_path / "hook"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text(_COUNT_BUILT, encoding="utf-8")
    counted = tmp_path / "built.json"
    env = cases.child_env(root)
    env.update(LEVEL_2, SURASURA_FORCE_RUN="1", DSA_WALK_COUNT=str(counted),
               PYTHONPATH=str(hook) + os.pathsep + env["PYTHONPATH"])
    p = subprocess.run([sys.executable, os.path.join(cases.REPO, "app", "analyzer.py"), f"--language={language}",
                        "--static", "--no-open"], cwd=cases.REPO, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
    built = json.loads(counted.read_text(encoding="utf-8"))
    assert size["sentences"] > 300 and len(size["common"]) > 20
    # Before: every sentence (and token) of every counted file, at least. On ids: well under half of them.
    assert built["built"] < 0.5 * size["sentences"], (built, size)
    assert built["tokens"] < 0.5 * size["tokens"], (built, size)
    # G5: the progressive pass's rank of each listed word, one integer made once a round (ties sharing it), never a
    # tuple made a word a file — the order the same (test_plan_file pins the pass's outputs byte for byte). (RP-2's
    # Chinese, 97 % known, may leave no file two listed words to rank.)
    assert built["ranks"] == ["int"] if language == "ja" else "tuple" not in built["ranks"], built["ranks"]


# ---------------------------------------------------------------------------------------------------- #
# G8: the known words normalized per term
# ---------------------------------------------------------------------------------------------------- #
def _known_words_file(folder, resources, language, extra=()):
    """The real known-words file (ja: 11,582 entries; zh: its own), plus `extra` terms marked known — a sync's add."""
    name = "KnownWord.json" if language == "ja" else "KnownWords.json"
    with open(os.path.join(resources, name), encoding="utf-8-sig") as f:
        data = json.load(f)
    words = data["words"] if isinstance(data, dict) else data
    words.extend({"dictForm": term, "knownStatus": "KNOWN"} for term in extra)
    path = os.path.join(str(folder), "KnownWord.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return path


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_sync_that_adds_a_word_reads_only_that_word_again(tmp_path, language, ja_resources_dir, zh_resources_dir):
    # why: G8 — any sync that adds one word missed the store's whole cache, and every known term was tokenized again
    # (the bench's 9,315 keys: 0.31-0.86 s a Generate after a sync); each term's words depend on the term alone (and on
    # the switches, tables, script and tokenizer the store keys them on), so only the terms not read before are
    # tokenized — and the sets are the very ones a fresh read of the whole file gives
    from app import analyzer
    resources = ja_resources_dir if language == "ja" else zh_resources_dir
    store = ti.open_store(language, path=str(tmp_path / "store.db"))
    store.switches = (False, False, False)
    tok = analyzer.JapaneseTokenizer() if language == "ja" else analyzer.ChineseTokenizer()
    asked = []
    name = "tokenize_sentences" if language == "ja" else "tokenize"     # (what a known term is read by)
    real = getattr(tok, name)
    setattr(tok, name, lambda text, *a, **k: (asked.append(text), real(text, *a, **k))[1])
    try:
        path = _known_words_file(tmp_path, resources, language)
        first = analyzer.read_known_words(store, path, ti.known_signature(path), tok)
        whole = len(set(asked))
        assert whole > 3 and first[0] and first[1]
        held = {w.get("dictForm") for w in json.load(open(path, encoding="utf-8"))["words"]}
        new = [w for w in (("寝坊", "鯨幕", "雪洞", "勘違い") if language == "ja" else ("夜市", "麻辣烫", "臭豆腐"))
               if w not in held][:2]
        assert len(new) == 2, "two words the file doesn't hold"
        os.remove(path)
        path = _known_words_file(tmp_path, resources, language, new)
        del asked[:]
        again = analyzer.read_known_words(store, path, ti.known_signature(path), tok)
        assert sorted(set(asked)) == sorted(new), "only the words the sync added are read"
        del asked[:]
        fresh = analyzer.load_known_words(path, tok)
        assert again == fresh and len(set(asked)) == whole + len(new)
        assert again[0] > first[0] and again[1] > first[1]
        # A removed word leaves the store's terms with it; another tokenizer (another build) reads every term again
        os.remove(path)
        path = _known_words_file(tmp_path, resources, language, new[:1])
        new = tuple(new)
        assert analyzer.read_known_words(store, path, ti.known_signature(path), tok) == analyzer.load_known_words(path, tok)
        assert new[1] not in store.known_terms(getattr(tok, "script", "asis"))
        store.set_meta("build_sig", "another tokenizer")
        assert store.known_terms(getattr(tok, "script", "asis")) == {}
    finally:
        store.close()
