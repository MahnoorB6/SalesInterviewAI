import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.database.database import SessionLocal
from app.models.interview import Interview
from app.statuses import InterviewStatus, can_transition_interview
from app.services.meet_bot import run_meet_bot
from app.transcripts import set_structured_transcript_state
from app.logging_config import (
    configure_backend_logging,
    reset_interview_context,
    set_interview_context,
    set_interview_stage,
)


configure_backend_logging()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# ============================================================
# CONFIGURATION
# ============================================================

# Scheduler checks frequently so the bot does not wait
# until the exact interview time before starting Chrome.
CHECK_INTERVAL_SECONDS = 2

# Start Playwright early enough to load the browser and Meet
# pre-join screen. The Meet Join button is held until scheduled_at.
#
# This gives Chrome / Google Meet time to:
#
#   1. Launch
#   2. Open the Meet URL
#   3. Load the Meet UI
#   4. Wait at the pre-join screen for scheduled_at
#   5. Join at the scheduled time, then prepare audio
#
# Alena should NOT be started by the scheduler itself.
# run_meet_bot() is responsible for starting Alena after
# the Meet side is ready.
PREPARE_BEFORE_SECONDS = 30

TIMEZONE = ZoneInfo("Asia/Karachi")


# ============================================================
# ACTIVE INTERVIEWS
# ============================================================

# Keep track of interviews already launched by this scheduler
# process.
#
# The database status is also changed to "in_progress", but
# this in-memory set provides an additional protection against
# duplicate background tasks during the same process.
active_interviews = set()

active_interviews_lock = asyncio.Lock()


def claim_scheduled_interview(db, interview_id: int) -> bool:
    """Atomically transition scheduled -> in_progress; only one worker wins."""
    claimed = (
        db.query(Interview)
        .filter(
            Interview.id == interview_id,
            Interview.status == InterviewStatus.SCHEDULED.value,
        )
        .update(
            {Interview.status: InterviewStatus.IN_PROGRESS.value},
            synchronize_session=False,
        )
    )
    db.commit()
    if claimed:
        logger.info(
            "Interview status transition previous=%s new=%s reason=scheduler claimed scheduled interview origin=claim_scheduled_interview",
            InterviewStatus.SCHEDULED.value,
            InterviewStatus.IN_PROGRESS.value,
            extra={"interview_id": interview_id, "stage": "status_claim"},
        )
    return claimed == 1


def compare_and_set_interview_status(
    db,
    interview_id: int,
    expected_status: str,
    target_status: str,
) -> bool:
    """Commit a status transition only if no concurrent path changed it."""
    changed = (
        db.query(Interview)
        .filter(
            Interview.id == interview_id,
            Interview.status == expected_status,
        )
        .update(
            {Interview.status: target_status},
            synchronize_session=False,
        )
    )
    if changed:
        db.commit()
    return changed == 1


def fail_stale_interviews(db, now=None) -> list[int]:
    """Fail executions too old to resume safely after a process restart."""
    now = now or datetime.now(timezone.utc)
    stale_before = now - timedelta(minutes=35)
    stale_rows = db.query(Interview).filter(
        Interview.status == InterviewStatus.IN_PROGRESS.value
    ).all()
    failed_ids = []
    for interview in stale_rows:
        scheduled = interview.scheduled_at
        if scheduled and scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=TIMEZONE)
        if scheduled and scheduled.astimezone(timezone.utc) < stale_before:
            previous_status = interview.status
            if not compare_and_set_interview_status(
                db,
                interview.id,
                InterviewStatus.IN_PROGRESS.value,
                InterviewStatus.FAILED.value,
            ):
                continue
            logger.warning(
                "Interview status transition previous=%s new=%s reason=stale in-progress interview recovery threshold exceeded origin=fail_stale_interviews",
                previous_status,
                InterviewStatus.FAILED.value,
                extra={"interview_id": interview.id, "stage": "stale_recovery"},
            )
            interview.status = InterviewStatus.FAILED.value
            failed_ids.append(interview.id)
            try:
                set_structured_transcript_state(interview, InterviewStatus.FAILED.value)
            except (OSError, ValueError, json.JSONDecodeError) as transcript_error:
                print(f"[SCHEDULER] Could not finalize stale transcript #{interview.id}: {type(transcript_error).__name__}")
    return failed_ids


# ============================================================
# WINDOWS PLAYWRIGHT / PROACTOR THREAD
# ============================================================

