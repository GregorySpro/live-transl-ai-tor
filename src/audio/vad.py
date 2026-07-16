"""
Voice Activity Detection avec silero-vad.
Accumule les chunks audio et émet des segments de parole complets.
"""
import logging
import queue
import threading
from dataclasses import dataclass, field

import numpy as np
import torch

from .capture import AudioChunk

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000


@dataclass
class SpeechSegment:
    audio: np.ndarray   # float32, mono, 16kHz — segment de parole complet
    source: str          # "system" | "mic"


class VADProcessor:
    """
    Consomme une queue de AudioChunk, détecte la parole,
    et pousse des SpeechSegment dans out_queue quand un tour de parole est terminé.
    """

    def __init__(self, in_queue: queue.Queue, out_queue: queue.Queue, config: dict):
        self._in = in_queue
        self._out = out_queue
        self._threshold = config["audio"].get("vad_threshold", 0.5)
        self._silence_ms = config["audio"].get("silence_duration_ms", 800)
        self._running = False
        self._model = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            trust_repo=True,
        )
        self._model.eval()
        logger.info("Silero-VAD chargé")
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="vad")
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _run(self) -> None:
        # Buffer par source
        buffers: dict[str, list[np.ndarray]] = {"system": [], "mic": []}
        silence_chunks: dict[str, int] = {"system": 0, "mic": 0}
        speaking: dict[str, bool] = {"system": False, "mic": False}

        chunk_duration_ms = (1024 / SAMPLE_RATE) * 1000
        silence_chunks_needed = int(self._silence_ms / chunk_duration_ms)

        while self._running:
            try:
                chunk: AudioChunk = self._in.get(timeout=0.2)
            except queue.Empty:
                continue

            src = chunk.source
            is_speech = self._is_speech(chunk.data)

            if is_speech:
                buffers[src].append(chunk.data)
                silence_chunks[src] = 0
                speaking[src] = True
            elif speaking[src]:
                buffers[src].append(chunk.data)
                silence_chunks[src] += 1
                if silence_chunks[src] >= silence_chunks_needed:
                    # Fin du tour de parole
                    full_audio = np.concatenate(buffers[src])
                    self._out.put(SpeechSegment(audio=full_audio, source=src))
                    buffers[src] = []
                    silence_chunks[src] = 0
                    speaking[src] = False

    def _is_speech(self, audio: np.ndarray) -> bool:
        try:
            tensor = torch.from_numpy(audio)
            with torch.no_grad():
                confidence = self._model(tensor, SAMPLE_RATE).item()
            return confidence >= self._threshold
        except Exception:
            return False
