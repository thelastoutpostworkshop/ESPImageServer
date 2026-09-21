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


def run(environment, expect_success=True):
    ready = None
    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True, env=environment) as child:
        for line in child.stdout:
            print(line, end="", flush=True)
            event = json.loads(line)
            if event["kind"] == "ready":
                ready = Path(event["python"])
        code = child.wait()
        if expect_success:
            assert code == 0 and ready
        else:
            assert code != 0 and ready is None, "A failed dependency update must not publish a runtime"
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
# Exercise a changed dependency set that cannot be resolved offline. It must
# leave the verified previous environment intact and usable after restoration.
requirements = backend / "setup/generation-requirements.txt"
original_requirements = requirements.read_text()
old_marker = (python.parents[2] / "ready.json").read_bytes()
try:
    requirements.write_text(original_requirements + "\nespimageserver-upgrade-fixture-missing==0.0.0\n")
    run({**os.environ, "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}, expect_success=False)
    assert (python.parents[2] / "ready.json").read_bytes() == old_marker
    assert len(list(storage.glob("*/ready.json"))) == 1
finally:
    requirements.write_text(original_requirements)
assert run({**os.environ, "PIP_NO_INDEX": "1"}) == python
subprocess.run([str(python), "-I", "-B", "ci/verify-native-runtime.py", str(backend), str(python.parents[2])], check=True)
print("PASS: dependencies installed, reused offline, survived a failed dependency update, and served the current app")
