import asyncio
import os

from playwright.async_api import async_playwright

from app.database.database import SessionLocal
from app.models.interview import Interview
from app.services.elevenlabs_agent import run_alena


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)

PROFILE_DIR = os.path.join(
    BASE_DIR,
    "playwright_profile",
)

RECORDING_DIR = os.path.join(
    BASE_DIR,
    "data",
    "recordings",
)

os.makedirs(
    RECORDING_DIR,
    exist_ok=True,
)


# ============================================================
# DATABASE UPDATE
# ============================================================

def update_interview_files(
    interview_id: int,
    transcript_path=None,
    recording_path=None,
):

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
                f"[DATABASE] Interview "
                f"#{interview_id} not found."
            )

            return

        if transcript_path:

            interview.transcript_path = (
                transcript_path
            )

            print(
                f"[DATABASE] Transcript saved for "
                f"interview #{interview_id}"
            )

        if recording_path:

            interview.recording_path = (
                recording_path
            )

            print(
                f"[DATABASE] Recording saved for "
                f"interview #{interview_id}"
            )

        db.commit()

    except Exception as error:

        db.rollback()

        print(
            f"[DATABASE ERROR] {error}"
        )

    finally:

        db.close()


# ============================================================
# LEAVE GOOGLE MEET
# ============================================================

async def leave_google_meet(page):

    print(
        "\n[MEET] Ending Google Meet call..."
    )

    leave_selectors = [

        page.get_by_role(
            "button",
            name="Leave call",
        ),

        page.get_by_role(
            "button",
            name="Leave meeting",
        ),

        page.get_by_text(
            "Leave call",
            exact=True,
        ),

    ]

    for selector in leave_selectors:

        try:

            if await selector.count() > 0:

                await selector.first.click()

                print(
                    "[MEET] Leave button clicked."
                )

                await page.wait_for_timeout(
                    3000
                )

                return True

        except Exception as error:

            print(
                f"[MEET] Leave attempt failed: "
                f"{error}"
            )

    print(
        "[MEET] Leave button was not found."
    )

    return False


# ============================================================
# GOOGLE MEET BOT + ALENA
# ============================================================

