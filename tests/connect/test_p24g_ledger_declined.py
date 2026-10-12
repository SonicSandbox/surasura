"""Connect ledger: `declined` names only the words Anki Miner turned down (P2.4 gap, mutant P2.4-B22).

The rule: a word counts as declined for an item when its outcome is `not_found` (or any other outcome that is
not one of made / uncertain / not_attempted). A word the miner never tried (`not_attempted`), a word it made
(`made`) and a word it could not decide on (`uncertain`) are not declined, so a later pick may still send them.

What a wrong answer would cost: if `not_attempted` counts as declined, a word the miner never got to is
never sent again for that item, so the user silently loses cards that were never tried. The mutant drops
`not_attempted` from the excluded outcomes, so ("一生懸命", "") lands in the declined set and this test fails.
"""
from app.connect.ledger import Ledger


def _o(word, outcome, note=None):
    """One outcome row as the runner records it (reading left empty, the note id only for a made card)."""
    return {"word": word, "reading": "", "outcome": outcome, "note_id": note}


def test_declined_names_only_the_words_anki_miner_turned_down(tmp_path):
    """Only `not_found` is a decline. `made`, `uncertain` and `not_attempted` are left out of the declined set
    (a never-tried word is not a refusal, so a later pick may still send it)."""
    with Ledger(str(tmp_path / "ledger.sqlite")) as L:
        j = L.queue("ja", 4, "user", None)
        # Four words of one item in one attempt: 上層部 made, 気配 uncertain, 一生懸命 never attempted,
        # 溜め息 turned down. Only 溜め息 may come back as declined.
        with L.transaction():
            L.record_outcomes(j, 1, [_o("上層部", "made", 1), _o("気配", "uncertain"),
                                     _o("一生懸命", "not_attempted"), _o("溜め息", "not_found")])
        assert L.declined("ja", 4) == {("溜め息", "")}
