from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.evaluation import Evaluation
from app.models.interview import Interview
from app.schemas.evaluation import EvaluationCreate, EvaluationResponse


router = APIRouter(
    prefix="/api/evaluations",
    tags=["Evaluations"],
)


# ============================================================
# CREATE EVALUATION
# ============================================================

@router.post("/", response_model=EvaluationResponse)
def create_evaluation(
    evaluation: EvaluationCreate,
    db: Session = Depends(get_db),
):
    interview = (
        db.query(Interview)
        .filter(Interview.id == evaluation.interview_id)
        .first()
    )

    if not interview:
        raise HTTPException(
            status_code=404,
            detail="Interview not found",
        )

    existing_evaluation = (
        db.query(Evaluation)
        .filter(
            Evaluation.interview_id == evaluation.interview_id
        )
        .first()
    )

    if existing_evaluation:
        raise HTTPException(
            status_code=400,
            detail="Evaluation already exists for this interview",
        )

    new_evaluation = Evaluation(
        interview_id=evaluation.interview_id,
        communication=evaluation.communication,
        confidence=evaluation.confidence,
        sales_knowledge=evaluation.sales_knowledge,
        lead_qualification=evaluation.lead_qualification,
        objection_handling=evaluation.objection_handling,
        persuasion=evaluation.persuasion,
        closing_ability=evaluation.closing_ability,
        overall_score=evaluation.overall_score,
        recommendation=evaluation.recommendation,
        strengths=evaluation.strengths,
        weaknesses=evaluation.weaknesses,
    )

    db.add(new_evaluation)
    db.commit()
    db.refresh(new_evaluation)

    return new_evaluation


# ============================================================
# GET ALL EVALUATIONS
# ============================================================

@router.get("/", response_model=list[EvaluationResponse])
def get_evaluations(
    db: Session = Depends(get_db),
):
    return (
        db.query(Evaluation)
        .order_by(Evaluation.id.desc())
        .all()
    )


# ============================================================
# GET ONE EVALUATION
# ============================================================

@router.get("/{evaluation_id}", response_model=EvaluationResponse)
def get_evaluation(
    evaluation_id: int,
    db: Session = Depends(get_db),
):
    evaluation = (
        db.query(Evaluation)
        .filter(Evaluation.id == evaluation_id)
        .first()
    )

    if not evaluation:
        raise HTTPException(
            status_code=404,
            detail="Evaluation not found",
        )

    return evaluation


# ============================================================
# UPDATE EVALUATION
# ============================================================

@router.put("/{evaluation_id}", response_model=EvaluationResponse)
def update_evaluation(
    evaluation_id: int,
    evaluation_data: EvaluationCreate,
    db: Session = Depends(get_db),
):
    evaluation = (
        db.query(Evaluation)
        .filter(Evaluation.id == evaluation_id)
        .first()
    )

    if not evaluation:
        raise HTTPException(
            status_code=404,
            detail="Evaluation not found",
        )

    evaluation.communication = evaluation_data.communication
    evaluation.confidence = evaluation_data.confidence
    evaluation.sales_knowledge = evaluation_data.sales_knowledge
    evaluation.lead_qualification = evaluation_data.lead_qualification
    evaluation.objection_handling = evaluation_data.objection_handling
    evaluation.persuasion = evaluation_data.persuasion
    evaluation.closing_ability = evaluation_data.closing_ability
    evaluation.overall_score = evaluation_data.overall_score
    evaluation.recommendation = evaluation_data.recommendation
    evaluation.strengths = evaluation_data.strengths
    evaluation.weaknesses = evaluation_data.weaknesses

    db.commit()
    db.refresh(evaluation)

    return evaluation


# ============================================================
# DELETE EVALUATION
# ============================================================

@router.delete("/{evaluation_id}")
def delete_evaluation(
    evaluation_id: int,
    db: Session = Depends(get_db),
):
    evaluation = (
        db.query(Evaluation)
        .filter(Evaluation.id == evaluation_id)
        .first()
    )

    if not evaluation:
        raise HTTPException(
            status_code=404,
            detail="Evaluation not found",
        )

    db.delete(evaluation)
    db.commit()

    return {
        "message": "Evaluation deleted successfully",
        "evaluation_id": evaluation_id,
    }