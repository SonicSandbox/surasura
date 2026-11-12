# SPDX-License-Identifier: GPL-3.0-or-later
"""Anki Backfill's engine (`backfill.py`, Patterns_Spec.md §17) — against a fake collection, never Anki.

What this file guards, most costly first:

  * **The automatic run touches new cards only, and only empty fields.** The user's condition for the
    whole feature (2026-09-24): "the ONLY way this works is if it's an extremely robust separation".
    So the tests set the window to All and Replace and prove the automatic run still writes neither a
    studied card nor a filled field.
  * **The snapshot is on disk before the first write**, in its own file, and Restore reverts only what
    still holds the fill's value.
  * **Only the mapped field is written**, and a note type with no field mapped is never read at all.
  * **The known new cards are skipped** — the ones 順 files as "known" — and nothing else is.

Real Japanese words on real Lapis field names; ids of real Anki magnitude.
"""
import csv
import os
from unittest import mock

from app.path_utils import get_data_path
from modules.junban import backfill, undo
from modules.junban.tests.test_reposition import FakeCollection, _known, _patched

URL = "http://127.0.0.1:8765"
FIRST_NOTE = 1789712000000
FIRST_CARD = 1789712080000
LAPIS = ["Expression", "ExpressionReading", "Sentence", "Patterns", "Glossary"]
MIGAKU = ["Sentence", "Target Word", "Definitions"]
PATTERNS = backfill.FILLS[0]


class BackfillCollection(FakeCollection):
    """The fake collection, answering the three reads Backfill adds: the note types, their fields,
    and the notes of one type in scope (`note:"M" deck:"X" [is:new]` — `deck:*` for every deck).
    Like Anki, `is:new` finds a note with ANY new card; the planner's own check is what refuses a
    note with a studied one."""

    def __init__(self, cards, notes, models, **kwargs):
        super().__init__(cards, notes, actions=("updateNoteFields", "multi"), **kwargs)
        self.models = models

    def _dispatch(self, action, params):
        if action == "modelNames":
            return list(self.models)
        if action == "modelFieldNames":
            return list(self.models.get(params.get("modelName"), []))
        if action == "findNotes":
            return self._find_notes(params.get("query", ""))
        if action == "findCards":
            query = params.get("query", "")
            return self._find_young_cards() if "prop:ivl<21" in query else self._find_new_cards(query)
        if action == "cardsToNotes":
            return sorted({self.cards[c]["note"] for c in params.get("cards", []) if c in self.cards})
        return super()._dispatch(action, params)

    def _find_young_cards(self):
        """`-is:new -is:suspended prop:ivl<21`: studied, not suspended, not mature yet."""
        return sorted(c["cardId"] for c in self.cards.values()
                      if c["type"] != 0 and c["queue"] != -1 and c.get("interval", 0) < 21)

    def _find_new_cards(self, query):
        """`(note:"A" OR note:"B") deck:… is:new` — Anki's is:new is the card's type, suspended or not."""
        models = set(query.split('note:"')[i].split('"')[0] for i in range(1, query.count('note:"') + 1))
        deck = query.split('deck:"')[1].split('"')[0] if 'deck:"' in query else None
        found = []
        for note in self.notes.values():
            if note["modelName"] not in models:
                continue
            for card_id in note.get("cards", []):
                card = self.cards.get(card_id)
                if card and card["type"] == 0 and (deck is None or card["deckName"] == deck
                                                   or card["deckName"].startswith(deck + "::")):
                    found.append(card_id)
        return sorted(found)

    def _find_notes(self, query):
        model = query.split('note:"')[1].split('"')[0] if 'note:"' in query else None
        deck = query.split('deck:"')[1].split('"')[0] if 'deck:"' in query else None
        found = []
        for note in self.notes.values():
            cards = [self.cards[c] for c in note.get("cards", []) if c in self.cards]
            if model and note["modelName"] != model:
                continue
            if deck and not any(c["deckName"] == deck or c["deckName"].startswith(deck + "::")
                                for c in cards):
                continue
            if "is:new" in query and not any(c["type"] == 0 for c in cards):
                continue
            found.append(note["noteId"])
        return sorted(found)


def _lapis(index, word, reading, patterns="", studied=False, deck="TheBank"):
    """One Lapis note and its one card, as Anki returns them."""
    note_id, card_id = FIRST_NOTE + index, FIRST_CARD + index
    values = {"Expression": word, "ExpressionReading": reading, "Sentence": f"{word}の話をした。",
              "Patterns": patterns, "Glossary": f"<div>{word}</div>"}
    note = {"noteId": note_id, "modelName": "Lapis", "tags": [], "cards": [card_id],
            "fields": {name: {"value": values[name], "order": i} for i, name in enumerate(LAPIS)}}
    card = {"cardId": card_id, "note": note_id, "due": 2800 + index, "deckName": deck,
            "type": 2 if studied else 0, "queue": 2 if studied else 0}
    return note, card


def _migaku(index, word):
    note_id, card_id = FIRST_NOTE + 500 + index, FIRST_CARD + 500 + index
    values = {"Sentence": f"{word}です。", "Target Word": word, "Definitions": ""}
    note = {"noteId": note_id, "modelName": "Migaku Japanese", "tags": [], "cards": [card_id],
            "fields": {name: {"value": values[name], "order": i} for i, name in enumerate(MIGAKU)}}
    return note, {"cardId": card_id, "note": note_id, "due": 0, "deckName": "TheBank", "type": 0,
                  "queue": -1}


