import io
from pathlib import Path

from app_round_time.log_reader import LogReader


def test_log_reader_rotation_and_truncation(tmp_path: Path):
    log1 = tmp_path / "nwclientLog1.txt"
    log2 = tmp_path / "nwclientLog2.txt"

    log1.write_text("line1\n", encoding="utf-8")
    log2.write_text("", encoding="utf-8")

    reader = LogReader(str(tmp_path))
    reader.initialize(start_at_end=False)

    captured = []

    def on_line(line: str, wall_time_ns: int, perf_ns: int) -> None:
        captured.append(line.strip())

    reader.read_new_lines(on_line)
    assert "line1" in captured

    # Simulate rotation: update log2 mtime to be newest
    log2.write_text("line2\n", encoding="utf-8")
    reader.read_new_lines(on_line)
    assert "line2" in captured

    # Truncate log2
    log2.write_text("line3\n", encoding="utf-8")
    reader.read_new_lines(on_line)
    assert "line3" in captured
