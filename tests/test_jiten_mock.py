
import pytest
import json
import os
import re
import sys
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


# --- The API key never travels on a command line (it would land in debug/app_debug_log.txt) ---- #
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
