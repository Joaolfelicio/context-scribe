import json
from context_scribe.observer.copilot_provider import CopilotProvider
from context_scribe.evaluator.models import INTERNAL_SIGNATURE


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

    provider = CopilotProvider(log_dir=str(tmp_path))
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
