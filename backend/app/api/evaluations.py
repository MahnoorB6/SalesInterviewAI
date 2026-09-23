import json
import os

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.database import get_db

from app.models.evaluation import Evaluation
from app.models.interview import Interview
from app.models.interview_question import InterviewQuestion
from app.models.candidate import Candidate

from app.schemas.evaluation import (
    EvaluationCreate,
    EvaluationResponse,
)

from app.services.evaluation_service import evaluate_interview
from app.services.google_calendar import send_email


router = APIRouter(
    prefix="/api/evaluations",
    tags=["Evaluations"],
)


# ============================================================
# CREATE EVALUATION
# ============================================================

@router.post(
    "/",
    response_model=EvaluationResponse,
)
def create_evaluation(
    evaluation_data: EvaluationCreate,
    db: Session = Depends(get_db),
):
    evaluation = Evaluation(
        interview_id=evaluation_data.interview_id,

        communication=evaluation_data.communication,
        confidence=evaluation_data.confidence,
        sales_knowledge=evaluation_data.sales_knowledge,
        lead_qualification=evaluation_data.lead_qualification,
        objection_handling=evaluation_data.objection_handling,
        persuasion=evaluation_data.persuasion,
        closing_ability=evaluation_data.closing_ability,

        overall_score=evaluation_data.overall_score,

        result=evaluation_data.result,

        recommendation=evaluation_data.recommendation,

        strengths=evaluation_data.strengths,
        weaknesses=evaluation_data.weaknesses,

        question_scores=evaluation_data.question_scores,
    )

    db.add(evaluation)
    db.commit()
    db.refresh(evaluation)

    return evaluation


# ============================================================
# GENERATE RULE-BASED EVALUATION
# ============================================================

