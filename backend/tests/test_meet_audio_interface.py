import base64
import queue
import threading
import unittest

import numpy as np
from unittest.mock import patch

from app.services.elevenlabs_agent import MeetAudioInterface
from elevenlabs.conversational_ai.conversation import Conversation


def make_interface():
    interface = object.__new__(MeetAudioInterface)
    interface.interview_id = 42
    interface._stop_event = threading.Event()
    interface._stop_lock = threading.RLock()
    interface._output_enqueue_lock = threading.Lock()
    interface._cleanup_thread = None
    interface._cleanup_done = threading.Event()
    interface._discarded_output_chunks = 0
    interface._output_queue = queue.Queue(maxsize=MeetAudioInterface.OUTPUT_QUEUE_CHUNKS)
    interface._input_callback = None
    interface._input_stream = None
    interface._output_stream = None
    interface._input_thread = None
    interface._output_thread = None
    interface._input_chunks = 0
    interface._input_callback_chunks = 0
    interface._input_errors = 0
    interface._received_chunks = 0
    interface._queued_chunks = 0
    interface._written_chunks = 0
    interface._output_write_errors = 0
    interface._queue_full_events = 0
    interface.input_device_name = "Speakers (Realtek(R) Audio) [Loopback]"
    interface.output_device_name = "CABLE Input (VB-Audio Virtual Cable)"
    return interface


