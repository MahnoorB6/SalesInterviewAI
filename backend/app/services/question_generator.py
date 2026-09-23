
import json
import os

from dotenv import load_dotenv
from google import genai

load_dotenv()


def _get_resume_value(
    resume_analysis: dict,
    *keys,
    default="",
):
    """
    Safely get the first available value from resume_analysis.
    """

    if not isinstance(resume_analysis, dict):
        return default

    for key in keys:
        value = resume_analysis.get(key)

        if value is None:
            continue

        if isinstance(value, str):
            value = value.strip()

            if value:
                return value

        elif value:
            return value

    return default


def _generate_fallback_questions(
    resume_analysis: dict,
    position: str,
):
    """
    Local fallback question generation.

    This is used when Gemini is unavailable, returns invalid
    data, or fails validation.

    No external API call is made by this function.
    """

    latest_role = _get_resume_value(
        resume_analysis,
        "latest_role",
        "current_role",
        "role",
        default="the candidate's latest role",
    )

    latest_company = _get_resume_value(
        resume_analysis,
        "latest_company",
        "current_company",
        "company",
        default="their previous company",
    )

    role_description = _get_resume_value(
        resume_analysis,
        "latest_role_description",
        "role_description",
        "responsibilities",
        default=(
            "the responsibilities described on your resume"
        ),
    )

    skills = _get_resume_value(
        resume_analysis,
        "skills",
        "technical_skills",
        "key_skills",
        default=(
            "the skills listed on your resume"
        ),
    )

    achievements = _get_resume_value(
        resume_analysis,
        "achievements",
        "key_achievements",
        "accomplishments",
        default=(
            "the achievements listed on your resume"
        ),
    )

    questions = [
        {
            "question_number": 1,
            "question": (
                f"Can you describe your experience as a "
                f"{latest_role} and how it prepared you for "
                f"the {position} role?"
            ),
            "category": "role_specific",
        },
        {
            "question_number": 2,
            "question": (
                f"What were your main responsibilities at "
                f"{latest_company}, particularly those related "
                f"to sales and customer interactions?"
            ),
            "category": "role_specific",
        },
        {
            "question_number": 3,
            "question": (
                f"How did you approach achieving your sales "
                f"objectives in your role as {latest_role}?"
            ),
            "category": "role_specific",
        },
        {
            "question_number": 4,
            "question": (
                "Tell me about a challenging customer or sales "
                "situation you handled in your previous experience. "
                "What approach did you take?"
            ),
            "category": "role_specific",
        },
        {
            "question_number": 5,
            "question": (
                f"Your resume describes your responsibilities as "
                f"'{role_description}'. Which of these responsibilities "
                f"required the strongest sales or communication skills?"
            ),
            "category": "resume_specific",
        },
        {
            "question_number": 6,
            "question": (
                f"Your resume mentions {skills}. Can you give an "
                "example of how you used one of these skills in "
                "a professional situation?"
            ),
            "category": "resume_specific",
        },
        {
            "question_number": 7,
            "question": (
                f"Looking at your experience at {latest_company}, "
                f"which achievement or result are you most proud of, "
                f"and what did you personally contribute to it?"
            ),
            "category": "resume_specific",
        },
        {
            "question_number": 8,
            "question": (
                "How do you build trust and establish a strong "
                "relationship with a new customer?"
            ),
            "category": "hr",
        },
        {
            "question_number": 9,
            "question": (
                "How do you respond when a potential customer "
                "rejects your sales proposal or raises objections?"
            ),
            "category": "hr",
        },
        {
            "question_number": 10,
            "question": (
                "Why are you interested in this position, and what "
                "do you believe you can contribute to the sales team?"
            ),
            "category": "hr",
        },
    ]

    return questions


