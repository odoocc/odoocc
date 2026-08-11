# OdooCC Odoo 19 模块开发规范

本文定义 OdooCC 模块从创建、实现、测试到发布的统一基线。目标是让新模块可以自动发现、
全新安装、独立理解和安全验收，同时允许 TreeGrid、认证集成、纯后端能力等不同形态按需组织
目录。

除非特别说明，本文命令都在 Odoo 源码根目录执行，并假定本仓库目录名为
`addons_odoocc`。

## 1. 适用范围与原则

- 适用于本仓库全部 Odoo 19 模块。
- 中文是用户文档和界面文案的主要语言；稳定技术标识使用英文。
- 正式模块与演示/验收模块严格分离。
- 目录按真实能力创建，不为了“看起来完整”生成空模型、空 ACL、空控制器或空迁移。
- 静态检查保证结构底线；Odoo 动态测试和人工审查负责判断业务正确性。

## 2. 命名与模块配对

正式模块名必须匹配：

```text
occ_<domain>
occ_<domain>_<capability>
```

只允许小写 ASCII 字母、数字和单个下划线分段，例如 `occ_quality_trace`。禁止大写、连字符、
路径分隔符、连续下划线以及以 `_test` 结尾的正式模块名。

每个正式模块必须有一个可安装的同名验收模块：

```text
occ_quality_trace
occ_quality_trace_test
```

正式模块不得依赖、导入或通过 XML 引用 `_test` 模块。验收模块必须直接依赖对应正式模块，
用来展示或验证公开契约，不复制正式实现。

Python、XML 和数据库标识建议遵循：

| 对象 | 示例 |
| --- | --- |
| 模块 | `occ_quality_trace` |
| 模型 | `occ.quality.trace.record` |
| Python 类 | `OccQualityTraceRecord` |
| XML ID | `view_occ_quality_trace_record_list` |
| 字段/方法 | `trace_code`、`action_confirm` |
| Hoot 标签 | `occ_quality_trace` |

面向用户的名称、帮助文本和错误信息使用自然中文；模型名、字段名、XML ID、路由参数和公开
API 键名保持英文。

## 3. 最小目录与条件性目录

每个模块至少包含：

```text
<module>/
├── README.md
├── __init__.py
├── __manifest__.py
└── tests/
    ├── __init__.py
    └── test_*.py
```

其他目录按能力创建：

| 目录 | 创建条件 |
| --- | --- |
| `models/` | 定义、继承模型或模型混入 |
| `controllers/` | 提供 HTTP 路由 |
| `services/` | 隔离外部接口或复杂领域逻辑 |
| `security/` | 用户可访问的新持久模型、用户组、ACL 或记录规则 |
| `views/` | 后台视图、菜单、动作或 QWeb 模板 |
| `data/` | 邮件模板、配置、定时任务或安装后必备数据 |
| `demo/` | 只在启用 Odoo demo 数据时加载的数据 |
| `static/src/` | JavaScript、SCSS、OWL/QWeb 等前端资源 |
| `static/tests/` | Hoot 前端测试 |
| `i18n/` | 翻译文件 |
| `migrations/` | 升级已有数据库所需的数据或元数据迁移 |
| `wizards/`、`report/` | 存在对应业务能力 |

`__init__.py` 必须显式导入实际存在的 Python 包；`tests/__init__.py` 必须导入全部
`test_*.py`，否则文件不会被 Odoo 测试加载器执行。

## 4. Manifest

### 4.1 固定字段

```python
{
    "name": "OdooCC 质量追溯",
    "version": "19.0.1.0.0",
    "category": "Manufacturing",
    "summary": "追踪批次、工序和质量事件",
    "description": "为制造企业提供可审计的质量追溯基础能力。",
    "author": "Odoo老赵",
    "website": "https://odoocc.com",
    "support": "156277468@qq.com",
    "license": "AGPL-3",
    "depends": ["mrp", "stock"],
    "application": False,
    "installable": True,
}
```

规则：

- `name` 以 `OdooCC` 开头。
- `version` 严格采用 `19.0.x.y.z` 五段数字。
- `summary` 是简短中文摘要；`description` 说明价值和边界，不复述营销口号。
- `author`、`website`、`support`、`license` 使用上述固定值。
- `depends` 只声明实际直接依赖，正式模块不得依赖 `_test`。
- `application` 必须显式填写；扩展模块通常为 `False`，真正独立完整的应用经评审后可为
  `True`。
- `installable` 必须为 `True`。尚未达到安装基线的代码不应进入公开分支。

### 4.2 `_test` 模块

