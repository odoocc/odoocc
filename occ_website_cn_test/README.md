# OdooCC 网站中国生态增强验收（`occ_website_cn_test`）

> 本模块仅用于开发、演示和验收，不建议在生产环境安装。

`occ_website_cn_test` 是正式模块 `occ_website_cn` 的可安装验收辅助模块。它提供系统管理员可
维护的业务化清单，用于验收B站视频、国内分享、ICP/公安备案以及相应隐私与安全边界；它
不复制正式实现，不提供伪造成功路径，也不保存平台凭据或客户数据。

## 验收范围与功能边界

- B站：Website Builder、HTML 富文本、合法地址/官方 iframe、分P、保存重载、非法输入拒绝、
  Odoo 原生视频回归和可选 Cookie 零外联。
- 国内分享：微信、QQ好友、QQ空间、微博、复制链接，三类微信环境、敏感 URL 警告、复制
  回退、键盘与焦点。
- 网站备案：多网站隔离、默认官网链接、严格 HTTP(S) 校验、文本/链接组合、footer 模板、
  Copyright 与整个 footer 的显隐。
- 验收模块只记录“待验收、通过、失败、阻塞”和脱敏备注，不调用真实外部平台、不跟随B站
  短链、不使用微信 JS-SDK，也不替代正式模块的服务端或 Hoot 自动测试。

商品媒体B站适配、高德地图和公众号关注区块不属于 1.0，不应在本清单中标记为已支持。

## 安装与入口

在非生产数据库安装验收模块会通过依赖自动安装正式模块：

```bash
./odoo-bin -d <非生产数据库> \
    --addons-path=addons,addons_odoocc \
    -i occ_website_cn_test \
    --stop-after-init
```

以系统管理员进入“设置 → 网站中国生态增强验收”。菜单提供四个入口：

- “验收清单”：记录业务验收状态和脱敏结论；
- “验收演示页”：打开固定、脱敏、不可索引的公开页面，供无痕浏览器验证 Cookie 零外联、
  国内分享和当前网站备案；页面内容不含平台凭据或客户数据；
- “前往网站设置”：打开 Website 设置，配置当前网站的备案信息和 Cookie 策略；
- “打开网站”：打开当前域名首页，进入 Website Builder 或验证发布页。

普通内部用户、门户用户和公共用户没有清单模型访问权。正式模块不依赖本模块；本模块
`application=False`、`auto_install=False`，不会自动进入生产依赖链。

验收演示页为验证真实“发布页同意前零外联”而允许公共 GET 访问，但 `sitemap=False`，且入口
菜单仍仅系统管理员可见。它只包含固定 BV 标识、国内分享区块和备案说明；不要在公开演示页
URL 中添加敏感查询参数。完成验收后应卸载本模块。

## 验收数据、升级与脱敏

固定验收清单使用 `noupdate="1"` 加载。模块升级不会重置管理员已经填写的状态和备注；管理员
也可以创建部署专属的补充检查项。卸载本验收模块会删除清单模型及其记录，不影响正式模块的
网站配置和页面内容。

备注只能记录类似“桌面二维码正常”“测试页未出现备案条”“Safari 手工复制回退可用”这样的
脱敏结论。不要填写或粘贴：

- 密码、Token、Cookie、授权码或验证链接；
- 含敏感查询参数的完整 URL；
- 客户名称、联系方式、订单或其他生产数据；
- 生产环境截图、浏览器存储内容或完整 Network 请求正文。

验收B站和国内分享时使用经授权、无敏感参数的公开测试页面。自动测试全部使用本地输入或
mock；真实平台链路只在隔离环境人工验收。

## 统一演示入口协议

本模块可以在只配置 `addons_odoocc` 的环境独立安装，不依赖、导入或引用
`occ_odoocc_demo`。Manifest 中的 `odoocc_demo` 是纯数据协议 v1，供可选聚合环境发现菜单：

- 分类：`foundation_localization`（基础与本地化）；
- 可重组菜单：`occ_website_cn_test.menu_acceptance_root`；
- 默认入口：`occ_website_cn_test.menu_acceptance_check`。

聚合器只能重组菜单，不得扩大 `base.group_system` 菜单限制或模型 ACL。

## 自动测试

```bash
./odoo-bin -d <测试数据库> \
    --addons-path=addons,addons_odoocc \
    -i occ_website_cn_test \
    --test-enable \
    --test-tags=/occ_website_cn_test \
    --stop-after-init
```

测试覆盖清单分类与 `noupdate` 语义、四种状态、系统管理员 CRUD、普通内部用户越权拒绝、
菜单/动作及设置和网站快捷入口。它不会把人工状态重置为“待验收”，也不会请求B站、微信、
QQ、微博或其他外部平台。

## English summary

`occ_website_cn_test` is an independently installable acceptance companion for `occ_website_cn`.
It provides administrator-only sanitized checklists and a fixed public, non-sitemap page for
testing published-page cookie consent, Bilibili media, China-focused sharing, and per-website
ICP/public-security filing. It stores no credentials or customer data, makes no automated
real-platform requests, and must not be installed in production. Fixed checklist records are
`noupdate`, so upgrades preserve manual statuses and notes.

## 许可证与联系

- 作者：Odoo老赵
- 官网：<https://odoocc.com>
- 支持邮箱：<156277468@qq.com>
- 许可证：[GNU Affero General Public License v3.0](../LICENSE)
