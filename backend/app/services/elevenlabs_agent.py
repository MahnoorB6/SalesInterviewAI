import os
import threading
import time
from datetime import datetime

import pyaudio
from dotenv import load_dotenv

from elevenlabs.client import ElevenLabs
from elevenlabs.conversational_ai.conversation import (
    Conversation,
    AudioInterface,
)


load_dotenv()


# ============================================================
# CONFIGURATION
# ============================================================

AGENT_ID = os.getenv("ELEVENLABS_AGENT_ID")
API_KEY = os.getenv("ELEVENLABS_API_KEY")

# Device 4 = Microphone Array
# Device 12 = CABLE Input
INPUT_DEVICE_INDEX = 4
OUTPUT_DEVICE_INDEX = 12

SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_SIZE = 1024

# Maximum interview duration.
# 30 minutes = 1800 seconds.
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
    "transcripts",
)

os.makedirs(
    TRANSCRIPT_DIR,
    exist_ok=True,
)


# ============================================================
# VB-CABLE AUDIO INTERFACE
# ============================================================

class VBCableAudioInterface(AudioInterface):

    def __init__(self):

        self.audio = pyaudio.PyAudio()

        self.input_stream = None
        self.output_stream = None

        self.running = False
        self.lock = threading.Lock()
        self.input_thread = None


    def start(self, input_callback):

        print("[AUDIO] Starting VB-Cable audio...")

        self.running = True

        # ----------------------------------------------------
        # CANDIDATE AUDIO INPUT
        # Device 4 = Microphone Array
        # ----------------------------------------------------

        self.input_stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            input_device_index=INPUT_DEVICE_INDEX,
            frames_per_buffer=CHUNK_SIZE,
        )

        # ----------------------------------------------------
        # ALENA AUDIO OUTPUT
        # Device 12 = CABLE Input
        # ----------------------------------------------------

        self.output_stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            output=True,
            output_device_index=OUTPUT_DEVICE_INDEX,
            frames_per_buffer=CHUNK_SIZE,
        )


        def read_audio():

            print(
                "[AUDIO] Listening for candidate..."
            )

            while self.running:

                try:

                    data = self.input_stream.read(
                        CHUNK_SIZE,
                        exception_on_overflow=False,
                    )

                    if self.running:

                        input_callback(data)

                except Exception as error:

                    if self.running:

                        print(
                            f"[AUDIO INPUT ERROR] {error}"
                        )

                    break


        self.input_thread = threading.Thread(
            target=read_audio,
            daemon=True,
        )

        self.input_thread.start()

        print(
            "[AUDIO] VB-Cable input ready."
        )


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


    def output(self, audio: bytes):

        if not self.running:
            return

        try:

            with self.lock:

                if self.output_stream:

                    self.output_stream.write(
                        audio
                    )

        except Exception as error:

            print(
                f"[AUDIO OUTPUT ERROR] {error}"
            )


    def interrupt(self):

        print(
            "[AUDIO] Interrupting Alena audio..."
        )

        # Do not close the audio stream here.
        # ElevenLabs manages conversational interruption.


# ============================================================
# SAVE TRANSCRIPT
# ============================================================

def save_transcript(
    interview_id,
    transcript_entries,
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
        filename,
    )


    with open(
        transcript_path,
        "w",
        encoding="utf-8",
    ) as file:

        file.write(
            "SalesInterviewAI - Alena Interview Transcript\n"
        )

        file.write(
            "=" * 70
            + "\n\n"
        )


        for entry in transcript_entries:

            speaker = entry.get(
                "speaker",
                "UNKNOWN",
            )

            text = entry.get(
                "text",
                "",
            )

            timestamp = entry.get(
                "timestamp",
                "",
            )

            file.write(
                f"[{timestamp}] {speaker}: {text}\n\n"
            )


    print(
        f"[TRANSCRIPT] Saved: {transcript_path}"
    )

    return transcript_path


# ============================================================
# RUN ALENA
# ============================================================

def run_alena(
    interview_id=None,
    max_duration_seconds=MAX_INTERVIEW_SECONDS,
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
    print("SalesInterviewAI - ALENA")
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


    # --------------------------------------------------------
    # TRANSCRIPT MEMORY
    # --------------------------------------------------------

    transcript_entries = []

    transcript_lock = threading.Lock()


    def add_transcript(
        speaker,
        text,
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


    # --------------------------------------------------------
    # CALLBACKS
    # --------------------------------------------------------

    def on_agent_response(response):

        print(
            f"\nALENA: {response}"
        )

        add_transcript(
            "ALENA",
            response,
        )


    def on_user_transcript(transcript):

        print(
            f"\nCANDIDATE: {transcript}"
        )

        add_transcript(
            "CANDIDATE",
            transcript,
        )


    def on_agent_correction(
        original,
        corrected,
    ):

        print(
            f"\nALENA CORRECTION: "
            f"{original} -> {corrected}"
        )


    # --------------------------------------------------------
    # ELEVENLABS CONVERSATION
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # AUTOMATIC SESSION STOP
    # --------------------------------------------------------

    stop_timer = None


    def automatic_shutdown():

        print("\n")
        print("=" * 70)

        print(
            "[ALENA] Maximum interview duration reached."
        )

        print(
            "[ALENA] Ending ElevenLabs session..."
        )

        print("=" * 70)


        try:

            conversation.end_session()

        except Exception as error:

            print(
                f"[ALENA] Session shutdown error: "
                f"{error}"
            )


    try:

        print(
            "\n[ALENA] Starting conversation..."
        )

        print(
            "[ALENA] Waiting for candidate audio..."
        )


        # ----------------------------------------------------
        # START SESSION
        # ----------------------------------------------------

        conversation.start_session()


        # ----------------------------------------------------
        # START MAX-DURATION TIMER
        # ----------------------------------------------------

        stop_timer = threading.Timer(
            max_duration_seconds,
            automatic_shutdown,
        )

        stop_timer.daemon = True

        stop_timer.start()


        print(
            "\n[ALENA] Conversation is active."
        )

        print(
            "[ALENA] Automatic ending timer started."
        )


        # ----------------------------------------------------
        # WAIT UNTIL ALENA SESSION ENDS
        # ----------------------------------------------------

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


        # ----------------------------------------------------
        # SAVE TRANSCRIPT
        # ----------------------------------------------------

        transcript_path = save_transcript(
            interview_id=interview_id,
            transcript_entries=transcript_entries,
        )


        return {
            "conversation_id": conversation_id,
            "transcript_path": transcript_path,
            "transcript_entries": transcript_entries,
        }


    finally:

        # ----------------------------------------------------
        # CANCEL TIMER IF INTERVIEW ENDED EARLY
        # ----------------------------------------------------

        if stop_timer:

            try:

                stop_timer.cancel()

            except Exception:
                pass


        # ----------------------------------------------------
        # STOP AUDIO
        # ----------------------------------------------------

        try:

            audio_interface.stop()

        except Exception:
            pass


        print(
            "[ALENA] Audio interface closed."
        )


# ============================================================
# DIRECT TEST
# ============================================================

if __name__ == "__main__":

    run_alena()