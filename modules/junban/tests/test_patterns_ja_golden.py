# SPDX-License-Identifier: GPL-3.0-or-later
"""Japanese stays exactly as it is (Patterns_Chinese_Spec.md §13, JU-1) — three goldens, written at the
commit before any Chinese code (2026-09-25, builder 5) and compared after every work package:

  (a) the builder: every lemma, alias and pattern row a build of the repo's real Japanese fixtures
      writes (floor 1, MIN_PATTERN 1 — so every rule fires on so little text);
  (b) the lookup: `patterns_from_sources`' field for 25 words through three fixture stores — the
      conversational one, the balanced one (which holds it, as the real ones do) and the library;
  (c) the planner: `backfill.plan` over a Lapis collection with a REAL session on those stores, under
      two settings (All; New only with Replace) — edits, rows, counts, and what 例文 asked the library.

A golden changes only on purpose: `SURASURA_WRITE_GOLDEN=1 python -m pytest
modules/junban/tests/test_patterns_ja_golden.py` rewrites them — and fails, so a rewrite is never
silent. Then show that only the intended rows moved. (Rewritten 2026-09-25 for words keeping their
affixes and for builder 6 — Patterns_Quality_Spec.md §6, §8; 2026-09-29 for builder 8 — words made of words
are one word, and numbers and symbols are no content, as the tokenizer counts; and again that day for a katakana
name a compound no dictionary lists had cut: ビルデイング is one word, not ビルデ + イング — 7 rows; and 2026-09-30 for a
katakana word the lists hold that no dictionary join makes, cut into letters: レーナ and アサト are one word each, not
レー + ナ and アサ + ト — 8 rows gone, 20 new, every one of them レーナ's or アサト's; and once more that day for two
fillers cut out of one interjection: a sample book's inline ruby おう (of 王) was the fillers お + う and is the
interjection おう now, on おお's row — 2 rows, its counts; and once more that day for a one-kanji word's own uses: a
one-kanji word glued to another one-kanji piece or right after a number gives its row no count and no line, as the
list counts it — 223 rows gone, 108 new, every one a row of one of 64 one-character words; and the 人 card reads 人
'person' (人の形 · 人に対する · 人をほる · 人の家, from balanced), no longer outweighed by the counter 〜人 after numbers;
and 2026-10-01 for the dictionary's words the tagger cuts at their grammar: the samples' いつも, でも, それで, 何か, 一緒に,
思わず, すまない, 思いがけない … are words of their own, each with its lemma, alias and lines (26 words: 52 rows and 14
lines), and the pieces they held lose those uses (居る, 無い and 良い count fewer particle lines; 本当にすむ is
本当にすまない) — 9 rows gone, 66 new; the いい card loses で〜, read in それでもいい; and once more that day for a
spelling the dictionary keeps apart from the lemma UniDic files it under: the samples' 帰る, 撮る, 挙げる, 指す, 言える,
思える, 使える, 聞ける, 貰える … are words of their own as well (18 words: their lemma and alias rows, and 23 lines on 12 of
them — 家に帰る and 帰らない on 帰る, 手を挙げる on 挙げる), while their lemmas keep every use: no pattern row moved, their
18 spellings left the lemmas' alias rows for their own (the same counts), and 5 lemmas show their next spelling (返る
かえる, 差す 差す) — 23 rows gone, 64 new; and once more that evening for the list's counter clause (the 目 of ２時間目:
a one-kanji word right after a number + a word holding a kanji is a piece of the count, analyzer._bound_at), which the
builder now asks with the token before the word's left neighbour too: the sample's 豆知識 after ５つ子 gives its part 豆
no use — the clause's accepted imprecision, a free word after a count — 3 rows gone, every one 豆's; and
2026-11-10 (Hon-SM) for new fixtures: the bundled samples are public-domain texts now (蜘蛛の糸, 注文の多い料理店,
ごん狐 and a café dialogue written for Surasura), so all three goldens were written again from them, and the
lookup and planner words the old samples held (老婆, 共和国, 席, 少女, 市民, 座る, 譲る, 人間, おだやか, 素直, 大切な) became words of the new
ones (蜘蛛, 地獄, 糸, 紳士, 狐, 歩く, 助ける, 極楽, 元気, きれい, 立派な).)
"""
import gzip
import json
import os
import shutil
import sqlite3
from unittest import mock

