import { describe, expect, it, vi } from 'vitest';
import { FocusWebApi } from '../src/focus/api';
import { installFocusApiTestHooks, meta, registration } from './focus-api-test-support';

installFocusApiTestHooks();

describe('Focus Q&A export API', () => {
  it('downloads Q&A Markdown through the catalogued authenticated route', async () => {
    window.location.hash = '';
    const markdown = '# Codex conversation summary\n\n## User\n\nHello\n';
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
      expect(path).toBe('/api/threads/thread-1/export-summary');
      expect(options?.method).toBe('POST');
      expect(JSON.parse(options?.body as string)).toEqual({ scope: 'all', turn_ids: [] });
      expect(options?.headers).toMatchObject({
        'X-Focus-Web-Client': expect.any(String),
        'X-Focus-Web-Document': expect.any(String),
      });
      return new Response(markdown, {
        status: 200,
        headers: { 'Content-Type': 'text/markdown; charset=utf-8' },
      });
    });
    vi.stubGlobal('fetch', fetchMock);
    const api = new FocusWebApi();
    await api.initialize();

    const blob = await api.exportThreadSummary('thread-1');

    expect(await blob.text()).toBe(markdown);
  });

  it('pages export turns independently and posts exact selections with cancellation and CSRF', async () => {
    window.location.hash = '';
    const signal = new AbortController().signal;
    const selection = { scope: 'selected' as const, turn_ids: ['b', 'a'] };
    const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
      if (path === '/api/client/register') return new Response(JSON.stringify(registration()));
      if (path === '/api/meta') return new Response(JSON.stringify(meta));
      expect(options?.signal).toBe(signal);
      if (path === '/api/threads/thread-1/export-turns?cursor=older%2Fpage') {
        expect(options?.method).toBe('GET');
        return new Response(JSON.stringify({ thread_id: 'thread-1', turns: [{ turn_id: 'a', prompt: 'Question', answer: 'Reply', status: 'completed' }], next_cursor: null }));
      }
      expect(path).toBe('/api/threads/thread-1/export-summary');
      expect(options?.method).toBe('POST');
      expect(options?.headers).toMatchObject({ 'Content-Type': 'application/json', 'X-Focus-Web-Csrf': expect.any(String), 'X-Focus-Web-Document': expect.any(String) });
      expect(JSON.parse(options?.body as string)).toEqual(selection);
      return new Response('Selected Q&A', { headers: { 'Content-Type': 'text/markdown' } });
    });
    vi.stubGlobal('fetch', fetchMock);
    const api = new FocusWebApi(); await api.initialize();
    expect((await api.listExportTurns('thread-1', 'older/page', signal)).turns[0]?.turn_id).toBe('a');
    expect(await (await api.exportThreadSummary('thread-1', selection, signal)).text()).toBe('Selected Q&A');
  });

});
