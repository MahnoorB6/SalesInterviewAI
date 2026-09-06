from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.interview import Interview
from app.models.candidate import Candidate
from app.schemas.interview import (
    InterviewCreate,
    InterviewResponse,
)

from app.services.google_calendar import (
    create_interview_event,
)


router = APIRouter(
    prefix="/api/interviews",
    tags=["Interviews"],
)


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

    # --------------------------------------------------------
    # FIND CANDIDATE
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

    # --------------------------------------------------------
    # CREATE GOOGLE CALENDAR + GOOGLE MEET
    # --------------------------------------------------------

    try:

        google_event = create_interview_event(
            candidate_name=candidate.name,
            candidate_email=candidate.email,
            scheduled_at=interview_data.scheduled_at,
            position=interview_data.position,
        )

    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to create Google Calendar "
                f"event: {str(error)}"
            ),
        )

    # --------------------------------------------------------
    # SAVE INTERVIEW
    # --------------------------------------------------------

    interview = Interview(
        candidate_id=candidate.id,
        position=interview_data.position,
        scheduled_at=interview_data.scheduled_at,
        status="scheduled",
        meet_link=google_event["meet_link"],
        calendar_event_id=google_event["event_id"],
    )

    db.add(interview)

    db.commit()

    db.refresh(interview)

    return interview


# ============================================================
# GET ALL INTERVIEWS
# ============================================================

@router.get(
    "/",
    response_model=list[InterviewResponse],
)
def get_interviews(
    db: Session = Depends(get_db),
):

    return (
        db.query(Interview)
        .order_by(Interview.scheduled_at.asc())
        .all()
    )


# ============================================================
# GET SINGLE INTERVIEW
# ============================================================

@router.get(
    "/{interview_id}",
    response_model=InterviewResponse,
)
def get_interview(
    interview_id: int,
    db: Session = Depends(get_db),
):

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

    return interview


# ============================================================
# UPDATE INTERVIEW
# ============================================================

@router.put(
    "/{interview_id}",
    response_model=InterviewResponse,
)
def update_interview(
    interview_id: int,
    interview_data: InterviewCreate,
    db: Session = Depends(get_db),
):

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
            Candidate.id == interview_data.candidate_id
        )
        .first()
    )

    if not candidate:

        raise HTTPException(
            status_code=404,
            detail="Candidate not found.",
        )

    interview.candidate_id = candidate.id
    interview.position = interview_data.position
    interview.scheduled_at = interview_data.scheduled_at

    db.commit()

    db.refresh(interview)

    return interview


# ============================================================
# UPDATE STATUS
# ============================================================

@router.patch(
    "/{interview_id}/status",
)
def update_interview_status(
    interview_id: int,
    status: str,
    db: Session = Depends(get_db),
):

    allowed_statuses = [
        "scheduled",
        "in_progress",
        "completed",
        "cancelled",
    ]

    if status not in allowed_statuses:

        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid status. Allowed values: "
                + ", ".join(allowed_statuses)
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

    db.commit()

    db.refresh(interview)

    return {
        "message":
            "Interview status updated successfully.",
        "interview_id":
            interview.id,
        "status":
            interview.status,
    }


# ============================================================
# DELETE INTERVIEW
# ============================================================

@router.delete(
    "/{interview_id}",
)
def delete_interview(
    interview_id: int,
    db: Session = Depends(get_db),
):

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

    db.delete(interview)

    db.commit()

    return {
        "message":
            "Interview deleted successfully.",
        "interview_id":
            interview_id,
    }