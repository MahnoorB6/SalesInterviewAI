import pyaudio
import math
import struct
import time

DEVICES = [78, 86, 93, 94, 95, 87, 88]

RATE = 44100
CHUNK = 1024
SECONDS = 5

p = pyaudio.PyAudio()

print("=" * 70)
print("VOICEMEETER BUS SCAN")
print("=" * 70)
print()
print("Stay COMPLETELY SILENT.")
print("Let ALENA speak during the 5-second test.")
print()

for device in DEVICES:
    info = p.get_device_info_by_index(device)

    print(f"\nTesting Device {device}: {info['name']}")

    try:
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=RATE,
            input=True,
            input_device_index=device,
            frames_per_buffer=CHUNK,
        )

        levels = []

        for _ in range(int(RATE / CHUNK * SECONDS)):
            data = stream.read(CHUNK, exception_on_overflow=False)

            samples = struct.unpack(
                "<" + "h" * (len(data) // 2),
                data
            )

            rms = math.sqrt(
                sum(x * x for x in samples) / len(samples)
            )

            levels.append(rms)

        stream.stop_stream()
        stream.close()

        print("  Average:", round(sum(levels) / len(levels), 2))
        print("  Maximum:", round(max(levels), 2))

    except Exception as e:
        print("  ERROR:", e)

p.terminate()

print()
print("=" * 70)
print("SCAN COMPLETE")
print("=" * 70)