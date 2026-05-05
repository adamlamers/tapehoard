import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import { API_URL, SOURCE_ROOT, RESTORE_DEST, setupRequestContext, configureBackend, waitForScanComplete } from './helpers';

test.describe('Backup & Restore', () => {
  test.beforeEach(async () => {
    fs.mkdirSync(SOURCE_ROOT, { recursive: true });
    fs.mkdirSync(RESTORE_DEST, { recursive: true });
    fs.writeFileSync(path.join(SOURCE_ROOT, 'backup_test.txt'), 'backup me');
    fs.mkdirSync(path.join(SOURCE_ROOT, 'subdir'), { recursive: true });
    fs.writeFileSync(path.join(SOURCE_ROOT, 'subdir', 'nested.txt'), 'nested content');
  });

  test('backup to specific media works', async ({}) => {
    const requestContext = await setupRequestContext();
    await configureBackend(requestContext);

    const registerResp = await requestContext.post(`${API_URL}/inventory/media`, {
      data: {
        identifier: 'SPECIFIC_TAPE_001',
        media_type: "lto_tape",
        generation: 'LTO-7',
        capacity: 6000
      }
    });
    const media = await registerResp.json();

    const initResp = await requestContext.post(`${API_URL}/inventory/media/${media.id}/initialize`);
    expect(initResp.ok()).toBe(true);

    const scanResp = await requestContext.post(`${API_URL}/system/scan`);
    expect(scanResp.ok()).toBe(true);
    await waitForScanComplete(requestContext);

    const backupResp = await requestContext.post(`${API_URL}/backups/trigger/${media.id}`);
    expect(backupResp.ok()).toBe(true);
    const result = await backupResp.json();
    expect(result.media).toBe('SPECIFIC_TAPE_001');

    await requestContext.delete(`${API_URL}/inventory/media/${media.id}`);
    await requestContext.dispose();
  });

  test('backup fails when no active media', async ({}) => {
    const requestContext = await setupRequestContext();

    const backupResp = await requestContext.post(`${API_URL}/backups/trigger/auto`);
    expect(backupResp.status()).toBe(400);
    const errBody = await backupResp.json();
    expect(errBody.detail.toLowerCase()).toContain('no active media');

    await requestContext.dispose();
  });

  test('add file to restore queue and clear it', async ({}) => {
    const requestContext = await setupRequestContext();
    await configureBackend(requestContext);

    const registerResp = await requestContext.post(`${API_URL}/inventory/media`, {
      data: {
        identifier: 'RESTORE_TAPE_001',
        media_type: "lto_tape",
        generation: 'LTO-8',
        capacity: 12000
      }
    });
    const media = await registerResp.json();
    await requestContext.post(`${API_URL}/inventory/media/${media.id}/initialize`);

    const scanResp = await requestContext.post(`${API_URL}/system/scan`);
    expect(scanResp.ok()).toBe(true);
    await waitForScanComplete(requestContext);

    const backupResp = await requestContext.post(`${API_URL}/backups/trigger/${media.id}`);
    expect(backupResp.ok()).toBe(true);
    await expect(async () => {
      const jobsResp = await requestContext.get(`${API_URL}/system/jobs`);
      const jobs = await jobsResp.json();
      const backupJob = (jobs as Array<any>).find((j: any) => j.job_type === 'BACKUP');
      expect(backupJob).toBeDefined();
      expect(backupJob.status).toBe('COMPLETED');
    }).toPass({ timeout: 30000 });

    const metaResp = await requestContext.get(`${API_URL}/archive/metadata`, {
      params: { path: path.join(SOURCE_ROOT, 'backup_test.txt') }
    });
    expect(metaResp.ok()).toBe(true);
    const meta = await metaResp.json();
    const fileId = meta.id;

    const queueResp = await requestContext.post(`${API_URL}/restores/queue/file/${fileId}`);
    expect(queueResp.ok()).toBe(true);

    const listQueueResp = await requestContext.get(`${API_URL}/restores/queue`);
    const queue = await listQueueResp.json();
    expect((queue as Array<any>).length).toBeGreaterThan(0);

    const clearResp = await requestContext.post(`${API_URL}/restores/queue/clear`);
    expect(clearResp.ok()).toBe(true);

    const afterClearResp = await requestContext.get(`${API_URL}/restores/queue`);
    const afterClear = await afterClearResp.json();
    expect((afterClear as Array<any>).length).toBe(0);

    await requestContext.delete(`${API_URL}/inventory/media/${media.id}`);
    await requestContext.dispose();
  });

  test('deleted file cannot be added to restore queue', async ({}) => {
    const requestContext = await setupRequestContext();
    await configureBackend(requestContext);

    const registerResp = await requestContext.post(`${API_URL}/inventory/media`, {
      data: {
        identifier: 'DELETE_TAPE_001',
        media_type: "lto_tape",
        generation: 'LTO-8',
        capacity: 12000
      }
    });
    const media = await registerResp.json();
    await requestContext.post(`${API_URL}/inventory/media/${media.id}/initialize`);

    const scanResp = await requestContext.post(`${API_URL}/system/scan`);
    expect(scanResp.ok()).toBe(true);
    await waitForScanComplete(requestContext);

    const backupResp = await requestContext.post(`${API_URL}/backups/trigger/${media.id}`);
    expect(backupResp.ok()).toBe(true);
    await expect(async () => {
      const jobsResp = await requestContext.get(`${API_URL}/system/jobs`);
      const jobs = await jobsResp.json();
      const backupJob = (jobs as Array<any>).find((j: any) => j.job_type === 'BACKUP');
      expect(backupJob).toBeDefined();
      expect(backupJob.status).toBe('COMPLETED');
    }).toPass({ timeout: 30000 });

    const metaResp = await requestContext.get(`${API_URL}/archive/metadata`, {
      params: { path: path.join(SOURCE_ROOT, 'backup_test.txt') }
    });
    expect(metaResp.ok()).toBe(true);
    const meta = await metaResp.json();
    const fileId = meta.id;

    const confirmResp = await requestContext.post(`${API_URL}/system/discrepancies/${fileId}/confirm`);
    expect(confirmResp.ok()).toBe(true);

    const queueResp = await requestContext.post(`${API_URL}/restores/queue/file/${fileId}`);
    expect(queueResp.status()).toBe(400);
    const errBody = await queueResp.json();
    expect(errBody.detail.toLowerCase()).toContain('deleted');

    await requestContext.delete(`${API_URL}/inventory/media/${media.id}`);
    await requestContext.dispose();
  });

  test('recovery manifest calculates correctly', async ({}) => {
    const requestContext = await setupRequestContext();
    await configureBackend(requestContext);

    const registerResp = await requestContext.post(`${API_URL}/inventory/media`, {
      data: {
        identifier: 'MANIFEST_TAPE_001',
        media_type: "lto_tape",
        generation: 'LTO-8',
        capacity: 12000
      }
    });
    const media = await registerResp.json();
    await requestContext.post(`${API_URL}/inventory/media/${media.id}/initialize`);

    const scanResp = await requestContext.post(`${API_URL}/system/scan`);
    expect(scanResp.ok()).toBe(true);
    await waitForScanComplete(requestContext);

    const backupResp = await requestContext.post(`${API_URL}/backups/trigger/${media.id}`);
    expect(backupResp.ok()).toBe(true);
    await expect(async () => {
      const jobsResp = await requestContext.get(`${API_URL}/system/jobs`);
      const jobs = await jobsResp.json();
      const backupJob = (jobs as Array<any>).find((j: any) => j.job_type === 'BACKUP');
      expect(backupJob).toBeDefined();
      expect(backupJob.status).toBe('COMPLETED');
    }).toPass({ timeout: 30000 });

    const metaResp = await requestContext.get(`${API_URL}/archive/metadata`, {
      params: { path: path.join(SOURCE_ROOT, 'backup_test.txt') }
    });
    expect(metaResp.ok()).toBe(true);
    const meta = await metaResp.json();

    await requestContext.post(`${API_URL}/restores/queue/file/${meta.id}`);

    const manifestResp = await requestContext.get(`${API_URL}/restores/manifest`);
    expect(manifestResp.ok()).toBe(true);
    const manifest = await manifestResp.json();
    expect(manifest.total_files).toBeGreaterThan(0);
    expect(manifest.media_required.length).toBeGreaterThan(0);

    await requestContext.delete(`${API_URL}/inventory/media/${media.id}`);
    await requestContext.dispose();
  });
});
