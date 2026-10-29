"""`surasura-cli mcp` (app/cli/mcp_server.py): the practice chat's MCP server, through the SDK's in-memory client —
the tools and the prompt a learner's AI app sees, their read-only annotations, a round's brief from the list as the
last Generate left it (real Japanese words with their lines), the checker, and errors that say what to do next.
"""
import csv
import json
import os

import anyio
import pytest

from app import analyzer, practice
from app.cli import mcp_server, verbs

pytest.importorskip("mcp")
from mcp import Client  # noqa: E402

TALK = "今日は天気がいいから、映画を見に行こう。駅の前で待ってるね。"
LIST = [  # the top of a real list: Word, Orth, Reading, and lines from the learner's own episodes
    ("冒険", "冒険", "ボウケン", ["冒険は危険だが、価値がある。", "素晴らしい冒険が待っているはずだ。"]),
    ("議事録", "議事録", "ギジロク", ["会議の議事録を確認してください。"]),
    ("散歩", "散歩", "サンポ", ["公園で少し散歩してから帰った。"]),
]


def _state(known_texts=(TALK,), unknown=()):
    """A ServerState whose ja checker knows the words of `known_texts` except `unknown` (no settings.json read)."""
    analyzer.SANITIZE_JA = True
    tokenizer = analyzer.JapaneseTokenizer()
    keys = {(l, r) for text in known_texts for l, r, _s, _o in tokenizer.tokenize(text) if l not in set(unknown)}
    state = mcp_server.ServerState()
    state._checkers["ja"] = practice.Checker("ja", settings={}, recent=["駅", "映画"], library=(None, 0),
                                             known=(keys, {l for l, _r in keys}, set()))
    state.default_language = lambda: "ja"
    return state


def _write_list(rows=LIST):
    folder = verbs._results_dir()
    os.makedirs(folder, exist_ok=True)
    for name in (verbs.PRIORITY_CSV, verbs.PROGRESSIVE_CSV):
        with open(os.path.join(folder, name), "w", encoding="utf-8-sig", newline="") as f:
            out = csv.writer(f)
            out.writerow(["Word", "Orth", "Reading", "Score", "Context 1", "Src 1", "Context 2", "Src 2"])
            ordered = rows if name == verbs.PRIORITY_CSV else list(reversed(rows))
            for word, orth, reading, lines in ordered:
                cells = []
                for line in lines + [""] * (2 - len(lines)):
                    cells += [line, "HighPriority/Show/ep01.srt" if line else ""]
                out.writerow([word, orth, reading, 100] + cells)


def _run(state, calls):
    """Open the in-memory client on a fresh server and run `calls(client)` -> its result."""
    server, _ = mcp_server.build(state, warm=False)

    async def go():
        async with Client(server) as client:
            return await calls(client)
    return anyio.run(go)


def _data(result):
    return json.loads(result.content[0].text)


def test_the_ai_app_sees_three_read_only_tools_and_the_practice_prompt():
    async def calls(client):
        return await client.list_tools(), await client.list_prompts()
    tools, prompts = _run(_state(), calls)
    names = [t.name for t in tools.tools]
    assert names == ["surasura_practice_start", "surasura_check_text", "surasura_words"]
    for tool in tools.tools:
        a = tool.annotations
        assert a.read_only_hint is True and a.destructive_hint is False and a.open_world_hint is False
    (prompt,) = prompts.prompts
    assert prompt.name == "practice" and [a.name for a in prompt.arguments] == ["words", "role", "kind", "source"]


def test_check_text_through_the_server_passes_a_known_reply_and_names_a_new_word():
    async def calls(client):
        ok = await client.call_tool("surasura_check_text", {"text": TALK})
        bad = await client.call_tool("surasura_check_text", {"text": "会議の議事録を見ましたか。"})
        return ok, bad
    ok, bad = _run(_state(known_texts=(TALK, "会議の議事録を見ましたか。"), unknown={"議事録"}), calls)
    assert _data(ok)["pass"] is True and _data(ok)["recent_used"] == ["駅", "映画"]
    assert _data(bad)["pass"] is False and "議事録" in _data(bad)["reasons"][0]


