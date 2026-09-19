"""HTTP API for ESPImageServer."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
import hashlib
from io import BytesIO
import json
import logging
from math import gcd
import os
from pathlib import Path
import subprocess
from threading import Timer
from time import perf_counter
from typing import Literal, Protocol
import webbrowser

from fastapi import FastAPI, Header, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from PIL import Image
from starlette.background import BackgroundTask

from .config import Settings
from .app_settings import AppSettingsStore
from .display import ActiveDisplayStore
from .display_commands import LEGACY_DISPLAY_ID, DisplayCommandStore
from .display_registry import (
    DisplayDevice,
    DisplayNotFoundError,
    DisplayRegistry,
    DisplayRegistryError,
)
from .display_settings import DisplaySettingsStore, VALID_ROTATIONS
from .devices import DeviceError, DeviceManager
from .diagnostics import ConsoleLogStore, DiagnosticLogStore
from .generator import DiffusersGenerator
from .generation_jobs import GenerationCancelled
from .generation_queue import GenerationQueue
from .generation_size import optimal_generation_size
from .image_processor import to_display_jpeg, to_jpeg
from .image_library import ImageLibrary
from .latest_image import LatestImage, LatestImageAssignment, LatestImageStore
from .mdns import MdnsAdvertiser, active_lan_address
from .models import MODELS, get_model, model_is_cached, model_settings, remove_cached_model
from .model_settings import ModelSelectionStore
from .mjpeg_cache import MjpegConversionCache
from .video_generator import LTXVideoGenerator, VIDEO_MODELS, remove_cached_video_model, video_model_is_cached
from .video_library import VideoLibrary, bundled_ffmpeg_executable
from .version import APP_VERSION

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEVELOPMENT_WEB_BUILD = PROJECT_ROOT / "frontend" / "dist"
INSTALLED_WEB_BUILD = PROJECT_ROOT / "web"
WEB_BUILD = DEVELOPMENT_WEB_BUILD if DEVELOPMENT_WEB_BUILD.is_dir() else INSTALLED_WEB_BUILD
JPEG_METADATA_PREFIX = b"ESPImageServer metadata:"


def embed_jpeg_metadata(jpeg: bytes, metadata: dict[str, object]) -> bytes:
    """Store portable ESPImageServer settings in a standard JPEG comment segment."""
    if not jpeg.startswith(b"\xff\xd8"):
        return jpeg
    payload = JPEG_METADATA_PREFIX + json.dumps(metadata, separators=(",", ":")).encode("utf-8")
    if len(payload) > 65_533:
        logger.warning("Image metadata is too large to embed in JPEG; saving library index only")
        return jpeg
    segment_length = len(payload) + 2
    comment = b"\xff\xfe" + segment_length.to_bytes(2, "big") + payload
    return jpeg[:2] + comment + jpeg[2:]


def extract_jpeg_metadata(jpeg: bytes) -> dict[str, object] | None:
    """Read ESPImageServer metadata embedded in a JPEG comment segment."""
    if len(jpeg) < 6 or not jpeg.startswith(b"\xff\xd8\xff\xfe"):
        return None
    segment_length = int.from_bytes(jpeg[4:6], "big")
    payload = jpeg[6:6 + segment_length - 2]
    if not payload.startswith(JPEG_METADATA_PREFIX):
        return None
    try:
        metadata = json.loads(payload[len(JPEG_METADATA_PREFIX):].decode("utf-8"))
    except (UnicodeDecodeError, ValueError, TypeError):
        return None
    return metadata if isinstance(metadata, dict) else None


class ImageGenerator(Protocol):
    ready: bool
    device: str

    def load(self) -> None: ...

    def activate_model(self, settings: Settings, progress=None) -> None: ...

    def unload(self) -> None: ...

    def generate(self, prompt: str, width: int | None = None, height: int | None = None, progress=None, inference_steps=None, seed=None, negative_prompt=None) -> Image.Image: ...


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=1_000, description="Text to turn into an image")
    model_id: str | None = Field(default=None, min_length=1, max_length=200, description="Image model to use for this job")
    steps: int | None = Field(default=None, ge=1, le=100, description="Model inference steps")
    seed: int | None = Field(default=None, ge=0, le=4_294_967_295, description="Optional repeatable random seed")
    negative_prompt: str | None = Field(default=None, max_length=1_000)
    display_ids: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=32,
        description="Optional registered displays that should receive this image",
    )
    broadcast_aspect_mode: Literal["crop", "fit", "separate"] | None = Field(
        default=None,
        description=(
            "Required for targets with mixed display aspect ratios: crop to fill, "
            "fit with black borders, or generate separate compositions per aspect ratio"
        ),
    )


class DisplayAnnouncement(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    width: int = Field(ge=64, le=1_024)
    height: int = Field(ge=64, le=1_024)
    firmware_version: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$",
    )


class DisplaySettingsRequest(BaseModel):
    rotation: int


class RegisterDisplayRequest(DisplayAnnouncement):
    model_config = ConfigDict(extra="forbid")
    hardware_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9:._-]+$")
    capabilities: dict[str, bool] = Field(default_factory=dict)


class DisplayHeartbeatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    firmware_version: str | None = Field(
        default=None,
        min_length=1,
        max_length=32,
        pattern=r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$",
    )
    capabilities: dict[str, bool] | None = None


class UpdateDisplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=64)


class DisplayTargetsRequest(BaseModel):
    """Optional explicit recipients for an existing Creation Gallery image."""

    model_config = ConfigDict(extra="forbid")
    display_ids: list[str] | None = Field(default=None, min_length=1, max_length=32)
    broadcast_aspect_mode: Literal["crop", "fit"] | None = Field(
        default=None,
        description="Required for mixed-aspect targets: crop to fill or fit with black borders",
    )


class AppSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image_library_location: str | None = Field(default=None, min_length=1)
    jpeg_quality: int | None = Field(default=None, ge=1, le=100)
    video_jpeg_quality: int | None = Field(default=None, ge=2, le=31)
    auto_save_images: bool | None = None
    auto_save_videos: bool | None = None
    confirm_deletion: bool | None = None


class RegisterDeviceRequest(BaseModel):
    pairing_code: str = Field(min_length=6, max_length=6)
    name: str = Field(min_length=1, max_length=64)


class AcknowledgeImageRequest(BaseModel):
    image_id: str = Field(min_length=1, max_length=64)


class DisplayCommandAcknowledgement(BaseModel):
    success: bool
    detail: str = Field(default="", max_length=200)


class DisplayCommandProgress(BaseModel):
    stage: Literal["downloading", "verifying"]
    received_bytes: int = Field(ge=0, le=64 * 1024 * 1024)
    total_bytes: int = Field(ge=0, le=64 * 1024 * 1024)


class DisplaySDCardReport(BaseModel):
    available: bool
    offline_experience_saved: bool | None = None
    verified_saves: bool = False
    mode: str = Field(pattern="^(server_controlled|offline_slideshow|offline_video_loop|preview_slideshow|preview_video_loop|live_images|sd_card)$")
    total_bytes: int = Field(ge=0)
    used_bytes: int = Field(ge=0)
    files: list[dict[str, object]] = Field(default_factory=list)
    offline_experience: str = Field(default="slideshow", pattern="^(slideshow|video_loop)$")
    slideshow_interval_ms: int = Field(default=15_000, ge=500, le=3_600_000)
    slideshow_order: str = Field(default="newest_first", pattern="^(newest_first|oldest_first|random)$")


class DisplayExperienceRequest(BaseModel):
    offline_experience: str = Field(default="slideshow", pattern="^(slideshow|video_loop)$")
    slideshow_interval_ms: int = Field(ge=500, le=3_600_000)
    slideshow_order: str = Field(pattern="^(newest_first|oldest_first|random)$")


class VideoGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=1_000)
    width: int = Field(default=512, ge=1, le=768)
    height: int = Field(default=320, ge=1, le=768)
    num_frames: int = Field(default=25, ge=9, le=249)
    fps: int = Field(default=8, ge=4, le=24)
    steps: int = Field(default=8, ge=4, le=50)
    model_id: str = Field(default="ltx-2b-0.9.6-distilled")
    seed: int | None = Field(default=None, ge=0, le=4_294_967_295)
    source_image_id: str | None = Field(default=None, min_length=1, max_length=64)
    display_ids: list[str] | None = Field(default=None, min_length=1, max_length=1)


def create_app(
    settings: Settings | None = None,
    generator: ImageGenerator | None = None,
    device_manager: DeviceManager | None = None,
    latest_image_store: LatestImageStore | None = None,
    active_display_store: ActiveDisplayStore | None = None,
    display_settings_store: DisplaySettingsStore | None = None,
    display_registry: DisplayRegistry | None = None,
    model_selection_store: ModelSelectionStore | None = None,
    image_library: ImageLibrary | None = None,
    app_settings_store: AppSettingsStore | None = None,
    generation_queue: GenerationQueue | None = None,
    display_command_store: DisplayCommandStore | None = None,
    mjpeg_cache: MjpegConversionCache | None = None,
    video_generator: LTXVideoGenerator | None = None,
    enable_mdns: bool = True,
) -> FastAPI:
    supplied_settings = settings is not None
    settings = settings or Settings.from_env()
    model_selection_store = model_selection_store or ModelSelectionStore(settings.model_id)
    active_model_id = settings.model_id if supplied_settings else model_selection_store.get()
    try:
        active_settings = model_settings(settings, active_model_id)
    except ValueError:
        active_model_id = settings.model_id
        active_settings = settings
    generator = generator or DiffusersGenerator(active_settings)
    device_manager = device_manager or DeviceManager()
    latest_image_store = latest_image_store or LatestImageStore()
    active_display_store = active_display_store or ActiveDisplayStore()
    display_settings_store = display_settings_store or DisplaySettingsStore()
    display_registry = display_registry or DisplayRegistry()
    video_output_path = Path(os.getenv("LOCALAPPDATA", Path.home() / ".local")) / "ESPImageServer" / "videos"
    generation_queue = generation_queue or GenerationQueue(video_result_root=video_output_path)
    diagnostics = DiagnosticLogStore()
    diagnostics.setFormatter(logging.Formatter("%(message)s"))
    console_output = ConsoleLogStore()
    console_output.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root_logger = logging.getLogger()
    uvicorn_logger = logging.getLogger("uvicorn")
    root_logger.addHandler(diagnostics)
    root_logger.addHandler(console_output)
    display_command_store = display_command_store or DisplayCommandStore()
    video_generator = video_generator or LTXVideoGenerator()
    model_loading_status: dict[str, object] = {"active": False, "step": 0, "steps": 0, "stage": ""}
    mjpeg_cache = mjpeg_cache or MjpegConversionCache(video_output_path / "display-mjpeg")
    sd_thumbnail_path = Path(os.getenv("LOCALAPPDATA", Path.home() / ".local")) / "ESPImageServer" / "display_sd_thumbnails"
    app_settings_store = app_settings_store or AppSettingsStore()
    persisted_app_settings = app_settings_store.get()
    library_location = persisted_app_settings.get("image_library_location")
    image_library = image_library or ImageLibrary(Path(library_location) if isinstance(library_location, str) else None)
    video_library = VideoLibrary(image_library.path)
    jpeg_quality = persisted_app_settings.get("jpeg_quality", settings.jpeg_quality)
    jpeg_quality = jpeg_quality if isinstance(jpeg_quality, int) and 1 <= jpeg_quality <= 100 else settings.jpeg_quality
    video_jpeg_quality = persisted_app_settings.get("video_jpeg_quality", 10)
    video_jpeg_quality = video_jpeg_quality if isinstance(video_jpeg_quality, int) and 2 <= video_jpeg_quality <= 31 else 10
    auto_save_images = persisted_app_settings.get("auto_save_images", True)
    auto_save_images = auto_save_images if isinstance(auto_save_images, bool) else True
    auto_save_videos = persisted_app_settings.get("auto_save_videos", True)
    auto_save_videos = auto_save_videos if isinstance(auto_save_videos, bool) else True
    confirm_deletion = persisted_app_settings.get("confirm_deletion", True)
    confirm_deletion = confirm_deletion if isinstance(confirm_deletion, bool) else True

    def cleanup_temporary_data() -> None:
        """Bound disposable data without ever evicting active or in-use media."""
        removed_jobs = generation_queue.prune_completed()
        removed_commands = display_command_store.prune_completed()
        referenced_cache_files = mjpeg_cache.paths_for_video_ids(display_command_store.referenced_video_ids())
        removed_conversions = mjpeg_cache.cleanup(referenced_cache_files)
        if removed_jobs or removed_commands or removed_conversions:
            logger.info(
                "Temporary-data cleanup removed %s generation jobs, %s display commands, and %s MJPEG conversions",
                removed_jobs, removed_commands, removed_conversions,
            )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Uvicorn keeps its own non-propagating console logger. Mirror it as
        # well so startup and server errors are visible in the Console tab.
        uvicorn_logger.addHandler(console_output)
        cleanup_temporary_data()
        mdns = MdnsAdvertiser(settings.port) if enable_mdns else None
        if mdns is not None:
            try:
                mdns.start()
                logger.info("Local network address: http://espimageserver.local:%s/", settings.port)
            except Exception:
                logger.exception("Could not advertise espimageserver.local")
        logger.info("Browser test page: http://127.0.0.1:%s/", settings.port)
        if settings.host in {"0.0.0.0", "::"}:
            logger.info(
                "Network binding: %s:%s (0.0.0.0 is for ESP32/LAN access, not a browser address)",
                settings.host,
                settings.port,
            )
        else:
            logger.info("Server address: http://%s:%s/", settings.host, settings.port)
        logger.info("Image model will download and load when the user selects it; device=%s", generator.device)
        if os.getenv("ESP_IMAGE_OPEN_BROWSER") == "1":
            Timer(0.5, lambda: webbrowser.open_new_tab(f"http://127.0.0.1:{settings.port}/")).start()
        try:
            yield
        finally:
            if mdns is not None:
                mdns.close()
            cleanup_temporary_data()
            generation_queue.close()
            root_logger.removeHandler(diagnostics)
            root_logger.removeHandler(console_output)
            uvicorn_logger.removeHandler(console_output)

    app = FastAPI(title="ESPImageServer", version=APP_VERSION, lifespan=lifespan)
    app.state.device_manager = device_manager
    app.state.latest_image_store = latest_image_store
    app.state.active_display_store = active_display_store
    app.state.display_settings_store = display_settings_store
    app.state.display_registry = display_registry
    app.state.model_selection_store = model_selection_store
    app.state.generation_queue = generation_queue
    app.state.diagnostics = diagnostics
    app.state.console_output = console_output
    app.state.display_command_store = display_command_store
    app.state.mjpeg_cache = mjpeg_cache
    app.state.image_library = image_library
    app.state.video_library = video_library
    app.state.app_settings_store = app_settings_store
    app.mount(
        "/assets",
        StaticFiles(directory=Path(__file__).with_name("static")),
        name="assets",
    )
    if WEB_BUILD.is_dir():
        app.mount("/ui", StaticFiles(directory=WEB_BUILD), name="ui")

    @app.get("/", include_in_schema=False)
    def test_page() -> Response:
        index = WEB_BUILD / "index.html"
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-store, max-age=0"})
        return Response("Frontend build is missing. Run: npm --prefix frontend run build", status_code=503)

    @app.get("/health")
    def health() -> dict[str, object]:
        active_job = generation_queue.active_job()
        image_job = active_job if active_job and active_job.kind == "image" else None
        video_job = active_job if active_job and active_job.kind == "video" else None
        return {
            "status": "ready" if generator.ready else "loading",
            "device": generator.device,
            "generating": image_job is not None,
            "image_generating": image_job is not None,
            "video_generating": video_job is not None,
            "active_image_job": image_job.as_dict() if image_job else None,
            "active_video_job": video_job.as_dict() if video_job else None,
            "queue_depth": sum(1 for job in generation_queue.list() if job["status"] in {"queued", "running", "cancelling"}),
        }

    @app.get("/diagnostics")
    def get_diagnostics() -> list[dict[str, str]]:
        return diagnostics.list()

    @app.delete("/diagnostics", status_code=status.HTTP_204_NO_CONTENT)
    def clear_diagnostics() -> Response:
        diagnostics.clear()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/console-output")
    def get_console_output() -> list[str]:
        return console_output.list()

    @app.delete("/console-output", status_code=status.HTTP_204_NO_CONTENT)
    def clear_console_output() -> Response:
        console_output.clear()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/server-info")
    def server_info() -> dict[str, object]:
        lan_address = active_lan_address()
        model_details = {
            "stabilityai/sd-turbo": (
                "SD-Turbo",
                "Fast local AI image model, designed for quick results.",
            ),
            "segmind/SSD-1B": (
                "Segmind SSD-1B",
                "Higher-quality local AI image model; slower and best with an NVIDIA graphics card.",
            ),
        }
        model_name, model_description = model_details.get(
            active_model_id, (active_model_id, "Local AI image model selected in the app.")
        )
        if generator.device == "cuda":
            processing = "NVIDIA graphics card acceleration — fast image generation."
        elif generator.device == "cpu":
            processing = "Computer processor mode — works broadly, but image generation can take longer."
        else:
            processing = f"Processing device: {generator.device}"
        return {
            "version": app.version,
            "model_name": get_model(active_model_id).name,
            "model_id": active_model_id,
            "model_description": get_model(active_model_id).description,
            "processing": processing,
            "default_width": active_settings.output_width,
            "default_height": active_settings.output_height,
            "port": settings.port,
            "local_network_url": f"http://{lan_address}:{settings.port}" if lan_address else None,
        }

    @app.get("/models")
    def list_models() -> list[dict[str, object]]:
        return [
            {
                "id": model.model_id,
                "name": model.name,
                "model_card_url": f"https://huggingface.co/{model.model_id}",
                "description": model.description,
                "recommendation": model.recommendation,
                "hardware": model.hardware,
                "speed": model.speed,
                "default_steps": model.inference_steps,
                "minimum_steps": model.minimum_steps,
                "maximum_steps": model.maximum_steps,
                "supports_negative_prompt": model.supports_negative_prompt,
                "active": model.model_id == active_model_id,
                "installed": model_is_cached(model, active_settings.model_cache_dir),
            }
            for model in MODELS
        ]

    @app.post("/models/{model_id:path}/select")
    async def select_model(model_id: str) -> dict[str, object]:
        nonlocal active_model_id, active_settings
        try:
            selected_settings = model_settings(settings, model_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="This model is not available in ESPImageServer") from exc
        if model_id == active_model_id and generator.ready:
            return {"status": "active", "model_id": model_id}
        if generation_queue.has_active_job():
            active_settings = selected_settings
            active_model_id = model_id
            model_selection_store.set(model_id)
            logger.info("Image model changed to %s for subsequent queued jobs", model_id)
            return {"status": "selected", "model_id": model_id}
        try:
            model_loading_status.update(active=True, step=0, steps=0, stage="Preparing image model")
            def report_download(step: int, steps: int, stage: str) -> None:
                model_loading_status.update(active=True, step=step, steps=steps, stage=stage)
            video_generator.unload()
            await run_in_threadpool(generator.activate_model, selected_settings, report_download)
            model_selection_store.set(model_id)
        except Exception:
            logger.exception("Unable to activate image model '%s'", model_id)
            raise HTTPException(status_code=500, detail="Unable to download or load the selected model") from None
        finally:
            model_loading_status["active"] = False
        active_settings = selected_settings
        active_model_id = model_id
        logger.info("Active image model changed to %s", model_id)
        return {"status": "active", "model_id": model_id}

    @app.delete("/models/{model_id:path}")
    def remove_image_model(model_id: str) -> dict[str, object]:
        try:
            model = get_model(model_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Image model not found") from exc
        if generation_queue.has_active_job():
            raise HTTPException(status_code=409, detail="Wait for the current image generation to finish before removing an image model")
        generator.unload()
        removed = remove_cached_model(model, active_settings.model_cache_dir)
        return {"removed": removed}

    @app.get("/model-loading-status")
    def get_model_loading_status() -> dict[str, object]:
        return model_loading_status.copy()

    @app.get("/display")
    def active_display() -> JSONResponse:
        profile = active_display_store.get()
        if profile is None:
            payload: dict[str, object] = {"connected": False}
        else:
            payload = {
                "connected": True,
                "name": profile.name,
                "width": profile.width,
                "height": profile.height,
                "firmware_version": profile.firmware_version,
            }
        return JSONResponse(content=payload, headers={"Cache-Control": "no-store, max-age=0"})

    @app.post("/display", status_code=status.HTTP_201_CREATED)
    def announce_display(announcement: DisplayAnnouncement) -> dict[str, object]:
        profile = active_display_store.set(
            announcement.name,
            announcement.width,
            announcement.height,
            announcement.firmware_version,
        )
        logger.info(
            "Active display announced: %s (%sx%s), firmware %s",
            profile.name,
            profile.width,
            profile.height,
            profile.firmware_version,
        )
        return {
            "status": "registered",
            "name": profile.name,
            "width": profile.width,
            "height": profile.height,
            "firmware_version": profile.firmware_version,
        }

    @app.get("/display-settings")
    def get_display_settings() -> dict[str, int]:
        return {"rotation": display_settings_store.get_rotation()}

    @app.put("/display-settings")
    def update_display_settings(request: DisplaySettingsRequest) -> dict[str, int]:
        if request.rotation not in VALID_ROTATIONS:
            raise HTTPException(status_code=422, detail="Image rotation must be 0, 90, 180, or 270 degrees")
        return {"rotation": display_settings_store.set_rotation(request.rotation)}

    @app.get("/video-display-settings")
    def get_video_display_settings() -> dict[str, int]:
        return {"rotation": display_settings_store.get_video_rotation()}

    @app.put("/video-display-settings")
    def update_video_display_settings(request: DisplaySettingsRequest) -> dict[str, int]:
        if request.rotation not in VALID_ROTATIONS:
            raise HTTPException(status_code=422, detail="Video rotation must be 0, 90, 180, or 270 degrees")
        return {"rotation": display_settings_store.set_video_rotation(request.rotation)}

    def get_registered_display(display_id: str) -> DisplayDevice:
        try:
            return display_registry.get(display_id)
        except DisplayNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def display_command_activity(command: dict[str, object], outcome: str) -> str:
        labels = {
            "save_latest": "Save latest image",
            "save_saved_image": "Save image",
            "save_saved_video": "Save video",
            "refresh_sd_card": "Refresh SD card",
            "display_sd_file": "Show SD-card file",
            "delete_sd_file": "Delete SD-card file",
            "set_mode": "Change display mode",
            "set_display_experience": "Save display experience",
            "preview_display_experience": "Preview display experience",
            "stop_display_experience_preview": "Stop experience preview",
        }
        label = labels.get(str(command.get("type", "")), "Display command")
        return f"{label} {outcome}"

    def requested_target_displays(display_ids: list[str] | None) -> list[DisplayDevice]:
        """Resolve an explicit recipient list while preserving its chosen order."""
        if display_ids is None:
            return []
        unique_ids = list(dict.fromkeys(display_ids))
        return [get_registered_display(display_id) for display_id in unique_ids]

    def display_artwork_dimensions(display: DisplayDevice) -> tuple[int, int]:
        return (
            (display.height, display.width)
            if display.rotation in {90, 270}
            else (display.width, display.height)
        )

    def target_aspect_groups(targets: list[DisplayDevice]) -> list[list[DisplayDevice]]:
        """Group targets by their physical artwork aspect ratio in chosen order."""
        groups: dict[tuple[int, int], list[DisplayDevice]] = {}
        for display in targets:
            width, height = display_artwork_dimensions(display)
            divisor = gcd(width, height)
            groups.setdefault((width // divisor, height // divisor), []).append(display)
        return list(groups.values())

    def resolve_broadcast_aspect_mode(
        targets: list[DisplayDevice], requested_mode: str | None, *, allow_separate: bool,
    ) -> str:
        """Require an explicit crop, fit, or separate-artwork policy when needed."""
        if requested_mode == "separate" and not allow_separate:
            raise HTTPException(
                status_code=422,
                detail="Separate artwork is available only when generating a new image.",
            )
        if len(target_aspect_groups(targets)) > 1 and requested_mode is None:
            choices = "crop, fit, or separate artwork" if allow_separate else "crop or fit"
            raise HTTPException(
                status_code=422,
                detail=(
                    "Selected displays have different aspect ratios. "
                    f"Choose {choices} with broadcast_aspect_mode."
                ),
            )
        return requested_mode or "crop"

    def rendered_jpeg(
        image: LatestImage,
        *,
        width: int,
        height: int,
        rotation: int,
        aspect_mode: str = "crop",
    ) -> tuple[bytes, str]:
        rendition = latest_image_store.rendition(
            image,
            width=width,
            height=height,
            rotation=rotation,
            quality=jpeg_quality,
            aspect_mode=aspect_mode,
        )
        metadata = extract_jpeg_metadata(image.jpeg)
        jpeg = embed_jpeg_metadata(rendition.jpeg, metadata) if metadata is not None else rendition.jpeg
        return jpeg, rendition.etag

    def latest_image_response(
        assignment: LatestImageAssignment | None,
        *,
        width: int,
        height: int,
        rotation: int,
        if_none_match: str | None,
    ) -> Response:
        if assignment is None:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        jpeg, etag = rendered_jpeg(
            assignment.image,
            width=width,
            height=height,
            rotation=rotation,
            aspect_mode=assignment.aspect_mode,
        )
        if if_none_match == etag:
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
        return Response(
            content=jpeg,
            media_type="image/jpeg",
            headers={"ETag": etag, "Cache-Control": "no-cache"},
        )

    @app.post("/displays/register", status_code=status.HTTP_201_CREATED)
    def register_display(request: RegisterDisplayRequest) -> dict[str, object]:
        return display_registry.register(
            request.hardware_id,
            request.name,
            request.width,
            request.height,
            request.firmware_version,
            request.capabilities,
        ).as_dict()

    @app.get("/displays")
    def list_registered_displays() -> list[dict[str, object]]:
        return [display.as_dict() for display in display_registry.list()]

    @app.get("/displays/{display_id}")
    def get_registered_display_route(display_id: str) -> dict[str, object]:
        return get_registered_display(display_id).as_dict()

    @app.patch("/displays/{display_id}")
    def update_registered_display(
        display_id: str, request: UpdateDisplayRequest,
    ) -> dict[str, object]:
        try:
            return display_registry.set_name(display_id, request.name).as_dict()
        except DisplayNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/displays/{display_id}/heartbeat")
    def heartbeat_registered_display(
        display_id: str,
        request: DisplayHeartbeatRequest | None = None,
    ) -> dict[str, object]:
        try:
            display = display_registry.heartbeat(
                display_id,
                request.firmware_version if request is not None else None,
                request.capabilities if request is not None else None,
            )
        except DisplayNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"status": "ok", "display": display.as_dict()}

    @app.get("/displays/{display_id}/display-settings")
    def get_registered_display_settings(display_id: str) -> dict[str, int]:
        return {"rotation": get_registered_display(display_id).rotation}

    @app.put("/displays/{display_id}/display-settings")
    def update_registered_display_settings(
        display_id: str, request: DisplaySettingsRequest,
    ) -> dict[str, int]:
        try:
            display = display_registry.set_rotation(display_id, request.rotation)
        except DisplayNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DisplayRegistryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"rotation": display.rotation}

    @app.get("/displays/{display_id}/video-display-settings")
    def get_registered_video_display_settings(display_id: str) -> dict[str, int]:
        return {"rotation": get_registered_display(display_id).video_rotation}

    @app.put("/displays/{display_id}/video-display-settings")
    def update_registered_video_display_settings(
        display_id: str, request: DisplaySettingsRequest,
    ) -> dict[str, int]:
        try:
            display = display_registry.set_video_rotation(display_id, request.rotation)
        except DisplayNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DisplayRegistryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"rotation": display.video_rotation}

    @app.post("/display-commands/save-latest", status_code=status.HTTP_202_ACCEPTED)
    def save_latest_to_display_sd_card() -> dict[str, object]:
        assignment = latest_image_store.get_assignment()
        if assignment is None:
            raise HTTPException(status_code=409, detail="Generate an image before saving it to the display SD card")
        profile = active_display_store.get()
        width = profile.width if profile else settings.output_width
        height = profile.height if profile else settings.output_height
        jpeg, _ = rendered_jpeg(
            assignment.image,
            width=width,
            height=height,
            rotation=display_settings_store.get_rotation(),
            aspect_mode=assignment.aspect_mode,
        )
        return queue_image_save(jpeg)

    @app.post("/display-commands/save-saved-image/{image_id}", status_code=status.HTTP_202_ACCEPTED)
    def save_creation_library_image_to_display_sd_card(image_id: str) -> dict[str, object]:
        image_path = image_library.find_path(image_id)
        if image_path is None:
            raise HTTPException(status_code=404, detail="Saved image not found")
        return queue_image_save(image_path.read_bytes(), image_id)

    @app.post("/display-commands/save-saved-video/{video_id}", status_code=status.HTTP_202_ACCEPTED)
    def save_saved_video_to_display_sd_card(video_id: str) -> dict[str, object]:
        """Queue one saved video for conversion and storage on the display SD card."""
        profile = active_display_store.get()
        if profile is None:
            raise HTTPException(status_code=409, detail="Connect a display before saving a video to its SD card")
        return queue_saved_video_to_display_sd_card(video_id, profile.width, profile.height)

    def queue_saved_video_to_display_sd_card(
        video_id: str,
        width: int,
        height: int,
        *,
        display_id: str = LEGACY_DISPLAY_ID,
    ) -> dict[str, object]:
        if video_library.find_path(video_id) is None:
            raise HTTPException(status_code=404, detail="Saved video not found")
        record = next((item for item in video_library.list(limit=10_000) if item.get("id") == video_id), {})
        metadata = record.get("metadata", {}) if isinstance(record, dict) else {}
        fps = metadata.get("fps", 15) if isinstance(metadata, dict) else 15
        try:
            fps = max(1, min(24, int(fps)))
        except (TypeError, ValueError):
            fps = 15
        content_key = f"v1-{video_id}-{width}x{height}-fps{fps}"
        existing_filename = display_command_store.find_sd_card_content(
            content_key, "video", display_id=display_id,
        )
        if existing_filename is not None:
            return {
                "status": "already_saved",
                "filename": existing_filename,
                "content_key": content_key,
                "detail": "This video is already on the display SD card for its current size and frame rate",
            }
        if bundled_ffmpeg_executable() is None:
            raise HTTPException(
                status_code=503,
                detail="Video conversion is unavailable on this computer (FFmpeg is missing). Repair the app installation and restart it before saving videos to the display.",
            )
        # The ESP32's SD filesystem does not expose a portable creation time.
        # Keep the stable content key for deduplication, but prefix it with the
        # UTC save time so the board can report a real Created value later.
        saved_at = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        filename = f"esp-video-{saved_at}-{content_key}.mjpeg"
        thumbnail_path = video_library.find_thumbnail_path(video_id)
        if thumbnail_path is not None:
            write_sd_thumbnail(filename, thumbnail_path.read_bytes(), display_id=display_id)
        return display_command_store.queue(
            "save_saved_video", display_id=display_id, filename=filename, video_id=video_id,
            video_url=f"/saved-videos/{video_id}/mjpeg-download", fps=fps,
            content_key=content_key, thumbnail_url=f"/saved-videos/{video_id}/thumbnail",
        )

    def queue_image_save(
        jpeg: bytes, image_id: str | None = None, *, display_id: str = LEGACY_DISPLAY_ID,
    ) -> dict[str, object]:
        image_hash = hashlib.sha256(jpeg).hexdigest()[:16]
        content_key = f"v1-{image_hash}"
        existing_filename = display_command_store.find_sd_card_image(image_hash, display_id=display_id)
        if existing_filename is not None:
            return {
                "status": "already_saved",
                "filename": existing_filename,
                "content_key": content_key,
                "detail": "This image is already on the display SD card",
            }
        # See the equivalent video name above.  The ESP32 extracts this UTC
        # timestamp when it reports the SD-card inventory.
        saved_at = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        filename = f"esp-image-{saved_at}-{content_key}.jpg"
        command = display_command_store.queue_save(
            filename,
            image_id,
            content_key=content_key,
            display_id=display_id,
            thumbnail_url=sd_thumbnail_url(display_id, filename),
        )
        write_sd_thumbnail(filename, jpeg, display_id=display_id)
        return command

    def sd_thumbnail_path_for(display_id: str, filename: str) -> Path:
        folder = sd_thumbnail_path if display_id == LEGACY_DISPLAY_ID else sd_thumbnail_path / display_id
        return folder / Path(filename).name

    def sd_thumbnail_url(display_id: str, filename: str) -> str:
        if display_id == LEGACY_DISPLAY_ID:
            return f"/display-sd-card/thumbnails/{Path(filename).name}"
        return f"/displays/{display_id}/display-sd-card/thumbnails/{Path(filename).name}"

    def saved_image_sd_card_content_keys(image_path: Path) -> list[str]:
        """Return identities for both a gallery original and its first display rendition.

        Saving a Creation Gallery item directly writes the original JPEG to the
        SD card. Saving the latest generated image writes a display-sized JPEG
        instead. The latter has a different hash even though it represents the
        same creation, so retain both identities for the gallery's SD-card
        status check.
        """
        try:
            original_jpeg = image_path.read_bytes()
        except OSError:
            return []
        content_keys = [f"v1-{hashlib.sha256(original_jpeg).hexdigest()[:16]}"]
        metadata = extract_jpeg_metadata(original_jpeg)
        display = metadata.get("display") if isinstance(metadata, dict) else None
        if not isinstance(display, dict):
            return content_keys
        width, height = display.get("width"), display.get("height")
        rotation = metadata.get("rotation")
        aspect_mode = metadata.get("broadcast_aspect_mode", "crop")
        if (
            not isinstance(width, int)
            or not isinstance(height, int)
            or not isinstance(rotation, int)
            or rotation not in VALID_ROTATIONS
            or aspect_mode not in {"crop", "fit"}
        ):
            return content_keys
        try:
            with Image.open(BytesIO(original_jpeg)) as source:
                display_jpeg = to_display_jpeg(
                    source,
                    width=width,
                    height=height,
                    rotation=rotation,
                    quality=jpeg_quality,
                    aspect_mode=aspect_mode,
                )
        except (OSError, ValueError):
            return content_keys
        content_keys.append(
            f"v1-{hashlib.sha256(embed_jpeg_metadata(display_jpeg, metadata)).hexdigest()[:16]}"
        )
        return content_keys

    def write_sd_thumbnail(
        filename: str, jpeg: bytes, *, display_id: str = LEGACY_DISPLAY_ID,
    ) -> None:
        """Keep the server copy paired with the thumbnail written to the SD card."""
        thumbnail_path = sd_thumbnail_path_for(display_id, filename)
        thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(BytesIO(jpeg)) as source:
            thumbnail_path.write_bytes(to_jpeg(source, width=160, height=120, quality=70))

    def restore_sd_video_thumbnail(filename: str, *, display_id: str = LEGACY_DISPLAY_ID) -> None:
        """Rebuild the server thumbnail cache for an MJPEG file already on the card."""
        if not filename.endswith(".mjpeg") or "-fps" not in filename:
            return
        if "-v1-" in filename:
            video_prefix = filename.split("-v1-", 1)[1].split("-", 1)[0]
        else:
            video_prefix = filename.rsplit("-fps", 1)[0].rsplit("-", 1)[-1]
        record = next(
            (item for item in video_library.list(limit=10_000) if str(item.get("id", "")).startswith(video_prefix)),
            None,
        )
        if record is None:
            return
        thumbnail_path = video_library.find_thumbnail_path(str(record["id"]))
        if thumbnail_path is not None:
            write_sd_thumbnail(filename, thumbnail_path.read_bytes(), display_id=display_id)

    def get_display_sd_card_report(display_id: str = LEGACY_DISPLAY_ID) -> dict[str, object]:
        report = display_command_store.sd_card_report(display_id)
        files = report.get("files", [])
        if isinstance(files, list):
            for file in files:
                if isinstance(file, dict):
                    filename = Path(str(file.get("name", ""))).name
                    if filename.endswith(".mjpeg") and not sd_thumbnail_path_for(display_id, filename).is_file():
                        restore_sd_video_thumbnail(filename, display_id=display_id)
            report["files"] = [
                {
                    **file,
                    "thumbnail_available": sd_thumbnail_path_for(
                        display_id, str(file.get("name", "")),
                    ).is_file(),
                }
                for file in files if isinstance(file, dict)
            ]
        return report

    def get_display_experience_response(display_id: str = LEGACY_DISPLAY_ID) -> dict[str, object]:
        report = display_command_store.sd_card_report(display_id)
        return {
            "connected": bool(report.get("available", False)),
            "current_mode": report.get("mode", "server_controlled"),
            "offline_experience": report.get("offline_experience", "slideshow"),
            "offline_experience_saved": report.get("offline_experience_saved"),
            "slideshow_interval_ms": report.get("slideshow_interval_ms", 15_000),
            "slideshow_order": report.get("slideshow_order", "newest_first"),
        }

    @app.get("/display-sd-card")
    def get_display_sd_card() -> dict[str, object]:
        return get_display_sd_card_report()

    @app.get("/display-sd-card/thumbnails/{filename}", response_class=Response)
    def get_display_sd_card_thumbnail(filename: str) -> Response:
        thumbnail_path = sd_thumbnail_path_for(LEGACY_DISPLAY_ID, filename)
        if not thumbnail_path.is_file():
            raise HTTPException(status_code=404, detail="SD card thumbnail not available")
        return FileResponse(thumbnail_path, media_type="image/jpeg")

    @app.post("/display-sd-card/report", status_code=status.HTTP_204_NO_CONTENT)
    def report_display_sd_card(report: DisplaySDCardReport) -> Response:
        display_command_store.report_sd_card(report.model_dump())
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/display-experience")
    def get_display_experience() -> dict[str, object]:
        return get_display_experience_response()

    @app.put("/display-experience", status_code=status.HTTP_202_ACCEPTED)
    def set_display_experience(request: DisplayExperienceRequest) -> dict[str, object]:
        return display_command_store.queue(
            "set_display_experience",
            offline_experience=request.offline_experience,
            slideshow_interval_ms=request.slideshow_interval_ms,
            slideshow_order=request.slideshow_order,
        )

    @app.post("/display-experience/preview", status_code=status.HTTP_202_ACCEPTED)
    def preview_display_experience(request: DisplayExperienceRequest) -> dict[str, object]:
        return display_command_store.queue(
            "preview_display_experience",
            offline_experience=request.offline_experience,
            slideshow_interval_ms=request.slideshow_interval_ms,
            slideshow_order=request.slideshow_order,
        )

    @app.delete("/display-experience/preview", status_code=status.HTTP_202_ACCEPTED)
    def stop_display_experience_preview() -> dict[str, object]:
        return display_command_store.queue("stop_display_experience_preview")

    @app.post("/display-sd-card/mode/{mode}", status_code=status.HTTP_202_ACCEPTED)
    def set_display_mode(mode: str) -> dict[str, object]:
        if mode not in {"live_images", "sd_card"}:
            raise HTTPException(status_code=422, detail="Mode must be live_images or sd_card")
        return display_command_store.queue("set_mode", mode=mode)

    @app.post("/display-sd-card/refresh", status_code=status.HTTP_202_ACCEPTED)
    def refresh_display_sd_card() -> dict[str, object]:
        return display_command_store.queue("refresh_sd_card")

    @app.post("/display-sd-card/files/{filename}/display", status_code=status.HTTP_202_ACCEPTED)
    def display_sd_card_file(filename: str) -> dict[str, object]:
        return display_command_store.queue("display_sd_file", filename=filename)

    @app.delete("/display-sd-card/files/{filename}", status_code=status.HTTP_202_ACCEPTED)
    def delete_sd_card_file(filename: str) -> dict[str, object]:
        return display_command_store.queue("delete_sd_file", filename=filename)

    @app.get("/display-commands/next")
    def next_display_command() -> Response:
        command = display_command_store.next()
        return JSONResponse(command) if command is not None else Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/display-commands/{command_id}/ack")
    def acknowledge_display_command(command_id: str, acknowledgement: DisplayCommandAcknowledgement) -> dict[str, object]:
        command = display_command_store.acknowledge(command_id, acknowledgement.success, acknowledgement.detail)
        if command is None:
            raise HTTPException(status_code=404, detail="Display command not found")
        return command

    @app.get("/display-commands/{command_id}")
    def get_display_command(command_id: str) -> dict[str, object]:
        command = display_command_store.get(command_id)
        if command is None:
            raise HTTPException(status_code=404, detail="Display command not found")
        return command

    @app.post("/displays/{display_id}/display-commands/save-latest", status_code=status.HTTP_202_ACCEPTED)
    def save_latest_to_registered_display_sd_card(display_id: str) -> dict[str, object]:
        display = get_registered_display(display_id)
        assignment = latest_image_store.get_assignment(display_id)
        if assignment is None:
            raise HTTPException(status_code=409, detail="Generate an image before saving it to the display SD card")
        jpeg, _ = rendered_jpeg(
            assignment.image,
            width=display.width,
            height=display.height,
            rotation=display.rotation,
            aspect_mode=assignment.aspect_mode,
        )
        return queue_image_save(jpeg, display_id=display_id)

    @app.post(
        "/displays/{display_id}/display-commands/save-saved-image/{image_id}",
        status_code=status.HTTP_202_ACCEPTED,
    )
    def save_creation_library_image_to_registered_display_sd_card(
        display_id: str, image_id: str,
    ) -> dict[str, object]:
        get_registered_display(display_id)
        image_path = image_library.find_path(image_id)
        if image_path is None:
            raise HTTPException(status_code=404, detail="Saved image not found")
        return queue_image_save(image_path.read_bytes(), image_id, display_id=display_id)

    @app.post(
        "/displays/{display_id}/display-commands/save-saved-video/{video_id}",
        status_code=status.HTTP_202_ACCEPTED,
    )
    def save_saved_video_to_registered_display_sd_card(
        display_id: str, video_id: str,
    ) -> dict[str, object]:
        display = get_registered_display(display_id)
        return queue_saved_video_to_display_sd_card(
            video_id, display.width, display.height, display_id=display_id,
        )

    @app.get("/displays/{display_id}/display-sd-card")
    def get_registered_display_sd_card(display_id: str) -> dict[str, object]:
        get_registered_display(display_id)
        return get_display_sd_card_report(display_id)

    @app.get("/displays/{display_id}/display-sd-card/thumbnails/{filename}", response_class=Response)
    def get_registered_display_sd_card_thumbnail(display_id: str, filename: str) -> Response:
        get_registered_display(display_id)
        thumbnail_path = sd_thumbnail_path_for(display_id, filename)
        if not thumbnail_path.is_file():
            raise HTTPException(status_code=404, detail="SD card thumbnail not available")
        return FileResponse(thumbnail_path, media_type="image/jpeg")

    @app.post("/displays/{display_id}/display-sd-card/report", status_code=status.HTTP_204_NO_CONTENT)
    def report_registered_display_sd_card(
        display_id: str,
        report: DisplaySDCardReport,
    ) -> Response:
        get_registered_display(display_id)
        display_registry.record_activity(display_id, "SD-card list received")
        display_command_store.report_sd_card(report.model_dump(), display_id=display_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/displays/{display_id}/display-experience")
    def get_registered_display_experience(display_id: str) -> dict[str, object]:
        get_registered_display(display_id)
        return get_display_experience_response(display_id)

    @app.put("/displays/{display_id}/display-experience", status_code=status.HTTP_202_ACCEPTED)
    def set_registered_display_experience(
        display_id: str, request: DisplayExperienceRequest,
    ) -> dict[str, object]:
        get_registered_display(display_id)
        return display_command_store.queue(
            "set_display_experience",
            display_id=display_id,
            offline_experience=request.offline_experience,
            slideshow_interval_ms=request.slideshow_interval_ms,
            slideshow_order=request.slideshow_order,
        )

    @app.post("/displays/{display_id}/display-experience/preview", status_code=status.HTTP_202_ACCEPTED)
    def preview_registered_display_experience(
        display_id: str, request: DisplayExperienceRequest,
    ) -> dict[str, object]:
        get_registered_display(display_id)
        return display_command_store.queue(
            "preview_display_experience",
            display_id=display_id,
            offline_experience=request.offline_experience,
            slideshow_interval_ms=request.slideshow_interval_ms,
            slideshow_order=request.slideshow_order,
        )

    @app.delete("/displays/{display_id}/display-experience/preview", status_code=status.HTTP_202_ACCEPTED)
    def stop_registered_display_experience_preview(display_id: str) -> dict[str, object]:
        get_registered_display(display_id)
        return display_command_store.queue("stop_display_experience_preview", display_id=display_id)

    @app.post("/displays/{display_id}/display-sd-card/mode/{mode}", status_code=status.HTTP_202_ACCEPTED)
    def set_registered_display_mode(display_id: str, mode: str) -> dict[str, object]:
        get_registered_display(display_id)
        if mode not in {"live_images", "sd_card"}:
            raise HTTPException(status_code=422, detail="Mode must be live_images or sd_card")
        return display_command_store.queue("set_mode", display_id=display_id, mode=mode)

    @app.post("/displays/{display_id}/display-sd-card/refresh", status_code=status.HTTP_202_ACCEPTED)
    def refresh_registered_display_sd_card(display_id: str) -> dict[str, object]:
        get_registered_display(display_id)
        return display_command_store.queue("refresh_sd_card", display_id=display_id)

    @app.post(
        "/displays/{display_id}/display-sd-card/files/{filename}/display",
        status_code=status.HTTP_202_ACCEPTED,
    )
    def display_registered_sd_card_file(display_id: str, filename: str) -> dict[str, object]:
        get_registered_display(display_id)
        return display_command_store.queue("display_sd_file", display_id=display_id, filename=filename)

    @app.delete("/displays/{display_id}/display-sd-card/files/{filename}", status_code=status.HTTP_202_ACCEPTED)
    def delete_registered_sd_card_file(display_id: str, filename: str) -> dict[str, object]:
        get_registered_display(display_id)
        return display_command_store.queue("delete_sd_file", display_id=display_id, filename=filename)

    @app.get("/displays/{display_id}/display-commands/next")
    def next_registered_display_command(display_id: str) -> Response:
        get_registered_display(display_id)
        command = display_command_store.next(display_id)
        if command is not None:
            display_registry.record_activity(display_id, display_command_activity(command, "received"))
        return JSONResponse(command) if command is not None else Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/displays/{display_id}/display-commands/{command_id}/ack")
    def acknowledge_registered_display_command(
        display_id: str,
        command_id: str,
        acknowledgement: DisplayCommandAcknowledgement,
    ) -> dict[str, object]:
        get_registered_display(display_id)
        command = display_command_store.acknowledge(
            command_id,
            acknowledgement.success,
            acknowledgement.detail,
            display_id=display_id,
        )
        if command is None:
            raise HTTPException(status_code=404, detail="Display command not found")
        outcome = "completed" if command["status"] == "complete" else str(command["status"])
        display_registry.record_activity(display_id, display_command_activity(command, outcome))
        return command

    @app.post("/displays/{display_id}/display-commands/{command_id}/progress")
    def report_registered_command_progress(display_id: str, command_id: str, progress: DisplayCommandProgress) -> dict[str, object]:
        get_registered_display(display_id)
        if progress.received_bytes > progress.total_bytes:
            raise HTTPException(status_code=422, detail="Received bytes exceed transfer size")
        command = display_command_store.progress(command_id, progress.stage, progress.received_bytes, progress.total_bytes, display_id=display_id)
        if command is None:
            raise HTTPException(status_code=404, detail="Display command not found")
        if command["status"] == "pending" and command.get("progress"):
            display_registry.record_activity(display_id, "SD-card transfer " + progress.stage)
        return command

    @app.post("/displays/{display_id}/display-commands/{command_id}/cancel")
    def cancel_registered_command(display_id: str, command_id: str) -> dict[str, object]:
        get_registered_display(display_id)
        command = display_command_store.cancel(command_id, display_id=display_id)
        if command is None:
            raise HTTPException(status_code=404, detail="Display command not found")
        return command

    @app.get("/displays/{display_id}/display-commands/{command_id}")
    def get_registered_display_command(display_id: str, command_id: str) -> dict[str, object]:
        get_registered_display(display_id)
        command = display_command_store.get(command_id, display_id=display_id)
        if command is None:
            raise HTTPException(status_code=404, detail="Display command not found")
        return command
        model_name, model_description = model_details.get(
            settings.model_id, (settings.model_id, "Local AI image model selected during installation.")
        )
        if generator.device == "cuda":
            processing = "NVIDIA graphics card acceleration — fast image generation."
        elif generator.device == "cpu":
            processing = "Computer processor mode — works broadly, but image generation can take longer."
        else:
            processing = f"Processing device: {generator.device}"
        return {
            "model_name": model_name,
            "model_id": settings.model_id,
            "model_description": model_description,
            "processing": processing,
            "default_width": settings.output_width,
            "default_height": settings.output_height,
        }

    @app.get("/app-settings")
    def get_app_settings() -> dict[str, object]:
        return {
            "image_library_location": str(image_library.path),
            "jpeg_quality": jpeg_quality,
            "video_jpeg_quality": video_jpeg_quality,
            "auto_save_images": auto_save_images,
            "auto_save_videos": auto_save_videos,
            "confirm_deletion": confirm_deletion,
        }

    @app.put("/app-settings")
    def update_app_settings(request: AppSettingsRequest) -> dict[str, object]:
        nonlocal jpeg_quality, video_jpeg_quality, auto_save_images, auto_save_videos, confirm_deletion
        if request.image_library_location is not None:
            location = Path(request.image_library_location)
            if not location.is_absolute():
                raise HTTPException(status_code=422, detail="Choose an absolute folder path for the image library")
            try:
                image_library.relocate(location)
                video_library.path = image_library.path / "videos"
            except (OSError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=f"Could not move the image library: {exc}") from exc
        if request.jpeg_quality is not None:
            jpeg_quality = request.jpeg_quality
        if request.video_jpeg_quality is not None:
            video_jpeg_quality = request.video_jpeg_quality
        if request.auto_save_images is not None:
            auto_save_images = request.auto_save_images
        if request.auto_save_videos is not None:
            auto_save_videos = request.auto_save_videos
        if request.confirm_deletion is not None:
            confirm_deletion = request.confirm_deletion
        app_settings_store.set({
            "image_library_location": str(image_library.path),
            "jpeg_quality": jpeg_quality,
            "video_jpeg_quality": video_jpeg_quality,
            "auto_save_images": auto_save_images,
            "auto_save_videos": auto_save_videos,
            "confirm_deletion": confirm_deletion,
        })
        return get_app_settings()

    @app.post("/app-settings/image-library/reveal")
    def reveal_image_library() -> dict[str, str]:
        image_library.path.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(image_library.path)  # type: ignore[attr-defined]  # Windows Explorer
        except (AttributeError, OSError) as exc:
            raise HTTPException(status_code=500, detail=f"Could not open the image library folder: {exc}") from exc
        return {"status": "opened", "image_library_location": str(image_library.path)}

    @app.post("/app-settings/image-library/choose")
    def choose_image_library() -> dict[str, object]:
        command = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$dialog.Description = 'Choose an empty folder for ESPImageServer images'; "
            "$dialog.SelectedPath = '" + str(image_library.path).replace("'", "''") + "'; "
            "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { "
            "[Console]::Out.Write($dialog.SelectedPath) }"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-STA", "-Command", command],
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise HTTPException(status_code=500, detail=f"Could not open the folder chooser: {exc}") from exc
        selected_path = result.stdout.strip()
        return {"selected": bool(selected_path), "image_library_location": selected_path or str(image_library.path)}

    @app.get("/devices")
    def list_devices() -> list[dict[str, object]]:
        return device_manager.list_devices()

    @app.get("/latest.jpg", response_class=Response)
    def latest_image(
        if_none_match: str | None = Header(default=None),
        width: int | None = Query(default=None, ge=1, le=1024),
        height: int | None = Query(default=None, ge=1, le=1024),
    ) -> Response:
        assignment = latest_image_store.get_assignment()
        if (width is None) != (height is None):
            raise HTTPException(status_code=422, detail="Width and height must be provided together")
        profile = active_display_store.get()
        return latest_image_response(
            assignment,
            width=width if width is not None else (profile.width if profile else settings.output_width),
            height=height if height is not None else (profile.height if profile else settings.output_height),
            rotation=display_settings_store.get_rotation(),
            if_none_match=if_none_match,
        )

    @app.get("/displays/{display_id}/latest.jpg", response_class=Response)
    def registered_display_latest_image(
        display_id: str,
        if_none_match: str | None = Header(default=None),
        width: int | None = Query(default=None, ge=1, le=1024),
        height: int | None = Query(default=None, ge=1, le=1024),
    ) -> Response:
        """Deliver cached source artwork at this display's native configuration."""
        display = get_registered_display(display_id)
        if (width is None) != (height is None):
            raise HTTPException(status_code=422, detail="Width and height must be provided together")
        if width is not None and (width != display.width or height != display.height):
            raise HTTPException(status_code=422, detail="Use the registered display's native dimensions")
        response = latest_image_response(
            latest_image_store.get_assignment(display_id),
            width=display.width,
            height=display.height,
            rotation=display.rotation,
            if_none_match=if_none_match,
        )
        if response.status_code == status.HTTP_200_OK:
            display_registry.record_activity(display_id, "Latest image sent")
        return response

    @app.get("/saved-images")
    def saved_images() -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        for record in image_library.list():
            image_path = image_library.find_path(str(record.get("id", "")))
            if image_path is None:
                continue
            content_keys = saved_image_sd_card_content_keys(image_path)
            records.append({
                **record,
                # Keep the original field for clients that save a gallery
                # file directly to the card, while newer clients can also
                # recognize its display-sized counterpart.
                "sd_card_content_key": content_keys[0] if content_keys else "",
                "sd_card_content_keys": content_keys,
            })
        return records

    @app.get("/saved-videos")
    def saved_videos() -> list[dict[str, object]]:
        return video_library.list()

    @app.get("/saved-videos/{video_id}/video")
    def saved_video(video_id: str) -> FileResponse:
        video_path = video_library.find_path(video_id)
        if video_path is None:
            raise HTTPException(status_code=404, detail="Saved video not found")
        return FileResponse(video_path, media_type="video/mp4", filename=video_path.name)

    @app.get("/saved-videos/{video_id}/mjpeg-download")
    def saved_video_mjpeg_download(video_id: str, width: int = Query(ge=1, le=1024), height: int = Query(ge=1, le=1024), fps: int = Query(default=8, ge=1, le=24)) -> FileResponse:
        """Create a display-sized MJPEG file for download to an ESP32 SD card."""
        video_path = video_library.find_path(video_id)
        if video_path is None:
            raise HTTPException(status_code=404, detail="Saved video not found")
        ffmpeg = bundled_ffmpeg_executable()
        if ffmpeg is None:
            raise HTTPException(status_code=503, detail="Bundled FFmpeg is unavailable")
        output_path = mjpeg_cache.output_path(video_id, width, height, fps, video_jpeg_quality)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if not output_path.is_file() or output_path.stat().st_mtime < video_path.stat().st_mtime:
                subprocess.run(
                    [ffmpeg, "-y", "-loglevel", "error", "-i", str(video_path), "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}",
                     "-r", str(fps), "-an", "-c:v", "mjpeg", "-pix_fmt", "yuvj420p", "-color_range", "pc",
                     "-q:v", str(video_jpeg_quality), "-f", "mjpeg", str(output_path)],
                    capture_output=True, check=True, timeout=300,
                )
        except (OSError, subprocess.SubprocessError) as exc:
            raise HTTPException(status_code=500, detail=f"Could not prepare video for the display: {exc}") from exc
        mjpeg_cache.acquire(output_path)

        def release_conversion() -> None:
            mjpeg_cache.release(output_path)
            cleanup_temporary_data()

        return FileResponse(
            output_path,
            media_type="video/x-motion-jpeg",
            filename=output_path.name,
            background=BackgroundTask(release_conversion),
        )

    @app.get("/saved-videos/{video_id}/thumbnail", response_class=Response)
    def saved_video_thumbnail(video_id: str) -> FileResponse:
        thumbnail_path = video_library.find_thumbnail_path(video_id)
        if thumbnail_path is None:
            raise HTTPException(status_code=404, detail="Saved video thumbnail not found")
        return FileResponse(thumbnail_path, media_type="image/jpeg")

    @app.delete("/saved-videos/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_saved_video(video_id: str) -> Response:
        try:
            deleted = video_library.delete(video_id)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="Saved video not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/creation-library/images", status_code=status.HTTP_201_CREATED)
    async def save_image_to_creation_library(request: Request) -> dict[str, object]:
        if request.headers.get("content-type", "").split(";", 1)[0].lower() != "image/jpeg":
            raise HTTPException(status_code=415, detail="Expected a JPEG image")
        jpeg = await request.body()
        metadata = extract_jpeg_metadata(jpeg)
        if metadata is None:
            raise HTTPException(status_code=422, detail="The image does not contain ESPImageServer generation details")
        return image_library.save(jpeg, metadata)

    @app.get("/saved-images/{image_id}/image", response_class=Response)
    def saved_image(
        image_id: str,
        width: int | None = Query(default=None, ge=1, le=1024),
        height: int | None = Query(default=None, ge=1, le=1024),
    ) -> Response:
        image_path = image_library.find_path(image_id)
        if image_path is None:
            raise HTTPException(status_code=404, detail="Saved image not found")
        if (width is None) != (height is None):
            raise HTTPException(status_code=422, detail="Width and height must be provided together")
        if width is not None and height is not None:
            try:
                with Image.open(image_path) as source:
                    jpeg = to_jpeg(source, width=width, height=height, quality=jpeg_quality)
            except (OSError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=f"Could not prepare saved image for the display: {exc}") from exc
            return Response(content=jpeg, media_type="image/jpeg")
        return FileResponse(image_path, media_type="image/jpeg", filename=image_path.name)

    @app.get("/displays/{display_id}/saved-images/{image_id}/image", response_class=Response)
    def saved_image_for_registered_display(display_id: str, image_id: str) -> Response:
        """Fit a Creation Gallery source for one display's size and rotation."""
        display = get_registered_display(display_id)
        image_path = image_library.find_path(image_id)
        if image_path is None:
            raise HTTPException(status_code=404, detail="Saved image not found")
        try:
            with Image.open(image_path) as source:
                jpeg = to_display_jpeg(
                    source,
                    width=display.width,
                    height=display.height,
                    rotation=display.rotation,
                    quality=jpeg_quality,
                )
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"Could not prepare saved image for the display: {exc}") from exc
        return Response(content=jpeg, media_type="image/jpeg")

    @app.post("/saved-images/{image_id}/display", status_code=status.HTTP_202_ACCEPTED)
    def show_saved_image_on_display(
        image_id: str, targets: DisplayTargetsRequest | None = None,
    ) -> dict[str, object]:
        """Broadcast or send a saved creation to selected ESP32 displays."""
        image_path = image_library.find_path(image_id)
        if image_path is None:
            raise HTTPException(status_code=404, detail="Saved image not found")
        try:
            target_displays = requested_target_displays(targets.display_ids if targets is not None else None)
            aspect_mode = resolve_broadcast_aspect_mode(
                target_displays,
                targets.broadcast_aspect_mode if targets is not None else None,
                allow_separate=False,
            )
            latest_image_store.set(
                image_path.read_bytes(),
                [display.id for display in target_displays] if targets is not None else None,
                aspect_mode=aspect_mode,
            )
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"Could not prepare saved image for the display: {exc}") from exc
        return {
            "message": "Saved image is ready for the selected displays" if targets is not None else "Saved image is ready for the display",
            "display_ids": [display.id for display in target_displays],
        }

    @app.delete("/saved-images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_saved_image(image_id: str) -> Response:
        try:
            deleted = image_library.delete(image_id)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="Saved image not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/saved-images/{image_id}/thumbnail", response_class=Response)
    def saved_image_thumbnail(image_id: str) -> Response:
        image_path = image_library.find_path(image_id)
        if image_path is None:
            raise HTTPException(status_code=404, detail="Saved image not found")
        with Image.open(image_path) as image:
            image = image.convert("RGB")
            image.thumbnail((160, 120), Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, format="JPEG", quality=80, optimize=True)
        return Response(content=output.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})

    @app.post("/pairing-codes", status_code=status.HTTP_201_CREATED)
    def create_pairing_code() -> dict[str, object]:
        code, expires_in_seconds = device_manager.create_pairing_code()
        return {"code": code, "expires_in_seconds": expires_in_seconds}

    @app.post("/devices/register", status_code=status.HTTP_201_CREATED)
    def register_device(request: RegisterDeviceRequest) -> dict[str, object]:
        try:
            device = device_manager.register_device(request.pairing_code, request.name)
        except DeviceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": device.device_id, "name": device.name, "token": device.token}

    @app.post("/devices/{device_id}/heartbeat")
    def heartbeat(device_id: str, x_espimage_token: str = Header(default="")) -> dict[str, object]:
        try:
            device_manager.heartbeat(device_id, x_espimage_token)
        except DeviceError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return {"status": "ok"}

    @app.post("/devices/{device_id}/images", status_code=status.HTTP_201_CREATED)
    async def queue_image(device_id: str, request: Request) -> dict[str, object]:
        content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type != "image/jpeg":
            raise HTTPException(status_code=415, detail="Expected an image/jpeg request body")
        try:
            image, device = device_manager.queue_image(device_id, await request.body())
        except DeviceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"image_id": image.image_id, "device": device.name, "status": "queued"}

    @app.get("/devices/{device_id}/next-image", response_class=Response)
    def next_image(
        device_id: str,
        wait_seconds: int = Query(default=25, ge=0, le=25),
        x_espimage_token: str = Header(default=""),
    ) -> Response:
        try:
            image = device_manager.next_image(device_id, x_espimage_token, wait_seconds)
        except DeviceError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        if image is None:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        return Response(
            content=image.jpeg,
            media_type="image/jpeg",
            headers={"X-ESPImage-Image-ID": image.image_id},
        )

    @app.post("/devices/{device_id}/ack")
    def acknowledge_image(
        device_id: str,
        request: AcknowledgeImageRequest,
        x_espimage_token: str = Header(default=""),
    ) -> dict[str, object]:
        try:
            device_manager.acknowledge(device_id, x_espimage_token, request.image_id)
        except DeviceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "acknowledged"}

    def generate_jpeg(
        request: GenerateRequest,
        progress=None,
        is_cancelled=None,
        model_id: str | None = None,
        selected_settings: Settings | None = None,
        generation_metadata: dict[str, object] | None = None,
        target_displays: list[DisplayDevice] | None = None,
        target_display_ids: list[str] | None = None,
        broadcast_aspect_mode: str = "crop",
    ) -> bytes:
        generation_started_at = perf_counter()

        def ensure_not_cancelled() -> None:
            if is_cancelled is not None and is_cancelled():
                raise GenerationCancelled()

        ensure_not_cancelled()
        job_model_id = model_id or active_model_id
        job_settings = selected_settings or active_settings
        generator.activate_model(job_settings)
        model = get_model(job_model_id)
        if request.negative_prompt and not model.supports_negative_prompt:
            raise ValueError(f"{model.name} does not support negative prompts")
        steps = request.steps if request.steps is not None else model.inference_steps
        if not model.minimum_steps <= steps <= model.maximum_steps:
            raise ValueError(f"{model.name} supports {model.minimum_steps} to {model.maximum_steps} steps")
        targets = target_displays or []
        target_groups = (
            target_aspect_groups(targets)
            if broadcast_aspect_mode == "separate" and targets
            else [targets]
        )
        source_aspect_mode = "crop" if broadcast_aspect_mode == "separate" else broadcast_aspect_mode
        first_preview: bytes | None = None
        first_profile: DisplayDevice | None = None
        first_rotation = display_settings_store.get_rotation()

        for group_index, group in enumerate(target_groups, start=1):
            ensure_not_cancelled()
            profile = group[0] if group else active_display_store.get()
            output_width = profile.width if profile else settings.output_width
            output_height = profile.height if profile else settings.output_height
            rotation = profile.rotation if isinstance(profile, DisplayDevice) else display_settings_store.get_rotation()
            artwork_width, artwork_height = (
                (output_height, output_width) if rotation in {90, 270} else (output_width, output_height)
            )
            generation_width, generation_height = optimal_generation_size(
                job_model_id, artwork_width, artwork_height,
            )
            group_label = (
                f" {group_index} of {len(target_groups)}"
                if len(target_groups) > 1 else ""
            )
            if progress is not None:
                progress(0, 0, f"Preparing the image model{group_label}")
            image = generator.generate(
                request.prompt,
                generation_width,
                generation_height,
                progress=(
                    lambda step, total, label=group_label: progress(
                        step, total, f"Generating image{label}",
                    )
                ) if progress else None,
                inference_steps=steps,
                seed=request.seed,
                cancelled=is_cancelled,
                negative_prompt=request.negative_prompt,
            )
            ensure_not_cancelled()
            if image.convert("RGB").getbbox() is None:
                raise RuntimeError("The model returned a blank image. Please try generating again.")
            if progress is not None:
                progress(1, 1, f"Saving source artwork and preparing display JPEGs{group_label}")

            group_target_ids = [display.id for display in group] if target_display_ids is not None else None
            metadata = {
                "version": 1,
                "createdAt": datetime.now(UTC).isoformat(),
                "model": {"id": job_model_id, "name": model.name},
                "prompt": request.prompt,
                "negative_prompt": request.negative_prompt,
                "steps": steps,
                "seed": request.seed,
                "rotation": rotation,
                "display_ids": group_target_ids,
                "broadcast_aspect_mode": broadcast_aspect_mode,
                "generation_time_seconds": round(perf_counter() - generation_started_at, 2),
                "display": (
                    {"name": profile.name, "width": profile.width, "height": profile.height}
                    if profile is not None else None
                ),
            }
            master_jpeg = embed_jpeg_metadata(
                to_jpeg(image, width=image.width, height=image.height, quality=95), metadata,
            )
            ensure_not_cancelled()
            latest_image = latest_image_store.set(
                master_jpeg,
                group_target_ids,
                aspect_mode=source_aspect_mode,
            )
            if auto_save_images:
                if progress is not None:
                    progress(1, 1, f"Saving image to your Creation Gallery{group_label}")
                image_library.save(master_jpeg, metadata)
            if first_preview is None:
                first_preview, _ = rendered_jpeg(
                    latest_image,
                    width=output_width,
                    height=output_height,
                    rotation=rotation,
                    aspect_mode=source_aspect_mode,
                )
                first_profile = profile if isinstance(profile, DisplayDevice) else None
                first_rotation = rotation

        if generation_metadata is not None:
            generation_metadata.update({
                "version": 1,
                "createdAt": datetime.now(UTC).isoformat(),
                "model": {"id": job_model_id, "name": model.name},
                "prompt": request.prompt,
                "negative_prompt": request.negative_prompt,
                "steps": steps,
                "seed": request.seed,
                "rotation": first_rotation,
                "display_ids": target_display_ids,
                "broadcast_aspect_mode": broadcast_aspect_mode,
                "separate_artwork_count": len(target_groups),
                "generation_time_seconds": round(perf_counter() - generation_started_at, 2),
                "display": (
                    {"name": first_profile.name, "width": first_profile.width, "height": first_profile.height}
                    if first_profile is not None else None
                ),
            })
        if first_preview is None:
            raise RuntimeError("The model did not produce an image")
        return first_preview

    @app.post("/generate", response_class=Response, responses={200: {"content": {"image/jpeg": {}}}})
    async def generate(request: GenerateRequest) -> Response:
        if generation_queue.has_active_job():
            raise HTTPException(status_code=409, detail="Wait for queued generation work to finish before using the direct image endpoint")
        target_displays = requested_target_displays(request.display_ids)
        broadcast_aspect_mode = resolve_broadcast_aspect_mode(
            target_displays, request.broadcast_aspect_mode, allow_separate=True,
        )
        target_display_ids = [display.id for display in target_displays] if request.display_ids is not None else None
        requested_model_id = request.model_id or active_model_id
        try:
            requested_settings = model_settings(settings, requested_model_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Image model not found") from exc
        try:
            await run_in_threadpool(video_generator.unload)
            jpeg = await run_in_threadpool(
                generate_jpeg,
                request,
                None,
                None,
                requested_model_id,
                requested_settings,
                None,
                target_displays,
                target_display_ids,
                broadcast_aspect_mode,
            )
        except RuntimeError as exc:
            logger.exception("Image generation failed")
            raise HTTPException(status_code=500, detail=str(exc)) from None
        except Exception:
            logger.exception("Image generation failed")
            raise HTTPException(status_code=500, detail="Image generation failed") from None
        return Response(content=jpeg, media_type="image/jpeg")

    @app.post("/generation-jobs", status_code=status.HTTP_202_ACCEPTED)
    def create_generation_job(request: GenerateRequest) -> dict[str, object]:
        nonlocal active_model_id, active_settings
        target_displays = requested_target_displays(request.display_ids)
        broadcast_aspect_mode = resolve_broadcast_aspect_mode(
            target_displays, request.broadcast_aspect_mode, allow_separate=True,
        )
        target_display_ids = [display.id for display in target_displays] if request.display_ids is not None else None
        job_model_id = request.model_id or active_model_id
        try:
            job_settings = model_settings(settings, job_model_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Image model not found") from exc
        active_model_id = job_model_id
        active_settings = job_settings
        model_selection_store.set(job_model_id)
        image_metadata: dict[str, object] = {
            "label": request.prompt[:80],
            "model_id": job_model_id,
            "display_id": target_display_ids[0] if target_display_ids else None,
            "display_ids": target_display_ids,
            "broadcast_aspect_mode": broadcast_aspect_mode,
        }
        job = generation_queue.create(
            "image",
            lambda progress, is_cancelled: (
                video_generator.unload(),
                generate_jpeg(
                    request,
                    progress,
                    is_cancelled,
                    job_model_id,
                    job_settings,
                    image_metadata,
                    target_displays,
                    target_display_ids,
                    broadcast_aspect_mode,
                ),
            )[1],
            image_metadata,
        )
        return job.as_dict()

    @app.get("/generation-queue")
    def list_generation_queue() -> list[dict[str, object]]:
        return generation_queue.list()

    @app.delete("/generation-queue")
    def clear_finished_generation_queue() -> dict[str, int]:
        return {"cleared": generation_queue.clear_finished()}

    @app.delete("/generation-queue/{job_id}")
    def cancel_queued_generation(job_id: str) -> dict[str, object]:
        job = generation_queue.cancel(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Generation job not found")
        return job.as_dict()

    @app.get("/generation-jobs/{job_id}")
    def generation_job(job_id: str) -> dict[str, object]:
        job = generation_queue.get(job_id, "image")
        if job is None:
            raise HTTPException(status_code=404, detail="Generation job not found")
        return job.as_dict()

    @app.delete("/generation-jobs/{job_id}")
    def cancel_generation_job(job_id: str) -> dict[str, object]:
        job = generation_queue.cancel(job_id, "image")
        if job is None:
            raise HTTPException(status_code=404, detail="Generation job not found")
        return job.as_dict()

    @app.get("/generation-jobs/{job_id}/image", response_class=Response)
    def generation_job_image(job_id: str) -> Response:
        job = generation_queue.get(job_id, "image")
        if job is None:
            raise HTTPException(status_code=404, detail="Generation job not found")
        if job.status != "complete" or job.jpeg is None:
            raise HTTPException(status_code=409, detail="Image is not ready")
        return Response(content=job.jpeg, media_type="image/jpeg")

    @app.get("/video-generation-info")
    def video_generation_info() -> dict[str, object]:
        return {
            "model_name": "Local video generation",
            "model_id": video_generator.model_id,
            "ready": video_generator.ready,
            "requires_cuda": True,
            "device": generator.device,
            "models": [{"id": model_id, **model} for model_id, model in VIDEO_MODELS.items()],
        }

    @app.get("/video-models")
    def list_video_models() -> list[dict[str, object]]:
        return [
            {
                "id": model_id,
                "name": model["name"],
                "model_card_url": f"https://huggingface.co/{model.get('repository', 'Lightricks/LTX-Video')}",
                "description": model["description"],
                "family": model["family"],
                "minimum_steps": model["minimum_steps"],
                "maximum_steps": model["maximum_steps"],
                "recommended_steps": model["recommended_steps"],
                "installed": video_model_is_cached(model_id),
                "supports_image": model["family"] != "wan",
                "removal_note": "Removes shared LTX-Video files used by both LTX choices." if model["family"] == "ltx" else "",
            }
            for model_id, model in VIDEO_MODELS.items()
        ]

    @app.delete("/video-models/{model_id}")
    def remove_video_model(model_id: str) -> dict[str, object]:
        if model_id not in VIDEO_MODELS:
            raise HTTPException(status_code=404, detail="Video model not found")
        if generation_queue.has_active_job():
            raise HTTPException(status_code=409, detail="Wait for queued generation work to finish before removing a video model")
        video_generator.unload()
        removed = remove_cached_video_model(model_id)
        return {"removed": removed}

    @app.post("/video-generation-jobs", status_code=status.HTTP_202_ACCEPTED)
    def create_video_generation_job(request: VideoGenerateRequest) -> dict[str, object]:
        if generator.device != "cuda":
            raise HTTPException(status_code=409, detail="Video generation requires a compatible NVIDIA GPU; this server is running image generation on CPU.")
        if (request.num_frames - 1) % 8:
            raise HTTPException(status_code=422, detail="Video frame count must be 1 plus a multiple of 8 (for example 17, 25, or 33).")
        video_model = VIDEO_MODELS.get(request.model_id)
        if video_model is None:
            raise HTTPException(status_code=422, detail="This video model is not available")
        if not video_model["minimum_steps"] <= request.steps <= video_model["maximum_steps"]:
            raise HTTPException(status_code=422, detail=(
                f"{video_model['name']} supports {video_model['minimum_steps']} to {video_model['maximum_steps']} steps"
            ))
        if request.source_image_id and video_model["family"] == "wan":
            raise HTTPException(status_code=422, detail="Wan 2.1 T2V is text-to-video only; choose an LTX model to animate an image")
        source_image_path = image_library.find_path(request.source_image_id) if request.source_image_id else None
        if request.source_image_id and source_image_path is None:
            raise HTTPException(status_code=404, detail="The selected Creation Gallery image was not found")
        target_displays = requested_target_displays(request.display_ids)
        profile = target_displays[0] if target_displays else active_display_store.get()
        output_width = profile.width if profile else request.width
        output_height = profile.height if profile else request.height
        rotation = profile.video_rotation if isinstance(profile, DisplayDevice) else display_settings_store.get_video_rotation()
        filename = f"ltx-video-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.mp4"
        output_path = video_output_path / filename
        video_metadata: dict[str, object] = {
            "label": request.prompt[:80], "model": {"id": request.model_id, "name": video_model["name"]},
            "prompt": request.prompt, "steps": request.steps, "seed": request.seed,
            "frames": request.num_frames, "fps": request.fps, "source_image_id": request.source_image_id,
            "rotation": rotation,
            "display_id": profile.id if isinstance(profile, DisplayDevice) else None,
            "display_ids": [display.id for display in target_displays],
            "display": (
                {"name": profile.name, "width": profile.width, "height": profile.height}
                if profile is not None else None
            ),
        }

        def generate_video(progress, cancelled):
            generation_started_at = perf_counter()
            generator.unload()
            result = video_generator.generate(
                request.prompt, output_width, output_height, request.num_frames, request.fps,
                request.steps, request.seed, output_path, progress, cancelled, source_image_path, request.model_id,
                rotation=rotation,
            )
            video_metadata["generation_time_seconds"] = round(perf_counter() - generation_started_at, 2)
            if auto_save_videos:
                progress(request.steps, request.steps, "Saving video to your Creation Gallery")
                saved_video = video_library.save(result, video_metadata)
                video_metadata["auto_saved"] = True
                video_metadata["saved_video_id"] = saved_video["id"]
            return result

        job = generation_queue.create(
            "video",
            generate_video,
            video_metadata,
            temporary_media_path=output_path,
        )
        return job.as_dict()

    @app.get("/video-generation-jobs/{job_id}")
    def video_generation_job(job_id: str) -> dict[str, object]:
        job = generation_queue.get(job_id, "video")
        if job is None:
            raise HTTPException(status_code=404, detail="Video generation job not found")
        return job.as_dict()

    @app.post("/video-generation-jobs/{job_id}/save", status_code=status.HTTP_201_CREATED)
    def save_video_to_creation_library(job_id: str) -> dict[str, object]:
        job = generation_queue.acquire_media(job_id, "video")
        if job is None or job.video_path is None:
            raise HTTPException(status_code=409, detail="Video is not ready to save")
        try:
            return video_library.save(job.video_path, job.metadata or {})
        finally:
            generation_queue.release_media(job_id)

    @app.delete("/video-generation-jobs/{job_id}")
    def cancel_video_generation_job(job_id: str) -> dict[str, object]:
        job = generation_queue.cancel(job_id, "video")
        if job is None:
            raise HTTPException(status_code=404, detail="Video generation job not found")
        return job.as_dict()

    @app.get("/video-generation-jobs/{job_id}/video")
    def video_generation_job_video(job_id: str) -> FileResponse:
        job = generation_queue.acquire_media(job_id, "video")
        if job is None:
            raise HTTPException(status_code=404, detail="Video generation job not found")
        if job.video_path is None or not job.video_path.is_file():
            generation_queue.release_media(job_id)
            raise HTTPException(status_code=409, detail="Video is not ready")
        return FileResponse(
            job.video_path,
            media_type="video/mp4",
            filename=job.video_path.name,
            background=BackgroundTask(generation_queue.release_media, job_id),
        )

    return app


app = create_app()
