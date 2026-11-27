import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';

/** Private DevTools pipe, with an inert about:blank page and embedded resources. */
export async function printWithBrowser(executable, html, diagramScript, directory) {
  const child = spawn(executable, ['--headless', '--no-first-run', '--disable-extensions',
    '--disable-background-networking', '--disable-component-update', '--no-proxy-server',
    '--user-data-dir=' + directory, '--remote-debugging-pipe', 'about:blank'],
  { stdio: ['ignore', 'ignore', 'ignore', 'pipe', 'pipe'] });
  const pending = new Map();
  let serial = 0, partial = '', closed = false;
  function fail() {
    closed = true;
    for (const { reject } of pending.values()) reject(new Error('Browser disconnected'));
    pending.clear();
  }
  child.on('error', fail);
  child.on('exit', fail);
  child.stdio[3].on('error', fail);
  child.stdio[4].on('error', fail);
  child.stdio[4].setEncoding('utf8').on('data', chunk => {
    const packets = (partial + chunk).split('\0');
    partial = packets.pop();
    for (const packet of packets) {
      let response;
      try { response = JSON.parse(packet); } catch { fail(); return; }
      const waiter = pending.get(response.id);
      if (!waiter) continue;
      pending.delete(response.id);
      if (response.error) waiter.reject(new Error('Browser command failed'));
      else waiter.resolve(response.result);
    }
  });
  const deadline = setTimeout(() => { fail(); child.kill('SIGKILL'); }, 25_000);
  let sessionId;
  function command(method, params = {}) {
    if (closed) return Promise.reject(new Error('Browser closed'));
    return new Promise((resolve, reject) => {
      const id = ++serial;
      pending.set(id, { resolve, reject });
      child.stdio[3].write(JSON.stringify({ id, method, params, sessionId }) + '\0');
    });
  }
  async function evaluate(expression) {
    const result = await command('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) throw new Error('Print layout failed');
    return result.result.value;
  }
  try {
    const { targetId } = await command('Target.createTarget', { url: 'about:blank' });
    ({ sessionId } = await command('Target.attachToTarget', { targetId, flatten: true }));
    await command('Network.enable');
    await command('Network.setBlockedURLs', { urls: ['http://*', 'https://*', 'file://*', 'ftp://*'] });
    await command('Emulation.setEmulatedMedia', { media: 'print' });
    const { frameTree } = await command('Page.getFrameTree');
    await command('Page.setDocumentContent', { frameId: frameTree.frame.id, html });
    const warnings = [];
    if (html.includes('class="summary-mermaid"')) {
      await evaluate(readFileSync(diagramScript, 'utf8') + '\n;void 0');
      const rounds = await evaluate('(' + renderDiagrams.toString() + ')()');
      for (const round of rounds) warnings.push({ kind: 'diagram', round });
    }
    const failed = await evaluate('(' + settleResources.toString() + ')()');
    for (const kind of failed) warnings.push({ kind });
    const result = await command('Page.printToPDF', { transferMode: 'ReturnAsStream', printBackground: true, preferCSSPageSize: true,
      displayHeaderFooter: false, paperWidth: 8.2677, paperHeight: 11.6929,
      marginTop: 0.5, marginBottom: 0.5, marginLeft: 0.5, marginRight: 0.5 });
    const chunks = [];
    let size = 0;
    while (true) {
      const part = await command('IO.read', { handle: result.stream, size: 512 * 1024 });
      const chunk = Buffer.from(part.data, part.base64Encoded ? 'base64' : 'utf8');
      size += chunk.length;
      if (size > 96 * 1024 * 1024) throw new Error('Browser PDF too large');
      chunks.push(chunk);
      if (part.eof) break;
    }
    const bytes = Buffer.concat(chunks, size);
    if (!bytes.subarray(0, 5).equals(Buffer.from('%PDF-'))) throw new Error('Invalid browser PDF');
    return { bytes, warnings };
  } finally {
    clearTimeout(deadline);
    fail();
    child.kill('SIGKILL');
  }
}

async function renderDiagrams() {
  const failures = [];
  globalThis.mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', suppressErrorRendering: true });
  for (const [i, node] of [...document.querySelectorAll('.summary-mermaid')].entries()) {
    try {
      const { svg } = await globalThis.mermaid.render('figure-' + i, node.textContent);
      const figure = document.createElement('figure');
      figure.innerHTML = svg;
      node.replaceWith(figure);
    } catch { failures.push(Number(node.dataset.round) || 0); }
  }
  return failures;
}

async function settleResources() {
  const failures = [];
  for (const img of document.images) {
    try { await img.decode(); } catch { img.replaceWith(document.createTextNode(img.alt || '[image]')); failures.push('image'); }
  }
  await document.fonts.ready;
  if ([...document.fonts].some(face => face.status === 'error')) failures.push('font');
  return failures;
}
