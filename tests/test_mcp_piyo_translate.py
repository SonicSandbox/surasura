"""Piyo translates the learner's cards (app/cli/mcp_server.py over app/card_translations.py): the cards that want a
translation → the learner's AI translates → the write, checked, into empty fields only, one Undo a batch — through the
SDK's in-memory client, as the learner's AI app sees them.

What a wrong answer would cost: a write the AI thinks failed (or worked) when it didn't; a field the learner filled
overwritten; a batch that can't be taken back; Anki's sync never arranged after a write (the phone keeps the old
card); a long answer per card (the learner's tokens); the AI told nothing about how to translate (two bolds, the
Japanese left in, the neighbouring lines translated too).

Real data: the public-domain 蜘蛛の糸 and the 喫茶店の朝 subtitle (`samples/ja/`); Anki is the fake of
tests/test_card_translations.py.
"""
import json

import pytest

from app import card_translations as ct
from app.cli import mcp_server
from app.connect import ledger as ledger_mod
from app.connect import sentence_audio as sa
from app.connect import undo as undoing
from tests.test_card_translations import _anki

pytest.importorskip("mcp")
import anyio  # noqa: E402
from mcp import Client  # noqa: E402

SPIDER = [("蓮池", "御釈迦様は極楽の<b>蓮池</b>のふちを、独りでぶらぶら御歩きになっていらっしゃいました。"),
          ("地獄", "その<b>地獄</b>の底に、犍陀多と云う男が一人、ほかの罪人と一しょに蠢いている姿が、御眼に止まりました。"),
          ("蜘蛛", "ふと見ますと、側の翡翠のような色をした蓮の葉の上に、極楽の<b>蜘蛛</b>が一匹、美しい銀色の糸をかけております。")]


@pytest.fixture
def anki(tmp_path, monkeypatch):
    fake = _anki()
    for n, (word, sentence) in enumerate(SPIDER, 1):
        fake.put(n, "Lapis", {"Expression": word, "Sentence": sentence}, tags=["surasura::connect::a-1"] if n == 1 else ())
    monkeypatch.setattr(ledger_mod, "path", lambda: str(tmp_path / "connect" / "ledger.sqlite"))
    monkeypatch.setattr(mcp_server, "_anki_url", lambda: ({}, "http://127.0.0.1:8765"))
    monkeypatch.setattr(ct, "AnkiReads", lambda url: fake)
    monkeypatch.setattr(sa, "AnkiConnectNotes", lambda url: fake)
    monkeypatch.setattr(ct, "context", lambda ids, language="ja", around=1, *a: {})
    fake.synced = []
    monkeypatch.setattr(undoing, "owe_sync", lambda settings: fake.synced.append(True))
    return fake


def _state():
    state = mcp_server.ServerState()
    state.default_language = lambda: "ja"
    return state


def _call(name, args=None):
    server, _ = mcp_server.build(_state(), warm=False)

    async def go():
        async with Client(server) as client:
            return await client.call_tool(name, args or {})
    return anyio.run(go)


def _tools():
    server, _ = mcp_server.build(_state(), warm=False)

    async def go():
        async with Client(server) as client:
            return (await client.list_tools()).tools
    return {t.name: t for t in anyio.run(go)}


def _error(result):
    return result.is_error if hasattr(result, "is_error") else result.isError


def _data(result):
    s = getattr(result, "structured_content", getattr(result, "structuredContent", None))
    return s if s is not None else json.loads(result.content[0].text)


def test_the_tools_tell_the_ai_how_to_translate_and_which_ones_write():
    """The list tool's description carries the instructions (one bold, the meaning, never the context translated);
    the write and the undo are marked as writing, the list as reading."""
    tools = _tools()
    listing = tools["surasura_cards_to_translate"]
    assert ct.HOW in listing.description and "data, not instructions" in listing.description
    assert listing.annotations.read_only_hint is True
    for name in ("surasura_write_translations", "surasura_undo_translations"):
        assert tools[name].annotations.read_only_hint is False and tools[name].annotations.destructive_hint is False
    assert "surasura_cards_to_translate" in mcp_server.INSTRUCTIONS


