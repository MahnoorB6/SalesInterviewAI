"""Local Windows audio signal checks; never connects to Meet or ElevenLabs."""

from __future__ import annotations

import argparse
import os
import threading
import time
from pathlib import Path

from dotenv import load_dotenv
import numpy as np
import pyaudiowpatch as pyaudio


BACKEND_DIR = Path(__file__).resolve().parents[2]
RATE = 48_000
CHANNELS = 2
FRAMES = 1024
REPORT_SECONDS = 1.0
TONE_FREQUENCY = 440
TONE_PEAK = 1800  # Low digital level; output is opened only on CABLE Input.
CAPTURE_TAIL_SECONDS = 2.0
BUFFER_TOLERANCE_SECONDS = 0.5
TONE_DETECTION_RMS = 50.0


def _host_index(audio) -> int:
    try:
        return int(audio.get_host_api_info_by_type(pyaudio.paWASAPI)["index"])
    except Exception as error:
        raise RuntimeError("Windows WASAPI is unavailable.") from error


def _name_matches(name: str, requested: str) -> bool:
    return requested.casefold().strip() in name.casefold().strip()


def _resolve_wasapi_device(audio, requested: str, *, input_device: bool):
    """Resolve a uniquely matching WASAPI endpoint, preferring an exact name."""
    host = _host_index(audio)
    channel_field = "maxInputChannels" if input_device else "maxOutputChannels"
    matches = []
    for index in range(audio.get_device_count()):
        info = audio.get_device_info_by_index(index)
        name = str(info.get("name", ""))
        if (
            int(info.get("hostApi", -1)) == host
            and int(info.get(channel_field, 0)) > 0
            and _name_matches(name, requested)
        ):
            matches.append((index, name, info))

    exact = [
        item for item in matches
        if item[1].casefold().strip() == requested.casefold().strip()
    ]
    candidates = exact or matches
    if len(candidates) != 1:
        direction = "input" if input_device else "output"
        found = [f"{name} (index {index})" for index, name, _ in candidates]
        raise RuntimeError(
            f"Expected one WASAPI {direction} matching {requested!r}; "
            f"found {len(candidates)}: {found}"
        )
    return candidates[0]


def _resolve_physical_speaker(audio) -> tuple[str, int, str]:
    requested = (
        os.getenv("MEET_SPEAKER_DEVICE", "").strip()
        or os.getenv("ELEVENLABS_AUDIO_LOOPBACK_DEVICE", "").strip()
    )
    host = _host_index(audio)
    if requested:
        output_index, speaker_name, _ = _resolve_wasapi_device(
            audio, requested, input_device=False
        )
    else:
        wasapi = audio.get_host_api_info_by_type(pyaudio.paWASAPI)
        output_index = int(wasapi["defaultOutputDevice"])
        info = audio.get_device_info_by_index(output_index)
        if int(info.get("hostApi", -1)) != host or int(info.get("maxOutputChannels", 0)) <= 0:
            raise RuntimeError("The default WASAPI output is not a usable output device.")
        speaker_name = str(info.get("name", ""))

    if not speaker_name or any(
        token in speaker_name.casefold() for token in ("cable", "voicemeeter")
    ):
        raise RuntimeError(f"Configured speaker is not a physical output: {speaker_name!r}")

    normalized = speaker_name.casefold().replace("[loopback]", "").strip()
    loopbacks = []
    for info in audio.get_loopback_device_info_generator():
        name = str(info.get("name", ""))
        candidate = name.casefold().replace("[loopback]", "").strip()
        if (
            int(info.get("hostApi", -1)) == host
            and int(info.get("maxInputChannels", 0)) > 0
        ):
            if candidate == normalized:
                loopbacks.append((int(info["index"]), name))
    if len(loopbacks) != 1:
        raise RuntimeError(
            f"Expected one WASAPI loopback for {speaker_name!r}; "
            f"found {[name for _, name in loopbacks]}"
        )
    loop_index, loop_name = loopbacks[0]
    return speaker_name, loop_index, loop_name


def _measure(samples: np.ndarray) -> tuple[float, int]:
    values = samples.astype(np.float64, copy=False)
    rms = float(np.sqrt(np.mean(values * values))) if values.size else 0.0
    peak = int(np.max(np.abs(values))) if values.size else 0
    return rms, peak


def _tone_rms(samples: np.ndarray, start_frame: int) -> float:
    """Estimate the RMS component at the generated tone frequency."""
    values = samples.astype(np.float64, copy=False)
    if values.size < CHANNELS:
        return 0.0
    mono = values.reshape(-1, CHANNELS).mean(axis=1)
    frames = start_frame + np.arange(mono.size)
    phase = 2.0 * np.pi * TONE_FREQUENCY * frames / RATE
    cosine = np.cos(phase)
    sine = np.sin(phase)
    amplitude = 2.0 * np.hypot(np.dot(mono, cosine), np.dot(mono, sine)) / mono.size
    return float(amplitude / np.sqrt(2.0))


