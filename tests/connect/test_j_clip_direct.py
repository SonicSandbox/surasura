"""J-CLIP 3: the journey's ▶ cuts a line's clip with Anki Miner's own ffmpeg and Anki Miner's own arguments (the
direct cut, `clips._direct`), and falls back to Anki Miner's `media` (`add_audio.cut`) whenever it can't.

What each test holds still:
- **Anki Miner's command, argument for argument:** `clips.command` equals the ffmpeg command Anki Miner 3.13's own
  `media_extractor` builds for the same line and settings (recorded from its source with ffmpeg stubbed): the padding
  each side and never before 0, the stream, libmp3lame / libopus (capped at 256 kbps), mono, the loudness filter and
  its fades only while the profile's switch is on. A change on either side is a red test here, not a silent drift;
- **Anki Miner's stream:** the audio stream its rule picks — tagged with the language's code (a regional variant
  too, never a mere prefix), the default of several, the only one there is; several none tagged so go to `media`;
- **the profile's settings:** read from its export once, again only once Anki Miner's files change; 3.5's export has
  no loudness switch (off); a value not Anki Miner's kind goes to `media`;
- **a file's first press pays the ffprobe, the next ones don't;**
- **the fallback says nothing:** no bundled ffmpeg (a source checkout, the suite's fake), the cut failing, no
  settings — the line is cut by `media` as before; an Anki Miner too old for `media` still plays through the direct
  cut, and only when neither can cut is the learner told to update;
- **the cut ahead claims its lines:** a press on a line being cut ahead waits for that cut, never starts another;
  a press between lines stops the rest;
- **the same bytes:** where an Anki Miner with `media` and a real .mkv are named (SURASURA_SAME_BYTES_*), the direct
  cut's clip is `media`'s byte for byte; skipped with its reason elsewhere.

What a wrong answer costs: a ▶ that plays another track (the English dub), louder or softer than the card, a clip
cut a little off the line — or one that stops playing when Anki Miner changes. Real Japanese and Chinese lines from
tests/Test Resources; ffmpeg's own (PATH's) for the cuts that need a real one, skipped without it.
"""
import json
import os
import shutil
import subprocess
import threading

import pytest

from app import cues
from app.connect import add_audio, anki_miner, clips, lineup

RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Test Resources")
SUBS = {"ja": os.path.join(RESOURCES, "ja", "placed_episode.srt"),
        "zh": os.path.join(RESOURCES, "zh", "night_market.srt")}
ITEM = 7
TAG = {"ja": "jpn", "zh": "chi"}
FFMPEG, FFPROBE = shutil.which("ffmpeg"), shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="no ffmpeg / ffprobe on PATH on this PC")

# Anki Miner 3.13's own command (`MediaExtractorService.extract_media` -> `_extract_audio`, ffmpeg stubbed, stream 1),
# recorded from its source on 2026-11-23 (the register's § J-CLIP 3): (start ms, end ms, settings, argv[1:-1])
RECORDED = [
    (62345, 64100, {"padding": 0.3, "format": "mp3", "bitrate": 192, "normalize": False},
     ["-y", "-ss", "62.045", "-t", "2.3549999999999955", "-i", "C:\\Videos\\Show\\ep 01.mkv", "-map", "0:1", "-vn",
      "-acodec", "libmp3lame", "-b:a", "192k", "-ac", "1"]),
    (1234567, 1239001, {"padding": 0.3, "format": "opus", "bitrate": 320, "normalize": True},
     ["-y", "-ss", "1234.267", "-t", "5.033999999999969", "-i", "C:\\Videos\\Show\\ep 01.mkv", "-map", "0:1", "-vn",
      "-acodec", "libopus", "-b:a", "256k", "-ac", "1", "-af",
      "loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=in:d=0.03,afade=t=out:st=5.004:d=0.03", "-ar", "48000"]),
    (120, 1980, {"padding": 0.5, "format": "mp3", "bitrate": 96, "normalize": False},
     ["-y", "-ss", "0.0", "-t", "2.48", "-i", "C:\\Videos\\Show\\ep 01.mkv", "-map", "0:1", "-vn", "-acodec",
      "libmp3lame", "-b:a", "96k", "-ac", "1"]),
    (5000, 5010, {"padding": 0.0, "format": "mp3", "bitrate": 128, "normalize": True},
     ["-y", "-ss", "5.0", "-t", "0.009999999999999787", "-i", "C:\\Videos\\Show\\ep 01.mkv", "-map", "0:1", "-vn",
      "-acodec", "libmp3lame", "-b:a", "128k", "-ac", "1", "-af",
      "loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=in:d=0.03,afade=t=out:st=0.000:d=0.03", "-ar", "48000"]),
]
EXPORT_313 = {"anki_miner_settings": 1, "app_version": "3.13.0", "settings": {
    "audio_padding": 0.3, "audio_format": "mp3", "audio_bitrate": 192, "normalize_audio_loudness": False}}
