import { webview } from '@kit.ArkWeb';
import { common } from '@kit.AbilityKit';
import { Site, sitePrefs } from './Sites';
import { BatchCall, UpdateAgent } from './ServerUpdates';
import { recordAllowed, recordCall } from './RecordsStore';

export class ReaderControls {
  controller: webview.WebviewController = new webview.WebviewController();
  notify(value: string): void {
    this.controller.runJavaScript('window.focusRecordEvent?.(JSON.parse('+JSON.stringify(value)+'))').catch(()=>{});
  }
  back(): void { this.controller.runJavaScript('window.focusRecordBack?.()').catch(()=>{}); }
}

class ReaderInit {
  current: string = '';
  active: string = '';
  sites: Site[] = [];
  entry: string = '';
  thread: string = '';
}

@Component
export struct RecordsPanel {
  sites: Site[] = [];
  entry: string = '';
  thread: string = '';
  activeEntry: string = '';
  controls: ReaderControls = new ReaderControls();
  action: (op: string, data: string) => void = () => {};
  private alive: boolean = true;
  @StorageLink('focusForeground') @Watch('cancelCheck') private foreground: boolean = true;
  @State private jobs: BatchCall[] = [];
  private cancelCheck(): void { this.jobs=[]; }
  private checked(job: BatchCall, value: string): void {
    if (!this.alive || !this.foreground || this.jobs[0]?.id!==job.id) return;
    this.jobs=[];
    this.controls.controller.runJavaScript('window.focusRecordCheck?.('+JSON.stringify(job.id)+',JSON.parse('+JSON.stringify(value)+'))').catch(()=>{});
  }
  private ctx(): common.UIAbilityContext { return getContext(this) as common.UIAbilityContext; }
  private local(address: string, file: string): boolean {
    return address==='resource://rawfile/'+file || address==='file://'+this.ctx().resourceDir+'/rawfile/'+file;
  }
  private async command(e: OnPromptEvent): Promise<void> {
    try {
      if (!this.alive || !this.local(e.url,'records.html') || !this.local(this.controls.controller.getUrl(),'records.html')
        || !e.message.startsWith('records/1/')) { e.result.handleCancel(); return; }
      const op = e.message.substring(10);
      if (op === 'init') {
        for (const site of this.sites) await recordCall(this.ctx(),site.id,site.origin,'register',{});
        const init = new ReaderInit(); init.sites=this.sites; init.active=this.activeEntry; init.current=sitePrefs(this.ctx()).getSync('thread.'+this.activeEntry,'') as string; init.entry=this.entry; init.thread=this.thread;
        e.result.handlePromptConfirm(JSON.stringify(init)); return;
      }
      const data = JSON.parse(e.value) as Record<string,string>;
      if (op==='cancelcheck') { this.cancelCheck(); e.result.handlePromptConfirm('ok'); return; }
      if (op==='verify') {
        const job=JSON.parse(e.value) as BatchCall;
        const site=this.sites.find((s: Site)=>s.id===data['entry']);
        if (!site || !this.foreground) { e.result.handleCancel(); return; }
        const states=JSON.parse(await recordCall(this.ctx(),site.id,site.origin,'status',{})) as Record<string,string>[];
        if (!this.alive || !this.foreground || states[0]?.locked!=='0' || !/^[a-f0-9]{64}$/.test(job.body.scope) || states[0].scope!==job.body.scope) { e.result.handleCancel(); return; }
        job.site=site.id; job.action='record-status'; this.jobs=[job]; e.result.handlePromptConfirm('ok'); return;
      }
      if (op === 'action') {
        e.result.handlePromptConfirm('ok'); setTimeout(()=>{if(this.alive)this.action(data['op'],e.value);},0); return;
      }
      const site = this.sites.find((s: Site)=>s.id===data['entry']);
      if (!site || !recordAllowed(true,op)) { e.result.handleCancel(); return; }
      e.result.handlePromptConfirm(await recordCall(this.ctx(),site.id,site.origin,op,data,()=>this.alive));
    } catch { e.result.handleCancel(); }
  }
  aboutToDisappear(): void { this.alive=false; }
  build() {
    Stack() {
    ForEach(this.jobs,(job: BatchCall)=>{
      UpdateAgent({site:this.sites.find((s: Site)=>s.id===job.site),call:job,finish:(value: string)=>this.checked(job,value)})
    },(job: BatchCall)=>job.id)
    Web({src:$rawfile('records.html'), controller:this.controls.controller})
      .width('100%').height('100%').javaScriptAccess(true).domStorageAccess(false).fileAccess(false).mixedMode(MixedMode.None)
      .onLoadIntercept(e=>e.data.isMainFrame() && !this.local(e.data.getRequestUrl(),'records.html'))
      .onInterceptRequest(e=>{
        if (this.local(e.request.getRequestUrl(),e.request.isMainFrame()?'records.html':'records.js')) return null;
        const denied=new WebResourceResponse(); denied.setResponseData(''); denied.setResponseCode(403);
        denied.setReasonMessage('Forbidden'); denied.setResponseMimeType('text/plain'); denied.setResponseEncoding('utf-8');
        return denied;
      }).onPrompt(e=>{void this.command(e); return true;})
    }.width('100%').height('100%')
  }
}
