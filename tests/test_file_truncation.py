"""Test file truncation detection in LogDirectoryMonitor.

This test verifies that the monitor correctly handles the case where the game
restarts and clears the log file (truncation scenario).
"""

import queue
import tempfile
from pathlib import Path

from app.monitor import LogDirectoryMonitor
from app.parser import LogParser


def test_file_truncation_detection():
    """Test that monitor detects when log file is truncated (e.g., game restart)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a test log file
        log_file = Path(tmpdir) / "nwclientLog1.txt"

        # Write initial content
        log_file.write_text("Line 1\nLine 2\nLine 3\n")

        # Setup monitor with debug_mode enabled to get debug messages
        monitor = LogDirectoryMonitor(tmpdir, debug_mode=True)
        monitor.start_monitoring()

        # Verify initial position is set to end of file
        initial_size = log_file.stat().st_size
        assert monitor.last_position == initial_size, f"Expected position {initial_size}, got {monitor.last_position}"

        # Simulate game restart: truncate file and write new content
        log_file.write_text("New Line 1\n")

        # Read new lines
        parser = LogParser(parse_immunity=False)
        data_queue = queue.Queue()
        monitor.read_new_lines(parser, data_queue)

        # Verify that monitor detected truncation and reset position
        assert monitor.last_position < initial_size, "Position should be reset after truncation"

        # Verify debug message about truncation was queued
        messages = []
        while not data_queue.empty():
            item = data_queue.get()
            if item.get('type') in ('debug', 'info'):
                messages.append(item['message'])

        truncation_detected = any('truncat' in msg.lower() for msg in messages)
        assert truncation_detected, f"Expected truncation message, got: {messages}"

        # Verify new content is read
        new_content_detected = any('New Line 1' in msg for msg in messages)
        assert new_content_detected, f"Expected new content to be read, got: {messages}"

        print("✓ File truncation detection works correctly")


def test_append_after_truncation():
    """Test that monitor continues to read new lines after truncation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "nwclientLog1.txt"

        # Initial content
        log_file.write_text("Initial content\n")

        # Setup monitor with debug_mode enabled
        monitor = LogDirectoryMonitor(tmpdir, debug_mode=True)
        monitor.start_monitoring()

        # Truncate and write new content
        log_file.write_text("After restart\n")

        # First read (should detect truncation)
        parser = LogParser(parse_immunity=False)
        data_queue = queue.Queue()
        monitor.read_new_lines(parser, data_queue)

        # Clear queue
        while not data_queue.empty():
            data_queue.get()

        # Append more content (simulate continued gameplay)
        with open(log_file, 'a') as f:
            f.write("New action line\n")

        # Second read (should read new appended line)
        monitor.read_new_lines(parser, data_queue)

        # Verify new line was read
        messages = []
        while not data_queue.empty():
            item = data_queue.get()
            if item.get('type') in ('debug', 'info'):
                messages.append(item['message'])

        new_line_detected = any('New action line' in msg for msg in messages)
        assert new_line_detected, f"Expected new appended line to be read, got: {messages}"

        print("✓ Continued monitoring after truncation works correctly")


if __name__ == '__main__':
    test_file_truncation_detection()
    test_append_after_truncation()
    print("\n✓ All truncation tests passed!")

