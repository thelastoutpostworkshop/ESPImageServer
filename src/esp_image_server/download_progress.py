"""Adapters that turn Hugging Face file-download progress into job progress."""

from __future__ import annotations

from typing import Callable

from tqdm.auto import tqdm


DownloadProgress = Callable[[int, int, str], None]


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
