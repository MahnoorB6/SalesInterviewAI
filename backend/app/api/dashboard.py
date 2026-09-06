
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.evaluation import Evaluation
from app.auth import get_current_user


router = APIRouter(
    prefix="/api/dashboard",
    tags=["Dashboard"],
)


@router.get("/stats")
def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    total_candidates = (
        db.query(func.count(Candidate.id)).scalar() or 0
    )

    scheduled_interviews = (
        db.query(func.count(Interview.id))
        .filter(Interview.status == "scheduled")
        .scalar()
        or 0
    )

    completed_interviews = (
        db.query(func.count(Interview.id))
        .filter(Interview.status == "completed")
        .scalar()
        or 0
    )

    average_score = db.query(
        func.avg(Evaluation.overall_score)
    ).scalar()

    return {
        "total_candidates": total_candidates,
        "scheduled_interviews": scheduled_interviews,
        "completed_interviews": completed_interviews,
        "average_score": (
            round(float(average_score), 2)
            if average_score is not None
            else None
        ),
    }


@router.get("/interviews")
def get_dashboard_interviews(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    interviews = (
        db.query(
            Interview.id,
            Interview.scheduled_at,
            Interview.status,
            Interview.meet_link,
            Candidate.id.label("candidate_id"),
            Candidate.name.label("candidate_name"),
            Candidate.email.label("candidate_email"),
            Evaluation.overall_score,
        )
        .join(
            Candidate,
            Interview.candidate_id == Candidate.id,
        )
        .outerjoin(
            Evaluation,
            Evaluation.interview_id == Interview.id,
        )
        .order_by(Interview.scheduled_at.desc())
        .all()
    )

    return [
        {
            "interview_id": interview.id,
            "candidate_id": interview.candidate_id,
            "candidate_name": interview.candidate_name,
            "candidate_email": interview.candidate_email,
            "scheduled_at": interview.scheduled_at,
            "status": interview.status,
            "meet_link": interview.meet_link,
            "score": interview.overall_score,
        }
        for interview in interviews
    ]


@router.get("/overview")
def get_dashboard_overview(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    total_candidates = (
        db.query(func.count(Candidate.id)).scalar() or 0
    )

    total_interviews = (
        db.query(func.count(Interview.id)).scalar() or 0
    )

    completed_interviews = (
        db.query(func.count(Interview.id))
        .filter(Interview.status == "completed")
        .scalar()
        or 0
    )

    scheduled_interviews = (
        db.query(func.count(Interview.id))
        .filter(Interview.status == "scheduled")
        .scalar()
        or 0
    )

    average_score = db.query(
        func.avg(Evaluation.overall_score)
    ).scalar()

    return {
        "total_candidates": total_candidates,
        "total_interviews": total_interviews,
        "scheduled_interviews": scheduled_interviews,
        "completed_interviews": completed_interviews,
        "average_score": (
            round(float(average_score), 2)
            if average_score is not None
            else None
        ),
    }

