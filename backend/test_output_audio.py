import pyaudio
import numpy as np
import time

OUTPUT_DEVICE_INDEX = 50

SAMPLE_RATE = 48000
CHANNELS = 2
DURATION = 10
FREQUENCY = 440
CHUNK = 1024

p = pyaudio.PyAudio()

info = p.get_device_info_by_index(OUTPUT_DEVICE_INDEX)

print("Using device:")
print(f"  Index: {OUTPUT_DEVICE_INDEX}")
print(f"  Name: {info['name']}")
print(f"  Input channels: {info['maxInputChannels']}")
print(f"  Output channels: {info['maxOutputChannels']}")
print(f"  Default rate: {info['defaultSampleRate']}")

stream = p.open(
    format=pyaudio.paInt16,
    channels=CHANNELS,
    rate=SAMPLE_RATE,
    output=True,
    output_device_index=OUTPUT_DEVICE_INDEX,
    frames_per_buffer=CHUNK
)

print()
print("Playing clean 440 Hz tone for 10 seconds...")
print("Watch the Voicemeeter Input meter.")
print()

t = np.arange(int(SAMPLE_RATE * DURATION)) / SAMPLE_RATE

tone = (
    12000 * np.sin(2 * np.pi * FREQUENCY * t)
).astype(np.int16)

stereo = np.column_stack((tone, tone))

for start in range(0, len(stereo), CHUNK):
    chunk = stereo[start:start + CHUNK]

    if len(chunk) < CHUNK:
        chunk = np.pad(
            chunk,
            ((0, CHUNK - len(chunk)), (0, 0))
        )

    stream.write(chunk.tobytes())

stream.stop_stream()
stream.close()
p.terminate()

print()
print("Test finished.")