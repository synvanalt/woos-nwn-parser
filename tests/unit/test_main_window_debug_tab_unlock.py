"""Unit tests for hidden Debug Console tab unlock behavior."""

from collections import deque
import tkinter as tk
from unittest.mock import Mock

import pytest

from app.ui.main_window import WoosNwnParserApp
import app.ui.main_window as main_window_module


def _can_create_tk_root() -> bool:
    """Check if Tk root creation is possible in this environment."""
    try:
        root = tk.Tk()
        root.withdraw()
        root.update_idletasks()
        root.destroy()
        return True
    except (tk.TclError, RuntimeError, Exception):
        return False


_TK_AVAILABLE = _can_create_tk_root()


def _build_unlock_shell() -> WoosNwnParserApp:
    """Create a minimal app shell for unlock logic tests."""
    app = WoosNwnParserApp.__new__(WoosNwnParserApp)
    app._debug_tab_visible = False
    app._dps_tab_click_times = deque()
    app._debug_unlock_click_target = 7
    app._debug_unlock_window_seconds = 3.0
    app._dps_tab_text = "Damage Per Second"
    app.notebook = Mock()
    app.debug_panel = Mock()
    return app


class TestDebugTabUnlock:
    """Test suite for hidden debug tab reveal gesture behavior."""

    def test_debug_tab_hidden_on_startup(self, monkeypatch):
        if not _TK_AVAILABLE:
            pytest.skip("Tkinter not available")

        try:
            root = tk.Tk()
        except tk.TclError:
            pytest.skip("Tkinter not available")
        root.withdraw()
        try:
            monkeypatch.setattr(main_window_module, "get_default_log_directory", lambda: None)
            monkeypatch.setattr(main_window_module.WoosNwnParserApp, "process_queue", lambda self: None)
            monkeypatch.setattr(main_window_module.font, "nametofont", lambda _: Mock())

            app = WoosNwnParserApp(root)
            tab_titles = [app.notebook.tab(tab_id, "text") for tab_id in app.notebook.tabs()]

            assert "Debug Console" not in tab_titles
            assert "Damage Per Second" in tab_titles
            assert "Target Stats" in tab_titles
            assert "Target Immunities" in tab_titles
            assert "Death Snippets" in tab_titles
            assert app._debug_tab_visible is False
        finally:
            root.destroy()

    def test_seven_clicks_within_window_unlocks(self, monkeypatch):
        app = _build_unlock_shell()
        app._show_debug_tab = Mock()

        times = iter([0.0, 0.4, 0.8, 1.2, 1.6, 2.0, 2.4])
        monkeypatch.setattr(main_window_module.time, "monotonic", lambda: next(times))

        for _ in range(7):
            app._record_dps_tab_click_and_maybe_unlock()

        app._show_debug_tab.assert_called_once()
        assert len(app._dps_tab_click_times) == 0

    def test_clicks_outside_window_do_not_unlock(self, monkeypatch):
        app = _build_unlock_shell()
        app._show_debug_tab = Mock()

        times = iter([0.0, 0.5, 1.0, 4.1, 4.6, 5.1, 5.6])
        monkeypatch.setattr(main_window_module.time, "monotonic", lambda: next(times))

        for _ in range(7):
            app._record_dps_tab_click_and_maybe_unlock()

        app._show_debug_tab.assert_not_called()

    def test_non_dps_click_resets_sequence(self):
        app = _build_unlock_shell()
        app._dps_tab_click_times.extend([1.0, 1.2, 1.4])
        app.notebook.identify.return_value = "label"
        app.notebook.index.return_value = 1
        app.notebook.tab.return_value = "Target Stats"

        event = Mock(x=10, y=10)
        app._on_notebook_click(event)

        assert len(app._dps_tab_click_times) == 0

    def test_show_debug_tab_is_idempotent(self):
        app = _build_unlock_shell()
        app.notebook = Mock()

        app._show_debug_tab()
        app._show_debug_tab()

        app.notebook.add.assert_called_once_with(app.debug_panel, text="Debug Console")
        assert app._debug_tab_visible is True
