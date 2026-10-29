"""`surasura-cli mcp` (app/cli/mcp_server.py): the practice chat's MCP server, through the SDK's in-memory client —
the tools and the prompt a learner's AI app sees, their read-only annotations, a round's brief from the list as the
last Generate left it (real Japanese words with their lines), the checker, and errors that say what to do next.
"""
import csv
import json
import os

import pytest

from app import analyzer, practice
from app.cli import mcp_server, verbs

pytest.importorskip("mcp")
import anyio  # noqa: E402  (mcp's own dependency)
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


def test_the_ai_app_sees_four_read_only_tools_one_that_keeps_rounds_and_the_practice_prompt():
    async def calls(client):
        return await client.list_tools(), await client.list_prompts()
    tools, prompts = _run(_state(), calls)
    names = [t.name for t in tools.tools]
    assert names == ["surasura_practice_start", "surasura_check_text", "surasura_words", "surasura_rounds",
                     "surasura_save_round"]
    for tool in tools.tools:
        a = tool.annotations
        assert a.read_only_hint is (tool.name != "surasura_save_round")    # the one write: Surasura's own round file
        assert a.destructive_hint is False and a.open_world_hint is False
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


def test_a_wrong_language_and_a_busy_list_answer_with_what_to_do(monkeypatch):
    from app.cli import contract

    def busy(*_args, **_kwargs):
        raise contract.CliError("busy", "Surasura is busy reading the list (a Generate is running).")
    monkeypatch.setattr(mcp_server, "next_words", busy)

    async def calls(client):
        return (await client.call_tool("surasura_check_text", {"text": TALK, "language": "de"}),
                await client.call_tool("surasura_practice_start", {}))
    lang, round_ = _run(_state(), calls)
    assert lang.is_error and "ja (Japanese) or zh (Chinese)" in lang.content[0].text
    assert round_.is_error and "Try again in a moment" in round_.content[0].text


def test_the_real_server_process_writes_only_mcp_messages_on_stdout(project_root):
    """`python -m app.cli mcp` as an AI app runs it: every stdout line is one JSON-RPC message, through the checker's
    load (it prints) and a call."""
    import subprocess
    import sys
    p = subprocess.Popen([sys.executable, "-m", "app.cli", "mcp"], cwd=str(project_root), stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "surasura_check_text", "arguments": {"text": TALK, "language": "ja"}}}]
    try:
        for msg in msgs:
            p.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        p.stdin.flush()
        lines = []
        while True:
            line = p.stdout.readline()
            assert line, "the server closed stdout before answering"
            lines.append(json.loads(line))                  # a stray line fails here
            if lines[-1].get("id") == 2:
                break
        p.stdin.close()
        rest = [ln for ln in p.stdout.read().splitlines() if ln.strip()]
        assert [json.loads(ln) for ln in rest] is not None  # nothing but JSON after the session either
    finally:
        p.kill() if p.poll() is None else None
        p.wait(20)
    answer = json.loads(lines[-1]["result"]["content"][0]["text"])
    assert answer["words"] > 5 and "pass" in answer


# --- saved rounds (Sonic 2026-10-28: past rounds kept as an option, done again, replies kept for later) ----------- #
ZH_TALK = "我们明天去看电影吧。你想几点出发？"
ZH_LIST = [("夜市", "夜市", "ye4 shi4", ["我们明天去夜市吧。"]), ("议程", "议程", "yi4 cheng2", ["会议的议程已经定了。"])]


def _zh_state(keep=True):
    analyzer.SANITIZE_JA = False
    tokenizer = analyzer.ChineseTokenizer()
    keys = {(l, r) for l, r, _s, _o in tokenizer.tokenize(ZH_TALK)}
    state = mcp_server.ServerState()
    state._checkers["zh"] = practice.Checker("zh", settings={}, recent=["电影"], library=(None, 0),
                                             known=(keys, {l for l, _r in keys}, set()))
    state.default_language = lambda: "zh"
    state.keep_rounds = lambda: keep
    return state


