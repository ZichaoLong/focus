'use strict';
(() => {
  const content = document.querySelector('#content'), status = document.querySelector('#status');
  const title = document.querySelector('#title'), header = document.querySelector('header');
  const call = (name, data = {}) => window.prompt('records/1/' + name, JSON.stringify(data));
  const init = JSON.parse(call('init') || '{}'), sites = init.sites || [];
  const manager = !init.entry;
  let entry = init.entry || sites[0]?.id || '', thread = init.thread || '', book, cold = !!init.cold;
  let activeIntent, requested, visibleSeq, markTimer, confirmBox, loadedAnchor;
  const action = (op, more = {}) => call('action', {op,entry,thread,...more});
  function db(op, values = {}, site = entry) {
    const result = call(op,{...values,entry:site,thread:values.thread ?? thread});
    if (!result) throw new Error('无法读取或写入本机记录');
    return JSON.parse(result);
  }
  function el(tag, text, cls) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  }
  function button(text, fn) {
    const node = el('button',text);
    node.onclick = () => { try { fn(); } catch (e) { status.textContent = e.message; } };
    return node;
  }
  function cancelIntent() {
    if (requested) action('cancel');
    activeIntent = null; requested = null;
  }
  function reset() {
    cancelIntent(); clearTimeout(markTimer); confirmBox = null;
    content.replaceChildren(); status.textContent = ''; window.scrollTo(0,0);
  }
  function bytes(n) { return Number(n) >= 1048576 ? (n/1048576).toFixed(1)+' MiB' : Math.ceil(n/1024)+' KiB'; }
  function confirmation(label, execute) {
    confirmBox?.remove(); confirmBox = el('div',undefined,'confirm');
    confirmBox.append(el('p',label),button('取消',()=>{confirmBox?.remove();confirmBox=null;}),button('确认清理',()=>{
      execute(); thread=''; list();
    }));
    content.prepend(confirmBox); confirmBox.scrollIntoView({block:'nearest'});
  }
  function clean(mode, all) {
    const targets = all ? sites : sites.filter(s=>s.id === entry);
    const before = Date.now()-30*86400000;
    const matches = targets.flatMap(site=>db('count',{},site.id).filter(r=>mode==='all' ||
      ((r.closed==='1' || Number(r.touched)<before) && r.key!==currentKeys.get(site.id))).map(r=>({...r,site:site.id})));
    const size = matches.reduce((n,r)=>n+Number(r.bytes),0);
    confirmation('清理'+matches.length+' 个线程（'+bytes(size)+'）的本机记录？',()=>{
      // Apply only the previewed keys. A subsequently enrolled thread is outside this decision.
      for (const row of matches) db('remove',{key:row.key},row.site);
    });
  }
  const currentKeys = new Map();
  for(const site of sites){
    const active=site.reading || (init.entry===site.id ? init.thread : init.active===site.id ? init.current : '');
    if(active){const r=db('list',{},site.id).find(r=>r.thread===active);if(r)currentKeys.set(site.id,r.key);}
  }
  function list() {
    reset(); book=null; thread=''; cold=false;
    title.textContent='本机离线记录';
    if (!sites.length) { status.textContent='尚未添加实例'; return; }
    const selector=el('select'); selector.setAttribute('aria-label','选择实例');
    for (const site of sites) { const opt=el('option',site.name); opt.value=site.id; selector.append(opt); }
    selector.value=entry; selector.onchange=()=>{entry=selector.value;list();}; content.append(selector);
    const setting=db('status')[0] || {};
    const check=el('input'); check.type='checkbox'; check.checked=setting.enabled==='1';
    const label=el('label',undefined,'row'); label.append(check,'自动保存正在浏览的线程');
    check.onchange=()=>{db('enable',{enable:check.checked?'1':'0'});action('refresh');list();};
    content.append(label);
    if(setting.note==='unsupported') content.append(el('p','此线程暂不支持按稳定位置读取在线历史。','muted'));
    if(setting.note==='paused') content.append(el('p','保存已暂停。可检查本机剩余空间或清理旧记录。','muted'));
    if(!manager && init.thread && check.checked) content.append(button('重新保存在线的当前线程',()=>{
      action('save',{thread:init.thread});status.textContent='正在请求保存…';
    }));
    if (setting.locked==='1') status.textContent='此实例需要重新授权。已保存的内容暂时锁定。';
    const records=db('list');
    if (!records.length && setting.locked!=='1') content.append(el('p','暂无记录。开启自动保存后，在线打开一个线程即可。','muted'));
    for (const row of records) {
      const open=button('',()=>{
        thread=row.thread;
        if(manager){action('visit');return;}
        currentKeys.set(entry,row.key);read();
      });
      open.className='entry'; open.append(el('span',row.title),el('small',(row.complete==='1'?'已完整保存':'部分已保存')+' · '+bytes(row.bytes)));
      content.append(open);
    }
    content.append(el('h2','清理记录'),el('p','旧线程指已确认关闭、归档，或已连续 30 天未在本机阅读的线程。','muted'));
    const controls=el('div',undefined,'row');
    controls.append(button('清理此实例旧线程',()=>clean('old',false)),button('清空此实例',()=>clean('all',false)));
    if (manager && sites.length>1) controls.append(button('清理所有实例旧线程',()=>clean('old',true)),button('清空所有实例',()=>clean('all',true)));
    content.append(controls);
  }
  // Offline Markdown has no HTML, image, embed or link navigation surface.
  function inline(node, text) {
    for (const segment of text.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g)) {
      if (segment.startsWith('**') && segment.endsWith('**')) node.append(el('strong',segment.slice(2,-2)));
      else if (segment.startsWith('`') && segment.endsWith('`')) node.append(el('code',segment.slice(1,-1)));
      else node.append(document.createTextNode(segment));
    }
  }
  function markdown(node, text) {
    const lines=text.split('\n');
    for (let i=0;i<lines.length;i++) {
      const line=lines[i]; if (!line.trim()) continue;
      if (/^\s*```/.test(line)) {
        const code=[]; while (++i<lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i]);
        node.append(el('pre',code.join('\n'))); continue;
      }
      if (line.includes('|') && /^\s*\|?\s*:?-{3,}/.test(lines[i+1] || '')) {
        const table=el('table');
        function cells(value,tag) { const tr=el('tr'); for (const c of value.replace(/^\s*\||\|\s*$/g,'').split('|')) { const cell=el(tag);inline(cell,c.trim());tr.append(cell); }table.append(tr); }
        cells(line,'th');i++;while(lines[i+1]?.includes('|')) cells(lines[++i],'td');node.append(table);continue;
      }
      const head=/^(#{1,6})\s+(.+)/.exec(line);
      const part=el(head?'h'+Math.min(6,head[1].length+1):line.startsWith('> ')?'blockquote':'p');
      inline(part,head?head[2]:line.replace(/^> /,''));node.append(part);
    }
  }
  function bookmark() {
    if (!book) return;
    const top=header.getBoundingClientRect().bottom;
    const row=[...content.querySelectorAll('[data-item]')].find(n=>n.getBoundingClientRect().bottom>top);
    if (!row) return;
    loadedAnchor={turn:row.dataset.turn,item:row.dataset.item,seq:visibleSeq,offset:row.getBoundingClientRect().top-top,
      reading:loadedAnchor?.reading ?? true};
    db('bookmark',{now:Date.now(),anchor:JSON.stringify(loadedAnchor)});
  }
  function toolGroup(group) {
    const wrap=el('section',undefined,'tools'), details=el('div');
    const toggle=button(group.count+' 条工具调用  ›',()=>{
      cold=false;
      if (activeIntent?.wrap===wrap) { cancelIntent();details.replaceChildren();toggle.setAttribute('aria-expanded','false');return; }
      cancelIntent();content.querySelectorAll('.tool-results').forEach(n=>n.replaceChildren());
      toggle.setAttribute('aria-expanded','true');details.textContent=manager?'在线进入此实例和线程后可查看详情':'恢复连接后展开…';
      if (manager) return;
      requested={op:'expand',id:crypto.randomUUID(),group};
      activeIntent={id:requested.id,wrap,details,group};
      action('expand',requested);
    });
    details.className='tool-results';toggle.setAttribute('aria-expanded','false');wrap.append(toggle,details);return wrap;
  }
  function pageRows(seq) {
    const c=db('chunk',{run:book.run,seq})[0];
    if (!c) return [];
    const items=JSON.parse(c.body).reverse();
    if (seq===Number(book.seq)-1 && book.edge) items.unshift(JSON.parse(book.edge));
    if (seq===0 && book.live) for(const row of JSON.parse(book.live)){
      if (!row) continue;
      const ix=items.findIndex(r=>r.turn===row.turn && r.item===row.item);
      if(ix>=0) items[ix]=row;else items.push(row);
    }
    const joined=[];
    for (const row of items) {
      const previous=joined[joined.length-1];
      if (row.part>0 && previous?.item===row.item && previous.turn===row.turn && previous.part!==undefined) previous.text+=row.text;
      else joined.push(row);
    }
    return joined;
  }
  function online(anchor) {
    cancelIntent();
    requested={id:crypto.randomUUID(),op:'online',anchor};
    status.textContent='正在等待在线对话…';
    action('online',requested);
  }
  function read(start) {
    reset();book=db('book')[0];
    if (!book) {list(); return;}
    db('touch',{now:Date.now()}); title.textContent=book.title;
    status.textContent=(book.complete==='1'?'已完整保存至 ':'部分已保存 · ')+new Date(Number(book.stamp)).toLocaleString();
    const actions=el('div',undefined,'row');
    if (!manager) actions.append(button('返回在线对话',()=>{bookmark();online(loadedAnchor);}));
    actions.append(button('线程列表',list),button('删除此记录',()=>{
      const r=db('list').find(b=>b.thread===thread);
      if (r) confirmation('删除此线程在本机的离线记录（'+bytes(r.bytes)+'）？',()=>db('remove',{key:r.key}));
    }));content.append(actions);
    const max=Number(book.seq)-1;
    loadedAnchor=JSON.parse(book.anchor || 'null');
    const previousSeq=visibleSeq;
    visibleSeq=Math.min(max,Math.max(0,start ?? loadedAnchor?.seq ?? 0));
    let items=pageRows(visibleSeq);
    if(!items.length){
      const step=start===undefined || visibleSeq<previousSeq ? -1 : 1;
      let next=visibleSeq;
      while(!items.length && next+step>=0 && next+step<=max){next+=step;items=pageRows(next);}
      visibleSeq=next;
    }
    if (start===undefined && loadedAnchor?.item) {
      const matches=r=>r.turn===loadedAnchor.turn && (r.item===loadedAnchor.item || r.first===loadedAnchor.item || r.last===loadedAnchor.item);
      if(!items.some(matches)) for(let seq=0;seq<=max;seq++) {
        const other=pageRows(seq);
        if(other.some(matches)){items=other;visibleSeq=seq;break;}
      }
    }
    if (visibleSeq<max) content.append(button('更早记录',()=>read(visibleSeq+1)));
    for(const row of items) {
      const node=row.kind==='tools'?toolGroup(row):el('article',undefined,'message '+row.kind);
      node.dataset.turn=row.turn;node.dataset.item=row.item || row.first;
      if(row.kind!=='tools'){if(row.partial)node.append(el('small','生成中 · 已保存片段'));markdown(node,row.text || '');}
      content.append(node);
    }
    if(visibleSeq>0)content.append(button('较新记录',()=>read(visibleSeq-1)));
    if(start===undefined && loadedAnchor?.item){
      const target=[...content.querySelectorAll('[data-item]')].find(n=>n.dataset.turn===loadedAnchor.turn && n.dataset.item===loadedAnchor.item);
      if(target)window.scrollBy(0,target.getBoundingClientRect().top-header.offsetHeight-(loadedAnchor.offset || 0));
    }else if(start===undefined && visibleSeq===0)window.scrollTo(0,document.body.scrollHeight);
  }
  window.focusRecordBack=()=>{if(confirmBox){confirmBox.remove();confirmBox=null;}else if(book && manager)list();else action('back');};
  window.focusRecordEvent=data=>{
    if(data.thread===thread && data.event==='revert'){list();status.textContent='线程历史已变更，正在等待重新保存。';return;}
    if(data.thread===thread && data.event==='closed'){cancelIntent();content.querySelectorAll('.tool-results').forEach(n=>n.replaceChildren());status.textContent='此线程已关闭或归档。';return;}
    if(data.event==='access'){
      if(book && !db('book')[0])list();return;
    }
    if(data.event==='ready'){
      if(cold && data.thread===thread){cold=false;online();}
      else if(requested) action(requested.op,requested);
      return;
    }
    if(requested?.op==='online' && data.id===requested.id){
      if(data.open){action('back');return;}
      if(data.error){
        status.textContent=data.error;
        if(data.missingPosition)status.append(button('进入在线线程',()=>online()));
      }
      return;
    }
    if(!activeIntent || data.id!==activeIntent.id) return;
    const {details,group}=activeIntent;
    if(data.waiting){details.textContent='恢复连接后展开…';return;}
    if(data.error){details.replaceChildren(el('p',data.error),button('重试',()=>action(requested.op,requested)));return;}
    if(typeof data.text==='string'){
      let pre=details.querySelector('.tool-detail');
      if(!data.append || !pre){pre=el('pre','','tool-detail');details.append(pre);}
      pre.append(document.createTextNode(data.text)); return;
    }
    if(Array.isArray(data.tools)){
      if(!data.append)details.replaceChildren(); for(const tool of data.tools){
        details.append(button(tool.name+' '+tool.arg,()=>{
          requested={id:crypto.randomUUID(),op:'detail',group,item:tool.item};activeIntent.id=requested.id;action('detail',requested);
        }));
      }
    }
  };
  document.querySelector('#back').onclick=window.focusRecordBack;
  const sw=document.querySelector('#switch');sw.hidden=manager;sw.onclick=()=>{cancelIntent();action('drawer');};
  for(const event of ['pointerdown','keydown','wheel','touchstart'])document.addEventListener(event,()=>{cold=false;},{passive:true});
  window.addEventListener('scroll',()=>{clearTimeout(markTimer);markTimer=setTimeout(()=>{try{bookmark();}catch{}},200);},{passive:true});
  try{if(thread)read();else list();if(cold)action('probe');}catch(e){status.textContent=e.message;}
})();
