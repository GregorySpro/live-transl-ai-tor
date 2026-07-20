"""
Overlay always-on-top — thème clair, professionnel, lisible.

Architecture visuelle :
  ┌──────────────────────────────────────────────────────┐
  │  translAI·tor        [FR] → [EN]               ⚙  ✕  │  ← header 36px
  ├──────────────────────────────────────────────────────┤
  │  source originale, italique discret                  │
  │  ↳ Traduction lisible, texte principal               │  ← historique scrollable
  │                                                      │
  ├▌─────────────────────────────────────────────────────┤  ← live zone (bordure gauche animée)
  │  ce que je dis…                               MIC   │
  │  ↳ traduction en cours…                             │
  │  [████░░░░░░░░░░░░░]  mic 0.0124               ↘   │
  └──────────────────────────────────────────────────────┘
"""
import logging
import math
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QPushButton, QSizeGrip, QFrame, QProgressBar,
)

from ..translation.argos_engine import TranslationResult

logger = logging.getLogger(__name__)

# ── Palette claire ────────────────────────────────────────────────────────────
LANG_COLORS = {
    "fr": "#6366f1",   # indigo (assombri pour fond clair)
    "en": "#059669",   # emerald foncé
    "es": "#ea580c",   # orange foncé
    "de": "#7c3aed",   # violet foncé
    "it": "#db2777",   # pink foncé
    "pt": "#d97706",   # amber foncé
    "nl": "#0891b2",   # cyan foncé
    "ru": "#dc2626",   # red foncé
    "ja": "#9333ea",   # purple foncé
    "zh": "#16a34a",   # green foncé
    "ko": "#0284c7",   # sky foncé
}
SPEAKER_ICONS = {"system": "♦", "mic": "●"}

_BG         = "#f4f6fb"   # fond principal — blanc bleuté très doux
_BG_SURF    = "#ffffff"   # header — blanc pur
_BG_LIVE    = "#edf1f8"   # live zone — légèrement grisé
_BORDER     = "#d8e0ed"   # bordures — gris bleuté
_TEXT       = "#1a2035"   # texte primaire — quasi-noir froid
_TEXT_MED   = "#546a85"   # texte secondaire
_TEXT_MUTED = "#97adc6"   # très discret
_ACCENT     = "#2563eb"   # bleu (brand, action)
_LIVE_ON    = "#16a34a"   # vert foncé (speaking, lisible sur fond clair)
_LIVE_DIM   = "#c8e6d0"   # vert très pâle (idle border)
_AMBER      = "#b45309"   # amber foncé (warning lisible sur fond clair)

# Template CSS de la barre d'accent gauche (widget séparé, pas de border-radius)
# Qt crashe si on mélange border-radius avec des largeurs de bordure différentes.
_ACCENT_CSS = "background: {color}; border: none;"


def _common_prefix_len(a: str, b: str) -> int:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n