def run_playwright_in_proactor_thread(
    meet_link: str,
    interview_id: int,
    scheduled_at: datetime | None = None,
):
    """
    Run the Playwright Meet bot inside a dedicated Windows
    Proactor event loop.

    Playwright uses Windows subprocesses, so it must run in
    a Proactor event loop.

    IMPORTANT:
    This function does NOT create another event loop inside
    the main FastAPI scheduler.
    """

    print()
    print("=" * 70)
    print(
        f"[PLAYWRIGHT THREAD] STARTING INTERVIEW #{interview_id}"
    )
    print("=" * 70)

    print(
        f"[PLAYWRIGHT THREAD] Meet link: {meet_link}"
    )

    loop = None

    try:

        # ----------------------------------------------------
        # CREATE WINDOWS PROACTOR EVENT LOOP
        # ----------------------------------------------------

        try:

            loop = asyncio.ProactorEventLoop()

        except AttributeError:

            # Compatibility fallback for Python versions where
            # ProactorEventLoop is exposed differently.
            loop = asyncio.new_event_loop()

        asyncio.set_event_loop(loop)

        print(
            "[PLAYWRIGHT THREAD] "
            "Proactor event loop created."
        )

        # ----------------------------------------------------
        # START MEET BOT
        # ----------------------------------------------------

        print(
            f"[PLAYWRIGHT THREAD] "
            f"Starting run_meet_bot() for "
            f"interview #{interview_id}"
        )

        result = loop.run_until_complete(
            run_meet_bot(
                meet_link=meet_link,
                interview_id=interview_id,
                scheduled_at=scheduled_at,
            )
        )

        print(
            f"[PLAYWRIGHT THREAD] "
            f"Meet bot finished for interview "
            f"#{interview_id}."
        )

        return result

    except Exception as error:

        print()
        print("=" * 70)
        print(
            f"[PLAYWRIGHT THREAD ERROR] "
            f"Interview #{interview_id}"
        )
        print(
            f"[PLAYWRIGHT THREAD ERROR] "
            f"{type(error).__name__}: {error}"
        )
        print("=" * 70)

        raise

    finally:

        if loop is not None:

            try:

                loop.run_until_complete(
                    loop.shutdown_asyncgens()
                )

            except Exception:
                pass

            try:
                # run_meet_bot may use asyncio.to_thread while Playwright is
                # active. Wait for any remaining default-executor workers
                # before closing the event loop they may still depend on.
                loop.run_until_complete(
                    loop.shutdown_default_executor()
                )

            except Exception as cleanup_error:
                print(
                    "[PLAYWRIGHT THREAD] Default executor shutdown failed: "
                    f"{type(cleanup_error).__name__}: {cleanup_error}"
                )

            try:

                loop.close()

            except Exception:
                pass

            asyncio.set_event_loop(None)

        print(
            "[PLAYWRIGHT THREAD] "
            "Proactor event loop closed."
        )


# ============================================================
# GET INTERVIEW
# ============================================================

def get_interview(
    interview_id: int,
):
    """
    Load one interview using a short-lived database session.

    This helper is intentionally synchronous because it is
    called from the scheduler/background workflow.
    """

    db = SessionLocal()

    try:

        return (
            db.query(Interview)
            .filter(
                Interview.id == interview_id
            )
            .first()
        )

    finally:

        db.close()


# ============================================================
# RUN ONE SCHEDULED INTERVIEW
# ============================================================

