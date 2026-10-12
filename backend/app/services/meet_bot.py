import asyncio
import os
import sys
import json
import threading
from pathlib import Path

from playwright.async_api import async_playwright

from app.database.database import SessionLocal
from app.models.interview import Interview
from app.services.elevenlabs_agent import get_meet_speaker_device_name, run_alena


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
    """Open Chrome with the saved Google account and force Meet audio routing."""

    meet_mic = os.getenv(
        "MEET_MIC_DEVICE",
        "CABLE Output (VB-Audio Virtual Cable)",
    )

    meet_mic_script = """
(() => {
    const targetName = %TARGET_MIC%;

    const originalGetUserMedia =
        navigator.mediaDevices.getUserMedia.bind(
            navigator.mediaDevices
        );

    navigator.mediaDevices.getUserMedia = async function(constraints) {
        if (!constraints || !constraints.audio) {
            return originalGetUserMedia(constraints);
        }

        try {
            const devices =
                await navigator.mediaDevices.enumerateDevices();

            const target = devices.find(
                d =>
                    d.kind === "audioinput" &&
                    d.label.toLowerCase().trim() ===
                        targetName.toLowerCase().trim()
            );

            if (target) {
                const audioConstraints =
                    constraints.audio === true
                        ? {}
                        : { ...constraints.audio };

                audioConstraints.deviceId = {
                    exact: target.deviceId,
                };

                constraints = {
                    ...constraints,
                    audio: audioConstraints,
                };

                console.log(
                    "[MEET AUDIO] Forced microphone:",
                    target.label
                );
            } else {
                throw new DOMException(
                    `Required Meet microphone not found: ${targetName}`,
                    "NotFoundError"
                );
            }
        } catch (error) {
            console.error(
                "[MEET AUDIO] Could not select required microphone:",
                targetName,
                error
            );
            throw error;
        }

        return originalGetUserMedia(constraints);
    };
})();
""".replace("%TARGET_MIC%", json.dumps(meet_mic))

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
            "--use-fake-ui-for-media-stream",
            "--window-size=900,600",
            "--window-position=50,50",
            "--force-device-scale-factor=1",
        ],
    )

    await context.add_init_script(script=meet_mic_script)

    print(
        f"[MEET AUDIO] Forced microphone target: {meet_mic}"
    )

    return context


