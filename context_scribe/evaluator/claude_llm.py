import subprocess
import logging
from typing import Optional
import json
import re
from pathlib import Path

from context_scribe.observer.provider import Interaction
from context_scribe.evaluator.models import RuleOutput, INTERNAL_SIGNATURE

logger = logging.getLogger(__name__)


class ClaudeEvaluator:
    """Evaluator that uses Claude Code CLI for headless rule extraction."""

    def __init__(self):
        try:
            subprocess.run(["claude", "--version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("Claude Code CLI not found.")

        # Load the prompt template
        template_path = Path(__file__).parent / "prompt_template.md"
        with open(template_path, "r", encoding="utf-8") as f:
            self.prompt_template = f.read()

    def evaluate_interaction(self, interaction: Interaction, existing_global: str = "", existing_project: str = "") -> Optional[RuleOutput]:
        prompt = self.prompt_template.format(
            internal_signature=INTERNAL_SIGNATURE,
            project_name=interaction.project_name,
            existing_global=existing_global,
            existing_project=existing_project,
            content=interaction.content
        )

        try:
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

            output = result.stdout.strip()

            # Claude JSON output has a "result" field containing the response text
            response_text = output
            try:
                data = json.loads(output)
                if isinstance(data, dict):
                    response_text = data.get("result", data.get("response", output))
            except json.JSONDecodeError:
                pass

            # Strip markdown code fences if present (Claude often wraps JSON in ```json ... ```)
            response_text = re.sub(r'```(?:json)?\s*', '', str(response_text)).strip()

            # Try to parse rule JSON from response text using a non-greedy match
            json_match = re.search(r'\{.*?"scope".*?"rules".*?\}', str(response_text), re.DOTALL)
            if json_match:
                try:
                    rule_data = json.loads(json_match.group(0))
                    if "scope" in rule_data and "rules" in rule_data:
                        rules_raw = rule_data["rules"]
                        desc = rule_data.get("description", "Updated rules")

                        if isinstance(rules_raw, list):
                            rules_content = "\n".join([str(r) for r in rules_raw]).strip()
                        else:
                            rules_content = str(rules_raw).strip()

                        if len(rules_content) > 0:
                            return RuleOutput(
                                content=rules_content,
                                scope=str(rule_data["scope"]).upper(),
                                description=str(desc)
                            )
                except json.JSONDecodeError:
                    pass

            if "NO_RULE" in str(response_text):
                return None

            # Fallback for non-JSON responses (robustness)
            text_upper = str(response_text).upper()
            if "PROJECT" in text_upper or "GLOBAL" in text_upper:
                scope = "PROJECT" if "PROJECT" in text_upper else "GLOBAL"
                content = str(response_text)
                return RuleOutput(content=content, scope=scope, description="Extracted via fallback")

            logger.error(f"Failed to parse rule extraction for {interaction.project_name}")
            return None

        except subprocess.TimeoutExpired:
            logger.error(f"Evaluation timed out for {interaction.project_name}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in ClaudeEvaluator: {e}")
            return None
