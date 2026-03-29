from context_scribe.models.interaction import Interaction
import logging
import os
import shutil
import tempfile
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional, Dict, Set

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from context_scribe.models.evaluator_models import INTERNAL_SIGNATURE_UPPER

logger = logging.getLogger(__name__)



class GenericLogHandler(FileSystemEventHandler):
    """A generic watchdog event handler that filters by file extension."""
    def __init__(self, extension: str, callback):
        super().__init__()
        self.extension = extension
        self.callback = callback

    def on_modified(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith(self.extension):
            self.callback(event.src_path)

    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith(self.extension):
            self.callback(event.src_path)


class BaseProvider(ABC):
    """Abstract base class for all log providers."""
    
    _MAX_PROCESSED_IDS = 10000

    def __init__(self, log_dir: str, file_extension: str):
        self.log_dir = Path(os.path.expanduser(log_dir))
        self.file_extension = file_extension
        self.interaction_queue = []
        # Track processed message IDs globally across all files to avoid duplicates
        self.global_processed_ids: Set[str] = set()
        self._processed_ids_order: deque = deque()
        # Track file mtimes to detect changes
        self.last_mtimes: Dict[str, float] = {}
        self._lock = threading.RLock()
        # Subclasses must call self._initialize_historical_logs() after super().__init__()
        # if they need to parse historical messages differently, but we can provide a default.

    def _initialize_historical_logs(self):
        """Skip all messages existing before the daemon starts."""
        if not self.log_dir.exists():
            return

        logger.info("Initializing historical logs (skipping existing messages)...")
        for file_path in self.log_dir.glob(f"**/*{self.file_extension}"):
            try:
                self.last_mtimes[str(file_path)] = os.path.getmtime(file_path)
                # We need to extract IDs to ignore them.
                # This delegates to the subclass's parsing logic but we don't enqueue interactions.
                self._parse_historical_file(str(file_path))
            except Exception as e:
                logger.debug(f"Failed to initialize historical log {file_path}: {e}")

    @abstractmethod
    def _parse_historical_file(self, file_path: str):
        """Parse a historical file to populate global_processed_ids without queuing interactions."""
        pass

    def _mark_id_processed(self, msg_id: str):
        """Thread-safe marking of an ID as processed with rolling eviction."""
        with self._lock:
            if msg_id not in self.global_processed_ids:
                self.global_processed_ids.add(msg_id)
                self._processed_ids_order.append(msg_id)
                
                # Rolling eviction to keep memory usage bounded without reprocessing everything
                if len(self._processed_ids_order) > self._MAX_PROCESSED_IDS:
                    oldest_id = self._processed_ids_order.popleft()
                    self.global_processed_ids.discard(oldest_id)

    def _process_file(self, file_path: str):
        """Safely process a file by taking a snapshot, then delegate to subclass parsing."""
        with self._lock:
            fd, temp_path = tempfile.mkstemp(suffix=".snapshot")
            try:
                os.close(fd)
                shutil.copy2(file_path, temp_path)
                self._parse_file_content(temp_path, file_path)
            except Exception as e:
                logger.debug(f"Failed to process file {file_path}: {e}")
            finally:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError as e:
                        logger.debug(f"Failed to remove temp file {temp_path}: {e}")

    @abstractmethod
    def _parse_file_content(self, temp_path: str, original_path: str):
        """Parse the content of the snapshot file and add to interaction_queue."""
        pass

    def _extract_interaction(self, data: dict, project_name: str):
        role = data.get("role") or data.get("type") or "unknown"

        # Normalize role: treat "human" as "user" (for Claude)
        if role == "human":
            role = "user"

        raw_content = data.get("content") or data.get("message") or data.get("text") or ""

        # Sometimes content is nested
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

        # Break the feedback loop (case-insensitive comparison)
        if INTERNAL_SIGNATURE_UPPER in content.upper():
            return None

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
        """
        Continuously yields new interactions as they are detected.
        This is a blocking generator that yields Interaction objects.
        """
        if not self.log_dir.exists():
            self.log_dir.mkdir(parents=True, exist_ok=True)

        event_handler = GenericLogHandler(self.file_extension, self._process_file)
        observer = Observer()
        observer.schedule(event_handler, str(self.log_dir), recursive=True)
        observer.start()

        try:
            while True:
                # Manual scanning as fallback/supplement to watchdog
                for file_path in self.log_dir.glob(f"**/*{self.file_extension}"):
                    try:
                        mtime = os.path.getmtime(file_path)
                        if str(file_path) not in self.last_mtimes or mtime > self.last_mtimes.get(str(file_path), 0):
                            self.last_mtimes[str(file_path)] = mtime
                            self._process_file(str(file_path))
                    except OSError as e:
                        logger.debug(f"Failed to check mtime for {file_path}: {e}")

                if not self.interaction_queue:
                    yield None
                    time.sleep(1)
                    continue

                with self._lock:
                    items = list(self.interaction_queue)
                    self.interaction_queue.clear()

                for item in items:
                    yield item
        except KeyboardInterrupt:
            pass
        finally:
            try:
                observer.stop()
            except Exception:
                logger.debug("Error stopping observer")
            observer.join()
