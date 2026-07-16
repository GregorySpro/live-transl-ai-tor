# live-transl**AI**tor

Traducteur audio en temps réel — 100% local, 100% gratuit.

Capture le son de ton ordinateur (appels vidéo, vidéos, podcasts…) **et** ton microphone, transcrit la parole avec [Whisper](https://github.com/SYSTRAN/faster-whisper) et traduit instantanément via [Argos Translate](https://github.com/argosopentech/argos-translate). Le tout dans un overlay flottant always-on-top.

---

## Fonctionnalités

- **Détection audio système** via WASAPI loopback (aucun driver tiers nécessaire)
- **Capture microphone** simultanée — garde un fil de conversation bilingue
- **Transcription locale** avec faster-whisper (modèle auto-choisi selon ton GPU/CPU)
- **Traduction locale** avec Argos Translate — aucune API, aucun quota
- **Overlay always-on-top** draggable, semi-transparent, activable avec `Ctrl+Shift+T`
- **Optimisation automatique** du modèle Whisper selon le matériel détecté
- **Paramètres** entièrement configurables (langues, modèle, raccourci, UI…)

---

## Installation

### 1. Prérequis

- Python 3.11+
- Windows 10/11

### 2. Environnement virtuel

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 3. Dépendances

```bash
pip install -r requirements.txt
```

> **Avec GPU NVIDIA :** installe d'abord PyTorch avec CUDA depuis [pytorch.org](https://pytorch.org/get-started/locally/) avant le `pip install`.

### 4. Modèles de traduction (une seule fois)

```bash
python scripts/install_models.py fr en        # installe les paires fr↔en
python scripts/install_models.py fr en de es  # plusieurs langues
```

---

## Lancement

```bash
python -m src.main
```

Appuie sur **`Ctrl+Shift+T`** pour afficher/masquer l'overlay.

---

## Sélection automatique du modèle Whisper

| Matériel | Modèle choisi |
|---|---|
| GPU NVIDIA ≥ 8 GB VRAM | `large-v3` (float16) |
| GPU NVIDIA 4–8 GB VRAM | `medium` (float16) |
| GPU NVIDIA 2–4 GB VRAM | `small` (float16) |
| GPU NVIDIA < 2 GB VRAM | `base` (float16) |
| CPU ≥ 16 GB RAM + 8 cœurs | `small` (int8) |
| CPU ≥ 8 GB RAM | `base` (int8) |
| CPU < 8 GB RAM | `tiny` (int8) |

Tu peux forcer un modèle dans **Paramètres → Whisper / IA** en décochant l'optimisation automatique.

---

## Structure du projet

```
src/
├── main.py              — Orchestrateur principal
├── config/              — Chargement/sauvegarde de la config JSON
├── hardware/            — Détection GPU/CPU/RAM + auto-sélection
├── audio/
│   ├── capture.py       — WASAPI loopback + microphone
│   └── vad.py           — Voice Activity Detection (Silero)
├── transcription/
│   └── whisper_engine.py — STT avec faster-whisper
├── translation/
│   └── argos_engine.py   — Traduction locale Argos
└── ui/
    ├── overlay.py        — Overlay PyQt6 always-on-top
    └── settings_window.py — Fenêtre de paramètres
```

---

## Coût

**0 €.** Tous les modèles tournent localement.

---

## Licence

MIT
