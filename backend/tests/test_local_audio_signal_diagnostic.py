import contextlib
import io
import sys
import unittest
from unittest.mock import patch

import numpy as np

from app.services import local_audio_signal_diagnostic as diagnostic


class LocalAudioSignalDiagnosticTests(unittest.TestCase):
    def test_capture_windows_allow_for_buffering_and_tail(self):
        self.assertEqual(diagnostic._capture_phase(0.0, 0.5, 1.0, 4.0), "BASELINE")
        self.assertEqual(
            diagnostic._capture_phase(0.5, 1.5, 1.0, 4.0),
            "TONE / BUFFER WINDOW",
        )

    def test_cable_tone_detector_distinguishes_440_hz_tone_from_silence(self):
        frames = diagnostic.RATE
        time_values = np.arange(frames) / diagnostic.RATE
        tone = np.round(
            diagnostic.TONE_PEAK
            * np.sin(2 * np.pi * diagnostic.TONE_FREQUENCY * time_values)
        ).astype(np.int16)
        stereo_tone = np.column_stack((tone, tone)).reshape(-1)
        silence = np.zeros(frames * diagnostic.CHANNELS, dtype=np.int16)

        self.assertGreaterEqual(
            diagnostic._tone_rms(stereo_tone, 0),
            diagnostic.TONE_DETECTION_RMS,
        )
        self.assertLess(
            diagnostic._tone_rms(silence, 0),
            diagnostic.TONE_DETECTION_RMS,
        )
        self.assertEqual(
            diagnostic._capture_phase(4.5, 5.5, 1.0, 4.0),
            "POST-TONE TAIL",
        )

    def test_main_keeps_diagnostic_modes_separate(self):
        for mode, runner in (
            ("speaker-loopback", "run_loopback_meter"),
            ("cable-roundtrip", "run_cable_roundtrip"),
        ):
            with self.subTest(mode=mode), \
                 patch.object(diagnostic, "load_dotenv"), \
                 patch.object(diagnostic, "run_loopback_meter") as loopback, \
                 patch.object(diagnostic, "run_cable_roundtrip") as cable, \
                 patch.object(sys, "argv", ["diagnostic", mode]):
                self.assertEqual(diagnostic.main(), 0)
                loopback.assert_called_once() if runner == "run_loopback_meter" else loopback.assert_not_called()
                cable.assert_called_once() if runner == "run_cable_roundtrip" else cable.assert_not_called()

    def test_main_reports_runtime_failure_and_returns_nonzero(self):
        output = io.StringIO()
        with patch.object(diagnostic, "load_dotenv"), \
             patch.object(diagnostic, "run_cable_roundtrip", side_effect=OSError("device unavailable")), \
             patch.object(sys, "argv", ["diagnostic", "cable-roundtrip"]), \
             contextlib.redirect_stdout(output):
            result = diagnostic.main()
        self.assertNotEqual(result, 0)
        self.assertIn("[DIAGNOSTIC ERROR] OSError: device unavailable", output.getvalue())


if __name__ == "__main__":
    unittest.main()
