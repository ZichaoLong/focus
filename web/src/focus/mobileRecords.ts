import { watch } from 'vue';
import { mobileRecords } from '../lib/mobileHost';
import type { ChatTurn } from '../types';
import type { FocusWebApiPort } from './api';
import { FocusApiError, type FocusProjectionEvent, type FocusThreadSnapshot } from './types';
import { classifyRecordTurn, foldRecordPage, recordHash, type RecordItem, type ToolCount } from './mobileRecordPage';
import { readTranscriptTarget } from './transcriptRead';

interface ReaderIntent {
  id: string; op: string; thread: string; group: ToolCount; item?: string;
  anchor?: { turn: string; item: string; reading: boolean };
}
interface Context {
  snapshot(): FocusThreadSnapshot | null;
  selected(): string;
  connected(): boolean;
  turns(): readonly ChatTurn[];
  selectOpen(thread: string): Promise<boolean>;
  locate(turn: string, item: string): Promise<string | null>;
}

function storage(op: string, data: object = {}): Record<string,string>[] {
  const reply = mobileRecords(op,data);
  if (!reply || !reply.startsWith('[')) throw new Error('记录已停止写入，或本机记录空间已满');
  return JSON.parse(reply);
}

export function installMobileRecords(api: Pick<FocusWebApiPort,'readTranscriptWindow'|'readMobileRecords'|'mobileReadScope'>, ctx: Context) {
  let scan: AbortController | undefined, expansion: AbortController | undefined;
  let pending: ReaderIntent | null = null;
  let selecting = '', retryMs = 1000;
  let retry: ReturnType<typeof setTimeout> | undefined;
  let timer: ReturnType<typeof setTimeout>, liveTimer: ReturnType<typeof setTimeout> | undefined;
  let paused = false, disposed = false, active = '';
  let writer: Record<string,string> | null = null;
  const current = () => !disposed && !paused && document.visibilityState !== 'hidden'
    && ctx.snapshot()?.thread.id === ctx.selected() && !!ctx.selected();
  const online = () => current() && ctx.connected() && !!api.mobileReadScope;
  const stop = () => { clearTimeout(retry); scan?.abort(); expansion?.abort(); clearTimeout(timer); clearTimeout(liveTimer); liveTimer = undefined; writer = null; };
  const reply = (id: string, value: object) => mobileRecords('result',{id,...value});

  async function capture(signal: AbortSignal) {
    const thread = ctx.selected(), snap = ctx.snapshot()!, scope = api.mobileReadScope!;
    const key = await recordHash(thread);
    signal.throwIfAborted();
    const state = storage('capture',{scope,key})[0];
    if (!state) return;
    const read = api.readMobileRecords?.bind(api);
    if (!read || snap.thread.history_mode !== 'paginated' || snap.thread.ephemeral) {
      mobileRecords('note',{note:'unsupported'}); return;
    }
    const base = { thread, scope, fence:state.fence!, key, run:String(crypto.randomUUID()) };
    const first = await read(thread,null,signal);
    const fingerprint = (p: typeof first) => recordHash(JSON.stringify(p.rows));
    const head = await fingerprint(first);
    const mark = JSON.stringify([first.epoch,first.mark]);
    const check = (page: typeof first) => {
      signal.throwIfAborted();
      if (!online() || ctx.selected() !== thread || page.scope !== scope || page.thread !== thread
        || page.epoch !== snap.runtime_epoch) throw new Error('线程或授权已变化');
    };
    check(first);
    const previous = storage('checkpoint',{...base,mark,head})[0];
    let page = first, seq = 0, edge: ToolCount | null = null;
    if (previous?.complete === '1') {
      writer = {...base,run:previous.run!}; return;
    }
    if (previous?.oldest) {
      const [turn,item] = JSON.parse(previous.oldest) as [string,string];
      const target = await readTranscriptTarget(api,thread,first.epoch,{turn_id:turn,item_id:item},signal,online);
      const anchor = target.turns[0];
      if (anchor?.rawTurnId === turn && anchor.itemId === item && target.older_cursor) {
        page = await read(thread,target.older_cursor,signal); check(page);
        if (page.mark === first.mark) {
          base.run = previous.run!; seq = Number(previous.seq); edge = JSON.parse(previous.edge || 'null');
        } else page = first;
      }
    }
    if (!seq) storage('start',{...base,mark,head, title:(snap.thread.title || snap.thread.name || thread).slice(0,512), now:Date.now()});
    writer = base; mobileRecords('note',{note:''});
    const seen = new Set<string>();
    for (;;) {
      check(page);
      if (page.mark !== first.mark) { schedule(1500); return; }
      const folded = await foldRecordPage(page.rows,edge);
      edge = folded.edge;
      // Bound single SQLite/CursorWindow and native prompt payloads. A very long
      // message is split at a Unicode character boundary and rejoined by identity.
      const rows: ((RecordItem & {part?: number}) | ToolCount)[] = [];
      for (const row of folded.body) {
        if ('text' in row && row.text && row.text.length > 32000) {
          const chunks = row.text.match(new RegExp('.{1,32000}','gsu'))!;
          for (let i=chunks.length-1; i>=0; i--) rows.push({...row,part:i,text:chunks[i]});
        } else rows.push(row);
      }
      let batch: typeof rows = [], size = 0;
      function write(carry: ToolCount | null, boundary = false) {
        check(page);
        storage('write',{...base, seq:seq++, body:JSON.stringify(batch), edge:carry ? JSON.stringify(carry) : '', oldest:boundary && page.oldest ? JSON.stringify(page.oldest) : ''});
        batch = []; size = 0;
      }
      for (const row of rows) {
        const cost = JSON.stringify(row).length;
        if (batch.length && size+cost > 64000) write(null);
        batch.push(row); size += cost;
      }
      write(edge,true);
      if (!page.older) break;
      if (seen.has(page.older)) throw new Error('历史页没有前进');
      seen.add(page.older);
      await new Promise(resolve => setTimeout(resolve,120));
      signal.throwIfAborted();
      page = await read(thread,page.older,signal);
    }
    if (first.older) {
      const verified = await read(thread,null,signal);
      check(verified);
      if (verified.mark !== first.mark || await fingerprint(verified) !== head) { schedule(650); return; }
    }
    check(page);
    storage('finish',base);
  }

  function schedule(delay = 150) {
    clearTimeout(timer);
    if (!online()) return;
    timer = setTimeout(() => {
      scan?.abort();
      scan = new AbortController();
      const signal = scan.signal;
      void capture(signal).catch(error => {
        if (signal.aborted || !online()) return;
        if (error instanceof FocusApiError && error.status === 401) mobileRecords('lock');
        else if (error instanceof TypeError || (error instanceof FocusApiError && (error.status >= 500 || error.code === 'stale_thread_read'))) schedule(3500);
        else mobileRecords('note',{note:error instanceof FocusApiError ? 'unsupported' : 'paused'});
      });
    },delay);
  }

  function live() {
    if (!writer || !current() || writer.thread !== ctx.selected()) return;
    if (liveTimer !== undefined) return;
    liveTimer = setTimeout(() => {
      liveTimer = undefined;
      if (!writer || !current() || writer.thread !== ctx.selected()) return;
      const turn = ctx.snapshot()?.active_turn_id;
      const items = ctx.turns().filter(r => r.rawTurnId === turn && r.role === 'assistant'
        && r.reply?.state === 'generating' && r.text).slice(-1).map(classifyRecordTurn);
      const latest = items[0];
      if (latest?.text) mobileRecords('live',{...writer,body:JSON.stringify([{...latest,text:latest.text.slice(0,96000),partial:true}])});
    },400);
  }

  async function expand(intent: ReaderIntent, signal: AbortSignal) {
    const {group:g,thread} = intent, epoch = ctx.snapshot()!.runtime_epoch;
    const valid = () => !signal.aborted && online() && pending?.id === intent.id && ctx.selected() === thread;
    const members: ChatTurn[] = [];
    // The first surviving stable item selects this group, even when an adjacent group has the same count.
    const consume = (rows: readonly ChatTurn[], start: boolean) => {
      let found = !start;
      for (const row of rows) {
        if (!found) found = row.rawTurnId === g.turn && row.itemId === g.first;
        if (!found) continue;
        if (row.rawTurnId !== g.turn) break;
        const item = classifyRecordTurn(row);
        if (!item) continue;
        if (item.kind !== 'tool') break;
        members.push(row);
        if (members.length === g.count) return true;
      }
      return false;
    };
    const verify = async () => {
      const folded = await foldRecordPage(members.map(r=>classifyRecordTurn(r)!),null);
      return folded.edge?.hash === g.hash && folded.edge.last === g.last && folded.edge.count === g.count;
    };
    let matched = consume(ctx.turns(),true) && await verify();
    if (!matched) {
      members.length = 0;
      if (!online()) { reply(intent.id,{waiting:true}); return; }
      let page = await readTranscriptTarget(api,thread,epoch,{turn_id:g.turn,item_id:g.first},signal,valid);
      const seen = new Set<string>();
      let first = true;
      for (;;) {
        // Do not walk through a semantic break and accidentally join a different run.
        const from = first ? page.turns.findIndex(row=>row.rawTurnId === g.turn && row.itemId === g.first) : 0;
        if (from < 0) break;
        const count = members.length;
        if (consume(page.turns.slice(from),false)) { matched = await verify(); break; }
        if (page.turns.slice(from).some(row=>row.rawTurnId !== g.turn || (classifyRecordTurn(row)?.kind ?? 'tool') !== 'tool')) break;
        if (!page.newer_cursor || seen.has(page.newer_cursor) || members.length === count && !page.turns.length) break;
        seen.add(page.newer_cursor);
        page = await readTranscriptTarget(api,thread,epoch,{cursor:page.newer_cursor,direction:'asc'},signal,valid);
        first = false;
      }
    }
    if (signal.aborted || pending?.id !== intent.id || ctx.selected() !== thread) return;
    if (!matched) { reply(intent.id,{error:'历史已变化，无法核对此工具组'}); return; }
    if (intent.op === 'detail') {
      if (!members.some(r=>r.itemId === intent.item)) return;
      const full = await readTranscriptTarget(api,thread,epoch,{turn_id:g.turn,item_id:intent.item,full:true},signal,valid);
      const text = full.full_text ?? '';
      for (let start=0; valid() && (start===0 || start<text.length); start+=24000)
        reply(intent.id,{text:text.slice(start,start+24000),append:start>0});
    } else for (let start=0;start<members.length;start+=32) {
      reply(intent.id,{append:start>0,tools:members.slice(start,start+32).map(r=>({item:r.itemId,name:r.tools![0]!.name,arg:r.tools![0]!.arg}))});
    }
  }

  async function openOnline(intent: ReaderIntent, signal: AbortSignal) {
    const anchor = intent.anchor;
    if (anchor?.turn && anchor.item) {
      const target = await ctx.locate(anchor.turn,anchor.item);
      if (signal.aborted || pending?.id !== intent.id || !online()) return;
      if (!target) { reply(intent.id,{error:'此阅读位置暂时无法在线核对。',missingPosition:true}); return; }
      window.dispatchEvent(new CustomEvent('focus-record-position',{detail:{thread:intent.thread,target,reading:anchor.reading}}));
    }
    if (!signal.aborted && pending?.id === intent.id && online()) reply(intent.id,{open:true});
  }

  function attempt() {
    clearTimeout(retry);
    expansion?.abort();
    const intent = pending;
    if (!intent || paused || disposed || !ctx.connected()) return;
    if (ctx.selected() !== intent.thread) {
      if (!ctx.connected() || selecting) return;
      selecting = intent.thread;
      void ctx.selectOpen(intent.thread).then(ok => {
        if (pending?.id !== intent.id) return;
        if (ok) attempt();
        else { pending=null; reply(intent.id,{error:'线程尚未在线打开，或当前对话还不能切换。'}); }
      }).finally(()=>{selecting='';});
      return;
    }
    if (!current()) return;
    expansion = new AbortController();
    const signal = expansion.signal;
    void (intent.op === 'online' ? openOnline(intent,signal) : expand(intent,signal)).catch(error=>{
      if (signal.aborted || pending?.id !== intent.id) return;
      if (error instanceof TypeError || error instanceof FocusApiError && (error.status >= 500 || error.code === 'stale_thread_read')) {
        reply(intent.id,{waiting:true}); retry=setTimeout(attempt,retryMs); retryMs=Math.min(30000,retryMs*2);
      } else reply(intent.id,{error:error instanceof FocusApiError && error.status===401 ? '需要重新授权' : '此历史已变化或不支持精确定位'});
    });
  }

  function action(e: Event) {
    const data = (e as CustomEvent<ReaderIntent>).detail;
    if (data?.op === 'probe') {
      if (online()) mobileRecords('ready',{thread:ctx.selected()});
      return;
    }
    clearTimeout(retry); retryMs=1000; expansion?.abort(); pending=null;
    if (data?.op === 'save' && data.thread===ctx.selected()) {
      void recordHash(data.thread).then(key=>{if(data.thread===ctx.selected()){mobileRecords('allow',{key});schedule(0);}}); return;
    }
    if (data?.op === 'refresh') { if(data.thread===ctx.selected()) mobileRecords('touch',{thread:data.thread,now:Date.now()}); schedule(0); return; }
    if (!data || !data.thread || !data.id) return;
    if (data.op !== 'online' && (!['expand','detail'].includes(data.op) || data.group?.v !== 1)) return;
    pending=data; reply(data.id,{waiting:true}); attempt();
  }
  window.addEventListener('focus-record-action',action);
  const unwatch = watch([ctx.selected,ctx.connected,()=>ctx.snapshot()?.thread.id],() => {
    stop();
    if (active !== ctx.selected()) { if (active && (!selecting || (ctx.selected() && ctx.selected() !== selecting))) pending = null; active = ctx.selected(); }
    if (ctx.connected() && !active) mobileRecords('ready',{thread:''});
    if (online()) {
      mobileRecords('touch',{thread:active,now:Date.now()});
      mobileRecords('ready',{thread:active});
      attempt(); schedule(300);
    }
  });
  return {
    live,
    event(e: FocusProjectionEvent) {
      if (e.type === 'session_expired' && e.reason === 'session_revoked') mobileRecords('revoke',{scope:api.mobileReadScope});
      if (!e.thread_id) return;
      if (['thread/closed','thread/archived','thread/deleted','web_thread_closed'].includes(e.reason ?? ''))
        mobileRecords('closed',{thread:e.thread_id});
      if (e.reason === 'thread/reverted' || e.reason === 'web_thread_revert_unconfirmed') {
        mobileRecords('revert',{thread:e.thread_id});
        if (e.thread_id === ctx.selected()) { stop(); pending = null; schedule(500); }
      } else if (e.thread_id === ctx.selected() && ['turn/completed','item/completed','web_prompt_succeeded'].includes(e.reason ?? '')) schedule(1500);
    },
    pause() { paused = true; stop(); },
    park() { pending = null; paused = true; stop(); },
    resume() { paused = false; attempt(); schedule(350); },
    deliberate(thread: string) { void recordHash(thread).then(key => {
      if (current() && thread === ctx.selected()) { mobileRecords('allow',{key}); schedule(200); }
    }); },
    dispose() { disposed = true; stop(); unwatch(); window.removeEventListener('focus-record-action',action); },
  };
}
