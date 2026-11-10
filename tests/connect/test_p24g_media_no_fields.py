"""With no field mapping (no mine this run and no settings export in the run folder), the batch's media rename does
nothing: it returns before it reaches Anki or the library store, with no rename and no pairing read.

What a wrong answer would cost: the rename goes on to Anki with no field to aim at, taking Anki's write lock for
nothing (and making the job wait while you review) for a batch with nothing to rename (mutant P2.4-E21).
"""
import os

from app.connect import media_names, runner


def test_no_field_mapping_and_no_export_means_no_rename_and_no_anki_or_store_touch(tmp_path, monkeypatch):
    # An empty run folder: no settings-export.json, and this run never mined, so there is no mapping either.
    run = tmp_path / "run"
    os.makedirs(run)

    steps = runner.Steps({"connect_enabled": True, "anki_connect_url": "http://127.0.0.1:1"})
    steps.run_dir = lambda job: str(run)

    pairing_calls, store_opens = [], []
    # A pairing with its content key: were the guard gone, nothing would stop the rename going on to Anki.
    steps.pairing = lambda lang, job: pairing_calls.append((lang, job)) or {"content_key": "Example Show - 05"}
    steps._open = lambda lang: store_opens.append(lang)

    rename_calls = []
    anki_calls = []
    monkeypatch.setattr(media_names, "AnkiConnectMedia", lambda url: anki_calls.append(url) or object())
    monkeypatch.setattr(media_names, "rename", lambda media, lines, key, audio, picture: rename_calls.append(
        (lines, key, audio, picture)) or {"renamed": len(lines)})

    lines = [(11, 1000, 2500, "勇気を出して")]
    result = steps.name_media("ja", {"item_id": 1}, {}, lines)

    # Nothing to rename with: the step returns None, Anki's media is never asked, the pairing never read.
    assert result is None
    assert rename_calls == []
    assert anki_calls == []
    assert pairing_calls == [] and store_opens == []
