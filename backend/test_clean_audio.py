import pyaudio
import math
import struct

DEVICE = 4
RATE = 44100
CHUNK = 1024
SECONDS = 5

p = pyaudio.PyAudio()
info = p.get_device_info_by_index(DEVICE)

print("=" * 50)
print("CLEAN MICROPHONE TEST")
print("=" * 50)
print("Device:", DEVICE)
print("Name:", info["name"])
print()
print("Speak normally for 5 seconds...")
print()

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
        sum(sample * sample for sample in samples)
        / len(samples)
    )

    levels.append(rms)

stream.stop_stream()
stream.close()
p.terminate()

print("Average:", round(sum(levels) / len(levels), 2))
print("Maximum:", round(max(levels), 2))
print()
print("TEST COMPLETE")