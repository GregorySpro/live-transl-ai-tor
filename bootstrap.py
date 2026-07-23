"""
Bootstrap — premier lancement de live-transl-ai-tor.

Flux :
  1. Si déjà installé → lance l'app directement via le venv.
  2. Si première fois  → affiche la fenêtre de setup, télécharge uv,
     crée le venv Python, installe les dépendances, puis lance l'app.
"""
import io
import json
import os
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import requests
import webview

# ── Chemins ───────────────────────────────────────────────────────────────────
APP_NAME  = "live-transl-ai-tor"
_LOCAL    = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
APP_DIR   = _LOCAL / APP_NAME
VENV_DIR  = APP_DIR / "venv"
UV_EXE    = APP_DIR / "uv.exe"
MARKER    = APP_DIR / ".installed"

_FROZEN   = getattr(sys, "frozen", False)
MEIPASS   = Path(sys._MEIPASS) if _FROZEN else Path(__file__).parent
INSTALL   = Path(sys.executable).parent if _FROZEN else Path(__file__).parent
APP_PY    = INSTALL / "app.py"
HTML_FILE = MEIPASS / "bootstrap_ui.html"

UV_URL    = (
    "https://github.com/astral-sh/uv/releases/latest/download/"
    "uv-x86_64-pc-windows-msvc.zip"
)

# Packages installés via uv, dans l'ordre (label, [packages])
INSTALL_STEPS = [
    ("Téléchargement du gestionnaire", ["_uv"]),          # pseudo-step
    ("Environnement Python 3.12",       ["_venv"]),        # pseudo-step
    ("Moteur audio",                    ["sounddevice", "pyaudiowpatch"]),
    ("Moteur vocal (IA)",               [
        "torch==2.3.1+cpu --extra-index-url https://download.pytorch.org/whl/cpu",
        "torchaudio==2.3.1+cpu --extra-index-url https://download.pytorch.org/whl/cpu",
        "faster-whisper",
    ]),
    ("Moteur de traduction",            ["argostranslate", "stanza"]),
    ("Interface et utilitaires",        ["PyQt6", "keyboard", "psutil",
                                         "numpy<2.0", "librosa", "numba>=0.60.0"]),
]

_window: webview.Window | None = None


# ── JS helpers ────────────────────────────────────────────────────────────────
def _js(script: str) -> None:
    if _window:
        try:
            _window.evaluate_js(script)
        except Exception:
            pass


def _set_step(i: int) -> None:
    _js(f"setStep({i})")


def _set_progress(pct: int, status: str) -> None:
    _js(f"setProgress({pct}, {json.dumps(status)})")


# ── Installation ──────────────────────────────────────────────────────────────
def _download_uv() -> None:
    """Télécharge et extrait uv.exe dans APP_DIR."""
    _set_progress(2, "Téléchargement du gestionnaire de paquets…")
    r = requests.get(UV_URL, stream=True, timeout=120)
    r.raise_for_status()
    data = io.BytesIO()
    total = int(r.headers.get("content-length", 0))
    received = 0
    for chunk in r.iter_content(chunk_size=65536):
        data.write(chunk)
        received += len(chunk)
        if total:
            pct = int(received / total * 8)
            _set_progress(2 + pct, "Téléchargement du gestionnaire de paquets…")
    data.seek(0)
    with zipfile.ZipFile(data) as z:
        for name in z.namelist():
            if name.endswith("uv.exe"):
                UV_EXE.write_bytes(z.read(name))
                break


def _uv_env() -> dict:
    """Variables d'environnement pour uv — force LOCALAPPDATA pour éviter
    les junctions Windows (ex. OneDrive qui redirige AppData\\Roaming)."""
    env = os.environ.copy()
    uv_home = APP_DIR / "uv"
    env["UV_DATA_DIR"]  = str(uv_home / "data")
    env["UV_CACHE_DIR"] = str(uv_home / "cache")
    env["UV_PYTHON_INSTALL_DIR"] = str(uv_home / "python")
    return env


def _run_uv(*args: str) -> None:
    result = subprocess.run(
        [str(UV_EXE), *args],
        capture_output=True, text=True,
        env=_uv_env(),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)


def _install(on_done: callable, on_error: callable) -> None:
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)

        n = len(INSTALL_STEPS)
        for i, (label, pkgs) in enumerate(INSTALL_STEPS):
            _set_step(i)
            pct_base = 12 + int(i / n * 80)

            if pkgs == ["_uv"]:
                if not UV_EXE.exists():
                    _download_uv()
                _set_progress(pct_base, f"{label} — OK")
                continue

            if pkgs == ["_venv"]:
                _set_progress(pct_base, "Création de l'environnement Python…")
                _run_uv("venv", str(VENV_DIR), "--python", "3.12")
                _set_progress(pct_base + 4, f"{label} — OK")
                continue

            _set_progress(pct_base, f"Installation : {label}…")
            venv_py = str(VENV_DIR / "Scripts" / "python.exe")
            for pkg in pkgs:
                _run_uv("pip", "install", "--python", venv_py, *pkg.split())

            _set_progress(pct_base + int(80 / n), f"{label} — OK")

        MARKER.touch()
        _set_progress(100, "Installation terminée")
        time.sleep(0.3)
        on_done()

    except Exception as exc:
        on_error(str(exc))


# ── Lancement app ─────────────────────────────────────────────────────────────
def _launch_app() -> None:
    venv_python = VENV_DIR / "Scripts" / "python.exe"
    # sys.stderr peut être None (frozen + console=False)
    _stderr = sys.stderr
    if sys.stderr is None:
        sys.stderr = io.StringIO()
    try:
        subprocess.Popen([str(venv_python), str(APP_PY)])
    finally:
        sys.stderr = _stderr
    if _window:
        _window.destroy()
    sys.exit(0)


# ── API exposée au JS ─────────────────────────────────────────────────────────
class BootstrapApi:
    def launch(self) -> None:
        threading.Thread(target=_launch_app, daemon=True).start()


# ── Point d'entrée ────────────────────────────────────────────────────────────
def main() -> None:
    global _window

    if MARKER.exists() and VENV_DIR.exists():
        _launch_app()
        return

    api = BootstrapApi()
    _window = webview.create_window(
        title=APP_NAME,
        url=str(HTML_FILE),
        width=560,
        height=560,
        resizable=False,
        frameless=True,
        js_api=api,
        background_color="#0a0a0a",
    )

    def _on_loaded() -> None:
        labels = [label for label, _ in INSTALL_STEPS]
        _js(f"initSteps({json.dumps(labels)})")

        def on_done() -> None:
            _js("showDone()")

        def on_error(msg: str) -> None:
            _js(f"showError({json.dumps(msg)})")

        threading.Thread(
            target=_install, args=(on_done, on_error), daemon=True
        ).start()

    _window.events.loaded += _on_loaded
    webview.start()


if __name__ == "__main__":
    main()
