import subprocess
import logging
from context_scribe.evaluator.base_evaluator import BaseEvaluator

logger = logging.getLogger(__name__)

class GeminiCliEvaluator(BaseEvaluator):
    """Evaluator that uses Gemini CLI for headless rule extraction."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        try:
            subprocess.run(["gemini", "--version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("Gemini CLI not found.")

    def _execute_cli(self, prompt: str) -> str:
        # Prompt is passed via stdin to avoid shell argument length limits
        result = subprocess.run(
            [
                "gemini",
                "--model", "gemini-2.5-flash-lite",
                "--output-format", "json"
            ],
            input=prompt,
            capture_output=True, 
            text=True,
            check=False,
            timeout=120
        )
        if result.returncode != 0:
            logger.debug(f"Gemini CLI error (code {result.returncode}): {result.stderr}")
        return result.stdout.strip()
