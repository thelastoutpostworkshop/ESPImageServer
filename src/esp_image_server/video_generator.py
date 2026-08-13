"""Lazy local LTX-Video 2B distilled adapter for short experimental clips."""

from __future__ import annotations

import os
from pathlib import Path
from threading import RLock
from typing import Callable

from PIL import Image, ImageOps

from .generation_jobs import GenerationCancelled


VIDEO_MODELS = {
    "ltx-2b-0.9.6-distilled": {
        "name": "LTX-Video 2B distilled", "description": "Fast short animations with low graphics-card memory use.",
        "checkpoint": "ltxv-2b-0.9.6-distilled-04-25.safetensors", "minimum_steps": 4, "maximum_steps": 8, "recommended_steps": 8, "guidance_scale": 1.0,
    },
    "ltx-2b-0.9.6-dev": {
        "name": "LTX-Video 2B quality", "description": "More detail and prompt accuracy, but much slower and more demanding.",
        "checkpoint": "ltxv-2b-0.9.6-dev-04-25.safetensors", "minimum_steps": 10, "maximum_steps": 40, "recommended_steps": 30, "guidance_scale": 3.0,
    },
}


def working_video_size(width: int, height: int) -> tuple[int, int]:
    """Use an LTX-friendly canvas, then scale the result down for the display."""
    shortest, longest = min(width, height), max(width, height)
    scale = min(384 / shortest, 704 / longest)
    working_width = max(256, round(width * scale / 32) * 32)
    working_height = max(256, round(height * scale / 32) * 32)
    return working_width, working_height


