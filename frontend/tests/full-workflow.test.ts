import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const SOURCE_ROOT = '/tmp/tapehoard_e2e_source';
const MOCK_LTO_PATH = '/tmp/tapehoard_e2e_mock_lto';
const RESTORE_DEST = '/tmp/tapehoard_e2e_restore';
const API_URL = 'http://localhost:8001';

test.describe('TapeHoard Golden Path', () => {
  test.beforeAll(async ({ playwright }) => {
    // 0. Reset Backend Environment
    const requestContext = await playwright.request.newContext();
    const resetResponse = await requestContext.post(`${API_URL}/system/test/reset`);
    if (!resetResponse.ok()) {
        console.error('Failed to reset test environment');
    }

    // 1. Create source data
    if (fs.existsSync(SOURCE_ROOT)) {
      fs.rmSync(SOURCE_ROOT, { recursive: true });
    }
    fs.mkdirSync(SOURCE_ROOT, { recursive: true });
    fs.writeFileSync(path.join(SOURCE_ROOT, 'test_file_1.txt'), 'Hello world 1');
    fs.mkdirSync(path.join(SOURCE_ROOT, 'subfolder'));
    fs.writeFileSync(path.join(SOURCE_ROOT, 'subfolder', 'test_file_2.txt'), 'Hello world 2');

    // Create mock LTO dir
    if (fs.existsSync(MOCK_LTO_PATH)) {
      fs.rmSync(MOCK_LTO_PATH, { recursive: true });
    }
    fs.mkdirSync(MOCK_LTO_PATH, { recursive: true });

    // Ensure restore destination exists
    if (fs.existsSync(RESTORE_DEST)) {
        fs.rmSync(RESTORE_DEST, { recursive: true });
    }
    fs.mkdirSync(RESTORE_DEST, { recursive: true });

    // Configure backend via API
    await requestContext.post(`${API_URL}/system/settings`, {
      data: { key: 'source_roots', value: JSON.stringify([SOURCE_ROOT]) }
    });
    await requestContext.post(`${API_URL}/system/settings`, {
        data: { key: 'restore_destinations', value: JSON.stringify([RESTORE_DEST]) }
    });
    await requestContext.dispose();
  });

  test('full ingestion, archival, and recovery workflow', async ({ page, request }) => {
    page.on('console', msg => console.log('BROWSER CONSOLE:', msg.text()));
    page.on('pageerror', err => console.log('BROWSER ERROR:', err.message));

    console.log('Step 1: Discovery & Tracking');
    await page.goto('/filesystem');
    await page.waitForLoadState('networkidle');

    await expect(page.getByText(SOURCE_ROOT).first()).toBeVisible();
    await page.getByText(SOURCE_ROOT).first().click();
    await page.waitForLoadState('networkidle');
    await expect(page.getByText('test_file_1.txt')).toBeVisible();
    await expect(page.getByText('subfolder')).toBeVisible();

    const fileRow1 = page.locator('div[role="button"]', { hasText: 'test_file_1.txt' });
    await fileRow1.locator('div').first().click();

    await page.getByRole('button', { name: /Commit rules/i }).click();
    await expect(page.getByText(/Changes committed/i)).toBeVisible();

    console.log('Step 2: Indexing');
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: /Start scan/i }).click();
    await expect(page.getByText(/Scan job initiated/i)).toBeVisible();

    await expect(async () => {
        await page.getByRole('button', { name: /Refresh/i }).click();
        const monitoredCountText = await page.locator('h4').first().textContent();
        const monitoredCount = parseInt(monitoredCountText?.replace(/,/g, '') || '0');
        console.log(`Current monitored count: ${monitoredCount}`);
        expect(monitoredCount).toBeGreaterThan(0);
    }).toPass({ timeout: 20000 });

    console.log('Step 3: Media Registration');
    // Tape media is registered via API (discovery-only flow — no UI form for tape)
    const registerResp = await request.post(`${API_URL}/inventory/media`, {
        data: {
            media_type: 'mock_lto',
            identifier: 'TAPE001',
            generation_tier: 'LTO-6',
            capacity: 100 * 1024 * 1024 * 1024,
            location: 'Test Shelf',
            config: { device_path: MOCK_LTO_PATH }
        }
    });
    expect(registerResp.ok()).toBe(true);

    await page.goto('/inventory');
    await page.waitForLoadState('networkidle');
    await expect(page.getByText('TAPE001')).toBeVisible({ timeout: 10000 });

    console.log('Step 4: Initialization');
    page.on('dialog', dialog => {
        console.log('Dialog opened: ', dialog.message());
        dialog.accept();
    });
    await page.getByRole('button', { name: /Initialize/i }).click();
    await expect(page.getByText(/initialized successfully/i)).toBeVisible({ timeout: 10000 });

    console.log('Step 5: Archival');
    await expect(page.getByText('TAPE001', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: /Auto archive/i }).click();
    await expect(page.getByText(/Archival job initiated/i)).toBeVisible();

    console.log('Step 6: Waiting for archival job');
    await page.goto('/jobs');
    await page.waitForLoadState('networkidle');
    await expect(page.getByText('Backup', { exact: false }).first()).toBeVisible({ timeout: 60000 });
    await expect(page.getByText('Completed').first()).toBeVisible({ timeout: 60000 });

    console.log('Step 7: Verify Protection');
    await page.goto('/index-browser');
    await page.waitForLoadState('networkidle');
    await page.getByText(SOURCE_ROOT).first().dblclick();
    await page.getByText('subfolder').first().dblclick();
    await expect(page.getByText('test_file_2.txt')).toBeVisible();
    await expect(page.getByText('TAPE001')).toBeVisible();

    console.log('Step 8: Data Recovery');
    const fileRow = page.locator('div[role="button"]', { hasText: 'test_file_2.txt' });
    await fileRow.locator('button[role="checkbox"]').click();
    await expect(page.getByText(/2 items in queue/i)).toBeVisible();

    await page.goto('/restores');
    await page.waitForLoadState('networkidle');
    await page.getByRole("treeitem").getByText('/tmp/tapehoard_e2e_source').click();
    await page.waitForLoadState('networkidle');
    await page.getByText('subfolder').dblclick();
    await expect(page.getByText('test_file_2.txt')).toBeVisible();

    await page.locator('select#destination').selectOption(RESTORE_DEST);
    await page.getByRole('button', { name: /Initiate recovery/i }).click();
    await expect(page.getByText(/Recovery job initiated/i)).toBeVisible();

    console.log('Step 9: Waiting for restore job');
    await page.goto('/jobs');
    await page.waitForLoadState('networkidle');
    await expect(page.getByText('Restore', { exact: false }).first()).toBeVisible({ timeout: 60000 });
    await expect(page.getByText('Completed').first()).toBeVisible({ timeout: 60000 });

    console.log('Step 10: Verify disk');
    const restoredFilePath = path.join(RESTORE_DEST, SOURCE_ROOT, 'subfolder', 'test_file_2.txt');
    await page.waitForTimeout(2000);

    if (!fs.existsSync(restoredFilePath)) {
        const fallbackPath = path.join(RESTORE_DEST, 'test_file_2.txt');
        if (fs.existsSync(fallbackPath)) {
            expect(fs.readFileSync(fallbackPath, 'utf-8')).toBe('Hello world 2');
        } else {
            const files = fs.readdirSync(RESTORE_DEST, { recursive: true });
            console.log('Restore DEST contents:', files);
            throw new Error(`Restored file not found. Present: ${files.join(', ')}`);
        }
    } else {
        expect(fs.readFileSync(restoredFilePath, 'utf-8')).toBe('Hello world 2');
    }
  });

  test('file deletion discrepancy workflow', async ({ page }) => {
    page.on('console', msg => console.log('BROWSER CONSOLE:', msg.text()));
    page.on('pageerror', err => console.log('BROWSER ERROR:', err.message));

    console.log('Step 1: Create test file and scan');
    const testFilePath = path.join(SOURCE_ROOT, 'discrepancy_test.txt');
    fs.writeFileSync(testFilePath, 'will be deleted');

    const requestContext = await page.context().request;
    const scanResp = await requestContext.post(`${API_URL}/system/scan`);
    expect(scanResp.ok()).toBe(true);

    // Wait for scan to complete
    await expect(async () => {
      const statusResp = await requestContext.get(`${API_URL}/system/scan/status`);
      const status = await statusResp.json();
      expect(status.is_running).toBe(false);
    }).toPass({ timeout: 20000 });

    // Also wait for hashing to complete
    await page.waitForTimeout(2000);

    // Get the file ID from the metadata endpoint
    const encodedPath = encodeURIComponent(testFilePath);
    const metaResp = await requestContext.get(`${API_URL}/inventory/metadata?path=${encodedPath}`);
    expect(metaResp.ok()).toBe(true);
    const meta = await metaResp.json();
    const fileId = meta.id;

    // Mark the file as deleted via discrepancy API
    const confirmResp = await requestContext.post(`${API_URL}/system/discrepancies/${fileId}/confirm`);
    if (!confirmResp.ok()) {
      const errBody = await confirmResp.json();
      console.log('Confirm failed:', errBody);
    }
    expect(confirmResp.ok()).toBe(true);

    // Verify it shows in discrepancies
    const discrepanciesResp = await requestContext.get(`${API_URL}/system/discrepancies`);
    const discrepancies = await discrepanciesResp.json();
    const deletedItem = (discrepancies as Array<any>).find((d: any) => d.path === testFilePath);
    expect(deletedItem).toBeDefined();
    expect(deletedItem.is_deleted).toBe(true);

    console.log('Step 2: Verify deleted file cannot be restored');
    const restoreResp = await requestContext.post(`${API_URL}/restores/queue/file/${fileId}`);
    expect(restoreResp.status()).toBe(400);
    const restoreBody = await restoreResp.json();
    expect(restoreBody.detail.toLowerCase()).toContain('deleted');

    console.log('Step 3: Dismiss the discrepancy');
    const dismissResp = await requestContext.post(`${API_URL}/system/discrepancies/${fileId}/dismiss`);
    expect(dismissResp.ok()).toBe(true);

    // Verify it's no longer in discrepancies
    const afterDismissResp = await requestContext.get(`${API_URL}/system/discrepancies`);
    const afterDismiss = await afterDismissResp.json();
    const stillDeleted = (afterDismiss as Array<any>).find((d: any) => d.path === testFilePath);
    expect(stillDeleted).toBeUndefined();

    fs.rmSync(testFilePath, { force: true });
    await requestContext.dispose();
  });
});
