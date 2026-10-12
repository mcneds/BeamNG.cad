import { readdir, readFile, stat } from 'node:fs/promises';
import { resolve, relative, sep } from 'node:path';
import { load } from 'cheerio';

const root = resolve('dist');
async function walk(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  return (await Promise.all(entries.map(e => e.isDirectory() ? walk(resolve(dir, e.name)) : resolve(dir, e.name)))).flat();
}
const files = await walk(root);
const html = files.filter(f => f.endsWith('.html'));
const pages = new Map();
const errors = [];
for (const file of html) pages.set(file, load(await readFile(file, 'utf8')));
for (const [file, $] of pages) {
  const pagePath = '/' + relative(root, file).split(sep).join('/').replace(/index\.html$/, '');
  for(const el of $('.sl-markdown-content p, .sl-markdown-content table, .sl-markdown-content pre, .sl-markdown-content img, .sl-markdown-content figure').toArray()) {
    if((['img','figure'].includes(el.tagName)||/\d/.test($(el).text()))&&!$(el).closest('[data-doc-evidence]').length) errors.push(`${pagePath}: untagged value or figure (${el.tagName})`);
  }
  for (const el of $('a[href], img[src], script[src], link[href]').toArray()) {
    const raw = $(el).attr('href') ?? $(el).attr('src');
    if (!raw || /^(?:[a-z][a-z\d+.-]*:|\/\/)/i.test(raw)) continue;
    const url = new URL(raw, `https://docs.local${pagePath}`);
    let target = resolve(root, '.' + decodeURIComponent(url.pathname));
    if (target !== root && !target.startsWith(root + sep)) { errors.push(`${pagePath}: path escapes output: ${raw}`); continue; }
    try {
      if ((await stat(target)).isDirectory()) target = resolve(target, 'index.html');
      await stat(target);
    } catch { errors.push(`${pagePath}: missing ${raw}`); continue; }
    if (url.hash && pages.has(target)) {
      const id = decodeURIComponent(url.hash.slice(1));
      if (!pages.get(target)('[id]').toArray().some(e => pages.get(target)(e).attr('id') === id)) errors.push(`${pagePath}: missing anchor ${raw}`);
    }
  }
}
const banned = files.filter(f => /(?:\.log$|\.cs$|\.py$|README-pre-site|docs[\\/]evidence|\.beamng-project\.json$)/i.test(f));
errors.push(...banned.map(f => `Unexpected published artifact: ${relative(root, f)}`));
if (!files.some(f => /pagefind[\\/]pagefind\.js$/.test(f))) errors.push('Missing production search index.');
try {
  const entry = JSON.parse(await readFile(resolve(root, 'pagefind/pagefind-entry.json'), 'utf8'));
  if (!entry.languages?.en?.hash || !entry.languages.en.page_count) errors.push('Search metadata has no indexed English pages.');
} catch { errors.push('Production search metadata is missing, empty or invalid. Rebuild before publishing.'); }
for (const file of files.filter(f => f.includes(`${sep}pagefind${sep}`))) {
  if ((await stat(file)).size === 0) errors.push(`Empty search artifact: ${relative(root, file)}`);
}
if (errors.length) { console.error(errors.join('\n')); process.exit(1); }
console.log(`Checked ${html.length} HTML pages: internal links, anchors, assets, search output, evidence tags and publication boundaries passed.`);
