"""Piyo helps with Surasura itself (app/cli/mcp_server.py): its help (topics → one topic → a search), diagnose, and
Send report asked of the learner in Surasura's window — through the SDK's in-memory client, as the learner's AI app
sees them.

What a wrong answer would cost: an AI that guesses where the help is silent, or reads it all for one question; an
answer twice its size (the words doubled as structured data, JSON pretty-printed); a report sent without the
learner's press, or a "sent" said when no window was open; the tools' own words naming how Surasura is built.
"""
import json
import os

import pytest

from app import anki_connect, help_docs, instance_name, practice, report, scrub, send_report
from app.cli import mcp_server
from tests import connect_helpers as ch

pytest.importorskip("mcp")
import anyio  # noqa: E402  (mcp's own dependency)
from mcp import Client  # noqa: E402

WHAT = "第3話のカードが作られなかった。Connectの行には「Anki Miner stopped」と出ている。"


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    """No real Anki, no real window: a test that wants one says so."""
    scrub.reset()
    help_docs.index.cache_clear()
    help_docs._search_table.cache_clear()
    monkeypatch.setattr(anki_connect, "probe", lambda url, required=(), timeout=5: {"ok": False, "missing": []})
    monkeypatch.setenv("SURASURA_INSTANCE_NAME", f"surasura-test-piyo-{os.getpid()}-none")
    yield
    scrub.reset()


def _state():
    state = mcp_server.ServerState()
    state.default_language = lambda: "ja"
    return state


def _call(name, args=None, state=None):
    server, _ = mcp_server.build(state or _state(), warm=False)

    async def go():
        async with Client(server) as client:
            return await client.call_tool(name, args or {})
    return anyio.run(go)


def _text(result):
    assert len(result.content) == 1
    return result.content[0].text


def _structured(result):
    return getattr(result, "structured_content", getattr(result, "structuredContent", None))


def _error(result):
    return result.is_error if hasattr(result, "is_error") else result.isError


# --- help ------------------------------------------------------------------------------------------------------- #
def test_the_topics_come_first_short_and_once():
    got = _call("surasura_help_topics")
    text = _text(got)
    assert text == help_docs.topics_text() and len(text) < 1200
    assert _structured(got) is None                         # its words once, never doubled as data


def test_one_topic_then_a_group_then_one_of_its_own():
    assert _text(_call("surasura_help", {"topic": "Known limits"})).startswith("Known limits\n")
    group = _text(_call("surasura_help", {"topic": "Questions"}))
    first = group.splitlines()[group.splitlines().index(next(l for l in group.splitlines() if l.startswith("Its ")))
                               + 1]
    assert _text(_call("surasura_help", {"topic": first})).startswith(f"Questions › ")


def test_a_topic_that_isnt_there_says_the_closest_ones():
    got = _call("surasura_help", {"topic": "Anki Miner window"})
    assert _error(got) and "No help topic" in _text(got) and "surasura_help_topics" in _text(got)


def test_a_search_answers_with_its_sections_and_nothing_says_the_help_is_silent():
    hits = _text(_call("surasura_help_search", {"query": "Does Surasura go online? What leaves my computer?"}))
    assert hits.startswith("## Questions › Core Concepts › Does Surasura go online?")
    silent = _text(_call("surasura_help_search", {"query": "flibbertigibbet zzqx"}))
    assert silent == mcp_server.NO_HELP and "never guess" in silent
    assert _error(_call("surasura_help_search", {"query": "anki", "limit": "lots"}))


def test_a_program_without_its_help_says_so_and_points_at_the_guide(monkeypatch):
    def gone():
        raise FileNotFoundError("help_index.json")
    monkeypatch.setattr(help_docs, "index", gone)
    got = _call("surasura_help_topics")
    assert _error(got) and "couldn't be read" in _text(got) and "Tutorial.md" in _text(got)


# --- diagnose --------------------------------------------------------------------------------------------------- #
def test_diagnose_answers_compact_json_once_with_how_to_read_it():
    ch.library("ja", connect=True)
    got = _call("surasura_diagnose", {"area": "library"})
    text = _text(got)
    assert _structured(got) is None and "\n" not in text and ", " not in text.split('"about"')[0]
    out = json.loads(text)
    assert set(out) == {"surasura", "library", "about"} and out["library"]["items"]["Current"] >= 4
    assert _error(_call("surasura_diagnose", {"area": "everything"}))


# --- Send report: the learner sends it, in the window ------------------------------------------------------------ #
def _files(root):
    return sorted(os.path.relpath(os.path.join(d, f), root) for d, _dirs, fs in os.walk(root) for f in fs)


