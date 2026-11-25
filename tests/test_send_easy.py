"""SEND-EASY (3.0.19; the lead's card, Sonic 2026-11-25): Send report is one easy "help us improve" button — it is
ready whenever there is something to send (a saved report, flagged sentences, swaps, the cards the learner didn't
want), and nothing has to be written. The cards the learner didn't want go too: `review_loop.for_report` reads them
from the one record of each — the review loop's own record (Suspend + the Ignore flag, read by the loop) and the
deleted-card look's rows in Connect's ledger (a deleted card answered *Known* or *Ignore*; *Parsing mistake* already
goes as a flagged sentence, *Bad card* as a swap) — into `connect/not_wanted.json`, scrubbed like every entry, a tick
each on What goes, each sent once in its state (Send report's own record, `report_send.json`).

What a wrong answer costs: a card the learner didn't want never reaching us (the signal Sonic asked for), a card's or
note's id or the learner's name in the zip, the same cards sent with every report, an unticked one sent anyway, a
record written by a read, or a learner with swaps waiting told there is nothing to send. Real lines from
tests/Test Resources (ja/library_episode.ass, ja/context_test.txt; zh/night_market.srt and its traditional lines),
the ledger and the loop's record real, the cards in the review loop's stand-in Anki.
"""
import io
import json
import zipfile

import pytest

from app import report, send_report
from app.connect import deleted, review_loop, swap_queue
from app.connect.ledger import Ledger
from app.services import flags
from tests import scrub_probe as probe_person
from tests.connect.test_kyou_lr_review_loop import DECK, LoopAnki, URL
from tests.test_swaps_report import CASES, _ask, _fresh_identity, pc, receiver  # noqa: F401  (fixtures)

# Each language's cards: (word, the sentence its card was made from) — real lines of the files above
RED = {"ja": ("図書", "図書カードはお持ちですか？"), "zh": ("夜市", "今天我们要去台北的夜市吃东西。")}
GONE = {"ja": [("危険", "きけん", "冒険は危険だが、価値がある。"), ("有名", "ゆうめい", "彼は冒険家として非常に有名です。"),
               ("図書館", "としょかん", "市立図書館"), ("借りる", "かりる", "すみません、この本を借りたいんですが。")],
        "zh": [("排隊", "páiduì", "每天都有很多人排隊。"), ("頻道", "píndào", "大家好，歡迎回到我的頻道。"),
               ("有名", "yǒumíng", "這家店的牛肉麵非常有名，"), ("我们", "wǒmen", "我们先点一碗牛肉面")]}
FIELDS = {"word", "sentence", "why", "by", "at"}
NOTE = 1_700_000_000_000
RED_CARD = 51


def _never(_word, _reading=""):
    return None


@pytest.fixture
def anki(pc, monkeypatch):
    """The review loop's stand-in Anki (cards in memory, nothing ever written), Connect on."""
    from app.path_utils import get_settings_path
    import os
    path = get_settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"connect_enabled": True}, f)
    return LoopAnki(monkeypatch)


def _sync(lang):
    from app import anki_sync, settings_manager
    result, _signal = anki_sync.sync_all(lang, URL, [DECK], [], settings_manager.load_settings(),
                                         include_suspended=False)
    assert not result.error, result.error
    return result


def _red(anki, lang, card=RED_CARD, made=True):
    """A card the learner flagged Suspend + Red (Ignore) on their phone, read by the known-words sync; `made`: Connect
    made it (its outcome in the ledger holds the sentence it was made from)."""
    word, line = RED[lang]
    _sync(lang)                                                    # the first read: nothing moved yet
    anki.add(card, word, suspended=True, flag=1)
    if made:
        with Ledger() as ledger:
            ledger.conn.execute("INSERT INTO outcomes (job_id, word, reading, sentence, outcome, note_id, attempt) "
                                "VALUES (1, ?, '', ?, 'made', ?, 1)", (word, line, card + 1000))
            ledger.conn.commit()
    return _sync(lang)


