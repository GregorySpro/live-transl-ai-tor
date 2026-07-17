"""
Overlay always-on-top — design professionnel avec traduction temps réel.

Architecture visuelle :
  ┌───────────────────────────────────────────────┐
  │  live-translAItor          [EN] → [FR]  ⚙  ✕ │  ← header 40px
  ├───────────────────────────────────────────────┤
  │  original text (muted italic)                 │
  │  ↳ translation (bright white)                 │  ← historique scrollable
  │                                               │
  ├─ ● ───────────────────────────────────────────┤  ← séparateur live (vert)
  │  parole en cours...          (live preview)   │  ← zone live 90px
  │  ↳ traduction partielle...                    │
  │                     mic ▁▂  sys ▁▁         🔲 │
  └───────────────────────────────────────────────┘
"""
import logging
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QPushButton, QSizeGrip, QFrame,
)

from ..translation.argos_engine import TranslationResult

logger = logging.getLogger(__name__)

# ── Palette ───────────────────────────────────────────────────────────────────
LANG_COLORS = {
    "fr": "#818cf8",   # indigo
    "en": "#34d399",   # emerald
    "es": "#fb923c",   # orange
    "de": "#a78bfa",   # violet
    "it": "#f472b6",   # pink
    "pt": "#fbbf24",   # amber
    "nl": "#22d3ee",   # cyan
    "ru": "#f87171",   # red
    "ja": "#c084fc",   # purple
    "zh": "#4ade80",   # green
    "ko": "#38bdf8",   # sky
}
SPEAKER_ICONS = {"system": "♦", "mic": "●"}

# Couleurs du dot live
_DOT_IDLE = ("◦", "#1e3a29")
_DOT_A    = ("●", "#22c55e")
_DOT_B    = ("●", "#15803d")

# Couleurs du texte
_C_SRC    = "#475569"    # texte original dans l'historique (ardoise muet)
_C_TRAD   = "#f1f5f9"    # traduction dans l'historique (blanc cassé)
_C_LABEL  = "#2d3748"    # métadonnées langue (très sombre)
_C_LIVE_SRC  = "#64748b" # source dans la zone live
_C_LIVE_TRAD = "#d1fae5" # traduction live (teinte verte)


