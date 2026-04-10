from __future__ import annotations

from context_scribe.models.evaluator_models import RuleOutput, INTERNAL_SIGNATURE
from .gemini_cli_llm import GeminiCliEvaluator
from .claude_llm import ClaudeEvaluator
from .copilot_llm import CopilotEvaluator
from .base_evaluator import BaseEvaluator

EVALUATOR_REGISTRY: dict[str, type[BaseEvaluator]] = {
    "gemini": GeminiCliEvaluator,
    "claude": ClaudeEvaluator,
    "copilot": CopilotEvaluator,
}

# Register AnthropicEvaluator only if the SDK is available
try:
    from .anthropic_llm import AnthropicEvaluator
    EVALUATOR_REGISTRY["anthropic"] = AnthropicEvaluator
except ImportError:
    pass


def get_evaluator(name: str) -> BaseEvaluator:
    """Return an evaluator instance by name. Raises ValueError for unknown names."""
    cls = EVALUATOR_REGISTRY.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown evaluator '{name}'. "
            f"Available: {', '.join(sorted(EVALUATOR_REGISTRY))}"
        )
    return cls()


__all__ = [
    "RuleOutput", "INTERNAL_SIGNATURE",
    "GeminiCliEvaluator", "ClaudeEvaluator", "CopilotEvaluator",
    "BaseEvaluator", "EVALUATOR_REGISTRY", "get_evaluator",
]
