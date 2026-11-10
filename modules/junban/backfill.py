# SPDX-License-Identifier: GPL-3.0-or-later
"""Anki Backfill — fill fields on the user's Anki notes from what Surasura knows (Patterns_Spec.md §17).

    probe -> read the notes in scope -> PREVIEW -> Fill        (and, if it went wrong, Restore)

One window (`backfill_gui.py`, reached from the Anki window and from 順) and one automatic step
(`auto.py`) drive this. Two fills today — パターン, and 例文, one more sentence with the word from the
user's own library; a later fill is one more entry in `FILLS` and a branch of `Session.value` — the
preview, the snapshot, Restore and the automatic step are shared.

Five rules, each for a reason:

* **One field per fill, through `updateNoteFields`, never a card value** (P1). A note type with no
  field mapped to a fill is skipped, never given one (P3).
* **Empty fields only, unless the user ticks Replace** (D6, amended 2026-09-24). The snapshot keeps
  what was there, so Restore puts it back.
* **A new card whose word the user already knows is skipped** — the cards 順 files as "known", by 順's
  own test (`reposition.is_known_word`). Every other card is filled, studied or not (the user,
  2026-09-24: "everything except for the backlogged cards that state 'known'").
* **The automatic run touches new cards only, and only empty fields — by construction.** It asks Anki
  for `is:new` notes, then re-checks every card of every note before planning, and the planner drops
  Replace on its own when `auto` is set; no setting can widen any of the three (`run_auto`).
* **The snapshot reaches disk before the first write** — `User Files/<lang>/junban_backfill_undo.json`,
  its own file, so a fill and a reorder never overwrite each other's way back. Restore reverts only a
  field that still holds exactly what was written, and says how many the user has edited since.

Everything that reads Anki reads it in batches (`findNotes` per note type in one `multi`, then
`notesInfo` / `cardsInfo` 250 at a time) and only for the note types a fill can write to, so a
collection of other note types costs a count, not a download. The databases, the tagger and the
known words are loaded once per `Session` and shared by a preview and the fill that follows it.

The library's own パターン set is built again in the background as the library grows (`rebuild_in_background`, the
user, 2026-10-01): written beside the set in use and put in when nothing holds it, so a preview, a fill or a Generate
never waits for it.
"""

import csv
import difflib
import html
import os
import re
import subprocess
import sys
import threading
from collections import Counter, namedtuple

from app import anki_connect
from app.anki_connect import AnkiError
from app.path_utils import list_reader
from app.unicode_ranges import KANA_LETTERS
from modules.junban import ankiconnect, first_touch, match, pairs, reposition, touchup, undo

# One fill: what it writes, and how the window offers it — `tip` on its tick box, and `help` behind its
# "?": a title and short sections (a header, one plain line, an example), written for a 12-year-old
# (the user, 2026-09-24). `fields` are the field names it maps to on its own (case aside); a note type
# with none of them waits for the user to pick one. `languages` are the sessions it is offered in —
# Chinese since 2026-09-25 (Patterns_Chinese_Spec.md WP-Z9), each note type filled only in its own
# language (`note_language`). A later fill is one more entry here.
Fill = namedtuple("Fill", "key label tip fields languages help")

FILLS = (
    Fill("patterns", "パターン", "How the word is used, in a few short lines.",
         ("Patterns", "パターン", "Pattern"), ("ja", "zh"),
         ("パターン — how this word is used", (
             ("Particles", "Little words right before or after it. The % is how often.",
              "影響 → 〜を 31%   (影響を与える)"),
             ("Forms", "How the word itself changes when people use it.",
              "囲む → 囲まれる 62%   (to be surrounded)"),
             ("Word pairs", "Words that often go with it.", "目 → 目を覚ます · 目の前"),
             ("Frames", "What often goes around it. 〜 is the word.", "探検 → 〜家 · 〜隊"),
             ("書き言葉", "Used mostly in writing, not in talking.", "設立 · 当初"),
             ("● ○", "Where the lines came from.",
              "no dot: everyday talk · ●: talk and writing · ○: your library")))),
    # Only a field named for it is found on its own — on Lapis, `ExampleSentences`, added for it with
    # the card's 例文 toggle (Anki_Card_Layout_Spec §5); anything else, the user picks.
    Fill("sentence", "例文", "Two more sentences with the word, from your own library.",
         ("ExampleSentences", "例文", "ExampleSentence", "Example Sentences", "Example Sentence"), ("ja", "zh"),
         ("例文 — two more sentences with this word", (
             ("Easy to read", "From your own shows and books. You know every other word in them.",
              "冒険 → 明日から冒険に出かけよう。"),
             ("Never the same", "Not your card's own sentence, or one almost like it.",
              "冒険が始まった！ ≈ 冒険が始まった。 → skipped"),
             ("None that easy?", "Then fewer, or none. An empty field beats a hard sentence.",
              "One easy sentence → just that one."),
             ("On the card", "Hidden under the 例文 toggle, next to 翻訳.",
              "Tap 例文 to see them.")))),
)
FILL_KEYS = tuple(fill.key for fill in FILLS)

# 例文: how many sentences a card gets; how many words besides the card's own may be ones the learner
# doesn't know (0: the user's "all known words, i+1 where the unknown word is the expression", 2026-09-24);
# and how alike two sentences may be before one counts as the other ("or one with even an 80% match").
SENTENCES_PER_CARD = 2
EASY_OTHERS = 0
SAME_SENTENCE = 0.8
# A field line shorter than this is a word or a reading, not a sentence to keep apart from.
SENTENCE_MIN = 8

# The Chinese window's "?" (Patterns_Chinese_Spec.md §6.7) — the same shape as each Fill's `help`, with
# the gate's real output (WP-Z6). No 书面语 line: Chinese has no register in v1.
HELP_ZH = {
    "patterns": ("パターン — how this word is used", (
        ("Measure words", "The counting word that goes before it. The % is how often.", "书 → 本〜 94%   (一本书)"),
        ("Little words before it", "The word that says who or what it is done with.",
         "结婚 → 与〜 38% · 和〜 23%   (和她结婚)"),
        ("Forms", "How the word itself changes when people use it.", "买 → 买了 21% · 贵 → 太贵 18%"),
        ("Word pairs", "Words that often go with it.", "电话 → 打电话 · 接到电话"),
        ("Frames", "What often goes around it. 〜 is the word.", "桌子 → 〜上 · 〜下面"))),
    "sentence": ("例文 — two more sentences with this word", (
        ("Easy to read", "From your own shows and books. You know every other word in them.",
         "冒险 → 我们需要去寻找新的冒险。"),
        ("Never the same", "Not your card's own sentence, or one almost like it.", "冒险很难。 ≈ 冒险很难！ → skipped"),
        ("None that easy?", "Then fewer, or none. An empty field beats a hard sentence.",
         "One easy sentence → just that one."),
        ("On the card", "In the field you chose for it.", "Your note type decides where it shows."))),
}

CARDS = ("all", "new")          # "all" = every card but the new ones whose word you know
SKIP = ""                       # a mapping the user set to "don't fill this note type"
LANGUAGES = ("ja", "zh")        # what a note type can be set to (`junban_backfill_note_languages`)
# Kana letters — hiragana and katakana syllables, never the block's ・ or ー: Chinese writes a foreign name with
# ・ (约翰・列侬), and one such note made an unset Chinese note type Japanese (the S3 leak; 2.3 pre-build scan).
# The kana letters every Chinese test reads (app/unicode_ranges.py: the ChineseTokenizer's, パターン zh's).
_KANA = re.compile(f"[{KANA_LETTERS}]")
# The field a word's reading is read from, when the note type has one (Lapis: ExpressionReading).
READING_FIELDS = ("ExpressionReading", "Reading", "WordReading", "Word Reading", "読み")
REQUIRED_ACTIONS = ("updateNoteFields", "multi")


# --------------------------------------------------------------------------- #
# Settings, read defensively
# --------------------------------------------------------------------------- #
def _deck(settings):
    """`""` means every deck."""
    return str((settings or {}).get("junban_backfill_deck") or "").strip()


def _cards(settings):
    value = str((settings or {}).get("junban_backfill_cards") or "all").strip().lower()
    return value if value in CARDS else "all"


def _replace(settings):
    return (settings or {}).get("junban_backfill_replace") is True


def _fills(settings):
    """The fills ticked, in `FILLS` order. A setting that is not a list means the default: all."""
    chosen = (settings or {}).get("junban_backfill_fills")
    if not isinstance(chosen, (list, tuple)):
        return list(FILL_KEYS)
    return [key for key in FILL_KEYS if key in chosen]