async def open_meet_audio_settings(page):
    """Dismiss Meet's camera warning if present, then open verified Audio settings."""
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    audio_settings_button = page.get_by_role(
        "button", name="Audio settings", exact=True
    )
    settings_dialog = page.get_by_role("dialog", name="Settings", exact=True)
    camera_warning = page.get_by_role(
        "dialog", name="Camera might be blocked", exact=True
    )
    click_errors = []

    try:
        await audio_settings_button.wait_for(state="visible", timeout=10000)
    except PlaywrightTimeoutError as error:
        raise RuntimeError(
            "Timed out waiting for Google Meet's Audio settings button to become visible."
        ) from error

    async def dismiss_camera_warning():
        if not await camera_warning.is_visible():
            return True
        close_button = camera_warning.get_by_role(
            "button", name="Close", exact=True
        )
        try:
            await close_button.wait_for(state="visible", timeout=3000)
            await close_button.click(timeout=3000)
            await camera_warning.wait_for(state="hidden", timeout=5000)
            print("[MEET AUDIO] Dismissed the 'Camera might be blocked' warning.")
            return True
        except Exception as error:
            click_errors.append(
                f"camera warning Close action: {type(error).__name__}: {error}"
            )
            return False

    async def settings_is_visible(timeout_ms):
        try:
            await settings_dialog.wait_for(state="visible", timeout=timeout_ms)
            return await settings_dialog.is_visible()
        except PlaywrightTimeoutError:
            return False

    async def capture_failure():
        try:
            expanded_state = await audio_settings_button.get_attribute("aria-expanded")
        except Exception as error:
            expanded_state = f"unavailable ({type(error).__name__}: {error})"

        visible_dialogs = []
        try:
            dialogs = page.get_by_role("dialog")
            for index in range(await dialogs.count()):
                dialog = dialogs.nth(index)
                if await dialog.is_visible():
                    visible_dialogs.append(await dialog.aria_snapshot())
        except Exception as error:
            visible_dialogs.append(
                f"Dialog inspection failed ({type(error).__name__}: {error})"
            )

        diagnostic_dir = Path(__file__).resolve().parents[2] / "data" / "diagnostics"
        log_path = diagnostic_dir / "meet_audio_settings_diagnostics.txt"
        try:
            await log_audio_settings_diagnostics(page)
        except Exception as error:
            click_errors.append(
                f"page-state capture: {type(error).__name__}: {error}"
            )

        raise RuntimeError(
            "Google Meet's Settings dialog did not become visible. "
            f"Audio settings aria-expanded={expanded_state!r}; "
            f"visible dialogs={visible_dialogs or '<none>'}; "
            f"click attempts={click_errors or '<no click exception>'}; "
            f"page-state screenshot/log: {diagnostic_dir / 'meet_audio_settings.png'}; {log_path}"
        )

    async def click_and_verify(label, *, force=False, dom=False, timeout_ms=2500):
        try:
            if dom:
                await audio_settings_button.evaluate("button => button.click()")
            else:
                await audio_settings_button.click(force=force, timeout=timeout_ms)
        except PlaywrightTimeoutError as error:
            click_errors.append(f"{label}: {type(error).__name__}: {error}")
        except Exception as error:
            click_errors.append(f"{label}: {type(error).__name__}: {error}")
        if await settings_is_visible(5000):
            return True
        click_errors.append(f"{label}: Settings dialog did not become visible.")
        return False

    if not await dismiss_camera_warning():
        await capture_failure()

    # Try an ordinary user-like click first after removing the observed overlay.
    if await click_and_verify("normal click", timeout_ms=2500):
        return

    # The warning may have appeared during the first attempt; close it before
    # retrying. Then use a forced click only if the normal retry still fails.
    if not await dismiss_camera_warning():
        await capture_failure()
    if await click_and_verify("normal retry", timeout_ms=2500):
        return

    if not await dismiss_camera_warning():
        await capture_failure()
    if await click_and_verify("forced click", force=True, timeout_ms=5000):
        return

    # Final, button-scoped DOM fallback. Success still requires the exact
    # Settings dialog to become visible.
    if not await dismiss_camera_warning():
        await capture_failure()
    if await click_and_verify("button DOM click", dom=True):
        return

    # A camera warning can appear during the final fallback too. Dismiss it
    # and make one last ordinary click, still requiring the Settings dialog.
    if await camera_warning.is_visible():
        if not await dismiss_camera_warning():
            await capture_failure()
        if await click_and_verify("normal retry after camera warning", timeout_ms=2500):
            return

    await capture_failure()


