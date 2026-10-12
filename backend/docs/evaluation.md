# Evaluation engine and future labeled data

## Current evaluation method

`BehavioralRubricEvaluationEngine` implements `EvaluationEngine`. The current method is deterministic and explicitly versioned as `behavioral_rubric_v1` (`sales_behavioral_1.0`, evaluator `behavioral_rubric_engine_1.0`). It is not a trained model and does not call Gemini.

Competencies, weights, observable criteria, question-intent tags, and the 1–5 behavior anchors live together in `app/services/evaluation_rubric.py`. Each criterion detector requires a phrase pattern associated with an action or demonstrated behavior. Merely mentioning a sales term, or giving a long answer, does not add points. The engine quotes the exact answer excerpt it used. An absent criterion is linked to the answer that was reviewed; an unasked or unanswerable competency is `not_observed` or `uncertain`, with no score.

Speaker turns are parsed before question alignment. Only `CANDIDATE`/`USER` turns are scored as answers. Alena/interviewer/agent turns identify prompts and never enter candidate evidence. In-order prompt matching is used when prompt counts support it; when additional prompts make ordering ambiguous, only high text-overlap matches are assigned. Unmatched answers remain uncertain rather than being shifted onto a different question.

The seven initial weights are 15, 10, 15, 15, 15, 15, and 15 percent. The engine calculates a weighted mean over sufficiently observed competencies and renormalizes by their included weights. Ratings map linearly from 1–5 to 0–100. Missing competencies are excluded, never treated as zero. Coverage, transcript quality, alignment quality, and evidence confidence accompany the score. `result` remains unset for engine evaluations; approve/reject remains a separate recruiter action.

The phrase-pattern rubric is intentionally inspectable but has limits: it can miss paraphrases, dialects, transcription errors, and behaviors expressed in ways the configured patterns do not capture. Its ratings are evidence prompts for a recruiter, not validated measures of job performance. Do not use this version as an automated hiring gate.

## Provenance and history

`evaluations.structured_result` holds the currently displayed structured report. Each generation appends an `evaluation_runs` record containing the complete output and its method/version metadata. Prior runs are retained when a report is regenerated. When an old evaluation without structured provenance is regenerated, the prior legacy values are first snapshotted as `legacy_unknown`; no evidence is reconstructed for them.

## Human labels and future ML

`human_evaluation_labels` is an empty-by-default annotation table. The authenticated `POST /api/evaluations/labels` endpoint records a rater, question, candidate answer, competency, rubric criterion, 1–5 rating, verbatim evidence span, rubric version, transcript quality, and pending adjudication state. The endpoint accepts labels only against an existing structured interview answer, validates criterion membership, and requires the evidence span to occur exactly in that answer. No seed rows, fabricated ratings, or training results are included.

Do not train until a sufficiently broad, representative human-rated dataset exists. A responsible future workflow should collect multiple independent ratings per answer, adjudicate disagreements, split train/validation/test by candidate (and preferably by time/source), report per-competency ordinal agreement and calibration, compare predictions with human ratings, assess subgroup error and transcript-quality sensitivity, version data and models, and monitor drift. Any future `MLEvaluationEngine` should estimate rubric behavior ratings or evidence spans only; the explainable rubric aggregation and recruiter decision remain separate.
