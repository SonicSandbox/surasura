"""The second random audit's small kinds (cases_ja_audit.py, JA-AUD-010 … 023) — each rule judged here before it is
built (lane AF, 2026-09-30).

    dash-stretch         a run of dashes (─ ━ ― —) right before a kana that never begins a word — a small kana, っ / ッ,
                         ん / ン — is a stretched vowel inside the word, read as one ー as a run of ー is (STRETCH-MARKS):
                         ジャ─────ック, 衛兵さ───ん, いくぞ──ッ. Anywhere else it is a dash between two words
                         (それは──あなたの, メイド──ラム), as the library writes it ~650 times in 700. After katakana only a
                         katakana one: サテラ──って starts the next word (a hiragana っ / ん opens the particles って / んだ).
    interjection-pieces  two fillers the tagger cut, each one kana (a mark aside): ま + あ, あ + あ～, い + え — the
                         pair read alone as ONE interjection or adverb the dictionary knows is that word (まあ, ああ, いえ);
                         a pair that reads otherwise alone stays (ま + え in したまえ, う + え in うえ～ん).
    repeated-sound       a katakana word the dictionary lacks that is one sound said three times or more (ハァハァハァ):
                         the word the tagger reads that sound said twice as, alone, when it is a sound word — an adverb or
                         an interjection (はあはあ) — shown as written.
    dash-no-word         dash punctuation (Unicode's Pd: －, 〜, ―, —) is never a word, though UniDic reads － as から,
                         対, マイナス or 引く and 〜 as から by context.

Each patches the function where the app looks it up, so every caller — the tokenizer, the known words, U9's
see-through, the sentence dictionary, パターン — reads text through it.

BUILT 2026-09-30 (lane AF) as DASH-STRETCH, FILLER-PIECES, REPEATED-SOUNDS and DASH-NOT-A-WORD (decisions_ja_audit.py),
with dash-stretch narrowed first: read wherever a kana follows (as ～ is), it changed 112 library sentences, 5 of them
for the worse (何──ッ → 何 + つ, かも──って → 持って); as written here, 3, all better. interjection-pieces was narrowed to
UniDic's fillers (two whole interjections, あー + あー, stay) and built taking 〜 as a filler's mark too (え〜). Kept as the
record of what was judged: on the built code each changes nothing.
"""
import re

from app import analyzer, names
from app.unicode_ranges import HAN, KANA_LETTERS
from tests.parsing.harness import patched
from tests.parsing.variants import after_join, variant

# --- dash-stretch ------------------------------------------------------------------------------------------------ #
_DASHES = frozenset("─━―—")
_KATAKANA_LETTER = "ァ-ヺヽ-ヿ"
_SMALL_KATAKANA = "ァィゥェォッャュョヮヵヶ"
_RUN = "[ー〜─━―—]*[─━―—][ー〜─━―—]*"
# Inside a word: before a final ん / ン (さ───ん, う────ん, ド────ン), or between katakana letters where the word goes on
# after a ッ, a small kana or ン (ジャ─────ック). A final ッ is the catch that ends a shout (いくぞ──ッ, 何──ッ): there the
# dash stays a dash, as before ん / っ that go on in hiragana (──んだ, ──って).
_DASH_STRETCH_RE = re.compile(f"(?<=[{KANA_LETTERS}{HAN}]){_RUN}(?=[んン](?![{KANA_LETTERS}]))"
                              f"|(?<=[{_KATAKANA_LETTER}]){_RUN}(?=[{_SMALL_KATAKANA}ン][{_KATAKANA_LETTER}])")


def _dash_stretched(text):
    return (analyzer_stretched(text)
            or (("─" in text or "━" in text or "―" in text or "—" in text) and _DASH_STRETCH_RE.search(text) is not None))


analyzer_stretched = analyzer._stretched


def _dash_stretches(groups):
    """_stretches, with a run holding a dash read as one ー only where _DASH_STRETCH_RE finds it."""
    out, i, n = [], 0, len(groups)
    marks = analyzer._STRETCH_MARKS | _DASHES
    while i < n:
        j = i
        while j < n and groups[j][2] in marks:
            j += 1
        if i < j < n and out and analyzer._STRETCH_BEFORE.match(out[-1][2][-1]):
            run = "".join(groups[k][2] for k in range(i, j))
            if _DASHES.isdisjoint(run):
                ok = analyzer._STRETCH_AFTER.match(groups[j][2]) is not None
            else:
                after = "".join(g[2] for g in groups[j:j + 3])[:2]
                ok = _DASH_STRETCH_RE.match(out[-1][2][-1] + run + after, 1) is not None
            if ok:
                out.append([groups[i][0], groups[j - 1][1], "ー"])
                i = j
                continue
        out.append(groups[i])
        i += 1
    return out


