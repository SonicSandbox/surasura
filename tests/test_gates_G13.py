"""G13: a kanji's lone uses ("q") in an arrival's record move a work's term the arrival never spells, so the names gate
moves exactly when the library's "w" terms table would change (`arrivals.Gates._names_move`). The records come from real one-kanji runs: the tokenizer reads each text with `names=`."""
from app import analyzer, names
from tests.test_arrivals_gates import LIST, _gates


def _record(text):
    """A file's record as the tokenizer makes it: 焔魄陣 (a work's term, no dictionary spelling) wherever `text` writes
    it as a word, and every one-kanji token standing alone or inside a run counted in "q"."""
    record = names.Record()
    list(analyzer.JapaneseTokenizer(library=False).tokenize_sentences(text, names=record))
    return record.data()


def _term_gates(library):
    """A `Gates` as `Gates.build` leaves it over `library`'s records: the tables and their sums."""
    tables = names.compute_tables(library, None, analyzer._sanitize_term)
    return tables, _gates(LIST, language="ja", tables=tables, table_sums=names.TableSums(library),
                          term_sums=names.TermSums(library, tables), records=library)


def test_a_lone_kanji_use_that_drops_a_work_term_below_the_keep_cut_moves_the_names_gate():
    """焔魄陣 met 3 times, and each of its kanji alone 4 times in all (one lone use each in the same text): stickiness
    3/4 joins. Three more lone use of each kanji (3/7 = 0.43, under KEEP 0.5) drop it from the terms table: the arrival
    spells no 焔魄陣, and the gate still moves."""
    library = [_record("焔魄陣を見た。" * 3 + "焔。魄。陣。")]
    tables, gates = _term_gates(library)
    assert "焔魄陣" in tables["w"], "the library's own term joins: 3 uses at 0.75"
    arrival = _record("焔。魄。陣。" * 3)
    assert arrival["q"] == {"焔": 3, "魄": 3, "陣": 3} and not arrival["s"], \
        "the arrival holds only lone kanji, no word of its own"
    assert names.compute_tables(library + [arrival], tables, analyzer._sanitize_term)["w"] != tables["w"], \
        "the table itself changes"
    assert gates._names_move([arrival]) is True, "the names gate moves with the table"


def test_a_lone_kanji_use_off_the_most_used_kanji_of_a_work_term_moves_no_gate():
    """焔魄陣 met 3 times with 焔 alone 1 time (4 in all) and 魄 and 陣 alone 47 times each (50 in all): the least-used
    kanji is 焔, so stickiness is 3/4. Two more lone 魄 and 陣 leave that least-used count alone, so the terms table is
    unchanged and the arrival is exact — the gate must not move on a lone use that flips nothing."""
    library = [_record("焔魄陣を見た。" * 3 + "焔。" + "魄。陣。" * 47)]
    tables, gates = _term_gates(library)
    arrival = _record("魄。陣。" * 2)
    assert arrival["q"] == {"魄": 2, "陣": 2} and not arrival["s"], "the arrival holds only two lone 魄 and two lone 陣"
    assert names.compute_tables(library + [arrival], tables, analyzer._sanitize_term)["w"] == tables["w"], \
        "the term is unchanged"
    assert gates._names_move([arrival]) is False, "no table changes, so the names gate stays still"


def test_a_lone_kanji_use_that_holds_a_work_term_exactly_at_the_keep_cut_stays_in_the_table():
    """焔魄陣 met 3 times with 焔 alone 1 time (4 in all): stickiness 3/4. Two more lone 焔 make it 3/6 = 0.5, which is
    still KEEP: the term stays in the table at 0.5, so it is not dropped at the cut. Its stickiness is part of the table
    entry, so the table changed and the names gate moves with it."""
    library = [_record("焔魄陣を見た。" * 3 + "焔。" + "魄。陣。" * 47)]
    tables, gates = _term_gates(library)
    arrival = _record("焔。" * 2)
    assert arrival["q"] == {"焔": 2} and not arrival["s"], "the arrival holds only two lone 焔"
    after = names.compute_tables(library + [arrival], tables, analyzer._sanitize_term)["w"]
    assert "焔魄陣" in after and after["焔魄陣"][0] == 0.5, "the term stays at the KEEP cut (3/6 = 0.5)"
    assert after != tables["w"], "the entry's stickiness moved from 0.75 to 0.5, so the table changed"
    assert gates._names_move([arrival]) is True, "the names gate moves with the stickiness the table now holds"