def _field_map(settings):
    """`{fill: {note type: field}}`, COPIED — settings_manager merges module defaults shallowly, so
    the dict in loaded settings can be the one inside SETTINGS_DEFAULTS (Junban spec §13 #12)."""
    saved = (settings or {}).get("junban_backfill_fields")
    if not isinstance(saved, dict):
        return {}
    return {str(fill): dict(models) for fill, models in saved.items() if isinstance(models, dict)}


def mapped_field(fill, model, field_names, saved):
    """The field `fill` writes on note type `model` — the user's choice, else a field named like the
    fill (Patterns / パターン), else None: that note type is skipped. `saved` is `_field_map(...)`."""
    choice = (saved.get(fill.key) or {}).get(model)
    if choice == SKIP:
        return None
    if choice in field_names:
        return choice
    by_lower = {name.lower(): name for name in field_names}
    for name in fill.fields:
        if name.lower() in by_lower:
            return by_lower[name.lower()]
    return None


def help_for(fill, language):
    """The "?" behind `fill`, in the words of `language`'s lines: Japanese's is the fill's own `help`."""
    return HELP_ZH.get(fill.key, fill.help) if language == "zh" else fill.help


def _note_languages(settings):
    """`{note type: "ja" | "zh"}` as the user set them, COPIED (a container: §13 #12); anything else is
    not a setting."""
    saved = (settings or {}).get("junban_backfill_note_languages")
    if not isinstance(saved, dict):
        return {}
    return {str(model): lang for model, lang in saved.items() if lang in LANGUAGES}


def note_language(model, notes, settings):
    """A note type's language (D7): what the user set in the Fields window; else Japanese when most of its
    notes in scope — more than half — have kana in some field: every real Japanese note type does, Lapis in
    every sentence, while a Chinese deck with one stray の or ツ in it stays Chinese; else None, not set, and
    nothing of it is filled, by hand or automatically. Content cannot tell the languages apart word by word:
    two in three kanji-only Japanese words are Chinese words too (Z-F11)."""
    chosen = _note_languages(settings).get(model)
    if chosen:
        return chosen
    kana = sum(1 for note in notes
               if any(_KANA.search(value or "") for value in (note.get("fields") or {}).values()))
    if kana * 2 > len(notes):
        return "ja"
    return None


def _query(deck, cards):
    """The search for the notes in scope: one deck (and its subdecks) or all, new cards only or not."""
    scope = f'deck:"{anki_connect.escape_query(deck)}"' if deck else "deck:*"
    return scope + (" is:new" if cards == "new" else "")


# --------------------------------------------------------------------------- #
# What a preview and its fill share
# --------------------------------------------------------------------------- #
class Session:
    """The databases, one fugashi tagger and the known-words test — loaded once, used by a preview
    and by the fill that follows it — and the 例文 found so far. `close()` releases the databases."""

    def __init__(self, settings):
        self.language = reposition._language(settings)
        promote(self.language)          # a library set rebuilt in the background goes in before it is opened
        self.stores = []
        self.tokenize = None
        self.is_known = lambda word: False
        self.sentences = {}             # 例文: target -> [(others, text, surface, file)], best first
        self._looked_up = set()         # the targets already asked for, found or not
        self._words = None              # the analyzer's own tokenizer: a phrase as the store holds it
        self._list, self._answers = ({}, [], []), {}    # 例文's first key: the list Junban follows
        self.zh_script = (settings or {}).get("zh_script")      # a Chinese card's lines: its own script
        if self.language == "ja":
            from app import analyzer
            from modules.junban import patterns
            words = self._words = analyzer.JapaneseTokenizer()
            self.stores = patterns.open_sources(self.language)
            self.tokenize = patterns.tokenizer(tagger=words.tagger)
            self.is_known = reposition.known_test(self.language, settings, tokenizer=words)
            # 例文 looks a card up where Junban places it and the report labels it: the list Junban
            # follows (`junban_order`) and the user's answers to "Same word as one on your list?".
            self._list = list_index(reposition.order_csv_path(settings))
            self._answers = pairs.load(self.language)
        else:
            from modules.junban import patterns
            self.stores = patterns.open_sources(self.language)   # only this language's (S1, S2)
            self.is_known = reposition.known_test(self.language, settings)
            if self.language == "zh":
                # 例文 looks the word up as the token store holds it: the analyzer's own tokenizer, in
                # the user's script and segmentation (Patterns_Chinese_Spec.md §7).
                from app import analyzer
                self._words = analyzer.ChineseTokenizer(
                    reinforce_segmentation=(settings or {}).get("reinforce_segmentation") is True,
                    script=reposition._script(settings))

    def prepare(self, fill, notes, status=None, young=()):
        """Load what `fill` needs for `notes` before their values are asked for. 例文: ONE pass over
        the library for all their words (`sentence_corpus.best_for` — seconds on a big library), and
        only for words this session has not asked about yet; `young`, the words still being learned,
        puts sentences that practise them first among equally easy ones."""
        if fill.key != "sentence" or self._words is None:
            return
        targets = {self.sentence_key(note["word"]) for note in notes} - {None} - self._looked_up
        if targets:
            from app import sentence_corpus
            fresh = {key for key in map(self.sentence_key, young or ()) if isinstance(key, tuple)}
            phrases = {t: self._lemmas(t) for t in targets if isinstance(t, str)}
            # Among equally easy sentences, one that shows how the word is used (Patterns_Quality_Spec
            # Part D). Looked up here: 例文 runs before any パターン value, and may be ticked on its own.
            prefer = {}
            for note in notes:
                key = self.sentence_key(note["word"])
                if isinstance(key, tuple) and key in targets and key not in prefer:
                    runs = self._shown_runs(note["word"], note.get("reading") or "")
                    if self._grammar_off(note["word"]):
                        # お部屋, 俺たち, 優しさ are searched as their word; a sentence that shows the card's
                        # own form goes first among equally easy ones.
                        own = self._lemmas(note["word"])
                        runs = ([own] if len(own) > 1 else []) + [run for run in runs if run != own]
                    if runs:
                        prefer[key] = runs
            self.sentences.update(sentence_corpus.best_for(
                self.language, {t for t in targets if isinstance(t, tuple)}, progress=status,
                young=fresh, phrases=phrases, prefer=prefer))
            self._looked_up |= targets

    def _shown_runs(self, word, reading):
        """-> the runs of lemmas that show how `word` is used — its top pairing and its top form, from the
        first of its sources to have them (a cheap `lines_for`, the card's own sources) — as the token
        store holds them: through the analyzer's tokenizer, so a Chinese item (kept in Simplified) meets a
        library read in Traditional (啓示を受ける -> 啓示 を 受ける; 打电话 -> 打 電話)."""
        from modules.junban import patterns
        for _name, store in self.stores:
            if store is None:
                continue
            if self.language == "zh":
                from modules.junban import patterns_zh
                key, _reason = patterns_zh.resolve_key(word, store)
                bare = key[0] if key else ""
            else:
                key, _reason = patterns.resolve_key(word, reading, store, self.tokenize)
                bare = patterns._bare_word(word, self.tokenize)
            if key is None:
                continue
            lines = patterns.lines_for(store, *key)
            items = [lines[kind][0][0] for kind in ("colloc", "form") if lines.get(kind)]
            if items:
                return [run for run in (self._lemmas(item.replace("{w}", bare)) for item in items)
                        if len(run) > 1]
        return []

    def sentence_key(self, word):
        """What the library is searched for: the list row the card's word reaches, as Junban places the
        card and the report labels it (`_list_key`); else one word as the token store keys it, (lemma,
        reading) — written with its な / に / する or not (斬新な, 来日する) — or, for several (当事者,
        気を取り直す), the card's word itself, found as its run of lemmas (`_lemmas`). A word the dictionary
        keeps apart from the one it is read as (`match.two_words`: 心する is no 心, 揚げる no 上げる) or from the
        list row its spelling reaches (`_another_row`: 従兄 is no 従兄弟) is the card's word itself too: its run
        of lemmas, or — one word — the word as the card writes it (a lemma or a dictionary spelling the library
        writes so: 揚げる, never 上げる). None: no word. A Chinese word is keyed by the analyzer's own Chinese
        tokenizer: (the word in the user's script, "")."""
        from modules.junban import patterns
        if self.language == "zh":
            tokens = self._words.tokenize(word or "") if self._words else []
            if not tokens:
                return None                     # no Chinese in it (a word with kana is dropped: S4)
            from app.analyzer import chinese_verb   # 认真地 is 认真, 吃了 吃, as Junban places it (match.one_word)
            token = match.one_word(tokens, "zh", chinese_verb)
            return tuple(token[:2]) if token else word
        listed = self._list_key(word)
        if listed is not None:
            return listed
        tokens = self.tokenize(word or "") if self.tokenize else []
        bare = match.affixes_off(tokens, kana=bool(patterns._KANA_WORD.fullmatch(word or "")))   # お部屋: 部屋
        if len(bare) < len(tokens):
            tokens = bare
        elif tokens and (match.two_words(word, tokens[0][0]) or self._another_row(word)):
            return word                         # a word of its own: never the one it is read as
        if len(tokens) == 2 and patterns._is_attached(tokens[1]):
            tokens = tokens[:1]
        if not tokens:
            return None
        return tuple(tokens[0][:2]) if len(tokens) == 1 else word

    def _another_row(self, word):
        """Does the card of a word the learner does not know reach a list row only as another dictionary word's
        spelling — the row's Forms hold it, and the dictionary keeps the two apart (`match.another_word`: 従兄 in
        従兄弟's, 集い in 集う's)? A known card takes nothing from the list (`_list_key`), so never."""
        if self.is_known(word or ""):
            return False
        rank_of, words, orths = self._list
        key = match.lookup(word or "", rank_of, "ja")
        return bool(key) and match.another_word(word, key, rank_of, words, orths)

    def _grammar_off(self, word):
        """Does a Japanese card carry its word's own grammar — a polite お / ご, a plural, a さ / み
        (`match.affixes_off`)?"""
        from modules.junban import patterns
        tokens = self.tokenize(word or "") if self.tokenize else []
        return len(match.affixes_off(tokens, kana=bool(patterns._KANA_WORD.fullmatch(word or "")))) < len(tokens)

    def _list_key(self, word):
        """The list row a Japanese card's word reaches with no question asked — `match.card_key`: its
        exact keys, the user's "yes", one word + one ending — as the token store keys that row, (Word,
        Reading). One card, one key everywhere (2026-09-27): read alone, 従兄 is じゅうけい and 仕向け
        a noun, where Junban places them on 従兄弟 (いとこ) and 仕向ける. None when the list has no row for
        it — or when the learner knows the word, which Junban tests first: the list holds only the
        words not known, so a known card reaches another word's row (だいぶ the loanword ダイブ through
        the kana fold, 好き the verb 好く's Forms), and Backfill fills studied cards too. The word is then
        read on its own."""
        if self.is_known(word or ""):
            return None
        rank_of, words, orths = self._list
        tokenize = self._words.tokenize if self._words is not None else None
        key = match.card_key(word or "", rank_of, "ja", self._answers, tokenize, words, orths)[0]
        if not key or not 0 <= rank_of[key] < len(words):
            return None
        lemma, reading = words[rank_of[key]]
        return (lemma, reading) if lemma and reading else None

    def _lemmas(self, phrase):
        """A phrase as the token store holds it: the analyzer's lemmas of every token."""
        from app import analyzer
        analyzer.SANITIZE_JA = self.language == "ja"    # as the store was built (and every run sets it)
        return tuple(t[0] for _text, tokens in self._words.tokenize_sentences(phrase) for t in tokens)

    def value(self, fill, note, field):
        """-> (the new value of `note`'s `field` for `fill`, why not)."""
        if fill.key == "patterns":
            from modules.junban import patterns
            value, reason, _source = patterns.patterns_from_sources(note["word"], note["reading"],
                                                                    self.stores, self.tokenize,
                                                                    language=self.language, script=self.zh_script)
            return value, reason
        if fill.key == "sentence":
            return self._sentence(note, field)
        return "", "not available"

    def _sentence(self, note, field):
        """The easiest SENTENCES_PER_CARD sentences, one per line: none the card's own or like it, no
        two alike, and each from an episode not used yet when an equally good one is there (the user,
        2026-09-24: "we want variety")."""
        target = self.sentence_key(note["word"])
        if target is None:
            return "", "no word"
        found = self.sentences.get(target)
        if not found:
            return "", "no sentence"
        easy = [c for c in found if c[0] <= EASY_OTHERS]
        if not easy:
            return "", "not easy"
        own = _own_lines(note["fields"], skip=field)
        left = [c for c in easy if not _same_sentence(c[1], own)]
        chosen = []
        while left and len(chosen) < SENTENCES_PER_CARD:
            used = {c[3] for c in chosen}
            pick = next((c for c in left if c[3] not in used), left[0])
            chosen.append(pick)
            left = [c for c in left if c is not pick and not _same_sentence(c[1], [_bare(pick[1])])]
        if not chosen:
            return "", "the card's own"
        tagger = getattr(self._words, "tagger", None)          # Japanese's: a verse number goes
        return "<br>".join(_sentence_html(text, surface, tagger)
                           for _others, text, surface, _file in chosen), None

    def close(self):
        for _name, store in self.stores:
            if store is not None:
                store.close()
        self.stores = []


