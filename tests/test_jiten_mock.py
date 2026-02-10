
import pytest
import json
import os
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
