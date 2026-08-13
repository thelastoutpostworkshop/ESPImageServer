"""Lazy local LTX-Video 2B distilled adapter for short experimental clips."""

from __future__ import annotations

import os
from pathlib import Path
from threading import Lock
from typing import Callable

from .generation_jobs import GenerationCancelled


class LTXVideoGenerator:
    # The repository also contains a generic, non-distilled Diffusers pipeline.
    # Loading it with ``from_pretrained`` does *not* load the checkpoint advertised
    # by the video page and produces substantially weaker results at short lengths.
    model_id = "Lightricks/LTX-Video · ltxv-2b-0.9.6-distilled-04-25"
    checkpoint_repository = "Lightricks/LTX-Video"
    checkpoint_filename = "ltxv-2b-0.9.6-distilled-04-25.safetensors"
    config_id = "Lightricks/LTX-Video-0.9.5"

    def __init__(self) -> None:
        self._pipeline = None
        self._lock = Lock()

    @property
    def ready(self) -> bool:
        return self._pipeline is not None

    def _load(self, progress: Callable[[int, int, str], None] | None = None) -> None:
        if self._pipeline is not None:
            return
        try:
            import torch
            from diffusers import LTXPipeline
            from huggingface_hub import hf_hub_download, snapshot_download
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
            filename=self.checkpoint_filename,
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
            progress(0, 0, "Loading LTX-Video into your NVIDIA graphics card")
        pipeline = LTXPipeline.from_single_file(
            checkpoint_path,
            config=config_path,
            torch_dtype=torch.bfloat16,
        )
        pipeline.to("cuda")
        # Tiling is provided by the LTX VAE rather than the pipeline itself.
        # This keeps memory use manageable on supported NVIDIA GPUs.
        pipeline.vae.enable_tiling()
        self._pipeline = pipeline

    def generate(
        self, prompt: str, width: int, height: int, num_frames: int, fps: int, steps: int,
        seed: int | None, output_path: Path, progress: Callable[[int, int, str], None],
        cancelled: Callable[[], bool],
    ) -> Path:
        with self._lock:
            self._load(progress)
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
            frames = self._pipeline(
                prompt=prompt,
                negative_prompt="worst quality, blurry, jittery, distorted, flickering",
                width=width,
                height=height,
                num_frames=num_frames,
                num_inference_steps=steps,
                # The distilled checkpoint is trained for CFG 1.0 and up to eight
                # denoising steps.  Higher values visibly degrade its output.
                guidance_scale=1.0,
                generator=generator,
                callback_on_step_end=on_step_end,
            ).frames[0]
            if cancelled():
                raise GenerationCancelled()
            progress(steps, steps, "Encoding MP4 video")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            export_to_video(frames, str(output_path), fps=fps)
            return output_path
