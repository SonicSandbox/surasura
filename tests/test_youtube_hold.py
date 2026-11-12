"""Yt-B (Sonic 2026-11-12: "will this hit from my own network and then will I have issues in the future with too many
requests?"): YouTube's bot check, met once, holds every YouTube call for a day, and YouTube is asked one call at a time,
a little apart (`app/youtube_hold.py`).

What a wrong answer costs: a learner's own address asked again and again after YouTube turned it away (the block lasts
longer), a hold that never ends (a broken record, a clock moved), an age-restricted video taken for the bot check, or
two programs asking YouTube at once. yt-dlp's own words, as it prints them; never the network.
"""
import json
import os
import threading
import time

import pytest

from app import locks, youtube_hold

BOT = ("ERROR: [youtube] dQw4w9WgXcQ: Sign in to confirm you’re not a bot. Use --cookies-from-browser or "
       "--cookies for the authentication.")
TOO_MANY = "ERROR: [youtube] dQw4w9WgXcQ: Unable to download webpage: HTTP Error 429: Too Many Requests"
AGE = ("ERROR: [youtube] dQw4w9WgXcQ: Sign in to confirm your age. This video may be inappropriate for some users. "
       "Use --cookies-from-browser or --cookies for the authentication.")
PRIVATE = "ERROR: [youtube] a429bcdefgh: Private video. Sign in if you've been granted access to this video"


@pytest.fixture(autouse=True)
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("SURASURA_TEST_ROOT", str(tmp_path))
    return tmp_path


def _record(root):
    with open(os.path.join(root, "persistent_root", youtube_hold.NAME), encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("text, refused", [
    (BOT, True), (BOT.replace("’", "'"), True), (TOO_MANY, True),
    (AGE, False), (PRIVATE, False), ("", False), (None, False),
], ids=["bot-curly", "bot-straight", "429", "age-check", "id-with-429", "empty", "none"])
def test_only_youtube_turning_the_computer_away_is_a_refusal(text, refused):
    # why: an age-restricted video is the video's own; holding every download for it would stop a day for nothing
    assert youtube_hold.refused(text) is refused


def test_the_first_refusal_holds_a_day_and_a_later_one_never_lengthens_it(root):
    now = 1_800_000_000.0
    assert youtube_hold.held(now) is None
    until = youtube_hold.hold(now)
    assert until == now + youtube_hold.HOLD_S
    assert youtube_hold.hold(now + 3600) == until, "a refusal met during the hold keeps its end"
    assert youtube_hold.held(now + 3600) == until
    assert youtube_hold.held(until) is None, "it ends at its end"
    assert youtube_hold.hold(until + 1) == until + 1 + youtube_hold.HOLD_S, "after it, a new refusal holds again"
    assert _record(root)["since"] == until + 1


@pytest.mark.parametrize("content", ["not json{", "[1, 2]", '{"until": "tomorrow"}', '{"until": true}'],
                         ids=["broken", "a-list", "a-string", "a-bool"])
def test_a_broken_record_is_no_hold(root, content):
    # why: a broken file must never stop YouTube for good
    folder = root / "persistent_root"
    folder.mkdir(exist_ok=True)
    (folder / youtube_hold.NAME).write_text(content, encoding="utf-8")
    assert youtube_hold.held() is None


def test_an_end_further_than_a_day_away_is_no_hold_but_a_clock_set_back_a_little_still_holds(root):
    # why: the clock moved back far (or a record from a copied profile) would otherwise hold for weeks; a small
    # correction (review 3: a time sync stepping back a second) must not lift a hold just begun
    now = time.time()
    until = youtube_hold.hold(now)
    assert youtube_hold.held(now - 5) == until
    assert youtube_hold.held(now - youtube_hold.SLACK_S - 5) is None
    os.remove(os.path.join(root, "persistent_root", youtube_hold.NAME))
    youtube_hold.hold(now + 10 * youtube_hold.HOLD_S)
    assert youtube_hold.held(now) is None


def test_the_words_say_when_it_tries_again_the_same_all_through_the_hold():
    # why (review 8): "tomorrow" turning "today" at midnight would make Connect's Needs you count it again
    now = time.mktime((2026, 11, 12, 21, 42, 0, 0, 0, -1))           # a Thursday
    said = youtube_hold.words(now + youtube_hold.HOLD_S)
    assert said.startswith(youtube_hold.HEAD) and "until Friday at 21:42" in said and youtube_hold.is_words(said)
    assert not youtube_hold.is_words("YouTube couldn't be reached: check your internet connection")


def test_one_call_at_a_time_and_a_little_apart(monkeypatch):
    # why: the window, Preview and Connect never ask YouTube together, and never back to back
    monkeypatch.setattr(youtube_hold, "GAP_S", 0.4)
    spans, lock = [], threading.Lock()

    def call():
        with youtube_hold.turn():
            start = time.time()
            time.sleep(0.2)
            with lock:
                spans.append((start, time.time()))
    threads = [threading.Thread(target=call) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    spans.sort()
    assert len(spans) == 3
    for (_s1, end), (start, _e2) in zip(spans, spans[1:]):
        assert start >= end + 0.35, f"the next call began {start - end:.2f} s after the last ended"


def test_a_turn_waited_for_is_given_up_at_a_stop():
    # why: a Stop (Connect's, the window's Cancel) never waits behind another program's half-hour playlist
    other = locks.take(youtube_hold.LOCK, "someone else's playlist", owner=object())   # (another program)
    try:
        asked = []

        def stop():
            asked.append(1)
            return len(asked) > 2
        started = time.monotonic()
        with pytest.raises(youtube_hold.Stopped):
            with youtube_hold.turn(stop):
                pytest.fail("no call while another holds the turn")
        assert time.monotonic() - started < 3
    finally:
        other.release()


def test_a_turn_records_its_end_even_when_the_call_fails(root):
    with pytest.raises(RuntimeError):
        with youtube_hold.turn():
            raise RuntimeError("yt-dlp crashed")
    assert abs(_record(root)["last"] - time.time()) < 5
    with youtube_hold.turn():                  # and the lock was let go
        pass


def test_a_record_that_cant_be_read_just_now_is_never_written_over(root, monkeypatch):
    # why (review 2): a scanner holding the file as a turn ends would have written {"last": …} over the hold
    until = youtube_hold.hold()
    before = _record(root)
    with monkeypatch.context() as m:
        m.setattr(youtube_hold, "_read", lambda tries=5: None)
        with youtube_hold.turn():
            pass
    assert _record(root) == before and youtube_hold.held() == until


def test_the_turn_is_one_for_every_install_of_this_user():
    # why (review 2): an installed copy and an alpha ask YouTube from one address
    assert youtube_hold.LOCK in locks.SHARED
