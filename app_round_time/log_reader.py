"""Incremental log reader with rotation handling."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional


class LogReader:
    def __init__(self, log_directory: str) -> None:
        self.log_directory = Path(log_directory)
        self.current_log_file: Optional[Path] = None
        self.last_position: int = 0
        self.last_mtime: float = 0.0

    def _find_active_log_file(self) -> Optional[Path]:
        if not self.log_directory.exists():
            return None
        log_files = sorted(self.log_directory.glob("nwclientLog[1-4].txt"))
        if not log_files:
            return None
        return max(log_files, key=lambda f: f.stat().st_mtime)

    def get_active_log_file(self) -> Optional[Path]:
        return self._find_active_log_file()

    def initialize(self, start_at_end: bool = True) -> None:
        self.current_log_file = self._find_active_log_file()
        if not self.current_log_file or not self.current_log_file.exists():
            return
        file_stat = self.current_log_file.stat()
        self.last_mtime = file_stat.st_mtime
        self.last_position = file_stat.st_size if start_at_end else 0

    def read_new_lines(self, on_line: Callable[[str, int, int], None]) -> int:
        active_file = self._find_active_log_file()
        if active_file != self.current_log_file:
            self.current_log_file = active_file
            self.last_position = 0

        if not self.current_log_file or not self.current_log_file.exists():
            return 0

        file_stat = self.current_log_file.stat()
        current_size = file_stat.st_size

        if current_size < self.last_position:
            self.last_position = 0

        with open(self.current_log_file, "r", encoding="utf-8", errors="ignore") as f:
            f.seek(self.last_position)
            new_lines = f.readlines()
            self.last_position = f.tell()

        count = 0
        for line in new_lines:
            if not line:
                continue
            wall_time_ns = time.time_ns()
            perf_ns = time.perf_counter_ns()
            on_line(line, wall_time_ns, perf_ns)
            count += 1
        return count
