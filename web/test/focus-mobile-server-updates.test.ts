import { afterAll, beforeAll, expect, it } from 'vitest';
import { chromium, type Browser, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';

const assets = new URL('../../mobile/harmony/entry/src/main/resources/rawfile/', import.meta.url);
const entries = ['A', 'Alias', 'C', 'Current', 'Offline'].map((name,i) => ({ name, id: 'site-' + i }));
type BatchCall = { site: string; action: string; body: Record<string, string> };
const ids = 'aacde';
const snapshot = (id:string) => ({
  installation_id: id.repeat(32), request_id: '', installed: {channel:'local',version:'1',source_revision:'1'.repeat(40)},
  operation: {state:'idle',phase:'idle',operation_id:'',target:'',resolved_commit:'',requested_commit:'',message:'',error:''},
});
let browser: Browser;
beforeAll(async () => {
  browser = await chromium.launch({ headless: true,
    ...(process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE ? { executablePath: process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE } : {}) });
});
afterAll(async () => { await browser?.close(); });

async function openManager(page: Page, respond: (call: BatchCall) => unknown) {
  await page.route('http://manager.test/**', route => {
    const name = new URL(route.request().url()).pathname.slice(1);
    return route.fulfill({contentType:name.endsWith('.js') ? 'text/javascript' : 'text/html',
      body:readFileSync(new URL(name,assets))});
  });
  await page.exposeFunction('batchTestCall', respond);
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
  await page.goto('http://manager.test/server-updates.html');
}

it('groups aliases, pins one confirmation per checked installation, and reconciles a lost reply after reopening', async () => {
  const page = await browser.newPage();
  const calls: BatchCall[] = [];
  const status = new Map([...ids].map(id => [id,snapshot(id)]));
  try {
    await openManager(page, call => {
      calls.push(call);
      const index = entries.findIndex(s => s.id === call.site);
      if (index === 4) return {error:'入口暂不可达'};
      const value = status.get(ids[index]!)!;
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

it('checks only the marked entries on a first check and after a partial failure', async () => {
  const page = await browser.newPage({viewport:{width:390,height:844}});
  const status = new Map([...ids].map(id => [id,snapshot(id)]));
  const calls: string[] = [];
  let recovered = false;
  const all = page.getByRole('button',{name:'检查并准备全部'});
  const selected = page.getByRole('button',{name:/检查并准备所选/});
  const box = (action: string, name: string) => page.getByRole('checkbox',{name:action + ' ' + name,exact:true});
  const checkSelected = async () => {
    await selected.click();
    await expect.poll(() => all.isEnabled()).toBe(true);
    return calls.splice(0);
  };
  try {
    await openManager(page, ({site,action,body}) => {
      calls.push([site,action,body.target].filter(Boolean).join(' '));
      const id = ids[entries.findIndex(entry => entry.id === site)]!;
      const value = status.get(id)!;
      if (!recovered && site === 'site-1') return {error:'入口暂不可达'};
      if (action === 'status') return {data:value};
      if (action !== 'prepare') throw Error('Unexpected ' + action);
      if (!recovered && site === 'site-4') return {error:'查询 main 失败',rejected:true};
      if (site === 'site-3') return {data:{...value,outcome:'current',target:'main',revision:'1'.repeat(40)}};
      if (value.operation.state === 'idle') {
        value.request_id = body.request_id!;
        Object.assign(value.operation,{operation_id:id.repeat(32),state:'ready',target:'main',resolved_commit:'2'.repeat(40)});
      }
      return {data:{...value,outcome:'prepared',target:'main',revision:'2'.repeat(40)}};
    });
    expect(await selected.isDisabled()).toBe(true);
    await page.getByRole('combobox',{name:'更新渠道'}).selectOption('main');
    await box('检查','C').check();
    expect(await checkSelected()).toEqual(['site-2 status','site-2 prepare main']);
    await box('更新','C').uncheck();
    await all.click();
    await expect.poll(() => all.isEnabled()).toBe(true);
    expect(await page.getByText('查询 main 失败').count()).toBe(1);
    expect(await page.getByText('入口暂不可达').count()).toBe(1);
    calls.length = 0;

    recovered = true;
    await box('检查','C').uncheck();
    await box('检查','Offline').check();
    expect(await checkSelected()).toEqual(['site-4 status','site-4 prepare main']);
    expect(await box('更新','Offline').isChecked()).toBe(true);
    expect(await box('更新','C').isChecked()).toBe(false);
    expect(await box('更新','A').isChecked()).toBe(true);
    expect(await page.getByText('已是最新').count()).toBe(1);

    await box('检查','Offline').uncheck();
    await box('更新','A').uncheck();
    await box('检查','Alias').check();
    expect(await checkSelected()).toEqual(['site-1 status','site-1 prepare main']);
    expect(await box('更新','A、Alias').isChecked()).toBe(false);
    expect(await checkSelected()).toEqual(['site-0 status','site-1 status','site-0 prepare main']);
  } finally { await page.close(); }
});
