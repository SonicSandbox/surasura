"""Connect mines a show from its first episode, not from the first one that crossed into the top 20 after it was
switched on (Michi-EO, 3.0.16).

Why these matter: Connect makes a job only of an item that ENTERS the top 20 after its watermark (`inbox.consume`, ✅
G1.1-2): what was already in the line at the switch-on is never logged. Setup places the shows (its sort screen) before
its page 5 turns Connect on, so a show's first episodes sit in the line unlogged; when the learner then finishes or
moves something above them, the show's NEXT episodes cross the line and get jobs — and the show is mined from episode 8,
episodes 1–7 never (a tester's 3.0.15 report). Sonic's ruling (2026-11-17, Q-EO1): a show is one unit — when Connect
queues any part of a show, every earlier part of it in Current (an earlier season too) that isn't mined and never had
a job is queued with it, ahead of it; the learner's own *Mine* still first, the cap and "never re-queue" unchanged.
Every test runs for Japanese and Chinese under the per-test SURASURA_TEST_ROOT, with real words from
tests/Test Resources/ (the episode-order tests' own registration).
"""

import pytest

from app import library_store as ls
from app.connect import inbox
from app.connect.ledger import SHOW, Ledger
from tests.test_library_store_episode_order import _episode
from tests.test_library_store_support import LANGUAGES, migrated, names, roots, touch


def _split_show(language):
    """The report's library: a 12-episode show placed by setup's sort (no reader yet: nothing logged), another show's
    13 files above it, then Connect switched on (its watermark at the log's end). The top 20 holds the other show's 13
    and episodes 1–7; 8–12 sit below it. -> (store, the show's ids by episode, the other show's ids)."""
    store = migrated(language, shows=0, episodes=0)
    w = names(language)
    eps = [_episode(store, language, w[160], n) for n in range(1, 13)]
    store.place(eps, "top")
    other = [_episode(store, language, w[161], n, season=3) for n in range(1, 14)]
    store.place(other, "top")
    store.register_reader("connect")
    assert set(eps[:7]) <= set(store._mine_ids(20)) and not set(eps[7:]) & set(store._mine_ids(20)), "the setup"
    return store, eps, other


def _video(store, language, show, word, n):
    """One video of a title whose records name no episode (a channel's videos: no number in the record or the name)
    -> its item id."""
    data_dir, _u = roots(language)
    video = str(91903000 + n)
    record = {"schema": 1, "producer": "browser", "language": language, "content_key": f"netflix:{video}",
              "video_id": video, "title": word, "show": {"title": show}}
    return store.register(touch(data_dir, f"{ls.PROCESSED_FOLDER}/{show} {word}.txt", f"{show} {word}\n"),
                          record).added[0]


