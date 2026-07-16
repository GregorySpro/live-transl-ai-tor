"""
Point d'entrée — orchestre tous les composants.
"""
import logging
import queue
import sys
import threading

import keyboard
from PyQt6.QtWidgets import QApplication

from . import config as cfg_module
from .hardware import detector
from .audio.capture import AudioCapture
from .audio.vad import VADProcessor
from .transcription.whisper_engine import WhisperEngine
from .translation.argos_engine import ArgosEngine
from .ui.overlay import Overlay

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
)
# Silencer les libs trop verboses
for noisy in (
    "httpx", "httpcore", "urllib3", "filelock", "huggingface_hub",
    "numba", "numba.core", "numba.core.byteflow", "numba.core.interpreter",
    "numba.core.ssa", "numba.typed",
):
    logging.getLogger(noisy).setLevel(logging.WARNING)

logger = logging.getLogger("main")


def main() -> None:
    config = cfg_module.load()

    profile = detector.detect()
    profile = detector.apply_config_overrides(profile, config)
    logger.info("Profil matériel : %s", profile.description)

    config["hardware"]["detected_profile"] = profile.description
    cfg_module.save(config)

    # Queues inter-threads
    raw_queue:        queue.Queue = queue.Queue(maxsize=200)
    speech_queue:     queue.Queue = queue.Queue(maxsize=50)
    transcript_queue: queue.Queue = queue.Queue(maxsize=50)
    result_queue:     queue.Queue = queue.Queue(maxsize=50)

    # Qt app — doit être créé avant l'overlay
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    overlay = Overlay(config)

    # Callback de statut thread-safe : met à jour le label "en cours" de l'overlay
    def status(msg: str) -> None:
        overlay.set_live_text(msg, "system")

    # Pipeline avec callbacks de statut
    capture = AudioCapture(raw_queue, config, status_cb=status)
    vad     = VADProcessor(raw_queue, speech_queue, config, status_cb=status)
    whisper = WhisperEngine(speech_queue, transcript_queue, profile, config, status_cb=status)
    argos   = ArgosEngine(transcript_queue, result_queue, config)

    # Dispatch : result_queue → overlay
    def _dispatch_loop():
        while True:
            try:
                result = result_queue.get(timeout=1.0)
                overlay.push_result(result)
            except queue.Empty:
                continue
            except Exception as e:
                logger.exception("Erreur dispatch : %s", e)

    threading.Thread(target=_dispatch_loop, daemon=True, name="dispatch").start()

    # Chargement dans l'ordre
    overlay.set_live_text("⏳ Chargement de Whisper…", "system")
    overlay.show()

    logger.info("⏳ Chargement de Whisper (%s)…", profile.whisper_model)
    whisper.start()

    logger.info("⏳ Chargement d'Argos…")
    overlay.set_live_text("⏳ Chargement d'Argos Translate…", "system")
    argos.start()

    logger.info("⏳ Démarrage VAD…")
    overlay.set_live_text("⏳ Démarrage VAD (Silero)…", "system")
    vad.start()

    logger.info("⏳ Démarrage capture audio…")
    overlay.set_live_text("⏳ Démarrage capture audio…", "system")
    capture.start()

    overlay.set_live_text("✅ Prêt — en attente de parole…", "system")

    hotkey = config["ui"].get("hotkey", "ctrl+shift+t")

    def _register_hotkey() -> None:
        try:
            keyboard.add_hotkey(hotkey, overlay.toggle)
            logger.info("⌨️  Raccourci global : %s", hotkey)
        except Exception as e:
            logger.warning("Raccourci global indisponible : %s", e)

    from PyQt6.QtCore import QTimer
    QTimer.singleShot(500, _register_hotkey)

    logger.info("✅ live-transl-ai-tor prêt")
    exit_code = app.exec()

    capture.stop()
    vad.stop()
    whisper.stop()
    argos.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
