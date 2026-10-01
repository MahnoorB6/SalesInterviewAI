import os
import queue
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
    """Save the current transcript to a text file."""

    path = TRANSCRIPT_DIR / f"interview_{interview_id}.txt"

    with open(path, "w", encoding="utf-8") as file:

        for item in transcript:

            role = item.get("role", "")
            message = item.get("message", "")

            file.write(
                f"{role.upper()}: {message}\n"
            )

    return str(path)


def save_transcript_path(interview_id: int, path: str):
    """Save transcript path to the database."""

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
):
    """Save the transcript immediately during the interview."""

    try:

        path = save_transcript(
            interview_id,
            transcript,
        )

        save_transcript_path(
            interview_id,
            path,
        )

        print(
            f"[TRANSCRIPT] Updated: {path}"
        )

    except Exception as error:

        print(
            f"[TRANSCRIPT] Save error: {error}"
        )


# --------------------------------------------------
# Interview status functions
# --------------------------------------------------

def mark_completed(interview_id: int):
    """Mark the interview as completed."""

    db = SessionLocal()

    try:

        interview = (
            db.query(Interview)
            .filter(Interview.id == interview_id)
            .first()
        )

        if interview:

            interview.status = "completed"

            interview.completed_at = (
                datetime.now(timezone.utc)
            )

            db.commit()

    finally:
        db.close()


def mark_interrupted(interview_id: int):
    """Mark the interview as interrupted."""

    db = SessionLocal()

    try:

        interview = (
            db.query(Interview)
            .filter(Interview.id == interview_id)
            .first()
        )

        if interview:

            interview.status = "interrupted"

            db.commit()

    finally:
        db.close()


