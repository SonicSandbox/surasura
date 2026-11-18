"""A top-20 file Connect will never mine by itself shows *Mine*, never the hourglass (Michi-EO, Sonic's ruling Q-EO2).

Why these matter: the hourglass's tip says *it mines by itself, in turn*. A file that was in the top 20 before Connect
was switched on is never logged (✅ G1.1-2), so Connect holds no job for it and will make none: a tester's 3.0.15 report
had episodes 1–7 under the hourglass for good. The store's feed now says which top files have an entry Connect hasn't
read yet (`mine_unread`); a top file with neither a Connect job nor such an entry is *Mine* (today's button, its face
the status's), its tip saying it isn't mined by itself. A file Connect will read, or holds a job for, keeps *Waiting*;
a store that doesn't say (no `mine_unread`) keeps today's view. Japanese and Chinese titles; hand-made feed rows.
"""
import pytest

from app.services import view_rows as vr
from tests.test_view_rows import WORKS, _feed, _job, eps, items_of, work

TITLES = {"ja": "星降る街の小さな工房", "zh": "云上的邮递员"}


@pytest.fixture(autouse=True)
def _works():
    WORKS.clear()
    work(1, TITLES["ja"])
    work(2, TITLES["zh"])
    yield
    WORKS.clear()


def _items(language):
    wid = 1 if language == "ja" else 2
    return items_of([("now", wid, 1, eps(TITLES[language], 1, 6), {})])          # ids 1–6; the top 4: 1–4


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_top_file_with_no_job_and_nothing_unread_says_mine_not_waiting(language):
    """The report's rows: Connect on, no job for the top files, nothing for Connect to read — *Mine*, with the tip that
    says it isn't mined by itself; the row says so too. The files below the line keep their own *Mine*."""
    view = vr.build(_items(language), WORKS, {"mine_line": 4, "mine_unread": []}, connect=_feed([], language=language),
                    language=language)
    row = view.rows[0]
    assert [e.status.kind for e in row.episodes] == ["mine"] * 6
    assert {e.status.tip for e in row.episodes[:4]} == {vr.STRINGS["tip_mine_own"].format(line=4)}
    assert {e.status.tip for e in row.episodes[4:]} == {vr.STRINGS["tip_mine"].format(line=4)}
    assert row.status.kind == "mine" and row.status.label == vr.STRINGS["mine"]
    assert row.status.tip == vr.STRINGS["tip_mine_own"].format(line=4)
    assert "top" in [ln.kind for ln in view.lines], "the top line stays: it is still the top 4"


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_top_file_connect_will_read_or_holds_a_job_for_keeps_waiting(language):
    """Episode 1 has an entry Connect hasn't read (its job is coming), episode 2 a job — both *Waiting*; episodes 3
    and 4 neither — *Mine*. The row reads its first episode Connect speaks for: *Waiting*."""
    feed = _feed([_job(2, state="queued")], language=language)
    row = vr.build(_items(language), WORKS, {"mine_line": 4, "mine_unread": [1]}, connect=feed,
                   language=language).rows[0]
    assert [e.status.kind for e in row.episodes[:4]] == ["waiting", "waiting", "mine", "mine"]
    assert row.status.kind == "waiting"


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_some_mined_and_the_rest_never_by_itself_says_mine_rest(language):
    """Two episodes mined (their cards in Anki), the other top two with no job: *2/6 · Mine rest*, its tip that the
    rest isn't mined by itself — never *2/6 · Waiting*."""
    items = _items(language)
    for i in (1, 2):
        items[i]["mined_at"] = "2026-11-16T09:00:00Z"
    row = vr.build(items, WORKS, {"mine_line": 4, "mine_unread": []}, cards={1: 4, 2: 3},
                   connect=_feed([], language=language), language=language).rows[0]
    assert row.status.kind == "mine_rest" and row.status.label == vr.STRINGS["mine_rest"].format(k=2, n=6)
    assert row.status.tip == vr.STRINGS["tip_mine_rest_own"].format(k=2, n=6)
    assert [e.status.kind for e in row.episodes[:4]] == ["in_anki", "in_anki", "mine", "mine"]


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_store_that_doesnt_say_and_connect_off_keep_todays_view(language):
    """No `mine_unread` (a feed from before, JSON mode): *Waiting* as before. Connect off: no top, *Mine* with today's
    tip (row 13). No feed: as without Connect."""
    from app.connect import feed
    items = _items(language)
    before = vr.build(items, WORKS, {"mine_line": 4}, connect=_feed([], language=language), language=language)
    assert [e.status.kind for e in before.rows[0].episodes[:4]] == ["waiting"] * 4
    off = vr.build(items, WORKS, {"mine_line": 4, "mine_unread": []}, connect=feed._off({}), language=language)
    assert {e.status.tip for e in off.rows[0].episodes} == {vr.STRINGS["tip_mine_off"]}
    plain = vr.build(items, WORKS, {"mine_line": 4, "mine_unread": []}, language=language)
    assert [e.status.kind for e in plain.rows[0].episodes[:4]] == ["waiting"] * 4


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_an_unchanged_feed_builds_the_same_row_objects(language):
    """S19 (redraw waste is a defect): the same Connect feed and the same files give the rows' cache the same feed
    items twice, so the second build hands back the very same row — nothing repainted."""
    cache = vr.RowCache()
    items = _items(language)
    feed = _feed([], language=language)
    options = {"mine_line": 4, "mine_unread": []}
    numbers, cards = (1, {}), {99: 1}                  # one numbers version, one cards dict (as the reader keeps)
    first = vr.build(items, WORKS, options, numbers=numbers, cards=cards, connect=feed, cache=cache,
                     language=language)
    second = vr.build(items, WORKS, dict(options), numbers=numbers, cards=cards, connect=feed, cache=cache,
                      language=language)
    assert second.rows[0] is first.rows[0]
    assert first.rows[0].status.kind == "mine"
    assert cache.same_global, "the feed items the rows read are the same object: the fast path"
