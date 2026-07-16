"""
Overlay always-on-top PyQt6 — affiche le transcript en temps réel.
"""
import queue
import threading
from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint
from PyQt6.QtGui import QFont, QColor, QPalette, QMouseEvent
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QPushButton, QSizeGrip,
)

from ..translation.argos_engine import TranslationResult

SPEAKER_ICONS = {"system": "🔊", "mic": "🎤"}
SPEAKER_COLORS = {"system": "#7dd3fc", "mic": "#86efac"}  # bleu ciel / vert clair


class Overlay(QWidget):
    _new_result = pyqtSignal(object)   # TranslationResult → thread-safe UI update

    def __init__(self, config: dict):
        super().__init__()
        self._cfg = config["ui"]
        self._transcript_lines: list[str] = []
        self._drag_pos: Optional[QPoint] = None

        self._setup_window()
        self._setup_ui()

        self._new_result.connect(self._append_result)

    # ------------------------------------------------------------------ public API

    def push_result(self, result: TranslationResult) -> None:
        """Appelé depuis n'importe quel thread."""
        self._new_result.emit(result)

    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    # ------------------------------------------------------------------ Qt setup

    def _setup_window(self) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self._cfg.get("always_on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("live-transl-ai-tor")

        w = self._cfg.get("width", 520)
        h = self._cfg.get("height", 420)
        x = self._cfg.get("position_x")
        y = self._cfg.get("position_y")
        self.resize(w, h)
        if x is not None and y is not None:
            self.move(x, y)

        opacity = self._cfg.get("opacity", 0.88)
        self.setWindowOpacity(opacity)

    def _setup_ui(self) -> None:
        font_size = self._cfg.get("font_size", 14)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Conteneur principal avec fond semi-transparent
        container = QWidget()
        container.setObjectName("container")
        container.setStyleSheet("""
            QWidget#container {
                background: rgba(15, 15, 20, 220);
                border-radius: 12px;
                border: 1px solid rgba(255,255,255,0.08);
            }
        """)
        root.addWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)

        # Barre de titre draggable
        titlebar = self._make_titlebar()
        layout.addLayout(titlebar)

        # Zone de transcript défilante
        self._transcript = QTextEdit()
        self._transcript.setReadOnly(True)
        self._transcript.setStyleSheet(f"""
            QTextEdit {{
                background: transparent;
                color: #e2e8f0;
                border: none;
                font-family: 'Segoe UI', sans-serif;
                font-size: {font_size}px;
            }}
            QScrollBar:vertical {{
                background: rgba(255,255,255,0.05);
                width: 6px;
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(255,255,255,0.2);
                border-radius: 3px;
            }}
        """)
        layout.addWidget(self._transcript)

        # Zone "en cours" (dernière phrase en cours de transcription)
        self._live_label = QLabel("En attente de parole…")
        self._live_label.setStyleSheet(f"""
            color: #94a3b8;
            font-size: {max(font_size - 2, 10)}px;
            font-style: italic;
            padding: 4px 0;
        """)
        self._live_label.setWordWrap(True)
        layout.addWidget(self._live_label)

        # Prise de redimensionnement
        grip_row = QHBoxLayout()
        grip_row.addStretch()
        grip = QSizeGrip(self)
        grip.setStyleSheet("background: transparent;")
        grip_row.addWidget(grip)
        layout.addLayout(grip_row)

    def _make_titlebar(self) -> QHBoxLayout:
        row = QHBoxLayout()

        title = QLabel("live-transl<span style='color:#60a5fa'>AI</span>tor")
        title.setStyleSheet("color: #f1f5f9; font-size: 13px; font-weight: 600;")
        title.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(title)
        row.addStretch()

        for icon, tip, slot in [
            ("⚙", "Paramètres", self._open_settings),
            ("✕", "Fermer", self.hide),
        ]:
            btn = QPushButton(icon)
            btn.setToolTip(tip)
            btn.setFixedSize(24, 24)
            btn.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    color: #94a3b8;
                    border: none;
                    font-size: 14px;
                }
                QPushButton:hover { color: #f1f5f9; }
            """)
            btn.clicked.connect(slot)
            row.addWidget(btn)

        return row

    # ------------------------------------------------------------------ slots

    def _append_result(self, result: TranslationResult) -> None:
        icon = SPEAKER_ICONS.get(result.source, "●")
        color = SPEAKER_COLORS.get(result.source, "#e2e8f0")
        lang_tag = f"[{result.source_lang}→{result.target_lang}]"

        line = (
            f'<span style="color:{color}">{icon}</span> '
            f'<span style="color:#64748b;font-size:11px">{lang_tag}</span> '
            f'<span style="color:#94a3b8;font-style:italic">{result.original}</span><br>'
            f'<span style="color:#e2e8f0;font-weight:500">↳ {result.translated}</span>'
        )

        self._transcript_lines.append(line)
        max_lines = self._cfg.get("max_transcript_lines", 100)
        if len(self._transcript_lines) > max_lines:
            self._transcript_lines = self._transcript_lines[-max_lines:]

        self._transcript.setHtml("<br><br>".join(self._transcript_lines))
        # Scroll vers le bas
        sb = self._transcript.verticalScrollBar()
        sb.setValue(sb.maximum())

        self._live_label.setText("En attente de parole…")

    def set_live_text(self, text: str, source: str) -> None:
        icon = SPEAKER_ICONS.get(source, "●")
        self._live_label.setText(f"{icon} {text}")

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