async def log_audio_settings_diagnostics(page):
    """Capture temporary diagnostics while Meet's Audio settings are open."""
    diagnostic_dir = Path(__file__).resolve().parents[2] / "data" / "diagnostics"
    screenshot_path = diagnostic_dir / "meet_audio_settings.png"
    log_path = diagnostic_dir / "meet_audio_settings_diagnostics.txt"
    lines = [
        "[MEET AUDIO DIAGNOSTICS] Audio settings panel snapshot",
        f"Screenshot: {screenshot_path}",
        f"Diagnostics: {log_path}",
    ]

    try:
        diagnostic_dir.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(screenshot_path), full_page=False)
        lines.append(f"Screenshot saved: {screenshot_path}")
    except Exception as error:
        lines.append(f"Screenshot failed: {type(error).__name__}: {error}")

    body = page.locator("body")
    try:
        snapshot = await body.aria_snapshot()
        lines.extend(["", "[ACCESSIBILITY SNAPSHOT: visible page with Audio panel open]", snapshot])
    except Exception as error:
        lines.append(
            f"[ACCESSIBILITY SNAPSHOT unavailable] {type(error).__name__}: {error}"
        )

    for role in ("button", "combobox"):
        lines.extend(["", f"[VISIBLE {role.upper()}S]"])
        try:
            controls = page.get_by_role(role)
            for index in range(await controls.count()):
                control = controls.nth(index)
                if await control.is_visible():
                    lines.append(f"{role}[{index}]: {await control.aria_snapshot()}")
        except Exception as error:
            lines.append(f"Could not inspect {role}s: {type(error).__name__}: {error}")

    lines.extend(["", "[VISIBLE LABEL ELEMENTS]"])
    try:
        labels = page.locator("label")
        for index in range(await labels.count()):
            label = labels.nth(index)
            if await label.is_visible():
                details = await label.evaluate(
                    """el => ({
                        text: (el.innerText || el.textContent || "").trim(),
                        for: el.htmlFor,
                        ariaLabel: el.getAttribute("aria-label"),
                        html: el.outerHTML.slice(0, 1200)
                    })"""
                )
                lines.append(f"label[{index}]: {json.dumps(details, ensure_ascii=False)}")
    except Exception as error:
        lines.append(f"Could not inspect labels: {type(error).__name__}: {error}")

    lines.extend(["", "[VISIBLE MICROPHONE-RELATED DOM]"])
    try:
        nodes = await body.evaluate(
            """body => Array.from(body.querySelectorAll("*"))
                .filter(el => {
                    const rect = el.getBoundingClientRect();
                    const style = getComputedStyle(el);
                    const visible = rect.width > 0 && rect.height > 0 &&
                        style.visibility !== "hidden" && style.display !== "none";
                    const identifyingText = [
                        el.getAttribute("aria-label") || "",
                        el.getAttribute("aria-labelledby") || "",
                        el.getAttribute("role") || "",
                        el.getAttribute("title") || "",
                        el.id || "",
                        el.innerText || ""
                    ].join(" ");
                    return visible && /microphone|microphones|audio input/i.test(identifyingText);
                })
                .slice(0, 20)
                .map(el => ({
                    tag: el.tagName,
                    role: el.getAttribute("role"),
                    ariaLabel: el.getAttribute("aria-label"),
                    ariaLabelledby: el.getAttribute("aria-labelledby"),
                    text: (el.innerText || el.textContent || "").trim().slice(0, 300),
                    html: el.outerHTML.slice(0, 1600),
                    parentHtml: el.parentElement ? el.parentElement.outerHTML.slice(0, 2400) : ""
                }))"""
        )
        lines.append(json.dumps(nodes, ensure_ascii=False, indent=2))
    except Exception as error:
        lines.append(f"Could not inspect microphone DOM: {type(error).__name__}: {error}")

    output = "\n".join(lines)
    try:
        log_path.write_text(output, encoding="utf-8")
    except Exception as error:
        output += f"\nCould not save diagnostics file: {type(error).__name__}: {error}"
    print(output)


