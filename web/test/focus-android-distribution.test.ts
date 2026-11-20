import { describe, expect, it, vi } from 'vitest';
import { FocusWebApi } from '../src/focus/api';
import { decodeFocusAndroidChannel } from '../src/focus/httpResponseDecoder';
import { installFocusApiTestHooks, meta, registration } from './focus-api-test-support';

installFocusApiTestHooks();
const release = { package: 'org.focus.mobile', version: '1.2.0', version_code: 3, source_revision: 'a'.repeat(40),
  sha256: 'b'.repeat(64), certificate_sha256: 'c'.repeat(64), size: 12345 };
const channel = { release, checked_at: 123, stale: true };

describe('Android distribution', () => {
  it('checks the selected channel through the registered document on the current instance', async () => {
    const fetchMock = vi.fn(async (path: string) => Response.json(
      path === '/api/client/register' ? registration() : path === '/api/meta' ? meta : channel,
    ));
    window.location.hash = '';
    vi.stubGlobal('fetch', fetchMock);
    const api = new FocusWebApi();
    await api.initialize();
    await expect(api.checkAndroidChannel('main')).resolves.toEqual(channel);
    expect(fetchMock).toHaveBeenLastCalledWith('/api/mobile/android/main/check', expect.objectContaining({
      method: 'POST', body: '{}',
    }));
  });

  it('accepts an unpublished channel and rejects out-of-contract descriptors', () => {
    expect(decodeFocusAndroidChannel({ release: null, checked_at: 0, stale: false })?.release).toBeNull();
    for (const fields of [{ size: 32 * 1024 * 1024 + 1 }, { version_code: -1 }, { package: '../other' },
      { sha256: 'a'.repeat(63) }, { certificate_sha256: 'unknown' }, { source_revision: 'working-tree' },
      { url: 'https://another.example' }]) {
      expect(decodeFocusAndroidChannel({ ...channel, release: { ...release, ...fields } })).toBeNull();
    }
  });
});
