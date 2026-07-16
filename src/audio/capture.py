"""
Capture audio système (WASAPI loopback) + microphone.
"""
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional, Callable

import numpy as np
import pyaudiowpatch as pyaudio

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_FRAMES = 1024
PRE_GAIN_LOOPBACK = 8.0
PRE_GAIN_MIC = 20.0
# Log du niveau audio toutes les N secondes pour diagnostic
_LEVEL_LOG_INTERVAL = 3.0


@dataclass
class AudioChunk:
    data: np.ndarray      # float32, mono, 16kHz
    source: str           # "system" | "mic"


def list_devices() -> dict:
    pa = pyaudio.PyAudio()
    result = {"loopback": [], "mic": []}
    try:
        for i in range(pa.get_device_count()):
            dev = pa.get_device_info_by_index(i)
            if dev.get("isLoopbackDevice"):
                result["loopback"].append({"index": i, "name": dev["name"]})
            elif dev.get("maxInputChannels", 0) > 0:
                result["mic"].append({"index": i, "name": dev["name"]})
    finally:
        pa.terminate()
    return result


def _find_default_loopback(pa: pyaudio.PyAudio) -> Optional[dict]:
    try:
        for dev in pa.get_loopback_device_info_generator():
            return dev
    except AttributeError:
        pass
    try:
        for i in range(pa.get_device_count()):
            dev = pa.get_device_info_by_index(i)
            if dev.get("isLoopbackDevice"):
                return dev
    except Exception as e:
        logger.warning("Loopback introuvable : %s", e)
    return None


class AudioCapture:
    def __init__(self, out_queue: queue.Queue, config: dict,
                 status_cb: Optional[Callable[[str], None]] = None,
                 level_cb: Optional[Callable[[float, str], None]] = None):
        self._queue = out_queue
        self._cfg = config["audio"]
        self._running = False
        self._threads: list[threading.Thread] = []
        self._status = status_cb or (lambda msg: None)
        self._level_cb = level_cb or (lambda level, src: None)

    def start(self) -> None:
        self._running = True
        t_sys = threading.Thread(target=self._capture_loopback, daemon=True, name="capture-loopback")
        t_mic = threading.Thread(target=self._capture_mic,      daemon=True, name="capture-mic")
        self._threads = [t_sys, t_mic]
        for t in self._threads:
            t.start()
        logger.info("Capture audio démarrée (loopback + micro)")

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------ loopback

    def _capture_loopback(self) -> None:
        pa = pyaudio.PyAudio()
        try:
            dev_idx = self._cfg.get("loopback_device_index")
            if dev_idx is None:
                dev = _find_default_loopback(pa)
                if dev is None:
                    msg = "❌ Aucun périphérique loopback WASAPI trouvé"
                    logger.error(msg)
                    self._status(msg)
                    return
                dev_idx = dev["index"]
                native_rate = int(dev.get("defaultSampleRate", SAMPLE_RATE))
            else:
                native_rate = int(pa.get_device_info_by_index(dev_idx).get("defaultSampleRate", SAMPLE_RATE))

            dev_info = pa.get_device_info_by_index(dev_idx)
            n_channels = int(dev_info.get("maxInputChannels", 2)) or 2
            dev_name = dev_info.get("name", "?")[:40]
            logger.info("🔊 Loopback : [%d] %s @ %dHz %dch", dev_idx, dev_name, native_rate, n_channels)
            self._status(f"🔊 Loopback OK : {dev_name} @ {native_rate}Hz")

            stream = pa.open(
                format=pyaudio.paFloat32,
                channels=n_channels,
                rate=native_rate,
                input=True,
                input_device_index=dev_idx,
                frames_per_buffer=CHUNK_FRAMES,
            )

            chunk_count = 0
            level_acc = 0.0
            last_log = time.time()

            while self._running:
                raw = stream.read(CHUNK_FRAMES, exception_on_overflow=False)
                audio = np.frombuffer(raw, dtype=np.float32)
                if n_channels > 1:
                    audio = audio.reshape(-1, n_channels).mean(axis=1)
                audio = _resample_if_needed(audio, native_rate, SAMPLE_RATE)
                audio = np.clip(audio * PRE_GAIN_LOOPBACK, -1.0, 1.0)

                level = float(np.abs(audio).mean())
                level_acc += level
                chunk_count += 1

                now = time.time()
                if now - last_log >= _LEVEL_LOG_INTERVAL:
                    avg = level_acc / max(chunk_count, 1)
                    bar = "█" * min(int(avg * 40), 20)
                    logger.info("🔊 Loopback niveau moyen : %.4f  %s", avg, bar)
                    self._level_cb(avg, "system")
                    level_acc = 0.0
                    chunk_count = 0
                    last_log = now

                self._queue.put(AudioChunk(data=audio, source="system"))

            stream.stop_stream()
            stream.close()
        except Exception as e:
            logger.exception("❌ Erreur loopback : %s", e)
            self._status(f"❌ Loopback erreur : {e}")
        finally:
            pa.terminate()

    # ------------------------------------------------------------------ mic

    def _capture_mic(self) -> None:
        try:
            import sounddevice as sd

            dev_idx = self._cfg.get("mic_device_index")

            chunk_count = 0
            level_acc = 0.0
            last_log = [time.time()]

            def callback(indata: np.ndarray, frames, t, status):
                nonlocal chunk_count, level_acc
                if status:
                    logger.debug("Mic status : %s", status)
                audio = np.clip(indata[:, 0].astype(np.float32) * PRE_GAIN_MIC, -1.0, 1.0).copy()
                level = float(np.abs(audio).mean())
                level_acc += level
                chunk_count += 1

                now = time.time()
                if now - last_log[0] >= _LEVEL_LOG_INTERVAL:
                    avg = level_acc / max(chunk_count, 1)
                    bar = "█" * min(int(avg * 40), 20)
                    logger.info("🎤 Micro niveau moyen : %.4f  %s", avg, bar)
                    self._level_cb(avg, "mic")
                    level_acc = 0
                    chunk_count = 0
                    last_log[0] = now

                self._queue.put(AudioChunk(data=audio, source="mic"))

            logger.info("🎤 Micro : device %s", dev_idx or "défaut")
            self._status(f"🎤 Micro OK : device {dev_idx or 'défaut'}")
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=CHUNK_FRAMES,
                device=dev_idx,
                callback=callback,
            ):
                while self._running:
                    time.sleep(0.1)
        except Exception as e:
            logger.exception("❌ Erreur microphone : %s", e)
            self._status(f"❌ Micro erreur : {e}")


# ------------------------------------------------------------------ helpers

def _resample_if_needed(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate:
        return audio
    try:
        import librosa
        return librosa.resample(audio, orig_sr=src_rate, target_sr=dst_rate)
    except Exception:
        ratio = dst_rate / src_rate
        new_len = int(len(audio) * ratio)
        indices = np.linspace(0, len(audio) - 1, new_len)
        return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)
