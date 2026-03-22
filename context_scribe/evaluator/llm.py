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
   - **GLOBAL (DEFAULT)**: All general coding styles, naming conventions, and personal preferences. If the user says "Always", "I like", "Use X", or doesn't mention a project, it is GLOBAL.
   - **PROJECT (EXCEPTION)**: Strictly for rules unique to "{interaction.project_name}" (e.g., repo-specific tech, file paths, or if the user says "In this project only").
2. Rule Enhancement (CRITICAL):
   - **Professionalize**: Convert informal requests or slang into professional technical specifications.
   - **Clarify**: Translate terms like "spongebob typing" into technical descriptions (e.g., "alternating uppercase and lowercase characters").
   - **Actionable**: Ensure rules are phrased as clear directives for an AI agent.
   - **Examples**: Add a tiny inline example for complex rules (e.g., `LiKe_ThIs`).
3. Output Format:
   - Output a JSON object with:
     - "scope": "GLOBAL" or "PROJECT"
     - "rules": "The ENTIRE consolidated list of rules for that scope, enhanced for clarity and organized into logical Markdown categories (e.g., # Style, # Architecture, # Workflow, etc.)."
4. If NO changes are needed, output exactly: NO_RULE

CRITICAL: **Ambiguity = GLOBAL**. Unless the user explicitly restricts the rule to "{interaction.project_name}", save it globally. Output ONLY the JSON object or NO_RULE.
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
            
            response_text = output
            try:
                data = json.loads(output)
                response_text = data.get("response", output)
            except json.JSONDecodeError:
                pass

            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                try:
                    rule_data = json.loads(json_match.group(0))
                    if "scope" in rule_data and "rules" in rule_data:
                        rules_raw = rule_data["rules"]
                        rules_content = "\n".join([str(r) for r in rules_raw]).strip() if isinstance(rules_raw, list) else str(rules_raw).strip()
                        return RuleOutput(content=rules_content, scope=rule_data["scope"].upper())
                except json.JSONDecodeError:
                    pass

            if "NO_RULE" in response_text:
                return None
            
            return RuleOutput(content=str(response_text), scope="PROJECT" if "PROJECT" in response_text.upper() else "GLOBAL")
            
        except subprocess.TimeoutExpired:
            return None
        except Exception:
            return None