def _fake(*pairs, **kwargs):
    notes, cards = [p[0] for p in pairs], [p[1] for p in pairs]
    return BackfillCollection(cards, notes, {"Lapis": LAPIS, "Migaku Japanese": MIGAKU}, **kwargs)


FIELD = {"探検": '<div class="pat-particle pat-src-conversational">〜に 34% · 〜を 24%</div>',
         "大切": '<div class="pat-form pat-src-conversational">大切な 59% · 大切に 20%</div>',
         "囲む": '<div class="pat-form pat-src-balanced">囲まれる 76%</div>'}


class _Session:
    """The lookup, without databases or a tagger: a word's field, and which words are known."""
    language = "ja"

    def __init__(self, known=()):
        self.known = set(known)

    def is_known(self, word):
        return word in self.known

    def prepare(self, fill, notes, status=None, young=()):
        self.prepared = getattr(self, "prepared", []) + [(fill.key, [n["word"] for n in notes], set(young))]

    def value(self, fill, note, field):
        word = note["word"]
        return (FIELD[word], None) if word in FIELD else ("", "phrase")

    def close(self):
        pass


def _settings(**over):
    settings = {"target_language": "ja", "junban_url": URL, "junban_chunk_size": 150,
                "junban_backfill_fills": ["patterns"]}
    settings.update(over)
    return settings


def _plan(fake, session=None, auto=False, **over):
    settings = _settings(**over)
    with _patched(fake):
        scope = backfill.gather(URL, settings)
    return backfill.plan(scope, session or _Session(), settings, auto=auto)


# --- which field, which notes ---------------------------------------------------------------------- #
def test_a_field_named_like_the_fill_is_found_on_its_own():
    # Lapis carries `Patterns`; another note type may call it パターン or pattern.
    assert backfill.mapped_field(PATTERNS, "Lapis", LAPIS, {}) == "Patterns"
    assert backfill.mapped_field(PATTERNS, "Kiku", ["Word", "パターン"], {}) == "パターン"
    assert backfill.mapped_field(PATTERNS, "Senren", ["word", "pattern"], {}) == "pattern"
    assert backfill.mapped_field(PATTERNS, "Migaku Japanese", MIGAKU, {}) is None


def test_the_users_choice_wins_and_can_switch_a_note_type_off():
    saved = {"patterns": {"Migaku Japanese": "Definitions", "Lapis": backfill.SKIP}}
    assert backfill.mapped_field(PATTERNS, "Migaku Japanese", MIGAKU, saved) == "Definitions"
    assert backfill.mapped_field(PATTERNS, "Lapis", LAPIS, saved) is None
    # A choice naming a field the type no longer has falls back to the name rule.
    gone = {"patterns": {"Lapis": "Removed"}}
    assert backfill.mapped_field(PATTERNS, "Lapis", LAPIS, gone) == "Patterns"


def test_a_note_type_with_no_field_mapped_is_counted_but_never_read():
    # A collection of 2,046 suspended Migaku notes costs one count, not a download.
    fake = _fake(_lapis(0, "探検", "たんけん"), _migaku(0, "須藤"), _migaku(1, "鳥取"))
    with _patched(fake):
        scope = backfill.gather(URL, _settings())
    assert scope["models"]["Migaku Japanese"]["count"] == 2
    assert scope["models"]["Migaku Japanese"]["mapped"] == {"patterns": None, "sentence": None}
    read = [i for r in fake.requests if r["action"] == "notesInfo" for i in r["params"]["notes"]]
    assert read == [FIRST_NOTE]


def test_a_hand_typed_field_is_read_as_the_one_word_it_holds():
    """Backfill reads a card's word as Junban and the report do (anki_match.card_word, in the
    session's language) — 「撒く」 with its reading on a second line is 撒く, whose パターン and 例文 it
    then fills. It used to look up 「撒く」まく, which no database holds."""
    fake = _fake(_lapis(0, "「撒く」<br>まく", "まく"))
    with _patched(fake):
        scope = backfill.gather(URL, _settings())
    assert [note["word"] for note in scope["notes"]] == ["撒く"]


def test_one_deck_or_every_deck():
    fake = _fake(_lapis(0, "探検", "たんけん", deck="TheBank"),
                 _lapis(1, "大切", "たいせつ", deck="The Accelerator"))
    assert {r[1] for r in _plan(fake, junban_backfill_deck="TheBank")["rows"]} == {"探検"}
    assert {r[1] for r in _plan(fake)["rows"]} == {"探検", "大切"}


# --- what gets planned ----------------------------------------------------------------------------- #
def test_an_empty_field_is_filled_and_a_filled_one_left_alone():
    fake = _fake(_lapis(0, "探検", "たんけん"), _lapis(1, "大切", "たいせつ", patterns="<div>mine</div>"))
    result = _plan(fake)
    assert result["edits"] == {FIRST_NOTE: {"Patterns": {"before": "", "after": FIELD["探検"]}}}
    assert result["counts"] == {"fill": 1, "filled": 1}


