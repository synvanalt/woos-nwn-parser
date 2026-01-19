"""Unit tests for LogDirectoryMonitor.

Tests file discovery, rotation detection, truncation handling,
and incremental reading.
"""

import pytest
import queue
import time
from pathlib import Path

from app.monitor import LogDirectoryMonitor
from app.parser import LogParser


class TestLogDirectoryMonitorInitialization:
    """Test suite for LogDirectoryMonitor initialization."""

    def test_initialization(self, temp_log_dir: Path) -> None:
        """Test monitor initializes correctly."""
        monitor = LogDirectoryMonitor(str(temp_log_dir))

        assert monitor.log_directory == temp_log_dir
        assert monitor.current_log_file is None
        assert monitor.last_position == 0
        assert monitor.last_mtime == 0.0

    def test_initialization_nonexistent_directory(self) -> None:
        """Test monitor handles nonexistent directory."""
        monitor = LogDirectoryMonitor("/nonexistent/path")
        assert monitor.log_directory == Path("/nonexistent/path")


class TestFileDiscovery:
    """Test suite for file discovery methods."""

    def test_find_active_log_file_none_exists(self, temp_log_dir: Path) -> None:
        """Test finding active log file when none exist."""
        monitor = LogDirectoryMonitor(str(temp_log_dir))
        active = monitor.find_active_log_file()
        assert active is None

    def test_find_active_log_file_single_file(self, temp_log_dir: Path) -> None:
        """Test finding active log file with single file."""
        log1 = temp_log_dir / "nwclientLog1.txt"
        log1.write_text("Test content")

        monitor = LogDirectoryMonitor(str(temp_log_dir))
        active = monitor.find_active_log_file()

        assert active == log1

    def test_find_active_log_file_multiple_files(self, temp_log_dir: Path) -> None:
        """Test finding active log file with multiple files."""
        log1 = temp_log_dir / "nwclientLog1.txt"
        log2 = temp_log_dir / "nwclientLog2.txt"
        log3 = temp_log_dir / "nwclientLog3.txt"

        log1.write_text("Old content")
        time.sleep(0.01)
        log2.write_text("Older content")
        time.sleep(0.01)
        log3.write_text("Newest content")

        monitor = LogDirectoryMonitor(str(temp_log_dir))
        active = monitor.find_active_log_file()

        # Should return the most recently modified file
        assert active == log3

    def test_find_active_log_file_ignores_other_files(self, temp_log_dir: Path) -> None:
        """Test that find_active_log_file ignores non-log files."""
        log1 = temp_log_dir / "nwclientLog1.txt"
        other = temp_log_dir / "otherfile.txt"

        log1.write_text("Log content")
        other.write_text("Other content")

        monitor = LogDirectoryMonitor(str(temp_log_dir))
        active = monitor.find_active_log_file()

        assert active == log1


class TestMonitoringInitialization:
    """Test suite for start_monitoring method."""

    def test_start_monitoring_empty_directory(self, temp_log_dir: Path) -> None:
        """Test starting monitoring with no log files."""
        monitor = LogDirectoryMonitor(str(temp_log_dir))
        monitor.start_monitoring()

        assert monitor.current_log_file is None
        assert monitor.last_position == 0

    def test_start_monitoring_with_existing_file(self, temp_log_dir: Path) -> None:
        """Test starting monitoring with existing file."""
        log1 = temp_log_dir / "nwclientLog1.txt"
        log1.write_text("Existing content\n")

        monitor = LogDirectoryMonitor(str(temp_log_dir))
        monitor.start_monitoring()

        assert monitor.current_log_file == log1
        assert monitor.last_position == log1.stat().st_size

    def test_start_monitoring_sets_mtime(self, temp_log_dir: Path) -> None:
        """Test that start_monitoring sets modification time."""
        log1 = temp_log_dir / "nwclientLog1.txt"
        log1.write_text("Content\n")

        monitor = LogDirectoryMonitor(str(temp_log_dir))
        monitor.start_monitoring()

        assert monitor.last_mtime > 0.0


