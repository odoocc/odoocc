# OdooCC TreeGrid 演示与集成测试（`occ_treegrid_test`）

`occ_treegrid_test` 是 `occ_treegrid` 的可安装演示模块。它提供一个最小但完整的层级业务
模型、可见菜单、三级样例树和服务端自动测试，方便开发、验收及回归 TreeGrid 的公开契约。
模块不修改 `occ_treegrid`，也不应作为真实业务数据模型使用。它会装载固定样例数据并向内部
用户开放完整 CRUD 权限，因此不建议在生产数据库中安装。

## English summary

`occ_treegrid_test` is an installable OdooCC demonstration and integration-test module for
`occ_treegrid`. It provides a minimal hierarchical model, visible menus, fixed three-level sample
data, and automated contract tests. It is intended for development, QA, and acceptance testing;
production installation is not recommended. Dependency-free manifest metadata lets an optional
deployment aggregator organize its existing menu without changing standalone installation.

## 安装与入口

模块依赖 `occ_treegrid`，不会自动安装：

```bash
./odoo-bin -c odoo.conf -d <数据库> -i occ_treegrid_test --stop-after-init
```

安装后，内部用户可从顶级菜单“OdooCC TreeGrid 演示”进入“层级节点”。列表默认展开整棵树，
并允许在没有搜索或自定义排序时通过手柄调整同一父节点下的顺序。

## 统一演示入口协议

本模块始终可以单独安装，不依赖、不导入部署侧的 `occ_odoocc_demo`。Manifest 中的
`odoocc_demo` 是版本化的纯数据协议，供 OdooCC 在线演示环境自动发现并组织菜单：

- 分类：`developer_tools`（开发者工具）；
- 可被接管的模块菜单：`occ_treegrid_test.menu_occ_treegrid_test_root`；
- 默认可点击入口：`occ_treegrid_test.menu_occ_treegrid_test_node`。

未安装聚合模块时，上述原有顶级菜单和权限保持不变。聚合环境只允许重组菜单，
不得改变 `base.group_user` 的现有 CRUD 边界或门户/公共用户的拒绝策略。

## 样例结构

模块固定装载以下样例，便于在没有演示数据选项的数据库中直接验收：

```text
演示根节点
├── 子节点 A
│   └── 孙节点 A-1
├── 子节点 B
└── 已归档子节点（默认隐藏）
```

在搜索菜单中启用“已归档”筛选，可以查看归档节点。TreeGrid 排序 RPC 会把当前用户可访问
的归档同级节点一并纳入重新编号，避免恢复后出现冲突顺序。

这五条固定样例用于保证验收环境可重复：模块升级会重新写入它们的基线名称、父子关系、排序
和归档状态。请把需要长期保留的业务示例另建记录，不要依赖这些样例保存业务数据。

## 集成契约

模型 `occ.treegrid.test.node`：

- 继承 `occ.treegrid.mixin`；
- 使用自关联 `parent_id` 作为父字段；
- 使用整数 `sequence` 作为同级排序字段；
- 使用 `parent_path` 保存层级路径，并拒绝父子循环；
- 使用 `active` 支持标准归档行为。

列表视图严格声明：

```xml
<list js_class="occ_treegrid" default_order="sequence,id">
    <field name="sequence" widget="handle"/>
    <field name="name"
           options="{'occ_treegrid_column': True,
                     'occ_treegrid_default_expand': 'all'}"/>
    <field name="parent_id" optional="hide"
           options="{'occ_treegrid_parent': True}"/>
</list>
```

内部用户拥有样例模型的读、写、创建和删除权限，以便实际验证拖拽排序；门户用户和公共用户
没有该模型 ACL，菜单也仅对内部用户可见。

## 自动测试

`tests/test_treegrid_test.py` 覆盖：

- 深层匹配记录的可读祖先补入；
- 三级样例结构和 `all` 展开视图契约；
- 包含归档节点的同级排序；
- 跨父节点排序拒绝；
- 默认归档过滤及显式归档读取；
- 内部用户 CRUD 与门户用户 ACL 拒绝；
- 列表字段选项、动作、菜单和归档筛选契约；
- 父子循环约束。

定向运行：

```bash
./odoo-bin -c odoo.conf -d <测试数据库> \
    --test-enable --test-tags /occ_treegrid_test \
    -i occ_treegrid_test --stop-after-init
```

## 许可证与联系

- 作者：Odoo老赵
- 网站：https://odoocc.com
- 技术支持：156277468@qq.com
- 许可证：AGPL-3
