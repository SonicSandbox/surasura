"""P4.1 row 4.1.9L (✅ P4.1-1; the intent keeper's S6): *Link…* — an episode's video chosen by the user, its pairing
written through the store's own `register` on the existing item (`app/connect/link.py`): one undoable command, never
a new item, never a move, never over hato's record.

What a wrong answer would cost: a link that adds a second copy of the episode or moves it (the user's order broken by a
click about a video); a link that writes over hato's pairing for that video (hato's timing lost, and another episode
mined with this one's lines); a link with a verdict of its own that skips the timing check (cards cut seconds off);
a cloud placeholder read whole (a download the user never asked for); a link the store's undo can't take back.

The suite's real Japanese and Chinese subtitles in a store built from folders (`connect_helpers.library`), synthetic
videos (`connect_helpers.video`); Connect's loop against `FakeSteps` with the real store-backed `video` / `pairing`
steps and the real fit check over a tsubasa stand-in.
"""
import json
import os

import pytest

from app import settings_manager
from app.connect import fit_check, library, link, runner
from app.connect.ledger import Ledger
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.connect.fake_steps import FakeSteps

WORDS = [("上層部", "ジョウソウブ"), ("一生懸命", "イッショウケンメイ"), ("走り出す", "ハシリダス")]


def _episode(lang="ja"):
    """A library (Connect on, its watermark set) -> (store, its first item's id)."""
    c.library(lang)
    s = c.store(lang)
    library.switch_on(s)
    return s, s.ids("now")[0]


class Tsubasa:
    """`subprocess.run`'s stand-in for tsubasa: its one JSON line; each call's command kept."""

    def __init__(self, outcome="CONFIDENT", offset=-1.5):
        self.answer = c.tsubasa_answer(outcome, [[None, offset]] if outcome == "CONFIDENT" else [])
        self.calls = []

    def __call__(self, command, **_k):
        self.calls.append(command)
        return type("Done", (), {"stdout": json.dumps(self.answer).encode("utf-8"), "returncode": 0})()


class LinkedSteps(FakeSteps):
    """FakeSteps with the real store-backed `pairing` / `video` / `subtitle` and the real fit check (tsubasa a
    stand-in): what a linked episode meets in Connect's run."""

    def __init__(self, folder, plan, tsubasa):
        super().__init__(folder, plan)
        self.real = runner.Steps(settings_manager.load_settings())
        self.tsubasa = tsubasa

    def pairing(self, lang, job):
        return self.real.pairing(lang, job)

    def video(self, lang, job):
        return self.real.video(lang, job)

    def fit(self, lang, job, pairing, video, subtitle):
        self.log.append(("fit", job["item_id"]))
        return fit_check.fit(pairing, video, self.real.subtitle(lang, job), tsubasa="tsubasa", run=self.tsubasa)


