"""
ANPR System — Configuration Loader

Loads config.yaml and exposes an AppConfig dataclass with sensible defaults.
"""

import os
import logging
from dataclasses import dataclass, field
from typing import Optional

import yaml


# ── Defaults ────────────────────────────────────────────────
_DEFAULTS = {
    "camera": {
        "resolution_width": 640,
        "resolution_height": 480,
        "capture_count": 5,
        "warmup_seconds": 2,
    },
    "sensor": {
        "trigger_pin": 23,
        "echo_pin": 24,
        "distance_threshold_cm": 50,
        "confirmation_readings": 3,
        "reading_interval_sec": 0.1,
    },
    "actuator": {
        "servo_pin": 18,
        "relay_pin": 25,
        "servo_open_angle": 90,
        "servo_closed_angle": 0,
        "open_duration_sec": 10,
        "use_servo": True,
        "use_relay": False,
    },
    "detection": {
        "min_detection_confidence": 0.5,
        "min_ocr_confidence": 60,
        "max_retries": 3,
        "preprocessing_width": 800,
        "plate_aspect_min": 2.0,
        "plate_aspect_max": 6.0,
        "min_plate_area": 1000,
    },
    "ocr": {
        "engine": "tesseract",
        "tesseract_psm": 7,
        "char_whitelist": "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    },
    "paths": {
        "database": "data/db/anpr.db",
        "events_dir": "data/events",
    },
    "web": {
        "host": "0.0.0.0",
        "port": 5000,
        "debug": False,
    },
    "logging": {
        "level": "INFO",
        "file": "data/anpr.log",
    },
    "telegram": {
        "enabled": False,
        "bot_token": "",
        "allowed_chat_ids": [],
        "notify_on_allow": True,
        "notify_on_deny": True,
        "notify_on_unknown": True,
        "send_image": True,
    },
}


# ── Nested Config Dataclasses ───────────────────────────────
@dataclass
class CameraConfig:
    resolution_width: int = 640
    resolution_height: int = 480
    capture_count: int = 5
    warmup_seconds: int = 2


@dataclass
class SensorConfig:
    trigger_pin: int = 23
    echo_pin: int = 24
    distance_threshold_cm: int = 50
    confirmation_readings: int = 3
    reading_interval_sec: float = 0.1


@dataclass
class ActuatorConfig:
    servo_pin: int = 18
    relay_pin: int = 25
    servo_open_angle: int = 90
    servo_closed_angle: int = 0
    open_duration_sec: int = 10
    use_servo: bool = True
    use_relay: bool = False


@dataclass
class DetectionConfig:
    min_detection_confidence: float = 0.5
    min_ocr_confidence: float = 60
    max_retries: int = 3
    preprocessing_width: int = 800
    plate_aspect_min: float = 2.0
    plate_aspect_max: float = 6.0
    min_plate_area: int = 1000


@dataclass
class OcrConfig:
    engine: str = "tesseract"
    tesseract_psm: int = 7
    char_whitelist: str = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


@dataclass
class PathsConfig:
    database: str = "data/db/anpr.db"
    events_dir: str = "data/events"


@dataclass
class WebConfig:
    host: str = "0.0.0.0"
    port: int = 5000
    debug: bool = False


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "data/anpr.log"


@dataclass
class TelegramConfig:
    enabled: bool = False
    bot_token: str = ""
    allowed_chat_ids: list = field(default_factory=list)
    notify_on_allow: bool = True
    notify_on_deny: bool = True
    notify_on_unknown: bool = True
    send_image: bool = True


@dataclass
class AppConfig:
    """Top-level application configuration."""
    camera: CameraConfig = field(default_factory=CameraConfig)
    sensor: SensorConfig = field(default_factory=SensorConfig)
    actuator: ActuatorConfig = field(default_factory=ActuatorConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    ocr: OcrConfig = field(default_factory=OcrConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    web: WebConfig = field(default_factory=WebConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)

    # Absolute base directory (set at load time)
    base_dir: str = ""


# ── Deep merge helper ──────────────────────────────────────
def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base*, returning a new dict."""
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


# ── Loader ──────────────────────────────────────────────────
def load_config(config_path: Optional[str] = None) -> AppConfig:
    """
    Load configuration from a YAML file, merge with defaults,
    and return an AppConfig instance.

    If *config_path* is None, looks for ``config.yaml`` next to the
    project root (parent of ``src/``).
    """
    if config_path is None:
        # Default: project root / config.yaml
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base_dir, "config.yaml")
    else:
        base_dir = os.path.dirname(os.path.abspath(config_path))

    raw: dict = {}
    if os.path.isfile(config_path):
        with open(config_path, "r") as fh:
            raw = yaml.safe_load(fh) or {}
    else:
        logging.warning("Config file not found at %s — using defaults.", config_path)

    merged = _deep_merge(_DEFAULTS, raw)

    cfg = AppConfig(
        camera=CameraConfig(**merged["camera"]),
        sensor=SensorConfig(**merged["sensor"]),
        actuator=ActuatorConfig(**merged["actuator"]),
        detection=DetectionConfig(**merged["detection"]),
        ocr=OcrConfig(**merged["ocr"]),
        paths=PathsConfig(**merged["paths"]),
        web=WebConfig(**merged["web"]),
        logging=LoggingConfig(**merged["logging"]),
        telegram=TelegramConfig(**merged["telegram"]),
        base_dir=base_dir,
    )

    return cfg


# ── Convenience: resolve paths relative to base_dir ────────
def resolve_path(cfg: AppConfig, relative_path: str) -> str:
    """Return an absolute path by joining *relative_path* with cfg.base_dir."""
    if os.path.isabs(relative_path):
        return relative_path
    return os.path.join(cfg.base_dir, relative_path)


# ── Setup logging based on config ──────────────────────────
def setup_logging(cfg: AppConfig) -> None:
    """Configure the root logger from AppConfig."""
    log_path = resolve_path(cfg, cfg.logging.file)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    numeric_level = getattr(logging, cfg.logging.level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path),
            logging.StreamHandler(),
        ],
    )
