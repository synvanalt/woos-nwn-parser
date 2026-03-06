"""Additional edge-case tests for LogDirectoryMonitor."""

from types import SimpleNamespace
from unittest.mock import Mock
import queue

from app.monitor import LogDirectoryMonitor


class _FakeFileHandle:
    """Simple context-managed file object for monitor tests."""

    def __init__(self, lines: list[str], tell_value: int) -> None:
        self._lines = lines
        self._tell_value = tell_value

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def seek(self, _pos: int) -> None:
        return None

    def readlines(self) -> list[str]:
        return self._lines

    def tell(self) -> int:
        return self._tell_value


def test_read_new_lines_emits_error_on_open_failure(monkeypatch) -> None:
    monitor = LogDirectoryMonitor("C:/logs")
    current_file = Mock()
    current_file.exists.return_value = True
    current_file.stat.return_value = SimpleNamespace(st_size=10, st_mtime=10.0)
    current_file.name = "nwclientLog1.txt"
    monitor.current_log_file = current_file
    monitor.last_position = 0

    monkeypatch.setattr(monitor, "get_active_log_file", lambda: current_file)
    monkeypatch.setattr("builtins.open", Mock(side_effect=OSError("disk is busy")))

    messages: list[tuple[str, str]] = []
    parser = Mock()
    monitor.read_new_lines(
        parser,
        queue.Queue(),
        on_log_message=lambda msg, msg_type: messages.append((msg, msg_type)),
        debug_enabled=True,
    )

    assert any(msg_type == "error" and "I/O Error" in msg for msg, msg_type in messages)


def test_read_new_lines_emits_error_when_parser_raises(monkeypatch) -> None:
    monitor = LogDirectoryMonitor("C:/logs")
    current_file = Mock()
    current_file.exists.return_value = True
    current_file.stat.return_value = SimpleNamespace(st_size=20, st_mtime=20.0)
    current_file.name = "nwclientLog1.txt"
    monitor.current_log_file = current_file

    monkeypatch.setattr(monitor, "get_active_log_file", lambda: current_file)
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: _FakeFileHandle(["line-1\n"], 7))

    parser = Mock()
    parser.parse_line.side_effect = RuntimeError("parser boom")

    messages: list[tuple[str, str]] = []
    monitor.read_new_lines(
        parser,
        queue.Queue(),
        on_log_message=lambda msg, msg_type: messages.append((msg, msg_type)),
        debug_enabled=False,
    )

    assert any(msg_type == "error" and "I/O Error" in msg for msg, msg_type in messages)


def test_read_new_lines_rotation_to_none_does_not_crash(monkeypatch) -> None:
    monitor = LogDirectoryMonitor("C:/logs")
    previous_file = Mock()
    previous_file.name = "nwclientLog1.txt"
    monitor.current_log_file = previous_file

    # Simulate an unexpected "no active file" during rotation check.
    monkeypatch.setattr(monitor, "get_active_log_file", lambda: None)

    messages: list[tuple[str, str]] = []
    monitor.read_new_lines(
        parser=Mock(),
        data_queue=queue.Queue(),
        on_log_message=lambda msg, msg_type: messages.append((msg, msg_type)),
        debug_enabled=True,
    )

    assert any(msg_type == "error" and "I/O Error" in msg for msg, msg_type in messages)


def test_read_new_lines_logs_truncation_warning_and_resets_position(monkeypatch) -> None:
    monitor = LogDirectoryMonitor("C:/logs")
    current_file = Mock()
    current_file.exists.return_value = True
    current_file.name = "nwclientLog1.txt"
    current_file.stat.return_value = SimpleNamespace(st_size=4, st_mtime=30.0)
    monitor.current_log_file = current_file
    monitor.last_position = 50

    monkeypatch.setattr(monitor, "get_active_log_file", lambda: current_file)
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: _FakeFileHandle(["x\n"], 2))

    messages: list[tuple[str, str]] = []
    monitor.read_new_lines(
        parser=Mock(parse_line=Mock(return_value=None)),
        data_queue=queue.Queue(),
        on_log_message=lambda msg, msg_type: messages.append((msg, msg_type)),
        debug_enabled=False,
    )

    assert any(msg_type == "warning" and "truncat" in msg.lower() for msg, msg_type in messages)
    assert monitor.last_position == 2
