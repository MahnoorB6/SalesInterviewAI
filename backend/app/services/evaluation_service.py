import re


# ============================================================
# SCORING CONFIGURATION
# ============================================================

COMPETENCY_WEIGHTS = {
    "communication": 15,
    "confidence": 10,
    "sales_knowledge": 15,
    "lead_qualification": 15,
    "objection_handling": 15,
    "persuasion": 15,
    "closing_ability": 15,
}

PASS_SCORE = 60
MIN_COMPETENCY_SCORE = 40


# ============================================================
# KEYWORD GROUPS
# ============================================================

KEYWORDS = {
    "communication": [
        "understand",
        "explain",
        "clear",
        "listen",
        "communicate",
        "communication",
        "clarify",
        "question",
        "conversation",
        "customer",
        "client",
    ],

    "confidence": [
        "confident",
        "confidence",
        "certain",
        "comfortable",
        "definitely",
        "absolutely",
        "assure",
        "believe",
        "experience",
        "successfully",
    ],

    "sales_knowledge": [
        "sales",
        "selling",
        "prospect",
        "lead",
        "pipeline",
        "crm",
        "conversion",
        "sales funnel",
        "value proposition",
        "upsell",
        "cross-sell",
        "customer needs",
        "discovery",
        "qualification",
    ],

    "lead_qualification": [
        "qualify",
        "qualification",
        "budget",
        "need",
        "needs",
        "authority",
        "decision maker",
        "timeline",
        "requirement",
        "requirements",
        "pain point",
        "pain points",
        "prospect",
        "fit",
    ],

    "objection_handling": [
        "objection",
        "concern",
        "concerns",
        "understand your concern",
        "address",
        "alternative",
        "solution",
        "clarify",
        "question",
        "value",
        "benefit",
        "follow up",
        "follow-up",
        "handle",
        "resolve",
    ],

    "persuasion": [
        "value",
        "benefit",
        "benefits",
        "solution",
        "customer",
        "roi",
        "return on investment",
        "advantage",
        "results",
        "prove",
        "demonstrate",
        "recommend",
        "recommendation",
        "why",
    ],

    "closing_ability": [
        "close",
        "closing",
        "sale",
        "buy",
        "purchase",
        "sign",
        "agreement",
        "next step",
        "next steps",
        "schedule",
        "meeting",
        "demo",
        "follow up",
        "follow-up",
        "commit",
        "decision",
        "ask for the sale",
    ],
}


# ============================================================
# QUESTION-SPECIFIC KEYWORDS
# ============================================================

QUESTION_KEYWORDS = {
    "communication": [
        "communication",
        "communicate",
        "customer",
        "client",
        "explain",
        "listen",
        "clarify",
    ],

    "sales": [
        "sales",
        "sell",
        "selling",
        "prospect",
        "lead",
        "customer",
        "client",
        "deal",
        "pipeline",
    ],

    "lead": [
        "qualify",
        "qualification",
        "budget",
        "need",
        "authority",
        "decision maker",
        "timeline",
        "requirement",
        "pain point",
    ],

    "objection": [
        "objection",
        "concern",
        "price",
        "expensive",
        "competitor",
        "problem",
        "alternative",
        "solution",
        "value",
    ],

    "persuasion": [
        "value",
        "benefit",
        "roi",
        "advantage",
        "solution",
        "recommend",
        "customer",
        "results",
    ],

    "closing": [
        "close",
        "closing",
        "sale",
        "buy",
        "purchase",
        "next step",
        "meeting",
        "demo",
        "agreement",
    ],
}


# ============================================================
# TEXT HELPERS
# ============================================================

