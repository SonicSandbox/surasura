"""SWAPS-REPORT (Sonic's yes, OPEN-FOR-SONIC § 92): Send report carries the learner's swaps the way it carries the
flagged sentences — `swap.for_report` reads them from the one record (the swap queue's entry; Connect's ledger only for
the two sentences the entry lacks, and for the asks with no entry: the journey's ⇄, *Bad card*), `report.plan` puts
the ones not sent yet in `connect/swaps.json`, scrubbed like every entry, `send_report` ticks them on What goes and
remembers the ones the receiver took.

What a wrong answer costs: a swap's record written over or doubled (the queue is the one record: nothing here writes
it); a card's or note's id, a path or the learner's name in the zip; the same swaps sent with every report; an unticked
swap sent anyway; swaps alone lighting Send report (a swap is a study move, not a report). Real lines from
tests/Test Resources (ja/library_episode.ass, zh/night_market.srt), the ledger real.
"""
import datetime
import io
import json
import sqlite3
import zipfile

import pytest

from app import report, scrub, send_report
from app.connect import swap, swap_queue
from app.connect.ledger import Ledger
from app.services import flags
from tests import scrub_probe as probe_person
from tests.test_send_report import Receiver

# The word, the old card's line, the line its new card was made from (real lines of the files above)
CASES = {"ja": ("借りる", "すみません、この本を借りたいんですが。", "ペンを借りてもいいですか"),
         "zh": ("我们", "今天我们要去台北的夜市吃东西。", "我们先点一碗牛肉面")}
FIELDS = {"word", "old", "new", "asked", "state", "why", "at", "by"}


@pytest.fixture(autouse=True)
def _fresh_identity():
    scrub.reset()
    yield
    scrub.reset()


@pytest.fixture
def pc(tmp_path, monkeypatch):
    """The probe person's PC, its clocks stepping a minute at a time (the queue's local time, the ledger's UTC one),
    so newest-first is decided by when each swap was asked."""
    person = probe_person.make(tmp_path, monkeypatch)
    tick = {"n": 0}
    start = datetime.datetime(2026, 11, 24, 9, 0, 0)

    def local():
        tick["n"] += 1
        return (start + datetime.timedelta(minutes=tick["n"])).isoformat(timespec="seconds")

    def utc():
        tick["n"] += 1
        when = (start + datetime.timedelta(minutes=tick["n"])).astimezone().astimezone(datetime.timezone.utc)
        return when.strftime("%Y-%m-%dT%H:%M:%SZ")
    monkeypatch.setattr(swap_queue, "_now", local)
    monkeypatch.setattr(swap, "_now", utc)
    return person


def _ask(lang, card, line=None, old=None, ref=True, by=swap.BY_SWAP, state=None, why=None):
    """One swap as the app records it: the queue's entry (the review loop's green flag) and Connect's ledger row for
    it (`make_card`, then the job's outcome: the new card's line, the old card's sentence it avoided)."""
    word = CASES[lang][0]
    entry = swap_queue.add(lang, word, card, card + 1, "sync-1") if ref else None
    with Ledger() as ledger:
        got = swap.make_card(lang, word, old_note=card + 1, old_card=card, by=by,
                             ref=entry["id"] if entry else None, ledger=ledger, wake=False,
                             state_of=lambda w, r: None)
        values = {}
        if old is not None:
            values["avoid"] = json.dumps([old], ensure_ascii=False)
        if line is not None:
            values["line"] = line
        if state is not None:
            values.update(state=state, why=why)
        if values:
            swap._set(ledger, got["id"], **values)
    return entry, got["id"]


def _swaps(path):
    with zipfile.ZipFile(path) as z:
        if report.SWAPS not in z.namelist():
            return None
        return json.loads(z.read(report.SWAPS).decode("utf-8"))


