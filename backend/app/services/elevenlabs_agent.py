import os
import threading
import time
from datetime import datetime, timezone

import numpy as np
import pyaudio
from dotenv import load_dotenv
from scipy.signal import resample_poly

from elevenlabs.client import ElevenLabs
from elevenlabs.conversational_ai.conversation import (
    AudioInterface,
    Conversation,
    ConversationInitiationData,
)

from app.database.database import SessionLocal
from app.models.interview import Interview
from app.models.interview_question import InterviewQuestion


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()

API_KEY = os.getenv("ELEVENLABS_API_KEY")
AGENT_ID = os.getenv("ELEVENLABS_AGENT_ID")


# ============================================================
# AUDIO DEVICES
# ============================================================

# Candidate audio coming FROM Google Meet.
#
# Google Meet SPEAKER:
#     CABLE Input
#
# Python candidate input:
#     CABLE Output
#
CABLE_INPUT_CANDIDATES = [
    "CABLE Output (VB-Audio Virtual Cable)",
]

# Alena audio going INTO Google Meet microphone.
#
# Python output:
#     CABLE Input
#
# Google Meet MICROPHONE:
#     CABLE Output
#
CABLE_OUTPUT_CANDIDATES = [
    "CABLE Input (VB-Audio Virtual Cable)"
]


# ============================================================
# AUDIO SETTINGS
# ============================================================

ELEVENLABS_RATE = 16000

INPUT_RATE = 44100
INPUT_CHANNELS = 2
INPUT_CHUNK = 2048

OUTPUT_RATE = 44100
OUTPUT_CHANNELS = 2
OUTPUT_CHUNK = 1024

MIN_AUDIO_LEVEL = 50


# ============================================================
# INTERVIEW SETTINGS
# ============================================================

MAX_INTERVIEW_SECONDS = 30 * 60


# ============================================================
# TRANSCRIPTS
# ============================================================

TRANSCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data",
    "transcripts",
)

os.makedirs(
    TRANSCRIPT_DIR,
    exist_ok=True,
)


# ============================================================
# AUDIO HELPERS
# ============================================================

def find_device(
    p,
    names,
    input_device=False,
    output_device=False,
):
    """
    Find the first matching usable PortAudio device.
    """

    if isinstance(names, str):
        candidates = [names]
    else:
        candidates = list(names)

    candidates_lower = [c.lower() for c in candidates]

    for candidate in candidates_lower:

        for index in range(p.get_device_count()):

            try:

                info = p.get_device_info_by_index(index)

                device_name = str(
                    info.get("name", "")
                ).lower()

                if candidate not in device_name:
                    continue

                if input_device:

                    if (
                        int(
                            info.get(
                                "maxInputChannels",
                                0,
                            )
                        )
                        <= 0
                    ):
                        continue

                if output_device:

                    if (
                        int(
                            info.get(
                                "maxOutputChannels",
                                0,
                            )
                        )
                        <= 0
                    ):
                        continue

                return index, info

            except Exception:
                continue

    return None, None


def find_all_devices(
    p,
    names,
    input_device=False,
    output_device=False,
):
    """
    Return every matching device/backend variant.

    WASAPI is preferred because it generally provides
    more reliable Windows audio routing for virtual
    audio devices such as VB-Audio Cable.
    """

    if isinstance(names, str):
        candidates = [names]
    else:
        candidates = list(names)

    candidates_lower = [c.lower() for c in candidates]

    matches = []

    for candidate in candidates_lower:

        for index in range(p.get_device_count()):

            try:

                info = p.get_device_info_by_index(index)

                device_name = str(
                    info.get("name", "")
                ).lower()

                if candidate not in device_name:
                    continue

                if input_device:

                    if (
                        int(info.get("maxInputChannels", 0))
                        <= 0
                    ):
                        continue

                if output_device:

                    if (
                        int(info.get("maxOutputChannels", 0))
                        <= 0
                    ):
                        continue

                try:

                    host_api_info = p.get_host_api_info_by_index(
                        info.get("hostApi", 0)
                    )

                    host_api_name = host_api_info.get(
                        "name",
                        "",
                    )

                except Exception:

                    host_api_name = ""

                matches.append(
                    (index, info, host_api_name)
                )

            except Exception:
                continue

    seen = set()
    unique_matches = []

    for match in matches:

        index = match[0]

        if index in seen:
            continue

        seen.add(index)
        unique_matches.append(match)

    # ========================================================
    # IMPORTANT:
    # Prefer WASAPI over DirectSound.
    #
    # Previous order:
    # MME -> DirectSound -> WDM-KS -> WASAPI
    #
    # New order:
    # WASAPI -> DirectSound -> WDM-KS -> MME
    # ========================================================

    backend_priority = {
        "Windows WASAPI": 0,
        "Windows DirectSound": 1,
        "Windows WDM-KS": 2,
        "MME": 3,
    }

    unique_matches.sort(
        key=lambda m: backend_priority.get(m[2], 4)
    )

    return unique_matches


