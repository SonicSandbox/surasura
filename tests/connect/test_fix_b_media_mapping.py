"""P2.4 review fix B #4: media renamed after a kill. When this run never mined (no `self._mapping`, as after a
crash and a restart), `Steps.name_media` reads the field mapping from the job's own `settings-export.json` in its
run folder and still renames the clip and picture. What a wrong answer would cost: the clip and the picture keep
their Anki-made names, so the card's [sound:] and <img> never point at the renamed files and the words on the
card are lost to the learner's review.
"""
import json
import os

from app.connect import media_names, runner


def test_a_run_after_a_kill_reads_its_field_mapping_from_the_job_export_and_still_renames(tmp_path, monkeypatch):
    run = tmp_path / "run"
    os.makedirs(run)
    # The export Anki Miner writes into the run folder (shape as tests/connect/fake_anki_miner.py's export).
    export = {"anki_miner_settings": 1, "app_version": "3.5.0", "config_schema_version": 9, "configured": True,
              "settings": {"anki_deck_name": "DevTest", "anki_note_type": "Lapis",
                           "anki_fields": {"word": "Expression", "sentence": "Sentence", "audio": "SentenceAudio",
                                           "picture": "Picture"}}}
    with open(os.path.join(run, "settings-export.json"), "w", encoding="utf-8") as f:
        json.dump(export, f, ensure_ascii=False)

    # The run never mined, so there is no mapping on the instance; the export is the only source.
    steps = runner.Steps({"connect_enabled": True, "anki_connect_url": "http://127.0.0.1:1"})
    steps.run_dir = lambda job: str(run)
    steps.pairing = lambda lang, job: {"content_key": "ep-1"}

    calls = []
    monkeypatch.setattr(media_names, "AnkiConnectMedia", lambda url: object())
    monkeypatch.setattr(media_names, "rename", lambda media, lines, key, audio, picture: calls.append(
        (lines, key, audio, picture)) or {"renamed": len(lines)})

    lines = [(11, 1000, 2500, "勇気を出して")]
    result = steps.name_media("ja", {"item_id": 1}, {}, lines)

    # Both roles come from the export, the key from the pairing; the rename really ran.
    assert calls == [(lines, "ep-1", "SentenceAudio", "Picture")]
    assert result == {"renamed": 1}
