"""Listening rounds (app/listening.py, Piyo-LR): the check before anything is made, the maker (clips -> the joined
track, its subtitles, the copy with pauses), what a stop, a cancel or a crash leaves, again=, the one-maker lock, and
the language -> voice table. The voice is a fake that returns real wav bytes (the AI voice's own suite fakes its
server the same way); every line is real Japanese from tests/Test Resources/ja.
"""
import io
import json
import math
import os
import shutil
import struct
import subprocess
import threading
import wave

import pytest

from app import analyzer, listening, practice, practice_rounds

RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources", "ja", "context_test.txt")
RATE = 24000


def real_lines():
    with open(RES, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def wav_bytes(seconds, rate=RATE, channels=1):
    n = int(round(seconds * rate))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{n * channels}h", *[int(3000 * math.sin(i / 7)) for i in range(n * channels)]))
    return buf.getvalue()


def seconds_of(text):
    """The fake voice's clip length: every line its own (long lines long, short lines short)."""
    return 0.3 + 0.05 * len(text)


class FakeVoice:
    """The voice module's contract (listening.py's docstring): why_not, usable, seconds_per_line, Speaker, Busy."""

    class Busy(Exception):
        pass

    def __init__(self, why=None, fail_on=(), busy_times=0, during=None):
        self.why, self.fail_on, self.busy_times, self.during = why, set(fail_on), busy_times, during
        self.spoken, self.entered, self.inside, self.most_inside = [], 0, 0, 0
        self._lock = threading.Lock()

    def why_not(self, settings):
        return self.why

    def usable(self, text):
        return "too long for the voice: 200 characters at most" if len(text) > 200 else None

    def seconds_per_line(self):
        return 20

    def Speaker(self, settings):            # noqa: N802 (the module's class)
        voice = self

        class _S:
            def __enter__(self):
                with voice._lock:
                    if voice.busy_times:
                        voice.busy_times -= 1
                        raise FakeVoice.Busy("The AI voice is making card audio just now.")
                    voice.entered += 1
                    voice.inside += 1
                    voice.most_inside = max(voice.most_inside, voice.inside)
                return self

            def speak(self, text):
                if voice.during:
                    voice.during(text)
                if text in voice.fail_on:
                    raise RuntimeError("timed out")
                voice.spoken.append(text)
                return wav_bytes(seconds_of(text))

            def __exit__(self, *exc):
                with voice._lock:
                    voice.inside -= 1
        return _S()


@pytest.fixture
def fake(monkeypatch):
    voice = FakeVoice()
    monkeypatch.setitem(listening.VOICES, "ja", lambda: voice)
    monkeypatch.setattr(listening, "start_maker", lambda language, popen=None: None)
    return voice


def _queued(lines, title=""):
    return listening.queue("ja", lines, title)


def _parse_srt(path):
    with open(path, encoding="utf-8") as f:
        blocks = [b for b in f.read().split("\n\n") if b.strip()]
    out = []
    for b in blocks:
        _n, times, text = b.strip().split("\n", 2)
        a, z = times.split(" --> ")
        out.append((_ms(a), _ms(z), text))
    return out


def _ms(stamp):
    hms, ms = stamp.split(",")
    h, m, s = (int(x) for x in hms.split(":"))
    return ((h * 60 + m) * 60 + s) * 1000 + int(ms)


# --- the check: a line that fails is never voiced -------------------------------------------------------------------- #
def _checker(known_texts, unknown=()):
    analyzer.SANITIZE_JA = True
    tokenizer = analyzer.JapaneseTokenizer()
    keys = {(l, r) for text in known_texts for l, r, _s, _o in tokenizer.tokenize(text) if l not in set(unknown)}
    return practice.Checker("ja", settings={}, recent=[], library=(None, 0), known=(keys, {l for l, _r in keys}, set()))


def test_a_line_with_an_unknown_word_names_only_that_line_and_its_word():
    lines = real_lines()[:5] + ["冒険の準備はできていますか？"]
    checker = _checker(lines, unknown={"準備"})
    fixes, _ = listening.check_lines(checker, lines)
    assert fixes == [{"line": 6, "swap": ["準備"]}]


def test_every_known_line_passes_and_the_share_is_the_rounds_not_a_lines():
    # One upcoming word in a short line is 10 % of that line, but well under 3 % of the round: it passes.
    lines = real_lines()
    checker = _checker(lines, unknown={"価値"})
    checker.upcoming = {("価値", "カチ")}
    fixes, counts = listening.check_lines(checker, lines)
    assert fixes == [] and counts["new"] == 1 and counts["words"] > 40


def test_too_many_new_words_for_the_round_names_the_last_lines_until_the_rest_fits():
    lines = real_lines()[:3]                    # few words: one new word is already past 3 %
    checker = _checker(lines, unknown={"冒険"})
    checker.upcoming = {("冒険", "ボウケン")}
    fixes, _ = listening.check_lines(checker, lines)
    assert fixes and all(f["swap"] == ["冒険"] for f in fixes)
    assert fixes[-1]["line"] == 3


def test_a_line_the_voice_cant_read_or_with_no_japanese_is_said_never_cut():
    lines = real_lines()[:2]
    checker = _checker(lines)
    fixes, _ = listening.check_lines(checker, lines + ["冒険" * 101, "OK, see you"],
                                     usable=FakeVoice().usable)
    assert fixes == [{"line": 3, "why": "too long for the voice: 200 characters at most"},
                     {"line": 4, "why": "no Japanese in it"}]


# --- the table: Japanese only, a voice absent, the voice off --------------------------------------------------------- #
def test_a_chinese_round_says_in_one_sentence_it_isnt_ready():
    why = listening.why_not("zh", {})
    assert why == "Listening rounds are Japanese only for now: a Chinese voice isn't ready yet."
    assert why.count(".") == 1


def test_a_build_without_the_voice_says_so(monkeypatch):
    def gone():
        raise ImportError("no module named modules.irodori")
    monkeypatch.setitem(listening.VOICES, "ja", gone)
    assert listening.why_not("ja", {}) == listening.NO_VOICE


def test_the_voice_turned_off_after_queueing_fails_the_round_and_makes_nothing(fake):
    rid = _queued(real_lines()[:2])
    fake.why = "The AI voice is off."
    assert listening.make_round("ja", rid, settings={}) == "failed"
    data = listening.read("ja", rid)
    assert data["state"] == "failed" and data["problem"] == "The AI voice is off." and fake.spoken == []


def test_a_new_language_needs_one_row_and_nothing_else(monkeypatch):
    # The lead (2026-11-14): a Chinese voice plugs in through the table, the round, timing and saving unchanged.
    voice = FakeVoice()
    monkeypatch.setitem(listening.VOICES, "zh", lambda: voice)
    os.makedirs(practice_rounds.folder("zh"), exist_ok=True)
    rid = listening.queue("zh", ["我们明天去公园散步吧。", "今天天气很好。"])
    assert listening.why_not("zh", {}) is None
    assert listening.make_round("zh", rid, settings={}, tool=None) == "done"
    assert voice.spoken == ["我们明天去公园散步吧。", "今天天气很好。"]


# --- the files: the srt is the clips' own times ---------------------------------------------------------------------- #
LINES = ["冒険だ。", "冒険する？", "この本は彼の冒険について書かれている。", "冒険！",
         "ねえ、ＯＫ？　明日の冒険は９時からだよ。"]          # very short, long, mixed scripts and full-width


def test_the_srt_cues_are_the_clips_own_times_in_both_copies_without_ffmpeg(fake):
    rid = _queued(LINES, title="Morning: 冒険/1")
    assert listening.make_round("ja", rid, settings={}, tool=None) == "done"
    data = listening.read("ja", rid)
    here = listening.folder("ja", rid)
    assert data["files"] == {"audio": "Morning 冒険 1.wav", "audio_subtitles": "Morning 冒険 1.srt"}
    assert "ffmpeg" in data["note"]                     # the copy with pauses skipped, and said
    cues = _parse_srt(os.path.join(here, "Morning 冒険 1.srt"))
    at = 0
    for (a, z, text), line in zip(cues, LINES):
        clip = int(round(seconds_of(line) * RATE))
        assert text == line
        assert abs(a - at * 1000 / RATE) <= 1 and abs((z - a) - clip * 1000 / RATE) <= 1
        at += clip + int(round(listening.LINE_GAP_S * RATE))
    with wave.open(os.path.join(here, "Morning 冒険 1.wav")) as w:
        assert w.getnframes() == at                     # the track is the clips and the gaps, nothing else
    for n in range(1, len(LINES) + 1):                  # each line alone, kept
        assert os.path.getsize(os.path.join(here, "lines", f"{n:02d}.wav")) > 0


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_with_ffmpeg_both_mp3s_last_as_long_as_their_subtitles_say_within_a_frame(fake):
    rid = _queued(LINES)
    assert listening.make_round("ja", rid, settings={}) == "done"
    data = listening.read("ja", rid)
    here = listening.folder("ja", rid)
    assert data["files"] == {"audio": "Listening.mp3", "audio_subtitles": "Listening.srt",
                             "with_pauses": "Listening (pauses).mp3",
                             "with_pauses_subtitles": "Listening (pauses).srt"}
    assert "note" not in data and not [n for n in os.listdir(here) if n.endswith((".part", ".wav"))]
    frame = 1152 / RATE                                 # one mp3 frame
    for mp3, srt_name, gap in (("Listening.mp3", "Listening.srt", listening.LINE_GAP_S),
                               ("Listening (pauses).mp3", "Listening (pauses).srt", listening.PAUSE_S)):
        pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", os.path.join(here, mp3), "-f", "s16le", "-ac", "1",
                              "-"], capture_output=True).stdout          # as a player decodes it (its gapless header read)
        got = len(pcm) / 2 / RATE
        cues = _parse_srt(os.path.join(here, srt_name))
        assert abs(got - (cues[-1][1] / 1000 + gap)) <= frame + 0.002
        for (a, z, _t), line in zip(cues, LINES):
            assert abs((z - a) / 1000 - seconds_of(line)) <= 0.001
    pauses = _parse_srt(os.path.join(here, "Listening (pauses).srt"))
    assert all(abs((b[0] - a[1]) / 1000 - listening.PAUSE_S) <= 0.001 for a, b in zip(pauses, pauses[1:]))


