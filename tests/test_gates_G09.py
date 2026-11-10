"""G09: a Japanese arrival whose name record is missing can't be judged exact, so the names gate is named."""
from tests.test_arrivals_gates import GAKKOU, LIST, _gates, _rec


def test_a_japanese_arrival_without_its_name_record_is_named_as_a_names_move_never_exact():
    """A Japanese file's record of names is what tells whether its katakana runs and kanji names move the tables. An
    arrival without one (its record is None) can't be told apart from one that moves them, so the gate must say
    `names` rather than call the Generate exact. A list word met once more is otherwise quiet."""
    gates = _gates(LIST, language="ja", tables=None, records=[])
    assert gates.check([_rec(uses={GAKKOU: 1}, names=None)]) == (False, ["names"])


def test_a_non_japanese_arrival_without_a_name_record_does_not_name_the_names_gate():
    """The rule is for Japanese only: a Chinese arrival has no katakana or kanji name tables, so a missing name
    record (None) must not turn a list word met once more into a names move. The gate stays exact."""
    gates = _gates(LIST, language="zh", tables=None, records=[])
    assert gates.check([_rec(uses={GAKKOU: 1}, names=None)]) == (True, [])
