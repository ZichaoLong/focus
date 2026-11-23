import { router } from '@kit.ArkUI';
import { common, ConfigurationConstant } from '@kit.AbilityKit';
import { systemDateTime } from '@kit.BasicServicesKit';
import { util, url } from '@kit.ArkTS';
import { InstanceTab, InstancePane } from '../InstancePane';
import { RecordsPanel, ReaderControls } from '../RecordsPanel';
import { ServerUpdates } from '../ServerUpdates';
import { Site, sitePrefs, siteOrigin, focusRoot, forgetSite } from '../Sites';

@Entry
@Component
struct Index {
  @State private tabs: InstanceTab[] = [];
  @State private activeId: string = '';
  @State private managing: string = '';
  @State private drawerOpen: boolean = false;
  @State private drawerDark: boolean = false;
  private drawerExitDeadline: number = 0;
  @StorageLink('focusForeground') @Watch('disarmDrawerExit') private foreground: boolean = true;
  private nextId: string = '';
  @State private returnId: string = '';
  @State private pageLimit: number = 2;
  @StorageLink('focusMemoryWarning') @Watch('releaseInactive') private memoryWarning: number = 0;
  @State private sites: Site[] = [];
  @State private records: boolean = false;
  private readerControls: ReaderControls = new ReaderControls();
  @State private updating: boolean = false;
  @State private editing: boolean = false;
  @State private editingId: string = '';
  @State private label: string = '';
  @State private address: string = '';
  @State private sso: boolean = false;
  @State private message: string = '';
  @State private authSite: string = '';
  @State private authLink: string = '';
  private ctx(): common.UIAbilityContext { return getContext(this) as common.UIAbilityContext; }

  aboutToAppear(): void {
    const prefs = sitePrefs(this.ctx());
    this.pageLimit = Math.max(1, Math.min(5, prefs.getSync('page-limit', 2) as number));
    this.sites = JSON.parse(prefs.getSync('sites', '[]') as string) as Site[];
    const previous = this.sites.find((item: Site) => item.id === prefs.getSync('active', ''));
    if (previous) this.open(previous);
  }

  private open(site: Site, link: string = '', reload: boolean = false, readerThread: string = ''): void {
    const cached = this.tabs.find((tab: InstanceTab) => tab.site.id === site.id);
    const tab = cached && !link && !reload ? cached : new InstanceTab(site, link);
    if(readerThread) { tab.readerThread=readerThread; if(tab===cached)tab.read(readerThread); }
    const others = this.tabs.filter((item: InstanceTab) => item.site.id !== site.id);
    this.tabs = [...others, tab].slice(-this.pageLimit);
    this.returnId = '';
    this.activeId = site.id;
    this.managing = '';
    const prefs = sitePrefs(this.ctx());
    prefs.putSync('active', site.id); void prefs.flush();
  }

  private leave(tab: InstanceTab, retained: boolean): void {
    if (!this.tabs.some((item: InstanceTab) => item.key === tab.key)) return;
    if (!retained) this.tabs = this.tabs.filter((item: InstanceTab) => item.key !== tab.key);
    if (this.activeId !== tab.site.id) return;
    this.returnId = tab.site.id;
    this.activeId = '';
    const prefs = sitePrefs(this.ctx());
    prefs.deleteSync('active'); void prefs.flush();
    const target = this.sites.find((site: Site) => site.id === this.nextId);
    this.nextId = '';
    if (target) this.open(target);
  }

  private releaseInactive(): void {
    this.tabs = this.tabs.filter((tab: InstanceTab) => tab.site.id === this.activeId);
  }

  private selectEntry(id: string): void {
    this.drawerOpen = false;
    if (id === this.activeId) return;
    this.nextId = id;
    this.tabs.find((tab: InstanceTab) => tab.site.id === this.activeId)?.park();
  }

  private disarmDrawerExit(): void { this.drawerExitDeadline = 0; }

  private showDrawer(theme: string, fromRootBack: boolean): void {
    if (!this.foreground || !this.activeId) return;
    this.drawerDark = theme === 'dark' || (!theme && this.ctx().config.colorMode === ConfigurationConstant.ColorMode.COLOR_MODE_DARK);
    this.drawerOpen = true;
    this.drawerExitDeadline = fromRootBack ? systemDateTime.getUptime(systemDateTime.TimeType.STARTUP) + 2000 : 0;
  }

