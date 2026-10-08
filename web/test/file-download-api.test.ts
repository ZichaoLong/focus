import { describe, expect, it, vi } from 'vitest';
import { FocusWebApi } from '../src/focus/api';
import { decodeFocusFileInfo } from '../src/focus/httpResponseDecoder';
import { installFocusApiTestHooks, meta, registration } from './focus-api-test-support';

installFocusApiTestHooks();

describe('single-file transport', () => {
  it('encodes exact server paths and save names without credentials in download URLs', async () => {
    window.location.hash = '';
    const signal = new AbortController().signal;
    const path = '/work/报告 #1?.pdf';
    const file = { path, name: '报告 #1?.pdf', size: 3 };
    const body = new Response(new Uint8Array([0, 255, 1]), { headers: { 'Content-Type': 'application/octet-stream' } });
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/client/register') return Response.json(registration());
      if (url === '/api/meta') return Response.json(meta);
      const parsed = new URL(url, 'http://localhost');
      expect(parsed.searchParams.get('path')).toBe(path);
      expect(init?.credentials).toBe('same-origin');
      expect(init?.signal).toBe(signal);
      if (parsed.pathname === '/api/files/info') return Response.json(file);
      expect(parsed.pathname).toBe('/api/files/download');
      return body;
    });
    vi.stubGlobal('fetch', fetchMock);
    const api = new FocusWebApi();
    await api.initialize();
    expect(await api.fileInfo(path, '/work', signal)).toEqual(file);
    expect(await api.fileContent(path, signal)).toBe(body);
    expect(body.bodyUsed).toBe(false);
    const url = new URL(api.fileDownloadUrl(path, '我的报告.pdf'), 'http://localhost');
    expect([...url.searchParams.keys()]).toEqual(['path', 'filename']);
    expect(url.searchParams.get('filename')).toBe('我的报告.pdf');
  });

  it('rejects login/proxy HTML without presenting it as file content', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>Login</html>', { headers: { 'Content-Type': 'text/html' } })));
    await expect(new FocusWebApi().fileContent('/a', new AbortController().signal)).rejects.toMatchObject({ code: 'invalid_gateway_response' });
  });

  it('preserves actionable HTTP file errors', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ error: { code: 'file_not_found', message: 'missing' } }, { status: 404 })));
    await expect(new FocusWebApi().fileContent('/a', new AbortController().signal)).rejects.toMatchObject({ code: 'file_not_found', status: 404 });
  });

  it.each([
    { path: '/a', name: 'a', size: -1 },
    { path: '/a', name: 'a', size: Number.MAX_SAFE_INTEGER + 1 },
    { path: '', name: 'a', size: 1 },
    { path: '/a', name: '../a', size: 1 },
    { path: '/a', name: 'a', size: 1, content: 'unexpected body' },
  ])('rejects malformed metadata: %j', value => {
    expect(decodeFocusFileInfo(value)).toBeNull();
  });
});
