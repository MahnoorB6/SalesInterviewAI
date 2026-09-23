import asyncio
import os
import sys

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

os.makedirs(PROFILE_DIR, exist_ok=True)
os.makedirs(RECORDING_DIR, exist_ok=True)


# ============================================================
# CONFIGURATION
# ============================================================

MEET_PAGE_LOAD_WAIT_SECONDS = 3
JOIN_TIMEOUT_SECONDS = 45
MEETING_READY_TIMEOUT_SECONDS = 30

CAPTIONS_START_DELAY_SECONDS = 2
CAPTIONS_RETRY_SECONDS = 20

# ============================================================
# AUDIO DEVICES
#
# Google Meet:
#   Microphone -> CABLE Output
#   Speaker    -> CABLE Input
#
# Python / ElevenLabs:
#   Candidate audio is read from CABLE Output
#   Alena audio is written to CABLE Input
# ============================================================

MEET_MICROPHONE_NAME = "CABLE Output"
MEET_SPEAKER_NAME = "CABLE Input"

AUDIO_DEVICE_CONFIG_TIMEOUT_SECONDS = 40
AUDIO_DEVICE_CONFIG_RETRY_DELAY_MS = 900


# ============================================================
# DATABASE
# ============================================================

def update_interview_files(
    interview_id: int,
    transcript_path: str | None = None,
    recording_path: str | None = None,
):
    db = SessionLocal()

    try:
        interview = (
            db.query(Interview)
            .filter(Interview.id == interview_id)
            .first()
        )

        if not interview:
            print(
                f"[DB] Interview {interview_id} not found."
            )
            return

        if transcript_path:
            interview.transcript_path = transcript_path

        if recording_path:
            interview.recording_path = recording_path

        db.commit()

        print(
            f"[DB] Interview {interview_id} files updated."
        )

    except Exception as e:
        db.rollback()

        print(
            f"[DB ERROR] Could not update interview files: {e}"
        )

    finally:
        db.close()


# ============================================================
# GOOGLE MEET CAPTIONS
#
# Captions are kept only for debugging / recording.
# They are NOT used as the conversation input.
# ============================================================

async def enable_google_meet_captions(page):
    try:
        await asyncio.sleep(
            CAPTIONS_START_DELAY_SECONDS
        )

        print("[CAPTIONS] Attempting to enable captions...")

        buttons = page.locator(
            "button"
        )

        count = await buttons.count()

        for i in range(count):
            try:
                button = buttons.nth(i)

                if not await button.is_visible():
                    continue

                text = (
                    await button.inner_text()
                ).strip().lower()

                aria = (
                    await button.get_attribute(
                        "aria-label"
                    )
                    or ""
                ).strip().lower()

                combined = f"{text} {aria}"

                if (
                    "caption" in combined
                    or "subtitles" in combined
                ):
                    await button.click(
                        timeout=3000
                    )

                    print(
                        "[CAPTIONS] Caption control clicked."
                    )

                    return True

            except Exception:
                continue

        print(
            "[CAPTIONS] Caption button not found."
        )

        return False

    except Exception as e:
        print(
            f"[CAPTIONS] Error: {e}"
        )

        return False


# ============================================================
# MEETING STATE
# ============================================================

async def is_meeting_ready(page):

    try:
        selectors = [
            '[aria-label*="Leave call"]',
            '[aria-label*="Leave meeting"]',
            'button[aria-label*="Leave"]',
        ]

        for selector in selectors:
            try:
                if await page.locator(
                    selector
                ).count() > 0:

                    if await page.locator(
                        selector
                    ).first.is_visible():

                        return True

            except Exception:
                continue

        return False

    except Exception:
        return False


async def wait_for_meeting_ready(
    page,
    timeout_seconds=MEETING_READY_TIMEOUT_SECONDS,
):

    print(
        "[MEET] Waiting for meeting to become ready..."
    )

    start = asyncio.get_event_loop().time()

    while (
        asyncio.get_event_loop().time() - start
        < timeout_seconds
    ):

        if await is_meeting_ready(page):
            print(
                "[MEET] Meeting is ready."
            )
            return True

        await asyncio.sleep(1)

    print(
        "[MEET] Meeting ready timeout."
    )

    return False


