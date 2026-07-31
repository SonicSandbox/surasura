"""Display-side trimming of runaway example sentences.

A word's OWN sentence is deliberately exempt from `logic.context.max_chars` (analyzer.py keeps
`first_context` as a fallback so every word has an example), so an unpunctuated speech transcript
can put a 400-character run-on on a card. The report now WINDOWS such a sentence around the target
word for display, with ellipses on whichever side was cut.

Two layers here:
  1. `test_*_template*` — asserts the wiring straight from the templates (repo convention, see
     test_web_app_render_fixes.py), so a future edit can't silently drop the trim at one of the
     four render sites.
  2. `test_trim_*` — exercises a Python MIRROR of the template's `trimContext` against the real
     runaway transcript in Test Resources, pinning the invariants the windowing must hold.

The stored sentence is untouched: the CSV, exports and the deep-link anchor all keep the full text
(covered by test_context_length_cap.py and test_deep_link_anchors.py).
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_APP = os.path.join(ROOT, "templates", "web_app.html")
ZEN_APP = os.path.join(ROOT, "templates", "zen_app.html")
RUNAWAY = os.path.join(ROOT, "tests", "Test Resources", "ja", "runaway_transcript.txt")

CAP = 150  # logic.context.max_chars default


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _runaway():
    return _read(RUNAWAY).strip()


# --- Mirror of trimContext() in templates/web_app.html + zen_app.html -------------------------
# Kept deliberately line-for-line with the JS so the invariants below describe what actually ships.
# Known benign divergence: JS lengths/indices are UTF-16 code units, so a sentence containing
# non-BMP kanji (e.g. 𠮟) yields a window a couple of units shorter there. Everything is measured
# in the same units within each implementation, so the word is still fully inside the window.
BREAKS = "、。！？!?,.　・ "


def trim_context(text, word, cap):
    if not text or len(text) <= cap:
        return {"text": text or "", "trimmed": False}

    at, word_len = 0, 0
    if word:
        m = re.search(re.escape(word), text, re.IGNORECASE)
        if m:
            at, word_len = m.start(), len(m.group(0))

    clauses, cur = [], ""
    for ch in text:
        cur += ch
        if ch in BREAKS:
            clauses.append(cur)
            cur = ""
    if cur:
        clauses.append(cur)

    k, pos = 0, 0
    for i, c in enumerate(clauses):
        if pos + len(c) > at:
            k = i
            break
        pos += len(c)

    lo = hi = k
    total = len(clauses[k])
    while True:
        grew = False
        if hi + 1 < len(clauses) and total + len(clauses[hi + 1]) <= cap:
            hi += 1
            total += len(clauses[hi])
            grew = True
        if lo - 1 >= 0 and total + len(clauses[lo - 1]) <= cap:
            lo -= 1
            total += len(clauses[lo])
            grew = True
        if not grew:
            break

    body = "".join(clauses[lo:hi + 1]).strip()
    head, tail = lo > 0, hi < len(clauses) - 1

    if len(body) > cap:
        start = max(0, at - max(0, cap - word_len) // 2)
        end = min(len(text), max(start + cap, at + word_len))
        start = max(0, min(start, end - cap))
        body = text[start:end].strip()
        head, tail = start > 0, end < len(text)

    return {"text": ("…" if head else "") + body + ("…" if tail else ""), "trimmed": True}


# --- Template wiring --------------------------------------------------------------------------

def test_both_templates_define_the_trim_helper():
    for path in (WEB_APP, ZEN_APP):
        html = _read(path)
        assert "function trimContext(text, word, cap)" in html, f"{path} lost trimContext"
        # The cap is read from the SAME setting that governs candidate exclusion, not hardcoded.
        assert "globalLogic.context" in html and "max_chars" in html, f"{path} must read the cap from settings"


def test_web_app_trims_at_every_render_site():
    html = _read(WEB_APP)
    # Context 1 on the full card, the lazily-loaded extra contexts, and the compact sentence row.
    assert "trimContext(c1Full, word, ctxCap)" in html, "Context 1 must be trimmed"
    assert "trimContext(data[k], word, ctxCap)" in html, "extra contexts must be trimmed"
    assert "trimContext(contextFull, data.Word, contextCap())" in html, "compact rows must be trimmed"
    # The old untrimmed forms must not come back.
    assert "const displayC1 = formatContext(c1Full)" not in html


def test_zen_mode_trims_its_contexts():
    html = _read(ZEN_APP)
    assert "trimContext(c.text, data.Word, zenCap)" in html


def test_audio_reads_what_is_displayed_not_the_runaway_original():
    """The Listen button must speak the windowed sentence, not 400 characters of transcript."""
    html = _read(WEB_APP)
    assert "const audioSource = escapeHtml(c1 || word);" in html
    # c1 is the TRIMMED text (c1Full is the original), so audio follows the display.
    assert "const c1 = c1Trim.text;" in html


def test_full_sentence_stays_reachable_on_hover_when_trimmed():
    """Nothing is hidden: a windowed sentence carries the untrimmed original in its title."""
    web = _read(WEB_APP)
    assert "c1Trim.trimmed ? ` title=\"${escapeHtml(c1Full)}\"` : ''" in web
    assert '<div class="context-box"${c1Title}>' in web
    zen = _read(ZEN_APP)
    assert "t.trimmed ? ` title=\"${escapeHtml(c.text)}\"` : ''" in zen


# --- Windowing behaviour on the real runaway transcript ---------------------------------------

def test_the_resource_is_actually_a_runaway_sentence():
    """Guards the fixture itself — if it were short, every assertion below would vacuously pass."""
    text = _runaway()
    assert len(text) > 2 * CAP, f"resource must exceed 2x the cap to be representative, got {len(text)}"
    assert text.count("。") == 1, "it is genuinely ONE sentence — that's why the cap can't split it"


def test_short_sentence_is_returned_untouched():
    short = "電車に乗る。"
    out = trim_context(short, "電車", CAP)
    assert out["text"] == short
    assert out["trimmed"] is False
    assert "…" not in out["text"]


def test_empty_context_is_safe():
    """Words can arrive with a missing context column; trimming must not throw."""
    for empty in ("", None):
        out = trim_context(empty, "電車", CAP)
        assert out["text"] == ""
        assert out["trimmed"] is False


def test_window_contains_the_word_and_respects_the_cap():
    """The whole point: the learner must still see the word they're studying."""
    text = _runaway()
    for word in ("今日", "資本主義", "暗黙", "親髄"):
        out = trim_context(text, word, CAP)
        assert out["trimmed"] is True, f"{word}: a {len(text)}-char sentence must be trimmed"
        assert word in out["text"], f"{word}: trimmed window lost the target word"
        # Cap + the two ellipses; the clause-boundary snap only ever shortens.
        assert len(out["text"]) <= CAP + 2, f"{word}: window is {len(out['text'])} chars, over the cap"


