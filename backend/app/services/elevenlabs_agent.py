
import os
import threading
import time
from datetime import datetime

import numpy as np
import pyaudio
from dotenv import load_dotenv
from scipy.signal import resample_poly

from elevenlabs.client import ElevenLabs
from elevenlabs.conversational_ai.conversation import (
    Conversation,
    AudioInterface,
)

load_dotenv()


# ============================================================
# ELEVENLABS
# ============================================================

AGENT_ID = os.getenv("ELEVENLABS_AGENT_ID")
API_KEY = os.getenv("ELEVENLABS_API_KEY")


# ============================================================
# AUDIO DEVICE NAMES
#
# IMPORTANT:
# We use names instead of fixed Windows indexes because
# Windows can change PyAudio indexes.
# ============================================================

CABLE_OUTPUT_NAME = "CABLE Output (VB-Audio Virtual Cable)"

VOICEMEETER_INPUT_NAME = (
    "Voicemeeter Input (VB-Audio Voicemeeter VAIO)"
)


# ============================================================
# AUDIO SETTINGS
# ============================================================

# Candidate audio from CABLE Output
INPUT_SAMPLE_RATE = 44100
INPUT_CHANNELS = 2
INPUT_CHUNK_SIZE = 2048

# ElevenLabs realtime input
ELEVENLABS_SAMPLE_RATE = 16000

# Alena audio going into Voicemeeter
OUTPUT_SAMPLE_RATE = 48000
OUTPUT_CHANNELS = 2
OUTPUT_CHUNK_SIZE = 1024


# ============================================================
# INTERVIEW LIMIT
# ============================================================

MAX_INTERVIEW_SECONDS = 30 * 60


# ============================================================
# CANDIDATE SESSION END DETECTION
# ============================================================

SESSION_END_PHRASES = [
    "i want to end the interview",
    "i want to end this interview",
    "i'd like to end the interview",
    "i would like to end the interview",
    "i want to end the interview now",
    "i'd like to end the interview now",
    "i would like to end the interview now",

    "end the interview",
    "please end the interview",
    "can we end the interview",
    "can we end this interview",

    "let's end the interview",
    "lets end the interview",

    "stop the interview",
    "please stop the interview",
    "let's stop the interview",
    "lets stop the interview",

    "i'm done with the interview",
    "i am done with the interview",

    "that's all from me",
    "thats all from me",

    "can we finish the interview",
    "i want to finish the interview",
    "i'd like to finish the interview",
    "i would like to finish the interview",

    "please finish the interview",
]


SESSION_END_DELAY_SECONDS = 7


# ============================================================
# AUDIO DETECTION
# ============================================================

AUDIO_DETECTION_RMS = 100
AUDIO_DETECTION_PEAK = 300

# We don't immediately start ElevenLabs.
# First we verify that candidate audio exists.
AUDIO_WAIT_TIMEOUT = 60


# ============================================================
# DIRECTORIES
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)

TRANSCRIPT_DIR = os.path.join(
    BASE_DIR,
    "data",
    "transcripts"
)

os.makedirs(
    TRANSCRIPT_DIR,
    exist_ok=True
)


# ============================================================
# CHECK IF CANDIDATE WANTS TO END SESSION
# ============================================================

def candidate_requested_session_end(text):

    if not text:
        return False

    normalized = (
        " ".join(
            str(text)
            .lower()
            .strip()
            .split()
        )
    )

    for phrase in SESSION_END_PHRASES:

        if phrase in normalized:
            return True

    return False


# ============================================================
# FIND AUDIO DEVICE
# ============================================================

