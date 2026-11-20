import { webview } from '@kit.ArkWeb';
import { router } from '@kit.ArkUI';

// Deliberately exercises ArkWeb itself, with the same app UID and VPN routing as the client.
@Entry
@Component
struct Probe {
  private controller: webview.WebviewController = new webview.WebviewController();
  @State private entry: string = (router.getParams() as Record<string, string>)['origin'] + '/focus-connect.txt';
  private answered: boolean = false;
  @State private status: string = '正在用 ArkWeb 连接入口…';

  build() {
    Column() {
      Row() {
        Button('返回').onClick(() => router.back())
        Text('ArkWeb 通路检查').fontWeight(FontWeight.Medium).margin({ left: 12 })
      }.width('100%').padding(8)
      Text(this.status).width('100%').padding(8)
      Web({ src: this.entry, controller: this.controller, incognitoMode: true })
        .layoutWeight(1).width('100%').javaScriptAccess(false).fileAccess(false)
        .onLoadIntercept(event => !event.data.isMainFrame() || event.data.getRequestUrl() !== this.entry)
        .onHttpAuthRequest(event => {
          this.answered = true;
          this.status = '已从入口收到 HTTP 认证挑战。此探针不提交凭据。';
          event.handler.cancel();
          return true;
        })
        .onHttpErrorReceive(event => {
          if (event.request.isMainFrame()) {
            this.answered = true;
            this.status = '入口应答 HTTP ' + event.response.getResponseCode();
          }
        })
        .onErrorReceive(event => {
          if (event.request.isMainFrame() && !this.answered) this.status = 'ArkWeb 连接失败 ' + event.error.getErrorCode();
        })
        .onPageEnd(() => {
          if (this.status.startsWith('正在')) this.status = '请核对下方是否显示入口返回的 Focus 字样。';
        })
    }.width('100%').height('100%')
  }
}
