"""A line shown again inside a card's clip reads once in its sentence (Anki Miner 3.13's `line_skip`, Z-26; Sonic's yes
to Michi-AM13's F2).

Streaming subtitles show a line again straight after itself (the same text, touching times; another speaker's line
may sit at either copy's time). Connect runs a card's clip to the copy's end so the audio isn't cut mid-speech
(`pick.window`); Anki Miner then wrote the line's text twice in the Sentence. From 3.13.0 the run file names those
copies (`line_skip`: offsets from the word's line) — their time stays in the clip, their text leaves the sentence.
An older Anki Miner refuses the key (`BAD_RUN_FILE`), and 3.13 names no feature for it: it goes only to an Anki Miner
whose `version` says 3.13.0 or newer.

The subtitles are written for these tests (`Test Resources/ja|zh/repeated_lines.*.srt`, natural lines, no show's).
"""
import json
import os

import pytest

from app import analyzer, cues
from app.connect import anki_miner, fields, pick, runfile
from tests.connect.fake_anki_miner import LAPIS_EXPORT

RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Test Resources")
JA = os.path.join(RESOURCES, "ja", "repeated_lines.ja.srt")
ZH = os.path.join(RESOURCES, "zh", "repeated_lines.zh.srt")


@pytest.fixture(autouse=True)
def _a_japanese_run():
    analyzer.SANITIZE_JA = True             # as analyzer.main sets it (conftest restores the global)


def _read(path, language):
    read = cues.read(path, language)
    return read, cues.tokens(read, language)


def _line(read, text, nth=0):
    return [i for i, cue in enumerate(read) if cue.text == text][nth]


def _skip(path, language, text, nth=0):
    read, tokens = _read(path, language)
    return pick.line_skip(read, _line(read, text, nth), pick.Lines(read, tokens, language))


def _picked(path, language, word):
    read, tokens = _read(path, language)
    chosen = pick.pick(read, tokens, language, lambda key: key[0] != word, mode="unknown")
    return next(w for w in chosen["words"] if w["word"] == word)


# --------------------------------------------------------------------------- #
# Which lines of a card are copies
# --------------------------------------------------------------------------- #
def test_a_japanese_line_shown_again_straight_after_itself_is_skipped_once():
    # 図書館の鍵を忘れちゃった, then its copy 0.25 s on screen: the card holds both, the sentence the line once
    assert _skip(JA, "ja", "図書館の鍵を忘れちゃった") == [1]


def test_a_copy_through_another_speakers_line_is_skipped_and_the_other_line_kept():
    # Netflix's way (batch 2's Z-26 example): the line beside another speaker's, then shown again — the copy goes,
    # the other speaker's line stays: 早く窓口に返却しないと でも まだ半分しか読んでない
    assert _skip(JA, "ja", "早く窓口に返却しないと") == [2]


def test_the_card_cut_from_the_copy_keeps_its_own_line_and_skips_the_first_showing():
    # Offset 0 (the word's own line) is never skipped (Anki Miner refuses it): the first showing goes instead
    assert _skip(JA, "ja", "早く窓口に返却しないと", nth=1) == [-2]


def test_a_chinese_line_run_on_into_its_copy_is_skipped_too():
    # Chinese keeps the punctuation rule: a line with no 。 runs on into the next — here its own copy, then the reply
    assert _skip(ZH, "zh", "我们明天去夜市吃牛肉面吧") == [1]
    assert _skip(ZH, "zh", "那家臭豆腐的摊位还在吗") == [1]


def test_a_reply_pulled_back_over_a_repeated_line_keeps_its_first_showing():
    # 好啊，几点见？'s card takes the two lines before it (the line and its copy): the copy goes, the first showing stays
    read, tokens = _read(ZH, "zh")
    assert pick.line_expansion(read, _line(read, "好啊，几点见？"), pick.Lines(read, tokens, "zh")) == [2, 0]
    assert _skip(ZH, "zh", "好啊，几点见？") == [-1]


def test_a_card_with_no_copy_skips_nothing():
    assert _skip(JA, "ja", "今日は閲覧室がすごく静かだね") == []
    assert _skip(ZH, "zh", "我想顺便买一杯珍珠奶茶。") == []
    # a Chinese line with no 。 runs on into the next, a different one: two lines, nothing skipped
    read, tokens = _read(ZH, "zh")
    at = _line(read, "晚上七点在捷运站门口")
    assert pick.line_expansion(read, at, pick.Lines(read, tokens, "zh")) == [0, 1]
    assert _skip(ZH, "zh", "晚上七点在捷运站门口") == []


def test_the_pick_carries_the_copies_of_the_words_line():
    assert _picked(JA, "ja", "鍵")["line_skip"] == [1]
    assert _picked(JA, "ja", "鍵")["line_expansion"] == [0, 1]       # the clip still runs to the copy's end
    assert _picked(ZH, "zh", "牛肉面")["line_skip"] == [1]
    assert _picked(JA, "ja", "閲覧室")["line_skip"] == []


