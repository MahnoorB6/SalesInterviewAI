import os
import uuid

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
)
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.evaluation import Evaluation
from app.schemas.candidate import (
    CandidateCreate,
    CandidateResponse,
)

from app.services.resume_parser import (
    extract_resume_text,
    detect_latest_role,
)

from app.services.resume_analyzer import (
    analyze_resume,
)


router = APIRouter(
    prefix="/api/candidates",
    tags=["Candidates"],
)


# ============================================================
# RESUME STORAGE
# ============================================================

RESUME_DIR = os.path.join(
    "data",
    "resumes",
)

os.makedirs(
    RESUME_DIR,
    exist_ok=True,
)


ALLOWED_RESUME_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
}


# ============================================================
# CREATE CANDIDATE
# ============================================================

@router.post(
    "/",
    response_model=CandidateResponse,
)
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

@router.get(
    "/",
    response_model=list[CandidateResponse],
)
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

@router.get(
    "/{candidate_id}",
    response_model=CandidateResponse,
)
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

@router.put(
    "/{candidate_id}",
    response_model=CandidateResponse,
)
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
# UPLOAD / REPLACE RESUME
# ============================================================

@router.post(
    "/{candidate_id}/resume",
    response_model=CandidateResponse,
)
async def upload_resume(
    candidate_id: int,
    file: UploadFile = File(...),
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

    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="No resume file provided",
        )

    extension = os.path.splitext(
        file.filename
    )[1].lower()

    if extension not in ALLOWED_RESUME_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid resume format. "
                "Allowed formats: PDF, DOC, DOCX."
            ),
        )

    # --------------------------------------------------------
    # DELETE OLD RESUME
    # --------------------------------------------------------

    if candidate.resume_path:
        old_path = candidate.resume_path

        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass

    # --------------------------------------------------------
    # CREATE UNIQUE FILENAME
    # --------------------------------------------------------

    filename = (
        f"candidate_{candidate_id}_"
        f"{uuid.uuid4().hex}"
        f"{extension}"
    )

    file_path = os.path.join(
        RESUME_DIR,
        filename,
    )

    # --------------------------------------------------------
    # SAVE FILE
    # --------------------------------------------------------

    contents = await file.read()

    with open(file_path, "wb") as resume_file:
        resume_file.write(contents)

    candidate.resume_path = file_path

    # --------------------------------------------------------
    # EXTRACT RESUME TEXT
    # --------------------------------------------------------

    try:
        resume_text = extract_resume_text(
            file_path
        )

    except Exception as error:

        candidate.resume_text = None
        candidate.resume_analysis = None

        db.commit()

        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse resume: {str(error)}",
        )

    # --------------------------------------------------------
    # GEMINI RESUME ANALYSIS
    # --------------------------------------------------------

    try:
        analysis = analyze_resume(
            resume_text
        )

    except Exception as error:

        candidate.resume_text = None
        candidate.resume_analysis = None

        db.commit()

        raise HTTPException(
            status_code=500,
            detail=(
                f"Failed to analyze resume with Gemini: "
                f"{str(error)}"
            ),
        )

    # --------------------------------------------------------
    # FALLBACK DETERMINISTIC ROLE DETECTION
    # --------------------------------------------------------

    try:
        role_data = detect_latest_role(
            resume_text
        )

    except Exception:
        role_data = {
            "latest_role": None,
            "latest_company": None,
            "latest_role_start_date": None,
            "latest_role_end_date": None,
            "latest_role_description": None,
        }

    # --------------------------------------------------------
    # SAVE RESUME DATA
    # --------------------------------------------------------

    candidate.resume_text = resume_text

    # Save complete Gemini analysis
    candidate.resume_analysis = (
        analysis.model_dump()
    )

    # Use Gemini as the primary source for latest role
    candidate.latest_role = (
        analysis.latest_role
    )

    candidate.latest_company = (
        analysis.latest_company
    )

    candidate.latest_role_start_date = (
        analysis.start_date
    )

    candidate.latest_role_end_date = (
        analysis.end_date
    )

    # Store responsibilities as the role description
    candidate.latest_role_description = (
        "\n".join(
            analysis.responsibilities
        )
        if analysis.responsibilities
        else role_data.get(
            "latest_role_description"
        )
    )

    # --------------------------------------------------------
    # SAVE DATABASE CHANGES
    # --------------------------------------------------------

    db.commit()
    db.refresh(candidate)

    return candidate


# ============================================================
# DELETE RESUME
# ============================================================

@router.delete(
    "/{candidate_id}/resume",
)
def delete_resume(
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

    if candidate.resume_path:

        if os.path.exists(candidate.resume_path):

            try:
                os.remove(candidate.resume_path)

            except OSError:
                pass

    candidate.resume_path = None
    candidate.resume_text = None
    candidate.resume_analysis = None
    candidate.latest_role = None
    candidate.latest_company = None
    candidate.latest_role_start_date = None
    candidate.latest_role_end_date = None
    candidate.latest_role_description = None

    db.commit()

    return {
        "message": "Resume deleted successfully",
        "candidate_id": candidate_id,
    }


# ============================================================
# DELETE CANDIDATE
# ============================================================

@router.delete(
    "/{candidate_id}",
)
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

    # --------------------------------------------------------
    # DELETE RESUME FILE
    # --------------------------------------------------------

    if candidate.resume_path:

        if os.path.exists(candidate.resume_path):

            try:
                os.remove(candidate.resume_path)

            except OSError:
                pass

    # --------------------------------------------------------
    # FIND INTERVIEWS
    # --------------------------------------------------------

    interviews = (
        db.query(Interview)
        .filter(
            Interview.candidate_id == candidate_id
        )
        .all()
    )

    # --------------------------------------------------------
    # DELETE EVALUATIONS + INTERVIEWS
    # --------------------------------------------------------

    for interview in interviews:

        evaluation = (
            db.query(Evaluation)
            .filter(
                Evaluation.interview_id == interview.id
            )
            .first()
        )

        if evaluation:
            db.delete(evaluation)

        db.delete(interview)

    # --------------------------------------------------------
    # DELETE CANDIDATE
    # --------------------------------------------------------

    db.delete(candidate)

    db.commit()

    return {
        "message": (
            "Candidate and related records "
            "deleted successfully"
        ),
        "candidate_id": candidate_id,
    }