# SPDX-License-Identifier: GPL-3.0-or-later
"""bilibili.tv links in the transcript downloader and Preview — no account needed.

Why bilibili.tv and not bilibili.com (measured 2026-09-18): bilibili.com gives subtitles only to
signed-in users (0 of 20 popular videos without a login), and signing up there is hard for learners
outside China. bilibili.tv serves its subtitle tracks, Chinese included, with no account, wherever a
show is licensed for the viewer's region.

What is pinned, all hermetic (yt-dlp is faked at `_run_ytdlp`, as in test_extract_integration.py):
- which links count as bilibili.tv, and that bilibili.com links are turned away BEFORE any fetch;
- bilibili.tv captions are asked for as SRT, never converted to VTT (that needs ffmpeg, which users
  don't have), and their comma timestamps still yield cue times;
- each cue is closed as a sentence. Chinese subtitles carry no end punctuation, and joined with
  spaces they became one endless "sentence";
- files are named "[bilibili-<id>]": a bare bracketed number is too common to trust;
- no "Unknown -" channel prefix or folder (bilibili.tv names no uploader), and a season is a folder;
- a region-locked or members-only episode is explained in plain words instead of vanishing;
- Preview recognises the links, guards against duplicates and links its badge to the episode page.

The subtitle text mirrors yt-dlp's json2srt output for bilibili.tv (BiliIntlBaseIE.json2srt).
"""
import json
import os
import tempfile
import types
import unittest
from unittest.mock import patch

import pytest

from modules.youtube_downloader import downloader as core
from modules.youtube_downloader import preview as pv

EP_URL = "https://www.bilibili.tv/en/play/2410703/30646923"
SEASON_URL = "https://www.bilibili.tv/en/play/2410703"
YT_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

SRT_ZH = ("1\n00:00:01,000 --> 00:00:03,500\n欢迎光临时光照相馆\n\n"
          "2\n00:00:03,600 --> 00:00:06,000\n我们今天要接一个新的委托\n\n"
          "3\n00:01:06,100 --> 00:01:08,400\n你确定要进入这张照片吗？\n\n"
          "4\n00:01:08,500 --> 00:01:10,900\n放心吧 我会小心的")

VTT_EN = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nwelcome back\n"

# Subtitle languages the bilibili.tv API listed for this episode (live, 2026-09-18).
BILI_SUBS = {code: [{"ext": "srt"}] for code in ("en", "th", "id", "zh-Hans", "zh-Hant")}

# yt-dlp's own output for a refused episode, captured live from yt-dlp 2026.07.04 (the region lock is
# exactly what this episode returns outside its licensed countries). Note there is NO episode id in
# it: an earlier version of this code assumed "ERROR: [BiliIntl] <id>: ..." and missed every one.
GEO_ERROR = ("ERROR: [BiliIntl] This video is not available from your location due to geo "
             "restriction\nYou might want to use a VPN or a proxy server (with --proxy) to workaround.")
# yt-dlp's raise_login_required default text, raised for bilibili.tv's members-only codes.
MEMBERS_ERROR = ("ERROR: [BiliIntl] This video is only available for registered users. Use "
                 "--username and --password, --netrc-cmd, --netrc (biliintl) or "
                 "--cookies-from-browser or --cookies for the authentication.")


def _bili_info(vid="30646923", title="E7", url=EP_URL):
    # What BiliIntl yields: no channel / uploader / series at all.
    return {"id": vid, "title": title, "webpage_url": url, "duration": 1440,
            "subtitles": BILI_SUBS, "automatic_captions": {}}


def _yt_info():
    return {"id": "dQw4w9WgXcQ", "title": "First Talk", "channel": "NHK", "webpage_url": YT_URL,
            "upload_date": "20260101", "duration": 60,
            "subtitles": {"en": [{"ext": "vtt"}]}, "automatic_captions": {}}


