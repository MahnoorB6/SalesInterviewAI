import re

from pydantic import BaseModel, Field


# ============================================================
# RESUME ANALYSIS MODEL
# ============================================================

class ResumeAnalysis(BaseModel):
    latest_role: str | None = None
    latest_company: str | None = None
    start_date: str | None = None
    end_date: str | None = None

    responsibilities: list[str] = Field(
        default_factory=list
    )

    skills: list[str] = Field(
        default_factory=list
    )

    education: list[str] = Field(
        default_factory=list
    )

    sales_experience: list[str] = Field(
        default_factory=list
    )


# ============================================================
# COMMON SKILLS
# ============================================================

KNOWN_SKILLS = [
    "python",
    "java",
    "javascript",
    "typescript",
    "c++",
    "c#",
    "sql",
    "mysql",
    "postgresql",
    "mongodb",
    "fastapi",
    "flask",
    "django",
    "react",
    "node.js",
    "nodejs",
    "html",
    "css",
    "git",
    "github",
    "docker",
    "aws",
    "azure",
    "machine learning",
    "deep learning",
    "artificial intelligence",
    "ai",
    "ml",
    "data analysis",
    "data science",
    "pandas",
    "numpy",
    "scikit-learn",
    "tensorflow",
    "pytorch",
    "opencv",
    "nlp",
    "computer vision",
    "generative ai",
    "openai",
    "gemini",
    "sales",
    "salesforce",
    "crm",
    "lead generation",
    "lead qualification",
    "customer relationship management",
    "negotiation",
    "communication",
    "cold calling",
    "business development",
]


# ============================================================
# ROLE KEYWORDS
# ============================================================

ROLE_KEYWORDS = [
    "sales manager",
    "sales executive",
    "sales representative",
    "sales associate",
    "sales officer",
    "sales consultant",
    "account executive",
    "account manager",
    "business development manager",
    "business development executive",
    "business development representative",
    "business development officer",
    "customer success manager",
    "customer success executive",
    "marketing manager",
    "marketing executive",
    "software engineer",
    "software developer",
    "frontend developer",
    "backend developer",
    "full stack developer",
    "data scientist",
    "data analyst",
    "machine learning engineer",
    "ai engineer",
    "ai/ml engineer",
    "product manager",
    "project manager",
    "intern",
]


# ============================================================
# SALES KEYWORDS
# ============================================================

SALES_KEYWORDS = [
    "sales",
    "selling",
    "prospecting",
    "prospect",
    "lead generation",
    "lead qualification",
    "customer acquisition",
    "business development",
    "cold calling",
    "cold calls",
    "client acquisition",
    "negotiation",
    "closing",
    "sales target",
    "sales targets",
    "revenue",
    "crm",
    "salesforce",
    "account management",
    "customer relationship",
    "upselling",
    "cross-selling",
]


# ============================================================
# DATE PATTERNS
# ============================================================

MONTH_PATTERN = (
    r"(?:January|February|March|April|May|June|July|"
    r"August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
)

DATE_PATTERN = re.compile(
    rf"\b{MONTH_PATTERN}"
    rf"(?:\s+\d{{4}})?"
    rf"|\b\d{{1,2}}[/-]\d{{4}}\b"
    rf"|\b\d{{4}}\b",
    re.IGNORECASE,
)


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_text(text: str) -> str:

    if not text:
        return ""

    text = text.replace(
        "\r\n",
        "\n",
    )

    text = text.replace(
        "\r",
        "\n",
    )

    return text


def clean_line(line: str) -> str:

    line = line.strip()

    line = re.sub(
        r"^[•●▪◦\-*]+\s*",
        "",
        line,
    )

    return line.strip()


# ============================================================
# SECTION DETECTION
# ============================================================

def find_section_lines(
    lines: list[str],
    section_names: list[str],
) -> list[str]:

    section_lines = []

    inside_section = False

    normalized_names = [
        name.lower()
        for name in section_names
    ]

    for line in lines:

        clean = clean_line(line)

        if not clean:
            continue

        lower = clean.lower()

        is_heading = (
            lower in normalized_names
            or any(
                lower.startswith(
                    name + ":"
                )
                for name in normalized_names
            )
        )

        if is_heading:

            inside_section = True
            continue

        if inside_section:

            # Detect another common section heading.
            if (
                len(clean) < 50
                and (
                    clean.isupper()
                    or lower in {
                        "experience",
                        "work experience",
                        "employment",
                        "education",
                        "skills",
                        "technical skills",
                        "responsibilities",
                        "profile",
                        "summary",
                        "projects",
                        "certifications",
                        "achievements",
                    }
                )
            ):
                break

            section_lines.append(
                clean
            )

    return section_lines


# ============================================================
# EXTRACT SKILLS
# ============================================================

def extract_skills(
    text: str,
    lines: list[str],
) -> list[str]:

    skills = []

    skill_lines = find_section_lines(
        lines,
        [
            "skills",
            "technical skills",
            "core skills",
            "key skills",
            "skills & expertise",
        ],
    )

    search_text = " ".join(
        skill_lines
    )

    if not search_text:
        search_text = text

    normalized = search_text.lower()

    for skill in KNOWN_SKILLS:

        if skill.lower() in normalized:

            if skill not in skills:
                skills.append(skill)

    return skills


# ============================================================
# EXTRACT EDUCATION
# ============================================================

