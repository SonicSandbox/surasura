"""Piyo's listening round through the MCP server (app/cli/mcp_server.py → app/listening.py): what the learner's AI
sends and gets back — short answers only (never audio, subtitles or long text), a failed line's words to swap with
nothing made, the voice off or a Chinese round in one sentence, the round queued and its status, again= on a made
round with no voice asked, play and cancel. The voice is the fake of tests/test_listening.py.
"""
import json
import os

import pytest

from app import listening, practice_rounds
from tests.test_listening import LINES, FakeVoice, _checker, real_lines
from tests.test_mcp_server import _run, _state

pytest.importorskip("mcp")


@pytest.fixture
def voice(monkeypatch):
    fake = FakeVoice()
    monkeypatch.setitem(listening.VOICES, "ja", lambda: fake)
    fake.started = []
    monkeypatch.setattr(listening, "start_maker", lambda language, popen=None: fake.started.append(language))
    os.makedirs(practice_rounds.folder("ja"), exist_ok=True)
    return fake


def _known_state(lines, unknown=()):
    state = _state()
    state._checkers["ja"] = _checker(lines, unknown)
    return state


def _call(state, name, args):
    async def calls(client):
        return await client.call_tool(name, args)
    got = _run(state, calls)
    return got.content[0].text, (got.is_error if hasattr(got, "is_error") else got.isError)


def _data(state, name, args):
    text, error = _call(state, name, args)
    assert not error, text
    return json.loads(text)


def test_a_round_with_a_line_that_fails_names_only_its_words_and_makes_nothing(voice):
    lines = real_lines()[:4] + ["冒険の準備はできていますか？"]
    state = _known_state(lines, unknown={"準備"})
    out = _data(state, "surasura_listening_round", {"lines": lines})
    assert out["queued"] is False and out["fix"] == [{"line": 5, "swap": ["準備"]}]
    assert voice.started == [] and voice.spoken == []
    assert not [n for n in os.listdir(practice_rounds.folder("ja"))]        # no round, no record
    assert len(json.dumps(out, ensure_ascii=False)) < 300


def test_a_round_that_passes_is_queued_kept_for_again_and_answered_short(voice):
    state = _known_state(LINES)
    out = _data(state, "surasura_listening_round", {"lines": LINES, "title": "朝の冒険"})
    assert out["queued"] is True and out["lines"] == len(LINES) and voice.started == ["ja"]
    assert set(out) == {"queued", "round_id", "lines", "next"} and len(json.dumps(out, ensure_ascii=False)) < 400
    rid = out["round_id"]
    assert listening.read("ja", rid)["state"] == "queued" and listening.read("ja", rid)["name"] == "朝の冒険"
    listed = _data(state, "surasura_rounds", {})["rounds"]
    assert listed[0]["round_id"] == rid and listed[0]["kind"] == "listening" and listed[0]["lines_kept"] == len(LINES)


def test_the_voice_off_and_a_chinese_round_each_say_one_sentence_and_make_nothing(voice):
    state = _known_state(LINES)
    voice.why = "The AI voice is off. Turn it on in Surasura: Settings › App › Beta, then press Install."
    out = _data(state, "surasura_listening_round", {"lines": LINES})
    assert out == {"queued": False, "why": voice.why}
    out = _data(state, "surasura_listening_round", {"lines": ["我们明天去公园散步吧。"], "language": "zh"})
    assert out == {"queued": False, "why": listening.NOT_YET["zh"]}
    assert voice.started == [] and not os.listdir(practice_rounds.folder("ja"))


def test_no_lines_or_too_many_is_said_as_what_to_send(voice):
    state = _known_state(LINES)
    for lines in ([], ["冒険だ。"] * (listening.LINES_MOST + 1)):
        text, error = _call(state, "surasura_listening_round", {"lines": lines})
        assert error and "1-20 short lines" in text
    # a blank entry is refused by its number, never dropped (the fix's numbers stay the AI's own: Opus r1 #5)
    text, error = _call(state, "surasura_listening_round", {"lines": ["冒険だ。", "  ", "冒険する？"]})
    assert error and "Line 2 is empty" in text and voice.started == []