EXPORT_350 = {"anki_miner_settings": 1, "app_version": "3.5.0", "settings": {
    "audio_padding": 0.3, "audio_format": "mp3", "audio_bitrate": 192}}


@pytest.fixture(autouse=True)
def _fresh_caches(monkeypatch):
    """Each test starts with no settings and no streams kept (they are the process's, kept across presses)."""
    monkeypatch.setattr(clips, "_known", {})
    monkeypatch.setattr(clips, "_streams", {})


# --------------------------------------------------------------------------- #
# Anki Miner's own command and stream, pinned
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("start_ms, end_ms, got, recorded", RECORDED)
def test_the_cut_is_anki_miners_own_command_argument_for_argument(start_ms, end_ms, got, recorded):
    out = r"H:\out\clip." + got["format"]
    made = clips.command("ffmpeg", r"C:\Videos\Show\ep 01.mkv", cues.seconds(start_ms), cues.seconds(end_ms), 1, got,
                         out)
    assert made == ["ffmpeg"] + recorded + [out]
    assert "-frames:v" not in made and "-vf" not in made       # no picture is made


def _streams(*specs):
    """ffprobe's audio streams: (index, language tag or None, default?, title or None) each."""
    out = []
    for index, tag, default, title in specs:
        tags = {k: v for k, v in (("language", tag), ("title", title)) if v is not None}
        out.append({"index": index, "codec_name": "aac", "tags": tags, "disposition": {"default": int(default)}})
    return out


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_stream_is_the_one_tagged_with_the_language_the_default_of_several_else_the_first(lang):
    tag = TAG[lang]
    # an English dub first, the learner's language second: Anki Miner's rule takes the second
    assert clips.pick_stream(_streams((1, "eng", True, None), (2, tag, False, None)), lang) == 2
    # two in the language: the default one, else the first
    assert clips.pick_stream(_streams((1, tag, False, "Commentary"), (2, tag, True, None)), lang) == 2
    assert clips.pick_stream(_streams((1, "eng", True, None), (3, tag, False, None), (4, tag, False, None)), lang) == 3
    # a regional variant counts; upper case too
    assert clips.pick_stream(_streams((1, "eng", True, None), (5, f"{lang}-XX".upper(), False, None)), lang) == 5


def test_a_prefix_is_not_the_language_and_several_streams_none_tagged_so_go_to_media():
    # "jav" (Javanese) starts like "ja" but isn't it; with two streams Anki Miner reads titles: `media` cuts those
    assert clips.pick_stream(_streams((1, "jav", True, None), (2, "eng", False, "日本語")), "ja") is None
    assert clips.pick_stream(_streams((1, None, True, "Japanese"), (2, "und", False, None)), "ja") is None
    # one stream, whatever its tag: the one Anki Miner takes too
    assert clips.pick_stream(_streams((1, "eng", True, None)), "ja") == 1
    assert clips.pick_stream(_streams((1, None, False, None)), "zh") == 1
    # none at all, a stream with no index, a language Anki Miner's rule isn't read for here: `media`
    assert clips.pick_stream([], "ja") is None
    assert clips.pick_stream([{"codec_name": "aac"}], "ja") is None
    assert clips.pick_stream(_streams((1, "kor", True, None)), "ko") is None


