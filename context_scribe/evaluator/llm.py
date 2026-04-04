import subprocess
import logging
from typing import Optional, Dict
import json
from dataclasses import dataclass, field
import re

from context_scribe.observer.provider import Interaction

logger = logging.getLogger(__name__)

INTERNAL_SIGNATURE = "--- CONTEXT-SCRIBE-INTERNAL-EVALUATION ---"

PREFILTER_PROMPT_TEMPLATE = """{signature}
You are a lightweight classifier. Your ONLY job is to determine whether the following
user-agent interaction contains a NEW persistent preference, project constraint, or
behavioral rule that should be remembered long-term.

Examples of rule-bearing interactions:
- "Always use tabs instead of spaces"
- "For this project, use PostgreSQL not MySQL"
- "Never use semicolons in TypeScript"

Examples of NON-rule interactions:
- "Can you help me fix this bug?"
- "Explain how async/await works"
- "Generate a function that sorts a list"

INTERACTION:
'''
{content}
'''

Respond with ONLY a JSON object:
{{"contains_rule": true/false, "confidence": 0.0-1.0}}
"""


@dataclass
class PrefilterResult:
    """Result of the lightweight pre-evaluation stage."""
    contains_rule: bool
    confidence: float

    @property
    def should_skip_full_eval(self) -> bool:
        """Skip full evaluation if confident there's no rule."""
        return not self.contains_rule and self.confidence > 0.8


@dataclass
class PrefilterMetrics:
    """Tracks prefilter pipeline statistics."""
    total_interactions: int = 0
    prefilter_passed: int = 0
    prefilter_skipped: int = 0
    prefilter_errors: int = 0

    @property
    def skip_rate(self) -> float:
        if self.total_interactions == 0:
            return 0.0
        return self.prefilter_skipped / self.total_interactions

    def record_result(self, result: Optional[PrefilterResult]) -> None:
        self.total_interactions += 1
        if result is None:
            self.prefilter_errors += 1
            self.prefilter_passed += 1  # On error, pass through to full eval
        elif result.should_skip_full_eval:
            self.prefilter_skipped += 1
        else:
            self.prefilter_passed += 1


@dataclass
class RuleOutput:
    content: str
    scope: str  # "GLOBAL" or "PROJECT"
    description: str # Concise summary of what changed

class Evaluator:
    def __init__(self, skip_prefilter: bool = False):
        self.skip_prefilter = skip_prefilter
        self.metrics = PrefilterMetrics()
        try:
            subprocess.run(["gemini", "--version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("Gemini CLI not found.")

    def pre_evaluate(self, interaction: Interaction) -> Optional[PrefilterResult]:
        """Stage 1: Lightweight check using cheapest model to filter non-rule interactions."""
        prompt = PREFILTER_PROMPT_TEMPLATE.format(
            signature=INTERNAL_SIGNATURE,
            content=interaction.content
        )
        try:
            result = subprocess.run(
                [
                    "gemini",
                    "--model", "gemini-2.0-flash-lite",
                    "--extensions", "",
                    "--allowed-mcp-server-names", "",
                    "--prompt", prompt,
                    "--output-format", "json"
                ],
                capture_output=True,
                text=True,
                check=False,
                stdin=subprocess.DEVNULL,
                timeout=30
            )

            output = result.stdout.strip()
            response_text = output
            try:
                data = json.loads(output)
                if isinstance(data, dict):
                    response_text = data.get("response", output)
            except json.JSONDecodeError:
                pass

            # Parse the prefilter JSON response
            json_match = re.search(r'\{[^}]*"contains_rule"[^}]*\}', str(response_text))
            if json_match:
                pf_data = json.loads(json_match.group(0))
                return PrefilterResult(
                    contains_rule=bool(pf_data.get("contains_rule", True)),
                    confidence=float(pf_data.get("confidence", 0.0))
                )

            # If we can't parse, assume it might contain a rule (pass through)
            logger.warning("Could not parse prefilter response, passing through to full eval")
            return None

        except subprocess.TimeoutExpired:
            logger.warning("Prefilter timed out, passing through to full eval")
            return None
        except Exception as e:
            logger.warning(f"Prefilter error: {e}, passing through to full eval")
            return None

    def evaluate_interaction(self, interaction: Interaction, existing_global: str = "", existing_project: str = "") -> Optional[RuleOutput]:
        # Stage 1: Pre-filter
        if not self.skip_prefilter:
            prefilter_result = self.pre_evaluate(interaction)
            self.metrics.record_result(prefilter_result)
            if prefilter_result and prefilter_result.should_skip_full_eval:
                logger.info(f"Prefilter: skipping full eval for {interaction.project_name} "
                           f"(confidence={prefilter_result.confidence:.2f})")
                return None

        # Stage 2: Full extraction
        prompt = f"""
{INTERNAL_SIGNATURE}
You are a 'Persistent Secretary' for an AI agent. Your job is to read user-agent chat logs
and extract long-term behavioral rules, project constraints, or user preferences.

CURRENT PROJECT NAME: {interaction.project_name}

EXISTING GLOBAL RULES:
'''
{existing_global}
'''

EXISTING PROJECT RULES ({interaction.project_name}):
'''
{existing_project}
'''

LATEST USER INTERACTION TO ANALYZE:
'''
{interaction.content}
'''

INSTRUCTIONS:
1. Categorize the rule with a strict **"Global-Unless-Proven-Local"** policy:
   - **GLOBAL (DEFAULT)**: General preferences applying universally.
   - **PROJECT (EXCEPTION)**: Rules unique to "{interaction.project_name}" or explicitly restricted by the user.
2. Rule Hierarchy & Updates (CRITICAL):
   - If the rule is GLOBAL: Merge it ONLY into the **EXISTING GLOBAL RULES** list.
   - If the rule is PROJECT: Merge it ONLY into the **EXISTING PROJECT RULES** list.
   - **Exclusive Scope**: When outputting rules for a scope, **DO NOT** include rules from the other scope.
   - **Preservation Mandate**: You are FORBIDDEN from autonomously deleting rules or deduplicating by moving them between scopes. However, if a new user instruction directly CONTRADICTS an existing rule, you MUST replace the old rule with the new one (**New-Trumps-Old**).
   - **NEVER** mix global rules into the project list, or vice versa.
3. Rule Enhancement:
   - Professionalize slang and add concrete examples.
   - Ensure rules are phrased as clear directives.
4. Output Format:
   - Output a JSON object with:
     - "scope": "GLOBAL" or "PROJECT"
     - "description": "A very concise summary of the change."
     - "rules": "The FULL consolidated list for the CHOSEN SCOPE ONLY, organized into logical Markdown categories (e.g., # Style, # Architecture, # Workflow, etc.). Use clean bullet points."
5. If NO changes are needed, output exactly: NO_RULE

CRITICAL: **Do not return rules from the other scope.** Return ONE single clean list for the determined scope. Output ONLY the JSON object or NO_RULE.
"""
        try:
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
            
            output = result.stdout.strip()
            
            # Extract response text
            response_text = output
            try:
                data = json.loads(output)
                if isinstance(data, dict):
                    response_text = data.get("response", output)
            except json.JSONDecodeError:
                pass

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
            logger.error(f"Unexpected error in Evaluator: {e}")
            return None
