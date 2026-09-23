import sys

from app.database.database import SessionLocal
from app.models.candidate import Candidate
from app.services.question_generator import generate_interview_questions


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

    if not candidate.resume_analysis:
        print(
            "This candidate does not have Gemini resume analysis."
        )
        raise SystemExit(1)

    print("\nGenerating personalized questions...\n")

    questions = generate_interview_questions(
        resume_analysis=candidate.resume_analysis,
        position="Sales Representative",
    )

    print("===== GENERATED INTERVIEW QUESTIONS =====")

    for item in questions:
        print(
            f"\n{item['question_number']}. "
            f"[{item['category']}]"
        )
        print(item["question"])

    print("\n==========================================")

finally:
    db.close()