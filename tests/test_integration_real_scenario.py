"""Integration test to simulate the exact user scenario with polling.

This test mimics the actual app behavior with polling every 500ms.
"""

import queue
import time
from pathlib import Path
import tempfile

from app.monitor import LogDirectoryMonitor
from app.parser import LogParser


def test_real_world_scenario():
    """Test the exact scenario: monitoring with polling, game restart, continue monitoring."""
    print("=== Real-world Integration Test ===\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "nwclientLog1.txt"

        # Step 1: Game starts and writes initial content
        print("Step 1: Game starts")
        with open(log_file, 'w') as f:
            f.write("[Thu Jan 09 14:30:00] You attack Goblin: *hit*: (10 damage)\n")
            f.write("[Thu Jan 09 14:30:01] You attack Goblin: *hit*: (12 damage)\n")
        print(f"  Log file created: {log_file.stat().st_size} bytes\n")

        # Step 2: App starts monitoring
        print("Step 2: App starts monitoring")
        monitor = LogDirectoryMonitor(tmpdir)
        monitor.start_monitoring()
        parser = LogParser(parse_immunity=False)
        data_queue = queue.Queue()
        print(f"  Monitor initialized at position: {monitor.last_position} bytes\n")

        # Step 3: Simulate first poll - should read nothing (already at end)
        print("Step 3: First poll (no new data)")
        monitor.read_new_lines(parser, data_queue)
        items = []
        while not data_queue.empty():
            items.append(data_queue.get())
        print(f"  Items queued: {len(items)}")
        print(f"  Monitor position: {monitor.last_position} bytes\n")

        # Step 4: Player continues gaming
        print("Step 4: Player hits more")
        time.sleep(0.1)
        with open(log_file, 'a') as f:
            f.write("[Thu Jan 09 14:30:02] You attack Goblin: *hit*: (15 damage)\n")
        print(f"  Log file size: {log_file.stat().st_size} bytes")

        # Poll again
        monitor.read_new_lines(parser, data_queue)
        items = []
        while not data_queue.empty():
            items.append(data_queue.get())
        print(f"  Items queued: {len(items)}")
        print(f"  Monitor position: {monitor.last_position} bytes\n")

        # Step 5: Game exits
        print("Step 5: Game exits")
        old_size = log_file.stat().st_size
        print(f"  Log file remains: {old_size} bytes")
        print(f"  Monitor position: {monitor.last_position} bytes\n")
        time.sleep(0.2)

        # Step 6: Game restarts - CLEARS file and starts fresh
        print("Step 6: ⚠️  GAME RESTARTS - FILE IS TRUNCATED!")
        with open(log_file, 'w') as f:  # This truncates!
            f.write("[Thu Jan 09 14:35:00] You attack Orc: *hit*: (20 damage)\n")

        new_size = log_file.stat().st_size
        print(f"  Old file size: {old_size} bytes")
        print(f"  New file size: {new_size} bytes")
        print(f"  Monitor position (stale): {monitor.last_position} bytes")
        print(f"  ⚠️  TRUNCATION: new size < monitor position? {new_size < monitor.last_position}\n")

        # Step 7: Next poll happens (without user touching anything!)
        print("Step 7: Next automatic poll (500ms later)")
        monitor.read_new_lines(parser, data_queue)

        items = []
        while not data_queue.empty():
            items.append(data_queue.get())

        print(f"  Items queued: {len(items)}")
        print(f"  Monitor position: {monitor.last_position} bytes")

        # Check results
        debug_msgs = [i for i in items if i.get('type') == 'debug']
        info_msgs = [i for i in items if i.get('type') == 'info']

        print(f"\n  Debug messages: {len(debug_msgs)}")
        for msg in debug_msgs:
            print(f"    - {msg.get('message', '')}")

        truncation_detected = any('truncat' in msg.get('message', '').lower() for msg in debug_msgs)
        new_content_found = any('Orc' in msg.get('message', '') for msg in info_msgs)

        print(f"\n  ✓ Truncation detected: {truncation_detected}")
        print(f"  ✓ New content (Orc) found: {new_content_found}")

        if truncation_detected and new_content_found:
            print("\n=== ✓ TEST PASSED: App correctly handled game restart! ===")
        else:
            print("\n=== ✗ TEST FAILED: App did not handle game restart correctly! ===")
            raise AssertionError("Truncation not handled correctly")

        # Step 8: Verify continued monitoring works
        print("\nStep 8: Player continues gaming after restart")
        with open(log_file, 'a') as f:
            f.write("[Thu Jan 09 14:35:01] You attack Orc: *hit*: (25 damage)\n")

        monitor.read_new_lines(parser, data_queue)
        items = []
        while not data_queue.empty():
            items.append(data_queue.get())

        continued_content = any('25 damage' in msg.get('message', '') for msg in items if msg.get('type') == 'info')
        print(f"  ✓ Continued content detected: {continued_content}")

        if not continued_content:
            raise AssertionError("Continued monitoring failed")

        print("\n=== ✓ FULL TEST PASSED ===")


if __name__ == '__main__':
    test_real_world_scenario()

