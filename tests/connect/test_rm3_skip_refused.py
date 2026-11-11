"""Michi-RM3 (3.0.3; Mattias's reports on 3.0.1 / 3.0.2): two words Anki refuses every run, so *Try again* never helps.

The cause, proven on Anki's DevTest profile: AnkiConnect's `addNotes` answers *cannot create note for unknown reason*
when Anki's own fields check returns a cloze state — on a note type that isn't a cloze one (Lapis), a field holding
cloze marks (`{{c1::…}}`). Anki Miner puts the word's dictionary text in the card, and some dictionaries' grammar
entries carry such marks, so that word's card is refused every time, in every part. Surasura can't change what Anki
Miner writes; what it can do (Sonic: nothing silently refused, every press reacts, never asked forever):

- the part's line names the words and says why in plain words (the cloze marks), its own kind `mine-refused`, with
  *Skip this word* beside *Try again*;
- *Skip this word*: those words are left out (outcome `skipped`), the part goes on to fill and order the cards it did
  make, and ends done — no *Try again* left;
- a word you skipped is never sent again, in any part, for that Anki Miner (a new Anki Miner asks once more, as a word
  with no definition is).

What a wrong answer would cost: twenty identical failures a part, a part that never finishes, a press that does
nothing, or a word skipped in one part sent again in the next.

Against `FakeSteps` (Anki refuses `refuse_words`' notes, its answer AnkiConnect's real words) and a real ledger read
by the real status record and feed; real Japanese words. Never a live Anki, no sleeps.
"""
from app.connect import actions, feed, runner, status
from app.connect.ledger import Ledger, _now
from tests.connect.fake_steps import REFUSED_SAID, FakeSteps

WORDS = [("上層部", "じょうそうぶ"), ("塗れ", "まみれ"), ("気配", "けはい")]
APP = "3.11.0"


def _run(steps, path):
    with Ledger(path) as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)


def _refused_part(tmp_path, words=WORDS, refuse=(WORDS[1][0],)):
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "words": {"1": words}, "refuse_words": list(refuse),
            "app": APP}
    steps = FakeSteps(str(tmp_path), plan)
    path = str(tmp_path / "ledger.sqlite")
    _run(steps, path)
    return steps, path


def _need(path, kind=runner.MINE_REFUSED):
    with Ledger(path) as ledger:
        return [n for n in ledger.needs("ja") if n["kind"] == kind]


def test_a_part_anki_refused_words_of_is_its_own_line_naming_them_and_the_cloze_marks(tmp_path):
    _steps, path = _refused_part(tmp_path)
    [need] = _need(path)
    assert "塗れ" in need["say"] and "{{c1::" in need["say"] and "Skip" in need["say"]
    assert REFUSED_SAID in need["say"], "Anki Miner's own words stay beside ours"
    assert _need(path, "mine-failed") == []
    assert feed.build(status.read(languages=["ja"], path=path), "ja").items[1].kind == feed.FAILED


def test_skip_this_word_finishes_the_part_with_the_cards_it_made(tmp_path):
    steps, path = _refused_part(tmp_path)
    [need] = _need(path)
    assert actions.skip_refused("ja", need["id"], path=path) == actions.SKIPPED_ON
    with Ledger(path) as ledger:
        job = ledger.jobs("ja")[0]
        assert (job["state"], job["resume"]) == ("waiting", "filling")
        outcomes = {o["word"]: o["outcome"] for o in ledger.outcomes(job["id"])}
        assert outcomes == {"上層部": "made", "塗れ": "skipped", "気配": "made"}
        assert not [n for n in ledger.needs("ja") if n["kind"] == runner.MINE_REFUSED], "its line answered"
    _run(steps, path)                                   # Connect's next look: the part fills, orders, and is done
    with Ledger(path) as ledger:
        assert [j["state"] for j in ledger.jobs("ja")] == ["done"]
        assert ledger.conn.execute("SELECT COUNT(*) FROM meta WHERE key LIKE 'alone:%'").fetchone()[0] == 0
    assert any(e[0] == "fill" for e in steps.log), "the cards it did make are filled as any part's"
    assert status.read(languages=["ja"], path=path)["languages"]["ja"]["failed"] == []
    assert sorted(steps.anki.words()) == ["上層部", "気配"]


def test_a_skipped_word_is_never_sent_again_in_another_part_for_that_anki_miner(tmp_path):
    steps, path = _refused_part(tmp_path)
    [need] = _need(path)
    actions.skip_refused("ja", need["id"], path=path)
    _run(steps, path)
    steps.plan.update(queue={"ja": [2]}, line={"ja": [2]}, words={"2": [WORDS[1], ("約束", "やくそく")]})
    _run(steps, path)
    sent = [e[3] for e in steps.log if e[0] == "mine" and e[1] == 2]
    assert sent == [["約束"]], "skipped once: never asked again"


def test_a_new_anki_miner_asks_a_skipped_word_once_more(tmp_path):
    steps, path = _refused_part(tmp_path)
    [need] = _need(path)
    actions.skip_refused("ja", need["id"], path=path)
    _run(steps, path)
    steps.plan.update(queue={"ja": [2]}, line={"ja": [2]}, words={"2": [WORDS[1]]}, app="3.12.0", refuse_words=[])
    _run(steps, path)
    assert [e[3] for e in steps.log if e[0] == "mine" and e[1] == 2] == [["塗れ"]]


def test_skip_refuses_what_isnt_an_open_refusal_and_writes_nothing(tmp_path):
    steps, path = _refused_part(tmp_path)
    [need] = _need(path)
    assert actions.skip_refused("zh", need["id"], path=path) is False, "another language's line"
    assert actions.skip_refused("ja", need["id"] + 99, path=path) is False
    assert actions.skip_refused("ja", need["id"], path=path) == actions.SKIPPED_ON
    assert actions.skip_refused("ja", need["id"], path=path) is False, "pressed twice: one skip"
    assert actions.skip_refused("ja", 1, path=str(tmp_path / "none.sqlite")) is False


