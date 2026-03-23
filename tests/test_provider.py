import json
import os
from pathlib import Path
from context_scribe.observer.gemini_provider import GeminiProvider
from context_scribe.evaluator.models import INTERNAL_SIGNATURE

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
        "message": f"{INTERNAL_SIGNATURE}\nDo something"
    }, "test-project")
    assert len(provider.interaction_queue) == 0
