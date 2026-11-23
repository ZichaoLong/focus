import { webview } from '@kit.ArkWeb';
import { router } from '@kit.ArkUI';
import { KeyboardAvoidMode as WindowKeyboardAvoidMode } from '@ohos.arkui.UIContext';
import { common } from '@kit.AbilityKit';
import { util, url } from '@kit.ArkTS';
import { print } from '@kit.BasicServicesKit';
import { Site, Login, savedLogin, rememberLogin, forgetLogin, basicRealm, sitePrefs, siteOrigin, focusRoot, httpsOrigin } from './Sites';
import { recordAllowed, recordCall } from './RecordsStore';
import { RecordsPanel, ReaderControls } from './RecordsPanel';
import { FileExchange } from './FileExchange';

export class InstanceTab {
  site: Site;
  key: string = util.generateRandomUUID();
  link: string;
  readerThread: string = '';
  read: (thread: string) => void = () => {};
  back: () => void = () => {};
  park: () => void = () => {};
  constructor(site: Site, link: string) { this.site = site; this.link = link; }
}

@Component
export struct InstancePane {
  tab: InstanceTab = new InstanceTab(new Site(), '');
  @Prop @Watch('selectionChanged') active: boolean = true;
  showDrawer: (theme: string, fromRootBack: boolean) => void = () => {};
  leavePage: (retained: boolean) => void = () => {};
  private site: Site = new Site();
  @State private reader: boolean = false;
  private readerThread: string = '';
  private coldReader: boolean = false;
  private recordScopeConfirmed: boolean = false;
  private readerControls: ReaderControls = new ReaderControls();
  private leaving: boolean = false;
  @State private nativeSwitcher: boolean = false;
  private switcherTimer: number = -1;
  private controller: webview.WebviewController = new webview.WebviewController();
  private files: FileExchange = new FileExchange();
  @StorageLink('focusForeground') @Watch('foregroundChanged') private foreground: boolean = true;
  @State private phase: string = 'probe';
  @State private source: string = '';
  @State private epoch: number = 0;
  @State private message: string = '';
  @State private loginForm: boolean = false;
  @State private user: string = '';
  @State private password: string = '';
  @State private remember: boolean = false;
  private handler?: HttpAuthHandler;
  private observedRealm?: string;
  private challengedRealm?: string;
  private attempted: boolean = false;
  private manual: boolean = false;
  private previousBasicUser?: string;
  private supplied?: Login;
  private ticket: string = '';
  private link: string = '';
  private retry: number = -1;
  private delay: number = 1000;
  private needsNetwork: boolean = false;
  private rendererFailures: number = 0;
  private lastReauth: number = 0;
  private gone: boolean = false;
  private backRequest: number = 0;
  private pendingBack: number = 0;
  private ctx(): common.UIAbilityContext { return getContext(this) as common.UIAbilityContext; }
  private probeUrl(): string { return this.site.origin + '/focus-connect.txt'; }

  aboutToAppear(): void {
    this.getUIContext().setKeyboardAvoidMode(WindowKeyboardAvoidMode.RESIZE);
    this.site = this.tab.site;
    this.source = this.probeUrl();
    this.link = this.tab.link;
    this.tab.link = '';
    this.tab.read = (thread: string) => { this.readerThread=thread; this.coldReader=false; this.reader=true; };
    if(this.tab.readerThread) this.tab.read(this.tab.readerThread);
    else void this.restoreRecord();
    this.tab.back = () => this.back();
    this.tab.park = () => this.leave();
    this.awaitWebSwitcher();
  }

  private async restoreRecord(): Promise<void> {
    const site=this.site;
    try {
      await recordCall(this.ctx(),site.id,site.origin,'register',{});
      const thread=sitePrefs(this.ctx()).getSync('thread.'+site.id,'') as string;
      const query: Record<string,string> = {}; query['thread']=thread;
      if (!this.link && thread && await recordCall(this.ctx(),site.id,site.origin,'book',query) !== '[]'
        && this.active && !this.gone && !this.ticket) {
        this.readerThread=thread; this.coldReader=true; this.reader=true;
      }
    } catch { /* Reading storage is optional. */ }
  }

