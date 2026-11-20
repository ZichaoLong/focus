# Focus 手机客户端

Android 使用系统 WebView，HarmonyOS 使用 ArkUI Stage 工程和 ArkWeb。两端都从所选实例加载 Focus Web。对话、管理、设置、Focus 服务升级、审批和附件使用实例当前提供的实现。安装包与实例可独立升级。恢复和系统保存文件需要实例部署包含移动容器协议的 Web 版本。[移动容器合同](../docs/contracts/focus-mobile.zh-CN.md)

## 配置入口

1. 先连上通常用来访问实例的网络。在使用 Tailscale 的手机上手动打开它。
2. 打开 Focus，选「添加实例」，输入显示名和 HTTPS 站点根地址，例如 `https://focus.example.net`。可使用自定义端口。本地模式支持手机回环的 HTTP 地址（仅限 `127.0.0.1`、`localhost`、`[::1]`）。远端域名或 IP 必须与手机信任的 TLS 证书匹配。
3. 打开该实例。窄屏点击会话标题，在会话切换面板选「切换实例」；宽屏可从侧栏进入。阅读模式也可点会话标题。加载期间及旧版 Web 可点原生的实例名称。实例列表中每一行的「⋮」提供重新连接、编辑、授权链接和删除。系统返回键优先回退网页导航。更换地址会创建新的本地身份。
4. 为其他实例重复上述步骤。为独立入口使用不同的主机名，尤其是代理使用 Cookie 登录时。ArkWeb API 12 的 Cookie 存储以主机划分，此版鸿蒙端会拒绝同主机的第二个条目。Android 对支持多配置的系统 WebView 使用独立的命名配置，同一主机的不同端口也可隔离。旧引擎一次打开一个实例，继续使用各自的数据目录。

| 入口已有的认证 | 手机上的操作 |
| --- | --- |
| Focus 自身授权 | 使用「授权链接」一次性打开实例签发的、同一站点根地址的 `#token=…` 链接。本地模式须先有可用的本机回环入口，地址和端口须与链接一致。有可信代理的远端入口使用现有代理授权。Focus 的注册或会话过期时按页面提示重新授权。 |
| 可信代理或私网 ACL 放行 | 直接打开。代理继续在服务器端完成 Focus 的可信入口准入。 |
| 标准 HTTP Basic | 第一次收到匹配的挑战时，核对对话框中的站点与 realm，输入用户名密码。勾选「安全保存凭据」可在下次启动时复用。Android 使用 Keystore 加密，鸿蒙使用 Asset Store。拒绝后选择更新凭据或重新连接。 |
| 网页登录或 SSO | 在该条目的编辑界面勾选「网页登录 / SSO」，在网页内完成 HTTPS 登录和回跳。身份提供方须允许嵌入式浏览器。可用性还取决于 IdP 的 Cookie、二次认证和回跳策略。 |

Basic 凭据只在 HTTPS 上响应。Basic 处理适用于首页、静态资源、API 和 WebSocket 共用同一个 HTTP 保护空间的入口。客户端在配置的站点上验证标准挑战，再由引擎为同保护空间的请求完成认证。成功前不会持久保存新输入的密码。网络故障保留已保存的凭据。删除实例清除该条目的安全凭据和 Focus 页面数据。网页登录的共享 IdP 仍可以保有自己的会话。

只填写最终访问地址。HTTPS 代理直接连接 Focus、通过 SSH 访问远端 Focus，以及 Tailscale 的直连和 DERP 情况都由原部署处理。Focus 的 proxy proof 由服务器端代理提供。[Focus 外部访问合同](../docs/decisions/focus-web-external-access.zh-CN.md)

## 恢复与文件

进入前台会触发现有 WebSocket 健康检查。断线时退避重连，握手后重新读取服务端状态。若原页面注册已清理，满足安全条件的可见页面会限频重新注册。被其他标签替换的身份须显式刷新。有待核验操作时，先按 Focus 提示查看结果。服务端任务继续按原生命周期运行。App 最多在内存保留最近两个实例的页面。打开实例列表即暂停原实例的 WebSocket、状态轮询和重试；切回后重新握手并核对服务端状态。打开第三个实例、系统回收内存、页面未确认暂停或手动「重新连接」时，回到实例会重建页面。

