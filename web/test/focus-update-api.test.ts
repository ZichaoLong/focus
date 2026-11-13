import { describe, expect, it, vi } from 'vitest';
import { FocusWebApi } from '../src/focus/api';
import { installFocusApiTestHooks, meta, registration } from './focus-api-test-support';

installFocusApiTestHooks();

describe('Focus update API', () => {
  it.each(['cancelling', 'cancelled'] as const)('decodes %s and sends only the exact cancellation ID', async (state) => {
    const operationId = 'b'.repeat(32);
    const fetchMock = vi.fn(async (path: string) => {
      const payload = path === '/api/client/register' ? registration()
        : path === '/api/meta' ? meta : {
          source: { url: 'https://example.com/focus.git', branch: 'main' },
          operation_source: null, operation_id: operationId, target: 'stable', state,
          requested_commit: '', resolved_commit: '', message: '', error: '', preflight: {},
          updated_at: 1, restart_required: false, installation_started: false,
          phase: state, phase_started_at: 1, last_progress_at: 1, progress: null,
        };
      return new Response(JSON.stringify(payload), { status: 200, headers: { 'Content-Type': 'application/json' } });
    });
    window.location.hash = '';
    vi.stubGlobal('fetch', fetchMock);
    const api = new FocusWebApi();
    await api.initialize();
    await expect(api.cancelUpdate(operationId)).resolves.toMatchObject({ state, operation_id: operationId });
    expect(fetchMock).toHaveBeenLastCalledWith('/api/update/cancel', expect.objectContaining({
      method: 'POST', body: JSON.stringify({ operation_id: operationId }),
    }));
  });

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
