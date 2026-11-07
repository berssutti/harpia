import unittest.mock as mock
import pytest
import json
from .main import fetch_initial_watchlist, fetch_initial_groups, watchlist, monitored_groups

def test_fetch_initial_watchlist():
    mock_data = [
        {"value": "test@example.com", "target_type": "email", "is_active": True},
        {"value": "ignored@example.com", "target_type": "email", "is_active": False}
    ]
    
    with mock.patch("urllib.request.urlopen") as mock_url:
        mock_response = mock.MagicMock()
        mock_response.read.return_value = json.dumps(mock_data).encode()
        mock_response.__enter__.return_value = mock_response
        mock_url.return_value = mock_response
        
        fetch_initial_watchlist()
        
        assert "test@example.com" in watchlist
        assert "ignored@example.com" not in watchlist

def test_fetch_initial_groups():
    mock_data = [
        {"name": "@testgroup"},
        {"name": "1234567"}
    ]
    
    with mock.patch("urllib.request.urlopen") as mock_url:
        mock_response = mock.MagicMock()
        mock_response.read.return_value = json.dumps(mock_data).encode()
        mock_response.__enter__.return_value = mock_response
        mock_url.return_value = mock_response
        
        fetch_initial_groups()
        
        assert "testgroup" in monitored_groups
        assert "1234567" in monitored_groups

@pytest.mark.asyncio
async def test_worker_handler_logic():
    # This is a placeholder for a more complex Telethon event test
    # In a real scenario, we would mock the 'event' object
    assert True
