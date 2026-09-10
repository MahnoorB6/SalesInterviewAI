import wave
import pyaudio

WAV_FILE = "test_tone.wav"
OUTPUT_DEVICE_INDEX = 50

p = pyaudio.PyAudio()

print("Opening:", WAV_FILE)

wf = wave.open(WAV_FILE, "rb")

print("WAV settings:")
print("  Channels:", wf.getnchannels())
print("  Sample width:", wf.getsampwidth())
print("  Sample rate:", wf.getframerate())

print("\nUsing output device:")
info = p.get_device_info_by_index(OUTPUT_DEVICE_INDEX)
print("  Index:", OUTPUT_DEVICE_INDEX)
print("  Name:", info["name"])
print("  Output channels:", info["maxOutputChannels"])
print("  Default rate:", info["defaultSampleRate"])

stream = p.open(
    format=p.get_format_from_width(wf.getsampwidth()),
    channels=wf.getnchannels(),
    rate=wf.getframerate(),
    output=True,
    output_device_index=OUTPUT_DEVICE_INDEX,
)

print("\nPlaying WAV...")
print("Watch the 'Voicemeeter Input' meter.")
print("You should hear a clean continuous tone.\n")

data = wf.readframes(1024)

while data:
    stream.write(data)
    data = wf.readframes(1024)

stream.stop_stream()
stream.close()
wf.close()
p.terminate()

print("Test finished.")