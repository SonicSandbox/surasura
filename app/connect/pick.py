"""Which of one subtitle's words become cards, and the line each is cut from (P1.3 row 1.3.3; the Integration Spec
§4.2, Sonic's G0.3-2, IS-R2, P1.5-12 and G1.6-3).

Surasura chooses the words, Anki Miner makes the cards: every word is named, with the line Surasura picked — never
Anki Miner's own selection. Word identity is Surasura's: a word is its (lemma, reading), keyed by the analyzer's own
tokenizers (`app/cues.py`), and a word only Surasura joins is sent whole (IS-R2).

Which words (`connect_mine_words`, Mado's *Words to make cards from*):
- `list`    — the episode's words on your Surasura list (the last Generate's), not known, with no card yet
- `unknown` — every word Surasura reads in the episode that you don't know (Surasura's reading, ✅ G0.3-6)
- `i1`      — only words with a line whose other words you all know
Names follow Surasura's own setting (G1.3, Sonic: "based on their setting in surasura"): sent unless Ignore names
(`logic.ignore_names`) is on — a name being whatever `names.name_lemma` says — and each name sent is marked (`name`)
so its card is tagged `surasura::name` once made (`anki_miner.tag_names`). Grammar words — and a grammar expression's row (かもしれない, として:
`phrases.Phrase.grammar`) — are sent unless `connect_send_grammar` is off (✅ G0.3-2, G1.3). A word that already has a card — in
Anki now, or in the backlog of the last sync when Anki is closed — is never sent: Anki Miner cuts media before it
checks for a duplicate.

The line (IS:256–268, ✅ P1.5-12): never a sung line; a line no other word of this batch took, unless there is no
other; a line with no other new word first; then one whose card the 8 s cap doesn't cut (else the shortest card); a
written-out occurrence over a kana-only one; then the earliest. Its start goes as written (seconds, millisecond
precision), and `line_expansion` always — the lines Anki Miner adds (card lines, Sonic 2026-11-09): the next line is
taken while this one runs on, the line before only when it runs into this one, at most 2 each side (a line's copies counting as it), with gaps up to
2 s, and never past 8 s from the first line's start to the last's end (the word's own line is never cut). Whether a
Japanese line runs on is its grammar (`Lines.runs_on`: its last word, from the analyzer's own tokens), not its
punctuation; but a card the punctuation rule (`finished`: 。？！… or a closing bracket or quote ends a line) makes in
4.5 s or less stays as it is, two speakers and all ("a pass between 2 characters"). A line shown again straight after
itself (the same text, touching times; another speaker's line at either copy's time may sit between) counts as the
line it repeats, and the card runs to its last copy, so the clip ends with the speech. Chinese keeps the punctuation
rule, capped. Lines are counted as Anki Miner counts them: since 3.10.1 it drops a line holding none of the
language's script (an English sign, a ♪～).

A book's or a text's line (Z-9, Michi-BS, Mattias's report 2026-11-12) is its sentence, 。！？ inside 「」 included —
Anki Miner's own unit is a whole 「…」 speech, and it cuts that unit to the sentence named only when it holds it exactly
(0xzerolight/anki_miner#148): so the sentence goes as the book writes it (`cues.reading`), a quote mark left alone at
either end dropped (`book_line`), and one within the learner's *Length* first (PROVISIONAL; never cut).

The card front (IS:233–236): a verb, adjective or helper verb by its dictionary form as written, anything else exactly
as written; Surasura's `Word` goes as a second entry when it differs and no word in the episode is written that way
(the homograph guard: 帰る's Word is 返る); never for a set phrase, whose front is the occurrence's own words with the
last in its dictionary form (`phrases.spellings`). An Anki Miner that makes a word from its line (3.7, Z-2) gets the
card front alone, with `surface` and `front_reading` (`runfile.entries`, `runfile.word_requests`).

Each word carries a predicted class (IS:247–255): why Anki Miner may not find it. A predicted miss is still sent: it
costs nothing (no media is cut for a word his parse doesn't hold), and a later Anki Miner may find it.

Pure: the caller hands in the cues, their words, what the learner knows and which words have cards. Nothing written.
"""
import os
import re
import unicodedata

from app import analyzer
from app.cues import seconds

MODES = ("list", "unknown", "i1")
SIDE = 2                # line_expansion: at most this many lines each side
GAP_MS = 2000           # ...across gaps up to this long
CAP_MS = 8000           # ...and never past this, first start to last end (Sonic: "8 second cap is wonderful")
PASS_MS = 4500          # a card the punctuation rule makes this short stays as it is ("a pass between 2 characters")
REPEAT_MS = 10          # a line shown again: the same text, starting at most this long after the copy before ends
                        # (Generate's own window, Kotoba-R: 83 ms is the streaming gap between a line said twice)