async def select_meet_microphone(page, device_name: str, speaker_device_name: str):
    """Select Meet's virtual microphone and the speaker endpoint captured by WASAPI."""
    try:
        await open_meet_audio_settings(page)

        await log_audio_settings_diagnostics(page)
        microphone_selector = page.get_by_role("button", name="Microphone:", exact=False)
        await microphone_selector.wait_for(state="visible", timeout=10000)
        accessible_snapshot = await microphone_selector.aria_snapshot()
        name_marker = 'button "'
        name_start = accessible_snapshot.find(name_marker)
        if name_start >= 0:
            name_start += len(name_marker)
            name_end = accessible_snapshot.find('"', name_start)
            current_accessible_name = (
                accessible_snapshot[name_start:name_end]
                if name_end >= 0
                else accessible_snapshot
            )
        else:
            current_accessible_name = accessible_snapshot

        target_device_name = device_name
        if target_device_name not in current_accessible_name:
            await microphone_selector.click()
            await page.wait_for_timeout(500)
            microphone_option = page.get_by_text(target_device_name, exact=True)
            await microphone_option.wait_for(state="visible", timeout=5000)
            await microphone_option.click()
            await page.wait_for_timeout(500)

        verified_microphone = await microphone_selector.aria_snapshot()
        if target_device_name not in verified_microphone:
            raise RuntimeError(
                "Meet microphone selection did not verify; expected "
                f"{target_device_name!r}, got {verified_microphone!r}."
            )
        print(f"[MEET AUDIO] Verified microphone: {target_device_name}")

        speaker_selector = page.get_by_role(
            "button", name="Speaker:", exact=False
        )
        await speaker_selector.wait_for(state="visible", timeout=10000)
        current_speaker = await speaker_selector.aria_snapshot()
        if speaker_device_name not in current_speaker:
            await speaker_selector.click()
            await page.wait_for_timeout(500)
            speaker_option = page.get_by_text(speaker_device_name, exact=True)
            await speaker_option.wait_for(state="visible", timeout=5000)
            await speaker_option.click()
            await page.wait_for_timeout(500)

        verified_speaker = await speaker_selector.aria_snapshot()
        if speaker_device_name not in verified_speaker:
            raise RuntimeError(
                "Meet speaker selection did not verify; expected "
                f"{speaker_device_name!r}, got {verified_speaker!r}."
            )
        print(
            "[MEET AUDIO] Verified speaker output for candidate capture: "
            f"{speaker_device_name}"
        )

        close = page.get_by_role("button", name="Close")
        if await close.is_visible():
            await close.click()
            await page.wait_for_timeout(500)

    except Exception as error:
        print(f"[MEET AUDIO] Settings microphone selection failed: {error}")
        raise

async def ensure_meet_microphone_off(page):
    """Require Meet's microphone to be muted before diagnostic joining."""
    for name in ("Turn off microphone", "Turn off mic", "Mute"):
        button = page.get_by_role("button", name=name).first
        try:
            if await button.is_visible():
                await button.click()
                print(f"[MEET AUDIO DIAGNOSTICS] Muted Meet microphone: {name}")
                return
        except Exception:
            continue

    for name in ("Turn on microphone", "Turn on mic", "Unmute"):
        button = page.get_by_role("button", name=name).first
        try:
            if await button.is_visible():
                print("[MEET AUDIO DIAGNOSTICS] Meet microphone is already muted.")
                return
        except Exception:
            continue

    raise RuntimeError(
        "Could not confirm that the Meet microphone is muted; "
        "stopping diagnostics before joining."
    )


async def ensure_meet_microphone_on(page):
    """Make sure Google Meet is sending the virtual microphone."""

    selectors = [
        "Turn on microphone",
        "Turn on mic",
        "Unmute",
    ]

    for name in selectors:
        try:
            button = page.get_by_role(
                "button",
                name=name,
            )
            if await button.is_visible():
                await button.click()
                print(
                    f"[MEET AUDIO] Microphone enabled: {name}"
                )
                return
        except Exception:
            pass

    print(
        "[MEET AUDIO] Microphone button was not found; "
        "Meet may already be unmuted."
    )


