# OdooCC：面向 Odoo 19 的中文社区扩展

[![CI](https://github.com/odoocc/odoocc/actions/workflows/ci.yml/badge.svg)](https://github.com/odoocc/odoocc/actions/workflows/ci.yml)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)

OdooCC 是一组面向 **Odoo 19.0** 的开源扩展，当前聚焦层级列表（TreeGrid）、微信扫码
登录和网站中国生态增强。正式模块可用于经过评估的生产部署；同仓库的 `*_test` 模块只用于
开发、演示、培训和验收，不应安装到生产数据库。

> **以 Odoo 为根，以 AI 为光，让中小企业拥有自己的智能经营系统。**

## 模块一览

| 模块 | 版本 | 定位 | 直接依赖 | 用途与安装建议 |
| --- | --- | --- | --- | --- |
| `occ_treegrid` | `19.0.1.0.1` | 正式模块 | `web` | 为显式接入的 Odoo 列表视图提供层级展开、祖先上下文和同级拖拽排序，可用于生产 |
| `occ_treegrid_test` | `19.0.1.0.1` | 演示/验收模块 | `occ_treegrid` | 提供示例模型、样例数据、菜单和回归测试，仅用于非生产环境 |
| `occ_wechat_login` | `19.0.4.0.5` | 正式模块 | `web`、`mail`、`base_setup` | 提供微信 QRConnect 扫码登录、UnionID 账号绑定、社区用户名与邮箱验证 |
| `occ_wechat_login_test` | `19.0.1.0.1` | 验收辅助模块 | `occ_wechat_login` | 提供管理员人工验收清单，不模拟认证、不保存微信身份或凭据，仅用于非生产环境 |
| `occ_website_cn` | `19.0.1.0.0` | 正式模块 | `website` | 增加B站视频、国内分享和多网站 ICP/公安备案，可用于经过验收的生产网站 |
| `occ_website_cn_test` | `19.0.1.0.0` | 验收辅助模块 | `occ_website_cn` | 提供三项网站增强能力的管理员脱敏验收清单，仅用于非生产环境 |

详细功能、配置契约与安全边界请阅读：

- [`occ_treegrid/README.md`](occ_treegrid/README.md)
- [`occ_treegrid_test/README.md`](occ_treegrid_test/README.md)
- [`occ_wechat_login/README.md`](occ_wechat_login/README.md)
- [`occ_wechat_login_test/README.md`](occ_wechat_login_test/README.md)
- [`occ_website_cn/README.md`](occ_website_cn/README.md)
- [`occ_website_cn_test/README.md`](occ_website_cn_test/README.md)

## 兼容性

- Odoo：`19.0`（Community Edition 为主要验证环境）
- 数据库：PostgreSQL
- 许可证：GNU Affero General Public License v3.0

仓库不承诺兼容 Odoo 18 或更早版本。若用于 Odoo Enterprise，请先在隔离数据库中验证与
企业版模块、自定义主题及其他前端扩展的兼容性。

## 安装

除非特别说明，本文命令都在 Odoo 源码根目录执行，并假定本仓库目录名为
`addons_odoocc`：

```bash
git clone https://github.com/odoocc/odoocc.git addons_odoocc

./odoo-bin -d <数据库名> \
    --addons-path=addons,addons_odoocc \
    -i occ_treegrid,occ_wechat_login,occ_website_cn \
    --stop-after-init
```

也可以把本仓库放到其他目录，但必须将该目录加入 `addons_path`。随后更新应用列表，并安装
所需正式模块。`occ_treegrid` 本身不提供业务菜单，需要业务模型和列表视图显式接入；
`occ_wechat_login` 默认关闭，完成微信开放平台、基础 URL、邮件服务器和用户类型配置后再启用；
`occ_website_cn` 上线前应配置备案信息，并验收可选 Cookie 与国内分享在目标浏览器中的行为。

开发或验收环境如需示例数据，可以额外安装测试模块：

```bash
./odoo-bin -d <非生产数据库> \
    --addons-path=addons,addons_odoocc \
    -i occ_treegrid_test,occ_wechat_login_test,occ_website_cn_test \
    --stop-after-init
```

> 所有 `_test` 模块均不属于生产依赖。不要在生产数据库安装，也不要
> 将其中的验收记录或样例数据复制到生产环境。

## 升级

升级前请备份数据库与附件目录，并先在生产数据库副本中演练：

```bash
git pull --ff-only

./odoo-bin -d <数据库名> \
    --addons-path=addons,addons_odoocc \
    -u occ_treegrid,occ_wechat_login,occ_website_cn \
    --stop-after-init
```

若业务模块依赖 `occ_treegrid`，应在同一次验证中升级并回归这些业务模块。升级
`occ_wechat_login` 后，应复核登录页、微信回调域、邮件投递、既有账号绑定与停用用户行为；
升级 `occ_website_cn` 后，应复核B站媒体、可选 Cookie、分享入口和所有网站的备案 footer。

## 测试

以下命令与仓库 CI 的核心路径一致。请使用独立测试数据库，不要对生产库运行测试模块或
`--test-enable`。

服务端测试：

```bash
OCC_MODULES="$(python3 addons_odoocc/tools/check_modules.py list --format csv)"
SERVER_TEST_TAGS="$(python3 addons_odoocc/tools/check_modules.py list --format test-tags)"

./odoo-bin -d <测试数据库> \
    --addons-path=addons,addons_odoocc \
    -i "$OCC_MODULES" \
    --without-demo=true \
    --stop-after-init

./odoo-bin -d <测试数据库> \
    --addons-path=addons,addons_odoocc \
    -u "$OCC_MODULES" \
    --test-enable \
    --test-tags="$SERVER_TEST_TAGS" \
    --stop-after-init
```

TreeGrid Hoot 前端测试：

```bash
./odoo-bin -d <测试数据库> \
    --addons-path=addons,addons_odoocc \
    -u web,occ_treegrid \
    --test-enable --stop-after-init \
    --test-tags='/web:WebSuite.test_unit_desktop[@occ_treegrid]'
```

Hoot 命令需要系统中存在可用的 Google Chrome 或 Chromium。完整依赖、PostgreSQL 参数和
自动化步骤见 [`.github/workflows/ci.yml`](.github/workflows/ci.yml)。

## 开发规范与新模块

仓库级开发约定见 [`AGENTS.md`](AGENTS.md)，完整的 Odoo 19 模块规范、权限要求、测试矩阵和
发布清单见 [`docs/ODOO_MODULE_STANDARD.md`](docs/ODOO_MODULE_STANDARD.md)。

新模块默认成对创建“正式模块 + 可安装 `_test` 验收模块”。先预览：

```bash
python3 addons_odoocc/tools/scaffold_module.py create occ_example \
    --title "示例能力" \
    --summary "面向用户的中文摘要" \
    --summary-en "A concise English summary." \
    --description "说明要解决的问题、目标用户和明确边界。" \
    --demo-category developer_tools \
    --demo-keyword "示例能力" \
    --depends base \
    --dry-run
```

确认后去掉 `--dry-run`。脚手架固定 OdooCC 作者、邮箱、官网、许可证与初始版本，不覆盖已有
目录，也不修改 Git 索引。生成后仍需实现真实业务能力并更新本页模块表。

本地规范检查：

```bash
python3 addons_odoocc/tools/check_modules.py check
python3 -m unittest discover \
    -s addons_odoocc/tools/tests \
    -t addons_odoocc \
    -p "test_*.py" \
    -v
```

CI 使用同一工具自动发现根目录中的模块、服务端测试标签和 Hoot 模块；以后新增模块无需维护
CI 内的硬编码模块列表。

每个 `_test` Manifest 还包含 `odoocc_demo` v1 纯数据注册信息，声明七类分类、菜单、
默认入口、排序和搜索词。该协议不会引入部署依赖；社区用户仍可在只有
`addons_odoocc` 的环境中独立安装任意 `_test` 模块。完整协议见
[`docs/ODOO_MODULE_STANDARD.md`](docs/ODOO_MODULE_STANDARD.md#统一演示注册协议-v1)。

## 在线演示

- Odoo 19 演示环境：<https://odoocc.com/odoo/odoocc-demo>
- 需要微信扫码登录


在 OdooCC 服务器上，部署侧的 `occ_odoocc_demo` 可按上述 Manifest 协议统一组织已安装
`_test` 的菜单。聚合只改变导航层级，不改变模块依赖、模型 ACL 和菜单用户组；
因此管理员专用验收入口不会自动向公开演示账号开放。

这是多人共享的公开演示账号，环境中的数据可能被其他访问者修改，也可能随时重置；稳定性、
可用性和保留期限均不等同于生产服务。请遵守以下安全要求：

- 不要录入真实客户、订单、手机号、邮箱、微信身份或其他个人信息；
- 不要上传合同、密钥、令牌、数据库备份或任何机密文件；
- 不要把公共演示密码用于其他网站，也不要尝试修改公共账号的密码或权限；
- 不要在演示环境绑定生产微信应用、真实 SMTP 凭据或生产账号；
- 演示地址或公开凭据如有变化，以本 README 的最新说明为准。

## 参与贡献

欢迎通过 GitHub Issue 报告可复现的问题或提出功能建议。提交代码前请阅读
[`CONTRIBUTING.md`](CONTRIBUTING.md)。安全漏洞不要公开提交 Issue，请按
[`SECURITY.md`](SECURITY.md) 私下报告。

## 联系方式

- 官网：<https://odoocc.com>
- GitHub Issues：<https://github.com/odoocc/odoocc/issues>
- 支持邮箱：<156277468@qq.com>
- 作者：Odoo老赵

### 微信社区

<table>
  <thead>
    <tr>
      <th align="center" width="50%">微信公众号</th>
      <th align="center" width="50%">微信交流群</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td align="center">
        <a href="docs/assets/gongzhonghao.png">
          <img src="docs/assets/gongzhonghao.png" alt="和光同源 Odoo 中文社区公众号二维码" width="170">
        </a>
      </td>
      <td align="center">
        <a href="docs/assets/weixinqun.png">
          <img src="docs/assets/weixinqun.png" alt="OdooCC 微信交流群二维码" width="170">
        </a>
      </td>
    </tr>
    <tr>
      <td align="center">获取 Odoo 中文教程、模块解读与项目动态</td>
      <td align="center">交流 Odoo 开发、实施经验与中小企业数字化实践</td>
    </tr>
  </tbody>
</table>

> 点击二维码可以查看原图。交流群二维码可能定期更新；如无法加入，请通过支持邮箱联系维护者。

## English summary

OdooCC provides AGPL-3.0 extensions for Odoo 19. `occ_treegrid` adds an explicitly
configured hierarchical list view with ancestor-aware results and safe sibling
resequencing. `occ_wechat_login` implements WeChat QRConnect login, UnionID account
binding, community usernames, and email verification. `occ_website_cn` adds Bilibili
media, China-focused sharing, and per-website ICP/public-security filing information.

The companion `*_test` modules are for development, demonstrations, and acceptance
testing only; do not install them in a production database. See the module READMEs for
configuration details, and use private email reporting for security vulnerabilities as
described in [`SECURITY.md`](SECURITY.md).

## 许可证

本项目依据 [GNU AGPL v3.0](LICENSE) 发布。