# UniDic's parts of speech
GRAMMAR = frozenset(("助詞", "助動詞", "感動詞", "連体詞", "接続詞"))     # IS-P9 (fillers are 感動詞,フィラー)
CONJUGATED = frozenset(("動詞", "形容詞", "助動詞"))                     # the card front by its dictionary form
_PROPER, _NUMBER = "固有名詞", "数詞"
_KANA_ONLY_POS = frozenset(("名詞", "代名詞", "副詞"))

_FINISHED = frozenset("。｡．.！？!?…‥")

# Card lines (rule 1): what a Japanese line's end says about the next line
_RUNS_ON_MARKS = frozenset("➡➨→⇒➔►―—、，,")        # an arrow, a dash, a comma: the sentence goes on
_CLOSERS = frozenset("＞>")                          # a narration's closing ＞ ends it, as 》 does
_QUOTES = dict(zip("「｢『（〔［｛〈《【([{｟〝", "」｣』）〕］｝〉》】)]}｠〟"))   # Anki Miner's bracket pairs (its splitter's)
_QUOTE_ENDS = frozenset(_QUOTES.values())
_RUN_ON_TAILS = ("とはいえ", "とはいっても", "ものの", "どころか", "かどで", "ながらも")
_EITHER_WAY = ("せよ", "しろ")        # にせよ / にしろ: concessive after a case particle に (何にしろ, あるにせよ), runs on;
                                      # after the copula's に (勝手にしろ, 静かにせよ) it is an order, and ends
_RUN_ON_PARTICLES = frozenset(("格助詞", "接続助詞", "係助詞", "副助詞", "準体助詞"))     # に を や は ばっかり …
_ENDING_PARTICLES = frozenset(("けど", "けれど", "けれども", "けども", "のに", "し", "もん", "もの", "って", "か",
                               "の", "から", "ので"))                     # said as a whole line (言いさし)
_REASONS = frozenset(("から", "ので"))
_POLITE = frozenset(("です", "ます"))                                   # ですから / ますから end the line…
_POLITE_STEMS = frozenset(("でし", "まし", "ませ"))                       # …as でしたから / ましたから / ませんから do
_NOUN_LINKS = frozenset(("ノチ", "アト", "ウチ", "タメ", "ホド"))          # 後 内 為 程 as nouns: のち あと うち ため ほど
_HAN = re.compile(f"[{analyzer.HAN}]")
_HIRAGANA_ONLY = re.compile(r"^[ぁ-ゟー]+$")
_KATAKANA_ONLY = re.compile(r"^[ァ-ヿー]+$")
_KANA_ONLY = re.compile(r"^[ぁ-ゟァ-ヿー]+$")

# Why a word of the episode isn't sent (`not_offered`), in plain words
REASONS = {
    "has-card": "already has a card in Anki",
    "in-backlog": "already has a card (your Anki backlog, from the last sync)",
    "name": "a name (Ignore names is on)",
    "grammar": "a grammar word (Send grammar words is off)",
    "sung": "said only in a song line",
}


def finished(text):
    """Does a subtitle line end its sentence: in 。？！…, or in a closing bracket or quote (IS:262)?"""
    text = (text or "").rstrip()
    return bool(text) and (text[-1] in _FINISHED or unicodedata.category(text[-1]) in ("Pe", "Pf"))


def book_line(text):
    """A book's or a text's sentence as its card names it (`line_text`): a quote mark the split left with no partner
    in it — at its start (「おれはこれから…好い。) or its end (…黙つてゐるのだぞ。」) — dropped, with the space it
    leaves; one inside it (…かな」蕗屋は…) and a whole quote (「…知れない。」) kept. It stays an exact piece of its
    paragraph: Anki Miner cuts its unit (a 「…」 speech is one) only around a sentence it holds exactly (Mattias's
    0xzerolight/anki_miner#148), so a partner added would bring the whole speech back. Nothing left: as it was."""
    text = text or ""
    stack, lone = [], set()
    for at, ch in enumerate(text):
        if ch in _QUOTES:
            stack.append(at)
        elif ch in _QUOTE_ENDS:
            if stack and _QUOTES[text[stack[-1]]] == ch:
                stack.pop()
            else:
                lone.add(at)
    lone.update(stack)
    lo, hi = 0, len(text)
    while lo < hi and lo in lone:
        lo += 1
    while hi > lo and hi - 1 in lone:
        hi -= 1
    return text[lo:hi].strip() or text


