"""Fix B, the known-from-Anki signal: one term it doesn't know turns the whole signal off.

What a wrong answer would cost: a list with a typo ("suspnded") or a term the signal doesn't know ("flag:33") that
still lets the valid terms through would widen the signal, so cards the user never chose to count would mark their
words known. The signal reads "and", so a list with any unknown term is off, and says why in a line of print. No
Anki is reached: `signal` is a pure function of the settings.
"""
from app.connect import known_signal


def test_a_list_with_an_unknown_term_turns_the_whole_signal_off(capsys):
    # Why: "flag:33" is not a term the signal knows; keeping "suspended" alone would be a silent widening of "and".
    assert known_signal.signal({"connect_enabled": True, "known_from_anki": ["suspended", "flag:33"]}) == []
    assert "flag:33" in capsys.readouterr().out


def test_known_terms_in_any_case_and_spacing_are_read_as_the_clean_list():
    # Why: the case and spacing of a valid term must not count as an unknown term; the order is the user's own.
    assert known_signal.signal({"connect_enabled": True, "known_from_anki": ["Suspended", " flag:1 "]}) == [
        "suspended",
        "flag:1",
    ]
