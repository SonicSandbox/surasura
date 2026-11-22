# SPDX-License-Identifier: GPL-3.0-or-later
"""The AI voice's side of a listening round (`modules/irodori/listen.py`, app/listening.py's VOICES["ja"]): the switch
and the install said in one sentence each, every line of a round in ONE listening voice (its caption and seed on each
line, K2's speed; the one named, else the default) on the loopback server, the cards' own voice left as it was,
the one-run lock card audio and rounds share, and a whole round made through
the real module on a fake server. No network, no model: the server is faked (as test_irodori.py's)."""
import io
import os
import wave

import pytest

from app import listening, path_utils, practice_rounds
from modules.irodori import listen, runtime, voice


def _wav(seconds=0.4, rate=24000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x10\x00" * int(seconds * rate))
    return buf.getvalue()


def _free():
    """The voice's one-run lock is free: taken and let go again."""
    held = runtime.running()
    assert held is not None
    path_utils.release_lock(held)


class FakeServer:
    def __init__(self):
        self.spoken, self.started, self.stopped = [], 0, 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def speak(self, text, caption, **kw):
        self.spoken.append((text, caption, kw))
        return _wav(0.2 + 0.02 * len(text))


def test_off_and_not_installed_each_say_one_sentence_with_how_to_turn_it_on(installed):
    assert listen.why_not({}) == listen.OFF and "Settings › App › Beta" in listen.OFF
    assert listen.why_not({"enable_irodori": True}) is None
    os.remove(os.path.join(installed, "installed.json"))
    assert listen.why_not({"enable_irodori": True}) == listen.NOT_INSTALLED and "Install" in listen.NOT_INSTALLED


def test_the_round_asks_the_switch_and_the_install_through_the_table(installed):
    assert listening.why_not("ja", {}) == listen.OFF
    assert listening.why_not("ja", {"enable_irodori": True}) is None
    assert listening.voice("ja") is listen


def test_a_round_with_no_voice_named_is_read_by_the_default_one_voice_on_every_line(installed, ja_sentences):
    # a round keeps ONE voice (its caption and seed on every line), unlike a card's voice chosen per line
    srv = FakeServer()
    pack = voice.packs(runtime.home())[listen.DEFAULT_VOICE]
    with listen.Speaker({}, srv=srv) as speaker:
        for line in ja_sentences[:3]:
            assert speaker.speak(line).startswith(b"RIFF")
    assert [t for t, _c, _k in srv.spoken] == ja_sentences[:3]
    assert {(cap, kw["seed"]) for _t, cap, kw in srv.spoken} == {(pack["caption"], pack["seed"])}
    for _text, _cap, kw in srv.spoken:
        assert kw["speed"] == pack["speed"] == 1.1 and kw["voice"] == "none" and kw["lora"] is None


def test_each_listening_voice_is_one_fixed_caption_and_seed_at_k2s_speed():
    found = listen.voices()
    assert found[0] == listen.DEFAULT_VOICE and len(found) == len(set(found)) and 3 <= len(found) <= 5
    packs = voice.packs()
    assert "k2-natural" not in found                    # the card voice picks per line: never a round's
    for name in found:
        pack = packs[name]
        assert pack["id"] == name and pack["for"] == "listening" and pack["voice"] == "none"
        assert 0 < len(pack["caption"]) <= voice.MAX_CAPTION and isinstance(pack["seed"], int)
        assert pack["speed"] == packs["k2-natural"]["speed"] and pack["steps"] == packs["k2-natural"]["steps"]
        # the same person on a question, a request and an exclamation alike (no per-line who / how)
        lines = ("文化祭まで、あと三日しかないよ。", "二時間目の授業、ちゃんと聞いてた？", "手伝ってくれない？", "冒険！")
        assert {voice.caption(t, pack) for t in lines} == {pack["caption"]}
        assert {voice.seed(t, pack) for t in lines} == {pack["seed"]}
    assert len({packs[n]["caption"] for n in found}) == len(found)      # each a different voice


def test_cards_keep_k2_natural_a_voice_and_a_seed_per_line():
    # k2-natural stays the default for cards: the round's packs change nothing there
    from modules.irodori import SETTINGS_DEFAULTS
    assert SETTINGS_DEFAULTS["irodori_voice"] == voice.DEFAULT == "k2-natural" == voice.pack()["id"]
    k2 = voice.pack()
    assert voice.seed("冒険だ。", k2) == voice.seed("冒険だ。") != voice.seed("冒険する？", k2)
    assert voice.caption("俺が行くぜ。", k2) != voice.caption("あたしが行くわよ。", k2)


def test_a_named_voice_reads_every_line_and_an_unknown_one_is_named_back(installed, ja_sentences):
    srv = FakeServer()
    man = voice.packs()["man-20s"]
    with listen.Speaker({"irodori_voice": "k2-natural"}, srv=srv, voice="man-20s") as speaker:
        for line in ja_sentences[:2]:
            speaker.speak(line)
    assert [(c, k["seed"]) for _t, c, k in srv.spoken] == [(man["caption"], man["seed"])] * 2
    assert listen.unknown("") is None and listen.unknown("man-20s") is None
    said = listen.unknown("robot")
    assert "'robot'" in said and all(name in said for name in listen.voices())


def test_a_voice_gone_since_the_round_was_queued_falls_back_to_the_default(installed):
    srv = FakeServer()
    with listen.Speaker({}, srv=srv, voice="removed-pack") as speaker:
        speaker.speak("冒険だ。")
    assert srv.spoken[0][1] == voice.packs()[listen.DEFAULT_VOICE]["caption"]


def test_with_no_listening_pack_at_all_a_round_reads_in_the_card_voice(installed, monkeypatch):
    monkeypatch.setattr(listen, "_listening_packs", lambda: {})
    srv = FakeServer()
    with listen.Speaker({}, srv=srv) as speaker:
        speaker.speak("冒険だ。")
    k2 = voice.pack()
    assert srv.spoken[0][1] == voice.caption("冒険だ。", k2) and srv.spoken[0][2]["seed"] == voice.seed("冒険だ。")
    assert listen.voices() == []


def test_card_audio_and_a_round_take_turns_on_the_voice(installed):
    held = runtime.running()                     # Backfill's run holds the voice
    try:
        with pytest.raises(listen.Busy, match="making card audio"):
            listen.Speaker({}, srv=FakeServer()).__enter__()
    finally:
        path_utils.release_lock(held)
    with listen.Speaker({}, srv=FakeServer()):
        assert runtime.running() is None         # the round holds it now: card audio waits
    held = runtime.running()                     # and lets it go after
    assert held is not None
    path_utils.release_lock(held)


def test_the_server_it_started_is_stopped_even_when_a_line_fails(installed, monkeypatch):
    made = FakeServer()

    def broken(text, caption, **kw):
        raise RuntimeError("the voice stopped")
    made.speak = broken
    monkeypatch.setattr("modules.irodori.server.Server", lambda: made)
    with pytest.raises(RuntimeError):
        with listen.Speaker({}) as speaker:
            speaker.speak("冒険だ。")
    assert made.stopped == 1
    _free()


def test_a_line_the_voice_cant_read_is_said_in_words():
    assert listen.usable("冒険だ。") is None
    assert listen.usable("冒険！") is None                   # kanji alone: a round's line is Japanese already
    assert listen.usable("OK, see you") == "no Japanese in it"
    assert listen.usable("冒険だ" * 70) == "too long for the voice: 200 characters at most"
    assert listen.usable("冒険" * 100) is None                # 200: the most, still read
    assert listen.usable("冒険" * 101) == "too long for the voice: 200 characters at most"


def test_a_whole_round_through_the_real_module_on_a_fake_server(installed, monkeypatch, ja_sentences):
    srv = FakeServer()
    monkeypatch.setattr("modules.irodori.server.Server", lambda: srv)
    os.makedirs(practice_rounds.folder("ja"), exist_ok=True)
    lines = ja_sentences[:4]
    rid = listening.queue("ja", lines)
    assert listening.make_round("ja", rid, settings={"enable_irodori": True}, tool=None) == "done"
    assert [t for t, _c, _k in srv.spoken] == lines and srv.stopped == 1
    assert listening.read("ja", rid)["files"]["audio"] == "Listening.wav"
    _free()                                      # the voice let go for card audio


def test_a_round_that_names_a_voice_is_made_in_it_through_the_real_module(installed, monkeypatch, ja_sentences):
    srv = FakeServer()
    monkeypatch.setattr("modules.irodori.server.Server", lambda: srv)
    os.makedirs(practice_rounds.folder("ja"), exist_ok=True)
    rid = listening.queue("ja", ja_sentences[:3], voice="storyteller")
    assert listening.make_round("ja", rid, settings={"enable_irodori": True}, tool=None) == "done"
    teller = voice.packs()["storyteller"]
    assert {(c, k["seed"]) for _t, c, k in srv.spoken} == {(teller["caption"], teller["seed"])}
    assert listening.voice_names() == listen.voices()
    _free()


def test_r1_a_server_that_cant_be_made_lets_the_voice_go(installed, monkeypatch):
    def broken():
        raise OSError("no port")
    monkeypatch.setattr("modules.irodori.server.Server", broken)
    with pytest.raises(OSError):
        listen.Speaker({}).__enter__()
    _free()


def test_r1o_on_a_gpu_the_voice_rests_after_each_burst_across_rounds(installed, monkeypatch):
    from modules.irodori import make
    monkeypatch.setattr(listen, "seconds_per_line", lambda: listen.GPU_S)
    monkeypatch.setattr(listen, "_MADE", [0])
    monkeypatch.setattr(listen, "_RESTED", [0])
    rests = []
    for _round in range(2):                         # two rounds in one maker: the count runs across them
        with listen.Speaker({}, srv=FakeServer()) as speaker:
            for n in range(make.BURST):
                rests.append(speaker.rest_before())
                speaker.speak(f"冒険の準備はできていますか？{n}")
    assert [r for r in rests if r] == [make.PAUSE_S] and rests[make.BURST] == make.PAUSE_S
    monkeypatch.setattr(listen, "seconds_per_line", lambda: listen.CPU_S)
    with listen.Speaker({}, srv=FakeServer()) as speaker:
        assert speaker.rest_before() == 0           # the CPU: no rest


def test_r2_the_rest_is_taken_a_second_at_a_time_and_a_cancel_cuts_it(installed, monkeypatch):
    # 180 s in one sleep left a cancel or an update unheard for 3 minutes
    from modules.irodori import make
    monkeypatch.setattr(listen, "seconds_per_line", lambda: listen.GPU_S)
    monkeypatch.setattr(listen, "_MADE", [make.BURST])
    monkeypatch.setattr(listen, "_RESTED", [0])
    monkeypatch.setattr("modules.irodori.server.Server", lambda: FakeServer())
    os.makedirs(practice_rounds.folder("ja"), exist_ok=True)
    rid = listening.queue("ja", ["冒険だ。", "冒険する？"])
    naps = []

    def nap(s):
        naps.append(s)
        if len(naps) == 5:
            listening.cancel("ja", rid)             # (no maker holds the lock here: finished cancelled at once)
    assert listening.make_round("ja", rid, settings={"enable_irodori": True}, sleep=nap, tool=None) == "cancelled"
    assert naps == [1] * 5


def test_r1_with_the_default_pack_gone_a_round_reads_in_the_first_listening_voice_not_the_cards(installed, monkeypatch):
    # the description promises "the first if left out"; the card pack is only for no listening pack at all
    packs = {k: p for k, p in voice.packs().items() if p.get("for") == "listening" and k != listen.DEFAULT_VOICE}
    monkeypatch.setattr(listen, "_listening_packs", lambda: packs)
    srv = FakeServer()
    with listen.Speaker({}, srv=srv) as speaker:
        speaker.speak("冒険だ。")
    assert srv.spoken[0][1] == packs[listen.voices()[0]]["caption"]


def test_r1_an_unknown_voice_is_echoed_short():
    said = listen.unknown("ロボット" * 5000)
    assert len(said) < 300 and all(name in said for name in listen.voices())
