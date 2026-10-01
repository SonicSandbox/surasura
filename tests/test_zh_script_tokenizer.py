"""WP-Z2: the Chinese tokenizer's `script`, and the caches that must follow a script switch.

Spec: docs/agent instructions/Chinese_Script_Conversion_Spec.md (§5.3, §7, gotchas 2-5).

- As-is reads the text through Simplified too (jieba's dictionary is Simplified only) and keeps every word
  as the text writes it: 為什麼 is one word, still spelled 為什麼. Its full output is pinned by a golden
  file generated from the committed analyzer, not against a re-implementation (2.4 retired the old rule
  that as-is be byte-for-byte the pre-feature tokenizer: it cut Traditional text into pieces).
- `s` / `t` emit single-script tokens, segment in Simplified, and merge a word across scripts.
- The token store's build signature and the known-words signature change on a switch and ONLY on a
  switch. An as-is store keeps its exact old signature, or every Chinese user would rebuild their
  whole index on upgrade (gotcha 5).
- The background indexer builds the SAME tokenizer a run does. It used to drop `reinforce` for the
  known-words cache while the analyzer passed it, and both write the one cache entry (gotcha 3).
"""

import json
import os
import sys
from unittest.mock import patch

import pytest

from app import analyzer, indexer, token_index as ti, zh_script


def _read(zh_resources_dir, name):
    with open(os.path.join(zh_resources_dir, name), encoding="utf-8") as f:
        return f.read()


def _words(text, script):
    return [t[0] for _s, toks in analyzer.ChineseTokenizer(script=script).tokenize_sentences(text)
            for t in toks]


# ---- the tokenizer ---------------------------------------------------------------------------- #

def test_asis_tokenization_matches_its_golden(zh_resources_dir, monkeypatch):
    """The golden holds the as-is tokenizer's full output (sentences AND token tuples) for both files, under
    the sentence boundaries it was generated with: any change to it is deliberate, and regenerates it."""
    with open(os.path.join(zh_resources_dir, "asis_tokens_golden.json"), encoding="utf-8") as f:
        golden = json.load(f)
    monkeypatch.setitem(analyzer.LOGIC, "sentence_boundaries", {"zh": golden["boundaries"]})
    for name, expected in golden["files"].items():
        text = _read(zh_resources_dir, name)
        for tok in (analyzer.ChineseTokenizer(), analyzer.ChineseTokenizer(script="asis")):
            got = [[s, [list(t) for t in toks]] for s, toks in tok.tokenize_sentences(text)]
            assert got == expected, name


def test_an_unknown_script_value_is_as_is():
    assert analyzer.ChineseTokenizer(script="tw").script == "asis"
    assert analyzer.ChineseTokenizer().script == "asis"


def test_s_reads_traditional_content_as_simplified(zh_resources_dir):
    text = _read(zh_resources_dir, "traditional_news.txt")
    asis = [s for s, _ in analyzer.ChineseTokenizer().tokenize_sentences(text)]
    got = list(analyzer.ChineseTokenizer(script="s").tokenize_sentences(text))
    # Same sentences, just converted: the boundaries (punctuation) never move.
    assert [s for s, _ in got] == [zh_script.convert(s, "s") for s in asis]
    words = [t[0] for _s, toks in got for t in toks]
    assert "学习" in words and "关系" in words
    assert all(zh_script.to_simplified(w) == w for w in words)


def test_t_reads_simplified_content_as_traditional(zh_resources_dir):
    """Offsets from segmenting the Simplified copy are used to slice the Traditional text. Any
    misalignment would show up as sentences that no longer match their converted as-is originals."""
    text = _read(zh_resources_dir, "chinese_text_1.txt")
    asis = [s for s, _ in analyzer.ChineseTokenizer().tokenize_sentences(text)]
    got = list(analyzer.ChineseTokenizer(script="t").tokenize_sentences(text))
    assert [s for s, _ in got] == [zh_script.convert(s, "t") for s in asis]
    words = [t[0] for _s, toks in got for t in toks]
    assert "臺灣" in words and "習近平" in words
    assert all(zh_script.to_traditional(w) == w for w in words), "a Simplified character survived"
    # The token tuple keeps its shape: (lemma, reading, surface, orth), all the same word.
    _s, toks = got[5]
    assert all(t[1] == "" and t[0] == t[2] == t[3] for t in toks)


