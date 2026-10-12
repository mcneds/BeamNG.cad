import { test, expect, chromium } from '@playwright/test';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import manifest from '../public/assets/wrapping/manifest.json' with { type: 'json' };
import mate from '../src/data/mate-compilation.json' with { type: 'json' };
import tuning from '../src/data/frame-tuning.json' with { type: 'json' };

test('published data is traceable and all graph endpoints exist', () => {
  for (const item of manifest.cases) {
    const bytes = readFileSync(new URL(`../public/assets/wrapping/${item.id}.json`, import.meta.url));
    expect(createHash('sha256').update(bytes).digest('hex')).toBe(item.sha256);
    const data = JSON.parse(bytes.toString());
    expect(data.graph.positions).toHaveLength(item.graphNodes);
    expect(data.graph.edges.length + data.graph.addedEdges.length).toBe(item.graphBeams);
    expect([...data.graph.edges, ...data.graph.addedEdges].filter(edge => edge.length !== 2 || edge[0] === edge[1] || !edge.every((i: number) => Number.isInteger(i) && i >= 0 && i < item.graphNodes))).toEqual([]);
  }
  expect(JSON.parse(readFileSync(new URL('../public/assets/wrapping/mate-evidence.json', import.meta.url), 'utf8'))).toEqual(mate);
  expect(JSON.parse(readFileSync(new URL('../public/assets/wrapping/tuning-evidence.json', import.meta.url), 'utf8'))).toEqual(tuning);
});

test('frame viewer renders actual preset changes and every generation stage', async ({ page }, testInfo) => {
  test.setTimeout(90000);
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('/concepts/wrapping/');
  const demo = page.locator('cad-wrap-explorer');
  await demo.getByRole('button', { name: 'Load interactive frame' }).click();
  await expect(demo).toHaveAttribute('data-ready', 'true', { timeout: 45000 });
  await expect(demo.locator('canvas')).toBeVisible();
  await expect(demo.locator('[data-fallback]')).toBeHidden();
  testInfo.annotations.push({ type: 'graphics backend', description: (await demo.getAttribute('data-backend'))! });
  const originalCanvas = await demo.locator('canvas').screenshot();
  const initial = await demo.locator('[data-metrics]').textContent();
  await demo.getByLabel('Alpha divisor').selectOption('12');
  await demo.getByLabel('Offset ratio').selectOption('300');
  await expect(demo).toHaveAttribute('data-case', 'a12-o300');
  await expect(demo.locator('[data-metrics]')).not.toHaveText(initial!);
  expect((await demo.locator('canvas').screenshot()).equals(originalCanvas)).toBe(false);
  for (const stage of ['cad', 'grid', 'projected', 'hull', 'graph', 'braced']) {
    await demo.locator(`button[data-stage="${stage}"]`).click();
    await expect(demo).toHaveAttribute('data-stage', stage);
    await expect(demo.locator('[data-explanation]')).not.toBeEmpty();
  }
  await expect(demo.locator('[data-metrics]')).toContainText(`${manifest.cases.find(c => c.id === 'a12-o300')!.graphBeams} beams`);
  await demo.getByRole('button', { name: 'Side', exact: true }).click();
  await demo.getByLabel('Show CAD').uncheck();
  await demo.screenshot({ path: testInfo.outputPath('frame-graph.png') });
  await demo.locator('button[data-stage="proxy"]').click();
  await expect(demo).toHaveAttribute('data-stage', 'proxy');
  await demo.screenshot({ path: testInfo.outputPath('alpha-wrap.png') });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  expect(errors).toEqual([]);
});

test('tuning changes real response data without changing supports or source graph', async ({ page }, testInfo) => {
  await page.goto('/concepts/calibration/');
  const demo = page.locator('cad-tuning-explorer');
  const original = await demo.locator('[data-rest] path').getAttribute('d');
  const fitted = await demo.locator('[data-deformed] path').getAttribute('d');
  const fittedResult = await demo.locator('[data-result]').textContent();
  await demo.getByRole('button', { name: 'Initial springs' }).click();
  await expect(demo.locator('[data-result]')).not.toHaveText(fittedResult!);
  await expect(demo.locator('[data-deformed] path')).not.toHaveAttribute('d', fitted!);
  await demo.getByRole('button', { name: 'Torsion', exact: true }).click();
  await expect(demo).toHaveAttribute('data-case', 'torsion');
  await demo.getByRole('button', { name: 'Fitted springs' }).click();
  const result = await demo.locator('[data-result]').textContent();
  await demo.getByRole('slider').fill('0');
  await expect(demo.locator('[data-deformed] path')).toHaveAttribute('d', original!);
  await expect(demo.locator('[data-result]')).toHaveText(result!);
  expect(await demo.locator('[data-markers] rect').evaluateAll(nodes => nodes.every(n => n.getAttribute('width') === '8'))).toBe(true);
  await demo.getByRole('slider').fill('45');
  await demo.screenshot({ path: testInfo.outputPath('calibration.png') });
  await demo.getByLabel('Show internal beams').check();
  await expect(demo.locator('[data-rest] path')).not.toHaveAttribute('d', original!);
  await expect(demo.locator('[data-result]')).toHaveText(result!);
});