# --- the reader: one record, read only ------------------------------------------------------------------------------ #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_each_swap_goes_with_its_word_both_sentences_when_and_what_came_of_it_newest_first(pc, lang):
    word, old, new = CASES[lang]
    made, _ = _ask(lang, 1000, line=new, old=old)
    swap_queue.made(lang, made["id"], 5001)
    dropped, _ = _ask(lang, 1010, old=old)
    swap_queue.drop(lang, dropped["id"], "known")
    undone, _ = _ask(lang, 1020, line=new, old=old)
    swap_queue.made(lang, undone["id"], 5002)
    swap_queue.undone(lang, undone["id"])
    waiting = swap_queue.add(lang, word, 1030, 1031, "sync-2")             # a green flag Connect hasn't looked at
    before = open(swap_queue.path(lang), "rb").read()

    got = swap.for_report(lang)

    assert open(swap_queue.path(lang), "rb").read() == before                # read only: the one record untouched
    assert [rid for rid, _, _ in got] == [f"q:{e['id']}" for e in (waiting, undone, dropped, made)]
    assert [state for _, state, _ in got] == ["waiting", "undone", "dropped", "made"]
    lines = [line for _, _, line in got]
    assert all(set(line) == FIELDS for line in lines)                         # never a card's or note's id
    w, u, d, m = lines
    assert (m["word"], m["old"], m["new"], m["state"], m["why"], m["by"]) == (word, old, new, "made", None, "swap")
    assert m["asked"] == made["queued"] and m["at"] > m["asked"]              # when it was asked, when it was made
    assert (u["old"], u["new"], u["state"], u["at"]) == (old, new, "undone", swap_queue.load(lang)[2]["undone"])
    assert (d["old"], d["new"], d["state"], d["why"]) == (old, None, "dropped", "known")
    assert (w["word"], w["old"], w["new"], w["state"], w["at"]) == (word, None, None, "waiting", None)
    raw = json.dumps(lines, ensure_ascii=False)
    assert "1000" not in raw and "5001" not in raw and "sync-1" not in raw


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_journey_swap_and_a_bad_card_are_read_from_the_ledger_and_add_now_is_no_swap(pc, lang):
    """J-SWAP: the journey's ⇄ and *Bad card* ask with no queue entry — the ledger's row is their one record. *Add
    now* has no old card: no swap."""
    word, old, new = CASES[lang]
    _, journey = _ask(lang, 2000, line=new, old=old, ref=False, by=swap.BY_JOURNEY, state=swap.MADE)
    _ask(lang, 2010, old=old, ref=False, by=swap.BY_BAD_CARD, state=swap.WAITS, why=swap.NO_LINE)
    _ask(lang, 2020, line=new, ref=False, by=swap.BY_ADD_NOW, state=swap.MADE)

    got = swap.for_report(lang)

    assert [(rid[:2], state, line["by"]) for rid, state, line in got] == [("l:", "waiting", "bad card"),
                                                                          ("l:", "made", "journey")]
    j = got[1][2]
    assert (j["old"], j["new"], j["why"]) == (old, new, None) and j["asked"] <= j["at"]
    assert got[0][2]["why"] is None                                            # waiting: no why ("no other line" is Connect's)
    assert got[1][0] == f"l:{journey}"


def test_the_old_sentence_is_connects_record_of_the_note_else_the_avoided_line_markup_and_furigana_out(pc):
    word, old, new = CASES["ja"]
    a, _ = _ask("ja", 3000, line=new, old="<b>関係ない</b>")
    with Ledger() as ledger:                                                  # Connect made the old card from `old`
        ledger.conn.execute("INSERT INTO outcomes (job_id, word, reading, sentence, outcome, note_id, attempt) "
                            "VALUES (1, ?, '', ?, 'made', ?, 1)", (word, old, 3001))
        ledger.conn.commit()
    b, _ = _ask("ja", 3010, line=new, old="すみません、この<b>本</b>[ほん]を\n借りたいんですが。")
    got = {line["asked"]: line for _, _, line in swap.for_report("ja")}
    assert got[a["queued"]]["old"] == old
    assert got[b["queued"]]["old"] == "すみません、この本を 借りたいんですが。"


def test_a_swap_sent_in_its_state_is_left_out_until_it_changes(pc):
    word, old, new = CASES["zh"]
    entry, _ = _ask("zh", 4000, line=new, old=old)
    rid = f"q:{entry['id']}"
    assert [r for r, _, _ in swap.for_report("zh", sent={rid: "waiting"})] == []
    swap_queue.made("zh", entry["id"], 4100)                                  # made since it went: it goes again
    assert [(r, s) for r, s, _ in swap.for_report("zh", sent={rid: "waiting"})] == [(rid, "made")]