@variant("dash-stretch",
         "A run of dashes (─ ━ ― —) inside a word is a stretched vowel, read as one ー: before a final ん / ン (衛兵さ───ん) "
         "or between katakana letters where the word goes on after a ッ, a small kana or ン (ジャ─────ック); "
         "elsewhere a dash between words.")
def _dash_stretch():
    global analyzer_stretched
    analyzer_stretched = analyzer._stretched
    with patched(analyzer, "_MARKS_RE", re.compile("[ー〜─━―—]")),             patched(analyzer, "_stretched", _dash_stretched),             patched(analyzer, "_stretches", _dash_stretches):
        yield


# --- interjection-pieces ----------------------------------------------------------------------------------------- #
_ONE_KANA = re.compile(f"^[{KANA_LETTERS}][ー〜]*$")
_SOUND_WORDS = frozenset(("感動詞", "副詞"))


def _sound_word(spelling):
    """The tagger's feature for `spelling` read alone when it is ONE interjection or adverb it knows, else None."""
    whole = names._read_whole(spelling)
    return whole if whole is not None and whole.pos1 in _SOUND_WORDS else None


def _interjection_pieces(words):
    out, i, n = [], 0, len(words)
    while i < n:
        w = words[i]
        if i + 1 < n:
            v = words[i + 1]
            if (w.feature.pos2 == "フィラー" and v.feature.pos2 == "フィラー" and not getattr(v, "white_space", "")
                    and _ONE_KANA.match(analyzer._read(w)) and _ONE_KANA.match(analyzer._read(v))):
                spelling = analyzer._read(w) + analyzer._read(v)
                whole = _sound_word(spelling) or _sound_word(spelling.replace("ー", "").replace("〜", ""))
                if whole is not None:
                    out.append(analyzer.JoinedWord(w.surface + v.surface, whole,
                                                   ((w.surface, w.feature), (v.surface, v.feature)),
                                                   getattr(w, "white_space", "")))
                    i += 2
                    continue
        out.append(w)
        i += 1
    return out


@variant("interjection-pieces",
         "Two interjections the tagger cut, each one kana (ま + あ, あ + あ～, い + え), are the interjection or adverb "
         "the pair reads as alone (まあ, ああ, いえ) — when it reads as one such word alone.")
def _interjections():
    with after_join(_interjection_pieces):
        yield


# --- repeated-sound ---------------------------------------------------------------------------------------------- #
def _unit(text):
    """The unit `text` (less a final ッ or ー) writes three times or more, else None."""
    spelling = text.rstrip("ッー")
    n = len(spelling)
    for k in range(1, n // 3 + 1):
        if n % k == 0 and spelling == spelling[:k] * (n // k):
            return spelling[:k]
    return None


_KATAKANA_WORD = re.compile("^[ァ-ヺー-ヿ]+$")


def _repeated_sounds(words):
    out = None
    for k, w in enumerate(words):
        if not w.is_unk:
            continue
        text = analyzer._read(w)
        unit = _KATAKANA_WORD.match(text) and _unit(text)
        whole = _sound_word(unit * 2) if unit else None
        if whole is None:
            continue
        if out is None:
            out = list(words)
        out[k] = analyzer.JoinedWord(w.surface, whole, ((w.surface, w.feature),), getattr(w, "white_space", ""))
    return words if out is None else out


@variant("repeated-sound",
         "A katakana word the dictionary lacks that says one sound three times or more (ハァハァハァ) is the sound word "
         "the tagger reads that sound said twice as alone (はあはあ), shown as written.")
def _repeated():
    with after_join(_repeated_sounds):
        yield


# --- dash-no-word ------------------------------------------------------------------------------------------------ #
_PD = frozenset(chr(c) for c in range(0x10000) if __import__("unicodedata").category(chr(c)) == "Pd")


@variant("dash-no-word",
         "Dash punctuation (Unicode Pd: －, 〜, ―, —) is never a word: UniDic reads － as から / 対 / マイナス / 引く and 〜 "
         "as から by context.")
def _dash_no_word():
    real = analyzer.word_lemma

    def word_lemma(word):
        text = analyzer._read(word)
        if text and text[0] in _PD and _PD.issuperset(text):
            return None
        return real(word)
    with patched(analyzer, "word_lemma", word_lemma):
        yield
