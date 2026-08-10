import copy
import uuid
from datetime import timedelta
from unittest.mock import patch

from psycopg2.errors import UniqueViolation

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user

from ..services.definition import ApprovalDefinitionService


class TestApprovalWorkflowEngine(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        def make_user(login, groups):
            return new_test_user(
                cls.env,
                login=login,
                groups=groups,
                company_id=cls.company.id,
                company_ids=[Command.set(cls.company.ids)],
            )

        cls.requester = make_user(
            "occ_engine_requester",
            "occ_approval.group_approval_user,base.group_partner_manager",
        )
        cls.approver = make_user(
            "occ_engine_approver",
            "occ_approval.group_approval_user",
        )
        cls.alternate = make_user(
            "occ_engine_alternate",
            "occ_approval.group_approval_user",
        )
        cls.outsider = make_user(
            "occ_engine_outsider",
            "occ_approval.group_approval_user",
        )
        cls.manager = make_user(
            "occ_engine_manager",
            "occ_approval.group_approval_manager",
        )

    def _simple_definition(
        self,
        *,
        assignee=None,
        assignment_type="users",
        node_name="Approval",
        node_type="approval",
    ):
        assignment = {"type": assignment_type}
        if assignment_type == "users":
            assignment["user_ids"] = [(assignee or self.approver).id]
        return {
            "schema_version": 1,
            "nodes": [
                {"id": "start", "type": "start", "name": "Start"},
                {
                    "id": "decision",
                    "type": node_type,
                    "name": node_name,
                    "assignment": assignment,
                    "mode": "all",
                },
                {"id": "end", "type": "end", "name": "End"},
            ],
            "edges": [
                {
                    "source": "start",
                    "target": "decision",
                    "sequence": 10,
                    "condition": [],
                },
                {
                    "source": "decision",
                    "target": "end",
                    "sequence": 10,
                    "condition": [],
                },
            ],
        }

    def _create_draft_workflow(
        self,
        *,
        definition=None,
        model_name="res.partner",
        action_key="manual",
        applicability_domain=None,
        auto_execute=False,
    ):
        model = self.env["ir.model"]._get(model_name)
        return self.env["occ.approval.workflow"].with_user(self.manager).create(
            {
                "name": f"Engine workflow {uuid.uuid4().hex[:8]}",
                "code": f"engine-{uuid.uuid4().hex}",
                "company_id": self.company.id,
                "model_id": model.id,
                "action_key": action_key,
                "applicability_domain": applicability_domain or [],
                "auto_execute": auto_execute,
                "draft_definition": definition or self._simple_definition(),
            }
        )

    def _publish_workflow(self, workflow):
        result = (
            self.env["occ.approval.workflow"]
            .with_user(self.manager)
            .publish_designer_data(
                workflow.id,
                expected_revision=workflow.draft_revision,
            )
        )
        version = self.env["occ.approval.workflow.version"].browse(
            result["version_id"]
        )
        return workflow, version

    def _create_published_workflow(self, **values):
        return self._publish_workflow(self._create_draft_workflow(**values))

    def _create_source(self, suffix):
        return self.env["res.partner"].sudo().create(
            {
                "name": f"Approval engine source {suffix}",
                "company_id": self.company.id,
            }
        )

    def _instance_api(self, user):
        return self.env["occ.approval.instance"].with_user(user)

    def _runtime_instance(self, panel):
        return self.env["occ.approval.instance"].sudo().browse(
            panel["instance"]["id"]
        )

    def test_manual_approval_runs_from_request_to_completion(self):
        workflow, _version = self._create_published_workflow()
        source = self._create_source("manual")
        requester_api = self._instance_api(self.requester)

        created_panel = requester_api.create_for_record(
            source._name,
            source.id,
            workflow_id=workflow.id,
        )
        instance = self._runtime_instance(created_panel)
        self.assertEqual(created_panel["state"], "draft")
        self.assertTrue(created_panel["actions"]["can_submit"])
        self.assertEqual(instance.current_node_id.node_key, "start")

        submitted_panel = requester_api.submit(instance.id)
        instance.invalidate_recordset()
        task = instance.task_ids.filtered(
            lambda item: item.node_id.node_key == "decision"
            and item.state == "pending"
        ).ensure_one()
        self.assertEqual(submitted_panel["state"], "running")
        self.assertEqual(instance.current_node_id.node_key, "decision")
        self.assertEqual(task.user_id, self.approver)

        approved_panel = self._instance_api(self.approver).approve_task(
            task.id,
            {"comment": "Approved in the full-flow test"},
        )
        instance.invalidate_recordset()
        task.invalidate_recordset()
        self.assertEqual(approved_panel["state"], "approved")
        self.assertEqual(instance.state, "approved")
        self.assertEqual(instance.last_decision, "approved")
        self.assertFalse(instance.current_node_id)
        self.assertEqual(task.state, "approved")
        self.assertEqual(task.comment, "Approved in the full-flow test")
        self.assertEqual(
            instance.event_ids.sorted("sequence").mapped("sequence"),
            list(range(1, len(instance.event_ids) + 1)),
        )
        self.assertIn("instance_approved", instance.event_ids.mapped("event_type"))

    def test_requester_choice_is_visible_assignable_and_used_on_submit(self):
        definition = self._simple_definition(assignment_type="requester_choice")
        workflow, _version = self._create_published_workflow(
            definition=definition
        )
        source = self._create_source("requester-choice")
        requester_api = self._instance_api(self.requester)

        created_panel = requester_api.create_for_record(
            source._name,
            source.id,
            workflow_id=workflow.id,
        )
        instance = self._runtime_instance(created_panel)
        decision_node = instance.node_ids.filtered(
            lambda node: node.node_key == "decision"
        ).ensure_one()
        assignment_task = next(
            task for task in created_panel["tasks"] if task["kind"] == "assignment"
        )
        self.assertEqual(assignment_task["id"], f"node:{decision_node.id}")
        self.assertTrue(assignment_task["actions"]["choose_users"])
        self.assertFalse(assignment_task["assignees"])

        assignable = requester_api.search_assignable_users(
            f"node:{decision_node.id}",
            query=self.approver.name,
        )
        self.assertIn(self.approver.id, [user["id"] for user in assignable])

        selected_panel = requester_api.set_draft_assignees(
            instance.id,
            decision_node.id,
            [self.approver.id],
        )
        selected_task = next(
            task for task in selected_panel["tasks"] if task["kind"] == "assignment"
        )
        self.assertEqual(
            [user["id"] for user in selected_task["assignees"]],
            [self.approver.id],
        )

        requester_api.submit(instance.id)
        instance.invalidate_recordset()
        approval_task = instance.task_ids.filtered(
            lambda task: task.node_id == decision_node and task.state == "pending"
        ).ensure_one()
        self.assertEqual(approval_task.user_id, self.approver)
        self._instance_api(self.approver).approve_task(approval_task.id)
        instance.invalidate_recordset()
        self.assertEqual(instance.state, "approved")

    def test_company_drift_locks_workflow_actions_but_allows_fail_safe_cancel(self):
        other_company = self.env["res.company"].create({"name": "OCC Drift Company"})
        (self.requester | self.approver | self.manager).sudo().write(
            {"company_ids": [Command.link(other_company.id)]}
        )
        workflow, _version = self._create_published_workflow()
        source = self._create_source("company-drift")
        allowed_companies = [self.company.id, other_company.id]
        requester_api = self._instance_api(self.requester).with_context(
            allowed_company_ids=allowed_companies
        )
        panel = requester_api.create_for_record(
            source._name, source.id, workflow_id=workflow.id
        )
        instance = self._runtime_instance(panel)
        requester_api.submit(instance.id)
        instance.invalidate_recordset()
        task = instance.task_ids.filtered(lambda item: item.state == "pending").ensure_one()

        source.sudo().write({"company_id": other_company.id})
        drift_panel = requester_api.get_panel_data(
            res_model=source._name, res_id=source.id
        )
        self.assertTrue(drift_panel["source_company_mismatch"])
        self.assertTrue(drift_panel["actions"]["can_cancel_instance"])
        self.assertFalse(drift_panel["actions"]["can_cancel_submission"])
        self.assertFalse(drift_panel["actions"]["can_remind"])
        self.assertFalse(drift_panel["tasks"])

        with self.assertRaises(ValidationError):
            requester_api.cancel_submission(instance.id)
        with self.assertRaises(ValidationError):
            self._instance_api(self.approver).with_context(
                allowed_company_ids=allowed_companies
            ).approve_task(task.id)

        event_count = len(instance.event_ids)
        open_node_ids = instance.node_ids.filtered(
            lambda node: node.state in ("waiting", "active")
        ).ids
        cancelled_panel = requester_api.cancel_instance(instance.id)
        instance.invalidate_recordset()
        self.assertEqual(cancelled_panel["state"], "cancelled")
        self.assertEqual(instance.state, "cancelled")
        self.assertFalse(instance.current_node_id)
        self.assertTrue(
            all(
                node.state == "cancelled"
                for node in instance.node_ids.filtered(
                    lambda item: item.id in open_node_ids
                )
            )
        )
        self.assertTrue(all(item.state == "cancelled" for item in instance.task_ids))
        self.assertEqual(len(instance.event_ids), event_count + 1)
        self.assertEqual(instance.event_ids[-1].event_type, "instance_cancelled")

        missing_source = self._create_source("deleted-source")
        missing_panel = requester_api.create_for_record(
            missing_source._name,
            missing_source.id,
            workflow_id=workflow.id,
        )
        missing_instance = self._runtime_instance(missing_panel)
        missing_source.sudo().unlink()
        manager_result = self._instance_api(self.manager).cancel_instance(
            missing_instance.id
        )
        missing_instance.invalidate_recordset()
        self.assertEqual(manager_result["state"], "cancelled")
        self.assertEqual(missing_instance.state, "cancelled")

    def test_terminal_instance_cannot_change_waiting_requester_choice_users(self):
        definition = self._simple_definition(assignment_type="requester_choice")
        workflow, _version = self._create_published_workflow(definition=definition)
        source = self._create_source("terminal-assignment")
        requester_api = self._instance_api(self.requester)
        panel = requester_api.create_for_record(
            source._name, source.id, workflow_id=workflow.id
        )
        instance = self._runtime_instance(panel)
        node = instance.node_ids.filtered(
            lambda item: item.node_key == "decision"
        ).ensure_one()
        instance.sudo().write({"state": "approved"})
        event_count = len(instance.event_ids)

        with self.assertRaisesRegex(UserError, "active approval instance"):
            requester_api.set_draft_assignees(
                instance.id, node.id, [self.approver.id]
            )
        node.invalidate_recordset(["draft_assignee_user_ids"])
        self.assertFalse(node.draft_assignee_user_ids)
        self.assertEqual(len(instance.event_ids), event_count)

    def test_revoke_rejects_a_task_from_an_earlier_node_attempt(self):
        definition = {
            "schema_version": 1,
            "nodes": [
                {"id": "start", "type": "start", "name": "Start"},
                {
                    "id": "first",
                    "type": "approval",
                    "name": "First",
                    "assignment": {"type": "users", "user_ids": [self.approver.id]},
                    "mode": "all",
                },
                {
                    "id": "second",
                    "type": "approval",
                    "name": "Second",
                    "assignment": {"type": "users", "user_ids": [self.approver.id]},
                    "mode": "all",
                },
                {"id": "end", "type": "end", "name": "End"},
            ],
            "edges": [
                {"source": "start", "target": "first", "sequence": 10, "condition": []},
                {"source": "first", "target": "second", "sequence": 10, "condition": []},
                {"source": "second", "target": "end", "sequence": 10, "condition": []},
            ],
        }
        workflow, _version = self._create_published_workflow(definition=definition)
        source = self._create_source("stale-revoke")
        requester_api = self._instance_api(self.requester)
        panel = requester_api.create_for_record(
            source._name, source.id, workflow_id=workflow.id
        )
        instance = self._runtime_instance(panel)
        requester_api.submit(instance.id)
        instance.invalidate_recordset()
        first_task = instance.task_ids.filtered(
            lambda item: item.node_id.node_key == "first" and item.state == "pending"
        ).ensure_one()
        approver_api = self._instance_api(self.approver)
        approver_api.approve_task(first_task.id)
        instance.invalidate_recordset()
        first_node = first_task.node_id
        first_node.sudo().write({"attempt": first_node.attempt + 1})
        event_count = len(instance.event_ids)
        current_node = instance.current_node_id

        self.assertFalse(
            approver_api._engine()._can_revoke_task(first_task, self.approver)
        )
        with self.assertRaisesRegex(UserError, "earlier node attempt"):
            approver_api.revoke_task(first_task.id)
        instance.invalidate_recordset()
        self.assertEqual(instance.current_node_id, current_node)
        self.assertEqual(len(instance.event_ids), event_count)

    def test_non_manual_action_requires_its_explicit_action_key(self):
        partner_class = type(self.env["res.partner"])
        supported_calls = []
        execution_calls = []

        def supported_actions(recordset):
            supported_calls.append(
                {
                    "record_ids": recordset.ids,
                    "user_id": recordset.env.user.id,
                }
            )
            return frozenset({"confirm"})

        def execute_approved_action(recordset, instance):
            recordset.ensure_one()
            verified_instance = recordset.env[
                "occ.approval.instance"
            ]._assert_execution_capability(recordset, "confirm")
            execution_calls.append(
                {
                    "record_id": recordset.id,
                    "user_id": recordset.env.user.id,
                    "instance_id": instance.id,
                    "verified_instance_id": verified_instance.id,
                    "action_key": instance.action_key,
                    "execution_context": instance.env.context.get(
                        "occ_approval_execution"
                    ),
                    "record_company_id": recordset.env.company.id,
                    "instance_company_id": instance.env.company.id,
                    "allowed_company_ids": recordset.env.context.get(
                        "allowed_company_ids"
                    ),
                }
            )
            return True

        with (
            patch.object(
                partner_class,
                "_occ_supported_approval_actions",
                new=supported_actions,
                create=True,
            ),
            patch.object(
                partner_class,
                "_occ_execute_approved_action",
                new=execute_approved_action,
                create=True,
            ),
        ):
            workflow, version = self._create_published_workflow(
                action_key="confirm",
                auto_execute=True,
            )
            source = self._create_source("non-manual")
            requester_api = self._instance_api(self.requester)

            record_state = requester_api.get_record_state(source._name, source.id)
            self.assertTrue(record_state["enabled"])
            self.assertIn(workflow.id, record_state["workflow_ids"])
            self.assertFalse(record_state["can_request"])
            self.assertTrue(version.auto_execute)

            with self.assertRaises(UserError):
                requester_api.create_for_record(source._name, source.id)

            with self.assertRaises(AccessError):
                requester_api.create_for_record(
                    source._name,
                    source.id,
                    workflow_id=workflow.id,
                    values={"action_key": "confirm"},
                )

            created_panel = requester_api._create_for_record(
                source._name,
                source.id,
                workflow_id=workflow.id,
                values={"action_key": "confirm"},
            )
            instance = self._runtime_instance(created_panel)
            self.assertEqual(instance.action_key, "confirm")
            self.assertEqual(instance.execution_state, "pending")
            forged_source = source.with_user(self.requester).with_context(
                allowed_company_ids=[self.company.id],
                occ_approval_instance_id=instance.id,
                occ_approval_execution=True,
            )
            with self.assertRaises(AccessError):
                requester_api._assert_execution_capability(
                    forged_source, "confirm"
                )
            requester_api.submit(instance.id)
            instance.invalidate_recordset()
            task = instance.task_ids.filtered(
                lambda item: item.state == "pending"
            ).ensure_one()
            self._instance_api(self.approver).approve_task(task.id)
            instance.invalidate_recordset()
            self.assertEqual(instance.state, "approved")
            self.assertEqual(instance.execution_state, "done")
            self.assertEqual(instance.execution_attempts, 1)
            self.assertTrue(instance.executed_at)
            self.assertIn(
                "execution_completed",
                instance.event_ids.mapped("event_type"),
            )

        self.assertGreaterEqual(len(supported_calls), 2)
        self.assertEqual(supported_calls[-1]["record_ids"], source.ids)
        self.assertEqual(supported_calls[-1]["user_id"], self.requester.id)
        self.assertEqual(
            execution_calls,
            [
                {
                    "record_id": source.id,
                    "user_id": self.requester.id,
                    "instance_id": instance.id,
                    "verified_instance_id": instance.id,
                    "action_key": "confirm",
                    "execution_context": True,
                    "record_company_id": self.company.id,
                    "instance_company_id": self.company.id,
                    "allowed_company_ids": [self.company.id],
                }
            ],
        )

    def test_unique_constraint_race_is_reported_as_a_friendly_user_error(self):
        workflow, _version = self._create_published_workflow()
        source = self._create_source("unique-race")
        requester_api = self._instance_api(self.requester)
        first_panel = requester_api.create_for_record(
            source._name,
            source.id,
            workflow_id=workflow.id,
        )
        existing = self._runtime_instance(first_panel)
        alternative_workflow, _alternative_version = (
            self._create_published_workflow()
        )
        with self.assertRaisesRegex(
            UserError,
            "An unfinished approval instance already exists",
        ):
            requester_api.create_for_record(
                source._name,
                source.id,
                workflow_id=alternative_workflow.id,
            )

        instance_class = type(self.env["occ.approval.instance"])
        empty = self.env["occ.approval.instance"].sudo().browse()
        search_results = iter((empty, existing))
        searched_domains = []

        def fake_search(recordset, domain, *args, **kwargs):
            searched_domains.append(domain)
            return next(search_results)

        def fake_create(recordset, values):
            raise UniqueViolation("simulated concurrent unique-index conflict")

        with (
            patch.object(instance_class, "search", new=fake_search),
            patch.object(instance_class, "create", new=fake_create),
            self.assertRaisesRegex(
                UserError,
                "An unfinished approval instance already exists",
            ),
        ):
            requester_api.create_for_record(
                source._name,
                source.id,
                workflow_id=workflow.id,
            )

        self.assertEqual(len(searched_domains), 2)

    def test_failed_business_execution_blocks_a_new_approval_for_the_source(self):
        partner_class = type(self.env["res.partner"])

        def supported_actions(recordset):
            return frozenset({"confirm"})

        def execute_approved_action(recordset, instance):
            recordset.env[
                "occ.approval.instance"
            ]._assert_execution_capability(recordset, "confirm")
            raise UserError("simulated connector failure")

        with (
            patch.object(
                partner_class,
                "_occ_supported_approval_actions",
                new=supported_actions,
                create=True,
            ),
            patch.object(
                partner_class,
                "_occ_execute_approved_action",
                new=execute_approved_action,
                create=True,
            ),
        ):
            workflow, _version = self._create_published_workflow(
                action_key="confirm", auto_execute=True
            )
            source = self._create_source("failed-execution-block")
            requester_api = self._instance_api(self.requester)
            panel = requester_api._create_for_record(
                source._name,
                source.id,
                workflow_id=workflow.id,
                values={"action_key": "confirm"},
            )
            instance = self._runtime_instance(panel)
            requester_api.submit(instance.id)
            instance.invalidate_recordset()
            task = instance.task_ids.filtered(
                lambda item: item.state == "pending"
            ).ensure_one()
            self._instance_api(self.approver).approve_task(task.id)
            instance.invalidate_recordset()
            self.assertEqual(instance.state, "approved")
            self.assertEqual(instance.execution_state, "failed")

            with self.assertRaisesRegex(
                UserError, "An unfinished approval instance already exists"
            ):
                requester_api._create_for_record(
                    source._name,
                    source.id,
                    workflow_id=workflow.id,
                    values={"action_key": "confirm"},
                )

    def test_archived_workflow_keeps_readable_history_model_entry(self):
        workflow, version = self._create_published_workflow()
        source = self._create_source("archived-history")
        requester_api = self._instance_api(self.requester)
        panel = requester_api.create_for_record(
            source._name,
            source.id,
            workflow_id=workflow.id,
        )
        visible_instance = self._runtime_instance(panel)

        company_definition = self._simple_definition(assignee=self.outsider)
        company_workflow, company_version = self._create_published_workflow(
            definition=company_definition,
            model_name="res.company",
        )
        hidden_instance = self.env["occ.approval.instance"].sudo().create(
            {
                "name": "APR-HIDDEN-COMPANY-HISTORY",
                "company_id": self.company.id,
                "workflow_id": company_workflow.id,
                "workflow_version_id": company_version.id,
                "action_key": company_version.action_key,
                "source_model": "res.company",
                "source_res_id": self.company.id,
                "source_display_name": self.company.display_name,
                "requester_id": self.outsider.id,
                "participant_user_ids": [Command.set(self.outsider.ids)],
                "state": "approved",
                "last_decision": "approved",
                "completed_at": self.env.cr.now(),
            }
        )

        workflow_api = self.env["occ.approval.workflow"].with_user(self.manager)
        saved = workflow_api.save_designer_data(
            workflow.id,
            self._simple_definition(node_name="Unseen archived version"),
            expected_revision=workflow.draft_revision,
        )
        published_v2 = workflow_api.publish_designer_data(
            workflow.id,
            expected_revision=saved["revision"],
        )
        unseen_version = self.env["occ.approval.workflow.version"].browse(
            published_v2["version_id"]
        )
        workflow_api.archive_workflow(workflow.id)
        workflow_api.archive_workflow(company_workflow.id)

        version.with_user(self.requester).check_access("read")
        with self.assertRaises(AccessError):
            unseen_version.with_user(self.requester).check_access("read")

        active_models = {
            item["model"]
            for item in self.env["occ.approval.workflow"]
            .with_user(self.requester)
            .get_supported_models()
        }
        self.assertNotIn("res.partner", active_models)
        self.assertNotIn("res.company", active_models)

        grouped_models = {
            model_name
            for (model_name,) in requester_api._read_group([], ["source_model"])
        }
        self.assertIn("res.partner", grouped_models)
        self.assertNotIn("res.company", grouped_models)
        self.assertFalse(requester_api.search([("id", "=", hidden_instance.id)]))

        supported_models = {
            item["model"] for item in requester_api.get_supported_models()
        }
        self.assertIn("res.partner", supported_models)
        self.assertNotIn("res.company", supported_models)

        state = requester_api.get_record_state(source._name, source.id)
        self.assertTrue(state["enabled"])
        self.assertEqual(state["state"], "draft")
        self.assertEqual(state["instance_id"], visible_instance.id)
        archived_panel = requester_api.get_panel_data(
            res_model=source._name,
            res_id=source.id,
        )
        self.assertEqual(archived_panel["instance"]["id"], visible_instance.id)
        self.assertFalse(archived_panel["workflows"])
        self.assertEqual(version.workflow_id.id, workflow.id)

    def test_checksum_covers_full_snapshot_and_lifecycle_keeps_versions_stable(self):
        definition_v1 = self._simple_definition(node_name="Approval V1")
        workflow = self._create_draft_workflow(
            definition=definition_v1,
            applicability_domain=[["name", "ilike", "Approval"]],
        )
        workflow, version_v1 = self._publish_workflow(workflow)
        checksum_v1 = version_v1.checksum

        self.assertEqual(
            ApprovalDefinitionService.checksum_for_version(version_v1),
            checksum_v1,
        )
        snapshot = {
            "workflow_id": version_v1.workflow_id.id,
            "company_id": version_v1.company_id.id,
            "version": version_v1.version,
            "model_name": version_v1.model_name,
            "action_key": version_v1.action_key,
            "applicability_domain": version_v1.applicability_domain or [],
            "auto_execute": version_v1.auto_execute,
            "definition": version_v1.definition,
            "published_by_id": version_v1.published_by_id.id,
            "published_at": version_v1.published_at,
        }
        self.assertEqual(
            ApprovalDefinitionService.version_checksum(**snapshot),
            checksum_v1,
        )

        changed_definition = copy.deepcopy(version_v1.definition)
        changed_definition["nodes"][1]["name"] = "Checksum metadata change"
        metadata_changes = {
            "workflow_id": snapshot["workflow_id"] + 1,
            "company_id": snapshot["company_id"] + 1,
            "version": snapshot["version"] + 1,
            "model_name": "res.users",
            "action_key": "confirm",
            "applicability_domain": [["id", ">", 0]],
            "auto_execute": not snapshot["auto_execute"],
            "definition": changed_definition,
            "published_by_id": self.alternate.id,
            "published_at": snapshot["published_at"] + timedelta(seconds=1),
        }
        for field_name, changed_value in metadata_changes.items():
            changed_snapshot = {**snapshot, field_name: changed_value}
            with self.subTest(field_name=field_name):
                self.assertNotEqual(
                    ApprovalDefinitionService.version_checksum(**changed_snapshot),
                    checksum_v1,
                )

        workflow_api = self.env["occ.approval.workflow"].with_user(self.manager)
        workflow_api.archive_workflow(workflow.id)
        workflow.invalidate_recordset(["state", "active"])
        self.assertEqual(workflow.state, "archived")
        self.assertFalse(workflow.active)

        definition_v2 = self._simple_definition(node_name="Approval V2")
        with self.assertRaises(UserError):
            workflow_api.save_designer_data(
                workflow.id,
                definition_v2,
                expected_revision=workflow.draft_revision,
            )
        with self.assertRaises(UserError):
            workflow_api.publish_designer_data(
                workflow.id,
                expected_revision=workflow.draft_revision,
            )

        workflow_api.restore_workflow(workflow.id)
        workflow.invalidate_recordset(["state", "active", "draft_revision"])
        self.assertEqual(workflow.state, "published")
        self.assertTrue(workflow.active)

        saved = workflow_api.save_designer_data(
            workflow.id,
            definition_v2,
            expected_revision=workflow.draft_revision,
        )
        published_v2 = workflow_api.publish_designer_data(
            workflow.id,
            expected_revision=saved["revision"],
        )
        version_v2 = self.env["occ.approval.workflow.version"].browse(
            published_v2["version_id"]
        )
        version_v1.invalidate_recordset(["checksum", "definition"])
        self.assertEqual(version_v2.version, 2)
        self.assertNotEqual(version_v2.checksum, checksum_v1)
        self.assertEqual(version_v1.checksum, checksum_v1)
        self.assertEqual(
            ApprovalDefinitionService.checksum_for_version(version_v1),
            checksum_v1,
        )