async def run_scheduled_interview(
    interview_id: int,
    meet_link: str,
):
    """
    Run one scheduled interview.

    Flow:

        Scheduler
            ↓
        Playwright
            ↓
        Google Meet
            ↓
        Meet bot joins
            ↓
        Meet bot prepares captions/audio
            ↓
        Alena starts
            ↓
        Interview
            ↓
        Meet bot exits
            ↓
        Alena/transcript code controls final status
    """

    log_context = set_interview_context(interview_id, "scheduler_start")
    stage = "load_interview"

    print()
    print("=" * 70)
    print(
        f"[SCHEDULER] STARTING INTERVIEW #{interview_id}"
    )
    print(
        f"[SCHEDULER] Meet: {meet_link}"
    )
    print("=" * 70)

    db = SessionLocal()

    try:

        # ----------------------------------------------------
        # GET INTERVIEW
        # ----------------------------------------------------

        interview = (
            db.query(Interview)
            .filter(
                Interview.id == interview_id
            )
            .first()
        )

        if not interview:

            print(
                f"[SCHEDULER] Interview #{interview_id} "
                "was not found."
            )

            return {"outcome": "skipped", "status": None}

        scheduled_at = interview.scheduled_at
        if scheduled_at is not None:
            scheduled_at = (
                scheduled_at.replace(tzinfo=TIMEZONE)
                if scheduled_at.tzinfo is None
                else scheduled_at.astimezone(TIMEZONE)
            )

        # ----------------------------------------------------
        # VERIFY MEET LINK
        # ----------------------------------------------------

        if not meet_link:
            stage = "validate_meet_link"
            set_interview_stage(stage)
            previous_status = interview.status
            logger.error(
                "Interview status transition previous=%s new=%s reason=missing Meet link origin=run_scheduled_interview",
                previous_status,
                InterviewStatus.FAILED.value,
                extra={"interview_id": interview_id, "stage": "validate_meet_link"},
            )

            print(
                f"[SCHEDULER] Interview #{interview_id} "
                "does not have a Meet link."
            )

            if compare_and_set_interview_status(
                db,
                interview_id,
                previous_status,
                InterviewStatus.FAILED.value,
            ):
                interview.status = InterviewStatus.FAILED.value

            return {
                "outcome": "handled_failure",
                "status": interview.status,
                "error": "Interview does not have a Meet link.",
            }

        # ----------------------------------------------------
        # VERIFY STATUS
        # ----------------------------------------------------

        if interview.status != InterviewStatus.IN_PROGRESS.value:

            print(
                f"[SCHEDULER] Interview #{interview_id} "
                f"has status '{interview.status}'. "
                "Skipping."
            )

            return {"outcome": "skipped", "status": interview.status}

        # ----------------------------------------------------
        # MARK IN PROGRESS
        # ----------------------------------------------------

        # Status is atomically claimed by the scheduler before this task starts.

        print(
            f"[SCHEDULER] Interview #{interview_id} "
            "is IN_PROGRESS."
        )

        # ----------------------------------------------------
        # START PLAYWRIGHT
        # ----------------------------------------------------

        print()
        print("=" * 70)
        print(
            f"[SCHEDULER] LAUNCHING MEET BOT "
            f"FOR INTERVIEW #{interview_id}"
        )
        print("=" * 70)

        print(
            f"[SCHEDULER] Meet link: {meet_link}"
        )

        print(
            "[SCHEDULER] "
            "Playwright will prepare Google Meet "
            "before the scheduled interview time."
        )

        print("=" * 70)
        print()

        stage = "run_meet_bot"
        set_interview_stage(stage)
        await asyncio.to_thread(
            run_playwright_in_proactor_thread,
            meet_link,
            interview_id,
            scheduled_at,
        )

        # ----------------------------------------------------
        # RELOAD INTERVIEW
        # ----------------------------------------------------

        stage = "reload_final_status"
        set_interview_stage(stage)
        db.expire_all()

        interview = (
            db.query(Interview)
            .filter(
                Interview.id == interview_id
            )
            .first()
        )

        if not interview:

            print(
                f"[SCHEDULER] Interview #{interview_id} "
                "no longer exists."
            )

            return {"outcome": "skipped", "status": None}

        # ----------------------------------------------------
        # IMPORTANT STATUS HANDLING
        # ----------------------------------------------------

        # run_alena() is responsible for changing the interview
        # to COMPLETED when the candidate explicitly ends the
        # interview normally.
        #
        # Therefore this scheduler should NOT blindly change
        # every returned interview to completed.
        if interview.status == InterviewStatus.COMPLETED.value:

            print(
                f"[SCHEDULER] Interview #{interview_id} "
                "already marked COMPLETED by interview flow."
            )

        elif interview.status == InterviewStatus.INTERRUPTED.value:

            print(
                f"[SCHEDULER] Interview #{interview_id} "
                "finished as INTERRUPTED."
            )

        elif interview.status == InterviewStatus.CANCELLED.value:

            print(
                f"[SCHEDULER] Interview #{interview_id} "
                "finished as CANCELLED."
            )

        elif interview.status == InterviewStatus.IN_PROGRESS.value:

            # If the Meet bot returned without the Alena flow
            # updating the status, do NOT falsely report a
            # successful completed interview.
            logger.warning(
                "Meet/Alena flow returned without a final status; marking interrupted",
                extra={"interview_id": interview_id, "stage": "reload_final_status"},
            )
            print(
                f"[SCHEDULER WARNING] Interview #{interview_id} returned "
                "without a final status; marking it INTERRUPTED."
            )
            compare_and_set_interview_status(
                db,
                interview_id,
                InterviewStatus.IN_PROGRESS.value,
                InterviewStatus.INTERRUPTED.value,
            )
            db.expire_all()
            interview = (
                db.query(Interview)
                .filter(Interview.id == interview_id)
                .first()
            )

        else:

            print(
                f"[SCHEDULER] Interview #{interview_id} "
                f"finished with status: "
                f"{interview.status}"
            )

        return {"outcome": "finished", "status": interview.status}

    except asyncio.CancelledError:
        logger.warning(
            "Scheduler task cancelled during interview execution",
            extra={"interview_id": interview_id, "stage": stage},
        )
        try:
            interview = (
                db.query(Interview)
                .filter(Interview.id == interview_id)
                .first()
            )
            if interview and interview.status == InterviewStatus.IN_PROGRESS.value:
                compare_and_set_interview_status(
                    db,
                    interview_id,
                    InterviewStatus.IN_PROGRESS.value,
                    InterviewStatus.INTERRUPTED.value,
                )
        except Exception:
            logger.exception(
                "Could not persist interrupted status after task cancellation",
                extra={"interview_id": interview_id, "stage": "status_persistence"},
            )
        raise

    except Exception as error:
        logger.exception(
            "Exception escaped interview execution; current scheduler stage=%s",
            stage,
            extra={"interview_id": interview_id, "stage": stage},
        )

        print()
        print("=" * 70)
        print(f"[SCHEDULER ERROR] Interview #{interview_id}")
        print(f"[SCHEDULER ERROR] {type(error).__name__}: {error}")
        print("=" * 70)

        # Preserve existing final states and transition rules. Return the
        # handled outcome so the task callback does not label it successful.
        persisted_status = None
        try:
            interview = (
                db.query(Interview)
                .filter(Interview.id == interview_id)
                .first()
            )
            if interview:
                if interview.status not in (
                    InterviewStatus.COMPLETED.value,
                    InterviewStatus.INTERRUPTED.value,
                ):
                    if can_transition_interview(
                        interview.status, InterviewStatus.FAILED.value
                    ):
                        previous_status = interview.status
                        if compare_and_set_interview_status(
                            db,
                            interview_id,
                            previous_status,
                            InterviewStatus.FAILED.value,
                        ):
                            logger.error(
                                "Interview status transition previous=%s new=%s reason=scheduler execution exception (%s) origin=run_scheduled_interview",
                                previous_status,
                                InterviewStatus.FAILED.value,
                                type(error).__name__,
                                extra={"interview_id": interview_id, "stage": "status_update"},
                            )
                    db.expire_all()
                    interview = (
                        db.query(Interview)
                        .filter(Interview.id == interview_id)
                        .first()
                    )
                persisted_status = interview.status
                print(
                    f"[SCHEDULER] Interview #{interview_id} "
                    f"persisted status={persisted_status!r} after scheduler error "
                    f"{type(error).__name__}: {error}"
                )
        except Exception as db_error:
            logger.exception(
                "Scheduler status persistence exception after original execution error",
                extra={"interview_id": interview_id, "stage": "status_persistence"},
            )
            print(
                "[SCHEDULER] Database update failed: "
                f"{type(db_error).__name__}: {db_error}"
            )

        return {
            "outcome": "handled_failure",
            "status": persisted_status,
            "error": f"{type(error).__name__}: {error}",
        }

    finally:

        db.close()

        # ----------------------------------------------------
        # REMOVE FROM ACTIVE SET
        # ----------------------------------------------------

        async with active_interviews_lock:

            active_interviews.discard(
                interview_id
            )

        reset_interview_context(log_context)

        print(
            f"[SCHEDULER] Task finished for "
            f"interview #{interview_id}."
        )


