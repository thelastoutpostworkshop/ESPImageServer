"""Supported image-model definitions and their maker-facing descriptions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from .config import Settings


@dataclass(frozen=True)
class ModelDefinition:
    model_id: str
    name: str
    description: str
    recommendation: str
    hardware: str
    speed: str
    inference_steps: int
    guidance_scale: float
    generation_width: int
    generation_height: int


MODELS: tuple[ModelDefinition, ...] = (
    ModelDefinition("stabilityai/sd-turbo", "SD-Turbo", "Fast local AI image model, designed for quick results.", "Recommended for most ESP32 displays and CPU compatibility mode.", "CPU or NVIDIA GPU", "Fast", 1, 0.0, 512, 512),
    ModelDefinition("segmind/SSD-1B", "Segmind SSD-1B", "Higher-quality local AI image model with more detailed results.", "Best with an NVIDIA graphics card; generation takes longer.", "NVIDIA GPU recommended", "Higher quality", 20, 9.0, 1024, 1024),
)


def get_model(model_id: str) -> ModelDefinition:
    for model in MODELS:
        if model.model_id == model_id:
            return model
    raise ValueError(f"Unsupported model: {model_id}")


def model_settings(settings: Settings, model_id: str) -> Settings:
    model = get_model(model_id)
    return replace(settings, model_id=model.model_id, inference_steps=model.inference_steps,
                   guidance_scale=model.guidance_scale, generation_width=model.generation_width,
                   generation_height=model.generation_height)


def model_is_cached(model: ModelDefinition, cache_dir: Path | None) -> bool:
    if cache_dir is None:
        return False
    repo_dir = "models--" + model.model_id.replace("/", "--")
    return (cache_dir / repo_dir / "snapshots").is_dir() or (cache_dir / "hub" / repo_dir / "snapshots").is_dir()