def test_a_round_brief_carries_the_choices_the_lists_words_and_their_lines():
    _write_list()

    async def calls(client):
        return await client.call_tool("surasura_practice_start",
                                      {"words": 2, "role": "senpai", "kind": "chat", "source": "soon"})
    state = _state()
    brief = _data(_run(state, calls))
    assert brief["round"] == {"words": 2, "role": "senpai", "kind": "chat", "source": "soon"}
    assert brief["mode"] == "chat" and brief["known_recent"] == ["駅", "映画"]
    assert [w["word"] for w in brief["round_words"]] == ["冒険", "議事録"]
    assert brief["round_words"][0]["lines"][0] == {"line": "冒険は危険だが、価値がある。", "from": "ep01.srt"}
    assert any("senpai" in rule and "casual" in rule for rule in brief["rules"])
    assert any("surasura_check_text" in rule for rule in brief["rules"])
    # the round's words are the ones a reply may now bring in
    assert ("議事録", "ギジロク") in state._checkers["ja"].upcoming


def test_latest_reads_the_journeys_order_and_a_quiz_gets_lines():
    _write_list()

    async def calls(client):
        return await client.call_tool("surasura_practice_start", {"words": 1, "kind": "quiz", "source": "latest"})
    brief = _data(_run(_state(), calls))
    assert [w["word"] for w in brief["round_words"]] == ["散歩"]
    assert brief["quiz_lines"] == [{"line": "公園で少し散歩してから帰った。", "from": "ep01.srt", "word": "散歩"}]


def test_a_round_before_the_first_generate_says_only_easy_nouns_come_in():
    async def calls(client):
        return await client.call_tool("surasura_practice_start", {})
    brief = _data(_run(_state(), calls))
    assert brief["round_words"] == [] and "easy everyday nouns" in brief["note"]


def test_a_wrong_choice_answers_with_what_to_pick():
    async def calls(client):
        return (await client.call_tool("surasura_practice_start", {"role": "dragon"}),
                await client.call_tool("surasura_check_text", {"text": TALK, "mode": "essay"}))
    role, mode = _run(_state(), calls)
    assert role.is_error and "friend, coworker, boss" in role.content[0].text
    assert mode.is_error and "chat (a short reply)" in mode.content[0].text


def test_the_words_tool_gives_recent_and_upcoming_words():
    _write_list()

    async def calls(client):
        return (await client.call_tool("surasura_words", {"which": "recent"}),
                await client.call_tool("surasura_words", {"which": "soon", "limit": 2}))
    recent, soon = _run(_state(), calls)
    assert _data(recent)["words"] == ["駅", "映画"]
    assert [w["word"] for w in _data(soon)["words"]] == ["冒険", "議事録"]


def test_the_practice_prompt_points_the_ai_at_the_round_tool_with_its_arguments():
    async def calls(client):
        return await client.get_prompt("practice", {"words": "3", "role": "kohai", "kind": "quiz", "source": "mix"})
    got = _run(_state(), calls)
    text = got.messages[0].content.text
    assert 'surasura_practice_start(words=3, role="kohai", kind="quiz", source="mix")' in text


def test_the_list_of_the_other_language_gives_no_words(monkeypatch):
    _write_list()
    monkeypatch.setattr(verbs, "_results_language", lambda: "zh")
    assert mcp_server.next_words("ja") == []


def test_the_cli_hands_mcp_to_the_server_before_its_json_channel_opens(monkeypatch):
    """The server owns stdout as its wire: the CLI's channel (which swaps stdout for its log) never opens."""
    from app.cli import __main__ as cli, contract
    seen = []
    monkeypatch.setattr(mcp_server, "main", lambda argv: seen.append(argv) or 0)
    monkeypatch.setattr(contract, "open_channel", lambda out=None: pytest.fail("the JSON channel opened"))
    assert cli.main(["mcp"]) == 0 and seen == [[]]
