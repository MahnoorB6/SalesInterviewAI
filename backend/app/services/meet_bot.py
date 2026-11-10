import asyncio
import os
import sys
import json
import logging
import threading
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

from app.database.database import SessionLocal
from app.models.interview import Interview
from app.services.elevenlabs_agent import get_meet_speaker_device_name, run_alena
from app.logging_config import (
    configure_backend_logging,
    reset_interview_context,
    set_interview_context,
    set_interview_stage,
)


configure_backend_logging()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


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

        const diagnosticState = window.__salesInterviewMeetAudioDiagnostics = {
            configuredDevice: targetName,
            permission: "unavailable",
            availableInputs: [],
            selectedInput: null,
            activeTracks: []
        };

        try {
            const getMicrophonePermission = async () => {
                try {
                    return (await navigator.permissions.query({ name: "microphone" })).state;
                } catch (_) {
                    return "unavailable";
                }
            };
            let permissionState = await getMicrophonePermission();
            diagnosticState.permission = permissionState;
            let devices = await navigator.mediaDevices.enumerateDevices();
            diagnosticState.availableInputs = devices
                .filter(d => d.kind === "audioinput")
                .map(d => d.label || "label unavailable");
            let target = devices.find(
                d =>
                    d.kind === "audioinput" &&
                    d.label.toLowerCase().trim() ===
                        targetName.toLowerCase().trim()
            );

            // Chromium may hide device labels until microphone permission has
            // been granted. Request permission through the original API first,
            // stop that temporary stream, then resolve and request the exact
            // configured endpoint. Never hand the temporary stream to Meet.
            if (!target && permissionState !== "denied") {
                console.info(
                    "[MEET AUDIO] Microphone labels unavailable; requesting browser permission before resolving the configured device.",
                    `permission=${permissionState}`,
                    `url=${location.href}`
                );
                const permissionStream = await originalGetUserMedia({ audio: true });
                for (const track of permissionStream.getTracks()) track.stop();
                permissionState = await getMicrophonePermission();
                diagnosticState.permission = permissionState;
                devices = await navigator.mediaDevices.enumerateDevices();
                diagnosticState.availableInputs = devices
                    .filter(d => d.kind === "audioinput")
                    .map(d => d.label || "label unavailable");
                target = devices.find(
                    d =>
                        d.kind === "audioinput" &&
                        d.label.toLowerCase().trim() ===
                            targetName.toLowerCase().trim()
                );
            }

            if (target) {
                diagnosticState.selectedInput = target.label;
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
                    target.label,
                    `permission=${permissionState}`,
                    `url=${location.href}`
                );
            } else {
                console.error(
                    "[MEET AUDIO] Configured microphone unavailable after permission check:",
                    targetName,
                    `permission=${permissionState}`,
                    `url=${location.href}`
                );
                throw new DOMException(
                    `Required Meet microphone not found: ${targetName}`,
                    "NotFoundError"
                );
            }

            const stream = await originalGetUserMedia(constraints);
            const tracks = stream.getAudioTracks();
            if (!tracks.length) {
                throw new DOMException(
                    `No audio track was returned for ${targetName}`,
                    "NotFoundError"
                );
            }

            for (const track of tracks) {
                const settings = track.getSettings ? track.getSettings() : {};
                if (settings.deviceId && settings.deviceId !== target.deviceId) {
                    for (const audioTrack of tracks) audioTrack.stop();
                    throw new DOMException(
                        `Active Meet microphone did not match ${targetName}`,
                        "NotReadableError"
                    );
                }
                const verification = settings.deviceId
                    ? "deviceId"
                    : (track.label === target.label ? "track label" : "unavailable");
                diagnosticState.activeTracks.push({
                    label: track.label || "label unavailable",
                    verification,
                    readyState: track.readyState,
                    muted: track.muted,
                    enabled: track.enabled,
                    sampleRate: settings.sampleRate || null,
                    channelCount: settings.channelCount || null
                });
                const log = verification === "unavailable" ? console.warn : console.log;
                log(
                    "[MEET AUDIO] Active microphone track:",
                    track.label || "label unavailable",
                    `verification=${verification}`,
                    `readyState=${track.readyState}`,
                    `muted=${track.muted}`,
                    `enabled=${track.enabled}`,
                    `sampleRate=${settings.sampleRate || "unavailable"}`,
                    `channelCount=${settings.channelCount || "unavailable"}`
                );
            }
            return stream;
        } catch (error) {
            if (error && (error.name === "NotAllowedError" || error.name === "SecurityError")) {
                console.error(
                    "[MEET AUDIO] Browser microphone access was denied. " +
                    "Check Chrome site permission and Windows microphone privacy settings; " +
                    "browser automation cannot distinguish which policy blocked access.",
                    error.name,
                    error
                );
            }
            console.error(
                "[MEET AUDIO] Could not select required microphone:",
                targetName,
                error
            );
            throw error;
        }

    };
})();
""".replace("%TARGET_MIC%", json.dumps(meet_mic))

    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        channel="chrome",
        headless=False,
        chromium_sandbox=True,
        # Preserve the existing camera grant. Microphone access is granted
        # separately below and scoped to the Meet origin.
        permissions=["camera"],
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

    try:
        await context.grant_permissions(
            ["camera", "microphone"],
            origin="https://meet.google.com",
        )
        logger.info(
            "Granted browser camera and microphone permissions for origin=%s",
            "https://meet.google.com",
            extra={"stage": "browser_permissions"},
        )
    except Exception:
        await context.close()
        logger.exception(
            "Could not grant required Meet-origin microphone permission; refusing to start Meet",
            extra={"stage": "browser_permissions"},
        )
        raise

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

    button_count = await audio_settings_button.count()
    if button_count != 1:
        raise RuntimeError(
            "Expected exactly one Google Meet Audio settings button; "
            f"found {button_count}."
        )

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

        pointer_blocker = "unavailable"
        extension_resources = []
        try:
            pointer_details = await audio_settings_button.evaluate(
                """button => {
                    const rect = button.getBoundingClientRect();
                    const x = rect.left + rect.width / 2;
                    const y = rect.top + rect.height / 2;
                    const hit = document.elementFromPoint(x, y);
                    const describe = el => el && ({
                        tag: el.tagName,
                        role: el.getAttribute('role'),
                        ariaLabel: el.getAttribute('aria-label'),
                        id: el.id,
                        className: typeof el.className === 'string' ? el.className : '',
                        injectedContentController: el.getAttribute('data-inject-content-controller'),
                        html: el.outerHTML.slice(0, 1000)
                    });
                    return {
                        button: describe(button),
                        hitTarget: describe(hit),
                        ancestors: (() => {
                            const result = [];
                            for (let node = hit, i = 0; node && i < 5; node = node.parentElement, i++)
                                result.push(describe(node));
                            return result;
                        })()
                    };
                }"""
            )
            pointer_blocker = json.dumps(pointer_details, ensure_ascii=False)
            extension_resources = await page.evaluate(
                """() => performance.getEntriesByType('resource')
                    .map(entry => entry.name)
                    .filter(name => name.startsWith('chrome-extension://'))
                    .slice(-20)"""
            )
        except Exception as error:
            pointer_blocker = f"inspection failed ({type(error).__name__}: {error})"

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
            f"pointer hit-test={pointer_blocker}; "
            f"extension resources={extension_resources or '<none observed>'}; "
            f"click attempts={click_errors or '<no click exception>'}; "
            f"page-state screenshot/log: {diagnostic_dir / 'meet_audio_settings.png'}; {log_path}"
        )

    async def verify_dialog(timeout_ms=5000):
        try:
            await settings_dialog.wait_for(state="visible", timeout=timeout_ms)
            return await settings_dialog.is_visible()
        except PlaywrightTimeoutError:
            return False

    async def keyboard_activate(timeout_ms=5000):
        # Reacquire after a UI transition and use Playwright's supported focus
        # and keyboard APIs. This avoids clicking through the observed overlay.
        button = page.get_by_role("button", name="Audio settings", exact=True)
        await button.wait_for(state="visible", timeout=timeout_ms)
        if await button.count() != 1:
            raise RuntimeError("Audio settings button became ambiguous before keyboard activation.")
        await button.focus(timeout=timeout_ms)
        focused = await button.evaluate("element => document.activeElement === element")
        if not focused:
            raise RuntimeError("Could not focus the exact Audio settings button.")
        await page.keyboard.press("Enter")
        if await verify_dialog(timeout_ms):
            logger.info("Meet Audio settings opened via focused Enter key interaction")
            return True
        return False

    if not await dismiss_camera_warning():
        await capture_failure()

    try:
        await audio_settings_button.click(timeout=5000)
    except PlaywrightTimeoutError as error:
        click_errors.append(f"normal click: {type(error).__name__}: {error}")
        if "intercepts pointer events" not in str(error).casefold():
            await capture_failure()
        logger.warning(
            "Meet Audio settings pointer interaction intercepted; attempting focused Enter",
            extra={"stage": "meet_audio_settings"},
        )
        try:
            if await keyboard_activate():
                return
            click_errors.append("focused Enter: Settings dialog did not become visible.")
        except Exception as keyboard_error:
            click_errors.append(
                f"focused Enter: {type(keyboard_error).__name__}: {keyboard_error}"
            )
    except Exception as error:
        click_errors.append(f"normal click: {type(error).__name__}: {error}")
        await capture_failure()
    else:
        if await verify_dialog():
            return
        click_errors.append("normal click: Settings dialog did not become visible.")

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

        async def selected_device_name(selector, device_label):
            snapshot = await selector.aria_snapshot()
            marker = f'button "{device_label}: '
            start = snapshot.find(marker)
            if start >= 0:
                start += len(marker)
                end = snapshot.find('"', start)
                if end >= 0:
                    return snapshot[start:end].strip()
            try:
                aria_label = await selector.get_attribute("aria-label")
            except Exception:
                aria_label = None
            if aria_label and aria_label.casefold().startswith(f"{device_label.casefold()}:"):
                return aria_label.split(":", 1)[1].strip()
            return None

        current_microphone = await selected_device_name(microphone_selector, "Microphone")

        target_device_name = device_name
        if (current_microphone or "").casefold() != target_device_name.casefold():
            await microphone_selector.click()
            await page.wait_for_timeout(500)
            microphone_option = page.get_by_text(target_device_name, exact=True)
            await microphone_option.wait_for(state="visible", timeout=5000)
            await microphone_option.click()
            await page.wait_for_timeout(500)

        verified_microphone = await selected_device_name(microphone_selector, "Microphone")
        if (verified_microphone or "").casefold() != target_device_name.casefold():
            raise RuntimeError(
                "Meet microphone selection did not verify; expected "
                f"{target_device_name!r}, got {verified_microphone!r}."
            )
        print(f"[MEET AUDIO] Verified microphone: {target_device_name}")
        logger.info(
            "Meet selected microphone verified device=%s",
            verified_microphone,
            extra={"stage": "meet_audio_selection"},
        )

        speaker_selector = page.get_by_role(
            "button", name="Speaker:", exact=False
        )
        await speaker_selector.wait_for(state="visible", timeout=10000)
        current_speaker = await selected_device_name(speaker_selector, "Speaker")
        if (current_speaker or "").casefold() != speaker_device_name.casefold():
            await speaker_selector.click()
            await page.wait_for_timeout(500)
            speaker_option = page.get_by_text(speaker_device_name, exact=True)
            await speaker_option.wait_for(state="visible", timeout=5000)
            await speaker_option.click()
            await page.wait_for_timeout(500)

        verified_speaker = await selected_device_name(speaker_selector, "Speaker")
        if (verified_speaker or "").casefold() != speaker_device_name.casefold():
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
                exact=False,
            )
            if await button.is_visible():
                await button.click()
                for _ in range(20):
                    state = await get_meet_microphone_state(page)
                    system_warning = await meet_system_microphone_muted(page)
                    if state == "unmuted":
                        # The VB-CABLE input can be silent until ElevenLabs
                        # opens its playback stream. Meet may show a transient
                        # "Microphone problem" warning during setup even when
                        # the selected device and unmuted control are correct.
                        # Do not block the interview on that pre-audio warning;
                        # the active session loop continues recording it.
                        warning_logger = logger.warning if system_warning is True else logger.info
                        warning_logger(
                            "Meet microphone toggle is unmuted before audio starts; system warning=%s",
                            system_warning,
                            extra={"stage": "meet_microphone_ready"},
                        )
                        print(
                            "[MEET AUDIO] Meet microphone toggle is unmuted "
                            f"after clicking {name!r}; system warning={system_warning}. "
                            "Continuing so the live audio stream can initialize."
                        )
                        return
                    await page.wait_for_timeout(250)
                raise RuntimeError(
                    f"Clicked {name!r}, but Meet did not expose an unmuted control state."
                )
        except Exception as error:
            logger.warning(
                "Meet microphone verification attempt failed control=%s error_type=%s error=%s",
                name,
                type(error).__name__,
                error,
            )
            print(
                f"[MEET AUDIO] Microphone enable attempt failed for {name}: "
                f"{type(error).__name__}: {error}"
            )

    state = await get_meet_microphone_state(page)
    system_warning = await meet_system_microphone_muted(page)
    if state == "unmuted":
        warning_logger = logger.warning if system_warning is True else logger.info
        warning_logger(
            "Meet microphone toggle is already unmuted before audio starts; system warning=%s",
            system_warning,
            extra={"stage": "meet_microphone_ready"},
        )
        print(
            "[MEET AUDIO] Meet microphone toggle is already unmuted; "
            f"system warning={system_warning}. Continuing so the live audio stream can initialize."
        )
        return
    if system_warning:
        reason = (
            "Google Meet reports 'Microphone problem' or 'Microphone muted by system'; Meet's toggle "
            f"state is {state!r}."
        )
    elif system_warning is None:
        reason = "Could not verify whether Meet can use the selected microphone."
    else:
        reason = f"Meet microphone state is {state!r} after all unmute controls were checked."
    logger.error(
        "Meet microphone verification failed state=%s system_mic_warning_detected=%s reason=%s",
        state,
        system_warning,
        reason,
    )
    print(f"[MEET AUDIO ERROR] {reason}")
    raise RuntimeError(reason)


async def meet_system_microphone_muted(page) -> bool | None:
    """Detect Meet's mic-problem control and explicit system-mute warning."""
    try:
        warning = page.get_by_text("Microphone muted by system", exact=False).first
        if await warning.is_visible():
            return True
        problem_control = page.get_by_role(
            "button", name="Microphone problem", exact=False
        ).first
        if await problem_control.is_visible():
            return True
        return False
    except Exception as error:
        logger.warning(
            "Could not inspect Meet system-microphone warning error_type=%s error=%s",
            type(error).__name__,
            error,
        )
        return None


