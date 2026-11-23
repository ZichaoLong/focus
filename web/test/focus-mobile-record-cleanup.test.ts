import { chromium } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { expect, it } from 'vitest';

const assets = new URL('../../mobile/harmony/entry/src/main/resources/rawfile/', import.meta.url);

it('previews offline copies by entry and confirms only the selected rows', async () => {
  const browser = await chromium.launch({headless:true,
    ...(process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE ? {executablePath:process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE} : {})});
  try {
    const page = await browser.newPage({viewport:{width:390,height:844}});
    const sites = [{id:'a',name:'工作'}, {id:'b',name:'私人'}];
    const now = Date.now(), day = 86400000;
    const old = {choice:'old',title:'相册',touched:String(now-43.5*day),bytes:'2048',closed:'0',complete:'0',reading:'0',locked:'0',fence:'4'};
    const closed = {...old,choice:'closed',title:'周报',touched:String(now),bytes:'1024',closed:'1',complete:'1'};
    const current = {...closed,choice:'active',title:'在读笔记',reading:'1'};
    const calls: Record<string,string>[] = [];
    let workLocked = false;
    await page.route('http://reader.test/**', route => {
      const name = new URL(route.request().url()).pathname.slice(1);
      return route.fulfill({contentType:name.endsWith('.js') ? 'text/javascript' : 'text/html',
        body:readFileSync(new URL(name,assets))});
    });
    page.on('dialog', async dialog => {
      const data = JSON.parse(dialog.defaultValue() || '{}');
      let result: unknown = [];
      switch (dialog.message().split('/').pop()) {
        case 'init': result = {sites,active:'a',current:'reading'}; break;
        case 'status': result = [{enabled:'1',locked:workLocked || data.entry === 'b' ? '1' : '0',fence:'4'}]; break;
        case 'candidates':
          if (data.entry === 'b') result = [{...old,title:'',locked:'1',choice:'private'},
            {...old,title:'',locked:'1',choice:'other'}];
          else {
            const rows = data.mode === 'all' ? [old,closed,current] : [old,closed];
            result = workLocked ? rows.map(row=>({...row,title:'',locked:'1'})) : rows;
          }
          break;
        case 'cleanselected': calls.push(data); result = [{removed:'1'}]; break;
      }
      await dialog.accept(JSON.stringify(result));
    });
    await page.goto('http://reader.test/records.html');
    const button = (name:string) => page.getByRole('button',{name,exact:true});
    const box = (name:string) => page.getByRole('checkbox',{name,exact:true});
    await button('选择要清理的离线记录').click();
    expect(await page.getByText('本机 43 天未读 · 部分已保存 · 2 KiB').count()).toBe(1);
    expect(await page.getByText(/已记录关闭、归档或删除 · 本机 24 小时内读过 · 已完整保存/).count()).toBe(1);
    expect(await box('在读笔记').count()).toBe(0);
    expect(await button('清理所选 0 条 · 0 KiB').isDisabled()).toBe(true);
    await box('周报').check();
    expect(await button('清理所选 1 条 · 1 KiB').isEnabled()).toBe(true);
    const accessChanged = () => page.evaluate(() => (window as any).focusRecordEvent({event:'access'}));
    await accessChanged();
    expect(await box('周报').isChecked()).toBe(true);
    await button('清理所选 1 条 · 1 KiB').click();
    workLocked = true;
    await accessChanged();
    expect(await page.locator('.confirm').count()).toBe(0);
    expect(await page.getByText('周报',{exact:true}).count()).toBe(0);
    expect(await box('2 条锁定记录 · 3 KiB').isChecked()).toBe(false);
    workLocked = false;
    await accessChanged();
    await box('周报').check();
    await page.getByRole('combobox',{name:'实例范围'}).selectOption('all');
    expect(await box('周报').isChecked()).toBe(false);
    expect(await page.getByRole('region',{name:'私人'}).getByRole('checkbox').count()).toBe(1);
    await box('全选当前列表').check();
    expect(await button('清理所选 4 条 · 7 KiB').isEnabled()).toBe(true);
    await page.getByRole('combobox',{name:'记录范围'}).selectOption('all');
    await box('在读笔记').check();
    await box('2 条锁定记录 · 4 KiB').check();
    await button('清理所选 3 条 · 5 KiB').click();
    expect(await page.locator('.confirm').innerText()).toContain('工作 · 在读笔记');
    await button('取消').click();
    expect(calls).toEqual([]);
    await button('清理所选 3 条 · 5 KiB').click();
    await button('确认清理').click();
    expect(calls).toMatchObject([
      {entry:'a',mode:'all',reading:'reading',choices:',active,',locked:'0'},
      {entry:'b',mode:'all',reading:'',choices:',private,other,',locked:'1'},
    ]);
    expect(await page.getByRole('status').innerText()).toContain('已清理 2 条本机离线记录。1 条记录已变化，已跳过。');
  } finally { await browser.close(); }
}, 20000);