def test_asis_cuts_traditional_text_through_simplified_and_keeps_its_spelling():
    """jieba's dictionary is Simplified only: cut as written, Traditional text came out in pieces (為 / 什麼,
    頭 / 髮, 我覺 / 得, 臺 / 灣旅遊, 經濟關 / 係). As-is now cuts the Simplified copy, as `t` always has, and every
    word is the text's own stretch — the script is kept, only the cut is shared."""
    assert _words("為什麼你不學中文？", "asis")[0] == "為什麼"
    assert "頭髮" in _words("她的頭髮很長。", "asis")
    assert _words("我覺得臺灣旅遊很好。", "asis")[:4] == ["我", "覺得", "臺灣", "旅遊"]
    assert _words("經濟關係的發展很重要。", "asis")[:2] == ["經濟", "關係"] == _words("經濟關係的發展很重要。", "t")[:2]


def test_the_simplified_fixtures_cut_alike_as_is_and_as_simplified(zh_resources_dir):
    """For text already in Simplified the Simplified pass changes nothing: as-is and `s` give the same tokens,
    sentence for sentence (the as-is change reaches Traditional text only)."""
    for name in ("context_test.txt", "patterns_zh_sample.txt"):
        text = _read(zh_resources_dir, name)
        asis = list(analyzer.ChineseTokenizer().tokenize_sentences(text))
        assert asis == list(analyzer.ChineseTokenizer(script="s").tokenize_sentences(text)), name


def test_t_segments_traditional_text_as_well_as_as_is():
    """Both cut the Simplified copy (spec §5.3); `t` writes every word in Traditional, as-is as written."""
    text = "經濟關係的發展很重要。"
    assert _words(text, "t")[:2] == ["經濟", "關係"] == _words(text, "asis")[:2]
    assert _words("经济关系很重要。", "t")[:2] == ["經濟", "關係"] and _words("经济关系很重要。", "asis")[:2] == ["经济", "关系"]


def test_a_mixed_library_counts_each_word_once():
    """The same sentence in either script must produce the SAME words, or 学习 and 學習 count twice."""
    simp = "我们需要学习这个问题。经济关系的发展很重要。"
    trad = "我們需要學習這個問題。經濟關係的發展很重要。"
    assert _words(simp, "asis") != _words(trad, "asis")      # the problem being solved
    for script in ("s", "t"):
        assert _words(simp, script) == _words(trad, script), script


# ---- signatures ------------------------------------------------------------------------------- #

@pytest.mark.parametrize("args, expected", [
    (("zh",), "zh|reinforce=False"),                        # exactly the pre-feature strings (I2)
    (("zh", True), "zh|reinforce=False"),                    # reinforce is retired: read as off
    (("zh", False, "asis"), "zh|reinforce=False"),
    (("zh", False, "s"), "zh|reinforce=False|script=s"),
    (("zh", True, "t"), "zh|reinforce=False|script=t"),
    (("zh", False, "tw"), "zh|reinforce=False"),           # unknown value = as-is
    (("ja", True, "t"), "ja|reinforce=False"),             # Japanese ignores both
])
def test_build_signature(args, expected):
    assert ti.build_signature(*args) == expected


def test_known_signature_changes_only_when_converting(tmp_path):
    known = tmp_path / "KnownWord.json"
    known.write_text(json.dumps({"words": [{"dictForm": "学习", "knownStatus": "KNOWN"}]}),
                     encoding="utf-8")
    st = os.stat(known)
    assert ti.known_signature(str(known)) == json.dumps([True, st.st_mtime, st.st_size])   # I2
    assert ti.known_signature(str(known), "asis") == ti.known_signature(str(known))
    assert ti.known_signature(str(known), "t") != ti.known_signature(str(known), "s")
    assert ti.known_signature(str(tmp_path / "missing.json"), "t") != \
        ti.known_signature(str(tmp_path / "missing.json"))