  private leaveToSystem(): void {
    this.ctx().moveAbilityToBackground().catch(() => { this.message = '系统未能将 Focus 移到后台'; });
  }

  onBackPress(): boolean {
    if (this.records) { this.readerControls.back(); return true; }
    if (this.updating) { this.updating = false; return true; }
    if (this.drawerOpen) {
      this.drawerOpen = false;
      if (this.drawerExitDeadline > systemDateTime.getUptime(systemDateTime.TimeType.STARTUP)) this.leaveToSystem();
      this.disarmDrawerExit();
      return true;
    }
    const tab = this.tabs.find((item: InstanceTab) => item.site.id === this.activeId);
    if (tab) { tab.back(); return true; }
    if (this.editing) { this.editing = false; return true; }
    if (this.authSite) { this.authSite = ''; this.authLink = ''; return true; }
    if (this.managing) { this.managing = ''; return true; }
    if (!this.returnToPage()) this.leaveToSystem();
    return true;
  }

  private returnToPage(): boolean {
    const site = this.sites.find((item: Site) => item.id === this.returnId);
    if (!site) return false;
    this.open(site);
    return true;
  }

  private setPageLimit(value: number): void {
    this.pageLimit = value;
    this.tabs = this.tabs.slice(-value);
    const prefs = sitePrefs(this.ctx());
    prefs.putSync('page-limit', value); void prefs.flush();
  }

  private edit(site: Site): void {
    this.editing = true; this.editingId = site.id;
    this.label = site.name; this.address = site.origin; this.sso = site.sso; this.message = '';
  }

  private async save(): Promise<void> {
    try {
      const origin = siteOrigin(this.address.trim());
      const parsed = new url.URL(this.address.trim());
      if (!this.label.trim() || parsed.pathname !== '/' || parsed.search || parsed.hash) throw new Error('请输入名称和站点根地址');
      // ArkWeb API 12 has a shared cookie jar. Cookies have no port attribute.
      if (this.sites.some((s: Site) => s.id !== this.editingId && new url.URL(s.origin).hostname === parsed.hostname))
        throw new Error('此主机已有实例。独立实例需使用不同主机名，以隔离 Cookie。');
      const old = this.sites.find((s: Site) => s.id === this.editingId);
      const site = new Site();
      site.origin = origin; site.name = this.label.trim(); site.sso = this.sso;
      site.id = old?.origin === origin ? old.id : util.generateRandomUUID();
      if (old && (old.origin !== origin || old.sso !== site.sso))
        this.tabs = this.tabs.filter((tab: InstanceTab) => tab.site.id !== old.id);
      const retained = this.tabs.find((tab: InstanceTab) => tab.site.id === site.id);
      if (retained) retained.site.name = site.name;
      if (old && old.origin !== origin) await forgetSite(this.ctx(), old);
      const next = this.sites.filter((s: Site) => s.id !== this.editingId);
      next.push(site);
      await this.persist(next); this.editing = false;
    } catch (err) { this.message = (err as Error).message; }
  }

  private async persist(sites: Site[]): Promise<void> {
    const prefs = sitePrefs(this.ctx());
    prefs.putSync('sites', JSON.stringify(sites));
    await prefs.flush();
    this.sites = sites;
  }

  private remove(site: Site): void {
    AlertDialog.show({ message: '删除实例及此 App 保存的凭据和页面数据？',
      primaryButton: { value: '取消', action: () => {} },
      secondaryButton: { value: '删除', action: async () => {
        try {
          this.tabs = this.tabs.filter((tab: InstanceTab) => tab.site.id !== site.id);
          await forgetSite(this.ctx(), site);
          await this.persist(this.sites.filter((item: Site) => item.id !== site.id));
        } catch (err) { this.message = (err as Error).message; }
      } } });
  }

