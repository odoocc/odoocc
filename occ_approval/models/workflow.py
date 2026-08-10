import ast
import hmac
import uuid

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain

from ..services.definition import ApprovalDefinitionService, VERSION_SNAPSHOT_SCHEMA


GROUP_USER = "occ_approval.group_approval_user"
GROUP_MANAGER = "occ_approval.group_approval_manager"
GROUP_TECHNICAL = "occ_approval.group_approval_technical"


class OccApprovalRole(models.Model):
    _name = "occ.approval.role"
    _table = "occ_approval_v2_role"
    _description = "Approval Role"
    _order = "name, id"
    _check_company_auto = True

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, default=lambda self: uuid.uuid4().hex, index=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
        ondelete="cascade",
    )
    user_ids = fields.Many2many(
        "res.users",
        "occ_approval_v2_role_user_rel",
        "role_id",
        "user_id",
        string="Users",
    )
    active = fields.Boolean(default=True)

    _company_code_unique = models.UniqueIndex(
        "(company_id, code)", "Approval role codes must be unique per company."
    )

    @api.model_create_multi
    def create(self, vals_list):
        self._check_manager()
        records = super().create(vals_list)
        records._validate_company_users()
        return records

    def write(self, vals):
        self._check_manager()
        result = super().write(vals)
        if "company_id" in vals or "user_ids" in vals:
            self._validate_company_users()
        return result

    def unlink(self):
        self._check_manager()
        return super().unlink()

    def _check_manager(self):
        if not (
            self.env.su
            or self.env.user.has_group(GROUP_MANAGER)
            or self.env.user.has_group(GROUP_TECHNICAL)
        ):
            raise AccessError(_("Only approval managers can maintain approval roles."))

    def _validate_company_users(self):
        for role in self:
            invalid = role.user_ids.filtered(
                lambda user: user.share
                or not user.active
                or role.company_id not in user.company_ids
            )
            if invalid:
                raise ValidationError(
                    _("All role users must be active internal users of the same company.")
                )


