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
so its card is tagged `surasura::name` once made (`anki_miner.tag_names`). Grammar words are sent unless `connect_send_grammar` is off (✅ G0.3-2,
G1.3). A word that already has a card — in
Anki now, or in the backlog of the last sync when Anki is closed — is never sent: Anki Miner cuts media before it
checks for a duplicate.

The line (IS:256–268, ✅ P1.5-12): never a sung line; a line no other word of this batch took, unless there is no
other; a line with no other new word first; a written-out occurrence over a kana-only one; then the earliest. Its
start goes as written (seconds, millisecond precision), and `line_expansion` always: a line is finished when it ends in
。？！… or a closing bracket or quote; the next line is taken while this one runs on, the line before only when it runs
into this one, at most 2 each side, with gaps up to 2 s.

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

# UniDic's parts of speech
GRAMMAR = frozenset(("助詞", "助動詞", "感動詞", "連体詞", "接続詞"))     # IS-P9 (fillers are 感動詞,フィラー)
CONJUGATED = frozenset(("動詞", "形容詞", "助動詞"))                     # the card front by its dictionary form
_PROPER, _NUMBER = "固有名詞", "数詞"
_KANA_ONLY_POS = frozenset(("名詞", "代名詞", "副詞"))

_FINISHED = frozenset("。｡．.！？!?…‥")
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


def line_expansion(cues, at):
    """[before, after]: the lines Anki Miner adds to line `at` so the card holds the whole sentence (§ above)."""
    after, here = 0, at
    while after < SIDE and here + 1 < len(cues) and not finished(cues[here].text) \
            and cues[here + 1].start - cues[here].end <= GAP_MS:
        after, here = after + 1, here + 1
    before, here = 0, at
    while before < SIDE and here > 0 and not finished(cues[here - 1].text) \
            and cues[here].start - cues[here - 1].end <= GAP_MS:
        before, here = before + 1, here - 1
    return [before, after]


def card_front(token):
    """The word Anki Miner is named by (IS:234): a verb, adjective or helper verb by its dictionary form as the
    occurrence writes it (orthBase); anything else exactly as written (伯父さん, not おじさん; クソ, not くそ)."""
    node = token.node
    if node is not None and node.feature.pos1 in CONJUGATED:
        return node.feature.orthBase or token.orth
    return token.written


def front_reading(occurrence, key, language):
    """The reading the card front is said with on this line, in hiragana as Anki Miner writes readings — or None (Anki
    Miner then reads it itself). A set phrase: its row's reading (the dictionary's, キガツク); a word: its occurrence's
    dictionary-form kana (UniDic's kanaBase, as Anki Miner reads a front it finds itself: やっぱり, never its lemma's
    やはり; 言っ, いう); a joined word: the reading the join gives it (日本人, にほんじん). Chinese keeps none."""
    if language != "ja":
        return None
    from app import anki_match
    node = occurrence.token.node
    if not occurrence.phrase and node is None:
        return None
    reading = key[1] if occurrence.phrase else getattr(node.feature, "kanaBase", None)
    reading = reading if isinstance(reading, str) and reading not in ("", "*") else None
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
                found.append(_Occurrence(key, first.cue, front, written, phrase.display, first, True, ()))
    return found, new_in


def pick(cues, tokens, language, is_known, mode="list", listed=None, carded=None, carded_source="anki",
         ignore_names=False, send_grammar=True, skip_single=True, phrase_set=None, readable=None):
    """The words of one subtitle to make cards from, and why the rest of its new words aren't sent:
    {"words": [...], "not_offered": [...]} (row 1.3.3's shapes). `is_known((lemma, reading))`: known or ignored, by the
    analyzer's rule; `readable(key)`: a word read through known words (`analyzer.LearningView`), no new word in a line.
    `listed` ({(lemma, reading): list position}): the list's rows, for `list` (and the order of every mode: the list's
    first). `carded`: the card keys (a card's word, its kana fold) of the words with a card. A line's other new words
    are counted over what its card holds — the line and the lines its expansion adds (IS:268)."""
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

    spans = {}

    def span(at):
        """The lines a card cut from line `at` holds: the line and its expansion."""
        if at not in spans:
            before, after = line_expansion(cues, at)
            spans[at] = range(at - before, at + after + 1)
        return spans[at]

    def others(o):
        return len(set().union(*(new_in.get(c, ()) for c in span(o.cue))) - {o.key})

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
        elif (not send_grammar and not first.phrase and first.token.node is not None
              and first.token.node.feature.pos1 in GRAMMAR):
            reason = "grammar"
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
        best = min(usable, key=lambda o: (not taken.isdisjoint(span(o.cue)), others(o) > 0,
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
            "line_start": seconds(cue.start), "line_end": seconds(cue.end), "line_text": cue.text,
            "line_expansion": line_expansion(cues, best.cue),
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
