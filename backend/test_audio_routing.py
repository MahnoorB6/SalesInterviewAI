import pyaudio
import numpy as np
import time


DEVICE_NAME = "CABLE Output (VB-Audio Virtual Cable)"
SAMPLE_RATE = 44100
CHANNELS = 2
CHUNK = 2048


audio = pyaudio.PyAudio()

print("=" * 70)
print("SalesInterviewAI - ZERO CREDIT AUDIO TEST")
print("=" * 70)

device_index = None

for i in range(audio.get_device_count()):
    try:
        info = audio.get_device_info_by_index(i)

        if DEVICE_NAME.lower() in info["name"].lower():
            if info["maxInputChannels"] >= 2:
                device_index = i

                print(f"[FOUND] Device index: {i}")
                print(f"[FOUND] Name: {info['name']}")
                print(
                    f"[FOUND] Inputs: "
                    f"{info['maxInputChannels']}"
                )
                print(
                    f"[FOUND] Rate: "
                    f"{info['defaultSampleRate']}"
                )

                break

    except Exception:
        pass


if device_index is None:

    print()
    print("[ERROR] CABLE Output was not found.")
    audio.terminate()
    raise SystemExit


print()
print("=" * 70)
print("IMPORTANT")
print("=" * 70)
print()
print("Google Meet:")
print("  Microphone -> Voicemeeter Out B1")
print("  Speaker    -> CABLE Input")
print()
print("Now have the candidate speak in Google Meet.")
print()
print("Testing for 30 seconds...")
print("=" * 70)


stream = audio.open(
    format=pyaudio.paInt16,
    channels=CHANNELS,
    rate=SAMPLE_RATE,
    input=True,
    input_device_index=device_index,
    frames_per_buffer=CHUNK,
)


start = time.time()
detected = False
max_rms = 0
max_peak = 0


try:

    while time.time() - start < 30:

        data = stream.read(
            CHUNK,
            exception_on_overflow=False
        )

        samples = np.frombuffer(
            data,
            dtype=np.int16
        )

        if len(samples) == 0:
            continue

        rms = float(
            np.sqrt(
                np.mean(
                    samples.astype(
                        np.float32
                    ) ** 2
                )
            )
        )

        peak = int(
            np.max(
                np.abs(samples)
            )
        )

        max_rms = max(
            max_rms,
            rms
        )

        max_peak = max(
            max_peak,
            peak
        )

        if rms > 100 or peak > 300:

            if not detected:

                print()
                print("=" * 70)
                print("✓ CANDIDATE AUDIO DETECTED")
                print("=" * 70)

                detected = True

            print(
                f"RMS={rms:.0f}  "
                f"PEAK={peak}"
            )


finally:

    stream.stop_stream()
    stream.close()
    audio.terminate()


print()
print("=" * 70)
print("TEST FINISHED")
print("=" * 70)

print(
    f"Maximum RMS : {max_rms:.0f}"
)

print(
    f"Maximum Peak: {max_peak}"
)

print()


if detected:

    print("✓ SUCCESS")
    print()
    print(
        "Candidate audio is reaching Python."
    )
    print(
        "We can now connect this path to Alena."
    )

else:

    print("✗ NO AUDIO")
    print()
    print(
        "Python is still receiving silence "
        "from CABLE Output."
    )

print("=" * 70)
