"""G10: with Ignore names on, an arrival's name record that names a word the library's names don't hold moves the gate."""
from app import analyzer
from tests.test_arrivals_gates import _gates, _rec, GAKKOU, LIST


def test_with_ignore_names_on_a_new_name_moves_the_names_gate_and_a_held_one_does_not(monkeypatch):
    """Ignore names on: an arrival that names 三日月 (ミカサ) the library's names don't hold is a new name, so the
    names gate moves; once the library holds ミカサ as a name, the same arrival moves nothing. Real words, real gate."""
    monkeypatch.setitem(analyzer.LOGIC, "ignore_names", True)
    arrival = {"n": {"ミカサ": 1}}
    gates = _gates(LIST, language="ja", tables=None, records=[], names_words=())
    assert gates.check([_rec(uses={GAKKOU: 1}, names=arrival)]) == (False, ["names"])
    held = _gates(LIST, language="ja", tables=None, records=[], names_words={"ミカサ"})
    assert held.check([_rec(uses={GAKKOU: 1}, names=arrival)]) == (True, [])
