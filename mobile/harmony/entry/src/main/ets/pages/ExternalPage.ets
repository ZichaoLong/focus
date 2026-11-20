import { webview } from '@kit.ArkWeb';
import { router } from '@kit.ArkUI';
import { common } from '@kit.AbilityKit';
import { httpsOrigin } from '../Sites';

@Entry
@Component
struct ExternalPage {
  private controller: webview.WebviewController = new webview.WebviewController();
  private initial: string = (router.getParams() as Record<string, string>)['address'];
  @State private address: string = this.initial;
  @State private message: string = '';

  onBackPress(): boolean { router.back(); return true; }

  build() {
    Column() {
      Row({ space: 8 }) {
        Button('‹').type(ButtonType.Normal).borderRadius(8).accessibilityText('回到 Focus').onClick(() => router.back())
        Text(httpsOrigin(this.address)).layoutWeight(1).maxLines(2).textOverflow({ overflow: TextOverflow.Ellipsis })
          .onClick(() => { AlertDialog.show({ message: httpsOrigin(this.address) }); })
        Button('用浏览器打开').fontSize(14).onClick(() => {
          const current = this.controller.getUrl();
          if (httpsOrigin(this.address)) (getContext(this) as common.UIAbilityContext)
            .startAbility({ action: 'ohos.want.action.viewData', uri: httpsOrigin(current) ? current : this.address })
            .catch(() => { this.message = '未找到浏览器'; });
        })
      }.width('100%').padding(8)
      if (this.message) { Text(this.message) }
      if (httpsOrigin(this.initial)) {
        Web({ src: this.initial, controller: this.controller, incognitoMode: true })
          .layoutWeight(1).width('100%').javaScriptAccess(true).domStorageAccess(true)
          .fileAccess(false).mixedMode(MixedMode.None)
          .onLoadIntercept(e => e.data.isMainFrame() && !httpsOrigin(e.data.getRequestUrl()))
          .onPageBegin(e => { if (httpsOrigin(e.url)) this.address = e.url; })
          .onPageEnd(e => { if (httpsOrigin(e.url)) this.address = e.url; })
          .onHttpAuthRequest(e => { e.handler.cancel(); return true; })
      }
    }.width('100%').height('100%')
  }
}
