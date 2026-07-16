DEFAULT_CONFIG = {
    "whisper": {
        "model": "auto",        # auto = choisi par hardware detector
        "device": "auto",       # auto, cuda, cpu
        "compute_type": "auto", # auto, float16, int8, float32
        "language_source": "auto",
    },
    "translation": {
        "source_lang": "en",
        "target_lang": "fr",
    },
    "audio": {
        "loopback_device_index": None,  # None = auto-detect
        "mic_device_index": None,
        "sample_rate": 16000,
        "chunk_ms": 500,
        "silence_duration_ms": 800,
        "vad_threshold": 0.5,
    },
    "ui": {
        "hotkey": "ctrl+shift+t",
        "opacity": 0.88,
        "always_on_top": True,
        "font_size": 14,
        "max_transcript_lines": 100,
        "position_x": None,
        "position_y": None,
        "width": 520,
        "height": 420,
        "theme": "dark",
    },
    "hardware": {
        "auto_optimize": True,
        "detected_profile": None,
    },
}
