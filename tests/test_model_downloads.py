"""Exercise the real Hub cache without network access or model inference."""

import hashlib
import importlib
from pathlib import Path
import sys
from threading import Event
from types import SimpleNamespace

import pytest

from esp_image_server.config import Settings
from esp_image_server import download_progress
from esp_image_server.generator import DiffusersGenerator
from esp_image_server.models import get_model, model_is_cached, remove_cached_model
from esp_image_server import video_generator


SDXL = "stabilityai/stable-diffusion-xl-base-1.0"
COMMIT = "a" * 40
FILES = {
    "model_index.json": b'{"_class_name": "StableDiffusionXLPipeline"}',
    "unet/config.json": b'{"sample_size": 128}',
    "unet/weights.bin": b"tiny fixture weights, never loaded by Diffusers",
}


@pytest.fixture
def hub_cache(tmp_path, monkeypatch):
    """Stub only the remote metadata/bytes; retain Hub's cache and threading."""
    hub = pytest.importorskip("huggingface_hub")
    snapshot_module = importlib.import_module("huggingface_hub._snapshot_download")
    file_module = importlib.import_module("huggingface_hub.file_download")
    requests = pytest.importorskip("requests")
    cache = tmp_path / "c"
    state = SimpleNamespace(
        hub=hub, cache=cache, downloads=[], metadata=[], workers=[],
        symlink_attempts=[], fail_once=set(), competing_symlink=Event(),
    )
    monkeypatch.setattr(download_progress, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(file_module, "_are_symlinks_supported_in_dir", {})
    monkeypatch.setattr(file_module.constants, "HF_HUB_DISABLE_SYMLINKS_WARNING", True)
    monkeypatch.setattr(snapshot_module.constants, "HF_HUB_ENABLE_HF_TRANSFER", False)

    def no_network(*args, **kwargs):
        pytest.fail("A fixture model download attempted a network request")

    monkeypatch.setattr(requests.sessions.Session, "request", no_network)

    def repo_info(self, *, repo_id, **kwargs):
        return SimpleNamespace(
            sha=COMMIT,
            siblings=[SimpleNamespace(rfilename=name) for name in FILES],
        )

    monkeypatch.setattr(snapshot_module.HfApi, "repo_info", repo_info)

    def metadata(*, filename, **kwargs):
        state.metadata.append(filename)
        data = FILES[filename]
        etag = hashlib.sha256(data).hexdigest()[:12]
        return f"https://fixture.invalid/{filename}", etag, COMMIT, len(data), None, None

    monkeypatch.setattr(file_module, "_get_metadata_or_catch_error", metadata)

    def download_bytes(*, filename, destination_path, incomplete_path, **kwargs):
        state.downloads.append(filename)
        if filename in state.fail_once:
            state.fail_once.remove(filename)
            incomplete_path.write_bytes(FILES[filename][:4])
            raise OSError("Fixture connection interrupted")
        destination_path.write_bytes(FILES[filename])
        incomplete_path.unlink(missing_ok=True)

    monkeypatch.setattr(file_module, "_download_to_tmp_and_move", download_bytes)

    def denied_symlink(src, dst, **kwargs):
        state.symlink_attempts.append((src, dst))
        if len(state.symlink_attempts) == 1:
            # Keep the first probe open long enough for a parallel worker to
            # observe Hub's tentative True result. With one worker, no second
            # download starts until the probe has selected its copy fallback.
            state.competing_symlink.wait(0.1)
        else:
            state.competing_symlink.set()
        error = OSError("A required privilege is not held by the client")
        error.winerror = 1314
        raise error

    monkeypatch.setattr(file_module.os, "symlink", denied_symlink)
    original_thread_map = snapshot_module.thread_map

    def thread_map(*args, **kwargs):
        state.workers.append(kwargs["max_workers"])
        return original_thread_map(*args, **kwargs)

    monkeypatch.setattr(snapshot_module, "thread_map", thread_map)
    return state


def assert_plain_snapshot(snapshot):
    snapshot = Path(snapshot)
    for filename, expected in FILES.items():
        path = snapshot / filename
        assert path.is_file()
        assert not path.is_symlink()
        assert path.read_bytes() == expected


def test_sdxl_load_without_symlinks(hub_cache, tmp_path, monkeypatch):
    monkeypatch.setenv("ESP_IMAGE_MODEL_CACHE", str(tmp_path / "other-cache"))
    monkeypatch.setattr(DiffusersGenerator, "_detect_device", staticmethod(lambda: "cuda"))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(float16="fp16"))
    loaded = []
    devices = []
    pipeline = SimpleNamespace(to=lambda device: devices.append(device) or pipeline)

    def from_pretrained(snapshot, **kwargs):
        assert_plain_snapshot(snapshot)
        loaded.append((Path(snapshot), kwargs))
        return pipeline

    monkeypatch.setitem(sys.modules, "diffusers", SimpleNamespace(
        AutoPipelineForText2Image=SimpleNamespace(from_pretrained=from_pretrained),
    ))
    progress = []
    generator = DiffusersGenerator(Settings(model_id=SDXL, model_cache_dir=hub_cache.cache))

    generator.load(lambda *args: progress.append(args))

    assert generator.ready
    assert loaded == [(
        hub_cache.cache / "models--stabilityai--stable-diffusion-xl-base-1.0" / "snapshots" / COMMIT,
        {"safety_checker": None, "requires_safety_checker": False, "torch_dtype": "fp16"},
    )]
    assert devices == ["cuda"]
    assert hub_cache.workers == [1]
    assert len(hub_cache.symlink_attempts) == 1
    assert hub_cache.downloads == list(FILES)
    assert any("Loading" in message for _, _, message in progress)
    assert not (tmp_path / "other-cache").exists()


