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

import numpy as np

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

    # Prompt de contexte par langue : ancre le modèle de langue de Whisper
    # et réduit drastiquement les hallucinations sur les mots courts isolés
    _INITIAL_PROMPTS: dict[str, str] = {
        "fr": "Conversation en français.",
        "en": "Conversation in English.",
        "de": "Gespräch auf Deutsch.",
        "es": "Conversación en español.",
        "it": "Conversazione in italiano.",
        "pt": "Conversa em português.",
        "nl": "Gesprek in het Nederlands.",
        "ru": "Разговор на русском языке.",
        "ja": "日本語での会話。",
        "zh": "中文对话。",
        "ko": "한국어로 대화.",
        "ar": "محادثة باللغة العربية.",
    }

    _HALLUCINATIONS = {
        # Anglais
        "thank you", "thank you.", "thank you for watching.",
        "thanks for watching.", "please subscribe.", "subtitles by",
        ".", ",", "...", "♪", "♪♪", "[music]", "[applause]",
        "you", "i", "the", "a", "and", "or",
        "transcribed by", "transcription by", "captions by",
        "www.", "http", "copyright",
        # Français
        "merci.", "merci", "merci beaucoup", "merci beaucoup.",
        "sous-titres par", "sous-titrage", "sous-titres",
        "sous-titré par", "sous-titreur",
        "musique", "[musique]", "[bruit]", "[silence]",
        "bonjour.", "bonjour", "bonsoir.", "bonsoir",
        "oui.", "oui", "non.", "non",
        "voilà.", "voilà", "voila.", "voila",
        "d'accord.", "d'accord", "ok.", "ok",
    }

    # Préfixes typiques d'hallucinations Whisper
    _HALLUCINATION_PREFIXES = (
        "♪", "[", "sous-titr", "transcri", "http", "www.",
        "copyright", "tous droits",
    )

    def _is_hallucination(self, text: str) -> bool:
        cleaned = text.strip().lower()
        if len(cleaned) < 4:
            return True
        if cleaned in self._HALLUCINATIONS:
            return True
        for prefix in self._HALLUCINATION_PREFIXES:
            if cleaned.startswith(prefix):
                return True
        # Ponctuation/ellipses seules
        if all(c in '.… \t,;:!?' for c in cleaned):
            return True
        words = cleaned.split()
        n = len(words)
        # Mot unique très court (1-2 caractères hors ponctuation)
        if n == 1 and len(cleaned.rstrip(".,!?")) <= 2:
            return True
        # Tous les mots identiques sur ≥2 mots
        if n >= 2 and len(set(words)) == 1:
            return True
        # Demi-répétition sur ≥4 mots : "hello world hello world"
        if n >= 4:
            half = n // 2
            if words[:half] == words[half : half * 2]:
                return True
        # Répétitions de phrases : "phrase. phrase."
        sentences = [s.strip().rstrip(".,!?").strip() for s in cleaned.split(".") if s.strip()]
        if len(sentences) >= 2 and len(set(sentences)) == 1:
            return True
        return False

    def _normalize_audio(self, audio: np.ndarray) -> np.ndarray:
        """Ramène le signal à un niveau cohérent pour Whisper sans saturer."""
        audio = audio.astype(np.float32)
        peak = float(np.abs(audio).max())
        if peak < 1e-4:
            return audio  # silence — ne pas amplifier du bruit pur
        # Cible 0.9 de peak ; gain max 10× pour éviter d'amplifier du quasi-silence
        gain = min(0.9 / peak, 10.0)
        return np.clip(audio * gain, -1.0, 1.0)

    def _resolve_src_lang(self) -> Optional[str]:
        """Lit la langue source depuis la config (supporte les changements à chaud)."""
        lang = self._config["whisper"].get("language_source", "auto")
        if not lang or lang == "auto":
            # Fallback : langue source de traduction si définie
            trans_src = self._config["translation"].get("source_lang", "auto")
            if trans_src and trans_src != "auto":
                return trans_src
            return None
        return lang

    def _run(self) -> None:
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
            beam_size = 1 if segment.is_preview else 3
            src_lang  = self._resolve_src_lang()   # re-lu à chaque segment

            if not segment.is_preview:
                logger.info("📝 Whisper FINAL %s %.1fs…", segment.source, dur)
                self._status(f"{icon} Transcription en cours ({dur:.1f}s)…")
            else:
                logger.debug("🔍 Whisper PREVIEW %s %.1fs…", segment.source, dur)

            t0 = time.time()
            try:
                audio_in     = self._normalize_audio(segment.audio)
                initial_prompt = self._INITIAL_PROMPTS.get(src_lang or "", None)
                segments_gen, info = self._model.transcribe(
                    audio_in,
                    language=src_lang,
                    initial_prompt=initial_prompt,    # ancre le modèle de langue, réduit les hallucinations
                    beam_size=beam_size,
                    temperature=0.0,                  # passe unique — empêche la spirale multi-températures
                    # VAD interne de Whisper sur les chunks système (3s, peut contenir du silence)
                    vad_filter=(segment.source == "system"),
                    no_speech_threshold=0.45,
                    log_prob_threshold=-1.0,
                    compression_ratio_threshold=2.0,
                    condition_on_previous_text=False,
                )
                good_parts: list[str] = []
                for seg in segments_gen:
                    if seg.no_speech_prob > 0.45:
                        logger.debug("Seg rejeté no_speech=%.2f: '%s'", seg.no_speech_prob, seg.text[:30])
                        continue
                    good_parts.append(seg.text.strip())
                text    = " ".join(good_parts).strip()
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
