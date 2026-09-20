import sys
from types import SimpleNamespace
import pytest
from esp_image_server.config import Settings
from esp_image_server.generator import DiffusersGenerator

def test_cuda_driver_failure_leaves_management_available(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError('CUDA driver failure')
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True), empty=fail))
    generator = DiffusersGenerator(Settings())
    assert generator.device == 'cpu'
    with pytest.raises(RuntimeError, match='CPU generation is not supported'):
        generator.load()

def test_usable_cuda_runs_probe(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: True, synchronize=lambda: calls.append('sync')),
        empty=lambda *args, **kwargs: calls.append(kwargs['device']),
    ))
    assert DiffusersGenerator(Settings()).device == 'cuda'
    assert calls == ['cuda', 'sync']


def test_image_loading_honors_settings_cache_override(tmp_path, monkeypatch):
    cache = tmp_path / 'chosen models'
    monkeypatch.setenv('ESP_IMAGE_MODEL_CACHE', str(tmp_path / 'environment models'))
    monkeypatch.setattr(DiffusersGenerator, '_detect_device', staticmethod(lambda: 'cuda'))
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(float16='float16'))
    monkeypatch.setitem(sys.modules, 'diffusers', SimpleNamespace(AutoPipelineForText2Image=object()))
    calls = []

    class StopBeforeDownload(Exception):
        pass

    def snapshot_download(model, **kwargs):
        calls.append(kwargs['cache_dir'])
        raise StopBeforeDownload

    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(snapshot_download=snapshot_download))
    generator = DiffusersGenerator(Settings(model_cache_dir=cache))
    with pytest.raises(StopBeforeDownload):
        generator.load()
    assert calls == [cache]
    assert cache.is_dir()
    assert not (tmp_path / 'environment models').exists()
