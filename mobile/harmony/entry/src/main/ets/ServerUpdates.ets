import { common } from '@kit.AbilityKit';
import { webview } from '@kit.ArkWeb';
import { url } from '@kit.ArkTS';
import { Site, savedLogin, basicRealm, sitePrefs } from './Sites';

class BatchCall {
  id: string = '';
  action: string = '';
  site: string = '';
  body: Record<string, string> = {};
}

class SavedOperation {
  install: string = '';
  op: string = '';
  version?: string;
  request?: string;
  until?: number;
  sent: boolean = false;
}
class ManagerData {
  channel: string = 'installed';
  records: Record<string, SavedOperation> = {};
  sites: Site[] = [];
}

function denied(): WebResourceResponse {
  const res = new WebResourceResponse();
  res.setResponseData(''); res.setResponseCode(403); res.setReasonMessage('Forbidden');
  res.setResponseMimeType('text/plain'); res.setResponseEncoding('utf-8');
  return res;
}

@Component
struct UpdateAgent {
  site: Site = new Site();
  call: BatchCall = new BatchCall();
  finish: (result: string) => void = () => {};
  private controller: webview.WebviewController = new webview.WebviewController();
  @State private epoch: number = 0;
  private phase: string = 'probe';
  private realm: string | undefined;
  private challenged: boolean = false;
  private attempted: boolean = false;
  private dispatched: boolean = false;
  private closed: boolean = false;
  private timeout: number = -1;
  private timer: number = -1;
  private probe(): string { return this.site.origin + '/focus-connect.txt'; }
  private agent(): string { return this.site.origin + '/focus-update.html'; }
  private address(): string { return this.phase === 'agent' ? this.agent() : this.probe(); }

