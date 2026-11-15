"""Kura-NT, based on Mattias's #454 (his 3.0.10 report): The Apothecary Diaries S01 Ep 3, 4 and 8 read *No cards in
Anki* — "It was mined, but none of its cards are in Anki now: cards you deleted aren't made again unless you ask". He
had deleted nothing: their jobs ended `done` with `no words to make cards from`, every word they hold already on a card
(患う made from Ep 2 a moment before). The row couldn't tell "made, then deleted" from "nothing to make": its receipt
with no card was both.

Now Connect's record names each item whose newest job (never a level raise's) found nothing to make, that no open job
holds and of which no card was ever made (`status`'s `nothing`); the feed gives it a NOTHING item and its row reads
*Nothing new to mine*, its tip why. A part whose cards were really deleted still reads *No cards in Anki*, a row mixing
both too; the strip and *Needs you* pass the new kind by. The stone's look: `test_stone_plan.py`.

What a wrong answer would cost: a learner told he deleted cards he never had, looking for them in Anki; or a part whose
cards he did delete said to have had nothing to make.

Against `FakeSteps` and a real ledger read by the real status record and feed; real Japanese and Chinese words. No live
Anki, no sleeps.
"""
from types import SimpleNamespace

import pytest

from app.connect import feed, runner, status
from app.connect.ledger import Ledger, _now
from app.services import status as window_status
from app.services import needs as window_needs
from app.services import view_rows
from tests.connect.fake_steps import FakeSteps

WORDS = {"ja": [("患う", "わずらう"), ("推測", "すいそく"), ("帰還", "きかん")],
         "zh": [("认识", "rènshi"), ("突然", "tūrán"), ("已经", "yǐjīng")]}
DELETED = view_rows.Status("deleted", view_rows.STRINGS["deleted"], view_rows.STRINGS["tip_deleted"], "faint")


def _run(steps, path, lang):
    with Ledger(path) as ledger:
        runner.run({}, [lang], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        return [(j["item_id"], j.get("kind") or "mine", j["state"], j.get("reason")) for j in ledger.jobs(lang)]


def _two_episodes(tmp_path, lang="ja"):
    """Ep 1 and Ep 2 hold the same words: Ep 1 makes their cards, Ep 2 finds every one carded."""
    plan = {"line": {lang: [1, 2]}, "queue": {lang: [1, 2]}, "words": {"1": WORDS[lang], "2": WORDS[lang]}}
    steps = FakeSteps(str(tmp_path), plan)
    path = str(tmp_path / "ledger.sqlite")
    got = _run(steps, path, lang)
    assert got == [(1, "mine", "done", None), (2, "mine", "done", runner.NO_WORDS)], \
        f"why: Ep 2 must end with nothing to make, or this proves nothing: {got}"
    return steps, path


def _record(path, lang="ja"):
    return status.read(languages=[lang], path=path)


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_part_mined_with_nothing_new_reads_nothing_new_to_mine_never_cards_you_deleted(tmp_path, lang):
    _steps, path = _two_episodes(tmp_path, lang)
    rec = _record(path, lang)["languages"][lang]
    assert rec["nothing"] == [2], "Ep 1 made its cards: only Ep 2 had nothing new"
    item = feed.build(_record(path, lang), lang).items[2]
    assert (item.kind, item.words, item.job) == (feed.NOTHING, "Nothing new to mine", None)
    st = view_rows._connected(DELETED, item, "video")
    assert (st.kind, st.label, st.tip, st.tone) == ("nothing", "Nothing new to mine",
                                                    view_rows.STRINGS["tip_nothing"], "faint")
    assert "deleted" not in st.tip
    assert 1 not in feed.build(_record(path, lang), lang).items, "a part that made its cards has no stone of Connect's"


def test_a_part_whose_cards_were_made_then_deleted_still_reads_no_cards_in_anki(tmp_path):
    """Ep 1 made its cards; asked again while they were there, its new job found nothing new (done, NO_WORDS). The
    learner then deleted them: *No cards in Anki · cards you deleted* is the truth — never *Nothing new to mine*."""
    steps, path = _two_episodes(tmp_path)
    with Ledger(path) as ledger, ledger.transaction():
        assert ledger.ask("ja", 1, _now(), store_id="store-1")[0] == "queued"
    got = _run(steps, path, "ja")
    assert got[-1] == (1, "asked", "done", runner.NO_WORDS), f"why: the ask must find nothing new: {got}"
    rec = _record(path)["languages"]["ja"]
    assert rec["nothing"] == [2], "a part a card was ever made of is never *Nothing new*"
    item = feed.build(_record(path), "ja").items.get(1)
    assert view_rows._connected(DELETED, item, "video") is DELETED


def test_a_level_raises_nothing_to_make_never_marks_a_part(tmp_path):
    """A level raise mines only an item's newly listed words: its *nothing to make* says nothing of the rest. Ep 1's
    mining failed (none made), then a level job found its one word carded: it stays *Try again*, never *Nothing*."""
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "words": {"1": WORDS["ja"]},
            "crash_mid_batch": 0, "crash_always": True}
    steps = FakeSteps(str(tmp_path), plan)
    path = str(tmp_path / "ledger.sqlite")
    assert [s for _i, _k, s, _r in _run(steps, path, "ja")] == ["failed"]
    steps.anki.add("溜め息", "made-elsewhere")          # its level word already has a card
    steps.plan.update(crash_mid_batch=None, crash_always=False, queue={}, level=[("ja", 1, [["溜め息", "ためいき"]])])
    got = _run(steps, path, "ja")
    assert got[-1] == (1, "level", "done", runner.NO_WORDS), f"why: the level job must find nothing new: {got}"
    assert _record(path)["languages"]["ja"]["nothing"] == []
    assert feed.build(_record(path), "ja").items[1].kind == feed.FAILED


