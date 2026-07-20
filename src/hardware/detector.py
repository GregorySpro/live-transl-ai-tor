import os
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Seuils VRAM (MB) pour la sélection automatique du modèle
_GPU_TIERS = [
    (8000, "large-v3", "float16"),
    (4000, "medium",   "float16"),
    (2000, "small",    "float16"),
    (0,    "base",     "float16"),
]

# Seuils RAM (MB) + cœurs CPU pour la sélection automatique
_CPU_TIERS = [
    (10000, 6, "small", "int8"),
    (6000,  4, "base",  "int8"),
    (0,     0, "tiny",  "int8"),
]


@dataclass
class HardwareProfile:
    has_cuda: bool = False
    gpu_name: str = ""
    gpu_vram_mb: int = 0
    cpu_cores: int = 1
    ram_mb: int = 0

    whisper_model: str = "tiny"
    device: str = "cpu"
    compute_type: str = "int8"
    description: str = ""


def detect() -> HardwareProfile:
    profile = HardwareProfile()
    profile.cpu_cores = os.cpu_count() or 1
    profile.ram_mb = _get_ram_mb()

    cuda = _get_cuda_info()
    if cuda:
        profile.has_cuda = True
        profile.gpu_name = cuda["name"]
        profile.gpu_vram_mb = cuda["vram_mb"]
        profile.device = "cuda"

    _apply_recommendations(profile)
    logger.info("Profil matériel détecté : %s", profile.description)
    return profile


def apply_config_overrides(profile: HardwareProfile, config: dict) -> HardwareProfile:
    """Applique les overrides manuels depuis la config utilisateur."""
    hw_cfg = config.get("hardware", {})
    if not hw_cfg.get("auto_optimize", True):
        w = config.get("whisper", {})
        if w.get("model") not in (None, "auto"):
            profile.whisper_model = w["model"]
        if w.get("device") not in (None, "auto"):
            profile.device = w["device"]
        if w.get("compute_type") not in (None, "auto"):
            profile.compute_type = w["compute_type"]
        profile.description += " [override manuel]"
    return profile


def _apply_recommendations(p: HardwareProfile) -> None:
    if p.has_cuda:
        for vram_min, model, compute in _GPU_TIERS:
            if p.gpu_vram_mb >= vram_min:
                p.whisper_model = model
                p.compute_type = compute
                gb = p.gpu_vram_mb // 1024
                p.description = f"GPU {p.gpu_name} ({gb}GB VRAM) → {model} [{compute}]"
                break
    else:
        for ram_min, cores_min, model, compute in _CPU_TIERS:
            if p.ram_mb >= ram_min and p.cpu_cores >= cores_min:
                p.whisper_model = model
                p.compute_type = compute
                gb = p.ram_mb // 1024
                p.description = (
                    f"CPU {p.cpu_cores} cœurs, {gb}GB RAM → {model} [{compute}]"
                )
                break


def _get_ram_mb() -> int:
    try:
        import psutil
        return psutil.virtual_memory().total // (1024 * 1024)
    except Exception:
        return 0


def _get_cuda_info() -> Optional[dict]:
    try:
        import torch
        if not torch.cuda.is_available():
            return None
        idx = torch.cuda.current_device()
        props = torch.cuda.get_device_properties(idx)
        return {
            "name": torch.cuda.get_device_name(idx),
            "vram_mb": props.total_memory // (1024 * 1024),
        }
    except Exception:
        return None
