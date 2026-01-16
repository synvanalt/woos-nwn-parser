"""Integration tests for monitor, parser, and file handling.

Tests file monitoring, rotation, truncation, and real-world scenarios.
"""

import pytest
import queue
import time
from pathlib import Path

from app.monitor import LogDirectoryMonitor
from app.parser import LogParser


class TestMonitorParserIntegration:
    """Test suite for monitor and parser integration."""

    def test_basic_monitoring_workflow(self, temp_log_dir: Path) -> None:
        """Test basic monitoring workflow with new content."""
        log_file = temp_log_dir / "nwclientLog1.txt"
        log_file.write_text("Initial content\n")

        monitor = LogDirectoryMonitor(str(temp_log_dir))
        monitor.start_monitoring()

        # Append new content
        with open(log_file, 'a') as f:
            f.write("[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Goblin: 50 (50 Physical)\n")

        parser = LogParser()
        data_queue = queue.Queue()

        monitor.read_new_lines(parser, data_queue)

        # Collect parsed events
        events = []
        while not data_queue.empty():
            item = data_queue.get()
            events.append(item)

        # Should have parsed the damage line
        damage_events = [e for e in events if e.get('type') == 'damage_dealt']
        assert len(damage_events) > 0


class TestFileRotation:
    """Test suite for log file rotation scenarios."""

    def test_rotation_log1_to_log2(self, temp_log_dir: Path) -> None:
        """Test rotation from nwclientLog1.txt to nwclientLog2.txt."""
        log1 = temp_log_dir / "nwclientLog1.txt"
        log2 = temp_log_dir / "nwclientLog2.txt"

        # Start with log1
        log1.write_text("Content in log1\n")

        monitor = LogDirectoryMonitor(str(temp_log_dir), debug_mode=True)
        monitor.start_monitoring()

        assert monitor.current_log_file == log1

        # Simulate rotation: log2 becomes active
        time.sleep(0.1)
        log2.write_text("Content in log2\n")

        parser = LogParser()
        data_queue = queue.Queue()

        monitor.read_new_lines(parser, data_queue)

        # Should detect rotation
        assert monitor.current_log_file == log2

        # Check for rotation debug message
        items = []
        while not data_queue.empty():
            items.append(data_queue.get())

        rotation_detected = any(
            'rotation' in item.get('message', '').lower()
            for item in items if item.get('type') == 'debug'
        )
        assert rotation_detected

    def test_rotation_through_multiple_files(self, temp_log_dir: Path) -> None:
        """Test rotation through multiple log files."""
        log1 = temp_log_dir / "nwclientLog1.txt"
        log2 = temp_log_dir / "nwclientLog2.txt"
        log3 = temp_log_dir / "nwclientLog3.txt"

        log1.write_text("Log1\n")

        monitor = LogDirectoryMonitor(str(temp_log_dir))
        monitor.start_monitoring()

        parser = LogParser()
        data_queue = queue.Queue()

        # Rotate to log2
        time.sleep(0.1)
        log2.write_text("Log2\n")
        monitor.read_new_lines(parser, data_queue)
        assert monitor.current_log_file == log2

        # Clear queue
        while not data_queue.empty():
            data_queue.get()

        # Rotate to log3
        time.sleep(0.1)
        log3.write_text("Log3\n")
        monitor.read_new_lines(parser, data_queue)
        assert monitor.current_log_file == log3

    def test_continue_monitoring_after_rotation(self, temp_log_dir: Path) -> None:
        """Test that monitoring continues correctly after rotation."""
        log1 = temp_log_dir / "nwclientLog1.txt"
        log2 = temp_log_dir / "nwclientLog2.txt"

        log1.write_text("Log1\n")

        monitor = LogDirectoryMonitor(str(temp_log_dir), debug_mode=True)
        monitor.start_monitoring()

        parser = LogParser()
        data_queue = queue.Queue()

        # Rotate to log2
        time.sleep(0.1)
        log2.write_text("Log2\n")
        monitor.read_new_lines(parser, data_queue)

        # Clear queue
        while not data_queue.empty():
            data_queue.get()

        # Append to log2
        with open(log2, 'a') as f:
            f.write("[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Orc: 100 (100 Physical)\n")

        monitor.read_new_lines(parser, data_queue)

        # Should read new content
        items = []
        while not data_queue.empty():
            items.append(data_queue.get())

        assert any('Orc' in str(item.get('message', '')) for item in items)


