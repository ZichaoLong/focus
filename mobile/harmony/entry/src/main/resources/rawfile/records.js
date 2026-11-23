'use strict';
(() => {
  const content = document.querySelector('#content'), status = document.querySelector('#status');
  const title = document.querySelector('#title'), header = document.querySelector('header');
  const call = (name, data = {}) => window.prompt('records/1/' + name, JSON.stringify(data));
  const init = JSON.parse(call('init') || '{}'), sites = init.sites || [];
  const manager = !init.entry;
  let entry = init.entry || sites[0]?.id || '', thread = init.thread || '', book;
  let activeIntent, requested, visibleSeq, markTimer, confirmBox, loadedAnchor, refreshCleanup;
  let checkRequest;
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
    cancelIntent(); cancelCheck(); refreshCleanup=null; clearTimeout(markTimer); confirmBox = null;
    content.replaceChildren(); status.textContent = ''; window.scrollTo(0,0);
  }
  function bytes(n) { return Number(n) >= 1048576 ? (n/1048576).toFixed(1)+' MiB' : Math.ceil(n/1024)+' KiB'; }
  function confirmation(label, execute) {
    confirmBox?.remove(); confirmBox = el('div',undefined,'confirm');
    const box=confirmBox;
    const submit=button('确认清理',async ()=>{
      if (submit.disabled) return;
      submit.disabled=true;
      try {
        const message=await execute(()=>confirmBox===box);
        if(confirmBox!==box) return;
        list(); if(typeof message==='string') status.textContent=message;
      } catch(e) { if(confirmBox===box) { status.textContent=e.message; submit.disabled=false; } }
    });
    box.append(el('p',label),button('取消',()=>{confirmBox?.remove();confirmBox=null;}),submit);
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
  function cancelCheck() {
    if(!checkRequest) return;
    call('cancelcheck'); checkRequest.finish(null);
  }
  function verify(site, scope, rows) {
    if(!scope || !rows.length) return Promise.resolve(null);
    cancelCheck();
    return new Promise(resolve=>{
      const id=crypto.randomUUID();
      const timeout=setTimeout(()=>{if(checkRequest?.id===id) cancelCheck();},25000);
      checkRequest={id,finish:value=>{clearTimeout(timeout);checkRequest=null;resolve(value);}};
      const ok=call('verify',{entry:site.id,id,body:{scope,threads:JSON.stringify(rows.map(r=>r.thread))}});
      if(ok!=='ok') checkRequest.finish(null);
    });
  }
  window.focusRecordCheck=(id,reply)=>{ if(checkRequest?.id===id) checkRequest.finish(reply); };
  const categories=[
    ['deleted','已确认删除',true],['missing','服务端已找不到，本机仍有副本',true],
    ['archived','已归档',true],['closed','已关闭',false],['old','本机至少 30 天未读',false],
    ['unknown','状态待核实',false],['recent','近期读过',false],['reading','当前在读',false],['locked','已锁定',false]
  ];
  function classify(row, remote, before) {
    if(row.locked==='1') return 'locked';
    if(row.reading==='1') return 'reading';
    if(remote==='missing') return row.closed==='4' ? 'deleted' : 'missing';
    if(remote==='archived') return 'archived';
    if(remote!=='present' && row.closed==='4') return 'deleted';
    if(remote!=='present' && row.closed==='3') return 'archived';
    if(row.closed==='2') return 'closed';
    if(row.closed==='1') return 'unknown';
    if(Number(row.touched)<=before) return 'old';
    return remote==='present' ? 'recent' : 'unknown';
  }
  function cleanup(scope='current', mode='old', selected=new Map(), expanded=new Map()) {
    reset(); book=null; thread='';
    title.textContent='选择要清理的离线记录';
    const current=sites.find(site=>site.id===entry);
    const targets=scope==='all' ? sites : [current];
    const choices=[], groups=[];
    const selectionKey=(site,row)=>[site.id,row.fence,row.locked,row.choice].join(':');
    const now=Date.now(), before=now-30*day;
    const sitesWithRows=targets.map(site=>({site,access:db('status',{},site.id)[0],
      rows:db('candidates',{mode:'all',before,reading:readingThreads.get(site.id)},site.id),remote:new Map()}));
    let confirming=false, scanGeneration=0, previewed=new Set();
    const refresh=(accessOnly=false)=>{
      if(accessOnly && sitesWithRows.every(({site,access})=>{
        const state=db('status',{},site.id)[0];
        return state && access && state.fence===access.fence && state.locked===access.locked;
      })) return;
      cleanup(scope,mode,selected,expanded);
    };
    refreshCleanup=refresh;
    const filters=el('div',undefined,'row');
    if(manager && sites.length>1) filters.append(cleanupFilter('实例范围',
      [['current','当前实例 · '+current.name],['all','所有实例']],scope,value=>cleanup(value,mode)));
    filters.append(cleanupFilter('记录范围',[['old','清理候选'],['all','全部记录']],mode,value=>cleanup(scope,value)));
    content.append(filters,el('p','清理所选线程在本机的副本和阅读位置。当前在读记录始终由你手动选择。','muted'));
    const selectAll=el('input'); selectAll.type='checkbox';
    const selectLabel=el('label',undefined,'row'); selectLabel.append(selectAll,'全选当前列表');
    const results=el('div'), footer=el('div',undefined,'cleanup-footer');
    const submit=button('',()=>{
      const batches=sitesWithRows.map(data=>({...data,rows:choices.filter(c=>c.site===data.site && c.checked).flatMap(c=>c.rows)})).filter(g=>g.rows.length);
      if(!batches.length) return;
      previewed=new Set(batches.flatMap(group=>group.rows));
      const reading=batches.flatMap(g=>g.rows.filter(r=>r.reading==='1').map(r=>g.site.name+' · '+(r.title || '锁定记录')));
      const last=choices.some(c=>c.checked && ['missing','deleted'].includes(c.category));
      confirmation(submit.textContent+'？仅删除本机离线副本。'+(last?'所选记录可能是最后一份可读副本。':'')+
        (reading.length?'包含当前在读记录：'+reading.join('、')+'。':''),async stillOpen=>{
        confirming=true; scanGeneration++; cancelCheck();
        const verified=[];
        let changed=0;
        try {
          for(const group of batches) {
            const vetted=[];
            const checked=group.rows.filter(row=>['archived','missing'].includes(group.remote.get(row.choice)));
            const checkKeys=new Set(checked.map(row=>row.choice));
            vetted.push(...group.rows.filter(row=>!checkKeys.has(row.choice)));
            for(let i=0;i<checked.length;i+=32) {
              if(!stillOpen()) return;
              const page=checked.slice(i,i+32), states=await checkPage(group,page);
              if(!stillOpen()) return;
              for(const [j,row] of page.entries()) {
                if(states?.[j]===group.remote.get(row.choice)) vetted.push(row); else changed++;
              }
            }
            if(vetted.length) verified.push({site:group.site,rows:vetted});
          }
          if(!stillOpen()) return;
          const message=cleanSelection(verified,mode==='old'?'review':'all');
          return message+(changed ? changed+' 条在线状态已变化或无法核实，已保留。' : '');
        } finally { confirming=false; }
      });
    });
    function updateSelection() {
      let count=0,size=0,checked=0;
      for(const group of groups) {
        let n=0;
        for(const item of group.items) if(item.checked) { n+=item.rows.length; size+=item.size; checked++; }
        count+=n;
        group.label.textContent=group.name+' · 已选 '+n+' / '+group.count+' 条 · '+bytes(group.size);
      }
      selectAll.checked=checked>0 && checked===choices.length;
      selectAll.indeterminate=checked>0 && checked<choices.length;
      submit.disabled=!count; submit.textContent='清理所选 '+count+' 条 · '+bytes(size);
    }
    function remember(item, checked) {
      item.checked=checked;
      if(item.box) item.box.checked=checked;
      for(const row of item.rows) selected.set(selectionKey(item.site,row),checked);
      confirmBox?.remove(); confirmBox=null;
    }
    selectAll.onchange=()=>{for(const item of choices) remember(item,selectAll.checked); updateSelection();};
    function showRows(group) {
      if(!group.fold.open || group.body.childElementCount) return;
      for(const item of group.items) {
        const line=el('label',undefined,'candidate'), box=el('input'), text=el('span');
        const locked=item.category==='locked', row=item.rows[0];
        const title=locked ? item.rows.length+' 条锁定记录 · '+bytes(item.size) : row.title;
        const detail=el('small',locked ? '重新授权后可逐条查看。' : recordSummary(row,now));
        detail.id='cleanup-detail-'+item.index;
        box.type='checkbox'; box.setAttribute('aria-label',title); box.setAttribute('aria-describedby',detail.id);
        box.checked=item.checked; item.box=box;
        box.onchange=()=>{remember(item,box.checked);updateSelection();};
        text.append(el('strong',title),detail); line.append(box,text); group.body.append(line);
      }
    }
    function render() {
      for(const group of groups) expanded.set(group.key,group.fold.open);
      results.replaceChildren(); groups.length=0; choices.length=0;
      for(const {site,rows,remote} of sitesWithRows) {
        const section=el('section'); section.setAttribute('aria-label',site.name); section.append(el('h2',site.name));
        for(const [category,name,preselect] of categories) {
          if(mode==='old' && (category==='recent' || category==='reading')) continue;
          const matching=rows.filter(r=>(mode!=='old' || r.reading!=='1') && classify(r,remote.get(r.choice),before)===category);
          if(!matching.length) continue;
          const fold=el('details'),label=el('summary'),items=[],body=el('div'),foldKey=site.id+':'+category;
          fold.open=expanded.get(foldKey) ?? preselect;
          fold.append(label);
          if(category==='missing') fold.append(el('p','可能是最后一份可读副本。','muted'));
          const size=matching.reduce((n,r)=>n+Number(r.bytes),0);
          const group={name,label,items,count:matching.length,size,fold,body,key:foldKey};
          groups.push(group); fold.append(body);
          fold.ontoggle=()=>{if(fold.isConnected) { expanded.set(foldKey,fold.open); showRows(group); }};
          for(const copies of category==='locked' ? [matching] : matching.map(r=>[r])) {
            const amount=copies.reduce((n,r)=>n+Number(r.bytes),0);
            const checked=copies.every(r=>selected.get(selectionKey(site,r)) ?? (preselect && r.reading!=='1'));
            const item={checked,rows:copies,site,category,size:amount,index:choices.length};
            items.push(item); choices.push(item);
          }
          showRows(group); section.append(fold);
        }
        if(section.children.length>1) results.append(section);
      }
      selectLabel.hidden=footer.hidden=!choices.length;
      if(!choices.length) results.append(el('p',mode==='old'?'没有符合条件的旧线程。':'没有可清理的本机离线记录。','muted'));
      updateSelection();
    }
    async function checkPage(group, page) {
      const response=await verify(group.site,group.access?.scope,page);
      if(refreshCleanup!==refresh) return null;
      if(response?.scope_changed) {
        db('checklock',{scope:group.access.scope,fence:group.access.fence},group.site.id);
        refresh(true); return null;
      }
      const data=response?.data;
      if(data?.scope!==group.access?.scope || !Array.isArray(data?.states) || data.states.length!==page.length) return null;
      return data.states.every(s=>['present','archived','missing','unknown'].includes(s)) ? data.states : null;
    }
    async function scan() {
      const generation=++scanGeneration;
      let incomplete=false;
      for(const group of sitesWithRows) {
        const rows=group.rows.filter(row=>row.thread && row.reading!=='1');
        for(let i=0;i<rows.length;i+=32) {
          if(refreshCleanup!==refresh || document.hidden || confirming || generation!==scanGeneration) return;
          const page=rows.slice(i,i+32), states=await checkPage(group,page);
          if(refreshCleanup!==refresh || confirming || generation!==scanGeneration) return;
          if(!states) { incomplete=true; break; }
          const changes=page.filter((row,j)=>classify(row,group.remote.get(row.choice),before)!==classify(row,states[j],before));
          page.forEach((row,j)=>group.remote.set(row.choice,states[j]));
          if(confirmBox && changes.some(row=>previewed.has(row))) { confirmBox.remove(); confirmBox=null; }
          if(changes.length) render();
        }
      }
      if(refreshCleanup===refresh) status.textContent=incomplete?'部分记录暂时无法从服务端核实，已保留本机状态。':'';
    }
    footer.append(submit);content.append(selectLabel,results,footer);render();
    status.textContent='正在核对服务端线程状态…';
    void scan().catch(()=>{if(refreshCleanup===refresh)status.textContent='部分记录暂时无法核实。';});
  }
  function list() {
    reset(); refreshCleanup=null; book=null; thread='';
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
    if(data.event==='lifecycle'){
      if(refreshCleanup) refreshCleanup();
      else if(data.thread===thread && ['closed','archived','deleted'].includes(data.reason)){
        cancelIntent();content.querySelectorAll('.tool-results').forEach(n=>n.replaceChildren());status.textContent='线程状态已变化，可在清理页查看。';
      }
      return;
    }
    if(data.event==='access'){
      if(refreshCleanup) refreshCleanup(true); else if(!book || !db('book')[0]) list();return;
    }
    if(data.event==='ready'){
      if(!book && init.entry && data.thread && data.thread!==readingThreads.get(init.entry)){
        readingThreads.set(init.entry,data.thread); refreshCleanup?.();
      }
      if(requested) action(requested.op,requested);
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
  window.addEventListener('scroll',()=>{clearTimeout(markTimer);markTimer=setTimeout(()=>{try{bookmark();}catch{}},200);},{passive:true});
  document.addEventListener('visibilitychange',()=>{
    if(document.hidden) {
      if(refreshCleanup && confirmBox) { confirmBox.remove(); confirmBox=null; }
      cancelCheck();
    } else refreshCleanup?.();
  });
  try{if(thread)read();else list();if(!manager)action('probe');}catch(e){status.textContent=e.message;}
})();
