from enum import Enum


class InterviewStatus(str, Enum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


INTERVIEW_STATUS_VALUES = tuple(status.value for status in InterviewStatus)

VALID_INTERVIEW_TRANSITIONS = {
    InterviewStatus.SCHEDULED.value: frozenset({InterviewStatus.IN_PROGRESS.value, InterviewStatus.CANCELLED.value, InterviewStatus.FAILED.value}),
    InterviewStatus.IN_PROGRESS.value: frozenset({InterviewStatus.COMPLETED.value, InterviewStatus.INTERRUPTED.value, InterviewStatus.FAILED.value}),
    InterviewStatus.INTERRUPTED.value: frozenset({InterviewStatus.SCHEDULED.value, InterviewStatus.FAILED.value}),
    InterviewStatus.COMPLETED.value: frozenset(),
    InterviewStatus.CANCELLED.value: frozenset(),
    InterviewStatus.FAILED.value: frozenset(),
}


def can_transition_interview(current: str, target: str) -> bool:
    return current == target or target in VALID_INTERVIEW_TRANSITIONS.get(current, frozenset())
