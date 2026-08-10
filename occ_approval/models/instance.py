import uuid

from odoo import _, api, fields, models
from odoo.exceptions import AccessError


GROUP_USER = "occ_approval.group_approval_user"
GROUP_MANAGER = "occ_approval.group_approval_manager"
GROUP_TECHNICAL = "occ_approval.group_approval_technical"


class OccApprovalInstance(models.Model):
    _name = "occ.approval.instance"
    _table = "occ_approval_v2_instance"
    _description = "Approval Instance V2"
    _order = "id desc"
    _check_company_auto = True

    name = fields.Char(required=True, default=lambda self: f"APR-{uuid.uuid4().hex[:12].upper()}", index=True)
    company_id = fields.Many2one(
        "res.company", required=True, index=True, ondelete="restrict"
    )
    workflow_id = fields.Many2one(
        "occ.approval.workflow",
        required=True,
        index=True,
        ondelete="restrict",
        check_company=True,
    )
    workflow_version_id = fields.Many2one(
        "occ.approval.workflow.version",
        required=True,
        index=True,
        ondelete="restrict",
        check_company=True,
    )
    action_key = fields.Char(required=True, default="manual", index=True, readonly=True)
    source_model = fields.Char(required=True, index=True, readonly=True)
    source_res_id = fields.Many2oneReference(
        string="Source Record",
        model_field="source_model",
        required=True,
        index=True,
        readonly=True,
    )
    source_display_name = fields.Char(required=True, readonly=True)
    requester_id = fields.Many2one(
        "res.users", required=True, index=True, ondelete="restrict"
    )
    participant_user_ids = fields.Many2many(
        "res.users",
        "occ_approval_v2_instance_participant_rel",
        "instance_id",
        "user_id",
        string="Participants",
        readonly=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("running", "Running"),
            ("rework", "Rework"),
            ("approved", "Approved"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        required=True,
        index=True,
        readonly=True,
    )
    last_decision = fields.Selection(
        [("none", "None"), ("approved", "Approved"), ("rejected", "Rejected")],
        default="none",
        required=True,
        readonly=True,
    )
    current_node_id = fields.Many2one(
        "occ.approval.instance.node",
        readonly=True,
        copy=False,
        ondelete="set null",
        check_company=True,
    )
    return_node_id = fields.Many2one(
        "occ.approval.instance.node",
        string="Direct Rejection Return Node",
        readonly=True,
        copy=False,
        ondelete="set null",
        check_company=True,
    )
    submitted_at = fields.Datetime(readonly=True, copy=False)
    completed_at = fields.Datetime(readonly=True, copy=False)
    cancelled_at = fields.Datetime(readonly=True, copy=False)
    cancellation_reason = fields.Text(readonly=True, copy=False)
    execution_state = fields.Selection(
        [
            ("none", "Not Required"),
            ("pending", "Pending"),
            ("running", "Running"),
            ("done", "Done"),
            ("failed", "Failed"),
        ],
        default="none",
        required=True,
        index=True,
        readonly=True,
        copy=False,
    )
    execution_attempts = fields.Integer(default=0, readonly=True, copy=False)
    execution_error = fields.Text(
        string="Internal Execution Error",
        readonly=True,
        copy=False,
        groups=GROUP_MANAGER,
    )
    execution_error_public = fields.Text(
        string="Execution Error",
        readonly=True,
        copy=False,
    )
    executed_at = fields.Datetime(readonly=True, copy=False)
    last_event_sequence = fields.Integer(default=0, required=True, readonly=True)
    node_ids = fields.One2many(
        "occ.approval.instance.node", "instance_id", readonly=True
    )
    task_ids = fields.One2many("occ.approval.task", "instance_id", readonly=True)
    event_ids = fields.One2many("occ.approval.event", "instance_id", readonly=True)

    _active_source_unique = models.UniqueIndex(
        "(source_model, source_res_id) WHERE state IN ('draft', 'running', 'rework') "
        "OR (state = 'approved' AND execution_state IN ('pending', 'running', 'failed'))",
        "Only one unfinished approval instance may exist for a source record.",
    )
    _source_res_id_positive = models.Constraint(
        "CHECK(source_res_id > 0)", "The source record id must be positive."
    )
    _event_sequence_nonnegative = models.Constraint(
        "CHECK(last_event_sequence >= 0)", "The event sequence cannot be negative."
    )

    @api.model_create_multi
    def create(self, vals_list):
        self._assert_service_mutation()
        return super().create(vals_list)

    def write(self, vals):
        self._assert_service_mutation()
        return super().write(vals)

    def unlink(self):
        self._assert_service_mutation()
        return super().unlink()

    def _assert_service_mutation(self):
        if not self.env.su:
            raise AccessError(
                _("Approval instances can only be mutated through the approval service.")
            )

    def _engine(self):
        from ..services.engine import ApprovalEngine

        return ApprovalEngine(self.env)

    @api.model
    def _assert_execution_capability(self, source_record, action_key):
        return self._engine()._assert_execution_capability(
            source_record, action_key
        )

    @api.model
    def get_dashboard_summary(self):
        return self._engine().get_dashboard_summary()

    @api.model
    def get_dashboard_data(self):
        return self.get_dashboard_summary()

    @api.model
    def get_record_state(self, res_model, res_id):
        return self._engine().get_record_state(res_model, res_id)

    @api.model
    def get_panel_data(self, res_model=None, res_id=None, instance_id=None):
        return self._engine().get_panel_data(
            instance_id=instance_id, res_model=res_model, res_id=res_id
        )

    @api.model
    def get_supported_models(self, query=None, limit=100):
        """Return models with a published workflow or a readable history.

        Keeping runtime models in this capability list ensures that an existing
        approval remains reachable from its source form after the workflow is
        archived.  The runtime side is evaluated without sudo so record rules
        preserve the caller's company and participation boundaries.
        """
        safe_limit = min(max(int(limit or 100), 1), 500)
        result = self.env["occ.approval.workflow"].get_supported_models(
            query=query, limit=500
        )
        seen = {item["model"] for item in result}
        runtime_model_names = {
            model_name
            for (model_name,) in self._read_group([], ["source_model"])
            if model_name and model_name not in seen
        }
        if runtime_model_names:
            model_domain = [("model", "in", sorted(runtime_model_names))]
            if query:
                model_domain += [
                    "|",
                    ("name", "ilike", query),
                    ("model", "ilike", query),
                ]
            runtime_models = self.env["ir.model"].sudo().search(
                model_domain, order="name, model"
            )
            result.extend(
                {
                    "id": model.id,
                    "name": model.name,
                    "model": model.model,
                }
                for model in runtime_models
            )
        return result[:safe_limit]

    @api.model
    def get_record_panel(self, res_model, res_id):
        return self.get_panel_data(res_model=res_model, res_id=res_id)

    @api.model
    def create_for_record(self, res_model, res_id, workflow_id=None, values=None):
        """Public RPC boundary: interactive users may only start manual approvals."""
        values = dict(values or {})
        if values.get("action_key") not in (None, "", "manual"):
            raise AccessError(
                _("Non-manual approvals can only be started by a business connector.")
            )
        values["action_key"] = "manual"
        return self._engine().create_for_record(
            res_model,
            res_id,
            workflow_id=workflow_id,
            values=values,
            allow_non_manual=False,
        )

    @api.model
    def _create_for_record(self, res_model, res_id, workflow_id=None, values=None):
        """Private Python connector entry point; underscore methods are not RPC-callable."""
        return self._engine().create_for_record(
            res_model,
            res_id,
            workflow_id=workflow_id,
            values=values or {},
            allow_non_manual=True,
        )

    @api.model
    def request(self, res_model, res_id, workflow_id=None, draft_assignees=None):
        values = {"draft_assignees": draft_assignees or {}}
        return self.create_for_record(res_model, res_id, workflow_id, values)

    @api.model
    def submit(self, instance_id):
        return self._engine().submit(instance_id)

    @api.model
    def cancel_submission(self, instance_id, reason=None):
        return self._engine().cancel_submission(instance_id, reason=reason)

    @api.model
    def cancel_instance(self, instance_id, reason=None):
        return self._engine().cancel_instance(instance_id, reason=reason)

    @api.model
    def cancel(self, instance_id, reason=None):
        return self.cancel_instance(instance_id, reason=reason)

    @api.model
    def approve_task(self, task_id, values=None):
        return self._engine().approve_task(task_id, values=values or {})

    @api.model
    def approve(self, task_id, comment=None):
        return self.approve_task(task_id, {"comment": comment or ""})

    @api.model
    def reject_task(self, task_id, values=None):
        return self._engine().reject_task(task_id, values=values or {})

    @api.model
    def reject(self, task_id, target_node_id, mode="sequential", comment=None):
        return self.reject_task(
            task_id,
            {
                "target_node_id": target_node_id,
                "mode": mode,
                "comment": comment or "",
            },
        )

    @api.model
    def revoke_task(self, task_id, values=None):
        return self._engine().revoke_task(task_id, values=values or {})

    @api.model
    def withdraw(self, task_id, comment=None):
        return self.revoke_task(task_id, {"comment": comment or ""})

    @api.model
    def remind(self, instance_id, values=None):
        return self._engine().remind(instance_id, values=values or {})

    @api.model
    def search_assignable_users(self, task_id, query=None, limit=50):
        return self._engine().search_assignable_users(task_id, query=query, limit=limit)

    @api.model
    def set_task_users(self, task_id, user_ids):
        return self._engine().set_task_users(task_id, user_ids)

    @api.model
    def set_draft_assignees(self, instance_id, node_id, user_ids):
        return self._engine().set_draft_assignees(instance_id, node_id, user_ids)

    @api.model
    def retry_execution(self, instance_id):
        return self._engine().retry_execution(instance_id)

    @api.model
    def open_document(self, instance_id):
        return self._engine().open_document(instance_id)

    def action_open_document(self):
        self.ensure_one()
        return self._engine().open_document(self.id)

    def action_cancel_instance(self):
        self.ensure_one()
        self._engine().cancel_instance(self.id)
        return {"type": "ir.actions.client", "tag": "reload"}


class OccApprovalInstanceNode(models.Model):
    _name = "occ.approval.instance.node"
    _table = "occ_approval_v2_instance_node"
    _description = "Approval Instance Node V2"
    _order = "sequence, id"
    _check_company_auto = True

    instance_id = fields.Many2one(
        "occ.approval.instance",
        required=True,
        index=True,
        ondelete="cascade",
        check_company=True,
    )
    company_id = fields.Many2one(
        "res.company", required=True, index=True, ondelete="restrict"
    )
    node_key = fields.Char(required=True, index=True, readonly=True)
    name = fields.Char(required=True, readonly=True)
    node_type = fields.Selection(
        [
            ("start", "Start"),
            ("approval", "Approval"),
            ("task", "Task"),
            ("copy", "Copy"),
            ("end", "End"),
        ],
        required=True,
        index=True,
        readonly=True,
    )
    sequence = fields.Integer(required=True, index=True, readonly=True)
    definition = fields.Json(required=True, readonly=True)
    assignment_type = fields.Selection(
        [
            ("users", "Specified Users"),
            ("role", "Role"),
            ("manager", "Manager"),
            ("manager_chain", "Manager Chain"),
            ("requester", "Requester"),
            ("requester_choice", "Requester Choice"),
        ],
        readonly=True,
    )
    approval_mode = fields.Selection(
        [("all", "All"), ("any", "Any")], readonly=True
    )
    state = fields.Selection(
        [
            ("waiting", "Waiting"),
            ("active", "Active"),
            ("approved", "Approved"),
            ("completed", "Completed"),
            ("rejected", "Rejected"),
            ("skipped", "Skipped"),
            ("cancelled", "Cancelled"),
        ],
        default="waiting",
        required=True,
        index=True,
        readonly=True,
    )
    attempt = fields.Integer(default=0, required=True, readonly=True)
    visit_count = fields.Integer(default=0, required=True, readonly=True)
    draft_assignee_user_ids = fields.Many2many(
        "res.users",
        "occ_approval_v2_node_draft_user_rel",
        "node_id",
        "user_id",
        string="Requester Selected Users",
        readonly=True,
    )
    entered_at = fields.Datetime(readonly=True, copy=False)
    deadline_at = fields.Datetime(readonly=True, copy=False, index=True)
    automatic_reminder_at = fields.Datetime(readonly=True, copy=False, index=True)
    reminder_sent_at = fields.Datetime(readonly=True, copy=False)
    manual_reminder_sent_at = fields.Datetime(readonly=True, copy=False)
    timeout_processed_at = fields.Datetime(readonly=True, copy=False)
    completed_at = fields.Datetime(readonly=True, copy=False)
    timeout_action = fields.Selection(
        [("none", "None"), ("approve", "Approve"), ("reject", "Reject")],
        default="none",
        required=True,
        readonly=True,
    )
    task_ids = fields.One2many("occ.approval.task", "node_id", readonly=True)

    _instance_node_key_unique = models.UniqueIndex(
        "(instance_id, node_key)", "Node keys must be unique within an instance."
    )
    _node_counts_nonnegative = models.Constraint(
        "CHECK(attempt >= 0 AND visit_count >= 0)",
        "Node attempt counters cannot be negative.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        self._assert_service_mutation()
        return super().create(vals_list)

    def write(self, vals):
        self._assert_service_mutation()
        return super().write(vals)

    def unlink(self):
        self._assert_service_mutation()
        return super().unlink()

    def _assert_service_mutation(self):
        if not self.env.su:
            raise AccessError(
                _("Approval nodes can only be mutated through the approval service.")
            )


class OccApprovalTask(models.Model):
    _name = "occ.approval.task"
    _description = "Approval User Task"
    _order = "state, deadline_at, id"
    _check_company_auto = True

    instance_id = fields.Many2one(
        "occ.approval.instance",
        required=True,
        index=True,
        ondelete="cascade",
        check_company=True,
    )
    node_id = fields.Many2one(
        "occ.approval.instance.node",
        required=True,
        index=True,
        ondelete="cascade",
        check_company=True,
    )
    company_id = fields.Many2one(
        "res.company", required=True, index=True, ondelete="restrict"
    )
    workflow_id = fields.Many2one(
        "occ.approval.workflow",
        related="instance_id.workflow_id",
        store=True,
        index=True,
        readonly=True,
    )
    user_id = fields.Many2one(
        "res.users", required=True, index=True, ondelete="restrict"
    )
    task_kind = fields.Selection(
        [("approval", "Approval"), ("task", "Task"), ("copy", "Copy")],
        required=True,
        index=True,
        readonly=True,
    )
    attempt = fields.Integer(required=True, default=1, readonly=True)
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("completed", "Completed"),
            ("rejected", "Rejected"),
            ("copied", "Copied"),
            ("cancelled", "Cancelled"),
        ],
        default="pending",
        required=True,
        index=True,
        readonly=True,
    )
    assigned_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    deadline_at = fields.Datetime(index=True, readonly=True)
    acted_at = fields.Datetime(index=True, readonly=True, copy=False)
    acted_by_id = fields.Many2one("res.users", readonly=True, ondelete="set null")
    comment = fields.Text(readonly=True, copy=False)
    reminder_sent_at = fields.Datetime(readonly=True, copy=False)

    _node_user_attempt_unique = models.UniqueIndex(
        "(node_id, user_id, attempt, task_kind)",
        "A user can only have one task per node attempt.",
    )
    _task_attempt_positive = models.Constraint(
        "CHECK(attempt > 0)", "Task attempts must be positive."
    )

    @api.model_create_multi
    def create(self, vals_list):
        self._assert_service_mutation()
        return super().create(vals_list)

    def write(self, vals):
        self._assert_service_mutation()
        return super().write(vals)

    def unlink(self):
        self._assert_service_mutation()
        return super().unlink()

    def _assert_service_mutation(self):
        if not self.env.su:
            raise AccessError(
                _("Approval tasks can only be mutated through the approval service.")
            )

    @api.model
    def cron_process_deadlines(self):
        from ..services.engine import ApprovalEngine

        if not (
            self.env.su
            or self.env.user.has_group(GROUP_TECHNICAL)
            or self.env.user.has_group(GROUP_MANAGER)
        ):
            raise AccessError(_("Only the approval scheduler can process deadlines."))
        return ApprovalEngine(self.env).cron_process_deadlines()