def list_index(path):
    """`(rank_of, words, orths)` — the list at `path` indexed exactly as Junban indexes it (`match.build_index`:
    Orth, Word, Forms, the kana fold, the one-character rule), each row's `(Word, Reading)` by rank, the key
    the token store holds that word under — what 例文 looks a card up by first — and each row's Orth, the
    spelling a card written so is that row's own by (`match.another_word`). `({}, [], [])` for a missing or
    unreadable list — a card is then read on its own, as before."""
    index = match.build_index(path, language="ja")
    if not index.rank_of:
        return {}, [], []
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            words = [(str(row.get("Word") or "").strip(), str(row.get("Reading") or "").strip())
                     for row in list_reader(handle)]
    except (OSError, UnicodeError, csv.Error):
        return {}, [], []
    return index.rank_of, words, index.orths


def _bare(text):
    """A sentence as compared: no markup, furigana or ruby (`match.normalize_word`), no punctuation or
    spaces — 冒険が始まった！ and <b>冒険</b>が始まった。 are one."""
    return re.sub(r"[\W_]+", "", match.normalize_word(text or ""))


def _own_lines(fields, skip=None):
    """The card's own sentences, bare: every line of every field but the one being filled (its old
    value never blocks writing the same again) — and not the word, its reading or a number."""
    lines = []
    for name, value in (fields or {}).items():
        if name == skip:
            continue
        for part in re.split(r"(?i)<br\s*/?>|\n", value or ""):
            bare = _bare(part)
            if len(bare) >= SENTENCE_MIN:
                lines.append(bare)
    return lines


def _same_sentence(text, own):
    """Is `text` one of the card's own sentences: the same, one inside the other (a clause of the
    card's line), or at least SAME_SENTENCE alike — difflib's cheap upper bounds first."""
    bare = _bare(text)
    for line in own:
        if bare in line or line in bare:
            return True
        matcher = difflib.SequenceMatcher(None, bare, line, autojunk=False)
        if (matcher.real_quick_ratio() >= SAME_SENTENCE and matcher.quick_ratio() >= SAME_SENTENCE
                and matcher.ratio() >= SAME_SENTENCE):
            return True
    return False


# What a library line can carry that a card should not show: subtitle markup (<>余は…</>), a
# scripture's footnote marks (門は①狭く), and a bracket whose other half is in another line (「前者の…。).
_MARKUP = re.compile(r"<[^<>]*>")
_FOOTNOTES = re.compile("[①-⑳]")
_BRACKETS = (("「", "」"), ("『", "』"), ("（", "）"), ("(", ")"))


def _sentence_html(text, surface, tagger=None):
    """The sentence as the field holds it: tidied (markup, footnote marks, a leading verse number —
    the analyzer's own `strip_verse_number` — and an unmatched bracket at either end), escaped, and the
    word in bold where it is written (the surface comes from that very sentence; not found as written,
    nothing is guessed)."""
    from app.sentence_corpus import _clean
    text = _FOOTNOTES.sub("", _MARKUP.sub("", _clean(text))).strip()
    if tagger is not None:
        from app.analyzer import strip_verse_number
        text = strip_verse_number(text, tagger)
    for opening, closing in _BRACKETS:
        if text.startswith(opening) and closing not in text:
            text = text[1:].lstrip()
        if text.endswith(closing) and opening not in text:
            text = text[:-1].rstrip()
    at = text.find(surface) if surface else -1
    if at < 0:
        return html.escape(text, quote=False)
    return (html.escape(text[:at], quote=False) + "<b>" + html.escape(surface, quote=False) + "</b>"
            + html.escape(text[at + len(surface):], quote=False))


# --------------------------------------------------------------------------- #
# Reading Anki
# --------------------------------------------------------------------------- #
def _multi_ids(url, queries):
    """One `multi` of `findNotes`; the ids per query (a failed slot is none)."""
    replies = anki_connect.multi([{"action": "findNotes", "params": {"query": q}} for q in queries], url)
    out = []
    for reply in replies:
        result = reply.get("result") if isinstance(reply, dict) else None
        out.append([i for i in result if isinstance(i, int)] if isinstance(result, list) else [])
    return out


