from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.evaluation import Evaluation
from app.schemas.candidate import CandidateCreate, CandidateResponse


router = APIRouter(
    prefix="/api/candidates",
    tags=["Candidates"],
)


# ============================================================
# CREATE CANDIDATE
# ============================================================

@router.post("/", response_model=CandidateResponse)
def create_candidate(
    candidate: CandidateCreate,
    db: Session = Depends(get_db),
):
    existing_candidate = (
        db.query(Candidate)
        .filter(Candidate.email == candidate.email)
        .first()
    )

    if existing_candidate:
        raise HTTPException(
            status_code=400,
            detail="A candidate with this email already exists",
        )

    new_candidate = Candidate(
        name=candidate.name,
        email=candidate.email,
        phone=candidate.phone,
    )

    db.add(new_candidate)
    db.commit()
    db.refresh(new_candidate)

    return new_candidate


# ============================================================
# GET ALL CANDIDATES
# ============================================================

@router.get("/", response_model=list[CandidateResponse])
def get_candidates(
    db: Session = Depends(get_db),
):
    return (
        db.query(Candidate)
        .order_by(Candidate.created_at.desc())
        .all()
    )


# ============================================================
# GET ONE CANDIDATE
# ============================================================

@router.get("/{candidate_id}", response_model=CandidateResponse)
def get_candidate(
    candidate_id: int,
    db: Session = Depends(get_db),
):
    candidate = (
        db.query(Candidate)
        .filter(Candidate.id == candidate_id)
        .first()
    )

    if not candidate:
        raise HTTPException(
            status_code=404,
            detail="Candidate not found",
        )

    return candidate


# ============================================================
# UPDATE CANDIDATE
# ============================================================

@router.put("/{candidate_id}", response_model=CandidateResponse)
def update_candidate(
    candidate_id: int,
    candidate_data: CandidateCreate,
    db: Session = Depends(get_db),
):
    candidate = (
        db.query(Candidate)
        .filter(Candidate.id == candidate_id)
        .first()
    )

    if not candidate:
        raise HTTPException(
            status_code=404,
            detail="Candidate not found",
        )

    duplicate = (
        db.query(Candidate)
        .filter(
            Candidate.email == candidate_data.email,
            Candidate.id != candidate_id,
        )
        .first()
    )

    if duplicate:
        raise HTTPException(
            status_code=400,
            detail="A candidate with this email already exists",
        )

    candidate.name = candidate_data.name
    candidate.email = candidate_data.email
    candidate.phone = candidate_data.phone

    db.commit()
    db.refresh(candidate)

    return candidate


# ============================================================
# DELETE CANDIDATE
# ============================================================

@router.delete("/{candidate_id}")
def delete_candidate(
    candidate_id: int,
    db: Session = Depends(get_db),
):
    candidate = (
        db.query(Candidate)
        .filter(Candidate.id == candidate_id)
        .first()
    )

    if not candidate:
        raise HTTPException(
            status_code=404,
            detail="Candidate not found",
        )

    # Find all interviews belonging to this candidate
    interviews = (
        db.query(Interview)
        .filter(Interview.candidate_id == candidate_id)
        .all()
    )

    # Delete evaluations and interviews first
    for interview in interviews:

        evaluation = (
            db.query(Evaluation)
            .filter(Evaluation.interview_id == interview.id)
            .first()
        )

        if evaluation:
            db.delete(evaluation)

        db.delete(interview)

    # Delete candidate
    db.delete(candidate)

    db.commit()

    return {
        "message": "Candidate and related records deleted successfully",
        "candidate_id": candidate_id,
    }