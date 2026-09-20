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
