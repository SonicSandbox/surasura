"""The loop's fill step hands Backfill the job's tag beside its notes (runner `Steps.fill`): Backfill reads the source
field from the job's run folder, and that folder is named by the tag.

What a wrong answer would cost: Backfill runs without its tag, so it cannot find the run folder that holds the
sentence source for these notes, and the 例文 and パターン fields come out empty or from the wrong episode.

Backfill is replaced by a capture at its own boundary (the real `Steps.fill` runs), so no Anki is reached.
"""
from app.cli import verbs
from app.connect import runner


def test_backfill_is_given_the_jobs_tag_beside_its_notes(monkeypatch):
    # the tag is the ledger's (`<ledger uid>-<id>`) under the Connect prefix: the run folder's name, not the bare job id
    seen = {}

    def backfill(ns):
        seen.update(lang=ns.lang, tag=ns.tag, notes=ns.notes)
        return {}
    monkeypatch.setattr(verbs, "backfill", backfill)
    runner.Steps({}).fill("ja", {"id": 7, "item_id": 3, "tag": "ab12cd34-7"}, [101, 102])
    assert seen["tag"] == "surasura::connect::ab12cd34-7", "Backfill finds the run folder by the job's tag"
    assert seen["notes"] == "101,102" and seen["lang"] == "ja"
