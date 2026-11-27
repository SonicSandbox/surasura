"""AUDIO-WASTE: `Store.holding` — the first look for which files hold some words — gives the byte search's answer
exactly, read a query per HOLDING_CHUNK paths and, with many words asked, each file's counts read once into a set.

Real data: the suite's Japanese and Chinese subtitles and texts (`tests/Test Resources/ja|zh`), tokenized by the real
tokenizers into a store in a temp folder. The reference is the byte search as it was before (one SELECT and one
search of the blob per word per file), kept here so every answer is compared with it.
"""
import json
import os
import zlib

import pytest

from app import token_index as ti

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "Test Resources")
JA = ["placed_episode.srt", "repeated_lines.ja.srt", "readings_sample.srt", "verses_sample.srt",
      "utterances_sample.srt", "context_test.txt", "sentence_words.txt"]
ZH = ["night_market.srt", "repeated_lines.zh.srt", "utterances_sample.srt", "chinese_text_1.txt", "context_test.txt",
      "mixed_script_transcript.txt"]


def _reference(store, paths, keys=(), runs=(), most=None):
    """The byte search as it was (before AUDIO-WASTE): one SELECT and a search of the blob per word per file."""
    wanted = [[json.dumps(ti.make_key(lemma, reading), ensure_ascii=False).encode("utf-8")] for lemma, reading in keys]
    wanted += [[json.dumps(lemma, ensure_ascii=False)[:-1].encode("utf-8") + b"|" for lemma in run]
               for run in runs if run]
    found = [0] * len(wanted)
    out = []
    for path in paths:
        if most is not None and all(n >= most for n in found):
            break
        row = store.conn.execute("SELECT counts FROM files WHERE path=?", (ti._norm(path),)).fetchone()
        try:
            text = zlib.decompress(row[0]) if row and row[0] else b""
        except zlib.error:
            text = b""
        hit = False
        for at, parts in enumerate(wanted):
            if (most is None or found[at] < most) and all(p in text for p in parts):
                found[at] += 1
                hit = True
        if hit:
            out.append(path)
    return out


def _store(tmp_path, language, names):
    paths = [os.path.join(RES, language, n) for n in names]
    paths = [p for p in paths if os.path.isfile(p)]
    store = ti.open_store(language, path=str(tmp_path / f"store_{language}.db"))
    store.reconcile(paths, ti.make_tokenizer(language))
    return store, paths


def _words(store):
    """Every (lemma, reading) the store counted, in a stable order."""
    keys = set()
    for (blob,) in store.conn.execute("SELECT counts FROM files WHERE counts IS NOT NULL"):
        keys.update(json.loads(zlib.decompress(blob)))
    return [tuple(k.split("|", 1)) for k in sorted(keys)]


@pytest.mark.parametrize("language,names", [("ja", JA), ("zh", ZH)])
def test_holding_answers_as_the_byte_search_for_many_and_few_words_ja_and_zh(tmp_path, monkeypatch, language, names):
    """Many words (the set read), few (the byte search), several-word runs, a word no file holds, `most`, duplicate
    and unknown paths, chunks of 1 and 2 paths — each answer exactly the byte search's, in the paths' order."""
    store, paths = _store(tmp_path, language, names)
    try:
        words = _words(store)
        assert len(words) > 100 and len(paths) >= 3            # real tokenized text, several files
        lemmas = sorted({w[0] for w in words})
        asked = paths + [paths[0], os.path.join(RES, language, "not_in_the_store.srt")]
        cases = [
            dict(keys=words[::7]),
            dict(runs=[[w] for w in lemmas[::5]]),
            dict(runs=[[w] for w in lemmas[:3]]),                                      # few: the byte search
            dict(runs=[lemmas[i:i + 3] for i in range(0, len(lemmas), 11)] + [["存在しない語彙"]]),
            dict(keys=words[:40] + [("存在しない語彙", "ゾンザイシナイ")], runs=[[w] for w in lemmas[-30:]]),
            dict(keys=[(w[0], w[1] + "x") for w in words[:30]]),                       # a lemma held, not that key
        ]
        for first, chunk in ((1, 1), (1, 2), (2, 3), (ti.HOLDING_FIRST, ti.HOLDING_CHUNK)):
            monkeypatch.setattr(ti, "HOLDING_FIRST", first)              # (growing reads: 1, 2, 2 ... / 2, 3, 3 ...)
            monkeypatch.setattr(ti, "HOLDING_CHUNK", chunk)
            for case in cases + [dict()]:
                for most in (None, 0, 1, 2):
                    got = store.holding(asked, most=most, **case)
                    assert got == _reference(store, asked, most=most, **case), (chunk, most, case)
        assert store.holding([], runs=[[w] for w in lemmas]) == []
        many = dict(runs=[[w] for w in lemmas[::5]])                    # any iterable of paths, as before
        assert store.holding(iter(asked), **many) == _reference(store, asked, **many)
    finally:
        store.close()