async def log_meet_join_failure(page):
    """Capture the current page state when expected Meet join controls are absent."""
    diagnostic_dir = Path(__file__).resolve().parents[2] / "data" / "diagnostics"
    screenshot_path = diagnostic_dir / "meet_join_failure.png"
    log_path = diagnostic_dir / "meet_join_failure_diagnostics.txt"
    diagnostic_dir.mkdir(parents=True, exist_ok=True)

    try:
        page_url = page.url
    except Exception as error:
        page_url = f"<unavailable: {type(error).__name__}: {error}>"

    try:
        page_title = await page.title()
    except Exception as error:
        page_title = f"<unavailable: {type(error).__name__}: {error}>"

    lines = [
        "[MEET JOIN FAILURE DIAGNOSTICS]",
        f"Current URL: {page_url}",
        f"Page title: {page_title}",
    ]

    try:
        await page.screenshot(path=str(screenshot_path), full_page=False)
        lines.append(f"Screenshot saved: {screenshot_path}")
    except Exception as error:
        lines.append(f"Screenshot failed: {type(error).__name__}: {error}")

    button_names = []
    try:
        buttons = page.get_by_role("button")
        for index in range(await buttons.count()):
            button = buttons.nth(index)
            if await button.is_visible():
                button_names.append(await button.aria_snapshot())
    except Exception as error:
        lines.append(f"Button inventory failed: {type(error).__name__}: {error}")

    lines.append("[VISIBLE BUTTONS AND ACCESSIBLE NAMES]")
    lines.extend(button_names or ["<none found>"])

    page_text = ""
    try:
        page_text = (await page.locator("body").inner_text(timeout=3000)).casefold()
    except Exception as error:
        lines.append(f"Visible page text inspection failed: {type(error).__name__}: {error}")

    signals = []
    lowered_url = page_url.casefold()
    if "accounts.google.com" in lowered_url or "sign in" in page_text or "log in" in page_text:
        signals.append("Possible Google sign-in page")
    if any(phrase in page_text for phrase in (
        "waiting for someone to let you in",
        "you asked to join",
        "waiting for host",
    )):
        signals.append("Possible Meet waiting room")
    if any(phrase in page_text for phrase in (
        "allow microphone",
        "allow camera",
        "permission",
        "blocked",
    )):
        signals.append("Possible browser or Meet permission prompt")
    if not signals:
        signals.append(
            "No sign-in, waiting-room, or permission text detected; "
            "inspect the screenshot and visible button inventory for a changed pre-join UI."
        )
    lines.append("[PAGE STATE CLUES]")
    lines.extend(signals)

    output = "\n".join(lines)
    try:
        log_path.write_text(output, encoding="utf-8")
        print(output)
        print(f"[MEET JOIN FAILURE DIAGNOSTICS] Log saved: {log_path}")
    except Exception as error:
        output += f"\nDiagnostics log save failed: {type(error).__name__}: {error}"
        print(output)

    return {
        "url": page_url,
        "title": page_title,
        "signals": "; ".join(signals),
        "screenshot": str(screenshot_path),
        "log": str(log_path),
    }


def _log_page_lifecycle(page, lifecycle_events=None, phase="in-call detection"):
    """Log browser target state without querying locators on a closed page."""
    state = {"phase": phase, "page_is_closed": None, "url": None,
             "context_pages": None, "browser_connected": None,
             "close_events": lifecycle_events or {}}
    try:
        state["page_is_closed"] = page.is_closed()
    except Exception as error:
        state["page_is_closed"] = f"unavailable: {type(error).__name__}: {error}"
    try:
        state["url"] = page.url
    except Exception as error:
        state["url"] = f"unavailable: {type(error).__name__}: {error}"
    try:
        context = page.context
        pages = context.pages
        state["context_pages"] = []
        for context_page in pages:
            try:
                state["context_pages"].append({
                    "url": context_page.url,
                    "is_closed": context_page.is_closed(),
                })
            except Exception as error:
                state["context_pages"].append(
                    f"unavailable: {type(error).__name__}: {error}"
                )
        browser = context.browser
        state["browser_connected"] = (
            browser.is_connected() if browser is not None else None
        )
    except Exception as error:
        state["context_state_error"] = f"{type(error).__name__}: {error}"
    print("[MEET AUDIO DIAGNOSTICS] Page lifecycle: " + json.dumps(state, ensure_ascii=False))