  @Builder
  manager() {
    Scroll() {
      Column({ space: 12 }) {
        if (!this.editing && this.sites.some((item: Site) => item.id === this.returnId)) {
          Button('返回对话').buttonStyle(ButtonStyleMode.TEXTUAL).onClick(() => this.returnToPage())
        }
        Row({ space: 8 }) {
          Text(this.editing ? (this.editingId ? '编辑实例' : '添加实例') : '管理实例')
            .fontSize(26).fontWeight(FontWeight.Bold).layoutWeight(1)
          if (!this.editing) { Button('添加实例').onClick(() => this.edit(new Site())) }
        }.width('100%').margin({ bottom: 8 })
        if (this.editing) {
          Column({ space: 10 }) {
            Text('实例名称').fontWeight(FontWeight.Medium)
            TextInput({ placeholder: '名称', text: this.label }).onChange(v => this.label = v)
            Text('访问地址').fontWeight(FontWeight.Medium)
            TextInput({ placeholder: 'https://focus.example', text: this.address }).onChange(v => this.address = v)
            Row({ space: 8 }) {
              Checkbox().select(this.sso).accessibilityText('允许跨站登录').onChange(v => this.sso = v)
              Text('允许跨站登录（SSO）').onClick(() => { this.sso = !this.sso; })
            }
            Text('仅在入口需要跳到其他网站登录时开启。HTTP Basic 会在连接时询问。')
              .fontSize(14).fontColor($r('sys.color.ohos_id_color_text_secondary'))
          }.alignItems(HorizontalAlign.Start).width('100%').padding(16).borderRadius(16)
            .backgroundColor($r('sys.color.ohos_id_color_list_card_bg'))
          Row({ space: 12 }) {
            Button('取消').buttonStyle(ButtonStyleMode.TEXTUAL).onClick(() => this.editing = false)
            Button('保存').onClick(() => this.save())
          }.width('100%').justifyContent(FlexAlign.End)
        } else {
          if (this.sites.length) { Button('本机离线记录').onClick(()=>this.records=true)
            Button('服务端更新').buttonStyle(ButtonStyleMode.TEXTUAL).onClick(() => this.updating = true) }
          if (!this.sites.length) { Text('添加 Focus 的访问地址以开始使用。').fontSize(15) }
          ForEach(this.sites, (site: Site) => {
            Column({ space: 8 }) {
              Row() {
                Column({ space: 4 }) {
                  if (site.id === this.returnId) { Text('当前实例').fontSize(12).fontColor($r('sys.color.ohos_id_color_emphasize')) }
                  Text(site.name).fontSize(18).fontWeight(FontWeight.Medium)
                  Text(site.origin).fontSize(14).fontColor($r('sys.color.ohos_id_color_text_secondary'))
                }.alignItems(HorizontalAlign.Start).layoutWeight(1).onClick(() => this.open(site))
                Button('⋮').buttonStyle(ButtonStyleMode.TEXTUAL).accessibilityText('管理 ' + site.name).onClick(() => {
                  this.managing = this.managing === site.id ? '' : site.id;
                  this.authSite = ''; this.authLink = ''; this.message = '';
                })
              }.width('100%')
              if (this.managing === site.id) {
                Divider()
                Flex({ wrap: FlexWrap.Wrap }) {
                  Button('重新连接').buttonStyle(ButtonStyleMode.TEXTUAL).onClick(() => this.open(site, '', true))
                  Button('编辑').buttonStyle(ButtonStyleMode.TEXTUAL).onClick(() => this.edit(site))
                  Button('通路检查').buttonStyle(ButtonStyleMode.TEXTUAL).onClick(() => router.pushUrl({ url: 'pages/Probe', params: site }))
                  Button('使用 Focus 授权链接').buttonStyle(ButtonStyleMode.TEXTUAL).onClick(() => { this.authSite = site.id; this.authLink = ''; })
                  Button('删除').buttonStyle(ButtonStyleMode.TEXTUAL).onClick(() => this.remove(site))
                }
              }
              if (this.authSite === site.id) {
                Text('仅在 Focus 提示需要授权时，粘贴这个实例签发的链接。').fontSize(14)
                TextInput({ placeholder: '同一入口的 Focus 授权链接', text: this.authLink }).onChange(v => this.authLink = v)
                Button('打开一次').onClick(() => {
                  if (focusRoot(this.authLink, site.origin) && new url.URL(this.authLink).hash.startsWith('#token=')) {
                    this.open(site, this.authLink); this.authLink = ''; this.authSite = '';
                  } else this.message = '需要同一入口的授权链接';
                })
              }
            }.width('100%').padding(16).borderRadius(16).alignItems(HorizontalAlign.Start)
              .backgroundColor($r('sys.color.ohos_id_color_list_card_bg'))
          }, (site: Site) => site.id)
          Row({ space: 12 }) {
            Text('保留实例页面数').layoutWeight(1)
            Select([{ value: '1' }, { value: '2' }, { value: '3' }, { value: '4' }, { value: '5' }])
              .selected(this.pageLimit - 1).value(this.pageLimit.toString()).onSelect((index: number) => this.setPageLimit(index + 1))
          }.width('100%').padding(14).margin({ top: 8 }).borderRadius(14).backgroundColor($r('sys.color.ohos_id_color_list_card_bg'))
        }
        if (this.message) { Text(this.message).fontColor('#a83b26') }
      }.width('100%').padding(20).alignItems(HorizontalAlign.Start)
    }.width('100%').height('100%').backgroundColor($r('sys.color.ohos_id_color_background'))
  }

