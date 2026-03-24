import json
import logging
import shutil
import subprocess

from context_scribe.evaluator.base_evaluator import BaseEvaluator

logger = logging.getLogger(__name__)


class CopilotEvaluator(BaseEvaluator):
    """Evaluator that uses the GitHub Copilot CLI for headless rule extraction."""

    def __init__(self):
        super().__init__()
        self._cli_path = shutil.which("copilot")
        if not self._cli_path:
            logger.warning(
                "GitHub Copilot CLI not found in PATH. "
                "CopilotEvaluator will fail at evaluation time."
            )

    def _execute_cli(self, prompt: str) -> str:
        cli = self._cli_path or shutil.which("copilot") or "copilot"
        result = subprocess.run(
            [cli, "-p", prompt, "--output-format", "json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        if result.returncode != 0:
            logger.error(
                "Copilot CLI exited with non-zero status %s. Stderr: %s",
                result.returncode,
                (result.stderr or "").strip(),
            )
            return ""
        # Output is a JSONL event stream; extract the last assistant.message content
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
