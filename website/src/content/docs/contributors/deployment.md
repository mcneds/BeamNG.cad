---
title: "Deploy to Cloudflare Pages"
description: "Deploy to Cloudflare Pages — beamng.cad documentation."
sidebar:
  order: 4
---

The site builds to static files in `website/dist/`. It needs no server adapter, database or Pages Functions. The production hostname is `beamng-cad.mcneds.dev`, with Pages project `beamng-cad-docs` and source repository [mcneds/BeamNG.cad](https://github.com/mcneds/BeamNG.cad).

## Build and preview

From `website/`:

```powershell
npm ci
npm run check
npm run build
npm run preview
```

Confirm the landing page, a guide and search work in the production preview. The build checks internal links and publication boundaries.

## Choose your Pages project type

Use a **Git-integrated Pages project** connected to the repository's `main` branch. This lets Cloudflare build the documentation on pushes using the settings below. Keep deployment output out of Git. See [Cloudflare Git integration](https://developers.cloudflare.com/pages/get-started/git-integration/).

Direct Upload remains an option for manual deployment. Cloudflare does not support switching a Direct Upload project to Git integration later, so choose it only if you intend to keep uploading builds yourself. See [Cloudflare Direct Upload](https://developers.cloudflare.com/pages/get-started/direct-upload/).

For Direct Upload, authenticate and create a project once:

```powershell
npx wrangler login
npx wrangler pages project create beamng-cad-docs
```

Choose your actual project name and production branch when prompted.

## Set the origin and deploy

Set your own HTTPS hostname and Pages project name in the terminal:

```powershell
$env:SITE_URL = 'https://beamng-cad.mcneds.dev'
$env:CLOUDFLARE_PAGES_PROJECT = 'beamng-cad-docs'
npm run deploy
```

Alternatively copy `.env.example` to `.env` and replace its examples. The deployment script refuses missing configuration, checks/builds the site, validates generated links and calls Wrangler with the selected project. No credentials belong in source files.

`SITE_URL` is the origin only, with no path, query or fragment. It supplies canonical metadata and the sitemap. Local development works without it. Use the final custom hostname before your production build.

## Attach the custom domain

In Cloudflare, open **Workers & Pages → your Pages project → Custom domains** and add the hostname. Follow that flow before manually adding a CNAME; DNS alone does not register the hostname with Pages.

An apex domain must be a zone in the same Cloudflare account as the Pages project. A subdomain can use the required CNAME to the project's `pages.dev` hostname. Follow [Cloudflare's custom-domain instructions](https://developers.cloudflare.com/pages/configuration/custom-domains/) for the relevant DNS setup.

After activation, verify HTTPS, direct loading of a nested guide, search, images and a missing-page URL.

## GitHub integration

When a repository exists, connect it through Pages with:

| Setting | Value |
| --- | --- |
| Root directory | `website` |
| Build command | `npm ci && npm run check && npm run build` |
| Output directory | `dist` |
| Node version | `24` |
| Environment | `SITE_URL=https://beamng-cad.mcneds.dev` |

Keep the framework lockfile committed. Pages manages deployment in this mode; the build command should not run `npm run deploy`.

The repository ignore rules retain the website's saved datasets and public assets. These are the build inputs; local `docs/evidence/`, CAD exports and recordings are unnecessary. Keep the full repository checkout available when running implementation evidence checks. See [what belongs in Git](/contributors/documentation/#what-belongs-in-git) for the aggregation and export workflow.

## Release checklist

- Production checks and browser tests pass.
- The canonical origin is the intended hostname.
- Only selected public assets are in the output.
- Domain/TLS and nested routes work after deployment.
- Retain the previous deployment for rollback through Cloudflare.
