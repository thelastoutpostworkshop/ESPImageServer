import json
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def setup_fixture(tmp_path, monkeypatch):
    module = runpy.run_path(str(Path(__file__).resolve().parents[1] / "installer/linux-generation-setup.py"))
    scope = module["setup"].__globals__
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setitem(sys.modules, "fcntl", SimpleNamespace(LOCK_EX=1, LOCK_NB=2, flock=lambda *a: None))
    backend = tmp_path / "app"
    (backend / "setup").mkdir(parents=True)
    (backend / ".venv/lib/python3.12/site-packages").mkdir(parents=True)
    (backend / ".venv/lib/python3.12/site-packages/esp-image-server.pth").write_text("../../../../src\n")
    (backend / "runtime-manifest.json").write_text(json.dumps({"python_source": {"sha256": "pinned"}, "app_version": "1.0.0"}))
    for name in ("generation-requirements.txt", "constraints-linux-cuda.txt", "constraints-cuda.txt"):
        (backend / "setup" / name).write_text("torch==example\n")
    (backend / "requirements-resolved.txt").write_text("base==1\n")
    calls, events = [], []
    monkeypatch.setitem(scope, "command", lambda args, env: calls.append(args))
    monkeypatch.setitem(scope, "emit", lambda kind, **values: events.append({"kind": kind, **values}))
    return module, scope, backend, tmp_path / "user", calls, events


def test_publish_only_verified_runtime_and_reuse_across_app_updates(setup_fixture):
    module, _, backend, storage, calls, events = setup_fixture
    module["setup"](backend, storage, check_gpu=False)
    runtime = Path(events[-1]["python"]).parents[2]
    assert (runtime / "ready.json").exists()
    assert "--only-binary=:all:" in calls[0]
    assert any("check" in c for c in calls)
    source_pth = backend / ".venv/lib/python3.12/site-packages/esp-image-server.pth"
    assert source_pth.read_text() == "../../../../src\n"
    manifest = json.loads((backend / "runtime-manifest.json").read_text())
    manifest["app_version"] = "2.0.0"
    (backend / "runtime-manifest.json").write_text(json.dumps(manifest))
    calls.clear()
    module["setup"](backend, storage, check_gpu=False)
    assert len(calls) == 1 and "install" not in calls[0]
    assert Path(events[-1]["python"]).parents[2] == runtime
    (backend / "setup/generation-requirements.txt").write_text("changed==2\n")
    module["setup"](backend, storage, check_gpu=False)
    assert Path(events[-1]["python"]).parents[2] != runtime
    assert (runtime / "ready.json").exists()


def test_failed_download_is_not_ready_and_retry_replaces_partial(setup_fixture, monkeypatch):
    module, scope, backend, storage, calls, events = setup_fixture
    def fail(*args):
        raise RuntimeError("Network interrupted")
    monkeypatch.setitem(scope, "command", fail)
    with pytest.raises(RuntimeError, match="interrupted"):
        module["setup"](backend, storage, check_gpu=False)
    assert not list(storage.glob("*/ready.json"))
    monkeypatch.setitem(scope, "command", lambda args, env: calls.append(args))
    module["setup"](backend, storage, check_gpu=False)
    assert events[-1]["kind"] == "ready"
    assert not list(storage.glob("*.partial"))


def test_gpu_missing_does_not_download(setup_fixture, monkeypatch):
    module, scope, backend, storage, calls, events = setup_fixture
    monkeypatch.setattr(scope["subprocess"], "run", lambda *a, **kw: SimpleNamespace(returncode=1, stdout=""))
    module["setup"](backend, storage)
    assert events[-1]["kind"] == "unsupported"
    assert not calls and not storage.exists()


def test_broken_cached_runtime_is_repairable(setup_fixture, monkeypatch):
    module, scope, backend, storage, calls, events = setup_fixture
    module["setup"](backend, storage, check_gpu=False)
    def fail(*args):
        raise RuntimeError("Missing library")
    monkeypatch.setitem(scope, "command", fail)
    with pytest.raises(RuntimeError):
        module["setup"](backend, storage, check_gpu=False)
    assert not list(storage.glob("*/ready.json"))
    monkeypatch.setitem(scope, "command", lambda args, env: calls.append(args))
    module["setup"](backend, storage, check_gpu=False)
    assert events[-1]["kind"] == "ready"
