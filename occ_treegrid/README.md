# OCC 层级列表（`occ_treegrid`）

`occ_treegrid` 在 Odoo 标准列表视图上增加树形层级、展开/收起、祖先上下文展示和同级
拖拽排序。它只对明确继承服务端混入并显式声明视图选项的模型生效，不会猜测任意模型的
父字段或排序字段，也不会全局替换 Odoo 原生列表视图。

## 业务价值

- 在熟悉的列表界面中展示目录、分类、组织、任务分解等层级数据，减少用户在列表和树控件
  之间切换的认知成本。
- 搜索命中深层节点时自动补入用户可读的祖先链，让用户知道结果处于哪条业务路径中。
- 拖拽排序仅作用于同一父节点下的同级记录，并由服务端事务、权限检查和并发锁保护。
- 继续复用 Odoo 列表的字段组件、按钮、选择、表单打开和搜索能力，降低定制视图的维护成本。

## 适用角色

- 业务用户：浏览层级、展开或收起分支、筛选节点，并在允许时调整同级顺序。
- 业务管理员：维护树结构完整性、排序权限和节点规模。
- 模块开发者：让自定义层级模型接入 TreeGrid，并配置列表视图契约。
- 实施与运维人员：评估记录规则、归档数据、并发排序和节点上限带来的影响。

## 典型场景

- 文档目录、知识分类、产品分类或资产目录。
- 组织单元、区域、成本中心等管理层级。
- 工作分解结构、项目阶段树或可排序的菜单结构。

TreeGrid 适合“父子层级 + 同级人工排序”的数据。若业务需要跨父节点拖拽、按需懒加载数十万
节点、行内批量编辑或分组统计，应采用专门方案，而不是直接套用本模块。

## 核心功能

### 层级渲染

- 将服务端返回的平铺记录转换为深度优先顺序。
- 支持 `roots`（默认仅显示根层）和 `all`（首次显示全部分支）两种展开策略。
- 支持鼠标点击和左右方向键展开/收起。
- 输出 `treegrid`、`aria-level`、`aria-expanded`、`aria-posinset` 和
  `aria-setsize` 等辅助功能元数据。

### 祖先上下文与筛选

- 服务端读取匹配节点后，继续向上补齐当前用户可读的祖先。
- 补入的祖先只作为上下文显示，不计入匹配数量，也不会进入批量选择。
- 存在显式搜索时，匹配路径会强制展开，便于定位结果。
- 已归档或被记录规则隐藏的父节点不会通过 `sudo()` 强行返回；可见子节点会作为不可拖拽的
  临时根节点展示。

### 同级拖拽排序

- 仅允许在同一父节点下，将节点放到某个同级节点之前或之后。
- 显式筛选、搜索面板条件、非标准排序或只读拖拽字段存在时会禁用拖拽。
- 服务端包含当前用户可访问的已归档同级节点一起重新编号，避免恢复归档记录后出现意外顺序。
- 排序值按 `10、20、30...` 规范化，并在保存点内对完整同级集合加非阻塞锁。
- 并发期间层级或同级集合发生变化时，中止并回滚本次排序。

## 安装与升级

1. 将 `addons_occ` 加入 Odoo 的 `addons_path`。
2. 更新应用列表。
3. 安装“OCC 层级列表”（技术名 `occ_treegrid`）。
4. 让需要接入的业务模块在清单中依赖 `occ_treegrid`。

命令行示例：

```bash
./odoo-bin -d <数据库名> -i occ_treegrid --stop-after-init
./odoo-bin -d <数据库名> -u occ_treegrid,<业务模块> --stop-after-init
```

本模块没有独立菜单。安装后只有使用 `js_class="occ_treegrid"` 的列表视图会改变行为。

## 服务端模型配置

模型必须显式继承 `occ.treegrid.mixin`：

```python
from odoo import fields, models


class ExampleNode(models.Model):
    _name = "example.node"
    _description = "示例层级节点"
    _inherit = ["occ.treegrid.mixin"]

    _occ_treegrid_parent_field = "parent_id"
    _occ_treegrid_sequence_field = "sequence"
    _occ_treegrid_max_nodes = 2000

    name = fields.Char(string="名称", required=True)
    parent_id = fields.Many2one("example.node", string="父节点", index=True)
    sequence = fields.Integer(string="排序", default=10, index=True)
```

模型契约如下：

- 父字段必须是已存储、指向模型自身的 `Many2one`。
- 排序字段必须是已存储的 `Integer`。
- `_occ_treegrid_max_nodes` 必须是大于零的整数；默认值为 2000。
- 推荐为父字段和排序字段建立索引，并在业务层阻止父子循环。

混入提供两个 RPC：

- `occ_treegrid_read(domain, specification, order=None)`：读取匹配树及可读祖先上下文。
- `occ_treegrid_resequence(moved_id, target_id, position)`：在同级范围内执行事务化排序。

## 列表视图配置

```xml
<list js_class="occ_treegrid" default_order="sequence,id">
    <field name="sequence" widget="handle"/>
    <field name="name"
           options="{'occ_treegrid_column': True,
                     'occ_treegrid_default_expand': 'roots'}"/>
    <field name="parent_id" optional="hide"
           options="{'occ_treegrid_parent': True}"/>
</list>
```

视图契约如下：

- 必须且只能有一个字段设置 `occ_treegrid_column=True`，该字段负责显示缩进和展开按钮。
- 必须且只能有一个字段设置 `occ_treegrid_parent=True`，并与模型父字段一致。
- 必须且只能有一个 `Integer` 字段使用 `widget="handle"`，并与模型排序字段一致。
- `occ_treegrid_default_expand` 只能设置在树结构列上，值为 `roots` 或 `all`。
- 视图不支持 `editable`、`multi_edit` 或分组。
- 为允许拖拽，`default_order` 必须以排序字段升序、`id` 升序开头，例如
  `sequence,id`。