class TestFileTruncation:
    """Test suite for file truncation scenarios (game restarts)."""

    def test_truncation_detection(self, temp_log_dir: Path) -> None:
        """Test that monitor detects file truncation."""
        log_file = temp_log_dir / "nwclientLog1.txt"
        log_file.write_text("Line 1\nLine 2\nLine 3\n")

        monitor = LogDirectoryMonitor(str(temp_log_dir), debug_mode=True)
        monitor.start_monitoring()

        initial_size = log_file.stat().st_size
        assert monitor.last_position == initial_size

        # Truncate file
        log_file.write_text("New Line 1\n")

        parser = LogParser(parse_immunity=False)
        data_queue = queue.Queue()

        monitor.read_new_lines(parser, data_queue)

        # Position should be reset
        assert monitor.last_position < initial_size

        # Check for truncation message
        items = []
        while not data_queue.empty():
            items.append(data_queue.get())

        truncation_detected = any(
            'truncat' in item.get('message', '').lower()
            for item in items if item.get('type') == 'debug'
        )
        assert truncation_detected

    def test_read_new_content_after_truncation(self, temp_log_dir: Path) -> None:
        """Test that new content is read after truncation."""
        log_file = temp_log_dir / "nwclientLog1.txt"
        log_file.write_text("[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Old line\n" * 10)

        monitor = LogDirectoryMonitor(str(temp_log_dir), debug_mode=True)
        monitor.start_monitoring()

        initial_position = monitor.last_position

        # Ensure some time passes and file is modified
        time.sleep(0.05)

        # Truncate and write new content with a parseable log line (smaller than before)
        log_file.write_text("[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] New line\n")

        # Verify truncation condition
        new_size = log_file.stat().st_size
        assert new_size < initial_position, "Test setup error: file should be smaller"

        parser = LogParser()
        data_queue = queue.Queue()

        monitor.read_new_lines(parser, data_queue)

        items = []
        while not data_queue.empty():
            items.append(data_queue.get())

        # Should have read lines after truncation
        assert len(items) > 0, f"Expected items but got none. Was {initial_position} bytes, now {new_size}"

        # Should have truncation detection message
        truncation_messages = [
            item for item in items
            if item.get('type') == 'debug' and 'truncat' in item.get('message', '').lower()
        ]
        assert len(truncation_messages) > 0, f"Expected truncation message"

    def test_continue_after_truncation(self, temp_log_dir: Path) -> None:
        """Test that monitoring continues after truncation."""
        log_file = temp_log_dir / "nwclientLog1.txt"
        log_file.write_text("Initial content\n")

        monitor = LogDirectoryMonitor(str(temp_log_dir), debug_mode=True)
        monitor.start_monitoring()

        parser = LogParser()
        data_queue = queue.Queue()

        # Truncate
        log_file.write_text("After restart\n")
        monitor.read_new_lines(parser, data_queue)

        # Clear queue
        while not data_queue.empty():
            data_queue.get()

        # Append more content
        with open(log_file, 'a') as f:
            f.write("New action line\n")

        monitor.read_new_lines(parser, data_queue)

        # Should read new line
        items = []
        while not data_queue.empty():
            items.append(data_queue.get())

        assert any('New action line' in str(item.get('message', '')) for item in items)


class TestRealWorldScenarios:
    """Test suite for real-world usage scenarios."""

    def test_game_start_monitor_gameplay_restart(self, temp_log_dir: Path) -> None:
        """Test complete scenario: game start, monitor, gameplay, restart."""
        log_file = temp_log_dir / "nwclientLog1.txt"

        # Game starts
        with open(log_file, 'w') as f:
            f.write("[Thu Jan 09 14:30:00] You attack Goblin: *hit*: (10 damage)\n")

        # App starts monitoring with debug_mode enabled
        monitor = LogDirectoryMonitor(str(temp_log_dir), debug_mode=True)
        monitor.start_monitoring()

        parser = LogParser(parse_immunity=False)
        data_queue = queue.Queue()
        is_monitoring = True

        # First poll (no new data)
        monitor.read_new_lines(parser, data_queue)

        # Player continues gaming
        time.sleep(0.05)
        with open(log_file, 'a') as f:
            f.write("[Thu Jan 09 14:30:02] You attack Goblin: *hit*: (15 damage)\n")

        # Poll again
        monitor.read_new_lines(parser, data_queue)

        # Game restarts - clears file
        time.sleep(0.05)
        with open(log_file, 'w') as f:
            f.write("[Thu Jan 09 14:35:00] You attack Orc: *hit*: (20 damage)\n")

        # Next automatic poll
        monitor.read_new_lines(parser, data_queue)

        items = []
        while not data_queue.empty():
            items.append(data_queue.get())

        # Verify truncation was detected
        truncation_detected = any(
            'truncat' in item.get('message', '').lower()
            for item in items if item.get('type') == 'debug'
        )
        assert truncation_detected

        # Verify new content (Orc) was found
        orc_found = any('Orc' in str(item.get('message', '')) for item in items)
        assert orc_found

        # Verify continued monitoring works
        while not data_queue.empty():
            data_queue.get()

        with open(log_file, 'a') as f:
            f.write("[Thu Jan 09 14:35:01] You attack Orc: *hit*: (25 damage)\n")

        monitor.read_new_lines(parser, data_queue)

        items = []
        while not data_queue.empty():
            items.append(data_queue.get())

        continued_content = any('25 damage' in str(item.get('message', '')) for item in items)
        assert continued_content

    def test_multiple_polling_cycles(self, temp_log_dir: Path) -> None:
        """Test multiple polling cycles with incremental content."""
        log_file = temp_log_dir / "nwclientLog1.txt"
        log_file.write_text("")

        monitor = LogDirectoryMonitor(str(temp_log_dir))
        monitor.start_monitoring()

        parser = LogParser()
        data_queue = queue.Queue()

        # Simulate multiple polling cycles
        for i in range(5):
            # Add new content
            with open(log_file, 'a') as f:
                f.write(f"Line {i}\n")

            # Poll
            monitor.read_new_lines(parser, data_queue)

            # Clear queue
            while not data_queue.empty():
                data_queue.get()

        # All lines should have been read incrementally
        assert monitor.last_position > 0

    def test_no_log_files_initially(self, temp_log_dir: Path) -> None:
        """Test monitoring when no log files exist initially."""
        monitor = LogDirectoryMonitor(str(temp_log_dir))
        monitor.start_monitoring()

        assert monitor.current_log_file is None

        parser = LogParser()
        data_queue = queue.Queue()

        # Poll with no files (should not error)
        monitor.read_new_lines(parser, data_queue)

        # Now create a log file
        log_file = temp_log_dir / "nwclientLog1.txt"
        log_file.write_text("New content\n")

        # Next poll should detect it
        monitor.read_new_lines(parser, data_queue)

        # Should now be monitoring the file
        assert monitor.current_log_file is not None

