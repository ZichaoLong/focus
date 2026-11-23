import { afterEach, describe, expect, it, vi } from 'vitest';
import { nextTick, ref } from 'vue';
import { hasMobileFeature, mobileRecords } from '../src/lib/mobileHost';
import { installMobileRecords } from '../src/focus/mobileRecords';
import type { FocusThreadSnapshot } from '../src/focus/types';
import { classifyRecordTurn, decodeRecordPage, foldRecordPage, type ToolCount, type RecordItem } from '../src/focus/mobileRecordPage';
import { projectTranscriptToolGroups } from '../src/components/toolGroupPresentation';
import type { ChatTurn } from '../src/types';

const tool=(item:string,turn='one'):RecordItem=>({kind:'tool',turn,item});
const ids=Array.from({length:80},(_,i)=>'tool-'+i);

vi.mock('../src/lib/mobileHost',()=>({mobileRecords:vi.fn(),hasMobileFeature:vi.fn(()=>false)}));

describe('compact mobile thread records',()=>{
  it('preserves the same ordered membership across pages and stores constant-size locators',async()=>{
    const items=ids.map(id=>tool(id));
    const all=(await foldRecordPage(items,null)).edge!;
    let edge:ToolCount|null=null;
    for(let end=80;end>0;end-=13)edge=(await foldRecordPage(items.slice(Math.max(0,end-13),end),edge)).edge;
    expect(edge).toEqual(all);
    expect(edge?.count).toBe(80);
    expect(Object.values(edge!)).not.toContain(ids[40]);
    const changed=[...items];changed[40]=tool('changed');
    expect((await foldRecordPage(changed,null)).edge?.hash).not.toBe(edge?.hash);
    expect((await foldRecordPage(items.slice(0,79),null)).edge?.hash).not.toBe(edge?.hash);
    const append=[...items,tool('80'),tool('81'),tool('82')];
    expect((await foldRecordPage(append.slice(0,all.count),null)).edge).toEqual(all);
    expect((await foldRecordPage(append,null)).edge?.count).toBe(83);
  });
  it('agrees with Web groups across whitespace targets, visible reasoning, turns and intermediate replies',async()=>{
    const row=(id:string,rawTurnId='one'):ChatTurn=>({id,rawTurnId,itemId:id,role:'assistant',text:'',no:0});
    const tools=(name:string)=>ids.map(id=>({...row(name+id),contentDeferred:true,tools:[{id,name:'private',arg:'private',status:'done' as const}]}));
    const turns:ChatTurn[]=[...tools('a'),row('empty'),{...row('separator'),thinking:'visible'},...tools('b'),
      {...row('intermediate'),text:'intermediate'},{...tools('c')[0]!,rawTurnId:'two'}];
    const groups=projectTranscriptToolGroups(turns);
    const records=await foldRecordPage(turns.map(classifyRecordTurn).filter((r):r is RecordItem=>r!==null),null);
    const saved=[...records.body,...records.edge?[records.edge]:[]].filter((r):r is ToolCount=>r.kind==='tools').reverse();
    expect(saved.map(r=>r.count)).toEqual([...groups.leaders.values()].map(g=>g.tools.length));
    expect(saved.map(r=>r.count)).toEqual([80,80,1]);
    expect(saved[0]!.hash).not.toBe(saved[1]!.hash);
    expect(JSON.stringify(saved)).not.toContain('private');
    expect(classifyRecordTurn({...row('delta'),text:'a',reply:{state:'generating'}})?.partial).toBe(true);
  });
  it('rejects unsupported protocol and malformed locators',()=>{
    const page={version:1,epoch:'e',scope:'a'.repeat(64),mark:'1:2',thread:'t',oldest:['one','first'],older:null,rows:[tool('first')]};
    expect(decodeRecordPage(page)).toEqual(page);
    expect(decodeRecordPage({...page,oldest:['first']})).toBeNull();
    expect(decodeRecordPage({...page,version:2})).toBeNull();
  });
});

