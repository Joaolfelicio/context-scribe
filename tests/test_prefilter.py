import json
from unittest.mock import MagicMock, patch
import subprocess
from context_scribe.evaluator.llm import (
    Evaluator, PrefilterResult, PrefilterMetrics, PREFILTER_PROMPT_TEMPLATE
)
from context_scribe.evaluator.claude_llm import ClaudeEvaluator
from context_scribe.observer.provider import Interaction


# --- PrefilterResult tests ---

def test_prefilter_result_should_skip_no_rule_high_confidence():
    result = PrefilterResult(contains_rule=False, confidence=0.95)
    assert result.should_skip_full_eval is True


def test_prefilter_result_should_not_skip_no_rule_low_confidence():
    result = PrefilterResult(contains_rule=False, confidence=0.5)
    assert result.should_skip_full_eval is False


def test_prefilter_result_should_not_skip_no_rule_at_threshold():
    result = PrefilterResult(contains_rule=False, confidence=0.8)
    assert result.should_skip_full_eval is False


def test_prefilter_result_should_not_skip_has_rule():
    result = PrefilterResult(contains_rule=True, confidence=0.95)
    assert result.should_skip_full_eval is False


# --- PrefilterMetrics tests ---

def test_metrics_initial_state():
    metrics = PrefilterMetrics()
    assert metrics.total_interactions == 0
    assert metrics.prefilter_passed == 0
    assert metrics.prefilter_skipped == 0
    assert metrics.prefilter_errors == 0
    assert metrics.skip_rate == 0.0


def test_metrics_record_skip():
    metrics = PrefilterMetrics()
    result = PrefilterResult(contains_rule=False, confidence=0.95)
    metrics.record_result(result)
    assert metrics.total_interactions == 1
    assert metrics.prefilter_skipped == 1
    assert metrics.prefilter_passed == 0
    assert metrics.skip_rate == 1.0


def test_metrics_record_pass():
    metrics = PrefilterMetrics()
    result = PrefilterResult(contains_rule=True, confidence=0.9)
    metrics.record_result(result)
    assert metrics.total_interactions == 1
    assert metrics.prefilter_passed == 1
    assert metrics.prefilter_skipped == 0


def test_metrics_record_error_passes_through():
    metrics = PrefilterMetrics()
    metrics.record_result(None)
    assert metrics.total_interactions == 1
    assert metrics.prefilter_errors == 1
    assert metrics.prefilter_passed == 1  # errors pass through


def test_metrics_skip_rate():
    metrics = PrefilterMetrics()
    metrics.record_result(PrefilterResult(contains_rule=False, confidence=0.95))
    metrics.record_result(PrefilterResult(contains_rule=True, confidence=0.9))
    metrics.record_result(PrefilterResult(contains_rule=False, confidence=0.95))
    metrics.record_result(PrefilterResult(contains_rule=False, confidence=0.5))  # low confidence, passes
    assert metrics.total_interactions == 4
    assert metrics.prefilter_skipped == 2
    assert metrics.skip_rate == 0.5


# --- Gemini Evaluator prefilter tests ---

def test_gemini_pre_evaluate_no_rule():
    evaluator = Evaluator()
    interaction = Interaction(timestamp=None, role="user", content="Fix this bug please", project_name="test")

    with patch("subprocess.run") as mock_run:
        mock_res = MagicMock()
        mock_res.stdout = json.dumps({
            "response": json.dumps({"contains_rule": False, "confidence": 0.95})
        })
        mock_run.return_value = mock_res

        result = evaluator.pre_evaluate(interaction)
        assert result is not None
        assert result.contains_rule is False
        assert result.confidence == 0.95
        assert result.should_skip_full_eval is True


def test_gemini_pre_evaluate_has_rule():
    evaluator = Evaluator()
    interaction = Interaction(timestamp=None, role="user", content="Always use tabs", project_name="test")

    with patch("subprocess.run") as mock_run:
        mock_res = MagicMock()
        mock_res.stdout = json.dumps({
            "response": json.dumps({"contains_rule": True, "confidence": 0.9})
        })
        mock_run.return_value = mock_res

        result = evaluator.pre_evaluate(interaction)
        assert result is not None
        assert result.contains_rule is True
        assert result.should_skip_full_eval is False


