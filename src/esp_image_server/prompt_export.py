"""Plain-text prompt exports using only the settings saved with each creation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable


NOT_RECORDED = "Not recorded"
ROTATION_LABELS = {
    0: "Normal (0°)",
    90: "90° clockwise",
    180: "180°",
    270: "90° counter-clockwise (270°)",
}


def _saved_value(value: object, missing: str = NOT_RECORDED) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return missing
    return str(value) if value != "" else missing


def _model_label(metadata: dict[str, object]) -> str:
    model = metadata.get("model")
    if isinstance(model, dict):
        name = _saved_value(model.get("name"), "")
        model_id = _saved_value(model.get("id"), "")
    else:
        name = _saved_value(metadata.get("model_name"), "")
        model_id = _saved_value(metadata.get("model_id"), "")
        if isinstance(model, str) and model:
            model_id = model_id or model
    if name and model_id and name != model_id:
        return f"{name} ({model_id})"
    return name or model_id or NOT_RECORDED


def _rotation(metadata: dict[str, object]) -> int | None:
    value = metadata.get("rotation")
    return value if isinstance(value, int) and not isinstance(value, bool) and value in ROTATION_LABELS else None


def _orientation(metadata: dict[str, object], rotation: int | None) -> str:
    display = metadata.get("display")
    if not isinstance(display, dict) or rotation is None:
        return NOT_RECORDED
    width, height = display.get("width"), display.get("height")
    if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in (width, height)):
        return NOT_RECORDED
    if rotation in {90, 270}:
        width, height = height, width
    name = "Landscape" if width > height else "Portrait" if width < height else "Square"
    return f"{name} ({width} x {height})"


def format_gallery_prompts(
    images: Iterable[dict[str, object]],
    videos: Iterable[dict[str, object]],
    *,
    exported_at: datetime | None = None,
) -> str:
    """Render every supplied saved record without consulting current settings."""
    exported_at = exported_at or datetime.now(UTC)
    entries = [("Image", record) for record in images] + [("Video", record) for record in videos]
    entries.sort(key=lambda entry: str(entry[1].get("created_at", "")), reverse=True)
    lines = [
        "ESPImageServer — Creation Gallery prompts",
        f"Exported: {exported_at.astimezone(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"Saved items: {len(entries)}",
        "",
    ]
    if not entries:
        lines.append("No saved images or videos were found in the Creation Gallery.")
    for index, (media_type, record) in enumerate(entries, start=1):
        metadata = record.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        rotation = _rotation(metadata)
        negative_prompt = metadata.get("negative_prompt") if "negative_prompt" in metadata else metadata.get("negativePrompt")
        lines.extend([
            f"{index}. {media_type}: {_saved_value(record.get('filename'))}",
            f"Model: {_model_label(metadata)}",
            f"Orientation: {_orientation(metadata, rotation)}",
            f"Rotation: {ROTATION_LABELS[rotation] if rotation is not None else NOT_RECORDED}",
            f"Steps: {_saved_value(metadata.get('steps'))}",
            f"Seed: {_saved_value(metadata.get('seed'))}",
            "Prompt:",
            _saved_value(metadata.get("prompt")),
            "Negative prompt:",
            _saved_value(negative_prompt, "None"),
            "",
        ])
    return "\n".join(lines).rstrip("\n") + "\n"