def test_replace_overwrites_and_keeps_what_was_there():
    fake = _fake(_lapis(1, "大切", "たいせつ", patterns="<div>mine</div>"))
    result = _plan(fake, junban_backfill_replace=True)
    assert result["edits"] == {FIRST_NOTE + 1: {"Patterns": {"before": "<div>mine</div>",
                                                             "after": FIELD["大切"]}}}
    assert result["counts"] == {"replace": 1}


def test_studied_cards_are_filled_unless_new_only_is_chosen():
    fake = _fake(_lapis(0, "探検", "たんけん"), _lapis(1, "大切", "たいせつ", studied=True))
    assert set(_plan(fake)["edits"]) == {FIRST_NOTE, FIRST_NOTE + 1}
    new_only = _plan(fake, junban_backfill_cards="new")
    assert set(new_only["edits"]) == {FIRST_NOTE}


def test_a_new_card_whose_word_you_know_is_skipped_and_a_studied_one_is_not():
    # The user: "everything except for the backlogged cards that state 'known'". A studied card's word
    # is known by definition (the Anki sync) and is still filled.
    fake = _fake(_lapis(0, "探検", "たんけん"), _lapis(1, "大切", "たいせつ", studied=True))
    result = _plan(fake, session=_Session(known={"探検", "大切"}))
    assert set(result["edits"]) == {FIRST_NOTE + 1}
    assert result["counts"] == {"known": 1, "fill": 1}


def test_a_lookup_that_finds_nothing_says_why():
    fake = _fake(_lapis(0, "話が弾む", "はなしがはずむ"))
    assert _plan(fake)["counts"] == {"phrase": 1}


def test_chinese_is_not_offered_the_japanese_fill():
    session = _Session()
    session.language = "zh"
    fake = _fake(_lapis(0, "探検", "たんけん"))
    assert _plan(fake, session=session)["counts"] == {"language": 1}


def test_the_summary_is_one_short_line_in_notes_and_the_reasons_wait_behind_it():
    # The user, 2026-09-24: "Fill notes, skipped, and that's it" — counted in NOTES however many fills
    # are ticked (a note skipped gets nothing at all); the reasons are the ⓘ's, each once ("too rare
    # (7 < 12)" and "too rare (3 < 20)" are one), the most first.
    rows = [(1, "探検", "Patterns", "fill", "…", "patterns"),
            (1, "探検", "ExampleSentences", "not easy", "", "sentence"),
            (2, "大切", "Patterns", "filled", "", "patterns"),
            (2, "大切", "ExampleSentences", "fill", "…", "sentence"),
            (3, "話が弾む", "Patterns", "phrase", "", "patterns"),
            (3, "話が弾む", "ExampleSentences", "no sentence", "", "sentence")]
    assert backfill.summary({"edits": {1: {}, 2: {}}, "rows": rows}) == "Fill 2 notes · 1 skipped"
    assert backfill.summary({"edits": {1: {}}, "rows": rows[:1]}) == "Fill 1 note"
    assert backfill.summary({"edits": {}, "rows": rows[2:3]}) == "Nothing to fill · 1 skipped"
    counts = {"fill": 1064, "replace": 2, "too rare (7 < 12)": 50, "too rare (3 < 20)": 44,
              "phrase": 61, "filled": 25, "no pattern clears the floors": 45}
    assert backfill.skipped(counts) == [("too rare", 94), ("phrases", 61), ("nothing to show", 45),
                                        ("already filled", 25)]


def test_every_reason_the_window_can_show_is_explained():
    # Behind the ⓘ each count carries a plain line; a label without one would be a bare number.
    labels = set(backfill.REASONS.values()) - {"fill"}
    assert labels <= set(backfill.REASON_HELP)
    assert all(backfill.REASON_HELP[label] for label in labels)


def test_the_sentence_help_is_as_plain():
    _title, sections = backfill.FILLS[1].help
    assert backfill.FILLS[1].key == "sentence"
    assert all(line and len(line) <= 70 and example for _header, line, example in sections)


def test_the_patterns_help_names_each_line_plainly_with_an_example():
    # The "?" (the user: "as if for a 6th grader … with a simple example for each"): a header per
    # line of the field, one short sentence, an example.
    _title, sections = backfill.FILLS[0].help
    assert [header for header, _line, _example in sections][:5] == \
        ["Particles", "Forms", "Word pairs", "Frames", "書き言葉"]
    assert all(line and len(line) <= 70 for _header, line, _example in sections)
    assert all(example for _header, _line, example in sections)


def test_an_unticked_fill_still_knows_its_field_but_reads_no_note():
    # The window shows where each fill goes whether or not it is ticked; only a ticked one reads notes.
    fake = _fake(_lapis(0, "探検", "たんけん"))
    with _patched(fake):
        scope = backfill.gather(URL, _settings(junban_backfill_fills=[]))
    assert scope["models"]["Lapis"]["mapped"] == {"patterns": "Patterns", "sentence": None}
    assert scope["notes"] == []
    assert not [r for r in fake.requests if r["action"] == "notesInfo"]


# --- 例文: two more sentences, every other word known, never the card's own ------------------------- #
LAPIS_EX = LAPIS + ["ExampleSentences"]
MINE = "明日から冒険に出かけよう。"


