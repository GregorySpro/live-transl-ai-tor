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
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


def main() -> None:
    config = cfg_module.load()

    # Détection matériel + override manuel si désactivé
    profile = detector.detect()
    profile = detector.apply_config_overrides(profile, config)
    logger.info("Profil actif : %s", profile.description)

    # Sauvegarder le profil détecté
    config["hardware"]["detected_profile"] = profile.description
    cfg_module.save(config)

    # Queues inter-threads
    raw_queue: queue.Queue = queue.Queue(maxsize=200)
    speech_queue: queue.Queue = queue.Queue(maxsize=50)
    transcript_queue: queue.Queue = queue.Queue(maxsize=50)
    result_queue: queue.Queue = queue.Queue(maxsize=50)

    # Pipeline
    capture = AudioCapture(raw_queue, config)
    vad = VADProcessor(raw_queue, speech_queue, config)
    whisper = WhisperEngine(speech_queue, transcript_queue, profile, config)
    argos = ArgosEngine(transcript_queue, result_queue, config)

    # Qt app
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    overlay = Overlay(config)

    # Thread de dispatch : lit result_queue → overlay (thread-safe via signal Qt)
    def _dispatch_loop():
        while True:
            try:
                result = result_queue.get(timeout=1.0)
                overlay.push_result(result)
            except queue.Empty:
                continue
            except Exception as e:
                logger.exception("Erreur dispatch : %s", e)

    dispatch_thread = threading.Thread(target=_dispatch_loop, daemon=True, name="dispatch")
    dispatch_thread.start()

    # Démarrage du pipeline (ordre important)
    logger.info("Chargement de Whisper…")
    whisper.start()
    logger.info("Chargement d'Argos…")
    argos.start()
    logger.info("Démarrage du VAD…")
    vad.start()
    logger.info("Démarrage de la capture audio…")
    capture.start()

    # Raccourci global
    hotkey = config["ui"].get("hotkey", "ctrl+shift+t")
    keyboard.add_hotkey(hotkey, overlay.toggle)
    logger.info("Raccourci global : %s", hotkey)
    logger.info("live-transl-ai-tor prêt — appuie sur %s pour ouvrir l'overlay", hotkey)

    # Lancer l'UI
    overlay.show()
    exit_code = app.exec()

    # Arrêt propre
    capture.stop()
    vad.stop()
    whisper.stop()
    argos.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
