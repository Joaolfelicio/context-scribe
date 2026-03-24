import json
import subprocess
from unittest.mock import MagicMock, patch
from context_scribe.evaluator.copilot_cli_llm import CopilotCliEvaluator
from context_scribe.models.interaction import Interaction

def test_copilot_evaluator_extract_rule_json():
    evaluator = CopilotCliEvaluator()
    mock_interaction = Interaction(timestamp=None, role="user", content="Always use tabs", project_name="test")
    
    with patch("subprocess.run") as mock_run:
        mock_res = MagicMock()
        mock_res.returncode = 0
        # Simulated JSONL response from copilot CLI
        json_obj = {"scope": "GLOBAL", "rules": ["- Always use tabs"], "description": "Tab preference"}
        mock_res.stdout = f'{{"type":"some.event"}}\n{{"type":"assistant.message","data":{{"content":{json.dumps(json.dumps(json_obj))}}}}}'
        mock_run.return_value = mock_res
        
        result = evaluator.evaluate_interaction(mock_interaction)
        assert result is not None
        assert result.scope == "GLOBAL"
        assert result.content == "- Always use tabs"

def test_copilot_evaluator_no_rule():
    evaluator = CopilotCliEvaluator()
    mock_interaction = Interaction(timestamp=None, role="user", content="hello", project_name="test")
    
    with patch("subprocess.run") as mock_run:
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = "NO_RULE"
        mock_run.return_value = mock_res
        
        result = evaluator.evaluate_interaction(mock_interaction)
        assert result is None

def test_copilot_evaluator_error_handling():
    evaluator = CopilotCliEvaluator()
    mock_interaction = Interaction(timestamp=None, role="user", content="test", project_name="test")
    
    with patch("subprocess.run") as mock_run:
        mock_res = MagicMock()
        mock_res.returncode = 1
        mock_res.stderr = "Error occurred"
        mock_run.return_value = mock_res
        
        result = evaluator.evaluate_interaction(mock_interaction)
        assert result is None