  @Builder
  drawer() {
    Row() {
      Column({ space: 8 }) {
        Text('实例').fontSize(22).fontWeight(FontWeight.Bold)
          .fontColor(this.drawerDark ? '#f1f1ed' : '#242523').width('100%').padding(12)
        Scroll() {
          Column({ space: 4 }) {
            ForEach(this.sites, (site: Site) => {
              Row() {
                Column({ space: 2 }) {
                  Text(site.name).fontSize(16)
                  Text(site.origin).fontSize(12).fontColor(this.drawerDark ? '#b1b1aa' : '#61645d')
                    .maxLines(1).textOverflow({ overflow: TextOverflow.Ellipsis })
                }.layoutWeight(1).alignItems(HorizontalAlign.Start)
                if (site.id === this.activeId) { Text('✓') }
              }.width('100%').padding(14).borderRadius(10)
                .backgroundColor(site.id === this.activeId ? (this.drawerDark ? '#343b37' : '#e6ece7') : Color.Transparent)
                .onClick(() => this.selectEntry(site.id))
            }, (site: Site) => site.id)
          }.width('100%')
        }.layoutWeight(1)
        Divider()
        Text('管理实例').width('100%').padding(12).onClick(() => this.selectEntry(''))
        Text('关于 Focus Mobile').width('100%').padding(12).onClick(() => {
          this.drawerOpen = false;
          AlertDialog.show({ title: 'Focus Mobile 1.7.0', message: 'HarmonyOS · ArkWeb' });
        })
      }.width('82%').constraintSize({ maxWidth: 328 }).height('100%').padding(14)
        .foregroundColor(this.drawerDark ? '#f1f1ed' : '#242523')
        .backgroundColor(this.drawerDark ? '#1d1f1d' : '#fcfcfa')
      Blank().height('100%').layoutWeight(1).onClick(() => this.drawerOpen = false)
    }.width('100%').height('100%').backgroundColor('#66000000')
  }

  build() {
    Stack() {
      ForEach(this.tabs, (tab: InstanceTab) => {
        Column() {
          InstancePane({ tab: tab, active: this.activeId === tab.site.id,
            showDrawer: (theme: string, fromRootBack: boolean) => this.showDrawer(theme, fromRootBack),
            leavePage: (retained: boolean) => this.leave(tab, retained) })
        }.width('100%').height('100%')
          .visibility(this.activeId === tab.site.id ? Visibility.Visible : Visibility.Hidden)
      }, (tab: InstanceTab) => tab.key)
      if (!this.activeId && this.records) {
        RecordsPanel({sites:this.sites,controls:this.readerControls,activeEntry:this.returnId,action:(op: string,value: string)=>{
          if(op==='back')this.records=false;
          if(op==='visit'){
            const data=JSON.parse(value) as Record<string,string>;
            const site=this.sites.find((s: Site)=>s.id===data['entry']);
            if(site){this.records=false;this.open(site,'',false,data['thread']);}
          }
        }})
      } else if (!this.activeId && this.updating) {
        ServerUpdates({sites:this.sites, close:() => this.updating = false,
          open:(site: Site) => { this.updating = false; this.open(site); }})
      } else if (!this.activeId) { this.manager() }
      if (this.activeId && this.drawerOpen) { this.drawer() }
    }.width('100%').height('100%')
  }
}
