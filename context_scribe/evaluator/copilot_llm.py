import json
import logging
import shutil
import subprocess

from context_scribe.evaluator.base_evaluator import BaseEvaluator

logger = logging.getLogger(__name__)

COPILOT_CLI = shutil.which("copilot") or "copilot"


class CopilotEvaluator(BaseEvaluator):
    """Evaluator that uses the GitHub Copilot CLI for headless rule extraction."""

    def __init__(self):
        super().__init__()
        if not shutil.which("copilot"):
            logger.warning("GitHub Copilot CLI not found in PATH.")

    def _execute_cli(self, prompt: str) -> str:
        result = subprocess.run(
            [COPILOT_CLI, "-p", prompt, "--output-format", "json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        # Output is JSONL; extract the last assistant.message content
        response_text = ""
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                if event.get("type") == "assistant.message":
                    response_text = event.get("data", {}).get("content", "")
            except json.JSONDecodeError:
                continue
        return response_text
