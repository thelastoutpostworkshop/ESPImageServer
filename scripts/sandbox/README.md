# Windows installer tests in Sandbox

Enable Windows Sandbox and restart Windows first. Use a freshly requested
installer build that contains the changes being tested. This launcher does not
build an installer or run one on the host.

From the repository root, replace the example version with the actual artifact:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\sandbox\start-test.ps1 `
  -InstallerPath .\dist\ESPImageServer-Setup-1.1.10.exe
```

Add `-PrepareOnly` to prepare the inputs and configuration without launching
Sandbox. The command prints the unique run directory under the Git-ignored
`dist/sandbox-tests` directory. It verifies the copied EXE's SHA-256 hash and
records its filename, version, hash, run ID, and checkout commit in
`input/manifest.json`. The hash identifies the exact tested artifact; the
checkout commit alone does not establish whether a build included uncommitted
changes. Each run gets a snapshot of the current guest runner.

The generated `.wsb` maps only:

| Host directory | Guest directory | Access |
| --- | --- | --- |
| This run's `input` | `C:\ESPInstallerTestInput` | Read-only |
| This run's `results` | `C:\ESPInstallerTestResults` | Read/write |

Networking and virtual graphics are enabled, with 8 GB RAM. Clipboard,
microphone, camera, and printer sharing are disabled. Do not add mappings for
your host profile, installed application, model cache, or image library. The
guest runner refuses to execute outside the Sandbox `WDAGUtilityAccount` and
uses the guest account's application directory. It never installs into a mapped
folder. See Microsoft's [Sandbox configuration reference](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file).

## Send test commands

Wait for `results/status.json` to report `state: "ready"`. A launcher process ID
does not mean that the guest is ready. Inspect `environment.json` for the guest
OS, Python/WinGet availability, Visual C++ runtime, and graphics adapters.

Create commands atomically in this run's `results/commands` directory. Use a
new ID for every command, including retries. This example starts interactive
setup; replace the run directory with the exact path printed by the launcher:

```powershell
$runDirectory = 'C:\path\to\ESPImageServer\dist\sandbox-tests\<printed-run-id>'
$manifest = Get-Content -LiteralPath (Join-Path $runDirectory 'input\manifest.json') -Raw | ConvertFrom-Json
$results = Join-Path $runDirectory 'results'
$id = '001-install'
$commandPath = Join-Path $results ('commands\' + $id + '.json')
if (Test-Path -LiteralPath $commandPath) { throw 'Choose a new command ID.' }
$command = @{ id = $id; run_id = $manifest.run_id; action = 'install-interactive' }
$pendingPath = $commandPath + '.pending'
[IO.File]::WriteAllText($pendingPath, ($command | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $pendingPath -Destination $commandPath
```

Supported actions use the same three fields:

| Action | Purpose |
| --- | --- |
| `install-interactive` | Run the actual installer and inspect its wizard in Sandbox. |
| `install-silent` | Run setup with Inno logging and no automatic restart. |
| `install-silent-with-hostile-python-env` | Give only the installer child deliberately invalid `PYTHONHOME`/`PYTHONPATH`; verify private Python isolation. |
| `cancel-bootstrap` | Request cancellation through the active bootstrap supervisor's control directory. |
| `uninstall-interactive` | Run the guest uninstaller with its normal cleanup behavior. |
| `collect` | Capture logs and an installation snapshot, including while setup runs. |
| `finish` | Collect a final snapshot and stop the runner when no installer is active; leave Sandbox open. |

`cancel-bootstrap` requires the dependency bootstrap to have started. If it is
too early, wait and retry with a new ID. It tests the cancellation protocol;
clicking the wizard's Cancel button or window-close control remains a separate
interactive check. Cancellation of the Microsoft runtime prerequisite is not
forced while its system installation transaction is running.

Read `results/command-results/<id>.json` and `results/status.json` to follow
progress. A command status of `completed` means the process exited, not that
installation passed. Classify the installer exit code and inspect its logs:

| Exit code | Expected interpretation |
| --- | --- |
| `0` | Setup reported successful completion. Validate launch and resulting files. |
| `1` | Dependency bootstrap failed; confirm a useful error and no app-launch option. |
| `2` | Installation/bootstrap was cancelled. Confirm worker cleanup. |
| `7` | A prerequisite prevented installation. |
| `8` | A prerequisite requires a restart before installation can proceed. |

For a cancellation request, also wait for the original install command to
complete and verify its exit code and process snapshot. A successful cancellation
command by itself only establishes that the request was sent.

## Acceptance and evidence

Start with fresh-account installation, cancellation during dependency setup,
and retry. Inspect interactive failure/Finished pages and their launch controls.
Check per-user registration and shortcuts. Use guest-only marker files to check
preservation during repair and custom-library preservation during uninstall.
Use interactive uninstall: the current silent-uninstall path intentionally
skips the application's cleanup helper and cannot establish runtime/cache cleanup.

Sandbox graphics support does not establish CUDA availability. When CUDA is
unavailable, the unmodified production installer should fail clearly at the GPU
check, return a nonzero exit code, and avoid activating an incomplete runtime.
Do not bypass the GPU check and describe the result as production installation
acceptance. Successful generation and any GPU-dependent installation success
require a suitable NVIDIA test environment. Downloads can be large; retrying
inside the same Sandbox can reuse its download cache.

The results folder retains `guest-startup.log` (including failures before the
runner transcript starts), the runner transcript, Inno logs, command outcomes,
and numbered snapshots containing bootstrap/prerequisite logs, runtime-folder
inventory, registration, shortcuts, and process summaries. Collect UI screenshots
separately when checking interactive behavior. Do not execute files produced by
the guest on the host. Send `collect` or `finish` and confirm the evidence was
written before closing Sandbox; closing it discards guest-only files. Review and
remove only the dedicated run directory when its results are no longer needed.
