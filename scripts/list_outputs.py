"""Liste tous les devices de sortie ET teste le niveau de chaque loopback."""
import time
import numpy as np
import pyaudiowpatch as pyaudio

pa = pyaudio.PyAudio()

print("=== Tous les devices de sortie ===")
for i in range(pa.get_device_count()):
    d = pa.get_device_info_by_index(i)
    if d.get("maxOutputChannels", 0) > 0:
        name = d["name"][:70]
        print(f"  [{i}] {name}  out={d['maxOutputChannels']} rate={d['defaultSampleRate']}")

print()
print("=== Niveau de chaque loopback (2 sec) ===")
for dev in pa.get_loopback_device_info_generator():
    idx = dev["index"]
    n_ch = int(dev.get("maxInputChannels", 2)) or 2
    rate = int(dev.get("defaultSampleRate", 48000))
    name = dev["name"][:60]
    try:
        stream = pa.open(
            format=pyaudio.paFloat32,
            channels=n_ch,
            rate=rate,
            input=True,
            input_device_index=idx,
            frames_per_buffer=1024,
        )
        levels = []
        for _ in range(20):
            raw = stream.read(1024, exception_on_overflow=False)
            audio = np.frombuffer(raw, dtype=np.float32)
            levels.append(np.abs(audio).mean())
            time.sleep(0.05)
        stream.stop_stream()
        stream.close()
        avg = np.mean(levels)
        peak = np.max(levels)
        print(f"  [{idx}] {name}  avg={avg:.5f}  peak={peak:.5f}")
    except Exception as e:
        print(f"  [{idx}] {name}  ERREUR: {e}")

pa.terminate()