  aboutToAppear(): void {
    this.phase = this.site.origin.startsWith('https:') ? 'probe' : 'agent';
    this.timeout = setTimeout(() => this.fail('连接超时，稍后核对服务端记录'),15000);
  }
  aboutToDisappear(): void { this.closed = true; clearTimeout(this.timeout); clearTimeout(this.timer); }
  private complete(value: string): void {
    if (!this.closed) { this.closed = true; clearTimeout(this.timeout); clearTimeout(this.timer); this.finish(value); }
  }
  private login(message: string): void { this.complete(JSON.stringify({error:message, needs_entry:true})); }
  private fail(message: string): void { this.complete(JSON.stringify({error:message})); }
  private next(phase: string): void {
    this.phase = phase; this.controller = new webview.WebviewController(); this.epoch++;
  }
  private async challenge(e: OnHttpAuthRequestEvent, epoch: number): Promise<void> {
    if (this.closed || epoch !== this.epoch || !this.site.origin.startsWith('https:') ||
      e.host.toLowerCase() !== new url.URL(this.site.origin).hostname.toLowerCase()) { e.handler.cancel(); return; }
    if (this.phase === 'probe') {
      this.challenged = true; this.realm = e.realm; e.handler.cancel(); return;
    }
    if (this.phase !== 'verified' || this.attempted || this.realm !== e.realm) {
      e.handler.cancel(); this.login('请打开实例验证入口凭据'); return;
    }
    this.attempted = true;
    try {
      const login = await savedLogin(this.site,e.realm);
      if (this.closed || epoch !== this.epoch || !login) { e.handler.cancel(); this.login('请打开实例完成入口认证'); return; }
      e.handler.confirm(login.user,login.password);
    } catch { e.handler.cancel(); this.fail('暂时无法核验入口认证'); }
  }
  private httpError(e: OnHttpErrorReceiveEvent, epoch: number): void {
    if (this.closed || epoch !== this.epoch || !e.request.isMainFrame()) return;
    const code = e.response.getResponseCode();
    if (code === 401 && this.phase === 'probe' && e.request.getRequestUrl() === this.probe()) {
      const headers = e.response.getResponseHeader().filter((h: Header) => h.headerKey.toLowerCase() === 'www-authenticate');
      const seen = headers.length === 1 ? basicRealm(headers[0].headerValue) : undefined;
      if (seen !== undefined && (!this.challenged || this.realm === seen)) {
        this.realm = seen; this.next('verified'); return;
      }
    }
    if (code === 401 || code === 403) this.login('请打开实例完成登录或授权');
    else if (code === 404 && this.phase === 'agent') this.login('此服务端未提供批量管理，请在实例设置中查看服务端更新');
    else this.fail('入口返回 HTTP ' + code);
  }
  private allowed(req: WebResourceRequest, epoch: number): boolean {
    const address = req.getRequestUrl();
    if (this.closed || this.epoch !== epoch) return false;
    if (req.isMainFrame()) return this.address() === address;
    if (this.phase !== 'agent') return false;
    if (req.getRequestMethod() === 'GET') return address.startsWith(this.site.origin + '/assets/') ||
      address === this.site.origin + '/api/update/installation';
    return req.getRequestMethod() === 'POST' && (address === this.site.origin + '/api/client/register' ||
      (this.call.action === 'prepare' && address === this.site.origin + '/api/update/prepare-latest') ||
      (this.call.action === 'apply' && address === this.site.origin + '/api/update/apply'));
  }
  private async poll(): Promise<void> {
    if (this.closed) return;
    try {
      const reply = await this.controller.runJavaScript('location.href===' + JSON.stringify(this.agent()) + ' && window.focusUpdateReply || ""');
      if (reply && reply !== 'null') {
        const data = JSON.parse(reply) as BatchCall;
        if (reply.length > 65536 || data.id !== this.call.id) throw Error('id');
        this.complete(reply);
      } else this.timer = setTimeout(() => this.poll(),200);
    } catch { this.fail('无法核验更新响应'); }
  }
  private async loaded(address: string, epoch: number): Promise<void> {
    if (this.closed || epoch !== this.epoch || address !== this.address()) return;
    if (this.phase !== 'agent') {
      if (this.phase === 'probe' ? !this.challenged : this.attempted) this.next('agent');
      return;
    }
    if (this.dispatched) return;
    this.dispatched = true; clearTimeout(this.timeout);
    this.timeout = setTimeout(() => this.fail('连接超时，稍后核对服务端记录'),this.call.action === 'prepare' ? 75000 : 15000);
    const args = JSON.stringify(this.call.id) + ',' + JSON.stringify(this.call.action) + ',' + JSON.stringify(this.call.body);
    try {
      const ack = await this.controller.runJavaScript('location.href===' + JSON.stringify(this.agent()) +
        " && !!document.querySelector('meta[name=focus-update-agent][content=\"1\"]')" + ' && window.focusUpdateAgent?.(' + args + ')===true');
      if (ack === 'true') await this.poll(); else this.login('请打开实例登录，或先更新该服务端');
    } catch { this.fail('无法连接此实例'); }
  }
  build() {
    ForEach([this.epoch], (epoch: number) => {
      Web({src:this.address(), controller:this.controller})
        .width(1).height(1).javaScriptAccess(this.phase === 'agent').domStorageAccess(this.phase === 'agent')
        .fileAccess(false).mixedMode(MixedMode.None)
        .onLoadIntercept(e => {
          if (e.data.isMainFrame() && e.data.getRequestUrl() !== this.address()) {
            if (epoch === this.epoch) this.login('入口发生跳转，请打开实例完成登录');
            return true;
          }
          return false;
        })
        .onInterceptRequest(e => { if (!this.allowed(e.request,epoch)) return denied(); return null; })
        .onHttpAuthRequest(e => { void this.challenge(e,epoch); return true; })
        .onHttpErrorReceive(e => this.httpError(e,epoch))
        .onErrorReceive(e => {
          if (epoch === this.epoch && e.request.isMainFrame() && !(this.phase === 'probe' && this.challenged)) this.fail('入口暂不可达，请核对网络');
        })
        .onPageEnd(e => this.loaded(e.url,epoch))
        .onRenderExited(() => { if (epoch === this.epoch) this.fail('网页进程已退出，请重新核对服务端状态'); })
        .onAlert(e => { e.result.handleCancel(); return true; })
        .onConfirm(e => { e.result.handleCancel(); return true; })
        .onPrompt(e => { e.result.handleCancel(); return true; })
    }, (epoch: number) => epoch.toString())
  }
}

