import os
import uuid
import logging
import tempfile
import zipfile

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    UploadFile,
    File,
)
from app.auth import get_current_user
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.candidate import Candidate
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
    dependencies=[Depends(get_current_user)],
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
    ".docx",
}
MAX_RESUME_BYTES = 10 * 1024 * 1024
logger = logging.getLogger(__name__)


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
    candidate_id: int = Path(gt=0),
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
    candidate_data: CandidateCreate,
    candidate_id: int = Path(gt=0),
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

@router.post("/{candidate_id}/resume", response_model=CandidateResponse)
async def upload_resume(candidate_id: int = Path(gt=0), file: UploadFile = File(...), db: Session = Depends(get_db)):
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    if not file.filename:
        raise HTTPException(status_code=400, detail="No resume file provided")
    extension = os.path.splitext(file.filename)[1].lower()
    if extension not in ALLOWED_RESUME_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Invalid resume format. Allowed formats: PDF and DOCX.")

    os.makedirs(RESUME_DIR, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=f"candidate_{candidate_id}_", suffix=extension, dir=RESUME_DIR)
    os.close(fd)
    final_path = None
    try:
        size, signature = 0, b""
        with open(temp_path, "wb") as target:
            while chunk := await file.read(64 * 1024):
                size += len(chunk)
                if size > MAX_RESUME_BYTES:
                    raise HTTPException(status_code=413, detail="Resume exceeds the 10 MB upload limit.")
                signature += chunk[: max(0, 8 - len(signature))]
                target.write(chunk)
        if not size:
            raise HTTPException(status_code=400, detail="Resume file is empty.")
        if extension == ".pdf" and not signature.startswith(b"%PDF-"):
            raise HTTPException(status_code=400, detail="File content does not match a PDF resume.")
        if extension == ".docx":
            if not signature.startswith(b"PK") or not zipfile.is_zipfile(temp_path):
                raise HTTPException(status_code=400, detail="File content does not match a DOCX resume.")
            with zipfile.ZipFile(temp_path) as archive:
                names = set(archive.namelist())
                if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                    raise HTTPException(status_code=400, detail="DOCX document structure is invalid.")
        try:
            resume_text = extract_resume_text(temp_path)
        except Exception as error:
            logger.info("Resume parsing rejected candidate %s (%s)", candidate_id, type(error).__name__)
            raise HTTPException(status_code=400, detail="Resume could not be parsed. Check that the PDF or DOCX is valid.") from error
        try:
            analysis = analyze_resume(resume_text)
        except Exception as error:
            logger.warning("Resume analysis failed for candidate %s (%s)", candidate_id, type(error).__name__)
            raise HTTPException(status_code=503, detail="Resume analysis is temporarily unavailable. The existing resume was preserved.") from error
        try:
            role_data = detect_latest_role(resume_text)
        except Exception:
            role_data = {"latest_role_description": None}

        final_path = os.path.join(RESUME_DIR, f"candidate_{candidate_id}_{uuid.uuid4().hex}{extension}")
        os.replace(temp_path, final_path)
        previous_path = candidate.resume_path
        candidate.resume_path = final_path
        candidate.resume_text = resume_text
        candidate.resume_analysis = analysis.model_dump()
        candidate.latest_role = analysis.latest_role
        candidate.latest_company = analysis.latest_company
        candidate.latest_role_start_date = analysis.start_date
        candidate.latest_role_end_date = analysis.end_date
        candidate.latest_role_description = "\n".join(analysis.responsibilities) if analysis.responsibilities else role_data.get("latest_role_description")
        try:
            db.commit()
            db.refresh(candidate)
        except Exception as error:
            db.rollback()
            logger.warning("Could not save resume data for candidate %s (%s)", candidate_id, type(error).__name__)
            raise HTTPException(status_code=500, detail="Could not save resume information.") from error
        if previous_path and os.path.abspath(previous_path) != os.path.abspath(final_path) and os.path.isfile(previous_path):
            try:
                os.remove(previous_path)
            except OSError:
                logger.warning("Could not remove replaced resume file")
        return candidate
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        if final_path and os.path.exists(final_path) and candidate.resume_path != final_path:
            os.remove(final_path)


# ============================================================
# DELETE RESUME
# ============================================================

@router.delete(
    "/{candidate_id}/resume",
)
def delete_resume(
    candidate_id: int = Path(gt=0),
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
    candidate_id: int = Path(gt=0),
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

    db.delete(candidate)

    db.commit()

    return {
        "message": (
            "Candidate and related records "
            "deleted successfully"
        ),
        "candidate_id": candidate_id,
    }
