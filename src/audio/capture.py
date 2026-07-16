"""
Capture audio système (WASAPI loopback) + microphone.
Utilise pyaudiowpatch pour le loopback et sounddevice pour le micro.
"""
import logging
import queue
import threading
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pyaudiowpatch as pyaudio

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_FRAMES = 1024
PRE_GAIN = 8.0  # Amplifie le signal loopback (souvent très atténué par Windows)


@dataclass
class AudioChunk:
    data: np.ndarray      # float32, mono, 16kHz
    source: str           # "system" | "mic"


def list_devices() -> dict:
    """Retourne les périphériques audio disponibles."""
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
        # Méthode recommandée par pyaudiowpatch
        for dev in pa.get_loopback_device_info_generator():
            return dev   # premier device loopback trouvé
    except AttributeError:
        pass
    # Fallback : parcours manuel
    try:
        for i in range(pa.get_device_count()):
            dev = pa.get_device_info_by_index(i)
            if dev.get("isLoopbackDevice"):
                return dev
    except Exception as e:
        logger.warning("Impossible de trouver le loopback WASAPI : %s", e)
    return None


class AudioCapture:
    """
    Capture en parallèle le son système (loopback) et le microphone.
    Pousse des AudioChunk dans `out_queue`.
    """

    def __init__(self, out_queue: queue.Queue, config: dict):
        self._queue = out_queue
        self._cfg = config["audio"]
        self._running = False
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        self._running = True
        t_sys = threading.Thread(target=self._capture_loopback, daemon=True, name="capture-loopback")
        t_mic = threading.Thread(target=self._capture_mic, daemon=True, name="capture-mic")
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
                    logger.error("Aucun périphérique loopback trouvé — audio système désactivé")
                    return
                dev_idx = dev["index"]
                native_rate = int(dev.get("defaultSampleRate", SAMPLE_RATE))
            else:
                native_rate = int(pa.get_device_info_by_index(dev_idx).get("defaultSampleRate", SAMPLE_RATE))

            # Utiliser le nombre de canaux natif du device (souvent 2 pour le loopback)
            dev_info = pa.get_device_info_by_index(dev_idx)
            n_channels = int(dev_info.get("maxInputChannels", 2)) or 2
            logger.info("Loopback : device %d @ %d Hz, %d ch", dev_idx, native_rate, n_channels)
            stream = pa.open(
                format=pyaudio.paFloat32,
                channels=n_channels,
                rate=native_rate,
                input=True,
                input_device_index=dev_idx,
                frames_per_buffer=CHUNK_FRAMES,
            )
            while self._running:
                raw = stream.read(CHUNK_FRAMES, exception_on_overflow=False)
                audio = np.frombuffer(raw, dtype=np.float32)
                # Stereo → mono
                if n_channels > 1:
                    audio = audio.reshape(-1, n_channels).mean(axis=1)
                audio = _resample_if_needed(audio, native_rate, SAMPLE_RATE)
                # Amplifie + clamp pour compenser le volume faible du loopback
                audio = np.clip(audio * PRE_GAIN, -1.0, 1.0)
                self._queue.put(AudioChunk(data=audio, source="system"))
            stream.stop_stream()
            stream.close()
        except Exception as e:
            logger.exception("Erreur loopback : %s", e)
        finally:
            pa.terminate()

    # ------------------------------------------------------------------ mic

    def _capture_mic(self) -> None:
        try:
            import sounddevice as sd

            dev_idx = self._cfg.get("mic_device_index")

            def callback(indata: np.ndarray, frames, time, status):
                if status:
                    logger.debug("Mic status : %s", status)
                audio = indata[:, 0].astype(np.float32).copy()
                self._queue.put(AudioChunk(data=audio, source="mic"))

            logger.info("Micro : device %s", dev_idx or "défaut")
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=CHUNK_FRAMES,
                device=dev_idx,
                callback=callback,
            ):
                while self._running:
                    import time as _time
                    _time.sleep(0.1)
        except Exception as e:
            logger.exception("Erreur microphone : %s", e)


# ------------------------------------------------------------------ helpers

def _resample_if_needed(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate:
        return audio
    try:
        import librosa
        return librosa.resample(audio, orig_sr=src_rate, target_sr=dst_rate)
    except Exception:
        # Fallback : resample simple (qualité dégradée)
        ratio = dst_rate / src_rate
        new_len = int(len(audio) * ratio)
        indices = np.linspace(0, len(audio) - 1, new_len)
        return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)