  private readerAction(op: string, data: string): void {
    if (!this.active || !this.foreground) return;
    if (op==='drawer') { this.reader=false; this.showDrawer('',false); return; }
    if (op==='back') { this.reader=false; }
    if (this.ticket && this.phase==='page') this.controller.runJavaScript(
      'if(window.__focusMobile?.ticket==='+JSON.stringify(this.ticket)+
      '){dispatchEvent(new CustomEvent("focus-record-action",{detail:JSON.parse('+JSON.stringify(data)+')}))}').catch(()=>{});
  }

  private async recordPrompt(e: OnPromptEvent, op: string, epoch: number): Promise<void> {
    try {
      if (!this.foreground) { e.result.handleCancel(); return; }
      const data=JSON.parse(e.value) as Record<string,string>;
      if (op==='show') {
        this.readerThread=data['thread']; this.coldReader=false; this.reader=true;
      } else if (op==='ready' || op==='result') {
        data['event']=op; if(this.reader)this.readerControls.notify(JSON.stringify(data));
      } else if (op==='bookmark' && this.reader) {
        e.result.handlePromptConfirm('[]'); return;
      } else {
        if (!recordAllowed(false,op) || (data['thread'] && op!=='closed' && op!=='revert' &&
          data['thread']!==sitePrefs(this.ctx()).getSync('thread.'+this.site.id,''))) { e.result.handleCancel(); return; }
        const ticket=this.ticket;
        const result=await recordCall(this.ctx(),this.site.id,this.site.origin,op,data,()=>
          this.active && this.foreground && !this.gone && !this.leaving && epoch===this.epoch && this.ticket===ticket);
        e.result.handlePromptConfirm(result);
        if (op==='auth') this.recordScopeConfirmed=true;
        if (this.reader && (op==='closed' || op==='revert')) {
          data['event']=op; this.readerControls.notify(JSON.stringify(data));
        }
        if(this.reader && (op==='auth' || op==='lock' || op==='revoke')) this.readerControls.notify('{"event":"access"}');
        return;
      }
      e.result.handlePromptConfirm('ok');
    } catch { e.result.handleCancel(); }
  }

  private awaitWebSwitcher(): void {
    if (this.nativeSwitcher || this.switcherTimer !== -1) return;
    this.switcherTimer = setTimeout(() => this.setNativeSwitcher(true), 2500);
  }

  private setNativeSwitcher(visible: boolean): void {
    clearTimeout(this.switcherTimer); this.switcherTimer = -1;
    this.nativeSwitcher = visible;
  }

  private resetView(phase: string, address: string): void {
    this.pendingBack = 0;
    clearTimeout(this.retry);
    this.awaitWebSwitcher(); this.files.cancel(); this.ticket = ''; this.loginForm = false;
    this.handler?.cancel(); this.handler = undefined; this.password = '';
    this.phase = phase; this.source = address;
    this.controller = new webview.WebviewController();
    this.epoch++;
  }

  private start(manual: boolean = false): void {
    this.manual = manual; this.observedRealm = undefined; this.challengedRealm = undefined;
    this.attempted = false; this.supplied = undefined; this.previousBasicUser = undefined; this.needsNetwork = false; this.message = '';
    this.resetView('probe', this.probeUrl());
  }

  private async enterPage(epoch: number): Promise<void> {
    if (epoch !== this.epoch || this.gone || this.phase === 'page' || this.phase === 'blocked' || this.needsNetwork) return;
    if (this.supplied) {
      if (this.supplied.user !== this.previousBasicUser) await this.lockRecords('reauthorize');
      if (epoch !== this.epoch || this.gone) return;
      try {
        if (this.remember) await rememberLogin(this.site, this.supplied);
        else await forgetLogin(this.site);
      } catch { this.message = '安全存储不可用，本次凭据仅在内存中使用'; }
    }
    if (epoch !== this.epoch || this.gone) return;
    this.supplied = undefined; this.delay = 1000;
    const fragment = focusRoot(this.link, this.site.origin) ? new url.URL(this.link).hash : '';
    const thread = sitePrefs(this.ctx()).getSync('thread.' + this.site.id, '') as string;
    this.link = '';
    this.resetView('page', this.site.origin + '/?focusApp=1' + (thread ? '&thread=' + encodeURIComponent(thread) : '') + fragment);
  }

  private unavailable(message: string): void {
    this.setNativeSwitcher(true);
    this.needsNetwork = true; this.message = message;
    clearTimeout(this.retry);
    if (this.active && this.foreground) {
      this.retry = setTimeout(() => this.start(), this.delay);
      this.delay = Math.min(this.delay * 2, 30000);
    }
  }