def _ex(index, word, reading, sentence=MINE, studied=False, interval=0, examples=""):
    """A Lapis note with the ExampleSentences field (added for 例文) and its one card."""
    note_id, card_id = FIRST_NOTE + index, FIRST_CARD + index
    values = {"Expression": word, "ExpressionReading": reading, "Sentence": sentence, "Patterns": "",
              "Glossary": f"<div>{word}</div>", "ExampleSentences": examples}
    note = {"noteId": note_id, "modelName": "Lapis", "tags": [], "cards": [card_id],
            "fields": {name: {"value": values[name], "order": i} for i, name in enumerate(LAPIS_EX)}}
    card = {"cardId": card_id, "note": note_id, "due": 2800 + index, "deckName": "TheBank",
            "type": 2 if studied else 0, "queue": 2 if studied else 0, "interval": interval}
    return note, card


def _sentences(notes, found, **over):
    """Plan the 例文 fill with a REAL session (fugashi keys, phrases, the tidy-up) and the library pass
    answered by `found` — {lemma or phrase: [(others, text, surface, file)]}. -> (plan, the calls)."""
    calls = []

    def best_for(language, wanted, progress=None, young=None, phrases=None, prefer=None):
        calls.append({"wanted": set(wanted), "young": set(young or ()), "phrases": dict(phrases or {}),
                      "prefer": dict(prefer or {})})
        out = {key: found[key[0]] for key in wanted if key[0] in found}
        out.update({name: found[name] for name in (phrases or {}) if name in found})
        return out

    fake = BackfillCollection([n[1] for n in notes], [n[0] for n in notes], {"Lapis": LAPIS_EX})
    settings = _settings(junban_backfill_fills=["sentence"], **over)
    session = backfill.Session(settings)
    try:
        with _patched(fake), mock.patch("app.sentence_corpus.best_for", side_effect=best_for):
            result = backfill.plan(backfill.gather(URL, settings), session, settings)
    finally:
        session.close()
    return result, calls


def _written(result):
    return {row[1]: row[4] for row in result["rows"] if row[3] in ("fill", "replace")}


def test_a_card_gets_its_two_easiest_sentences_one_per_line_with_the_word_in_bold():
    # The field Lapis gained for it is found on its own; the two lead the ranking; <br> between.
    found = {"冒険": [(0, "彼は毎日冒険に出かけます。", "冒険", 0), (0, "冒険の話を聞かせて。", "冒険", 1),
                    (0, "冒険は続く。", "冒険", 2)]}
    result, calls = _sentences([_ex(0, "冒険", "ぼうけん")], found)
    assert _written(result)["冒険"] == "彼は毎日<b>冒険</b>に出かけます。<br><b>冒険</b>の話を聞かせて。"
    assert result["by_fill"] == {"sentence": {"fill": 1}}
    assert len(calls) == 1                                   # one pass for every card at once


def test_never_the_cards_own_sentence_or_one_almost_like_it():
    # The user: "it isn't doing the same sentence (or one with even an 80% match …, as we want
    # variety)". The same line with other punctuation, one a word longer, and a clause of it all go.
    found = {"冒険": [(0, "明日から冒険に出かけよう！", "冒険", 0),          # the card's, punctuation aside
                    (0, "明日から冒険に出かけるよ。", "冒険", 1),          # 92% alike, neither inside the other
                    (0, "明日から冒険に", "冒険", 2),                   # inside the card's sentence
                    (0, "彼は毎日冒険に出かけます。", "冒険", 3),
                    (0, "冒険の話を聞かせて。", "冒険", 4)]}
    result, _calls = _sentences([_ex(0, "冒険", "ぼうけん")], found)
    assert _written(result)["冒険"] == "彼は毎日<b>冒険</b>に出かけます。<br><b>冒険</b>の話を聞かせて。"
    # Nothing left but the card's own: said so, nothing written.
    result, _calls = _sentences([_ex(0, "冒険", "ぼうけん")], {"冒険": found["冒険"][:3]})
    assert result["by_fill"] == {"sentence": {"the card's own": 1}}


def test_only_sentences_where_every_other_word_is_known():
    # "All known words, i+1 where the unknown word is the expression": one other unknown word is out.
    found = {"冒険": [(0, "冒険は続く。", "冒険", 0), (1, "未知の冒険が始まる。", "冒険", 1)]}
    result, _calls = _sentences([_ex(0, "冒険", "ぼうけん")], found)
    assert _written(result)["冒険"] == "<b>冒険</b>は続く。"          # one easy one: just that one
    result, _calls = _sentences([_ex(0, "冒険", "ぼうけん")], {"冒険": found["冒険"][1:]})
    assert result["by_fill"] == {"sentence": {"not easy": 1}}
    assert backfill.reason("not easy") == "none easy"


def test_the_two_are_never_alike_each_other():
    # A repeated subtitle line in two episodes is still one sentence: the second is a different one.
    found = {"冒険": [(0, "彼は毎日冒険に出かけます。", "冒険", 0), (0, "彼は毎日冒険に出かけます！", "冒険", 1),
                    (0, "冒険の話を聞かせて。", "冒険", 2)]}
    result, _calls = _sentences([_ex(0, "冒険", "ぼうけん")], found)
    assert _written(result)["冒険"] == "彼は毎日<b>冒険</b>に出かけます。<br><b>冒険</b>の話を聞かせて。"