def test_no_window_open_nothing_saved_nothing_sent(monkeypatch):
    sent = []
    monkeypatch.setattr(send_report, "send", lambda *a, **k: sent.append(a) or pytest.fail("never sent from here"))
    before = _files(os.environ["SURASURA_TEST_ROOT"])
    got = json.loads(_text(_call("surasura_send_report", {"what": WHAT, "learner_said": "カードが来ない"})))
    assert got == {"asked": False, "why": got["why"]} and "isn't open" in got["why"]
    assert _files(os.environ["SURASURA_TEST_ROOT"]) == before and sent == []
    assert report.listed(os.path.join(os.environ["SURASURA_TEST_ROOT"], "nowhere")) == []


def test_the_open_window_is_handed_the_words_and_the_learner_is_told_what_to_press(monkeypatch):
    handed = []
    monkeypatch.setattr(instance_name, "ask_window", lambda args, **k: handed.append(args) or True)
    got = json.loads(_text(_call("surasura_send_report", {"what": WHAT, "learner_said": "カードが来ない",
                                                           "expected": "三枚のカード"})))
    assert got["asked"] is True and "press Send report" in got["next"] and "Nothing is sent" in got["next"]
    assert handed == [[practice.REPORT_ARG, f"{WHAT}\n\nIn my words: カードが来ない", "三枚のカード"]]
    assert "limit" not in got


def test_the_days_limit_is_said_before_the_learner_presses(monkeypatch):
    monkeypatch.setattr(instance_name, "ask_window", lambda args, **k: True)
    monkeypatch.setattr(send_report, "sent_today", lambda now=None: send_report.PER_DAY)
    got = json.loads(_text(_call("surasura_send_report", {"what": WHAT})))
    assert got["asked"] is True and "5 reports today" in got["limit"]


def test_a_window_that_never_answers_is_said_and_a_report_too_long_or_empty_is_refused(monkeypatch):
    monkeypatch.setattr(instance_name, "ask_window", lambda args, **k: False)
    got = json.loads(_text(_call("surasura_send_report", {"what": WHAT})))
    assert got["asked"] is False and "didn't answer" in got["why"]
    assert _error(_call("surasura_send_report", {"what": "  "}))
    assert _error(_call("surasura_send_report", {"what": "あ" * (mcp_server.REPORT_WHAT_MAX + 1)}))
    assert _error(_call("surasura_send_report", {"what": WHAT, "expected": "い" * 1001}))


# --- what the AI reads ---------------------------------------------------------------------------------------- #
def test_the_tools_words_and_the_instructions_name_nothing_of_how_surasura_is_made():
    server, _ = mcp_server.build(_state(), warm=False)

    async def go():
        async with Client(server) as client:
            return await client.list_tools()
    tools = anyio.run(go)
    words = " ".join([mcp_server.INSTRUCTIONS] + [t.description or "" for t in tools.tools]).casefold()
    for word in ("index.json", "help_docs", "diagnose.py", "instance_name"):         # no file or module named
        assert word not in words, word
    from tests.test_help_docs import never_public
    for word in never_public() or ():
        assert word not in words, word
    assert len(mcp_server.INSTRUCTIONS) < 4096 and "surasura_help_search" in mcp_server.INSTRUCTIONS


# --- end to end: the real server process, as an AI app starts it -------------------------------------------------- #
def test_the_real_server_answers_a_how_to_and_a_diagnose_over_stdio(project_root):
    """`python -m app.cli mcp` over stdio: one how-to question and one diagnose, each answered once on the wire."""
    import subprocess
    import sys
    ch.library("ja", connect=True)
    p = subprocess.Popen([sys.executable, "-m", "app.cli", "mcp"], cwd=str(project_root), stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    calls = {3: ("surasura_help_search", {"query": "Do I need Anki open for cards to be made?"}),
             4: ("surasura_diagnose", {"area": "library"})}
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"}]
    msgs += [{"jsonrpc": "2.0", "id": n, "method": "tools/call", "params": {"name": name, "arguments": args}}
             for n, (name, args) in calls.items()]
    try:
        for msg in msgs:
            p.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        p.stdin.flush()
        got = {}
        while not set(calls) <= set(got):
            line = p.stdout.readline()
            assert line, "the server closed stdout before answering"
            msg = json.loads(line)
            got[msg.get("id")] = msg
        p.stdin.close()
    finally:
        p.kill() if p.poll() is None else None
        p.wait(20)
    how_to, diag = got[3]["result"], got[4]["result"]
    assert not how_to.get("isError") and "structuredContent" not in how_to
    (text,) = [c["text"] for c in how_to["content"]]
    assert text.startswith("## ") and "Anki" in text and "must be open" in text
    assert not diag.get("isError") and "structuredContent" not in diag
    out = json.loads(diag["content"][0]["text"])
    assert out["library"]["items"]["Current"] >= 4 and out["surasura"]["version"]