describe('foreground mobile reader',()=>{
  const scope='d'.repeat(64);
  function fixture() {
    vi.stubGlobal('window',new EventTarget());
    vi.stubGlobal('document',{visibilityState:'visible'});
    const connected=ref(false);
    const snapshot={thread:{id:'thread',history_mode:'paginated'},runtime_epoch:'epoch',active_turn_id:'one'} as FocusThreadSnapshot;
    const turns:ChatTurn[]=[{id:'reply',rawTurnId:'one',itemId:'reply',no:0,role:'assistant',text:'partial',reply:{state:'generating'}}];
    const api={mobileReadScope:scope,readTranscriptWindow:vi.fn(),readMobileRecords:vi.fn(async()=>({
      version:1 as const,epoch:'epoch',scope,mark:'1:2',thread:'thread',oldest:null,older:null,rows:[],
    }))};
    const ctx={snapshot:()=>snapshot, selected:()=>snapshot.thread.id, connected:()=>connected.value, turns:()=>turns,
      selectOpen:vi.fn(async()=>false), locate:vi.fn(async()=> 'rendered')};
    const host=vi.mocked(mobileRecords).mockReset();
    host.mockImplementation(op => op==='capture' ? '[{"fence":"2"}]' : op==='checkpoint' ? '[{"run":"saved","complete":"1"}]' : '[]');
    const owner=installMobileRecords(api,ctx);
    const action=(detail:object)=>window.dispatchEvent(new CustomEvent('focus-record-action',{detail}));
    return {owner,host,connected,action,api,ctx};
  }
  afterEach(()=>vi.unstubAllGlobals());
  it('passes scoped lifecycle changes to a capable shell and preserves the older close signal',()=>{
    const {owner,host}=fixture();
    const feature=vi.mocked(hasMobileFeature);
    const event=(reason:string)=>owner.event({type:'thread_invalidated',thread_id:'other',reason,runtime_epoch:'epoch',revision:1});
    try {
      event('thread/archived');
      expect(host).toHaveBeenCalledWith('closed',{thread:'other'});
      host.mockClear();
      feature.mockImplementation(name=>name==='record-states');
      for(const [reason,state] of [['thread/archived','archived'],['thread/deleted','deleted'],
        ['web_thread_closed','closed'],['web_thread_opened','opened'],['thread/unarchived','unarchived']] as const) {
        event(reason);
        expect(host).toHaveBeenLastCalledWith('lifecycle',{thread:'other',reason:state,scope});
      }
      expect(host).not.toHaveBeenCalledWith('closed',expect.anything());
    } finally { feature.mockReturnValue(false); owner.dispose(); }
  });
  it('uses the accepted head for a complete edition without downloading its messages again',async()=>{
    const {owner,connected,api}=fixture();
    try {
      owner.acceptHead({thread_id:'thread',turn_id:null,view:'transcript',revision:2,runtime_epoch:'epoch',
        readingMark:'1:2',older_cursor:null,newer_cursor:null,target_pending:false,full_text:null,turns:[]});
      connected.value=true;
      await vi.waitFor(()=>expect(mobileRecords).toHaveBeenCalledWith('checkpoint',expect.anything()));
      expect(api.readMobileRecords).not.toHaveBeenCalled();
    } finally { owner.dispose(); }
  });
  it('reattaches live partial text to a completed edition after parking',async()=>{
    const {owner,host,connected,api}=fixture();
    try {
      connected.value=true;
      await vi.waitFor(()=>expect(host).toHaveBeenCalledWith('checkpoint',expect.anything()));
      owner.pause(); host.mockClear(); owner.resume();
      await vi.waitFor(()=>expect(host).toHaveBeenCalledWith('checkpoint',expect.anything()));
      owner.live();
      await vi.waitFor(()=>expect(host).toHaveBeenCalledWith('live',expect.objectContaining({run:'saved',body:expect.stringContaining('partial')})));
      expect(api.readMobileRecords).toHaveBeenCalledTimes(2);
      expect(host).not.toHaveBeenCalledWith('write',expect.anything());
    } finally { owner.dispose(); }
  });
  it('keeps only the last offline intent and never selects a closed thread for writing',async()=>{
    const {owner,connected,action,host,api,ctx}=fixture();
    try {
      const group=(await foldRecordPage([tool('first')],null)).edge!;
      action({id:'old',op:'expand',thread:'thread',group});
      action({op:'cancel'});
      connected.value=true; await nextTick();
      expect(api.readTranscriptWindow).not.toHaveBeenCalled();
      action({id:'closed',op:'online',thread:'missing'});
      await vi.waitFor(()=>expect(host).toHaveBeenCalledWith('result',expect.objectContaining({id:'closed',error:expect.any(String)})));
      expect(ctx.selectOpen).toHaveBeenCalledOnce();
      action({id:'open',op:'online',thread:'thread',anchor:{turn:'one',item:'first'}});
      await vi.waitFor(()=>expect(host).toHaveBeenCalledWith('result',{id:'open',open:true}));
      expect(ctx.locate).toHaveBeenCalledWith('one','first');
    } finally { owner.dispose(); }
  });
});

describe('saved messages in the ordinary conversation', () => {
  it('reads and pages while open is held, then adopts the authoritative item exactly once',async () => {
    const { createFocusTranscript } = await import('../src/focus/focusTranscript');
    const scope='e'.repeat(64);
    const feature=vi.mocked(hasMobileFeature);
    feature.mockImplementation(name=>name==='conversation-windows');
    const stored=(item:string,text:string)=>({kind:'assistant',turn:'turn',item,text});
    const native=vi.mocked(mobileRecords).mockReset().mockImplementation((op,data)=>{
      const request=data as {direction:string};
      if(op!=='readwindow') return 'ok';
      return JSON.stringify({thread:'t',title:'saved',anchor:{},older:true,newer:false,
        rows:request.direction==='older'?[stored('0','older')]:[stored('1','cached')]});
    });
    const thread=ref('');
    const snapshot=ref<FocusThreadSnapshot|null>(null);
    const read=vi.fn(async () => ({thread_id:'t',turn_id:null,runtime_epoch:'e',revision:3,view:'transcript' as const,
      target_pending:false,turns:[{id:'turn:item:1:0',rawTurnId:'turn',itemId:'1',role:'assistant' as const,text:'updated',no:0}],
      older_cursor:null,newer_cursor:null,full_text:null}));
    const owner=createFocusTranscript({api:{mobileReadScope:scope,readTranscriptWindow:read},snapshot,activeThreadId:thread,isDisposed:()=>false});
    try {
      thread.value='t'; await nextTick();
      expect(owner.visibleTurns.value.map(t=>t.text)).toEqual(['cached']);
      expect(await owner.older()).toBe(true);
      expect(owner.visibleTurns.value.map(t=>t.text)).toEqual(['older','cached']);
      expect(read).not.toHaveBeenCalled();
      owner.updateViewport(null,true);
      snapshot.value={runtime_epoch:'e',thread:{id:'t',history_mode:'paginated'},revision:3} as FocusThreadSnapshot;
      await vi.waitFor(()=>expect(owner.visibleTurns.value.map(t=>t.text)).toEqual(['updated']));
      expect(native).toHaveBeenCalledWith('putwindow',expect.objectContaining({thread:'t',scope,tail:true}));
      thread.value='another';
      await nextTick();
      expect(owner.visibleTurns.value).toEqual([]);
    } finally { owner.dispose(); feature.mockReturnValue(false); }
  });
});