class MeetAudioInterface(AudioInterface):
    """Transport Google Meet audio to and from ElevenLabs.

    ElevenLabs handles speech recognition, conversation logic, and voice
    generation. PyAudioWPatch is only the Windows audio transport and
    WASAPI loopback capture layer.

    Routing:
        Google Meet speakers -> WASAPI loopback -> ElevenLabs input
        ElevenLabs output -> VB-CABLE Input -> VB-CABLE Output
        -> Google Meet microphone

    This uses the existing single VB-CABLE. No A+B and no Voicemeeter.
    """

    INPUT_RATE = 16000
    OUTPUT_RATE = 48000
    OUTPUT_CHANNELS = 2
    FORMAT = pyaudio.paInt16
    INPUT_FRAMES = 960
    OUTPUT_FRAMES = 1000

    def __init__(self):
        self.output_device_name = os.getenv(
            "ELEVENLABS_AUDIO_OUTPUT_DEVICE",
            "CABLE Input (VB-Audio Virtual Cable)",
        )
        self.loopback_device_name = os.getenv(
            "ELEVENLABS_AUDIO_LOOPBACK_DEVICE",
            "",
        )
        self._pa = None
        self._input_stream = None
        self._output_stream = None
        self._input_callback = None
        self._output_queue = queue.Queue()
        self._stop_event = threading.Event()
        self._output_thread = None
        self._input_channels = 2
        self._input_rate = 48000

    def _find_output_device(self, name):
        target = name.lower().strip()

        for index in range(self._pa.get_device_count()):
            info = self._pa.get_device_info_by_index(index)
            device_name = str(info.get("name", ""))

            if (
                target in device_name.lower()
                and int(info.get("maxOutputChannels", 0)) > 0
            ):
                return index, device_name

        available = []
        for index in range(self._pa.get_device_count()):
            info = self._pa.get_device_info_by_index(index)

            if int(info.get("maxOutputChannels", 0)) > 0:
                available.append(
                    f"{index}: {info.get('name', '')}"
                )

        raise RuntimeError(
            f"ElevenLabs output device not found: {name!r}. "
            f"Available output devices: {available}"
        )

    def _find_loopback_device(self):
        if self.loopback_device_name:
            target = self.loopback_device_name.lower().strip()

            for info in self._pa.get_loopback_device_info_generator():
                device_name = str(info.get("name", ""))

                if target in device_name.lower():
                    return info

            raise RuntimeError(
                "Requested WASAPI loopback device was not found: "
                f"{self.loopback_device_name!r}"
            )

        try:
            return self._pa.get_default_wasapi_loopback()
        except (OSError, LookupError) as error:
            raise RuntimeError(
                "Could not find the WASAPI loopback for the default "
                "Windows speaker. Make sure Google Meet uses the "
                "physical/default Windows speakers."
            ) from error

    def start(self, input_callback):
        self._input_callback = input_callback
        self._stop_event.clear()
        self._pa = pyaudio.PyAudio()

        loopback = self._find_loopback_device()
        loopback_index = int(loopback["index"])
        loopback_name = str(loopback["name"])

        self._input_channels = max(
            1,
            min(
                int(loopback.get("maxInputChannels", 2)),
                2,
            ),
        )
        self._input_rate = int(
            loopback.get("defaultSampleRate", 48000)
        )

        output_index, output_name = self._find_output_device(
            self.output_device_name
        )

        self._input_stream = self._pa.open(
            format=self.FORMAT,
            channels=self._input_channels,
            rate=self._input_rate,
            input=True,
            input_device_index=loopback_index,
            frames_per_buffer=self.INPUT_FRAMES,
        )

        self._output_stream = self._pa.open(
            format=self.FORMAT,
            channels=self.OUTPUT_CHANNELS,
            rate=self.OUTPUT_RATE,
            output=True,
            output_device_index=output_index,
            frames_per_buffer=self.OUTPUT_FRAMES,
        )

        print(f"[AUDIO] ElevenLabs input: {loopback_name}")
        print(
            "[AUDIO] Input: WASAPI loopback / "
            f"{self._input_channels}ch / {self._input_rate} Hz"
        )
        print(f"[AUDIO] ElevenLabs output: {output_name}")
        print(
            "[AUDIO] Output: 16-bit PCM / stereo / "
            f"{self.OUTPUT_RATE} Hz"
        )

        self._output_thread = threading.Thread(
            target=self._output_worker,
            name="alena-audio-output",
            daemon=True,
        )
        self._output_thread.start()

        threading.Thread(
            target=self._input_worker,
            name="meet-audio-input",
            daemon=True,
        ).start()

    def _input_worker(self):
        while not self._stop_event.is_set():
            try:
                audio = self._input_stream.read(
                    self.INPUT_FRAMES,
                    exception_on_overflow=False,
                )

                if not audio or not self._input_callback:
                    continue

                samples = np.frombuffer(
                    audio,
                    dtype=np.int16,
                )

                if self._input_channels > 1:
                    usable = (
                        samples.size // self._input_channels
                    ) * self._input_channels

                    samples = samples[:usable].reshape(
                        -1,
                        self._input_channels,
                    ).mean(axis=1)

                if self._input_rate != self.INPUT_RATE:
                    samples = resample_poly(
                        samples,
                        self.INPUT_RATE,
                        self._input_rate,
                    )

                samples = np.clip(
                    samples,
                    -32768,
                    32767,
                ).astype(np.int16)

                self._input_callback(samples.tobytes())

            except Exception as error:
                if not self._stop_event.is_set():
                    print(f"[AUDIO INPUT ERROR] {error}")
                break

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
            except Exception as error:
                if not self._stop_event.is_set():
                    print(f"[AUDIO OUTPUT ERROR] {error}")

    def output(self, audio: bytes):
        if self._stop_event.is_set():
            return

        try:
            samples = np.frombuffer(
                audio,
                dtype=np.int16,
            )

            if samples.size == 0:
                return

            resampled = resample_poly(
                samples,
                self.OUTPUT_RATE,
                self.INPUT_RATE,
            )

            resampled = np.clip(
                resampled,
                -32768,
                32767,
            ).astype(np.int16)

            stereo = np.column_stack(
                (resampled, resampled)
            )

            self._output_queue.put(stereo.tobytes())

        except Exception as error:
            print(
                f"[AUDIO OUTPUT CONVERSION ERROR] {error}"
            )

    def interrupt(self):
        while True:
            try:
                self._output_queue.get_nowait()
            except queue.Empty:
                break

    def stop(self):
        self._stop_event.set()
        self.interrupt()
        self._output_queue.put(None)

        for stream in (
            self._input_stream,
            self._output_stream,
        ):
            if stream is not None:
                try:
                    stream.stop_stream()
                except Exception:
                    pass

                try:
                    stream.close()
                except Exception:
                    pass

        if self._output_thread and self._output_thread.is_alive():
            self._output_thread.join(timeout=1)

        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass

        self._input_stream = None
        self._output_stream = None
        self._output_thread = None
        self._pa = None


# --------------------------------------------------
# Alena
# --------------------------------------------------

