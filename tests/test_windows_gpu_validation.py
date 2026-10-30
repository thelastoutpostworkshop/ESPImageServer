"""Exercise the production GPU-check invocation under Windows PowerShell 5.1.

Only the GPU block and logging function are evaluated; the bootstrap installer
body is never executed. A local fake torch module records checks and computation
without importing real PyTorch, touching a GPU, or installing anything.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


PROJECT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell GPU validation")

HARNESS = r'''
param([string]$Bootstrap, [string]$Interpreter, [string]$FixtureRoot, [string]$Outcome)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
if ($PSVersionTable.PSVersion.Major -ne 5) { throw 'Use Windows PowerShell 5.1' }
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($Bootstrap, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
$function = @($ast.EndBlock.Statements | Where-Object {
    $_ -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $_.Name -eq 'Invoke-LoggedExternal'
})
if ($function.Count -ne 1) { throw 'Missing production invocation helper' }
. ([scriptblock]::Create($function[0].Extent.Text))
$gpuBlock = @($ast.FindAll({ param($node)
    $node -is [Management.Automation.Language.IfStatementAst] -and
    $node.Extent.Text.Contains("'verify-gpu.py'")
}, $true))
if ($gpuBlock.Count -ne 1) { throw 'Missing production GPU validation block' }
function Write-InstallLog([string]$Message) { Write-Host $Message }
$UseCuda = $true
$venvPython = $Interpreter
$projectRoot = $FixtureRoot
$gpuCheckExitCode = $null
$failure = $null
$global:LASTEXITCODE = 0
try { . ([scriptblock]::Create($gpuBlock[0].Extent.Text)) }
catch { $failure = $_.Exception.Message }
@{ code = $gpuCheckExitCode; error = $failure; native_exit_code = $global:LASTEXITCODE } |
    ConvertTo-Json -Compress | Set-Content -LiteralPath $Outcome -Encoding UTF8
'''

FAKE_TORCH = r'''
import json
import os
from pathlib import Path
from types import SimpleNamespace

scenario = os.environ["ESP_TEST_GPU_SCENARIO"]
if scenario == "import_error":
    raise OSError("Synthetic DLL load failure: MSVCP140.dll")

def record(name):
    with Path(__file__).with_name("calls.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(name) + "\n")

version = SimpleNamespace(cuda=None if scenario == "cpu" else "12.8")
__version__ = "fixture"

class Cuda:
    def is_available(self):
        record("available")
        if scenario == "availability_error":
            raise RuntimeError("Synthetic CUDA initialization failure")
        return scenario != "unavailable"

    def synchronize(self):
        record("synchronize")
        if scenario == "synchronize_error":
            raise RuntimeError("Synthetic CUDA execution failure")

    def get_device_properties(self, index):
        if index != 0:
            raise RuntimeError("Unexpected device")
        record("properties")
        return SimpleNamespace(name="Fixture GPU", total_memory=8 * 1024**3)

cuda = Cuda()

class Tensor:
    def __matmul__(self, other):
        record("matmul")
        return self

    def __eq__(self, expected):
        if expected != 16:
            raise RuntimeError("Unexpected expected result")
        record("compare")
        return self

    def all(self):
        record("all")
        return self

    def item(self):
        record("item")
        return scenario != "wrong_result"

def ones(shape, device):
    if shape != (16, 16) or device != "cuda":
        raise RuntimeError("Unexpected computation parameters")
    record("ones")
    if scenario == "allocation_error":
        raise RuntimeError("Synthetic CUDA allocation failure")
    return Tensor()
'''


def run_validation(tmp_path, scenario="success", *, check_source=None, missing_script=False, missing_interpreter=False):
    # Every scenario uses a path that exposed fragile native argument handling.
    fixture = tmp_path / "Installed app é 日本語"
    fixture.mkdir()
    if not missing_script:
        destination = fixture / "verify-gpu.py"
        if check_source is None:
            shutil.copyfile(PROJECT / "installer/verify-gpu.py", destination)
        else:
            destination.write_text(check_source, encoding="utf-8")
    (fixture / "torch.py").write_text(FAKE_TORCH, encoding="utf-8")
    harness = tmp_path / "gpu-harness.ps1"
    harness.write_text(HARNESS, encoding="utf-8-sig")
    outcome = tmp_path / "outcome.json"
    interpreter = fixture / "missing-python.exe" if missing_interpreter else Path(sys.executable)
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    environment = os.environ.copy()
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    environment.update(
        ESP_TEST_GPU_SCENARIO=scenario,
        PYTHONOPTIMIZE="2",  # Validation must not disappear with Python asserts.
        PYTHONIOENCODING="utf-8",
    )
    result = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(harness), "-Bootstrap", str(PROJECT / "installer/bootstrap.ps1"),
         "-Interpreter", str(interpreter), "-FixtureRoot", str(fixture), "-Outcome", str(outcome)],
        env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    details = json.loads(outcome.read_text(encoding="utf-8-sig"))
    calls_path = fixture / "calls.jsonl"
    calls = [json.loads(line) for line in calls_path.read_text(encoding="utf-8").splitlines()] if calls_path.exists() else []
    return details, calls, result.stdout + result.stderr


@pytest.mark.parametrize("scenario,expected_code,message,calls", [
    ("import_error", 10, "PyTorch could not be loaded", []),
    ("cpu", 11, "CPU-only PyTorch", []),
    ("unavailable", 12, "cannot access a compatible NVIDIA GPU", ["available"]),
    ("availability_error", 12, "cannot access a compatible NVIDIA GPU", ["available"]),
    ("allocation_error", 13, "CUDA computation check failed", ["available", "ones"]),
    ("synchronize_error", 13, "CUDA computation check failed", ["available", "ones", "matmul", "synchronize"]),
    ("wrong_result", 13, "CUDA computation check failed", ["available", "ones", "matmul", "synchronize", "compare", "all", "item"]),
])
def test_validation_rejects_failures_with_specific_recovery_advice(tmp_path, scenario, expected_code, message, calls):
    outcome, actual_calls, output = run_validation(tmp_path, scenario)
    assert outcome["code"] == expected_code, output
    assert message in outcome["error"], output
    assert actual_calls == calls
    assert "CUDA computation passed" not in output
    if scenario == "import_error":
        assert "MSVCP140.dll" in output
        assert "NVIDIA driver" not in outcome["error"]


def test_success_runs_and_verifies_the_complete_computation_with_optimization_enabled(tmp_path):
    outcome, calls, output = run_validation(tmp_path)
    assert outcome == {"code": 0, "error": None, "native_exit_code": 0}, output
    assert calls == ["available", "ones", "matmul", "synchronize", "compare", "all", "item", "properties"]
    assert "CUDA computation passed: Fixture GPU, 8.0 GiB" in output


def test_missing_validation_script_fails_before_launching_python(tmp_path):
    outcome, calls, output = run_validation(tmp_path, missing_script=True)
    assert outcome["code"] is None, output
    assert "GPU validation script is missing" in outcome["error"]
    assert not calls


def test_unexpected_process_failure_is_not_reported_as_a_gpu_driver_problem(tmp_path):
    outcome, calls, output = run_validation(tmp_path, check_source="raise SystemExit(71)\n")
    assert outcome["code"] == 71, output
    assert "failed unexpectedly (exit code 71)" in outcome["error"]
    assert "NVIDIA driver" not in outcome["error"]
    assert not calls


def test_interpreter_launch_failure_cannot_reuse_a_previous_success_exit_code(tmp_path):
    outcome, calls, output = run_validation(tmp_path, missing_interpreter=True)
    # PowerShell raises before assigning a check result for a missing command.
    # The helper must also invalidate the seeded successful native exit code.
    assert outcome["code"] is None, output
    assert outcome["native_exit_code"] == 1
    assert "missing-python.exe" in outcome["error"]
    assert "CUDA computation passed" not in output
    assert not calls
