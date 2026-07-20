"""
Traduction locale avec argos-translate.
Consomme des TranscriptResult (previews et finaux) et pousse des TranslationResult.
"""
import logging
import queue
import threading
from dataclasses import dataclass, field

from ..transcription.whisper_engine import TranscriptResult

logger = logging.getLogger(__name__)


@dataclass
class TranslationResult:
    original: str
    translated: str
    source_lang: str
    target_lang: str
    source: str                   # "system" | "mic"
    whisper_confidence: float = 0.0
    is_preview: bool = False


class ArgosEngine:
    def __init__(
        self,
        in_queue: queue.Queue,
        out_queue: queue.Queue,
        config: dict,
    ):
        self._in      = in_queue
        self._out     = out_queue
        self._config  = config
        self._running = False
        self._thread: threading.Thread | None = None
        self._package_cache: dict[tuple[str, str], bool] = {}

    def start(self) -> None:
        import argostranslate.package
        import argostranslate.translate
        self._argos_package   = argostranslate.package
        self._argos_translate = argostranslate.translate
        logger.info("Argos Translate prêt")
        self._running = True
        self._thread  = threading.Thread(target=self._run, daemon=True, name="translation")
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def translate(self, text: str, from_lang: str, to_lang: str) -> str:
        if from_lang == to_lang:
            return text
        if not self._ensure_package(from_lang, to_lang):
            return text
        try:
            return self._argos_translate.translate(text, from_lang, to_lang)
        except Exception as e:
            logger.error("Erreur de traduction : %s", e)
            return text

    def _run(self) -> None:
        while self._running:
            try:
                result: TranscriptResult = self._in.get(timeout=0.5)
            except queue.Empty:
                continue

            # Re-lire la config à chaque segment : supporte les changements à chaud
            target       = self._config["translation"]["target_lang"]
            fallback_src = self._config["translation"].get("source_lang", "auto")
            if fallback_src == "auto":
                fallback_src = "en"

            try:
                src_lang = result.language if result.language else fallback_src
                label    = "preview" if result.is_preview else "FINAL"
                logger.info(
                    "🌐 Traduction [%s|%s] %s→%s : \"%s\"",
                    result.source, label, src_lang, target, result.text[:60],
                )

                translated = self.translate(result.text, src_lang, target)

                if not result.is_preview:
                    logger.info("✅ Traduction terminée : \"%s\"", translated[:60])

                self._out.put(TranslationResult(
                    original=result.text,
                    translated=translated,
                    source_lang=src_lang,
                    target_lang=target,
                    source=result.source,
                    whisper_confidence=result.confidence,
                    is_preview=result.is_preview,
                ))
            except Exception as e:
                logger.exception("❌ Erreur traduction (segment ignoré) : %s", e)

    def _ensure_package(self, from_lang: str, to_lang: str) -> bool:
        key = (from_lang, to_lang)
        if key in self._package_cache:
            return self._package_cache[key]

        # Vérifie les packages installés directement (plus fiable que get_installed_languages)
        try:
            installed_pkgs = self._argos_package.get_installed_packages()
            if any(p.from_code == from_lang and p.to_code == to_lang for p in installed_pkgs):
                self._package_cache[key] = True
                return True
        except Exception as e:
            logger.debug("Erreur vérification packages installés : %s", e)

        logger.info("Installation du package %s → %s…", from_lang, to_lang)
        try:
            self._argos_package.update_package_index()
            available_pkgs = self._argos_package.get_available_packages()
            pkg = next(
                (p for p in available_pkgs if p.from_code == from_lang and p.to_code == to_lang),
                None,
            )
            if pkg is None:
                logger.error("Aucun package disponible pour %s → %s", from_lang, to_lang)
                self._package_cache[key] = False
                return False
            self._argos_package.install_from_path(pkg.download())
            self._package_cache[key] = True
            logger.info("✅ Package %s → %s installé", from_lang, to_lang)
            return True
        except Exception as e:
            logger.error("Impossible d'installer le package de traduction : %s", e)
            self._package_cache[key] = False
            return False