def test_the_profiles_settings_are_its_exports_and_one_not_anki_miners_kind_goes_to_media():
    assert clips.audio_settings(EXPORT_313) == {"padding": 0.3, "format": "mp3", "bitrate": 192, "normalize": False}
    # 3.5 had no loudness switch: it never filtered
    assert clips.audio_settings(EXPORT_350) == {"padding": 0.3, "format": "mp3", "bitrate": 192, "normalize": False}
    on = {"settings": dict(EXPORT_313["settings"], normalize_audio_loudness=True, audio_format="opus")}
    assert clips.audio_settings(on) == {"padding": 0.3, "format": "opus", "bitrate": 192, "normalize": True}
    for bad in ({"audio_padding": "0.3"}, {"audio_padding": -1}, {"audio_padding": True}, {"audio_bitrate": 0},
                {"audio_bitrate": 192.5}, {"audio_format": "wav"}, {"normalize_audio_loudness": "yes"},
                {"audio_padding": None}, {"audio_padding": float("inf")}, {"audio_padding": float("nan")}):
        assert clips.audio_settings({"settings": dict(EXPORT_313["settings"], **bad)}) is None, bad
    assert clips.audio_settings(None) is None and clips.audio_settings({"settings": []}) is None


# --------------------------------------------------------------------------- #
# A press: the direct cut, its fallback
# --------------------------------------------------------------------------- #
class Steps:
    def __init__(self, subtitle, video):
        self._subtitle, self._video = subtitle, video

    def subtitle(self, lang, job):
        return self._subtitle

    def video(self, lang, job):
        return self._video


def _id(cue):
    return f"{ITEM}:{int(round(cues.seconds(cue.start) * 1000))}"


@pytest.fixture
def episode(tmp_path, fake_miner, monkeypatch):
    """-> (lang) -> dict: the language's real subtitle, an .mkv beside it, Steps, Connect on, the fake Anki Miner
    (`media` answers) and a stand-in for the direct cut's pieces the test turns."""
    monkeypatch.setattr(anki_miner, "can_now", lambda asks: set(asks) <= {"Z-10"})
    exports = []
    monkeypatch.setattr(anki_miner, "settings_export",
                        lambda path, lang, out, profile=None, timeout=None: exports.append(lang) or EXPORT_313)
    stamp = {"now": ("files", 1)}
    monkeypatch.setattr(anki_miner, "stamp", lambda path: stamp["now"])

    def make(lang):
        video = tmp_path / f"episode-{lang}.mkv"
        video.write_bytes(b"\x1aE\xdf\xa3 matroska")
        return {"lang": lang, "lines": list(cues.read(SUBS[lang], lang)), "video": str(video),
                "steps": Steps(SUBS[lang], str(video)), "settings": {"connect_enabled": True},
                "miner": fake_miner.path, "exports": exports, "stamp": stamp}
    return make


def _cut(ep, cue):
    return clips.cut(ep["lang"], _id(cue), settings=ep["settings"], steps=ep["steps"], miner=ep["miner"])


def _media_calls(fake):
    return [c for c in fake.calls() if "media_lines" in c]


