import pyaudio
import struct

DEVICE = 24
RATE = 16000
CHUNK = 1024

p = pyaudio.PyAudio()

print("Opening device 24...")
stream = p.open(
    format=pyaudio.paInt16,
    channels=1,
    rate=RATE,
    input=True,
    input_device_index=DEVICE,
    frames_per_buffer=CHUNK
)

print("LISTENING - speak normally for 10 seconds")
print()

for _ in range(int(RATE / CHUNK * 10)):
    data = stream.read(CHUNK, exception_on_overflow=False)
    samples = struct.unpack("<" + "h" * (len(data) // 2), data)
    rms = int((sum(x * x for x in samples) / len(samples)) ** 0.5)
    print(f"\rRMS: {rms:6d}", end="")

stream.stop_stream()
stream.close()
p.terminate()

print("\n\nTEST FINISHED")
