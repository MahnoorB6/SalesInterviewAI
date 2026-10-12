
import os
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import PlainTextResponse
import logging
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.interview import Interview
from app.models.candidate import Candidate
from app.models.interview_question import InterviewQuestion
from app.schemas.interview import InterviewCreate, InterviewQuestionResponse, InterviewResponse
from app.statuses import InterviewStatus, can_transition_interview
from app.auth import get_current_user
from app.transcripts import transcript_path_for, structured_transcript_path_for

# IMPORTANT:
# Your actual file is:
# app/services/question_generator.py
from app.services.question_generator import (
    generate_interview_questions,
)

from app.services.google_calendar import (
    create_interview_event,
    send_email,
)


router = APIRouter(
    prefix="/api/interviews",
    tags=["Interviews"],
    dependencies=[Depends(get_current_user)],
)
logger = logging.getLogger(__name__)


# ============================================================
# HELPERS
# ============================================================

PAKISTAN_TIMEZONE = ZoneInfo("Asia/Karachi")


def normalize_scheduled_at(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=PAKISTAN_TIMEZONE)
    return value.astimezone(PAKISTAN_TIMEZONE)


def get_candidate_name(candidate):
    """
    Safely get candidate's full name.
    """

    if not candidate:
        return "Candidate"

    first_name = getattr(
        candidate,
        "first_name",
        None,
    )

    last_name = getattr(
        candidate,
        "last_name",
        None,
    )

    if first_name or last_name:
        return " ".join(
            part
            for part in [
                first_name,
                last_name,
            ]
            if part
        ).strip()

    name = getattr(
        candidate,
        "name",
        None,
    )

    if name:
        return name

    return "Candidate"


def get_candidate_email(candidate):
    """
    Safely get candidate email.
    """

    if not candidate:
        return None

    return getattr(
        candidate,
        "email",
        None,
    )


def interview_with_candidate(
    db: Session,
    interview_id: int = Path(gt=0),
):
    """
    Get interview together with its candidate.
    """

    interview = (
        db.query(Interview)
        .filter(
            Interview.id == interview_id
        )
        .first()
    )

    if not interview:
        raise HTTPException(
            status_code=404,
            detail="Interview not found.",
        )

    candidate = (
        db.query(Candidate)
        .filter(
            Candidate.id == interview.candidate_id
        )
        .first()
    )

    if not candidate:
        raise HTTPException(
            status_code=404,
            detail="Candidate not found.",
        )

    return interview, candidate


# ============================================================
# CREATE INTERVIEW
# ============================================================

