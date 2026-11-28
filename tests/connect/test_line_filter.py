"""A picked word sent as Anki Miner finds it once its profile's subtitle filter has cleaned the line
(`runfile.line_filter`, `through_filter`; a tester's swap of ぐぐっと, Overlord III 11, 2026-11-28).

The profile's *Remove speaker names, sound effects and music notes* takes ～ out of every line before Anki Miner looks
for a word, so ぐぐ～っと上昇 reads ぐぐっと上昇. Sent as the line wrote it (front ぐぐーっと, surface ぐぐ～っと), the word was
`not_found` and no card was made; Anki Miner 3.13.0's `render` of the same run file with ぐぐっと made it from its line.
"""
import json
import os

import pytest

from app.connect import anki_miner, fields, runfile
from tests.connect.fake_anki_miner import FEATURES_37, LAPIS_EXPORT

# the tester's profile's pattern, as its settings export holds it
PROFILE_PATTERN = (r"\([^)]*\)|（[^）]*）|\[[^\]]*\]|［[^］]*］|[♪♬♫#]+|(?<!\d)[～〜]+|[～〜]+(?!\d)|"
                   r"^[^「『:：]+[:：](?!\d)\s*|(?:^|(?<=[.!?…]\s))[-–—]\s+")
LINE = "私の中のお気に入りランクが ぐぐ～っと上昇っすよ"


def _export(on=True, pattern=PROFILE_PATTERN, replacement=""):
    return {"settings": {"use_subtitle_regex_filter": on, "subtitle_regex_filter": pattern,
                         "subtitle_regex_replacement": replacement}}


def _guguu(**more):
    return dict({"word": "ぐぐ", "reading": "ググ", "orth": "ぐぐっと", "surface": "ぐぐ～っと", "sent": ["ぐぐーっと"],
                 "front_reading": "ぐぐーっと", "predicted_class": "IS-P5", "line_start": 1283.95,
                 "line_end": 1287.16, "line_text": LINE, "line_expansion": [0, 0]}, **more)


def test_a_wave_dash_the_profile_takes_out_leaves_the_word_its_line_now_says():
    [word] = runfile.through_filter([_guguu()], runfile.line_filter(_export()))
    assert (word["surface"], word["sent"], word["front_reading"]) == ("ぐぐっと", ["ぐぐっと"], "ぐぐっと")
    assert (word["word"], word["reading"]) == ("ぐぐ", "ググ")         # Surasura's own word is never changed


def test_the_run_file_names_the_cleaned_word_alone():
    [word] = runfile.through_filter([_guguu()], runfile.line_filter(_export()))
    [entry] = runfile.word_requests([word], FEATURES_37 + ["word-from-line"])
    assert entry["word"] == "ぐぐっと" and "surface" not in entry and entry["reading"] == "ぐぐっと"


@pytest.mark.parametrize("export", [
    _export(on=False),                          # the filter off: the line keeps its ～
    _export(pattern=""),                        # no pattern
    _export(pattern="(["),                      # one that doesn't compile
    _export(replacement="〜"),                   # a filter that rewrites: no cut to read off
    {},                                         # no export
])
def test_with_no_filter_to_follow_the_word_goes_as_it_was(export):
    assert runfile.through_filter([_guguu()], runfile.line_filter(export)) == [_guguu()]


def test_a_wave_dash_between_numbers_is_kept_as_the_filter_keeps_it():
    word = _guguu(surface="1～2話", sent=["1～2話"], front_reading=None, line_text="今日は 1～2話 だけ")
    assert runfile.through_filter([word], runfile.line_filter(_export())) == [word]


def test_a_front_that_does_not_line_up_with_the_spelling_goes_as_it_was():
    # a dictionary-form front (another length than the spelling) is not cut: only the spelling is
    word = _guguu(surface="食べ～", sent=["食べる"], front_reading="たべる", line_text="もう食べ～ないよ")
    [out] = runfile.through_filter([word], runfile.line_filter(_export()))
    assert (out["surface"], out["sent"], out["front_reading"]) == ("食べ", ["食べる"], "たべる")


def test_a_word_the_filter_takes_out_whole_goes_as_it_was():
    word = _guguu(surface="♪", sent=["♪"], front_reading=None, line_text="♪ ラララ")
    assert runfile.through_filter([word], runfile.line_filter(_export())) == [word]


def test_the_mine_step_sends_the_cleaned_word_and_reads_its_outcome(tmp_path, fake_miner):
    fake_miner.plan(app="3.13.0", features=FEATURES_37 + ["word-from-line"])
    run_dir = tmp_path / "runs" / "job-1"
    run_dir.mkdir(parents=True)
    (run_dir / runfile.EXPORT).write_text(json.dumps(_export(), ensure_ascii=False), encoding="utf-8")
    video = tmp_path / "episode.mkv"
    video.write_bytes(b"\x1aE\xdf\xa3")
    subtitle = tmp_path / "episode.ja.srt"
    subtitle.write_text("1\n00:21:23,950 --> 00:21:27,160\n" + LINE + "\n", encoding="utf-8")
    done = anki_miner.mine_batch(fake_miner.path, "ja", "job-1", str(video), str(subtitle), [_guguu()],
                                 fields.from_export(LAPIS_EXPORT), "Surasura", str(run_dir), "http://127.0.0.1:9")
    [entry] = fake_miner.run_files()[-1]["episodes"][0]["words"]
    assert entry["word"] == "ぐぐっと"
    [outcome] = done["outcomes"]
    assert (outcome["word"], outcome["outcome"]) == ("ぐぐ", "made")    # the row is read as the entry it stands for
