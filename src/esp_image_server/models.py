"""Supported image-model definitions and their maker-facing descriptions."""

from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path
import shutil

from .config import Settings


@dataclass(frozen=True)
class ModelDefinition:
    model_id: str
    name: str
    description: str
    recommendation: str
    hardware: str
    speed: str
    minimum_steps: int
    maximum_steps: int
    inference_steps: int
    guidance_scale: float
    generation_width: int
    generation_height: int
    supports_negative_prompt: bool


MODELS: tuple[ModelDefinition, ...] = (
    ModelDefinition("stabilityai/sd-turbo", "SD-Turbo", "Fast local AI image model, designed for quick results.", "Recommended for most ESP32 displays and CPU compatibility mode.", "CPU or NVIDIA GPU", "Fast", 1, 4, 1, 0.0, 512, 512, False),
    ModelDefinition("Lykon/dreamshaper-8", "DreamShaper 8", "Creative, polished artwork for illustrations, fantasy scenes, and stylized displays.", "NVIDIA graphics card recommended. It is slower than SD-Turbo but creates more artistic images.", "NVIDIA GPU recommended", "Creative and detailed", 10, 40, 25, 7.0, 512, 512, True),
    ModelDefinition("segmind/SSD-1B", "Segmind SSD-1B", "Higher-quality local AI image model with more detailed results.", "Best with an NVIDIA graphics card; generation takes longer.", "NVIDIA GPU recommended", "Higher quality", 10, 40, 20, 9.0, 1024, 1024, True),
    ModelDefinition("stabilityai/stable-diffusion-xl-base-1.0", "SDXL Base 1.0", "Premium image detail, richer compositions, and stronger prompt understanding.", "Requires a powerful NVIDIA graphics card with ample video memory. This is the largest and slowest option.", "Powerful NVIDIA GPU required", "Best detail", 10, 40, 30, 7.0, 1024, 1024, True),
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


def model_cache_roots(cache_dir: Path | None) -> tuple[Path, ...]:
    """Return the image-model cache roots used by installed and dev builds."""
    if cache_dir is None:
        app_cache = Path(os.getenv("ESP_IMAGE_MODEL_CACHE", Path.home() / ".cache" / "ESPImageServer" / "models"))
        hub_cache = os.getenv("HUGGINGFACE_HUB_CACHE") or os.getenv("HF_HUB_CACHE")
        hf_home = Path(os.getenv("HF_HOME", Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache")) / "huggingface"))
        return (app_cache, Path(hub_cache) if hub_cache else hf_home / "hub")
    return (cache_dir,)


def model_is_cached(model: ModelDefinition, cache_dir: Path | None) -> bool:
    """Return whether a model is available locally without another download."""
    repo_dir = "models--" + model.model_id.replace("/", "--")
    return any(
        (root / repo_dir / "snapshots").is_dir() or (root / "hub" / repo_dir / "snapshots").is_dir()
        for root in model_cache_roots(cache_dir)
    )


def remove_cached_model(model: ModelDefinition, cache_dir: Path | None) -> bool:
    """Remove only this image model's Hugging Face cache entries."""
    repo_dir = "models--" + model.model_id.replace("/", "--")
    removed = False
    for root in model_cache_roots(cache_dir):
        for path in (root / repo_dir, root / "hub" / repo_dir):
            if path.is_dir():
                shutil.rmtree(path)
                removed = True
    return removed