def _gone(lang, answers):
    """Connect made GONE's cards, the learner deleted them, the look saw them gone, and each was answered (`answers`:
    one deleted.* answer per card, None = not answered) -> the note ids."""
    notes = [NOTE + i for i in range(len(answers))]
    with Ledger() as ledger:
        job = ledger.queue(lang, 900 + len(answers), "test", None)
        with ledger.transaction():
            ledger.record_outcomes(job, 1, [{"word": w, "reading": r, "sentence": s, "line_start": 12.5 + i,
                                             "line_end": 14.0 + i, "outcome": "made", "note_id": notes[i]}
                                            for i, (w, r, s) in enumerate(GONE[lang][:len(answers)])])
        deleted.seen(lang, notes, None, state_of=_never, ledger=ledger, likely_of=lambda *_a: {})
        for note, why in zip(notes, answers):
            if why is not None:
                got = deleted.answer(lang, [note], why, ledger=ledger, state_of=_never, open_store=None)
                assert got["done"], got
    return notes


def _cards(path):
    with zipfile.ZipFile(path) as z:
        if report.NOT_WANTED not in z.namelist():
            return None
        return json.loads(z.read(report.NOT_WANTED).decode("utf-8"))


# --- the reader: the loop's one record of each, read only ------------------------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_each_card_not_wanted_goes_with_its_word_sentence_and_why_and_what_goes_already_is_not_doubled(anki, lang):
    # why: Sonic's ask is "the cards they swap / don't want"; Parsing mistake already goes as a flagged sentence and
    # Bad card as a swap, so only Known and Ignore are new — and an unanswered card has no reason recorded
    _red(anki, lang)
    notes = _gone(lang, [deleted.IGNORE, deleted.KNOWN, deleted.PARSING, None])
    record = open(review_loop.record_path(lang), "rb").read()

    got = review_loop.for_report(lang)

    assert open(review_loop.record_path(lang), "rb").read() == record          # read only: the record untouched
    by_id = {rid: (state, line) for rid, state, line in got}
    assert set(by_id) == {f"r:{RED_CARD}", f"d:{notes[0]}", f"d:{notes[1]}"}
    assert all(set(line) == FIELDS for _s, line in by_id.values())           # never a card's or note's id
    state, red = by_id[f"r:{RED_CARD}"]
    assert (state, red["word"], red["sentence"], red["why"], red["by"]) == ("ignore", *RED[lang], "ignore", "flag")
    state, ignored = by_id[f"d:{notes[0]}"]
    assert (state, ignored["word"], ignored["sentence"], ignored["why"], ignored["by"]) == (
        "ignore", GONE[lang][0][0], GONE[lang][0][2], "ignore", "deleted")
    state, known = by_id[f"d:{notes[1]}"]
    assert (state, known["word"], known["why"]) == ("known", GONE[lang][1][0], "known")
    assert all(line["at"] for _s, line in by_id.values())
    assert [line["at"] for _r, _s, line in got] == sorted((line["at"] for _r, _s, line in got), reverse=True)
    raw = json.dumps([line for _r, _s, line in got], ensure_ascii=False)
    assert str(NOTE) not in raw and str(RED_CARD + 1000) not in raw


def test_a_red_card_surasura_didnt_make_has_no_sentence_and_an_undone_sync_takes_it_out(anki):
    # why: the learner's own card has no record of its sentence on this PC (Send report never reads Anki); a move the
    # learner took back with the toast's Undo is no card they didn't want
    result = _red(anki, "ja", made=False)
    ((rid, _s, line),) = review_loop.for_report("ja")
    assert (rid, line["word"], line["sentence"]) == (f"r:{RED_CARD}", RED["ja"][0], None)
    review_loop.undo("ja", result.loop["sync"])
    assert review_loop.for_report("ja") == []


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_card_sent_in_its_state_is_left_out_until_its_answer_changes(pc, lang):
    (note,) = _gone(lang, [deleted.IGNORE])
    rid = f"d:{note}"
    assert review_loop.for_report(lang, sent={rid: "ignore"}) == []
    with Ledger() as ledger:                                       # undone, then answered Known: it goes again
        deleted.undo(lang, [note], ledger=ledger)
        deleted.answer(lang, [note], deleted.KNOWN, ledger=ledger, state_of=_never, open_store=None)
    assert [(r, s) for r, s, _ in review_loop.for_report(lang, sent={rid: "ignore"})] == [(rid, "known")]


def test_the_newest_cards_up_to_the_flagged_sentences_cap(pc):
    _gone("zh", [deleted.IGNORE] * 4)
    got = review_loop.for_report("zh", newest=2)
    assert len(got) == 2 and review_loop.for_report.__defaults__[-1] == flags.MAX_LINES