class OccApprovalEvent(models.Model):
    _name = "occ.approval.event"
    _description = "Append-only Approval Event"
    _order = "instance_id, sequence"
    _check_company_auto = True

    instance_id = fields.Many2one(
        "occ.approval.instance",
        required=True,
        index=True,
        ondelete="cascade",
        check_company=True,
    )
    node_id = fields.Many2one(
        "occ.approval.instance.node",
        index=True,
        ondelete="set null",
        check_company=True,
    )
    task_id = fields.Many2one(
        "occ.approval.task", index=True, ondelete="set null", check_company=True
    )
    company_id = fields.Many2one(
        "res.company", required=True, index=True, ondelete="restrict"
    )
    sequence = fields.Integer(required=True, index=True, readonly=True)
    event_type = fields.Char(required=True, index=True, readonly=True)
    actor_id = fields.Many2one(
        "res.users", index=True, readonly=True, ondelete="set null"
    )
    occurred_at = fields.Datetime(
        required=True, default=fields.Datetime.now, index=True, readonly=True
    )
    from_state = fields.Char(readonly=True)
    to_state = fields.Char(readonly=True)
    payload = fields.Json(default=dict, readonly=True)

    _instance_event_sequence_unique = models.UniqueIndex(
        "(instance_id, sequence)", "Approval event sequences must be unique per instance."
    )
    _event_sequence_positive = models.Constraint(
        "CHECK(sequence > 0)", "Approval event sequences must be positive."
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not (self.env.su and self.env.context.get("occ_approval_append_event")):
            raise AccessError(_("Approval events can only be appended by the approval service."))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_("Approval events are append-only."))

    def unlink(self):
        if self.env.context.get("module_uninstall"):
            return super().unlink()
        raise AccessError(_("Approval events are append-only."))
