"""
Overlay always-on-top PyQt6 — interface repensée.
"""
import logging
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QFont, QMouseEvent, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QPushButton, QSizeGrip, QFrame, QGraphicsOpacityEffect,
)

from ..translation.argos_engine import TranslationResult

logger = logging.getLogger(__name__)

SPEAKER_ICONS = {"system": "♦", "mic": "●"}
# Couleurs d'accent par langue (pas de flags emoji — non supportés sur Windows/Qt)
LANG_COLORS = {
    "fr": "#60a5fa", "en": "#34d399", "es": "#fb923c", "de": "#a78bfa",
    "it": "#f472b6", "pt": "#fbbf24", "nl": "#22d3ee", "ru": "#f87171",
    "ja": "#c084fc", "zh": "#4ade80", "ko": "#38bdf8",
}

LEVEL_CHARS = " ▁▂▃▄▅▆▇█"


def _level_bar(level: float, width: int = 6) -> str:
    bars = []
    for i in range(width):
        threshold = (i + 1) / width
        idx = min(int(level / threshold * 4), 8) if level > threshold * 0.5 else 0
        bars.append(LEVEL_CHARS[idx])
    return "".join(bars)


class Overlay(QWidget):
    _new_result   = pyqtSignal(object)        # TranslationResult
    _live_signal  = pyqtSignal(str)           # set_live_text
    _level_signal = pyqtSignal(float, str)    # level, source

    def __init__(self, config: dict):
        super().__init__()
        self._cfg            = config["ui"]
        self._cfg_translation = config["translation"]
        self._config         = config
        self._transcript_lines: list[str] = []
        self._drag_pos: Optional[QPoint] = None

        # Détection mismatch langue
        self._mismatch_count = 0
        self._last_mismatch_lang: Optional[str] = None
        self._mismatch_dismissed_for: Optional[str] = None

        # Niveaux audio (thread-safe: écriture atomique float)
        self._levels = {"system": 0.0, "mic": 0.0}

        self._setup_window()
        self._setup_ui()

        self._new_result.connect(self._append_result)
        self._live_signal.connect(self._status_label.setText)
        self._level_signal.connect(self._on_level)

        # Timer niveau audio : met à jour l'indicateur toutes les 150ms
        self._level_timer = QTimer(self)
        self._level_timer.timeout.connect(self._refresh_level_display)
        self._level_timer.start(150)

    # ------------------------------------------------------------------ API publique

    def push_result(self, result: TranslationResult) -> None:
        self._new_result.emit(result)

    def set_live_text(self, text: str, source: str = "status") -> None:
        self._live_signal.emit(text)

    def set_audio_level(self, level: float, source: str) -> None:
        """Thread-safe (float assignment atomique en Python)."""
        self._levels[source] = level
        self._level_signal.emit(level, source)

    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    # ------------------------------------------------------------------ setup fenêtre

    def _setup_window(self) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self._cfg.get("always_on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("live-transl-ai-tor")

        w = self._cfg.get("width", 480)
        h = self._cfg.get("height", 400)
        x = self._cfg.get("position_x")
        y = self._cfg.get("position_y")
        self.resize(w, h)
        if x is not None and y is not None:
            self.move(x, y)
        self.setWindowOpacity(self._cfg.get("opacity", 0.93))

    # ------------------------------------------------------------------ setup UI

    def _setup_ui(self) -> None:
        font_size = self._cfg.get("font_size", 14)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._container = QWidget()
        self._container.setObjectName("container")
        self._container.setStyleSheet("""
            QWidget#container {
                background: rgba(10, 12, 18, 235);
                border-radius: 14px;
                border: 1px solid rgba(255,255,255,0.09);
            }
        """)
        root.addWidget(self._container)

        layout = QVBoxLayout(self._container)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(0)

        # ── Header ─────────────────────────────────────────────────────
        layout.addLayout(self._make_header())
        layout.addSpacing(8)

        # ── Séparateur ─────────────────────────────────────────────────
        layout.addWidget(self._hsep())

        # ── Barre de langue ─────────────────────────────────────────────
        layout.addSpacing(8)
        layout.addLayout(self._make_lang_bar())
        layout.addSpacing(8)

        # ── Notification mismatch (cachée par défaut) ───────────────────
        self._mismatch_widget = self._make_mismatch_bar()
        self._mismatch_widget.hide()
        layout.addWidget(self._mismatch_widget)
        layout.addSpacing(2)

        # ── Zone transcript ─────────────────────────────────────────────
        layout.addWidget(self._hsep())
        layout.addSpacing(6)

        self._transcript = QTextEdit()
        self._transcript.setReadOnly(True)
        self._transcript.setStyleSheet(f"""
            QTextEdit {{
                background: transparent;
                color: #e2e8f0;
                border: none;
                font-family: 'Segoe UI', 'Arial', sans-serif;
                font-size: {font_size}px;
                padding: 0px 2px;
                selection-background-color: rgba(96,165,250,0.3);
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 4px;
                margin: 4px 0;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(255,255,255,0.15);
                border-radius: 2px;
                min-height: 16px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)
        layout.addWidget(self._transcript, 1)

        layout.addSpacing(6)
        layout.addWidget(self._hsep())
        layout.addSpacing(6)

        # ── Status bar ──────────────────────────────────────────────────
        status_row = QHBoxLayout()
        status_row.setSpacing(6)

        self._level_label = QLabel("")
        self._level_label.setStyleSheet("""
            color: #334155;
            font-size: 10px;
            font-family: monospace;
            letter-spacing: 1px;
        """)
        status_row.addWidget(self._level_label)

        self._status_label = QLabel("⏳ Initialisation…")
        self._status_label.setStyleSheet(f"""
            color: #475569;
            font-size: {max(font_size - 3, 10)}px;
            font-style: italic;
        """)
        self._status_label.setWordWrap(True)
        status_row.addWidget(self._status_label, 1)

        grip = QSizeGrip(self)
        grip.setStyleSheet("background: transparent;")
        status_row.addWidget(grip)
        layout.addLayout(status_row)

    def _make_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)

        title = QLabel("live-transl<span style='color:#60a5fa;font-weight:800'>AI</span>tor")
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setStyleSheet("""
            color: #94a3b8;
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 0.5px;
        """)
        row.addWidget(title)
        row.addStretch()

        for icon, tip, slot in [
            ("⚙", "Paramètres", self._open_settings),
            ("✕", "Fermer", self.hide),
        ]:
            btn = QPushButton(icon)
            btn.setToolTip(tip)
            btn.setFixedSize(22, 22)
            btn.setStyleSheet("""
                QPushButton {
                    background: rgba(255,255,255,0.05);
                    color: #475569;
                    border: 1px solid rgba(255,255,255,0.07);
                    border-radius: 5px;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background: rgba(255,255,255,0.10);
                    color: #cbd5e1;
                    border-color: rgba(255,255,255,0.15);
                }
            """)
            btn.clicked.connect(slot)
            row.addWidget(btn)

        return row

    def _make_lang_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        src = self._cfg_translation.get("source_lang", "auto")
        tgt = self._cfg_translation.get("target_lang", "fr")

        self._src_btn = self._lang_button(src)
        self._tgt_btn = self._lang_button(tgt)

        arrow = QLabel("→")
        arrow.setStyleSheet("color: #334155; font-size: 15px; font-weight: 300;")
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)

        row.addStretch()
        row.addWidget(self._src_btn)
        row.addWidget(arrow)
        row.addWidget(self._tgt_btn)
        row.addStretch()

        self._src_btn.clicked.connect(self._open_settings)
        self._tgt_btn.clicked.connect(self._open_settings)

        return row

    def _lang_button(self, lang: str) -> QPushButton:
        label = "AUTO" if lang == "auto" else lang.upper()
        color = LANG_COLORS.get(lang, "#7dd3fc")
        btn = QPushButton(label)
        btn.setFixedHeight(30)
        btn.setMinimumWidth(72)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(15, 23, 42, 0.9);
                color: {color};
                border: 1px solid {color}44;
                border-radius: 8px;
                padding: 0 16px;
                font-size: 13px;
                font-weight: 800;
                letter-spacing: 2px;
            }}
            QPushButton:hover {{
                background: {color}22;
                border-color: {color}88;
            }}
        """)
        return btn

    def _make_mismatch_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("mismatch")
        bar.setStyleSheet("""
            QWidget#mismatch {
                background: rgba(245, 158, 11, 0.10);
                border: 1px solid rgba(245, 158, 11, 0.28);
                border-radius: 9px;
            }
        """)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 7, 8, 7)
        layout.setSpacing(8)

        self._mismatch_label = QLabel()
        self._mismatch_label.setStyleSheet("""
            color: #fbbf24;
            font-size: 11px;
            background: transparent;
            border: none;
        """)
        self._mismatch_label.setWordWrap(True)
        layout.addWidget(self._mismatch_label, 1)

        switch_btn = QPushButton("Switcher")
        switch_btn.setFixedSize(68, 24)
        switch_btn.setStyleSheet("""
            QPushButton {
                background: rgba(245,158,11,0.18);
                color: #fbbf24;
                border: 1px solid rgba(245,158,11,0.38);
                border-radius: 6px;
                font-size: 11px;
                font-weight: 700;
            }
            QPushButton:hover { background: rgba(245,158,11,0.30); color: #fde68a; }
        """)
        switch_btn.clicked.connect(self._do_switch_lang)
        layout.addWidget(switch_btn)

        dismiss = QPushButton("✕")
        dismiss.setFixedSize(20, 20)
        dismiss.setStyleSheet("""
            QPushButton { background: transparent; color: #78716c; border: none; font-size: 10px; }
            QPushButton:hover { color: #fbbf24; }
        """)
        dismiss.clicked.connect(self._dismiss_mismatch)
        layout.addWidget(dismiss)

        return bar

    def _hsep(self) -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: rgba(255,255,255,0.06); max-height: 1px;")
        return sep

    # ------------------------------------------------------------------ slots

    def _append_result(self, result: TranslationResult) -> None:
        # Détection mismatch langue
        configured_src = self._cfg_translation.get("source_lang", "auto")
        if (configured_src != "auto"
                and result.source_lang != configured_src
                and result.whisper_confidence > 0.65):
            self._mismatch_count += 1
            if (self._mismatch_count >= 2
                    and result.source_lang != self._mismatch_dismissed_for):
                self._show_mismatch(result.source_lang, configured_src)
        else:
            self._mismatch_count = 0

        # Rendu HTML du résultat
        icon = SPEAKER_ICONS.get(result.source, "●")
        src_col = LANG_COLORS.get(result.source_lang, "#7dd3fc")
        tgt_col = LANG_COLORS.get(result.target_lang, "#7dd3fc")
        is_same = result.source_lang == result.target_lang

        if is_same:
            line = (
                f'<div style="margin:0 0 12px 0">'
                f'<span style="color:#334155;font-size:10px">'
                f'{icon} <span style="color:{src_col}">{result.source_lang.upper()}</span>'
                f'</span><br>'
                f'<span style="color:#cbd5e1">{result.original}</span>'
                f'</div>'
            )
        else:
            line = (
                f'<div style="margin:0 0 12px 0">'
                f'<span style="color:#334155;font-size:10px">'
                f'{icon} <span style="color:{src_col}">{result.source_lang.upper()}</span>'
                f' → <span style="color:{tgt_col}">{result.target_lang.upper()}</span>'
                f'</span><br>'
                f'<span style="color:#64748b;font-style:italic">{result.original}</span><br>'
                f'<span style="color:#e2e8f0;font-weight:600">↳ {result.translated}</span>'
                f'</div>'
            )

        self._transcript_lines.append(line)
        max_lines = self._cfg.get("max_transcript_lines", 100)
        if len(self._transcript_lines) > max_lines:
            self._transcript_lines = self._transcript_lines[-max_lines:]

        self._transcript.setHtml("".join(self._transcript_lines))
        sb = self._transcript.verticalScrollBar()
        sb.setValue(sb.maximum())

        self._status_label.setText("⏳ En attente de parole…")

    def _show_mismatch(self, detected: str, configured: str) -> None:
        if self._last_mismatch_lang == detected:
            return
        self._last_mismatch_lang = detected
        self._pending_mismatch = (detected, configured)
        self._mismatch_label.setText(
            f"Langue détectée : {detected.upper()} "
            f"(source config : {configured.upper()}) — changer ?"
        )
        self._mismatch_widget.show()

    def _do_switch_lang(self) -> None:
        if not hasattr(self, "_pending_mismatch"):
            return
        detected, configured = self._pending_mismatch
        current_tgt = self._cfg_translation.get("target_lang", "fr")

        # Choisit new_src/new_tgt en évitant source == target
        if detected == current_tgt:
            # Swap : la détection coïncide avec la cible → on inverse
            new_src, new_tgt = detected, configured
        else:
            new_src, new_tgt = detected, current_tgt

        # Sécurité : ne jamais laisser source == target
        if new_src == new_tgt:
            logger.warning("Switch annulé : source == target == %s", new_src)
            self._dismiss_mismatch()
            return

        self._cfg_translation["source_lang"] = new_src
        self._cfg_translation["target_lang"] = new_tgt

        self._src_btn.setText("AUTO" if new_src == "auto" else new_src.upper())
        self._tgt_btn.setText(new_tgt.upper())

        try:
            from .. import config as cfg_module
            cfg = cfg_module.load()
            cfg["translation"]["source_lang"] = new_src
            cfg["translation"]["target_lang"] = new_tgt
            cfg_module.save(cfg)
            logger.info("Langue switchée : %s → %s", new_src, new_tgt)
        except Exception as e:
            logger.warning("Impossible de sauvegarder la config langue : %s", e)

        self._dismiss_mismatch()

    def _dismiss_mismatch(self) -> None:
        if hasattr(self, "_pending_mismatch"):
            detected, _ = self._pending_mismatch
            self._mismatch_dismissed_for = detected
        self._mismatch_widget.hide()
        self._mismatch_count = 0

    def _on_level(self, level: float, source: str) -> None:
        self._levels[source] = level

    def _refresh_level_display(self) -> None:
        mic = self._levels.get("mic", 0.0)
        sys = self._levels.get("system", 0.0)
        mic_bar = _level_bar(min(mic * 12, 1.0), 5)
        sys_bar = _level_bar(min(sys * 12, 1.0), 5)
        self._level_label.setText(f"🎤{mic_bar}  🔊{sys_bar}")

    def _open_settings(self) -> None:
        from .settings_window import SettingsWindow
        win = SettingsWindow(self._cfg, parent=self)
        win.exec()

    # ------------------------------------------------------------------ drag

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_pos = None
