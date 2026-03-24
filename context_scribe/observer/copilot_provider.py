import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

from watchdog.observers import Observer

from context_scribe.models.evaluator_models import INTERNAL_SIGNATURE
from context_scribe.models.interaction import Interaction
from context_scribe.observer.base_provider import BaseProvider, GenericLogHandler

logger = logging.getLogger(__name__)


class CopilotProvider(BaseProvider):
    """Watches both VS Code Copilot Chat logs and Copilot CLI session events."""

    def __init__(
        self,
        log_dir: str = "~/.config/github-copilot/chat/",
        cli_log_dir: str = "~/.copilot/session-state/",
    ):
        super().__init__(log_dir=log_dir, file_extension=".json")
        self.cli_log_dir = Path(os.path.expanduser(cli_log_dir))
        self._initialize_historical_logs()
        self._initialize_cli_historical_logs()

    # ------------------------------------------------------------------ #
    # VS Code Copilot Chat (JSON files)                                   #
    # ------------------------------------------------------------------ #

    def _parse_historical_file(self, file_path: str):
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            messages = self._get_messages_from_data(data)
            session_id = data.get("sessionId") or data.get("id") or "unknown" if isinstance(data, dict) else "unknown"
            for msg in messages:
                raw_msg_id = msg.get("id") or msg.get("messageId") or str(msg)
                self.global_processed_ids.add(f"{session_id}_{raw_msg_id}")

    def _get_messages_from_data(self, data) -> list:
        """Extracts a list of message objects from VS Code Copilot Chat JSON structures."""
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
        try:
            path_obj = Path(original_path)
            rel_path = path_obj.relative_to(self.log_dir)
            project_name = rel_path.parts[0] if len(rel_path.parts) > 1 else "global"
        except ValueError:
            project_name = "global"

        with open(temp_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return
            data = json.loads(content)
            messages = self._get_messages_from_data(data)
            session_id = data.get("sessionId") or data.get("id") or "unknown" if isinstance(data, dict) else "unknown"

            for msg in messages:
                raw_msg_id = msg.get("id") or msg.get("messageId") or str(msg)
                msg_id = f"{session_id}_{raw_msg_id}"
                if msg_id not in self.global_processed_ids:
                    self._extract_interaction(msg, project_name)
                    self.global_processed_ids.add(msg_id)

    # ------------------------------------------------------------------ #
    # Copilot CLI (events.jsonl files under session-state/)               #
    # ------------------------------------------------------------------ #

    def _get_cli_project_name(self, file_path: str) -> str:
        """Derive project name from session.start cwd in an events.jsonl file."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    event = json.loads(line)
                    if event.get("type") == "session.start":
                        cwd = event.get("data", {}).get("context", {}).get("cwd", "")
                        if cwd:
                            return Path(cwd).name or "global"
                        break
        except (json.JSONDecodeError, OSError):
            pass
        return "global"

    def _initialize_cli_historical_logs(self):
        """Mark existing Copilot CLI event IDs as seen so we don't reprocess them."""
        if not self.cli_log_dir.exists():
            return
        print("Initializing Copilot CLI historical logs...")
        for file_path in self.cli_log_dir.glob("*/events.jsonl"):
            try:
                self.last_mtimes[str(file_path)] = os.path.getmtime(file_path)
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if event.get("type") == "user.message":
                            self.global_processed_ids.add(event.get("id", str(event)))
            except OSError as e:
                logger.debug("Failed to init CLI log %s: %s", file_path, e)

    def _parse_cli_file(self, file_path: str):
        """Process new user.message events in a Copilot CLI events.jsonl file."""
        with self._lock:
            project_name = self._get_cli_project_name(file_path)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        if event.get("type") != "user.message":
                            continue

                        event_id = event.get("id", str(event))
                        if event_id in self.global_processed_ids:
                            continue

                        content = event.get("data", {}).get("content", "").strip()
                        if not content:
                            continue
                        if INTERNAL_SIGNATURE in content.upper():
                            continue

                        self.global_processed_ids.add(event_id)
                        try:
                            ts_raw = event.get("timestamp", "")
                            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")) if ts_raw else datetime.now()
                        except (ValueError, AttributeError):
                            ts = datetime.now()
                        self.interaction_queue.append(
                            Interaction(
                                timestamp=ts,
                                role="user",
                                content=content,
                                project_name=project_name,
                                metadata=event.get("data", {}),
                            )
                        )
                        logger.debug("CLI event queued: %s (project=%s)", event_id[:8], project_name)
            except OSError as e:
                logger.debug("Failed to read CLI log %s: %s", file_path, e)

    # ------------------------------------------------------------------ #
    # Dual-path watch loop                                                #
    # ------------------------------------------------------------------ #

    def watch(self) -> Iterator[Optional[Interaction]]:
        # Ensure VS Code chat dir exists
        self.log_dir.mkdir(parents=True, exist_ok=True)
        # Ensure CLI session-state dir exists
        self.cli_log_dir.mkdir(parents=True, exist_ok=True)

        # Observer for VS Code Copilot Chat (.json)
        chat_handler = GenericLogHandler(self.file_extension, self._process_file)
        chat_observer = Observer()
        chat_observer.schedule(chat_handler, str(self.log_dir), recursive=True)
        chat_observer.start()

        # Observer for Copilot CLI (events.jsonl)
        cli_handler = GenericLogHandler(".jsonl", self._parse_cli_file)
        cli_observer = Observer()
        cli_observer.schedule(cli_handler, str(self.cli_log_dir), recursive=True)
        cli_observer.start()

        logger.debug("Watching VS Code chat: %s", self.log_dir)
        logger.debug("Watching Copilot CLI:  %s", self.cli_log_dir)

        try:
            while True:
                # Periodic scan — VS Code chat JSON files
                for file_path in self.log_dir.glob("**/*.json"):
                    try:
                        mtime = os.path.getmtime(file_path)
                        key = str(file_path)
                        if key not in self.last_mtimes or mtime > self.last_mtimes[key]:
                            self.last_mtimes[key] = mtime
                            self._process_file(str(file_path))
                    except OSError as e:
                        logger.debug("mtime check failed %s: %s", file_path, e)

                # Periodic scan — Copilot CLI events.jsonl files
                for file_path in self.cli_log_dir.glob("*/events.jsonl"):
                    try:
                        mtime = os.path.getmtime(file_path)
                        key = str(file_path)
                        if key not in self.last_mtimes or mtime > self.last_mtimes[key]:
                            self.last_mtimes[key] = mtime
                            self._parse_cli_file(str(file_path))
                    except OSError as e:
                        logger.debug("mtime check failed %s: %s", file_path, e)

                if not self.interaction_queue:
                    yield None
                    time.sleep(1)
                    continue

                with self._lock:
                    while self.interaction_queue:
                        yield self.interaction_queue.pop(0)

        except KeyboardInterrupt:
            pass
        finally:
            for obs in (chat_observer, cli_observer):
                try:
                    obs.stop()
                except Exception:
                    pass
                obs.join()

