
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.interview import Interview
from app.models.candidate import Candidate
from app.models.interview_question import InterviewQuestion
from app.schemas.interview import InterviewCreate, InterviewResponse

# IMPORTANT:
# Your actual file is:
# app/services/question_generator.py
from app.services.question_generator import (
    generate_interview_questions,
)

from app.services.google_calendar import create_interview_event


router = APIRouter(
    prefix="/api/interviews",
    tags=["Interviews"],
)


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
    interview_id: int,
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
        print(
            "[INTERVIEW] Question generation failed: "
            f"{error}"
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "Unable to generate interview questions. "
                f"{error}"
            ),
        )

    # --------------------------------------------------------
    # 5. CREATE INTERVIEW DATABASE RECORD
    # --------------------------------------------------------

    scheduled_at = normalize_scheduled_at(interview_data.scheduled_at)

    interview = Interview(
        candidate_id=interview_data.candidate_id,
        position=position,
        scheduled_at=scheduled_at,
        notes=getattr(
            interview_data,
            "notes",
            None,
        ),
        status="scheduled",
    )

    db.add(interview)
    db.commit()
    db.refresh(interview)

    print(
        f"[INTERVIEW] Created interview #{interview.id}"
    )

    # --------------------------------------------------------
    # 6. SAVE QUESTIONS
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
                interview_id=interview.id,
                question_number=question_number,
                question=question_text,
                category=category,
            )

            db.add(interview_question)

        db.commit()

        print(
            f"[INTERVIEW] Saved {len(interview_questions)} "
            f"questions for interview #{interview.id}"
        )

    except Exception as error:

        db.rollback()

        print(
            "[INTERVIEW] Failed to save questions: "
            f"{error}"
        )

        try:
            db.delete(interview)
            db.commit()
        except Exception:
            db.rollback()

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

        if (
            event_id
            and hasattr(
                interview,
                "google_event_id",
            )
        ):
            interview.google_event_id = event_id

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

    except Exception as error:

        db.rollback()

        print(
            "[INTERVIEW] Google Calendar creation failed: "
            f"{error}"
        )

        raise HTTPException(
            status_code=502,
            detail=(
                "Interview questions were created, but "
                "Google Calendar/Google Meet creation failed. "
                f"{error}"
            ),
        )

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
                "status": interview.status,
                "meet_link": getattr(
                    interview,
                    "meet_link",
                    None,
                ),
                "notes": getattr(
                    interview,
                    "notes",
                    None,
                ),
                "transcript_path": getattr(
                    interview,
                    "transcript_path",
                    None,
                ),
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
    interview_id: int,
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
        "status": interview.status,
        "meet_link": getattr(
            interview,
            "meet_link",
            None,
        ),
        "notes": getattr(
            interview,
            "notes",
            None,
        ),
        "transcript_path": getattr(
            interview,
            "transcript_path",
            None,
        ),
        "completed_at": getattr(
            interview,
            "completed_at",
            None,
        ),
    }


# ============================================================
# GET INTERVIEW TRANSCRIPT
# ============================================================

@router.get(
    "/{interview_id}/transcript",
    response_class=PlainTextResponse,
)
def get_interview_transcript(
    interview_id: int,
    db: Session = Depends(get_db),
):
    """
    Return the saved transcript for an interview.

    This endpoint does NOT call Gemini or ElevenLabs.
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

    transcript_path = getattr(
        interview,
        "transcript_path",
        None,
    )

    if not transcript_path:
        raise HTTPException(
            status_code=404,
            detail="Transcript is not available.",
        )

    transcript_path = os.path.abspath(
        os.path.expanduser(
            transcript_path
        )
    )

    if not os.path.isfile(
        transcript_path
    ):
        raise HTTPException(
            status_code=404,
            detail="Transcript file not found.",
        )

    try:
        try:
            with open(
                transcript_path,
                "r",
                encoding="utf-8",
            ) as file:
                transcript = file.read()

        except UnicodeDecodeError:
            with open(
                transcript_path,
                "r",
                encoding="utf-8-sig",
            ) as file:
                transcript = file.read()

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Unable to read transcript: {error}"
            ),
        )

    return PlainTextResponse(
        content=transcript,
        media_type="text/plain; charset=utf-8",
    )


# ============================================================
# UPDATE INTERVIEW STATUS
# ============================================================

@router.patch(
    "/{interview_id}/status",
)
def update_interview_status(
    interview_id: int,
    status: str,
    db: Session = Depends(get_db),
):
    """
    Update interview status.

    Allowed:
    - scheduled
    - in_progress
    - completed
    - cancelled
    """

    allowed_statuses = {
        "scheduled",
        "in_progress",
        "completed",
        "cancelled",
    }

    if status not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid status. Allowed values: "
                "scheduled, in_progress, completed, cancelled."
            ),
        )

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

    interview.status = status

    if status == "completed":
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
    interview_id: int,
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
        print(
            "[INTERVIEW] Question generation failed: "
            f"{error}"
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "Unable to generate interview questions. "
                f"{error}"
            ),
        )

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

        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to save generated questions. "
                f"{error}"
            ),
        )

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
)
def get_interview_questions(
    interview_id: int,
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
        }
        for question in questions
    ]

