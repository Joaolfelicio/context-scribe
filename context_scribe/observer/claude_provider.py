import hashlib
import json
import logging
import os
import shutil
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Iterator, Dict, Optional, Set

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from context_scribe.observer.provider import Interaction, BaseProvider

logger = logging.getLogger(__name__)


class ClaudeLogHandler(FileSystemEventHandler):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def on_modified(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith(".jsonl"):
            self.callback(event.src_path)

    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith(".jsonl"):
            self.callback(event.src_path)


class ClaudeProvider(BaseProvider):
    _MAX_PROCESSED_IDS = 10000

    def __init__(self, log_dir: str = "~/.claude/projects/"):
        self.log_dir = Path(os.path.expanduser(log_dir))
        self.interaction_queue = []
        # Track processed message IDs globally across all files to avoid duplicates
        self.global_processed_ids: Set[str] = set()
        # Track file mtimes to detect changes
        self.last_mtimes: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._initialize_historical_logs()

    def _initialize_historical_logs(self):
        """Skip all messages existing before the daemon starts."""
        if not self.log_dir.exists():
            return

        print("Initializing historical logs (skipping existing messages)...")
        for file_path in self.log_dir.glob("**/*.jsonl"):
            try:
                self.last_mtimes[str(file_path)] = os.path.getmtime(file_path)
                messages = self._get_messages_from_file(file_path)
                for line_num, msg in messages:
                    msg_id = self._make_msg_id(str(file_path), line_num, msg)
                    self.global_processed_ids.add(msg_id)
            except Exception:
                logger.debug("Failed to initialize historical log: %s", file_path)

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
            logger.debug("Failed to read messages from file: %s", file_path)
        return messages

    def _process_file(self, file_path: str):
        with self._lock:
            # Extract project name from the directory structure
            try:
                path_obj = Path(file_path)
                rel_path = path_obj.relative_to(self.log_dir)
                if len(rel_path.parts) <= 1:
                    project_name = "global"
                else:
                    # Use the directory components (excluding the filename) as project name
                    project_name = str(Path(*rel_path.parts[:-1]))
            except Exception:
                project_name = "global"

            fd, temp_path = tempfile.mkstemp(suffix=".snapshot")
            os.close(fd)
            try:
                shutil.copy2(file_path, temp_path)
                messages = self._get_messages_from_file(temp_path)

                for line_num, msg in messages:
                    msg_id = self._make_msg_id(file_path, line_num, msg)

                    if msg_id not in self.global_processed_ids:
                        self._extract_interaction(msg, project_name)
                        self.global_processed_ids.add(msg_id)

                # Cap global_processed_ids to prevent unbounded growth
                if len(self.global_processed_ids) > self._MAX_PROCESSED_IDS:
                    self.global_processed_ids.clear()
            except Exception:
                logger.debug("Failed to process file: %s", file_path)
            finally:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        logger.debug("Failed to remove temp file: %s", temp_path)

    def _extract_interaction(self, data: dict, project_name: str):
        role = data.get("role") or data.get("type") or "unknown"

        # Normalize role: treat "human" as "user"
        if role == "human":
            role = "user"

        raw_content = data.get("content") or data.get("message") or data.get("text") or ""

        if isinstance(raw_content, list):
            text_parts = []
            for part in raw_content:
                if isinstance(part, dict):
                    text_parts.append(part.get("text", ""))
                else:
                    text_parts.append(str(part))
            content = "\n".join(text_parts)
        else:
            content = str(raw_content)

        # BREAK THE FEEDBACK LOOP
        upper_content = content.upper()
        if "CONTEXT-SCRIBE-INTERNAL-EVALUATION" in upper_content:
            return

        if content.strip() and role == "user":
            self.interaction_queue.append(
                Interaction(
                    timestamp=datetime.now(),
                    role=role,
                    content=content,
                    project_name=project_name,
                    metadata=data
                )
            )

    def watch(self) -> Iterator[Optional[Interaction]]:
        if not self.log_dir.exists():
            self.log_dir.mkdir(parents=True, exist_ok=True)

        event_handler = ClaudeLogHandler(self._process_file)
        observer = Observer()
        observer.schedule(event_handler, str(self.log_dir), recursive=True)
        observer.start()

        try:
            while True:
                for file_path in self.log_dir.glob("**/*.jsonl"):
                    try:
                        mtime = os.path.getmtime(file_path)
                        if str(file_path) not in self.last_mtimes or mtime > self.last_mtimes.get(str(file_path), 0):
                            self.last_mtimes[str(file_path)] = mtime
                            self._process_file(str(file_path))
                    except Exception:
                        logger.debug("Failed to check file mtime: %s", file_path)

                if not self.interaction_queue:
                    yield None
                    time.sleep(1)
                    continue

                while self.interaction_queue:
                    yield self.interaction_queue.pop(0)
        finally:
            observer.stop()
            observer.join()
