# OCC Approval

`occ_approval` 是面向 Odoo 19 的通用审批引擎。核心模块只依赖 `mail` 与
`web`，不绑定销售、采购等具体业务模块。

## 核心能力

- 可视化 DAG 设计器：拖拽节点、连线、缩放、自动布局和条件分支。
- 五类节点：`start`、`approval`、`task`、`copy`、`end`。
- 审批模式：全员通过（`all`）或任一通过（`any`）。
- 分配方式：指定用户、审批角色、直属上级、上级链、申请人、申请人选人。
- 驳回、撤回、取消提交、催办、截止时间、自动同意和自动驳回。
- 审批侧栏、全局表单入口、我的待办 Dashboard 和完整流程轨迹。
- 发布版本不可变，实例固定引用发起时的版本。
- SHA-256 完整版本快照校验和 append-only 审计事件。
- 行锁、草稿 revision、每个源单据仅一个活动实例与并发冲突友好提示。
- 多公司隔离以及申请人、参与人、任务处理人、管理员的分层权限。
- 固定 Python 连接器白名单；数据库中不执行 Python 代码或任意方法名。

## 流程定义

设计器保存 JSON 原生、可版本化的 DAG。字段使用 `id`、`name`、
`assignment`、`mode`、`sequence` 和 `condition`：

```json
{
  "schema_version": 1,
  "nodes": [
    {
      "id": "start",
      "type": "start",
      "name": "发起",
      "position": {"x": 80, "y": 180}
    },
    {
      "id": "department_approval",
      "type": "approval",
      "name": "部门审批",
      "position": {"x": 300, "y": 180},
      "assignment": {"type": "role", "role_id": 12},
      "mode": "all",
      "deadline_hours": 24,
      "reminder_before_hours": 4,
      "timeout_action": "approve"
    },
    {
      "id": "follow_up",
      "type": "task",
      "name": "后续处理",
      "position": {"x": 520, "y": 100},
      "assignment": {"type": "requester_choice"},
      "mode": "any",
      "deadline_hours": 48,
      "reminder_before_hours": 8,
      "timeout_action": "reject",
      "timeout_reject_node": "department_approval",
      "timeout_reject_mode": "sequential"
    },
    {
      "id": "end",
      "type": "end",
      "name": "完成",
      "position": {"x": 760, "y": 180}
    }
  ],
  "edges": [
    {
      "source": "start",
      "target": "department_approval",
      "sequence": 10,
      "condition": []
    },
    {
      "source": "department_approval",
      "target": "follow_up",
      "sequence": 10,
      "condition": [["category_id", "!=", false]]
    },
    {
      "source": "department_approval",
      "target": "end",
      "sequence": 20,
      "condition": []
    },
    {
      "source": "follow_up",
      "target": "end",
      "sequence": 10,
      "condition": []
    }
  ]
}
```

发布时会强制验证：

- 恰好一个开始节点和一个结束节点；
- 图必须无环，所有节点从开始可达并且最终可到达结束；
- 每个非结束节点恰好有一条空条件 fallback；
- 同一源节点的出口 `sequence` 为正整数且不可重复，fallback 排在最后；
- Domain 必须是 JSON 原生 Odoo Domain，不接受字符串求值或 Python 表达式；
- 超时驳回目标必须更早、可驳回，并且支配当前节点，即所有到达当前节点的路径都经过它。

发布生成不可修改的 `occ.approval.workflow.version`。checksum schema 2 覆盖流程、
公司、版本号、模型、动作、适用 Domain、自动执行开关、完整图定义及发布元数据；
实例创建和自动执行前都会复核。开发期 schema 1 版本仍可读取，其校验范围仅为旧的
definition JSON。

## 业务模型接入

手动审批可通过全局表单入口用于用户有权读写且存在已发布流程的普通 Odoo 记录。
如需在业务模型中显示计算字段或提供明确按钮，可继承 mixin：

```python
from odoo import models


class BusinessDocument(models.Model):
    _inherit = ["your.business.model", "occ.approval.source.mixin"]
```

自动业务动作必须在 Python 连接器中显式声明白名单，并实现固定适配器：

```python
from odoo import _, api, models
from odoo.exceptions import UserError


class BusinessDocument(models.Model):
    _inherit = ["your.business.model", "occ.approval.source.mixin"]

    @api.model
    def _occ_supported_approval_actions(self):
        return frozenset({"document_confirm"})

    def _occ_execute_approved_action(self, instance):
        self.ensure_one()
        if instance.action_key != "document_confirm":
            raise UserError(_("Unsupported approved action."))
        return self.action_confirm()

    def action_request_confirm_approval(self):
        self.ensure_one()
        return self._occ_create_approval(action_key="document_confirm")

    def action_confirm(self):
        self.ensure_one()
        if self.env.context.get("occ_approval_execution"):
            self._occ_assert_approved_execution(action_key="document_confirm")
            return super().action_confirm()
        return self.action_request_confirm_approval()
```

`occ_approval_execution` 只用于识别执行路径，不能单独作为授权依据；它是客户端可构造的
context 值。若连接器复用公开业务动作，必须同时调用
`_occ_assert_approved_execution()`，由核心校验仅服务端可持有的执行 capability、实例、
源记录、action key、申请人、状态和公司。更简单的连接器可以直接调用不可 RPC 的私有
业务实现。核心引擎不会从数据库读取 Python 代码，也不会按数据库中的方法名动态调用；
发布和实际执行两个阶段都会复核 `_occ_supported_approval_actions()`。

数据库内业务动作受 savepoint 保护；外部 API、消息队列等数据库外副作用必须由 connector
按 `(instance.id, instance.action_key)` 实现幂等，或先写入 transactional outbox。核心
当前提供 at-least-once 重试语义，不能替外部系统保证 exactly-once。

自动动作以原申请人的权限和实例所属公司执行，`allowed_company_ids` 会收窄到该公司，
不会以超级用户执行业务操作。因此申请人在执行时仍需拥有实例公司及源单据写权限；
权限不足会形成可重试的执行失败，内部异常详情只向审批管理员展示。

## 权限模型

- `occ_approval.group_approval_user`：发起审批、处理自己的任务、查看本人参与的实例。
- `occ_approval.group_approval_manager`：维护当前公司的角色与流程、查看当前公司运行数据。
- `occ_approval.group_approval_technical`：可跨公司维护流程定义，但运行数据仍受 active
  companies 限制。
- Portal 用户没有流程、实例、任务或审计事件权限。

运行表的 create/write/unlink 只能由服务层执行；普通用户和管理员都不能直接改状态。
面板按当前用户的 record rules 查找历史实例，源单据本身的读写权限也会再次校验。
源单据在审批中途切换公司会被阻止继续流转，并要求取消后重新发起。

## 安装与升级

当旧源码目录也在 addons path 中时，新目录必须排在旧目录前面：

```bash
venv/bin/python odoo-bin \
  --addons-path=addons,addons_occ,addons_odoocc \
  --database=<database> \
  --update=occ_approval \
  --stop-after-init
```

生产升级前应先备份数据库，并在副本上完成安装、权限、流程发布、审批全流程和前端资产
验证。定时任务“Approval deadline processor”负责提醒与超时动作。

## 测试

```bash
venv/bin/python odoo-bin \
  --addons-path=addons,addons_occ,addons_odoocc \
  --database=<test_database> \
  --update=occ_approval \
  --test-enable \
  --test-tags=/occ_approval \
  --stop-after-init
```

详细的旧模块替换边界见 `MIGRATION.md`。
