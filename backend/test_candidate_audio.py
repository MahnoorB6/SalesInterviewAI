import time
import pyaudio

DEVICE = 64
RATE = 48000
CHANNELS = 2
CHUNK = 2048

p = pyaudio.PyAudio()

print("Opening CABLE Output...")
stream = p.open(
    format=pyaudio.paInt16,
    channels=CHANNELS,
    rate=RATE,
    input=True,
    input_device_index=DEVICE,
    frames_per_buffer=CHUNK
)

print()
print("========================================")
print(" RECORDING FOR 10 SECONDS")
print(" SPEAK INTO THE GOOGLE MEET MIC NOW")
print("========================================")

for seconds_left in range(10, 0, -1):
    print(f"Recording... {seconds_left} seconds remaining")
    time.sleep(1)

stream.stop_stream()
stream.close()
p.terminate()

print()
print("========================================")
print(" RECORDING TEST FINISHED")
print("========================================")