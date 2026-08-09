"""Choose efficient diffusion canvases for a display's aspect ratio."""

from __future__ import annotations


MODEL_LONG_EDGES = {
    "stabilityai/sd-turbo": 512,
    "Lykon/dreamshaper-8": 512,
    "segmind/SSD-1B": 1024,
}


def optimal_generation_size(model_id: str, output_width: int, output_height: int) -> tuple[int, int]:
    """Return an aspect-matched, multiple-of-eight canvas for a supported model."""
    long_edge = MODEL_LONG_EDGES.get(model_id, 512)
    if output_width >= output_height:
        width = long_edge
        height = round((long_edge * output_height / output_width) / 8) * 8
    else:
        height = long_edge
        width = round((long_edge * output_width / output_height) / 8) * 8
    return max(64, width), max(64, height)