def find_audio_device(
    audio,
    device_name,
    input_device=True
):
    """
    Find an audio device by name.

    We do NOT rely on fixed indexes such as 24 or 50.
    """

    print()
    print("=" * 70)
    print("[AUDIO] SEARCHING DEVICE")
    print("=" * 70)

    print(
        f"[AUDIO] Looking for: {device_name}"
    )

    matches = []

    for index in range(
        audio.get_device_count()
    ):

        try:

            info = audio.get_device_info_by_index(
                index
            )

            name = info.get(
                "name",
                ""
            )

            max_input = int(
                info.get(
                    "maxInputChannels",
                    0
                )
            )

            max_output = int(
                info.get(
                    "maxOutputChannels",
                    0
                )
            )

            sample_rate = float(
                info.get(
                    "defaultSampleRate",
                    44100
                )
            )

            if device_name.lower() in name.lower():

                matches.append(
                    {
                        "index": index,
                        "name": name,
                        "inputs": max_input,
                        "outputs": max_output,
                        "sample_rate": sample_rate,
                    }
                )

        except Exception:
            continue


    if not matches:

        print(
            "[AUDIO ERROR] Device not found:"
        )

        print(
            f"              {device_name}"
        )

        print("=" * 70)

        raise RuntimeError(
            f"Audio device not found: "
            f"{device_name}"
        )


    # --------------------------------------------------------
    # Filter according to required direction
    # --------------------------------------------------------

    if input_device:

        candidates = [
            item
            for item in matches
            if item["inputs"] > 0
        ]

    else:

        candidates = [
            item
            for item in matches
            if item["outputs"] > 0
        ]


    if not candidates:

        direction = (
            "input"
            if input_device
            else "output"
        )

        raise RuntimeError(
            f"Device '{device_name}' was found, "
            f"but it has no usable {direction} channels."
        )


    # --------------------------------------------------------
    # Prefer 2-channel device
    # --------------------------------------------------------

    candidates.sort(
        key=lambda item: (
            0
            if (
                item["inputs"] == 2
                if input_device
                else item["outputs"] == 2
            )
            else 1,
            item["index"]
        )
    )


    selected = candidates[0]


    print(
        "[AUDIO] Device selected:"
    )

    print(
        f"        Index        : "
        f"{selected['index']}"
    )

    print(
        f"        Name         : "
        f"{selected['name']}"
    )

    print(
        f"        Input chans  : "
        f"{selected['inputs']}"
    )

    print(
        f"        Output chans : "
        f"{selected['outputs']}"
    )

    print(
        f"        Sample rate  : "
        f"{selected['sample_rate']}"
    )

    print("=" * 70)


    return selected


# ============================================================
# LIST RELEVANT DEVICES
# ============================================================

def print_audio_devices(audio):

    print()
    print("=" * 70)
    print("AVAILABLE RELEVANT AUDIO DEVICES")
    print("=" * 70)

    for index in range(
        audio.get_device_count()
    ):

        try:

            info = audio.get_device_info_by_index(
                index
            )

            name = info.get(
                "name",
                ""
            )

            if (
                "CABLE" in name.upper()
                or "VOICEMEETER" in name.upper()
            ):

                print(
                    f"[{index}] "
                    f"{name}"
                )

                print(
                    f"     INPUTS="
                    f"{info.get('maxInputChannels', 0)} "
                    f"OUTPUTS="
                    f"{info.get('maxOutputChannels', 0)} "
                    f"RATE="
                    f"{info.get('defaultSampleRate', 0)}"
                )

        except Exception:
            continue

    print("=" * 70)


# ============================================================
# CANDIDATE AUDIO CONVERSION
#
# 44.1kHz stereo
#        ↓
# stereo -> mono
#        ↓
# 44.1kHz mono
#        ↓
# 16kHz mono
#        ↓
# ElevenLabs
# ============================================================

def stereo_to_mono_16000(
    data,
    input_sample_rate
):

    if not data:
        return b""


    samples = np.frombuffer(
        data,
        dtype=np.int16
    )


    if len(samples) == 0:
        return b""


    usable_length = (
        len(samples)
        -
        (
            len(samples)
            %
            INPUT_CHANNELS
        )
    )


    if usable_length <= 0:
        return b""


    samples = samples[
        :usable_length
    ]


    stereo = samples.reshape(
        -1,
        INPUT_CHANNELS
    )


    mono = np.mean(
        stereo.astype(
            np.float32
        ),
        axis=1
    )


    # --------------------------------------------------------
    # Resample to ElevenLabs input rate
    # --------------------------------------------------------

    if input_sample_rate != ELEVENLABS_SAMPLE_RATE:

        # Use integer ratio where possible.
        # 44100 -> 16000 = 160 / 441

        if (
            input_sample_rate == 44100
        ):

            converted = resample_poly(
                mono,
                160,
                441
            )

        else:

            # Generic resampling
            from scipy.signal import resample

            output_length = int(
                len(mono)
                *
                ELEVENLABS_SAMPLE_RATE
                /
                input_sample_rate
            )

            converted = resample(
                mono,
                output_length
            )

    else:

        converted = mono


    converted = np.clip(
        converted,
        -32768,
        32767
    )


    return converted.astype(
        np.int16
    ).tobytes()


