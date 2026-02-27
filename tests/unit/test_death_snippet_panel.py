"""Unit tests for DeathSnippetPanel formatting behavior."""

from app.ui.widgets.death_snippet_panel import DeathSnippetPanel


class TestDeathSnippetPanel:
    """Test suite for DeathSnippetPanel helper behavior."""

    def test_sanitize_display_line_removes_chat_window_prefix(self) -> None:
        line = "[CHAT WINDOW TEXT] [Tue Jan 13 19:59:36] Your God refuses to hear your prayers!"
        sanitized = DeathSnippetPanel._sanitize_display_line(line)
        assert sanitized == "[Tue Jan 13 19:59:36] Your God refuses to hear your prayers!"

    def test_sanitize_display_line_leaves_non_prefixed_line_unchanged(self) -> None:
        line = "[Tue Jan 13 19:59:36] HYDROXYS killed Woo Wildrock"
        sanitized = DeathSnippetPanel._sanitize_display_line(line)
        assert sanitized == line