def resample_audio(
    audio,
    source_rate,
    target_rate,
):
    """
    Convert audio from one sample rate to another.
    """

    if audio is None:
        return np.array([], dtype=np.int16)

    if len(audio) == 0:
        return np.array([], dtype=np.int16)

    if source_rate == target_rate:
        return audio.astype(
            np.int16,
            copy=False,
        )

    converted = resample_poly(
        audio.astype(np.float32),
        target_rate,
        source_rate,
    )

    return np.clip(
        converted,
        -32768,
        32767,
    ).astype(np.int16)


def stereo_to_mono(
    audio,
    channels,
):
    """
    Convert incoming audio to mono.
    """

    if audio is None:
        return np.array([], dtype=np.int16)

    if len(audio) == 0:
        return np.array([], dtype=np.int16)

    channels = max(
        1,
        int(channels),
    )

    if channels == 1:

        return audio.astype(
            np.int16,
            copy=False,
        )

    usable = (
        len(audio)
        - (
            len(audio)
            % channels
        )
    )

    if usable <= 0:
        return np.array([], dtype=np.int16)

    data = audio[:usable].reshape(
        -1,
        channels,
    )

    mono = np.mean(
        data.astype(np.float32),
        axis=1,
    )

    return np.clip(
        mono,
        -32768,
        32767,
    ).astype(np.int16)


def mono_to_stereo(
    audio,
):
    """
    Convert mono audio to stereo.
    """

    if audio is None:
        return np.array([], dtype=np.int16)

    if len(audio) == 0:
        return np.array([], dtype=np.int16)

    audio = audio.astype(
        np.int16,
        copy=False,
    )

    return np.repeat(
        audio[:, None],
        2,
        axis=1,
    ).reshape(-1)


# ============================================================
# DATABASE
# ============================================================

def load_interview_data(
    interview_id,
):
    """
    Load the interview position and questions
    from PostgreSQL.
    """

    db = SessionLocal()

    try:

        interview = (
            db.query(Interview)
            .filter(
                Interview.id == interview_id
            )
            .first()
        )

        if not interview:

            raise RuntimeError(
                f"Interview #{interview_id} "
                "was not found."
            )

        position = (
            getattr(
                interview,
                "position",
                None,
            )
            or "Sales Representative"
        )

        questions = (
            db.query(
                InterviewQuestion
            )
            .filter(
                InterviewQuestion.interview_id
                == interview_id
            )
            .order_by(
                InterviewQuestion.id
            )
            .all()
        )

        question_list = []

        for number, question in enumerate(
            questions,
            start=1,
        ):

            text = (
                getattr(
                    question,
                    "question",
                    None,
                )
                or getattr(
                    question,
                    "question_text",
                    None,
                )
            )

            if text:

                question_list.append(
                    f"{number}. {text}"
                )

        return (
            position,
            question_list,
        )

    finally:

        db.close()


def get_transcript_path(
    interview_id,
):
    return os.path.join(
        TRANSCRIPT_DIR,
        f"interview_{interview_id}.txt",
    )


