import logging
import os

import anthropic

from context_scribe.evaluator.base_evaluator import BaseEvaluator

logger = logging.getLogger(__name__)


class AnthropicEvaluator(BaseEvaluator):
    """Evaluator that uses the Anthropic SDK directly for rule extraction.

    Requires the ANTHROPIC_API_KEY environment variable to be set.
    Uses claude-haiku by default for cost efficiency.
    """

    def __init__(self, model: str = "claude-haiku-4-5-20251001"):
        super().__init__()

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY environment variable is required for AnthropicEvaluator."
            )

        self._client = anthropic.Anthropic(api_key=api_key, timeout=120.0)
        self._model = model

    def _execute_cli(self, prompt: str) -> str:
        """Call the Anthropic API instead of a CLI subprocess."""
        message = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        # Extract text from the response content blocks
        return "".join(
            block.text for block in message.content if block.type == "text"
        )