def test_a_part_anki_miner_crashed_on_stays_the_plain_line_with_try_again(tmp_path):
    """Not every failure is Anki's refusal: a crash twice keeps the line it had (no word to skip)."""
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "words": {"1": WORDS}, "crash_mid_batch": 1,
            "crash_always": True}
    _run(FakeSteps(str(tmp_path), plan), str(tmp_path / "ledger.sqlite"))
    assert _need(str(tmp_path / "ledger.sqlite")) == []
    assert len(_need(str(tmp_path / "ledger.sqlite"), "mine-failed")) == 1


def test_a_skip_with_a_try_again_already_queued_lets_that_try_finish_the_part(tmp_path):
    """One open job an item (the ledger's rule): with a *Try again* already queued, the skip leaves the failed job as
    it is — its words skipped — and the new try, which never sends them, finishes the part."""
    steps, path = _refused_part(tmp_path)
    [need] = _need(path)
    with Ledger(path) as ledger, ledger.transaction():
        ledger.ask("ja", 1, _now(), store_id="store-1")
    assert actions.skip_refused("ja", need["id"], path=path) == actions.SKIPPED_OWES, "the try open finishes it"
    before = len(steps.log)
    _run(steps, path)
    with Ledger(path) as ledger:
        assert [j["state"] for j in ledger.jobs("ja")] == ["failed", "done"]
    assert not [e for e in steps.log[before:] if e[0] == "mine" and "塗れ" in e[3]], "the skipped word: never sent"
    assert status.read(languages=["ja"], path=path)["languages"]["ja"]["failed"] == []


# --- review round 1 ---------------------------------------------------------------------------------------------- #
def test_a_skip_leaves_the_part_failed_while_it_owes_a_word_anki_never_refused(tmp_path):
    """B1: one word refused alone, another whose own run timed out. Skip leaves out the refused one only; the part
    stays *Try again* for the other, and its new try sends that word alone — never the skipped one."""
    words = [("上層部", "じょうそうぶ"), ("塗れ", "まみれ"), ("気配", "けはい")]
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "words": {"1": words}, "refuse_words": ["塗れ"], "app": APP}
    steps = FakeSteps(str(tmp_path), plan)
    original = steps.mine

    def times_out_alone(lang, job, picked, ws, attempt):
        if [w["word"] for w in ws] == ["気配"]:
            return {"outcomes": [dict(word=w["word"], reading=w["reading"], outcome="uncertain", note_id=None)
                                 for w in ws], "app": APP, "doubt": True}
        return original(lang, job, picked, ws, attempt)
    steps.mine = times_out_alone
    path = str(tmp_path / "ledger.sqlite")
    _run(steps, path)
    [need] = _need(path)
    assert "塗れ" in need["say"] and "気配" not in need["say"]
    assert actions.skip_refused("ja", need["id"], path=path) == actions.SKIPPED_OWES, "said: it still owes 気配"
    with Ledger(path) as ledger:
        assert ledger.jobs("ja")[0]["state"] == "failed", "it still owes 気配: its Try again stands"
        with ledger.transaction():
            ledger.ask("ja", 1, _now(), store_id="store-1")
    steps.mine = original
    before = len(steps.log)
    _run(steps, path)
    assert [e[3] for e in steps.log[before:] if e[0] == "mine"] == [["気配"]]
    with Ledger(path) as ledger:
        assert [j["state"] for j in ledger.jobs("ja")] == ["failed", "done"]


def test_a_refused_line_with_no_word_named_has_nothing_to_skip(tmp_path):
    _steps, path = _refused_part(tmp_path)
    [need] = _need(path)
    with Ledger(path) as ledger, ledger.transaction():
        ledger.conn.execute("DELETE FROM meta WHERE key LIKE 'alone:%'")
    assert actions.skip_refused("ja", need["id"], path=path) is False
    with Ledger(path) as ledger:
        assert ledger.jobs("ja")[0]["state"] == "failed"


def test_a_word_skipped_in_a_batch_of_no_known_version_counts_for_every_version(tmp_path):
    """N2: a word-at-a-time batch whose first run crashed records no Anki Miner version; its skip still holds."""
    steps, path = _refused_part(tmp_path)
    [need] = _need(path)
    actions.skip_refused("ja", need["id"], path=path)
    with Ledger(path) as ledger, ledger.transaction():
        ledger.conn.execute("UPDATE batches SET anki_miner = NULL")
    with Ledger(path) as ledger:
        assert ("塗れ", "まみれ") in ledger.skipped_words("ja", APP)


def test_a_name_surasura_puts_in_a_card_never_carries_an_anki_cloze_mark():
    """The one text Surasura itself puts in a card through Anki Miner's add (the Source's names, from a folder or a
    title): a cloze mark is broken by a zero-width space (proven on DevTest: then Anki takes it), shown the same."""
    from app.connect import runfile
    ep = runfile.episode("t-1", "/v/1.mkv", "/v/1.srt", [], names=["砂{{c1::まみれ}}の手", "第1話 {{C2::x}}"])
    assert "{{c1::" not in ep["series_name_override"] and "{{C2::" not in ep["episode_name_override"]
    assert ep["series_name_override"].replace("​", "") == "砂{{c1::まみれ}}の手"
    assert runfile.no_cloze("Re:ゼロ {c1} 第2話") == "Re:ゼロ {c1} 第2話" and runfile.no_cloze(None) is None
