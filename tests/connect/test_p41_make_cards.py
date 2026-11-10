"""P4.1 WF (IK D-1 lean (a); adversary S3, S4, S5; P2.1-3): *Make their cards* on a *Needs you* gap —
`actions.make_cards(language, gap_id)`, the window's short ledger write beside *Mine anyway*: each of the gap's episodes
with no open job and never mined queued as Connect's ordinary job (kind `mine`, by `user`, stamped with the library's
identity), never an ask; the gap marked noticed; how many were queued.

What a wrong answer would cost: deleted cards made again in bulk (an ask's job re-makes every word whose note is gone,
N15); an episode Connect mined since the gap mined twice; a job with no library identity, which the runner drops and
names as a new gap — the entry coming straight back; or a Chinese gap's episodes queued in Japanese.

A real store from the suite's files and a real ledger under the test's root (no Connect run).
"""
from app.connect import actions, library
from app.connect.ledger import ASKED, DONE, Ledger
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


def _gap(items, language="ja"):
    with Ledger() as ledger, ledger.transaction():
        return ledger.add_gap(language, items)


def test_make_their_cards_queues_the_gaps_episodes_as_connects_ordinary_jobs_never_an_ask():
    c.library()
    with c.store() as s:
        a, b, d, e = s.ids("now")[:4]
        sid = library.store_id(s)
    assert sid
    with Ledger() as ledger, ledger.transaction():
        done = ledger.queue("ja", b, "user", None, store_id=sid)
        ledger.set_state(done, DONE)                        # Connect mined it since the gap
        ledger.queue("ja", d, "user", None, store_id=sid)   # queued already (a move into the top 20)
    gap = _gap([a, b, d, e, a])
    assert actions.make_cards("ja", gap) == 2
    with Ledger() as ledger:
        jobs = {j["item_id"]: j for j in ledger.jobs("ja")}
        assert len(ledger.jobs("ja")) == 4, "one job each: none for the mined one, the queued one kept"
        for item in (a, e):
            job = jobs[item]
            assert (job["kind"], job["source"], job["state"], job["store_id"]) == ("mine", "user", "queued", sid)
            assert job["kind"] != ASKED and not job.get("asked_at"), "never an ask"
        assert ledger.gaps("ja", unnoticed=True) == [] and ledger.gaps("ja")[0]["noticed"] == 1
    with c.store() as s:                                    # an ordinary job makes no word Connect ever made (N15)
        assert library.made_words_for(s, jobs[a]) == library.made_words_all(s)
    assert actions.make_cards("ja", gap) == 0, "pressed again: nothing left to queue"


def test_make_their_cards_writes_nothing_for_another_languages_gap_no_gap_no_ledger_or_no_library(tmp_path):
    c.library()
    gap = _gap([1, 2])
    zh_gap = _gap([1, 2], language="zh")
    assert actions.make_cards("zh", gap) is False, "a Japanese gap is never made in Chinese"
    # P4.1 L2 mutants (W04): even with a library identity in hand, another language's gap is no gap here
    assert actions.make_cards("zh", gap, store_id="zh-library") is False
    assert actions.make_cards("ja", gap + zh_gap + 10) is False
    assert actions.make_cards("zh", zh_gap) is False, "no Chinese library: its identity can't be read"
    assert actions.make_cards("ja", gap, path=str(tmp_path / "no-ledger.sqlite")) is False
    assert not (tmp_path / "no-ledger.sqlite").exists(), "the window never makes Connect's ledger"
    with Ledger() as ledger:
        assert ledger.jobs() == [] and len(ledger.gaps("ja", unnoticed=True)) == 1