def test_gemini_pre_evaluate_timeout():
    evaluator = Evaluator()
    interaction = Interaction(timestamp=None, role="user", content="test", project_name="test")

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["cmd"], 30)):
        result = evaluator.pre_evaluate(interaction)
        assert result is None


def test_gemini_pre_evaluate_unparseable_response():
    evaluator = Evaluator()
    interaction = Interaction(timestamp=None, role="user", content="test", project_name="test")

    with patch("subprocess.run") as mock_run:
        mock_res = MagicMock()
        mock_res.stdout = "garbage response"
        mock_run.return_value = mock_res

        result = evaluator.pre_evaluate(interaction)
        assert result is None


def test_gemini_evaluate_skips_when_prefilter_says_no():
    evaluator = Evaluator()
    interaction = Interaction(timestamp=None, role="user", content="Fix bug", project_name="test")

    with patch("subprocess.run") as mock_run:
        # First call: prefilter returns no rule
        mock_prefilter = MagicMock()
        mock_prefilter.stdout = json.dumps({
            "response": json.dumps({"contains_rule": False, "confidence": 0.95})
        })
        mock_run.return_value = mock_prefilter

        result = evaluator.evaluate_interaction(interaction)
        assert result is None
        # Only 1 subprocess call (prefilter), not 2 (prefilter + full eval)
        assert mock_run.call_count == 1
        assert evaluator.metrics.prefilter_skipped == 1


def test_gemini_evaluate_proceeds_when_prefilter_says_yes():
    evaluator = Evaluator()
    interaction = Interaction(timestamp=None, role="user", content="Always use tabs", project_name="test")

    with patch("subprocess.run") as mock_run:
        # Prefilter says yes, full eval returns a rule
        mock_prefilter = MagicMock()
        mock_prefilter.stdout = json.dumps({
            "response": json.dumps({"contains_rule": True, "confidence": 0.9})
        })
        mock_full = MagicMock()
        mock_full.stdout = json.dumps({
            "response": json.dumps({"scope": "GLOBAL", "rules": "- Always use tabs", "description": "Tab rule"})
        })
        mock_run.side_effect = [mock_prefilter, mock_full]

        result = evaluator.evaluate_interaction(interaction)
        assert result is not None
        assert result.scope == "GLOBAL"
        assert mock_run.call_count == 2
        assert evaluator.metrics.prefilter_passed == 1


def test_gemini_evaluate_skip_prefilter_flag():
    evaluator = Evaluator(skip_prefilter=True)
    interaction = Interaction(timestamp=None, role="user", content="Always use tabs", project_name="test")

    with patch("subprocess.run") as mock_run:
        mock_res = MagicMock()
        mock_res.stdout = json.dumps({
            "response": json.dumps({"scope": "GLOBAL", "rules": "- Always use tabs", "description": "Tab rule"})
        })
        mock_run.return_value = mock_res

        result = evaluator.evaluate_interaction(interaction)
        assert result is not None
        # Only 1 call (full eval), no prefilter call
        assert mock_run.call_count == 1
        assert evaluator.metrics.total_interactions == 0  # metrics not tracked when skipped


# --- Claude Evaluator prefilter tests ---

def test_claude_pre_evaluate_no_rule():
    evaluator = ClaudeEvaluator()
    interaction = Interaction(timestamp=None, role="user", content="Explain async/await", project_name="test")

    with patch("subprocess.run") as mock_run:
        mock_res = MagicMock()
        mock_res.stdout = json.dumps({
            "result": json.dumps({"contains_rule": False, "confidence": 0.92})
        })
        mock_run.return_value = mock_res

        result = evaluator.pre_evaluate(interaction)
        assert result is not None
        assert result.contains_rule is False
        assert result.confidence == 0.92
        assert result.should_skip_full_eval is True


def test_claude_pre_evaluate_has_rule():
    evaluator = ClaudeEvaluator()
    interaction = Interaction(timestamp=None, role="user", content="Never use semicolons in TS", project_name="test")

    with patch("subprocess.run") as mock_run:
        mock_res = MagicMock()
        mock_res.stdout = json.dumps({
            "result": json.dumps({"contains_rule": True, "confidence": 0.88})
        })
        mock_run.return_value = mock_res

        result = evaluator.pre_evaluate(interaction)
        assert result is not None
        assert result.contains_rule is True