async def log_meet_microphone_diagnostics(page, interview_id: int, reason: str):
    """Log permission, page, and visible Meet controls without clicking them."""
    details = {
        "url": "unavailable",
        "microphone_permission": "unavailable",
        "configured_microphone": os.getenv(
            "MEET_MIC_DEVICE", "CABLE Output (VB-Audio Virtual Cable)"
        ),
        "visible_audio_controls": [],
        "browser_permission_prompt": "not observable in page DOM",
        "system_mic_warning_detected": await meet_system_microphone_muted(page),
    }
    try:
        details.update(await page.evaluate("""async () => {
            let permission = "unavailable";
            try {
                permission = (await navigator.permissions.query({name: "microphone"})).state;
            } catch (_) {}
            const visible = element => {
                const rect = element.getBoundingClientRect();
                const style = getComputedStyle(element);
                return rect.width > 0 && rect.height > 0 &&
                    style.visibility !== "hidden" && style.display !== "none";
            };
            const controls = Array.from(document.querySelectorAll('button,[role="button"]'))
                .filter(visible)
                .map(element => (element.getAttribute("aria-label") || element.innerText || "").trim())
                .filter(label => /microphone|use mic|allow|join|leave/i.test(label))
                .slice(0, 20);
            const microphoneControl = Array.from(document.querySelectorAll('button,[role="button"]'))
                .find(element => /microphone:/i.test(element.getAttribute('aria-label') || ''));
            const audioState = window.__salesInterviewMeetAudioDiagnostics || null;
            return {
                url: location.href,
                microphone_permission: permission,
                visible_audio_controls: controls,
                meet_selected_microphone: microphoneControl
                    ? (microphoneControl.getAttribute('aria-label') || microphoneControl.innerText || '').trim()
                    : null,
                available_audio_inputs: Array.from(navigator.mediaDevices?.enumerateDevices
                    ? await navigator.mediaDevices.enumerateDevices()
                    : [])
                    .filter(device => device.kind === 'audioinput')
                    .map(device => device.label || 'label unavailable'),
                active_audio_diagnostics: audioState,
                active_track_signal: audioState?.activeTracks?.length
                    ? "not measured; track metadata does not prove incoming audio"
                    : "unverified; no active microphone track reported"
            };
        }"""))
    except Exception as error:
        details["page_inspection_error"] = f"{type(error).__name__}: {error}"

    details["reason"] = reason
    logger.info(
        "Meet microphone/session diagnostics %s",
        json.dumps(details, ensure_ascii=False, sort_keys=True),
        extra={"interview_id": interview_id, "stage": "meet_microphone_diagnostics"},
    )


