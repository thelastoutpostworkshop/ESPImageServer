"""Local image-model adapter, deliberately independent of the web layer."""

from __future__ import annotations

import logging
import os
from threading import Lock
from typing import Callable

from PIL import Image

from .config import Settings
from .generation_jobs import GenerationCancelled

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

    def generate(
        self, prompt: str, width: int | None = None, height: int | None = None,
        progress: Callable[[int, int], None] | None = None, inference_steps: int | None = None,
        seed: int | None = None, cancelled: Callable[[], bool] | None = None,
    ) -> Image.Image:
        if self._pipeline is None:
            raise RuntimeError("Image model is not ready")
        # Most local diffusion pipelines are not safe to invoke concurrently.
        with self._lock:
            width = width or self.settings.generation_width
            height = height or self.settings.generation_height
            steps = inference_steps or self.settings.inference_steps
            if progress is not None:
                progress(0, steps)

            if cancelled is not None and cancelled():
                raise GenerationCancelled()

            def on_step_end(_pipeline, step, _timestep, callback_kwargs):
                if cancelled is not None and cancelled():
                    raise GenerationCancelled()
                if progress is not None:
                    progress(step + 1, steps)
                return callback_kwargs

            options = {
                "prompt": prompt,
                "num_inference_steps": steps,
                "guidance_scale": self.settings.guidance_scale,
                "width": width,
                "height": height,
                "callback_on_step_end": on_step_end if progress is not None or cancelled is not None else None,
            }
            if seed is not None:
                import torch
                options["generator"] = torch.Generator(device=self._device).manual_seed(seed)
            result = self._pipeline(**options)
        return result.images[0]
