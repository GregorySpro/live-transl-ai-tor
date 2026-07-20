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
PREVIEW_INTERVAL_S = 0.5    # fréquence d'émission des previews live (mic)
MIN_PREVIEW_S      = 0.4    # durée minimale d'audio pour un preview (mic)
SYSTEM_CHUNK_S     = 3.0    # durée des chunks loopback système (fenêtre fixe)
SYSTEM_MIN_LEVEL   = 0.01   # niveau minimum pour envoyer un chunk système (ajusté au nouveau gain)
MIN_CHUNK_LEVEL    = 0.008  # filtre absolu pré-Silero : ignore le bruit de fond pur
MIN_SEGMENT_RMS    = 0.015  # RMS minimum d'un segment mic avant envoi à Whisper
ONSET_FRAMES       = 2      # frames consécutives is_speech requis avant déclenchement (anti-click)


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
        # ── État pour le mic (VAD classique) ──────────────────────────
        mic_buffer:    list[np.ndarray] = []
        mic_silence:   int              = 0
        mic_speaking:  bool             = False
        mic_last_prev: float            = 0.0
        mic_onset:     int              = 0   # frames is_speech consécutives avant déclenchement

        chunk_duration_ms     = (1024 / SAMPLE_RATE) * 1000
        silence_chunks_needed = int(self._silence_ms / chunk_duration_ms)

        # ── État pour le loopback système (fenêtre fixe, pas de VAD) ──
        sys_buffer:     list[np.ndarray] = []
        sys_chunk_start: float           = time.time()

        while self._running:
            try:
                chunk: AudioChunk = self._in.get(timeout=0.2)
            except queue.Empty:
                # Vérifier si un chunk système est prêt même sans nouveau chunk
                now = time.time()
                if sys_buffer and (now - sys_chunk_start) >= SYSTEM_CHUNK_S:
                    self._flush_system_chunk(sys_buffer, sys_chunk_start)
                    sys_buffer      = []
                    sys_chunk_start = now
                continue

            src = chunk.source

            # ════════════════════════════════════════════════════════════
            # LOOPBACK SYSTÈME : fenêtre fixe de SYSTEM_CHUNK_S secondes
            # ════════════════════════════════════════════════════════════
            if src == "system":
                sys_buffer.append(chunk.data)
                now = time.time()
                if (now - sys_chunk_start) >= SYSTEM_CHUNK_S:
                    self._flush_system_chunk(sys_buffer, sys_chunk_start)
                    sys_buffer      = []
                    sys_chunk_start = now
                continue

            # ════════════════════════════════════════════════════════════
            # MICROPHONE : VAD classique avec segmentation par silence
            # ════════════════════════════════════════════════════════════
            confidence, is_speech = self._vad_score(chunk.data)

            if confidence > 0.1:
                logger.debug("VAD [mic] conf=%.2f  speech=%s", confidence, is_speech)

            if is_speech:
                mic_onset += 1
                mic_buffer.append(chunk.data)
                mic_silence = 0

                # ── Déclenchement après ONSET_FRAMES consécutifs (anti-click) ──
                if not mic_speaking and mic_onset >= ONSET_FRAMES:
                    mic_speaking  = True
                    mic_last_prev = time.time()
                    logger.info("👂 Parole détectée [mic] conf=%.2f", confidence)
                    self._status(f"🎤 Parole détectée… (conf={confidence:.0%})")
                    self._speaking_cb(True, "mic")

                # ── Preview (uniquement si parole confirmée) ──────────
                if mic_speaking:
                    now = time.time()
                    if (now - mic_last_prev) >= PREVIEW_INTERVAL_S:
                        audio_so_far = np.concatenate(mic_buffer)
                        if len(audio_so_far) / SAMPLE_RATE >= MIN_PREVIEW_S:
                            self._out.put(SpeechSegment(
                                audio=audio_so_far.copy(),
                                source="mic",
                                is_preview=True,
                            ))
                            logger.debug("🔍 Preview [mic] %.1fs", len(audio_so_far) / SAMPLE_RATE)
                            mic_last_prev = now

            # ── Silence pendant la parole → fin du segment ────────────
            elif mic_speaking:
                mic_onset = 0
                mic_buffer.append(chunk.data)
                mic_silence += 1
                if mic_silence >= silence_chunks_needed:
                    audio_final = np.concatenate(mic_buffer)
                    dur = len(audio_final) / SAMPLE_RATE
                    rms = float(np.sqrt(np.mean(audio_final.astype(np.float64) ** 2)))
                    if rms >= MIN_SEGMENT_RMS:
                        logger.info("✅ Segment [mic] terminé — %.1fs (RMS=%.4f) → Whisper", dur, rms)
                        self._status(f"🎤 Segment {dur:.1f}s → Whisper…")
                        self._out.put(SpeechSegment(audio=audio_final, source="mic", is_preview=False))
                    else:
                        logger.debug("⚠️ Segment [mic] rejeté — RMS trop faible (%.4f)", rms)
                    mic_buffer   = []
                    mic_silence  = 0
                    mic_speaking = False
                    self._speaking_cb(False, "mic")

            else:
                # Silence hors parole : décrémente l'onset et vide le pré-buffer si avorté
                if mic_onset > 0:
                    mic_onset -= 1
                if mic_onset == 0 and mic_buffer:
                    mic_buffer = []  # flush les frames pré-onset si l'onset n'a pas abouti

    def _flush_system_chunk(self, buffer: list[np.ndarray], t_start: float) -> None:
        """Envoie un chunk système à Whisper s'il contient de l'audio réel."""
        if not buffer:
            return
        audio = np.concatenate(buffer)
        level = float(np.abs(audio).max())
        dur   = len(audio) / SAMPLE_RATE
        if level < SYSTEM_MIN_LEVEL:
            logger.debug("🔊 Chunk système silencieux (%.5f) — ignoré", level)
            return
        logger.info("🔊 Chunk système %.1fs (level=%.4f) → Whisper", dur, level)
        self._out.put(SpeechSegment(
            audio=audio,
            source="system",
            is_preview=False,
        ))

    def _vad_score(self, audio: np.ndarray) -> tuple[float, bool]:
        """Silero-VAD requiert exactement 512 samples à 16kHz."""
        VAD_WINDOW = 512
        try:
            peak = float(np.abs(audio).max())
            # Filtre absolu : si même le pic est sous le seuil minimal,
            # c'est du bruit de fond pur — inutile d'interroger Silero
            if peak < MIN_CHUNK_LEVEL:
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
