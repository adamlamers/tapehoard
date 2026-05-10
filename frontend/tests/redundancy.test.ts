import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import { API_URL, SOURCE_ROOT, setupRequestContext, configureBackend, triggerScanAndWait } from './helpers';

const HDD_A = '/tmp/tapehoard_e2e_hdd_redundancy_a';
const HDD_B = '/tmp/tapehoard_e2e_hdd_redundancy_b';

async function waitForJobComplete(requestContext: any, jobId: number, timeoutMs = 30000) {
  await expect(async () => {
    const jobResp = await requestContext.get(`${API_URL}/system/jobs/${jobId}`);
    expect(jobResp.ok()).toBe(true);
    const job = await jobResp.json();
    expect(job.status).toBe('COMPLETED');
  }).toPass({ timeout: timeoutMs });
}

async function triggerBackupAndWait(requestContext: any, mediaId: number) {
  const resp = await requestContext.post(`${API_URL}/backups/trigger/${mediaId}`);
  expect(resp.ok()).toBe(true);
  const body = await resp.json();
  await waitForJobComplete(requestContext, body.job_id);
}

async function getFileVersionMediaIds(requestContext: any, filePath: string): Promise<string[]> {
  const metaResp = await requestContext.get(`${API_URL}/archive/metadata`, {
    params: { path: filePath }
  });
  expect(metaResp.ok()).toBe(true);
  const meta = await metaResp.json();
  return (meta.versions as Array<any>).map((v: any) => v.media_id);
}

async function registerHdd(requestContext: any, identifier: string, mountPath: string) {
  const resp = await requestContext.post(`${API_URL}/inventory/media`, {
    data: {
      identifier,
      media_type: 'local_hdd',
      capacity: 10_000_000_000,
      mount_path: mountPath
    }
  });
  expect(resp.ok()).toBe(true);
  const media = await resp.json();
  const initResp = await requestContext.post(`${API_URL}/inventory/media/${media.id}/initialize`);
  expect(initResp.ok()).toBe(true);
  return media;
}

async function setRedundancyTarget(requestContext: any, target: number) {
  const resp = await requestContext.post(`${API_URL}/system/settings`, {
    data: { key: 'redundancy_target', value: String(target) }
  });
  expect(resp.ok()).toBe(true);
}