def _jobs(ledger, language, states=("queued",)):
    return {j["item_id"]: j for j in ledger.jobs(language, states=states)}


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_show_split_by_the_switch_on_is_mined_from_its_first_episode(language):
    """The report: the learner finishes one of the other show's files, episode 8 crosses into the top 20 — its job
    comes with episodes 1–7's, and the line's order runs episode 1 first."""
    from app.connect.runner import _ordered
    store, eps, other = _split_show(language)
    with Ledger() as ledger:
        assert inbox.consume(store, language, ledger)["queued"] == [], "the switch-on alone mines nothing (G1.1-2)"
        store.finish(other[:1])
        inbox.consume(store, language, ledger)
        jobs = ledger.jobs(language, states=("queued",))
        assert {j["item_id"] for j in jobs} == set(eps[:8])
        line = store._mine_ids(20)
        assert [j["item_id"] for j in _ordered(jobs, line)] == eps[:8], "episode 1 first, then in episode order"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_show_whole_in_the_line_at_the_switch_on_is_still_never_mined_by_itself(language):
    """G1.1-2 unchanged where nothing of the show crosses later: a show that was all in the top 20 at the switch-on
    gets no job until the learner asks (D1's *Make cards*, *Mine*)."""
    store, eps, other = _split_show(language)
    with Ledger() as ledger:
        store.finish(eps[7:])                    # its later episodes go: nothing of the show crosses the line
        inbox.consume(store, language, ledger)
        assert not {j["item_id"] for j in ledger.jobs(language)} & set(eps)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_earlier_season_in_current_below_the_line_is_mined_first_and_kept_below_it(language):
    """Q-EO1 (earlier seasons count as earlier parts): season 1 sits in Current below the top 20 when season 2 comes in
    at the top — season 1 is queued with it, mined ahead of it, first episode first, and stays queued below the line
    (a show's part is kept while it is in Current; a plain job there would be dropped as *left*)."""
    from app.connect.runner import _ordered
    store = migrated(language, shows=0, episodes=0)
    w = names(language)
    s1 = [_episode(store, language, w[170], n, season=1) for n in range(1, 13)]
    store.place(s1, "top")
    other = [_episode(store, language, w[171], n, season=5) for n in range(1, 26)]
    store.place(other, "top")
    store.register_reader("connect")
    s2 = [_episode(store, language, w[170], n, season=2) for n in range(1, 4)]
    store.place(s2, "top")
    line = store._mine_ids(20)
    assert set(s2) <= set(line) and not set(s1) & set(line), "the setup: season 2 in the top, season 1 below"
    with Ledger() as ledger:
        inbox.consume(store, language, ledger)
        jobs = _jobs(ledger, language)
        assert set(jobs) == set(s1 + s2)
        assert {i for i, j in jobs.items() if j["kind"] == SHOW} == set(s1), "season 2's own jobs are plain ones"
        assert {j["source"] for j in jobs.values()} == {"user"}, "by the person whose move brought season 2 in"
        assert [j["item_id"] for j in _ordered(list(jobs.values()), line)] == s1 + s2
        store.finish(other[:3])                 # a look with events: season 1 still below the line, still queued
        inbox.consume(store, language, ledger)
        assert set(s1) <= set(_jobs(ledger, language))
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_title_with_no_episode_numbers_keeps_todays_order(language):
    """The card: a title whose parts name no episode (a channel's videos) has no earlier part to read — the file that
    crossed the line alone is queued, as before; the others above it wait for the learner, as G1.1-2 says."""
    store = migrated(language, shows=0, episodes=0)
    w = names(language)
    vids = [_video(store, language, w[172], w[180 + n], n) for n in range(12)]
    assert len({store.item(i)["work_id"] for i in vids}) == 1, "the setup: one title"
    store.place(vids, "top")
    other = [_episode(store, language, w[173], n) for n in range(1, 14)]
    store.place(other, "top")
    store.register_reader("connect")
    line = store._mine_ids(20)
    assert set(vids[:7]) <= set(line) and vids[7] not in line, "the setup"
    with Ledger() as ledger:
        store.finish(other[:1])
        inbox.consume(store, language, ledger)
        assert set(_jobs(ledger, language)) == {vids[7]}
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_learners_mine_goes_first_then_the_shows_earlier_parts(language):
    """The learner's own *Mine* on episode 10 still goes first; the show's earlier episodes in Current (1–7 in the top
    20, 8–9 below it) come with it, in episode order after it. None of them is an ask: the cap holds them as any."""
    from app.connect.runner import _ordered, held_by_cap
    store, eps, other = _split_show(language)
    with Ledger() as ledger:
        store.ask_mining([eps[9]])
        inbox.consume(store, language, ledger)
        jobs = _jobs(ledger, language)
        assert set(jobs) == set(eps[:10])
        assert [j["item_id"] for j in _ordered(list(jobs.values()), store._mine_ids(20))] == [eps[9]] + eps[:9]
        assert not any(held_by_cap(bool(jobs[eps[9]].get("asked_at"))) for _ in (1,)), "the ask passes the cap"
        assert all(held_by_cap(bool(jobs[i].get("asked_at"))) for i in eps[:9]), "its show's parts don't"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_mined_part_or_one_that_had_a_job_is_never_queued_again(language):
    """Never re-queue: episode 2 is mined (its receipt) and episode 3's job was dropped once; episode 5 sits in 6+
    Months (only Current's parts come) — when episode 8 crosses the line, only 1, 4, 6 and 7 come with it."""
    store, eps, other = _split_show(language)
    store.receipt(eps[1], "2026-11-16T09:00:00Z")
    store.place([eps[4]], "goal")
    with Ledger() as ledger:
        ledger.queue(language, eps[2], "user", None, store_id="old")
        ledger.drop(language, eps[2], "left the top 20")
        inbox.consume(store, language, ledger)
        if eps[7] not in _jobs(ledger, language):   # (episode 5's move made room: 8 is in already — or not yet)
            store.finish(other[:1])
            inbox.consume(store, language, ledger)
        jobs = _jobs(ledger, language)
        assert {i for i, j in jobs.items() if j["kind"] == SHOW} == {eps[0], eps[3], eps[5], eps[6]}
        assert jobs[eps[7]]["kind"] == "mine"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_shows_part_moved_out_of_current_is_dropped(language):
    """A show's earlier part is kept below the top 20 only while it is in Current: moved to 6+ Months (no line crossed:
    it was below it) its job goes at the next look, as one that left; finished, too. Another part stays queued."""
    store, eps, other = _split_show(language)
    with Ledger() as ledger:
        store.ask_mining([eps[11]])             # 8–11 below the line come too, as the show's parts
        inbox.consume(store, language, ledger)
        assert _jobs(ledger, language)[eps[8]]["kind"] == SHOW
        store.place([eps[8]], "goal")
        store.finish([eps[9]])
        out = inbox.consume(store, language, ledger)
        assert {eps[8], eps[9]} <= set(out["dropped"])
        jobs = _jobs(ledger, language)
        assert eps[8] not in jobs and eps[9] not in jobs and eps[10] in jobs
        store.place([eps[2]], "goal")               # one in the top 20 (it leaves the line) out of Current: dropped
        assert eps[2] in inbox.consume(store, language, ledger)["dropped"]
        assert eps[2] not in _jobs(ledger, language) and eps[3] in _jobs(ledger, language)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_gap_drops_a_shows_part_out_of_current_and_keeps_one_below_the_line(language):
    """A gap (the log can't be trusted: `_gone`'s reconcile) keeps a show's part below the top 20 while it is in
    Current, and drops one placed in 6+ Months — as the events would have."""
    store, eps, other = _split_show(language)
    with Ledger() as ledger:
        store.ask_mining([eps[11]])
        inbox.consume(store, language, ledger)
        store.place([eps[8]], "goal")
        gone = inbox._gone(store, ledger, language)
        assert gone.get(eps[8]) == "finished" and eps[9] not in gone
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_seasons_title_and_a_folders_names_read_as_one_show_in_order(language):
    """The one "same show?" key with a season written at a title's end left off (`Show S2`, `Show 2nd Season`: the
    store keeps another season as another title), and a file's own place when its record names none — a season
    folder's, an `S02E05` name's, a folder's K4 number."""
    from app.connect import library
    w = names(language)
    assert library._show_of(f"{w[174]} S2") == library._show_of(w[174]) == library._show_of(f"{w[174]} 2nd Season")
    assert library._show_of(w[175]) != library._show_of(w[174])
    store = migrated(language, shows=0, episodes=0)
    assert library.part_of(store, -1, f"Library/{w[174]}/Season 02/{w[174]} - 05.srt") == (2, 5)
    assert library.part_of(store, -1, f"Library/{w[174]}/{w[174]} S03E07.srt") == (3, 7)
    assert library.part_of(store, -1, f"Library/{w[174]}/{w[174]} - 04.srt") == (1, 4)
    assert library.part_of(store, -1, f"Library/{w[174]}/{w[176]}.srt") is None
    store.close()


