"""HTTP API for ESPImageServer."""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
from threading import Timer
from typing import Protocol
import webbrowser

from fastapi import FastAPI, Header, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from PIL import Image

from .config import Settings
from .devices import DeviceError, DeviceManager
from .generator import DiffusersGenerator
from .image_processor import to_jpeg
from .latest_image import LatestImageStore
from .mdns import MdnsAdvertiser
from .test_page import TEST_PAGE_HTML

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


class ImageGenerator(Protocol):
    ready: bool
    device: str

    def load(self) -> None: ...

    def generate(self, prompt: str, width: int | None = None, height: int | None = None) -> Image.Image: ...


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=1_000, description="Text to turn into an image")
    width: int | None = Field(default=None, ge=64, le=1_024, description="JPEG width for the ESP32")
    height: int | None = Field(default=None, ge=64, le=1_024, description="JPEG height for the ESP32")


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
    enable_mdns: bool = True,
) -> FastAPI:
    settings = settings or Settings.from_env()
    generator = generator or DiffusersGenerator(settings)
    device_manager = device_manager or DeviceManager()
    latest_image_store = latest_image_store or LatestImageStore()

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

    app = FastAPI(title="ESPImageServer", version="0.1.11", lifespan=lifespan)
    app.state.device_manager = device_manager
    app.state.latest_image_store = latest_image_store
    app.mount(
        "/assets",
        StaticFiles(directory=Path(__file__).with_name("static")),
        name="assets",
    )

    @app.get("/", include_in_schema=False, response_class=HTMLResponse)
    def test_page() -> HTMLResponse:
        return HTMLResponse(TEST_PAGE_HTML)

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"status": "ready" if generator.ready else "loading", "device": generator.device}

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

    @app.post("/generate", response_class=Response, responses={200: {"content": {"image/jpeg": {}}}})
    async def generate(request: GenerateRequest) -> Response:
        if not generator.ready:
            raise HTTPException(status_code=503, detail="Image model is still loading")
        try:
            output_width = request.width or settings.output_width
            output_height = request.height or settings.output_height
            generation_width = max(64, round(output_width / 8) * 8)
            generation_height = max(64, round(output_height / 8) * 8)
            image = await run_in_threadpool(
                generator.generate, request.prompt, generation_width, generation_height
            )
            jpeg = to_jpeg(
                image,
                width=output_width,
                height=output_height,
                quality=settings.jpeg_quality,
            )
            latest_image_store.set(jpeg)
        except Exception:
            logger.exception("Image generation failed")
            raise HTTPException(status_code=500, detail="Image generation failed") from None
        return Response(content=jpeg, media_type="image/jpeg")

    return app


app = create_app()
