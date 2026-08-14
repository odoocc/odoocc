# OdooCC Markdown 编辑器验收（`occ_markdown_test`）

> 本模块仅用于开发、演示和验收，不建议在生产环境安装。

本模块提供管理员专用的 Markdown 综合样例模型和脱敏验收清单，直接验证
`occ_markdown` 的公开字段组件、服务端转换 API、图片/B站能力和 HTML `/Markdown`
Powerbox，不复制生产转换器。

## 安装与入口

```bash
python -m pip install -r addons_odoocc/requirements.txt
./odoo-bin -d <非生产数据库> --addons-path=addons,addons_odoocc \
    -i occ_markdown_test --stop-after-init
```

系统管理员从“设置 → OdooCC Markdown 编辑器验收 → Markdown 编辑工作台”进入固定示例：

- 在默认单窗口所见即所得模式编辑标题、业务流程表格、Mermaid 流程图、代码、图片和B站标记；
- 切换 Markdown 源码与服务端效果，确认内容不丢失且最终效果同源；
- 勾选 Emoji 清理和生成目录，点击“生成服务端 HTML”；
- 在已保存记录中粘贴本地截图、网络图片并复用 Odoo 媒体库；
- 从飞书/网页粘贴 HTML 表格、从 Excel 粘贴制表符表格，并粘贴 `flowchart TD` 流程定义；
- 在“HTML /Markdown 验收”页的富文本字段输入 `/Markdown` 并插入内容；
- 用未保存记录验证本地图片按钮禁用和中文提示。

综合示例及通用清单使用 `noupdate="1"`：模块升级不会覆盖人工编辑内容、状态或脱敏备注。

## 权限、安全、升级与卸载

演示模型、清单、动作和菜单仅授予 `base.group_system`。普通内部、门户和公共用户无 ACL。
演示内容不得上传生产截图、客户数据、密钥或个人信息；B站写作卡片不发起外部请求，最终
播放器的真实加载行为只应在隔离验收环境按站点 Cookie 策略测试。

升级前备份非生产数据库并执行 `-u occ_markdown_test`。卸载会删除本模块固定示例、生成 HTML
和人工清单；上传到示例记录的附件应按 Odoo 卸载/附件策略另行核对。

## 自动测试

```bash
./odoo-bin -d <测试数据库> --addons-path=addons,addons_odoocc \
    -i occ_markdown_test --test-enable --test-tags=/occ_markdown_test \
    --stop-after-init
```

正式模块的 Hoot 标签为 `occ_markdown`，覆盖默认单窗、三模式、服务端防抖、未保存保护、
图片、B站卡片和 Powerbox 注册。Manifest 的 `odoocc_demo` v1 数据注册到
`developer_tools`，但本模块不依赖部署侧聚合模块。

## English summary

`occ_markdown_test` is a non-production, administrator-only acceptance workspace for the
production Markdown widget, conversion API, images, Bilibili markers, and global HTML-editor
command. Its fixed sample and checklist preserve user-maintained results on upgrades and contain
no production credentials or external-platform shortcuts.

## 许可证与联系

- 作者：Odoo老赵
- 官网：<https://odoocc.com>
- 支持邮箱：<156277468@qq.com>
- 许可证：[GNU Affero General Public License v3.0](../LICENSE)