def test_a_part_with_an_open_job_is_not_nothing_new(tmp_path):
    """*Mine* asked again (new words listed, or a level raise queued): its open job's stone, never the old *Nothing*."""
    _steps, path = _two_episodes(tmp_path)
    with Ledger(path) as ledger, ledger.transaction():
        assert ledger.ask("ja", 2, _now(), store_id="store-1")[0] == "queued"
    assert _record(path)["languages"]["ja"]["nothing"] == []
    assert feed.build(_record(path), "ja").items[2].kind == feed.ASKED
    (tmp_path / "level").mkdir()
    _steps, path = _two_episodes(tmp_path / "level")
    with Ledger(path) as ledger, ledger.transaction():
        ledger.queue_level("ja", 2, [("溜め息", "ためいき")], store_id="store-1")
    assert _record(path)["languages"]["ja"]["nothing"] == []
    assert feed.build(_record(path), "ja").items[2].kind != feed.NOTHING


def test_a_shows_row_says_nothing_new_only_when_every_part_holding_no_card_had_nothing_new(tmp_path):
    connect = feed.build(_record(_two_episodes(tmp_path)[1]), "ja").items
    one = [SimpleNamespace(id=2, cards=0, deleted=True, online=None)]
    st = view_rows._row_connected(DELETED, one, connect, "video")
    assert (st.kind, st.label, st.tip) == ("nothing", "Nothing new to mine", view_rows.STRINGS["tip_nothing"])
    two = {2: connect[2], 3: connect[2]}
    both = one + [SimpleNamespace(id=3, cards=0, deleted=True, online=None)]
    assert view_rows._row_connected(DELETED, both, two, "video").label == "Nothing new to mine · 2"
    mixed = one + [SimpleNamespace(id=9, cards=0, deleted=True, online=None)]   # Ep 9's cards were deleted
    assert view_rows._row_connected(DELETED, mixed, connect, "video") is DELETED


def test_a_nothing_item_never_changes_a_part_with_cards_or_one_not_mined():
    item = feed.Item(kind=feed.NOTHING, words=feed.WORDS[feed.NOTHING], tip=feed.WORDS[feed.NOTHING], job=None,
                     made=0, total=0)
    in_anki = view_rows.Status("in_anki", "2", "", "ok")
    mine = view_rows.Status("mine", "Mine", "", "ink")
    assert view_rows._connected(in_anki, item, "video") is in_anki
    assert view_rows._connected(mine, item, "video") is mine
    assert view_rows._row_connected(in_anki, [SimpleNamespace(id=2, cards=3, deleted=False, online=None)],
                                    {2: item}, "video") is in_anki


