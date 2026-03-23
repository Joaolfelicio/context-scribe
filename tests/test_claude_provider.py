import json
from context_scribe.observer.claude_provider import ClaudeProvider


def test_get_messages_from_file_jsonl_format(tmp_path):
    """Test parsing standard JSONL lines."""
    log_file = tmp_path / "conversation.jsonl"
    lines = [
        json.dumps({"role": "user", "content": "hello"}),
        json.dumps({"role": "assistant", "content": "hi there"}),
    ]
    log_file.write_text("\n".join(lines))

    provider = ClaudeProvider(log_dir=str(tmp_path))
    messages = provider._get_messages_from_file(log_file)
    assert len(messages) == 2
    assert messages[0][1]["role"] == "user"
    assert messages[0][1]["content"] == "hello"
    assert messages[1][1]["role"] == "assistant"


def test_get_messages_from_file_message_object(tmp_path):
    """Test parsing JSONL with nested message objects."""
    log_file = tmp_path / "conversation.jsonl"
    lines = [
        json.dumps({"type": "human", "message": {"content": "hello world"}}),
        json.dumps({"type": "assistant", "message": {"content": "response"}}),
    ]
    log_file.write_text("\n".join(lines))

    provider = ClaudeProvider(log_dir=str(tmp_path))
    messages = provider._get_messages_from_file(log_file)
    assert len(messages) == 2
    # The nested message should be extracted, with role from outer type
    assert messages[0][1]["role"] == "human"
    assert messages[0][1]["content"] == "hello world"


def test_get_messages_from_file_simple_format(tmp_path):
    """Test parsing simple role/content format."""
    log_file = tmp_path / "conversation.jsonl"
    lines = [
        json.dumps({"role": "user", "content": "Use tabs for indentation"}),
    ]
    log_file.write_text("\n".join(lines))

    provider = ClaudeProvider(log_dir=str(tmp_path))
    messages = provider._get_messages_from_file(log_file)
    assert len(messages) == 1
    assert messages[0][1]["content"] == "Use tabs for indentation"


def test_get_messages_from_file_skips_blank_lines(tmp_path):
    """Test that blank lines are skipped."""
    log_file = tmp_path / "conversation.jsonl"
    content = json.dumps({"role": "user", "content": "hello"}) + "\n\n\n" + json.dumps({"role": "assistant", "content": "hi"})
    log_file.write_text(content)

    provider = ClaudeProvider(log_dir=str(tmp_path))
    messages = provider._get_messages_from_file(log_file)
    assert len(messages) == 2


def test_get_messages_from_file_skips_invalid_json(tmp_path):
    """Test that invalid JSON lines are skipped."""
    log_file = tmp_path / "conversation.jsonl"
    content = "not valid json\n" + json.dumps({"role": "user", "content": "hello"})
    log_file.write_text(content)

    provider = ClaudeProvider(log_dir=str(tmp_path))
    messages = provider._get_messages_from_file(log_file)
    assert len(messages) == 1


def test_extract_interaction_user_filter():
    """Test that only user/human messages are added to queue."""
    provider = ClaudeProvider(log_dir="/nonexistent")

    # User message should be added
    provider._extract_interaction({"role": "user", "content": "hello"}, "test-project")
    assert len(provider.interaction_queue) == 1
    assert provider.interaction_queue[0].role == "user"
    assert provider.interaction_queue[0].project_name == "test-project"

    # Human role should be treated as user
    provider._extract_interaction({"role": "human", "content": "world"}, "test-project")
    assert len(provider.interaction_queue) == 2
    assert provider.interaction_queue[1].role == "user"

    # Assistant message should be filtered out
    provider._extract_interaction({"role": "assistant", "content": "hi"}, "test-project")
    assert len(provider.interaction_queue) == 2


def test_extract_interaction_internal_loop_filter():
    """Test that context-scribe internal evaluation messages are filtered."""
    provider = ClaudeProvider(log_dir="/nonexistent")

    # Should skip internal evaluation messages
    provider._extract_interaction({
        "role": "user",
        "content": "--- CONTEXT-SCRIBE-INTERNAL-EVALUATION ---\nDo something"
    }, "test-project")
    assert len(provider.interaction_queue) == 0

    # Also test mixed-case variant (case-insensitive filter)
    provider._extract_interaction({
        "role": "user",
        "content": "--- Context-Scribe-Internal-Evaluation ---\nDo something"
    }, "test-project")
    assert len(provider.interaction_queue) == 0


def test_process_file_deduplication(tmp_path):
    """Test that processing the same file twice doesn't duplicate interactions."""
    log_dir = tmp_path / "projects"
    log_dir.mkdir()
    log_file = log_dir / "conversation.jsonl"
    log_file.write_text(json.dumps({"role": "user", "content": "hello"}))

    provider = ClaudeProvider(log_dir=str(log_dir))
    # Clear historical state so messages are treated as new
    provider.global_processed_ids.clear()

    provider._process_file(str(log_file))
    assert len(provider.interaction_queue) == 1

    # Process same file again - should not duplicate
    provider._process_file(str(log_file))
    assert len(provider.interaction_queue) == 1


def test_initialize_historical_logs(tmp_path):
    """Test that historical logs are marked as processed at startup."""
    log_dir = tmp_path / "projects"
    project_dir = log_dir / "my-project"
    project_dir.mkdir(parents=True)
    log_file = project_dir / "conversation.jsonl"
    log_file.write_text(json.dumps({"role": "user", "content": "existing message"}))

    provider = ClaudeProvider(log_dir=str(log_dir))
    # Historical messages should be tracked
    assert len(provider.global_processed_ids) == 1

    # Processing the file should not yield new interactions
    provider._process_file(str(log_file))
    assert len(provider.interaction_queue) == 0


def test_project_name_detection(tmp_path):
    """Test project name extraction from directory structure."""
    log_dir = tmp_path / "projects"
    project_dir = log_dir / "my-cool-project"
    project_dir.mkdir(parents=True)
    log_file = project_dir / "conversation.jsonl"
    log_file.write_text(json.dumps({"role": "user", "content": "hello"}))

    provider = ClaudeProvider(log_dir=str(log_dir))
    provider.global_processed_ids.clear()

    provider._process_file(str(log_file))
    assert len(provider.interaction_queue) == 1
    assert provider.interaction_queue[0].project_name == "my-cool-project"


def test_project_name_global_for_root_files(tmp_path):
    """Test that files in the root log dir get 'global' project name."""
    log_dir = tmp_path / "projects"
    log_dir.mkdir(parents=True)
    log_file = log_dir / "conversation.jsonl"
    log_file.write_text(json.dumps({"role": "user", "content": "hello"}))

    provider = ClaudeProvider(log_dir=str(log_dir))
    provider.global_processed_ids.clear()

    provider._process_file(str(log_file))
    assert len(provider.interaction_queue) == 1
    assert provider.interaction_queue[0].project_name == "global"


def test_extract_interaction_list_content():
    """Test handling of list-type content (multi-part messages)."""
    provider = ClaudeProvider(log_dir="/nonexistent")
    provider._extract_interaction({
        "role": "user",
        "content": [
            {"text": "Part 1"},
            {"text": "Part 2"}
        ]
    }, "test-project")
    assert len(provider.interaction_queue) == 1
    assert "Part 1" in provider.interaction_queue[0].content
    assert "Part 2" in provider.interaction_queue[0].content
