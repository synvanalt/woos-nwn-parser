"""Log file monitoring for NWN game log files.

This module handles directory monitoring and incremental log file reading,
supporting automatic rotation between nwclientLog1.txt through nwclientLog4.txt.
"""

import queue
from pathlib import Path
from typing import Optional


class LogDirectoryMonitor:
    """Manages finding and tracking the active log file in a directory.

    The NWN game writes to nwclientLog1.txt, then nwclientLog2.txt, etc. when a file becomes full.
    This class identifies which file is currently being written to (based on modification time)
    and handles switching to the next file when rotation occurs.
    """

    IDLE_RESCAN_INTERVAL_POLLS = 10

    def __init__(self, log_directory: str) -> None:
        """Initialize the directory monitor.

        Args:
            log_directory: Path to the directory containing nwclientLog*.txt files
        """
        self.log_directory = Path(log_directory)
        self._candidate_files = tuple(
            self.log_directory / f"nwclientLog{index}.txt"
            for index in range(1, 5)
        )
        self.current_log_file: Optional[Path] = None
        self.last_position = 0
        self.last_mtime = 0.0  # Track file modification time
        self._last_directory_mtime = 0.0
        self._idle_polls_until_rescan = 0

    def _get_directory_mtime(self) -> float:
        """Return the directory mtime or 0.0 when it is unavailable."""
        try:
            return self.log_directory.stat().st_mtime
        except OSError:
            return 0.0

    def _reset_idle_rescan_state(self) -> None:
        """Reset the idle-poll tracker after activity or a full rescan."""
        self._idle_polls_until_rescan = 0

    def _note_idle_poll(self) -> None:
        """Track idle polls without letting the counter grow unbounded."""
        if self._idle_polls_until_rescan > 0:
            self._idle_polls_until_rescan -= 1

    def _idle_rescan_due(self) -> bool:
        """Return True when the next idle poll should force a candidate rescan."""
        return self._idle_polls_until_rescan == 0

    def find_active_log_file(self) -> Optional[Path]:
        """Find the currently active log file based on most recent modification time.

        Returns:
            Path to the active log file, or None if no log files found
        """
        if not self.log_directory.exists():
            self._last_directory_mtime = 0.0
            return None

        active_file: Optional[Path] = None
        active_mtime = float("-inf")

        for candidate in self._candidate_files:
            try:
                candidate_mtime = candidate.stat().st_mtime
            except OSError:
                continue
            if candidate_mtime >= active_mtime:
                active_file = candidate
                active_mtime = candidate_mtime

        self._last_directory_mtime = self._get_directory_mtime()
        return active_file

    def get_active_log_file(self) -> Optional[Path]:
        """Get the current active log file, checking for rotation if needed.

        Returns:
            Path to the active log file, or None if no log files found
        """
        if self.current_log_file is None:
            active_file = self.find_active_log_file()
            self._idle_polls_until_rescan = self.IDLE_RESCAN_INTERVAL_POLLS
            return active_file

        try:
            current_stat = self.current_log_file.stat()
        except OSError:
            active_file = self.find_active_log_file()
            self._idle_polls_until_rescan = self.IDLE_RESCAN_INTERVAL_POLLS
            return active_file

        current_size = current_stat.st_size
        current_mtime = current_stat.st_mtime

        # Truncation is handled in the steady-state path; no rediscovery required.
        if current_size < self.last_position:
            self._reset_idle_rescan_state()
            return self.current_log_file

        if current_size > self.last_position or current_mtime > self.last_mtime:
            self._reset_idle_rescan_state()
            return self.current_log_file

        directory_mtime = self._get_directory_mtime()
        if directory_mtime != self._last_directory_mtime:
            active_file = self.find_active_log_file()
            self._idle_polls_until_rescan = self.IDLE_RESCAN_INTERVAL_POLLS
            return active_file

        if self._idle_rescan_due():
            active_file = self.find_active_log_file()
            self._idle_polls_until_rescan = self.IDLE_RESCAN_INTERVAL_POLLS
            return active_file
        self._note_idle_poll()

        return self.current_log_file

    def start_monitoring(self) -> None:
        """Initialize file position for incremental reading.

        Finds the currently active log file and sets up position tracking.
        """
        self.current_log_file = self.get_active_log_file()
        self._reset_idle_rescan_state()
        if self.current_log_file and self.current_log_file.exists():
            file_stat = self.current_log_file.stat()
            self.last_position = file_stat.st_size
            self.last_mtime = file_stat.st_mtime

    def read_new_lines(
        self,
        parser,
        data_queue: queue.Queue,
        on_log_message=None,
        debug_enabled: bool = False,
        max_lines_per_poll: int = 2000,
    ) -> bool:
        """Read new lines from the current log file, handling rotation to new files.

        Args:
            parser: ParserSession instance for parsing lines
            data_queue: Queue for passing parsed data to UI
            on_log_message: Optional callback for logging (message, msg_type)
            debug_enabled: Whether to emit debug messages (default False for performance)
            max_lines_per_poll: Maximum number of lines to parse in one call

        Returns:
            True when more unread lines remain in the file after this call
        """
        try:
            active_file = self.get_active_log_file()
            queue_saturated = False
            queue_maxsize = int(getattr(data_queue, "maxsize", 0) or 0)
            queue_is_bounded = queue_maxsize > 0
            queue_full = data_queue.full
            queue_put_nowait = data_queue.put_nowait
            parse_line = parser.parse_line

            # Handle rotation: if we switched to a new file, reset position and notify
            if active_file != self.current_log_file:
                if on_log_message and active_file is not None:
                    previous_name = self.current_log_file.name if self.current_log_file else 'None'
                    on_log_message(
                        f"Log rotation: {previous_name} -> {active_file.name}",
                        'info',
                    )
                elif on_log_message and active_file is None and self.current_log_file is not None:
                    on_log_message(
                        "I/O Error: active log file became unavailable during rotation check",
                        'error',
                    )
                self.current_log_file = active_file
                self.last_position = 0
                self._reset_idle_rescan_state()

            if not self.current_log_file or not self.current_log_file.exists():
                return False

            file_stat = self.current_log_file.stat()
            current_size = file_stat.st_size
            current_mtime = file_stat.st_mtime

            if current_size < self.last_position:
                if on_log_message:
                    on_log_message(
                        f"File truncation: {self.current_log_file.name} (was {self.last_position} bytes, now {current_size} bytes)",
                        'warning',
                    )
                self.last_position = 0
                self.last_mtime = current_mtime
            elif current_size == 0 and self.last_position > 0:
                if on_log_message:
                    on_log_message(
                        f"File cleared: {self.current_log_file.name}",
                        'warning',
                    )
                self.last_position = 0
                self.last_mtime = current_mtime

            parsed_lines = 0
            with open(self.current_log_file, 'r', encoding='utf-8', errors='ignore') as handle:
                handle.seek(self.last_position)
                while parsed_lines < max_lines_per_poll:
                    if queue_is_bounded and queue_full():
                        queue_saturated = True
                        break
                    line = handle.readline()
                    if not line:
                        break

                    parsed_lines += 1
                    if debug_enabled and on_log_message:
                        on_log_message(f"Raw line: {line.strip()}", 'info')

                    parsed_data = parse_line(line)
                    if parsed_data:
                        try:
                            queue_put_nowait(parsed_data)
                        except queue.Full:
                            queue_saturated = True
                            break

                self.last_position = handle.tell()
                self.last_mtime = current_mtime
                self._last_directory_mtime = self._get_directory_mtime()

            has_more_pending = queue_saturated or self.last_position < current_size

            if parsed_lines and debug_enabled and on_log_message:
                on_log_message(
                    f"Read {parsed_lines} line(s) from {self.current_log_file.name}",
                    'debug',
                )
            if queue_saturated and on_log_message:
                on_log_message(
                    f"Realtime queue saturated while reading {self.current_log_file.name}; deferring remaining lines",
                    'warning',
                )

            return has_more_pending

        except Exception as exc:
            if on_log_message:
                on_log_message(f"I/O Error: {exc}", 'error')
            return False
