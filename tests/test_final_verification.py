"""Final verification test - simulates EXACT user scenario.

This test proves that the fix works for the exact use case described:
1. Open game
2. Open app and click Start Monitoring
3. Start hitting target
4. Quit game (app still monitoring)
5. Open game again, start hitting target again
6. App should track immediately without user intervention
"""

import queue
import time
from pathlib import Path
import tempfile

from app.monitor import LogDirectoryMonitor
from app.parser import LogParser


def test_exact_user_scenario():
    """Verify the EXACT user scenario now works correctly."""
    print("=" * 70)
    print("FINAL VERIFICATION TEST - Exact User Scenario")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "nwclientLog1.txt"

        # Step 1: I open video game
        print("\n1. I open video game")
        with open(log_file, 'w') as f:
            pass  # Empty file initially
        print("   ✓ Game started, log file created")

        # Step 2: I open app and click Start Monitoring
        print("\n2. I open app and click Start Monitoring")
        monitor = LogDirectoryMonitor(tmpdir)
        monitor.start_monitoring()
        parser = LogParser(parse_immunity=False)
        data_queue = queue.Queue()
        is_monitoring = True
        print(f"   ✓ Monitoring started (position: {monitor.last_position})")

        # Simulate polling loop
        def simulate_poll():
            if is_monitoring:
                monitor.read_new_lines(parser, data_queue)

        # Step 3: I start hitting target, parser works as expected
        print("\n3. I start hitting target, parser works as expected")
        with open(log_file, 'a') as f:
            f.write("[Thu Jan 09 14:30:00] Your Greatsword hits Goblin Scout for 15 points of damage.\n")
            f.write("[Thu Jan 09 14:30:01] Your Greatsword hits Goblin Scout for 18 points of damage.\n")

        # Poll 1
        simulate_poll()
        items_before = []
        while not data_queue.empty():
            items_before.append(data_queue.get())

        info_msgs = [i for i in items_before if i.get('type') == 'info']
        print(f"   ✓ Parser tracked {len(info_msgs)} raw lines")
        print(f"   ✓ Monitor position: {monitor.last_position} bytes")

        # Step 4: I quit game - parser app is still up and "monitoring"
        print("\n4. I quit game - parser app is still up and 'monitoring'")
        print(f"   ✓ Log file size: {log_file.stat().st_size} bytes")
        print(f"   ✓ Monitor position: {monitor.last_position} bytes")
        print(f"   ✓ App still monitoring: {is_monitoring}")

        # Simulate some polling while game is closed
        time.sleep(0.1)
        simulate_poll()

        # Step 5: I open video game again, start hitting target again
        print("\n5. I open video game again, start hitting target again")
        print("   ⚠️  Game clears nwclientLog1.txt and starts writing fresh!")

        # Game clears file and writes new content
        with open(log_file, 'w') as f:
            f.write("[Thu Jan 09 14:35:00] Your Greatsword hits Orc Warrior for 20 points of damage.\n")
            f.write("[Thu Jan 09 14:35:01] Your Greatsword hits Orc Warrior for 22 points of damage.\n")

        new_size = log_file.stat().st_size
        print(f"   ✓ New log file size: {new_size} bytes")
        print(f"   ✓ Monitor position (stale): {monitor.last_position} bytes")
        print(f"   ✓ Truncation will be detected: {new_size < monitor.last_position}")

        # Step 6: Expected behavior - App keeps tracking immediately
        print("\n6. Expected Behavior: App keeps tracking immediately!")
        print("   (Without needing to click Pause/Start Monitoring)")

        # Next automatic poll (happens every 500ms)
        time.sleep(0.1)
        simulate_poll()

        items_after = []
        while not data_queue.empty():
            items_after.append(data_queue.get())

        # Verify results
        debug_msgs = [i for i in items_after if i.get('type') == 'debug']
        info_msgs = [i for i in items_after if i.get('type') == 'info']

        truncation_detected = any('truncat' in msg.get('message', '').lower() for msg in debug_msgs)
        orc_content = [msg for msg in info_msgs if 'Orc' in msg.get('message', '')]

        print(f"\n   ✓ Truncation detected: {truncation_detected}")
        print(f"   ✓ New content tracked: {len(orc_content)} lines with 'Orc'")
        print(f"   ✓ Monitor position updated: {monitor.last_position} bytes")

        # Show debug messages
        if debug_msgs:
            print("\n   Debug messages:")
            for msg in debug_msgs[:3]:  # Show first 3
                print(f"      - {msg.get('message', '')}")

        # Final verification
        print("\n" + "=" * 70)

        # Use proper assertions instead of return
        assert truncation_detected, "Truncation should have been detected"
        assert len(orc_content) >= 2, f"Expected at least 2 lines with 'Orc', got {len(orc_content)}"

        print("✅ SUCCESS! The app tracked new damage immediately after game restart!")
        print("   The user did NOT need to click Pause/Start Monitoring!")
        print("=" * 70)


if __name__ == '__main__':
    test_exact_user_scenario()

