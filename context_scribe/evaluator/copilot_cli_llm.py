import json
import subprocess
import logging
from context_scribe.evaluator.base_evaluator import BaseEvaluator

logger = logging.getLogger(__name__)

class CopilotCliEvaluator(BaseEvaluator):
    """Evaluator that uses GitHub Copilot CLI for rule extraction."""

    def __init__(self):
        super().__init__()
        try:
            # Check if copilot command is available
            subprocess.run(["copilot", "--version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("GitHub Copilot CLI ('copilot' command) not found.")

    def _execute_cli(self, prompt: str) -> str:
        """
        Executes 'copilot -p [prompt] --yolo' and extracts the final assistant message.
        """
        try:
            result = subprocess.run(
                [
                    "copilot",
                    "-p", prompt,
                    "--yolo",
                    "--output-format", "json",
                    "-s"
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=120
            )
            
            if result.returncode != 0:
                logger.debug(f"Copilot CLI error (code {result.returncode}): {result.stderr}")
            
            # Copilot CLI in JSON mode outputs JSONL (one JSON object per line)
            # We need to find the line with type "assistant.message"
            lines = result.stdout.strip().splitlines()
            for line in reversed(lines):
                try:
                    data = json.loads(line)
                    if data.get("type") == "assistant.message":
                        content = data.get("data", {}).get("content", "")
                        if content:
                            return content
                except json.JSONDecodeError:
                    continue
            
            # Fallback to the whole stdout if no assistant.message found
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            logger.error("Copilot CLI evaluation timed out.")
            raise
        except Exception as e:
            logger.error(f"Failed to execute Copilot CLI: {e}")
            return ""
