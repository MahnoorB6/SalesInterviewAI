"""Compatibility entry point for existing callers; delegates to the engine."""

from app.services.evaluation_engine import (
    DEFAULT_EVALUATION_ENGINE,
    BehavioralRubricEvaluationEngine,
    EvaluationEngine,
)


def evaluate_interview(
    transcript: str,
    interview_questions: list[dict],
    resume_analysis: dict | None = None,
    position: str = "Sales Representative",
    *,
    interview_status: str | None = None,
    transcript_quality: str | None = None,
):
    """Legacy-compatible function; resume data intentionally does not affect scores."""
    return DEFAULT_EVALUATION_ENGINE.evaluate(
        transcript,
        interview_questions,
        interview_status=interview_status,
        transcript_quality=transcript_quality,
    )


__all__ = [
    "EvaluationEngine",
    "BehavioralRubricEvaluationEngine",
    "evaluate_interview",
]
