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
            # Don't clear data - we want to merge past logs with current session
            # Save current state first if not already saved
            if self.session_only_state is None:
                self.save_session_state()

            # Parse all log files in the directory (in order: log1, log2, log3, log4)
            log_dir = Path(log_directory)
            log_files = sorted(log_dir.glob('nwclientLog[1-4].txt'))

            if not log_files:
                on_log("No log files found in directory", "warning")
            else:
                total_lines = 0
                for log_file in log_files:
                    if not self.is_parsing:
                        on_log("Parsing cancelled by user", "info")
                        break

                    on_log(f"Parsing: {log_file.name}", "debug")

                    # Parse only lines before the monitoring start position for this file
                    # If monitoring_start_position is None or file not in dict, parse entire file
                    max_line = None
                    if monitoring_start_position and log_file.name in monitoring_start_position:
                        max_line = monitoring_start_position[log_file.name]
                        on_log(f"  → Parsing past logs up to line {max_line}", "debug")

                    # Create progress callback that calls the on_progress callback and yields
                    def progress_callback(lines_count: int) -> None:
                        """Called after each chunk - yields control and triggers UI update."""
                        # Yield control to allow UI thread to process events
                        time.sleep(0.001)
                        # Trigger UI update if callback provided
                        if on_progress:
                            on_progress()

                    result = parse_and_import_file(
                        str(log_file),
                        self.parser,
                        self.data_store,
                        max_line=max_line,
                        progress_callback=progress_callback,
                        progress_interval=1  # Call after every chunk
                    )

                    if result['success']:
                        lines = result['lines_processed']
                        total_lines += lines
                        on_log(f"  → {log_file.name}: {lines} lines", "debug")
                    else:
                        on_log(f"  → Error: {result['error']}", "error")

                if self.is_parsing:
                    on_log(f"All past logs parsed successfully ({total_lines} total lines)", "info")
                    # Mark that past logs are now included
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
        """
        with self.data_store.lock:
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
        """Restore the session-only state (exclude past logs from view)."""
        if self.session_only_state is None:
            return

        with self.data_store.lock:
            self.data_store.events = copy.deepcopy(self.session_only_state['events'])
            self.data_store.attacks = copy.deepcopy(self.session_only_state['attacks'])
            self.data_store.dps_data = copy.deepcopy(self.session_only_state['dps_data'])
            self.data_store.last_damage_timestamp = self.session_only_state['last_damage_timestamp']
            self.data_store.immunity_data = copy.deepcopy(self.session_only_state['immunity_data'])
            self.parser.target_ac = copy.deepcopy(self.session_only_state['target_ac'])
            self.parser.target_saves = copy.deepcopy(self.session_only_state['target_saves'])
            self.parser.target_attack_bonus = copy.deepcopy(self.session_only_state['target_attack_bonus'])

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

