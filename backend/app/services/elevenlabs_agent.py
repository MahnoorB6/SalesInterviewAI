
import os
import queue
import json
import logging
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from elevenlabs import ElevenLabs
from elevenlabs.conversational_ai.conversation import (
    AudioInterface,
    Conversation,
    ConversationInitiationData,
)

import pyaudiowpatch as pyaudio
import numpy as np
from scipy.signal import resample_poly

from app.database.database import SessionLocal
from app.models.interview import Interview
from app.models.interview_question import InterviewQuestion
from app.statuses import InterviewStatus, can_transition_interview
from app.logging_config import (
    bind_thread_context,
    configure_backend_logging,
    reset_interview_context,
    set_interview_context,
    set_interview_stage,
    set_thread_stage,
    unbind_thread_context,
)


load_dotenv()
configure_backend_logging()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_AGENT_ID = os.getenv("ELEVENLABS_AGENT_ID")

MAX_INTERVIEW_SECONDS = 30 * 60

TRANSCRIPT_DIR = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "transcripts"
)
TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------
# Transcript functions
# --------------------------------------------------

def save_transcript(interview_id: int, transcript: list[dict]) -> str:
    """Atomically save readable and structured transcripts."""

    path = TRANSCRIPT_DIR / f"interview_{interview_id}.txt"

    text = "".join(
        f"{item.get('role', 'unknown').upper()}: "
        f"{item.get('message', '')}\n"
        for item in transcript
    )

    _atomic_write(path, text)
    _atomic_write(
        path.with_suffix(".json"),
        json.dumps(
            {
                "interview_id": interview_id,
                "state": transcript_state(interview_id),
                "turns": transcript,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )

    return str(path)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None

    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as file:
            temporary = Path(file.name)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())

        os.replace(temporary, path)

    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def transcript_state(interview_id: int) -> str:
    db = SessionLocal()
    try:
        interview = (
            db.query(Interview)
            .filter(Interview.id == interview_id)
            .first()
        )
        return interview.status if interview else "incomplete"
    finally:
        db.close()


def build_question_context(questions) -> tuple[list[dict], dict[str, str]]:
    """Serialize the saved interview questions in their stored order."""

    ordered = sorted(questions, key=lambda question: question.question_number)

    if not ordered:
        raise ValueError(
            "Saved interview questions are missing; Alena session cannot start."
        )

    plan = [
        {
            "id": question.id,
            "order": question.question_number,
            "question": question.question,
            "category": question.category,
        }
        for question in ordered
    ]

    dynamic_variables = {
        "interview_questions": "\n".join(
            f"{item['order']}. {item['question']}" for item in plan
        ),
        "interview_question_plan": json.dumps(
            plan,
            ensure_ascii=False,
        ),
    }

    return plan, dynamic_variables


def save_transcript_path(interview_id: int, path: str) -> None:
    db = SessionLocal()
    try:
        interview = (
            db.query(Interview)
            .filter(Interview.id == interview_id)
            .first()
        )

        if interview:
            interview.transcript_path = path
            db.commit()
    finally:
        db.close()


def save_live_transcript(
    interview_id: int,
    transcript: list[dict],
) -> None:
    try:
        path = save_transcript(interview_id, transcript)
        save_transcript_path(interview_id, path)
        print(f"[TRANSCRIPT] Updated: {path}")
    except Exception as error:
        print(f"[TRANSCRIPT] Save error: {error}")


# --------------------------------------------------
# Interview status functions
# --------------------------------------------------

def mark_completed(
    interview_id: int,
    reason: str = "explicit completion event",
) -> None:
    _transition_interview_status(
        interview_id,
        InterviewStatus.COMPLETED.value,
        reason,
        completed_at=datetime.now(timezone.utc),
    )


def mark_interrupted(
    interview_id: int,
    reason: str = "interruption",
) -> None:
    _transition_interview_status(
        interview_id,
        InterviewStatus.INTERRUPTED.value,
        reason,
    )


def mark_failed(interview_id: int, diagnostic: str) -> None:
    """Record a failed execution without exposing diagnostic text in public fields."""

    changed = _transition_interview_status(
        interview_id,
        InterviewStatus.FAILED.value,
        diagnostic,
    )
    if changed:
        print(
            f"[ALENA] Interview {interview_id} marked failed "
            "after an execution error."
        )


def _transition_interview_status(
    interview_id: int,
    target_status: str,
    reason: str,
    completed_at=None,
) -> bool:
    """Persist one status change with a compare-and-set to protect final states."""
    db = SessionLocal()
    try:
        interview = (
            db.query(Interview)
            .filter(Interview.id == interview_id)
            .first()
        )

        if not interview or not can_transition_interview(
            interview.status,
            target_status,
        ):
            return False

        previous_status = interview.status
        values = {Interview.status: target_status}
        if completed_at is not None:
            values[Interview.completed_at] = completed_at
        changed = (
            db.query(Interview)
            .filter(
                Interview.id == interview_id,
                Interview.status == previous_status,
            )
            .update(values, synchronize_session=False)
        )
        if not changed:
            logger.warning(
                "Interview status transition skipped because status changed concurrently expected=%s target=%s",
                previous_status,
                target_status,
                extra={"interview_id": interview_id, "stage": "status_update"},
            )
            return False

        db.commit()
        logger.info(
            "Interview status transition previous=%s new=%s reason=%s origin=run_alena",
            previous_status,
            target_status,
            reason,
            extra={"interview_id": interview_id, "stage": "status_update"},
        )
        return True
    finally:
        db.close()


def safe_diagnostic(error: Exception) -> str:
    message = str(error)

    for secret in (ELEVENLABS_API_KEY,):
        if secret:
            message = message.replace(secret, "[redacted]")

    message = re.sub(
        r"(?i)(api[_ -]?key|authorization|bearer)"
        r"(\s*[:=]\s*)[^\s,;]+",
        r"\1\2[redacted]",
        message,
    )

    return f"{type(error).__name__}: {message[:400]}"


# --------------------------------------------------
# WASAPI device discovery
# --------------------------------------------------

def get_wasapi_host_index(audio) -> int:
    """Return the Windows WASAPI host API index."""

    try:
        return int(
            audio.get_host_api_info_by_type(pyaudio.paWASAPI)["index"]
        )
    except Exception as error:
        raise RuntimeError(
            "Windows WASAPI audio support is unavailable."
        ) from error


def get_meet_speaker_device_name() -> str:
    """Resolve the physical Windows speaker used for candidate capture."""

    audio = pyaudio.PyAudio()

    try:
        wasapi_index = get_wasapi_host_index(audio)

        requested = (
            os.getenv("MEET_SPEAKER_DEVICE", "").strip()
            or os.getenv("ELEVENLABS_AUDIO_LOOPBACK_DEVICE", "").strip()
        )

        if requested:
            for index in range(audio.get_device_count()):
                info = audio.get_device_info_by_index(index)

                if (
                    int(info.get("hostApi", -1)) == wasapi_index
                    and int(info.get("maxOutputChannels", 0)) > 0
                    and requested.casefold()
                    in str(info.get("name", "")).casefold()
                ):
                    selected = str(info["name"])
                    break
            else:
                raise RuntimeError(
                    f"Configured Meet speaker {requested!r} was not found "
                    "as a WASAPI output device."
                )
        else:
            wasapi = audio.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_info = audio.get_device_info_by_index(
                int(wasapi["defaultOutputDevice"])
            )
            selected = str(default_info.get("name", ""))

        if not selected:
            raise RuntimeError("Could not resolve a Windows speaker device.")

        if any(
            virtual_name in selected.casefold()
            for virtual_name in ("cable", "voicemeeter")
        ):
            raise RuntimeError(
                f"Meet speaker must be a physical output, not {selected!r}."
            )

        return selected

    finally:
        audio.terminate()


class MeetAudioInterface(AudioInterface):
    """
    Candidate input:
        Physical Meet speakers -> WASAPI loopback -> ElevenLabs.

    Alena output:
        ElevenLabs -> VB-Audio CABLE Input -> Meet microphone.

    ElevenLabs remains responsible for speech recognition, conversation,
    and voice generation. PyAudio is only the audio transport layer.
    """

    INPUT_RATE = 16000
    CAPTURE_RATE = 48000
    OUTPUT_RATE = 48000

    CAPTURE_CHANNELS = 2
    OUTPUT_CHANNELS = 2

    FORMAT = pyaudio.paInt16

    # 4,800 capture frames are 100 ms and divide exactly by the 3:1
    # 48 kHz -> 16 kHz conversion ratio (1,600 mono SDK samples).
    INPUT_FRAMES = 4800
    OUTPUT_FRAMES = 1000
    OUTPUT_QUEUE_CHUNKS = 10
    WORKER_JOIN_TIMEOUT = 1.5

    def __init__(self, interview_id: int | None = None):
        self.interview_id = interview_id
        self.meet_microphone_name = os.getenv(
            "MEET_MIC_DEVICE",
            "CABLE Output (VB-Audio Virtual Cable)",
        ).strip()

        self.loopback_device_name = get_meet_speaker_device_name()
        self.input_device_name = self.loopback_device_name

        self.output_device_name = os.getenv(
            "ELEVENLABS_AUDIO_OUTPUT_DEVICE",
            "CABLE Input (VB-Audio Virtual Cable)",
        ).strip()

        self._pa = None
        self._input_stream = None
        self._output_stream = None

        self._input_callback = None

        self._output_queue = queue.Queue(maxsize=self.OUTPUT_QUEUE_CHUNKS)
        self._stop_event = threading.Event()
        self._stop_lock = threading.RLock()
        self._output_enqueue_lock = threading.Lock()
        self._cleanup_thread = None
        self._cleanup_done = threading.Event()
        self._discarded_output_chunks = 0

        self._output_thread = None
        self._input_thread = None

        self._queued_chunks = 0
        self._received_chunks = 0
        self._written_chunks = 0
        self._output_write_errors = 0
        self._queue_full_events = 0
        self._input_chunks = 0
        self._input_callback_chunks = 0
        self._input_errors = 0

    # --------------------------------------------------
    # Deterministic WASAPI device lookup
    # --------------------------------------------------

    def _find_wasapi_device(self, name: str, input_device: bool):
        """Find the requested device only under Windows WASAPI."""

        wasapi_index = get_wasapi_host_index(self._pa)

        channel_key = (
            "maxInputChannels" if input_device else "maxOutputChannels"
        )
        target = name.casefold().strip()

        matches = []

        for index in range(self._pa.get_device_count()):
            info = self._pa.get_device_info_by_index(index)

            if int(info.get("hostApi", -1)) != wasapi_index:
                continue

            if int(info.get(channel_key, 0)) <= 0:
                continue

            device_name = str(info.get("name", ""))

            if device_name.casefold().strip() == target:
                matches.append((index, device_name, info))

        if not matches:
            available = []

            for index in range(self._pa.get_device_count()):
                info = self._pa.get_device_info_by_index(index)

                if (
                    int(info.get("hostApi", -1)) == wasapi_index
                    and int(info.get(channel_key, 0)) > 0
                ):
                    available.append(
                        f"{index}: {info.get('name', '')}"
                    )

            direction = "input" if input_device else "output"

            raise RuntimeError(
                f"WASAPI {direction} device {name!r} not found. "
                f"Available WASAPI {direction} devices: {available}"
            )

        # Route only to the configured endpoint. A substring lookalike can
        # select a different virtual/physical device and silently lose audio.
        selected = matches[0]

        index, device_name, info = selected

        print(
            f"[AUDIO DEVICE] direction="
            f"{'input' if input_device else 'output'} "
            f"index={index} name={device_name!r} "
            f"hostApi={info.get('hostApi')}"
        )

        return index, device_name, info

    def _find_loopback_device(self):
        """Resolve a loopback device matching the physical speaker name."""

        target = self.loopback_device_name.casefold().strip()
        matches = []

        for info in self._pa.get_loopback_device_info_generator():
            name = str(info.get("name", ""))

            # The loopback name normally appends "[Loopback]" to
            # the corresponding physical output device name.
            normalized = name.casefold().replace("[loopback]", "").strip()

            if (
                normalized == target
                or target in normalized
                or normalized in target
            ):
                matches.append((int(info["index"]), name))

        if not matches:
            available = [
                str(info.get("name", ""))
                for info in self._pa.get_loopback_device_info_generator()
            ]

            raise RuntimeError(
                "No WASAPI loopback device matches the selected physical "
                f"speaker {self.loopback_device_name!r}. "
                f"Available loopback devices: {available}"
            )

        exact = [
            item for item in matches
            if item[1].casefold().replace("[loopback]", "").strip() == target
        ]

        return exact[0] if exact else matches[0]

    # --------------------------------------------------
    # Start audio
    # --------------------------------------------------

    def start(self, input_callback):
        """Open audio streams and start the transport workers."""

        if self._pa is not None:
            raise RuntimeError("Meet audio interface is already running.")

        self._input_callback = input_callback
        self._stop_event.clear()
        self._output_queue = queue.Queue(maxsize=self.OUTPUT_QUEUE_CHUNKS)

        input_name = self.loopback_device_name
        output_name = self.output_device_name
        try:
            self._pa = pyaudio.PyAudio()

            input_index, input_name = self._find_loopback_device()

            output_index, output_name, output_info = (
                self._find_wasapi_device(
                    self.output_device_name,
                    input_device=False,
                )
            )

            wasapi_index = get_wasapi_host_index(self._pa)

            if int(output_info.get("hostApi", -1)) != wasapi_index:
                raise RuntimeError(
                    "Alena output was not resolved to Windows WASAPI."
                )

            if int(output_info.get("maxOutputChannels", 0)) < self.OUTPUT_CHANNELS:
                raise RuntimeError(
                    f"Alena output device {output_name!r} does not support "
                    f"{self.OUTPUT_CHANNELS} output channels."
                )

            if any(
                name in output_name.casefold()
                for name in ("voicemeeter",)
            ):
                raise RuntimeError(
                    f"Unexpected Alena output device: {output_name!r}"
                )

            # Candidate audio: physical speakers captured through WASAPI.
            self._input_stream = self._pa.open(
                format=self.FORMAT,
                channels=self.CAPTURE_CHANNELS,
                rate=self.CAPTURE_RATE,
                input=True,
                input_device_index=input_index,
                frames_per_buffer=self.INPUT_FRAMES,
            )

            # Alena audio: CABLE Input playback endpoint.
            self._output_stream = self._pa.open(
                format=self.FORMAT,
                channels=self.OUTPUT_CHANNELS,
                rate=self.OUTPUT_RATE,
                output=True,
                output_device_index=output_index,
                frames_per_buffer=self.OUTPUT_FRAMES,
            )

            print()
            print("[AUDIO ROUTE] Configuration opened successfully.")
            print(
                f"[AUDIO ROUTE] Meet microphone setting: "
                f"{self.meet_microphone_name!r}"
            )
            print(
                f"[AUDIO ROUTE] Candidate capture: "
                f"{input_name!r} | WASAPI loopback"
            )
            print(
                f"[AUDIO ROUTE] Alena output: "
                f"{output_name!r} | WASAPI playback"
            )
            print(
                "[AUDIO ROUTE] Expected chain: "
                "ElevenLabs -> CABLE Input -> Meet microphone."
            )
            print(
                "[AUDIO ROUTE] Candidate chain: "
                "Meet physical speakers -> WASAPI loopback -> ElevenLabs."
            )
            logger.info(
                "Audio devices initialized candidate_input=%s candidate_format=int16/%sHz/%sch output_device=%s output_format=int16/%sHz/%sch Meet_microphone=%s",
                input_name,
                self.CAPTURE_RATE,
                self.CAPTURE_CHANNELS,
                output_name,
                self.OUTPUT_RATE,
                self.OUTPUT_CHANNELS,
                self.meet_microphone_name,
                extra={
                    "interview_id": self.interview_id or "-",
                    "stage": "audio_initialization",
                },
            )
            print(
                "[AUDIO FORMAT] SDK input: 16-bit PCM, mono, 16000 Hz."
            )
            print(
                "[AUDIO FORMAT] SDK output: 16-bit PCM, mono, 16000 Hz."
            )
            print(
                "[AUDIO FORMAT] Cable playback: "
                "16-bit PCM, stereo, 48000 Hz."
            )
            print()

            self._output_thread = threading.Thread(
                target=self._output_worker,
                name="alena-audio-output",
                daemon=True,
            )
            self._input_thread = threading.Thread(
                target=self._input_worker,
                name="meet-audio-input",
                daemon=True,
            )

            self._output_thread.start()
            self._input_thread.start()

        except Exception as error:
            logger.exception(
                "Audio transport initialization failed candidate_input=%s Alena_output=%s Meet_microphone=%s error_type=%s error=%s",
                input_name,
                output_name,
                self.meet_microphone_name,
                type(error).__name__,
                error,
                extra={
                    "interview_id": self.interview_id or "-",
                    "stage": "audio_initialization",
                },
            )
            print(
                "[AUDIO ROUTE ERROR] "
                f"candidate_input={input_name!r} "
                f"Alena_output={output_name!r} "
                f"Meet_microphone={self.meet_microphone_name!r} "
                f"{type(error).__name__}: {error}"
            )
            self.stop()
            raise

    # --------------------------------------------------
    # Candidate input worker
    # --------------------------------------------------

    def _input_worker(self):
        consecutive_read_errors = 0
        while not self._stop_event.is_set():
            try:
                audio = self._input_stream.read(
                    self.INPUT_FRAMES,
                    exception_on_overflow=False,
                )
                consecutive_read_errors = 0

                if not audio:
                    continue

                expected_bytes = self.INPUT_FRAMES * self.CAPTURE_CHANNELS * 2
                if len(audio) != expected_bytes:
                    raise ValueError(
                        f"WASAPI loopback returned {len(audio)} bytes; "
                        f"expected {expected_bytes} for "
                        f"{self.INPUT_FRAMES} stereo int16 frames."
                    )

                samples = np.frombuffer(audio, dtype=np.int16)

                if samples.size == 0:
                    continue

                samples = samples.reshape(
                    -1,
                    self.CAPTURE_CHANNELS,
                ).astype(np.float32).mean(axis=1)

                # Convert 48 kHz mono -> 16 kHz mono.
                resampled = resample_poly(
                    samples,
                    self.INPUT_RATE,
                    self.CAPTURE_RATE,
                )

                resampled = np.clip(
                    resampled,
                    -32768,
                    32767,
                ).astype(np.int16)

                self._input_chunks += 1

                if self._input_chunks == 1 or self._input_chunks % 100 == 0:
                    rms = float(
                        np.sqrt(np.mean(resampled.astype(np.float64) ** 2))
                    )
                    print(
                        f"[AUDIO INPUT] chunks={self._input_chunks} "
                        f"samples={resampled.size} rms={rms:.1f}"
                    )

                if self._input_callback:
                    # Fail separately from device reads: retrying a broken SDK
                    # callback as if it were a transient WASAPI read error
                    # would silently discard candidate audio indefinitely.
                    try:
                        self._input_callback(resampled.tobytes())
                    except Exception as error:
                        self._input_errors += 1
                        self._stop_event.set()
                        logger.exception(
                            "ElevenLabs candidate-input callback failed; audio transport stopped source_device=%s destination=ElevenLabs",
                            self.input_device_name,
                            extra={
                                "interview_id": self.interview_id or "-",
                                "stage": "candidate_audio_callback",
                            },
                        )
                        print(
                            "[AUDIO INPUT CALLBACK ERROR] "
                            f"{type(error).__name__}: {error}; "
                            "audio transport stopped."
                        )
                        break
                    self._input_callback_chunks += 1
                    if self._input_callback_chunks == 1 or self._input_callback_chunks % 100 == 0:
                        print(
                            "[AUDIO INPUT SDK HANDOFF] "
                            f"chunks={self._input_callback_chunks}; callback returned."
                        )

            except Exception as error:
                if not self._stop_event.is_set():
                    self._input_errors += 1
                    consecutive_read_errors += 1
                    logger.warning(
                        "Candidate audio input read failed device=%s destination=ElevenLabs consecutive_errors=%s error_type=%s error=%s",
                        self.input_device_name,
                        consecutive_read_errors,
                        type(error).__name__,
                        error,
                        extra={
                            "interview_id": self.interview_id or "-",
                            "stage": "candidate_audio_input",
                        },
                    )
                    print(
                        f"[AUDIO INPUT ERROR] "
                        f"consecutive={consecutive_read_errors}; "
                        f"{type(error).__name__}: {error}"
                    )
                    if consecutive_read_errors < 5:
                        self._stop_event.wait(0.25)
                        continue
                    logger.error(
                        "Candidate audio capture stopped after consecutive WASAPI read failures; Alena output remains active",
                        extra={
                            "interview_id": self.interview_id or "-",
                            "stage": "candidate_audio_input",
                        },
                    )
                    print(
                        "[AUDIO INPUT] Candidate capture worker stopped after five "
                        "consecutive read failures; Alena output remains active."
                    )
                break

    # --------------------------------------------------
    # Alena output worker
    # --------------------------------------------------

    def _output_worker(self):
        logger.info(
            "Alena audio output worker started device=%s format=int16/%sHz/%sch",
            self.output_device_name,
            self.OUTPUT_RATE,
            self.OUTPUT_CHANNELS,
            extra={"interview_id": self.interview_id or "-", "stage": "alena_audio_worker"},
        )
        exit_reason = "stop_requested"
        try:
            while not self._stop_event.is_set():
                try:
                    audio = self._output_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                if audio is None:
                    exit_reason = "sentinel_received"
                    break

                try:
                    self._output_stream.write(audio)
                    self._written_chunks += 1

                    if self._written_chunks == 1 or self._written_chunks % 50 == 0:
                        samples = np.frombuffer(audio, dtype=np.int16)
                        rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
                        peak = int(np.max(np.abs(samples.astype(np.int32)))) if samples.size else 0
                        logger.info(
                            "Alena audio write returned chunks=%s bytes=%s format=int16/%sHz/%sch rms=%.1f peak=%s silent=%s pending_chunks=%s output_device=%s; downstream Meet capture is not verified by this write",
                            self._written_chunks,
                            len(audio),
                            self.OUTPUT_RATE,
                            self.OUTPUT_CHANNELS,
                            rms,
                            peak,
                            peak == 0,
                            self._output_queue.qsize(),
                            self.output_device_name,
                            extra={
                                "interview_id": self.interview_id or "-",
                                "stage": "alena_audio_written",
                            },
                        )

                except Exception as error:
                    self._output_write_errors += 1
                    exit_reason = "write_error"
                    logger.exception(
                        "Alena audio output write failed; audio transport stopped device=%s format=int16/%sHz/%sch bytes=%s",
                        self.output_device_name,
                        self.OUTPUT_RATE,
                        self.OUTPUT_CHANNELS,
                        len(audio),
                        extra={
                            "interview_id": self.interview_id or "-",
                            "stage": "alena_audio_output",
                        },
                    )
                    self._stop_event.set()
                    break
        finally:
            logger.info(
                "Alena audio output worker exited reason=%s written_chunks=%s pending_chunks=%s output_write_errors=%s device=%s",
                exit_reason,
                self._written_chunks,
                self._output_queue.qsize(),
                self._output_write_errors,
                self.output_device_name,
                extra={"interview_id": self.interview_id or "-", "stage": "alena_audio_worker"},
            )

    # --------------------------------------------------
    # ElevenLabs audio output
    # --------------------------------------------------

    def output(self, audio: bytes):
        """Convert ElevenLabs 16 kHz mono audio to 48 kHz stereo."""

        if self._stop_event.is_set() or not audio:
            return

        try:
            if len(audio) % 2:
                raise ValueError(
                    f"ElevenLabs PCM callback contained an odd byte count: {len(audio)}."
                )
            self._received_chunks += 1
            if self._received_chunks == 1 or self._received_chunks % 50 == 0:
                samples = np.frombuffer(audio, dtype=np.int16)
                rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
                peak = int(np.max(np.abs(samples.astype(np.int32)))) if samples.size else 0
                logger.info(
                    "ElevenLabs audio received chunks=%s bytes=%s sample_count=%s format=int16/%sHz/1ch rms=%.1f peak=%s silent=%s destination_device=%s",
                    self._received_chunks,
                    len(audio),
                    samples.size,
                    self.INPUT_RATE,
                    rms,
                    peak,
                    peak == 0,
                    self.output_device_name,
                    extra={
                        "interview_id": self.interview_id or "-",
                        "stage": "elevenlabs_audio_received",
                    },
                )
            samples = np.frombuffer(audio, dtype=np.int16)

            if samples.size == 0:
                return

            # SDK output is 16-bit PCM, mono, 16 kHz.
            # Cable playback stream is 16-bit PCM, stereo, 48 kHz.
            resampled = resample_poly(
                samples.astype(np.float32),
                self.OUTPUT_RATE,
                self.INPUT_RATE,
            )

            resampled = np.clip(
                resampled,
                -32768,
                32767,
            ).astype(np.int16)

            stereo = np.column_stack((resampled, resampled))
            output_audio = stereo.tobytes()

            # Bound queued playback to avoid unbounded latency if the cable
            # device is slower than the ElevenLabs output callback. Wait for
            # the writer rather than dropping/reordering speech chunks.
            queue_wait_logged = False
            queued_count = None
            while not self._stop_event.is_set():
                try:
                    with self._output_enqueue_lock:
                        if self._stop_event.is_set():
                            break
                        self._output_queue.put_nowait(output_audio)
                        self._queued_chunks += 1
                        queued_count = self._queued_chunks
                    break
                except queue.Full:
                    self._queue_full_events += 1
                    if (
                        not queue_wait_logged
                        and (
                            self._queue_full_events == 1
                            or self._queue_full_events % 50 == 0
                        )
                    ):
                        queue_wait_logged = True
                        logger.warning(
                            "Alena audio queue full; applying playback backpressure events=%s pending_chunks=%s capacity=%s output_device=%s",
                            self._queue_full_events,
                            self._output_queue.qsize(),
                            self.OUTPUT_QUEUE_CHUNKS,
                            self.output_device_name,
                            extra={
                                "interview_id": self.interview_id or "-",
                                "stage": "alena_audio_output",
                            },
                        )
                    self._stop_event.wait(0.1)
            else:
                raise RuntimeError(
                    "Audio transport stopped before the ElevenLabs chunk could be queued."
                )

            if queued_count is None:
                raise RuntimeError(
                    "Audio transport stopped before the ElevenLabs chunk could be queued."
                )

            if queued_count == 1 or queued_count % 50 == 0:
                rms = float(
                    np.sqrt(np.mean(resampled.astype(np.float64) ** 2))
                )
                peak = int(np.max(np.abs(resampled.astype(np.int32))))
                logger.info(
                    "Alena audio queued chunks=%s input_bytes=%s input_format=int16/%sHz/1ch output_bytes=%s output_samples=%s output_format=int16/%sHz/%sch resample_ratio=%s:%s rms=%.1f peak=%s silent=%s pending_chunks=%s output_device=%s",
                    queued_count,
                    len(audio),
                    self.INPUT_RATE,
                    len(output_audio),
                    resampled.size,
                    self.OUTPUT_RATE,
                    self.OUTPUT_CHANNELS,
                    self.OUTPUT_RATE,
                    self.INPUT_RATE,
                    rms,
                    peak,
                    peak == 0,
                    self._output_queue.qsize(),
                    self.output_device_name,
                    extra={
                        "interview_id": self.interview_id or "-",
                        "stage": "alena_audio_queued",
                    },
                )

        except Exception as error:
            logger.exception(
                "ElevenLabs output callback failed; audio chunk was not queued source=ElevenLabs destination_device=%s",
                self.output_device_name,
                extra={
                    "interview_id": self.interview_id or "-",
                    "stage": "alena_audio_conversion",
                },
            )
            print(f"[AUDIO OUTPUT CALLBACK ERROR] {type(error).__name__}: {error}")
            raise

    # --------------------------------------------------
    # Interrupt
    # --------------------------------------------------

    def interrupt(self):
        """Discard queued audio after the candidate interrupts Alena."""
        discarded = 0
        while True:
            try:
                pending = self._output_queue.get_nowait()
                if pending is not None:
                    discarded += 1
            except queue.Empty:
                break
        if discarded:
            logger.info(
                "Alena queued audio discarded after interrupt chunks=%s output_device=%s",
                discarded,
                self.output_device_name,
                extra={"interview_id": self.interview_id or "-", "stage": "alena_audio_output"},
            )

    # --------------------------------------------------
    # Stop audio
    # --------------------------------------------------

    def stop(self):
        """Stop transport and defer resource closure until workers exit."""
        with self._stop_lock:
            if self._pa is None and self._input_stream is None and self._output_stream is None:
                return
            if self._cleanup_thread and self._cleanup_thread.is_alive():
                logger.info(
                    "Audio cleanup is already waiting for worker termination",
                    extra={
                        "interview_id": self.interview_id or "-",
                        "stage": "audio_cleanup",
                    },
                )
                return

            # Stop accepting new chunks atomically with output() queue writes,
            # then discard audio that has not started playing. On an ended or
            # interrupted session, stale queued speech must not play later.
            with self._output_enqueue_lock:
                self._stop_event.set()
            discarded = 0
            while True:
                try:
                    pending = self._output_queue.get_nowait()
                except queue.Empty:
                    break
                if pending is not None:
                    discarded += 1
            self._discarded_output_chunks += discarded

            streams = (self._input_stream, self._output_stream)
            audio = self._pa
            workers = tuple(
                thread
                for thread in (self._input_thread, self._output_thread)
                if thread is not None
            )

            for stream in streams:
                if stream is not None:
                    try:
                        stream.stop_stream()
                    except Exception as error:
                        logger.warning(
                            "Audio stream stop failed device=%s error_type=%s error=%s",
                            self.output_device_name
                            if stream is self._output_stream
                            else self.input_device_name,
                            type(error).__name__,
                            error,
                            extra={
                                "interview_id": self.interview_id or "-",
                                "stage": "audio_cleanup",
                            },
                        )

            current_thread = threading.current_thread()
            for thread in workers:
                if thread and thread is not current_thread and thread.is_alive():
                    thread.join(timeout=self.WORKER_JOIN_TIMEOUT)

            active_workers = [thread for thread in workers if thread.is_alive()]
            if active_workers:
                logger.error(
                    "Audio worker shutdown exceeded %.1fs; stream closure deferred worker_names=%s pending_chunks_discarded=%s output_device=%s",
                    self.WORKER_JOIN_TIMEOUT,
                    [thread.name for thread in active_workers],
                    discarded,
                    self.output_device_name,
                    extra={
                        "interview_id": self.interview_id or "-",
                        "stage": "audio_cleanup",
                    },
                )
                self._cleanup_done.clear()
                self._cleanup_thread = threading.Thread(
                    target=self._finish_deferred_cleanup,
                    args=(active_workers, streams, audio, discarded),
                    name="alena-audio-cleanup",
                    daemon=True,
                )
                self._cleanup_thread.start()
                return

            self._finish_audio_cleanup(streams, audio, discarded)

    def _finish_deferred_cleanup(self, workers, streams, audio, discarded):
        """Close devices only after every transport worker has stopped."""
        for worker in workers:
            worker.join()
        self._finish_audio_cleanup(streams, audio, discarded)

    def _finish_audio_cleanup(self, streams, audio, discarded):
        for stream in streams:
            if stream is not None:
                try:
                    stream.close()
                except Exception as error:
                    logger.exception(
                        "Audio stream close failed device=%s error_type=%s error=%s",
                        self.output_device_name
                        if stream is self._output_stream
                        else self.input_device_name,
                        type(error).__name__,
                        error,
                        extra={
                            "interview_id": self.interview_id or "-",
                            "stage": "audio_cleanup",
                        },
                    )

        if audio is not None:
            try:
                audio.terminate()
            except Exception as error:
                logger.exception(
                    "PyAudio termination failed error_type=%s error=%s",
                    type(error).__name__,
                    error,
                    extra={
                        "interview_id": self.interview_id or "-",
                        "stage": "audio_cleanup",
                    },
                )

        with self._stop_lock:
            if self._pa is audio:
                self._input_stream = None
                self._output_stream = None
                self._input_thread = None
                self._output_thread = None
                self._pa = None
            self._cleanup_thread = None
            self._cleanup_done.set()

        logger.info(
            "Audio workers terminated and streams released pending_output_discarded=%s output_device=%s",
            self._discarded_output_chunks,
            self.output_device_name,
            extra={
                "interview_id": self.interview_id or "-",
                "stage": "audio_cleanup",
            },
        )

        print(
            f"[AUDIO SUMMARY] output_queued={self._queued_chunks}, "
            f"elevenlabs_audio_received={self._received_chunks}, "
            f"output_written={self._written_chunks}, "
            f"output_write_errors={self._output_write_errors}, "
            f"input_chunks={self._input_chunks}, "
            f"input_sdk_handoffs={self._input_callback_chunks}, "
            f"input_errors={self._input_errors}"
        )
        logger.info(
            "Audio transport summary output_queued=%s elevenlabs_audio_received=%s output_written=%s output_write_errors=%s input_chunks=%s input_sdk_handoffs=%s input_errors=%s pending_output_discarded=%s output_device=%s",
            self._queued_chunks,
            self._received_chunks,
            self._written_chunks,
            self._output_write_errors,
            self._input_chunks,
            self._input_callback_chunks,
            self._input_errors,
            self._discarded_output_chunks,
            self.output_device_name,
            extra={
                "interview_id": self.interview_id or "-",
                "stage": "audio_summary",
            },
        )


# --------------------------------------------------
# Alena
# --------------------------------------------------

def run_alena(
    interview_id: int,
    stop_event: threading.Event | None = None,
):
    """Start the ElevenLabs Alena interview."""

    if not ELEVENLABS_API_KEY:
        try:
            raise ValueError("ELEVENLABS_API_KEY is missing.")
        except ValueError:
            logger.exception(
                "Interview initialization exception",
                extra={"interview_id": interview_id, "stage": "configuration_validation"},
            )
        raise ValueError("ELEVENLABS_API_KEY is missing.")

    if not ELEVENLABS_AGENT_ID:
        try:
            raise ValueError("ELEVENLABS_AGENT_ID is missing.")
        except ValueError:
            logger.exception(
                "Interview initialization exception",
                extra={"interview_id": interview_id, "stage": "configuration_validation"},
            )
        raise ValueError("ELEVENLABS_AGENT_ID is missing.")

    # Get interview information and saved questions.
    db = SessionLocal()

    log_context = set_interview_context(interview_id, "session_start")
    stage = "session_start"
    try:
        set_interview_stage(stage)
        interview = (
            db.query(Interview)
            .filter(Interview.id == interview_id)
            .first()
        )

        if not interview:
            raise ValueError(f"Interview {interview_id} not found.")

        if interview.status != InterviewStatus.IN_PROGRESS.value:
            raise ValueError(
                f"Interview {interview_id} is {interview.status}; "
                "Alena can only start for an in-progress interview."
            )

        position = (
            getattr(interview, "position", None)
            or "Sales Executive"
        )

        questions = (
            db.query(InterviewQuestion)
            .filter(InterviewQuestion.interview_id == interview_id)
            .order_by(InterviewQuestion.question_number.asc())
            .all()
        )

        question_plan, question_variables = build_question_context(questions)

    except Exception:
        logger.exception(
            "Interview setup exception",
            extra={"interview_id": interview_id, "stage": "load_interview_context"},
        )
        reset_interview_context(log_context)
        raise
    finally:
        db.close()

    # Transcript state.
    transcript = []
    current_question = {"index": 0}
    transcript_lock = threading.Lock()
    termination_lock = threading.Lock()
    termination_state = {"reason": None, "explicit_end": False}

    def record_explicit_end(message: str, source: str) -> None:
        # Only clear interview-ending language in Alena's final response or a
        # candidate's explicit request counts as a successful interview end.
        end_patterns = (
            r"\b(?:the )?interview (?:is|has been) (?:now )?(?:over|concluded|complete)\b",
            r"\b(?:ending|concluding) (?:today(?:'s)? )?interview\b",
            r"\b(?:session|interview) is now concluded\b",
        )
        stop_patterns = (
            r"\b(?:please )?(?:end|stop|terminate) (?:the )?interview\b",
            r"\bi (?:need|want) to (?:leave|stop|end)\b",
        )
        matched = any(
            re.search(pattern, message, re.IGNORECASE)
            for pattern in (stop_patterns if source == "candidate" else end_patterns)
        )
        if matched:
            is_successful_end = source != "candidate"
            reason = (
                "candidate requested to stop"
                if source == "candidate"
                else "explicit interview end language in Alena transcript"
            )
            with termination_lock:
                termination_state["reason"] = reason
                termination_state["explicit_end"] = is_successful_end
            print(
                f"[ALENA TERMINATION] Transcript end signal observed; "
                f"source={source}; reason={reason}."
            )
            logger.info(
                "Interview termination signal detected source=%s reason=%s completion_condition_satisfied=%s",
                source,
                reason,
                is_successful_end,
                extra={"interview_id": interview_id, "stage": "termination_detection"},
            )

    # Transcript callbacks.
    def on_agent_response(response):
        print(f"Alena: {response}")
        record_explicit_end(str(response), "Alena")

        with transcript_lock:
            asked_question = "?" in str(response)

            question_id = (
                question_plan[current_question["index"]]["id"]
                if (
                    asked_question
                    and current_question["index"] < len(question_plan)
                )
                else None
            )

            transcript.append(
                {
                    "interview_id": interview_id,
                    "sequence": len(transcript) + 1,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "role": "interviewer",
                    "message": response,
                    "question_id": question_id,
                    "completeness": "complete",
                }
            )

            if (
                asked_question
                and current_question["index"] < len(question_plan)
            ):
                current_question["index"] += 1

            save_live_transcript(interview_id, transcript.copy())

    def on_user_transcript(message):
        print(f"Candidate: {message}")
        record_explicit_end(str(message), "candidate")

        with transcript_lock:
            transcript.append(
                {
                    "interview_id": interview_id,
                    "sequence": len(transcript) + 1,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "role": "candidate",
                    "message": message,
                    "question_id": (
                        question_plan[
                            max(0, current_question["index"] - 1)
                        ]["id"]
                        if current_question["index"]
                        else None
                    ),
                    "completeness": "complete",
                }
            )

            save_live_transcript(interview_id, transcript.copy())

    # ElevenLabs client and conversation.
    try:
        set_interview_stage("conversation_initialization")
        elevenlabs = ElevenLabs(api_key=ELEVENLABS_API_KEY)

        conversation = Conversation(
            elevenlabs,
            ELEVENLABS_AGENT_ID,
            requires_auth=bool(ELEVENLABS_API_KEY),
            audio_interface=MeetAudioInterface(interview_id),
            callback_agent_response=on_agent_response,
            callback_user_transcript=on_user_transcript,
            config=ConversationInitiationData(
                dynamic_variables={
                    "position": position,
                    "interview_position": position,
                    **question_variables,
                }
            ),
        )
    except Exception:
        logger.exception(
            "Interview initialization exception",
            extra={"interview_id": interview_id, "stage": "conversation_initialization"},
        )
        reset_interview_context(log_context)
        raise

    # Maximum interview timer.
    session_started = False
    session_finished = False
    timed_out = threading.Event()
    session_ended = threading.Event()
    stop_watcher = None
    sdk_thread_id = None

    end_session_lock = threading.Lock()
    end_session_requested = threading.Event()
    end_session_call_done = threading.Event()

    def request_session_end(reason: str) -> None:
        """Request shutdown once even when timer, Meet, and finally race."""
        with end_session_lock:
            if end_session_requested.is_set():
                already_requested = True
            else:
                already_requested = False
                end_session_requested.set()
                if termination_state["reason"] is None:
                    termination_state["reason"] = reason
        if already_requested:
            logger.info(
                "Duplicate session end request; waiting for current cleanup reason=%s",
                reason,
                extra={"interview_id": interview_id, "stage": "termination_request"},
            )
            end_session_call_done.wait(timeout=2)
            return
        logger.info(
            "Session end requested reason=%s",
            reason,
            extra={"interview_id": interview_id, "stage": "termination_request"},
        )
        print(f"[ALENA TERMINATION] Session end requested; reason={reason}.")
        try:
            conversation.end_session()
        finally:
            end_session_call_done.set()

    def end_for_timeout():
        with termination_lock:
            if session_ended.is_set():
                logger.info(
                    "Duration timer fired after session cleanup began; request ignored",
                    extra={"interview_id": interview_id, "stage": "duration_timer"},
                )
                return
            if termination_state["explicit_end"]:
                logger.info(
                    "Configured duration timer fired after explicit completion; completion preserved",
                    extra={"interview_id": interview_id, "stage": "duration_timer"},
                )
                print(
                    "[ALENA TERMINATION] Duration timer fired after an explicit "
                    "completion event; keeping the completed outcome."
                )
                return
            timed_out.set()
        logger.warning(
            "Configured interview duration reached",
            extra={"interview_id": interview_id, "stage": "duration_timer"},
        )
        request_session_end("configured interview duration reached")

    timer = threading.Timer(
        MAX_INTERVIEW_SECONDS,
        end_for_timeout,
    )

    try:
        print()
        print("=" * 40)
        print("        ALENA INTERVIEW STARTED")
        print("=" * 40)
        print()
        print("Connecting to ElevenLabs...")

        conversation.start_session()
        session_started = True
        sdk_thread = getattr(conversation, "_thread", None)
        sdk_thread_id = sdk_thread.ident if sdk_thread is not None else None
        if sdk_thread_id is not None:
            bind_thread_context(sdk_thread_id, interview_id, "session_start")

        logger.info("ElevenLabs session started")
        print("ElevenLabs session started.")
        print("Alena is ready.")

        timer.start()

        if stop_event is not None:
            def watch_stop_request():
                while not session_ended.is_set():
                    if stop_event.wait(0.25):
                        request_session_end("Meet/browser termination confirmed")
                        return

            stop_watcher = threading.Thread(
                target=watch_stop_request,
                daemon=True,
            )
            stop_watcher.start()

        stage = "wait_for_session_end"
        set_interview_stage(stage)
        if sdk_thread_id is not None:
            set_thread_stage(sdk_thread_id, stage)
        logger.info("Waiting for ElevenLabs session termination")
        conversation.wait_for_session_end()
        session_finished = True
        with termination_lock:
            if termination_state["reason"] is None:
                termination_state["reason"] = "ElevenLabs session ended without a recognized end event"
        print(
            "[ALENA TERMINATION] ElevenLabs wait_for_session_end returned; "
            f"timed_out={timed_out.is_set()}; "
            f"reason={termination_state['reason']}"
        )

    except Exception as error:
        logger.exception(
            "Interview execution exception before cleanup: %s",
            type(error).__name__,
            extra={"interview_id": interview_id, "stage": stage},
        )
        error_text = safe_diagnostic(error)

        print()
        print("=" * 40)
        print("        ALENA INTERVIEW FAILED")
        print("=" * 40)
        print(f"Error: {error_text}")
        print()

        print(f"[ALENA TERMINATION] Interview execution failed; reason={error_text}")
        mark_failed(interview_id, error_text)

        with transcript_lock:
            transcript_path = save_transcript(
                interview_id,
                transcript.copy(),
            )

        save_transcript_path(interview_id, transcript_path)

        return {
            "status": "failed",
            "transcript_path": transcript_path,
            "error": error_text,
        }

    finally:
        session_ended.set()
        timer.cancel()
        if timer.is_alive():
            timer.join(timeout=1)
            if timer.is_alive():
                logger.error(
                    "Duration timer thread did not stop during cleanup",
                    extra={"interview_id": interview_id, "stage": "session_cleanup"},
                )
        if sdk_thread_id is not None:
            unbind_thread_context(sdk_thread_id)

        if stop_watcher and stop_watcher.is_alive():
            stop_watcher.join(timeout=2)
            if stop_watcher.is_alive():
                logger.error(
                    "Meet termination watcher did not stop during cleanup",
                    extra={"interview_id": interview_id, "stage": "session_cleanup"},
                )

        try:
            set_interview_stage("session_cleanup")
            request_session_end("run_alena cleanup")
        except Exception as cleanup_error:
            logger.exception(
                "Session cleanup exception; original interview outcome is preserved: %s",
                type(cleanup_error).__name__,
                extra={"interview_id": interview_id, "stage": "session_cleanup"},
            )
            print(
                f"[ALENA] Session cleanup failed for interview "
                f"{interview_id}: {type(cleanup_error).__name__}"
            )
        reset_interview_context(log_context)

    # Final transcript and status.
    with termination_lock:
        explicit_completion = termination_state["explicit_end"]
        termination_reason = termination_state["reason"]
        did_timeout = timed_out.is_set()
    if session_started and session_finished:
        if explicit_completion:
            mark_completed(interview_id, termination_reason or "explicit completion event")
            final_status = "completed"
        elif did_timeout or (
            stop_event is not None and stop_event.is_set()
        ):
            mark_interrupted(interview_id, termination_reason or "timer or Meet termination")
            final_status = "interrupted"
        else:
            # A normal return from the SDK only confirms disconnection. It is
            # not evidence that the interview completed successfully.
            mark_interrupted(interview_id, termination_reason or "unexpected ElevenLabs session exit")
            final_status = "interrupted"
            print(
                "[ALENA TERMINATION] Unexpected session end; "
                f"status=interrupted; reason={termination_reason}"
            )

        logger.info(
            "Interview session ended status=%s reason=%s",
            final_status,
            termination_reason,
            extra={"interview_id": interview_id, "stage": "status_update"},
        )

        with transcript_lock:
            transcript_path = save_transcript(
                interview_id,
                transcript.copy(),
            )

        save_transcript_path(interview_id, transcript_path)

        print()
        print("=" * 40)
        print(f"        ALENA INTERVIEW {final_status.upper()}")
        print("=" * 40)
        print(f"Transcript: {transcript_path}")
        print()

        return {
            "status": final_status,
            "transcript_path": transcript_path,
        }


# --------------------------------------------------
# Direct execution
# --------------------------------------------------

if __name__ == "__main__":
    print("ElevenLabs Alena service.")
    print("Live transcript saving enabled.")
    print("The interview scheduler starts Alena automatically.")
