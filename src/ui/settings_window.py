"""
Fenêtre de paramètres — permet l'override manuel de tous les réglages auto.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox,
    QPushButton, QGroupBox, QTabWidget, QWidget, QLineEdit,
)

import argostranslate.translate as _argos

# Langues les plus courantes (code ISO 639-1)
COMMON_LANGS = [
    ("auto", "Détection automatique"),
    ("fr",  "Français"),
    ("en",  "Anglais"),
    ("de",  "Allemand"),
    ("es",  "Espagnol"),
    ("it",  "Italien"),
    ("pt",  "Portugais"),
    ("nl",  "Néerlandais"),
    ("pl",  "Polonais"),
    ("ru",  "Russe"),
    ("ja",  "Japonais"),
    ("zh",  "Chinois"),
    ("ar",  "Arabe"),
    ("ko",  "Coréen"),
]

WHISPER_MODELS = ["auto", "tiny", "base", "small", "medium", "large-v3"]
COMPUTE_TYPES  = ["auto", "float16", "int8", "float32"]
DEVICES        = ["auto", "cuda", "cpu"]


class SettingsWindow(QDialog):
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._cfg = config
        self.setWindowTitle("Paramètres — live-transl-ai-tor")
        self.setMinimumWidth(460)
        self.setStyleSheet("""
            QDialog { background: #0f0f14; color: #e2e8f0; }
            QGroupBox { color: #94a3b8; font-size: 12px; border: 1px solid #1e293b;
                        border-radius: 6px; margin-top: 8px; padding-top: 8px; }
            QGroupBox::title { subcontrol-origin: margin; padding: 0 4px; }
            QLabel { color: #cbd5e1; }
            QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
                background: #1e293b; color: #e2e8f0; border: 1px solid #334155;
                border-radius: 4px; padding: 4px 8px; }
            QPushButton { background: #1e40af; color: #e2e8f0; border: none;
                          border-radius: 4px; padding: 6px 16px; }
            QPushButton:hover { background: #2563eb; }
            QCheckBox { color: #cbd5e1; }
        """)

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.setStyleSheet("QTabBar::tab { color: #94a3b8; padding: 6px 16px; }")
        layout.addWidget(tabs)

        tabs.addTab(self._make_translation_tab(), "Traduction")
        tabs.addTab(self._make_whisper_tab(), "Whisper / IA")
        tabs.addTab(self._make_audio_tab(), "Audio")
        tabs.addTab(self._make_ui_tab(), "Interface")

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = QPushButton("Sauvegarder")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Annuler")
        cancel_btn.setStyleSheet("background: #1e293b;")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------ tabs

    def _make_translation_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._src_lang = self._lang_combo(self._cfg.get("translation", {}).get("source_lang", "en"))
        self._tgt_lang = self._lang_combo(self._cfg.get("translation", {}).get("target_lang", "fr"))

        form.addRow("Langue source :", self._src_lang)
        form.addRow("Langue cible :", self._tgt_lang)

        note = QLabel("Les packages de langue manquants seront téléchargés automatiquement au premier usage.")
        note.setStyleSheet("color: #64748b; font-size: 11px;")
        note.setWordWrap(True)
        form.addRow(note)
        return w

    def _make_whisper_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._auto_opt = QCheckBox("Optimisation automatique selon le matériel")
        self._auto_opt.setChecked(self._cfg.get("hardware", {}).get("auto_optimize", True))
        self._auto_opt.toggled.connect(self._toggle_manual)
        form.addRow(self._auto_opt)

        self._model_combo = self._combo(WHISPER_MODELS, self._cfg.get("whisper", {}).get("model", "auto"))
        self._device_combo = self._combo(DEVICES, self._cfg.get("whisper", {}).get("device", "auto"))
        self._compute_combo = self._combo(COMPUTE_TYPES, self._cfg.get("whisper", {}).get("compute_type", "auto"))

        form.addRow("Modèle :", self._model_combo)
        form.addRow("Device :", self._device_combo)
        form.addRow("Compute type :", self._compute_combo)

        self._toggle_manual(self._auto_opt.isChecked())
        return w

    def _make_audio_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._vad_threshold = QDoubleSpinBox()
        self._vad_threshold.setRange(0.1, 0.99)
        self._vad_threshold.setSingleStep(0.05)
        self._vad_threshold.setValue(self._cfg.get("audio", {}).get("vad_threshold", 0.5))
        form.addRow("Seuil VAD :", self._vad_threshold)

        self._silence_ms = QSpinBox()
        self._silence_ms.setRange(200, 3000)
        self._silence_ms.setSingleStep(100)
        self._silence_ms.setSuffix(" ms")
        self._silence_ms.setValue(self._cfg.get("audio", {}).get("silence_duration_ms", 800))
        form.addRow("Durée silence :", self._silence_ms)

        return w

    def _make_ui_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._hotkey = QLineEdit(self._cfg.get("ui", {}).get("hotkey", "ctrl+shift+t"))
        form.addRow("Raccourci :", self._hotkey)

        self._font_size = QSpinBox()
        self._font_size.setRange(8, 24)
        self._font_size.setValue(self._cfg.get("ui", {}).get("font_size", 14))
        form.addRow("Taille police :", self._font_size)

        self._opacity = QDoubleSpinBox()
        self._opacity.setRange(0.3, 1.0)
        self._opacity.setSingleStep(0.05)
        self._opacity.setValue(self._cfg.get("ui", {}).get("opacity", 0.88))
        form.addRow("Opacité :", self._opacity)

        self._always_on_top = QCheckBox("Toujours au premier plan")
        self._always_on_top.setChecked(self._cfg.get("ui", {}).get("always_on_top", True))
        form.addRow(self._always_on_top)

        return w

    # ------------------------------------------------------------------ helpers

    def _lang_combo(self, current: str) -> QComboBox:
        cb = QComboBox()
        for code, label in COMMON_LANGS:
            cb.addItem(f"{label} ({code})", code)
        idx = next((i for i, (c, _) in enumerate(COMMON_LANGS) if c == current), 0)
        cb.setCurrentIndex(idx)
        return cb

    def _combo(self, items: list[str], current: str) -> QComboBox:
        cb = QComboBox()
        for item in items:
            cb.addItem(item)
        if current in items:
            cb.setCurrentIndex(items.index(current))
        return cb

    def _toggle_manual(self, auto: bool) -> None:
        for w in (self._model_combo, self._device_combo, self._compute_combo):
            w.setEnabled(not auto)

    def _save(self) -> None:
        from .. import config as cfg_module

        # --- Translation ---
        self._cfg.setdefault("translation", {})
        new_src = self._src_lang.currentData()
        new_tgt = self._tgt_lang.currentData()
        # Empêche source == cible (sauf auto)
        if new_src != "auto" and new_src == new_tgt:
            new_tgt = "fr" if new_src != "fr" else "en"
        self._cfg["translation"]["source_lang"] = new_src
        self._cfg["translation"]["target_lang"]  = new_tgt
        # Synchronise aussi le paramètre Whisper de détection langue
        self._cfg.setdefault("whisper", {})
        self._cfg["whisper"]["language_source"] = new_src  # "auto" ou code langue

        # --- Whisper / matériel ---
        self._cfg["whisper"]["model"]        = self._model_combo.currentText()
        self._cfg["whisper"]["device"]       = self._device_combo.currentText()
        self._cfg["whisper"]["compute_type"] = self._compute_combo.currentText()

        self._cfg.setdefault("hardware", {})
        self._cfg["hardware"]["auto_optimize"] = self._auto_opt.isChecked()

        # --- Audio ---
        self._cfg.setdefault("audio", {})
        self._cfg["audio"]["vad_threshold"]      = self._vad_threshold.value()
        self._cfg["audio"]["silence_duration_ms"] = self._silence_ms.value()

        # --- UI ---
        self._cfg.setdefault("ui", {})
        self._cfg["ui"]["hotkey"]        = self._hotkey.text()
        self._cfg["ui"]["font_size"]     = self._font_size.value()
        self._cfg["ui"]["opacity"]       = self._opacity.value()
        self._cfg["ui"]["always_on_top"] = self._always_on_top.isChecked()

        cfg_module.save(self._cfg)
        self.accept()
