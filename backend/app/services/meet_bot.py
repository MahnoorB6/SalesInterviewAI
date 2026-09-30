import asyncio
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright

from app.database.database import SessionLocal
from app.models.interview import Interview
from app.services.elevenlabs_agent import run_alena


PROFILE_DIR = Path("playwright_profile")
RECORDING_DIR = Path("data/recordings")

PROFILE_DIR.mkdir(parents=True, exist_ok=True)
RECORDING_DIR.mkdir(parents=True, exist_ok=True)


def update_recording_path(interview_id: int, path: str):
    """Save the Meet recording path."""

    db = SessionLocal()

    try:
        interview = db.query(Interview).filter(
            Interview.id == interview_id
        ).first()

        if interview:
            interview.recording_path = path
            db.commit()

    finally:
        db.close()


async def create_browser(playwright):
    """Open Chrome with the saved Google account."""

    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        channel="chrome",
        headless=False,
        permissions=["microphone", "camera"],
        record_video_dir=str(RECORDING_DIR),
        record_video_size={
            "width": 1280,
            "height": 720,
        },
        args=[
            "--disable-blink-features=AutomationControlled",
            "--autoplay-policy=no-user-gesture-required",
            "--window-size=900,600",
            "--window-position=50,50",
            "--force-device-scale-factor=1",
        ],
    )

    return context


async def join_meet(page, meet_link: str):
    """Open and join the Google Meet."""

    await page.goto(
        meet_link,
        wait_until="domcontentloaded",
    )

    await page.wait_for_timeout(5000)

    # Turn camera off.
    try:
        camera_button = page.get_by_role(
            "button",
            name="Turn off camera",
        )

        if await camera_button.is_visible():
            await camera_button.click()

    except Exception:
        pass

    # Join the meeting.
    join_buttons = [
        "Join now",
        "Ask to join",
    ]

    for button_name in join_buttons:
        try:
            button = page.get_by_role(
                "button",
                name=button_name,
            )

            if await button.is_visible():
                await button.click()
                break

        except Exception:
            pass

    await page.wait_for_timeout(5000)


async def leave_meet(page):
    """Leave Google Meet."""

    try:
        leave_button = page.get_by_role(
            "button",
            name="Leave call",
        )

        if await leave_button.is_visible():
            await leave_button.click()
            return

    except Exception:
        pass

    try:
        button = page.get_by_text(
            "Leave",
            exact=True,
        )

        if await button.is_visible():
            await button.click()

    except Exception:
        pass


async def run_meet_bot(interview_id: int, meet_link: str):
    """Run the complete Google Meet + Alena interview."""

    async with async_playwright() as playwright:

        context = await create_browser(playwright)

        page = (
            context.pages[0]
            if context.pages
            else await context.new_page()
        )

        try:
            print()
            print("=" * 40)
            print("        GOOGLE MEET BOT")
            print("=" * 40)
            print()

            print("Opening Google Meet...")
            await join_meet(page, meet_link)

            print("Google Meet joined.")
            print("Starting Alena...")

            # Run ElevenLabs in a background thread
            # so Playwright can continue controlling Meet.
            alena_result = await asyncio.to_thread(
                run_alena,
                interview_id,
            )

            print("Alena session ended.")

            await leave_meet(page)

            print("Google Meet left.")

            # Save browser recording path.
            try:
                video_path = await page.video.path()

                if video_path:
                    update_recording_path(
                        interview_id,
                        video_path,
                    )

            except Exception as error:
                print(f"Recording path error: {error}")

            return alena_result

        except Exception as error:
            print(f"Meet bot error: {error}")

            try:
                await leave_meet(page)
            except Exception:
                pass

            raise

        finally:
            await context.close()


if __name__ == "__main__":

    if len(sys.argv) < 3:
        print(
            "Usage: python meet_bot.py "
            "<interview_id> <meet_link>"
        )
        sys.exit(1)

    interview_id = int(sys.argv[1])
    meet_link = sys.argv[2]

    asyncio.run(
        run_meet_bot(
            interview_id,
            meet_link,
        )
    )