def test_the_newest_swaps_up_to_the_flagged_sentences_cap(pc, monkeypatch):
    for card in range(5000, 5050, 10):
        _ask("ja", card, old=CASES["ja"][1])
    asked = [e["queued"] for e in swap_queue.load("ja")]
    got = swap.for_report("ja", newest=3)
    assert [line["asked"] for _, _, line in got] == sorted(asked, reverse=True)[:3]
    assert swap.for_report.__defaults__[-1] == flags.MAX_LINES                # the same cap as the flagged lines


def test_no_queue_no_ledger_no_swaps(pc):
    assert swap.for_report("ja") == [] and swap.for_report("zh") == []


def test_a_queue_that_cant_be_read_raises_and_a_ledger_that_cant_leaves_only_the_sentences_out(pc, monkeypatch):
    word, old, new = CASES["ja"]
    entry, _ = _ask("ja", 6000, line=new, old=old)

    def busy(language):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(swap, "_report_rows", busy)
    ((rid, state, line),) = swap.for_report("ja")
    assert (line["word"], line["old"], line["new"], state) == (word, None, None, "waiting")
    with open(swap_queue.path("ja"), "w", encoding="utf-8") as f:
        f.write("{not json")
    with pytest.raises(swap_queue.Unreadable):
        swap.for_report("ja")


# --- the zip --------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_swaps_go_in_connect_swaps_json_scrubbed_beside_a_report_and_what_goes_shows_them_as_zipped(pc, lang,
                                                                                                          tmp_path):
    word, old, new = CASES[lang]
    entry, _ = _ask(lang, 7000, line=new, old=f"{old} {probe_person.EMAIL}")   # a sentence naming them: scrubbed
    report.save("入れ替えた文がまた同じだった", "")
    made = report.make_send_zip(str(tmp_path / "send.zip"), lang)
    got = _swaps(made.path)
    assert got["format"] == 1 and got["language"] == lang
    (line,) = got["swaps"]
    assert set(line) == FIELDS and (line["word"], line["new"]) == (word, new)
    assert line["old"] == f"{old} <email>" and probe_person.EMAIL not in json.dumps(got, ensure_ascii=False)
    (shown,) = made.swap_lines
    assert {k: v for k, v in shown.items() if k not in ("id", "changed")} == line
    assert made.swaps == {f"q:{entry['id']}": "waiting"} == {shown["id"]: shown["changed"]}
    assert scrub.leaks(made.path) == []


def test_swaps_alone_make_no_report_and_no_swaps_no_entry(pc, tmp_path):
    _ask("ja", 7100, old=CASES["ja"][1])
    with pytest.raises(ValueError):
        report.make_send_zip(str(tmp_path / "send.zip"), "ja")
    with pytest.raises(ValueError):
        report.make_zip(str(tmp_path / "out"), "ja")
    report.save("リストが空のまま", "")
    made = report.make_send_zip(str(tmp_path / "zh.zip"), "zh")                # (the swap is Japanese's)
    assert _swaps(made.path) is None and made.swaps == {} and made.swap_lines == []
    assert not any(x.startswith(report.SWAPS) for x in made.left_out)


def test_a_queue_that_cant_be_read_is_said_in_left_out_never_a_reason_to_fail(pc, tmp_path):
    import os
    os.makedirs(os.path.dirname(swap_queue.path("ja")), exist_ok=True)
    with open(swap_queue.path("ja"), "w", encoding="utf-8") as f:
        f.write("[]")                                                         # (a list, not the queue)
    report.save("壊れた記録", "")
    made = report.make_send_zip(str(tmp_path / "send.zip"), "ja")
    assert _swaps(made.path) is None
    assert any(x.startswith(f"{report.SWAPS}: couldn't be read") for x in made.left_out)


def test_rewritten_with_fewer_swaps_only_that_entry_changes_and_none_leaves_it_out(pc, tmp_path):
    a, _ = _ask("zh", 7200, line=CASES["zh"][2], old=CASES["zh"][1])
    b, _ = _ask("zh", 7210, old=CASES["zh"][1])
    report.save("换的句子不对", "")
    made = report.make_send_zip(str(tmp_path / "send.zip"), "zh")
    strip = [{k: v for k, v in x.items() if k not in ("id", "changed")} for x in made.swap_lines]
    report.rewrite_flagged(made.path, "zh", [], made.left_out)               # swaps None: as they were
    assert len(_swaps(made.path)["swaps"]) == 2
    report.rewrite_flagged(made.path, "zh", [], made.left_out, swaps=strip[1:])
    assert [x["asked"] for x in _swaps(made.path)["swaps"]] == [a["queued"]]
    with zipfile.ZipFile(made.path) as z:
        assert report.SWAPS in z.read("MANIFEST.txt").decode("utf-8")
    report.rewrite_flagged(made.path, "zh", [], made.left_out, swaps=[])
    assert _swaps(made.path) is None


