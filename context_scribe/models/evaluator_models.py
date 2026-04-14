from dataclasses import dataclass
from typing import Optional

INTERNAL_SIGNATURE = "--- CONTEXT-SCRIBE-INTERNAL-EVALUATION ---"
INTERNAL_SIGNATURE_UPPER = INTERNAL_SIGNATURE.upper()


@dataclass
class RuleOutput:
    content: str
    scope: str  # "GLOBAL" or "PROJECT"
    description: str  # Concise summary of what changed


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
    prefilter_passed: int = 0
    prefilter_skipped: int = 0
    prefilter_errors: int = 0

    @property
    def skip_rate(self) -> float:
        total = self.prefilter_passed + self.prefilter_skipped
        if total == 0:
            return 0.0
        return self.prefilter_skipped / total

    def record_result(self, result: Optional["PrefilterResult"]) -> None:
        if result is None:
            self.prefilter_errors += 1
        elif result.should_skip_full_eval:
            self.prefilter_skipped += 1
        else:
            self.prefilter_passed += 1
