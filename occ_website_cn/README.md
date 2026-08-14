# OdooCC 网站中国生态增强（`occ_website_cn`）

`occ_website_cn` 面向中国大陆网站访客和内容运营人员，在保留 Odoo Website 原生国际平台
能力的前提下，增加 B站视频、国内社交分享以及 ICP/公安备案展示。B站离线解析由直接依赖的
`occ_base_bilibili` 提供；模块不依赖微信 JS-SDK、
二维码 CDN 或 B站接口，适合希望控制外部依赖和数据边界的网站。

## 功能与边界

### B站视频

- 在 Website Builder 和 Odoo HTML 富文本媒体选择器中接受 B站视频 URL、官方播放器 URL
  或官方 iframe 代码。
- 支持标准 BV 号、`av` 号和 `p`/`page` 分P；保存前统一规范化为 HTTPS 播放器地址，
  并固定关闭自动播放。
- 发布页把 B站视为需要可选 Cookie 同意的第三方内容。启用 Odoo Cookie Bar 并同时启用
  “阻止第三方跟踪服务”后，访客同意前 iframe 保持 `about:blank`，不会连接 B站；编辑器
  预览仍可供获授权的内容编辑人员核对。若关闭第三方阻断开关，则按 Odoo 原生策略立即加载。
- 模块把 `bilibili.com` 加入 Odoo 默认第三方域名观察列表；若管理员使用 Odoo 原生
  `#ignore_default` 指令完全接管该列表，则模块尊重该显式配置，管理员必须自行加入
  `bilibili.com` 才能保持 Cookie 阻断。
- 原有 YouTube、Vimeo、Dailymotion、Instagram 和 Facebook 等平台继续由 Odoo 处理。
- 不支持 `b23.tv` 短链、直播、番剧、课程、仅含 cid 的地址、背景视频、远程封面、自动
  播放、循环、起播时间或弹幕选项，也不包含 `website_sale` 商品媒体适配。

### 国内分享

- Website Builder 增加独立的“国内分享”区块，不替换原生国际分享区块。
- 固定提供微信、QQ好友、QQ空间、微博和复制链接；分享当前页面标题以及去掉 fragment 后
  的完整 URL，查询参数保持不变。
- URL 中出现疑似凭据参数时先向访客警告，但不会擅自删改参数。请勿把登录态、找回密码或
  其他私密链接放入公共页面。
- 微信内提示使用右上角菜单；桌面浏览器在本地生成二维码；其他移动浏览器复制链接并提示
  切换微信。不使用微信 JS-SDK 或系统 Web Share。
- 二维码由模块内置的 MIT 许可 `qrcode-generator 1.4.4` 在浏览器本地生成，不向二维码
  服务上传页面地址。第三方源码信息见模块的 `static/lib/qrcode-generator/NOTICE`。

### 网站备案

- 每个网站可分别配置 ICP 备案展示文本/链接和公安备案展示文本/链接。
- 初始链接分别指向工信部备案系统和全国互联网安全管理服务平台，也可以按网站改为其他
  HTTP(S) 地址；展示文本为空的项目不会输出。
- 备案条位于网站 footer 内且独立于 copyright 内容。若主题或编辑器隐藏整个 footer，备案
  条也会随之隐藏。

## 安装与配置

将 `addons_odoocc` 加入 `addons_path`，然后安装：

```bash
./odoo-bin -d <数据库名> \
    --addons-path=addons,addons_odoocc \
    -i occ_website_cn \
    --stop-after-init
```

安装后，以系统管理员身份打开“网站 → 配置 → 设置”，在当前网站的备案配置区域填写展示
文本并核对链接。Website Designer 可在页面编辑器的区块面板中拖入“国内分享”，并通过
视频媒体选择器粘贴受支持的 B站地址。

生产上线前至少完成以下检查：

- 同时启用并实测 Odoo Cookie Bar 与“阻止第三方跟踪服务”；未同意可选 Cookie 时从浏览器
  Network 确认没有 B站请求。
- 检查全部分享入口生成的页面标题和 URL，特别是页面查询参数是否适合公开传播。
- 用桌面端、微信内置浏览器和普通移动浏览器分别验收微信分支。
- 按实际主体填写备案号，并确认 footer 在当前主题、移动端和多网站环境中可见。

## 权限、安全与数据

- 本模块直接依赖 `website` 和 `occ_base_bilibili`，不创建新的业务持久模型或 ACL；
  备案数据存放在现有 `website` 记录中。服务端仅允许系统管理员写入四个备案字段，普通网站设计人员即使绕过
  设置视图直接调用 RPC 也不能修改。
- B站输入由 Python 和 JavaScript 严格解析，只生成固定的
  `https://player.bilibili.com/player.html` 地址，不传播用户提供的任意播放器参数。
  原模块内的 Python/JavaScript 导入路径保留兼容转发，新增集成应直接使用
  `occ_base_bilibili` 的公共接口。
- QQ、QQ空间和微博只在访客主动点击时打开各平台分享页；微信二维码只在本地生成。
- 分享链接会保留查询参数。敏感参数检测只是提醒机制，不能代替页面访问控制、一次性令牌
  设计或人工复核。
- 自动测试不会连接真实的 B站、微信、QQ 或微博。

## 升级与卸载

升级前备份数据库和附件目录，并先在生产副本执行：

```bash
./odoo-bin -d <测试数据库> \
    --addons-path=addons,addons_odoocc \
    -u occ_website_cn \
    --stop-after-init
```

1.0 是新模块，不包含历史数据迁移。卸载模块会删除 `website` 上由本模块定义的备案字段。
已经保存到页面或富文本中的国内分享区块、B站媒体容器或播放器地址可能继续留在视图内容
中，但对应编辑、交互、Cookie 阻断或 iframe 重建能力将停止；卸载前应先从页面中移除这些
内容，并在数据库副本中验证主题和页面回退结果。

## 自动测试与验收

服务端测试：

```bash
./odoo-bin -d <测试数据库> \
    --addons-path=addons,addons_odoocc \
    -i occ_website_cn \
    --test-enable \
    --test-tags=/occ_website_cn \
    --stop-after-init
```

Hoot 前端测试：

```bash
./odoo-bin -d <测试数据库> \
    --addons-path=addons,addons_odoocc \
    -u web,occ_website_cn \
    --test-enable \
    --test-tags='/web:WebSuite.test_unit_desktop[@occ_website_cn]' \
    --stop-after-init
```

配套的 `occ_website_cn_test` 仅用于非生产环境，提供管理员脱敏验收清单及三项能力的人工
验收入口。

## English summary

`occ_website_cn` extends Odoo 19 Website without replacing its international integrations. It
adds strict Bilibili video parsing for the website builder and HTML media editor, a separate
China-focused sharing snippet for WeChat, QQ, QZone, Weibo, and local link copying, plus
per-website ICP and public-security filing information.

When both Odoo's Cookie Bar and third-party tracking-domain blocking are enabled, published
Bilibili embeds are held behind optional-cookie consent. QR codes are generated locally with a
vendored MIT library, and no social-platform API credentials are required. Version 1.0 deliberately
excludes shortened Bilibili links, live/series content, background and product videos, WeChat
JS-SDK integration, social-account follow blocks, and mainland map providers.

## 许可证与联系

- 作者：Odoo老赵
- 官网：<https://odoocc.com>
- 支持邮箱：<156277468@qq.com>
- 许可证：[GNU Affero General Public License v3.0](../LICENSE)
