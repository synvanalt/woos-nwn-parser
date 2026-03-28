"""Unit tests for hidden Debug Console tab unlock behavior."""

import tkinter as tk
from unittest.mock import Mock

import pytest

from app.ui.controllers.debug_unlock_controller import DebugUnlockController
from app.ui.main_window import WoosNwnParserApp
import app.ui.main_window as main_window_module
from app.ui.runtime_config import DEFAULT_APP_RUNTIME_CONFIG


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
    app.runtime_config = DEFAULT_APP_RUNTIME_CONFIG
    app._debug_tab_visible = False
    app.notebook = Mock()
    app.debug_panel = Mock()
    app.debug_unlock_controller = DebugUnlockController(
        notebook=app.notebook,
        policy=app.runtime_config.debug_unlock,
        is_debug_tab_visible=lambda: app._debug_tab_visible,
        on_unlock=app._show_debug_tab,
    )
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
        app.debug_unlock_controller.on_unlock = app._show_debug_tab

        times = iter([0.0, 0.4, 0.8, 1.2, 1.6, 2.0, 2.4])
        monkeypatch.setattr("app.ui.controllers.debug_unlock_controller.time.monotonic", lambda: next(times))

        for _ in range(7):
            app.debug_unlock_controller.record_click_and_maybe_unlock()

        app._show_debug_tab.assert_called_once()

    def test_clicks_outside_window_do_not_unlock(self, monkeypatch):
        app = _build_unlock_shell()
        app._show_debug_tab = Mock()
        app.debug_unlock_controller.on_unlock = app._show_debug_tab

        times = iter([0.0, 0.5, 1.0, 4.1, 4.6, 5.1, 5.6])
        monkeypatch.setattr("app.ui.controllers.debug_unlock_controller.time.monotonic", lambda: next(times))

        for _ in range(7):
            app.debug_unlock_controller.record_click_and_maybe_unlock()

        app._show_debug_tab.assert_not_called()

    def test_non_dps_click_resets_sequence(self):
        app = _build_unlock_shell()
        app._show_debug_tab = Mock()
        app.debug_unlock_controller.on_unlock = app._show_debug_tab
        app.notebook.identify.return_value = "label"
        app.notebook.index.return_value = 1
        app.notebook.tab.return_value = "Target Stats"

        for _ in range(3):
            app.debug_unlock_controller.record_click_and_maybe_unlock()
        event = Mock(x=10, y=10)
        app._on_notebook_click(event)
        for _ in range(4):
            app.debug_unlock_controller.record_click_and_maybe_unlock()

        app._show_debug_tab.assert_not_called()

    def test_show_debug_tab_is_idempotent(self):
        app = _build_unlock_shell()
        app.notebook = Mock()
        app.debug_unlock_controller.notebook = app.notebook

        app._show_debug_tab()
        app._show_debug_tab()

        app.notebook.add.assert_called_once_with(
            app.debug_panel,
            text=DEFAULT_APP_RUNTIME_CONFIG.debug_unlock.debug_tab_text,
        )
        assert app._debug_tab_visible is True