def _label_signal(rms: float, peak: int) -> str:
    # Only exact digital zero is labelled silence; no universal audibility
    # threshold is assumed. Compare levels during stimulus and baseline.
    return "ZERO SAMPLES" if rms == 0.0 and peak == 0 else "NON-ZERO SAMPLES"


def _capture_phase(start: float, end: float, tone_start: float, tone_end: float) -> str:
    """Label capture-time windows with slack for device/stream buffering."""
    earliest_tone = max(0.0, tone_start - BUFFER_TOLERANCE_SECONDS)
    latest_tone = tone_end + BUFFER_TOLERANCE_SECONDS
    if end <= earliest_tone:
        return "BASELINE"
    if start >= latest_tone:
        return "POST-TONE TAIL"
    return "TONE / BUFFER WINDOW"


def _close_stream(stream, label: str) -> None:
    if stream is None:
        return
    try:
        stream.stop_stream()
    except Exception as error:
        print(f"[CLEANUP] {label} stop: {type(error).__name__}: {error}")
    try:
        stream.close()
    except Exception as error:
        print(f"[CLEANUP] {label} close: {type(error).__name__}: {error}")


def run_loopback_meter() -> None:
    audio = None
    stream = None
    try:
        audio = pyaudio.PyAudio()
        speaker, index, loop_name = _resolve_physical_speaker(audio)
        print(f"[DEVICE] Physical speaker: {speaker}")
        print(f"[DEVICE] WASAPI loopback: {loop_name} (resolved dynamically)")
        stream = audio.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            input_device_index=index,
            frames_per_buffer=FRAMES,
        )
        print(f"[STREAM OPEN] Loopback capture running at {RATE} Hz, {CHANNELS} channels.")
        print("Play a local test sound through the selected physical speaker. Press Ctrl+C to stop.")
        batch = []
        samples_in_batch = 0
        target_samples = int(RATE * REPORT_SECONDS)
        while True:
            raw = stream.read(FRAMES, exception_on_overflow=False)
            samples = np.frombuffer(raw, dtype=np.int16)
            if samples.size:
                batch.append(samples)
                samples_in_batch += samples.size
            if samples_in_batch >= target_samples * CHANNELS:
                rms, peak = _measure(np.concatenate(batch))
                print(f"[LOOPBACK] rms={rms:.1f} peak={peak} | {_label_signal(rms, peak)}")
                batch = []
                samples_in_batch = 0
    finally:
        _close_stream(stream, "Loopback stream")
        try:
            if audio is not None:
                audio.terminate()
        finally:
            print("[CLEANUP] Audio resources released.")


def _capture_cable_input(
    stream,
    stop_event: threading.Event,
    errors: list[Exception],
    capture_started: threading.Event,
) -> None:
    started = time.monotonic()
    capture_started.set()
    bucket = []
    sample_count = 0
    window_samples = RATE * CHANNELS
    try:
        while not stop_event.is_set():
            raw = stream.read(FRAMES, exception_on_overflow=False)
            data = np.frombuffer(raw, dtype=np.int16)
            if data.size:
                bucket.append(data)
                sample_count += data.size
            if sample_count >= window_samples:
                elapsed = time.monotonic() - started
                window_end = elapsed
                window_start = max(0.0, window_end - sample_count / (RATE * CHANNELS))
                captured = np.concatenate(bucket)
                rms, peak = _measure(captured)
                phase = _capture_phase(window_start, window_end, 1.0, 4.0)
                tone_rms = _tone_rms(
                    captured,
                    int(round(window_start * RATE)),
                )
                tone_detected = tone_rms >= TONE_DETECTION_RMS
                print(
                    f"[CABLE CAPTURE {phase}] "
                    f"window={window_start:.1f}-{window_end:.1f}s "
                    f"rms={rms:.1f} peak={peak} "
                    f"tone_{TONE_FREQUENCY}hz_rms={tone_rms:.1f} "
                    f"tone_detected={tone_detected} | {_label_signal(rms, peak)}"
                )
                bucket = []
                sample_count = 0
    except Exception as error:
        if not stop_event.is_set():
            errors.append(error)
            stop_event.set()