def run_alena(interview_id: int):
    """Start the ElevenLabs Alena interview."""

    if not ELEVENLABS_API_KEY:

        raise ValueError(
            "ELEVENLABS_API_KEY is missing."
        )

    if not ELEVENLABS_AGENT_ID:

        raise ValueError(
            "ELEVENLABS_AGENT_ID is missing."
        )

    # --------------------------------------------------
    # Get interview information
    # --------------------------------------------------

    db = SessionLocal()

    try:

        interview = (
            db.query(Interview)
            .filter(Interview.id == interview_id)
            .first()
        )

        if not interview:

            raise ValueError(
                f"Interview {interview_id} not found."
            )

        position = (
            getattr(
                interview,
                "position",
                None,
            )
            or "Sales Executive"
        )

    finally:

        db.close()

    # --------------------------------------------------
    # Transcript
    # --------------------------------------------------

    transcript = []

    # Lock prevents simultaneous transcript writes.
    transcript_lock = threading.Lock()

    # --------------------------------------------------
    # Callbacks
    # --------------------------------------------------

    def on_agent_response(response):

        print(
            f"Alena: {response}"
        )

        with transcript_lock:

            transcript.append(
                {
                    "role": "Alena",
                    "message": response,
                }
            )

            # SAVE IMMEDIATELY
            save_live_transcript(
                interview_id,
                transcript.copy(),
            )


    def on_user_transcript(message):

        print(
            f"Candidate: {message}"
        )

        with transcript_lock:

            transcript.append(
                {
                    "role": "Candidate",
                    "message": message,
                }
            )

            # SAVE IMMEDIATELY
            save_live_transcript(
                interview_id,
                transcript.copy(),
            )

    # --------------------------------------------------
    # ElevenLabs
    # --------------------------------------------------

    elevenlabs = ElevenLabs(
        api_key=ELEVENLABS_API_KEY
    )

    conversation = Conversation(
        elevenlabs,
        ELEVENLABS_AGENT_ID,
        requires_auth=bool(
            ELEVENLABS_API_KEY
        ),
        audio_interface=MeetAudioInterface(),
        callback_agent_response=on_agent_response,
        callback_user_transcript=on_user_transcript,
        config=ConversationInitiationData(
            dynamic_variables={
                "position": position,
                "interview_position": position,
            }
        ),
    )

    # --------------------------------------------------
    # Maximum interview timer
    # --------------------------------------------------

    timer = threading.Timer(
        MAX_INTERVIEW_SECONDS,
        conversation.end_session,
    )

    session_started = False
    session_finished = False

    # --------------------------------------------------
    # Start session
    # --------------------------------------------------

    try:

        print()
        print("=" * 40)
        print("        ALENA INTERVIEW STARTED")
        print("=" * 40)
        print()

        print(
            "Connecting to ElevenLabs..."
        )

        conversation.start_session()

        session_started = True

        print(
            "ElevenLabs session started."
        )

        print(
            "Alena is ready."
        )

        timer.start()

        conversation.wait_for_session_end()

        session_finished = True

    except Exception as error:

        error_text = str(error)

        print()
        print("=" * 40)
        print("        ALENA INTERVIEW FAILED")
        print("=" * 40)
        print(
            f"Error: {error_text}"
        )
        print()

        # Save whatever transcript exists.
        with transcript_lock:

            transcript_path = save_transcript(
                interview_id,
                transcript.copy(),
            )

        save_transcript_path(
            interview_id,
            transcript_path,
        )

        mark_interrupted(
            interview_id
        )

        return {
            "status": "interrupted",
            "transcript_path": transcript_path,
            "error": error_text,
        }

    finally:

        timer.cancel()

    # --------------------------------------------------
    # Final transcript
    # --------------------------------------------------

    if session_started and session_finished:

        with transcript_lock:

            transcript_path = save_transcript(
                interview_id,
                transcript.copy(),
            )

        save_transcript_path(
            interview_id,
            transcript_path,
        )

        mark_completed(
            interview_id
        )

        print()
        print("=" * 40)
        print("        ALENA INTERVIEW COMPLETED")
        print("=" * 40)
        print(
            f"Transcript: {transcript_path}"
        )
        print()

        return {
            "status": "completed",
            "transcript_path": transcript_path,
        }


if __name__ == "__main__":

    print(
        "ElevenLabs Alena service."
    )

    print(
        "Live transcript saving enabled."
    )

    print(
        "The interview scheduler starts Alena automatically."
    )