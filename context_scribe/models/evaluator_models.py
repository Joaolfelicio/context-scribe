from dataclasses import dataclass

INTERNAL_SIGNATURE = "--- CONTEXT-SCRIBE-INTERNAL-EVALUATION ---"
INTERNAL_SIGNATURE_UPPER = INTERNAL_SIGNATURE.upper()

@dataclass
class RuleOutput:
    content: str
    scope: str  # "GLOBAL" or "PROJECT"
    description: str # Concise summary of what changed