def test_a_float_wav_is_joined_as_16_bit():
    floats = struct.pack("<4f", 0.0, 0.5, -0.5, 2.0)
    fmt = struct.pack("<HHIIHH", 3, 1, RATE, RATE * 4, 4, 32)
    data = b"RIFF" + struct.pack("<I", 36 + len(floats)) + b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + \
        b"data" + struct.pack("<I", len(floats)) + floats
    rate, channels, pcm = listening.read_wav(data)
    assert (rate, channels) == (RATE, 1) and struct.unpack("<4h", pcm) == (0, 16383, -16383, 32767)
    with pytest.raises(ValueError):
        listening.read_wav(b"ID3\x04 not a wav at all")


def test_the_files_name_takes_nothing_of_a_path():
    assert listening.base_name('..\\..\\x/y:"z"') == "x y z"
    assert listening.base_name("   ") == listening.NAME and len(listening.base_name("冒" * 99)) == listening.TITLE_CHARS


# --- a stop, a cancel, a crash: never a half round marked done -------------------------------------------------------- #
def test_a_cancel_between_two_lines_stops_it_and_marks_nothing_done(fake):
    lines = LINES[:4]
    rid = _queued(lines)
    fake.during = lambda text: text == lines[1] and listening.cancel("ja", rid)
    monkey_running = listening.maker_running
    listening.maker_running = lambda: True              # a maker is at work: the cancel is its to see
    try:
        assert listening.make_round("ja", rid, settings={}, tool=None) == "cancelled"
    finally:
        listening.maker_running = monkey_running
    data = listening.read("ja", rid)
    here = listening.folder("ja", rid)
    assert data["state"] == "cancelled" and "files" not in data
    assert fake.spoken == lines[:2] and sorted(os.listdir(os.path.join(here, "lines"))) == ["01.wav", "02.wav"]
    assert not [n for n in os.listdir(here) if n.endswith((".srt", ".mp3", ".wav", ".part"))]