def test_the_strip_and_needs_you_pass_a_nothing_item_by(tmp_path):
    """The phase strip's waits and *Needs you*'s Anki line read the feed's kinds: nothing new waits on no one."""
    _steps, path = _two_episodes(tmp_path)
    record = _record(path)
    items = feed.build(record, "ja").items
    assert items[2].kind == feed.NOTHING
    assert window_status._waits(tuple(items.values())) == {}
    assert window_status.CONNECT_WAITS.get(feed.NOTHING) is None
    assert window_needs._anki_waits(record["languages"]["ja"]) == {}


def test_an_empty_ledger_names_nothing(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")):
        pass
    assert _record(str(tmp_path / "ledger.sqlite"))["languages"]["ja"]["nothing"] == []


def test_only_a_job_that_found_no_word_counts_and_only_in_its_own_language(tmp_path):
    """One ledger, both languages, the same item ids: ja 7 found nothing (zh 7 made a card — another title's part);
    ja 8 ended done for another reason with none made (never *Nothing new*: it was stopped); zh 9 found nothing while
    ja 9 waits (another language's open job holds nothing of zh's)."""
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger, ledger.transaction():
        ja7 = ledger.queue("ja", 7, "user", None, store_id="store-1")
        ledger.set_state(ja7, "done", reason=runner.NO_WORDS)
        zh7 = ledger.queue("zh", 7, "user", None, store_id="store-1")
        ledger.record_outcomes(zh7, 1, [{"word": "认识", "reading": "rènshi", "outcome": "made", "note_id": 5001}])
        ledger.set_state(zh7, "done")
        ja8 = ledger.queue("ja", 8, "user", None, store_id="store-1")
        ledger.set_state(ja8, "done", reason=runner.STOPPED_BY_YOU)
        zh9 = ledger.queue("zh", 9, "user", None, store_id="store-1")
        ledger.set_state(zh9, "done", reason=runner.NO_WORDS)
        assert ledger.queue("ja", 9, "user", None, store_id="store-1") is not None
    rec = status.read(languages=["ja", "zh"], path=path)["languages"]
    assert (rec["ja"]["nothing"], rec["zh"]["nothing"]) == ([7], [9])


def _episode(n, cards=0, deleted=True):
    return view_rows.Episode(id=n, label=f"第{n}話", number=n, title="薬屋のひとりごと", watched=False, cards=cards,
                             mining=False, missing=False, removed=False, in_top=True, pct=0, n_new=0, status=None,
                             mark=None, rel_path=f"HighPriority/薬屋のひとりごと/薬屋のひとりごと {n:02d}.srt",
                             play_tip="", can_play=True, deleted=deleted)


def test_a_rows_status_built_from_its_episodes_reads_nothing_new_and_a_mixed_row_no_cards():
    """Through `status_of` with real episodes: every part mined, none holding a card, is the row's *No cards in Anki*
    — and Connect's feed turns it into *Nothing new to mine* only when every one of them had nothing new."""
    item = feed.Item(kind=feed.NOTHING, words=feed.WORDS[feed.NOTHING], tip=feed.WORDS[feed.NOTHING], job=None,
                     made=0, total=0)
    eps = [_episode(3), _episode(4), _episode(8)]
    st, _mark = view_rows._row_status(eps, "video", 20, {3: item, 4: item, 8: item})
    assert (st.kind, st.label) == ("nothing", "Nothing new to mine · 3")
    st, _mark = view_rows._row_status(eps, "video", 20, {3: item, 4: item})       # Ep 8's cards were deleted
    assert (st.kind, st.label) == ("deleted", "No cards in Anki · 3")
    st, _mark = view_rows._row_status(eps[:2] + [_episode(8, cards=6, deleted=False)], "video", 20, {3: item, 4: item})
    assert st.kind == "in_anki", "a row with cards in Anki keeps its ✓"
