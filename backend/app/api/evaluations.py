import json
import os
import logging
import re
from typing import Literal

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database.database import get_db

from app.models.evaluation import Evaluation, EvaluationRun
from app.models.human_evaluation_label import HumanEvaluationLabel
from app.models.interview import Interview
from app.models.interview_question import InterviewQuestion
from app.models.candidate import Candidate

from app.schemas.evaluation import (
    EvaluationCreate,
    EvaluationResponse,
)
from app.schemas.human_evaluation_label import HumanEvaluationLabelCreate, HumanEvaluationLabelResponse

from app.services.evaluation_service import evaluate_interview
from app.services.google_calendar import send_email
from app.statuses import InterviewStatus
from app.auth import get_current_user
from app.transcripts import transcript_path_for
from app.models.user import User
from app.services.evaluation_rubric import COMPETENCY_BY_KEY


router = APIRouter(
    prefix="/api/evaluations",
    tags=["Evaluations"],
    dependencies=[Depends(get_current_user)],
)
logger = logging.getLogger(__name__)
MAX_TRANSCRIPT_UPLOAD_BYTES = 5 * 1024 * 1024


class RecruiterDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    contact_email: str = Field(min_length=3, max_length=254)
    contact_name: str | None = Field(default=None, max_length=150)
    transcript_name: str | None = Field(default=None, max_length=255)
    overall_score: float | None = Field(default=None, ge=0, le=100)


def _send_recruiter_decision_email(
    *, recipient: str, contact_name: str, decision: str,
    overall_score: float | None, transcript_name: str | None = None,
):
    email = recipient.strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(status_code=422, detail="Enter a valid recipient email address.")
    approved = decision == "approved"
    outcome = "selected to move forward" if approved else "not selected to move forward at this stage"
    result_label = "APPROVED" if approved else "NOT SELECTED"
    score_line = f"Overall Score: {overall_score}/100\n" if overall_score is not None else ""
    transcript_line = f"Transcript reviewed: {transcript_name}\n" if transcript_name else ""
    body = (
        f"Dear {contact_name or 'Candidate'},\n\n"
        "Thank you for participating in the interview process.\n\n"
        f"We are pleased to inform you that you have been {outcome}.\n\n"
        f"Interview Result: {result_label}\n{score_line}{transcript_line}\n"
        "Best regards,\nSalesInterviewAI\n"
    ) if approved else (
        f"Dear {contact_name or 'Candidate'},\n\n"
        "Thank you for taking the time to participate in the interview process.\n\n"
        f"After careful consideration, we regret to inform you that you have been {outcome}.\n\n"
        f"Interview Result: {result_label}\n{score_line}{transcript_line}\n"
        "We appreciate your time and interest in the opportunity and wish you the best in your future career.\n\n"
        "Best regards,\nSalesInterviewAI\n"
    )
    try:
        result = send_email(
            recipient_email=email,
            subject="SalesInterviewAI - Interview Result",
            body=body,
        )
    except Exception as error:
        logger.warning("Recruiter decision email failed (%s)", type(error).__name__)
        raise HTTPException(status_code=502, detail="The decision was not emailed. Check the email connection and try again.") from error
    return email, result


@router.post("/transcript-decision")
def decide_standalone_transcript(payload: RecruiterDecisionRequest):
    recipient, email_result = _send_recruiter_decision_email(
        recipient=payload.contact_email,
        contact_name=payload.contact_name or "Candidate",
        decision=payload.decision,
        overall_score=payload.overall_score,
        transcript_name=payload.transcript_name,
    )
    return {
        "message": f"Decision email sent to {recipient}.",
        "recruiter_status": payload.decision,
        "email_sent_to": recipient,
        "email_message_id": email_result.get("id") if isinstance(email_result, dict) else None,
    }


