import json
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

from context_scribe.models.evaluator_models import PrefilterResult, PrefilterMetrics
from context_scribe.models.interaction import Interaction
from context_scribe.evaluator.base_evaluator import _parse_bool


def _make_interaction(content="Can you help me fix this bug?"):
    return Interaction(
        timestamp=datetime.now(),
        role="user",
        content=content,
        project_name="test-project",
        metadata={},
    )


# --- PrefilterResult tests ---

def test_prefilter_result_should_skip_no_rule_high_confidence():
    r = PrefilterResult(contains_rule=False, confidence=0.95)
    assert r.should_skip_full_eval is True


def test_prefilter_result_should_not_skip_no_rule_low_confidence():
    r = PrefilterResult(contains_rule=False, confidence=0.5)
    assert r.should_skip_full_eval is False


def test_prefilter_result_should_not_skip_has_rule():
    r = PrefilterResult(contains_rule=True, confidence=0.95)
    assert r.should_skip_full_eval is False


def test_prefilter_result_boundary_confidence():
    r = PrefilterResult(contains_rule=False, confidence=0.8)
    assert r.should_skip_full_eval is False  # must be > 0.8, not >=


# --- PrefilterMetrics tests ---

def test_metrics_record_skip():
    m = PrefilterMetrics()
    m.record_result(PrefilterResult(contains_rule=False, confidence=0.95))
    assert m.prefilter_skipped == 1
    assert m.prefilter_passed == 0
    assert m.skip_rate == 1.0


def test_metrics_record_pass():
    m = PrefilterMetrics()
    m.record_result(PrefilterResult(contains_rule=True, confidence=0.9))
    assert m.prefilter_passed == 1
    assert m.prefilter_skipped == 0
    assert m.skip_rate == 0.0


def test_metrics_record_error():
    m = PrefilterMetrics()
    m.record_result(None)
    assert m.prefilter_errors == 1
    assert m.prefilter_passed == 1  # errors pass through


def test_metrics_skip_rate_empty():
    m = PrefilterMetrics()
    assert m.skip_rate == 0.0


# --- _parse_bool tests ---

def test_parse_bool_true_values():
    assert _parse_bool(True) is True
    assert _parse_bool("true") is True
    assert _parse_bool("True") is True
    assert _parse_bool("1") is True
    assert _parse_bool("yes") is True


def test_parse_bool_false_values():
    assert _parse_bool(False) is False
    assert _parse_bool("false") is False
    assert _parse_bool("False") is False
    assert _parse_bool("0") is False
    assert _parse_bool("no") is False


def test_parse_bool_unknown_values_return_none():
    """Unrecognised or null values return None (fail-open)."""
    assert _parse_bool("") is None
    assert _parse_bool(None) is None
    assert _parse_bool("maybe") is None
    assert _parse_bool(42) is None


# --- BaseEvaluator prefilter integration ---

def test_prefilter_skips_non_rule_interaction():
    """Evaluator skips full eval when prefilter says no rule with high confidence."""
    from context_scribe.evaluator.gemini_cli_llm import GeminiCliEvaluator

    with patch.object(GeminiCliEvaluator, '__init__', lambda self, **kw: None):
        evaluator = GeminiCliEvaluator.__new__(GeminiCliEvaluator)
        # Manually init the base class fields
        from context_scribe.evaluator.base_evaluator import BaseEvaluator
        from pathlib import Path
        evaluator.skip_prefilter = False
        evaluator.metrics = PrefilterMetrics()
        template_path = Path(__file__).parent.parent / "context_scribe" / "evaluator" / "prompt_template.md"
        with open(template_path) as f:
            evaluator.prompt_template = f.read()
        prefilter_path = Path(__file__).parent.parent / "context_scribe" / "evaluator" / "prefilter_template.md"
        with open(prefilter_path) as f:
            evaluator._prefilter_template = f.read()

    prefilter_json = json.dumps({"contains_rule": False, "confidence": 0.95})
    with patch.object(type(evaluator), '_execute_cli', return_value=prefilter_json):
        result = evaluator.evaluate_interaction(_make_interaction(), "", "")

    assert result is None
    assert evaluator.metrics.prefilter_skipped == 1