@Component
export struct ServerUpdates {
  sites: Site[] = [];
  close: () => void = () => {};
  open: (site: Site) => void = () => {};
  @StorageLink('focusForeground') @Watch('lifecycle') private foreground: boolean = true;
  @State private jobs: BatchCall[] = [];
  private panel: webview.WebviewController = new webview.WebviewController();
  private ctx(): common.UIAbilityContext { return getContext(this) as common.UIAbilityContext; }
  private lifecycle(): void {
    if (!this.foreground) this.jobs = [];
    this.panel.runJavaScript('window.focusBatchActive?.(' + this.foreground.toString() + ')').catch(() => {});
  }
  private local(address: string, file: string): boolean {
    return (address.startsWith('resource://') || address.startsWith('file://')) && address.endsWith('/' + file);
  }
  private async command(e: OnPromptEvent): Promise<void> {
    if (!this.foreground || !this.local(e.url,'server-updates.html') || !this.local(this.panel.getUrl(),'server-updates.html')) {
      e.result.handleCancel(); return;
    }
    const prefs = sitePrefs(this.ctx());
    try {
      if (e.message === 'focus-updates/init') {
        const data = new ManagerData(); data.sites = this.sites; data.channel = prefs.getSync('batch-channel','installed') as string;
        this.sites.forEach((site: Site) => {
          const value = prefs.getSync('batch.' + site.id,'') as string;
          if (value) data.records[site.id] = JSON.parse(value) as SavedOperation;
        });
        e.result.handlePromptConfirm(JSON.stringify(data)); return;
      }
      if (e.message === 'focus-updates/save') {
        const data = JSON.parse(e.value) as ManagerData;
        prefs.putSync('batch-channel',data.channel);
        this.sites.forEach((site: Site) => {
          const record = data.records[site.id];
          if (record) prefs.putSync('batch.' + site.id,JSON.stringify(record)); else prefs.deleteSync('batch.' + site.id);
        });
        await prefs.flush(); e.result.handlePromptConfirm('ok'); return;
      }
      if (e.message === 'focus-updates/back') { e.result.handlePromptConfirm('ok'); setTimeout(() => this.close(),0); return; }
      if (e.message === 'focus-updates/open') {
        const site = this.sites.find((s: Site) => s.id === e.value);
        if (site) { e.result.handlePromptConfirm('ok'); setTimeout(() => this.open(site),0); return; }
      }
      if (e.message === 'focus-updates/request' && !this.jobs.length) {
        const call = JSON.parse(e.value) as BatchCall;
        if (/^[a-f0-9]{32}$/.test(call.id) && ['status','prepare','apply'].includes(call.action) && this.sites.some((s: Site) => s.id === call.site)) {
          e.result.handlePromptConfirm('ok'); this.jobs = [call]; return;
        }
      }
    } catch { /* Reject incomplete reads and writes. */ }
    e.result.handleCancel();
  }
  private result(call: BatchCall, data: string): void {
    if (!this.foreground || this.jobs[0]?.id !== call.id) return;
    this.jobs = [];
    this.panel.runJavaScript('window.focusBatchResult?.(' + JSON.stringify(call.id) + ',JSON.parse(' + JSON.stringify(data) + '))').catch(() => {});
  }
  build() {
    Stack() {
      ForEach(this.jobs, (job: BatchCall) => {
        UpdateAgent({site:this.sites.find((s: Site) => s.id === job.site), call:job, finish:(value: string) => this.result(job,value)})
      }, (job: BatchCall) => job.id)
      Web({src:$rawfile('server-updates.html'),controller:this.panel})
        .width('100%').height('100%').javaScriptAccess(true).fileAccess(false).mixedMode(MixedMode.None)
        .onLoadIntercept(e => e.data.isMainFrame() && !this.local(e.data.getRequestUrl(),'server-updates.html'))
        .onInterceptRequest(e => {
          if (!this.local(e.request.getRequestUrl(), e.request.isMainFrame() ? 'server-updates.html' : 'server-updates.js')) return denied();
          return null;
        })
        .onPrompt(e => { void this.command(e); return true; })
    }.width('100%').height('100%')
  }
}
