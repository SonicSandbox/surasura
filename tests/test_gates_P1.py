"""The phrases gate, first branch: a word of a phrase row's lemmas arriving as a word the library doesn't hold moves it."""
from tests.test_arrivals_gates import LIST, _Phrase, _PhraseSet, _gates, _rec

KIGA = ("気がする", "キガスル")


def test_a_word_of_a_phrase_rows_lemmas_arriving_moves_the_phrases_gate():
    """気がする is a phrase row on the list (its Word is the row's lemma run). An arrival that brings 気がする as a word
    the library doesn't hold (not in the store's counts) moves the phrases gate: the word keeps the row, so the verdict
    is not exact. Without this branch the arrival would pass unnoticed, because the phrase itself is never met."""
    phrase_set = _PhraseSet([_Phrase(KIGA[0], KIGA[1], KIGA[0])])
    gates = _gates(LIST + [[*KIGA, 1, 0, 3]], phrase_set=phrase_set, row_of_phrase={0: 3})
    assert gates.check([_rec(counts={KIGA: 1})]) == (False, ["phrases"])


def test_a_word_of_a_phrase_rows_lemmas_the_library_already_holds_does_not_move_the_phrases_gate():
    """The same 気がする arriving, but the store already holds it as a word (in its counts, so its lemma is held).
    The word keeps the row either way, so nothing about the row moves: the verdict is exact. Only a word new to the library
    moves the gate."""
    phrase_set = _PhraseSet([_Phrase(KIGA[0], KIGA[1], KIGA[0])])
    gates = _gates(LIST + [[*KIGA, 1, 0, 3]], counts={KIGA: 1}, phrase_set=phrase_set, row_of_phrase={0: 3})
    assert gates.check([_rec(counts={KIGA: 1})]) == (True, [])


def test_a_new_word_that_is_no_phrase_rows_word_does_not_move_the_phrases_gate():
    """A phrase row is on the list, and the arrival brings a word new to the library (教室) that is not the row's
    Word: no row's lemmas are joined, so the phrases gate stays exact — only a row's own Word arriving moves it."""
    phrase_set = _PhraseSet([_Phrase(KIGA[0], KIGA[1], KIGA[0])])
    gates = _gates(LIST + [[*KIGA, 1, 0, 3]], phrase_set=phrase_set, row_of_phrase={0: 3})
    assert gates.check([_rec(counts={("教室", "キョウシツ"): 1})]) == (True, [])