def test_the_known_cache_is_not_served_across_a_switch(tmp_path):
    """Gotcha 2: the known set is normalized in one script; after a switch the file is untouched, so a
    stat-only signature would keep serving the old script's set."""
    known = tmp_path / "KnownWord.json"
    known.write_text("{}", encoding="utf-8")
    store = ti.open_store("zh")
    try:
        store.set_cached_known(ti.known_signature(str(known), "s"), {("学习", "")}, {"学习"})
        assert store.get_cached_known(ti.known_signature(str(known), "s")) is not None
        assert store.get_cached_known(ti.known_signature(str(known), "t")) is None
        assert store.get_cached_known(ti.known_signature(str(known))) is None
    finally:
        store.close()


def test_switching_script_rebuilds_the_token_store(zh_resources_dir, tmp_path):
    """Reconcile keys "unchanged" on (mtime, size), so without the signature a switch would keep
    serving tokens in the old script. Switching back to as-is must rebuild again too."""
    content = tmp_path / "news.txt"
    content.write_text(_read(zh_resources_dir, "traditional_news.txt"), encoding="utf-8")

    def words_after(script):
        ti.reconcile_language("zh", [str(content)], script=script)
        store = ti.open_store("zh")
        try:
            assert store.get_meta("build_sig") == ti.build_signature("zh", False, script)
            return {t[0] for _s, toks in store.file_tokens(str(content)) for t in toks}
        finally:
            store.close()

    assert "學習" in words_after("asis")
    after_s = words_after("s")
    assert "学习" in after_s and "學習" not in after_s
    assert "學習" in words_after("asis")


# ---- the background indexer ------------------------------------------------------------------- #

@pytest.fixture
def zh_library(tmp_path, zh_resources_dir):
    high = tmp_path / "data" / "zh" / "HighPriority"
    high.mkdir(parents=True)
    (high / "news.txt").write_text(_read(zh_resources_dir, "traditional_news.txt"), encoding="utf-8")
    uf = tmp_path / "User Files" / "zh"
    uf.mkdir(parents=True)
    known = uf / "KnownWord.json"
    known.write_text(json.dumps({"words": [{"dictForm": "學習", "knownStatus": "KNOWN"}]},
                                ensure_ascii=False), encoding="utf-8")
    return {"root": tmp_path, "known": known}


def _write_settings(**values):
    with open(os.path.join(os.environ["SURASURA_TEST_ROOT"], "settings.json"), "w",
              encoding="utf-8") as f:
        json.dump(values, f)


def _run_indexer(lib):
    root = lib["root"]
    with patch("app.path_utils.get_data_path", side_effect=lambda lang: str(root / "data" / lang)), \
         patch("app.path_utils.get_user_files_path",
               side_effect=lambda lang: str(root / "User Files" / lang)), \
         patch.object(sys, "argv", ["indexer.py", "--language", "zh"]):
        indexer.main()


def test_indexer_builds_the_same_tokenizer_a_run_does(zh_library):
    """Both the reconcile tokenizer and the known-words tokenizer get the setting's reinforce AND
    script. The known one used to be a bare ChineseTokenizer()."""
    _write_settings(reinforce_segmentation=True, zh_script="t")
    built = []
    real = analyzer.ChineseTokenizer

    def spy(*args, **kwargs):
        built.append(kwargs)
        return real(*args, **kwargs)

    with patch.object(analyzer, "ChineseTokenizer", side_effect=spy):
        _run_indexer(zh_library)
    assert built and all(k == {"reinforce_segmentation": True, "script": "t"} for k in built), built

    store = ti.open_store("zh")
    try:
        assert store.get_meta("build_sig") == "zh|reinforce=False|script=t"    # reinforce is retired
        assert store.get_cached_known(ti.known_signature(str(zh_library["known"]), "t")) is not None
    finally:
        store.close()


def test_indexer_as_is_keeps_the_pre_feature_signatures(zh_library):
    """No zh_script in settings.json (every existing install): nothing about the store changes."""
    _write_settings(reinforce_segmentation=False)
    _run_indexer(zh_library)
    store = ti.open_store("zh")
    try:
        assert store.get_meta("build_sig") == "zh|reinforce=False"
        assert store.get_cached_known(ti.known_signature(str(zh_library["known"]))) is not None
    finally:
        store.close()
