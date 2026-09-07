
import asyncio
import os

from playwright.async_api import async_playwright

from app.database.database import SessionLocal
from app.models.interview import Interview
from app.services.elevenlabs_agent import run_alena


# ============================================================
# PATHS
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)

PROFILE_DIR = os.path.join(BASE_DIR, "playwright_profile")
RECORDING_DIR = os.path.join(BASE_DIR, "data", "recordings")

os.makedirs(PROFILE_DIR, exist_ok=True)
os.makedirs(RECORDING_DIR, exist_ok=True)


# ============================================================
# UPDATE INTERVIEW FILES
# ============================================================

def update_interview_files(interview_id, transcript_path=None, recording_path=None):
    db = SessionLocal()

    try:
        interview = db.query(Interview).filter(
            Interview.id == interview_id
        ).first()

        if not interview:
            print(f"[DB] Interview #{interview_id} not found.")
            return

        if transcript_path:
            interview.transcript_path = transcript_path

        if recording_path:
            interview.recording_path = recording_path

        db.commit()

        print(f"[DB] Interview #{interview_id} files updated.")

    except Exception as e:
        db.rollback()
        print(f"[DB ERROR] {e}")

    finally:
        db.close()


# ============================================================
# LEAVE GOOGLE MEET
# ============================================================

async def leave_google_meet(page):
    print("[MEET] Leaving Google Meet...")

    try:
        # Try normal Leave call button
        buttons = page.get_by_role("button")

        count = await buttons.count()

        for i in range(count):
            try:
                button = buttons.nth(i)

                label = await button.get_attribute("aria-label")

                if label:
                    label_lower = label.lower()

                    if (
                        "leave call" in label_lower
                        or "leave meeting" in label_lower
                    ):
                        await button.click()
                        print("[MEET] Leave button clicked.")
                        return

            except Exception:
                continue

        # Fallback: press Escape
        await page.keyboard.press("Escape")

    except Exception as e:
        print(f"[MEET] Leave error: {e}")


# ============================================================
# MAIN MEET BOT
# ============================================================