async def get_meet_microphone_state(page) -> str:
    """Read the accessible Meet toggle label; never infer state from a click."""
    controls = (
        ("Turn on microphone", "muted"),
        ("Turn on mic", "muted"),
        ("Unmute", "muted"),
        ("Turn off microphone", "unmuted"),
        ("Turn off mic", "unmuted"),
        ("Mute microphone", "unmuted"),
    )
    for name, state in controls:
        try:
            control = page.get_by_role("button", name=name, exact=False).first
            if await control.is_visible():
                return state
        except Exception:
            continue
    return "unknown"


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

async def join_meet(
    page,
    meet_link: str,
    diagnostics_only: bool = False,
    lifecycle_events=None,
    scheduled_at: datetime | None = None,
):
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

    if diagnostics_only:
        await ensure_meet_microphone_off(page)

    if scheduled_at is not None and not diagnostics_only:
        if scheduled_at.tzinfo is None:
            raise ValueError("scheduled_at must include a timezone for exact Meet joining.")
        while True:
            remaining = (scheduled_at - datetime.now(scheduled_at.tzinfo)).total_seconds()
            if remaining <= 0:
                break
            await asyncio.sleep(min(remaining, 0.2))
        join_click_at = datetime.now(scheduled_at.tzinfo)
        lateness_ms = max(0, round((join_click_at - scheduled_at).total_seconds() * 1000))
        logger.info(
            "Scheduled Meet join click scheduled_at=%s click_started_at=%s lateness_ms=%s",
            scheduled_at.isoformat(),
            join_click_at.isoformat(),
            lateness_ms,
            extra={"stage": "meet_scheduled_join"},
        )
        print(
            f"[MEET SCHEDULE] Join click at {join_click_at.isoformat()} "
            f"(scheduled {scheduled_at.isoformat()}, lateness {lateness_ms} ms)."
        )

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
        diagnostics = await log_meet_join_failure(page)
        raise RuntimeError(
            "Google Meet did not confirm that the bot joined the meeting within "
            "90 seconds. Check whether the bot is still waiting for host admission "
            "or whether Meet changed its in-call controls. "
            f"Page URL: {diagnostics['url']}; title: {diagnostics['title']}; "
            f"page clues: {diagnostics['signals']}; "
            f"screenshot: {diagnostics['screenshot']}; log: {diagnostics['log']}"
        )

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
        logger.warning("Meet page closure detected; termination condition=page_closed")
        print("[MEET TERMINATION] Meet page closed; treating browser closure as confirmed termination.")
        return True
    for phrase in ("You left the meeting", "You've left the meeting", "The meeting has ended", "Call ended"):
        try:
            if await page.get_by_text(phrase, exact=False).first.is_visible():
                logger.warning(
                    "Meet end condition detected condition=%s",
                    phrase,
                )
                print(f"[MEET TERMINATION] Confirmed Meet end state: {phrase!r}.")
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


