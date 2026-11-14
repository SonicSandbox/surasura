"""Piyo's rounds from what Anki knows (Piyo-AK, 2026-11-14; a tester asked for his leeches, the cards he learned today
and the ones he knows well): `surasura_practice_start` and `surasura_words` with source struggling / today / known,
through the SDK's in-memory client, against a fake AnkiConnect (tests/test_anki_words.py's `CardCollection`) and a
real library indexed in the sandbox (the sentence dictionary's own build), so each word comes with real lines.

**Why it matters:** the round must practise the learner's own struggling / new / well-known cards in their order, each
with lines from their own shows and books; and when Anki can't answer (closed, busy, no deck chosen) or has none, the
AI gets one plain sentence that offers soon or top — never a round of other words passed off as those.
"""
import json
import os
from unittest import mock

import pytest

from app import anki_words
from app import sentence_corpus as sc
from app.cli import mcp_server
from tests.test_anki_sync import URL
from tests.test_anki_words import JA_DECK, CardCollection
from tests.test_mcp_server import _data, _run, _state, _zh_state

pytest.importorskip("mcp")

# Real lines (tests/Test Resources/ja/context_test.txt, zh/context_test.txt)
JA_LINES = ["冒険の準備はできていますか？", "素晴らしい冒険が待っているはずだ。", "冒険は危険だが、価値がある。",
            "彼は冒険家として非常に有名です。", "私たちは新しい冒険を求めている。", "彼は毎日冒険に出かけます。"]
ZH_LINES = ["我们需要去寻找新的冒险。", "冒险总是伴随着巨大的挑战。", "他在冒险中学会了勇敢和坚强。"]


def _library(language, lines, decks):
    """A library of two episodes in NOW (the lines split between them: the dictionary keeps two lines a word from one
    file), indexed as the background indexer leaves it, and settings.json naming the known-words sync's decks."""
    root = os.environ["SURASURA_TEST_ROOT"]
    now = os.path.join(root, "data", language, "HighPriority")
    os.makedirs(now, exist_ok=True)
    half = (len(lines) + 1) // 2
    for name, part in (("第01話.txt", lines[:half]), ("第02話.txt", lines[half:])):
        with open(os.path.join(now, name), "w", encoding="utf-8") as f:
            f.write("\n".join(part) + "\n")
    user_files = os.path.join(root, "User Files", language)
    os.makedirs(user_files, exist_ok=True)
    with open(os.path.join(user_files, "KnownWord.json"), "w", encoding="utf-8") as f:
        json.dump({"words": []}, f)
    with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as f:
        json.dump({"target_language": language, "anki_connect_url": URL,
                   "anki_sync_decks": {language: list(decks)}, "anki_sync_fields": {language: []}}, f)
    sc.build(language, os.path.join(root, f"corpus-{language}.zip"), progress=lambda message: None)


def _deck():
    fake = CardCollection()
    fake.card_note("危険", [{"ivl": 0, "lapses": 8, "suspended": True}], leech=True)
    fake.card_note("準備", [{"ivl": 1, "lapses": 6}], leech=True)
    fake.card_note("冒険", [{"ivl": 2, "lapses": 3}, {"ivl": 5, "lapses": 1}])
    fake.card_note("価値", [{"ivl": 40}])
    fake.card_note("求める", [{"ivl": 1, "today": True}])
    fake.card_note("有名", [{"ivl": 0, "today": True}])
    fake.card_note("出かける", [{"ivl": 90}])
    return fake


def _said(answer):
    """A ToolError's own words (the SDK puts "Error executing tool <name>: " before them)."""
    assert answer.is_error
    return answer.content[0].text.split(": ", 1)[1]


def _call(fake, state, tool, args):
    async def calls(client):
        return await client.call_tool(tool, args)
    with mock.patch("urllib.request.urlopen", fake):
        return _run(state, calls)


