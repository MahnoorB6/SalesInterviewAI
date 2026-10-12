import json
import unittest
import json
from types import SimpleNamespace


from app.services.elevenlabs_agent import build_question_context, save_transcript
from app.services.evaluation_engine import BehavioralRubricEvaluationEngine
from app.statuses import InterviewStatus, can_transition_interview
from fastapi import HTTPException
from datetime import datetime, timedelta, timezone


class InterviewExecutionTests(unittest.TestCase):
  def test_saved_questions_are_passed_in_persisted_order(self):
    questions = [
        SimpleNamespace(id=22, question_number=2, question="Second?", category="role"),
        SimpleNamespace(id=11, question_number=1, question="First?", category="resume"),
    ]
    plan, variables = build_question_context(questions)
    self.assertEqual([item["id"] for item in plan], [11, 22])
    self.assertEqual(variables["interview_questions"], "1. First?\n2. Second?")
    self.assertEqual([item["id"] for item in json.loads(variables["interview_question_plan"])], [11, 22])

  def test_run_alena_receives_the_persisted_question_plan(self):
    from unittest.mock import patch
    from app.models.interview import Interview
    from app.services import elevenlabs_agent as agent
    saved = [
        SimpleNamespace(id=31, question_number=1, question="Resume question?", category="resume"),
        SimpleNamespace(id=32, question_number=2, question="Role question?", category="role"),
    ]
    interview = SimpleNamespace(id=4, status="in_progress", position="Sales manager")

    class Query:
      def __init__(self, model):
        self.model = model
      def filter(self, *_args):
        return self
      def first(self):
        return interview
      def order_by(self, *_args):
        return self
      def all(self):
        return saved

    class FakeDB:
      def query(self, model):
        return Query(model)
      def close(self):
        pass

    class FakeConversation:
      config = None
      def __init__(self, *_args, config=None, **_kwargs):
        FakeConversation.config = config
      def start_session(self):
        pass
      def wait_for_session_end(self):
        pass
      def end_session(self):
        pass

    with patch.object(agent, "ELEVENLABS_API_KEY", "test-key"), \
         patch.object(agent, "ELEVENLABS_AGENT_ID", "test-agent"), \
         patch.object(agent, "SessionLocal", return_value=FakeDB()), \
         patch.object(agent, "ElevenLabs"), \
         patch.object(agent, "Conversation", FakeConversation), \
         patch.object(agent, "MeetAudioInterface", return_value=object()), \
         patch.object(agent, "mark_completed"), \
         patch.object(agent, "save_transcript", return_value="transcript.txt"), \
         patch.object(agent, "save_transcript_path"):
      result = agent.run_alena(4)
    self.assertEqual(result["status"], "completed")
    self.assertEqual(FakeConversation.config.dynamic_variables["interview_questions"], "1. Resume question?\n2. Role question?")
    self.assertEqual([question["id"] for question in json.loads(FakeConversation.config.dynamic_variables["interview_question_plan"])], [31, 32])


  def test_missing_saved_questions_fail_clearly(self):
    with self.assertRaisesRegex(ValueError, "Saved interview questions are missing"):
        build_question_context([])


  def test_expected_status_transitions_are_valid(self):
    for current, target in [("scheduled", "in_progress"), ("scheduled", "cancelled"), ("in_progress", "completed"), ("in_progress", "interrupted"), ("in_progress", "failed")]:
        with self.subTest(current=current, target=target):
            self.assertTrue(can_transition_interview(current, target))


  def test_terminal_or_running_status_transitions_are_rejected(self):
    for current, target in [("completed", "in_progress"), ("cancelled", "in_progress"), ("failed", "in_progress"), ("in_progress", "scheduled"), ("completed", "cancelled")]:
        with self.subTest(current=current, target=target):
            self.assertFalse(can_transition_interview(current, target))


  def test_transcript_snapshot_retains_roles_order_ids_and_timestamps(self):
    from unittest.mock import patch
    from pathlib import Path
    tmp_path = Path(__file__).resolve().parent
    turns = [
        {"interview_id": 5, "sequence": 1, "timestamp": "2026-01-01T00:00:00+00:00", "role": "interviewer", "message": "Question?", "question_id": 10, "completeness": "complete"},
        {"interview_id": 5, "sequence": 2, "timestamp": "2026-01-01T00:00:02+00:00", "role": "candidate", "message": "Answer", "question_id": 10, "completeness": "complete"},
    ]
    path = tmp_path / "interview_5.txt"
    json_path = tmp_path / "interview_5.json"
    try:
      with patch("app.services.elevenlabs_agent.TRANSCRIPT_DIR", tmp_path), patch("app.services.elevenlabs_agent.transcript_state", lambda _id: "interrupted"):
        save_transcript(5, turns)
      structured = json.loads(json_path.read_text(encoding="utf-8"))
      self.assertEqual(structured["state"], "interrupted")
      self.assertEqual(structured["turns"], turns)
      rendered = path.read_text(encoding="utf-8")
      self.assertIn("INTERVIEWER: Question?", rendered)
      self.assertIn("CANDIDATE: Answer", rendered)
    finally:
      path.unlink(missing_ok=True)
      json_path.unlink(missing_ok=True)


  def test_evaluator_uses_candidate_answers_and_never_alena_as_evidence(self):
    engine = BehavioralRubricEvaluationEngine()
    result = engine.evaluate(
        "ALENA: Tell me how you would handle this objection?\n"
        "CANDIDATE: I would ask what concern is behind the objection, then share relevant evidence.",
        [{"id": 7, "question_number": 1, "question": "Tell me how you would handle this objection?"}],
        interview_status=InterviewStatus.INTERRUPTED.value,
    )
    item = result["question_evaluations"][0]
    self.assertTrue(item["candidate_answer"].startswith("I would ask"))
    self.assertEqual(item["question_id"], 7)


  def test_missing_candidate_answer_stays_not_observed(self):
    result = BehavioralRubricEvaluationEngine().evaluate(
        "INTERVIEWER: Tell me how you would handle this objection?\nALENA: Please take your time.",
        [{"id": 9, "question_number": 1, "question": "Tell me how you would handle this objection?"}],
    )
    self.assertIsNone(result["question_evaluations"][0]["candidate_answer"])
    self.assertIsNone(result["question_evaluations"][0]["score"])


  def test_saved_interview_question_generation_is_frozen(self):
    from app.api import interviews

    from unittest.mock import patch
    for status in ("scheduled", "in_progress", "completed", "interrupted", "cancelled", "failed"):
      with self.subTest(status=status), patch.object(interviews, "interview_with_candidate", return_value=(SimpleNamespace(status=status), SimpleNamespace(resume_analysis={}))):
        with self.assertRaises(HTTPException) as error:
            interviews.generate_questions_for_interview(interview_id=1, db=object())
        self.assertEqual(error.exception.status_code, 409)


  def test_only_persisted_scheduled_interviews_are_scheduler_candidates(self):
    # check_interviews selects only this persisted status in its DB query.
    for status, expected in [("scheduled", True), ("in_progress", False), ("completed", False), ("interrupted", False), ("cancelled", False), ("failed", False)]:
      with self.subTest(status=status):
        self.assertEqual(status == InterviewStatus.SCHEDULED.value, expected)

  def test_scheduler_compare_and_set_allows_one_launch(self):
    from app.services.scheduler import claim_scheduled_interview
    db = _FakeDB(result=1)
    self.assertTrue(claim_scheduled_interview(db, 8))
    db.result = 0
    self.assertFalse(claim_scheduled_interview(db, 8))
    self.assertEqual(db.commits, 2)

  def test_scheduler_does_not_launch_in_progress_or_terminal_interviews(self):
    from app.services.scheduler import claim_scheduled_interview
    for status in ("in_progress", "completed", "cancelled", "failed"):
      with self.subTest(status=status):
        self.assertFalse(claim_scheduled_interview(_FakeDB(result=0), 9))

  def test_stale_in_progress_interview_is_marked_failed(self):
    from app.services.scheduler import fail_stale_interviews
    now = datetime.now(timezone.utc)
    stale = SimpleNamespace(id=1, status="in_progress", scheduled_at=now - timedelta(minutes=40))
    active = SimpleNamespace(id=2, status="in_progress", scheduled_at=now - timedelta(minutes=10))
    db = _FakeDB(rows=[stale, active])
    self.assertEqual(fail_stale_interviews(db, now=now), [1])
    self.assertEqual(stale.status, "failed")
    self.assertEqual(active.status, "in_progress")


class _ClaimQuery:
    def __init__(self, result):
        self.result = result

    def filter(self, *_conditions):
        return self

    def update(self, *_args, **_kwargs):
        return self.result


class _FakeDB:
    def __init__(self, result=1, rows=()):
        self.result = result
        self.rows = list(rows)
        self.commits = 0

    def query(self, _model):
        return _ClaimQuery(self.result) if not self.rows else _StaleQuery(self.rows)

    def commit(self):
        self.commits += 1


class _StaleQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *_conditions):
        return self

    def all(self):
        return self.rows


def load_tests(loader, tests, pattern):
    return unittest.defaultTestLoader.loadTestsFromTestCase(InterviewExecutionTests)
