"""Hugging Face download settings and job-progress adapters."""

from __future__ import annotations

import sys
from typing import Callable

from tqdm.auto import tqdm


DownloadProgress = Callable[[int, int, str], None]


def model_snapshot_download_options() -> dict[str, int]:
    """Avoid a concurrent Windows symlink probe in Hugging Face's cache.

    The installed Hub library publishes a tentative supported result before
    the probe finishes. One file worker lets it select its normal move/copy
    fallback before another file can try creating a privileged symlink.
    """
    return {"max_workers": 1} if sys.platform == "win32" else {}


def huggingface_progress(label: str, report: DownloadProgress):
    """Create the ``tqdm_class`` accepted by ``snapshot_download``.

    Hugging Face reports completed files rather than an aggregate byte count.
    That is still real download progress and, unlike a timer-based estimate,
    remains correct when a cached model only needs a few files.
    """
    class DownloadTqdm(tqdm):
        def update(self, n: int = 1):
            result = super().update(n)
            if self.total:
                report(int(self.n), int(self.total), f"Downloading {label}: {int(self.n)} of {int(self.total)} files")
            return result

    return DownloadTqdm
