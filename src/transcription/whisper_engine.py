"""
Transcription avec faster-whisper.
"""
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from faster_whisper import WhisperModel

from ..audio.vad import SpeechSegment
from ..hardware.detector import HardwareProfile

logger = logging.getLogger(__name__)


@dataclass
class TranscriptResult:
    text: str
    language: str
    source: str
    confidence: float


class WhisperEngine:
    def __init__(self, in_queue: queue.Queue, out_queue: queue.Queue,
                 profile: HardwareProfile, config: dict,
                 status_cb: Optional[Callable[[str], None]] = None):
        self._in = in_queue
        self._out = out_queue
        self._profile = profile
        self._config = config
        self._model: WhisperModel | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._status = status_cb or (lambda msg: None)

    def start(self) -> None:
        model_size = self._profile.whisper_model
        device = self._profile.device
        compute = self._profile.compute_type
        logger.info("Chargement Whisper %s sur %s [%s]…", model_size, device, compute)
        self._model = WhisperModel(model_size, device=device, compute_type=compute)
        logger.info("✅ Whisper prêt (%s/%s/%s)", model_size, device, compute)
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="whisper")
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    # Phrases générées par Whisper quand il n'y a pas de vraie parole
    _HALLUCINATIONS = {
        "thank you", "thank you.", "thank you for watching.",
        "thanks for watching.", "please subscribe.", "subtitles by",
        ".", ",", "...", "♪", "♪♪", "[music]", "[applause]",
        "you", "i", "the", "a",
    }

    def _is_hallucination(self, text: str) -> bool:
        cleaned = text.strip().lower()
        if len(cleaned) < 3:
            return True
        if cleaned in self._HALLUCINATIONS:
            return True
        if cleaned.startswith("♪") or cleaned.startswith("["):
            return True
        return False

    def _run(self) -> None:
        src_lang = self._config["whisper"].get("language_source") or None
        if src_lang == "auto":
            src_lang = None

        while self._running:
            try:
                segment: SpeechSegment = self._in.get(timeout=0.5)
            except queue.Empty:
                continue

            icons = {"system": "🔊", "mic": "🎤"}
            icon = icons.get(segment.source, "●")
            dur = len(segment.audio) / 16000
            logger.info("📝 Whisper transcrit %s %.1fs…", segment.source, dur)
            self._status(f"{icon} Transcription en cours ({dur:.1f}s)…")
            t0 = time.time()

            try:
                segments_gen, info = self._model.transcribe(
                    segment.audio,
                    language=src_lang,
                    beam_size=5,
                    vad_filter=False,
                    no_speech_threshold=0.85,   # plus permissif (défaut=0.6)
                    log_prob_threshold=-2.0,     # plus permissif (défaut=-1.0)
                )
                text = " ".join(s.text.strip() for s in segments_gen).strip()
                elapsed = time.time() - t0

                if not text or self._is_hallucination(text):
                    logger.info("📝 Whisper : segment ignoré '%s' (%.1fs)", text[:40], elapsed)
                    self._status("⏳ En attente de parole…")
                    continue

                logger.info("📝 Whisper [%s] → \"%s\" (%.1fs, lang=%s)",
                            segment.source, text[:80], elapsed, info.language)
                self._status(f"{icon} Transcrit ({elapsed:.1f}s) → traduction…")

                # all_language_probs peut être une liste [(lang, prob)] ou un dict
                probs = getattr(info, "all_language_probs", None)
                if isinstance(probs, dict):
                    confidence = probs.get(info.language, 0.0)
                elif isinstance(probs, list) and probs:
                    confidence = next((p for l, p in probs if l == info.language), 0.0)
                else:
                    confidence = 0.0
                self._out.put(TranscriptResult(
                    text=text,
                    language=info.language,
                    source=segment.source,
                    confidence=float(confidence),
                ))
            except Exception as e:
                logger.exception("❌ Erreur Whisper : %s", e)
                self._status(f"❌ Erreur Whisper : {e}")
