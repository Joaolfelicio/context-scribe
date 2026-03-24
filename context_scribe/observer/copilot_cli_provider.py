import json
import logging
import os
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional

from context_scribe.models.interaction import Interaction
from context_scribe.observer.base_provider import BaseProvider

logger = logging.getLogger(__name__)

class CopilotCliProvider(BaseProvider):
    """
    Provider for GitHub Copilot CLI (NPM package @github/copilot).
    Monitors ~/.copilot/session-state/*/events.jsonl
    """
    def __init__(self, log_dir: str = "~/.copilot/session-state/"):
        # We watch events.jsonl files
        super().__init__(log_dir=log_dir, file_extension="events.jsonl")
        self._initialize_historical_logs()

    def _get_project_name(self, events_file_path: str) -> str:
        """Extracts project name from workspace.yaml in the same directory."""
        import time
        session_dir = Path(events_file_path).parent
        workspace_file = session_dir / "workspace.yaml"
        
        # Retry logic to handle race condition where events.jsonl is created before workspace.yaml is ready
        for attempt in range(5):
            if workspace_file.exists():
                try:
                    with open(workspace_file, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                        if not content:
                            raise ValueError("File is empty")
                        data = yaml.safe_load(content)
                        if data:
                            cwd = data.get("cwd") or data.get("workingDirectory")
                            if cwd:
                                name = Path(cwd).name
                                logger.info(f"Project detection success: '{name}' (attempt {attempt+1})")
                                return name
                except Exception as e:
                    logger.debug(f"Attempt {attempt+1}: Failed to parse {workspace_file}: {e}")
            
            if attempt < 4:
                time.sleep(0.5)
        
        logger.warning(f"Project detection failed for {events_file_path}, defaulting to 'global'")
        return "global"

    def _parse_historical_file(self, file_path: str):
        if not os.path.exists(file_path):
            return
            
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        msg_id = data.get("id")
                        if msg_id:
                            self.global_processed_ids.add(msg_id)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.debug(f"Failed to parse historical Copilot CLI log {file_path}: {e}")

    def _parse_file_content(self, temp_path: str, original_path: str):
        project_name = self._get_project_name(original_path)
        
        try:
            with open(temp_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                        
                    try:
                        event = json.loads(line)
                        msg_id = event.get("id")
                        
                        if msg_id and msg_id in self.global_processed_ids:
                            continue
                            
                        # We are interested in user messages
                        event_type = event.get("type")
                        event_data = event.get("data", {})
                        
                        if event_type == "user.message":
                            interaction_data = {
                                "role": "user",
                                "content": event_data.get("content", ""),
                                "timestamp": event.get("timestamp")
                            }
                            self._extract_interaction(interaction_data, project_name)
                        
                        if msg_id:
                            self.global_processed_ids.add(msg_id)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.debug(f"Failed to parse Copilot CLI log content {original_path}: {e}")