def test_no_record_no_ledger_no_cards_and_an_unreadable_record_raises(pc):
    assert review_loop.for_report("ja") == [] and review_loop.for_report("zh") == []
    import os
    os.makedirs(os.path.dirname(review_loop.record_path("ja")), exist_ok=True)
    with open(review_loop.record_path("ja"), "w", encoding="utf-8") as f:
        f.write("{not json")
    with pytest.raises(review_loop.Unreadable):
        review_loop.for_report("ja")


def test_a_ledger_that_cant_be_read_leaves_the_deleted_cards_out_and_the_red_ones_without_sentences(anki, monkeypatch):
    _red(anki, "zh")
    _gone("zh", [deleted.IGNORE])

    def busy(language, notes=()):
        import sqlite3
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(deleted, "report_rows", busy)
    ((rid, _s, line),) = review_loop.for_report("zh")
    assert (rid, line["sentence"]) == (f"r:{RED_CARD}", None)


# --- the zip --------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_cards_go_in_connect_not_wanted_json_scrubbed_with_nothing_written_and_what_goes_shows_them(pc, lang,
                                                                                                    tmp_path):
    # why: "nothing has to be written" — the cards alone make a report; a sentence naming the learner is scrubbed
    (note,) = _gone(lang, [deleted.IGNORE])
    with Ledger() as ledger:
        ledger.conn.execute("UPDATE deleted SET sentence = ? WHERE note_id = ?",
                            (f"{GONE[lang][0][2]} {probe_person.EMAIL}", note))
        ledger.conn.commit()
    made = report.make_send_zip(str(tmp_path / "send.zip"), lang)
    assert made.zipped == {} and made.flags == {} and made.swaps == {}
    got = _cards(made.path)
    assert got["format"] == 1 and got["language"] == lang
    (line,) = got["cards"]
    assert set(line) == FIELDS and line["sentence"] == f"{GONE[lang][0][2]} <email>"
    assert probe_person.EMAIL not in json.dumps(got, ensure_ascii=False)
    (shown,) = made.not_wanted_lines
    assert {k: v for k, v in shown.items() if k not in ("id", "changed")} == line
    assert made.not_wanted == {f"d:{note}": "ignore"} == {shown["id"]: shown["changed"]}
    assert any(x.startswith("never taken") and report.NOT_WANTED in x for x in made.left_out)
    from app import scrub
    assert scrub.leaks(made.path) == []


def test_swaps_alone_make_a_report_now_and_make_a_zip_still_wants_a_saved_one(pc, tmp_path):
    # why: SWAPS-REPORT's "swaps never make a report alone" is overruled (Sonic 2026-11-25); *Make a zip instead*
    # zips the saved reports, as before
    _ask("ja", 7100, old=CASES["ja"][1])
    made = report.make_send_zip(str(tmp_path / "send.zip"), "ja")
    assert made.zipped == {} and len(made.swap_lines) == 1
    with pytest.raises(ValueError):
        report.make_zip(str(tmp_path / "out"), "ja")


def test_nothing_at_all_is_still_nothing_to_send(pc, tmp_path):
    with pytest.raises(ValueError):
        report.make_send_zip(str(tmp_path / "send.zip"), "zh")
    report.save("リストが空のまま", "")
    plain = report.make_send_zip(str(tmp_path / "a.zip"), "zh")
    assert _cards(plain.path) is None and plain.not_wanted == {} and plain.not_wanted_lines == []
    assert not any(report.NOT_WANTED in x for x in plain.left_out)


def test_an_unreadable_record_is_said_in_left_out_never_a_reason_to_fail(pc, tmp_path):
    import os
    os.makedirs(os.path.dirname(review_loop.record_path("ja")), exist_ok=True)
    with open(review_loop.record_path("ja"), "w", encoding="utf-8") as f:
        f.write("[]")                                                         # (a list, not the record)
    report.save("壊れた記録", "")
    made = report.make_send_zip(str(tmp_path / "send.zip"), "ja")
    assert _cards(made.path) is None
    assert any(x.startswith(f"{report.NOT_WANTED}: couldn't be read") for x in made.left_out)