每个实例可恢复上次已确认的线程、阅读或普通模式、文字草稿和可验证的历史消息位置。升级各实例提供的 Focus Web 后才会提供新的切换入口和模式恢复。离线期间可以看到仍在内存里的页面，冷启动需要实例页面可访问。历史内容已删除、服务器拒绝打开线程或用户另选了位置时，按服务器当前结果显示。结果未知的 prompt 使用既有定位记录查询，审批、回答、中断和其他业务操作由原有处理流程核验。选中的附件和提交权限仍属于原 writer。Tailscale、SSH 或代理恢复连通后，页面才有条件接续。

附件由系统文件选择器交给现有上传入口。下载使用 Web 中「另存为」，选择系统目标后，Web 用当前会话读取内容，原生分块暂存并写入目标。可在预览里查看文本、图片、PDF 等已有格式。HTML 预览保留现有沙箱。Web 不向外部网页提供原生文件桥接。

问答导出可选择 Markdown、线程数据或「打印／另存为 PDF」。在完整问答预览准备好后点击打印，按系统打印服务提供的选项选择目标。点击「返回对话」回到原线程。

## Android 构建、签名与安装

需要 Python 3、带 `javac` 和 `keytool` 的 JDK（建议 17 或更新）、Android SDK Platform 35、Build Tools 35.0.0 和 Platform Tools。使用 Android Studio 的 SDK Manager 或已配置的命令行工具安装上述组件。

```sh
sdkmanager "platform-tools" "platforms;android-35" "build-tools;35.0.0"
python mobile/android/build.py --sdk "$ANDROID_HOME"
adb install -r mobile/android/build/focus-debug.apk
```

首次构建下载 Google Maven 的 AndroidX WebKit 1.12.1 并校验 SHA-256。离线构建可传 `--webkit-aar /path/to/webkit-1.12.1.aar`。

输出 `mobile/android/build/focus-debug.apk`，支持 Android 9（API 28）及以上。也可把该 APK 下载到手机，通过系统安装器打开并按系统提示允许此下载来源。首次构建在本用户的 `.android/debug.keystore` 生成调试密钥。更新同一应用须使用相同签名。独立发布时使用自己的密钥签署已对齐的 APK，口令由工具交互读取。

```sh
python mobile/android/build.py --sdk "$ANDROID_HOME" --unsigned
"$ANDROID_HOME/build-tools/35.0.0/apksigner" sign --ks /path/to/release.jks --out focus-release.apk mobile/android/build/focus-unsigned.apk
"$ANDROID_HOME/build-tools/35.0.0/apksigner" verify --verbose focus-release.apk
```

使用相同包名和签名覆盖安装可保留现有实例和 Keystore 凭据。首次升级到多配置时，App 用本地空页面按原站点迁移 Focus 的草稿、恢复记录和根地址 Cookie，临时副本加密并在导入成功后删除。迁移遇到当前引擎不接受的数据时，会继续使用原有目录。已启用网页登录的旧条目沿用原配置，以保留 IdP 会话，切换时冷恢复。若已有命名配置后系统 WebView 被降级到不支持该能力的版本，恢复兼容的系统 WebView 即可重新使用原数据。

## HarmonyOS 构建、签名与安装