async def run_meet_bot(interview_id, meet_link):

    print()
    print("=" * 70)
    print("SalesInterviewAI - ALENA AUTOMATIC MEET BOT")
    print("=" * 70)
    print(f"Interview ID: {interview_id}")
    print(f"Meet link: {meet_link}")
    print(f"Chrome profile: {PROFILE_DIR}")
    print(f"Recording dir: {RECORDING_DIR}")
    print("=" * 70)

    video_path = None
    transcript_path = None

    async with async_playwright() as p:

        browser = None
        context = None
        page = None

        try:

            # ====================================================
            # 1. START GOOGLE CHROME
            # ====================================================

            print("[1] Starting Google Chrome...")

            context = await p.chromium.launch_persistent_context(
                user_data_dir=PROFILE_DIR,
                channel="chrome",
                headless=False,

                # Recording
                record_video_dir=RECORDING_DIR,
                record_video_size={
                    "width": 1280,
                    "height": 720
                },

                # IMPORTANT:
                # Force Chrome to start small and NOT maximized
                args=[
                    "--window-size=900,600",
                    "--window-position=50,50",
                    "--start-normal",

                    "--disable-blink-features=AutomationControlled",

                    "--use-fake-ui-for-media-stream",

                    "--autoplay-policy=no-user-gesture-required",
                ],

                viewport={
                    "width": 900,
                    "height": 600
                },
            )

            print("[CHROME] Google Chrome started.")

            # ====================================================
            # 2. OPEN GOOGLE MEET
            # ====================================================

            print("[2] Opening Google Meet...")

            page = context.pages[0] if context.pages else await context.new_page()

            await page.goto(
                meet_link,
                wait_until="domcontentloaded",
                timeout=60000
            )

            print("[MEET] Google Meet page opened.")

            await page.wait_for_timeout(5000)

            # ====================================================
            # FORCE WINDOW SMALL / NORMAL
            # ====================================================

            print("[MEET] Forcing browser window to normal size...")

            try:
                await page.evaluate("""
                    () => {
                        window.resizeTo(900, 600);
                        window.moveTo(50, 50);
                    }
                """)
            except Exception as e:
                print(f"[MEET] Browser resize script skipped: {e}")

            # ====================================================
            # ZOOM OUT GOOGLE MEET
            # ====================================================

            print("[MEET] Zooming Meet out...")

            try:
                await page.keyboard.press("Control+-")
                await page.keyboard.press("Control+-")
                await page.keyboard.press("Control+-")
            except Exception as e:
                print(f"[MEET] Zoom error: {e}")

            await page.wait_for_timeout(2000)

            # ====================================================
            # IMPORTANT DEBUG PAUSE
            # ====================================================

            print()
            print("=" * 70)
            print("GOOGLE MEET WINDOW SHOULD NOW BE SMALL")
            print("=" * 70)
            print()
            print("Before continuing, check Google Meet Audio settings.")
            print()
            print("Set:")
            print("Microphone -> Voicemeeter Out B1")
            print("Speaker     -> CABLE Input")
            print()
            print("Then continue with the bot.")
            print("=" * 70)

            # ====================================================
            # 3. TURN CAMERA OFF
            # ====================================================

            print("[3] Turning camera off...")

            try:

                camera_buttons = page.get_by_role("button")

                count = await camera_buttons.count()

                camera_clicked = False

                for i in range(count):

                    try:

                        button = camera_buttons.nth(i)

                        label = await button.get_attribute("aria-label")

                        if label:

                            label_lower = label.lower()

                            if (
                                "turn off camera" in label_lower
                                or "camera" in label_lower
                            ):

                                await button.click()

                                print("[MEET] Camera button clicked.")

                                camera_clicked = True

                                break

                    except Exception:
                        continue

                if not camera_clicked:
                    print("[MEET] Camera button not found.")

            except Exception as e:
                print(f"[MEET] Camera error: {e}")

            # ====================================================
            # 4. CHECK MICROPHONE
            # ====================================================

            print("[4] Checking microphone...")

            try:

                mic_buttons = page.get_by_role("button")

                count = await mic_buttons.count()

                mic_found = False

                for i in range(count):

                    try:

                        button = mic_buttons.nth(i)

                        label = await button.get_attribute("aria-label")

                        if label:

                            label_lower = label.lower()

                            if "microphone" in label_lower:

                                print(f"[MEET] Microphone state: {label}")

                                mic_found = True

                                break

                    except Exception:
                        continue

                if not mic_found:
                    print("[MEET] Microphone button not found.")

            except Exception as e:
                print(f"[MEET] Microphone check error: {e}")

            # ====================================================
            # 5. LOOK FOR JOIN BUTTON
            # ====================================================

            print("[5] Looking for Join button...")

            await page.wait_for_timeout(2000)

            joined = False

            # Try "Join now"
            try:

                join_button = page.get_by_role(
                    "button",
                    name="Join now"
                )

                if await join_button.count() > 0:

                    await join_button.first.click()

                    print("[MEET] JOIN button clicked.")

                    joined = True

            except Exception:
                pass

            # Try "Ask to join"
            if not joined:

                try:

                    ask_button = page.get_by_role(
                        "button",
                        name="Ask to join"
                    )

                    if await ask_button.count() > 0:

                        await ask_button.first.click()

                        print("[MEET] ASK TO JOIN button clicked.")

                        joined = True

                except Exception:
                    pass

            # Fallback text search
            if not joined:

                try:

                    buttons = page.get_by_role("button")

                    count = await buttons.count()

                    for i in range(count):

                        try:

                            button = buttons.nth(i)

                            text = await button.inner_text()

                            text_lower = text.lower()

                            if (
                                "join now" in text_lower
                                or "ask to join" in text_lower
                            ):

                                await button.click()

                                print("[MEET] Join button clicked.")

                                joined = True

                                break

                        except Exception:
                            continue

                except Exception as e:
                    print(f"[MEET] Join search error: {e}")

            if not joined:

                print("[MEET] Join button not found.")
                print("[MEET] Please check the browser manually.")

            # ====================================================
            # WAIT FOR MEETING
            # ====================================================

            print("[MEET] Waiting for meeting...")

            await page.wait_for_timeout(10000)

            print()
            print("=" * 70)
            print("GOOGLE MEET READY")
            print("=" * 70)
            print()

            # ====================================================
            # START ALENA
            # ====================================================

            print("STARTING ALENA")

            print(f"Interview ID: {interview_id}")

            try:

                # run_alena is synchronous, so run it in a thread
                alena_result = await asyncio.to_thread(
                    run_alena,
                    interview_id
                )

                # ====================================================
                # PROCESS ALENA RESULT
                # ====================================================

                if isinstance(alena_result, dict):

                    transcript_path = alena_result.get(
                        "transcript_path"
                    )

                elif isinstance(alena_result, str):

                    transcript_path = alena_result

                print("[ALENA] Interview finished.")

            except Exception as e:

                print()
                print("=" * 70)
                print("[ALENA ERROR]")
                print("=" * 70)
                print(e)
                print("=" * 70)

            # ====================================================
            # LEAVE MEETING
            # ====================================================

            await leave_google_meet(page)

            await page.wait_for_timeout(3000)

            # ====================================================
            # GET VIDEO PATH
            # ====================================================

            try:

                video_path = await page.video.path()

                print(f"[RECORDING] Video: {video_path}")

            except Exception as e:

                print(f"[RECORDING] Video path unavailable: {e}")

        except Exception as e:

            print()
            print("=" * 70)
            print("[MEET BOT ERROR]")
            print("=" * 70)
            print(e)
            print("=" * 70)

        finally:

            # ====================================================
            # UPDATE DATABASE
            # ====================================================

            try:

                update_interview_files(
                    interview_id=interview_id,
                    transcript_path=transcript_path,
                    recording_path=video_path
                )

            except Exception as e:

                print(f"[DB] Could not update files: {e}")

            # ====================================================
            # KEEP CHROME OPEN FOR DEBUGGING
            # ====================================================

            if page:

                print()
                print("=" * 70)
                print("CHROME DEBUG MODE")
                print("=" * 70)
                print()
                print("Chrome will remain open.")
                print("Press ENTER in this terminal to close Chrome.")
                print("=" * 70)

                try:
                    await asyncio.to_thread(input)
                except Exception:
                    pass

            # ====================================================
            # CLOSE CHROME
            # ====================================================

            try:

                if context:

                    await context.close()

                    print("[CHROME] Chrome closed.")

            except Exception as e:

                print(f"[CHROME] Close error: {e}")