def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = text.lower()

    text = re.sub(
        r"[^a-z0-9\s\-]",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def count_keyword_matches(
    text: str,
    keywords: list[str],
) -> int:

    count = 0

    for keyword in keywords:
        keyword = normalize_text(keyword)

        if not keyword:
            continue

        if keyword in text:
            count += 1

    return count


def clamp_score(score: float) -> int:
    return max(
        0,
        min(
            100,
            round(score),
        ),
    )


# ============================================================
# EXTRACT CANDIDATE ANSWERS
# ============================================================

def extract_candidate_answers(
    transcript: str,
) -> list[str]:

    """
    Extract candidate speech from the transcript.

    Supports common transcript formats such as:

    Candidate: ...
    Alena: ...

    or:

    CANDIDATE: ...
    INTERVIEWER: ...
    """

    if not transcript:
        return []

    lines = transcript.splitlines()

    answers = []

    current_speaker = None
    current_text = []

    candidate_labels = {
        "candidate",
        "user",
        "candidate:",
        "user:",
    }

    interviewer_labels = {
        "alena",
        "interviewer",
        "agent",
        "alena:",
        "interviewer:",
        "agent:",
    }

    for raw_line in lines:

        line = raw_line.strip()

        if not line:
            continue

        lower_line = line.lower()

        matched_candidate = False
        matched_interviewer = False

        for label in candidate_labels:

            if lower_line.startswith(label):

                if current_speaker == "candidate":
                    if current_text:
                        answers.append(
                            " ".join(current_text)
                        )

                current_speaker = "candidate"

                content = line[len(label):].strip()

                current_text = []

                if content:
                    current_text.append(content)

                matched_candidate = True
                break

        if matched_candidate:
            continue

        for label in interviewer_labels:

            if lower_line.startswith(label):

                if current_speaker == "candidate":
                    if current_text:
                        answers.append(
                            " ".join(current_text)
                        )

                current_speaker = "interviewer"
                current_text = []

                matched_interviewer = True
                break

        if matched_interviewer:
            continue

        if current_speaker == "candidate":
            current_text.append(line)

    if current_speaker == "candidate":
        if current_text:
            answers.append(
                " ".join(current_text)
            )

    return [
        answer.strip()
        for answer in answers
        if answer.strip()
    ]


# ============================================================
# FALLBACK CANDIDATE TEXT
# ============================================================

def get_candidate_text(
    transcript: str,
) -> str:

    answers = extract_candidate_answers(
        transcript
    )

    if answers:
        return " ".join(answers)

    # If speaker labels are unavailable,
    # use the transcript as a fallback.
    return transcript or ""


# ============================================================
# SCORE A COMPETENCY
# ============================================================

def score_competency(
    text: str,
    competency: str,
) -> int:

    normalized = normalize_text(text)

    keywords = KEYWORDS.get(
        competency,
        [],
    )

    if not normalized:
        return 0

    word_count = len(
        normalized.split()
    )

    keyword_matches = count_keyword_matches(
        normalized,
        keywords,
    )

    # Keyword coverage
    keyword_score = min(
        70,
        keyword_matches * 10,
    )

    # Answer depth
    if word_count >= 120:
        depth_score = 30

    elif word_count >= 80:
        depth_score = 25

    elif word_count >= 50:
        depth_score = 20

    elif word_count >= 25:
        depth_score = 12

    elif word_count >= 10:
        depth_score = 6

    else:
        depth_score = 0

    return clamp_score(
        keyword_score + depth_score
    )


# ============================================================
# QUESTION SCORING
# ============================================================

def detect_question_category(
    question: str,
) -> str | None:

    normalized = normalize_text(
        question
    )

    category_scores = {}

    for category, keywords in QUESTION_KEYWORDS.items():

        matches = count_keyword_matches(
            normalized,
            keywords,
        )

        category_scores[category] = matches

    if not category_scores:
        return None

    category = max(
        category_scores,
        key=category_scores.get,
    )

    if category_scores[category] == 0:
        return None

    return category


def score_question(
    question: str,
    answer: str,
) -> tuple[int, str]:

    normalized_answer = normalize_text(
        answer
    )

    if not normalized_answer:

        return (
            0,
            "No candidate answer was detected.",
        )

    word_count = len(
        normalized_answer.split()
    )

    category = detect_question_category(
        question
    )

    category_keywords = []

    if category:
        category_keywords = QUESTION_KEYWORDS.get(
            category,
            [],
        )

    keyword_matches = count_keyword_matches(
        normalized_answer,
        category_keywords,
    )

    # Base answer-quality score
    if word_count >= 100:
        depth_score = 45

    elif word_count >= 70:
        depth_score = 38

    elif word_count >= 50:
        depth_score = 32

    elif word_count >= 30:
        depth_score = 25

    elif word_count >= 15:
        depth_score = 15

    elif word_count >= 5:
        depth_score = 8

    else:
        depth_score = 2

    keyword_score = min(
        45,
        keyword_matches * 9,
    )

    score = clamp_score(
        depth_score + keyword_score
    )

    if score >= 75:
        feedback = (
            "The candidate provided a detailed "
            "and relevant response."
        )

    elif score >= 60:
        feedback = (
            "The candidate provided a reasonable "
            "response with relevant information."
        )

    elif score >= 40:
        feedback = (
            "The candidate addressed the question "
            "but the response lacked sufficient detail."
        )

    else:
        feedback = (
            "The response was brief or lacked "
            "relevant information."
        )

    return score, feedback


# ============================================================
# FIND ANSWERS FOR QUESTIONS
# ============================================================

def match_questions_to_answers(
    interview_questions: list,
    transcript: str,
) -> list[str]:

    answers = extract_candidate_answers(
        transcript
    )

    if not answers:

        return [
            ""
            for _ in interview_questions
        ]

    # Normally the interview transcript contains
    # one candidate response for each question.
    #
    # If there are more responses than questions,
    # distribute them across the questions.
    #
    # If there are fewer responses, remaining
    # questions receive an empty answer.

    matched = []

    for index in range(
        len(interview_questions)
    ):

        if index < len(answers):

            matched.append(
                answers[index]
            )

        else:

            matched.append("")

    return matched


# ============================================================
# GENERATE STRENGTHS
# ============================================================

def generate_strengths(
    scores: dict,
) -> list[str]:

    strengths = []

    labels = {
        "communication": "Clear communication",
        "confidence": "Confidence",
        "sales_knowledge": "Sales knowledge",
        "lead_qualification": "Lead qualification",
        "objection_handling": "Objection handling",
        "persuasion": "Persuasion",
        "closing_ability": "Closing ability",
    }

    for competency, score in scores.items():

        if competency not in labels:
            continue

        if score >= 75:

            strengths.append(
                f"{labels[competency]} demonstrated strongly "
                f"({score}/100)."
            )

    if not strengths:

        strongest = sorted(
            [
                (
                    competency,
                    score,
                )
                for competency, score in scores.items()
                if competency in labels
            ],
            key=lambda item: item[1],
            reverse=True,
        )

        for competency, score in strongest[:2]:

            strengths.append(
                f"{labels[competency]} was one of the "
                f"stronger areas ({score}/100)."
            )

    return strengths[:4]


# ============================================================
# GENERATE WEAKNESSES
# ============================================================

def generate_weaknesses(
    scores: dict,
) -> list[str]:

    weaknesses = []

    labels = {
        "communication": "Communication",
        "confidence": "Confidence",
        "sales_knowledge": "Sales knowledge",
        "lead_qualification": "Lead qualification",
        "objection_handling": "Objection handling",
        "persuasion": "Persuasion",
        "closing_ability": "Closing ability",
    }

    for competency, score in scores.items():

        if competency not in labels:
            continue

        if score < 60:

            weaknesses.append(
                f"{labels[competency]} needs improvement "
                f"({score}/100)."
            )

    if not weaknesses:

        weaknesses.append(
            "No major competency weakness was identified "
            "by the rule-based evaluation."
        )

    return weaknesses[:4]


# ============================================================
# GENERATE RECOMMENDATION
# ============================================================

def generate_recommendation(
    overall_score: int,
    result: str,
) -> str:

    if result == "PASS":

        return (
            f"The candidate achieved an overall score of "
            f"{overall_score}/100 and meets the defined "
            f"passing criteria for this sales interview."
        )

    return (
        f"The candidate achieved an overall score of "
        f"{overall_score}/100 and does not meet the "
        f"defined passing criteria for this sales interview."
    )


# ============================================================
# MAIN EVALUATION FUNCTION
# ============================================================

def evaluate_interview(
    transcript: str,
    interview_questions: list,
    resume_analysis: dict | None = None,
    position: str = "Sales Representative",
):
    """
    Evaluate a completed sales interview using
    deterministic rule-based scoring.

    Gemini is NOT used.

    Resume is optional and does not affect scoring.
    """

    # ========================================================
    # VALIDATE TRANSCRIPT
    # ========================================================

    if not transcript or not transcript.strip():

        raise ValueError(
            "Interview transcript is empty."
        )

    # ========================================================
    # VALIDATE QUESTIONS
    # ========================================================

    if not interview_questions:

        raise ValueError(
            "Interview questions are missing."
        )

    print(
        "[RULE-BASED EVALUATION] "
        "Generating evaluation..."
    )

    # ========================================================
    # GET CANDIDATE TEXT
    # ========================================================

    candidate_text = get_candidate_text(
        transcript
    )

    # ========================================================
    # SCORE COMPETENCIES
    # ========================================================

    competency_scores = {}

    for competency in COMPETENCY_WEIGHTS:

        score = score_competency(
            candidate_text,
            competency,
        )

        competency_scores[
            competency
        ] = score

    # ========================================================
    # SCORE QUESTIONS
    # ========================================================

    candidate_answers = match_questions_to_answers(
        interview_questions,
        transcript,
    )

    question_scores = []

    for index, question_data in enumerate(
        interview_questions
    ):

        question_number = question_data.get(
            "question_number",
            index + 1,
        )

        question_text = question_data.get(
            "question",
            "",
        )

        answer = candidate_answers[index]

        score, feedback = score_question(
            question_text,
            answer,
        )

        question_scores.append(
            {
                "question_number": question_number,
                "score": score,
                "feedback": feedback,
            }
        )

    # ========================================================
    # CALCULATE OVERALL SCORE
    # ========================================================

    overall_score = 0

    for competency, weight in COMPETENCY_WEIGHTS.items():

        overall_score += (
            competency_scores[competency]
            * weight
            / 100
        )

    overall_score = clamp_score(
        overall_score
    )

    # ========================================================
    # PASS / FAIL
    # ========================================================

    has_low_competency = any(
        score < MIN_COMPETENCY_SCORE
        for score in competency_scores.values()
    )

    result = (
        "PASS"
        if (
            overall_score >= PASS_SCORE
            and not has_low_competency
        )
        else "FAIL"
    )

    # ========================================================
    # STRENGTHS / WEAKNESSES
    # ========================================================

    strengths = generate_strengths(
        competency_scores
    )

    weaknesses = generate_weaknesses(
        competency_scores
    )

    # ========================================================
    # RECOMMENDATION
    # ========================================================

    recommendation = generate_recommendation(
        overall_score,
        result,
    )

    # ========================================================
    # FINAL RESULT
    # ========================================================

    evaluation = {
        "question_scores": question_scores,

        "communication": competency_scores[
            "communication"
        ],

        "confidence": competency_scores[
            "confidence"
        ],

        "sales_knowledge": competency_scores[
            "sales_knowledge"
        ],

        "lead_qualification": competency_scores[
            "lead_qualification"
        ],

        "objection_handling": competency_scores[
            "objection_handling"
        ],

        "persuasion": competency_scores[
            "persuasion"
        ],

        "closing_ability": competency_scores[
            "closing_ability"
        ],

        "overall_score": overall_score,

        "result": result,

        "strengths": strengths,

        "weaknesses": weaknesses,

        "recommendation": recommendation,
    }

    print(
        "[RULE-BASED EVALUATION] "
        f"Evaluation generated successfully. "
        f"Score: {overall_score}/100 | "
        f"Result: {result}"
    )

    return evaluation