def report_scheduled_task_outcome(completed_task, interview_id: int) -> None:
    """Log the task result separately from persisted interview status changes."""
    try:
        if completed_task.cancelled():
            print(f"[SCHEDULER TASK CANCELLED] Interview #{interview_id} task was cancelled.")
            return

        exception = completed_task.exception()
        if exception is not None:
            print(
                f"[SCHEDULER TASK ERROR] Interview #{interview_id} "
                f"unhandled {type(exception).__name__}: {exception}"
            )
            return

        result = completed_task.result()
        if not isinstance(result, dict):
            print(
                f"[SCHEDULER TASK] Interview #{interview_id} "
                "finished without an outcome result."
            )
            return

        outcome = result.get("outcome")
        status = result.get("status")
        if outcome == "handled_failure":
            print(
                f"[SCHEDULER TASK FAILURE] Interview #{interview_id} "
                f"handled; persisted status={status!r}; "
                f"reason={result.get('error', 'unknown error')}"
            )
        elif outcome == "finished" and status == InterviewStatus.COMPLETED.value:
            print(f"[SCHEDULER TASK SUCCESS] Interview #{interview_id} completed.")
        elif outcome == "finished" and status == InterviewStatus.INTERRUPTED.value:
            print(f"[SCHEDULER TASK] Interview #{interview_id} finished as INTERRUPTED.")
        elif outcome == "finished" and status == InterviewStatus.CANCELLED.value:
            print(
                f"[SCHEDULER TASK] Interview #{interview_id} finished normally "
                "with persisted status=CANCELLED."
            )
        elif outcome == "finished" and status == InterviewStatus.FAILED.value:
            print(
                f"[SCHEDULER TASK FAILURE] Interview #{interview_id} "
                "finished with persisted status=FAILED."
            )
        elif outcome == "finished":
            print(
                f"[SCHEDULER TASK] Interview #{interview_id} "
                f"finished with persisted status={status!r}."
            )
        else:
            print(
                f"[SCHEDULER TASK] Interview #{interview_id} "
                f"outcome={outcome!r}; persisted status={status!r}."
            )
    except asyncio.CancelledError:
        print(f"[SCHEDULER TASK CANCELLED] Interview #{interview_id} task was cancelled.")
    except Exception as callback_error:
        print(
            f"[SCHEDULER CALLBACK ERROR] Interview #{interview_id} "
            f"{type(callback_error).__name__}: {callback_error}"
        )


