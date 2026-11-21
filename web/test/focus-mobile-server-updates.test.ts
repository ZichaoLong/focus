import { afterAll, beforeAll, expect, it } from 'vitest';
import { chromium, type Browser } from '@playwright/test';
import { readFileSync } from 'node:fs';

const assets = new URL('../../mobile/harmony/entry/src/main/resources/rawfile/', import.meta.url);
const entries = ['A', 'Alias', 'C', 'Current', 'Offline'].map((name,i) => ({ name, id: 'site-' + i }));
let browser: Browser;
beforeAll(async () => {
  browser = await chromium.launch({ headless: true,
    ...(process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE ? { executablePath: process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE } : {}) });
});
afterAll(async () => { await browser?.close(); });

it('groups aliases, pins one confirmation per checked installation, and reconciles a lost reply after reopening', async () => {
  const page = await browser.newPage();
  const calls: {site:string; action:string; body:Record<string,string>}[] = [];
  const ids = 'aacde';
  const snapshot = (i:number) => ({
    installation_id: ids[i]!.repeat(32), request_id: '', installed: {channel:'local',version:'1',source_revision:'1'.repeat(40)},
    operation: {state:'idle',phase:'idle',operation_id:'',target:'',resolved_commit:'',requested_commit:'',message:'',error:''},
  });
  const status = new Map(entries.map((_,i) => [ids[i],snapshot(i)]));
  await page.route('http://manager.test/**', route => {
    const name = new URL(route.request().url()).pathname.slice(1);
    return route.fulfill({contentType:name.endsWith('.js') ? 'text/javascript' : 'text/html',
      body:readFileSync(new URL(name,assets))});
  });
  await page.exposeFunction('batchTestCall', async (call: typeof calls[number]) => {
    calls.push(call);
    const index = entries.findIndex(s => s.id === call.site);
    if (index === 4) return {error:'入口暂不可达'};
    const value = status.get(ids[index])!;
    if (call.action === 'prepare') {
      if (index === 3) return {data:{...value, outcome:'current',target:'main',revision:'1'.repeat(40)}};
      value.request_id = call.body.request_id!;
      Object.assign(value.operation,{operation_id:(index === 0 ? 'f' : 'e').repeat(32),state:'ready',target:'main',resolved_commit:'2'.repeat(40)});
      // The manager must recover the server-issued ID even without this response.
      if (index === 0) return {error:'连接中断'};
      return {data:{...value,outcome:'prepared',target:'main',revision:'2'.repeat(40)}};
    }
    if (call.action === 'apply') {
      expect(call.body.operation_id).toBe(value.operation.operation_id);
      value.operation.state = 'succeeded';
      return {error:'连接中断'};
    }
    return {data:value};
  });
  await page.addInitScript(({entries}) => {
    const w = window as any;
    w.prompt = (key:string,text:string) => {
      if (key.endsWith('/init')) return JSON.stringify({sites:entries,...JSON.parse(localStorage.getItem('batch') || '{}')});
      if (key.endsWith('/save')) { localStorage.setItem('batch',text); return 'ok'; }
      if (key.endsWith('/request')) {
        const req = JSON.parse(text);
        w.batchTestCall(req).then((result:unknown) => w.focusBatchResult(req.id,result));
        return 'ok';
      }
      return '';
    };
  },{entries});
  try {
    await page.goto('http://manager.test/server-updates.html');
    await page.getByText('检查并准备全部').click();
    await expect.poll(async () => await page.locator('#apply').textContent(), {timeout:12000})
      .toContain('2 套安装');
    expect(calls.filter(c => c.action === 'prepare').map(c => c.site)).toEqual(['site-0','site-2','site-3']);
    expect(await page.locator('.card').count()).toBe(4);
    expect(await page.getByText('已是最新').count()).toBe(1);
    await page.getByRole('checkbox',{name:'更新 C',exact:true}).uncheck();
    await page.getByRole('button',{name:'确认更新已就绪的 1 套安装'}).click();
    await expect.poll(() => calls.filter(c => c.action === 'apply').length).toBe(1);
    await page.reload();
    await expect.poll(async () => await page.getByText('更新成功').count()).toBe(1);
    expect(calls.filter(c => c.action === 'apply').map(c => c.site)).toEqual(['site-0']);
    expect(calls.filter(c => c.action === 'prepare').length).toBe(3);
  } finally { await page.close(); }
}, 25000);
