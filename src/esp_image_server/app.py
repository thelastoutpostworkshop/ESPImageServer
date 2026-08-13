"""HTTP API for ESPImageServer."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
import hashlib
from io import BytesIO
import json
import logging
import os
from pathlib import Path
import subprocess
from threading import Lock, Timer
from typing import Protocol
import webbrowser

from fastapi import FastAPI, Header, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from PIL import Image

from .config import Settings
from .app_settings import AppSettingsStore
from .display import ActiveDisplayStore
from .display_commands import DisplayCommandStore
from .display_settings import DisplaySettingsStore, VALID_ROTATIONS
from .devices import DeviceError, DeviceManager
from .generator import DiffusersGenerator
from .generation_jobs import GenerationCancelled, GenerationJobStore
from .generation_size import optimal_generation_size
from .image_processor import to_jpeg
from .image_library import ImageLibrary
from .latest_image import LatestImageStore
from .mdns import MdnsAdvertiser
from .models import MODELS, get_model, model_is_cached, model_settings
from .model_settings import ModelSelectionStore
from .video_generator import LTXVideoGenerator, VIDEO_MODELS
from .video_jobs import VideoJobStore
from .video_library import VideoLibrary

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
    steps: int | None = Field(default=None, ge=1, le=100, description="Model inference steps")
    seed: int | None = Field(default=None, ge=0, le=4_294_967_295, description="Optional repeatable random seed")
    negative_prompt: str | None = Field(default=None, max_length=1_000)


class DisplayAnnouncement(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    width: int = Field(ge=64, le=1_024)
    height: int = Field(ge=64, le=1_024)


class DisplaySettingsRequest(BaseModel):
    rotation: int


class AppSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image_library_location: str | None = Field(default=None, min_length=1)
    jpeg_quality: int | None = Field(default=None, ge=1, le=100)
    auto_save_images: bool | None = None
    confirm_deletion: bool | None = None


class RegisterDeviceRequest(BaseModel):
    pairing_code: str = Field(min_length=6, max_length=6)
    name: str = Field(min_length=1, max_length=64)


class AcknowledgeImageRequest(BaseModel):
    image_id: str = Field(min_length=1, max_length=64)


class DisplayCommandAcknowledgement(BaseModel):
    success: bool
    detail: str = Field(default="", max_length=200)


class DisplaySDCardReport(BaseModel):
    available: bool
    mode: str = Field(pattern="^(live_images|sd_card)$")
    total_bytes: int = Field(ge=0)
    used_bytes: int = Field(ge=0)
    files: list[dict[str, object]] = Field(default_factory=list)


class VideoGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=1_000)
    width: int = Field(default=512, ge=1, le=768)
    height: int = Field(default=320, ge=1, le=768)
    num_frames: int = Field(default=25, ge=9, le=249)
    fps: int = Field(default=8, ge=4, le=24)
    steps: int = Field(default=8, ge=4, le=40)
    model_id: str = Field(default="ltx-2b-0.9.6-distilled")
    seed: int | None = Field(default=None, ge=0, le=4_294_967_295)
    source_image_id: str | None = Field(default=None, min_length=1, max_length=64)


def create_app(
    settings: Settings | None = None,
    generator: ImageGenerator | None = None,
    device_manager: DeviceManager | None = None,
    latest_image_store: LatestImageStore | None = None,
    active_display_store: ActiveDisplayStore | None = None,
    display_settings_store: DisplaySettingsStore | None = None,
    model_selection_store: ModelSelectionStore | None = None,
    image_library: ImageLibrary | None = None,
    app_settings_store: AppSettingsStore | None = None,
    generation_jobs: GenerationJobStore | None = None,
    display_command_store: DisplayCommandStore | None = None,
    video_generator: LTXVideoGenerator | None = None,
    video_jobs: VideoJobStore | None = None,
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
    generation_jobs = generation_jobs or GenerationJobStore()
    display_command_store = display_command_store or DisplayCommandStore()
    video_generator = video_generator or LTXVideoGenerator()
    video_jobs = video_jobs or VideoJobStore()
    # Only one model family may own the GPU at a time. The lock covers the
    # check, unload, and job creation so simultaneous requests cannot overlap.
    generation_mode_lock = Lock()
    model_loading_status: dict[str, object] = {"active": False, "step": 0, "steps": 0, "stage": ""}
    video_output_path = Path(os.getenv("LOCALAPPDATA", Path.home() / ".local")) / "ESPImageServer" / "videos"
    sd_thumbnail_path = Path(os.getenv("LOCALAPPDATA", Path.home() / ".local")) / "ESPImageServer" / "display_sd_thumbnails"
    app_settings_store = app_settings_store or AppSettingsStore()
    persisted_app_settings = app_settings_store.get()
    library_location = persisted_app_settings.get("image_library_location")
    image_library = image_library or ImageLibrary(Path(library_location) if isinstance(library_location, str) else None)
    video_library = VideoLibrary(image_library.path)
    jpeg_quality = persisted_app_settings.get("jpeg_quality", settings.jpeg_quality)
    jpeg_quality = jpeg_quality if isinstance(jpeg_quality, int) and 1 <= jpeg_quality <= 100 else settings.jpeg_quality
    auto_save_images = persisted_app_settings.get("auto_save_images", True)
    auto_save_images = auto_save_images if isinstance(auto_save_images, bool) else True
    confirm_deletion = persisted_app_settings.get("confirm_deletion", True)
    confirm_deletion = confirm_deletion if isinstance(confirm_deletion, bool) else True

    @asynccontextmanager
    async def lifespan(_: FastAPI):
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
            generation_jobs.close()
            video_jobs.close()

    app = FastAPI(title="ESPImageServer", version="1.0.20", lifespan=lifespan)
    app.state.device_manager = device_manager
    app.state.latest_image_store = latest_image_store
    app.state.active_display_store = active_display_store
    app.state.display_settings_store = display_settings_store
    app.state.model_selection_store = model_selection_store
    app.state.generation_jobs = generation_jobs
    app.state.display_command_store = display_command_store
    app.state.image_library = image_library
    app.state.video_jobs = video_jobs
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
        return {
            "status": "ready" if generator.ready else "loading",
            "device": generator.device,
            "generating": generation_jobs.has_active_job(),
        }

    @app.get("/server-info")
    def server_info() -> dict[str, object]:
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
        }

    @app.get("/models")
    def list_models() -> list[dict[str, object]]:
        return [
            {
                "id": model.model_id,
                "name": model.name,
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
        if generation_jobs.has_active_job():
            raise HTTPException(
                status_code=409,
                detail="Wait for the current image generation to finish before changing models",
            )
        if video_jobs.has_active_job():
            raise HTTPException(
                status_code=409,
                detail="Wait for the current video generation to finish before loading an image model",
            )
        try:
            selected_settings = model_settings(settings, model_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="This model is not available in ESPImageServer") from exc
        if model_id == active_model_id and generator.ready:
            return {"status": "active", "model_id": model_id}
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
            }
        return JSONResponse(content=payload, headers={"Cache-Control": "no-store, max-age=0"})

    @app.post("/display", status_code=status.HTTP_201_CREATED)
    def announce_display(announcement: DisplayAnnouncement) -> dict[str, object]:
        profile = active_display_store.set(
            announcement.name, announcement.width, announcement.height
        )
        logger.info("Active display announced: %s (%sx%s)", profile.name, profile.width, profile.height)
        return {"status": "registered", "name": profile.name, "width": profile.width, "height": profile.height}

    @app.get("/display-settings")
    def get_display_settings() -> dict[str, int]:
        return {"rotation": display_settings_store.get_rotation()}

    @app.put("/display-settings")
    def update_display_settings(request: DisplaySettingsRequest) -> dict[str, int]:
        if request.rotation not in VALID_ROTATIONS:
            raise HTTPException(status_code=422, detail="Image rotation must be 0, 90, 180, or 270 degrees")
        return {"rotation": display_settings_store.set_rotation(request.rotation)}

    @app.post("/display-commands/save-latest", status_code=status.HTTP_202_ACCEPTED)
    def save_latest_to_display_sd_card() -> dict[str, object]:
        latest_image = latest_image_store.get()
        if latest_image is None:
            raise HTTPException(status_code=409, detail="Generate an image before saving it to the display SD card")
        return queue_image_save(latest_image.jpeg)

    @app.post("/display-commands/save-saved-image/{image_id}", status_code=status.HTTP_202_ACCEPTED)
    def save_creation_library_image_to_display_sd_card(image_id: str) -> dict[str, object]:
        image_path = image_library.find_path(image_id)
        if image_path is None:
            raise HTTPException(status_code=404, detail="Saved image not found")
        return queue_image_save(image_path.read_bytes(), image_id)

    def queue_image_save(jpeg: bytes, image_id: str | None = None) -> dict[str, object]:
        image_hash = hashlib.sha256(jpeg).hexdigest()[:16]
        filename = f"esp-image-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{image_hash}.jpg"
        if display_command_store.sd_card_has_image_hash(image_hash):
            return {"status": "already_saved", "filename": filename, "detail": "Image is already on the display SD card"}
        command = display_command_store.queue_save(filename, image_id)
        write_sd_thumbnail(filename, jpeg)
        return command

    def write_sd_thumbnail(filename: str, jpeg: bytes) -> None:
        """Keep the server copy paired with the thumbnail written to the SD card."""
        thumbnail_path = sd_thumbnail_path / Path(filename).name
        thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(BytesIO(jpeg)) as source:
            thumbnail_path.write_bytes(to_jpeg(source, width=160, height=120, quality=70))

    @app.get("/display-sd-card")
    def get_display_sd_card() -> dict[str, object]:
        report = display_command_store.sd_card_report()
        files = report.get("files", [])
        if isinstance(files, list):
            report["files"] = [
                {**file, "thumbnail_available": (sd_thumbnail_path / Path(str(file.get("name", ""))).name).is_file()}
                for file in files if isinstance(file, dict)
            ]
        return report

    @app.get("/display-sd-card/thumbnails/{filename}", response_class=Response)
    def get_display_sd_card_thumbnail(filename: str) -> Response:
        thumbnail_path = sd_thumbnail_path / Path(filename).name
        if not thumbnail_path.is_file():
            raise HTTPException(status_code=404, detail="SD card thumbnail not available")
        return FileResponse(thumbnail_path, media_type="image/jpeg")

    @app.post("/display-sd-card/report", status_code=status.HTTP_204_NO_CONTENT)
    def report_display_sd_card(report: DisplaySDCardReport) -> Response:
        display_command_store.report_sd_card(report.model_dump())
        return Response(status_code=status.HTTP_204_NO_CONTENT)

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
            "auto_save_images": auto_save_images,
            "confirm_deletion": confirm_deletion,
        }

    @app.put("/app-settings")
    def update_app_settings(request: AppSettingsRequest) -> dict[str, object]:
        nonlocal jpeg_quality, auto_save_images, confirm_deletion
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
        if request.auto_save_images is not None:
            auto_save_images = request.auto_save_images
        if request.confirm_deletion is not None:
            confirm_deletion = request.confirm_deletion
        app_settings_store.set({
            "image_library_location": str(image_library.path),
            "jpeg_quality": jpeg_quality,
            "auto_save_images": auto_save_images,
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
    def latest_image(if_none_match: str | None = Header(default=None)) -> Response:
        image = latest_image_store.get()
        if image is None:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        etag = f'"{image.image_id}"'
        if if_none_match == etag:
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
        return Response(
            content=image.jpeg,
            media_type="image/jpeg",
            headers={"ETag": etag, "Cache-Control": "no-cache"},
        )

    @app.get("/saved-images")
    def saved_images() -> list[dict[str, object]]:
        return image_library.list()

    @app.get("/saved-videos")
    def saved_videos() -> list[dict[str, object]]:
        return video_library.list()

    @app.get("/saved-videos/{video_id}/video")
    def saved_video(video_id: str) -> FileResponse:
        video_path = video_library.find_path(video_id)
        if video_path is None:
            raise HTTPException(status_code=404, detail="Saved video not found")
        return FileResponse(video_path, media_type="video/mp4", filename=video_path.name)

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
    def saved_image(image_id: str) -> FileResponse:
        image_path = image_library.find_path(image_id)
        if image_path is None:
            raise HTTPException(status_code=404, detail="Saved image not found")
        return FileResponse(image_path, media_type="image/jpeg", filename=image_path.name)

    @app.post("/saved-images/{image_id}/display", status_code=status.HTTP_202_ACCEPTED)
    def show_saved_image_on_display(image_id: str) -> dict[str, object]:
        """Make a saved creation the next image retrieved by the ESP32."""
        image_path = image_library.find_path(image_id)
        if image_path is None:
            raise HTTPException(status_code=404, detail="Saved image not found")
        try:
            profile = active_display_store.get()
            width = profile.width if profile else settings.output_width
            height = profile.height if profile else settings.output_height
            with Image.open(image_path) as source:
                latest_image_store.set(to_jpeg(source, width=width, height=height, quality=jpeg_quality))
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"Could not prepare saved image for the display: {exc}") from exc
        return {"message": "Saved image is ready for the display"}

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

    def generate_jpeg(request: GenerateRequest, progress=None, is_cancelled=None) -> bytes:
        def ensure_not_cancelled() -> None:
            if is_cancelled is not None and is_cancelled():
                raise GenerationCancelled()

        ensure_not_cancelled()
        if not generator.ready:
            # A fresh installation deliberately has no model.  A generation
            # request is the user's explicit choice to fetch and load the
            # currently selected model.
            generator.activate_model(active_settings)
        profile = active_display_store.get()
        output_width = profile.width if profile else settings.output_width
        output_height = profile.height if profile else settings.output_height
        rotation = display_settings_store.get_rotation()
        artwork_width, artwork_height = (
            (output_height, output_width) if rotation in {90, 270} else (output_width, output_height)
        )
        generation_width, generation_height = optimal_generation_size(active_model_id, artwork_width, artwork_height)
        model = get_model(active_model_id)
        if request.negative_prompt and not model.supports_negative_prompt:
            raise ValueError(f"{model.name} does not support negative prompts")
        steps = request.steps if request.steps is not None else model.inference_steps
        if not model.minimum_steps <= steps <= model.maximum_steps:
            raise ValueError(f"{model.name} supports {model.minimum_steps} to {model.maximum_steps} steps")
        if progress is not None:
            progress(0, 0, "Preparing the image model")
        ensure_not_cancelled()
        image = generator.generate(
            request.prompt, generation_width, generation_height,
            progress=(lambda step, steps: progress(step, steps, "Generating image")) if progress else None,
            inference_steps=steps,
            seed=request.seed,
            cancelled=is_cancelled,
            negative_prompt=request.negative_prompt,
        )
        ensure_not_cancelled()
        if image.convert("RGB").getbbox() is None:
            raise RuntimeError("The model returned a blank image. Please try generating again.")
        if progress is not None:
            if rotation:
                progress(1, 1, "Rotating image for your ESP32 display")
            else:
                progress(1, 1, "Fitting the image to your ESP32 display")
        if rotation == 90:
            image = image.transpose(Image.Transpose.ROTATE_270)
        elif rotation == 180:
            image = image.transpose(Image.Transpose.ROTATE_180)
        elif rotation == 270:
            image = image.transpose(Image.Transpose.ROTATE_90)
        ensure_not_cancelled()
        if progress is not None and rotation:
            progress(1, 1, "Fitting the image to your ESP32 display")
        if progress is not None:
            progress(1, 1, "Encoding image for your ESP32 display")
        jpeg = to_jpeg(image, width=output_width, height=output_height, quality=jpeg_quality)
        metadata = {
            "version": 1,
            "createdAt": datetime.now(UTC).isoformat(),
            "model": {"id": active_model_id, "name": model.name},
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt,
            "steps": steps,
            "seed": request.seed,
            "rotation": rotation,
            "display": (
                {"name": profile.name, "width": profile.width, "height": profile.height}
                if profile is not None else None
            ),
        }
        jpeg = embed_jpeg_metadata(jpeg, metadata)
        ensure_not_cancelled()
        latest_image_store.set(jpeg)
        if auto_save_images:
            if progress is not None:
                progress(1, 1, "Saving image to your Creation Gallery")
            image_library.save(jpeg, metadata)
        return jpeg

    @app.post("/generate", response_class=Response, responses={200: {"content": {"image/jpeg": {}}}})
    async def generate(request: GenerateRequest) -> Response:
        if video_jobs.has_active_job():
            raise HTTPException(status_code=409, detail="Wait for the current video generation to finish before generating an image")
        try:
            await run_in_threadpool(video_generator.unload)
            jpeg = await run_in_threadpool(generate_jpeg, request)
        except RuntimeError as exc:
            logger.exception("Image generation failed")
            raise HTTPException(status_code=500, detail=str(exc)) from None
        except Exception:
            logger.exception("Image generation failed")
            raise HTTPException(status_code=500, detail="Image generation failed") from None
        return Response(content=jpeg, media_type="image/jpeg")

    @app.post("/generation-jobs", status_code=status.HTTP_202_ACCEPTED)
    def create_generation_job(request: GenerateRequest) -> dict[str, object]:
        with generation_mode_lock:
            if video_jobs.has_active_job():
                raise HTTPException(
                    status_code=409,
                    detail="Wait for the current video generation to finish before generating an image",
                )
            video_generator.unload()
            job = generation_jobs.create(lambda progress, is_cancelled: generate_jpeg(request, progress, is_cancelled))
        return job.as_dict()

    @app.get("/generation-jobs/{job_id}")
    def generation_job(job_id: str) -> dict[str, object]:
        job = generation_jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Generation job not found")
        return job.as_dict()

    @app.delete("/generation-jobs/{job_id}")
    def cancel_generation_job(job_id: str) -> dict[str, object]:
        job = generation_jobs.cancel(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Generation job not found")
        return job.as_dict()

    @app.get("/generation-jobs/{job_id}/image", response_class=Response)
    def generation_job_image(job_id: str) -> Response:
        job = generation_jobs.get(job_id)
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
        with generation_mode_lock:
            if generation_jobs.has_active_job():
                raise HTTPException(
                    status_code=409,
                    detail="Wait for the current image generation to finish before generating a video",
                )
            generator.unload()
            source_image_path = image_library.find_path(request.source_image_id) if request.source_image_id else None
            if request.source_image_id and source_image_path is None:
                raise HTTPException(status_code=404, detail="The selected Creation Gallery image was not found")
            profile = active_display_store.get()
            output_width = profile.width if profile else request.width
            output_height = profile.height if profile else request.height
            filename = f"ltx-video-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.mp4"
            output_path = video_output_path / filename
            job = video_jobs.create(lambda progress, cancelled: video_generator.generate(
                request.prompt, output_width, output_height, request.num_frames, request.fps,
            request.steps, request.seed, output_path, progress, cancelled, source_image_path,
            request.model_id,
            ))
            job.metadata = {
                "model": {"id": request.model_id, "name": video_model["name"]}, "prompt": request.prompt,
                "steps": request.steps, "seed": request.seed, "frames": request.num_frames, "fps": request.fps,
                "source_image_id": request.source_image_id,
            }
        return job.as_dict()

    @app.get("/video-generation-jobs/{job_id}")
    def video_generation_job(job_id: str) -> dict[str, object]:
        job = video_jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Video generation job not found")
        return job.as_dict()

    @app.post("/video-generation-jobs/{job_id}/save", status_code=status.HTTP_201_CREATED)
    def save_video_to_creation_library(job_id: str) -> dict[str, object]:
        job = video_jobs.get(job_id)
        if job is None or job.status != "complete" or job.video_path is None:
            raise HTTPException(status_code=409, detail="Video is not ready to save")
        return video_library.save(job.video_path, job.metadata or {})

    @app.delete("/video-generation-jobs/{job_id}")
    def cancel_video_generation_job(job_id: str) -> dict[str, object]:
        job = video_jobs.cancel(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Video generation job not found")
        return job.as_dict()

    @app.get("/video-generation-jobs/{job_id}/video")
    def video_generation_job_video(job_id: str) -> FileResponse:
        job = video_jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Video generation job not found")
        if job.status != "complete" or job.video_path is None or not job.video_path.is_file():
            raise HTTPException(status_code=409, detail="Video is not ready")
        return FileResponse(job.video_path, media_type="video/mp4", filename=job.video_path.name)

    return app


app = create_app()
