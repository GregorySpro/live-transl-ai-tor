"""
Test complet : joue un son via sounddevice (WASAPI) + capture loopback simultanément.
Si le loopback fonctionne, on doit voir un signal non-nul pendant la lecture.
"""
import threading
import time
import numpy as np
import sounddevice as sd
import pyaudiowpatch as pyaudio

RATE = 48000
DURATION = 3.0

# Génère un bip 440Hz
t = np.linspace(0, DURATION, int(RATE * DURATION), endpoint=False)
tone = (np.sin(2 * np.pi * 440 * t) * 0.5).astype(np.float32)

loopback_levels = []

def capture_loopback():
    pa = pyaudio.PyAudio()
    for dev in pa.get_loopback_device_info_generator():
        idx = dev["index"]
        n_ch = int(dev.get("maxInputChannels", 2)) or 2
        rate = int(dev.get("defaultSampleRate", 48000))
        print(f"Capture loopback [{idx}] {dev['name']} @ {rate}Hz")
        stream = pa.open(format=pyaudio.paFloat32, channels=n_ch, rate=rate,
                         input=True, input_device_index=idx, frames_per_buffer=1024)
        end = time.time() + DURATION + 0.5
        while time.time() < end:
            raw = stream.read(1024, exception_on_overflow=False)
            audio = np.frombuffer(raw, dtype=np.float32)
            loopback_levels.append(float(np.abs(audio).mean()))
        stream.stop_stream()
        stream.close()
        break
    pa.terminate()

# Lance la capture en parallèle
t_cap = threading.Thread(target=capture_loopback, daemon=True)
t_cap.start()
time.sleep(0.2)

# Joue le bip via sounddevice (WASAPI shared mode)
print(f"Lecture d'un bip 440Hz pendant {DURATION}s...")
sd.play(tone, samplerate=RATE, blocking=True)

t_cap.join(timeout=5)

avg = np.mean(loopback_levels) if loopback_levels else 0
peak = np.max(loopback_levels) if loopback_levels else 0
print(f"\nRésultat loopback : avg={avg:.5f}  peak={peak:.5f}")
if avg > 0.001:
    print("✓ Le loopback FONCTIONNE — il capte le son de sortie")
elif avg > 0.00005:
    print("~ Signal très faible détecté — peut-être le bon device mais volume bas")
else:
    print("✗ Loopback silencieux — l'audio de sortie passe par un autre device")
    print("  → Vérifie le device de lecture par défaut dans les paramètres son Windows")