def test_a_struggling_round_practises_the_leeches_first_then_the_most_forgotten_with_lines_from_the_library():
    _library("ja", JA_LINES, [JA_DECK])
    state = _state(known_texts=JA_LINES)
    brief = _data(_call(_deck(), state, "surasura_practice_start", {"words": 3, "source": "struggling"}))
    assert brief["round"]["source"] == "struggling"
    assert [(w["word"], w["reading"]) for w in brief["round_words"]] == [("危険", "キケン"), ("準備", "ジュンビ"),
                                                                         ("冒険", "ボウケン")]
    by_word = {w["word"]: w["lines"] for w in brief["round_words"]}
    assert by_word["危険"] == [{"line": "冒険は危険だが、価値がある。", "from": "第01話.txt"}]
    assert all("冒険" in line["line"] for line in by_word["冒険"])
    assert len(by_word["冒険"]) == mcp_server.LINES_PER_WORD, "six lines say 冒険: the brief gives two"
    assert anki_words.SOURCES["struggling"]["rule"] in brief["rules"]
    assert ("危険", "キケン") in state._checkers["ja"].upcoming


def test_today_and_known_give_their_own_cards_through_the_words_tool_too():
    _library("ja", JA_LINES, [JA_DECK])
    state = _state(known_texts=JA_LINES)
    fake = _deck()
    today = _data(_call(fake, state, "surasura_words", {"which": "today"}))
    struggling = _data(_call(fake, state, "surasura_words", {"which": "struggling", "limit": 3}))
    assert [len(w["lines"]) for w in struggling["words"]] == [1, 1, mcp_server.LINES_PER_WORD]   # 冒険: six lines
    known = _data(_call(fake, state, "surasura_practice_start", {"words": 5, "source": "known", "kind": "reading"}))
    assert [w["word"] for w in today["words"]] == ["有名", "求める"]
    assert today["words"][0]["lines"] == [{"line": "彼は冒険家として非常に有名です。", "from": "第02話.txt"}]
    assert [w["word"] for w in known["round_words"]] == ["出かける", "価値"]
    assert anki_words.SOURCES["known"]["rule"] in known["rules"]


def test_a_word_the_library_never_says_comes_without_lines():
    _library("ja", JA_LINES, [JA_DECK])
    fake = CardCollection()
    fake.card_note("散歩", [{"ivl": 3, "lapses": 2}])
    brief = _data(_call(fake, _state(), "surasura_practice_start", {"source": "struggling"}))
    assert brief["round_words"] == [{"word": "散歩", "reading": "サンポ", "lines": []}]


def test_a_phrase_card_and_a_storys_own_term_come_with_their_lines():
    """A card's word of several words (気を取り直す) is found as its run of words, however inflected; a story's own term
    the library's name tables join (焔魄陣: a made-up technique the tagger cuts 焔 + 魄 + 陣) as it is written."""
    term = ["明日から焔魄陣の修行を始めよう。", "彼は昨日も焔魄陣を放った。", "焔魄陣が夜空に明るく光った。"]
    _library("ja", JA_LINES + ["彼女は気を取り直して歩き出した。"] + term, [JA_DECK])
    fake = CardCollection()
    fake.card_note("焔魄陣", [{"ivl": 3, "lapses": 4}])
    fake.card_note("気を取り直す", [{"ivl": 3, "lapses": 2}])
    brief = _data(_call(fake, _state(), "surasura_practice_start", {"words": 2, "source": "struggling"}))
    words = {w["word"]: [line["line"] for line in w["lines"]] for w in brief["round_words"]}
    assert words["気を取り直す"] == ["彼女は気を取り直して歩き出した。"]
    assert len(words["焔魄陣"]) == 2 and set(words["焔魄陣"]) <= set(term)
    # the term alone: no other card's look brings its episode in (the token store counts it as 焔 + 魄 + 陣)
    alone = CardCollection()
    alone.card_note("焔魄陣", [{"ivl": 3, "lapses": 4}])
    brief = _data(_call(alone, _state(), "surasura_practice_start", {"words": 1, "source": "struggling"}))
    assert len(brief["round_words"][0]["lines"]) == 2
    assert {line["line"] for line in brief["round_words"][0]["lines"]} <= set(term)