async def join_meet(page, meet_link: str, diagnostics_only: bool = False, lifecycle_events=None):
    """Open and join the Google Meet."""

    await page.goto(
        meet_link,
        wait_until="domcontentloaded",
    )

    await page.wait_for_load_state("domcontentloaded")

    async def capture_if_already_in_call():
        if not diagnostics_only:
            return False

        audio_settings_button = page.get_by_role(
            "button", name="Audio settings", exact=True
        ).first
        people_button = page.get_by_role(
            "button", name="People", exact=True
        ).first
        leave_call_button = page.get_by_role(
            "button", name="Leave call", exact=True
        ).first
        _log_page_lifecycle(page, lifecycle_events)
        try:
            print(
                "[MEET AUDIO DIAGNOSTICS] Before Audio settings is_visible()",
                flush=True,
            )
            audio_settings_visible = await audio_settings_button.is_visible()
            print(
                "[MEET AUDIO DIAGNOSTICS] After Audio settings is_visible(): "
                f"{audio_settings_visible}",
                flush=True,
            )
            if not audio_settings_visible:
                return False
            if not await people_button.is_visible() or not await leave_call_button.is_visible():
                return False
        except Exception as error:
            print(
                "[MEET AUDIO DIAGNOSTICS] Audio settings is_visible() raised "
                f"{type(error).__name__}: {error}",
                flush=True,
            )
            _log_page_lifecycle(page, lifecycle_events, phase="in-call detection error")
            raise

        print(
            "[MEET AUDIO DIAGNOSTICS] Already in the meeting; "
            "capturing Audio settings without using pre-join controls."
        )
        await ensure_meet_microphone_off(page)
        await open_meet_audio_settings(page)
        await log_audio_settings_diagnostics(page)
        print(
            "[MEET AUDIO DIAGNOSTICS] Capture complete; "
            "stopping before microphone selection and Alena."
        )
        return True

    if await capture_if_already_in_call():
        return

    join_button = None
    for name in ("Join now", "Ask to join"):
        candidate = page.get_by_role("button", name=name, exact=True).first
        try:
            await candidate.wait_for(state="visible", timeout=60000)
            join_button = candidate
            break
        except Exception as error:
            if diagnostics_only and type(error).__name__ == "TargetClosedError":
                _log_page_lifecycle(
                    page, lifecycle_events, phase="join-control wait target closed"
                )
                raise RuntimeError(
                    "Google Meet's page closed while waiting for the 'Join now' or "
                    "'Ask to join' control. The diagnostic cleanup had not started; "
                    "see the lifecycle log to determine whether the page, context, "
                    "or browser disconnected."
                ) from error
            continue
    if join_button is None:
        # Meet may finish rendering its in-call toolbar while the pre-join
        # locators are waiting. Recheck before treating that state as failure.
        if await capture_if_already_in_call():
            return

        diagnostics = await log_meet_join_failure(page)
        raise RuntimeError(
            "Google Meet pre-join screen did not become ready (join control not found). "
            f"Page URL: {diagnostics['url']}; title: {diagnostics['title']}; "
            f"page clues: {diagnostics['signals']}; "
            f"screenshot: {diagnostics['screenshot']}; log: {diagnostics['log']}"
        )

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

    try:
        button = page.get_by_text("Leave", exact=True)
        if await button.is_visible():
            await button.click()
    except Exception:
        pass

    if diagnostics_only:
        await ensure_meet_microphone_off(page)

    # Join the meeting.
    await join_button.click()

    deadline = asyncio.get_running_loop().time() + 90
    while asyncio.get_running_loop().time() < deadline:
        waiting_for_admission = False
        for text in (
            "Please wait until a meeting host brings you into the call",
            "Waiting for someone to let you in",
            "You asked to join",
        ):
            try:
                if await page.get_by_text(text, exact=False).first.is_visible():
                    waiting_for_admission = True
                    break
            except Exception:
                continue

        if waiting_for_admission:
            await page.wait_for_timeout(500)
            continue

        call_confirmed = False
        for name in ("Leave call", "Leave", "Turn off microphone", "Turn off mic"):
            try:
                if await page.get_by_role("button", name=name).first.is_visible():
                    call_confirmed = True
                    break
            except Exception:
                continue

        if call_confirmed:
            break

        await page.wait_for_timeout(500)
    else:
        raise RuntimeError("Google Meet did not confirm that the bot joined the meeting.")

    if diagnostics_only:
        await open_meet_audio_settings(page)
        await log_audio_settings_diagnostics(page)
        print(
            "[MEET AUDIO DIAGNOSTICS] Capture complete; "
            "stopping before microphone selection and Alena."
        )
        return

    await select_meet_microphone(
        page,
        os.getenv(
            "MEET_MIC_DEVICE",
            "CABLE Output (VB-Audio Virtual Cable)",
        ),
        get_meet_speaker_device_name(),
    )

    await ensure_meet_microphone_on(page)

    await page.wait_for_timeout(250)


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
        fallback = page.get_by_text("Leave", exact=True)
        if await fallback.is_visible():
            await fallback.click()
    except Exception:
        pass