import pytest

from app import analyzer, settings_manager
from modules.junban import backfill, patterns, patterns_build as pb
from modules.junban.tests.test_backfill import (URL, BackfillCollection, LAPIS_EX, MIGAKU, _ex,
                                                _migaku)
from modules.junban.tests.test_reposition import _patched

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")
WRITE = os.environ.get("SURASURA_WRITE_GOLDEN") == "1"
# The real fixtures, by the store they build: talk (a subtitle file, the 冒険 lines, a transcript) and
# writing; balanced holds both, as the real balanced set holds the conversational one.
TALK = ["samples/ja/HighPriority/喫茶店の朝.srt", "tests/Test Resources/ja/context_test.txt",
        "tests/Test Resources/ja/runaway_transcript.txt"]
WRITING = ["samples/ja/HighPriority/蜘蛛の糸（芥川龍之介）.txt", "samples/ja/LowPriority/注文の多い料理店（宮沢賢治）.txt",
           "samples/ja/LowPriority/ごん狐（新美南吉）.txt"]
WORDS = ["冒険", "冒険家", "蜘蛛", "目", "人", "地獄", "糸", "極楽", "紳士", "顔", "狐", "持つ", "待つ",
         "見る", "歩く", "助ける", "立つ", "長い", "悪い", "いい", "元気", "きれい", "立派な", "話が弾む", "探検"]


@pytest.fixture
def stores(monkeypatch):
    """The three fixture stores, built where the app looks (the sandboxed data folder), with the
    default sentence boundaries — a golden must not move with the developer's settings."""
    logic = dict(analyzer.LOGIC)
    logic["sentence_boundaries"] = dict(logic.get("sentence_boundaries") or {},
                                        ja=settings_manager.DEFAULT_SETTINGS["logic"]["sentence_boundaries"]["ja"])
    monkeypatch.setattr(analyzer, "LOGIC", logic)
    monkeypatch.setattr(pb, "MIN_PATTERN", 1)
    # Six small files: "seen in 3 documents" and "strength 2" would leave almost nothing to compare, so
    # they are off here, the way MIN_PATTERN is (Patterns_Quality_Spec.md §8.5); every other rule holds.
    monkeypatch.setattr(patterns, "MIN_DOCS", 1)
    monkeypatch.setattr(patterns, "MIN_STRENGTH", float("-inf"))
    built = {}
    for name, files in (("conversational", TALK), ("balanced", TALK + WRITING), ("library", WRITING)):
        corpus = os.path.join(os.path.dirname(pb.default_db_path("ja")), "corpus_" + name)
        os.makedirs(corpus)
        for path in files:
            shutil.copy(os.path.join(_ROOT, path), corpus)
        db = pb.default_db_path("ja", None if name == "library" else name)
        pb.build(corpus_dir=corpus, db_path=db, floor=1)
        built[name] = db
    return built