def test_claude_pre_evaluate_uses_haiku():
    evaluator = ClaudeEvaluator()
    interaction = Interaction(timestamp=None, role="user", content="test", project_name="test")

    with patch("subprocess.run") as mock_run:
        mock_res = MagicMock()
        mock_res.stdout = '{"result": "{\\"contains_rule\\": false, \\"confidence\\": 0.9}"}'
        mock_run.return_value = mock_res

        evaluator.pre_evaluate(interaction)

        call_args = mock_run.call_args[0][0]
        assert "claude" in call_args[0]
        assert "--model" in call_args
        model_idx = call_args.index("--model")
        assert call_args[model_idx + 1] == "haiku"


def test_claude_pre_evaluate_timeout():
    evaluator = ClaudeEvaluator()
    interaction = Interaction(timestamp=None, role="user", content="test", project_name="test")

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["cmd"], 30)):
        result = evaluator.pre_evaluate(interaction)
        assert result is None


def test_claude_evaluate_skips_when_prefilter_says_no():
    evaluator = ClaudeEvaluator()
    interaction = Interaction(timestamp=None, role="user", content="Help with bug", project_name="test")

    with patch("subprocess.run") as mock_run:
        mock_prefilter = MagicMock()
        mock_prefilter.stdout = json.dumps({
            "result": json.dumps({"contains_rule": False, "confidence": 0.95})
        })
        mock_run.return_value = mock_prefilter

        result = evaluator.evaluate_interaction(interaction)
        assert result is None
        assert mock_run.call_count == 1
        assert evaluator.metrics.prefilter_skipped == 1


def test_claude_evaluate_proceeds_when_prefilter_says_yes():
    evaluator = ClaudeEvaluator()
    interaction = Interaction(timestamp=None, role="user", content="Always use tabs", project_name="test")

    with patch("subprocess.run") as mock_run:
        mock_prefilter = MagicMock()
        mock_prefilter.stdout = json.dumps({
            "result": json.dumps({"contains_rule": True, "confidence": 0.9})
        })
        mock_full = MagicMock()
        mock_full.stdout = json.dumps({
            "result": json.dumps({"scope": "GLOBAL", "rules": "- Always use tabs", "description": "Tab rule"})
        })
        mock_run.side_effect = [mock_prefilter, mock_full]

        result = evaluator.evaluate_interaction(interaction)
        assert result is not None
        assert result.scope == "GLOBAL"
        assert mock_run.call_count == 2


def test_claude_evaluate_skip_prefilter_flag():
    evaluator = ClaudeEvaluator(skip_prefilter=True)
    interaction = Interaction(timestamp=None, role="user", content="Always use tabs", project_name="test")

    with patch("subprocess.run") as mock_run:
        mock_res = MagicMock()
        mock_res.stdout = json.dumps({
            "result": json.dumps({"scope": "GLOBAL", "rules": "- Always use tabs", "description": "Tab rule"})
        })
        mock_run.return_value = mock_res

        result = evaluator.evaluate_interaction(interaction)
        assert result is not None
        assert mock_run.call_count == 1


def test_gemini_pre_evaluate_uses_flash_lite():
    evaluator = Evaluator()
    interaction = Interaction(timestamp=None, role="user", content="test", project_name="test")

    with patch("subprocess.run") as mock_run:
        mock_res = MagicMock()
        mock_res.stdout = json.dumps({
            "response": json.dumps({"contains_rule": False, "confidence": 0.9})
        })
        mock_run.return_value = mock_res

        evaluator.pre_evaluate(interaction)

        call_args = mock_run.call_args[0][0]
        assert "gemini" in call_args[0]
        assert "--model" in call_args
        model_idx = call_args.index("--model")
        assert call_args[model_idx + 1] == "gemini-2.0-flash-lite"


def test_prefilter_error_passes_through_to_full_eval():
    """When prefilter errors, should proceed to full evaluation."""
    evaluator = Evaluator()
    interaction = Interaction(timestamp=None, role="user", content="Always use tabs", project_name="test")

    with patch.object(evaluator, 'pre_evaluate', return_value=None):
        with patch("subprocess.run") as mock_run:
            mock_res = MagicMock()
            mock_res.stdout = json.dumps({
                "response": json.dumps({"scope": "GLOBAL", "rules": "- Always use tabs", "description": "Tab rule"})
            })
            mock_run.return_value = mock_res

            result = evaluator.evaluate_interaction(interaction)
            assert result is not None
            assert evaluator.metrics.prefilter_errors == 1
            assert evaluator.metrics.prefilter_passed == 1