@router.post(
    "/",
    response_model=InterviewResponse,
)
def create_interview(
    interview_data: InterviewCreate,
    db: Session = Depends(get_db),
):
    """
    Create a new interview.

    Flow:

    1. Validate candidate.
    2. Read candidate resume analysis.
    3. Generate 10 interview questions.
       - Gemini is attempted once.
       - If Gemini fails, local fallback questions are used.
    4. Save interview.
    5. Save interview questions.
    6. Create Google Calendar event.
    7. Save Google Meet link.
    """

    # --------------------------------------------------------
    # 1. CHECK CANDIDATE
    # --------------------------------------------------------

    candidate = (
        db.query(Candidate)
        .filter(
            Candidate.id == interview_data.candidate_id
        )
        .first()
    )

    if not candidate:
        raise HTTPException(
            status_code=404,
            detail="Candidate not found.",
        )

    candidate_name = get_candidate_name(
        candidate
    )

    candidate_email = get_candidate_email(
        candidate
    )

    if not candidate_email:
        raise HTTPException(
            status_code=400,
            detail=(
                "Candidate does not have an email address."
            ),
        )

    # --------------------------------------------------------
    # 2. GET RESUME ANALYSIS
    # --------------------------------------------------------

    resume_analysis = getattr(
        candidate,
        "resume_analysis",
        None,
    )

    if resume_analysis is None:
        resume_analysis = {}

    if not isinstance(
        resume_analysis,
        dict,
    ):
        resume_analysis = {}

    # --------------------------------------------------------
    # 3. GET POSITION
    # --------------------------------------------------------

    position = (
        getattr(
            interview_data,
            "position",
            None,
        )
        or "Sales Representative"
    )

    # --------------------------------------------------------
    # 4. GENERATE INTERVIEW QUESTIONS
    # --------------------------------------------------------

    try:
        print(
            f"[INTERVIEW] Generating questions for "
            f"candidate #{candidate.id} "
            f"({candidate_name})..."
        )

        interview_questions = (
            generate_interview_questions(
                resume_analysis=resume_analysis,
                position=position,
            )
        )

        if not interview_questions:
            raise ValueError(
                "No interview questions were generated."
            )

        if len(interview_questions) != 10:
            raise ValueError(
                "Interview question generator must "
                "return exactly 10 questions."
            )

        print(
            "[INTERVIEW] 10 interview questions ready."
        )

    except Exception as error:
        logger.exception("Question generation failed")
        raise HTTPException(status_code=503, detail="Unable to generate interview questions")

    # --------------------------------------------------------
    # 5. CREATE INTERVIEW DATABASE RECORD
    # --------------------------------------------------------

    scheduled_at = normalize_scheduled_at(interview_data.scheduled_at)

    interview = Interview(
        candidate_id=interview_data.candidate_id,
        position=position,
        scheduled_at=scheduled_at,
        duration_minutes=interview_data.duration_minutes,
        notes=getattr(
            interview_data,
            "notes",
            None,
        ),
        status=InterviewStatus.SCHEDULED.value,
    )

    # --------------------------------------------------------
    # 6. SAVE INTERVIEW AND QUESTIONS ATOMICALLY
    # --------------------------------------------------------

    try:
        for question in interview_questions:

            question_number = question.get(
                "question_number"
            )

            question_text = question.get(
                "question"
            )

            category = question.get(
                "category"
            )

            interview_question = InterviewQuestion(
                interview=interview,
                question_number=question_number,
                question=question_text,
                category=category,
            )

            db.add(interview_question)

        db.add(interview)
        db.commit()
        db.refresh(interview)

        print(
            f"[INTERVIEW] Saved {len(interview_questions)} "
            f"questions for interview #{interview.id}"
        )

    except Exception as error:

        db.rollback()

        logger.warning("Question persistence failed for interview request (%s)", type(error).__name__)

        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to save interview questions."
            ),
        )

    # --------------------------------------------------------
    # 7. CREATE GOOGLE CALENDAR EVENT + GOOGLE MEET
    # --------------------------------------------------------

    try:
        print(
            f"[INTERVIEW] Creating Google Calendar event "
            f"for interview #{interview.id}..."
        )

        # IMPORTANT:
        # create_interview_event() does NOT accept notes.
        calendar_result = create_interview_event(
            candidate_name=candidate_name,
            candidate_email=candidate_email,
            position=position,
            scheduled_at=scheduled_at,
            duration_minutes=interview.duration_minutes,
        )

        if not calendar_result:
            raise RuntimeError(
                "Google Calendar returned no result."
            )

        meet_link = calendar_result.get(
            "meet_link"
        )

        calendar_link = calendar_result.get(
            "calendar_link"
        )

        event_id = calendar_result.get(
            "event_id"
        )

        if not meet_link:
            raise RuntimeError(
                "Google Calendar event was created "
                "without a Google Meet link."
            )

        # ----------------------------------------------------
        # SAVE GOOGLE MEET LINK
        # ----------------------------------------------------

        if hasattr(
            interview,
            "meet_link",
        ):
            interview.meet_link = meet_link

        # ----------------------------------------------------
        # SAVE GOOGLE CALENDAR EVENT ID
        # ----------------------------------------------------

        interview.calendar_event_id = event_id

        db.commit()
        db.refresh(interview)

        print(
            f"[INTERVIEW] Google Meet link saved: "
            f"{meet_link}"
        )

        if calendar_link:
            print(
                f"[INTERVIEW] Google Calendar link: "
                f"{calendar_link}"
            )

        # ----------------------------------------------------
        # SEND INTERVIEW SCHEDULING EMAIL
        # ----------------------------------------------------

        scheduled_display = scheduled_at.strftime(
            "%A, %d %B %Y at %I:%M %p"
        )

        email_subject = (
            f"Sales Interview Scheduled - {position}"
        )

        email_body = (
            f"Hello {candidate_name},\n\n"
            "Your sales interview has been scheduled.\n\n"
            f"Position: {position}\n"
            f"Date & Time: {scheduled_display} (Pakistan Time)\n"
            f"Duration: {interview.duration_minutes} minutes\n\n"
            f"Google Meet: {meet_link}\n\n"
            "Please join the Google Meet link at the scheduled time.\n\n"
            "Best regards,\n"
            "SalesInterviewAI"
        )

        try:
            send_email(
                recipient_email=candidate_email,
                subject=email_subject,
                body=email_body,
            )

            print(
                f"[INTERVIEW] Scheduling email sent to {candidate_email}"
            )

        except Exception as email_error:
            logger.warning("Scheduling email failed for interview %s (%s)", interview.id, type(email_error).__name__)
            raise HTTPException(status_code=502, detail="Interview and Meet were created, but the scheduling email could not be sent")

    except HTTPException:
        raise

    except Exception as error:

        db.rollback()

        logger.warning("Calendar event creation failed for interview %s (%s)", interview.id, type(error).__name__)
        raise HTTPException(status_code=502, detail="Interview was saved, but Google Calendar/Meet creation failed")

    # --------------------------------------------------------
    # 8. RETURN INTERVIEW
    # --------------------------------------------------------

    return interview