class FakeYtdlp:
    """Stands in for `_run_ytdlp`: records every call, and for a download call drops the info.json
    plus the caption file each site really produces (bilibili.tv: SRT; YouTube: WebVTT)."""

    def __init__(self, infos, stderr=""):
        self.infos = infos           # url -> info dict
        self.stderr = stderr
        self.calls = []

    def __call__(self, args, timeout=None, **_kw):
        self.calls.append(list(args))
        res = types.SimpleNamespace(returncode=0, stdout="", stderr="")
        if '-J' in args:
            res.stdout = json.dumps(self.infos.get(args[-1], {}))
            return res
        tmpdir = os.path.dirname(args[args.index('-o') + 1])
        for url in [a for a in args if a.startswith('http')]:
            info = self.infos.get(url)
            if info is None:
                continue
            with open(os.path.join(tmpdir, f"{info['id']}.info.json"), "w", encoding="utf-8") as f:
                json.dump(info, f, ensure_ascii=False)
            if core.site_of(url) == 'bilibili':
                sub, ext = SRT_ZH, "zh-Hans.srt"
            else:
                sub, ext = VTT_EN, "en.vtt"
            with open(os.path.join(tmpdir, f"{info['id']}.{ext}"), "w", encoding="utf-8") as f:
                f.write(sub)
        if any(core.site_of(a) == 'bilibili' for a in args if a.startswith('http')):
            res.stderr = self.stderr
        return res


def _summary():
    return {"written": 0, "no_transcript": 0, "errors": 0}


# ---- links ------------------------------------------------------------------------------------ #

@pytest.mark.parametrize("url, site", [
    (EP_URL, "bilibili"),
    (SEASON_URL, "bilibili"),
    ("https://www.bilibili.tv/en/video/2044137234", "bilibili"),
    ("https://bilibili.tv/th/play/1006275/11170995", "bilibili"),
    ("https://www.biliintl.com/en/play/34613/341736", "bilibili"),
    ("https://www.bilibili.com/bangumi/play/ep5137677", "bilibili.com"),
    ("https://www.bilibili.com/video/BV1wue26pE7Y", "bilibili.com"),
    ("https://b23.tv/abc123", "bilibili.com"),
    (YT_URL, "youtube"),
    ("https://youtu.be/dQw4w9WgXcQ", "youtube"),
    ("http://A", "youtube"),                      # anything unknown keeps the old behaviour
])
def test_site_of(url, site):
    assert core.site_of(url) == site


# ---- captions --------------------------------------------------------------------------------- #

def test_srt_cues_keep_their_times():
    """SRT writes '00:01:06,100'. Read as WebVTT, the comma used to leave every time unknown, and a
    cue without a time can't be linked to its moment."""
    assert core.clean_vtt_cues(SRT_ZH) == [
        ("欢迎光临时光照相馆", 1), ("我们今天要接一个新的委托", 3),
        ("你确定要进入这张照片吗？", 66), ("放心吧 我会小心的", 68)]


def test_bilibili_tv_tracks_resolve_like_manual_captions():
    info = _bili_info()
    assert core.resolve_caption(info, core.LANGS["Chinese"]) == ("zh-Hans", "manual")
    assert core.resolve_caption(info, core.LANGS["English"]) == ("en", "manual")
    assert core.resolve_caption(info, core.LANGS["Japanese"]) == (None, None)


def test_bilibili_tv_asks_for_srt_and_never_converts():
    bili = core._subtitle_args("bilibili", core.LANGS["Chinese"])
    assert "--convert-subs" not in bili, "converting needs ffmpeg, which users don't have"
    assert bili[bili.index("--sub-format") + 1] == "srt/best"
    youtube = core._subtitle_args("youtube", core.LANGS["Chinese"])
    assert youtube[youtube.index("--convert-subs") + 1] == "vtt"     # YouTube unchanged


# ---- a full bucket ---------------------------------------------------------------------------- #

