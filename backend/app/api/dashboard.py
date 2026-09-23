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


# ============================================================
# DASHBOARD STATS
# ============================================================

@router.get("/stats")
def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    total_candidates = (
        db.query(func.count(Candidate.id))
        .scalar()
        or 0
    )

    scheduled_interviews = (
        db.query(func.count(Interview.id))
        .filter(
            Interview.status == "scheduled"
        )
        .scalar()
        or 0
    )

    in_progress_interviews = (
        db.query(func.count(Interview.id))
        .filter(
            Interview.status == "in_progress"
        )
        .scalar()
        or 0
    )

    completed_interviews = (
        db.query(func.count(Interview.id))
        .filter(
            Interview.status == "completed"
        )
        .scalar()
        or 0
    )

    # Completed interviews that don't have an evaluation yet
    pending_evaluation = (
        db.query(func.count(Interview.id))
        .outerjoin(
            Evaluation,
            Evaluation.interview_id == Interview.id,
        )
        .filter(
            Interview.status == "completed",
            Evaluation.id.is_(None),
        )
        .scalar()
        or 0
    )

    evaluated_interviews = (
        db.query(func.count(Evaluation.id))
        .scalar()
        or 0
    )

    average_score = (
        db.query(
            func.avg(Evaluation.overall_score)
        )
        .scalar()
    )

    return {
        "total_candidates": total_candidates,
        "scheduled_interviews": scheduled_interviews,
        "in_progress_interviews": in_progress_interviews,
        "completed_interviews": completed_interviews,
        "pending_evaluation": pending_evaluation,
        "evaluated_interviews": evaluated_interviews,
        "average_score": (
            round(float(average_score), 2)
            if average_score is not None
            else None
        ),
    }


# ============================================================
# DASHBOARD INTERVIEWS
# ============================================================

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
            Interview.recording_path,
            Interview.transcript_path,
            Interview.completed_at,

            Candidate.id.label(
                "candidate_id"
            ),

            Candidate.name.label(
                "candidate_name"
            ),

            Candidate.email.label(
                "candidate_email"
            ),

            Candidate.latest_role.label(
                "latest_role"
            ),

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
        .order_by(
            Interview.scheduled_at.desc()
        )
        .all()
    )

    return [
        {
            "interview_id": interview.id,
            "candidate_id": interview.candidate_id,
            "candidate_name": interview.candidate_name,
            "candidate_email": interview.candidate_email,
            "latest_role": interview.latest_role,
            "scheduled_at": interview.scheduled_at,
            "completed_at": interview.completed_at,
            "status": interview.status,
            "meet_link": interview.meet_link,
            "recording_available": (
                interview.recording_path is not None
            ),
            "transcript_available": (
                interview.transcript_path is not None
            ),
            "score": interview.overall_score,
        }
        for interview in interviews
    ]


# ============================================================
# RECENT CANDIDATES
# ============================================================

@router.get("/candidates")
def get_dashboard_candidates(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    candidates = (
        db.query(Candidate)
        .order_by(
            Candidate.created_at.desc()
        )
        .limit(10)
        .all()
    )

    return [
        {
            "id": candidate.id,
            "name": candidate.name,
            "email": candidate.email,
            "phone": candidate.phone,
            "latest_role": candidate.latest_role,
            "latest_company": candidate.latest_company,
            "resume_uploaded": (
                candidate.resume_path is not None
            ),
            "created_at": candidate.created_at,
        }
        for candidate in candidates
    ]


# ============================================================
# COMPLETED INTERVIEWS WITH EVALUATIONS
# ============================================================

@router.get("/evaluations")
def get_dashboard_evaluations(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    evaluations = (
        db.query(
            Interview.id.label(
                "interview_id"
            ),
            Interview.completed_at,
            Candidate.id.label(
                "candidate_id"
            ),
            Candidate.name.label(
                "candidate_name"
            ),
            Candidate.email.label(
                "candidate_email"
            ),
            Evaluation.id.label(
                "evaluation_id"
            ),
            Evaluation.overall_score,
        )
        .join(
            Candidate,
            Interview.candidate_id == Candidate.id,
        )
        .join(
            Evaluation,
            Evaluation.interview_id == Interview.id,
        )
        .filter(
            Interview.status == "completed"
        )
        .order_by(
            Interview.completed_at.desc()
        )
        .all()
    )

    return [
        {
            "interview_id": item.interview_id,
            "evaluation_id": item.evaluation_id,
            "candidate_id": item.candidate_id,
            "candidate_name": item.candidate_name,
            "candidate_email": item.candidate_email,
            "completed_at": item.completed_at,
            "score": item.overall_score,
        }
        for item in evaluations
    ]


# ============================================================
# DASHBOARD OVERVIEW
# ============================================================

@router.get("/overview")
def get_dashboard_overview(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    total_candidates = (
        db.query(func.count(Candidate.id))
        .scalar()
        or 0
    )

    total_interviews = (
        db.query(func.count(Interview.id))
        .scalar()
        or 0
    )

    completed_interviews = (
        db.query(func.count(Interview.id))
        .filter(
            Interview.status == "completed"
        )
        .scalar()
        or 0
    )

    scheduled_interviews = (
        db.query(func.count(Interview.id))
        .filter(
            Interview.status == "scheduled"
        )
        .scalar()
        or 0
    )

    pending_evaluation = (
        db.query(func.count(Interview.id))
        .outerjoin(
            Evaluation,
            Evaluation.interview_id == Interview.id,
        )
        .filter(
            Interview.status == "completed",
            Evaluation.id.is_(None),
        )
        .scalar()
        or 0
    )

    average_score = (
        db.query(
            func.avg(Evaluation.overall_score)
        )
        .scalar()
    )

    return {
        "total_candidates": total_candidates,
        "total_interviews": total_interviews,
        "scheduled_interviews": scheduled_interviews,
        "completed_interviews": completed_interviews,
        "pending_evaluation": pending_evaluation,
        "average_score": (
            round(float(average_score), 2)
            if average_score is not None
            else None
        ),
    }