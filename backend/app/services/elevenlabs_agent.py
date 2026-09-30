import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from elevenlabs import ElevenLabs
from elevenlabs.conversational_ai.conversation import (
    Conversation,
    ConversationInitiationData,
)
from elevenlabs.conversational_ai.default_audio_interface import (
    DefaultAudioInterface,
)

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
        audio_interface=DefaultAudioInterface(),
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