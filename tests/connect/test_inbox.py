"""Connect's inbox (P2.1 row 2.1.4): the store's placement log → jobs in the ledger.

What a wrong answer would cost: Connect writes the user's Anki unattended, so a job made for something placed before
Connect was switched on would mine the user's history (✅ G1.1-2 forbids it); a back-fill registration that made a job
would mine the ~60 files already in hato's folder; a kill between reading and advancing that made a second job would
make every card twice; a pruned log replayed as fresh would mine history too. Real subtitles, synthetic titles, a
small mine line (2) so a handful of real files cross it.
"""
import pytest

from app.connect import inbox
from app.connect.ledger import Ledger
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


def _library(lang="ja", line=2):
    c.library(lang)
    with c.store(lang) as s:
        s.bookkeeping({"mine_line": line}, copy_carries=True)


def _consume(lang="ja"):
    with c.store(lang) as s, Ledger() as ledger:
        return inbox.consume(s, lang, ledger)


def _jobs(lang="ja", **kw):
    with Ledger() as ledger:
        return ledger.jobs(lang, **kw)


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_first_run_skips_everything_placed_before_the_watermark(lang):
    _library(lang)
    with c.store(lang) as s:
        s.register_reader("window-notice")          # another reader: the log is written from here on
        ids = s.ids("now")
        s.move([ids[-1]], "now")                    # entered the top 2 before Connect was on
        assert any(k == "entered_mine_line" for _i, k, _b in c.events(s))
    first = _consume(lang)
    assert first == {"queued": [], "dropped": [], "reconciled": False, "read": 0, "missed": []}
    assert _jobs(lang) == [], "nothing placed before Connect was switched on is mined"
    assert _consume(lang)["queued"] == []


def test_an_item_entering_the_top_20_is_queued_with_who_placed_it():
    _library()
    _consume()                                          # Connect on: the watermark
    with c.store() as s:
        moved = s.ids("now")[-1]
    from app.connect import library
    with c.store() as s:
        library.place(s, moved, "now", source="my-script")
    out = _consume()
    assert out["queued"] == [moved]
    job = _jobs()[0]
    assert (job["item_id"], job["state"], job["source"]) == (moved, "queued", "my-script")


def test_a_hato_drop_is_queued_as_hatos_and_a_backfill_never_is():
    _library()
    _consume()
    with c.store() as s:
        loud = s.register(c.drop("Example Show - 05.ja.srt"), c.record(c.drop("Example Show - 05.ja.srt"), "v5"))
        quiet = s.register(c.drop("Example Show - 04.ja.srt"), c.record(c.drop("Example Show - 04.ja.srt"), "v4"),
                           backfill=True)
    out = _consume()
    assert out["queued"] == [loud.added[0]] and quiet.added[0] not in out["queued"]
    assert [j["source"] for j in _jobs()] == ["hato"]


def test_an_item_that_leaves_the_top_20_before_mining_is_dropped():
    _library()
    _consume()
    from app.connect import library
    with c.store() as s:
        ids = s.ids("now")
        library.place(s, ids[-1], "now", source="user")      # enters (top 2), pushes ids[1] out
    _consume()
    with c.store() as s:
        library.place(s, ids[-1], "soon", source="user")     # leaves again before any mining
    out = _consume()
    assert ids[-1] in out["dropped"]
    assert [j["state"] for j in _jobs() if j["item_id"] == ids[-1]] == ["dropped"]


def test_a_started_job_is_never_dropped():
    _library()
    _consume()
    from app.connect import library
    with c.store() as s:
        item = s.ids("now")[-1]
        library.place(s, item, "now", source="user")
    _consume()
    with Ledger() as ledger:
        ledger.conn.execute("UPDATE jobs SET state = 'mining' WHERE item_id = ?", (item,))
    with c.store() as s:
        library.place(s, item, "soon", source="user")
    assert _consume()["dropped"] == [] and _jobs()[0]["state"] == "mining", "once mining has started, it finishes"


def test_a_kill_between_read_and_advance_re_reads_without_a_second_job(monkeypatch):
    _library()
    _consume()
    from app.connect import library
    with c.store() as s:
        item = s.ids("now")[-1]
        library.place(s, item, "now", source="user")
    from app import library_store

    def killed(*_a, **_k):
        raise KeyboardInterrupt("killed after the ledger's commit, before the reader moved")
    advance = library_store.Store.advance_reader
    monkeypatch.setattr(library_store.Store, "advance_reader", killed)
    with pytest.raises(KeyboardInterrupt):
        _consume()
    monkeypatch.setattr(library_store.Store, "advance_reader", advance)
    assert [j["item_id"] for j in _jobs()] == [item], "the job was committed"
    again = _consume()
    assert again["read"] > 0 and again["queued"] == []
    assert len(_jobs()) == 1, "re-read, one job"