class _Stop(Exception):
    pass


class _Steps:
    """The runner's steps as far as `_job`'s drop: whether the item is in Current, then a stop at the next step."""

    def __init__(self, current):
        self.current = current

    def in_current(self, lang, item_id):
        return self.current

    def watched(self, lang, job):
        raise _Stop()


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("current, dropped", [(True, False), (None, False), (False, True)])
def test_the_runner_keeps_a_shows_part_below_the_line_only_while_it_is_in_current(language, current, dropped):
    """`runner._job`'s drop before mining: a show's part out of the top 20 goes on while its item is in Current (or the
    store is busy: asked again next look), and is dropped as *left* once it isn't. A plain job there is dropped."""
    from app.connect import runner
    with Ledger() as ledger:
        jid = ledger.queue(language, 1, "user", 5, store_id="s", kind=SHOW)
        plain = ledger.queue(language, 2, "user", 6, store_id="s")
        out = runner._empty()
        for job_id in (jid, plain):
            try:
                runner._job(_Steps(current), ledger, language, ledger.job_by_id(job_id), "s", set(), out)
            except _Stop:
                pass
        assert (ledger.job_by_id(jid)["state"] == "dropped") is dropped
        assert ledger.job_by_id(plain)["state"] == "dropped"


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_feed_names_the_top_entries_connect_has_not_read(language):
    """Q-EO2's data (the rows' *Waiting* or *Mine*): the store's feed names the items an entry into the top 20 logged
    that Connect hasn't read — none at the switch-on (episodes 1–7 were never logged), episode 8 once it crosses, none
    again once Connect has read it (its job holds it then). No reader at all: none."""
    store, eps, other = _split_show(language)
    assert store.read_feed()["options"]["mine_unread"] == []
    store.finish(other[:1])
    assert store.read_feed()["options"]["mine_unread"] == [eps[7]]
    with Ledger() as ledger:
        inbox.consume(store, language, ledger)
    assert store.read_feed()["options"]["mine_unread"] == []
    (entry,) = store.conn.execute("SELECT id FROM placement_log WHERE item_id = ? AND kind = 'entered_mine_line'",
                                  (eps[7],)).fetchone()
    store.advance_reader("connect", entry)          # read up to episode 8's entry itself: it is read
    assert store.read_feed()["options"]["mine_unread"] == []
    store.advance_reader("connect", entry - 1)      # one before it: not yet
    assert store.read_feed()["options"]["mine_unread"] == [eps[7]]
    store.unregister_reader("connect")
    store.finish(other[1:2])
    assert store.read_feed()["options"]["mine_unread"] == []
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_show_whose_key_reads_works_and_a_nan_episode_break_nothing(language):
    """Review fixes: a title whose one key folds to the cache's own word (`Works`) reads its parts as any — and a
    second show read through the same look's cache after it too; a record's NaN episode is no place (it would make the
    order inconsistent)."""
    from app.connect import library
    store = migrated(language, shows=0, episodes=0)
    w = names(language)
    works = [_episode(store, language, "Works", n, season=7) for n in range(1, 4)]
    first = [_episode(store, language, w[177], n, season=1) for n in range(1, 3)]       # another show's two seasons:
    other = [_episode(store, language, w[177], n, season=2) for n in range(1, 4)]       # two titles in the store
    store.place(works + first + other, "top")
    cache = {}
    assert library.parts_before(store, works[2], cache) == works[:2]
    assert library.parts_before(store, other[2], cache) == first + other[:2], "its first season's title read too"
    assert library.parts_before(store, works[1], cache) == works[:1]
    real = store._show_record
    store._show_record = lambda item_id: {"show": {"title": w[177], "season": 1, "episode": float("nan")}}
    try:
        assert library.part_of(store, other[0], store.item(other[0])["rel_path"]) is None
        store._show_record = lambda item_id: {"producer": ls.SOURCE_PRODUCER, "episode": float("nan")}
        assert library.part_of(store, other[0], f"Library/{w[177]}/{w[178]}.srt") is None, "a folder's K4 NaN too"
        store._show_record = lambda item_id: {"producer": ls.SOURCE_PRODUCER, "episode": 6}
        assert library.part_of(store, other[0], f"Library/{w[177]}/{w[178]}.srt") == (1, 6), "a folder's K4 number"
    finally:
        store._show_record = real
    store.close()
