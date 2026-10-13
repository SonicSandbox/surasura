"""The subtitle offset a job was picked with reaches Anki Miner's batch (P2.4 review fix R17): `runner.Steps.mine`
hands `subtitle_offset` on from the picked item's `offset`, so a subtitle that Connect shifted by tsubasa's offset is
mined at that same shift and its lines land on the right moment of the video.

What a wrong answer would cost: every card of a shifted episode mined with the lines a second or more off the picture,
the sentence audio and screenshot of each card taken from the wrong moment. Real subtitle words; a fake Anki Miner
(its `mine_batch` captures the call); Anki is never reached.
"""
from types import SimpleNamespace

from app.cli import verbs
from app.connect import anki_miner, runner


def test_the_subtitle_offset_reaches_anki_miner_as_the_job_was_picked_with_it(monkeypatch):
    monkeypatch.setattr(anki_miner, "find", lambda loaded: "am.exe")
    monkeypatch.setattr(verbs, "_anki_miner_setup", lambda loaded, lang, run_dir: (None, None, SimpleNamespace(word="Word")))
    seen = {}

    def capture(*args, **kwargs):
        seen.update(kwargs)
        return {"outcomes": [], "app": "3.7.0"}
    monkeypatch.setattr(anki_miner, "mine_batch", capture)
    words = [{"word": "一生懸命", "reading": "イッショウケンメイ", "line_start": 3.0}]
    # Why 1.24: a non-zero, non-round offset, so a step that drops it to the default 0.0 cannot pass by accident.
    picked = {"video": "v.mkv", "subtitle": "s.srt", "offset": 1.24, "profile": None}
    got = runner.Steps({}).mine("ja", {"id": 1, "item_id": 1, "tag": "ab-1"}, picked, words, 1)
    assert got["outcomes"] == []
    assert seen["subtitle_offset"] == 1.24, "the job's offset is the one Anki Miner shifts the subtitle by"