def test_the_cards_come_compact_connects_first_with_the_next_step(anki):
    got = _call("surasura_cards_to_translate", {"limit": 2})
    assert not _error(got)
    text = got.content[0].text
    data = json.loads(text)
    assert [c["id"] for c in data["cards"]] == [1, 3] and data["left"] == 1
    assert data["cards"][0]["word"] == "蓮池" and "<b>" not in data["cards"][0]["sentence"]
    assert "surasura_write_translations" in data["next"] and "1 more" in data["next"]
    assert ": " not in text and "\n" not in text, "compact JSON: the learner's tokens"
    assert len(text) < 400


def test_a_batch_is_written_refused_ones_say_why_the_sync_is_arranged_and_one_undo_takes_it_back(anki):
    got = _data(_call("surasura_write_translations", {"items": [
        {"id": 1, "translation": "The Buddha was strolling alone along the edge of the <b>lotus pond</b> in paradise."},
        {"id": 2, "translation": "At the bottom of hell, a man named Kandata."},
        {"id": 3, "translation": "A <b>spider</b> of paradise was spinning a beautiful silver thread."}]}))
    assert got["written"] == 2 and got["refused"] == {"2": ct.ONE_BOLD}
    assert "surasura_undo_translations" in got["undo"] and anki.synced == [True]
    assert anki.value(1, "Hint").endswith("<b>lotus pond</b> in paradise.") and anki.value(2, "Hint") == ""
    done = _data(_call("surasura_undo_translations", {"batch": got["batch"]}))
    assert done == {"emptied": 2} and anki.value(1, "Hint") == "" and anki.synced == [True, True]
    again = _call("surasura_undo_translations", {"batch": got["batch"]})
    assert _error(again) and "No translations" in again.content[0].text


def test_while_the_learner_reviews_nothing_is_written_and_the_ai_is_told_to_wait(anki):
    anki.reviewing_ = True
    got = _call("surasura_write_translations", {"items": [{"id": 1, "translation": "The <b>lotus pond</b>."}]})
    assert _error(got) and "reviewing" in got.content[0].text
    assert anki.value(1, "Hint") == "" and anki.synced == []


def test_too_many_or_no_items_and_anki_closed_are_answered_in_plain_words(anki, monkeypatch):
    many = [{"id": n, "translation": "<b>x</b>"} for n in range(ct.MOST + 1)]
    assert "At most" in _call("surasura_write_translations", {"items": many}).content[0].text
    assert "items is a list" in _call("surasura_write_translations", {"items": []}).content[0].text
    from app import anki_connect

    def closed(*a, **k):
        raise anki_connect.AnkiError("offline", kind="offline")
    monkeypatch.setattr(anki, "note_types", closed)
    got = _call("surasura_cards_to_translate")
    assert _error(got) and "Anki isn't open" in got.content[0].text


def test_a_source_surasura_made_nothing_from_says_so(anki, monkeypatch):
    monkeypatch.setattr(ct, "source_notes", lambda language, title, data_dir=None: [])
    got = _call("surasura_cards_to_translate", {"source": "蜘蛛の糸"})
    assert _error(got) and "made no cards" in got.content[0].text
    monkeypatch.setattr(ct, "source_notes", lambda language, title, data_dir=None: [3])
    assert [c["id"] for c in _data(_call("surasura_cards_to_translate", {"source": "蜘蛛"}))["cards"]] == [3]


def test_a_batch_stopped_part_way_by_any_failure_names_its_undo(anki):
    """r1 S6: something not Anki's stops the write after the first card: the answer names the batch to take back,
    the sync is arranged, and that Undo works."""
    anki.fail_on_update = 3
    got = _call("surasura_write_translations", {"items": [
        {"id": 1, "translation": "By the <b>lotus pond</b> in paradise."},
        {"id": 3, "translation": "A <b>spider</b> of paradise."}]})
    text = got.content[0].text
    assert _error(got) and "surasura_undo_translations(batch=" in text and anki.synced == [True]
    batch = text.split("batch=")[1].split(")")[0].strip("'\"")
    assert anki.value(1, "Hint").startswith("By the")
    assert _data(_call("surasura_undo_translations", {"batch": batch})) == {"emptied": 1, "kept": {"3": "never written"}}


def test_no_card_offered_but_more_waiting_says_so_never_all_done(anki, monkeypatch):
    """r1 S3: a scan that offered nothing while cards remain never says every card has a translation."""
    monkeypatch.setattr(ct, "cards", lambda *a, **k: {"cards": [], "left": 7})
    data = _data(_call("surasura_cards_to_translate"))
    assert data["left"] == 7 and "Every card" not in data["next"]
