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

PROFILE_DIR = os.path.join(
    BASE_DIR,
    "playwright_profile"
)

RECORDING_DIR = os.path.join(
    BASE_DIR,
    "data",
    "recordings"
)

os.makedirs(
    PROFILE_DIR,
    exist_ok=True
)

os.makedirs(
    RECORDING_DIR,
    exist_ok=True
)


# ============================================================
# UPDATE INTERVIEW FILES
# ============================================================

def update_interview_files(
    interview_id,
    transcript_path=None,
    recording_path=None
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
                f"[DB] Interview #{interview_id} "
                f"not found."
            )

            return

        if transcript_path:

            interview.transcript_path = (
                transcript_path
            )

        if recording_path:

            interview.recording_path = (
                recording_path
            )

        db.commit()

        print(
            f"[DB] Interview #{interview_id} "
            f"files updated."
        )

    except Exception as e:

        db.rollback()

        print(
            f"[DB ERROR] {e}"
        )

    finally:

        db.close()


# ============================================================
# GOOGLE MEET LIVE CAPTIONS READER
# ============================================================

async def read_google_meet_captions(
    page,
    caption_callback,
    stop_event
):
    """
    Reads Google Meet live captions from the Meet DOM.

    The callback receives:
        candidate_text

    This is currently used only as a diagnostic/fallback
    mechanism. It does NOT send anything to ElevenLabs yet.
    """

    print()
    print("=" * 70)
    print("[CC] GOOGLE MEET CAPTION READER STARTING")
    print("=" * 70)

    last_caption = ""

    while not stop_event.is_set():

        try:

            # ------------------------------------------------
            # Google Meet caption regions
            # ------------------------------------------------

            selectors = [
                '[role="region"][aria-label*="aption" i]',
                '[aria-live="polite"][role="region"]',
                'div[aria-live="polite"]',
            ]

            current_text = ""

            for selector in selectors:

                try:

                    locator = page.locator(
                        selector
                    )

                    count = await locator.count()

                    if count == 0:
                        continue

                    for i in range(count):

                        try:

                            element = locator.nth(i)

                            text = await element.inner_text(
                                timeout=500
                            )

                            if text:

                                text = " ".join(
                                    text.split()
                                ).strip()

                                if text:
                                    current_text = text

                        except Exception:
                            continue

                except Exception:
                    continue

            # ------------------------------------------------
            # Nothing found
            # ------------------------------------------------

            if not current_text:

                await page.wait_for_timeout(
                    300
                )

                continue

            # ------------------------------------------------
            # Ignore unchanged caption
            # ------------------------------------------------

            if current_text == last_caption:

                await page.wait_for_timeout(
                    300
                )

                continue

            # ------------------------------------------------
            # New caption detected
            # ------------------------------------------------

            last_caption = current_text

            print()
            print("=" * 70)
            print("[CC] NEW CAPTION")
            print("=" * 70)
            print(current_text)
            print("=" * 70)

            # ------------------------------------------------
            # Send to callback
            # ------------------------------------------------

            if caption_callback:

                await caption_callback(
                    current_text
                )

        except Exception as e:

            if not stop_event.is_set():

                print(
                    f"[CC] Reader error: {e}"
                )

        await page.wait_for_timeout(
            300
        )

    print(
        "[CC] Caption reader stopped."
    )


# ============================================================
# ENABLE GOOGLE MEET CAPTIONS
# ============================================================

async def enable_google_meet_captions(
    page
):

    print(
        "[CC] Looking for captions button..."
    )

    try:

        buttons = page.get_by_role(
            "button"
        )

        count = await buttons.count()

        for i in range(count):

            try:

                button = buttons.nth(i)

                label = await button.get_attribute(
                    "aria-label"
                )

                tooltip = await button.get_attribute(
                    "data-tooltip"
                )

                text = ""

                try:

                    text = await button.inner_text()

                except Exception:

                    pass

                combined = " ".join(
                    [
                        label or "",
                        tooltip or "",
                        text or ""
                    ]
                ).lower()

                # --------------------------------------------
                # Captions button
                # --------------------------------------------

                if (
                    "turn on captions"
                    in combined
                    or
                    "show captions"
                    in combined
                    or
                    combined.strip() == "captions"
                ):

                    await button.click()

                    print(
                        "[CC] ✓ Captions enabled."
                    )

                    return True

                # --------------------------------------------
                # Already enabled
                # --------------------------------------------

                if (
                    "turn off captions"
                    in combined
                    or
                    "hide captions"
                    in combined
                ):

                    print(
                        "[CC] ✓ Captions already enabled."
                    )

                    return True

            except Exception:

                continue

    except Exception as e:

        print(
            f"[CC] Caption button search error: {e}"
        )

    print(
        "[CC] Could not automatically enable captions."
    )

    print(
        "[CC] Please enable captions manually."
    )

    return False