@router.post(
    "/{interview_id}/generate",
    response_model=EvaluationResponse,
)
def generate_evaluation(
    interview_id: int,
    db: Session = Depends(get_db),
):
    # ========================================================
    # LOAD INTERVIEW
    # ========================================================

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
            detail="Interview not found",
        )

    # ========================================================
    # INTERVIEW CAN BE COMPLETED OR IN PROGRESS
    # ========================================================

    interview_status = str(
        interview.status or ""
    ).strip().lower()

    if interview_status not in {
        "completed",
        "in_progress",
    }:
        raise HTTPException(
            status_code=400,
            detail=(
                "Only completed or in-progress interviews "
                "can be evaluated."
            ),
        )

    # ========================================================
    # CHECK TRANSCRIPT
    # ========================================================

    if not interview.transcript_path:
        raise HTTPException(
            status_code=400,
            detail=(
                "Transcript not available for this interview yet."
            ),
        )

    if not os.path.exists(
        interview.transcript_path
    ):
        raise HTTPException(
            status_code=404,
            detail="Transcript file not found.",
        )

    # ========================================================
    # READ TRANSCRIPT
    # ========================================================

    try:
        with open(
            interview.transcript_path,
            "r",
            encoding="utf-8",
        ) as transcript_file:

            transcript = transcript_file.read()

    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=f"Unable to read transcript: {error}",
        )

    if not transcript.strip():
        raise HTTPException(
            status_code=400,
            detail=(
                "Transcript is empty. "
                "Wait until transcript content is available "
                "and try again."
            ),
        )

    # ========================================================
    # LOAD INTERVIEW QUESTIONS
    # ========================================================

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

    if not questions:
        raise HTTPException(
            status_code=400,
            detail="No interview questions found.",
        )

    question_list = [
        {
            "question_number": question.question_number,
            "question": question.question,
        }
        for question in questions
    ]

    # ========================================================
    # LOAD CANDIDATE
    # ========================================================

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

    # ========================================================
    # OPTIONAL RESUME ANALYSIS
    # ========================================================

    resume_analysis = None

    if candidate.resume_analysis:

        resume_analysis = candidate.resume_analysis

        if isinstance(
            resume_analysis,
            str,
        ):

            try:

                resume_analysis = json.loads(
                    resume_analysis
                )

            except json.JSONDecodeError:

                resume_analysis = None

    # ========================================================
    # GENERATE RULE-BASED EVALUATION
    # ========================================================

    try:

        result = evaluate_interview(
            position=interview.position,
            resume_analysis=resume_analysis,
            interview_questions=question_list,
            transcript=transcript,
        )

    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=f"Evaluation failed: {error}",
        )

    # ========================================================
    # FIND EXISTING EVALUATION
    # ========================================================

    evaluation = (
        db.query(Evaluation)
        .filter(
            Evaluation.interview_id
            == interview_id
        )
        .first()
    )

    # ========================================================
    # QUESTION SCORES
    # ========================================================

    question_scores = result.get(
        "question_scores",
        [],
    )

    if len(question_scores) != len(
        question_list
    ):

        raise HTTPException(
            status_code=500,
            detail=(
                "Evaluation returned an incorrect "
                "number of question scores."
            ),
        )

    question_scores_json = json.dumps(
        question_scores
    )

    # ========================================================
    # STRENGTHS
    # ========================================================

    strengths = result.get(
        "strengths",
        [],
    )

    if isinstance(
        strengths,
        list,
    ):

        strengths_text = "\n".join(
            f"- {item}"
            for item in strengths
        )

    else:

        strengths_text = str(
            strengths
        )

    # ========================================================
    # WEAKNESSES
    # ========================================================

    weaknesses = result.get(
        "weaknesses",
        [],
    )

    if isinstance(
        weaknesses,
        list,
    ):

        weaknesses_text = "\n".join(
            f"- {item}"
            for item in weaknesses
        )

    else:

        weaknesses_text = str(
            weaknesses
        )

    # ========================================================
    # CREATE OR UPDATE EVALUATION
    # ========================================================

    if evaluation:

        evaluation.communication = result.get(
            "communication"
        )

        evaluation.confidence = result.get(
            "confidence"
        )

        evaluation.sales_knowledge = result.get(
            "sales_knowledge"
        )

        evaluation.lead_qualification = result.get(
            "lead_qualification"
        )

        evaluation.objection_handling = result.get(
            "objection_handling"
        )

        evaluation.persuasion = result.get(
            "persuasion"
        )

        evaluation.closing_ability = result.get(
            "closing_ability"
        )

        evaluation.overall_score = result.get(
            "overall_score"
        )

        evaluation.result = result.get(
            "result"
        )

        evaluation.recommendation = result.get(
            "recommendation"
        )

        evaluation.strengths = strengths_text

        evaluation.weaknesses = weaknesses_text

        evaluation.question_scores = (
            question_scores_json
        )

    else:

        evaluation = Evaluation(
            interview_id=interview_id,

            communication=result.get(
                "communication"
            ),

            confidence=result.get(
                "confidence"
            ),

            sales_knowledge=result.get(
                "sales_knowledge"
            ),

            lead_qualification=result.get(
                "lead_qualification"
            ),

            objection_handling=result.get(
                "objection_handling"
            ),

            persuasion=result.get(
                "persuasion"
            ),

            closing_ability=result.get(
                "closing_ability"
            ),

            overall_score=result.get(
                "overall_score"
            ),

            result=result.get(
                "result"
            ),

            recommendation=result.get(
                "recommendation"
            ),

            strengths=strengths_text,

            weaknesses=weaknesses_text,

            question_scores=question_scores_json,
        )

        db.add(evaluation)

    # ========================================================
    # SAVE
    # ========================================================

    db.commit()
    db.refresh(evaluation)

    return evaluation


# ============================================================
# GET ALL EVALUATIONS
# ============================================================

@router.get(
    "/",
    response_model=list[EvaluationResponse],
)
def get_all_evaluations(
    db: Session = Depends(get_db),
):
    evaluations = (
        db.query(Evaluation)
        .order_by(
            Evaluation.id.desc()
        )
        .all()
    )

    return evaluations


# ============================================================
# GET RECRUITER EVALUATION DETAILS
# ============================================================

@router.get(
    "/interview/{interview_id}/details",
)
def get_recruiter_evaluation_details(
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
            detail="Interview not found",
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
            detail="Candidate not found",
        )

    evaluation = (
        db.query(Evaluation)
        .filter(
            Evaluation.interview_id == interview_id
        )
        .first()
    )

    if not evaluation:
        raise HTTPException(
            status_code=404,
            detail="Evaluation not found for this interview",
        )

    question_scores = []

    if evaluation.question_scores:

        try:

            question_scores = json.loads(
                evaluation.question_scores
            )

        except json.JSONDecodeError:

            question_scores = []

    return {
        "interview": {
            "id": interview.id,
            "candidate_id": interview.candidate_id,
            "position": interview.position,
            "scheduled_at": interview.scheduled_at,
            "status": interview.status,
            "recording_path": interview.recording_path,
            "transcript_path": interview.transcript_path,
            "completed_at": interview.completed_at,
        },

        "candidate": {
            "id": candidate.id,
            "name": candidate.name,
            "email": candidate.email,
            "phone": candidate.phone,

            "latest_role": candidate.latest_role,

            "latest_company": (
                candidate.latest_company
            ),

            "latest_role_start_date": (
                candidate.latest_role_start_date
            ),

            "latest_role_end_date": (
                candidate.latest_role_end_date
            ),

            "latest_role_description": (
                candidate.latest_role_description
            ),
        },

        "evaluation": {
            "id": evaluation.id,

            "interview_id": (
                evaluation.interview_id
            ),

            "communication": (
                evaluation.communication
            ),

            "confidence": (
                evaluation.confidence
            ),

            "sales_knowledge": (
                evaluation.sales_knowledge
            ),

            "lead_qualification": (
                evaluation.lead_qualification
            ),

            "objection_handling": (
                evaluation.objection_handling
            ),

            "persuasion": (
                evaluation.persuasion
            ),

            "closing_ability": (
                evaluation.closing_ability
            ),

            "overall_score": (
                evaluation.overall_score
            ),

            "result": (
                evaluation.result
            ),

            "recommendation": (
                evaluation.recommendation
            ),

            "strengths": (
                evaluation.strengths
            ),

            "weaknesses": (
                evaluation.weaknesses
            ),

            "question_scores": (
                question_scores
            ),
        },
    }


