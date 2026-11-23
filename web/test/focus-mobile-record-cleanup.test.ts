import { chromium } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { expect, it } from 'vitest';

const assets = new URL('../../mobile/harmony/entry/src/main/resources/rawfile/', import.meta.url);

it('groups all local copies, preserves folded choices and verifies remote defaults again before removal', async () => {
  const browser = await chromium.launch({headless:true,
    ...(process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE ? {executablePath:process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE} : {})});
  try {
    const page = await browser.newPage({viewport:{width:390,height:844}});
    page.setDefaultTimeout(6000);
    await page.route('https://reader.test/**', route => {
      const name = new URL(route.request().url()).pathname.slice(1);
      return route.fulfill({contentType:name.endsWith('.js') ? 'text/javascript' : 'text/html',body:readFileSync(new URL(name,assets))});
    });
    const names=['刚删除','外部移除','归档','仅关闭','旧版记录','长期未读','正常','在读'];
    let locked=false, restored=false;
    const removals: Record<string,string>[]=[];
    page.on('dialog', async dialog=>{
      const d=JSON.parse(dialog.defaultValue() || '{}');
      const op=dialog.message().split('/').pop(), scope='f'.repeat(64);
      let value: unknown=[];
      if(op==='init') value={sites:[{id:'a',name:'工作',reading:'在读'},{id:'b',name:'私人'}],active:'a'};
      if(op==='status') value=[{enabled:'1',locked:locked || d.entry==='b'?'1':'0',scope,fence:'3'}];
      if(op==='candidates') value=(d.entry==='a'?names:['私密']).map((name,i)=>({
        choice:name,title:locked || d.entry==='b'?'':name,thread:locked || d.entry==='b'?'':name,
        closed:['4','0','0','2','1','0','0','3'][i],reading:i===7?'1':'0',
        touched:String(Date.now()-(i===5?43:0)*86400000),complete:'1',locked:locked || d.entry==='b'?'1':'0',bytes:'1024',fence:'3',
      }));
      if(op==='verify') {
        const states=JSON.parse(d.body.threads).map((name:string)=>name==='归档'?'archived':
          name==='外部移除' && restored?'present':['外部移除','刚删除'].includes(name)?'missing':'present');
        await dialog.accept('ok');
        await page.evaluate(({id,scope,states})=>(window as any).focusRecordCheck(id,{data:{scope,states}}),{id:d.id,scope,states});
        return;
      }
      if(op==='cleanselected') { removals.push(d); value=[{removed:String(d.choices.split(',').filter(Boolean).length)}]; }
      await dialog.accept(JSON.stringify(value));
    });
    const button=(name:string)=>page.getByRole('button',{name,exact:true});
    const box=(name:string)=>page.getByRole('checkbox',{name,exact:true});
    await page.goto('https://reader.test/records.html');
    await button('选择要清理的离线记录').click();
    await button('清理所选 3 条 · 3 KiB').waitFor();
    expect(await box('外部移除').isChecked()).toBe(true);
    expect(await box('仅关闭').count()).toBe(0);
    await page.locator('summary').filter({hasText:'已关闭'}).click();
    expect(await box('仅关闭').isChecked()).toBe(false);
    await box('仅关闭').check();
    await page.locator('summary').filter({hasText:'已关闭'}).click();
    expect(await button('清理所选 4 条 · 4 KiB').isEnabled()).toBe(true);
    expect(await page.locator('summary').filter({hasText:'状态待核实'}).count()).toBe(1);
    expect(await page.locator('summary').filter({hasText:'本机至少 30 天未读'}).count()).toBe(1);
    expect(await box('在读').count()).toBe(0);
    await box('归档').uncheck();
    await page.evaluate(()=>(window as any).focusRecordEvent({event:'access'}));
    expect(await box('归档').isChecked()).toBe(false);
    await button('清理所选 3 条 · 3 KiB').click();
    expect(await page.locator('.confirm').innerText()).toContain('最后一份可读副本');
    restored=true;
    await button('确认清理').click();
    await button('选择要清理的离线记录').waitFor();
    expect(removals).toHaveLength(1);
    expect(new Set(removals[0]!.choices!.split(',').filter(Boolean))).toEqual(new Set(['刚删除','仅关闭']));
    expect(await page.getByRole('status').innerText()).toContain('已保留');
    await button('选择要清理的离线记录').click();
    await page.getByRole('combobox',{name:'实例范围'}).selectOption('all');
    await page.getByRole('combobox',{name:'记录范围'}).selectOption('all');
    await page.locator('summary').filter({hasText:'当前在读'}).click();
    expect(await box('在读').isChecked()).toBe(false);
    await box('在读').check();
    await page.locator('summary').filter({hasText:'已锁定'}).click();
    expect(await box('1 条锁定记录 · 1 KiB').isChecked()).toBe(false);
    expect(await page.getByText('私密',{exact:true}).count()).toBe(0);
    await page.getByRole('button',{name:/清理所选/}).click();
    expect(await page.locator('.confirm').innerText()).toContain('工作 · 在读');
    locked=true;
    await page.evaluate(()=>(window as any).focusRecordEvent({event:'access'}));
    expect(await page.locator('.confirm').count()).toBe(0);
    expect(await button('清理所选 0 条 · 0 KiB').isDisabled()).toBe(true);
  } finally { await browser.close(); }
},30000);
