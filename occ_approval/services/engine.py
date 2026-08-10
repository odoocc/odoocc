import logging
from datetime import timedelta

from psycopg2.errors import UniqueViolation

from odoo import _
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from odoo.fields import Domain

from .definition import ApprovalDefinitionService, REJECT_MODES


_logger = logging.getLogger(__name__)

GROUP_USER = "occ_approval.group_approval_user"
GROUP_MANAGER = "occ_approval.group_approval_manager"
GROUP_TECHNICAL = "occ_approval.group_approval_technical"
ACTIVE_INSTANCE_STATES = ("draft", "running", "rework")
BLOCKING_EXECUTION_STATES = ("pending", "running", "failed")
OPEN_NODE_STATES = ("waiting", "active")
ACTION_NODE_TYPES = ("approval", "task")
EXECUTION_CAPABILITY = object()


class ApprovalEngine:
    """Transactional approval runtime.

    Every public entry point validates the actor and source record.  Every
    mutation locks the instance row and writes runtime records in sudo mode;
    callers cannot mutate runtime tables directly.
    """

    def __init__(self, env):
        self.env = env

    # ------------------------------------------------------------------
    # Access and lookup helpers
    # ------------------------------------------------------------------

    def _check_user_group(self):
        if not (
            self.env.su
            or self.env.user.has_group(GROUP_USER)
            or self.env.user.has_group(GROUP_MANAGER)
            or self.env.user.has_group(GROUP_TECHNICAL)
        ):
            raise AccessError(_("Approval user access is required."))

    def _is_manager(self):
        return bool(
            self.env.su
            or self.env.user.has_group(GROUP_MANAGER)
            or self.env.user.has_group(GROUP_TECHNICAL)
        )

    def _is_technical(self):
        return bool(self.env.su or self.env.user.has_group(GROUP_TECHNICAL))

    def _check_company(self, company):
        if not self.env.su and company not in self.env.companies:
            raise AccessError(_("The approval record belongs to an unavailable company."))

    def _source_record(self, model_name, res_id, operation="read", *, sudo=False):
        if not isinstance(model_name, str) or model_name not in self.env:
            raise ValidationError(_("Unsupported source model."))
        if model_name.startswith("occ.approval."):
            raise ValidationError(_("Approval runtime records cannot be approval sources."))
        try:
            res_id = int(res_id)
        except (TypeError, ValueError) as error:
            raise ValidationError(_("Invalid source record id.")) from error
        if res_id <= 0:
            raise ValidationError(_("Invalid source record id."))

        record = self.env[model_name].browse(res_id).exists()
        if not record:
            raise MissingError(_("The source record no longer exists."))
        record.check_access(operation)
        return record.sudo() if sudo else record

    def _source_company(self, record):
        company = self.env.company
        if "company_id" in record._fields and record.company_id:
            company = record.company_id
        self._check_company(company)
        return company

    @staticmethod
    def _instance_source_company_matches(instance, record):
        return not (
            "company_id" in record._fields
            and record.company_id
            and record.company_id != instance.company_id
        )

    @classmethod
    def _assert_instance_source_company(cls, instance, record):
        if not cls._instance_source_company_matches(instance, record):
            raise ValidationError(
                _(
                    "The source record changed company after this approval started. Cancel it and start a new approval."
                )
            )

    def _instance_for_actor(
        self,
        instance_id,
        *,
        operation="read",
        require_participant=True,
        allow_source_company_mismatch=False,
    ):
        self._check_user_group()
        instance = self.env["occ.approval.instance"].sudo().browse(instance_id).exists()
        if not instance:
            raise MissingError(_("Approval instance not found."))
        self._check_company(instance.company_id)
        record = self._source_record(
            instance.source_model, instance.source_res_id, operation
        )
        if not allow_source_company_mismatch:
            self._assert_instance_source_company(instance, record)
        if (
            require_participant
            and not self._is_manager()
            and self.env.user != instance.requester_id
            and self.env.user not in instance.participant_user_ids
        ):
            raise AccessError(_("You are not a participant of this approval instance."))
        return instance

    def _instance_for_cancellation(self, instance_id):
        """Load an instance for fail-safe cancellation without trusting its source.

        A source record may have moved company or been deleted.  Cancellation
        only closes approval runtime rows, so it must remain available while
        company scope and actor authorization are still enforced separately.
        """
        self._check_user_group()
        instance = self.env["occ.approval.instance"].sudo().browse(instance_id).exists()
        if not instance:
            raise MissingError(_("Approval instance not found."))
        self._check_company(instance.company_id)
        return instance

    @staticmethod
    def _instance_blocks_new_request(instance):
        return bool(
            instance
            and (
                instance.state in ACTIVE_INSTANCE_STATES
                or (
                    instance.state == "approved"
                    and instance.execution_state in BLOCKING_EXECUTION_STATES
                )
            )
        )

    def _assert_execution_capability(self, record, action_key):
        """Verify the unforgeable, transaction-local connector capability."""
        record.ensure_one()
        context = record.env.context
        if context.get("occ_approval_execution_capability") is not EXECUTION_CAPABILITY:
            raise AccessError(_("A valid approval execution capability is required."))
        try:
            instance_id = int(context.get("occ_approval_instance_id") or 0)
        except (TypeError, ValueError) as error:
            raise AccessError(_("A valid approval execution capability is required.")) from error
        instance = (
            record.env["occ.approval.instance"].sudo().browse(instance_id).exists()
        )
        allowed_company_ids = context.get("allowed_company_ids") or []
        try:
            allowed_company_ids = [int(company_id) for company_id in allowed_company_ids]
        except (TypeError, ValueError) as error:
            raise AccessError(_("A valid approval execution capability is required.")) from error
        if (
            not instance
            or instance.state != "approved"
            or instance.execution_state != "running"
            or instance.source_model != record._name
            or instance.source_res_id != record.id
            or instance.action_key != action_key
            or instance.requester_id != record.env.user
            or record.env.company != instance.company_id
            or allowed_company_ids != [instance.company_id.id]
            or not self._instance_source_company_matches(instance, record)
        ):
            raise AccessError(_("The approval execution capability does not match this action."))
        return instance

    def _task_for_actor(self, task_id, *, acted=False):
        self._check_user_group()
        task = self.env["occ.approval.task"].sudo().browse(task_id).exists()
        if not task:
            raise MissingError(_("Approval task not found."))
        instance = self._instance_for_actor(task.instance_id.id, operation="read")
        if task.user_id != self.env.user:
            raise AccessError(_("Only the assigned user can process this task."))
        if acted and task.state == "pending":
            raise UserError(_("This task has not been processed yet."))
        return task, instance

    def _lock_instance(self, instance_id):
        self.env.cr.execute(
            "SELECT id FROM occ_approval_v2_instance WHERE id = %s FOR UPDATE",
            (int(instance_id),),
        )
        if not self.env.cr.fetchone():
            raise MissingError(_("Approval instance not found."))
        instance = self.env["occ.approval.instance"].sudo().browse(instance_id)
        instance.invalidate_recordset()
        return instance

    def _lock_workflow(self, workflow):
        workflow.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM occ_approval_workflow WHERE id = %s FOR SHARE",
            (workflow.id,),
        )
        if not self.env.cr.fetchone():
            raise MissingError(_("Approval workflow not found."))
        workflow.invalidate_recordset(
            [
                "company_id",
                "model_name",
                "active",
                "state",
                "published_version_id",
            ]
        )
        return workflow

    def _lock_and_refresh_task(self, task_id):
        task = self.env["occ.approval.task"].sudo().browse(task_id).exists()
        if not task:
            raise MissingError(_("Approval task not found."))
        instance = self._lock_instance(task.instance_id.id)
        task.invalidate_recordset()
        task.node_id.invalidate_recordset()
        return task, instance

    # ------------------------------------------------------------------
    # Event and serialization helpers
    # ------------------------------------------------------------------

    def _append_event(
        self,
        instance,
        event_type,
        *,
        node=None,
        task=None,
        from_state=None,
        to_state=None,
        payload=None,
        actor_id=None,
    ):
        sequence = instance.last_event_sequence + 1
        instance.sudo().write({"last_event_sequence": sequence})
        return self.env["occ.approval.event"].with_context(
            occ_approval_append_event=True
        ).sudo().create(
            {
                "instance_id": instance.id,
                "node_id": node.id if node else False,
                "task_id": task.id if task else False,
                "company_id": instance.company_id.id,
                "sequence": sequence,
                "event_type": event_type,
                "actor_id": actor_id if actor_id is not None else self.env.user.id,
                "from_state": from_state or False,
                "to_state": to_state or False,
                "payload": payload or {},
            }
        )

    def _serialize_instance(self, instance):
        execution_error = (
            instance.execution_error
            if self._is_manager()
            else instance.execution_error_public
        )
        if instance.execution_state == "failed" and not execution_error:
            execution_error = _(
                "Business execution failed. Contact an approval administrator."
            )
        return {
            "id": instance.id,
            "name": instance.name,
            "company_id": instance.company_id.id,
            "workflow_id": instance.workflow_id.id,
            "workflow_name": instance.workflow_id.name,
            "workflow_version_id": instance.workflow_version_id.id,
            "workflow_version": instance.workflow_version_id.version,
            "action_key": instance.action_key,
            "source_model": instance.source_model,
            "source_res_id": instance.source_res_id,
            "source_display_name": instance.source_display_name,
            "requester_id": instance.requester_id.id,
            "requester_name": instance.requester_id.name,
            "participant_user_ids": instance.participant_user_ids.ids,
            "state": instance.state,
            "display_state": self._display_state(instance.state),
            "last_decision": instance.last_decision,
            "current_node_id": instance.current_node_id.id,
            "return_node_id": instance.return_node_id.id,
            "submitted_at": instance.submitted_at,
            "completed_at": instance.completed_at,
            "cancelled_at": instance.cancelled_at,
            "execution_state": instance.execution_state,
            "execution_attempts": instance.execution_attempts,
            "execution_error": execution_error or "",
            "executed_at": instance.executed_at,
        }

    @staticmethod
    def _operation_comment(values):
        return values.get("comment") or values.get("opinion") or ""

    @staticmethod
    def _display_state(state):
        labels = {
            "not_created": "Not created",
            "draft": "Draft",
            "waiting": "Waiting",
            "active": "Active",
            "running": "Running",
            "rework": "Rework",
            "pending": "Pending",
            "approved": "Approved",
            "completed": "Completed",
            "rejected": "Rejected",
            "copied": "Copied",
            "cancelled": "Cancelled",
            "skipped": "Skipped",
            "failed": "Failed",
        }
        return labels.get(state, state)

    @staticmethod
    def _serialize_users(users, *, state_by_user=None):
        state_by_user = state_by_user or {}
        return [
            {
                "id": user.id,
                "user_id": user.id,
                "name": user.name,
                "user_name": user.name,
                "state": state_by_user.get(user.id, ""),
            }
            for user in users
        ]

    @staticmethod
    def _notify_users(users, *, title, message, notification_type="info"):
        users.sudo()._bus_send(
            "simple_notification",
            {
                "title": title,
                "message": message,
                "type": notification_type,
                "sticky": False,
            },
        )

    def _reject_targets(self, node):
        return node.instance_id.node_ids.filtered(
            lambda candidate: candidate.sequence < node.sequence
            and candidate.visit_count > 0
            and candidate.node_type not in ("copy", "end")
        )

    def _can_revoke_task(self, task, actor):
        instance = task.instance_id
        node = task.node_id
        if (
            task.user_id != actor
            or task.state not in ("approved", "completed")
            or instance.state != "running"
            or task.attempt != node.attempt
        ):
            return False
        if instance.current_node_id == node and node.state == "active":
            return task.attempt == node.attempt
        later_acted = instance.task_ids.filtered(
            lambda item: item.node_id.sequence > node.sequence
            and item.state in ("approved", "completed", "rejected", "copied")
        )
        if later_acted:
            return False
        current = instance.current_node_id
        if not current or current.sequence <= node.sequence:
            return False
        current_tasks = current.task_ids.filtered(
            lambda item: item.attempt == current.attempt
        )
        return bool(current_tasks) and all(
            item.state == "pending" for item in current_tasks
        )

    def _task_actions(self, task, actor, *, allow_actions=True):
        if not allow_actions:
            return {
                "approve": False,
                "reject": False,
                "revoke": False,
                "set_users": False,
                "choose_users": False,
            }
        node = task.node_id
        instance = task.instance_id
        open_for_actor = (
            task.user_id == actor
            and task.state == "pending"
            and task.task_kind in ACTION_NODE_TYPES
            and instance.state in ("running", "rework")
            and instance.current_node_id == node
            and node.state == "active"
            and task.attempt == node.attempt
        )
        return {
            "approve": open_for_actor,
            "reject": open_for_actor and bool(self._reject_targets(node)),
            "revoke": self._can_revoke_task(task, actor),
            "set_users": False,
            "choose_users": False,
        }

    def _serialize_node(self, node, actor, *, allow_actions=True):
        current_tasks = node.task_ids.filtered(lambda task: task.attempt == node.attempt)
        actor_tasks = current_tasks.filtered(lambda task: task.user_id == actor)
        reject_targets = self._reject_targets(node)
        task_states = {task.user_id.id: task.state for task in current_tasks}
        return {
            "id": node.id,
            "key": node.node_key,
            "name": node.name,
            "type": node.node_type,
            "sequence": node.sequence,
            "state": node.state,
            "display_state": self._display_state(node.state),
            "attempt": node.attempt,
            "visit_count": node.visit_count,
            "assignment_type": node.assignment_type,
            "mode": node.approval_mode,
            "draft_assignee_user_ids": node.draft_assignee_user_ids.ids,
            "entered_at": node.entered_at,
            "deadline_at": node.deadline_at,
            "reminder_sent_at": node.reminder_sent_at,
            "manual_reminder_sent_at": node.manual_reminder_sent_at,
            "completed_at": node.completed_at,
            "tasks": [
                self._serialize_task(
                    task, actor=actor, allow_actions=allow_actions
                )
                for task in current_tasks
            ],
            "actors": self._serialize_users(
                current_tasks.user_id, state_by_user=task_states
            ),
            "actor_task_ids": actor_tasks.ids,
            "reject_targets": [
                {"id": target.id, "key": target.node_key, "name": target.name}
                for target in reject_targets
            ],
        }

    def _serialize_task(self, task, *, actor=None, allow_actions=True):
        actor = actor or self.env.user
        node = task.node_id
        attempt_tasks = node.task_ids.filtered(
            lambda item: item.attempt == task.attempt
        )
        task_states = {item.user_id.id: item.state for item in attempt_tasks}
        reject_targets = self._reject_targets(node)
        return {
            "id": task.id,
            "task_id": task.id,
            "instance_id": task.instance_id.id,
            "instance_name": task.instance_id.name,
            "source_model": task.instance_id.source_model,
            "source_res_id": task.instance_id.source_res_id,
            "source_display_name": task.instance_id.source_display_name,
            "workflow_name": task.instance_id.workflow_id.name,
            "node_id": task.node_id.id,
            "name": node.name,
            "node_name": node.name,
            "node_type": node.node_type,
            "user_id": task.user_id.id,
            "user_name": task.user_id.name,
            "kind": task.task_kind,
            "attempt": task.attempt,
            "state": task.state,
            "display_state": self._display_state(task.state),
            "assigned_at": task.assigned_at,
            "deadline_at": task.deadline_at,
            "acted_at": task.acted_at,
            "acted_by_id": task.acted_by_id.id,
            "comment": task.comment or "",
            "assignees": self._serialize_users(
                attempt_tasks.user_id, state_by_user=task_states
            ),
            "available_revert_nodes": [
                {"id": target.id, "node_id": target.id, "name": target.name}
                for target in reject_targets
            ],
            "actions": self._task_actions(
                task, actor, allow_actions=allow_actions
            ),
        }

    def _serialize_assignment_task(self, node, actor, *, allow_actions=True):
        can_set_users = (
            allow_actions
            and
            node.assignment_type == "requester_choice"
            and node.state == "waiting"
            and node.instance_id.state in ACTIVE_INSTANCE_STATES
            and (actor == node.instance_id.requester_id or self._is_manager())
        )
        selected_users = node.draft_assignee_user_ids
        return {
            "id": f"node:{node.id}",
            "task_id": f"node:{node.id}",
            "node_id": node.id,
            "name": node.name,
            "node_name": node.name,
            "node_type": node.node_type,
            "kind": "assignment",
            "state": "waiting",
            "display_state": _("Assignees selected")
            if selected_users
            else _("Assignees required"),
            "description": _("Choose assignees before this node is entered."),
            "assignees": self._serialize_users(selected_users),
            "available_revert_nodes": [],
            "actions": {
                "approve": False,
                "reject": False,
                "revoke": False,
                "set_users": can_set_users,
                "choose_users": can_set_users,
            },
        }

    @staticmethod
    def _serialize_event(event):
        return {
            "id": event.id,
            "sequence": event.sequence,
            "type": event.event_type,
            "node_id": event.node_id.id,
            "task_id": event.task_id.id,
            "actor_id": event.actor_id.id,
            "actor_name": event.actor_id.name,
            "occurred_at": event.occurred_at,
            "from_state": event.from_state or "",
            "to_state": event.to_state or "",
            "payload": event.payload or {},
        }

    def _terminal_instance_payload(self, instance):
        """Serialize a closed instance without depending on its source record."""
        actor = self.env.user
        actions = {
            "can_create": False,
            "can_submit": False,
            "can_cancel_submission": False,
            "can_remind": False,
            "can_cancel_instance": False,
            "can_retry_execution": False,
        }
        return {
            "enabled": True,
            "instance": self._serialize_instance(instance),
            "state": instance.state,
            "display_state": self._display_state(instance.state),
            "nodes": [
                self._serialize_node(node, actor, allow_actions=False)
                for node in instance.node_ids.sorted("sequence")
            ],
            "events": [
                self._serialize_event(event)
                for event in instance.event_ids.sorted("sequence")[-100:]
            ],
            "tasks": [],
            "available_revert_nodes": [],
            "workflows": [],
            "source_company_mismatch": False,
            "actions": actions,
            "permissions": {**actions, "can_request": False, "pending_task_ids": []},
        }

    # ------------------------------------------------------------------
    # Workflow matching and read APIs
    # ------------------------------------------------------------------

    def _matching_workflows(self, record, company, *, action_key=None):
        workflows = self.env["occ.approval.workflow"].sudo().search(
            [
                ("company_id", "=", company.id),
                ("state", "=", "published"),
                ("active", "=", True),
                ("published_version_id", "!=", False),
            ],
            order="priority desc, id",
        )
        matched = []
        record_sudo = record.sudo()
        for workflow in workflows:
            version = workflow.published_version_id
            if version.model_name != record._name or (
                action_key is not None and version.action_key != action_key
            ):
                continue
            domain = version.applicability_domain or []
            if domain and not record_sudo.filtered_domain(Domain(domain)):
                continue
            matched.append(workflow)
        return self.env["occ.approval.workflow"].sudo().browse(
            [workflow.id for workflow in matched]
        )

    def get_record_state(self, res_model, res_id):
        self._check_user_group()
        record = self._source_record(res_model, res_id, "read")
        company = self._source_company(record)
        instance = self.env["occ.approval.instance"].search(
            [
                ("source_model", "=", res_model),
                ("source_res_id", "=", int(res_id)),
            ],
            order="id desc",
            limit=1,
        )
        workflows = self._matching_workflows(record, company)
        manual_workflows = workflows.filtered(
            lambda workflow: workflow.published_version_id.action_key == "manual"
        )
        return {
            "enabled": bool(workflows or instance),
            "state": instance.state if instance else "none",
            "instance_id": instance.id,
            "workflow_ids": workflows.ids,
            "can_request": bool(manual_workflows)
            and self._can_write_source(record)
            and not self._instance_blocks_new_request(instance),
        }

    def get_panel_data(self, *, instance_id=None, res_model=None, res_id=None):
        self._check_user_group()
        if instance_id:
            instance = self._instance_for_actor(
                instance_id,
                operation="read",
                allow_source_company_mismatch=True,
            )
            record = self._source_record(
                instance.source_model, instance.source_res_id, "read"
            )
            company = self._source_company(record)
        else:
            if not res_model or not res_id:
                raise ValidationError(_("Provide an instance or source record."))
            record = self._source_record(res_model, res_id, "read")
            company = self._source_company(record)
            instance = self.env["occ.approval.instance"].search(
                [
                    ("source_model", "=", res_model),
                    ("source_res_id", "=", int(res_id)),
                ],
                order="id desc",
                limit=1,
            )
            if instance:
                self._check_company(instance.company_id)
        source_company_mismatch = bool(
            instance
            and not self._instance_source_company_matches(instance, record)
        )
        workflows = self._matching_workflows(record, company)
        manual_workflows = workflows.filtered(
            lambda workflow: workflow.published_version_id.action_key == "manual"
        )
        can_write_source = self._can_write_source(record)
        workflow_choices = [
            {
                "id": workflow.id,
                "name": workflow.name,
                "action_key": workflow.published_version_id.action_key,
            }
            for workflow in workflows
        ]
        if not instance:
            can_create = bool(manual_workflows) and can_write_source
            return {
                "enabled": bool(workflows),
                "instance": None,
                "state": "not_created",
                "display_state": self._display_state("not_created"),
                "nodes": [],
                "events": [],
                "tasks": [],
                "available_revert_nodes": [],
                "workflows": workflow_choices,
                "source_company_mismatch": False,
                "actions": {
                    "can_create": can_create,
                    "can_submit": False,
                    "can_cancel_submission": False,
                    "can_remind": False,
                    "can_cancel_instance": False,
                    "can_retry_execution": False,
                },
                "permissions": {"can_request": can_create},
            }

        actor = self.env.user
        pending_actor_tasks = instance.task_ids.filtered(
            lambda task: task.user_id == actor and task.state == "pending"
        )
        can_manage = self._is_manager()
        start_node_ready = (
            instance.current_node_id
            and instance.current_node_id.node_type == "start"
            and instance.current_node_id.state == "active"
        )
        acted_tasks = instance.task_ids.filtered(
            lambda task: task.task_kind in ACTION_NODE_TYPES
            and task.state in ("approved", "completed", "rejected")
        )
        current_node = instance.current_node_id
        current_pending = (
            current_node.task_ids.filtered(
                lambda task: task.attempt == current_node.attempt
                and task.state == "pending"
            )
            if current_node
            else self.env["occ.approval.task"].sudo().browse()
        )
        can_remind = bool(
            current_node
            and current_node.node_type in ACTION_NODE_TYPES
            and current_node.state == "active"
            and current_pending
            and not current_node.manual_reminder_sent_at
            and (actor == instance.requester_id or can_manage)
        )
        can_create = bool(
            not self._instance_blocks_new_request(instance)
            and manual_workflows
            and can_write_source
        )
        allow_runtime_actions = not source_company_mismatch
        actions = {
            "can_create": can_create,
            "can_submit": allow_runtime_actions
            and instance.state in ("draft", "rework")
            and start_node_ready
            and (actor == instance.requester_id or can_manage),
            "can_cancel_submission": allow_runtime_actions
            and instance.state in ("running", "rework")
            and not acted_tasks
            and (actor == instance.requester_id or can_manage),
            "can_remind": allow_runtime_actions and can_remind,
            "can_cancel_instance": instance.state in ACTIVE_INSTANCE_STATES
            and (actor == instance.requester_id or can_manage),
            "can_retry_execution": allow_runtime_actions
            and instance.execution_state == "failed"
            and can_manage,
        }
        permissions = {
            **actions,
            "can_request": can_create,
            "pending_task_ids": pending_actor_tasks.ids,
        }
        task_payloads = []
        for task in instance.task_ids.sorted("id"):
            if task.user_id != actor or task.task_kind not in ACTION_NODE_TYPES:
                continue
            payload = self._serialize_task(
                task, actor=actor, allow_actions=allow_runtime_actions
            )
            if any(payload["actions"].values()):
                task_payloads.append(payload)
        assignment_nodes = instance.node_ids.filtered(
            lambda node: node.assignment_type == "requester_choice"
            and node.state == "waiting"
        ).sorted("sequence")
        if actor == instance.requester_id or can_manage:
            task_payloads.extend(
                self._serialize_assignment_task(node, actor)
                if allow_runtime_actions
                else self._serialize_assignment_task(
                    node, actor, allow_actions=False
                )
                for node in assignment_nodes
            )
        revert_nodes_by_id = {}
        for task_payload in task_payloads:
            for target in task_payload.get("available_revert_nodes", []):
                revert_nodes_by_id[target["id"]] = target
        events = instance.event_ids.sorted("sequence")[-100:]
        node_payloads = [
            self._serialize_node(
                node, actor, allow_actions=allow_runtime_actions
            )
            for node in instance.node_ids.sorted("sequence")
        ]
        return {
            "enabled": True,
            "instance": self._serialize_instance(instance),
            "state": instance.state,
            "display_state": self._display_state(instance.state),
            "nodes": node_payloads,
            "events": [self._serialize_event(event) for event in events],
            "tasks": task_payloads,
            "available_revert_nodes": list(revert_nodes_by_id.values()),
            "workflows": workflow_choices,
            "source_company_mismatch": source_company_mismatch,
            "actions": actions,
            "permissions": permissions,
        }

    def _can_write_source(self, record):
        try:
            record.check_access("write")
        except AccessError:
            return False
        return True

    def get_dashboard_summary(self):
        self._check_user_group()
        company_domain = [] if self.env.su else [("company_id", "in", self.env.companies.ids)]
        pending_tasks = self.env["occ.approval.task"].sudo().search(
            company_domain
            + [
                ("user_id", "=", self.env.user.id),
                ("state", "=", "pending"),
                ("instance_id.state", "in", ("running", "rework")),
            ],
            order="deadline_at, id",
            limit=100,
        )
        my_instances = self.env["occ.approval.instance"].sudo().search(
            company_domain + [("requester_id", "=", self.env.user.id)],
            order="id desc",
            limit=100,
        )
        pending_tasks = pending_tasks.filtered(
            lambda task: self._can_read_source_safely(task.instance_id)
        )
        my_instances = my_instances.filtered(self._can_read_source_safely)
        now = self.env.cr.now()
        overdue = pending_tasks.filtered(
            lambda task: task.deadline_at and task.deadline_at < now
        )
        return {
            "counts": {
                "pending": len(pending_tasks),
                "overdue": len(overdue),
                "my_draft": len(my_instances.filtered(lambda item: item.state == "draft")),
                "my_running": len(
                    my_instances.filtered(lambda item: item.state in ("running", "rework"))
                ),
                "my_approved": len(my_instances.filtered(lambda item: item.state == "approved")),
                "execution_failed": len(
                    my_instances.filtered(lambda item: item.execution_state == "failed")
                ),
            },
            "pending_tasks": [self._serialize_task(task) for task in pending_tasks[:50]],
            "instances": [self._serialize_instance(item) for item in my_instances[:50]],
        }

    def _can_read_source_safely(self, instance):
        try:
            self._source_record(instance.source_model, instance.source_res_id, "read")
        except (AccessError, MissingError, ValidationError):
            return False
        return True

    # ------------------------------------------------------------------
    # Instance creation and draft assignment
    # ------------------------------------------------------------------

    def create_for_record(
        self,
        res_model,
        res_id,
        *,
        workflow_id=None,
        values=None,
        allow_non_manual=False,
    ):
        self._check_user_group()
        values = values or {}
        requested_action_key = values.get("action_key") or "manual"
        if not isinstance(requested_action_key, str) or not requested_action_key.strip():
            raise ValidationError(_("Invalid approval action key."))
        requested_action_key = requested_action_key.strip()
        if requested_action_key != "manual" and not allow_non_manual:
            raise AccessError(
                _("Non-manual approvals can only be started by a business connector.")
            )
        record = self._source_record(res_model, res_id, "write")
        company = self._source_company(record)
        if workflow_id:
            try:
                workflow_id = int(workflow_id)
            except (TypeError, ValueError) as error:
                raise ValidationError(_("Invalid workflow id.")) from error
            workflows = self._matching_workflows(
                record, company, action_key=requested_action_key
            )
            workflow = workflows.filtered(lambda item: item.id == workflow_id)
            if not workflow:
                raise AccessError(_("The selected workflow cannot be used for this record."))
        else:
            workflows = self._matching_workflows(
                record, company, action_key=requested_action_key
            )
            workflow = workflows[:1]
        if not workflow:
            raise UserError(_("No published workflow matches this record."))
        workflow = self._lock_workflow(workflow)
        if (
            workflow.company_id != company
            or workflow.state != "published"
            or not workflow.active
            or not workflow.published_version_id
        ):
            raise UserError(_("The selected workflow is no longer available."))
        version = workflow.published_version_id
        version._assert_integrity()
        if (
            version.workflow_id != workflow
            or version.company_id != company
            or version.model_name != res_model
            or version.action_key != requested_action_key
        ):
            raise ValidationError(
                _(
                    "The selected workflow version is inconsistent. Contact an approval administrator."
                )
            )
        applicability_domain = version.applicability_domain or []
        if applicability_domain and not record.sudo().filtered_domain(
            Domain(applicability_domain)
        ):
            raise UserError(_("The selected workflow no longer applies to this record."))

        blocking_instance_domain = [
            ("source_model", "=", res_model),
            ("source_res_id", "=", int(res_id)),
            "|",
            ("state", "in", ACTIVE_INSTANCE_STATES),
            "&",
            ("state", "=", "approved"),
            ("execution_state", "in", BLOCKING_EXECUTION_STATES),
        ]
        existing = self.env["occ.approval.instance"].sudo().search(
            blocking_instance_domain, limit=1
        )
        if existing:
            raise UserError(_("An unfinished approval instance already exists."))

        try:
            with self.env.cr.savepoint():
                instance = self.env["occ.approval.instance"].sudo().create(
                    {
                        "company_id": company.id,
                        "workflow_id": workflow.id,
                        "workflow_version_id": version.id,
                        "action_key": version.action_key,
                        "source_model": res_model,
                        "source_res_id": int(res_id),
                        "source_display_name": record.display_name,
                        "requester_id": self.env.user.id,
                        "participant_user_ids": [(6, 0, [self.env.user.id])],
                        "state": "draft",
                        "execution_state": "pending" if version.auto_execute else "none",
                    }
                )
        except UniqueViolation:
            if self.env["occ.approval.instance"].sudo().search(
                blocking_instance_domain, limit=1
            ):
                raise UserError(_("An unfinished approval instance already exists.")) from None
            raise

        node_values = []
        for node_definition in version.definition["nodes"]:
            assignment = node_definition.get("assignment") or {}
            node_values.append(
                {
                    "instance_id": instance.id,
                    "company_id": company.id,
                    "node_key": node_definition["id"],
                    "name": node_definition["name"],
                    "node_type": node_definition["type"],
                    "sequence": node_definition["sequence"],
                    "definition": node_definition,
                    "assignment_type": assignment.get("type") or False,
                    "approval_mode": node_definition.get("mode") or False,
                    "timeout_action": node_definition.get("timeout_action", "none"),
                }
            )
        nodes = self.env["occ.approval.instance.node"].sudo().create(node_values)
        start_node = nodes.filtered(lambda node: node.node_type == "start").ensure_one()
        now = self.env.cr.now()
        start_node.sudo().write(
            {
                "state": "active",
                "attempt": 1,
                "visit_count": 1,
                "entered_at": now,
            }
        )
        instance.sudo().write({"current_node_id": start_node.id})
        self._lock_instance(instance.id)
        instance.invalidate_recordset()
        self._append_event(
            instance,
            "instance_requested",
            node=start_node,
            from_state="none",
            to_state="draft",
            payload={
                "workflow_version_id": version.id,
                "workflow_version": version.version,
                "action_key": version.action_key,
            },
        )

        draft_assignees = values.get("draft_assignees") or {}
        for node_ref, user_ids in draft_assignees.items():
            node = nodes.filtered(
                lambda item: item.node_key == str(node_ref) or str(item.id) == str(node_ref)
            )[:1]
            if node:
                self._set_draft_assignees_locked(instance, node, user_ids)
        return self.get_panel_data(instance_id=instance.id)

    def _resolve_assignment_node(self, reference):
        if isinstance(reference, str) and reference.startswith("node:"):
            try:
                node_id = int(reference.partition(":")[2])
            except (TypeError, ValueError) as error:
                raise ValidationError(_("Invalid approval assignment reference.")) from error
            node = (
                self.env["occ.approval.instance.node"].sudo().browse(node_id).exists()
            )
            if not node:
                raise MissingError(_("Approval node not found."))
            return node
        try:
            reference_id = int(reference)
        except (TypeError, ValueError) as error:
            raise ValidationError(_("Invalid approval assignment reference.")) from error
        node_candidate = (
            self.env["occ.approval.instance.node"]
            .sudo()
            .browse(reference_id)
            .exists()
        )
        if node_candidate and node_candidate.assignment_type == "requester_choice":
            return node_candidate
        task = self.env["occ.approval.task"].sudo().browse(reference_id).exists()
        node = (
            task.node_id
            if task
            else node_candidate
        )
        if not node:
            raise MissingError(_("Approval node or task not found."))
        return node

    def search_assignable_users(self, task_id, *, query=None, limit=50):
        node = self._resolve_assignment_node(task_id)
        instance = self._instance_for_actor(node.instance_id.id, operation="read")
        if node.assignment_type != "requester_choice":
            raise UserError(_("This node does not allow requester-selected users."))
        if not self._is_manager() and self.env.user != instance.requester_id:
            raise AccessError(_("Only the requester can select node users."))
        domain = [
            ("active", "=", True),
            ("share", "=", False),
            ("company_ids", "in", instance.company_id.id),
        ]
        if query:
            domain.append(("name", "ilike", query))
        users = self.env["res.users"].sudo().search(
            domain,
            order="name, id",
            limit=min(max(int(limit or 50) * 3, 1), 200),
        )
        users = users.filtered(
            lambda user: self._user_can_read_instance_source(instance, user)
        )[: min(max(int(limit or 50), 1), 200)]
        return [{"id": user.id, "name": user.name} for user in users]

    def set_task_users(self, task_id, user_ids):
        node = self._resolve_assignment_node(task_id)
        return self.set_draft_assignees(node.instance_id.id, node.id, user_ids)

    def set_draft_assignees(self, instance_id, node_id, user_ids):
        instance = self._instance_for_actor(instance_id, operation="write")
        if not self._is_manager() and self.env.user != instance.requester_id:
            raise AccessError(_("Only the requester can select node users."))
        instance = self._lock_instance(instance.id)
        node = instance.node_ids.filtered(lambda item: item.id == int(node_id))
        if not node:
            raise ValidationError(_("The node does not belong to this instance."))
        self._set_draft_assignees_locked(instance, node, user_ids)
        return self.get_panel_data(instance_id=instance.id)

    def _set_draft_assignees_locked(self, instance, node, user_ids):
        if instance.state not in ACTIVE_INSTANCE_STATES:
            raise UserError(_("Node users can only be changed on an active approval instance."))
        if node.assignment_type != "requester_choice":
            raise UserError(_("This node does not allow requester-selected users."))
        if node.state not in ("waiting",):
            raise UserError(_("Node users can only be changed before the node is entered."))
        users = self._validate_runtime_users(instance.company_id, user_ids)
        if not users:
            raise ValidationError(_("Select at least one assignee."))
        self._validate_source_readers(instance, users)
        node.sudo().write({"draft_assignee_user_ids": [(6, 0, users.ids)]})
        self._append_event(
            instance,
            "draft_assignees_set",
            node=node,
            payload={"user_ids": users.ids},
        )

    def _validate_runtime_users(self, company, user_ids):
        try:
            user_ids = sorted(set(int(user_id) for user_id in user_ids))
        except (TypeError, ValueError) as error:
            raise ValidationError(_("Invalid assignee list.")) from error
        users = self.env["res.users"].sudo().browse(user_ids).exists()
        if set(users.ids) != set(user_ids):
            raise ValidationError(_("One or more assignees no longer exist."))
        invalid = users.filtered(
            lambda user: user.share or not user.active or company not in user.company_ids
        )
        if invalid:
            raise ValidationError(_("Assignees must be active internal users of the instance company."))
        return users

    def _user_can_read_instance_source(self, instance, user):
        if instance.source_model not in self.env:
            return False
        record = (
            self.env[instance.source_model]
            .with_user(user)
            .with_context(allowed_company_ids=[instance.company_id.id])
            .browse(instance.source_res_id)
            .exists()
        )
        if not record:
            return False
        try:
            record.check_access("read")
        except AccessError:
            return False
        return True

    def _validate_source_readers(self, instance, users):
        unreadable = users.filtered(
            lambda user: not self._user_can_read_instance_source(instance, user)
        )
        if unreadable:
            raise ValidationError(
                _(
                    "These assignees cannot read the source document: %(users)s.",
                    users=", ".join(unreadable.mapped("name")),
                )
            )

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def submit(self, instance_id):
        instance = self._instance_for_actor(instance_id, operation="write")
        if not self._is_manager() and self.env.user != instance.requester_id:
            raise AccessError(_("Only the requester can submit this approval."))
        instance = self._lock_instance(instance.id)
        if instance.state not in ("draft", "rework"):
            raise UserError(_("This approval cannot be submitted in its current state."))
        start_node = instance.current_node_id
        if not start_node or start_node.node_type != "start" or start_node.state != "active":
            raise UserError(_("The approval is not waiting at its start node."))
        old_state = instance.state
        now = self.env.cr.now()
        instance.sudo().write(
            {
                "state": "running",
                "submitted_at": instance.submitted_at or now,
                "last_decision": "none",
            }
        )
        start_node.sudo().write({"state": "completed", "completed_at": now})
        self._append_event(
            instance,
            "instance_submitted",
            node=start_node,
            from_state=old_state,
            to_state="running",
        )
        self._advance(instance, start_node)
        return self.get_panel_data(instance_id=instance.id)

    def cancel_submission(self, instance_id, *, reason=None):
        instance = self._instance_for_actor(instance_id, operation="write")
        if not self._is_manager() and self.env.user != instance.requester_id:
            raise AccessError(_("Only the requester can cancel the submission."))
        instance = self._lock_instance(instance.id)
        if instance.state not in ("running", "rework"):
            raise UserError(_("Only a running submission can be returned to draft."))
        acted = instance.task_ids.filtered(
            lambda task: task.task_kind in ACTION_NODE_TYPES
            and task.state in ("approved", "completed", "rejected")
        )
        if acted:
            raise UserError(_("The submission cannot be cancelled after a user has acted."))
        self._cancel_pending_tasks(instance.task_ids)
        instance.node_ids.filtered(lambda node: node.node_type != "start").sudo().write(
            {"state": "waiting"}
        )
        start_node = instance.node_ids.filtered(lambda node: node.node_type == "start").ensure_one()
        start_node.sudo().write(
            {
                "state": "active",
                "attempt": start_node.attempt + 1,
                "visit_count": start_node.visit_count + 1,
                "entered_at": self.env.cr.now(),
                "completed_at": False,
            }
        )
        instance.sudo().write(
            {
                "state": "draft",
                "current_node_id": start_node.id,
                "return_node_id": False,
                "last_decision": "none",
            }
        )
        self._append_event(
            instance,
            "submission_cancelled",
            node=start_node,
            from_state="running",
            to_state="draft",
            payload={"reason": reason or ""},
        )
        return self.get_panel_data(instance_id=instance.id)

    def cancel_instance(self, instance_id, *, reason=None):
        instance = self._instance_for_cancellation(instance_id)
        if not self._is_manager() and self.env.user != instance.requester_id:
            raise AccessError(_("Only the requester or an approval manager can cancel this instance."))
        instance = self._lock_instance(instance.id)
        if instance.state not in ACTIVE_INSTANCE_STATES:
            raise UserError(_("Only a draft or running approval instance can be cancelled."))
        old_state = instance.state
        self._cancel_pending_tasks(instance.task_ids)
        instance.node_ids.filtered(lambda node: node.state in OPEN_NODE_STATES).sudo().write(
            {"state": "cancelled"}
        )
        instance.sudo().write(
            {
                "state": "cancelled",
                "current_node_id": False,
                "return_node_id": False,
                "cancelled_at": self.env.cr.now(),
                "cancellation_reason": reason or "",
            }
        )
        self._append_event(
            instance,
            "instance_cancelled",
            from_state=old_state,
            to_state="cancelled",
            payload={"reason": reason or ""},
        )
        return self._terminal_instance_payload(instance)

    def approve_task(self, task_id, *, values=None, automatic=False):
        values = values or {}
        comment = self._operation_comment(values)
        if not automatic:
            self._task_for_actor(task_id)
        task, instance = self._lock_and_refresh_task(task_id)
        if not automatic:
            self._instance_for_actor(instance.id, operation="read")
            if task.user_id != self.env.user:
                raise AccessError(_("Only the assigned user can approve this task."))
        self._assert_open_task(task, instance)
        node = task.node_id
        target_task_state = "approved" if node.node_type == "approval" else "completed"
        task.sudo().write(
            {
                "state": target_task_state,
                "acted_at": self.env.cr.now(),
                "acted_by_id": self.env.user.id,
                "comment": comment,
            }
        )
        self._append_event(
            instance,
            "task_approved" if node.node_type == "approval" else "task_completed",
            node=node,
            task=task,
            from_state="pending",
            to_state=target_task_state,
            payload={"comment": comment, "automatic": automatic},
        )
        current_tasks = node.task_ids.filtered(
            lambda item: item.attempt == node.attempt and item.state == "pending"
        )
        if node.approval_mode == "any":
            self._cancel_pending_tasks(current_tasks)
            self._complete_action_node(instance, node)
        elif not current_tasks:
            self._complete_action_node(instance, node)
        return self.get_panel_data(instance_id=instance.id) if not automatic else True

    def reject_task(self, task_id, *, values=None, automatic=False):
        values = values or {}
        comment = self._operation_comment(values)
        if not automatic:
            self._task_for_actor(task_id)
        task, instance = self._lock_and_refresh_task(task_id)
        if not automatic:
            self._instance_for_actor(instance.id, operation="read")
            if task.user_id != self.env.user:
                raise AccessError(_("Only the assigned user can reject this task."))
        self._assert_open_task(task, instance)
        target = self._resolve_reject_target(instance, task.node_id, values)
        mode = values.get("mode") or values.get("revert_mode") or "sequential"
        self._reject_current_node(
            instance,
            task.node_id,
            target,
            mode,
            task=task,
            comment=comment,
            automatic=automatic,
        )
        return self.get_panel_data(instance_id=instance.id) if not automatic else True

    def _reject_current_node(
        self,
        instance,
        current_node,
        target_node,
        mode,
        *,
        task=None,
        comment="",
        automatic=False,
    ):
        if mode not in REJECT_MODES:
            raise ValidationError(_("Invalid rejection mode."))
        if task:
            task.sudo().write(
                {
                    "state": "rejected",
                    "acted_at": self.env.cr.now(),
                    "acted_by_id": self.env.user.id,
                    "comment": comment,
                }
            )
        self._cancel_pending_tasks(
            current_node.task_ids.filtered(lambda item: item.attempt == current_node.attempt)
        )
        current_node.sudo().write(
            {"state": "rejected", "completed_at": self.env.cr.now()}
        )
        instance.sudo().write(
            {"state": "rework", "last_decision": "rejected"}
        )
        self._append_event(
            instance,
            "task_rejected",
            node=current_node,
            task=task,
            from_state="active",
            to_state="rejected",
            payload={
                "target_node_id": target_node.id,
                "target_node_key": target_node.node_key,
                "mode": mode,
                "comment": comment,
                "automatic": automatic,
            },
        )

        affected = instance.node_ids.filtered(
            lambda node: target_node.sequence <= node.sequence <= current_node.sequence
        )
        self._cancel_pending_tasks(affected.mapped("task_ids"))
        affected.sudo().write(
            {
                "state": "waiting",
                "completed_at": False,
                "deadline_at": False,
                "automatic_reminder_at": False,
            }
        )
        instance.sudo().write(
            {"return_node_id": current_node.id if mode == "direct" else False}
        )
        self._enter_node(instance, target_node, state="rework")

    def _resolve_reject_target(self, instance, current_node, values):
        target_id = values.get("target_node_id") or values.get("revert_node_id")
        target_key = values.get("target_node_key")
        if target_id:
            try:
                target_id = int(target_id)
            except (TypeError, ValueError) as error:
                raise ValidationError(_("Invalid rejection target.")) from error
        target = instance.node_ids.filtered(
            lambda node: (target_id and node.id == target_id)
            or (target_key and node.node_key == target_key)
        )[:1]
        if not target:
            raise ValidationError(_("Select a rejection target from the same instance."))
        if (
            target.sequence >= current_node.sequence
            or target.visit_count <= 0
            or target.node_type in ("copy", "end")
        ):
            raise ValidationError(_("The rejection target must be a previously visited node."))
        return target

    def revoke_task(self, task_id, *, values=None):
        values = values or {}
        comment = self._operation_comment(values)
        task, _instance = self._task_for_actor(task_id, acted=True)
        task, instance = self._lock_and_refresh_task(task.id)
        self._instance_for_actor(instance.id, operation="read")
        if task.user_id != self.env.user:
            raise AccessError(_("Only the original actor can revoke this task."))
        if instance.state not in ("running",):
            raise UserError(_("A task cannot be revoked in the current instance state."))
        if task.state not in ("approved", "completed"):
            raise UserError(_("Only an approved or completed task can be revoked."))

        node = task.node_id
        if task.attempt != node.attempt:
            raise UserError(_("This task belongs to an earlier node attempt."))
        if instance.current_node_id == node and node.state == "active":
            old_task_state = task.state
            task.sudo().write(
                {
                    "state": "pending",
                    "acted_at": False,
                    "acted_by_id": False,
                    "comment": False,
                }
            )
            self._append_event(
                instance,
                "task_revoked",
                node=node,
                task=task,
                from_state=old_task_state,
                to_state="pending",
                payload={"comment": comment},
            )
            return self.get_panel_data(instance_id=instance.id)

        later_acted = instance.task_ids.filtered(
            lambda item: item.node_id.sequence > node.sequence
            and item.state in ("approved", "completed", "rejected", "copied")
        )
        if later_acted:
            raise UserError(_("This task cannot be revoked after a later node has acted."))
        current = instance.current_node_id
        if not current or current.sequence <= node.sequence:
            raise UserError(_("The workflow is no longer immediately after this task."))
        current_pending = current.task_ids.filtered(
            lambda item: item.attempt == current.attempt and item.state == "pending"
        )
        if len(current_pending) != len(
            current.task_ids.filtered(lambda item: item.attempt == current.attempt)
        ):
            raise UserError(_("The next node has already been processed."))

        self._cancel_pending_tasks(current_pending)
        current.sudo().write({"state": "waiting"})
        instance.sudo().write({"return_node_id": False, "last_decision": "none"})
        self._append_event(
            instance,
            "task_revoked",
            node=node,
            task=task,
            from_state=task.state,
            to_state="pending",
            payload={"comment": comment},
        )
        node.sudo().write({"state": "waiting", "completed_at": False})
        self._enter_node(instance, node)
        return self.get_panel_data(instance_id=instance.id)

    def _assert_open_task(self, task, instance):
        if instance.state not in ("running", "rework"):
            raise UserError(_("The approval instance is not accepting task actions."))
        if task.state != "pending":
            raise UserError(_("This task has already been processed."))
        node = task.node_id
        if (
            instance.current_node_id != node
            or node.state != "active"
            or task.attempt != node.attempt
        ):
            raise UserError(_("This task is stale because the workflow has moved on."))

    def _complete_action_node(self, instance, node):
        target_state = "approved" if node.node_type == "approval" else "completed"
        node.sudo().write({"state": target_state, "completed_at": self.env.cr.now()})
        self._append_event(
            instance,
            "node_approved" if node.node_type == "approval" else "node_completed",
            node=node,
            from_state="active",
            to_state=target_state,
        )
        self._advance(instance, node)

    # ------------------------------------------------------------------
    # Node entry, assignment, routing, and completion
    # ------------------------------------------------------------------

    def _enter_node(self, instance, node, *, state=None):
        now = self.env.cr.now()
        definition = node.definition or {}
        deadline_hours = float(definition.get("deadline_hours") or 0)
        reminder_before = float(definition.get("reminder_before_hours") or 0)
        deadline_at = now + timedelta(hours=deadline_hours) if deadline_hours else False
        reminder_at = (
            deadline_at - timedelta(hours=reminder_before)
            if deadline_at and reminder_before
            else False
        )
        attempt = node.attempt + 1
        node.sudo().write(
            {
                "state": "active",
                "attempt": attempt,
                "visit_count": node.visit_count + 1,
                "entered_at": now,
                "completed_at": False,
                "deadline_at": deadline_at,
                "automatic_reminder_at": reminder_at,
                "reminder_sent_at": False,
                "manual_reminder_sent_at": False,
                "timeout_processed_at": False,
            }
        )
        instance_values = {"current_node_id": node.id}
        if state:
            instance_values["state"] = state
        instance.sudo().write(instance_values)
        self._append_event(
            instance,
            "node_entered",
            node=node,
            from_state="waiting",
            to_state="active",
            payload={"attempt": attempt},
        )

        if node.node_type == "start":
            return
        if node.node_type == "end":
            node.sudo().write({"state": "completed", "completed_at": now})
            self._finalize_approved(instance, node)
            return

        users = self._resolve_assignees(instance, node)
        if not users:
            raise ValidationError(_("Node %s has no available assignees.", node.name))
        instance.sudo().write(
            {"participant_user_ids": [(4, user.id) for user in users]}
        )
        task_kind = node.node_type
        task_state = "copied" if node.node_type == "copy" else "pending"
        tasks = self.env["occ.approval.task"].sudo().create(
            [
                {
                    "instance_id": instance.id,
                    "node_id": node.id,
                    "company_id": instance.company_id.id,
                    "user_id": user.id,
                    "task_kind": task_kind,
                    "attempt": attempt,
                    "state": task_state,
                    "deadline_at": deadline_at,
                    "acted_at": now if task_state == "copied" else False,
                }
                for user in users
            ]
        )
        self._append_event(
            instance,
            "tasks_assigned" if node.node_type != "copy" else "copy_delivered",
            node=node,
            payload={"task_ids": tasks.ids, "user_ids": users.ids, "attempt": attempt},
        )
        if node.node_type == "copy":
            self._notify_users(
                users,
                title=_("Approval notification"),
                message=_(
                    "You received an approval copy for %(document)s.",
                    document=instance.source_display_name,
                ),
            )
        else:
            self._notify_users(
                users,
                title=_("Approval task assigned"),
                message=_(
                    "A new approval task for %(document)s is waiting for you.",
                    document=instance.source_display_name,
                ),
            )
        if node.node_type == "copy":
            node.sudo().write({"state": "completed", "completed_at": now})
            self._advance(instance, node)

    def _resolve_assignees(self, instance, node):
        assignment = (node.definition or {}).get("assignment") or {}
        assignment_type = assignment.get("type")
        users = self.env["res.users"].sudo().browse()
        requester = instance.requester_id
        if assignment_type == "users":
            users = self.env["res.users"].sudo().browse(assignment.get("user_ids") or [])
        elif assignment_type == "role":
            role = self.env["occ.approval.role"].sudo().browse(
                assignment.get("role_id")
            ).exists()
            if not role or role.company_id != instance.company_id or not role.active:
                raise ValidationError(_("The approval role for node %s is unavailable.", node.name))
            users = role.user_ids
        elif assignment_type == "requester":
            users = requester
        elif assignment_type == "requester_choice":
            users = node.draft_assignee_user_ids
        elif assignment_type in ("manager", "manager_chain"):
            chain = []
            seen = {requester.id}
            manager = requester.occ_approval_manager_id
            while manager and manager.id not in seen and len(chain) < 100:
                seen.add(manager.id)
                chain.append(manager)
                manager = manager.occ_approval_manager_id
            if assignment_type == "manager":
                level = int(assignment.get("level") or 1)
                users = chain[level - 1] if len(chain) >= level else users
            else:
                levels = int(assignment.get("levels") or 0)
                selected = chain[:levels] if levels else chain
                users = self.env["res.users"].sudo().browse(
                    [manager.id for manager in selected]
                )
        else:
            raise ValidationError(_("Node %s has an unsupported assignment type.", node.name))
        users = self._validate_runtime_users(instance.company_id, users.ids)
        self._validate_source_readers(instance, users)
        return users

    def _advance(self, instance, completed_node):
        if instance.return_node_id and instance.return_node_id != completed_node:
            target = instance.return_node_id
            instance.sudo().write({"return_node_id": False})
            self._enter_node(instance, target, state="running")
            return

        definition = instance.workflow_version_id.definition
        outgoing = [
            edge for edge in definition["edges"] if edge["source"] == completed_node.node_key
        ]
        outgoing.sort(key=lambda edge: (edge.get("sequence", 0), edge["target"]))
        source = self._source_record(
            instance.source_model, instance.source_res_id, "read", sudo=True
        )
        self._assert_instance_source_company(instance, source)
        selected = None
        fallback = None
        for edge in outgoing:
            condition = edge.get("condition") or []
            if not condition:
                fallback = edge
                continue
            if source.filtered_domain(Domain(condition)):
                selected = edge
                break
        selected = selected or fallback
        if not selected:
            raise ValidationError(
                _("No outgoing condition matched node %s and no fallback edge exists.", completed_node.name)
            )
        next_node = instance.node_ids.filtered(
            lambda node: node.node_key == selected["target"]
        ).ensure_one()
        self._append_event(
            instance,
            "edge_selected",
            node=completed_node,
            payload={
                "source": selected["source"],
                "target": selected["target"],
                "sequence": selected.get("sequence", 0),
            },
        )
        self._enter_node(instance, next_node, state="running")

    def _finalize_approved(self, instance, end_node):
        old_state = instance.state
        instance.sudo().write(
            {
                "state": "approved",
                "last_decision": "approved",
                "current_node_id": False,
                "return_node_id": False,
                "completed_at": self.env.cr.now(),
            }
        )
        self._append_event(
            instance,
            "instance_approved",
            node=end_node,
            from_state=old_state,
            to_state="approved",
        )
        if instance.workflow_version_id.auto_execute:
            self._execute_approved_adapter(instance)

    def _cancel_pending_tasks(self, tasks):
        tasks.filtered(lambda task: task.state == "pending").sudo().write(
            {"state": "cancelled"}
        )

    # ------------------------------------------------------------------
    # Reminders, deadlines and execution adapter
    # ------------------------------------------------------------------

    def remind(self, instance_id, *, values=None):
        values = values or {}
        reminder_message = values.get("message") or self._operation_comment(values)
        instance = self._instance_for_actor(instance_id, operation="read")
        if not self._is_manager() and self.env.user != instance.requester_id:
            raise AccessError(_("Only the requester can remind current assignees."))
        instance = self._lock_instance(instance.id)
        node_id = values.get("node_id")
        node = (
            instance.node_ids.filtered(lambda item: item.id == int(node_id))
            if node_id
            else instance.current_node_id
        )
        if not node or node != instance.current_node_id or node.state != "active":
            raise UserError(_("Only the active node can be reminded."))
        if node.node_type not in ACTION_NODE_TYPES:
            raise UserError(_("This node has no actionable assignees."))
        if node.manual_reminder_sent_at:
            raise UserError(_("A manual reminder was already sent for this node attempt."))
        pending = node.task_ids.filtered(
            lambda task: task.attempt == node.attempt and task.state == "pending"
        )
        if not pending:
            raise UserError(_("There are no pending assignees to remind."))
        self._notify_users(
            pending.user_id,
            title=_("Approval reminder"),
            message=reminder_message
            or _(
                "Approval for %(document)s is waiting for your action.",
                document=instance.source_display_name,
            ),
            notification_type="warning",
        )
        now = self.env.cr.now()
        node.sudo().write({"manual_reminder_sent_at": now})
        pending.sudo().write({"reminder_sent_at": now})
        self._append_event(
            instance,
            "manual_reminder_sent",
            node=node,
            payload={
                "task_ids": pending.ids,
                "user_ids": pending.user_id.ids,
                "message": reminder_message,
            },
        )
        return self.get_panel_data(instance_id=instance.id)

    def cron_process_deadlines(self):
        now = self.env.cr.now()
        reminder_nodes = self.env["occ.approval.instance.node"].sudo().search(
            [
                ("state", "=", "active"),
                ("automatic_reminder_at", "!=", False),
                ("automatic_reminder_at", "<=", now),
                ("reminder_sent_at", "=", False),
                ("instance_id.state", "in", ("running", "rework")),
            ]
        )
        timeout_nodes = self.env["occ.approval.instance.node"].sudo().search(
            [
                ("state", "=", "active"),
                ("deadline_at", "!=", False),
                ("deadline_at", "<=", now),
                ("timeout_processed_at", "=", False),
                ("timeout_action", "!=", "none"),
                ("instance_id.state", "in", ("running", "rework")),
            ]
        )
        reminders = 0
        timeouts = 0
        for node in reminder_nodes:
            try:
                with self.env.cr.savepoint():
                    instance = self._lock_instance(node.instance_id.id)
                    node.invalidate_recordset()
                    if node.state != "active" or node.reminder_sent_at:
                        continue
                    pending = node.task_ids.filtered(
                        lambda task: task.attempt == node.attempt and task.state == "pending"
                    )
                    sent_at = self.env.cr.now()
                    if pending:
                        self._notify_users(
                            pending.user_id,
                            title=_("Approval reminder"),
                            message=_(
                                "Approval for %(document)s is waiting for your action.",
                                document=instance.source_display_name,
                            ),
                            notification_type="warning",
                        )
                    node.sudo().write({"reminder_sent_at": sent_at})
                    pending.sudo().write({"reminder_sent_at": sent_at})
                    self._append_event(
                        instance,
                        "automatic_reminder_sent",
                        node=node,
                        payload={"task_ids": pending.ids, "user_ids": pending.user_id.ids},
                    )
                    reminders += 1
            except Exception:
                _logger.exception("Failed to process approval reminder for node %s", node.id)

        for node in timeout_nodes:
            try:
                with self.env.cr.savepoint():
                    instance = self._lock_instance(node.instance_id.id)
                    node.invalidate_recordset()
                    if node.state != "active" or node.timeout_processed_at:
                        continue
                    node.sudo().write({"timeout_processed_at": self.env.cr.now()})
                    self._append_event(
                        instance,
                        "node_timeout_reached",
                        node=node,
                        payload={"action": node.timeout_action},
                    )
                    self._process_timeout(instance, node)
                    timeouts += 1
            except Exception:
                _logger.exception("Failed to process approval timeout for node %s", node.id)
        return {"reminders": reminders, "timeouts": timeouts}

    def _process_timeout(self, instance, node):
        source = self._source_record(
            instance.source_model, instance.source_res_id, "read", sudo=True
        )
        self._assert_instance_source_company(instance, source)
        pending = node.task_ids.filtered(
            lambda task: task.attempt == node.attempt and task.state == "pending"
        )
        if not pending:
            return
        if node.timeout_action == "approve":
            if node.approval_mode == "any":
                first = pending[:1]
                first.sudo().write(
                    {
                        "state": "approved" if node.node_type == "approval" else "completed",
                        "acted_at": self.env.cr.now(),
                        "acted_by_id": self.env.user.id,
                        "comment": "Automatic timeout approval",
                    }
                )
                self._cancel_pending_tasks(pending - first)
            else:
                pending.sudo().write(
                    {
                        "state": "approved" if node.node_type == "approval" else "completed",
                        "acted_at": self.env.cr.now(),
                        "acted_by_id": self.env.user.id,
                        "comment": "Automatic timeout approval",
                    }
                )
            self._append_event(
                instance,
                "timeout_auto_approved",
                node=node,
                payload={"task_ids": pending.ids},
            )
            self._complete_action_node(instance, node)
        elif node.timeout_action == "reject":
            version = instance.workflow_version_id
            version._assert_integrity()
            definition = next(
                (
                    item
                    for item in version.definition.get("nodes", [])
                    if item.get("id") == node.node_key
                ),
                None,
            )
            if not definition or definition.get("timeout_action") != "reject":
                raise ValidationError(
                    _("The timeout configuration no longer matches the published workflow.")
                )
            target = instance.node_ids.filtered(
                lambda item: item.node_key == definition.get("timeout_reject_node")
            )[:1]
            if not target:
                raise ValidationError(_("The timeout rejection target no longer exists."))
            if (
                target.instance_id != instance
                or target.sequence >= node.sequence
                or target.visit_count <= 0
                or target.node_type in ("copy", "end")
                or not ApprovalDefinitionService.is_dominator(
                    version.definition, target.node_key, node.node_key
                )
            ):
                raise ValidationError(
                    _(
                        "The timeout rejection target must be an earlier mandatory node from the same instance."
                    )
                )
            self._reject_current_node(
                instance,
                node,
                target,
                definition.get("timeout_reject_mode") or "sequential",
                comment="Automatic timeout rejection",
                automatic=True,
            )

    def retry_execution(self, instance_id):
        instance = self._instance_for_actor(instance_id, operation="write")
        if not self._is_manager():
            raise AccessError(_("Only approval managers can retry business execution."))
        instance = self._lock_instance(instance.id)
        if instance.state != "approved" or instance.execution_state != "failed":
            raise UserError(_("Only failed execution of an approved instance can be retried."))
        self._execute_approved_adapter(instance)
        return self.get_panel_data(instance_id=instance.id)

    def _execute_approved_adapter(self, instance):
        if instance.execution_state == "running":
            raise UserError(_("Business execution is already running."))
        instance.sudo().write(
            {
                "execution_state": "running",
                "execution_attempts": instance.execution_attempts + 1,
                "execution_error": False,
                "execution_error_public": False,
            }
        )
        self._append_event(
            instance,
            "execution_started",
            payload={"attempt": instance.execution_attempts},
        )
        try:
            with self.env.cr.savepoint():
                execution_context = {
                    **self.env.context,
                    "allowed_company_ids": [instance.company_id.id],
                    "occ_approval_instance_id": instance.id,
                    "occ_approval_execution": True,
                    "occ_approval_execution_capability": EXECUTION_CAPABILITY,
                }
                record = (
                    self.env[instance.source_model]
                    .with_user(instance.requester_id)
                    .with_context(execution_context)
                    .with_company(instance.company_id)
                    .browse(instance.source_res_id)
                    .exists()
                )
                if not record:
                    raise MissingError(_("The source record no longer exists."))
                record.check_access("write")
                self._assert_instance_source_company(instance, record)
                version = instance.workflow_version_id
                version._assert_integrity()
                if (
                    version.model_name != instance.source_model
                    or version.action_key != instance.action_key
                ):
                    raise ValidationError(
                        _("The approval instance no longer matches its published workflow version.")
                    )
                supported_action_method = getattr(
                    record, "_occ_supported_approval_actions", None
                )
                supported_actions = (
                    supported_action_method() if supported_action_method else frozenset()
                )
                if isinstance(supported_actions, str):
                    raise ValidationError(
                        _("The business connector returned an invalid action allowlist.")
                    )
                try:
                    supported_actions = frozenset(supported_actions)
                except TypeError as error:
                    raise ValidationError(
                        _("The business connector returned an invalid action allowlist.")
                    ) from error
                if instance.action_key not in supported_actions:
                    raise UserError(
                        _(
                            "The business connector no longer permits the approved action %(action)s.",
                            action=instance.action_key,
                        )
                    )
                adapter = getattr(record, "_occ_execute_approved_action", None)
                if not callable(adapter):
                    raise UserError(
                        _("The business model has no approved-action connector.")
                    )
                self._assert_execution_capability(record, instance.action_key)
                execution_instance = (
                    instance.with_user(instance.requester_id)
                    .with_context(execution_context)
                    .with_company(instance.company_id)
                )
                adapter(execution_instance)
        except Exception as error:
            _logger.exception("Approved business adapter failed for instance %s", instance.id)
            public_error = (
                str(error)
                if isinstance(error, UserError)
                else _(
                    "Business execution failed unexpectedly. Contact an approval administrator."
                )
            )
            instance.sudo().write(
                {
                    "execution_state": "failed",
                    "execution_error": str(error),
                    "execution_error_public": public_error,
                    "executed_at": False,
                }
            )
            self._append_event(
                instance,
                "execution_failed",
                from_state="running",
                to_state="failed",
                payload={"error": public_error, "attempt": instance.execution_attempts},
            )
        else:
            instance.sudo().write(
                {
                    "execution_state": "done",
                    "execution_error": False,
                    "execution_error_public": False,
                    "executed_at": self.env.cr.now(),
                }
            )
            self._append_event(
                instance,
                "execution_completed",
                from_state="running",
                to_state="done",
                payload={"attempt": instance.execution_attempts},
            )

    def open_document(self, instance_id):
        instance = self._instance_for_actor(
            instance_id,
            operation="read",
            allow_source_company_mismatch=True,
        )
        record = self._source_record(
            instance.source_model, instance.source_res_id, "read"
        )
        return {
            "type": "ir.actions.act_window",
            "name": record.display_name,
            "res_model": instance.source_model,
            "res_id": instance.source_res_id,
            "view_mode": "form",
            "target": "current",
        }
