import { test, expect } from '@playwright/test';

test('landing page leads to a usable guide without horizontal overflow', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('From CAD to BeamNG.');
  await expect(page.locator('img')).toHaveCount(1);
  await expect.poll(() => page.locator('img').evaluateAll(images => images.every(img => (img as HTMLImageElement).naturalWidth > 0))).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('home.png'), fullPage: true });
  await page.getByRole('link', { name: 'Get started', exact: true }).click();
  await expect(page).toHaveURL(/\/start\/overview\/$/);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('What is beamng.cad?');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  expect(errors).toEqual([]);
});

test('production search for coilover opens the Spring Setup guide', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Search', exact: true });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('textbox').fill('coilover');
  const result = dialog.locator('a[href*="/guides/coilovers/"]').first();
  await expect(result).toBeVisible({ timeout: 20000 });
  await result.click();
  await expect(page).toHaveURL(/\/guides\/coilovers\//);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Spring setup');
});

test('sidebar, themes and direct nested routes work', async ({ page, isMobile }, testInfo) => {
  await page.goto('/guides/frame/');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Prepare and generate a frame');
  if (isMobile) await page.getByRole('button', { name: 'Menu', exact: true }).click();
  const select = page.locator('starlight-theme-select select:visible').first();
  await select.selectOption('dark');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  const navLink = page.locator('#starlight__sidebar a[href="/guides/shafts/"]');
  await navLink.click();
  await expect(page).toHaveURL(/\/guides\/shafts\/$/);
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('guide-dark.png'), fullPage: true });
  if (isMobile) await page.getByRole('button', { name: 'Menu', exact: true }).click();
  await page.locator('starlight-theme-select select:visible').first().selectOption('light');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
});

test('code copy, keyboard navigation and missing-page response', async ({ page, context, isMobile }) => {
  await page.goto('/start/install/');
  if (!isMobile) {
    await page.keyboard.press('Tab');
    await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused();
    await page.keyboard.press('Enter');
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    const buildCommand = page.locator('.expressive-code').filter({ hasText: 'dotnet build beamng.cad.slnx' }).first();
    await buildCommand.hover();
    await buildCommand.getByRole('button', { name: /copy to clipboard/i }).click();
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toContain('dotnet build beamng.cad.slnx');
    await page.keyboard.press('Control+k');
    await expect(page.getByRole('dialog', { name: 'Search', exact: true })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog', { name: 'Search', exact: true })).not.toBeVisible();
  }
  const response = await page.goto('/a-page-that-does-not-exist/');
  expect(response?.status()).toBe(404);
  await expect(page.getByRole('heading', { level: 1 })).toContainText('404');
});