class TestBilibiliBucket(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="bili_")

    def _run(self, urls, infos, stderr="", keep_ts=False):
        fake, summary, log = FakeYtdlp(infos, stderr), _summary(), []
        with patch.object(core, "_run_ytdlp", fake):
            core._download_bucket(urls, self.out, core.LANGS["Chinese"], "Chinese",
                                  keep_ts=keep_ts, channel_first=True, log=log.append,
                                  summary=summary)
        return fake, summary, log

    def test_a_mixed_bucket_runs_each_site_with_its_own_flags(self):
        yt = dict(_yt_info(), subtitles={"zh-Hans": [{"ext": "vtt"}]})
        fake, summary, _log = self._run([YT_URL, EP_URL], {YT_URL: yt, EP_URL: _bili_info()})
        downloads = [c for c in fake.calls if "--write-subs" in c]
        self.assertEqual(len(downloads), 2, "one yt-dlp call per site")
        for call in downloads:
            urls = [a for a in call if a.startswith("http")]
            self.assertEqual(len(urls), 1)
            if core.site_of(urls[0]) == "bilibili":
                self.assertNotIn("--convert-subs", call)
            else:
                self.assertIn("--convert-subs", call)
        self.assertEqual(summary["written"], 2)

    def test_episode_transcript_is_named_closed_and_linked(self):
        # yt-dlp tags an episode reached through a season with a smuggle fragment.
        info = _bili_info(url=EP_URL + "#__youtubedl_smuggle=%7B%22title%22%3A+%22E7%22%7D")
        _fake, summary, _log = self._run([EP_URL], {EP_URL: info})
        self.assertEqual(summary, {"written": 1, "no_transcript": 0, "errors": 0})

        path = os.path.join(self.out, "E7 [bilibili-30646923].txt")
        self.assertTrue(os.path.isfile(path), os.listdir(self.out))   # no "Unknown - " prefix
        text = open(path, encoding="utf-8").read()
        self.assertIn("Captions: Chinese (manual)", text)
        # One sentence per cue: closed with 。 unless it already ends in punctuation, no spaces
        # glued between them.
        self.assertIn("欢迎光临时光照相馆。我们今天要接一个新的委托。你确定要进入这张照片吗？放心吧 我会小心的。",
                      text)

        with open(core.sidecar_path(path), encoding="utf-8") as f:
            side = json.load(f)
        self.assertEqual(side["url"], EP_URL, "the smuggle fragment is plumbing, not the address")
        self.assertEqual(side["video_id"], "30646923")
        self.assertEqual([c[1] for c in side["cues"]], [1, 3, 66, 68])

    def test_keep_timestamps_puts_one_cue_per_line(self):
        _fake, _summary_, _log = self._run([EP_URL], {EP_URL: _bili_info()}, keep_ts=True)
        text = open(os.path.join(self.out, "E7 [bilibili-30646923].txt"), encoding="utf-8").read()
        self.assertIn("[00:01:06] 你确定要进入这张照片吗？\n[00:01:08] 放心吧 我会小心的", text)

    def test_refused_episodes_are_explained_not_dropped(self):
        """A season where two episodes are region-locked, one is members-only and one failed for
        some other reason: yt-dlp writes nothing for any of them, only these lines."""
        stderr = "\n".join([GEO_ERROR, GEO_ERROR, MEMBERS_ERROR,
                            "ERROR: [BiliIntl] 30646925: Unable to download JSON metadata: HTTP Error 404"])
        _fake, summary, log = self._run([SEASON_URL], {}, stderr=stderr)
        self.assertIn("  – 2 episodes: not available in your region "
                      "(bilibili.tv licenses each show per country)", log)
        self.assertIn("  – 1 episode: for bilibili.tv members only", log)
        self.assertIn("  ! episode 30646925: Unable to download JSON metadata: HTTP Error 404", log)
        self.assertNotIn("VPN", "\n".join(log), "never steer the learner around a region lock")
        self.assertEqual(summary, {"written": 0, "no_transcript": 3, "errors": 1})


def test_an_upload_bilibili_tv_will_not_play_is_named_not_a_python_error():
    """bilibili.tv's playback API refused these uploads (code 10004002) and yt-dlp crashed with this
    exact line, no extractor tag, on both 2026.07.04 and 2026.08.19. The learner should read a
    sentence, not a Python error."""
    def fake(args, timeout=None, **_kw):
        return types.SimpleNamespace(returncode=1, stdout="null\n",
                                     stderr="ERROR: 'NoneType' object is not subscriptable")

    log = []
    with patch.object(core, "_run_ytdlp", fake):
        core._probe("https://www.bilibili.tv/en/video/2009506988", log.append)
    assert log == ["  – could not read https://www.bilibili.tv/en/video/2009506988: "
                   "bilibili.tv didn't return this video"]


def _bucket_into(target, urls, infos, stderr=""):
    with patch.object(core, "_run_ytdlp", FakeYtdlp(infos, stderr)):
        core._download_bucket(urls, target, core.LANGS["Chinese"], "Chinese", keep_ts=False,
                              channel_first=True, log=lambda *_: None, summary=_summary())


def test_a_season_that_yields_nothing_leaves_no_empty_folder(tmp_path):
    """Seen live: a region-locked season left an empty "LINK CLICK 3 (playlist)" in Processed, which
    the window then reported as new and copied into the library as an empty group."""
    target = tmp_path / "LINK CLICK 3 (playlist)"
    _bucket_into(str(target), [SEASON_URL], {}, stderr=GEO_ERROR)
    assert not target.exists()


def test_a_folder_that_already_existed_is_never_removed(tmp_path):
    target = tmp_path / "LINK CLICK 3 (playlist)"
    target.mkdir()
    _bucket_into(str(target), [SEASON_URL], {}, stderr=GEO_ERROR)
    assert target.is_dir()


