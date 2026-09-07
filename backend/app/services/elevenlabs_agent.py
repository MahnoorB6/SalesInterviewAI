
import os
import threading
from datetime import datetime
import array

import pyaudio
from dotenv import load_dotenv

from elevenlabs.client import ElevenLabs
from elevenlabs.conversational_ai.conversation import (
    Conversation,
    AudioInterface,
)

load_dotenv()

AGENT_ID = os.getenv("ELEVENLABS_AGENT_ID")
API_KEY = os.getenv("ELEVENLABS_API_KEY")


# ============================================================
# AUDIO DEVICES
# ============================================================

# CABLE Output = candidate audio coming from Google Meet
INPUT_DEVICE_INDEX = 24

# Voicemeeter Input = Alena audio going into Voicemeeter
OUTPUT_DEVICE_INDEX = 50


# ============================================================
# ELEVENLABS INPUT
# ============================================================

# VB-Cable native rate
INPUT_SAMPLE_RATE = 44100

# ElevenLabs realtime input
ELEVENLABS_SAMPLE_RATE = 16000

INPUT_CHANNELS = 1
INPUT_CHUNK_SIZE = 2048


# ============================================================
# ALENA OUTPUT
# ============================================================

OUTPUT_SAMPLE_RATE = 48000
OUTPUT_CHANNELS = 2
OUTPUT_CHUNK_SIZE = 1024


MAX_INTERVIEW_SECONDS = 30 * 60


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
# AUDIO RESAMPLER
# 44,100 Hz -> 16,000 Hz
# ============================================================

def resample_44100_to_16000(data: bytes) -> bytes:
    """
    Convert 44.1 kHz signed 16-bit mono PCM
    to clean 16 kHz mono PCM for ElevenLabs.
    """

    if not data:
        return b""

    samples = array.array("h")
    samples.frombytes(data)

    if len(samples) < 2:
        return b""

    input_length = len(samples)

    output_length = int(
        input_length
        * ELEVENLABS_SAMPLE_RATE
        / INPUT_SAMPLE_RATE
    )

    if output_length <= 0:
        return b""

    output = array.array("h")

    ratio = (
        INPUT_SAMPLE_RATE
        / ELEVENLABS_SAMPLE_RATE
    )

    # --------------------------------------------------------
    # RESAMPLE 44.1 kHz -> 16 kHz
    # --------------------------------------------------------

    for i in range(output_length):

        position = i * ratio

        index = int(position)

        fraction = position - index

        if index >= input_length - 1:

            value = samples[-1]

        else:

            sample1 = samples[index]
            sample2 = samples[index + 1]

            value = int(
                sample1
                + (sample2 - sample1) * fraction
            )

        output.append(value)

    # --------------------------------------------------------
    # NORMALIZE / AMPLIFY FOR SPEECH RECOGNITION
    # --------------------------------------------------------

    peak = max(
        abs(sample)
        for sample in output
    )

    if peak > 0:

        # Target speech peak
        target_peak = 24500

        gain = target_peak / peak

        # Don't excessively amplify audio
        if gain > 1.8:
            gain = 1.8

        if gain < 1.0:
            gain = 1.0

        for i in range(len(output)):

            value = int(
                output[i] * gain
            )

            if value > 32767:
                value = 32767

            elif value < -32768:
                value = -32768

            output[i] = value

    return output.tobytes()


# ============================================================
# AUDIO INTERFACE
# ============================================================

