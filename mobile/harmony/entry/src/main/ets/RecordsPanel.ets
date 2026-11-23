import { webview } from '@kit.ArkWeb';
import { common } from '@kit.AbilityKit';
import { Site, sitePrefs } from './Sites';
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
  cold: boolean = false;
}

@Component
export struct RecordsPanel {
  sites: Site[] = [];
  entry: string = '';
  thread: string = '';
  cold: boolean = false;
  activeEntry: string = '';
  controls: ReaderControls = new ReaderControls();
  action: (op: string, data: string) => void = () => {};
  private alive: boolean = true;
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
        const init = new ReaderInit(); init.sites=this.sites; init.active=this.activeEntry; init.current=sitePrefs(this.ctx()).getSync('thread.'+this.activeEntry,'') as string; init.entry=this.entry; init.thread=this.thread; init.cold=this.cold;
        e.result.handlePromptConfirm(JSON.stringify(init)); return;
      }
      const data = JSON.parse(e.value) as Record<string,string>;
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
    Web({src:$rawfile('records.html'), controller:this.controls.controller})
      .width('100%').height('100%').javaScriptAccess(true).domStorageAccess(false).fileAccess(false).mixedMode(MixedMode.None)
      .onLoadIntercept(e=>e.data.isMainFrame() && !this.local(e.data.getRequestUrl(),'records.html'))
      .onInterceptRequest(e=>{
        if (this.local(e.request.getRequestUrl(),e.request.isMainFrame()?'records.html':'records.js')) return null;
        const denied=new WebResourceResponse(); denied.setResponseData(''); denied.setResponseCode(403);
        denied.setReasonMessage('Forbidden'); denied.setResponseMimeType('text/plain'); denied.setResponseEncoding('utf-8');
        return denied;
      }).onPrompt(e=>{void this.command(e); return true;})
  }
}
