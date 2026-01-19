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

    def __init__(self, log_directory: str) -> None:
        """Initialize the directory monitor.

        Args:
            log_directory: Path to the directory containing nwclientLog*.txt files
        """
        self.log_directory = Path(log_directory)
        self.current_log_file: Optional[Path] = None
        self.last_position = 0
        self.last_mtime = 0.0  # Track file modification time

    def find_active_log_file(self) -> Optional[Path]:
        """Find the currently active log file based on most recent modification time.

        Returns:
            Path to the active log file, or None if no log files found
        """
        if not self.log_directory.exists():
            return None

        # Find all nwclientLog*.txt files
        log_files = sorted(self.log_directory.glob('nwclientLog[1-4].txt'))

        if not log_files:
            return None

        # Return the file with the most recent modification time
        active_file = max(log_files, key=lambda f: f.stat().st_mtime)
        return active_file

    def get_active_log_file(self) -> Optional[Path]:
        """Get the current active log file, checking for rotation if needed.

        Returns:
            Path to the active log file, or None if no log files found
        """
        active_file = self.find_active_log_file()
        return active_file


    def start_monitoring(self) -> None:
        """Initialize file position for incremental reading.

        Finds the currently active log file and sets up position tracking.
        """
        self.current_log_file = self.get_active_log_file()
        if self.current_log_file and self.current_log_file.exists():
            file_stat = self.current_log_file.stat()
            self.last_position = file_stat.st_size
            self.last_mtime = file_stat.st_mtime

    def read_new_lines(
        self,
        parser,
        data_queue: queue.Queue,
        on_log_message=None,
        debug_enabled: bool = False
    ) -> None:
        """Read new lines from the current log file, handling rotation to new files.

        Args:
            parser: LogParser instance for parsing lines
            data_queue: Queue for passing parsed data to UI
            on_log_message: Optional callback for logging (message, msg_type)
            debug_enabled: Whether to emit debug messages (default False for performance)
        """
        try:
            # Check if we've rotated to a new log file
            active_file = self.get_active_log_file()

            # Handle rotation: if we switched to a new file, reset position and notify
            if active_file != self.current_log_file:
                if debug_enabled and on_log_message:
                    on_log_message(
                        f"📁 Log rotation: {self.current_log_file.name if self.current_log_file else 'None'} → {active_file.name}",
                        'debug'
                    )
                self.current_log_file = active_file
                self.last_position = 0  # Start from beginning of new file

            # Read from current log file
            if not self.current_log_file or not self.current_log_file.exists():
                return

            # Get current file stats
            file_stat = self.current_log_file.stat()
            current_size = file_stat.st_size
            current_mtime = file_stat.st_mtime

            # Check if file has been truncated (e.g., game restart cleared the file)
            # This can happen when:
            # 1. File size is smaller than our last read position (truncation detected)
            # 2. Modification time changed but size is smaller (file was rewritten)
            if current_size < self.last_position:
                if debug_enabled and on_log_message:
                    on_log_message(
                        f"⚠️ File truncation: {self.current_log_file.name} (was {self.last_position} bytes, now {current_size} bytes)",
                        'warning'
                    )
                self.last_position = 0
                self.last_mtime = current_mtime
            elif current_size == 0 and self.last_position > 0:
                # Special case: file was completely cleared
                if debug_enabled and on_log_message:
                    on_log_message(
                        f"⚠️ File cleared: {self.current_log_file.name}",
                        'warning'
                    )
                self.last_position = 0
                self.last_mtime = current_mtime

            with open(self.current_log_file, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(self.last_position)
                new_lines = f.readlines()
                self.last_position = f.tell()
                self.last_mtime = current_mtime

                if new_lines and debug_enabled and on_log_message:
                    on_log_message(
                        f"📖 Read {len(new_lines)} line(s) from {self.current_log_file.name}",
                        'debug'
                    )

                # Parse and queue all lines (no more redundant parsing feedback)
                for line in new_lines:
                    on_log_message(
                        f"Raw line: {line.strip()}",
                        'info'
                    )
                    parsed_data = parser.parse_line(line)
                    if parsed_data:
                        data_queue.put(parsed_data)

        except Exception as e:
            if on_log_message:
                on_log_message(f"I/O Error: {e}", 'error')
            else:
                data_queue.put({'type': 'error', 'message': str(e)})

