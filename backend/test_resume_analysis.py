import sys

from app.database.database import SessionLocal
from app.models.candidate import Candidate
from app.services.resume_analyzer import analyze_resume


candidate_id = (
    int(sys.argv[1])
    if len(sys.argv) > 1
    else int(input("Enter candidate ID: "))
)

db = SessionLocal()

try:
    candidate = (
        db.query(Candidate)
        .filter(Candidate.id == candidate_id)
        .first()
    )

    if not candidate:
        print("Candidate not found.")
        raise SystemExit(1)

    if not candidate.resume_text:
        print("This candidate does not have extracted resume text.")
        raise SystemExit(1)

    print("\nAnalyzing resume with Gemini...\n")

    analysis = analyze_resume(candidate.resume_text)

    print("===== GEMINI RESUME ANALYSIS =====")
    print(analysis.model_dump_json(indent=2))
    print("==================================")

finally:
    db.close()
    