class VBCableAudioInterface(AudioInterface):

    def __init__(self):

        self.audio = pyaudio.PyAudio()

        self.input_stream = None
        self.output_stream = None

        self.running = False

        self.lock = threading.Lock()

        self.input_thread = None


    # ========================================================
    # START AUDIO
    # ========================================================

    def start(self, input_callback):

        print("[AUDIO] Starting audio interface...")

        self.running = True


        # ----------------------------------------------------
        # CANDIDATE INPUT
        #
        # Google Meet
        #      ↓
        # CABLE Input
        #      ↓
        # CABLE Output
        #      ↓
        # Device 24
        #      ↓
        # 44.1 kHz
        #      ↓
        # Python resampling
        #      ↓
        # 16 kHz mono
        #      ↓
        # ElevenLabs
        # ----------------------------------------------------

        print(
            f"[AUDIO] Opening candidate input device "
            f"{INPUT_DEVICE_INDEX} at "
            f"{INPUT_SAMPLE_RATE} Hz..."
        )

        self.input_stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=INPUT_CHANNELS,
            rate=INPUT_SAMPLE_RATE,
            input=True,
            input_device_index=INPUT_DEVICE_INDEX,
            frames_per_buffer=INPUT_CHUNK_SIZE,
        )

        print("[AUDIO] Candidate input opened.")


        # ----------------------------------------------------
        # ALENA OUTPUT
        #
        # ElevenLabs
        #      ↓
        # Python
        #      ↓
        # Device 50
        #      ↓
        # Voicemeeter
        #      ↓
        # B1
        #      ↓
        # Google Meet microphone
        # ----------------------------------------------------

        print(
            f"[AUDIO] Opening Alena output device "
            f"{OUTPUT_DEVICE_INDEX}..."
        )

        self.output_stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=OUTPUT_CHANNELS,
            rate=OUTPUT_SAMPLE_RATE,
            output=True,
            output_device_index=OUTPUT_DEVICE_INDEX,
            frames_per_buffer=OUTPUT_CHUNK_SIZE,
        )

        print("[AUDIO] Alena output opened.")


        # ====================================================
        # CANDIDATE AUDIO THREAD
        # ====================================================

        def read_audio():

            print(
                "[AUDIO] Listening for candidate "
                "(44.1 kHz -> 16 kHz)..."
            )

            while self.running:

                try:

                    # Read native VB-Cable audio
                    data = self.input_stream.read(
                        INPUT_CHUNK_SIZE,
                        exception_on_overflow=False,
                    )


                    # Convert:
                    #
                    # 44,100 Hz
                    #       ↓
                    # 16,000 Hz
                    #
                    converted_audio = (
                        resample_44100_to_16000(
                            data
                        )
                    )


                    if (
                        self.running
                        and converted_audio
                    ):

                        # Send 16 kHz mono PCM
                        # to ElevenLabs
                        input_callback(
                            converted_audio
                        )


                except Exception as error:

                    if self.running:

                        print(
                            f"[AUDIO INPUT ERROR] "
                            f"{error}"
                        )

                    break


        self.input_thread = threading.Thread(
            target=read_audio,
            daemon=True
        )

        self.input_thread.start()


        print(
            "[AUDIO] Candidate input ready."
        )

        print(
            "[AUDIO] Alena output ready."
        )


    # ========================================================
    # STOP AUDIO
    # ========================================================

    def stop(self):

        print("[AUDIO] Stopping...")

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

            self.audio.terminate()

        except Exception:

            pass


        print("[AUDIO] Stopped.")


    # ========================================================
    # ALENA AUDIO OUTPUT
    # ========================================================

    def output(self, audio: bytes):

        if not self.running:

            return


        try:

            with self.lock:

                if not self.output_stream:

                    return


                # ElevenLabs gives us 16-bit PCM.
                #
                # Convert:
                #
                # 16 kHz mono
                #       ↓
                # 48 kHz mono
                #       ↓
                # stereo
                #
                # 16 -> 48 kHz = 3x sample duplication

                samples = array.array(
                    "h",
                    audio
                )

                resampled = array.array(
                    "h"
                )


                for sample in samples:

                    resampled.append(
                        sample
                    )

                    resampled.append(
                        sample
                    )

                    resampled.append(
                        sample
                    )


                stereo = array.array(
                    "h"
                )


                for sample in resampled:

                    stereo.append(
                        sample
                    )

                    stereo.append(
                        sample
                    )


                self.output_stream.write(
                    stereo.tobytes()
                )


        except Exception as error:

            print(
                f"[AUDIO OUTPUT ERROR] "
                f"{error}"
            )


    # ========================================================
    # INTERRUPT
    # ========================================================

    def interrupt(self):

        print(
            "[AUDIO] Interrupting Alena audio..."
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
            "=" * 70 + "\n\n"
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


    print("=" * 70)

    print(
        "SalesInterviewAI - ALENA"
    )

    print("=" * 70)

    print(
        f"Interview ID: {interview_id}"
    )

    print(
        f"Agent ID: {AGENT_ID}"
    )

    print(
        f"Candidate input device: "
        f"{INPUT_DEVICE_INDEX}"
    )

    print(
        f"Candidate input rate: "
        f"{INPUT_SAMPLE_RATE} Hz"
    )

    print(
        f"ElevenLabs input rate: "
        f"{ELEVENLABS_SAMPLE_RATE} Hz"
    )

    print(
        f"Alena output device: "
        f"{OUTPUT_DEVICE_INDEX}"
    )

    print(
        f"Maximum duration: "
        f"{max_duration_seconds} seconds"
    )

    print("=" * 70)


    elevenlabs = ElevenLabs(
        api_key=API_KEY
    )


    audio_interface = (
        VBCableAudioInterface()
    )


    transcript_entries = []

    transcript_lock = threading.Lock()


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

            "timestamp": datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),

        }


        with transcript_lock:

            transcript_entries.append(
                entry
            )


    def on_agent_response(response):

        print(
            f"\nALENA: {response}"
        )

        add_transcript(
            "ALENA",
            response
        )


    def on_user_transcript(transcript):

        print(
            f"\nCANDIDATE: {transcript}"
        )

        add_transcript(
            "CANDIDATE",
            transcript
        )


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
    # AUTOMATIC SHUTDOWN
    # ========================================================

    def automatic_shutdown():

        print("\n")

        print("=" * 70)

        print(
            "[ALENA] Maximum interview "
            "duration reached."
        )

        print(
            "[ALENA] Ending ElevenLabs session..."
        )

        print("=" * 70)


        try:

            conversation.end_session()

        except Exception as error:

            print(
                "[ALENA] Session shutdown error: "
                + str(error)
            )


    # ========================================================
    # START SESSION
    # ========================================================

    try:

        print(
            "\n[ALENA] Starting conversation..."
        )

        print(
            "[ALENA] Waiting for candidate audio..."
        )


        conversation.start_session()


        stop_timer = threading.Timer(
            max_duration_seconds,
            automatic_shutdown
        )

        stop_timer.daemon = True

        stop_timer.start()


        print(
            "\n[ALENA] Conversation is active."
        )

        print(
            "[ALENA] Automatic ending timer started."
        )


        conversation_id = (
            conversation.wait_for_session_end()
        )


        print(
            "\n[ALENA] Session ended:"
        )

        print(
            f"[ALENA] Conversation ID: "
            f"{conversation_id}"
        )


        transcript_path = save_transcript(

            interview_id=interview_id,

            transcript_entries=(
                transcript_entries
            ),

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

