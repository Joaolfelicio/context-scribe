import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path

from context_scribe.evaluator.models import INTERNAL_SIGNATURE
from context_scribe.observer.base_provider import Interaction, BaseProvider

logger = logging.getLogger(__name__)


class ClaudeProvider(BaseProvider):
    def __init__(self, log_dir: str = "~/.claude/projects/"):
        super().__init__(log_dir=log_dir, file_extension=".jsonl")
        self._initialize_historical_logs()

    def _make_msg_id(self, file_path: str, line_num: int, msg: dict) -> str:
        """Create a unique ID for a message using line number and content hash."""
        content = json.dumps(msg, sort_keys=True)
        content_hash = hashlib.md5(content.encode()).hexdigest()
        return f"{file_path}_{line_num}_{content_hash}"

    def _get_messages_from_file(self, file_path) -> list:
        """Extracts a list of (line_number, message_dict) tuples from a JSONL file."""
        messages = []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if isinstance(data, dict):
                            # If there's a nested "message" object with role/content, use it
                            if "message" in data and isinstance(data["message"], dict):
                                msg = data["message"]
                                # Preserve the type field from the outer object if present
                                if "type" in data and "role" not in msg:
                                    msg["role"] = data["type"]
                                messages.append((line_num, msg))
                            else:
                                messages.append((line_num, data))
                    except json.JSONDecodeError:
                        continue
        except Exception:
            logger.debug(f"Failed to read messages from file: {file_path}")
        return messages

    def _parse_historical_file(self, file_path: str):
        messages = self._get_messages_from_file(file_path)
        for line_num, msg in messages:
            msg_id = self._make_msg_id(str(file_path), line_num, msg)
            self.global_processed_ids.add(msg_id)

    def _parse_file_content(self, temp_path: str, original_path: str):
        # Extract project name from the directory structure
        try:
            path_obj = Path(original_path)
            rel_path = path_obj.relative_to(self.log_dir)
            if len(rel_path.parts) <= 1:
                project_name = "global"
            else:
                # Use the directory components (excluding the filename) as project name
                project_name = str(Path(*rel_path.parts[:-1]))
        except Exception:
            project_name = "global"

        messages = self._get_messages_from_file(temp_path)

        for line_num, msg in messages:
            msg_id = self._make_msg_id(original_path, line_num, msg)

            if msg_id not in self.global_processed_ids:
                self._extract_interaction(msg, project_name)
                self.global_processed_ids.add(msg_id)

