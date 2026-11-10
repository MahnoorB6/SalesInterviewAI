import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.services import meet_bot


class _Locator:
    def __init__(self, visible=False, page=None, label=""):
        self.first = self
        self.visible = visible
        self.page = page
        self.label = label

    async def wait_for(self, **_kwargs):
        if not self.visible:
            raise TimeoutError(self.label)

    async def is_visible(self):
        return self.visible

    async def click(self, **_kwargs):
        if self.page is not None:
            self.page.clicked.append(self.label)


class _Page:
    def __init__(self):
        self.clicked = []

    async def goto(self, *_args, **_kwargs):
        pass

    async def wait_for_load_state(self, *_args, **_kwargs):
        pass

    async def wait_for_timeout(self, *_args, **_kwargs):
        pass

    def get_by_role(self, _role, name, **_kwargs):
        return _Locator(name in ("Join now", "Leave call"), self, name)

    def get_by_text(self, text, exact=False):
        # Model a visible generic Leave text node, which must never be clicked
        # while Meet is transitioning from its pre-join screen.
        return _Locator(text == "Leave" and exact, self, text)


class MeetJoinTests(unittest.IsolatedAsyncioTestCase):
    async def test_clicks_join_control_without_clicking_generic_leave_text(self):
        page = _Page()
        with patch.object(
            meet_bot, "select_meet_microphone", new=AsyncMock()
        ), patch.object(
            meet_bot, "ensure_meet_microphone_on", new=AsyncMock()
        ):
            await meet_bot.join_meet(page, "https://meet.google.com/test")

        self.assertEqual(page.clicked, ["Join now"])

    async def test_audio_setup_failure_aborts_before_alena_starts(self):
        page = SimpleNamespace(on=Mock())
        context = SimpleNamespace(
            pages=[page],
            browser=None,
            on=Mock(),
            close=AsyncMock(),
        )

        class PlaywrightContext:
            async def __aenter__(self):
                return object()

            async def __aexit__(self, *_args):
                return False

        with patch.object(
            meet_bot, "async_playwright", return_value=PlaywrightContext()
        ), patch.object(
            meet_bot, "create_browser", new=AsyncMock(return_value=context)
        ), patch.object(
            meet_bot,
            "join_meet",
            new=AsyncMock(side_effect=RuntimeError("Settings dialog did not open")),
        ), patch.object(
            meet_bot, "log_meet_microphone_diagnostics", new=AsyncMock()
        ), patch.object(
            meet_bot, "leave_meet", new=AsyncMock()
        ) as leave_meet, patch.object(
            meet_bot, "run_alena"
        ) as run_alena:
            with self.assertRaisesRegex(RuntimeError, "Settings dialog did not open"):
                await meet_bot.run_meet_bot(121, "https://meet.google.com/test")

        run_alena.assert_not_called()
        leave_meet.assert_awaited_once_with(page)
        context.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