class Lines:
    """What `window` reads of one episode's lines: the lines Anki Miner has (`kept`, cue indices in order: a line
    holding the language's script — Anki Miner drops the rest since 3.10.1), and each Japanese line's words as the
    analyzer read them (`tokens`, `cues.tokens`'s: no second tagger pass), so its grammar says whether it runs on.
    `tokens` None: read here, for a caller with none of its own."""

    def __init__(self, cues, tokens=None, language="ja"):
        self.cues, self.language = cues, language
        self.kept = [i for i, cue in enumerate(cues) if analyzer.has_target_language(cue.text or "", language)]
        self.place = {cue: n for n, cue in enumerate(self.kept)}
        self._pieces = {}                   # cue -> [(surface, UniDic feature or None)], a joined word by its parts
        if language != "ja" or getattr(cues, "units", False):
            return
        if tokens is None:
            from app import cues as cue_reader
            tokens = cue_reader.tokens(cues, language)
        for token in tokens:
            node = token.node
            pieces = self._pieces.setdefault(token.cue, [])
            if node is None:
                pieces.append((token.surface, None))
            elif isinstance(node, analyzer.JoinedWord):
                pieces.extend(node.parts)
            else:
                pieces.append((node.surface, node.feature))

    def runs_on(self, at, forward=True):
        """Does Japanese line `at` run on into the line after it (`forward`), or into the line after it when that
        line is the card's (not `forward`: is it pulled in from before)? By its end (rule 1): it runs on at a て / で
        form, a 連用形 or 仮定形 (なら, ば, たら), a case / binding / adverbial particle (に を や は ばっかり), ず, an
        adverb after other words (ずっと; なるほど alone is a reply), an arrow, dash or comma, a tail (にせよ にしろ
        とはいえ … ながらも; 勝手にしろ is an order), the nouns のち あと うち ため ほど; a plain から / ので only
        forward, into its main clause (ですから, ましたから end; a reason is never pulled in from before). It ends at
        。？！…, a closing bracket or ＞, a sentence-final particle, a plain / polite / imperative / volitional form,
        a noun or a name, an interjection, and at けど けれど し もん もの って か
        の. のに runs on (PROVISIONAL): UniDic reads it as の + に."""
        text = (self.cues[at].text or "").rstrip()
        if not text or finished(text) or text[-1] in _CLOSERS:
            return False
        if text[-1] in _RUNS_ON_MARKS or text.endswith(_RUN_ON_TAILS):
            return True
        pieces = self._pieces.get(at) or []
        if not pieces or pieces[-1][1] is None:
            return False                    # no word the tagger read: nothing says it runs on
        surface, f = pieces[-1]
        before = [piece[0] for piece in pieces[:-1]]
        if surface in _EITHER_WAY and before[-1:] == ["に"]:
            return pieces[-2][1] is not None and pieces[-2][1].pos2 == "格助詞"
        if surface == "で" and before[-1:] == ["の"]:      # UniDic reads ので after ます as の + で
            surface, before = "ので", before[:-1]
        if surface == "ので" or (surface == "から" and f.pos2 == "接続助詞"):
            polite = bool(before) and (before[-1] in _POLITE or (len(before) > 1 and before[-2] in _POLITE_STEMS))
            return forward and not polite
        if f.pos1 == "助詞":
            if surface in _ENDING_PARTICLES and f.pos2 != "格助詞":
                return False
            return f.pos2 in _RUN_ON_PARTICLES
        if f.pos1 == "助動詞" and surface == "ず":
            return True
        if f.pos1 in CONJUGATED:
            return (f.cForm or "").startswith(("連用形", "仮定形"))
        if f.pos1 == "副詞":
            return bool(before)
        return f.pos1 == "名詞" and f.kanaBase in _NOUN_LINKS


def _spread(cues, kept, lo, hi):
    """Milliseconds from the earliest start to the latest end of Anki Miner's lines `kept[lo..hi]` (its window: the
    least start and the greatest end, as an .ass file's events needn't be in time order)."""
    held = [cues[i] for i in kept[lo:hi + 1]]
    return max(cue.end for cue in held) - min(cue.start for cue in held)


def _copy(cues, kept, earlier, later):
    """Is Anki Miner's line `kept[later]` its line `kept[earlier]` shown again: the same text, starting at most
    REPEAT_MS after it ends (and not before it starts), each line between them at one copy's time (another speaker's
    line, shown beside one of them)?"""
    a, b = cues[kept[earlier]], cues[kept[later]]
    if a.text != b.text or b.start < a.start or b.start - a.end > REPEAT_MS:
        return False
    return all((cues[i].start, cues[i].end) in ((a.start, a.end), (b.start, b.end)) for i in kept[earlier + 1:later])


