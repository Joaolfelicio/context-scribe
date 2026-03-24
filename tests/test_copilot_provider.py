import json
import os
import tempfile  # noqa: F401
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

from context_scribe.observer.copilot_provider import CopilotProvider
from context_scribe.models.evaluator_models import INTERNAL_SIGNATURE


def test_get_messages_from_data_turns_format():
    provider = CopilotProvider()
    data = {
        "turns": [
            {
                "request": {"content": "hello", "id": "1"},
                "response": {"content": "hi there", "id": "2"}
            }
        ]
    }
    messages = provider._get_messages_from_data(data)
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "hello"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "hi there"


def test_get_messages_from_data_messages_format():
    provider = CopilotProvider()
    data = {"messages": [{"role": "user", "content": "hello", "id": "1"}]}
    messages = provider._get_messages_from_data(data)
    assert len(messages) == 1
    assert messages[0]["content"] == "hello"


def test_get_messages_from_data_list():
    provider = CopilotProvider()
    data = [{"role": "user", "content": "hello"}]
    messages = provider._get_messages_from_data(data)
    assert len(messages) == 1
    assert messages[0]["content"] == "hello"


def test_extract_interaction_user_filter():
    provider = CopilotProvider()
    # User message should be added
    provider._extract_interaction({"role": "user", "content": "hello"}, "test-project")
    assert len(provider.interaction_queue) == 1
    assert provider.interaction_queue[0].role == "user"
    assert provider.interaction_queue[0].project_name == "test-project"

    # Assistant message should be filtered out
    provider._extract_interaction({"role": "assistant", "content": "hi"}, "test-project")
    assert len(provider.interaction_queue) == 1


def test_extract_interaction_internal_loop_filter():
    provider = CopilotProvider()
    # Should skip internal evaluation messages
    provider._extract_interaction({
        "role": "user",
        "content": f"{INTERNAL_SIGNATURE}\nDo something"
    }, "test-project")
    assert len(provider.interaction_queue) == 0


def test_process_file_deduplication(tmp_path):
    provider = CopilotProvider(log_dir=str(tmp_path))
    # Create a test log file
    log_file = tmp_path / "test.json"
    data = {
        "sessionId": "session1",
        "messages": [
            {"role": "user", "content": "hello", "id": "msg1"},
        ]
    }
    log_file.write_text(json.dumps(data))

    # Process the file once
    provider._process_file(str(log_file))
    assert len(provider.interaction_queue) == 1

    # Process the same file again - should not add duplicates
    provider._process_file(str(log_file))
    assert len(provider.interaction_queue) == 1


def test_initialize_historical_logs(tmp_path):
    # Create a log file before initializing the provider
    log_file = tmp_path / "existing.json"
    data = {
        "sessionId": "session1",
        "messages": [
            {"role": "user", "content": "old message", "id": "msg1"},
        ]
    }
    log_file.write_text(json.dumps(data))

    # Isolate cli_log_dir to an empty tmp dir so real CLI logs don't leak in
    cli_dir = tmp_path / "cli"
    cli_dir.mkdir()
    provider = CopilotProvider(log_dir=str(tmp_path), cli_log_dir=str(cli_dir))
    # The historical message should already be in global_processed_ids
    assert len(provider.global_processed_ids) == 1

    # Processing the file should not yield new interactions
    provider._process_file(str(log_file))
    assert len(provider.interaction_queue) == 0


def test_project_name_detection(tmp_path):
    provider = CopilotProvider(log_dir=str(tmp_path))

    # File directly in log_dir -> global
    global_log = tmp_path / "chat.json"
    global_log.write_text(json.dumps({
        "sessionId": "s1",
        "messages": [{"role": "user", "content": "global msg", "id": "g1"}]
    }))
    provider._process_file(str(global_log))
    assert provider.interaction_queue[0].project_name == "global"

    # File in a subdirectory -> project name from directory
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    project_log = project_dir / "chat.json"
    project_log.write_text(json.dumps({
        "sessionId": "s2",
        "messages": [{"role": "user", "content": "project msg", "id": "p1"}]
    }))
    provider._process_file(str(project_log))
    assert provider.interaction_queue[1].project_name == "my-project"


def test_initialize_cli_historical_logs(tmp_path):
    """CLI historical log events are marked seen so they are not reprocessed."""
    cli_dir = tmp_path / "cli"
    session_dir = cli_dir / "session1"
    session_dir.mkdir(parents=True)
    events_file = session_dir / "events.jsonl"
    events_file.write_text(
        '{"type":"user.message","id":"msg1","data":{"content":"hello"}}\n'
        '{"type":"user.message","id":"msg2","data":{"content":"world"}}\n'
        '{"type":"assistant.message","id":"a1","data":{"content":"hi"}}\n'
    )

    provider = CopilotProvider(log_dir=str(tmp_path / "chat"), cli_log_dir=str(cli_dir))
    assert "msg1" in provider.global_processed_ids
    assert "msg2" in provider.global_processed_ids
    assert "a1" not in provider.global_processed_ids  # assistant events not tracked


def test_initialize_cli_historical_logs_bad_line(tmp_path):
    """A corrupt JSONL line does not abort processing of subsequent valid lines."""
    cli_dir = tmp_path / "cli"
    session_dir = cli_dir / "session1"
    session_dir.mkdir(parents=True)
    events_file = session_dir / "events.jsonl"
    events_file.write_text(
        '{"type":"user.message","id":"msg1","data":{"content":"before corrupt"}}\n'
        'NOT_VALID_JSON\n'
        '{"type":"user.message","id":"msg3","data":{"content":"after corrupt"}}\n'
    )

    provider = CopilotProvider(log_dir=str(tmp_path / "chat"), cli_log_dir=str(cli_dir))
    assert "msg1" in provider.global_processed_ids
    assert "msg3" in provider.global_processed_ids


def test_parse_cli_file_malformed_timestamp(tmp_path):
    """Malformed timestamps fall back to now() without raising."""
    cli_dir = tmp_path / "cli"
    session_dir = cli_dir / "session1"
    session_dir.mkdir(parents=True)
    events_file = session_dir / "events.jsonl"
    events_file.write_text(
        '{"type":"session.start","data":{"context":{"cwd":"/projects/myapp"}}}\n'
        '{"type":"user.message","id":"msg1","timestamp":"not-a-timestamp",'
        '"data":{"content":"hello"}}\n'
        '{"type":"user.message","id":"msg2",'
        '"data":{"content":"no timestamp key"}}\n'
    )

    provider = CopilotProvider(log_dir=str(tmp_path / "chat"), cli_log_dir=str(cli_dir))
    # Mark as unseen so _parse_cli_file will process them
    provider.global_processed_ids.discard("msg1")
    provider.global_processed_ids.discard("msg2")

    provider._parse_cli_file(str(events_file))
    contents = [i.content for i in provider.interaction_queue]
    assert "hello" in contents
    assert "no timestamp key" in contents


def test_get_cli_project_name(tmp_path):
    """Project name derived from session.start cwd field."""
    cli_dir = tmp_path / "cli"
    session_dir = cli_dir / "session1"
    session_dir.mkdir(parents=True)
    events_file = session_dir / "events.jsonl"
    events_file.write_text(
        '{"type":"session.start","data":{"context":{"cwd":"/home/user/myapp"}}}\n'
        '{"type":"user.message","id":"m1","data":{"content":"hi"}}\n'
    )

    provider = CopilotProvider(log_dir=str(tmp_path / "chat"), cli_log_dir=str(cli_dir))
    name = provider._get_cli_project_name(str(events_file))
    assert name == "myapp"
