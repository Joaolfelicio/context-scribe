import os
import json
import yaml
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch
from context_scribe.observer.copilot_cli_provider import CopilotCliProvider

def test_copilot_cli_provider_project_name():
    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir) / "session-1"
        session_dir.mkdir()
        workspace_file = session_dir / "workspace.yaml"
        with open(workspace_file, "w") as f:
            yaml.dump({"workingDirectory": "/home/user/my-project"}, f)
        
        events_file = session_dir / "events.jsonl"
        events_file.touch()
        
        provider = CopilotCliProvider(log_dir=tmpdir)
        project_name = provider._get_project_name(str(events_file))
        assert project_name == "my-project"

def test_copilot_cli_provider_parse_content():
    with tempfile.TemporaryDirectory() as tmpdir:
        session_dir = Path(tmpdir) / "session-1"
        session_dir.mkdir()
        events_file = session_dir / "events.jsonl"
        
        # Mock events.jsonl content
        events = [
            {"type": "user.message", "id": "msg-1", "data": {"content": "Hello", "timestamp": "2024-03-23T00:00:00Z"}},
            {"type": "assistant.message", "id": "msg-2", "data": {"content": "Hi", "timestamp": "2024-03-23T00:00:01Z"}},
            {"type": "user.message", "id": "msg-3", "data": {"content": "Extract rules", "timestamp": "2024-03-23T00:00:02Z"}}
        ]
        
        with open(events_file, "w") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")
        
        provider = CopilotCliProvider(log_dir=tmpdir)
        # Clear interaction queue if initialized
        provider.interaction_queue = []
        provider.global_processed_ids = set()
        
        provider._parse_file_content(str(events_file), str(events_file))
        
        # Should have 2 interactions (user messages)
        assert len(provider.interaction_queue) == 2
        assert provider.interaction_queue[0].content == "Hello"
        assert provider.interaction_queue[1].content == "Extract rules"
        assert "msg-1" in provider.global_processed_ids
        assert "msg-3" in provider.global_processed_ids
