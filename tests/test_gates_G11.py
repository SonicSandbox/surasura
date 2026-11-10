"""The names gate: a kanji name the library holds twice, reached by an arrival's
third use, must move the names gate. The gate's warm path (tables kept) checks the kanji names an arrival touches; a
gate that skips them would call the arrival exact while the next Generate's name table gains 冬木. The sums and
tables are built the way `Gates.build` leaves them (`compute_tables`, `TableSums`, `TermSums`), so the test runs the
real warm path over real Japanese words."""
from app import analyzer, names

from tests.test_arrivals_gates import GAKKOU, LIST, _gates, _rec

FUYUKI = "冬木"                  # a kanji name (Fuyuki): two files' records hold it once each
OTHER_NAME = "西園寺"            # a kanji name the library holds nowhere


def _kanji_record(spelling, n=1):
    """A file's record holding the kanji name `spelling` `n` times (`names.Record` data: "jc" uses, "jb" bits)."""
    return {"jc": {spelling: n}, "jb": {spelling: 0}}


def _warm(library, sanitize):
    """The tables, sums and terms `Gates.build` keeps for a library whose files' records are `library`."""
    tables = names.compute_tables(library, None, sanitize)
    return tables, names.TableSums(library), names.TermSums(library, tables)


def test_a_kanji_name_reaching_three_uses_moves_the_names_gate():
    """Two files hold 冬木 once each (under the 3 uses a kanji name needs), so the library's table is empty. An
    arrival's third use of 冬木 joins it: the gate must move (False, ["names"])."""
    sanitize = analyzer._sanitize_term
    library = [_kanji_record(FUYUKI), _kanji_record(FUYUKI)]
    tables, table_sums, term_sums = _warm(library, sanitize)
    assert tables["j"] == {}, "two uses are under the cut-off: the library's table starts empty"
    gates = _gates(LIST, language="ja", tables=tables, table_sums=table_sums, term_sums=term_sums, records=library)
    moved = gates.check([_rec(uses={GAKKOU: 1}, names=_kanji_record(FUYUKI))])
    assert moved == (False, ["names"]), "a kanji name's third use joins it: the names gate must see it"


def test_a_kanji_name_reaching_two_uses_and_a_name_met_nowhere_do_not_move_the_names_gate():
    """The library holds 冬木 once; an arrival's one use makes two, under the 3 a kanji name needs, so nothing joins:
    exact, (True, []). An arrival holding a kanji name the library holds nowhere joins nothing either."""
    sanitize = analyzer._sanitize_term
    library = [_kanji_record(FUYUKI)]
    tables, table_sums, term_sums = _warm(library, sanitize)
    assert tables["j"] == {}, "one use is under the cut-off: the library's table starts empty"
    gates = _gates(LIST, language="ja", tables=tables, table_sums=table_sums, term_sums=term_sums, records=library)
    assert gates.check([_rec(uses={GAKKOU: 1}, names=_kanji_record(FUYUKI))]) == (True, []), (
        "two uses in all is under the cut-off: the names gate stays exact")
    assert gates.check([_rec(uses={GAKKOU: 1}, names=_kanji_record(OTHER_NAME))]) == (True, []), (
        "a kanji name met once in all moves nothing")