@router.post("/{evaluation_id}/recruiter-decision")
def decide_saved_evaluation(
    payload: RecruiterDecisionRequest,
    evaluation_id: int = Path(gt=0),
    db: Session = Depends(get_db),
):
    evaluation = (
        db.query(Evaluation)
        .filter(Evaluation.id == evaluation_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    if evaluation.recruiter_status not in (None, "pending"):
        raise HTTPException(status_code=409, detail=f"Evaluation already has the {evaluation.recruiter_status} decision")
    interview = db.query(Interview).filter(Interview.id == evaluation.interview_id).first()
    candidate = db.query(Candidate).filter(Candidate.id == interview.candidate_id).first() if interview else None
    recipient = payload.contact_email or (candidate.email if candidate else "")
    name = payload.contact_name or (candidate.name if candidate else "Candidate")
    email_sent_to, email_result = _send_recruiter_decision_email(
        recipient=recipient,
        contact_name=name,
        decision=payload.decision,
        overall_score=evaluation.overall_score,
    )
    evaluation.recruiter_status = payload.decision
    evaluation.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(evaluation)
    return {
        "message": f"Decision recorded and email sent to {email_sent_to}.",
        "evaluation_id": evaluation.id,
        "recruiter_status": evaluation.recruiter_status,
        "reviewed_at": evaluation.reviewed_at,
        "email_sent_to": email_sent_to,
        "email_message_id": email_result.get("id") if isinstance(email_result, dict) else None,
    }


@router.post("/transcript-file")
async def evaluate_transcript_file(file: UploadFile = File(...)):
    """Evaluate a recruiter-provided TXT transcript without linking a candidate."""
    if not file.filename or not file.filename.lower().endswith(".txt"):
        raise HTTPException(status_code=400, detail="Choose a .txt transcript file.")
    content = await file.read(MAX_TRANSCRIPT_UPLOAD_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="The selected transcript file is empty.")
    if len(content) > MAX_TRANSCRIPT_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Transcript must be 5 MB or smaller.")
    try:
        transcript = content.decode("utf-8-sig").strip()
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Transcript must be a UTF-8 text file.")
    if not transcript:
        raise HTTPException(status_code=400, detail="The selected transcript file contains no text.")

    turns: list[tuple[str, str]] = []
    current_role: str | None = None
    current_text: list[str] = []

    def save_turn() -> None:
        text = " ".join(current_text).strip()
        if current_role and text:
            turns.append((current_role, text))

    role_pattern = re.compile(
        r"^\s*(?:\[[^\]]+\]\s*)?(?:\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}\s*)?"
        r"([A-Za-z][A-Za-z _-]*?\d*)\s*:\s*(.*)$"
    )
    for line in transcript.splitlines():
        match = role_pattern.match(line)
        if match:
            save_turn()
            label = re.sub(r"[_-]+", " ", match.group(1)).strip().lower()
            if re.fullmatch(r"(?:q|question)\s*\d*", label):
                current_role = "interviewer"
            elif re.fullmatch(r"(?:a|answer)\s*\d*", label):
                current_role = "candidate"
            elif any(token in label for token in ("interviewer", "alena", "agent", "assistant", "host", "chatbot")) or label in {"ai", "bot"}:
                current_role = "interviewer"
            elif any(token in label for token in ("candidate", "applicant", "respondent", "sales rep")) or label in {"user", "answer", "a"} or label.startswith("speaker 0"):
                current_role = "candidate"
            elif label.startswith("speaker 1"):
                current_role = "interviewer"
            else:
                current_role = None
            current_text = [match.group(2).strip()]
        elif current_role and line.strip():
            current_text.append(line.strip())
        else:
            save_turn()
            current_role = None
            current_text = []
    save_turn()

    # Also accept plain Q/A transcripts where prompts and answers are on separate lines.
    if not any(role == "interviewer" for role, _ in turns):
        plain_turns = []
        for line in transcript.splitlines():
            text = line.strip()
            if not text or set(text) <= {"=", "-", "_"}:
                continue
            plain_turns.append(("interviewer" if "?" in text else "candidate", text))
        if any(role == "interviewer" for role, _ in plain_turns):
            turns = plain_turns

    questions = []
    normalized_turns = []
    for role, text in turns:
        if role == "interviewer":
            prompt = text if "?" in text else f"{text}?"
            questions.append({"question_number": len(questions) + 1, "question": prompt})
            normalized_turns.append(f"INTERVIEWER: {prompt}")
        else:
            normalized_turns.append(f"CANDIDATE: {text}")

    if not questions:
        raise HTTPException(
            status_code=400,
            detail="Could not identify interview questions in this transcript. Use speaker labels (including timestamps) or put each question on its own line ending with a question mark.",
        )
    try:
        result = evaluate_interview(transcript="\n".join(normalized_turns), interview_questions=questions)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception:
        logger.exception("Transcript-file evaluation failed")
        raise HTTPException(status_code=500, detail="Evaluation could not be generated from this transcript.")

    profiles = result["competencies"]
    return {
        "transcript_name": file.filename,
        "overall_score": result["overall_score"],
        **{key: profiles[key]["score_out_of_100"] for key in ("communication", "confidence", "sales_knowledge", "lead_qualification", "objection_handling", "persuasion", "closing_ability")},
        "recommendation": result["recommendation"],
        "strengths": "\\n".join(result["strengths"]),
        "weaknesses": "\\n".join(result["weaknesses"]),
        "evaluation_status": result["evaluation_status"],
        "rubric_version": result["rubric_version"],
        "evaluator_version": result["evaluator_version"],
        "evaluation_method": result["evaluation_method"],
        "structured_result": result,
    }


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
    interview = db.query(Interview).filter(Interview.id == evaluation_data.interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    if interview.status not in {InterviewStatus.COMPLETED.value, InterviewStatus.INTERRUPTED.value}:
        raise HTTPException(status_code=409, detail="Only completed or interrupted interviews can be evaluated")
    if db.query(Evaluation).filter(Evaluation.interview_id == interview.id).first():
        raise HTTPException(status_code=409, detail="An evaluation already exists for this interview")
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

        result=None,

        recommendation=evaluation_data.recommendation,

        strengths=evaluation_data.strengths,
        weaknesses=evaluation_data.weaknesses,

        question_scores=evaluation_data.question_scores,
        evaluation_status="manual_unverified",
        rubric_version="unknown",
        evaluator_version="manual_input",
        evaluation_method="manual_legacy",
    )

    db.add(evaluation)
    db.commit()
    db.refresh(evaluation)

    return evaluation


# ============================================================
# GENERATE EVIDENCE-BASED EVALUATION
# ============================================================

@router.post(
    "/{interview_id}/generate",
    response_model=EvaluationResponse,
)
def generate_evaluation(
    interview_id: int = Path(gt=0),
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

    interview_status = str(
        interview.status or ""
    ).strip().lower()

    if interview_status not in {InterviewStatus.COMPLETED.value, InterviewStatus.INTERRUPTED.value}:
        raise HTTPException(
            status_code=400,
            detail=(
                "Only completed or interrupted interviews "
                "can be evaluated."
            ),
        )

    # ========================================================
    # CHECK TRANSCRIPT
    # ========================================================

    transcript_path = transcript_path_for(interview)
    if not transcript_path:
        raise HTTPException(
            status_code=400,
            detail=(
                "Transcript not available for this interview yet."
            ),
        )

    if not transcript_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Transcript file not found.",
        )

    # ========================================================
    # READ TRANSCRIPT
    # ========================================================

    try:
        with open(transcript_path, "r", encoding="utf-8") as transcript_file:
            transcript = transcript_file.read()
    except OSError:
        logger.exception("Could not read transcript for interview %s", interview_id)
        raise HTTPException(status_code=500, detail="Transcript could not be read")

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

    evaluation = db.query(Evaluation).filter(Evaluation.interview_id == interview_id).first()
    if evaluation and evaluation.recruiter_status not in (None, "pending"):
        raise HTTPException(status_code=409, detail="A recruiter decision already exists; evaluated results are locked")

    question_list = [
        {
            "id": question.id,
            "question_number": question.question_number,
            "question": question.question,
            "category": question.category,
        }
        for question in questions
    ]
    try:
        result = evaluate_interview(
            transcript=transcript,
            interview_questions=question_list,
            interview_status=interview_status,
        )
    except Exception:
        logger.exception("Behavioral evaluation failed for interview %s", interview_id)
        raise HTTPException(status_code=500, detail="Evaluation could not be generated")

    strengths_text = "\n".join(result["strengths"])
    weaknesses_text = "\n".join(result["weaknesses"])
    question_scores_json = json.dumps(result["question_evaluations"], ensure_ascii=False)

    if evaluation and evaluation.structured_result is None and any(
        value is not None for value in (evaluation.overall_score, evaluation.communication, evaluation.question_scores)
    ):
        legacy_snapshot = {
            "legacy_result": {
                "overall_score": evaluation.overall_score,
                "competencies_out_of_100": {
                    key: getattr(evaluation, key)
                    for key in ("communication", "confidence", "sales_knowledge", "lead_qualification", "objection_handling", "persuasion", "closing_ability")
                },
                "question_scores": evaluation.question_scores,
                "result": evaluation.result,
            },
            "notice": "Legacy evaluation imported without recoverable rubric or evidence provenance.",
        }
        db.add(EvaluationRun(
            evaluation=evaluation,
            structured_result=legacy_snapshot,
            rubric_version=evaluation.rubric_version or "legacy_unknown",
            evaluator_version=evaluation.evaluator_version or "legacy_unknown",
            evaluation_method=evaluation.evaluation_method or "legacy_unknown",
        ))

    if evaluation is None:
        evaluation = Evaluation(interview_id=interview_id, recruiter_status="pending")
        db.add(evaluation)

    profiles = result["competencies"]
    for key in ("communication", "confidence", "sales_knowledge", "lead_qualification", "objection_handling", "persuasion", "closing_ability"):
        setattr(evaluation, key, profiles[key]["score_out_of_100"])
    evaluation.overall_score = result["overall_score"]
    evaluation.result = None  # Automated rubric output is not an approve/reject decision.
    evaluation.recommendation = result["recommendation"]
    evaluation.strengths = strengths_text
    evaluation.weaknesses = weaknesses_text
    evaluation.question_scores = question_scores_json
    evaluation.structured_result = result
    evaluation.evaluation_status = result["evaluation_status"]
    evaluation.rubric_version = result["rubric_version"]
    evaluation.evaluator_version = result["evaluator_version"]
    evaluation.evaluation_method = result["evaluation_method"]
    db.flush()
    db.add(EvaluationRun(
        evaluation=evaluation,
        structured_result=result,
        rubric_version=result["rubric_version"],
        evaluator_version=result["evaluator_version"],
        evaluation_method=result["evaluation_method"],
    ))
    db.commit()
    db.refresh(evaluation)
    return evaluation


@router.post("/labels", response_model=HumanEvaluationLabelResponse, status_code=201)
def create_human_evaluation_label(
    payload: HumanEvaluationLabelCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    competency = COMPETENCY_BY_KEY.get(payload.competency)
    if not competency or payload.criterion not in {criterion.key for criterion in competency.criteria}:
        raise HTTPException(status_code=422, detail="Criterion does not belong to the requested competency")
    question = db.query(InterviewQuestion).filter(InterviewQuestion.id == payload.interview_question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Interview question not found")
    evaluation = db.query(Evaluation).filter(Evaluation.interview_id == question.interview_id).first()
    if not evaluation or not evaluation.structured_result:
        raise HTTPException(status_code=409, detail="Generate a structured evaluation before adding a human label")
    question_result = next(
        (item for item in evaluation.structured_result.get("question_evaluations", []) if item.get("question_id") == question.id),
        None,
    )
    if not question_result or not question_result.get("candidate_answer"):
        raise HTTPException(status_code=409, detail="No candidate answer is aligned to this interview question")
    if payload.evidence_span not in question_result["candidate_answer"]:
        raise HTTPException(status_code=422, detail="Evidence span must be copied exactly from the aligned candidate answer")
    duplicate = db.query(HumanEvaluationLabel).filter(
        HumanEvaluationLabel.interview_question_id == question.id,
        HumanEvaluationLabel.criterion == payload.criterion,
        HumanEvaluationLabel.rater_id == current_user.id,
        HumanEvaluationLabel.rubric_version == evaluation.rubric_version,
    ).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="You have already labeled this criterion for this question and rubric version")
    label = HumanEvaluationLabel(
        interview_id=question.interview_id,
        interview_question_id=question.id,
        question=question.question,
        candidate_answer=question_result["candidate_answer"],
        competency=payload.competency,
        criterion=payload.criterion,
        rating=payload.rating,
        evidence_span=payload.evidence_span,
        rater_id=current_user.id,
        rubric_version=evaluation.rubric_version or "unknown",
        transcript_quality=payload.transcript_quality,
        adjudication_status="pending",
    )
    db.add(label)
    db.commit()
    db.refresh(label)
    return label


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
    interview_id: int = Path(gt=0),
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
            "recording_available": bool(interview.recording_path),
            "transcript_available": bool(interview.transcript_path),
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
            "structured_result": evaluation.structured_result,
            "evaluation_status": evaluation.evaluation_status,
            "rubric_version": evaluation.rubric_version,
            "evaluator_version": evaluation.evaluator_version,
            "evaluation_method": evaluation.evaluation_method,
            "runs": [
                {
                    "id": run.id,
                    "evaluation_id": run.evaluation_id,
                    "structured_result": run.structured_result,
                    "rubric_version": run.rubric_version,
                    "evaluator_version": run.evaluator_version,
                    "evaluation_method": run.evaluation_method,
                    "created_at": run.created_at,
                }
                for run in evaluation.runs
            ],
        },
    }


# ============================================================
# RECRUITER APPROVE EVALUATION
# ============================================================

@router.post(
    "/{evaluation_id}/approve",
)
def approve_evaluation(
    evaluation_id: int = Path(gt=0),
    db: Session = Depends(get_db),
):
    evaluation = (
        db.query(Evaluation)
        .filter(Evaluation.id == evaluation_id)
        .with_for_update()
        .populate_existing()
        .first()
    )

    if not evaluation:
        raise HTTPException(
            status_code=404,
            detail="Evaluation not found",
        )

    if evaluation.structured_result is not None:
        raise HTTPException(status_code=409, detail="Structured evaluations are immutable; regenerate through the evaluation engine")

    if evaluation.recruiter_status not in (None, "pending"):
        raise HTTPException(status_code=409, detail=f"Evaluation already has the {evaluation.recruiter_status} decision")

    # Persist the decision before sending mail so retries cannot send duplicates.
    evaluation.recruiter_status = "approved"
    evaluation.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(evaluation)

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

        email_result = send_email(
            recipient_email=candidate_email,
            subject=email_subject,
            body=email_body,
        )

    except Exception as error:

        logger.warning("Approval notification failed for evaluation %s (%s)", evaluation_id, type(error).__name__)
        raise HTTPException(status_code=502, detail="Recruiter decision was recorded, but the candidate email could not be sent. Contact the candidate manually.")

    # --------------------------------------------------------
    # UPDATE RECRUITER STATUS
    # --------------------------------------------------------


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
    evaluation_id: int = Path(gt=0),
    db: Session = Depends(get_db),
):
    evaluation = (
        db.query(Evaluation)
        .filter(Evaluation.id == evaluation_id)
        .with_for_update()
        .populate_existing()
        .first()
    )

    if not evaluation:
        raise HTTPException(
            status_code=404,
            detail="Evaluation not found",
        )

    if evaluation.recruiter_status not in (None, "pending"):
        raise HTTPException(status_code=409, detail=f"Evaluation already has the {evaluation.recruiter_status} decision")

    # Persist the decision before sending mail so retries cannot send duplicates.
    evaluation.recruiter_status = "rejected"
    evaluation.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(evaluation)

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

        email_result = send_email(
            recipient_email=candidate_email,
            subject=email_subject,
            body=email_body,
        )

    except Exception as error:

        logger.warning("Rejection notification failed for evaluation %s (%s)", evaluation_id, type(error).__name__)
        raise HTTPException(status_code=502, detail="Recruiter decision was recorded, but the candidate email could not be sent. Contact the candidate manually.")

    # --------------------------------------------------------
    # UPDATE RECRUITER STATUS
    # --------------------------------------------------------


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
    evaluation_id: int = Path(gt=0),
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
    evaluation_data: EvaluationCreate,
    evaluation_id: int = Path(gt=0),
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

    if evaluation_data.interview_id != evaluation.interview_id:
        raise HTTPException(status_code=409, detail="An evaluation cannot be moved to a different interview")
    interview = db.query(Interview).filter(Interview.id == evaluation.interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    if interview.status not in {InterviewStatus.COMPLETED.value, InterviewStatus.INTERRUPTED.value}:
        raise HTTPException(status_code=409, detail="Only completed or interrupted interviews can be evaluated")

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
    evaluation.evaluation_status = "manual_unverified"
    evaluation.rubric_version = "unknown"
    evaluation.evaluator_version = "manual_input"
    evaluation.evaluation_method = "manual_legacy"
    evaluation.result = None

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
    evaluation_id: int = Path(gt=0),
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