def test_a_blob_or_word_json_escapes_falls_back_to_the_byte_search_and_answers_the_same(tmp_path):
    """A key holding a quote, a backslash or a tab (JSON writes each with a backslash: a quote in the blob is then
    not only a key's own) — that file is searched byte by byte, and a word with one is too; a lemma with a bar is
    searched as the byte search finds it (`"a|` also starts the key a|b|…). Each answer the reference's."""
    store, paths = _store(tmp_path, "ja", JA[:3])
    try:
        odd = {'言"う|イウ': 1, '"|キゴウ': 1, "円\\記号|エン": 2, "タブ\tの|タブ": 1, "棒|線|ボウ": 1, "普通|フツウ": 3}
        store.conn.execute("UPDATE files SET counts = ? WHERE path = ?",
                           (ti._encode_counts(odd), ti._norm(paths[0])))
        clean = {"棒|線|ボウ": 1, "棒|ボウ": 2, "普通|フツウ": 1}
        store.conn.execute("UPDATE files SET counts = ? WHERE path = ?",
                           (ti._encode_counts(clean), ti._norm(paths[1])))
        odd2 = zlib.compress(json.dumps({"abc": 1, "x|y": "ab|c", "p|q": {"a|b": 1}, "普通|フツウ": 2},
                                        ensure_ascii=False).encode("utf-8"))      # not the writer's shape
        store.conn.execute("UPDATE files SET counts = ? WHERE path = ?", (odd2, ti._norm(paths[2])))
        store.conn.commit()
        lemmas = ["abc", "ab", "a", "x", "p", '言"う', "円\\記号", "タブ\tの", "棒", "棒|線", "普通", '"', "う", "言", ""] + \
            [w[0] for w in _words(store)][:30]
        keys = [("a", "b"), ("x", "y"), ('言"う', "イウ"), ("円\\記号", "エン"), ("棒|線", "ボウ"), ("棒", "線|ボウ"), ("普通", "フツウ"),
                ('"', "キゴウ")]
        for case in (dict(runs=[[w] for w in lemmas]), dict(keys=keys, runs=[[w] for w in lemmas]),
                     dict(runs=[["棒", "普通"], ['言"う', "普通"]] + [[w] for w in lemmas])):
            assert store.holding(paths, **case) == _reference(store, paths, **case), case
        assert len(dict(runs=[[w] for w in lemmas])["runs"]) >= ti.HOLDING_SET_AT     # (the set read was asked)
    finally:
        store.close()


def test_holding_reads_the_blobs_a_query_per_chunk_never_one_per_file(tmp_path, monkeypatch):
    """Red before AUDIO-WASTE: one SELECT a file. Now one a HOLDING_CHUNK paths (HOLDING_FIRST the first)."""
    store, paths = _store(tmp_path, "ja", JA)
    try:
        monkeypatch.setattr(ti, "HOLDING_FIRST", 3)
        monkeypatch.setattr(ti, "HOLDING_CHUNK", 3)
        said = []
        lemmas = sorted({w[0] for w in _words(store)})
        store.conn.set_trace_callback(lambda sql: said.append(sql) if "FROM files" in sql else None)
        said.clear()
        store.holding(paths, runs=[[w] for w in lemmas])
        assert len(said) == -(-len(paths) // 3) < len(paths)
    finally:
        store.conn.set_trace_callback(None)
        store.close()


def test_many_words_read_each_file_once_not_once_a_word(tmp_path, monkeypatch):
    """Red before AUDIO-WASTE: the counts are searched once a word a file (W × files searches of the blob). Now, with
    HOLDING_SET_AT words or more, each file's counts are read once (`json.loads` once a file) and each word a look."""
    store, paths = _store(tmp_path, "ja", JA)
    try:
        lemmas = sorted({w[0] for w in _words(store)})
        loads = []
        real = ti.json.loads
        monkeypatch.setattr(ti.json, "loads", lambda s, *a, **k: loads.append(1) or real(s, *a, **k))
        got = store.holding(paths, runs=[[w] for w in lemmas])
        monkeypatch.setattr(ti.json, "loads", real)
        assert got == _reference(store, paths, runs=[[w] for w in lemmas]) == paths
        assert len(loads) == len(paths)
    finally:
        store.close()


def test_a_caller_stopping_at_most_reads_few_blobs_not_a_whole_chunk(tmp_path):
    """`most` 1 for one word every file holds: the answer is the first file, and the reads stop at the first query
    (HOLDING_FIRST paths), never HOLDING_CHUNK blobs for one file."""
    store, paths = _store(tmp_path, "ja", JA)
    try:
        common = sorted(set.intersection(*[{k.split("|")[0] for k in json.loads(zlib.decompress(b))}
                                           for (b,) in store.conn.execute("SELECT counts FROM files")]))
        assert common                                                   # (a word every file holds: は, の …)
        said = []
        store.conn.set_trace_callback(lambda sql: said.append(sql) if "FROM files" in sql else None)
        assert store.holding(paths * 10, runs=[[common[0]]], most=1) == paths[:1]
        assert len(said) == 1 and said[0].count("', '") + 1 <= ti.HOLDING_FIRST     # (one query, its few paths)
    finally:
        store.conn.set_trace_callback(None)
        store.close()