解析器会在视图加载阶段拒绝不满足契约的配置，避免直到用户拖拽时才发现模型与视图不一致。

## 操作流程

### 浏览与定位

1. 打开接入 TreeGrid 的列表动作。
2. 点击节点前的箭头，或在当前行使用左右方向键展开/收起。
3. 输入搜索条件；若命中深层节点，系统补入可读祖先并自动展开路径。
4. 点击“查看”或普通字段区域，按标准列表行为打开表单。

### 调整顺序

1. 清除筛选、搜索面板条件和自定义排序。
2. 确认列表按排序字段升序、`id` 升序显示。
3. 从拖拽手柄拖动一个节点；展开的后代会作为一个视觉整体随节点移动。
4. 将节点放在同一父节点下另一个同级节点的前后边界。
5. 服务端校验权限、锁定完整同级集合、写入新顺序并重新加载列表。

父节点仍通过常规表单维护。当前版本不允许通过 TreeGrid 拖拽改变父子关系。

## 权限与安全

- 读取与排序均使用当前用户权限，不使用 `sudo()` 绕过 ACL 或记录规则。
- 读取前会执行模型读权限检查，排序前会执行模型与记录写权限检查。
- 排序会在 `active_test=False` 下读取并写入当前用户可访问的同级集合，包括已归档节点，
  但仍严格应用记录规则。业务模型必须保证可排序用户能够读取和写入真实的完整同级集合；
  被规则隐藏的同级节点不会通过 `sudo()` 补入。
- 被 `active_test` 或记录规则隐藏的祖先不会返回，其显示名也会从返回的子记录中清除，防止
  通过 Many2one 展示泄露不可见记录。
- 节点总量和单个同级集合都受 `_occ_treegrid_max_nodes` 限制，避免超大请求耗尽资源。
- 服务端只接受正整数记录 ID，以及固定位置值 `before` 或 `after`。
- 排序使用非阻塞行锁和保存点；锁冲突、层级变化或写入异常会整体回滚。

## 功能边界

- 当前版本仅支持未分组、非行内编辑的动作列表。
- TreeGrid 一次加载完整匹配树，不提供分页和节点懒加载。
- 拖拽只改变同级顺序，不改变 `parent_id`。
- 搜索或非标准排序期间禁用拖拽，因为当前显示顺序不能安全代表完整同级顺序。
- 不可读或已归档祖先不会为了视觉完整性被提升权限返回。
- 若记录规则让用户只能看到部分同级节点，本模块无法安全代表完整业务顺序；应调整业务权限或
  禁止该用户排序，而不是依赖 TreeGrid 猜测隐藏记录。
- 模块不会自动增加模型访问权限、记录规则、父子循环约束或删除保护。

## 性能建议

- 根据业务规模设置 `_occ_treegrid_max_nodes`，不要盲目调高默认 2000 上限。
- 为父字段、排序字段以及常用筛选字段建立数据库索引。
- 大型树应通过动作域先限定业务范围；若单棵树长期超过上限，应评估懒加载树组件。
- 保持同级集合规模合理，因为每次排序会检查、锁定并重新编号整个同级集合。

## 排障

### 提示视图配置无效

- 确认树结构列、父字段列和 `handle` 列各只有一个。
- 确认父字段是指向当前模型自身的 `Many2one`，排序字段是 `Integer`。
- 移除 `editable`、`multi_edit` 和分组配置。
- 检查 `occ_treegrid_default_expand` 是否为 `roots` 或 `all`。

### 列表能显示但不能拖拽

- 清除搜索、筛选、搜索面板分类和收藏中残留的分组。
- 恢复 `sequence ASC, id ASC` 形式的标准排序。
- 确认视图与记录不是只读，并且当前用户拥有完整同级集合的写权限。
- 临时根节点和仅作搜索上下文的祖先节点按设计不可拖拽。

### 提示节点过多

- 缩小动作域或搜索范围后重新打开。
- 检查是否意外将多个大型业务树放入同一动作。
- 只有在评估服务器内存、RPC 负载和前端渲染成本后，才提高
  `_occ_treegrid_max_nodes`。

### 提示层级在排序时发生变化

- 刷新列表后重试；通常表示另一事务同时新增、移动、归档或删除了同级节点。
- 检查自动化任务或集成是否频繁改写父字段和排序字段。

### 子节点显示为临时根节点

- 检查父节点是否已归档。
- 检查当前用户是否受记录规则限制而无法读取父节点。
- 不要通过放宽 `sudo()` 解决；应从业务权限或数据完整性上确认预期可见范围。

## 验证与维护

- Python 测试：`tests/test_treegrid_mixin.py`，覆盖祖先补入、上限、权限、归档同级、
  跨父排序和事务回滚。
- Hoot 测试：`static/tests/treegrid.test.js`，覆盖视图解析、树结构转换、键盘操作、选择、
  拖拽约束、RPC 和通知。
- 修改模块后应执行 Python 编译、XML 解析，并运行上述服务端与 Hoot 测试。

## 为什么保留英文技术标识（Why English identifiers remain）

模型名、字段名、XML 属性、视图注册键、RPC 名、API 参数和值（例如
`occ.treegrid.mixin`、`parent_id`、`sequence`、`js_class`、`occ_treegrid_column`、
`roots`、`all`、`before`、`after`）属于稳定技术契约。将它们翻译为中文会导致视图解析、
外部调用、继承或已有数据失效，因此继续保留英文；面向用户的异常、通知、按钮和辅助功能
说明则使用自然中文。