def test_status_while_making_then_done_then_play_opens_the_copy_with_pauses(voice, monkeypatch):
    state = _known_state(LINES)
    rid = _data(state, "surasura_listening_round", {"lines": LINES})["round_id"]
    making = _data(state, "surasura_listening_status", {"round_id": rid})
    assert making["state"] == "queued" and making["of"] == len(LINES) and "min left" in making["next"]
    text, error = _call(state, "surasura_listening_status", {"round_id": rid, "play": True})
    assert error and "isn't made yet" in text
    assert listening.make_waiting("ja", settings={})["made"] == [rid]
    done = _data(state, "surasura_listening_status", {"round_id": rid})
    assert done["state"] == "done" and done["files"]["audio"].endswith(".mp3" if listening.ffmpeg() else ".wav")
    assert done["where"] == f"Surasura's User Files › ja › practice › {rid}"
    opened = []
    monkeypatch.setattr(listening, "open_file", opened.append)
    played = _data(state, "surasura_listening_status", {"round_id": rid, "play": True})
    want = done["files"].get("with_pauses") or done["files"]["audio"]
    assert opened == [os.path.join(listening.folder("ja", rid), want)]
    assert played == {"round_id": rid, "state": "done", "opened": want}           # its name, never a path
    shown = _data(state, "surasura_listening_status", {"round_id": rid, "open_folder": True})
    assert opened[-1] == listening.folder("ja", rid) and shown["opened"] == rid


def test_again_on_a_made_round_answers_its_files_and_asks_no_voice(voice):
    state = _known_state(LINES)
    rid = _data(state, "surasura_listening_round", {"lines": LINES})["round_id"]
    listening.make_waiting("ja", settings={}, tool=None)
    voice.spoken, voice.started = [], []
    out = _data(state, "surasura_practice_start", {"again": rid})
    assert out["state"] == "done" and out["files"] and voice.spoken == [] and voice.started == []


def test_cancel_through_the_server_stops_a_queued_round(voice):
    state = _known_state(LINES)
    rid = _data(state, "surasura_listening_round", {"lines": LINES})["round_id"]
    assert _data(state, "surasura_listening_status", {"round_id": rid, "cancel": True}) == \
        {"round_id": rid, "state": "cancelled"}
    assert listening.make_waiting("ja", settings={})["made"] == [] and voice.spoken == []


def test_an_unknown_round_id_is_said_never_a_path(voice):
    state = _known_state(LINES)
    for rid in ("../../settings", "20261114-000000-deadbeef"):
        text, error = _call(state, "surasura_listening_status", {"round_id": rid})
        assert error and ("No saved round" in text or "No listening round" in text)


def test_r1o_again_with_the_voice_off_queues_nothing(voice):
    state = _known_state(LINES)
    rid = _data(state, "surasura_listening_round", {"lines": LINES})["round_id"]
    _data(state, "surasura_listening_status", {"round_id": rid, "cancel": True})
    voice.why, voice.started = "The AI voice is off.", []
    out = _data(state, "surasura_practice_start", {"again": rid})
    assert out == {"round_id": rid, "queued": False, "why": "The AI voice is off."}
    assert listening.read("ja", rid)["state"] == "cancelled" and voice.started == []


def test_r2_a_record_that_cant_be_kept_leaves_no_round_stuck_new(voice, monkeypatch):
    from app.cli import contract
    state = _known_state(LINES)

    def busy(*a, **k):
        raise contract.CliError("busy", "Another call is saving a practice round.")
    monkeypatch.setattr(listening, "keep_record", busy)
    text, error = _call(state, "surasura_listening_round", {"lines": LINES})
    assert error and "couldn't save the round" in text and voice.started == []
    (rid,) = os.listdir(practice_rounds.folder("ja"))
    assert listening.read("ja", rid)["state"] == "failed" and listening.waiting_rounds("ja") == []
