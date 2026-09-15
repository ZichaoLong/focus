import { describe, expect, it, vi } from 'vitest';
import { FocusWebApi } from '../src/focus/api';
import {
  installFocusApiTestHooks,
  meta,
  registration,
} from './focus-api-test-support';


installFocusApiTestHooks();

describe('Focus current-thread data export API', () => {
  it('downloads JSONL through the catalogued authenticated route', async () => {
    window.location.hash = '';
    const jsonl = '{"threadId":"thread-1","turnId":"turn-1","item":{"id":"item-1","type":"commandExecution"}}\n';
    const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
      if (path === '/api/client/register') {
        return new Response(JSON.stringify(registration()), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (path === '/api/meta') {
        return new Response(JSON.stringify(meta), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      expect(path).toBe('/api/threads/thread-1/export-data');
      expect(options?.method).toBe('GET');
      expect(options?.headers).toMatchObject({
        'X-Focus-Web-Client': expect.any(String),
        'X-Focus-Web-Document': expect.any(String),
      });
      return new Response(jsonl, {
        status: 200,
        headers: { 'Content-Type': 'application/x-ndjson; charset=utf-8' },
      });
    });
    vi.stubGlobal('fetch', fetchMock);
    const api = new FocusWebApi();
    await api.initialize();

    const blob = await api.exportThreadData('thread-1');

    expect(await blob.text()).toBe(jsonl);
  });
});
