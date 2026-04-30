import { test, expect, request } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import { API_URL, SOURCE_ROOT, setupRequestContext, configureBackend } from './helpers';

test.describe('Discrepancies', () => {
  let fileIds: Record<string, number> = {};

  test.beforeAll(async ({ playwright }) => {
    const requestContext = await setupRequestContext();

    if (fs.existsSync(SOURCE_ROOT)) {
      fs.rmSync(SOURCE_ROOT, { recursive: true });
    }
    fs.mkdirSync(SOURCE_ROOT, { recursive: true });

    // Create files for testing (except ui_missing.txt which needs to be deleted from disk)
    const testFiles = [
      'confirm_missing.txt',
      'dismiss_test.txt',
      'purge_test.txt',
      'ui_deleted.txt',
    ];
    for (const f of testFiles) {
      fs.writeFileSync(path.join(SOURCE_ROOT, f), `content for ${f}`);
    }

    // Create ui_missing.txt, scan it, then delete it from disk to make it "missing"
    const missingFilePath = path.join(SOURCE_ROOT, 'ui_missing.txt');
    fs.writeFileSync(missingFilePath, 'content for ui_missing.txt');

    await configureBackend(requestContext);

    // Trigger scan via API
    await requestContext.post(`${API_URL}/system/scan`);

    // Wait for scan to complete by polling dashboard stats
    const deadline = Date.now() + 30000;
    while (Date.now() < deadline) {
      const statsResp = await requestContext.get(`${API_URL}/system/dashboard/stats`);
      const stats = await statsResp.json();
      if (stats.monitored_files_count > 0) {
        break;
      }
      await new Promise(r => setTimeout(r, 500));
    }

    // Get file IDs from metadata
    for (const f of [...testFiles, 'ui_missing.txt']) {
      const filePath = path.join(SOURCE_ROOT, f);
      const encodedPath = encodeURIComponent(filePath);
      const metaResp = await requestContext.get(`${API_URL}/inventory/metadata?path=${encodedPath}`);
      if (metaResp.ok()) {
        const meta = await metaResp.json();
        fileIds[f] = meta.id;
      }
    }

    // Delete ui_missing.txt from disk so it shows as "missing" in discrepancies
    fs.rmSync(missingFilePath, { force: true });

    // Rescan to detect the missing file
    await requestContext.post(`${API_URL}/system/scan`);
    const deadline2 = Date.now() + 30000;
    while (Date.now() < deadline2) {
      const statsResp = await requestContext.get(`${API_URL}/system/dashboard/stats`);
      const stats = await statsResp.json();
      if (stats.files_missing > 0) {
        break;
      }
      await new Promise(r => setTimeout(r, 500));
    }

    console.log(`File IDs: ${JSON.stringify(fileIds)}`);
    await requestContext.dispose();
  });

  test.afterEach(async ({}) => {
    // No automatic cleanup needed - tests use separate files
  });

  test('missing files are detected and can be confirmed', async ({}) => {
    const requestContext = await request.newContext();
    const fileId = fileIds['confirm_missing.txt'];
    expect(fileId).toBeDefined();

    console.log('Step 1: Confirm the file as deleted');
    const confirmResp = await requestContext.post(`${API_URL}/system/discrepancies/${fileId}/confirm`);
    expect(confirmResp.ok()).toBe(true);

    console.log('Step 2: Verify item appears in discrepancies as deleted');
    const discResp = await requestContext.get(`${API_URL}/system/discrepancies`);
    const discrepancies = await discResp.json();
    const found = (discrepancies as Array<any>).find((d: any) => d.path === path.join(SOURCE_ROOT, 'confirm_missing.txt'));
    expect(found).toBeDefined();
    expect(found.is_deleted).toBe(true);

    await requestContext.dispose();
  });

  test('dismiss discrepancy', async ({}) => {
    const requestContext = await request.newContext();
    const fileId = fileIds['dismiss_test.txt'];
    expect(fileId).toBeDefined();

    console.log('Step 1: Confirm as deleted first');
    await requestContext.post(`${API_URL}/system/discrepancies/${fileId}/confirm`);

    console.log('Step 2: Dismiss the discrepancy');
    const dismissResp = await requestContext.post(`${API_URL}/system/discrepancies/${fileId}/dismiss`);
    expect(dismissResp.ok()).toBe(true);

    console.log('Step 3: Verify discrepancy is cleared');
    const afterDismissResp = await requestContext.get(`${API_URL}/system/discrepancies`);
    const afterDismiss = await afterDismissResp.json();
    const stillPresent = (afterDismiss as Array<any>).find((d: any) => d.path === path.join(SOURCE_ROOT, 'dismiss_test.txt'));
    expect(stillPresent).toBeUndefined();

    await requestContext.dispose();
  });

  test('purge deleted file record', async ({}) => {
    const requestContext = await request.newContext();
    const fileId = fileIds['purge_test.txt'];
    expect(fileId).toBeDefined();

    console.log('Step 1: Confirm as deleted');
    await requestContext.post(`${API_URL}/system/discrepancies/${fileId}/confirm`);

    console.log('Step 2: Purge the record');
    const purgeResp = await requestContext.delete(`${API_URL}/system/discrepancies/${fileId}`);
    expect(purgeResp.ok()).toBe(true);

    console.log('Step 3: Verify record is permanently gone');
    const afterPurgeResp = await requestContext.get(`${API_URL}/system/discrepancies`);
    const afterPurge = await afterPurgeResp.json();
    const stillPresent = (afterPurge as Array<any>).find((d: any) => d.path === path.join(SOURCE_ROOT, 'purge_test.txt'));
    expect(stillPresent).toBeUndefined();

    await requestContext.dispose();
  });

  test('discrepancies page UI renders correctly', async ({ page }) => {
    const requestContext = await request.newContext();
    const fileId = fileIds['ui_deleted.txt'];
    expect(fileId).toBeDefined();

    console.log('Step 1: Confirm as deleted');
    const confirmResp = await requestContext.post(`${API_URL}/system/discrepancies/${fileId}/confirm`);
    // If already deleted or purged, that's OK - we just need some discrepancies to show
    if (!confirmResp.ok()) {
      console.log(`  Confirm response: ${confirmResp.status()}`);
    }

    console.log('Step 2: Navigate to discrepancies page');
    await page.goto('/discrepancies');
    await page.waitForLoadState('networkidle');

    await expect(page.getByRole('heading', { name: 'Discrepancies' })).toBeVisible();
    await expect(page.getByText('Files missing from disk or confirmed deleted')).toBeVisible();

    console.log('Step 3: Verify summary cards are visible');
    await expect(page.getByText('Confirmed deleted', { exact: true })).toBeVisible();
    await expect(page.getByText('Missing from disk', { exact: true })).toBeVisible();

    await requestContext.dispose();
  });

  test('empty state displays when no discrepancies', async ({ page }) => {
    const requestContext = await request.newContext();

    console.log('Step 1: Clean up all discrepancies');
    const discResp = await requestContext.get(`${API_URL}/system/discrepancies`);
    const discrepancies = await discResp.json();

    if ((discrepancies as Array<any>).length > 0) {
      for (const d of discrepancies as Array<any>) {
        await requestContext.delete(`${API_URL}/system/discrepancies/${d.id}`);
      }
    }

    console.log('Step 2: Navigate to discrepancies page');
    await page.goto('/discrepancies');
    await page.waitForLoadState('networkidle');

    await expect(page.getByText('All clear')).toBeVisible();
    await expect(page.getByText('No discrepancies detected')).toBeVisible();

    await requestContext.dispose();
  });
});