# ============================================================
# ALENA OUTPUT CONVERSION
#
# 16kHz mono
#        ↓
# 48kHz mono
#        ↓
# stereo
#        ↓
# Voicemeeter Input
# ============================================================

def resample_16000_to_48000(
    data
):

    if not data:
        return b""


    samples = np.frombuffer(
        data,
        dtype=np.int16
    )


    if len(samples) == 0:
        return b""


    converted = resample_poly(
        samples.astype(
            np.float32
        ),
        3,
        1
    )


    converted = np.clip(
        converted,
        -32768,
        32767
    )


    return converted.astype(
        np.int16
    ).tobytes()


# ============================================================
# AUDIO INTERFACE
# ============================================================

class VBCableAudioInterface(
    AudioInterface
):

    def __init__(self):

        self.audio = pyaudio.PyAudio()

        self.input_stream = None
        self.output_stream = None

        self.input_device = None
        self.output_device = None

        self.running = False

        self.lock = threading.Lock()

        self.input_thread = None

        self.candidate_audio_detected = (
            threading.Event()
        )

        self.last_rms = 0
        self.last_peak = 0


    # ========================================================
    # START
    # ========================================================

    def start(
        self,
        input_callback
    ):

        print()
        print("=" * 70)
        print("[AUDIO] STARTING AUDIO INTERFACE")
        print("=" * 70)


        self.running = True


        # ----------------------------------------------------
        # Show relevant devices
        # ----------------------------------------------------

        print_audio_devices(
            self.audio
        )


        # ----------------------------------------------------
        # Find CABLE Output
        # ----------------------------------------------------

        self.input_device = (
            find_audio_device(
                self.audio,
                CABLE_OUTPUT_NAME,
                input_device=True
            )
        )


        # ----------------------------------------------------
        # Find Voicemeeter Input
        # ----------------------------------------------------

        self.output_device = (
            find_audio_device(
                self.audio,
                VOICEMEETER_INPUT_NAME,
                input_device=False
            )
        )


        input_index = (
            self.input_device["index"]
        )

        output_index = (
            self.output_device["index"]
        )


        input_rate = (
            self.input_device["sample_rate"]
        )


        # ----------------------------------------------------
        # We prefer 44100 because your CABLE Output endpoint
        # has been identified at 44100.
        #
        # If Windows reports something else, use that rate.
        # ----------------------------------------------------

        if input_rate <= 0:

            input_rate = INPUT_SAMPLE_RATE


        print()
        print(
            "[AUDIO] FINAL ROUTING"
        )

        print(
            f"        Candidate input : "
            f"CABLE Output"
        )

        print(
            f"        Input index     : "
            f"{input_index}"
        )

        print(
            f"        Input rate      : "
            f"{input_rate}"
        )

        print(
            f"        Alena output    : "
            f"Voicemeeter Input"
        )

        print(
            f"        Output index    : "
            f"{output_index}"
        )

        print(
            f"        Output rate     : "
            f"{OUTPUT_SAMPLE_RATE}"
        )


        # ====================================================
        # OPEN CANDIDATE INPUT
        # ====================================================

        print()
        print(
            "[AUDIO] Opening CABLE Output..."
        )


        try:

            self.input_stream = (
                self.audio.open(
                    format=pyaudio.paInt16,

                    channels=INPUT_CHANNELS,

                    rate=int(input_rate),

                    input=True,

                    input_device_index=input_index,

                    frames_per_buffer=(
                        INPUT_CHUNK_SIZE
                    ),
                )
            )

        except Exception as error:

            self.running = False

            print(
                "[AUDIO ERROR] Could not open "
                "CABLE Output:"
            )

            print(error)

            raise


        print(
            "[AUDIO] CABLE Output opened."
        )


        # ====================================================
        # OPEN ALENA OUTPUT
        # ====================================================

        print()
        print(
            "[AUDIO] Opening Voicemeeter Input..."
        )


        try:

            self.output_stream = (
                self.audio.open(
                    format=pyaudio.paInt16,

                    channels=OUTPUT_CHANNELS,

                    rate=OUTPUT_SAMPLE_RATE,

                    output=True,

                    output_device_index=output_index,

                    frames_per_buffer=(
                        OUTPUT_CHUNK_SIZE
                    ),
                )
            )

        except Exception as error:

            self.running = False

            if self.input_stream:

                try:
                    self.input_stream.close()
                except Exception:
                    pass

            print(
                "[AUDIO ERROR] Could not open "
                "Voicemeeter Input:"
            )

            print(error)

            raise


        print(
            "[AUDIO] Voicemeeter Input opened."
        )


        # ====================================================
        # CANDIDATE INPUT THREAD
        # ====================================================

        def read_audio():

            print()
            print(
                "=" * 70
            )

            print(
                "[AUDIO] LISTENING FOR CANDIDATE"
            )

            print(
                "[AUDIO] Speak into the Google Meet microphone."
            )

            print(
                "[AUDIO] Waiting for signal..."
            )

            print(
                "=" * 70
            )


            while self.running:

                try:

                    data = (
                        self.input_stream.read(
                            INPUT_CHUNK_SIZE,
                            exception_on_overflow=False
                        )
                    )


                    if not data:

                        continue


                    # ------------------------------------------------
                    # Calculate signal level
                    # ------------------------------------------------

                    samples = np.frombuffer(
                        data,
                        dtype=np.int16
                    )


                    if len(samples) > 0:

                        rms = float(
                            np.sqrt(
                                np.mean(
                                    samples.astype(
                                        np.float32
                                    ) ** 2
                                )
                            )
                        )


                        peak = int(
                            np.max(
                                np.abs(
                                    samples
                                )
                            )
                        )


                        self.last_rms = rms
                        self.last_peak = peak


                        # ------------------------------------------------
                        # Detect actual signal
                        # ------------------------------------------------

                        if (
                            rms >= AUDIO_DETECTION_RMS
                            or
                            peak >= AUDIO_DETECTION_PEAK
                        ):

                            if not self.candidate_audio_detected.is_set():

                                print()
                                print(
                                    "=" * 70
                                )

                                print(
                                    "[AUDIO] ✓ CANDIDATE AUDIO DETECTED"
                                )

                                print(
                                    f"[AUDIO] RMS  : {rms:.0f}"
                                )

                                print(
                                    f"[AUDIO] PEAK : {peak}"
                                )

                                print(
                                    "=" * 70
                                )


                            self.candidate_audio_detected.set()


                    # ------------------------------------------------
                    # Convert audio
                    # ------------------------------------------------

                    converted_audio = (
                        stereo_to_mono_16000(
                            data,
                            input_rate
                        )
                    )


                    if (
                        self.running
                        and converted_audio
                    ):

                        input_callback(
                            converted_audio
                        )


                except Exception as error:

                    if self.running:

                        print(
                            "[AUDIO INPUT ERROR]"
                        )

                        print(error)

                    break


        self.input_thread = threading.Thread(
            target=read_audio,
            daemon=True
        )


        self.input_thread.start()


        print()
        print(
            "[AUDIO] Candidate input thread started."
        )

        print(
            "[AUDIO] Alena output ready."
        )

        print("=" * 70)


    # ========================================================
    # WAIT FOR CANDIDATE AUDIO
    # ========================================================

    def wait_for_candidate_audio(
        self,
        timeout=AUDIO_WAIT_TIMEOUT
    ):

        print()
        print("=" * 70)

        print(
            "[AUDIO CHECK] Waiting for candidate audio..."
        )

        print(
            f"[AUDIO CHECK] Timeout: {timeout} seconds"
        )

        print("=" * 70)


        detected = (
            self.candidate_audio_detected.wait(
                timeout
            )
        )


        if detected:

            print()
            print(
                "[AUDIO CHECK] ✓ Candidate audio confirmed."
            )

            return True


        print()
        print(
            "[AUDIO CHECK] ✗ No candidate audio detected."
        )

        print(
            "[AUDIO CHECK] RMS:",
            self.last_rms
        )

        print(
            "[AUDIO CHECK] PEAK:",
            self.last_peak
        )

        return False


    # ========================================================
    # STOP
    # ========================================================

    def stop(self):

        print()
        print(
            "[AUDIO] Stopping audio interface..."
        )


        self.running = False


        try:

            if self.input_stream:

                self.input_stream.stop_stream()
                self.input_stream.close()

        except Exception:
            pass


        try:

            if self.output_stream:

                self.output_stream.stop_stream()
                self.output_stream.close()

        except Exception:
            pass


        try:

            if self.input_thread:

                self.input_thread.join(
                    timeout=1
                )

        except Exception:
            pass


        try:

            self.audio.terminate()

        except Exception:
            pass


        print(
            "[AUDIO] Audio interface stopped."
        )


    # ========================================================
    # ALENA OUTPUT
    # ========================================================

    def output(
        self,
        audio: bytes
    ):

        if not self.running:
            return


        if not audio:
            return


        try:

            with self.lock:

                if not self.output_stream:
                    return


                mono_48k = (
                    resample_16000_to_48000(
                        audio
                    )
                )


                if not mono_48k:
                    return


                samples = np.frombuffer(
                    mono_48k,
                    dtype=np.int16
                )


                stereo = np.column_stack(
                    (
                        samples,
                        samples
                    )
                ).astype(
                    np.int16
                )


                self.output_stream.write(
                    stereo.tobytes()
                )


        except Exception as error:

            print(
                "[AUDIO OUTPUT ERROR]",
                error
            )


    # ========================================================
    # INTERRUPT
    # ========================================================

    def interrupt(self):

        print(
            "[AUDIO] Interrupt requested."
        )


