"""Stateless sandbox document for explicitly opened HTML file previews.

The browser supplies its already-read source over a private MessagePort. No file
paths, sessions, or document contents are retained here. See the file preview contract.
"""

HTML_PREVIEW_CSP = (
    "sandbox allow-scripts; default-src 'none'; base-uri 'none'; "
    "frame-ancestors 'self'; object-src 'none'; frame-src 'none'; "
    "script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "img-src data: blob:; font-src data:; media-src data: blob:; "
    "connect-src 'none'; worker-src 'none'; form-action 'none'"
)

# This bootstrap must run before any file script. The transferred port stays in
# its closure: file scripts cannot forge parent file-open messages through the
# ordinary window message channel, and synthetic clicks never request a file.
HTML_PREVIEW_DOCUMENT = r"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="referrer" content="no-referrer">
<title>HTML preview</title></head><body><script>
(() => {
  'use strict';
  const owner = parent;
  const ownerOrigin = location.origin;
  const doc = document;
  function receive(event) {
    if (event.source !== owner || event.origin !== ownerOrigin
        || event.data?.type !== 'focus-html-preview' || typeof event.data.html !== 'string'
        || event.data.html.length > 8 * 1024 * 1024 || event.ports.length !== 1) return;
    removeEventListener('message', receive);
    const send = event.ports[0].postMessage.bind(event.ports[0]);
    const source = event.data.html;
    const closest = Function.call.bind(Element.prototype.closest);
    const attribute = Function.call.bind(Element.prototype.getAttribute);
    const prevent = Function.call.bind(Event.prototype.preventDefault);
    const stop = Function.call.bind(Event.prototype.stopImmediatePropagation);
    const path = Function.call.bind(Event.prototype.composedPath);
    let reportedResource = false;
    doc.open();
    doc.addEventListener('click', event => {
      const target = path(event)[0];
      if (!(target instanceof Element)) return;
      const link = closest(target, 'a[href], area[href]');
      if (!link) return;
      const href = attribute(link, 'href') || '';
      if (!href || href.startsWith('#')) return;
      prevent(event); stop(event);
      if (event.isTrusted && event.button === 0 && href.length <= 8192) send({type:'link', href});
    }, true);
    doc.addEventListener('securitypolicyviolation', () => {
      if (!reportedResource) { reportedResource = true; send({type:'blocked-resource'}); }
    });
    addEventListener('error', () => send({type:'script-error'}), {once:true});
    doc.write(source);
    doc.close();
    send({type:'rendered'});
  }
  addEventListener('message', receive);
})();
</script></body></html>"""
