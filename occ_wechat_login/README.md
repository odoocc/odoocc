# OdooCC 微信扫码登录（`occ_wechat_login`）

`occ_wechat_login` 为 Odoo 中文社区（[odoocc.com](https://odoocc.com)）提供微信扫码登录、社区用户名、邮箱验证及密码登录能力。

## 功能

- 桌面登录页左侧内嵌微信官方 QRConnect 二维码，右侧保留 Odoo 邮箱/密码表单；移动端纵向堆叠。
- 以微信 `unionid` 唯一绑定 Odoo 用户，`openid` 仅作为当前网站应用的辅助标识。
- 首次扫码可按系统设置创建门户用户（`base.group_portal`）或内部用户（`base.group_user`）；邮箱验证不会改变所选用户类型。
- 验证成功后将规范化邮箱同时设为用户正式邮箱和 Odoo 登录名；用户仍可继续使用微信扫码登录。
- 首次完成验证时生成随机初始密码，并通过独立凭据邮件发送到已验证邮箱。
- 对微信 state、一次性登录 grant、邮箱验证链接、发送频率及敏感日志进行安全控制。
- 邮箱绑定、链接确认及验证结果页面固定使用简体中文；不会改变用户在其他 Odoo 页面中的个人语言偏好。
- 首次扫码创建账号时，若微信昵称符合社区用户名规则且未被占用，邮箱绑定页会将其作为可编辑的默认用户名。
- 模块会启用简体中文；新建的微信用户默认使用 `zh_CN`，之后用户自行修改的语言偏好不会被再次扫码覆盖。
- 社区用户名确认或再次修改时，会同步更新 Odoo 显示名称、联系人名称和电子邮件签名。

## 账号与验证规则

### 邮箱登录名

- 验证前，微信新用户使用由 `unionid` 摘要生成的内部技术登录名，该值不会展示给用户。
- 验证成功后，邮箱会被规范化并同时写入 `res.users.login`、正式邮箱及 `occ_verified_email`；之后可使用“邮箱 + 密码”登录。
- 邮箱必须在全部启用和停用用户中保持可用：模块同时检查其他用户的正式邮箱和登录名，不自动合并账号。
- 管理员或用户修改已验证邮箱时，新地址只会进入待验证状态，正式邮箱会被清空并要求重新验证；已有的门户/内部用户组保持不变。重新验证后登录名更新为新邮箱，原密码保持不变。

### 社区用户名

- 用户名会先做 Unicode NFKC 规范化并去除首尾空白，长度必须为 2–32 个字符。
- 可使用 Unicode 字母和数字；下划线 `_` 与连字符 `-` 只能出现在中间，首尾必须是字母或数字。
- 唯一性按“NFKC 规范化后再 casefold”的值判断，因此大小写及全角/兼容字符不能绕过重复检查；数据库唯一约束会再次阻止并发抢占。
- 唯一性覆盖启用和停用用户。社区用户名既保存在独立社区身份字段中，也作为 Odoo 用户显示名称；登录凭据仍是已验证邮箱。

### 初始密码与凭据邮件

- 仅当账号仍使用首次扫码生成的技术登录名时，验证流程才生成一次初始密码；后续更换邮箱或重新验证不会重置既有密码。
- 初始密码长度为 16，使用加密安全随机源生成，至少包含一个小写字母、一个大写字母、一个数字和一个 `!@#$%` 符号，并排除容易混淆的部分字符。
- `res.users` 的业务密码字段只保存哈希，验证结果页和应用日志不会输出明文初始密码。为发送 `occ_wechat_login.mail_template_initial_credentials`，明文仍会短暂进入邮件渲染和发送链路，并可能由数据库事务/WAL、SMTP 中继或收件箱承载；邮件设置 `auto_delete` 只会减少发送后的 Odoo 业务记录留存，不能消除邮件传输明文凭据的固有风险。
- 用户收到凭据邮件后应尽快使用“邮箱 + 初始密码”登录并修改密码；也可以继续使用微信扫码登录。
- 新账号验证与首次凭据邮件发送处于同一事务保护范围内；邮件发送失败时不会留下已激活但用户未收到密码的半完成状态。

## 安装、升级与微信配置

1. 将本仓库目录 `addons_odoocc` 加入 Odoo 的 `addons_path`，更新应用列表并安装“OdooCC 微信扫码登录”；模块不依赖额外的 `occ` 基础模块。
2. 将系统参数 `web.base.url` 设置为部署实例真实、可从公网访问的 HTTPS 根地址，并将 `web.base.url.freeze` 设置为 `True`。
3. 在微信开放平台创建并审核“网站应用”，将授权回调域配置为该部署实例的域名。
4. 在“设置 → 常规设置 → 集成 → OdooCC 微信登录”选择“新建用户类型”，填写 AppID 和 AppSecret，并核对回调地址：

   ```text
   https://<你的 Odoo 域名>/occ/wechat/callback
   ```

5. 完成下面的 126 SMTP 配置并测试发信，最后再启用微信登录。

模块默认关闭；只有启用且 AppID、AppSecret 均已配置时，登录页才显示微信入口。“新建用户类型”缺省为“内部用户”，也可选择“门户用户”：

- **门户用户**：首次扫码授予 `base.group_portal`，邮箱验证后仍为门户用户。适合只需要网站/门户访问、不希望开放 Odoo 后台的部署。
- **内部用户**：首次扫码授予 `base.group_user`，邮箱验证后仍为内部用户。此模式与旧版本行为兼容。
- 缺失或无法识别的配置值会回退为“内部用户”。邮箱验证只确认邮箱、社区用户名和登录凭据，不添加、移除或切换门户/内部用户组。

命令行安装或升级示例：

```bash
./odoo-bin -d <数据库名> --addons-path=addons,addons_odoocc \
    -i occ_wechat_login --stop-after-init
./odoo-bin -d <数据库名> --addons-path=addons,addons_odoocc \
    -u occ_wechat_login --stop-after-init
```

升级前应备份数据库，并先在测试环境验证扫码、邮件和原有账号登录。卸载会移除模块定义的
视图、模板和字段；如需保留微信身份绑定及验证状态，应先按部署方的数据保留策略导出相关
用户数据，不要直接在生产环境试卸载。

版本 `19.0.4.0.5` 会将仍使用默认名称的两个邮件模板从旧的 `OCC:` 前缀迁移为 `OdooCC:`；
已经由部署方自定义过名称的模板不会被覆盖。

## 126 发件服务器配置

验证邮件和首次凭据邮件都明确使用：

```text
Odoo Chinese Community <odoocc@126.com>
```

在 126 邮箱后台开启 SMTP 服务并生成“客户端授权密码”，不要在 Odoo 中填写网页版登录密码。然后在“设置 → 技术 → 邮件 → 发件服务器”创建服务器：

| Odoo 字段 | 建议值 |
| --- | --- |
| SMTP Server | `smtp.126.com` |
| SMTP Port | `465` |
| Connection Encryption | `SSL/TLS, encryption and validation` |
| Authenticate with | `Username` |
| Username | `odoocc@126.com` |
| Password | 126 客户端授权密码 |
| FROM Filtering | `odoocc@126.com` |

- 保存后先执行“测试连接”，再从真实验证流程检查收件箱和垃圾邮件目录。
- `FROM Filtering` 必须匹配模板和控制器强制使用的 `odoocc@126.com`，否则 Odoo 可能选择其他 SMTP 服务器或重写 `From`。
- 不要直接改成 `@odoocc.com` 发件人，除非已经部署并授权可代表该域发信的 SMTP 服务，同时正确配置 SPF、DKIM 和 DMARC。
- 生产日志不要启用长期 SMTP DEBUG；其中可能包含邮件地址、服务器响应或其他敏感信息。

## 登录与验证流程

1. 用户扫描登录页左侧的微信官方二维码，也可使用备用链接打开微信登录页。
2. 回调取得 `openid`、`unionid` 和昵称；已有 `unionid` 复用原账号，未知 `unionid` 按“新建用户类型”配置创建门户用户或内部用户。
3. 未验证用户进入 `/occ/wechat/email`，提交唯一社区用户名和邮箱。待验证邮箱不会提前进入通知或密码重置流程。
4. 验证邮件链接先显示社区用户名和掩码邮箱，用户通过带 CSRF 的 POST 主动确认。
5. 确认成功后，社区用户名同时成为 Odoo 用户显示名称；邮箱成为正式邮箱及登录名，用户继续保持首次创建时选择的门户或内部用户类型。
6. 首次验证的微信新用户会收到包含登录邮箱、社区用户名和随机初始密码的第二封邮件。

## 安全与部署

- 生产环境必须使用 HTTPS，并在反向代理部署中正确启用 `proxy_mode`、Secure Cookie 和 `SameSite=Lax`。
- 内嵌二维码 URL 由服务器生成，只包含公开 AppID、回调地址、授权范围及与 session 绑定的一次性 `state`，绝不向浏览器输出 AppSecret。
- 二维码使用 `login_type=jssdk` 和 `self_redirect=false`，授权完成后由顶层页面进入回调，从而携带 `SameSite=Lax` session cookie。
- 如部署层设置了 Content-Security-Policy，至少允许 `frame-src https://open.weixin.qq.com`；否则内嵌二维码会被阻止，但备用微信登录链接仍可使用。
- 模块会在 Odoo 进程内脱敏微信回调、验证链接及微信 API 请求中的 `secret`、`code` 和 token；反向代理、负载均衡、出口代理、APM 与异常采集系统也不得记录这些原始 URL。
- 选择“内部用户”时，首次扫码后账号会立即获得 Odoo 内部用户的基础访问权限；邮箱引导页只是 Web UI 门禁，不能替代 ACL 和记录规则。若不应开放后台权限，请选择“门户用户”。
- 邮箱验证不会改变门户/内部用户组。需要进一步限制业务功能时，应由部署方使用自己的用户组、ACL 和记录规则；模块不依赖额外的社区用户组。

## 自动化与上线检查

- 微信 state 的会话绑定、10 分钟过期、一次消费、最多 5 个并行 state、站外重定向拦截。
- 微信 API 异常、UnionID 缺失或不一致、停用用户、并发首次登录和一次性 session grant。
- 邮箱及登录名重复、社区用户名 NFKC/casefold 唯一性、并发确认、验证链接篡改/过期/重放。
- 验证邮件 60 秒冷却及每小时 5 封限制；首次密码复杂度、哈希保存、邮件失败回滚和重复验证不重置密码。
- 门户/内部两种新用户配置、邮箱验证前后用户类型保持不变、未验证用户访问 `/odoo` 的引导，以及邮箱变更后的重新验证。
- 上线前使用已审核的网站应用和真实 126 邮箱完成真机扫码、邮件送达、邮箱密码登录、改密、退出及再次登录测试。

服务端自动测试不会连接真实微信开放平台，而是验证 HTTP、安全、模型和日志脱敏契约：

```bash
./odoo-bin -d <测试数据库> --addons-path=addons,addons_odoocc \
    -i occ_wechat_login --test-enable --stop-after-init \
    --test-tags=/occ_wechat_login
```

测试数据库必须与生产数据库隔离。仓库中的 `occ_wechat_login_test` 提供可见的人工验收清单
和配置快捷入口，适合开发、培训及上线验收，不建议安装到生产数据库。该验收模块不会保存
AppID、AppSecret 或 UnionID，也不会提供模拟登录或绕过微信认证的后门。

## 许可证与联系

- 许可证：[GNU Affero General Public License v3.0](../LICENSE)
- 官网：<https://odoocc.com>
- 作者：Odoo老赵
- 支持邮箱：<156277468@qq.com>

## English summary

`occ_wechat_login` is an AGPL-3 authentication extension for Odoo 19. It embeds
WeChat QRConnect on the login page, binds accounts by UnionID, verifies a unique
community username and email login, and preserves the configured portal or internal
user type. Production deployment requires HTTPS, an approved WeChat Open Platform
website application, correctly configured outbound email, and a full real-device
acceptance test. The companion `occ_wechat_login_test` module contains only a manual
acceptance checklist; it never bypasses real WeChat authentication.
