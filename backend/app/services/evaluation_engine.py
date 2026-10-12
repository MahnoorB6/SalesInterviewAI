"""Evidence-first evaluation engine. This implementation is deterministic, not ML."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from difflib import SequenceMatcher
from typing import Any

from app.services.evaluation_rubric import (
    COMPETENCIES,
    COMPETENCY_BY_KEY,
    COMPETENCY_WEIGHTS,
    EVALUATION_METHOD,
    EVALUATOR_VERSION,
    QUESTION_TAG_PATTERNS,
    RATING_RATIO_THRESHOLDS,
    RUBRIC_VERSION,
)


class EvaluationEngine(ABC):
    @abstractmethod
    def evaluate(
        self,
        transcript: str,
        interview_questions: list[dict[str, Any]],
        *,
        interview_status: str | None = None,
        transcript_quality: str | None = None,
    ) -> dict[str, Any]:
        """Return a structured, reproducible evaluation result."""


class BehavioralRubricEvaluationEngine(EvaluationEngine):
    """Transparent phrase-pattern rubric. Patterns surface evidence; they do not count keywords."""

    def evaluate(
        self,
        transcript: str,
        interview_questions: list[dict[str, Any]],
        *,
        interview_status: str | None = None,
        transcript_quality: str | None = None,
    ) -> dict[str, Any]:
        if not transcript or not transcript.strip():
            raise ValueError("Interview transcript is empty")
        if not interview_questions:
            raise ValueError("Interview questions are missing")

        questions = [
            {
                "id": item.get("id", item.get("question_number", index + 1)) or item.get("question_number", index + 1),
                "order": item.get("question_number", item.get("order", index + 1)),
                "text": str(item.get("question", item.get("text", ""))).strip(),
            }
            for index, item in enumerate(interview_questions)
        ]
        questions.sort(key=lambda item: (item["order"] is None, item["order"] or 0))
        for question in questions:
            question["competency_tags"] = _tag_question(question["text"])

        turns = _parse_speaker_turns(transcript)
        question_turns = [
            turn for turn in turns
            if turn["speaker"] == "interviewer" and "?" in turn["text"]
        ]
        pairings, alignment_quality = _align_question_turns(questions, question_turns)

        question_results: list[dict[str, Any]] = []
        competency_observations: dict[str, list[dict[str, Any]]] = {
            item.key: [] for item in COMPETENCIES
        }
        for question in questions:
            prompt_turn = pairings.get(question["id"])
            if prompt_turn is None:
                answer = {
                    "candidate_text": None,
                    "turn_references": [],
                    "completeness": "uncertain",
                    "quality": "unmatched_question",
                }
            else:
                answer = _answer_after_turn(turns, prompt_turn["turn_index"])
            relevant = list(question["competency_tags"])
            question_evidence: list[dict[str, Any]] = []
            question_profiles: dict[str, dict[str, Any]] = {}

            if answer["candidate_text"]:
                for key in relevant:
                    profile = _score_competency(key, [{"question": question, "answer": answer}], alignment_quality)
                    question_profiles[key] = profile
                    question_evidence.extend(profile["evidence"])
            for key in relevant:
                if key in question_profiles:
                    profile = question_profiles[key]
                else:
                    profile = _score_competency(key, [{"question": question, "answer": answer}], alignment_quality)
                    question_profiles[key] = profile
                competency_observations[key].append({"question": question, "answer": answer, "profile": profile})

            observed_profiles = [profile for profile in question_profiles.values() if profile["score"] is not None]
            question_score = round(sum(profile["score"] for profile in observed_profiles) / len(observed_profiles)) if observed_profiles else None
            question_confidence = _answer_confidence(answer, alignment_quality)
            if observed_profiles:
                question_confidence = round(
                    (question_confidence + sum(profile["confidence"] for profile in observed_profiles) / len(observed_profiles)) / 2,
                    2,
                )
            all_missing = sorted({
                behavior
                for profile in question_profiles.values()
                for behavior in profile["missing_behaviors"]
            })
            demonstrated = [item for item in question_evidence if item["assessment"] == "demonstrated"]
            question_results.append({
                "question_id": question["id"],
                "question_order": question["order"],
                "question": question["text"],
                "candidate_answer": answer["candidate_text"],
                "transcript_turn_references": answer["turn_references"],
                "answer_completeness": answer["completeness"],
                "relevant_competencies": relevant,
                "score": question_score,
                "score_scale": "1_to_5",
                "evidence": question_evidence,
                "strengths": [
                    _evidence_statement(item, item["competency"])
                    for item in demonstrated[:3]
                ],
                "missing_behaviors": all_missing if answer["candidate_text"] else [],
                "confidence": question_confidence,
                "quality_indicator": answer["quality"],
            })

        profiles = {
            competency.key: _aggregate_competency(
                competency.key,
                competency_observations[competency.key],
                alignment_quality,
            )
            for competency in COMPETENCIES
        }
        sufficiently_observed = [
            key for key, profile in profiles.items()
            if profile["sufficiently_observed"]
        ]
        total_weight = sum(COMPETENCY_WEIGHTS[key] for key in sufficiently_observed)
        overall = None
        if total_weight:
            weighted_rating = sum(
                profiles[key]["score"] * COMPETENCY_WEIGHTS[key]
                for key in sufficiently_observed
            ) / total_weight
            overall = round((weighted_rating - 1) * 25, 1)

        quality = _transcript_quality(
            transcript,
            interview_status,
            transcript_quality,
            questions,
            question_turns,
            question_results,
        )
        observed_weight = sum(COMPETENCY_WEIGHTS[key] for key in sufficiently_observed)
        confidence_values = [profiles[key]["confidence"] for key in sufficiently_observed]
        overall_confidence = round(sum(confidence_values) / len(confidence_values), 2) if confidence_values else 0.0
        for key, profile in profiles.items():
            profile["confidence"] = round(profile["confidence"] * _quality_multiplier(quality), 2)
            profile["sufficiently_observed"] = profile["sufficiently_observed"] and _quality_multiplier(quality) >= 0.6
        if _quality_multiplier(quality) < 0.6:
            sufficiently_observed = [key for key in sufficiently_observed if profiles[key]["sufficiently_observed"]]
            total_weight = sum(COMPETENCY_WEIGHTS[key] for key in sufficiently_observed)
            observed_weight = total_weight
            if total_weight:
                overall = round((sum(profiles[key]["score"] * COMPETENCY_WEIGHTS[key] for key in sufficiently_observed) / total_weight - 1) * 25, 1)
            else:
                overall = None
        if sufficiently_observed:
            overall_confidence = round(sum(profiles[key]["confidence"] for key in sufficiently_observed) / len(sufficiently_observed), 2)
        else:
            overall_confidence = 0.0

        strengths = _build_strengths(profiles)
        weaknesses = _build_weaknesses(profiles)
        status = "complete" if len(sufficiently_observed) >= 5 else "insufficient_evidence"
        recommendation = (
            "Evidence coverage is sufficient for a structured recruiter review. Review the cited answer excerpts before making any hiring decision."
            if status == "complete"
            else "Evidence coverage is limited. Gather more interview evidence or review the available excerpts; no automated hiring decision is made."
        )
        return {
            "overall_score": overall,
            "competencies": profiles,
            "competency_weights": dict(COMPETENCY_WEIGHTS),
            "question_evaluations": question_results,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "recommendation": recommendation,
            "coverage": {
                "observed_count": len([profile for profile in profiles.values() if profile["observed"]]),
                "sufficiently_observed_count": len(sufficiently_observed),
                "total_competencies": len(COMPETENCIES),
                "description": f"{len(sufficiently_observed)} of {len(COMPETENCIES)} competencies sufficiently observed",
                "observed_weight_percent": observed_weight,
                "overall_confidence": overall_confidence,
                "transcript_quality": quality,
                "question_alignment_confidence": alignment_quality,
            },
            "evaluation_status": status,
            "rubric_version": RUBRIC_VERSION,
            "evaluator_version": EVALUATOR_VERSION,
            "evaluation_method": EVALUATION_METHOD,
        }


def _tag_question(text: str) -> list[str]:
    tags = ["communication"]
    for key, patterns in QUESTION_TAG_PATTERNS.items():
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
            tags.append(key)
    return tags


def _parse_speaker_turns(transcript: str) -> list[dict[str, Any]]:
    roles = {
        "candidate": "candidate", "user": "candidate", "applicant": "candidate", "speaker 0": "candidate",
        "alena": "interviewer", "agent": "interviewer", "interviewer": "interviewer", "assistant": "interviewer", "ai": "interviewer", "bot": "interviewer",
    }
    turns: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    label = re.compile(r"^\s*([A-Za-z][A-Za-z _-]{0,30})\s*:\s*(.*)$")
    for line in transcript.splitlines():
        match = label.match(line)
        if match:
            if current and current["text"].strip():
                current["text"] = current["text"].strip()
                turns.append(current)
            raw_role = re.sub(r"[_-]+", " ", match.group(1)).strip().lower()
            speaker = roles.get(raw_role, "unknown")
            current = {"turn_index": len(turns), "speaker": speaker, "text": match.group(2).strip()}
        elif current and line.strip():
            current["text"] += " " + line.strip()
        elif line.strip():
            # Unlabelled content is explicitly not attributed to the candidate.
            turns.append({"turn_index": len(turns), "speaker": "unknown", "text": line.strip()})
    if current and current["text"].strip():
        current["text"] = current["text"].strip()
        turns.append(current)
    for index, turn in enumerate(turns):
        turn["turn_index"] = index
    return turns


def _align_question_turns(questions: list[dict[str, Any]], prompts: list[dict[str, Any]]) -> tuple[dict[Any, dict[str, Any]], float]:
    if not prompts:
        return {}, 0.0
    if len(prompts) <= len(questions):
        aligned = list(zip(questions, prompts))
        similarities = [
            SequenceMatcher(None, _normalize(prompt["text"]), _normalize(question["text"])).ratio()
            for question, prompt in aligned
        ]
        text_match = sum(similarities) / len(similarities) if similarities else 0.0
        quality = (0.95 if len(prompts) == len(questions) else 0.72) if text_match >= 0.35 else 0.58
        return {question["id"]: prompt for question, prompt in zip(questions, prompts)}, quality
    # Extra spoken prompts often include follow-ups. Map only high-overlap prompts;
    # ambiguous turns remain unassigned rather than shifting every later answer.
    mapped: dict[Any, dict[str, Any]] = {}
    last_order = -1
    for prompt in prompts:
        candidates = []
        for index, question in enumerate(questions):
            if index <= last_order:
                continue
            similarity = SequenceMatcher(None, _normalize(prompt["text"]), _normalize(question["text"])).ratio()
            candidates.append((similarity, index, question))
        if candidates:
            similarity, index, question = max(candidates, key=lambda item: item[0])
            if similarity >= 0.48:
                mapped[question["id"]] = prompt
                last_order = index
    return mapped, 0.55 if mapped else 0.0


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()


def _answer_after_turn(turns: list[dict[str, Any]], prompt_index: int) -> dict[str, Any]:
    answer_turns = []
    for turn in turns[prompt_index + 1:]:
        if turn["speaker"] == "interviewer":
            break
        if turn["speaker"] == "candidate":
            answer_turns.append(turn)
        elif turn["speaker"] == "unknown":
            break
    if not answer_turns:
        return {"candidate_text": None, "turn_references": [], "completeness": "missing", "quality": "missing_answer"}
    text = " ".join(turn["text"] for turn in answer_turns).strip()
    count = len(re.findall(r"\b\w+\b", text))
    completeness = "partial" if count < 6 or text.rstrip().endswith(("...", "…")) else "complete"
    quality = "short_or_vague" if count < 6 else ("brief" if count < 12 else "usable")
    return {
        "candidate_text": text,
        "turn_references": [turn["turn_index"] for turn in answer_turns],
        "completeness": completeness,
        "quality": quality,
    }


def _score_competency(key: str, observations: list[dict[str, Any]], alignment_quality: float) -> dict[str, Any]:
    competency = COMPETENCY_BY_KEY[key]
    evidence: list[dict[str, Any]] = []
    matched = {criterion.key: "not_demonstrated" for criterion in competency.criteria}
    confidence_values = []
    for observation in observations:
        answer = observation["answer"]
        text = answer["candidate_text"]
        if not text:
            continue
        confidence_values.append(_answer_confidence(answer, alignment_quality))
        question = observation["question"]
        for criterion in competency.criteria:
            state, excerpt = _detect(criterion.demonstrated, criterion.partial, text)
            if state == "not_demonstrated":
                matched.setdefault(criterion.key, state)
            else:
                prior = matched.get(criterion.key, "not_demonstrated")
                if prior != "demonstrated" or state == "demonstrated":
                    matched[criterion.key] = state
            # Negative assessments point back to the exact answer reviewed too.
            evidence.append({
                "question_id": question["id"],
                "question_order": question["order"],
                "answer_excerpt": excerpt if excerpt is not None else text,
                "criterion": criterion.key,
                "criterion_label": criterion.label,
                "assessment": state,
                "competency": key,
                "transcript_turn_references": answer["turn_references"],
            })
    answered = bool(confidence_values)
    if not observations:
        score = None
        status = "not_observed"
        confidence = 0.0
    elif not answered:
        score = None
        status = "uncertain"
        confidence = 0.0
    else:
        demonstrated_count = sum(value == "demonstrated" for value in matched.values())
        partial_count = sum(value == "partially_demonstrated" for value in matched.values())
        ratio = (demonstrated_count + 0.5 * partial_count) / len(competency.criteria)
        score = _ratio_to_rating(ratio)
        confidence = round(sum(confidence_values) / len(confidence_values), 2)
        status = "demonstrated" if score >= 4 else "partially_demonstrated" if score in (2, 3) else "not_demonstrated"
    missing = [criterion.label for criterion in competency.criteria if matched.get(criterion.key) != "demonstrated"] if answered else []
    sufficiently_observed = bool(answered and confidence >= 0.45)
    rationale = _rationale(competency.label, score, status, evidence, answered)
    return {
        "competency": key,
        "label": competency.label,
        "score": score,
        "score_scale": "1_to_5",
        "score_out_of_100": _rating_to_100(score),
        "weight": competency.weight,
        "confidence": confidence,
        "observed": bool(observations),
        "status": status,
        "sufficiently_observed": sufficiently_observed,
        "evidence": evidence,
        "missing_behaviors": missing,
        "rationale": rationale,
        "anchors": competency.anchors,
    }


def _aggregate_competency(key: str, observations: list[dict[str, Any]], alignment_quality: float) -> dict[str, Any]:
    if not observations:
        return _score_competency(key, [], alignment_quality)
    if not any(observation["profile"]["score"] is not None for observation in observations):
        return _score_competency(key, observations, alignment_quality)
    # Merge evidence across tagged answers, and score distinct criteria once.
    evidence: list[dict[str, Any]] = []
    criterion_states: dict[str, str] = {}
    confidence_values = []
    for observation in observations:
        profile = observation["profile"]
        evidence.extend(profile["evidence"])
        confidence_values.append(profile["confidence"])
        for item in profile["evidence"]:
            prior = criterion_states.get(item["criterion"], "not_demonstrated")
            if item["assessment"] == "demonstrated" or prior == "not_demonstrated":
                criterion_states[item["criterion"]] = item["assessment"]
    competency = COMPETENCY_BY_KEY[key]
    for criterion in competency.criteria:
        criterion_states.setdefault(criterion.key, "not_demonstrated")
    demonstrated_count = sum(value == "demonstrated" for value in criterion_states.values())
    partial_count = sum(value == "partially_demonstrated" for value in criterion_states.values())
    ratio = (demonstrated_count + 0.5 * partial_count) / len(competency.criteria)
    score = _ratio_to_rating(ratio)
    confidence = round(sum(confidence_values) / len(confidence_values), 2)
    status = "demonstrated" if score >= 4 else "partially_demonstrated" if score in (2, 3) else "not_demonstrated"
    missing = [criterion.label for criterion in competency.criteria if criterion_states[criterion.key] != "demonstrated"]
    return {
        "competency": key,
        "label": competency.label,
        "score": score,
        "score_scale": "1_to_5",
        "score_out_of_100": _rating_to_100(score),
        "weight": competency.weight,
        "confidence": confidence,
        "observed": True,
        "status": status,
        "sufficiently_observed": confidence >= 0.45,
        "evidence": evidence,
        "missing_behaviors": missing,
        "rationale": _rationale(competency.label, score, status, evidence, True),
        "anchors": competency.anchors,
    }


def _detect(demonstrated: tuple[str, ...], partial: tuple[str, ...], text: str) -> tuple[str, str | None]:
    for pattern in demonstrated:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return "demonstrated", _surrounding_excerpt(text, match.start(), match.end())
    for pattern in partial:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return "partially_demonstrated", _surrounding_excerpt(text, match.start(), match.end())
    return "not_demonstrated", None


def _surrounding_excerpt(text: str, start: int, end: int) -> str:
    left_boundaries = [text.rfind(mark, 0, start) for mark in ".!?\n"]
    left = max(left_boundaries) + 1
    right_candidates = [position for mark in ".!?\n" if (position := text.find(mark, end)) >= 0]
    right = min(right_candidates) + 1 if right_candidates else len(text)
    excerpt = text[left:right].strip()
    if len(excerpt) > 320:
        excerpt = excerpt[:317].rsplit(" ", 1)[0] + "..."
    return excerpt


def _answer_confidence(answer: dict[str, Any], alignment_quality: float) -> float:
    text = answer.get("candidate_text") or ""
    count = len(re.findall(r"\b\w+\b", text))
    if not text:
        return 0.0
    quality = 0.35 if count < 6 else 0.62 if count < 12 else 0.9
    if answer.get("completeness") == "partial":
        quality *= 0.82
    return round(quality * alignment_quality, 2)


def _rating_to_100(rating: int | None) -> int | None:
    return None if rating is None else (rating - 1) * 25


def _ratio_to_rating(ratio: float) -> int:
    for rating in (5, 4, 3):
        if ratio >= RATING_RATIO_THRESHOLDS[rating]:
            return rating
    return 2 if ratio > 0 else 1


def _rationale(label: str, score: int | None, status: str, evidence: list[dict[str, Any]], answered: bool) -> str:
    if not answered:
        return f"{label} was not reliably observed because no candidate answer could be aligned to a tagged question."
    if not evidence:
        return f"A relevant answer was available, but none of the defined observable behaviors was evidenced in the cited response. The rating reflects available evidence, not an untested ability."
    demonstrated = [item["criterion_label"] for item in evidence if item["assessment"] == "demonstrated"]
    partial = [item["criterion_label"] for item in evidence if item["assessment"] == "partially_demonstrated"]
    details = demonstrated[:3] or partial[:3]
    return f"{label} received {score}/5 because the answer evidence showed: {', '.join(details)}."


def _evidence_statement(item: dict[str, Any], label: str) -> str:
    return f'{label.replace("_", " ").title()}: “{item["answer_excerpt"]}” — {item["criterion_label"]}.'


def _build_strengths(profiles: dict[str, dict[str, Any]]) -> list[str]:
    rows = []
    for key, profile in profiles.items():
        if profile["score"] is not None and profile["score"] >= 4:
            for item in profile["evidence"]:
                if item["assessment"] == "demonstrated":
                    rows.append(_evidence_statement(item, profile["label"]))
    return list(dict.fromkeys(rows))[:8]


def _build_weaknesses(profiles: dict[str, dict[str, Any]]) -> list[str]:
    rows = []
    for profile in profiles.values():
        if not profile["observed"] or profile["score"] is None or profile["score"] > 3:
            continue
        orders = sorted({item["question_order"] for item in profile["evidence"] if item.get("question_order") is not None})
        context = f" in answer to question {orders[0]}" if orders else " in the available answer"
        for behavior in profile["missing_behaviors"][:2]:
            rows.append(f"{profile['label']}{context}: {behavior} was not evidenced.")
    return rows[:8]


def _quality_multiplier(quality: str) -> float:
    return {"good": 1.0, "uncertain": 0.8, "incomplete": 0.72, "poor": 0.5}.get(quality, 0.8)


def _transcript_quality(transcript: str, interview_status: str | None, provided: str | None, questions: list[dict[str, Any]], prompts: list[dict[str, Any]], results: list[dict[str, Any]]) -> str:
    if provided in {"poor", "uncertain", "incomplete", "good"}:
        return provided
    if interview_status == "interrupted" or re.search(r"(?:\[incomplete\]|\[truncated\]|…|\.\.\.)\s*$", transcript.strip(), re.IGNORECASE):
        return "incomplete"
    if not any(turn["speaker"] == "candidate" for turn in _parse_speaker_turns(transcript)):
        return "poor"
    if len(prompts) < len(questions) or any(item["answer_completeness"] in {"missing", "uncertain"} for item in results):
        return "incomplete"
    if len(prompts) != len(questions):
        return "uncertain"
    return "good"


DEFAULT_EVALUATION_ENGINE = BehavioralRubricEvaluationEngine()
