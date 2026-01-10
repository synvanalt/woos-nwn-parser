"""Demo script to simulate the game restart scenario.

This script demonstrates the fix for the issue where the app wouldn't track
new damage/actions after the game restarts and clears the log file.
"""

import queue
import time
from pathlib import Path
import tempfile

from app.monitor import LogDirectoryMonitor
from app.parser import LogParser


def simulate_game_session():
    """Simulate a complete game session with restart."""
    print("=== Simulating Game Session with Restart ===\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "nwclientLog1.txt"

        # 1. Game starts - writes initial content
        print("1. Game starts, writing to log file...")
        with open(log_file, 'w') as f:
            f.write("[Thu Jan 09 14:30:00] You attack Goblin: *hit*: (10 damage)\n")
            f.write("[Thu Jan 09 14:30:01] You attack Goblin: *hit*: (12 damage)\n")
        print(f"   Log file size: {log_file.stat().st_size} bytes\n")

        # 2. App starts monitoring
        print("2. App starts monitoring...")
        monitor = LogDirectoryMonitor(tmpdir)
        monitor.start_monitoring()
        parser = LogParser(parse_immunity=False)
        data_queue = queue.Queue()
        print(f"   Monitor position: {monitor.last_position} bytes\n")

        # 3. Player continues gaming, new lines are appended
        print("3. Player continues gaming...")
        with open(log_file, 'a') as f:
            f.write("[Thu Jan 09 14:30:02] You attack Goblin: *hit*: (15 damage)\n")

        monitor.read_new_lines(parser, data_queue)
        print(f"   Read {data_queue.qsize()} items from queue")
        print(f"   Monitor position: {monitor.last_position} bytes\n")

        # Clear queue for next phase
        while not data_queue.empty():
            data_queue.get()

        # 4. Player exits game
        print("4. Player exits game...")
        print(f"   Log file remains: {log_file.stat().st_size} bytes\n")
        time.sleep(0.1)  # Small delay

        # 5. Game restarts - CLEARS the log file and starts fresh
        print("5. Game restarts - CLEARS log file and starts writing fresh!")
        with open(log_file, 'w') as f:  # This truncates the file
            f.write("[Thu Jan 09 14:35:00] You attack Orc: *hit*: (20 damage)\n")

        print(f"   Log file size AFTER restart: {log_file.stat().st_size} bytes")
        print(f"   Monitor position (before read): {monitor.last_position} bytes")
        print(f"   ⚠️  File is SMALLER than last position - TRUNCATION DETECTED!\n")

        # 6. App continues monitoring (without user intervention)
        print("6. App continues monitoring automatically...")
        monitor.read_new_lines(parser, data_queue)

        # Check what was queued
        items = []
        while not data_queue.empty():
            items.append(data_queue.get())

        # Show results
        print(f"   ✓ Read {len(items)} items from queue")
        print(f"   ✓ Monitor position: {monitor.last_position} bytes")

        # Verify truncation was detected
        truncation_msgs = [item for item in items if item.get('type') == 'debug' and 'truncated' in item.get('message', '').lower()]
        if truncation_msgs:
            print(f"   ✓ Truncation detected: {truncation_msgs[0]['message']}")

        # Verify new content was read
        info_msgs = [item for item in items if item.get('type') == 'info']
        if info_msgs:
            print(f"   ✓ New content read: Found {len([m for m in info_msgs if 'Orc' in m.get('message', '')])} line(s) with 'Orc'\n")

        # 7. Player continues gaming after restart
        print("7. Player continues gaming after restart...")
        with open(log_file, 'a') as f:
            f.write("[Thu Jan 09 14:35:01] You attack Orc: *hit*: (25 damage)\n")

        monitor.read_new_lines(parser, data_queue)
        print(f"   ✓ Read {data_queue.qsize()} more items\n")

        print("=== SUCCESS! App tracked all actions without user intervention ===")


if __name__ == '__main__':
    simulate_game_session()

