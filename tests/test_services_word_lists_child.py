"""*Paste text*'s child process (W3.3 FX-wl S2; n16 "a worker process": `word_lists.find_words` / `find_main`, started
as `app_entry.py word-lists-find --headless`).

What a wrong answer would cost: the paste finding other words than the library's tokenizer finds (a chip that adds a
word the list never counts, or misses one); the text put on the child's command line (app_entry.py logs every argv);
a child that crashed or hung read as "no words", or left running; the window's own `analyzer.LOGIC` changed by a paste.
"""
import json
import os
import subprocess
import sys

import pytest

from app import path_utils
from app.services import word_lists


@pytest.fixture
def known_file(ja_resources_dir):
    """The real Migaku export (11,176 entries, 46 IGNORED) as this language's KnownWord.json."""
    import shutil
    dst = os.path.join(path_utils.get_user_files_path("ja"), "KnownWord.json")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(os.path.join(ja_resources_dir, "KnownWord.json"), dst)
    return dst


@pytest.fixture
def own_logic(monkeypatch):
    """The analyzer's LOGIC as a copy for this test: the in-process reference (`words_in`) updates it, and no other test
    may inherit that."""
    from app import analyzer
    monkeypatch.setattr(analyzer, "LOGIC", dict(analyzer.LOGIC))
    return analyzer


def _put(text, kind="ignore", language="ja"):
    path = word_lists.list_path(kind, language)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(text.encode("utf-8"))
    return path


