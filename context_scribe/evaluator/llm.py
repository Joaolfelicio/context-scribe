import subprocess
import logging
from typing import Optional
import json

from context_scribe.observer.provider import Interaction

logger = logging.getLogger(__name__)

class Evaluator:
    def __init__(self):
        try:
            subprocess.run(["gemini", "--version"], capture_output=True, check=True)
            logger.debug("Gemini CLI found successfully.")
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("Gemini CLI not found.")

    def evaluate_interaction(self, interaction: Interaction, existing_rules: str = "") -> Optional[str]:
        prompt = f"""
You are a 'Persistent Secretary' for an AI agent. Your job is to read user-agent chat logs
and extract long-term behavioral rules, project constraints, or user preferences.

EXISTING RULES IN MEMORY BANK:
'''
{existing_rules}
'''

LATEST INTERACTION TO ANALYZE (Role: {interaction.role}):
'''
{interaction.content}
'''

INSTRUCTIONS:
1. Extract any new long-term rules or constraints from the latest interaction.
2. If a new rule contradicts an existing rule, the NEW rule takes precedence (New-Trumps-Old).
3. If there is a change or a new rule, output the ENTIRE consolidated list of rules for the Memory Bank.
4. Maintain a clean, bulleted Markdown format.
5. If no new rules are found and no changes are needed, output exactly: NO_RULE
"""
        logger.debug(f"Evaluating interaction with conflict resolution...")
        try:
            # We use non-interactive mode and json output with a strict timeout
            result = subprocess.run(
                ["gemini", "--prompt", prompt, "--output-format", "json"], 
                capture_output=True, 
                text=True,
                check=False,
                stdin=subprocess.DEVNULL,
                timeout=45
            )
            
            output = result.stdout.strip()
            
            json_str = None
            try:
                start_idx = output.find('{')
                end_idx = output.rfind('}')
                if start_idx != -1 and end_idx != -1:
                    json_str = output[start_idx:end_idx+1]
                    data = json.loads(json_str)
                    response_text = data.get("response", "").strip()
                else:
                    response_text = output
            except json.JSONDecodeError:
                response_text = output
            
            if "NO_RULE" in response_text or not response_text:
                return None
            
            # Clean up ephemeral messages
            if "<EPHEMERAL_MESSAGE>" in response_text:
                response_text = response_text.split("<EPHEMERAL_MESSAGE>")[0].strip()
            
            plain_marker = "The following is an ephemeral message"
            if plain_marker in response_text:
                response_text = response_text.split(plain_marker)[0].strip()

            return response_text
        except subprocess.TimeoutExpired:
            logger.error("Gemini CLI evaluation timed out after 30 seconds.")
            return None
        except Exception as e:
            logger.error(f"Unexpected error calling gemini CLI: {e}")
            return None
