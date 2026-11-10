import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.meet_audio_preflight import (
    DEFAULT_MICROPHONE,
    _runtime_evidence,
    match_device_name,
)


class MeetAudioPreflightTests(unittest.TestCase):
    def test_matches_configured_input_name_case_insensitively(self):
        self.assertEqual(
            match_device_name(
                DEFAULT_MICROPHONE,
                ["Microphone Array", "cable output (vb-audio virtual cable)"],
            ),
            "cable output (vb-audio virtual cable)",
        )

    def test_unavailable_or_partial_name_does_not_match(self):
        self.assertIsNone(match_device_name(DEFAULT_MICROPHONE, ["Microphone Array"]))
        self.assertIsNone(
            match_device_name(
                DEFAULT_MICROPHONE,
                ["CABLE Output (VB-Audio Virtual Cable) (2)"],
            )
        )

    def test_runtime_permission_and_track_are_read_as_historical_evidence(self):
        line = (
            '2026-10-26 12:00:00,000 INFO app.services.meet_bot '
            'interview_id=121 stage=meet_browser_console '
            'Meet browser console audio message type=log text='
            '[MEET AUDIO] Forced microphone: '
            'CABLE Output (VB-Audio Virtual Cable) permission=granted '
            'url=https://meet.google.com/example'
        )
        track_line = (
            '2026-10-26 12:00:01,000 INFO app.services.meet_bot '
            'interview_id=121 stage=meet_browser_console '
            'Meet browser console audio message type=log text='
            '[MEET AUDIO] Active microphone track: '
            'CABLE Output (VB-Audio Virtual Cable) verification=deviceId'
        )
        path = Path("mock-interviews.log")
        with patch.object(Path, "is_file", return_value=True), patch.object(
            Path, "read_text", return_value=line + "\n" + track_line
        ):
            evidence = _runtime_evidence(path)

        self.assertEqual(evidence["permission"], "granted")
        self.assertIn("interview_id=121", evidence["permission_context"])
        self.assertEqual(
            evidence["active_track"],
            "CABLE Output (VB-Audio Virtual Cable)",
        )
        self.assertEqual(evidence["active_track_verification"], "deviceId")

    def test_missing_runtime_evidence_remains_unverified(self):
        uncorrelated_test_warning = (
            "2026-10-26 12:00:00,000 ERROR app.services.meet_bot "
            "interview_id=- stage=- system_mic_warning_detected=True"
        )
        path = Path("test-generated-log.log")
        with patch.object(Path, "is_file", return_value=True), patch.object(
            Path, "read_text", return_value=uncorrelated_test_warning
        ):
            evidence = _runtime_evidence(path)

        self.assertIsNone(evidence["permission"])
        self.assertIsNone(evidence["active_track"])


if __name__ == "__main__":
    unittest.main()