def _last_copy(cues, kept, n, fits=lambda hi: True):
    """The last copy of Anki Miner's line `kept[n]` shown straight after it (`n` itself when none), while
    `fits(copy)`."""
    moved = True
    while moved:
        moved = False
        for later in range(n + 1, min(n + SIDE + 2, len(kept))):
            if _copy(cues, kept, n, later):
                if fits(later):
                    n, moved = later, True
                break
    return n


def _first_copy(cues, kept, n, fits=lambda lo: True):
    """The line Anki Miner's line `kept[n]` shows again, back to its first showing (`n` itself when none), while
    `fits(copy)`."""
    moved = True
    while moved:
        moved = False
        for earlier in range(n - 1, max(n - SIDE - 2, -1), -1):
            if _copy(cues, kept, earlier, n):
                if fits(earlier):
                    n, moved = earlier, True
                break
    return n


def _next_to(cues, earlier, later):
    """Are lines `earlier` and `later` (cue indices, in the file's order) next to each other in time: the later
    starting at most GAP_MS after it ends and at most GAP_MS before it starts (an .ass file's events needn't be in
    time order: two shown together are neighbours, a line said a minute away never is)?"""
    a, b = cues[earlier], cues[later]
    return b.start >= a.start - GAP_MS and b.start - a.end <= GAP_MS


def _ended(text):
    """Does a line end its sentence and run on only by an arrow or a dash after it (a TV caption's 。➡: the same
    speaker's next sentence follows)?"""
    text = (text or "").rstrip()
    bare = text.rstrip("".join(_RUNS_ON_MARKS - {"、", "，", ","}))
    return bare != text and finished(bare)


def _walk(cues, kept, n, runs_on, cap, repeats):
    """(lo, hi, cut): the card cut from Anki Miner's line `kept[n]` holds its lines `kept[lo..hi]`. `runs_on(cue,
    forward)` says whether a line runs on; the lines after first (Anki Miner adds those first too), then the lines
    before, at most SIDE a side; `repeats`: a line's copies count as that line (`_copy`), its grammar its first copy's
    (a later copy may hold no words). `cap`: the longest card in ms (None: none). Under it the word's own sentence
    comes first: a line past a sentence's end (`_ended`, a TV caption's 。➡ — the speaker's next or last sentence) is
    added only once the sentence is in, while it fits; `cut` True when the cap left the word's own sentence short."""
    cap = float("inf") if cap is None else cap
    at = {"lo": n, "hi": n, "after": 0, "before": 0}
    if repeats:                             # the word's line with its copies, as many as fit (the line itself always)
        at["lo"] = _first_copy(cues, kept, n, lambda lo: _spread(cues, kept, lo, n) <= cap)
        at["hi"] = _last_copy(cues, kept, n, lambda hi: _spread(cues, kept, at["lo"], hi) <= cap)
    short = repeats and (_first_copy(cues, kept, n) != at["lo"] or _last_copy(cues, kept, n) != at["hi"])
    at["judged"] = at["lo"]

    def ahead(own):
        """Add the lines after while the last runs on (`own`: within the word's sentence); False when the cap cut."""
        while at["after"] < SIDE and at["hi"] + 1 < len(kept) and runs_on(kept[at["judged"]], True) \
                and _next_to(cues, kept[at["hi"]], kept[at["hi"] + 1]):
            if own and _ended(cues[kept[at["judged"]]].text):
                return True
            reach = _last_copy(cues, kept, at["hi"] + 1) if repeats else at["hi"] + 1
            if _spread(cues, kept, at["lo"], reach) > cap:
                return False
            at.update(judged=at["hi"] + 1, hi=reach, after=at["after"] + 1)
        return True

    def behind(own):
        """Add the lines before while each runs into the next; False when the cap cut."""
        while at["before"] < SIDE and at["lo"] > 0 and _next_to(cues, kept[at["lo"] - 1], kept[at["lo"]]):
            reach = _first_copy(cues, kept, at["lo"] - 1) if repeats else at["lo"] - 1
            if not runs_on(kept[reach], False) or (own and _ended(cues[kept[reach]].text)):
                return True
            if _spread(cues, kept, reach, at["hi"]) > cap:
                return False
            at.update(lo=reach, before=at["before"] + 1)
        return True

    cut = not ahead(own=True) or short
    cut = not behind(own=True) or cut
    if not cut:                             # the sentence is in: its neighbours by the same speaker, while they fit
        ahead(own=False)
        behind(own=False)
    return at["lo"], at["hi"], cut