def test_the_second_comes_from_another_episode_when_one_is_as_good():
    found = {"冒険": [(0, "彼は毎日冒険に出かけます。", "冒険", 0), (0, "冒険の話を聞かせて。", "冒険", 0),
                    (0, "冒険は続く。", "冒険", 5)]}
    result, _calls = _sentences([_ex(0, "冒険", "ぼうけん")], found)
    assert _written(result)["冒険"].split("<br>")[1] == "<b>冒険</b>は続く。"


def test_a_phrase_is_looked_up_as_its_run_of_words():
    # 気を取り直す is three tokens: the library pass is asked for it by name, as the store's lemmas.
    found = {"気を取り直す": [(0, "彼女は気を取り直して歩き出した。", "気を取り直し", 0)]}
    result, calls = _sentences([_ex(0, "気を取り直す", "きをとりなおす")], found)
    assert calls[0]["phrases"] == {"気を取り直す": ("気", "を", "取り直す")}
    assert _written(result)["気を取り直す"] == "彼女は<b>気を取り直し</b>て歩き出した。"


def test_words_still_being_learned_are_handed_to_the_ranking():
    # The user: "even better if the words are NOT mature". 大切 is studied and young (5 days), 探検 is
    # mature (40): only 大切 is passed on, as a key of the store.
    notes = [_ex(0, "冒険", "ぼうけん"), _ex(1, "大切", "たいせつ", studied=True, interval=5),
             _ex(2, "探検", "たんけん", studied=True, interval=40)]
    _result, calls = _sentences(notes, {})
    assert {lemma for lemma, _reading in calls[0]["young"]} == {"大切"}


def test_a_card_is_looked_up_where_junban_places_it_and_a_known_one_is_read_on_its_own(tmp_path):
    # One card, one key everywhere (2026-09-27). Read alone, 葱 is キ, while the list Junban
    # follows has it as ねぎ — so 葱 (ネギ) is looked up, where Junban places the card. A word the learner knows is on
    # no row of the list (it holds only the words not known): the studied だいぶ card reaches the loanword ダイブ 'dive'
    # only through the kana fold, so it is read on its own, 大分, as before (known is tested first). And the dictionary decides
    # (the user, 2026-09-30): 従兄 and 仕向け are JMdict words of their own, apart from 従兄弟 and 仕向ける whose rows
    # hold their spellings, so each is looked up as it is written — never as those rows (the library's 仕向け is the
    # verb's: no sentence).
    folder = os.path.join(str(tmp_path), "results")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "progressive_learning_list.csv"), "w", encoding="utf-8-sig",
              newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Sequence", "Word", "Orth", "Forms", "Reading", "Score", "Occurrences (Global)"])
        writer.writerows([(1, "葱", "葱", "", "ネギ", 84, 17),
                          (1, "従兄弟", "いとこ", "従兄", "イトコ", 82, 16),
                          (1, "仕向ける", "仕向ける", "仕向け|しむけ", "シムケル", 79, 19),
                          (2, "ダイブ", "ダイブ", "", "ダイブ", 50, 12)])
    _known(tmp_path, ["だいぶ"])
    found = {"葱": [(0, "葱を刻んでスープに入れた。", "葱", 0)],
             "従兄": [(0, "昨日、従兄が遊びに来た。", "従兄", 0)],
             "従兄弟": [(0, "従兄弟と海へ行った。", "従兄弟", 0)],
             "仕向ける": [(0, "彼をそう仕向けたのは私だ。", "仕向け", 0)],
             "大分": [(0, "もうだいぶ慣れてきた。", "だいぶ", 0)],
             "ダイブ": [(0, "プールにダイブした。", "ダイブ", 0)]}
    notes = [_ex(0, "葱", "ねぎ"), _ex(1, "従兄", "いとこ"), _ex(2, "仕向け", "しむけ"),
             _ex(3, "だいぶ", "だいぶ", studied=True)]

    result, calls = _sentences(notes, found)

    assert calls[0]["wanted"] == {("葱", "ネギ"), ("大分", "ダイブ")}
    assert set(calls[0]["phrases"]) == {"従兄", "仕向け"}
    assert _written(result) == {"葱": "<b>葱</b>を刻んでスープに入れた。", "従兄": "昨日、<b>従兄</b>が遊びに来た。",
                                "だいぶ": "もう<b>だいぶ</b>慣れてきた。"}


