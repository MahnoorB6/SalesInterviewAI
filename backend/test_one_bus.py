import pyaudio
import math
import struct
import time

DEVICE = 50
RATE = 44100
CHUNK = 1024
SECONDS = 5

p = pyaudio.PyAudio()
info = p.get_device_info_by_index(DEVICE)

print("=" * 55)
print("AUDIO BUS TEST")
print("=" * 55)
print("Device:", DEVICE)
print("Name:", info["name"])
print()
print("IMPORTANT:")
print("1. Wait for ALENA to speak.")
print("2. DO NOT speak while Alena is speaking.")
print("3. When Alena stops, speak normally.")
print()
print("Starting in 3 seconds...")
time.sleep(3)

stream = p.open(
    format=pyaudio.paInt16,
    channels=1,
    rate=RATE,
    input=True,
    input_device_index=DEVICE,
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
p.terminate()

print()
print("Average:", round(sum(levels) / len(levels), 2))
print("Maximum:", round(max(levels), 2))
print()
print("TEST COMPLETE")
