'use strict';
(() => {
  const content = document.querySelector('#content'), status = document.querySelector('#status');
  const title = document.querySelector('#title'), header = document.querySelector('header');
  const call = (name, data = {}) => window.prompt('records/1/' + name, JSON.stringify(data));
  const init = JSON.parse(call('init') || '{}'), sites = init.sites || [];
  const manager = !init.entry;
  let entry = init.entry || sites[0]?.id || '', thread = init.thread || '', book, cold = !!init.cold;
  let activeIntent, requested, visibleSeq, markTimer, confirmBox, loadedAnchor, refreshCleanup;
  const day = 86400000;
  const readingThreads = new Map(sites.map(site => [site.id, site.reading ||
    (init.entry === site.id ? init.thread : init.active === site.id ? init.current : '') || '']));
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
      const message=execute(); list(); if(typeof message==='string') status.textContent=message;
    }));
    content.prepend(confirmBox); confirmBox.scrollIntoView({block:'nearest'});
  }
  function cleanupFilter(label, options, value, change) {
    const select=el('select');
    select.setAttribute('aria-label',label);
    for (const [id,name] of options) {
      const option=el('option',name); option.value=id; select.append(option);
    }
    select.value=value; select.onchange=()=>change(select.value);
    return select;
  }
  function recordSummary(row, now) {
    const days=Math.max(0,Math.floor((now-Number(row.touched))/day));
    const parts=[];
    if(row.reading==='1') parts.push('当前在读');
    if(row.closed==='1') parts.push('已记录关闭、归档或删除');
    parts.push(days ? '本机 '+days+' 天未读' : '本机 24 小时内读过',
      row.complete==='1' ? '已完整保存' : row.complete==='0' ? '部分已保存' : '尚无可读片段',bytes(row.bytes));
    return parts.join(' · ');
  }
  function cleanSelection(groups, mode) {
    let removed=0, skipped=0, uncertain=0;
    for (const {site,rows} of groups) {
      try {
        // Each site checks the preview and removes exactly its selected copies in one transaction.
        const [result]=db('cleanselected',{mode,reading:readingThreads.get(site.id),before:Date.now()-30*day,
          fence:rows[0].fence,locked:rows[0].locked,choices:','+rows.map(row=>row.choice).join(',')+','},site.id);
        const count=Number(result.removed);
        removed+=count; skipped+=rows.length-count;
      } catch { uncertain+=rows.length; }
    }
    return '已清理 '+removed+' 条本机离线记录。'+(skipped ? skipped+' 条记录已变化，已跳过。' : '')+
      (uncertain ? uncertain+' 条清理结果待核对，请重新查看列表。' : '');
  }
  function cleanup(scope='current', mode='old') {
    reset(); book=null; thread=''; cold=false;
    title.textContent='选择要清理的离线记录';
    const current=sites.find(site=>site.id===entry);
    const targets=scope==='all' ? sites : [current], access=new Map();
    refreshCleanup=(accessEvent=false)=>{
      if(accessEvent && targets.every(site=>{
        const state=db('status',{},site.id)[0], prior=access.get(site.id);
        return state && prior && state.fence===prior.fence && state.locked===prior.locked;
      })) return;
      cleanup(scope,mode);
    };
    const filters=el('div',undefined,'row');
    if(manager && sites.length>1) filters.append(cleanupFilter('实例范围',
      [['current','当前实例 · '+current.name],['all','所有实例']],scope,value=>cleanup(value,mode)));
    filters.append(cleanupFilter('记录范围',[['old','旧线程'],['all','全部记录']],mode,value=>cleanup(scope,value)));
    content.append(filters,el('p',mode==='old' ? '列出已记录关闭、归档或删除，以及本机至少 30 天未读的线程。当前在读线程已排除。'
      : '清理会删除所选线程在本机的离线副本和阅读位置。实例入口和服务端对话会保留。','muted'));
    const now=Date.now(), choices=[];
    const selectAll=el('input'); selectAll.type='checkbox';
    const selectLabel=el('label',undefined,'row'); selectLabel.append(selectAll,'全选当前列表');
    const results=el('div'), footer=el('div',undefined,'cleanup-footer');
    const submit=button('',()=>{
      const selected=new Map(), reading=[];
      for (const {box,site,rows} of choices) {
        if(!box.checked) continue;
        if(!selected.has(site)) selected.set(site,[]);
        selected.get(site).push(...rows);
        for(const row of rows) if(row.reading==='1') reading.push(site.name+' · '+(row.title || '锁定记录'));
      }
      const groups=Array.from(selected,([site,rows])=>({site,rows}));
      if(groups.length) confirmation(submit.textContent+'？仅删除本机离线副本。'+
        (reading.length ? '包含当前在读记录：'+reading.join('、')+'。' : ''),()=>cleanSelection(groups,mode));
    });
    function updateSelection() {
      confirmBox?.remove(); confirmBox=null;
      let count=0, size=0, checked=0;
      for(const choice of choices) if(choice.box.checked) { count+=choice.rows.length; size+=choice.size; checked++; }
      selectAll.checked=checked>0 && checked===choices.length;
      selectAll.indeterminate=checked>0 && checked<choices.length;
      submit.disabled=!count; submit.textContent='清理所选 '+count+' 条 · '+bytes(size);
    }
    selectAll.onchange=()=>{ for(const {box} of choices) box.checked=selectAll.checked; updateSelection(); };
    function addChoice(section, site, rows, name, summary) {
      const label=el('label',undefined,'candidate'), box=el('input'), text=el('span');
      box.type='checkbox'; box.setAttribute('aria-label',name); box.onchange=updateSelection;
      const detail=el('small',summary); detail.id='cleanup-detail-'+choices.length;
      box.setAttribute('aria-describedby',detail.id); text.append(el('strong',name),detail);
      label.append(box,text); section.append(label);
      choices.push({box,site,rows,size:rows.reduce((n,row)=>n+Number(row.bytes),0)});
    }
    for (const site of targets) {
      const rows=db('candidates',{mode,before:now-30*day,reading:readingThreads.get(site.id)},site.id);
      access.set(site.id,rows[0] || db('status',{},site.id)[0]);
      if(!rows.length) continue;
      const section=el('section'); section.setAttribute('aria-label',site.name); section.append(el('h2',site.name));
      if(rows[0].locked==='1') {
        const size=rows.reduce((n,row)=>n+Number(row.bytes),0);
        addChoice(section,site,rows,rows.length+' 条锁定记录 · '+bytes(size),'重新授权后可查看标题并逐条选择。');
      } else for(const row of rows) addChoice(section,site,[row],row.title,recordSummary(row,now));
      results.append(section);
    }
    if(!choices.length) { content.append(el('p',mode==='old'?'没有符合条件的旧线程。':'没有可清理的本机离线记录。','muted')); return; }
    footer.append(submit); content.append(selectLabel,results,footer); updateSelection();
  }
  function list() {
    reset(); refreshCleanup=null; book=null; thread=''; cold=false;
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
    content.append(button('选择要清理的离线记录',()=>cleanup()));
    const records=db('list');
    if (!records.length && setting.locked!=='1') content.append(el('p','暂无记录。开启自动保存后，在线打开一个线程即可。','muted'));
    for (const row of records) {
      const open=button('',()=>{
        thread=row.thread;
        if(manager){action('visit');return;}
        readingThreads.set(entry,row.thread);read();
      });
      open.className='entry'; open.append(el('span',row.title),el('small',(row.complete==='1'?'已完整保存':'部分已保存')+' · '+bytes(row.bytes)));
      content.append(open);
    }
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
    if (!book || confirmBox) return;
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
      const site=sites.find(item=>item.id===entry);
      const row=db('candidates',{mode:'all',before:0,reading:thread}).find(item=>item.reading==='1' && item.locked==='0');
      if (!row) { list(); return; }
      readingThreads.set(entry,thread);
      confirmation('删除当前在读记录「'+row.title+'」的本机离线副本（'+bytes(row.bytes)+'）？',
        ()=>cleanSelection([{site,rows:[row]}],'all'));
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
  window.focusRecordBack=()=>{if(confirmBox){confirmBox.remove();confirmBox=null;}else if(refreshCleanup || (book && manager))list();else action('back');};
  window.focusRecordEvent=data=>{
    if(data.thread===thread && data.event==='revert'){list();status.textContent='线程历史已变更，正在等待重新保存。';return;}
    if(data.thread===thread && data.event==='closed'){cancelIntent();content.querySelectorAll('.tool-results').forEach(n=>n.replaceChildren());status.textContent='此线程已关闭或归档。';return;}
    if(data.event==='access'){
      if(refreshCleanup) refreshCleanup(true); else if(!book || !db('book')[0]) list();return;
    }
    if(data.event==='ready'){
      if(!book && init.entry && data.thread && data.thread!==readingThreads.get(init.entry)){
        readingThreads.set(init.entry,data.thread); refreshCleanup?.();
      }
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
  document.addEventListener('visibilitychange',()=>{if(!document.hidden && refreshCleanup)refreshCleanup();});
  try{if(thread)read();else list();if(cold)action('probe');}catch(e){status.textContent=e.message;}
})();
