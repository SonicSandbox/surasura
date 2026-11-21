"""*Mine again* says why a word of the episode still gets no card (Kantan-MA, a tester's report 2026-11-21: 大衆 in an
episode was never made, *Mine again* made nothing, and nothing said why).

Connect left a word out in two places that said nothing: the pick's own reasons (`pick.REASONS`: a name with Ignore
names on, a grammar word, only sung, only near a cut) were dropped by the runner, and a word Anki Miner had turned down
once for the episode (not found, no definition, skipped …) was filtered from every later pick of it, *Mine again*
included. Now each pick keeps those words with why (`picked["left"]`, `runner._left_out`), and `ledger.left_of` reads
the newest pick's back — with its own job's turned-down words — for the episode's window. A word with a card already is
no "not made" word.

Against `FakeSteps` and a real ledger; real Japanese and Chinese words. No live Anki, no sleeps.
"""
import json
import os

import pytest

from app.connect import ledger as L
from app.connect import pick, runner
from app.connect.ledger import Ledger, _now
from tests.connect.fake_steps import FakeSteps

WORDS = {"ja": [("迷宮", "メイキュウ"), ("大衆", "タイシュウ")], "zh": [("迷宫", "mígōng"), ("大众", "dàzhòng")]}


def _run(steps, path, lang):
    with Ledger(path) as ledger:
        runner.run({}, [lang], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        return [(j["id"], j.get("kind") or "mine", j["state"]) for j in ledger.jobs(lang)]


def _steps(tmp_path, lang, not_offered=()):
    """One episode holding WORDS[lang]; its pick also says `not_offered` (the real pick's shape)."""
    steps = FakeSteps(str(tmp_path), {"line": {lang: [1]}, "queue": {lang: [1]}, "words": {"1": WORDS[lang]}})
    real = steps.pick

    def picked(*a, **kw):
        return dict(real(*a, **kw), not_offered=list(not_offered))
    steps.pick = picked
    return steps


def _sung(word, reading):
    return {"word": word, "reading": reading, "orth": word, "reason": "sung", "why": pick.REASONS["sung"]}


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_word_the_pick_leaves_out_is_kept_with_why_and_read_back(tmp_path, lang):
    # why: the pick knew why (only sung) and the runner dropped it: the episode's window could never say
    sung = ("魔物", "マモノ") if lang == "ja" else ("魔物", "mówù")
    path = str(tmp_path / "ledger.sqlite")
    _run(_steps(tmp_path, lang, [_sung(*sung)]), path, lang)
    assert L.left_of(lang, [1], path) == {1: [{"word": sung[0], "why": pick.REASONS["sung"]}]}


def test_a_word_with_a_card_already_is_never_named_as_not_made(tmp_path):
    # why: "already has a card" is no word missing a card: listing every carded word would bury the real ones
    path = str(tmp_path / "ledger.sqlite")
    carded = {"word": "冒険", "reading": "ボウケン", "orth": "冒険", "reason": "has-card", "why": pick.REASONS["has-card"]}
    backlog = dict(carded, word="料理", reason="in-backlog", why=pick.REASONS["in-backlog"])
    _run(_steps(tmp_path, "ja", [carded, backlog]), path, "ja")
    assert L.left_of("ja", [1], path) == {1: []}


def test_mine_again_names_a_word_anki_miner_turned_down_before(tmp_path):
    # why: the report's shape — the word was turned down once (here: not found in its line), every later pick of the
    # episode left it out silently, *Mine again* too: now that ask's record says why
    path = str(tmp_path / "ledger.sqlite")
    steps = _steps(tmp_path, "ja")
    _run(steps, path, "ja")
    with Ledger(path) as ledger, ledger.transaction():
        first = ledger.jobs("ja")[0]["id"]
        ledger.conn.execute("DELETE FROM outcomes WHERE job_id = ?", (first,))
        ledger.record_outcomes(first, 1, [{"word": "大衆", "reading": "タイシュウ", "outcome": "not_found"}])
        assert ledger.ask("ja", 1, _now(), store_id="store-1")[0] == "queued"
    steps.anki._save({"next": 2000, "notes": {}})   # the 迷宮 card deleted meanwhile: the ask makes it again
    got = _run(steps, path, "ja")
    assert got[-1][1:] == ("asked", "done"), got
    with Ledger(path) as ledger:
        picked = ledger.picked(got[-1][0])
    assert [w["word"] for w in picked["words"]] == ["迷宮"]
    assert picked["left"] == [{"word": "大衆", "reading": "タイシュウ", "why": L.LEFT_WHY["not_found"]}]
    assert L.left_of("ja", [1], path) == {1: [{"word": "大衆", "why": L.LEFT_WHY["not_found"]}]}


def test_the_newest_pick_wins_and_its_own_turned_down_words_join_it(tmp_path):
    # why: an episode mined again says what its last pick left, never an older pick's words it has since made; a word
    # Anki Miner turned down in that same job (no definition) is named with it; reading writes nothing
    db = str(tmp_path / "ledger.sqlite")
    assert L.left_of("ja", [1], db) == {1: []}                           # no ledger yet
    with Ledger(db) as led:
        for item, left in ((1, [{"word": "魔物", "why": "said only in a song line"}]),
                           (1, [{"word": "詠唱", "why": "a name (Ignore names is on)"}]),
                           (2, None)):
            led.conn.execute("INSERT INTO jobs (language, item_id, state, created_at, updated_at, picked) VALUES "
                             "('ja', ?, 'done', 't', 't', ?)",
                             (item, json.dumps({"words": [], **({"left": left} if left else {})}, ensure_ascii=False)))
        newest = led.conn.execute("SELECT MAX(id) FROM jobs WHERE item_id = 1").fetchone()[0]
        with led.transaction():
            led.record_outcomes(newest, 1, [{"word": "鱗", "reading": "ウロコ", "outcome": "no_definition"},
                                            {"word": "装備", "reading": "ソウビ", "outcome": "made"}])
    before = os.stat(db).st_mtime_ns
    assert L.left_of("ja", [1, 2], db) == {1: [{"word": "詠唱", "why": "a name (Ignore names is on)"},
                                               {"word": "鱗", "why": L.LEFT_WHY["no_definition"]}], 2: []}
    assert L.left_of("zh", [1], db) == {1: []}
    assert os.stat(db).st_mtime_ns == before


def test_a_record_it_cant_read_gives_no_words_never_an_error(tmp_path):
    db = str(tmp_path / "ledger.sqlite")
    with Ledger(db) as led:
        led.conn.execute("INSERT INTO jobs (language, item_id, state, created_at, updated_at, picked) VALUES "
                         "('ja', 1, 'done', 't', 't', ?)", ('{"left": "not a list"',))
    assert L.left_of("ja", [1], db) == {1: []}


def test_left_out_names_each_declined_word_by_its_own_answer():
    # why: the words of the pick the runner filters (declined) each get Anki Miner's answer for them; a word kept out
    # for having no definition in other episodes (`uncardable`) or skipped by you says so
    got = {"words": [{"word": "大衆", "reading": "タイシュウ"}, {"word": "鱗", "reading": "ウロコ"},
                     {"word": "装備", "reading": "ソウビ"}, {"word": "迷宮", "reading": "メイキュウ"}],
           "not_offered": [_sung("魔物", "マモノ")]}
    declined = {("大衆", "タイシュウ"), ("鱗", "ウロコ"), ("装備", "ソウビ")}
    out = runner._left_out(got, declined, {("大衆", "タイシュウ"): "duplicate"}, {("装備", "ソウビ")})
    assert [(w["word"], w["why"]) for w in out] == [("大衆", L.LEFT_WHY["duplicate"]),
                                                    ("鱗", L.LEFT_WHY["no_definition"]),
                                                    ("装備", L.LEFT_WHY["skipped"]),
                                                    ("魔物", pick.REASONS["sung"])]


def test_an_answer_it_has_no_words_for_is_said_plainly():
    # why: an outcome the list of reasons doesn't name (a dry run's `ready`, a newer Anki Miner's) is never called
    # "not found": it says no card was made
    got = {"words": [{"word": "鱗", "reading": "ウロコ"}]}
    out = runner._left_out(got, {("鱗", "ウロコ")}, {("鱗", "ウロコ"): "ready"}, set())
    assert out == [{"word": "鱗", "reading": "ウロコ", "why": L.LEFT_OTHER}]