def _fake_direct(monkeypatch, made):
    """The direct cut's ffmpeg / ffprobe as stand-ins: ffprobe lists an English stream then the language's (the
    returned list takes the language), every cut writes its clip holding the command it was given."""
    monkeypatch.setattr(clips, "_binaries", lambda miner: ("ffmpeg.exe", "ffprobe.exe"))
    made_lang = []

    def run(cmd, below=False, stdout=False):
        if os.path.basename(cmd[0]) == "ffprobe.exe":
            made.append(("probe", cmd[-1]))
            listed = [{"index": 1, "tags": {"language": "eng"}}, {"index": 2, "tags": {"language": TAG[made_lang[0]]}}]
            return json.dumps({"streams": listed}).encode()
        made.append(("cut", cmd, below))
        with open(cmd[-1], "w", encoding="utf-8") as f:
            f.write(" ".join(cmd))
        return b""
    monkeypatch.setattr(clips, "_run", run)
    return made_lang


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_press_cuts_with_anki_miners_ffmpeg_and_never_starts_anki_miner(episode, fake_miner, monkeypatch, lang):
    ep = episode(lang)
    made = []
    _fake_direct(monkeypatch, made).append(lang)
    cue = ep["lines"][1]
    path = _cut(ep, cue)
    assert path.endswith(".mp3") and os.path.dirname(path) == clips.root()
    cut = [m for m in made if m[0] == "cut"]
    assert len(cut) == 1 and cut[0][2] is False                 # the press: normal priority
    assert cut[0][1] == clips.command("ffmpeg.exe", ep["video"], cues.seconds(cue.start), cues.seconds(cue.end), 2,
                                      clips.audio_settings(EXPORT_313), cut[0][1][-1])
    assert _media_calls(fake_miner) == []                       # Anki Miner itself not started for it
    assert [d for d in os.listdir(clips.root()) if d.startswith(".run-")] == []


def test_a_files_first_press_pays_the_probe_and_the_settings_are_read_once(episode, monkeypatch):
    ep = episode("ja")
    made = []
    _fake_direct(monkeypatch, made).append("ja")
    for cue in ep["lines"][:3]:
        _cut(ep, cue)
    assert [m for m in made if m[0] == "probe"] == [("probe", ep["video"])]     # one file: one ffprobe
    assert ep["exports"] == ["ja"]
    ep["stamp"]["now"] = ("files", 2)                           # a profile saved in Anki Miner: read again
    _cut(ep, ep["lines"][4])
    assert ep["exports"] == ["ja", "ja"]
    os.utime(ep["video"], ns=(1, 1))                            # the file replaced: its stream asked again
    _cut(ep, ep["lines"][5])
    assert [m for m in made if m[0] == "probe"] == [("probe", ep["video"])] * 2


def test_a_failed_export_is_not_asked_again_on_every_press(episode, fake_miner, monkeypatch):
    ep = episode("ja")
    asked = []

    def broken(path, lang, out, profile=None, timeout=None):
        asked.append(timeout)
        raise anki_miner.AnkiMinerError("timeout", "no answer")
    monkeypatch.setattr(anki_miner, "settings_export", broken)
    monkeypatch.setattr(clips, "_binaries", lambda miner: ("ffmpeg.exe", "ffprobe.exe"))
    _cut(ep, ep["lines"][0])
    _cut(ep, ep["lines"][1])
    assert asked == [clips.SETTINGS_TIMEOUT]                    # once, and a press waits less than Connect's look-ups
    assert len(_media_calls(fake_miner)) == 2                   # both played, through media


@pytest.mark.parametrize("why", ["no bundled ffmpeg", "ffmpeg failed", "no stream", "no settings", "raised"])
def test_whatever_keeps_the_direct_cut_from_working_media_cuts_the_line_and_nothing_is_said(
        episode, fake_miner, monkeypatch, why):
    ep = episode("ja")
    monkeypatch.setattr(clips, "_binaries", lambda miner: None if why == "no bundled ffmpeg" else ("f", "p"))
    monkeypatch.setattr(clips, "_settings", lambda miner, lang: None if why == "no settings" else
                        clips.audio_settings(EXPORT_313))

    def stream(ffprobe, video, lang, below=False):
        if why == "raised":
            raise OSError("the share went away")
        return None if why == "no stream" else 1
    monkeypatch.setattr(clips, "_stream", stream)
    monkeypatch.setattr(clips, "_run", lambda cmd, below=False, stdout=False: None)     # ffmpeg exits non-zero
    cue = ep["lines"][2]
    path = _cut(ep, cue)
    with open(path, encoding="utf-8") as f:
        assert cue.text in f.read()                             # the fake's media clip, of that line
    assert len(_media_calls(fake_miner)) == 1


