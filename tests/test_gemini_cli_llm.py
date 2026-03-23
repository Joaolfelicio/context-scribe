import json
from unittest.mock import MagicMock, patch
import subprocess
from context_scribe.evaluator.gemini_cli_llm import GeminiCliEvaluator
from context_scribe.observer.provider import Interaction

def test_evaluator_no_rule():
    evaluator = GeminiCliEvaluator()
    mock_interaction = Interaction(timestamp=None, role="user", content="hello", project_name="test")
    
    with patch("subprocess.run") as mock_run:
        mock_res = MagicMock()
        mock_res.stdout = '{"response": "NO_RULE"}'
        mock_run.return_value = mock_res
        
        result = evaluator.evaluate_interaction(mock_interaction)
        assert result is None

def test_evaluator_extract_rule_json():
    evaluator = GeminiCliEvaluator()
    mock_interaction = Interaction(timestamp=None, role="user", content="Always use tabs", project_name="test")
    
    with patch("subprocess.run") as mock_run:
        mock_res = MagicMock()
        mock_res.stdout = '{"response": "{\\"scope\\": \\"GLOBAL\\", \\"rules\\": \\"- Always use tabs\\"}"}'
        mock_run.return_value = mock_res
        
        result = evaluator.evaluate_interaction(mock_interaction)
        assert result.scope == "GLOBAL"
        assert result.content == "- Always use tabs"

def test_evaluator_list_format_handling():
    evaluator = GeminiCliEvaluator()
    mock_interaction = Interaction(timestamp=None, role="user", content="Rules", project_name="test")
    
    with patch("subprocess.run") as mock_run:
        mock_res = MagicMock()
        mock_res.stdout = '{"response": "{\\"scope\\": \\"PROJECT\\", \\"rules\\": [\\"Rule 1\\", \\"Rule 2\\"]}"}'
        mock_run.return_value = mock_res
        
        result = evaluator.evaluate_interaction(mock_interaction)
        assert result.scope == "PROJECT"
        assert "Rule 1\nRule 2" in result.content

def test_evaluator_timeout_handling():
    evaluator = GeminiCliEvaluator()
    mock_interaction = Interaction(timestamp=None, role="user", content="Slow", project_name="test")
    
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["cmd"], 120)):
        result = evaluator.evaluate_interaction(mock_interaction)
        assert result is None