# ============================================================
# RECRUITER APPROVE EVALUATION
# ============================================================

@router.post(
    "/{evaluation_id}/approve",
)
def approve_evaluation(
    evaluation_id: int,
    db: Session = Depends(get_db),
):
    evaluation = (
        db.query(Evaluation)
        .filter(
            Evaluation.id == evaluation_id
        )
        .first()
    )

    if not evaluation:
        raise HTTPException(
            status_code=404,
            detail="Evaluation not found",
        )

    interview = (
        db.query(Interview)
        .filter(
            Interview.id == evaluation.interview_id
        )
        .first()
    )

    if not interview:
        raise HTTPException(
            status_code=404,
            detail="Interview not found",
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
            detail="Candidate not found",
        )

    candidate_email = (
        str(candidate.email or "")
        .strip()
    )

    if not candidate_email:
        raise HTTPException(
            status_code=400,
            detail="Candidate does not have a valid email address.",
        )

    # --------------------------------------------------------
    # SEND EMAIL FIRST
    # --------------------------------------------------------

    email_subject = (
        "SalesInterviewAI - Interview Result"
    )

    email_body = f"""Dear {candidate.name},

Thank you for participating in the interview process.

We are pleased to inform you that you have been selected to move forward to the next stage of the recruitment process.

Interview Result: APPROVED
Overall Score: {evaluation.overall_score}/100

We will contact you with the next steps.

Best regards,
SalesInterviewAI
"""

    try:

        print(
            f"[EMAIL] Sending approval email "
            f"to {candidate_email}..."
        )

        email_result = send_email(
            recipient_email=candidate_email,
            subject=email_subject,
            body=email_body,
        )

        print(
            f"[EMAIL] Approval email sent successfully "
            f"to {candidate_email}. "
            f"Message ID: "
            f"{email_result.get('id') if isinstance(email_result, dict) else 'unknown'}"
        )

    except Exception as error:

        print(
            f"[EMAIL ERROR] Failed to send approval email "
            f"to {candidate_email}: {error}"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                f"Approval email could not be sent to "
                f"{candidate_email}: {error}"
            ),
        )

    # --------------------------------------------------------
    # UPDATE RECRUITER STATUS
    # --------------------------------------------------------

    evaluation.recruiter_status = "approved"

    evaluation.reviewed_at = datetime.now(
        timezone.utc
    )

    db.commit()
    db.refresh(evaluation)

    # --------------------------------------------------------
    # RESPONSE
    # --------------------------------------------------------

    return {
        "message": (
            "Evaluation approved and email sent successfully"
        ),
        "evaluation_id": evaluation.id,
        "recruiter_status": evaluation.recruiter_status,
        "reviewed_at": evaluation.reviewed_at,
        "email_sent_to": candidate_email,
        "email_message_id": (
            email_result.get("id")
            if isinstance(email_result, dict)
            else None
        ),
    }


# ============================================================
# RECRUITER REJECT EVALUATION
# ============================================================