# ============================================================
# CHECK FOR DUE / PREPARING INTERVIEWS
# ============================================================

async def check_interviews():

    print()
    print("=" * 70)
    print("SalesInterviewAI Scheduler Started")
    print("=" * 70)

    print(
        f"[SCHEDULER] Timezone: {TIMEZONE}"
    )

    print(
        f"[SCHEDULER] Check interval: "
        f"{CHECK_INTERVAL_SECONDS} seconds"
    )

    print(
        f"[SCHEDULER] Meet preparation lead time: "
        f"{PREPARE_BEFORE_SECONDS} seconds"
    )

    print("=" * 70)
    print()

    while True:

        db = SessionLocal()

        try:

            # ------------------------------------------------
            # CURRENT PAKISTAN TIME
            # ------------------------------------------------

            now = datetime.now(TIMEZONE)

            print(
                "[SCHEDULER] Current Pakistan time: "
                f"{now.strftime('%Y-%m-%d %H:%M:%S')}"
            )

            # ------------------------------------------------
            # GET SCHEDULED INTERVIEWS
            # ------------------------------------------------

            interviews = (
                db.query(Interview)
                .filter(
                    Interview.status == InterviewStatus.SCHEDULED.value,
                    Interview.meet_link.isnot(None),
                )
                .all()
            )

            # A browser/voice session cannot be resumed after a process restart.
            # Fail stale executions after the 30-minute cap plus cleanup grace.
            fail_stale_interviews(db)

            print(
                "[SCHEDULER] Scheduled interviews found: "
                f"{len(interviews)}"
            )

            # ------------------------------------------------
            # CHECK EACH INTERVIEW
            # ------------------------------------------------

            for interview in interviews:

                interview_id = interview.id

                # ------------------------------------------------
                # DUPLICATE PROTECTION
                # ------------------------------------------------

                async with active_interviews_lock:

                    if interview_id in active_interviews:

                        print(
                            f"[SCHEDULER] Interview "
                            f"#{interview_id} "
                            "is already running."
                        )

                        continue

                # ------------------------------------------------
                # VERIFY MEET LINK
                # ------------------------------------------------

                meet_link = (
                    interview.meet_link
                )

                if not meet_link:

                    print(
                        f"[SCHEDULER] Interview "
                        f"#{interview_id} "
                        "has no Meet link."
                    )

                    continue

                # ------------------------------------------------
                # GET SCHEDULED TIME
                # ------------------------------------------------

                scheduled_at = (
                    interview.scheduled_at
                )

                if scheduled_at is None:

                    print(
                        f"[SCHEDULER] Interview "
                        f"#{interview_id} "
                        "has no scheduled_at value."
                    )

                    continue

                # ------------------------------------------------
                # NORMALIZE TIMEZONE
                # ------------------------------------------------

                if scheduled_at.tzinfo is None:

                    scheduled_at = (
                        scheduled_at.replace(
                            tzinfo=TIMEZONE
                        )
                    )

                else:

                    scheduled_at = (
                        scheduled_at.astimezone(
                            TIMEZONE
                        )
                    )

                # ------------------------------------------------
                # CALCULATE PREPARATION TIME
                # ------------------------------------------------

                prepare_at = (
                    scheduled_at
                    - timedelta(
                        seconds=PREPARE_BEFORE_SECONDS
                    )
                )

                print(
                    f"[SCHEDULER] Interview "
                    f"#{interview_id} "
                    f"scheduled for "
                    f"{scheduled_at.strftime('%Y-%m-%d %H:%M:%S')}"
                )

                print(
                    f"[SCHEDULER] Interview "
                    f"#{interview_id} "
                    f"preparation starts at "
                    f"{prepare_at.strftime('%Y-%m-%d %H:%M:%S')}"
                )

                # ------------------------------------------------
                # NOT YET TIME
                # ------------------------------------------------

                if now < prepare_at:

                    continue

                # ------------------------------------------------
                # INTERVIEW IS READY TO PREPARE
                # ------------------------------------------------

                print()
                print("=" * 70)
                print(
                    "[SCHEDULER] INTERVIEW READY "
                    "FOR MEET PREPARATION"
                )
                print(
                    f"[SCHEDULER] Interview: #{interview_id}"
                )
                print(
                    "[SCHEDULER] Scheduled time: "
                    f"{scheduled_at.strftime('%Y-%m-%d %H:%M:%S')}"
                )
                print(
                    "[SCHEDULER] Preparation time: "
                    f"{prepare_at.strftime('%Y-%m-%d %H:%M:%S')}"
                )
                print(
                    "[SCHEDULER] Current time: "
                    f"{now.strftime('%Y-%m-%d %H:%M:%S')}"
                )
                print(
                    "[SCHEDULER] Meet link: "
                    f"{meet_link}"
                )
                print("=" * 70)

                # ------------------------------------------------
                # CLAIM INTERVIEW
                # ------------------------------------------------

                # Compare-and-set persisted status to guard against duplicate
                # scheduler instances and polling races.
                if not claim_scheduled_interview(db, interview_id):
                    continue

                print(
                    f"[SCHEDULER] Interview "
                    f"#{interview_id} claimed."
                )

                # ------------------------------------------------
                # ADD TO ACTIVE SET
                # ------------------------------------------------

                async with active_interviews_lock:

                    active_interviews.add(
                        interview_id
                    )

                # ------------------------------------------------
                # START BACKGROUND TASK
                # ------------------------------------------------

                task = asyncio.create_task(
                    run_scheduled_interview(
                        interview_id=interview_id,
                        meet_link=meet_link,
                    )
                )

                print(
                    f"[SCHEDULER] "
                    f"Background task created for "
                    f"interview #{interview_id}."
                )

                # ------------------------------------------------
                # TASK ERROR CALLBACK
                # ------------------------------------------------

                def task_done_callback(
                    completed_task,
                    interview_id=interview_id,
                ):
                    report_scheduled_task_outcome(
                        completed_task,
                        interview_id,
                    )

                task.add_done_callback(
                    task_done_callback
                )

        except Exception as error:

            print()
            print("=" * 70)
            print("[SCHEDULER ERROR]")
            print(
                f"{type(error).__name__}: {error}"
            )
            print("=" * 70)

        finally:

            db.close()

        # ----------------------------------------------------
        # WAIT BEFORE NEXT CHECK
        # ----------------------------------------------------

        await asyncio.sleep(
            CHECK_INTERVAL_SECONDS
        )


# ============================================================
# START SCHEDULER
# ============================================================

def start_scheduler():

    print(
        "[SCHEDULER] Creating scheduler task..."
    )

    task = asyncio.create_task(
        check_interviews()
    )

    print(
        "[SCHEDULER] Scheduler task created."
    )

    return task