# ============================================================
# GET ALL INTERVIEWS
# ============================================================

@router.get(
    "/",
)
def get_interviews(
    db: Session = Depends(get_db),
):
    """
    Return all interviews.
    """

    interviews = (
        db.query(Interview)
        .order_by(
            Interview.scheduled_at.desc()
        )
        .all()
    )

    results = []

    for interview in interviews:

        candidate = (
            db.query(Candidate)
            .filter(
                Candidate.id
                == interview.candidate_id
            )
            .first()
        )

        results.append(
            {
                "id": interview.id,
                "candidate_id": interview.candidate_id,
                "candidate_name": get_candidate_name(
                    candidate
                ),
                "candidate_email": get_candidate_email(
                    candidate
                ),
                "position": interview.position,
                "scheduled_at": interview.scheduled_at,
                "duration_minutes": interview.duration_minutes,
                "status": interview.status,
                "meet_link": getattr(
                    interview,
                    "meet_link",
                    None,
                ),
                "calendar_event_id": interview.calendar_event_id,
                "notes": getattr(
                    interview,
                    "notes",
                    None,
                ),
                "transcript_available": bool(interview.transcript_path),
                "completed_at": getattr(
                    interview,
                    "completed_at",
                    None,
                ),
            }
        )

    return results


# ============================================================
# GET SINGLE INTERVIEW
# ============================================================

@router.get(
    "/{interview_id}",
)
def get_interview(
    interview_id: int = Path(gt=0),
    db: Session = Depends(get_db),
):
    """
    Return one interview.
    """

    interview, candidate = interview_with_candidate(
        db=db,
        interview_id=interview_id,
    )

    return {
        "id": interview.id,
        "candidate_id": interview.candidate_id,
        "candidate_name": get_candidate_name(
            candidate
        ),
        "candidate_email": get_candidate_email(
            candidate
        ),
        "position": interview.position,
        "scheduled_at": interview.scheduled_at,
        "duration_minutes": interview.duration_minutes,
        "status": interview.status,
        "meet_link": getattr(
            interview,
            "meet_link",
            None,
        ),
        "calendar_event_id": interview.calendar_event_id,
        "notes": getattr(
            interview,
            "notes",
            None,
        ),
        "transcript_available": bool(interview.transcript_path),
        "completed_at": getattr(
            interview,
            "completed_at",
            None,
        ),
    }


# ============================================================
# GET INTERVIEW TRANSCRIPT
# ============================================================

@router.get("/{interview_id}/transcript", response_class=PlainTextResponse)
def get_interview_transcript(interview_id: int = Path(gt=0), db: Session = Depends(get_db)):
    interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    if not interview.transcript_path:
        raise HTTPException(status_code=404, detail="Transcript is not available for this interview")
    path = transcript_path_for(interview)
    if not path:
        raise HTTPException(status_code=404, detail="Transcript is not available for this interview")
    try:
        with open(path, "r", encoding="utf-8") as transcript_file:
            return PlainTextResponse(transcript_file.read())
    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Transcript file not found")
    except OSError:
        logger.exception("Could not retrieve transcript for interview %s", interview_id)
        raise HTTPException(status_code=500, detail="Transcript could not be retrieved")


@router.get("/{interview_id}/transcript/structured")
def get_structured_interview_transcript(interview_id: int = Path(gt=0), db: Session = Depends(get_db)):
    interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    path = structured_transcript_path_for(interview)
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="Structured transcript is not available for this interview")
    try:
        with path.open("r", encoding="utf-8") as transcript_file:
            return json.load(transcript_file)
    except (OSError, json.JSONDecodeError):
        logger.exception("Could not retrieve structured transcript for interview %s", interview_id)
        raise HTTPException(status_code=500, detail="Structured transcript could not be retrieved")


# ============================================================
# UPDATE INTERVIEW STATUS
# ============================================================