```python
{
    "name": "OdooCC 质量追溯验收",
    "version": "19.0.1.0.0",
    "category": "Tools",
    "summary": "验收 OdooCC 质量追溯的公开业务契约",
    "description": "提供管理员可维护的脱敏验收清单。",
    "author": "Odoo老赵",
    "website": "https://odoocc.com",
    "support": "156277468@qq.com",
    "license": "AGPL-3",
    "depends": ["occ_quality_trace"],
    "data": [
        "security/ir.model.access.csv",
        "data/acceptance_checklist_data.xml",
        "views/acceptance_check_views.xml",
    ],
    "odoocc_demo": {
        "schema_version": 1,
        "category": "supply_manufacturing",
        "sequence": 100,
        "menu_xmlid": "occ_quality_trace_test.menu_acceptance_root",
        "entry_menu_xmlid": "occ_quality_trace_test.menu_acceptance_check",
        "keywords": ["质量追溯", "批次", "质量"],
    },
    "application": False,
    "installable": True,
    "auto_install": False,
}
```

验收模块不能进入正式模块依赖链，不得保存 AppSecret、密码、令牌、完整个人身份标识或生产
数据。

#### 统一演示注册协议 v1

`odoocc_demo` 是供部署侧聚合模块读取的纯 Manifest 数据，不是运行时依赖。它包含以下
五个必填字段和一个可选字段，不得增加其他字段：

| 字段 | 约束 | 含义 |
| --- | --- | --- |
| `schema_version` | 整数 `1` | 协议版本；不支持的版本不得猜测解析 |
| `category` | 下表七个技术值之一 | 统一演示 App 的二级分类 |
| `sequence` | `1..9999` 正整数 | 模块在分类中的稳定排序，默认 `100` |
| `menu_xmlid` | 当前模块的完整 XML ID | 可在聚合环境中重组父级的模块菜单 |
| `entry_menu_xmlid` | 当前模块的完整 XML ID | 带 action 的默认可点击入口，必须是上述菜单本身或后代 |
| `keywords`（可选） | 最多 12 个去重的非空单行字符串，每项最长 40 字符 | 部署侧搜索同义词；省略时等同于空列表 |

`category` 允许值：

| 技术值 | 中文分类 |
| --- | --- |
| `foundation_localization` | 基础与本地化 |
| `customer_operations` | 客户、销售与服务 |
| `supply_manufacturing` | 采购、库存与制造 |
| `finance_compliance` | 财税与合规 |
| `collaboration_integration` | 协同与平台集成 |
| `data_ai_automation` | 数据、自动化与 AI |
| `developer_tools` | 开发者工具 |

两个菜单 XML ID 必须由当前 `_test` Manifest 的 `data` XML 创建，使用模块全名前缀，
并在未启用 Odoo demo 数据时也存在。聚合器只能重组菜单层级和排序，不能扩大菜单
用户组、模型 ACL 或记录规则。

`_test` 模块必须只直接依赖其真实功能所需的模块，不得在 Manifest 依赖或 asset 中引用
`occ_odoocc_demo`，Python/JavaScript 不得导入它，XML 也不得引用它的记录。因此社区用户
只配置 `addons_odoocc` 时，每个 `_test` 仍能独立安装并使用原有菜单与前端资源。

### 4.3 版本语义

OdooCC 使用 `19.0.x.y.z`：

- `19.0`：目标 Odoo 主版本；
- `x`：不兼容或重要功能代际；
- `y`：向后兼容功能；
- `z`：修复、文档随行为修正或小型兼容调整。

版本变化必须与实际发布内容一致。若升级需要转换已有数据、XML ID 或默认记录，应添加迁移
脚本和回归测试。Odoo 19 支持 major-less 迁移目录，例如 Manifest
`19.0.4.0.5` 可使用 `migrations/4.0.5/`；不要强制重命名已有有效目录。

### 4.4 数据与资源

- Manifest 中 `data`、`demo` 和 asset 路径必须存在，不重复，不越出模块目录。
- Odoo 19 后台列表视图使用 `<list>`，不要沿用旧版 `<tree>`。
- 安装后无论是否启用 demo 都必须存在的数据放 `data/`；仅演示数据放 `demo/`。
- 是否使用 `noupdate="1"` 按升级语义决定：
  - 固定演示基线需要升级恢复时不使用 `noupdate`；
  - 人工验收状态、备注或用户维护值需要保留时使用 `noupdate="1"`。
- 前端测试资源注册到 `web.assets_unit_tests`，业务资源注册到正确的 backend、frontend 或
  lazy bundle。

## 5. Python、模型与事务