def test_a_season_with_transcripts_keeps_its_folder(tmp_path):
    target = tmp_path / "LINK CLICK 3 (playlist)"
    _bucket_into(str(target), [EP_URL], {EP_URL: _bili_info()})
    assert (target / "E7 [bilibili-30646923].txt").is_file()


def test_a_link_that_cannot_be_read_says_why():
    """The lookup step: for a region-locked episode yt-dlp prints 'null' and the error. That used to
    return nothing silently, and the run ended with just "No videos found"."""
    def fake(args, timeout=None, **_kw):
        return types.SimpleNamespace(returncode=1, stdout="null\n", stderr=GEO_ERROR)

    log = []
    with patch.object(core, "_run_ytdlp", fake):
        assert core._probe(EP_URL, log.append) is None
    assert log == [f"  – could not read {EP_URL}: not available in your region "
                   "(bilibili.tv licenses each show per country)"]


def test_bilibili_com_links_are_turned_away_before_anything_is_fetched(tmp_path):
    def must_not_run(*_a, **_k):
        raise AssertionError("yt-dlp must not be called for a bilibili.com link")

    log = []
    with patch.object(core, "_run_ytdlp", must_not_run):
        summary = core.extract(["https://www.bilibili.com/bangumi/play/ep5137677"], str(tmp_path),
                               lang="Chinese", log=log.append)
    assert summary["errors"] == 1 and summary["written"] == 0
    assert any("bilibili.tv" in line and "signed-in" in line for line in log)


def test_a_season_gets_its_own_folder_and_loose_episodes_no_unknown_folder(tmp_path):
    season = {"_type": "playlist", "id": "2410703", "title": "LINK CLICK 3", "entries": [{}]}
    buckets = core.plan_buckets([
        (SEASON_URL, season),
        (EP_URL, _bili_info()),
        ("https://www.bilibili.tv/en/play/2410703/30646924", _bili_info("30646924", "E8")),
    ], str(tmp_path))
    targets = {os.path.basename(target) if target != str(tmp_path) else "<Processed>": urls
               for urls, target in buckets}
    assert targets["LINK CLICK 3 (playlist)"] == [SEASON_URL]
    assert sorted(targets["<Processed>"]) == sorted([EP_URL, "https://www.bilibili.tv/en/play/2410703/30646924"])
    assert "Unknown" not in targets


# ---- Preview ---------------------------------------------------------------------------------- #

@pytest.mark.parametrize("url, vid", [
    (EP_URL, "bilibili-30646923"),
    ("https://www.bilibili.tv/en/video/2044137234?bstar_from=bstar-web", "bilibili-2044137234"),
    (SEASON_URL, None),                         # a season is a playlist, not one video
    (YT_URL, "dQw4w9WgXcQ"),
])
def test_preview_recognises_the_link(url, vid):
    assert pv.extract_video_id(url) == vid


def test_preview_refuses_an_episode_already_in_the_library(tmp_path):
    folder = tmp_path / "zh" / "Processed" / "LINK CLICK 3 (playlist)"
    folder.mkdir(parents=True)
    (folder / "E7 [bilibili-30646923].txt").write_text("欢迎光临时光照相馆。", encoding="utf-8")
    with patch.object(pv, "get_data_path", lambda language: str(tmp_path / language)):
        assert pv.video_in_library(pv.extract_video_id(EP_URL), "zh")
        assert not pv.video_in_library(pv.extract_video_id(EP_URL.replace("923", "924")), "zh")


def test_preview_badge_opens_the_episode_page(tmp_path, monkeypatch):
    transcript = tmp_path / "E7 [bilibili-30646923].txt"
    transcript.write_text("欢迎光临时光照相馆。", encoding="utf-8")
    with open(core.sidecar_path(str(transcript)), "w", encoding="utf-8") as f:
        json.dump({"video_id": "30646923", "url": EP_URL, "cues": [["欢迎光临时光照相馆", 1]]}, f)
    monkeypatch.setattr("app.static_html_generator._load_source_map", lambda: {})
    words = [{"Word": "照相馆", "Context 1": "欢迎光临时光照相馆。", "Src 1": pv.VIDEO_SOURCE}]

    table = pv._resolve_preview_sources([(transcript.name, words, str(transcript))],
                                        {"target_language": "zh", "source_display": "icon"})
    assert table[words[0]["Src 1"]][1] == "bilibili"
    assert table[words[0]["Src 1"]][4] == EP_URL
