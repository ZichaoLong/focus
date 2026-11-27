# Focus 手机客户端

Android 使用系统 WebView，HarmonyOS 使用 ArkUI Stage 工程和 ArkWeb。两端都从所选实例加载 Focus Web。对话、管理、设置、Focus 服务升级、审批和附件使用实例当前提供的实现。安装包与实例可独立升级。恢复和系统保存文件需要实例部署包含移动容器协议的 Web 版本。[移动容器合同](../docs/contracts/focus-mobile.zh-CN.md)

## 移动端开发导航

在仓库根目录列出涉及移动端的能力，包含与实例 Web 共用的能力。

```sh
python scripts/focus_nav.py list --under mobile
```

用 `python scripts/focus_nav.py show <能力>` 查看合同、实现文件、测试以及本页对应的构建和验收章节。已知文件时，可用 `python scripts/focus_nav.py paths <文件> --locations` 反查。`python scripts/focus_verify.py <能力> --dry-run` 展示自动检查及单独执行的平台验收，去掉 `--dry-run` 即可运行自动检查。[仓库职责地图](../docs/architecture/focus-design.zh-CN.md#6-仓库职责地图) · [仓库开发与验证规范](../docs/architecture/development-navigation.zh-CN.md)

## 批量更新 Focus 服务端

打开左侧实例抽屉，进入「管理实例 → 服务端更新」。默认沿用每套安装的渠道，也可以选择 main 或 stable。点「检查并准备全部」可检查所有入口。如果某个实例检查失败，网络恢复后，勾选该行的「检查」，点「检查并准备所选」即可单独重试。首次检查也可以这样选一个或多个入口。

列表会合并共用一套安装的入口，显示安装版本、目标 commit 及准备进度。切回对话后，已经收到请求的服务端会继续准备。就绪安装的「更新」默认勾选，可按需取消。点「确认更新已就绪的 N 套安装」后才会逐套提交更新。更新前结束该安装下仍在运行的任务，或稍后再更新。

首次使用时，较旧的服务端要先在该实例的「设置 → 服务端更新」里升级一次。需要 Basic、SSO 或 Focus 授权时，点对应行的「打开实例」完成。网络暂断或服务重启时，回到批量页会核对原操作。已经发出但结果待核实的更新不会自动重发；退出页面时还没提交的安装可在回来后再次勾选确认。如果切换到尚未支持批量管理的旧 stable，可展开「操作 ID」，在该实例的更新页核对结果。手机里的 APK 仍在「关于 Focus Mobile」更新。


### 批量更新设备验收

在测试安装上添加两个指向同一安装的入口和一个独立安装。暂时断开独立安装，选择 main 并检查准备全部，核对别名只准备一次。记下就绪操作 ID，取消该行的「更新」。恢复连接后，只勾选独立安装的「检查」并点「检查并准备所选」，核对只有这套安装收到检查请求，另一套仍显示原就绪操作且「更新」未勾选。退出后重进，核验原操作，再确认选中的一套安装并核对版本。在 Android 和鸿蒙上各走一次壳内管理页。

## 配置入口

1. 先连上通常用来访问实例的网络。在使用 Tailscale 的手机上手动打开它。
2. 打开 Focus，选「添加实例」，输入显示名和 HTTPS 站点根地址，例如 `https://focus.example.net`。可使用自定义端口。本地模式支持手机回环的 HTTP 地址（仅限 `127.0.0.1`、`localhost`、`[::1]`）。远端域名或 IP 必须与手机信任的 TLS 证书匹配。
3. 打开该实例。窄屏和阅读模式点顶栏的「切换实例」图标，宽屏从侧栏进入。左侧抽屉列出所有实例，当前实例带勾。点另一行直接切换，点当前行或右侧遮罩可立即收起。Android 也可在抽屉内向左滑动收起。点底部「管理实例」进入完整列表。点「返回对话」或用系统返回键可回到进入管理前的对话。若已删除该入口或更换地址，可从列表选择仍有效的实例。每行的「⋮」提供重新连接、编辑、使用 Focus 授权链接和删除。切换时直接显示目标页面。若加载较慢、旧版网页没有入口或连接失败，可点左上角的「切换实例」打开同一抽屉。在对话顶层也可用系统返回打开抽屉。更换地址会创建新的本地身份。
4. 为其他实例重复上述步骤。为独立入口使用不同的主机名，尤其是代理使用 Cookie 登录时。ArkWeb API 12 的 Cookie 存储以主机划分，此版鸿蒙端会拒绝同主机的第二个条目。Android 对支持多配置的系统 WebView 使用独立的命名配置，同一主机的不同端口也可隔离。旧引擎一次打开一个实例，继续使用各自的数据目录。

| 入口已有的认证 | 手机上的操作 |
| --- | --- |
| Focus 自身授权 | 选择「⋮ → 使用 Focus 授权链接」，一次性打开实例签发的、同一站点根地址的 `#token=…` 链接。本地模式须先有可用的本机回环入口，地址和端口须与链接一致。有可信代理的远端入口使用现有代理授权。Focus 的注册或会话过期时按页面提示重新授权。 |
| 可信代理或私网 ACL 放行 | 直接打开。代理继续在服务器端完成 Focus 的可信入口准入。 |
| 标准 HTTP Basic | 第一次收到匹配的挑战时，核对对话框中的站点与 realm，输入用户名密码。勾选「安全保存凭据」可在下次启动时复用。Android 使用 Keystore 加密，鸿蒙使用 Asset Store。拒绝后选择更新凭据或重新连接。 |
| 网页登录或 SSO | 在该条目的编辑界面勾选「允许跨站登录（SSO）」，在网页内完成 HTTPS 登录和回跳。仅使用 HTTP Basic 或同站网页登录的入口可以关闭此项。身份提供方须允许嵌入式浏览器。可用性还取决于 IdP 的 Cookie、二次认证和回跳策略。 |

Basic 凭据只在 HTTPS 上响应。Basic 处理适用于首页、静态资源、API 和 WebSocket 共用同一个 HTTP 保护空间的入口。客户端在配置的站点上验证标准挑战，再由引擎为同保护空间的请求完成认证。成功前不会持久保存新输入的密码。网络故障保留已保存的凭据。删除实例清除该条目的安全凭据和 Focus 页面数据。网页登录的共享 IdP 仍可以保有自己的会话。

只填写最终访问地址。HTTPS 代理直接连接 Focus、通过 SSH 访问远端 Focus，以及 Tailscale 的直连和 DERP 情况都由原部署处理。Focus 的 proxy proof 由服务器端代理提供。[Focus 外部访问合同](../docs/decisions/focus-web-external-access.zh-CN.md)

## 外链和系统返回

在对话或 Markdown 文件中点击外部 HTTPS 链接，App 会在原页上方打开独立网页，顶栏显示正在访问的站点。点「‹ 回到 Focus」或按一次系统返回即可关掉整页，即使外站发生过重定向。也可点「用浏览器打开」。此功能独立于跨站登录选择。外链页使用独立的浏览数据，Android 的外站可以在外链专用目录中保留自己的登录 Cookie，鸿蒙使用 ArkWeb 临时上下文。HTML 附件预览沿用沙箱的外链限制。

文件预览内按系统返回会先关闭眼前的层。例如从 `A.md` 点开 `B.pdf`，返回一次会重读 `A.md`，再返回一次回到原对话。键盘、系统文件选择器、文件名浮层、下载表单或放大的图表在前面时，先退这一层。「×」可结束整条文件预览。原页面被回收时，按下文的线程、草稿和阅读位置记录恢复，临时文件预览历史只留在内存中。

在对话顶层，按一次系统返回键或做一次系统返回手势会打开左侧实例抽屉。要马上回到对话，可点右侧遮罩。在 Android 上也可从面板内向左拖过约三分之一宽度，或快速向左一甩。慢慢拖一小段就松手，抽屉会弹回原位。上下滑动可滚动实例列表。

用系统返回打开抽屉后，2 秒内再次使用系统返回，Focus 会退到后台。超过 2 秒再返回则回到当前对话。点图标手动打开抽屉后，按返回会直接回到对话。下次点 App 图标优先回到上次的实例。从其他应用进入或在卓易通中运行时，系统或宿主决定退后台后显示哪个界面。要使用预览返回和完整的外链分流，请同时更新 App 和实例的 Focus Web。旧 Web 仍可使用原生网页历史，跨站登录开启时旧网页的外链也可能留在实例自己的 WebView。

## 恢复与文件

进入前台会触发现有 WebSocket 健康检查。断线时退避重连，握手后重新读取服务端状态。若原页面注册已清理，满足安全条件的可见页面会限频重新注册。被其他标签替换的身份须显式刷新。有待核验操作时，先按 Focus 提示查看结果。服务端任务继续按原生命周期运行。在「管理实例 → 保留实例页面数」可选 1 至 5 页，默认 2 页，含当前页。支持多配置的 Android WebView 和鸿蒙 ArkWeb 按使用顺序保留各实例最近一页。旧版 Android 引擎一次打开一页。展开或关闭抽屉时原页仍在线。选中另一个实例或进入管理界面，原实例才暂停 WebSocket、状态轮询和重试。切回后重新握手并核对服务端状态。超出容量或调低上限时先释放最久未访问的页。页面被淘汰、系统回收内存、网页未确认暂停或手动「重新连接」后，下次打开会重建。

每个实例可恢复上次已确认的线程、阅读或普通模式、文字草稿和可验证的历史消息位置。共享 Web 在引擎支持时使用 IndexedDB 的严格落盘事务保留这些显示数据，沿用既有草稿清理策略。升级各实例提供的 Focus Web 后才会提供新的切换入口和模式恢复。离线期间可以看到仍在内存里的页面。Android 1.10 配合新版实例 Web，冷启动可在普通聊天界面接着读已保存的消息，联网后自动接续。点「查看离线副本」也可进入本机记录的专用阅读器。历史内容已删除、服务器拒绝打开线程或用户另选了位置时，按服务器当前结果显示。结果未知的 prompt 使用既有定位记录查询，审批、回答、中断和其他业务操作由原有处理流程核验。选中的附件和提交权限仍属于原 writer。Tailscale、SSH 或代理恢复连通后，页面才有条件接续。

在实例的 Web 设置中，「每个实例记住的最近线程数」可选 5、10、20，默认 10。每个位置只保存消息标识、偏移和阅读或普通模式。切回线程先确认服务端状态，分页对话直接读取锚点附近的一页；原消息已删除时回到最新页。沿用同一浏览器标签刷新可恢复书签，App 重建页面也可恢复。Android 已保存的消息可先从本机读取，首次打开和遇到未保存的历史位置时仍需联网。草稿按原有清理策略管理，调低书签上限只淘汰阅读记录。

同一轮连续的工具调用摘要从第一条起收在一个组头内，显示数量、运行状态和失败数。点击组头展开后，新调用会留在已展开的组里。来回切线程、浏览器标签或尚在内存的实例时可保留手动选择；页面刷新或回收后重新默认折叠。

普通模式和阅读模式中，点「最新消息」会先向当前实例确认最新内容，并尽量保留已经读过的连续上下文。若折叠工具后仍有大片空白，页面会尝试补足一屏。在 App 里切回原本跟随最新消息的实例，会等连接握手、最新页和对话区布局就绪后判断。若切回时窗口较小，窗口变大后会再看一次；若连接再次握手或补页位置临时过期，会按新确认的位置继续。每次补屏最多三次请求，成功响应单次最多 128 KiB、合计最多 256 KiB。整体重同步替掉先前可读的正文时，从新确认的分页位置恢复这一屏。切走前正在读历史消息时，切回来仍定位到那条消息。工具调用连续很多页时仍可能只显示一个组头，可用滚轮、滑动或「加载更早消息」继续向前翻。此项改动随各实例的 Focus Web 更新。

附件由系统文件选择器交给现有上传入口。下载使用 Web 中「另存为」，选择系统目标后，Web 用当前会话读取内容，原生分块暂存并写入目标。可在预览里查看文本、图片、PDF 等已有格式。HTML 预览保留现有沙箱。Web 不向外部网页提供原生文件桥接。

从会话菜单选「打印或保存 PDF」，选择轮次和内容后点「打开预览」。在「打印预览」里可编辑文档标题并点「打印」。若系统明确拒绝，会立即显示原因。若一直留在预览，约三秒后会提示当前环境可能不支持系统打印，可点「试试下载 PDF」。选择保存位置即可继续，同一实例的服务器会显示进度、实际使用的排版方式及已检测到的字体或内容问题。实例需更新到支持服务器 PDF 的共享 Web。「返回对话」回到原线程。

## 手机上更新

**更新当前机器的 Focus 服务**。打开会话设置 → 服务端更新，选 main（也可指定 commit）或 stable 并准备。就绪后点「应用更新并重启」，核对实例、主机、目标和提交，再确认。在同一页展开「关于 Focus Web」可查看版本和后端身份。服务端会检查完整的 operation ID 和运行状态，停服影响该机的全部 Focus 实例。响应丢失时重新读取该操作的状态。页面仍显示可选取、复制的完整 ID，供诊断使用。

**更新 Android App**。首次安装或从 1.1 升级，可用手机或电脑打开 [Android main 清单](https://github.com/ZichaoLong/focus-mobile-dist/blob/main/channels/main.json)，从同一仓库的 `android/<sha256>.apk` 下载并覆盖安装。Pura X 上已有卓易通版时，在同一卓易通 Android 环境打开 APK。已有新壳后，将所用实例也更新到支持移动分发的 Focus，然后从「切换实例 → 关于 Focus Mobile」选 main 或 stable，点「检查客户端更新」。检查时会显示实例正在准备安装包。下载时会显示手机已写入的大小、总大小和百分比，传输结束后校验安装包。点「下载安装」后按系统提示允许该来源并确认覆盖安装；也可点「另存 APK」，用系统文件选择器保存已验证的文件，再交给安装器打开。相同内容显示已安装，低于已装版本号的渠道只显示状态。渠道还未首次发布时会提示暂无版本。

部署机器需要能用 Git 读取移动分发仓库。默认地址为 `https://github.com/ZichaoLong/focus-mobile-dist.git`。服务账户可沿用其 Git 代理、凭据助手或 SSH 配置。fork 的运营者在启动 Focus 服务的环境中设置 `FOCUS_MOBILE_DIST_URL` 为自己的 HTTPS 或 SSH Git URL 后重启服务。该设置与 Web 的「Git 更新源」独立。分发仓库有一个 `main` 分支，`channels/main.json` 和 `channels/stable.json` 可指向同一或不同的 APK。各源的清单与安装包保存在 `<FOCUS_DATA_ROOT>/mobile-updates/<源地址哈希>/`。只在用户检查时联网；源暂时不可达时显示上次校验时间。普通用户的 Focus 机器和手机均无需 Android SDK 或发布密钥。

检查更新时会自动回收临时目录和过期缓存。两个渠道各自当前使用的 APK 会保留，被替换或撤回的包再保留七天，供已选好版本的手机完成下载。

### Android 客户端更新验收

在专用测试实例和 Android 模拟器或手机上，以测试签名安装前一版，从测试分发源提供签名兼容的新包。分别走「另存 APK」和系统覆盖安装，核对文件摘要、安装版本及原实例数据。使用不同签名的测试包时，核对安装请求被拒绝。分发源配置见上节。

## Android 构建、签名与安装

需要 Node.js 22、Web 构建依赖（在 `web` 下执行 `npm ci`）、Python 3、带 `javac` 和 `keytool` 的 JDK（建议 17 或更新）、Android SDK Platform 35、Build Tools 35.0.0 和 Platform Tools。使用 Android Studio 的 SDK Manager 或已配置的命令行工具安装上述组件。

```sh
sdkmanager "platform-tools" "platforms;android-35" "build-tools;35.0.0"
python mobile/android/build.py --sdk "$ANDROID_HOME"
adb install -r mobile/android/build/focus-debug.apk
```

首次构建下载 Google Maven 的 AndroidX WebKit 1.12.1 并校验 SHA-256。离线构建可传 `--webkit-aar /path/to/webkit-1.12.1.aar`。

输出 `mobile/android/build/focus-debug.apk`，支持 Android 9（API 28）及以上。也可把该 APK 下载到手机，通过系统安装器打开并按系统提示允许此下载来源。首次构建在本用户的 `.android/debug.keystore` 生成调试密钥。覆盖升级需使用已安装应用认可的签名或轮换链。独立发布时使用自己的密钥签署已对齐的 APK，口令由工具交互读取。

```sh
python mobile/android/build.py --sdk "$ANDROID_HOME" --unsigned
"$ANDROID_HOME/build-tools/35.0.0/apksigner" sign --ks /path/to/release.jks --out focus-release.apk mobile/android/build/focus-unsigned.apk
"$ANDROID_HOME/build-tools/35.0.0/apksigner" verify --verbose focus-release.apk
```

使用相同包名和签名覆盖安装可保留现有实例和 Keystore 凭据。首次升级到多配置时，App 用本地空页面按原站点迁移 Focus 的草稿、恢复记录和根地址 Cookie，临时副本加密并在导入成功后删除。迁移遇到当前引擎不接受的数据时，会继续使用原有目录。已启用网页登录的旧条目沿用原配置，以保留 IdP 会话，切换时冷恢复。若已有命名配置后系统 WebView 被降级到不支持该能力的版本，恢复兼容的系统 WebView 即可重新使用原数据。

### Android 发布者流程

源代码在 Focus 仓库。正式 APK 和两份渠道清单在独立分发仓库的 Git 中跟踪。每次客户端发版才写入分发仓库。服务端源码提交、服务端 stable Release、Android main 和 Android stable 各自发布。仓库管理者可用以下方式发布。

1. 推送目标源码并确认准确提交的 CI 通过。用干净的 Android 源码构建已对齐的 unsigned APK，内嵌完整源码提交。用安全保存的发布密钥和 apksigner 签名。保留密钥、口令以及已有的轮换链，并保存可恢复的异地备份。
2. 校验包名、版本和预期的证书指纹。官方包名为 `org.focus.mobile`。Android 1.2 起的正式证书 SHA-256 为 `823ff9afe9baad124cbb73cb223cfa1dc18478a07158b7be039b99e0fed66dd4`。由以前的 `c58399d84703f71170c280c618e5c3bc6a618b03a593ff5bb9fd9aa86ffe8966` 签名的 1.1 用签名轮换链在 Android 9+ 覆盖升级。签名兼容仍由设备安装器最终裁决。
3. 在项目根运行发布工具。下面环境变量分别指定可推送的分发仓库、预期公钥证书指纹和通过 CI 的 40 位源码提交。工具在一个 Git 提交写入 APK 和渠道清单，然后独立读取远端字节、重验签名。固定分发提交的文件链接可长期下载。新的浅克隆只需当前渠道使用的包。

```sh
python scripts/publish_android.py --channel main --repository "$DIST_GIT" \
  --sdk "$ANDROID_HOME" --apk mobile/android/build/focus-release.apk \
  --certificate-sha256 "$CERT_SHA256" --source-revision "$SOURCE_COMMIT"

# 独立决定发布 stable 时，可晋升已验证的 main，无需重签或重建。
python scripts/publish_android.py --channel stable --promote-main --repository "$DIST_GIT" \
  --sdk "$ANDROID_HOME" --certificate-sha256 "$CERT_SHA256" --source-revision "$SOURCE_COMMIT"
```

发布回执包含渠道、源码提交、分发提交、固定到分发提交的 APK 下载链接，以及读回的 APK SHA-256 和签名证书 SHA-256。

维护官方的轮换签名时，给 apksigner 传已有的 `--lineage` 和 `--rotation-min-sdk-version 28`，使用正式密钥作为当前签名者。仅使用当前私钥签这一 API 28+ APK 时启用 v3、关闭 v1/v2。首次独立发布的 fork 可从第一次分发起使用自有包名或签名、分发仓库和证书指纹。不同签名使用独立包名可与官方安装并存。使用官方客户端的用户始终可以从自己的 Focus 服务获取官方签名包。

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

## 移动端真机验收

在目标设备安装待测 APK 或已签名的 HAP，使用设备实际访问测试实例的网络。分别记录系统版本、网页引擎、客户端版本和实例提供的 Web 版本。

| 操作 | 观察结果 |
| --- | --- |
| 给两个入口保存不同密码，分别在同名线程写不同草稿，切换并关闭 App 后重新打开 | 当前线程、草稿和访问权限随实例恢复。无外层认证的入口直接进入。 |
| 在有历史的线程上滚到中段，输入草稿，短暂和较长时间锁屏、切后台，再解锁 | 页面可读、可继续输入。观察原消息位置及新事件，记录是否弹窗或需要刷新。折叠与展开屏幕各测一次。 |
| 暂时断开并恢复手机访问测试实例使用的网络或 VPN | 断网阶段保留现场，连通后重新确认最新服务端状态。 |
| 在有维护窗口的测试环境暂时停用上游转发，或重启测试 Focus，保持客户端打开 | 观察 5xx、重连、重新注册和原线程恢复。转发由原部署恢复。 |
| 在测试入口更改 Basic 密码，并单独使 Focus 会话过期 | 拒绝的密码进入更新入口，错误密码不会循环弹窗。Focus 授权过期使用 Focus 原有入口。 |
| 在服务端可能已接收 prompt 或审批后断网 | 用线程、待处理请求、mutation result 等服务端证据核对，若无法确认，保留结果未知。检查是否发生重复请求或中断了其他任务。 |
| 在两个入口各打开线程，接收流式更新，选择并上传文件，再预览和另存较大文件 | 核对两端文件内容、传输完成状态和保存位置。取消选择、暂离 App、外链和 HTML 预览也各检查一次。 |
| 使用已有网页登录入口，同时在普通浏览器打开 Focus | 验证自己的 IdP 流程、旧版 Web 与无桥接浏览器的实际表现。 |

### 系统返回真机验收

在一个实例的嵌套文件预览里点外链，用系统返回依次关掉外链、退回上一文件、回到对话。切换到第二个实例，分别试手动打开抽屉后返回、从对话顶层连续两次返回并重开。记录每一步的落点、键盘或预览是否只退一层、重开后选中的实例。在 Pura X 上，原生鸿蒙应用和卓易通中的 APK 分别验收。

### Pura X 后续验收

在使用卓易通内 Tailscale 的 Pura X 上打开原生鸿蒙包，先在实例列表点击 **通路检查**。这是同一应用、同一 UID 下的最小 ArkWeb 页面，使用独立的临时浏览上下文。分别检查两个入口。收到对应站点的 Basic 挑战或正确的入口响应，可以确认该 App 到该入口的 HTTPS 请求已到达。超时或 TLS 错误时保留错误码，核对同一时刻和同一网络下系统浏览器的结果。再回实例列表打开完整客户端检查认证、API、WebSocket 和文件，并分别验收折叠与展开布局。

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

在该目录的 `instances.json` 读取两个临时地址和第一个入口的临时测试密码，用户名为 `tester`。第二个入口由测试代理放行。第三个条目用于本地模式测试，可用 `adb reverse tcp:<第三个条目的端口> tcp:<同一端口>` 建立模拟器回环通路，再通过 App 的「使用 Focus 授权链接」打开测试目录的 `local-link.txt`。每次重启测试服务会生成新的一次性链接。测试包有不同的 Android 包名和专用信任锚。系统选择器保存 Demo 线程里的 `sample.txt` 后可与测试目录中的文件比较 SHA-256。退出测试进程即可关闭测试入口。

### Android 打印重试验收

在 Android 15 userdebug 专用模拟器中打开上节隔离网关的第二个 HTTPS 入口，保持竖屏普通模式。用 `adb -s emulator-5554 root` 允许测试临时切换用户的系统打印限制。

```sh
.venv/bin/python mobile/tests/android_print_smoke.py "$lab" --serial emulator-5554
```

脚本在打开的问答预览中临时禁止系统打印，验证失败提示、系统文件选择器和服务端 PDF 的实际正文。恢复权限后，用系统打印面板保存同一份问答并再次提取文字。模拟器的文件选择器应使用本机共享存储。也可使用隔离网关的回环授权入口，经 adb reverse 转发后给脚本加 `--loopback`。

### Android 模拟器验证返回和外链

按上节准备隔离网关，启动时加 `--navigation` 以提供跨站跳转夹具。在专用测试 APK 中添加前两个 HTTPS 入口并完成首次登录后执行：

```sh
.venv/bin/python mobile/tests/android_navigation_smoke.py "$lab" --adb /path/to/adb --serial emulator-5588
```

脚本使用 Android 系统返回键、实际 WebView 链接、独立 HTTPS 外站和一次测试身份页回跳。模拟器已开启手势导航时，加 `--edge-gesture` 可用系统边缘侧滑运行相同场景。除文件逐层返回、外站 Cookie 和凭据隔离外，也检查从另一实例行上慢拖、快甩，点遮罩或当前行回到原对话，连续系统返回退后台和重开。要验证列表实际滚动，可在这两个测试实例之后再添加条目，直至抽屉超过一屏。

### 连接恢复和实例切换验收

如需复现 SSH 中断，在上述夹具命令后加 `--basic-forward-port <临时转发监听端口>`。启动后，夹具把 Basic 入口的 Focus 后端端口写入 `$lab/forward-target.txt`。在隔离的 SSH 测试环境中，把本地转发监听端口连到该后端的回环地址。仅停用并重启这条测试转发，即可观察代理返回 502 和恢复后的 WebSocket 握手。

在已完成首次登录的 Android 模拟器保持待测实例打开，运行以下脚本可观察静态资源、注册、meta、WebSocket 101/hello，并验证系统 Home、模拟器息屏唤醒和强制停止后的线程及文字草稿。脚本只接受模拟器、测试包名和上述临时入口，会在 Demo 线程填写一条测试草稿。测试第二个入口时先切换实例再指定 `--entry 1`。

```sh
.venv/bin/python mobile/tests/android_webview_smoke.py --serial emulator-5554 --entry 0 "$lab"
```

检查 5 页容量时，用 `--https-count 6` 启动隔离网关，先在测试壳中完成第一个入口的 Basic 登录（加了 `--second-basic` 时还需登录第二个）。运行下列命令。脚本仅使用指定的专用模拟器和测试包，添加缺少的测试入口，测量宿主与 renderer 的 PSS，验证管理返回、调低上限和冷恢复。

```sh
.venv/bin/python mobile/tests/android_page_retention.py "$lab" --serial emulator-5584
```

在专用模拟器的飞行模式关闭时，可给 HTTPS 入口的上述命令加上 `--cycle-network`。脚本切换飞行模式、临时关闭 Wi-Fi，确认断网期间 HTTPS 无法读取，恢复原网络设置后检查同一页面的 WebSocket 握手。想复现会话过期，可在启动服务夹具时加 `--session-lifetime 60`，在模拟器脚本中加 `--wait-session-expiry`。服务夹具还可加 `--second-basic`，为第二个 HTTPS 入口设置独立密码，适合用同一主机的两个端口测试 Android 凭据隔离。

为两个 HTTPS 入口分别完成首次登录并选中第一个实例后，用下列命令验证热切换和进程回收。若已配置第三个模拟器回环入口，可加 `--third-origin http://127.0.0.1:<该端口>` 验证淘汰和冷恢复。脚本先检查旧网页延迟出现的原生入口与页面接手后的可用高度，再从顶栏或侧栏进入实例抽屉，观察两个 document 的标识、真实 WebSocket 握手和关闭、POST、草稿及历史消息相对位置。

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
| 生产版 Focus Web，窄屏 Chromium，受控 API 和事件连接 | 阅读模式对话区高 624 CSS px。分别重放小视口切回后再放大、首次补页返回 `409 stale_thread_read`、补页后再次握手；旧版三种情况下都留下 266 CSS px 空白，新版均为 26 CSS px。另用 14 次工具调用、一段回复、57 次工具调用（8 次失败）的跨页记录验证：第一张旧页合并后空白约 248 CSS px，第二张带回上一段正文后约 26 CSS px，两组保持折叠。 |
| Android 15 模拟器，WebView 124，四个隔离 HTTPS 入口 | 批量页通过真实 TLS、Basic 和可信代理访问生产管理文档与 Gateway。四个入口汇总为三套安装，已是最新的一套未启动准备，其余各准备一次。强制停止并重新打开后复用认证和两条 ready 记录，一次确认按顺序各提交一次。使用真实更新 journal，测试替身负责远端候选元数据、构建和安装，不涉及真实停服。 |
| Android 15 模拟器，系统 WebView 124，隔离的回环 Focus Gateway | 通过原生抽屉从 A 切到 B 再回 A。22 条工具与文字记录按需补到 23 条。首次补页返回受控的 409 时，实际请求顺序为最新页、旧页、重新确认最新页、旧页；回到同一文档，底部留白为 26 CSS px。另在 1.5.1 测试壳中实际切换到重建的 WebView 文档：恢复阅读模式，读最新页并补两页，共 73 条，两组 14 和 57 次工具调用仍折叠，底部留白为 26 CSS px。 |
| Android 15 模拟器，系统 WebView 124，阅读模式，本机回环 Gateway 与隔离的 HTTPS 实例 | 用原生抽屉从 A 切到 B 再回 A。修复前，A 的已加载记录从 81 条降至 40 条，折叠工具下方的空白从 26 增至 418 CSS px。修复后，同一文档重读最新页并沿 cursor 补两页，恢复 81 条，工具仍折叠，空白为 26 CSS px。先上翻阅读旧回复再切换，切回仅按原消息读取一次，阅读偏移误差小于 4 CSS px。 |
| Android 15 模拟器，三键导航和边缘返回手势 | 两种导航均验证了首次返回打开实例抽屉、2 秒内再返回退后台、超时或手动打开后返回原对话。嵌套文件预览逐层返回，独立外链关闭后回到原文档。无网页抽屉的页面先使用完整高度，稍后可用原生「切换实例」，恢复网页抽屉后再次使用完整高度。 |
| Android 1.4.1 测试壳，Android 15 模拟器，系统 WebView 124 | 通过回环访问隔离的 Focus Gateway，使用 81 个受控分页条目和生产 Web 资源。阅读模式里有 80 个已读条目时，工具折叠后的底部空白为 298 CSS px。点「最新消息」重读最新页并补一页，空白降至 26 px。再次上翻并返回最新，保留 81 行和折叠状态，网关只收到一次最新页读取。 |
| Android 1.4，API 35 模拟器，隔离 HTTPS 网关 | 从 Basic 入口的对话与 Markdown 预览实际点击链接。SSO 开关两种状态下，独立网页都跟随 302，目标未收到实例 Cookie 或认证头。按系统返回回到原文档，阅读模式及草稿保留，阅读位置偏差小于 5 CSS 像素。嵌套文件逐级回到对话。系统输入法展开时，第一次返回只收起键盘。关闭 SSO 时自动跨站登录被拦住，开启后测试身份页可回跳。切换两个实例后顶层按返回离开 Focus，再点图标回到最后实例的同一文档。 |
| 共享 Web，Chromium | 已协商的返回动作逐层收起文件名浮层、下载表单、Mermaid 查看器，能从 PDF 和读取失败的文件信息回到 Markdown，首份文件返回对话。普通浏览器继续通过工具栏箭头和关闭按钮使用现有预览。 |
| Pura X，HarmonyOS 7.0.0，卓易通内运行 Android 版 Focus（用户真机反馈） | 用户成功安装 APK、打开当前实例并在对话中发送消息，对端已收到。 |
| 标准 Android 调试 APK，Android 15 模拟器 | APK v3 验签、安装和启动成功。从原生界面输入一次性本地授权链接后，可打开测试线程、看到附件链接并使用输入框。 |
| 同源码的测试 CA 包，系统 WebView 124 | 通过隔离的 Basic HTTPS、无 Basic 的可信代理 HTTPS 和本地授权三个入口加载页面、静态资源和 API，收到 WebSocket 101 和 hello。两个主机名及 realm 相同、端口不同的 Basic 入口分别复用了自己的密码，恢复了同名线程里的不同草稿。模拟器息屏唤醒及进程重启后可继续输入。错误密码和已变更密码均可进入更新入口。 |
| Android 1.3，API 35 模拟器，六个隔离的 HTTPS 入口 | 容量设为 5 时，依次打开五页、重访第一页、再打开第六页，只释放第二页。管理页的「返回对话」与系统返回都回到原页面。改名并返回后，网页收到新显示名，已打开的文档未重载。降为 1 仅留当前页，再切实例按已保存现场重建。对同一示例线程测量宿主与 renderer 的总 PSS，分别保留 1、2、5 页时五次采样中位数约 194、248、372 MiB。页面内容、引擎及设备会影响实际占用。 |
| Chromium，共享 Web | 窄屏两线程在延迟和限速夹具下往返，恢复各自草稿、模式和原消息位置。返回分页线程的第一笔正文读取直接指定原消息。80 条流式工具调用保持折叠，手动展开后新成员继续加入同一组，失败数仍可见。 |
| Android 1.2，API 35 模拟器、两个真实 HTTPS Basic 测试入口 | 抽屉选中当前项后原 WebSocket 保持连接。切换 A → B → A → B 保留各页 document、线程、草稿和模式，停用页断开，返回页重新 101/hello，切换未产生业务 POST。切换后立即强停再启动，两页均恢复最后一份文字，阅读锚点偏差小于 4 个 CSS 像素。 |
| Android App 内更新，API 35 模拟器，测试 CA 和隔离的 Git 源 | 在当前实例的抽屉打开「关于」，下载测试渠道 APK。异签名包被原生校验拒绝。用「另存 APK」保存的文件与服务端 SHA-256 一致；允许此安装来源并经系统安装器覆盖后，设备上实际安装的 base.apk 也与分发文件字节一致。 |
| Android 官方包签名迁移，API 35 模拟器 | 从此前 1.1 的签名通过 v3 轮换链覆盖升级为正式签名的 1.2，核对 UID 和升级前五份偏好文件的摘要保持一致。Pura X 卓易通中的本次覆盖升级仍待真机验收。 |
| Android 1.0 → 1.1 覆盖安装，系统 WebView 124 | 两个同主机不同端口的 Basic 入口，在旧包中分别留下文字草稿和持久 Cookie。用相同签名覆盖安装后，两个原线程、不同草稿和各自的 Cookie 都可用；核对了 Cookie 的 HttpOnly、Secure、SameSite 属性，两个入口均未再次询问已保存的 Basic 密码。 |
| Android 1.1 实例切换，隔离的双 HTTPS Gateway | A 为阅读模式、B 为普通模式。经原生列表 A → B → A → B，各自 document 标识保持，停用页关闭 WebSocket，返回页收到 101 和 hello，热切换期间未观察到 POST。强制停止后，两页重新注册并恢复各自线程、草稿和模式；旧格式对话的原消息位置偏差小于 4 个 CSS 像素。打开第三个实例后，最久未使用的页面被释放，再选择它时按已保存的现场重建。 |
| Android 模拟器系统断网和 Focus 会话过期 | 飞行模式并关闭 Wi-Fi 后，页面收到离线状态且 HTTPS 读取失败。重新联网后，同一 document 收到 WebSocket 101 和 hello。另一次测试中服务端发出 `session_expired`，可信代理入口完成新页面注册并收到 hello，原线程和草稿可用，期间只发送了注册 POST。 |
| 隔离的 Caddy、OpenSSH 和 Focus Gateway | 停用转发时返回 502，恢复后原 document、线程和草稿仍在，WebSocket 重新握手，观察期间没有 POST。重启测试 Focus 后也能重新进入原线程。经 Basic 和 SSH 的系统选文件上传成功，预览和系统另存的 176000 字节文本与服务端样本的 SHA-256 一致。业务后端采用仓库的 Codex 测试实现。 |
| Android 系统打印 | 从 Web 的问答导出菜单进入预览，用系统打印面板另存 PDF，再从模拟器取回文件提取文字，核对了所选问题和最终回答。草稿与界面控件均未出现在 PDF 内。 |
| 共享 Web 和 Gateway 自动化 | 覆盖普通 Chromium 页面重新注册、历史消息阅读锚点、草稿、鉴权和结果未知请求核验。相关验证范围内 896 项 Python 测试、1112 项 Web 测试通过，Web 类型检查、生产构建和仓库 guard 通过。 |
| 鸿蒙原生 Focus | 公开 OpenHarmony API 12 SDK 已完成 ArkTS、资源、SysCap 和未签名 HAP 编译检查。商用 HarmonyOS 签名安装、原生 Focus 的 ArkWeb 经卓易通内 Tailscale 访问实例、Pura X 折叠布局及真机锁屏恢复待验。具体 SSO 身份提供方和生产服务升级也待对应环境验收。 |

## 后续范围

推送服务、设备登记与撤销、通知分类及权限、无人值守更新、鸿蒙 App 内分发和应用商店发布独立交付。服务端升级仍走 Focus Web 当前的管理流程。

## 本机离线记录

将需要保存的实例更新到支持 `records-v1` 的 Focus 服务端，并安装 Focus Mobile 1.7 或更新版本。在「管理实例 → 本机离线记录」选择实例，打开「自动保存正在浏览的线程」，再在线打开想保存的线程。也可以点会话标题，从会话选择器进入本机记录。实例各自设置。可验证分页的线程会由近到远补齐，离开实例或 App 时暂停。「部分已保存」和「已完整保存至…」显示本地副本的进度。

Android 1.10 起会在收到消息页时保存这一页。下次打开线程，聊天界面先显示上次阅读位置附近的消息，同时连接实例取得新消息。上翻优先使用已保存的页，补齐更多历史在前台空闲时进行。

Android 1.11 配合支持 `conversation-layout` 的实例 Web，本机首屏沿用该实例的主题、字号、语言和线程阅读模式。普通模式下，输入区先占位，连上后恢复原草稿和编辑。正在翻看一条长回复时，联网后从原段落接着读。手机顶栏提示连接状态。点会话标题，再点「查看离线副本」可打开专用阅读器。升级前保存的线程仍可打开，在线访问一次后会记住新版显示设置。

停留在专用阅读器时，在线页继续重连。工具组以计数行显示。点击计数会保留展开意图，网络恢复、Focus 会话有效且位置核验成功时在原处显示调用摘要。再点击一条才读取完整内容。重启 Focus 可能换发新会话，此时 App 会重新保存当前获准读取的内容。公式、媒体和交互图表可回到在线对话查看。

点「选择要清理的离线记录」查看折叠分组和已选数量。已归档、已确认删除和服务端已找不到的记录默认勾选；仅关闭、长期未读和待核实记录可逐条勾选。收起分组会保留选择。当前在读记录可在「全部记录」中手动勾选。管理页可切到所有实例。锁定记录仅显示汇总。支持元数据核对的 Focus 服务端可找出经其他工具移除的线程，旧服务端仍可按本机已有状态清理。清理仅删除本机副本和离线阅读位置。[本机离线记录合同](../docs/contracts/focus-mobile.zh-CN.md#本机离线记录)

Android API 35 模拟器使用两个隔离的 HTTPS Focus 网关（一个要求 Basic），接入可控的分页历史源。同一组线程和消息 ID 在两实例中有不同内容。230 轮、622 个源条目（462 条文字、两组各 80 次工具调用）保存后占用约 178 KiB 正文。系统强停并开启飞行模式后可读到从未在线翻看的第一条，再次强停可恢复阅读位置。联网后展开指定的 80 条，再选择单条可读完整输出。模拟器实测还覆盖了保存的 Basic 凭据复用、实例隔离和离线删除。

Android 1.10 在同一夹具、系统 WebView 124 下，阻塞服务端打开请求后，点回已保存线程约 0.33 秒即可读到旧回复。放行后，离开期间新增的回复出现一次。强停并进入飞行模式后，从桌面启动到普通聊天页显示加粗的旧回复约 4 秒。停在第一轮消息时恢复网络，在线会话在同一轮接续。这两项计时分别包含了线程切换和整个进程冷启动的成本。

### 离线记录真机验收

选两个认证设置不同的测试实例，分别保存含中间回复和多组工具调用的长线程，等到显示已完整保存。记下阅读位置，关闭网络并从系统强制停止 App，重开后翻到从未在线翻过的开头。点开一组、切换或收起、重新联网，核对仅最后保留的意图显示详情。再测试锁屏唤醒、修改 Basic 密码、服务重启、离线按线程清理，以及切回停放页面后不回填已删记录。Pura X 的原生 ArkWeb 经卓易通 Tailscale 访问仍需在商业签名包和设备上复核。

### 离线记录模拟器验收

自动验收覆盖普通和阅读模式。先用深色主题和 17px 字号打开带中英文长段落的会话并留下草稿，强停、断网后重新打开，从段落中间读三秒，再恢复网络。逐行比较交接前后的文字矩形及消息视口，核对草稿和输入权限。

Android 自动验收使用独立模拟器和短期测试 CA。按[隔离网关步骤](#在隔离环境复现-android-网络检查)准备测试证书、安装匹配的 test-CA APK 并构建 Web。在仓库根分两个终端运行以下命令，两边的 `lab` 指向同一测试目录。脚本会重置专用模拟器内的测试 App，并切换该模拟器的飞行模式。

```sh
.venv/bin/python mobile/tests/emulator_gateway.py "$lab" --records
.venv/bin/python mobile/tests/android_records_smoke.py --lab "$lab" --serial emulator-5594
```
