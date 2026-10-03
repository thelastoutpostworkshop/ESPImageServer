"""Turn common local AI stack errors into helpful messages for the web app."""

from __future__ import annotations


def user_facing_generation_error(error: Exception, kind: str) -> str:
    """Return a clear error followed by the original detail for troubleshooting."""
    message = str(error).casefold()
    label = "video" if kind == "video" else "image"
    details = str(error).strip() or type(error).__name__

    if any(marker in message for marker in (
        "cuda out of memory", "outofmemoryerror", "cuda error: out of memory",
        "cuda error: memory allocation", "not enough memory",
    )):
        suggestion = "Try fewer frames or a shorter clip." if kind == "video" else "Try a smaller image model or close other GPU applications."
        friendly = f"Your graphics card does not have enough memory for this {label}. {suggestion}"
    elif any(marker in message for marker in (
        "no cuda gpus are available", "no cuda gpu is available", "cuda is not available",
        "torch.cuda.is_available", "requires a compatible nvidia gpu",
    )):
        friendly = "A compatible NVIDIA graphics card is required for this generation."
    elif "winerror 1314" in message or "required privilege is not held" in message:
        friendly = "Windows could not prepare the model files. Restart ESPImageServer and try again. If it continues, check the server log."
    elif any(marker in message for marker in (
        "does not appear to have a file named", "weights for this component appear to be missing",
        "safetensors", "checkpoint",
    )) and any(marker in message for marker in ("missing", "not found", "does not appear", "failed to load")):
        friendly = "The downloaded model files are incomplete. Try again to download the model again."
    elif any(marker in message for marker in (
        "couldn't connect", "connection error", "network is unreachable", "name resolution",
        "failed to download", "huggingface",
    )):
        friendly = "The model could not be downloaded. Check your internet connection and try again."
    else:
        friendly = f"Could not generate the {label}. Please try again; if it continues, check the server log."

    return f"{friendly}\n\nTechnical details: {details}"
