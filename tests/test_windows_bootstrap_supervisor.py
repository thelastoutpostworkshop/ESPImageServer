"""Exercise real Windows process supervision with harmless fixture workers only.

No test invokes bootstrap.ps1, package managers, GPU work, or an installer.
All long-running fixture processes have a finite lifetime and are cleaned up
through retained handles so a recycled PID can never target another process.
"""

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from functools import lru_cache
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest


PROJECT = Path(__file__).resolve().parents[1]
SUPERVISOR = PROJECT / "installer/bootstrap-supervisor.ps1"
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows process supervision")


def powershell():
    return Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"


def ps_string(value):
    return "'" + str(value).replace("'", "''") + "'"


def write_script(path, body, parameters=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Windows PowerShell 5.1 needs a BOM for Unicode fixture source text.
    path.write_text(parameters + "\n$ErrorActionPreference = 'Stop'\n" + body, encoding="utf-8-sig")
    return path


def wait_until(predicate, description, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for {description}")


@lru_cache(maxsize=1)
def kernel32():
    native = ctypes.WinDLL("kernel32", use_last_error=True)
    native.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    native.OpenProcess.restype = wintypes.HANDLE
    native.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    native.WaitForSingleObject.restype = wintypes.DWORD
    native.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    native.TerminateProcess.restype = wintypes.BOOL
    native.CloseHandle.argtypes = (wintypes.HANDLE,)
    native.CloseHandle.restype = wintypes.BOOL
    return native


class FixtureProcess:
    def __init__(self, pid):
        # SYNCHRONIZE | PROCESS_TERMINATE: only PIDs published by this fixture.
        self.handle = kernel32().OpenProcess(0x00100001, False, pid)
        assert self.handle, f"Cannot retain fixture process {pid}: {ctypes.get_last_error()}"

    def stopped(self):
        result = kernel32().WaitForSingleObject(self.handle, 0)
        assert result in (0, 258), f"Unexpected process wait result: {result}"
        return result == 0

    def close(self):
        try:
            if not self.stopped():
                assert kernel32().TerminateProcess(self.handle, 99), ctypes.get_last_error()
                assert kernel32().WaitForSingleObject(self.handle, 5000) == 0
        finally:
            kernel32().CloseHandle(self.handle)


@contextmanager
def running_supervisor(tmp_path, body, *, parent_pid=None, seed_result=None, worker_name="worker.ps1",
                       cancel_before_start=False, parameters=""):
    worker = write_script(tmp_path / worker_name, body, parameters)
    control = tmp_path / "control"
    control.mkdir()
    if cancel_before_start:
        (control / "cancel.request").touch()
    if seed_result is not None:
        (worker.parent / "installer_result.txt").write_text(seed_result, encoding="ascii")
    command = [str(powershell()), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
               "-File", str(SUPERVISOR), "-BootstrapPath", str(worker),
               "-ControlDirectory", str(control), "-ParentProcessId", str(parent_pid or os.getpid())]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        yield process, control, worker
    finally:
        if process.poll() is None:
            # Supervisor's kill-on-close job owns all descendants it started.
            process.kill()
        process.communicate(timeout=10)


def finish(process, control, outcome):
    stdout, stderr = process.communicate(timeout=25)
    diagnostic = (stdout + stderr).decode("utf-8", errors="replace")
    assert (process.returncode == 0) == (outcome == "success"), diagnostic
    result = control / "outcome.txt"
    assert result.is_file(), diagnostic
    assert result.read_text(encoding="utf-8-sig").strip() == outcome, diagnostic
    if outcome == "failed":
        error = (control / "error.txt").read_text(encoding="utf-8-sig").strip()
        assert error, diagnostic
        return error
    return ""


SUCCESS = "Set-Content -LiteralPath (Join-Path $PSScriptRoot 'installer_result.txt') -Value 'success' -Encoding ascii\n"


def test_worker_receives_current_progress_directory_and_feedback_cannot_imply_success(tmp_path):
    body = r'''
if (-not [IO.Path]::IsPathRooted($ProgressDirectory)) { throw 'Missing progress directory' }
[IO.File]::WriteAllText((Join-Path $ProgressDirectory 'progress.txt'), '6|Finishing installation...')
exit 17
'''
    with running_supervisor(
        tmp_path / "setup é 日本語", body,
        parameters="[CmdletBinding()]\nparam([string]$ProgressDirectory, [switch]$UseCuda)",
    ) as (process, control, _):
        assert "code 17" in finish(process, control, "failed")
        assert (control / "progress.txt").read_text() == "6|Finishing installation..."


@pytest.mark.parametrize("body,seed_result,expected_error", [
    ("exit 23\n", None, "code 23"),
    ("exit 0\n", None, "without a completion result"),
    ("exit 0\n", "success\n", "without a completion result"),
    (SUCCESS + "exit 17\n", None, "code 17"),
    ("Set-Content (Join-Path $PSScriptRoot 'installer_result.txt') 'unknown'\nexit 0\n",
     None, "did not report successful completion"),
    ("throw 'Synthetic startup failure'\n", None, "code 1"),
])
def test_early_and_conflicting_results_fail_promptly(tmp_path, body, seed_result, expected_error):
    with running_supervisor(tmp_path, body, seed_result=seed_result) as (process, control, _):
        assert expected_error in finish(process, control, "failed")


def test_success_requires_worker_exit_and_preserves_unicode_paths(tmp_path):
    body = SUCCESS + r'''
$deadline = [DateTime]::UtcNow.AddSeconds(15)
while (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'may-exit'))) {
    if ([DateTime]::UtcNow -gt $deadline) { exit 71 }
    Start-Sleep -Milliseconds 50
}
exit 0
'''
    with running_supervisor(tmp_path, body, worker_name="Installed app é 日本語/worker.ps1") as (process, control, worker):
        wait_until(lambda: (worker.parent / "installer_result.txt").exists(), "early success marker")
        assert process.poll() is None, "A success marker must not finish a still-running worker"
        assert not (control / "outcome.txt").exists()
        (worker.parent / "may-exit").touch()
        finish(process, control, "success")


def test_result_write_failure_finishes_with_failure(tmp_path):
    body = r'''
New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot 'installer_result.txt') | Out-Null
Set-Content -LiteralPath (Join-Path $PSScriptRoot 'installer_result.txt') -Value 'success'
'''
    with running_supervisor(tmp_path, body) as (process, control, _):
        assert "code 1" in finish(process, control, "failed")


def test_cancellation_before_start_never_launches_the_worker(tmp_path):
    body = "Set-Content (Join-Path $PSScriptRoot 'worker-started') 'unexpected'\n" + SUCCESS
    with running_supervisor(tmp_path, body, cancel_before_start=True) as (process, control, worker):
        finish(process, control, "cancelled")
        assert not (worker.parent / "worker-started").exists()


def tree_worker(tmp_path, *, successful_exit=False):
    def fixture_script(name, next_script=None):
        body = f"Set-Content -LiteralPath (Join-Path $PSScriptRoot '{name}.pid') -Value $PID -Encoding ascii\n"
        if next_script:
            body += f"$childArguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"' + (Join-Path $PSScriptRoot '{next_script}') + '\"'\n"
            body += "Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -ArgumentList $childArguments -WindowStyle Hidden -PassThru | Out-Null\n"
        return body + "Start-Sleep -Seconds 45\nexit 72\n"

    write_script(tmp_path / "grandchild.ps1", fixture_script("grandchild"))
    write_script(tmp_path / "child.ps1", fixture_script("child", "grandchild.ps1"))
    body = fixture_script("worker", "child.ps1")
    if successful_exit:
        body = body.replace("Start-Sleep -Seconds 45\nexit 72\n", r'''
$deadline = [DateTime]::UtcNow.AddSeconds(20)
while (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'may-exit'))) {
    if ([DateTime]::UtcNow -gt $deadline) { exit 73 }
    Start-Sleep -Milliseconds 50
}
''' + SUCCESS + "exit 0\n")
    return body


@contextmanager
def retain_tree(tmp_path):
    retained = []
    try:
        for name in ("worker", "child", "grandchild"):
            pid_file = tmp_path / f"{name}.pid"

            def read_pid():
                try:
                    return int(pid_file.read_text(encoding="ascii").strip())
                except (FileNotFoundError, ValueError, PermissionError):
                    return None

            retained.append(FixtureProcess(wait_until(read_pid, f"{name} fixture PID")))
        yield retained
    finally:
        for process in reversed(retained):
            process.close()


@contextmanager
def unrelated_process():
    process = subprocess.Popen([str(powershell()), "-NoProfile", "-NonInteractive", "-Command",
                                "Start-Sleep -Seconds 45"], creationflags=subprocess.CREATE_NO_WINDOW,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        yield process
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)


def test_cancel_stops_worker_and_descendants_but_preserves_unrelated_process(tmp_path):
    with unrelated_process() as unrelated:
        with running_supervisor(tmp_path, tree_worker(tmp_path)) as (process, control, _):
            with retain_tree(tmp_path) as descendants:
                (control / "cancel.request").touch()
                finish(process, control, "cancelled")
                assert all(child.stopped() for child in descendants), "Cancellation must wait for the entire job"
                assert unrelated.poll() is None


def test_forced_supervisor_death_stops_its_process_tree(tmp_path):
    with running_supervisor(tmp_path, tree_worker(tmp_path)) as (process, _, _):
        with retain_tree(tmp_path) as descendants:
            process.kill()
            process.communicate(timeout=10)
            wait_until(lambda: all(child.stopped() for child in descendants), "kill-on-close job cleanup", timeout=10)


def test_success_drains_leftover_descendants_before_reporting_completion(tmp_path):
    with running_supervisor(tmp_path, tree_worker(tmp_path, successful_exit=True)) as (process, control, _):
        with retain_tree(tmp_path) as descendants:
            (tmp_path / "may-exit").touch()
            finish(process, control, "success")
            assert all(child.stopped() for child in descendants)


def test_parent_exit_cancels_and_drains_process_tree(tmp_path):
    with unrelated_process() as parent:
        with running_supervisor(tmp_path, tree_worker(tmp_path), parent_pid=parent.pid) as (process, control, _):
            with retain_tree(tmp_path) as descendants:
                parent.kill()
                parent.wait(timeout=10)
                finish(process, control, "cancelled")
                assert all(child.stopped() for child in descendants)