def _settings(data):
    with open(path_utils.get_settings_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _lines(folder, name, n):
    with open(os.path.join(folder, name), encoding="utf-8") as f:
        return "\n".join(f.read().splitlines()[:n])


# --- the same words as the in-process read ------------------------------------------------------------------------- #
def test_the_childs_japanese_words_and_marks_equal_the_in_process_read(ja_resources_dir, known_file, own_logic):
    # A page of real sentences, CRLF line ends, with words on both lists and in KnownWord.json: every mark the chips
    # show (listed / known / left_out / new) and the order must come back exactly as words_in gives them.
    text = _lines(ja_resources_dir, "context_test.txt", 11).replace("\n", "\r\n") + "\r\nケーキを食べた。灯台の砂時計。"
    _put("# 無視する単語\n冒険\n")
    _put("灯台\n", "blacklist")
    child = word_lists.find_words(text, "ja", "ignore")
    assert child == word_lists.words_in(text, "ja", "ignore")
    marks = {c.word: c.status for c in child}
    assert marks["冒険"] == "listed" and marks["灯台"] == "left_out" and marks["砂時計"] == "new"
    assert marks["食べる"] == "known"                                 # KNOWN in KnownWord.json
    assert all(isinstance(c, word_lists.Candidate) for c in child)


def test_the_childs_chinese_words_equal_the_in_process_read(zh_resources_dir, own_logic):
    text = _lines(zh_resources_dir, "chinese_text_1.txt", 12)
    _put("台湾\n", "blacklist", "zh")
    child = word_lists.find_words(text, "zh", "blacklist")
    assert child == word_lists.words_in(text, "zh", "blacklist")
    marks = {c.word: c.status for c in child}
    assert marks["台湾"] == "listed" and "特朗普" in marks


def test_the_child_reads_the_settings_itself_and_the_callers_logic_never_changes(ja_resources_dir, own_logic):
    # N4: the paste read the user's logic block into the window's own analyzer.LOGIC. Now the child reads it, so the
    # caller's stays as it was — and the child's words still follow the settings (exclude_single off: one-kanji words).
    analyzer = own_logic
    _settings({"exclude_single": False, "logic": {"names_katakana": not analyzer.LOGIC.get("names_katakana", True)}})
    before = dict(analyzer.LOGIC)
    text = _lines(ja_resources_dir, "context_test.txt", 11) + "手に入れた。"
    child = word_lists.find_words(text, "ja")
    assert analyzer.LOGIC == before
    assert child == word_lists.words_in(text, "ja")                  # the reference: settings read in-process
    assert "手" in [c.word for c in child]                           # exclude_single off reached the child


def test_an_empty_text_finds_nothing_in_the_child(own_logic):
    assert word_lists.find_words("", "ja") == [] and word_lists.find_words("  \n", "zh") == []


# --- the child's command line and its stdout ---------------------------------------------------------------------- #
def test_the_text_never_goes_on_the_command_line(monkeypatch):
    seen = []
    real = subprocess.Popen

    def record(args, **kw):
        seen.append(list(args))
        return real(args, **kw)
    monkeypatch.setattr(word_lists.subprocess, "Popen", record)
    word_lists.find_words("冒険の準備", "ja")
    assert len(seen) == 1
    assert seen[0][-2:] == [word_lists.FIND_VERB, "--headless"]
    assert not any("冒険" in arg for arg in seen[0])


def test_the_command_is_the_frozen_apps_own_verb_or_app_entry_from_source(monkeypatch):
    monkeypatch.setattr(path_utils, "is_frozen", lambda: True)
    assert word_lists.find_command() == [sys.executable, "word-lists-find", "--headless"]
    monkeypatch.setattr(path_utils, "is_frozen", lambda: False)
    command = word_lists.find_command()
    assert command[0] == sys.executable and os.path.basename(command[1]) == "app_entry.py"
    assert os.path.isfile(command[1]) and command[2:] == ["word-lists-find", "--headless"]


def test_what_the_tokenizer_prints_stays_off_the_answer(monkeypatch, capfd):
    # find_main moves stdout to stderr while it reads: run in this process with stdin and stdout as pipes would be.
    import io
    request = json.dumps({"text": "冒険の準備", "language": "ja", "kind": "ignore"}, ensure_ascii=False)
    out = io.BytesIO()

    class Stream:
        buffer = out
    real = word_lists.words_in

    def noisy(*args):
        print("Loading the tokenizer…")
        return real(*args)
    monkeypatch.setattr(word_lists, "words_in", noisy)
    monkeypatch.setattr(sys, "stdin", type("In", (), {"buffer": io.BytesIO(request.encode("utf-8"))})())
    monkeypatch.setattr(sys, "stdout", Stream())
    from app import analyzer
    monkeypatch.setattr(analyzer, "LOGIC", dict(analyzer.LOGIC))
    assert word_lists.find_main() == 0
    answer = json.loads(out.getvalue().decode("utf-8"))
    assert [w[0] for w in answer["words"]] == ["冒険", "準備"]
    assert "Loading the tokenizer" in capfd.readouterr().err


@pytest.mark.parametrize("request_text", ["not json", json.dumps({"text": "冒険", "language": "fr"}),
                                          json.dumps({"text": "冒険", "language": "ja", "kind": "graduated"})])
def test_a_request_the_child_cant_answer_exits_1_with_nothing_on_stdout(request_text):
    env = path_utils.build_subprocess_env(False)
    proc = subprocess.run(word_lists.find_command(), input=request_text.encode("utf-8"), capture_output=True, env=env,
                          timeout=120)
    assert proc.returncode == 1 and proc.stdout == b""
    assert b"Traceback" in proc.stderr


# --- a child that fails, hangs or is cancelled -------------------------------------------------------------------- #
def test_a_child_that_fails_raises_with_its_last_line_and_exit_code(monkeypatch):
    monkeypatch.setattr(word_lists, "find_command",
                        lambda: [sys.executable, "-c", "import sys; sys.stderr.write('MeCab failed to load\\n'); "
                                                       "sys.exit(3)"])
    with pytest.raises(word_lists.FindFailed) as e:
        word_lists.find_words("冒険", "ja")
    assert not isinstance(e.value, word_lists.Cancelled)
    assert "exit code 3" in str(e.value) and "MeCab failed to load" in str(e.value)


def test_a_child_whose_answer_cant_be_read_raises(monkeypatch):
    monkeypatch.setattr(word_lists, "find_command", lambda: [sys.executable, "-c", "print('{\"wor')"])
    with pytest.raises(word_lists.FindFailed, match="couldn't read"):
        word_lists.find_words("冒険", "ja")


def test_a_child_that_hangs_is_killed_at_the_timeout(monkeypatch):
    started = []
    real = word_lists.Paste._started

    def record(self, proc):
        started.append(proc)
        return real(self, proc)
    monkeypatch.setattr(word_lists.Paste, "_started", record)
    monkeypatch.setattr(word_lists, "find_command", lambda: [sys.executable, "-c", "import time; time.sleep(60)"])
    with pytest.raises(word_lists.FindFailed, match="longer than 1 seconds") as e:
        word_lists.find_words("冒険", "ja", timeout=1)
    assert not isinstance(e.value, word_lists.Cancelled)
    assert started and started[0].poll() is not None                # killed, not left running


def test_a_cancel_kills_the_running_child(monkeypatch):
    import threading
    monkeypatch.setattr(word_lists, "find_command", lambda: [sys.executable, "-c", "import time; time.sleep(60)"])
    paste, result = word_lists.Paste(), []

    def run():
        try:
            word_lists.find_words("冒険", "ja", paste=paste)
        except word_lists.FindFailed as e:
            result.append(e)
    t = threading.Thread(target=run)
    t.start()
    import time
    deadline = time.monotonic() + 30
    while paste._proc is None and time.monotonic() < deadline:
        time.sleep(0.01)
    proc = paste._proc
    assert proc is not None
    paste.cancel()
    t.join(30)
    assert not t.is_alive() and isinstance(result[0], word_lists.Cancelled)
    assert proc.poll() is not None


def test_a_paste_cancelled_before_it_starts_starts_no_child(monkeypatch):
    seen = []
    monkeypatch.setattr(word_lists.subprocess, "Popen", lambda *a, **kw: seen.append(a))
    paste = word_lists.Paste()
    paste.cancel()
    with pytest.raises(word_lists.Cancelled):
        word_lists.find_words("冒険", "ja", paste=paste)
    assert seen == []


def test_a_child_that_cant_start_raises(monkeypatch):
    monkeypatch.setattr(word_lists, "find_command", lambda: [os.path.join(os.getcwd(), "no-such-program.exe")])
    with pytest.raises(word_lists.FindFailed, match="couldn't start"):
        word_lists.find_words("冒険", "ja")
