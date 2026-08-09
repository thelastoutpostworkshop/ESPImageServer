"""Configuration read from environment variables."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    value = int(os.getenv(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    value = float(os.getenv(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


@dataclass(frozen=True)
class Settings:
    model_id: str = "stabilityai/sd-turbo"
    output_width: int = 466
    output_height: int = 466
    generation_width: int = 512
    generation_height: int = 512
    jpeg_quality: int = 85
    inference_steps: int = 1
    guidance_scale: float = 0.0
    host: str = "0.0.0.0"
    port: int = 8000
    model_cache_dir: Path | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        quality = _env_int("ESP_IMAGE_JPEG_QUALITY", 85, 1)
        if quality > 100:
            raise ValueError("ESP_IMAGE_JPEG_QUALITY must be no more than 100")
        generation_width = _env_int("ESP_IMAGE_GENERATION_WIDTH", 512, 8)
        generation_height = _env_int("ESP_IMAGE_GENERATION_HEIGHT", 512, 8)
        if generation_width % 8 or generation_height % 8:
            raise ValueError("generation dimensions must be divisible by 8")
        return cls(
            model_id=os.getenv("ESP_IMAGE_MODEL", cls.model_id),
            output_width=_env_int("ESP_IMAGE_OUTPUT_WIDTH", 466),
            output_height=_env_int("ESP_IMAGE_OUTPUT_HEIGHT", 466),
            generation_width=generation_width,
            generation_height=generation_height,
            jpeg_quality=quality,
            inference_steps=_env_int("ESP_IMAGE_INFERENCE_STEPS", 1),
            guidance_scale=_env_float("ESP_IMAGE_GUIDANCE_SCALE", 0.0),
            host=os.getenv("ESP_IMAGE_HOST", cls.host),
            port=_env_int("ESP_IMAGE_PORT", 8000),
            model_cache_dir=Path(os.environ["ESP_IMAGE_MODEL_CACHE"]) if os.getenv("ESP_IMAGE_MODEL_CACHE") else None,
        )
