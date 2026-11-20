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
    this.sites = JSON.parse(prefs.getSync('sites', '[]') as string) as Site[];
    const previous = this.sites.find((item: Site) => item.id === prefs.getSync('active', ''));
    if (previous) this.open(previous);
  }

  private open(site: Site, link: string = '', reload: boolean = false): void {
    const cached = this.tabs.find((tab: InstanceTab) => tab.site.id === site.id);
    const tab = cached && !link && !reload ? cached : new InstanceTab(site, link);
    const others = this.tabs.filter((item: InstanceTab) => item.site.id !== site.id);
    this.tabs = [...others.slice(-1), tab];
    this.activeId = site.id;
    this.managing = '';
    const prefs = sitePrefs(this.ctx());
    prefs.putSync('active', site.id); void prefs.flush();
  }

  private leave(tab: InstanceTab, retained: boolean): void {
    if (!this.tabs.some((item: InstanceTab) => item.key === tab.key)) return;
    if (!retained) this.tabs = this.tabs.filter((item: InstanceTab) => item.key !== tab.key);
    if (this.activeId !== tab.site.id) return;
    this.activeId = '';
    const prefs = sitePrefs(this.ctx());
    prefs.deleteSync('active'); void prefs.flush();
  }

  private releaseInactive(): void {
    this.tabs = this.tabs.filter((tab: InstanceTab) => tab.site.id === this.activeId);
  }

  onBackPress(): boolean {
    const tab = this.tabs.find((item: InstanceTab) => item.site.id === this.activeId);
    if (tab) { tab.back(); return true; }
    if (this.editing) { this.editing = false; return true; }
    return false;
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
      if (old && (old.origin !== origin || old.name !== site.name || old.sso !== site.sso))
        this.tabs = this.tabs.filter((tab: InstanceTab) => tab.site.id !== old.id);
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

  build() {
    Stack() {
      ForEach(this.tabs, (tab: InstanceTab) => {
        Column() {
          InstancePane({ tab: tab, active: this.activeId === tab.site.id,
            leavePage: (retained: boolean) => this.leave(tab, retained) })
        }.width('100%').height('100%')
          .visibility(this.activeId === tab.site.id ? Visibility.Visible : Visibility.Hidden)
      }, (tab: InstanceTab) => tab.key)
      if (!this.activeId) { this.manager() }
    }.width('100%').height('100%')
  }
}
