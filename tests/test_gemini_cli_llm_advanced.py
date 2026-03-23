import pytest
from unittest.mock import MagicMock, patch
from context_scribe.evaluator.gemini_cli_llm import GeminiCliEvaluator
from context_scribe.observer.provider import Interaction

def test_evaluator_malformed_json_fallback():
    evaluator = GeminiCliEvaluator()
    mock_interaction = Interaction(timestamp=None, role="user", content="msg", project_name="p")
    
    with patch("subprocess.run") as mock_run:
        mock_res = MagicMock()
        # Should NOT contain NO_RULE to trigger fallback
        mock_res.stdout = 'The scope is PROJECT and here are the rules'
        mock_run.return_value = mock_res
        
        result = evaluator.evaluate_interaction(mock_interaction)
        assert result is not None
        assert result.scope == "PROJECT"

def test_evaluator_no_json_at_all_global_fallback():
    evaluator = GeminiCliEvaluator()
    mock_interaction = Interaction(timestamp=None, role="user", content="msg", project_name="p")
    
    with patch("subprocess.run") as mock_run:
        mock_res = MagicMock()
        mock_res.stdout = 'Just plain text describing a global change'
        mock_run.return_value = mock_res
        
        result = evaluator.evaluate_interaction(mock_interaction)
        assert result is not None
        assert result.scope == "GLOBAL" # Default fallback when PROJECT not mentioned