  private signal(name: string): void {
    if (this.phase !== 'page' || !this.ticket) return;
    this.controller.runJavaScript("if(window.__focusMobile)dispatchEvent(new Event('focus-host-" + name + "'))").catch(() => {});
  }

  private foregroundChanged(): void {
    this.pendingBack = 0;
    clearTimeout(this.retry);
    if (!this.active) return;
    this.signal(this.foreground ? 'resume' : 'pause');
    if (this.foreground && this.needsNetwork && !this.gone) this.start();
  }

  private offer(address: string): void {
    if (!this.active || this.leaving || !focusRoot(address, this.site.origin)) return;
    if (!this.ticket) this.ticket = util.generateRandomUUID();
    const printFeature = canIUse('SystemCapability.Print.PrintFramework') ? ',"print"' : '';
    const script = 'if(window===top && location.origin===' + JSON.stringify(this.site.origin) +
      ' && location.pathname==="/" && window.__focusMobile?.ticket!==' + JSON.stringify(this.ticket) + ' && document.querySelector(\'meta[name=focus-mobile-contract][content="1"]\')){' +
      'const url=new URL(location.href);if(!url.searchParams.has("focusApp") && !url.searchParams.has("print") && !url.hash){' +
      'url.searchParams.set("focusApp","1");location.replace(url.href)}else{' +
      'window.__focusMobile=Object.assign(window.__focusMobile||{},{version:1,instance:' + JSON.stringify(this.site.id) + ',ticket:' + JSON.stringify(this.ticket) +
      ',name:' + JSON.stringify(this.site.name) + ',features:["wake","resume","save","thread","tabs","drawer","navigation","records-v1"' + printFeature + ']});dispatchEvent(new Event("focus-host-ready"))}}';
    this.controller.runJavaScript(script).catch(() => {});
  }

  private block(message: string): void {
    this.setNativeSwitcher(true);
    this.lockRecords();
    this.phase = 'blocked'; this.message = message; this.supplied = undefined;
    this.loginForm = false; this.password = '';
    this.handler?.cancel(); this.handler = undefined;
  }

  private async lockRecords(operation: string = 'lock'): Promise<void> {
    await recordCall(this.ctx(),this.site.id,this.site.origin,operation,{}).then(()=>{
      if(this.reader)this.readerControls.notify('{"event":"access"}');
    }).catch(()=>{});
  }

  private async challenge(event: OnHttpAuthRequestEvent, epoch: number): Promise<void> {
    if (!this.active || this.leaving || this.gone || this.epoch !== epoch || !this.site.origin.startsWith('https://') || event.host.toLowerCase() !== new url.URL(this.site.origin).hostname) {
      event.handler.cancel(); return;
    }
    if (this.phase === 'probe') {
      // Cancel this unauthenticated request to inspect its exact main-frame
      // 401 and WWW-Authenticate header in ArkWeb, on the device's own route.
      this.challengedRealm = event.realm;
      event.handler.cancel();
      return;
    }
    if (this.phase !== 'verified' || this.observedRealm !== event.realm || this.attempted || this.handler) {
      event.handler.cancel();
      if (this.phase === 'verified') this.block('入口未接受凭据，请更新后重试。');
      else if (this.phase === 'page') this.reauthenticate(epoch, false);
      return;
    }
    this.handler = event.handler;
    let existing: Login | undefined;
    try { existing = await savedLogin(this.site, event.realm); }
    catch { this.message = '无法读取安全凭据，请重新输入。'; }
    if (epoch !== this.epoch || this.gone || this.handler !== event.handler) return;
    this.previousBasicUser = existing?.user;
    if (existing && !this.manual) { this.remember = true; this.provide(existing); }
    else {
      this.setNativeSwitcher(true);
      this.lockRecords(); this.user = ''; this.password = ''; this.remember = false; this.loginForm = true;
    }
  }

  private provide(entry: Login): void {
    if (!this.handler) return;
    this.supplied = entry; this.attempted = true; this.loginForm = false; this.password = '';
    const handler = this.handler; this.handler = undefined;
    handler.confirm(entry.user, entry.password);
  }

  private reauthenticate(epoch: number, failedMainRequest: boolean): void {
    this.setNativeSwitcher(true);
    this.message = '入口要求重新验证。';
    if (!this.active || !this.foreground || Date.now() - this.lastReauth < 60000) return;
    const verify = (): void => {
      if (epoch !== this.epoch || this.gone) return;
      this.lastReauth = Date.now(); this.start();
    };
    if (failedMainRequest) { verify(); return; }
    this.controller.runJavaScript("window.__focusCanRebuild?.() === true && (dispatchEvent(new Event('focus-host-pause')),true)")
      .then(result => { if (result === 'true') verify(); }).catch(() => {});
  }

