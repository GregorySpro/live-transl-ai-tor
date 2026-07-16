import json
import copy
from pathlib import Path

from .defaults import DEFAULT_CONFIG

CONFIG_PATH = Path.home() / ".live-transl-ai-tor" / "config.json"


def load() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
        config = copy.deepcopy(DEFAULT_CONFIG)
        _deep_update(config, saved)
        return config
    return copy.deepcopy(DEFAULT_CONFIG)


def save(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def _deep_update(base: dict, override: dict) -> None:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
