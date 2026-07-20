"""Diagnostic : mesure le niveau audio du loopback en temps réel."""
import time
import numpy as np
import pyaudiowpatch as pyaudio

pa = pyaudio.PyAudio()

print("Périphériques loopback disponibles :")
loopback = None
for dev in pa.get_loopback_device_info_generator():
    print(f"  [{dev['index']}] {dev['name']}  {int(dev['defaultSampleRate'])}Hz  {dev['maxInputChannels']}ch")
    if loopback is None:
        loopback = dev

if loopback is None:
    print("ERREUR : aucun device loopback trouvé")
    pa.terminate()
    exit(1)

idx = loopback["index"]
rate = int(loopback["defaultSampleRate"])
n_ch = int(loopback["maxInputChannels"]) or 2

print(f"\nCapture sur device {idx} @ {rate}Hz {n_ch}ch — écoute 8 secondes...")
stream = pa.open(
    format=pyaudio.paFloat32,
    channels=n_ch,
    rate=rate,
    input=True,
    input_device_index=idx,
    frames_per_buffer=1024,
)

for i in range(80):  # ~8 secondes
    raw = stream.read(1024, exception_on_overflow=False)
    audio = np.frombuffer(raw, dtype=np.float32)
    level = np.abs(audio).mean()
    bar = "#" * int(level * 500)
    print(f"[{i:02d}] level={level:.5f}  {bar}")
    time.sleep(0.1)

stream.stop_stream()
stream.close()
pa.terminate()
print("Diagnostic terminé.")
