"""
Transcription avec faster-whisper.
- Segments finaux   : beam_size=5, qualité maximale
- Segments previews : beam_size=1, rapide (<0.5s)
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
    is_preview: bool = False


class WhisperEngine:
    def __init__(
        self,
        in_queue: queue.Queue,
        out_queue: queue.Queue,
        profile: HardwareProfile,
        config: dict,
        status_cb: Optional[Callable[[str], None]] = None,
    ):
        self._in      = in_queue
        self._out     = out_queue
        self._profile = profile
        self._config  = config
        self._model: WhisperModel | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._status  = status_cb or (lambda msg: None)

    def start(self) -> None:
        model_size = self._profile.whisper_model
        device     = self._profile.device
        compute    = self._profile.compute_type
        logger.info("Chargement Whisper %s sur %s [%s]…", model_size, device, compute)
        self._model = WhisperModel(model_size, device=device, compute_type=compute)
        logger.info("✅ Whisper prêt (%s/%s/%s)", model_size, device, compute)
        self._running = True
        self._thread  = threading.Thread(target=self._run, daemon=True, name="whisper")
        self._thread.start()

    def stop(self) -> None:
        self._running = False

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

        # Pour les previews : on garde la dernière preview en attente
        # et on la remplace si une nouvelle arrive avant traitement
        pending_preview: Optional[SpeechSegment] = None
        icons = {"system": "🔊", "mic": "🎤"}

        while self._running:
            # ── Récupère le prochain segment ──────────────────────────
            segment: Optional[SpeechSegment] = None
            try:
                segment = self._in.get(timeout=0.1)
            except queue.Empty:
                # Pas de segment final → traite preview en attente si présent
                if pending_preview is not None:
                    segment = pending_preview
                    pending_preview = None
                else:
                    continue

            if segment is None:
                continue

            # Si c'est un preview, drainer la file pour garder le plus récent
            if segment.is_preview:
                while True:
                    try:
                        next_seg = self._in.get_nowait()
                        if not next_seg.is_preview:
                            # Un final est arrivé — traite-le en priorité
                            pending_preview = None
                            segment = next_seg
                            break
                        else:
                            segment = next_seg   # garde le preview le plus récent
                    except queue.Empty:
                        break

                # Si après drainage c'est encore un preview, on le met en attente
                # pour laisser la chance à un final d'arriver rapidement
                if segment.is_preview:
                    # Vérification rapide : file toujours vide ?
                    if self._in.empty():
                        pending_preview = None
                        # traite ce preview ci-dessous
                    else:
                        pending_preview = segment
                        continue

            # ── Transcription ──────────────────────────────────────────
            icon      = icons.get(segment.source, "●")
            dur       = len(segment.audio) / 16000
            beam_size = 1 if segment.is_preview else 5

            if not segment.is_preview:
                logger.info("📝 Whisper FINAL %s %.1fs…", segment.source, dur)
                self._status(f"{icon} Transcription en cours ({dur:.1f}s)…")
            else:
                logger.debug("🔍 Whisper PREVIEW %s %.1fs…", segment.source, dur)

            t0 = time.time()
            try:
                segments_gen, info = self._model.transcribe(
                    segment.audio,
                    language=src_lang,
                    beam_size=beam_size,
                    vad_filter=False,
                    no_speech_threshold=0.85,
                    log_prob_threshold=-2.0,
                )
                text    = " ".join(s.text.strip() for s in segments_gen).strip()
                elapsed = time.time() - t0

                if not text or self._is_hallucination(text):
                    if not segment.is_preview:
                        logger.info("📝 Whisper : segment ignoré '%s' (%.1fs)", text[:40], elapsed)
                        self._status("⏳ En attente de parole…")
                    continue

                logger.info(
                    "📝 Whisper [%s|%s] → \"%s\" (%.1fs, lang=%s)",
                    segment.source,
                    "preview" if segment.is_preview else "final",
                    text[:60],
                    elapsed,
                    info.language,
                )
                if not segment.is_preview:
                    self._status(f"{icon} Transcrit ({elapsed:.1f}s) → traduction…")

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
                    is_preview=segment.is_preview,
                ))

            except Exception as e:
                logger.exception("❌ Erreur Whisper : %s", e)
                if not segment.is_preview:
                    self._status(f"❌ Erreur Whisper : {e}")