def test_a_cards_word_is_read_as_junban_and_backfill_read_it():
    """お部屋 is 部屋 and 努力する 努力 (their own grammar off, `anki_match.one_word`); 揚げる is no 上げる (the dictionary
    keeps them apart, `two_words`): its lines say 揚げる, never another word's; もん reads モン as written, as the list
    shows it; わかる and 分かる, two cards of one word, come once."""
    lines = ["母が台所で天ぷらを揚げている。", "先生の質問に手を上げた。", "部屋を片付けてから寝た。",
             "毎日努力を続けている。", "そんなもんだよ、人生って。", "やっと意味が分かった。"]
    _library("ja", lines, [JA_DECK])
    fake = CardCollection()
    for word in ("揚げる", "お部屋", "努力する", "もん", "わかる", "分かる"):
        fake.card_note(word, [{"ivl": 3, "lapses": 1}])
    got = _data(_call(fake, _state(known_texts=lines), "surasura_words", {"which": "struggling"}))["words"]
    by_word = {w["word"]: ([line["line"] for line in w["lines"]], w["reading"]) for w in got}
    assert by_word["揚げる"] == (["母が台所で天ぷらを揚げている。"], "アゲル")
    assert by_word["お部屋"][0] == ["部屋を片付けてから寝た。"]
    assert by_word["努力する"][0] == ["毎日努力を続けている。"]
    assert by_word["もん"] == (["そんなもんだよ、人生って。"], "モン")
    assert [w["word"] for w in got].count("分かる") + [w["word"] for w in got].count("わかる") == 1


def _real_words(n):
    """`n` different real words: a learner's known words (tests/Test Resources/ja/KnownWord.json), kanji ones."""
    import re
    path = os.path.join(os.path.dirname(__file__), "Test Resources", "ja", "KnownWord.json")
    with open(path, encoding="utf-8") as f:
        words = [e.get("dictForm") or "" for e in json.load(f)["words"]]
    return list(dict.fromkeys(w for w in words if re.fullmatch("[一-龯]{2}", w)))[:n]


def test_a_compound_the_token_store_counts_as_one_word_comes_with_its_lines():
    """上層部 is one word to the store too (an affix join, never the name tables): looked for by its own key."""
    lines = ["上層部の決定には逆らえない。", "その件は上層部に報告した。"]
    _library("ja", lines + JA_LINES, [JA_DECK])
    fake = CardCollection()
    fake.card_note("上層部", [{"ivl": 3, "lapses": 3}])
    got = _data(_call(fake, _state(), "surasura_words", {"which": "struggling"}))["words"]
    assert [line["line"] for line in got[0]["lines"]] == lines


def test_a_word_its_first_files_never_say_is_looked_for_again_in_every_file(monkeypatch):
    """揚げる is counted as 上げる (UniDic files it there): its first files may all be 上げる's. Those give no line, so
    every file holding it is looked at once more, and its own line is found."""
    monkeypatch.setattr(mcp_server, "FILES_PER_WORD", 1)
    _library("ja", ["先生の質問に手を上げた。", "母が台所で天ぷらを揚げている。"], [JA_DECK])
    fake = CardCollection()
    fake.card_note("揚げる", [{"ivl": 3, "lapses": 3}])
    got = _data(_call(fake, _state(), "surasura_words", {"which": "struggling"}))["words"]
    assert got[0]["lines"] == [{"line": "母が台所で天ぷらを揚げている。", "from": "第02話.txt"}]