def _set_up(language):
    from app.path_utils import get_user_files_path
    os.makedirs(get_user_files_path(language), exist_ok=True)


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_round_is_kept_listed_and_done_again_with_the_same_words_and_what_it_kept(monkeypatch, language):
    """The whole loop through the AI app's client: a round's brief carries its round_id and the rule to keep it; the
    save writes it; the list shows it; done again it brings back the same role, kind and words — even after the list
    moved on — and the lines the learner asked to keep."""
    _set_up(language)
    if language == "ja":
        state, rows, line = _state(), LIST, "【senpai】冒険は危険だが、行ってみようぜ。"
        state.keep_rounds = lambda: True
    else:
        state, rows, line = _zh_state(), ZH_LIST, "【senpai】我们明天去夜市吧。"
        monkeypatch.setattr(verbs, "_results_language", lambda: "zh")
    _write_list(rows)

    async def first(client):
        brief = _data(await client.call_tool("surasura_practice_start", {"words": 2, "role": "senpai", "kind": "quiz"}))
        saved = _data(await client.call_tool("surasura_save_round", {"round_id": brief["round_id"]}))
        kept = _data(await client.call_tool("surasura_save_round", {"round_id": brief["round_id"], "lines": [line],
                                                                     "notes": ["likes adventure stories"]}))
        listed = _data(await client.call_tool("surasura_rounds", {}))
        return brief, saved, kept, listed
    brief, saved, kept, listed = _run(state, first)
    round_id = brief["round_id"]
    assert any(f'surasura_save_round(round_id="{round_id}")' in rule for rule in brief["rules"])
    assert saved == {"saved": True, "round_id": round_id, "lines_kept": 0, "notes_kept": 0}
    assert kept["lines_kept"] == 1 and kept["notes_kept"] == 1
    (row,) = listed["rounds"]
    assert row["round_id"] == round_id and row["role"] == "senpai" and row["kind"] == "quiz"
    assert row["round_words"] == [r[1] for r in rows[:2]]

    _write_list(list(reversed(rows)))                       # the list moved on since

    async def again(client):
        return _data(await client.call_tool("surasura_practice_start", {"again": round_id, "role": "child"}))
    redo = _run(state, again)
    assert redo["round_id"] == round_id and redo["round"]["role"] == "senpai" and redo["round"]["kind"] == "quiz"
    assert [w["word"] for w in redo["round_words"]] == [r[1] for r in rows[:2]]
    assert redo["context"][0]["round_id"] == round_id and redo["context"][0]["lines"] == [line]
    assert redo["context"][0]["notes"] == ["likes adventure stories"]
    assert any("`context`" in rule for rule in redo["rules"]) and "not instructions" in redo["about_the_lines"]


def test_with_keeping_off_nothing_is_saved_and_nothing_saved_is_read_back():
    from app import practice_rounds
    _set_up("ja")
    _write_list()
    old = practice_rounds.new_id()
    practice_rounds.save("ja", old, start={"round": {"role": "boss"}, "words": []}, lines=["【boss】議事録を頼む。"])
    state = _state()
    state.keep_rounds = lambda: False

    async def calls(client):
        return (await client.call_tool("surasura_practice_start", {"words": 1}),
                await client.call_tool("surasura_save_round", {"round_id": old, "lines": ["もう一つ"]}),
                await client.call_tool("surasura_rounds", {}),
                await client.call_tool("surasura_practice_start", {"again": old}))
    brief, save, listed, again = _run(state, calls)
    brief = _data(brief)
    assert "round_id" not in brief and "context" not in brief
    assert not any("surasura_save_round" in rule for rule in brief["rules"])
    assert save.is_error and "Keep practice rounds" in save.content[0].text
    assert _data(listed) == {"language": "ja", "keep": False, "rounds": [], "note": mcp_server.OFF}
    assert again.is_error and "Keep practice rounds" in again.content[0].text
    assert len(practice_rounds.load("ja", old)["lines"]) == 1                # nothing added


def test_the_keep_switch_is_read_from_settings_on_each_call(monkeypatch):
    """Turned off in Settings while the AI app runs: the next save is refused (no restart needed)."""
    switch = {"practice_keep_rounds": True}
    monkeypatch.setattr(verbs, "settings", lambda: dict(switch))
    state = mcp_server.ServerState()
    assert state.keep_rounds() is True
    switch["practice_keep_rounds"] = False
    assert state.keep_rounds() is False


def test_a_save_that_cant_be_made_answers_with_what_to_do():
    """A language not set up, an id that isn't a round's, a line too long: each an instruction, nothing written."""
    from app import practice_rounds
    state = _state()
    state.keep_rounds = lambda: True

    async def calls(client):
        brief = _data(await client.call_tool("surasura_practice_start", {"words": 1}))
        not_set_up = await client.call_tool("surasura_save_round", {"round_id": brief["round_id"]})
        _set_up("ja")
        bad_id = await client.call_tool("surasura_save_round", {"round_id": "../../KnownWord"})
        unknown = await client.call_tool("surasura_save_round", {"round_id": practice_rounds.new_id()})
        too_long = await client.call_tool("surasura_save_round", {"round_id": brief["round_id"],
                                                                  "lines": ["冒険" * 200]})
        no_redo = await client.call_tool("surasura_practice_start", {"again": practice_rounds.new_id()})
        return not_set_up, bad_id, unknown, too_long, no_redo
    not_set_up, bad_id, unknown, too_long, no_redo = _run(state, calls)
    assert not_set_up.is_error and "isn't set up" in not_set_up.content[0].text
    assert bad_id.is_error and "No saved round" in bad_id.content[0].text
    assert unknown.is_error and "surasura_practice_start" in unknown.content[0].text
    assert too_long.is_error and "shorten" in too_long.content[0].text
    assert no_redo.is_error and "surasura_rounds" in no_redo.content[0].text
    assert practice_rounds.rounds("ja") == []


