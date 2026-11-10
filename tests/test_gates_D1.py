"""Automatic rarity's warm band count: `Gates._band_words` must follow a compound's parts into `near`, so a
compound arrival's or a part arrival's credit reaches the compound's other parts the way a whole recount gives it.

Rule: an arrival of a compound's part (部 of 上層部 = 上層 + 部) whose compound the library holds counts every band
exactly as a whole recount of the library with the arrival added does — the compound and its other parts are counted
again too."""
from app import analyzer, token_index, word_selection
from tests.test_arrivals_gates import GAKKOU, JOUSOU, JOUSOUBU, SENSEI, TOMODACHI, _gates


class _Store:
    """The library's phrase table as `Store.phrase_table()` gives it for a library with no phrase rows."""

    def phrase_table(self):
        return {"rows": {}, "taken": {}}


def _part():
    """The 部 of 上層部 — a real part of a real compound (analyzer.compound_parts), not an invented one."""
    return next(key for key in ((lemma, reading) for lemma, reading, _free in analyzer.compound_parts()[JOUSOUBU])
                if key[0] == "部")


def test_a_part_arrival_counts_its_compound_and_other_parts_in_every_band_as_a_whole_recount_does(
        monkeypatch, tmp_path):
    """Under the cut-off of 3, 上層部 (library count 2) and its part 部 (count 1) each sit below the floor. An arrival
    of 2 more uses of 部 lifts words over the floor; a count that doesn't follow the compound's parts misses that
    credit in every band."""
    total = 1000
    part = _part()
    # Each band gets a different floor (3, 4, 5) at this total, so the given-back credit is tested at several floors.
    ppm = {band: 1000 * (1 + index % 5) for index, band in enumerate(word_selection.BANDS_ORDER)}
    # The compound's other part (上層) is held too, so its credit must be counted again in each band.
    counts = {GAKKOU: 5, SENSEI: 3, TOMODACHI: 2, part: 1, JOUSOUBU: 2, JOUSOU: 2}
    arrival = {part: 2}
    gates = _gates([[*GAKKOU, 0, 0, 5], [*SENSEI, 0, 0, 3], [*TOMODACHI, 0, 0, 2]], counts=counts, total=total,
                   min_count=3, ppm=ppm, language="ja", auto=True)
    gates.view.script = None
    monkeypatch.setattr(token_index, "preview_lists", lambda *a, **k: {
        "known_tuples": set(), "known_lemmas": set(), "ignore_set": set(), "skip_singles": False})
    gates._warm_band(_Store(), str(tmp_path))

    # The total after the arrival, as the parity suite (`_BAND_CHILD`) counts it.
    total_after = total + sum(arrival.values())
    got = gates._band_words(arrival, {}, [({}, {})], total_after)

    full = dict(counts)
    for key, n in arrival.items():
        full[key] = full.get(key, 0) + n
    whole = token_index.unknown_distribution(full, total_after, set(), set(), set(), False, "ja",
                                             _Store().phrase_table(), None)
    expected = {band: p["word_count"] for band, p in word_selection.band_previews(whole, ppm, 3).items()}

    assert got == expected


def test_a_compound_arrival_the_library_never_held_counts_its_parts_again_as_a_whole_recount_does(
        monkeypatch, tmp_path):
    """An arrival of 上層部 itself, a compound the library has never met (so no part leads to it): its parts 上層 and 部,
    held under the cut-off, are reached only through the compound table — each band counts them again, exactly as a
    whole recount of the library with the arrival added does."""
    total = 1000
    part = _part()
    ppm = {band: 1000 * (1 + index % 5) for index, band in enumerate(word_selection.BANDS_ORDER)}
    counts = {GAKKOU: 5, SENSEI: 3, TOMODACHI: 2, part: 2, JOUSOU: 2}
    arrival = {JOUSOUBU: 1}
    gates = _gates([[*GAKKOU, 0, 0, 5], [*SENSEI, 0, 0, 3], [*TOMODACHI, 0, 0, 2]], counts=counts, total=total,
                   min_count=3, ppm=ppm, language="ja", auto=True)
    gates.view.script = None
    monkeypatch.setattr(token_index, "preview_lists", lambda *a, **k: {
        "known_tuples": set(), "known_lemmas": set(), "ignore_set": set(), "skip_singles": False})
    gates._warm_band(_Store(), str(tmp_path))
    assert JOUSOUBU not in gates.holders.get(part, ()), "the library holds no 上層部: only the table leads to its parts"

    total_after = total + sum(arrival.values())
    got = gates._band_words(arrival, {}, [({}, {})], total_after)

    full = dict(counts)
    for key, n in arrival.items():
        full[key] = full.get(key, 0) + n
    whole = token_index.unknown_distribution(full, total_after, set(), set(), set(), False, "ja",
                                             _Store().phrase_table(), None)
    expected = {band: p["word_count"] for band, p in word_selection.band_previews(whole, ppm, 3).items()}

    assert got == expected