async def run_meet_bot(
    meet_link: str,
    interview_id: int,
):

    print("=" * 70)
    print(
        "SalesInterviewAI - ALENA AUTOMATIC MEET BOT"
    )
    print("=" * 70)

    print(
        f"Interview ID  : {interview_id}"
    )

    print(
        f"Meet link     : {meet_link}"
    )

    print(
        f"Chrome profile: {PROFILE_DIR}"
    )

    print(
        f"Recording dir : {RECORDING_DIR}"
    )

    print("=" * 70)


    async with async_playwright() as p:

        context = None
        page = None
        recording_path = None
        transcript_path = None

        try:

            # ====================================================
            # START GOOGLE CHROME
            # ====================================================

            print(
                "\n[1] Starting Google Chrome..."
            )

            context = await p.chromium.launch_persistent_context(

                user_data_dir=PROFILE_DIR,

                channel="chrome",

                headless=False,

                record_video_dir=RECORDING_DIR,

                record_video_size={
                    "width": 1280,
                    "height": 720,
                },

                args=[
                    "--start-maximized",

                    "--disable-blink-features="
                    "AutomationControlled",

                    "--use-fake-ui-for-media-stream",

                    "--autoplay-policy="
                    "no-user-gesture-required",
                ],

                viewport={
                    "width": 1280,
                    "height": 720,
                },
            )

            print(
                "[CHROME] Google Chrome started."
            )


            # ====================================================
            # GET PAGE
            # ====================================================

            if context.pages:

                page = context.pages[0]

            else:

                page = await context.new_page()


            # ====================================================
            # OPEN GOOGLE MEET
            # ====================================================

            print(
                "\n[2] Opening Google Meet..."
            )

            await page.goto(
                meet_link,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            print(
                "[MEET] Google Meet page opened."
            )

            await page.wait_for_timeout(
                5000
            )


            # ====================================================
            # TURN CAMERA OFF
            # ====================================================

            print(
                "\n[3] Turning camera off..."
            )

            try:

                camera_button = page.get_by_role(
                    "button",
                    name="Turn off camera",
                )

                if await camera_button.count() > 0:

                    await camera_button.first.click()

                    print(
                        "[MEET] Camera turned OFF."
                    )

                else:

                    print(
                        "[MEET] Camera button not found."
                    )

            except Exception as error:

                print(
                    f"[MEET] Camera check failed: "
                    f"{error}"
                )


            # ====================================================
            # MICROPHONE
            # ====================================================

            print(
                "\n[4] Checking microphone..."
            )

            try:

                mute_button = page.get_by_role(
                    "button",
                    name="Turn off microphone",
                )

                if await mute_button.count() > 0:

                    print(
                        "[MEET] Microphone is ON."
                    )

                else:

                    print(
                        "[MEET] Microphone button "
                        "not detected."
                    )

            except Exception as error:

                print(
                    f"[MEET] Microphone check failed: "
                    f"{error}"
                )


            # ====================================================
            # JOIN MEETING
            # ====================================================

            print(
                "\n[5] Looking for Join button..."
            )

            join_selectors = [

                page.get_by_role(
                    "button",
                    name="Join now",
                ),

                page.get_by_role(
                    "button",
                    name="Ask to join",
                ),

                page.get_by_text(
                    "Join now",
                    exact=True,
                ),

                page.get_by_text(
                    "Ask to join",
                    exact=True,
                ),

            ]


            joined = False


            for selector in join_selectors:

                try:

                    if await selector.count() > 0:

                        await selector.first.click()

                        print(
                            "[MEET] JOIN button clicked."
                        )

                        joined = True

                        break

                except Exception as error:

                    print(
                        f"[MEET] Join attempt failed: "
                        f"{error}"
                    )

                    continue


            if not joined:

                print(
                    "[MEET] Join button was not found."
                )

                print(
                    "[MEET] Checking whether "
                    "already inside the meeting..."
                )

            else:

                print(
                    "[MEET] Waiting for meeting..."
                )


            # ====================================================
            # WAIT FOR MEET TO LOAD
            # ====================================================

            await page.wait_for_timeout(
                10000
            )


            # ====================================================
            # MEET READY
            # ====================================================

            print(
                "\n" + "=" * 70
            )

            print(
                "GOOGLE MEET READY"
            )

            print(
                "=" * 70
            )

            print(
                f"Interview #{interview_id}"
            )

            print(
                "Chrome is running."
            )

            print(
                "Google Meet is open."
            )

            print(
                "Bot has joined/attempted to join."
            )

            print(
                "=" * 70
            )


            # ====================================================
            # START ALENA
            # ====================================================

            print(
                "\n" + "=" * 70
            )

            print(
                "STARTING ALENA"
            )

            print(
                "=" * 70
            )

            print(
                "[ALENA] Connecting to ElevenLabs..."
            )

            print(
                "[ALENA] Starting audio interface..."
            )

            print(
                "[ALENA] Interview starting..."
            )

            print(
                "=" * 70
            )


            # ----------------------------------------------------
            # run_alena() is synchronous.
            #
            # Run it in a worker thread so Playwright remains
            # active and Google Meet stays open.
            # ----------------------------------------------------

            alena_result = await asyncio.to_thread(

                run_alena,

                interview_id=interview_id,

            )


            # ====================================================
            # ALENA SESSION ENDED
            # ====================================================

            print(
                "\n" + "=" * 70
            )

            print(
                "ALENA SESSION ENDED"
            )

            print(
                "=" * 70
            )


            if isinstance(
                alena_result,
                dict,
            ):

                conversation_id = (
                    alena_result.get(
                        "conversation_id"
                    )
                )

                transcript_path = (
                    alena_result.get(
                        "transcript_path"
                    )
                )

            else:

                conversation_id = (
                    alena_result
                )


            print(
                f"Conversation ID: "
                f"{conversation_id}"
            )


            if transcript_path:

                print(
                    f"Transcript: "
                    f"{transcript_path}"
                )


            print(
                "=" * 70
            )


            # ====================================================
            # LEAVE GOOGLE MEET
            # ====================================================

            await leave_google_meet(
                page
            )


            # ====================================================
            # UPDATE DATABASE WITH TRANSCRIPT
            # ====================================================

            update_interview_files(

                interview_id=interview_id,

                transcript_path=(
                    transcript_path
                ),

            )


            print(
                "\n[MEET BOT] Interview "
                "workflow finished."
            )


        except Exception as error:

            # ====================================================
            # IMPORTANT DEBUG ERROR
            # ====================================================

            print(
                "\n" + "=" * 70
            )

            print(
                "[MEET BOT ERROR]"
            )

            print(
                "=" * 70
            )

            print(
                f"Exception type: "
                f"{type(error).__name__}"
            )

            print(
                f"Exception repr: "
                f"{repr(error)}"
            )

            print(
                f"Exception message: "
                f"{str(error)}"
            )

            print(
                "=" * 70
            )

            raise


        finally:

            # ====================================================
            # DEBUG MODE
            #
            # DO NOT CLOSE CHROME IMMEDIATELY.
            #
            # This allows us to inspect Google Meet after
            # ElevenLabs fails.
            # ====================================================

            if context:

                print(
                    "\n" + "=" * 70
                )

                print(
                    "[DEBUG] Google Chrome will remain OPEN."
                )

                print(
                    "[DEBUG] Inspect the Google Meet window."
                )

                print(
                    "[DEBUG] When you are finished,"
                )

                print(
                    "[DEBUG] press ENTER in this terminal."
                )

                print(
                    "=" * 70
                )


                try:

                    await asyncio.to_thread(
                        input
                    )

                except Exception as error:

                    print(
                        f"[DEBUG] Input wait error: "
                        f"{error}"
                    )


                # ====================================================
                # CLOSE CHROME AFTER ENTER
                # ====================================================

                print(
                    "\n[MEET BOT] Closing Google Chrome..."
                )

                try:

                    # ------------------------------------------------
                    # Playwright finalizes the recorded video when
                    # the browser context is closed.
                    # ------------------------------------------------

                    await context.close()

                    print(
                        "[MEET BOT] Google Chrome closed."
                    )

                except Exception as error:

                    print(
                        f"[MEET BOT] Chrome close error: "
                        f"{error}"
                    )


                # ====================================================
                # GET FINAL RECORDING PATH
                # ====================================================

                if page:

                    try:

                        video = page.video

                        if video:

                            recording_path = (
                                await video.path()
                            )

                            print(
                                "[RECORDING] Saved:"
                            )

                            print(
                                recording_path
                            )

                    except Exception as error:

                        print(
                            "[RECORDING] Could not "
                            "retrieve recording path:"
                        )

                        print(
                            error
                        )


                # ====================================================
                # SAVE RECORDING PATH TO DATABASE
                # ====================================================

                if recording_path:

                    update_interview_files(

                        interview_id=interview_id,

                        recording_path=(
                            recording_path
                        ),

                    )


# ============================================================
# MANUAL TEST
# ============================================================

async def open_meet(
    meet_link: str,
):

    await run_meet_bot(
        meet_link=meet_link,
        interview_id=0,
    )


# ============================================================
# DIRECT EXECUTION
# ============================================================

if __name__ == "__main__":

    meet_link = input(
        "Enter Google Meet link: "
    ).strip()


    if not meet_link:

        print(
            "ERROR: Google Meet link is required."
        )

        raise SystemExit(1)


    asyncio.run(
        open_meet(meet_link)
    )