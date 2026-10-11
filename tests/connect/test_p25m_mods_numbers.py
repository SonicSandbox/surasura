"""The shelf records only real numeric mods (`shelf._mods`).

Rule: a note's mod is kept only when Anki answers with a number (int or float). A bool, a string or None is
dropped. A bool would be stored as 1 and read back as a real mod, so an edit would look hidden and *Undo this
batch* could delete a note the user changed. A wrong answer here would cost a learner a note they edited.
"""

from app.connect import shelf


class FakeAnki:
    """Only the method `shelf._mods` calls: `note_mods(ids)` returns {note id: mod} as Anki reports it."""

    def __init__(self, mods):
        self._mods = mods

    def note_mods(self, note_ids):
        return {n: self._mods[n] for n in note_ids if n in self._mods}


def test_only_numeric_mods_are_recorded_and_others_are_dropped():
    # Real mods are ints or floats; a bool (True), a numeric string and None are not numbers a mod can be.
    anki = FakeAnki({1: 1760000001, 2: True, 3: "1760000000", 4: None, 5: 1760000005.0})

    got = shelf._mods(anki, [1, 2, 3, 4, 5])

    assert got == {1: 1760000001, 5: 1760000005.0}
    assert all(isinstance(m, (int, float)) and not isinstance(m, bool) for m in got.values())


def test_a_bool_mod_alone_is_never_recorded_as_one():
    # Why: True == 1 in Python, so a bool slipping through would look like a real mod of 1 (an edit hidden).
    anki = FakeAnki({7: True})

    assert shelf._mods(anki, [7]) == {}