# ============================================================
# MANUAL TEST
# ============================================================

async def open_meet(meet_link):

    print()
    print("=" * 70)
    print("SalesInterviewAI - MANUAL GOOGLE MEET TEST")
    print("=" * 70)
    print(f"Meet link: {meet_link}")
    print("=" * 70)

    async with async_playwright() as p:

        context = await p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            channel="chrome",
            headless=False,

            args=[
                "--window-size=900,600",
                "--window-position=50,50",
                "--start-normal",
                "--disable-blink-features=AutomationControlled",
                "--use-fake-ui-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
            ],

            viewport={
                "width": 900,
                "height": 600
            },
        )

        page = context.pages[0] if context.pages else await context.new_page()

        await page.goto(
            meet_link,
            wait_until="domcontentloaded",
            timeout=60000
        )

        await page.wait_for_timeout(5000)

        # Force normal/small window
        try:

            await page.evaluate("""
                () => {
                    window.resizeTo(900, 600);
                    window.moveTo(50, 50);
                }
            """)

        except Exception:
            pass

        # Zoom out
        try:

            await page.keyboard.press("Control+-")
            await page.keyboard.press("Control+-")
            await page.keyboard.press("Control+-")

        except Exception:
            pass

        print()
        print("=" * 70)
        print("MEET OPENED")
        print("=" * 70)
        print()
        print("Now configure Google Meet:")
        print()
        print("Settings -> Audio")
        print()
        print("Microphone -> Voicemeeter Out B1")
        print("Speaker     -> CABLE Input")
        print()
        print("Press ENTER here when finished.")
        print("=" * 70)

        await asyncio.to_thread(input)

        await context.close()


# ============================================================
# DIRECT EXECUTION
# ============================================================

if __name__ == "__main__":

    print()
    print("=" * 70)
    print("SalesInterviewAI - GOOGLE MEET BOT")
    print("=" * 70)
    print()

    meet_link = input(
        "Enter Google Meet link: "
    ).strip()

    if not meet_link:

        print("No Meet link entered.")

    else:

        asyncio.run(
            run_meet_bot(
                interview_id=0,
                meet_link=meet_link
            )
        )