# ============================================================
# LEAVE GOOGLE MEET
# ============================================================

async def leave_google_meet(page):

    try:
        print(
            "[MEET] Leaving Google Meet..."
        )

        selectors = [
            'button[aria-label*="Leave call"]',
            'button[aria-label*="Leave meeting"]',
            'button[aria-label*="Leave"]',
        ]

        for selector in selectors:

            try:
                locator = page.locator(
                    selector
                )

                if await locator.count() == 0:
                    continue

                for i in range(
                    await locator.count()
                ):

                    button = locator.nth(i)

                    if await button.is_visible():

                        await button.click(
                            timeout=3000
                        )

                        print(
                            "[MEET] Leave button clicked."
                        )

                        await asyncio.sleep(2)

                        return True

            except Exception:
                continue

        print(
            "[MEET] Leave button not found."
        )

        return False

    except Exception as e:

        print(
            f"[MEET] Leave error: {e}"
        )

        return False


# ============================================================
# CAMERA
# ============================================================

async def turn_camera_off(page):

    try:

        print(
            "[MEET] Turning camera off..."
        )

        selectors = [
            'button[aria-label*="Turn off camera"]',
            'button[aria-label*="camera"]',
        ]

        for selector in selectors:

            try:

                locator = page.locator(
                    selector
                )

                count = await locator.count()

                for i in range(count):

                    button = locator.nth(i)

                    if not await button.is_visible():
                        continue

                    aria = (
                        await button.get_attribute(
                            "aria-label"
                        )
                        or ""
                    ).lower()

                    if (
                        "turn off" in aria
                        or "camera" in aria
                    ):

                        await button.click(
                            timeout=3000
                        )

                        print(
                            "[MEET] Camera turned off."
                        )

                        return True

            except Exception:
                continue

        print(
            "[MEET] Camera button not found."
        )

        return False

    except Exception as e:

        print(
            f"[MEET] Camera error: {e}"
        )

        return False


# ============================================================
# MICROPHONE CHECK
# ============================================================

async def check_microphone(page):

    try:

        print(
            "[MEET] Checking microphone..."
        )

        await asyncio.sleep(1)

        selectors = [
            'button[aria-label*="microphone"]',
            'button[aria-label*="Microphone"]',
        ]

        for selector in selectors:

            try:

                locator = page.locator(
                    selector
                )

                count = await locator.count()

                if count == 0:
                    continue

                for i in range(count):

                    button = locator.nth(i)

                    if not await button.is_visible():
                        continue

                    aria = (
                        await button.get_attribute(
                            "aria-label"
                        )
                        or ""
                    )

                    print(
                        f"[MEET] Microphone button: {aria}"
                    )

                    return True

            except Exception:
                continue

        print(
            "[MEET] Microphone button not found."
        )

        return False

    except Exception as e:

        print(
            f"[MEET] Microphone check error: {e}"
        )

        return False


# ============================================================
# JOIN GOOGLE MEET
# ============================================================

async def join_google_meet(page):

    print(
        "[MEET] Attempting to join meeting..."
    )

    start = asyncio.get_event_loop().time()

    while (
        asyncio.get_event_loop().time() - start
        < JOIN_TIMEOUT_SECONDS
    ):

        try:

            buttons = page.locator(
                "button"
            )

            count = await buttons.count()

            for i in range(count):

                button = buttons.nth(i)

                try:

                    if not await button.is_visible():
                        continue

                    text = (
                        await button.inner_text()
                    ).strip().lower()

                    aria = (
                        await button.get_attribute(
                            "aria-label"
                        )
                        or ""
                    ).strip().lower()

                    combined = (
                        f"{text} {aria}"
                    )

                    if (
                        "join now" in combined
                        or "ask to join" in combined
                    ):

                        await button.click(
                            timeout=3000
                        )

                        print(
                            "[MEET] Join button clicked."
                        )

                        await asyncio.sleep(3)

                        return True

                except Exception:
                    continue

        except Exception:
            pass

        await asyncio.sleep(1)

    print(
        "[MEET] Could not find Join button."
    )

    return False