def gather(url, settings):
    """Read the scope: every note type with notes in it, and the notes of those a fill can write to.

    Returns `{"models": {name: {"fields": [...], "count": n, "mapped": {fill: field or None},
    "language": "ja" | "zh" | None}}, "notes": [note]}` where each note is `{"id", "model", "word",
    "reading", "fields", "new"}` — `new` meaning every one of its cards is still unstudied
    (`type == 0`), the definition D2 uses and the automatic run re-checks. A note type of another
    language than the session's is counted and never planned: its notes are read only to learn its
    language (`note_language`), and dropped (Patterns_Chinese_Spec.md S3). Raises `AnkiError`."""
    deck, cards = _deck(settings), _cards(settings)
    saved, fills = _field_map(settings), [f for f in FILLS if f.key in _fills(settings)]
    languages = _note_languages(settings)
    names = [str(name) for name in anki_connect.invoke("modelNames", url) or []]
    replies = anki_connect.multi([{"action": "modelFieldNames", "params": {"modelName": name}}
                                  for name in names], url) if names else []
    fields_of = {}
    for name, reply in zip(names, replies):
        result = reply.get("result") if isinstance(reply, dict) else None
        fields_of[name] = [str(f) for f in result] if isinstance(result, list) else []

    scope = _query(deck, cards)
    counts = _multi_ids(url, [f'note:"{anki_connect.escape_query(name)}" {scope}' for name in names]) \
        if names else []
    models, wanted, fillable = {}, [], []
    for name, ids in zip(names, counts):
        if not ids:
            continue
        # Every fill's field, ticked or not — the window shows where each goes — but only a ticked
        # fill's note types are read.
        mapped = {fill.key: mapped_field(fill, name, fields_of[name], saved) for fill in FILLS}
        models[name] = {"fields": fields_of[name], "count": len(ids), "mapped": mapped,
                        "language": languages.get(name)}
        if any(mapped[fill.key] for fill in fills):
            wanted.extend(ids)
            fillable.append(name)

    notes = []
    if wanted:
        overrides = reposition._word_fields(settings)
        infos = ankiconnect.notes_info(url, wanted)
        # Which cards are still new: one `findCards … is:new` (ids only). `cardsInfo` would say the
        # same with every card's rendered HTML — 40 MB and 1.4 s of the user's 1,457 notes (measured
        # 2026-09-24), against 0.01 s for this. Anki's is:new is `type == 0`, suspended or not.
        kinds = " OR ".join(f'note:"{anki_connect.escape_query(name)}"' for name in fillable)
        new_cards = set(anki_connect.find_cards(url, f"({kinds}) {_query(deck, 'all')} is:new"))
        for note in infos:
            note_id = note.get("noteId")
            if not isinstance(note_id, int):
                continue
            values = reposition._note_values(note)
            own = [c for c in (note.get("cards") or []) if isinstance(c, int)]
            reading = next((values[f] for f in READING_FIELDS if values.get(f)), "")
            notes.append({"id": note_id, "model": note.get("modelName") or "",
                          "word": match.target_word(note, overrides, reposition._language(settings)),
                          "reading": match.normalize_word(reading),
                          "fields": values,
                          # A note with no card to check is NOT new: the automatic run must be able
                          # to prove a note is unstudied before it may touch it.
                          "new": bool(own) and all(c in new_cards for c in own)})
        by_model = {}
        for note in notes:
            by_model.setdefault(note["model"], []).append(note)
        for name in fillable:
            models[name]["language"] = note_language(name, by_model.get(name, []), settings)
        # The session's language, and the note types whose language is not set — the plan says
        # "Language?" for those — stay; another language's notes go.
        session = reposition._language(settings)
        notes = [note for note in notes if models[note["model"]]["language"] in (session, None)]
    young = set()
    if notes and any(fill.key == "sentence" for fill in fills):
        young = _young_words(url, reposition._word_fields(settings),
                             {note["id"]: note["word"] for note in notes}, session)
    return {"models": models, "notes": notes, "young": young}


def _young_words(url, overrides, seen, language=None):
    """The words of the cards the learner is still learning — studied, not suspended, and not mature
    yet (interval under 21 days, Anki's line) — across the collection: 例文 prefers sentences that
    practise them. Ids first (one `findCards`, one `cardsToNotes`); only notes not read already are
    read. `seen` is {note id: word} of the notes in scope."""
    cards = anki_connect.find_cards(url, "-is:new -is:suspended prop:ivl<21")
    if not cards:
        return set()
    note_ids = sorted({n for n in anki_connect.invoke("cardsToNotes", url, cards=cards) or []
                       if isinstance(n, int)})
    words = {seen[n] for n in note_ids if n in seen}
    missing = [n for n in note_ids if n not in seen]
    if missing:
        words.update(match.target_word(note, overrides, language)
                     for note in ankiconnect.notes_info(url, missing))
    return {word for word in words if word}


# --------------------------------------------------------------------------- #
# Planning (pure given the session)
# --------------------------------------------------------------------------- #
def plan(scope, session, settings, auto=False, status=None):
    """Decide every field write. Writes nothing. -> `{"edits", "rows", "counts", "by_fill"}`.

    `edits` is `{note_id: {field: {"before", "after"}}}` — the snapshot's own shape; `rows` is one
    `(note_id, word, field, action, value, fill key)` per note and fill for the preview, `action`
    "fill", "replace" or why not; `counts` tallies the actions, `by_fill` per fill.

    `auto` is the automatic run: new cards only and empty fields only, whatever `settings` say — the
    planner re-checks both itself, so a caller cannot widen them by mistake. `status` hears what a
    slow step is doing (the 例文 pass over the library)."""
    cards, replace = _cards(settings), _replace(settings) and not auto
    fills = [f for f in FILLS if f.key in _fills(settings)]
    models = scope.get("models") or {}
    edits, rows, counts = {}, [], Counter()
    by_fill = {fill.key: Counter() for fill in fills}
    decided = []                        # (note, fill, field, action) — no action yet: its value decides
    for note in scope.get("notes") or []:
        model = models.get(note["model"]) or {}
        mapped = model.get("mapped") or {}
        for fill in fills:
            field = mapped.get(fill.key)
            action = None
            if not field:
                action = "no field"
            elif model.get("language") is None:
                action = "language not set"             # never filled until the user says which
            elif model["language"] != session.language or session.language not in fill.languages:
                action = "language"
            elif session.language == "zh" and _KANA.search(note["word"] or ""):
                action = "language"                     # S4: a word with kana is never Chinese
            elif (auto or cards == "new") and not note["new"]:
                action = "studied"
            elif note["new"] and session.is_known(note["word"]):
                action = "known"
            elif (note["fields"].get(field) or "").strip() and not replace:
                action = "filled"
            decided.append((note, fill, field, action))
    for fill in fills:
        # What a fill needs is loaded once, for exactly the notes that will ask for it.
        session.prepare(fill, [note for note, of, _field, action in decided if of is fill and action is None],
                        status=status, young=scope.get("young") or ())
    for note, fill, field, action in decided:
        value = ""
        if action is None:
            before = note["fields"].get(field) or ""
            value, reason = session.value(fill, note, field)
            if not value:
                action = reason or "nothing to add"
            elif value == before:
                action = "unchanged"
            else:
                action = "replace" if before.strip() else "fill"
                edits.setdefault(note["id"], {})[field] = {"before": before, "after": value}
        counts[action] += 1
        by_fill[fill.key][action] += 1
        rows.append((note["id"], note["word"], field or "", action, value, fill.key))
    return {"edits": edits, "rows": rows, "counts": dict(counts),
            "by_fill": {key: dict(tally) for key, tally in by_fill.items()}}


# What the window calls each outcome — short, in the user's words. The lookup's own reasons come
# first ("too rare (7 < 12)" is shown as "too rare"), then the planner's.
REASONS = {"fill": "fill", "replace": "replace", "phrase": "phrases", "not found": "not found",
           "too rare": "too rare", "no pattern clears the floors": "nothing to show",
           "no word": "no word", "no database built": "no data yet", "not available": "not available",
           "no field": "no field", "language": "other language", "language not set": "Language?",
           "studied": "studied",
           "known": "known", "filled": "already filled", "unchanged": "unchanged",
           "no sentence": "no sentence", "not easy": "none easy", "the card's own": "only the card's"}


# What each label means, in a few plain words — behind the window's ⓘ.
REASON_HELP = {"replace": "Replace is ticked, so what's there is overwritten.",
               "phrases": "More than one word.", "not found": "Not in the texts Surasura read.",
               "too rare": "Seen too few times to say.", "nothing to show": "Seen, but nothing stands out.",
               "no word": "No word found on the card.", "no data yet": "Nothing built to fill from yet.",
               "not available": "Not for this card.", "no field": "No field chosen for its note type.",
               "other language": "Not for this language.",
               "Language?": "Its note type's language isn't set. Choose it under Fields….",
               "studied": "Studied already — New only is on.",
               "known": "New, but you already know the word.",
               "already filled": "Something's there. Tick Replace to overwrite.",
               "unchanged": "Already says this.",
               "no sentence": "No sentence of a good length in your library.",
               "none easy": "Every sentence has another word you don't know yet.",
               "only the card's": "The easy ones are all your card's own sentence."}