def test_a_crash_mid_make_is_left_making_and_the_next_maker_voices_only_whats_missing(fake):
    lines = LINES[:4]
    rid = _queued(lines)

    def crash(text):
        if text == lines[2]:
            raise SystemExit("the process ended")     # not an error the round catches: the process is gone
    fake.during = crash
    with pytest.raises(SystemExit):
        listening.make_round("ja", rid, settings={}, tool=None)
    assert listening.read("ja", rid)["state"] == "making"
    assert listening.waiting_rounds("ja") == [rid]
    fake.during, fake.spoken = None, []
    got = listening.make_waiting("ja", settings={})
    assert got == {"made": [rid], "left": 0, "busy": False}
    assert fake.spoken == lines[2:] and listening.read("ja", rid)["state"] == "done"


def test_a_line_the_voice_fails_fails_the_round_by_its_number(fake):
    rid = _queued(LINES[:3])
    fake.fail_on = {LINES[1]}
    assert listening.make_round("ja", rid, settings={}, tool=None) == "failed"
    assert listening.read("ja", rid)["problem"] == "The AI voice couldn't read line 2 (timed out)."


def test_a_stop_for_an_update_leaves_it_for_the_next_maker(fake):
    rid = _queued(LINES[:3])
    looks = iter([False, False, True])
    assert listening.make_waiting("ja", settings={}, should_stop=lambda: next(looks, True))["made"] == []
    assert listening.read("ja", rid)["state"] == "making" and len(fake.spoken) == 1


