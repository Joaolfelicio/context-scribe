import os
import pytest
import time
from unittest.mock import MagicMock, patch
from context_scribe.observer.gemini_cli_provider import GeminiCliProvider

@pytest.mark.timeout(5)
def test_provider_watch_manual_scan_trigger(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    provider = GeminiCliProvider(log_dir=str(log_dir))
    
    # Pre-fill last_mtimes so it doesn't process on first check unless changed
    test_file = log_dir / "test.json"
    test_file.write_text('[]')
    provider.last_mtimes[str(test_file)] = os.path.getmtime(test_file)
    
    with patch("context_scribe.observer.base_provider.Observer") as mock_obs:
        # Mock time.sleep to raise KeyboardInterrupt to break the infinite loop
        with patch("time.sleep", side_effect=[None, KeyboardInterrupt()]):
            # Create a new file while "watching"
            new_file = log_dir / "new.json"
            new_file.write_text('{"sessionId": "s", "messages": [{"id": "m", "type": "user", "text": "manual"}]}')
            
            # This will run one iteration, then sleep once, then raising KeyboardInterrupt
            gen = provider.watch()
            
            # First item from queue
            interaction = next(gen)
            assert interaction.content == "manual"
