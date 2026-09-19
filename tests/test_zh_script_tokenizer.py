"""WP-Z2: the Chinese tokenizer's `script`, and the caches that must follow a script switch.

Spec: docs/agent instructions/Chinese_Script_Conversion_Spec.md (§5.3, §7, gotchas 2-5).

- As-is must be byte-for-byte what the tokenizer produced BEFORE this feature (I2). It is compared
  against a golden file generated from the committed analyzer, not against a re-implementation.
- `s` / `t` emit single-script tokens, segment in Simplified (which is what repairs Traditional
  segmentation: 經濟關|係 as-is, 經濟|關係 under `t`), and merge a word across scripts.
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

def test_asis_tokenization_is_byte_identical_to_before_the_feature(zh_resources_dir, monkeypatch):
    """I2. The golden holds the pre-feature tokenizer's full output (sentences AND token tuples) for
    both files, under the sentence boundaries it was generated with."""
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


def test_t_segments_traditional_text_better_than_as_is():
    """jieba's dictionary is Simplified only, so Traditional text as-is splits 經濟關係 into 經濟關|係.
    Segmenting the Simplified copy fixes that for free (spec §5.3)."""
    text = "經濟關係的發展很重要。"
    assert "關係" not in _words(text, "asis")
    assert _words(text, "t")[:2] == ["經濟", "關係"]


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
    (("zh", True), "zh|reinforce=True"),
    (("zh", False, "asis"), "zh|reinforce=False"),
    (("zh", False, "s"), "zh|reinforce=False|script=s"),
    (("zh", True, "t"), "zh|reinforce=True|script=t"),
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
        assert store.get_meta("build_sig") == "zh|reinforce=True|script=t"
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