# ============================================================
# LEAVE GOOGLE MEET
# ============================================================

async def leave_google_meet(
    page
):

    print(
        "[MEET] Leaving Google Meet..."
    )

    try:

        buttons = page.get_by_role(
            "button"
        )

        count = await buttons.count()

        for i in range(count):

            try:

                button = buttons.nth(i)

                label = await button.get_attribute(
                    "aria-label"
                )

                if label:

                    label_lower = (
                        label.lower()
                    )

                    if (
                        "leave call"
                        in label_lower
                        or
                        "leave meeting"
                        in label_lower
                    ):

                        await button.click()

                        print(
                            "[MEET] Leave button clicked."
                        )

                        return

            except Exception:

                continue

        await page.keyboard.press(
            "Escape"
        )

    except Exception as e:

        print(
            f"[MEET] Leave error: {e}"
        )


# ============================================================
# TURN CAMERA OFF
# ============================================================

async def turn_camera_off(
    page
):

    print(
        "[MEET] Checking camera..."
    )

    try:

        buttons = page.get_by_role(
            "button"
        )

        count = await buttons.count()

        for i in range(count):

            try:

                button = buttons.nth(i)

                label = await button.get_attribute(
                    "aria-label"
                )

                if not label:
                    continue

                label_lower = (
                    label.lower()
                )

                # Only click if camera appears ON.
                if (
                    "turn off camera"
                    in label_lower
                ):

                    await button.click()

                    print(
                        "[MEET] Camera turned off."
                    )

                    return True

            except Exception:

                continue

    except Exception as e:

        print(
            f"[MEET] Camera error: {e}"
        )

    print(
        "[MEET] Camera state not changed."
    )

    return False


# ============================================================
# CHECK MICROPHONE
# ============================================================

async def check_microphone(
    page
):

    print(
        "[MEET] Checking microphone..."
    )

    try:

        buttons = page.get_by_role(
            "button"
        )

        count = await buttons.count()

        for i in range(count):

            try:

                button = buttons.nth(i)

                label = await button.get_attribute(
                    "aria-label"
                )

                if label:

                    if (
                        "microphone"
                        in label.lower()
                    ):

                        print(
                            f"[MEET] Microphone: "
                            f"{label}"
                        )

                        return label

            except Exception:

                continue

    except Exception as e:

        print(
            f"[MEET] Microphone check error: "
            f"{e}"
        )

    print(
        "[MEET] Microphone button not found."
    )

    return None


# ============================================================
# JOIN MEETING
# ============================================================

async def join_google_meet(
    page
):

    print(
        "[MEET] Looking for Join button..."
    )

    await page.wait_for_timeout(
        2000
    )

    # --------------------------------------------------------
    # Join now
    # --------------------------------------------------------

    try:

        join_button = page.get_by_role(
            "button",
            name="Join now"
        )

        if await join_button.count() > 0:

            await join_button.first.click()

            print(
                "[MEET] JOIN NOW clicked."
            )

            return True

    except Exception:

        pass

    # --------------------------------------------------------
    # Ask to join
    # --------------------------------------------------------

    try:

        ask_button = page.get_by_role(
            "button",
            name="Ask to join"
        )

        if await ask_button.count() > 0:

            await ask_button.first.click()

            print(
                "[MEET] ASK TO JOIN clicked."
            )

            return True

    except Exception:

        pass

    # --------------------------------------------------------
    # Fallback
    # --------------------------------------------------------

    try:

        buttons = page.get_by_role(
            "button"
        )

        count = await buttons.count()

        for i in range(count):

            try:

                button = buttons.nth(i)

                text = await button.inner_text()

                text_lower = (
                    text.lower()
                )

                if (
                    "join now"
                    in text_lower
                    or
                    "ask to join"
                    in text_lower
                ):

                    await button.click()

                    print(
                        "[MEET] Join button clicked."
                    )

                    return True

            except Exception:

                continue

    except Exception as e:

        print(
            f"[MEET] Join search error: "
            f"{e}"
        )

    print(
        "[MEET] Join button not found."
    )

    return False


# ============================================================
# OPEN CHROME
# ============================================================

async def create_chrome_context(
    p
):

    print(
        "[CHROME] Starting Google Chrome..."
    )

    context = (
        await p.chromium.launch_persistent_context(

            user_data_dir=PROFILE_DIR,

            channel="chrome",

            headless=False,

            record_video_dir=RECORDING_DIR,

            record_video_size={
                "width": 1280,
                "height": 720
            },

            args=[

                "--window-size=900,600",

                "--window-position=50,50",

                "--start-normal",

                "--disable-blink-features="
                "AutomationControlled",

                # Automatically accept microphone/
                # camera permissions.
                "--use-fake-ui-for-media-stream",

                "--autoplay-policy="
                "no-user-gesture-required",

            ],

            viewport={
                "width": 900,
                "height": 600
            },

        )
    )

    print(
        "[CHROME] Chrome started."
    )

    return context