test.describe('Multiple Redundancy', () => {
  test.beforeEach(async () => {
    fs.mkdirSync(SOURCE_ROOT, { recursive: true });
    fs.mkdirSync(HDD_A, { recursive: true });
    fs.mkdirSync(HDD_B, { recursive: true });
    fs.writeFileSync(path.join(SOURCE_ROOT, 'redundancy_test.txt'), 'redundancy test content');
  });

  test.afterEach(async () => {
    fs.rmSync(HDD_A, { recursive: true, force: true });
    fs.rmSync(HDD_B, { recursive: true, force: true });
  });

  test('redundancy_target setting persists via settings API', async ({}) => {
    const requestContext = await setupRequestContext();

    await setRedundancyTarget(requestContext, 3);

    const getResp = await requestContext.get(`${API_URL}/system/settings`);
    const settings = await getResp.json();
    expect(settings.redundancy_target).toBe('3');

    await requestContext.dispose();
  });

  test('target=1: second backup skips already-covered file', async ({}) => {
    const requestContext = await setupRequestContext();
    await configureBackend(requestContext);
    await setRedundancyTarget(requestContext, 1);

    const mediaA = await registerHdd(requestContext, 'REDUND_HDD_A1', HDD_A);
    const mediaB = await registerHdd(requestContext, 'REDUND_HDD_B1', HDD_B);

    await triggerScanAndWait(requestContext);

    const filePath = path.join(SOURCE_ROOT, 'redundancy_test.txt');

    // Backup to A
    await triggerBackupAndWait(requestContext, mediaA.id);

    const afterA = await getFileVersionMediaIds(requestContext, filePath);
    expect(afterA).toContain('REDUND_HDD_A1');

    // Backup to B — file is already at target=1, should not be written again
    await triggerBackupAndWait(requestContext, mediaB.id);

    const afterB = await getFileVersionMediaIds(requestContext, filePath);
    expect(afterB).not.toContain('REDUND_HDD_B1');
    expect(new Set(afterB).has('REDUND_HDD_A1')).toBe(true);

    await requestContext.delete(`${API_URL}/inventory/media/${mediaA.id}`);
    await requestContext.delete(`${API_URL}/inventory/media/${mediaB.id}`);
    await requestContext.dispose();
  });

  test('target=2: file gets backed up to both media', async ({}) => {
    const requestContext = await setupRequestContext();
    await configureBackend(requestContext);
    await setRedundancyTarget(requestContext, 2);

    const mediaA = await registerHdd(requestContext, 'REDUND_HDD_A2', HDD_A);
    const mediaB = await registerHdd(requestContext, 'REDUND_HDD_B2', HDD_B);

    await triggerScanAndWait(requestContext);

    const filePath = path.join(SOURCE_ROOT, 'redundancy_test.txt');

    // First copy to A
    await triggerBackupAndWait(requestContext, mediaA.id);

    const afterA = await getFileVersionMediaIds(requestContext, filePath);
    expect(afterA).toContain('REDUND_HDD_A2');

    // Second copy to B — target=2, file still needs one more copy
    await triggerBackupAndWait(requestContext, mediaB.id);

    const afterB = await getFileVersionMediaIds(requestContext, filePath);
    expect(afterB).toContain('REDUND_HDD_A2');
    expect(afterB).toContain('REDUND_HDD_B2');

    await requestContext.delete(`${API_URL}/inventory/media/${mediaA.id}`);
    await requestContext.delete(`${API_URL}/inventory/media/${mediaB.id}`);
    await requestContext.dispose();
  });

  test('marking media FAILED reduces redundancy in insights', async ({}) => {
    const requestContext = await setupRequestContext();
    await configureBackend(requestContext);
    await setRedundancyTarget(requestContext, 2);

    const mediaA = await registerHdd(requestContext, 'REDUND_HDD_AF', HDD_A);
    const mediaB = await registerHdd(requestContext, 'REDUND_HDD_BF', HDD_B);

    await triggerScanAndWait(requestContext);

    // Backup to both
    await triggerBackupAndWait(requestContext, mediaA.id);
    await triggerBackupAndWait(requestContext, mediaB.id);

    const filePath = path.join(SOURCE_ROOT, 'redundancy_test.txt');
    const mediaIds = await getFileVersionMediaIds(requestContext, filePath);
    expect(mediaIds).toContain('REDUND_HDD_AF');
    expect(mediaIds).toContain('REDUND_HDD_BF');

    // Insights should show at least some files with 2 copies
    const beforeInsights = await requestContext.get(`${API_URL}/inventory/insights`);
    const beforeData = await beforeInsights.json();
    const before2copies = (beforeData.redundancy as Array<any>).find((r: any) => r.copies === 2);
    expect(before2copies).toBeDefined();
    expect(before2copies.file_count).toBeGreaterThan(0);

    // Mark media A as FAILED — should purge its coverage rows
    const failResp = await requestContext.patch(`${API_URL}/inventory/media/${mediaA.id}`, {
      data: { status: 'FAILED' }
    });
    expect(failResp.ok()).toBe(true);

    // Insights should now show files at 1 copy (coverage dropped)
    const afterInsights = await requestContext.get(`${API_URL}/inventory/insights`);
    const afterData = await afterInsights.json();
    const after1copy = (afterData.redundancy as Array<any>).find((r: any) => r.copies === 1);
    expect(after1copy).toBeDefined();
    expect(after1copy.file_count).toBeGreaterThan(0);

    await requestContext.delete(`${API_URL}/inventory/media/${mediaA.id}`);
    await requestContext.delete(`${API_URL}/inventory/media/${mediaB.id}`);
    await requestContext.dispose();
  });

  test('raising redundancy_target from 1 to 2 makes file a backup candidate again', async ({}) => {
    const requestContext = await setupRequestContext();
    await configureBackend(requestContext);
    await setRedundancyTarget(requestContext, 1);

    const mediaA = await registerHdd(requestContext, 'REDUND_HDD_AR', HDD_A);
    const mediaB = await registerHdd(requestContext, 'REDUND_HDD_BR', HDD_B);

    await triggerScanAndWait(requestContext);

    const filePath = path.join(SOURCE_ROOT, 'redundancy_test.txt');

    // Backup at target=1, satisfied after first backup
    await triggerBackupAndWait(requestContext, mediaA.id);

    const afterA = await getFileVersionMediaIds(requestContext, filePath);
    expect(afterA).toContain('REDUND_HDD_AR');

    // Raise target to 2
    await setRedundancyTarget(requestContext, 2);

    // Now backup to B — file should be a candidate again (needs 2nd copy)
    await triggerBackupAndWait(requestContext, mediaB.id);

    const afterB = await getFileVersionMediaIds(requestContext, filePath);
    expect(afterB).toContain('REDUND_HDD_AR');
    expect(afterB).toContain('REDUND_HDD_BR');

    await requestContext.delete(`${API_URL}/inventory/media/${mediaA.id}`);
    await requestContext.delete(`${API_URL}/inventory/media/${mediaB.id}`);
    await requestContext.dispose();
  });
});