def test_a_card_the_dictionary_keeps_apart_is_looked_up_as_it_is_written(tmp_path):
    # The dictionary decides (the user, 2026-09-30): 心する 'take heed' and 一気に 'in one go' are words of their own
    # in JMdict, so each is found as its own run of words — never 心's or 一気's sentences; 揚げる 'deep-fry', which
    # UniDic files under 上げる, is found as it is written — never 上げる's. 努力する is still 努力 (JMdict lists no
    # 努力する). Since 2026-10-01 the tokenizer reads 一気に as one adverb (JMdict's, cut at its particle): it is wanted
    # as a word of its own.
    _known(tmp_path, ["無関係"])
    found = {"心する": [(0, "足元に心して歩け。", "心し", 0)], "心": [(0, "心が温まる話だ。", "心", 0)],
             "一気に": [(0, "坂を一気に駆け上がった。", "一気に", 0)], "一気": [(0, "一気に飲み干した。", "一気", 0)],
             "揚げる": [(0, "油で揚げた魚を食べた。", "揚げ", 0)], "上げる": [(0, "手を上げて質問した。", "上げ", 0)],
             "努力": [(0, "毎日努力を重ねた。", "努力", 0)]}
    notes = [_ex(0, "心する", "こころする"), _ex(1, "一気に", "いっきに"), _ex(2, "揚げる", "あげる"),
             _ex(3, "努力する", "どりょくする")]

    result, calls = _sentences(notes, found)

    assert calls[0]["wanted"] == {("努力", "ドリョク"), ("一気に", "イッキニ")}
    assert calls[0]["phrases"] == {"心する": ("心", "為る"), "揚げる": ("上げる",)}
    assert _written(result) == {"心する": "足元に<b>心し</b>て歩け。", "一気に": "坂を<b>一気に</b>駆け上がった。",
                                "揚げる": "油で<b>揚げ</b>た魚を食べた。", "努力する": "毎日<b>努力</b>を重ねた。"}


def test_the_sentence_is_tidied_for_the_card():
    # What library lines carry that a card should not show: subtitle markup, a scripture's verse
    # number and footnote marks, a bracket whose other half is in another line — and what stays.
    from app import analyzer
    tagger = analyzer.JapaneseTokenizer().tagger
    tidy = backfill._sentence_html
    assert tidy("<>王は自分の領内の争いを治めるため</><>この町へ来たのだ</>。", "領内", tagger) == \
        "王は自分の<b>領内</b>の争いを治めるためこの町へ来たのだ。"
    assert tidy("14村へ続く①橋は古く、その道は②細い。", "その道", tagger) == \
        "村へ続く橋は古く、<b>その道</b>は細い。"
    assert tidy("「前者の二つは明日までに片付くだろう。", "前者", tagger) == \
        "<b>前者</b>の二つは明日までに片付くだろう。"
    assert tidy("3人で冒険に出た。", "冒険", tagger) == "3人で<b>冒険</b>に出た。"


# --- the automatic run: new cards, empty fields — nothing else, whatever the window says ------------ #
def test_the_automatic_run_never_reaches_a_studied_card_or_a_filled_field():
    fake = _fake(_lapis(0, "探検", "たんけん"), _lapis(1, "大切", "たいせつ", studied=True),
                 _lapis(2, "囲む", "かこむ", patterns="<div>mine</div>"))
    result = _plan(fake, auto=True, junban_backfill_cards="all", junban_backfill_replace=True)
    assert set(result["edits"]) == {FIRST_NOTE}
    assert result["counts"] == {"fill": 1, "studied": 1, "filled": 1}


def test_the_automatic_run_asks_anki_for_new_cards_only():
    fake = _fake(_lapis(0, "探検", "たんけん"))
    session = _Session()
    with _patched(fake), mock.patch.object(backfill, "Session", lambda settings: session):
        report = backfill.run_auto(_settings(junban_backfill_cards="all"))
    assert report["ok"] and report["written"] == [FIRST_NOTE]
    queries = [a["params"]["query"] for r in fake.requests if r["action"] == "multi"
               for a in r["params"]["actions"] if a["action"] == "findNotes"]
    assert queries and all(q.endswith(" is:new") for q in queries)


def test_a_note_with_one_studied_card_is_not_new():
    # Anki's is:new finds a note with ANY new card; the planner's own check refuses it.
    note, card = _lapis(0, "探検", "たんけん")
    studied = dict(card, cardId=card["cardId"] + 1, type=2, queue=2)
    note["cards"] = [card["cardId"], studied["cardId"]]
    fake = BackfillCollection([card, studied], [note], {"Lapis": LAPIS})
    assert _plan(fake, auto=True)["counts"] == {"studied": 1}


# --- fill and restore ------------------------------------------------------------------------------ #
def test_the_snapshot_is_on_disk_before_the_first_write():
    seen = {}

    def first_write():
        seen["snapshot"] = undo.load("ja", kind="backfill")
    fake = _fake(_lapis(0, "探検", "たんけん"), on_note_write=first_write)
    with _patched(fake):
        report = backfill.run(_settings(), _Session())
    assert report["ok"] and report["written"] == [FIRST_NOTE]
    assert seen["snapshot"]["complete"] is False
    assert seen["snapshot"]["fields"] == {str(FIRST_NOTE): {"Patterns": {"before": "",
                                                                         "after": FIELD["探検"]}}}
    assert undo.load("ja", kind="backfill")["complete"] is True
    # Only the mapped field reached Anki.
    assert fake.note_writes == [(FIRST_NOTE, {"Patterns": FIELD["探検"]})]


def test_a_second_fill_writes_nothing():
    fake = _fake(_lapis(0, "探検", "たんけん"))
    with _patched(fake):
        backfill.run(_settings(), _Session())
        report = backfill.run(_settings(), _Session())
    assert report["message"] == "Nothing to fill." and len(fake.note_writes) == 1