# ============================================================
# SAVE TRANSCRIPT
# ============================================================

def save_transcript(
    interview_id,
    transcript_entries
):

    if not transcript_entries:

        print(
            "[TRANSCRIPT] No transcript entries found."
        )

        return None


    if interview_id:

        filename = (
            f"interview_{interview_id}.txt"
        )

    else:

        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        filename = (
            f"interview_{timestamp}.txt"
        )


    transcript_path = os.path.join(
        TRANSCRIPT_DIR,
        filename
    )


    with open(
        transcript_path,
        "w",
        encoding="utf-8"
    ) as file:

        file.write(
            "SalesInterviewAI - "
            "Alena Interview Transcript\n"
        )

        file.write(
            "=" * 70
            + "\n\n"
        )


        for entry in transcript_entries:

            speaker = entry.get(
                "speaker",
                "UNKNOWN"
            )

            text = entry.get(
                "text",
                ""
            )

            timestamp = entry.get(
                "timestamp",
                ""
            )


            file.write(
                f"[{timestamp}] "
                f"{speaker}: {text}\n\n"
            )


    print(
        f"[TRANSCRIPT] Saved: "
        f"{transcript_path}"
    )


    return transcript_path


# ============================================================
# RUN ALENA
# ============================================================

def run_alena(
    interview_id=None,
    max_duration_seconds=MAX_INTERVIEW_SECONDS
):

    if not AGENT_ID:

        raise RuntimeError(
            "ELEVENLABS_AGENT_ID is missing from .env"
        )


    if not API_KEY:

        raise RuntimeError(
            "ELEVENLABS_API_KEY is missing from .env"
        )


    print()
    print("=" * 70)
    print("SalesInterviewAI - ALENA")
    print("=" * 70)


    print(
        f"Interview ID: {interview_id}"
    )


    print(
        f"Agent ID: {AGENT_ID}"
    )


    print(
        "Candidate input: CABLE Output"
    )


    print(
        "Alena output: Voicemeeter Input"
    )


    print(
        f"Maximum duration: "
        f"{max_duration_seconds} seconds"
    )


    print("=" * 70)


    # ========================================================
    # ELEVENLABS CLIENT
    # ========================================================

    elevenlabs = ElevenLabs(
        api_key=API_KEY
    )


    # ========================================================
    # AUDIO INTERFACE
    # ========================================================

    audio_interface = (
        VBCableAudioInterface()
    )


    transcript_entries = []

    transcript_lock = threading.Lock()


    # ========================================================
    # SESSION END CONTROL
    # ========================================================

    session_end_requested = threading.Event()

    session_end_timer = None


    # ========================================================
    # TRANSCRIPT HANDLERS
    # ========================================================

    def add_transcript(
        speaker,
        text
    ):

        if not text:
            return


        entry = {

            "speaker": speaker,

            "text": str(text),

            "timestamp": (
                datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            ),

        }


        with transcript_lock:

            transcript_entries.append(
                entry
            )


    def on_agent_response(
        response
    ):

        print(
            f"\nALENA: {response}"
        )


        add_transcript(
            "ALENA",
            response
        )


    def on_user_transcript(
        transcript
    ):

        nonlocal session_end_timer


        print(
            f"\nCANDIDATE: {transcript}"
        )


        add_transcript(
            "CANDIDATE",
            transcript
        )


        # ====================================================
        # CHECK FOR SESSION END REQUEST
        # ====================================================

        if candidate_requested_session_end(
            transcript
        ):

            # Prevent duplicate timers
            if session_end_requested.is_set():

                return


            session_end_requested.set()


            print()
            print("=" * 70)

            print(
                "[SESSION] CANDIDATE REQUESTED "
                "TO END INTERVIEW"
            )

            print("=" * 70)


            print(
                f"[SESSION] Candidate said: "
                f"{transcript}"
            )


            print(
                "[SESSION] Alena will give "
                "her closing response."
            )


            print(
                f"[SESSION] Session will end in "
                f"{SESSION_END_DELAY_SECONDS} seconds."
            )


            print("=" * 70)


            # ------------------------------------------------
            # Give Alena time to say goodbye
            # ------------------------------------------------

            def end_session_after_goodbye():

                try:

                    print()
                    print(
                        "[SESSION] Ending "
                        "ElevenLabs session..."
                    )


                    conversation.end_session()


                    print(
                        "[SESSION] ✓ ElevenLabs "
                        "session ended."
                    )


                except Exception as error:

                    print(
                        "[SESSION END ERROR]",
                        error
                    )


            session_end_timer = threading.Timer(
                SESSION_END_DELAY_SECONDS,
                end_session_after_goodbye
            )


            session_end_timer.daemon = True


            session_end_timer.start()


    def on_agent_correction(
        original,
        corrected
    ):

        print(
            f"\nALENA CORRECTION: "
            f"{original} -> {corrected}"
        )


    # ========================================================
    # ELEVENLABS CONVERSATION
    # ========================================================

    conversation = Conversation(

        client=elevenlabs,

        agent_id=AGENT_ID,

        requires_auth=True,

        audio_interface=audio_interface,

        callback_agent_response=(
            on_agent_response
        ),

        callback_user_transcript=(
            on_user_transcript
        ),

        callback_agent_response_correction=(
            on_agent_correction
        ),

    )


    stop_timer = None


    # ========================================================
    # START AUDIO
    #
    # NOTE:
    # The ElevenLabs session is NOT started yet.
    #
    # We first verify that candidate audio exists.
    # ========================================================

    try:

        print()
        print(
            "[ALENA] Starting local audio interface..."
        )


        # Conversation's audio interface needs to be started
        # by the ElevenLabs SDK when the session starts.
        #
        # We therefore cannot use the normal Conversation
        # start sequence as a zero-credit test.
        #
        # This function is intended to be called after
        # Meet routing has already been verified.


        print()
        print(
            "[ALENA] Starting ElevenLabs conversation..."
        )


        conversation.start_session()


        stop_timer = threading.Timer(
            max_duration_seconds,
            lambda: conversation.end_session()
        )


        stop_timer.daemon = True


        stop_timer.start()


        print()
        print(
            "[ALENA] Conversation is active."
        )


        conversation_id = (
            conversation.wait_for_session_end()
        )


        print()
        print(
            "[ALENA] Session ended:"
        )


        print(
            f"[ALENA] Conversation ID: "
            f"{conversation_id}"
        )


        transcript_path = save_transcript(
            interview_id=interview_id,
            transcript_entries=(
                transcript_entries
            )
        )


        return {

            "conversation_id":
                conversation_id,

            "transcript_path":
                transcript_path,

            "transcript_entries":
                transcript_entries,

        }


    finally:

        if stop_timer:

            try:
                stop_timer.cancel()
            except Exception:
                pass


        # ====================================================
        # CANCEL SESSION END TIMER
        # ====================================================

        if session_end_timer:

            try:
                session_end_timer.cancel()
            except Exception:
                pass


        try:

            audio_interface.stop()

        except Exception:
            pass


        print(
            "[ALENA] Audio interface closed."
        )


# ============================================================
# DIRECT RUN
# ============================================================

if __name__ == "__main__":

    run_alena()