def window(cues, at, lines=None):
    """(before, after, cut, ms): the lines Anki Miner adds to line `at` so the card holds the whole sentence (§
    above), counted in Anki Miner's lines (`Lines.kept`); whether the 8 s cap cut that sentence short; the card's
    length. A book's or a text's cue is a whole sentence already (`cues.reading`, Z-9): none."""
    if getattr(cues, "units", False):
        return 0, 0, False, 0
    lines = lines if lines is not None else Lines(cues)      # Japanese, read here: for a caller with no Lines
    kept, n = lines.kept, lines.place.get(at)
    if n is None:                           # a line Anki Miner doesn't have (no script of the language)
        return 0, 0, False, max(cues[at].end - cues[at].start, 0)
    punctuated = lambda cue, forward: not finished(cues[cue].text)      # noqa: E731 — the rule before grammar
    if lines.language == "ja":
        lo, hi, cut = _walk(cues, kept, n, punctuated, None, False)
        if _spread(cues, kept, lo, hi) > PASS_MS:
            lo, hi, cut = _walk(cues, kept, n, lines.runs_on, CAP_MS, True)
        else:                               # the pass as it is, but ending with the speech: its ends' copies too
            lo = _first_copy(cues, kept, lo, lambda a: _spread(cues, kept, a, hi) <= CAP_MS)
            hi = _last_copy(cues, kept, hi, lambda b: _spread(cues, kept, lo, b) <= CAP_MS)
    else:
        lo, hi, cut = _walk(cues, kept, n, punctuated, CAP_MS, False)
    return n - lo, hi - n, cut, _spread(cues, kept, lo, hi)


def line_expansion(cues, at, lines=None):
    """[before, after]: the lines Anki Miner adds to line `at` so the card holds the whole sentence (`window`)."""
    before, after, _cut, _ms = window(cues, at, lines)
    return [before, after]


def _by_lemma(token):
    """A verb or adjective form UniDic reads as another word's (its lemma's reading isn't its own dictionary form's):
    a potential, ra-nuki or classical form — 行ける, 辿り着ける, 来れる, 美しき. Anki Miner folds these to the lemma too
    (`morphology.mining_base`), so the card is the lemma's (P1.3-AM37 review #3)."""
    node = token.node
    f = node.feature if node is not None else None
    return (f is not None and f.pos1 in ("動詞", "形容詞") and bool(token.lemma) and bool(f.lForm)
            and bool(f.kanaBase) and f.kanaBase != "*" and f.lForm != f.kanaBase)


def card_front(token):
    """The word Anki Miner is named by (IS:234): a verb, adjective or helper verb by its dictionary form as the
    occurrence writes it (orthBase) — by its lemma where that form is another word's (`_by_lemma`: 行ける → 行く);
    anything else exactly as written (伯父さん, not おじさん; クソ, not くそ) — as the tagger reads it (`analyzer.tagger_text`:
    ﾗｲﾌﾞﾊｳｽ is ライブハウス), for Anki Miner asks its dictionary for the front as named (laptop round 5: a half-width
    name found its line and no definition); the file's own spelling goes as `surface`."""
    node = token.node
    if node is not None and node.feature.pos1 in CONJUGATED:
        return token.lemma if _by_lemma(token) else node.feature.orthBase or token.orth
    return analyzer.tagger_text(token.written)[0]


# The everyday reading of a front UniDic reads otherwise: 日本 is ニッポン in UniDic, にほん as people say it (and as
# Anki Miner 3.11 reads it; the only place name where the two differed, Michi-RD 2026-11-09).
EVERYDAY = {"日本": "にほん"}