def test_prefilter_passes_rule_interaction():
    """Evaluator runs full eval when prefilter detects a rule."""
    from context_scribe.evaluator.gemini_cli_llm import GeminiCliEvaluator

    with patch.object(GeminiCliEvaluator, '__init__', lambda self, **kw: None):
        evaluator = GeminiCliEvaluator.__new__(GeminiCliEvaluator)
        evaluator.skip_prefilter = False
        evaluator.metrics = PrefilterMetrics()
        from pathlib import Path
        template_path = Path(__file__).parent.parent / "context_scribe" / "evaluator" / "prompt_template.md"
        with open(template_path) as f:
            evaluator.prompt_template = f.read()
        prefilter_path = Path(__file__).parent.parent / "context_scribe" / "evaluator" / "prefilter_template.md"
        with open(prefilter_path) as f:
            evaluator._prefilter_template = f.read()

    prefilter_json = json.dumps({"contains_rule": True, "confidence": 0.9})
    full_eval_json = json.dumps({
        "scope": "GLOBAL",
        "description": "Tab preference",
        "rules": ["- Use tabs for indentation"],
    })

    call_count = [0]
    def mock_execute(prompt):
        call_count[0] += 1
        if call_count[0] == 1:
            return prefilter_json
        return full_eval_json

    with patch.object(type(evaluator), '_execute_cli', side_effect=mock_execute):
        result = evaluator.evaluate_interaction(
            _make_interaction("Always use tabs"), "", ""
        )

    assert result is not None
    assert result.scope == "GLOBAL"
    assert evaluator.metrics.prefilter_passed == 1


def test_skip_prefilter_flag_bypasses_stage1():
    """With skip_prefilter=True, no prefilter call is made."""
    from context_scribe.evaluator.gemini_cli_llm import GeminiCliEvaluator

    with patch.object(GeminiCliEvaluator, '__init__', lambda self, **kw: None):
        evaluator = GeminiCliEvaluator.__new__(GeminiCliEvaluator)
        evaluator.skip_prefilter = True
        evaluator.metrics = PrefilterMetrics()
        from pathlib import Path
        template_path = Path(__file__).parent.parent / "context_scribe" / "evaluator" / "prompt_template.md"
        with open(template_path) as f:
            evaluator.prompt_template = f.read()
        prefilter_path = Path(__file__).parent.parent / "context_scribe" / "evaluator" / "prefilter_template.md"
        with open(prefilter_path) as f:
            evaluator._prefilter_template = f.read()

    full_eval_json = json.dumps({
        "scope": "GLOBAL",
        "description": "Tab preference",
        "rules": ["- Use tabs"],
    })

    with patch.object(type(evaluator), '_execute_cli', return_value=full_eval_json) as mock_cli:
        result = evaluator.evaluate_interaction(
            _make_interaction("Always use tabs"), "", ""
        )

    # Should only be called once (full eval), not twice (prefilter + full eval)
    assert mock_cli.call_count == 1
    assert result is not None


def test_prefilter_error_passes_through():
    """On prefilter error, pass through to full eval (fail-open)."""
    from context_scribe.evaluator.gemini_cli_llm import GeminiCliEvaluator
    import subprocess

    with patch.object(GeminiCliEvaluator, '__init__', lambda self, **kw: None):
        evaluator = GeminiCliEvaluator.__new__(GeminiCliEvaluator)
        evaluator.skip_prefilter = False
        evaluator.metrics = PrefilterMetrics()
        from pathlib import Path
        template_path = Path(__file__).parent.parent / "context_scribe" / "evaluator" / "prompt_template.md"
        with open(template_path) as f:
            evaluator.prompt_template = f.read()
        prefilter_path = Path(__file__).parent.parent / "context_scribe" / "evaluator" / "prefilter_template.md"
        with open(prefilter_path) as f:
            evaluator._prefilter_template = f.read()

    full_eval_json = json.dumps({
        "scope": "GLOBAL",
        "description": "Tab preference",
        "rules": ["- Use tabs"],
    })

    call_count = [0]
    def mock_execute(prompt):
        call_count[0] += 1
        if call_count[0] == 1:
            raise subprocess.TimeoutExpired("gemini", 30)
        return full_eval_json

    with patch.object(type(evaluator), '_execute_cli', side_effect=mock_execute):
        result = evaluator.evaluate_interaction(
            _make_interaction("Always use tabs"), "", ""
        )

    assert result is not None
    assert evaluator.metrics.prefilter_errors == 1
    assert evaluator.metrics.prefilter_passed == 1  # error counts as pass-through


def test_parse_bool_handles_string_false_from_llm():
    """Regression: bool('false') == True, but _parse_bool('false') == False."""
    assert _parse_bool("false") is False
    # This was the original bug in PR #20
    assert bool("false") is True  # Python's built-in behavior (the bug)
