"""Lazy local video generators for short clips on consumer NVIDIA GPUs."""

from __future__ import annotations

from pathlib import Path
import shutil
from threading import RLock
from typing import Callable

import numpy as np
from PIL import Image, ImageOps

from .paths import model_cache_dir as resolve_model_cache_dir
from .generation_jobs import GenerationCancelled
from .download_progress import huggingface_progress


VIDEO_MODELS = {
    "ltx-2b-0.9.6-distilled": {
        "name": "LTX-Video 2B distilled", "description": "Fast short animations with low graphics-card memory use.",
        "family": "ltx", "checkpoint": "ltxv-2b-0.9.6-distilled-04-25.safetensors", "minimum_steps": 4, "maximum_steps": 8, "recommended_steps": 8, "guidance_scale": 1.0,
    },
    "ltx-2b-0.9.6-dev": {
        "name": "LTX-Video 2B quality", "description": "More detail and prompt accuracy, but much slower and more demanding.",
        "family": "ltx", "checkpoint": "ltxv-2b-0.9.6-dev-04-25.safetensors", "minimum_steps": 10, "maximum_steps": 40, "recommended_steps": 30, "guidance_scale": 3.0,
    },
    "wan-2.1-t2v-1.3b": {
        "name": "Wan 2.1 T2V 1.3B", "description": "Detailed text-to-video alternative. Slower, with CPU memory offload for 8 GB graphics cards.",
        "family": "wan", "repository": "Wan-AI/Wan2.1-T2V-1.3B-Diffusers", "minimum_steps": 20, "maximum_steps": 50, "recommended_steps": 30, "guidance_scale": 6.0,
    },

}


def video_model_cache_dir() -> Path:
    return resolve_model_cache_dir()


def video_model_is_cached(model_id: str) -> bool:
    """Return whether the selected video model's primary checkpoint is cached."""
    model = VIDEO_MODELS[model_id]
    cache_dir = video_model_cache_dir()
    if model["family"] == "ltx":
        checkpoint = model["checkpoint"]
        return any((cache_dir / "models--Lightricks--LTX-Video").glob(f"snapshots/**/{checkpoint}"))
    repositories = [model["repository"]]
    return any(
        (cache_dir / ("models--" + repository.replace("/", "--")) / "snapshots").is_dir()
        for repository in repositories
    )


def remove_cached_video_model(model_id: str) -> bool:
    """Remove a video model's downloaded files without touching user creations."""
    model = VIDEO_MODELS[model_id]
    cache_dir = video_model_cache_dir()
    if model["family"] == "ltx":
        paths = [
            cache_dir / "models--Lightricks--LTX-Video",
            cache_dir / "ltx-video-0.9.5-config",
            cache_dir / "ltx-video-text-encoder",
        ]
    else:
        paths = [cache_dir / ("models--" + model["repository"].replace("/", "--"))]
    removed = False
    for path in paths:
        if path.is_dir():
            shutil.rmtree(path)
            removed = True
    return removed


def working_video_size(width: int, height: int) -> tuple[int, int]:
    """Use an LTX-friendly canvas, then scale the result down for the display."""
    shortest, longest = min(width, height), max(width, height)
    scale = min(384 / shortest, 704 / longest)
    working_width = max(256, round(width * scale / 32) * 32)
    working_height = max(256, round(height * scale / 32) * 32)
    return working_width, working_height


def rotate_frame_for_display(frame: Image.Image, rotation: int) -> Image.Image:
    """Rotate an artwork frame into the display's fixed native orientation."""
    if rotation == 90:
        return frame.transpose(Image.Transpose.ROTATE_270)
    if rotation == 180:
        return frame.transpose(Image.Transpose.ROTATE_180)
    if rotation == 270:
        return frame.transpose(Image.Transpose.ROTATE_90)
    if rotation != 0:
        raise ValueError("Video rotation must be 0, 90, 180, or 270 degrees")
    return frame


