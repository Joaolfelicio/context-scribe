import os
import shutil
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from context_scribe.observer.gemini_cli_provider import GeminiCliProvider

def test_provider_initialization_with_existing_logs(tmp_path):
    # Setup mock log dir
    log_dir = tmp_path / "gemini_logs"
    log_dir.mkdir()
    session_file = log_dir / "session.json"
    session_file.write_text('{"sessionId": "s1", "messages": [{"id": "m1", "text": "test"}]}')
    
    with patch("os.path.expanduser", return_value=str(log_dir)):
        provider = GeminiCliProvider(log_dir=str(log_dir))
        assert "s1_m1" in provider.global_processed_ids

def test_process_file_new_message(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    provider = GeminiCliProvider(log_dir=str(log_dir))
    
    file_path = log_dir / "new_session.json"
    file_path.write_text('{"sessionId": "s2", "messages": [{"id": "m2", "type": "user", "text": "New Rule"}]}')
    
    provider._process_file(str(file_path))
    
    assert len(provider.interaction_queue) == 1
    assert provider.interaction_queue[0].content == "New Rule"
    assert "s2_m2" in provider.global_processed_ids

def test_project_name_detection(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    provider = GeminiCliProvider(log_dir=str(log_dir))
    
    # Global file (direct in tmp)
    global_file = log_dir / "logs.json"
    global_file.write_text('[]')
    provider._process_file(str(global_file))
    # We can't easily check project_name without a message, so let's add one
    global_file.write_text('[{"sessionId": "g", "messageId": 1, "type": "user", "message": "msg"}]')
    provider._process_file(str(global_file))
    assert provider.interaction_queue[0].project_name == "global"
    
    # Project file (in subfolder)
    proj_dir = log_dir / "my-project"
    proj_dir.mkdir()
    proj_file = proj_dir / "session.json"
    proj_file.write_text('{"sessionId": "p", "messages": [{"id": "m", "type": "user", "text": "msg"}]}')
    provider._process_file(str(proj_file))
    assert provider.interaction_queue[1].project_name == "my-project"
