import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import { API_URL, SOURCE_ROOT, setupRequestContext, triggerScanAndWait } from './helpers';

test.describe('Exclusion Policy', () => {
  test.beforeEach(async () => {
    fs.mkdirSync(SOURCE_ROOT, { recursive: true });
    fs.mkdirSync(path.join(SOURCE_ROOT, 'docs'), { recursive: true });
    fs.mkdirSync(path.join(SOURCE_ROOT, 'temp'), { recursive: true });
    fs.writeFileSync(path.join(SOURCE_ROOT, 'readme.txt'), 'hello');
    fs.writeFileSync(path.join(SOURCE_ROOT, 'notes.txt'), 'world');
    fs.writeFileSync(path.join(SOURCE_ROOT, 'data.tmp'), 'temp1');
    fs.writeFileSync(path.join(SOURCE_ROOT, 'cache.tmp'), 'temp2');
    fs.writeFileSync(path.join(SOURCE_ROOT, 'docs', 'guide.txt'), 'guide');
    fs.writeFileSync(path.join(SOURCE_ROOT, 'docs', 'draft.tmp'), 'draft');
    fs.writeFileSync(path.join(SOURCE_ROOT, 'temp', 'scratch.tmp'), 'scratch');
  });

  test('global exclusions mark matching files as ignored', async ({ page }) => {
    const requestContext = await setupRequestContext();

    await requestContext.post(`${API_URL}/system/settings`, {
      data: { key: 'source_roots', value: JSON.stringify([SOURCE_ROOT]) }
    });
    await requestContext.post(`${API_URL}/system/settings`, {
      data: { key: 'global_exclusions', value: '*.tmp\n' }
    });

    await triggerScanAndWait(requestContext);

    const browseResp = await requestContext.get(
      `${API_URL}/system/browse?path=${SOURCE_ROOT}`
    );
    const browseData = await browseResp.json();
    const files = (browseData as any).files;

    const tmpFiles = (files as Array<any>).filter((f: any) => f.name.endsWith('.tmp'));
    const txtFiles = (files as Array<any>).filter((f: any) => f.name.endsWith('.txt'));

    expect(tmpFiles.length).toBeGreaterThan(0);
    tmpFiles.forEach((f: any) => {
      expect(f.ignored, `expected ${f.name} to be ignored`).toBe(true);
    });

    txtFiles.forEach((f: any) => {
      expect(f.ignored, `expected ${f.name} to NOT be ignored`).toBe(false);
    });

    await requestContext.dispose();
  });

  test('manual include overrides global exclusion', async ({ page }) => {
    const requestContext = await setupRequestContext();

    await requestContext.post(`${API_URL}/system/settings`, {
      data: { key: 'source_roots', value: JSON.stringify([SOURCE_ROOT]) }
    });
    await requestContext.post(`${API_URL}/system/settings`, {
      data: { key: 'global_exclusions', value: '*.tmp\n' }
    });

    // Include one specific .tmp file despite the global exclusion
    await requestContext.post(`${API_URL}/system/track/batch`, {
      data: {
        tracks: [path.join(SOURCE_ROOT, 'data.tmp')],
        untracks: []
      }
    });

    await triggerScanAndWait(requestContext);

    const browseResp = await requestContext.get(
      `${API_URL}/system/browse?path=${SOURCE_ROOT}`
    );
    const browseData = await browseResp.json();
    const files = (browseData as any).files;

    const dataTmp = (files as Array<any>).find((f: any) => f.name === 'data.tmp');
    const cacheTmp = (files as Array<any>).find((f: any) => f.name === 'cache.tmp');

    expect(dataTmp).toBeDefined();
    expect(dataTmp.ignored).toBe(false);

    expect(cacheTmp).toBeDefined();
    expect(cacheTmp.ignored).toBe(true);

    await requestContext.dispose();
  });

  test('updating global exclusions recomputes existing indexed files', async ({ page }) => {
    const requestContext = await setupRequestContext();

    await requestContext.post(`${API_URL}/system/settings`, {
      data: { key: 'source_roots', value: JSON.stringify([SOURCE_ROOT]) }
    });
    // No exclusions initially
    await requestContext.post(`${API_URL}/system/settings`, {
      data: { key: 'global_exclusions', value: '' }
    });

    await triggerScanAndWait(requestContext);

    // Verify nothing is ignored before exclusions are set
    const browseBefore = await requestContext.get(
      `${API_URL}/system/browse?path=${SOURCE_ROOT}`
    );
    const beforeData = await browseBefore.json();
    const beforeFiles = (beforeData as any).files as Array<any>;
    beforeFiles.forEach((f: any) => {
      expect(f.ignored, `expected ${f.name} to NOT be ignored before policy`).toBe(false);
    });

    // Now apply global exclusions — should recompute without requiring a new scan
    await requestContext.post(`${API_URL}/system/settings`, {
      data: { key: 'global_exclusions', value: '*.tmp\n' }
    });

    const browseAfter = await requestContext.get(
      `${API_URL}/system/browse?path=${SOURCE_ROOT}`
    );
    const afterData = await browseAfter.json();
    const afterFiles = (afterData as any).files as Array<any>;

    const tmpAfter = afterFiles.filter((f: any) => f.name.endsWith('.tmp'));
    const txtAfter = afterFiles.filter((f: any) => f.name.endsWith('.txt'));

    tmpAfter.forEach((f: any) => {
      expect(f.ignored, `expected ${f.name} to be ignored after policy update`).toBe(true);
    });
    txtAfter.forEach((f: any) => {
      expect(f.ignored, `expected ${f.name} to NOT be ignored after policy update`).toBe(false);
    });

    await requestContext.dispose();
  });

  test('exclusion preview returns correct counts and sample', async ({ page }) => {
    const requestContext = await setupRequestContext();

    await requestContext.post(`${API_URL}/system/settings`, {
      data: { key: 'source_roots', value: JSON.stringify([SOURCE_ROOT]) }
    });

    await triggerScanAndWait(requestContext);

    const previewResp = await requestContext.post(`${API_URL}/system/settings/test-exclusions`, {
      data: { patterns: '*.tmp', limit: 10 }
    });
    expect(previewResp.ok()).toBe(true);
    const preview = await previewResp.json();

    expect(preview.total_files).toBeGreaterThan(0);
    expect(preview.matched_count).toBeGreaterThan(0);
    expect(preview.matched_size).toBeGreaterThanOrEqual(0);
    expect(Array.isArray(preview.sample)).toBe(true);
    expect(preview.sample.length).toBeGreaterThan(0);
    expect(preview.sample.length).toBeLessThanOrEqual(10);

    preview.sample.forEach((s: any) => {
      expect(s.name.endsWith('.tmp')).toBe(true);
      expect(s.path).toBeDefined();
      expect(s.size).toBeDefined();
    });

    await requestContext.dispose();
  });

  test('exclusion preview with no patterns returns empty result', async ({ page }) => {
    const requestContext = await setupRequestContext();

    await requestContext.post(`${API_URL}/system/settings`, {
      data: { key: 'source_roots', value: JSON.stringify([SOURCE_ROOT]) }
    });

    await triggerScanAndWait(requestContext);

    const previewResp = await requestContext.post(`${API_URL}/system/settings/test-exclusions`, {
      data: { patterns: '', limit: 10 }
    });
    expect(previewResp.ok()).toBe(true);
    const preview = await previewResp.json();

    expect(preview.total_files).toBe(0);
    expect(preview.matched_count).toBe(0);
    expect(preview.matched_size).toBe(0);
    expect(preview.sample).toEqual([]);

    await requestContext.dispose();
  });

  test('exclusion CSV download contains matched files', async ({ page }) => {
    const requestContext = await setupRequestContext();

    await requestContext.post(`${API_URL}/system/settings`, {
      data: { key: 'source_roots', value: JSON.stringify([SOURCE_ROOT]) }
    });

    await triggerScanAndWait(requestContext);

    const downloadResp = await requestContext.post(
      `${API_URL}/system/settings/test-exclusions/download`,
      { data: { patterns: '*.tmp' } }
    );
    expect(downloadResp.ok()).toBe(true);

    const contentType = downloadResp.headers()['content-type'];
    expect(contentType).toContain('text/csv');

    const body = await downloadResp.text();
    expect(body).toContain('path,size,mtime,sha256_hash');
    expect(body).toContain('.tmp');

    const lines = body.trim().split('\n');
    expect(lines.length).toBeGreaterThan(1); // header + at least one row

    await requestContext.dispose();
  });

  test('directory-level global exclusion ignores nested files', async ({ page }) => {
    const requestContext = await setupRequestContext();

    await requestContext.post(`${API_URL}/system/settings`, {
      data: { key: 'source_roots', value: JSON.stringify([SOURCE_ROOT]) }
    });
    await requestContext.post(`${API_URL}/system/settings`, {
      data: { key: 'global_exclusions', value: 'temp/\n' }
    });

    await triggerScanAndWait(requestContext);

    const browseRoot = await requestContext.get(
      `${API_URL}/system/browse?path=${SOURCE_ROOT}`
    );
    const rootData = await browseRoot.json();
    const rootFiles = (rootData as any).files as Array<any>;

    const tempDir = rootFiles.find((f: any) => f.name === 'temp');
    expect(tempDir).toBeDefined();
    expect(tempDir.ignored).toBe(true);

    // Files inside temp should also be ignored
    const browseTemp = await requestContext.get(
      `${API_URL}/system/browse?path=${path.join(SOURCE_ROOT, 'temp')}`
    );
    const tempData = await browseTemp.json();
    const tempFiles = (tempData as any).files as Array<any>;
    tempFiles.forEach((f: any) => {
      expect(f.ignored, `expected ${f.name} inside temp/ to be ignored`).toBe(true);
    });

    // Files outside temp should NOT be ignored
    const readme = rootFiles.find((f: any) => f.name === 'readme.txt');
    expect(readme).toBeDefined();
    expect(readme.ignored).toBe(false);

    await requestContext.dispose();
  });
});
