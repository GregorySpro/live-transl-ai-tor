"""
Traduction locale avec argos-translate.
Consomme des TranscriptResult et pousse des TranslationResult.
"""
import logging
import queue
import threading
from dataclasses import dataclass

from ..transcription.whisper_engine import TranscriptResult

logger = logging.getLogger(__name__)


@dataclass
class TranslationResult:
    original: str
    translated: str
    source_lang: str
    target_lang: str
    source: str          # "system" | "mic"


class ArgosEngine:
    def __init__(
        self,
        in_queue: queue.Queue,
        out_queue: queue.Queue,
        config: dict,
    ):
        self._in = in_queue
        self._out = out_queue
        self._config = config
        self._running = False
        self._thread: threading.Thread | None = None
        # Cache des packages installés : (src, tgt) → bool
        self._package_cache: dict[tuple[str, str], bool] = {}

    def start(self) -> None:
        import argostranslate.package
        import argostranslate.translate
        self._argos_package = argostranslate.package
        self._argos_translate = argostranslate.translate
        logger.info("Argos Translate prêt")

        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="translation")
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
        target = self._config["translation"]["target_lang"]
        # source_lang de la config est utilisé comme fallback si Whisper n'a pas détecté
        fallback_src = self._config["translation"].get("source_lang", "en")

        while self._running:
            try:
                result: TranscriptResult = self._in.get(timeout=0.5)
            except queue.Empty:
                continue

            src_lang = result.language if result.language else fallback_src
            logger.info("🌐 Traduction [%s] %s→%s : \"%s\"", result.source, src_lang, target, result.text[:80])
            translated = self.translate(result.text, src_lang, target)
            logger.info("✅ Traduction terminée : \"%s\"", translated[:80])

            self._out.put(TranslationResult(
                original=result.text,
                translated=translated,
                source_lang=src_lang,
                target_lang=target,
                source=result.source,
            ))
            logger.info("📤 Résultat envoyé à l'overlay")

    def _ensure_package(self, from_lang: str, to_lang: str) -> bool:
        key = (from_lang, to_lang)
        if key in self._package_cache:
            return self._package_cache[key]

        installed = self._argos_translate.get_installed_languages()
        installed_codes = {lang.code for lang in installed}

        if from_lang in installed_codes and to_lang in installed_codes:
            src_lang_obj = next(l for l in installed if l.code == from_lang)
            available = {t.code for t in src_lang_obj.translations_to}
            if to_lang in available:
                self._package_cache[key] = True
                return True

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
            return True
        except Exception as e:
            logger.error("Impossible d'installer le package de traduction : %s", e)
            self._package_cache[key] = False
            return False
