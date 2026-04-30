import { expect, request } from '@playwright/test';

export const API_URL = 'http://localhost:8001';
export const SOURCE_ROOT = '/tmp/tapehoard_e2e_source';
export const MOCK_LTO_PATH = '/tmp/tapehoard_e2e_mock_lto';
export const RESTORE_DEST = '/tmp/tapehoard_e2e_restore';

/**
 * Creates a request context and resets the test environment.
 * Call dispose() on the returned context when done.
 */
export async function setupRequestContext() {
  const requestContext = await request.newContext();
  const resetResponse = await requestContext.post(`${API_URL}/system/test/reset`);
  if (!resetResponse.ok()) {
    console.error('Failed to reset test environment');
  }
  return requestContext;
}

/**
 * Waits for a scan job to complete by polling /system/scan/status.
 */
export async function waitForScanComplete(requestContext: any, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const statusResp = await requestContext.get(`${API_URL}/system/scan/status`);
    const status = await statusResp.json();
    if (!status.is_running) {
      return;
    }
    await new Promise(r => setTimeout(r, 500));
  }
  throw new Error('Scan did not complete within timeout');
}

/**
 * Configures the source roots and restore destinations.
 */
export async function configureBackend(requestContext: any) {
  await requestContext.post(`${API_URL}/system/settings`, {
    data: { key: 'source_roots', value: JSON.stringify([SOURCE_ROOT]) }
  });
  await requestContext.post(`${API_URL}/system/settings`, {
    data: { key: 'restore_destinations', value: JSON.stringify([RESTORE_DEST]) }
  });
}
