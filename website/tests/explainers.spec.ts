import { test, expect } from '@playwright/test';
import { springSetup } from '../src/lib/explainers';

test('spring model retains physical scaling', () => {
  const baseline = springSetup(40, 2, 0.5);
  expect(springSetup(80,2,.5).stiffness).toBeCloseTo(2*baseline.stiffness);
  expect(springSetup(40,4,.5).stiffness).toBeCloseTo(4*baseline.stiffness);
  expect(springSetup(40,2,1).stiffness).toBeCloseTo(baseline.stiffness/4);
  expect(baseline.preload*.5).toBeCloseTo(40*9.81);
});


test('spring controls recalculate both the plot and its numeric readouts', async ({ page }, testInfo) => {
  await page.goto('/concepts/wheels-drivetrain/');
  const demo = page.locator('cad-spring-demo');
  const original = await demo.locator('[data-force]').getAttribute('d');
  await demo.getByRole('slider', { name: 'Sprung corner mass' }).fill('40');
  await demo.getByRole('slider', { name: 'Target frequency' }).fill('2');
  await demo.getByRole('slider', { name: 'Motion ratio', exact: true }).fill('0.5');
  await expect(demo.locator('[data-rate]')).toHaveText('25.3 N/mm');
  await expect(demo.locator('[data-preload]')).toHaveText('785 N');
  await expect(demo.locator('[data-damping]')).toHaveText('1206 N·s/m');
  await expect(demo.locator('[data-force]')).not.toHaveAttribute('d', original!);
  await demo.getByRole('button', { name: 'Reset inputs' }).click();
  await expect(demo.locator('[data-force]')).toHaveAttribute('d', original!);
  await demo.screenshot({ path: testInfo.outputPath('spring.png') });
});

test('recorded evidence preserves the failed qualification when a passing metric is selected', async ({ page }, testInfo) => {
  await page.goto('/concepts/verification/');
  const demo = page.locator('cad-evidence-demo');
  await expect(demo.locator('[data-value="0"]')).toHaveText('2.821');
  await expect(demo.locator('[data-value="1"]')).toHaveText('1.690');
  await demo.getByRole('button', { name: 'Broken beams' }).click();
  await expect(demo.locator('[data-bar="0"]')).toHaveAttribute('width', '0');
  await expect(demo.locator('[data-zero="0"]')).toHaveAttribute('visibility', 'visible');
  await expect(demo.locator('[data-conclusion]')).toContainText('still failed on lateral drift');
  await demo.getByText('Exact measurements and source provenance').click();
  await expect(demo.getByRole('table')).toContainText('2.821061');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await demo.screenshot({ path: testInfo.outputPath('evidence.png') });
});

test('every explainer has no browser errors or horizontal page overflow', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  for (const slug of ['pipeline', 'wheels-drivetrain', 'verification']) {
    await page.goto(`/concepts/${slug}/`);
    await expect(page.locator('.explainer button').first()).toBeEnabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    expect(await page.locator('.explainer svg').count()).toBe(1);
  }
  expect(errors).toEqual([]);
});

test('explanations retain useful figures and provenance without JavaScript', async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false, viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  try {
    for (const slug of ['pipeline', 'wheels-drivetrain', 'verification']) {
      await page.goto(`/concepts/${slug}/`);
      await expect(page.locator('.explainer svg')).toBeVisible();
      await expect(page.locator('.explainer figcaption')).not.toBeEmpty();
      await expect(page.locator('.explainer button').first()).toBeDisabled();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    }
    await page.getByText('Exact measurements and source provenance').click();
    await expect(page.locator('.demo-evidence-table')).toContainText('2.821061');
  } finally { await context.close(); }
});
