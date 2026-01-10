"""Test log file rotation functionality.

This test verifies that the monitor correctly handles rotation from
nwclientLog1.txt → nwclientLog2.txt → nwclientLog3.txt → nwclientLog4.txt
when log files fill up, and that truncation detection didn't break this.
"""

import queue
import time
from pathlib import Path
import tempfile

from app.monitor import LogDirectoryMonitor
from app.parser import LogParser


def test_basic_rotation_log1_to_log2():
    """Test rotation from nwclientLog1.txt to nwclientLog2.txt."""
    print("=== Test: Basic Rotation (Log1 → Log2) ===\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        log1 = Path(tmpdir) / "nwclientLog1.txt"
        log2 = Path(tmpdir) / "nwclientLog2.txt"

        # Setup: Game writes to log1
        print("Step 1: Game writes to nwclientLog1.txt")
        with open(log1, 'w') as f:
            f.write("[Thu Jan 09 14:00:00] You attack Goblin: *hit*: (10 damage)\n")
            f.write("[Thu Jan 09 14:00:01] You attack Goblin: *hit*: (12 damage)\n")
        print(f"  Log1 size: {log1.stat().st_size} bytes\n")

        # Start monitoring
        print("Step 2: Start monitoring")
        monitor = LogDirectoryMonitor(tmpdir)
        monitor.start_monitoring()
        parser = LogParser(parse_immunity=False)
        data_queue = queue.Queue()

        assert monitor.current_log_file == log1, "Should start with log1"
        print(f"  Monitoring: {monitor.current_log_file.name}")
        print(f"  Position: {monitor.last_position} bytes\n")

        # Append to log1
        print("Step 3: More content in log1")
        time.sleep(0.05)  # Small delay to ensure different mtime
        with open(log1, 'a') as f:
            f.write("[Thu Jan 09 14:00:02] You attack Goblin: *hit*: (15 damage)\n")

        monitor.read_new_lines(parser, data_queue)
        items = []
        while not data_queue.empty():
            items.append(data_queue.get())

        info_msgs = [i for i in items if i.get('type') == 'info']
        print(f"  Read {len(info_msgs)} line(s) from log1")
        print(f"  Position: {monitor.last_position} bytes\n")

        # Log1 fills up, game starts writing to log2
        print("Step 4: Log1 fills up, game rotates to nwclientLog2.txt")
        time.sleep(0.1)  # Ensure log2 has newer mtime
        with open(log2, 'w') as f:
            f.write("[Thu Jan 09 14:01:00] You attack Orc: *hit*: (20 damage)\n")
            f.write("[Thu Jan 09 14:01:01] You attack Orc: *hit*: (22 damage)\n")
        print(f"  Log2 created: {log2.stat().st_size} bytes")
        print(f"  Log2 mtime > Log1 mtime: {log2.stat().st_mtime > log1.stat().st_mtime}\n")

        # Next poll should detect rotation
        print("Step 5: Next poll detects rotation")
        monitor.read_new_lines(parser, data_queue)

        items = []
        while not data_queue.empty():
            items.append(data_queue.get())

        debug_msgs = [i for i in items if i.get('type') == 'debug']
        info_msgs = [i for i in items if i.get('type') == 'info']

        # Check rotation was detected
        rotation_detected = any('rotation' in msg.get('message', '').lower() for msg in debug_msgs)
        orc_content = [msg for msg in info_msgs if 'Orc' in msg.get('message', '')]

        print(f"  Rotation detected: {rotation_detected}")
        print(f"  Now monitoring: {monitor.current_log_file.name if monitor.current_log_file else 'None'}")
        print(f"  Position: {monitor.last_position} bytes")
        print(f"  Content from log2: {len(orc_content)} lines with 'Orc'\n")

        # Show debug messages
        if debug_msgs:
            print("  Debug messages:")
            for msg in debug_msgs[:5]:
                if 'rotation' in msg.get('message', '').lower() or 'Read' in msg.get('message', ''):
                    print(f"    - {msg.get('message', '')}")

        # Verify
        assert rotation_detected, "Rotation should be detected"
        assert monitor.current_log_file == log2, "Should now monitor log2"
        assert len(orc_content) >= 2, "Should read content from log2"
        assert monitor.last_position > 0, "Position should be updated"

        print("\n✓ Test passed: Basic rotation works correctly\n")


def test_full_rotation_sequence():
    """Test full rotation sequence: Log1 → Log2 → Log3 → Log4."""
    print("=== Test: Full Rotation Sequence (Log1 → Log2 → Log3 → Log4) ===\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        log_files = [Path(tmpdir) / f"nwclientLog{i}.txt" for i in range(1, 5)]

        # Create log1
        print("Step 1: Game starts with nwclientLog1.txt")
        with open(log_files[0], 'w') as f:
            f.write("[Thu Jan 09 14:00:00] Combat in Log1\n")

        # Start monitoring
        monitor = LogDirectoryMonitor(tmpdir)
        monitor.start_monitoring()
        parser = LogParser(parse_immunity=False)
        data_queue = queue.Queue()

        print(f"  Monitoring: {monitor.current_log_file.name}\n")

        # Simulate rotation through all 4 log files
        for i in range(1, 4):  # Rotate to log2, log3, log4
            current_log = log_files[i - 1]
            next_log = log_files[i]

            print(f"Step {i + 1}: Game rotates to nwclientLog{i + 1}.txt")
            time.sleep(0.1)  # Ensure different mtime

            with open(next_log, 'w') as f:
                f.write(f"[Thu Jan 09 14:{i:02d}:00] Combat in Log{i + 1}\n")

            # Poll
            monitor.read_new_lines(parser, data_queue)

            # Clear queue
            items = []
            while not data_queue.empty():
                items.append(data_queue.get())

            debug_msgs = [item for item in items if item.get('type') == 'debug']
            rotation_msg = [msg for msg in debug_msgs if 'rotation' in msg.get('message', '').lower()]

            if rotation_msg:
                print(f"  ✓ {rotation_msg[0].get('message', '')}")

            assert monitor.current_log_file == next_log, f"Should now monitor log{i + 1}"
            print(f"  ✓ Now monitoring: {monitor.current_log_file.name}\n")

        print("✓ Test passed: Full rotation sequence works correctly\n")


def test_rotation_does_not_trigger_truncation_warning():
    """Verify that rotation doesn't trigger false truncation warnings."""
    print("=== Test: Rotation Does NOT Trigger Truncation Warning ===\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        log1 = Path(tmpdir) / "nwclientLog1.txt"
        log2 = Path(tmpdir) / "nwclientLog2.txt"

        # Create log1 with content
        print("Step 1: Create log1 with content")
        with open(log1, 'w') as f:
            f.write("[Thu Jan 09 14:00:00] Combat in Log1\n" * 10)

        # Start monitoring
        monitor = LogDirectoryMonitor(tmpdir)
        monitor.start_monitoring()
        parser = LogParser(parse_immunity=False)
        data_queue = queue.Queue()

        initial_position = monitor.last_position
        print(f"  Initial position: {initial_position} bytes\n")

        # Create log2 (rotation)
        print("Step 2: Create log2 (rotation)")
        time.sleep(0.1)
        with open(log2, 'w') as f:
            f.write("[Thu Jan 09 14:01:00] Combat in Log2\n")

        # Poll - should detect rotation, NOT truncation
        monitor.read_new_lines(parser, data_queue)

        items = []
        while not data_queue.empty():
            items.append(data_queue.get())

        debug_msgs = [i for i in items if i.get('type') == 'debug']

        rotation_detected = any('rotation' in msg.get('message', '').lower() for msg in debug_msgs)
        truncation_detected = any('truncat' in msg.get('message', '').lower() for msg in debug_msgs)

        print(f"  Rotation detected: {rotation_detected}")
        print(f"  Truncation detected: {truncation_detected}")
        print(f"  Now monitoring: {monitor.current_log_file.name}\n")

        # Verify
        assert rotation_detected, "Should detect rotation"
        assert not truncation_detected, "Should NOT detect truncation during rotation"
        assert monitor.current_log_file == log2, "Should monitor log2"

        print("✓ Test passed: Rotation doesn't trigger false truncation warnings\n")


def test_truncation_on_same_file_still_works():
    """Verify truncation detection still works on the same file (non-rotation)."""
    print("=== Test: Truncation Detection Still Works (Same File) ===\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        log1 = Path(tmpdir) / "nwclientLog1.txt"

        # Create log1 with content
        print("Step 1: Create log1 with initial content")
        with open(log1, 'w') as f:
            f.write("[Thu Jan 09 14:00:00] Combat before restart\n" * 5)

        # Start monitoring
        monitor = LogDirectoryMonitor(tmpdir)
        monitor.start_monitoring()
        parser = LogParser(parse_immunity=False)
        data_queue = queue.Queue()

        initial_position = monitor.last_position
        print(f"  Initial position: {initial_position} bytes\n")

        # Truncate the SAME file (game restart)
        print("Step 2: Truncate log1 (game restart)")
        time.sleep(0.1)
        with open(log1, 'w') as f:  # Truncates!
            f.write("[Thu Jan 09 14:05:00] Combat after restart\n")

        new_size = log1.stat().st_size
        print(f"  New size: {new_size} bytes")
        print(f"  Truncation: {new_size < initial_position}\n")

        # Poll - should detect truncation
        monitor.read_new_lines(parser, data_queue)

        items = []
        while not data_queue.empty():
            items.append(data_queue.get())

        debug_msgs = [i for i in items if i.get('type') == 'debug']

        truncation_detected = any('truncat' in msg.get('message', '').lower() for msg in debug_msgs)

        print(f"  Truncation detected: {truncation_detected}")
        print(f"  Still monitoring: {monitor.current_log_file.name}")
        print(f"  Position reset to: {monitor.last_position} bytes\n")

        # Verify
        assert truncation_detected, "Should detect truncation"
        assert monitor.current_log_file == log1, "Should still monitor log1"
        assert monitor.last_position < initial_position, "Position should be reset"

        print("✓ Test passed: Truncation detection still works\n")


def test_rotation_with_content_continuation():
    """Test that content reading continues correctly after rotation."""
    print("=== Test: Content Continues After Rotation ===\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        log1 = Path(tmpdir) / "nwclientLog1.txt"
        log2 = Path(tmpdir) / "nwclientLog2.txt"

        # Create log1
        print("Step 1: Create log1")
        with open(log1, 'w') as f:
            f.write("[Thu Jan 09 14:00:00] Goblin hit\n")

        # Start monitoring
        monitor = LogDirectoryMonitor(tmpdir)
        monitor.start_monitoring()
        parser = LogParser(parse_immunity=False)
        data_queue = queue.Queue()

        # Poll log1
        monitor.read_new_lines(parser, data_queue)
        while not data_queue.empty():
            data_queue.get()

        print(f"  Monitoring log1, position: {monitor.last_position}\n")

        # Rotate to log2
        print("Step 2: Rotate to log2")
        time.sleep(0.1)
        with open(log2, 'w') as f:
            f.write("[Thu Jan 09 14:01:00] Orc hit line 1\n")
            f.write("[Thu Jan 09 14:01:01] Orc hit line 2\n")

        # Poll - should read ALL content from log2
        monitor.read_new_lines(parser, data_queue)

        items = []
        while not data_queue.empty():
            items.append(data_queue.get())

        info_msgs = [i for i in items if i.get('type') == 'info']
        orc_lines = [msg for msg in info_msgs if 'Orc' in msg.get('message', '')]

        print(f"  Read {len(orc_lines)} lines with 'Orc' from log2")
        print(f"  Position in log2: {monitor.last_position} bytes\n")

        # Now append more to log2
        print("Step 3: Append more to log2")
        with open(log2, 'a') as f:
            f.write("[Thu Jan 09 14:01:02] Orc hit line 3\n")

        # Poll again
        monitor.read_new_lines(parser, data_queue)

        items = []
        while not data_queue.empty():
            items.append(data_queue.get())

        info_msgs = [i for i in items if i.get('type') == 'info']
        line3 = [msg for msg in info_msgs if 'line 3' in msg.get('message', '')]

        print(f"  Read {len(line3)} more line(s) from log2")
        print(f"  Final position: {monitor.last_position} bytes\n")

        # Verify
        assert len(orc_lines) >= 2, "Should read initial 2 lines from log2"
        assert len(line3) >= 1, "Should read appended line from log2"

        print("✓ Test passed: Content reading continues correctly after rotation\n")


if __name__ == '__main__':
    print("=" * 70)
    print("LOG FILE ROTATION TESTS")
    print("Verifying truncation detection didn't break rotation functionality")
    print("=" * 70)
    print()

    try:
        test_basic_rotation_log1_to_log2()
        test_full_rotation_sequence()
        test_rotation_does_not_trigger_truncation_warning()
        test_truncation_on_same_file_still_works()
        test_rotation_with_content_continuation()

        print("=" * 70)
        print("✅ ALL ROTATION TESTS PASSED!")
        print("✅ Truncation detection did NOT break rotation functionality")
        print("=" * 70)
    except AssertionError as e:
        print("=" * 70)
        print(f"❌ TEST FAILED: {e}")
        print("=" * 70)
        raise

