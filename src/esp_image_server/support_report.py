"""Allowlisted server information and optional sanitized logs for issue reports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import importlib
from importlib import metadata
import ipaddress
import platform
import re


_PACKAGES = {
    "torch": "torch",
    "diffusers": "diffusers",
    "transformers": "transformers",
    "accelerate": "accelerate",
    "fastapi": "fastapi",
    "imageio_ffmpeg": "imageio-ffmpeg",
}
_LOG_LIMIT = 50
_LINE_LIMIT = 1_000
_PROMPT = re.compile(r"prompt", re.IGNORECASE)
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)(?<![\w])['\"]?(?:[a-z0-9]+[_-])*(?:wi[\s_-]*fi[\s_-]*)?"
    r"(?:password|passwd|passphrase|pwd|psk|ssid|api[\s_-]*key|"
    r"(?:access|refresh|auth)[\s_-]*token|token|client[\s_-]*secret|secret(?:[\s_-]*key)?|"
    r"authorization|credentials?|user(?:[\s_-]*name)?|login)['\"]?\s*[:=]"
)
_REDACTIONS = (
    (re.compile(r"(?i)\bbearer\s+[^\s,;\"']+"), "Bearer [redacted]"),
    (re.compile(r"\b(?:hf_|sk-|gh[pousr]_|github_pat_)[A-Za-z0-9_-]{6,}"), "[redacted token]"),
    (re.compile(r"(?i)\b(?:https?|wss?|ftp)://[^\s<>\"')\]]+"), "[network address]"),
    # Absolute Windows, UNC and POSIX paths may include spaces. Conservatively
    # redact to the next quoted-field boundary instead of leaking a basename.
    (re.compile(r"(?i)\b[a-z]:[\\/][^<>\"'\r\n,;]*"), "[local path]"),
    (re.compile(r"\\\\[^\s\\/]+[\\/][^<>\"'\r\n,;]*"), "[local path]"),
    (re.compile(r"//[^\s/]+/[^<>\"'\r\n,;]*"), "[local path]"),
    (re.compile(r"(?<![\w/])/(?!/)[^<>\"'\r\n,;]*"), "[local path]"),
    (re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?"), "[network address]"),
    (re.compile(r"\[[0-9a-fA-F:.%_\-]+\](?::\d+)?"), "[network address]"),
    (re.compile(r"(?i)\b[0-9a-f]{2}(?:[:-][0-9a-f]{2}){5}\b"), "[device identifier]"),
    (re.compile(r"(?i)\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b"), "[device identifier]"),
    (re.compile(r"(?i)(?<![\w])[0-9a-f]{12,}(?![\w])"), "[device identifier]"),
    (re.compile(r"(?i)\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+"
                r"(?:local|lan|home|internal|com|net|org|io|dev|app|edu|gov|co|ca|uk|de|fr)"
                r"(?::\d{1,5})?\b"), "[network address]"),
    (re.compile(r"(?im)(?<![\w])['\"]?(?:ip(?:[\s_-]*address)?|hostname|host|"
                r"server[\s_-]*(?:url|address)|mac(?:[\s_-]*address)?|"
                r"(?:device|hardware|display|board)[\s_-]*id|serial(?:[\s_-]*number)?)"
                r"['\"]?\s*[:=]\s*[^\r\n]+"), "[identifier redacted]"),
)
_IPV6 = re.compile(r"(?<![\w:])(?:[0-9a-fA-F]{0,4}:){2,}[0-9a-fA-F:.]*(?:%[\w.-]+)?")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _platform_value(function) -> str:
    try:
        return str(function()) or "Unknown"
    except Exception:
        # Never include an exception string: it can contain installation paths.
        return "Unknown"


def _package_version(distribution: str) -> str | None:
    try:
        return metadata.version(distribution)
    except Exception:
        return None


def _generation_information(device: str) -> dict[str, object]:
    result: dict[str, object] = {
        "device": device,
        "cuda_available": False,
        "cuda_version": None,
        "gpu_name": None,
        "gpu_memory_bytes": None,
    }
    try:
        torch = importlib.import_module("torch")
    except Exception:
        return result
    try:
        cuda_version = torch.version.cuda
        if isinstance(cuda_version, str):
            result["cuda_version"] = cuda_version
    except Exception:
        pass
    try:
        result["cuda_available"] = bool(torch.cuda.is_available())
    except Exception:
        return result
    if result["cuda_available"]:
        try:
            properties = torch.cuda.get_device_properties(0)
            if isinstance(properties.name, str):
                result["gpu_name"] = properties.name
            if isinstance(properties.total_memory, int) and properties.total_memory >= 0:
                result["gpu_memory_bytes"] = properties.total_memory
        except Exception:
            pass
    return result


def _redact_ipv6(match: re.Match[str]) -> str:
    try:
        ipaddress.IPv6Address(match.group())
    except ValueError:
        return match.group()
    return "[network address]"


def sanitize_report_log(entry: str) -> list[str]:
    """Sanitize one complete log entry before splitting tracebacks into lines.

    Prompt-bearing entries are excluded entirely, including multiline context.
    Credential assignments also discard their whole entry, so spaced, quoted,
    escaped or multiline values cannot escape a value-matching expression.
    """
    if not isinstance(entry, str):
        return []
    text = _CONTROL_CHARACTERS.sub("", _ANSI.sub("", entry))
    if _PROMPT.search(text):
        return []
    if _CREDENTIAL_ASSIGNMENT.search(text):
        return ["[Credential-bearing log entry redacted]"]
    # This existing startup message includes a user-chosen display name.
    if re.search(r"(?i)active display announced\s*:", text):
        return ["[Display registration details redacted]"]
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    text = _IPV6.sub(_redact_ipv6, text)
    return [line[:_LINE_LIMIT] for line in text.splitlines() if line.strip()]


def report_logs(
    diagnostic_entries: Iterable[Mapping[str, object]], console_lines: Iterable[str],
) -> list[str]:
    """Prefer the chronological console mirror; fall back to diagnostics.

    Both stores receive the same server logging records. Using one avoids
    duplicating every error while retaining diagnostics when no console exists.
    """
    console = list(console_lines)[-_LOG_LIMIT:]
    if console:
        entries = console
    else:
        entries = [str(entry.get("message", "")) for entry in reversed(list(diagnostic_entries)[:_LOG_LIMIT])]
    lines: list[str] = []
    for entry in entries:
        lines.extend(sanitize_report_log(entry))
    return lines[-_LOG_LIMIT:]


def create_support_report(
    *, app_version: str, device: str, include_logs: bool = False,
    diagnostic_entries: Iterable[Mapping[str, object]] = (), console_lines: Iterable[str] = (),
) -> dict[str, object]:
    """Return an explicit allowlist, without reading configuration or job data."""
    return {
        "app_version": app_version,
        "system": {
            "os": _platform_value(platform.system),
            "release": _platform_value(platform.release),
            "version": _platform_value(platform.version),
            "architecture": _platform_value(platform.machine),
            "python": _platform_value(platform.python_version),
        },
        "generation": _generation_information(device),
        "packages": {key: _package_version(distribution) for key, distribution in _PACKAGES.items()},
        "logs": report_logs(diagnostic_entries, console_lines) if include_logs else [],
    }