def test_the_words_tool_from_anki_waits_for_a_checker_still_loading_without_a_deadlock():
    """The first call of a session may come while the language's checker still loads (it takes the checker's lock):
    the words are read once it is loaded, never under that lock (round 2: a two-minute wait, then a failure)."""
    import time
    _library("zh", ZH_LINES, ["中文"])
    fake = CardCollection()
    fake.card_note("冒险", [{"ivl": 30}], deck="中文")
    state = mcp_server.ServerState()
    state.default_language = lambda: "zh"
    started = time.monotonic()
    got = _data(_call(fake, state, "surasura_words", {"which": "known"}))["words"]
    assert [w["word"] for w in got] == ["冒险"] and got[0]["lines"]
    assert time.monotonic() - started < 60


def test_a_round_says_how_many_words_it_has_when_anki_has_fewer():
    _library("ja", JA_LINES, [JA_DECK])
    fake = CardCollection()
    fake.card_note("わかる", [{"ivl": 3, "lapses": 1}])
    fake.card_note("分かる", [{"ivl": 3, "lapses": 1}])
    brief = _data(_call(fake, _state(), "surasura_practice_start", {"words": 5, "source": "struggling"}))
    assert brief["round"]["words"] == len(brief["round_words"]) == 1


def test_the_words_tool_takes_at_most_fifty_from_anki():
    _library("ja", JA_LINES, [JA_DECK])
    fake = CardCollection()
    for word in _real_words(60):
        fake.card_note(word, [{"ivl": 3, "lapses": 1}])
    got = _data(_call(fake, _state(), "surasura_words", {"which": "struggling", "limit": 200}))
    assert len(got["words"]) == mcp_server.ANKI_WORDS_MOST == 50


def test_a_chinese_struggling_round():
    _library("zh", ZH_LINES, ["中文"])
    fake = CardCollection()
    fake.card_note("冒险", [{"ivl": 3, "lapses": 4}], deck="中文")
    fake.card_note("挑战", [{"ivl": 3, "lapses": 2}], deck="中文")
    fake.card_note("勇敢地", [{"ivl": 3, "lapses": 1}], deck="中文")       # 勇敢地 is 勇敢 (`one_word`'s 地)
    brief = _data(_call(fake, _zh_state(keep=False), "surasura_practice_start", {"words": 3, "source": "struggling"}))
    assert [w["word"] for w in brief["round_words"]] == ["冒险", "挑战", "勇敢地"]
    assert brief["round_words"][2]["lines"] == [{"line": "他在冒险中学会了勇敢和坚强。", "from": "第02話.txt"}]
    assert brief["round_words"][1]["lines"] == [{"line": "冒险总是伴随着巨大的挑战。", "from": "第01話.txt"}]


# --------------------------------------------------------------------------- #
# None, closed, busy, no deck: one plain sentence, soon / top offered, no round
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("source", list(anki_words.SOURCES))
def test_no_such_cards_say_so_and_offer_soon_or_top_and_the_words_tool_answers_empty(source):
    _library("ja", JA_LINES, [JA_DECK])
    fake = CardCollection()
    fake.card_note("冒険", [{"ivl": 3}])            # studied, never forgotten, not today, not mature
    started = _call(fake, _state(), "surasura_practice_start", {"source": source})
    text = _said(started)
    assert text.startswith(anki_words.SOURCES[source]["none"]) and "soon" in text and "top" in text
    listed = _data(_call(fake, _state(), "surasura_words", {"which": source}))
    assert listed["words"] == [] and listed["note"] == anki_words.SOURCES[source]["none"] + "."


