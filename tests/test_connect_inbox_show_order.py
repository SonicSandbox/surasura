"""Connect mines a show from its first episode, not from the first one that crossed into the top 20 after it was
switched on (Michi-EO, 3.0.16).

Why these matter: Connect makes a job only of an item that ENTERS the top 20 after its watermark (`inbox.consume`, ✅
G1.1-2): what was already in the line at the switch-on is never logged. Setup places the shows (its sort screen) before
its page 5 turns Connect on, so a show's first episodes sit in the line unlogged; when the learner then finishes or
moves something above them, the show's NEXT episodes cross the line and get jobs — and the show is mined from episode 8,
episodes 1–7 never (a tester's 3.0.15 report). Every test runs for Japanese and Chinese under the per-test
SURASURA_TEST_ROOT, with real words from tests/Test Resources/ (the episode-order tests' own registration).
"""

import pytest

from app.connect import inbox
from app.connect.ledger import Ledger
from tests.test_library_store_episode_order import _episode
from tests.test_library_store_support import LANGUAGES, migrated, names


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
