
import pytest
import json
import os
import re
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from app.jiten_converter import fetch_jiten_vocabulary

@pytest.fixture
def mock_jiten_response():
    """Sample JSON response from Jiten API."""
    return [
        {
            "wordId": 101,
            "wordText": "猫",
            "reading": "ねこ",
            "partOfSpeech": "noun",
            "state": 5,  # Should map to KNOWN
            "cardId": 12345,
            "created": "2023-01-01T12:00:00Z",
            "lastReview": "2023-02-01T12:00:00Z"
        },
        {
            "wordId": 102,
            "wordText": "犬",
            "reading": "いぬ",
            "partOfSpeech": "noun",
            "state": 3, # Should map to LEARNING
            "cardId": None,
            "created": "2023-01-02T12:00:00Z"
        }
    ]

def test_jiten_fetch_success(tmp_path, mock_jiten_response):
    """Test successful Jiten API fetch and conversion."""
    output_file = tmp_path / "jiten_output.json"
    
    # Mock requests.get
    with patch("requests.get") as mock_get:
        # Configure mock response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_jiten_response
        mock_get.return_value = mock_resp
        
        # Run function
        success = fetch_jiten_vocabulary("dummy_api_key", str(output_file))
        
        assert success is True
        assert output_file.exists()
        
        # Verify content
        with open(output_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        assert data["source"] == "Jiten API"
        assert len(data["words"]) == 2
        
        # Check mapping logic
        w1 = next(w for w in data["words"] if w["dictForm"] == "猫")
        assert w1["knownStatus"] == "KNOWN"
        assert w1["hasCard"] == 1
        
        w2 = next(w for w in data["words"] if w["dictForm"] == "犬")
        assert w2["knownStatus"] == "LEARNING"
        assert w2["hasCard"] == 0

def test_jiten_fetch_invalid_key(tmp_path):
    """Test handling of invalid API key."""
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_get.return_value = mock_resp
        
        success = fetch_jiten_vocabulary("bad_key", str(tmp_path / "out.json"))
        assert success is False


# --- Replacing known words: a dated backup first, never an empty overwrite -------------------- #
def _jiten_returns(cards):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = cards
    return patch("requests.get", return_value=mock_resp)


def _known_words_file(tmp_path):
    path = tmp_path / "User Files" / "ja" / "KnownWord.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"source": "AnkiConnect", "words": [
        {"dictForm": "冒険", "knownStatus": "KNOWN", "hasCard": 1, "language": "ja"}]},
        ensure_ascii=False), encoding="utf-8")
    return path


def test_jiten_import_backs_up_the_known_words_it_replaces(tmp_path, mock_jiten_response):
    known = _known_words_file(tmp_path)
    before = known.read_bytes()

    with _jiten_returns(mock_jiten_response):
        assert fetch_jiten_vocabulary("key", str(known)) is True

    [backup] = list((known.parent / ".trash").iterdir())
    assert re.fullmatch(r"KnownWord\.\d{8}-\d{6}\.json", backup.name), backup.name
    assert backup.read_bytes() == before


def test_an_empty_jiten_account_never_replaces_existing_known_words(tmp_path):
    known = _known_words_file(tmp_path)
    before = known.read_bytes()

    with _jiten_returns([]):
        assert fetch_jiten_vocabulary("key", str(known)) is False
    assert known.read_bytes() == before


# --- The API key never travels on a command line (it would land in logs/app_debug_log.txt) ----- #
def test_the_import_window_passes_the_key_in_the_environment_not_the_command_line():
    from app.jiten_db_importer_gui import JitenImporterGUI
    from app.jiten_converter import API_KEY_ENV
    with patch.object(JitenImporterGUI, "__init__", lambda self, root, language='ja': None):
        gui = JitenImporterGUI(None)
    gui.language = "ja"
    gui.api_key_var = MagicMock()
    gui.api_key_var.get.return_value = "jiten-secret-key-123"
    gui.log = MagicMock()

    process = MagicMock(stdout=[], returncode=0)
    with patch("app.jiten_db_importer_gui.subprocess.Popen", return_value=process) as popen:
        gui.fetch_and_import()

    cmd, kwargs = popen.call_args[0][0], popen.call_args[1]
    assert not any("jiten-secret-key-123" in str(part) for part in cmd), cmd
    assert kwargs["env"][API_KEY_ENV] == "jiten-secret-key-123"


def test_the_converter_reads_the_key_from_its_environment(monkeypatch):
    from app import jiten_converter
    monkeypatch.setenv(jiten_converter.API_KEY_ENV, "jiten-secret-key-123")
    monkeypatch.setattr(sys, "argv", ["convert_jiten", "--language", "ja"])
    with patch.object(jiten_converter, "fetch_jiten_vocabulary", return_value=True) as fetch, \
         pytest.raises(SystemExit) as done:
        jiten_converter.main()
    assert fetch.call_args[0][0] == "jiten-secret-key-123"
    assert done.value.code == 0


