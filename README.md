# beamng.cad

SolidWorks COM add-in for turning selected CAD groups into BeamNG structures and vehicle packages. CAD ownership, physical graphs and appearance meshes are kept separate.

## License

Copyright (C) 2026 mcneds and BeamNG.cad contributors.

Original BeamNG.cad software is licensed under **GPL-3.0-or-later**, with the [BeamNG.cad host-linking exception](LICENSE-EXCEPTION.txt) for SOLIDWORKS and BeamNG.drive. You may redistribute and modify the software under GNU GPL version 3 or, at your option, any later version. See the complete [GNU GPLv3 text](LICENSE) and [third-party notices](THIRD-PARTY-NOTICES.md). The software is provided without warranty as described in the GPL.

This grant covers the original software implementation, including C#, Python, Lua and PowerShell source, documentation-site code, software configuration, build tooling and project-authored calibration/wizard code. Existing third-party licenses remain authoritative; the host exception applies only to original BeamNG.cad code.

**Software only:** CAD models, meshes, vehicle/calibration datasets, screenshots, renders, other non-software assets and documentation prose are excluded from this grant unless separately licensed by their rights holder. The Mochi team retains its separate rights to the model and derived materials. Their inclusion in this repository or documentation does not grant additional reuse permissions.

Generated vehicle geometry does not automatically become GPL because this software produced it. Copied project software included in a generated package, such as Lua runtime controllers, remains GPL with the applicable host exception; retain those notices and comply with the software license when redistributing it.

## Documentation

Read the handbook at **[beamng-cad.mcneds.dev](https://beamng-cad.mcneds.dev)**. Source: [mcneds/BeamNG.cad](https://github.com/mcneds/BeamNG.cad).

The maintained handbook is an **Astro Starlight** site in [website/](website/README.md). It covers installation, CAD preparation, frame calibration, component and joint authoring, appearance, packaging, native verification, internals and troubleshooting.

```powershell
cd website
npm ci
npm run dev
```

Open the printed local address. For production search, run `npm run build` then `npm run preview`.

- [Start here](website/src/content/docs/start/overview.md)
- [Install the add-in](website/src/content/docs/start/install.md)
- [Your first CAD vehicle](website/src/content/docs/start/first-vehicle.md)
- [How the pipeline works](website/src/content/docs/concepts/pipeline.mdx)
- [Capabilities and qualification limits](website/src/content/docs/start/capabilities.md)
- [Deploy to your Cloudflare domain](website/src/content/docs/contributors/deployment.md)

The site is ready for Cloudflare Pages deployment. Only four selected milestone summaries are public. The original documentation archive in `docs/archive/` and full experiment evidence remain local and are excluded from Git.

## Preparing a GitHub checkout

The root `.gitignore` excludes compiled output, IDE state, Python/Node caches, local configuration, logs, `artifacts/`, the old `docs/` tree and per-run JSON files in `tools/`. It keeps application source, tests, examples, vendored calibration source and required calibration fixtures. Do not ignore `dependencies/` wholesale: the add-in copies its Python packages during the build.

Preview the exact candidate files without initializing or changing this workspace's Git repository:

```powershell
python tools/prepare-github.py
python tools/prepare-github.py --output artifacts/github-preview
```

The first command writes paths, sizes and SHA-256 hashes to ignored `artifacts/github-manifest.json`. The second copies those files into a new directory and refuses to overwrite an existing export. It does not commit or upload anything. This is an inventory of the repository ignore rules; once a repository exists, remember that `.gitignore` does not remove files already tracked by Git.

Documentation builds need the complete `website/` source, including `package-lock.json`, `src/data/`, `public/`, scripts and configuration. The reviewed extracts are intentional source inputs even though they were generated offline. Keep them in Git; rebuild `website/dist/` with `npm ci`, `npm run check` and `npm run build` from `website/`. See the [website maintenance guide](website/src/content/docs/contributors/documentation.md) for the evidence aggregation boundary and refresh commands.

`.gitattributes` preserves file bytes across platforms because calibration receipts and documentation provenance use byte-based hashes. No Git LFS setup is needed for the current candidate files. Native SolidWorks/BeamNG integration tests still require their external applications and local fixtures; a clean checkout does not include those working environments.

## Build the add-in

From the project root:

```powershell
dotnet build beamng.cad.slnx -c Debug -p:XCadRegDll=false
```

The application targets .NET Framework 4.7.2, C# 8 and xCAD 0.8.0. First registration requires an administrator build without `XCadRegDll=false`; see the installation guide. Keep dependencies and the copied `FramePipeline` directory beside the DLL and restart SolidWorks after replacing it.

## Validation

```powershell
powershell -NoProfile -STA -ExecutionPolicy Bypass -File tools/Test-All.ps1
```

See [application testing](website/src/content/docs/contributors/testing.md) for native fixture requirements. A build, completed recording and physical qualification are different outcomes; current development vehicles and provisional models must be assessed against their exact receipts.

Local diagnostic evidence: `docs/evidence/steady-speed-summary-20261012.md` (12 October 2026; not included in Git). These tests preserve the installed vehicle and distinguish expected bump/roll steer from simulation error.

Local follow-up: `docs/evidence/dynamics-followup-20261012.md`, including unresolved physical inputs and the excluded resource-aborted capture.