# --- Send report: the ticks, the receiver's yes ---------------------------------------------------------------------- #
@pytest.fixture
def receiver(monkeypatch):
    from app import telemetry
    r = Receiver()
    monkeypatch.setattr(telemetry, "report_receiver", lambda env="production": r.url)
    yield r
    r.close()


def _sent_words(body):
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        if report.SWAPS not in z.namelist():
            return []
        return [x["state"] for x in json.loads(z.read(report.SWAPS))["swaps"]]


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_ticked_swap_goes_once_an_unticked_one_stays_for_the_next_report(pc, receiver, lang):
    a, _ = _ask(lang, 8000, line=CASES[lang][2], old=CASES[lang][1])
    swap_queue.made(lang, a["id"], 8100)
    b, _ = _ask(lang, 8010, old=CASES[lang][1])
    report.save("入れ替えの記録", "")
    ob = send_report.build(lang)
    assert [x["state"] for x in ob.swap_lines] == ["waiting", "made"]
    assert send_report.send(nonce=ob.nonce, keep=[f"q:{a['id']}"]).outcome == send_report.SENT
    assert _sent_words(receiver.got[0]["body"]) == ["made"]
    assert send_report.swaps_sent(lang) == {f"q:{a['id']}": "made"}
    report.save("もう一つ", "")
    again = send_report.build(lang)
    assert [x["id"] for x in again.swap_lines] == [f"q:{b['id']}"]          # the sent one is gone, the other stays
    swap_queue.undone(lang, a["id"])                                          # changed since: it comes back
    assert {x["id"]: x["changed"] for x in send_report.build(lang).swap_lines} == {f"q:{b['id']}": "waiting",
                                                                                  f"q:{a['id']}": "undone"}


def test_a_failed_send_remembers_no_swap(pc, receiver):
    a, _ = _ask("ja", 8200, old=CASES["ja"][1])
    report.save("送れなかった", "")
    receiver.answer = (503, {"error": "paused"})
    send_report.build("ja")
    assert send_report.send().outcome == send_report.PAUSED
    assert send_report.swaps_sent("ja") == {} and len(send_report.waiting().swap_lines) == 1


def test_refit_writes_the_swaps_ticks_and_the_same_ticks_change_nothing(pc):
    a, _ = _ask("zh", 8300, old=CASES["zh"][1])
    b, _ = _ask("zh", 8310, line=CASES["zh"][2], old=CASES["zh"][1])
    report.save("换句子", "")
    ob = send_report.build("zh")
    both = [f"q:{a['id']}", f"q:{b['id']}"]
    same = send_report.refit(both, ob.nonce)
    assert same.nonce == ob.nonce and same.sha256 == ob.sha256
    one = send_report.refit(both[:1], ob.nonce)
    assert one.nonce != ob.nonce and set(one.swaps) == {both[0]} and len(one.swap_lines) == 2   # all still shown
    with open(one.path, "rb") as f:
        assert _sent_words(f.read()) == ["waiting"]
    none = send_report.refit([], one.nonce)                                   # a saved report still goes
    with open(none.path, "rb") as f:
        assert _sent_words(f.read()) == [] and none.swaps == {}


def test_swaps_ticked_beside_flags_all_unticked_and_no_report_is_nothing_to_send(pc, receiver):
    _ask("zh", 8400, old=CASES["zh"][1])
    flagged = flags.add("zh", CASES["zh"][1], "夜市", "journey", key="e2:4.1", reasons=["too_long"])
    ob = send_report.build("zh")
    assert ob.zipped == {} and len(ob.swap_lines) == 1 and set(ob.flags) == {flagged["id"]}
    with pytest.raises(ValueError):
        send_report.send(keep=[ob.swap_lines[0]["id"]])
    assert receiver.got == [] and send_report.swaps_sent("zh") == {}
