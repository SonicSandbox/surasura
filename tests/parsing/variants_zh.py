"""Prototype segmentation choices for Chinese (scope P6) — the two open jieba decisions, each a patch of how the app
calls jieba, for the run. Nothing in app/ or modules/ changes.

    zh-hmm-off               jieba.cut with HMM=False wherever the app cuts (the analyzer's tokenizer and
                             patterns_zh, whose contract is to cut exactly as the analyzer does) — ZH-HMM
    zh-asis-via-simplified   the analyzer's as-is tokenizer segments the text's Simplified form and emits the text as
                             written (conversion is length-preserving, zh_script I3) — ZH-TRAD-ASIS

The zh porter measured both with one-line jieba.cut patches (HMM off: fixes 16, breaks 6; as-is through
Simplified: fixes 7, breaks 0 — debug/parsing_suite/PORTING_NOTES.md). Here the second is scoped to the as-is
tokenizer, where the decision lives (s / t already segment through Simplified; パターン's cut is its own contract).
"""
from app import analyzer, zh_script
from tests.parsing.harness import patched
from tests.parsing.variants import variant


@variant("zh-hmm-off",
         "jieba's HMM off: jieba.cut(..., HMM=False) everywhere the app cuts — no guessed words (他来, 我要 stay two), "
         "names and words missing from jieba's dictionary split (ZH-HMM).")
def _zh_hmm_off():
    import jieba
    real = jieba.cut

    def cut(sentence, cut_all=False, HMM=True, use_paddle=False):
        return real(sentence, cut_all=cut_all, HMM=False, use_paddle=use_paddle)
    with patched(jieba, "cut", cut):
        yield


@variant("zh-asis-via-simplified",
         "As-is Chinese segmented through Simplified: the default as-is tokenizer cuts the text's Simplified form and "
         "emits the text as written (為什麼 one word, not 為 / 什麼) — ZH-TRAD-ASIS, against I2's byte-identical as-is.")
def _zh_asis_via_simplified():
    import jieba
    real_cut, real_sentences = jieba.cut, analyzer.ChineseTokenizer.tokenize_sentences

    def via_simplified(sentence, *args, **kwargs):
        pos = 0
        for word in real_cut(zh_script.to_simplified(sentence), *args, **kwargs):
            yield sentence[pos:pos + len(word)]
            pos += len(word)

    def tokenize_sentences(self, text):
        if self.script != "asis":
            return real_sentences(self, text)
        with patched(jieba, "cut", via_simplified):          # the as-is branch's one jieba.cut, while it runs
            return iter(list(real_sentences(self, text)))
    with patched(analyzer.ChineseTokenizer, "tokenize_sentences", tokenize_sentences):
        yield
