"""
Transcription avec faster-whisper.
Consomme des SpeechSegment et pousse des TranscriptResult.
"""
import logging
import queue
import threading
from dataclasses import dataclass

import numpy as np
from faster_whisper import WhisperModel

from ..audio.vad import SpeechSegment
from ..hardware.detector import HardwareProfile

logger = logging.getLogger(__name__)


@dataclass
class TranscriptResult:
    text: str
    language: str
    source: str   # "system" | "mic"
    confidence: float


class WhisperEngine:
    def __init__(
        self,
        in_queue: queue.Queue,
        out_queue: queue.Queue,
        profile: HardwareProfile,
        config: dict,
    ):
        self._in = in_queue
        self._out = out_queue
        self._profile = profile
        self._config = config
        self._model: WhisperModel | None = None
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        model_size = self._profile.whisper_model
        device = self._profile.device
        compute = self._profile.compute_type

        logger.info("Chargement Whisper %s sur %s [%s]…", model_size, device, compute)
        self._model = WhisperModel(model_size, device=device, compute_type=compute)
        logger.info("Whisper prêt")

        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="whisper")
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _run(self) -> None:
        src_lang = self._config["whisper"].get("language_source") or None
        if src_lang == "auto":
            src_lang = None  # faster-whisper auto-détecte si None

        while self._running:
            try:
                segment: SpeechSegment = self._in.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                segments, info = self._model.transcribe(
                    segment.audio,
                    language=src_lang,
                    beam_size=5,
                    vad_filter=False,  # déjà filtré par notre VAD
                )
                text = " ".join(s.text.strip() for s in segments).strip()
                if not text:
                    continue
                # Confiance approximative via avg_logprob du dernier segment
                confidence = getattr(info, "all_language_probs", {}).get(info.language, 0.0)
                self._out.put(TranscriptResult(
                    text=text,
                    language=info.language,
                    source=segment.source,
                    confidence=float(confidence),
                ))
            except Exception as e:
                logger.exception("Erreur Whisper : %s", e)