def test_the_suites_fake_and_a_source_checkout_have_no_bundled_ffmpeg(tmp_path):
    assert clips._binaries(str(tmp_path / "fake_anki_miner.py")) is None
    exe = tmp_path / "AnkiMiner" / "AnkiMiner.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    assert clips._binaries(str(exe)) is None
    folder = exe.parent / "_internal" / "bin"
    folder.mkdir(parents=True)
    (folder / ("ffmpeg" + clips.BIN_EXT)).write_bytes(b"MZ")
    assert clips._binaries(str(exe)) is None                    # ffprobe too, or `media`
    (folder / ("ffprobe" + clips.BIN_EXT)).write_bytes(b"MZ")
    assert clips._binaries(str(exe)) == (str(folder / ("ffmpeg" + clips.BIN_EXT)),
                                         str(folder / ("ffprobe" + clips.BIN_EXT)))
    assert clips._binaries(None) is None


def test_an_anki_miner_too_old_for_media_still_plays_through_its_ffmpeg_and_says_update_only_when_neither_can(
        episode, fake_miner, monkeypatch):
    ep = episode("ja")
    monkeypatch.setattr(anki_miner, "can_now", lambda asks: False)      # 3.5: no `media`
    monkeypatch.setattr(anki_miner, "settings_export", lambda path, lang, out, profile=None, timeout=None: EXPORT_350)
    made = []
    _fake_direct(monkeypatch, made).append("ja")
    assert _cut(ep, ep["lines"][0]).endswith(".mp3")
    monkeypatch.setattr(clips, "_binaries", lambda miner: None)         # and one whose ffmpeg isn't where it was
    with pytest.raises(clips.Refused) as e:
        _cut(ep, ep["lines"][1])
    assert e.value.message == clips.OLD_MINER
    assert _media_calls(fake_miner) == []


def test_settings_are_never_asked_of_an_install_older_than_its_api(episode, monkeypatch):
    ep = episode("ja")
    monkeypatch.setattr(anki_miner, "too_old_install", lambda path: "3.4.0")
    assert clips._settings(ep["miner"], "ja") is None
    assert ep["exports"] == []                                  # (it would open its window)


# --------------------------------------------------------------------------- #
# The cut ahead: one line at a time, claimed
# --------------------------------------------------------------------------- #
def _ahead_done(timeout=20):
    import time
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        worker = clips._ahead["worker"]
        if worker is None or not worker.is_alive():
            return True
        time.sleep(0.02)
    return False


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_ahead_cuts_each_shown_line_directly_below_normal_and_a_press_then_plays_it(
        episode, fake_miner, monkeypatch, lang):
    ep = episode(lang)
    made = []
    _fake_direct(monkeypatch, made).append(lang)
    shown = ep["lines"][:3]
    assert clips.ahead(lang, [_id(c) for c in shown], settings=ep["settings"], steps=ep["steps"],
                       miner=ep["miner"]) == 3
    assert _ahead_done()
    cut = [m for m in made if m[0] == "cut"]
    assert len(cut) == 3 and all(below for _c, _cmd, below in cut)
    assert _media_calls(fake_miner) == []
    assert clips._cutting == {}                                 # every claim let go
    for cue in shown:
        _cut(ep, cue)
    assert len([m for m in made if m[0] == "cut"]) == 3         # the presses played what was kept