- 遵循 `.editorconfig`：UTF-8、LF、4 空格缩进，目标行宽 100。
- 模型必须设置准确的 `_description`；有稳定业务顺序时显式设置 `_order`。
- 字段约束在 ORM 和数据库层按风险组合实现，不只依赖界面属性。
- 批量 API 必须正确处理多记录集；避免隐含 singleton 假设。
- 不通过 `sudo()` 修复权限设计。确需提权时缩小范围、说明信任边界并补充越权测试。
- 多步写入、排序、迁移和并发路径应使用保存点、约束或锁保证失败时不留下半完成状态。
- 不捕获宽泛异常后静默成功；用户错误应可操作，日志应保留脱敏诊断信息。
- 新持久模型必须明确访问策略。面向用户的模型提供最小 ACL；只允许受控服务、cron 或
  `sudo()` 边界内访问的内部存储模型可以有意不授予 ACL，但必须在 README 说明理由，并测试
  普通用户无法直接访问。继承现有模型、`AbstractModel`、`TransientModel` 不机械增加空
  ACL，但仍需评估字段级权限和调用入口。
- 敏感字段使用字段级 `groups` 或独立安全模型，不能只在视图中隐藏。

ACL 文件使用标准表头：

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
```

权限应遵循最小授权，并在测试中同时覆盖被允许用户和至少一个被拒绝用户。

## 6. 视图与前端

- XML ID 在模块内稳定且语义明确；发布后不要仅为命名美观随意更换。
- 菜单、动作、列表、表单和搜索视图必须形成可达链路，用户组与模型 ACL 保持一致。
- 视图中的 `groups` 不是服务端安全边界。
- JavaScript 模块采用 Odoo 19 模块与 OWL/Hoot 约定，避免全局补丁；必须补丁时说明影响面
  和卸载/升级行为。
- 前端错误、空状态、键盘操作和辅助功能按实际交互风险测试。
- 每个 Hoot 测试文件添加：

  ```javascript
  describe.current.tags("headless", "occ_quality_trace");
  ```

模块技术名标签用于 CI 自动发现后定向执行。

## 7. 控制器、外部系统与敏感数据

- 明确每条路由的 `auth`、HTTP 方法、CSRF、会话和返回格式。
- 对 state、nonce、回调 code、一次性 grant 和重放攻击设置服务端校验与过期机制。
- 重定向目标使用可信 allowlist，拒绝开放重定向。
- 外部请求设置连接/读取超时，校验响应结构，区分可重试与不可重试错误。
- 自动测试 mock 微信、SMTP、支付或其他外部平台；CI 不访问真实服务。
- 不把密钥、令牌、邮箱验证链接、完整个人身份标识写入日志、README、样例数据或验收备注。
- `tools/check_modules.py check` 只提供确定性的高置信敏感信息基线扫描，不能证明仓库或 Git
  历史中不存在密钥；提交和发布前建议额外使用 Gitleaks 扫描，并人工复核配置、XML 数据与
  测试夹具。
- 认证类 `_test` 模块只提供真实流程清单，不增加模拟登录入口、身份伪造、回调后门或成功
  捷径。

## 8. 测试

### 8.1 服务端

每个 `test_*.py` 中的 Odoo 测试类使用：

```python
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestQualityTrace(TransactionCase):
    ...
```

按能力覆盖：

- 全新安装与 Manifest 数据加载；
- 正常流程、边界值和失败回滚；
- ACL、记录规则、门户/公共用户越权；
- 归档、多公司、时区和并发；
- 视图、菜单、动作与公开模型/RPC 契约；
- 控制器认证、CSRF、重定向、一次性令牌和异常；
- 升级迁移与用户自定义值保留。

测试必须独立、可重复，不依赖执行顺序、生产数据或真实外部平台。

### 8.2 `_test` 验收模块

验收模块必须满足：

- `installable=True`、`application=False`、`auto_install=False`；
- 有内部用户或管理员可见的菜单；
- 提供样例场景或人工验收清单；
- 状态、备注等人工结果不包含敏感数据；
- 自动测试验证安装、ACL、菜单、样例数据及与正式模块的集成；
- 真实扫码、邮件、支付等链路由人工在隔离环境验收。

通用脚手架生成管理员验收清单。若正式模块适合可操作演示模型，应把 `_test` 扩展成能直接
验证公开契约的样例，例如 TreeGrid 的层级模型；不要保留与业务无关的伪功能。

### 8.3 Hoot

有前端交互逻辑时：

- 在 `static/tests/` 添加 Hoot；
- 在 Manifest 的 `web.assets_unit_tests` 以直接字符串路径或 glob 注册；为保证 CI 能静态确认
  每个测试实际进入 bundle，不在该 bundle 中使用 `include`、`remove`、`replace` 等指令；
- 使用模块技术名标签；
- 覆盖解析、状态变化、RPC、错误通知、键盘和权限相关表现。

## 9. README

中文正文至少说明：

- 定位、适用场景和功能边界；
- 安装、配置、使用、升级和卸载；
- 权限、安全、数据和生产注意事项；
- 自动测试命令和人工验收前置条件；
- 对应 `_test` 模块的用途及入口；
- 作者、官网、支持邮箱和 AGPL-3；
- `## English summary` 简述价值、边界和生产适用性。

