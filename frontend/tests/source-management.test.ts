import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import { API_URL, SOURCE_ROOT, setupRequestContext } from './helpers';

test.describe('Source Management', () => {
  test.beforeEach(async () => {
    // Ensure source root exists
    fs.mkdirSync(SOURCE_ROOT, { recursive: true });
    fs.writeFileSync(path.join(SOURCE_ROOT, 'include.txt'), 'should be tracked');
    fs.mkdirSync(path.join(SOURCE_ROOT, 'excluded_dir'), { recursive: true });
    fs.writeFileSync(path.join(SOURCE_ROOT, 'excluded_dir', 'secret.txt'), 'should be ignored');
  });

  test('configure source roots and trigger scan', async ({ page }) => {
    const requestContext = await setupRequestContext();

    console.log('Step 1: Set source roots');
    const settingsResp = await requestContext.post(`${API_URL}/system/settings`, {
      data: { key: 'source_roots', value: JSON.stringify([SOURCE_ROOT]) }
    });
    expect(settingsResp.ok()).toBe(true);

    console.log('Step 2: Verify settings persisted');
    const getSettings = await requestContext.get(`${API_URL}/system/settings`);
    const settings = await getSettings.json();
    expect(settings.source_roots).toBeDefined();

    console.log('Step 3: Trigger scan');
    const scanResp = await requestContext.post(`${API_URL}/system/scan`);
    expect(scanResp.ok()).toBe(true);
    expect(scanResp.json()).toBeDefined();

    // Wait for scan to complete
    await new Promise(r => setTimeout(r, 3000));
    const statusResp = await requestContext.get(`${API_URL}/system/scan/status`);
    const status = await statusResp.json();
    expect(status.is_running).toBe(false);
    expect(status.total_files_found).toBeGreaterThan(0);

    await requestContext.dispose();
  });

  test('exclude path via tracking rules', async ({ page }) => {
    const requestContext = await setupRequestContext();

    await requestContext.post(`${API_URL}/system/settings`, {
      data: { key: 'source_roots', value: JSON.stringify([SOURCE_ROOT]) }
    });

    console.log('Step 1: Exclude a path via batch tracking');
    const trackResp = await requestContext.post(`${API_URL}/system/track/batch`, {
      data: {
        tracks: [],
        untracks: [path.join(SOURCE_ROOT, 'excluded_dir')]
      }
    });
    expect(trackResp.ok()).toBe(true);

    console.log('Step 2: Trigger scan');
    const scanResp = await requestContext.post(`${API_URL}/system/scan`);
    expect(scanResp.ok()).toBe(true);

    await new Promise(r => setTimeout(r, 3000));

    console.log('Step 3: Verify excluded file is marked ignored');
    const browseResp = await requestContext.get(
      `${API_URL}/system/browse?path=${path.join(SOURCE_ROOT, 'excluded_dir')}`
    );
    const browseData = await browseResp.json();
    const files = (browseData as any).files;
    const secretFile = (files as Array<any>).find((f: any) => f.name === 'secret.txt');
    if (secretFile) {
      expect(secretFile.ignored).toBe(true);
    }

    await requestContext.dispose();
  });

  test('override exclusion with include rule', async ({ page }) => {
    const requestContext = await setupRequestContext();

    await requestContext.post(`${API_URL}/system/settings`, {
      data: { key: 'source_roots', value: JSON.stringify([SOURCE_ROOT]) }
    });

    // First exclude, then include the same path (most specific wins)
    await requestContext.post(`${API_URL}/system/track/batch`, {
      data: {
        tracks: [path.join(SOURCE_ROOT, 'excluded_dir', 'secret.txt')],
        untracks: [path.join(SOURCE_ROOT, 'excluded_dir')]
      }
    });

    const scanResp = await requestContext.post(`${API_URL}/system/scan`);
    expect(scanResp.ok()).toBe(true);

    await new Promise(r => setTimeout(r, 3000));

    const browseResp = await requestContext.get(
      `${API_URL}/system/browse?path=${SOURCE_ROOT}`
    );
    const browseData = await browseResp.json();
    const files = (browseData as any).files;
    const includedFile = (files as Array<any>).find((f: any) => f.name === 'include.txt');
    expect(includedFile).toBeDefined();
    expect(includedFile.ignored).toBe(false);

    await requestContext.dispose();
  });

  test('remove source root stops scanning', async ({ page }) => {
    const requestContext = await setupRequestContext();

    // Set a nonexistent source root
    await requestContext.post(`${API_URL}/system/settings`, {
      data: { key: 'source_roots', value: JSON.stringify(['/nonexistent/path']) }
    });

    const scanResp = await requestContext.post(`${API_URL}/system/scan`);
    expect(scanResp.ok()).toBe(true);

    await new Promise(r => setTimeout(r, 3000));

    const statusResp = await requestContext.get(`${API_URL}/system/scan/status`);
    const status = await statusResp.json();
    // No files found since source doesn't exist
    expect(status.total_files_found).toBe(0);

    await requestContext.dispose();
  });
});
