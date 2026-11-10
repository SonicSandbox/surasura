"""P2.4 review fix B: a job's media is named with that job's own field mapping. The run's held mapping
(`steps._mapping`) belongs to the job it mined (`steps._mapping_job`); a later job resumed with nothing left to
mine must read its own `settings-export.json` in its run folder, never job 1's audio field. What a wrong answer
would cost: job 2's clip is renamed with job 1's audio field name, so the card's [sound:] is looked up in the
wrong field and the learner hears nothing on the card.
"""
import json
import os
from types import SimpleNamespace

from app.connect import media_names, runner


def _export_for(run, audio_field, picture_field):
    """Write an Anki Miner settings export into a run folder (shape as tests/connect/fake_anki_miner.py's export)."""
    os.makedirs(run, exist_ok=True)
    export = {"anki_miner_settings": 1, "app_version": "3.5.0", "config_schema_version": 9, "configured": True,
              "settings": {"anki_deck_name": "DevTest", "anki_note_type": "Lapis",
                           "anki_fields": {"word": "Expression", "sentence": "Sentence", "audio": audio_field,
                                           "picture": picture_field}}}
    with open(os.path.join(run, "settings-export.json"), "w", encoding="utf-8") as f:
        json.dump(export, f, ensure_ascii=False)


def test_a_resumed_job_with_no_mining_left_names_its_media_with_its_own_export_not_the_first_jobs_mapping(
        tmp_path, monkeypatch):
    # Job 1 mined and holds its mapping (AudioA); job 2 is a different job whose own export says SentenceAudio.
    run2 = tmp_path / "run2"
    _export_for(str(run2), "SentenceAudio", "Picture")
    steps = runner.Steps({"connect_enabled": True, "anki_connect_url": "http://127.0.0.1:1"})
    steps._mapping = SimpleNamespace(fields={"audio": "AudioA", "picture": "PictureA"})
    steps._mapping_job = 1
    steps.run_dir = lambda job: str(run2)
    steps.pairing = lambda lang, job: {"content_key": "ep-2"}

    calls = []
    monkeypatch.setattr(media_names, "AnkiConnectMedia", lambda url: object())
    monkeypatch.setattr(media_names, "rename", lambda media, lines, key, audio, picture: calls.append(
        (lines, key, audio, picture)) or {"renamed": len(lines)})

    lines = [(12, 2000, 3100, "溜め息をつく")]
    result = steps.name_media("ja", {"id": 2, "item_id": 2}, {}, lines)

    # Job 2's own export names the fields; the first job's AudioA must not leak across.
    assert calls == [(lines, "ep-2", "SentenceAudio", "Picture")]
    assert result == {"renamed": 1}


def test_the_job_that_mined_keeps_the_mapping_it_was_given_for_its_media(tmp_path, monkeypatch):
    # Job 1 mined in this run: its held mapping is the one the media is named with, and no export is read.
    steps = runner.Steps({"connect_enabled": True, "anki_connect_url": "http://127.0.0.1:1"})
    steps._mapping = SimpleNamespace(fields={"audio": "AudioA", "picture": "PictureA"})
    steps._mapping_job = 1
    steps.run_dir = lambda job: str(tmp_path / "missing-run")
    steps.pairing = lambda lang, job: {"content_key": "ep-1"}

    calls = []
    monkeypatch.setattr(media_names, "AnkiConnectMedia", lambda url: object())
    monkeypatch.setattr(media_names, "rename", lambda media, lines, key, audio, picture: calls.append(
        (lines, key, audio, picture)) or {"renamed": len(lines)})

    lines = [(13, 500, 1500, "気配を感じる")]
    steps.name_media("ja", {"id": 1, "item_id": 1}, {}, lines)

    assert calls == [(lines, "ep-1", "AudioA", "PictureA")]