1. 在支持的 Windows 或 macOS 开发机安装 DevEco Studio 和 HarmonyOS SDK，打开 `mobile/harmony` 所在的工程根目录。工程使用 Stage、API 12、包名 `org.focus.mobile`。选择配有此 SDK 的 DevEco 工具链。模拟器还需要相应镜像和虚拟化支持。[DevEco Studio](https://developer.huawei.com/consumer/cn/deveco-studio/)
2. 在 **Project Structure → Signing Configs** 为 default 产品配置签名。可使用 DevEco 的自动签名，或选择自己的调试密钥、证书和包含目标设备的调试 profile。证书、包名、设备范围须匹配。保留签名文件在开发者自己的环境。
3. 选择 entry/default 的 debug 构建，执行 **Build Hap(s)**。已配置 DevEco 命令行环境时可在工程根执行 `hvigorw --mode module -p product=default -p module=entry@default assembleHap`。签名成功后通常输出 `entry/build/default/outputs/default/entry-default-signed.hap`。同目录的 `*-unsigned.hap` 可用于检查包内容。
4. DevEco **Run** 可安装到已连接的模拟器或具备调试安装条件的手机。命令行使用 `hdc list targets`，再执行 `hdc -t <目标标识> install -r <已签名HAP路径>`。商用设备对发行和调试安装分别有签名、profile 及系统安装渠道要求。只把调试 HAP 下载到手机，不能保证系统文件管理器允许安装。要走免调试的下载分发，需要对应的发布签名及系统接受的分发渠道。

模拟器运行真正的 ArkWeb，可以检查登录、文件选择器和界面。Windows/macOS 虚拟机可以承担源码编译和签名。运行内层设备模拟器还取决于宿主的虚拟化支持。开发机路由、模拟器路由、Pura X 上卓易通内 Tailscale 对其他 App 的路由是三个不同的验证环境。

## Linux 上的公开 SDK 编译检查

安装 Node 22、JDK、公开 OpenHarmony 5.0 API 12 Linux SDK 和 Hvigor。SDK 根目录下需有 `12/{ets,js,native,toolchains}`。以下命令在隔离的工具目录安装官方 Hvigor。已有工具链时可以直接传入对应的 `node_modules`。

```sh
npm install --prefix /path/to/focus-hvigor --registry=https://repo.harmonyos.com/npm/ @ohos/hvigor@5.2.2 @ohos/hvigor-ohos-plugin@5.2.2
python mobile/harmony/verify_openharmony.py --sdk /path/to/openharmony-sdk --modules /path/to/focus-hvigor/node_modules
```

脚本复制同一份 ArkTS、页面和资源，以公开 SDK 的 `OpenHarmony/default` 设备类型执行资源编译、ArkTS 编译、SysCap 检查和 HAP 打包，校验 `ets/modules.abc`。产物为 `mobile/harmony/build/focus-openharmony-api12-unsigned.hap`。Pura X 使用上文的商用 HarmonyOS 构建、签名和分发流程。

## Pura X 后续验收

安装了可运行的鸿蒙包后，先在实例列表点击 **通路检查**。这是同一应用、同一 UID 下的最小 ArkWeb 页面，使用独立的临时浏览上下文。分别检查两个入口。收到对应站点的 Basic 挑战或正确的入口响应，可以确认该 App 到该入口的 HTTPS 请求已到达。超时或 TLS 错误时保留错误码，核对同一时刻和同一网络下系统浏览器的结果。再回实例列表打开完整客户端检查认证、API、WebSocket 和文件。此步骤可在方便验证时完成。

| 操作 | 观察结果 |
| --- | --- |
| 给两个入口保存不同密码，分别在同名线程写不同草稿，切换并关闭 App 后重新打开 | 当前线程、草稿和访问权限随实例恢复。无外层认证的入口直接进入。 |
| 在有历史的线程上滚到中段，输入草稿，短暂和较长时间锁屏、切后台，再解锁 | 页面可读、可继续输入。观察原消息位置及新事件，记录是否弹窗或需要刷新。折叠与展开屏幕各测一次。 |
| 临时关闭手机的 Tailscale，再打开 | 断网阶段保留现场，连通后重新确认最新服务端状态。 |
| 在有维护窗口的测试环境暂时停用上游转发，或重启测试 Focus，保持客户端打开 | 观察 5xx、重连、重新注册和原线程恢复。实际 B 发起的 SSH 连接由原部署恢复。 |
| 在测试入口更改 Basic 密码，并单独使 Focus 会话过期 | 拒绝的密码进入更新入口，错误密码不会循环弹窗。Focus 授权过期使用 Focus 原有入口。 |
| 在服务端可能已接收 prompt 或审批后断网 | 用线程、待处理请求、mutation result 等服务端证据核对，若无法确认，保留结果未知。检查是否发生重复请求或中断了其他任务。 |
| 在两个入口各打开线程，接收流式更新，选择并上传文件，再预览和另存较大文件 | 核对两端文件内容、传输完成状态和保存位置。取消选择、暂离 App、外链和 HTML 预览也各检查一次。 |
| 使用已有网页登录入口，同时在普通浏览器打开 Focus | 验证自己的 IdP 流程、旧版 Web 与无桥接浏览器的实际表现。 |

## 在隔离环境复现 Android 网络检查

`mobile/tests/emulator_gateway.py` 创建三个监听 loopback 的真实 WebGateway，其中两个经临时 HTTPS 代理访问，第三个使用 Focus 本地授权，业务后端使用仓库的测试 harness。Android 模拟器通过 `10.0.2.2` 访问。需要系统可执行的 Caddy、OpenSSL、安装好仓库依赖的 Python 和已经构建的 Web。以下命令在仓库根运行，使用单独的测试目录。

```sh
(cd web && npm ci && npm run build)
lab=$(mktemp -d)
openssl req -x509 -newkey rsa:2048 -nodes -days 2 -keyout "$lab/ca.key" -out "$lab/ca.pem" -subj "/CN=Focus temporary test CA" -addext "basicConstraints=critical,CA:TRUE"
openssl req -new -newkey rsa:2048 -nodes -keyout "$lab/server.key" -out "$lab/server.csr" -subj "/CN=10.0.2.2"
echo "subjectAltName=IP:10.0.2.2" > "$lab/extensions"
openssl x509 -req -in "$lab/server.csr" -CA "$lab/ca.pem" -CAkey "$lab/ca.key" -CAcreateserial -days 2 -extfile "$lab/extensions" -out "$lab/server.pem"
python mobile/android/build.py --sdk "$ANDROID_HOME" --debug-ca "$lab/ca.pem"
adb install -r mobile/android/build/focus-debug-test-ca.apk
.venv/bin/python mobile/tests/emulator_gateway.py "$lab"
```

在该目录的 `instances.json` 读取两个临时地址和第一个入口的临时测试密码，用户名为 `tester`。第二个入口由测试代理放行。第三个条目用于本地模式测试，可用 `adb reverse tcp:<第三个条目的端口> tcp:<同一端口>` 建立模拟器回环通路，再通过 App 的「授权链接」打开测试目录的 `local-link.txt`。每次重启测试服务会生成新的一次性链接。测试包有不同的 Android 包名和专用信任锚。系统选择器保存 Demo 线程里的 `sample.txt` 后可与测试目录中的文件比较 SHA-256。退出测试进程即可关闭测试入口。

如需复现 SSH 中断，在上述夹具命令后加 `--basic-forward-port <临时转发监听端口>`。启动后，夹具把 Basic 入口的 Focus 后端端口写入 `$lab/forward-target.txt`。在隔离的 SSH 测试环境中，把本地转发监听端口连到该后端的回环地址。仅停用并重启这条测试转发，即可观察代理返回 502 和恢复后的 WebSocket 握手。

在已完成首次登录的 Android 模拟器保持待测实例打开，运行以下脚本可观察静态资源、注册、meta、WebSocket 101/hello，并验证系统 Home、模拟器息屏唤醒和强制停止后的线程及文字草稿。脚本只接受模拟器、测试包名和上述临时入口，会在 Demo 线程填写一条测试草稿。测试第二个入口时先切换实例再指定 `--entry 1`。

```sh
.venv/bin/python mobile/tests/android_webview_smoke.py --serial emulator-5554 --entry 0 "$lab"
```

在专用模拟器的飞行模式关闭时，可给 HTTPS 入口的上述命令加上 `--cycle-network`。脚本切换飞行模式、临时关闭 Wi-Fi，确认断网期间 HTTPS 无法读取，恢复原网络设置后检查同一页面的 WebSocket 握手。想复现会话过期，可在启动服务夹具时加 `--session-lifetime 60`，在模拟器脚本中加 `--wait-session-expiry`。服务夹具还可加 `--second-basic`，为第二个 HTTPS 入口设置独立密码，适合用同一主机的两个端口测试 Android 凭据隔离。

为两个 HTTPS 入口分别完成首次登录并选中第一个实例后，用下列命令验证热切换和进程回收。若已配置第三个模拟器回环入口，可加 `--third-origin http://127.0.0.1:<该端口>` 验证淘汰和冷恢复。脚本从会话标题进入系统实例列表，观察两个 document 的标识、真实 WebSocket 握手和关闭、POST、草稿及历史消息相对位置。

```sh
.venv/bin/python mobile/tests/android_tabs_smoke.py --serial emulator-5554 "$lab"
```

JDK 可独立运行 Android 的站点、端口和 Basic realm 策略测试。

```sh
out=$(mktemp -d)
javac -d "$out" mobile/android/src/org/focus/mobile/Site.java mobile/tests/SitePolicyTest.java
java -cp "$out" org.focus.mobile.SitePolicyTest
```

## 本次验证记录

| 环境 | 已观察到的结果 |
| --- | --- |
| Pura X，HarmonyOS 7.0.0，卓易通内运行 Android 版 Focus（用户真机反馈） | 用户成功安装 APK、打开当前实例并在对话中发送消息，对端已收到。 |
| 标准 Android 调试 APK，Android 15 模拟器 | APK v3 验签、安装和启动成功。从原生界面输入一次性本地授权链接后，可打开测试线程、看到附件链接并使用输入框。 |
| 同源码的测试 CA 包，系统 WebView 124 | 通过隔离的 Basic HTTPS、无 Basic 的可信代理 HTTPS 和本地授权三个入口加载页面、静态资源和 API，收到 WebSocket 101 和 hello。两个主机名及 realm 相同、端口不同的 Basic 入口分别复用了自己的密码，恢复了同名线程里的不同草稿。模拟器息屏唤醒及进程重启后可继续输入。错误密码和已变更密码均可进入更新入口。 |
| Android 1.0 → 1.1 覆盖安装，系统 WebView 124 | 两个同主机不同端口的 Basic 入口，在旧包中分别留下文字草稿和持久 Cookie。用相同签名覆盖安装后，两个原线程、不同草稿和各自的 Cookie 都可用；核对了 Cookie 的 HttpOnly、Secure、SameSite 属性，两个入口均未再次询问已保存的 Basic 密码。 |
| Android 1.1 实例切换，隔离的双 HTTPS Gateway | A 为阅读模式、B 为普通模式。经原生列表 A → B → A → B，各自 document 标识保持，停用页关闭 WebSocket，返回页收到 101 和 hello，热切换期间未观察到 POST。强制停止后，两页重新注册并恢复各自线程、草稿和模式；旧格式对话的原消息位置偏差小于 4 个 CSS 像素。打开第三个实例后，最久未使用的页面被释放，再选择它时按已保存的现场重建。 |
| Android 模拟器系统断网和 Focus 会话过期 | 飞行模式并关闭 Wi-Fi 后，页面收到离线状态且 HTTPS 读取失败。重新联网后，同一 document 收到 WebSocket 101 和 hello。另一次测试中服务端发出 `session_expired`，可信代理入口完成新页面注册并收到 hello，原线程和草稿可用，期间只发送了注册 POST。 |
| 隔离的 Caddy、OpenSSH 和 Focus Gateway | 停用转发时返回 502，恢复后原 document、线程和草稿仍在，WebSocket 重新握手，观察期间没有 POST。重启测试 Focus 后也能重新进入原线程。经 Basic 和 SSH 的系统选文件上传成功，预览和系统另存的 176000 字节文本与服务端样本的 SHA-256 一致。业务后端采用仓库的 Codex 测试实现。 |
| Android 系统打印 | 从 Web 的问答导出菜单进入预览，用系统打印面板另存 PDF，再从模拟器取回文件提取文字，核对了所选问题和最终回答。草稿与界面控件均未出现在 PDF 内。 |
| 共享 Web 和 Gateway 自动化 | 覆盖普通 Chromium 页面重新注册、历史消息阅读锚点、草稿、鉴权和结果未知请求核验。相关验证范围内 896 项 Python 测试、1112 项 Web 测试通过，Web 类型检查、生产构建和仓库 guard 通过。 |
| 鸿蒙原生 Focus | 公开 OpenHarmony API 12 SDK 已完成 ArkTS、资源、SysCap 和未签名 HAP 编译检查。商用 HarmonyOS 签名安装、原生 Focus 的 ArkWeb 经卓易通内 Tailscale 访问实例、Pura X 折叠布局及真机锁屏恢复待验。具体 SSO 身份提供方和生产服务升级也待对应环境验收。 |

## 后续范围

推送服务、设备登记与撤销、通知分类及权限、原生包自动更新和应用商店发布独立交付。服务端升级仍走 Focus Web 当前的管理流程。