def reason(action):
    """The window's short label for an outcome — "too rare (7 < 12)" and "too rare (3 < 20)" are one."""
    group = action.split(" (", 1)[0]
    return REASONS.get(group, group)


def skipped(counts):
    """-> `[(label, n)]`, the most first: why the rest are left alone."""
    tally = Counter()
    for action, n in (counts or {}).items():
        if action not in ("fill", "replace"):
            tally[reason(action)] += n
    return tally.most_common()


def summary(result):
    """One line for the window: "Fill 1,066 notes · 391 skipped" — in notes, however many fills are
    ticked (a note skipped is one that gets nothing). The reasons are `skipped`'s, per fill, shown on
    demand (the user, 2026-09-24: "Fill notes, skipped, and that's it")."""
    written = len(result.get("edits") or {})
    left = len({row[0] for row in result.get("rows") or []}) - written
    head = f"Fill {written:,} note{'' if written == 1 else 's'}" if written else "Nothing to fill"
    return f"{head} · {left:,} skipped" if left else head


# --------------------------------------------------------------------------- #
# Preview, fill, restore
# --------------------------------------------------------------------------- #
def _url(settings):
    return reposition._url(settings)


def _report(ok, message, **extra):
    report = {"ok": ok, "message": message, "problems": [], "written": [], "failures": [],
              "skipped": 0, "snapshot": None}
    report.update(extra)
    return report


def preview(settings, session, status=None):
    """The dry run: `gather` + `plan`. Reads Anki; writes nothing, anywhere. Raises `AnkiError`."""
    scope = gather(_url(settings), settings)
    return {"scope": scope, **plan(scope, session, settings, status=status)}


def run(settings, session, planned=None, progress=None, auto=False, wait=0.0, cancel=None, on_wait=None,
        verb="Backfill"):
    """`_run`, holding the Anki-write lock from the first read to the last write (E1.4 §W): `wait` /
    `cancel` / `on_wait` say how long to wait for another writer; still held, or refused after the wait,
    it returns the usual refusal with `busy: True`. A previewed fill re-reads its notes inside the lock."""
    held, problem = anki_connect.take_writer(verb, _url(settings), wait, cancel, on_wait)
    if held is None:
        return _report(False, "Nothing was filled.", problems=[problem], busy=True)
    with held:
        return _run(settings, session, planned, progress, auto)


def _run(settings, session, planned=None, progress=None, auto=False):
    """Fill. Preflight, snapshot, write — in that order, always. Never raises.

    `planned` is the preview the user confirmed; each of its notes is re-read first and one whose
    field has changed since is left alone (counted in `skipped`). Without it (the automatic run) the
    scope is read and planned here."""
    url = _url(settings)
    language = session.language
    probe = anki_connect.probe(url, required=REQUIRED_ACTIONS)
    if not probe.get("ok"):
        return _report(False, "Nothing was filled.",
                       problems=[probe.get("error") or f"Could not reach Anki at {url}."])
    previous = undo.load(language, kind="backfill")
    if previous and previous.get("complete") is False:
        return _report(False, "Nothing was filled.",
                       problems=["The last fill did not finish. Press Restore first, then fill again."])
    unfinished = undo.unfinished(language, "backfill")         # one of Connect's fills (P1.4, §7.2)
    if unfinished is not None:
        return _report(False, "Nothing was filled.", unfinished=unfinished,
                       problems=["An automatic fill did not finish. Press Restore first, then fill again."])

    skipped = 0
    try:
        if planned is None:
            edits = plan(gather(url, settings), session, settings, auto=auto)["edits"]
        else:
            edits, skipped = _still_as_previewed(url, planned.get("edits") or {})
    except AnkiError as e:
        return _report(False, "Nothing was filled.", problems=[str(e)])
    if not edits:
        return _report(True, "Nothing to fill.", skipped=skipped)

    try:
        _note_fill(url, language, [_deck(settings) or "All decks"], edits)       # FT K8: this run's own edits
        snapshot = undo.save([], [_deck(settings) or "All decks"], language=language,
                             fields=undo.carry_forward_fields(previous, edits), kind="backfill")
    except OSError as e:
        return _report(False, "Nothing was filled.",
                       problems=[f"Could not save the undo file, so nothing was changed ({e})."])

    written, failures = [], []
    wire = touchup.edits_for_wire(edits)
    chunk = reposition._chunk_size(settings)
    ids = list(wire)
    for start in range(0, len(ids), chunk):
        batch = {note_id: wire[note_id] for note_id in ids[start:start + chunk]}
        done, failed = ankiconnect.update_notes(url, batch, chunk=chunk)
        written.extend(done)
        failures.extend(failed)
        if progress:
            progress(len(written) + len(failures), len(ids))
    if not failures:
        undo.mark_complete(language, kind="backfill")
    message = f"Filled {len(written)} note{'' if len(written) == 1 else 's'}."
    if failures:
        message = (f"Filled {len(written)} of {len(ids)} notes — {len(failures)} could not be "
                   "changed. What was there before is saved; Restore puts it back.")
    if skipped:
        message += f" {skipped} changed since the preview and were left alone."
    return _report(not failures, message, written=written, failures=failures, skipped=skipped,
                   snapshot=snapshot, problems=[reason for _id, reason in failures[:1]])


def _note_fill(url, language, deck, edits):
    """FT (D4, K8): the fields this fill writes, in the first-touch journal before the first write — with the open
    profile (one `getActiveProfile`, K1). Raises `OSError`: then nothing is filled."""
    first_touch.note(language, "backfill", first_touch.open_profile(url), deck, fields=edits)


def _still_as_previewed(url, edits):
    """`(edits, skipped)`: the previewed edits whose field still holds what the preview saw."""
    current = {}
    for note in ankiconnect.notes_info(url, [int(note_id) for note_id in edits]):
        if isinstance(note.get("noteId"), int):
            current[note["noteId"]] = reposition._note_values(note)
    kept, skipped = {}, 0
    for note_id, changes in edits.items():
        now = current.get(int(note_id))
        for field, change in changes.items():
            if now is not None and (now.get(field) or "") == change["before"]:
                kept.setdefault(int(note_id), {})[field] = change
            else:
                skipped += 1
    return kept, skipped


def run_auto(settings, wait=0.0, cancel=None, on_wait=None, verb=anki_connect.AUTOMATIC_STEP):
    """The automatic step (`auto.py`): new cards only, empty fields only — see the module docstring.
    Never raises; `(report, session)` is not kept, so each run loads what it needs and lets it go.
    It reaches Anki only through `run`, which takes the Anki-write lock (`wait` / `cancel` / `on_wait`
    passed through), so it takes nothing itself: a nested take never happens."""
    settings = dict(settings or {})
    settings["junban_backfill_cards"] = "new"
    settings["junban_backfill_replace"] = False
    session = None
    try:
        if "patterns" in _fills(settings):
            # Never waited for: a library outgrown since its set was built gets one again in the background, and
            # this fill uses the set in use (`rebuild_in_background`).
            rebuild_in_background(reposition._language(settings), settings.get("reinforce_segmentation") is True,
                                  when_grown=True)
        session = Session(settings)
        return run(settings, session, auto=True, wait=wait, cancel=cancel, on_wait=on_wait, verb=verb)
    except Exception as e:              # a background job must never take the window down
        return _report(False, "Nothing was filled.", problems=[str(e)])
    finally:
        if session is not None:
            session.close()


def restore(settings, wait=0.0, cancel=None, on_wait=None, confirmed=None, run=None):
    """`_restore`, holding the Anki-write lock (E1.4 §W) as `run` does. `confirmed` is the saved time
    (`written_at`) of the fills' snapshot the user said yes to: after a wait, a snapshot on disk that is
    no longer that one (a fill it waited for saved a newer one) is refused. `run`: one of Connect's
    unfinished fills the user said yes to (P1.4) — exactly that one, as `reposition.restore`. Never raises."""
    language = reposition._language(settings)
    if run is not None:
        changed = lambda: undo.unfinished(language, "backfill") != run
    else:
        changed = None if confirmed is None else (
            lambda: (undo.load(language, kind="backfill") or {}).get("written_at") != confirmed)
    held, problem = anki_connect.take_writer("Backfill restore", _url(settings), wait, cancel, on_wait,
                                             changed=changed)
    if held is None:
        return _report(False, "Nothing was restored.", problems=[problem], busy=True)
    with held:
        return _restore(settings, asked=run if run is not None else (None if confirmed is None else ""))


