import unittest
from unittest.mock import AsyncMock, patch

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.services import meet_bot


class _Locator:
    def __init__(self, page, kind):
        self.page = page
        self.kind = kind

    async def wait_for(self, state, timeout=None):
        if self.kind == "settings" and not self.page.dialog_visible:
            raise PlaywrightTimeoutError("settings dialog did not open")
        if self.kind == "audio_settings" and not self.page.button_visible:
            raise PlaywrightTimeoutError("Audio settings button missing")

    async def count(self):
        return 1

    async def is_visible(self):
        return self.kind == "settings" and self.page.dialog_visible

    async def click(self, timeout=None):
        if self.kind == "camera_warning":
            return
        raise PlaywrightTimeoutError(
            "<div class='VYBDae-Bz112c-RLmnJb'> from Meet toolbar subtree "
            "intercepts pointer events"
        )

    async def focus(self, timeout=None):
        self.page.focused = self.kind == "audio_settings"

    async def evaluate(self, _expression):
        if self.kind == "audio_settings":
            return self.page.focused
        return None

    async def get_attribute(self, name):
        if name == "aria-expanded":
            return "true" if self.page.dialog_visible else "false"
        return None

    async def aria_snapshot(self):
        return "- dialog \"Settings\"" if self.page.dialog_visible else ""


class _Page:
    def __init__(self):
        self.dialog_visible = False
        self.button_visible = True
        self.focused = False
        self.keyboard = AsyncMock()
        self.keyboard.press.side_effect = self._press_key

    async def _press_key(self, key):
        if key == "Enter" and self.focused and self.open_on_enter:
            self.dialog_visible = True

    open_on_enter = True

    def get_by_role(self, role, name=None, **_kwargs):
        if role == "button" and name == "Audio settings":
            return _Locator(self, "audio_settings")
        if role == "dialog" and name == "Settings":
            return _Locator(self, "settings")
        if role == "dialog" and name == "Camera might be blocked":
            return _Locator(self, "camera_warning")
        if role == "dialog":
            return _Locator(self, "other_dialog")
        raise AssertionError(f"Unexpected locator: {role=} {name=}")


class MeetAudioSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_pointer_interception_uses_focused_enter_without_reclicking(self):
        page = _Page()

        await meet_bot.open_meet_audio_settings(page)

        page.keyboard.press.assert_awaited_once_with("Enter")
        self.assertTrue(page.dialog_visible)

    async def test_interaction_fails_closed_when_dialog_never_opens(self):
        page = _Page()
        page.open_on_enter = False

        with patch.object(meet_bot, "log_audio_settings_diagnostics", new=AsyncMock()):
            with self.assertRaisesRegex(RuntimeError, "Settings dialog did not become visible"):
                await meet_bot.open_meet_audio_settings(page)

        page.keyboard.press.assert_awaited_once_with("Enter")
        self.assertFalse(page.dialog_visible)


if __name__ == "__main__":
    unittest.main()