def _run(tmp_path, item, tsubasa, lang="ja"):
    plan = {"line": {lang: [item]}, "queue": {lang: [item]}, "words": {str(item): WORDS}}
    steps = LinkedSteps(str(tmp_path), plan, tsubasa)
    with Ledger() as ledger:
        runner.run({}, [lang], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        job = ledger.job(lang, item)
        return steps, job, ledger.picked(job["id"]) or {}, [n for n in ledger.needs(lang)]


def _state(s):
    """The store's items as they stand (id, tier, place) and its placement log's end: nothing moved, nothing added."""
    return [(i, s.place_of(i)) for i in s.ids("now")] + [("log", library.log_seq(s))]


def test_a_linked_episode_is_checked_by_tsubasa_and_mined_with_its_offset(tmp_path):
    s, item = _episode()
    video = c.video("Example Show - 05.mkv")
    before = _state(s)
    with s:
        change = link.link(s, item, video)
        assert change is not None and _state(s) == before, "only the pairing written: no new item, no move"
        rec = library.pairing_of(s, item)
    assert rec["video_path"] == os.path.abspath(video) and rec["producer"] == "surasura"
    assert "verdict" not in rec, "no verdict of its own: Connect's fit check asks tsubasa"
    tsubasa = Tsubasa(offset=-1.5)
    steps, job, picked, needs = _run(tmp_path, item, tsubasa)
    assert job["state"] == "done" and sorted(steps.anki.words()) == sorted(w for w, _r in WORDS)
    assert picked["video"] == os.path.abspath(video) and picked["offset"] == -1.5
    assert len(tsubasa.calls) == 1 and tsubasa.calls[0][2] == os.path.abspath(video), "tsubasa asked on that video"


def test_a_linked_episode_not_timed_is_needs_you(tmp_path):
    s, item = _episode()
    with s:
        link.link(s, item, c.video("Example Show - 05.mkv"))
    steps, job, _picked, needs = _run(tmp_path, item, Tsubasa(outcome="REFUSED"))
    assert steps.anki.words() == [] and job["state"] == "waiting"
    assert [n["kind"] for n in needs] == ["not-timed"], "*Needs you*'s *Mine anyway* is next (row 4.1.9)"


def _renamed(path, old, new):
    """`path` with its file name's `old` made `new` — never the folders' (a pytest temp folder can hold "05")."""
    return os.path.join(os.path.dirname(path), os.path.basename(path).replace(old, new))


@pytest.mark.parametrize("how", ["renamed", "moved"])
def test_a_renamed_or_moved_video_is_no_video_again(tmp_path, how):
    s, item = _episode()
    video = c.video("Example Show - 05.mkv")
    with s:
        link.link(s, item, video)
    if how == "renamed":
        os.rename(video, _renamed(video, "05", "05 (old)"))
    else:
        away = os.path.join(os.path.dirname(os.path.dirname(video)), "elsewhere")
        os.makedirs(away)
        os.rename(video, os.path.join(away, os.path.basename(video)))
    steps, job, _picked, _needs = _run(tmp_path, item, Tsubasa())
    assert (job["state"], job["reason"]) == ("waiting", runner.NO_VIDEO) and steps.anki.words() == []


def test_the_stores_undo_takes_the_link_back(tmp_path):
    s, item = _episode()
    with s:
        change = link.link(s, item, c.video("Example Show - 05.mkv"))
        s.undo(change)
        assert library.pairing_of(s, item) is None


def test_a_placeholder_a_subtitle_or_a_missing_file_is_refused_and_nothing_is_written(tmp_path, monkeypatch):
    s, item = _episode()
    video = c.video("Example Show - 05.mkv")
    srt = os.path.join(os.path.dirname(video), "Example Show - 05.ja.srt")
    with open(srt, "w", encoding="utf-8") as f:
        f.write("1\n00:00:01,000 --> 00:00:02,000\n上層部の命令だ\n")
    with s:
        stored = c.store_state()
        with pytest.raises(link.Refused, match="isn't a video"):
            link.link(s, item, srt)
        with pytest.raises(link.Refused, match="isn't there"):
            link.link(s, item, _renamed(video, "05", "06"))
        monkeypatch.setattr(runner, "_on_disk", lambda path: False)        # a cloud placeholder: never read
        read = []
        monkeypatch.setattr(link, "_sha256", lambda p: read.append(p) or "0" * 64)
        with pytest.raises(link.Refused, match="cloud"):
            link.link(s, item, video)
        assert read == [] and library.pairing_of(s, item) is None
    assert c.store_state() == stored


def test_a_second_link_replaces_the_first_for_connect(tmp_path):
    s, item = _episode()
    first, second = c.video("Example Show - 05.mkv"), c.video("Example Show - 05 [BD].mkv")
    with s:
        link.link(s, item, first)
        link.link(s, item, second)
        assert library.pairing_of(s, item)["video_path"] == os.path.abspath(second), "the newest pairing wins"
        assert link.link(s, item, second) is None, "the same link again: nothing written"


def test_a_video_hato_paired_keeps_hatos_record(tmp_path):
    s, item = _episode()
    other = [i for i in s.ids("now") if i != item][0]
    sub = os.path.join(s.data_dir, *s.item(other)["rel_path"].split("/"))
    hato = c.hato_record(sub, 5)                        # hato paired its video with another episode
    with s:
        s.register(sub, hato)
        kept = s.conn.execute("SELECT item_id, pairing FROM pairings").fetchall()
        with pytest.raises(link.Refused, match="hato has already paired"):
            link.link(s, item, hato["video_path"])
        assert s.conn.execute("SELECT item_id, pairing FROM pairings").fetchall() == kept, "never written over"
        assert library.pairing_of(s, item) is None


def test_a_chinese_episode_links_too(tmp_path):
    s, item = _episode("zh")
    with s:
        link.link(s, item, c.video("示例节目 - 05.mp4"))
        rec = library.pairing_of(s, item)
    assert rec["language"] == "zh" and rec["video_path"].endswith("示例节目 - 05.mp4")


class _RunningSteps(LinkedSteps):
    """A Connect running for hours (Mattias's, 3.0.0): its wake mark read as the real run reads it, and every video
    look kept — `during_pause` is the user's press while it pauses between two looks."""

    def __init__(self, folder, plan, tsubasa, during_pause):
        super().__init__(folder, plan, tsubasa)
        self.during_pause, self.videos_found = during_pause, []

    def kicked(self):
        return self.real.kicked()

    def video(self, lang, job):
        found = super().video(lang, job)
        self.videos_found.append((job["item_id"], found))
        return found

    def sleep(self, _seconds):
        press, self.during_pause = self.during_pause, None
        if press is not None:
            press()

    def mine(self, lang, job, picked, words, attempt):
        press, self.during_mine = getattr(self, "during_mine", None), None
        if press is not None:
            press()                                     # the user's press while Anki Miner makes this one's cards
        return super().mine(lang, job, picked, words, attempt)


def test_a_video_linked_while_connect_runs_is_mined_from_in_the_same_run(tmp_path, lang="ja"):
    # why (Michi-VF): Mattias's episodes waited *No video* while Connect ran on (other episodes kept it looking);
    # he picked each video by hand and nothing changed until a restart that never came. The link, through the
    # window's own Link (as the writer's hook calls it), must let the next look find that video and go on —
    # here to Anki Miner (busy: the episode then waits on it, never on *No video*). Japanese: Connect waits on a
    # Chinese episode before its pick (E24); the link's kick is the same for both (`test_p41_window_link`)
    from app.connect import window_link
    s, item = _episode(lang)
    other = s.ids("now")[1]
    with s:
        link.link(s, other, c.video("Other - 02.mkv"))                  # the episode keeping it looking
    video = c.video("[NanakoRaws] Example Show S4 - 12 (AT-X 1080p).mkv")

    def pick_it_by_hand():
        with c.store(lang) as st:
            assert link.link(st, item, video) is not None
        on = window_link.Link(lang, lambda: {"connect_enabled": True}, running=lambda: True)
        assert on.after_change(op=window_link.LINKED) == window_link.RUNNING

    plan = {"line": {lang: [item, other]}, "queue": {lang: [item, other]}, "words": {str(item): WORDS,
            str(other): WORDS}, "miner_busy": True}
    steps = _RunningSteps(str(tmp_path), plan, Tsubasa(), pick_it_by_hand)
    with Ledger() as ledger:
        summary = runner.run({}, [lang], steps=steps, ledger=ledger, sleep=steps.sleep, looks=3)
    mine = [found for i, found in steps.videos_found if i == item]
    assert mine[0] is None, "no video at the first look: No video, parked"
    assert mine[1:] and all(found == os.path.abspath(video) for found in mine[1:]), "looked at again after the link"
    assert summary["languages"][lang]["waiting"][item] == runner.ANKI_MINER_OPEN, "past No video: at Anki Miner"


def test_a_video_linked_during_connects_last_pass_is_mined_before_it_exits(tmp_path):
    # why (Michi-VF review B1): nothing holding Connect open — its pass parks episode A on *No video*, then mines B
    # (a minute of Anki Miner) while you link A's video. The pass ends with nothing to look at again, and a link puts
    # nothing in the inbox: exiting there leaves A parked for a start no one makes. The wake read before the exit
    # takes one more pass, and A is mined
    from app.connect import window_link
    s, item = _episode()
    other = s.ids("now")[1]
    with s:
        link.link(s, other, c.video("Other - 02.mkv"))
    video = c.video("[NanakoRaws] Example Show S4 - 13 (AT-X 1080p).mkv")

    def pick_it_by_hand():
        with c.store() as st:
            assert link.link(st, item, video) is not None
        on = window_link.Link("ja", lambda: {"connect_enabled": True}, running=lambda: True)
        assert on.after_change(op=window_link.LINKED) == window_link.RUNNING

    plan = {"line": {"ja": [item, other]}, "queue": {"ja": [item, other]},
            "words": {str(item): WORDS, str(other): [("約束", "ヤクソク"), ("勇気", "ユウキ")]}}
    steps = _RunningSteps(str(tmp_path), plan, Tsubasa(), None)
    steps.during_mine = pick_it_by_hand
    with Ledger() as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=steps.sleep, looks=5)
        assert ledger.job("ja", other)["state"] == "done"
        assert ledger.job("ja", item)["state"] == "done", "mined in the same run, never left on No video"
    assert [found for i, found in steps.videos_found if i == item] == [None, os.path.abspath(video)]
    assert sorted(steps.anki.words()) == sorted([w for w, _r in WORDS] + ["約束", "勇気"])