def generate_interview_questions(
    resume_analysis: dict,
    position: str = "Sales Representative",
):
    """
    Generate exactly 10 interview questions.

    Gemini is attempted only once.

    If Gemini is unavailable or returns invalid data,
    local fallback questions are returned instead.

    This prevents temporary Gemini failures from blocking
    interview creation and avoids repeated API calls.
    """

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        print("[GEMINI] GEMINI_API_KEY is not configured.")
        print("[GEMINI] Using fallback interview questions.")

        return _generate_fallback_questions(
            resume_analysis=resume_analysis,
            position=position,
        )

    try:
        client = genai.Client(api_key=api_key)
    except Exception as error:
        print(
            "[GEMINI] Client initialization failed: "
            f"{error}"
        )
        print("[GEMINI] Using fallback interview questions.")

        return _generate_fallback_questions(
            resume_analysis=resume_analysis,
            position=position,
        )

    prompt = f"""
You are an expert sales-interview designer.

Create a personalized interview for this candidate.

Position:
{position}

Candidate resume analysis:
{json.dumps(resume_analysis, indent=2)}

Generate exactly 10 interview questions.

Question distribution:

1. Questions 1-4:
   Role-specific sales questions based on the candidate's
   latest role, responsibilities, and sales experience.

2. Questions 5-7:
   Questions based specifically on the candidate's resume,
   skills, achievements, tools, companies, or responsibilities.

3. Questions 8-10:
   General HR and behavioral questions appropriate for a
   sales interview.

Rules:

- Questions must be realistic interview questions.
- Do not invent candidate experience.
- Questions 1-7 must be personalized to this resume.
- Avoid duplicate questions.
- Questions should allow the candidate to explain their experience.
- Do not provide answers.
- Return ONLY valid JSON.
- Do not use markdown.
- Do not add any fields.

Return exactly:

{{
    "questions": [
        {{
            "question_number": 1,
            "question": "string",
            "category": "role_specific"
        }}
    ]
}}

Allowed categories:

- role_specific
- resume_specific
- hr
"""

    try:
        print(
            "[GEMINI] Generating personalized interview "
            "questions (single attempt)..."
        )

        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt,
            config={
                "response_mime_type": "application/json",
            },
        )

    except Exception as error:
        print(
            "[GEMINI] Question generation failed: "
            f"{error}"
        )
        print(
            "[GEMINI] Using fallback interview questions."
        )

        return _generate_fallback_questions(
            resume_analysis=resume_analysis,
            position=position,
        )

    if not response or not response.text:
        print(
            "[GEMINI] Gemini returned an empty response."
        )
        print(
            "[GEMINI] Using fallback interview questions."
        )

        return _generate_fallback_questions(
            resume_analysis=resume_analysis,
            position=position,
        )

    try:
        data = json.loads(response.text)

    except json.JSONDecodeError as error:
        print(
            "[GEMINI] Gemini returned invalid JSON: "
            f"{error}"
        )
        print(
            "[GEMINI] Using fallback interview questions."
        )

        return _generate_fallback_questions(
            resume_analysis=resume_analysis,
            position=position,
        )

    if not isinstance(data, dict):
        print("[GEMINI] Gemini returned an invalid object.")
        print(
            "[GEMINI] Using fallback interview questions."
        )

        return _generate_fallback_questions(
            resume_analysis=resume_analysis,
            position=position,
        )

    questions = data.get("questions", [])

    if not isinstance(questions, list):
        print("[GEMINI] Invalid questions format.")
        print(
            "[GEMINI] Using fallback interview questions."
        )

        return _generate_fallback_questions(
            resume_analysis=resume_analysis,
            position=position,
        )

    if len(questions) != 10:
        print(
            "[GEMINI] Expected 10 questions, "
            f"got {len(questions)}."
        )
        print(
            "[GEMINI] Using fallback interview questions."
        )

        return _generate_fallback_questions(
            resume_analysis=resume_analysis,
            position=position,
        )

    allowed_categories = {
        "role_specific",
        "resume_specific",
        "hr",
    }

    validated_questions = []

    try:
        for expected_number, item in enumerate(
            questions,
            start=1,
        ):
            if not isinstance(item, dict):
                raise ValueError(
                    "A generated question is not an object."
                )

            question_number = item.get(
                "question_number"
            )

            question_text = item.get(
                "question"
            )

            category = item.get(
                "category"
            )

            if question_number != expected_number:
                raise ValueError(
                    "Question numbers are invalid."
                )

            if not isinstance(
                question_text,
                str,
            ) or not question_text.strip():
                raise ValueError(
                    "A generated question is empty."
                )

            if category not in allowed_categories:
                raise ValueError(
                    f"Invalid question category: {category}"
                )

            validated_questions.append(
                {
                    "question_number": question_number,
                    "question": question_text.strip(),
                    "category": category,
                }
            )

    except Exception as error:
        print(
            "[GEMINI] Generated questions failed "
            f"validation: {error}"
        )
        print(
            "[GEMINI] Using fallback interview questions."
        )

        return _generate_fallback_questions(
            resume_analysis=resume_analysis,
            position=position,
        )

    print(
        "[GEMINI] Successfully generated 10 "
        "personalized interview questions."
    )

    return validated_questions

