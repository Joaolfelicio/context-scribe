import json
import os
from pathlib import Path
from context_scribe.observer.gemini_provider import GeminiProvider

def test_get_messages_from_data_dict_messages():
    provider = GeminiProvider()
    data = {"messages": [{"id": "1", "text": "hello"}]}
    messages = provider._get_messages_from_data(data)
    assert len(messages) == 1
    assert messages[0]["text"] == "hello"

def test_get_messages_from_data_list():
    provider = GeminiProvider()
    data = [{"message": "hello"}]
    messages = provider._get_messages_from_data(data)
    assert len(messages) == 1
    assert messages[0]["message"] == "hello"

def test_extract_interaction_user_filter():
    provider = GeminiProvider()
    # User message should be added
    provider._extract_interaction({"type": "user", "message": "hello"}, "test-project")
    assert len(provider.interaction_queue) == 1
    assert provider.interaction_queue[0].role == "user"
    assert provider.interaction_queue[0].project_name == "test-project"
    
    # Gemini message should be filtered out
    provider._extract_interaction({"type": "gemini", "message": "hi"}, "test-project")
    assert len(provider.interaction_queue) == 1

def test_extract_interaction_internal_loop_filter():
    provider = GeminiProvider()
    # Should skip internal evaluation messages
    provider._extract_interaction({
        "type": "user", 
        "message": "--- CONTEXT-SCRIBE-INTERNAL-EVALUATION ---\nDo something"
    }, "test-project")
    assert len(provider.interaction_queue) == 0
