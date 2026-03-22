import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Iterator

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from context_scribe.observer.provider import Interaction, BaseProvider


class GeminiLogHandler(FileSystemEventHandler):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.processed_files = set()

    def on_modified(self, event):
        if event.is_directory:
            return
            
        # Try to process specific log files (e.g., .json files in the tmp directory)
        if event.src_path.endswith(".json"):
            self.callback(event.src_path)

    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith(".json"):
            self.callback(event.src_path)


class GeminiProvider(BaseProvider):
    def __init__(self, log_dir: str = "~/.gemini/tmp/"):
        self.log_dir = Path(os.path.expanduser(log_dir))
        self.interaction_queue = []
        self.last_positions = {}  # Track the last read position for each file
        self._initialize_positions()

    def _initialize_positions(self):
        """Pre-fill positions with current file sizes to skip historical data."""
        if self.log_dir.exists():
            for file_path in self.log_dir.glob("**/*.json"):
                try:
                    self.last_positions[str(file_path)] = file_path.stat().st_size
                    self.last_positions[f"{file_path}_mtime"] = os.path.getmtime(file_path)
                except Exception:
                    pass

    def _process_file(self, file_path: str):
        # Safety: copy file to avoid locking issues
        temp_path = f"{file_path}.snapshot"
        try:
            shutil.copy2(file_path, temp_path)
            
            with open(temp_path, "r", encoding="utf-8") as f:
                # Seek to last read position to avoid re-reading
                last_pos = self.last_positions.get(file_path, 0)
                f.seek(last_pos)
                
                content = f.read()
                
                # Update last read position
                self.last_positions[file_path] = f.tell()

                if not content.strip():
                    return

                # Attempt to parse Gemini CLI format. 
                # Assuming JSON lines or a JSON array. We might need to adjust this depending on the exact format.
                try:
                    # Let's assume it's JSON array for now, or lines.
                    # We will just parse the whole file for now as a placeholder
                    # In a real scenario, we would parse line by line or use a JSON parser that handles streams
                    if content.strip().startswith("{"):
                        # might be single json object
                        data = json.loads(content)
                        self._extract_interaction(data)
                    elif content.strip().startswith("["):
                        data = json.loads(content)
                        for item in data:
                            self._extract_interaction(item)
                except json.JSONDecodeError:
                    # If it's not valid JSON, we'll try to find any new rules or text
                    # For a robust implementation, this needs exact log format.
                    pass

        except Exception as e:
            print(f"Error processing {file_path}: {e}")
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

    def _extract_interaction(self, data: dict):
        # Extract based on expected Gemini CLI log schema
        # We check for common keys used in Gemini/MCP logs
        role = data.get("role") or data.get("type") or "unknown"
        
        # content can be a string or a list of parts
        content = data.get("content") or data.get("text") or ""
        
        if isinstance(content, list):
            # If it's a list of message parts (common in some MCP/Gemini schemas)
            text_parts = []
            for part in content:
                if isinstance(part, dict):
                    text_parts.append(part.get("text", ""))
                else:
                    text_parts.append(str(part))
            content = "\\n".join(text_parts)
            
        if content:
            self.interaction_queue.append(
                Interaction(
                    timestamp=datetime.now(),
                    role=role,
                    content=str(content),
                    metadata=data
                )
            )

    def watch(self) -> Iterator[Interaction]:
        if not self.log_dir.exists():
            self.log_dir.mkdir(parents=True, exist_ok=True)

        event_handler = GeminiLogHandler(self._process_file)
        observer = Observer()
        observer.schedule(event_handler, str(self.log_dir), recursive=True)
        observer.start()

        try:
            while True:
                # Manual scan for any .json files in the tmp directory
                for file_path in self.log_dir.glob("**/*.json"):
                    # Check if file is new or was modified
                    mtime = os.path.getmtime(file_path)
                    if str(file_path) not in self.last_positions or mtime > self.last_positions.get(f"{file_path}_mtime", 0):
                        self.last_positions[f"{file_path}_mtime"] = mtime
                        self._process_file(str(file_path))
                
                while self.interaction_queue:
                    yield self.interaction_queue.pop(0)
                time.sleep(2)
        except KeyboardInterrupt:
            observer.stop()
        
        observer.join()