def test_a_press_on_a_line_the_ahead_cut_holds_waits_for_it_never_cuts_it_twice(episode, fake_miner, monkeypatch):
    ep = episode("ja")
    first, second = ep["lines"][0], ep["lines"][1]
    gate, inside, cuts = threading.Event(), threading.Event(), []

    def direct(language, video, cue, miner, out, below=False):
        cuts.append((cue.start, below))
        if below and cue.start == first.start:
            inside.set()
            gate.wait(10)                                       # the ahead cut, mid-cut of the first line
        path = f"{out}.mp3"
        with open(path, "w", encoding="utf-8") as f:
            f.write(cue.text)
        return path
    monkeypatch.setattr(clips, "_direct", direct)
    clips.ahead("ja", [_id(first), _id(second)], settings=ep["settings"], steps=ep["steps"], miner=ep["miner"])
    assert inside.wait(10)
    got = {}
    press = threading.Thread(target=lambda: got.update(path=_cut(ep, first)))
    press.start()
    clips.stop_ahead()                                          # (the door stops ahead at a press)
    gate.set()
    press.join(15)
    assert _ahead_done()
    assert got["path"] and open(got["path"], encoding="utf-8").read() == first.text
    assert cuts.count((first.start, True)) == 1 and (first.start, False) not in cuts     # cut once, by ahead
    assert (second.start, True) not in cuts                     # stopped between lines: the rest not cut
    assert _media_calls(fake_miner) == [] and clips._cutting == {}
    assert _cut(ep, second)                                     # a line let go is cut by its own press
    assert (second.start, False) in cuts


def test_a_press_waiting_on_a_line_the_ahead_cut_lets_go_cuts_it_itself(episode, fake_miner, monkeypatch):
    # the press came on the second line while the ahead cut was on the first: ahead stops between lines and lets the
    # second go uncut — the press waiting on it plays it, never "couldn't cut"
    ep = episode("ja")
    first, second = ep["lines"][0], ep["lines"][1]
    gate, inside, cuts = threading.Event(), threading.Event(), []

    def direct(language, video, cue, miner, out, below=False):
        cuts.append((cue.start, below))
        if below:
            inside.set()
            gate.wait(10)
        path = f"{out}.mp3"
        with open(path, "w", encoding="utf-8") as f:
            f.write(cue.text)
        return path
    monkeypatch.setattr(clips, "_direct", direct)
    clips.ahead("ja", [_id(first), _id(second)], settings=ep["settings"], steps=ep["steps"], miner=ep["miner"])
    assert inside.wait(10)
    got = {}
    press = threading.Thread(target=lambda: got.update(path=_cut(ep, second)))
    press.start()
    press.join(0.3)
    assert press.is_alive()                                     # waiting on ahead's claim of the second line
    clips.stop_ahead()
    gate.set()
    press.join(15)
    assert _ahead_done()
    assert open(got["path"], encoding="utf-8").read() == second.text
    assert cuts == [(first.start, True), (second.start, False)]


def test_the_cut_ahead_failing_before_its_first_cut_leaves_no_claim(episode, monkeypatch):
    # (the clips folder unreachable as the ahead cut starts: its lines must not wait 35 s on a claim nobody holds)
    ep = episode("ja")
    def unreachable():
        raise OSError("the data folder went away")
    monkeypatch.setattr(clips, "_kept", lambda key: None)              # (its own lookups of the folder aside)
    monkeypatch.setattr(clips, "root", unreachable)
    clips.ahead("ja", [_id(c) for c in ep["lines"][:2]], settings=ep["settings"], steps=ep["steps"], miner=ep["miner"])
    assert _ahead_done()
    assert clips._cutting == {}


def test_a_tool_that_fails_is_a_failure_whatever_it_wrote():
    import sys
    assert clips._run([sys.executable, "-c", "import sys; print('half'); sys.exit(3)"], stdout=True) is None
    assert clips._run([sys.executable, "-c", "print('streams')"], stdout=True).strip() == b"streams"
    assert clips._run([sys.executable, "-c", "pass"]) == b""