def _restore(settings, asked=None):
    """Put back every field the fills wrote that still holds exactly what was written. Never raises."""
    url = _url(settings)
    language = reposition._language(settings)
    probe = anki_connect.probe(url, required=REQUIRED_ACTIONS)
    if not probe.get("ok"):
        return _report(False, "Nothing was restored.",
                       problems=[probe.get("error") or f"Could not reach Anki at {url}."])
    unfinished = undo.unfinished(language, "backfill")         # one of Connect's fills that never finished, first
    if unfinished is not None or asked:                         # — the one asked about, never another in its place
        if asked is not None and unfinished != asked:
            return _report(False, "Nothing was restored.", problems=[reposition.RESTORE_CHANGED])
        return _restore_run(settings, unfinished)
    snapshot = undo.load(language, kind="backfill")
    if not snapshot or not snapshot.get("fields"):
        return _report(False, "Nothing was restored.", problems=["Nothing has been filled yet."])
    try:
        current = {}
        for note in ankiconnect.notes_info(url, undo.note_ids(snapshot)):
            if isinstance(note.get("noteId"), int):
                current[note["noteId"]] = reposition._note_values(note)
        edits, skipped = undo.restore_fields(snapshot, current)
    except AnkiError as e:
        return _report(False, "Nothing was restored.", problems=[str(e)])
    written, failures = ankiconnect.update_notes(url, edits, chunk=reposition._chunk_size(settings))
    first_touch.restored(language, url, snapshot, snapshot.get("scope"),
                         fields={note_id: edits[note_id] for note_id in written})          # FT D4
    if not failures:
        undo.mark_complete(language, kind="backfill")
    message = f"Restored {len(written)} note{'' if len(written) == 1 else 's'}."
    if skipped:
        message += f" {skipped} you edited since were left as they are."
    return _report(not failures, message, written=written, failures=failures, skipped=skipped,
                   problems=[reason for _id, reason in failures[:1]])


# --------------------------------------------------------------------------- #
# Connect's Backfill (P1.4 rows 1.4.6–1.4.7): the notes one run names, unattended
# --------------------------------------------------------------------------- #
def _in_deck(decks, deck):
    return any(name == deck or str(name).startswith(deck + "::") for name in decks)


def gather_notes(url, settings, note_ids):
    """The scope `plan` reads — `gather`'s shape — for exactly `note_ids` (a Connect job's notes), each note also
    carrying `decks` (its cards' decks). Notes of another language than the session's are dropped, as `gather` drops
    them. Raises `AnkiError`."""
    infos = [note for note in ankiconnect.notes_info(url, sorted({int(n) for n in note_ids}))
             if isinstance(note.get("noteId"), int)]
    names = sorted({str(note.get("modelName") or "") for note in infos} - {""})
    replies = anki_connect.multi([{"action": "modelFieldNames", "params": {"modelName": name}}
                                  for name in names], url) if names else []
    fields_of = {}
    for name, reply in zip(names, replies):
        result = reply.get("result") if isinstance(reply, dict) else None
        fields_of[name] = [str(f) for f in result] if isinstance(result, list) else []
    card_ids = [c for note in infos for c in note.get("cards") or [] if isinstance(c, int)]
    rows = anki_connect.cards_info(url, card_ids) if card_ids else []
    new_cards = {row.get("cardId") for row in rows if row.get("type") == 0}
    deck_of = {row.get("cardId"): row.get("deckName") for row in rows}
    saved, overrides = _field_map(settings), reposition._word_fields(settings)
    session = reposition._language(settings)
    notes = []
    for note in infos:
        values = reposition._note_values(note)
        own = [c for c in (note.get("cards") or []) if isinstance(c, int)]
        notes.append({"id": note["noteId"], "model": note.get("modelName") or "",
                      "word": match.target_word(note, overrides, session),
                      "reading": match.normalize_word(next((values[f] for f in READING_FIELDS if values.get(f)), "")),
                      "fields": values, "new": bool(own) and all(c in new_cards for c in own),
                      "decks": sorted({deck_of[c] for c in own if deck_of.get(c)})})
    models = {}
    for name in names:
        of_model = [note for note in notes if note["model"] == name]
        models[name] = {"fields": fields_of[name], "count": len(of_model),
                        "mapped": {fill.key: mapped_field(fill, name, fields_of[name], saved) for fill in FILLS},
                        "language": note_language(name, of_model, settings)}
    notes = [note for note in notes if models[note["model"]]["language"] in (session, None)]
    young = set()
    if notes and "sentence" in _fills(settings):
        young = _young_words(url, overrides, {note["id"]: note["word"] for note in notes}, session)
    return {"models": models, "notes": notes, "young": young}


def source_text(video):
    """The source a Connect job's notes get (K40): the show and the episode, as the library names them — the show is
    the file's folder (the store's own rule), the episode its name: "Frieren · 第05話"; just the episode when its
    name already holds the show's."""
    if not video:
        return ""
    show = os.path.basename(os.path.dirname(os.path.abspath(video)))
    episode = os.path.splitext(os.path.basename(video))[0]
    return episode if not show or show in episode else f"{show} · {episode}"


def source_edits(scope, source, note_type, field):
    """K40 (HC-B6, Surasura's last say on its own fields): the source field — `field` on note type `note_type`, as
    Anki Miner's mapping names them — filled with `source` on every new note whose field is empty. Never a field that
    holds anything; never another note type's. -> `{note_id: {field: {"before", "after"}}}`."""
    if not source or not field or not note_type:
        return {}
    out = {}
    for note in scope.get("notes") or []:
        if note["model"] != note_type or field not in note["fields"] or not note["new"]:
            continue
        if not match.normalize_word(note["fields"].get(field) or ""):
            out[note["id"]] = {field: {"before": note["fields"].get(field) or "", "after": source}}
    return out


def run_named(settings, session, note_ids, source=None, dry_run=False, run_id=None, wait=0.0, cancel=None,
              on_wait=None, verb="Backfill (Connect)"):
    """Connect's Backfill of the notes `note_ids` names (`surasura-cli backfill`): new cards only, empty fields only —
    the automatic run's rules — in Backfill's one deck, and the source field (`source`: `(text, note type, field)`).

    §7.2: under the Anki-write lock; refused while a fill (the window's or a run of Connect's) never finished; each
    note re-read just before it is written, and one changed since the plan left alone; the run's own snapshot
    (`run_id`) on disk before the first write. `dry_run` reads and plans, takes no lock and writes nothing.

    -> `{"ok", "message", "problems", "filled" (note ids), "skipped" ({reason: notes}), "planned", "undo", "busy"}`.
    Never raises."""
    if dry_run:
        return _run_named(settings, session, note_ids, source, True, None)
    held, problem = anki_connect.take_writer(verb, _url(settings), wait, cancel, on_wait)
    if held is None:
        return _named_report(False, "Nothing was filled.", problems=[problem], busy=True)
    with held:
        return _run_named(settings, session, note_ids, source, False, run_id)


def _fields_put_back(language, deck):
    """P4.1 N2 (FT-1, D7 / C16 / K6): after *Put Anki back the way it was…* brought a deck's fields back, Backfill
    doesn't fill it by itself — Connect's fill of the notes it made included (its fills are journalled, FT K8, and the
    put-back takes them off, C18) — until you switch Backfill's automatic step (*Fill new cards automatically*,
    `junban_auto_backfill`) on again. -> the line Connect's fill says instead of filling, or None.

    Read at the fill's start, inside the Anki-write hold (`run_named` takes it first): a put-back that held the lock
    while this fill waited is seen, as `reposition._put_back_since` sees one for the re-order. The language's last
    `put_back` journal line that put fields back, in a deck overlapping `deck` — the decks whose fields came back
    (the line's `field_decks`, FT-1's own comparison in `first_touch._aside`; adversary AD-3), else, on a line from
    before them, its `deck` (a line naming none: every deck);
    settings.json as it is now (one that can't be read: the switch as off — the put-back's side, fill nothing)."""
    from app import settings_manager
    try:
        fresh = settings_manager.load_settings(strict=True)
    except Exception:
        fresh = {}
    if fresh.get("junban_auto_backfill") is True:
        return None
    for line in reversed(first_touch.journal(language)):
        if line.get("kind") != "put_back":
            continue
        if not (line.get("fields") or (line.get("done") or {}).get("fields")):
            continue                        # a put-back that left the fields as they were
        decks = line.get("field_decks") if isinstance(line.get("field_decks"), list) else line.get("deck")
        if any(first_touch._overlap(deck, other) for other in (decks or [""])):
            return (f"Backfill won't fill {deck or 'your decks'} by itself: you put its fields back the way they "
                    "were. Turn on Fill new cards automatically to fill it again.")
    return None