def run_cable_roundtrip() -> None:
    playback_name = "CABLE Input (VB-Audio Virtual Cable)"
    recording_name = "CABLE Output (VB-Audio Virtual Cable)"
    audio = None
    capture = playback = None
    stop_event = threading.Event()
    capture_errors: list[Exception] = []
    capture_thread = None
    capture_started = threading.Event()
    try:
        audio = pyaudio.PyAudio()
        capture_index, capture_name, _ = _resolve_wasapi_device(
            audio, recording_name, input_device=True
        )
        playback_index, actual_playback_name, _ = _resolve_wasapi_device(
            audio, playback_name, input_device=False
        )
        if (
            "vb-audio virtual cable" not in capture_name.casefold()
            or "vb-audio virtual cable" not in actual_playback_name.casefold()
        ):
            raise RuntimeError("Resolved endpoints are not both VB-Audio Virtual Cable devices.")

        print(f"[DEVICE] Cable recording endpoint: {capture_name}")
        print(f"[DEVICE] Cable playback endpoint: {actual_playback_name}")
        try:
            capture = audio.open(
                format=pyaudio.paInt16,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                input_device_index=capture_index,
                frames_per_buffer=FRAMES,
            )
        except Exception as error:
            raise RuntimeError(
                f"Could not open 48 kHz stereo capture endpoint "
                f"{capture_name!r}: {type(error).__name__}: {error}"
            ) from error
        try:
            playback = audio.open(
                format=pyaudio.paInt16,
                channels=CHANNELS,
                rate=RATE,
                output=True,
                output_device_index=playback_index,
                frames_per_buffer=FRAMES,
            )
        except Exception as error:
            raise RuntimeError(
                f"Could not open 48 kHz stereo playback endpoint "
                f"{actual_playback_name!r}: {type(error).__name__}: {error}"
            ) from error
        print(f"[STREAM OPEN] Capture and playback at {RATE} Hz, {CHANNELS} channels.")
        print("A low-level 440 Hz test tone will be sent only to CABLE Input for 3 seconds.")
        print("No microphone is opened; no captured audio is saved.")

        capture_thread = threading.Thread(
            target=_capture_cable_input,
            args=(capture, stop_event, capture_errors, capture_started),
            name="local-cable-capture",
            daemon=True,
        )
        capture_thread.start()
        if not capture_started.wait(timeout=2.0):
            raise RuntimeError("Cable capture worker did not start.")

        total_seconds = 5
        tone_start, tone_end = 1, 4
        frames_written = 0
        total_frames = RATE * total_seconds
        while frames_written < total_frames and not stop_event.is_set():
            count = min(FRAMES, total_frames - frames_written)
            frame_times = (frames_written + np.arange(count)) / RATE
            active = (frame_times >= tone_start) & (frame_times < tone_end)
            mono = np.zeros(count, dtype=np.int16)
            if np.any(active):
                tone_phase = 2.0 * np.pi * TONE_FREQUENCY * frame_times[active]
                mono[active] = np.round(TONE_PEAK * np.sin(tone_phase)).astype(np.int16)
            stereo = np.column_stack((mono, mono))
            playback.write(stereo.tobytes())
            frames_written += count

        # WASAPI and the virtual cable can buffer playback/capture. Keep
        # collecting after playback ends so delayed tail samples are reported.
        if not stop_event.is_set():
            time.sleep(CAPTURE_TAIL_SECONDS)
    finally:
        stop_event.set()
        _close_stream(playback, "Cable playback stream")
        _close_stream(capture, "Cable capture stream")
        if capture_thread is not None:
            capture_thread.join(timeout=3.0)
            if capture_thread.is_alive():
                print("[CLEANUP] Cable capture worker did not stop within 3 seconds.")
        if audio is not None:
            try:
                audio.terminate()
            finally:
                print("[CLEANUP] Audio resources released.")
        for error in capture_errors:
            print(f"[CAPTURE ERROR] {type(error).__name__}: {error}")
    if capture_errors:
        error = capture_errors[0]
        raise RuntimeError(
            f"Cable capture worker failed: {type(error).__name__}: {error}"
        ) from error


def main() -> int:
    try:
        load_dotenv(BACKEND_DIR / ".env")
        parser = argparse.ArgumentParser(
            description="Local audio signal checks; no Meet or ElevenLabs connection."
        )
        parser.add_argument(
            "mode",
            choices=("speaker-loopback", "cable-roundtrip"),
            help="Select one independent local audio test.",
        )
        args = parser.parse_args()
        if args.mode == "speaker-loopback":
            run_loopback_meter()
        else:
            run_cable_roundtrip()
    except KeyboardInterrupt:
        print("\n[STOP] Diagnostic stopped by user.")
        return 130
    except Exception as error:
        print(f"[DIAGNOSTIC ERROR] {type(error).__name__}: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
