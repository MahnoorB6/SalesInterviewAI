import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.database.database import SessionLocal
from app.models.interview import Interview
from app.services.meet_bot import run_meet_bot


# ============================================================
# CONFIGURATION
# ============================================================

# Scheduler checks frequently so the bot does not wait
# until the exact interview time before starting Chrome.
CHECK_INTERVAL_SECONDS = 2

# Start Playwright this many seconds BEFORE the scheduled
# interview time.
#
# This gives Chrome / Google Meet time to:
#
#   1. Launch
#   2. Open the Meet URL
#   3. Load the Meet UI
#   4. Join the meeting
#   5. Enable Live Captions
#   6. Prepare the audio devices
#
# Alena should NOT be started by the scheduler itself.
# run_meet_bot() is responsible for starting Alena after
# the Meet side is ready.
PREPARE_BEFORE_SECONDS = 15

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


# ============================================================
# WINDOWS PLAYWRIGHT / PROACTOR THREAD
# ============================================================

def run_playwright_in_proactor_thread(
    meet_link: str,
    interview_id: int,
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

                loop.close()

            except Exception:
                pass

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

            return

        # ----------------------------------------------------
        # VERIFY MEET LINK
        # ----------------------------------------------------

        if not meet_link:

            print(
                f"[SCHEDULER] Interview #{interview_id} "
                "does not have a Meet link."
            )

            interview.status = "cancelled"

            db.commit()

            return

        # ----------------------------------------------------
        # VERIFY STATUS
        # ----------------------------------------------------

        if interview.status not in (
            "scheduled",
            "in_progress",
        ):

            print(
                f"[SCHEDULER] Interview #{interview_id} "
                f"has status '{interview.status}'. "
                "Skipping."
            )

            return

        # ----------------------------------------------------
        # MARK IN PROGRESS
        # ----------------------------------------------------

        if interview.status != "in_progress":

            interview.status = "in_progress"

            db.commit()

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

        await asyncio.to_thread(
            run_playwright_in_proactor_thread,
            meet_link,
            interview_id,
        )

        # ----------------------------------------------------
        # RELOAD INTERVIEW
        # ----------------------------------------------------

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

            return

        # ----------------------------------------------------
        # IMPORTANT STATUS HANDLING
        # ----------------------------------------------------

        # run_alena() is responsible for changing the interview
        # to COMPLETED when the candidate explicitly ends the
        # interview normally.
        #
        # Therefore this scheduler should NOT blindly change
        # every returned interview to completed.
        if interview.status == "completed":

            print(
                f"[SCHEDULER] Interview #{interview_id} "
                "already marked COMPLETED by interview flow."
            )

        elif interview.status == "interrupted":

            print(
                f"[SCHEDULER] Interview #{interview_id} "
                "finished as INTERRUPTED."
            )

        elif interview.status == "cancelled":

            print(
                f"[SCHEDULER] Interview #{interview_id} "
                "finished as CANCELLED."
            )

        elif interview.status == "in_progress":

            # If the Meet bot returned without the Alena flow
            # updating the status, do NOT falsely report a
            # successful completed interview.
            print(
                f"[SCHEDULER WARNING] "
                f"Interview #{interview_id} "
                "returned while still IN_PROGRESS."
            )

            print(
                "[SCHEDULER WARNING] "
                "The Meet/Alena flow exited before "
                "setting a final interview status."
            )

        else:

            print(
                f"[SCHEDULER] Interview #{interview_id} "
                f"finished with status: "
                f"{interview.status}"
            )

    except Exception as error:

        print()
        print("=" * 70)
        print(
            f"[SCHEDULER ERROR] Interview #{interview_id}"
        )
        print(
            f"[SCHEDULER ERROR] "
            f"{type(error).__name__}: {error}"
        )
        print("=" * 70)

        # ----------------------------------------------------
        # DATABASE ERROR STATUS
        # ----------------------------------------------------

        try:

            interview = (
                db.query(Interview)
                .filter(
                    Interview.id == interview_id
                )
                .first()
            )

            if interview:

                # Do not overwrite a completed/interrupted
                # interview because of a late scheduler exception.
                if interview.status not in (
                    "completed",
                    "interrupted",
                ):

                    interview.status = "cancelled"

                    db.commit()

                    print(
                        f"[SCHEDULER] Interview "
                        f"#{interview_id} "
                        "marked CANCELLED because "
                        "the scheduler failed."
                    )

        except Exception as db_error:

            print(
                "[SCHEDULER] "
                "Database update failed: "
                f"{type(db_error).__name__}: "
                f"{db_error}"
            )

    finally:

        db.close()

        # ----------------------------------------------------
        # REMOVE FROM ACTIVE SET
        # ----------------------------------------------------

        async with active_interviews_lock:

            active_interviews.discard(
                interview_id
            )

        print(
            f"[SCHEDULER] Task finished for "
            f"interview #{interview_id}."
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
                    Interview.status == "scheduled",
                    Interview.meet_link.isnot(None),
                )
                .all()
            )

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

                # Set status BEFORE creating the background
                # task so another scheduler cycle cannot select
                # this interview again.
                interview.status = "in_progress"

                db.commit()

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

                    try:

                        exception = (
                            completed_task.exception()
                        )

                        if exception:

                            print(
                                f"[SCHEDULER TASK ERROR] "
                                f"Interview #{interview_id}: "
                                f"{repr(exception)}"
                            )

                        else:

                            print(
                                f"[SCHEDULER TASK] "
                                f"Interview #{interview_id} "
                                "completed without an "
                                "unhandled exception."
                            )

                    except asyncio.CancelledError:

                        print(
                            f"[SCHEDULER] Interview "
                            f"#{interview_id} "
                            "task was cancelled."
                        )

                    except Exception as callback_error:

                        print(
                            "[SCHEDULER CALLBACK ERROR] "
                            f"{type(callback_error).__name__}: "
                            f"{callback_error}"
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