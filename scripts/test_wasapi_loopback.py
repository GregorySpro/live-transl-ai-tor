"""
Force la lecture sur le device WASAPI [8] et capture depuis le loopback [10].
"""
import threading
import time
import numpy as np
import pyaudiowpatch as pyaudio

RATE = 48000
CHUNK = 1024
PLAY_DEV = 8   # Haut-parleurs WASAPI
LOOP_DEV = 10  # Loopback WASAPI

t_arr = np.linspace(0, 3.0, int(RATE * 3.0), endpoint=False)
tone = (np.sin(2 * np.pi * 440 * t_arr) * 0.6).astype(np.float32)
tone_stereo = np.stack([tone, tone], axis=1).flatten()  # stéréo interleaved

loopback_levels = []

def play_tone():
    pa = pyaudio.PyAudio()
    stream = pa.open(format=pyaudio.paFloat32, channels=2, rate=RATE,
                     output=True, output_device_index=PLAY_DEV, frames_per_buffer=CHUNK)
    pos = 0
    while pos < len(tone_stereo):
        end = min(pos + CHUNK * 2, len(tone_stereo))
        stream.write(tone_stereo[pos:end].tobytes())
        pos = end
    stream.stop_stream()
    stream.close()
    pa.terminate()

def capture_loop():
    pa = pyaudio.PyAudio()
    stream = pa.open(format=pyaudio.paFloat32, channels=2, rate=RATE,
                     input=True, input_device_index=LOOP_DEV, frames_per_buffer=CHUNK)
    end_t = time.time() + 4.0
    while time.time() < end_t:
        raw = stream.read(CHUNK, exception_on_overflow=False)
        audio = np.frombuffer(raw, dtype=np.float32)
        loopback_levels.append(float(np.abs(audio).mean()))
    stream.stop_stream()
    stream.close()
    pa.terminate()

print(f"Lecture sur device [{PLAY_DEV}] + capture loopback [{LOOP_DEV}]...")
t_cap = threading.Thread(target=capture_loop, daemon=True)
t_play = threading.Thread(target=play_tone, daemon=True)
t_cap.start()
time.sleep(0.2)
t_play.start()
t_play.join()
t_cap.join(timeout=5)

avg = np.mean(loopback_levels) if loopback_levels else 0
peak = np.max(loopback_levels) if loopback_levels else 0
print(f"Résultat : avg={avg:.5f}  peak={peak:.5f}")
if avg > 0.01:
    print("✓ Loopback WASAPI fonctionne parfaitement")
elif avg > 0.0001:
    print("~ Signal faible — le loopback fonctionne mais volume bas")
else:
    print("✗ Toujours rien — problème de configuration Windows ou de pilote")