def test_a_mined_item_is_not_queued_again():
    _library()
    _consume()
    from app.connect import library
    with c.store() as s:
        item = s.ids("now")[-1]
        s.receipt(item, "2026-10-05T12:00:00Z")
        library.place(s, item, "now", source="user")
    assert _consume()["queued"] == []


def test_a_gap_reconciles_drops_what_left_and_queues_nothing():
    _library()
    _consume()
    from app.connect import library
    with c.store() as s:
        ids = s.ids("now")
        library.place(s, ids[-1], "now", source="user")
    _consume()                                              # ids[-1] queued
    with c.store() as s:
        library.place(s, ids[-1], "goal", source="user")     # left …
        library.place(s, ids[1], "now", source="user")       # … and another entered
        with s._writing():                                  # the log pruned past Connect's watermark
            s.conn.execute("DELETE FROM placement_log")
    out = _consume()
    assert out["reconciled"] is True and out["queued"] == [], "never a mine of history"
    assert out["dropped"] == [ids[-1]]
    with c.store() as s:
        rows, gap = s.read_events("connect")
        assert not gap and rows == [], "the reader moved to the log's end"


def test_switching_connect_on_again_reads_nothing_placed_while_it_was_off():
    """Review P2.1 #3: every switch-on is a watermark (G1.1-2), not only the first."""
    _library()
    _consume()
    from app.connect import library
    with c.store() as s:
        library.place(s, s.ids("now")[-1], "now", source="user")     # while Connect is off
        library.switch_on(s)                                           # the preview's switch turned on again
    assert _consume() == {"queued": [], "dropped": [], "reconciled": False, "read": 0, "missed": []}


def test_a_gap_moves_the_reader_only_as_far_as_it_read(monkeypatch):
    """Review P2.1 #4: an item placed while a gap's reconcile reads is read by the next run, never passed."""
    _library()
    _consume()
    from app.connect import library
    with c.store() as s:
        s.bookkeeping({"reader_epoch:connect": -1})            # a rebuild's new epoch: a gap
        late = s.ids("now")[-1]
    real = library.mine_line

    def meanwhile(store):
        with c.store() as other:                             # another program, between the read and the advance
            library.place(other, late, "now", source="my-script")
        return real(store)
    monkeypatch.setattr(library, "mine_line", meanwhile)
    assert _consume()["reconciled"] is True
    monkeypatch.setattr(library, "mine_line", real)
    assert _consume()["queued"] == [late]


def test_connect_reads_every_language_and_again_before_it_exits(monkeypatch):
    """Review P2.1 #5: one Connect for both languages, and what was logged during its read is read before it leaves."""
    from tests import cli_helpers as h
    _library("ja")
    _library("zh")
    for lang in ("ja", "zh"):
        _consume(lang)
    from app.connect import inbox, library
    with c.store("zh") as s:
        zh_item = s.ids("now")[-1]
        library.place(s, zh_item, "now", source="my-script")
    with c.store("ja") as s:
        ja_item = s.ids("now")[-1]
    real, calls = inbox.consume, []

    def consume(store, language, ledger=None):
        calls.append(language)
        out = real(store, language, ledger)
        if len(calls) == 1:                                  # a Japanese drop lands during the first read
            with c.store("ja") as other:
                library.place(other, ja_item, "now", source="hato")
        return out
    monkeypatch.setattr(inbox, "consume", consume)
    code, line = h.call("connect", "--consume-only")
    assert code == 0 and line["rounds"] == 2, line
    assert line["languages"]["zh"]["queued"] == [zh_item] and line["languages"]["ja"]["queued"] == [ja_item]


def test_a_gap_keeps_the_top_20_episodes_without_cards_for_needs_you_and_mines_none():
    """✅ P2.1-3 (Sonic: the lean, plus Needs you): after a gap nothing is mined; the top-20 episodes with no cards and
    no job are kept in the ledger, from Connect's last read to now, for the start-up notice (2.x) and Needs you (3.0)."""
    _library()
    _consume()
    from app.connect import library
    with c.store() as s:
        line = library.mine_line(s)
        s.receipt(line[0], "2026-10-05T12:00:00Z")          # mined already: never "missed"
        with s._writing():
            s.conn.execute("DELETE FROM placement_log")
        s.bookkeeping({"reader_epoch:connect": -1})
    out = _consume()
    assert out["reconciled"] is True and out["queued"] == [] and out["missed"] == line[1:]
    assert _consume()["missed"] == [], "the next read is no gap"
    with Ledger() as ledger:
        gaps = ledger.gaps("ja")
    assert [g["items"] for g in gaps] == [line[1:]] and gaps[0]["since"] and gaps[0]["until"] >= gaps[0]["since"]
    assert _jobs() == []