def test_a_rejected_key_exits_with_an_error_so_the_window_says_so(monkeypatch):
    """The window shows "Success" on exit code 0. An invalid key used to exit 0 too, so it announced
    "Jiten vocabulary imported successfully!" for an import that wrote nothing."""
    from app import jiten_converter
    monkeypatch.setenv(jiten_converter.API_KEY_ENV, "bad-key")
    monkeypatch.setattr(sys, "argv", ["convert_jiten", "--language", "ja"])
    with patch.object(jiten_converter, "fetch_jiten_vocabulary", return_value=False), \
         pytest.raises(SystemExit) as done:
        jiten_converter.main()
    assert done.value.code == 1


def test_no_key_at_all_exits_with_an_error(monkeypatch):
    from app import jiten_converter
    monkeypatch.delenv(jiten_converter.API_KEY_ENV, raising=False)
    monkeypatch.setattr(sys, "argv", ["convert_jiten", "--language", "ja"])
    with patch.object(jiten_converter, "fetch_jiten_vocabulary") as fetch, \
         pytest.raises(SystemExit) as done:
        jiten_converter.main()
    assert done.value.code == 1
    fetch.assert_not_called()


# --- W3.4 row 2: Japanese only, fetch then confirm, the ignored words kept --------------------------------------- #
def test_a_chinese_import_is_refused_before_any_fetch(tmp_path):
    """Jiten stamps every word 'ja': a zh import would replace the Chinese list with Japanese words (inv §4.9)."""
    from app import jiten_converter
    known = tmp_path / "KnownWord.json"
    known.write_text('{"words": [{"dictForm": "学习", "knownStatus": "KNOWN"}]}', encoding="utf-8")
    before = known.read_bytes()
    with patch("requests.get") as get:
        assert fetch_jiten_vocabulary("key", str(known), language="zh") is False
        assert jiten_converter.save_cards("key", str(tmp_path / "cards.json"), language="zh") is False
        assert jiten_converter.replace_known([{"dictForm": "猫", "knownStatus": "KNOWN"}], "zh", str(known)) is False
    get.assert_not_called()
    assert known.read_bytes() == before


def test_the_converter_refuses_chinese_before_reading_a_key(monkeypatch):
    from app import jiten_converter
    monkeypatch.setenv(jiten_converter.API_KEY_ENV, "jiten-secret-key-123")
    with patch("requests.get") as get, pytest.raises(SystemExit) as done:
        jiten_converter.main(["--language", "zh"])
    assert done.value.code == 1
    get.assert_not_called()


def test_step_one_keeps_the_cards_and_changes_no_known_words(tmp_path, mock_jiten_response, monkeypatch, capsys):
    from app import jiten_converter
    known = _known_words_file(tmp_path)
    before = known.read_bytes()
    cards = tmp_path / "cards.json"
    monkeypatch.setenv(jiten_converter.API_KEY_ENV, "jiten-secret-key-123")
    with _jiten_returns(mock_jiten_response), pytest.raises(SystemExit) as done:
        jiten_converter.main(["--language", "ja", "--save-cards", str(cards)])
    assert done.value.code == 0
    assert jiten_converter.load_cards(str(cards)) == mock_jiten_response
    assert known.read_bytes() == before and not (known.parent / ".trash").exists()
    assert "jiten-secret-key-123" not in capsys.readouterr().out


def test_step_two_replaces_from_the_kept_cards_with_no_fetch_and_keeps_ignored_and_graduated_words(
        tmp_path, mock_jiten_response):
    from app import jiten_converter
    known = tmp_path / "User Files" / "ja" / "KnownWord.json"
    known.parent.mkdir(parents=True)
    known.write_text(json.dumps({"words": [
        {"dictForm": "冒険", "knownStatus": "KNOWN", "hasCard": 1},
        {"dictForm": "えっと", "knownStatus": "IGNORED", "hasCard": 0},          # dismissed in Migaku
        {"dictForm": "猫", "knownStatus": "IGNORED", "hasCard": 0},              # Jiten names it: Jiten's entry wins
        {"dictForm": "旅", "knownStatus": "KNOWN", "source": "GraduatedList"},   # a past Graduate's word
    ]}, ensure_ascii=False), encoding="utf-8")
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps(mock_jiten_response, ensure_ascii=False), encoding="utf-8")
    with patch("requests.get") as get:
        assert jiten_converter.replace_from_cards(str(cards), "ja", str(known)) is True
    get.assert_not_called()
    words = {w["dictForm"]: w["knownStatus"] for w in json.loads(known.read_text(encoding="utf-8"))["words"]}
    assert words == {"猫": "KNOWN", "犬": "LEARNING", "旅": "KNOWN", "えっと": "IGNORED"}   # 冒険 (Anki's) replaced
    assert len(list((known.parent / ".trash").iterdir())) == 1


