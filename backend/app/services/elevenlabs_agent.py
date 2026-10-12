
import os
import queue
import json
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


load_dotenv()

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

def mark_completed(interview_id: int) -> None:
    db = SessionLocal()
    try:
        interview = (
            db.query(Interview)
            .filter(Interview.id == interview_id)
            .first()
        )

        if interview and can_transition_interview(
            interview.status,
            InterviewStatus.COMPLETED.value,
        ):
            interview.status = InterviewStatus.COMPLETED.value
            interview.completed_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


def mark_interrupted(interview_id: int) -> None:
    db = SessionLocal()
    try:
        interview = (
            db.query(Interview)
            .filter(Interview.id == interview_id)
            .first()
        )

        if interview and can_transition_interview(
            interview.status,
            InterviewStatus.INTERRUPTED.value,
        ):
            interview.status = InterviewStatus.INTERRUPTED.value
            db.commit()
    finally:
        db.close()


def mark_failed(interview_id: int, diagnostic: str) -> None:
    """Record a failed execution without exposing diagnostic text in public fields."""

    db = SessionLocal()
    try:
        interview = (
            db.query(Interview)
            .filter(Interview.id == interview_id)
            .first()
        )

        if interview and can_transition_interview(
            interview.status,
            InterviewStatus.FAILED.value,
        ):
            interview.status = InterviewStatus.FAILED.value
            db.commit()

        print(
            f"[ALENA] Interview {interview_id} marked failed "
            "after an execution error."
        )
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

    INPUT_FRAMES = 4000
    OUTPUT_FRAMES = 1000

    def __init__(self):
        self.meet_microphone_name = os.getenv(
            "MEET_MIC_DEVICE",
            "CABLE Output (VB-Audio Virtual Cable)",
        ).strip()

        self.loopback_device_name = get_meet_speaker_device_name()

        self.output_device_name = os.getenv(
            "ELEVENLABS_AUDIO_OUTPUT_DEVICE",
            "CABLE Input (VB-Audio Virtual Cable)",
        ).strip()

        self._pa = None
        self._input_stream = None
        self._output_stream = None

        self._input_callback = None

        self._output_queue = queue.Queue()
        self._stop_event = threading.Event()

        self._output_thread = None
        self._input_thread = None

        self._queued_chunks = 0
        self._written_chunks = 0
        self._output_write_errors = 0
        self._input_chunks = 0
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

            if target in device_name.casefold():
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

        # Prefer the closest exact name if duplicate/variant names exist.
        exact = [
            item for item in matches
            if item[1].casefold().strip() == target
        ]
        selected = exact[0] if exact else matches[0]

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
        self._output_queue = queue.Queue()

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

        except Exception:
            self.stop()
            raise

    # --------------------------------------------------
    # Candidate input worker
    # --------------------------------------------------

    def _input_worker(self):
        while not self._stop_event.is_set():
            try:
                audio = self._input_stream.read(
                    self.INPUT_FRAMES,
                    exception_on_overflow=False,
                )

                if not audio:
                    continue

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
                    self._input_callback(resampled.tobytes())

            except Exception as error:
                if not self._stop_event.is_set():
                    self._input_errors += 1
                    print(
                        f"[AUDIO INPUT ERROR] "
                        f"{type(error).__name__}: {error}"
                    )
                break

    # --------------------------------------------------
    # Alena output worker
    # --------------------------------------------------

    def _output_worker(self):
        while not self._stop_event.is_set():
            try:
                audio = self._output_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if audio is None:
                break

            try:
                self._output_stream.write(audio)
                self._written_chunks += 1

                if self._written_chunks == 1 or self._written_chunks % 50 == 0:
                    print(
                        f"[AUDIO OUTPUT WRITTEN] "
                        f"chunks={self._written_chunks} "
                        f"bytes={len(audio)} "
                        f"device={self.output_device_name!r}"
                    )

            except Exception as error:
                if not self._stop_event.is_set():
                    self._output_write_errors += 1

                    if (
                        self._output_write_errors == 1
                        or self._output_write_errors % 10 == 0
                    ):
                        print(
                            f"[AUDIO OUTPUT ERROR] "
                            f"write_failures={self._output_write_errors} "
                            f"device={self.output_device_name!r} "
                            f"{type(error).__name__}: {error}"
                        )

    # --------------------------------------------------
    # ElevenLabs audio output
    # --------------------------------------------------

    def output(self, audio: bytes):
        """Convert ElevenLabs 16 kHz mono audio to 48 kHz stereo."""

        if self._stop_event.is_set() or not audio:
            return

        try:
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

            self._queued_chunks += 1

            if self._queued_chunks == 1 or self._queued_chunks % 50 == 0:
                rms = float(
                    np.sqrt(np.mean(resampled.astype(np.float64) ** 2))
                )
                print(
                    f"[AUDIO OUTPUT QUEUED] "
                    f"chunks={self._queued_chunks} "
                    f"input_bytes={len(audio)} "
                    f"output_bytes={len(output_audio)} "
                    f"rms={rms:.1f}"
                )

            self._output_queue.put(output_audio)

        except Exception as error:
            print(
                f"[AUDIO OUTPUT CONVERSION ERROR] "
                f"{type(error).__name__}: {error}"
            )

    # --------------------------------------------------
    # Interrupt
    # --------------------------------------------------

    def interrupt(self):
        """Discard queued audio after the candidate interrupts Alena."""

        while True:
            try:
                self._output_queue.get_nowait()
            except queue.Empty:
                break

    # --------------------------------------------------
    # Stop audio
    # --------------------------------------------------

    def stop(self):
        """Stop worker threads and close audio resources safely."""

        self._stop_event.set()

        try:
            self._output_queue.put_nowait(None)
        except Exception:
            pass

        for stream in (self._input_stream, self._output_stream):
            if stream is not None:
                try:
                    stream.stop_stream()
                except Exception:
                    pass

        for thread in (self._input_thread, self._output_thread):
            if thread and thread.is_alive():
                thread.join(timeout=1.5)

        for stream in (self._input_stream, self._output_stream):
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass

        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass

        self._input_stream = None
        self._output_stream = None
        self._input_thread = None
        self._output_thread = None
        self._pa = None

        print(
            f"[AUDIO SUMMARY] output_queued={self._queued_chunks}, "
            f"output_written={self._written_chunks}, "
            f"output_write_errors={self._output_write_errors}, "
            f"input_chunks={self._input_chunks}, "
            f"input_errors={self._input_errors}"
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
        raise ValueError("ELEVENLABS_API_KEY is missing.")

    if not ELEVENLABS_AGENT_ID:
        raise ValueError("ELEVENLABS_AGENT_ID is missing.")

    # Get interview information and saved questions.
    db = SessionLocal()

    try:
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

    finally:
        db.close()

    # Transcript state.
    transcript = []
    current_question = {"index": 0}
    transcript_lock = threading.Lock()

    # Transcript callbacks.
    def on_agent_response(response):
        print(f"Alena: {response}")

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
    elevenlabs = ElevenLabs(api_key=ELEVENLABS_API_KEY)

    conversation = Conversation(
        elevenlabs,
        ELEVENLABS_AGENT_ID,
        requires_auth=bool(ELEVENLABS_API_KEY),
        audio_interface=MeetAudioInterface(),
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

    # Maximum interview timer.
    session_started = False
    session_finished = False
    timed_out = threading.Event()
    session_ended = threading.Event()
    stop_watcher = None

    def end_for_timeout():
        timed_out.set()
        conversation.end_session()

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

        print("ElevenLabs session started.")
        print("Alena is ready.")

        timer.start()

        if stop_event is not None:
            def watch_stop_request():
                while not session_ended.is_set():
                    if stop_event.wait(0.25):
                        conversation.end_session()
                        return

            stop_watcher = threading.Thread(
                target=watch_stop_request,
                daemon=True,
            )
            stop_watcher.start()

        conversation.wait_for_session_end()
        session_finished = True

    except Exception as error:
        error_text = safe_diagnostic(error)

        print()
        print("=" * 40)
        print("        ALENA INTERVIEW FAILED")
        print("=" * 40)
        print(f"Error: {error_text}")
        print()

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

        if stop_watcher and stop_watcher.is_alive():
            stop_watcher.join(timeout=1)

        try:
            conversation.end_session()
        except Exception as cleanup_error:
            print(
                f"[ALENA] Session cleanup failed for interview "
                f"{interview_id}: {type(cleanup_error).__name__}"
            )

    # Final transcript and status.
    if session_started and session_finished:
        if timed_out.is_set() or (
            stop_event is not None and stop_event.is_set()
        ):
            mark_interrupted(interview_id)
            final_status = "interrupted"
        else:
            mark_completed(interview_id)
            final_status = "completed"

        with transcript_lock:
            transcript_path = save_transcript(
                interview_id,
                transcript.copy(),
            )

        save_transcript_path(interview_id, transcript_path)

        print()
        print("=" * 40)
        print("        ALENA INTERVIEW COMPLETED")
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
