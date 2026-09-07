import pyaudio
import math
import struct
import time

p = pyaudio.PyAudio()

DEVICES = [1, 2, 3, 5, 6, 7, 8, 9, 10, 24, 25, 26, 28, 29, 30, 31, 32, 33, 57, 58, 60, 61, 62, 63, 65, 66, 78, 79, 86, 87, 88, 93, 94, 95]

RATE = 16000
CHANNELS = 1
CHUNK = 1024

def rms(data):
    samples = struct.unpack("<" + "h" * (len(data) // 2), data)
    return math.sqrt(sum(x * x for x in samples) / len(samples))

print("\n==============================================")
print(" SalesInterviewAI - Audio Bus Tester")
print("==============================================")
print()
print("We will test each possible Voicemeeter input.")
print("When a device is being tested, SPEAK normally.")
print("You do NOT need to hear yourself.")
print()

for index in DEVICES:

    try:
        info = p.get_device_info_by_index(index)

        if info["maxInputChannels"] <= 0:
            continue

        print("\n----------------------------------------------")
        print(f"Testing DEVICE {index}")
        print(f"Name: {info['name']}")
        print("----------------------------------------------")
        print("Speak normally for 3 seconds...")

        stream = p.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            input_device_index=index,
            frames_per_buffer=CHUNK,
        )

        levels = []

        start = time.time()

        while time.time() - start < 3:
            data = stream.read(CHUNK, exception_on_overflow=False)
            levels.append(rms(data))

        stream.stop_stream()
        stream.close()

        average = sum(levels) / len(levels)
        maximum = max(levels)

        print(f"Average level: {average:.2f}")
        print(f"Maximum level: {maximum:.2f}")

        if maximum > 500:
            print(">>> VOICE DETECTED <<<")
        else:
            print("No significant audio detected.")

    except Exception as e:
        print(f"ERROR: {e}")

p.terminate()

print("\n==============================================")
print("TEST COMPLETE")
print("==============================================")