def _named_report(ok, message, **extra):
    report = {"ok": ok, "message": message, "problems": [], "filled": [], "skipped": {}, "planned": 0,
              "undo": None, "busy": False}
    report.update(extra)
    return report


def _run_named(settings, session, note_ids, source, dry_run, run_id):
    url = _url(settings)
    language = session.language
    deck = _deck(settings)
    aside = _fields_put_back(language, deck)
    if aside is not None:                   # P4.1 N2 (FT-1): read inside the writer's hold — Anki asked nothing
        return _named_report(False, "Nothing was filled.", problems=[aside], stands_aside=True)
    probe = anki_connect.probe(url, required=REQUIRED_ACTIONS)
    if not probe.get("ok"):
        return _named_report(False, "Nothing was filled.",
                             problems=[probe.get("error") or f"Could not reach Anki at {url}."])
    if not dry_run:
        previous = undo.load(language, kind="backfill")
        unfinished = undo.unfinished(language, "backfill")
        if (previous and previous.get("complete") is False) or unfinished is not None:
            return _named_report(False, "Nothing was filled.", unfinished=unfinished,
                                 problems=["The last fill did not finish. Press Restore first, then fill again."])
    settings = dict(settings, junban_backfill_cards="new", junban_backfill_replace=False)
    skipped = Counter()
    try:
        scope = gather_notes(url, settings, note_ids)
        kept = []
        for note in scope["notes"]:
            if deck and not _in_deck(note["decks"], deck):
                skipped["other deck"] += 1
            else:
                kept.append(note)
        scope["notes"] = kept
        planned = plan(scope, session, settings, auto=True)
        edits = {note_id: dict(changes) for note_id, changes in planned["edits"].items()}
        text, note_type, field = source or (None, None, None)
        for note_id, changes in source_edits(scope, text, note_type, field).items():
            edits.setdefault(note_id, {}).update(changes)
        for row in planned["rows"]:
            if row[3] not in ("fill", "replace"):
                skipped[reason(row[3])] += 1
    except AnkiError as e:
        return _named_report(False, "Nothing was filled.", problems=[str(e)])
    if dry_run or not edits:
        return _named_report(True, f"Would fill {len(edits)} note{'' if len(edits) == 1 else 's'}." if dry_run
                             else "Nothing to fill.", skipped=dict(skipped), planned=len(edits))
    try:
        # §7.2: each note read again right before it is written; a field changed since the plan is left alone.
        planned_edits = edits
        edits, changed = _still_as_previewed(url, edits)
    except AnkiError as e:
        return _named_report(False, "Nothing was filled.", problems=[str(e)])
    if changed:                 # counted in notes, as every other reason here (`changed` counts fields)
        skipped["changed since"] += sum(1 for note_id, changes in planned_edits.items()
                                        if len(edits.get(int(note_id)) or {}) < len(changes))
    if not edits:
        return _named_report(True, "Nothing to fill.", skipped=dict(skipped))
    # Asked again inside the writer's hold, right before the snapshot: planning takes seconds, and a review started
    # meanwhile is never written into (§7.2). Nothing written, no snapshot.
    if anki_connect.reviewing(url):
        return _named_report(False, "Nothing was filled.", problems=[anki_connect.REVIEWING], reviewing=True)
    try:
        _note_fill(url, language, [deck or "All decks"], edits)                 # FT K8
        undo.save([], [deck or "All decks"], language=language, fields=edits, kind="backfill", run_id=run_id)
    except OSError as e:
        return _named_report(False, "Nothing was filled.",
                             problems=[f"Could not save the undo file, so nothing was changed ({e})."])
    written, failures = ankiconnect.update_notes(url, touchup.edits_for_wire(edits),
                                                 chunk=reposition._chunk_size(settings))
    if not failures:
        undo.mark_complete(language, kind="backfill", run_id=run_id)
    message = f"Filled {len(written)} note{'' if len(written) == 1 else 's'}."
    if failures:
        message = (f"Filled {len(written)} of {len(edits)} notes — {len(failures)} could not be changed. "
                   "What was there before is saved; Restore puts it back.")
    return _named_report(not failures, message, filled=written, skipped=dict(skipped), planned=len(edits),
                         undo=run_id, failures=failures, problems=[r for _id, r in failures[:1]])


def restore_run(settings, run_id, wait=0.0, cancel=None, on_wait=None):
    """Put back the fields one of Connect's fills wrote — only those still holding what it wrote; one you edited
    since stays as you left it (P1.4 row 1.4.2). Holds the Anki-write lock. Never raises."""
    held, problem = anki_connect.take_writer("Backfill restore", _url(settings), wait, cancel, on_wait)
    if held is None:
        return _report(False, "Nothing was restored.", problems=[problem], busy=True)
    with held:
        return _restore_run(settings, run_id)


def _restore_run(settings, run_id):
    url = _url(settings)
    language = reposition._language(settings)
    snapshot = undo.load(language, kind="backfill", run_id=run_id)
    if not snapshot or snapshot.get("kind") != "backfill":
        return _report(False, "Nothing was restored.", problems=[f"There is no saved fill run {run_id!r}."])
    if snapshot.get("restored_at"):
        return _report(False, "Nothing was restored.", problems=[f"The fill {run_id} was already put back."])
    probe = anki_connect.probe(url, required=REQUIRED_ACTIONS)
    if not probe.get("ok"):
        return _report(False, "Nothing was restored.",
                       problems=[probe.get("error") or f"Could not reach Anki at {url}."])
    try:
        current = {}
        for note in ankiconnect.notes_info(url, undo.note_ids(snapshot)):
            if isinstance(note.get("noteId"), int):
                current[note["noteId"]] = reposition._note_values(note)
        edits, skipped = undo.restore_fields(snapshot, current)
    except AnkiError as e:
        return _report(False, "Nothing was restored.", problems=[str(e)])
    written, failures = ankiconnect.update_notes(url, edits, chunk=reposition._chunk_size(settings))
    first_touch.restored(language, url, snapshot, snapshot.get("scope"),
                         fields={note_id: edits[note_id] for note_id in written})          # FT D4
    if not failures:
        undo.mark_complete(language, kind="backfill", run_id=run_id, restored=True)
    message = f"Restored {len(written)} note{'' if len(written) == 1 else 's'}."
    if skipped:
        message += f" {skipped} you edited since were left as they are."
    return _report(not failures, message, written=written, failures=failures, skipped=skipped, run=run_id,
                   problems=[r for _id, r in failures[:1]])


def data_ready(language="ja"):
    """Is the library's own パターン data built, by this version's builder? Until it is, the window's
    Preview is "Build & preview" (once, about a minute) — also for a user who has a general database:
    the library is the only source that knows their names and niche words. An older build counts as
    not built (Patterns_Quality_Spec.md §8.3a)."""
    from modules.junban.patterns_build import default_db_path
    from modules.junban.patterns_store import is_current
    return is_current(default_db_path(language, None), language)


def general_ready(language="ja"):
    """Is a general パターン database here — the user's own two, or the shared one (§18) — by this
    version's builder? Without one, the window offers "Get data…": download the shared one, or import a
    package. Read from the language's own fill order: a language with none has none
    (Patterns_Chinese_Spec.md S2)."""
    from modules.junban.patterns_build import default_db_path
    from modules.junban.patterns import sources_for
    from modules.junban.patterns_store import is_current
    return any(is_current(default_db_path(language, name), language) for name in sources_for(language)
               if name != "library")


def describe(language="ja"):
    """One line for the window: what Restore would put back, or "" when nothing was filled."""
    snapshot = undo.load(language, kind="backfill")
    count = len((snapshot or {}).get("fields") or {})
    if not count:
        return ""
    return f"{count} note{'' if count == 1 else 's'} filled · last on {snapshot.get('written_at', '')[:10]}"


# --------------------------------------------------------------------------- #
# Rebuilding the library's パターン data (a subprocess: CLAUDE.md §6)
# --------------------------------------------------------------------------- #
# The library's set is built again by itself once the library holds a quarter more words than when it was built, as
# the token store counts them (`patterns_build.library_size`; the build records what it read) — the user, 2026-10-01:
# "it wouldn't be done often", and "in the background … so it doesn't hold the generate or anything hostage". No
# minimum size: a word needs FLOOR_LIBRARY uses to get lines, so a small library's set holds only its common words.
GROWTH = 0.25
_LOCK = threading.Lock()
_PROCESS = None         # the library build this app started last: one at a time, whoever asks (a laptop's minute each)
_BACKGROUND = {}        # the background build while it runs: {"language", "done", "total"} — the window's quiet line
_FAILED = {}            # language -> why its background build failed ("" once said): the automatic one leaves that
                        # language alone until the app starts again — it would fail the same way; the button still tries