@router.patch(
    "/{interview_id}/status",
)
def update_interview_status(
    status: InterviewStatus,
    interview_id: int = Path(gt=0),
    db: Session = Depends(get_db),
):
    """
    Update interview status.

    Allowed:
    - scheduled
    - in_progress
    - completed
    - cancelled
    - interrupted
    """

    status_value = status.value

    interview = (
        db.query(Interview)
        .filter(
            Interview.id == interview_id
        )
        .first()
    )

    if not interview:
        raise HTTPException(
            status_code=404,
            detail="Interview not found.",
        )

    if status_value in {
        InterviewStatus.IN_PROGRESS.value,
        InterviewStatus.COMPLETED.value,
        InterviewStatus.INTERRUPTED.value,
        InterviewStatus.FAILED.value,
    }:
        raise HTTPException(
            status_code=409,
            detail="Execution status is managed by the scheduler and interview runner.",
        )

    if not can_transition_interview(interview.status, status_value):
        raise HTTPException(status_code=409, detail=f"Cannot change interview status from {interview.status} to {status_value}")
    interview.status = status_value

    if status_value == InterviewStatus.COMPLETED.value:
        if hasattr(
            interview,
            "completed_at",
        ):
            interview.completed_at = datetime.now(
                timezone.utc
            )

    db.commit()
    db.refresh(interview)

    return {
        "message": "Interview status updated.",
        "interview_id": interview.id,
        "status": interview.status,
        "completed_at": getattr(
            interview,
            "completed_at",
            None,
        ),
    }


# ============================================================
# GENERATE / REGENERATE INTERVIEW QUESTIONS
# ============================================================

@router.post(
    "/{interview_id}/questions/generate",
)
def generate_questions_for_interview(
    interview_id: int = Path(gt=0),
    db: Session = Depends(get_db),
):
    """
    Generate or regenerate the 10 questions
    for an existing interview.

    Gemini is attempted once.
    If Gemini fails, question_generator.py
    automatically provides fallback questions.
    """

    interview, candidate = interview_with_candidate(
        db=db,
        interview_id=interview_id,
    )

    # The current schema has no persisted draft state: interviews are created
    # together with their saved questions and immediately scheduled.
    if interview.status != "draft":
        raise HTTPException(
            status_code=409,
            detail="Interview questions are frozen once the interview is saved and scheduled.",
        )

    resume_analysis = getattr(
        candidate,
        "resume_analysis",
        None,
    )

    if resume_analysis is None:
        resume_analysis = {}

    if not isinstance(
        resume_analysis,
        dict,
    ):
        resume_analysis = {}

    position = (
        interview.position
        or "Sales Representative"
    )

    try:
        questions = generate_interview_questions(
            resume_analysis=resume_analysis,
            position=position,
        )

    except Exception as error:
        logger.exception("Question generation failed")
        raise HTTPException(status_code=503, detail="Unable to generate interview questions")

    if len(questions) != 10:
        raise HTTPException(
            status_code=500,
            detail=(
                "Question generator did not return "
                "exactly 10 questions."
            ),
        )

    try:
        # Remove old questions
        (
            db.query(InterviewQuestion)
            .filter(
                InterviewQuestion.interview_id
                == interview.id
            )
            .delete(
                synchronize_session=False
            )
        )

        # Add new questions
        for question in questions:

            db.add(
                InterviewQuestion(
                    interview_id=interview.id,
                    question_number=question[
                        "question_number"
                    ],
                    question=question[
                        "question"
                    ],
                    category=question[
                        "category"
                    ],
                )
            )

        db.commit()

    except Exception as error:

        db.rollback()

        logger.exception("Question save failed for interview %s", interview_id)
        raise HTTPException(status_code=500, detail="Failed to save generated questions")

    return {
        "message": (
            "Interview questions generated successfully."
        ),
        "interview_id": interview.id,
        "questions": questions,
    }


# ============================================================
# GET INTERVIEW QUESTIONS
# ============================================================

@router.get(
    "/{interview_id}/questions",
    response_model=list[InterviewQuestionResponse],
)
def get_interview_questions(
    interview_id: int = Path(gt=0),
    db: Session = Depends(get_db),
):
    """
    Return all questions belonging to an interview.
    """

    interview = (
        db.query(Interview)
        .filter(
            Interview.id == interview_id
        )
        .first()
    )

    if not interview:
        raise HTTPException(
            status_code=404,
            detail="Interview not found.",
        )

    questions = (
        db.query(InterviewQuestion)
        .filter(
            InterviewQuestion.interview_id
            == interview_id
        )
        .order_by(
            InterviewQuestion.question_number.asc()
        )
        .all()
    )

    return [
        {
            "id": question.id,
            "interview_id": question.interview_id,
            "question_number": (
                question.question_number
            ),
            "question": question.question,
            "category": question.category,
            "created_at": question.created_at,
        }
        for question in questions
    ]


