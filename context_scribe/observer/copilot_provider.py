import json
import logging
from datetime import datetime
from pathlib import Path

from context_scribe.models.evaluator_models import INTERNAL_SIGNATURE
from context_scribe.models.interaction import Interaction
from context_scribe.observer.base_provider import BaseProvider

logger = logging.getLogger(__name__)


class CopilotProvider(BaseProvider):
    def __init__(self, log_dir: str = "~/.config/github-copilot/chat/"):
        super().__init__(log_dir=log_dir, file_extension=".json")
        self._initialize_historical_logs()

    def _parse_historical_file(self, file_path: str):
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            messages = self._get_messages_from_data(data)

            if isinstance(data, dict):
                session_id = data.get("sessionId") or data.get("id") or "unknown"
            else:
                session_id = "unknown"

            for msg in messages:
                raw_msg_id = msg.get("id") or msg.get("messageId") or str(msg)
                self.global_processed_ids.add(f"{session_id}_{raw_msg_id}")

    def _get_messages_from_data(self, data) -> list:
        """Extracts a list of message objects from various possible JSON structures."""
        if isinstance(data, dict):
            if "turns" in data:
                messages = []
                for turn in data["turns"]:
                    if "request" in turn:
                        req = turn["request"]
                        if isinstance(req, dict):
                            if "role" not in req:
                                req["role"] = "user"
                            messages.append(req)
                    if "response" in turn:
                        resp = turn["response"]
                        if isinstance(resp, dict):
                            if "role" not in resp:
                                resp["role"] = "assistant"
                            messages.append(resp)
                return messages
            if "messages" in data:
                return data["messages"]
            return [data]
        elif isinstance(data, list):
            return data
        return []

    def _parse_file_content(self, temp_path: str, original_path: str):
        # Extract project name from the directory structure
        try:
            path_obj = Path(original_path)
            rel_path = path_obj.relative_to(self.log_dir)
            if len(rel_path.parts) == 1:
                project_name = "global"
            else:
                project_name = rel_path.parts[0]
        except ValueError:
            project_name = "global"

        with open(temp_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return
            data = json.loads(content)
            messages = self._get_messages_from_data(data)

            if isinstance(data, dict):
                session_id = data.get("sessionId") or data.get("id") or "unknown"
            else:
                session_id = "unknown"

            for msg in messages:
                raw_msg_id = msg.get("id") or msg.get("messageId") or str(msg)
                msg_id = f"{session_id}_{raw_msg_id}"

                if msg_id not in self.global_processed_ids:
                    self._extract_interaction(msg, project_name)
                    self.global_processed_ids.add(msg_id)
