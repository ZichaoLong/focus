import { afterEach, expect, it, vi } from 'vitest';
import { fetchSummaryPdf } from '../src/focus/summaryServerPdf';

afterEach(() => vi.unstubAllGlobals());

it('continues a broken authenticated file response at the first missing byte', async () => {
  const encode = (s: string) => new TextEncoder().encode(s);
  let attempt = 0, chunks = 0;
  const phases: string[] = [];
  const fetch = vi.fn(async (_url: string, options: RequestInit) => {
    if (options.method === 'POST') return Response.json({ phase: 'ready', engine: 'basic', warnings: [], done: 0, total: 0 });
    expect(options.credentials).toBe('same-origin');
    if (++attempt === 1) return new Response(new ReadableStream({
      pull(controller) {
        if (!chunks++) controller.enqueue(encode('%PDF-'));
        else controller.error(new Error('disconnected'));
      },
    }), { headers: { 'Content-Type': 'application/pdf', 'Content-Length': '8' } });
    expect(options.headers).toEqual({ Range: 'bytes=5-' });
    return new Response(encode('end'), { status: 206,
      headers: { 'Content-Range': 'bytes 5-7/8', 'Content-Type': 'application/pdf' } });
  });
  vi.stubGlobal('fetch', fetch);
  const result = await fetchSummaryPdf({ id: 'a'.repeat(32), csrf: 'secret' }, 'b'.repeat(32), 'Edited', 'en',
    new AbortController().signal, state => phases.push(state.phase));
  expect(await result.response.text()).toBe('%PDF-end');
  expect(phases).toEqual(['ready', 'reconnecting', 'ready']);
  expect(fetch).toHaveBeenCalledTimes(3);
});
