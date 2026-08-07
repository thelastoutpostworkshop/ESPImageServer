import uvicorn

from .app import app
from .config import Settings


if __name__ == "__main__":
    settings = Settings.from_env()
    uvicorn.run(app, host=settings.host, port=settings.port)
