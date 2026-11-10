"""Read-only preflight for the configured Google Meet microphone endpoint.

This utility enumerates WASAPI input devices and reads existing backend logs.
It does not open audio streams or start Chrome, Meet, or ElevenLabs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
import pyaudiowpatch as pyaudio


BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_MICROPHONE = "CABLE Output (VB-Audio Virtual Cable)"
DEFAULT_LOG = BACKEND_DIR / "logs" / "interviews.log"


def match_device_name(requested: str, available_names: list[str]) -> str | None:
    """Return an exact case-insensitive device-name match, if one exists."""
    normalized = requested.strip().casefold()
    if not normalized:
        return None
    return next(
        (name for name in available_names if name.strip().casefold() == normalized),
        None,
    )


def _wasapi_input_names(audio) -> list[str]:
    wasapi_index = int(audio.get_host_api_info_by_type(pyaudio.paWASAPI)["index"])
    names = []
    for index in range(audio.get_device_count()):
        info = audio.get_device_info_by_index(index)
        if (
            int(info.get("hostApi", -1)) == wasapi_index
            and int(info.get("maxInputChannels", 0)) > 0
            and "[loopback]" not in str(info.get("name", "")).casefold()
        ):
            names.append(str(info.get("name", "")))
    return names


def _runtime_evidence(log_path: Path) -> dict[str, str | None]:
    """Summarize the latest logged permission, track, and system-mute evidence."""
    result: dict[str, str | None] = {
        "permission": None,
        "permission_context": None,
        "active_track": None,
        "active_track_verification": None,
        "system_mute_warning": None,
    }
    if not log_path.is_file():
        return result

    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return result

    entry_prefix = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)[,.]\d+ .*?interview_id=([^ ]+)")
    permission_re = re.compile(r"\bpermission=(granted|denied|prompt|unavailable)\b", re.I)
    track_re = re.compile(r"Active microphone track:\s*(.*?)\s+verification=(deviceId|track label|unavailable)", re.I)

    for line in lines:
        prefix = entry_prefix.search(line)
        if not prefix or not prefix.group(2).isdigit():
            # Ignore uncorrelated unit-test/manual diagnostics (interview_id=-).
            continue
        context = f"{prefix.group(1)} interview_id={prefix.group(2)}"
        if "Meet microphone/session diagnostics" in line:
            payload = line.partition("Meet microphone/session diagnostics ")[2]
            try:
                details = json.loads(payload)
            except (TypeError, json.JSONDecodeError):
                details = {}
            permission = details.get("microphone_permission")
            if permission in {"granted", "denied", "prompt", "unavailable"}:
                result["permission"] = permission
                result["permission_context"] = context

        if "Meet browser console audio message" in line:
            permission_match = permission_re.search(line)
            if permission_match:
                result["permission"] = permission_match.group(1).casefold()
                result["permission_context"] = context
            track_match = track_re.search(line)
            if track_match:
                result["active_track"] = track_match.group(1).strip()
                result["active_track_verification"] = track_match.group(2)

        if "system_mic_warning_detected=True" in line:
            result["system_mute_warning"] = f"present ({context})"
        elif "system_mic_warning_detected=False" in line:
            result["system_mute_warning"] = f"not reported ({context})"

    return result


def _report_runtime_evidence(evidence: dict[str, str | None], target: str) -> None:
    permission = evidence["permission"]
    if permission:
        print(
            f"[LAST RUNTIME PERMISSION] {permission} ({evidence['permission_context']}); "
            "historical evidence only, not a current browser check."
        )
    else:
        print(
            "[UNVERIFIED] No logged Chrome/Meet microphone permission state; "
            "it cannot be checked offline."
        )

    track = evidence["active_track"]
    verification = evidence["active_track_verification"]
    if track and verification:
        if track.casefold() == target.strip().casefold() and verification.casefold() in {
            "deviceid",
            "track label",
        }:
            print(
                f"[LAST RUNTIME TRACK] Exact configured device observed: {track} "
                f"(verified by {verification}); historical evidence only."
            )
        else:
            print(
                f"[LAST RUNTIME TRACK] {track} (verification={verification}); "
                f"does not prove current selection of {target!r}."
            )
    else:
        print(
            "[UNVERIFIED] No logged active microphone track; device selection "
            "cannot be checked offline."
        )

    warning = evidence["system_mute_warning"]
    print(
        f"[LAST RUNTIME SYSTEM-MUTE EVIDENCE] {warning}"
        if warning
        else "[UNVERIFIED] No logged Meet system-microphone warning state."
    )
    print("[AUDIO CAPTURE] NOT TESTED; this preflight opens no audio streams.")


def main(argv: list[str] | None = None) -> int:
    load_dotenv(BACKEND_DIR / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--device",
        default=os.getenv("MEET_MIC_DEVICE", DEFAULT_MICROPHONE),
        help="Configured Meet microphone name (defaults to MEET_MIC_DEVICE).",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=DEFAULT_LOG,
        help="Existing backend log to inspect for runtime permission evidence.",
    )
    args = parser.parse_args(argv)

    audio = None
    try:
        audio = pyaudio.PyAudio()
        available = _wasapi_input_names(audio)
    except Exception as error:
        print(f"[PREFLIGHT ERROR] Could not enumerate WASAPI inputs: {type(error).__name__}: {error}")
        return 2
    finally:
        if audio is not None:
            audio.terminate()

    print(f"Configured Meet microphone: {args.device}")
    match = match_device_name(args.device, available)
    if match:
        print(f"[AVAILABLE] Exact WASAPI input match: {match}")
    else:
        print("[UNAVAILABLE] No exact WASAPI input-name match.")
    print("WASAPI input endpoints:")
    for name in available:
        print(f"  - {name}")

    _report_runtime_evidence(_runtime_evidence(args.log), args.device)
    return 0 if match else 1


if __name__ == "__main__":
    raise SystemExit(main())
