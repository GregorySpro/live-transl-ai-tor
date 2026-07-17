"""
Voice Activity Detection avec silero-vad.
Émet des SpeechSegment finaux (silence détecté) ET des previews
toutes les PREVIEW_INTERVAL_S secondes pendant la parole active.
"""
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import torch

from .capture import AudioChunk

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
PREVIEW_INTERVAL_S = 1.5    # fréquence d'émission des previews live
MIN_PREVIEW_S      = 0.8    # durée minimale d'audio pour un preview


@dataclass
class SpeechSegment:
    audio: np.ndarray
    source: str
    is_preview: bool = False   # True = chunk live, False = segment final


class VADProcessor:
    def __init__(
        self,
        in_queue: queue.Queue,
        out_queue: queue.Queue,
        config: dict,
        status_cb: Optional[Callable[[str], None]] = None,
        speaking_cb: Optional[Callable[[bool, str], None]] = None,
    ):
        self._in          = in_queue
        self._out         = out_queue
        self._threshold   = config["audio"].get("vad_threshold", 0.5)
        self._silence_ms  = config["audio"].get("silence_duration_ms", 800)
        self._running     = False
        self._model       = None
        self._thread: threading.Thread | None = None
        self._status      = status_cb   or (lambda msg: None)
        self._speaking_cb = speaking_cb or (lambda is_sp, src: None)

    def start(self) -> None:
        self._model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            trust_repo=True,
        )
        self._model.eval()
        logger.info("Silero-VAD chargé (seuil=%.2f)", self._threshold)
        self._running = True
        self._thread  = threading.Thread(target=self._run, daemon=True, name="vad")
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _run(self) -> None:
        buffers:         dict[str, list[np.ndarray]] = {"system": [], "mic": []}
        silence_chunks:  dict[str, int]              = {"system": 0,   "mic": 0}
        speaking:        dict[str, bool]             = {"system": False,"mic": False}
        last_preview:    dict[str, float]            = {"system": 0.0,  "mic": 0.0}

        chunk_duration_ms    = (1024 / SAMPLE_RATE) * 1000
        silence_chunks_needed = int(self._silence_ms / chunk_duration_ms)

        icons = {"system": "🔊", "mic": "🎤"}

        while self._running:
            try:
                chunk: AudioChunk = self._in.get(timeout=0.2)
            except queue.Empty:
                continue

            src = chunk.source
            confidence, is_speech = self._vad_score(chunk.data)

            if confidence > 0.1:
                logger.debug("VAD [%s] conf=%.2f  speech=%s", src, confidence, is_speech)

            # ── Début de parole ───────────────────────────────────────
            if is_speech and not speaking[src]:
                speaking[src]      = True
                last_preview[src]  = time.time()
                logger.info("👂 Parole détectée [%s] conf=%.2f", src, confidence)
                self._status(f"{icons[src]} Parole détectée… (conf={confidence:.0%})")
                self._speaking_cb(True, src)

            # ── Accumulation ──────────────────────────────────────────
            if is_speech:
                buffers[src].append(chunk.data)
                silence_chunks[src] = 0

                # Émission d'un preview toutes les PREVIEW_INTERVAL_S
                now = time.time()
                if (now - last_preview[src]) >= PREVIEW_INTERVAL_S:
                    audio_so_far = np.concatenate(buffers[src])
                    dur = len(audio_so_far) / SAMPLE_RATE
                    if dur >= MIN_PREVIEW_S:
                        self._out.put(SpeechSegment(
                            audio=audio_so_far.copy(),
                            source=src,
                            is_preview=True,
                        ))
                        logger.debug("🔍 Preview [%s] %.1fs", src, dur)
                        last_preview[src] = now

            # ── Silence → fin du segment ──────────────────────────────
            elif speaking[src]:
                buffers[src].append(chunk.data)
                silence_chunks[src] += 1
                if silence_chunks[src] >= silence_chunks_needed:
                    audio_final = np.concatenate(buffers[src])
                    dur = len(audio_final) / SAMPLE_RATE
                    logger.info("✅ Segment [%s] terminé — %.1fs → Whisper", src, dur)
                    self._status(f"{icons[src]} Segment {dur:.1f}s → Whisper…")
                    self._out.put(SpeechSegment(
                        audio=audio_final,
                        source=src,
                        is_preview=False,
                    ))
                    buffers[src]        = []
                    silence_chunks[src] = 0
                    speaking[src]       = False
                    self._speaking_cb(False, src)

    def _vad_score(self, audio: np.ndarray) -> tuple[float, bool]:
        """Silero-VAD requiert exactement 512 samples à 16kHz."""
        VAD_WINDOW = 512
        try:
            peak = np.abs(audio).max()
            if peak < 1e-6:
                return 0.0, False
            normalized = (audio / peak).astype(np.float32)
            max_conf = 0.0
            for i in range(0, len(normalized) - VAD_WINDOW + 1, VAD_WINDOW):
                window = normalized[i:i + VAD_WINDOW]
                tensor = torch.from_numpy(window)
                with torch.no_grad():
                    conf = float(self._model(tensor, SAMPLE_RATE).item())
                if conf > max_conf:
                    max_conf = conf
            return max_conf, max_conf >= self._threshold
        except Exception as e:
            logger.debug("VAD erreur : %s", e)
            return 0.0, False