def front_reading(occurrence, key, language):
    """The reading the card front is said with on this line, in hiragana as Anki Miner writes readings — or None (Anki
    Miner then reads it itself). The reading of the front as the line writes it (Sonic, 2026-11-09: option A), by the
    journey's own rule for a set phrase (`plan_rules.display_reading`: kana as written, kanji as the dictionary reads
    them, so the card and the journey's Kana agree): from its row's reading (the dictionary's: キガツク; いい感じ is
    いいかんじ, not its row's よいかんじ), never the tagger's kana (気に入る is きにいる, not キニハイル). A word written in
    kana alone: itself (`plan_rules.kana_as_written`: それじゃあ, not its lemma's それじゃ; もん, not もの; not an iteration mark's
    こゝろ, which keeps こころ). Any other word: its occurrence's
    dictionary-form kana (UniDic's kanaBase, as Anki Miner reads a front it finds itself: 言っ, いう), or the lemma's
    where the front is the lemma (行ける, いく); a joined word: the reading the join gives it (日本人, にほんじん). A name
    keeps its reading (立川, たちかわ); 日本 is にほん (`EVERYDAY`). Chinese keeps none."""
    if language != "ja":
        return None
    from app import anki_match, plan_rules
    if occurrence.front in EVERYDAY:
        return EVERYDAY[occurrence.front]
    node = occurrence.token.node
    if not occurrence.phrase and node is None:
        return None
    as_written = None if occurrence.phrase else plan_rules.kana_as_written(occurrence.front)
    if as_written:
        return anki_match.fold_kana(as_written)         # the line's own kana, voicing too (いつもどおり's どおり)
    by_lemma = occurrence.phrase or _by_lemma(occurrence.token)
    reading = key[1] if by_lemma else getattr(node.feature, "kanaBase", None)
    reading = reading if isinstance(reading, str) and reading not in ("", "*") else None
    if reading and occurrence.phrase:
        reading = plan_rules.display_reading(occurrence.front, occurrence.phrase.display, reading)
    return anki_match.fold_kana(reading) if reading else None


def predicted_class(token, phrase=False, neighbours=()):
    """Why Anki Miner may miss this occurrence (IS:142–152), from its own tokens — or None. Japanese only."""
    if phrase:
        return "IS-P5"
    node = token.node
    if node is None:
        return None
    f = node.feature
    if f.pos1 in GRAMMAR:
        return "IS-P9"
    if f.pos2 == _PROPER or _is_name(node):
        return "IS-P2"
    if isinstance(node, analyzer.JoinedWord):
        head = node.parts[0][1]
        if head.pos2 in (_PROPER, _NUMBER):
            return "IS-P4"
        return "IS-P5"
    surface = token.surface
    if f.pos1 in _KANA_ONLY_POS and _HIRAGANA_ONLY.match(surface):
        return "IS-P1"
    if _KATAKANA_ONLY.match(surface):
        if f.pos1 == "副詞" and (len(surface) <= 3 or surface.endswith("ッ")):
            return "IS-P1"
        if any(n is not None and _KATAKANA_ONLY.match(n) for n in neighbours):
            return "IS-P1"          # a katakana piece touching more katakana
    return None


def _is_name(node):
    try:
        from app import names
        return names.name_lemma(node, analyzer._sanitize_term) is not None
    except Exception:
        return False


def _written_out(surface, lemma):
    """A written-out occurrence (kanji) of a word that has one: 1; a kana-only one of such a word: 0 (IS-P1)."""
    return 0 if _HAN.search(lemma) and not _HAN.search(surface) else 1


class _Occurrence:
    __slots__ = ("key", "cue", "front", "surface", "orth", "token", "phrase", "neighbours")

    def __init__(self, key, cue, front, surface, orth, token, phrase, neighbours):
        self.key, self.cue, self.front, self.surface, self.orth = key, cue, front, surface, orth
        self.token, self.phrase, self.neighbours = token, phrase, neighbours


def _sentences(tokens):
    """[(sentence text, [token index])]: the tokens grouped by the sentence they were read in (a sentence may run
    across cues), in the order first met."""
    out = {}
    for i, token in enumerate(tokens):
        out.setdefault(id(token.sentence), (token.sentence, []))[1].append(i)
    return list(out.values())


def occurrences(cues, tokens, language, is_known, skip_single=True, phrase_set=None, readable=None,
                ignore_names=False):
    """Every use of a word the learner may be offered, in order, and each cue's new words: ([_Occurrence],
    {cue: {key}}). A word counts as the analyzer counts it — its script, a one-character word only where the list can
    offer it (`analyzer.unoffered`) — and a set phrase (Japanese, `phrase_set`) is an occurrence of its row. A new word
    is one the learner neither knows nor reads through known words (`readable`: `analyzer.LearningView`'s, the one
    learning rule), nor a name while Ignore names is on."""
    found, new_in = [], {}
    for text, at in _sentences(tokens):
        sentence = [tokens[i][:4] for i in at]
        skip = analyzer.unoffered(text or "", sentence) if language == "ja" and skip_single else ()
        for k, i in enumerate(at):
            token = tokens[i]
            key, cue = (token.lemma, token.reading), token.cue
            if k in skip or not token.lemma or not analyzer.has_target_language(token.lemma + token.surface, language):
                continue
            neighbours = (tokens[i - 1].surface if i > 0 and tokens[i - 1].cue == cue else None,
                          tokens[i + 1].surface if i + 1 < len(tokens) and tokens[i + 1].cue == cue else None)
            found.append(_Occurrence(key, cue, card_front(token), token.written, token.orth, token, False, neighbours))
            if not is_known(key) and not (readable is not None and readable(key)) \
                    and not (ignore_names and token.node is not None and _is_name(token.node)):
                new_in.setdefault(cue, set()).add(key)
        if phrase_set is not None and language == "ja":
            from app import phrases
            for start, end, index in phrase_set.find(sentence, text or ""):
                phrase = phrase_set.entry(index)
                front, written = phrases.spellings(sentence, start, end, phrase)
                key, first = (phrase.word, phrase.reading), tokens[at[start]]
                found.append(_Occurrence(key, first.cue, front, written, phrase.display, first, phrase, ()))
    return found, new_in


