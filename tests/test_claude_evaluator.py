import json
from unittest.mock import MagicMock, patch
import subprocess
from context_scribe.evaluator.claude_llm import ClaudeEvaluator
from context_scribe.models.interaction import Interaction


def test_claude_evaluator_no_rule():
    evaluator = ClaudeEvaluator()
    mock_interaction = Interaction(timestamp=None, role="user", content="hello", project_name="test")

    with patch("subprocess.run") as mock_run:
        mock_res = MagicMock()
        mock_res.stdout = '{"result": "NO_RULE"}'
        mock_run.return_value = mock_res

        result = evaluator.evaluate_interaction(mock_interaction)
        assert result is None


def test_claude_evaluator_extract_rule_json():
    evaluator = ClaudeEvaluator()
    mock_interaction = Interaction(timestamp=None, role="user", content="Always use tabs", project_name="test")

    with patch("subprocess.run") as mock_run:
        mock_res = MagicMock()
        mock_res.stdout = json.dumps({
            "result": json.dumps({"scope": "GLOBAL", "description": "Added tab rule", "rules": "- Always use tabs"})
        })
        mock_run.return_value = mock_res

        result = evaluator.evaluate_interaction(mock_interaction)
        assert result.scope == "GLOBAL"
        assert result.content == "- Always use tabs"
        assert result.description == "Added tab rule"


def test_claude_evaluator_list_format_handling():
    evaluator = ClaudeEvaluator()
    mock_interaction = Interaction(timestamp=None, role="user", content="Rules", project_name="test")

    with patch("subprocess.run") as mock_run:
        mock_res = MagicMock()
        mock_res.stdout = json.dumps({
            "result": json.dumps({"scope": "PROJECT", "rules": ["Rule 1", "Rule 2"]})
        })
        mock_run.return_value = mock_res

        result = evaluator.evaluate_interaction(mock_interaction)
        assert result.scope == "PROJECT"
        assert "Rule 1\nRule 2" in result.content


def test_claude_evaluator_timeout_handling():
    evaluator = ClaudeEvaluator()
    mock_interaction = Interaction(timestamp=None, role="user", content="Slow", project_name="test")

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["cmd"], 120)):
        result = evaluator.evaluate_interaction(mock_interaction)
        assert result is None


def test_claude_evaluator_uses_claude_cli():
    evaluator = ClaudeEvaluator()
    mock_interaction = Interaction(timestamp=None, role="user", content="test", project_name="test")

    with patch("subprocess.run") as mock_run:
        mock_res = MagicMock()
        mock_res.stdout = "NO_RULE"
        mock_run.return_value = mock_res

        evaluator.evaluate_interaction(mock_interaction)

        # Verify claude CLI was called with correct args
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "claude"
        assert "-p" in call_args
        assert "--output-format" in call_args
        assert "json" in call_args
        assert "--no-session-persistence" in call_args
        # Verify prompt is passed via stdin (input kwarg), not as positional arg
        assert "input" in mock_run.call_args[1]


def test_claude_evaluator_fallback_parsing():
    evaluator = ClaudeEvaluator()
    mock_interaction = Interaction(timestamp=None, role="user", content="msg", project_name="p")

    with patch("subprocess.run") as mock_run:
        mock_res = MagicMock()
        mock_res.stdout = 'The scope is GLOBAL and here are the rules'
        mock_run.return_value = mock_res

        result = evaluator.evaluate_interaction(mock_interaction)
        assert result is not None
        assert result.scope == "GLOBAL"


def test_claude_evaluator_plain_text_result():
    """Claude sometimes returns plain text without JSON wrapper."""
    evaluator = ClaudeEvaluator()
    mock_interaction = Interaction(timestamp=None, role="user", content="use spaces", project_name="test")

    with patch("subprocess.run") as mock_run:
        mock_res = MagicMock()
        # Plain text with embedded JSON (no wrapper)
        mock_res.stdout = '{"scope": "GLOBAL", "description": "Added spacing rule", "rules": "- Use 4 spaces for indentation"}'
        mock_run.return_value = mock_res

        result = evaluator.evaluate_interaction(mock_interaction)
        assert result is not None
        assert result.scope == "GLOBAL"
        assert "4 spaces" in result.content


def test_claude_evaluator_strips_code_fences():
    """Claude often wraps JSON in markdown code fences."""
    evaluator = ClaudeEvaluator()
    mock_interaction = Interaction(timestamp=None, role="user", content="use tabs", project_name="test")

    with patch("subprocess.run") as mock_run:
        mock_res = MagicMock()
        mock_res.stdout = json.dumps({
            "result": '```json\n{"scope": "GLOBAL", "description": "Added tab rule", "rules": "- Always use tabs"}\n```'
        })
        mock_run.return_value = mock_res

        result = evaluator.evaluate_interaction(mock_interaction)
        assert result is not None
        assert result.scope == "GLOBAL"
        assert "tabs" in result.content