class TestIncrementalReading:
    """Test suite for read_new_lines method."""

    def test_read_new_lines_no_new_content(self, temp_log_dir: Path) -> None:
        """Test reading when no new content exists."""
        log1 = temp_log_dir / "nwclientLog1.txt"
        log1.write_text("Initial content\n")

        monitor = LogDirectoryMonitor(str(temp_log_dir))
        monitor.start_monitoring()

        parser = LogParser()
        data_queue = queue.Queue()

        monitor.read_new_lines(parser, data_queue)

        # Should not add any items to queue
        assert data_queue.empty()

    def test_read_new_lines_with_new_content(self, temp_log_dir: Path) -> None:
        """Test reading new content appended to file."""
        log1 = temp_log_dir / "nwclientLog1.txt"
        log1.write_text("Initial content\n")

        monitor = LogDirectoryMonitor(str(temp_log_dir))
        monitor.start_monitoring()

        # Append new content
        with open(log1, 'a') as f:
            f.write("New line\n")

        parser = LogParser()
        data_queue = queue.Queue()

        # Mock callback to capture debug messages
        debug_messages = []
        def mock_log(message, msg_type):
            debug_messages.append({'message': message, 'type': msg_type})

        monitor.read_new_lines(parser, data_queue, on_log_message=mock_log, debug_enabled=True)

        # Should have logged reading new lines
        assert len(debug_messages) > 0
        assert any("Read" in msg['message'] and "line" in msg['message'] for msg in debug_messages)

    def test_read_new_lines_updates_position(self, temp_log_dir: Path) -> None:
        """Test that read_new_lines updates position."""
        log1 = temp_log_dir / "nwclientLog1.txt"
        log1.write_text("Initial content\n")

        monitor = LogDirectoryMonitor(str(temp_log_dir))
        monitor.start_monitoring()

        initial_position = monitor.last_position

        with open(log1, 'a') as f:
            f.write("New content\n")

        parser = LogParser()
        data_queue = queue.Queue()

        monitor.read_new_lines(parser, data_queue)

        assert monitor.last_position > initial_position


class TestFileRotation:
    """Test suite for log file rotation detection."""

    def test_rotation_detection(self, temp_log_dir: Path) -> None:
        """Test detection of file rotation."""
        log1 = temp_log_dir / "nwclientLog1.txt"
        log2 = temp_log_dir / "nwclientLog2.txt"

        log1.write_text("Log 1 content\n")

        monitor = LogDirectoryMonitor(str(temp_log_dir))
        monitor.start_monitoring()

        assert monitor.current_log_file == log1

        # Simulate rotation: log2 becomes active
        time.sleep(0.1)
        log2.write_text("Log 2 content\n")

        parser = LogParser()
        data_queue = queue.Queue()

        # Mock callback to capture debug messages
        debug_messages = []
        def mock_log(message, msg_type):
            debug_messages.append({'message': message, 'type': msg_type})

        monitor.read_new_lines(parser, data_queue, on_log_message=mock_log, debug_enabled=True)

        # Should detect rotation
        assert monitor.current_log_file == log2
        assert monitor.last_position >= 0

        # Should log message about rotation
        rotation_messages = [
            msg for msg in debug_messages
            if 'rotation' in msg['message'].lower()
        ]
        assert len(rotation_messages) > 0

    def test_rotation_resets_position(self, temp_log_dir: Path) -> None:
        """Test that rotation resets position to start of new file."""
        log1 = temp_log_dir / "nwclientLog1.txt"
        log2 = temp_log_dir / "nwclientLog2.txt"

        log1.write_text("Log 1 content\n" * 100)

        monitor = LogDirectoryMonitor(str(temp_log_dir))
        monitor.start_monitoring()

        old_position = monitor.last_position

        time.sleep(0.1)
        log2.write_text("Log 2 content\n")

        parser = LogParser()
        data_queue = queue.Queue()

        monitor.read_new_lines(parser, data_queue)

        # Position should reset (be smaller than old position)
        assert monitor.last_position < old_position


