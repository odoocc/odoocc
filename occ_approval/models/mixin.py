from odoo import _, api, fields, models
from odoo.exceptions import UserError


class OccApprovalSourceMixin(models.AbstractModel):
    _name = "occ.approval.source.mixin"
    _description = "Approval Source Integration Mixin"

    occ_approval_instance_id = fields.Many2one(
        "occ.approval.instance",
        string="Current Approval",
        compute="_compute_occ_approval_info",
        compute_sudo=False,
    )
    occ_approval_state = fields.Selection(
        [
            ("none", "No Approval"),
            ("draft", "Draft"),
            ("running", "Running"),
            ("rework", "Rework"),
            ("approved", "Approved"),
            ("cancelled", "Cancelled"),
        ],
        compute="_compute_occ_approval_info",
        compute_sudo=False,
    )

    def _compute_occ_approval_info(self):
        instance_model = self.env["occ.approval.instance"]
        for record in self:
            instance = instance_model.browse()
            if record.id and self.env.user.has_group(
                "occ_approval.group_approval_user"
            ):
                instance = instance_model.search(
                    [
                        ("source_model", "=", record._name),
                        ("source_res_id", "=", record.id),
                    ],
                    order="id desc",
                    limit=1,
                )
            record.occ_approval_instance_id = instance
            record.occ_approval_state = instance.state if instance else "none"

    def _occ_get_approval_state(self):
        self.ensure_one()
        return self.env["occ.approval.instance"].get_record_state(
            self._name, self.id
        )

    def _occ_create_approval(self, *, action_key="manual", workflow_id=None):
        self.ensure_one()
        return self.env["occ.approval.instance"]._create_for_record(
            self._name,
            self.id,
            workflow_id=workflow_id,
            values={"action_key": action_key},
        )

    def action_occ_create_approval(self):
        self.ensure_one()
        self._occ_create_approval()
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_occ_open_approval(self):
        self.ensure_one()
        state = self._occ_get_approval_state()
        instance_id = state.get("instance_id")
        if not instance_id:
            raise UserError(_("No approval instance exists for this record."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Approval"),
            "res_model": "occ.approval.instance",
            "res_id": instance_id,
            "view_mode": "form",
            "target": "current",
        }

    def _occ_execute_approved_action(self, instance):
        """Fixed private adapter; connectors must explicitly override it."""
        raise UserError(
            _(
                "Model %s has not implemented the approved-action adapter.",
                self._name,
            )
        )

    def _occ_assert_approved_execution(self, *, action_key):
        """Validate the server-only capability before reusing a public action."""
        self.ensure_one()
        return self.env["occ.approval.instance"]._assert_execution_capability(
            self, action_key
        )

    @api.model
    def _occ_supported_approval_actions(self):
        """Return action keys this connector can execute after approval.

        Connectors enabling ``auto_execute`` must explicitly override this
        method and return an immutable collection such as ``frozenset``.
        """
        return frozenset()