  private httpError(event: OnHttpErrorReceiveEvent, epoch: number): void {
    if (!this.active || this.leaving || this.gone || epoch !== this.epoch || !event.request.isMainFrame()) return;
    const code = event.response.getResponseCode();
    if (this.phase === 'page' && this.site.origin.startsWith('https://') && code === 401 && focusRoot(event.request.getRequestUrl(), this.site.origin)) {
      this.reauthenticate(epoch, true); return;
    }
    if (code >= 500) { this.unavailable('入口返回 HTTP ' + code); return; }
    if (this.phase !== 'page' && code === 403) { this.block('入口拒绝访问 (HTTP 403)。'); return; }
    if (this.phase === 'verified' && code === 401 && this.attempted) { this.block('入口未接受凭据，请更新后重试。'); return; }
    if (this.phase !== 'probe' || code !== 401 || event.request.getRequestUrl() !== this.probeUrl()) return;
    const challenges = event.response.getResponseHeader().filter((h: Header) => h.headerKey.toLowerCase() === 'www-authenticate');
    const realm = challenges.length === 1 ? basicRealm(challenges[0].headerValue) : undefined;
    if (realm === undefined || this.challengedRealm !== undefined && this.challengedRealm !== realm) {
      this.block('未收到匹配的标准 Basic 认证范围。'); return;
    }
    this.observedRealm = realm; this.challengedRealm = undefined;
    this.resetView('verified', this.probeUrl());
  }

  private intercept(req: WebResourceRequest, epoch: number): boolean {
    if (!this.active || this.leaving || epoch !== this.epoch || this.gone) return true;
    const address = req.getRequestUrl();
    if (this.phase !== 'page') {
      if (req.isMainFrame() && address !== this.probeUrl() && this.phase !== 'blocked') {
        if (this.phase === 'probe' && this.challengedRealm === undefined) void this.enterPage(epoch);
        else this.block('认证检查发生重定向。');
      }
      return !req.isMainFrame() || address !== this.probeUrl();
    }
    if (!req.isMainFrame()) return false;
    try {
      const origin = siteOrigin(address);
      if (origin === this.site.origin) return false;
      if (origin.startsWith('https://')) {
        if (this.site.sso) return false;
        if (req.isRequestGesture() && !req.isRedirect()) void this.openExternal(address);
        return true;
      }
    } catch {}
    if (req.isRequestGesture() && !req.isRedirect() && /^http:\/\//i.test(address)) {
      this.ctx().startAbility({ action: 'ohos.want.action.viewData', uri: address }).catch(() => {});
    }
    return true;
  }

  private openExternal(address: string): Promise<void> {
    this.pendingBack = 0;
    return router.pushUrl({ url: 'pages/ExternalPage', params: { address: address } })
      .catch(() => { this.message = '无法打开外部网页'; });
  }

  private filePrompt(event: OnPromptEvent, epoch: number): boolean {
    if (!event.message.startsWith('focus/1/')) return false;
    const prefix = 'focus/1/' + this.ticket + '/';
    if (!this.active || this.leaving || this.gone || epoch !== this.epoch || this.phase !== 'page' || !this.ticket || !event.message.startsWith(prefix)
      || !focusRoot(this.controller.getUrl(), this.site.origin) || !focusRoot(event.url, this.site.origin)) {
      event.result.handleCancel(); return true;
    }
    const op = event.message.slice(prefix.length);
    if (op.startsWith('records-')) { void this.recordPrompt(event,op.substring(8),epoch); return true; }
    if (op === 'external') {
      const origin = httpsOrigin(event.value);
      if (!this.foreground || !origin || origin === this.site.origin) { event.result.handleCancel(); return true; }
      event.result.handlePromptConfirm('ok'); void this.openExternal(event.value); return true;
    }
    if (op === 'instances') {
      event.result.handlePromptConfirm('ok');
      setTimeout(() => { if (epoch === this.epoch && this.active) this.showDrawer(event.value, false); }, 0);
      return true;
    }
    if (op === 'chrome') {
      if(event.value==='web' && !this.recordScopeConfirmed)this.lockRecords();
      this.setNativeSwitcher(event.value !== 'web');
      event.result.handlePromptConfirm('ok'); return true;
    }
    if (op === 'print') {
      const name = event.value;
      if (!name || name.length > 255) { event.result.handleCancel(); return true; }
      if (canIUse('SystemCapability.Print.PrintFramework')) {
        try {
          const adapter = this.controller.createWebPrintDocumentAdapter(name);
          print.print(name, adapter, {}, this.ctx()).then(() => event.result.handlePromptConfirm('ok'))
            .catch(() => event.result.handleCancel());
        } catch { event.result.handleCancel(); }
      } else event.result.handleCancel();
      return true;
    }
    if (op === 'thread') {
      if (event.value.length > 256) { event.result.handleCancel(); return true; }
      const prefs = sitePrefs(this.ctx());
      prefs.putSync('thread.' + this.site.id, event.value);
      prefs.flush().then(() => event.result.handlePromptConfirm('ok')).catch(() => event.result.handleCancel());
      return true;
    }
    this.files.handle(this.ctx(), op, event.value)
      .then(reply => { if (epoch === this.epoch && !this.gone) event.result.handlePromptConfirm(reply); else event.result.handleCancel(); })
      .catch(() => event.result.handleCancel());
    return true;
  }

