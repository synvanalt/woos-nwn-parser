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

    def read_new_lines(self, parser, data_queue: queue.Queue) -> None:
        """Read new lines from the current log file, handling rotation to new files.

        Args:
            parser: LogParser instance for parsing lines
            data_queue: Queue for passing parsed data to UI
        """
        try:
            # Check if we've rotated to a new log file
            active_file = self.get_active_log_file()

            # Handle rotation: if we switched to a new file, reset position and notify
            if active_file != self.current_log_file:
                data_queue.put({
                    'type': 'debug',
                    'message': f"Log file rotation detected: {self.current_log_file.name if self.current_log_file else 'None'} → {active_file.name if active_file else 'None'}"
                })
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
                data_queue.put({
                    'type': 'debug',
                    'message': f"⚠️ File truncation detected: {self.current_log_file.name} (was {self.last_position} bytes, now {current_size} bytes) - resetting to beginning"
                })
                self.last_position = 0
                self.last_mtime = current_mtime
            elif current_size == 0 and self.last_position > 0:
                # Special case: file was completely cleared
                data_queue.put({
                    'type': 'debug',
                    'message': f"⚠️ File cleared: {self.current_log_file.name} - resetting to beginning"
                })
                self.last_position = 0
                self.last_mtime = current_mtime

            with open(self.current_log_file, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(self.last_position)
                new_lines = f.readlines()
                self.last_position = f.tell()
                self.last_mtime = current_mtime

                if new_lines:
                    data_queue.put({
                        'type': 'debug',
                        'message': f"Read {len(new_lines)} new line(s) from {self.current_log_file.name}"
                    })

                for line in new_lines:
                    # Show more of the line in debug (300 chars instead of 100)
                    data_queue.put({'type': 'info', 'message': f"Raw line: {line.strip()}"})
                    parsed_data = parser.parse_line(line)
                    if parsed_data:
                        data_queue.put({'type': 'debug', 'message': f"✓ Parsed: {parsed_data['type']}"})
                        if parsed_data['type'] == 'damage_dealt':
                            # Show damage breakdown for debugging
                            data_queue.put({'type': 'debug',
                                                 'message': f"  → Target: {parsed_data['target']}, Damage types: {list(parsed_data['damage_types'].keys())}"})
                        data_queue.put(parsed_data)
                    else:
                        data_queue.put({'type': 'debug', 'message': f"✗ No match for line"})
        except Exception as e:
            data_queue.put({'type': 'error', 'message': str(e)})

