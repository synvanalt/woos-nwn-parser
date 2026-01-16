"""Past logs parsing service.

This module handles parsing of historical log files in a background thread.
All logic is pure Python with no Tkinter dependencies - UI updates are
delegated via callbacks.
"""

import threading
import time
from pathlib import Path
from typing import Callable, Optional, Dict, Any
import copy

from ..storage import DataStore
from ..parser import LogParser
from ..utils import parse_and_import_file


class PastLogsParserService:
    """Service for parsing historical log files in background threads.

    This service manages the lifecycle of background parsing operations,
    including starting, stopping, and monitoring parsing progress.
    All UI updates are delegated via callbacks to maintain separation
    of concerns.

    The service also manages state to allow toggling between session-only
    and session+past logs views.
    """

    def __init__(self, data_store: DataStore, parser: LogParser) -> None:
        """Initialize the parser service.

        Args:
            data_store: Reference to the data store
            parser: Reference to the log parser
        """
        self.data_store = data_store
        self.parser = parser
        self.is_parsing = False
        self.parse_thread: Optional[threading.Thread] = None

        # State management for toggling between session-only and session+past
        self.past_logs_included = False
        self.session_only_state: Optional[Dict[str, Any]] = None
        self.monitoring_start_position: Optional[Dict[str, int]] = None

    def start_parsing(
        self,
        log_directory: str,
        on_log: Callable[[str, str], None],
        on_complete: Callable[[], None],
        on_progress: Optional[Callable[[], None]] = None,
        monitoring_start_position: Optional[Dict[str, int]] = None,
    ) -> bool:
        """Start parsing past logs in a background thread.

        Args:
            log_directory: Path to directory containing log files
            on_log: Callback for logging messages (message, msg_type)
            on_complete: Callback when parsing completes
            on_progress: Optional callback for progress updates (called frequently from background thread)
            monitoring_start_position: Dict mapping log file names to line positions where monitoring started

        Returns:
            True if parsing started, False if already in progress
        """
        if self.is_parsing:
            on_log("Parsing already in progress", "warning")
            return False

        self.is_parsing = True
        self.monitoring_start_position = monitoring_start_position

        # Start background thread
        self.parse_thread = threading.Thread(
            target=self._parse_logs_thread,
            args=(log_directory, on_log, on_complete, on_progress, monitoring_start_position),
            daemon=True
        )
        self.parse_thread.start()

        return True

    def stop_parsing(self, timeout: float = 2.0) -> None:
        """Stop the background parsing thread.

        Args:
            timeout: Maximum seconds to wait for thread to finish
        """
        if not self.is_parsing:
            return

        self.is_parsing = False

        # Wait for thread to finish (with timeout)
        if self.parse_thread and self.parse_thread.is_alive():
            self.parse_thread.join(timeout=timeout)

    def _parse_logs_thread(
        self,
        log_directory: str,
        on_log: Callable[[str, str], None],
        on_complete: Callable[[], None],
        on_progress: Optional[Callable[[], None]],
        monitoring_start_position: Optional[Dict[str, int]] = None,
    ) -> None:
        """Background thread function to parse log files.

        Args:
            log_directory: Path to directory containing log files
            on_log: Callback for logging messages
            on_complete: Callback when parsing completes
            on_progress: Callback for progress updates (called frequently)
            monitoring_start_position: Dict mapping log file names to line positions where monitoring started
        """
        try:
            # OPTIMIZATION: Save state in background thread (not on UI thread)
            # Only save if we have data and haven't saved yet
            if self.session_only_state is None:
                # Quick check if there's any data worth saving
                has_data = (len(self.data_store.events) > 0 or
                           len(self.data_store.attacks) > 0 or
                           len(self.data_store.dps_data) > 0)
                if has_data:
                    on_log("Saving current session state...", "debug")
                    self.save_session_state()
                    on_log("Session state saved", "debug")

            # Parse all log files in the directory (in order: log1, log2, log3, log4)
            log_dir = Path(log_directory)
            log_files = sorted(log_dir.glob('nwclientLog[1-4].txt'))

            if not log_files:
                on_log("No log files found in directory", "warning")
            else:
                total_lines = 0
                files_processed = 0

                # OPTIMIZATION: Batch log messages for better performance
                on_log(f"Starting to parse {len(log_files)} log file(s)...", "info")

                for log_file in log_files:
                    if not self.is_parsing:
                        on_log("Parsing cancelled by user", "info")
                        break

                    # Parse only lines before the monitoring start position for this file
                    max_line = None
                    if monitoring_start_position and log_file.name in monitoring_start_position:
                        max_line = monitoring_start_position[log_file.name]

                    # OPTIMIZATION: Minimal progress callbacks since UI doesn't update during parsing
                    # Update every 40 chunks = every 200,000 lines with 5000-line chunks
                    # This maximizes parsing speed while still yielding for responsiveness
                    chunk_count = [0]

                    def progress_callback(lines_count: int) -> None:
                        """Called after each chunk - yields very infrequently for maximum speed."""
                        chunk_count[0] += 1

                        # Update every 40 chunks = every 200,000 lines
                        # Since we don't update UI during parsing, we can afford to update less
                        if chunk_count[0] % 40 == 0:
                            time.sleep(0.00001)  # Minimal sleep, just enough to yield GIL
                            if on_progress:
                                on_progress()  # This just resets a flag, doesn't refresh UI

                    result = parse_and_import_file(
                        str(log_file),
                        self.parser,
                        self.data_store,
                        max_line=max_line,
                        progress_callback=progress_callback,
                        progress_interval=1
                    )

                    if result['success']:
                        lines = result['lines_processed']
                        total_lines += lines
                        files_processed += 1
                        # OPTIMIZATION: Only log every other file to reduce debug overhead
                        if files_processed % 2 == 0 or files_processed == len(log_files):
                            on_log(f"Progress: {files_processed}/{len(log_files)} files, {total_lines} lines", "debug")
                    else:
                        on_log(f"Error in {log_file.name}: {result['error']}", "error")

                if self.is_parsing:
                    on_log(f"Completed: {total_lines} lines from {files_processed} file(s)", "info")
                    self.mark_past_logs_included()

        except Exception as e:
            on_log(f"Error during parsing: {e}", "error")
        finally:
            # Mark parsing as complete
            self.is_parsing = False
            # Notify completion (will be called on background thread)
            on_complete()

    def is_parsing_active(self) -> bool:
        """Check if parsing is currently active.

        Returns:
            True if parsing is in progress
        """
        return self.is_parsing

    def is_past_logs_included(self) -> bool:
        """Check if past logs are currently included in the view.

        Returns:
            True if past logs are included
        """
        return self.past_logs_included

    def save_session_state(self) -> None:
        """Save the current session-only state before parsing past logs.

        This allows us to restore the session-only view when the user
        toggles off "Include Past Logs".

        Note: We deep copy here so restoration is fast (just assignment).
        """
        with self.data_store.lock:
            # Deep copy only once during save (not during restore)
            self.session_only_state = {
                'events': copy.deepcopy(self.data_store.events),
                'attacks': copy.deepcopy(self.data_store.attacks),
                'dps_data': copy.deepcopy(self.data_store.dps_data),
                'last_damage_timestamp': self.data_store.last_damage_timestamp,
                'immunity_data': copy.deepcopy(self.data_store.immunity_data),
                'target_ac': copy.deepcopy(self.parser.target_ac),
                'target_saves': copy.deepcopy(self.parser.target_saves),
                'target_attack_bonus': copy.deepcopy(self.parser.target_attack_bonus),
            }

    def restore_session_state(self) -> None:
        """Restore the session-only state (exclude past logs from view).

        Fast operation - just reassigns the saved deep copies.
        """
        if self.session_only_state is None:
            return

        with self.data_store.lock:
            # Direct assignment - no need to deep copy again
            # The session_only_state already contains deep copies
            self.data_store.events = self.session_only_state['events']
            self.data_store.attacks = self.session_only_state['attacks']
            self.data_store.dps_data = self.session_only_state['dps_data']
            self.data_store.last_damage_timestamp = self.session_only_state['last_damage_timestamp']
            self.data_store.immunity_data = self.session_only_state['immunity_data']
            self.parser.target_ac = self.session_only_state['target_ac']
            self.parser.target_saves = self.session_only_state['target_saves']
            self.parser.target_attack_bonus = self.session_only_state['target_attack_bonus']

        self.past_logs_included = False

    def mark_past_logs_included(self) -> None:
        """Mark that past logs have been successfully parsed and included."""
        self.past_logs_included = True

    def clear_state(self) -> None:
        """Clear all saved state when user resets data.

        This should be called when the user clicks "Reset Data" to ensure
        that any saved session state is cleared and the service is ready
        for a new session.
        """
        self.session_only_state = None
        self.past_logs_included = False
        self.monitoring_start_position = None

