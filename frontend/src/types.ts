export const INTERVIEW_STATUSES = [
  "scheduled",
  "in_progress",
  "completed",
  "cancelled",
  "interrupted",
  "failed",
] as const

export type InterviewStatus = (typeof INTERVIEW_STATUSES)[number]
