import { test, expect } from '@playwright/test';
import { API_URL, SOURCE_ROOT, setupRequestContext, configureBackend } from './helpers';

test.describe('Settings & System', () => {
  test('CRUD system settings', async ({ page }) => {
    const requestContext = await setupRequestContext();

    console.log('Step 1: Get initial settings (should be empty)');
    const getResp = await requestContext.get(`${API_URL}/system/settings`);
    expect(getResp.ok()).toBe(true);
    const initial = await getResp.json();
    expect(Object.keys(initial).length).toBe(0);

    console.log('Step 2: Create a new setting');
    const createResp = await requestContext.post(`${API_URL}/system/settings`, {
      data: { key: 'test_key', value: 'test_value' }
    });
    expect(createResp.ok()).toBe(true);

    console.log('Step 3: Verify setting persisted');
    const afterCreate = await requestContext.get(`${API_URL}/system/settings`);
    const settings = await afterCreate.json();
    expect(settings.test_key).toBe('test_value');

    console.log('Step 4: Update existing setting');
    const updateResp = await requestContext.post(`${API_URL}/system/settings`, {
      data: { key: 'test_key', value: 'updated_value' }
    });
    expect(updateResp.ok()).toBe(true);

    const afterUpdate = await requestContext.get(`${API_URL}/system/settings`);
    const updated = await afterUpdate.json();
    expect(updated.test_key).toBe('updated_value');

    await requestContext.dispose();
  });

  test('dashboard stats reflect system state', async ({ page }) => {
    const requestContext = await setupRequestContext();
    await configureBackend(requestContext);

    const statsResp = await requestContext.get(`${API_URL}/system/dashboard/stats`);
    expect(statsResp.ok()).toBe(true);
    const stats = await statsResp.json();

    expect(stats.monitored_files_count).toBeDefined();
    expect(stats.total_data_size).toBeDefined();
    expect(stats.media_distribution).toBeDefined();
    expect(stats.media_distribution.LTO).toBeDefined();
    expect(stats.media_distribution.HDD).toBeDefined();

    await requestContext.dispose();
  });

  test('job listing returns empty list initially', async ({ page }) => {
    const requestContext = await setupRequestContext();

    const jobsResp = await requestContext.get(`${API_URL}/system/jobs`);
    expect(jobsResp.ok()).toBe(true);
    const jobs = await jobsResp.json();
    expect(Array.isArray(jobs)).toBe(true);

    const countResp = await requestContext.get(`${API_URL}/system/jobs/count`);
    const count = await countResp.json();
    expect(count.count).toBe(0);

    await requestContext.dispose();
  });

  test('tree endpoint returns source roots', async ({ page }) => {
    const requestContext = await setupRequestContext();
    await configureBackend(requestContext);

    const treeResp = await requestContext.get(`${API_URL}/system/tree`);
    expect(treeResp.ok()).toBe(true);
    const tree = await treeResp.json();
    expect(Array.isArray(tree)).toBe(true);
    expect(tree.length).toBeGreaterThan(0);

    await requestContext.dispose();
  });

  test('host directory listing works', async ({ page }) => {
    const requestContext = await setupRequestContext();

    const lsResp = await requestContext.get(`${API_URL}/system/ls?path=/`);
    expect(lsResp.ok()).toBe(true);
    const dirs = await lsResp.json();
    expect(Array.isArray(dirs)).toBe(true);

    await requestContext.dispose();
  });
});
