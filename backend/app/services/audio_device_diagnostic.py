"""Offline PyAudio device inventory and supported-format probe; opens no streams."""
import os
from pathlib import Path
from dotenv import load_dotenv
import pyaudiowpatch as pyaudio

BACKEND_DIR=Path(__file__).resolve().parents[2]
PROBES=((16000,1),(44100,2),(48000,2))
def find_device(pa,name,is_input):
    key="maxInputChannels" if is_input else "maxOutputChannels"
    for i in range(pa.get_device_count()):
        x=pa.get_device_info_by_index(i)
        if name.lower().strip() in str(x.get("name","")).lower() and int(x.get(key,0))>0: return i,x
    return None
def query(pa,i,is_input,rate,channels):
    try:
        if is_input: pa.is_format_supported(rate,input_device=i,input_channels=channels,input_format=pyaudio.paInt16)
        else: pa.is_format_supported(rate,output_device=i,output_channels=channels,output_format=pyaudio.paInt16)
        return True,""
    except Exception as e: return False,f"{type(e).__name__}: {e}"
def report(pa,i,name,is_input):
    ok=False; direction="input" if is_input else "output"
    for rate,ch in PROBES:
        yes,error=query(pa,i,is_input,rate,ch)
        print(f"[{'SUPPORTED' if yes else 'UNSUPPORTED'}] {i} {name} {direction}: {rate}Hz {ch}ch int16"+(f" ({error})" if error else ""))
        if (rate,ch)==(48000,2): ok=yes
    return ok
def main():
    load_dotenv(BACKEND_DIR/".env")
    mic=os.getenv("MEET_MIC_DEVICE","CABLE Output (VB-Audio Virtual Cable)")
    cable=os.getenv("ELEVENLABS_AUDIO_OUTPUT_DEVICE","CABLE Input (VB-Audio Virtual Cable)")
    speaker=os.getenv("MEET_SPEAKER_DEVICE","").strip() or os.getenv("ELEVENLABS_AUDIO_LOOPBACK_DEVICE","").strip()
    pa=pyaudio.PyAudio(); ok=True
    try:
        print("Device inventory and format support (no streams opened)")
        print("Index | Host API | Name | Max in | Max out | Default rate")
        for i in range(pa.get_device_count()):
            x=pa.get_device_info_by_index(i)
            try: host=pa.get_host_api_info_by_index(int(x["hostApi"])).get("name","")
            except Exception: host=x.get("hostApi","?")
            ni=int(x.get("maxInputChannels",0)); no=int(x.get("maxOutputChannels",0))
            print(f"{i} | {host} | {x.get('name','')} | {ni} | {no} | {x.get('defaultSampleRate','?')}")
            if ni: report(pa,i,str(x.get("name","")),True)
            if no: report(pa,i,str(x.get("name","")),False)
        wasapi=pa.get_host_api_info_by_type(pyaudio.paWASAPI); host=int(wasapi["index"])
        default=pa.get_device_info_by_index(int(wasapi["defaultOutputDevice"]))
        speaker=speaker or str(default.get("name",""))
        if any(z in speaker.casefold() for z in ("cable","voicemeeter")):
            print(f"[MISMATCH] WASAPI speaker is virtual: {speaker}"); ok=False
        else:
            out=next(((i,x) for i in range(pa.get_device_count()) for x in [pa.get_device_info_by_index(i)]
                      if int(x.get("hostApi",-1))==host and int(x.get("maxOutputChannels",0))>0
                      and speaker.casefold() in str(x.get("name","")).casefold()),None)
            if not out: print(f"[MISMATCH] Physical WASAPI output missing: {speaker}"); ok=False
            else:
                print(f"[MATCH] Meet speaker output: {out[0]} {out[1]['name']}")
                loop=next((x for x in pa.get_loopback_device_info_generator()
                           if str(out[1]["name"]).casefold() in str(x.get("name","")).casefold()),None)
                if not loop: print(f"[MISMATCH] WASAPI loopback missing for {speaker}"); ok=False
                else:
                    print(f"[MATCH] Meet speaker loopback: {loop['index']} {loop['name']}")
                    ok &= report(pa,int(loop["index"]),str(loop["name"]),True)
        for label,target,is_input in (("Meet mic/CABLE Output",mic,True),("Alena output/CABLE Input",cable,False)):
            found=find_device(pa,target,is_input)
            if not found: print(f"[MISMATCH] {label} missing: {target}"); ok=False
            else:
                i,x=found; print(f"[MATCH] {label}: {i} {x['name']}")
                ok &= report(pa,i,str(x["name"]),is_input)
    finally: pa.terminate(); print("PyAudio terminated.")
    return 0 if ok else 1
if __name__=="__main__": raise SystemExit(main())