def extract_education(
    lines: list[str],
) -> list[str]:

    education_lines = find_section_lines(
        lines,
        [
            "education",
            "academic background",
            "qualifications",
        ],
    )

    results = []

    for line in education_lines:

        if len(line) < 3:
            continue

        results.append(line)

    return results[:20]


# ============================================================
# EXTRACT RESPONSIBILITIES
# ============================================================

def extract_responsibilities(
    lines: list[str],
) -> list[str]:

    responsibility_lines = find_section_lines(
        lines,
        [
            "responsibilities",
            "key responsibilities",
            "duties",
            "roles and responsibilities",
        ],
    )

    results = []

    for line in responsibility_lines:

        if len(line) < 10:
            continue

        results.append(line)

    return results[:30]


# ============================================================
# FIND ROLE
# ============================================================

def find_role(
    line: str,
) -> str | None:

    lower = line.lower()

    for role in sorted(
        ROLE_KEYWORDS,
        key=len,
        reverse=True,
    ):

        if role.lower() in lower:

            return role

    return None


# ============================================================
# FIND DATES
# ============================================================

def extract_dates(
    text: str,
) -> tuple[str | None, str | None]:

    matches = DATE_PATTERN.findall(
        text
    )

    if not matches:
        return None, None

    cleaned = [
        match.strip()
        for match in matches
        if match.strip()
    ]

    if not cleaned:
        return None, None

    start_date = cleaned[0]

    end_date = (
        cleaned[1]
        if len(cleaned) > 1
        else None
    )

    if re.search(
        r"\b(?:present|current|now)\b",
        text,
        re.IGNORECASE,
    ):

        end_date = "Present"

    return start_date, end_date


# ============================================================
# EXTRACT LATEST ROLE / COMPANY
# ============================================================

def extract_latest_employment(
    lines: list[str],
) -> tuple[
    str | None,
    str | None,
    str | None,
    str | None,
]:

    experience_lines = find_section_lines(
        lines,
        [
            "experience",
            "work experience",
            "employment",
            "professional experience",
            "work history",
        ],
    )

    if not experience_lines:

        experience_lines = lines

    role = None
    company = None
    start_date = None
    end_date = None

    for index, line in enumerate(
        experience_lines
    ):

        detected_role = find_role(
            line
        )

        if not detected_role:
            continue

        role = detected_role.title()

        # Look around the role line for
        # company and dates.
        nearby = experience_lines[
            max(0, index - 1):
            min(
                len(experience_lines),
                index + 3,
            )
        ]

        combined = " ".join(
            nearby
        )

        dates = DATE_PATTERN.findall(
            combined
        )

        if dates:

            start_date = dates[0]

            if len(dates) > 1:

                end_date = dates[1]

        if re.search(
            r"\b(?:present|current|now)\b",
            combined,
            re.IGNORECASE,
        ):

            end_date = "Present"

        # Try to identify a company line.
        for nearby_line in nearby:

            lower = nearby_line.lower()

            if (
                nearby_line == line
                or find_role(nearby_line)
            ):
                continue

            if DATE_PATTERN.search(
                nearby_line
            ):
                continue

            if len(nearby_line) <= 80:

                company = nearby_line

                break

        # First detected role is treated as
        # the most recent role because resumes
        # normally list newest experience first.
        break

    return (
        role,
        company,
        start_date,
        end_date,
    )


# ============================================================
# EXTRACT SALES EXPERIENCE
# ============================================================

def extract_sales_experience(
    lines: list[str],
) -> list[str]:

    results = []

    experience_lines = find_section_lines(
        lines,
        [
            "experience",
            "work experience",
            "employment",
            "professional experience",
            "work history",
        ],
    )

    for line in experience_lines:

        lower = line.lower()

        if any(
            keyword in lower
            for keyword in SALES_KEYWORDS
        ):

            if line not in results:

                results.append(line)

    return results[:30]


# ============================================================
# MAIN ANALYZER
# ============================================================

def analyze_resume(
    resume_text: str,
) -> ResumeAnalysis:

    """
    Analyze a resume using deterministic
    rule-based extraction.

    No Gemini or external API is used.
    """

    if not resume_text or not resume_text.strip():

        return ResumeAnalysis()

    text = normalize_text(
        resume_text
    )

    lines = [
        clean_line(line)
        for line in text.split("\n")
    ]

    lines = [
        line
        for line in lines
        if line
    ]

    # ========================================================
    # LATEST EMPLOYMENT
    # ========================================================

    (
        latest_role,
        latest_company,
        start_date,
        end_date,
    ) = extract_latest_employment(
        lines
    )

    # ========================================================
    # SKILLS
    # ========================================================

    skills = extract_skills(
        text,
        lines,
    )

    # ========================================================
    # EDUCATION
    # ========================================================

    education = extract_education(
        lines
    )

    # ========================================================
    # RESPONSIBILITIES
    # ========================================================

    responsibilities = extract_responsibilities(
        lines
    )

    # ========================================================
    # SALES EXPERIENCE
    # ========================================================

    sales_experience = extract_sales_experience(
        lines
    )

    # ========================================================
    # RESULT
    # ========================================================

    return ResumeAnalysis(
        latest_role=latest_role,
        latest_company=latest_company,
        start_date=start_date,
        end_date=end_date,
        responsibilities=responsibilities,
        skills=skills,
        education=education,
        sales_experience=sales_experience,
    )