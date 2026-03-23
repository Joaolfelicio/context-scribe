import subprocess
import logging
from context_scribe.evaluator.base_evaluator import BaseEvaluator

logger = logging.getLogger(__name__)

class GeminiCliEvaluator(BaseEvaluator):
    """Evaluator that uses Gemini CLI for headless rule extraction."""

    def __init__(self):
        super().__init__()
        try:
            subprocess.run(["gemini", "--version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("Gemini CLI not found.")

    def _execute_cli(self, prompt: str) -> str:
        # SPEED OPTIMIZED CLI CALL:
        result = subprocess.run(
            [
                "gemini", 
                "--model", "gemini-2.5-flash-lite",
                "--extensions", "",
                "--allowed-mcp-server-names", "",
                "--prompt", prompt, 
                "--output-format", "json"
            ], 
            capture_output=True, 
            text=True,
            check=False,
            stdin=subprocess.DEVNULL,
            timeout=120
        )
        return result.stdout.strip()