def pick(cues, tokens, language, is_known, mode="list", listed=None, carded=None, carded_source="anki",
         ignore_names=False, send_grammar=True, skip_single=True, phrase_set=None, readable=None, sentence_length=None):
    """The words of one subtitle to make cards from, and why the rest of its new words aren't sent:
    {"words": [...], "not_offered": [...]} (row 1.3.3's shapes). `is_known((lemma, reading))`: known or ignored, by the
    analyzer's rule; `readable(key)`: a word read through known words (`analyzer.LearningView`), no new word in a line.
    `listed` ({(lemma, reading): list position}): the list's rows, for `list` (and the order of every mode: the list's
    first). `carded`: the card keys (a card's word, its kana fold) of the words with a card. A line's other new words
    are counted over what its card holds — the line and the lines its expansion adds (IS:268).

    A book's or a text's sentences (`cues.units`, Michi-BS): each word's `line_text` is `book_line`'s, and
    `sentence_length` ((min, preferred max, never longer than) characters: the learner's *Length* and *Never longer
    than*, logic.context min_chars / preferred_max_chars / max_chars; PROVISIONAL lean, 2026-11-12: cards honour them
    too) ranks its sentences (`length`) where the 8 s cap ranks a video's lines — a preference only, never cut, a word
    with only sentences outside it still sent. A video's lines never read it."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    found, new_in = occurrences(cues, tokens, language, is_known, skip_single, phrase_set, readable, ignore_names)
    listed = listed or {}
    carded = carded or set()
    # The homograph guard: every way a word of the episode can be named — as written, its dictionary form as written
    # (Anki Miner's card front, which it matches first) and its spelling. Word named a second time where any of them
    # is Word would cut a second card from that occurrence (帰る's Word 返る, the card front of 返って on another line)
    spelled = {name for o in found for name in (o.front, o.orth, o.surface)}

    by_key = {}                                     # key -> its uses, keys in the order first met
    for o in found:
        by_key.setdefault(o.key, []).append(o)
    met = {key: n for n, key in enumerate(by_key)}

    lines = Lines(cues, tokens, language)
    cards = {}

    def card(at):
        """A card cut from line `at`: (the cues it holds — the line and its expansion —, [before, after], whether the
        cap cut it, its length in ms)."""
        if at not in cards:
            before, after, cut, ms = window(cues, at, lines)
            n = lines.place.get(at)
            held = lines.kept[n - before:n + after + 1] if n is not None else [at]
            cards[at] = (held, [before, after], cut, ms)
        return cards[at]

    def span(at):
        """The lines a card cut from line `at` holds."""
        return card(at)[0]

    def fits(at):
        """Does the card cut from line `at` hold its whole sentence within the cap (rule 4)?"""
        return not card(at)[2] and card(at)[3] <= CAP_MS

    def others(o):
        return len(set().union(*(new_in.get(c, ()) for c in span(o.cue))) - {o.key})

    units = bool(getattr(cues, "units", False))

    def length(at):
        """A book's sentence against the learner's Length (`sentence_length`: (min, preferred max, never longer than)
        characters) -> (past the cap, too short, too long): inside it first, then longer up to the cap, then shorter,
        then past the cap — the report's examples' order (a sentence past max_chars is only ever a word's fallback);
        (0, 0, 0) for a video's line or with no Length handed in. Based on the approach in #372 by Mattias."""
        if not units or not sentence_length:
            return (0, 0, 0)
        low, high, cap = sentence_length
        n = len(book_line(cues[at].text))
        return (int(bool(cap) and n > cap), int(n < low), int(n > high))

    candidates = []
    for key, uses in by_key.items():
        phrase = uses[0].phrase
        if is_known(key) or (phrase and key not in listed):
            continue
        if mode == "list" and key not in listed:
            continue
        if mode == "i1" and not any(others(o) == 0 and not cues[o.cue].sung for o in uses):
            continue
        candidates.append(key)
    candidates.sort(key=lambda k: (listed.get(k, len(listed)), met[k]))

    words, not_offered, taken = [], [], set()
    from app import anki_match
    for key in candidates:
        uses = by_key[key]
        first = uses[0]
        reason = None
        name = language == "ja" and not first.phrase and first.token.node is not None and _is_name(first.token.node)
        if name and ignore_names:
            reason = "name"
        elif not send_grammar and (first.phrase.grammar if first.phrase else (
                first.token.node is not None and first.token.node.feature.pos1 in GRAMMAR)):
            reason = "grammar"      # a grammar word, or a grammar expression's row (かもしれない: phrases.Phrase.grammar)
        if reason is None:
            spellings = {first.front, key[0], first.orth, first.surface}
            spellings |= {anki_match.fold_kana(s) for s in spellings if s} if language == "ja" else set()
            if not carded.isdisjoint(spellings):
                reason = "has-card" if carded_source == "anki" else "in-backlog"
        usable = [o for o in uses if not cues[o.cue].sung and (mode != "i1" or others(o) == 0)]
        if reason is None and not usable:
            reason = "sung"
        if reason is not None:
            not_offered.append({"word": key[0], "reading": key[1], "orth": first.orth, "reason": reason,
                                "why": REASONS[reason]})
            continue
        # a line no other word took; no other new word; a card that fits the cap uncut (else the shortest); written out
        best = min(usable, key=lambda o: (not taken.isdisjoint(span(o.cue)), others(o) > 0, not fits(o.cue),
                                          length(o.cue), 0 if fits(o.cue) else card(o.cue)[3],
                                          -_written_out(o.surface, key[0]), others(o), o.cue))
        taken.update(span(best.cue))
        cue = cues[best.cue]
        sent = [best.front]
        if (language == "ja" and not best.phrase and key[0] != best.front and key[0] not in spelled):
            sent.append(key[0])     # Surasura's Word as well, where no word here is written so (IS:235)
        words.append({
            "word": key[0], "reading": key[1], "orth": best.orth, "surface": best.surface, "sent": sent,
            "front_reading": front_reading(best, key, language),
            "kind": "phrase" if best.phrase else "word", "name": bool(name),
            "line_start": seconds(cue.start), "line_end": seconds(cue.end),
            "line_text": book_line(cue.text) if units else cue.text,
            "line_expansion": list(card(best.cue)[1]),
            "predicted_class": (predicted_class(best.token, best.phrase, best.neighbours) if language == "ja"
                                else None),
            "other_new": others(best),
        })
    return {"words": words, "not_offered": not_offered}


def carded(language, settings, decks=()):
    """(card keys, where they came from) — every word that has a card, as a card's word and its kana fold: from Anki
    itself when it answers ("anki": the known sync's decks and `decks`, suspended cards too — a card is a card), else
    from the backlog the last sync saved ("backlog"). Read-only on Anki. Only the notes no sync has read yet are
    fetched: the known words' (KnownWord.json names their notes) and the backlog's are keyed already."""
    from app import anki_connect, anki_sync
    saved = anki_sync.load_backlog(language).get("notes")
    saved = saved if isinstance(saved, dict) else {}
    keys = set(anki_sync.backlog_keys(language))
    scope = [d for d in list((settings.get("anki_sync_decks") or {}).get(language) or []) + list(decks) if d]
    fields = list((settings.get("anki_sync_fields") or {}).get(language) or [])
    url = anki_connect.address(settings)
    if not scope or os.environ.get("SURASURA_NO_ANKI_SYNC") or not anki_connect.probe(url, timeout=2).get("ok"):
        return keys, "backlog"
    try:
        query = " OR ".join(f'deck:"{anki_connect.escape_query(d)}"' for d in dict.fromkeys(scope))
        ids = anki_connect.find_notes(url, f"({query})")
        # Anki answers: only cards still there count — a card deleted since the last sync no longer blocks its word
        live = {str(n) for n in ids}
        keys = {str(k) for n, entry in saved.items() if n in live and isinstance(entry, dict)
                for k in entry.get("keys") or () if k}
        read = set(saved)
        try:
            _data, words = anki_sync._read_known_file(language)
        except anki_sync._KnownFileError:
            words = None
        read |= {str(w.get("ankiNoteId")) for w in words or () if isinstance(w, dict) and w.get("ankiNoteId")}
        todo = [n for n in ids if str(n) not in read]
        for note in anki_connect.notes_info(url, todo) if todo else ():
            entry = anki_sync._backlog_entry(note, fields, language)
            if entry is not None:
                keys.update(entry["keys"])
    except anki_connect.AnkiError:
        return keys, "backlog"
    return keys, "anki"
