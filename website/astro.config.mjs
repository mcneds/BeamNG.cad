import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import { existsSync } from 'node:fs';
import evidenceTags from './scripts/remark-doc-evidence.mjs';
import { unified } from '@astrojs/markdown-remark';

if (existsSync('.env')) process.loadEnvFile('.env');

const siteUrl = process.env.SITE_URL;
if (siteUrl) {
  const url = new URL(siteUrl);
  if (url.protocol !== 'https:' || url.pathname !== '/' || url.search || url.hash || url.username || url.password) {
    throw new Error('SITE_URL must be an HTTPS origin, e.g. https://docs.example.com');
  }
}

export default defineConfig({
  site: siteUrl,
  output: 'static',
  // The island inspector is developer tooling, not part of the documentation UI.
  devToolbar: { enabled: false },
  trailingSlash: 'always',
  markdown: { processor: unified({ remarkPlugins: [evidenceTags] }) },
  integrations: [
    starlight({
      title: 'beamng.cad',
      description: 'From SolidWorks assemblies to reviewed BeamNG structures. User guides, architecture, and technical reference.',
      favicon: '/favicon.svg',
      social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/mcneds/BeamNG.cad' }],
      editLink: { baseUrl: 'https://github.com/mcneds/BeamNG.cad/edit/main/website/' },
      customCss: ['./src/styles/custom.css'],
      components: { PageTitle: './src/components/ReviewedPageTitle.astro', MarkdownContent: './src/components/ReviewedMarkdownContent.astro' },
      sidebar: [
        { label: 'Start here', items: [{ autogenerate: { directory: 'start' } }] },
        { label: 'User guides', items: [{ autogenerate: { directory: 'guides' } }] },
        { label: 'How it works', items: [{ autogenerate: { directory: 'concepts' } }] },
        { label: 'Reference', items: [{ autogenerate: { directory: 'reference' } }] },
        { label: 'Contributors', items: [{ autogenerate: { directory: 'contributors' } }] },
        { label: 'Selected milestones', collapsed: true, items: [{ autogenerate: { directory: 'milestones' } }] },
      ],
    }),
  ],
});
