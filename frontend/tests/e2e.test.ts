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

  test('full ingestion, archival, and recovery workflow', async ({ page }) => {
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
    await page.goto('/inventory');
    await page.waitForLoadState('networkidle');
    console.log('Clicking Register media button');
    await page.getByRole('button', { name: /Register media/i }).click();

    console.log('Waiting for Mock LTO Tape text');
    await expect(page.getByText('Mock LTO Tape (Test)')).toBeVisible({ timeout: 10000 });
    await page.getByText('Mock LTO Tape (Test)').click();

    console.log('Filling form');
    await page.getByLabel('Identifier (Barcode/SN)').fill('TAPE001');
    await page.getByLabel('Capacity (GB)').fill('100');
    await page.getByLabel('Mock Directory Path').fill(MOCK_LTO_PATH);

    await page.getByRole('button', { name: 'Register media' }).last().click();
    await expect(page.getByText(/TAPE001 registered/i)).toBeVisible();

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
    const backupJob = page.locator('div', { hasText: /BACKUP/i }).filter({ hasText: /JOB #/ }).first();
    await expect(backupJob.getByText('COMPLETED', { exact: true }).first()).toBeVisible({ timeout: 60000 });

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
    const restoreJob = page.locator('div', { hasText: /RESTORE/i }).filter({ hasText: /JOB #/ }).first();
    await expect(restoreJob.getByText('COMPLETED', { exact: true }).first()).toBeVisible({ timeout: 60000 });

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
});