def save_transcript(
    path,
    lines,
):
    if not path:
        return

    try:

        with open(
            path,
            "w",
            encoding="utf-8",
        ) as file:

            for line in lines:
                file.write(
                    line + "\n"
                )

    except Exception as e:

        print(
            f"[TRANSCRIPT] Save error: {e}"
        )


def set_transcript_path(
    interview_id,
    path,
):
    db = SessionLocal()

    try:

        interview = (
            db.query(Interview)
            .filter(
                Interview.id == interview_id
            )
            .first()
        )

        if not interview:
            return

        interview.transcript_path = path

        db.commit()

    except Exception as e:

        db.rollback()

        print(
            f"[DB] Transcript path error: {e}"
        )

    finally:

        db.close()


def mark_completed(
    interview_id,
):
    db = SessionLocal()

    try:

        interview = (
            db.query(Interview)
            .filter(
                Interview.id == interview_id
            )
            .first()
        )

        if not interview:
            return

        interview.status = "completed"

        try:

            interview.completed_at = (
                datetime.now(
                    timezone.utc
                )
            )

        except Exception:
            pass

        db.commit()

        print(
            f"[DB] Interview #{interview_id} "
            "completed."
        )

    except Exception as e:

        db.rollback()

        print(
            f"[DB] Completion error: {e}"
        )

    finally:

        db.close()


def mark_interrupted(
    interview_id,
):
    db = SessionLocal()

    try:

        interview = (
            db.query(Interview)
            .filter(
                Interview.id == interview_id
            )
            .first()
        )

        if not interview:
            return

        if interview.status == "completed":
            return

        interview.status = "interrupted"

        db.commit()

        print(
            f"[DB] Interview #{interview_id} "
            "interrupted."
        )

    except Exception as e:

        db.rollback()

        print(
            f"[DB] Interrupted status error: {e}"
        )

    finally:

        db.close()


# ============================================================
# AUDIO INTERFACE
# ============================================================

