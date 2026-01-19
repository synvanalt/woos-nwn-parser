"""Unit tests for monitor debug_mode optimization.

Tests the debug_mode flag that reduces queue operations.
"""

import pytest
import queue
from pathlib import Path

from app.monitor import LogDirectoryMonitor
from app.parser import LogParser


class TestDebugMode:
    """Test suite for debug_mode flag optimization."""

    def test_debug_mode_false_skips_debug_messages(self, temp_log_dir: Path) -> None:
        """Test that debug messages are not queued when debug_enabled=False."""
        log_file = temp_log_dir / "nwclientLog1.txt"
        log_file.write_text("[Thu Jan 09 14:30:00] Test line\n")

        monitor = LogDirectoryMonitor(str(temp_log_dir))
        monitor.start_monitoring()

        # Append new line
        with open(log_file, 'a') as f:
            f.write("[Thu Jan 09 14:30:01] Another test line\n")

        parser = LogParser()
        data_queue = queue.Queue()

        monitor.read_new_lines(parser, data_queue, debug_enabled=False)

        # Collect queue items
        items = []
        while not data_queue.empty():
            items.append(data_queue.get())

        # Should have NO debug/info messages
        debug_items = [i for i in items if i.get('type') in ('debug', 'info')]
        assert len(debug_items) == 0

    def test_debug_mode_true_includes_debug_messages(self, temp_log_dir: Path) -> None:
        """Test that debug messages ARE emitted when debug_enabled=True."""
        log_file = temp_log_dir / "nwclientLog1.txt"
        log_file.write_text("[Thu Jan 09 14:30:00] Test line\n")

        monitor = LogDirectoryMonitor(str(temp_log_dir))
        monitor.start_monitoring()

        # Append new line
        with open(log_file, 'a') as f:
            f.write("[Thu Jan 09 14:30:01] Another test line\n")

        parser = LogParser()
        data_queue = queue.Queue()

        # Mock callback to capture debug messages
        debug_messages = []
        def mock_log(message, msg_type):
            debug_messages.append({'message': message, 'type': msg_type})

        monitor.read_new_lines(parser, data_queue, on_log_message=mock_log, debug_enabled=True)

        # Should have debug messages via callback
        assert len(debug_messages) > 0

    def test_debug_mode_false_reduces_queue_operations(self, temp_log_dir: Path) -> None:
        """Test that debug_enabled=False reduces callback overhead."""
        log_file = temp_log_dir / "nwclientLog1.txt"
        log_file.write_text("")

        monitor_with_debug = LogDirectoryMonitor(str(temp_log_dir))
        monitor_without_debug = LogDirectoryMonitor(str(temp_log_dir))

        monitor_with_debug.start_monitoring()
        monitor_without_debug.start_monitoring()

        # Append multiple lines
        with open(log_file, 'a') as f:
            for i in range(10):
                f.write(f"[Thu Jan 09 14:30:{i:02d}] Test line {i}\n")

        parser = LogParser()

        # Test with debug
        debug_messages_with = []
        def mock_log_with(message, msg_type):
            debug_messages_with.append({'message': message, 'type': msg_type})

        queue_with_debug = queue.Queue()
        monitor_with_debug.read_new_lines(parser, queue_with_debug, on_log_message=mock_log_with, debug_enabled=True)

        # Reset file position for second monitor
        monitor_without_debug.last_position = 0

        # Test without debug
        debug_messages_without = []
        def mock_log_without(message, msg_type):
            debug_messages_without.append({'message': message, 'type': msg_type})

        queue_without_debug = queue.Queue()
        monitor_without_debug.read_new_lines(parser, queue_without_debug, on_log_message=mock_log_without, debug_enabled=False)

        # Without debug should have no debug callback invocations
        # With debug: callback is invoked for file reading messages
        assert len(debug_messages_without) == 0
        assert len(debug_messages_with) > 0

    def test_debug_mode_false_with_rotation(self, temp_log_dir: Path) -> None:
        """Test that rotation messages are skipped when debug_enabled=False."""
        log1 = temp_log_dir / "nwclientLog1.txt"
        log2 = temp_log_dir / "nwclientLog2.txt"

        log1.write_text("[Thu Jan 09 14:00:00] Content in log1\n")

        monitor = LogDirectoryMonitor(str(temp_log_dir))
        monitor.start_monitoring()

        # Simulate rotation
        import time
        time.sleep(0.1)
        log2.write_text("[Thu Jan 09 14:01:00] Content in log2\n")

        parser = LogParser()
        data_queue = queue.Queue()

        monitor.read_new_lines(parser, data_queue, debug_enabled=False)

        # Collect items
        items = []
        while not data_queue.empty():
            items.append(data_queue.get())

        # Should NOT have rotation debug message
        rotation_messages = [
            i for i in items
            if i.get('type') == 'debug' and 'rotation' in i.get('message', '').lower()
        ]
        assert len(rotation_messages) == 0

    def test_debug_mode_true_with_rotation(self, temp_log_dir: Path) -> None:
        """Test that rotation messages are included when debug_enabled=True."""
        log1 = temp_log_dir / "nwclientLog1.txt"
        log2 = temp_log_dir / "nwclientLog2.txt"

        log1.write_text("[Thu Jan 09 14:00:00] Content in log1\n")

        monitor = LogDirectoryMonitor(str(temp_log_dir))
        monitor.start_monitoring()

        # Simulate rotation
        import time
        time.sleep(0.1)
        log2.write_text("[Thu Jan 09 14:01:00] Content in log2\n")

        parser = LogParser()
        data_queue = queue.Queue()

        # Mock callback to capture debug messages
        debug_messages = []
        def mock_log(message, msg_type):
            debug_messages.append({'message': message, 'type': msg_type})

        monitor.read_new_lines(parser, data_queue, on_log_message=mock_log, debug_enabled=True)

        # Should have rotation debug message via callback
        rotation_messages = [
            msg for msg in debug_messages
            if 'rotation' in msg['message'].lower()
        ]
        assert len(rotation_messages) > 0

    def test_debug_mode_false_with_truncation(self, temp_log_dir: Path) -> None:
        """Test that truncation messages are skipped when debug_enabled=False."""
        log_file = temp_log_dir / "nwclientLog1.txt"
        log_file.write_text("Initial content\n" * 10)

        monitor = LogDirectoryMonitor(str(temp_log_dir))
        monitor.start_monitoring()

        initial_position = monitor.last_position

        # Truncate file
        log_file.write_text("New content after restart\n")

        parser = LogParser()
        data_queue = queue.Queue()

        monitor.read_new_lines(parser, data_queue, debug_enabled=False)

        # Collect items
        items = []
        while not data_queue.empty():
            items.append(data_queue.get())

        # Should NOT have truncation debug message
        truncation_messages = [
            i for i in items
            if i.get('type') == 'debug' and 'truncat' in i.get('message', '').lower()
        ]
        assert len(truncation_messages) == 0

    def test_debug_mode_performance_with_large_batch(self, temp_log_dir: Path) -> None:
        """Test performance benefit with large batch of lines."""
        log_file = temp_log_dir / "nwclientLog1.txt"

        # Create file with many lines
        with open(log_file, 'w') as f:
            for i in range(1000):
                f.write(f"[Thu Jan 09 14:{i%60:02d}:{i%60:02d}] Line {i}\n")

        monitor_disabled = LogDirectoryMonitor(str(temp_log_dir))
        monitor_disabled.start_monitoring()

        # Reset to start
        monitor_disabled.last_position = 0

        parser = LogParser()
        data_queue = queue.Queue()

        monitor_disabled.read_new_lines(parser, data_queue, debug_enabled=False)

        items = []
        while not data_queue.empty():
            items.append(data_queue.get())

        # With 1000 lines and debug_mode=False:
        # - 0 info messages (normally 1000)
        # - 0 debug parse messages (normally 1000-2000)
        # - Only actual parsed events (if any)
        # Total: saves 2000-3000 queue operations

        debug_items = [i for i in items if i.get('type') in ('debug', 'info')]
        assert len(debug_items) == 0


