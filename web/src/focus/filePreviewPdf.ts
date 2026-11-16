/** Loaded only by an opened PDF preview. The document never supplies asset URLs. */
import { getDocument, GlobalWorkerOptions, version } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

export { PasswordResponses, TextLayer } from 'pdfjs-dist';
export const PDF_CANVAS_PIXELS = 12_000_000;

export function loadPreviewPdf(bytes: Uint8Array<ArrayBuffer>) {
  GlobalWorkerOptions.workerSrc = workerUrl;
  const base = new URL(`${import.meta.env.BASE_URL}pdfjs/${version}/`, location.href).href;
  return getDocument({
    // PDF.js transfers its buffer to the worker. Keep the read owner's bytes
    // intact for the lifetime of the preview, including download overlays.
    data: bytes.slice(), cMapUrl: `${base}cmaps/`, cMapPacked: true,
    standardFontDataUrl: `${base}standard_fonts/`, wasmUrl: `${base}wasm/`,
    useWorkerFetch: true, useSystemFonts: false, useWasm: false, enableXfa: false,
    stopAtErrors: true, maxImageSize: 24_000_000, canvasMaxAreaInBytes: PDF_CANVAS_PIXELS * 4,
  });
}
