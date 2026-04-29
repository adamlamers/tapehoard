import { test, expect } from '@playwright/test';

test.describe('TapeHoard Golden Path', () => {
  test('homepage loads and shows basic navigation', async ({ page }) => {
    await page.goto('/');

    // Validate the page title or basic UI elements exist
    // This assumes there's some header or title indicating TapeHoard
    await expect(page).toHaveTitle(/TapeHoard|Svelte/i);

    // Check if navigation links are visible
    // We expect links to Backup Manager, Media Inventory, Archive Index etc based on E2E.md
    const nav = page.locator('nav');
    if (await nav.count() > 0) {
      await expect(page.locator('text=Inventory').first()).toBeVisible();
      await expect(page.locator('text=Archive').first()).toBeVisible();
    }
  });

  test('media inventory shows mock provider when in test mode', async ({ page }) => {
    await page.goto('/inventory');

    // Wait for the page to be fully loaded and hydrated
    await page.waitForLoadState('networkidle');

    // Click the Register media button to open the dialog
    await page.getByRole('button', { name: /Register media/i }).click();

    // Check for the Mock provider text inside the dialog
    await expect(page.getByText('Mock LTO Tape (Test)')).toBeVisible({ timeout: 10000 });
  });
});
