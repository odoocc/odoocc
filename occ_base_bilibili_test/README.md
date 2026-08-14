# OdooCC B站基础能力验收（`occ_base_bilibili_test`）

> 本模块仅用于开发、演示和验收，不建议在生产环境安装。

本模块直接调用 `occ_base_bilibili` 的公开 Python 接口，提供管理员专用的交互式离线解析器
和脱敏验收清单，不复制解析逻辑、不加载真实视频、不请求任何外部平台。

## 安装与使用

```bash
./odoo-bin -d <非生产数据库> --addons-path=addons,addons_odoocc \
    -i occ_base_bilibili_test --stop-after-init
```

系统管理员从“设置 → OdooCC B站基础能力验收 → B站视频解析器”进入：

1. 输入视频页、移动端地址、官方播放器地址或 av 号；若要输入单独 BV 号，勾选对应选项。
2. 点击“离线解析”。
3. 核对输入声明、规范视频号、分P和固定播放器地址。
4. 用短链、直播、恶意域名、端口或未知参数验证“无效”结果，页面始终不加载 iframe。

“验收清单”用于记录待验收、通过、失败、阻塞和脱敏备注。固定清单采用
`noupdate="1"`，升级时保留管理员填写的状态与备注。

## 权限、安全、升级与卸载

解析器、清单、动作和菜单仅向 `base.group_system` 开放；普通内部、门户和公共用户没有模型
ACL。不要在备注中保存密码、令牌、生产 URL、客户数据或完整个人标识。模块没有认证后门，
也不会为了验收伪造外部成功结果。

升级前备份非生产数据库并执行 `-u occ_base_bilibili_test`。卸载会删除本模块的演示记录和
清单，不影响正式模块；若已填写人工结论，应先导出脱敏结果。

## 自动测试

```bash
./odoo-bin -d <测试数据库> --addons-path=addons,addons_odoocc \
    -i occ_base_bilibili_test --test-enable \
    --test-tags=/occ_base_bilibili_test --stop-after-init
```

测试覆盖公开解析接口、样例流程、菜单、管理员 ACL 和普通内部用户越权拒绝。Manifest 的
`odoocc_demo` v1 数据把本模块注册到 `developer_tools`，但不依赖部署侧聚合模块。

## English summary

`occ_base_bilibili_test` is a non-production, administrator-only acceptance module with an
interactive offline parser and sanitized checklist. It invokes the production module's public
API, never loads a real video or contacts Bilibili, and remains independently installable.

## 许可证与联系

- 作者：Odoo老赵
- 官网：<https://odoocc.com>
- 支持邮箱：<156277468@qq.com>
- 许可证：[GNU Affero General Public License v3.0](../LICENSE)
