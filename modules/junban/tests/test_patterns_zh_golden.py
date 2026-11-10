# SPDX-License-Identifier: GPL-3.0-or-later
"""Chinese stays exactly as it is — three goldens, the Japanese way (test_patterns_ja_golden.py), written
2026-09-25 at Chinese builder 2 (Patterns_Quality_Spec.md §10) so that the next language, or any Chinese
change, is measured against them (Patterns_New_Language_Playbook.md §11.1):

  (a) the builder: every lemma, alias and pattern row a build of the repo's real Chinese fixtures writes
      (floor 1, MIN_PATTERN 1 — so every rule fires on so little text), segmentation as the analyzer's
      default (reinforce off);
  (b) the lookup: `patterns_zh.from_sources`' field for 25 words — Simplified and Traditional cards — through
      three fixture stores (conversational, balanced which holds it, and the library), in the user's script
      s and in t;
  (c) the planner: `backfill.plan` over a Chinese note type with a REAL session on those stores — edits,
      rows, counts, and what 例文 asked the library.

A golden changes only on purpose: `SURASURA_WRITE_GOLDEN=1 python -m pytest
modules/junban/tests/test_patterns_zh_golden.py` rewrites them — and fails, so a rewrite is never silent.
Then show that only the intended rows moved.
"""
import os
import shutil
from unittest import mock

import pytest

from app import analyzer, settings_manager
from modules.junban import backfill, patterns, patterns_build as pb, patterns_zh as pz
from modules.junban.tests.test_patterns_ja_golden import _check, _rows
from modules.junban.tests.test_patterns_zh_build import jieba_state  # noqa: F401  (a fixture)
from modules.junban.tests.test_reposition import _patched
from modules.junban.tests.test_side_by_side import URL, _fake, _zh

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
ZH = os.path.join("tests", "Test Resources", "zh")
# The real fixtures, by the store they build: talk (the 冒险 lines, a mixed-script transcript, the two
# パターン samples written for this) and writing (BBC news, Taiwanese news); balanced holds both.
TALK = ["context_test.txt", "mixed_script_transcript.txt", "patterns_zh_sample.txt", "patterns_zh_sample_trad.txt"]
WRITING = ["chinese_text_1.txt", "traditional_news.txt"]
WORDS = ["问题", "問題", "学习", "學習", "电话", "電話", "朋友", "喜欢", "重要", "关系", "关税", "合作", "桌子",
         "冒险", "通话", "强调", "希望", "表示", "谈判", "非常", "中文", "台湾", "特朗普", "可能", "没有的词"]


@pytest.fixture
def zh_stores(monkeypatch, jieba_state):  # noqa: F811
    """The three fixture stores, built where the app looks (the sandboxed data folder), with the default
    zh sentence boundaries — a golden must not move with the developer's settings."""
    logic = dict(analyzer.LOGIC)
    logic["sentence_boundaries"] = dict(logic.get("sentence_boundaries") or {},
                                        zh=settings_manager.DEFAULT_SETTINGS["logic"]["sentence_boundaries"]["zh"])
    monkeypatch.setattr(analyzer, "LOGIC", logic)
    monkeypatch.setattr(pb, "MIN_PATTERN", 1)
    # Six small files: "seen in 3 documents" and "strength 2" would leave almost nothing to compare, so they
    # are off here, as in the Japanese golden; every other rule holds.
    monkeypatch.setattr(patterns, "MIN_DOCS", 1)
    monkeypatch.setattr(patterns, "MIN_STRENGTH", float("-inf"))
    built = {}
    for name, files in (("conversational", TALK), ("balanced", TALK + WRITING), ("library", WRITING)):
        corpus = os.path.join(os.path.dirname(pb.default_db_path("zh")), "corpus_zh_" + name)
        os.makedirs(corpus)
        for path in files:
            shutil.copy(os.path.join(_ROOT, ZH, path), corpus)
        db = pb.default_db_path("zh", None if name == "library" else name)
        pb.build(corpus_dir=corpus, db_path=db, language="zh", floor=1)
        built[name] = db
    return built


def test_the_chinese_builders_rows_are_unchanged(zh_stores):
    # (a) Every rule, on real text: a change that reached a Chinese function body — or a shared one the
    # Chinese builder calls — moves rows here.
    rows = _rows(zh_stores["balanced"])
    assert len(rows) > 2500
    _check("zh_builder_rows.txt.gz", rows)


def test_the_chinese_lookups_fields_are_unchanged(zh_stores):
    # (b) The card's field for 25 words — Simplified and Traditional cards of one word (问题 / 問題), nouns,
    # verbs, an adjective, an adverb (非常), names (台湾, 特朗普), a word not in the texts — through the fill
    # order the app uses, in the user's script s and in t.
    sources = patterns.open_sources("zh")
    try:
        fields = {script: {word: list(pz.from_sources(word, sources, script)) for word in WORDS}
                  for script in ("s", "t")}
    finally:
        for _name, store in sources:
            if store is not None:
                store.close()
    assert sum(1 for html, _reason, _src in fields["s"].values() if html) >= 15
    _check("zh_lookup.json", fields)


def test_the_chinese_planners_decisions_are_unchanged(zh_stores):
    # (c) A real Chinese session on the fixture stores; the library search for 例文 answered from the
    # fixture sentences — and recorded, so what the planner asks the library for is compared too.
    lines = [line.strip() for line in open(os.path.join(_ROOT, ZH, "patterns_zh_sample.txt"), encoding="utf-8")
             if line.strip()]
    asked = []

    def best_for(language, wanted, progress=None, young=None, phrases=None, prefer=None):
        asked.append({"language": language, "wanted": sorted(map(list, wanted)),
                      "phrases": {k: list(v) for k, v in sorted((phrases or {}).items())},
                      "prefer": {"|".join(k): [list(run) for run in v] for k, v in sorted((prefer or {}).items())}})
        return {key: [(0, line, key[0], n) for n, line in enumerate(lines) if key[0] in line]
                for key in wanted if any(key[0] in line for line in lines)}

    fake = _fake(_zh(0, "问题", "wèntí", "这个问题很难。"), _zh(1, "學習", "xuéxí", "他在學校學習。"),
                 _zh(2, "电话", "diànhuà", "我给他打了电话。"), _zh(3, "朋友", "péngyǒu", "他是我的好朋友。"),
                 _zh(4, "喜欢", "xǐhuan", "我很喜欢这本书。"), _zh(5, "桌子", "zhuōzi", "书在桌子上。"))
    settings = {"target_language": "zh", "zh_script": "s", "junban_url": URL, "junban_chunk_size": 150,
                "junban_backfill_fills": ["patterns", "sentence"],
                "junban_backfill_note_languages": {"Chinese Vocab": "zh"}}
    session = backfill.Session(settings)
    try:
        with _patched(fake), mock.patch("app.sentence_corpus.best_for", side_effect=best_for):
            result = backfill.plan(backfill.gather(URL, settings), session, settings)
    finally:
        session.close()
    out = {**result, "edits": {str(k): v for k, v in result["edits"].items()}, "asked": asked}
    assert out["counts"].get("fill", 0) >= 3
    _check("zh_plan.json", out)