def test_a_field_changed_since_the_preview_is_left_alone():
    fake = _fake(_lapis(0, "探検", "たんけん"), _lapis(1, "大切", "たいせつ"))
    with _patched(fake):
        planned = backfill.preview(_settings(), _Session())
    fake.notes[FIRST_NOTE + 1]["fields"]["Patterns"]["value"] = "<div>typed by hand</div>"
    with _patched(fake):
        report = backfill.run(_settings(), _Session(), planned=planned)
    assert report["written"] == [FIRST_NOTE] and report["skipped"] == 1
    assert fake.notes[FIRST_NOTE + 1]["fields"]["Patterns"]["value"] == "<div>typed by hand</div>"


def test_an_unfinished_fill_blocks_the_next_until_restored():
    fake = _fake(_lapis(0, "探検", "たんけん"), refuse_note_writes="collection is not available")
    with _patched(fake):
        failed = backfill.run(_settings(), _Session())
        blocked = backfill.run(_settings(), _Session())
    assert not failed["ok"] and undo.load("ja", kind="backfill")["complete"] is False
    assert not blocked["ok"] and "Restore first" in blocked["problems"][0]


def test_restore_reverts_the_fill_but_never_an_edit_made_since():
    fake = _fake(_lapis(0, "探検", "たんけん"), _lapis(1, "大切", "たいせつ"))
    with _patched(fake):
        backfill.run(_settings(), _Session())
    fake.notes[FIRST_NOTE + 1]["fields"]["Patterns"]["value"] = "<div>edited</div>"
    with _patched(fake):
        report = backfill.restore(_settings())
    assert report["ok"] and report["written"] == [FIRST_NOTE] and report["skipped"] == 1
    assert fake.notes[FIRST_NOTE]["fields"]["Patterns"]["value"] == ""
    assert fake.notes[FIRST_NOTE + 1]["fields"]["Patterns"]["value"] == "<div>edited</div>"


def test_a_fill_and_a_reorder_never_overwrite_each_others_snapshot():
    undo.save([(FIRST_CARD, 2800)], ["TheBank"], language="ja")
    fake = _fake(_lapis(0, "探検", "たんけん"))
    with _patched(fake):
        backfill.run(_settings(), _Session())
    assert undo.load("ja")["cards"] == {str(FIRST_CARD): 2800}
    assert list(undo.load("ja", kind="backfill")["fields"]) == [str(FIRST_NOTE)]
    assert os.path.basename(undo.snapshot_path("ja")) == "junban_undo.json"


def test_anki_closed_is_a_message_not_a_crash():
    fake = _fake(_lapis(0, "探検", "たんけん"), offline=True)
    with _patched(fake):
        report = backfill.run(_settings(), _Session())
        restored = backfill.restore(_settings())
    assert not report["ok"] and "Anki" in report["problems"][0]
    assert not restored["ok"]


