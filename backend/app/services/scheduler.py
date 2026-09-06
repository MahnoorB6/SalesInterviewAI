import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from app.database.database import SessionLocal
from app.models.interview import Interview
from app.services.meet_bot import run_meet_bot


CHECK_INTERVAL_SECONDS = 10

TIMEZONE = ZoneInfo("Asia/Karachi")


def run_playwright_in_proactor_thread(
    meet_link: str,
    interview_id: int,
):
    """
    Run the complete Playwright Meet bot inside its own
    Windows Proactor event loop.

    This is required because Playwright launches a
    subprocess and Windows SelectorEventLoop does not
    support async subprocesses.
    """

    print(
        "[PLAYWRIGHT THREAD] Creating Proactor event loop..."
    )

    loop = asyncio.ProactorEventLoop()

    asyncio.set_event_loop(loop)

    try:

        print(
            "[PLAYWRIGHT THREAD] Starting Meet bot..."
        )

        return loop.run_until_complete(
            run_meet_bot(
                meet_link=meet_link,
                interview_id=interview_id,
            )
        )

    finally:

        try:
            loop.run_until_complete(
                loop.shutdown_asyncgens()
            )
        except Exception:
            pass

        loop.close()

        print(
            "[PLAYWRIGHT THREAD] Proactor event loop closed."
        )


async def run_scheduled_interview(
    interview_id: int,
    meet_link: str,
):

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

        interview.status = "in_progress"

        db.commit()

        print(
            f"[SCHEDULER] Interview #{interview_id} "
            "marked IN_PROGRESS."
        )

        # --------------------------------------------------
        # RUN PLAYWRIGHT IN A SEPARATE PROACTOR THREAD
        # --------------------------------------------------

        await asyncio.to_thread(
            run_playwright_in_proactor_thread,
            meet_link,
            interview_id,
        )

        # --------------------------------------------------
        # INTERVIEW FINISHED
        # --------------------------------------------------

        interview = (
            db.query(Interview)
            .filter(
                Interview.id == interview_id
            )
            .first()
        )

        if interview:

            interview.status = "completed"

            db.commit()

            print(
                f"[SCHEDULER] Interview #{interview_id} "
                "marked COMPLETED."
            )

    except Exception as error:

        print(
            f"[SCHEDULER ERROR] Interview "
            f"#{interview_id}: "
            f"{repr(error)}"
        )

        try:

            interview = (
                db.query(Interview)
                .filter(
                    Interview.id == interview_id
                )
                .first()
            )

            if interview:

                interview.status = "failed"

                db.commit()

        except Exception as db_error:

            print(
                "[SCHEDULER] Database update failed: "
                f"{repr(db_error)}"
            )

    finally:

        db.close()


async def check_interviews():

    print("=" * 70)
    print("SalesInterviewAI Scheduler Started")
    print("=" * 70)

    while True:

        db = SessionLocal()

        try:

            now = datetime.now(TIMEZONE)

            print(
                "[SCHEDULER] Current Pakistan time: "
                f"{now.strftime('%Y-%m-%d %H:%M:%S')}"
            )

            interviews = (
                db.query(Interview)
                .filter(
                    Interview.status == "scheduled",
                    Interview.meet_link.isnot(None),
                )
                .all()
            )

            for interview in interviews:

                scheduled_at = interview.scheduled_at

                if scheduled_at.tzinfo is None:

                    scheduled_at = scheduled_at.replace(
                        tzinfo=TIMEZONE
                    )

                else:

                    scheduled_at = scheduled_at.astimezone(
                        TIMEZONE
                    )

                print(
                    f"[SCHEDULER] Interview #{interview.id} "
                    "scheduled for "
                    f"{scheduled_at.strftime('%Y-%m-%d %H:%M:%S')}"
                )

                if scheduled_at <= now:

                    print("=" * 70)
                    print(
                        "[SCHEDULER] DUE INTERVIEW FOUND: "
                        f"#{interview.id}"
                    )
                    print("=" * 70)

                    interview_id = interview.id
                    meet_link = interview.meet_link

                    # Prevent this interview from being picked
                    # again by the scheduler.
                    interview.status = "in_progress"

                    db.commit()

                    asyncio.create_task(
                        run_scheduled_interview(
                            interview_id=interview_id,
                            meet_link=meet_link,
                        )
                    )

        except Exception as error:

            print(
                "[SCHEDULER ERROR] "
                f"{repr(error)}"
            )

        finally:

            db.close()

        await asyncio.sleep(
            CHECK_INTERVAL_SECONDS
        )


def start_scheduler():

    print(
        "[SCHEDULER] Creating scheduler task..."
    )

    asyncio.create_task(
        check_interviews()
    )