# --------------------------------------------------------------------------- #
# A real ffmpeg: the language's stream, the line's length
# --------------------------------------------------------------------------- #
def _two_track_mkv(path, lang, seconds=32):
    """An .mkv with two audio streams: an English one silent, the learner's language's a tone — so a clip's sound says
    which stream it was cut from."""
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=mono:d={seconds}",
                    "-f", "lavfi", "-i", f"sine=f=440:r=48000:d={seconds}", "-map", "0:a", "-map", "1:a",
                    "-c:a", "flac", "-metadata:s:a:0", "language=eng", "-metadata:s:a:1", f"language={TAG[lang]}",
                    str(path)], check=True, timeout=60)


def _loudest(clip):
    pcm = subprocess.run([FFMPEG, "-v", "error", "-i", clip, "-f", "s16le", "-ac", "1", "-"], capture_output=True,
                         check=True, timeout=60).stdout
    samples = memoryview(pcm).cast("h")
    return max((abs(s) for s in samples), default=0), len(samples)


def _probe_seconds(clip):
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", clip],
                         capture_output=True, text=True, check=True, timeout=60).stdout
    return float(out.strip())


@needs_ffmpeg
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_real_cut_plays_the_languages_stream_for_the_lines_length_and_padding(episode, monkeypatch, tmp_path, lang):
    ep = episode(lang)
    video = tmp_path / f"two-tracks-{lang}.mkv"
    _two_track_mkv(video, lang)
    ep["steps"] = Steps(SUBS[lang], str(video))
    monkeypatch.setattr(clips, "_binaries", lambda miner: (FFMPEG, FFPROBE))
    cue = ep["lines"][1]
    path = _cut(ep, cue)
    loudest, n = _loudest(path)
    assert loudest > 3000                                       # the tone: the language's stream, not the silent dub
    want = cues.seconds(cue.end) - cues.seconds(cue.start) + 0.6
    assert abs(_probe_seconds(path) - want) < 0.1               # the line, 0.3 s padding each side


# --------------------------------------------------------------------------- #
# The same bytes as Anki Miner's `media`, where one is named
# --------------------------------------------------------------------------- #
SAME = {k: os.environ.get(f"SURASURA_SAME_BYTES_{k.upper()}") for k in ("miner", "video", "subtitle", "home", "bin")}


@pytest.mark.skipif(not (SAME["miner"] and SAME["video"] and SAME["subtitle"]),
                    reason="no Anki Miner with media and real .mkv named here (SURASURA_SAME_BYTES_MINER / _VIDEO / "
                           "_SUBTITLE, optional _HOME for its ANKI_MINER_HOME and _BIN for a checkout's ffmpeg folder)")
def test_the_direct_cut_is_medias_clip_byte_for_byte(tmp_path, monkeypatch):
    if SAME["home"]:
        monkeypatch.setenv("ANKI_MINER_HOME", SAME["home"])
    miner = SAME["miner"]
    found = clips._binaries(miner)
    if found is None:                       # a source checkout: Anki Miner's resolver takes PATH's (or the one named)
        where = SAME["bin"]
        found = tuple(os.path.join(where, n + clips.BIN_EXT) if where else shutil.which(n)
                      for n in ("ffmpeg", "ffprobe"))
    monkeypatch.setattr(clips, "_binaries", lambda path: found)
    lines = list(cues.read(SAME["subtitle"], "ja"))
    for cue in (lines[0], lines[len(lines) // 2], lines[-1]):
        run_dir = tmp_path / f"media-{cue.start}"
        line = lineup.Cue(SAME["video"], SAME["subtitle"], cues.seconds(cue.start), cues.seconds(cue.end),
                          lineup.clean(cue.text))
        theirs = add_audio.cut(miner, "ja", None, {0: line}, str(run_dir))[0]
        ours = clips._direct("ja", SAME["video"], cue, miner, str(tmp_path / f"direct-{cue.start}"))
        assert ours, "the direct cut didn't run"
        with open(theirs, "rb") as a, open(ours, "rb") as b:
            assert a.read() == b.read(), f"the line at {cue.start} ms: the direct cut isn't media's clip"