def test_ellipses_mark_only_the_sides_actually_cut():
    text = _runaway()

    # 親髄 opens the sentence -> nothing cut on the left, so no leading ellipsis.
    head = trim_context(text, "親髄", CAP)
    assert not head["text"].startswith("…")
    assert head["text"].endswith("…")

    # 言うんだろう closes it -> nothing cut on the right.
    tail = trim_context(text, "言うんだろう", CAP)
    assert tail["text"].startswith("…")
    assert not tail["text"].endswith("…")

    # A word in the middle is cut on both sides.
    mid = trim_context(text, "資本主義", CAP)
    assert mid["text"].startswith("…") and mid["text"].endswith("…")


def test_every_cut_lands_on_a_clause_boundary():
    """Japanese speech is comma-dense. A raw character slice produced "…の中には" (cutting 世の中 in
    half); building the window out of whole clauses is what fixed that."""
    text = _runaway()
    for word in ("今日", "資本主義", "暗黙", "虚務感"):
        body = trim_context(text, word, CAP)["text"].strip("…")
        idx = text.index(body)
        if idx > 0:
            assert text[idx - 1] in BREAKS, f"{word}: left cut is mid-phrase, not on a clause boundary"
        end = idx + len(body)
        if end < len(text):
            assert text[end - 1] in BREAKS, f"{word}: right cut is mid-phrase, not on a clause boundary"


def test_unpunctuated_run_on_still_gets_capped():
    """Degenerate case the clause walk can't solve: a transcript with NO punctuation is one giant
    clause, so it must fall back to a hard character window rather than flood the card."""
    text = "私" * 200 + "資本主義" + "私" * 200  # no 、 or 。 anywhere
    out = trim_context(text, "資本主義", CAP)
    assert out["trimmed"] is True
    assert "資本主義" in out["text"]
    assert len(out["text"]) <= CAP + 2
    assert out["text"].startswith("…") and out["text"].endswith("…")


def test_falls_back_to_the_head_when_the_lemma_never_surfaces():
    """A lemma can differ from the inflected surface form (見える vs 見えた) — never throw, never
    return an empty window; just show the start of the sentence."""
    text = _runaway()
    out = trim_context(text, "存在しない語", CAP)
    assert out["trimmed"] is True
    assert text.startswith(out["text"].rstrip("…"))
    assert out["text"].endswith("…")
    assert not out["text"].startswith("…")


def test_word_longer_than_the_cap_is_still_shown_whole():
    """Degenerate but real: a very long compound must not be sliced in half by the window."""
    long_word = "資本主義的な世界"
    text = _runaway()
    out = trim_context(text, long_word, len(long_word) - 4)
    assert long_word in out["text"], "the window must never cut through the target word"