# --------------------------------------------------------------------------- #
# Sent only to an Anki Miner that takes it
# --------------------------------------------------------------------------- #
WORD = {"word": "鍵", "reading": "カギ", "sent": ["鍵"], "line_start": 1.0, "line_expansion": [0, 1], "line_skip": [1]}


@pytest.mark.parametrize("app, sent", [("3.13.0", [1]), ("3.13", [1]), ("3.14.2", [1]), ("4.0.0", [1]),
                                       ("3.12.0", None), ("3.9.0", None), (None, None), ("unknown", None)])
def test_line_skip_goes_only_to_anki_miner_3_13_or_newer(app, sent):
    entry = runfile.word_requests([WORD], app=app)[0]
    assert entry.get("line_skip") == sent
    assert entry["line_expansion"] == [0, 1], "the clip is the same either way"


def test_no_copy_means_no_key_and_a_book_line_never_carries_one():
    assert "line_skip" not in runfile.word_requests([dict(WORD, line_skip=[])], app="3.13.0")[0]
    book = dict(WORD, line_text="図書館の鍵を忘れちゃった")
    assert "line_skip" not in runfile.word_requests([book], app="3.13.0", book=True)[0]


# --------------------------------------------------------------------------- #
# Through the caller, against the fake Anki Miner (which, like 3.12, refuses the key below 3.13)
# --------------------------------------------------------------------------- #
@pytest.fixture
def mine(tmp_path, fake_miner):
    words = [_picked(JA, "ja", "鍵")]
    video = tmp_path / "episode.mkv"
    video.write_bytes(b"\x1aE\xdf\xa3")

    def run(app):
        fake_miner.plan(app=app, features=["word-from-line"])
        done = anki_miner.mine_batch(fake_miner.path, "ja", "job-1", str(video), JA, words,
                                     fields.from_export(LAPIS_EXPORT), "Surasura", str(tmp_path / "runs" / app),
                                     "http://127.0.0.1:9")
        sent = [w for f in fake_miner.run_files() for e in f["episodes"] for w in e["words"]]
        return done, sent
    return run


@pytest.mark.parametrize("app, skip", [("3.13.0", [1]), ("3.12.0", None)])
def test_the_run_file_names_the_copy_only_for_3_13_and_both_are_mined(mine, app, skip):
    done, sent = mine(app)
    assert [o["outcome"] for o in done["outcomes"]] == ["made"]
    assert sent and [w.get("line_skip") for w in sent] == [skip] * len(sent)


@pytest.mark.parametrize("app, skip", [("3.13.0", [1]), ("3.12.0", None)])
def test_the_pick_verbs_run_file_names_the_copy_only_for_3_13(tmp_path, monkeypatch, app, skip):
    # surasura-cli's own `pick` writes a run file too (app/cli/verbs.py): the same gate, from its version answer
    from types import SimpleNamespace
    from app.cli import verbs
    video = tmp_path / "episode.mkv"
    video.write_bytes(b"\x1aE\xdf\xa3")
    monkeypatch.setattr(verbs, "settings", lambda: {"target_language": "ja"})
    monkeypatch.setattr(verbs, "require_set_up", lambda lang: None)
    monkeypatch.setattr(verbs, "_known_test", lambda *a: (lambda key: key[0] != "鍵"))
    monkeypatch.setattr(pick, "carded", lambda *a, **k: (set(), "anki"))
    setup = ({"app": app, "features": ["word-from-line"]}, "Surasura", fields.from_export(LAPIS_EXPORT))
    monkeypatch.setattr(verbs, "_anki_miner_setup", lambda *a, **k: setup)
    out = verbs.pick(SimpleNamespace(lang="ja", file=JA, video=str(video), words="unknown", job="ls", wait=0.0,
                                     made=set(), listed={}, reading=None))
    with open(out["run_file"], encoding="utf-8") as f:
        sent = [w for e in json.load(f)["episodes"] for w in e["words"]]
    assert sent and [w.get("line_skip") for w in sent] == [skip] * len(sent)


def test_a_book_word_lined_up_with_its_audiobook_carries_no_skip(monkeypatch):
    # its sentence is cut at its own cue (`lineup.split`: line_expansion [0, 0]): a skip would name no merged line
    from app.connect import lineup
    cue = SimpleCue(start=3.0, end=5.0, audio="a.m4b", subtitle="a.srt")
    monkeypatch.setattr(lineup, "usable", lambda state: True)
    monkeypatch.setattr(lineup, "cues", lambda state: [cue])
    monkeypatch.setattr(lineup, "place", lambda *a: cue)
    groups, rest = lineup.split([dict(WORD, line_text="図書館の鍵を忘れちゃった")], {})
    (word,) = groups[("a.m4b", "a.srt")]
    assert (word["line_expansion"], word["line_skip"], rest) == ([0, 0], [], [])
    assert "line_skip" not in runfile.word_requests([word], app="3.13.0")[0]


class SimpleCue:
    def __init__(self, **kw):
        self.__dict__.update(kw)
