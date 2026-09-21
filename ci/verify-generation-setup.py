"""Exercise real Linux dependency download and offline reuse on a CPU-only runner."""
import json
import os
from pathlib import Path
import subprocess
import sys

backend = Path(sys.argv[1]).resolve()
storage = Path(sys.argv[2]).resolve()
helper = backend / "setup/linux-generation-setup.py"
command = [str(backend / ".venv/bin/python"), "-I", "-u", str(helper), str(backend), str(storage), "--ci-no-gpu"]


def run(environment):
    ready = None
    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True, env=environment) as child:
        for line in child.stdout:
            print(line, end="", flush=True)
            event = json.loads(line)
            if event["kind"] == "ready":
                ready = Path(event["python"])
        assert child.wait() == 0 and ready
    return ready


python = run(os.environ.copy())
stamp = (python.parents[2] / "ready.json").stat().st_mtime_ns
# An unavailable package index must not affect reuse across app-only updates.
manifest_path = backend / "runtime-manifest.json"
original = manifest_path.read_text()
manifest = json.loads(original)
manifest["app_version"] = "99.0.0"
try:
    manifest_path.write_text(json.dumps(manifest))
    assert run({**os.environ, "PIP_NO_INDEX": "1"}) == python
    assert (python.parents[2] / "ready.json").stat().st_mtime_ns == stamp
finally:
    manifest_path.write_text(original)
subprocess.run([str(python), "-I", "-B", "ci/verify-native-runtime.py", str(backend), str(python.parents[2])], check=True)
print("PASS: generation dependencies installed, verified, reused offline, and served the current app")
