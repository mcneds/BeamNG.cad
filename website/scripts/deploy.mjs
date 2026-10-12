import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

if (existsSync('.env')) process.loadEnvFile('.env');
const origin = process.env.SITE_URL;
const project = process.env.CLOUDFLARE_PAGES_PROJECT;
if (!origin || !project || !/^[a-z0-9][a-z0-9-]*$/.test(project)) {
  console.error('Set SITE_URL and CLOUDFLARE_PAGES_PROJECT in .env or your environment before deployment. See README.md.');
  process.exit(1);
}
function run(script, args = []) {
  const result = spawnSync(process.execPath, [script, ...args], { stdio: 'inherit', env: process.env });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}
function bin(pkg, key) {
  const dir = resolve('node_modules', pkg);
  const metadata = JSON.parse(readFileSync(resolve(dir, 'package.json'), 'utf8'));
  return resolve(dir, typeof metadata.bin === 'string' ? metadata.bin : metadata.bin[key]);
}
run(bin('astro', 'astro'), ['check']);
run(bin('astro', 'astro'), ['build']);
run(resolve('scripts/check-links.mjs'));
run(bin('wrangler', 'wrangler'), ['pages', 'deploy', 'dist', '--project-name', project]);
