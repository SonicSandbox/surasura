"""E2.2 D2: automatic rarity's warm band count adds an arrival's one-kanji pieces (`bound`) the way the whole recount does."""
from collections import Counter

from app import token_index, word_selection
from tests.test_arrivals_gates import GAKKOU, SENSEI, TOMODACHI, _gates, _rec

TE = ("手", "テ")          # a one-kanji word the list offers (one_kanji_data), read as UniDic reads it


class _Store:
    """The store's phrase table, empty: this library holds no set phrases."""

    def phrase_table(self):
        return {}


def test_with_the_one_kanji_rule_on_an_arrivals_pieces_come_off_the_warm_band_count(tmp_path, monkeypatch):
    """With the one-kanji rule on (`skip_singles`, Japanese), a one-kanji word's uses as pieces of another word are not
    unknowns: the arrival's 手 is used three times, twice as pieces (手紙, 手間 style), once on its own. The warm band
    count (`_band_words`, the arrival's pieces added in) must equal the whole recount over the library with the arrival
    added, in every band. Only the one use on its own is an unknown, so at a cut-off of 2 it is not counted. Ignoring
    the arrival's pieces would count all three uses and make the warm count disagree with the recount."""
    monkeypatch.setattr(token_index, "preview_lists", lambda *a, **k: {
        "known_tuples": set(), "known_lemmas": set(), "ignore_set": set(), "skip_singles": True})
    library = {GAKKOU: 5, SENSEI: 3, TOMODACHI: 2}
    gates = _gates([[*GAKKOU, 0, 0, 5], [*SENSEI, 0, 0, 3], [*TOMODACHI, 0, 0, 2]], language="ja", auto=True,
                   counts=library, total=1000, min_count=2)
    gates.view.script = None
    store = _Store()
    gates._warm_band(store, tmp_path)

    arrival = _rec(uses={TE: 3}, bound={TE: 2})
    total = gates.total + sum(arrival["counts"].values())
    warm = gates._band_words(arrival["counts"], arrival["bound"], [arrival["tally"]], total)

    counts = dict(library)
    counts[TE] = counts.get(TE, 0) + arrival["counts"][TE]
    bound = dict(gates.bound)
    bound[TE] = bound.get(TE, 0) + arrival["bound"][TE]
    freqs = token_index.unknown_distribution(counts, total, set(), set(), set(), True, "ja", None, bound)
    whole = {band: p["word_count"] for band, p in word_selection.band_previews(freqs, gates.ppm, gates.min_count).items()}

    assert warm == whole, "the arrival's one-kanji pieces come off the warm count as they do in the whole recount"
    assert any(warm.values()), "the warm count is not vacuously zero in every band"

    # The rule itself, asked of the arrival's own counts: 3 uses, 2 of them pieces, so 1 unknown use (not 3).
    own = token_index.unknown_distribution({TE: 3}, 3, set(), set(), set(), True, "ja", None, {TE: 2})
    assert dict(own["unknown"]) == {"手|テ": 1}, "the arrival's 2 piece uses come off its 3 uses, leaving 1 unknown"

    # Without the arrival's pieces the warm count moves: the test can tell the rule apart from ignoring it.
    ignored = gates._band_words(arrival["counts"], Counter(), [arrival["tally"]], total)
    assert ignored != warm, "ignoring the arrival's pieces changes the warm count"
