import unittest

from app.services.evaluation_engine import BehavioralRubricEvaluationEngine
from app.services.evaluation_rubric import COMPETENCY_WEIGHTS


ENGINE = BehavioralRubricEvaluationEngine()


def evaluate(question, answer, *, status="completed", tail=""):
    transcript = f"ALENA: {question}\nCANDIDATE: {answer}\n{tail}"
    return ENGINE.evaluate(
        transcript,
        [{"id": 12, "question_number": 1, "question": question}],
        interview_status=status,
    )


def test_strong_objection_handling_answer_scores_with_cited_behaviors():
    result = evaluate(
        "Tell me how you handle a customer objection?",
        "I acknowledged their concern and asked what specifically worried them about the price. "
        "Based on their need to reduce onboarding delays, I explained how setup could be staged. "
        "For example, a similar customer cut onboarding time by 20%. I stayed calm and asked, "
        "does that address your concern? The next step is a short implementation demo.",
    )
    profile = result["competencies"]["objection_handling"]
    assert profile["score"] >= 4
    assert profile["evidence"]
    assert all(item["question_id"] == 12 for item in profile["evidence"])


def test_weak_objection_handling_stays_low():
    result = evaluate(
        "Tell me how you handle a customer objection?",
        "I always handle objections effectively. I talk about our features and hope they agree.",
    )
    assert result["competencies"]["objection_handling"]["score"] <= 2


def test_keyword_only_answer_does_not_score_high():
    result = evaluate(
        "How do you qualify a sales lead?",
        "I always qualify leads based on budget.",
    )
    assert result["competencies"]["lead_qualification"]["score"] <= 2


def test_strong_lead_qualification_answer():
    result = evaluate(
        "How do you qualify a sales lead?",
        "I ask what problem they need to solve and what outcome matters. I followed up by asking "
        "how they handle it today and what has not worked. I identify decision makers by asking "
        "who is involved in approval. I confirm their budget and timeline. We agree what success "
        "should look like by reducing delays by half. Then I check that our solution is a fit, and "
        "I schedule a next meeting.",
    )
    assert result["competencies"]["lead_qualification"]["score"] >= 4


def test_strong_closing_answer():
    result = evaluate(
        "Tell me about a time you closed an opportunity?",
        "When they asked about implementation dates, I recognized that as a buying signal. I asked "
        "for a commitment to start a paid pilot. I proposed a demo on Tuesday as the next step. "
        "When they hesitated, I asked what was holding them back and clarified the main risk. "
        "We agreed to revisit on Friday; I will send the proposal today and coordinate the invite. "
        "I confirmed a follow-up after the demo.",
    )
    assert result["competencies"]["closing_ability"]["score"] >= 4


def test_unasked_competency_is_not_observed_not_zero():
    result = evaluate("What did you learn in your last role?", "I owned a customer onboarding project and explained my decisions.")
    profile = result["competencies"]["objection_handling"]
    assert profile["status"] == "not_observed"
    assert profile["score"] is None
    assert "objection_handling" not in result["competency_weights"] or profile["weight"] == 15


def test_missing_candidate_answer_is_uncertain_and_unscored():
    result = ENGINE.evaluate(
        "ALENA: Tell me how you handle a customer objection?",
        [{"id": 5, "question_number": 1, "question": "Tell me how you handle a customer objection?"}],
    )
    item = result["question_evaluations"][0]
    assert item["answer_completeness"] == "missing"
    assert item["candidate_answer"] is None
    assert result["competencies"]["objection_handling"]["status"] == "uncertain"
    assert result["competencies"]["objection_handling"]["score"] is None


def test_alena_turn_is_never_included_in_candidate_answer_or_evidence():
    question = "Tell me how you handle a customer objection?"
    transcript = (
        f"ALENA: {question}\n"
        "CANDIDATE: I asked what specifically concerned them about the price.\n"
        "ALENA: I acknowledged their concern and proposed a demo next week."
    )
    result = ENGINE.evaluate(transcript, [{"id": 10, "question_number": 1, "question": question}])
    answer = result["question_evaluations"][0]["candidate_answer"]
    assert answer == "I asked what specifically concerned them about the price."
    for profile in result["competencies"].values():
        for evidence in profile["evidence"]:
            assert "I acknowledged their concern" not in evidence["answer_excerpt"]


def test_incomplete_transcript_reduces_confidence_and_coverage():
    result = evaluate(
        "Tell me how you handle a customer objection?",
        "I acknowledged their concern and asked what specifically worried them about the risk. "
        "Then I explained why the staged plan would address their need...",
        status="interrupted",
    )
    assert result["coverage"]["transcript_quality"] == "incomplete"
    assert result["coverage"]["overall_confidence"] < 1


def test_short_vague_answer_is_low_confidence_not_a_length_bonus():
    result = evaluate("How do you qualify a lead?", "I ask their budget.")
    profile = result["competencies"]["lead_qualification"]
    assert profile["score"] <= 2
    assert profile["confidence"] < 0.5
    assert result["question_evaluations"][0]["quality_indicator"] == "short_or_vague"


def test_every_evidence_excerpt_is_verbatim_candidate_text():
    answer = "I acknowledged their concern and asked what specifically worried them about the price."
    result = evaluate("Tell me about an objection you handled?", answer)
    for profile in result["competencies"].values():
        for evidence in profile["evidence"]:
            assert evidence["answer_excerpt"] in answer


def test_weights_are_central_and_sum_to_one_hundred():
    assert COMPETENCY_WEIGHTS == {
        "communication": 15,
        "confidence": 10,
        "sales_knowledge": 15,
        "lead_qualification": 15,
        "objection_handling": 15,
        "persuasion": 15,
        "closing_ability": 15,
    }
    assert sum(COMPETENCY_WEIGHTS.values()) == 100


def test_not_observed_competency_is_excluded_from_weight_denominator():
    result = evaluate("Tell me how you handle an objection?", "I acknowledged the concern and asked what worried them.")
    profile = result["competencies"]["lead_qualification"]
    assert profile["score"] is None
    assert result["coverage"]["observed_weight_percent"] < 100


def test_overall_score_renormalizes_only_sufficiently_observed_competencies():
    result = evaluate("Tell me how you handle an objection?", "I acknowledged their concern and asked what specifically worried them about the price. I explained a relevant option and checked whether that addressed it.")
    available = [item for item in result["competencies"].values() if item["sufficiently_observed"]]
    denominator = sum(item["weight"] for item in available)
    expected = round((sum(item["score"] * item["weight"] for item in available) / denominator - 1) * 25, 1) if denominator else None
    assert result["overall_score"] == expected


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            suite.addTest(unittest.FunctionTestCase(function, description=name))
    return suite