def test_a_disk_that_refuses_the_files_fails_it_with_the_clips_kept(fake, monkeypatch):
    rid = _queued(LINES[:2])

    def full(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(listening, "build", full)
    assert listening.make_round("ja", rid, settings={}, tool=None) == "failed"
    assert "No space left" in listening.read("ja", rid)["problem"]


# --- again=: a made round costs nothing ------------------------------------------------------------------------------- #
def test_again_on_a_made_round_voices_nothing_and_on_a_cancelled_one_makes_only_the_rest(fake):
    rid = _queued(LINES[:3])
    assert listening.make_round("ja", rid, settings={}, tool=None) == "done"
    fake.spoken = []
    assert listening.again("ja", rid) is False and fake.spoken == []
    other = _queued(LINES[:3])
    fake.during = lambda text: text == LINES[0] and listening.cancel("ja", other)
    listening.maker_running, saved = (lambda: True), listening.maker_running
    try:
        listening.make_round("ja", other, settings={}, tool=None)
    finally:
        listening.maker_running = saved
    fake.during, fake.spoken = None, []
    assert listening.again("ja", other) is True
    assert listening.make_round("ja", other, settings={}, tool=None) == "done" and fake.spoken == LINES[1:3]


# --- two rounds at once: they queue, never collide --------------------------------------------------------------------- #
def test_two_makers_at_once_make_each_round_once_and_never_hold_the_voice_together(fake):
    a, b = _queued(LINES[:3]), _queued(LINES[2:5])
    gate = threading.Event()
    fake.during = lambda text: gate.wait(5)
    results = []
    threads = [threading.Thread(target=lambda: results.append(listening.make_waiting("ja", settings={},
                                                                                      sleep=lambda s: None)))
               for _ in range(2)]
    threads[0].start()
    while fake.entered == 0:
        pass
    threads[1].start()
    threads[1].join(5)
    gate.set()
    threads[0].join(10)
    assert sorted(r["busy"] for r in results) == [False, True]
    assert next(r for r in results if not r["busy"])["made"] == [a, b]
    assert fake.most_inside == 1 and len(fake.spoken) == 6
    assert listening.read("ja", a)["state"] == listening.read("ja", b)["state"] == "done"


def test_a_round_waits_its_turn_while_card_audio_holds_the_voice(fake):
    rid = _queued(LINES[:2])
    fake.busy_times = 2
    naps = []
    assert listening.make_round("ja", rid, settings={}, sleep=naps.append, tool=None) == "done"
    assert naps == [listening.BUSY_LOOK_S] * 2
    assert "waiting" not in listening.read("ja", rid)


def test_status_says_how_many_lines_are_ready_and_starts_a_maker_none_is_running(fake, monkeypatch):
    started = []
    monkeypatch.setattr(listening, "start_maker", lambda language, popen=None: started.append(language))
    rid = _queued(LINES[:3])
    out = listening.status("ja", rid)
    assert out["state"] == "queued" and (out["ready"], out["of"]) == (0, 3) and started == ["ja"]
    assert "min left" in out["next"] and len(json.dumps(out, ensure_ascii=False)) < 600


# --- the maker's own process --------------------------------------------------------------------------------------- #
def test_the_maker_starts_below_normal_as_this_installs_cli_out_of_the_ai_apps_job(monkeypatch):
    calls = []

    def popen(argv, **kw):
        calls.append((argv, kw))
        if len(calls) == 1 and os.name == "nt":
            raise PermissionError(5, "Access is denied")     # a job that forbids breakaway
        return object()
    assert listening.start_maker("ja", popen=popen) is not None
    argv, kw = calls[-1]
    assert argv[-3:] == ["_listen", "--lang", "ja"] and argv[-5:-3] == ["-m", "app.cli"]
    assert kw["stdin"] == kw["stdout"] == subprocess.DEVNULL and "PYTHONPATH" in kw["env"]
    if os.name == "nt":
        assert kw["creationflags"] & 0x00004000 and kw["creationflags"] & listening.NO_WINDOW
        assert calls[0][1]["creationflags"] & 0x01000000 and not kw["creationflags"] & 0x01000000


def test_the_makers_verb_is_hidden_from_help():
    from app.cli import __main__ as cli
    assert cli.VERBS["_listen"][2] is False
    args = cli._parser().parse_args(["_listen", "--lang", "ja"])
    assert args.verb == "_listen" and args.lang == "ja"


def test_open_file_hands_it_to_the_systems_player(tmp_path):
    if os.name != "nt":
        pytest.skip("Windows' shell open")
    opened = []
    listening.open_file(str(tmp_path / "Listening.mp3"), startfile=opened.append)
    assert opened == [str(tmp_path / "Listening.mp3")]


# --- review r1 (Haiku lenses: bounds, state) ------------------------------------------------------------------------- #
def test_r1_every_use_of_a_new_word_counts_toward_the_rounds_share():
    # The checker counts each use of an unknown word: a word used twice is two of the round's new uses.
    lines = ["冒険は危険だが、冒険には価値がある。"] + [x for x in real_lines() if "価値" not in x]
    checker = _checker(lines, unknown={"価値"})
    checker.upcoming = {("価値", "カチ")}
    once, counts = listening.check_lines(checker, lines)
    assert once == [] and counts["new"] == 1                    # 1 use in ~60 words: under 3 %
    twice, counts = listening.check_lines(checker, ["価値がある。価値がある。"] + lines)
    assert counts["new"] == 3 and {f["line"] for f in twice} == {1, 2}           # 3 uses: past it, both named
    assert all(f["swap"] == ["価値"] for f in twice)


def test_r1_a_clip_with_no_audio_fails_its_line(fake, monkeypatch):
    rid = _queued(LINES[:2])
    monkeypatch.setattr("tests.test_listening.wav_bytes", lambda seconds, rate=RATE, channels=1: _empty_wav())
    assert listening.make_round("ja", rid, settings={}, tool=None) == "failed"
    assert listening.read("ja", rid)["problem"] == "The AI voice couldn't read line 1 (no audio came back)."


def _empty_wav():
    import io as _io
    buf = _io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
    return buf.getvalue()


@pytest.mark.parametrize("title", ["CON", "nul", "com1", "Aux.", "lpt9.txt"])
def test_r1_a_title_windows_keeps_for_a_device_is_never_the_files_name(title):
    name = listening.base_name(title)
    assert name.split(".")[0].strip().upper() not in listening._RESERVED and name.startswith(listening.NAME)


def test_r1_a_long_why_is_cut_short_for_the_ai(fake):
    rid = _queued(LINES[:2])
    fake.fail_on = {LINES[0]}
    fake.speak_error = "x" * 5000
    real = FakeVoice.Speaker

    def long_error(self, settings):
        s = real(self, settings)
        speak = s.speak

        def failing(text):
            if text in self.fail_on:
                raise RuntimeError("timed out " + "あ" * 5000)
            return speak(text)
        s.speak = failing
        return s
    FakeVoice.Speaker = long_error
    try:
        assert listening.make_round("ja", rid, settings={}, tool=None) == "failed"
    finally:
        FakeVoice.Speaker = real
    assert len(listening.read("ja", rid)["problem"]) <= listening.PROBLEM_CHARS


def test_r1_every_line_break_kind_becomes_a_space_in_the_subtitles():
    for brk in ("\n", "\r\n", "\u2028", "\u2029", "\x85", "\x1c", "\t"):
        assert listening.one_line(f"冒険{brk}{brk}だ。") == "冒険 だ。"
    assert listening.one_line("ねえ、\u3000明日") == "ねえ、\u3000明日"          # its own spaces kept


def test_r1_a_short_format_chunk_is_a_wav_this_cant_join():
    data = b"RIFF" + struct.pack("<I", 20) + b"WAVE" + b"fmt " + struct.pack("<I", 4) + b"\x01\x00\x01\x00"
    with pytest.raises(ValueError):
        listening.read_wav(data)


def test_r1_a_cancel_with_no_maker_is_cancelled_at_once_and_with_one_waits_for_it(fake):
    from app import path_utils
    rid = _queued(LINES[:2])
    held = path_utils.try_lock(listening._lock_path())          # a maker at work
    try:
        assert listening.cancel("ja", rid) == "cancelling"
        assert listening.read("ja", rid)["state"] == "queued"   # never rewritten under the maker
        assert listening.status("ja", rid, start=False)["state"] == "cancelling"
    finally:
        path_utils.release_lock(held)
    other = _queued(LINES[:2])
    assert listening.cancel("ja", other) == "cancelled" and listening.read("ja", other)["state"] == "cancelled"


def test_r1_again_on_a_round_on_its_way_never_rewrites_it(fake):
    from app import path_utils
    rid = _queued(LINES[:2])
    before = listening.read("ja", rid)
    held = path_utils.try_lock(listening._lock_path())          # a maker at work
    try:
        assert listening.again("ja", rid) is True and listening.read("ja", rid) == before
    finally:
        path_utils.release_lock(held)


def test_r1_a_round_whose_record_the_disk_refuses_is_tried_once_a_run_never_forever(fake, monkeypatch):
    rid = _queued(LINES[:2])
    real = listening._finish

    def refused(language, round_id, data, state, problem=None):
        if state == "done":
            raise PermissionError(13, "held open")
        return real(language, round_id, data, state, problem)
    monkeypatch.setattr(listening, "_finish", refused)
    got = listening.make_waiting("ja", settings={}, tool=None, sleep=lambda s: None)
    assert got["made"] == [] and got["left"] == 1 and listening.read("ja", rid)["state"] == "making"
    monkeypatch.setattr(listening, "_finish", real)
    fake.spoken = []
    assert listening.make_waiting("ja", settings={}, tool=None)["made"] == [rid] and fake.spoken == []


def test_r1_a_made_round_whose_files_were_moved_says_again_makes_them(fake):
    rid = _queued(LINES[:2])
    listening.make_round("ja", rid, settings={}, tool=None)
    os.remove(os.path.join(listening.folder("ja", rid), "Listening.wav"))
    out = listening.status("ja", rid)
    assert "moved or deleted" in out["next"]
    assert listening.again("ja", rid) is True
    fake.spoken = []
    assert listening.make_round("ja", rid, settings={}, tool=None) == "done" and fake.spoken == []


def test_r1_a_cancel_clears_a_half_written_clip(fake):
    rid = _queued(LINES[:2])
    part = os.path.join(listening.folder("ja", rid), "lines", "01.wav.part")
    with open(part, "wb") as f:
        f.write(b"RIFF")
    listening.cancel("ja", rid)
    assert not os.path.exists(part)


def test_r1_a_new_round_is_never_taken_before_its_record_is_written(fake):
    rid = listening.queue("ja", LINES[:2], state="new")
    assert listening.waiting_rounds("ja") == []
    listening.ready("ja", rid)
    assert listening.waiting_rounds("ja") == [rid]


# --- review r1 (Opus) -------------------------------------------------------------------------------------------- #
def test_r1o_a_made_rounds_answer_names_its_files_and_never_a_path(fake):
    rid = _queued(LINES[:2])
    listening.make_round("ja", rid, settings={}, tool=None)
    text = json.dumps(listening.status("ja", rid), ensure_ascii=False)
    assert os.sep not in text.replace(" › ", "") and os.path.expanduser("~") not in text
    assert listening.status("ja", rid)["files"]["audio"] == "Listening.wav"


def test_r1o_a_round_its_maker_never_finishes_is_failed_after_a_few_tries(fake):
    rid = _queued(LINES[:2])

    def killed(text):
        raise SystemExit("killed")
    fake.during = killed
    for _ in range(listening.TRIES):
        with pytest.raises(SystemExit):
            listening.make_round("ja", rid, settings={}, tool=None)
    fake.during = None
    assert listening.make_round("ja", rid, settings={}, tool=None) == "failed"
    assert "stopped 3 times" in listening.read("ja", rid)["problem"]
    assert listening.again("ja", rid) and listening.make_round("ja", rid, settings={}, tool=None) == "done"


def test_r1o_the_maker_steps_aside_only_on_the_same_reason_twice(monkeypatch, fake):
    from app.cli import mcp_server
    looks = iter([None, "an update is staged", None, "an update is staged", "an update is staged"])
    monkeypatch.setattr(mcp_server, "why_step_aside", lambda: next(looks, "an update is staged"))
    got = []
    monkeypatch.setattr(listening, "make_waiting", lambda lang, should_stop: got.extend(
        should_stop() for _ in range(5)) or {"made": [], "left": 0, "busy": False})
    listening.verb(type("A", (), {"lang": "ja"})())
    assert got == [False, False, False, False, True]


# --- review r2 (Opus) -------------------------------------------------------------------------------------------- #
def test_r2_an_errors_filename_never_reaches_the_ai(fake):
    rid = _queued(LINES[:2])
    fake.fail_on = set()
    real = FakeVoice.Speaker

    def denied(self, settings):
        s = real(self, settings)

        def speak(text):
            raise PermissionError(13, "Permission denied", r"C:\Users\someone\AppData\Local\run\server.log")
        s.speak = speak
        return s
    FakeVoice.Speaker = denied
    try:
        listening.make_round("ja", rid, settings={}, tool=None)
    finally:
        FakeVoice.Speaker = real
    problem = listening.read("ja", rid)["problem"]
    assert problem == "The AI voice couldn't read line 1 (Permission denied)." and "someone" not in problem


def test_r2_a_cancel_whose_maker_died_is_finished_by_the_next_status(fake):
    from app import path_utils
    rid = _queued(LINES[:2])
    held = path_utils.try_lock(listening._lock_path())
    assert listening.cancel("ja", rid) == "cancelling"
    path_utils.release_lock(held)                   # the maker is killed before it looks again
    assert listening.status("ja", rid)["state"] == "cancelled"
    assert listening.read("ja", rid)["state"] == "cancelled"


def test_r2_a_round_queued_again_during_a_run_is_made_in_that_run(fake):
    a, b = _queued(LINES[:2]), _queued(LINES[2:4])

    def during(text):
        if text == LINES[0]:
            assert listening.cancel("ja", a) == "cancelling"        # the maker (this run) holds the lock
        if text == LINES[2]:
            assert listening.again("ja", a) is True                 # asked again while b is made
    fake.during = during
    got = listening.make_waiting("ja", settings={}, tool=None, sleep=lambda s: None)
    assert got["made"] == [b, a] and listening.read("ja", a)["state"] == "done"


def test_r2_a_voice_busy_past_the_wait_says_what_happened(fake, monkeypatch):
    monkeypatch.setattr(listening, "BUSY_WAIT_S", 20)
    rid = _queued(LINES[:2])
    fake.busy_times = 99
    assert listening.make_round("ja", rid, settings={}, sleep=lambda s: None, tool=None) == "failed"
    assert listening.read("ja", rid)["problem"] == "The AI voice stayed busy making card audio for 0 minutes."


def test_r2_again_on_a_round_killed_three_times_starts_its_tries_over(fake):
    rid = _queued(LINES[:2])
    listening._write("ja", rid, dict(listening.read("ja", rid), state="making", tries=listening.TRIES))
    assert listening.again("ja", rid) is True and listening.read("ja", rid)["tries"] == 0
    assert listening.make_round("ja", rid, settings={}, tool=None) == "done"


def test_r2_a_stop_for_an_update_is_not_one_of_the_tries(fake):
    rid = _queued(LINES[:2])
    for _ in range(listening.TRIES + 2):
        assert listening.make_round("ja", rid, settings={}, should_stop=lambda: True, tool=None) == "stopped"
    assert listening.read("ja", rid)["state"] == "making" and listening.read("ja", rid)["tries"] == 0
    assert listening.make_round("ja", rid, settings={}, tool=None) == "done"
    assert listening.make_round("ja", rid, settings={}, tool=None) == "done" and len(fake.spoken) == 2  # made once
