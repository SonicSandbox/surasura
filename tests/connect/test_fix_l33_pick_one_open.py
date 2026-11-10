"""L3.3 wiring (W6): `runner.Steps.pick` reads the subtitle's item and every made word through ONE store handle, and the
command line's pick (`verbs.pick`, which calls Anki Miner) runs with no store span open.

What a wrong answer would cost: a span held across Anki Miner's minutes, so a store marked damaged meanwhile couldn't be
set aside by Repair; or two handles opened for the two reads of one pick, each a store opened again for nothing.

Real subtitles and words (the connect helpers' library); a stand-in pick; Anki is never reached.
"""
from app import library_store
from app.cli import verbs
from app.connect import library, runner
from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


def test_pick_reads_the_store_through_one_handle_and_runs_anki_miner_with_no_span_open(monkeypatch):
    # Why: the pick verb runs for minutes; a span open then keeps the store held while Repair may need it.
    c.library()
    with c.store() as s:
        first, second = s.ids("now")[:2]
        library.record_batch(s, first, {"上層部": [1001], "一生懸命": [1002]}, "2026-10-08T15:00:00Z", "7")

    spans_clear = []

    def pick(ns):
        spans_clear.append(library_store._span() is None)
        return {"words": [], "subtitle": None}
    monkeypatch.setattr(verbs, "pick", pick)

    # Why: the wrapper only records; it keeps every handle alive so a later handle can't reuse an earlier id().
    original_open = library_store.open_store
    handles, kept = [], []

    def recording_open_store(*args, **kwargs):
        result = original_open(*args, **kwargs)
        kept.append(result)
        handles.append(id(result))
        return result
    monkeypatch.setattr(library_store, "open_store", recording_open_store)

    steps = runner.Steps({"connect_enabled": True, "anki_connect_url": h.CLOSED_PORT})
    steps.pick("ja", {"id": 8, "item_id": second}, "episode.mkv")

    assert spans_clear == [True], "the pick verb (Anki Miner) must run with no store span open"
    assert len(handles) >= 2, "the subtitle's item and the made words are both read through the store"
    assert len(set(handles)) == 1, "every store read inside one pick shares one handle (one open, not one per read)"
