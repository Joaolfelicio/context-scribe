import subprocess
import logging

from context_scribe.evaluator.base_evaluator import BaseEvaluator

logger = logging.getLogger(__name__)

class ClaudeEvaluator(BaseEvaluator):
    """Evaluator that uses Claude Code CLI for headless rule extraction."""

    def __init__(self):
        super().__init__()
        try:
            subprocess.run(["claude", "--version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("Claude Code CLI not found.")

    def _execute_cli(self, prompt: str) -> str:
        result = subprocess.run(
            [
                "claude",
                "-p",
                "--output-format", "json",
                "--model", "haiku",
                "--no-session-persistence",
            ],
            capture_output=True,
            text=True,
            check=False,
            input=prompt,
            timeout=120
        )
        return result.stdout.strip()
