import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from context_scribe.models.interaction import Interaction
from context_scribe.models.evaluator_models import RuleOutput

class DaemonMocks:
    def __init__(self):
        self.provider = MagicMock()
        self.evaluator = MagicMock()
        self.mcp = AsyncMock()
        self.processed_interaction = False

        # Setup interaction
        self.interaction = Interaction(
            timestamp=None,
            role="user",
            content="New Rule",
            project_name="p1"
        )

        # Mock watch iterator: yield one interaction then None then raise KeyboardInterrupt
        def mock_watch():
            yield self.interaction
            yield None
            raise KeyboardInterrupt()

        self.provider.watch.return_value = mock_watch()

        # Correct RuleOutput with description
        self.rule_output = RuleOutput(scope="GLOBAL", content="Extracted Rule", description="Added new rule")
        self.evaluator.evaluate_interaction.return_value = self.rule_output

        # Mock read_rules
        self.mcp.read_rules.return_value = ""

        # Track interaction processing to break loop
        async def save_rule_side_effect(*args, **kwargs):
            self.processed_interaction = True
            return MagicMock()
        self.mcp.save_rule.side_effect = save_rule_side_effect

@pytest.fixture
def daemon_mocks():
    return DaemonMocks()
