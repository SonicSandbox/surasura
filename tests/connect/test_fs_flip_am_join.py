"""FS-FLIP × AM-FIX (2026-11-23, 3.0.18): the full Swap on by default, joined with AM-FIX's new card beside the old one.

With the default on, a flagged card Connect made is an in-place swap. An Anki Miner without `render` (3.5–3.10) can
rewrite nothing, and AM-FIX's ruling 2 says the new card can't be made either (its `mine` refuses the old card's
duplicate). Before: the in-place swap fell back to a new card for good (`fall_back`, kind NEW_CARD, said *a new card
instead*), then waited on *Update Anki Miner to swap this card's sentence* — and once updated it made a NEW card, not
the same card the learner's default promised. Now the in-place swap waits on that same line, keeps its kind, and after
the update rewrites the card in place. Real lines: the simple Swap's CASES (tests/Test Resources), ja and zh.
"""
import pytest

from app.connect import anki_miner, runner, swap
from tests.connect.test_am_fix_swap_duplicate import Anki, _no_render, _steps, _words
from tests.connect.test_full_swap import _card, _made_by_connect, _rendered, _to_job
from tests.connect.test_kantan_sl_swap import ledger  # noqa: F401


def _in_place_swap(ledger, lang, anki, monkeypatch, tmp_path):
    """A flagged card Connect made, its swap's job made as the shipped default makes it: in place."""
    monkeypatch.setattr(swap, "_swap_flag", lambda: 3)
    monkeypatch.setattr(swap, "in_place_on", lambda settings=None: True)
    monkeypatch.setattr(swap, "kept_folder", lambda: str(tmp_path / "swap-kept"))
    _made_by_connect(ledger, lang)
    _entry, row = _to_job(ledger, lang, anki, monkeypatch)
    assert (row["kind"], row["state"]) == (swap.IN_PLACE, swap.QUEUED)
    return row


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_an_in_place_swap_with_an_anki_miner_without_render_waits_for_the_update_then_keeps_the_same_card(
        ledger, tmp_path, monkeypatch, lang):
    anki = _card(Anki(), lang)
    row = _in_place_swap(ledger, lang, anki, monkeypatch, tmp_path)
    job = ledger.job_by_id(row["job_id"])
    picked = {"video": "a.mkv", "subtitle": "a.ass"}
    steps = _steps(tmp_path, monkeypatch, anki, _rendered(tmp_path, lang))
    monkeypatch.setattr(anki_miner, "render_line", _no_render)
    with pytest.raises(runner.Needs) as e:
        steps.swap_in_place(lang, job, picked, _words(lang), 1, ledger, swap.in_place_row(ledger, row["job_id"]))
    assert (e.value.kind, e.value.say) == (runner.SWAP_UPDATE_NEED, swap.UPDATE_TO_SWAP) and e.value.standing
    kept = swap._rows(ledger, "id = ?", (row["id"],))[-1]
    assert (kept["kind"], kept["kind_why"]) == (swap.IN_PLACE, None)     # never fallen back: the same card waits
    assert not any(op[0] in ("add_note", "store", "update", "delete_media") for op in anki.log)
    ledger.need(lang, runner.SWAP_UPDATE_NEED, swap.UPDATE_TO_SWAP, job_id=job["id"], standing=True)
    # Updated: the next try renders, rewrites the same card, and the update line goes by itself.
    steps = _steps(tmp_path, monkeypatch, anki, _rendered(tmp_path, lang))
    done = steps.swap_in_place(lang, job, picked, _words(lang), 1, ledger, swap.in_place_row(ledger, row["job_id"]))
    assert done["in_place"] and done["outcomes"][0]["note_id"] == 900
    assert not [n for n in ledger.needs(lang) if n["kind"] == runner.SWAP_UPDATE_NEED]
    assert not any(op[0] == "add_note" for op in anki.log)


def test_an_in_place_swap_whose_word_render_cant_find_still_falls_back_once(ledger, tmp_path, monkeypatch):
    """Not the update case: Anki Miner has `render` but didn't find the word on that line — a new card instead, said
    once, as FS-1 made it (AM-FIX's beside-the-old-card path then makes it)."""
    anki = _card(Anki(), "ja")
    row = _in_place_swap(ledger, "ja", anki, monkeypatch, tmp_path)
    job = ledger.job_by_id(row["job_id"])
    steps = _steps(tmp_path, monkeypatch, anki, None)
    assert steps.swap_in_place("ja", job, {"video": "a.mkv", "subtitle": "a.ass"}, _words("ja"), 1, ledger,
                               swap.in_place_row(ledger, row["job_id"])) is None
    assert swap._rows(ledger, "id = ?", (row["id"],))[-1]["kind"] == swap.NEW_CARD
