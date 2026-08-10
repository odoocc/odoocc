from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user


class TestApprovalRuntimeSecurity(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env["res.company"].create({"name": "Approval Runtime B"})
        cls.source_model = cls.env["ir.model"]._get("res.partner")

        def make_user(login, group, company):
            return new_test_user(
                cls.env,
                login=login,
                groups=group,
                company_id=company.id,
                company_ids=[Command.set(company.ids)],
            )

        cls.requester = make_user(
            "occ_runtime_requester",
            "occ_approval.group_approval_user",
            cls.company_a,
        )
        cls.participant = make_user(
            "occ_runtime_participant",
            "occ_approval.group_approval_user",
            cls.company_a,
        )
        cls.assignee = make_user(
            "occ_runtime_assignee",
            "occ_approval.group_approval_user",
            cls.company_a,
        )
        cls.outsider = make_user(
            "occ_runtime_outsider",
            "occ_approval.group_approval_user",
            cls.company_a,
        )
        cls.manager = make_user(
            "occ_runtime_manager",
            "occ_approval.group_approval_manager",
            cls.company_a,
        )
        cls.technical = make_user(
            "occ_runtime_technical",
            "occ_approval.group_approval_technical",
            cls.company_a,
        )
        cls.portal = make_user(
            "occ_runtime_portal", "base.group_portal", cls.company_a
        )

        cls.workflow_a, cls.version_a = cls._create_published_workflow(
            cls.company_a, "runtime-a"
        )
        cls.workflow_b, cls.version_b = cls._create_published_workflow(
            cls.company_b, "runtime-b"
        )
        cls.source_a = cls.env["res.partner"].sudo().create(
            {"name": "Approval runtime source A", "company_id": cls.company_a.id}
        )
        cls.source_b = cls.env["res.partner"].sudo().create(
            {"name": "Approval runtime source B", "company_id": cls.company_b.id}
        )
        cls.instance_a, cls.node_a, cls.task_a, cls.event_a = cls._create_runtime_chain(
            company=cls.company_a,
            workflow=cls.workflow_a,
            version=cls.version_a,
            source=cls.source_a,
            requester=cls.requester,
            participants=cls.participant,
            assignee=cls.assignee,
            suffix="a",
        )
        cls.instance_b, cls.node_b, cls.task_b, cls.event_b = cls._create_runtime_chain(
            company=cls.company_b,
            workflow=cls.workflow_b,
            version=cls.version_b,
            source=cls.source_b,
            requester=cls.env.ref("base.user_admin"),
            participants=cls.env.ref("base.user_admin"),
            assignee=cls.env.ref("base.user_admin"),
            suffix="b",
        )

    @classmethod
    def _create_published_workflow(cls, company, suffix):
        workflow = (
            cls.env["occ.approval.workflow"]
            .sudo()
            .with_company(company)
            .create(
                {
                    "name": f"Runtime workflow {suffix}",
                    "code": f"runtime-{suffix}",
                    "company_id": company.id,
                    "model_id": cls.source_model.id,
                }
            )
        )
        result = (
            cls.env["occ.approval.workflow"]
            .sudo()
            .with_company(company)
            .publish_designer_data(
                workflow.id, expected_revision=workflow.draft_revision
            )
        )
        return workflow, cls.env["occ.approval.workflow.version"].browse(
            result["version_id"]
        )

    @classmethod
    def _create_runtime_chain(
        cls,
        *,
        company,
        workflow,
        version,
        source,
        requester,
        participants,
        assignee,
        suffix,
    ):
        instance = cls.env["occ.approval.instance"].sudo().create(
            {
                "name": f"APR-RUNTIME-{suffix.upper()}",
                "company_id": company.id,
                "workflow_id": workflow.id,
                "workflow_version_id": version.id,
                "source_model": source._name,
                "source_res_id": source.id,
                "source_display_name": source.display_name,
                "requester_id": requester.id,
                "participant_user_ids": [Command.set(participants.ids)],
                "state": "running",
            }
        )
        node = cls.env["occ.approval.instance.node"].sudo().create(
            {
                "instance_id": instance.id,
                "company_id": company.id,
                "node_key": f"approval-{suffix}",
                "name": "Approval",
                "node_type": "approval",
                "sequence": 20,
                "definition": {
                    "id": f"approval-{suffix}",
                    "type": "approval",
                    "name": "Approval",
                },
                "assignment_type": "users",
                "approval_mode": "any",
                "state": "active",
                "attempt": 1,
                "visit_count": 1,
            }
        )
        task = cls.env["occ.approval.task"].sudo().create(
            {
                "instance_id": instance.id,
                "node_id": node.id,
                "company_id": company.id,
                "user_id": assignee.id,
                "task_kind": "approval",
                "attempt": 1,
            }
        )
        event = (
            cls.env["occ.approval.event"]
            .with_context(occ_approval_append_event=True)
            .sudo()
            .create(
                {
                    "instance_id": instance.id,
                    "node_id": node.id,
                    "task_id": task.id,
                    "company_id": company.id,
                    "sequence": 1,
                    "event_type": "test.created",
                    "actor_id": requester.id,
                }
            )
        )
        instance.sudo().write(
            {"current_node_id": node.id, "last_event_sequence": event.sequence}
        )
        return instance, node, task, event

    def assert_chain_readable(self, user):
        for record in (self.instance_a, self.node_a, self.task_a, self.event_a):
            record.with_user(user).check_access("read")

    def assert_chain_hidden(self, user):
        for record in (self.instance_a, self.node_a, self.task_a, self.event_a):
            with self.assertRaises(AccessError):
                record.with_user(user).check_access("read")

    def test_requester_participant_and_task_user_read_the_instance_chain(self):
        self.assert_chain_readable(self.requester)
        self.assert_chain_readable(self.participant)
        self.assert_chain_readable(self.assignee)

    def test_unrelated_user_and_portal_cannot_read_runtime_data(self):
        self.assert_chain_hidden(self.outsider)
        self.assert_chain_hidden(self.portal)

    def test_manager_reads_only_runtime_data_in_active_companies(self):
        self.assert_chain_readable(self.manager)
        with self.assertRaises(AccessError):
            self.instance_b.with_user(self.manager).check_access("read")

    def test_technical_admin_does_not_bypass_runtime_company_scope(self):
        self.assert_chain_readable(self.technical)
        with self.assertRaises(AccessError):
            self.instance_b.with_user(self.technical).check_access("read")

    def test_users_and_managers_cannot_mutate_runtime_records_directly(self):
        for user in (self.requester, self.manager):
            for record in (self.instance_a, self.node_a, self.task_a, self.event_a):
                with self.assertRaises(AccessError):
                    record.with_user(user).write({"write_date": False})
                with self.assertRaises(AccessError):
                    record.with_user(user).unlink()
        for user in (self.requester, self.manager):
            with self.assertRaises(AccessError):
                self.env["occ.approval.instance"].with_user(user).create({})
            with self.assertRaises(AccessError):
                self.env["occ.approval.event"].with_user(user).create({})

    def test_event_is_append_only_even_in_service_environment(self):
        with self.assertRaises(AccessError):
            self.event_a.sudo().write({"payload": {"tampered": True}})
        with self.assertRaises(AccessError):
            self.event_a.sudo().unlink()