_PROGRESS = re.compile(r"PROGRESS (\d+)/(\d+)")


def rebuild_command(language="ja", reinforce=False, db=None):
    """-> `(argv, env, cwd)` that runs `patterns_build` for `language`'s library in its own process —
    through `app_entry` in a packaged build (a frozen app can only launch its own subcommands), as a
    module from source. Japanese's command line is today's; another language names itself (S9), and
    Chinese segments as the user's analyzer does (`reinforce`: the `reinforce_segmentation` setting).
    `db` writes the set there instead of over the one in use (`staged_path`)."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    extra = [] if language == "ja" else ["--language", language] + (["--reinforce"] if reinforce else [])
    if db:
        extra += ["--db", db]
    if getattr(sys, "frozen", False):
        return [sys.executable, "junban_patterns"] + extra, env, None
    env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    return [sys.executable, "-m", "modules.junban.patterns_build"] + extra, env, root


def start_rebuild(language="ja", reinforce=False, db=None):
    """Start `language`'s library build. -> the `Popen`, its output a line per `PROGRESS n/total` — or None while
    another library build from this app is running: never two at once. At low priority (Windows'
    BELOW_NORMAL_PRIORITY_CLASS): a Generate started meanwhile goes first, and the build has what is left."""
    global _PROCESS
    argv, env, cwd = rebuild_command(language, reinforce, db)
    with _LOCK:
        if building() or _update_waiting():
            return None
        _PROCESS = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace",
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                                    | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))
        return _PROCESS


def _update_waiting():
    """An update is waiting for Surasura's programs to finish (S1.1 K75): no new build starts until it is cancelled."""
    try:
        from app import updater
        return updater.children_held()
    except Exception:
        return False


def rebuild_process():
    """The library build this app started, while it runs (the `Popen`), else None — what an update waits for."""
    process = _PROCESS
    return process if process is not None and process.poll() is None else None


def building():
    """Is a library build from this app running now — any language, the window's or the background's? A background
    one runs until its new set is put in or its failure kept (`_follow`)."""
    return (_PROCESS is not None and _PROCESS.poll() is None) or bool(_BACKGROUND)


def staged_path(language="ja"):
    """Where a rebuild of `language`'s library set is written: beside the set in use, never over it — Windows will not
    replace a database a reader holds open, and the window keeps filling from the current set while one builds."""
    from modules.junban.patterns_build import default_db_path
    return default_db_path(language, None) + ".new"


def promote(language="ja"):
    """Put a finished rebuild in place of the set in use -> True when it went in. Asked by whoever finds the set free:
    the build's own end, a new `Session`, the window when it is idle; while a reader still holds the old set, it waits
    for the next. A staged set older than the one in use (built again since, by "Build & preview") is dropped."""
    from modules.junban.patterns_build import default_db_path
    staged, path = staged_path(language), default_db_path(language, None)
    try:
        if not os.path.exists(staged):
            return False
        if os.path.exists(path) and os.path.getmtime(staged) < os.path.getmtime(path):
            os.remove(staged)
            return False
        os.replace(staged, path)
        return True
    except OSError:
        return False


def built_from(language="ja"):
    """The meta of `language`'s library set — when it was built, from how much — or None when there is none to read
    (none, or an older builder's: `data_ready`)."""
    from modules.junban.patterns_build import default_db_path
    from modules.junban.patterns_store import open_store
    store = open_store(default_db_path(language, None), language, quiet=True)
    if store is None:
        return None
    try:
        return dict(store.meta())
    finally:
        store.close()


def growth(language="ja"):
    """How much the library has grown since its set was built — (words now − words then) / words then, as the token
    store counts them — or None when either is not known: no set (or an older builder's), a set built before builds
    recorded it, no token store yet. A set built while the store held nothing has grown by anything at all."""
    from modules.junban.patterns_build import library_size
    return _growth(built_from(language), library_size(language))


def _growth(meta, now):
    try:
        then = int((meta or {})["library_tokens"])
    except (KeyError, ValueError):
        return None
    if now is None:
        return None
    if then <= 0:
        return float("inf") if now[0] > 0 else 0.0
    return (now[0] - then) / then


def rebuild_in_background(language="ja", reinforce=False, when_grown=False):
    """Build `language`'s library set again with nothing waiting for it: the build runs in its own process at low
    priority (`start_rebuild`) into a file beside the set in use, which everything keeps reading until the new one goes
    in (`promote`). `when_grown` is the automatic one: only when the library has grown by GROWTH since its set was
    built — never a first build (that is the window's "Build & preview"), never again this session after one failed.
    -> True when a build started. Never raises. While an update waits (K75) it is kept for when the update is
    cancelled, and returns False."""
    try:
        from app import updater
        if updater.defer_child(lambda: rebuild_in_background(language, reinforce, when_grown)):
            return False
    except Exception:
        pass
    try:
        if when_grown:
            promote(language)               # one that ended while the app was closed goes in first
            if language in _FAILED or (growth(language) or 0) < GROWTH:
                return False
        process = start_rebuild(language, reinforce, db=staged_path(language))
    except Exception as e:                  # a background job must never take the window down
        print(f"パターン: the library's build could not start ({e}).")
        return False
    if process is None:
        return False
    _FAILED.pop(language, None)
    _BACKGROUND.update(language=language, done=0, total=0)
    threading.Thread(target=_follow, args=(process, language), daemon=True).start()
    return True


def read_build(process, on_progress=None):
    """A library build's output, read to its end: each `PROGRESS n/total` line to `on_progress(n, total)`, the last
    other line kept (what a failure says). -> `(ok, last)`. The one reader of a build's lines — the background's
    (`_follow`) and the window's "Build & preview". Raises what reading the pipe raises."""
    last = ""
    for line in process.stdout:
        line = line.strip()
        found = _PROGRESS.match(line)
        if found:
            if on_progress is not None:
                on_progress(int(found.group(1)), int(found.group(2)))
        elif line:
            last = line
    return process.wait() == 0, last


def _follow(process, language):
    """A background build, followed to its end: its progress for the window's line; then the new set put in when it
    is free (`promote`), or why it failed — kept for `failed_note`, the set in use left as it was."""
    try:
        ok, last = read_build(process, lambda done, total: _BACKGROUND.update(done=done, total=total))
    except Exception as e:
        ok, last = False, str(e)
    try:
        if ok:
            promote(language)
        else:
            _FAILED[language] = last or "it stopped"
            print(f"パターン: the library's build failed ({_FAILED[language]}); the set in use is kept.")
    finally:
        _BACKGROUND.clear()             # the build is over: the next may start


def background():
    """`(language, files done, files in all)` while a background build runs, else None."""
    state = dict(_BACKGROUND)
    return (state.get("language", ""), state.get("done", 0), state.get("total", 0)) if state else None


def failed_note():
    """One line about a background build that failed — once: whoever says it first, and "" after."""
    for language, why in list(_FAILED.items()):       # a copy: a build's thread may add a language meanwhile
        if why:
            _FAILED[language] = ""
            name = {"ja": "Japanese", "zh": "Chinese"}.get(language, language)
            return f"Your {name} library's パターン could not be updated ({why}). Backfill keeps using the one it has."
    return ""


def _words(n):
    """4,239,192 -> "4.2 million words"; under a million, every word."""
    return f"{n / 1e6:.1f} million words" if n >= 1_000_000 else f"{n:,} words"


def rebuild_tip(language="ja"):
    """The tooltip of "Rebuild from my library": what it does, when the set was built and from how much of the library,
    how much the library holds now — and how often a word must be used to get lines, which is why no library is too
    small for one."""
    from modules.junban.patterns_build import FLOOR_LIBRARY, library_size
    meta, now = built_from(language) or {}, library_size(language)
    lines = ["Builds your library's パターン again, in the background. Backfill keeps using the one it has meanwhile."]
    try:
        files = int(meta.get("library_files", meta["files"]))
        words = int(meta.get("library_tokens", meta["tokens"]))
        lines.append(f"Built {str(meta.get('built_at', ''))[:10]} from {files:,} files ({_words(words)}).")
    except (KeyError, ValueError):
        pass
    if now is not None:
        grown = _growth(meta, now)
        more = f", {grown:.0%} more" if grown is not None and 0 < grown < float("inf") else ""
        lines.append(f"Your library now: {now[1]:,} files ({_words(now[0])}){more}.")
    lines.append("It rebuilds by itself once your library grows by a quarter." if "library_tokens" in meta
                 else "Rebuild it once, and it keeps up with your library by itself.")
    try:
        floor = int(meta.get("floor", FLOOR_LIBRARY))
    except ValueError:
        floor = FLOOR_LIBRARY
    lines.append(f"A word gets lines once your library uses it {floor} times.")
    return "\n".join(lines)
