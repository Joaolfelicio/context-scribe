import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Iterator, Dict, Set

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from context_scribe.observer.provider import Interaction, BaseProvider


class CopilotLogHandler(FileSystemEventHandler):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def on_modified(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith(".json"):
            self.callback(event.src_path)

    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith(".json"):
            self.callback(event.src_path)


class CopilotProvider(BaseProvider):
    def __init__(self, log_dir: str = "~/.config/github-copilot/chat/"):
        self.log_dir = Path(os.path.expanduser(log_dir))
        self.interaction_queue = []
        # Track processed message IDs globally across all files to avoid duplicates
        self.global_processed_ids: Set[str] = set()
        # Track file mtimes to detect changes
        self.last_mtimes: Dict[str, float] = {}
        self._initialize_historical_logs()

    def _initialize_historical_logs(self):
        """Skip all messages existing before the daemon starts."""
        if not self.log_dir.exists():
            return

        print("Initializing historical logs (skipping existing messages)...")
        for file_path in self.log_dir.glob("**/*.json"):
            try:
                self.last_mtimes[str(file_path)] = os.path.getmtime(file_path)
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
            except Exception:
                pass

    def _get_messages_from_data(self, data) -> list:
        """Extracts a list of message objects from various possible JSON structures.

        Supports multiple Copilot log formats:
        - turns format: {"turns": [{"request": {...}, "response": {...}}, ...]}
        - messages format: {"messages": [{"role": "user", "content": "..."}, ...]}
        - list format: [{"role": "user", "content": "..."}, ...]
        """
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

    def _process_file(self, file_path: str):
        # Extract project name from the directory structure
        try:
            path_obj = Path(file_path)
            rel_path = path_obj.relative_to(self.log_dir)
            if len(rel_path.parts) == 1:
                project_name = "global"
            else:
                project_name = rel_path.parts[0]
        except Exception:
            project_name = "global"

        temp_path = f"{file_path}.snapshot"
        try:
            shutil.copy2(file_path, temp_path)
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
        except Exception:
            pass
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

    def _extract_interaction(self, data: dict, project_name: str):
        role = data.get("role") or data.get("type") or "unknown"
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
        if "--- CONTEXT-SCRIBE-INTERNAL-EVALUATION ---" in content.upper() or "CONTEXT-SCRIBE-INTERNAL-EVALUATION" in content:
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

    def watch(self) -> Iterator[Interaction]:
        if not self.log_dir.exists():
            self.log_dir.mkdir(parents=True, exist_ok=True)

        event_handler = CopilotLogHandler(self._process_file)
        observer = Observer()
        observer.schedule(event_handler, str(self.log_dir), recursive=True)
        observer.start()

        try:
            while True:
                for file_path in self.log_dir.glob("**/*.json"):
                    try:
                        mtime = os.path.getmtime(file_path)
                        if str(file_path) not in self.last_mtimes or mtime > self.last_mtimes.get(str(file_path), 0):
                            self.last_mtimes[str(file_path)] = mtime
                            self._process_file(str(file_path))
                    except Exception:
                        pass

                if not self.interaction_queue:
                    yield None
                    time.sleep(1)
                    continue

                while self.interaction_queue:
                    yield self.interaction_queue.pop(0)
        except KeyboardInterrupt:
            observer.stop()

        observer.join()