def test_step_two_with_unreadable_cards_changes_nothing(tmp_path):
    from app import jiten_converter
    known = _known_words_file(tmp_path)
    before = known.read_bytes()
    bad = tmp_path / "cards.json"
    bad.write_text("{not json", encoding="utf-8")
    assert jiten_converter.replace_from_cards(str(bad), "ja", str(known)) is False
    assert known.read_bytes() == before


def test_a_held_known_words_lock_refuses_the_replace_and_writes_nothing(tmp_path, mock_jiten_response, monkeypatch):
    from app import anki_sync, jiten_converter
    from tests.test_cli_locks import Holder
    monkeypatch.setattr(anki_sync, "KNOWN_LOCK_WAIT", 0.2)
    known = tmp_path / "User Files" / "ja" / "KnownWord.json"
    known.parent.mkdir(parents=True)
    known.write_text('{"words": [{"dictForm": "冒険", "knownStatus": "KNOWN"}]}', encoding="utf-8")
    before = known.read_bytes()
    with Holder("known-words-ja", "Anki known-words sync"):
        assert jiten_converter.replace_known(jiten_converter.words_from_cards(mock_jiten_response), "ja",
                                             str(known)) is False
    assert known.read_bytes() == before


def test_the_command_lines_step_two_needs_no_key_and_never_fetches(tmp_path, mock_jiten_response, monkeypatch):
    from app import jiten_converter
    monkeypatch.delenv(jiten_converter.API_KEY_ENV, raising=False)
    from app.path_utils import get_user_files_path
    known = Path(get_user_files_path("ja")) / "KnownWord.json"           # the command line's own default
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps(mock_jiten_response, ensure_ascii=False), encoding="utf-8")
    with patch("requests.get") as get, pytest.raises(SystemExit) as done:
        jiten_converter.main(["--language", "ja", "--cards", str(cards)])
    assert done.value.code == 0
    get.assert_not_called()
    assert {w["dictForm"] for w in json.loads(known.read_text(encoding="utf-8"))["words"]} == {"猫", "犬"}


def test_a_failed_backup_leaves_the_known_words_untouched_by_jiten(tmp_path, mock_jiten_response):
    from app import jiten_converter
    known = _known_words_file(tmp_path)
    before = known.read_bytes()
    with patch("app.jiten_converter.backup_to_trash", side_effect=OSError("disk full")):
        assert jiten_converter.replace_known(jiten_converter.words_from_cards(mock_jiten_response), "ja",
                                             str(known)) is False
    assert known.read_bytes() == before


# --- AD2-1: a known-words file that exists but can't be read is never replaced #
# Its past Graduates' and dismissed words can't be kept from a file no one can read, and the confirmation would say
# "0 → N": the replace refuses, writing nothing — the rule the .apkg import's merge follows.
UNREADABLE = ['{"words": [{"dictForm": "冒険"', '"冒険"', '{"words": "冒険"}']


@pytest.mark.parametrize("content", UNREADABLE)
def test_an_unreadable_known_words_file_refuses_jitens_replace_and_writes_nothing(tmp_path, content):
    from app import jiten_converter
    known = _known_words_file(tmp_path)
    known.write_text(content, encoding="utf-8")
    words = jiten_converter.words_from_cards([{"wordText": "猫", "state": 5}])
    assert jiten_converter.replace_known(words, "ja", str(known)) is False
    assert known.read_bytes() == content.encode("utf-8")
    assert not (known.parent / ".trash").exists()          # refused before any backup


def test_step_one_refuses_before_any_fetch_when_the_known_words_cant_be_read(monkeypatch, tmp_path):
    from app import jiten_converter
    from app.path_utils import get_user_files_path
    os.makedirs(get_user_files_path("ja"), exist_ok=True)
    known = os.path.join(get_user_files_path("ja"), "KnownWord.json")
    with open(known, "w", encoding="utf-8") as f:
        f.write(UNREADABLE[0])
    fetched = []
    monkeypatch.setattr(jiten_converter, "fetch_cards", lambda key: fetched.append(key) or ([], None))
    cards = tmp_path / "cards.json"
    assert jiten_converter.save_cards("key", str(cards), "ja") is False
    assert fetched == [] and not cards.exists()
