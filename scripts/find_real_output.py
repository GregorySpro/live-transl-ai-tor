"""Trouve le device de sortie réellement actif en jouant un bip et testant tous les loopbacks."""
import threading
import time
import numpy as np
import sounddevice as sd
import pyaudiowpatch as pyaudio

RATE = 48000
DURATION = 2.0

t_arr = np.linspace(0, DURATION, int(RATE * DURATION), endpoint=False)
tone = (np.sin(2 * np.pi * 440 * t_arr) * 0.7).astype(np.float32)

# Affiche le device par défaut de sounddevice
print("=== sounddevice default output ===")
print(sd.query_devices(kind="output"))

pa = pyaudio.PyAudio()

print("\n=== Test de tous les devices d'entrée pendant la lecture ===")
all_devs = []
for i in range(pa.get_device_count()):
    d = pa.get_device_info_by_index(i)
    if d.get("maxInputChannels", 0) > 0:
        all_devs.append((i, d))

pa.terminate()

def measure_device(idx, dev_info, results, tone_arr):
    pa2 = pyaudio.PyAudio()
    n_ch = min(int(dev_info.get("maxInputChannels", 2)), 2)
    rate = int(dev_info.get("defaultSampleRate", 44100))
    levels = []
    try:
        stream = pa2.open(format=pyaudio.paFloat32, channels=n_ch, rate=rate,
                          input=True, input_device_index=idx, frames_per_buffer=1024)
        end = time.time() + DURATION + 0.5
        while time.time() < end:
            raw = stream.read(1024, exception_on_overflow=False)
            audio = np.frombuffer(raw, dtype=np.float32)
            levels.append(float(np.abs(audio).mean()))
        stream.stop_stream()
        stream.close()
    except Exception:
        pass
    finally:
        pa2.terminate()
    results[idx] = (np.mean(levels) if levels else 0, np.max(levels) if levels else 0)

results = {}
threads = []
for idx, dev in all_devs:
    th = threading.Thread(target=measure_device, args=(idx, dev, results, tone), daemon=True)
    threads.append(th)
    th.start()

time.sleep(0.3)
print("Lecture du bip...")
sd.play(tone, samplerate=RATE, blocking=True)

for th in threads:
    th.join(timeout=5)

print("\nidx  avg       peak      name")
print("-" * 80)
for idx, dev in sorted(all_devs, key=lambda x: -results.get(x[0], (0,0))[0]):
    avg, peak = results.get(idx, (0, 0))
    name = dev["name"][:60]
    flag = " <-- SIGNAL !" if avg > 0.001 else (" ~ bruit" if avg > 0.00005 else "")
    print(f"[{idx:2d}] {avg:.5f}  {peak:.5f}  {name}{flag}")