def test_rewritten_with_fewer_cards_only_that_entry_changes_and_none_leaves_it_out(pc, tmp_path):
    _gone("zh", [deleted.IGNORE, deleted.KNOWN])
    report.save("换的句子不对", "")
    made = report.make_send_zip(str(tmp_path / "send.zip"), "zh")
    strip = [{k: v for k, v in x.items() if k not in ("id", "changed")} for x in made.not_wanted_lines]
    report.rewrite_flagged(made.path, "zh", [], made.left_out)               # cards None: as they were
    assert len(_cards(made.path)["cards"]) == 2
    report.rewrite_flagged(made.path, "zh", [], made.left_out, not_wanted=strip[1:])
    assert [x["why"] for x in _cards(made.path)["cards"]] == [strip[1]["why"]]
    report.rewrite_flagged(made.path, "zh", [], made.left_out, not_wanted=[])
    assert _cards(made.path) is None


# --- Send report: the ticks, the receiver's yes ---------------------------------------------------------------------- #
def _sent(body, name, key):
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        if name not in z.namelist():
            return []
        return [x["why" if key == "cards" else "state"] for x in json.loads(z.read(name))[key]]


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_cards_alone_are_sent_once_and_an_unticked_one_stays_for_the_next_report(pc, receiver, lang):
    a, b = _gone(lang, [deleted.IGNORE, deleted.KNOWN])
    ob = send_report.build(lang)
    assert ob.zipped == {} and {x["id"] for x in ob.not_wanted_lines} == {f"d:{a}", f"d:{b}"}
    assert send_report.send(nonce=ob.nonce, keep=[f"d:{a}"]).outcome == send_report.SENT
    assert _sent(receiver.got[0]["body"], report.NOT_WANTED, "cards") == ["ignore"]
    assert send_report.not_wanted_sent(lang) == {f"d:{a}": "ignore"}
    again = send_report.build(lang)
    assert [x["id"] for x in again.not_wanted_lines] == [f"d:{b}"]           # the sent one is gone, the other stays


def test_swaps_alone_are_sent_once_with_nothing_written(pc, receiver):
    entry, _ = _ask("zh", 8400, old=CASES["zh"][1])
    ob = send_report.build("zh")
    assert send_report.send(nonce=ob.nonce, keep=[f"q:{entry['id']}"]).outcome == send_report.SENT
    assert _sent(receiver.got[0]["body"], report.SWAPS, "swaps") == ["waiting"]
    with pytest.raises(ValueError):                                          # sent: nothing is left to send
        send_report.build("zh")


def test_only_a_swap_ticked_beside_unticked_flags_goes_and_nothing_ticked_is_nothing_to_send(pc, receiver):
    entry, _ = _ask("zh", 8500, old=CASES["zh"][1])
    flagged = flags.add("zh", CASES["zh"][1], "夜市", "journey", key="e2:4.1", reasons=["too_long"])
    ob = send_report.build("zh")
    with pytest.raises(ValueError):
        send_report.send(nonce=ob.nonce, keep=[])
    assert receiver.got == []
    assert send_report.send(nonce=ob.nonce, keep=[f"q:{entry['id']}"]).outcome == send_report.SENT
    body = receiver.got[0]["body"]
    assert _sent(body, report.SWAPS, "swaps") == ["waiting"] and _sent(body, report.FLAGGED, "lines") == []
    assert [x["id"] for x in flags.read("zh")] == [flagged["id"]]            # the unticked flag: still flagged


def test_a_failed_send_remembers_no_card(pc, receiver):
    _gone("ja", [deleted.IGNORE])
    receiver.answer = (503, {"error": "paused"})
    send_report.build("ja")
    assert send_report.send().outcome == send_report.PAUSED
    assert send_report.not_wanted_sent("ja") == {} and len(send_report.waiting().not_wanted_lines) == 1


def test_a_card_whose_answer_changed_since_the_zip_gets_a_new_nonce(pc):
    (note,) = _gone("zh", [deleted.IGNORE])
    first = send_report.build("zh")
    assert send_report.build("zh").nonce == first.nonce                       # nothing changed: the same nonce
    with Ledger() as ledger:
        deleted.undo("zh", [note], ledger=ledger)
        deleted.answer("zh", [note], deleted.KNOWN, ledger=ledger, state_of=_never, open_store=None)
    again = send_report.build("zh")
    assert again.nonce != first.nonce and again.not_wanted_lines[0]["why"] == "known"


def test_the_queue_is_never_written_by_a_report(pc):
    # why: the swap queue and the loop's record are the one record each — Send report keeps its own
    entry, _ = _ask("ja", 8600, old=CASES["ja"][1])
    before = open(swap_queue.path("ja"), "rb").read()
    report.save("記録", "")
    send_report.build("ja")
    assert open(swap_queue.path("ja"), "rb").read() == before
