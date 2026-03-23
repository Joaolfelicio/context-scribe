import subprocess
import logging
from typing import Optional
import json
import re

from context_scribe.observer.provider import Interaction
from context_scribe.evaluator.llm import RuleOutput, INTERNAL_SIGNATURE

logger = logging.getLogger(__name__)


class ClaudeEvaluator:
    """Evaluator that uses Claude Code CLI for headless rule extraction."""

    def __init__(self):
        try:
            subprocess.run(["claude", "--version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("Claude Code CLI not found.")

    def evaluate_interaction(self, interaction: Interaction, existing_global: str = "", existing_project: str = "") -> Optional[RuleOutput]:
        prompt = f"""{INTERNAL_SIGNATURE}
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

CRITICAL: **Do not return rules from the other scope.** Return ONE single clean list for the determined scope. Output ONLY the JSON object or NO_RULE."""

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