def test_partial_cache_retry_and_reuse(hub_cache):
    repo = hub_cache.cache / "models--stabilityai--stable-diffusion-xl-base-1.0"
    # An existing blob must be copied rather than moved: another revision may
    # still need it. Other newly downloaded blobs use Hub's normal move path.
    blob = repo / "blobs" / hashlib.sha256(FILES["model_index.json"]).hexdigest()[:12]
    blob.parent.mkdir(parents=True)
    blob.write_bytes(FILES["model_index.json"])
    hub_cache.fail_once.add("unet/weights.bin")
    options = download_progress.model_snapshot_download_options()

    with pytest.raises(OSError, match="Fixture connection interrupted"):
        hub_cache.hub.snapshot_download(SDXL, cache_dir=hub_cache.cache, **options)

    snapshot = repo / "snapshots" / COMMIT
    assert (snapshot / "model_index.json").read_bytes() == FILES["model_index.json"]
    assert (snapshot / "unet/config.json").read_bytes() == FILES["unet/config.json"]
    assert not (snapshot / "unet/weights.bin").exists()
    assert blob.read_bytes() == FILES["model_index.json"]

    result = hub_cache.hub.snapshot_download(SDXL, cache_dir=hub_cache.cache, **options)
    assert_plain_snapshot(result)
    assert hub_cache.downloads == ["unet/config.json", "unet/weights.bin", "unet/weights.bin"]
    assert not list(repo.rglob("*.incomplete"))
    metadata_count = len(hub_cache.metadata)
    download_count = len(hub_cache.downloads)

    assert hub_cache.hub.snapshot_download(SDXL, cache_dir=hub_cache.cache, **options) == result
    assert len(hub_cache.metadata) == metadata_count
    assert len(hub_cache.downloads) == download_count
    assert (repo / "refs/main").read_text() == COMMIT
    assert hub_cache.workers == [1, 1, 1]


def test_remove_and_reinstall_one_model(hub_cache, tmp_path):
    options = download_progress.model_snapshot_download_options()
    snapshot = hub_cache.hub.snapshot_download(SDXL, cache_dir=hub_cache.cache, **options)
    other_model = get_model("Lykon/dreamshaper-8")
    other_snapshot = Path(hub_cache.hub.snapshot_download(
        other_model.model_id, cache_dir=hub_cache.cache, **options,
    ))
    creation = tmp_path / "saved-creation.jpg"
    creation.write_bytes(b"user creation")
    model = get_model(SDXL)

    assert model_is_cached(model, hub_cache.cache)
    assert model_is_cached(other_model, hub_cache.cache)
    assert remove_cached_model(model, hub_cache.cache)
    assert not model_is_cached(model, hub_cache.cache)
    assert not Path(snapshot).exists()
    assert model_is_cached(other_model, hub_cache.cache)
    assert_plain_snapshot(other_snapshot)
    assert creation.read_bytes() == b"user creation"

    reinstalled = hub_cache.hub.snapshot_download(SDXL, cache_dir=hub_cache.cache, **options)
    assert_plain_snapshot(reinstalled)
    assert model_is_cached(model, hub_cache.cache)
    assert_plain_snapshot(other_snapshot)


@pytest.mark.parametrize("platform,expected_options", [("win32", {"max_workers": 1}), ("linux", {})])
@pytest.mark.parametrize("family", ["image", "wan", "ltx"])
def test_loader_snapshot_options(tmp_path, monkeypatch, platform, expected_options, family):
    """All cache-based loaders apply the fix without altering other arguments."""
    monkeypatch.setattr(download_progress, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setenv("ESP_IMAGE_MODEL_CACHE", str(tmp_path))
    monkeypatch.setattr(DiffusersGenerator, "_detect_device", staticmethod(lambda: "cuda"))
    monkeypatch.setattr(video_generator, "detect_generation_device", lambda: "cuda")
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(float16="fp16"))
    monkeypatch.setitem(sys.modules, "diffusers", SimpleNamespace(
        AutoPipelineForText2Image=object(), AutoencoderKLWan=object(),
        WanPipeline=object(), LTXPipeline=object(),
    ))
    monkeypatch.setitem(sys.modules, "diffusers.schedulers.scheduling_unipc_multistep", SimpleNamespace(
        UniPCMultistepScheduler=object(),
    ))
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(T5EncoderModel=object()))
    calls = []

    class StopBeforeModelLoad(Exception):
        pass

    def snapshot_download(*args, **kwargs):
        calls.append((args, kwargs))
        raise StopBeforeModelLoad

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot_download))
    with pytest.raises(StopBeforeModelLoad):
        if family == "image":
            DiffusersGenerator(Settings(model_id=SDXL, model_cache_dir=tmp_path)).load()
        else:
            model_id = "wan-2.1-t2v-1.3b" if family == "wan" else "ltx-2b-0.9.6-distilled"
            video_generator.LTXVideoGenerator()._load(model_id)

    expected_kwargs = {"cache_dir": tmp_path, "tqdm_class": None, **expected_options}
    if family == "ltx":
        expected_args = ()
        expected_kwargs.update(
            repo_id=video_generator.LTXVideoGenerator.checkpoint_repository,
            allow_patterns=video_generator.VIDEO_MODELS[model_id]["checkpoint"],
        )
    else:
        repository = SDXL if family == "image" else video_generator.VIDEO_MODELS[model_id]["repository"]
        expected_args = (repository,)
    assert calls == [(expected_args, expected_kwargs)]