test('mate matrix and visualization agree on each compiled constraint combination', async ({ page }, testInfo) => {
  await page.goto('/concepts/joints/');
  const demo = page.locator('cad-mate-explorer');
  for (const c of mate.cases) {
    await demo.locator(`button[data-case="${c.id}"]`).click();
    await expect(demo.locator('[data-result]')).toContainText(`${c.kind}: ${c.dof}`);
    await expect(demo.locator('[data-matrix] tr')).toHaveCount(c.matrix.length);
    await expect(demo.locator('[data-rank]')).toContainText(`rank ${6 - c.dof}`);
    await expect(demo.locator('[data-freedoms] [data-free="true"]')).toHaveCount(c.dof);
  }
  await demo.locator('button[data-case="hinge"]').click();
  await expect(demo.locator('.mate-realization')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await demo.screenshot({ path: testInfo.outputPath('mate-compiler.png') });
});

test('source tags survive Markdown and MDX builds and retired routes return 404', async ({ page }) => {
  for (const slug of ['wrapping', 'calibration', 'joints']) {
    await page.goto(`/concepts/${slug}/`);
    await expect(page.locator('figure[data-doc-evidence]').first()).toBeVisible();
    await expect(page.locator('a[href^="/contributors/documentation/#"]').first()).toBeVisible();
    expect(await page.locator('.sl-markdown-content p[data-doc-evidence]').count()).toBeGreaterThan(0);
  }
  await page.goto('/guides/frame/');
  expect(await page.locator('.sl-markdown-content [data-doc-evidence]').count()).toBeGreaterThan(0);
  for (const route of ['interchange', 'draft-preparation', 'legacy-frame']) {
    expect((await page.goto(`/reference/${route}/`))!.status()).toBe(404);
  }
});

test('engineering explanations keep useful geometry and data with JavaScript disabled', async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false, viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  try {
    await page.goto('/concepts/wrapping/');
    await expect(page.locator('[data-fallback]')).toBeVisible();
    for (const slug of ['calibration', 'joints']) {
      await page.goto(`/concepts/${slug}/`);
      await expect(page.locator('figure.engineering-explorer svg').first()).toBeVisible();
      await expect(page.locator('figure.engineering-explorer noscript')).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    }
  } finally { await context.close(); }
});

test('frame viewer falls back to WebGL2 when WebGPU is unavailable', async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, 'gpu', { value: undefined, configurable: true }));
  await page.goto('/concepts/wrapping/');
  const demo = page.locator('cad-wrap-explorer');
  await demo.getByRole('button', { name: 'Load interactive frame' }).click();
  await expect(demo).toHaveAttribute('data-ready', 'true', { timeout: 45000 });
  await expect(demo).toHaveAttribute('data-backend', 'WebGL2');
  await expect(demo.locator('[data-fallback]')).toBeHidden();
});

test('unavailable graphics retains the static explanation and offers retry', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'gpu', { value: undefined, configurable: true });
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function(this: HTMLCanvasElement, type: string, ...args: any[]) {
      if (/webgl|webgpu/.test(type)) return null;
      return original.apply(this, [type, ...args] as any);
    } as typeof original;
  });
  await page.goto('/concepts/wrapping/');
  const demo = page.locator('cad-wrap-explorer');
  await demo.getByRole('button', { name: 'Load interactive frame' }).click();
  await expect(demo.getByRole('button', { name: 'Retry 3D view' })).toBeEnabled({ timeout: 45000 });
  await expect(demo.locator('[data-fallback]')).toBeVisible();
  await expect(demo.locator('[data-status]')).toContainText('could not start');
});

test('WebGPU compiles the TSL materials and renders the graph', async ({}, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'One backend check is sufficient; responsive behavior has separate coverage.');
  test.setTimeout(90000);
  const browser = await chromium.launch({ args: ['--enable-unsafe-webgpu'] });
  try {
    const page = await browser.newPage();
    await page.goto('http://127.0.0.1:4322/concepts/wrapping/');
    const available = await page.evaluate(async () => Boolean(await (navigator as any).gpu?.requestAdapter()));
    test.skip(!available, 'This machine does not expose a WebGPU adapter to Chromium.');
    const errors: string[] = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', message => { if(message.type() === 'error') errors.push(message.text()); });
    const demo = page.locator('cad-wrap-explorer');
    await demo.getByRole('button', { name: 'Load interactive frame' }).click();
    await expect(demo).toHaveAttribute('data-ready', 'true', { timeout: 45000 });
    await expect(demo).toHaveAttribute('data-backend', 'WebGPU');
    const proxy = await demo.locator('canvas').screenshot();
    await demo.locator('button[data-stage="braced"]').click();
    await expect(demo).toHaveAttribute('data-stage', 'braced');
    expect((await demo.locator('canvas').screenshot()).equals(proxy)).toBe(false);
    await demo.screenshot({ path: testInfo.outputPath('webgpu.png') });
    expect(errors).toEqual([]);
  } finally { await browser.close(); }
});
