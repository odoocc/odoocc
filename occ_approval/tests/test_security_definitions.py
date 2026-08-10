from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user


class TestApprovalDefinitionSecurity(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env["res.company"].create({"name": "Approval Security B"})
        cls.source_model = cls.env["ir.model"]._get("res.partner")

        def make_user(login, group, company):
            return new_test_user(
                cls.env,
                login=login,
                groups=group,
                company_id=company.id,
                company_ids=[Command.set(company.ids)],
            )

        cls.approval_user = make_user(
            "occ_approval_security_user",
            "occ_approval.group_approval_user",
            cls.company_a,
        )
        cls.approval_manager = make_user(
            "occ_approval_security_manager",
            "occ_approval.group_approval_manager",
            cls.company_a,
        )
        cls.approval_technical = make_user(
            "occ_approval_security_technical",
            "occ_approval.group_approval_technical",
            cls.company_a,
        )
        cls.portal_user = make_user(
            "occ_approval_security_portal",
            "base.group_portal",
            cls.company_a,
        )

        cls.workflow_a_draft = cls._create_workflow(cls.company_a, "draft-a")
        cls.workflow_a_published = cls._create_workflow(
            cls.company_a, "published-a", state="published"
        )
        cls.workflow_b_published = cls._create_workflow(
            cls.company_b, "published-b", state="published"
        )

    @classmethod
    def _create_workflow(cls, company, suffix, **extra_values):
        requested_state = extra_values.pop("state", "draft")
        values = {
            "name": f"Approval {suffix}",
            "code": f"approval-{suffix}",
            "company_id": company.id,
            "model_id": cls.source_model.id,
        }
        values.update(extra_values)
        workflow = (
            cls.env["occ.approval.workflow"]
            .sudo()
            .with_company(company)
            .create(values)
        )
        if requested_state == "published":
            (
                cls.env["occ.approval.workflow"]
                .sudo()
                .with_company(company)
                .publish_designer_data(
                    workflow.id,
                    expected_revision=workflow.draft_revision,
                )
            )
            workflow.invalidate_recordset()
        return workflow

    def test_user_reads_only_published_workflows_in_active_company(self):
        workflows = self.env["occ.approval.workflow"].with_user(
            self.approval_user
        ).search([])
        self.assertIn(self.workflow_a_published, workflows)
        self.assertNotIn(self.workflow_a_draft, workflows)
        self.assertNotIn(self.workflow_b_published, workflows)

    def test_user_cannot_create_or_mutate_workflow(self):
        workflow_model = self.env["occ.approval.workflow"].with_user(
            self.approval_user
        )
        with self.assertRaises(AccessError):
            workflow_model.create(
                {
                    "name": "Forbidden workflow",
                    "company_id": self.company_a.id,
                    "model_id": self.source_model.id,
                }
            )
        with self.assertRaises(AccessError):
            self.workflow_a_published.with_user(self.approval_user).write(
                {"description": "Forbidden change"}
            )
        with self.assertRaises(AccessError):
            self.workflow_a_published.with_user(self.approval_user).unlink()

    def test_user_and_portal_cannot_read_approval_roles(self):
        role = self.env["occ.approval.role"].sudo().create(
            {
                "name": "Sensitive approval role",
                "company_id": self.company_a.id,
            }
        )
        with self.assertRaises(AccessError):
            role.with_user(self.approval_user).check_access("read")
        with self.assertRaises(AccessError):
            role.with_user(self.portal_user).check_access("read")

    def test_portal_has_no_workflow_access(self):
        with self.assertRaises(AccessError):
            self.env["occ.approval.workflow"].with_user(self.portal_user).search([])

    def test_manager_is_limited_to_active_companies(self):
        manager_model = self.env["occ.approval.workflow"].with_user(
            self.approval_manager
        )
        self.assertIn(self.workflow_a_draft, manager_model.search([]))
        self.assertNotIn(self.workflow_b_published, manager_model.search([]))
        with self.assertRaises(AccessError):
            manager_model.create(
                {
                    "name": "Forbidden cross-company workflow",
                    "company_id": self.company_b.id,
                    "model_id": self.source_model.id,
                }
            )

    def test_technical_admin_can_manage_definitions_cross_company(self):
        technical_model = self.env["occ.approval.workflow"].with_user(
            self.approval_technical
        )
        self.assertIn(self.workflow_b_published, technical_model.search([]))
        workflow = technical_model.create(
            {
                "name": "Technical cross-company workflow",
                "code": "technical-cross-company",
                "company_id": self.company_b.id,
                "model_id": self.source_model.id,
            }
        )
        self.assertEqual(workflow.company_id, self.company_b)

    def test_published_version_is_immutable(self):
        workflow = self._create_workflow(self.company_a, "immutable")
        result = self.env["occ.approval.workflow"].with_user(
            self.approval_manager
        ).publish_designer_data(workflow.id, expected_revision=workflow.draft_revision)
        version = self.env["occ.approval.workflow.version"].browse(
            result["version_id"]
        )
        with self.assertRaises(AccessError):
            version.with_user(self.approval_manager).write({"checksum": "tampered"})
        with self.assertRaises(AccessError):
            version.with_user(self.approval_manager).unlink()