# ============================================================
# PREPARE MEET PAGE
# ============================================================

async def prepare_meet_page(
    page,
    meet_link
):

    print(
        "[MEET] Opening:"
    )

    print(
        meet_link
    )

    await page.goto(
        meet_link,
        wait_until="domcontentloaded",
        timeout=60000
    )

    print(
        "[MEET] Page opened."
    )

    await page.wait_for_timeout(
        5000
    )

    # --------------------------------------------------------
    # Resize
    # --------------------------------------------------------

    try:

        await page.evaluate(
            """
            () => {
                window.resizeTo(900, 600);
                window.moveTo(50, 50);
            }
            """
        )

    except Exception as e:

        print(
            f"[MEET] Resize skipped: {e}"
        )

    # --------------------------------------------------------
    # Zoom out
    # --------------------------------------------------------

    try:

        await page.keyboard.press(
            "Control+-"
        )

        await page.keyboard.press(
            "Control+-"
        )

        await page.keyboard.press(
            "Control+-"
        )

    except Exception:

        pass

    await page.wait_for_timeout(
        1000
    )


# ============================================================
# AUDIO ROUTING INSTRUCTIONS
# ============================================================

def print_audio_routing():

    print()
    print("=" * 70)
    print("SALESINTERVIEWAI AUDIO ROUTING")
    print("=" * 70)

    print()
    print("GOOGLE MEET:")
    print()

    print(
        "Microphone -> Voicemeeter Out B1"
    )

    print(
        "Speaker    -> CABLE Input"
    )

    print()
    print("PYTHON:")
    print()

    print(
        "Candidate INPUT -> CABLE Output"
    )

    print(
        "Alena OUTPUT    -> Voicemeeter Input"
    )

    print()
    print("=" * 70)

    print(
        "Do NOT change the routing while the bot "
        "is testing audio."
    )

    print("=" * 70)


# ============================================================
# MAIN MEET BOT
# ============================================================

