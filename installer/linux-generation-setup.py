"""Install the pinned generation runtime into private, persistent user storage."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def emit(kind, **values):
    print(json.dumps({"kind": kind, **values}), flush=True)


def runtime_key(backend):
    manifest = json.loads((backend / "runtime-manifest.json").read_text())
    digest = hashlib.sha256(manifest["python_source"]["sha256"].encode())
    for name in ("generation-requirements.txt", "constraints-linux-cuda.txt", "constraints-cuda.txt"):
        digest.update((backend / "setup" / name).read_bytes())
    digest.update((backend / "requirements-resolved.txt").read_bytes())
    return digest.hexdigest()[:24]


def command(args, env):
    with subprocess.Popen([str(a) for a in args], stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, env=env) as process:
        for line in process.stdout:
            emit("log", text=line.rstrip())
        if process.wait():
            raise RuntimeError("Generation dependency setup failed. Check the setup details and retry.")


def setup(backend, storage, *, check_gpu=True):
    if sys.platform != "linux":
        raise RuntimeError("Generation setup is supported on Linux only")
    if check_gpu:
        emit("status", title="Checking NVIDIA graphics", detail="Checking the installed NVIDIA driver before downloading generation components.")
        try:
            probe = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                                   capture_output=True, text=True, timeout=20)
            if probe.returncode or not probe.stdout.strip():
                raise OSError("No NVIDIA GPU reported")
        except (OSError, subprocess.TimeoutExpired):
            emit("unsupported", detail="Image and video generation requires a working NVIDIA GPU and driver. Install or repair the NVIDIA driver, then retry.")
            return
    import fcntl
    storage.mkdir(parents=True, exist_ok=True)
    with (storage / "setup.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Generation setup is already running. Wait for it to finish, then retry.")
        key = runtime_key(backend)
        destination = storage / key
        staging = storage / (key + ".partial")
        if staging.is_symlink() or destination.is_symlink():
            raise RuntimeError("Unexpected symbolic link in generation runtime storage")
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
        env["PYTHONUNBUFFERED"] = "1"
        verification = (
            "import torch, torchvision, sentencepiece; "
            "from transformers import T5Tokenizer; "
            "from diffusers import AutoPipelineForText2Image, LTXPipeline, WanPipeline; "
            "assert torch.__version__ == '2.11.0+cu128'; "
            "assert torchvision.__version__ == '0.26.0+cu128'; "
            "assert torchvision.ops.nms(torch.tensor([[0.,0.,2.,2.]]),torch.tensor([1.]),0.5).tolist()==[0]"
        )
        if not (destination / "ready.json").is_file():
            if destination.exists():
                shutil.rmtree(destination)
            if staging.exists():
                shutil.rmtree(staging)
            emit("status", title="Preparing image and video generation", detail="Preparing a private Python runtime. Existing models and creations are preserved.")
            shutil.copytree(backend / ".venv", staging / ".venv", symlinks=True)
            python = staging / ".venv/bin/python"
            emit("status", title="Downloading generation components", detail="This first-time setup downloads several GB. Progress is shown below. Closing the app stops setup; reopen it to retry.")
            command([python, "-I", "-m", "pip", "install", "--only-binary=:all:",
                     "--cache-dir", storage / "downloads", "--progress-bar", "off",
                     "--constraint", backend / "setup/constraints-linux-cuda.txt",
                     "--extra-index-url", "https://download.pytorch.org/whl/cu128",
                     "-r", backend / "setup/generation-requirements.txt"], env)
            emit("status", title="Verifying generation components", detail="Checking image/video libraries before starting the server.")
            command([python, "-I", "-m", "pip", "check"], env)
            command([python, "-I", "-c", verification], env)
            (staging / "ready.json").write_text(json.dumps({"key": key}))
            # Publish only a fully verified runtime. Never overwrite an active version.
            if destination.exists():
                raise RuntimeError("An incomplete runtime already exists; check setup storage before retrying")
            staging.rename(destination)
        python = destination / ".venv/bin/python"
        # Point reused dependencies at the CURRENT installed app, not an old release.
        emit("status", title="Checking generation readiness", detail="Verifying the saved runtime and GPU compatibility.")
        try:
            (destination / ".venv/lib/python3.12/site-packages/esp-image-server.pth").write_text(str(backend / "src") + "\n", encoding="utf-8")
            command([python, "-I", "-c", verification], env)
        except Exception:
            (destination / "ready.json").unlink(missing_ok=True)
            raise
        if check_gpu:
            gpu = subprocess.run([str(python), "-I", "-c",
                "import torch; assert torch.cuda.is_available(); x=torch.ones(1,device='cuda'); assert x.item()==1"],
                capture_output=True, text=True, env=env, timeout=90)
            if gpu.returncode:
                emit("log", text=gpu.stderr[-4000:])
                emit("unsupported", detail="The generation components are installed, but the NVIDIA GPU cannot run them. Check the driver and GPU compatibility, then retry.")
                return
        emit("ready", python=str(python))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backend", type=Path)
    parser.add_argument("storage", type=Path)
    parser.add_argument("--ci-no-gpu", action="store_true")
    args = parser.parse_args()
    try:
        if args.ci_no_gpu and os.environ.get("GITHUB_ACTIONS") != "true":
            raise RuntimeError("The no-GPU dependency check is restricted to GitHub Actions")
        setup(args.backend.resolve(), args.storage.resolve(), check_gpu=not args.ci_no_gpu)
    except Exception as error:
        emit("error", detail=str(error))
        sys.exit(1)
