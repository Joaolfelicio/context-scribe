import subprocess
import logging
from typing import Optional, Dict
import json
from dataclasses import dataclass
import re

from context_scribe.observer.provider import Interaction

logger = logging.getLogger(__name__)

INTERNAL_SIGNATURE = "--- CONTEXT-SCRIBE-INTERNAL-EVALUATION ---"

@dataclass
class RuleOutput:
    content: str
    scope: str  # "GLOBAL" or "PROJECT"
    description: str # Concise summary of what changed

class Evaluator:
    def __init__(self):
        try:
            subprocess.run(["gemini", "--version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("Gemini CLI not found.")

    def evaluate_interaction(self, interaction: Interaction, existing_global: str = "", existing_project: str = "") -> Optional[RuleOutput]:
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
   - **GLOBAL (DEFAULT)**: All general coding styles, naming conventions, and personal preferences.
   - **PROJECT (EXCEPTION)**: Strictly for rules unique to "{interaction.project_name}".
2. Rule Enhancement (CRITICAL):
   - Professionalize slang into technical descriptions.
   - Ensure rules are clear directives.
   - Add a tiny inline example for complex rules.
3. Output Format:
   - Output a JSON object with:
     - "scope": "GLOBAL" or "PROJECT"
     - "description": "A very concise (3-5 words) summary of the change."
     - "rules": "The FULL list of consolidated rules. You MUST merge the new rule into the existing list and remove any duplicates or redundant headers. Return ONE single clean list."
4. If NO changes are needed, output exactly: NO_RULE

CRITICAL: **Do not repeat the existing list followed by a new list.** Return only the final, unified state. Output ONLY the JSON object or NO_RULE.
"""
        try:
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
            # and looking for the specific keys we expect.
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
                            
                        # If LLM just outputted conversational noise in the 'rules' key,
                        # check if it contains actual rules (markdown bullets or headers)
                        if len(rules_content) > 0:
                            return RuleOutput(
                                content=rules_content, 
                                scope=str(rule_data["scope"]).upper(), 
                                description=str(desc)
                            )
                except json.JSONDecodeError:
                    pass

            # If no JSON found, check for NO_RULE
            if "NO_RULE" in str(response_text):
                return None
            
            # ABSOLUTELY NO FALLBACK TO RAW TEXT. 
            # If the LLM didn't give us valid JSON, we treat it as no change to avoid corruption.
            logger.error(f"Failed to parse rule extraction from LLM response for {interaction.project_name}")
            return None
            
        except subprocess.TimeoutExpired:
            logger.error(f"Evaluation timed out for {interaction.project_name}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in Evaluator: {e}")
            return None
