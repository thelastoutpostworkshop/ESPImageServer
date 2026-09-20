"""Local image-model adapter, deliberately independent of the web layer."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from threading import Lock
from typing import Callable

from PIL import Image

from .config import Settings
from .download_progress import DownloadProgress, huggingface_progress
from .generation_jobs import GenerationCancelled

logger = logging.getLogger(__name__)


class DiffusersGenerator:
    """Generate PIL images with a Diffusers text-to-image pipeline."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._pipeline = None
        # Models are loaded only once a user selects one.  Detect CUDA here as
        # well so the UI can correctly offer video generation before any image
        # model has been downloaded.
        self._device = self._detect_device()
        self._lock = Lock()

    @staticmethod
    def _detect_device() -> str:
        try:
            import torch
            if torch.cuda.is_available():
                torch.empty(1, device="cuda")
                torch.cuda.synchronize()
                return "cuda"
            return "cpu"
        except (ImportError, RuntimeError, OSError):
            return "cpu"

    @property
    def device(self) -> str:
        return self._device

    @property
    def ready(self) -> bool:
        return self._pipeline is not None

    def load(self, progress: DownloadProgress | None = None) -> None:
        """Load the model once. Imports stay here so setup errors are actionable."""
        if self._pipeline is not None:
            return
        self._device = self._detect_device()
        if self._device != "cuda":
            raise RuntimeError("Image generation requires a working NVIDIA GPU with CUDA; CPU generation is not supported.")
        try:
            import torch
            from diffusers import AutoPipelineForText2Image
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise RuntimeError(
                "Image dependencies are missing. Install the project dependencies and PyTorch."
            ) from exc

        dtype = torch.float16
        logger.info("Loading model '%s' on %s", self.settings.model_id, self._device)
        options = {"torch_dtype": dtype}
        model_cache_dir = Path(os.getenv("ESP_IMAGE_MODEL_CACHE", Path.home() / ".cache" / "ESPImageServer" / "models"))
        model_cache_dir.mkdir(parents=True, exist_ok=True)
        if progress is not None:
            progress(0, 0, f"Checking or downloading {self.settings.model_id}")
        model_path = snapshot_download(
            self.settings.model_id, cache_dir=model_cache_dir,
            tqdm_class=huggingface_progress(self.settings.model_id, progress) if progress else None,
        )
        # Some model repositories bundle the legacy safety checker. Its false
        # positives are returned as an all-black image, which is especially
        # confusing on a small ESP32 display. The app validates output below
        # instead of silently showing a blank image.
        if progress is not None:
            progress(0, 0, f"Loading {self.settings.model_id} from disk")
        pipeline = AutoPipelineForText2Image.from_pretrained(
            model_path,
            safety_checker=None,
            requires_safety_checker=False,
            **options,
        )
        if progress is not None:
            destination = "NVIDIA graphics card (CUDA)" if self._device == "cuda" else "CPU"
            progress(0, 0, f"Moving {self.settings.model_id} to {destination}")
        pipeline = pipeline.to(self._device)
        self._pipeline = pipeline

    def activate_model(self, settings: Settings, progress: DownloadProgress | None = None) -> None:
        """Unload the current pipeline and download/load the selected model."""
        with self._lock:
            if self._pipeline is not None and self.settings.model_id == settings.model_id:
                return
            self._pipeline = None
            self.settings = settings
        self.load(progress)

    def unload(self) -> None:
        """Release the image pipeline so another GPU workload can use VRAM."""
        with self._lock:
            pipeline, self._pipeline = self._pipeline, None
        if pipeline is None:
            return
        try:
            pipeline.to("cpu")
        finally:
            del pipeline
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass

    def generate(
        self, prompt: str, width: int | None = None, height: int | None = None,
        progress: Callable[[int, int], None] | None = None, inference_steps: int | None = None,
        seed: int | None = None, cancelled: Callable[[], bool] | None = None,
        negative_prompt: str | None = None,
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
            if negative_prompt:
                options["negative_prompt"] = negative_prompt
            if seed is not None:
                import torch
                options["generator"] = torch.Generator(device=self._device).manual_seed(seed)
            result = self._pipeline(**options)
        return result.images[0]
