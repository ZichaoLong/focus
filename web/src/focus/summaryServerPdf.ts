import { FOCUS_WEB_ENDPOINTS, focusWebEndpointPath, isFocusWebWireEnum, hasFocusWebRequiredFields, type FocusWebWireEnum } from './focusWire.generated';

import { isFocusWireRecord } from './projectionEventDecoder';

export interface PdfPreview { id: string; csrf: string }
export type SummaryExportBlob = Blob & { pdfPreview?: PdfPreview };
const previewId = new RegExp('^[0-9a-f]{32}$');
export function isPdfPreview(value: unknown): value is PdfPreview {
  const p = value as Partial<PdfPreview> | null;
  return !!p && typeof p.id === 'string' && previewId.test(p.id)
    && typeof p.csrf === 'string' && p.csrf.length > 0 && p.csrf.length < 1024;
}
export interface PdfWarning { kind: FocusWebWireEnum<'pdf_warning'>; round?: number; code?: string; count?: number }
export interface PdfStatus {
  phase: FocusWebWireEnum<'pdf_phase'> | 'reconnecting'; error?: string; engine?: FocusWebWireEnum<'pdf_engine'>; done?: number; total?: number; warnings?: PdfWarning[];
}
function count(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}
function isStatus(value: unknown): value is PdfStatus {
  return isFocusWireRecord(value) && hasFocusWebRequiredFields('pdf_job', value)
    && isFocusWebWireEnum('pdf_phase', value.phase) && count(value.done) && count(value.total)
    && (value.engine === undefined ? value.phase !== 'ready' : isFocusWebWireEnum('pdf_engine', value.engine))
    && Array.isArray(value.warnings) && value.warnings.length <= 101 && value.warnings.every(w =>
      isFocusWireRecord(w) && hasFocusWebRequiredFields('pdf_warning', w) && isFocusWebWireEnum('pdf_warning', w.kind)
      && (w.round === undefined || count(w.round)) && (w.code === undefined || typeof w.code === 'string')
      && (w.count === undefined || count(w.count)));
}
export class PdfRequestError extends Error {
  constructor(readonly reason: 'expired' | 'queue' | 'network' | 'render' | 'timeout' | 'save') { super(reason); }
}
export function pdfJobId(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('');
}
function delay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    signal.throwIfAborted();
    const cancel = () => { clearTimeout(timer); reject(signal.reason); };
    const timer = setTimeout(() => { signal.removeEventListener('abort', cancel); resolve(); }, ms);
    signal.addEventListener('abort', cancel, { once: true });
  });
}

export async function fetchSummaryPdf(ticket: PdfPreview, jobId: string, title: string, lang: string,
  signal: AbortSignal, report: (status: PdfStatus) => void): Promise<{ response: Response; status: PdfStatus }> {
  const params = { preview_id: ticket.id, job_id: jobId };
  type Endpoint = 'pdf_job_start' | 'pdf_job_status' | 'pdf_job_file';
  async function request(endpoint: Endpoint, offset = 0): Promise<Response> {
    for (let failures = 0; ; failures++) {
      signal.throwIfAborted();
      const start = endpoint === 'pdf_job_start';
      let res: Response | undefined;
      try {
        res = await fetch(focusWebEndpointPath(endpoint, params), {
          credentials: 'same-origin', cache: 'no-store', method: FOCUS_WEB_ENDPOINTS[endpoint].method, signal,
          ...(offset > 0 && { headers: { Range: 'bytes=' + offset + '-' } }),
          ...(start && { headers: { 'Content-Type': 'application/json', 'X-Focus-Web-Csrf': ticket.csrf },
            body: JSON.stringify({ title, lang }) }),
        });
      } catch { signal.throwIfAborted(); }
      if (res?.ok) return res;
      if (res && [401, 403, 404, 410].includes(res.status)) throw new PdfRequestError('expired');
      if (res?.status === 429) throw new PdfRequestError('queue');
      if (res && res.status < 500) throw new PdfRequestError('render');
      if (failures === 8) throw new PdfRequestError('network');
      report({ phase: 'reconnecting' });
      await delay(Math.min(500 * 2 ** failures, 4000), signal);
    }
  }
  async function readStatus(endpoint: 'pdf_job_start' | 'pdf_job_status'): Promise<PdfStatus> {
    for (let attempt = 0; ; attempt++) {
      const res = await request(endpoint);
      try {
        const state = await res.json();
        if (!isStatus(state)) throw new PdfRequestError('render');
        return state;
      } catch (error) {
        signal.throwIfAborted();
        if (error instanceof PdfRequestError) throw error;
        if (attempt >= 3) throw new PdfRequestError('network');
        report({ phase: 'reconnecting' });
        await delay(750, signal);
      }
    }
  }
  let state = await readStatus('pdf_job_start');
  while (state.phase !== 'ready') {
    if (state.phase === 'failed') throw new PdfRequestError(state.error === 'timeout' ? 'timeout' : 'render');
    report(state);
    await delay(650, signal);
    state = await readStatus('pdf_job_status');
  }
  async function file(offset: number): Promise<Response> {
    const res = await request('pdf_job_file', offset);
    if (res.headers.get('Content-Type')?.split(';')[0] !== 'application/pdf' || !res.body) throw new PdfRequestError('render');
    return res;
  }
  const first = await file(0);
  const length = Number(first.headers.get('Content-Length')) || 0;
  let received = 0, retries = 0;
  let reader = first.body!.getReader();
  const stream = new ReadableStream<Uint8Array>({
    async pull(controller) {
      for (;;) {
        try {
          const chunk = await reader.read();
          if (!chunk.done) { received += chunk.value.byteLength; controller.enqueue(chunk.value); return; }
          if (length && received !== length) throw new PdfRequestError('network');
          reader.releaseLock();
          controller.close();
          return;
        } catch {
          signal.throwIfAborted();
          reader.releaseLock();
          if (++retries > 3) throw new PdfRequestError('network');
          report({ phase: 'reconnecting' });
          await delay(750, signal);
          const next = await file(received);
          if (received && (!length || next.status !== 206
            || next.headers.get('Content-Range') !== 'bytes ' + received + '-' + (length - 1) + '/' + length)) {
            await next.body!.cancel();
            throw new PdfRequestError('network');
          }
          reader = next.body!.getReader();
          report(state);
        }
      }
    },
    async cancel() { await reader.cancel().catch(() => {}); },
  });
  report(state);
  return { response: new Response(stream, { headers: first.headers }), status: state };
}
