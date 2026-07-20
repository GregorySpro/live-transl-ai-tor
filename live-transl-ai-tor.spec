# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — live-transl-ai-tor
Build : pyinstaller live-transl-ai-tor.spec
Output : dist/live-transl-ai-tor/live-transl-ai-tor.exe
"""

from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

# ── Collecte des packages lourds ──────────────────────────────────────────────
datas     = []
binaries  = []
hiddenimports = []

for pkg in ("torch", "torchaudio", "ctranslate2", "faster_whisper",
            "argostranslate", "numba", "llvmlite", "librosa"):
    d, b, h = collect_all(pkg)
    datas    += d
    binaries += b
    hiddenimports += h

# Metadata nécessaire pour les imports dynamiques (importlib.metadata)
for pkg in ("torch", "torchaudio", "filelock", "huggingface_hub",
            "faster_whisper", "argostranslate"):
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass

# Fichiers de données argostranslate (langues, stanza…)
datas += collect_data_files("argostranslate")
datas += collect_data_files("stanza", include_py_files=False)

# ── Analyse ───────────────────────────────────────────────────────────────────
a = Analysis(
    ["app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + [
        # PyQt6
        "PyQt6", "PyQt6.QtWidgets", "PyQt6.QtCore", "PyQt6.QtGui",
        "PyQt6.sip",
        # Audio
        "sounddevice", "pyaudiowpatch", "_sounddevice_data",
        # Keyboard
        "keyboard",
        # Psutil
        "psutil", "psutil._pswindows",
        # Src package
        "src", "src.main", "src.config", "src.hardware", "src.hardware.detector",
        "src.audio", "src.audio.capture", "src.audio.vad",
        "src.transcription", "src.transcription.whisper_engine",
        "src.translation", "src.translation.argos_engine",
        "src.ui", "src.ui.overlay", "src.ui.settings_window",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Pas besoin de ces modules dans l'exe
        "matplotlib", "PIL", "IPython", "jupyter", "notebook",
        "sphinx", "pytest", "setuptools", "pip",
        "tkinter", "wx",
    ],
    noarchive=False,
    optimize=1,
)

# ── PYZ ───────────────────────────────────────────────────────────────────────
pyz = PYZ(a.pure)

# ── EXE ───────────────────────────────────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="live-transl-ai-tor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # pas de fenêtre console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon="assets/icon.ico",  # décommenter si icône disponible
)

# ── COLLECT (onedir) ──────────────────────────────────────────────────────────
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="live-transl-ai-tor",
)
