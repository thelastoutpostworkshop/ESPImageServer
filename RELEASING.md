# Prepare a release

The **Prepare draft release** GitHub Actions workflow builds one installer for
Windows x64 and Ubuntu 24.04 x64. macOS release delivery is deferred; its existing
platform checks and development artifacts remain in CI. The workflow creates an
unpublished GitHub release only after all reused platform checks and the Linux
dependency setup checks pass. Normal pushes still run **Platform checks** and
do not create a release or build the full Windows installer.

1. Set the intended version in `pyproject.toml` to an unused `major.minor.patch`.
   Commit and push the version change and workflow changes. Build scripts
   synchronize derived metadata.
2. Tag that commit as `v<version>` and push the tag. For example, if the committed
   project version is `1.2.3`:

   ```powershell
   git tag -a v1.2.3 -m "ESPImageServer 1.2.3"
   git push origin v1.2.3
   ```

   This automatically starts **Prepare draft release**. A tag that does not
   match the project version fails before the installers are built. Branch
   pushes continue running normal Platform checks; tag pushes use those checks
   through the release workflow without starting a duplicate standalone run.
3. When it passes, open **Releases** and review the unpublished draft named
   **ESPImageServer <version>**. Add the user-facing changes to its notes.
4. Publish using GitHub's release editor when you choose to make it public.
   Pushing the tag creates a draft; it does not automatically publish it.

The draft contains two installers and two adjacent `.sha256` files. The
collector requires exactly that set, checks the version in every filename, and
recomputes each checksum before uploading. All builds use the workflow's commit;
the draft targets that same commit. The remote tag must still point to the tested commit (annotated and lightweight
tags are supported). Existing releases with that version are rejected without
replacing their files. If a run fails before creating a draft, rerun the failed
GitHub Actions run. For a partially uploaded draft, delete only the unpublished
draft, retain the tag, and rerun all jobs to regenerate the complete artifact set.
Do not delete or move a published tag or release to retry this workflow.

Windows uses the real Inno Setup installer and downloads dependencies during
setup. Linux downloads generation dependencies on first launch. Both require a
supported NVIDIA GPU for generation. These installers are unsigned; the
generated draft notes state this limitation. macOS is not included in this release.

CI checks package lifecycle and dependency imports without physical GPU
generation. Windows upgrade preservation uses fixture payloads, while its release
installer is compiled separately from the production files. Creating the draft
does not establish Windows installation or real GPU generation coverage.

Only the final draft job receives repository contents write permission. Build
jobs keep read permission. No signing credentials are required for this unsigned
draft workflow. GitHub documents [tag push triggers](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#push)
and the CLI's [draft release creation](https://cli.github.com/manual/gh_release_create).