def _check(name, value):
    """Compare `value` with the golden `name` — or, with SURASURA_WRITE_GOLDEN=1, write it and fail."""
    path = os.path.join(GOLDEN, name)
    if name.endswith(".gz"):
        data = gzip.compress("\n".join(value).encode("utf-8") + b"\n", mtime=0)
    else:
        data = (json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")
    if WRITE:
        os.makedirs(GOLDEN, exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        pytest.fail(f"golden written: {path} — run again without SURASURA_WRITE_GOLDEN")
    assert os.path.exists(path), f"no golden {name}: see this file's docstring"
    with open(path, "rb") as f:
        stored = f.read()
    if name.endswith(".gz"):
        want, got = gzip.decompress(stored).decode("utf-8").splitlines(), value
    else:
        want, got = json.loads(stored.decode("utf-8")), json.loads(data.decode("utf-8"))
    if want != got:
        if isinstance(want, list):
            gone, new = sorted(set(want) - set(got)), sorted(set(got) - set(want))
            pytest.fail(f"{name}: {len(gone)} rows gone, {len(new)} new — e.g. gone {gone[:5]}, new {new[:5]}")
        assert got == want


def _rows(db):
    """Every row of the three tables, as text, sorted — the meta (paths, times) is not compared."""
    con = sqlite3.connect(db)
    try:
        return sorted("\t".join([table] + ["\\N" if v is None else str(v) for v in row])
                      for table in ("lemma", "alias", "pattern") for row in con.execute(f"SELECT * FROM {table}"))
    finally:
        con.close()


def test_the_builders_rows_are_unchanged(stores):
    # (a) Every rule, on real text: a Chinese change that reached one Japanese function body would
    # move rows here.
    rows = _rows(stores["balanced"])
    assert len(rows) > 5000                  # (2026-11-10, Hon-SM: the public-domain samples are a smaller corpus: 5,535)
    _check("ja_builder_rows.txt.gz", rows)


def test_the_lookups_fields_are_unchanged(stores):
    # (b) The card's field for 25 words — nouns, verbs, adjectives, a compound (冒険家), a word written
    # with its な (立派な), a phrase, a word not in the texts — through the fill order the app uses.
    sources = patterns.open_sources("ja")
    tokenize = patterns.tokenizer()
    try:
        fields = {word: list(patterns.patterns_from_sources(word, "", sources, tokenize)) for word in WORDS}
    finally:
        for _name, store in sources:
            if store is not None:
                store.close()
    assert sum(1 for html, _reason, _src in fields.values() if html) >= 20
    _check("ja_lookup.json", fields)


def _collection():
    """Lapis notes (with the 例文 field) of every kind the planner tells apart, and a Migaku note."""
    pairs = [_ex(0, "冒険", "ぼうけん"), _ex(1, "目", "め", studied=True, interval=5), _ex(2, "蜘蛛", "くも"),
             _ex(3, "立派な", "りっぱな"), _ex(4, "話が弾む", "はなしがはずむ"), _ex(5, "探検", "たんけん"),
             _ex(6, "持つ", "もつ", studied=True, interval=40), _ex(7, "長い", "ながい"),
             _ex(8, "元気", "げんき"), _ex(9, "地獄", "じごく"), _ex(10, "冒険家", "ぼうけんか"),
             _migaku(0, "冒険")]
    pairs[2][0]["fields"]["Patterns"]["value"] = "<div>もう書いてある</div>"
    return BackfillCollection([p[1] for p in pairs], [p[0] for p in pairs],
                              {"Lapis": LAPIS_EX, "Migaku Japanese": MIGAKU})


def test_the_planners_decisions_are_unchanged(stores):
    # (c) A real session on the fixture stores; the library search for 例文 answered from the fixture
    # sentences — and recorded, so what the planner asks the library for is compared too.
    lines = [line.strip() for line in open(os.path.join(_ROOT, "tests", "Test Resources", "ja", "context_test.txt"),
                                           encoding="utf-8") if line.strip()]
    asked = []

    def best_for(language, wanted, progress=None, young=None, phrases=None, prefer=None):
        asked.append({"wanted": sorted(map(list, wanted)), "young": sorted(map(list, young or ())),
                      "phrases": {k: list(v) for k, v in sorted((phrases or {}).items())},
                      "prefer": {"|".join(k): [list(run) for run in v] for k, v in sorted((prefer or {}).items())}})
        return {key: [(0, line, key[0], n) for n, line in enumerate(lines) if key[0] in line]
                for key in wanted if any(key[0] in line for line in lines)}

    out = {}
    for label, over in (("all", {}), ("new_replace", {"junban_backfill_cards": "new", "junban_backfill_replace": True})):
        settings = {"target_language": "ja", "junban_url": URL, "junban_chunk_size": 150,
                    "junban_backfill_fills": ["patterns", "sentence"], **over}
        session = backfill.Session(settings)
        try:
            with _patched(_collection()), mock.patch("app.sentence_corpus.best_for", side_effect=best_for):
                result = backfill.plan(backfill.gather(URL, settings), session, settings)
        finally:
            session.close()
        out[label] = {**result, "edits": {str(k): v for k, v in result["edits"].items()}}
    out["asked"] = asked
    assert out["all"]["counts"].get("fill", 0) >= 5
    _check("ja_plan.json", out)
