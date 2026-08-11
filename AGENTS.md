# OdooCC repository instructions

本文件适用于整个 `addons_odoocc` 仓库。Codex 或其他自动化代理在修改本仓库前，必须先阅读
[`docs/ODOO_MODULE_STANDARD.md`](docs/ODOO_MODULE_STANDARD.md)，并把其中的规范视为完成
条件，而不是参考建议。本文件中的工具命令在 `addons_odoocc` 仓库根目录执行。

## 开始工作前

- 先执行 `git status --short`，识别并保留用户已有的修改、删除、暂存状态和未跟踪文件。
- 不恢复、重置、覆盖或顺手整理与当前任务无关的内容。
- 除非用户明确要求，不提交、不推送、不修改 Git 索引。
- 使用 `python3 tools/check_modules.py list --format lines` 获取实际模块列表。CI 和全仓安装、
  测试清单必须由该工具自动发现，不得维护另一份硬编码列表；面向用户的生产安装子集、单模块
  升级和定向测试示例可以显式写出模块名，以免误装 `_test` 模块或模糊示例范围。

## 新模块

- 正式模块技术名必须匹配 `occ_<业务名>`，仅使用小写字母、数字和下划线。
- 必须同时创建同名验收模块 `<正式模块名>_test`；正式模块不得依赖或导入 `_test` 模块。
- 首选仓库脚手架，禁止直接使用未经适配的 Odoo 默认 scaffold：

  ```bash
  python3 tools/scaffold_module.py create occ_example \
      --title "示例能力" \
      --summary "面向用户的中文摘要" \
      --summary-en "A concise English summary." \
      --description "说明要解决的问题、目标用户和明确边界。" \
      --demo-category developer_tools \
      --demo-keyword "示例能力" \
      --depends base
  ```

- 脚手架不得覆盖现有目录。发生冲突时，应检查差异并由用户决定，不得使用删除目录或
  `--force` 绕过保护。
- 新模块生成后，必须把真实功能、权限、测试和文档补充完整；不得把脚手架中的通用验收项
  当作业务测试的替代品。

## 固定元数据

所有模块 Manifest 必须使用：

- Odoo：`19.0`
- 作者：`Odoo老赵`
- 支持邮箱：`156277468@qq.com`
- 官网：`https://odoocc.com`
- 许可证：`AGPL-3`
- 版本格式：`19.0.x.y.z`
- `installable=True`

`application` 必须显式填写。`_test` 模块还必须设置
`application=False`、`auto_install=False`，并直接依赖对应正式模块。

## 统一演示注册

- 每个 `_test` Manifest 必须声明 `odoocc_demo` v1 纯数据协议，包含
  `schema_version`、`category`、`sequence`、`menu_xmlid` 和 `entry_menu_xmlid`；
  可选的 `keywords` 用于补充目录搜索词。
- `_test` 模块必须在不存在 `occ_odoocc_demo` 的 addons path 中仍可独立安装；
  Manifest 不得依赖或引用该部署模块的资源，Python/JavaScript 不得导入它，XML 不得引用
  它的 XML ID。
- `menu_xmlid` 指向聚合环境可重组的模块菜单；`entry_menu_xmlid` 指向其本身
  或后代中带 action 的默认入口。两者必须由当前 `_test` 的 Manifest `data`
  创建。
- 聚合模块只能重组菜单，不得通过演示协议扩大 `_test` 的用户组、ACL 或记录规则。

## 实现边界

- 正式模块只承载可生产部署的能力；固定演示数据、人工验收记录和演示菜单放在 `_test`
  模块。
- 新持久模型必须明确访问策略：面向用户的模型提供最小 ACL，需要更细粒度隔离时同时设计
  记录规则；只允许受控服务或定时任务访问的内部模型可以有意不授予 ACL，但必须在 README
  说明并测试普通用户无法直接访问。继承现有模型、`AbstractModel` 或 `TransientModel` 时按
  实际风险处理，不创建为了通过检查而放宽权限的 ACL。
- 控制器、外部请求、定时任务、邮件、个人信息、认证或密钥相关改动必须补充失败路径和越权
  测试，不得创建模拟认证后门、伪造成功路径或真实外部调用。
- 前端行为使用 Hoot 测试，并把测试注册到 `web.assets_unit_tests`；每个 Hoot 文件使用模块
  技术名作为标签。
- 影响已有数据或默认记录时评估迁移脚本。迁移目录允许采用 Odoo 支持的 major-less 版本，
  不要仅凭目录名机械改写已有迁移。
- 用户可见行为、安装配置、安全边界、公共接口或升级方式变化时，同步更新模块 README；新增
  模块还要更新根 README 的模块表。

## 完成前验证

至少执行：

```bash
python3 tools/check_modules.py check
python3 -m unittest discover -s tools/tests -p "test_*.py" -v
```

随后根据改动范围，在独立测试数据库中执行：

- 对所有受影响模块做全新安装；
- 运行对应 `/模块名` 服务端测试；
- 修改前端时运行对应 Hoot 标签；
- 修改迁移时验证旧版本数据升级与用户自定义数据保留；
- 外部平台真实链路只做人工验收，自动测试必须 mock。

如果环境不足以运行某项动态验证，交付说明必须列出未运行项、原因和已完成的替代检查。
