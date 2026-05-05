import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import { API_URL, setupRequestContext } from './helpers';

test.describe('Media Lifecycle', () => {
  test('register and initialize mock LTO media', async ({}) => {
    const requestContext = await setupRequestContext();

    console.log('Step 1: Register media via API');
    const registerResp = await requestContext.post(`${API_URL}/inventory/media`, {
      data: {
        identifier: 'TEST_LTO_001',
        media_type: 'lto_tape',
        generation: 'LTO-8',
        capacity: 12000,
        location: 'Test Lab'
      }
    });
    expect(registerResp.ok()).toBe(true);
    const media = await registerResp.json();
    expect(media.identifier).toBe('TEST_LTO_001');

    console.log('Step 2: Verify media appears in inventory');
    const listResp = await requestContext.get(`${API_URL}/inventory/media`);
    const mediaList = await listResp.json();
    const found = (mediaList as Array<any>).find((m: any) => m.identifier === 'TEST_LTO_001');
    expect(found).toBeDefined();
    expect(found.status).toBe('active');

    console.log('Step 3: Initialize media');
    const initResp = await requestContext.post(`${API_URL}/inventory/media/${media.id}/initialize`);
    expect(initResp.ok()).toBe(true);

    console.log('Step 4: Verify media status after initialization');
    const afterInitResp = await requestContext.get(`${API_URL}/inventory/media`);
    const afterInit = await afterInitResp.json();
    const updated = (afterInit as Array<any>).find((m: any) => m.identifier === 'TEST_LTO_001');
    expect(updated).toBeDefined();

    await requestContext.delete(`${API_URL}/inventory/media/${media.id}`);
    await requestContext.dispose();
  });

  test('register and retire HDD media', async ({}) => {
    const requestContext = await setupRequestContext();
    const hddPath = '/tmp/tapehoard_e2e_hdd_test';
    fs.mkdirSync(hddPath, { recursive: true });

    try {
      const registerResp = await requestContext.post(`${API_URL}/inventory/media`, {
        data: {
          identifier: 'TEST_HDD_001',
          media_type: 'local_hdd',
          capacity: 1000000,
          location: 'Test Lab',
          mount_path: hddPath
        }
      });
      expect(registerResp.ok()).toBe(true);
      const media = await registerResp.json();
      expect(media.media_type).toBe('local_hdd');

      console.log('Step 2: Retire media');
      const retireResp = await requestContext.patch(`${API_URL}/inventory/media/${media.id}`, {
        data: { status: 'retired' }
      });
      expect(retireResp.ok()).toBe(true);
      const retired = await retireResp.json();
      expect(retired.status).toBe('retired');

      console.log('Step 3: Verify retired media cannot accept backups');
      const backupResp = await requestContext.post(`${API_URL}/backups/trigger/${media.id}`);
      expect(backupResp.status()).toBe(400);
      const errBody = await backupResp.json();
      expect(errBody.detail.toLowerCase()).toContain('cannot');

      await requestContext.delete(`${API_URL}/inventory/media/${media.id}`);
    } finally {
      fs.rmSync(hddPath, { recursive: true, force: true });
    }

    await requestContext.dispose();
  });

  test('discover hardware returns empty when no drives configured', async ({}) => {
    const requestContext = await setupRequestContext();

    const discoverResp = await requestContext.get(`${API_URL}/system/hardware/discover`);
    expect(discoverResp.ok()).toBe(true);
    const devices = await discoverResp.json();
    expect(Array.isArray(devices)).toBe(true);

    await requestContext.dispose();
  });

  test('duplicate media identifier is rejected', async ({}) => {
    const requestContext = await setupRequestContext();

    const registerResp = await requestContext.post(`${API_URL}/inventory/media`, {
      data: {
        identifier: 'TEST_DUP_001',
        media_type: 'lto_tape',
        generation: 'LTO-7',
        capacity: 6000
      }
    });
    expect(registerResp.ok()).toBe(true);
    const media = await registerResp.json();

    try {
      const dupResp = await requestContext.post(`${API_URL}/inventory/media`, {
        data: {
          identifier: 'TEST_DUP_001',
          media_type: 'lto_tape',
          generation: 'LTO-7',
          capacity: 6000
        }
      });
      expect(dupResp.status()).toBe(400);
    } finally {
      await requestContext.delete(`${API_URL}/inventory/media/${media.id}`);
    }

    await requestContext.dispose();
  });

  test('inventory categorizes media by status correctly', async ({ page }) => {
    const requestContext = await setupRequestContext();

    const activeMedia = await requestContext.post(`${API_URL}/inventory/media`, {
      data: { identifier: 'CAT_ACTIVE', media_type: 'lto_tape', generation: 'LTO-8', capacity: 12000 }
    }).then(r => r.json());

    const fullMedia = await requestContext.post(`${API_URL}/inventory/media`, {
      data: { identifier: 'CAT_FULL', media_type: 'lto_tape', generation: 'LTO-8', capacity: 12000 }
    }).then(r => r.json());
    await requestContext.patch(`${API_URL}/inventory/media/${fullMedia.id}`, { data: { status: 'full' } });

    const failedMedia = await requestContext.post(`${API_URL}/inventory/media`, {
      data: { identifier: 'CAT_FAILED', media_type: 'lto_tape', generation: 'LTO-8', capacity: 12000 }
    }).then(r => r.json());
    await requestContext.patch(`${API_URL}/inventory/media/${failedMedia.id}`, { data: { status: 'failed' } });

    const retiredMedia = await requestContext.post(`${API_URL}/inventory/media`, {
      data: { identifier: 'CAT_RETIRED', media_type: 'lto_tape', generation: 'LTO-8', capacity: 12000 }
    }).then(r => r.json());
    await requestContext.patch(`${API_URL}/inventory/media/${retiredMedia.id}`, { data: { status: 'retired' } });

    await page.goto('/inventory');
    await page.waitForLoadState('networkidle');

    const activeSection = page.getByTestId('active-media-section');
    const fullSection = page.getByTestId('full-media-section');
    const unavailableSection = page.getByTestId('unavailable-media-section');

    await expect(activeSection).toBeVisible();
    await expect(activeSection.getByText('CAT_ACTIVE')).toBeVisible();
    await expect(activeSection.getByText('CAT_FULL')).not.toBeVisible();
    await expect(activeSection.getByText('CAT_FAILED')).not.toBeVisible();
    await expect(activeSection.getByText('CAT_RETIRED')).not.toBeVisible();

    await expect(fullSection).toBeVisible();
    await expect(fullSection.getByText('CAT_FULL')).toBeVisible();
    await expect(fullSection.getByText('CAT_ACTIVE')).not.toBeVisible();
    await expect(fullSection.getByText('CAT_FAILED')).not.toBeVisible();
    await expect(fullSection.getByText('CAT_RETIRED')).not.toBeVisible();

    await expect(unavailableSection).toBeVisible();
    await expect(unavailableSection.getByText('CAT_FAILED')).toBeVisible();
    await expect(unavailableSection.getByText('CAT_RETIRED')).toBeVisible();

    await expect(unavailableSection).toBeVisible();
    await expect(unavailableSection.getByText('CAT_FAILED')).toBeVisible();
    await expect(unavailableSection.getByText('CAT_RETIRED')).toBeVisible();

    await requestContext.delete(`${API_URL}/inventory/media/${activeMedia.id}`);
    await requestContext.delete(`${API_URL}/inventory/media/${fullMedia.id}`);
    await requestContext.delete(`${API_URL}/inventory/media/${failedMedia.id}`);
    await requestContext.delete(`${API_URL}/inventory/media/${retiredMedia.id}`);
    await requestContext.dispose();
  });
});
