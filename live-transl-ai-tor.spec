# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — live-transl-ai-tor (spec allégé)
Build : pyinstaller live-transl-ai-tor.spec
Output : dist/live-transl-ai-tor/live-transl-ai-tor.exe
"""

from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

datas    = []
binaries = []
hiddenimports = []

# ctranslate2 et faster-whisper ont besoin de collect_all (DLLs natives)
for pkg in ("ctranslate2", "faster_whisper"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

# argostranslate : données de langues
d, b, h = collect_all("argostranslate")
datas += d; binaries += b; hiddenimports += h

# Métadonnées pour importlib.metadata
for pkg in ("torch", "torchaudio", "filelock", "huggingface_hub", "faster_whisper"):
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass

# ── Analyse ───────────────────────────────────────────────────────────────────
a = Analysis(
    ["app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + [
        "PyQt6", "PyQt6.QtWidgets", "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.sip",
        "sounddevice", "pyaudiowpatch",
        "keyboard",
        "psutil", "psutil._pswindows",
        "torch", "torch.nn", "torch.jit",
        "torchaudio",
        "numpy", "scipy", "librosa",
        "numba", "llvmlite",
        "src", "src.main", "src.config",
        "src.hardware", "src.hardware.detector",
        "src.audio", "src.audio.capture", "src.audio.vad",
        "src.transcription", "src.transcription.whisper_engine",
        "src.translation", "src.translation.argos_engine",
        "src.ui", "src.ui.overlay", "src.ui.settings_window",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Tout ce dont on n'a pas besoin
        "matplotlib", "PIL", "Pillow", "IPython", "jupyter", "notebook",
        "sphinx", "pytest", "setuptools", "pip", "tkinter", "wx",
        "sklearn", "scikit-learn", "pandas", "tensorflow", "keras",
        "cv2", "skimage", "imageio",
        "sympy", "networkx",
        # torch.distributed, torch.testing… inutiles en inférence CPU
        "torch.distributed", "torch.testing", "torch.ao",
        "torch.backends.cuda", "torch.backends.cudnn",
        "torch.cuda", "caffe2",
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="live-transl-ai-tor",
    debug=False,
    strip=False,
    upx=False,          # UPX désactivé — trop lent sur les gros binaires torch
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="live-transl-ai-tor",
)