class MeetAudioInterfaceTests(unittest.TestCase):
    def test_input_block_converts_48khz_stereo_int16_to_16khz_mono(self):
        interface = make_interface()
        self.assertEqual(interface.INPUT_FRAMES, 4800)
        source = np.full((interface.INPUT_FRAMES, 2), 1200, dtype=np.int16)
        received = []

        def callback(audio):
            received.append(audio)
            interface._stop_event.set()

        class InputStream:
            def read(self, frames, exception_on_overflow=False):
                self.assert_frames = frames
                return source.tobytes()

        interface._input_stream = InputStream()
        interface._input_callback = callback
        interface._input_worker()

        self.assertEqual(len(received), 1)
        samples = np.frombuffer(received[0], dtype=np.int16)
        self.assertEqual(samples.size, 1600)
        self.assertEqual(interface._input_callback_chunks, 1)
        self.assertTrue(np.all((samples[20:-20] > 1100) & (samples[20:-20] < 1300)))

    def test_input_callback_exception_is_logged_and_stops_transport(self):
        interface = make_interface()
        source = np.zeros((interface.INPUT_FRAMES, 2), dtype=np.int16)

        class InputStream:
            def read(self, *_args, **_kwargs):
                return source.tobytes()

        interface._input_stream = InputStream()
        interface._input_callback = lambda _audio: (_ for _ in ()).throw(
            RuntimeError("SDK callback failed")
        )
        with self.assertLogs("app.services.elevenlabs_agent", level="ERROR") as logs:
            interface._input_worker()

        self.assertTrue(interface._stop_event.is_set())
        self.assertIn("candidate-input callback failed", " ".join(logs.output))
        self.assertIn(interface.input_device_name, " ".join(logs.output))

    def test_output_block_converts_mono_pcm_to_48khz_stereo_without_clipping(self):
        interface = make_interface()
        source = np.array([0, 1000, -1000, 2000], dtype=np.int16)
        with self.assertLogs("app.services.elevenlabs_agent", level="INFO"):
            interface.output(source.tobytes())

        output = interface._output_queue.get_nowait()
        stereo = np.frombuffer(output, dtype=np.int16).reshape(-1, 2)
        self.assertEqual(stereo.shape, (source.size * 3, 2))
        np.testing.assert_array_equal(stereo[:, 0], stereo[:, 1])
        self.assertEqual(stereo.dtype, np.int16)
        self.assertLessEqual(int(np.max(np.abs(stereo.astype(np.int32)))), 32768)

    def test_installed_sdk_audio_event_routes_pcm_to_transport_output(self):
        interface = make_interface()
        conversation = Conversation.__new__(Conversation)
        conversation.audio_interface = interface
        conversation._last_interrupt_id = 0
        conversation.callback_agent_response = None
        conversation.callback_agent_response_correction = None
        conversation.callback_agent_chat_response_part = None
        conversation.callback_user_transcript = None
        conversation.callback_latency_measurement = None
        conversation.callback_audio_alignment = None
        pcm = np.array([200, -200, 400], dtype=np.int16).tobytes()
        message = {
            "type": "audio",
            "audio_event": {
                "event_id": 1,
                "audio_base_64": base64.b64encode(pcm).decode("ascii"),
            },
        }

        with self.assertLogs("app.services.elevenlabs_agent", level="INFO"):
            conversation._handle_message(message, ws=None)

        queued = interface._output_queue.get_nowait()
        converted = np.frombuffer(queued, dtype=np.int16).reshape(-1, 2)
        self.assertEqual(converted.shape, (len(pcm) // 2 * 3, 2))
        self.assertEqual(interface._received_chunks, 1)
        self.assertEqual(interface._queued_chunks, 1)

    def test_multiple_small_and_normal_chunks_are_queued_and_written_in_order(self):
        interface = make_interface()
        small = np.array([900], dtype=np.int16).tobytes()
        normal = np.arange(1600, dtype=np.int16).tobytes()
        with self.assertLogs("app.services.elevenlabs_agent", level="INFO"):
            interface.output(small)
        with self.assertNoLogs("app.services.elevenlabs_agent", level="INFO"):
            interface.output(normal)
        expected = [
            interface._output_queue.get_nowait(),
            interface._output_queue.get_nowait(),
        ]
        written = []

        class OutputStream:
            def write(self, audio):
                written.append(audio)
                if len(written) == 2:
                    interface._stop_event.set()

        interface._output_stream = OutputStream()
        for audio in expected:
            interface._output_queue.put(audio)
        interface._output_worker()

        self.assertEqual(written, expected)
        self.assertEqual(interface._queued_chunks, 2)
        self.assertEqual(interface._written_chunks, 2)

    def test_received_and_queued_audio_are_logged_with_existing_cadence(self):
        interface = make_interface()
        source = np.array([0, 1000, -1000, 2000], dtype=np.int16).tobytes()

        with self.assertLogs("app.services.elevenlabs_agent", level="INFO") as logs:
            interface.output(source)
        self.assertEqual(len(logs.records), 2)
        self.assertIn("ElevenLabs audio received", logs.records[0].getMessage())
        self.assertIn("Alena audio queued", logs.records[1].getMessage())
        self.assertIn("format=int16/16000Hz/1ch", logs.records[0].getMessage())
        self.assertIn("rms=", logs.records[0].getMessage())
        self.assertIn("peak=", logs.records[0].getMessage())
        self.assertIn("silent=False", logs.records[0].getMessage())
        self.assertIn("output_format=int16/48000Hz/2ch", logs.records[1].getMessage())
        self.assertIn("resample_ratio=48000:16000", logs.records[1].getMessage())
        for record in logs.records:
            self.assertEqual(record.interview_id, 42)
            self.assertIn(interface.output_device_name, record.getMessage())

        interface._output_queue.get_nowait()
        with self.assertNoLogs("app.services.elevenlabs_agent", level="INFO"):
            interface.output(source)
        self.assertEqual(interface._received_chunks, 2)
        self.assertEqual(interface._queued_chunks, 2)

    def test_successful_output_write_is_logged(self):
        interface = make_interface()

        class OutputStream:
            def write(self, _audio):
                interface._stop_event.set()

        interface._output_stream = OutputStream()
        interface._output_queue.put(np.array([1000, -1000], dtype=np.int16).tobytes())
        with self.assertLogs("app.services.elevenlabs_agent", level="INFO") as logs:
            interface._output_worker()

        record = next(record for record in logs.records if record.stage == "alena_audio_written")
        self.assertEqual(record.interview_id, 42)
        self.assertEqual(record.stage, "alena_audio_written")
        self.assertIn(interface.output_device_name, record.getMessage())
        self.assertIn("peak=1000", record.getMessage())
        self.assertIn("silent=False", record.getMessage())
        self.assertIn("downstream Meet capture is not verified", record.getMessage())

    def test_interrupt_logs_queued_audio_discarded(self):
        interface = make_interface()
        interface._output_queue.put(b"stale chunk")
        with self.assertLogs("app.services.elevenlabs_agent", level="INFO") as logs:
            interface.interrupt()
        self.assertTrue(interface._output_queue.empty())
        self.assertIn("discarded after interrupt chunks=1", logs.records[0].getMessage())

    def test_wasapi_output_lookup_requires_exact_configured_endpoint(self):
        interface = make_interface()

        class Audio:
            devices = [
                {"hostApi": 7, "maxOutputChannels": 2,
                 "name": "CABLE Input (VB-Audio Virtual Cable) Speakers"},
                {"hostApi": 7, "maxOutputChannels": 2,
                 "name": "CABLE Input (VB-Audio Virtual Cable)"},
            ]

            def get_device_count(self):
                return len(self.devices)

            def get_device_info_by_index(self, index):
                return self.devices[index]

        interface._pa = Audio()
        with patch("app.services.elevenlabs_agent.get_wasapi_host_index", return_value=7):
            index, name, info = interface._find_wasapi_device(
                "CABLE Input (VB-Audio Virtual Cable)", input_device=False
            )
            self.assertEqual(index, 1)
            self.assertEqual(name, "CABLE Input (VB-Audio Virtual Cable)")
            self.assertEqual(info["maxOutputChannels"], 2)

            interface._pa.devices = [Audio.devices[0]]
            with self.assertRaisesRegex(RuntimeError, "not found"):
                interface._find_wasapi_device(
                    "CABLE Input (VB-Audio Virtual Cable)", input_device=False
                )

    def test_malformed_output_pcm_is_logged_and_raised(self):
        interface = make_interface()
        with self.assertLogs("app.services.elevenlabs_agent", level="ERROR"):
            with self.assertRaisesRegex(ValueError, "odd byte count"):
                interface.output(b"\x01")
        self.assertTrue(interface._output_queue.empty())

    def test_full_output_queue_applies_backpressure_without_dropping_existing_audio(self):
        interface = make_interface()
        for index in range(interface.OUTPUT_QUEUE_CHUNKS):
            interface._output_queue.put(f"older audio {index}".encode())
        release = threading.Timer(0.2, interface._stop_event.set)
        release.start()
        try:
            with self.assertLogs("app.services.elevenlabs_agent", level="WARNING"):
                with self.assertRaisesRegex(RuntimeError, "stopped before"):
                    interface.output(np.array([100], dtype=np.int16).tobytes())
        finally:
            release.join()
        queued = [interface._output_queue.get_nowait() for _ in range(interface.OUTPUT_QUEUE_CHUNKS)]
        self.assertEqual(
            queued,
            [f"older audio {index}".encode() for index in range(interface.OUTPUT_QUEUE_CHUNKS)],
        )
        self.assertTrue(interface._output_queue.empty())

    def test_output_device_write_failure_stops_worker(self):
        interface = make_interface()

        class OutputStream:
            def write(self, _audio):
                raise OSError("device removed")

        interface._output_stream = OutputStream()
        interface._output_queue.put(b"audio")
        with self.assertLogs("app.services.elevenlabs_agent", level="ERROR") as logs:
            interface._output_worker()

        self.assertTrue(interface._stop_event.is_set())
        self.assertIn("audio output write failed", " ".join(logs.output))
        self.assertIn(interface.output_device_name, " ".join(logs.output))
        self.assertEqual(logs.records[0].interview_id, 42)

    def test_final_audio_summary_is_logged(self):
        interface = make_interface()

        class Audio:
            @staticmethod
            def terminate():
                pass

        interface._pa = Audio()
        interface._received_chunks = 4
        interface._queued_chunks = 3
        interface._written_chunks = 2
        interface._output_write_errors = 1

        with self.assertLogs("app.services.elevenlabs_agent", level="INFO") as logs:
            interface.stop()

        record = next(record for record in logs.records if record.stage == "audio_summary")
        self.assertEqual(record.interview_id, 42)
        self.assertEqual(record.stage, "audio_summary")
        self.assertIn("output_queued=3", record.getMessage())
        self.assertIn("elevenlabs_audio_received=4", record.getMessage())
        self.assertIn("output_written=2", record.getMessage())
        self.assertIn("output_write_errors=1", record.getMessage())
        self.assertIn(interface.output_device_name, record.getMessage())

    def test_stop_discards_pending_audio_and_is_idempotent(self):
        interface = make_interface()

        class Stream:
            def __init__(self):
                self.closed = 0
                self.stopped = 0

            def stop_stream(self):
                self.stopped += 1

            def close(self):
                self.closed += 1

        class Audio:
            def __init__(self):
                self.terminated = 0

            def terminate(self):
                self.terminated += 1

        stream = Stream()
        audio = Audio()
        interface._pa = audio
        interface._output_stream = stream
        interface._output_queue.put(b"pending speech")

        with self.assertLogs("app.services.elevenlabs_agent", level="INFO") as logs:
            interface.stop()
        interface.stop()

        self.assertEqual(interface._discarded_output_chunks, 1)
        self.assertTrue(interface._output_queue.empty())
        self.assertEqual(stream.closed, 1)
        self.assertEqual(stream.stopped, 1)
        self.assertEqual(audio.terminated, 1)
        self.assertTrue(interface._cleanup_done.is_set())
        self.assertIn("pending_output_discarded=1", logs.records[-1].getMessage())

    def test_stream_closure_waits_for_slow_output_worker(self):
        interface = make_interface()
        write_started = threading.Event()
        finish_write = threading.Event()

        class Stream:
            def __init__(self):
                self.closed = 0

            def write(self, _audio):
                write_started.set()
                finish_write.wait(timeout=2)

            def stop_stream(self):
                pass

            def close(self):
                self.closed += 1

        class Audio:
            def __init__(self):
                self.terminated = 0

            def terminate(self):
                self.terminated += 1

        stream = Stream()
        audio = Audio()
        interface._output_stream = stream
        interface._pa = audio
        interface.WORKER_JOIN_TIMEOUT = 0.02
        interface._output_queue.put(b"currently playing speech")
        worker = threading.Thread(target=interface._output_worker)
        interface._output_thread = worker
        worker.start()
        self.assertTrue(write_started.wait(timeout=1))

        with self.assertLogs("app.services.elevenlabs_agent", level="ERROR") as logs:
            interface.stop()
        interface.stop()

        self.assertTrue(worker.is_alive())
        self.assertEqual(stream.closed, 0)
        self.assertEqual(audio.terminated, 0)
        self.assertIn("stream closure deferred", " ".join(logs.output))

        finish_write.set()
        self.assertTrue(interface._cleanup_done.wait(timeout=1))
        self.assertFalse(worker.is_alive())
        self.assertEqual(stream.closed, 1)
        self.assertEqual(audio.terminated, 1)


if __name__ == "__main__":
    unittest.main()