class Overlay(QWidget):
    _new_result     = pyqtSignal(object)   # TranslationResult final
    _preview_signal = pyqtSignal(object)   # TranslationResult preview
    _live_signal    = pyqtSignal(str)      # message statut système
    _level_signal   = pyqtSignal(float, str)

    def __init__(self, config: dict):
        super().__init__()
        self._cfg             = config["ui"]
        self._cfg_translation = config["translation"]
        self._config          = config

        self._transcript_lines: list[str] = []
        self._drag_pos: Optional[QPoint]  = None

        self._mismatch_count            = 0
        self._last_mismatch_lang: Optional[str] = None
        self._mismatch_dismissed_for: Optional[str] = None

        self._levels    = {"system": 0.0, "mic": 0.0}
        self._dot_phase = 0
        self._is_speaking = False   # assignation atomique — pas de verrou nécessaire

        self._setup_window()
        self._setup_ui()

        self._new_result.connect(self._on_final)
        self._preview_signal.connect(self._on_preview)
        self._live_signal.connect(self._on_status)
        self._level_signal.connect(self._on_level)

        # Pulsation du dot toutes les 500ms
        self._dot_timer = QTimer(self)
        self._dot_timer.timeout.connect(self._pulse_dot)
        self._dot_timer.start(500)

        # Rafraîchissement du niveau audio toutes les 120ms
        self._level_timer = QTimer(self)
        self._level_timer.timeout.connect(self._refresh_levels)
        self._level_timer.start(120)

    # ─────────────────────────────────────────────────────── API publique ──────

    def push_result(self, result: TranslationResult) -> None:
        """Thread-safe — route preview → zone live, final → historique."""
        if getattr(result, "is_preview", False):
            self._preview_signal.emit(result)
        else:
            self._new_result.emit(result)

    def set_live_text(self, text: str, source: str = "status") -> None:
        """Thread-safe — met à jour le statut (messages système)."""
        self._live_signal.emit(text)

    def set_audio_level(self, level: float, source: str) -> None:
        self._levels[source] = level
        self._level_signal.emit(level, source)

    def set_speaking(self, is_speaking: bool) -> None:
        """Appelé depuis le thread VAD — assignation atomique Python."""
        self._is_speaking = is_speaking

    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    # ───────────────────────────────────────────────────── Fenêtre ───────────

    def _setup_window(self) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self._cfg.get("always_on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("live-transl-ai-tor")

        w = self._cfg.get("width", 560)
        h = self._cfg.get("height", 380)
        x = self._cfg.get("position_x")
        y = self._cfg.get("position_y")
        self.resize(w, h)
        if x is not None and y is not None:
            self.move(x, y)
        self.setWindowOpacity(self._cfg.get("opacity", 0.95))

    # ─────────────────────────────────────────────────────────── UI ──────────

    def _setup_ui(self) -> None:
        fs = self._cfg.get("font_size", 14)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Container principal
        container = QWidget()
        container.setObjectName("ctn")
        container.setStyleSheet("""
            QWidget#ctn {
                background: rgba(7, 9, 14, 250);
                border-radius: 14px;
                border: 1px solid rgba(255,255,255,0.07);
            }
        """)
        root.addWidget(container)

        cl = QVBoxLayout(container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────
        cl.addWidget(self._make_header())

        # ── Séparateur header/transcript ──────────────────────────────
        cl.addWidget(self._hsep("rgba(255,255,255,0.055)"))

        # ── Historique transcript ─────────────────────────────────────
        self._transcript = QTextEdit()
        self._transcript.setReadOnly(True)
        self._transcript.setStyleSheet(f"""
            QTextEdit {{
                background: transparent;
                color: {_C_TRAD};
                border: none;
                font-family: 'Segoe UI', 'Inter', 'Arial', sans-serif;
                font-size: {fs}px;
                padding: 14px 18px 6px 18px;
                line-height: 1.5;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 4px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(255,255,255,0.09);
                border-radius: 2px;
                min-height: 20px;
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{ height: 0; }}
        """)
        cl.addWidget(self._transcript, 1)

        # ── Barre mismatch (cachée par défaut) ────────────────────────
        self._mismatch_widget = self._make_mismatch_bar()
        self._mismatch_widget.hide()
        cl.addWidget(self._mismatch_widget)

        # ── Zone live ─────────────────────────────────────────────────
        cl.addWidget(self._make_live_zone(fs))

    def _make_header(self) -> QWidget:
        hdr = QWidget()
        hdr.setObjectName("hdr")
        hdr.setStyleSheet("""
            QWidget#hdr {
                background: rgba(255,255,255,0.02);
                border-radius: 13px 13px 0 0;
            }
        """)
        hdr.setFixedHeight(42)
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(16, 0, 12, 0)
        hl.setSpacing(6)

        # Logo
        title = QLabel("live-transl<span style='color:#60a5fa;font-weight:800'>AI</span>tor")
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setStyleSheet(
            "color:#334155;font-size:11px;font-weight:600;"
            "letter-spacing:0.4px;background:transparent;"
        )
        hl.addWidget(title)
        hl.addSpacing(10)

        # Paire de langues dans le header
        src = self._cfg_translation.get("source_lang", "auto")
        tgt = self._cfg_translation.get("target_lang", "fr")
        self._src_btn = self._make_lang_btn(src)
        self._tgt_btn = self._make_lang_btn(tgt)
        arr = QLabel("→")
        arr.setStyleSheet(
            "color:#1e293b;font-size:13px;font-weight:300;background:transparent;"
        )
        hl.addWidget(self._src_btn)
        hl.addWidget(arr)
        hl.addWidget(self._tgt_btn)
        self._src_btn.clicked.connect(self._open_settings)
        self._tgt_btn.clicked.connect(self._open_settings)

        hl.addStretch()

        # Boutons ⚙ ✕
        for ico, tip, cb in [("⚙", "Paramètres", self._open_settings),
                              ("✕", "Fermer", self.hide)]:
            b = QPushButton(ico)
            b.setFixedSize(24, 24)
            b.setToolTip(tip)
            b.setStyleSheet("""
                QPushButton {
                    background: transparent;
                    color: #27374d;
                    border: none;
                    border-radius: 5px;
                    font-size: 12px;
                }
                QPushButton:hover {
                    color: #94a3b8;
                    background: rgba(255,255,255,0.06);
                }
            """)
            b.clicked.connect(cb)
            hl.addWidget(b)

        return hdr

    def _make_lang_btn(self, lang: str) -> QPushButton:
        label = "AUTO" if lang == "auto" else lang.upper()
        color = LANG_COLORS.get(lang, "#7dd3fc")
        b = QPushButton(label)
        b.setFixedHeight(24)
        b.setMinimumWidth(54)
        b.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {color};
                border: 1px solid {color}2a;
                border-radius: 5px;
                padding: 0 10px;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 1.5px;
            }}
            QPushButton:hover {{
                background: {color}14;
                border-color: {color}55;
            }}
        """)
        return b

    def _make_live_zone(self, fs: int) -> QWidget:
        live = QWidget()
        live.setObjectName("live")
        live.setFixedHeight(96)
        live.setStyleSheet("""
            QWidget#live {
                background: rgba(5, 10, 8, 0.55);
                border-radius: 0 0 13px 13px;
                border-top: 1px solid rgba(34,197,94,0.15);
            }
        """)
        ll = QVBoxLayout(live)
        ll.setContentsMargins(16, 8, 12, 6)
        ll.setSpacing(3)

        # Ligne indicateur : dot + ligne colorée
        ind = QHBoxLayout()
        ind.setSpacing(8)
        self._dot_label = QLabel("◦")
        self._dot_label.setStyleSheet(
            f"color:{_DOT_IDLE[1]};font-size:9px;background:transparent;"
        )
        self._dot_label.setFixedWidth(10)
        ind.addWidget(self._dot_label)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: rgba(34,197,94,0.18); border: none;")
        ind.addWidget(sep, 1)
        ll.addLayout(ind)

        # Texte source live
        self._live_src = QLabel("En écoute…")
        self._live_src.setStyleSheet(f"""
            color: {_C_LIVE_SRC};
            font-size: {fs - 1}px;
            font-style: italic;
            background: transparent;
        """)
        self._live_src.setWordWrap(True)
        ll.addWidget(self._live_src)

        # Traduction live
        self._live_trad = QLabel("")
        self._live_trad.setStyleSheet(f"""
            color: {_C_LIVE_TRAD};
            font-size: {fs}px;
            font-weight: 500;
            background: transparent;
            padding-left: 14px;
        """)
        self._live_trad.setWordWrap(True)
        self._live_trad.hide()
        ll.addWidget(self._live_trad)

        ll.addStretch()

        # Pied : niveaux + resize grip
        foot = QHBoxLayout()
        foot.setSpacing(0)
        self._level_label = QLabel("")
        self._level_label.setStyleSheet(
            "color:#1a2e1a;font-size:9px;font-family:monospace;background:transparent;"
        )
        foot.addWidget(self._level_label)
        foot.addStretch()
        grip = QSizeGrip(self)
        grip.setStyleSheet("background:transparent;")
        foot.addWidget(grip)
        ll.addLayout(foot)

        return live

    def _make_mismatch_bar(self) -> QWidget:
        w = QWidget()
        w.setObjectName("mm")
        w.setStyleSheet("""
            QWidget#mm {
                background: rgba(245,158,11,0.07);
                border-top: 1px solid rgba(245,158,11,0.18);
            }
        """)
        l = QHBoxLayout(w)
        l.setContentsMargins(16, 6, 10, 6)
        l.setSpacing(8)

        self._mismatch_label = QLabel()
        self._mismatch_label.setStyleSheet(
            "color:#d97706;font-size:11px;background:transparent;border:none;"
        )
        self._mismatch_label.setWordWrap(True)
        l.addWidget(self._mismatch_label, 1)

        sw = QPushButton("Switcher")
        sw.setFixedHeight(22)
        sw.setMinimumWidth(60)
        sw.setStyleSheet("""
            QPushButton {
                background: rgba(245,158,11,0.12);
                color: #d97706;
                border: 1px solid rgba(245,158,11,0.28);
                border-radius: 5px;
                font-size: 11px;
                font-weight: 600;
                padding: 0 10px;
            }
            QPushButton:hover { background: rgba(245,158,11,0.22); }
        """)
        sw.clicked.connect(self._do_switch_lang)
        l.addWidget(sw)

        dm = QPushButton("✕")
        dm.setFixedSize(20, 20)
        dm.setStyleSheet("""
            QPushButton { background:transparent; color:#78716c; border:none; font-size:11px; }
            QPushButton:hover { color:#d97706; }
        """)
        dm.clicked.connect(self._dismiss_mismatch)
        l.addWidget(dm)

        return w

    def _hsep(self, color: str = "rgba(255,255,255,0.06)") -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {color}; border: none;")
        return sep

    # ──────────────────────────────────────────────────────────── Slots ──────

    def _on_final(self, result: TranslationResult) -> None:
        # Détection mismatch
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

        # Bloc HTML pour l'historique
        icon    = SPEAKER_ICONS.get(result.source, "●")
        sc      = LANG_COLORS.get(result.source_lang, "#7dd3fc")
        tc      = LANG_COLORS.get(result.target_lang, "#7dd3fc")
        is_same = result.source_lang == result.target_lang

        if is_same:
            block = (
                f'<div style="margin:0 0 16px 0">'
                f'<div style="color:{_C_LABEL};font-size:10px;margin-bottom:3px">'
                f'{icon} <span style="color:{sc}">{result.source_lang.upper()}</span>'
                f'</div>'
                f'<div style="color:{_C_TRAD};line-height:1.5">{result.original}</div>'
                f'</div>'
            )
        else:
            block = (
                f'<div style="margin:0 0 16px 0">'
                f'<div style="color:{_C_LABEL};font-size:10px;margin-bottom:3px">'
                f'{icon} <span style="color:{sc}">{result.source_lang.upper()}</span>'
                f' → <span style="color:{tc}">{result.target_lang.upper()}</span>'
                f'</div>'
                f'<div style="color:{_C_SRC};font-style:italic;line-height:1.5">'
                f'{result.original}</div>'
                f'<div style="color:{_C_TRAD};font-weight:600;line-height:1.5;margin-top:3px">'
                f'↳ {result.translated}</div>'
                f'</div>'
            )

        self._transcript_lines.append(block)
        max_l = self._cfg.get("max_transcript_lines", 100)
        if len(self._transcript_lines) > max_l:
            self._transcript_lines = self._transcript_lines[-max_l:]
        self._transcript.setHtml("".join(self._transcript_lines))
        sb = self._transcript.verticalScrollBar()
        sb.setValue(sb.maximum())

        # Nettoie la zone live
        self._clear_live()

    def _on_preview(self, result: TranslationResult) -> None:
        self._is_speaking = True
        self._live_src.setText(result.original)
        if result.source_lang != result.target_lang and result.translated:
            self._live_trad.setText(f"↳ {result.translated}")
            self._live_trad.show()
        else:
            self._live_trad.hide()

    def _on_status(self, text: str) -> None:
        if not self._is_speaking:
            self._live_src.setText(text)
            self._live_trad.hide()

    def _on_level(self, level: float, source: str) -> None:
        self._levels[source] = level

    def _clear_live(self) -> None:
        self._is_speaking = False
        self._live_src.setText("En écoute…")
        self._live_trad.hide()
        self._live_trad.setText("")

    def _pulse_dot(self) -> None:
        self._dot_phase = (self._dot_phase + 1) % 4
        if self._is_speaking:
            char, col = _DOT_A if self._dot_phase % 2 == 0 else _DOT_B
        else:
            char, col = _DOT_IDLE
        self._dot_label.setText(char)
        self._dot_label.setStyleSheet(
            f"color:{col};font-size:9px;background:transparent;"
        )

    def _refresh_levels(self) -> None:
        mic = self._levels.get("mic", 0.0)
        sys = self._levels.get("system", 0.0)

        def bar(v: float, n: int = 5) -> str:
            blocks = " ▁▂▃▄▅▆▇█"
            filled = max(0, min(n, round(v * n * 10)))
            return "".join(blocks[min(8, max(0, filled - i))] for i in range(n - 1, -1, -1))

        self._level_label.setText(f"mic {bar(mic)}  sys {bar(sys)}")

    # ──────────────────────────────────────────────────────── Mismatch ────────

    def _show_mismatch(self, detected: str, configured: str) -> None:
        if self._last_mismatch_lang == detected:
            return
        self._last_mismatch_lang = detected
        self._pending_mismatch   = (detected, configured)
        dc = LANG_COLORS.get(detected, "#fbbf24")
        self._mismatch_label.setText(
            f"Langue détectée : <b style='color:{dc}'>{detected.upper()}</b> "
            f"(source actuelle : {configured.upper()}) — changer ?"
        )
        self._mismatch_label.setTextFormat(Qt.TextFormat.RichText)
        self._mismatch_widget.show()

    def _do_switch_lang(self) -> None:
        if not hasattr(self, "_pending_mismatch"):
            return
        detected, configured = self._pending_mismatch
        current_tgt = self._cfg_translation.get("target_lang", "fr")
        new_src     = detected
        new_tgt     = configured if detected == current_tgt else current_tgt
        if new_src == new_tgt:
            self._dismiss_mismatch()
            return
        self._cfg_translation["source_lang"] = new_src
        self._cfg_translation["target_lang"] = new_tgt
        self._update_lang_display(new_src, new_tgt)
        try:
            from .. import config as cfg_module
            cfg = cfg_module.load()
            cfg["translation"]["source_lang"] = new_src
            cfg["translation"]["target_lang"] = new_tgt
            cfg_module.save(cfg)
            logger.info("Langue switchée : %s → %s", new_src, new_tgt)
        except Exception as e:
            logger.warning("Impossible de sauvegarder la config : %s", e)
        self._dismiss_mismatch()

    def _dismiss_mismatch(self) -> None:
        if hasattr(self, "_pending_mismatch"):
            self._mismatch_dismissed_for = self._pending_mismatch[0]
        self._mismatch_widget.hide()
        self._mismatch_count = 0

    def _update_lang_display(self, src: str, tgt: str) -> None:
        self._src_btn.setText("AUTO" if src == "auto" else src.upper())
        self._tgt_btn.setText(tgt.upper())
        self._src_btn.setStyleSheet(
            self._lang_btn_css(LANG_COLORS.get(src, "#7dd3fc"))
        )
        self._tgt_btn.setStyleSheet(
            self._lang_btn_css(LANG_COLORS.get(tgt, "#7dd3fc"))
        )

    def _lang_btn_css(self, color: str) -> str:
        return f"""
            QPushButton {{
                background: transparent;
                color: {color};
                border: 1px solid {color}2a;
                border-radius: 5px;
                padding: 0 10px;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 1.5px;
            }}
            QPushButton:hover {{
                background: {color}14;
                border-color: {color}55;
            }}
        """

    def _open_settings(self) -> None:
        from .settings_window import SettingsWindow
        win = SettingsWindow(self._cfg, parent=self)
        win.exec()

    # ─────────────────────────────────────────────────────────── Drag ────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_pos = None