async def run_meet_bot(
    interview_id: int,
    meet_link: str,
    scheduled_at: datetime | None = None,
):
    """Run the complete Google Meet + Alena interview."""

    log_context = set_interview_context(interview_id, "meet_browser_start")
    async with async_playwright() as playwright:

        try:
            context = await create_browser(playwright)
        except Exception:
            logger.exception(
                "Browser creation exception",
                extra={"interview_id": interview_id, "stage": "browser_creation"},
            )
            reset_interview_context(log_context)
            raise

        try:
            page = context.pages[0] if context.pages else await context.new_page()
        except Exception:
            logger.exception(
                "Meet page initialization exception",
                extra={"interview_id": interview_id, "stage": "page_initialization"},
            )
            try:
                await context.close()
            finally:
                reset_interview_context(log_context)
            raise

        def log_meet_audio_console(message):
            text = message.text
            if "[MEET AUDIO]" in text:
                print(f"[MEET BROWSER AUDIO] {text}")
                log_method = logger.error if message.type == "error" else logger.info
                log_method(
                    "Meet browser console audio message type=%s text=%s",
                    message.type,
                    text,
                    extra={"interview_id": interview_id, "stage": "meet_browser_console"},
                )

        page.on("console", log_meet_audio_console)
        page.on(
            "close",
            lambda *_: logger.warning(
                "Meet page close event observed",
                extra={"interview_id": interview_id, "stage": "meet_active"},
            ),
        )
        context.on(
            "close",
            lambda *_: logger.warning(
                "Playwright browser context close event observed",
                extra={"interview_id": interview_id, "stage": "meet_active"},
            ),
        )
        if context.browser is not None:
            context.browser.on(
                "disconnected",
                lambda *_: logger.warning(
                    "Playwright browser disconnected event observed",
                    extra={"interview_id": interview_id, "stage": "meet_active"},
                ),
            )

        stage = "meet_join"
        try:
            print()
            print("=" * 40)
            print("        GOOGLE MEET BOT")
            print("=" * 40)
            print()

            print("Opening Google Meet...")
            set_interview_stage(stage)
            await join_meet(page, meet_link, scheduled_at=scheduled_at)
            await log_meet_microphone_diagnostics(
                page, interview_id, "Meet joined and microphone setup completed; starting Alena"
            )

            stage = "alena_active"
            set_interview_stage(stage)
            print("Google Meet joined.")
            print("Starting Alena...")

            # Run ElevenLabs in a background thread
            # so Playwright can continue controlling Meet.
            stop_alena = threading.Event()
            last_mic_observation = None
            alena_task = asyncio.create_task(
                asyncio.to_thread(run_alena, interview_id, stop_alena)
            )
            while not alena_task.done():
                if await meet_has_ended(page):
                    await log_meet_microphone_diagnostics(
                        page, interview_id,
                        "Meet page closed or Meet end state detected; requesting Alena stop",
                    )
                    print("Google Meet ended while Alena was active; interrupting the session.")
                    stop_alena.set()
                    break
                mic_state = await get_meet_microphone_state(page)
                system_warning = await meet_system_microphone_muted(page)
                observation = (mic_state, system_warning)
                if observation != last_mic_observation:
                    logger.info(
                        "Meet microphone state observed toggle_state=%s system_mic_warning_detected=%s",
                        mic_state,
                        system_warning,
                    )
                    print(
                        "[MEET AUDIO STATE] Microphone toggle state changed/observed: "
                        f"{mic_state}; system mute warning={system_warning}. "
                        "Microphone state changes do not stop Alena's session."
                    )
                    last_mic_observation = observation
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
            await log_meet_microphone_diagnostics(
                page,
                interview_id,
                f"Meet/Alena flow raised {type(error).__name__}: {error}",
            )
            logger.exception(
                "Meet interview execution exception",
                extra={"interview_id": interview_id, "stage": stage},
            )
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
                logger.exception(
                    "Meet browser cleanup exception",
                    extra={"interview_id": interview_id, "stage": "meet_cleanup"},
                )
                print(f"Meet browser cleanup failed: {type(cleanup_error).__name__}")
            finally:
                reset_interview_context(log_context)


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
