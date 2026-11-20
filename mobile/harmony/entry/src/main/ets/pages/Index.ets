import { router } from '@kit.ArkUI';
import { common } from '@kit.AbilityKit';
import { util, url } from '@kit.ArkTS';
import { InstanceTab, InstancePane } from '../InstancePane';
import { Site, sitePrefs, siteOrigin, focusRoot, forgetSite } from '../Sites';

@Entry
@Component
struct Index {
  @State private tabs: InstanceTab[] = [];
  @State private activeId: string = '';
  @State private managing: string = '';
  @State private drawerOpen: boolean = false;
  @State private drawerDark: boolean = false;
  private nextId: string = '';
  @State private returnId: string = '';
  @State private pageLimit: number = 2;
  @StorageLink('focusMemoryWarning') @Watch('releaseInactive') private memoryWarning: number = 0;
  @State private sites: Site[] = [];
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

  private open(site: Site, link: string = '', reload: boolean = false): void {
    const cached = this.tabs.find((tab: InstanceTab) => tab.site.id === site.id);
    const tab = cached && !link && !reload ? cached : new InstanceTab(site, link);
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

  onBackPress(): boolean {
    if (this.drawerOpen) { this.drawerOpen = false; return true; }
    const tab = this.tabs.find((item: InstanceTab) => item.site.id === this.activeId);
    if (tab) { tab.back(); return true; }
    if (this.editing) { this.editing = false; return true; }
    if (this.authSite) { this.authSite = ''; this.authLink = ''; return true; }
    if (this.managing) { this.managing = ''; return true; }
    return this.returnToPage();
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
        Text(this.editing ? '实例入口' : 'Focus 实例').fontSize(26).fontWeight(FontWeight.Bold)
        if (this.editing) {
          TextInput({ placeholder: '名称', text: this.label }).onChange(v => this.label = v)
          TextInput({ placeholder: 'https://focus.example', text: this.address }).onChange(v => this.address = v)
          Row() {
            Checkbox().select(this.sso).onChange(v => this.sso = v)
            Text('网页登录 / SSO（允许 HTTPS 登录跳转）')
          }
          Row({ space: 8 }) {
            Button('取消').onClick(() => this.editing = false)
            Button('保存').onClick(() => this.save())
          }
        } else {
          if (this.sites.some((item: Site) => item.id === this.returnId)) {
            Button('返回对话').onClick(() => this.returnToPage())
          }
          Row({ space: 12 }) {
            Text('保留实例页面数')
            Select([{ value: '1' }, { value: '2' }, { value: '3' }, { value: '4' }, { value: '5' }])
              .selected(this.pageLimit - 1).value(this.pageLimit.toString()).onSelect((index: number) => this.setPageLimit(index + 1))
          }
          Button('添加实例').onClick(() => this.edit(new Site()))
          ForEach(this.sites, (site: Site) => {
            Column({ space: 6 }) {
              Row({ space: 6 }) {
                Button(site.name).layoutWeight(1).onClick(() => this.open(site))
                Button('⋮').accessibilityText('管理 ' + site.name).onClick(() => {
                  this.managing = this.managing === site.id ? '' : site.id;
                })
              }
              Text(site.origin).fontSize(14)
              if (this.managing === site.id) {
                Button('重新连接').onClick(() => this.open(site, '', true))
                Row({ space: 8 }) {
                  Button('编辑').fontSize(13).onClick(() => this.edit(site))
                  Button('删除').fontSize(13).onClick(() => this.remove(site))
                  Button('通路检查').fontSize(13).onClick(() => router.pushUrl({ url: 'pages/Probe', params: site }))
                  Button('授权链接').fontSize(13).onClick(() => { this.authSite = site.id; this.authLink = ''; })
                }
              }
              if (this.authSite === site.id) {
                TextInput({ placeholder: '同一入口的 Focus 授权链接' }).onChange(v => this.authLink = v)
                Button('打开一次').onClick(() => {
                  if (focusRoot(this.authLink, site.origin) && new url.URL(this.authLink).hash.startsWith('#token=')) {
                    this.open(site, this.authLink); this.authLink = ''; this.authSite = '';
                  } else this.message = '需要同一入口的授权链接';
                })
              }
            }.width('100%').padding({ top: 10, bottom: 12 })
          }, (site: Site) => site.id)
        }
        if (this.message) { Text(this.message).fontColor('#a83b26') }
      }.width('100%').padding(16)
    }.width('100%').height('100%')
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
          AlertDialog.show({ title: 'Focus Mobile 1.3.0', message: 'HarmonyOS · ArkWeb' });
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
            showDrawer: (theme: string) => { this.drawerDark = theme === 'dark'; this.drawerOpen = true; },
            leavePage: (retained: boolean) => this.leave(tab, retained) })
        }.width('100%').height('100%')
          .visibility(this.activeId === tab.site.id ? Visibility.Visible : Visibility.Hidden)
      }, (tab: InstanceTab) => tab.key)
      if (!this.activeId) { this.manager() }
      if (this.activeId && this.drawerOpen) { this.drawer() }
    }.width('100%').height('100%')
  }
}
