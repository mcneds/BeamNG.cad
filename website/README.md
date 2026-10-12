# beamng.cad documentation

The maintained handbook uses Astro Starlight. Node.js 22.12+ is required; the initial build uses Node 24. Run commands from this directory.

```powershell
npm ci
npm run dev
```

Open the printed local URL. Edit Markdown in `src/content/docs/`; sidebar groups follow its directories. Use MDX only when framework components are needed. The application and SolidWorks are not required to build the site.

## Validate and preview

```powershell
npm run check
npm run build
npx playwright install chromium
npm test
npm run preview
```

Search works against the production build. `build` validates generated links, anchors, assets and search output. Playwright tests start and stop their own production preview. Build artifacts and browser results are ignored.

## Deploy yourself

Production uses `beamng-cad.mcneds.dev` and Pages project `beamng-cad-docs`, with [mcneds/BeamNG.cad](https://github.com/mcneds/BeamNG.cad) as the source repository. Connect its `main` branch using the Git integration settings below. The commands below describe the alternative manual deployment workflow; create a project only if it does not already exist.

```powershell
npx wrangler login
npx wrangler pages project create beamng-cad-docs
$env:SITE_URL = 'https://beamng-cad.mcneds.dev'
$env:CLOUDFLARE_PAGES_PROJECT = 'beamng-cad-docs'
npm run deploy
```

Alternatively copy `.env.example` to `.env`. The deployment script checks and rebuilds before uploading `dist/`. For a fork, replace the hostname and project name with your own.

Attach your hostname in **Cloudflare → Workers & Pages → your project → Custom domains**, then follow the DNS instructions there. `SITE_URL` controls canonical metadata and the sitemap; it must be an HTTPS origin without a subpath. Local development can omit it.

For Git integration: root `website`, build `npm ci && npm run check && npm run build`, output `dist`, Node 24, and your `SITE_URL` environment value. Do not run the deploy script during a Pages build.

Commit website source, `package-lock.json`, `src/data/` and the selected `public/` assets. These saved aggregates let a fresh checkout build without raw local evidence or CAD tools. Keep `dist/`, dependencies, caches, test output and `.env` ignored. From the project root, `python tools/prepare-github.py` inventories the candidate files, and `--output artifacts/github-preview` copies them into a new directory for a clean build check. The [maintenance guide](src/content/docs/contributors/documentation.md#what-belongs-in-git) lists every aggregate and its refresh path.

Full instructions: [Deployment](src/content/docs/contributors/deployment.md) and [Maintenance](src/content/docs/contributors/documentation.md). Official references: [Cloudflare Direct Upload](https://developers.cloudflare.com/pages/get-started/direct-upload/) and [custom domains](https://developers.cloudflare.com/pages/configuration/custom-domains/).

## Content boundaries

The How it works pages include interactive SVG diagrams and graphs built with ordinary Astro scripts and browser custom elements. They need no UI framework or `client:` directive. Astro's development toolbar is disabled in `astro.config.mjs`; its “No islands detected” inspector message only means there are no hydrated framework components.

See `src/components/explainers/` for the visuals. The frame explorer uses Three.js WebGPU/TSL with WebGL2 fallback, on-demand rendering, and nine actual CGAL parameter sweeps from the exported Mochi frame. It follows the proxy, grid boundary, projection, weld, structural graph and bracing. Calibration and mate diagrams use fingerprinted solver outputs. New UI screenshots are deferred until the generator MVP and interface settle.

Numeric claims, settings and figures carry `data-doc-evidence` tags. `npm run docs:check` detects source changes using `src/data/doc-evidence.json`; the maintenance guide lists refresh commands and review responsibilities. Keep historical measurements dated. Record reviewed changes with `npm run docs:review -- --group=<group>` after updating the affected content.

The historical verification chart uses selected fields in `src/data/checkpoint.json`. From the full project checkout, refresh them with `node scripts/extract-explainer-evidence.mjs`; review the dated caption and source hashes together. The normal build needs only the committed extract, never raw recordings.

This site is the maintained handbook. The original README and migrated guides are retained under `../docs/archive/`. Only selected illustrations, one example fragment and four milestone summaries are public. Full local evidence, logs, CAD files and working project data stay outside the build.

The website links to the GitHub repository and offers page editing against `main`. Preserve `package-lock.json` and rerun checks after framework upgrades.

The `postcss-nested` override to 7.0.2 allows the patched selector parser (7.1.6) to replace the older transitive dependency used by Expressive Code. The production build and browser checks cover this combination. Reassess/remove the override when upstream dependencies include the fix.
