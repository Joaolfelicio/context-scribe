import json
import logging
import re
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from context_scribe.models.interaction import Interaction
from context_scribe.models.evaluator_models import (
    RuleOutput, INTERNAL_SIGNATURE, PrefilterResult, PrefilterMetrics,
)

logger = logging.getLogger(__name__)

_PREFILTER_TEMPLATE_PATH = Path(__file__).parent / "prefilter_template.md"


def _parse_bool(value) -> bool:
    """Safely parse a boolean that may arrive as a string from LLM JSON."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


class BaseEvaluator(ABC):
    def __init__(self, skip_prefilter: bool = False):
        self.skip_prefilter = skip_prefilter
        self.metrics = PrefilterMetrics()
        # Load the prompt templates
        template_path = Path(__file__).parent / "prompt_template.md"
        with open(template_path, "r", encoding="utf-8") as f:
            self.prompt_template = f.read()
        with open(_PREFILTER_TEMPLATE_PATH, "r", encoding="utf-8") as f:
            self._prefilter_template = f.read()

    @abstractmethod
    def _execute_cli(self, prompt: str) -> str:
        """Executes the specific CLI tool and returns the raw stdout.

        Should raise subprocess.TimeoutExpired if the execution takes too long.
        """
        pass

    def _pre_evaluate(self, interaction: Interaction) -> Optional[PrefilterResult]:
        """Stage 1: Lightweight check to filter non-rule interactions."""
        prompt = self._prefilter_template.format(
            internal_signature=INTERNAL_SIGNATURE,
            content=interaction.content,
        )
        try:
            output = self._execute_cli(prompt)

            # Extract response text from JSON wrapper if present
            response_text = output
            try:
                data = json.loads(output)
                if isinstance(data, dict):
                    response_text = data.get("result", data.get("response", output))
            except json.JSONDecodeError:
                pass

            response_text = re.sub(r'```(?:json)?\s*', '', str(response_text)).strip()

            # Parse the prefilter JSON response
            json_match = re.search(r'\{[^}]*"contains_rule"[^}]*\}', response_text)
            if json_match:
                pf_data = json.loads(json_match.group(0))
                return PrefilterResult(
                    contains_rule=_parse_bool(pf_data.get("contains_rule", True)),
                    confidence=float(pf_data.get("confidence", 0.0)),
                )

            logger.warning("Could not parse prefilter response, passing through to full eval")
            return None

        except subprocess.TimeoutExpired:
            logger.warning("Prefilter timed out, passing through to full eval")
            return None
        except Exception as e:
            logger.warning("Prefilter error: %s, passing through to full eval", e)
            return None

    def evaluate_interaction(self, interaction: Interaction, existing_global: str = "", existing_project: str = "") -> Optional[RuleOutput]:
        # Stage 1: Pre-filter
        if not self.skip_prefilter:
            prefilter_result = self._pre_evaluate(interaction)
            self.metrics.record_result(prefilter_result)
            if prefilter_result and prefilter_result.should_skip_full_eval:
                logger.info(
                    "Prefilter: skipping full eval for %s (confidence=%.2f)",
                    interaction.project_name, prefilter_result.confidence,
                )
                return None

        # Stage 2: Full extraction
        prompt = self.prompt_template.format(
            internal_signature=INTERNAL_SIGNATURE,
            project_name=interaction.project_name,
            existing_global=existing_global,
            existing_project=existing_project,
            content=interaction.content
        )

        try:
            output = self._execute_cli(prompt)

            # Extract response text
            response_text = output
            try:
                data = json.loads(output)
                if isinstance(data, dict):
                    response_text = data.get("result", data.get("response", output))
            except json.JSONDecodeError:
                pass

            # Strip markdown code fences if present
            response_text = re.sub(r'```(?:json)?\s*', '', str(response_text)).strip()

            # Robust JSON extraction
            best_rule_data = None
            start_indices = [i for i, char in enumerate(response_text) if char == '{']
            end_indices = [i for i, char in enumerate(response_text) if char == '}']

            for start in start_indices:
                for end in reversed(end_indices):
                    if end > start:
                        try:
                            candidate = response_text[start:end+1]
                            if '"scope"' in candidate and '"rules"' in candidate:
                                data = json.loads(candidate)
                                if isinstance(data, dict) and "scope" in data and "rules" in data:
                                    best_rule_data = data
                                    break
                        except json.JSONDecodeError:
                            continue
                if best_rule_data:
                    break

            if best_rule_data:
                try:
                    rules_raw = best_rule_data["rules"]
                    desc = best_rule_data.get("description", "Updated rules")

                    if isinstance(rules_raw, list):
                        rules_content = "\n".join([str(r) for r in rules_raw]).strip()
                    else:
                        rules_content = str(rules_raw).strip()

                    if len(rules_content) > 0:
                        return RuleOutput(
                            content=rules_content,
                            scope=str(best_rule_data["scope"]).upper(),
                            description=str(desc)
                        )
                except Exception as e:
                    logger.debug(f"Failed to extract rule fields from JSON: {e}")

            if "NO_RULE" in str(response_text):
                return None

            # Fallback for non-JSON responses
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
            logger.error(f"Unexpected error in {self.__class__.__name__}: {e}")
            return None
