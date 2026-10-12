---
title: "Maintain this website"
description: "Maintain this website — beamng.cad documentation."
sidebar:
  order: 3
---

The handbook uses standard [Astro Starlight](https://starlight.astro.build/) content and components. Keep customization small so framework updates remain straightforward.

## Local setup

Install Node.js 22.12+ (Node 24 is used for the initial build), then from `website/`:

```powershell
npm ci
npm run dev
```

Open the printed local address. The application and native CAD tools are not required. Built-in search indexes the production build, so test search with `npm run build` followed by `npm run preview`.

## Add or edit a page

Pages live in `src/content/docs/`. Prefer Markdown, using MDX only for framework components such as the landing-page cards.

```yaml
---
title: A useful task name
description: What this page helps the reader accomplish.
sidebar:
  order: 4
---
```

The directory selects a navigation group. Give guides prerequisites, steps, expected outputs and recovery guidance. Use root-relative site links with a trailing slash. Put essential context in text as well as screenshots, and add meaningful alt text.

Use source/UI terminology. Distinguish supported behaviour, experimental settings and dated results. Replace developer-machine paths with clearly labelled examples. Never present synthetic hardpoints or provisional material values as a user's hardware specification.

## Assets and history

### Interactive explanations

Concept pages use MDX to embed the Astro components in `src/components/explainers/`. These use browser scripts and custom elements, so they do not need React or a `client:` directive. The development toolbar is disabled; its “No islands detected” message is an inspector notice, not a missing-script error.

Keep diagrams readable without JavaScript. Use labelled buttons and sliders, keyboard focus, text readouts, and theme-aware colours. The frame explorer uses Three.js WebGPURenderer, TSL node materials and its WebGL2 fallback. It loads on request and renders on changes, with no continuous animation loop. CGAL results are computed offline, not approximated by the renderer.

The dated verification graph uses `src/data/checkpoint.json`, a selected extract with source hashes. Run `node scripts/extract-explainer-evidence.mjs` from `website/` in the full project checkout to regenerate it. Review the chart's dates, limits and captions alongside any data change. Builds use the checked-in extract and do not publish raw evidence.

Add new UI screenshots after the generator MVP and interface stabilize. Existing screenshots remain dated references; animations and output graphs can explain the stable concepts in the meantime.

Only selected public assets belong in `public/assets/`. Keep raw logs, full evidence collections, source CAD and working project files outside the site. A milestone should explain a major result and its limits; do not replicate the experiment journal.

The original README and migrated source documents are preserved in the local `docs/archive/` directory. Historical documents there are not published.

### What belongs in Git

Commit the whole website source, its lockfile and reviewed public datasets. Ignore `node_modules/`, `dist/`, `.astro/`, `.wrangler/`, browser test results and local `.env` files. The repository also excludes the original `docs/` tree and `artifacts/`; those are not required for a documentation build.

| Published input to keep in Git | How it is aggregated or refreshed locally |
| --- | --- |
| `src/content/docs/`, including selected milestones | Write reviewed explanations and dated conclusions from local evidence. |
| `src/data/checkpoint.json` | `node scripts/extract-explainer-evidence.mjs` selects two historical cases from the local checkpoint report and records source hashes. |
| `src/data/frame-tuning.json` and `mate-compilation.json` | `tools/generate-docs-evidence.py` extracts selected calibration responses and mate constraints. |
| `public/assets/wrapping/`, including manifests, graph data, previews and public evidence copies | The wrap/graph exporters below compute the selected visualizations offline; retain all files referenced by the manifest. |
| Other selected `public/` assets and downloads | Keep reviewed images and examples used by the pages. |
| `src/data/doc-evidence.json` | Records which implementation snapshot was reviewed; update only after reviewing affected documentation. |

Normal builds consume these saved inputs. They do not regenerate the datasets or require SolidWorks, BeamNG, Blender, CGAL or raw experiment recordings. Regeneration requires the relevant local source data and tools; source hashes are provenance, not downloadable copies of excluded recordings.

For a full GitHub checkout, retain `beamng.cad/`, vendored `dependencies/cad-calibration/` source and the documentation exporter scripts in `tools/`: the evidence checker fingerprints them. A website-only checkout can also build using the saved snapshots, but cannot run the full implementation review check. Preserve both the JSON datasets under `src/data/` and their public copies under `public/assets/wrapping/` when refreshing them.

From the project root, `python tools/prepare-github.py --output artifacts/github-preview` creates a clean candidate checkout using the repository ignore rules. Run the normal website check/build commands from its `website/` directory to verify that no ignored local files are needed. Choose a fresh output directory for each export.

## Changing implementation details

Every page identifies its reviewed implementation snapshot. Numeric prose, tables, code settings, screenshots and plots carry a `data-doc-evidence` tag linked to a source group below. This marks values that need review when implementation or optimization changes. Mathematical identities and historical measurements keep their stated meaning; a changed solver does not rewrite an old recording.

Numeric Markdown blocks and images receive explicit tags; a page-level scope covers generated code blocks and other rendered content. Figures can override that scope with their own source group. The build rejects untagged numeric blocks and figures. In browser tools, find the nearest `data-doc-evidence` ancestor to identify the applicable sources.

`src/data/doc-evidence.json` records reviewed source hashes. `npm run docs:check` fails when they differ. `npm run build` prints the affected groups while building the last reviewed documentation. After checking the relevant prose and data, record a new review with `npm run docs:review -- --group=frame-generation` (substitute the affected group). Do not refresh hashes merely to silence the check.

### Frame generation

Group: `frame-generation`. Review `FramePipeline/generation/AlphaWrap.py`, `JBeamShellGenerator.py`, preparation and local bracing. The frame explorer publishes nine exact alpha/offset runs of one saved CAD export. Reproduce them from the project root:

```powershell
python tools/generate-docs-wrap.py --frame '<prepared frame.stl>' --blender '<blender.exe>' --cgal '<CGAL python.exe>' --work '<new empty atlas directory>' --source-label '<assembly and frame revision>'
& '<calibration python.exe>' tools/generate-docs-graph.py --work '<same atlas directory>'
```

Use a new work directory when source geometry, parameters or code changes. Review every preset; the manifest records input and implementation hashes. The public dataset contains only selected mesh geometry, never assembly paths, persistent references or raw recordings.

### Frame calibration

Group: `frame-calibration`. Review fitting policy, iteration budgets, modal limits and response tolerances. `tools/generate-docs-evidence.py --calibration '<case directory>' --project '<saved project JSON>'` extracts calibration and mate examples and refreshes the SVG fallback. It independently solves the saved graph and checks the result against the retained calibration report. Copy `src/data/frame-tuning.json` to `public/assets/wrapping/tuning-evidence.json` after review.

### Mate compilation

Group: `mate-compilation`. Review native geometry, combined constraints, supported joints and hardpoint ownership. The evidence exporter records the actual compiler's matrix and nullspace. Its locked-rotation alternatives are explicitly hypothetical. Copy `src/data/mate-compilation.json` to `public/assets/wrapping/mate-evidence.json` after review.

### Vehicle generation

Group: `vehicle-generation`. Review component defaults, support mass policies, coilover equations and drivetrain contracts. The spring calculator is an illustrative equation, while plotted native outputs are dated evidence. Update each according to its own source.

### Verification

Group: `verification`. Review scenarios, repeat counts, measured limits and telemetry contracts. Historical plots retain their original dates and hashes. New qualification claims require new recordings; code changes alone do not update the evidence.

### Application

Group: `application`. Review UI names, input validation, supported workflows and instruction screenshots when the C# application changes. Reviewed template JSON import remains supported alongside authored CAD joints. The uncalibrated prepared-frame builder and draft interchange have been removed.

### Website

Group: `website`. Review dependency versions, build and deployment commands. Run the type check, link checks and browser tests after a change. WebGPU rendering should be tested separately from its WebGL2 fallback and unavailable-graphics state.

## Run checks

```powershell
npm run check
npm run docs:check
npm run build
npx playwright install chromium
npm test
```

The build checks internal links, anchors, assets and search output. Browser tests cover the built site, navigation, themes, code copying, search and mobile overflow. Browser installation is needed once per Playwright version.

## Update dependencies

Use the framework's documented upgrade process, inspect the diff, and rerun the checks above. Keep `package-lock.json` with `package.json`; use `npm ci` for reproducible installs. Review dependency overrides before carrying them into a new release.

Edit/source links point to [mcneds/BeamNG.cad](https://github.com/mcneds/BeamNG.cad). Configure the deployment origin through `SITE_URL`, not hardcoded page links; production uses `https://beamng-cad.mcneds.dev`.
