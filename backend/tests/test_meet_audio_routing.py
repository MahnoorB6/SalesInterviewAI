import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.services import meet_bot


class _Locator:
    def __init__(self, visible, page=None):
        self.first = self
        self.visible = visible
        self.page = page

    async def is_visible(self):
        return self.visible

    async def click(self):
        if self.page is not None:
            self.page.clicks += 1


class _Page:
    def __init__(self, system_warning=False):
        self.system_warning = system_warning
        self.clicks = 0

    def get_by_text(self, _text, exact=False):
        return _Locator(self.system_warning)

    def get_by_role(self, *_args, **_kwargs):
        return _Locator(False, self)


class MeetAudioRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_browser_grants_microphone_permission_only_for_meet_origin(self):
        class Context:
            script = None
            permissions = None

            async def add_init_script(self, script):
                self.script = script

            async def grant_permissions(self, permissions, origin=None):
                self.permissions = (permissions, origin)

        class Chromium:
            options = None

            async def launch_persistent_context(self, **options):
                self.options = options
                return context

        context = Context()
        chromium = Chromium()
        playwright = type("Playwright", (), {"chromium": chromium})()
        with patch.dict(
            "os.environ",
            {"MEET_MIC_DEVICE": "CABLE Output (VB-Audio Virtual Cable)"},
        ):
            await meet_bot.create_browser(playwright)

        self.assertEqual(chromium.options["permissions"], ["camera"])
        self.assertEqual(
            context.permissions,
            (["camera", "microphone"], "https://meet.google.com"),
        )
        self.assertIs(chromium.options["chromium_sandbox"], True)
        self.assertFalse(
            any(
                argument.casefold().startswith(("--no-sandbox", "--disable-sandbox"))
                for argument in chromium.options["args"]
            )
        )
        self.assertNotIn("--no-sandbox", chromium.options["args"])
        self.assertNotIn(
            "--use-fake-ui-for-media-stream",
            chromium.options["args"],
        )
        self.assertIn("CABLE Output (VB-Audio Virtual Cable)", context.script)
        self.assertIn("navigator.permissions.query({ name: \"microphone\" })", context.script)
        self.assertIn("originalGetUserMedia({ audio: true })", context.script)
        self.assertIn("permissionStream.getTracks()", context.script)
        self.assertIn("exact: target.deviceId", context.script)
        self.assertIn("activeTracks.push", context.script)

    def test_manual_meet_helper_enables_chromium_sandbox(self):
        helper = (
            Path(meet_bot.__file__).resolve().parents[2]
            / "backend"
            / "test_meet_cc.py"
        )
        source = helper.read_text(encoding="utf-8")
        self.assertIn("chromium_sandbox=True", source)

    async def test_microphone_diagnostics_log_permission_url_controls_and_stop_reason(self):
        class Page:
            def get_by_text(self, _text, exact=False):
                return _Locator(False)

            async def evaluate(self, _script):
                return {
                    "url": "https://meet.google.com/test",
                    "microphone_permission": "denied",
                    "visible_audio_controls": ["Use microphone", "Leave call"],
                    "meet_selected_microphone": "Microphone: CABLE Output (VB-Audio Virtual Cable)",
                    "available_audio_inputs": ["CABLE Output (VB-Audio Virtual Cable)"],
                    "active_audio_diagnostics": {
                        "permission": "granted",
                        "activeTracks": [{"verification": "deviceId", "muted": False}],
                    },
                    "active_track_signal": "not measured; track metadata does not prove incoming audio",
                }

        with self.assertLogs(meet_bot.logger, level="INFO") as captured:
            await meet_bot.log_meet_microphone_diagnostics(
                Page(), 120, "Microphone setup failed before Alena started"
            )

        message = "\n".join(captured.output)
        self.assertEqual(captured.records[0].interview_id, 120)
        self.assertIn("microphone_permission", message)
        self.assertIn("denied", message)
        self.assertIn("https://meet.google.com/test", message)
        self.assertIn("Use microphone", message)
        self.assertIn("system_mic_warning_detected", message)
        self.assertIn("meet_selected_microphone", message)
        self.assertIn("active_audio_diagnostics", message)
        self.assertIn("active_track_signal", message)
        self.assertIn("does not prove incoming audio", message)
        self.assertIn("Microphone setup failed before Alena started", message)

    async def test_browser_permission_grant_failure_closes_context_and_aborts(self):
        class Context:
            closed = False

            async def grant_permissions(self, *_args, **_kwargs):
                raise RuntimeError("permission grant rejected")

            async def close(self):
                self.closed = True

        class Chromium:
            async def launch_persistent_context(self, **_options):
                return context

        context = Context()
        playwright = type("Playwright", (), {"chromium": Chromium()})()

        with self.assertLogs(meet_bot.logger, level="ERROR"):
            with self.assertRaisesRegex(RuntimeError, "permission grant rejected"):
                await meet_bot.create_browser(playwright)

        self.assertTrue(context.closed)

    async def test_meet_audio_settings_verify_cable_mic_and_physical_speaker(self):
        expected_mic = "CABLE Output (VB-Audio Virtual Cable)"
        expected_speaker = "Speakers (Realtek(R) Audio)"

        class Locator:
            def __init__(self, snapshot=""):
                self.snapshot = snapshot
                self.click_count = 0

            async def wait_for(self, **_kwargs):
                pass

            async def aria_snapshot(self):
                return self.snapshot

            async def get_attribute(self, _name):
                return None

            async def is_visible(self):
                return False

            async def click(self):
                self.click_count += 1

        class Page:
            def __init__(self):
                self.microphone = Locator(f'button "Microphone: {expected_mic}"')
                self.speaker = Locator(f'button "Speaker: {expected_speaker}"')

            def get_by_role(self, _role, name, **_kwargs):
                if name == "Close":
                    return Locator()
                if name == "Microphone:":
                    return self.microphone
                if name == "Speaker:":
                    return self.speaker
                raise AssertionError(f"Unexpected Meet control: {name}")

        page = Page()
        with patch.object(meet_bot, "open_meet_audio_settings", new=AsyncMock()), \
             patch.object(meet_bot, "log_audio_settings_diagnostics", new=AsyncMock()):
            await meet_bot.select_meet_microphone(
                page,
                expected_mic,
                expected_speaker,
            )

        self.assertEqual(page.microphone.click_count, 0)
        self.assertEqual(page.speaker.click_count, 0)

    async def test_microphone_selection_fails_when_meet_does_not_confirm_target(self):
        target = "CABLE Output (VB-Audio Virtual Cable)"

        class Locator:
            def __init__(self, snapshot="", visible=True):
                self.snapshot = snapshot
                self.visible = visible

            async def wait_for(self, **_kwargs):
                pass

            async def aria_snapshot(self):
                return self.snapshot

            async def is_visible(self):
                return self.visible

            async def click(self, **_kwargs):
                pass

        class Page:
            microphone = Locator('button "Microphone: Default"')
            target_option = Locator(target)

            async def wait_for_timeout(self, _milliseconds):
                pass

            def get_by_role(self, _role, name, **_kwargs):
                if name == "Microphone:":
                    return self.microphone
                raise AssertionError(f"Unexpected control: {name}")

            def get_by_text(self, text, exact=False):
                if exact and text == target:
                    return self.target_option
                raise AssertionError(f"Unexpected option: {text}")

        with patch.object(meet_bot, "open_meet_audio_settings", new=AsyncMock()), \
             patch.object(meet_bot, "log_audio_settings_diagnostics", new=AsyncMock()):
            with self.assertRaisesRegex(RuntimeError, "microphone selection did not verify"):
                await meet_bot.select_meet_microphone(
                    Page(), target, "Speakers (Realtek(R) Audio)"
                )

    async def test_detects_windows_system_microphone_mute_warning(self):
        self.assertTrue(await meet_bot.meet_system_microphone_muted(_Page(True)))
        self.assertFalse(await meet_bot.meet_system_microphone_muted(_Page(False)))

    async def test_unmuted_meet_control_does_not_override_system_mute_warning(self):
        page = _Page(system_warning=True)
        with patch.object(
            meet_bot,
            "get_meet_microphone_state",
            new=AsyncMock(return_value="unmuted"),
        ):
            with self.assertRaisesRegex(RuntimeError, "Microphone muted by system"):
                await meet_bot.ensure_meet_microphone_on(page)

    async def test_unknown_system_warning_state_fails_closed(self):
        page = _Page()
        with patch.object(
            meet_bot,
            "get_meet_microphone_state",
            new=AsyncMock(return_value="unmuted"),
        ), patch.object(
            meet_bot,
            "meet_system_microphone_muted",
            new=AsyncMock(return_value=None),
        ):
            with self.assertRaisesRegex(RuntimeError, "Could not verify"):
                await meet_bot.ensure_meet_microphone_on(page)

    async def test_already_unmuted_microphone_is_not_clicked_or_toggled(self):
        page = _Page(system_warning=False)
        with patch.object(
            meet_bot,
            "get_meet_microphone_state",
            new=AsyncMock(return_value="unmuted"),
        ):
            await meet_bot.ensure_meet_microphone_on(page)
        self.assertEqual(page.clicks, 0)

    async def test_microphone_state_change_is_not_a_meeting_end_signal(self):
        page = _Page(system_warning=False)
        page.is_closed = lambda: False
        self.assertFalse(await meet_bot.meet_has_ended(page))


if __name__ == "__main__":
    unittest.main()