# ============================================================
# CHROME CONTEXT
# ============================================================

async def create_chrome_context(p):

    print(
        "[CHROME] Launching persistent Chrome..."
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
            "--window-size=900,600",
            "--window-position=50,50",
            "--start-normal",

            "--disable-blink-features=AutomationControlled",

            "--use-fake-ui-for-media-stream",

            "--autoplay-policy=no-user-gesture-required",
        ],

        viewport={
            "width": 900,
            "height": 600,
        },

        permissions=[
            "microphone",
            "camera",
        ],
    )

    return context


# ============================================================
# PREPARE MEET PAGE
# ============================================================

async def prepare_meet_page(
    page,
    meet_link: str,
):

    print(
        f"[MEET] Opening: {meet_link}"
    )

    await page.goto(
        meet_link,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    await asyncio.sleep(
        MEET_PAGE_LOAD_WAIT_SECONDS
    )

    try:

        await page.evaluate(
            """
            () => {
                window.moveTo(50, 50);
                window.resizeTo(900, 600);
            }
            """
        )

    except Exception:
        pass

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


# ============================================================
# AUDIO ROUTING DISPLAY
# ============================================================

def print_audio_routing():

    print()
    print("=" * 65)
    print("AUDIO ROUTING")
    print("=" * 65)

    print()
    print("GOOGLE MEET")
    print(
        "Microphone -> CABLE Output"
    )
    print(
        "Speaker    -> CABLE Input"
    )

    print()
    print("PYTHON / ELEVENLABS")
    print(
        "Candidate INPUT -> CABLE Output"
    )
    print(
        "Alena OUTPUT    -> CABLE Input"
    )

    print()
    print("SIGNAL FLOW")
    print()
    print("Candidate")
    print("    ↓")
    print("Google Meet Microphone")
    print("    ↓")
    print("CABLE Output")
    print("    ↓")
    print("Python / ElevenLabs")
    print()
    print("Alena")
    print("    ↓")
    print("Python")
    print("    ↓")
    print("CABLE Input")
    print("    ↓")
    print("Google Meet Speaker")
    print("    ↓")
    print("Candidate")

    print()
    print("[AUDIO] Voicemeeter is NOT used.")
    print("[AUDIO] VB-CABLE A+B is NOT required.")
    print("=" * 65)
    print()


# ============================================================
# CLICK HELPER
# ============================================================

async def _click_first_visible_text(
    page,
    texts,
):

    for text in texts:

        selectors = [
            f'text="{text}"',
            f'[aria-label*="{text}"]',
        ]

        for selector in selectors:

            try:

                locator = page.locator(
                    selector
                )

                count = await locator.count()

                for i in range(count):

                    element = locator.nth(i)

                    if not await element.is_visible():
                        continue

                    await element.click(
                        timeout=3000
                    )

                    return True

            except Exception:
                continue

    return False


# ============================================================
# SELECTED DEVICE CHECK
# ============================================================

async def _selected_device_matches(
    page,
    device_name,
):

    try:

        text = (
            await page.locator(
                "body"
            ).inner_text()
        )

        return device_name.lower() in text.lower()

    except Exception:
        return False


# ============================================================
# MEET DEVICE SELECTION
# ============================================================

async def _select_meet_device_from_open_list(
    page,
    device_name,
):

    try:

        print(
            f"[AUDIO] Selecting: {device_name}"
        )

        locator = page.get_by_text(
            device_name,
            exact=False,
        )

        count = await locator.count()

        for i in range(count):

            item = locator.nth(i)

            try:

                if not await item.is_visible():
                    continue

                await item.click(
                    timeout=3000
                )

                print(
                    f"[AUDIO] Selected: {device_name}"
                )

                return True

            except Exception:
                continue

        return False

    except Exception as e:

        print(
            f"[AUDIO] Device selection error: {e}"
        )

        return False


# ============================================================
# CONFIGURE GOOGLE MEET AUDIO
# ============================================================

async def configure_google_meet_audio_devices(
    page,
):

    print()
    print(
        "[AUDIO] Configuring Google Meet audio devices..."
    )

    try:

        # ----------------------------------------------------
        # Open Meet settings
        # ----------------------------------------------------

        settings_opened = await _click_first_visible_text(
            page,
            [
                "Settings",
            ],
        )

        if not settings_opened:

            # Try aria-labels directly
            selectors = [
                'button[aria-label*="Settings"]',
                '[aria-label*="settings"]',
            ]

            for selector in selectors:

                try:

                    locator = page.locator(
                        selector
                    )

                    count = await locator.count()

                    for i in range(count):

                        button = locator.nth(i)

                        if await button.is_visible():

                            await button.click(
                                timeout=3000
                            )

                            settings_opened = True
                            break

                    if settings_opened:
                        break

                except Exception:
                    continue

        if not settings_opened:

            print(
                "[AUDIO] Could not open Meet settings."
            )

            return False

        await asyncio.sleep(2)

        # ----------------------------------------------------
        # Open Audio tab
        # ----------------------------------------------------

        audio_opened = await _click_first_visible_text(
            page,
            [
                "Audio",
            ],
        )

        if not audio_opened:

            print(
                "[AUDIO] Could not open Audio settings."
            )

            return False

        await asyncio.sleep(1)

        # ----------------------------------------------------
        # MICROPHONE
        # ----------------------------------------------------

        print(
            f"[AUDIO] Target microphone: {MEET_MICROPHONE_NAME}"
        )

        microphone_selectors = [
            'select',
            '[role="combobox"]',
            '[aria-haspopup="listbox"]',
        ]

        microphone_done = False

        for selector in microphone_selectors:

            try:

                locator = page.locator(
                    selector
                )

                count = await locator.count()

                for i in range(count):

                    element = locator.nth(i)

                    if not await element.is_visible():
                        continue

                    aria = (
                        await element.get_attribute(
                            "aria-label"
                        )
                        or ""
                    ).lower()

                    text = (
                        await element.inner_text()
                    ).lower()

                    combined = (
                        f"{aria} {text}"
                    )

                    if (
                        "microphone" in combined
                        or "mic" in combined
                    ):

                        await element.click(
                            timeout=3000
                        )

                        await asyncio.sleep(
                            0.5
                        )

                        if await _select_meet_device_from_open_list(
                            page,
                            MEET_MICROPHONE_NAME,
                        ):

                            microphone_done = True
                            break

                if microphone_done:
                    break

            except Exception:
                continue

        if not microphone_done:

            print(
                "[AUDIO] Automatic microphone selection failed."
            )

        # ----------------------------------------------------
        # SPEAKER
        # ----------------------------------------------------

        print(
            f"[AUDIO] Target speaker: {MEET_SPEAKER_NAME}"
        )

        speaker_done = False

        for selector in microphone_selectors:

            try:

                locator = page.locator(
                    selector
                )

                count = await locator.count()

                for i in range(count):

                    element = locator.nth(i)

                    if not await element.is_visible():
                        continue

                    aria = (
                        await element.get_attribute(
                            "aria-label"
                        )
                        or ""
                    ).lower()

                    text = (
                        await element.inner_text()
                    ).lower()

                    combined = (
                        f"{aria} {text}"
                    )

                    if "speaker" in combined:

                        await element.click(
                            timeout=3000
                        )

                        await asyncio.sleep(
                            0.5
                        )

                        if await _select_meet_device_from_open_list(
                            page,
                            MEET_SPEAKER_NAME,
                        ):

                            speaker_done = True
                            break

                if speaker_done:
                    break

            except Exception:
                continue

        if not speaker_done:

            print(
                "[AUDIO] Automatic speaker selection failed."
            )

        # ----------------------------------------------------
        # CLOSE SETTINGS
        # ----------------------------------------------------

        await _click_first_visible_text(
            page,
            [
                "Close",
                "Done",
            ],
        )

        await asyncio.sleep(1)

        print()

        if microphone_done:
            print(
                "[AUDIO] Microphone -> CABLE Output"
            )
        else:
            print(
                "[AUDIO] WARNING: Microphone was not automatically configured."
            )

        if speaker_done:
            print(
                "[AUDIO] Speaker -> CABLE Input"
            )
        else:
            print(
                "[AUDIO] WARNING: Speaker was not automatically configured."
            )

        print()

        return microphone_done and speaker_done

    except Exception as e:

        print(
            f"[AUDIO] Configuration error: {e}"
        )

        return False


# ============================================================
# ONE-TIME AUDIO SETUP
# ============================================================

async def setup_meet_audio_devices(
    meet_link: str,
):

    print_audio_routing()

    print(
        "TARGET GOOGLE MEET DEVICES:"
    )

    print(
        f"Microphone: {MEET_MICROPHONE_NAME}"
    )

    print(
        f"Speaker:    {MEET_SPEAKER_NAME}"
    )

    print()

    async with async_playwright() as p:

        context = await create_chrome_context(
            p
        )

        page = context.pages[0]

        await prepare_meet_page(
            page,
            meet_link,
        )

        print()
        print(
            "[AUDIO] Configure the devices in Google Meet if needed."
        )

        await configure_google_meet_audio_devices(
            page
        )

        print()
        print(
            "[AUDIO] Setup finished."
        )

        input(
            "Press ENTER to close Chrome..."
        )

        await context.close()


# ============================================================
# MAIN MEET BOT
# ============================================================

async def run_meet_bot(
    interview_id: int,
    meet_link: str,
):

    print()
    print("=" * 65)
    print(
        f"STARTING SALES INTERVIEW BOT - INTERVIEW #{interview_id}"
    )
    print("=" * 65)

    print_audio_routing()

    async with async_playwright() as p:

        context = None
        page = None

        try:

            # ------------------------------------------------
            # CHROME
            # ------------------------------------------------

            context = await create_chrome_context(
                p
            )

            if context.pages:

                page = context.pages[0]

            else:

                page = await context.new_page()

            # ------------------------------------------------
            # OPEN MEET
            # ------------------------------------------------

            await prepare_meet_page(
                page,
                meet_link,
            )

            # ------------------------------------------------
            # CAMERA OFF
            # ------------------------------------------------

            await turn_camera_off(
                page
            )

            # ------------------------------------------------
            # MICROPHONE CHECK
            # ------------------------------------------------

            await check_microphone(
                page
            )

            # ------------------------------------------------
            # JOIN
            # ------------------------------------------------

            joined = await join_google_meet(
                page
            )

            if not joined:

                print(
                    "[MEET] Failed to join meeting."
                )

                return None

            # ------------------------------------------------
            # WAIT UNTIL READY
            # ------------------------------------------------

            ready = await wait_for_meeting_ready(
                page
            )

            if not ready:

                print(
                    "[MEET] Meeting did not become ready."
                )

            await asyncio.sleep(2)

            # ------------------------------------------------
            # AUDIO CONFIGURATION
            # ------------------------------------------------

            print()
            print(
                "[AUDIO] Configuring Meet audio..."
            )

            audio_configured = (
                await configure_google_meet_audio_devices(
                    page
                )
            )

            if audio_configured:

                print(
                    "[AUDIO] Meet audio devices configured successfully."
                )

            else:

                print(
                    "[AUDIO] WARNING: Automatic audio configuration was incomplete."
                )

                print(
                    "[AUDIO] Check that CABLE Output and CABLE Input are selected in Meet."
                )

            # ------------------------------------------------
            # AUDIO SETTLE
            # ------------------------------------------------

            await asyncio.sleep(
                AUDIO_DEVICE_CONFIG_TIMEOUT_SECONDS
                / 20
            )

            # ------------------------------------------------
            # FINAL ROUTING
            # ------------------------------------------------

            print()
            print(
                "[AUDIO] Candidate -> CABLE Output -> ElevenLabs"
            )

            print(
                "[AUDIO] ElevenLabs -> CABLE Input -> Meet"
            )

            print(
                "[AUDIO] Captions are NOT used as conversation input."
            )

            print()

            # ------------------------------------------------
            # RUN ALENA
            # ------------------------------------------------

            print(
                "[ALENA] Starting Alena..."
            )

            alena_result = await asyncio.to_thread(
                run_alena,
                interview_id,
                30 * 60,
            )

            print(
                "[ALENA] Alena finished."
            )

            print(
                f"[ALENA] Result: {alena_result}"
            )

            # ------------------------------------------------
            # TRANSCRIPT
            # ------------------------------------------------

            transcript_path = None

            if isinstance(
                alena_result,
                dict,
            ):

                transcript_path = (
                    alena_result.get(
                        "transcript_path"
                    )
                )

            # ------------------------------------------------
            # LEAVE MEET
            # ------------------------------------------------

            await leave_google_meet(
                page
            )

            await asyncio.sleep(2)

            # ------------------------------------------------
            # RECORDING
            # ------------------------------------------------

            recording_path = None

            try:

                video = page.video

                if video:

                    recording_path = (
                        await video.path()
                    )

                    print(
                        f"[RECORDING] Saved: {recording_path}"
                    )

            except Exception as e:

                print(
                    f"[RECORDING] Could not get recording path: {e}"
                )

            # ------------------------------------------------
            # DATABASE
            # ------------------------------------------------

            update_interview_files(
                interview_id=interview_id,
                transcript_path=transcript_path,
                recording_path=recording_path,
            )

            print()
            print("=" * 65)
            print(
                "INTERVIEW BOT FINISHED"
            )
            print("=" * 65)

            return {
                "transcript_path": transcript_path,
                "recording_path": recording_path,
                "alena_result": alena_result,
            }

        except Exception as e:

            print()
            print(
                "=" * 65
            )

            print(
                f"[MEET BOT ERROR] {e}"
            )

            print(
                "=" * 65
            )

            return None

        finally:

            # ------------------------------------------------
            # CLOSE CHROME
            # ------------------------------------------------

            if context:

                try:

                    await context.close()

                except Exception as e:

                    print(
                        f"[CHROME] Close error: {e}"
                    )


# ============================================================
# MANUAL MEET TEST
# ============================================================

async def open_meet(
    meet_link: str,
):

    async with async_playwright() as p:

        context = await create_chrome_context(
            p
        )

        page = context.pages[0]

        await prepare_meet_page(
            page,
            meet_link,
        )

        print_audio_routing()

        await turn_camera_off(
            page
        )

        await check_microphone(
            page
        )

        await configure_google_meet_audio_devices(
            page
        )

        print()
        print(
            "Google Meet audio:"
        )

        print(
            "Microphone -> CABLE Output"
        )

        print(
            "Speaker    -> CABLE Input"
        )

        print()

        input(
            "Press ENTER to close Chrome..."
        )

        await context.close()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    if len(sys.argv) > 1:

        command = sys.argv[1]

        # --------------------------------------------
        # ONE-TIME AUDIO SETUP
        # --------------------------------------------

        if command == "--setup":

            if len(sys.argv) < 3:

                print(
                    "Usage:"
                )

                print(
                    "python -m app.services.meet_bot --setup <MEET_LINK>"
                )

                sys.exit(1)

            meet_link = sys.argv[2]

            asyncio.run(
                setup_meet_audio_devices(
                    meet_link
                )
            )

        # --------------------------------------------
        # NORMAL INTERVIEW
        # --------------------------------------------

        else:

            print(
                "Unknown command."
            )

            print()
            print(
                "Use:"
            )

            print(
                "python -m app.services.meet_bot --setup <MEET_LINK>"
            )

    else:

        meet_link = input(
            "Enter Google Meet link: "
        ).strip()

        if not meet_link:

            print(
                "No Meet link provided."
            )

            sys.exit(1)

        asyncio.run(
            run_meet_bot(
                interview_id=0,
                meet_link=meet_link,
            )
        )