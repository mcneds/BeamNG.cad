# Working in BeamNG.cad

## Project map

- `beamng.cad/`: SolidWorks COM add-in, targeting .NET Framework 4.7.2 and C# 8. `Preparation/` owns CAD intake and saved project contracts; `UI/` owns the native workflow.
- `beamng.cad/FramePipeline/`: Python preparation, calibrated generation, joints, packaging and verification integration. Active geometry scripts live in `generation/`.
- `dependencies/cad-calibration/`: required vendored calibration and vehicle-wizard source. The add-in copies these packages into its output; do not remove or ignore this directory wholesale.
- `tests/` and `tools/`: regression fixtures, native checks and documentation exporters.
- `website/`: maintained Astro Starlight handbook. Read [website/README.md](website/README.md) and the [maintenance guide](website/src/content/docs/contributors/documentation.md) before changing its tooling or evidence.
- `docs/`, `artifacts/` and application `bin/` directories contain local archives, working data and experiment evidence. They are not authoritative maintained instructions or normal publishable inputs.

## Implementation boundaries

- Preserve the distinction between CAD ownership, physical graphs and appearance meshes. Do not infer missing hardpoints or physical properties from display geometry without an explicit supported contract.
- Frame generation uses the calibrated pipeline. The uncalibrated prepared-frame builder, old material tuner/flexbody associator, obsolete tuning-study command and draft interchange tooling were removed. Do not restore them as fallback paths.
- `FramePipeline/build_static_frame.py` remains for completed-package validation, customization and installation; its filename does not imply an available generation route.
- Reviewed template JSON import remains supported alongside native mate authoring. Persisted values such as joint-workspace mode `legacy`, settings migration and old receipt compatibility are separate from the retired generator. Do not delete them merely because of their names.
- Preserve source CAD, saved projects, installed vehicles and existing evidence during verification. Use isolated output directories and fixture profiles. Keep live native checks distinct from offline tests.

## Documentation and visual explanations

- Keep Astro Starlight and its standard content structure. Prefer Markdown for prose, MDX for embedded components, and small customizations that remain straightforward to maintain.
- Explain concrete inputs, transformations, outputs and limitations. Avoid filler and elaborate interactions for simple facts such as coordinate conversion.
- Prioritize useful visuals of alpha wrapping, graph construction, calibration and mate compilation. Use actual assembly geometry and solver/compiler outputs when available. Label schematics, illustrative calculations and hypothetical edits explicitly.
- The frame explorer uses Three.js `WebGPURenderer` and TSL with WebGL2 fallback. Its controls select saved CGAL results; CGAL does not run in the browser. Do not imply arbitrary live recomputation or interpolate fabricated solver output.
- Keep rendering on demand, dispose graphics resources, retain a useful static fallback, and support keyboard controls and small screens. Test WebGPU and WebGL separately when available; report unavailable backend coverage honestly.
- Astro scripts and custom elements do not require framework islands or `client:` directives. The disabled development toolbar's “No islands detected” notice was not an application failure.
- New application UI screenshots and UI redesign are deferred until the generator MVP and interface stabilize, unless the user changes that direction.

## Values, plots and source provenance

- Keep implementation-sensitive values, settings, screenshots and figures within a `data-doc-evidence` scope. Numeric Markdown blocks are tagged automatically; rendered content inherits a page scope. Give a figure its own source group when it differs from the page.
- `website/scripts/doc-evidence.mjs` defines source groups; `website/src/data/doc-evidence.json` records reviewed hashes. When changing an algorithm, default, limit or input contract, review the affected documentation and datasets too.
- From `website/`, run `npm run docs:check` to identify changed sources. After reviewing and updating the affected content, use `npm run docs:review -- --group=<group>`. Never refresh hashes merely to silence a warning.
- Preserve dates and hashes of historical measurements. A solver optimization does not turn an old recording into a new qualification result. Distinguish generation success, completed recording, numerical acceptance and physical qualification.
- Regeneration tools are `tools/generate-docs-wrap.py`, `tools/generate-docs-graph.py` and `tools/generate-docs-evidence.py`; exact commands and required inputs are in the maintenance guide. Use fresh atlas work directories when inputs or implementation change.
- Keep reviewed `website/src/data/` extracts and selected `website/public/` assets in Git. Refresh both the source JSON and its public download copy when applicable. Normal website builds must not require local CAD files, raw recordings, Blender or CGAL.
- Do not publish native project files, persistent CAD references, machine paths, credentials or full experiment logs. Preserve the separate software and asset licensing boundaries documented in the root README and notices.

## Build and verification

For routine add-in compilation, disable COM registration:

```powershell
dotnet build beamng.cad.slnx -c Debug -p:XCadRegDll=false
```

Use a separate `OutputPath` when needed. Always keep `XCadRegDll=false` on verification builds, including isolated builds: otherwise the build can register its temporary DLL. Follow the installation guide for an intentional registration task.

For website changes, run the applicable checks from `website/`:

```powershell
npm run check
npm run docs:check
npm run build
npm test
```

- Use `npm ci` for a fresh checkout; preserve `package-lock.json`. On PowerShell, `npm.cmd` can be used if the script shim is blocked. Runtime requirements are in `website/package.json`.
- The production build checks links, anchors, assets, search output, evidence tags and publication boundaries. Search requires a production build.
- Playwright starts its own preview; see `website/playwright.config.ts` for the port and projects. Install Chromium once with `npx playwright install chromium`. Do not stop an unrelated user preview to run tests.
- Run focused Python/native checks for changed behavior. [Application testing](website/src/content/docs/contributors/testing.md) documents the broader `tools/Test-All.ps1` workflow and external fixture requirements. Do not present historical passing counts as current verification.
- Documentation-only edits to these instructions need a content/path review, not a full native or browser suite.

## Publishing and repository hygiene

- Follow `.gitignore` and `.gitattributes`. Keep generated builds, caches, local configuration and raw evidence out of commits; preserve bytes of fingerprinted source inputs.
- Cloudflare Pages settings and the documented domain/project live in the [deployment guide](website/src/content/docs/contributors/deployment.md). A local documentation change does not itself request a deployment or DNS change.
- Prefer the existing project's build/deploy workflow. Do not create another Pages project or change hosting arrangements as a side effect of editing documentation.