# --- end to end, with a real library database ---------------------------------------------------- #
def test_a_real_library_build_fills_a_real_note(tmp_path):
    # Fourteen real sentences about 影響 over three episodes (a library's document is a file, and a
    # pairing must be seen in three), built into the library database the way Rebuild builds it; the
    # Session opens it, tokenises with fugashi, and the planner writes its lines. 14 uses is thin: every
    # line says so (pat-thin — the card's label turns amber, Patterns_Quality_Spec decision 3).
    from modules.junban import patterns_build
    tier = os.path.join(get_data_path("ja"), "HighPriority")
    os.makedirs(tier)
    lines = ["台風の影響を受けて電車が止まった。", "彼の言葉に大きな影響を受けた。",
             "子どもは親の影響を受けやすい。", "円安の影響が広がっている。",
             "天気の影響で試合が中止になった。", "その本は多くの人に影響を与えた。",
             "大きな影響を与える決定だ。", "経済への影響が心配だ。", "影響は小さいと思う。",
             "強い影響を受けている。", "環境に影響を与える。", "影響が出るのは来年だ。",
             "大きな影響はない。", "悪い影響を受ける。"]
    for n in range(3):
        with open(os.path.join(tier, f"影響{n + 1}.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines[n::3]))
    patterns_build.build()
    session = backfill.Session(_settings())
    try:
        fake = _fake(_lapis(0, "影響", "えいきょう"))
        result = _plan(fake, session=session)
    finally:
        session.close()
    after = result["edits"][FIRST_NOTE]["Patterns"]["after"]
    assert after.startswith('<div class="pat-particle pat-src-library pat-thin">〜を 57% · 〜が 21%</div>')
    assert '<div class="pat-colloc pat-src-library pat-thin">影響を受ける · 影響を与える</div>' in after


# --- rebuilding the library data ------------------------------------------------------------------ #
def test_the_rebuild_runs_through_the_packaged_app_or_as_a_module(monkeypatch):
    monkeypatch.setattr("sys.frozen", True, raising=False)
    argv, _env, _cwd = backfill.rebuild_command()
    assert argv[1:] == ["junban_patterns"]
    monkeypatch.delattr("sys.frozen")
    argv, env, cwd = backfill.rebuild_command()
    assert argv[1:] == ["-m", "modules.junban.patterns_build"]
    assert os.path.isfile(os.path.join(cwd, "app_entry.py")) and env["PYTHONIOENCODING"] == "utf-8"


def test_a_session_serves_one_worker_after_another_and_closes_from_the_window(tmp_path):
    # The window keeps its session across previews, each on a new worker thread, and closes it on the
    # UI thread — found by opening the real window: SQLite's same-thread check refused the second one.
    import threading
    from modules.junban import patterns_build
    tier = os.path.join(get_data_path("ja"), "HighPriority")
    os.makedirs(tier)
    with open(os.path.join(tier, "探検.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(["探検に出かける。"] * 15))
    patterns_build.build()
    session = backfill.Session(_settings())
    errors = []

    def preview():
        try:
            session.value(PATTERNS, {"word": "探検", "reading": "たんけん", "fields": {}}, "Patterns")
        except Exception as e:          # noqa: BLE001 — recorded, asserted below
            errors.append(e)
    for _ in range(2):
        worker = threading.Thread(target=preview)
        worker.start()
        worker.join()
    session.close()
    assert errors == []


# --- 例文 prefers the sentence that shows the word's top pairing (Patterns_Quality_Spec.md Part D) ----- #
def test_the_sentence_step_looks_up_the_words_top_pairing_and_form_itself(tmp_path):
    # 例文 runs before any パターン value, and may be ticked on its own — so it looks the pairing up on the
    # card's own sources, and hands it on as the token store holds it: the analyzer's lemmas.
    from modules.junban import patterns_build as pb
    from modules.junban.patterns_store import open_store
    db = str(tmp_path / "patterns_ja_balanced.db")
    key = ("啓示", "ケイジ")
    pb.write_rows(db, [(*key, "啓示", "名詞", 204)], [("啓示", *key, 204)],
                  [(*key, "colloc", "{w}を受ける", 23, 4.8, "C1を", 9), (*key, "form", "{w}だ", 22, None, "W", 5)],
                  {"floor": 20, "language": "ja"})
    session = backfill.Session(_settings(junban_backfill_fills=["sentence"]))
    try:
        session.stores = [("balanced", open_store(db))]
        assert session._shown_runs("啓示", "けいじ") == [("啓示", "を", "受ける"), ("啓示", "だ")]
        assert session._shown_runs("冒険", "ぼうけん") == []          # not in any source: no preference
    finally:
        session.close()


def test_a_card_with_its_words_own_grammar_is_searched_as_its_word_its_own_form_first():
    # お部屋 and 優しさ are 部屋 and 優しい to the tokenizer, as Junban, the mark and パターン read the cards: 例文
    # searches their word's sentences, and among equally easy ones puts a sentence showing the card's own form
    # (御 部屋, 優しい さ) first.
    found = {"部屋": [(0, "お部屋はこちらです。", "部屋", 0), (0, "部屋が広い。", "部屋", 1)]}
    result, calls = _sentences([_ex(0, "お部屋", "おへや"), _ex(1, "優しさ", "やさしさ")], found)
    assert {("部屋", "ヘヤ"), ("優しい", "ヤサシイ")} <= calls[0]["wanted"]
    assert calls[0]["prefer"][("部屋", "ヘヤ")][0] == ("御", "部屋")
    assert calls[0]["prefer"][("優しい", "ヤサシイ")][0] == ("優しい", "さ")
    assert _written(result)["お部屋"] == "お<b>部屋</b>はこちらです。<br><b>部屋</b>が広い。"


def test_a_chinese_pairing_is_handed_on_in_the_users_script(tmp_path):
    # The database keeps Simplified; the token store is keyed in the user's script. A Traditional reader's
    # preference must say 電話, or it never meets a sentence.
    from modules.junban import patterns_build as pb
    from modules.junban.patterns_store import open_store
    db = str(tmp_path / "patterns_zh_shared.db")
    pb.write_rows(db, [("电话", "", "电话", "n", 900)], [("电话", "电话", "", 900)],
                  [("电话", "", "colloc", "接到{w}", 40, 8.0, "VO", 9)], {"floor": 20, "language": "zh"})
    session = backfill.Session({**_settings(junban_backfill_fills=["sentence"]), "target_language": "zh",
                                "zh_script": "t"})
    try:
        session.stores = [("shared", open_store(db, language="zh"))]
        assert session._shown_runs("電話", "") == [("接到", "電話")]
    finally:
        session.close()


def test_a_backfill_restore_asked_about_one_fill_never_puts_back_another():
    """Backfill's Restore was asked about one of Connect's fills; meanwhile another fill is the unfinished one. Nothing
    is restored — the other fill's fields stay as written — and the answer says what changed."""
    from modules.junban import reposition
    note, card = _lapis(0, "探検", "たんけん", patterns="<div>〜を探検する</div>")
    fake = _fake((note, card))
    newer = "backfill-20261006-050000-000"
    undo.save([], ["TheBank"], kind="backfill", run_id=newer,
              fields={note["noteId"]: {"Patterns": {"before": "", "after": "<div>〜を探検する</div>"}}})
    with _patched(fake):
        report = backfill.restore(_settings(), run="backfill-20261006-040000-000")
    assert not report["ok"] and report["problems"] == [reposition.RESTORE_CHANGED], report
    assert fake.notes[note["noteId"]]["fields"]["Patterns"]["value"] == "<div>〜を探検する</div>"
    assert undo.unfinished("ja", "backfill") == newer
