# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — bootstrap uniquement (fenêtre de premier lancement).
Ne contient PAS torch / faster-whisper / PyQt6 — ils sont installés au runtime.
Build : pyinstaller bootstrap.spec
Output : dist/live-transl-ai-tor-bootstrap/live-transl-ai-tor.exe
"""

from PyInstaller.utils.hooks import collect_all, collect_data_files

datas    = []
binaries = []
hiddenimports = []

# pywebview — fenêtre de setup
for pkg in ("webview",):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

# Fichier HTML de la fenêtre de setup
datas += [("bootstrap_ui.html", ".")]

a = Analysis(
    ["bootstrap.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + [
        "webview", "webview.platforms", "webview.platforms.winforms",
        "clr", "clr_loader",
        "requests", "urllib3", "certifi", "charset_normalizer", "idna",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "torch", "torchaudio", "faster_whisper", "ctranslate2",
        "PyQt6", "argostranslate", "stanza", "networkx",
        "matplotlib", "PIL", "sklearn", "pandas", "tkinter",
        "pytest", "setuptools",
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
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="live-transl-ai-tor-bootstrap",
)
