"""Turn common local AI stack errors into helpful messages for the web app."""

from __future__ import annotations


def user_facing_generation_error(error: Exception, kind: str) -> str:
    """Return a stable, non-technical error while callers log the original."""
    message = str(error).casefold()
    label = "video" if kind == "video" else "image"

    if any(marker in message for marker in (
        "cuda out of memory", "outofmemoryerror", "cuda error: out of memory",
        "cuda error: memory allocation", "not enough memory",
    )):
        suggestion = "Try fewer frames or a shorter clip." if kind == "video" else "Try a smaller image model or close other GPU applications."
        return f"Your graphics card does not have enough memory for this {label}. {suggestion}"
    if any(marker in message for marker in (
        "no cuda gpus are available", "no cuda gpu is available", "cuda is not available",
        "torch.cuda.is_available", "requires a compatible nvidia gpu",
    )):
        return "A compatible NVIDIA graphics card is required for this generation."
    if "winerror 1314" in message or "required privilege is not held" in message:
        return "Windows prevented the model files from being prepared. Enable Developer Mode, then try again."
    if any(marker in message for marker in (
        "does not appear to have a file named", "weights for this component appear to be missing",
        "safetensors", "checkpoint",
    )) and any(marker in message for marker in ("missing", "not found", "does not appear", "failed to load")):
        return "The downloaded model files are incomplete. Try again to download the model again."
    if any(marker in message for marker in (
        "couldn't connect", "connection error", "network is unreachable", "name resolution",
        "failed to download", "huggingface",
    )):
        return "The model could not be downloaded. Check your internet connection and try again."
    return f"Could not generate the {label}. Please try again; if it continues, check the server log."
