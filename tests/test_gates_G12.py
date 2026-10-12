"""The names gate: a piece's own uses can unjoin a katakana run the arrival doesn't spell."""
from app import analyzer, names
from tests.test_arrivals_gates import GAKKOU, LIST, _gates, _name_record, _rec


def test_a_piece_used_alone_often_unjoins_a_katakana_run_the_arrival_never_spells():
    """ミカサ joined in the library (three records, stickiness 1.0). An arrival that uses its pieces alone often
    (カサ and ミ five times each) pushes the run's stickiness down to 3 / 8, under KEEP, so the joined run leaves the
    tables though the arrival never spells ミカサ: the names gate must move. Without the piece lookup in
    `TableSums.touched` the run is never re-checked and the gate would wrongly stay exact."""
    library = [_name_record("ミカサ", ("ミ", "カサ")) for _ in range(3)]
    tables = names.compute_tables(library, None, analyzer._sanitize_term)
    gates = _gates(LIST, language="ja", tables=tables, table_sums=names.TableSums(library),
                   term_sums=names.TermSums(library, tables), records=library)
    arrival = _rec(uses={GAKKOU: 1}, names={"p": {"カサ": 5, "ミ": 5}})
    assert gates.check([arrival]) == (False, ["names"])


def test_a_piece_used_alone_once_leaves_the_run_joined_and_the_gate_exact():
    """Control arm for the test above: the same warm library, and the arrival uses the run's own piece カサ alone
    once. The run is decided again (its piece moved) but its stickiness stays 3 / 3 (its least-used piece, ミ, still
    has 3 uses), so its table entry is the same and the names gate stays exact."""
    library = [_name_record("ミカサ", ("ミ", "カサ")) for _ in range(3)]
    tables = names.compute_tables(library, None, analyzer._sanitize_term)
    gates = _gates(LIST, language="ja", tables=tables, table_sums=names.TableSums(library),
                   term_sums=names.TermSums(library, tables), records=library)
    arrival = _rec(uses={GAKKOU: 1}, names={"p": {"カサ": 1}})
    assert gates.check([arrival]) == (True, [])