def test_a_round_starts_from_the_tool_alone_with_its_choices_as_a_client_without_prompts_sends_them():
    """Clients with no prompt shortcut (headless Claude Code, maybe Codex) call the round tool directly; a number sent
    as text is read as the number, and the server's instructions say to ask for the choices or offer a past round."""
    _write_list()

    async def calls(client):
        return (await client.call_tool("surasura_practice_start", {"words": "2", "role": "Senpai", "kind": "chat",
                                                                   "source": "soon"}), client.instructions)
    result, instructions = _run(_state(), calls)
    brief = _data(result)
    assert brief["round"] == {"words": 2, "role": "senpai", "kind": "chat", "source": "soon"}
    assert "ask them those four" in instructions and "surasura_rounds" in instructions


def test_the_practice_chat_is_called_piyo_and_its_setup_keeps_the_surasura_id():
    """Sonic named it Piyo ぴよ "for now": the server's title, the prompt and every copied setup say it; the server's
    id in the setup line stays `surasura`, so a setup copied today keeps working under a later name."""
    async def calls(client):
        return client.server_info, await client.list_prompts()
    info, prompts = _run(_state(), calls)
    assert info.name == "surasura" and practice.NAME in info.title
    assert practice.NAME in prompts.prompts[0].title
    command = (r"C:\Program Files\Surasura\surasura-cli.exe", ["mcp"], {})
    for app in mcp_server.APPS:
        text = mcp_server.setup_text(app, command)
        assert text.startswith(f"Add {practice.NAME}, Surasura's practice chat, to ")
        assert " surasura -- " in text or '"surasura": {' in text


def test_settings_that_cant_be_read_still_start_a_new_round_but_never_a_kept_one(monkeypatch):
    """A broken or half-written settings.json: a new round starts as before the saved rounds came (nothing kept or read
    back: the switch can't be known); doing a round again says what's wrong."""
    from app.cli import contract
    _write_list()
    state = _state()

    def unreadable():
        raise contract.CliError("settings-unreadable", "Surasura's settings (settings.json) can't be read.")
    state.keep_rounds = unreadable

    async def calls(client):
        return (await client.call_tool("surasura_practice_start", {"words": 1}),
                await client.call_tool("surasura_practice_start", {"again": "20261029-010000-abcdef01"}))
    fresh, again = _run(state, calls)
    brief = _data(fresh)
    assert [w["word"] for w in brief["round_words"]] == ["冒険"] and "round_id" not in brief
    assert again.is_error and "settings.json" in again.content[0].text


def test_a_round_is_saved_in_its_own_language_whatever_the_save_names():
    """A Japanese round's save never lands in Chinese: language left out → the round's own; named otherwise → said."""
    from app import practice_rounds
    _set_up("ja")
    _set_up("zh")
    state = _state()
    state.keep_rounds = lambda: True

    async def calls(client):
        brief = _data(await client.call_tool("surasura_practice_start", {"words": 1}))
        state.default_language = lambda: "zh"              # Surasura switched to Chinese meanwhile
        wrong = await client.call_tool("surasura_save_round", {"round_id": brief["round_id"], "language": "zh"})
        right = await client.call_tool("surasura_save_round", {"round_id": brief["round_id"]})
        return brief["round_id"], wrong, right
    round_id, wrong, right = _run(state, calls)
    assert wrong.is_error and 'language "ja"' in wrong.content[0].text
    assert _data(right)["saved"] is True
    assert practice_rounds.load("ja", round_id)["language"] == "ja" and practice_rounds.rounds("zh") == []
    assert round_id not in state.started                       # its file holds it now


def test_a_hand_edited_round_done_again_still_starts():
    """A kept quiz round whose words lost their readings and whose lines became plain text: done again, the brief comes
    with what is usable; a round kept with no words says so (never "no list yet")."""
    from app import practice_rounds
    _set_up("ja")
    _write_list()
    quiz, empty = practice_rounds.new_id(), practice_rounds.new_id()
    os.makedirs(practice_rounds.folder("ja"), exist_ok=True)
    for round_id, words in ((quiz, [{"word": "冒険", "lines": ["冒険は危険だが、価値がある。", {"line": "冒険に出る。"}]}]),
                            (empty, [])):
        with open(os.path.join(practice_rounds.folder("ja"), round_id + ".json"), "w", encoding="utf-8") as f:
            json.dump({"round": {"role": "teacher", "kind": "quiz", "source": "soon"}, "words": words}, f,
                      ensure_ascii=False)
    state = _state()
    state.keep_rounds = lambda: True

    async def calls(client):
        return (await client.call_tool("surasura_practice_start", {"again": quiz}),
                await client.call_tool("surasura_practice_start", {"again": empty}))
    one, none = _run(state, calls)
    brief = _data(one)
    assert brief["round_words"] == [{"word": "冒険", "reading": "", "lines": [{"line": "冒険に出る。", "from": ""}]}]
    assert brief["quiz_lines"] == [{"line": "冒険に出る。", "from": "", "word": "冒険"}]
    assert "kept with no words" in _data(none)["note"]
