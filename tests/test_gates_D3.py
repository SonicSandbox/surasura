"""Automatic rarity's warm band count: a phrase row's Word arriving as a word takes the row out of the unknowns."""
from app import token_index, word_selection
from tests.test_arrivals_gates import GAKKOU, SENSEI, TOMODACHI, _gates

KIGA = ("気がする", "キガスル")
ROWS = {"rows": {"気がする|キガスル": [3, ["気がする"]]}, "taken": {}}


class _Store:
    """The library's phrase table (`Store.phrase_table()`): one idiom row, 気がする, met three times."""

    def phrase_table(self):
        return ROWS


def test_a_phrase_rows_word_arriving_as_a_word_takes_the_row_out_of_every_band(monkeypatch, tmp_path):
    """気がする is an idiom row the library meets three times (an unknown of the Rarity slider's in every band at a
    cut-off of 2). An arrival brings 気がする as a word of its own, which the library never held: the row's lemmas are
    now a word the library holds, so the row is no unknown any more. The warm count (`_band_words`) equals the whole
    recount over the library with the arrival added, where the row is no unknown — so the bands the row stood in count
    one word fewer."""
    monkeypatch.setattr(token_index, "preview_lists", lambda *a, **k: {
        "known_tuples": set(), "known_lemmas": set(), "ignore_set": set(), "skip_singles": False})
    library = {GAKKOU: 5, SENSEI: 3, TOMODACHI: 2}
    gates = _gates([[*GAKKOU, 0, 0, 5], [*SENSEI, 0, 0, 3], [*TOMODACHI, 0, 0, 2]], language="ja", auto=True,
                   counts=library, total=1000, min_count=2)
    gates.view.script = None
    gates._warm_band(_Store(), str(tmp_path))
    before = gates._band_words({}, {}, [], gates.total)

    arrival = {KIGA: 1}
    total = gates.total + 1
    warm = gates._band_words(arrival, {}, [({}, {})], total)

    counts = {**library, **arrival}
    freqs = token_index.unknown_distribution(counts, total, set(), set(), set(), False, "ja", ROWS, None)
    whole = {band: p["word_count"] for band, p in word_selection.band_previews(freqs, gates.ppm, gates.min_count).items()}
    assert warm == whole
    assert dict(freqs["unknown"])["気がする|キガスル"] == 1, "the word's own one use, never the row's three"
    assert any(warm[band] < before[band] for band in warm), (before, warm)


def test_a_phrase_rows_word_arriving_with_another_reading_still_takes_the_row_out(monkeypatch, tmp_path):
    """The same, with the word read otherwise than its row (UniDic's reading against the phrase data's): the row is
    named by its Word and reading, the arriving word by its own, so only the row's Word leads to it — the row still
    leaves the unknowns, as the whole recount (which goes by Words) has it."""
    monkeypatch.setattr(token_index, "preview_lists", lambda *a, **k: {
        "known_tuples": set(), "known_lemmas": set(), "ignore_set": set(), "skip_singles": False})
    library = {GAKKOU: 5, SENSEI: 3, TOMODACHI: 2}
    gates = _gates([[*GAKKOU, 0, 0, 5], [*SENSEI, 0, 0, 3], [*TOMODACHI, 0, 0, 2]], language="ja", auto=True,
                   counts=library, total=1000, min_count=2)
    gates.view.script = None
    gates._warm_band(_Store(), str(tmp_path))
    before = gates._band_words({}, {}, [], gates.total)

    arrival = {("気がする", "きがする"): 1}             # the row's Word, its reading written otherwise
    total = gates.total + 1
    warm = gates._band_words(arrival, {}, [({}, {})], total)

    counts = {**library, **arrival}
    freqs = token_index.unknown_distribution(counts, total, set(), set(), set(), False, "ja", ROWS, None)
    whole = {band: p["word_count"] for band, p in word_selection.band_previews(freqs, gates.ppm, gates.min_count).items()}
    assert "気がする|キガスル" not in dict(freqs["unknown"]), "the whole recount takes the row out"
    assert warm == whole
    assert any(warm[band] < before[band] for band in warm), (before, warm)
