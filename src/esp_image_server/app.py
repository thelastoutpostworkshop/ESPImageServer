"""HTTP API for ESPImageServer."""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
from threading import Timer
from typing import Protocol
import webbrowser

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from PIL import Image

from .config import Settings
from .generator import DiffusersGenerator
from .image_processor import to_jpeg
from .test_page import TEST_PAGE_HTML

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


class ImageGenerator(Protocol):
    ready: bool
    device: str

    def load(self) -> None: ...

    def generate(self, prompt: str) -> Image.Image: ...


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=1_000, description="Text to turn into an image")


def create_app(settings: Settings | None = None, generator: ImageGenerator | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    generator = generator or DiffusersGenerator(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
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
        yield

    app = FastAPI(title="ESPImageServer", version="0.1.8", lifespan=lifespan)
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

    @app.post("/generate", response_class=Response, responses={200: {"content": {"image/jpeg": {}}}})
    async def generate(request: GenerateRequest) -> Response:
        if not generator.ready:
            raise HTTPException(status_code=503, detail="Image model is still loading")
        try:
            image = await run_in_threadpool(generator.generate, request.prompt)
            jpeg = to_jpeg(
                image,
                width=settings.output_width,
                height=settings.output_height,
                quality=settings.jpeg_quality,
            )
        except Exception:
            logger.exception("Image generation failed")
            raise HTTPException(status_code=500, detail="Image generation failed") from None
        return Response(content=jpeg, media_type="image/jpeg")

    return app


app = create_app()
