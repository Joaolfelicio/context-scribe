import json
import logging
import re
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from context_scribe.models.interaction import Interaction
from context_scribe.models.evaluator_models import RuleOutput, INTERNAL_SIGNATURE

logger = logging.getLogger(__name__)

class BaseEvaluator(ABC):
    def __init__(self):
        # Load the prompt template
        template_path = Path(__file__).parent / "prompt_template.md"
        with open(template_path, "r", encoding="utf-8") as f:
            self.prompt_template = f.read()

    @abstractmethod
    def _execute_cli(self, prompt: str) -> str:
        """Executes the specific CLI tool and returns the raw stdout.
        
        Should raise subprocess.TimeoutExpired if the execution takes too long.
        """
        pass

    def evaluate_interaction(self, interaction: Interaction, existing_global: str = "", existing_project: str = "") -> Optional[RuleOutput]:
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
                    # Handle both gemini ("response") and claude ("result"/"response") formats
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
                # Try to find some content if rules are just listed
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