def working_wan_video_size(width: int, height: int) -> tuple[int, int]:
    """Use Wan's 480p-class canvas while preserving the ESP32 aspect ratio."""
    shortest, longest = min(width, height), max(width, height)
    scale = min(480 / shortest, 832 / longest)
    working_width = max(256, round(width * scale / 16) * 16)
    working_height = max(256, round(height * scale / 16) * 16)
    return working_width, working_height


def frame_to_rgb_image(frame: Image.Image | object) -> Image.Image:
    """Convert Diffusers frame output to a Pillow-compatible RGB image.

    LTX normally returns Pillow images, whereas Wan can return floating-point
    NumPy arrays with RGB values in the 0..1 range. Pillow cannot construct an
    RGB image directly from those float arrays, so normalize them first.
    """
    if isinstance(frame, Image.Image):
        return frame.convert("RGB")

    array = np.asarray(frame)
    if np.issubdtype(array.dtype, np.floating):
        array = np.nan_to_num(array, nan=0.0, posinf=1.0, neginf=0.0)
        if array.size and array.min() >= 0.0 and array.max() <= 1.0:
            array = array * 255.0
        array = np.rint(np.clip(array, 0, 255)).astype(np.uint8)
    elif array.dtype != np.uint8:
        array = np.clip(array, 0, 255).astype(np.uint8)
    return Image.fromarray(array).convert("RGB")


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

    def _load(
        self, model_id: str, progress: Callable[[int, int, str], None] | None = None,
    ) -> None:
        if model_id not in VIDEO_MODELS:
            raise ValueError("Unsupported video model")
        model = VIDEO_MODELS[model_id]
        if self._pipeline is not None and self._loaded_model_id == model_id:
            return
        if self._pipeline is not None:
            self.unload()
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError("Video dependencies are missing. Reinstall ESPImageServer to add video support.") from exc
        if not torch.cuda.is_available():
            raise RuntimeError("Video generation requires a compatible NVIDIA GPU. Video generation is not available in CPU mode.")
        cache_dir = video_model_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        if model["family"] == "wan":
            try:
                from diffusers import AutoencoderKLWan, WanPipeline
                from diffusers.schedulers.scheduling_unipc_multistep import UniPCMultistepScheduler
                from huggingface_hub import snapshot_download
            except ImportError as exc:
                raise RuntimeError("Your installed Diffusers version does not support Wan 2.1. Reinstall ESPImageServer.") from exc
            if progress is not None:
                progress(0, 0, "Checking or downloading Wan 2.1 (first download may take several minutes)")
            repository = VIDEO_MODELS[model_id]["repository"]
            model_path = snapshot_download(
                repository, cache_dir=cache_dir,
                tqdm_class=huggingface_progress("Wan 2.1", progress) if progress else None,
            )
            # The VAE is intentionally float32, as recommended by Diffusers for
            # cleaner Wan decoding. CPU offload keeps it out of VRAM except when
            # it is needed to decode the finished frames.
            vae = AutoencoderKLWan.from_pretrained(
                model_path, subfolder="vae", torch_dtype=torch.float32,
            )
            pipeline = WanPipeline.from_pretrained(
                model_path, vae=vae, torch_dtype=torch.bfloat16,
            )
            pipeline.scheduler = UniPCMultistepScheduler.from_config(pipeline.scheduler.config, flow_shift=5.0)
            if progress is not None:
                progress(0, 0, "Loading Wan 2.1 with graphics-card memory offload")
            pipeline.enable_model_cpu_offload()
            pipeline.vae.enable_tiling()
            pipeline.vae.enable_slicing()
            self._pipeline = pipeline
            self._loaded_model_id = model_id
            return
        try:
            from diffusers import LTXPipeline
            from huggingface_hub import snapshot_download
            from transformers import T5EncoderModel
        except ImportError as exc:
            raise RuntimeError("LTX-Video dependencies are missing. Reinstall ESPImageServer to add video support.") from exc
        # Download with Hugging Face's cache API first. Passing its web URL to
        # from_single_file makes recent Diffusers versions mistake ``resolve``
        # for part of the filename.
        if progress is not None:
            progress(0, 0, "Checking or downloading LTX-Video (first download may take several minutes)")
        checkpoint_root = snapshot_download(
            repo_id=self.checkpoint_repository,
            cache_dir=cache_dir,
            allow_patterns=VIDEO_MODELS[model_id]["checkpoint"],
            tqdm_class=huggingface_progress("LTX-Video", progress) if progress else None,
        )
        checkpoint_path = Path(checkpoint_root) / VIDEO_MODELS[model_id]["checkpoint"]
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
            tqdm_class=huggingface_progress("LTX-Video configuration", progress) if progress else None,
        )
        if progress is not None:
            progress(0, 0, "Checking or downloading the LTX text encoder (first download may take several minutes)")
        text_encoder_root = snapshot_download(
            repo_id=self.checkpoint_repository,
            cache_dir=cache_dir,
            local_dir=cache_dir / "ltx-video-text-encoder",
            local_dir_use_symlinks=False,
            allow_patterns="text_encoder/*",
            tqdm_class=huggingface_progress("LTX text encoder", progress) if progress else None,
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
        model_id: str = "ltx-2b-0.9.6-distilled", rotation: int = 0,
    ) -> Path:
        with self._lock:
            model = VIDEO_MODELS.get(model_id)
            if model is None:
                raise ValueError("Unsupported video model")
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
            if model["family"] == "wan" and source_image_path is not None:
                raise ValueError("Wan 2.1 T2V uses text only; choose an LTX model to animate a Creation Gallery image")
            if source_image_path is not None:
                progress(0, 0, "Preparing your Creation Gallery image for animation")
                with Image.open(source_image_path) as source_image:
                    source_frame = source_image.convert("RGB").copy()
                if model["family"] == "ltx":
                    from diffusers import LTXImageToVideoPipeline

                    generation_pipeline = LTXImageToVideoPipeline(
                        scheduler=self._pipeline.scheduler,
                        vae=self._pipeline.vae,
                        text_encoder=self._pipeline.text_encoder,
                        tokenizer=self._pipeline.tokenizer,
                        transformer=self._pipeline.transformer,
                    )
                    generation_options = {"image": source_frame, "frame_rate": fps}

            if rotation not in {0, 90, 180, 270}:
                raise ValueError("Video rotation must be 0, 90, 180, or 270 degrees")
            artwork_width, artwork_height = (
                (height, width) if rotation in {90, 270} else (width, height)
            )
            # Native ESP32 screens are far below LTX's useful working size.
            # Generate on an aspect-matched, 32-pixel-aligned canvas first,
            # then rotate and downscale the decoded frames to the display dimensions.
            generation_width, generation_height = (
                working_wan_video_size(artwork_width, artwork_height)
                if model["family"] == "wan" else working_video_size(artwork_width, artwork_height)
            )
            frames = generation_pipeline(
                prompt=prompt,
                negative_prompt="worst quality, blurry, jittery, distorted, flickering",
                width=generation_width,
                height=generation_height,
                num_frames=num_frames,
                num_inference_steps=steps,
                guidance_scale=model["guidance_scale"],
                generator=generator,
                callback_on_step_end=on_step_end,
                **generation_options,
            ).frames[0]
            if cancelled():
                raise GenerationCancelled()
            progress(steps, steps, "Decoding generated video frames")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if (generation_width, generation_height) != (artwork_width, artwork_height):
                progress(steps, steps, "Resizing video for your ESP32 display")
                frames = [
                    ImageOps.fit(
                        frame_to_rgb_image(frame),
                        (artwork_width, artwork_height), method=Image.Resampling.LANCZOS,
                    )
                    for frame in frames
                ]
            if rotation:
                progress(steps, steps, "Rotating video for your ESP32 display")
                frames = [rotate_frame_for_display(frame_to_rgb_image(frame), rotation) for frame in frames]
            progress(steps, steps, "Encoding MP4 video")
            export_to_video(frames, str(output_path), fps=fps)
            return output_path