@router.post(
    "/{evaluation_id}/reject",
)
def reject_evaluation(
    evaluation_id: int,
    db: Session = Depends(get_db),
):
    evaluation = (
        db.query(Evaluation)
        .filter(
            Evaluation.id == evaluation_id
        )
        .first()
    )

    if not evaluation:
        raise HTTPException(
            status_code=404,
            detail="Evaluation not found",
        )

    interview = (
        db.query(Interview)
        .filter(
            Interview.id == evaluation.interview_id
        )
        .first()
    )

    if not interview:
        raise HTTPException(
            status_code=404,
            detail="Interview not found",
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
            detail="Candidate not found",
        )

    candidate_email = (
        str(candidate.email or "")
        .strip()
    )

    if not candidate_email:
        raise HTTPException(
            status_code=400,
            detail="Candidate does not have a valid email address.",
        )

    # --------------------------------------------------------
    # SEND EMAIL FIRST
    # --------------------------------------------------------

    email_subject = (
        "SalesInterviewAI - Interview Result"
    )

    email_body = f"""Dear {candidate.name},

Thank you for taking the time to participate in the interview process.

After careful consideration, we regret to inform you that you have not been selected to move forward at this stage.

Interview Result: NOT SELECTED
Overall Score: {evaluation.overall_score}/100

We appreciate your time and interest in the opportunity and wish you the best in your future career.

Best regards,
SalesInterviewAI
"""

    try:

        print(
            f"[EMAIL] Sending rejection email "
            f"to {candidate_email}..."
        )

        email_result = send_email(
            recipient_email=candidate_email,
            subject=email_subject,
            body=email_body,
        )

        print(
            f"[EMAIL] Rejection email sent successfully "
            f"to {candidate_email}. "
            f"Message ID: "
            f"{email_result.get('id') if isinstance(email_result, dict) else 'unknown'}"
        )

    except Exception as error:

        print(
            f"[EMAIL ERROR] Failed to send rejection email "
            f"to {candidate_email}: {error}"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                f"Rejection email could not be sent to "
                f"{candidate_email}: {error}"
            ),
        )

    # --------------------------------------------------------
    # UPDATE RECRUITER STATUS
    # --------------------------------------------------------

    evaluation.recruiter_status = "rejected"

    evaluation.reviewed_at = datetime.now(
        timezone.utc
    )

    db.commit()
    db.refresh(evaluation)

    # --------------------------------------------------------
    # RESPONSE
    # --------------------------------------------------------

    return {
        "message": (
            "Evaluation rejected and email sent successfully"
        ),
        "evaluation_id": evaluation.id,
        "recruiter_status": evaluation.recruiter_status,
        "reviewed_at": evaluation.reviewed_at,
        "email_sent_to": candidate_email,
        "email_message_id": (
            email_result.get("id")
            if isinstance(email_result, dict)
            else None
        ),
    }


# ============================================================
# GET ONE EVALUATION
# ============================================================

@router.get(
    "/{evaluation_id}",
    response_model=EvaluationResponse,
)
def get_evaluation(
    evaluation_id: int,
    db: Session = Depends(get_db),
):
    evaluation = (
        db.query(Evaluation)
        .filter(
            Evaluation.id == evaluation_id
        )
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

@router.put(
    "/{evaluation_id}",
    response_model=EvaluationResponse,
)
def update_evaluation(
    evaluation_id: int,
    evaluation_data: EvaluationCreate,
    db: Session = Depends(get_db),
):
    evaluation = (
        db.query(Evaluation)
        .filter(
            Evaluation.id == evaluation_id
        )
        .first()
    )

    if not evaluation:
        raise HTTPException(
            status_code=404,
            detail="Evaluation not found",
        )

    evaluation.interview_id = (
        evaluation_data.interview_id
    )

    evaluation.communication = (
        evaluation_data.communication
    )

    evaluation.confidence = (
        evaluation_data.confidence
    )

    evaluation.sales_knowledge = (
        evaluation_data.sales_knowledge
    )

    evaluation.lead_qualification = (
        evaluation_data.lead_qualification
    )

    evaluation.objection_handling = (
        evaluation_data.objection_handling
    )

    evaluation.persuasion = (
        evaluation_data.persuasion
    )

    evaluation.closing_ability = (
        evaluation_data.closing_ability
    )

    evaluation.overall_score = (
        evaluation_data.overall_score
    )

    evaluation.result = (
        evaluation_data.result
    )

    evaluation.recommendation = (
        evaluation_data.recommendation
    )

    evaluation.strengths = (
        evaluation_data.strengths
    )

    evaluation.weaknesses = (
        evaluation_data.weaknesses
    )

    evaluation.question_scores = (
        evaluation_data.question_scores
    )

    db.commit()
    db.refresh(evaluation)

    return evaluation


# ============================================================
# DELETE EVALUATION
# ============================================================

@router.delete(
    "/{evaluation_id}",
)
def delete_evaluation(
    evaluation_id: int,
    db: Session = Depends(get_db),
):
    evaluation = (
        db.query(Evaluation)
        .filter(
            Evaluation.id == evaluation_id
        )
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