"""Piyo's listening round through the MCP server (app/cli/mcp_server.py → app/listening.py): what the learner's AI
sends and gets back — short answers only (never audio, subtitles or long text), a failed line's words to swap with
nothing made, the voice off or a Chinese round in one sentence, the round queued and its status, again= on a made
round with no voice asked, play and cancel. The voice is the fake of tests/test_listening.py.
"""
import json
import os

import pytest

from app import listening, practice_rounds
from app.cli import mcp_server
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


# --- Iro-V: the round's voice ------------------------------------------------------------------------------------- #
def _with_voices(voice):
    voice.voices = lambda: ["woman-20s", "woman-30s", "man-20s"]
    voice.unknown = lambda name: None if name in voice.voices() else f"There is no voice {name!r}: choose one of x."


def test_a_round_naming_a_voice_keeps_it_and_an_unknown_one_makes_nothing(voice):
    _with_voices(voice)
    state = _known_state(LINES)
    out = _data(state, "surasura_listening_round", {"lines": LINES, "voice": " man-20s "})
    assert out["queued"] is True and listening.read("ja", out["round_id"])["voice"] == "man-20s"
    listening.make_waiting("ja", settings={}, tool=None)
    assert voice.asked == [{"voice": "man-20s"}]
    voice.started = []
    before = set(os.listdir(practice_rounds.folder("ja")))
    text, error = _call(state, "surasura_listening_round", {"lines": LINES, "voice": "robot"})
    assert error and "There is no voice 'robot'" in text and "Nothing was made." in text
    assert voice.started == [] and set(os.listdir(practice_rounds.folder("ja"))) == before


def test_a_round_naming_no_voice_is_queued_for_the_default(voice):
    _with_voices(voice)
    out = _data(_known_state(LINES), "surasura_listening_round", {"lines": LINES})
    assert listening.read("ja", out["round_id"])["voice"] == ""


def test_the_tools_description_lists_the_voices_in_one_line_the_first_the_default(voice):
    async def tools(client):
        return await client.list_tools()

    def described():
        got = _run(_state(), tools)
        (tool,) = [t for t in got.tools if t.name == "surasura_listening_round"]
        schema = tool.input_schema if hasattr(tool, "input_schema") else tool.inputSchema
        return tool.description, schema["properties"]
    text, props = described()
    assert text == mcp_server.LISTENING_ROUND and "voice" in props          # no choice of voices: no voice line
    _with_voices(voice)
    text, _props = described()
    extra = text[len(mcp_server.LISTENING_ROUND):]
    assert text.startswith(mcp_server.LISTENING_ROUND) and "\n" not in extra
    assert "voice: one of woman-20s, woman-30s, man-20s (the first if left out)" in extra and len(extra) < 160


def test_r1_a_rounds_voice_is_listed_and_named_when_its_files_are_gone(voice):
    # review r1 #1: remade from its lines, the round comes back in the voice it had, never the default by accident
    import shutil
    _with_voices(voice)
    state = _known_state(LINES)
    rid = _data(state, "surasura_listening_round", {"lines": LINES, "voice": "woman-30s"})["round_id"]
    listed = _data(state, "surasura_rounds", {})["rounds"]
    assert listed[0]["round_id"] == rid and listed[0]["voice"] == "woman-30s"
    shutil.rmtree(listening.folder("ja", rid))
    text, error = _call(state, "surasura_practice_start", {"again": rid})
    assert "files are gone" in text and "voice=woman-30s" in text
    plain = _data(state, "surasura_listening_round", {"lines": LINES})["round_id"]
    shutil.rmtree(listening.folder("ja", plain))
    text, _error = _call(state, "surasura_practice_start", {"again": plain})
    assert "files are gone" in text and "voice=" not in text
    assert "voice" not in [r for r in _data(state, "surasura_rounds", {})["rounds"] if r["round_id"] == plain][0]


def test_r1_a_voice_of_only_spaces_is_the_default(voice):
    _with_voices(voice)
    out = _data(_known_state(LINES), "surasura_listening_round", {"lines": LINES, "voice": "   "})
    assert out["queued"] is True and listening.read("ja", out["round_id"])["voice"] == ""