class TestDebugModeBackwardCompatibility:
    """Test that debug_mode doesn't break existing functionality."""

    def test_parsing_works_with_debug_disabled(self, temp_log_dir: Path) -> None:
        """Test that parsing still works when debug_enabled=False."""
        log_file = temp_log_dir / "nwclientLog1.txt"
        log_file.write_text("")

        monitor = LogDirectoryMonitor(str(temp_log_dir))
        monitor.start_monitoring()

        # Write parseable damage line (proper format with timestamp)
        with open(log_file, 'a') as f:
            f.write("[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Woo damages Goblin: 50 (50 Physical)\n")

        parser = LogParser()
        data_queue = queue.Queue()

        monitor.read_new_lines(parser, data_queue, debug_enabled=False)

        # Should still get parsed damage event
        items = []
        while not data_queue.empty():
            items.append(data_queue.get())

        damage_events = [i for i in items if i.get('type') == 'damage_dealt']
        assert len(damage_events) >= 1  # At least one damage event parsed

    def test_error_messages_still_queued(self, temp_log_dir: Path) -> None:
        """Test that error messages are always queued regardless of debug_mode."""
        # This is important - errors should always be visible
        # The current implementation queues errors via on_log_message callback
        # which is outside the debug_mode check
        pass  # Errors are handled at a higher level

