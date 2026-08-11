# 参与贡献

感谢你改进 OdooCC。本仓库面向 Odoo 19，每个正式模块都配有一个仅供开发、演示和验收使用
的 `_test` 模块。提交改动时，请保持两者的职责边界清晰。

## 开始之前

1. 对缺陷修复，先搜索现有 Issue，确认没有重复报告。
2. 对较大的功能、公共 API 或数据模型变化，建议先创建功能建议 Issue，说明业务问题、方案与
   兼容性影响。
3. 安全漏洞不要公开讨论或提交 Pull Request，请按 [`SECURITY.md`](SECURITY.md) 私下报告。
4. 请确认你有权依据 AGPL-3.0 提交相关代码、文档和素材。

## 本地开发环境

推荐使用 Odoo 19.0、独立 PostgreSQL 测试数据库和受支持的 Python 环境。将本仓库放在 Odoo
源码根目录的 `addons_odoocc` 中，或把实际路径加入 `addons_path`。除非特别说明，本文件的
命令都在 Odoo 源码根目录执行，并假定仓库目录名为 `addons_odoocc`。

使用仓库工具发现并安装当前全部模块：

```bash
OCC_MODULES="$(python3 addons_odoocc/tools/check_modules.py list --format csv)"

./odoo-bin -d <开发数据库> \
    --addons-path=addons,addons_odoocc \
    -i "$OCC_MODULES" \
    --without-demo=true \
    --stop-after-init
```

不要在生产数据库安装任何以 `_test` 结尾的模块。

## 创建新模块

完整规则见 [`docs/ODOO_MODULE_STANDARD.md`](docs/ODOO_MODULE_STANDARD.md)。新模块必须成对
创建正式模块和 `_test` 验收模块，建议先 dry-run：

```bash
python3 addons_odoocc/tools/scaffold_module.py create occ_example \
    --title "示例能力" \
    --summary "面向用户的中文摘要" \
    --summary-en "A concise English summary." \
    --description "说明要解决的问题、目标用户和明确边界。" \
    --demo-category developer_tools \
    --depends base \
    --dry-run
```

确认目标目录和参数后去掉 `--dry-run`。脚手架不会覆盖已有目录，也不会修改 Git 索引。生成
后必须补充真实业务实现、权限和回归测试，并在根 README 模块表登记两个新模块。

## 代码与文档约定

- 遵循 [`.editorconfig`](.editorconfig)；Python 和 JavaScript 使用 4 空格缩进，YAML 使用
  2 空格缩进，文件采用 UTF-8 与 LF 换行。
- 遵循 [`docs/ODOO_MODULE_STANDARD.md`](docs/ODOO_MODULE_STANDARD.md) 中的 Manifest、
  正式模块、验收模块、权限、测试和文档规范。
- 遵循 Odoo 19 的模型、视图、资源包和测试惯例，不绕过 ACL、记录规则或 CSRF 防护。
- 面向用户的中文应自然、明确；模型名、字段名、XML ID、资源包名和 API 参数等稳定技术标识
  保持英文。
- 新增或改变行为时补充相应的服务端测试；TreeGrid 前端行为同时补充 Hoot 测试。
- 行为、安装方式、安全边界或公共契约发生变化时，同步更新根 README 和模块 README。
- 不要提交真实 AppID、AppSecret、SMTP 密码、访问令牌、个人信息、数据库转储或生产日志。

模块版本采用 Odoo 形式的版本号，例如 `19.0.1.0.0`。需要调整版本时，应在 Pull Request 中
说明兼容性、数据迁移和升级步骤；不要仅为无行为变化的格式调整随意增加版本。

## 提交前验证

先运行规范检查与仓库工具单测：

```bash
python3 addons_odoocc/tools/check_modules.py check
python3 -m unittest discover \
    -s addons_odoocc/tools/tests \
    -t addons_odoocc \
    -p "test_*.py" \
    -v
```

再使用独立数据库运行服务端测试：

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
    --test-enable --stop-after-init \
    --test-tags="$SERVER_TEST_TAGS"
```

修改任一模块的 JavaScript、前端 XML 或 SCSS 时，还要按模块技术名运行 Hoot。可自动查看
已注册 Hoot 的模块：

```bash
python3 addons_odoocc/tools/check_modules.py list --format hoot-modules

./odoo-bin -d <测试数据库> \
    --addons-path=addons,addons_odoocc \
    -u web,<模块名> \
    --test-enable --stop-after-init \
    --test-tags='/web:WebSuite.test_unit_desktop[@<模块名>]'
```

Hoot 需要 Chrome 或 Chromium。若某项检查因环境限制无法运行，请在 Pull Request 中明确说明
未运行的项目、原因和替代验证，不要直接省略。

## Pull Request 要求

- 一次 Pull Request 聚焦一个清晰问题，避免混入无关重构。
- 关联对应 Issue，并说明受影响模块、用户可见变化和兼容性风险。
- 列出实际执行的命令与结果；界面变化附截图或短视频。
- 明确数据库迁移、权限、个人信息、外部请求和密钥管理方面的影响。
- 确认新增文件具有正确许可证，并且测试、文档和版本已按需要更新。

维护者可能要求拆分改动、补充测试或进一步说明设计取舍。合并前所有 CI 检查都应通过。