`_test` README 在开头明确“不建议在生产环境安装”，并说明固定样例、人工记录在升级时是否
重置。不得虚构演示地址、外部平台能力或尚不存在的业务功能。

## 10. 脚手架

先预览：

```bash
python3 addons_odoocc/tools/scaffold_module.py create occ_quality_trace \
    --title "质量追溯" \
    --summary "追踪批次、工序和质量事件" \
    --summary-en "Trace lots, operations, and quality events." \
    --description "为制造企业提供可审计的质量追溯基础能力。" \
    --category "Manufacturing" \
    --demo-category supply_manufacturing \
    --demo-sequence 100 \
    --demo-keyword "质量追溯" \
    --demo-keyword "批次" \
    --depends mrp \
    --depends stock \
    --dry-run
```

确认后去掉 `--dry-run`。脚手架会同时生成正式模块和 `_test` 模块，固定品牌元数据，不覆盖
已有文件，也不修改 Git 索引。生成后仍需：

1. 实现真实模型、视图、权限和业务测试。
2. 按业务语义调整 `_test` 验收项或样例模型。
3. 在根 README 模块表中增加两个模块。
4. 运行静态检查、工具单测和 Odoo 动态测试。

仓库 CI 还会生成固定的 `occ_scaffold_smoke` 临时模块对，并在全新数据库安装其 `_test`
模块、执行两侧服务端测试。这样模板中的 ACL XML ID、菜单引用和视图字段等 Odoo 语义错误
会在模板变更时直接失败，而不是等到下一次真实模块创建后才暴露。

## 11. 自动检查与本地命令

列出自动发现的模块：

```bash
python3 addons_odoocc/tools/check_modules.py list --format lines
```

运行仓库规范检查：

```bash
python3 addons_odoocc/tools/check_modules.py check
python3 -m unittest discover \
    -s addons_odoocc/tools/tests \
    -t addons_odoocc \
    -p "test_*.py" \
    -v
```

生成 Odoo 安装列表与服务端标签：

```bash
OCC_MODULES="$(python3 addons_odoocc/tools/check_modules.py list --format csv)"
SERVER_TEST_TAGS="$(python3 addons_odoocc/tools/check_modules.py list --format test-tags)"
```

在独立数据库中验证：

```bash
./odoo-bin -d <测试数据库> \
    --addons-path=addons,addons_odoocc \
    --init="$OCC_MODULES" \
    --without-demo=true \
    --stop-after-init

./odoo-bin -d <测试数据库> \
    --addons-path=addons,addons_odoocc \
    --update="$OCC_MODULES" \
    --test-enable \
    --test-tags="$SERVER_TEST_TAGS" \
    --stop-after-init
```

CI 会使用同一发现工具生成模块列表，先把每个模块分别装入独立数据库以发现漏声明的直接
依赖，再在汇总数据库安装全部模块并运行服务端与 Hoot 测试。因此新模块不需要手工修改 CI
变量。

## 12. 发布前检查清单

- [ ] 正式模块与同名 `_test` 模块同时存在。
- [ ] Manifest 固定元数据、依赖、版本和安装标志正确。
- [ ] 正式模块没有任何 `_test` 依赖。
- [ ] 新持久模型的访问策略明确：用户模型有最小 ACL，内部模型的无 ACL 设计已记录并测试。
- [ ] Manifest 的数据和资源路径均存在。
- [ ] 服务端测试已由 `tests/__init__.py` 注册并通过。
- [ ] 前端行为有 Hoot，模块标签与技术名一致。
- [ ] 数据变化有升级策略、迁移和回归测试。
- [ ] README 中英文摘要、安装、配置、安全、测试和联系信息完整。
- [ ] `_test` README 明确非生产用途，验收数据不含敏感信息。
- [ ] `_test` 的 `odoocc_demo` v1 字段、七类分类、本地菜单 XML ID 和搜索词合法。
- [ ] `_test` 没有依赖、导入或 XML 引用 `occ_odoocc_demo`，可在社区仓库中独立安装。
- [ ] 根 README 模块表已更新。
- [ ] 未提交真实密钥、个人信息、数据库、日志或运行产物。
- [ ] `python3 addons_odoocc/tools/check_modules.py check` 和工具单测通过。
- [ ] 全新安装、服务端测试及适用的 Hoot/人工验收通过。