def test_anki_closed_busy_or_with_no_deck_answers_in_one_sentence_that_offers_soon_or_top():
    _library("ja", JA_LINES, [JA_DECK])
    closed = _call(CardCollection(offline=True), _state(), "surasura_practice_start", {"source": "struggling"})
    busy = _call(CardCollection(busy=True), _state(), "surasura_words", {"which": "known"})
    for answer, says in ((closed, "Anki isn't open"), (busy, "Anki is busy")):
        text = _said(answer)
        assert text.startswith(says) and "soon" in text and "top" in text
        assert text.count(". ") == 0, "one sentence"
    refused = CardCollection()
    refused.card_note("冒険", [{"ivl": 3, "lapses": 2}])
    original = refused._answer
    refused._answer = lambda p: ({"result": None, "error": "Invalid search"} if p["action"] == "findNotes"
                                 and "prop:lapses=1" in p["params"]["query"] else original(p))
    text = _said(_call(refused, _state(), "surasura_practice_start", {"source": "struggling"}))
    assert text.startswith("Anki couldn't search") and "soon" in text, "Anki is open: never 'isn't open'"
    for name, card in (("no studied card", {"new": True}), ("no word", None)):
        fake = CardCollection()
        if card:
            fake.card_note("冒険", [card])
        else:
            fake.card_note("冒険", [{"ivl": 3, "lapses": 2}], fields=[("Expression", "")])
        _library("ja", JA_LINES, [JA_DECK])
        text = _said(_call(fake, _state(), "surasura_practice_start", {"source": "struggling"}))
        assert ("another profile" in text if card else "word field" in text) and "soon" in text, name
    with open(os.path.join(os.environ["SURASURA_TEST_ROOT"], "settings.json"), "w", encoding="utf-8") as f:
        json.dump({"target_language": "ja", "anki_sync_decks": {}}, f)
    fake = _deck()
    none = _call(fake, _state(), "surasura_practice_start", {"source": "today"})
    assert none.is_error and "Settings → Known words" in none.content[0].text and "soon" in none.content[0].text
    assert fake.requests == []


def test_an_anki_too_old_for_today_says_so():
    _library("ja", JA_LINES, [JA_DECK])
    fake = CardCollection(introduced=False)
    fake.card_note("冒険", [{"ivl": 0, "today": True}])
    answer = _call(fake, _state(), "surasura_practice_start", {"source": "today"})
    assert answer.is_error and "too old" in answer.content[0].text and "soon" in answer.content[0].text


# --------------------------------------------------------------------------- #
# What the AI reads: every tool text names the three, short; a rename is one key
# --------------------------------------------------------------------------- #
def test_the_round_and_words_tools_the_prompt_and_a_wrong_choice_name_every_source_briefly():
    async def calls(client):
        return (await client.list_tools(), await client.list_prompts(),
                await client.call_tool("surasura_practice_start", {"source": "leeches"}))
    tools, prompts, wrong = _run(_state(), calls)
    texts = {t.name: t.description for t in tools.tools}
    for name in ("surasura_practice_start", "surasura_words"):
        assert all(source in texts[name] for source in mcp_server.SOURCES), name
        assert len(texts[name]) < 1100, f"{name}: Piyo's AI reads it every turn"
    assert all(source in prompts.prompts[0].description for source in mcp_server.SOURCES)
    assert wrong.is_error and all(source in wrong.content[0].text for source in mcp_server.SOURCES)
    assert set(anki_words.SOURCES) <= set(mcp_server.SOURCES)
    assert all(source in mcp_server.INSTRUCTIONS for source in anki_words.SOURCES)


def test_a_struggling_round_done_again_keeps_its_words_without_asking_anki(monkeypatch):
    _library("ja", JA_LINES, [JA_DECK])
    state = _state(known_texts=JA_LINES)
    state.keep_rounds = lambda: True
    first = _data(_call(_deck(), state, "surasura_practice_start", {"words": 2, "source": "struggling"}))
    _call(_deck(), state, "surasura_save_round", {"round_id": first["round_id"]})
    closed = CardCollection(offline=True)
    again = _data(_call(closed, state, "surasura_practice_start", {"again": first["round_id"]}))
    assert again["round"]["source"] == "struggling"
    assert [w["word"] for w in again["round_words"]] == [w["word"] for w in first["round_words"]] == ["危険", "準備"]
    assert closed.requests == []