class VBCableAudioInterface(AudioInterface):

    """
    Two-way audio bridge using the standard VB-Audio Cable.
    """

    def __init__(self):

        super().__init__()

        self.p = pyaudio.PyAudio()

        self.input_stream = None
        self.output_stream = None

        self.input_thread = None

        self.running = False
        self.accept_output = False

        self.output_lock = threading.Lock()

        self.input_device_index = None
        self.output_device_index = None

        self.input_rate = INPUT_RATE
        self.input_channels = INPUT_CHANNELS

        self.output_rate = OUTPUT_RATE
        self.output_channels = OUTPUT_CHANNELS

        self.last_input_log = 0
        self.last_output_log = 0

        # ----------------------------------------------------
        # FIND CANDIDATE INPUT
        # ----------------------------------------------------

        self.input_candidates = find_all_devices(
            self.p,
            CABLE_INPUT_CANDIDATES,
            input_device=True,
        )

        if not self.input_candidates:

            self.print_devices()

            raise RuntimeError(
                "Could not find any device matching "
                f"{CABLE_INPUT_CANDIDATES}. Is VB-Audio "
                "Virtual Cable installed, and is Google Meet's "
                "SPEAKER set to 'CABLE Input'? Check the device "
                "list printed above for the exact name Windows "
                "is reporting."
            )

        # ----------------------------------------------------
        # FIND ALENA OUTPUT
        # ----------------------------------------------------

        self.output_candidates = find_all_devices(
            self.p,
            CABLE_OUTPUT_CANDIDATES,
            output_device=True,
        )

        if not self.output_candidates:

            self.print_devices()

            raise RuntimeError(
                "Could not find any device matching "
                f"{CABLE_OUTPUT_CANDIDATES}. Is VB-Audio Virtual "
                "Cable installed, and is Google Meet's MICROPHONE "
                "set to 'CABLE Output'? Check the device "
                "list printed above for the exact name Windows "
                "is reporting."
            )

        print()
        print("=" * 70)
        print("AUDIO ROUTING")
        print("=" * 70)

        print(
            "Candidate input candidates (tried in this order):"
        )

        for index, info, host_api_name in self.input_candidates:

            print(
                f"  {index} - {info.get('name')} "
                f"[{host_api_name or 'unknown backend'}]"
            )

        print(
            "Alena output candidates (tried in this order):"
        )

        for index, info, host_api_name in self.output_candidates:

            print(
                f"  {index} - {info.get('name')} "
                f"[{host_api_name or 'unknown backend'}]"
            )

        print("=" * 70)

    # ========================================================
    # PRINT DEVICES
    # ========================================================

    def print_devices(self):

        print()
        print("=" * 90)
        print("AVAILABLE AUDIO DEVICES")
        print("=" * 90)

        for index in range(
            self.p.get_device_count()
        ):

            try:

                info = (
                    self.p.get_device_info_by_index(
                        index
                    )
                )

                print(
                    f"{index:3d} | "
                    f"{info.get('name')} | "
                    f"in={info.get('maxInputChannels')} | "
                    f"out={info.get('maxOutputChannels')} | "
                    f"rate={info.get('defaultSampleRate')}"
                )

            except Exception:
                pass

        print("=" * 90)

    # ========================================================
    # OPEN INPUT
    # ========================================================

    def open_input(self):

        for device_index, info, host_api_name in self.input_candidates:

            max_channels = int(
                info.get(
                    "maxInputChannels",
                    0,
                )
            )

            channels_to_try = []

            if max_channels >= 2:
                channels_to_try.append(2)

            if max_channels >= 1:
                channels_to_try.append(1)

            rates_to_try = []

            default_rate = int(
                round(
                    float(
                        info.get(
                            "defaultSampleRate",
                            INPUT_RATE,
                        )
                    )
                )
            )

            rates_to_try.append(
                default_rate
            )

            if INPUT_RATE not in rates_to_try:
                rates_to_try.append(
                    INPUT_RATE
                )

            for rate in rates_to_try:

                for channels in channels_to_try:

                    try:

                        stream = self.p.open(
                            format=pyaudio.paInt16,
                            channels=channels,
                            rate=rate,
                            input=True,
                            input_device_index=(
                                device_index
                            ),
                            frames_per_buffer=(
                                INPUT_CHUNK
                            ),
                            start=True,
                        )

                        self.input_stream = stream
                        self.input_device_index = device_index
                        self.input_rate = rate
                        self.input_channels = channels

                        print(
                            "[AUDIO INPUT] Ready: "
                            f"device {device_index} "
                            f"[{host_api_name or 'unknown backend'}] "
                            f"{rate} Hz / "
                            f"{channels} channels"
                        )

                        return

                    except Exception as e:

                        print(
                            "[AUDIO INPUT] "
                            f"Failed device {device_index} "
                            f"[{host_api_name or 'unknown backend'}] "
                            f"{rate} Hz / "
                            f"{channels} ch: {e}"
                        )

        raise RuntimeError(
            "Could not open CABLE input on any matching device/backend. "
            "See the failures above -- if every attempt shows "
            "'Unanticipated host error', another application may be "
            "holding the device open, or it is locked in exclusive "
            "mode in Windows Sound settings."
        )

    # ========================================================
    # OPEN OUTPUT
    # ========================================================

    def open_output(self):

        any_output_channels = False

        for device_index, info, host_api_name in self.output_candidates:

            max_channels = int(
                info.get(
                    "maxOutputChannels",
                    0,
                )
            )

            if max_channels <= 0:
                continue

            any_output_channels = True

            default_rate = int(
                round(
                    float(
                        info.get(
                            "defaultSampleRate",
                            OUTPUT_RATE,
                        )
                    )
                )
            )

            channels_to_try = []

            if max_channels >= 2:
                channels_to_try.append(2)

            if max_channels >= 1:
                channels_to_try.append(1)

            rates_to_try = [
                default_rate,
                OUTPUT_RATE,
                48000,
            ]

            unique_rates = []

            for rate in rates_to_try:

                if (
                    rate > 0
                    and rate not in unique_rates
                ):

                    unique_rates.append(rate)

            for rate in unique_rates:

                for channels in channels_to_try:

                    try:

                        stream = self.p.open(
                            format=pyaudio.paInt16,
                            channels=channels,
                            rate=rate,
                            output=True,
                            output_device_index=(
                                device_index
                            ),
                            frames_per_buffer=(
                                OUTPUT_CHUNK
                            ),
                            start=True,
                        )

                        self.output_stream = stream
                        self.output_device_index = device_index
                        self.output_rate = rate
                        self.output_channels = channels

                        print(
                            "[AUDIO OUTPUT] Ready: "
                            f"CABLE Input | "
                            f"device {device_index} "
                            f"[{host_api_name or 'unknown backend'}] "
                            f"{rate} Hz / "
                            f"{channels} channels"
                        )

                        return True

                    except Exception as e:

                        print(
                            "[AUDIO OUTPUT] "
                            f"Failed device {device_index} "
                            f"[{host_api_name or 'unknown backend'}] "
                            f"{rate} Hz / "
                            f"{channels} ch: {e}"
                        )

        if not any_output_channels:

            raise RuntimeError(
                "CABLE Input has no output channels on any "
                "matching device."
            )

        print(
            "[AUDIO OUTPUT] All backend variants of CABLE Input "
            "failed to open. If every attempt above shows "
            "'Unanticipated host error', see the exclusive-mode "
            "checklist (Windows Sound settings > Playback > "
            "CABLE Input > Properties > Advanced) or close any "
            "other app that might be holding the device open, "
            "including a previous crashed run of this script."
        )

        return False

    # ========================================================
    # START
    # ========================================================

    def start(
        self,
        callback,
    ):

        if self.running:
            return

        print()
        print(
            "[AUDIO] Starting audio interface..."
        )

        self.running = True
        self.accept_output = True

        self.open_input()

        output_ready = self.open_output()

        if not output_ready:

            self.accept_output = False

            print()
            print(
                "[AUDIO OUTPUT] "
                "WARNING: Could not open CABLE Input."
            )

            print(
                "[AUDIO OUTPUT] "
                "Candidate input is still active."
            )

        self.input_thread = threading.Thread(
            target=self.input_loop,
            args=(callback,),
            daemon=True,
            name="CandidateAudioInput",
        )

        self.input_thread.start()

        print(
            "[AUDIO] Audio interface started."
        )

    # ========================================================
    # INPUT LOOP
    # ========================================================

    def input_loop(
        self,
        callback,
    ):

        print(
            "[AUDIO INPUT] Listening "
            "for candidate..."
        )

        while self.running:

            try:

                if not self.input_stream:
                    time.sleep(0.05)
                    continue

                data = self.input_stream.read(
                    INPUT_CHUNK,
                    exception_on_overflow=False,
                )

                if not data:
                    continue

                audio = np.frombuffer(
                    data,
                    dtype=np.int16,
                )

                if len(audio) == 0:
                    continue

                mono = stereo_to_mono(
                    audio,
                    self.input_channels,
                )

                if len(mono) == 0:
                    continue

                peak = int(
                    np.max(
                        np.abs(
                            mono.astype(
                                np.int32
                            )
                        )
                    )
                )

                now = time.monotonic()

                if (
                    peak >= MIN_AUDIO_LEVEL
                    and
                    now - self.last_input_log
                    >= 2
                ):

                    print(
                        "[AUDIO INPUT] "
                        f"Candidate detected "
                        f"peak={peak}"
                    )

                    self.last_input_log = now

                # Convert to 16 kHz mono.

                audio_16k = resample_audio(
                    mono.astype(
                        np.float32
                    ),
                    self.input_rate,
                    ELEVENLABS_RATE,
                )

                if len(audio_16k) == 0:
                    continue

                # Send candidate audio to ElevenLabs.

                if callback:

                    callback(
                        audio_16k.tobytes()
                    )

            except Exception as e:

                if self.running:

                    print(
                        "[AUDIO INPUT] "
                        f"Error: {e}"
                    )

                    time.sleep(0.1)

        print(
            "[AUDIO INPUT] Stopped."
        )

    # ========================================================
    # OUTPUT
    # ========================================================

    def output(
        self,
        audio,
    ):

        if not self.accept_output:
            return

        if not audio:
            return

        with self.output_lock:

            if not self.output_stream:
                return

            try:

                pcm = np.frombuffer(
                    audio,
                    dtype=np.int16,
                )

                if len(pcm) == 0:
                    return

                peak = int(
                    np.max(
                        np.abs(
                            pcm.astype(
                                np.int32
                            )
                        )
                    )
                )

                now = time.monotonic()

                if (
                    peak >= MIN_AUDIO_LEVEL
                    and
                    now - self.last_output_log
                    >= 2
                ):

                    print(
                        "[AUDIO OUTPUT] "
                        "Alena audio -> CABLE Input "
                        f"peak={peak}"
                    )

                    self.last_output_log = now

                # ElevenLabs gives 16 kHz mono.
                # Convert to the actual CABLE Input format.

                converted = resample_audio(
                    pcm.astype(
                        np.float32
                    ),
                    ELEVENLABS_RATE,
                    self.output_rate,
                )

                if len(converted) == 0:
                    return

                if self.output_channels == 2:

                    converted = mono_to_stereo(
                        converted
                    )

                self.output_stream.write(
                    converted.tobytes(),
                    exception_on_underflow=False,
                )

            except Exception as e:

                print(
                    "[AUDIO OUTPUT] "
                    f"Write error: {e}"
                )

    # ========================================================
    # INTERRUPT
    # ========================================================

    def interrupt(self):

        # Do NOT destroy the stream.
        # ElevenLabs can continue using the same stream.

        return

    # ========================================================
    # STOP
    # ========================================================

    def stop(self):

        print(
            "[AUDIO] Stopping audio..."
        )

        self.accept_output = False
        self.running = False

        # INPUT

        if self.input_stream:

            try:

                self.input_stream.stop_stream()
            except Exception:
                pass

            try:

                self.input_stream.close()
            except Exception:
                pass

            self.input_stream = None

        # INPUT THREAD

        if self.input_thread:

            try:

                if self.input_thread.is_alive():

                    self.input_thread.join(
                        timeout=2
                    )

            except Exception:
                pass

            self.input_thread = None

        # OUTPUT

        with self.output_lock:

            if self.output_stream:

                try:

                    self.output_stream.stop_stream()
                except Exception:
                    pass

                try:

                    self.output_stream.close()
                except Exception:
                    pass

                self.output_stream = None

        # PYAUDIO

        try:

            self.p.terminate()

        except Exception:
            pass

        print(
            "[AUDIO] Audio stopped."
        )


