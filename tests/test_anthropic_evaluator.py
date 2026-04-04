import importlib
import json
import sys
from unittest.mock import MagicMock, patch

import pytest

from context_scribe.models.interaction import Interaction
from datetime import datetime


def _make_interaction(content="I prefer tabs over spaces"):
    return Interaction(
        timestamp=datetime.now(),
        role="user",
        content=content,
        project_name="test-project",
        metadata={},
    )


@pytest.fixture
def mock_anthropic():
    """Mock the anthropic SDK at sys.modules level, then import AnthropicEvaluator."""
    mock_module = MagicMock()
    mock_client = MagicMock()
    mock_module.Anthropic.return_value = mock_client

    with patch.dict(sys.modules, {"anthropic": mock_module}):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            # Force re-import so the module picks up our mock
            if "context_scribe.evaluator.anthropic_llm" in sys.modules:
                del sys.modules["context_scribe.evaluator.anthropic_llm"]
            from context_scribe.evaluator.anthropic_llm import AnthropicEvaluator
            evaluator = AnthropicEvaluator()
            yield evaluator, mock_client


def test_anthropic_evaluator_extracts_rule(mock_anthropic):
    evaluator, mock_client = mock_anthropic
    rule_json = json.dumps({
        "scope": "GLOBAL",
        "description": "Indentation preference",
        "rules": ["- Use tabs for indentation"],
    })
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = rule_json
    mock_client.messages.create.return_value = MagicMock(content=[text_block])

    result = evaluator.evaluate_interaction(_make_interaction(), "", "")
    assert result is not None
    assert result.scope == "GLOBAL"
    assert "tabs" in result.content


def test_anthropic_evaluator_returns_none_for_no_rule(mock_anthropic):
    evaluator, mock_client = mock_anthropic
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "NO_RULE"
    mock_client.messages.create.return_value = MagicMock(content=[text_block])

    result = evaluator.evaluate_interaction(_make_interaction("hello"), "", "")
    assert result is None


def test_anthropic_evaluator_passes_correct_model(mock_anthropic):
    evaluator, mock_client = mock_anthropic
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "NO_RULE"
    mock_client.messages.create.return_value = MagicMock(content=[text_block])

    evaluator.evaluate_interaction(_make_interaction(), "", "")
    call_kwargs = mock_client.messages.create.call_args[1]
    assert call_kwargs["model"] == "claude-haiku-4-5-20251001"
    assert call_kwargs["max_tokens"] == 4096


def test_anthropic_evaluator_missing_api_key():
    mock_module = MagicMock()
    with patch.dict(sys.modules, {"anthropic": mock_module}):
        with patch.dict("os.environ", {}, clear=True):
            if "context_scribe.evaluator.anthropic_llm" in sys.modules:
                del sys.modules["context_scribe.evaluator.anthropic_llm"]
            from context_scribe.evaluator.anthropic_llm import AnthropicEvaluator
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
                AnthropicEvaluator()