  private leave(): void {
    if (!this.active || this.leaving) return;
    this.pendingBack = 0;
    this.reader=false; this.leaving = true;
    this.signal('pause');
    const epoch = this.epoch;
    let timer: number = -1;
    const done = (warm: boolean): void => {
      if (!this.leaving || this.gone) return;
      this.leaving = false; clearTimeout(timer);
      this.leavePage(warm && epoch === this.epoch);
    };
    if (this.phase !== 'page' || !this.ticket || !focusRoot(this.controller.getUrl(), this.site.origin)) { done(false); return; }
    timer = setTimeout(() => done(false), 800);
    this.controller.runJavaScript('window.__focusSetTabActive?.(false) === true')
      .then(reply => done(reply === 'true')).catch(() => done(false));
  }

  private selectionChanged(): void {
    if (!this.active) {
      clearTimeout(this.retry);
      this.controller.onInactive();
    } else {
      this.controller.onActive();
      if (this.ticket && this.phase === 'page') {
        const ticket = JSON.stringify(this.ticket);
        this.controller.runJavaScript('if(window.__focusMobile?.ticket===' + ticket + '){window.__focusMobile.name=' +
          JSON.stringify(this.site.name) + ';dispatchEvent(new Event("focus-host-ready"));window.__focusSetTabActive?.(true)}').catch(() => {});
      }
      this.foregroundChanged();
    }
  }

  private browserBack(): void {
    if (this.phase === 'page' && this.controller.accessBackward()) this.controller.backward();
    else this.showDrawer('', true);
  }

  private back(): void {
    if (!this.active || this.leaving || this.gone || this.pendingBack) return;
    if (this.reader) { this.readerControls.back(); return; }
    if (this.loginForm) { this.block('已取消认证。'); return; }
    if (this.phase !== 'page' || !this.ticket || !focusRoot(this.controller.getUrl(), this.site.origin)) {
      this.browserBack(); return;
    }
    const press = ++this.backRequest;
    this.pendingBack = press;
    const script = 'if(!window.__focusMobile){0}else if(window.__focusMobile.ticket===' + JSON.stringify(this.ticket) +
      '){typeof window.__focusBack==="function"?window.__focusBack():0}';
    this.controller.runJavaScript(script).then(result => {
      if (this.pendingBack !== press || this.gone) return;
      this.pendingBack = 0;
      if (result === 'false') this.showDrawer('', true);
      else if (result === '0') this.browserBack();
    }).catch(() => { if (this.pendingBack === press) this.pendingBack = 0; });
  }
  aboutToDisappear(): void {
    this.gone = true; this.epoch++; clearTimeout(this.retry); clearTimeout(this.switcherTimer);
    this.handler?.cancel(); this.files.cancel();
  }