# ============================================================
# RUN ALENA
# ============================================================

def run_alena(
    interview_id=None,
    max_duration_seconds=MAX_INTERVIEW_SECONDS,
    external_message_queue=None,
):
    """
    Start one complete Alena interview.

    external_message_queue is intentionally ignored.
    Candidate communication happens through real audio.
    """

    if not API_KEY:

        raise RuntimeError(
            "ELEVENLABS_API_KEY is not configured."
        )

    if not AGENT_ID:

        raise RuntimeError(
            "ELEVENLABS_AGENT_ID is not configured."
        )

    if interview_id is None:

        raise RuntimeError(
            "interview_id is required."
        )

    print()
    print("=" * 80)
    print("SALESINTERVIEWAI - ALENA INTERVIEW")
    print("=" * 80)

    print(
        f"[ALENA] Interview: #{interview_id}"
    )

    # ========================================================
    # LOAD QUESTIONS
    # ========================================================

    (
        position,
        questions,
    ) = load_interview_data(
        interview_id
    )

    print(
        f"[ALENA] Position: {position}"
    )

    print(
        f"[ALENA] Questions: {len(questions)}"
    )

    questions_text = "\n".join(
        questions
    )

    # ========================================================
    # TRANSCRIPT
    # ========================================================

    transcript_path = get_transcript_path(
        interview_id
    )

    set_transcript_path(
        interview_id,
        transcript_path,
    )

    transcript_lines = []

    transcript_lock = threading.Lock()

    # ========================================================
    # CALLBACKS
    # ========================================================

    def add_transcript(
        speaker,
        text,
    ):

        if not text:
            return

        text = str(text).strip()

        if not text:
            return

        line = (
            f"{speaker}: {text}"
        )

        with transcript_lock:

            transcript_lines.append(
                line
            )

            save_transcript(
                transcript_path,
                transcript_lines,
            )

    def on_agent_response(
        text,
    ):

        if not text:
            return

        print()
        print(
            "[ALENA]"
        )
        print(text)

        add_transcript(
            "Alena",
            text,
        )

    def on_user_transcript(
        text,
    ):

        if not text:
            return

        print()
        print(
            "[CANDIDATE]"
        )
        print(text)

        add_transcript(
            "Candidate",
            text,
        )

    # ========================================================
    # AUDIO
    # ========================================================

    audio_interface = (
        VBCableAudioInterface()
    )

    # ========================================================
    # ELEVENLABS
    # ========================================================

    client = ElevenLabs(
        api_key=API_KEY
    )

    dynamic_variables = {
        "position": position,
        "interview_position": position,
        "interview_questions": questions_text,
    }

    print()
    print(
        "[ALENA] Starting interview..."
    )

    # ========================================================
    # CONVERSATION CONFIG
    # ========================================================

    initiation_data = (
        ConversationInitiationData(
            dynamic_variables=dynamic_variables
        )
    )

    conversation = Conversation(
        client=client,
        agent_id=AGENT_ID,
        requires_auth=True,
        audio_interface=audio_interface,
        callback_agent_response=(
            on_agent_response
        ),
        callback_user_transcript=(
            on_user_transcript
        ),
        config=initiation_data,
    )

    # ========================================================
    # SESSION
    # ========================================================

    session_started = False
    completed = False

    start_time = time.monotonic()

    try:

        print()
        print("=" * 80)
        print(
            "[ALENA] STARTING SESSION"
        )
        print("=" * 80)

        conversation.start_session()

        session_started = True

        print()
        print("=" * 80)
        print(
            "[ALENA] ✓ SESSION STARTED"
        )
        print(
            "[ALENA] ✓ Candidate audio -> Alena"
        )
        print(
            "[ALENA] ✓ Alena audio -> Meet"
        )
        print(
            "[ALENA] ✓ Interview conversation active"
        )
        print("=" * 80)

        # WAIT

        while True:

            elapsed = (
                time.monotonic()
                - start_time
            )

            if (
                elapsed
                >= max_duration_seconds
            ):

                print()
                print(
                    "[ALENA] Maximum interview "
                    "duration reached."
                )

                completed = True
                break

            time.sleep(0.2)

    except KeyboardInterrupt:

        print(
            "[ALENA] Stopped manually."
        )

        completed = False

    except Exception as e:

        print()
        print(
            "[ALENA] ERROR:"
        )
        print(
            f"{type(e).__name__}: {e}"
        )

        completed = False

    finally:

        # END ELEVENLABS

        if session_started:

            try:

                print(
                    "[ALENA] Ending session..."
                )

                conversation.end_session()

            except Exception as e:

                print(
                    "[ALENA] "
                    f"End session error: {e}"
                )

        # SAVE TRANSCRIPT

        save_transcript(
            transcript_path,
            transcript_lines,
        )

        # DATABASE

        if completed:

            mark_completed(
                interview_id
            )

        else:

            mark_interrupted(
                interview_id
            )

        # AUDIO

        try:

            audio_interface.stop()

        except Exception as e:

            print(
                "[AUDIO] "
                f"Stop error: {e}"
            )

        print()
        print("=" * 80)
        print(
            "[ALENA] INTERVIEW FINISHED"
        )
        print(
            f"[ALENA] Transcript: "
            f"{transcript_path}"
        )
        print("=" * 80)

    return {
        "interview_id": interview_id,
        "transcript_path": transcript_path,
        "completed": completed,
        "transcript_lines": transcript_lines,
    }


# ============================================================
# DIRECT EXECUTION
# ============================================================

if __name__ == "__main__":

    print()
    print("=" * 80)
    print("SalesInterviewAI - ALENA")
    print("=" * 80)
    print()
    print(
        "This module is started by "
        "the SalesInterviewAI scheduler."
    )
    print()