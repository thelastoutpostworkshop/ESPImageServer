import sys
from types import SimpleNamespace

import pytest

from esp_image_server.generation_capabilities import GenerationCapabilities, detect_generation_device
from esp_image_server.generator import DiffusersGenerator
from esp_image_server.video_generator import LTXVideoGenerator, VIDEO_MODELS
from esp_image_server.config import Settings


@pytest.mark.parametrize("device", ["cpu", "mps", "xpu", "unknown"])
def test_unsupported_devices_cannot_place_or_seed_models(device):
    capabilities = GenerationCapabilities(device)
    for family in ("image", "ltx", "wan"):
        assert not capabilities.supports(family)
        with pytest.raises(RuntimeError, match="CPU generation is not supported"):
            capabilities.place_pipeline(object(), family)
        with pytest.raises(RuntimeError):
            capabilities.seeded_generator(object(), 42, family)


def test_model_precision_and_offload_policy_preserves_cuda_behavior():
    capabilities = GenerationCapabilities("cuda")
    assert capabilities.policy("image").precision == "float16"
    assert capabilities.policy("ltx").precision == "bfloat16"
    assert capabilities.policy("wan").precision == "bfloat16"
    assert capabilities.policy("wan").vae_precision == "float32"
    calls = []
    pipeline = SimpleNamespace(to=lambda device: calls.append(device) or pipeline,
                               enable_model_cpu_offload=lambda: calls.append("offload"))
    for family in ("image", "ltx", "wan"):
        assert capabilities.place_pipeline(pipeline, family) is pipeline
    assert calls == ["cuda", "cuda", "offload"]
    with pytest.raises(RuntimeError):
        capabilities.policy("unsupported-model-family")


def test_seed_is_created_on_cuda_and_none_does_not_allocate():
    calls = []
    torch = SimpleNamespace(Generator=lambda **kwargs: calls.append(kwargs) or
                            SimpleNamespace(manual_seed=lambda seed: seed))
    caps = GenerationCapabilities("cuda")
    assert caps.seeded_generator(torch, None) is None
    assert calls == []
    assert caps.seeded_generator(torch, 123, "wan") == 123
    assert calls == [{"device": "cuda"}]


def test_mps_availability_does_not_enable_generation(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: False),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: True))))
    assert detect_generation_device() == "cpu"


@pytest.mark.parametrize("model_id", list(VIDEO_MODELS))
def test_video_rejects_broken_cuda_before_downloads(monkeypatch, tmp_path, model_id):
    def broken(*args, **kwargs):
        raise RuntimeError("driver failed")
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: True), empty=broken))
    monkeypatch.setenv("ESP_IMAGE_MODEL_CACHE", str(tmp_path / "not-created"))
    with pytest.raises(RuntimeError, match="working NVIDIA GPU"):
        LTXVideoGenerator()._load(model_id)
    assert not (tmp_path / "not-created").exists()


@pytest.mark.parametrize("kind", ["image", "video"])
def test_unload_releases_pipeline_before_emptying_cache(monkeypatch, kind):
    monkeypatch.setattr(DiffusersGenerator, "_detect_device", staticmethod(lambda: "cuda"))
    generator = DiffusersGenerator(Settings()) if kind == "image" else LTXVideoGenerator()
    calls = []
    def clear():
        assert generator._pipeline is None
        calls.append("clear")
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: True, empty_cache=clear)))
    generator._pipeline = SimpleNamespace(to=lambda device: calls.append(device))
    generator.unload()
    assert calls == ["cpu", "clear"]

    generator.unload()
    assert calls == ["cpu", "clear"]


@pytest.mark.parametrize("model_id", list(VIDEO_MODELS))
def test_video_loader_applies_family_policy(monkeypatch, tmp_path, model_id):
    calls = []
    torch = SimpleNamespace(float32="fp32", bfloat16="bf16",
        cuda=SimpleNamespace(is_available=lambda: True, synchronize=lambda: None), empty=lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setenv("ESP_IMAGE_MODEL_CACHE", str(tmp_path))
    vae = SimpleNamespace(enable_tiling=lambda: calls.append("tile"), enable_slicing=lambda: calls.append("slice"))
    pipeline = SimpleNamespace(vae=vae, scheduler=SimpleNamespace(config={}),
        to=lambda device: calls.append(device) or pipeline,
        enable_model_cpu_offload=lambda: calls.append("offload"))
    def load_pipeline(*args, **kwargs):
        calls.append(("pipeline", kwargs["torch_dtype"]))
        return pipeline
    def load_vae(*args, **kwargs):
        calls.append(("vae", kwargs["torch_dtype"]))
        return vae
    def load_encoder(*args, **kwargs):
        calls.append(("encoder", kwargs["torch_dtype"]))
        return object()
    monkeypatch.setitem(sys.modules, "diffusers", SimpleNamespace(
        AutoencoderKLWan=SimpleNamespace(from_pretrained=load_vae),
        WanPipeline=SimpleNamespace(from_pretrained=load_pipeline),
        LTXPipeline=SimpleNamespace(from_single_file=load_pipeline)))
    monkeypatch.setitem(sys.modules, "diffusers.schedulers.scheduling_unipc_multistep", SimpleNamespace(
        UniPCMultistepScheduler=SimpleNamespace(from_config=lambda *a, **k: object())))
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(T5EncoderModel=SimpleNamespace(from_pretrained=load_encoder)))
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=lambda *a, **k: str(tmp_path)))
    generator = LTXVideoGenerator()
    generator._load(model_id)
    assert generator.ready
    assert ("pipeline", "bf16") in calls
    if VIDEO_MODELS[model_id]["family"] == "wan":
        assert ("vae", "fp32") in calls
        assert "offload" in calls and "cuda" not in calls
    else:
        assert ("encoder", "bf16") in calls
        assert "cuda" in calls and "offload" not in calls
