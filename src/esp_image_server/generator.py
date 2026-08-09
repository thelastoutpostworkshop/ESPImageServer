"""Local image-model adapter, deliberately independent of the web layer."""

from __future__ import annotations

import logging
import os
from threading import Lock

from PIL import Image

from .config import Settings

logger = logging.getLogger(__name__)


class DiffusersGenerator:
    """Generate PIL images with a Diffusers text-to-image pipeline."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._pipeline = None
        self._device = "cpu"
        self._lock = Lock()

    @property
    def device(self) -> str:
        return self._device

    @property
    def ready(self) -> bool:
        return self._pipeline is not None

    def load(self) -> None:
        """Load the model once. Imports stay here so setup errors are actionable."""
        if self._pipeline is not None:
            return
        try:
            import torch
            from diffusers import AutoPipelineForText2Image
        except ImportError as exc:
            raise RuntimeError(
                "Image dependencies are missing. Install the project dependencies and PyTorch."
            ) from exc

        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if self._device == "cuda" else torch.float32
        logger.info("Loading model '%s' on %s", self.settings.model_id, self._device)
        options = {"torch_dtype": dtype}
        if model_cache_dir := os.getenv("ESP_IMAGE_MODEL_CACHE"):
            options["cache_dir"] = model_cache_dir
        pipeline = AutoPipelineForText2Image.from_pretrained(self.settings.model_id, **options)
        pipeline = pipeline.to(self._device)
        if self._device == "cpu":
            pipeline.enable_attention_slicing()
        self._pipeline = pipeline

    def activate_model(self, settings: Settings) -> None:
        """Unload the current pipeline and download/load the selected model."""
        with self._lock:
            if self._pipeline is not None and self.settings.model_id == settings.model_id:
                return
            self._pipeline = None
            self.settings = settings
        self.load()

    def generate(self, prompt: str, width: int | None = None, height: int | None = None) -> Image.Image:
        if self._pipeline is None:
            raise RuntimeError("Image model is not ready")
        # Most local diffusion pipelines are not safe to invoke concurrently.
        with self._lock:
            width = width or self.settings.generation_width
            height = height or self.settings.generation_height
            result = self._pipeline(
                prompt=prompt,
                num_inference_steps=self.settings.inference_steps,
                guidance_scale=self.settings.guidance_scale,
                width=width,
                height=height,
            )
        return result.images[0]