class Overlay(QWidget):
    _new_result     = pyqtSignal(object)
    _preview_signal = pyqtSignal(object)
    _live_signal    = pyqtSignal(str)
    _level_signal   = pyqtSignal(float, str)

    def __init__(self, config: dict):
        super().__init__()
        self._cfg             = config["ui"]
        self._cfg_translation = config["translation"]
        self._config          = config

        self._transcript_lines: list[str] = []
        self._drag_pos: Optional[QPoint]  = None

        self._mismatch_count                    = 0
        self._last_mismatch_lang: Optional[str] = None
        self._mismatch_dismissed_for: Optional[str] = None
        self._pending_mismatch: Optional[tuple] = None

        self._levels      = {"system": 0.0, "mic": 0.0}
        self._dot_phase   = 0
        self._is_speaking = False
        self._tw_target_src:  str = ""
        self._tw_target_trad: str = ""
        self._tw_pos_src:     int = 0
        self._tw_pos_trad:    int = 0

        # Doit être initialisé AVANT _setup_window() car resize() dans _setup_window
        # déclenche resizeEvent qui accède à ce timer dès la construction.
        self._geo_save_timer = QTimer(self)
        self._geo_save_timer.setSingleShot(True)
        self._geo_save_timer.timeout.connect(self._save_geometry)

        self._setup_window()
        self._setup_ui()

        self._new_result.connect(self._on_final)
        self._preview_signal.connect(self._on_preview)
        self._live_signal.connect(self._on_status)
        self._level_signal.connect(self._on_level)

        self._dot_timer = QTimer(self)
        self._dot_timer.timeout.connect(self._pulse_dot)
        self._dot_timer.start(500)

        self._typewriter_timer = QTimer(self)
        self._typewriter_timer.timeout.connect(self._typewriter_tick)

        self._level_timer = QTimer(self)
        self._level_timer.timeout.connect(self._refresh_levels)
        self._level_timer.start(120)


    # ─────────────────────────────────────────────────────── API publique ──────

    def push_result(self, result: TranslationResult) -> None:
        if getattr(result, "is_preview", False):
            self._preview_signal.emit(result)
        else:
            self._new_result.emit(result)

    def set_live_text(self, text: str, source: str = "status") -> None:
        self._live_signal.emit(text)

    def set_audio_level(self, level: float, source: str) -> None:
        self._levels[source] = level
        self._level_signal.emit(level, source)

    def set_speaking(self, is_speaking: bool) -> None:
        self._is_speaking = is_speaking

    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    # ─────────────────────────────────────────────────────── Fenêtre ─────────

    def _setup_window(self) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self._cfg.get("always_on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("live-transl-ai-tor")

        w = self._cfg.get("width", 560)
        h = self._cfg.get("height", 400)
        x = self._cfg.get("position_x")
        y = self._cfg.get("position_y")
        self.setMinimumSize(340, 200)
        self.resize(w, h)
        if x is not None and y is not None:
            self.move(x, y)
        self.setWindowOpacity(1.0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._cfg["width"]  = event.size().width()
        self._cfg["height"] = event.size().height()
        self._geo_save_timer.start(1000)

    # ───────────────────────────────────────────────────────────── UI ─────────

    def _setup_ui(self) -> None:
        fs = self._cfg.get("font_size", 14)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        container = QWidget()
        container.setObjectName("ctn")
        container.setStyleSheet(f"""
            QWidget#ctn {{
                background: {_BG};
                border-radius: 10px;
                border: 1px solid {_BORDER};
            }}
        """)
        root.addWidget(container)

        cl = QVBoxLayout(container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        cl.addWidget(self._make_header())
        # QFrame séparateur (pas sur un widget avec border-radius — ici c'est safe)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {_BORDER}; border: none;")
        cl.addWidget(sep)

        self._transcript = QTextEdit()
        self._transcript.setReadOnly(True)
        self._transcript.setStyleSheet(f"""
            QTextEdit {{
                background: transparent;
                color: {_TEXT};
                border: none;
                font-family: 'Segoe UI', system-ui, sans-serif;
                font-size: {fs}px;
                padding: 16px 18px 8px 18px;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 4px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {_BORDER};
                border-radius: 2px;
                min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {_TEXT_MUTED};
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{ height: 0; }}
        """)
        cl.addWidget(self._transcript, 1)

        self._mismatch_widget = self._make_mismatch_bar()
        self._mismatch_widget.hide()
        cl.addWidget(self._mismatch_widget)

        live_sep = QFrame()
        live_sep.setFrameShape(QFrame.Shape.HLine)
        live_sep.setFixedHeight(1)
        live_sep.setStyleSheet(f"background: {_BORDER}; border: none;")
        cl.addWidget(live_sep)

        cl.addWidget(self._make_live_zone(fs))

    def _make_header(self) -> QWidget:
        hdr = QWidget()
        hdr.setObjectName("hdr")
        # Pas de border-bottom ici : Qt crashe avec border-radius + bordures non uniformes.
        # Le séparateur visuel est assuré par le QFrame ajouté dans _setup_ui.
        hdr.setStyleSheet(f"""
            QWidget#hdr {{
                background: {_BG_SURF};
                border-radius: 10px 10px 0 0;
            }}
        """)
        hdr.setFixedHeight(36)
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(14, 0, 10, 0)
        hl.setSpacing(5)

        title = QLabel(
            f"transl<span style='color:{_ACCENT};font-weight:700'>AI</span>"
            f"<span style='color:{_TEXT_MUTED};'>·tor</span>"
        )
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setStyleSheet(
            f"color:{_TEXT_MUTED};font-size:10px;font-weight:500;"
            "letter-spacing:0.2px;background:transparent;"
        )
        hl.addWidget(title)
        hl.addSpacing(10)

        src = self._cfg_translation.get("source_lang", "auto")
        tgt = self._cfg_translation.get("target_lang", "fr")
        self._src_btn = self._make_lang_btn(src)
        self._tgt_btn = self._make_lang_btn(tgt)

        arr = QLabel("→")
        arr.setStyleSheet(
            f"color:{_TEXT_MUTED};font-size:11px;background:transparent;"
        )
        hl.addWidget(self._src_btn)
        hl.addWidget(arr)
        hl.addWidget(self._tgt_btn)
        self._src_btn.clicked.connect(self._open_settings)
        self._tgt_btn.clicked.connect(self._open_settings)

        hl.addStretch()

        for ico, tip, cb in [("⚙", "Paramètres", self._open_settings),
                              ("✕", "Fermer", self.hide)]:
            b = QPushButton(ico)
            b.setFixedSize(26, 26)
            b.setToolTip(tip)
            b.setStyleSheet(self._ctrl_btn_css(_TEXT_MUTED))
            b.clicked.connect(cb)
            hl.addWidget(b)

        return hdr

    def _make_lang_btn(self, lang: str) -> QPushButton:
        label = "AUTO" if lang == "auto" else lang.upper()
        color = LANG_COLORS.get(lang, _ACCENT)
        b = QPushButton(label)
        b.setFixedHeight(22)
        b.setMinimumWidth(42)
        b.setStyleSheet(self._lang_btn_css(color))
        return b

    def _make_live_zone(self, fs: int) -> QWidget:
        # Conteneur externe : background + border-radius uniquement (pas de border-side
        # pour éviter le crash Qt avec mixed widths + border-radius).
        self._live_zone = QWidget()
        self._live_zone.setObjectName("live")
        self._live_zone.setFixedHeight(104)
        self._live_zone.setStyleSheet(f"""
            QWidget#live {{
                background: {_BG_LIVE};
                border-radius: 0 0 10px 10px;
            }}
        """)

        outer = QHBoxLayout(self._live_zone)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Barre d'accent gauche : widget 3px, sans border-radius, animé par _pulse_dot
        self._live_accent = QWidget()
        self._live_accent.setFixedWidth(3)
        self._live_accent.setStyleSheet(_ACCENT_CSS.format(color=_LIVE_DIM))
        outer.addWidget(self._live_accent)

        # Zone de contenu (VBoxLayout)
        content = QWidget()
        content.setStyleSheet("background: transparent; border: none;")
        outer.addWidget(content, 1)

        ll = QVBoxLayout(content)
        ll.setContentsMargins(14, 10, 12, 6)
        ll.setSpacing(3)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self._live_src = QLabel("En écoute…")
        self._live_src.setStyleSheet(f"""
            color: {_TEXT_MED};
            font-size: {fs - 1}px;
            font-style: italic;
            background: transparent;
        """)
        self._live_src.setWordWrap(True)
        top_row.addWidget(self._live_src, 1)

        self._source_badge = QLabel("")
        self._source_badge.setStyleSheet(
            f"color:{_LIVE_ON};font-size:9px;font-weight:700;"
            "letter-spacing:1.2px;background:transparent;border:none;padding:0;"
        )
        top_row.addWidget(self._source_badge)
        ll.addLayout(top_row)

        self._live_trad = QLabel("")
        self._live_trad.setStyleSheet(f"""
            color: {_TEXT};
            font-size: {fs}px;
            font-weight: 500;
            background: transparent;
            padding-left: 12px;
        """)
        self._live_trad.setWordWrap(True)
        self._live_trad.hide()
        ll.addWidget(self._live_trad)

        ll.addStretch()

        foot = QHBoxLayout()
        foot.setSpacing(8)

        self._mic_bar = QProgressBar()
        self._mic_bar.setRange(0, 100)
        self._mic_bar.setValue(0)
        self._mic_bar.setTextVisible(False)
        self._mic_bar.setFixedHeight(3)
        self._mic_bar.setStyleSheet(self._mic_bar_css(_LIVE_ON))
        self._mic_bar_color = _LIVE_ON
        foot.addWidget(self._mic_bar, 1)

        self._level_label = QLabel("")
        self._level_label.setStyleSheet(
            f"color:{_TEXT_MUTED};font-size:9px;"
            "font-family:Consolas,monospace;"
            "background:transparent;min-width:60px;"
        )
        foot.addWidget(self._level_label)

        grip = QSizeGrip(self)
        grip.setStyleSheet("background:transparent;")
        foot.addWidget(grip)

        ll.addLayout(foot)
        return self._live_zone

    def _make_mismatch_bar(self) -> QWidget:
        w = QWidget()
        w.setObjectName("mm")
        w.setStyleSheet(f"""
            QWidget#mm {{
                background: #fffbeb;
                border-top: 1px solid #fcd34d;
            }}
        """)
        l = QHBoxLayout(w)
        l.setContentsMargins(16, 7, 10, 7)
        l.setSpacing(8)

        self._mismatch_label = QLabel()
        self._mismatch_label.setStyleSheet(
            f"color:{_AMBER};font-size:11px;background:transparent;border:none;"
        )
        self._mismatch_label.setWordWrap(True)
        l.addWidget(self._mismatch_label, 1)

        sw = QPushButton("Changer")
        sw.setFixedHeight(22)
        sw.setMinimumWidth(62)
        sw.setStyleSheet(f"""
            QPushButton {{
                background: #fef3c7;
                color: {_AMBER};
                border: 1px solid #fcd34d;
                border-radius: 4px;
                font-size: 11px;
                font-weight: 600;
                padding: 0 10px;
            }}
            QPushButton:hover {{ background: #fde68a; }}
        """)
        sw.clicked.connect(self._do_switch_lang)
        l.addWidget(sw)

        dm = QPushButton("✕")
        dm.setFixedSize(20, 20)
        dm.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{_TEXT_MUTED}; border:none; font-size:11px; }}
            QPushButton:hover {{ color:{_AMBER}; }}
        """)
        dm.clicked.connect(self._dismiss_mismatch)
        l.addWidget(dm)

        return w

    # ──────────────────────────────────────────────────── Helpers CSS ─────────

    def _ctrl_btn_css(self, color: str) -> str:
        return f"""
            QPushButton {{
                background: transparent;
                color: {color};
                border: none;
                border-radius: 5px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                color: {_TEXT};
                background: rgba(0,0,0,0.06);
            }}
        """

    def _lang_btn_css(self, color: str) -> str:
        return f"""
            QPushButton {{
                background: transparent;
                color: {color};
                border: 1px solid {_BORDER};
                border-radius: 4px;
                padding: 0 9px;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 1.2px;
            }}
            QPushButton:hover {{
                background: rgba(0,0,0,0.04);
                border-color: {color};
            }}
        """

    def _mic_bar_css(self, color: str) -> str:
        return (
            f"QProgressBar {{ background: {_BORDER}; border: none; border-radius: 1px; }}"
            f"QProgressBar::chunk {{ background: {color}; border-radius: 1px; }}"
        )

    # ─────────────────────────────────────────────────────────── Slots ────────

    def _on_final(self, result: TranslationResult) -> None:
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

        sc = LANG_COLORS.get(result.source_lang, _ACCENT)
        tc = LANG_COLORS.get(result.target_lang, _ACCENT)
        is_same = result.source_lang == result.target_lang

        if is_same:
            block = (
                f'<div style="margin:0 0 14px 0">'
                f'<div style="color:{_TEXT_MUTED};font-size:9px;'
                f'letter-spacing:0.6px;margin-bottom:5px">'
                f'<span style="color:{sc}">{result.source_lang.upper()}</span>'
                f'</div>'
                f'<div style="color:{_TEXT};font-size:14px">{result.original}</div>'
                f'</div>'
            )
        else:
            block = (
                f'<div style="margin:0 0 14px 0">'
                f'<div style="color:{_TEXT_MUTED};font-size:9px;'
                f'letter-spacing:0.6px;margin-bottom:5px">'
                f'<span style="color:{sc}">{result.source_lang.upper()}</span>'
                f'<span style="color:{_TEXT_MUTED}"> → </span>'
                f'<span style="color:{tc}">{result.target_lang.upper()}</span>'
                f'</div>'
                f'<div style="color:{_TEXT_MED};font-style:italic;font-size:12px;'
                f'margin-bottom:4px">{result.original}</div>'
                f'<div style="color:{_TEXT};font-size:14px;font-weight:600">'
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

        self._clear_live()

    def _on_preview(self, result: TranslationResult) -> None:
        self._is_speaking = True

        if result.source == "mic":
            self._source_badge.setText("MIC")
            self._source_badge.setStyleSheet(
                f"color:{_LIVE_ON};font-size:9px;font-weight:700;"
                "letter-spacing:1.2px;background:transparent;border:none;padding:0;"
            )
        else:
            self._source_badge.setText("SYS")
            self._source_badge.setStyleSheet(
                f"color:{_ACCENT};font-size:9px;font-weight:700;"
                "letter-spacing:1.2px;background:transparent;border:none;padding:0;"
            )

        new_src  = result.original
        new_trad = (
            result.translated
            if (result.source_lang != result.target_lang and result.translated)
            else ""
        )

        self._tw_pos_src  = _common_prefix_len(self._tw_target_src,  new_src)
        self._tw_pos_trad = _common_prefix_len(self._tw_target_trad, new_trad)
        self._tw_target_src  = new_src
        self._tw_target_trad = new_trad

        if not self._typewriter_timer.isActive():
            self._typewriter_timer.start(25)

    def _on_status(self, text: str) -> None:
        if not self._is_speaking:
            self._live_src.setText(text)
            self._live_trad.hide()

    def _on_level(self, level: float, source: str) -> None:
        self._levels[source] = level

    def _clear_live(self) -> None:
        self._is_speaking = False
        self._typewriter_timer.stop()
        self._tw_target_src  = ""
        self._tw_target_trad = ""
        self._tw_pos_src     = 0
        self._tw_pos_trad    = 0
        self._live_src.setText("En écoute…")
        self._live_trad.hide()
        self._live_trad.setText("")
        self._source_badge.setText("")

    def _typewriter_tick(self) -> None:
        STEP = 2
        done_src = done_trad = True

        target_len_src = len(self._tw_target_src)
        if self._tw_pos_src < target_len_src:
            self._tw_pos_src = min(self._tw_pos_src + STEP, target_len_src)
            self._live_src.setText(self._tw_target_src[:self._tw_pos_src])
            done_src = (self._tw_pos_src >= target_len_src)
        elif self._tw_target_src and self._live_src.text() != self._tw_target_src:
            self._live_src.setText(self._tw_target_src)

        target_len_trad = len(self._tw_target_trad)
        if target_len_trad == 0:
            self._live_trad.hide()
        else:
            if self._tw_pos_trad < target_len_trad:
                self._tw_pos_trad = min(self._tw_pos_trad + STEP, target_len_trad)
                self._live_trad.setText(f"↳ {self._tw_target_trad[:self._tw_pos_trad]}")
                self._live_trad.show()
                done_trad = (self._tw_pos_trad >= target_len_trad)
            elif self._live_trad.text() != f"↳ {self._tw_target_trad}":
                self._live_trad.setText(f"↳ {self._tw_target_trad}")
                self._live_trad.show()

        if done_src and done_trad:
            self._typewriter_timer.stop()

    def _pulse_dot(self) -> None:
        self._dot_phase = (self._dot_phase + 1) % 4
        if self._is_speaking:
            color = _LIVE_ON if self._dot_phase % 2 == 0 else "#166534"
        else:
            color = _LIVE_DIM
        new_css = _ACCENT_CSS.format(color=color)
        if self._live_accent.styleSheet() != new_css:
            self._live_accent.setStyleSheet(new_css)

    def _refresh_levels(self) -> None:
        mic = self._levels.get("mic", 0.0)
        pct = max(0, min(100, int((math.log10(max(mic, 1e-4)) + 4) * 25)))
        self._mic_bar.setValue(pct)

        if pct < 60:
            color = _LIVE_ON
        elif pct < 85:
            color = _AMBER
        else:
            color = "#dc2626"

        if color != self._mic_bar_color:
            self._mic_bar_color = color
            self._mic_bar.setStyleSheet(self._mic_bar_css(color))

        self._level_label.setText(f"mic {mic:.4f}")

    # ─────────────────────────────────────────────────────── Mismatch ─────────

    def _show_mismatch(self, detected: str, configured: str) -> None:
        if self._last_mismatch_lang == detected:
            return
        self._last_mismatch_lang = detected
        self._pending_mismatch   = (detected, configured)
        dc = LANG_COLORS.get(detected, _AMBER)
        self._mismatch_label.setText(
            f"Langue détectée : <b style='color:{dc}'>{detected.upper()}</b> "
            f"(source actuelle : {configured.upper()}) — changer ?"
        )
        self._mismatch_label.setTextFormat(Qt.TextFormat.RichText)
        self._mismatch_widget.show()

    def _do_switch_lang(self) -> None:
        if self._pending_mismatch is None:
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
        self._config["whisper"]["language_source"] = new_src
        self._update_lang_display(new_src, new_tgt)
        try:
            from .. import config as cfg_module
            cfg_module.save(self._config)
            logger.info("Langue switchée : %s → %s", new_src, new_tgt)
        except Exception as e:
            logger.warning("Impossible de sauvegarder la config : %s", e)
        self._dismiss_mismatch()

    def _dismiss_mismatch(self) -> None:
        if self._pending_mismatch is not None:
            self._mismatch_dismissed_for = self._pending_mismatch[0]
        self._pending_mismatch = None
        self._mismatch_widget.hide()
        self._mismatch_count = 0

    def _update_lang_display(self, src: str, tgt: str) -> None:
        self._src_btn.setText("AUTO" if src == "auto" else src.upper())
        self._tgt_btn.setText(tgt.upper())
        self._src_btn.setStyleSheet(
            self._lang_btn_css(LANG_COLORS.get(src, _ACCENT))
        )
        self._tgt_btn.setStyleSheet(
            self._lang_btn_css(LANG_COLORS.get(tgt, _ACCENT))
        )

    def _open_settings(self) -> None:
        from .settings_window import SettingsWindow
        win = SettingsWindow(self._config, parent=self)
        if win.exec():
            src = self._cfg_translation.get("source_lang", "auto")
            tgt = self._cfg_translation.get("target_lang", "fr")
            self._update_lang_display(src, tgt)

    # ──────────────────────────────────────────────────────────── Drag ────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_pos is not None and event.button() == Qt.MouseButton.LeftButton:
            self._save_geometry()
        self._drag_pos = None

    def _save_geometry(self) -> None:
        pos  = self.pos()
        size = self.size()
        self._cfg["position_x"] = pos.x()
        self._cfg["position_y"] = pos.y()
        self._cfg["width"]      = size.width()
        self._cfg["height"]     = size.height()
        try:
            from .. import config as cfg_module
            cfg_module.save(self._config)
        except Exception:
            pass