class LTXVideoGenerator:
    # The repository also contains a generic, non-distilled Diffusers pipeline.
    # Loading it with ``from_pretrained`` does *not* load the checkpoint advertised
    # by the video page and produces substantially weaker results at short lengths.
    model_id = "Lightricks/LTX-Video · ltxv-2b-0.9.6-distilled-04-25"
    checkpoint_repository = "Lightricks/LTX-Video"
    config_id = "Lightricks/LTX-Video-0.9.5"

    def __init__(self) -> None:
        self._pipeline = None
        self._loaded_model_id: str | None = None
        self._lock = RLock()

    @property
    def ready(self) -> bool:
        return self._pipeline is not None

    def unload(self) -> None:
        """Release LTX-Video from the GPU until the next video request."""
        with self._lock:
            pipeline, self._pipeline = self._pipeline, None
            self._loaded_model_id = None
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

    def _load(self, model_id: str, progress: Callable[[int, int, str], None] | None = None) -> None:
        if model_id not in VIDEO_MODELS:
            raise ValueError("Unsupported video model")
        if self._pipeline is not None and self._loaded_model_id == model_id:
            return
        if self._pipeline is not None:
            self.unload()
        try:
            import torch
            from diffusers import LTXPipeline
            from huggingface_hub import hf_hub_download, snapshot_download
            from transformers import T5EncoderModel
        except ImportError as exc:
            raise RuntimeError("Video dependencies are missing. Reinstall ESPImageServer to add LTX-Video support.") from exc
        if not torch.cuda.is_available():
            raise RuntimeError("LTX-Video requires a compatible NVIDIA GPU. Video generation is not available in CPU mode.")
        cache_dir = Path(os.getenv("ESP_IMAGE_MODEL_CACHE", Path.home() / ".cache" / "ESPImageServer" / "models"))
        cache_dir.mkdir(parents=True, exist_ok=True)
        # Download with Hugging Face's cache API first. Passing its web URL to
        # from_single_file makes recent Diffusers versions mistake ``resolve``
        # for part of the filename.
        if progress is not None:
            progress(0, 0, "Checking or downloading LTX-Video (first download may take several minutes)")
        checkpoint_path = hf_hub_download(
            repo_id=self.checkpoint_repository,
            filename=VIDEO_MODELS[model_id]["checkpoint"],
            cache_dir=cache_dir,
        )
        # This original-format checkpoint contains the actual 2B distilled
        # model. Diffusers recognises its format and uses the 0.9.5 component
        # configuration.
        if progress is not None:
            progress(0, 0, "Preparing LTX-Video configuration files")
        # Keep the configuration in a normal application folder rather than a
        # Hugging Face snapshot. This avoids Windows symlink creation, which is
        # commonly denied for standard (non-developer-mode) user accounts.
        config_path = snapshot_download(
            repo_id=self.config_id,
            cache_dir=cache_dir,
            local_dir=cache_dir / "ltx-video-0.9.5-config",
            local_dir_use_symlinks=False,
            allow_patterns=[
                "model_index.json", "scheduler/*", "text_encoder/config.json",
                "tokenizer/*", "transformer/config.json", "vae/config.json",
            ],
        )
        if progress is not None:
            progress(0, 0, "Checking or downloading the LTX text encoder (first download may take several minutes)")
        text_encoder_root = snapshot_download(
            repo_id=self.checkpoint_repository,
            cache_dir=cache_dir,
            local_dir=cache_dir / "ltx-video-text-encoder",
            local_dir_use_symlinks=False,
            allow_patterns="text_encoder/*",
        )
        text_encoder = T5EncoderModel.from_pretrained(
            Path(text_encoder_root) / "text_encoder",
            torch_dtype=torch.bfloat16,
            local_files_only=True,
        )
        if progress is not None:
            progress(0, 0, "Loading LTX-Video into your NVIDIA graphics card")
        pipeline = LTXPipeline.from_single_file(
            checkpoint_path,
            config=config_path,
            torch_dtype=torch.bfloat16,
            text_encoder=text_encoder,
        )
        pipeline.to("cuda")
        # Tiling is provided by the LTX VAE rather than the pipeline itself.
        # This keeps memory use manageable on supported NVIDIA GPUs.
        pipeline.vae.enable_tiling()
        self._pipeline = pipeline
        self._loaded_model_id = model_id

    def generate(
        self, prompt: str, width: int, height: int, num_frames: int, fps: int, steps: int,
        seed: int | None, output_path: Path, progress: Callable[[int, int, str], None],
        cancelled: Callable[[], bool], source_image_path: Path | None = None,
        model_id: str = "ltx-2b-0.9.6-distilled",
    ) -> Path:
        with self._lock:
            self._load(model_id, progress)
            import torch
            from diffusers.utils import export_to_video
            if cancelled():
                raise GenerationCancelled()

            def on_step_end(_pipe, step, _timestep, callback_kwargs):
                if cancelled():
                    raise GenerationCancelled()
                progress(step + 1, steps, "Generating video frames")
                return callback_kwargs

            generator = torch.Generator(device="cuda").manual_seed(seed) if seed is not None else None
            generation_pipeline = self._pipeline
            generation_options: dict[str, object] = {}
            if source_image_path is not None:
                from diffusers import LTXImageToVideoPipeline

                progress(0, 0, "Preparing your Creation Gallery image for animation")
                with Image.open(source_image_path) as source_image:
                    source_frame = source_image.convert("RGB").copy()
                generation_pipeline = LTXImageToVideoPipeline(
                    scheduler=self._pipeline.scheduler,
                    vae=self._pipeline.vae,
                    text_encoder=self._pipeline.text_encoder,
                    tokenizer=self._pipeline.tokenizer,
                    transformer=self._pipeline.transformer,
                )
                generation_options = {"image": source_frame, "frame_rate": fps}

            # Native ESP32 screens are far below LTX's useful working size.
            # Generate on an aspect-matched, 32-pixel-aligned canvas first,
            # then downscale the decoded frames to the display dimensions.
            generation_width, generation_height = working_video_size(width, height)
            frames = generation_pipeline(
                prompt=prompt,
                negative_prompt="worst quality, blurry, jittery, distorted, flickering",
                width=generation_width,
                height=generation_height,
                num_frames=num_frames,
                num_inference_steps=steps,
                guidance_scale=VIDEO_MODELS[model_id]["guidance_scale"],
                generator=generator,
                callback_on_step_end=on_step_end,
                **generation_options,
            ).frames[0]
            if cancelled():
                raise GenerationCancelled()
            progress(steps, steps, "Decoding generated video frames")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if (generation_width, generation_height) != (width, height):
                progress(steps, steps, "Resizing video for your ESP32 display")
                frames = [ImageOps.fit(frame.convert("RGB"), (width, height), method=Image.Resampling.LANCZOS) for frame in frames]
            progress(steps, steps, "Encoding MP4 video")
            export_to_video(frames, str(output_path), fps=fps)
            return output_path
