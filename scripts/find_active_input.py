"""Teste TOUS les devices d'entrée pour trouver lequel reçoit l'audio système."""
import time
import numpy as np
import pyaudiowpatch as pyaudio

pa = pyaudio.PyAudio()

results = []
for i in range(pa.get_device_count()):
    d = pa.get_device_info_by_index(i)
    if d.get("maxInputChannels", 0) == 0:
        continue
    n_ch = min(int(d["maxInputChannels"]), 2)
    rate = int(d["defaultSampleRate"])
    name = d["name"][:60]
    try:
        stream = pa.open(
            format=pyaudio.paFloat32,
            channels=n_ch,
            rate=rate,
            input=True,
            input_device_index=i,
            frames_per_buffer=1024,
        )
        levels = []
        for _ in range(15):
            raw = stream.read(1024, exception_on_overflow=False)
            audio = np.frombuffer(raw, dtype=np.float32)
            levels.append(float(np.abs(audio).mean()))
            time.sleep(0.05)
        stream.stop_stream()
        stream.close()
        avg = np.mean(levels)
        peak = np.max(levels)
        results.append((i, name, avg, peak, rate, n_ch))
    except Exception as e:
        results.append((i, name, -1, -1, rate, n_ch))

pa.terminate()

print("idx  avg       peak      rate   ch  name")
print("-" * 80)
for idx, name, avg, peak, rate, n_ch in sorted(results, key=lambda x: -x[2]):
    bar = "#" * int(avg * 300) if avg > 0 else ""
    flag = " <-- SIGNAL" if avg > 0.0001 else ""
    print(f"[{idx:2d}] {avg:.5f}  {peak:.5f}  {rate:6d}  {n_ch}  {name}{flag}")