async def meet_has_ended(page) -> bool:
    if page.is_closed():
        return True
    for phrase in ("You left the meeting", "You've left the meeting", "The meeting has ended", "Call ended"):
        try:
            if await page.get_by_text(phrase, exact=False).first.is_visible():
                return True
        except Exception:
            continue
    return False


async def run_meet_audio_diagnostics(meet_link: str):
    """Join Meet muted, capture Audio settings diagnostics, and stop without Alena."""
    async with async_playwright() as playwright:
        context = await create_browser(playwright)
        diagnostic_error = None
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            lifecycle_events = {
                "page_close_event": "not observed",
                "context_close_event": "not observed",
                "browser_disconnected_event": "not observed",
            }
            page.on(
                "close",
                lambda *args: lifecycle_events.update(
                    page_close_event={"observed": True, "reason": "Playwright close event provides no reason."}
                ),
            )
            context.on(
                "close",
                lambda *args: lifecycle_events.update(
                    context_close_event={"observed": True, "reason": "Playwright close event provides no reason."}
                ),
            )
            browser = context.browser
            if browser is not None:
                browser.on(
                    "disconnected",
                    lambda *args: lifecycle_events.update(
                        browser_disconnected_event={"observed": True, "reason": "Disconnected event provides no cause."}
                    ),
                )
            await join_meet(
                page, meet_link, diagnostics_only=True,
                lifecycle_events=lifecycle_events,
            )
        except BaseException as error:
            diagnostic_error = error
            print(
                f"[MEET AUDIO DIAGNOSTICS] Diagnostic failed: {type(error).__name__}: {error}",
                flush=True,
            )
            raise
        finally:
            try:
                await context.close()
            except Exception as cleanup_error:
                print(
                    "[MEET AUDIO DIAGNOSTICS] Cleanup failed: "
                    f"{type(cleanup_error).__name__}: {cleanup_error}",
                    flush=True,
                )
                if diagnostic_error is None:
                    raise


async def run_meet_bot(interview_id: int, meet_link: str):
    """Run the complete Google Meet + Alena interview."""

    async with async_playwright() as playwright:

        context = await create_browser(playwright)

        try:
            page = context.pages[0] if context.pages else await context.new_page()
        except Exception:
            await context.close()
            raise

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
            stop_alena = threading.Event()
            alena_task = asyncio.create_task(
                asyncio.to_thread(run_alena, interview_id, stop_alena)
            )
            while not alena_task.done():
                if await meet_has_ended(page):
                    print("Google Meet ended while Alena was active; interrupting the session.")
                    stop_alena.set()
                    break
                try:
                    await asyncio.wait_for(asyncio.shield(alena_task), timeout=1)
                except asyncio.TimeoutError:
                    pass
            alena_result = await alena_task

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
            try:
                await context.close()
            except Exception as cleanup_error:
                print(f"Meet browser cleanup failed: {type(cleanup_error).__name__}")


if __name__ == "__main__":

    if len(sys.argv) == 3 and sys.argv[1] == "--audio-diagnostics":
        asyncio.run(run_meet_audio_diagnostics(sys.argv[2]))
    elif len(sys.argv) >= 3:
        interview_id = int(sys.argv[1])
        meet_link = sys.argv[2]

        asyncio.run(
            run_meet_bot(
                interview_id,
                meet_link,
            )
        )
    else:
        print(
            "Usage: python meet_bot.py <interview_id> <meet_link>\n"
            "   or: python meet_bot.py --audio-diagnostics <meet_link>"
        )
        sys.exit(1)
