import { describe, expect, it, vi } from 'vitest';
import { FocusWebApi } from '../src/focus/api';
import { installFocusApiTestHooks, meta, registration } from './focus-api-test-support';

installFocusApiTestHooks();

describe('Focus update API', () => {
  it('classifies an update admission refusal as pre-effect', async () => {
    window.location.hash = '';
    const fetchMock = vi.fn(async (path: string) => {
      const payload = path === '/api/client/register'
        ? registration()
        : path === '/api/meta'
          ? meta
          : { error: { code: 'update_rejected', message: 'operation is no longer ready' } };
      return new Response(JSON.stringify(payload), {
        status: path.startsWith('/api/update') ? 409 : 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });
    vi.stubGlobal('fetch', fetchMock);
    const api = new FocusWebApi();
    await api.initialize();

    await expect(api.applyUpdate('a'.repeat(32), 'a'.repeat(32))).rejects.toMatchObject({
      code: 'update_rejected', effectEvidence: 'pre_effect',
    });
  });
});
