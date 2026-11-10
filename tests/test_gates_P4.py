"""The phrases gate: a phrase not on the list whose Word the library already holds makes no row."""
from tests.test_arrivals_gates import LIST, _Phrase, _PhraseSet, _gates, _rec

KIGA_SURU = ("気がする", "キガスル")     # an idiom ('to feel like'); its Word is held by the library as a word


def test_a_phrase_off_the_list_whose_word_the_library_holds_makes_no_row():
    """気がする is off the list and its Word is already a word the library holds (so the phrase's lemma is not new).
    Two more uses bring the phrase to the cut-off of 2, yet no row comes: the held word keeps the phrase on the word
    the learner already has, not as a row of its own. Exact, nothing moves."""
    gates = _gates(LIST, min_freq=2, floor0=2, counts={**{(k[0], k[1]): k[4] for k in LIST}, KIGA_SURU: 4},
                   phrase_set=_PhraseSet([_Phrase(*KIGA_SURU, KIGA_SURU[0])]), phrase_uses={0: 1},
                   phrase_spellings={0: []}, row_of_phrase={})
    assert gates.check([_rec(phrases={0: 1})]) == (True, [])


def test_the_same_phrase_whose_word_the_library_does_not_hold_makes_its_row():
    """Control for the test above: the same idiom at the same cut-off, but its Word (気がする) is not a word the
    library holds (KIGA_SURU is absent from counts). Reaching the cut-off with no held Word, it makes a row, so the
    held Word is what suppresses the row, not the phrase or the cut-off alone."""
    gates = _gates(LIST, min_freq=2, floor0=2, counts={(k[0], k[1]): k[4] for k in LIST},
                   phrase_set=_PhraseSet([_Phrase(*KIGA_SURU, KIGA_SURU[0])]), phrase_uses={0: 1},
                   phrase_spellings={0: []}, row_of_phrase={})
    assert gates.check([_rec(phrases={0: 1})]) == (False, ["phrases"])