async def run_meet_bot(
    interview_id,
    meet_link
):

    print()
    print("=" * 70)
    print("SalesInterviewAI - ALENA AUTOMATIC MEET BOT")
    print("=" * 70)

    print(
        f"Interview ID: {interview_id}"
    )

    print(
        f"Meet link: {meet_link}"
    )

    print(
        f"Chrome profile: {PROFILE_DIR}"
    )

    print(
        f"Recording dir: {RECORDING_DIR}"
    )

    print("=" * 70)

    video_path = None
    transcript_path = None

    # --------------------------------------------------------
    # CC TASK VARIABLES
    # --------------------------------------------------------

    cc_stop_event = None
    cc_task = None

    async with async_playwright() as p:

        context = None
        page = None

        try:

            # ====================================================
            # 1. START CHROME
            # ====================================================

            context = await create_chrome_context(
                p
            )

            # ====================================================
            # 2. PAGE
            # ====================================================

            page = (
                context.pages[0]
                if context.pages
                else await context.new_page()
            )

            # ====================================================
            # 3. OPEN MEET
            # ====================================================

            await prepare_meet_page(
                page,
                meet_link
            )

            # ====================================================
            # 4. AUDIO ROUTING
            # ====================================================

            print_audio_routing()

            print()
            print(
                "IMPORTANT:"
            )

            print(
                "Meet must use:"
            )

            print(
                "  Microphone = Voicemeeter Out B1"
            )

            print(
                "  Speaker    = CABLE Input"
            )

            print()

            # ====================================================
            # 5. CAMERA
            # ====================================================

            await turn_camera_off(
                page
            )

            # ====================================================
            # 6. MICROPHONE
            # ====================================================

            await check_microphone(
                page
            )

            # ====================================================
            # 7. JOIN
            # ====================================================

            joined = await join_google_meet(
                page
            )

            if not joined:

                print()
                print(
                    "[MEET] Could not automatically join."
                )

                print(
                    "[MEET] Check Chrome manually."
                )

            # ====================================================
            # 8. WAIT
            # ====================================================

            print()
            print(
                "[MEET] Waiting for meeting..."
            )

            await page.wait_for_timeout(
                10000
            )

            # ====================================================
            # 8A. ENABLE GOOGLE MEET CAPTIONS
            # ====================================================

            print()
            print(
                "[CC] Enabling Google Meet captions..."
            )

            await enable_google_meet_captions(
                page
            )

            # ====================================================
            # 8B. START CC READER
            # ====================================================

            cc_stop_event = asyncio.Event()

            async def handle_caption(
                text
            ):

                print(
                    f"[CC → ALENA] Candidate: {text}"
                )

            cc_task = asyncio.create_task(
                read_google_meet_captions(
                    page=page,

                    caption_callback=handle_caption,

                    stop_event=cc_stop_event
                )
            )

            print()
            print("=" * 70)
            print("GOOGLE MEET READY")
            print("=" * 70)

            print()
            print(
                "[CC] Caption reader is running."
            )

            print(
                "[CC] Speak in the candidate account "
                "to test captions."
            )

            # ====================================================
            # 9. START ALENA
            # ====================================================

            print()
            print(
                "[ALENA] Starting Alena..."
            )

            try:

                alena_result = (
                    await asyncio.to_thread(
                        run_alena,
                        interview_id
                    )
                )

                if isinstance(
                    alena_result,
                    dict
                ):

                    transcript_path = (
                        alena_result.get(
                            "transcript_path"
                        )
                    )

                elif isinstance(
                    alena_result,
                    str
                ):

                    transcript_path = (
                        alena_result
                    )

                print(
                    "[ALENA] Interview finished."
                )

            except Exception as e:

                print()
                print("=" * 70)
                print("[ALENA ERROR]")
                print("=" * 70)

                print(e)

                print("=" * 70)

            # ====================================================
            # 9A. STOP CC READER
            # ====================================================

            print()
            print(
                "[CC] Stopping caption reader..."
            )

            try:

                if cc_stop_event:

                    cc_stop_event.set()

                if cc_task:

                    await cc_task

            except Exception as e:

                print(
                    f"[CC] Stop error: {e}"
                )

            # ====================================================
            # 10. LEAVE
            # ====================================================

            await leave_google_meet(
                page
            )

            await page.wait_for_timeout(
                3000
            )

            # ====================================================
            # 11. VIDEO
            # ====================================================

            try:

                if page.video:

                    video_path = (
                        await page.video.path()
                    )

                    print(
                        f"[RECORDING] Video: "
                        f"{video_path}"
                    )

            except Exception as e:

                print(
                    "[RECORDING] Video path unavailable:"
                )

                print(e)

        except Exception as e:

            print()
            print("=" * 70)
            print("[MEET BOT ERROR]")
            print("=" * 70)

            print(e)

            print("=" * 70)

        finally:

            # ====================================================
            # SAFETY: STOP CC READER
            # ====================================================

            try:

                if cc_stop_event:

                    cc_stop_event.set()

                if cc_task:

                    if not cc_task.done():

                        await cc_task

            except Exception as e:

                print(
                    f"[CC] Final stop error: {e}"
                )

            # ====================================================
            # DATABASE
            # ====================================================

            try:

                update_interview_files(
                    interview_id=interview_id,
                    transcript_path=transcript_path,
                    recording_path=video_path
                )

            except Exception as e:

                print(
                    f"[DB] Could not update files: {e}"
                )

            # ====================================================
            # DEBUG
            # ====================================================

            if page:

                print()
                print("=" * 70)
                print("CHROME DEBUG MODE")
                print("=" * 70)

                print(
                    "Chrome will remain open."
                )

                print(
                    "Press ENTER in this terminal "
                    "to close Chrome."
                )

                print("=" * 70)

                try:

                    await asyncio.to_thread(
                        input
                    )

                except Exception:

                    pass

            # ====================================================
            # CLOSE
            # ====================================================

            try:

                if context:

                    await context.close()

                    print(
                        "[CHROME] Chrome closed."
                    )

            except Exception as e:

                print(
                    f"[CHROME] Close error: {e}"
                )


# ============================================================
# MANUAL MEET TEST
# ============================================================

async def open_meet(
    meet_link
):

    print()
    print("=" * 70)
    print("SalesInterviewAI - MANUAL GOOGLE MEET TEST")
    print("=" * 70)

    print(
        f"Meet link: {meet_link}"
    )

    print("=" * 70)

    async with async_playwright() as p:

        context = (
            await create_chrome_context(
                p
            )
        )

        page = (
            context.pages[0]
            if context.pages
            else await context.new_page()
        )

        await prepare_meet_page(
            page,
            meet_link
        )

        print_audio_routing()

        print()
        print(
            "Set Google Meet:"
        )

        print()
        print(
            "Microphone -> Voicemeeter Out B1"
        )

        print(
            "Speaker    -> CABLE Input"
        )

        print()

        print(
            "Press ENTER after checking Meet."
        )

        await asyncio.to_thread(
            input
        )

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

        print(
            "No Meet link entered."
        )

    else:

        asyncio.run(
            run_meet_bot(
                interview_id=0,
                meet_link=meet_link
            )
        )