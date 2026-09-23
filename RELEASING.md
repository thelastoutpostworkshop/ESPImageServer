# Prepare a release

The **Prepare draft release** GitHub Actions workflow builds one installer for
Windows x64, Ubuntu 24.04 x64, and macOS 15+ Apple Silicon. It creates an
unpublished GitHub release only after all reused platform checks and the Linux
dependency setup checks pass. Normal pushes still run **Platform checks** and
do not create a release or build the full Windows installer.

1. Set the intended version in `pyproject.toml` to an unused `major.minor.patch`.
   Commit and push the changes. Build scripts synchronize derived metadata.
2. In GitHub, select **Actions > Prepare draft release > Run workflow** and
   choose the branch containing the intended release commit. The workflow must
   be on the default branch before GitHub exposes the manual Run workflow button.
3. When it passes, open **Releases** and review the draft named
   **ESPImageServer <version>**. Add the user-facing changes to its notes.
4. Publish using GitHub's release editor when you choose to make it public.
   The workflow never publishes automatically.

The draft contains three installers and three adjacent `.sha256` files. The
collector requires exactly that set, checks the version in every filename, and
recomputes each checksum before uploading. All builds use the workflow's commit;
the draft targets that same commit. Existing tags or releases with that version
are rejected without replacing their files. To retry a partially uploaded draft,
delete the unpublished draft first (and any associated tag), or choose a new
version. Do not delete an already published release to retry this workflow.

Windows uses the real Inno Setup installer and downloads dependencies during
setup. Linux downloads generation dependencies on first launch. Both require a
supported NVIDIA GPU for generation. macOS currently supports display management
only. These installers are unsigned, and macOS notarization remains unfinished;
the generated draft notes state these limitations.

CI checks package lifecycle and dependency imports without physical GPU
generation. Windows upgrade preservation uses fixture payloads, while its release
installer is compiled separately from the production files. Creating the draft
does not establish Windows installation or real GPU generation coverage.

Only the final draft job receives repository contents write permission. Build
jobs keep read permission. No signing credentials are required for this unsigned
draft workflow. GitHub documents [manual workflows](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)
and the CLI's [draft release creation](https://cli.github.com/manual/gh_release_create).
