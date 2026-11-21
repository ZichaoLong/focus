// Privileged only inside the offline, app-owned management page.
(() => {
  'use strict';
  const host = (name, value = '') => prompt('focus-updates/' + name, value);
  const config = JSON.parse(host('init'));
  const $ = id => document.getElementById(id);
  const rows = config.sites.map(site => ({site, note: '待检查', fresh: false, selected: true}));
  const saved = config.records || {};
  $('channel').value = ['main', 'stable'].includes(config.channel) ? config.channel : 'installed';
  const activeStates = ['checking', 'cancelling', 'applying'];
  const labels = {idle:'待检查', checking:'正在准备', ready:'已就绪', applying:'正在更新', succeeded:'更新成功',
    failed:'更新失败', unknown:'结果待核实', cancelling:'正在取消', cancelled:'已取消'};
  let generation = 0, foreground = true, busy = false, request = null, timer = 0, backoff = 0;
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const live = n => foreground && n === generation;
  const token = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2,'0')).join('');
  const persist = () => {
    if (host('save', JSON.stringify({records:saved, channel:$('channel').value})) !== 'ok') throw Error('无法保存操作记录');
  };
  function rpc(row, action, body = {}) {
    return new Promise((resolve, reject) => {
      if (!foreground || request) { reject(Error('管理页面已暂停')); return; }
      const id = token();
      request = {id, resolve, reject};
      if (host('request', JSON.stringify({id, site:row.site.id, action, body})) !== 'ok') {
        request = null; reject(Error('无法连接此实例'));
      }
    });
  }
  function groups() {
    const result = new Map();
    for (const row of rows) {
      const key = row.install || row.site.id;
      if (!result.has(key)) result.set(key, []);
      result.get(key).push(row);
    }
    return [...result.values()];
  }
  function record(row) {
    const item = saved[row.site.id];
    return row.install && item?.install === row.install ? item : undefined;
  }
  function remember(group, value) {
    for (const r of group) saved[r.site.id] = value;
    persist();
  }
  function representative(group) { return group.find(row => row.fresh) || group[0]; }
  function eligible(row) {
    const savedOp = record(row);
    const channel = $('channel').value;
    const target = channel === 'installed' ? (row.installed?.channel === 'stable' ? 'stable' : 'main') : channel;
    return row.fresh && row.op?.target === target && row.op?.state === 'ready' && savedOp?.op === row.op.operation_id && !savedOp.sent;
  }
  function node(tag, text, cls) {
    const el = document.createElement(tag);
    if (text) el.textContent = text;
    if (cls) el.className = cls;
    return el;
  }
  function render() {
    const list = $('list'); list.replaceChildren();
    let ready = 0;
    for (const group of groups()) {
      const row = representative(group);
      const card = node('section', '', 'card'), header = node('header');
      const names = group.map(r => r.site.name).join('、');
      header.append(node('h2',names));
      if (eligible(row)) {
        const box = node('input'); box.type = 'checkbox'; box.checked = row.selected; box.disabled = busy;
        box.setAttribute('aria-label','更新 ' + names);
        box.onchange = () => { for (const r of group) r.selected = box.checked; render(); };
        header.append(box);
        if (row.selected) ready++;
      }
      card.append(header);
      const installed = row.installed;
      if (installed) card.append(node('div','已装 ' + (installed.channel === 'local' ? 'main' : installed.channel) +
        ' · ' + installed.version + ' · ' + installed.source_revision.slice(0,10), 'muted'));
      if (row.fresh && installed === null) card.append(node('div','已装构建未知','muted'));
      if (row.to) card.append(node('div','目标 ' + row.to,'muted'));
      card.append(node('div',row.note,'status'));
      if (row.detail) card.append(node('small',row.detail));
      if (row.open) {
        const link = node('button','打开实例','link'); link.disabled = busy;
        link.onclick = () => host('open',row.site.id); card.append(node('br'),link);
        const operation = record(row)?.op;
        if (operation) {
          const details = node('details');
          details.append(node('summary','操作 ID','muted'),node('code',operation)); card.append(details);
        }
      }
      list.append(card);
    }
    $('apply').textContent = ready ? '确认更新已就绪的 ' + ready + ' 套安装' : '确认更新已就绪的安装';
    $('apply').disabled = !ready || busy;
    $('check').disabled = busy || !rows.length; $('channel').disabled = busy;
  }
  function targetLabel(channel, revision, version) {
    return [channel, version, revision.slice(0,10)].filter(Boolean).join(' · ');
  }
  function observe(row, data) {
    if (!data || !/^[a-f0-9]{32}$/.test(data.installation_id) || !Object.hasOwn(labels,data.operation?.state))
      throw Error('无法核验此安装的状态');
    row.install = data.installation_id; row.installed = data.installed; row.op = data.operation;
    row.fresh = true; row.blocked = false; row.open = false; row.detail = '';
    const r = record(row), op = row.op;
    if (r?.request && !r.op && data.request_id === r.request && op.operation_id) {
      for (const key of Object.keys(saved)) if (saved[key].install === row.install && saved[key].request === r.request)
        saved[key].op = op.operation_id;
      persist();
    }
    if (r?.op && r.op === op.operation_id) {
      row.to = targetLabel(op.target,op.resolved_commit || op.requested_commit,r.version);
      row.note = labels[op.state];
      row.detail = op.error || (activeStates.includes(op.state) ? op.message : '');
      if (op.progress?.total) row.detail += ' · ' + Math.floor(100 * op.progress.current / op.progress.total) + '%';
      if (op.state === 'ready' && r.sent) { row.note = '服务端仍为已就绪，请重新检查后确认'; row.open = true; }
      if (op.state === 'failed' || op.state === 'unknown') row.open = true;
    } else {
      row.to = ''; row.note = r ? (!r.op && Date.now() < r.until ? '等待服务端确认上次准备' : '未找到上次操作，请重新检查') : labels[op.state];
      if (r && !r.op && row.lastError) { row.note = row.lastError; row.detail = '正在核对上次准备的操作记录'; row.open = true; }
      if (op.state === 'ready' && !r) row.note = '已有准备，检查后可确认';
      if (activeStates.includes(op.state) || op.state === 'unknown') { row.detail = op.error || op.message; row.open = true; }
    }
  }
  function failure(row, e) {
    row.fresh = false; row.open = true; row.blocked = e.needsEntry === true; row.note = String(e.message || e).slice(0,300);
    row.detail = record(row)?.sent ? (row.blocked ? '请在实例设置中核对上次操作 ID' : '等待服务恢复后核对操作记录') : '';
  }
  async function read(row, n) {
    try { const data = await rpc(row,'status'); if (live(n)) observe(row,data); }
    catch (e) { if (live(n)) failure(row,e); }
    if (live(n)) render();
  }
  async function check(n) {
    for (const row of rows) {
      if (!live(n)) return;
      row.install = ''; row.to = ''; row.lastError = ''; row.fresh = false; row.selected = true; row.note = '正在读取安装记录'; render();
      await read(row,n);
    }
    // Limit builds launched by this click. The server workers outlive their HTTP requests.
    let preparing = [];
    for (const group of groups()) {
      if (!live(n)) return;
      const row = representative(group);
      if (!row.fresh || activeStates.includes(row.op.state) || row.op.state === 'unknown') continue;
      while (preparing.length >= 2) {
        await sleep(3500);
        if (!live(n)) return;
        for (const pending of preparing) {
          await read(pending,n);
          if (!live(n)) return;
        }
        preparing = preparing.filter(r => r.fresh && r.op.state === 'checking');
      }
      const proposed = token(), previous = row.op.operation_id, install = row.install;
      const prior = group.map(item => saved[item.site.id]);
      try {
        remember(group,{install, op:'', request:proposed, until:Date.now()+120000, sent:false});
        row.note = '正在查询目标版本'; render();
        const data = await rpc(row,'prepare',{installation_id:install, target:$('channel').value,
          previous_operation_id:previous, request_id:proposed});
        if (!live(n)) return;
        if (data.installation_id !== install) throw Error('安装已更换，请重新检查');
        if (data.outcome === 'current') {
          for (const item of group) delete saved[item.site.id];
          persist();
          for (const item of group) {
            observe(item,data); item.note = '已是最新'; item.to = targetLabel(data.target,data.revision,data.version);
          }
        } else {
          const op = data.operation;
          if ((data.request_id !== proposed && !(op.state === 'ready' && op.operation_id === previous)) ||
              op.target !== data.target || (op.resolved_commit || op.requested_commit) !== data.revision)
            throw Error('准备记录与查询目标不一致');
          remember(group,{install, op:op.operation_id, version:data.version, sent:false});
          for (const item of group) observe(item,data);
          if (row.op.state === 'checking') preparing.push(row);
        }
      } catch (e) {
        if (!live(n)) return;
        if (e.rejected) {
          group.forEach((item,i) => { if (prior[i]) saved[item.site.id] = prior[i]; else delete saved[item.site.id]; });
          persist();
        }
        for (const item of group) { failure(item,e); item.lastError = item.note; if (e.rejected) item.blocked = true; }
      }
      if (live(n)) render();
    }
  }
  async function apply(n, choices) {
    for (const {group, row, install, op} of choices) {
      if (!live(n)) return;
      try {
        // Persist the exact user confirmation before dispatch. Resume only observes.
        remember(group,{install, op, version:record(row)?.version, sent:true}); row.note = '正在提交更新'; render();
        const data = await rpc(row,'apply',{installation_id:install,operation_id:op});
        if (!live(n)) return;
        if (data.installation_id !== install || data.operation.operation_id !== op) throw Error('操作记录已更换');
        for (const item of group) observe(item,data);
      } catch (e) { if (live(n)) for (const item of group) failure(item,e); }
      let missed = 0;
      while (live(n) && (!row.fresh || (row.install === install && row.op.operation_id === op && row.op.state === 'applying')) && missed < 2) {
        render(); await sleep(3500);
        if (!live(n)) return;
        await read(row,n); missed = row.fresh ? 0 : missed + 1;
      }
    }
  }
  function watch(row) {
    const r = record(row) || saved[row.site.id];
    return !row.blocked && r && (!row.fresh || (!r.op && Date.now() < r.until) || (r.op === row.op?.operation_id && activeStates.includes(row.op.state)));
  }
  function schedule() {
    clearTimeout(timer);
    if (foreground && !busy && groups().some(group => watch(representative(group))))
      timer = setTimeout(() => start(refresh), Math.min(60000, 5000 * 2 ** backoff));
  }
  async function refresh(n) {
    for (const group of groups()) {
      if (!live(n)) return;
      const row = representative(group);
      if (watch(row)) {
        await read(row,n);
        if (live(n) && row.fresh) for (const alias of group) {
          if (alias !== row && alias.install === row.install) Object.assign(alias,{fresh:row.fresh,op:row.op,note:row.note,detail:row.detail,to:row.to,installed:row.installed});
        }
      }
    }
    backoff = rows.some(row => watch(row) && !row.fresh) ? Math.min(backoff + 1,4) : 0;
  }
  function start(fn) {
    if (busy || !foreground) return;
    clearTimeout(timer); const n = ++generation; busy = true; $('message').textContent = ''; render();
    fn(n).catch(e => { if (live(n)) $('message').textContent = String(e.message || e); })
      .finally(() => { if (live(n)) { busy = false; render(); schedule(); } });
  }
  window.focusBatchResult = (id, reply) => {
    if (!request || request.id !== id) return;
    const pending = request; request = null;
    if (reply.error || !reply.data) pending.reject(Object.assign(Error(reply.error || '无法读取回复'), {needsEntry:reply.needs_entry === true, rejected:reply.rejected === true}));
    else pending.resolve(reply.data);
  };
  window.focusBatchActive = active => {
    if (foreground === active) return;
    foreground = active; generation++; clearTimeout(timer); busy = false;
    if (request) { request.reject(Error('已暂停')); request = null; }
    if (active) {
      for (const row of rows) if (saved[row.site.id]) row.fresh = false;
      start(refresh);
    }
  };
  $('channel').onchange = () => {
    for (const row of rows) { row.fresh = false; row.to = ''; row.note = '请检查所选渠道'; }
    persist(); clearTimeout(timer); render();
  };
  $('back').onclick = () => host('back');
  $('check').onclick = () => { backoff = 0; start(check); };
  $('apply').onclick = () => {
    const choices = groups().map(group => ({group, row:representative(group)})).filter(({row}) => eligible(row) && row.selected)
      .map(({group,row}) => ({group,row,install:row.install,op:row.op.operation_id}));
    if (choices.length) start(n => apply(n,choices));
  };
  render(); if (rows.some(row => saved[row.site.id])) start(refresh);
})();