  @Builder
  pageWeb(epoch: number) {
    Web({ src: this.source, controller: this.controller })
      .width('100%').layoutWeight(1).javaScriptAccess(this.phase === 'page')
      .domStorageAccess(this.phase === 'page').fileAccess(false).mixedMode(MixedMode.None)
      .onLoadIntercept(e => this.intercept(e.data, epoch))
      .onInterceptRequest(e => {
        if (this.phase !== 'page' && (!e.request.isMainFrame() || e.request.getRequestUrl() !== this.probeUrl())) {
          const denied = new WebResourceResponse();
          denied.setResponseData(''); denied.setResponseCode(403); denied.setReasonMessage('Forbidden');
          denied.setResponseMimeType('text/plain'); denied.setResponseEncoding('utf-8');
          return denied;
        }
        return null;
      })
      .onPageBegin(e => { if (epoch === this.epoch) {
        this.ticket = ''; this.recordScopeConfirmed=false; this.pendingBack = 0; this.files.cancel();
        const origin = httpsOrigin(e.url);
        if (this.phase==='page' && this.site.sso && origin && origin!==this.site.origin) void this.lockRecords('reauthorize');
        if (this.active) this.awaitWebSwitcher(); else this.leavePage(false);
      } })
      .onProgressChange(e => {
        if (epoch === this.epoch && this.phase === 'page' && e.newProgress >= 60) this.offer(this.controller.getUrl());
      })
      .onPageEnd(e => {
        if (epoch !== this.epoch || this.gone || this.needsNetwork) return;
        if (this.phase === 'page') this.offer(e.url);
        else if (e.url === this.probeUrl() && (this.phase === 'verified' && this.attempted
          || this.phase === 'probe' && this.challengedRealm === undefined)) void this.enterPage(epoch);
        else if (this.phase === 'probe' && this.challengedRealm !== undefined)
          this.message = '等待 ArkWeb 返回认证响应头；可重新检查入口。';
      })
      .onHttpAuthRequest(e => { void this.challenge(e, epoch); return true; })
      .onHttpErrorReceive(e => this.httpError(e, epoch))
      .onErrorReceive(e => {
        if (this.active && !this.leaving && epoch === this.epoch && e.request.isMainFrame() && this.phase !== 'blocked' && this.challengedRealm === undefined)
          this.unavailable('ArkWeb 连接失败 ' + e.error.getErrorCode());
      })
      .onRenderExited(() => {
        if (epoch !== this.epoch || this.gone) return;
        if (!this.active) { this.leavePage(false); return; }
        if (++this.rendererFailures <= 2) this.start(); else this.block('网页进程已退出，请重新连接。');
      })
      .onConsole(e => {
        if (epoch === this.epoch && this.phase === 'page' && e.message.getMessage() === 'focus-host-request/1')
          this.offer(this.controller.getUrl());
        return false;
      })
      .onPrompt(e => this.filePrompt(e, epoch))
      .onShowFileSelector(e => {
        if (this.active && epoch === this.epoch && this.phase === 'page' && focusRoot(this.controller.getUrl(), this.site.origin)) {
          void this.files.upload(this.ctx(), e);
        } else e.result.handleFileList([]);
        return true;
      })
  }

  build() {
    Stack() {
    Column() {
      if (this.nativeSwitcher) {
        Row() {
          Button('切换实例').buttonStyle(ButtonStyleMode.TEXTUAL).height(48).onClick(() => this.showDrawer('', false))
        }.width('100%').justifyContent(FlexAlign.Start)
      }
      if (this.message) { Text(this.message).width('100%').padding(6) }
      if (this.loginForm) {
        Column({ space: 6 }) {
          Text('HTTP Basic · ' + this.observedRealm + '\n' + this.site.origin)
          TextInput({ placeholder: '用户名', text: this.user }).onChange(v => this.user = v)
          TextInput({ placeholder: '密码', text: this.password }).type(InputType.Password).onChange(v => this.password = v)
          Row() { Checkbox().select(this.remember).onChange(v => this.remember = v); Text('安全保存凭据') }
          Row({ space: 8 }) {
            Button('取消').onClick(() => this.block('已取消认证。'))
            Button('登录').onClick(() => {
              const login = new Login();
              login.origin = this.site.origin; login.realm = this.observedRealm ?? '';
              login.user = this.user; login.password = this.password; this.provide(login);
            })
          }
        }.padding(12)
      }
      ForEach([this.epoch], (epoch: number) => { this.pageWeb(epoch) }, (epoch: number) => String(epoch))
    }.width('100%').height('100%')
    if(this.reader) {
      RecordsPanel({sites:[this.site],entry:this.site.id,thread:this.readerThread,cold:this.coldReader,
        controls:this.readerControls,action:(op: string,data: string)=>this.readerAction(op,data)})
    }
    }.width('100%').height('100%')
  }
}