class OccApprovalWorkflow(models.Model):
    _name = "occ.approval.workflow"
    _description = "Approval Workflow"
    _order = "priority desc, name, id"
    _check_company_auto = True

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, default=lambda self: uuid.uuid4().hex, index=True)
    description = fields.Text(translate=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
        ondelete="cascade",
    )
    model_id = fields.Many2one(
        "ir.model",
        required=True,
        index=True,
        ondelete="cascade",
        domain="[('transient', '=', False), ('abstract', '=', False)]",
    )
    model_name = fields.Char(
        string="Technical Model Name", related="model_id.model", store=True, index=True
    )
    action_key = fields.Char(
        required=True,
        default="manual",
        index=True,
        help="Stable business action key used to select this workflow.",
    )
    priority = fields.Integer(default=10, index=True)
    applicability_domain = fields.Json(
        string="Applicability Domain Data", default=list, groups=GROUP_MANAGER
    )
    applicability_domain_expression = fields.Char(
        string="Applicability Domain",
        compute="_compute_applicability_domain_expression",
        inverse="_inverse_applicability_domain_expression",
        groups=GROUP_MANAGER,
    )
    auto_execute = fields.Boolean(
        default=False,
        help="Execute the source model's fixed _occ_execute_approved_action adapter after approval.",
        groups=GROUP_MANAGER,
    )
    active = fields.Boolean(default=True)
    state = fields.Selection(
        [("draft", "Draft"), ("published", "Published"), ("archived", "Archived")],
        default="draft",
        required=True,
        index=True,
    )
    draft_definition = fields.Json(
        default=lambda self: ApprovalDefinitionService.default_definition(),
        groups=GROUP_MANAGER,
    )
    draft_revision = fields.Integer(
        default=1, required=True, readonly=True, groups=GROUP_MANAGER
    )
    published_version_id = fields.Many2one(
        "occ.approval.workflow.version",
        readonly=True,
        copy=False,
        ondelete="restrict",
        check_company=True,
        groups=GROUP_MANAGER,
    )
    version_ids = fields.One2many(
        "occ.approval.workflow.version",
        "workflow_id",
        readonly=True,
        groups=GROUP_MANAGER,
    )
    instance_ids = fields.One2many(
        "occ.approval.instance", "workflow_id", readonly=True
    )

    _company_code_unique = models.UniqueIndex(
        "(company_id, code)", "Workflow codes must be unique per company."
    )
    _draft_revision_positive = models.Constraint(
        "CHECK(draft_revision > 0)", "The workflow draft revision must be positive."
    )
    _action_key_not_empty = models.Constraint(
        "CHECK(length(trim(action_key)) > 0)", "The workflow action key cannot be empty."
    )
    @api.model_create_multi
    def create(self, vals_list):
        self._check_manager()
        for vals in vals_list:
            action_key = vals.get("action_key") or "manual"
            if not isinstance(action_key, str) or not action_key.strip():
                raise ValidationError(_("The workflow action key cannot be empty."))
            vals["action_key"] = action_key.strip()
            vals["active"] = True
            vals["state"] = "draft"
            vals["draft_revision"] = 1
            vals.pop("published_version_id", None)
            company = self.env["res.company"].browse(
                vals.get("company_id") or self.env.company.id
            )
            model_id = vals.get("model_id")
            if model_id:
                model_name = self.env["ir.model"].sudo().browse(model_id).model
                vals["draft_definition"] = ApprovalDefinitionService(
                    self.env, company=company, source_model=model_name
                ).validate(
                    vals.get("draft_definition")
                    or ApprovalDefinitionService.default_definition()
                )
                self._validate_domain(model_name, vals.get("applicability_domain", []))
        return super().create(vals_list)

    def write(self, vals):
        self._check_manager()
        if "action_key" in vals:
            action_key = vals.get("action_key")
            if not isinstance(action_key, str) or not action_key.strip():
                raise ValidationError(_("The workflow action key cannot be empty."))
            vals["action_key"] = action_key.strip()
        protected = {"active", "published_version_id", "draft_revision", "state"}
        if protected.intersection(vals) and not (
            self.env.su and self.env.context.get("occ_approval_workflow_service")
        ):
            raise AccessError(_("Published workflow metadata can only be changed by the workflow service."))
        if {"model_id", "company_id", "action_key"}.intersection(vals) and self.version_ids:
            raise UserError(
                _("The company, source model and action key cannot be changed after publication.")
            )
        definition_fields = {
            "draft_definition",
            "model_id",
            "company_id",
            "applicability_domain",
        }
        if len(self) > 1 and definition_fields.intersection(vals):
            raise UserError(_("Workflow definitions must be edited one workflow at a time."))
        if self and definition_fields.intersection(vals):
            workflow = self.ensure_one()
            company = self.env["res.company"].browse(
                vals.get("company_id") or workflow.company_id.id
            )
            model_name = (
                self.env["ir.model"].sudo().browse(vals["model_id"]).model
                if vals.get("model_id")
                else workflow.model_name
            )
            definition = vals.get("draft_definition", workflow.draft_definition)
            applicability_domain = vals.get(
                "applicability_domain", workflow.applicability_domain or []
            )
            vals["draft_definition"] = ApprovalDefinitionService(
                self.env, company=company, source_model=model_name
            ).validate(definition)
            self._validate_domain(model_name, applicability_domain)
            vals["applicability_domain"] = applicability_domain
        return super().write(vals)

    @api.constrains("state", "active", "published_version_id")
    def _check_lifecycle_consistency(self):
        for workflow in self:
            if (workflow.state == "archived") != (not workflow.active):
                raise ValidationError(
                    _(
                        "Archived workflows must be inactive and usable workflows must be active."
                    )
                )
            if workflow.state == "published" and not workflow.published_version_id:
                raise ValidationError(
                    _("A published workflow must reference a published version.")
                )

    @api.depends("applicability_domain")
    def _compute_applicability_domain_expression(self):
        for workflow in self:
            workflow.applicability_domain_expression = repr(
                workflow.applicability_domain or []
            )

    def _inverse_applicability_domain_expression(self):
        for workflow in self:
            expression = workflow.applicability_domain_expression or "[]"
            try:
                domain = ast.literal_eval(expression)
            except (SyntaxError, ValueError) as error:
                raise ValidationError(
                    _("The applicability domain must be a literal domain list.")
                ) from error
            if not isinstance(domain, list):
                raise ValidationError(
                    _("The applicability domain must be a literal domain list.")
                )
            workflow.applicability_domain = domain

    def unlink(self):
        self._check_manager()
        if self.version_ids:
            raise UserError(_("Published workflows must be archived instead of deleted."))
        return super().unlink()

    def _check_manager(self):
        if not (
            self.env.su
            or self.env.user.has_group(GROUP_MANAGER)
            or self.env.user.has_group(GROUP_TECHNICAL)
        ):
            raise AccessError(_("Only approval managers can maintain workflows."))

    def _check_company_access(self):
        if self.env.su or self.env.user.has_group(GROUP_TECHNICAL):
            return
        allowed = self.env.companies
        if self.filtered(lambda workflow: workflow.company_id not in allowed):
            raise AccessError(_("The workflow belongs to an unavailable company."))

    def _lock_for_service(self, fields_to_refresh=None):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM occ_approval_workflow WHERE id = %s FOR UPDATE",
            (self.id,),
        )
        if not self.env.cr.fetchone():
            raise UserError(_("Workflow not found."))
        self.invalidate_recordset(
            fields_to_refresh
            or ["company_id", "active", "state", "published_version_id"]
        )
        return self

    def _validate_domain(self, model_name, domain):
        if not isinstance(domain, list):
            raise ValidationError(_("The applicability domain must be a native domain list."))
        try:
            Domain(domain).validate(self.env[model_name])
        except Exception as error:
            raise ValidationError(_("Invalid applicability domain: %s", error)) from error

    @api.model
    def get_supported_models(self, query=None, limit=100):
        if not (
            self.env.su
            or self.env.user.has_group(GROUP_USER)
            or self.env.user.has_group(GROUP_MANAGER)
            or self.env.user.has_group(GROUP_TECHNICAL)
        ):
            raise AccessError(_("Approval user access is required."))
        workflow_domain = [
            ("state", "=", "published"),
            ("active", "=", True),
            ("published_version_id", "!=", False),
        ]
        if not (self.env.su or self.env.user.has_group(GROUP_TECHNICAL)):
            workflow_domain.append(("company_id", "in", self.env.companies.ids))
        if query:
            workflow_domain += [
                "|",
                ("model_name", "ilike", query),
                ("model_id.name", "ilike", query),
            ]
        workflows = self.sudo().search(
            workflow_domain,
            order="model_id, priority desc, id",
            limit=min(max(int(limit or 100), 1), 500),
        )
        seen = set()
        result = []
        for workflow in workflows:
            if workflow.model_name in seen:
                continue
            seen.add(workflow.model_name)
            result.append(
                {
                    "id": workflow.model_id.id,
                    "name": workflow.model_id.name,
                    "model": workflow.model_name,
                }
            )
        return result

    @api.model
    def search_source_models(self, query=None, limit=100):
        self._check_manager()
        domain = [("transient", "=", False), ("abstract", "=", False)]
        if query:
            domain += ["|", ("name", "ilike", query), ("model", "ilike", query)]
        models_found = self.env["ir.model"].sudo().search(
            domain, order="name, model", limit=min(max(int(limit or 100), 1), 500)
        )
        excluded = {
            "occ.approval.workflow",
            "occ.approval.workflow.version",
            "occ.approval.role",
            "occ.approval.instance",
            "occ.approval.instance.node",
            "occ.approval.task",
            "occ.approval.event",
        }
        return [
            {"id": model.id, "name": model.name, "model": model.model}
            for model in models_found
            if model.model not in excluded
        ]

    @api.model
    def get_designer_data(self, workflow_id):
        self._check_manager()
        workflow = self.browse(workflow_id).exists()
        if not workflow:
            raise UserError(_("Workflow not found."))
        workflow._check_company_access()
        return {
            "id": workflow.id,
            "name": workflow.name,
            "code": workflow.code,
            "company_id": workflow.company_id.id,
            "model_id": workflow.model_id.id,
            "model_name": workflow.model_name,
            "action_key": workflow.action_key,
            "state": workflow.state,
            "revision": workflow.draft_revision,
            "definition": workflow.draft_definition,
            "published_version_id": workflow.published_version_id.id,
            "published_version": workflow.published_version_id.version,
            "auto_execute": workflow.auto_execute,
            "applicability_domain": workflow.applicability_domain or [],
        }

    @api.model
    def save_designer_data(self, workflow_id, definition, expected_revision=None):
        self._check_manager()
        workflow = self.browse(workflow_id).exists()
        if not workflow:
            raise UserError(_("Workflow not found."))
        workflow._check_company_access()
        self.env.cr.execute(
            "SELECT id FROM occ_approval_workflow WHERE id = %s FOR UPDATE",
            (workflow.id,),
        )
        workflow.invalidate_recordset(
            [
                "company_id",
                "model_id",
                "model_name",
                "active",
                "state",
                "draft_revision",
                "draft_definition",
            ]
        )
        workflow._check_company_access()
        if workflow.state == "archived" or not workflow.active:
            raise UserError(_("Restore the archived workflow before editing it."))
        if expected_revision is not None and workflow.draft_revision != int(expected_revision):
            raise UserError(_("The workflow draft was changed by another user. Reload it and retry."))
        normalized = ApprovalDefinitionService(
            self.env,
            company=workflow.company_id,
            source_model=workflow.model_name,
        ).validate(definition)
        workflow.with_context(occ_approval_workflow_service=True).sudo().write(
            {
                "draft_definition": normalized,
                "draft_revision": workflow.draft_revision + 1,
            }
        )
        return self.get_designer_data(workflow.id)

    @api.model
    def save_graph(self, workflow_id, values=None):
        values = values or {}
        return self.save_designer_data(
            workflow_id,
            values.get("graph", values.get("definition")),
            expected_revision=values.get("expected_revision"),
        )

    @api.model
    def publish_designer_data(self, workflow_id, expected_revision=None):
        self._check_manager()
        workflow = self.browse(workflow_id).exists()
        if not workflow:
            raise UserError(_("Workflow not found."))
        workflow._check_company_access()
        self.env.cr.execute(
            "SELECT id FROM occ_approval_workflow WHERE id = %s FOR UPDATE",
            (workflow.id,),
        )
        workflow.invalidate_recordset(
            [
                "company_id",
                "model_id",
                "model_name",
                "action_key",
                "applicability_domain",
                "auto_execute",
                "active",
                "state",
                "draft_revision",
                "draft_definition",
                "published_version_id",
            ]
        )
        workflow._check_company_access()
        if workflow.state == "archived" or not workflow.active:
            raise UserError(_("Restore the archived workflow before publishing it."))
        if expected_revision is not None and workflow.draft_revision != int(expected_revision):
            raise UserError(_("The workflow draft was changed by another user. Reload it and retry."))

        validator = ApprovalDefinitionService(
            self.env,
            company=workflow.company_id,
            source_model=workflow.model_name,
        )
        self._validate_domain(
            workflow.model_name, workflow.applicability_domain or []
        )
        definition = validator.validate(workflow.draft_definition)
        if workflow.auto_execute:
            source_model = self.env[workflow.model_name]
            supported_action_method = getattr(
                source_model, "_occ_supported_approval_actions", None
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
            if workflow.action_key not in supported_actions:
                raise ValidationError(
                    _(
                        "Model %(model)s does not explicitly support auto execution for action %(action)s.",
                        model=workflow.model_name,
                        action=workflow.action_key,
                    )
                )
            if not callable(
                getattr(source_model, "_occ_execute_approved_action", None)
            ):
                raise ValidationError(
                    _("The business model has no approved-action connector.")
                )

        latest = self.env["occ.approval.workflow.version"].sudo().search(
            [("workflow_id", "=", workflow.id)], order="version desc", limit=1
        )
        next_version = (latest.version or 0) + 1
        published_at = fields.Datetime.now()
        checksum = validator.version_checksum(
            workflow_id=workflow.id,
            company_id=workflow.company_id.id,
            version=next_version,
            model_name=workflow.model_name,
            action_key=workflow.action_key,
            applicability_domain=workflow.applicability_domain or [],
            auto_execute=workflow.auto_execute,
            definition=definition,
            published_by_id=self.env.user.id,
            published_at=published_at,
        )
        version = self.env["occ.approval.workflow.version"].with_context(
            occ_approval_publish=True
        ).sudo().create(
            {
                "workflow_id": workflow.id,
                "company_id": workflow.company_id.id,
                "version": next_version,
                "model_name": workflow.model_name,
                "action_key": workflow.action_key,
                "applicability_domain": workflow.applicability_domain or [],
                "auto_execute": workflow.auto_execute,
                "definition": definition,
                "checksum": checksum,
                "checksum_schema": VERSION_SNAPSHOT_SCHEMA,
                "published_by_id": self.env.user.id,
                "published_at": published_at,
            }
        )
        workflow.with_context(occ_approval_workflow_service=True).sudo().write(
            {"published_version_id": version.id, "state": "published"}
        )
        return {
            "workflow_id": workflow.id,
            "version_id": version.id,
            "version": version.version,
            "checksum": version.checksum,
        }

    @api.model
    def publish(self, workflow_id, values=None):
        values = values or {}
        return self.publish_designer_data(
            workflow_id, expected_revision=values.get("expected_revision")
        )

    @api.model
    def archive_workflow(self, workflow_id):
        self._check_manager()
        workflow = self.browse(workflow_id).exists()
        if not workflow:
            raise UserError(_("Workflow not found."))
        workflow._check_company_access()
        workflow._lock_for_service()
        workflow._check_company_access()
        workflow.with_context(occ_approval_workflow_service=True).sudo().write(
            {"state": "archived", "active": False}
        )
        return True

    @api.model
    def restore_workflow(self, workflow_id):
        self._check_manager()
        workflow = self.with_context(active_test=False).browse(workflow_id).exists()
        if not workflow:
            raise UserError(_("Workflow not found."))
        workflow._check_company_access()
        workflow._lock_for_service()
        workflow._check_company_access()
        state = "published" if workflow.published_version_id else "draft"
        workflow.with_context(occ_approval_workflow_service=True).sudo().write(
            {"state": state, "active": True}
        )
        return True

    def action_archive(self):
        self._check_manager()
        for workflow in self:
            self.archive_workflow(workflow.id)
        return True

    def action_unarchive(self):
        self._check_manager()
        for workflow in self:
            self.restore_workflow(workflow.id)
        return True


class OccApprovalWorkflowVersion(models.Model):
    _name = "occ.approval.workflow.version"
    _description = "Published Approval Workflow Version"
    _order = "workflow_id, version desc"
    _check_company_auto = True

    workflow_id = fields.Many2one(
        "occ.approval.workflow",
        required=True,
        index=True,
        ondelete="restrict",
        check_company=True,
    )
    company_id = fields.Many2one(
        "res.company", required=True, index=True, ondelete="restrict"
    )
    version = fields.Integer(required=True)
    model_name = fields.Char(required=True, index=True)
    action_key = fields.Char(required=True, default="manual", index=True)
    applicability_domain = fields.Json(default=list, readonly=True)
    auto_execute = fields.Boolean(default=False, readonly=True)
    definition = fields.Json(required=True)
    checksum = fields.Char(required=True, index=True)
    checksum_schema = fields.Integer(
        required=True,
        default=1,
        readonly=True,
        help="1 protects legacy definition JSON; 2 protects the complete version snapshot.",
    )
    published_by_id = fields.Many2one(
        "res.users", required=True, ondelete="restrict", index=True
    )
    published_at = fields.Datetime(required=True, index=True)
    instance_ids = fields.One2many(
        "occ.approval.instance", "workflow_version_id", readonly=True
    )

    _workflow_version_unique = models.UniqueIndex(
        "(workflow_id, version)", "Workflow version numbers must be unique."
    )
    _version_positive = models.Constraint(
        "CHECK(version > 0)", "Workflow versions must be positive."
    )
    _checksum_sha256 = models.Constraint(
        "CHECK(length(checksum) = 64)", "Workflow version checksums must be SHA-256 digests."
    )
    _checksum_schema_supported = models.Constraint(
        "CHECK(checksum_schema IN (1, 2))", "Unsupported workflow checksum schema."
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not (self.env.su and self.env.context.get("occ_approval_publish")):
            raise AccessError(_("Workflow versions can only be created by the publish service."))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_("Published workflow versions are immutable."))

    def unlink(self):
        if self.env.context.get("module_uninstall"):
            return super().unlink()
        raise AccessError(_("Published workflow versions are immutable."))

    def _assert_integrity(self):
        for version in self:
            expected = ApprovalDefinitionService.checksum_for_version(version)
            if not hmac.compare_digest(version.checksum or "", expected):
                raise ValidationError(
                    _(
                        "The published workflow version failed its integrity check. Contact an approval administrator."
                    )
                )
        return True
