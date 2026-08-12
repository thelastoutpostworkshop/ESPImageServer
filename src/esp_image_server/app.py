"""HTTP API for ESPImageServer."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from io import BytesIO
import json
import logging
import os
from pathlib import Path
import subprocess
from threading import Timer
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

    def activate_model(self, settings: Settings) -> None: ...

    def generate(self, prompt: str, width: int | None = None, height: int | None = None, progress=None, inference_steps=None, seed=None) -> Image.Image: ...


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=1_000, description="Text to turn into an image")
    steps: int | None = Field(default=None, ge=1, le=100, description="Model inference steps")
    seed: int | None = Field(default=None, ge=0, le=4_294_967_295, description="Optional repeatable random seed")


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


class RegisterDeviceRequest(BaseModel):
    pairing_code: str = Field(min_length=6, max_length=6)
    name: str = Field(min_length=1, max_length=64)


class AcknowledgeImageRequest(BaseModel):
    image_id: str = Field(min_length=1, max_length=64)


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
    app_settings_store = app_settings_store or AppSettingsStore()
    persisted_app_settings = app_settings_store.get()
    library_location = persisted_app_settings.get("image_library_location")
    image_library = image_library or ImageLibrary(Path(library_location) if isinstance(library_location, str) else None)
    jpeg_quality = persisted_app_settings.get("jpeg_quality", settings.jpeg_quality)
    jpeg_quality = jpeg_quality if isinstance(jpeg_quality, int) and 1 <= jpeg_quality <= 100 else settings.jpeg_quality
    auto_save_images = persisted_app_settings.get("auto_save_images", True)
    auto_save_images = auto_save_images if isinstance(auto_save_images, bool) else True

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
        await run_in_threadpool(generator.load)
        logger.info("Image model is ready; device=%s", generator.device)
        if os.getenv("ESP_IMAGE_OPEN_BROWSER") == "1":
            Timer(0.5, lambda: webbrowser.open_new_tab(f"http://127.0.0.1:{settings.port}/")).start()
        try:
            yield
        finally:
            if mdns is not None:
                mdns.close()
            generation_jobs.close()

    app = FastAPI(title="ESPImageServer", version="0.1.79", lifespan=lifespan)
    app.state.device_manager = device_manager
    app.state.latest_image_store = latest_image_store
    app.state.active_display_store = active_display_store
    app.state.display_settings_store = display_settings_store
    app.state.model_selection_store = model_selection_store
    app.state.generation_jobs = generation_jobs
    app.state.image_library = image_library
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
            active_model_id, (active_model_id, "Local AI image model selected during installation.")
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
        try:
            selected_settings = model_settings(settings, model_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="This model is not available in ESPImageServer") from exc
        if model_id == active_model_id:
            return {"status": "active", "model_id": model_id}
        try:
            await run_in_threadpool(generator.activate_model, selected_settings)
            model_selection_store.set(model_id)
        except Exception:
            logger.exception("Unable to activate image model '%s'", model_id)
            raise HTTPException(status_code=500, detail="Unable to download or load the selected model") from None
        active_settings = selected_settings
        active_model_id = model_id
        logger.info("Active image model changed to %s", model_id)
        return {"status": "active", "model_id": model_id}

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
        }

    @app.put("/app-settings")
    def update_app_settings(request: AppSettingsRequest) -> dict[str, object]:
        nonlocal jpeg_quality, auto_save_images
        if request.image_library_location is not None:
            location = Path(request.image_library_location)
            if not location.is_absolute():
                raise HTTPException(status_code=422, detail="Choose an absolute folder path for the image library")
            try:
                image_library.relocate(location)
            except (OSError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=f"Could not move the image library: {exc}") from exc
        if request.jpeg_quality is not None:
            jpeg_quality = request.jpeg_quality
        if request.auto_save_images is not None:
            auto_save_images = request.auto_save_images
        app_settings_store.set({
            "image_library_location": str(image_library.path),
            "jpeg_quality": jpeg_quality,
            "auto_save_images": auto_save_images,
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
            raise RuntimeError("Image model is still loading")
        profile = active_display_store.get()
        output_width = profile.width if profile else settings.output_width
        output_height = profile.height if profile else settings.output_height
        rotation = display_settings_store.get_rotation()
        artwork_width, artwork_height = (
            (output_height, output_width) if rotation in {90, 270} else (output_width, output_height)
        )
        generation_width, generation_height = optimal_generation_size(active_model_id, artwork_width, artwork_height)
        model = get_model(active_model_id)
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
        )
        ensure_not_cancelled()
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
        jpeg = to_jpeg(image, width=output_width, height=output_height, quality=jpeg_quality)
        metadata = {
            "version": 1,
            "createdAt": datetime.now(UTC).isoformat(),
            "model": {"id": active_model_id, "name": model.name},
            "prompt": request.prompt,
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
            image_library.save(jpeg, metadata)
        return jpeg

    @app.post("/generate", response_class=Response, responses={200: {"content": {"image/jpeg": {}}}})
    async def generate(request: GenerateRequest) -> Response:
        try:
            jpeg = await run_in_threadpool(generate_jpeg, request)
        except Exception:
            logger.exception("Image generation failed")
            raise HTTPException(status_code=500, detail="Image generation failed") from None
        return Response(content=jpeg, media_type="image/jpeg")

    @app.post("/generation-jobs", status_code=status.HTTP_202_ACCEPTED)
    def create_generation_job(request: GenerateRequest) -> dict[str, object]:
        if not generator.ready:
            raise HTTPException(status_code=503, detail="Image model is still loading")
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

    return app


app = create_app()