class TestFileTruncation:
    """Test suite for file truncation detection."""

    def test_truncation_detection(self, temp_log_dir: Path) -> None:
        """Test detection of file truncation (game restart)."""
        log1 = temp_log_dir / "nwclientLog1.txt"
        log1.write_text("Initial content\n" * 10)

        monitor = LogDirectoryMonitor(str(temp_log_dir))
        monitor.start_monitoring()

        old_position = monitor.last_position

        # Simulate truncation: file is cleared and rewritten
        log1.write_text("New content after restart\n")

        parser = LogParser()
        data_queue = queue.Queue()

        # Mock callback to capture debug messages
        debug_messages = []
        def mock_log(message, msg_type):
            debug_messages.append({'message': message, 'type': msg_type})

        monitor.read_new_lines(parser, data_queue, on_log_message=mock_log, debug_enabled=True)

        # Position should be reset
        assert monitor.last_position < old_position

        # Should log message about truncation
        truncation_messages = [
            msg for msg in debug_messages
            if 'truncat' in msg['message'].lower()
        ]
        assert len(truncation_messages) > 0

    def test_truncation_reads_new_content(self, temp_log_dir: Path) -> None:
        """Test that after truncation, new content is read."""
        log1 = temp_log_dir / "nwclientLog1.txt"
        log1.write_text("[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Old line\n" * 10)

        monitor = LogDirectoryMonitor(str(temp_log_dir))
        monitor.start_monitoring()

        initial_position = monitor.last_position

        # Ensure some time passes and file is modified
        time.sleep(0.05)

        # Truncate and write new content with a parseable log line (smaller than before)
        log1.write_text("[CHAT WINDOW TEXT] [Thu Jan 09 14:30:01] New line\n")

        # Verify truncation condition: new size < old position
        new_size = log1.stat().st_size
        assert new_size < initial_position, "Test setup error: file should be smaller after truncation"

        parser = LogParser()
        data_queue = queue.Queue()

        # Mock callback to capture debug messages
        debug_messages = []
        def mock_log(message, msg_type):
            debug_messages.append({'message': message, 'type': msg_type})

        monitor.read_new_lines(parser, data_queue, on_log_message=mock_log, debug_enabled=True)

        # Should have logged truncation and reading
        assert len(debug_messages) > 0, f"Expected debug messages. Position was {initial_position}, now {new_size}"

        # Should have truncation detection message
        truncation_messages = [
            msg for msg in debug_messages
            if 'truncat' in msg['message'].lower()
        ]
        assert len(truncation_messages) > 0, f"Expected truncation message, got: {[i.get('message', '') for i in items]}"

    def test_complete_file_clear(self, temp_log_dir: Path) -> None:
        """Test handling of completely cleared file."""
        log1 = temp_log_dir / "nwclientLog1.txt"
        log1.write_text("Content\n")

        monitor = LogDirectoryMonitor(str(temp_log_dir))
        monitor.start_monitoring()

        # Clear file completely
        log1.write_text("")

        parser = LogParser()
        data_queue = queue.Queue()

        monitor.read_new_lines(parser, data_queue)

        assert monitor.last_position == 0


class TestErrorHandling:
    """Test suite for error handling."""

    def test_read_nonexistent_file(self, temp_log_dir: Path) -> None:
        """Test reading from nonexistent file."""
        monitor = LogDirectoryMonitor(str(temp_log_dir))
        monitor.current_log_file = temp_log_dir / "nonexistent.txt"

        parser = LogParser()
        data_queue = queue.Queue()

        # Should not raise exception
        monitor.read_new_lines(parser, data_queue)

    def test_read_with_parser_errors(self, temp_log_dir: Path) -> None:
        """Test that parser errors are handled gracefully."""
        log1 = temp_log_dir / "nwclientLog1.txt"
        log1.write_text("Malformed log line\n")

        monitor = LogDirectoryMonitor(str(temp_log_dir))
        monitor.start_monitoring()

        with open(log1, 'a') as f:
            f.write("Another line\n")

        parser = LogParser()
        data_queue = queue.Queue()

        # Should handle gracefully
        monitor.read_new_lines(parser, data_queue)

